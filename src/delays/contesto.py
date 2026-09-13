"""Dalle colonne di una giornata alle coppie (cella, valore) su cui si stima.

Due lavori distinti, tenuti insieme perche' il secondo consuma il primo.

**Estrarre le coppie.** La tabella stima ``P(R0 | contesto, R-1)``, dove R-1 e R0
sono i ritardi a due fermate **consecutive della stessa corsa**. Le righe grezze
non sono ne' una per passaggio - il feed ripubblica lo stesso passaggio a ogni
revisione - ne' ordinate, quindi bisogna prima ridurle all'ultima revisione di
ciascun passaggio e poi accoppiare le fermate contigue.

**Codificare il contesto.** Ogni livello della scala di risalita e' una codifica a
radice mista dei fattori che tiene: al piu' fine la linea, al piu' grossolano
nulla. Le formule sono scritte per esteso, un livello alla volta, invece di essere
generate da un ciclo sui fattori: sono cinque, vanno riportate nel documento, e
una formula che si legge a occhio si controlla a occhio.

La ragione per cui questo modulo esiste separato dallo script che legge i parquet
e' la mappa dei genitori. Dedurla dalle osservazioni sarebbe comodo e sbagliato -
vedere il docstring di ``src.delays.rete`` - quindi va calcolata sull'**intero**
prodotto cartesiano dei fattori, incluse le celle che nessuna giornata visita. Qui
si conoscono i fattori; nello script si conoscono solo le righe.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FASCE_ORARIE = (6, 9, 12, 15, 20)
"""Confini fra le fasce: notte, mattina presto, punta, meta' giornata, sera, tarda.

Sono gli stessi confini della copertura misurata in D1, e cambiarli qui
renderebbe i due risultati non confrontabili.
"""

N_FASCE = len(FASCE_ORARIE) + 1
N_GIORNI = 3
"""Feriale, sabato, festivo: il sabato ha servizio proprio in entrambe le citta'."""

LIVELLI = ("bin", "tipo", "tipo x fascia", "tipo x fascia x giorno",
           "linea x fascia x giorno")


class ErroreContesto(Exception):
    """I fattori del contesto non sono coerenti fra loro."""


def fascia_oraria(ore: np.ndarray) -> np.ndarray:
    """L'indice di fascia dell'ora programmata, fra 0 e ``N_FASCE`` escluso."""
    return np.searchsorted(np.asarray(FASCE_ORARIE), ore, side="right").astype(np.int64)


def tipo_di_giorno(giorno_settimana: np.ndarray) -> np.ndarray:
    """0 dal lunedi' al venerdi', 1 il sabato, 2 la domenica."""
    return np.where(giorno_settimana < 5, 0, np.where(giorno_settimana == 5, 1, 2))


def ultima_revisione(codice: np.ndarray, sequenza: np.ndarray,
                     istante: np.ndarray) -> np.ndarray:
    """Maschera dell'ultima revisione pubblicata di ciascun passaggio.

    Il feed ripubblica lo stesso passaggio a ogni giro, e tenere tutte le revisioni
    gonfierebbe la numerosita' con copie correlate fra loro. Si tiene l'ultima
    perche' e' quella che il pianificatore avrebbe visto piu' vicino al fatto.

    Restituisce la maschera **nell'ordine di ingresso**, cosi' chi chiama puo'
    applicarla anche a colonne che non ha passato.
    """
    if not (codice.shape == sequenza.shape == istante.shape):
        raise ErroreContesto("le tre colonne non hanno la stessa lunghezza")
    n = codice.size
    if n == 0:
        return np.zeros(0, dtype=bool)
    ordine = np.lexsort((istante, sequenza, codice))
    c, s = codice[ordine], sequenza[ordine]
    ultimo = np.empty(n, dtype=bool)
    ultimo[-1] = True
    ultimo[:-1] = (c[1:] != c[:-1]) | (s[1:] != s[:-1])
    maschera = np.zeros(n, dtype=bool)
    maschera[ordine[ultimo]] = True
    return maschera


def coppie_contigue(codice: np.ndarray, sequenza: np.ndarray) -> np.ndarray:
    """Maschera delle posizioni i tali che (i, i+1) sia una coppia utilizzabile.

    Richiede che gli array siano gia' ordinati per corsa e sequenza. Le fermate
    devono essere contigue: fra la fermata 4 e la 7 c'e' un salto, e trattarle come
    consecutive attribuirebbe alla transizione un intervallo di tempo che non ha.
    """
    if codice.size < 2:
        return np.zeros(max(0, codice.size - 1), dtype=bool)
    return (codice[1:] == codice[:-1]) & (sequenza[1:] - sequenza[:-1] == 1)


GIORNO = 86_400
RESIDUO_PLAUSIBILE = 3_600
"""Scarto massimo, tolte ventiquattro ore, perche' un ritardo sia un salto di giorno.

Il criterio precedente era la distanza da +/- 86.400 entro dieci minuti, ed era
sbagliato: un salto di giorno **piu' un ritardo reale di quaranta minuti** vale
-84.000 s, cade fuori da quella finestra e finiva contato fra le anomalie di altra
natura, mescolando due fenomeni distinti. La regola giusta non guarda la distanza
dal valore tondo ma il **residuo**: si tolgono ventiquattro ore e si guarda se cio'
che resta sia un ritardo plausibile. Un'ora di residuo copre i ritardi reali senza
catturare nient'altro, perche' un ritardo autentico di ventitre ore - il solo che
verrebbe scambiato - non esiste.
"""


def maschera_rollover(ritardo):
    """Righe il cui ritardo e' un salto di giorno, con sopra un ritardo vero o meno.

    Si toglie una giornata intera, nell'uno e nell'altro verso, e si guarda cosa
    resta: se il residuo e' un ritardo plausibile, la riga e' un salto di giorno.
    Guardare invece la distanza dal valore tondo di 86.400 lascerebbe fuori proprio
    i casi piu' frequenti, quelli in cui il mezzo era anche realmente in ritardo, e
    li mescolerebbe con anomalie di natura diversa.

    Scritta con ``np.abs`` invece del metodo ``.abs()`` perche' la usano sia la
    diagnosi del consolidamento, che lavora su ``pandas.Series``, sia la stima, che
    lavora su ``numpy.ndarray``: una sola definizione per due chiamanti, cosi' il
    criterio con cui si diagnostica e quello con cui si scarta non possono divergere.
    """
    return ((np.abs(ritardo + GIORNO) <= RESIDUO_PLAUSIBILE)
            | (np.abs(ritardo - GIORNO) <= RESIDUO_PLAUSIBILE))


SOGLIA_PUBBLICA_IL_PASSATO = 60.0
"""Secondi oltre l'orario programmato entro cui il feed deve arrivare almeno una volta.

Serve a decidere se su un feed le constatazioni **esistano**. Se il produttore
togliesse la fermata dal `trip_updates` appena il mezzo vi transita, nessun
passaggio avvenuto sarebbe mai osservabile, e il criterio di ``constatazione``
selezionerebbe soltanto le previsioni piu' anticipate - una selezione sistematica
che restituisce la coda negativa della distribuzione.

Un minuto e' una soglia larga di proposito: distingue "pubblica il passato" da
"non lo pubblica affatto", non misura quanto lo pubblichi. Sui dati raccolti la
separazione e' netta di quattro ordini di grandezza - Roma arriva a decine di
migliaia di secondi, Torino a quattro - quindi nessun valore ragionevole entro
l'ordine del minuto cambierebbe il verdetto.
"""


SOGLIA_COPERTURA_ORARIO = 0.90
"""Quota minima di righe che trovano il proprio orario programmato in una giornata.

Il ritardo e' uno scostamento da un orario programmato: una riga la cui corsa non
esiste nell'archivio statico in vigore quel giorno non ha un ritardo calcolabile, e
non entra ne' nella stima ne' nel backtesting. Che potesse succedere su scala
massiccia non era stato previsto, e quando e' successo la conseguenza si e'
manifestata altrove e senza spiegazione: una giornata romana che contribuiva sette
coppie rigiocabili invece di trenta, attribuita per giorni a un consolidamento
parziale che non c'era.

Non e' una taratura ma un confine. Sui dati raccolti ogni giornata sta **sopra il
97%** oppure **sotto il 40%**, e in mezzo non c'e' nulla: il 31 agosto e il 7
settembre, gli unici due lunedi' della finestra, Roma riconosce il 43,5% e il 46,6%
dei ``trip_id`` del proprio feed nell'archivio che ha pubblicato quel giorno. La
soglia separa due popolazioni che i dati tengono gia' separate.

**Chi la supera avvisa e non scarta.** Escludere in automatico cambierebbe in
silenzio il campione di stima, e quelle due giornate sono dentro la finestra su cui
il modello e' stato stimato: toglierle e' una decisione da prendere guardando i
numeri, non un effetto collaterale di un controllo. Cio' che mancava non era
l'esclusione ma la visibilita'.
"""


def copertura_orario(orario_programmato: np.ndarray) -> float:
    """Quota di righe che hanno trovato il proprio orario programmato.

    Un'array vuoto da' 1.0 e non 0.0: una giornata senza righe non e' una giornata
    mal coperta, e segnalarla come tale confonderebbe due problemi diversi.
    """
    if orario_programmato.size == 0:
        return 1.0
    return float(np.isfinite(orario_programmato).mean())


def avviso_copertura(quota: float, soglia: float = SOGLIA_COPERTURA_ORARIO) -> str:
    """Il testo dell'avviso da stampare, o stringa vuota se la copertura basta.

    Restituisce testo invece di stampare perche' chi chiama sa dove metterlo - in
    coda alla propria riga di riepilogo - e perche' cosi' la regola si collauda
    senza catturare l'uscita a schermo.
    """
    if quota >= soglia:
        return ""
    return (f"  <== ATTENZIONE: solo il {quota:.1%} delle righe ha un orario "
            f"programmato, la giornata e' in gran parte non utilizzabile")


def constatazione(orario_programmato: np.ndarray, ritardo: np.ndarray,
                  istante_feed: np.ndarray) -> np.ndarray:
    """Il passaggio era gia' avvenuto quando il feed lo ha pubblicato?

    GTFS Real-Time non offre alcun segnale di "gia' passato", quindi lo si deduce:
    se l'orario atteso - programmato piu' ritardo - e' anteriore all'istante del
    feed, il mezzo e' passato e il numero e' una constatazione; altrimenti e' una
    previsione, e vale quanto vale la previsione di chi la pubblica.
    """
    return (orario_programmato + ritardo) <= istante_feed


@dataclass(frozen=True)
class Codifica:
    """I fattori del contesto e le cinque codifiche che ne discendono.

    ``tipo_di_linea`` ha una voce per linea, col tipo di veicolo GTFS gia'
    rinumerato in un intervallo contiguo: e' l'unico legame fra i due livelli piu'
    fini, e passarlo per intero e' cio' che permette di calcolare le mappe dei
    genitori sulle celle mai osservate.
    """

    tipo_di_linea: np.ndarray
    n_tipi: int
    n_bin: int

    def __post_init__(self) -> None:
        if self.n_linee == 0:
            raise ErroreContesto("nessuna linea nella codifica")
        if self.n_tipi <= 0 or self.n_bin <= 0:
            raise ErroreContesto(f"{self.n_tipi} tipi e {self.n_bin} bin")
        if int(self.tipo_di_linea.min()) < 0 or int(self.tipo_di_linea.max()) >= self.n_tipi:
            raise ErroreContesto("un tipo di linea cade fuori dai tipi dichiarati")

    @property
    def n_linee(self) -> int:
        return int(self.tipo_di_linea.size)

    def quante(self, livello: int) -> int:
        """Quante celle ha il livello, contando anche quelle mai osservate."""
        nb, nf, ng, t, l = self.n_bin, N_FASCE, N_GIORNI, self.n_tipi, self.n_linee
        return (nb, t * nb, t * nf * nb, t * nf * ng * nb, l * nf * ng * nb)[livello]

    def celle(self, livello: int, linea: np.ndarray, fascia: np.ndarray,
              giorno: np.ndarray, bin_monte: np.ndarray) -> np.ndarray:
        """Il codice di cella di ciascuna osservazione, al livello richiesto.

        I fattori vengono promossi a interi lunghi prima di comporli. Chi chiama li
        conserva in tipi stretti - con milioni di coppie la differenza e' fra
        centosettanta megabyte e mezzo gigabyte - e il prodotto ``linea * nf`` in
        int8 traboccherebbe in silenzio dando codici di cella sbagliati anziche' un
        errore.
        """
        nb, nf, ng = self.n_bin, N_FASCE, N_GIORNI
        linea = np.asarray(linea, dtype=np.int64)
        fascia = np.asarray(fascia, dtype=np.int64)
        giorno = np.asarray(giorno, dtype=np.int64)
        bin_monte = np.asarray(bin_monte, dtype=np.int64)
        tipo = self.tipo_di_linea[linea]
        if livello == 0:
            return bin_monte
        if livello == 1:
            return tipo * nb + bin_monte
        if livello == 2:
            return (tipo * nf + fascia) * nb + bin_monte
        if livello == 3:
            return ((tipo * nf + fascia) * ng + giorno) * nb + bin_monte
        if livello == 4:
            return ((linea * nf + fascia) * ng + giorno) * nb + bin_monte
        raise ErroreContesto(f"livello {livello} inesistente")

    def bin_di_cella(self, celle: np.ndarray) -> np.ndarray:
        """Il bin del ritardo a monte di una cella, a qualunque livello.

        Il bin e' l'ultimo fattore della codifica a ogni livello, quindi si legge
        col resto della divisione. Sta qui e non nel chiamante perche' e' una
        proprieta' della codifica: se un giorno il bin non fosse piu' l'ultimo
        fattore, questo metodo cambierebbe e nessun altro.
        """
        return celle % self.n_bin

    def padre(self, livello: int) -> np.ndarray:
        """Per ogni cella del livello, la cella del livello precedente che la contiene.

        Si costruisce decodificando l'intero intervallo dei codici e ricodificandolo
        al livello di sopra: e' l'unico modo di definirla anche dove non e' passato
        nessun autobus.
        """
        if livello <= 0 or livello >= len(LIVELLI):
            raise ErroreContesto(f"il livello {livello} non ha un genitore")
        nb, nf, ng = self.n_bin, N_FASCE, N_GIORNI
        codici = np.arange(self.quante(livello), dtype=np.int64)
        bin_monte = codici % nb
        resto = codici // nb
        if livello == 1:                       # tipo x bin -> bin
            return bin_monte
        if livello == 2:                       # tipo x fascia x bin -> tipo x bin
            return (resto // nf) * nb + bin_monte
        if livello == 3:                       # + giorno -> tipo x fascia x bin
            return (resto // ng) * nb + bin_monte
        # linea x fascia x giorno x bin -> tipo x fascia x giorno x bin
        giorno = resto % ng
        fascia = (resto // ng) % nf
        linea = resto // (ng * nf)
        tipo = self.tipo_di_linea[linea]
        return ((tipo * nf + fascia) * ng + giorno) * nb + bin_monte

    def scala(self) -> tuple[np.ndarray, ...]:
        """Le quattro mappe dei genitori, dal livello 1 al 4."""
        return tuple(self.padre(i) for i in range(1, len(LIVELLI)))
