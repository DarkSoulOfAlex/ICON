"""Il modello appreso, nella forma che il pianificatore sa consumare.

La Fase 3 stima una tabella ``P(bin del ritardo a valle | contesto, bin a monte)``.
La Fase 2 aveva pero' fissato un contratto diverso: una tratta entra, una
distribuzione continua esce, con ripartizione, quantili, campionamento e media
(vedere ``src.delays.interfaccia``). Questo modulo e' il ponte fra le due cose, ed
e' l'unico punto del progetto in cui si dichiara che cosa si assuma dentro un
bin, dove la tabella per costruzione non dice nulla.

Che cosa si assume dentro un bin, e perche' proprio quello. Ogni assunzione qui
e' la distribuzione di massima entropia compatibile con cio' che si e' misurato,
cioe' quella che aggiunge meno informazione di quanta i dati ne diano:

- nei bin limitati si conosce solo l'intervallo, e la massima entropia su un
  intervallo e' l'uniforme;
- nei due bin aperti verso l'infinito l'intervallo non basta, ma si conosce il
  ritardo medio misurato dentro quel bin, e la massima entropia su una semiretta
  con media assegnata e' l'esponenziale.

Nessuno di questi parametri e' scelto: gli estremi vengono dai bordi tarati a parte,
le medie sono misurate sulle stesse giornate su cui si stima. L'alternativa
che si e' scartata era mettere tutta la massa di un bin nel suo valore medio: la
ripartizione diventerebbe una scala a gradini, e ``P(arrivo <= T)`` salterebbe di
colpo al variare di T di un secondo, il che non e' un difetto di precisione ma un
artefatto che il pianificatore prenderebbe per un fatto.

Il ritardo a monte puo' non essere noto. Alla prima fermata di un itinerario
nessuno ha ancora osservato nulla. In quel caso non si sceglie un bin arbitrario:
si mescolano le righe della tabella pesandole con la distribuzione marginale dei
bin a monte, misurata anch'essa. E' la stessa cosa che fare la media sulla
variabile non osservata, ed e' cio' che una rete bayesiana fa per definizione.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from src.delays.contesto import Codifica, fascia_oraria, tipo_di_giorno
from src.delays.interfaccia import Distribuzione, ModelloRitardo, Tratta
from src.delays.markov import discretizza
from src.delays.rete import Modello


FUSO = ZoneInfo("Europe/Rome")


class ErroreBayesiano(Exception):
    """Il modello stimato e la codifica non combaciano."""


def quando_cade(orario_programmato: int) -> tuple[int, int]:
    """Fascia oraria e tipo di giorno di un istante, come li vede la stima.

    Passa dalle stesse funzioni di ``src.delays.contesto``: se il pianificatore
    calcolasse la fascia per conto proprio, basterebbe un confine diverso perche'
    interrogasse celle che non sono quelle in cui il modello ha imparato.
    """
    istante = datetime.fromtimestamp(int(orario_programmato), FUSO)
    return (int(fascia_oraria(np.array([istante.hour]))[0]),
            int(tipo_di_giorno(np.array([istante.weekday()]))[0]))


def _estremi(bordi: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Estremo inferiore e superiore di ciascun bin, con infiniti ai due capi."""
    b = np.asarray(bordi, dtype=np.float64)
    return (np.concatenate(([-np.inf], b)), np.concatenate((b, [np.inf])))


@dataclass(frozen=True)
class Forma:
    """Come si distribuisce la massa dentro i bin: misurata una volta, riusata sempre.

    Sta fuori da ``MassaDiscreta`` perche' non dipende dalla cella: gli estremi
    vengono dai bordi e le medie dalle giornate di stima, e ricalcolarli per ogni
    tratta di ogni itinerario costerebbe senza cambiare nulla.
    """

    bordi: tuple[float, ...]
    medie: np.ndarray
    """Ritardo medio misurato dentro ciascun bin, in secondi."""

    def __post_init__(self) -> None:
        if self.medie.size != len(self.bordi) + 1:
            raise ErroreBayesiano(
                f"{self.medie.size} medie per {len(self.bordi) + 1} bin")
        if len(self.bordi) and np.any(np.diff(self.bordi) <= 0):
            raise ErroreBayesiano("i bordi devono essere strettamente crescenti")

    @property
    def n_bin(self) -> int:
        return int(self.medie.size)

    @property
    def scale(self) -> tuple[float, float]:
        """Le scale delle due code esponenziali, dedotte dalle medie misurate.

        Se una coda risultasse degenere - media dalla parte sbagliata del bordo,
        che accadrebbe solo con un bin vuoto - si ripiega su un secondo, cioe' su
        una coda praticamente puntiforme. Meglio una coda che non si allarga di una
        che si allarga a caso.
        """
        inf, sup = _estremi(self.bordi)
        bassa = max(1.0, float(inf[1] - self.medie[0])) if self.n_bin > 1 else 1.0
        alta = max(1.0, float(self.medie[-1] - sup[-2])) if self.n_bin > 1 else 1.0
        return bassa, alta


class MassaDiscreta(Distribuzione):
    """Una distribuzione continua ricostruita da una massa sui bin.

    Uniforme dentro i bin limitati, esponenziale nei due aperti: vedere il
    docstring del modulo per il motivo.
    """

    def __init__(self, probabilita: np.ndarray, forma: Forma) -> None:
        p = np.asarray(probabilita, dtype=np.float64)
        if p.size != forma.n_bin:
            raise ErroreBayesiano(f"{p.size} probabilita' per {forma.n_bin} bin")
        if np.any(p < 0):
            raise ErroreBayesiano("una probabilita' negativa non e' una probabilita'")
        totale = float(p.sum())
        if totale <= 0:
            raise ErroreBayesiano("la massa totale e' nulla")
        self.p = p / totale
        self.forma = forma
        self.inf, self.sup = _estremi(forma.bordi)
        self.cumulata = np.concatenate(([0.0], np.cumsum(self.p)))

    def cdf(self, secondi: float) -> float:
        return float(self.cdf_vettoriale(np.array([secondi], dtype=np.float64))[0])

    def cdf_vettoriale(self, valori: np.ndarray) -> np.ndarray:
        x = np.asarray(valori, dtype=np.float64)
        bassa, alta = self.forma.scale
        n = self.forma.n_bin
        # Il bin in cui cade ciascun valore, e quanta massa sta interamente sotto.
        indice = np.clip(np.searchsorted(np.asarray(self.forma.bordi), x, side="right"),
                         0, n - 1)
        sotto = self.cumulata[indice]
        dentro = np.zeros_like(x)

        primo = indice == 0
        if primo.any() and n > 1:
            # Coda esponenziale che decade allontanandosi dal bordo verso il basso.
            dentro[primo] = np.exp((x[primo] - self.inf[1]) / bassa)
        ultimo = indice == n - 1
        if ultimo.any() and n > 1:
            dentro[ultimo] = 1.0 - np.exp(-(x[ultimo] - self.sup[n - 2]) / alta)
        interni = ~(primo | ultimo)
        if interni.any():
            i = indice[interni]
            larghezza = self.sup[i] - self.inf[i]
            dentro[interni] = np.clip((x[interni] - self.inf[i]) / larghezza, 0.0, 1.0)
        if n == 1:
            dentro[:] = 1.0
        return np.clip(sotto + self.p[indice] * dentro, 0.0, 1.0)

    def quantile(self, probabilita: float) -> float:
        q = float(probabilita)
        if not 0.0 < q < 1.0:
            raise ErroreBayesiano(f"quantile {q} fuori da (0, 1)")
        return float(self._quantili(np.array([q]))[0])

    def _quantili(self, q: np.ndarray) -> np.ndarray:
        bassa, alta = self.forma.scale
        n = self.forma.n_bin
        # Il bin che contiene il quantile: -1 perche' searchsorted conta i bordi
        # cumulati, il primo dei quali e' lo zero.
        i = np.clip(np.searchsorted(self.cumulata, q, side="right") - 1, 0, n - 1)
        residuo = np.divide(q - self.cumulata[i], self.p[i],
                            out=np.zeros_like(q), where=self.p[i] > 0)
        residuo = np.clip(residuo, 0.0, 1.0)
        fuori = np.empty_like(q)
        primo, ultimo = i == 0, i == n - 1
        if n == 1:
            return np.full_like(q, float(self.forma.medie[0]))
        interni = ~(primo | ultimo)
        # log(0) sarebbe -inf: il quantile zero della coda bassa e' meno infinito,
        # e si preferisce un valore grande ma finito, altrimenti ogni media o
        # confronto a valle diventerebbe non numerico.
        if primo.any():
            fuori[primo] = self.inf[1] + bassa * np.log(np.maximum(residuo[primo], 1e-12))
        if ultimo.any():
            fuori[ultimo] = self.sup[n - 2] - alta * np.log(
                np.maximum(1.0 - residuo[ultimo], 1e-12))
        if interni.any():
            j = i[interni]
            fuori[interni] = self.inf[j] + residuo[interni] * (self.sup[j] - self.inf[j])
        return fuori

    def campiona(self, quanti: int, generatore: np.random.Generator) -> np.ndarray:
        if quanti <= 0:
            return np.zeros(0, dtype=np.float64)
        return self._quantili(generatore.uniform(1e-9, 1 - 1e-9, size=quanti))

    def media(self) -> float:
        """Usa le medie misurate dentro i bin, non i punti medi degli intervalli.

        I due bin aperti non hanno un punto medio, e attribuirgliene uno sarebbe
        inventare; le medie misurate ci sono gia' e sono quelle giuste anche nei bin
        limitati, dove la massa non e' distribuita uniformemente sul serio.
        """
        return float(self.p @ self.forma.medie)


class ModelloBayesiano(ModelloRitardo):
    """La tabella stimata in Fase 3, esposta come modello dei ritardi.

    ``indice_linea`` traduce il ``route_id`` di una tratta nell'indice usato dalla
    codifica. Una linea che non compare - servizio nuovo, o corsa di una linea che
    nelle giornate di stima non e' mai passata - non e' un errore: si ripiega sul
    livello piu' grossolano della scala, che e' esattamente cio' per cui la scala
    esiste, e il ripiego si conta invece di restare invisibile.
    """

    sintetico = False

    def __init__(self, modello: Modello, codifica: Codifica, forma: Forma,
                 indice_linea: dict[str, int], marginale_a_monte: np.ndarray,
                 citta: str, etichetta_bordi: str) -> None:
        if codifica.n_bin != forma.n_bin:
            raise ErroreBayesiano(
                f"codifica a {codifica.n_bin} bin e forma a {forma.n_bin}")
        if modello.finale.shape != (codifica.quante(4), forma.n_bin):
            raise ErroreBayesiano(
                f"tabella {modello.finale.shape} incompatibile con "
                f"({codifica.quante(4)}, {forma.n_bin})")
        if marginale_a_monte.size != forma.n_bin:
            raise ErroreBayesiano("la marginale a monte non ha un valore per bin")
        # Il ripiego per una linea mai vista legge ``tabelle[0]`` come se fosse
        # indicizzata per bin del ritardo a monte. E' vero solo se la scala parte
        # dal livello di contesto piu' grossolano, che e' il solo bin: con una scala
        # che parta piu' in basso quella riga non fallisce, restituisce una
        # distribuzione plausibile e sbagliata. E' il genere di guasto che non si
        # manifesta finche' un giorno non si manifesta - nel backtesting il ripiego
        # non e' mai scattato, zero linee ignote su entrambe le citta' - quindi
        # l'invariante lo dichiara il costruttore invece di restare nel docstring.
        if modello.tabelle[0].shape != (forma.n_bin, forma.n_bin):
            raise ErroreBayesiano(
                f"il primo gradino della scala ha forma {modello.tabelle[0].shape} "
                f"invece di ({forma.n_bin}, {forma.n_bin}): non e' indicizzato per "
                f"bin del ritardo a monte, e il ripiego per le linee ignote "
                f"restituirebbe una distribuzione sbagliata senza dirlo"
            )
        self.modello = modello
        self.codifica = codifica
        self.forma = forma
        self.indice_linea = indice_linea
        self.marginale = np.asarray(marginale_a_monte, dtype=np.float64)
        self.marginale = self.marginale / self.marginale.sum()
        self.citta = citta
        self.nome = f"bayesiano-{citta}-{etichetta_bordi}"
        self.linee_ignote: set[str] = set()
        self.tratte_servite = 0
        self.tratte_senza_monte = 0

    def _riga(self, tratta: Tratta) -> np.ndarray:
        """La distribuzione sui bin a valle, marginalizzando cio' che non si sa."""
        self.tratte_servite += 1
        if tratta.ritardo_a_monte is None:
            self.tratte_senza_monte += 1
            pesi = self.marginale
        else:
            bin_monte = int(discretizza(np.array([float(tratta.ritardo_a_monte)]),
                                        self.forma.bordi)[0])
            pesi = np.zeros(self.forma.n_bin)
            pesi[bin_monte] = 1.0

        indice = self.indice_linea.get(str(tratta.route_id))
        if indice is None:
            self.linee_ignote.add(str(tratta.route_id))
            # Livello piu' grossolano della scala: dipende solo dal bin a monte.
            # E' il ripiego per cui la risalita esiste, e qui si vede in atto.
            return pesi @ self.modello.tabelle[0][np.arange(self.forma.n_bin)]
        fascia, giorno = quando_cade(int(tratta.orario_programmato))
        celle = self.codifica.celle(
            4, np.array([indice]), np.array([fascia]), np.array([giorno]),
            np.arange(self.forma.n_bin))
        return pesi @ self.modello.finale[celle]

    def distribuzione(self, tratta: Tratta) -> MassaDiscreta:
        return MassaDiscreta(self._riga(tratta), self.forma)

    def diagnostica(self) -> dict[str, float]:
        """Quanto il modello ha dovuto ripiegare: va riportato accanto ai risultati."""
        return {
            "tratte_servite": self.tratte_servite,
            "tratte_senza_ritardo_a_monte": self.tratte_senza_monte,
            "linee_ignote": len(self.linee_ignote),
        }
