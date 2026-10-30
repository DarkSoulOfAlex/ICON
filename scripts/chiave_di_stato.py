"""Quanto costa mettere l'istante nella chiave di uno stato.

Nel grafo tempo-espanso uno stato a terra si puo' identificare con
``(fermata, istante, cambi)`` oppure con ``(fermata, cambi)``. La prima
formulazione sembra la piu' naturale - due arrivi alla stessa fermata in momenti
diversi sono stati diversi - ed e' quella sbagliata: la ricerca procede in ordine
di orario di arrivo, quindi il primo arrivo a una fermata con un dato numero di
cambi domina tutti quelli successivi, e tenerli separati moltiplica gli stati senza
cambiare la risposta.

Perche' questo programma esiste, e perche' cosi' tardi. Il numero era stato
misurato una volta e riportato nel documento, ma non lo produceva nessuno script:
viveva nel log di una sessione. E' lo stesso difetto - un numero vero
quando fu scritto e non piu' verificabile - e qui costa un minuto rimediarlo,
perche' la macchina per farlo c'era gia': ``cerca_primo_arrivo`` accetta
``istante_nella_chiave``.

Si usano le prime coppie risolte del campione di Torino con il seme 20260826 e lo
stesso archivio delle altre fasi: la prima e' quella che il documento riportava
quando la misura era su una coppia sola, e resta in testa al CSV. Una coppia sola
non dice se il fattore cento sia la regola o un caso fortunato; dieci coppie danno
media e deviazione, e verificano su ciascuna che l'orario di arrivo coincida.

    python scripts/chiave_di_stato.py
    python scripts/chiave_di_stato.py --citta torino --archivio 2026-08-26 --coppie 10
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

RADICE = Path(__file__).resolve().parents[1]
for _percorso in (RADICE, RADICE / "scripts"):
    if str(_percorso) not in sys.path:
        sys.path.insert(0, str(_percorso))

import pandas as pd                                          # noqa: E402

from src.graph.search import cerca_primo_arrivo               # noqa: E402
from src.graph.time_expanded import costruisci                # noqa: E402
from src.eval.ambiente import marca_macchina  # noqa: E402
from src.gtfs.loader import carica_archivio                   # noqa: E402

FUSO = ZoneInfo("Europe/Rome")
ORA_PARTENZA = 8
ORIZZONTE = 120
SEME = 20260826
"""Il seme con cui il documento dichiara estratta la coppia: non si cambia."""

def velocita_massima(citta: str, risultati: Path) -> float:
    """La velocita' massima misurata sugli archi, da ``velocita_archi.csv``.

    E' quella che rende ammissibile l'euristica della Fase 2, ed e' la stessa
    con cui il resto di quel capitolo e' stato misurato. Al primo tentativo questo
    programma usava un limite lasco di 500 m/s, plausibile in astratto: dava
    1.512.712 stati contro i 1.464.312 del documento, cioe' un esperimento diverso
    invece di una verifica. Un parametro scelto per comodita' basta a rendere
    irriproducibile un numero che era giusto.
    """
    tavola = pd.read_csv(risultati / "velocita_archi.csv")
    riga = tavola[tavola["citta"] == citta]
    if riga.empty:
        raise SystemExit(f"nessuna velocita' misurata per {citta} in velocita_archi.csv")
    return float(riga["massimo_m_s"].iloc[0])


def archivio_scelto(citta: str, fino_a: str | None) -> Path:
    archivi = sorted((RADICE / "data" / "raw" / "gtfs" / citta).glob("*.zip"))
    if fino_a:
        archivi = [a for a in archivi if a.stem.split("_")[0] <= fino_a]
    if not archivi:
        raise SystemExit(f"nessun archivio GTFS per {citta} valido al {fino_a}")
    return archivi[-1]


COPPIE_PREDEFINITE = 10
"""Abbastanza per una deviazione, e la formulazione lenta costa circa un minuto l'una."""


def prime_coppie_risolte(grafo, inizio: int, velocita: float, servono: int,
                         quante: int = 200) -> list[tuple[str, str]]:
    """Le prime coppie del campione su cui esista un cammino, col seme dichiarato.

    Il campione e' lo stesso di prima, quindi la prima coppia restituita e' quella
    che il documento riportava: aggiungere coppie estende la misura senza
    sostituirla.
    """
    from ricerca_confronto import coppie_casuali

    risolte = []
    for origine, destinazione in coppie_casuali(grafo, quante, SEME):
        if cerca_primo_arrivo(grafo, origine, destinazione, inizio, velocita).trovato:
            risolte.append((origine, destinazione))
            if len(risolte) == servono:
                return risolte
    if not risolte:
        raise SystemExit("nessuna coppia risolta nel campione")
    return risolte


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", default="torino")
    parser.add_argument("--archivio", default="2026-08-26", metavar="AAAA-MM-GG")
    parser.add_argument("--origine", default=None)
    parser.add_argument("--destinazione", default=None)
    parser.add_argument("--coppie", type=int, default=COPPIE_PREDEFINITE)
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    percorso = archivio_scelto(argomenti.citta, argomenti.archivio)
    archivio = carica_archivio(percorso, con_stop_times=True)
    giorno = date.fromisoformat(percorso.stem.split("_")[0])
    inizio = int(datetime(giorno.year, giorno.month, giorno.day, ORA_PARTENZA, 0,
                          tzinfo=FUSO).timestamp())
    grafo = costruisci(archivio, argomenti.citta, giorno, inizio, ORIZZONTE)
    velocita = velocita_massima(argomenti.citta, argomenti.radice / "results")
    print(f"=== {argomenti.citta} ({percorso.name}), partenza {ORA_PARTENZA}:00, "
          f"orizzonte {ORIZZONTE} min, V {velocita:.2f} m/s ===", flush=True)

    if argomenti.origine and argomenti.destinazione:
        coppie = [(argomenti.origine, argomenti.destinazione)]
    else:
        coppie = prime_coppie_risolte(grafo, inizio, velocita, argomenti.coppie)

    righe = []
    for numero, (origine, destinazione) in enumerate(coppie, start=1):
        print(f"  coppia {numero}: {origine} -> {destinazione} (seme {SEME})", flush=True)
        for etichetta, con_istante in (("(fermata, istante, cambi)", True),
                                       ("(fermata, cambi)", False)):
            esito = cerca_primo_arrivo(grafo, origine, destinazione, inizio, velocita,
                                       istante_nella_chiave=con_istante)
            righe.append({
                "citta": argomenti.citta, "archivio": percorso.name,
                "seme": SEME, "velocita_m_s": round(velocita, 4),
                "coppia": numero, "origine": origine, "destinazione": destinazione,
                "chiave": etichetta, "istante_nella_chiave": con_istante,
                "stati_espansi": esito.stati_espansi,
                "stati_generati": esito.stati_generati,
                "secondi": round(esito.tempo_secondi, 2),
                "orario_arrivo": esito.orario_arrivo,
                "cambi": esito.cambi,
                "trovato": esito.trovato,
            })
            print(f"    {etichetta:<28} {esito.stati_espansi:>10,} stati  "
                  f"{esito.tempo_secondi:>7.2f} s  arrivo {esito.orario_arrivo}", flush=True)

    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    destinazione_csv = risultati / "chiave_di_stato.csv"
    tavola = pd.DataFrame(righe)
    marca_macchina(tavola).to_csv(destinazione_csv, index=False)
    print(f"\nscritto {destinazione_csv} ({len(righe)} righe)")
    _riassumi(tavola)
    return 0


def _riassumi(tavola: pd.DataFrame) -> None:
    """Rapporti per coppia fra le due formulazioni, e se l'arrivo coincide sempre.

    Il rapporto si calcola coppia per coppia e poi si media: mediare prima gli
    stati e poi dividere darebbe un peso sproporzionato alle coppie piu' costose.
    """
    larga = tavola.pivot(index="coppia", columns="istante_nella_chiave",
                         values=["stati_espansi", "secondi", "orario_arrivo"])
    sugli_stati = larga["stati_espansi"][True] / larga["stati_espansi"][False].clip(lower=1)
    sul_tempo = larga["secondi"][True] / larga["secondi"][False].clip(lower=0.01)
    stesso_arrivo = (larga["orario_arrivo"][True] == larga["orario_arrivo"][False]).all()
    print(f"  {len(larga)} coppie | rapporto sugli stati {sugli_stati.mean():.0f} +/- "
          f"{sugli_stati.std():.0f}, sul tempo {sul_tempo.mean():.0f} +/- {sul_tempo.std():.0f} | "
          f"stesso arrivo su tutte: {stesso_arrivo}")


if __name__ == "__main__":
    raise SystemExit(main())
