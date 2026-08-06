#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game_state.py

Répond à UNE question : « où en est la partie, là, maintenant ? »

C'est la brique qui manquait avant de pouvoir agir. Savoir quelles
cartes on a et quelles stats elles ont (poc.py + detect_chiffres.py) ne
sert à rien si on ne sait pas s'il faut jouer une carte, déclarer une
attaque, assigner des bloqueurs ou simplement attendre. Aucune action
ne doit être déclenchée sans être passée par `GameStateReader`.

--------------------------------------------------------------------
DEUX SOURCES D'INFORMATION, ET POURQUOI
--------------------------------------------------------------------
1. L'API locale (`lor_api`) donne la POSITION et l'IDENTITÉ de chaque
   carte visible. C'est fiable, rapide, et indépendant de la
   résolution. On s'en sert pour tout ce qui est « qui est où ».

2. La vision (OpenCV sur une capture d'écran) donne ce que l'API ne
   dit PAS : à qui est le tour, et qui détient le jeton d'attaque.
   L'API n'expose aucun champ pour ça. Deux tests, de natures
   différentes et pour de bonnes raisons :
       - l'orbe de fin de tour (à droite, à mi-hauteur) est BLEUE quand
         c'est à nous d'agir, GRISE sinon -> test de COULEUR, le bleu
         saturé ne se confond avec rien d'autre à cet endroit ;
       - le jeton d'attaque est l'icône d'épée -> test de FORME
         (template matching). Un test de couleur est inutilisable ici :
         le décor du plateau est en laiton et bois doré, donc dans les
         teintes exactes de l'épée, et le moindre reflet sur un rouage
         passe le seuil. Une forme, non.

--------------------------------------------------------------------
ZONES DU PLATEAU
--------------------------------------------------------------------
L'API ne dit pas non plus dans quelle zone se trouve une carte : il
faut le déduire de sa hauteur. Les cartes sont classées par bandes
horizontales, de bas en haut :

    hand           notre main (les cartes dépassent sous le bord bas)
    board          notre banc
    attack         notre rangée d'attaque (cartes avancées)
    stack          la pile de sorts, au milieu
    enemy_attack   la rangée d'attaque adverse
    enemy_board    le banc adverse
    enemy_hand     la main adverse

Les bornes de `ZONE_BANDS` sont exprimées en ratio de la hauteur de la
fenêtre, mesuré depuis le BAS, sur un point d'ancrage situé à 25% sous
le bord haut de la carte. Elles viennent du bot de référence
(LoR-Bot/code/StateMachine.py) et fonctionnent en 1920x1080.

    >>> python game_state.py inspect

affiche, pour chaque carte réellement présente à l'écran, son ratio
calculé et la zone déduite. C'est l'outil pour valider ou réajuster ces
bornes en 30 secondes au lieu de deviner.

--------------------------------------------------------------------
DISTINGUER « JE BLOQUE » DE « J'AI ATTAQUÉ ET IL A BLOQUÉ »
--------------------------------------------------------------------
Piège classique : dans les deux cas il y a des cartes adverses dans la
bande `enemy_attack`. Le bot de référence s'en sort avec des temporisa-
tions. On fait mieux : si NOTRE rangée d'attaque est occupée, c'est nous
l'attaquant (phase ATTACKING, il n'y a qu'à attendre la résolution) ;
si elle est vide et que la rangée adverse est occupée, c'est nous qui
devons bloquer (phase BLOCKING).

--------------------------------------------------------------------
UTILISATION
--------------------------------------------------------------------
    from game_state import GameStateReader, Phase

    reader = GameStateReader()
    snap = reader.snapshot()

    if snap.phase is Phase.ATTACK_TURN:
        for card in snap.hand:
            ...          # card.center est déjà en coordonnées écran

CLI :
    python game_state.py monitor      # boucle de surveillance en direct
    python game_state.py inspect      # tableau des rectangles + zones
    python game_state.py vision       # crops de calibration + score du jeton
    python game_state.py snap avec    # capture d'écran nommée
    python game_state.py cut-token    # découpe le template de l'épée
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

import cv2
import numpy as np

import lor_api
from lor_api import ApiUnavailable, Window

LOGGER = logging.getLogger(__name__)


# ============================================================
# ZONES — bandes calibrées (réf. 1920x1080)
# ============================================================

# Point d'ancrage : 25% de la hauteur de la carte sous son bord haut.
# On n'utilise pas le centre de la carte parce que les cartes en main
# dépassent largement sous le bord bas de l'écran : leur centre tombe
# hors cadre et la bande devient impossible à calibrer.
ZONE_ANCHOR_RATIO = 0.25

# (borne supérieure du ratio depuis le BAS, nom de la zone), croissant.
ZONE_BANDS = (
    (0.030, "hand"),
    (0.250, "board"),
    (0.400, "attack"),
    (0.550, "stack"),
    (0.725, "enemy_attack"),
    (0.900, "enemy_board"),
)
FALLBACK_ZONE = "enemy_hand"

ZONE_ORDER = (
    "hand",
    "board",
    "attack",
    "stack",
    "enemy_attack",
    "enemy_board",
    "enemy_hand",
)

# Nombre maximum d'unités sur le banc (règle du jeu).
MAX_BOARD_SIZE = 6

# Où saisir une carte à la souris, en fraction de sa hauteur depuis son
# bord haut. Surtout PAS le centre : les cartes en main dépassent
# largement sous le bord bas de l'écran, leur centre géométrique tombe
# hors cadre, et un clic à cet endroit ne touche rien du tout.
CARD_GRAB_Y_RATIO = 0.15


# ============================================================
# VISION — zones et seuils de couleur
# ============================================================
# Zones exprimées en ratios de la fenêtre ((rx1, ry1), (rx2, ry2)),
# Y depuis le HAUT (convention image).
#
# Les seuils HSV sont en convention OpenCV : H sur 0-179 (donc moitié
# des degrés), S et V sur 0-255. L'image d'entrée est en BGR
# (cf. lor_api.capture_screen_bgr) — ne pas y passer du RGB, sinon
# rouge et bleu sont échangés et les deux tests renvoient n'importe quoi.
#
# ATTENTION — LA SATURATION EST LE SEUL GARDE-FOU QUI COMPTE ICI
# Le plateau de LoR est presque entièrement en laiton et bois doré, donc
# dans les teintes orange. Un test « teinte orange » avec une saturation
# permissive détecte le DÉCOR et renvoie systématiquement vrai. Seul un
# plancher de saturation élevé (>= 190) distingue un élément d'interface
# saturé de la ferronnerie du fond.
#
# Ces valeurs viennent du bot de référence, dont le code convertissait
# du RGB comme si c'était du BGR (rouge et bleu échangés). Pour un tel
# échange, H_vraie = 240° - H_lue, tandis que S et V sont INCHANGÉS
# (max et min d'un triplet sont invariants par permutation des canaux).
# Il ne fallait donc convertir que la teinte, et surtout pas desserrer
# S et V.
#
# `python game_state.py vision` exporte le crop et le masque, et indique
# quel critère (H, S ou V) écarte les pixels, pour réajuster.

TURN_ORB_REGION = ((0.77, 0.42), (0.93, 0.58))
TURN_ORB_HSV = ((100, 190, 180), (122, 255, 255))   # bleu saturé de l'orbe
TURN_ORB_MIN_PX = 100


# ============================================================
# JETON D'ATTAQUE — TEMPLATE MATCHING, PAS DE COULEUR
# ============================================================
# Le jeton est l'icône d'épée. Il est cherché par CORRESPONDANCE DE
# FORME et non par couleur, pour une raison de fond : le décor du
# plateau (laiton, bois doré, reflets sur les rouages) occupe exactement
# les teintes de l'épée. Même avec une saturation stricte, le liseré
# brillant d'un rouage passe le test — c'est ce qui donnait un faux
# positif permanent. Une forme, elle, ne se confond pas avec un reflet.
#
# Le template est à générer une fois depuis une capture :
#     python game_state.py snap avec        # pendant que tu as le jeton
#     python game_state.py cut-token        # entoure l'épée à la souris
#
# À VÉRIFIER EN JEU : si l'épée apparaît aussi du côté adverse quand
# c'est LUI qui a le jeton, alors la seule présence de l'icône ne suffit
# pas — c'est son côté qui compte. `find_attack_token()` gère déjà ce cas
# en comparant la position du match à la ligne médiane entre les deux
# nexus (donnée par l'API, donc fiable). Si l'icône ne s'affiche jamais
# côté adverse, ce test est simplement toujours vrai et ne coûte rien.

ATTACK_TOKEN_TEMPLATE = lor_api.PROJECT_ROOT / "assets" / "attack_token.png"

# 0.75 : valeur validée en jeu. Si un faux positif apparaît un jour, la
# bonne réaction est de RECADRER LE TEMPLATE plus serré, pas de remonter
# ce seuil. Un template qui embarque du décor a un score plafonné (le
# décor bouge), donc on est tenté de descendre le seuil pour compenser —
# et on finit par accepter des correspondances qui n'en sont pas. Le
# score affiché par `monitor` doit rester nettement au-dessus du seuil
# quand le jeton est là, et nettement en dessous quand il ne l'est pas.
ATTACK_TOKEN_MATCH_THRESHOLD = 0.75

# Région de recherche volontairement large en hauteur : elle doit couvrir
# les DEUX moitiés du plateau pour pouvoir déterminer de quel côté se
# trouve l'épée. La restreindre en largeur suffit à garder le matching
# rapide et à éviter de matcher une épée dessinée sur l'illustration
# d'une carte en main.
ATTACK_TOKEN_SEARCH_REGION = ((0.66, 0.18), (1.00, 0.92))


# ============================================================
# MULLIGAN
# ============================================================
# Pendant le mulligan, les cartes proposées sont toutes alignées à la
# même hauteur, au milieu de l'écran. Attention : les cartes en main en
# cours de partie sont ALIGNÉES AUSSI — c'est la hauteur (bien plus
# basse) et le plateau vide qui font la différence.

MULLIGAN_BAND = (0.45, 0.80)
MULLIGAN_MAX_SPREAD = 0.02
MULLIGAN_MIN_CARDS = 3


# ============================================================
# PHASES
# ============================================================

class Phase(Enum):
    """Phase de jeu courante. C'est le seul vocabulaire que la couche
    de décision doit connaître."""

    NO_API = "api_injoignable"       # client fermé ou API pas prête
    MENUS = "menus"                  # hors partie
    MULLIGAN = "mulligan"            # choix des cartes de départ
    OPPONENT_TURN = "tour_adverse"   # rien à faire, on attend
    ATTACK_TURN = "notre_tour_attaque"   # à nous, avec le jeton d'attaque
    DEFEND_TURN = "notre_tour_defense"   # à nous, sans le jeton
    OUR_TURN = "notre_tour_indetermine"  # à nous, jeton non déterminable
    BLOCKING = "blocage"             # l'adversaire attaque, il faut bloquer
    ATTACKING = "attaque_declaree"   # notre attaque est posée, ça résout
    SPELL_STACK = "sort_en_attente"  # un sort attend une réponse
    GAME_OVER = "partie_terminee"    # événement, émis UNE seule fois

    @property
    def is_our_move(self) -> bool:
        """True si le bot doit agir maintenant."""
        return self in (
            Phase.MULLIGAN,
            Phase.ATTACK_TURN,
            Phase.DEFEND_TURN,
            Phase.OUR_TURN,
            Phase.BLOCKING,
            Phase.SPELL_STACK,
        )

    @property
    def in_game(self) -> bool:
        """True si une partie est en cours (ni menus, ni API absente)."""
        return self not in (Phase.NO_API, Phase.MENUS, Phase.GAME_OVER)


# ============================================================
# MODÈLE DE CARTE
# ============================================================

def _normalize_keyword(value: str) -> str:
    """« Can't Block » et « CantBlock » doivent matcher : on retire tout
    ce qui n'est pas alphanumérique et on passe en minuscules."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


@dataclass
class BoardCard:
    """Une carte visible à l'écran, enrichie de sa zone et de ses
    coordonnées écran (prêtes à cliquer)."""

    card_id: int
    code: str
    name: str
    cost: int
    base_attack: int
    base_health: int
    type: str
    keywords: tuple
    keyword_refs: tuple
    description: str
    local: bool
    zone: str
    ratio: float
    box: tuple      # (left, top, right, bottom) en coordonnées bureau
    center: tuple   # (x, y) en coordonnées bureau
    known: bool     # False si le cardCode est absent de card_sets

    # Stats LUES à l'écran, remplies par enrich_with_live_stats().
    # None tant que l'OCR n'a pas tourné : ne pas confondre avec 0.
    attack_read: Optional[int] = None
    health_read: Optional[int] = None

    # --- stats effectives ----------------------------------------------
    # `attack` et `health` sont des PROPRIÉTÉS : elles renvoient la valeur
    # lue à l'écran si on l'a, la valeur de base sinon. Tout le code de
    # décision utilise donc automatiquement les stats réelles dès que
    # l'OCR a tourné, sans qu'aucun appelant ait à le savoir — buffs,
    # dégâts subis et affaiblissements compris.
    @property
    def attack(self) -> int:
        return self.base_attack if self.attack_read is None else self.attack_read

    @property
    def health(self) -> int:
        return self.base_health if self.health_read is None else self.health_read

    @property
    def stats_are_live(self) -> bool:
        return self.attack_read is not None or self.health_read is not None

    # --- type de carte -------------------------------------------------
    @property
    def is_unit(self) -> bool:
        return self.type == "Unit"

    @property
    def is_spell(self) -> bool:
        return self.type == "Spell"

    @property
    def is_ability(self) -> bool:
        return self.type == "Ability"

    @property
    def is_equipment(self) -> bool:
        return self.type == "Equipment"

    @property
    def is_landmark(self) -> bool:
        return self.type == "Landmark"

    # --- mots-clés -----------------------------------------------------
    def has(self, keyword: str) -> bool:
        """Teste un mot-clé indifféremment sur le libellé affiché ou sur
        sa référence interne (insensible à la casse et à la ponctuation)."""
        target = _normalize_keyword(keyword)
        return any(
            _normalize_keyword(existing) == target
            for existing in (*self.keywords, *self.keyword_refs)
        )

    # --- points de saisie ----------------------------------------------
    @property
    def grab_point(self) -> tuple:
        """
        Point où attraper la carte à la souris, en coordonnées bureau.

        Voir CARD_GRAB_Y_RATIO : on vise le haut de la carte, seule partie
        garantie visible pour une carte en main.
        """
        left, top, right, bottom = self.box
        return ((left + right) // 2, int(top + CARD_GRAB_Y_RATIO * (bottom - top)))

    # --- mots-clés (suite) ----------------------------------------------
    @property
    def can_block(self) -> bool:
        return not (self.has("CantBlock") or self.has("Immobile"))

    @property
    def can_attack(self) -> bool:
        return not (self.has("CantAttack") or self.has("Immobile"))

    def __str__(self) -> str:
        # L'astérisque signale une stat lue à l'écran plutôt que déduite
        # de card_sets : indispensable pour distinguer « le bot voit un
        # 5/5 » de « le bot suppose un 5/5 » quand une décision surprend.
        mark = "*" if self.stats_are_live else ""
        suffix = "" if self.known else " (inconnue)"
        return f"{self.name} ({self.cost}) {self.attack}/{self.health}{mark}{suffix}"


# ============================================================
# CLASSIFICATION EN ZONES
# ============================================================

def zone_ratio(rect: dict, window: Window) -> float:
    """
    Position verticale normalisée d'un rectangle de l'API : 0.0 = bas de
    l'écran, 1.0 = haut. Les Y de l'API étant déjà mesurés depuis le bas,
    aucune inversion n'est nécessaire ici.
    """
    if window.height <= 0:
        return 0.0
    anchor = rect["TopLeftY"] - ZONE_ANCHOR_RATIO * rect["Height"]
    return anchor / window.height


def classify_zone(rect: dict, window: Window) -> str:
    """Zone du plateau déduite de la hauteur du rectangle."""
    ratio = zone_ratio(rect, window)
    for upper_bound, name in ZONE_BANDS:
        if ratio < upper_bound:
            return name
    return FALLBACK_ZONE


def zone_band(name: str) -> tuple:
    """
    Bornes (basse, haute) d'une zone, en ratio depuis le BAS de l'écran.
    Lève KeyError si la zone n'existe pas.
    """
    low = 0.0
    for upper_bound, zone in ZONE_BANDS:
        if zone == name:
            return (low, upper_bound)
        low = upper_bound
    if name == FALLBACK_ZONE:
        return (low, 1.0)
    raise KeyError(name)


def zone_center_from_top(name: str) -> float:
    """
    Milieu d'une zone, exprimé en ratio depuis le HAUT (convention écran).

    Sert à viser une zone à la souris. Le calculer à partir de ZONE_BANDS
    plutôt que d'écrire la valeur en dur garantit que le point visé et le
    classement des cartes ne peuvent pas diverger : retoucher une bande
    déplace automatiquement la cible.
    """
    low, high = zone_band(name)
    return 1.0 - (low + high) / 2


def empty_zones() -> dict:
    """Dict zone -> tuple vide, avec TOUTES les clés présentes, pour que
    l'appelant puisse faire zones["attack"] sans jamais se faire un KeyError."""
    return {name: () for name in ZONE_ORDER}


def group_by_zone(cards: Iterable[BoardCard]) -> dict:
    """Regroupe les cartes par zone, chaque zone triée de gauche à droite."""
    buckets = {name: [] for name in ZONE_ORDER}
    for card in cards:
        buckets.setdefault(card.zone, []).append(card)
    return {
        name: tuple(sorted(items, key=lambda c: c.center[0]))
        for name, items in buckets.items()
    }


# ============================================================
# VISION
# ============================================================

def _mask_pixel_count(
    screen: np.ndarray, window: Window, region: tuple, hsv_range: tuple
) -> tuple:
    """
    Compte les pixels d'une zone qui tombent dans un intervalle HSV.
    Renvoie (pixels_retenus, pixels_total) ; (0, 0) si la zone est hors cadre.
    """
    crop = lor_api.crop_box(screen, window.rel_box(region))
    if crop is None or crop.size == 0:
        return 0, 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    low, high = hsv_range
    mask = cv2.inRange(hsv, np.array(low, dtype=np.uint8), np.array(high, dtype=np.uint8))
    return int(cv2.countNonZero(mask)), int(mask.size)


def turn_orb_is_active(screen: np.ndarray, window: Window) -> bool:
    """
    True si l'orbe de fin de tour est colorée (bleue) : c'est à nous
    d'agir. Grise = l'adversaire joue, ou une animation est en cours.
    """
    count, _ = _mask_pixel_count(screen, window, TURN_ORB_REGION, TURN_ORB_HSV)
    return count >= TURN_ORB_MIN_PX


# --- jeton d'attaque : correspondance de forme -------------------------

# Cache indexé sur (chemin, date de modification) : régénérer le template
# avec `cut-token` le recharge automatiquement, sans relancer le bot.
_TEMPLATE_CACHE: dict = {}


def load_template(path) -> Optional[np.ndarray]:
    """Charge un template BGR, avec cache invalidé par la date du fichier."""
    path = Path(path)
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE.clear()
        _TEMPLATE_CACHE[key] = cv2.imread(str(path))
    return _TEMPLATE_CACHE[key]


@dataclass
class TokenMatch:
    """Résultat de la recherche de l'épée."""

    found: bool
    score: float
    position: Optional[tuple] = None   # centre du match, coords bureau
    ours: Optional[bool] = None        # None si indéterminable
    template_missing: bool = False

    @property
    def side(self) -> str:
        if not self.found:
            return "-"
        if self.ours is None:
            return "?"
        return "nous" if self.ours else "adversaire"


def nexus_midline_y(rectangles: list, window: Window) -> float:
    """
    Y écran de la ligne médiane entre les deux nexus.

    C'est la frontière « notre moitié / sa moitié », et elle vient de
    l'API : elle est donc juste quelle que soit la résolution, sans
    calibration. Repli sur le milieu de la fenêtre si un nexus manque.
    """
    centres = {}
    for rect in rectangles:
        if rect.get("CardCode") == lor_api.NEXUS_CARD_CODE:
            centres[bool(rect.get("LocalPlayer"))] = lor_api.rect_center_screen(rect, window)[1]

    if True in centres and False in centres:
        return (centres[True] + centres[False]) / 2
    return window.y + window.height / 2


def find_attack_token(
    screen: np.ndarray,
    window: Window,
    midline_y: Optional[float] = None,
    threshold: float = ATTACK_TOKEN_MATCH_THRESHOLD,
    region: tuple = ATTACK_TOKEN_SEARCH_REGION,
    template_path=ATTACK_TOKEN_TEMPLATE,
) -> TokenMatch:
    """
    Cherche l'icône d'épée par correspondance de forme.

    Renvoie toujours le score, même en cas d'échec : c'est ce qui permet
    de régler le seuil en connaissance de cause. Un score de 0.78 quand
    le jeton est visible signifie « seuil trop haut » ; un score de 0.85
    quand il est absent signifie « template trop générique, recadre-le
    plus serré sur l'épée ».

    `ours` compare la position du match à la ligne médiane des nexus :
    notre moitié est celle du BAS, donc les Y les plus grands.
    """
    template = load_template(template_path)
    if template is None:
        return TokenMatch(found=False, score=0.0, template_missing=True)

    box = window.rel_box(region)
    crop = lor_api.crop_box(screen, box)
    if crop is None:
        LOGGER.warning("Région de recherche du jeton hors cadre : %s", box)
        return TokenMatch(found=False, score=0.0)

    t_h, t_w = template.shape[:2]
    c_h, c_w = crop.shape[:2]
    if t_h > c_h or t_w > c_w:
        LOGGER.warning(
            "Template (%dx%d) plus grand que la région de recherche (%dx%d) : "
            "élargis ATTACK_TOKEN_SEARCH_REGION ou recadre le template.",
            t_w, t_h, c_w, c_h,
        )
        return TokenMatch(found=False, score=0.0)

    result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    score = float(score)

    if score < threshold:
        return TokenMatch(found=False, score=score)

    centre = (
        box[0] + location[0] + t_w // 2,
        box[1] + location[1] + t_h // 2,
    )
    ours = None if midline_y is None else centre[1] > midline_y
    return TokenMatch(found=True, score=score, position=centre, ours=ours)


# ============================================================
# STATS RÉELLES (OCR sur les badges des cartes)
# ============================================================
# card_sets donne les stats de BASE. Une unité 3/4 buffée à 5/6, ou
# blessée à 3/1, y figure toujours comme 3/4. Décider une attaque ou un
# blocage là-dessus produit des échanges perdants qu'on ne comprend pas
# en relisant les journaux.
#
# CE N'EST PAS FAIT À CHAQUE LECTURE D'ÉTAT, ET C'EST VOLONTAIRE.
# Un appel d'OCR par badge coûte cher : une dizaine d'unités en jeu font
# une vingtaine d'appels, soit plusieurs secondes. La boucle de combat
# interroge l'état en continu — payer ce prix à chaque tour de boucle la
# rendrait inutilisable. `enrich_with_live_stats()` est donc appelée
# explicitement, juste avant les décisions qui en dépendent (attaque,
# blocage), et nulle part ailleurs.

# Décalages des badges, calibrés sur une carte de banc de 126x159 px puis
# convertis en ratios pour suivre la taille réelle de la carte.
STAT_REFERENCE_CARD = (126, 159)
ATTACK_BADGE_BOX = (17, 8, 39, 26)     # (x, y, largeur, hauteur)
HEALTH_BADGE_BOX = (74, 8, 36, 26)

# Zones où les stats réelles changent quelque chose. Inutile de lire la
# main (les stats y sont celles de base, déjà connues) ni la main adverse.
LIVE_STAT_ZONES = ("board", "attack", "enemy_board", "enemy_attack")


def _badge_ratio(box: tuple, reference: tuple = STAT_REFERENCE_CARD) -> tuple:
    x, y, width, height = box
    ref_w, ref_h = reference
    return (x / ref_w, y / ref_h, width / ref_w, height / ref_h)


ATTACK_BADGE_REL = _badge_ratio(ATTACK_BADGE_BOX)
HEALTH_BADGE_REL = _badge_ratio(HEALTH_BADGE_BOX)


def _badge_crop(screen: np.ndarray, card: "BoardCard", relative: tuple):
    left, top, right, bottom = card.box
    width, height = right - left, bottom - top
    rx, ry, rw, rh = relative
    return lor_api.crop_box(
        screen,
        (
            left + rx * width,
            top + ry * height,
            left + (rx + rw) * width,
            top + (ry + rh) * height,
        ),
    )


def enrich_with_live_stats(
    snapshot: "GameSnapshot",
    screen: Optional[np.ndarray] = None,
    zones: tuple = LIVE_STAT_ZONES,
) -> "GameSnapshot":
    """
    Remplit `attack_read` / `health_read` des unités en jeu par OCR.

    Modifie l'instantané sur place et le renvoie. Une lecture qui échoue
    laisse la valeur à None, et la carte retombe alors sur sa stat de
    base : dégradation silencieuse plutôt qu'exception, parce qu'un badge
    illisible ne doit pas interrompre un combat.
    """
    try:
        from detect_chiffres import ocr_number
    except Exception as exc:
        LOGGER.warning(
            "OCR des stats indisponible (%s) : on reste sur les stats de base.", exc
        )
        return snapshot

    if screen is None:
        screen = lor_api.capture_screen_bgr()

    for zone in zones:
        for card in snapshot.zones.get(zone, ()):
            if not card.is_unit:
                continue
            card.attack_read = ocr_number(
                _badge_crop(screen, card, ATTACK_BADGE_REL), name=f"{card.code}_atk"
            )
            card.health_read = ocr_number(
                _badge_crop(screen, card, HEALTH_BADGE_REL), name=f"{card.code}_hp"
            )

    return snapshot


# ============================================================
# INSTANTANÉ DE PARTIE
# ============================================================

@dataclass
class GameSnapshot:
    """Photographie complète et cohérente de l'état de la partie."""

    phase: Phase
    window: Window
    zones: dict = field(default_factory=empty_zones)
    turn_orb_active: Optional[bool] = None
    attack_token: Optional[bool] = None
    token_match: Optional["TokenMatch"] = None
    api_state: str = ""
    game_id: Optional[int] = None
    last_game_won: Optional[bool] = None
    unknown_codes: tuple = ()

    # --- accès aux zones ----------------------------------------------
    @property
    def hand(self) -> tuple:
        return self.zones.get("hand", ())

    @property
    def board(self) -> tuple:
        return self.zones.get("board", ())

    @property
    def attack_row(self) -> tuple:
        return self.zones.get("attack", ())

    @property
    def stack(self) -> tuple:
        return self.zones.get("stack", ())

    @property
    def enemy_attack_row(self) -> tuple:
        return self.zones.get("enemy_attack", ())

    @property
    def enemy_board(self) -> tuple:
        return self.zones.get("enemy_board", ())

    @property
    def enemy_hand(self) -> tuple:
        return self.zones.get("enemy_hand", ())

    def cards(self, *zones: str) -> tuple:
        """Toutes les cartes des zones demandées (toutes zones si aucune)."""
        wanted = zones or ZONE_ORDER
        return tuple(card for name in wanted for card in self.zones.get(name, ()))

    # --- affichage ----------------------------------------------------
    def summary(self) -> str:
        def flag(value):
            return "?" if value is None else ("oui" if value else "non")

        # Le score du match est affiché en permanence : c'est lui qui dit
        # s'il faut bouger le seuil, et il est inutile une fois la partie
        # finie.
        token = f"jeton={flag(self.attack_token)}"
        if self.token_match is not None:
            if self.token_match.template_missing:
                token = "jeton=template_absent"
            else:
                token += (
                    f" (score {self.token_match.score:.2f}"
                    f" cote {self.token_match.side})"
                )

        lines = [
            f"[{self.phase.name}] api={self.api_state or '-'} "
            f"orbe={flag(self.turn_orb_active)} {token}"
        ]
        for name in ZONE_ORDER:
            cards = self.zones.get(name, ())
            if cards:
                lines.append(f"    {name:<13} " + " | ".join(str(c) for c in cards))
        if self.unknown_codes:
            lines.append(f"    codes absents de card_sets : {', '.join(self.unknown_codes)}")
        return "\n".join(lines)


# ============================================================
# LECTEUR D'ÉTAT
# ============================================================

class GameStateReader:
    """
    Produit des `GameSnapshot`. À instancier UNE fois et à réutiliser :
    l'objet garde en mémoire le dernier GameID vu, ce qui est nécessaire
    pour détecter une fin de partie.
    """

    def __init__(
        self,
        card_db: Optional[dict] = None,
        token_threshold: float = ATTACK_TOKEN_MATCH_THRESHOLD,
        token_template=ATTACK_TOKEN_TEMPLATE,
    ):
        self.card_db = card_db if card_db is not None else lor_api.load_card_db()
        self.token_threshold = token_threshold
        self.token_template = token_template
        self._warned_template = False
        self._last_game_id: Optional[int] = None
        self._last_game_won: Optional[bool] = None
        self._warned_codes: set = set()

    # --- construction des cartes --------------------------------------
    def _build_cards(self, rectangles: list, window: Window) -> tuple:
        cards, unknown = [], []

        for rect in rectangles:
            code = rect.get("CardCode")
            if not code or code == lor_api.NEXUS_CARD_CODE:
                continue

            info = self.card_db.get(code)
            known = info is not None
            if not known:
                info = {}
                unknown.append(code)
                if code not in self._warned_codes:
                    self._warned_codes.add(code)
                    LOGGER.warning(
                        "Carte %s absente de card_sets : conservée avec des "
                        "stats à 0 plutôt qu'ignorée, pour ne pas raisonner "
                        "sur un plateau incomplet.", code
                    )

            zone = classify_zone(rect, window)
            cards.append(
                BoardCard(
                    card_id=rect.get("CardID", -1),
                    code=code,
                    name=info.get("name") or code,
                    cost=info.get("cost") or 0,
                    base_attack=info.get("attack") or 0,
                    base_health=info.get("health") or 0,
                    type=info.get("type") or "",
                    keywords=tuple(info.get("keywords") or ()),
                    keyword_refs=tuple(info.get("keywordRefs") or ()),
                    description=info.get("descriptionRaw") or "",
                    local=bool(rect.get("LocalPlayer")),
                    zone=zone,
                    ratio=zone_ratio(rect, window),
                    box=lor_api.rect_to_screen_box(rect, window),
                    center=lor_api.rect_center_screen(rect, window),
                    known=known,
                )
            )

        return cards, tuple(dict.fromkeys(unknown))

    # --- fin de partie -------------------------------------------------
    def _poll_game_result(self) -> tuple:
        """
        Renvoie (game_id, partie_vient_de_finir).

        `/game-result` décrit la dernière partie TERMINÉE : son GameID
        n'augmente qu'au moment où une partie se conclut. La toute
        première lecture ne déclenche donc rien — sinon le bot croirait
        qu'une partie vient de finir à chaque démarrage.
        """
        try:
            result = lor_api.get_game_result()
        except ApiUnavailable:
            return self._last_game_id, False

        if not result or result.get("GameID") is None:
            return self._last_game_id, False

        game_id = int(result["GameID"])
        won = bool(result.get("LocalPlayerWon"))

        if self._last_game_id is None:
            self._last_game_id = game_id
            self._last_game_won = won
            return game_id, False

        if game_id > self._last_game_id:
            self._last_game_id = game_id
            self._last_game_won = won
            return game_id, True

        return game_id, False

    # --- mulligan ------------------------------------------------------
    @staticmethod
    def _looks_like_mulligan(cards: list) -> bool:
        local = [c for c in cards if c.local]
        if len(local) < MULLIGAN_MIN_CARDS:
            return False

        # Toutes nos cartes à la même hauteur, au milieu de l'écran.
        ratios = [c.ratio for c in local]
        if max(ratios) - min(ratios) > MULLIGAN_MAX_SPREAD:
            return False

        middle = sum(ratios) / len(ratios)
        if not MULLIGAN_BAND[0] <= middle <= MULLIGAN_BAND[1]:
            return False

        # ATTENTION : les cartes de mulligan tombent elles-mêmes dans la
        # bande `enemy_attack` (elles sont au centre de l'écran). Le test
        # de plateau vide doit donc porter sur NOS zones pour nos cartes
        # et sur les zones adverses pour les leurs — sinon la condition
        # s'auto-invalide et le mulligan n'est jamais reconnu.
        if any(c.local and c.zone in ("board", "attack") for c in cards):
            return False
        if any(not c.local and c.zone in ("enemy_board", "enemy_attack") for c in cards):
            return False

        return True

    # --- instantané ----------------------------------------------------
    def snapshot(self) -> GameSnapshot:
        """Lit l'API, capture l'écran si nécessaire, et déduit la phase."""
        try:
            api_data = lor_api.get_positional_rectangles()
        except ApiUnavailable as exc:
            LOGGER.debug("API indisponible : %s", exc)
            return GameSnapshot(phase=Phase.NO_API, window=lor_api.get_window())

        window = lor_api.get_window(api_data)
        api_state = api_data.get("GameState") or ""
        rectangles = api_data.get("Rectangles") or []

        cards, unknown = self._build_cards(rectangles, window)
        zones = group_by_zone(cards)
        game_id, just_finished = self._poll_game_result()

        base = dict(
            window=window,
            zones=zones,
            api_state=api_state,
            game_id=game_id,
            last_game_won=self._last_game_won,
            unknown_codes=unknown,
        )

        # La fin de partie prime sur tout le reste : c'est un événement,
        # et il n'est émis qu'une seule fois par partie.
        if just_finished:
            return GameSnapshot(phase=Phase.GAME_OVER, **base)

        if api_state != "InProgress":
            return GameSnapshot(phase=Phase.MENUS, **base)

        # Le mulligan se reconnaît sans vision : l'orbe peut être grise
        # pendant cet écran, donc le test doit venir AVANT.
        if self._looks_like_mulligan(cards):
            return GameSnapshot(phase=Phase.MULLIGAN, **base)

        screen = lor_api.capture_screen_bgr()
        orb_active = turn_orb_is_active(screen, window)
        base["turn_orb_active"] = orb_active

        # Le jeton est évalué dans TOUTES les phases de partie, et pas
        # seulement là où il départage ATTACK_TURN et DEFEND_TURN.
        #
        # Rappel de règle : le jeton signifie « ce round est mon round
        # d'attaque », pas « je suis en train d'attaquer ». Il alterne à
        # chaque round quoi qu'on fasse. Le savoir pendant le tour adverse
        # ou pendant un blocage reste utile, et ça évite un « jeton=? »
        # permanent dans `monitor` — c'est-à-dire une information
        # manquante exactement là où on veut la vérifier.
        match = find_attack_token(
            screen,
            window,
            midline_y=nexus_midline_y(rectangles, window),
            threshold=self.token_threshold,
            template_path=self.token_template,
        )
        base["token_match"] = match
        base["attack_token"] = None if match.template_missing else bool(
            match.found and match.ours is not False
        )

        if match.template_missing and not self._warned_template:
            self._warned_template = True
            LOGGER.warning(
                "Template du jeton absent (%s) : la phase reste OUR_TURN au "
                "lieu de trancher ATTACK/DEFEND. Génère-le avec "
                "`python game_state.py snap avec` puis `cut-token`.",
                self.token_template,
            )

        if not orb_active:
            return GameSnapshot(phase=Phase.OPPONENT_TURN, **base)

        # Notre rangée d'attaque occupée => c'est NOUS qui attaquons,
        # les cartes adverses en face sont des bloqueurs, pas une attaque.
        if zones["attack"]:
            return GameSnapshot(phase=Phase.ATTACKING, **base)

        if zones["enemy_attack"]:
            return GameSnapshot(phase=Phase.BLOCKING, **base)

        if zones["stack"]:
            return GameSnapshot(phase=Phase.SPELL_STACK, **base)

        # Sans template, on ne PEUT pas trancher : renvoyer DEFEND_TURN
        # serait une affirmation fausse déguisée en information. OUR_TURN
        # dit honnêtement « à toi de jouer, jeton inconnu ».
        if match.template_missing:
            return GameSnapshot(phase=Phase.OUR_TURN, **base)

        return GameSnapshot(
            phase=Phase.ATTACK_TURN if base["attack_token"] else Phase.DEFEND_TURN,
            **base,
        )

    # --- lectures stabilisées -----------------------------------------
    def stable_snapshot(
        self, confirmations: int = 2, poll: float = 0.6, timeout: float = 12.0
    ) -> GameSnapshot:
        """
        Attend que la même phase soit lue `confirmations` fois de suite
        avant de la renvoyer.

        Indispensable avant toute action : les animations (pioche, pose
        de carte, résolution de combat) déplacent les cartes entre les
        bandes pendant une seconde ou deux, et une lecture isolée pendant
        ce laps de temps donne une phase fausse. Au bout de `timeout`, on
        renvoie la dernière lecture telle quelle plutôt que de bloquer.
        """
        deadline = time.time() + timeout
        streak, snap = 0, self.snapshot()
        previous = snap.phase

        while True:
            streak = streak + 1 if snap.phase is previous else 1
            if streak >= max(1, confirmations):
                return snap
            if time.time() >= deadline:
                LOGGER.debug("Phase instable après %.1fs, on renvoie %s", timeout, snap.phase.name)
                return snap
            previous = snap.phase
            time.sleep(poll)
            snap = self.snapshot()

# ============================================================
# CLI — surveillance et calibration
# ============================================================

def cmd_monitor(interval: float) -> None:
    """Affiche la phase et le plateau en boucle. Ctrl+C pour arrêter."""
    reader = GameStateReader()
    print("Surveillance en cours — Ctrl+C pour arrêter.\n")
    last = None
    while True:
        snap = reader.snapshot()
        changed = snap.phase is not last
        marker = ">>" if changed else "  "
        print(f"{marker} {time.strftime('%H:%M:%S')} {snap.summary()}")
        last = snap.phase
        time.sleep(interval)


def cmd_inspect() -> None:
    """
    Tableau de tous les rectangles renvoyés par l'API, avec le ratio
    calculé et la zone déduite. C'est l'outil pour valider ZONE_BANDS :
    lance-le pendant un combat, et vérifie que chaque carte tombe dans
    la bonne colonne. Si une zone est décalée, ajuste la borne
    correspondante dans ZONE_BANDS.
    """
    try:
        api_data = lor_api.get_positional_rectangles()
    except ApiUnavailable as exc:
        print(f"API injoignable : {exc}")
        return

    window = lor_api.get_window(api_data)
    card_db = lor_api.load_card_db()
    rectangles = api_data.get("Rectangles") or []

    print(f"GameState : {api_data.get('GameState')}")
    print(f"Fenêtre   : {window}")
    print(f"Screen API: {api_data.get('Screen')}")
    print(f"{len(rectangles)} rectangles\n")

    header = f"{'code':<10} {'nom':<26} {'moi':<4} {'Y':>6} {'H':>5} {'ratio':>7}  zone"
    print(header)
    print("-" * len(header))

    for rect in sorted(rectangles, key=lambda r: -r.get("TopLeftY", 0)):
        code = rect.get("CardCode", "?")
        if code == lor_api.NEXUS_CARD_CODE:
            name, zone, ratio = "(nexus)", "-", zone_ratio(rect, window)
        else:
            name = (card_db.get(code) or {}).get("name", "?")
            zone = classify_zone(rect, window)
            ratio = zone_ratio(rect, window)
        print(
            f"{code:<10} {name[:26]:<26} "
            f"{'oui' if rect.get('LocalPlayer') else 'non':<4} "
            f"{rect.get('TopLeftY', 0):>6} {rect.get('Height', 0):>5} "
            f"{ratio:>7.3f}  {zone}"
        )

    print("\nBornes actuelles (ratio depuis le bas) :")
    low = 0.0
    for upper, name in ZONE_BANDS:
        print(f"    {name:<13} {low:.3f} -> {upper:.3f}")
        low = upper
    print(f"    {FALLBACK_ZONE:<13} {low:.3f} -> 1.000")


def cmd_vision(output_dir: str) -> None:
    """
    Exporte les deux zones de vision et leurs masques HSV, et surtout
    indique QUEL critère écarte les pixels.

    C'est la colonne « H seule » qu'il faut regarder en premier : si elle
    est énorme et que « H+S » s'effondre, c'est que la teinte attrape le
    décor doré et que seule la saturation fait le tri. Si « H+S+V » est
    non nul alors que tu ne vois pas l'élément à l'écran, la région pointe
    au mauvais endroit : refais `snap` puis `cut-token`.
    """
    from pathlib import Path

    try:
        api_data = lor_api.get_positional_rectangles()
    except ApiUnavailable:
        api_data = None

    window = lor_api.get_window(api_data)
    screen = lor_api.capture_screen_bgr()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Le jeton n'est plus ici : il est cherché par forme, pas par couleur.
    # Pour le diagnostiquer, `monitor` affiche son score de matching.
    targets = (
        ("orbe_de_tour", TURN_ORB_REGION, TURN_ORB_HSV, TURN_ORB_MIN_PX),
    )

    print(f"Fenêtre : {window}\n")
    for label, region, hsv_range, min_px in targets:
        box = window.rel_box(region)
        crop = lor_api.crop_box(screen, box)
        if crop is None:
            print(f"{label:<15} zone hors cadre {box}")
            continue

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        (h_lo, s_lo, v_lo), (h_hi, s_hi, v_hi) = hsv_range
        hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

        # Décomposition du filtre, pour voir lequel des trois critères
        # fait réellement le travail.
        m_h = (hue >= h_lo) & (hue <= h_hi)
        m_hs = m_h & (sat >= s_lo) & (sat <= s_hi)
        m_hsv = m_hs & (val >= v_lo) & (val <= v_hi)

        mask = (m_hsv * 255).astype(np.uint8)
        count = int(m_hsv.sum())
        total = hue.size

        cv2.imwrite(str(out / f"{label}_zone.png"), crop)
        cv2.imwrite(str(out / f"{label}_masque.png"), mask)

        verdict = "DÉTECTÉ" if count >= min_px else "absent"
        print(f"{label}  box={box}  seuil={min_px} px  -> {verdict}")
        print(f"    H seule   {int(m_h.sum()):>7} px ({100 * m_h.sum() / total:5.1f} %)")
        print(f"    H+S       {int(m_hs.sum()):>7} px ({100 * m_hs.sum() / total:5.1f} %)")
        print(f"    H+S+V     {count:>7} px ({100 * count / total:5.1f} %)")
        if m_hsv.any():
            print(
                f"    retenus   H {int(hue[m_hsv].min())}-{int(hue[m_hsv].max())}  "
                f"S {int(sat[m_hsv].min())}-{int(sat[m_hsv].max())}  "
                f"V {int(val[m_hsv].min())}-{int(val[m_hsv].max())}"
            )
        print()

    print(f"Crops exportés dans {out.resolve()}")

    # Diagnostic du jeton dans la même passe : c'est le score qui compte.
    match = find_attack_token(
        screen, window, midline_y=nexus_midline_y(
            (api_data or {}).get("Rectangles") or [], window
        )
    )
    print()
    if match.template_missing:
        print(f"jeton_attaque  template absent : {ATTACK_TOKEN_TEMPLATE}")
        print("               `snap avec` puis `cut-token` pour le générer.")
    else:
        print(
            f"jeton_attaque  score={match.score:.3f} "
            f"seuil={ATTACK_TOKEN_MATCH_THRESHOLD}  "
            f"-> {'TROUVÉ' if match.found else 'absent'}  côté {match.side}"
        )
        if match.position:
            print(f"               position {match.position}")


def _select_box_tk(image: np.ndarray, max_width: int) -> Optional[tuple]:
    """
    Sélecteur de zone en Tkinter.

    On n'utilise PAS cv2.selectROI : easyocr installe
    `opencv-python-headless`, une build d'OpenCV compilée SANS interface
    graphique, qui écrase la build normale. Toute fonction de fenêtrage
    d'OpenCV (imshow, selectROI, destroyAllWindows) lève alors « The
    function is not implemented ». Tkinter est dans la bibliothèque
    standard et ne dépend pas d'OpenCV, donc ce chemin marche quel que
    soit le paquet cv2 installé.

    Renvoie (x, y, largeur, hauteur) en pixels PLEINE RÉSOLUTION, ou None.
    """
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError as exc:
        print(f"Sélection interactive indisponible ({exc}).")
        return None

    height, width = image.shape[:2]
    scale = min(1.0, max_width / width)
    display = (
        cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else image
    )
    rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)

    state = {"start": None, "box": None, "rect": None}

    root = tk.Tk()
    root.title("Entoure l'epee — ENTREE pour valider, ECHAP pour annuler")
    photo = ImageTk.PhotoImage(Image.fromarray(rgb))
    canvas = tk.Canvas(root, width=photo.width(), height=photo.height(), highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=photo)
    label = tk.Label(root, text="Clique-glisse autour de l'épée.")
    label.pack(fill="x")

    def on_press(event):
        state["start"] = (event.x, event.y)
        if state["rect"] is not None:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#00ff00", width=2
        )

    def on_drag(event):
        if state["start"] is None:
            return
        x0, y0 = state["start"]
        canvas.coords(state["rect"], x0, y0, event.x, event.y)
        state["box"] = (min(x0, event.x), min(y0, event.y),
                        abs(event.x - x0), abs(event.y - y0))
        bx, by, bw, bh = state["box"]
        label.config(
            text=f"Sélection {int(bw / scale)}x{int(bh / scale)} px "
                 f"en ({int(bx / scale)}, {int(by / scale)}) — ENTRÉE pour valider"
        )

    def validate(_=None):
        root.quit()

    def cancel(_=None):
        state["box"] = None
        root.quit()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_drag)
    root.bind("<Return>", validate)
    root.bind("<KP_Enter>", validate)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    root.destroy()

    if not state["box"] or state["box"][2] < 3 or state["box"][3] < 3:
        return None

    x, y, w, h = state["box"]
    return (int(x / scale), int(y / scale), int(w / scale), int(h / scale))


def _tighten_to_icon(crop: np.ndarray, value_floor: int = 90,
                     margin: int = 2, max_coverage: float = 0.80) -> Optional[tuple]:
    """
    Resserre une sélection approximative sur l'icône qu'elle contient.

    LE SEUIL EST CALCULÉ, PAS DEVINÉ. Un plancher de saturation en dur ne
    peut pas marcher : la saturation du décor de LoR varie selon la zone
    du plateau et la luminosité, et une valeur choisie à l'avance est soit
    trop basse (tout le décor est retenu, le resserrage ne resserre rien)
    soit trop haute (l'icône elle-même disparaît). Otsu trouve la
    séparation naturelle entre les deux populations de pixels PRÉSENTES
    DANS LA SÉLECTION, ce qui est exactement la question posée.

    Ce n'est pas le test qui décidera plus tard si l'épée est là — c'est
    seulement un moyen de recadrer proprement, sur une zone que l'humain
    a déjà désignée. Le risque d'erreur est donc borné.

    Renvoie (x, y, largeur, hauteur) relatifs au crop, ou None si aucune
    séparation nette n'apparaît.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]

    _, mask = cv2.threshold(saturation, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_and(mask, ((value >= value_floor) * 255).astype(np.uint8))

    area = int(np.count_nonzero(mask))
    if area == 0 or area > max_coverage * mask.size:
        # Pas de séparation nette : soit la sélection est uniforme, soit
        # elle est entièrement « saturée ». Dans les deux cas, resserrer
        # serait arbitraire — on préfère ne rien faire et le dire.
        return None

    # La plus grande composante connexe, et non l'étendue de tous les
    # pixels retenus : un reflet isolé dans un coin de la sélection
    # élargirait la boîte jusqu'à lui.
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return None
    biggest = max(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA])

    height, width = crop.shape[:2]
    x = int(stats[biggest, cv2.CC_STAT_LEFT])
    y = int(stats[biggest, cv2.CC_STAT_TOP])
    w = int(stats[biggest, cv2.CC_STAT_WIDTH])
    h = int(stats[biggest, cv2.CC_STAT_HEIGHT])

    x1, y1 = max(0, x - margin), max(0, y - margin)
    x2, y2 = min(width, x + w + margin), min(height, y + h + margin)
    return (x1, y1, x2 - x1, y2 - y1)


def cmd_cut_token(source: str, output_path: str, max_width: int,
                  box: Optional[list] = None, tighten: bool = True) -> None:
    """
    Découpe le template de l'épée dans une capture.

    Deux façons de désigner la zone :
        - à la souris (fenêtre Tkinter), par défaut ;
        - avec --box X Y LARGEUR HAUTEUR, si l'affichage n'est pas
          disponible ou pour ajuster au pixel.

    Le cadrage doit être SERRÉ sur l'icône : un template qui embarque du
    décor matche moins bien dès que le fond change, et un template trop
    générique matche n'importe quoi. Il faut aussi éviter le halo
    pulsant, dont l'intensité varie d'une frame à l'autre. Comme c'est
    difficile à faire à la souris, une sélection approximative est
    resserrée automatiquement sur les pixels saturés (--no-tighten pour
    désactiver).
    """
    src = Path(source)
    if not src.exists():
        print(f"Capture introuvable : {src}")
        print("Lance d'abord `python game_state.py snap avec` en tenant le jeton.")
        return

    image = cv2.imread(str(src))
    if image is None:
        print(f"Capture illisible : {src}")
        return

    height, width = image.shape[:2]

    if box:
        x, y, w, h = (int(v) for v in box)
    else:
        print("Une fenêtre va s'ouvrir : entoure l'épée, puis ENTRÉE (ÉCHAP pour annuler).")
        selection = _select_box_tk(image, max_width)
        if selection is None:
            print("\nSélection annulée ou impossible.")
            print("Solution de repli, sans affichage :")
            print("    python game_state.py cut-token --box X Y LARGEUR HAUTEUR")
            print(f"La capture fait {width}x{height} px.")
            return
        x, y, w, h = selection

    # Bornage : une saisie manuelle hors cadre donnerait un crop vide.
    x, y = max(0, min(x, width - 1)), max(0, min(y, height - 1))
    w, h = max(1, min(w, width - x)), max(1, min(h, height - y))
    crop = image[y:y + h, x:x + w]

    if tighten:
        inner = _tighten_to_icon(crop)
        if inner is None:
            print("Pas de séparation nette icône/décor : sélection gardée telle quelle.")
            print("Si le template embarque du décor, recadre à la main avec --box.")
        elif inner[2] < 6 or inner[3] < 6:
            print(f"Resserrage ignoré : résultat trop petit ({inner[2]}x{inner[3]} px).")
        elif (inner[0], inner[1], inner[2], inner[3]) == (0, 0, w, h):
            print(f"Sélection déjà serrée ({w}x{h} px), aucun resserrage nécessaire.")
        else:
            ix, iy, iw, ih = inner
            print(f"Sélection {w}x{h} resserrée en {iw}x{ih} px sur l'icône.")
            x, y, w, h = x + ix, y + iy, iw, ih
            crop = image[y:y + h, x:x + w]

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(destination), crop)

    # Aperçu agrandi : à 20x20 px le template est illisible à l'œil, et
    # c'est pourtant la seule façon de voir qu'on a attrapé du décor.
    zoom = max(1, 160 // max(w, h))
    if zoom > 1:
        preview_path = destination.with_name(destination.stem + "_apercu.png")
        cv2.imwrite(
            str(preview_path),
            cv2.resize(crop, (w * zoom, h * zoom), interpolation=cv2.INTER_NEAREST),
        )
        print(f"Aperçu agrandi x{zoom} : {preview_path.resolve()}")

    print(f"\nTemplate écrit : {destination.resolve()}  ({w}x{h} px, box {x} {y} {w} {h})")

    # Région de recherche suggérée : large en hauteur pour couvrir les
    # deux moitiés du plateau, resserrée en largeur autour de la colonne
    # où se trouve l'épée.
    window = lor_api.get_window()
    centre_x = x + w / 2
    half_width = max(w * 3, int(window.width * 0.10))
    rx1 = max(0, centre_x - half_width) / window.width
    rx2 = min(window.width, centre_x + half_width) / window.width
    print(
        "\nRégion de recherche suggérée (ATTACK_TOKEN_SEARCH_REGION) :\n"
        f"    (({rx1:.4f}, 0.1800), ({rx2:.4f}, 0.9200))"
    )
    print(
        "\nVérifie ensuite avec :\n"
        "    python game_state.py vision      # score du matching\n"
        "    python game_state.py monitor     # le score doit chuter au round suivant"
    )


def cmd_snap(label: str, output_dir: str) -> None:
    """
    Capture l'écran complet sous un nom donné.

        python game_state.py snap avec    # pendant que tu AS le jeton
        python game_state.py cut-token    # découpe l'épée dedans
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ecran_{label}.png"

    screen = lor_api.capture_screen_bgr()
    cv2.imwrite(str(path), screen)

    window = lor_api.get_window()
    print(f"Écran capturé : {path.resolve()}")
    print(f"Fenêtre       : {window}")
    print(f"Taille        : {screen.shape[1]}x{screen.shape[0]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lecture de l'état de partie Legends of Runeterra."
    )
    sub = parser.add_subparsers(dest="command")

    monitor = sub.add_parser("monitor", help="surveille la phase en direct")
    monitor.add_argument("--interval", type=float, default=1.0)

    sub.add_parser("inspect", help="tableau des rectangles et des zones déduites")

    vision = sub.add_parser("vision", help="exporte les crops de calibration couleur")
    vision.add_argument("--output", default="calibration_crops")

    snap = sub.add_parser("snap", help="capture l'écran complet sous un nom")
    snap.add_argument("label", help="nom de la capture, ex. avec / sans")
    snap.add_argument("--output", default="calibration_crops")

    cut = sub.add_parser("cut-token", help="découpe le template de l'épée à la souris")
    cut.add_argument("--source", default="calibration_crops/ecran_avec.png",
                     help="capture dans laquelle découper")
    cut.add_argument("--output", default=str(ATTACK_TOKEN_TEMPLATE),
                     help="chemin du template à écrire")
    cut.add_argument("--max-width", type=int, default=1400,
                     help="largeur max de l'aperçu de sélection")
    cut.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "LARGEUR", "HAUTEUR"),
                     help="zone à découper, sans passer par la souris")
    cut.add_argument("--no-tighten", action="store_true",
                     help="ne pas resserrer la sélection sur les pixels saturés")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.command == "inspect":
        cmd_inspect()
    elif args.command == "vision":
        cmd_vision(args.output)
    elif args.command == "snap":
        cmd_snap(args.label, args.output)
    elif args.command == "cut-token":
        cmd_cut_token(args.source, args.output, args.max_width,
                      box=args.box, tighten=not args.no_tighten)
    else:
        try:
            cmd_monitor(getattr(args, "interval", 1.0))
        except KeyboardInterrupt:
            print("\nArrêt.")


if __name__ == "__main__":
    main()
