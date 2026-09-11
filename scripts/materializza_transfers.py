"""Esegue la base di conoscenza sull'intera rete di ogni citta'.

Produce ``data/processed/transfers_<citta>.parquet``, che e' l'artefatto su cui
poggera' il grafo tempo-espanso della Fase 2, e ``results/kb_rete_intera.csv``, che
riporta il costo dell'esecuzione a piena scala. Quest'ultimo serve al documento:
e' la misura reale, non l'estrapolazione della curva di complessita'.

**Perche' scrive un CSV e non solo a schermo.** Fino alla verifica del 11 settembre
questi numeri esistevano soltanto nel log di un'esecuzione: erano veri quando furono
scritti nel documento e non erano piu' verificabili da nessuno, che e' esattamente il
difetto della voce 70. Undici secondi di grounding non sono un costo che giustifichi
di non rifare la misura: mancava lo sbocco, non il tempo.

Uso:
    python scripts/materializza_transfers.py
    python scripts/materializza_transfers.py --citta torino
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic
from typing import Sequence

RADICE = Path(__file__).resolve().parent.parent
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import pandas as pd  # noqa: E402

from src.gtfs.loader import carica_archivio, fermate_fisiche  # noqa: E402
from src.kb.engine import ErroreKB, esegui, genera_fatti  # noqa: E402

CARTELLA_USCITA = RADICE / "data" / "processed"
RISULTATI = RADICE / "results"


def archivio_piu_recente(citta: str) -> Path:
    archivi = sorted((RADICE / "data" / "raw" / "gtfs" / citta).glob("*.zip"))
    if not archivi:
        raise SystemExit(f"Nessun archivio GTFS per '{citta}'.")
    return archivi[-1]


def materializza_citta(citta: str) -> dict:
    percorso = archivio_piu_recente(citta)
    inizio = monotonic()
    archivio = carica_archivio(percorso, con_stop_times=True)
    fermate = fermate_fisiche(archivio.stops)
    print(
        f"\n=== {citta} ({percorso.name}) ===\n"
        f"  {len(fermate):,} fermate fisiche, archivio letto in {monotonic() - inizio:.0f}s",
        flush=True,
    )

    inizio = monotonic()
    fatti = genera_fatti(archivio)
    tempo_fatti = monotonic() - inizio
    print(f"  {fatti.n_fatti:,} fatti generati in {tempo_fatti:.0f}s: {dict(fatti.conteggi)}", flush=True)

    risultato = esegui(fatti)
    if not risultato.soddisfacibile:
        # Un vincolo ha rifiutato il modello: si rilancia senza vincoli per
        # poter almeno dire quanti trasbordi ci sarebbero stati, e si segnala.
        diagnosi = esegui(fatti, con_vincoli=False)
        raise ErroreKB(
            f"[{citta}] la base di conoscenza e' insoddisfacibile: un vincolo di integrita' "
            f"ha rifiutato il modello. Senza vincoli il modello esiste e contiene "
            f"{len(diagnosi.trasbordi):,} trasbordi, quindi il rifiuto viene da un vincolo e "
            "non da un errore nelle regole. Vanno ispezionati i dati della citta'."
        )

    print(
        f"  atomi {risultato.atomi:,} | grounding {risultato.tempo_grounding:.1f}s | "
        f"solving {risultato.tempo_solving:.2f}s | {len(risultato.trasbordi):,} trasbordi",
        flush=True,
    )
    tabella = risultato.trasbordi
    print(
        f"  di cui a piedi {int(tabella['a_piedi'].sum()):,}, "
        f"accessibili {int(tabella['accessibile'].sum()):,}, "
        f"utili {int(tabella['utile'].sum()):,}",
        flush=True,
    )

    CARTELLA_USCITA.mkdir(parents=True, exist_ok=True)
    destinazione = CARTELLA_USCITA / f"transfers_{citta}.parquet"
    tabella.to_parquet(destinazione, index=False)
    print(f"  scritto {destinazione.name} ({destinazione.stat().st_size / 1024:.0f} KB)", flush=True)
    return {
        "citta": citta,
        "archivio": percorso.name,
        "fermate_fisiche": len(fermate),
        "fatti": fatti.n_fatti,
        "secondi_generazione_fatti": round(tempo_fatti, 2),
        "atomi": risultato.atomi,
        "regole": risultato.regole,
        "secondi_grounding": round(risultato.tempo_grounding, 2),
        "secondi_solving": round(risultato.tempo_solving, 2),
        "trasbordi": len(tabella),
        "trasbordi_a_piedi": int(tabella["a_piedi"].sum()),
        "trasbordi_accessibili": int(tabella["accessibile"].sum()),
        "trasbordi_utili": int(tabella["utile"].sum()),
        "corse": int(archivio.trips["trip_id"].nunique()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    analizzatore = argparse.ArgumentParser(description=__doc__)
    analizzatore.add_argument("--citta", default="torino,roma")
    argomenti = analizzatore.parse_args(argv)
    righe = [materializza_citta(c.strip()) for c in argomenti.citta.split(",")]
    if righe:
        RISULTATI.mkdir(parents=True, exist_ok=True)
        destinazione = RISULTATI / "kb_rete_intera.csv"
        pd.DataFrame(righe).to_csv(destinazione, index=False)
        print()
        print(f"scritto {destinazione} ({len(righe)} righe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
