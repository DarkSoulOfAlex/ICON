"""Test del ponte fra la tabella stimata e il contratto del pianificatore.

Qui non si collauda un modello ma una **traduzione**: da una massa sui bin a una
distribuzione continua. Un errore di traduzione non fa fallire nulla a valle, fa
uscire probabilita' sbagliate che sembrano giuste, e per questo i test verificano
le proprieta' che una distribuzione deve avere in quanto tale - ripartizione
monotona fra zero e uno, quantile inverso della ripartizione, campione che
riproduce la ripartizione - e non solo qualche valore.

Le due assunzioni dichiarate nel modulo, uniforme dentro i bin limitati ed
esponenziale nei due aperti, hanno ciascuna il proprio test: la prima si vede
dalla ripartizione lineare a tratti, la seconda dal fatto che la media della coda
sia quella misurata e non un'altra.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.delays.bayesiano import (
    ErroreBayesiano,
    Forma,
    MassaDiscreta,
    ModelloBayesiano,
    quando_cade,
)
from src.delays.contesto import N_FASCE, N_GIORNI, Codifica
from src.delays.interfaccia import Tratta, assicura_utilizzabile
from src.delays.rete import Livello, stima

BORDI = (-300.0, -60.0, 0.0, 120.0, 300.0, 900.0, 1800.0)
# Medie plausibili dentro ciascun bin: le due esterne stanno oltre il proprio bordo,
# come accadrebbe misurandole sui dati veri.
MEDIE = np.array([-700.0, -150.0, -30.0, 60.0, 200.0, 550.0, 1300.0, 3000.0])
N_BIN = len(BORDI) + 1


def _forma() -> Forma:
    return Forma(bordi=BORDI, medie=MEDIE)


def _massa(p: list[float]) -> MassaDiscreta:
    return MassaDiscreta(np.array(p, dtype=float), _forma())


def _uniforme() -> MassaDiscreta:
    return _massa([1 / N_BIN] * N_BIN)


# --- la traduzione produce una distribuzione, non qualcosa che le somiglia ------

def test_la_ripartizione_e_monotona_e_sta_fra_zero_e_uno():
    d = _uniforme()
    x = np.linspace(-5000, 8000, 4001)
    y = d.cdf_vettoriale(x)
    assert np.all(np.diff(y) >= -1e-12)
    assert np.all((y >= 0.0) & (y <= 1.0))


def test_la_ripartizione_tende_a_zero_e_a_uno():
    d = _uniforme()
    assert d.cdf(-10_000_000) == pytest.approx(0.0, abs=1e-9)
    assert d.cdf(10_000_000) == pytest.approx(1.0, abs=1e-9)


def test_la_massa_di_ciascun_bin_e_quella_dichiarata():
    """La ripartizione ai bordi deve restituire le probabilita' di partenza."""
    p = [0.05, 0.10, 0.20, 0.25, 0.15, 0.10, 0.10, 0.05]
    d = _massa(p)
    ai_bordi = d.cdf_vettoriale(np.array(BORDI))
    assert np.allclose(ai_bordi, np.cumsum(p)[:-1], atol=1e-9)


def test_il_quantile_inverte_la_ripartizione():
    d = _massa([0.05, 0.10, 0.20, 0.25, 0.15, 0.10, 0.10, 0.05])
    for q in (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99):
        assert d.cdf(d.quantile(q)) == pytest.approx(q, abs=1e-6)


def test_il_campione_riproduce_la_ripartizione():
    """Un campionamento scollegato dalla ripartizione non lo troverebbe nessuno."""
    d = _massa([0.05, 0.10, 0.20, 0.25, 0.15, 0.10, 0.10, 0.05])
    campione = d.campiona(200_000, np.random.default_rng(3))
    for x in (-300.0, 0.0, 300.0, 1800.0):
        assert float(np.mean(campione <= x)) == pytest.approx(d.cdf(x), abs=0.01)


# --- le due assunzioni dichiarate, una per volta --------------------------------

def test_dentro_un_bin_limitato_la_ripartizione_e_lineare():
    """E' l'uniforme, cioe' la massima entropia dato il solo intervallo."""
    d = _massa([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0])   # tutto nel bin [0, 120]
    x = np.linspace(0.0, 120.0, 25)
    y = d.cdf_vettoriale(x)
    assert np.allclose(y, x / 120.0, atol=1e-9)


def test_la_coda_superiore_ha_la_media_misurata():
    """E' l'esponenziale, cioe' la massima entropia data la media sulla semiretta."""
    d = _massa([0.0] * (N_BIN - 1) + [1.0])
    assert d.media() == pytest.approx(MEDIE[-1])
    campione = d.campiona(400_000, np.random.default_rng(5))
    assert float(campione.mean()) == pytest.approx(MEDIE[-1], rel=0.02)
    assert float(campione.min()) >= BORDI[-1] - 1e-6


def test_la_coda_inferiore_ha_la_media_misurata():
    d = _massa([1.0] + [0.0] * (N_BIN - 1))
    assert d.media() == pytest.approx(MEDIE[0])
    campione = d.campiona(400_000, np.random.default_rng(7))
    assert float(campione.mean()) == pytest.approx(MEDIE[0], rel=0.02)
    assert float(campione.max()) <= BORDI[0] + 1e-6


def test_la_media_usa_i_valori_misurati_e_non_i_punti_medi():
    """Nei bin aperti un punto medio non esiste, e inventarlo falserebbe la media."""
    p = np.array([0.1, 0.1, 0.1, 0.2, 0.2, 0.1, 0.1, 0.1])
    assert _massa(list(p)).media() == pytest.approx(float(p @ MEDIE))


# --- il modello, e i suoi ripieghi ----------------------------------------------

def _fattori(codifica: Codifica, celle: np.ndarray) -> tuple[np.ndarray, ...]:
    """Decodifica le celle fini nei fattori, per poterle ricodificare a ogni grado."""
    nb, nf, ng = codifica.n_bin, N_FASCE, N_GIORNI
    bin_monte = celle % nb
    resto = celle // nb
    giorno = resto % ng
    fascia = (resto // ng) % nf
    linea = resto // (ng * nf)
    return linea, fascia, giorno, bin_monte


def _modello_finto(n_linee: int = 3) -> ModelloBayesiano:
    """Un modello su una codifica minuscola, con celle riconoscibili a occhio."""
    codifica = Codifica(tipo_di_linea=np.zeros(n_linee, dtype=np.int64), n_tipi=1,
                        n_bin=N_BIN)
    g = np.random.default_rng(11)
    quante = codifica.quante(4)
    celle = g.integers(0, quante, size=20_000)
    valori = g.integers(0, N_BIN, size=20_000)
    # La scala completa, come quella vera: saltare i livelli intermedi darebbe una
    # mappa dei genitori che non combacia, ed e' bene che il codice lo rifiuti.
    livelli = []
    for grado in range(5):
        codici = codifica.celle(grado, *_fattori(codifica, celle))
        livelli.append(Livello(f"grado{grado}", codici, valori, codifica.quante(grado),
                               None if grado == 0 else codifica.padre(grado)))
    modello = stima(livelli, N_BIN, alfa=1.0)
    return ModelloBayesiano(modello, codifica, _forma(),
                            {f"linea{i}": i for i in range(n_linee)},
                            np.full(N_BIN, 1.0 / N_BIN), "prova", "misti")


def _tratta(route: str, ritardo_a_monte: int | None) -> Tratta:
    return Tratta(citta="prova", route_id=route, trip_id="t1", stop_id="s1",
                  stop_sequence=4, orario_programmato=1_788_000_000,
                  ritardo_a_monte=ritardo_a_monte)


def test_il_modello_appreso_non_e_sintetico():
    """Il presidio della Fase 2 deve lasciarlo passare, e sarebbe grave il contrario."""
    modello = _modello_finto()
    assert modello.sintetico is False
    assicura_utilizzabile(modello)
    assert "bayesiano" in modello.nome and "misti" in modello.nome


def test_un_ritardo_a_monte_noto_seleziona_una_riga_sola():
    modello = _modello_finto()
    fascia, giorno = quando_cade(1_788_000_000)
    atteso = modello.modello.finale[modello.codifica.celle(
        4, np.array([1]), np.array([fascia]), np.array([giorno]), np.array([3]))][0]
    ottenuta = modello.distribuzione(_tratta("linea1", 60)).p
    assert np.allclose(ottenuta, atteso)


def test_senza_ritardo_a_monte_si_marginalizza_invece_di_inventare():
    """Alla prima fermata nessuno ha osservato nulla: si media, non si sceglie."""
    modello = _modello_finto()
    fascia, giorno = quando_cade(1_788_000_000)
    righe = modello.modello.finale[modello.codifica.celle(
        4, np.array([1]), np.array([fascia]), np.array([giorno]), np.arange(N_BIN))]
    atteso = np.full(N_BIN, 1.0 / N_BIN) @ righe
    ottenuta = modello.distribuzione(_tratta("linea1", None)).p
    assert np.allclose(ottenuta, atteso)
    assert modello.diagnostica()["tratte_senza_ritardo_a_monte"] == 1


def test_una_linea_mai_vista_ripiega_sul_livello_grossolano():
    """E' il comportamento per cui la scala di risalita esiste, e va contato."""
    modello = _modello_finto()
    distribuzione = modello.distribuzione(_tratta("linea_nuova", 60))
    assert np.allclose(distribuzione.p, modello.modello.tabelle[0][3])
    assert modello.diagnostica()["linee_ignote"] == 1
    assert modello.diagnostica()["tratte_servite"] == 1


def test_la_fascia_e_calcolata_come_nella_stima():
    """Se il pianificatore contasse le fasce a modo suo, interrogherebbe altre celle."""
    fascia, giorno = quando_cade(1_788_000_000)
    assert 0 <= fascia < N_FASCE and 0 <= giorno < N_GIORNI


# --- incoerenze che i dati veri non attraversano --------------------------------

@pytest.mark.parametrize("costruzione, messaggio", [
    (lambda: Forma(bordi=BORDI, medie=np.zeros(3)), "medie per"),
    (lambda: Forma(bordi=(0.0, 0.0), medie=np.zeros(3)), "crescenti"),
    (lambda: _massa([1.0] * 3), "probabilita' per"),
    (lambda: _massa([-1.0] + [1.0] * (N_BIN - 1)), "negativa"),
    (lambda: _massa([0.0] * N_BIN), "massa totale"),
    (lambda: _uniforme().quantile(0.0), "fuori da"),
    (lambda: _uniforme().quantile(1.0), "fuori da"),
])
def test_le_incoerenze_vengono_dette(costruzione, messaggio):
    with pytest.raises(ErroreBayesiano, match=messaggio):
        costruzione()


def test_una_tabella_di_forma_sbagliata_viene_rifiutata():
    codifica = Codifica(tipo_di_linea=np.zeros(2, dtype=np.int64), n_tipi=1, n_bin=4)
    modello = stima([Livello("bin", np.zeros(5, dtype=np.int64),
                             np.zeros(5, dtype=np.int64), 4)], 4, alfa=1.0)
    with pytest.raises(ErroreBayesiano, match="incompatibile|codifica a"):
        ModelloBayesiano(modello, codifica, _forma(), {}, np.ones(N_BIN), "x", "y")


def test_un_campione_di_zero_elementi_non_e_un_errore():
    assert _uniforme().campiona(0, np.random.default_rng(1)).size == 0
