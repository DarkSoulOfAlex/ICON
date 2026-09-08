"""Il test della proprieta' markoviana sui dati veri, citta' per citta'.

Risponde alla domanda che decide la struttura della rete bayesiana: il ritardo due
fermate a monte aggiunge informazione, dato quello a una fermata a monte? Va
risolta **prima** di stimare qualunque tabella di probabilita', perche' un arco in
piu' moltiplica per otto le celle.

**Che cosa si misura e contro che cosa si giudica.** La quantita' e'
l'informazione mutua condizionata ``I(R0 ; R-2 | R-1)``, e non si legge da sola:
si confronta con due riferimenti distinti, che catturano due confondenti diversi.
Il **riferimento per permutazione** misura il bias di stima su campioni finiti,
rimescolando ``R-2`` dentro gli strati di ``R-1``. La **scala per granularita'**
misura l'artefatto della discretizzazione, che il primo riferimento non vede
affatto: condizionare sul bin non e' condizionare sulla variabile, e su una catena
markoviana per costruzione l'eccesso risulta dodici volte il riferimento per
permutazione. Il criterio e' il verso della scala: se l'eccesso cala verso zero al
raffinarsi dei bin e' discretizzazione, se resta o cresce e' struttura. La voce 60
del registro riporta il ragionamento per esteso.

**Le tre popolazioni, e perche' la terza e' quella conclusiva.** Il ritardo che i
feed pubblicano e' in larga parte una **previsione**, emessa in media con quindici
minuti di anticipo su Roma e due su Torino. Previsioni successive della stessa
corsa potrebbero essere correlate per come sono prodotte, e non per come si muove
il veicolo. Si misura percio' separatamente sulle terne in cui tutte e tre le
osservazioni erano ancora previsioni, e su quelle in cui **tutte e tre erano gia'
passate** al momento dell'emissione, che sono constatazioni. Se la dipendenza
sparisse fra le seconde e restasse fra le prime, sarebbe un artefatto del
produttore e non un fatto sul traffico.

**Le due citta' restano separate**, per il vincolo della voce 59: le loro colonne
``ritardo_secondi`` non descrivono la stessa grandezza con la stessa
affidabilita'. Se una soddisfacesse l'assunzione e l'altra no, e' gia' un
risultato.

**Sul volume.** Roma ha 172 milioni di righe, che non entrano in memoria insieme.
Si legge un giorno alla volta, con le sole colonne necessarie, e si accumulano le
sole terne: sono dell'ordine dei passaggi, non delle osservazioni, quindi circa
settecentomila al giorno contro dodici milioni di righe lette.

    python scripts/markov_terne.py
    python scripts/markov_terne.py --citta torino --giorni 3
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from src.delays.markov import (  # noqa: E402
    BORDI_OTTO,
    BORDI_QUATTRO,
    EsitoMarkov,
    Terne,
    discretizza,
    confronta_con_contesto,
    confronta_strutture,
    granularita_sostenibili,
    quota_valori_ripetuti,
    scala_per_granularita,
    verdetto_sulla_scala,
    valuta,
)

CITTA = ("roma", "torino")
COLONNE = ["service_date", "trip_id", "route_id", "stop_sequence", "ritardo_secondi",
           "orario_programmato", "timestamp_feed"]
FUSO = "Europe/Rome"
FASCE_ORARIE = (6, 9, 12, 15, 20)
"""Confini delle sei fasce: notte, punta mattino, morbida, pranzo, punta sera, sera.

Bande di congestione e non ore uniformi, come gia"'" nella base di conoscenza:
la differenza fra le otto e le nove conta piu' di quella fra le quattordici e le
quindici.
"""
RISULTATI = RADICE / "results"
GRANULARITA = (4, 6, 8, 12, 20)


@dataclass
class Grezze:
    """Terne con i ritardi ancora continui, che servono alla scala per granularita'."""

    r2: list[np.ndarray]
    r1: list[np.ndarray]
    r0: list[np.ndarray]
    a2: list[np.ndarray]
    a1: list[np.ndarray]
    a0: list[np.ndarray]
    giorno: list[np.ndarray]
    ampiezza: list[np.ndarray]
    contesto: list[np.ndarray]
    osservazioni: int = 0
    passaggi: int = 0
    con_buco: int = 0

    @classmethod
    def vuote(cls) -> "Grezze":
        return cls([], [], [], [], [], [], [], [], [])

    def aggiungi(self, r2, r1, r0, a2, a1, a0, giorno, ampiezza, contesto) -> None:
        self.r2.append(r2); self.r1.append(r1); self.r0.append(r0)
        self.a2.append(a2); self.a1.append(a1); self.a0.append(a0)
        self.giorno.append(giorno); self.ampiezza.append(ampiezza)
        self.contesto.append(contesto)

    def unite(self) -> tuple[np.ndarray, ...]:
        if not self.r2:
            v = np.empty(0, dtype=np.float32)
            return v, v, v, v, v, v, v.astype(np.int32), v, v.astype(np.int32)
        return tuple(np.concatenate(x) for x in
                     (self.r2, self.r1, self.r0, self.a2, self.a1, self.a0,
                      self.giorno, self.ampiezza, self.contesto))


def terne_di_un_giorno(percorso: Path, grezze: Grezze, indice_giorno: int) -> None:
    """Estrae le terne di una giornata e le accumula, senza tenere le righe.

    Per ogni passaggio si conserva **una sola** osservazione, l'ultima per istante
    di emissione, che e' la piu' vicina al passaggio reale. Le altre si scartano, e
    quante siano viene contato: senza quel numero le numerosita' della tabella
    finale non sarebbero leggibili, perche' il test lavora su una frazione dei dati
    e la frazione e' diversa nelle due citta'.
    """
    tabella = pq.read_table(percorso, columns=COLONNE)
    n = tabella.num_rows
    if n == 0:
        return
    grezze.osservazioni += n

    sd = pd.factorize(tabella.column("service_date").to_pandas(), sort=False)[0]
    trip = pd.factorize(tabella.column("trip_id").to_pandas(), sort=False)[0]
    # Chiave unica di corsa-giorno: la data fa parte della chiave, per la stessa
    # ragione della voce 58, cioe' che una cartella puo' contenere due giorni di
    # servizio e la stessa corsa vi ricorre.
    codice = sd.astype(np.int64) * (int(trip.max()) + 1) + trip
    seq = tabella.column("stop_sequence").to_numpy().astype(np.int64)
    rit = tabella.column("ritardo_secondi").to_numpy().astype(np.float64)
    prog = tabella.column("orario_programmato").to_pandas().to_numpy(dtype="float64",
                                                                    na_value=np.nan)
    feed = tabella.column("timestamp_feed").to_numpy().astype(np.float64)
    linea = pd.factorize(tabella.column("route_id").to_pandas(), sort=False)[0]
    del tabella

    # Ultima osservazione per passaggio: si ordina e si prende il fondo di ogni gruppo.
    ordine = np.lexsort((feed, seq, codice))
    codice, seq, rit, prog, feed, linea = (
        a[ordine] for a in (codice, seq, rit, prog, feed, linea))
    ultimo = np.empty(n, dtype=bool)
    ultimo[-1] = True
    ultimo[:-1] = (codice[1:] != codice[:-1]) | (seq[1:] != seq[:-1])
    codice, seq, rit, prog, feed, linea = (
        a[ultimo] for a in (codice, seq, rit, prog, feed, linea))
    grezze.passaggi += int(codice.size)
    if codice.size < 3:
        return

    # L'anticipo con cui l'osservazione e' stata emessa rispetto al passaggio
    # atteso: negativo se il mezzo era gia' passato, positivo se e' previsione.
    anticipo = (prog + rit) - feed

    # Terne su osservazioni adiacenti della stessa corsa-giorno.
    stessa = (codice[2:] == codice[:-2]) & (codice[1:-1] == codice[:-2])
    valida = stessa & np.isfinite(anticipo[:-2]) & np.isfinite(anticipo[1:-1]) \
        & np.isfinite(anticipo[2:])
    contigue = (seq[1:-1] - seq[:-2] == 1) & (seq[2:] - seq[1:-1] == 1)
    grezze.con_buco += int(np.count_nonzero(valida & ~contigue))
    tieni = valida & contigue
    if not tieni.any():
        return
    # L'ampiezza temporale della terna, cioe' quanto tempo passa fra la prima e
    # l'ultima delle tre fermate secondo l'orario. Serve a mettere alla prova una
    # spiegazione alternativa: se una popolazione avesse fermate piu' ravvicinate,
    # la sua maggiore dipendenza sarebbe spiegata dalla vicinanza e non dalla
    # natura del dato.
    ampiezza = (prog[2:] - prog[:-2])[tieni].astype(np.float32)
    # Contesto della transizione, preso alla fermata di arrivo: linea, fascia
    # oraria e tipo di giorno. La distanza percorsa non entra, perche' nelle terne
    # e' sempre una fermata per costruzione.
    quando = pd.to_datetime(prog[2:][tieni], unit="s", utc=True).tz_convert(FUSO)
    fascia = np.searchsorted(np.asarray(FASCE_ORARIE), quando.hour.to_numpy(), side="right")
    settimana = quando.dayofweek.to_numpy()
    tipo_giorno = np.where(settimana < 5, 0, np.where(settimana == 5, 1, 2))
    contesto = (linea[2:][tieni].astype(np.int64) * (len(FASCE_ORARIE) + 1) + fascia) * 3         + tipo_giorno
    grezze.aggiungi(
        rit[:-2][tieni].astype(np.float32), rit[1:-1][tieni].astype(np.float32),
        rit[2:][tieni].astype(np.float32),
        anticipo[:-2][tieni].astype(np.float32), anticipo[1:-1][tieni].astype(np.float32),
        anticipo[2:][tieni].astype(np.float32),
        np.full(int(tieni.sum()), indice_giorno, dtype=np.int32), ampiezza,
        contesto.astype(np.int32),
    )


def _terne_discrete(r2, r1, r0, bordi) -> Terne:
    return Terne(discretizza(r2, bordi), discretizza(r1, bordi), discretizza(r0, bordi),
                 np.ones(r2.size, dtype=bool))


def _riga(citta: str, popolazione: str, etichetta: str, esito: EsitoMarkov) -> dict:
    return {
        "citta": citta, "popolazione": popolazione, "granularita": etichetta,
        "terne": esito.terne, "condizionata": esito.condizionata,
        "riferimento": esito.riferimento, "scarto_riferimento": esito.scarto_riferimento,
        "eccesso": esito.eccesso, "mutua_semplice": esito.mutua_semplice,
        "quota": esito.quota_sul_primo_antenato,
        "compatibile_con_zero": int(esito.compatibile_con_zero),
    }


def analizza(citta: str, grezze: Grezze, generatore: np.random.Generator) -> list[dict]:
    r2, r1, r0, a2, a1, a0, giorno, ampiezza, contesto = grezze.unite()
    if r2.size == 0:
        print(f"  [{citta}] nessuna terna utilizzabile")
        return []

    previsioni = (a2 > 0) & (a1 > 0) & (a0 > 0)
    passate = (a2 <= 0) & (a1 <= 0) & (a0 <= 0)
    popolazioni = [
        ("tutte", np.ones(r2.size, dtype=bool)),
        ("solo previsioni", previsioni),
        ("solo gia' passate", passate),
    ]

    print(f"\n  [{citta}] osservazioni lette {grezze.osservazioni:,} | "
          f"passaggi {grezze.passaggi:,} | terne contigue {r2.size:,}")
    print(f"    osservazioni per passaggio: "
          f"{grezze.osservazioni / max(1, grezze.passaggi):.1f} -> il test lavora su "
          f"circa un {grezze.osservazioni // max(1, grezze.passaggi)}-esimo dei dati")
    print(f"    terne scartate per fermata mancante: {grezze.con_buco:,}")
    for nome, maschera in popolazioni:
        print(f"    {nome:<20} {int(maschera.sum()):>12,} terne "
              f"({maschera.mean():>6.1%})")

    righe = []
    for nome, maschera in popolazioni:
        quante = int(maschera.sum())
        if quante < 10_000:
            print(f"\n    --- {nome}: {quante:,} terne, sotto la soglia: non si giudica ---")
            continue
        s2, s1, s0 = r2[maschera], r1[maschera], r0[maschera]
        print(f"\n    --- {nome}: {quante:,} terne ---")

        for etichetta, bordi in (("otto bin (principale)", BORDI_OTTO),
                                 ("quattro bin (controllo)", BORDI_QUATTRO)):
            esito = valuta(_terne_discrete(s2, s1, s0, bordi), generatore=generatore)
            righe.append(_riga(citta, nome, etichetta, esito))
            print(f"      {etichetta:<24} condizionata {esito.condizionata:.5f} | "
                  f"riferimento {esito.riferimento:.5f} | eccesso {esito.eccesso:.5f} | "
                  f"quota {esito.quota_sul_primo_antenato:.2%}")

        # Solo le granularita' che il campione sostiene: il numero di celle cresce
        # con il cubo dei bin, e una stima con meno di un'osservazione per cella
        # produrrebbe comunque un numero, indistinguibile dagli altri.
        sostenibili = granularita_sostenibili(quante, GRANULARITA)
        escluse = [k for k in GRANULARITA if k not in sostenibili]
        if escluse:
            print(f"      granularita' escluse per numerosita': {escluse} "
                  f"(servono 50 terne per cella, e le celle sono k al cubo)")
        if not sostenibili:
            print(f"      nessuna granularita' sostenibile: la scala non si calcola")
            continue
        scala = scala_per_granularita(s2, s1, s0, sostenibili, generatore=generatore)
        print(f"      scala per granularita' (quota sull'antenato immediato):")
        for quanti, esito in scala:
            righe.append(_riga(citta, nome, f"{quanti} bin equispaziati", esito))
            print(f"        {quanti:>3} bin: eccesso {esito.eccesso:>9.5f} | "
                  f"quota {esito.quota_sul_primo_antenato:>7.2%}")
        dissolve, spiegazione = verdetto_sulla_scala(scala)
        etichetta = {True: "SI DISSOLVE", False: "NON si dissolve",
                     None: "NON GIUDICABILE"}[dissolve]
        print(f"      VERDETTO: {etichetta}")
        print(f"        -> {spiegazione}")

    righe += costo_beneficio(citta, r2, r1, r0, giorno, popolazioni)
    righe += costo_beneficio_con_contesto(citta, r2, r1, r0, giorno, contesto, popolazioni)
    valori_ripetuti(citta, r2, r1, r0, popolazioni)
    confronta_ampiezze(citta, ampiezza, previsioni, passate, r2, r1, r0)
    return righe


def costo_beneficio(citta, r2, r1, r0, giorno, popolazioni) -> list[dict]:
    """Quanto vale l'arco fuori campione, contro l'ottuplicarsi delle celle.

    Dentro il campione un genitore in piu' migliora sempre, e di esattamente
    l'informazione condizionata misurata sopra: e' la stessa quantita' vista da un
    altro lato. La domanda che decide la struttura e' un'altra, cioe' se quel
    guadagno **sopravviva** al costo di stimare otto volte le celle, e si risponde
    solo fuori campione.

    La separazione e' **per giornata** e non casuale. Terne della stessa corsa
    nello stesso giorno sono legate fra loro, e dividerle a caso metterebbe in
    verifica osservazioni quasi identiche a quelle di addestramento: entrambi i
    modelli sembrerebbero migliori, e soprattutto quello con piu' parametri, che e'
    proprio quello da mettere alla prova.
    """
    print()
    print("    --- Costo-beneficio dell'arco, fuori campione ---")
    disponibili = sorted(set(giorno.tolist()))
    # Servono almeno due giorni di addestramento oltre ai tre di verifica: con
    # meno, la separazione lascerebbe un insieme vuoto e i due modelli verrebbero
    # confrontati su una stima costruita sul nulla.
    if len(disponibili) < 5:
        print(f"      solo {len(disponibili)} giornate disponibili: la separazione "
              f"temporale non e' eseguibile, e il confronto non si fa")
        return []
    ultimi = disponibili[-3:]
    addestramento = ~np.isin(giorno, ultimi)
    print(f"      separazione per giornata: {int(addestramento.sum()):,} terne di "
          f"addestramento, {int((~addestramento).sum()):,} di verifica "
          f"(ultimi {len(ultimi)} giorni)")
    righe = []
    for nome, maschera in popolazioni:
        if int(maschera.sum()) < 100_000:
            print(f"      {nome:<20} {int(maschera.sum()):>10,} terne: base insufficiente")
            continue
        for etichetta, bordi in (("otto bin", BORDI_OTTO),):
            n_bin = len(bordi) + 1
            try:
                c = confronta_strutture(
                    discretizza(r2[maschera], bordi), discretizza(r1[maschera], bordi),
                    discretizza(r0[maschera], bordi), addestramento[maschera], n_bin,
                )
            except Exception as errore:
                print(f"      {nome}: non calcolabile ({errore})")
                continue
            print(f"      {nome:<20} {etichetta}: perdita senza arco "
                  f"{c.perdita_senza:.4f} bit, con arco {c.perdita_con:.4f} bit")
            print(f"      {'':<20} guadagno {c.guadagno:+.4f} bit "
                  f"({c.guadagno_relativo:+.2%}), celle da {c.celle_senza} a {c.celle_con}")
            righe.append({
                "citta": citta, "popolazione": nome, "granularita": f"costo-beneficio {etichetta}",
                "terne": c.terne_addestramento + c.terne_verifica,
                "condizionata": float("nan"), "riferimento": float("nan"),
                "scarto_riferimento": float("nan"), "eccesso": c.guadagno,
                "mutua_semplice": c.perdita_senza, "quota": c.guadagno_relativo,
                "compatibile_con_zero": int(c.guadagno <= 0),
            })
    return righe


def costo_beneficio_con_contesto(citta, r2, r1, r0, giorno, contesto, popolazioni) -> list[dict]:
    """L'arco misurato **dentro il modello vero**, con linea, fascia e tipo di giorno.

    E' la misura che decide la struttura, e non coincide con quella senza
    contesto. Li' si confrontano 64 celle contro 512 su milioni di osservazioni,
    quindi entrambe stimate benissimo, e la domanda a cui si risponde e' "il
    secondo antenato porta informazione". Qui il ritardo e' condizionato anche al
    contesto, le celle passano da 403 mila a 3,2 milioni, e le osservazioni per
    cella da una ventina a due e mezzo su Roma. Un guadagno misurato in abbondanza
    di dati non si trasferisce a un regime di scarsita': il numero che autorizza
    l'arco e' questo, non quello.
    """
    print()
    print("    --- Costo-beneficio DENTRO il modello con contesto ---")
    disponibili = sorted(set(giorno.tolist()))
    if len(disponibili) < 5:
        print(f"      solo {len(disponibili)} giornate: separazione non eseguibile")
        return []
    addestramento = ~np.isin(giorno, disponibili[-3:])
    n_contesto = int(contesto.max()) + 1
    print(f"      combinazioni di contesto osservate: {n_contesto:,}")
    righe = []
    for nome, maschera in popolazioni:
        quante = int(maschera.sum())
        if quante < 100_000:
            print(f"      {nome:<20} {quante:>10,} terne: base insufficiente")
            continue
        bordi = BORDI_OTTO
        n_bin = len(bordi) + 1
        try:
            c = confronta_con_contesto(
                contesto[maschera], discretizza(r2[maschera], bordi),
                discretizza(r1[maschera], bordi), discretizza(r0[maschera], bordi),
                addestramento[maschera], n_bin, n_contesto,
            )
        except Exception as errore:
            print(f"      {nome}: non calcolabile ({errore})")
            continue
        print(f"      {nome:<20} perdita senza arco {c.perdita_senza:.4f} bit, "
              f"con arco {c.perdita_con:.4f} bit")
        print(f"      {'':<20} guadagno {c.guadagno:+.4f} bit ({c.guadagno_relativo:+.2%}), "
              f"celle da {c.celle_senza:,} a {c.celle_con:,}")
        print(f"      {'':<20} osservazioni per cella in addestramento: "
              f"{c.terne_addestramento / c.celle_con:.2f} con l'arco, "
              f"{c.terne_addestramento / c.celle_senza:.1f} senza")
        righe.append({
            "citta": citta, "popolazione": nome,
            "granularita": "costo-beneficio con contesto",
            "terne": c.terne_addestramento + c.terne_verifica,
            "condizionata": float("nan"), "riferimento": float("nan"),
            "scarto_riferimento": float("nan"), "eccesso": c.guadagno,
            "mutua_semplice": c.perdita_senza, "quota": c.guadagno_relativo,
            "compatibile_con_zero": int(c.guadagno <= 0),
        })
    print("      Se qui il guadagno sparisce, l'arco non si aggiunge: il modello vero")
    print("      non ha i dati per sostenerlo, per quanta informazione ci sia.")
    return righe


def valori_ripetuti(citta, r2, r1, r0, popolazioni) -> None:
    """Il ritardo si ripete identico fra fermate consecutive?

    Mette alla prova la spiegazione che invertirebbe la lettura del capovolgimento
    fra previsioni e constatazioni. Se il produttore, passato il mezzo,
    **congelasse** il ritardo ripetendolo sulle fermate seguenti, i valori
    consecutivi sarebbero uguali per costruzione: l'entropia condizionata
    risulterebbe bassa e la dipendenza forte, ma si tratterebbe di copie e non di
    osservazioni. Spiegherebbe insieme le due anomalie, cioe' la perdita di 0,34
    bit su Torino gia' passate e il guadagno maggiore proprio su quelle
    popolazioni.

    Il confronto e' sui secondi e non sui bin: due ritardi diversi che cadono nello
    stesso bin non sono una ripetizione, e contarli come tale nasconderebbe cio'
    che si cerca.
    """
    print()
    print("    --- Il ritardo si ripete identico fra fermate consecutive? ---")
    for nome, maschera in popolazioni:
        if int(maschera.sum()) < 1_000:
            print(f"      {nome:<20} base insufficiente")
            continue
        uno = quota_valori_ripetuti(r1[maschera], r0[maschera])
        due = quota_valori_ripetuti(r2[maschera], r1[maschera])
        tre = float(np.mean((r2[maschera] == r1[maschera]) & (r1[maschera] == r0[maschera])))
        print(f"      {nome:<20} identico alla precedente: {uno:>6.2%} | "
              f"due volte di fila: {tre:>6.2%}")
    print("      Una quota alta sulle gia' passate, e bassa sulle previsioni,")
    print("      spiegherebbe il capovolgimento come propagazione e non come traffico.")


def confronta_ampiezze(citta, ampiezza, previsioni, passate, r2, r1, r0) -> None:
    """Le due popolazioni differiscono per quanto sono ravvicinate le fermate?

    E' la spiegazione alternativa da escludere prima di attribuire alla natura del
    dato la maggiore dipendenza delle osservazioni gia' passate. Se in quella
    popolazione le tre fermate fossero piu' vicine nel tempo, la dipendenza
    maggiore sarebbe spiegata dalla vicinanza: fermate a un minuto l'una
    dall'altra condividono piu' informazione di fermate a dieci, e non perche' il
    dato sia di natura diversa.
    """
    print()
    print("    --- Ampiezza temporale della terna nelle due popolazioni ---")
    if not previsioni.any() or not passate.any():
        print("      una delle due popolazioni e' vuota: confronto non eseguibile")
        return
    for nome, maschera in (("solo previsioni", previsioni), ("solo gia' passate", passate)):
        a = ampiezza[maschera] / 60.0
        print(f"      {nome:<20} n={int(maschera.sum()):>10,} | mediana "
              f"{np.median(a):>6.1f} min | q1 {np.quantile(a, .25):>6.1f} | "
              f"q3 {np.quantile(a, .75):>6.1f}")

    # Il controllo decisivo: si confrontano le due popolazioni sulla stessa
    # ampiezza. Se la differenza sopravvive a parita' di distanza fra le fermate,
    # non e' la vicinanza a spiegarla.
    basso = max(np.quantile(ampiezza[previsioni], .25), np.quantile(ampiezza[passate], .25))
    alto = min(np.quantile(ampiezza[previsioni], .75), np.quantile(ampiezza[passate], .75))
    if not basso < alto:
        print("      le due distribuzioni non si sovrappongono abbastanza: "
              "confronto a parita' di ampiezza non eseguibile")
        return
    print(f"      A PARITA' DI AMPIEZZA, fra {basso/60:.1f} e {alto/60:.1f} minuti:")
    dentro = (ampiezza >= basso) & (ampiezza <= alto)
    for nome, maschera in (("solo previsioni", previsioni & dentro),
                           ("solo gia' passate", passate & dentro)):
        quante = int(maschera.sum())
        if quante < 10_000:
            print(f"        {nome:<20} {quante:>10,} terne: base insufficiente")
            continue
        esito = valuta(_terne_discrete(r2[maschera], r1[maschera], r0[maschera], BORDI_OTTO),
                       ripetizioni=8)
        print(f"        {nome:<20} {quante:>10,} terne | quota "
              f"{esito.quota_sul_primo_antenato:>6.2%}")
    print(f"      Se la differenza sopravvive qui, non e' la vicinanza a spiegarla.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", nargs="*", default=list(CITTA))
    parser.add_argument("--giorni", type=int, default=0,
                        help="quanti giorni usare (0 = tutti)")
    parser.add_argument("--seme", type=int, default=20260908)
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    RISULTATI.mkdir(exist_ok=True)
    generatore = np.random.default_rng(argomenti.seme)
    tutte: list[dict] = []

    print("=" * 78)
    print("PROPRIETA' MARKOVIANA DEL RITARDO LUNGO LA CORSA")
    print("Sola lettura dei parquet: nessun file viene modificato.")
    print("=" * 78)

    for citta in argomenti.citta:
        cartella = argomenti.radice / "data" / "processed" / "osservazioni" / citta
        giorni = sorted(cartella.glob("*.parquet"))
        if argomenti.giorni:
            giorni = giorni[-argomenti.giorni:]
        if not giorni:
            print(f"  [{citta}] nessun parquet in {cartella}")
            continue
        grezze = Grezze.vuote()
        for indice, percorso in enumerate(giorni):
            terne_di_un_giorno(percorso, grezze, indice)
            print(f"  [{citta}] {percorso.stem}: {grezze.passaggi:,} passaggi cumulati",
                  flush=True)
        tutte.extend(analizza(citta, grezze, generatore))
        del grezze

    if tutte:
        destinazione = RISULTATI / "markov_terne.csv"
        pd.DataFrame(tutte).to_csv(destinazione, index=False)
        print(f"\nscritto {destinazione} ({len(tutte)} righe)")
    print("\n" + "=" * 78)
    print("Il verdetto si legge sulla scala, non sul valore assoluto: la voce 60")
    print("del registro spiega perche' il riferimento per permutazione non basta.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
