"""Test dell'estimatore che decide la struttura della rete bayesiana.

Un estimatore di informazione mutua non si puo' collaudare sui dati veri, perche'
li' la risposta non e' nota: si collauda su catene costruite di cui si conosce la
struttura, e si verifica che la ritrovi. E' l'unico modo di sapere se misuri cio'
che dice di misurare prima di fargli decidere se serva un arco in piu'.

I due casi che contano sono speculari, e servono entrambi. Una catena markoviana
per costruzione deve risultare compatibile con zero; una catena in cui il secondo
antenato porta davvero informazione deve risultare chiaramente sopra. Un
estimatore che dicesse sempre "zero" passerebbe il primo test, e uno che dicesse
sempre "molto" passerebbe il secondo.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.delays.markov import (
    BORDI_OTTO,
    BORDI_QUATTRO,
    SEME_CATENA,
    ErroreMarkov,
    Terne,
    catena_con_dipendenza_vera,
    catena_markoviana,
    discretizza,
    estrai_terne,
    informazione_mutua,
    informazione_mutua_condizionata,
    riferimento_per_permutazione,
    eccesso_si_dissolve,
    scala_per_granularita,
    unisci,
    valuta,
)

BIN = 8


def _catena_markoviana(n: int, seme: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """R-2 -> R-1 -> R0, dove R0 dipende SOLO da R-1.

    E' la struttura che la Fase 4 aveva assunto: il ritardo si propaga di fermata
    in fermata, e il passato remoto non aggiunge nulla a quello immediato.
    """
    g = np.random.default_rng(seme)
    r2 = g.integers(0, BIN, n)
    # R-1 dipende da R-2, con rumore: la catena e' reale, non due variabili slegate.
    r1 = np.clip(r2 + g.integers(-1, 2, n), 0, BIN - 1)
    r0 = np.clip(r1 + g.integers(-1, 2, n), 0, BIN - 1)
    return r2, r1, r0


def _catena_non_markoviana(n: int, seme: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """R0 dipende da R-1 **e** da R-2: l'assunzione markoviana e' falsa."""
    g = np.random.default_rng(seme)
    r2 = g.integers(0, BIN, n)
    r1 = np.clip(r2 + g.integers(-1, 2, n), 0, BIN - 1)
    # Il contributo diretto di R-2 e' cio' che rende la catena non markoviana.
    r0 = np.clip((r1 + r2) // 2 + g.integers(-1, 2, n), 0, BIN - 1)
    return r2, r1, r0


# =============================================================================
# L'estimatore ritrova la struttura che gli si e' data
# =============================================================================


def test_su_una_catena_markoviana_il_secondo_antenato_non_aggiunge_nulla() -> None:
    """Il caso in cui l'assunzione della Fase 4 e' vera per costruzione."""
    r2, r1, r0 = _catena_markoviana(200_000)
    esito = valuta(Terne(r2, r1, r0, np.ones(r2.size, dtype=bool)),
                   generatore=np.random.default_rng(7))
    assert esito.compatibile_con_zero, (
        f"condizionata {esito.condizionata:.5f}, riferimento "
        f"{esito.riferimento:.5f} +/- {esito.scarto_riferimento:.5f}"
    )


def test_su_una_catena_non_markoviana_il_secondo_antenato_si_vede() -> None:
    """Controllo speculare: un estimatore che dice sempre zero passerebbe l'altro test."""
    r2, r1, r0 = _catena_non_markoviana(200_000)
    esito = valuta(Terne(r2, r1, r0, np.ones(r2.size, dtype=bool)),
                   generatore=np.random.default_rng(7))
    assert not esito.compatibile_con_zero
    assert esito.eccesso > 10 * esito.scarto_riferimento
    # E l'eccesso e' una frazione apprezzabile di cio' che il primo antenato spiega.
    assert esito.quota_sul_primo_antenato > 0.05


# =============================================================================
# Il riferimento nullo, che e' cio' che rende leggibile il numero
# =============================================================================


def test_il_riferimento_nullo_e_positivo_su_campioni_finiti() -> None:
    """E' la ragione per cui il riferimento esiste.

    L'informazione mutua stimata da frequenze e' sempre positiva anche quando la
    vera e' zero. Se il riferimento risultasse nullo, vorrebbe dire che non stiamo
    misurando il bias che dovrebbe catturare.
    """
    g = np.random.default_rng(3)
    n = 4_000  # piccolo di proposito: il bias cresce al calare della numerosita'
    z = g.integers(0, BIN, n)
    x = g.integers(0, BIN, n)
    y = g.integers(0, BIN, n)
    media, scarto = riferimento_per_permutazione(x, y, z, ripetizioni=15,
                                                 generatore=np.random.default_rng(5))
    assert media > 0.0
    assert scarto > 0.0


def test_la_permutazione_conserva_il_legame_fra_il_secondo_antenato_e_il_primo() -> None:
    """Verifica che il rimescolamento sia quello giusto, non uno qualunque.

    Rimescolando globalmente si spezzerebbe anche la relazione fra R-2 e R-1, e il
    riferimento risulterebbe piu' basso del dovuto: un valore non significativo
    sembrerebbe significativo. Rimescolando dentro gli strati di R-1 quella
    relazione resta intatta, ed e' cio' che questo test controlla.
    """
    r2, r1, _ = _catena_markoviana(50_000, seme=11)
    prima = informazione_mutua(r2, r1)

    g = np.random.default_rng(13)
    ordine = np.argsort(r1, kind="stable")
    z, x = r1[ordine], r2[ordine]
    tagli = np.flatnonzero(np.diff(z)) + 1
    for blocco in np.split(np.arange(z.size), tagli):
        if blocco.size > 1:
            x[blocco] = g.permutation(x[blocco])
    dopo = informazione_mutua(x, z)

    assert dopo == pytest.approx(prima, abs=1e-9), (
        "la permutazione dentro gli strati deve lasciare intatto I(R-2 ; R-1)"
    )


def test_una_permutazione_globale_distruggerebbe_quel_legame() -> None:
    """Il controllo che rende il test precedente informativo."""
    r2, r1, _ = _catena_markoviana(50_000, seme=11)
    prima = informazione_mutua(r2, r1)
    globale = np.random.default_rng(17).permutation(r2)
    assert informazione_mutua(globale, r1) < prima / 10


# =============================================================================
# Estrazione delle terne
# =============================================================================


def test_le_terne_si_formano_su_osservazioni_adiacenti() -> None:
    posizioni = np.array([1, 2, 3, 4])
    ritardi = np.array([0.0, 100.0, 400.0, 900.0])
    t = estrai_terne(posizioni, ritardi)
    assert len(t) == 2
    assert t.contigue.all()
    assert list(t.monte2) == [discretizza(np.array([0.0]))[0],
                              discretizza(np.array([100.0]))[0]]


def test_una_fermata_mancante_marca_la_terna_come_non_contigua() -> None:
    """Il GTFS non garantisce che stop_sequence sia denso.

    Una terna con un buco non descrive tre passaggi consecutivi del veicolo, e
    tenerla senza saperlo mescolerebbe due grandezze diverse.
    """
    t = estrai_terne(np.array([1, 2, 4, 5]), np.array([0.0, 60.0, 120.0, 180.0]))
    assert len(t) == 2
    assert list(t.contigue) == [False, False]
    assert len(t.solo_contigue()) == 0


def test_una_corsa_con_meno_di_tre_passaggi_non_produce_terne() -> None:
    t = estrai_terne(np.array([1, 2]), np.array([0.0, 60.0]))
    assert len(t) == 0


def test_posizioni_non_crescenti_sono_un_errore_non_un_risultato() -> None:
    with pytest.raises(ErroreMarkov, match="strettamente crescenti"):
        estrai_terne(np.array([3, 1, 2]), np.array([0.0, 1.0, 2.0]))


def test_unisci_concatena_le_terne_di_piu_corse() -> None:
    a = estrai_terne(np.array([1, 2, 3]), np.array([0.0, 60.0, 120.0]))
    b = estrai_terne(np.array([1, 2, 3, 4]), np.array([0.0, 60.0, 120.0, 180.0]))
    assert len(unisci([a, b])) == len(a) + len(b)
    assert len(unisci([])) == 0


# =============================================================================
# Discretizzazione
# =============================================================================


def test_i_bin_estremi_assorbono_le_code() -> None:
    """Anticipo grande e ritardo grave non si scartano: sono i casi che contano."""
    v = np.array([-10_000.0, 10_000.0])
    b = discretizza(v)
    assert b[0] == 0
    assert b[1] == len(BORDI_OTTO)


def test_le_due_granularita_danno_numeri_di_bin_diversi() -> None:
    v = np.array([-100.0, 30.0, 200.0, 5_000.0])
    assert discretizza(v, BORDI_OTTO).max() <= len(BORDI_OTTO)
    assert discretizza(v, BORDI_QUATTRO).max() <= len(BORDI_QUATTRO)
    assert len(BORDI_QUATTRO) + 1 == 4


def _catena_continua(n: int, seme: int = SEME_CATENA):
    """La catena del modulo, non una sua copia.

    Il numero che questi test fissano finisce nel documento, e lo produce lo script
    che scrive il CSV: se il test costruisse una catena propria, le due potrebbero
    divergere senza che nulla lo segnalasse, ed e' esattamente cio' che il test
    dovrebbe impedire.
    """
    return catena_markoviana(n, seme)


def test_discretizzare_una_catena_markoviana_crea_dipendenza_apparente() -> None:
    """Il fatto scoperto costruendo il test, e la ragione per cui serve altro.

    Una catena markoviana **nel continuo** smette di esserlo dopo la
    discretizzazione: il bin di R-1 non porta tutta l'informazione del valore che
    rappresenta, e R-2 ne conserva un residuo. L'eccesso risultante e' reale, non
    e' rumore, e supera di molto il riferimento per permutazione.

    Questo test fissa il fenomeno perche' non venga scambiato per un difetto: se
    un giorno sparisse, vorrebbe dire che qualcosa e' cambiato nell'estimatore.
    """
    grezzo2, grezzo1, grezzo0 = _catena_continua(200_000)
    t = Terne(discretizza(grezzo2, BORDI_OTTO), discretizza(grezzo1, BORDI_OTTO),
              discretizza(grezzo0, BORDI_OTTO), np.ones(grezzo2.size, dtype=bool))
    esito = valuta(t, generatore=np.random.default_rng(29))
    assert not esito.compatibile_con_zero, (
        "su una catena markoviana discretizzata l'eccesso NON e' nullo: "
        "e' l'artefatto che il criterio della scala serve a riconoscere"
    )
    assert esito.eccesso > 10 * esito.scarto_riferimento
    # ma resta una frazione piccola di cio' che il primo antenato spiega
    assert esito.quota_sul_primo_antenato < 0.05


def test_l_artefatto_della_discretizzazione_si_dissolve_al_raffinarsi_dei_bin() -> None:
    """Il discriminante: l'artefatto svanisce, una dipendenza vera no.

    E' il criterio che distingue le due cause senza richiedere ipotesi sul
    processo continuo sottostante, che sui dati veri non conosciamo.
    """
    grezzo2, grezzo1, grezzo0 = _catena_continua(200_000)
    scala = scala_per_granularita(grezzo2, grezzo1, grezzo0,
                                  generatore=np.random.default_rng(31))
    quote = [e.quota_sul_primo_antenato for _, e in scala]
    assert eccesso_si_dissolve(scala), f"quote {[f'{q:.1%}' for q in quote]}"
    assert quote[-1] < 0.01


def test_una_dipendenza_vera_non_si_dissolve() -> None:
    """Controllo speculare: senza, un criterio che dice sempre "si dissolve" passerebbe."""
    grezzo2, grezzo1, grezzo0 = catena_con_dipendenza_vera(200_000)
    scala = scala_per_granularita(grezzo2, grezzo1, grezzo0,
                                  generatore=np.random.default_rng(41))
    quote = [e.quota_sul_primo_antenato for _, e in scala]
    assert not eccesso_si_dissolve(scala), f"quote {[f'{q:.1%}' for q in quote]}"


def test_campione_vuoto_e_un_errore() -> None:
    vuoto = np.empty(0, dtype=np.int64)
    with pytest.raises(ErroreMarkov, match="vuot"):
        informazione_mutua_condizionata(vuoto, vuoto, vuoto)


# =============================================================================
# Il campione deve sostenere la granularita', altrimenti non si giudica
# =============================================================================


def test_le_granularita_troppo_fini_vengono_escluse() -> None:
    """A venti bin la tabella condizionata ha ottomila celle.

    Su poche migliaia di terne la stima non e' imprecisa, e' priva di
    significato: escluderla e' l'unico modo di non farla leggere come le altre.
    """
    from src.delays.markov import granularita_sostenibili
    assert granularita_sostenibili(11_591, (4, 6, 8, 12, 20)) == (4, 6)
    assert granularita_sostenibili(9_800_000, (4, 6, 8, 12, 20)) == (4, 6, 8, 12, 20)


def test_su_poche_granularita_il_verdetto_si_rifiuta() -> None:
    """Un verdetto su due punti e' una coincidenza con un'etichetta sopra."""
    from src.delays.markov import verdetto_sulla_scala
    grezzo2, grezzo1, grezzo0 = _catena_continua(60_000)
    scala = scala_per_granularita(grezzo2, grezzo1, grezzo0, (4, 6),
                                  generatore=np.random.default_rng(43))
    esito, spiegazione = verdetto_sulla_scala(scala)
    assert esito is None
    assert "non si giudica" in spiegazione


def test_su_granularita_sufficienti_il_verdetto_si_pronuncia() -> None:
    """Controllo speculare: un criterio che rifiuta sempre passerebbe l'altro test."""
    from src.delays.markov import verdetto_sulla_scala
    grezzo2, grezzo1, grezzo0 = _catena_continua(400_000)
    scala = scala_per_granularita(grezzo2, grezzo1, grezzo0, (4, 6, 8, 12, 20),
                                  generatore=np.random.default_rng(47))
    esito, spiegazione = verdetto_sulla_scala(scala)
    assert esito is True, spiegazione


# =============================================================================
# Il costo-beneficio dell'arco, fuori campione
# =============================================================================


def _separazione(n: int, quota: float = 0.7) -> np.ndarray:
    """Maschera di addestramento: i primi in ordine, non a caso."""
    m = np.zeros(n, dtype=bool)
    m[: int(n * quota)] = True
    return m


def test_su_una_catena_markoviana_l_arco_non_paga() -> None:
    """Se il secondo antenato non porta informazione, aggiungerlo peggiora.

    Fuori campione un genitore inutile non e' neutro: moltiplica per otto le celle
    da stimare, quindi ogni cella riceve meno osservazioni e la stima peggiora.
    """
    from src.delays.markov import confronta_strutture
    r2, r1, r0 = _catena_markoviana(300_000)
    c = confronta_strutture(r2, r1, r0, _separazione(r2.size), BIN)
    assert c.celle_con == 8 * c.celle_senza
    assert c.guadagno <= 0.01, f"guadagno {c.guadagno:.5f} bit"


def test_su_una_catena_non_markoviana_l_arco_paga() -> None:
    """Controllo speculare: se l'informazione c'e', deve emergere fuori campione."""
    from src.delays.markov import confronta_strutture
    r2, r1, r0 = _catena_non_markoviana(300_000)
    c = confronta_strutture(r2, r1, r0, _separazione(r2.size), BIN)
    assert c.guadagno > 0.05, f"guadagno {c.guadagno:.5f} bit"
    assert c.guadagno_relativo > 0.02


def test_il_lisciamento_evita_la_perdita_infinita() -> None:
    """Senza priore, una combinazione mai vista darebbe probabilita' nulla.

    E' il modello con piu' genitori a soffrirne, perche' ha piu' combinazioni: un
    confronto senza lisciamento lo punirebbe per un difetto della stima invece che
    per la propria struttura.
    """
    from src.delays.markov import confronta_strutture
    g = np.random.default_rng(51)
    n = 3_000  # piccolo: garantisce combinazioni mai viste in addestramento
    r2, r1, r0 = (g.integers(0, BIN, n) for _ in range(3))
    c = confronta_strutture(r2, r1, r0, _separazione(n), BIN, alfa=0.5)
    assert np.isfinite(c.perdita_con) and np.isfinite(c.perdita_senza)


def test_una_separazione_vuota_e_un_errore() -> None:
    from src.delays.markov import confronta_strutture
    r2, r1, r0 = _catena_markoviana(1_000)
    with pytest.raises(ErroreMarkov, match="vuoto"):
        confronta_strutture(r2, r1, r0, np.ones(1_000, dtype=bool), BIN)


def test_il_confronto_con_contesto_penalizza_la_scarsita() -> None:
    """Lo stesso arco, misurato in abbondanza e in scarsita' di dati.

    E' la ragione per cui la misura senza contesto non autorizza la scelta di
    struttura: con molte combinazioni di contesto e le stesse osservazioni, le
    celle si svuotano e il guadagno puo' sparire o invertirsi.
    """
    from src.delays.markov import confronta_con_contesto, confronta_strutture
    r2, r1, r0 = _catena_non_markoviana(300_000)
    separa = _separazione(r2.size)
    senza_contesto = confronta_strutture(r2, r1, r0, separa, BIN)
    # Un contesto fine e privo di informazione: serve solo a moltiplicare le celle.
    contesto = np.random.default_rng(53).integers(0, 2_000, r2.size)
    con_contesto = confronta_con_contesto(contesto, r2, r1, r0, separa, BIN, 2_000)
    assert senza_contesto.guadagno > 0.05
    assert con_contesto.guadagno < senza_contesto.guadagno, (
        f"in scarsita' il guadagno deve ridursi: {con_contesto.guadagno:.4f} "
        f"contro {senza_contesto.guadagno:.4f}"
    )


def test_i_valori_ripetuti_si_contano_sui_secondi_non_sui_bin() -> None:
    """Due ritardi diversi nello stesso bin non sono una ripetizione."""
    from src.delays.markov import quota_valori_ripetuti
    precedente = np.array([100.0, 100.0, 100.0, 100.0])
    corrente = np.array([100.0, 100.0, 110.0, 500.0])
    assert quota_valori_ripetuti(precedente, corrente) == pytest.approx(0.5)
    # sui bin, i primi tre cadrebbero insieme e la quota sarebbe 0,75
    assert discretizza(np.array([100.0]))[0] == discretizza(np.array([110.0]))[0]
