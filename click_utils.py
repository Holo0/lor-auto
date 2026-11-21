import math
import os
import random
import time
import logging
import pyautogui

from adventure_navigation import (
    find_template_on_screen,
    find_all_matches_on_screen,
    TEMPLATES,
    MATCH_THRESHOLD,
)

# ============================================================
# VITESSE DES GESTES
# ============================================================
# pyautogui dort `PAUSE` secondes après CHAQUE appel public, et vaut 0.1 s
# par défaut. `human_move_mouse` trace une courbe en dizaines de `moveTo` :
# la pause invisible dominait donc complètement la durée annoncée par
# `duration`. On la désactive et on temporise explicitement, là où c'est
# utile. Voir le commentaire d'actions.py, qui fait le même choix.
pyautogui.PAUSE = 0

# 1.0 = durées d'origine, 2.0 = deux fois plus rapide. `actions.py` tient
# la même valeur et `actions.set_gesture_speed()` règle les deux à la fois,
# pour qu'une commande `--speed` s'applique aussi bien à la navigation
# qu'au combat.
GESTURE_SPEED = 2.0

# ============================================================
# PAUSES HUMAINES (secondes)
# ============================================================
# Bornes min/max — un délai aléatoire est tiré à chaque appel pour
# éviter un pattern robotique. À ajuster si certains écrans mettent
# plus ou moins longtemps à charger chez toi.
#
# Ces quatre-là attendent le CLIENT, pas la souris : un écran qui charge,
# une animation d'apparition avant de chercher un template. Elles suivent
# la vitesse, mais avec un plancher — chercher un bouton sur une frame de
# transition, c'est le manquer, et repartir pour un tour de boucle.

DELAY_AFTER_CLICK = (0.6, 1.2)          # après un clic simple (ex: clic sur un node)
DELAY_AFTER_TRANSITION = (1.2, 2.2)     # après un clic qui change d'écran (voyage, select, combat, quit)
DELAY_BEFORE_SEARCH = (0.3, 0.7)        # avant de chercher un template (laisse l'animation d'apparition finir)
DELAY_BETWEEN_RETRIES = (1.0, 1.8)      # entre deux tentatives en cas d'échec de détection

UI_DELAY_FLOOR = 0.30                   # sous ce seuil, l'écran n'a pas fini de charger


def scaled(seconds, floor=0.0):
    """Durée ramenée à l'échelle `GESTURE_SPEED`, sans descendre sous `floor`."""
    return max(floor, seconds / max(0.1, GESTURE_SPEED))


def human_delay(bounds, floor=UI_DELAY_FLOOR):
    """Attend une durée aléatoire dans l'intervalle `bounds` (min, max)."""
    duration = scaled(random.uniform(*bounds), floor)
    time.sleep(duration)
    return duration


# ============================================================
# MOUVEMENTS HUMAINS
# ============================================================

def ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def human_move_mouse(target_x, target_y):
    start_x, start_y = pyautogui.position()
    if (start_x, start_y) == (target_x, target_y):
        return

    distance = math.hypot(target_x - start_x, target_y - start_y)
    if distance < 10:
        pyautogui.moveTo(target_x, target_y, duration=scaled(random.uniform(0.05, 0.15)))
        return

    # Nombre de points de la courbe, PLAFONNÉ. Sans plafond, un déplacement
    # d'un bord à l'autre de l'écran en demandait une soixantaine — chacun
    # étant un appel système, et jadis une pause de 0.1 s. Une quarantaine
    # de points suffit à ce que le trajet reste courbe et non saccadé ; au
    # delà on paie des appels pour des pixels que personne ne regarde.
    steps = int(min(40, max(12, distance / 25)))
    ctrl_offset = min(120, distance * 0.25)

    p1_x = start_x + (target_x - start_x) * 0.25 + random.uniform(-ctrl_offset, ctrl_offset)
    p1_y = start_y + (target_y - start_y) * 0.25 + random.uniform(-ctrl_offset, ctrl_offset)
    p2_x = start_x + (target_x - start_x) * 0.75 + random.uniform(-ctrl_offset, ctrl_offset)
    p2_y = start_y + (target_y - start_y) * 0.75 + random.uniform(-ctrl_offset, ctrl_offset)

    duration = scaled(random.uniform(0.4, 0.7))

    for i in range(steps + 1):
        t = ease_out_cubic(i / steps)
        x = (
            (1 - t) ** 3 * start_x +
            3 * (1 - t) ** 2 * t * p1_x +
            3 * (1 - t) * t ** 2 * p2_x +
            t ** 3 * target_x
        )
        y = (
            (1 - t) ** 3 * start_y +
            3 * (1 - t) ** 2 * t * p1_y +
            3 * (1 - t) * t ** 2 * p2_y +
            t ** 3 * target_y
        )
        pyautogui.moveTo(int(x), int(y))
        time.sleep(duration / steps)

    pyautogui.moveTo(target_x, target_y)
    time.sleep(scaled(random.uniform(0.05, 0.12), floor=0.02))


def human_click(x, y):
    human_move_mouse(x + random.randint(-3, 3), y + random.randint(-3, 3))
    time.sleep(scaled(random.uniform(0.08, 0.18), floor=0.03))
    pyautogui.click()
    time.sleep(scaled(random.uniform(0.15, 0.3), floor=0.06))


# ============================================================
# GARER LA SOURIS
# ============================================================
# Un bouton peut être INVISIBLE POUR LE TEMPLATE parce que le curseur est
# dessus : au survol, le jeu l'éclaire, l'agrandit ou l'accompagne d'une
# infobulle, et l'image ne correspond plus. Demandé par Ewan le
# 02/09/2026 : quand tous les boutons ont été cherchés en vain, on
# déplace la souris avant de rechercher. Les points de stationnement sont
# sur le BORD GAUCHE de l'écran, où aucun bouton ne vit, et on alterne
# entre deux hauteurs pour ne pas rester au même endroit.
PARKING_SPOTS = ((0.04, 0.50), (0.04, 0.72))
_parking_turn = 0


def park_mouse():
    """Range le curseur hors de tout bouton ; alterne entre deux points."""
    global _parking_turn
    width, height = pyautogui.size()
    rx, ry = PARKING_SPOTS[_parking_turn % len(PARKING_SPOTS)]
    _parking_turn += 1
    x, y = int(width * rx) + random.randint(-6, 6), int(height * ry) + random.randint(-10, 10)
    logging.info("Souris garée en (%d, %d) : un bouton est peut-être caché dessous.", x, y)
    human_move_mouse(x, y)
    time.sleep(scaled(0.25, floor=0.1))


# ============================================================
# CLIC SUR BOUTON
# ============================================================

def click_button(image_name, timeout=10, threshold=MATCH_THRESHOLD, transition=False):
    """
    Cherche un bouton et clique dessus.

    transition=True indique que ce clic déclenche un changement
    d'écran (ex: voyage_button, select_button, combat_button,
    quit_button) : une pause plus longue est appliquée après le clic
    pour laisser le temps à l'UI de charger.
    """
    if image_name not in TEMPLATES:
        logging.error(f"Nom de bouton inconnu : {image_name}")
        return False

    template_path = TEMPLATES[image_name]
    logging.info(f"Recherche du bouton : {image_name}")

    start = time.time()
    parked = False
    while time.time() - start < timeout:
        human_delay(DELAY_BEFORE_SEARCH)
        # À mi-parcours d'une recherche longue, on déplace la souris une
        # fois : si le bouton était sous le curseur, il redevient
        # reconnaissable pour la seconde moitié.
        if not parked and timeout >= 3 and time.time() - start >= timeout / 2:
            park_mouse()
            parked = True
        coords = find_template_on_screen(template_path, threshold)
        if coords:
            x, y = coords
            pyautogui.moveTo(x, y)
            # Explicite depuis que PAUSE vaut 0 : le curseur doit être
            # ARRIVÉ avant l'appui, sinon le clic part de l'ancien point.
            time.sleep(scaled(0.12, floor=0.05))
            pyautogui.click()
            logging.info(f"Bouton '{image_name}' cliqué.")
            human_delay(DELAY_AFTER_TRANSITION if transition else DELAY_AFTER_CLICK)
            # Le POINT cliqué, et non un simple True : il reste vrai dans
            # un `if`, et permet de recliquer au même endroit (sortie du
            # boss final, lor_battle) une fois le bouton disparu.
            return (x, y)

        time.sleep(0.3)

    logging.warning(f"Bouton '{image_name}' introuvable.")
    return False


# ============================================================
# FONCTIONS GÉNÉRIQUES PAR CHEMIN D'IMAGE
# (indépendantes du dict TEMPLATES, utilisées par navigate.py)
# ============================================================

def image_exists(image_path, threshold=MATCH_THRESHOLD):
    """
    Retourne (True, (x, y)) si l'image est visible à l'écran, sinon (False, None).
    """
    coords = find_template_on_screen(image_path, threshold)
    if coords:
        return True, coords
    return False, None


def wait_for_image(image_path, timeout=10, threshold=MATCH_THRESHOLD, poll_interval=0.3):
    """
    Attend qu'une image apparaisse à l'écran, jusqu'à timeout secondes.
    Une petite pause est appliquée avant chaque tentative de détection
    pour laisser le temps aux animations d'apparition de se terminer.
    Retourne les coordonnées (x, y) du centre si trouvée, sinon None.
    """
    label = os.path.basename(image_path)
    logging.info(f"Attente de l'image : {label}")

    start = time.time()
    while time.time() - start < timeout:
        human_delay(DELAY_BEFORE_SEARCH)
        found, coords = image_exists(image_path, threshold)
        if found:
            logging.info(f"Image détectée : {label} @ {coords}")
            return coords
        time.sleep(poll_interval)

    logging.warning(f"Image non détectée après {timeout}s : {label}")
    return None


def topmost_match(image_path, timeout=10, threshold=MATCH_THRESHOLD, poll_interval=0.3):
    """
    Comme wait_for_image, mais pour une image qui peut apparaître PLUSIEURS
    fois à l'écran (ex: une liste d'entrées identiques). Attend qu'au
    moins une occurrence soit visible et retourne celle du HAUT de la
    liste — c'est-à-dire la première.

    Retourne (x, y) si au moins une occurrence est trouvée, sinon None.
    """
    label = os.path.basename(image_path)
    logging.info(f"Attente d'une liste contenant : {label}")

    start = time.time()
    while time.time() - start < timeout:
        human_delay(DELAY_BEFORE_SEARCH)
        matches = find_all_matches_on_screen(image_path, threshold)
        if matches:
            logging.info(f"{len(matches)} occurrence(s) de {label}, on prend la première : {matches[0]}")
            return matches[0]
        time.sleep(poll_interval)

    logging.warning(f"Aucune occurrence de {label} détectée après {timeout}s.")
    return None


def safe_click(x, y, transition=False):
    """
    Clique à des coordonnées données, en style humain, avec gestion d'erreur,
    puis attend que l'UI se stabilise.

    transition=True indique un clic qui change d'écran : une pause plus
    longue est appliquée après le clic.
    """
    try:
        human_click(x, y)
        human_delay(DELAY_AFTER_TRANSITION if transition else DELAY_AFTER_CLICK)
        return True
    except pyautogui.FailSafeException:
        logging.error("FailSafe déclenché : la souris a été déplacée dans un coin de l'écran.")
        return False
    except Exception as exc:
        logging.error(f"Erreur lors du clic sur ({x}, {y}) : {exc}")
        return False


def click_image(image_path, timeout=10, threshold=MATCH_THRESHOLD, transition=False):
    """
    Attend qu'une image apparaisse puis clique dessus (clic humain).
    Retourne True en cas de succès, False sinon.
    """
    coords = wait_for_image(image_path, timeout=timeout, threshold=threshold)
    if not coords:
        return False

    x, y = coords
    return safe_click(x, y, transition=transition)


def find_first_match_in_folder(folder_path, threshold=MATCH_THRESHOLD):
    """
    Scanne toutes les images (.png/.jpg/.jpeg) d'un dossier et retourne
    (image_path, (x, y)) pour la première qui correspond à l'écran actuel,
    ou (None, None) si aucune ne correspond.
    """
    if not os.path.isdir(folder_path):
        logging.error(f"Dossier introuvable : {folder_path}")
        return None, None

    valid_ext = (".png", ".jpg", ".jpeg")
    candidates = sorted(
        f for f in os.listdir(folder_path) if f.lower().endswith(valid_ext)
    )

    if not candidates:
        logging.warning(f"Aucune image trouvée dans le dossier : {folder_path}")
        return None, None

    # Pause avant le scan pour laisser le node fraîchement apparu finir
    # son animation d'entrée avant qu'on essaie de le matcher.
    human_delay(DELAY_BEFORE_SEARCH)

    for filename in candidates:
        image_path = os.path.join(folder_path, filename)
        found, coords = image_exists(image_path, threshold)
        if found:
            logging.info(f"Correspondance trouvée dans le dossier : {filename}")
            return image_path, coords

    return None, None