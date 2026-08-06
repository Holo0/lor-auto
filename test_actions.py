#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_actions.py

Tests de la couche de décision et de pose, SANS souris, SANS OCR et SANS
le jeu. Le mana est injecté à la main, les instantanés sont fabriqués, et
le glisser-déposer est remplacé par un enregistreur.

Ça permet de vérifier les cas qui coûtent cher à reproduire en jeu : une
pose qui échoue, un banc plein, une carte inconnue, la règle du mana de
sort.

    python test_actions.py
"""

from __future__ import annotations

import sys
import types

# --- bouchons pour tourner sans écran -----------------------------------
try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.size = lambda: (1920, 1080)
    stub.screenshot = lambda *a, **k: None
    stub.moveTo = lambda *a, **k: None
    stub.click = lambda *a, **k: None
    stub.mouseDown = lambda *a, **k: None
    stub.mouseUp = lambda *a, **k: None
    sys.modules["pyautogui"] = stub

import actions
import game_state

# L'enrichissement OCR est neutralisé : ces tests portent sur la DÉCISION,
# et les stats voulues sont déjà injectées via la base de cartes simulée.
actions.enrich_with_live_stats = lambda snapshot, *a, **k: snapshot
from actions import (
    choose_card_to_play,
    free_board_slots,
    play_card,
    play_hand,
    playable_cards,
)
from game_state import Phase
from mana import ManaPool, can_pay
from test_game_state import (
    CARD_DB,
    WINDOW,
    install_fakes,
    make_screen,
    nexus_rects,
    rect_at_ratio,
    reader as state_reader,
)

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ============================================================
# OUTILLAGE
# ============================================================

EXTRA_CARDS = {
    "UNIT_BIG": {
        "name": "Colosse", "cost": 6, "attack": 8, "health": 8,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "UNIT_TWIN": {
        "name": "Jumeaux", "cost": 3, "attack": 2, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Invoque un allié supplémentaire.",
    },
    "GEAR_A": {
        "name": "Lame Runique", "cost": 1, "attack": 0, "health": 0,
        "type": "Equipment", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
}
FULL_DB = {**CARD_DB, **EXTRA_CARDS}


def snapshot_with(hand_codes=(), board_codes=(), attack_codes=()):
    """Fabrique un instantané avec la main et le banc demandés."""
    rects, card_id = list(nexus_rects()), 100

    for index, code in enumerate(hand_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.029, code=code, card_id=card_id,
                                   height=330, x=500 + 140 * index))
    for index, code in enumerate(board_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id,
                                   x=500 + 130 * index))
    for index, code in enumerate(attack_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.320, code=code, card_id=card_id,
                                   x=500 + 130 * index))

    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


class FakeReader:
    """Renvoie une suite d'instantanés préparés, sans toucher au jeu."""

    def __init__(self, sequence, resolved=None):
        self.sequence = list(sequence)
        self.resolved = resolved
        self.calls = 0

    def stable_snapshot(self, **_):
        self.calls += 1
        if self.sequence:
            return self.sequence.pop(0)
        raise AssertionError("stable_snapshot appelé plus que prévu")

    def snapshot(self):
        """Utilisé par l'attente de résolution du combat."""
        if self.resolved is not None:
            return self.resolved
        return self.stable_snapshot()


class DragRecorder:
    """Remplace le glisser-déposer et note les gestes demandés."""

    def __init__(self):
        self.drags = []

    def __call__(self, source, destination):
        self.drags.append((source, destination))


def with_db(db):
    """Recharge la base de cartes utilisée par les instantanés."""
    import test_game_state
    test_game_state.CARD_DB.clear()
    test_game_state.CARD_DB.update(db)


# ============================================================
# TESTS
# ============================================================

def test_mana_rule():
    print("\nRègle du mana de sort")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "SPELL_A"])
    unit = next(c for c in snap.hand if c.code == "UNIT_A")     # coût 3
    spell = next(c for c in snap.hand if c.code == "SPELL_A")   # coût 1

    # 2 mana + 3 mana de sort = 5 au total, mais une unité à 3 n'est PAS
    # jouable : le mana de sort ne paie que les sorts.
    pool = ManaPool(mana=2, spell_mana=3)
    check("unité non payable avec du mana de sort", can_pay(unit, pool) is False)
    check("sort payable avec du mana de sort", can_pay(spell, pool) is True)

    check("unité payable avec assez de mana de tour", can_pay(unit, ManaPool(mana=3, spell_mana=0)))
    check("mana illisible -> rien n'est payable",
          can_pay(unit, ManaPool(mana=None, spell_mana=3)) is False)


def test_choice_order_and_filters():
    print("\nChoix de la carte")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "UNIT_B", "UNIT_BIG", "SPELL_A", "GEAR_A"])
    pool = ManaPool(mana=10, spell_mana=3)

    options = playable_cards(snap, pool)
    names = [c.name for c in options]
    check("la plus chère d'abord", names[0] == "Colosse", names)
    check("sorts exclus par défaut", "Éclair" not in names, names)
    check("équipements exclus", "Lame Runique" not in names, names)
    check("unités conservées", {"Garde de Fer", "Ombre Fuyante"} <= set(names), names)

    with_spells = [c.name for c in playable_cards(snap, pool, allow_spells=True)]
    check("sorts inclus si demandé", "Éclair" in with_spells, with_spells)

    # Mana serré : seules les cartes payables restent.
    tight = [c.name for c in playable_cards(snap, ManaPool(mana=2, spell_mana=0))]
    check("filtre par le mana disponible", tight == ["Ombre Fuyante"], tight)

    check("aucune option -> None",
          choose_card_to_play(snap, ManaPool(mana=0, spell_mana=0)) is None)


def test_unknown_card_is_not_played():
    print("\nCarte absente de card_sets")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "TOKEN_INCONNU"])
    options = playable_cards(snap, ManaPool(mana=10, spell_mana=0))
    codes = [c.code for c in options]

    # Elle est bien VUE (elle compte dans le plateau), mais son coût est
    # inconnu : la jouer serait un pari sur une donnée absente.
    check("carte inconnue visible en main", len(snap.hand) == 2, snap.hand)
    check("carte inconnue jamais choisie", "TOKEN_INCONNU" not in codes, codes)


def test_board_limit():
    print("\nLimite du banc")

    with_db(FULL_DB)
    pool = ManaPool(mana=10, spell_mana=0)

    snap = snapshot_with(hand_codes=["UNIT_A"], board_codes=["UNIT_A"] * 4,
                         attack_codes=["UNIT_B"] * 2)
    check("rangée d'attaque comptée dans le banc", free_board_slots(snap) == 0,
          (len(snap.board), len(snap.attack_row)))
    check("banc plein -> rien de jouable", playable_cards(snap, pool) == [])

    # Une carte qui invoque un allié supplémentaire a besoin de 2 places.
    snap = snapshot_with(hand_codes=["UNIT_TWIN", "UNIT_A"], board_codes=["UNIT_A"] * 5)
    names = [c.name for c in playable_cards(snap, pool)]
    check("1 place libre", free_board_slots(snap) == 1, free_board_slots(snap))
    check("carte à 2 corps écartée", "Jumeaux" not in names, names)
    check("carte à 1 corps gardée", "Garde de Fer" in names, names)


def test_grab_point_is_on_screen():
    print("\nPoint de saisie")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A"])
    card = snap.hand[0]
    left, top, right, bottom = card.box
    centre_y = (top + bottom) // 2

    # Le cœur du problème : une carte en main dépasse sous l'écran, donc
    # son centre géométrique est hors cadre et cliquer là ne touche rien.
    check("le centre de la carte est hors écran", centre_y > WINDOW.height, centre_y)
    check("le point de saisie est dans l'écran", 0 <= card.grab_point[1] < WINDOW.height,
          card.grab_point)
    check("le point de saisie est sur la carte", top <= card.grab_point[1] <= bottom,
          (top, card.grab_point[1], bottom))

    target = actions.drop_point(card, snap.window)
    check("dépôt à la verticale de la saisie", target[0] == card.grab_point[0], target)
    check("dépôt au-dessus de la saisie", target[1] < card.grab_point[1], target)
    # Le dépôt vise la rangée d'ATTAQUE, pas le banc : c'est la zone que
    # le client accepte pour poser une carte.
    low, high = game_state.zone_band("attack")
    ratio_from_bottom = 1.0 - target[1] / WINDOW.height
    check("dépôt dans la bande d'attaque", low < ratio_from_bottom < high,
          (ratio_from_bottom, low, high))
    check("dépôt hors de la bande du banc",
          not (game_state.zone_band("board")[0] < ratio_from_bottom
               < game_state.zone_band("board")[1]),
          ratio_from_bottom)


def test_play_card_verifies_result():
    print("\nVérification de la pose")

    with_db(FULL_DB)
    before = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
    after_ok = snapshot_with(hand_codes=["UNIT_B"], board_codes=["UNIT_A"])
    card = next(c for c in before.hand if c.code == "UNIT_A")

    recorder = DragRecorder()
    original_drag = actions.drag
    actions.drag = recorder
    try:
        success, latest = play_card(FakeReader([after_ok]), before, card)
        check("pose réussie détectée", success is True)
        check("un seul geste effectué", len(recorder.drags) == 1, recorder.drags)
        check("carte absente de la main après", len(latest.hand) == 1, latest.hand)

        # Échec : la main ne change pas. Deux tentatives, puis abandon —
        # sans quoi le bot rejouerait le même geste indéfiniment.
        unchanged = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
        recorder = DragRecorder()
        actions.drag = recorder
        success, _ = play_card(
            FakeReader([unchanged, unchanged]), before, card, attempts=2
        )
        check("pose ratée détectée", success is False)
        check("exactement 2 tentatives", len(recorder.drags) == 2, len(recorder.drags))
    finally:
        actions.drag = original_drag


def test_play_hand_stops_on_failure():
    print("\nBoucle de pose")

    with_db(FULL_DB)
    stuck = snapshot_with(hand_codes=["UNIT_A"])

    recorder = DragRecorder()
    original_drag, original_mana = actions.drag, actions.read_mana_pool
    actions.drag = recorder
    actions.read_mana_pool = lambda **_: ManaPool(mana=10, spell_mana=0)
    try:
        # La main ne change jamais : la pose échoue systématiquement.
        played, _, _ = play_hand(FakeReader([stuck] * 20), stuck, max_plays=8)
        check("aucune carte posée", played == [], played)
        # 2 tentatives pour la carte, puis mise de côté : la boucle ne
        # doit pas consommer ses 8 itérations sur la même carte.
        check("abandon après mise de côté", len(recorder.drags) == 2, len(recorder.drags))
    finally:
        actions.drag, actions.read_mana_pool = original_drag, original_mana


def test_attackers_selection():
    print("\nChoix des attaquants")

    with_db(FULL_DB)
    # SPELL_A a 0 d'attaque, UNIT_B a « Can't Block » mais peut attaquer.
    snap = snapshot_with(board_codes=["UNIT_BIG", "UNIT_A", "UNIT_B", "SPELL_A"])
    names = [c.name for c in actions.attackers_available(snap)]

    check("le plus gros en premier", names[0] == "Colosse", names)
    check("0 d'attaque écarté", "Éclair" not in names, names)
    check("Can't Block peut quand même attaquer", "Ombre Fuyante" in names, names)
    check("3 attaquants retenus", len(names) == 3, names)


def test_attack_needs_token():
    print("\nAttaque et jeton")

    with_db(FULL_DB)
    rects = nexus_rects() + [rect_at_ratio(0.150, code="UNIT_A", card_id=1)]

    # Sans jeton, on ne doit RIEN faire : le bouton de confirmation est au
    # même endroit que celui de fin de tour, un clic à tort passe le tour.
    install_fakes(rects, screen=make_screen(orb_active=True, token="adversaire"))
    snap = state_reader().snapshot()
    check("phase DEFEND_TURN", snap.phase is Phase.DEFEND_TURN, snap.phase)

    recorder = DragRecorder()
    clicks = []
    original_drag, original_click = actions.drag, actions.click
    actions.drag = recorder
    actions.click = lambda *a, **k: clicks.append(a)
    try:
        engaged, _, log = actions.declare_attack(FakeReader([]), snap)
        check("aucune unité engagée sans jeton", engaged == [], engaged)
        check("aucun geste souris", recorder.drags == [], recorder.drags)
        check("aucun clic de confirmation", clicks == [], clicks)
        check("raison journalisée", any("jeton" in e for e in log.entries), log.entries)
    finally:
        actions.drag, actions.click = original_drag, original_click


def test_attack_does_not_confirm_when_nothing_engaged():
    print("\nConfirmation seulement si engagement")

    with_db(FULL_DB)
    stuck = snapshot_with(board_codes=["UNIT_A"])
    check("phase ATTACK_TURN", stuck.phase is Phase.ATTACK_TURN, stuck.phase)

    recorder = DragRecorder()
    clicks = []
    original_drag, original_click = actions.drag, actions.click
    actions.drag = recorder
    actions.click = lambda *a, **k: clicks.append(a)
    try:
        # Le banc ne se vide jamais : l'engagement échoue.
        engaged, _, log = actions.declare_attack(FakeReader([stuck] * 5), stuck)
        check("aucune unité engagée", engaged == [], engaged)
        check("un geste tenté", len(recorder.drags) == 1, recorder.drags)
        # Le point critique : sans attaquant, ce clic terminerait le tour.
        check("pas de clic de confirmation", clicks == [], clicks)
        check("raison journalisée",
              any("passerait le tour" in e for e in log.entries), log.entries)
    finally:
        actions.drag, actions.click = original_drag, original_click


BLOCK_CARDS = {
    "ELUSIVE": {
        "name": "Spectre", "cost": 3, "attack": 3, "health": 2,
        "type": "Unit", "keywords": ["Elusive"], "keywordRefs": ["Elusive"],
        "descriptionRaw": "",
    },
    "FEARSOME": {
        "name": "Terreur", "cost": 4, "attack": 4, "health": 3,
        "type": "Unit", "keywords": ["Fearsome"], "keywordRefs": ["Fearsome"],
        "descriptionRaw": "",
    },
    "SMALL": {
        "name": "Recrue", "cost": 1, "attack": 1, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "WALL": {
        "name": "Muraille", "cost": 4, "attack": 1, "health": 7,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "BRUTE": {
        "name": "Brute", "cost": 5, "attack": 5, "health": 5,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "NOBLOCK": {
        "name": "Éclaireur", "cost": 2, "attack": 3, "health": 3,
        "type": "Unit", "keywords": ["Can't Block"], "keywordRefs": ["CantBlock"],
        "descriptionRaw": "",
    },
}
ALL_CARDS = {**FULL_DB, **BLOCK_CARDS}


def blocking_snapshot(board_codes, enemy_codes):
    """Instantané en phase de blocage : eux dans la rangée d'attaque, nous au banc."""
    with_db(ALL_CARDS)
    rects, card_id = list(nexus_rects()), 200

    for index, code in enumerate(board_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=500 + 130 * index))
    for index, code in enumerate(enemy_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.650, code=code, card_id=card_id,
                                   local=False, x=500 + 130 * index))

    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    return state_reader().snapshot()


def test_blocking_rules():
    print("\nRègles de blocage")

    snap = blocking_snapshot(["SMALL", "ELUSIVE", "BRUTE", "NOBLOCK"], ["ELUSIVE"])
    check("phase BLOCKING", snap.phase is Phase.BLOCKING, snap.phase)

    by_code = {c.code: c for c in snap.board}
    elusive_attacker = snap.enemy_attack_row[0]

    check("insaisissable non bloquable par une unité normale",
          actions.can_block_attacker(by_code["BRUTE"], elusive_attacker) is False)
    check("insaisissable bloquable par une insaisissable",
          actions.can_block_attacker(by_code["ELUSIVE"], elusive_attacker) is True)
    check("Can't Block ne bloque jamais",
          actions.can_block_attacker(by_code["NOBLOCK"], elusive_attacker) is False)

    # Redoutable : 3 d'attaque minimum.
    snap = blocking_snapshot(["SMALL", "BRUTE"], ["FEARSOME"])
    by_code = {c.code: c for c in snap.board}
    fearsome = snap.enemy_attack_row[0]
    check("redoutable non bloquable à 1 d'attaque",
          actions.can_block_attacker(by_code["SMALL"], fearsome) is False)
    check("redoutable bloquable à 5 d'attaque",
          actions.can_block_attacker(by_code["BRUTE"], fearsome) is True)


def test_block_scoring():
    print("\nQualité des blocages")

    snap = blocking_snapshot(["WALL", "BRUTE", "SMALL"], ["UNIT_A"])
    by_code = {c.code: c for c in snap.board}
    attacker = snap.enemy_attack_row[0]     # Garde de Fer 3/4

    # Brute 5/5 : tue le 3/4 et survit à ses 3 dégâts.
    check("tuer et survivre = 3",
          actions.block_score(by_code["BRUTE"], attacker) == actions.BLOCK_KILL_AND_SURVIVE)
    # Muraille 1/7 : survit largement mais ne tue pas.
    check("survivre sans tuer = 2",
          actions.block_score(by_code["WALL"], attacker) == actions.BLOCK_SURVIVE)
    # Recrue 1/2 : meurt et ne tue pas.
    check("mourir sans tuer = 0",
          actions.block_score(by_code["SMALL"], attacker) == actions.BLOCK_CHUMP)


def test_block_plan_prefers_small_at_equal_value():
    print("\nChoix du bloqueur")

    # Muraille 1/7 et Brute 5/5 survivent toutes deux à une Recrue 1/2,
    # mais seule la Brute la tue : elle doit être préférée.
    snap = blocking_snapshot(["WALL", "BRUTE"], ["SMALL"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("un blocage planifié", len(pairs) == 1, pairs)
    check("meilleur score choisi", pairs[0][0].code == "BRUTE", pairs[0][0].code)
    check("aucun dégât ne passe", leaking == 0, leaking)

    # Deux murailles équivalentes en valeur : la plus petite est engagée,
    # pour garder la grosse comme attaquante.
    snap = blocking_snapshot(["WALL", "UNIT_A"], ["SMALL"])
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    engaged = pairs[0][0]
    check("à valeur égale, la plus petite bloque",
          engaged.attack + engaged.health <= 7, str(engaged))


def test_no_chump_block_when_safe():
    print("\nPas de sacrifice inutile")

    # Recrue 1/2 face à une Brute 5/5 : elle meurt sans rien tuer.
    snap = blocking_snapshot(["SMALL"], ["BRUTE"])
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=20)

    check("aucun blocage sacrificiel", pairs == [], pairs)
    check("dégâts assumés", leaking == 5, leaking)
    check("raison chiffrée", "20 PV" in reason, reason)


def test_chump_block_when_lethal():
    print("\nSacrifice si létal")

    snap = blocking_snapshot(["SMALL"], ["BRUTE"])
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=4)

    check("blocage sacrificiel accepté", len(pairs) == 1, pairs)
    check("plus aucun dégât", leaking == 0, leaking)
    check("raison explicite", "létal" in reason, reason)

    # PV inconnus : on ne sacrifie pas, mais on le signale.
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=None)
    check("PV illisibles -> pas de sacrifice", pairs == [], pairs)
    check("incertitude signalée", "illisibles" in reason, reason)

    # Option explicite : sacrifier même hors situation létale.
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20, allow_chump=True)
    check("option chump respectée", len(pairs) == 1, pairs)


def test_one_blocker_per_attacker():
    print("\nUn bloqueur par attaquant")

    snap = blocking_snapshot(["BRUTE", "WALL"], ["UNIT_A", "UNIT_A"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)

    check("deux blocages", len(pairs) == 2, pairs)
    blockers = [b.card_id for b, _ in pairs]
    attackers = [a.card_id for _, a in pairs]
    check("aucun bloqueur réutilisé", len(set(blockers)) == 2, blockers)
    check("aucun attaquant doublé", len(set(attackers)) == 2, attackers)
    check("rien ne passe", leaking == 0, leaking)

    # Plus d'attaquants que de bloqueurs : le plus dangereux est traité
    # en premier, le reste passe.
    snap = blocking_snapshot(["BRUTE"], ["SMALL", "UNIT_A"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("le plus dangereux est bloqué", pairs[0][1].code == "UNIT_A", pairs[0][1].code)
    check("les dégâts restants sont comptés", leaking == 1, leaking)


def test_block_confirms_even_with_nothing():
    print("\nConfirmation du blocage")

    resolved = blocking_snapshot(["SMALL"], [])      # combat terminé
    snap = blocking_snapshot(["SMALL"], ["BRUTE"])   # aucun blocage rentable
    clicks = []
    recorder = DragRecorder()
    original_drag, original_click = actions.drag, actions.click
    original_health = actions.read_nexus_health
    actions.drag = recorder
    actions.click = lambda *a, **k: clicks.append(a)
    actions.read_nexus_health = lambda **_: 20
    try:
        done, _, log = actions.execute_blocks(
            FakeReader([snap] * 4, resolved=resolved), snap
        )
        check("aucun blocage effectué", done == [], done)
        check("aucun drag", recorder.drags == [], recorder.drags)
        # Contrairement à l'attaque : le jeu ATTEND une réponse, et « je ne
        # bloque rien » en est une. Ne pas cliquer figerait la partie.
        check("confirmation quand même envoyée", len(clicks) == 1, clicks)
        check("décision journalisée", any("dégâts" in e for e in log.entries), log.entries)
    finally:
        actions.drag, actions.click = original_drag, original_click
        actions.read_nexus_health = original_health


def test_play_hand_respects_phase():
    print("\nRespect de la phase")

    with_db(FULL_DB)
    rects = nexus_rects() + [rect_at_ratio(0.029, code="UNIT_A", card_id=1, height=330)]
    install_fakes(rects, screen=make_screen(orb_active=False, token="nous"))
    snap = state_reader().snapshot()

    check("phase lue OPPONENT_TURN", snap.phase is Phase.OPPONENT_TURN, snap.phase)

    recorder = DragRecorder()
    original_drag = actions.drag
    actions.drag = recorder
    try:
        played, _, log = play_hand(FakeReader([]), snap)
        check("rien joué pendant le tour adverse", played == [], played)
        check("aucun geste souris", recorder.drags == [], recorder.drags)
        check("raison journalisée", any("pas à nous" in e for e in log.entries), log.entries)
    finally:
        actions.drag = original_drag


def main():
    for test in (
        test_mana_rule,
        test_choice_order_and_filters,
        test_unknown_card_is_not_played,
        test_board_limit,
        test_grab_point_is_on_screen,
        test_play_card_verifies_result,
        test_play_hand_stops_on_failure,
        test_attackers_selection,
        test_attack_needs_token,
        test_attack_does_not_confirm_when_nothing_engaged,
        test_blocking_rules,
        test_block_scoring,
        test_block_plan_prefers_small_at_equal_value,
        test_no_chump_block_when_safe,
        test_chump_block_when_lethal,
        test_one_blocker_per_attacker,
        test_block_confirms_even_with_nothing,
        test_play_hand_respects_phase,
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
