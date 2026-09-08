"""Il ritardo due fermate a monte aggiunge informazione, dato quello a una fermata?

E' la domanda che decide la struttura della rete bayesiana della Fase 3, e va
risolta **prima** di stimare qualunque tabella di probabilita': se la risposta
fosse affermativa servirebbe un arco in piu', e con esso otto volte le celle, che
non e' cosa da scoprire dopo aver stimato un milione e quattrocentomila
probabilita' condizionate.

La quantita' misurata e' l'informazione mutua condizionata
``I(R0 ; R-2 | R-1)``, in bit. Se il ritardo si propaga in modo markoviano lungo
la corsa - il presente dipende dal passato solo attraverso il passato immediato -
quella quantita' e' nulla.

**Perche' il valore da solo non significa nulla, e serve un riferimento.**
L'informazione mutua stimata da frequenze campionarie e' **sistematicamente
positiva anche quando la vera e' zero**: il numero di celle e la numerosita'
finita bastano a produrla. Un valore di 0,03 bit non e' interpretabile finche'
non si sa quanto valga lo zero su quella stessa griglia e con quel campione. Il
riferimento si costruisce percio' per **permutazione dentro gli strati di
``R-1``**: si rimescola ``R-2`` fra osservazioni che condividono lo stesso valore
di ``R-1``, il che distrugge la dipendenza condizionata e conserva sia le
marginali sia la relazione fra ``R-2`` e ``R-1``. Rimescolare globalmente sarebbe
sbagliato, perche' spezzerebbe anche quella relazione e produrrebbe un
riferimento troppo basso, facendo sembrare significativo cio' che non lo e'.

**Perche' si riporta anche ``I(R0 ; R-1)``.** Un valore assoluto in bit non
risponde alla domanda vera, che e' *quanto il secondo antenato aggiunga rispetto a
quanto il primo gia' spiega*. Il rapporto fra le due informazioni e' la scala
interpretabile.

Il modulo contiene solo logica: riceve successioni di ritardi e restituisce
numeri, senza leggere file. E' cio' che permette di verificarlo su dati costruiti
di cui si conosce la risposta, che e' l'unico modo di sapere se un estimatore
misuri quello che dice di misurare.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Otto bin, come fissato nella proposta della rete: fitti vicino allo zero, dove
# si decidono le coincidenze, e grossolani in coda, dove la differenza fra quindici
# e venti minuti non cambia alcuna scelta.
BORDI_OTTO = (-60.0, 0.0, 60.0, 120.0, 300.0, 600.0, 1200.0)
# Quattro bin, per verificare che la conclusione non dipenda dalla granularita'.
BORDI_QUATTRO = (0.0, 120.0, 600.0)


class ErroreMarkov(Exception):
    """I dati non permettono di calcolare la quantita' richiesta."""


@dataclass(frozen=True)
class Terne:
    """Le terne (due fermate a monte, una a monte, corrente) di un insieme di corse."""

    monte2: np.ndarray
    monte1: np.ndarray
    corrente: np.ndarray
    contigue: np.ndarray
    """Vero dove le tre fermate hanno ``stop_sequence`` consecutivi.

    Va tenuto perche' il GTFS non garantisce che ``stop_sequence`` sia denso: due
    fermate adiacenti nell'elenco osservato possono avere una fermata mancante fra
    loro, e in quel caso la terna non descrive tre passaggi consecutivi del
    veicolo ma tre passaggi con un buco, che e' un'altra cosa.
    """

    def __len__(self) -> int:
        return int(self.monte2.size)

    def solo_contigue(self) -> "Terne":
        m = self.contigue
        return Terne(self.monte2[m], self.monte1[m], self.corrente[m], self.contigue[m])


def discretizza(valori: np.ndarray, bordi: tuple[float, ...] = BORDI_OTTO) -> np.ndarray:
    """Indice del bin di ciascun valore, da 0 a ``len(bordi)``.

    I bin estremi sono aperti: assorbono l'anticipo grande e il ritardo grave
    invece di scartarli, perche' sono i casi che il modello deve saper
    rappresentare.
    """
    return np.searchsorted(np.asarray(bordi, dtype=float), np.asarray(valori, dtype=float),
                           side="right").astype(np.int64)


def estrai_terne(
    posizioni: np.ndarray, ritardi: np.ndarray, bordi: tuple[float, ...] = BORDI_OTTO
) -> Terne:
    """Terne consecutive dentro una singola corsa, gia' discretizzate.

    ``posizioni`` e ``ritardi`` descrivono i passaggi di **una** corsa in un
    giorno di servizio, e devono essere ordinati per posizione crescente. Si
    formano terne su osservazioni adiacenti nell'elenco, marcando quali abbiano
    anche ``stop_sequence`` consecutivi.
    """
    posizioni = np.asarray(posizioni)
    ritardi = np.asarray(ritardi)
    if posizioni.size != ritardi.size:
        raise ErroreMarkov("posizioni e ritardi di lunghezza diversa")
    if posizioni.size < 3:
        vuoto = np.empty(0, dtype=np.int64)
        return Terne(vuoto, vuoto, vuoto, np.empty(0, dtype=bool))
    if np.any(np.diff(posizioni) <= 0):
        raise ErroreMarkov("le posizioni devono essere strettamente crescenti")

    bin_ = discretizza(ritardi, bordi)
    contigue = (np.diff(posizioni[:-1]) == 1) & (np.diff(posizioni[1:]) == 1)
    return Terne(bin_[:-2], bin_[1:-1], bin_[2:], contigue)


def unisci(pezzi: list[Terne]) -> Terne:
    """Concatena le terne di piu' corse."""
    if not pezzi:
        vuoto = np.empty(0, dtype=np.int64)
        return Terne(vuoto, vuoto, vuoto, np.empty(0, dtype=bool))
    return Terne(
        np.concatenate([p.monte2 for p in pezzi]),
        np.concatenate([p.monte1 for p in pezzi]),
        np.concatenate([p.corrente for p in pezzi]),
        np.concatenate([p.contigue for p in pezzi]),
    )


def _congiunta(*colonne: np.ndarray) -> np.ndarray:
    """Tabella di contingenza delle colonne indicate, come array di conteggi."""
    if not colonne:
        raise ErroreMarkov("nessuna colonna")
    forme = [int(c.max()) + 1 if c.size else 1 for c in colonne]
    piatto = np.zeros(int(np.prod(forme)), dtype=np.int64)
    indice = np.zeros(colonne[0].size, dtype=np.int64)
    for colonna, dimensione in zip(colonne, forme):
        indice = indice * dimensione + colonna
    np.add.at(piatto, indice, 1)
    return piatto.reshape(forme)


def informazione_mutua(x: np.ndarray, y: np.ndarray) -> float:
    """``I(X ; Y)`` in bit, stimata dalle frequenze."""
    if x.size == 0:
        raise ErroreMarkov("campione vuoto")
    congiunta = _congiunta(x, y).astype(float)
    totale = congiunta.sum()
    p_xy = congiunta / totale
    p_x = p_xy.sum(axis=1, keepdims=True)
    p_y = p_xy.sum(axis=0, keepdims=True)
    atteso = p_x * p_y
    dove = (p_xy > 0) & (atteso > 0)
    return float(np.sum(p_xy[dove] * np.log2(p_xy[dove] / atteso[dove])))


def informazione_mutua_condizionata(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> float:
    """``I(X ; Y | Z)`` in bit, stimata dalle frequenze.

    Si somma sugli strati di ``Z`` pesando per la loro probabilita', che e' la
    definizione: l'informazione che ``Y`` porta su ``X`` una volta noto ``Z``.
    """
    if x.size == 0:
        raise ErroreMarkov("campione vuoto")
    congiunta = _congiunta(z, x, y).astype(float)
    totale = congiunta.sum()
    p = congiunta / totale
    p_z = p.sum(axis=(1, 2), keepdims=True)
    p_xz = p.sum(axis=2, keepdims=True)
    p_yz = p.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        atteso = p_xz * p_yz / p_z
    dove = (p > 0) & (atteso > 0)
    return float(np.sum(p[dove] * np.log2(p[dove] / atteso[dove])))


def riferimento_per_permutazione(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    ripetizioni: int = 20,
    generatore: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Quanto vale "zero" su questo campione e questa griglia: media e deviazione standard.

    Il rimescolamento avviene **dentro ogni strato di** ``Z``. E' la sola forma
    corretta per questa ipotesi: rimescolando globalmente si spezzerebbe anche la
    relazione fra ``X`` e ``Z``, e il riferimento risulterebbe piu' basso del
    dovuto, facendo sembrare significativo un valore che non lo e'.
    """
    generatore = generatore or np.random.default_rng(20260908)
    valori = []
    ordine = np.argsort(z, kind="stable")
    z_ordinato = z[ordine]
    x_ordinato = x[ordine]
    y_ordinato = y[ordine]
    tagli = np.flatnonzero(np.diff(z_ordinato)) + 1
    blocchi = np.split(np.arange(z.size), tagli)
    for _ in range(ripetizioni):
        permutato = x_ordinato.copy()
        for blocco in blocchi:
            if blocco.size > 1:
                permutato[blocco] = generatore.permutation(permutato[blocco])
        valori.append(informazione_mutua_condizionata(permutato, y_ordinato, z_ordinato))
    return float(np.mean(valori)), float(np.std(valori))


@dataclass(frozen=True)
class EsitoMarkov:
    """Il verdetto su una popolazione di terne, con cio' che serve a leggerlo."""

    terne: int
    condizionata: float
    """``I(R0 ; R-2 | R-1)``, la quantita' che deve essere nulla."""
    riferimento: float
    scarto_riferimento: float
    mutua_semplice: float
    """``I(R0 ; R-1)``, l'informazione del solo antenato immediato: la scala."""

    @property
    def eccesso(self) -> float:
        """Quanto la condizionata supera lo zero effettivo, in bit."""
        return self.condizionata - self.riferimento

    @property
    def quota_sul_primo_antenato(self) -> float:
        """L'eccesso in rapporto a cio' che il primo antenato gia' spiega."""
        return self.eccesso / self.mutua_semplice if self.mutua_semplice > 0 else float("nan")

    @property
    def compatibile_con_zero(self) -> bool:
        """Vero se l'eccesso non supera tre deviazioni standard del riferimento."""
        return self.eccesso <= 3.0 * self.scarto_riferimento


def valuta(terne: Terne, ripetizioni: int = 20,
           generatore: np.random.Generator | None = None) -> EsitoMarkov:
    """Calcola le tre quantita' su una popolazione di terne."""
    if len(terne) == 0:
        raise ErroreMarkov("nessuna terna da valutare")
    media, scarto = riferimento_per_permutazione(
        terne.monte2, terne.corrente, terne.monte1, ripetizioni, generatore
    )
    return EsitoMarkov(
        terne=len(terne),
        condizionata=informazione_mutua_condizionata(
            terne.monte2, terne.corrente, terne.monte1
        ),
        riferimento=media,
        scarto_riferimento=scarto,
        mutua_semplice=informazione_mutua(terne.monte1, terne.corrente),
    )


def scala_per_granularita(
    grezzo2: np.ndarray,
    grezzo1: np.ndarray,
    grezzo0: np.ndarray,
    numeri_di_bin: tuple[int, ...] = (4, 6, 8, 12, 20),
    estremi: tuple[float, float] = (-600.0, 1800.0),
    ripetizioni: int = 8,
    generatore: np.random.Generator | None = None,
) -> list[tuple[int, EsitoMarkov]]:
    """Come cambia l'eccesso al raffinarsi della discretizzazione.

    **E' il discriminante che il riferimento per permutazione da solo non fornisce,
    ed e' emerso costruendo il test invece che progettandolo.** Discretizzare una
    catena markoviana **crea** dipendenza condizionata apparente: il bin di
    ``R-1`` non porta tutta l'informazione del valore continuo che rappresenta, e
    ``R-2`` ne conserva un residuo. Misurato su una catena markoviana per
    costruzione, l'eccesso vale l'1,6% di cio' che il primo antenato spiega con
    otto bin e il 3,3% con quattro, mentre il riferimento per permutazione vale
    dodici volte meno: usando solo quello, un processo perfettamente markoviano
    verrebbe dichiarato non markoviano.

    La distinzione si fa sul **verso della scala**. L'artefatto della
    discretizzazione si dissolve al raffinarsi dei bin, perche' bin piu' stretti
    perdono meno informazione: sulla catena costruita passa dal 3,6% a due bin
    allo 0,1% a venti. Una dipendenza vera non ha ragione di svanire, e anzi
    emerge meglio quando i bin smettono di confonderla. Se l'eccesso misurato sui
    dati **cala verso zero** al crescere dei bin, e' discretizzazione; se resta o
    cresce, e' struttura.

    Il vantaggio di questo criterio e' che non richiede alcuna ipotesi sul
    processo continuo sottostante, che sui dati veri non conosciamo.
    """
    if not numeri_di_bin:
        raise ErroreMarkov("nessuna granularita' richiesta")
    esiti = []
    for quanti in numeri_di_bin:
        if quanti < 2:
            raise ErroreMarkov(f"servono almeno due bin, richiesti {quanti}")
        bordi = tuple(np.linspace(estremi[0], estremi[1], quanti - 1))
        terne = Terne(
            discretizza(grezzo2, bordi),
            discretizza(grezzo1, bordi),
            discretizza(grezzo0, bordi),
            np.ones(np.asarray(grezzo2).size, dtype=bool),
        )
        esiti.append((quanti, valuta(terne, ripetizioni, generatore)))
    return esiti


def eccesso_si_dissolve(scala: list[tuple[int, EsitoMarkov]]) -> bool:
    """Vero se la quota cala in modo netto al raffinarsi dei bin.

    Il confronto e' fra la granularita' piu' grossolana e la piu' fine: si chiede
    che l'ultima valga meno di un terzo della prima. Non si pretende monotonia,
    perche' con bin pochi e larghi la quota oscilla per ragioni di
    campionamento, ma la direzione complessiva deve essere inequivocabile.
    """
    if len(scala) < 2:
        raise ErroreMarkov("servono almeno due granularita' per giudicare la scala")
    prima = scala[0][1].quota_sul_primo_antenato
    ultima = scala[-1][1].quota_sul_primo_antenato
    if not np.isfinite(prima) or not np.isfinite(ultima) or prima <= 0:
        return False
    return ultima < prima / 3.0


TERNE_PER_CELLA = 50
"""Terne minime per cella della tabella condizionata, perche' una stima sia leggibile.

Il numero di celle cresce con il **cubo** dei bin: a venti bin sono ottomila, e
una scala calcolata su poche migliaia di terne avrebbe meno di una osservazione
per cella. La stima non diventa allora imprecisa, diventa **priva di significato**,
e continua a produrre un numero: sulla giornata di sviluppo la scala oscillava fra
il 2,0% e il 4,8% senza alcun andamento, e il criterio del verso avrebbe emesso un
verdetto sul rumore.

Cinquanta per cella e' un requisito prudente ma non arbitrario: sotto quella
soglia la frequenza congiunta di una cella e' dominata dalla variabilita'
campionaria, e l'informazione mutua che se ne stima e' quasi tutta bias.
"""


def granularita_sostenibili(
    terne: int, numeri_di_bin: tuple[int, ...], per_cella: int = TERNE_PER_CELLA
) -> tuple[int, ...]:
    """Le granularita' che il campione puo' sostenere, dato il numero di terne.

    Una granularita' esclusa non e' un dato mancante: e' una misura che non va
    calcolata, perche' il numero che produrrebbe verrebbe letto come gli altri.
    """
    return tuple(k for k in numeri_di_bin if terne >= per_cella * k ** 3)


def verdetto_sulla_scala(
    scala: list[tuple[int, EsitoMarkov]], granularita_minime: int = 3
) -> tuple[bool | None, str]:
    """Il verdetto, oppure il rifiuto di pronunciarlo.

    Restituisce ``None`` quando le granularita' sostenibili sono troppo poche per
    leggere un andamento. Un verdetto emesso su due punti non e' un verdetto
    debole, e' una coincidenza con un'etichetta sopra.
    """
    if len(scala) < granularita_minime:
        return None, (
            f"solo {len(scala)} granularita' sostenibili dal campione, ne servono "
            f"almeno {granularita_minime}: la scala non e' leggibile e non si giudica"
        )
    if eccesso_si_dissolve(scala):
        return True, (
            "l'eccesso si dissolve al raffinarsi dei bin: e' l'artefatto della "
            "discretizzazione, e l'assunzione markoviana regge"
        )
    return False, (
        "l'eccesso NON si dissolve al raffinarsi dei bin: la dipendenza e' "
        "strutturale e la struttura della rete va rivista"
    )


# =============================================================================
# Quanto vale l'arco: il costo-beneficio fuori campione
# =============================================================================


def _indice_piatto(genitori: tuple[np.ndarray, ...], forme: tuple[int, ...]) -> np.ndarray:
    """Indice unico della combinazione dei genitori."""
    indice = np.zeros(genitori[0].size, dtype=np.int64)
    for colonna, dimensione in zip(genitori, forme):
        indice = indice * dimensione + colonna
    return indice


def tabella_condizionata(
    genitori: tuple[np.ndarray, ...],
    figlio: np.ndarray,
    forme_genitori: tuple[int, ...],
    forma_figlio: int,
    alfa: float = 0.5,
) -> np.ndarray:
    """Probabilita' del figlio dati i genitori, con priore di Dirichlet uniforme.

    Il lisciamento non e' un dettaglio implementativo ma la condizione perche' il
    confronto sia onesto: senza, una combinazione di genitori mai vista in
    addestramento darebbe probabilita' nulla e perdita infinita, e il modello con
    piu' genitori - che ha otto volte le celle e quindi molte piu' combinazioni
    mai viste - verrebbe punito per un difetto della stima invece che per la
    propria struttura. Lo stesso ``alfa`` si applica a entrambi.
    """
    conteggi = np.zeros((int(np.prod(forme_genitori)), forma_figlio), dtype=np.float64)
    np.add.at(conteggi, (_indice_piatto(genitori, forme_genitori), figlio), 1.0)
    conteggi += alfa
    return conteggi / conteggi.sum(axis=1, keepdims=True)


def perdita_logaritmica(
    tabella: np.ndarray,
    genitori: tuple[np.ndarray, ...],
    figlio: np.ndarray,
    forme_genitori: tuple[int, ...],
) -> float:
    """Bit medi necessari a codificare il figlio con quella tabella.

    E' la grandezza in cui si misura se un arco valga il proprio prezzo: dentro il
    campione un genitore in piu' non puo' che migliorarla, fuori campione paga il
    costo delle celle che deve stimare.
    """
    if figlio.size == 0:
        raise ErroreMarkov("campione di verifica vuoto")
    probabilita = tabella[_indice_piatto(genitori, forme_genitori), figlio]
    return float(-np.mean(np.log2(probabilita)))


@dataclass(frozen=True)
class Confronto:
    """Il costo e il beneficio dell'arco in piu', misurati fuori campione."""

    terne_addestramento: int
    terne_verifica: int
    celle_senza: int
    celle_con: int
    perdita_senza: float
    perdita_con: float
    alfa: float

    @property
    def guadagno(self) -> float:
        """Bit risparmiati per osservazione aggiungendo l'arco. Negativo se peggiora."""
        return self.perdita_senza - self.perdita_con

    @property
    def guadagno_relativo(self) -> float:
        return self.guadagno / self.perdita_senza if self.perdita_senza > 0 else float("nan")


def confronta_strutture(
    monte2: np.ndarray,
    monte1: np.ndarray,
    corrente: np.ndarray,
    addestramento: np.ndarray,
    n_bin: int,
    alfa: float = 0.5,
) -> Confronto:
    """Perdita fuori campione con e senza l'arco dal secondo antenato.

    ``addestramento`` e' una maschera booleana che separa le terne su cui si stima
    da quelle su cui si verifica. La separazione deve essere **per giornata** e non
    casuale: terne della stessa corsa nello stesso giorno sono legate fra loro, e
    dividerle a caso metterebbe in verifica osservazioni quasi identiche a quelle
    di addestramento, gonfiando entrambi i modelli e soprattutto quello con piu'
    parametri, che e' quello che si vuole mettere alla prova.
    """
    verifica = ~addestramento
    if not addestramento.any() or not verifica.any():
        raise ErroreMarkov("la separazione lascia vuoto uno dei due insiemi")

    senza = tabella_condizionata((monte1[addestramento],), corrente[addestramento],
                                 (n_bin,), n_bin, alfa)
    con = tabella_condizionata((monte1[addestramento], monte2[addestramento]),
                               corrente[addestramento], (n_bin, n_bin), n_bin, alfa)
    return Confronto(
        terne_addestramento=int(addestramento.sum()),
        terne_verifica=int(verifica.sum()),
        celle_senza=n_bin * n_bin,
        celle_con=n_bin * n_bin * n_bin,
        perdita_senza=perdita_logaritmica(senza, (monte1[verifica],), corrente[verifica],
                                          (n_bin,)),
        perdita_con=perdita_logaritmica(con, (monte1[verifica], monte2[verifica]),
                                        corrente[verifica], (n_bin, n_bin)),
        alfa=alfa,
    )
