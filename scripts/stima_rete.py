"""Stima della matrice di transizione, taratura del priore e confronto fra scale.

Produce i numeri della sezione sulla rete bayesiana: la concentrazione scelta per
ciascun gradino, la perdita fuori campione delle scale a confronto, la
calibrazione, e la correlazione implicita da mettere accanto allo 0,7 inventato
nella Fase 4.

**Perche' tre insiemi di giornate e non due.** La concentrazione si sceglie
misurando una perdita fuori campione, quindi le giornate su cui la si sceglie sono
gia' state usate: riportare su quelle stesse giornate darebbe un risultato
ottimistico di quanto la scelta le ha inseguite. Le giornate sono divise in
addestramento, taratura e verifica, in quest'ordine temporale, e dopo la taratura
il modello viene ristimato su addestramento piu' taratura con l'alfa scelto. La
verifica resta intatta, e le sue giornate danno la media e la deviazione standard.

**L'ordine che il piano voleva misurare non e' esprimibile come lo era stato
scritto, e la ragione e' istruttiva.** Il piano chiedeva di confrontare "le
constatazioni al contesto grossolano" contro "le previsioni al contesto fine" come
due gradini da scambiare nella scala. In una scala a priori incatenati lo scambio
non si puo' scrivere: ogni gradino usa come priore la stima del precedente, quindi
ogni sua cella deve avere un genitore che la **contiene**. Il contesto puo' solo
infittirsi lungo la scala. Mettere "constatazioni grossolane" dopo "previsioni
fini" chiederebbe a una cella grossolana di avere per genitore una cella fine, cioe'
di essere contenuta in una sua parte.

La domanda sotto lo scambio resta pero' misurabile, e in una forma piu' diretta:
**le previsioni al livello fine aggiungono qualcosa a cio' che le constatazioni
sanno gia' dal livello grossolano?** Si risponde confrontando la scala di sole
constatazioni con la stessa scala in cui il gradino delle previsioni fini e'
inserito appena prima di quello finale. Se inserirlo migliora, le previsioni al
contesto fine portano informazione che le constatazioni non hanno; se peggiora, no.
Il confronto e' fatto **separatamente** sulle giornate di verifica ristrette alle
constatazioni e su quelle ristrette alle previsioni, come il piano prescrive, e in
caso di conflitto decide la perdita sulle constatazioni.

    python scripts/stima_rete.py
    python scripts/stima_rete.py --citta roma --giorni 6
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from src.delays.contesto import (  # noqa: E402
    LIVELLI,
    N_FASCE,
    SOGLIA_PUBBLICA_IL_PASSATO,
    Codifica,
    avviso_copertura,
    constatazione,
    coppie_contigue,
    copertura_orario,
    fascia_oraria,
    maschera_rollover,
    tipo_di_giorno,
    ultima_revisione,
)
from src.delays.markov import BORDI_OTTO, discretizza  # noqa: E402
from src.delays.rete import Livello, componi, conta, stima, tara, trasparenza  # noqa: E402
from src.gtfs.indice_statico import carica_indice, versione_valida  # noqa: E402
from src.gtfs.loader import carica_archivio  # noqa: E402

CITTA = ("roma", "torino")
FUSO = "Europe/Rome"
COLONNE = ["service_date", "trip_id", "route_id", "stop_sequence", "ritardo_secondi",
           "orario_programmato", "timestamp_feed"]

C, P, U = "constatazioni", "previsioni", "tutte"

SIGLE = ("bin", "tipo", "tipo+fascia", "tipo+fascia+gg", "linea+fascia+gg")
"""Nomi brevi dei cinque livelli, per le tabelle a colonne strette.

Troncare ``LIVELLI`` non andrebbe bene: "tipo x fascia x giorno" tagliato a
quattordici caratteri diventa indistinguibile da "tipo x fascia".
"""

# Ogni scala e' una successione di gradini (livello di contesto, popolazione), dal
# priore piu' vago alla tabella finale. Il contesto puo' restare fermo o infittirsi
# di un passo, mai allargarsi: e' il vincolo discusso nel docstring.
SCALE: dict[str, tuple[tuple[int, str], ...]] = {
    "constatazioni sole": ((0, C), (1, C), (2, C), (3, C), (4, C)),
    "previsioni al livello fine": ((0, C), (1, C), (2, C), (3, C), (4, P), (4, C)),
    "previsioni a ogni livello": ((0, P), (0, C), (1, P), (1, C), (2, P), (2, C),
                                  (3, P), (3, C), (4, P), (4, C)),
    "solo livello fine": ((4, C),),
    "solo tipo di linea": ((1, C),),
    "previsioni sole": ((0, P), (1, P), (2, P), (3, P), (4, P)),
}
SCALA_PRINCIPALE = "constatazioni sole"

# Dove il feed non pubblica le fermate gia' passate esiste una popolazione sola, e
# la scala perde la dimensione del tipo di dato: vedere Citta.scale e la voce 63.
SCALE_POPOLAZIONE_UNICA: dict[str, tuple[tuple[int, str], ...]] = {
    "popolazione unica": ((0, U), (1, U), (2, U), (3, U), (4, U)),
    "solo livello fine": ((4, U),),
    "solo tipo di linea": ((1, U),),
}
SCALA_UNICA = "popolazione unica"

RISTRETTO_DECISIONE = (0.0, 1800.0)
"""L'intervallo di ritardo in cui la scelta dell'itinerario si decide davvero.

Da zero a trenta minuti: i margini provati nella Fase 4 arrivano a trenta, e il
guadagno del pianificatore ha il suo massimo fra quindici e venti. Sotto zero la
coincidenza non e' mai in pericolo; oltre mezz'ora l'itinerario l'ha gia' persa
qualsiasi cosa il modello dica. E' qui, e non sulla coda intera, che va pesata
l'ampiezza confusa: vedi risoluzione.
"""

CORRELAZIONE_SINTETICA = 0.7
"""Il valore usato nella Fase 4, scelto per buon senso e dichiarato sintetico."""


class Dati:
    """Le coppie di una citta', accumulate giornata per giornata.

    Si conservano i **fattori** e non i codici di cella: il numero di linee si
    conosce solo alla fine, e con esso la codifica. Conservare i codici
    obbligherebbe a fissare prima quel numero, cioe' a leggere due volte.
    """

    def __init__(self) -> None:
        self.pezzi: list[dict[str, np.ndarray]] = []
        self.indice_linea: dict[str, int] = {}
        self.giorni: list[str] = []
        self.salti_di_giorno: list[tuple[str, int, int]] = []

    def aggiungi(self, giorno: str, colonne: dict[str, np.ndarray]) -> None:
        self.giorni.append(giorno)
        colonne["giornata"] = np.full(colonne["secondi_valle"].size, len(self.giorni) - 1,
                                      dtype=np.int16)
        self.pezzi.append(colonne)

    def unisci(self) -> dict[str, np.ndarray]:
        if not self.pezzi:
            return {}
        return {chiave: np.concatenate([p[chiave] for p in self.pezzi])
                for chiave in self.pezzi[0]}


def tipi_di_linea(citta: str, cartella_gtfs: Path) -> dict[str, int]:
    """Corrispondenza linea -> ``route_type`` GTFS, dall'archivio piu' recente.

    Un archivio mancante o illeggibile non deve fermare la stima: si perde un
    livello della scala, che collassa sul precedente, e lo si dichiara. Fermarsi
    costringerebbe a rieseguire l'intera lettura dei parquet per un file di
    contorno.
    """
    try:
        indice = carica_indice(cartella_gtfs / citta / "index.json", citta)
    except Exception as errore:                          # noqa: BLE001
        print(f"  [{citta}] indice GTFS non leggibile ({errore})")
        return {}
    for sd in sorted(indice.get("giorni", {}), reverse=True):
        voce = versione_valida(indice, sd)
        if voce is None:
            continue
        try:
            archivio = carica_archivio(cartella_gtfs / citta / voce["file"])
        except Exception as errore:                      # noqa: BLE001
            print(f"  [{citta}] archivio {voce['file']} non leggibile ({errore})")
            continue
        return {str(r): int(t)
                for r, t in archivio.routes[["route_id", "route_type"]].itertuples(index=False)}
    return {}


def coppie_di_un_giorno(percorso: Path, indice_linea: dict[str, int],
                        scarta_salti: bool = True
                        ) -> tuple[dict[str, np.ndarray] | None, int, int]:
    """Le transizioni fra fermate consecutive di una giornata, in secondi.

    **Non** discretizza: i bordi dei bin sono a loro volta una scelta da misurare, e
    misurarla richiede di ridiscretizzare lo stesso campione piu' volte. Fissarli
    qui obbligherebbe a rileggere i parquet per ogni insieme di bordi da provare.

    Restituisce anche quante righe sono state scartate come salti di giorno e su
    quante se ne e' partiti, perche' scartare in silenzio una parte del campione di
    stima e' esattamente il genere di cosa che poi non si ritrova piu'.
    """
    tabella = pq.read_table(percorso, columns=COLONNE)
    if tabella.num_rows == 0:
        return None, 0, 0
    n = tabella.num_rows
    sd = pd.factorize(tabella.column("service_date").to_pandas(), sort=False)[0]
    trip = pd.factorize(tabella.column("trip_id").to_pandas(), sort=False)[0]
    codice = sd.astype(np.int64) * (int(trip.max()) + 1) + trip
    seq = tabella.column("stop_sequence").to_numpy().astype(np.int64)
    rit = tabella.column("ritardo_secondi").to_numpy().astype(np.float64)
    prog = tabella.column("orario_programmato").to_pandas().to_numpy(dtype="float64",
                                                                    na_value=np.nan)
    feed = tabella.column("timestamp_feed").to_numpy().astype(np.float64)
    testo_linea = tabella.column("route_id").to_pandas().to_numpy()
    del tabella

    # La copertura si misura **qui**, sulle righe come il consolidamento le ha
    # scritte, prima di qualunque filtro: piu' avanti ``prog`` viene ristretto ai
    # salti di giorno tolti e alle ultime revisioni, e la stessa formula darebbe un
    # numero piu' alto - 41,6% invece di 36,9% sul 31 agosto - cioe' la stessa
    # grandezza con due valori a seconda di dove la si calcola. Deve coincidere con
    # ``results/copertura_orario.csv``, altrimenti il documento e lo strumento
    # direbbero cose diverse chiamandole con lo stesso nome.
    copertura = copertura_orario(prog)

    for nome in pd.unique(testo_linea):
        indice_linea.setdefault(str(nome), len(indice_linea))
    linea = np.fromiter((indice_linea[str(x)] for x in testo_linea), dtype=np.int64, count=n)

    # I salti di giorno si tolgono **prima** di scegliere l'ultima revisione, non
    # dopo: se l'ultima pubblicazione di un passaggio e' difettosa e una precedente
    # no, togliendo dopo si perderebbe il passaggio intero, mentre togliendo prima
    # si conserva l'ultima pubblicazione sana. La contiguita' richiesta piu' sotto
    # impedisce comunque che due fermate diventate adiacenti per via dello scarto
    # vengano accoppiate come se lo fossero sempre state.
    salto = maschera_rollover(rit)
    scartate = int(salto.sum())
    if scartate and scarta_salti:
        codice, seq, rit, prog, feed, linea = (
            a[~salto] for a in (codice, seq, rit, prog, feed, linea))
    if codice.size < 2:
        return None, scartate, n

    tenuta = ultima_revisione(codice, seq, feed)
    codice, seq, rit, prog, feed, linea = (
        a[tenuta] for a in (codice, seq, rit, prog, feed, linea))
    if codice.size < 2:
        return None, scartate, n
    ordine = np.lexsort((seq, codice))
    codice, seq, rit, prog, feed, linea = (
        a[ordine] for a in (codice, seq, rit, prog, feed, linea))

    gia_passato = constatazione(prog, rit, feed)
    # Quanto in la' nel passato arriva il feed: e' la statistica che dice se su
    # questo produttore le constatazioni esistano affatto. Si calcola qui perche' e'
    # l'unico punto in cui le tre colonne sono gia' lette e allineate.
    con_orario = np.isfinite(prog) & np.isfinite(feed)
    massimo_feed = float((feed[con_orario] - prog[con_orario]).max()
                         if con_orario.any() else -np.inf)
    valida = (coppie_contigue(codice, seq)
              & np.isfinite(prog[:-1]) & np.isfinite(prog[1:])
              & np.isfinite(rit[:-1]) & np.isfinite(rit[1:]))
    if not valida.any():
        return None, scartate, n

    quando = pd.to_datetime(prog[1:][valida], unit="s", utc=True).tz_convert(FUSO)
    # Tipi stretti: su Roma le coppie di quattordici giornate sono milioni, e
    # conservarle tutte in interi lunghi costerebbe mezzo gigabyte per nulla. La
    # composizione dei codici di cella promuove da sola, vedere Codifica.celle.
    return {
        "linea": linea[1:][valida].astype(np.int32),
        "fascia": fascia_oraria(quando.hour.to_numpy()).astype(np.int8),
        "giorno": tipo_di_giorno(quando.dayofweek.to_numpy()).astype(np.int8),
        # Una coppia e' constatata quando **entrambe** le osservazioni lo sono: il
        # ritardo a monte indicizza la cella, e se fosse una previsione la riga
        # sarebbe classificata da una stima invece che da un fatto.
        "constatata": (gia_passato[:-1][valida] & gia_passato[1:][valida]).astype(np.int8),
        "secondi_monte": rit[:-1][valida].astype(np.float32),
        "secondi_valle": rit[1:][valida].astype(np.float32),
        "massimo_feed_meno_programmato": massimo_feed,
        "copertura_orario": copertura,
    }, scartate, n


def discretizza_coppie(dati: dict[str, np.ndarray],
                       bordi: tuple[float, ...]) -> dict[str, np.ndarray]:
    """Aggiunge i bin del ritardo a monte e a valle, senza ricopiare il resto."""
    return dict(dati,
                monte=discretizza(dati["secondi_monte"], bordi).astype(np.int8),
                valore=discretizza(dati["secondi_valle"], bordi).astype(np.int8))


def bordi_candidati(secondi: np.ndarray,
                    quanti_bin: int = 8) -> dict[str, tuple[float, ...]]:
    """Gli insiemi di bordi da mettere a confronto, tutti con lo stesso numero di bin.

    Il numero di bin resta fisso perche' altrimenti il confronto sarebbe truccato:
    con meno bin la perdita cala per costruzione, e vincerebbe sempre la
    discretizzazione piu' grossolana.

    I bordi devono essere **gli stessi per le due citta'**, altrimenti le loro
    perdite non sono confrontabili e il paragone della voce 59 perde il suo termine
    di riferimento. I candidati che dipendono dai dati si calcolano quindi sulle
    giornate di addestramento delle due citta' messe insieme.

    - ``attuali``: quelli scelti nella Fase 3 sulla popolazione intera, previsioni
      comprese. Sono il termine di paragone, non un candidato privilegiato.
    - ``ottili``: i quantili della popolazione di stima, cioe' bin a frequenza
      uguale. Massimizzano l'entropia marginale e quindi **peggiorano** la perdita
      grezza: e' il candidato che un criterio sbagliato scarterebbe per primo.
    - ``centrati``: la stessa spaziatura degli attuali, traslata sulla mediana della
      popolazione di stima invece che sullo zero dell'orario teorico. Verifica se il
      difetto degli attuali sia di sola posizione.
    - ``misti``: meta' dei tagli nell'anticipo e meta' nel ritardo, per quantili
      dentro ciascun lato. I percentili (25/55/85 sotto, 40/70/90 sopra) sono una
      scelta dichiarata, non il risultato di una ricerca: la voce 64 riporta che il
      confronto non dipende da loro entro la variabilita' misurata.
    - ``decisione``: costruito dal problema e non dai dati, vedi il commento sotto.
    """
    finiti = secondi[np.isfinite(secondi)]
    if finiti.size == 0:
        raise ValueError("nessun ritardo finito su cui costruire i bordi")
    quantili = np.linspace(0.0, 100.0, quanti_bin + 1)[1:-1]
    mediana = float(np.median(finiti))
    # La stessa spaziatura degli attuali, letta come scarti dal loro punto centrale:
    # -60, 0, 60, 120, 300, 600, 1200 sta a zero come questi stanno alla mediana.
    scarti = (-360.0, -300.0, -240.0, -180.0, 0.0, 300.0, 900.0)
    ottili = tuple(float(round(v)) for v in np.percentile(finiti, quantili))
    centrati = tuple(float(round(mediana + s)) for s in scarti)
    # I quantili seguono la massa, e la massa e' tutta nell'anticipo: su Roma gli
    # ottili cadrebbero tutti sotto i due minuti di ritardo, e il modello
    # risolverebbe finemente l'anticipo e per niente il ritardo. Ma la domanda a cui
    # il modello serve e' P(arrivo <= T), che e' sensibile **solo** al lato del
    # ritardo: un mezzo in anticipo di tre minuti o di dieci fa perdere la stessa
    # coincidenza, cioe' nessuna. Da qui il quarto candidato, che spende meta' dei
    # bordi di qua e meta' di la' dallo zero, e li dispone per quantili dentro
    # ciascun lato invece che sulla massa complessiva.
    negativi = finiti[finiti < 0]
    positivi = finiti[finiti >= 0]
    misti: tuple[float, ...] = ()
    if negativi.size and positivi.size:
        sotto = np.percentile(negativi, [25.0, 55.0, 85.0])
        sopra = np.percentile(positivi, [40.0, 70.0, 90.0])
        misti = tuple(float(round(v)) for v in (*sotto, 0.0, *sopra))
    # Il quinto candidato non viene dai dati: viene dal **problema**. I misti
    # tagliano il ritardo a 504 s, e sopra resta un bin solo con rappresentante di
    # quasi milleseicento secondi: il modello non distingue dieci minuti da
    # quaranta, che per un pianificatore con quindici minuti di margine sono la
    # decisione opposta. Tre tagli sul ritardo presi dai margini misurati nella
    # Fase 4 - cinque, quindici e trenta minuti -, due soli sull'anticipo, che non
    # decide nulla. Sono numeri del problema, non quantili: nessuna scelta a occhio
    # su una distribuzione da inseguire.
    decisione = (-300.0, -60.0, 0.0, 120.0, 300.0, 900.0, 1800.0)
    return {
        "attuali": BORDI_OTTO,
        "ottili": ottili,
        "centrati": centrati,
        **({"misti": misti} if misti else {}),
        "decisione": decisione,
    }


def entropia_marginale(valori_dentro: np.ndarray, valori_fuori: np.ndarray,
                       n_bin: int, alfa: float = 1.0) -> float:
    """Bit del modello che ignora tutto: nessun contesto, nessun ritardo a monte.

    E' il termine da sottrarre per confrontare insiemi di bordi diversi. La perdita
    grezza da sola non lo permette: un insieme che ammucchia meta' della massa in un
    solo bin ha entropia marginale bassa, e quindi perdita bassa, per quanto male il
    modello lavori. Sottraendola resta il **guadagno**, cioe' quanto il modello
    aggiunga a chi non sa nulla, che e' la grandezza confrontabile fra bordi diversi.
    """
    conteggi = np.bincount(valori_dentro.astype(np.int64), minlength=n_bin)
    p = (conteggi + alfa) / (conteggi.sum() + alfa * n_bin)
    return float(-np.mean(np.log2(p[valori_fuori.astype(np.int64)])))


def massa_nei_bin_aperti(valori: np.ndarray, n_bin: int) -> float:
    """Quota di osservazioni nei due bin estremi, che sono aperti verso l'infinito."""
    if valori.size == 0:
        return float("nan")
    return float(np.mean((valori == 0) | (valori == n_bin - 1)))


def risoluzione(secondi: np.ndarray, valori: np.ndarray, n_bin: int,
                 ristretto: tuple[float, float] | None = None
                 ) -> tuple[float, float]:
    """Quanti secondi il modello confonde: dentro i bin aperti, e in media su tutti.

    E' la misura che decide, e le altre due non possono farlo. La perdita grezza
    premia per costruzione i bordi che ammucchiano massa in pochi bin, perche' cosi'
    l'entropia marginale cala; il guadagno sul marginale premia per costruzione i
    bin a frequenza uguale, perche' a numero di bin fisso sono quelli che alzano il
    tetto. Sono due tautologie di verso opposto, e nessuna delle due sa che cosa
    serva al pianificatore.

    Al pianificatore serve distinguere differenze dell'ordine di un margine di
    coincidenza, cioe' qualche minuto. Si riporta quindi l'ampiezza fra primo e
    novantanovesimo percentile del ritardo **dentro** i due bin aperti - dove il
    modello dichiara di non distinguere nulla - e la stessa ampiezza mediata su
    tutti i bin, pesata per quanti vi cadono. Sono secondi, non bit, e si confrontano
    col margine di coincidenza invece che con un'altra discretizzazione.

    ``ristretto`` a una coppia di estremi ricalcola le due cifre **solo sulle
    osservazioni dentro quell'intervallo**. Serve perche' la media su tutto il
    campione e' dominata dalla coda: un bordo che lascia in un bin solo i ritardi
    fra dieci minuti e sedici ore risulta poco penalizzato se quelle ore sono rare,
    ma sopra i tre minuti il modello non distingue piu' nulla - e li' vive la
    decisione del pianificatore.
    """
    if secondi.size == 0:
        return float("nan"), float("nan")
    if ristretto is not None:
        sel = (secondi >= ristretto[0]) & (secondi <= ristretto[1])
        secondi, valori = secondi[sel], valori[sel]
        if secondi.size == 0:
            return float("nan"), float("nan")
    ampiezze, pesi = {}, {}
    for b in range(n_bin):
        sel = valori == b
        if int(sel.sum()) < 2:
            continue
        v = secondi[sel]
        ampiezze[b] = float(np.percentile(v, 99) - np.percentile(v, 1))
        pesi[b] = int(sel.sum())
    if not ampiezze:
        return float("nan"), float("nan")
    # Anche l'ampiezza dei bin aperti si calcola bin per bin e poi si media: presa
    # sull'unione dei due, il taglio ai percentili estremi agirebbe sulla
    # distribuzione congiunta e potrebbe restituire un intervallo piu' stretto di
    # quello di ciascuno dei due, che non e' confrontabile con la media sugli altri.
    def media_pesata(quali: list[int]) -> float:
        scelti = [b for b in quali if b in ampiezze]
        if not scelti:
            return float("nan")
        return float(np.average([ampiezze[b] for b in scelti],
                                weights=[pesi[b] for b in scelti]))

    return media_pesata([0, n_bin - 1]), media_pesata(list(range(n_bin)))

def costruisci_scala(nome: str, gradini: tuple[tuple[int, str], ...], c: Codifica,
                     dati: dict[str, np.ndarray], dentro: np.ndarray) -> list[Livello]:
    """I gradini di una scala, ristretti alle giornate di ``dentro``.

    Il genitore e' la mappa del contesto quando il contesto si infittisce, e
    l'identita' quando a cambiare e' solo la popolazione: nel secondo caso le celle
    sono le stesse, e il gradino nuovo non fa che rivedere la stima con altri dati.
    """
    livelli: list[Livello] = []
    for i, (livello, popolazione) in enumerate(gradini):
        if i:
            passo = livello - gradini[i - 1][0]
            if passo not in (0, 1):
                raise ValueError(f"scala '{nome}': il contesto salta da "
                                 f"{gradini[i - 1][0]} a {livello}")
            padre = c.padre(livello) if passo else np.arange(c.quante(livello),
                                                             dtype=np.int64)
        else:
            padre = None
        m = dentro & maschera_popolazione(dati, popolazione)
        celle = c.celle(livello, dati["linea"][m], dati["fascia"][m],
                        dati["giorno"][m], dati["monte"][m])
        livelli.append(Livello(f"{LIVELLI[livello]} / {popolazione}", celle,
                               dati["valore"][m].astype(np.int64), c.quante(livello),
                               padre))
    return livelli


def celle_finali(gradini: tuple[tuple[int, str], ...], c: Codifica,
                 dati: dict[str, np.ndarray], m: np.ndarray) -> np.ndarray:
    """I codici di cella con cui interrogare la tabella finale di una scala."""
    livello = gradini[-1][0]
    return c.celle(livello, dati["linea"][m], dati["fascia"][m], dati["giorno"][m],
                   dati["monte"][m])


def perdite_per_giornata(modello, gradini: tuple[tuple[int, str], ...], c: Codifica,
                         dati: dict[str, np.ndarray], giornate: Sequence[int],
                         popolazione: str) -> list[float]:
    """Una perdita per ciascuna giornata di verifica: la media da sola non basta."""
    perdite = []
    for g in giornate:
        m = (dati["giornata"] == g) & maschera_popolazione(dati, popolazione)
        if not m.any():
            continue
        perdite.append(modello.perdita(celle_finali(gradini, c, dati, m),
                                       dati["valore"][m].astype(np.int64)))
    return perdite


def calibrazione(modello, gradini: tuple[tuple[int, str], ...], c: Codifica,
                 dati: dict[str, np.ndarray], m: np.ndarray, n_bin: int,
                 quanti: int = 10) -> tuple[float, pd.DataFrame]:
    """Diagramma di affidabilita' e scarto medio di calibrazione.

    Una probabilita' non si verifica una osservazione alla volta: si raccolgono
    tutte le previsioni di valore simile e si guarda con quale frequenza l'evento
    previsto sia poi accaduto. Le coppie sono (probabilita' attribuita al bin k,
    il bin osservato era k), su tutti gli otto bin e non solo su quello realizzato,
    perche' un modello che sbaglia i bin che non escono mai e' comunque sbagliato.
    """
    previste = modello.finale[celle_finali(gradini, c, dati, m)]
    avvenute = (dati["valore"][m][:, None] == np.arange(n_bin)[None, :])
    p = previste.ravel()
    y = avvenute.ravel().astype(np.float64)
    bordi = np.linspace(0.0, 1.0, quanti + 1)
    dove = np.clip(np.digitize(p, bordi[1:-1]), 0, quanti - 1)
    righe, scarto, totale = [], 0.0, p.size
    for b in range(quanti):
        sel = dove == b
        if not sel.any():
            continue
        media_p, media_y, quante = float(p[sel].mean()), float(y[sel].mean()), int(sel.sum())
        scarto += quante * abs(media_p - media_y)
        righe.append({"bin": b, "estremo_inferiore": float(bordi[b]),
                      "probabilita_media": media_p, "frequenza_osservata": media_y,
                      "coppie": quante})
    return scarto / totale, pd.DataFrame(righe)


def valori_rappresentativi(dati: dict[str, np.ndarray], n_bin: int) -> np.ndarray:
    """Il ritardo medio osservato dentro ciascun bin, in secondi.

    Serve per tradurre una distribuzione su bin in una correlazione fra numeri. I
    valori sono **misurati**, non i punti medi degli intervalli: i due bin estremi
    non hanno un punto medio, e attribuirgliene uno inventerebbe un dato.
    """
    secondi = np.concatenate([dati["secondi_monte"], dati["secondi_valle"]])
    bin_di = np.concatenate([dati["monte"], dati["valore"]])
    somma = np.bincount(bin_di, weights=secondi, minlength=n_bin)
    quanti = np.bincount(bin_di, minlength=n_bin)
    return np.divide(somma, quanti, out=np.zeros(n_bin), where=quanti > 0)


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2 or x.std() <= 0 or y.std() <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2:
        return float("nan")
    return float(spearmanr(x, y).statistic)


def correlazioni_empiriche(dati: dict[str, np.ndarray], m: np.ndarray,
                           bordi: tuple[float, ...] = BORDI_OTTO) -> dict[str, float]:
    """Le letture della dipendenza fra i ritardi in secondi, in un quadrato due per due.

    Una sola lettura non basta, e la ragione e' emersa dai dati: sul primo giro
    Torino ha dato una correlazione di Pearson di 0,999 con deviazione 0,001, che
    non e' una misura ma la firma di pochi valori enormi che dominano le somme. Un
    ritardo ha coda pesante per natura - un mezzo puo' accumulare un'ora, non puo'
    recuperarne una - e Pearson su code pesanti misura le code.

    Il secondo giro ha mostrato un difetto nel confronto stesso: mettere accanto un
    Pearson ristretto e uno Spearman su tutto varia **due** cose insieme, la
    statistica e l'intervallo, e non permette di attribuire la differenza a
    nessuna delle due. Le combinazioni sono quindi quattro, Pearson e Spearman
    ciascuno su tutto e ciascuno dentro l'intervallo che i bin risolvono, piu' la
    quota di coppie in cui i due ritardi sono **identici al secondo**, che distingue
    una dipendenza da una copia.

    ``bordi`` sono quelli **scelti**, non BORDI_OTTO: "dentro i bordi" ha senso solo
    relative alla discretizzazione del modello che si sta giudicando, e con i bordi
    sbagliati la colonna di destra misurerebbe un intervallo che il modello non usa.
    """
    vuoto = dict.fromkeys(("pearson", "pearson_dentro", "spearman", "spearman_dentro",
                           "identiche", "quota_dentro"), float("nan"))
    if int(m.sum()) < 2:
        return vuoto
    x = dati["secondi_monte"][m].astype(np.float64)
    y = dati["secondi_valle"][m].astype(np.float64)
    # L'intervallo risolto dai bin: oltre il primo e l'ultimo bordo la matrice non
    # distingue piu' nulla, quindi li' ogni correlazione misura cio' che il modello
    # per costruzione ignora.
    dentro = ((x >= bordi[0]) & (x <= bordi[-1])
              & (y >= bordi[0]) & (y <= bordi[-1]))
    xd, yd = x[dentro], y[dentro]
    return {
        "pearson": _pearson(x, y), "pearson_dentro": _pearson(xd, yd),
        "spearman": _spearman(x, y), "spearman_dentro": _spearman(xd, yd),
        "identiche": float(np.mean(x == y)), "quota_dentro": float(dentro.mean()),
    }


def code_dei_ritardi(dati: dict[str, np.ndarray], m: np.ndarray) -> dict[str, float]:
    """I quantili del ritardo osservato, per sapere che cosa c'e' nelle code.

    Serve a leggere le correlazioni: se Pearson su tutto e Pearson dentro i bordi
    divergono, la spiegazione sta qui, e va riportata invece che dedotta.
    """
    x = dati["secondi_monte"][m].astype(np.float64)
    if x.size == 0:
        return {}
    q = np.percentile(x, [0, 1, 25, 50, 75, 99, 100])
    return dict(zip(("minimo", "p1", "p25", "mediana", "p75", "p99", "massimo"),
                    (float(v) for v in q)))


def correlazione_matrice(modello, gradini: tuple[tuple[int, str], ...], c: Codifica,
                         dati: dict[str, np.ndarray], m: np.ndarray,
                         rappresentanti: np.ndarray) -> float:
    """La correlazione implicita nella tabella stimata, sui valori dei bin.

    Si pesa ciascuna cella con la frequenza con cui il traffico reale la visita:
    una media sulle celle darebbe lo stesso peso a una linea portante e a una corsa
    notturna. Il ritardo a monte si legge dal codice di cella e non dai dati, cosi'
    il numero dipende dalla tabella e dal campione solo attraverso i pesi: e' la
    correlazione che il pianificatore usera' davvero, non quella che i dati hanno.
    """
    if not m.any():
        return float("nan")
    presenti, quante = np.unique(celle_finali(gradini, c, dati, m), return_counts=True)
    peso = quante / quante.sum()
    riga = modello.finale[presenti]
    monte = rappresentanti[c.bin_di_cella(presenti)]
    valle = riga @ rappresentanti
    media_monte, media_valle = float(peso @ monte), float(peso @ valle)
    var_monte = float(peso @ (monte - media_monte) ** 2)
    # Varianza totale a valle: la legge della varianza totale, con la parte interna
    # alla cella che una media delle sole medie condizionate perderebbe.
    var_valle = float(peso @ (riga * rappresentanti ** 2).sum(1)) - media_valle ** 2
    covarianza = float(peso @ ((monte - media_monte) * (valle - media_valle)))
    if var_monte <= 0 or var_valle <= 0:
        return float("nan")
    return covarianza / float(np.sqrt(var_monte * var_valle))


def confronto_sulla_correlazione(modello, gradini: tuple[tuple[int, str], ...],
                                 c: Codifica, dati: dict[str, np.ndarray],
                                 giornate: Sequence[int], rappresentanti: np.ndarray,
                                 citta: str, popolazione: str,
                                 bordi: tuple[float, ...] = BORDI_OTTO,
                                 finestra: str = "") -> list[dict]:
    """La correlazione per citta' e per fascia oraria, con media e scarto sui giorni.

    Il confronto richiesto ha tre termini e non due: il valore empirico sui
    secondi, quello implicito nella matrice, e lo 0,7 sintetico della Fase 4. Il
    primo dice quanto i ritardi si somiglino davvero, il secondo quanto di quella
    somiglianza il modello a bin conservi, il terzo quanto un parametro scelto per
    buon senso si discosti da entrambi.
    """
    def media_e_scarto(valori: list[float]) -> tuple[float, float]:
        a = np.asarray(valori, dtype=np.float64)
        return (float(np.nanmean(a)),
                float(np.nanstd(a, ddof=1)) if a.size > 1 else 0.0)

    chiavi = ("pearson", "pearson_dentro", "spearman", "spearman_dentro",
              "identiche", "quota_dentro")
    righe = []
    for fascia in [None] + list(range(N_FASCE)):
        raccolta: dict[str, list[float]] = {k: [] for k in chiavi}
        implicite, coppie = [], 0
        tutte: dict[str, list[float]] = {k: [] for k in chiavi}
        for g in giornate:
            m = (dati["giornata"] == g) & maschera_popolazione(dati, popolazione)
            if fascia is not None:
                m = m & (dati["fascia"] == fascia)
            if int(m.sum()) < 100:
                continue
            letture = correlazioni_empiriche(dati, m, bordi)
            for k in chiavi:
                raccolta[k].append(letture[k])
            implicite.append(correlazione_matrice(modello, gradini, c, dati, m,
                                                  rappresentanti))
            coppie += int(m.sum())
            if popolazione != U:
                # Riga di raffronto sulla popolazione "tutte" della stessa citta':
                # le perdite fra Roma e Torino non sono a confronto se ciascuna sta
                # su una domanda diversa (voce 59). Le colonne "raffronto_" danno la
                # lettura omogenea, senza sostituire quella principale.
                mt = (dati["giornata"] == g) & maschera_popolazione(dati, U)
                if fascia is not None:
                    mt = mt & (dati["fascia"] == fascia)
                if int(mt.sum()) >= 100:
                    letture_t = correlazioni_empiriche(dati, mt, bordi)
                    for k in chiavi:
                        tutte[k].append(letture_t[k])
        if not implicite:
            continue
        riga = {"citta": citta, "finestra": finestra,
                "fascia": "tutte" if fascia is None else str(fascia),
                "giornate": len(implicite), "coppie": coppie}
        for k in chiavi:
            riga[k], riga[f"deviazione_{k}"] = media_e_scarto(raccolta[k])
            if tutte[k]:
                riga[f"raffronto_tutte_{k}"], riga[f"raffronto_tutte_dev_{k}"] = \
                    media_e_scarto(tutte[k])
        riga["correlazione_matrice"], riga["deviazione_matrice"] = media_e_scarto(implicite)
        riga["sintetica"] = CORRELAZIONE_SINTETICA
        riga["scarto_spearman_sintetica"] = riga["spearman"] - CORRELAZIONE_SINTETICA
        riga["scarto_pearson_sintetica"] = riga["pearson"] - CORRELAZIONE_SINTETICA
        righe.append(riga)
    return righe


def _stampa_perdite(etichetta: str, perdite: list[float]) -> str:
    if not perdite:
        return f"{etichetta}: nessuna giornata utilizzabile"
    a = np.asarray(perdite)
    return (f"{etichetta}: {a.mean():.4f} +/- {a.std(ddof=1) if a.size > 1 else 0.0:.4f} bit "
            f"su {a.size} giornate")


@dataclass
class Citta:
    """Tutto cio' che serve per stimare su una citta', letto una volta sola.

    I bin non ci sono: la scelta dei bordi e' essa stessa da misurare, e misurarla
    richiede di ridiscretizzare lo stesso campione. Rileggere i parquet per ogni
    insieme di bordi da provare costerebbe minuti per nulla.
    """

    nome: str
    dati: dict[str, np.ndarray]
    tipo_di_linea: np.ndarray
    n_tipi: int
    giorni: list[str]
    addestramento: list[int]
    taratura: list[int]
    verifica: list[int]
    constatazioni_reali: bool
    massimo_feed_meno_programmato: float
    salti_di_giorno: list[tuple[str, int, int]]
    indice_linea: dict[str, int] = field(default_factory=dict)
    """Da ``route_id`` all'indice usato dalla codifica.

    Serve al backtesting, che deve interrogare il modello partendo da un itinerario
    e non da una riga di parquet: senza questa corrispondenza il ponte verso il
    pianificatore non saprebbe quale cella guardare.
    """
    quantificate_giorni: bool = True
    """Se la divisione in addestramento/taratura/verifica e' quella progettata.

    False quando le giornate sono troppe poche e taratura e verifica coincidono:
    in quel caso anche il banco di prova dei bordi coincide con la verifica, e la
    scelta dei bordi torna a toccare il test - una condizione da dichiarare, non da
    silently subire.
    """
    forza_due_dimensioni: bool = False
    """Tiene la scala a due dimensioni anche dove le constatazioni non esistono.

    Serve solo a riprodurre i numeri precedenti alla scoperta della voce 63, per
    poter dire di quanto una correzione alla volta abbia spostato le cose. Non e'
    una configurazione: e' uno strumento di confronto, e chi lo attiva sta
    chiedendo di misurare su una popolazione che porta un nome sbagliato.
    """

    @property
    def finestra(self) -> str:
        """L'ultima giornata effettivamente usata: l'etichetta della finestra.

        Va scritta in ogni CSV. Dedurla dalla data del commit funziona finche' non
        arriva una giornata nuova, e poi smette di funzionare senza dirlo: un
        risultato che non sa da quali giornate viene non e' riproducibile, e la
        prova che lo sia diventa una coincidenza fortunata.
        """
        return self.giorni[-1] if self.giorni else ""

    def codifica(self, n_bin: int) -> Codifica:
        return Codifica(tipo_di_linea=self.tipo_di_linea, n_tipi=self.n_tipi,
                        n_bin=n_bin)

    @property
    def bordo_holdout(self) -> list[int]:
        """Le giornate su cui la scelta dei bordi viene misurata, e mai stimata.

        Le ultime due di addestramento. I bordi sono un iperparametro come alfa:
        sceglierli sulla verifica renderebbe la stima finale dentro campione. Il
        prezzo e' che il modello finale perde due giorni di dati, e chi sceglie sui
        bordi lo paga in numeri - ma la scelta tocca una tabella sola, mentre la
        verifica tocca tutti i risultati che seguono.

        Con meno di nove giornate l'addestramento ha al massimo un giorno oltre il
        banco di prova: la separazione collassa e il banco coincide con la verifica.
        Lo si segnala qui e lo si stampa, perche' e' una condizione in cui i numeri
        della scelta vanno letti dichiarandola, non una configurazione silenziosa.
        """
        if len(self.addestramento) >= 2:
            return self.addestramento[-2:]
        return self.verifica

    @property
    def scale(self) -> dict[str, tuple[tuple[int, str], ...]]:
        """Le scale da provare, che dipendono da come si comporta il produttore.

        Dove il feed non pubblica le fermate gia' passate non esistono due
        popolazioni da ordinare: esiste un solo dato, l'ultima stima pubblicata
        prima che la fermata sparisca. Tenere in piedi il gradino per tipo di dato
        li' significherebbe separare un campione in due meta' che differiscono solo
        per quanto la stima fosse anticipata, e chiamare "fatto" la meta' piu'
        anticipata. La scala perde una dimensione e ne resta una sola, il contesto.
        """
        if self.constatazioni_reali or self.forza_due_dimensioni:
            return SCALE
        return SCALE_POPOLAZIONE_UNICA


def popolazione_di_stima(c: "Citta") -> str:
    """Su quale popolazione si stima e si verifica, in questa citta'."""
    return C if (c.constatazioni_reali or c.forza_due_dimensioni) else U


def maschera_popolazione(dati: dict[str, np.ndarray], popolazione: str) -> np.ndarray:
    """Le righe di una popolazione: constatazioni, previsioni, o tutte quante."""
    if popolazione == U:
        return np.ones(dati["constatata"].size, dtype=bool)
    return dati["constatata"] == (1 if popolazione == C else 0)


def carica(citta: str, cartella: Path, cartella_gtfs: Path, quanti_giorni: int,
           fino_a: str | None = None, scarta_salti: bool = True) -> Citta | None:
    """Legge le giornate di una citta' e decide come vanno lette.

    La domanda "esistono constatazioni su questo feed" si risponde qui e con i dati,
    non con una tabella scritta a mano: se un giorno il produttore torinese
    cominciasse a pubblicare le fermate passate, la scala tornerebbe a due
    dimensioni da sola. Il criterio e' lo stesso di
    ``scripts/diagnosi_constatazioni.py``.
    """
    giorni = sorted(cartella.glob("*.parquet"))
    # La finestra si puo' fissare a una data: la raccolta continua mentre si
    # misura, e senza questo un confronto fra due esecuzioni cadrebbe su giornate
    # di verifica diverse, attribuendo alla correzione uno spostamento che e' solo
    # un giorno nuovo.
    if fino_a:
        giorni = [g for g in giorni if g.stem <= fino_a]
    if quanti_giorni:
        giorni = giorni[-quanti_giorni:]
    if len(giorni) < 5:
        print(f"  [{citta}] {len(giorni)} giornate: servono almeno cinque "
              f"(addestramento, taratura, verifica)")
        return None

    tipo_gtfs = tipi_di_linea(citta, cartella_gtfs)
    grezzi_dati = Dati()
    massimo = -np.inf
    for percorso in giorni:
        colonne, scartate, righe = coppie_di_un_giorno(
            percorso, grezzi_dati.indice_linea, scarta_salti)
        grezzi_dati.salti_di_giorno.append((percorso.stem, scartate, righe))
        if colonne is None:
            print(f"  [{citta}] {percorso.stem}: nessuna coppia utilizzabile")
            continue
        massimo = max(massimo, colonne.pop("massimo_feed_meno_programmato"))
        copertura = colonne.pop("copertura_orario")
        grezzi_dati.aggiungi(percorso.stem, colonne)
        print(f"  [{citta}] {percorso.stem}: {colonne['secondi_valle'].size:,} coppie, "
              f"{int(colonne['constatata'].sum()):,} constatate | salti di giorno "
              f"{'scartati' if scarta_salti else 'tenuti'} {scartate:,} su {righe:,} "
              f"righe ({scartate / max_uno(righe):.3%})"
              f"{avviso_copertura(copertura)}", flush=True)
    dati = grezzi_dati.unisci()
    if not dati:
        return None

    # L'ordine e' imposto dall'indice e non dall'inserzione nel dizionario: se i due
    # divergessero, ogni linea finirebbe sotto il tipo di veicolo di un'altra e
    # nessun controllo se ne accorgerebbe.
    per_indice = sorted(grezzi_dati.indice_linea.items(), key=lambda voce: voce[1])
    grezzi = [tipo_gtfs.get(nome, 3) for nome, _ in per_indice]
    noti = sum(1 for nome, _ in per_indice if nome in tipo_gtfs)
    if noti < len(per_indice):
        print(f"  [{citta}] {len(per_indice) - noti} linee su {len(per_indice)} senza "
              f"tipo nell'archivio GTFS: assegnate a bus")
    # I tipi GTFS non sono contigui (0 tram, 1 metro, 3 bus, ...): rinumerarli evita
    # tabelle con righe irraggiungibili per i tipi che la citta' non ha.
    distinti = {t: i for i, t in enumerate(sorted(set(grezzi)))}

    n = len(grezzi_dati.giorni)
    verifica = list(range(n - 4, n))
    taratura = list(range(n - 7, n - 4))
    addestramento = list(range(0, n - 7))
    if not addestramento or not taratura:
        # Con poche giornate si rinuncia a separare la taratura, e lo si dichiara:
        # l'alfa scelto sara' ottimistico, e il risultato non e' pubblicabile.
        taglio = max(1, n - 2)
        addestramento, taratura, verifica = (list(range(taglio)), list(range(taglio, n)),
                                             list(range(taglio, n)))
        print(f"  [{citta}] ATTENZIONE: {n} giornate, taratura e verifica coincidono")

    reali = massimo >= SOGLIA_PUBBLICA_IL_PASSATO
    totali = sum(s for _, s, _ in grezzi_dati.salti_di_giorno)
    esaminate = sum(r for _, _, r in grezzi_dati.salti_di_giorno)
    verbo = "scartati" if scarta_salti else "CONTATI MA TENUTI"
    print(f"  [{citta}] salti di giorno {verbo} in tutto: {totali:,} su "
          f"{esaminate:,} righe ({totali / max_uno(esaminate):.3%})")
    print(f"  [{citta}] massimo di (feed - programmato): {massimo:,.0f} s -> "
          f"{'constatazioni reali' if reali else 'CONSTATAZIONI ASSENTI, popolazione unica'}")
    return Citta(
        nome=citta, dati=dati,
        tipo_di_linea=np.array([distinti[t] for t in grezzi], dtype=np.int64),
        n_tipi=len(distinti), giorni=grezzi_dati.giorni,
        addestramento=addestramento, taratura=taratura, verifica=verifica,
        constatazioni_reali=bool(reali), massimo_feed_meno_programmato=float(massimo),
        salti_di_giorno=grezzi_dati.salti_di_giorno,
        indice_linea=dict(grezzi_dati.indice_linea),
        quantificate_giorni=len(addestramento) >= 2 and bool(taratura),
    )


def max_uno(x: int) -> int:
    """Evita la divisione per zero nelle quote, senza nascondere uno zero vero."""
    return max(1, x)


def confronta_bordi(citta: list[Citta], candidati: dict[str, tuple[float, ...]],
                    risultati: Path) -> str:
    """Sceglie i bordi dei bin misurando, e non sulla perdita grezza.

    **La perdita fuori campione da sola non puo' decidere.** Un insieme di bordi che
    ammucchia meta' della massa in un solo bin ha entropia marginale bassa, quindi
    perdita bassa, per quanto male il modello lavori: e' proprio cio' che rende i
    bordi attuali artificiosamente buoni sulle constatazioni romane, la cui mediana
    e' molto sotto il primo bordo. Il criterio equo sottrae il marginale e confronta
    il **guadagno**, cioe' quanti bit il modello aggiunga a chi non sa nulla, a
    parita' di numero di bin.

    Si riporta anche la massa nei due bin aperti verso l'infinito, dove il modello
    non distingue fra tre minuti di anticipo e ventiquattro ore. E' il costo che
    nessuna delle due perdite vede, perche' concentrare massa in un bin aperto rende
    il valore piu' prevedibile e il modello meno utile insieme.

    **La scelta dei bordi non tocca la verifica.** I bordi sono un iperparametro
    esattamente come alfa, e alfa si tara sulla taratura: valutarli anche sulle
    giornate di verifica renderebbe la selezione dentro campione e toglierebbe alla
    stima finale il suo test fuori campione. Le ultime due giornate di addestramento
    fanno da banco di prova dei bordi; la stima che le segue le usa come dati, come
    fa con tutte le altre. In questa fase alfa e' tarato sulle stesse giornate della
    valutazione: una lettura assoluta ottimistica per tutti i candidati in igual
    modo, mentre il **confronto** fra loro resta equo - cosa da dichiarare, ed e'
    dichiarata qui e nella voce 64.

    **La soglia di indistinguibilita' viene dal candidato di riferimento**, non dal
    massimo su chi e' in gara: ``attuali`` e' lo stato dell'arte precedente, la sua
    variabilita' fra giornate e' una grandezza fissata prima di guardare gli altri
    candidati, e aggiungere un candidato pessimo non puo' allargarla.
    """
    print()
    print("=" * 78)
    print("SCELTA DEI BORDI DEI BIN")
    print("=" * 78)
    for nome, bordi in candidati.items():
        print(f"  {nome:<10}: " + ", ".join(f"{b:.0f}" for b in bordi))
    print()
    print("  Le ultime due giornate di addestramento fanno da banco di prova e non")
    print("  entrano nella stima che segue; la verifica non viene toccata dalla")
    print("  scelta. In questa fase alfa e' tarato sulle stesse giornate della")
    print("  valutazione: assoluto ottimistico per tutti, confronto equo.")
    for c in citta:
        if not c.quantificate_giorni:
            print(f"  ATTENZIONE [{c.nome}]: poche giornate, il banco di prova coincide")
            print("             con la verifica: la scelta dei bordi la tocca, e i suoi")
            print("             numeri vanno letti dichiarando questa condizione.")
    print()
    print(f"  {'bordi':<10} {'citta':<8} {'marginale':>10} {'perdita':>16} "
          f"{'guadagno':>12} {'aperti':>8} {'ampiezza aperti':>16} {'media':>9} "
          f"{'confusa 0-30min':>14}")

    righe: list[dict] = []
    for nome, bordi in candidati.items():
        n_bin = len(bordi) + 1
        for c in citta:
            dati = discretizza_coppie(c.dati, bordi)
            cod = c.codifica(n_bin)
            popolazione = popolazione_di_stima(c)
            scala = SCALA_PRINCIPALE if popolazione == C else SCALA_UNICA
            gradini = c.scale[scala]
            in_addestramento = np.isin(dati["giornata"], c.addestramento)
            # Il banco di prova dei bordi: le ultime due giornate di addestramento,
            # che la stima successiva usera' come dati come tutte le altre. Con
            # meno di due giornate di margine la separazione non esiste, e lo si
            # dichiara invece di scegliere silenziosamente sulla verifica.
            banco = c.bordo_holdout
            se_banco = np.isin(dati["giornata"], banco)
            in_stima = (in_addestramento & ~se_banco) | np.isin(dati["giornata"],
                                                                c.taratura)
            m_taratura = np.isin(dati["giornata"], c.taratura) & maschera_popolazione(
                dati, popolazione)
            m_banco = se_banco & maschera_popolazione(dati, popolazione)
            esito = tara(costruisci_scala(scala, gradini, cod, dati,
                                          in_addestramento & ~se_banco),
                         celle_finali(gradini, cod, dati, m_taratura),
                         dati["valore"][m_taratura].astype(np.int64), n_bin, passate=2)
            modello = stima(costruisci_scala(scala, gradini, cod, dati, in_stima),
                            n_bin, list(esito.alfa))
            perdite = perdite_per_giornata(modello, gradini, cod, dati, banco,
                                           popolazione)
            marginale = entropia_marginale(dati["valore"][in_stima & maschera_popolazione(
                dati, popolazione)], dati["valore"][m_banco], n_bin)
            perdita = float(np.mean(perdite)) if perdite else float("nan")
            scarto = (float(np.std(perdite, ddof=1)) if len(perdite) > 1 else 0.0)
            aperti = massa_nei_bin_aperti(dati["valore"][m_banco], n_bin)
            ampiezza, media_ampiezza = risoluzione(
                dati["secondi_valle"][m_banco].astype(np.float64),
                dati["valore"][m_banco], n_bin)
            _, confusa_dec = risoluzione(
                dati["secondi_valle"][m_banco].astype(np.float64),
                dati["valore"][m_banco], n_bin, ristretto=RISTRETTO_DECISIONE)
            print(f"  {nome:<10} {c.nome:<8} {marginale:>10.4f} "
                  f"{perdita:>8.4f} +/-{scarto:<5.4f} "
                  f"{marginale - perdita:>8.4f} bit {aperti:>7.1%} "
                  f"{ampiezza:>12,.0f} s {media_ampiezza:>7,.0f} s "
                  f"{confusa_dec:>11,.0f} s")
            righe.append({
                "bordi": nome, "citta": c.nome, "finestra": c.finestra,
                "estremi": " ".join(f"{b:.0f}" for b in bordi),
                "entropia_marginale": marginale, "perdita": perdita,
                "deviazione_perdita": scarto, "guadagno": marginale - perdita,
                "massa_nei_bin_aperti": aperti,
                "ampiezza_nei_bin_aperti": ampiezza,
                "ampiezza_media_pesata": media_ampiezza,
                "ampiezza_confusa_decisione": confusa_dec,
                "giornate": len(perdite),
            })

    tavola = pd.DataFrame(righe)
    tavola.to_csv(risultati / "scelta_bordi.csv", index=False)
    print(f"\n  scritto {risultati / 'scelta_bordi.csv'} ({len(righe)} righe)")
    # Si guarda il guadagno **minimo** fra le citta' e non la media: i bordi sono gli
    # stessi per entrambe, e un insieme che vada benissimo su una e male sull'altra
    # non e' un buon compromesso ma un buon risultato su una sola.
    per_bordi = tavola.groupby("bordi")["guadagno"].min()
    print("  guadagno minimo fra le citta': "
          + " | ".join(f"{k} {v:.4f}" for k, v in per_bordi.items()))

    # Il guadagno da solo non decide: a numero di bin fisso i bin a frequenza uguale
    # alzano il tetto per costruzione, come la perdita grezza premia per costruzione
    # quelli concentrati. Sono due tautologie di verso opposto. Si usa quindi il
    # guadagno per **escludere**, non per scegliere: i candidati che ne perdono meno
    # della variabilita' fra giornate sono indistinguibili, e fra loro decide quanti
    # secondi il modello confonde, che e' la grandezza che il pianificatore sente.
    riferimento = tavola[tavola["bordi"] == "attuali"]
    if riferimento.empty:
        print("  ATTENZIONE: candidato di riferimento 'attuali' assente, la soglia di")
        print("  indistinguibilita' ricade sul massimo fra i candidati in gara.")
        soglie = {str(ri.citta): float(tavola["deviazione_perdita"].max())
                  for ri in tavola[["citta"]].drop_duplicates().itertuples()}
    else:
        # La deviazione fra giornate del candidato di riferimento, per citta': i
        # bordi sono gli stessi per entrambe, e ciascuna porta la sua variabilita'.
        soglie = {str(ri.citta): float(ri.deviazione_perdita)
                  for ri in riferimento[["citta", "deviazione_perdita"]].itertuples()}
    migliore = float(per_bordi.max())
    per_citta = {b: dict(zip(g["citta"], g["guadagno"]))
                 for b, g in tavola.groupby("bordi")}
    # Un candidato e' ammesso se il suo guadagno, in **ciascuna** citta', non dista
    # dal migliore piu' della soglia di quella citta': i bordi valgono per entrambe,
    # e una bocciatura anche su una sola esclude.
    ammessi = [b for b in per_bordi.index
               if all(per_citta[b][c] >= migliore - soglie[c] for c in soglie)]
    print("  soglia di indistinguibilita' per citta' (deviazione fra giornate del "
          "riferimento 'attuali'): "
          + " | ".join(f"{c} {s:.4f}" for c, s in sorted(soglie.items())))
    ampiezza = (tavola[tavola["bordi"].isin(ammessi)]
                .groupby("bordi")["ampiezza_confusa_decisione"].max())
    scelti = str(ampiezza.idxmin())
    print(f"  indistinguibili sul guadagno: {', '.join(sorted(ammessi))}")
    print("  ampiezza confusa nei 0-30 min, la peggiore fra le citta' (e' la "
          "grandezza che decide): "
          + " | ".join(f"{k} {v:,.0f} s" for k, v in ampiezza.items()))
    print(f"  SCELTA: {scelti}")
    print("  Si puo' imporre un insieme diverso con --bordi.")
    return scelti


def valuta(c: Citta, bordi: tuple[float, ...], risultati: Path,
           etichetta: str) -> tuple[list[dict], list[dict], list[dict]]:
    """La stima vera e propria, con i bordi ormai scelti."""
    citta, n_bin = c.nome, len(bordi) + 1
    dati = discretizza_coppie(c.dati, bordi)
    cod = c.codifica(n_bin)
    popolazione = popolazione_di_stima(c)

    print()
    print(f"  [{citta}] {cod.n_linee:,} linee, {cod.n_tipi} tipi, {n_bin} bin | "
          f"celle al livello fine {cod.quante(4):,}")
    print(f"  [{citta}] giornate: {len(c.addestramento)} addestramento, "
          f"{len(c.taratura)} taratura, {len(c.verifica)} verifica "
          f"({c.giorni[c.verifica[0]]} .. {c.giorni[c.verifica[-1]]})")
    quota = float((dati["constatata"] == 1).mean())
    print(f"  [{citta}] coppie {dati['valore'].size:,}, constatate {quota:.1%} | "
          f"popolazione di stima: {popolazione}")

    in_stima = np.isin(dati["giornata"], c.addestramento + c.taratura)
    in_addestramento = np.isin(dati["giornata"], c.addestramento)
    m_taratura = np.isin(dati["giornata"], c.taratura) & maschera_popolazione(
        dati, popolazione)
    # Righe di **raffronto**, non risultati: valutare la stima anche sulla
    # popolazione "tutte" serve a rendere confrontabili le perdite delle due citta',
    # che altrimenti non stanno nella stessa domanda - Roma stima sulle
    # constatazioni, Torino su tutto quello che il feed pubblica (voce 59). La riga
    # di Roma qui prodotta e' quella di raffronto; la principale resta quella sulla
    # sua popolazione.
    m_verifica_tutte = np.isin(dati["giornata"], c.verifica) & maschera_popolazione(
        dati, U)
    rappresentanti = valori_rappresentativi(dati, n_bin)
    print(f"  [{citta}] ritardo medio per bin (s): "
          + ", ".join(f"{v:.0f}" for v in rappresentanti))
    m_verifica = np.isin(dati["giornata"], c.verifica) & maschera_popolazione(
        dati, popolazione)
    code = code_dei_ritardi(dati, m_verifica)
    if code:
        print(f"  [{citta}] ritardo in verifica (s): "
              + ", ".join(f"{k} {v:.0f}" for k, v in code.items()))

    righe: list[dict] = []
    correlazioni: list[dict] = []
    trasparenze: list[dict] = []
    scale = c.scale
    for nome, gradini in scale.items():
        print()
        print(f"    --- scala: {nome} ---")
        try:
            esito = tara(costruisci_scala(nome, gradini, cod, dati, in_addestramento),
                         celle_finali(gradini, cod, dati, m_taratura),
                         dati["valore"][m_taratura].astype(np.int64), n_bin, passate=2)
        except Exception as errore:                      # noqa: BLE001
            print(f"      non tarabile: {errore}")
            continue
        print("      alfa per gradino: "
              + ", ".join(f"{SIGLE[l]}/{p[:5]}={a:g}"
                          for (l, p), a in zip(gradini, esito.alfa)))
        if esito.al_bordo:
            print(f"      ATTENZIONE: {len(esito.al_bordo)} gradini con alfa a un "
                  f"estremo della griglia ({', '.join(esito.al_bordo)})")
        # conta e componi separati invece di stima(): i conteggi servono anche a
        # misurare quanto ciascun gradino disti dal proprio genitore, e ricontarli
        # per quella sola misura costerebbe una passata sul campione per nulla.
        conteggi = conta(costruisci_scala(nome, gradini, cod, dati, in_stima), n_bin)
        modello = componi(conteggi, list(esito.alfa))
        principale = perdite_per_giornata(modello, gradini, cod, dati, c.verifica,
                                          popolazione)
        print("      " + _stampa_perdite(f"su {popolazione:<14}", principale))
        altra = []
        if popolazione == C:
            altra = perdite_per_giornata(modello, gradini, cod, dati, c.verifica, P)
            print("      " + _stampa_perdite("su previsioni   ", altra))

        scarto, diagramma = calibrazione(modello, gradini, cod, dati, m_verifica, n_bin)
        rho = correlazione_matrice(modello, gradini, cod, dati, m_verifica, rappresentanti)
        marginale = entropia_marginale(
            dati["valore"][in_stima & maschera_popolazione(dati, popolazione)],
            dati["valore"][m_verifica], n_bin)
        media = float(np.mean(principale)) if principale else float("nan")
        riga_raffronto: dict[str, float] = {}
        if popolazione != U:
            perdite_tutte = perdite_per_giornata(modello, gradini, cod, dati,
                                                 c.verifica, U)
            scarto_tutte, _ = calibrazione(modello, gradini, cod, dati,
                                           m_verifica_tutte, n_bin)
            rho_tutte = correlazione_matrice(modello, gradini, cod, dati,
                                             m_verifica_tutte, rappresentanti)
            marginale_tutte = entropia_marginale(
                dati["valore"][in_stima & maschera_popolazione(dati, U)],
                dati["valore"][m_verifica_tutte], n_bin)
            media_tutte = (float(np.mean(perdite_tutte)) if perdite_tutte
                           else float("nan"))
            dev_tutte = (float(np.std(perdite_tutte, ddof=1))
                         if len(perdite_tutte) > 1 else 0.0)
            riga_raffronto = {
                "raffronto_tutte_perdita": media_tutte,
                "raffronto_tutte_deviazione": dev_tutte,
                "raffronto_tutte_scarto_calibrazione": scarto_tutte,
                "raffronto_tutte_correlazione_implicita": rho_tutte,
                "raffronto_tutte_entropia_marginale": marginale_tutte,
                "raffronto_tutte_guadagno": marginale_tutte - media_tutte,
            }
            print(f"      [raffronto] su tutte le coppie: {media_tutte:.4f} +/- "
                  f"{dev_tutte:.4f} bit | scarto di calibrazione {scarto_tutte:.4f} | "
                  f"correlazione implicita {rho_tutte:+.3f}")
        print(f"      scarto medio di calibrazione {scarto:.4f} | "
              f"correlazione implicita nella matrice {rho:+.3f} | "
              f"guadagno sul marginale {marginale - media:+.4f} bit")
        if nome == (SCALA_PRINCIPALE if popolazione == C else SCALA_UNICA):
            diagramma.insert(0, "citta", citta)
            diagramma.to_csv(risultati / f"calibrazione_rete_{citta}.csv", index=False)
            correlazioni.extend(confronto_sulla_correlazione(
                modello, gradini, cod, dati, c.verifica, rappresentanti, citta,
                popolazione, bordi, c.finestra))
            # Un alfa al bordo superiore non si legge allargando la griglia: si
            # legge misurando quanto il gradino disti gia' dal genitore, perche'
            # per alfa che cresce la stima tende a quella del genitore.
            print("      distanza di ciascun gradino dal proprio genitore:")
            for g in trasparenza(modello, conteggi):
                trasparenze.append({
                    "citta": citta, "finestra": c.finestra, "scala": nome,
                    "gradino": g.nome, "alfa": g.alfa,
                    "al_bordo": int(g.alfa in (min(esito.candidati),
                                               max(esito.candidati))),
                    "scarto_massimo": g.scarto_massimo,
                    "divergenza_media_bit": g.divergenza_media,
                    "celle": g.celle, "celle_osservate": g.celle_osservate,
                })
                print(f"        {g.nome:<24} alfa {g.alfa:>9g} | scarto massimo "
                      f"{g.scarto_massimo:.2e} | divergenza {g.divergenza_media:.2e} bit "
                      f"| celle osservate {g.celle_osservate:,}/{g.celle:,}")

        righe.append({
            "citta": citta, "scala": nome, "bordi": etichetta, "bin": n_bin,
            "finestra": c.finestra,
            "popolazione": popolazione, "gradini": len(gradini),
            "alfa": " ".join(f"{a:g}" for a in esito.alfa),
            "alfa_al_bordo": len(esito.al_bordo),
            "perdita": media,
            "deviazione": (float(np.std(principale, ddof=1))
                           if len(principale) > 1 else 0.0),
            "entropia_marginale": marginale, "guadagno": marginale - media,
            "perdita_previsioni": float(np.mean(altra)) if altra else float("nan"),
            "deviazione_previsioni": (float(np.std(altra, ddof=1))
                                      if len(altra) > 1 else 0.0),
            "giornate_verifica": len(principale),
            "scarto_calibrazione": scarto, "correlazione_implicita": rho,
            "coppie_stima": int((in_stima & maschera_popolazione(dati,
                                                                 popolazione)).sum()),
            **riga_raffronto,
        })

    if correlazioni:
        print()
        print("    --- correlazione fra ritardo a monte e a valle ---")
        print(f"      {'':<7} {'--- su tutte le coppie ---':^33} "
              f"{'--- dentro i bordi dei bin ---':^33}")
        print(f"      {'fascia':<7} {'Pearson':>16} {'Spearman':>16} "
              f"{'Pearson':>16} {'Spearman':>16} {'dentro':>7} {'uguali':>7} "
              f"{'matrice':>16}")
        for r in correlazioni:
            print(f"      {r['fascia']:<7} "
                  f"{r['pearson']:>+8.3f} +/-{r['deviazione_pearson']:<5.3f} "
                  f"{r['spearman']:>+8.3f} +/-{r['deviazione_spearman']:<5.3f} "
                  f"{r['pearson_dentro']:>+8.3f} +/-{r['deviazione_pearson_dentro']:<5.3f} "
                  f"{r['spearman_dentro']:>+8.3f} +/-{r['deviazione_spearman_dentro']:<5.3f} "
                  f"{r['quota_dentro']:>6.1%} {r['identiche']:>6.1%} "
                  f"{r['correlazione_matrice']:>+8.3f} +/-{r['deviazione_matrice']:<5.3f}")
        print(f"      Il valore sintetico della Fase 4 e' {CORRELAZIONE_SINTETICA:.2f}.")
        print("      Le due colonne di sinistra e le due di destra differiscono per")
        print("      l'intervallo, le righe di ciascuna coppia per la statistica: cosi'")
        print("      la differenza si attribuisce all'una o all'altra e non a entrambe.")
    return righe, correlazioni, trasparenze


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--giorni", type=int, default=0)
    parser.add_argument("--bordi", default="misura",
                        help="'misura' li sceglie confrontando i candidati; "
                             "'attuali', 'ottili', 'centrati', 'misti' o 'decisione' "
                             "ne impone uno")
    parser.add_argument("--fino-a", default=None, metavar="AAAA-MM-GG",
                        help="ignora le giornate successive, per confrontare due "
                             "esecuzioni sulla stessa finestra")
    parser.add_argument("--salti", choices=("scarta", "tieni"), default="scarta",
                        help="'tieni' conserva i salti di giorno, per misurare "
                             "quanto la loro rimozione sposti i risultati")
    parser.add_argument("--scala", choices=("automatica", "due-dimensioni"),
                        default="automatica",
                        help="'due-dimensioni' tiene constatazioni e previsioni "
                             "separate anche dove le prime non esistono, per "
                             "riprodurre i numeri anteriori alla voce 63")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    # I risultati seguono --radice e non il repository: una prova su dati finti non
    # deve poter scrivere dentro results/, che e' versionato ed e' il deliverable.
    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("STIMA DELLA MATRICE DI TRANSIZIONE")
    print("=" * 78)

    citta: list[Citta] = []
    for nome in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / nome
        if not cartella.is_dir():
            print(f"  [{nome}] cartella assente: {cartella}")
            continue
        caricata = carica(nome, cartella, argomenti.radice / "data" / "raw" / "gtfs",
                          argomenti.giorni, argomenti.fino_a,
                          argomenti.salti == "scarta")
        if caricata is not None:
            caricata.forza_due_dimensioni = argomenti.scala == "due-dimensioni"
            citta.append(caricata)
    if not citta:
        print("nessuna citta' utilizzabile")
        return 1

    # I candidati che dipendono dai dati si calcolano sulle giornate di
    # addestramento **meno il banco di prova dei bordi**, e solo della prima citta'.
    # Due ragioni, entrambe di separazione. Il banco non puo' entrare nei candidati
    # che si scelgono sui dati: sarebbe dentro campione rispetto alla misura che li
    # giudica. E usare una citta' sola per volta rende i candidati stabili al
    # variare dell'altra: le perdite restano confrontabili perche' gli insiemi di
    # bordi non si spostano con la popolazione dell'un o dell'altro campione.
    prima = min(citta, key=lambda c: CITTA.index(c.nome) if c.nome in CITTA else 99)
    di_stima = prima.dati["secondi_valle"][
        np.isin(prima.dati["giornata"], prima.addestramento)
        & ~np.isin(prima.dati["giornata"], prima.bordo_holdout)
        & maschera_popolazione(prima.dati, popolazione_di_stima(prima))]
    print(f"  candidati di bordi calcolati su {prima.nome}: "
          f"{int(di_stima.size):,} osservazioni (banco escluso)")
    candidati = bordi_candidati(di_stima.astype(np.float64))
    if argomenti.bordi == "misura":
        scelti = confronta_bordi(citta, candidati, risultati)
    elif argomenti.bordi in candidati:
        scelti = argomenti.bordi
    else:
        print(f"bordi '{argomenti.bordi}' sconosciuti: {sorted(candidati)}")
        return 1
    bordi = candidati[scelti]
    print()
    print("=" * 78)
    print(f"STIMA CON I BORDI '{scelti}': " + ", ".join(f"{b:.0f}" for b in bordi))
    print("=" * 78)

    tutte: list[dict] = []
    correlazioni: list[dict] = []
    trasparenze: list[dict] = []
    for c in citta:
        righe, rho, trasp = valuta(c, bordi, risultati, scelti)
        tutte.extend(righe)
        correlazioni.extend(rho)
        trasparenze.extend(trasp)

    if tutte:
        destinazione = risultati / "stima_rete.csv"
        pd.DataFrame(tutte).to_csv(destinazione, index=False)
        print(f"\nscritto {destinazione} ({len(tutte)} righe)")
    if correlazioni:
        destinazione = risultati / "correlazione_rete.csv"
        pd.DataFrame(correlazioni).to_csv(destinazione, index=False)
        print(f"scritto {destinazione} ({len(correlazioni)} righe)")
    if trasparenze:
        destinazione = risultati / "trasparenza_gradini.csv"
        pd.DataFrame(trasparenze).to_csv(destinazione, index=False)
        print(f"scritto {destinazione} ({len(trasparenze)} righe)")
    print()
    print("Dove il feed pubblica le fermate passate decide la perdita sulle")
    print("constatazioni; dove non le pubblica esiste una popolazione sola, e")
    print("chiamarne una parte 'constatazioni' sarebbe darle un nome che non ha.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
