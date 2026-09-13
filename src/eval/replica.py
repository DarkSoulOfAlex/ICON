"""Rigiocare un itinerario sui ritardi che quel giorno sono stati osservati.

E' il cuore del backtesting, e la ragione per cui esiste separato: la domanda di
ricerca non chiede quale itinerario il modello **creda** piu' sicuro, chiede se
quello scelto col modello perda **davvero** meno coincidenze. La differenza fra le
due cose e' esattamente cio' che un confronto fatto dentro il modello non puo'
vedere, perche' li' il modello sarebbe insieme giudice e imputato.

**Come si rigioca.** Il viaggiatore e' pronto a un istante; per ogni tappa si
cerca la prima corsa fra quelle disponibili che parta dalla fermata di salita
**non prima** che lui sia pronto, usando l'orario reale - programmato piu' ritardo
osservato - e non quello teorico. Da li' si legge l'arrivo reale alla fermata di
discesa, si aggiunge il tempo minimo di trasbordo della tappa seguente, e si
ricomincia.

**Il mezzo in anticipo fa perdere la coincidenza come quello in ritardo.** Se la
corsa pianificata e' gia' partita quando il viaggiatore arriva, la coincidenza e'
persa anche se quel mezzo era puntualissimo o addirittura in anticipo. E' il
fenomeno che la domanda di ricerca insegue, e rigiocare sugli orari reali e'
l'unico modo di contarlo: un confronto sugli orari teorici lo darebbe sempre per
riuscito.

**I recuperi contano come coincidenze perse, non come fallimenti.** Ogni tappa
porta con se' le corse successive della stessa linea dalla stessa fermata: se la
pianificata sfugge, si prende la seguente e si arriva piu' tardi. Trattare una
coincidenza persa come un fallimento del viaggio sopravvaluterebbe la differenza
fra le strategie, perche' in una rete urbana una linea ripassa.

**Una tratta senza osservazione ferma la replica.** Non si sostituisce con
l'orario teorico: sarebbe come dichiarare puntuale cio' che non si e' visto, e
proprio nei casi in cui il dato manca. Chi chiama riceve quante tratte sono state
rigiocate prima di fermarsi, e decide se l'istanza sia utilizzabile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.planner.robust import Itinerario, Tappa

RitardoOsservato = Callable[[str, str], int | None]
"""``(trip_id, stop_id) -> ritardo in secondi``, oppure ``None`` se non osservato."""


class ErroreReplica(Exception):
    """L'itinerario non e' in una forma rigiocabile."""


@dataclass(frozen=True)
class EsitoReplica:
    """Che cosa e' successo davvero a chi ha seguito quell'itinerario."""

    arrivo_reale: int | None
    """Istante di arrivo a destinazione; ``None`` se il viaggio si e' interrotto."""
    coincidenze_perse: int
    """Quante volte la corsa pianificata era gia' partita all'arrivo del viaggiatore."""
    recuperi_riusciti: int
    """Quante di quelle sono state rimediate con una corsa successiva."""
    tratte_rigiocate: int
    """Tappe percorse prima di arrivare o di fermarsi."""
    partenza_persa: bool = False
    """La prima corsa era gia' partita: non e' una coincidenza, e' un ritardo proprio."""

    @property
    def completato(self) -> bool:
        return self.arrivo_reale is not None

    def entro(self, scadenza: int) -> bool:
        """Il viaggio e' arrivato entro la scadenza. Un viaggio interrotto non lo e'.

        Trattare l'interruzione come un successo, o escluderla dal conto, premierebbe
        la strategia che si caccia piu' spesso nei guai.
        """
        return self.arrivo_reale is not None and self.arrivo_reale <= scadenza


def _pronto_per(tappa: Tappa, arrivo_precedente: int | None,
                partenza_richiesta: int) -> int:
    """Da quando il viaggiatore puo' salire su questa tappa.

    Alla prima tappa e' l'istante in cui chiede di partire; alle successive e'
    l'arrivo reale della precedente piu' il tempo minimo di trasbordo, che e' una
    proprieta' della tappa che si sta prendendo e non di quella che si lascia.
    """
    if arrivo_precedente is None:
        return partenza_richiesta
    return arrivo_precedente + tappa.tempo_minimo_trasbordo


def replica(itinerario: Itinerario, ritardo: RitardoOsservato) -> EsitoReplica:
    """Rigioca l'itinerario sui ritardi osservati e dice com'e' andata."""
    if not itinerario.tappe:
        raise ErroreReplica("un itinerario senza tappe non si puo' rigiocare")

    arrivo_precedente: int | None = None
    perse = recuperi = 0
    partenza_persa = False

    for indice, tappa in enumerate(itinerario.tappe):
        pronto = _pronto_per(tappa, arrivo_precedente, itinerario.partenza_richiesta)
        presa = None
        for posizione, corsa in enumerate(tappa.alternative):
            alla_salita = ritardo(corsa.trip_id, tappa.fermata_salita)
            alla_discesa = ritardo(corsa.trip_id, tappa.fermata_discesa)
            if alla_salita is None or alla_discesa is None:
                # Corsa non osservata: si passa alla successiva invece di
                # inventarne l'orario. Se nessuna lo e', la replica si ferma.
                continue
            if corsa.partenza_programmata + alla_salita < pronto:
                continue
            presa = (posizione, corsa.arrivo_programmato + alla_discesa)
            break

        if presa is None:
            return EsitoReplica(None, perse, recuperi, indice, partenza_persa)
        posizione, arrivo_precedente = presa
        if posizione > 0:
            # La corsa pianificata era gia' partita, o non era osservata: in
            # entrambi i casi non e' quella che si e' presa.
            if indice == 0:
                partenza_persa = True
            else:
                perse += 1
            recuperi += 1

    return EsitoReplica(arrivo_precedente + itinerario.coda_a_piedi, perse, recuperi,
                        len(itinerario.tappe), partenza_persa)


def rigiocabile(itinerario: Itinerario, ritardo: RitardoOsservato) -> bool:
    """L'itinerario **pianificato** e' osservato in ogni sua tratta.

    Si guarda la sola corsa pianificata, non i recuperi: un itinerario si include
    nel confronto se il piano che propone e' verificabile, e i recuperi servono a
    raccontare che cosa sarebbe successo, non a decidere l'ammissione. Chiedere che
    anche tutti i recuperi fossero osservati escluderebbe gli itinerari sulle linee
    piu' frequenti, che sono quelli che hanno piu' recuperi.
    """
    return all(
        ritardo(tappa.alternative[0].trip_id, tappa.fermata_salita) is not None
        and ritardo(tappa.alternative[0].trip_id, tappa.fermata_discesa) is not None
        for tappa in itinerario.tappe
    )


def margine_piu_stretto(itinerario) -> int | None:
    """I secondi di respiro della coincidenza piu' tesa dell'itinerario.

    Per ogni cambio, la differenza fra l'orario di partenza della corsa che si
    deve prendere e il primo istante in cui si e' pronti a prenderla - arrivo
    della tappa precedente piu' il tempo minimo di trasbordo. Il minimo su tutti
    i cambi e' la coincidenza che decide l'esito del viaggio: se salta quella,
    saltano le successive.

    Serve a distinguere due spiegazioni di uno stesso fenomeno. Il modello
    risulta pessimista sui viaggi rigiocati, e le ipotesi sono che l'errore si
    **componga** lungo la catena oppure che sia **locale** alla coincidenza piu'
    critica. Le due si separano guardando dove il divario si concentra, e questa
    e' la grandezza che lo dice.

    Vale ``None`` per un itinerario senza cambi: li' non c'e' coincidenza da
    perdere, e un valore convenzionale la farebbe entrare nelle medie come se ce
    ne fosse una molto larga.
    """
    if len(itinerario.tappe) < 2:
        return None
    margini = []
    for precedente, tappa in zip(itinerario.tappe, itinerario.tappe[1:]):
        # La prima alternativa e' la corsa pianificata: le altre sono i recuperi,
        # e misurare il respiro su un recupero direbbe quanto sia comodo il piano
        # di riserva invece di quanto sia teso il piano.
        arrivo = precedente.alternative[0].arrivo_programmato
        partenza = tappa.alternative[0].partenza_programmata
        margini.append(partenza - arrivo - tappa.tempo_minimo_trasbordo)
    return min(margini)
