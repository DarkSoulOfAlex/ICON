"""Test della stima gerarchica della matrice di transizione.

Vale qui la stessa regola dell'estimatore di informazione mutua: una stima non si
collauda sui dati veri, dove la risposta non e' nota, ma su gerarchie costruite di
cui si conosce la struttura. La differenza e' che qui non c'e' un numero da
ritrovare, bensi' un ordinamento: la scala deve battere fuori campione **entrambi**
gli estremi fra cui si colloca, il livello fine stimato da solo e quello
grossolano stimato da solo.

I casi sono speculari e servono tutti e tre. Se le celle fini differiscono davvero
ma i dati sono pochi, la scala deve battere il fine, che si affiderebbe a rumore.
Se le celle fini non differiscono affatto, la scala non deve peggiorare il
grossolano, che li' e' il modello giusto. Se differiscono e i dati abbondano, la
scala deve raggiungere il fine, senza restare ancorata a un genitore che non
serve piu'. Una stima che facesse sempre media col genitore passerebbe il secondo
caso e fallirebbe il terzo; una che lo ignorasse sempre farebbe l'opposto.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.delays.rete import (
    CANDIDATI,
    ErroreRete,
    Livello,
    componi,
    conta,
    mappa_annidata,
    stima,
    tara,
)

N_VALORI = 8
GRUPPI = 20
PER_GRUPPO = 30
FINI = GRUPPI * PER_GRUPPO
# Ogni cella fine appartiene al gruppo dato dalla divisione intera: e' la codifica
# annidata piu' semplice, e rende la mappa dei genitori verificabile a occhio.
PADRE = np.arange(FINI, dtype=np.int64) // PER_GRUPPO


def _distribuzioni(concentrazione: float | None, seme: int) -> np.ndarray:
    """Le distribuzioni vere delle celle fini, e quanto somigliano al loro gruppo.

    ``concentrazione`` alta significa celle fini quasi identiche al gruppo, cioe'
    una gerarchia che non porta informazione al livello fine; ``None`` significa
    celle fini indipendenti dal gruppo, cioe' una gerarchia che al livello fine
    porta tutta l'informazione che c'e'.
    """
    g = np.random.default_rng(seme)
    gruppi = g.dirichlet(np.ones(N_VALORI), size=GRUPPI)
    if concentrazione is None:
        return g.dirichlet(np.full(N_VALORI, 0.5), size=FINI)
    return np.stack([g.dirichlet(concentrazione * gruppi[PADRE[c]]) for c in range(FINI)])


def _campione(vere: np.ndarray, quante_per_cella: np.ndarray,
              seme: int) -> tuple[np.ndarray, np.ndarray]:
    """Estrae osservazioni dalle distribuzioni vere, con numerosita' assegnata."""
    g = np.random.default_rng(seme)
    celle = np.repeat(np.arange(FINI, dtype=np.int64), quante_per_cella)
    valori = np.array([g.choice(N_VALORI, p=vere[c]) for c in celle], dtype=np.int64)
    return celle, valori


def _numerosita_disuguale(seme: int, scala: float = 1.0) -> np.ndarray:
    """Poche celle molto popolose e molte quasi vuote, come in una rete reale.

    Una numerosita' uniforme renderebbe il test facile per la ragione sbagliata:
    la risalita serve proprio dove i dati scarseggiano, e con celle tutte ugualmente
    popolate non ci sarebbe niente da far reggere al genitore.
    """
    g = np.random.default_rng(seme)
    peso = g.pareto(1.5, size=FINI) + 0.2
    return np.maximum(0, (peso / peso.mean() * 12 * scala).astype(np.int64))


def _scala(celle: np.ndarray, valori: np.ndarray) -> list[Livello]:
    return [
        Livello("gruppo", PADRE[celle], valori, GRUPPI),
        Livello("cella", celle, valori, FINI, PADRE),
    ]


def _perdita_migliore(livelli: list[Livello], celle_v: np.ndarray,
                      valori_v: np.ndarray) -> float:
    """La perdita col migliore fra i candidati: il confronto dev'essere alla pari.

    Confrontare la scala tarata contro estremi con un alfa fissato a caso non
    direbbe nulla: ogni estremo va messo nelle sue condizioni migliori.
    """
    esito = tara(livelli, celle_v, valori_v, N_VALORI, passate=2)
    return esito.perdita


def _tre_perdite(concentrazione: float | None, scala_dati: float,
                 seme: int) -> tuple[float, float, float]:
    """Perdita fuori campione di scala, livello fine da solo, grossolano da solo."""
    vere = _distribuzioni(concentrazione, seme)
    celle_a, valori_a = _campione(vere, _numerosita_disuguale(seme + 1, scala_dati), seme + 2)
    celle_v, valori_v = _campione(vere, _numerosita_disuguale(seme + 3, 0.5), seme + 4)
    gerarchica = _perdita_migliore(_scala(celle_a, valori_a), celle_v, valori_v)
    fine = _perdita_migliore(
        [Livello("cella", celle_a, valori_a, FINI)], celle_v, valori_v)
    grossolana = _perdita_migliore(
        [Livello("gruppo", PADRE[celle_a], valori_a, GRUPPI)], PADRE[celle_v], valori_v)
    return gerarchica, fine, grossolana


# --- il caso centrale: gerarchia vera, dati scarsi -------------------------------

def test_la_scala_batte_entrambi_gli_estremi():
    """Celle fini che differiscono dal gruppo, ma con pochi dati ciascuna.

    E' la situazione del progetto: la linea conta, e quasi nessuna linea ha da sola
    abbastanza passaggi per stimare otto probabilita' condizionate.
    """
    gerarchica, fine, grossolana = _tre_perdite(concentrazione=8.0, scala_dati=1.0, seme=11)
    assert gerarchica < fine
    assert gerarchica < grossolana


def test_il_vantaggio_sulla_scala_non_dipende_dal_seme():
    """Tre gerarchie diverse, perche' un solo campione potrebbe essere fortunato."""
    for seme in (21, 41, 61):
        gerarchica, fine, grossolana = _tre_perdite(8.0, 1.0, seme)
        assert gerarchica < min(fine, grossolana), f"seme {seme}"


# --- i due casi speculari --------------------------------------------------------

def test_senza_differenze_fra_le_celle_fini_la_scala_non_peggiora_il_grossolano():
    """Celle fini identiche al gruppo: il modello giusto e' quello grossolano.

    La scala deve accorgersene tarando una concentrazione alta, e finire
    indistinguibile dal grossolano. Se peggiorasse, significherebbe che il livello
    fine viene aggiunto comunque e paga il proprio rumore.
    """
    gerarchica, _, grossolana = _tre_perdite(concentrazione=1e6, scala_dati=1.0, seme=31)
    assert gerarchica <= grossolana + 0.01


def test_con_differenze_forti_e_dati_abbondanti_la_scala_raggiunge_il_fine():
    """Celle fini indipendenti dal gruppo e molte osservazioni: il genitore e' inutile.

    La scala deve tarare una concentrazione bassa e finire indistinguibile dal
    livello fine. Se restasse ancorata al genitore, la media con una distribuzione
    che non ha nulla a che vedere con la cella la danneggerebbe.
    """
    gerarchica, fine, grossolana = _tre_perdite(concentrazione=None, scala_dati=40.0,
                                                seme=51)
    assert gerarchica <= fine + 0.01
    assert gerarchica < grossolana - 0.5


# --- il comportamento della singola cella ----------------------------------------

def test_una_cella_senza_osservazioni_coincide_col_genitore():
    """E' il comportamento che rende superflua una soglia di risalita esplicita."""
    celle = np.array([0, 0, 0, 1], dtype=np.int64)
    valori = np.array([0, 0, 1, 2], dtype=np.int64)
    padre = np.zeros(3, dtype=np.int64)
    modello = stima(
        [Livello("gruppo", np.zeros(4, dtype=np.int64), valori, 1),
         Livello("cella", celle, valori, 3, padre)], N_VALORI, alfa=5.0)
    assert np.allclose(modello.finale[2], modello.tabelle[0][0])


def test_una_cella_ricca_si_avvicina_alle_proprie_frequenze():
    """Con molte osservazioni il priore dev'essere trascurabile, non solo attenuato."""
    g = np.random.default_rng(7)
    vera = np.array([0.5, 0.2, 0.1, 0.1, 0.05, 0.03, 0.01, 0.01])
    valori = g.choice(N_VALORI, size=200_000, p=vera)
    celle = np.zeros(valori.size, dtype=np.int64)
    modello = stima(
        [Livello("gruppo", celle, valori, 1),
         Livello("cella", celle, valori, 1, np.zeros(1, dtype=np.int64))],
        N_VALORI, alfa=10.0)
    assert np.allclose(modello.finale[0], vera, atol=0.01)


def test_ogni_riga_e_una_distribuzione():
    """Comprese le righe delle celle mai osservate, che ereditano quella del padre."""
    celle, valori = _campione(_distribuzioni(8.0, 71), _numerosita_disuguale(72), 73)
    modello = stima(_scala(celle, valori), N_VALORI, alfa=[2.0, 20.0])
    for tabella in modello.tabelle:
        assert np.allclose(tabella.sum(axis=1), 1.0)
        assert (tabella > 0).all()


def test_un_gradino_senza_osservazioni_lascia_la_tabella_invariata():
    """Il caso in cui una citta' non ha previsioni utilizzabili al livello fine.

    Il gradino va aggiunto lo stesso, perche' la scala e' la stessa per tutte le
    citta', e non deve fare danni quando il suo campione e' vuoto.
    """
    celle, valori = _campione(_distribuzioni(8.0, 81), _numerosita_disuguale(82), 83)
    vuoto = np.array([], dtype=np.int64)
    senza = stima(_scala(celle, valori), N_VALORI, alfa=5.0)
    con = stima(_scala(celle, valori)
                + [Livello("previsioni", vuoto, vuoto, FINI,
                           np.arange(FINI, dtype=np.int64))], N_VALORI, alfa=5.0)
    assert np.allclose(senza.finale, con.finale)


# --- la seconda dimensione della scala: il tipo di dato ---------------------------

def test_il_gradino_per_tipo_di_dato_usa_il_proprio_campione():
    """Constatazioni e previsioni sono campioni diversi, non partizioni degli stessi.

    Il gradino delle previsioni ha la mappa identita' - stesso contesto, altro tipo
    di dato - e deve spostare la stima verso la distribuzione delle previsioni
    senza cancellare quella delle constatazioni.
    """
    n = 4_000
    zero = np.zeros(n, dtype=np.int64)
    g = np.random.default_rng(91)
    constatate = g.choice(N_VALORI, size=n, p=np.full(N_VALORI, 1 / N_VALORI))
    previste = np.zeros(n, dtype=np.int64)  # previsioni degeneri: sempre lo stesso bin
    scala = [
        Livello("constatazioni", zero, constatate, 1),
        Livello("previsioni", zero, previste, 1, np.zeros(1, dtype=np.int64)),
    ]
    modello = stima(scala, N_VALORI, alfa=[1.0, 2_000.0])
    assert modello.campioni == (n, n)
    assert modello.finale[0, 0] > modello.tabelle[0][0, 0]
    assert modello.finale[0, 0] < 0.9


def test_la_taratura_riconosce_quando_il_livello_fine_non_serve():
    """Concentrazione alta se le celle fini non differiscono, bassa se differiscono.

    E' la verifica che alfa faccia davvero il lavoro che nel piano era assegnato a
    una soglia separata: decidere quanto ciascun gradino debba credere ai propri dati.
    """
    def alfa_del_fine(concentrazione: float | None, scala_dati: float, seme: int) -> float:
        vere = _distribuzioni(concentrazione, seme)
        celle_a, valori_a = _campione(vere, _numerosita_disuguale(seme + 1, scala_dati),
                                      seme + 2)
        celle_v, valori_v = _campione(vere, _numerosita_disuguale(seme + 3, 0.5), seme + 4)
        return tara(_scala(celle_a, valori_a), celle_v, valori_v, N_VALORI).alfa[1]

    assert alfa_del_fine(1e6, 1.0, 101) > alfa_del_fine(None, 40.0, 111)


def test_la_taratura_non_peggiora_di_passata_in_passata():
    """La discesa lungo le coordinate deve convergere, non oscillare."""
    celle, valori = _campione(_distribuzioni(8.0, 121), _numerosita_disuguale(122), 123)
    celle_v, valori_v = _campione(_distribuzioni(8.0, 121), _numerosita_disuguale(124, 0.5),
                                  125)
    esito = tara(_scala(celle, valori), celle_v, valori_v, N_VALORI, passate=3)
    perdite = [p for _, _, p in esito.traccia]
    assert all(b <= a + 1e-12 for a, b in zip(perdite, perdite[1:]))
    assert esito.perdita == pytest.approx(perdite[-1])
    assert esito.alfa[0] in CANDIDATI and esito.alfa[1] in CANDIDATI


def test_un_alfa_sul_bordo_della_griglia_viene_segnalato():
    """Un valore all'estremo non e' una scelta ma un troncamento.

    Sul primo giro sui dati veri quasi tutti i gradini di Roma hanno scelto il
    massimo disponibile, il che diceva solo che l'ottimo stava oltre il punto in cui
    si era smesso di cercare. Il segnale deve venire dal codice, non da chi legge.
    """
    celle, valori = _campione(_distribuzioni(1e6, 141), _numerosita_disuguale(142), 143)
    celle_v, valori_v = _campione(_distribuzioni(1e6, 141),
                                  _numerosita_disuguale(144, 0.5), 145)
    stretta = tara(_scala(celle, valori), celle_v, valori_v, N_VALORI,
                   candidati=(0.5, 1.0, 2.0))
    assert stretta.al_bordo, "celle fini identiche al gruppo: alfa deve saturare in alto"
    larga = tara(_scala(celle, valori), celle_v, valori_v, N_VALORI)
    assert set(larga.alfa) <= set(CANDIDATI)
    assert larga.perdita <= stretta.perdita + 1e-12


def test_senza_candidati_dichiarati_non_si_pronuncia_sul_bordo():
    """Una ``Taratura`` costruita a mano non deve fingere di sapere la griglia."""
    from src.delays.rete import Taratura
    assert Taratura((1.0,), 0.0, (("a", 1.0, 0.0),)).al_bordo == ()


def test_contare_una_volta_sola_da_le_stesse_tabelle():
    """La separazione fra conteggio e composizione e' un'ottimizzazione.

    Serve perche' la taratura prova decine di concentrazioni sugli stessi dati, ma
    un'ottimizzazione che cambia i numeri e' un difetto: le tabelle devono
    coincidere a meno dell'errore di macchina, per ogni concentrazione.
    """
    celle, valori = _campione(_distribuzioni(8.0, 131), _numerosita_disuguale(132), 133)
    conteggi = conta(_scala(celle, valori), N_VALORI)
    for a in (0.5, 7.0, [1.0, 250.0]):
        insieme = stima(_scala(celle, valori), N_VALORI, a)
        separato = componi(conteggi, a)
        for prima, dopo in zip(insieme.tabelle, separato.tabelle):
            assert np.array_equal(prima, dopo)


def test_i_conteggi_sono_le_frequenze_osservate():
    """Un conteggio sbagliato passerebbe inosservato dietro il priore."""
    celle = np.array([0, 0, 1, 1, 1], dtype=np.int64)
    valori = np.array([2, 2, 0, 3, 3], dtype=np.int64)
    conteggi = conta([Livello("cella", celle, valori, 2)], N_VALORI)
    attesa = np.zeros((2, N_VALORI))
    attesa[0, 2], attesa[1, 0], attesa[1, 3] = 2, 1, 2
    assert np.array_equal(conteggi.matrici[0], attesa)
    assert conteggi.campioni == (5,)


# --- errori che i dati locali non attraversano -----------------------------------

def test_la_mappa_annidata_rifiuta_codifiche_non_annidate():
    figlio = np.array([0, 0, 1], dtype=np.int64)
    padre = np.array([0, 1, 1], dtype=np.int64)
    with pytest.raises(ErroreRete, match="non annidate"):
        mappa_annidata(figlio, padre, 2, 2)


def test_la_mappa_annidata_accetta_una_codifica_annidata():
    figlio = np.array([0, 0, 1, 3], dtype=np.int64)
    padre = np.array([0, 0, 0, 1], dtype=np.int64)
    assert mappa_annidata(figlio, padre, 4, 2).tolist() == [0, 0, 0, 1]


def test_indici_negativi_vengono_rifiutati_invece_di_leggere_dal_fondo():
    valori = np.array([0, 1], dtype=np.int64)
    with pytest.raises(ErroreRete, match="negativa"):
        Livello("cella", np.array([-1, 0], dtype=np.int64), valori, 2)


@pytest.mark.parametrize("costruzione, messaggio", [
    (lambda: stima([], N_VALORI, 1.0), "nessun gradino"),
    (lambda: stima([Livello("a", np.zeros(1, dtype=np.int64),
                            np.zeros(1, dtype=np.int64), 1)], N_VALORI, 0.0),
     "positiva"),
    (lambda: stima([Livello("a", np.zeros(1, dtype=np.int64),
                            np.zeros(1, dtype=np.int64), 1)], N_VALORI, [1.0, 2.0]),
     "concentrazioni"),
    (lambda: stima([Livello("a", np.zeros(1, dtype=np.int64),
                            np.zeros(1, dtype=np.int64), 1,
                            np.zeros(1, dtype=np.int64))], N_VALORI, 1.0),
     "non puo' avere un genitore"),
    (lambda: stima([Livello("a", np.zeros(1, dtype=np.int64),
                            np.zeros(1, dtype=np.int64), 1),
                    Livello("b", np.zeros(1, dtype=np.int64),
                            np.zeros(1, dtype=np.int64), 1)], N_VALORI, 1.0),
     "mappa dei genitori"),
    (lambda: Livello("a", np.zeros(3, dtype=np.int64),
                     np.zeros(2, dtype=np.int64), 1), "valori nel campione"),
    (lambda: Livello("a", np.zeros(1, dtype=np.int64),
                     np.zeros(1, dtype=np.int64), 0), "celle dichiarate"),
    (lambda: Livello("a", np.array([5], dtype=np.int64),
                     np.zeros(1, dtype=np.int64), 2), "oltre le 2"),
])
def test_le_incoerenze_vengono_dette(costruzione, messaggio):
    with pytest.raises(ErroreRete, match=messaggio):
        costruzione()


def test_un_valore_fuori_supporto_viene_detto():
    livello = Livello("a", np.zeros(2, dtype=np.int64),
                      np.array([0, 99], dtype=np.int64), 1)
    with pytest.raises(ErroreRete, match="valore 99"):
        stima([livello], N_VALORI, 1.0)


def test_la_perdita_su_un_campione_vuoto_viene_detta():
    modello = stima([Livello("a", np.zeros(2, dtype=np.int64),
                             np.zeros(2, dtype=np.int64), 1)], N_VALORI, 1.0)
    vuoto = np.array([], dtype=np.int64)
    with pytest.raises(ErroreRete, match="vuoto"):
        modello.perdita(vuoto, vuoto)
