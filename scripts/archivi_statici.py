"""Quante revisioni dell'orario statico esistono, e quanto pesano.

Il documento afferma che le due aziende aggiornano l'orario con frequenza molto
diversa - Roma ogni giorno, Torino circa una volta ogni tre - e che e' per questo
che archiviare a ogni cambiamento e' un requisito e non una precauzione: se
avessimo scaricato il GTFS una volta sola, i ritardi calcolati sulle giornate
precedenti sarebbero scostamenti da un orario che quel giorno non era in vigore.

Quei numeri venivano finora da un conteggio fatto a mano il 25 agosto e non erano
piu' rifacibili da nessuno. Sono invece la cosa piu' semplice da misurare che ci
sia - i file stanno su disco - e questo script li scrive in
``results/archivi_statici.csv``.

**Perche' la data e' una colonna e non un commento.** La raccolta e' ferma, ma
riprendera': ogni giornata nuova puo' aggiungere una revisione, e allora tutte le
righe di questo CSV cambiano. Senza la data del conteggio, due esecuzioni a
distanza di un mese darebbero numeri diversi senza che nulla dicesse perche'. E'
lo stesso motivo per cui esistono le colonne ``finestra`` e ``archivio`` altrove.

**Che cosa conta come revisione.** Un file ``.zip`` nella cartella della citta',
il cui nome e' la data in cui e' stato scaricato. Il collector lo scrive **solo
quando l'impronta cambia**, quindi il numero di file e' gia' il numero di revisioni
distinte: non si riapre nessun archivio per confrontarne il contenuto, perche'
sarebbe rifare a valle un controllo che il collector ha gia' fatto a monte.

    python scripts/archivi_statici.py
    python scripts/archivi_statici.py --fino-a 2026-09-09
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import pandas as pd  # noqa: E402

CITTA = ("roma", "torino")
MB = 1024 * 1024


def esamina(citta: str, radice: Path, fino_a: str | None) -> dict | None:
    """Le revisioni di una citta': quante, in quanti giorni, quanto pesano."""
    cartella = radice / "data" / "raw" / "gtfs" / citta
    if not cartella.is_dir():
        print(f"  [{citta}] cartella assente: {cartella}")
        return None
    archivi = sorted(cartella.glob("*.zip"))
    if fino_a:
        archivi = [a for a in archivi if a.stem.split("_")[0] <= fino_a]
    if not archivi:
        print(f"  [{citta}] nessun archivio")
        return None

    date_revisioni = [a.stem.split("_")[0] for a in archivi]
    dimensioni = [a.stat().st_size for a in archivi]
    # I giorni coperti sono quelli fra la prima e l'ultima revisione compresi, non
    # il numero di revisioni: e' il denominatore che rende "quindici su quindici"
    # e "cinque su quindici" confrontabili fra due citta' che aggiornano diversamente.
    primo, ultimo = date.fromisoformat(date_revisioni[0]), date.fromisoformat(date_revisioni[-1])
    giorni = (ultimo - primo).days + 1
    return {
        "citta": citta,
        "contato_il": date.today().isoformat(),
        "fino_a": fino_a or "",
        "prima_revisione": date_revisioni[0],
        "ultima_revisione": date_revisioni[-1],
        "giorni_coperti": giorni,
        "revisioni": len(archivi),
        "revisioni_per_giorno": len(archivi) / giorni,
        "byte_min": min(dimensioni),
        "byte_max": max(dimensioni),
        "byte_medi": sum(dimensioni) / len(dimensioni),
        "mb_medi": sum(dimensioni) / len(dimensioni) / MB,
        "mb_totali": sum(dimensioni) / MB,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG",
                        help="ignora le revisioni successive, per contare sulla "
                             "stessa finestra delle altre misure")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    print("=" * 78)
    print("LE REVISIONI DELL'ORARIO STATICO")
    print("=" * 78)
    righe = [r for citta in argomenti.citta
             if (r := esamina(citta, argomenti.radice, argomenti.fino_a))]
    if not righe:
        print("nessuna citta' utilizzabile")
        return 1

    for r in righe:
        print(f"\n  === {r['citta']} ===")
        print(f"  {r['revisioni']} revisioni distinte su {r['giorni_coperti']} giorni "
              f"({r['prima_revisione']} - {r['ultima_revisione']}), "
              f"una ogni {1 / r['revisioni_per_giorno']:.1f} giorni")
        print(f"  peso: {r['mb_medi']:.1f} MB in media, da {r['byte_min']:,} a "
              f"{r['byte_max']:,} byte")

    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    destinazione = risultati / "archivi_statici.csv"
    pd.DataFrame(righe).to_csv(destinazione, index=False)
    print(f"\nscritto {destinazione} ({len(righe)} righe)")
    print()
    print("Se avessimo scaricato il GTFS una volta sola, ogni ritardo calcolato su")
    print("una giornata precedente sarebbe uno scostamento da un orario che quel")
    print("giorno non era in vigore: non un'eccezione, ma un numero plausibile e falso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
