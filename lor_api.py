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

GET /static-decklist
    {"DeckCode": "CEBA...", "CardsInDeck": {"01IO015": 3, ...}}
    Notre deck de la partie en cours (CardsInDeck vaut null hors partie).

GET /game-result
    {"GameID": 12, "LocalPlayerWon": true}
    Décrit la DERNIÈRE partie terminée. GameID est monotone croissant :
    c'est ce qui permet de détecter une fin de partie (cf. game_state.py).

"""

from __future__ import annotations

import json
import logging
import socket
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

# LE PORT DE L'API N'EST PAS FIXE. 21337 est celui que le client prend
# quand il est libre — mais le 04/11/2026 il était sur 21338, et rien ne
# le disait : le bot a traversé la carte, lancé le boss final et attendu
# 120 s devant un mulligan qu'il ne voyait pas. Un simple changement de
# constante ne suffirait pas, puisque le port suivant est pris au
# lancement suivant selon ce qui est libre. On SONDE.
API_HOST = "127.0.0.1"
API_PORT_DEFAULT = 21337
# Les ports essayés, dans l'ordre, quand celui en cours ne répond pas.
API_PORT_CANDIDATES = tuple(range(21337, 21348))
API_BASE = f"http://{API_HOST}:{API_PORT_DEFAULT}"
API_TIMEOUT = 2.0
# Sonde plus courte que la lecture normale : on en fait une par port.
API_PROBE_TIMEOUT = 0.6

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

def set_api_port(port: int) -> str:
    """Fixe le port de l'API et renvoie la nouvelle base."""
    global API_BASE
    API_BASE = f"http://{API_HOST}:{int(port)}"
    return API_BASE


def probe_api_port(port: int, timeout: float = API_PROBE_TIMEOUT) -> bool:
    """
    Ce port porte-t-il l'API du client ?

    On ne se contente pas d'un port OUVERT : d'autres services tournent
    dans ces eaux-là. La réponse doit être le JSON de l'API, reconnu à
    ses clés (`Rectangles` / `GameState`). Un port ouvert qui répond
    autre chose est écarté.
    """
    url = f"http://{API_HOST}:{int(port)}/positional-rectangles"
    try:
        data = _SESSION.get(url, timeout=timeout).json()
    except Exception:      # noqa: BLE001 — un port muet n'est pas une erreur
        return False
    return isinstance(data, dict) and ("Rectangles" in data or "GameState" in data)


def find_api_base(candidates=API_PORT_CANDIDATES) -> Optional[str]:
    """
    Cherche le port de l'API et l'adopte. Rend la base trouvée, ou None.

    Le port en cours est essayé d'abord : quand il répond, la recherche
    ne coûte rien. Ce n'est pas une boucle de réessai — un seul passage,
    puis l'appelant décide.
    """
    courant = _port_courant()
    ordre = [courant] + [p for p in candidates if p != courant]
    for port in ordre:
        if probe_api_port(port):
            if port != courant:
                LOGGER.warning(
                    "API du client trouvée sur le port %d (et non %d) : "
                    "le client prend le premier port libre.", port, courant)
            return set_api_port(port)
    return None


def _port_courant() -> int:
    try:
        return int(API_BASE.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return API_PORT_DEFAULT


def get_json(endpoint: str, timeout: float = API_TIMEOUT):
    """
    Appelle un endpoint de l'API locale et renvoie le JSON décodé.
    Lève ApiUnavailable si le client ne répond pas ou renvoie autre
    chose que du JSON (ce qui arrive pendant les écrans de chargement).

    UN REFUS DE CONNEXION DÉCLENCHE UNE RECHERCHE DE PORT, une seule fois
    par appel : le client a pu démarrer sur un autre port que celui qu'on
    interroge (cf. API_PORT_CANDIDATES). Un refus est le bon signal — un
    délai dépassé ou un JSON invalide veulent dire « quelqu'un répond »,
    et changer de port là-dessus ferait perdre le bon.
    """
    try:
        return _get(endpoint, timeout)
    except ApiUnavailable:
        if not _connexion_refusee():
            raise
        if find_api_base() is None:
            raise
        return _get(endpoint, timeout)


def _get(endpoint: str, timeout: float):
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    try:
        response = _SESSION.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ApiUnavailable(f"{endpoint} : {exc}") from exc


def _connexion_refusee() -> bool:
    """Le port est-il muet ? (refus franc, pas un délai dépassé)"""
    probe = socket.socket()
    probe.settimeout(API_PROBE_TIMEOUT)
    try:
        probe.connect((API_HOST, _port_courant()))
        return False
    except Exception:      # noqa: BLE001 — refus, délai, hôte injoignable
        return True
    finally:
        probe.close()


def get_positional_rectangles() -> dict:
    """État positionnel courant : cartes visibles + taille de l'écran de jeu."""
    return get_json("positional-rectangles")


def get_game_result() -> dict:
    """Résultat de la dernière partie terminée ({} si aucune)."""
    return get_json("game-result")


def get_static_decklist() -> dict:
    """
    Notre deck de la partie EN COURS : {"DeckCode": ..., "CardsInDeck":
    {"01IO015": 3, ...}}. `CardsInDeck` est None hors partie. C'est la
    seule chose que l'API dise de ce qu'on n'a PAS encore vu.
    """
    return get_json("static-decklist")


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


# UNE BASE PRÉSENTE PEUT ÊTRE INCOMPLÈTE, ET ÇA NE SE VOIT PAS.
# « 2653 cartes » avait l'air complet. Il manquait pourtant TOUT le
# préfixe « 99… » — des cartes exclusives au mode aventure PvE, que
# Riot ne publie dans AUCUN paquet du Data Dragon (recensé le
# 10/11/2026 : quatorze paquets existent, aucun ne les contient) et que
# le bot rencontre à chaque tentative. Sans elles, `game_state` lit
# « 0/0 (inconnue) », `classify_card` rend `Targeting.NONE`, et le bot
# pose une carte qu'il ne sait pas résoudre : 23 s perdues sur 99PZ130
# le 09/11/2026 à 19:31, 8 s de plus au combat suivant.
#
# Ces cinq codes ont été RELEVÉS DANS LES LOGS, pas choisis : ils sont
# le témoin le moins cher qu'un compte de cartes ne dit pas tout. S'ils
# sont connus, c'est que `cartes_hors_ddragon.json` est là.
# Remplissage : `python LoR-Bot/code/download_card_sets.py`.
CODES_TEMOINS = ("99PZ104", "99PZ130", "99SH003", "99MT003", "99IO003")


def etat_base_cartes(db: Optional[dict] = None) -> tuple:
    """
    (total, hors_ddragon, codes témoins manquants).

    `hors_ddragon` compte les cartes qui ne viennent pas de Riot — elles
    portent un champ `source`. Les témoins manquants NOMMENT le trou :
    une base complète en rend zéro.
    """
    if db is None:
        db = load_card_db()
    hors = sum(1 for carte in db.values() if carte.get("source"))
    manquants = tuple(code for code in CODES_TEMOINS if code not in db)
    return len(db), hors, manquants


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
    total, hors, manquants = etat_base_cartes()
    print(f"Cartes en base       : {total} (dont {hors} hors Data Dragon)")
    if manquants:
        print(f"  TÉMOINS MANQUANTS  : {', '.join(manquants)} — lance "
              f"LoR-Bot/code/download_card_sets.py")
    try:
        data = get_positional_rectangles()
        print(f"GameState            : {data.get('GameState')}")
        print(f"Rectangles           : {len(data.get('Rectangles') or [])}")
        print(f"Screen (API)         : {data.get('Screen')}")
    except ApiUnavailable as exc:
        print(f"positional-rectangles indisponible : {exc}")
