"""Quante celle della matrice di transizione le constatazioni riescono a coprire.

E' la misura che decide l'ordine della scala di risalita, e va fatta prima di
stimare qualunque cosa. La voce 61 stabilisce che le constatazioni vengono prima
delle previsioni, perche' su Roma il 23% delle transizioni fra previsioni e'
l'identita' - valori non ricalcolati, quindi copie e non informazione - contro il
4,7% fra constatazioni. Resta da sapere **fin dove** le constatazioni arrivino: se
coprissero il livello piu' fine, la questione dell'ordine non si porrebbe; se
coprissero solo i livelli grossolani, il modello sara' per tipo di linea e non per
linea, e va dichiarato.

**Che cosa e' una cella.** La tabella stima ``P(R0 | contesto, R-1)``, quindi una
cella e' una combinazione di contesto e bin del ritardo a monte, e deve contenere
abbastanza osservazioni da stimare una distribuzione su otto valori. Si riporta la
copertura a tre soglie, cinque venti e cinquanta osservazioni per cella, perche'
la soglia non e' un fatto ma una scelta e il lettore deve poterne vedere l'effetto.

**Due letture della copertura, e la seconda conta di piu'.** La quota di **celle**
coperte dice quanto della tabella si riesce a stimare al livello fine; la quota di
**osservazioni** che cadono in celle coperte dice quanta parte del traffico reale
viene servita da quel livello. Le due divergono quando poche celle molto popolose
convivono con molte celle vuote, che e' esattamente cio' che una rete di trasporto
produce: poche linee portanti e molte marginali.

    python scripts/copertura_constatazioni.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from src.delays.markov import BORDI_OTTO, discretizza  # noqa: E402
from src.gtfs.indice_statico import carica_indice, versione_valida  # noqa: E402
from src.gtfs.loader import carica_archivio  # noqa: E402

CITTA = ("roma", "torino")
FUSO = "Europe/Rome"
FASCE_ORARIE = (6, 9, 12, 15, 20)
COLONNE = ["service_date", "trip_id", "route_id", "stop_sequence", "ritardo_secondi",
           "orario_programmato", "timestamp_feed"]
SOGLIE = (5, 20, 50)
RISULTATI = RADICE / "results"

LIVELLI = (
    "linea x fascia x giorno",
    "tipo linea x fascia x giorno",
    "tipo linea x fascia",
    "tipo linea",
    "citta'",
)


def tipi_di_linea(citta: str, cartella_gtfs: Path) -> dict[str, int]:
    """Corrispondenza linea -> tipo di veicolo, dall'archivio piu' recente."""
    indice = carica_indice(cartella_gtfs / citta / "index.json", citta)
    date = sorted(indice.get("giorni", {}))
    for sd in reversed(date):
        voce = versione_valida(indice, sd)
        if voce is None:
            continue
        archivio = carica_archivio(cartella_gtfs / citta / voce["file"])
        return {str(r): int(t)
                for r, t in archivio.routes[["route_id", "route_type"]].itertuples(index=False)}
    return {}


def _contesti(linea: np.ndarray, tipo: np.ndarray, fascia: np.ndarray,
              giorno: np.ndarray) -> dict[str, np.ndarray]:
    """Il codice di contesto a ciascun livello della scala."""
    nf, ng = len(FASCE_ORARIE) + 1, 3
    return {
        LIVELLI[0]: (linea * nf + fascia) * ng + giorno,
        LIVELLI[1]: (tipo * nf + fascia) * ng + giorno,
        LIVELLI[2]: tipo * nf + fascia,
        LIVELLI[3]: tipo,
        LIVELLI[4]: np.zeros(linea.size, dtype=np.int64),
    }


class Conteggi:
    """Conteggi per cella a ciascun livello, separati per tipo di dato."""

    def __init__(self) -> None:
        self.constatazioni: dict[str, Counter] = {l: Counter() for l in LIVELLI}
        self.tutte: dict[str, Counter] = {l: Counter() for l in LIVELLI}
        self.coppie = 0
        self.coppie_constatate = 0

    def aggiungi(self, contesti: dict[str, np.ndarray], bin_monte: np.ndarray,
                 constatata: np.ndarray) -> None:
        self.coppie += int(bin_monte.size)
        self.coppie_constatate += int(constatata.sum())
        for livello, codice in contesti.items():
            cella = codice * 8 + bin_monte
            self.tutte[livello].update(cella.tolist())
            self.constatazioni[livello].update(cella[constatata].tolist())


def coppie_di_un_giorno(percorso: Path, tipo_di: dict[str, int], conteggi: Conteggi,
                        linee: dict[str, int]) -> None:
    """Accumula i conteggi di una giornata, senza conservare le coppie."""
    tabella = pq.read_table(percorso, columns=COLONNE)
    n = tabella.num_rows
    if n == 0:
        return
    sd = pd.factorize(tabella.column("service_date").to_pandas(), sort=False)[0]
    trip = pd.factorize(tabella.column("trip_id").to_pandas(), sort=False)[0]
    codice = sd.astype(np.int64) * (int(trip.max()) + 1) + trip
    seq = tabella.column("stop_sequence").to_numpy().astype(np.int64)
    rit = tabella.column("ritardo_secondi").to_numpy().astype(np.float64)
    prog = tabella.column("orario_programmato").to_pandas().to_numpy(dtype="float64",
                                                                    na_value=np.nan)
    feed = tabella.column("timestamp_feed").to_numpy().astype(np.float64)
    testo_linea = tabella.column("route_id").to_pandas().to_numpy()
    del tabella

    # Codice di linea stabile fra le giornate: un indice per file non lo sarebbe,
    # e i conteggi di giorni diversi finirebbero in celle diverse.
    for nome in pd.unique(testo_linea):
        linee.setdefault(str(nome), len(linee))
    linea = np.fromiter((linee[str(x)] for x in testo_linea), dtype=np.int64, count=n)
    tipo = np.fromiter((tipo_di.get(str(x), 3) for x in testo_linea), dtype=np.int64, count=n)

    ordine = np.lexsort((feed, seq, codice))
    codice, seq, rit, prog, feed, linea, tipo = (
        a[ordine] for a in (codice, seq, rit, prog, feed, linea, tipo))
    ultimo = np.empty(n, dtype=bool)
    ultimo[-1] = True
    ultimo[:-1] = (codice[1:] != codice[:-1]) | (seq[1:] != seq[:-1])
    codice, seq, rit, prog, feed, linea, tipo = (
        a[ultimo] for a in (codice, seq, rit, prog, feed, linea, tipo))
    if codice.size < 2:
        return

    anticipo = (prog + rit) - feed
    stessa = codice[1:] == codice[:-1]
    contigue = seq[1:] - seq[:-1] == 1
    valida = stessa & contigue & np.isfinite(anticipo[:-1]) & np.isfinite(anticipo[1:])
    if not valida.any():
        return

    quando = pd.to_datetime(prog[1:][valida], unit="s", utc=True).tz_convert(FUSO)
    fascia = np.searchsorted(np.asarray(FASCE_ORARIE), quando.hour.to_numpy(), side="right")
    settimana = quando.dayofweek.to_numpy()
    tipo_giorno = np.where(settimana < 5, 0, np.where(settimana == 5, 1, 2))

    contesti = _contesti(linea[1:][valida], tipo[1:][valida], fascia, tipo_giorno)
    bin_monte = discretizza(rit[:-1][valida], BORDI_OTTO)
    # Una coppia e' constatata quando **entrambe** le osservazioni lo sono: il
    # ritardo a monte e' il condizionante, e se fosse una previsione la cella
    # sarebbe indicizzata da una stima invece che da un fatto.
    constatata = (anticipo[:-1][valida] <= 0) & (anticipo[1:][valida] <= 0)
    conteggi.aggiungi(contesti, bin_monte, constatata)


def riferisci(citta: str, conteggi: Conteggi) -> list[dict]:
    print()
    print(f"  [{citta}] coppie utilizzabili {conteggi.coppie:,} | di cui constatate "
          f"{conteggi.coppie_constatate:,} ({conteggi.coppie_constatate / max(1, conteggi.coppie):.1%})")
    righe = []
    for livello in LIVELLI:
        celle_tutte = conteggi.tutte[livello]
        celle_const = conteggi.constatazioni[livello]
        totale_const = sum(celle_const.values())
        print()
        print(f"    {livello}: {len(celle_tutte):,} celle osservate, "
              f"{len(celle_const):,} con almeno una constatazione")
        for soglia in SOGLIE:
            coperte = [c for c, q in celle_const.items() if q >= soglia]
            in_coperte = sum(celle_const[c] for c in coperte)
            quota_celle = len(coperte) / len(celle_tutte) if celle_tutte else 0.0
            quota_oss = in_coperte / totale_const if totale_const else 0.0
            print(f"      soglia {soglia:>3}: celle coperte {len(coperte):>8,} "
                  f"({quota_celle:>6.1%}) | osservazioni in celle coperte {quota_oss:>6.1%}")
            righe.append({
                "citta": citta, "livello": livello, "soglia": soglia,
                "celle_osservate": len(celle_tutte), "celle_coperte": len(coperte),
                "quota_celle": quota_celle, "quota_osservazioni": quota_oss,
                "constatazioni": totale_const,
            })
    return righe


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--giorni", type=int, default=0)
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    RISULTATI.mkdir(exist_ok=True)
    cartella_gtfs = argomenti.radice / "data" / "raw" / "gtfs"
    tutte: list[dict] = []

    print("=" * 78)
    print("COPERTURA DELLE CONSTATAZIONI PER LIVELLO DELLA SCALA DI RISALITA")
    print("=" * 78)

    for citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / citta
        giorni = sorted(cartella.glob("*.parquet"))
        if argomenti.giorni:
            giorni = giorni[-argomenti.giorni:]
        if not giorni:
            print(f"  [{citta}] nessun parquet in {cartella}")
            continue
        tipo_di = tipi_di_linea(citta, cartella_gtfs)
        if not tipo_di:
            print(f"  [{citta}] tipi di linea non caricabili: si assume bus ovunque")
        conteggi, linee = Conteggi(), {}
        for percorso in giorni:
            coppie_di_un_giorno(percorso, tipo_di, conteggi, linee)
            print(f"  [{citta}] {percorso.stem}: {conteggi.coppie:,} coppie cumulate",
                  flush=True)
        tutte.extend(riferisci(citta, conteggi))

    if tutte:
        destinazione = RISULTATI / "copertura_constatazioni.csv"
        pd.DataFrame(tutte).to_csv(destinazione, index=False)
        print(f"\nscritto {destinazione} ({len(tutte)} righe)")
    print()
    print("La quota di CELLE dice quanto della tabella si stima al livello fine;")
    print("la quota di OSSERVAZIONI dice quanta parte del traffico reale vi ricade.")
    print("Le due divergono quando poche linee portanti convivono con molte marginali.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
