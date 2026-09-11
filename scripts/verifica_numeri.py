"""Ogni numero del documento esiste in un CSV dei risultati?

Il difetto che questo programma esiste per intercettare non e' ipotetico: nel
resoconto della Fase 5 due numeri - il 3,4% di viaggi incompleti e il 35,9% di
divergenza - venivano da una corsa pilota il cui CSV era stato cancellato, e
nessuno se ne sarebbe accorto. Erano scritti a memoria invece che riletti dal
file, ed e' l'unico modo di sbagliare che conti davvero quando si scrive il
documento: un numero inventato non fa fallire nulla, non rompe nessun test, e
resta li'.

**Non e' un verificatore, e' un setaccio.** Riconosce come "risultato" qualunque
numero con la virgola decimale, qualunque percentuale e qualunque grandezza
seguita da un'unita' - bit, secondi, minuti - e per ciascuno cerca una cella dei
CSV che vi corrisponda **alla precisione con cui e' scritto**: 0,213 si confronta
al millesimo, 45% al punto percentuale. I falsi positivi sono previsti e
innocui - un anno, il numero di un capitolo, un conteggio - e si guardano a
occhio. Cio' che non deve poter accadere e' il contrario: che un numero senza
origine passi inosservato.

**Come tratta le percentuali.** Un CSV che scrive 0,4664 e un documento che scrive
46,6% dicono la stessa cosa: ogni percentuale viene quindi cercata sia come
scritta sia divisa per cento. Lo stesso per i numeri con segno, dove il documento
scrive +11,1% e la cella contiene una differenza che il CSV non ha mai
materializzato: per questo si cercano anche le **differenze fra celle** della
stessa colonna, che sono il modo in cui quasi tutti i confronti vengono riportati.

    python scripts/verifica_numeri.py
    python scripts/verifica_numeri.py --documento docs/documentazione.md --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import numpy as np                                          # noqa: E402
import pandas as pd                                         # noqa: E402

NUMERO = re.compile(
    r"(?<![\w.,])"                 # non in mezzo a una parola o a un numero piu' lungo
    r"([+-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?|[+-]?\d+(?:[.,]\d+)?)"
    r"\s*(%|bit|s\b|secondi|minuti|min\b)?"
)
"""Un numero, con l'unita' se ce l'ha. Accetta sia la virgola sia il punto decimale.

Il separatore delle migliaia italiano (`172.380.759`) e il punto decimale inglese
(`0.9437`) sono ambigui fra loro, e il documento usa entrambe le convenzioni in
punti diversi. Si prova quindi l'interpretazione italiana e, se fallisce, quella
inglese: e' un setaccio, e un numero interpretato in due modi si cerca in due modi.
"""

# Numeri che non sono risultati e che intaserebbero l'elenco senza informare.
DA_IGNORARE = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 100.0}
ANNI = range(2020, 2036)


@dataclass(frozen=True)
class Occorrenza:
    """Un numero trovato nel documento, con dove sta."""

    testo: str
    valori: tuple[tuple[float, int], ...]
    """Le letture possibili, ciascuna col proprio numero di cifre decimali."""
    unita: str
    riga: int
    contesto: str

    @property
    def valore(self) -> float:
        return self.valori[0][0]


AMBIGUO = re.compile(r"\d{1,3}\.\d{3}")
"""Un punto seguito da esattamente tre cifre: migliaia all'italiana o decimali."""


def _interpreta(testo: str) -> list[tuple[float, int]]:
    """I valori che il numero puo' avere, perche' il documento usa due convenzioni.

    ``7.334`` in un testo italiano vale settemila; ``0.9437`` copiato da un CSV vale
    zero virgola. Un punto seguito da esattamente tre cifre resta ambiguo: si
    restituiscono **entrambe** le letture e si cerca l'una e l'altra. Sceglierne una
    sola darebbe NON TROVATO a meta' delle tabelle del documento, e un setaccio che
    segnala tutto non segnala niente.
    """
    grezzo = testo.strip()
    segno = -1.0 if grezzo.startswith("-") else 1.0
    ripulito = grezzo.lstrip("+-")
    letture: list[str] = []
    if "," in ripulito:                      # 1.234,5 oppure 0,213: virgola decimale
        letture.append(ripulito.replace(".", "").replace(",", "."))
    elif ripulito.count(".") > 1:            # 172.380.759: solo migliaia
        letture.append(ripulito.replace(".", ""))
    elif AMBIGUO.fullmatch(ripulito):        # 7.334: le due letture convivono
        letture.append(ripulito.replace(".", ""))
        letture.append(ripulito)
    else:                                    # 0.9437 oppure 45
        letture.append(ripulito)
    # Le cifre decimali si contano **su ciascuna lettura**, non sul testo: letto
    # come migliaia, ``37.156`` non ha decimali e va cercato a mezza unita'; letto
    # come decimale ne ha tre e va cercato al mezzo millesimo. Contarle una volta
    # sola sul testo dava al primo la tolleranza del secondo, e faceva mancare la
    # media 37.156,23 per due decimi: era il difetto che segnalava come inventata
    # meta' della tabella di Argomento 2.
    valori: list[tuple[float, int]] = []
    for lettura in letture:
        try:
            valore = segno * float(lettura)
        except ValueError:
            continue
        pezzi = lettura.split(".")
        valori.append((valore, len(pezzi[1]) if len(pezzi) == 2 else 0))
    return valori


def estrai(documento: Path) -> list[Occorrenza]:
    """Tutti i numeri che sembrano un risultato, con la riga in cui stanno."""
    trovate: list[Occorrenza] = []
    for numero_riga, riga in enumerate(documento.read_text(encoding="utf-8").splitlines(), 1):
        # Le righe di codice e i riferimenti bibliografici pullulano di numeri che
        # non sono risultati: si saltano invece di riempire l'elenco di rumore.
        nuda = riga.strip()
        if nuda.startswith(("```", "    ", "#", ">")) or nuda.startswith("["):
            continue
        for grezzo, unita in NUMERO.findall(riga):
            valori = _interpreta(grezzo)
            if not valori or abs(valori[0][0]) in DA_IGNORARE:
                continue
            if not unita and all(v.is_integer() and int(v) in ANNI for v, _ in valori):
                continue
            # Il contesto finisce a schermo, e una console latina non sa scrivere
            # ogni carattere che un documento puo' contenere: si riduce ad ASCII
            # qui, dove il danno e' cosmetico, invece di far abortire il setaccio
            # sull ultima riga dopo mille numeri gia' controllati.
            leggibile = nuda.encode("ascii", "replace").decode("ascii")
            trovate.append(Occorrenza(grezzo, tuple(valori), unita or "",
                                      numero_riga, leggibile[:90]))
    return trovate


MASSIMI_GRUPPI = 16
"""Quante categorie al piu' puo' avere una colonna perche' valga la pena raggrupparvi.

Oltre, non e' una categoria ma un identificativo - un ``trip_id``, una coppia
numerata - e raggrupparvi produrrebbe centinaia di migliaia di medie su un
elemento ciascuna, che coinciderebbero coi valori gia' presenti.
"""


def _aggregati(nome: str, tavola: pd.DataFrame) -> list[tuple[str, str, float]]:
    """Medie e deviazioni per gruppo: e' cosi' che una tabella di risultati si scrive.

    La prima versione del setaccio cercava solo celle e differenze fra celle, e
    segnalava come NON TROVATI un centinaio di numeri **corretti**: i valori di
    Argomento 2, per esempio, sono le medie di ``ricerca_astar.csv`` calcolate sulle
    sole coppie risolte, quarantatre su cinquanta a Roma. Nessuno di quei numeri
    compare in una cella, e tutti si ricostruiscono in una riga.

    Un setaccio che segnala cento numeri buoni per trovarne uno cattivo non viene
    guardato, e allora non serve. Si generano quindi anche gli aggregati: per ogni
    raggruppamento su una o due colonne categoriche, la media e la deviazione di
    ogni colonna numerica, sia su tutte le righe sia sulle sole righe in cui una
    colonna booleana e' vera - che e' il filtro con cui quasi tutti i risultati di
    questo progetto sono condizionati.
    """
    numeriche = list(tavola.select_dtypes("number").columns)
    if not numeriche or tavola.empty:
        return []
    categoriche = [c for c in tavola.columns
                   if c not in numeriche and 1 < tavola[c].nunique() <= MASSIMI_GRUPPI]
    booleane = [c for c in tavola.columns if tavola[c].dtype == bool]

    viste: list[tuple[str, pd.DataFrame]] = [("", tavola)]
    for colonna in booleane:
        sotto = tavola[tavola[colonna]]
        if not sotto.empty and len(sotto) < len(tavola):
            viste.append((f" [{colonna}]", sotto))

    fuori: list[tuple[str, str, float]] = []
    for suffisso, vista in viste:
        for chiavi in _raggruppamenti(categoriche):
            try:
                gruppi = (vista.groupby(list(chiavi))[numeriche] if chiavi
                          else vista[numeriche])
                media = gruppi.mean()
                deviazione = gruppi.std(ddof=1)
            except Exception:                                # noqa: BLE001
                continue
            etichetta = "+".join(chiavi) if chiavi else "tutte le righe"
            for statistica, valori in (("media", media), ("deviazione", deviazione)):
                blocco = np.asarray(valori, dtype="float64").ravel()
                for v in blocco[np.isfinite(blocco)]:
                    fuori.append((nome, f"{statistica} per {etichetta}{suffisso}",
                                  float(v)))
    return fuori


def _raggruppamenti(categoriche: Sequence[str]) -> list[tuple[str, ...]]:
    """Nessun raggruppamento, poi uno per colonna, poi le coppie di colonne."""
    combinazioni: list[tuple[str, ...]] = [()]
    combinazioni.extend((c,) for c in categoriche)
    for i, a in enumerate(categoriche):
        for b in categoriche[i + 1:]:
            combinazioni.append((a, b))
    return combinazioni


RIGHE_DI_RIEPILOGO = 100
"""Oltre quante righe un CSV e' materia prima e non una tabella da citare.

Il documento cita riepiloghi: medie per citta', per margine, per strategia. I
file di dettaglio - una riga per istanza - contengono migliaia di valori in
[0, 1] e **saturano la retta dei numeri**: cercandovi dentro, qualunque
percentuale inventata trova una corrispondenza. Misurato: col dettaglio incluso
il 99,5% delle percentuali inventate a un decimale risulta "trovato", contro il
61% coi soli riepiloghi. Si cercano quindi per difetto i soli riepiloghi, e
``--con-dettaglio`` include il resto per chi sappia cosa sta facendo.
"""


def tasso_di_falso(celle: Sequence[tuple[str, str, float]], quanti: int = 400,
                   seme: int = 20260911) -> dict[str, float]:
    """Quanto spesso un numero **inventato** trova una corrispondenza.

    E' la misura che dice quanto valga un "trovato", e senza di essa il programma
    ingannerebbe chi lo usa. Un corpus di qualche migliaio di valori copre densamente
    l'intervallo [0, 1]: una percentuale scritta a un decimale ha appena mille valori
    possibili, e la collisione e' quasi certa. Un numero a quattro decimali ne ha
    diecimila volte tanti, e la collisione diventa rara.

    Se ne ricava una regola per chi scrive: **un risultato va riportato con le cifre
    che ha nel CSV**. Scritto come "il 46,6%" non e' verificabile da nessuno; scritto
    come "0,4664" lo e'.
    """
    generatore = np.random.default_rng(seme)
    prove = (
        ("percentuale a un decimale",
         lambda: (f"{generatore.uniform(0, 100):.1f}".replace(".", ","), "%")),
        ("numero a quattro decimali",
         lambda: (f"{generatore.uniform(0, 1):.4f}".replace(".", ","), "")),
        ("intero a cinque cifre",
         lambda: (f"{generatore.integers(10_000, 99_999)}", "")),
    )
    esiti: dict[str, float] = {}
    for etichetta, genera in prove:
        colpi = 0
        for _ in range(quanti):
            testo, unita = genera()
            finta = Occorrenza(testo, tuple(_interpreta(testo)), unita, 0, "")
            if cerca(finta, celle) is not None:
                colpi += 1
        esiti[etichetta] = colpi / quanti
    return esiti


def carica_celle(cartella: Path, con_dettaglio: bool = False,
                 con_differenze: bool = False) -> list[tuple[str, str, float]]:
    """Ogni cella numerica di ogni CSV, come (file, colonna, valore).

    Si tengono anche le **differenze** fra celle della stessa colonna dello stesso
    file: quasi tutti i confronti del documento sono differenze che il CSV non ha
    mai materializzato, e cercarle solo come valori assoluti darebbe NON TROVATO a
    numeri perfettamente sostenuti.
    """
    celle: list[tuple[str, str, float]] = []
    for percorso in sorted(cartella.glob("*.csv")):
        try:
            tavola = pd.read_csv(percorso)
        except Exception:                                    # noqa: BLE001
            continue
        if len(tavola) > RIGHE_DI_RIEPILOGO and not con_dettaglio:
            continue
        celle.extend(_aggregati(percorso.name, tavola))
        for colonna in tavola.select_dtypes("number").columns:
            valori = tavola[colonna].to_numpy(dtype="float64", na_value=np.nan)
            valori = valori[np.isfinite(valori)]
            for v in valori:
                celle.append((percorso.name, colonna, float(v)))
            # Le differenze a coppie esplodono col quadrato e riempiono la retta:
            # da sole portano il tasso di falso sulle percentuali dal 61% all'89%.
            # Una differenza si controlla a occhio dai due termini, che il documento
            # riporta quasi sempre; restano quindi facoltative.
            if con_differenze and 1 < valori.size <= 60:
                for i in range(valori.size):
                    for j in range(valori.size):
                        if i != j:
                            celle.append((percorso.name, f"{colonna} (differenza)",
                                          float(valori[i] - valori[j])))
    return celle


def cerca(occorrenza: Occorrenza,
          celle: Sequence[tuple[str, str, float]]) -> tuple[str, str] | None:
    """La prima cella che corrisponde al numero, alla precisione con cui e' scritto."""
    bersagli: list[tuple[float, float]] = []
    for v, decimali in occorrenza.valori:
        tolleranza = 0.5 * 10 ** (-decimali)
        bersagli.append((v, tolleranza))
        if occorrenza.unita == "%":
            # 46,6% nel documento e 0,4664 nella cella sono lo stesso numero: la
            # tolleranza si divide insieme al valore, altrimenti il confronto
            # diventerebbe cento volte piu' largo di quanto e' scritto.
            bersagli.append((v / 100.0, tolleranza / 100.0))
        if occorrenza.unita in ("minuti", "min"):
            bersagli.append((v * 60.0, tolleranza * 60.0))
    for file, colonna, valore in celle:
        for bersaglio, scala in bersagli:
            if abs(valore - bersaglio) <= scala:
                return file, colonna
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documento", type=Path,
                        default=RADICE / "docs" / "documentazione.md")
    parser.add_argument("--risultati", type=Path, default=RADICE / "results")
    parser.add_argument("--con-differenze", action="store_true",
                        help="cerca anche le differenze fra celle: le trova, ma "
                             "porta il tasso di falso sulle percentuali dal 61 all 89 per cento")
    parser.add_argument("--con-dettaglio", action="store_true",
                        help="cerca anche nei CSV di dettaglio: aumenta le "
                             "corrispondenze e le rende quasi tutte spurie")
    parser.add_argument("--verbose", action="store_true",
                        help="elenca anche i numeri trovati, con la cella che li ha "
                             "raccolti: e' li' che si vede se la corrispondenza e' seria")
    argomenti = parser.parse_args(argv)

    if not argomenti.documento.is_file():
        print(f"documento assente: {argomenti.documento}")
        return 1
    celle = carica_celle(argomenti.risultati, argomenti.con_dettaglio,
                         argomenti.con_differenze)
    occorrenze = estrai(argomenti.documento)
    print("=" * 78)
    print("OGNI NUMERO DEL DOCUMENTO ESISTE IN UN CSV?")
    print("=" * 78)
    print(f"  documento: {argomenti.documento.name}, {len(occorrenze)} numeri estratti")
    print(f"  risultati: {len(list(argomenti.risultati.glob('*.csv')))} CSV, "
          f"{len(celle):,} valori (celle, aggregati e differenze)"
          f"{'' if argomenti.con_dettaglio else ', solo riepiloghi'}")
    falsi = tasso_di_falso(celle)
    print()
    print("  QUANTO VALE UN \"TROVATO\": corrispondenze su numeri INVENTATI")
    for etichetta, quota in falsi.items():
        giudizio = ("inutilizzabile" if quota > 0.5 else
                    "debole" if quota > 0.15 else "utile")
        print(f"    {etichetta:<28} {quota:>6.1%}   {giudizio}")
    print("  Un numero riportato con poche cifre non e' verificabile da nessuno:")
    print("  scritto 46,6% collide quasi sempre, scritto 0,4664 quasi mai. Chi scrive")
    print("  il documento ne ricavi la regola - le cifre del CSV, non quelle comode.")
    print()

    mancanti: list[Occorrenza] = []
    trovati = 0
    for occorrenza in occorrenze:
        esito = cerca(occorrenza, celle)
        if esito is None:
            mancanti.append(occorrenza)
        else:
            trovati += 1
            if argomenti.verbose:
                print(f"  riga {occorrenza.riga:>5}  {occorrenza.testo + occorrenza.unita:>14}"
                      f"  ->  {esito[0]} / {esito[1]}")
    if mancanti:
        print(f"  {'riga':>6}  {'numero':>14}   contesto")
        for o in mancanti:
            print(f"  {o.riga:>6}  {o.testo + o.unita:>14}   NON TROVATO   {o.contesto}")
    print()
    print(f"  trovati {trovati} | NON TROVATI {len(mancanti)} su {len(occorrenze)}")
    print()
    print("A COSA SERVE, e a cosa no. La difesa principale del documento non e' questo")
    print("programma ma la riga di fonte sotto ogni tabella, che dice da quale CSV e con")
    print("quale aggregazione il numero viene (voce 71): quella rende il numero rifacibile")
    print("e obbliga chi scrive a riaprire il file invece di citare a memoria.")
    print()
    print("Qui si pescano i numeri in PROSA, che nessuna riga di fonte copre, e quelli che")
    print("NESSUN CSV sostiene - e' cosi' che si sono scoperti i numeri della rete ASP a")
    print("piena scala, esistenti solo nel log di una esecuzione. I falsi positivi sono")
    print("previsti: anni, numeri di pagina, conteggi. Un \"trovato\" non e' una verifica,")
    print("e il tasso di falso qui sopra dice di quanto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
