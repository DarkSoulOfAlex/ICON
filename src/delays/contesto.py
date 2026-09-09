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
        """Il codice di cella di ciascuna osservazione, al livello richiesto."""
        nb, nf, ng = self.n_bin, N_FASCE, N_GIORNI
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
