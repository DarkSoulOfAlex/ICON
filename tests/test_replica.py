"""Test della replica di un itinerario sui ritardi osservati.

Il backtesting non si collauda sui dati veri per la stessa ragione per cui non ci
si collauda un estimatore: li' non si sa quale sia la risposta giusta. Si
costruiscono invece itinerari di cui si conosce l'esito - la coincidenza si perde,
oppure si tiene per un soffio, oppure si recupera - e si verifica che la replica
lo ritrovi.

Il caso che conta piu' degli altri e' quello del **mezzo in anticipo**: e' il
fenomeno su cui poggia l'intera domanda di ricerca, non ha nulla di intuitivo -
un mezzo puntuale fa perdere la coincidenza - e un confronto fatto sugli orari
teorici lo darebbe sempre per riuscito.
"""

from __future__ import annotations

import pytest

from src.eval.replica import ErroreReplica, replica, rigiocabile
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
