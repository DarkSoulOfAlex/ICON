"""Test dell'etichetta della macchina, che accompagna ogni tempo misurato.

Non c'e' molto da collaudare in una stringa, e proprio per questo vale la pena di
fissare le due proprieta' su cui qualcuno potrebbe contare senza accorgersene: che
sia **stabile** dentro un'esecuzione, altrimenti due righe dello stesso CSV
direbbero macchine diverse, e che contenga la versione di Python, che e' la sola
parte dell'etichetta che cambi senza che cambi l'hardware.
"""

from __future__ import annotations

import sys

import pandas as pd

from src.eval.ambiente import etichetta_macchina, marca_macchina


def test_l_etichetta_e_stabile_dentro_un_esecuzione():
    """Due righe dello stesso CSV devono riportare la stessa macchina."""
    assert etichetta_macchina() == etichetta_macchina()


def test_l_etichetta_dice_la_versione_di_python():
    """E' la parte che cambia senza che cambi l'hardware, e va vista."""
    assert sys.version.split()[0] in etichetta_macchina()
    assert "Python" in etichetta_macchina()


def test_la_colonna_si_aggiunge_in_coda_senza_toccare_il_resto():
    tavola = pd.DataFrame({"citta": ["roma", "torino"], "secondi": [1.0, 2.0]})
    marcata = marca_macchina(tavola)
    assert list(marcata.columns) == ["citta", "secondi", "macchina"]
    assert marcata["macchina"].nunique() == 1
    assert marcata[["citta", "secondi"]].equals(tavola)
    assert "macchina" not in tavola.columns, "l'originale non va modificato"


def test_una_tabella_vuota_non_e_un_errore():
    vuota = pd.DataFrame()
    assert marca_macchina(vuota) is vuota
    assert marca_macchina(None) is None
