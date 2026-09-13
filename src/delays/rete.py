"""Stima della matrice di transizione del ritardo, con risalita gerarchica.

Stima ``P(ritardo alla fermata | contesto, ritardo alla fermata precedente)``, che
e' la tabella su cui si fonda la composizione delle probabilita' lungo la catena
delle coincidenze.

Il problema che la risalita risolve. Al livello piu' fine - linea, fascia
oraria, tipo di giorno - le celle sono centinaia di migliaia e la loro popolazione
e' fortemente disuguale: poche linee portanti concentrano la maggior parte dei
passaggi, mentre molte combinazioni corrispondono a servizi marginali con pochi
dati o nessuno. Stimarle tutte con le sole frequenze proprie darebbe tabelle
precise dove i dati abbondano e prive di senso dove scarseggiano. Stimarle tutte a
un livello grossolano darebbe l'opposto: nessuna cella priva di senso, e nessuna
capace di distinguere una linea dall'altra.

Come funziona. Ogni gradino della scala viene stimato usando come priore di
Dirichlet la stima del gradino che lo precede, con concentrazione ``alfa``:

    P(cella) = (conteggi + alfa * P(genitore)) / (osservazioni + alfa)

Una cella con tre osservazioni resta quasi uguale al genitore; una con tremila lo
ignora; una senza osservazioni coincide con il genitore, che e' esattamente il
comportamento voluto e si ottiene senza alcuna regola aggiuntiva.

Perche' non esiste una soglia separata. Verrebbe naturale aggiungere un
parametro che dica "sotto tante osservazioni, usa il genitore". Sarebbe pero'
ridondante e peggiore: ``alfa`` governa gia' quella transizione, e la governa in
modo graduale invece che a gradino, evitando che due celle con novantanove e
centouno osservazioni ricevano trattamenti diversi. I due parametri che il piano
distingueva - quando salire e quanto pesare il genitore - sono lo stesso
parametro. Si tara quindi ``alfa`` per gradino, il che permette di essere
prudenti dove i dati scarseggiano e fiduciosi dove abbondano.

La scala ha due dimensioni. Oltre al contesto, dal piu' grossolano al piu'
fine, c'e' il tipo di dato: le constatazioni prima e le previsioni poi, perche' su
Roma il 23% delle transizioni fra previsioni e' l'identita' - valori non
ricalcolati, quindi copie - contro il 4,7% fra constatazioni. Ne segue
che ogni gradino ha le proprie osservazioni, non una diversa partizione delle
stesse: il gradino "previsioni al contesto fine" vede righe che il gradino
"constatazioni al contesto fine" non vede affatto. Da qui la firma di ``Livello``,
che porta con se' il proprio campione.

La mappa dei genitori si dichiara, non si deduce. Sarebbe comodo ricavarla dai
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

    ``celle`` e ``valori`` hanno la lunghezza del campione di questo gradino,
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

    Da usare solo quando il chiamante puo' enumerare tutte le celle, per
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


@dataclass(frozen=True)
class Conteggi:
    """I conteggi per cella di ogni gradino, che non dipendono da ``alfa``.

    Sono separati dalla composizione perche' la taratura prova decine di
    concentrazioni sugli stessi dati: ricontare a ogni tentativo costerebbe una
    passata sulle osservazioni per candidato, cioe' ore invece di minuti sul
    campione vero, e conterebbe ogni volta gli stessi numeri.
    """

    nomi: tuple[str, ...]
    matrici: tuple[np.ndarray, ...]
    padri: tuple[np.ndarray | None, ...]
    n_valori: int
    campioni: tuple[int, ...]


def conta(livelli: list[Livello], n_valori: int) -> Conteggi:
    """Conta le osservazioni di ciascun gradino, e verifica che la scala regga."""
    if not livelli:
        raise ErroreRete("nessun gradino nella scala")
    if n_valori <= 0:
        raise ErroreRete(f"{n_valori} valori nel supporto della distribuzione")
    if livelli[0].padre is not None:
        raise ErroreRete("il primo gradino non puo' avere un genitore")
    if any(l.padre is None for l in livelli[1:]):
        raise ErroreRete("ogni gradino dopo il primo deve dichiarare la mappa dei genitori")

    matrici, quante_prima = [], 1
    for livello in livelli:
        if livello.padre is not None:
            _controlla_indici(livello.padre, quante_prima,
                              f"livello '{livello.nome}': genitore")
        _controlla_indici(livello.valori, n_valori, f"livello '{livello.nome}': valore")
        # bincount su un indice appiattito e non add.at: le celle sono molte e quasi
        # tutte vuote, e add.at su un indice a due dimensioni e' di un ordine di
        # grandezza piu' lento proprio sui campioni grandi che qui interessano.
        piatto = livello.celle * n_valori + livello.valori
        matrici.append(np.bincount(piatto, minlength=livello.quante * n_valori)
                       .astype(np.float64).reshape(livello.quante, n_valori))
        quante_prima = livello.quante
    return Conteggi(
        nomi=tuple(l.nome for l in livelli),
        matrici=tuple(matrici),
        padri=tuple(l.padre for l in livelli),
        n_valori=n_valori,
        campioni=tuple(int(l.valori.size) for l in livelli),
    )


def componi(conteggi: Conteggi, alfa: float | list[float]) -> Modello:
    """Incatena i gradini gia' contati, ciascuno con priore la stima del precedente."""
    quanti = len(conteggi.matrici)
    concentrazioni = ([float(alfa)] * quanti if np.ndim(alfa) == 0
                      else [float(a) for a in alfa])
    if len(concentrazioni) != quanti:
        raise ErroreRete(f"{len(concentrazioni)} concentrazioni per {quanti} gradini")
    if any(a <= 0 for a in concentrazioni):
        raise ErroreRete("la concentrazione del priore deve essere positiva")

    tabelle: list[np.ndarray] = []
    # Il priore della radice e' uniforme: senza alcun gradino a monte non c'e'
    # ragione di preferire un bin a un altro, e dichiararlo esplicitamente evita
    # che il primo gradino debba essere un caso speciale del ciclo.
    precedente = np.full((1, conteggi.n_valori), 1.0 / conteggi.n_valori)
    for matrice, padre, concentrazione in zip(conteggi.matrici, conteggi.padri,
                                              concentrazioni):
        atteso = (np.broadcast_to(precedente[0], matrice.shape) if padre is None
                  else precedente[padre])
        totale = matrice.sum(axis=1, keepdims=True)
        tabelle.append((matrice + concentrazione * atteso) / (totale + concentrazione))
        precedente = tabelle[-1]

    return Modello(nomi=conteggi.nomi, tabelle=tuple(tabelle),
                   alfa=tuple(concentrazioni), campioni=conteggi.campioni)


def stima(livelli: list[Livello], n_valori: int, alfa: float | list[float]) -> Modello:
    """Conta e compone in un colpo solo.

    ``livelli`` va fornito ordinato, dal gradino piu' generale al piu'
    specifico: l'ultimo e' la tabella che il pianificatore adopera. ``alfa`` puo'
    essere un solo numero, applicato a tutti i gradini, oppure uno per gradino.
    """
    return componi(conta(livelli, n_valori), alfa)


CANDIDATI = (0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 1_000.0, 5_000.0,
             25_000.0, 100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0)
"""I valori provati per la concentrazione, su scala logaritmica.

L'estremo superiore e' alto di proposito. Un gradino che scegliesse il massimo
disponibile non sarebbe tarato ma troncato: direbbe solo che il suo ottimo sta
oltre il punto dove si e' smesso di cercare, e ``Taratura.al_bordo`` lo segnala.

Perche' arriva a cento milioni e non a un milione. Con un milione la griglia si
fermava troppo presto per i gradini a poche celle molto popolose. Il peso che una
cella conserva sui propri conteggi vale ``N / (N + alfa)``: il gradino per tipo di
veicolo di Roma ha otto celle su 1,17 milioni di coppie, cioe' circa
centoquarantaseimila osservazioni ciascuna, e a un milione ne conservava ancora un
ottavo - restando a quattro punti percentuali dal genitore invece di coincidervi.
La saturazione era del cercatore, non della stima. Due ordini di grandezza in piu'
portano quel residuo sotto il punto percentuale e rendono la trasparenza
raggiungibile, senza togliere nulla ai gradini che un alfa piccolo gia' serviva.

Con una concentrazione molto maggiore del numero di osservazioni della cella, il
gradino diventa trasparente: la sua stima coincide con quella del genitore.
E' una risposta legittima e non un troncamento - vuol dire che il gradino non
serve - e su Roma capita davvero, perche' con tutte le linee di superficie
classificate come autobus il livello per tipo di veicolo ripete quello sotto di
se'. Distinguere i due casi richiede una misura: se allargando la griglia la
perdita non si muove, la saturazione e' trasparenza; se si muove, era un
troncamento.
"""


@dataclass(frozen=True)
class Taratura:
    """L'esito della taratura: le concentrazioni scelte e come vi si e' arrivati."""

    alfa: tuple[float, ...]
    perdita: float
    traccia: tuple[tuple[str, float, float], ...]
    """Per ogni mossa: gradino toccato, valore scelto, perdita risultante."""
    candidati: tuple[float, ...] = ()

    @property
    def al_bordo(self) -> tuple[str, ...]:
        """I gradini la cui concentrazione e' finita a un estremo della griglia.

        Un valore all'estremo non e' una scelta ma un troncamento: dice che
        l'ottimo sta oltre il punto in cui si e' smesso di cercare, e va allargata
        la griglia invece di riportarlo.
        """
        if not self.candidati:
            return ()
        estremi = {min(self.candidati), max(self.candidati)}
        return tuple(nome for nome, a in zip(self.nomi_dei_gradini(), self.alfa)
                     if a in estremi)

    def nomi_dei_gradini(self) -> tuple[str, ...]:
        """I nomi nell'ordine dei gradini, letti dall'ultima passata della traccia."""
        quanti = len(self.alfa)
        return tuple(nome for nome, _, _ in self.traccia[-quanti:]) if self.traccia else ()


def tara(
    livelli: list[Livello] | Conteggi,
    celle_verifica: np.ndarray,
    valori_verifica: np.ndarray,
    n_valori: int,
    candidati: tuple[float, ...] = CANDIDATI,
    passate: int = 2,
) -> Taratura:
    """Sceglie una concentrazione per gradino minimizzando la perdita fuori campione.

    Il campione di verifica deve contenere solo constatazioni: se contenesse
    anche previsioni, fra le quali su Roma quasi un quarto delle transizioni e'
    l'identita', la concentrazione verrebbe scelta per predire bene le ripetizioni,
    che e' il contrario di cio' che serve.

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
    conteggi = livelli if isinstance(livelli, Conteggi) else conta(livelli, n_valori)
    quanti = len(conteggi.matrici)
    # Si parte dal candidato mediano: partire da un estremo renderebbe la prima
    # passata una discesa in un solo verso, e la seconda dovrebbe disfarla.
    corrente = [float(sorted(candidati)[len(candidati) // 2])] * quanti
    perdita = float("inf")
    traccia: list[tuple[str, float, float]] = []
    for _ in range(passate):
        for i in range(quanti):
            migliore, perdita = corrente[i], float("inf")
            for a in candidati:
                prova = list(corrente)
                prova[i] = a
                candidata = componi(conteggi, prova).perdita(celle_verifica,
                                                             valori_verifica)
                if candidata < perdita:
                    migliore, perdita = a, candidata
            corrente[i] = migliore
            traccia.append((conteggi.nomi[i], migliore, perdita))
    return Taratura(tuple(corrente), perdita, tuple(traccia), tuple(candidati))


@dataclass(frozen=True)
class Trasparenza:
    """Quanto la tabella di un gradino si discosti da quella del suo genitore.

    Serve a leggere un ``alfa`` finito al bordo superiore della griglia. Per
    ``alfa`` che cresce la stima di una cella tende alla stima del genitore -
    ``(conteggi + alfa*atteso) / (osservazioni + alfa) -> atteso`` - quindi un
    gradino che sceglie il massimo disponibile sta chiedendo di somigliare al
    genitore quanto la griglia gli concede. Non c'e' bisogno di allargare la
    griglia per capire che cosa significhi: basta misurare quanto dista gia'.

    Se dista zero entro il numerico, il gradino e' trasparente e non serve. Se
    dista ancora, la griglia e' troppo stretta e va detto, perche' allora la scala
    sta lavorando su meno gradini per troncamento e non per esito.
    """

    nome: str
    alfa: float
    scarto_massimo: float
    """Massima differenza assoluta fra una probabilita' e quella del genitore."""
    divergenza_media: float
    """KL(gradino || genitore) in bit, mediata sulle celle col peso delle loro
    osservazioni: dice quanto il gradino sposti cio' che il modello afferma sul
    traffico reale, e non su celle che nessuno visita."""
    celle: int
    celle_osservate: int
    """Le celle vuote coincidono col genitore per costruzione, quindi contarle
    insieme alle altre diluirebbe la misura verso zero a prescindere."""


def trasparenza(modello: Modello, conteggi: Conteggi) -> tuple[Trasparenza, ...]:
    """Per ogni gradino oltre il primo, quanto disti dal proprio genitore."""
    if len(modello.tabelle) != len(conteggi.matrici):
        raise ErroreRete("il modello e i conteggi non hanno lo stesso numero di gradini")
    esiti: list[Trasparenza] = []
    for i in range(1, len(modello.tabelle)):
        padre = conteggi.padri[i]
        if padre is None:
            raise ErroreRete(f"il gradino {i} non dichiara la mappa dei genitori")
        figlia = modello.tabelle[i]
        genitrice = modello.tabelle[i - 1][padre]
        osservazioni = conteggi.matrici[i].sum(axis=1)
        visitate = osservazioni > 0
        scarto = float(np.max(np.abs(figlia - genitrice))) if figlia.size else 0.0
        if visitate.any():
            # Il logaritmo e' al sicuro: ogni cella ha probabilita' positive su
            # tutti i bin, perche' il priore e' positivo ovunque per costruzione.
            kl = np.sum(figlia[visitate] * np.log2(figlia[visitate] / genitrice[visitate]),
                        axis=1)
            peso = osservazioni[visitate]
            divergenza = float(np.sum(kl * peso) / np.sum(peso))
        else:
            divergenza = 0.0
        esiti.append(Trasparenza(
            nome=modello.nomi[i], alfa=modello.alfa[i],
            scarto_massimo=scarto, divergenza_media=divergenza,
            celle=int(figlia.shape[0]), celle_osservate=int(visitate.sum()),
        ))
    return tuple(esiti)
