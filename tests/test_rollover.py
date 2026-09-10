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
from src.delays.contesto import (  # noqa: E402
    GIORNO,
    RESIDUO_PLAUSIBILE,
    maschera_rollover,
)


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


# --- la banda che separa la soglia dai suoi vicini ---------------------------
#
# I test qui sopra usano soltanto due grandezze: +/-86.100, che ha residuo 300 s
# ed e' un salto di giorno per qualunque soglia ragionevole, e +120, che ha
# residuo 86.280 e non lo e' per nessuna. Fra le due c'e' un intervallo che
# nessuno visitava, ed e' esattamente quello in cui il valore della soglia
# decide: decuplicandola da 3.600 a 36.000 l'intera suite restava verde, cioe'
# la costante non era protetta da niente.
#
# Un ritardo di 60.000 s - sedici ore e quaranta - ha residuo 26.400 dalle
# ventiquattro ore: assurdo come ritardo reale, ma **non e' un salto di giorno**,
# e il criterio del residuo deve saperlo distinguere. E' li' che si mette il
# presidio, perche' e' li' che una soglia sbagliata butterebbe via dati veri.

def test_la_banda_fra_le_due_soglie_non_e_un_salto_di_giorno() -> None:
    """Residuo fra 3.600 e 36.000: la soglia attuale NON deve scartare.

    Se qualcuno allargasse `RESIDUO_PLAUSIBILE` fino a coprire questa banda,
    ritardi assurdi ma autentici verrebbero scambiati per salti di giorno e
    tolti dal campione di stima: su Roma sono migliaia di righe al giorno.
    """
    for ritardo in (-60_000, 60_000, -55_000, 55_000, -50_500, 50_500):
        residuo = min(abs(ritardo + GIORNO), abs(ritardo - GIORNO))
        assert 3_600 < residuo < 36_000, f"{ritardo} non e' nella banda ({residuo})"
        assert not bool(maschera_rollover(np.array([float(ritardo)]))[0]), (
            f"{ritardo} s ha residuo {residuo} s dalle ventiquattro ore: e' un "
            f"ritardo assurdo, non un salto di giorno"
        )


def test_il_confine_della_soglia_sta_a_un_ora_esatta() -> None:
    """Il confine e' scritto qui come **numero**, non come la costante stessa.

    Scriverlo come ``GIORNO - RESIDUO_PLAUSIBILE`` sembrerebbe piu' pulito e non
    proverebbe nulla: l'espressione si muove insieme alla costante, quindi il test
    resterebbe verde per qualunque valore le si desse. E' un errore che ho fatto
    scrivendo questo file, ed e' emerso mutando la soglia da 3.600 a 7.200: la
    versione precedente non se ne accorgeva.
    """
    assert RESIDUO_PLAUSIBILE == 3_600, "un'ora, e il documento la motiva cosi'"
    assert GIORNO == 86_400
    for segno in (1, -1):
        dentro = segno * (86_400 - 3_599)
        fuori = segno * (86_400 - 3_601)
        assert bool(maschera_rollover(np.array([float(dentro)]))[0]), dentro
        assert not bool(maschera_rollover(np.array([float(fuori)]))[0]), fuori


def test_una_riga_nella_banda_resta_nel_campione(tmp_path: Path) -> None:
    """La banda vista dal capo giusto: la riga sopravvive alla lettura di una giornata.

    Il test precedente collauda la maschera; questo collauda che la maschera sia
    davvero quella che decide chi entra nella stima.
    """
    base = 1_000_000
    righe = [
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S1", "stop_sequence": 1, "orario_programmato": base,
         "orario_osservato": base + 60_000, "ritardo_secondi": 60_000,
         "timestamp_feed": base + 60, "timestamp_poll": base + 61},
        {"service_date": "2026-09-10", "trip_id": "T1", "route_id": "L1",
         "stop_id": "S2", "stop_sequence": 2, "orario_programmato": base + 300,
         "orario_osservato": base + 300 + 60_100, "ritardo_secondi": 60_100,
         "timestamp_feed": base + 360, "timestamp_poll": base + 361},
    ]
    percorso = _parquet_sintetico(tmp_path / "osservazioni" / "roma", righe)
    indice: dict[str, int] = {}
    dati, scartate, totale = coppie_di_un_giorno(percorso, indice, True)
    assert scartate == 0, "un residuo di 26.400 s non e' un salto di giorno"
    assert totale == 2
    assert dati is not None and dati["secondi_valle"].size == 1
