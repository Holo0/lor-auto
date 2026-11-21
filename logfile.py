"""
Journal de lancement sur disque.

Jusqu'au 04/09/2026, les logs du bot n'allaient QUE dans la console : une
fois la fenêtre fermée, plus aucune trace de ce qui s'était passé — seuls
restaient `journal.jsonl` (une ligne par combat) et les captures. Chaque
lancement écrit désormais aussi `logs/<programme>_AAAAMMJJ_HHMMSS.log`,
même contenu que la console, pour pouvoir le relire après coup.
"""
import logging
import os
import time

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def setup(program: str, level=logging.INFO) -> str:
    """Console + fichier. Renvoie le chemin du fichier créé."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{program}_{time.strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        level=level,
        format=FORMAT,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(path, encoding="utf-8"),
        ],
    )
    logging.info("Journal de ce lancement : %s", path)
    return path
