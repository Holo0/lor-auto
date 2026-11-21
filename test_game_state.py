#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_game_state.py

Tests de la détection de phase et du classement en zones, SANS le jeu.

Toutes les entrées sont simulées : réponses de l'API fabriquées à la
main, écran synthétique peint en bleu ou en orange pour piloter les
tests de vision. On peut donc vérifier la logique de décision (y compris
les cas tordus : mulligan vs main alignée, « je bloque » vs « j'ai
attaqué ») sans lancer Legends of Runeterra.

    python test_game_state.py

Tourne aussi sans pyautogui (environnement sans écran) : le module est
alors remplacé par un bouchon.
"""

from __future__ import annotations

import sys
import types

# --- bouchon pyautogui pour pouvoir tourner sans écran ------------------
try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:  # ImportError, ou erreur d'accès à l'affichage
    stub = types.ModuleType("pyautogui")
    stub.size = lambda: (1920, 1080)
    stub.screenshot = lambda *a, **k: None
    sys.modules["pyautogui"] = stub

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

import lor_api
import game_state
import sortie_utf8
from game_state import (
    TURN_ORB_REGION,
    ZONE_ANCHOR_RATIO,
    GameStateReader,
    Phase,
    classify_zone,
)
from lor_api import Window

WINDOW = Window(0, 0, 1920, 1080)

# ------------------------------------------------------------
# ISOLATION VIS-À-VIS DE calibration.json
# ------------------------------------------------------------
# Les tests fabriquent leurs instantanés dans la géométrie d'ORIGINE des
# bandes de zones, et n'ont aucune calibration à eux. Or tout le code lit
# `lor_api.PROJECT_ROOT / "calibration.json"` au moment de l'appel : dès
# qu'une vraie calibration existe sur la machine, elle s'invite dans les
# tests. `zone_nexus_reference` transpose alors les bandes vers la
# géométrie du vrai plateau — les cartes tombent dans la mauvaise zone —
# et `nexus_health_relative` fait partir l'OCR pour de bon.
#
# Résultat : une suite verte sur une machine fraîche et rouge sur celle
# d'Ewan, pour une raison qui n'a rien à voir avec le code testé. On
# pointe donc la racine du projet sur un dossier vide, ce qui neutralise
# d'un coup TOUTES les clés de calibration, y compris celles à venir.
# Les tests qui portent sur une calibration précise la posent eux-mêmes.
CALIBRATION_SANDBOX = Path(tempfile.mkdtemp(prefix="lor-tests-"))
lor_api.PROJECT_ROOT = CALIBRATION_SANDBOX

TMP = Path(tempfile.gettempdir())
TOKEN_TEMPLATE = TMP / "faux_jeton_lor.png"
TOKEN_ABSENT = TMP / "jeton_qui_nexiste_pas.png"

CARD_DB = {
    "UNIT_A": {
        "name": "Garde de Fer", "cost": 3, "attack": 3, "health": 4,
        "type": "Unit", "keywords": ["Tough"], "keywordRefs": ["Tough"],
        "descriptionRaw": "",
    },
    "UNIT_B": {
        "name": "Ombre Fuyante", "cost": 2, "attack": 2, "health": 1,
        "type": "Unit", "keywords": ["Elusive", "Can't Block"],
        "keywordRefs": ["Elusive", "CantBlock"], "descriptionRaw": "",
    },
    "SPELL_A": {
        "name": "Éclair", "cost": 1, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "Deal 2 to an enemy.",
    },
}

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ============================================================
# FABRICATION DES ENTRÉES SIMULÉES
# ============================================================

def rect_at_ratio(ratio, code="UNIT_A", card_id=1, local=True, height=159, width=126, x=800):
    """
    Fabrique un rectangle d'API dont le ratio de zone vaudra exactement
    `ratio`. On inverse la formule de zone_ratio() :
        ratio = (TopLeftY - ZONE_ANCHOR_RATIO * H) / window.height
    """
    top_left_y = ratio * WINDOW.height + ZONE_ANCHOR_RATIO * height
    return {
        "CardID": card_id,
        "CardCode": code,
        "TopLeftX": x,
        "TopLeftY": int(round(top_left_y)),
        "Width": width,
        "Height": height,
        "LocalPlayer": local,
    }


def nexus_rects():
    return [
        {"CardID": -1, "CardCode": "face", "TopLeftX": 250, "TopLeftY": 200,
         "Width": 80, "Height": 80, "LocalPlayer": True},
        {"CardID": -2, "CardCode": "face", "TopLeftX": 250, "TopLeftY": 900,
         "Width": 80, "Height": 80, "LocalPlayer": False},
    ]


def build_token_template():
    """
    Fabrique un faux template d'épée : un motif TEXTURÉ, pas un aplat de
    couleur. Le but est de tester la correspondance de FORME — un template
    uni matcherait n'importe quelle zone unie et ne prouverait rien.
    """
    size = 28
    rows, cols = np.indices((size, size))
    pattern = np.zeros((size, size, 3), dtype=np.uint8)
    checker = ((rows // 4 + cols // 4) % 2).astype(bool)
    pattern[checker] = (0, 165, 255)     # orange
    pattern[~checker] = (40, 40, 40)
    pattern[size // 2 - 2:size // 2 + 2, :] = (255, 255, 255)  # barre centrale
    cv2.imwrite(str(TOKEN_TEMPLATE), pattern)
    return pattern


TOKEN_PATTERN = build_token_template()

# Positions dans la région de recherche, de part et d'autre de la ligne
# médiane des nexus (qui vaut 570 avec les nexus factices ci-dessus).
TOKEN_POS_OURS = (1400, 700)
TOKEN_POS_THEIRS = (1400, 300)


def make_screen(orb_active=True, token=None):
    """
    Écran synthétique 1920x1080 en BGR.

    Le fond est TEXTURÉ et non noir : sur un fond uni, TM_CCOEFF_NORMED
    est mal défini (variance nulle) et le test ne voudrait rien dire.

    `token` vaut None, "nous" ou "adversaire" : le motif est collé du côté
    correspondant de la ligne médiane.
    """
    rows, cols = np.indices((WINDOW.height, WINDOW.width))
    base = ((rows * 7 + cols * 13) % 64 + 40).astype(np.uint8)
    screen = np.dstack([base, (base // 2 + 30).astype(np.uint8), base])

    if orb_active:
        left, top, right, bottom = WINDOW.rel_box(TURN_ORB_REGION)
        screen[top:bottom, left:right] = (255, 0, 0)   # bleu pur en BGR

    if token is not None:
        x, y = TOKEN_POS_OURS if token == "nous" else TOKEN_POS_THEIRS
        h, w = TOKEN_PATTERN.shape[:2]
        screen[y:y + h, x:x + w] = TOKEN_PATTERN

    return screen


def install_fakes(rectangles, game_state_str="InProgress", screen=None, game_result=None,
                  decklist=None):
    """Remplace les accès au monde extérieur par des valeurs contrôlées."""
    lor_api.get_static_decklist = lambda: (
        {"DeckCode": "TEST", "CardsInDeck": decklist} if decklist else {"CardsInDeck": None}
    )
    api_payload = {
        "GameState": game_state_str,
        "Screen": {"ScreenWidth": WINDOW.width, "ScreenHeight": WINDOW.height},
        "Rectangles": rectangles,
    }
    lor_api.get_positional_rectangles = lambda: api_payload
    lor_api.get_game_result = lambda: (game_result if game_result is not None else {})
    lor_api.capture_screen_bgr = lambda: (screen if screen is not None else make_screen())
    lor_api.find_game_window = lambda title=None: None
    game_state.lor_api = lor_api


def reader(template=TOKEN_TEMPLATE):
    return GameStateReader(card_db=CARD_DB, token_template=template)


# ============================================================
# TESTS
# ============================================================

def test_coordinate_conversion():
    print("\nConversion de coordonnées API -> écran")

    # L'API mesure Y depuis le BAS : une carte à TopLeftY=1080 touche le
    # haut de l'écran, une carte à TopLeftY=159 a son bas au ras du bord.
    rect = {"TopLeftX": 800, "TopLeftY": 1080, "Width": 126, "Height": 159}
    check("bord haut -> top=0", lor_api.rect_to_screen_box(rect, WINDOW)[1] == 0,
          lor_api.rect_to_screen_box(rect, WINDOW))

    rect = {"TopLeftX": 800, "TopLeftY": 159, "Width": 126, "Height": 159}
    box = lor_api.rect_to_screen_box(rect, WINDOW)
    check("bord bas -> bottom=1080", box[3] == WINDOW.height, box)
    check("X inchangé en plein écran", box[0] == 800, box)

    centre = lor_api.rect_center_screen(rect, WINDOW)
    check("centre cohérent", centre == (863, 1000), centre)

    # Fenêtré : la fenêtre est décalée, tout doit suivre.
    windowed = Window(100, 50, 1280, 720)
    rect = {"TopLeftX": 10, "TopLeftY": 720, "Width": 100, "Height": 100}
    box = lor_api.rect_to_screen_box(rect, windowed)
    check("décalage de fenêtre appliqué", box == (110, 50, 210, 150), box)


def test_zone_bands():
    print("\nClassement en zones")
    expected = {
        0.010: "hand",
        0.150: "board",
        0.320: "attack",
        0.480: "stack",
        0.650: "enemy_attack",
        0.800: "enemy_board",
        0.950: "enemy_hand",
    }
    for ratio, zone in expected.items():
        got = classify_zone(rect_at_ratio(ratio), WINDOW)
        check(f"ratio {ratio:.3f} -> {zone}", got == zone, f"(obtenu {got})")

    # Les bandes doivent être contiguës et croissantes, sinon une carte
    # peut tomber dans un trou et disparaître du raisonnement.
    bounds = [upper for upper, _ in game_state.ZONE_BANDS]
    check("bornes strictement croissantes", bounds == sorted(set(bounds)), bounds)


def test_phase_our_turn():
    print("\nPhases de notre tour")

    hand = rect_at_ratio(0.01, code="UNIT_A", card_id=1, height=330)
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    rects = nexus_rects() + [hand, board]

    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = reader().snapshot()
    check("orbe bleue + épée côté nous -> ATTACK_TURN", snap.phase is Phase.ATTACK_TURN, snap.phase)
    check("match trouvé", snap.token_match.found is True, snap.token_match)
    check("côté identifié comme nous", snap.token_match.side == "nous", snap.token_match.side)
    check("main peuplée", len(snap.hand) == 1, snap.hand)
    check("banc peuplé", len(snap.board) == 1, snap.board)

    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    snap = reader().snapshot()
    check("pas d'épée -> DEFEND_TURN", snap.phase is Phase.DEFEND_TURN, snap.phase)
    check("score sous le seuil", snap.token_match.found is False,
          round(snap.token_match.score, 3))

    install_fakes(rects, screen=make_screen(orb_active=False, token="nous"))
    snap = reader().snapshot()
    check("orbe grise -> OPPONENT_TURN", snap.phase is Phase.OPPONENT_TURN, snap.phase)


def test_masked_token_ignores_the_background():
    """
    LE FOND DU TEMPLATE NE COMPTE PAS (02/09/2026). Le vrai template
    embarquait la gemme « 3 » de mana de sort et les rouages derrière
    l'épée : dès que le compteur n'était plus à 3, le score chutait sous
    le seuil et le bot restait en DEFEND_TURN. Avec le masque (canal
    alpha), seule l'épée est comparée : le même motif collé sur deux fonds
    différents doit matcher, et un template dont l'alpha est uniforme ne
    doit PAS être pris pour masqué.
    """
    print("\nJeton masqué : le fond n'entre pas dans le score")

    # Une « épée » : le motif texturé, dont on ne garde qu'un disque.
    h, w = TOKEN_PATTERN.shape[:2]
    rows, cols = np.indices((h, w))
    disque = (((rows - h / 2) ** 2 + (cols - w / 2) ** 2) <= (h / 2 - 2) ** 2)
    mask = np.where(disque, 255, 0).astype(np.uint8)
    masked_path = TMP / "faux_jeton_masque.png"
    cv2.imwrite(str(masked_path), np.dstack([TOKEN_PATTERN, mask]))

    loaded = game_state.load_template_with_mask(masked_path)
    check("alpha lu comme masque", loaded is not None and loaded[1] is not None)
    check("BGR à trois canaux", loaded[0].shape == (h, w, 3), loaded[0].shape)
    plain = game_state.load_template_with_mask(TOKEN_TEMPLATE)
    check("un PNG sans alpha : pas de masque", plain[1] is None)
    opaque_path = TMP / "faux_jeton_opaque.png"
    cv2.imwrite(str(opaque_path), np.dstack([TOKEN_PATTERN, np.full((h, w), 255, np.uint8)]))
    check("un alpha uniformément opaque : pas de masque",
          game_state.load_template_with_mask(opaque_path)[1] is None)

    def screen_with(fond):
        screen = make_screen(orb_active=True, token=None)
        x, y = TOKEN_POS_OURS
        roi = screen[y:y + h, x:x + w]
        roi[:] = fond                       # fond DIFFÉRENT de celui du template
        roi[disque] = TOKEN_PATTERN[disque]
        return screen

    for label, fond in (("fond noir", (0, 0, 0)), ("fond clair", (200, 220, 240)),
                        ("fond laiton", (60, 120, 170))):
        r = game_state.find_attack_token(screen_with(fond), WINDOW, midline_y=570,
                                         template_path=masked_path)
        check(f"épée trouvée sur {label}", r.found and r.ours is True,
              (round(r.score, 3), r.ours))
    r = game_state.find_attack_token(make_screen(orb_active=True, token=None), WINDOW,
                                     midline_y=570, template_path=masked_path)
    check("sans épée : rien", r.found is False, round(r.score, 3))

    # Le vrai template du dépôt porte bien un masque.
    vrai = game_state.load_template_with_mask(game_state.ATTACK_TOKEN_TEMPLATE)
    check("assets/attack_token.png est masqué", vrai is not None and vrai[1] is not None)
    if vrai is not None and vrai[1] is not None:
        couverture = float(vrai[1].mean()) / 255
        check("   masque ni vide ni plein", 0.2 < couverture < 0.8, round(couverture, 2))


def test_le_jeton_se_cherche_en_deux_etages():
    """
    LE RELEVÉ GROSSIER NE DOIT RIEN CHANGER À LA LECTURE (10/11/2026).

    Le jeton coûtait ~0,9 s par instantané — l'essentiel des 2,2 s de
    lecture d'une itération de combat — parce que le balayage des sept
    échelles se faisait en PLEINE résolution sur toute la région, et
    qu'il se déclenchait dans 68 % des lectures (celles où le jeton est
    absent). Il se fait désormais sur l'image RÉDUITE, et seuls les
    meilleurs PICS sont confirmés en pleine résolution.

    Ce test verrouille les deux côtés du marché :
      - la LECTURE est celle d'un balayage exhaustif pleine résolution,
        au score près et au pixel près, échelle ≠ 1.0 comprise ;
      - le TRAVAIL de corrélation est une fraction d'un seul balayage
        pleine résolution de la région.

    Il tourne sur le VRAI template du dépôt : un template de test de
    28 px ne serait pas réduit du tout (cf. ATTACK_TOKEN_COARSE_MIN_SIDE)
    et ne prouverait rien.
    """
    print("\nJeton : relevé grossier puis confirmation")

    charge = game_state.load_template_with_mask(game_state.ATTACK_TOKEN_TEMPLATE)
    if charge is None or charge[1] is None:
        check("assets/attack_token.png présent (sinon rien à mesurer)", False,
              game_state.ATTACK_TOKEN_TEMPLATE)
        return
    template, masque = charge

    def ecran_avec_jeton(echelle=None):
        """Le vrai template collé (masqué) sur le fond texturé."""
        screen = make_screen(orb_active=True, token=None)
        tpl, msk = template, masque
        if echelle is not None:
            taille = (int(round(template.shape[1] * echelle)),
                      int(round(template.shape[0] * echelle)))
            tpl = cv2.resize(template, taille, interpolation=cv2.INTER_AREA)
            msk = cv2.resize(masque, taille, interpolation=cv2.INTER_AREA)
        h, w = tpl.shape[:2]
        x, y = TOKEN_POS_OURS
        roi = screen[y:y + h, x:x + w]
        roi[msk > 127] = tpl[msk > 127]
        return screen

    def exhaustif(screen):
        """Ce que rendrait un balayage pleine résolution de TOUTES les échelles."""
        box = WINDOW.rel_box(game_state.ATTACK_TOKEN_SEARCH_REGION)
        crop = lor_api.crop_box(screen, box)
        best = max(
            (game_state._match_at_scale(crop, template, masque, s)
             for s in game_state.ATTACK_TOKEN_SCALES),
            key=lambda r: r[0],
        )
        score, location, (t_w, t_h), echelle = best
        return (score, (box[0] + location[0] + t_w // 2,
                        box[1] + location[1] + t_h // 2), echelle)

    for etiquette, echelle in (("à l'échelle du template", None),
                               ("agrandi de 10 %", 1.10),
                               ("réduit de 10 %", 0.90)):
        screen = ecran_avec_jeton(echelle)
        lu = game_state.find_attack_token(screen, WINDOW, midline_y=570)
        attendu_score, attendu_pos, attendu_echelle = exhaustif(screen)
        check(f"jeton {etiquette} : trouvé", lu.found is True, round(lu.score, 3))
        check("   même score que le balayage exhaustif",
              abs(lu.score - attendu_score) < 1e-6, (lu.score, attendu_score))
        check("   même position", lu.position == attendu_pos,
              (lu.position, attendu_pos))
        check("   même échelle retenue", lu.scale == attendu_echelle,
              (lu.scale, attendu_echelle))
        check("   et c'est bien notre côté", lu.ours is True, lu.ours)

    vide = make_screen(orb_active=True, token=None)
    lu = game_state.find_attack_token(vide, WINDOW, midline_y=570)
    check("sans jeton : refusé", lu.found is False, round(lu.score, 3))
    check("   et le score reste sous le seuil, loin",
          lu.score < game_state.ATTACK_TOKEN_MATCH_THRESHOLD - 0.1, round(lu.score, 3))

    # --- le travail de corrélation, compté ------------------------------
    # Un espion sur `_score_map` dit en une commande ce que la recherche
    # fait vraiment faire à OpenCV. L'unité est le travail d'une
    # corrélation : nombre de POSITIONS comparées × surface du template.
    # (Compter les pixels de l'image mènerait à l'erreur inverse : une
    # petite fenêtre de confirmation ne laisse presque aucune position.)
    # C'est le poste qui coûtait 0,9 s par instantané.
    def effort(largeur_image, hauteur_image, largeur_tpl, hauteur_tpl):
        positions = (max(0, largeur_image - largeur_tpl + 1)
                     * max(0, hauteur_image - hauteur_tpl + 1))
        return positions * largeur_tpl * hauteur_tpl

    vrai_score_map = game_state._score_map
    travail = []

    def espion(crop, tpl, msk, scale):
        t_w = max(1, int(round(tpl.shape[1] * scale)))
        t_h = max(1, int(round(tpl.shape[0] * scale)))
        travail.append(effort(crop.shape[1], crop.shape[0], t_w, t_h))
        return vrai_score_map(crop, tpl, msk, scale)

    game_state._score_map = espion
    try:
        game_state.find_attack_token(vide, WINDOW, midline_y=570)
    finally:
        game_state._score_map = vrai_score_map

    box = WINDOW.rel_box(game_state.ATTACK_TOKEN_SEARCH_REGION)
    un_balayage = effort(box[2] - box[0], box[3] - box[1],
                         template.shape[1], template.shape[0])
    check("le travail tient dans la MOITIÉ d'un balayage pleine résolution",
          sum(travail) < 0.5 * un_balayage,
          f"{sum(travail) / un_balayage:.2f} balayage(s), {len(travail)} corrélation(s)")
    check("   et aucune corrélation ne porte sur toute la région en pleine taille",
          max(travail) < 0.5 * un_balayage, round(max(travail) / un_balayage, 3))


def test_token_side_matters():
    print("\nCôté de l'épée")

    rects = nexus_rects() + [rect_at_ratio(0.15, code="UNIT_A", card_id=1)]

    # L'épée est bien trouvée, mais dans la moitié adverse : ce n'est PAS
    # notre jeton. Se contenter de « l'icône est présente » donnerait un
    # ATTACK_TURN faux un round sur deux.
    install_fakes(rects, screen=make_screen(orb_active=True, token="adversaire"))
    snap = reader().snapshot()
    check("épée côté adverse -> trouvée", snap.token_match.found is True, snap.token_match)
    check("épée côté adverse -> pas à nous", snap.token_match.ours is False, snap.token_match.ours)
    check("épée côté adverse -> DEFEND_TURN", snap.phase is Phase.DEFEND_TURN, snap.phase)

    # Ligne médiane : calculée depuis les nexus, donc sans calibration.
    midline = game_state.nexus_midline_y(nexus_rects(), WINDOW)
    check("ligne médiane entre les deux nexus", abs(midline - 570) < 1, midline)
    check("notre côté est le bas", TOKEN_POS_OURS[1] > midline > TOKEN_POS_THEIRS[1])


def test_template_missing_is_honest():
    print("\nTemplate absent")

    rects = nexus_rects() + [rect_at_ratio(0.15, code="UNIT_A", card_id=1)]
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = reader(template=TOKEN_ABSENT).snapshot()

    # Sans template, on ne peut pas trancher. Renvoyer DEFEND_TURN serait
    # une affirmation fausse déguisée en information.
    check("template absent -> OUR_TURN", snap.phase is Phase.OUR_TURN, snap.phase)
    check("jeton reste inconnu", snap.attack_token is None, snap.attack_token)
    check("cause signalée", snap.token_match.template_missing is True)
    check("OUR_TURN demande d'agir", Phase.OUR_TURN.is_our_move is True)


def test_blocking_vs_attacking():
    print("\nBlocage contre attaque déclarée")

    enemy_attacker = rect_at_ratio(0.65, code="UNIT_A", card_id=10, local=False)
    our_attacker = rect_at_ratio(0.32, code="UNIT_B", card_id=11, local=True)

    install_fakes(nexus_rects() + [enemy_attacker])
    snap = reader().snapshot()
    check("adversaire attaque, rangée à nous vide -> BLOCKING",
          snap.phase is Phase.BLOCKING, snap.phase)

    # Même configuration côté adverse, mais nos unités sont avancées :
    # c'est nous l'attaquant, il ne faut surtout pas croire qu'on bloque.
    install_fakes(nexus_rects() + [enemy_attacker, our_attacker])
    snap = reader().snapshot()
    check("nos unités avancées -> ATTACKING", snap.phase is Phase.ATTACKING, snap.phase)


def test_challenger_pulls_us_into_the_attack_row():
    """
    NOTRE RANGÉE AVANCÉE NE VEUT PAS DIRE QUE C'EST NOUS QUI ATTAQUONS.

    Challenger (et Vulnerable) TIRENT une de nos unités en face de
    l'attaquant : elle traverse la ligne toute seule. Les deux rangées
    sont alors occupées, exactement comme quand nous attaquons et qu'il
    bloque — et c'est le jeton, qui dit à qui appartient CE round
    d'attaque, qui départage les deux.

    Observé le 20/08/2026 : l'adversaire attire Mel, le bot lit ATTACKING
    et attend une résolution qui ne vient jamais pendant que le jeu
    réclame des bloqueurs.
    """
    print("\nChallenger : les deux rangées avancées")

    enemy_attacker = rect_at_ratio(0.65, code="UNIT_A", card_id=10, local=False)
    pulled = rect_at_ratio(0.32, code="UNIT_B", card_id=11, local=True)
    rects = nexus_rects() + [enemy_attacker, pulled]

    install_fakes(rects, screen=make_screen(orb_active=True, token="adversaire"))
    snap = reader().snapshot()
    check("épée côté adverse -> c'est SON attaque, on bloque",
          snap.phase is Phase.BLOCKING, snap.phase)
    check("notre unité est bien vue avancée", len(snap.attack_row) == 1, snap.attack_row)
    check("la sienne aussi", len(snap.enemy_attack_row) == 1, snap.enemy_attack_row)

    # Même image, jeton de notre côté : c'est nous l'attaquant et les
    # cartes d'en face sont ses bloqueurs. Rien ne doit changer.
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = reader().snapshot()
    check("épée de notre côté -> ATTACKING", snap.phase is Phase.ATTACKING, snap.phase)

    # Jeton introuvable : on ne DEVINE pas une attaque adverse. Le doute
    # laisse le comportement d'avant, et c'est la boucle de combat qui
    # rattrape (combat.CombatLoop._reconsider_attacking).
    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    snap = reader().snapshot()
    check("jeton introuvable -> ATTACKING, comme avant",
          snap.phase is Phase.ATTACKING, snap.phase)


def test_attack_is_read_before_the_orb():
    """
    L'orbe est grise pendant l'animation de la charge adverse. Tester
    l'orbe en premier donnait OPPONENT_TURN à ce moment-là, la boucle
    attendait, et le tour se terminait sur un « pas d'attaque ce tour »
    faux — attaque encaissée sans un seul bloqueur.
    """
    print("\nAttaque adverse pendant que l'orbe est grise")

    enemy_attacker = rect_at_ratio(0.65, code="UNIT_A", card_id=10, local=False)
    ours = rect_at_ratio(0.15, code="UNIT_B", card_id=11, local=True)

    install_fakes(nexus_rects() + [enemy_attacker, ours],
                  screen=make_screen(orb_active=False))
    snap = reader().snapshot()
    check("orbe grise mais unités adverses avancées -> BLOCKING",
          snap.phase is Phase.BLOCKING, snap.phase)
    check("l'orbe reste lisible pour qui doit agir",
          snap.turn_orb_active is False, snap.turn_orb_active)

    # Sans attaque déclarée, une orbe grise veut toujours dire « il joue ».
    install_fakes(nexus_rects() + [ours], screen=make_screen(orb_active=False))
    snap = reader().snapshot()
    check("orbe grise sans attaque -> OPPONENT_TURN",
          snap.phase is Phase.OPPONENT_TURN, snap.phase)


def test_side_beats_band():
    """
    Une unité qui charge traverse trois bandes ; laquelle elle atteint
    dépend de l'animation et du décalage du plateau. Son camp, lui, vient
    de l'API. C'est le camp qui doit trancher.
    """
    print("\nLe camp prime sur la bande")

    # Attaquant adverse qui a dépassé sa bande et retombe dans `stack`.
    overshot = rect_at_ratio(0.48, code="UNIT_A", card_id=30, local=False)
    install_fakes(nexus_rects() + [overshot])
    snap = reader().snapshot()
    check("unité adverse tombée dans la pile -> BLOCKING",
          snap.phase is Phase.BLOCKING, snap.phase)
    check("elle est rangée en attaquant adverse",
          len(snap.enemy_attack_row) == 1, snap.enemy_attack_row)
    check("la pile reste vide", len(snap.stack) == 0, snap.stack)

    # Symétrique : une de NOS unités trop avancée reste une attaquante.
    ours = rect_at_ratio(0.48, code="UNIT_B", card_id=31, local=True)
    install_fakes(nexus_rects() + [ours])
    snap = reader().snapshot()
    check("notre unité tombée dans la pile -> ATTACKING",
          snap.phase is Phase.ATTACKING, snap.phase)
    check("elle est rangée dans notre rangée d'attaque",
          len(snap.attack_row) == 1, snap.attack_row)

    # Un sort, lui, reste un sort : c'est bien une pile.
    spell = rect_at_ratio(0.48, code="SPELL_A", card_id=32, local=False)
    install_fakes(nexus_rects() + [spell])
    snap = reader().snapshot()
    check("un sort dans la pile reste un sort",
          snap.phase is Phase.SPELL_STACK, snap.phase)


def test_enemy_spell_is_read_wherever_it_lands():
    """
    UN SORT ADVERSE EST UNE FENÊTRE DE RÉPONSE, OÙ QU'IL TOMBE ET QUELLE
    QUE SOIT L'ORBE.

    Signalé par Ewan le 03/09/2026 : le bot ne voyait ni les sorts
    adverses ni la réponse adverse à nos sorts. La pile n'était lue
    qu'après l'orbe (grise pendant qu'il décide → OPPONENT_TURN), et un
    sort tombé hors de la bande « stack » passait pour une attaque.
    """
    print("\nSort adverse : lu avant l'orbe, où qu'il tombe")

    # Orbe GRISE, sort adverse dans la bande de la pile : c'est un sort.
    spell = rect_at_ratio(0.48, code="SPELL_A", card_id=40, local=False)
    install_fakes(nexus_rects() + [spell], screen=make_screen(orb_active=False))
    snap = reader().snapshot()
    check("orbe grise + sort adverse -> SPELL_STACK", snap.phase is Phase.SPELL_STACK, snap.phase)
    check("   l'orbe dit que c'est à lui de parler", snap.turn_orb_active is False)
    check("   le sort est rangé côté adverse",
          len(snap.stack_theirs) == 1 and not snap.stack_ours, snap.stack)

    # Sort adverse tombé dans la bande « enemy_attack » : pas une attaque.
    high = rect_at_ratio(0.65, code="SPELL_A", card_id=41, local=False)
    install_fakes(nexus_rects() + [high], screen=make_screen(orb_active=True))
    snap = reader().snapshot()
    check("sort adverse dans la bande d'attaque -> SPELL_STACK, pas BLOCKING",
          snap.phase is Phase.SPELL_STACK, snap.phase)
    check("   la rangée d'attaque adverse reste vide", not snap.enemy_attack_row)

    # Notre sort tombé dans NOTRE bande d'attaque : pas notre attaque.
    low = rect_at_ratio(0.32, code="SPELL_A", card_id=42, local=True)
    install_fakes(nexus_rects() + [low], screen=make_screen(orb_active=True))
    snap = reader().snapshot()
    check("notre sort dans notre bande d'attaque -> SPELL_STACK, pas ATTACKING",
          snap.phase is Phase.SPELL_STACK, snap.phase)

    # Réponse adverse à NOTRE sort : les deux sur la pile.
    ours = rect_at_ratio(0.48, code="SPELL_A", card_id=43, local=True, x=700)
    theirs = rect_at_ratio(0.48, code="SPELL_A", card_id=44, local=False, x=900)
    install_fakes(nexus_rects() + [ours, theirs], screen=make_screen(orb_active=True))
    snap = reader().snapshot()
    check("les deux sorts sur la pile -> SPELL_STACK", snap.phase is Phase.SPELL_STACK, snap.phase)
    check("   un à nous, un à lui", len(snap.stack_ours) == 1 and len(snap.stack_theirs) == 1)

    # Sort pendant le combat : la pile prime sur les rangées avancées.
    attacker = rect_at_ratio(0.65, code="UNIT_A", card_id=45, local=False)
    mid = rect_at_ratio(0.48, code="SPELL_A", card_id=46, local=False, x=1000)
    install_fakes(nexus_rects() + [attacker, mid], screen=make_screen(orb_active=True))
    snap = reader().snapshot()
    check("sort pendant l'attaque adverse -> SPELL_STACK d'abord",
          snap.phase is Phase.SPELL_STACK, snap.phase)
    check("   l'attaquant reste lu dans sa rangée", len(snap.enemy_attack_row) == 1)

    # Une carte INCONNUE dans la bande de la pile garde l'ancien traitement :
    # orbe grise -> tour adverse. Sans base de cartes, tout serait « sort ».
    unknown = rect_at_ratio(0.48, code="MYSTERY", card_id=47, local=False)
    install_fakes(nexus_rects() + [unknown], screen=make_screen(orb_active=False))
    snap = reader().snapshot()
    check("carte inconnue + orbe grise -> OPPONENT_TURN, comme avant",
          snap.phase is Phase.OPPONENT_TURN, snap.phase)


def test_spell_stack():
    print("\nSort sur la pile")
    spell = rect_at_ratio(0.48, code="SPELL_A", card_id=20, local=False)
    install_fakes(nexus_rects() + [spell])
    snap = reader().snapshot()
    check("carte dans la pile -> SPELL_STACK", snap.phase is Phase.SPELL_STACK, snap.phase)


def test_mulligan():
    print("\nMulligan")

    # Quatre cartes alignées au milieu de l'écran, plateau vide.
    mulligan = [
        rect_at_ratio(0.600, code="UNIT_A", card_id=i, height=330, x=600 + 200 * i)
        for i in range(4)
    ]
    install_fakes(nexus_rects() + mulligan)
    snap = reader().snapshot()
    check("4 cartes alignées au centre -> MULLIGAN", snap.phase is Phase.MULLIGAN, snap.phase)

    # Piège n°1 : une main est alignée aussi, mais bien plus bas.
    hand = [
        rect_at_ratio(0.010, code="UNIT_A", card_id=i, height=330, x=600 + 150 * i)
        for i in range(4)
    ]
    install_fakes(nexus_rects() + hand)
    snap = reader().snapshot()
    check("main alignée -> PAS mulligan", snap.phase is not Phase.MULLIGAN, snap.phase)

    # Piège n°2 : cartes alignées au centre MAIS plateau occupé.
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=99)
    install_fakes(nexus_rects() + mulligan + [board])
    snap = reader().snapshot()
    check("plateau occupé -> PAS mulligan", snap.phase is not Phase.MULLIGAN, snap.phase)


def test_menus_and_api_down():
    print("\nMenus et API absente")

    install_fakes(nexus_rects(), game_state_str="Menus")
    check("GameState Menus -> MENUS", reader().snapshot().phase is Phase.MENUS)

    def boom():
        raise lor_api.ApiUnavailable("simulé")

    lor_api.get_positional_rectangles = boom
    check("API injoignable -> NO_API", reader().snapshot().phase is Phase.NO_API)


def test_game_over_fires_once():
    print("\nFin de partie")

    board = rect_at_ratio(0.15, code="UNIT_A", card_id=1)
    install_fakes(nexus_rects() + [board], game_result={"GameID": 7, "LocalPlayerWon": True})
    detector = reader()

    first = detector.snapshot()
    check("première lecture ne déclenche pas GAME_OVER", first.phase is not Phase.GAME_OVER, first.phase)

    lor_api.get_game_result = lambda: {"GameID": 8, "LocalPlayerWon": False}
    second = detector.snapshot()
    check("GameID incrémenté -> GAME_OVER", second.phase is Phase.GAME_OVER, second.phase)
    check("résultat mémorisé", second.last_game_won is False, second.last_game_won)

    third = detector.snapshot()
    check("GAME_OVER n'est émis qu'une fois", third.phase is not Phase.GAME_OVER, third.phase)


def test_final_result_waits_for_the_verdict():
    """`/game-result` bascule après le retour aux menus : on l'attend un peu."""
    print("\nVerdict lu après les menus")

    install_fakes(nexus_rects(), game_result={"GameID": 7, "LocalPlayerWon": True})
    r = reader()
    r.snapshot()                                   # première lecture : mémorise 7
    calls = {"n": 0}

    def late_result():
        calls["n"] += 1
        return {"GameID": 8, "LocalPlayerWon": False} if calls["n"] >= 3 else {"GameID": 7, "LocalPlayerWon": True}

    lor_api.get_game_result = late_result
    won = r.final_result(timeout=5.0, poll=0.01)
    check("la défaite est lue quand le GameID bascule", won is False, won)
    check("   après plusieurs lectures", calls["n"] >= 3, calls["n"])

    lor_api.get_game_result = lambda: {"GameID": 8, "LocalPlayerWon": False}
    won = r.final_result(timeout=0.05, poll=0.01)
    check("rien de nouveau : None, pas un verdict inventé", won is None, won)


def test_decklist_is_read_once_and_tells_what_is_left():
    """
    /static-decklist : le deck se lit UNE fois par partie ; on en déduit ce
    qui reste à piocher (borne haute) et ce qui a été GÉNÉRÉ.
    """
    print("\nDeck lu sur /static-decklist")

    hand = [rect_at_ratio(0.029, code="UNIT_A", card_id=60, height=330, x=500),
            rect_at_ratio(0.029, code="SPELL_A", card_id=61, height=330, x=640)]
    install_fakes(nexus_rects() + hand, decklist={"UNIT_A": 3, "UNIT_B": 2})
    r = reader()
    snap = r.snapshot()
    check("le deck est connu", snap.deck == {"UNIT_A": 3, "UNIT_B": 2}, snap.deck)
    check("ce qui reste : une UNIT_A de moins", snap.deck_remaining() == {"UNIT_A": 2, "UNIT_B": 2},
          snap.deck_remaining())
    spell = next(c for c in snap.hand if c.code == "SPELL_A")
    unit = next(c for c in snap.hand if c.code == "UNIT_A")
    check("SPELL_A n'est pas dans le deck : générée", snap.is_generated(spell) is True)
    check("UNIT_A vient du deck", snap.is_generated(unit) is False)
    check("le résumé le dit", "deck : 5 cartes" in snap.summary(), snap.summary())

    calls = {"n": 0}
    def counting():
        calls["n"] += 1
        return {"CardsInDeck": {"UNIT_A": 3, "UNIT_B": 2}}
    lor_api.get_static_decklist = counting
    r.snapshot(); r.snapshot()
    check("pas relu à chaque lecture", calls["n"] == 0, calls["n"])

    # Deck inconnu : on n'affirme rien.
    install_fakes(nexus_rects() + hand)
    snap = reader().snapshot()
    check("deck inconnu : rien de généré, rien de restant",
          snap.deck == {} and snap.deck_remaining() == {} and snap.is_generated(spell) is False)


def test_champions_are_read_from_card_sets():
    """`supertype` et `collectible` de card_sets : champion, et niveau 2 par le cardCode."""
    print("\nChampions et niveau 2 lus dans la base")

    db = dict(CARD_DB)
    db["CHAMP"] = {**CARD_DB["UNIT_A"], "name": "Yasuo", "supertype": "Champion", "collectible": True}
    db["CHAMPT1"] = {**CARD_DB["UNIT_A"], "name": "Yasuo", "supertype": "Champion", "collectible": False}
    saved = dict(CARD_DB); CARD_DB.clear(); CARD_DB.update(db)
    try:
        rects = [rect_at_ratio(0.150, code="CHAMP", card_id=70, x=500),
                 rect_at_ratio(0.150, code="CHAMPT1", card_id=71, x=640),
                 rect_at_ratio(0.150, code="UNIT_A", card_id=72, x=780)]
        install_fakes(nexus_rects() + rects)
        snap = reader().snapshot()
        by = {c.code: c for c in snap.board}
        check("champion reconnu", by["CHAMP"].is_champion and not by["CHAMP"].is_leveled)
        check("niveau 2 reconnu au code non collectionnable", by["CHAMPT1"].is_leveled)
        check("une unité ordinaire n'est ni l'un ni l'autre",
              not by["UNIT_A"].is_champion and not by["UNIT_A"].is_leveled)
        import keywords
        base = keywords.unit_value(by["UNIT_A"])
        check("un champion vaut plus", keywords.unit_value(by["CHAMP"]) == base + keywords.CHAMPION_BONUS)
        check("monté, encore plus", keywords.unit_value(by["CHAMPT1"]) == base + keywords.LEVELED_BONUS)
    finally:
        CARD_DB.clear(); CARD_DB.update(saved)


def test_button_label_confirms_a_response_window():
    """
    Le TEXTE du bouton de tour est un témoin de phase : « RÉSOUDRE » veut
    dire que le jeu attend une réponse, même si l'API n'a pas rapporté le
    sort. Sans template, rien ne change.
    """
    print("\nLe libellé du bouton confirme la fenêtre de réponse")

    # Un « texte » synthétique collé dans la zone de l'orbe, et le même
    # motif enregistré comme template « resoudre ».
    rng = np.random.default_rng(3)
    text = rng.integers(0, 255, size=(24, 120, 3), dtype=np.uint8)
    folder = Path(tempfile.mkdtemp(prefix="lor-orb-"))
    cv2.imwrite(str(folder / "resoudre.png"), text)
    saved_dir, saved_cache = game_state.TURN_BUTTON_DIR, game_state._BUTTON_TEMPLATES
    game_state.TURN_BUTTON_DIR, game_state._BUTTON_TEMPLATES = folder, None
    try:
        screen = make_screen(orb_active=True)
        left, top, right, bottom = WINDOW.rel_box(TURN_ORB_REGION)
        y, x = top + 60, left + 90
        screen[y:y + 24, x:x + 120] = text
        install_fakes(nexus_rects(), screen=screen)
        snap = reader().snapshot()
        check("libellé lu : resoudre", snap.button_label == "resoudre", snap.button_label)
        check("pile vide mais bouton RÉSOUDRE -> SPELL_STACK", snap.phase is Phase.SPELL_STACK, snap.phase)
        check("le résumé montre le bouton", "bouton=resoudre" in snap.summary(), snap.summary())

        # Sans le texte : aucun libellé, phase ordinaire.
        install_fakes(nexus_rects(), screen=make_screen(orb_active=True, token="nous"))
        snap = reader().snapshot()
        check("sans texte : pas de libellé", snap.button_label is None, snap.button_label)
        check("   et la phase ne bouge pas", snap.phase is Phase.ATTACK_TURN, snap.phase)

        # Bouton RÉSOUDRE mais orbe grise : ce n'est pas à nous, on n'invente pas.
        screen = make_screen(orb_active=False)
        screen[y:y + 24, x:x + 120] = text
        install_fakes(nexus_rects(), screen=screen)
        snap = reader().snapshot()
        check("orbe grise : le libellé seul ne fait pas une fenêtre de réponse",
              snap.phase is Phase.OPPONENT_TURN, snap.phase)
    finally:
        game_state.TURN_BUTTON_DIR, game_state._BUTTON_TEMPLATES = saved_dir, saved_cache


def test_card_model():
    print("\nModèle de carte")

    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    install_fakes(nexus_rects() + [board])
    card = reader().snapshot().board[0]

    check("nom résolu depuis card_sets", card.name == "Ombre Fuyante", card.name)
    check("mot-clé par libellé", card.has("Can't Block"))
    check("mot-clé par référence interne", card.has("CantBlock"))
    check("mot-clé insensible à la casse", card.has("elusive"))
    check("can_block False si Can't Block", card.can_block is False)
    check("centre en coordonnées écran", card.center == (863, 1080 - board["TopLeftY"] + 79),
          (card.center, board["TopLeftY"]))

    # Une carte absente de card_sets doit être CONSERVÉE, pas ignorée :
    # raisonner sur un plateau incomplet est plus dangereux que raisonner
    # avec des stats à 0.
    unknown = rect_at_ratio(0.15, code="TOKEN_XYZ", card_id=3, x=1000)
    install_fakes(nexus_rects() + [unknown])
    snap = reader().snapshot()
    check("carte inconnue conservée", len(snap.board) == 1, snap.board)
    check("carte inconnue signalée", snap.unknown_codes == ("TOKEN_XYZ",), snap.unknown_codes)
    check("carte inconnue marquée known=False", snap.board[0].known is False)


def test_un_mot_cle_lu_a_lecran_complete_la_carte_imprimee():
    """
    L'ÉCRAN COMPLÈTE, IL NE RETIRE JAMAIS (décision d'Ewan, 20/11/2026).

    Pâle orchestre (06SI009) imprime DEUX mots-clés — Hallowed et
    Ephemeral — et l'écran en montre QUATRE : Challenger et Overwhelm lui
    ont été accordés en jeu. Ce sont deux mots-clés MODÉLISÉS : le
    premier décide si un blocage est légal, le second change l'excédent
    d'une attaque. Sans cette lecture, le bot jouait cinq unités comme si
    elles n'avaient ni l'un ni l'autre.
    """
    print("\nL'écran complète la carte imprimée")
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    install_fakes(nexus_rects() + [board])
    carte = reader().snapshot().board[0]

    imprime = tuple(carte.keywords)
    carte.keywords_lus = ("Challenger", "Overwhelm")

    check("l'imprimé est conservé", all(carte.has(k) for k in imprime), imprime)
    check("le mot-clé ACCORDÉ est vu", carte.has("Challenger"))
    check("et le second aussi", carte.has("Overwhelm"))
    check("ce qui n'est nulle part reste faux", carte.has("Formidable") is False)


def test_un_mot_cle_lu_ne_retire_jamais_un_imprime():
    """
    LE PRIX ASSUMÉ DU 20/11 : on ne voit pas les mots-clés RETIRÉS
    (Silence). Une lecture vide ne doit donc RIEN effacer — c'est la
    règle de `stunned`, « faux par défaut veut dire on n'a pas regardé ».
    """
    print("\nUne lecture vide n'efface rien")
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    install_fakes(nexus_rects() + [board])
    carte = reader().snapshot().board[0]

    check("vide par défaut", carte.keywords_lus == (), carte.keywords_lus)
    check("l'imprimé survit à une lecture vide", carte.has("CantBlock"))


def test_la_lecture_decran_est_vraiment_branchee():
    """
    UN MODULE PEUT ÊTRE PARFAIT ET N'ÊTRE BRANCHÉ NULLE PART (10/11/2026).

    Les deux tests ci-dessus posent `keywords_lus` À LA MAIN : ils
    décrivent ce que `has()` en fait, jamais le fait que `snapshot()`
    aille lire l'écran. Restaient donc sans aucun filet : les clés de
    `ZONES_DE_PLATEAU` (dont le commentaire avertit qu'on pourrait les
    « corriger » vers `attack_row` et tout casser EN SILENCE), le fait
    que les `BoardCard` passées à `lire_les_mots_cles` soient bien les
    objets que `snapshot.board` rend, et la place de l'appel après la
    sortie du mulligan.

    On bouchonne `identifier` — la seule couture vers l'image — et on
    regarde ce qui ressort du bout de la chaîne.

    ET LE CÔTÉ FAIT PARTIE DE LA QUESTION (21/11/2026) : chez
    l'adversaire la barre est en HAUT de la carte. Lire la mauvaise
    bande ne lève rien et ne journalise rien — c'est exactement la
    panne MUETTE qui a rendu le camp adverse aveugle. Le bouchon garde
    donc le drapeau que `lire_les_mots_cles` lui passe.

    ET LE CAMP VIENT DE LA CARTE, PAS DU NOM DE ZONE. Les zones de
    plateau sont déduites de la HAUTEUR du rectangle, et c'est la
    mesure que `reconcile_combat_rows` corrige depuis des mois (« la
    hauteur est une mesure bruitée ; le camp, lui, est donné par l'API
    et ne se trompe jamais »). Le troisième rectangle ci-dessous est
    donc à NOUS (`LocalPlayer` vrai) mais sa hauteur le range dans
    `enemy_board` : sa barre doit malgré tout être cherchée EN BAS.
    """
    print("\nLa lecture d'écran est branchée dans snapshot()")
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    adverse = rect_at_ratio(0.80, code="UNIT_B", card_id=3, local=False)
    # À nous, mais rangée dans `enemy_board` par sa seule hauteur.
    egaree = rect_at_ratio(0.85, code="UNIT_B", card_id=4, local=True, x=400)
    install_fakes(nexus_rects() + [board, adverse, egaree])

    vrai = game_state.mots_cles_ecran.identifier
    vus = []

    def bouchon(image, centre, adverse=False):
        vus.append((centre, adverse))
        return ("Challenger",)

    game_state.mots_cles_ecran.identifier = bouchon
    try:
        snap = reader().snapshot()
    finally:
        game_state.mots_cles_ecran.identifier = vrai

    carte = snap.board[0]
    # Par CardID : `enemy_board` en contient deux, et l'ordre de la zone
    # n'est pas celui de la trame.
    en_face = [c for c in snap.enemy_board if c.card_id == 3][0]
    check("l'écran a été interrogé sous l'unité du banc",
          (carte.center, False) in vus, (vus, carte.center))
    check("   et AU-DESSUS de l'unité adverse",
          (en_face.center, True) in vus, (vus, en_face.center))
    egaree_lue = [c for c in snap.enemy_board if c.card_id == 4]
    check("une unité À NOUS rangée dans `enemy_board` par sa hauteur…",
          len(egaree_lue) == 1, [c.card_id for c in snap.enemy_board])
    if egaree_lue:
        check("   …est quand même lue EN BAS : le camp vient de l'API",
              (egaree_lue[0].center, False) in vus, (vus, egaree_lue[0].center))
    check("le mot-clé lu arrive sur la carte de l'instantané",
          carte.keywords_lus == ("Challenger",), carte.keywords_lus)
    check("et `has` le voit", carte.has("Challenger"))
    check("l'imprimé est toujours là", carte.has("Elusive"))

    # L'INTERRUPTEUR DE REPLI DOIT VRAIMENT REPLIER. Il n'a d'intérêt que
    # le jour où on le bascule en pleine session : s'il ne coupait pas,
    # on n'aurait aucun moyen de revenir au comportement d'avant.
    vus.clear()
    game_state.mots_cles_ecran.identifier = bouchon
    game_state.MOTS_CLES_ECRAN = False
    try:
        coupe = reader().snapshot().board[0]
    finally:
        game_state.MOTS_CLES_ECRAN = True
        game_state.mots_cles_ecran.identifier = vrai

    check("interrupteur à False : l'écran n'est pas lu", vus == [], vus)
    check("   et la carte reste sur ses mots-clés imprimés",
          coupe.keywords_lus == () and coupe.has("Elusive"), coupe.keywords_lus)


def test_live_stats_override_base():
    print("\nStats réelles contre stats de base")

    board = rect_at_ratio(0.15, code="UNIT_A", card_id=1)      # Garde de Fer 3/4
    install_fakes(nexus_rects() + [board])
    snap = reader().snapshot()
    card = snap.board[0]

    check("stats de base avant OCR", (card.attack, card.health) == (3, 4),
          (card.attack, card.health))
    check("pas encore de lecture", card.stats_are_live is False)

    # L'unité est en réalité buffée à 5 et blessée à 1.
    card.attack_read, card.health_read = 5, 1
    check("la lecture prime sur la base", (card.attack, card.health) == (5, 1),
          (card.attack, card.health))
    check("origine signalée", card.stats_are_live is True)
    check("astérisque à l'affichage", str(card).endswith("5/1*"), str(card))

    # Une lecture partielle ne doit pas effacer l'autre valeur : un badge
    # illisible retombe sur la base, l'autre garde sa lecture.
    card.attack_read, card.health_read = None, 2
    check("repli par stat, pas en bloc", (card.attack, card.health) == (3, 2),
          (card.attack, card.health))


def test_live_stats_degrade_without_ocr():
    print("\nOCR indisponible")

    board = rect_at_ratio(0.15, code="UNIT_A", card_id=1)
    install_fakes(nexus_rects() + [board])
    snap = reader().snapshot()

    # easyocr n'est pas installé ici : l'enrichissement doit se dégrader
    # en silence, pas lever. Un badge illisible ne doit jamais
    # interrompre un combat.
    returned = game_state.enrich_with_live_stats(snap)
    check("aucune exception levée", returned is snap)
    check("stats de base conservées", (snap.board[0].attack, snap.board[0].health) == (3, 4),
          (snap.board[0].attack, snap.board[0].health))


def test_zone_bands_follow_nexus_geometry():
    print("\nBandes ancrées sur les nexus")

    rects = nexus_rects()
    span = game_state.nexus_span(rects, WINDOW)
    check("écartement mesuré", span is not None and abs(span[0] - 0.148) < 0.01,
          span)

    # Sans référence enregistrée, rien ne change : on ne rééchelonne pas
    # à partir d'un repère qu'on n'a pas mesuré.
    detector = reader()
    detector.zone_reference = None
    check("sans référence -> bandes d'origine",
          detector.bands_for(rects, WINDOW) == game_state.ZONE_BANDS)

    # Même géométrie que la référence : les bandes doivent être inchangées.
    detector.zone_reference = span
    rescaled = detector.bands_for(rects, WINDOW)
    check("géométrie identique -> bandes identiques",
          all(abs(a[0] - b[0]) < 1e-6 for a, b in zip(rescaled, game_state.ZONE_BANDS)),
          rescaled)

    # Plateau deux fois plus resserré : les bandes suivent.
    tight = (0.30, 0.62)
    moved = game_state.rescale_bands(game_state.ZONE_BANDS, span, tight)
    original_mid = (game_state.ZONE_BANDS[2][0] - span[0]) / (span[1] - span[0])
    new_mid = (moved[2][0] - tight[0]) / (tight[1] - tight[0])
    check("position relative conservée", abs(original_mid - new_mid) < 1e-6,
          (original_mid, new_mid))
    # La bonne propriété n'est pas « les bornes baissent » — un plateau
    # resserré peut être aussi décalé vers le haut — mais que la LARGEUR
    # totale des bandes suive le même facteur que l'écartement des nexus.
    factor = (tight[1] - tight[0]) / (span[1] - span[0])
    original_width = game_state.ZONE_BANDS[-1][0] - game_state.ZONE_BANDS[0][0]
    new_width = moved[-1][0] - moved[0][0]
    check("largeur mise à l'échelle",
          abs(new_width / original_width - factor) < 1e-6,
          (new_width / original_width, factor))


def _fake_cost_calibration(offsets=(0.05, 0.02, 0.13, 0.11)):
    """Écrit une calibration de gemme dans le bac à sable des tests."""
    import json
    path = CALIBRATION_SANDBOX / "calibration.json"
    path.write_text(json.dumps({game_state.COST_CALIBRATION_KEY: list(offsets)}),
                    encoding="utf8")
    return path


def test_screen_costs_are_read_for_known_cards():
    print("\nLecture du coût affiché")

    hand = rect_at_ratio(0.029, code="UNIT_A", card_id=1, height=330)   # imprimé à 3
    install_fakes(nexus_rects() + [hand])
    snap = reader().snapshot()
    card = snap.hand[0]

    check("coût imprimé avant lecture", card.cost == 3, card.cost)
    check("aucune lecture signalée", card.cost_is_live is False)
    check("écart indéfini avant lecture", card.cost_gap is None, card.cost_gap)

    # Sans calibration de la gemme, on ne lit rien et on ne casse rien.
    (CALIBRATION_SANDBOX / "calibration.json").unlink(missing_ok=True)
    check("sans calibration : aucune lecture",
          game_state.read_costs(snap, screen=make_screen()) == 0)
    check("coût imprimé conservé", card.cost == 3, card.cost)

    # Avec calibration : la carte CONNUE est lue elle aussi. C'est tout
    # l'objet du changement — une carte présente dans card_sets peut voir
    # son coût modifié en jeu, et c'est l'écran qui fait foi.
    _fake_cost_calibration()
    game_state._BADGE_CACHE.clear()
    saved = sys.modules.get("mana")
    stub = types.ModuleType("mana")
    stub.read_digits = lambda crop, maximum, debug=False: 1
    sys.modules["mana"] = stub
    try:
        count = game_state.read_costs(snap, screen=make_screen())
    finally:
        if saved is not None:
            sys.modules["mana"] = saved
        else:
            del sys.modules["mana"]

    check("carte connue lue quand même", count == 1, count)
    check("la lecture prime sur card_sets", card.cost == 1, card.cost)
    check("origine signalée", card.cost_is_live is True)
    check("écart mesuré", card.cost_gap == -2, card.cost_gap)
    check("écart listé", [c.name for c, _ in game_state.cost_gaps(snap)] == ["Garde de Fer"],
          game_state.cost_gaps(snap))
    check("marqué à l'affichage", "(1*)" in str(card), str(card))


def test_screen_costs_degrade_when_ocr_fails():
    print("\nOCR de la gemme en panne")

    hand = rect_at_ratio(0.029, code="UNIT_A", card_id=1, height=330)
    install_fakes(nexus_rects() + [hand])
    snap = reader().snapshot()

    _fake_cost_calibration()
    game_state._BADGE_CACHE.clear()

    def boom(crop, maximum, debug=False):
        # easyocr n'est chargé qu'au premier appel : la panne survient donc
        # en plein combat, pas à l'import. Elle ne doit pas remonter.
        raise RuntimeError("easyocr absent")

    saved = sys.modules.get("mana")
    stub = types.ModuleType("mana")
    stub.read_digits = boom
    sys.modules["mana"] = stub
    try:
        returned = game_state.enrich_with_live_costs(snap, screen=make_screen())
    finally:
        if saved is not None:
            sys.modules["mana"] = saved
        else:
            del sys.modules["mana"]

    check("aucune exception levée", returned is snap)
    check("coût imprimé conservé", snap.hand[0].cost == 3, snap.hand[0].cost)
    check("aucune lecture revendiquée", snap.hand[0].cost_is_live is False)


def test_badge_cache_separates_families():
    print("\nCache séparé par famille de badge")

    calls = []

    def fake_ocr(crop, name="", debug=False, maximum=None):
        calls.append(name)
        return 7

    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    game_state._BADGE_CACHE.clear()

    game_state._cached_ocr(crop, "a", fake_ocr, tag="stat")
    game_state._cached_ocr(crop, "a", fake_ocr, tag="stat")
    check("même famille : une seule lecture", len(calls) == 1, calls)

    # Mêmes pixels, autre famille : la gemme de mana et un badge de stat
    # ne passent pas par le même OCR, la réponse de l'un ne vaut pas pour
    # l'autre.
    game_state._cached_ocr(crop, "a", fake_ocr, tag="cost")
    check("famille différente : nouvelle lecture", len(calls) == 2, calls)


def test_an_implausible_reading_is_refused():
    """
    LE BOGUE DU 04/11/2026. Une Prancing Sea Spirits 3/3 a été lue
    **3/73**, jugée increvable, et envoyée attaquer sur cette base
    (« prévision : on perd 6, on tue 7 »). Cause : deux bornes pour la
    même grandeur. `_cached_ocr` passait bien `maximum=30` à la lecture
    par forme, mais son secours `ocr_number` rebornait à STAT_MAX (99)
    en interne et sa valeur n'était jamais revérifiée.

    Une valeur hors borne vaut un ÉCHEC de lecture — la carte retombe sur
    sa stat imprimée — et non une décision.
    """
    print("\nUne lecture invraisemblable est refusée")

    vus = []

    def ocr_delirant(crop, name="", debug=False, maximum=None):
        vus.append(maximum)
        return 73

    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    game_state._BADGE_CACHE.clear()
    lu = game_state._cached_ocr(crop, "spirits_hp", ocr_delirant, tag="stat")
    check("73 n'est pas retenu pour une stat", lu is None, lu)
    check("la borne est transmise à l'OCR",
          vus == [game_state.STAT_READ_MAX], vus)

    # Une valeur plausible passe : on ne jette pas l'OCR avec l'eau du bain.
    def ocr_sage(crop, name="", debug=False, maximum=None):
        return 7

    game_state._BADGE_CACHE.clear()
    check("7 est retenu",
          game_state._cached_ocr(crop, "spirits_hp", ocr_sage, tag="stat") == 7)

    # La borne exacte est acceptée, celle juste au-dessus non.
    for valeur, attendu in ((game_state.STAT_READ_MAX, game_state.STAT_READ_MAX),
                            (game_state.STAT_READ_MAX + 1, None)):
        game_state._BADGE_CACHE.clear()
        lu = game_state._cached_ocr(
            crop, "x", lambda c, name="", debug=False, maximum=None, v=valeur: v, tag="stat")
        check(f"   {valeur} -> {attendu}", lu == attendu, lu)

    # Le coût a SA borne, plus basse : 20 est une stat plausible, jamais
    # un coût en mana.
    game_state._BADGE_CACHE.clear()
    lu = game_state._cached_ocr(
        crop, "x_cost", lambda c, name="", debug=False, maximum=None: 20, tag="cost")
    check("20 refusé comme coût", lu is None, lu)
    game_state._BADGE_CACHE.clear()
    lu = game_state._cached_ocr(
        crop, "x_atk", lambda c, name="", debug=False, maximum=None: 20, tag="stat")
    check("   mais accepté comme stat", lu == 20, lu)

    # Une seule source par grandeur : les bornes ne doivent plus diverger.
    check("les bornes viennent des constantes",
          game_state._MAX_FOR_TAG == {"stat": game_state.STAT_READ_MAX,
                                      "cost": game_state.COST_MAX},
          game_state._MAX_FOR_TAG)


def test_badge_cache_avoids_repeat_ocr():
    print("\nCache des badges")

    calls = []

    def fake_ocr(crop, name="", debug=False, maximum=None):
        calls.append(name)
        return 7

    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    other = np.ones((10, 10, 3), dtype=np.uint8)
    game_state._BADGE_CACHE.clear()

    check("première lecture", game_state._cached_ocr(crop, "a", fake_ocr) == 7)
    check("deuxième lecture identique", game_state._cached_ocr(crop, "a", fake_ocr) == 7)
    # Le cache est indexé sur les PIXELS : mêmes pixels, même chiffre, donc
    # un seul appel d'OCR.
    check("OCR appelé une seule fois", len(calls) == 1, calls)

    game_state._cached_ocr(other, "b", fake_ocr)
    check("pixels différents -> nouvelle lecture", len(calls) == 2, calls)


def test_zones_never_keyerror():
    print("\nRobustesse")
    install_fakes(nexus_rects())
    snap = reader().snapshot()
    for name in game_state.ZONE_ORDER:
        check(f"zone '{name}' toujours présente", snap.zones[name] == ())
    check("phase is_our_move cohérente", Phase.OPPONENT_TURN.is_our_move is False)
    check("MENUS n'est pas in_game", Phase.MENUS.in_game is False)
    check("BLOCKING est in_game", Phase.BLOCKING.in_game is True)


def test_inspect_rejoue_le_classement_du_bot():
    """
    LE DIAGNOSTIC DOIT DIRE CE QUE LE BOT RETIENT, PAS LA MOITIÉ.

    `reconcile_combat_rows` fait DEUX choses : elle range une unité
    avancée selon son CAMP, et elle range un SORT (ou une compétence)
    sur la PILE, où que sa hauteur l'ait fait tomber. La colonne
    « zone retenue » d'`inspect` ne rejouait que la première moitié :
    un sort adverse tombé dans la bande `enemy_attack` y était montré
    en « enemy_attack » alors que le bot le range en « stack » — et
    c'est ce classement-là qui déclenche la phase SPELL_STACK.

    Le juge final de ce test n'est pas une valeur écrite à la main,
    c'est l'instantané lui-même : ligne par ligne, la colonne doit
    valoir la zone de la carte dans `snapshot()`.
    """
    print("\n`inspect` rejoue le classement du bot")

    # Un sort adverse haut (bande `enemy_attack`), une unité adverse qui
    # a dépassé (bande `stack`), une des nôtres au banc (rien à corriger).
    sort = rect_at_ratio(0.65, code="SPELL_A", card_id=60, local=False, x=1000)
    attaquant = rect_at_ratio(0.48, code="UNIT_A", card_id=61, local=False, x=700)
    banc = rect_at_ratio(0.15, code="UNIT_B", card_id=62, local=True, x=500)
    rects = nexus_rects() + [sort, attaquant, banc]

    install_fakes(rects, screen=make_screen(orb_active=True))
    lecteur = reader()
    lignes, bands, mulligan = game_state.lignes_inspection(lecteur, rects, WINDOW)
    par_code = {ligne.code: ligne for ligne in lignes if ligne.code != "face"}

    check("le sort adverse tombe bien dans la bande d'attaque adverse",
          par_code["SPELL_A"].bande == "enemy_attack", par_code["SPELL_A"].bande)
    check("   mais la zone retenue est la PILE",
          par_code["SPELL_A"].zone == "stack", par_code["SPELL_A"].zone)
    check("   et le tableau dit pourquoi",
          par_code["SPELL_A"].motif == "pile", par_code["SPELL_A"].motif)
    check("l'unité adverse tombée dans la pile est rendue à son camp",
          par_code["UNIT_A"].bande == "stack" and par_code["UNIT_A"].zone == "enemy_attack",
          (par_code["UNIT_A"].bande, par_code["UNIT_A"].zone))
    check("   motif : le camp", par_code["UNIT_A"].motif == "camp", par_code["UNIT_A"].motif)
    check("une carte au banc n'est pas touchée",
          par_code["UNIT_B"].zone == "board" and not par_code["UNIT_B"].motif,
          (par_code["UNIT_B"].zone, par_code["UNIT_B"].motif))
    check("les nexus restent des nexus",
          [l.nom for l in lignes if l.code == "face"] == ["(nexus)", "(nexus)"])

    # Le juge : la colonne doit valoir la zone de l'instantané, carte par carte.
    snap = reader().snapshot()
    zones_du_bot = {c.code: c.zone for c in snap.cards()}
    check("   la colonne dit EXACTEMENT ce que le bot retient",
          all(par_code[code].zone == zone for code, zone in zones_du_bot.items()),
          (zones_du_bot, {c: l.zone for c, l in par_code.items()}))
    check("   et c'est bien une phase de pile", snap.phase is Phase.SPELL_STACK, snap.phase)

    # Le mulligan est l'exception que `snapshot` s'autorise : les cartes
    # proposées sont alignées au CENTRE, donc en plein dans les bandes de
    # combat, et les ranger par camp ferait mentir le tableau dans l'autre
    # sens. `inspect` doit s'autoriser la même exception.
    cartes = [
        rect_at_ratio(0.600, code="UNIT_A", card_id=i, height=330, x=600 + 200 * i)
        for i in range(4)
    ]
    rects = nexus_rects() + cartes
    install_fakes(rects, screen=make_screen(orb_active=True))
    lignes, _, mulligan = game_state.lignes_inspection(reader(), rects, WINDOW)
    snap = reader().snapshot()
    check("mulligan reconnu par le tableau aussi", mulligan is True)
    check("   aucune carte n'est déplacée par le camp",
          all(not l.motif for l in lignes), [l.motif for l in lignes])
    check("   et là encore la colonne suit l'instantané",
          {l.zone for l in lignes if l.code != "face"} == {c.zone for c in snap.cards()},
          ({l.zone for l in lignes if l.code != "face"}, {c.zone for c in snap.cards()}))



# ============================================================
# LA SORTIE SURVIT-ELLE À UNE REDIRECTION ?
# ============================================================

def test_une_redirection_ne_tue_plus_le_diagnostic():
    """
    `game_state.py monitor > rapport.txt` mourait sur son propre « ≤ ».

    `GameSnapshot.summary()` écrit « deck : N cartes, ≤ M à piocher »
    (game_state.py:1504). La console Windows écrit en UTF-8, mais dès que
    stdout part dans un FICHIER ou un TUBE, Python retombe sur cp1252 —
    où ce caractère n'existe pas. La commande mourait donc exactement là
    où on la redirige pour la lire, et le `logging` ne disait rien :
    stderr survit toujours (`backslashreplace`), c'est le `print` qui
    tombe.

    CE TEST DOIT POUVOIR ÉCHOUER, et il le prouve lui-même : le même
    enfant SANS la parade doit mourir. Le projet vient de relever quatre
    assertions incapables de rougir — on n'en ajoute pas une cinquième.
    """
    print("\n-- une sortie redirigée en cp1252 --")

    import subprocess

    ligne = "deck : 3 cartes, ≤ 2 à piocher"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"

    def enfant(avec_parade):
        code = "import sortie_utf8\n" if avec_parade else ""
        code += "sortie_utf8.appliquer()\n" if avec_parade else ""
        code += f"print({ligne!r})\n"
        return subprocess.run([sys.executable, "-c", code],
                              cwd=str(Path(__file__).resolve().parent),
                              env=env, capture_output=True)

    # La contre-éprouvette : sans la parade, l'enfant DOIT mourir.
    sans = enfant(False)
    check("sans la parade, une redirection cp1252 tue l'impression",
          sans.returncode != 0 and b"UnicodeEncodeError" in sans.stderr,
          f"code={sans.returncode}")

    avec = enfant(True)
    check("avec la parade, l'enfant rend 0", avec.returncode == 0,
          avec.stderr.decode("utf-8", "replace")[-200:])
    check("et ce qu'il écrit est de l'UTF-8 lisible",
          avec.stdout.decode("utf-8").strip() == ligne,
          repr(avec.stdout[:60]))

    # ET LA COMMANDE L'APPELLE VRAIMENT, AVANT TOUT LE RESTE. Le module
    # peut être parfait et n'être branché nulle part : c'est le défaut
    # qu'on répare.
    #
    # ON N'EXÉCUTE PAS LA COMMANDE POUR LE VÉRIFIER. La première version
    # de ce test appelait  sans argument : la commande
    # par défaut va chercher le JEU, la suite est partie pour dix minutes
    # et elle aurait photographié l'écran d'Ewan — la sixième fuite de
    # l'histoire du projet, introduite par le test censé la prévenir.
    # On coupe donc à la construction de l'analyseur d'arguments, qui est
    # la toute première chose que  fait après la parade.
    vus = []
    vrai_appliquer = sortie_utf8.appliquer
    vrai_parser = game_state.argparse.ArgumentParser

    class Coupe(Exception):
        pass

    def analyseur_interdit(*a, **k):
        raise Coupe

    sortie_utf8.appliquer = lambda: vus.append("parade")
    game_state.argparse.ArgumentParser = analyseur_interdit
    try:
        game_state.main()
    except Coupe:
        vus.append("analyseur")
    finally:
        sortie_utf8.appliquer = vrai_appliquer
        game_state.argparse.ArgumentParser = vrai_parser

    check("game_state.main() applique la parade AVANT d'analyser la ligne de commande",
          vus == ["parade", "analyseur"], vus)


def main():
    for test in (
        test_coordinate_conversion,
        test_zone_bands,
        test_phase_our_turn,
        test_le_jeton_se_cherche_en_deux_etages,
        test_token_side_matters,
        test_masked_token_ignores_the_background,
        test_challenger_pulls_us_into_the_attack_row,
        test_template_missing_is_honest,
        test_blocking_vs_attacking,
        test_attack_is_read_before_the_orb,
        test_side_beats_band,
        test_spell_stack,
        test_enemy_spell_is_read_wherever_it_lands,
        test_mulligan,
        test_menus_and_api_down,
        test_game_over_fires_once,
        test_final_result_waits_for_the_verdict,
        test_decklist_is_read_once_and_tells_what_is_left,
        test_champions_are_read_from_card_sets,
        test_button_label_confirms_a_response_window,
        test_card_model,
        test_un_mot_cle_lu_a_lecran_complete_la_carte_imprimee,
        test_un_mot_cle_lu_ne_retire_jamais_un_imprime,
        test_la_lecture_decran_est_vraiment_branchee,
        test_live_stats_override_base,
        test_live_stats_degrade_without_ocr,
        test_screen_costs_are_read_for_known_cards,
        test_screen_costs_degrade_when_ocr_fails,
        test_zone_bands_follow_nexus_geometry,
        test_badge_cache_separates_families,
        test_an_implausible_reading_is_refused,
        test_badge_cache_avoids_repeat_ocr,
        test_zones_never_keyerror,
        test_inspect_rejoue_le_classement_du_bot,
        test_une_redirection_ne_tue_plus_le_diagnostic,
    ):
        test()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) en échec :")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("Tous les tests passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
