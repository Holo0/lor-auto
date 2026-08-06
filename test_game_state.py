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

import tempfile
from pathlib import Path

import cv2
import numpy as np

import lor_api
import game_state
from game_state import (
    TURN_ORB_REGION,
    ZONE_ANCHOR_RATIO,
    GameStateReader,
    Phase,
    classify_zone,
)
from lor_api import Window

WINDOW = Window(0, 0, 1920, 1080)

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
        "descriptionRaw": "Inflige 2 dégâts.",
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


def install_fakes(rectangles, game_state_str="InProgress", screen=None, game_result=None):
    """Remplace les accès au monde extérieur par des valeurs contrôlées."""
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


def test_zones_never_keyerror():
    print("\nRobustesse")
    install_fakes(nexus_rects())
    snap = reader().snapshot()
    for name in game_state.ZONE_ORDER:
        check(f"zone '{name}' toujours présente", snap.zones[name] == ())
    check("phase is_our_move cohérente", Phase.OPPONENT_TURN.is_our_move is False)
    check("MENUS n'est pas in_game", Phase.MENUS.in_game is False)
    check("BLOCKING est in_game", Phase.BLOCKING.in_game is True)


def main():
    for test in (
        test_coordinate_conversion,
        test_zone_bands,
        test_phase_our_turn,
        test_token_side_matters,
        test_template_missing_is_honest,
        test_blocking_vs_attacking,
        test_spell_stack,
        test_mulligan,
        test_menus_and_api_down,
        test_game_over_fires_once,
        test_card_model,
        test_live_stats_override_base,
        test_live_stats_degrade_without_ocr,
        test_zones_never_keyerror,
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
