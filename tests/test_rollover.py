"""Test del branch rollover in coppia_di_un_giorno.

Crea un parquet sintetico con righe che hanno ritardo +/- 86.400 s e verifica
che la maschera le identifichi come salti di giorno e che lo scarto sia
registrato correttamente.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

RADICE = Path(__file__).resolve().parents[0]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from scripts.stima_rete import coppie_di_un_giorno  # noqa: E402


def _parquet_sintetico(cartella: Path, righe: list[dict]) -> Path:
    """Scrive un parquet di prova in ``cartella`` e ne restituisce il percorso."""
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / "2026-09-10.parquet"
    tabella = pa.Table.from_pandas(pd.DataFrame(righe))
    pq.write_table(tabella, percorso)
    return percorso


def test_rollover_negativo_riconosciuto(tmp_path: Path) -> None:
    """Un ritardo di -86.400+300 s e' un salto di giorno, non un ritardo reale."""
    righe = [
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S1", "stop_sequence": 1,
         "orario_programmato": 1_000_000, "orario_osservato": 1_000_000,
         "ritardo_secondi": -86100, "timestamp_feed": 1_000_000,
         "timestamp_poll": 1_000_000},
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S2", "stop_sequence": 2,
         "orario_programmato": 1_000_600, "orario_osservato": 1_000_600,
         "ritardo_secondi": -86100, "timestamp_feed": 1_000_600,
         "timestamp_poll": 1_000_600},
    ]
    percorso = _parquet_sintetico(tmp_path / "osservazioni" / "roma", righe)
    indice: dict[str, int] = {}
    dati, scartate, totale = coppie_di_un_giorno(percorso, indice, True)
    assert scartate == 2, "il rollover negativo va scartato"
    assert totale == 2
    assert dati is None, "nessuna coppia utilizzabile dopo lo scarto"


def test_rollover_positivo_riconosciuto(tmp_path: Path) -> None:
    """Un ritardo di +86.400-300 s e' un salto di giorno, non un ritardo reale."""
    righe = [
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S1", "stop_sequence": 1,
         "orario_programmato": 1_000_000, "orario_osservato": 1_000_000,
         "ritardo_secondi": 86100, "timestamp_feed": 1_000_000,
         "timestamp_poll": 1_000_000},
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S2", "stop_sequence": 2,
         "orario_programmato": 1_000_600, "orario_osservato": 1_000_600,
         "ritardo_secondi": 86100, "timestamp_feed": 1_000_600,
         "timestamp_poll": 1_000_600},
    ]
    percorso = _parquet_sintetico(tmp_path / "osservazioni" / "roma", righe)
    indice: dict[str, int] = {}
    dati, scartate, totale = coppie_di_un_giorno(percorso, indice, True)
    assert scartate == 2, "il rollover positivo va scartato"
    assert totale == 2


def test_rollover_tenuto_non_scarta(tmp_path: Path) -> None:
    """Con scarta_salti=False le righe di rollover restano nel campione."""
    righe = [
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S1", "stop_sequence": 1,
         "orario_programmato": 1_000_000, "orario_osservato": 1_000_000,
         "ritardo_secondi": -86100, "timestamp_feed": 1_000_000,
         "timestamp_poll": 1_000_000},
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S2", "stop_sequence": 2,
         "orario_programmato": 1_000_600, "orario_osservato": 1_000_600,
         "ritardo_secondi": -86100, "timestamp_feed": 1_000_600,
         "timestamp_poll": 1_000_600},
    ]
    percorso = _parquet_sintetico(tmp_path / "osservazioni" / "roma", righe)
    indice: dict[str, int] = {}
    dati, scartate, totale = coppie_di_un_giorno(percorso, indice, False)
    assert scartate == 2, "il rollover e' comunque rilevato"
    assert totale == 2
    assert dati is not None, "con salti tenuti la coppia esiste"


def test_rollover_misto_con_ritardi_reali(tmp_path: Path) -> None:
    """Un giorno con rollover e ritardi reali: solo il rollover va scartato."""
    righe = []
    base = 1_000_000
    for i in range(20):
        righe.append({"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
                      "stop_id": f"S{i}", "stop_sequence": i + 1,
                      "orario_programmato": base + i * 300, "orario_osservato": base + i * 300 + 120,
                      "ritardo_secondi": 120, "timestamp_feed": base + i * 300 + 60,
                      "timestamp_poll": base + i * 300 + 61})
    # Inseriamo due righe di rollover a meta' della corsa
    righe.insert(10, {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
                      "stop_id": "S_ROLLOVER", "stop_sequence": 11,
                      "orario_programmato": base + 3000, "orario_osservato": base + 3000,
                      "ritardo_secondi": 86100, "timestamp_feed": base + 3000,
                      "timestamp_poll": base + 3000})
    cartella = tmp_path / "osservazioni" / "roma"
    percorso = _parquet_sintetico(cartella, righe)
    indice: dict[str, int] = {}
    dati, scartate, totale = coppie_di_un_giorno(percorso, indice, True)
    assert scartate == 1, "solo la riga di rollover va scartata"
    assert totale == 21
    assert dati is not None, "il resto della corsa e' utilizzabile"
    assert dati["secondi_valle"].size > 0, "le coppie normali restano"
