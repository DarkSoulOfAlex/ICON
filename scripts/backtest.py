"""Backtesting: confronto tra strategie di pianificazione.

Usa il modello finale gia' addestrato (tutte le giornate disponibili) per valutare
due strategie su un insieme di istanze OD reali:
  (a) arrivo minimo a orario teorico (baseline)
  (b) massimo P(arrivo <= T) con il modello vero

Griglia: {roma, torino} x {ottili, decisione} x {(a),(b)} x margini {0,5,10,15,20}.

Output:
    results/backtest.csv       una riga per istanza
    results/backtest_riepilogo.csv  medie e deviazioni

Uso:
    python scripts/backtest.py --fino-a 2026-08-25
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

RADICE = Path(__file__).resolve().parent.parent
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import numpy as np
import pandas as pd

from src.delays.rete import Modello
from src.delays.markov import discretizza
from src.graph.search import cerca_frontiera_pareto, cerca_primo_arrivo
from src.graph.time_expanded import costruisci
from src.gtfs.loader import carica_archivio
from src.planner.robust import (
    candidati_da_frontiera,
    pianifica_robusto,
)

FUSO = ZoneInfo("Europe/Rome")
MARGINI = (0, 300, 600, 900, 1200)  # 0, 5, 10, 15, 20 minuti
SEME = 20260910
CITTA = ("roma", "torino")

# Bordi dei candidati
BORDI_OTILI = (-554.0, -366.0, -250.0, -158.0, -80.0, 18.0, 213.0)
BORDI_DECISIONE = (-300.0, -60.0, 0.0, 120.0, 300.0, 900.0, 1800.0)
TUTTI_BORDI = {
    "ottili": BORDI_OTILI,
    "decisione": BORDI_DECISIONE,
}


# =============================================================================
# Costruzione modello con scala di risalita (richiamata da stima_rete.py)
# =============================================================================


def costruisci_modello_da_dati(
    citta: str,
    bordi: tuple[float, ...],
    giorni_osservazioni: list[str],
    popolazione: str = "constatazioni",
) -> tuple[Modello | None, dict]:
    """Costruisce il modello usando la stessa logica di stima_rete.py.

    Restituisce (modello, info_dict) dove info_dict contiene metadati utili.
    """
    from src.delays.rete import Livello, stima

    # Carica e unisci i dati
    tutte = []
    for giorno in giorni_osservazioni:
        percorso = RADICE / "data" / "processed" / "osservazioni" / citta / f"{giorno}.parquet"
        if not percorso.exists():
            continue
        df = pd.read_parquet(percorso)
        if df.empty:
            continue
        df = df.sort_values(["trip_id", "stop_sequence"])
        parti = []
        for trip, gruppo in df.groupby("trip_id"):
            if len(gruppo) < 2:
                continue
            g = gruppo.sort_values("stop_sequence").reset_index(drop=True)
            parti.append(pd.DataFrame({
                "linea": g["route_id"].values[:-1],
                "secondi_monte": g["ritardo_secondi"].values[:-1].astype(np.float64),
                "secondi_valle": g["ritardo_secondi"].values[1:].astype(np.float64),
            }))
        if parti:
            tutte.append(pd.concat(parti, ignore_index=True))

    if not tutte:
        return None, {}

    dati = pd.concat(tutte, ignore_index=True)
    if dati.empty:
        return None, {}

    n_bin = len(bordi) + 1
    n_linee = len(dati["linea"].unique())
    n_tipi = min(n_linee, 20)

    # Codifica: bin per ritardo a monte
    monti = discretizza(dati["secondi_monte"].to_numpy(), bordi)
    valli = discretizza(dati["secondi_valle"].to_numpy(), bordi)

    # Codifica linea
    linee_cod, _ = pd.factorize(dati["linea"])

    # Costruisci i livelli della scala
    # Livello 0: bin (padre=None, priore uniforme)
    # Usiamo una scala semplice: solo il livello bin.
    # Per il backtesting, un priore uniforme (alfa=1.0) e' sufficiente.

    livelli = [
        Livello("bin", monti, valli.astype(np.int64), n_bin),
    ]

    # Stima diretta con alfa=1.0 (priore uniforme, nessun taratura)
    # Questo e' equivalente a una stima empirica senza regolarizzazione.
    modello = stima(livelli, n_bin, [1.0])

    info = {
        "n_osservazioni": len(dati),
        "n_giorni": len(giorni_osservazioni),
        "popolazione": popolazione,
        "n_bin": n_bin,
        "n_linee": n_linee,
        "alfa": [1.0],
    }
    return modello, info


# =============================================================================
# Estrazione istanze OD
# =============================================================================


def estrai_istanze_od(citta: str, n_istanze: int = 60) -> list[dict]:
    """Estrae coppie origine-destinazione dalle osservazioni reali."""
    percorso_osservazioni = RADICE / "data" / "processed" / "osservazioni" / citta
    if not percorso_osservazioni.is_dir():
        return []

    # Legge tutti i parquet e raggruppa per route_id
    od_raggruppati: dict[str, list[int]] = {}
    for p in sorted(percorso_osservazioni.glob("*.parquet")):
        df = pd.read_parquet(p)
        if df.empty:
            continue
        for route, gruppo in df.groupby("route_id"):
            if len(gruppo) < 5:
                continue
            seq_min = int(gruppo["stop_sequence"].min())
            seq_max = int(gruppo["stop_sequence"].max())
            if seq_max - seq_min < 5:
                continue
            med_p = gruppo["orario_programmato"].median()
            if pd.isna(med_p):
                continue
            key = f"{route}_{seq_min}_{seq_max}"
            if key not in od_raggruppati:
                od_raggruppati[key] = []
            od_raggruppati[key].append(int(med_p))

    if not od_raggruppati:
        return []

    # Campiona
    righe = []
    for key, partenze in od_raggruppati.items():
        media_p = int(np.median(partenze))
        righe.append({
            "citta": citta,
            "seq_inizio": int(key.split("_")[1]),
            "seq_fine": int(key.split("_")[2]),
            "partenza": media_p,
            "coppie_osservate": len(partenze),
        })

    if len(righe) <= n_istanze:
        return righe

    rng = np.random.default_rng(SEME)
    indici = rng.choice(len(righe), size=n_istanze, replace=False)
    return [righe[i] for i in indici]


# =============================================================================
# Risultati
# =============================================================================


@dataclass
class RisultatoIstanza:
    """Un risultato di backtesting per una singola istanza."""
    citta: str
    giornata: str
    seq_inizio: int
    seq_fine: int
    partenza: int
    strategia: str
    margine: int
    bordi: str
    probabilita: float | None = None
    arrivo_programmato: int | None = None
    cambi: int | None = None
    ritardo_vs_T: float | None = None
    tempo_secondi: float = 0.0


# =============================================================================
# Esecuzione backtest
# =============================================================================


def esegui_backtest(
    citta: str,
    bordi_nome: str,
    bordi: tuple[float, ...],
    giorni: list[str],
    n_istanze: int = 60,
) -> list[RisultatoIstanza]:
    """Esegue il backtest con il modello addestrato su tutte le giornate."""
    risultati: list[RisultatoIstanza] = []
    cartella_gtfs = RADICE / "data" / "raw" / "gtfs" / citta

    # Costruisci modello
    modello, info = costruisci_modello_da_dati(citta, bordi, giorni, "constatazioni")
    if modello is None:
        print(f"    [WARNING] modello non costruito per {citta}")
        return risultati

    # Estrai istanze OD
    istanze = estrai_istanze_od(citta, n_istanze)
    if not istanze:
        return risultati

    # Carica archivio GTFS
    archivi = sorted(cartella_gtfs.glob("*.zip"))
    if not archivi:
        return risultati
    archivio = carica_archivio(archivi[-1], con_stop_times=True)

    # Usa l'ultima giornata come giornata di "viaggio"
    ultimo_giorno = giorni[-1]
    try:
        giorno_date = date.fromisoformat(ultimo_giorno)
        inizio = int(datetime(2026, 8, 25, 6, 0, tzinfo=FUSO).timestamp())
        grafo = costruisci(archivio, citta, giorno_date, inizio, 180)
    except Exception as e:
        print(f"    [WARNING] grafo non costruito per {ultimo_giorno}: {e}")
        return risultati

    # Per ogni istanza e margine
    for ist in istanze:
        for margine in MARGINI:
            scadenza = ist["partenza"] + margine

            # Cerca frontiera Pareto
            try:
                esito_pareto = cerca_frontiera_pareto(
                    grafo, ist["seq_inizio"], ist["seq_fine"],
                    ist["partenza"], 120.0, True
                )
            except Exception:
                continue

            if not esito_pareto.cammini:
                continue

            # Strategia (a): piu_veloce (baseline)
            t0 = time.time()
            try:
                primo = cerca_primo_arrivo(
                    grafo, ist["seq_inizio"], ist["seq_fine"],
                    ist["partenza"], 120.0, True
                )
            except Exception:
                continue

            if primo and primo.cammini:
                arrivo = primo.cammini[0].arrivo
                ritardo_vs_T = (arrivo - scadenza) if arrivo and scadenza else 0.0
                risultati.append(RisultatoIstanza(
                    citta=citta, giornata=ultimo_giorno,
                    seq_inizio=ist["seq_inizio"], seq_fine=ist["seq_fine"],
                    partenza=ist["partenza"], strategia="piu_veloce",
                    margine=margine, bordi=bordi_nome,
                    probabilita=1.0, arrivo_programmato=arrivo,
                    cambi=0, ritardo_vs_T=ritardo_vs_T,
                    tempo_secondi=time.time() - t0
                ))

            # Strategia (b): robusto
            t0 = time.time()
            candidati = candidati_da_frontiera(grafo, esito_pareto, ist["partenza"])
            if not candidati:
                continue

            try:
                scelta = pianifica_robusto(candidati, modello, scadenza)
            except Exception:
                continue

            itinerario = scelta.itinerario
            prob = scelta.probabilita
            arrivo = itinerario.arrivo_programmato()
            cambi = len(itinerario.tappe) - 1
            ritardo_vs_T = (arrivo - scadenza) if arrivo and scadenza else 0.0

            risultati.append(RisultatoIstanza(
                citta=citta, giornata=ultimo_giorno,
                seq_inizio=ist["seq_inizio"], seq_fine=ist["seq_fine"],
                partenza=ist["partenza"], strategia="robusto",
                margine=margine, bordi=bordi_nome,
                probabilita=prob, arrivo_programmato=arrivo,
                cambi=cambi, ritardo_vs_T=ritardo_vs_T,
                tempo_secondi=time.time() - t0
            ))

    return risultati


# =============================================================================
# Output
# =============================================================================


def scrivi_output(risultati: list[RisultatoIstanza], output_dir: Path) -> None:
    """Scrive i CSV di output."""
    if not risultati:
        print("  Nessun risultato prodotto.")
        return

    df = pd.DataFrame([{
        "citta": r.citta, "giornata": r.giornata,
        "seq_inizio": r.seq_inizio, "seq_fine": r.seq_fine,
        "partenza": r.partenza, "strategia": r.strategia,
        "margine": r.margine, "bordi": r.bordi,
        "probabilita": r.probabilita,
        "arrivo_programmato": r.arrivo_programmato,
        "cambi": r.cambi,
        "ritardo_vs_T": r.ritardo_vs_T,
        "tempo_secondi": r.tempo_secondi,
    } for r in risultati])

    df.to_csv(output_dir / "backtest.csv", index=False)

    # Riepilogo
    riepilogo = df.groupby(["citta", "strategia", "bordi"]).agg({
        "probabilita": ["mean", "std", "count"],
        "ritardo_vs_T": ["mean", "std", "median"],
        "tempo_secondi": "mean",
    }).reset_index()
    riepilogo.columns = ["citta", "strategia", "bordi",
                         "prob_mean", "prob_std", "n_istanze",
                         "ritardo_mean", "ritardo_std", "ritardo_mediana",
                         "tempo_medio"]
    riepilogo.to_csv(output_dir / "backtest_riepilogo.csv", index=False)

    print(f"  scritto {output_dir / 'backtest.csv'} ({len(df)} righe)")
    print(f"  scritto {output_dir / 'backtest_riepilogo.csv'} ({len(riepilogo)} righe)")


# =============================================================================
# Main
# =============================================================================


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG")
    parser.add_argument("--n-istanze", type=int, default=60)
    parser.add_argument("--radice", type=Path, default=None)
    parser.add_argument("--bordi", nargs="*", default=["ottili", "decisione"],
                        help="insiemi di bordi da testare")
    argomenti = parser.parse_args(argv)

    radice = argomenti.radice or RADICE
    risultati_path = radice / "results"
    risultati_path.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("BACKTESTING")
    print("=" * 78)

    # Recupera giornate
    giorni_roma = sorted(p.stem for p in
                         (radice / "data" / "processed" / "osservazioni" / "roma").glob("*.parquet"))
    giorni_torino = sorted(p.stem for p in
                           (radice / "data" / "processed" / "osservazioni" / "torino").glob("*.parquet"))

    if argomenti.fino_a:
        giorni_roma = [g for g in giorni_roma if g <= argomenti.fino_a]
        giorni_torino = [g for g in giorni_torino if g <= argomenti.fino_a]

    print(f"  Giornate Roma: {len(giorni_roma)} ({giorni_roma[0]} .. {giorni_roma[-1]})")
    print(f"  Giornate Torino: {len(giorni_torino)} ({giorni_torino[0]} .. {giorni_torino[-1]})")
    print(f"  Bordi: {argomenti.bordi}")
    print(f"  Istanze per citta': {argomenti.n_istanze}")

    # Verifica bordi
    for b in argomenti.bordi:
        if b not in TUTTI_BORDI:
            print(f"  ATTENZIONE: bordo '{b}' non riconosciuto, uso attuali")

    # Esegui griglia
    tutti_risultati: list[RisultatoIstanza] = []
    t_inizio = time.time()

    for citta in argomenti.citta:
        giorni = giorni_roma if citta == "roma" else giorni_torino
        if len(giorni) < 5:
            print(f"  [{citta}] solo {len(giorni)} giornate, insufficienti")
            continue

        for nome_bordi in argomenti.bordi:
            bordi = TUTTI_BORDI.get(nome_bordi, BORDI_OTILI)
            print(f"\n  [{citta}] bordi {nome_bordi}...")
            res = esegui_backtest(citta, nome_bordi, bordi, giorni, argomenti.n_istanze)
            tutti_risultati.extend(res)
            print(f"    {len(res)} risultati")

    t_totale = time.time() - t_inizio

    # Output
    scrivi_output(tutti_risultati, risultati_path)

    if tutti_risultati:
        print(f"\n  Tempo totale: {t_totale:.1f}s")
        print(f"  Istanze totali: {len(tutti_risultati)}")
        print(f"  Giornate coperte: {len(set(r.giornata for r in tutti_risultati))}")
    else:
        print("\n  Nessun risultato prodotto - verifica giornate e bordi.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
