"""Su quale macchina e' stato misurato un tempo.

Un tempo di esecuzione senza l'hardware su cui e' stato preso non significa nulla,
ed e' il motivo per cui i tempi riportati nel documento non erano difendibili:
venivano da due macchine diverse - il grounding della base di conoscenza da una,
i tempi della ricerca A* da un'altra - e il testo li confrontava fra loro come se
fossero omogenei. Nessuno poteva accorgersene, perche' nessun CSV lo diceva.

La riga che il documento riporta una volta sola non basta da sola: dipende dal
fatto che qualcuno la legga e la colleghi alla tabella giusta. La colonna nel CSV
viaggia invece insieme al numero, e sopravvive al copia-incolla di una riga in
un'altra tabella.

Si tiene volutamente corta: modello del processore, sistema e versione di Python.
Non e' un profilo dell'hardware, e' un'etichetta che permette di dire "questi due
tempi vengono dalla stessa macchina" oppure "non lo sappiamo".
"""

from __future__ import annotations

import platform
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def etichetta_macchina() -> str:
    """Una stringa breve e stabile che identifica dove si sta misurando.

    In cache perche' non cambia durante un'esecuzione e perche' finisce in ogni
    riga di ogni CSV: ricalcolarla migliaia di volte sarebbe sprecato, e usarla
    come costante di modulo la fisserebbe al momento dell'importazione, che e' lo
    stesso ma meno esplicito.
    """
    processore = platform.processor() or platform.machine() or "processore ignoto"
    # Il modello Intel/AMD viene prima della famiglia e basta a distinguere due
    # macchine; il resto della stringa e' rumore identico su tutti i PC simili.
    corto = processore.split(",")[0].strip()
    return (f"{corto} | {platform.system()} {platform.release()} "
            f"| Python {sys.version.split()[0]}")


def marca_macchina(tavola, colonna: str = "macchina"):
    """Aggiunge in coda la colonna con l'etichetta della macchina corrente."""
    if tavola is None or getattr(tavola, "empty", True):
        return tavola
    tavola = tavola.copy()
    tavola[colonna] = etichetta_macchina()
    return tavola
