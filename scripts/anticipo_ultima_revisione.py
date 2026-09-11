"""Con quanto anticipo sul transito atteso e' emessa l'ULTIMA stima di un passaggio.

E' il numero che regge una limitazione dichiarata del progetto: su Torino il feed
toglie la fermata dal ``trip_updates`` appena il mezzo vi transita (voce 63), quindi
il dato su cui il modello si stima e il backtesting verifica **non e' un ritardo
osservato** ma l'ultima previsione pubblicata prima della sparizione. Quanto valga
quell'"ultima" decide quanto la limitazione sia severa: a dieci secondi dal transito
e' quasi una constatazione, a dieci minuti e' una previsione a tutti gli effetti.

**Perche' non e' la stessa cosa di ``feed - programmato``.** Quella grandezza, che
``diagnosi_constatazioni.py`` riporta, misura la distanza fra l'istante di
pubblicazione e l'orario **programmato**, su **tutte** le righe: e' dominata dalle
previsioni lontane, che il feed ripubblica di continuo, e su Torino vale circa
-330 s. Qui si misura un'altra cosa:

    anticipo = orario_osservato - timestamp_feed

cioe' la distanza fra l'istante di pubblicazione e il transito **atteso** - orario
programmato piu' ritardo dichiarato - e solo sulla riga che ``ultima_revisione``
conserva per ciascun passaggio, che e' la sola che entra nella stima. Le due
rispondono a domande diverse e non vanno scambiate.

Un anticipo **positivo** significa che il transito atteso e' nel futuro rispetto alla
pubblicazione, cioe' che il dato e' una previsione; **negativo**, che il transito
atteso era gia' passato, cioe' una constatazione. Su Roma ci si aspettano entrambi i
segni, su Torino quasi solo il primo.

    python scripts/anticipo_ultima_revisione.py --fino-a 2026-09-09
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src.delays.contesto import ultima_revisione  # noqa: E402

CITTA = ("roma", "torino")
COLONNE = ["trip_id", "stop_sequence", "orario_osservato", "timestamp_feed"]


def anticipi_di_un_giorno(percorso: Path) -> np.ndarray:
    """Gli anticipi, in secondi, delle sole ultime revisioni di una giornata."""
    tabella = pq.read_table(percorso, columns=COLONNE)
    sequenza = tabella["stop_sequence"].to_numpy(zero_copy_only=False).astype(np.int64)
    osservato = tabella["orario_osservato"].to_numpy(zero_copy_only=False).astype(np.float64)
    feed = tabella["timestamp_feed"].to_numpy(zero_copy_only=False).astype(np.float64)

    # Il codice di corsa serve solo come identificatore, e si prende dal dizionario
    # di Arrow invece che da ``np.unique`` sulle stringhe: su venti milioni di righe
    # la differenza e' fra secondi e decine di minuti, perche' ``np.unique`` su un
    # array di oggetti ordina confrontando stringhe Python una coppia alla volta.
    codice = (tabella["trip_id"].combine_chunks().dictionary_encode()
              .indices.to_numpy(zero_copy_only=False).astype(np.int64))
    ultima = ultima_revisione(codice, sequenza, feed)

    anticipo = osservato[ultima] - feed[ultima]
    # Una riga senza orario programmato non ha un transito atteso: il ritardo che il
    # feed dichiara resta valido, ma l'anticipo no, e va tolto invece di contare come
    # zero (voce 63: le statistiche di contorno smascherano le popolazioni mal definite).
    return anticipo[np.isfinite(anticipo)]


def riassumi(citta: str, giornata: str, anticipo: np.ndarray) -> dict:
    return {
        "citta": citta, "giornata": giornata, "righe": int(anticipo.size),
        "anticipo_p25": float(np.quantile(anticipo, 0.25)),
        "anticipo_mediana": float(np.median(anticipo)),
        "anticipo_p75": float(np.quantile(anticipo, 0.75)),
        "anticipo_medio": float(np.mean(anticipo)),
        "quota_positivi": float(np.mean(anticipo > 0)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    print("=" * 78)
    print("ANTICIPO DELL'ULTIMA REVISIONE SUL TRANSITO ATTESO")
    print("=" * 78)

    righe: list[dict] = []
    for citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / citta
        giorni = sorted(cartella.glob("*.parquet"))
        if argomenti.fino_a:
            giorni = [g for g in giorni if g.stem <= argomenti.fino_a]
        if not giorni:
            print(f"  [{citta}] nessun parquet")
            continue
        finestra = giorni[-1].stem
        print(f"\n  === {citta} ({len(giorni)} giornate, fino al {finestra}) ===")
        print(f"  {'giornata':<12} {'passaggi':>12} {'p25':>9} {'mediana':>9} "
              f"{'p75':>9} {'positivi':>9}")
        per_citta = []
        for percorso in giorni:
            a = anticipi_di_un_giorno(percorso)
            if a.size == 0:
                print(f"  {percorso.stem:<12} nessuna riga con transito atteso")
                continue
            r = riassumi(citta, percorso.stem, a)
            r["finestra"] = finestra
            righe.append(r)
            per_citta.append(r)
            print(f"  {r['giornata']:<12} {r['righe']:>12,} {r['anticipo_p25']:>9.0f} "
                  f"{r['anticipo_mediana']:>9.0f} {r['anticipo_p75']:>9.0f} "
                  f"{r['quota_positivi']:>8.1%}")
        if per_citta:
            # Media e deviazione **fra giornate**: i passaggi di uno stesso giorno
            # condividono il traffico di quel giorno e non sono indipendenti.
            mediane = np.array([r["anticipo_mediana"] for r in per_citta])
            print(f"  mediana fra giornate: {mediane.mean():.0f} +/- "
                  f"{mediane.std(ddof=1):.0f} s "
                  f"({mediane.mean() / 60:.1f} +/- {mediane.std(ddof=1) / 60:.1f} min)")

    if not righe:
        print("nessuna giornata utilizzabile")
        return 1
    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    destinazione = risultati / "anticipo_ultima_revisione.csv"
    pd.DataFrame(righe).to_csv(destinazione, index=False)
    print(f"\nscritto {destinazione} ({len(righe)} righe)")
    print()
    print("Un anticipo positivo dice che il transito atteso era nel futuro rispetto")
    print("alla pubblicazione: il dato e' una previsione, non un fatto compiuto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
