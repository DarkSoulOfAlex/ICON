"""Il criterio di constatazione regge, su questo feed?

GTFS Real-Time non offre alcun segnale di "il mezzo e' gia' passato". Il progetto
lo deduce: se l'orario atteso - programmato piu' ritardo - e' anteriore
all'istante in cui il produttore ha pubblicato, il passaggio e' avvenuto e il
numero e' un fatto; altrimenti e' una previsione. Su questa distinzione poggia
l'ordine della scala di risalita, perche' le previsioni contengono copie e i fatti
no.

La deduzione presuppone una cosa che nessuno ha verificato: **che il produttore
pubblichi anche le fermate gia' passate**. Se le togliesse dal feed appena il mezzo
vi transita, nel dato non ci sarebbe nessun passaggio avvenuto da osservare, e il
criterio non selezionerebbe i fatti bensi' le previsioni piu' anticipate - quelle
il cui orario atteso e' talmente in anticipo da precedere l'istante di
pubblicazione. Sarebbe una selezione sistematica, non casuale, e il gradino delle
"constatazioni" conterrebbe l'esatto contrario di cio' che il suo nome promette.

La statistica che decide e' una sola: quanto in la' nel passato arriva
``timestamp_feed - orario_programmato``. Se il massimo su un'intera giornata e' di
pochi secondi, il produttore non pubblica il passato e le constatazioni non
esistono. Se arriva a decine di minuti, le pubblica e il criterio funziona.

Si guarda ogni giornata separatamente e non l'aggregato: un produttore puo'
cambiare comportamento, e una media nasconderebbe proprio il giorno in cui e'
successo.

    python scripts/diagnosi_constatazioni.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from src.delays.contesto import (  # noqa: E402
    SOGLIA_PUBBLICA_IL_PASSATO,
    constatazione,
)

CITTA = ("roma", "torino")
COLONNE = ["ritardo_secondi", "orario_programmato", "timestamp_feed"]


def esamina_giornata(percorso: Path) -> dict | None:
    """Le statistiche di una giornata, senza conservarne le righe."""
    tabella = pq.read_table(percorso, columns=COLONNE)
    if tabella.num_rows == 0:
        return None
    ritardo = tabella.column("ritardo_secondi").to_numpy().astype(np.float64)
    programmato = tabella.column("orario_programmato").to_pandas().to_numpy(
        dtype="float64", na_value=np.nan)
    feed = tabella.column("timestamp_feed").to_numpy().astype(np.float64)
    del tabella
    utili = np.isfinite(programmato) & np.isfinite(ritardo)
    ritardo, programmato, feed = ritardo[utili], programmato[utili], feed[utili]
    if ritardo.size == 0:
        return None

    quanto_dopo = feed - programmato
    constatate = constatazione(programmato, ritardo, feed)
    quante = int(constatate.sum())
    return {
        "giornata": percorso.stem,
        "righe_con_orario": int(ritardo.size),
        "feed_meno_programmato_p50": float(np.median(quanto_dopo)),
        "feed_meno_programmato_p99": float(np.percentile(quanto_dopo, 99)),
        "feed_meno_programmato_max": float(quanto_dopo.max()),
        "quota_constatazioni": quante / ritardo.size,
        # La prova del nove: se fra le constatazioni non c'e' nessun ritardo
        # positivo, non sono passaggi avvenuti ma previsioni anticipate, perche' un
        # mezzo in ritardo davvero passato darebbe una constatazione con ritardo
        # positivo.
        "constatazioni_con_ritardo_positivo": (float((ritardo[constatate] > 0).mean())
                                               if quante else float("nan")),
        "ritardo_massimo_fra_le_constatazioni": (float(ritardo[constatate].max())
                                                 if quante else float("nan")),
    }


def verdetto(righe: list[dict]) -> tuple[bool, str]:
    """Il feed pubblica le fermate gia' passate, oppure no.

    Basta una giornata che arrivi oltre la soglia perche' il produttore, almeno in
    qualche momento, pubblichi il passato. Il contrario - nessuna giornata che ci
    arrivi, su due settimane - non e' una coincidenza.
    """
    massimi = [r["feed_meno_programmato_max"] for r in righe]
    if not massimi:
        return False, "nessuna giornata utilizzabile"
    oltre = sum(1 for m in massimi if m >= SOGLIA_PUBBLICA_IL_PASSATO)
    if oltre:
        return True, (f"{oltre} giornate su {len(massimi)} arrivano oltre "
                      f"{SOGLIA_PUBBLICA_IL_PASSATO:.0f} s dopo l'orario programmato: "
                      f"il feed pubblica il passato e le constatazioni esistono")
    return False, (f"nessuna delle {len(massimi)} giornate supera "
                   f"{SOGLIA_PUBBLICA_IL_PASSATO:.0f} s (massimo assoluto "
                   f"{max(massimi):.0f} s): il feed toglie la fermata appena il mezzo "
                   f"vi transita, e cio' che il criterio seleziona NON sono passaggi "
                   f"avvenuti")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG",
                        help="ignora le giornate successive: senza, due esecuzioni "
                             "a giorni di distanza guardano finestre diverse e la "
                             "differenza si attribuisce alla misura invece che ai dati")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("IL CRITERIO DI CONSTATAZIONE REGGE SU QUESTO FEED?")
    print("=" * 78)

    tutte: list[dict] = []
    for citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / citta
        giorni = sorted(cartella.glob("*.parquet"))
        if argomenti.fino_a:
            giorni = [g for g in giorni if g.stem <= argomenti.fino_a]
        if not giorni:
            print(f"  [{citta}] nessun parquet in {cartella}")
            continue
        finestra = giorni[-1].stem
        print()
        print(f"  === {citta} ({len(giorni)} giornate, fino al {finestra}) ===")
        print(f"  {'giornata':<12} {'righe':>12} {'feed-prog p50':>13} {'p99':>9} "
              f"{'max':>9} {'constat.':>9} {'con ritardo > 0':>16}")
        righe = []
        for percorso in giorni:
            riga = esamina_giornata(percorso)
            if riga is None:
                continue
            riga["citta"] = citta
            righe.append(riga)
            print(f"  {riga['giornata']:<12} {riga['righe_con_orario']:>12,} "
                  f"{riga['feed_meno_programmato_p50']:>13.0f} "
                  f"{riga['feed_meno_programmato_p99']:>9.0f} "
                  f"{riga['feed_meno_programmato_max']:>9.0f} "
                  f"{riga['quota_constatazioni']:>8.1%} "
                  f"{riga['constatazioni_con_ritardo_positivo']:>15.2%}", flush=True)
        esistono, spiegazione = verdetto(righe)
        print(f"  VERDETTO: {'constatazioni reali' if esistono else 'CONSTATAZIONI ASSENTI'}"
              f" - {spiegazione}")
        for r in righe:
            r["constatazioni_reali"] = int(esistono)
            r["finestra"] = finestra
        tutte.extend(righe)

    if tutte:
        destinazione = risultati / "diagnosi_constatazioni.csv"
        colonne = ["citta", "finestra", "giornata", "righe_con_orario",
                   "feed_meno_programmato_p50",
                   "feed_meno_programmato_p99", "feed_meno_programmato_max",
                   "quota_constatazioni", "constatazioni_con_ritardo_positivo",
                   "ritardo_massimo_fra_le_constatazioni", "constatazioni_reali"]
        pd.DataFrame(tutte)[colonne].to_csv(destinazione, index=False)
        print(f"\nscritto {destinazione} ({len(tutte)} righe)")
    print()
    print("Dove le constatazioni sono assenti, il gradino che porta il loro nome")
    print("contiene previsioni selezionate per essere molto in anticipo: e' una")
    print("selezione sistematica, e va dichiarata invece che stimata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
