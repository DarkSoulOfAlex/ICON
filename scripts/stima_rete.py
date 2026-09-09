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
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from src.delays.contesto import (  # noqa: E402
    LIVELLI,
    N_FASCE,
    Codifica,
    constatazione,
    coppie_contigue,
    fascia_oraria,
    tipo_di_giorno,
    ultima_revisione,
)
from src.delays.markov import BORDI_OTTO, BORDI_QUATTRO, discretizza  # noqa: E402
from src.delays.rete import Livello, stima, tara  # noqa: E402
from src.gtfs.indice_statico import carica_indice, versione_valida  # noqa: E402
from src.gtfs.loader import carica_archivio  # noqa: E402

CITTA = ("roma", "torino")
FUSO = "Europe/Rome"
COLONNE = ["service_date", "trip_id", "route_id", "stop_sequence", "ritardo_secondi",
           "orario_programmato", "timestamp_feed"]

C, P = "constatazioni", "previsioni"

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
        self.scartate_senza_orario = 0

    def aggiungi(self, giorno: str, colonne: dict[str, np.ndarray]) -> None:
        self.giorni.append(giorno)
        colonne["giornata"] = np.full(colonne["valore"].size, len(self.giorni) - 1,
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
                        bordi: tuple[float, ...]) -> dict[str, np.ndarray] | None:
    """Le transizioni fra fermate consecutive di una giornata."""
    tabella = pq.read_table(percorso, columns=COLONNE)
    if tabella.num_rows == 0:
        return None
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

    for nome in pd.unique(testo_linea):
        indice_linea.setdefault(str(nome), len(indice_linea))
    linea = np.fromiter((indice_linea[str(x)] for x in testo_linea), dtype=np.int64, count=n)

    tenuta = ultima_revisione(codice, seq, feed)
    codice, seq, rit, prog, feed, linea = (
        a[tenuta] for a in (codice, seq, rit, prog, feed, linea))
    if codice.size < 2:
        return None
    ordine = np.lexsort((seq, codice))
    codice, seq, rit, prog, feed, linea = (
        a[ordine] for a in (codice, seq, rit, prog, feed, linea))

    gia_passato = constatazione(prog, rit, feed)
    valida = (coppie_contigue(codice, seq)
              & np.isfinite(prog[:-1]) & np.isfinite(prog[1:])
              & np.isfinite(rit[:-1]) & np.isfinite(rit[1:]))
    if not valida.any():
        return None

    quando = pd.to_datetime(prog[1:][valida], unit="s", utc=True).tz_convert(FUSO)
    # Tipi stretti: su Roma le coppie di quattordici giornate sono milioni, e
    # conservarle tutte in interi lunghi costerebbe mezzo gigabyte per nulla. La
    # composizione dei codici di cella promuove da sola, vedere Codifica.celle.
    return {
        "linea": linea[1:][valida].astype(np.int32),
        "fascia": fascia_oraria(quando.hour.to_numpy()).astype(np.int8),
        "giorno": tipo_di_giorno(quando.dayofweek.to_numpy()).astype(np.int8),
        "monte": discretizza(rit[:-1][valida], bordi).astype(np.int8),
        "valore": discretizza(rit[1:][valida], bordi).astype(np.int8),
        # Una coppia e' constatata quando **entrambe** le osservazioni lo sono: il
        # ritardo a monte indicizza la cella, e se fosse una previsione la riga
        # sarebbe classificata da una stima invece che da un fatto.
        "constatata": (gia_passato[:-1][valida] & gia_passato[1:][valida]).astype(np.int8),
        "secondi_monte": rit[:-1][valida].astype(np.float32),
        "secondi_valle": rit[1:][valida].astype(np.float32),
    }


def costruisci_scala(nome: str, c: Codifica, dati: dict[str, np.ndarray],
                     dentro: np.ndarray) -> list[Livello]:
    """I gradini di una scala, ristretti alle giornate di ``dentro``.

    Il genitore e' la mappa del contesto quando il contesto si infittisce, e
    l'identita' quando a cambiare e' solo la popolazione: nel secondo caso le celle
    sono le stesse, e il gradino nuovo non fa che rivedere la stima con altri dati.
    """
    gradini = SCALE[nome]
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
        m = dentro & (dati["constatata"] == 1 if popolazione == C
                      else dati["constatata"] == 0)
        celle = c.celle(livello, dati["linea"][m], dati["fascia"][m],
                        dati["giorno"][m], dati["monte"][m])
        livelli.append(Livello(f"{LIVELLI[livello]} / {popolazione}", celle,
                               dati["valore"][m].astype(np.int64), c.quante(livello),
                               padre))
    return livelli


def celle_finali(nome: str, c: Codifica, dati: dict[str, np.ndarray],
                 m: np.ndarray) -> np.ndarray:
    """I codici di cella con cui interrogare la tabella finale di una scala."""
    livello = SCALE[nome][-1][0]
    return c.celle(livello, dati["linea"][m], dati["fascia"][m], dati["giorno"][m],
                   dati["monte"][m])


def perdite_per_giornata(modello, nome: str, c: Codifica, dati: dict[str, np.ndarray],
                         giornate: Sequence[int], solo: str) -> list[float]:
    """Una perdita per ciascuna giornata di verifica: la media da sola non basta."""
    perdite = []
    for g in giornate:
        m = (dati["giornata"] == g) & (dati["constatata"] == (1 if solo == C else 0))
        if not m.any():
            continue
        perdite.append(modello.perdita(celle_finali(nome, c, dati, m),
                                       dati["valore"][m].astype(np.int64)))
    return perdite


def calibrazione(modello, nome: str, c: Codifica, dati: dict[str, np.ndarray],
                 m: np.ndarray, n_bin: int, quanti: int = 10) -> tuple[float, pd.DataFrame]:
    """Diagramma di affidabilita' e scarto medio di calibrazione.

    Una probabilita' non si verifica una osservazione alla volta: si raccolgono
    tutte le previsioni di valore simile e si guarda con quale frequenza l'evento
    previsto sia poi accaduto. Le coppie sono (probabilita' attribuita al bin k,
    il bin osservato era k), su tutti gli otto bin e non solo su quello realizzato,
    perche' un modello che sbaglia i bin che non escono mai e' comunque sbagliato.
    """
    previste = modello.finale[celle_finali(nome, c, dati, m)]
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


def correlazione_empirica(dati: dict[str, np.ndarray], m: np.ndarray) -> float:
    """La correlazione fra i ritardi in secondi, senza passare dai bin.

    E' la grandezza direttamente confrontabile con lo 0,7 della Fase 4, che era un
    parametro su ritardi continui. Va misurata anche quando si dispone della
    matrice, perche' la matrice vive sui bin e la discretizzazione attenua ogni
    dipendenza: la differenza fra le due e' il prezzo dei bin, non un errore.
    """
    if int(m.sum()) < 2:
        return float("nan")
    x, y = dati["secondi_monte"][m], dati["secondi_valle"][m]
    if x.std() <= 0 or y.std() <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def correlazione_matrice(modello, nome: str, c: Codifica, dati: dict[str, np.ndarray],
                         m: np.ndarray, rappresentanti: np.ndarray) -> float:
    """La correlazione implicita nella tabella stimata, sui valori dei bin.

    Si pesa ciascuna cella con la frequenza con cui il traffico reale la visita:
    una media sulle celle darebbe lo stesso peso a una linea portante e a una corsa
    notturna. Il ritardo a monte si legge dal codice di cella e non dai dati, cosi'
    il numero dipende dalla tabella e dal campione solo attraverso i pesi: e' la
    correlazione che il pianificatore usera' davvero, non quella che i dati hanno.
    """
    if not m.any():
        return float("nan")
    presenti, quante = np.unique(celle_finali(nome, c, dati, m), return_counts=True)
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


def confronto_sulla_correlazione(modello, nome: str, c: Codifica,
                                 dati: dict[str, np.ndarray], giornate: Sequence[int],
                                 rappresentanti: np.ndarray, citta: str) -> list[dict]:
    """La correlazione per citta' e per fascia oraria, con media e scarto sui giorni.

    Il confronto richiesto ha tre termini e non due: il valore empirico sui
    secondi, quello implicito nella matrice, e lo 0,7 sintetico della Fase 4. Il
    primo dice quanto i ritardi si somiglino davvero, il secondo quanto di quella
    somiglianza il modello a bin conservi, il terzo quanto un parametro scelto per
    buon senso si discosti da entrambi.
    """
    righe = []
    for fascia in [None] + list(range(N_FASCE)):
        empiriche, implicite, coppie = [], [], 0
        for g in giornate:
            m = (dati["giornata"] == g) & (dati["constatata"] == 1)
            if fascia is not None:
                m = m & (dati["fascia"] == fascia)
            if int(m.sum()) < 100:
                continue
            empiriche.append(correlazione_empirica(dati, m))
            implicite.append(correlazione_matrice(modello, nome, c, dati, m,
                                                  rappresentanti))
            coppie += int(m.sum())
        if not empiriche:
            continue
        e, i = np.asarray(empiriche), np.asarray(implicite)
        righe.append({
            "citta": citta, "fascia": "tutte" if fascia is None else str(fascia),
            "giornate": e.size, "coppie": coppie,
            "correlazione_empirica": float(np.nanmean(e)),
            "deviazione_empirica": float(np.nanstd(e, ddof=1)) if e.size > 1 else 0.0,
            "correlazione_matrice": float(np.nanmean(i)),
            "deviazione_matrice": float(np.nanstd(i, ddof=1)) if i.size > 1 else 0.0,
            "sintetica": CORRELAZIONE_SINTETICA,
            "scarto_empirica_sintetica": float(np.nanmean(e)) - CORRELAZIONE_SINTETICA,
            "attenuazione_dei_bin": float(np.nanmean(i)) - float(np.nanmean(e)),
        })
    return righe


def _stampa_perdite(etichetta: str, perdite: list[float]) -> str:
    if not perdite:
        return f"{etichetta}: nessuna giornata utilizzabile"
    a = np.asarray(perdite)
    return (f"{etichetta}: {a.mean():.4f} +/- {a.std(ddof=1) if a.size > 1 else 0.0:.4f} bit "
            f"su {a.size} giornate")


def elabora(citta: str, cartella: Path, cartella_gtfs: Path, risultati: Path,
            bordi: tuple[float, ...], quanti_giorni: int) -> tuple[list[dict], list[dict]]:
    n_bin = len(bordi) + 1
    giorni = sorted(cartella.glob("*.parquet"))
    if quanti_giorni:
        giorni = giorni[-quanti_giorni:]
    if len(giorni) < 5:
        print(f"  [{citta}] {len(giorni)} giornate: servono almeno cinque "
              f"(addestramento, taratura, verifica)")
        return [], []

    tipo_gtfs = tipi_di_linea(citta, cartella_gtfs)
    dati_grezzi = Dati()
    for percorso in giorni:
        colonne = coppie_di_un_giorno(percorso, dati_grezzi.indice_linea, bordi)
        if colonne is None:
            print(f"  [{citta}] {percorso.stem}: nessuna coppia utilizzabile")
            continue
        dati_grezzi.aggiungi(percorso.stem, colonne)
        print(f"  [{citta}] {percorso.stem}: {colonne['valore'].size:,} coppie, "
              f"{int(colonne['constatata'].sum()):,} constatate", flush=True)
    dati = dati_grezzi.unisci()
    if not dati:
        return [], []

    # L'ordine e' imposto dall'indice e non dall'inserzione nel dizionario: se i due
    # divergessero, ogni linea finirebbe sotto il tipo di veicolo di un'altra e
    # nessun controllo se ne accorgerebbe.
    per_indice = sorted(dati_grezzi.indice_linea.items(), key=lambda voce: voce[1])
    # I tipi GTFS non sono contigui (0 tram, 1 metro, 3 bus, ...): rinumerarli evita
    # tabelle con righe irraggiungibili per i tipi che la citta' non ha.
    grezzi = [tipo_gtfs.get(nome, 3) for nome, _ in per_indice]
    noti = sum(1 for nome, _ in per_indice if nome in tipo_gtfs)
    if noti < len(per_indice):
        print(f"  [{citta}] {len(per_indice) - noti} linee su {len(per_indice)} senza "
              f"tipo nell'archivio GTFS: assegnate a bus")
    distinti = {t: i for i, t in enumerate(sorted(set(grezzi)))}
    c = Codifica(tipo_di_linea=np.array([distinti[t] for t in grezzi], dtype=np.int64),
                 n_tipi=len(distinti), n_bin=n_bin)

    n = len(dati_grezzi.giorni)
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

    print()
    print(f"  [{citta}] {c.n_linee:,} linee, {c.n_tipi} tipi, {n_bin} bin | "
          f"celle al livello fine {c.quante(4):,}")
    print(f"  [{citta}] giornate: {len(addestramento)} addestramento, "
          f"{len(taratura)} taratura, {len(verifica)} verifica "
          f"({dati_grezzi.giorni[verifica[0]]} .. {dati_grezzi.giorni[verifica[-1]]})")
    quota = float((dati["constatata"] == 1).mean())
    print(f"  [{citta}] coppie {dati['valore'].size:,}, constatate {quota:.1%}")

    in_addestramento = np.isin(dati["giornata"], addestramento)
    in_taratura = np.isin(dati["giornata"], taratura)
    in_stima = in_addestramento | in_taratura
    m_taratura = in_taratura & (dati["constatata"] == 1)
    rappresentanti = valori_rappresentativi(dati, n_bin)
    print(f"  [{citta}] ritardo medio per bin (s): "
          + ", ".join(f"{v:.0f}" for v in rappresentanti))

    righe: list[dict] = []
    correlazioni: list[dict] = []
    for nome in SCALE:
        print()
        print(f"    --- scala: {nome} ---")
        try:
            esito = tara(costruisci_scala(nome, c, dati, in_addestramento),
                         celle_finali(nome, c, dati, m_taratura),
                         dati["valore"][m_taratura].astype(np.int64), n_bin, passate=2)
        except Exception as errore:                      # noqa: BLE001
            print(f"      non tarabile: {errore}")
            continue
        print("      alfa per gradino: "
              + ", ".join(f"{SIGLE[l]}/{p[:5]}={a:g}"
                          for (l, p), a in zip(SCALE[nome], esito.alfa)))
        modello = stima(costruisci_scala(nome, c, dati, in_stima), n_bin, list(esito.alfa))
        su_const = perdite_per_giornata(modello, nome, c, dati, verifica, C)
        su_prev = perdite_per_giornata(modello, nome, c, dati, verifica, P)
        print("      " + _stampa_perdite("su constatazioni", su_const))
        print("      " + _stampa_perdite("su previsioni   ", su_prev))

        m_verifica = np.isin(dati["giornata"], verifica) & (dati["constatata"] == 1)
        scarto, diagramma = calibrazione(modello, nome, c, dati, m_verifica, n_bin)
        rho = correlazione_matrice(modello, nome, c, dati, m_verifica, rappresentanti)
        print(f"      scarto medio di calibrazione {scarto:.4f} | "
              f"correlazione implicita nella matrice {rho:+.3f}")
        if nome == SCALA_PRINCIPALE:
            diagramma.insert(0, "citta", citta)
            diagramma.to_csv(risultati / f"calibrazione_rete_{citta}.csv", index=False)
            correlazioni.extend(confronto_sulla_correlazione(
                modello, nome, c, dati, verifica, rappresentanti, citta))

        righe.append({
            "citta": citta, "scala": nome, "bin": n_bin,
            "gradini": len(SCALE[nome]), "alfa": " ".join(f"{a:g}" for a in esito.alfa),
            "perdita_constatazioni": float(np.mean(su_const)) if su_const else float("nan"),
            "deviazione_constatazioni": (float(np.std(su_const, ddof=1))
                                         if len(su_const) > 1 else 0.0),
            "perdita_previsioni": float(np.mean(su_prev)) if su_prev else float("nan"),
            "deviazione_previsioni": (float(np.std(su_prev, ddof=1))
                                      if len(su_prev) > 1 else 0.0),
            "giornate_verifica": len(su_const),
            "scarto_calibrazione": scarto, "correlazione_implicita": rho,
            "coppie_stima": int(in_stima.sum()),
        })

    if correlazioni:
        print()
        print("    --- correlazione fra ritardo a monte e a valle ---")
        print(f"      {'fascia':<8} {'empirica':>18} {'nella matrice':>18} "
              f"{'scarto da 0,7':>14} {'attenuazione':>13}")
        for r in correlazioni:
            print(f"      {r['fascia']:<8} "
                  f"{r['correlazione_empirica']:>+9.3f} +/- {r['deviazione_empirica']:<5.3f} "
                  f"{r['correlazione_matrice']:>+9.3f} +/- {r['deviazione_matrice']:<5.3f} "
                  f"{r['scarto_empirica_sintetica']:>+14.3f} "
                  f"{r['attenuazione_dei_bin']:>+13.3f}")
        print("      L'attenuazione e' il prezzo degli otto bin, non un errore: la")
        print("      matrice non puo' esprimere le differenze interne a un bin.")
    return righe, correlazioni


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--giorni", type=int, default=0)
    parser.add_argument("--bin", type=int, choices=(4, 8), default=8)
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    # I risultati seguono --radice e non il repository: una prova su dati finti
    # non deve poter scrivere dentro results/, che e' versionato ed e' il
    # deliverable valutato.
    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    bordi = BORDI_OTTO if argomenti.bin == 8 else BORDI_QUATTRO
    print("=" * 78)
    print(f"STIMA DELLA MATRICE DI TRANSIZIONE ({argomenti.bin} bin)")
    print("=" * 78)

    tutte: list[dict] = []
    correlazioni: list[dict] = []
    for citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / citta
        if not cartella.is_dir():
            print(f"  [{citta}] cartella assente: {cartella}")
            continue
        righe, rho = elabora(citta, cartella,
                             argomenti.radice / "data" / "raw" / "gtfs", risultati,
                             bordi, argomenti.giorni)
        tutte.extend(righe)
        correlazioni.extend(rho)

    if tutte:
        destinazione = risultati / f"stima_rete_{argomenti.bin}bin.csv"
        pd.DataFrame(tutte).to_csv(destinazione, index=False)
        print(f"\nscritto {destinazione} ({len(tutte)} righe)")
    if correlazioni:
        destinazione = risultati / f"correlazione_rete_{argomenti.bin}bin.csv"
        pd.DataFrame(correlazioni).to_csv(destinazione, index=False)
        print(f"scritto {destinazione} ({len(correlazioni)} righe)")
    print()
    print("Decide la perdita sulle constatazioni: il pianificatore lavora sui ritardi")
    print("veri, e una previsione ben predetta non e' un viaggio riuscito.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
