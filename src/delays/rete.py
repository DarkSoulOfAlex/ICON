"""Stima della matrice di transizione del ritardo, con risalita gerarchica.

Stima ``P(ritardo alla fermata | contesto, ritardo alla fermata precedente)``, che
e' la tabella su cui si fonda la composizione delle probabilita' lungo la catena
delle coincidenze.

**Il problema che la risalita risolve.** Al livello piu' fine - linea, fascia
oraria, tipo di giorno - le celle sono centinaia di migliaia e la loro popolazione
e' fortemente disuguale: poche linee portanti concentrano la maggior parte dei
passaggi, mentre molte combinazioni corrispondono a servizi marginali con pochi
dati o nessuno. Stimarle tutte con le sole frequenze proprie darebbe tabelle
precise dove i dati abbondano e prive di senso dove scarseggiano. Stimarle tutte a
un livello grossolano darebbe l'opposto: nessuna cella priva di senso, e nessuna
capace di distinguere una linea dall'altra.

**Come funziona.** Ogni gradino della scala viene stimato usando come priore di
Dirichlet la stima del gradino che lo precede, con concentrazione ``alfa``:

    P(cella) = (conteggi + alfa * P(genitore)) / (osservazioni + alfa)

Una cella con tre osservazioni resta quasi uguale al genitore; una con tremila lo
ignora; una senza osservazioni **coincide** con il genitore, che e' esattamente il
comportamento voluto e si ottiene senza alcuna regola aggiuntiva.

**Perche' non esiste una soglia separata.** Verrebbe naturale aggiungere un
parametro che dica "sotto tante osservazioni, usa il genitore". Sarebbe pero'
ridondante e peggiore: ``alfa`` governa gia' quella transizione, e la governa in
modo **graduale** invece che a gradino, evitando che due celle con novantanove e
centouno osservazioni ricevano trattamenti diversi. I due parametri che il piano
distingueva - quando salire e quanto pesare il genitore - sono lo stesso
parametro. Si tara quindi ``alfa`` **per gradino**, il che permette di essere
prudenti dove i dati scarseggiano e fiduciosi dove abbondano.

**La scala ha due dimensioni.** Oltre al contesto, dal piu' grossolano al piu'
fine, c'e' il tipo di dato: le constatazioni prima e le previsioni poi, perche' su
Roma il 23% delle transizioni fra previsioni e' l'identita' - valori non
ricalcolati, quindi copie - contro il 4,7% fra constatazioni (voce 61). Ne segue
che ogni gradino ha **le proprie osservazioni**, non una diversa partizione delle
stesse: il gradino "previsioni al contesto fine" vede righe che il gradino
"constatazioni al contesto fine" non vede affatto. Da qui la firma di ``Livello``,
che porta con se' il proprio campione.

**La mappa dei genitori si dichiara, non si deduce.** Sarebbe comodo ricavarla dai
dati, guardando in quale cella grossolana cadano le osservazioni di ciascuna cella
fine. Sarebbe pero' sbagliato proprio dove conta: una cella mai osservata in
addestramento ma presente in verifica riceverebbe un genitore arbitrario, cioe' un
genitore sbagliato esattamente nel caso in cui la risalita e' l'unica cosa che
regge la stima. La mappa e' una proprieta' della codifica del contesto, che il
chiamante conosce per intero, e va passata per intero.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class ErroreRete(Exception):
    """La scala o i dati non permettono di stimare la tabella."""


def _controlla_indici(indici: np.ndarray, quanti: int, che_cosa: str) -> None:
    """Un indice fuori intervallo va detto, non lasciato a ``IndexError``.

    Con indici negativi numpy non solleverebbe nulla: leggerebbe dal fondo della
    tabella, restituendo la cella sbagliata in silenzio.
    """
    if indici.size == 0:
        return
    if int(indici.min()) < 0:
        raise ErroreRete(f"{che_cosa} negativa ({int(indici.min())})")
    if int(indici.max()) >= quanti:
        raise ErroreRete(f"{che_cosa} {int(indici.max())} oltre le {quanti} dichiarate")


@dataclass(frozen=True)
class Livello:
    """Un gradino della scala: il suo campione, le sue celle, il suo genitore.

    ``celle`` e ``valori`` hanno la lunghezza del campione **di questo gradino**,
    che puo' essere diverso da quello degli altri. ``padre`` ha lunghezza
    ``quante`` e dice, per ogni cella di questo gradino, quale cella del gradino
    precedente la contiene; vale ``None`` solo per il primo gradino, il cui priore
    e' uniforme. Quando il contesto non cambia e a cambiare e' solo il tipo di
    dato, ``padre`` e' l'identita'.
    """

    nome: str
    celle: np.ndarray
    valori: np.ndarray
    quante: int
    padre: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.quante <= 0:
            raise ErroreRete(f"livello '{self.nome}': {self.quante} celle dichiarate")
        if self.celle.shape != self.valori.shape:
            raise ErroreRete(
                f"livello '{self.nome}': {self.celle.size} celle e {self.valori.size} "
                f"valori nel campione"
            )
        _controlla_indici(self.celle, self.quante, f"livello '{self.nome}': cella")
        if self.padre is not None and self.padre.shape != (self.quante,):
            raise ErroreRete(
                f"livello '{self.nome}': mappa dei genitori di {self.padre.size} "
                f"voci per {self.quante} celle"
            )


@dataclass(frozen=True)
class Modello:
    """Le tabelle stimate a ogni gradino, dal primo all'ultimo."""

    nomi: tuple[str, ...]
    tabelle: tuple[np.ndarray, ...]
    alfa: tuple[float, ...]
    campioni: tuple[int, ...]

    @property
    def finale(self) -> np.ndarray:
        return self.tabelle[-1]

    def probabilita(self, celle: np.ndarray, valori: np.ndarray) -> np.ndarray:
        """Probabilita' assegnata a ciascun valore osservato, all'ultimo gradino."""
        tabella = self.finale
        _controlla_indici(celle, tabella.shape[0], "cella di verifica")
        _controlla_indici(valori, tabella.shape[1], "valore di verifica")
        return tabella[celle, valori]

    def perdita(self, celle: np.ndarray, valori: np.ndarray) -> float:
        """Bit medi per osservazione. E' il criterio con cui si tara ``alfa``."""
        if valori.size == 0:
            raise ErroreRete("campione di verifica vuoto")
        return float(-np.mean(np.log2(self.probabilita(celle, valori))))


def mappa_annidata(codice_figlio: np.ndarray, codice_padre: np.ndarray,
                   quante_figlio: int, quante_padre: int) -> np.ndarray:
    """Ricava la mappa dei genitori da una coppia di codifiche annidate.

    Da usare solo quando il chiamante puo' enumerare **tutte** le celle, per
    esempio percorrendo il prodotto cartesiano dei fattori del contesto, e non
    quando dispone soltanto delle celle osservate: vedere la nota nel docstring del
    modulo. L'annidamento viene verificato, perche' una codifica non annidata - due
    voci della stessa cella fine che ricadono in celle grossolane diverse -
    produrrebbe altrimenti una mappa dipendente dall'ordine delle righe.
    """
    if codice_figlio.shape != codice_padre.shape:
        raise ErroreRete("le due codifiche non hanno lo stesso numero di voci")
    _controlla_indici(codice_figlio, quante_figlio, "codice figlio")
    _controlla_indici(codice_padre, quante_padre, "codice padre")
    mappa = np.zeros(quante_figlio, dtype=np.int64)
    mappa[codice_figlio] = codice_padre
    if np.any(mappa[codice_figlio] != codice_padre):
        raise ErroreRete(
            "codifiche non annidate: una cella figlia ricade in piu' celle padre"
        )
    return mappa


def stima(livelli: list[Livello], n_valori: int, alfa: float | list[float]) -> Modello:
    """Incatena i gradini, ciascuno con priore la stima del precedente.

    ``livelli`` va fornito **ordinato**, dal gradino piu' generale al piu'
    specifico: l'ultimo e' la tabella che il pianificatore adopera. ``alfa`` puo'
    essere un solo numero, applicato a tutti i gradini, oppure uno per gradino.
    """
    if not livelli:
        raise ErroreRete("nessun gradino nella scala")
    if n_valori <= 0:
        raise ErroreRete(f"{n_valori} valori nel supporto della distribuzione")
    concentrazioni = ([float(alfa)] * len(livelli) if np.ndim(alfa) == 0
                      else [float(a) for a in alfa])
    if len(concentrazioni) != len(livelli):
        raise ErroreRete(f"{len(concentrazioni)} concentrazioni per {len(livelli)} gradini")
    if any(a <= 0 for a in concentrazioni):
        raise ErroreRete("la concentrazione del priore deve essere positiva")
    if livelli[0].padre is not None:
        raise ErroreRete("il primo gradino non puo' avere un genitore")
    if any(l.padre is None for l in livelli[1:]):
        raise ErroreRete("ogni gradino dopo il primo deve dichiarare la mappa dei genitori")

    tabelle: list[np.ndarray] = []
    # Il priore della radice e' uniforme: senza alcun gradino a monte non c'e'
    # ragione di preferire un bin a un altro, e dichiararlo esplicitamente evita
    # che il primo gradino debba essere un caso speciale del ciclo.
    precedente = np.full((1, n_valori), 1.0 / n_valori)

    for livello, concentrazione in zip(livelli, concentrazioni):
        padre = (np.zeros(livello.quante, dtype=np.int64) if livello.padre is None
                 else livello.padre)
        _controlla_indici(padre, precedente.shape[0], f"livello '{livello.nome}': genitore")
        _controlla_indici(livello.valori, n_valori, f"livello '{livello.nome}': valore")
        conteggi = np.zeros((livello.quante, n_valori), dtype=np.float64)
        # add.at e non un istogramma bidimensionale: le celle sono molte e quasi
        # tutte vuote, e accumulare in posto evita di materializzarne una copia.
        np.add.at(conteggi, (livello.celle, livello.valori), 1.0)
        atteso = precedente[padre]
        totale = conteggi.sum(axis=1, keepdims=True)
        tabelle.append((conteggi + concentrazione * atteso) / (totale + concentrazione))
        precedente = tabelle[-1]

    return Modello(
        nomi=tuple(l.nome for l in livelli),
        tabelle=tuple(tabelle),
        alfa=tuple(concentrazioni),
        campioni=tuple(int(l.valori.size) for l in livelli),
    )


CANDIDATI = (0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0)


@dataclass(frozen=True)
class Taratura:
    """L'esito della taratura: le concentrazioni scelte e come vi si e' arrivati."""

    alfa: tuple[float, ...]
    perdita: float
    traccia: tuple[tuple[str, float, float], ...]
    """Per ogni mossa: gradino toccato, valore scelto, perdita risultante."""


def tara(
    livelli: list[Livello],
    celle_verifica: np.ndarray,
    valori_verifica: np.ndarray,
    n_valori: int,
    candidati: tuple[float, ...] = CANDIDATI,
    passate: int = 2,
) -> Taratura:
    """Sceglie una concentrazione per gradino minimizzando la perdita fuori campione.

    Il campione di verifica deve contenere **solo constatazioni**: se contenesse
    anche previsioni, fra le quali su Roma quasi un quarto delle transizioni e'
    l'identita', la concentrazione verrebbe scelta per predire bene le ripetizioni,
    che e' il contrario di cio' che serve (voce 61).

    Provare tutte le combinazioni costerebbe ``len(candidati) ** len(livelli)``
    stime; si procede invece per discesa lungo le coordinate, un gradino alla volta
    dal piu' grossolano al piu' fine, ripetuta ``passate`` volte perche' la scelta
    su un gradino cambia il priore di quelli a valle e quindi il loro ottimo. La
    perdita non puo' peggiorare da una mossa alla successiva, dato che il valore
    corrente e' sempre fra i candidati provati, quindi la ripetizione converge.
    """
    if not candidati:
        raise ErroreRete("nessun candidato da provare")
    if passate < 1:
        raise ErroreRete(f"{passate} passate di taratura")
    # Si parte dal candidato mediano: partire da un estremo renderebbe la prima
    # passata una discesa in un solo verso, e la seconda dovrebbe disfarla.
    corrente = [float(sorted(candidati)[len(candidati) // 2])] * len(livelli)
    perdita = float("inf")
    traccia: list[tuple[str, float, float]] = []
    for _ in range(passate):
        for i, livello in enumerate(livelli):
            migliore, perdita = corrente[i], float("inf")
            for a in candidati:
                prova = list(corrente)
                prova[i] = a
                candidata = stima(livelli, n_valori, prova).perdita(
                    celle_verifica, valori_verifica)
                if candidata < perdita:
                    migliore, perdita = a, candidata
            corrente[i] = migliore
            traccia.append((livello.nome, migliore, perdita))
    return Taratura(tuple(corrente), perdita, tuple(traccia))
