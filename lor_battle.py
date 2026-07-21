import time
import random
from pathlib import Path
import subprocess
import sys
import logging
from click_utils import (click_button, human_click)


def _handle_post_combat():
  """
  Gère l'écran de fin de combat : détection de 'after_combat' puis clic
  sur 'continue_button' après un court délai. Retourne True si les deux
  écrans ont été détectés et cliqués avec succès.
  """
  if not click_button("after_combat", timeout=20):
    logging.warning("Image 'after_combat' non détectée après la fin du combat.")
    return False

  logging.info("Écran post-combat détecté et cliqué.")
  time.sleep(3)

  if not click_button("continue_button", timeout=5):
    logging.warning("Deuxième image 'continue_button' non détectée après le délai.")
    return False

  logging.info("Deuxième clic post-combat effectué après 3 secondes.")
  return True


def try_combat(node_x, node_y):
  """Try to play combat using the original LoR bot combat loop, en gérant
  les éventuels réessais ('retry') jusqu'à validation du combat."""

  result = play_combat()

  if not _handle_post_combat():
    return result

  while click_button("retry", timeout=5):
    logging.info("Bouton 'Réessayer' cliqué.")
    time.sleep(3)
    human_click(node_x, node_y)
    time.sleep(random.uniform(1.5, 2.5))

    if not click_button("combat_button"):
      continue

    logging.info("Bouton Combat cliqué. Début du combat.")
    result = play_combat()
    _handle_post_combat()

  logging.info("Aucun nouveau 'Réessayer' détecté, fin de la boucle de combat.")
  return result

def play_combat():
  """Launch the original LoR bot combat loop from LoR-Bot/code/LOR_Bot.py."""
  project_root = Path(__file__).resolve().parent
  script_path = project_root / "LoR-Bot" / "code" / "LOR_Bot.py"

  if not script_path.exists():
    raise FileNotFoundError(f"Combat script not found: {script_path}")

  # Run from the script directory so local imports in LOR_Bot.py keep working.
  completed = subprocess.run(
    [sys.executable, str(script_path)],
    cwd=str(script_path.parent),
    check=False,
  )

  if completed.returncode != 0:
    raise RuntimeError(f"Combat script exited with code {completed.returncode}")

  return "Combat finished"