"""I numeri delle catene a risposta nota, su file invece che dentro un test.

Il capitolo sull'apprendimento poggia su un punto di metodo che vale piu' della
scelta che ne discende: condizionare sul bin non e' condizionare sulla variabile,
e l'eccesso di informazione che ne risulta si riconosce dal **verso con cui varia al
raffinarsi della discretizzazione**. Quel punto e' dimostrato su due catene costruite
a tavolino, di cui si conosce la risposta:

- una markoviana esatta nel continuo, dove ``R0`` dipende da ``R-1`` e da nulla
  altro, e dove quindi l'eccesso misurato dopo la discretizzazione e' interamente
  artefatto: deve dissolversi al crescere dei bin;
- una in cui ``R0`` dipende anche da ``R-2``, dove l'eccesso e' struttura e non
  deve dissolversi.

I numeri stavano finora soltanto dentro ``tests/test_markov.py``, che li vincola con
delle soglie ma non li scrive da nessuna parte: chi legge il documento trovava
0,01174 bit e non aveva modo di rifarlo. E' lo stesso difetto applicato al
passaggio piu' importante del capitolo, e questo script lo chiude scrivendo
``results/catena_costruita.csv``.

Perche' non lo fa il test. Un test dichiara un comportamento e fallisce quando
cambia; non e' il posto dove produrre un artefatto da consegnare, perche' nessuno lo
esegue per leggerne l'uscita e la suite non deve scrivere dentro ``results/``. Le
catene stanno pero' in ``src.delays.markov`` e sono le stesse che il test usa, con
lo stesso seme: se divergessero, il test se ne accorgerebbe.

    python scripts/catena_costruita.py
    python scripts/catena_costruita.py --terne 500000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

RADICE = Path(__file__).resolve().parents[1]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.delays.markov import (  # noqa: E402
    BORDI_OTTO,
    SEME_CATENA,
    Terne,
    catena_con_dipendenza_vera,
    catena_markoviana,
    discretizza,
    eccesso_si_dissolve,
    scala_per_granularita,
    valuta,
)

RISULTATI = RADICE / "results"

SEME_PERMUTAZIONE = 29
"""Il seme del riferimento per permutazione alla granularita' principale."""

SEME_SCALA = 31
"""Il seme della scala per granularita'. Diverso dal precedente di proposito: due
misure indipendenti non devono condividere il rimescolamento, altrimenti un caso
fortunato le migliorerebbe entrambe insieme."""

SEME_SCALA_VERA = 41
"""Lo stesso, sulla catena a dipendenza vera."""

CATENE = (
    ("markoviana per costruzione", catena_markoviana, SEME_SCALA,
     "R0 = R-1 + rumore: l'eccesso misurato e' tutto artefatto della "
     "discretizzazione e deve dissolversi"),
    ("dipendenza vera da R-2", catena_con_dipendenza_vera, SEME_SCALA_VERA,
     "R0 = (R-1 + R-2)/2 + rumore: l'eccesso e' struttura e non deve dissolversi"),
)


def misura(nome: str, costruisci, seme_scala: int, attesa: str,
           n: int) -> list[dict]:
    """Le due letture su una catena: la granularita' principale e la scala."""
    grezzo2, grezzo1, grezzo0 = costruisci(n)
    righe: list[dict] = []

    terne = Terne(discretizza(grezzo2, BORDI_OTTO), discretizza(grezzo1, BORDI_OTTO),
                  discretizza(grezzo0, BORDI_OTTO), np.ones(n, dtype=bool))
    esito = valuta(terne, generatore=np.random.default_rng(SEME_PERMUTAZIONE))
    # Quante volte l'eccesso supera l'incertezza del proprio riferimento: e' il
    # numero che dice se il riferimento per permutazione, da solo, basterebbe a
    # dichiarare markoviano un processo markoviano. Non basta.
    volte = (esito.eccesso / esito.scarto_riferimento
             if esito.scarto_riferimento > 0 else float("nan"))
    print(f"\n  === {nome} ({n:,} terne) ===")
    print(f"  attesa: {attesa}")
    print(f"  otto bin del progetto: condizionata {esito.condizionata:.5f} | "
          f"riferimento {esito.riferimento:.5f} +/- {esito.scarto_riferimento:.5f} | "
          f"eccesso {esito.eccesso:.5f} ({volte:.0f} volte lo scarto)")
    righe.append({
        "catena": nome, "granularita": "otto bin del progetto", "terne": n,
        "seme_catena": SEME_CATENA if nome.startswith("markoviana") else 37,
        "seme_permutazione": SEME_PERMUTAZIONE,
        "condizionata": esito.condizionata, "riferimento": esito.riferimento,
        "scarto_riferimento": esito.scarto_riferimento, "eccesso": esito.eccesso,
        "eccesso_su_scarto": volte,
        "quota_sul_primo_antenato": esito.quota_sul_primo_antenato,
        "compatibile_con_zero": int(esito.compatibile_con_zero),
    })

    scala = scala_per_granularita(grezzo2, grezzo1, grezzo0,
                                  generatore=np.random.default_rng(seme_scala))
    print("  scala per granularita' (quota su cio' che il primo antenato spiega):")
    for quanti, e in scala:
        print(f"    {quanti:>3} bin: eccesso {e.eccesso:>9.5f} | "
              f"quota {e.quota_sul_primo_antenato:>7.2%}")
        righe.append({
            "catena": nome, "granularita": f"{quanti} bin equispaziati", "terne": n,
            "seme_catena": SEME_CATENA if nome.startswith("markoviana") else 37,
            "seme_permutazione": seme_scala,
            "condizionata": e.condizionata, "riferimento": e.riferimento,
            "scarto_riferimento": e.scarto_riferimento, "eccesso": e.eccesso,
            "eccesso_su_scarto": (e.eccesso / e.scarto_riferimento
                                  if e.scarto_riferimento > 0 else float("nan")),
            "quota_sul_primo_antenato": e.quota_sul_primo_antenato,
            "compatibile_con_zero": int(e.compatibile_con_zero),
        })
    dissolve = eccesso_si_dissolve(scala)
    etichetta = {True: "SI DISSOLVE", False: "NON si dissolve",
                 None: "NON GIUDICABILE"}[dissolve]
    print(f"  VERDETTO: {etichetta}")
    for r in righe:
        r["verdetto_sulla_scala"] = etichetta
    return righe


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terne", type=int, default=200_000,
                        help="quante terne per catena (le stesse dei test)")
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    print("=" * 78)
    print("LE CATENE A RISPOSTA NOTA")
    print("Nessun dato raccolto sul campo: qui la verita' e' costruita, ed e' l'unico")
    print("modo di sapere se il criterio distingua i casi che deve distinguere.")
    print("=" * 78)

    righe: list[dict] = []
    for nome, costruisci, seme, attesa in CATENE:
        righe += misura(nome, costruisci, seme, attesa, argomenti.terne)

    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    destinazione = risultati / "catena_costruita.csv"
    pd.DataFrame(righe).to_csv(destinazione, index=False)
    print(f"\nscritto {destinazione} ({len(righe)} righe)")
    print()
    print("Se un giorno la prima catena smettesse di dissolversi, o la seconda")
    print("cominciasse a farlo, il criterio della scala non varrebbe piu' e la")
    print("decisione sull'arco andrebbe rifatta da capo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
