#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lor_api.py

Couche d'accès BAS NIVEAU au client Legends of Runeterra :
    - API locale du client (http://127.0.0.1:21337)
    - base de données des cartes (LoR-Bot/card_sets/*.json)
    - géométrie de la fenêtre du jeu et capture d'écran

Ce module ne contient AUCUNE logique de jeu et AUCUNE dépendance OCR.
Il est volontairement léger pour pouvoir être importé par n'importe quel
autre module (game_state.py, poc.py, ...) sans payer le coût de
chargement d'easyocr (plusieurs secondes + VRAM).

--------------------------------------------------------------------
CONVENTION DE COORDONNÉES — À LIRE AVANT DE TOUCHER À CE FICHIER
--------------------------------------------------------------------
L'API `positional-rectangles` renvoie des Y mesurés depuis le BAS de la
surface de rendu (origine en bas à gauche), alors que toutes les
bibliothèques d'image (OpenCV, PIL, pyautogui) travaillent depuis le
HAUT. `api_y_to_screen_y()` fait la conversion, et c'est le SEUL
endroit où elle doit être faite.

Toute nouvelle fonction qui manipule un rectangle de l'API doit passer
par `rect_to_screen_box()` / `rect_center_screen()`. Sinon on découpe au
mauvais endroit de l'écran, le crop est vide, et aucun chiffre ne peut
jamais être lu — c'est le bug classique de ce projet.

--------------------------------------------------------------------
ENDPOINTS UTILES
--------------------------------------------------------------------
GET /positional-rectangles
    {"PlayerName": ..., "OpponentName": ...,
     "GameState": "Menus" | "InProgress",
     "Screen": {"ScreenWidth": 1920, "ScreenHeight": 1080},
     "Rectangles": [{"CardID": 3, "CardCode": "06MT008",
                     "TopLeftX": 812, "TopLeftY": 730,
                     "Width": 126, "Height": 159,
                     "LocalPlayer": true}, ...]}
    Le rectangle de CardCode "face" est le nexus (un par joueur).

GET /game-result
    {"GameID": 12, "LocalPlayerWon": true}
    Décrit la DERNIÈRE partie terminée. GameID est monotone croissant :
    c'est ce qui permet de détecter une fin de partie (cf. game_state.py).

"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pyautogui
import requests

LOGGER = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

API_BASE = "http://127.0.0.1:21337"
API_TIMEOUT = 2.0

PROJECT_ROOT = Path(__file__).resolve().parent
# Chemin résolu depuis l'emplacement DU FICHIER et non depuis le
# répertoire courant : sinon lancer le bot depuis un autre dossier
# charge silencieusement zéro carte, et toutes les cartes du plateau
# sont ignorées sans message d'erreur clair.
CARD_SETS_PATH = PROJECT_ROOT / "LoR-Bot" / "card_sets"

GAME_WINDOW_TITLE = "Legends of Runeterra"

NEXUS_CARD_CODE = "face"

_SESSION = requests.Session()


class ApiUnavailable(RuntimeError):
    """Le client LoR ne répond pas (jeu fermé, ou API non encore prête)."""


# ============================================================
# APPELS API
# ============================================================

def get_json(endpoint: str, timeout: float = API_TIMEOUT):
    """
    Appelle un endpoint de l'API locale et renvoie le JSON décodé.
    Lève ApiUnavailable si le client ne répond pas ou renvoie autre
    chose que du JSON (ce qui arrive pendant les écrans de chargement).
    """
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    try:
        response = _SESSION.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ApiUnavailable(f"{endpoint} : {exc}") from exc


def get_positional_rectangles() -> dict:
    """État positionnel courant : cartes visibles + taille de l'écran de jeu."""
    return get_json("positional-rectangles")


def get_game_result() -> dict:
    """Résultat de la dernière partie terminée ({} si aucune)."""
    return get_json("game-result")


def api_is_up() -> bool:
    """True si le client LoR expose bien son API locale."""
    try:
        get_positional_rectangles()
        return True
    except ApiUnavailable:
        return False


# ============================================================
# BASE DE CARTES
# ============================================================

def load_card_db(folder: Path = CARD_SETS_PATH) -> dict:
    """
    Charge tous les sets JSON et renvoie {cardCode: dict_carte}.

    Renvoie un dict vide (avec un warning) si le dossier est absent :
    on préfère un bot qui tourne en dégradé à un crash au démarrage.
    """
    folder = Path(folder)
    if not folder.is_dir():
        LOGGER.warning(
            "Dossier de sets introuvable : %s — lance "
            "LoR-Bot/code/download_card_sets.py pour le remplir.", folder
        )
        return {}

    db = {}
    for path in sorted(folder.glob("*.json")):
        try:
            with open(path, encoding="utf8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Set illisible ignoré (%s) : %s", path.name, exc)
            continue
        if not isinstance(data, list):
            continue
        for card in data:
            code = card.get("cardCode")
            if code:
                db[code] = card

    LOGGER.info("%d cartes chargées depuis %s", len(db), folder)
    return db


# ============================================================
# FENÊTRE DU JEU
# ============================================================

@dataclass(frozen=True)
class Window:
    """
    Surface de rendu du jeu, en coordonnées BUREAU (origine en haut à
    gauche de l'écran). En plein écran, x = y = 0.
    """

    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def rel(self, rx: float, ry: float) -> tuple:
        """Point exprimé en ratios de la fenêtre (0..1, Y depuis le HAUT)."""
        return (int(self.x + rx * self.width), int(self.y + ry * self.height))

    def rel_box(self, box: tuple) -> tuple:
        """
        Zone exprimée en ratios ((rx1, ry1), (rx2, ry2)) -> (left, top,
        right, bottom) en coordonnées bureau.
        """
        (rx1, ry1), (rx2, ry2) = box
        left, top = self.rel(rx1, ry1)
        right, bottom = self.rel(rx2, ry2)
        return (left, top, right, bottom)


def find_game_window(title: str = GAME_WINDOW_TITLE) -> Optional[Window]:
    """
    Localise la fenêtre du jeu via win32gui, ou None si introuvable
    (jeu fermé, ou pywin32 absent).

    On utilise GetClientRect + ClientToScreen et NON GetWindowRect :
    GetWindowRect inclut la bordure et la barre de titre en mode
    fenêtré, ce qui décale de quelques pixels tous les ratios de zones
    et fait rater les détections de couleur.
    """
    try:
        import win32gui
    except ImportError:
        LOGGER.debug("pywin32 absent : repli sur l'écran complet.")
        return None

    handles = []

    def _collect(handle, _):
        if win32gui.IsWindowVisible(handle) and win32gui.GetWindowText(handle) == title:
            handles.append(handle)

    try:
        win32gui.EnumWindows(_collect, None)
    except Exception as exc:  # EnumWindows peut lever si un handle meurt
        LOGGER.debug("EnumWindows a échoué : %s", exc)
        return None

    if not handles:
        return None

    handle = handles[0]
    try:
        left, top, right, bottom = win32gui.GetClientRect(handle)
        origin_x, origin_y = win32gui.ClientToScreen(handle, (left, top))
    except Exception as exc:
        LOGGER.debug("Lecture du rect client impossible : %s", exc)
        return None

    return Window(origin_x, origin_y, right - left, bottom - top)


def get_window(api_data: Optional[dict] = None) -> Window:
    """
    Fenêtre du jeu, avec deux replis successifs :
        1. win32gui (précis, gère le mode fenêtré)
        2. la taille annoncée par l'API, à l'origine (0, 0)
        3. la taille de l'écran complet
    """
    window = find_game_window()
    if window is not None and window.width > 0 and window.height > 0:
        return window

    if api_data:
        screen = api_data.get("Screen") or {}
        width = screen.get("ScreenWidth")
        height = screen.get("ScreenHeight")
        if width and height:
            return Window(0, 0, int(width), int(height))

    width, height = pyautogui.size()
    return Window(0, 0, int(width), int(height))


# ============================================================
# CAPTURE D'ÉCRAN
# ============================================================

def capture_screen_bgr() -> np.ndarray:
    """
    Capture le bureau complet et renvoie un tableau BGR (convention
    OpenCV). Tout le projet manipule du BGR : ne pas mélanger avec du
    RGB, sinon les seuils HSV de détection de couleur sont faux (rouge
    et bleu échangés).
    """
    return cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)


# ============================================================
# CONVERSION DE COORDONNÉES API -> ÉCRAN
# ============================================================

def api_y_to_screen_y(api_y: float, window: Window) -> int:
    """Y de l'API (depuis le BAS de la fenêtre) -> Y bureau (depuis le HAUT)."""
    return int(window.y + window.height - api_y)


def rect_to_screen_box(rect: dict, window: Window) -> tuple:
    """Rectangle de l'API -> (left, top, right, bottom) en coordonnées bureau."""
    left = int(window.x + rect["TopLeftX"])
    top = api_y_to_screen_y(rect["TopLeftY"], window)
    return (left, top, left + int(rect["Width"]), top + int(rect["Height"]))


def rect_center_screen(rect: dict, window: Window) -> tuple:
    """Centre d'un rectangle de l'API, en coordonnées bureau (pour cliquer)."""
    left, top, right, bottom = rect_to_screen_box(rect, window)
    return ((left + right) // 2, (top + bottom) // 2)


def crop_box(image: np.ndarray, box: tuple) -> Optional[np.ndarray]:
    """
    Découpe (left, top, right, bottom) dans une image, en bornant aux
    limites de l'image. Renvoie None si la zone est hors cadre.
    """
    left, top, right, bottom = (int(v) for v in box)
    height, width = image.shape[:2]
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right <= left or bottom <= top:
        return None
    return image[top:bottom, left:right]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print(f"API joignable        : {api_is_up()}")
    print(f"Fenêtre du jeu       : {find_game_window()}")
    print(f"Fenêtre retenue      : {get_window()}")
    print(f"Cartes en base       : {len(load_card_db())}")
    try:
        data = get_positional_rectangles()
        print(f"GameState            : {data.get('GameState')}")
        print(f"Rectangles           : {len(data.get('Rectangles') or [])}")
        print(f"Screen (API)         : {data.get('Screen')}")
    except ApiUnavailable as exc:
        print(f"positional-rectangles indisponible : {exc}")
