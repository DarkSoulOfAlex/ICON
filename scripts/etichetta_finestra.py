"""L'etichetta della finestra di stima, da passare a --fino-a.

La raccolta continua mentre si misura: due esecuzioni dello stesso script cadono su
giornate diverse, e il confronto fra un giro e l'altro attribuirebbe alla correzione
uno spostamento che e' solo un giorno nuovo (e' il motivo per cui ``stima_rete.py``
ha ``--fino-a``). Questo script stampa la **data dell'ultima giornata gia'
consolidata**, per le due citta': il valore da passare a ``--fino-a`` per fissare la
finestra e rendere due esecuzioni confrontabili.

    python scripts/etichetta_finestra.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

CITTA = ("roma", "torino")


def ultima_giornata(osservazioni: Path, citta: str) -> str | None:
    """L'ultima data per cui esiste un parquet di osservazioni.

    Il nome del file e' la data di servizio in forma ``AAAA-MM-GG``; una giornata a
    meta' viene consolidata lo stesso, quindi l'ultima presente e' l'ultima che si
    puo' usare senza rischiare di includere un giorno incompleto a meta'.
    """
    cartella = osservazioni / citta
    if not cartella.is_dir():
        return None
    giorni = sorted(p.stem for p in cartella.glob("*.parquet"))
    return giorni[-1] if giorni else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)
    osservazioni = argomenti.radice / "data" / "processed" / "osservazioni"
    ultime: list[str] = []
    for citta in CITTA:
        ultima = ultima_giornata(osservazioni, citta)
        print(f"  {citta:<7}: {ultima if ultima else 'nessun parquet'}")
        if ultima:
            ultime.append(ultima)
    if ultime:
        # La finestra comune e' l'ultima giornata disponibile per tutte le
        # citta': usare la piu' recente in assoluto taglierebbe fuori una citta' a
        # meta', e il confronto fra le due si romperebbe.
        print(f"\n--fino-a {min(ultime)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
