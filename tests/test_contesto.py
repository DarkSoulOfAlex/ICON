"""Test della codifica del contesto e dell'estrazione delle coppie.

La proprieta' che conta e' una sola, e va verificata sul **prodotto cartesiano
completo** dei fattori e non su un campione: la mappa dei genitori e la codifica
del livello superiore devono dire la stessa cosa su ogni cella possibile. Se
concordassero solo sulle celle osservate, la risalita funzionerebbe dove non serve
e sbaglierebbe genitore dove e' l'unica cosa che regge la stima.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from src.delays.contesto import (
    LIVELLI,
    N_FASCE,
    N_GIORNI,
    Codifica,
    ErroreContesto,
    constatazione,
    coppie_contigue,
    fascia_oraria,
    tipo_di_giorno,
    ultima_revisione,
)

# Tipi volutamente sbilanciati: sei linee su tre tipi, con un tipo che ne ha una
# sola, perche' una ripartizione uniforme nasconderebbe gli errori di divisione.
TIPI = np.array([0, 0, 0, 1, 1, 2], dtype=np.int64)


def _codifica(n_bin: int = 4) -> Codifica:
    return Codifica(tipo_di_linea=TIPI, n_tipi=3, n_bin=n_bin)


def _tutte_le_osservazioni(c: Codifica) -> tuple[np.ndarray, ...]:
    """Ogni combinazione di linea, fascia, giorno e bin: nessuna esclusa."""
    combinazioni = list(itertools.product(
        range(c.n_linee), range(N_FASCE), range(N_GIORNI), range(c.n_bin)))
    colonne = np.array(combinazioni, dtype=np.int64).T
    return tuple(colonne)


@pytest.mark.parametrize("livello", range(1, len(LIVELLI)))
def test_la_mappa_dei_genitori_concorda_con_la_codifica_di_sopra(livello):
    """Su ogni cella possibile, non solo su quelle che i dati visitano."""
    c = _codifica()
    linea, fascia, giorno, bin_monte = _tutte_le_osservazioni(c)
    figlie = c.celle(livello, linea, fascia, giorno, bin_monte)
    attese = c.celle(livello - 1, linea, fascia, giorno, bin_monte)
    assert (c.padre(livello)[figlie] == attese).all()


@pytest.mark.parametrize("livello", range(len(LIVELLI)))
def test_ogni_cella_del_livello_e_raggiunta_da_qualche_osservazione(livello):
    """La numerosita' dichiarata non deve essere ne' in eccesso ne' in difetto.

    In eccesso significherebbe tabelle con righe irraggiungibili, che sprecano
    memoria e falsano ogni conteggio di copertura; in difetto significherebbe un
    indice fuori intervallo alla prima osservazione insolita.
    """
    c = _codifica()
    celle = c.celle(livello, *_tutte_le_osservazioni(c))
    assert sorted(set(celle.tolist())) == list(range(c.quante(livello)))


def test_la_mappa_dei_genitori_e_definita_anche_dove_non_e_passato_nessuno():
    """E' la ragione per cui la mappa si calcola dalla codifica e non dai dati."""
    c = _codifica()
    padre = c.padre(4)
    assert padre.size == c.quante(4)
    assert int(padre.max()) < c.quante(3)
    # La linea 5 e' l'unica del tipo 2: se la mappa fosse dedotta da un campione
    # che non la contiene, le sue celle finirebbero sotto un tipo sbagliato.
    sola = c.celle(4, np.array([5]), np.array([2]), np.array([1]), np.array([3]))
    assert padre[sola][0] == c.celle(3, np.array([5]), np.array([2]),
                                     np.array([1]), np.array([3]))[0]


def test_i_livelli_estremi_non_hanno_genitore_o_non_esistono():
    c = _codifica()
    with pytest.raises(ErroreContesto, match="non ha un genitore"):
        c.padre(0)
    with pytest.raises(ErroreContesto, match="non ha un genitore"):
        c.padre(len(LIVELLI))
    with pytest.raises(ErroreContesto, match="inesistente"):
        c.celle(9, np.array([0]), np.array([0]), np.array([0]), np.array([0]))


def test_la_scala_restituisce_le_mappe_in_ordine():
    c = _codifica()
    scala = c.scala()
    assert len(scala) == len(LIVELLI) - 1
    assert [m.size for m in scala] == [c.quante(i) for i in range(1, len(LIVELLI))]


@pytest.mark.parametrize("tipi, n_tipi, messaggio", [
    (np.array([], dtype=np.int64), 3, "nessuna linea"),
    (np.array([0, 1], dtype=np.int64), 0, "0 tipi"),
    (np.array([0, 7], dtype=np.int64), 3, "fuori dai tipi"),
    (np.array([0, -1], dtype=np.int64), 3, "fuori dai tipi"),
])
def test_una_codifica_incoerente_viene_detta(tipi, n_tipi, messaggio):
    with pytest.raises(ErroreContesto, match=messaggio):
        Codifica(tipo_di_linea=tipi, n_tipi=n_tipi, n_bin=4)


# --- i fattori, uno per uno ------------------------------------------------------

def test_le_fasce_orarie_coprono_le_ventiquattro_ore():
    fasce = fascia_oraria(np.arange(24))
    assert fasce.min() == 0 and fasce.max() == N_FASCE - 1
    assert (np.diff(fasce) >= 0).all()
    assert fascia_oraria(np.array([5]))[0] == 0        # notte
    assert fascia_oraria(np.array([6]))[0] == 1        # il confine appartiene a dopo
    assert fascia_oraria(np.array([23]))[0] == N_FASCE - 1


def test_il_sabato_e_un_tipo_di_giorno_a_se():
    assert tipo_di_giorno(np.arange(7)).tolist() == [0, 0, 0, 0, 0, 1, 2]


# --- estrazione delle coppie -----------------------------------------------------

def test_si_tiene_l_ultima_revisione_di_ciascun_passaggio():
    """Tre revisioni dello stesso passaggio, pubblicate fuori ordine."""
    codice = np.array([1, 1, 1, 1], dtype=np.int64)
    sequenza = np.array([2, 2, 2, 3], dtype=np.int64)
    istante = np.array([500, 900, 100, 700], dtype=np.int64)
    assert ultima_revisione(codice, sequenza, istante).tolist() == [False, True, False, True]


def test_l_ultima_revisione_distingue_le_corse():
    """Due corse diverse alla stessa fermata non sono lo stesso passaggio."""
    codice = np.array([1, 2, 1, 2], dtype=np.int64)
    sequenza = np.array([5, 5, 5, 5], dtype=np.int64)
    istante = np.array([100, 100, 200, 50], dtype=np.int64)
    assert ultima_revisione(codice, sequenza, istante).tolist() == [False, True, True, False]


def test_l_ultima_revisione_su_una_giornata_vuota():
    vuoto = np.array([], dtype=np.int64)
    assert ultima_revisione(vuoto, vuoto, vuoto).size == 0
    with pytest.raises(ErroreContesto, match="stessa lunghezza"):
        ultima_revisione(vuoto, np.array([1]), vuoto)


def test_le_fermate_non_contigue_non_fanno_coppia():
    """Fra la fermata 4 e la 7 c'e' un salto, e la transizione non e' di una fermata."""
    codice = np.array([1, 1, 1, 2], dtype=np.int64)
    sequenza = np.array([3, 4, 7, 1], dtype=np.int64)
    assert coppie_contigue(codice, sequenza).tolist() == [True, False, False]
    assert coppie_contigue(np.array([1]), np.array([1])).size == 0


def test_una_constatazione_e_un_passaggio_gia_avvenuto():
    """Il segnale non esiste in GTFS-RT e si deduce dal confronto con l'istante del feed."""
    programmato = np.array([1000, 1000, 1000], dtype=np.float64)
    ritardo = np.array([60.0, 60.0, -30.0])
    feed = np.array([1100.0, 1000.0, 1000.0])
    assert constatazione(programmato, ritardo, feed).tolist() == [True, False, True]
