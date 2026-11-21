#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gestures.py

La COUCHE SOURIS du bot : les seuls appels à pyautogui de la logique de
combat. Quatre gestes (`move`, `click`, `right_click`, `drag`), une
échelle de vitesse (`GESTURE_SPEED`, `pause`, `set_gesture_speed`) et
les trois planchers qui rendent un glisser-déposer correct.

--------------------------------------------------------------------
POURQUOI UN MODULE À PART
--------------------------------------------------------------------
Jusqu'au 05/09/2026 ces gestes vivaient dans actions.py, au milieu de
4 400 lignes de décision. Les séparer rend deux choses évidentes :

    - ce qui DÉCIDE (actions.py : plan de pose, d'attaque, de blocage,
      ciblage) ne touche jamais pyautogui et se rejoue hors ligne sur une
      trace (`replay.py`) ou dans les tests ;
    - ce qui BOUGE la souris tient ici, en soixante lignes, et c'est le
      seul endroit à relire quand un geste rate.

actions.py réimporte ces noms : `actions.click`, `actions.drag`, etc.
restent valables — et les tests qui les remplacent par des espions
continuent de fonctionner, parce que les fonctions d'actions résolvent
`click` dans leur propre espace de noms.
"""

from __future__ import annotations

import logging
import random
import time

import pyautogui

LOGGER = logging.getLogger(__name__)

# Le coin de l'écran interrompt tout : indispensable quand un script
# pilote la souris.
pyautogui.FAILSAFE = True

# LE RÉGLAGE LE PLUS COÛTEUX DE TOUT LE PROJET, ET IL ÉTAIT INVISIBLE.
# pyautogui dort `PAUSE` secondes après CHAQUE appel public — moveTo,
# click, mouseDown, mouseUp — et sa valeur par défaut est 0.1 s. Or un
# déplacement « humain » trace une courbe de Bézier en une soixantaine de
# `moveTo` : la pause invisible ajoutait donc jusqu'à 6 s par déplacement,
# soit une douzaine de secondes pour un seul glisser-déposer, là où le code
# croyait en dépenser 0.6. C'est ce qui rendait un combat interminable
# (cf. les combats à 900 s dans journal.jsonl).
#
# On la met à zéro et on assume les temporisations EXPLICITEMENT : elles
# existent déjà, sont nommées, et chacune protège quelque chose de précis.
# Une pause implicite uniforme après chaque geste ne protège rien : elle
# ralentit autant le survol d'une carte, où l'attente est utile, que le
# millième point d'une courbe, où elle ne sert à rien.
pyautogui.PAUSE = 0

# Échelle des gestes. 1.0 = les durées d'origine ; 2.0 = deux fois plus
# rapide. Ce qui est mis à l'échelle, ce sont les déplacements et les
# micro-pauses de la souris — pas les attentes d'animation du client, qui
# ont leur propre plancher (cf. `_pause`).
#
# À monter avec méthode : au-delà d'un certain point le client laisse
# tomber des gestes, et le symptôme n'est pas une erreur mais une pose qui
# rate. `play_card` retente deux fois, donc une carte qui n'arrive
# qu'après deux tentatives est le signe que tu es allé trop loin.
GESTURE_SPEED = 2.0


def pause(seconds: float, floor: float = 0.0) -> float:
    """
    Durée ramenée à l'échelle `GESTURE_SPEED`, sans descendre sous `floor`.

    Le plancher distingue les deux natures de délai. Un temps de
    déplacement est un pur coût : le diviser ne casse rien. Une attente
    d'animation du client, elle, protège la CORRECTION du geste — sous un
    certain seuil, la carte est saisie dans un état intermédiaire et le
    drag part de travers. Elle suit donc l'échelle, mais pas jusqu'en bas.
    """
    return max(floor, seconds / max(0.1, GESTURE_SPEED))


def set_gesture_speed(value: float) -> None:
    """Change l'échelle des gestes ici ET dans click_utils, d'un seul geste."""
    global GESTURE_SPEED
    GESTURE_SPEED = max(0.1, float(value))
    try:
        import click_utils
        click_utils.GESTURE_SPEED = GESTURE_SPEED
    except Exception:  # click_utils tire adventure_navigation
        pass
    LOGGER.info("Vitesse des gestes : x%.2f", GESTURE_SPEED)


# Mouvement de souris « humain » : on réutilise celui déjà écrit pour la
# navigation plutôt que d'en avoir deux qui divergent.
try:
    from click_utils import human_move_mouse as _human_move_mouse
except Exception as exc:  # click_utils tire adventure_navigation
    LOGGER.debug("click_utils indisponible (%s) : mouvement pyautogui simple.", exc)
    _human_move_mouse = None



# Ancien nom, gardé pour actions.py et ses tests.
_pause = pause


# Les trois planchers que la vitesse ne peut pas franchir (cf. `drag`).
HOVER_BEFORE_GRAB = 0.55   # la carte s'agrandit au survol : la laisser finir
HOLD_DELAY = 0.12
DROP_SETTLE = 0.35


def move(x: float, y: float) -> None:
    if _human_move_mouse is not None:
        _human_move_mouse(int(x), int(y))
    else:
        pyautogui.moveTo(int(x), int(y), duration=pause(random.uniform(0.25, 0.45)))


def right_click(x: float, y: float) -> None:
    """Clic droit : c'est lui qui ANNULE une action en attente dans ce client."""
    move(x, y)
    time.sleep(pause(random.uniform(0.06, 0.14), floor=0.02))
    pyautogui.click(button="right")
    time.sleep(pause(random.uniform(0.15, 0.30), floor=0.06))


def click(x: float, y: float) -> None:
    move(x, y)
    # Un geste, puis le clic. Ces deux micro-pauses remplacent la pause
    # implicite de pyautogui, qu'on a désactivée : le client a besoin d'un
    # souffle entre l'arrivée du curseur et l'appui, pas d'un dixième de
    # seconde après chacun des soixante points du trajet.
    time.sleep(pause(random.uniform(0.06, 0.14), floor=0.02))
    pyautogui.click()
    time.sleep(pause(random.uniform(0.15, 0.30), floor=0.06))


def drag(source: tuple, destination: tuple) -> None:
    """
    Glisser-déposer, avec un survol préalable.

    Le survol n'est pas cosmétique : au passage de la souris, LoR agrandit
    la carte. Appuyer avant la fin de cette animation attrape la carte
    dans un état intermédiaire et le drag part de travers.

    LE RELÂCHEMENT EST DANS UN `finally`, ET C'EST INDISPENSABLE.
    Le déplacement vers la destination est justement l'endroit où le
    fail-safe de pyautogui se déclenche : il vérifie les coins à chaque
    `moveTo`. Sans ce `finally`, l'arrêt d'urgence — le geste qu'on fait
    quand le bot dérape — laissait le bouton gauche ENFONCÉ, avec une
    carte accrochée au curseur et un système inutilisable jusqu'à un clic
    manuel. Le moment où l'on a le plus besoin de reprendre la main était
    exactement celui où on la perdait.
    """
    move(*source)
    # Les trois planchers ci-dessous sont les seules durées que la vitesse
    # ne peut pas réduire à néant : ce sont elles qui rendent le geste
    # correct, pas rapide.
    time.sleep(pause(HOVER_BEFORE_GRAB, floor=0.25))
    pyautogui.mouseDown()
    try:
        time.sleep(pause(HOLD_DELAY, floor=0.05))
        move(*destination)
        time.sleep(pause(DROP_SETTLE, floor=0.12))
    finally:
        pyautogui.mouseUp()
    time.sleep(pause(DROP_SETTLE, floor=0.12))


# --------------------------------------------------------------------
# LA FENÊTRE DU JEU — un geste n'arrive que si elle est au premier plan
# --------------------------------------------------------------------
# MESURÉ LE 08/11/2026, ET C'EST UNE PANNE SILENCIEUSE. Un clic active
# la fenêtre qu'il touche : tant que le bot ne faisait que cliquer, le
# focus se réparait tout seul et personne n'avait à y penser. LA MOLETTE
# NON — Unity ne traite les événements de molette que fenêtre ACTIVE, et
# `pyautogui.scroll` ne rend aucune erreur quand ils tombent dans le
# vide. Mesure sur la grille des champions, même geste, même point :
#
#     fenêtre au premier plan     écart entre deux captures : 33.6
#     VS Code au premier plan     écart entre deux captures :  0.04
#
# Conséquence vue en session : `champions._parcourir` lit « rien n'a
# bougé » comme « bout de liste atteint », conclut sur le premier écran
# venu — six vignettes toutes épuisées — et renonce au choix du
# champion. Donc : AVANT DE DÉFILER, ON S'ASSURE DU PREMIER PLAN, et si
# on n'y arrive pas on le DIT au lieu de conclure.
WINDOW_TITLE = "Legends of Runeterra"
# Windows refuse le vol de focus à un processus qui n'est pas déjà au
# premier plan : la bascule peut échouer, et alors elle le dit.
FOCUS_SETTLE = 0.35

try:                                            # pywin32, Windows seulement
    import win32gui as _win32gui
except ImportError:                             # pragma: no cover
    _win32gui = None


def game_window_handle(title: str = WINDOW_TITLE):
    """Le handle de la fenêtre du jeu, ou None (pywin32 absent, jeu fermé)."""
    if _win32gui is None:
        return None
    try:
        handle = _win32gui.FindWindow(None, title)
    except Exception:                           # noqa: BLE001
        return None
    return handle or None


def game_window_focused(title: str = WINDOW_TITLE) -> bool:
    """La fenêtre du jeu est-elle au premier plan ?"""
    handle = game_window_handle(title)
    if handle is None:
        return False
    try:
        return _win32gui.GetForegroundWindow() == handle
    except Exception:                           # noqa: BLE001
        return False


def focus_game_window(title: str = WINDOW_TITLE) -> bool:
    """
    Met le jeu au premier plan et DIT si on y est arrivé.

    Rend True si la fenêtre est (ou devient) active. Rend False sans
    rien casser quand pywin32 manque, que le jeu est fermé, ou que
    Windows refuse la bascule : l'appelant décide quoi en faire — ici,
    ne pas confondre « plus rien ne bouge » avec « on est au bout ».
    """
    if game_window_focused(title):
        return True
    handle = game_window_handle(title)
    if handle is None:
        return False
    try:
        if _win32gui.IsIconic(handle):
            _win32gui.ShowWindow(handle, 9)     # SW_RESTORE
        _win32gui.SetForegroundWindow(handle)
    except Exception as exc:                    # noqa: BLE001
        LOGGER.warning("Fenêtre du jeu : bascule refusée (%s).", exc)
        return False
    time.sleep(FOCUS_SETTLE)
    return game_window_focused(title)
