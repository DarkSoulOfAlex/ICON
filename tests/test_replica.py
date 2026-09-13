"""Test della replica di un itinerario sui ritardi osservati.

Il backtesting non si collauda sui dati veri per la stessa ragione per cui non ci
si collauda un estimatore: li' non si sa quale sia la risposta giusta. Si
costruiscono invece itinerari di cui si conosce l'esito - la coincidenza si perde,
oppure si tiene per un soffio, oppure si recupera - e si verifica che la replica
lo ritrovi.

Il caso che conta piu' degli altri e' quello del mezzo in anticipo: e' il
fenomeno su cui poggia l'intera domanda di ricerca, non ha nulla di intuitivo -
un mezzo puntuale fa perdere la coincidenza - e un confronto fatto sugli orari
teorici lo darebbe sempre per riuscito.
"""

from __future__ import annotations

import pytest

from src.eval.replica import (ErroreReplica, margine_piu_stretto, replica,
                              rigiocabile)
from src.planner.robust import Itinerario, Salita, Tappa

ORA = 8 * 3600


def _tappa(salita: str, discesa: str, corse: list[tuple[str, int, int]],
           trasbordo: int = 120) -> Tappa:
    return Tappa(
        fermata_salita=salita, sequenza_salita=1,
        fermata_discesa=discesa, sequenza_discesa=5,
        tempo_minimo_trasbordo=trasbordo,
        alternative=tuple(Salita(trip_id=t, route_id="R", partenza_programmata=p,
                                 arrivo_programmato=a) for t, p, a in corse),
    )


def _itinerario(tappe: list[Tappa], coda: int = 0, partenza: int = ORA) -> Itinerario:
    return Itinerario(citta="prova", partenza_richiesta=partenza,
                      tappe=tuple(tappe), coda_a_piedi=coda)


def _ritardi(tabella: dict[tuple[str, str], int]):
    return lambda trip, stop: tabella.get((trip, stop))


# --- il viaggio riesce ----------------------------------------------------------

def test_senza_ritardi_l_arrivo_reale_e_quello_programmato():
    it = _itinerario([_tappa("A", "B", [("t1", ORA, ORA + 600)])])
    esito = replica(it, _ritardi({("t1", "A"): 0, ("t1", "B"): 0}))
    assert esito.arrivo_reale == ORA + 600
    assert esito.coincidenze_perse == 0 and esito.completato


def test_il_ritardo_alla_discesa_sposta_l_arrivo():
    it = _itinerario([_tappa("A", "B", [("t1", ORA, ORA + 600)])], coda=90)
    esito = replica(it, _ritardi({("t1", "A"): 0, ("t1", "B"): 240}))
    assert esito.arrivo_reale == ORA + 600 + 240 + 90


def test_la_coda_a_piedi_non_subisce_ritardi_ma_si_conta():
    """Ignorarla misurerebbe l'arrivo alla fermata, non a destinazione."""
    corse = [("t1", ORA, ORA + 600)]
    senza = replica(_itinerario([_tappa("A", "B", corse)]),
                    _ritardi({("t1", "A"): 0, ("t1", "B"): 0}))
    con = replica(_itinerario([_tappa("A", "B", corse)], coda=300),
                  _ritardi({("t1", "A"): 0, ("t1", "B"): 0}))
    assert con.arrivo_reale - senza.arrivo_reale == 300


# --- il caso che regge la domanda di ricerca ------------------------------------

def test_il_mezzo_in_anticipo_fa_perdere_la_coincidenza():
    """Nessun ritardo, coincidenza persa: l'orario teorico non lo vedrebbe mai."""
    prima = _tappa("A", "B", [("t1", ORA, ORA + 600)])
    dopo = _tappa("B", "C", [("t2", ORA + 780, ORA + 1200),
                             ("t3", ORA + 1380, ORA + 1800)], trasbordo=120)
    it = _itinerario([prima, dopo])
    # La seconda corsa parte in ANTICIPO di 90 s: il viaggiatore e' pronto a
    # ORA+720 e la trova gia' partita a ORA+690.
    esito = replica(it, _ritardi({("t1", "A"): 0, ("t1", "B"): 0,
                                  ("t2", "B"): -90, ("t2", "C"): -90,
                                  ("t3", "B"): 0, ("t3", "C"): 0}))
    assert esito.coincidenze_perse == 1
    assert esito.recuperi_riusciti == 1
    assert esito.arrivo_reale == ORA + 1800


def test_la_coincidenza_tenuta_per_un_soffio_non_si_conta_persa():
    prima = _tappa("A", "B", [("t1", ORA, ORA + 600)])
    dopo = _tappa("B", "C", [("t2", ORA + 720, ORA + 1200)], trasbordo=120)
    esito = replica(_itinerario([prima, dopo]),
                    _ritardi({("t1", "A"): 0, ("t1", "B"): 0,
                              ("t2", "B"): 0, ("t2", "C"): 0}))
    assert esito.coincidenze_perse == 0
    assert esito.arrivo_reale == ORA + 1200


def test_un_secondo_in_meno_e_la_coincidenza_si_perde():
    """Il confine e' esattamente il tempo minimo di trasbordo, e va verificato li'."""
    prima = _tappa("A", "B", [("t1", ORA, ORA + 600)])
    dopo = _tappa("B", "C", [("t2", ORA + 720, ORA + 1200),
                             ("t3", ORA + 1500, ORA + 2000)], trasbordo=120)
    esito = replica(_itinerario([prima, dopo]),
                    _ritardi({("t1", "A"): 0, ("t1", "B"): 1,
                              ("t2", "B"): 0, ("t2", "C"): 0,
                              ("t3", "B"): 0, ("t3", "C"): 0}))
    assert esito.coincidenze_perse == 1
    assert esito.arrivo_reale == ORA + 2000


def test_senza_recuperi_il_viaggio_si_interrompe():
    prima = _tappa("A", "B", [("t1", ORA, ORA + 600)])
    dopo = _tappa("B", "C", [("t2", ORA + 720, ORA + 1200)], trasbordo=120)
    esito = replica(_itinerario([prima, dopo]),
                    _ritardi({("t1", "A"): 0, ("t1", "B"): 300,
                              ("t2", "B"): 0, ("t2", "C"): 0}))
    assert esito.arrivo_reale is None
    assert esito.completato is False
    assert esito.tratte_rigiocate == 1


def test_un_viaggio_interrotto_non_e_arrivato_entro_la_scadenza():
    """Escluderlo, o contarlo riuscito, premierebbe chi si caccia nei guai."""
    prima = _tappa("A", "B", [("t1", ORA, ORA + 600)])
    dopo = _tappa("B", "C", [("t2", ORA + 720, ORA + 1200)], trasbordo=120)
    esito = replica(_itinerario([prima, dopo]),
                    _ritardi({("t1", "A"): 0, ("t1", "B"): 300,
                              ("t2", "B"): 0, ("t2", "C"): 0}))
    assert esito.entro(ORA + 100_000) is False


def test_la_prima_corsa_persa_non_e_una_coincidenza():
    """E' un ritardo proprio del viaggiatore, e mescolarlo falserebbe il conto."""
    it = _itinerario([_tappa("A", "B", [("t1", ORA - 60, ORA + 600),
                                        ("t2", ORA + 300, ORA + 900)])])
    esito = replica(it, _ritardi({("t1", "A"): 0, ("t1", "B"): 0,
                                  ("t2", "A"): 0, ("t2", "B"): 0}))
    assert esito.partenza_persa is True
    assert esito.coincidenze_perse == 0
    assert esito.arrivo_reale == ORA + 900


# --- osservazioni mancanti ------------------------------------------------------

def test_una_tratta_non_osservata_ferma_la_replica():
    """Non si sostituisce con l'orario teorico: sarebbe dichiarare puntuale l'ignoto."""
    it = _itinerario([_tappa("A", "B", [("t1", ORA, ORA + 600)])])
    esito = replica(it, _ritardi({("t1", "A"): 0}))     # manca la discesa
    assert esito.arrivo_reale is None and esito.tratte_rigiocate == 0


def test_rigiocabile_guarda_solo_la_corsa_pianificata():
    """I recuperi non decidono l'ammissione, altrimenti si escluderebbero le linee
    frequenti, che sono quelle che ne hanno di piu'."""
    tappa = _tappa("A", "B", [("t1", ORA, ORA + 600), ("t9", ORA + 900, ORA + 1500)])
    it = _itinerario([tappa])
    assert rigiocabile(it, _ritardi({("t1", "A"): 0, ("t1", "B"): 0})) is True
    assert rigiocabile(it, _ritardi({("t1", "A"): 0})) is False


def test_un_itinerario_senza_tappe_viene_detto():
    with pytest.raises(ErroreReplica, match="senza tappe"):
        replica(_itinerario([]), _ritardi({}))


def test_il_margine_critico_e_il_minimo_fra_le_coincidenze():
    """Due cambi con respiro diverso: conta il piu' teso, non la media."""
    itinerario = _itinerario([
        _tappa("A", "B", [("t1", ORA, ORA + 600)], trasbordo=60),
        # pronto a ORA+660, parte a ORA+900: 240 s di respiro
        _tappa("B", "C", [("t2", ORA + 900, ORA + 1500)], trasbordo=60),
        # pronto a ORA+1560, parte a ORA+1620: 60 s di respiro
        _tappa("C", "D", [("t3", ORA + 1620, ORA + 2000)], trasbordo=60),
    ])
    assert margine_piu_stretto(itinerario) == 60


def test_un_itinerario_senza_cambi_non_ha_margine_critico():
    """None e non zero: zero direbbe 'coincidenza strettissima' invece di 'nessuna'."""
    itinerario = _itinerario([_tappa("A", "B", [("t1", ORA, ORA + 600)])])
    assert margine_piu_stretto(itinerario) is None


def test_una_coincidenza_gia_impossibile_sull_orario_da_un_margine_negativo():
    """La frontiera puo' contenere coincidenze che l'orario stesso non regge.

    Non e' un caso teorico: succede quando il tempo minimo di trasbordo derivato
    dalla base di conoscenza e' maggiore del respiro che l'orario lascia. Il valore
    deve restare negativo invece di essere azzerato, perche' zero direbbe
    "appena fattibile" dove il dato dice "gia' impossibile".
    """
    itinerario = _itinerario([
        _tappa("A", "B", [("t1", ORA, ORA + 600)], trasbordo=300),
        _tappa("B", "C", [("t2", ORA + 700, ORA + 1200)], trasbordo=300),
    ])
    assert margine_piu_stretto(itinerario) == -200


def test_i_recuperi_non_entrano_nel_margine_critico():
    """Il respiro si misura sul piano, non sul piano di riserva."""
    stretto = _itinerario([
        _tappa("A", "B", [("t1", ORA, ORA + 600)], trasbordo=60),
        _tappa("B", "C", [("t2", ORA + 700, ORA + 1200),
                          ("t2b", ORA + 1800, ORA + 2400)], trasbordo=60),
    ])
    assert margine_piu_stretto(stretto) == 40


def test_la_replica_registra_ogni_cambio_col_suo_respiro():
    """Il respiro reale si misura sulla corsa pianificata, anche quando e' persa."""
    itinerario = _itinerario([
        _tappa("A", "B", [("t1", ORA, ORA + 600)], trasbordo=60),
        _tappa("B", "C", [("t2", ORA + 900, ORA + 1500),
                          ("t2b", ORA + 1800, ORA + 2400)], trasbordo=60),
    ])
    # t1 arriva 300 s tardi: si e' pronti a ORA+960, t2 parte a ORA+900: persa.
    esito = replica(itinerario, _ritardi({("t1", "A"): 0, ("t1", "B"): 300,
                                          ("t2", "B"): 0, ("t2", "C"): 0,
                                          ("t2b", "B"): 0, ("t2b", "C"): 0}))
    assert len(esito.coincidenze) == 1
    c = esito.coincidenze[0]
    assert c.indice == 1
    assert c.respiro_nominale == 240          # 900 - 600 - 60
    assert c.respiro_reale == -60             # 900 - 900 - 60, col ritardo di t1
    assert c.tenuta is False
    assert esito.coincidenze_perse == 1


def test_una_coincidenza_tenuta_ha_respiro_reale_positivo():
    itinerario = _itinerario([
        _tappa("A", "B", [("t1", ORA, ORA + 600)], trasbordo=60),
        _tappa("B", "C", [("t2", ORA + 900, ORA + 1500)], trasbordo=60),
    ])
    esito = replica(itinerario, _ritardi({("t1", "A"): 0, ("t1", "B"): 0,
                                          ("t2", "B"): 0, ("t2", "C"): 0}))
    c = esito.coincidenze[0]
    assert c.tenuta is True
    assert c.respiro_reale == 240
    assert c.respiro_reale == c.respiro_nominale


def test_un_itinerario_senza_cambi_non_registra_coincidenze():
    itinerario = _itinerario([_tappa("A", "B", [("t1", ORA, ORA + 600)])])
    esito = replica(itinerario, _ritardi({("t1", "A"): 0, ("t1", "B"): 0}))
    assert esito.coincidenze == ()
