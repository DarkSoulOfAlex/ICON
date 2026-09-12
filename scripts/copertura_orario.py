"""Quante osservazioni trovano il proprio orario programmato, giorno per giorno.

Il ritardo e' uno scostamento da un orario programmato: se l'osservazione non trova
la propria corsa nell'archivio statico in vigore quel giorno, il ritardo **non e'
calcolabile** e quella riga non entra in nulla - non nella stima, non nel
backtesting. Finora nessuna misura diceva quanto spesso accadesse, e la conseguenza
si e' manifestata altrove e senza spiegazione: una giornata romana che contribuiva
sette coppie rigiocabili invece di trenta, attribuita per un po' a un consolidamento
parziale che non c'era.

Lo script riporta, per ciascuna giornata:

- quante righe portano un ``orario_programmato``, cioe' quante hanno trovato la
  corsa nell'archivio;
- quanti dei ``trip_id`` visti nel feed esistono nell'archivio in vigore quel
  giorno.

Il secondo e' la misura della causa, il primo del suo effetto. Tenerli distinti
serve: una quota bassa di righe con orario potrebbe venire da poche corse molto
frequentate o da molte corse rare, e solo il conteggio sui ``trip_id`` distingue i
due casi.

**Perche' l'archivio si legge dall'indice e non si sceglie qui.** L'archivio in
vigore in una giornata e' una proprieta' di quella giornata, registrata quando la
giornata e' stata consolidata. Sceglierne un altro adesso - il piu' recente, per
esempio - misurerebbe una cosa diversa da quella che il consolidamento ha fatto, e
la misura direbbe che va tutto bene proprio nei giorni in cui non andava.

    python scripts/copertura_orario.py --fino-a 2026-09-09
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src.delays.contesto import SOGLIA_COPERTURA_ORARIO  # noqa: E402
from src.gtfs.indice_statico import carica_indice, versione_valida  # noqa: E402

CITTA = ("roma", "torino")


def trip_dell_archivio(percorso: Path) -> set[str]:
    """I ``trip_id`` dichiarati da un archivio, senza aprirne le fermate.

    Si legge il solo ``trips.txt``: per rispondere a "questa corsa esiste?" gli
    ``stop_times`` non servono, e su Roma pesano quaranta volte tanto.
    """
    with zipfile.ZipFile(percorso) as z:
        trips = pd.read_csv(io.BytesIO(z.read("trips.txt")), usecols=["trip_id"],
                            dtype=str)
    return set(trips["trip_id"])


def esamina(citta: str, percorso: Path, cartella_gtfs: Path,
            indice: dict) -> dict | None:
    giornata = percorso.stem
    tabella = pq.read_table(percorso, columns=["trip_id", "orario_programmato"])
    prog = tabella["orario_programmato"].to_numpy(zero_copy_only=False).astype("float64")
    osservati = set(tabella["trip_id"].to_pylist())
    con_orario = int(np.isfinite(prog).sum())

    versione = versione_valida(indice, giornata)
    if versione is None:
        return None
    nome = versione["file"]
    statici = trip_dell_archivio(cartella_gtfs / nome)
    comuni = len(osservati & statici)
    return {
        "citta": citta, "giornata": giornata, "archivio": nome,
        "righe": int(prog.size), "righe_con_orario": con_orario,
        "quota_con_orario": con_orario / max(1, prog.size),
        "trip_nel_feed": len(osservati), "trip_nell_archivio": len(statici),
        "trip_in_comune": comuni,
        "quota_trip_riconosciuti": comuni / max(1, len(osservati)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    print("=" * 78)
    print("QUANTE OSSERVAZIONI TROVANO IL PROPRIO ORARIO PROGRAMMATO")
    print("=" * 78)

    righe: list[dict] = []
    for citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / citta
        cartella_gtfs = argomenti.radice / "data" / "raw" / "gtfs" / citta
        giorni = sorted(cartella.glob("*.parquet"))
        if argomenti.fino_a:
            giorni = [g for g in giorni if g.stem <= argomenti.fino_a]
        if not giorni:
            print(f"  [{citta}] nessun parquet")
            continue
        indice = carica_indice(cartella_gtfs / "index.json", citta)
        finestra = giorni[-1].stem
        print(f"\n  === {citta} ({len(giorni)} giornate, fino al {finestra}) ===")
        print(f"  {'giornata':<12} {'righe':>12} {'con orario':>11} "
              f"{'trip nel feed':>14} {'riconosciuti':>13}")
        for percorso in giorni:
            r = esamina(citta, percorso, cartella_gtfs, indice)
            if r is None:
                print(f"  {percorso.stem:<12} nessun archivio in vigore")
                continue
            r["finestra"] = finestra
            righe.append(r)
            avviso = ("   <== la maggior parte delle corse non e' nell'archivio"
                      if r["quota_con_orario"] < SOGLIA_COPERTURA_ORARIO else "")
            print(f"  {r['giornata']:<12} {r['righe']:>12,} "
                  f"{r['quota_con_orario']:>10.1%} {r['trip_nel_feed']:>14,} "
                  f"{r['quota_trip_riconosciuti']:>12.1%}{avviso}")

    if not righe:
        print("nessuna giornata utilizzabile")
        return 1
    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    destinazione = risultati / "copertura_orario.csv"
    pd.DataFrame(righe).to_csv(destinazione, index=False)
    print(f"\nscritto {destinazione} ({len(righe)} righe)")
    print()
    print("Una riga senza orario programmato non ha un ritardo, e una giornata che")
    print("ne ha molte contribuisce poche coppie rigiocabili al backtesting: non e'")
    print("un problema della raccolta ma dell'orario pubblicato quel giorno.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
