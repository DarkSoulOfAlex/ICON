"""Backtesting: la domanda di ricerca, misurata sui ritardi realmente osservati.

Confronta due modi di scegliere un itinerario, a parita' di coppia origine-
destinazione e di scadenza:

  (a) **piu' veloce**: l'arrivo minimo secondo l'orario teorico;
  (b) **robusto**: il massimo di ``P(arrivo <= T)`` secondo il modello di Fase 3.

Poi rigioca entrambe le scelte sui ritardi che quel giorno sono stati osservati
davvero, e conta chi arriva entro T e chi perde coincidenze.

**Perche' rigiocare, e non confrontare le probabilita'.** Chiedere al modello
quale itinerario creda piu' sicuro e credergli sulla parola non e' una verifica:
il modello sarebbe giudice e imputato. La probabilita' che il modello attribuisce
alla propria scelta e' per costruzione la piu' alta - e' quella che ha scelto - e
misurarla non dice nulla su quanti viaggi riescano. Serve un arbitro esterno, e
l'unico disponibile e' cio' che i mezzi hanno fatto.

**Le giornate della replica sono quelle di verifica**, cioe' quelle che il modello
non ha visto in nessuna fase: la stima usa addestramento e taratura, la scelta dei
bordi usa il banco dentro l'addestramento (voce 64). Il modello arriva alla replica
senza avere mai guardato quel giorno.

**Che cosa si esclude, e va detto.** Solo una parte delle corse dell'orario compare
nel tempo reale, quindi non ogni itinerario e' rigiocabile: si tengono le coppie
con almeno due candidati interamente osservati. E' una selezione che favorisce le
linee frequenti, ed e' riportata come quota invece di essere lasciata implicita.

    python scripts/backtest.py
    python scripts/backtest.py --citta torino --bordi ottili --coppie 30
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

RADICE = Path(__file__).resolve().parents[1]
for _percorso in (RADICE, RADICE / "scripts"):
    if str(_percorso) not in sys.path:
        sys.path.insert(0, str(_percorso))

import numpy as np                                          # noqa: E402
import pandas as pd                                         # noqa: E402
import pyarrow.parquet as pq                                # noqa: E402

from src.delays.bayesiano import Forma, ModelloBayesiano     # noqa: E402
from src.delays.contesto import avviso_copertura, copertura_orario  # noqa: E402
from src.delays.interfaccia import assicura_utilizzabile     # noqa: E402
from src.eval.replica import (                               # noqa: E402
    margine_piu_stretto, replica, rigiocabile)
from src.graph.search import cerca_frontiera_pareto          # noqa: E402
from src.graph.time_expanded import costruisci               # noqa: E402
from src.gtfs.loader import carica_archivio                  # noqa: E402
from src.planner.robust import candidati_da_frontiera, pianifica_robusto  # noqa: E402

from ricerca_confronto import coppie_casuali                 # noqa: E402
from stima_rete import (                                     # noqa: E402
    Citta,
    carica,
    celle_finali,
    costruisci_scala,
    discretizza_coppie,
    maschera_popolazione,
    popolazione_di_stima,
    valori_rappresentativi,
)
from src.delays.rete import stima, tara                      # noqa: E402

FUSO = ZoneInfo("Europe/Rome")
CITTA = ("roma", "torino")
MARGINI = (0, 300, 600, 900, 1200, 1800)
"""Secondi concessi oltre l'arrivo teorico piu' rapido: da zero a trenta minuti.

Sono gli stessi della griglia di Fase 4, perche' il confronto fra i risultati
sintetici e quelli veri sia diretto invece che approssimativo.
"""
ORA_PARTENZA = 8
ORIZZONTE = 120
SEME = 20260910

BORDI = {
    "attuali": (-60.0, 0.0, 60.0, 120.0, 300.0, 600.0, 1200.0),
    "ottili": (-554.0, -366.0, -250.0, -158.0, -80.0, 18.0, 213.0),
    "decisione": (-300.0, -60.0, 0.0, 120.0, 300.0, 900.0, 1800.0),
}
"""Gli insiemi di bordi da mettere alla prova, con gli estremi di `scelta_bordi.csv`.

Sono trascritti e non ricalcolati di proposito: la Fase 3 li ha scelti su una
finestra dichiarata, e il backtesting deve usare quelli, non quelli che i dati di
oggi produrrebbero. Se cambiassero si vedrebbe dal confronto con quel CSV.
"""


@dataclass(frozen=True)
class Esito:
    """Una riga: una coppia, un margine, una strategia, un giorno."""

    citta: str
    giornata: str
    bordi: str
    finestra: str
    """Ultima giornata delle osservazioni usate: da dove viene questo numero."""
    coppie_richieste: int
    seme: int
    coppia: int
    origine: str
    destinazione: str
    margine: int
    strategia: str
    probabilita_attesa: float
    arrivo_programmato: int
    cambi: int
    arrivo_reale: int | None
    entro_scadenza: bool
    completato: bool
    coincidenze_perse: int
    recuperi: int
    partenza_persa: bool
    candidati: int
    coppie_esaminate: int
    """Coppie OD con almeno due candidati sull'orario, prima del filtro sul dato."""
    coppie_scartate: int
    """Quante di quelle sono cadute perche' i candidati non erano interamente
    osservati. Il rapporto fra le due dice su quale parte della rete il risultato
    valga, ed era finora un numero che esisteva solo nel log dell'esecuzione."""
    copertura_orario: float
    """Quota di righe della giornata che hanno trovato il proprio orario
    programmato: una giornata mal coperta produce poche coppie rigiocabili, ed e'
    successo (voce 64)."""
    margine_critico: int | None
    """Secondi di respiro della coincidenza piu' tesa dell'itinerario scelto.

    Distingue due spiegazioni del pessimismo del modello: un errore che si compone
    lungo la catena si concentrerebbe sugli itinerari lunghi, uno locale alla
    coincidenza critica si concentrerebbe su quelli con margini stretti. Vale
    ``None`` sugli itinerari senza cambi."""


def ritardi_osservati(percorso: Path,
                      giornata: str) -> tuple[dict[tuple[str, str], int], float]:
    """Il ritardo dell'ultima revisione di ogni passaggio, per (corsa, fermata).

    Si tiene l'ultima revisione, come nella stima: e' quella che il viaggiatore
    avrebbe visto piu' vicino al fatto, ed e' l'unica scelta che rende la replica
    confrontabile col modello, addestrato sulle stesse righe.
    """
    tabella = pq.read_table(percorso, columns=["service_date", "trip_id", "stop_id",
                                               "ritardo_secondi", "timestamp_feed",
                                               "orario_programmato"])
    dati = tabella.to_pandas()
    del tabella
    # Una giornata in cui gran parte delle corse non esiste nell'archivio in vigore
    # produce poche tratte osservate e quindi poche coppie rigiocabili: e' successo
    # su Roma il 31 agosto e il 7 settembre, e la conseguenza si e' manifestata
    # altrove e senza spiegazione. Si misura qui e si dichiara, non si esclude.
    #
    # Si misura **prima** del filtro sulla data di servizio, come in
    # ``scripts/copertura_orario.py``: la stessa grandezza deve avere lo stesso
    # valore ovunque la si legga, altrimenti non e' la stessa grandezza.
    copertura = copertura_orario(
        dati["orario_programmato"].to_numpy(dtype="float64", na_value=np.nan))
    dati = dati[dati["service_date"] == giornata]
    if dati.empty:
        return {}, copertura
    # Un ritardo assente non e' uno zero: e' una riga di cui non si sa nulla, e
    # tenerla convertendola dichiarerebbe puntuale cio' che non si e' visto. Si
    # scarta, con la stessa regola per cui una tratta non osservata ferma la replica.
    ritardo = pd.to_numeric(dati["ritardo_secondi"], errors="coerce")
    noti = np.isfinite(ritardo.to_numpy(dtype="float64", na_value=np.nan))
    dati = dati[noti]
    if dati.empty:
        return {}, copertura
    dati = dati.sort_values("timestamp_feed").drop_duplicates(
        subset=["trip_id", "stop_id"], keep="last")
    return {(str(t), str(s)): int(r) for t, s, r in
            zip(dati["trip_id"], dati["stop_id"],
                pd.to_numeric(dati["ritardo_secondi"]))}, copertura


def archivio_per(citta: str, giornata: str) -> Path:
    """L'archivio GTFS in vigore quel giorno: il piu' recente non successivo.

    Prendere sempre l'ultimo disponibile userebbe un orario pubblicato dopo il
    giorno che si rigioca, cioe' farebbe conoscere al pianificatore un servizio che
    quel giorno non era ancora annunciato.
    """
    archivi = sorted((RADICE / "data" / "raw" / "gtfs" / citta).glob("*.zip"))
    validi = [a for a in archivi if a.stem.split("_")[0] <= giornata]
    if not validi:
        raise SystemExit(f"nessun archivio GTFS per {citta} valido al {giornata}")
    return validi[-1]


def costruisci_modello(c: Citta, bordi: tuple[float, ...],
                       etichetta: str) -> tuple[ModelloBayesiano, dict]:
    """La stessa scala della Fase 3, tarata sulle stesse giornate.

    Non una versione semplificata: un modello piu' povero renderebbe il confronto
    fra le strategie una misura di quel modello, non della struttura scelta.
    """
    n_bin = len(bordi) + 1
    dati = discretizza_coppie(c.dati, bordi)
    codifica = c.codifica(n_bin)
    popolazione = popolazione_di_stima(c)
    scala = "constatazioni sole" if popolazione == "constatazioni" else "popolazione unica"
    gradini = c.scale[scala]

    in_addestramento = np.isin(dati["giornata"], c.addestramento)
    in_taratura = np.isin(dati["giornata"], c.taratura)
    in_stima = in_addestramento | in_taratura
    m_taratura = in_taratura & maschera_popolazione(dati, popolazione)

    esito = tara(costruisci_scala(scala, gradini, codifica, dati, in_addestramento),
                 celle_finali(gradini, codifica, dati, m_taratura),
                 dati["valore"][m_taratura].astype(np.int64), n_bin, passate=2)
    modello = stima(costruisci_scala(scala, gradini, codifica, dati, in_stima),
                    n_bin, list(esito.alfa))

    m_stima = in_stima & maschera_popolazione(dati, popolazione)
    marginale = np.bincount(dati["monte"][m_stima].astype(np.int64), minlength=n_bin)
    forma = Forma(bordi=bordi, medie=valori_rappresentativi(dati, n_bin))
    ponte = ModelloBayesiano(modello, codifica, forma, c.indice_linea,
                             marginale.astype(np.float64) + 1.0, c.nome, etichetta)
    assicura_utilizzabile(ponte)
    return ponte, {
        "scala": scala, "popolazione": popolazione,
        "alfa": " ".join(f"{a:g}" for a in esito.alfa),
        "coppie_di_stima": int(m_stima.sum()),
        "giornate_di_stima": len(c.addestramento) + len(c.taratura),
    }


def istanze_del_giorno(citta: str, giornata: str, ritardo, quante: int):
    """Coppie OD con almeno due candidati interamente osservati quel giorno."""
    archivio = carica_archivio(archivio_per(citta, giornata), con_stop_times=True)
    g = date.fromisoformat(giornata)
    inizio = int(datetime(g.year, g.month, g.day, ORA_PARTENZA, 0,
                          tzinfo=FUSO).timestamp())
    grafo = costruisci(archivio, citta, g, inizio, ORIZZONTE)
    trovate, esaminate, scartate = [], 0, 0
    for origine, destinazione in coppie_casuali(grafo, quante * 8, SEME):
        esito = cerca_frontiera_pareto(grafo, origine, destinazione, inizio)
        if len(esito.frontiera) < 2:
            continue
        candidati = candidati_da_frontiera(grafo, esito, inizio)
        if len(candidati) < 2:
            continue
        esaminate += 1
        rigiocabili = [c for c in candidati if rigiocabile(c.itinerario, ritardo)]
        if len(rigiocabili) < 2:
            scartate += 1
            continue
        trovate.append((origine, destinazione, rigiocabili))
        if len(trovate) >= quante:
            break
    return trovate, inizio, esaminate, scartate


def valuta_coppia(citta: str, giornata: str, etichetta: str, indice: int,
                  origine: str, destinazione: str, candidati, modello,
                  ritardo, provenienza: dict) -> list[Esito]:
    """Le due strategie sulla stessa coppia, per ogni margine, rigiocate."""
    righe: list[Esito] = []
    piu_rapido = min(c.orario_arrivo for c in candidati)
    for margine in MARGINI:
        scadenza = piu_rapido + margine
        veloce = min(candidati, key=lambda c: (c.orario_arrivo, c.cambi))
        try:
            scelta = pianifica_robusto(candidati, modello, scadenza)
        except Exception as errore:                          # noqa: BLE001
            print(f"      coppia {indice} margine {margine}: non valutabile ({errore})")
            continue
        robusto = scelta.candidato
        probabilita = dict(zip(range(len(candidati)), scelta.probabilita_per_candidato))
        for nome, candidato in (("piu_veloce", veloce), ("robusto", robusto)):
            esito = replica(candidato.itinerario, ritardo)
            righe.append(Esito(
                citta=citta, giornata=giornata, bordi=etichetta, coppia=indice,
                finestra=provenienza["finestra"],
                coppie_richieste=provenienza["coppie_richieste"],
                seme=provenienza["seme"],
                coppie_esaminate=provenienza["coppie_esaminate"],
                coppie_scartate=provenienza["coppie_scartate"],
                copertura_orario=provenienza["copertura_orario"],
                origine=origine, destinazione=destinazione, margine=margine,
                strategia=nome,
                probabilita_attesa=float(probabilita[candidati.index(candidato)]),
                arrivo_programmato=candidato.orario_arrivo, cambi=candidato.cambi,
                arrivo_reale=esito.arrivo_reale, entro_scadenza=esito.entro(scadenza),
                completato=esito.completato,
                coincidenze_perse=esito.coincidenze_perse,
                recuperi=esito.recuperi_riusciti,
                partenza_persa=esito.partenza_persa, candidati=len(candidati),
                margine_critico=margine_piu_stretto(candidato.itinerario)))
    return righe


QUOTA_MINIMA_DI_COPPIE = 0.5
"""Frazione delle coppie richieste sotto la quale una giornata non entra nella media.

La media fra giornate le pesa tutte uguali, ed e' la scelta giusta: le istanze di
uno stesso giorno condividono il traffico di quel giorno e non sono indipendenti.
Ne segue pero' che una giornata con sette coppie conta quanto una con trenta, e
sette coppie sono un campione che il caso muove a piacere.

La soglia e' fissata a meta' delle coppie richieste ed e' stata scelta **prima** di
guardare quale risultato producesse: e' l'unico modo di non sceglierla per l'esito.
Sui dati raccolti esclude una sola giornata, Roma 2026-09-07, che il consolidamento
aveva prodotto parziale.
"""


def scarta_giornate_magre(tabella: pd.DataFrame,
                          quota: float = QUOTA_MINIMA_DI_COPPIE) -> pd.DataFrame:
    """Toglie le giornate con troppe poche coppie perche' la loro media valga."""
    if tabella.empty or "coppie_richieste" not in tabella.columns:
        return tabella
    conteggio = (tabella.groupby(["citta", "giornata"])
                 .agg(coppie=("coppia", "nunique"),
                      richieste=("coppie_richieste", "first"))
                 .reset_index())
    magre = conteggio[conteggio.coppie < quota * conteggio.richieste]
    if magre.empty:
        return tabella
    for _, r in magre.iterrows():
        print(f"  giornata esclusa: {r.citta} {r.giornata} ha {int(r.coppie)} coppie "
              f"su {int(r.richieste)} richieste, sotto la meta'")
    escluse = set(zip(magre.citta, magre.giornata))
    tenute = [t not in escluse for t in zip(tabella.citta, tabella.giornata)]
    return tabella[tenute]


def segna_divergenze(tabella: pd.DataFrame, scarta_magre: bool = True) -> pd.DataFrame:
    """Marca le istanze in cui le due strategie scelgono itinerari diversi.

    Serve perche' dove scelgono lo stesso itinerario la differenza fra loro e' zero
    **per costruzione**, e mediare su quelle diluisce l'effetto verso lo zero per
    quanto il modello sia bravo. La quota di divergenza va riportata accanto alla
    differenza, altrimenti un vantaggio inesistente e un vantaggio reale ma raro si
    leggono allo stesso modo.
    """
    # Una riga ripetuta non cambia le medie ma gonfia i conteggi, e soprattutto e'
    # il sintomo di due esecuzioni che hanno scritto sullo stesso file: si toglie e
    # si dice, invece di assorbirla in silenzio.
    if scarta_magre:
        tabella = scarta_giornate_magre(tabella)
    identificativo = ["citta", "bordi", "giornata", "coppia", "margine", "strategia"]
    ripetute = int(tabella.duplicated(subset=identificativo).sum())
    if ripetute:
        print(f"  ATTENZIONE: {ripetute:,} righe ripetute sulla stessa chiave, tolte. "
              f"Di norma significa che due esecuzioni hanno scritto sullo stesso CSV.")
        tabella = tabella.drop_duplicates(subset=identificativo, keep="first")

    chiave = ["citta", "bordi", "giornata", "coppia", "margine"]
    scelte = (tabella.pivot_table(index=chiave, columns="strategia",
                                  values="arrivo_programmato", aggfunc="first")
              .reset_index())
    if not {"piu_veloce", "robusto"} <= set(scelte.columns):
        tabella["divergono"] = False
        return tabella
    scelte["divergono"] = scelte["piu_veloce"] != scelte["robusto"]
    return tabella.merge(scelte[chiave + ["divergono"]], on=chiave, how="left")


def riepiloga(righe: list[dict], scarta_magre: bool = True) -> pd.DataFrame:
    """Media e deviazione **sulle giornate**, non sulle istanze.

    Le istanze di uno stesso giorno condividono il traffico di quel giorno e non
    sono indipendenti: una deviazione calcolata su di esse sarebbe piu' stretta del
    vero e farebbe sembrare significative differenze che non lo sono.
    """
    tabella = segna_divergenze(pd.DataFrame(righe), scarta_magre)
    if tabella.empty:
        return tabella
    chiave = ["citta", "bordi", "strategia", "margine"]

    def scarto(v):
        return float(np.std(v, ddof=1)) if len(v) > 1 else 0.0

    per_giorno = (tabella.groupby(chiave + ["giornata"])
                  .agg(quota_entro=("entro_scadenza", "mean"),
                       quota_completati=("completato", "mean"),
                       coincidenze_perse=("coincidenze_perse", "mean"),
                       probabilita_attesa=("probabilita_attesa", "mean"),
                       cambi=("cambi", "mean"),
                       quota_divergenti=("divergono", "mean"),
                       istanze=("entro_scadenza", "size"))
                  .reset_index())
    riepilogo = (per_giorno.groupby(chiave)
                 .agg(giornate=("giornata", "nunique"),
                      istanze=("istanze", "sum"),
                      quota_entro=("quota_entro", "mean"),
                      deviazione_entro=("quota_entro", scarto),
                      quota_completati=("quota_completati", "mean"),
                      coincidenze_perse=("coincidenze_perse", "mean"),
                      probabilita_attesa=("probabilita_attesa", "mean"),
                      cambi=("cambi", "mean"),
                      quota_divergenti=("quota_divergenti", "mean"))
                 .reset_index())

    solo_diverse = tabella[tabella["divergono"]]
    if not solo_diverse.empty:
        per_giorno_diverse = (solo_diverse.groupby(chiave + ["giornata"])
                              .agg(quota=("entro_scadenza", "mean"),
                                   istanze=("entro_scadenza", "size"))
                              .reset_index())
        aggiunta = (per_giorno_diverse.groupby(chiave)
                    .agg(quota_entro_divergenti=("quota", "mean"),
                         deviazione_divergenti=("quota", scarto),
                         istanze_divergenti=("istanze", "sum"))
                    .reset_index())
        riepilogo = riepilogo.merge(aggiunta, on=chiave, how="left")
    if "coppie_esaminate" in tabella.columns:
        # Una riga per giornata, poi la media fra giornate: le colonne sono costanti
        # dentro una giornata, e mediarle sulle istanze le peserebbe per quante
        # istanze quella giornata ha prodotto, che e' il contrario di cio' che serve.
        per_giorno = (tabella.groupby(["citta", "bordi", "giornata"])
                      .agg(esaminate=("coppie_esaminate", "first"),
                           scartate=("coppie_scartate", "first"),
                           copertura=("copertura_orario", "first"))
                      .reset_index())
        per_giorno["quota_rigiocabili"] = (
            1 - per_giorno["scartate"] / per_giorno["esaminate"].clip(lower=1))
        quote = (per_giorno.groupby(["citta", "bordi"])
                 .agg(quota_rigiocabili=("quota_rigiocabili", "mean"),
                      deviazione_rigiocabili=("quota_rigiocabili", "std"),
                      copertura_orario_minima=("copertura", "min"))
                 .reset_index())
        riepilogo = riepilogo.merge(quote, on=["citta", "bordi"], how="left")
    return riepilogo


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--bordi", nargs="*", default=["ottili", "decisione"])
    parser.add_argument("--coppie", type=int, default=30)
    parser.add_argument("--giorni", type=int, default=0)
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG")
    parser.add_argument("--solo-riepilogo", action="store_true",
                        help="non rigioca nulla: rilegge results/backtest.csv e "
                             "ricalcola il riepilogo")
    parser.add_argument("--tieni-giornate-magre", action="store_true",
                        help="non applica QUOTA_MINIMA_DI_COPPIE e scrive "
                             "backtest_riepilogo_con_magre.csv: serve a misurare "
                             "quanto la regola sposti, invece di affermarlo")
    parser.add_argument("--riprendi", action="store_true",
                        help="riusa le righe gia' in results/backtest.csv e calcola "
                             "solo le combinazioni mancanti")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    dettaglio = risultati / "backtest.csv"
    print("=" * 78)
    print("BACKTESTING: LE DUE STRATEGIE RIGIOCATE SUI RITARDI OSSERVATI")
    print("=" * 78)

    # Una corsa completa dura decine di minuti, e perderla per un'interruzione
    # significherebbe rifarla per intero: si scrive a ogni giornata conclusa, e con
    # --riprendi si saltano le combinazioni gia' presenti nel CSV. Senza il flag il
    # file viene rifatto da capo, cosi' una corsa nuova non eredita in silenzio
    # righe prodotte con altri parametri.
    fatte: set[tuple[str, str, str]] = set()
    tutte: list[dict] = []
    if argomenti.solo_riepilogo:
        if not dettaglio.is_file():
            print(f"  {dettaglio} non esiste: nulla da riepilogare")
            return 1
        tutte = pd.read_csv(dettaglio).to_dict("records")
        print(f"  riepilogo da {dettaglio.name}: {len(tutte):,} righe lette")
        return riferisci(tutte, risultati, dettaglio,
                         scarta_magre=not argomenti.tieni_giornate_magre)
    if argomenti.riprendi and dettaglio.is_file():
        gia = pd.read_csv(dettaglio)
        tutte = gia.to_dict("records")
        fatte = set(zip(gia["citta"], gia["bordi"], gia["giornata"]))
        print(f"  ripresa: {len(tutte):,} righe gia' in {dettaglio.name}, "
              f"{len(fatte)} combinazioni citta'/bordi/giornata da saltare")
    elif dettaglio.is_file():
        dettaglio.unlink()
    for nome_citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / nome_citta
        if not cartella.is_dir():
            print(f"  [{nome_citta}] cartella assente: {cartella}")
            continue
        c = carica(nome_citta, cartella, argomenti.radice / "data" / "raw" / "gtfs",
                   argomenti.giorni, argomenti.fino_a)
        if c is None:
            continue
        # La provenienza viaggia con ogni riga: la finestra effettiva - l'ultima
        # giornata usata, anche quando --fino-a non e' passato - piu' i parametri
        # che determinano quali coppie si estraggono. Senza, il CSV non sa da dove
        # viene, e la sua riproducibilita' dipende da chi se lo ricorda.
        provenienza = {"finestra": c.giorni[-1] if c.giorni else "",
                       "coppie_richieste": argomenti.coppie, "seme": SEME}
        giornate = [c.giorni[i] for i in c.verifica]
        print(f"  [{nome_citta}] replica su {len(giornate)} giornate di verifica: "
              f"{', '.join(giornate)}")

        modelli = {}
        for etichetta in argomenti.bordi:
            if etichetta not in BORDI:
                print(f"  bordi '{etichetta}' sconosciuti: {sorted(BORDI)}")
                continue
            modelli[etichetta] = costruisci_modello(c, BORDI[etichetta], etichetta)
            _, info = modelli[etichetta]
            print(f"    [{nome_citta}/{etichetta}] scala '{info['scala']}' su "
                  f"{info['popolazione']}, {info['coppie_di_stima']:,} coppie in "
                  f"{info['giornate_di_stima']} giornate | alfa {info['alfa']}")
        if not modelli:
            continue

        # Le istanze non dipendono dai bordi: si costruiscono una volta per
        # giornata e si valutano con tutti i modelli. Ricostruire il grafo per ogni
        # insieme di bordi costerebbe minuti a Roma senza cambiare una riga.
        for giornata in giornate:
            if all((nome_citta, e, giornata) in fatte for e in modelli):
                print(f"      {giornata}: gia' fatta, saltata")
                continue
            # Una giornata che si rompe non deve portarsi via le altre: il lavoro
            # gia' fatto vale ore, e perderlo per un dato malformato in fondo alla
            # griglia significherebbe rifare tutto per scoprire lo stesso guasto.
            try:
                ritardo_di, copertura = ritardi_osservati(
                    cartella / f"{giornata}.parquet", giornata)
            except Exception as errore:                      # noqa: BLE001
                print(f"      {giornata}: osservazioni non leggibili ({errore})")
                continue
            if not ritardo_di:
                print(f"      {giornata}: nessuna osservazione")
                continue

            def ritardo(trip: str, stop: str, _tabella=ritardo_di) -> int | None:
                return _tabella.get((str(trip), str(stop)))

            try:
                istanze, _, esaminate, scartate = istanze_del_giorno(
                    nome_citta, giornata, ritardo, argomenti.coppie)
            except Exception as errore:                      # noqa: BLE001
                print(f"      {giornata}: istanze non costruibili ({errore})")
                continue
            if not istanze:
                print(f"      {giornata}: nessuna coppia rigiocabile "
                      f"({esaminate} esaminate)")
                continue
            quota = 1 - scartate / max(1, esaminate)
            # La provenienza porta gia' finestra, coppie richieste e seme: qui si
            # aggiunge cio' che dice **su quale parte della rete** il numero valga.
            provenienza["coppie_esaminate"] = esaminate
            provenienza["coppie_scartate"] = scartate
            provenienza["copertura_orario"] = copertura
            quante, nuove = 0, []
            for etichetta, (modello, _) in modelli.items():
                if (nome_citta, etichetta, giornata) in fatte:
                    continue
                righe: list[Esito] = []
                for indice, (o, d, candidati) in enumerate(istanze, 1):
                    righe.extend(valuta_coppia(nome_citta, giornata, etichetta, indice,
                                               o, d, candidati, modello, ritardo,
                                               provenienza))
                nuove.extend(vars(r) for r in righe)
                quante += len(righe)
            tutte.extend(nuove)
            if nuove:
                pd.DataFrame(nuove).to_csv(dettaglio, mode="a", index=False,
                                           header=not dettaglio.is_file())
            print(f"      {giornata}: {len(istanze)} coppie rigiocabili su "
                  f"{esaminate} esaminate ({quota:.0%}), {quante} righe"
                  f"{avviso_copertura(copertura)}", flush=True)

        for etichetta, (modello, _) in modelli.items():
            d = modello.diagnostica()
            print(f"    [{nome_citta}/{etichetta}] ripieghi: {d['linee_ignote']} linee "
                  f"ignote, {d['tratte_senza_ritardo_a_monte']:,} tratte senza ritardo "
                  f"a monte su {d['tratte_servite']:,}")

    return riferisci(tutte, risultati, dettaglio)


def riferisci(tutte: list[dict], risultati: Path, dettaglio: Path,
              scarta_magre: bool = True) -> int:
    """Riepiloga, scrive e stampa.

    Separato dal ciclo che rigioca per poterlo rifare senza ricalcolare nulla: la
    replica dura decine di minuti, il riepilogo un istante, e sbagliare una colonna
    del riepilogo non deve costare una corsa intera.
    """
    if not tutte:
        print("\nnessuna istanza rigiocabile: nessun risultato scritto")
        return 1

    riepilogo = riepiloga(tutte, scarta_magre)
    # Il riepilogo con le giornate magre dentro non sostituisce quello principale:
    # sta accanto, perche' la differenza fra i due E' il risultato che giustifica
    # la regola (voce 64), e senza un file quel confronto sarebbe un numero scritto
    # a memoria.
    destinazione = risultati / ("backtest_riepilogo.csv" if scarta_magre
                                else "backtest_riepilogo_con_magre.csv")
    riepilogo.to_csv(destinazione, index=False)
    # Il dettaglio non si scrive qui: viene aggiunto a ogni giornata conclusa,
    # perche' un'interruzione non porti via ore di replica. Qui si dice soltanto
    # quante righe lo compongono, che e' cio' su cui il riepilogo e' calcolato.
    print(f"\n{dettaglio} contiene {len(tutte)} righe")
    print(f"scritto {destinazione} ({len(riepilogo)} righe)")

    print()
    print("  QUOTA DI VIAGGI ARRIVATI ENTRO LA SCADENZA")
    intestazione = ("citta", "bordi", "margine", "piu_veloce", "robusto", "diff",
                    "divergono", "diff dove divergono")
    print(f"  {intestazione[0]:<8} {intestazione[1]:<10} {intestazione[2]:>8} "
          f"{intestazione[3]:>18} {intestazione[4]:>18} {intestazione[5]:>7} "
          f"{intestazione[6]:>10} {intestazione[7]:>22}")
    for (citta, bordi, margine), gruppo in riepilogo.groupby(["citta", "bordi",
                                                              "margine"]):
        per_strategia = gruppo.set_index("strategia")
        if not {"piu_veloce", "robusto"} <= set(per_strategia.index):
            continue
        a = per_strategia.loc["piu_veloce"]
        b = per_strategia.loc["robusto"]
        divergenti = ""
        if "quota_entro_divergenti" in gruppo.columns:
            da = a.get("quota_entro_divergenti")
            db = b.get("quota_entro_divergenti")
            if pd.notna(da) and pd.notna(db):
                quante = int(b.get("istanze_divergenti", 0))
                divergenti = f"{db - da:+.1%} su {quante}"
        print(f"  {citta:<8} {bordi:<10} {margine:>8} "
              f"{a.quota_entro:>9.1%} +/-{a.deviazione_entro:<6.1%} "
              f"{b.quota_entro:>9.1%} +/-{b.deviazione_entro:<6.1%} "
              f"{b.quota_entro - a.quota_entro:>+7.1%} "
              f"{b.quota_divergenti:>10.1%} {divergenti:>22}")
    print()
    print("La differenza e' la risposta alla domanda di ricerca, e va letta accanto")
    print("alla deviazione fra giornate: se e' piu' piccola, il vantaggio non c'e'.")
    print("Dove le due strategie scelgono lo stesso itinerario la differenza e' zero")
    print("per costruzione: l'ultima colonna toglie quelle istanze, ed e' la misura")
    print("piu' netta di quanto il modello sposti l'esito quando sposta la scelta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
