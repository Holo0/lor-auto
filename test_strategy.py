"""
Tests de strategy.py — le profil du deck et ce qu'il change dans les
décisions (`actions.plan_attack`, `CombatLoop`).

    python test_strategy.py

Hors ligne : ni souris, ni jeu, ni OCR.
"""

from __future__ import annotations

import sys

# Le stub pyautogui, l'horloge virtuelle et le journal neutralisé sont
# posés par test_combat à l'import.
import test_combat  # noqa: F401
from test_combat import ScriptedReader, make_loop, patched

import actions
import strategy
from game_state import Phase
from test_actions import ALL_CARDS, KEYWORD_CARDS, with_db
from test_game_state import (
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


def card(name, cost, kind="Unit", text="", keywords=(), supertype="", attack=2, health=2):
    return {
        "name": name, "cost": cost, "attack": attack, "health": health, "type": kind,
        "keywords": list(keywords), "keywordRefs": list(keywords), "descriptionRaw": text,
        "supertype": supertype, "regionRefs": ["Demacia"],
    }


# Trois decks caricaturaux, à 2 exemplaires par carte (24 cartes).
AGGRO_DB = {
    "A1": card("Éclaireur", 1, text="Attack: Deal 1 to the enemy Nexus.", attack=2, health=1),
    "A2": card("Coureur", 2, keywords=["Elusive"]),
    "A3": card("Brute", 2, keywords=["Overwhelm"], attack=3, health=2),
    "A4": card("Ziggs", 3, text="Attack: I deal 1 damage to my blocker and the enemy Nexus.",
               supertype="Champion"),
    "A5": card("Lucian", 1, keywords=["QuickStrike"], supertype="Champion"),
    "A6": card("Coup", 1, "Spell", "Give an ally +1|+1 this round."),
    "A7": card("Sbire", 1),
    "A8": card("Nexus Strike", 2, text="Nexus Strike: Draw 1."),
    "A9": card("Frappe", 2, "Spell", "Deal 2 to the enemy Nexus."),
    "A10": card("Aile", 2, keywords=["Elusive"]),
    "A11": card("Bélier", 3, keywords=["Overwhelm"]),
    "A12": card("Lancier", 2, keywords=["QuickStrike"]),
}
PULL_DB = {
    "P1": card("Provocateur", 3, keywords=["Challenger"]),
    "P2": card("Chasseur", 3, text="Play: Grant an enemy Vulnerable."),
    "P3": card("Jarvan IV", 6, text="When you attack, pay my cost to summon me Challenging the strongest enemy.",
               supertype="Champion", attack=6, health=4),
    "P4": card("Cataclysme", 3, "Spell", "An ally starts a free attack Challenging an enemy."),
    "P5": card("Duel", 3, "Spell", "Give an enemy -2|-0 this round. An ally and that enemy strike each other."),
    "P6": card("Fileur", 4, text="Play: Grant an enemy -1|-0 and Vulnerable."),
    "P7": card("Cavalier", 4, keywords=["Challenger"]),
    "P8": card("Mercenaire", 2, text="When I'm summoned, grant the strongest enemy Vulnerable."),
    "P9": card("Garde", 3),
    "P10": card("Mur", 4, attack=2, health=6),
    "P11": card("Nasus", 6, supertype="Champion", attack=3, health=3),
    "P12": card("Colosse", 5, attack=5, health=5),
}
CONTROL_DB = {
    "C1": card("Vaporisation", 2, "Spell", "Kill a unit."),
    "C2": card("Gel", 3, "Spell", "Frostbite an enemy."),
    "C3": card("Assommoir", 3, "Spell", "Stun an enemy and Curse it with Shackles."),
    "C4": card("Éclair", 3, "Spell", "Deal 3 to a unit."),
    "C5": card("Métamorphose", 6, "Spell", "Transform a unit into a 3|3 Mini-Minitee and Silence it."),
    "C6": card("Pioche", 2, "Spell", "Draw 2."),
    "C7": card("Silence", 4, "Spell", "Silence an enemy."),
    "C8": card("Sentinelle", 4, attack=3, health=5),
    "C9": card("Titan", 6, attack=6, health=6),
    "C10": card("Gardien", 5, attack=4, health=5),
    "C11": card("Karma", 5, supertype="Champion", attack=3, health=4),
    "C12": card("Soigneur", 4, attack=2, health=5),
}


def deck_of(db):
    return {code: 2 for code in db}


def test_archetypes_are_recognised():
    print("\nProfil du deck : trois plans de jeu, et le reste en midrange")

    aggro = strategy.profile_deck(deck_of(AGGRO_DB), AGGRO_DB)
    check("deck agressif → aggro", aggro.name == "aggro", (aggro.name, strategy.scores(strategy.read_signals(deck_of(AGGRO_DB), AGGRO_DB))))
    check("   champions relevés", set(aggro.champions) == {"Ziggs", "Lucian"}, aggro.champions)
    check("   un dégât au nexus vaut 2 à pleine santé", aggro.nexus_base_weight == 2.0)
    check("   plancher d'attaque négatif", aggro.attack_floor < 0)
    check("   mulligan plus sévère", aggro.mulligan_max_cost == 2)

    pull = strategy.profile_deck(deck_of(PULL_DB), PULL_DB)
    check("Challenger + Vulnerable → tirage", pull.name == "tirage",
          (pull.name, strategy.scores(strategy.read_signals(deck_of(PULL_DB), PULL_DB))))

    control = strategy.profile_deck(deck_of(CONTROL_DB), CONTROL_DB)
    check("retraits + courbe haute → contrôle", control.name == "controle",
          (control.name, strategy.scores(strategy.read_signals(deck_of(CONTROL_DB), CONTROL_DB))))
    check("   mulligan plus tolérant", control.mulligan_max_cost == 4)

    # Un deck sans signal net reste midrange : ni timide ni suicidaire.
    plain = {f"M{i}": card(f"Unité {i}", 2 + i % 4) for i in range(12)}
    mid = strategy.profile_deck(deck_of(plain), plain)
    check("sans signal → midrange", mid.name == "midrange", mid.name)

    # Sans deck ou sans base : l'ancien comportement, à l'identique.
    check("deck vide → défaut", strategy.profile_deck({}, AGGRO_DB) is strategy.DEFAULT)
    check("base absente → défaut", strategy.profile_deck(deck_of(AGGRO_DB), {}) is strategy.DEFAULT)
    check("None → défaut", strategy.profile_deck(None, None) is strategy.DEFAULT)
    unknown = strategy.profile_deck({"ZZ001": 2, "ZZ002": 2}, AGGRO_DB)
    check("codes tous inconnus → midrange, sans planter", unknown.name == "midrange", unknown.name)
    check("la description se lit", "aggro" in aggro.describe() or "agressif" in aggro.describe(),
          aggro.describe())


def test_attack_trigger_detection():
    print("\nDéclencheur « Attack: »")
    check("« Attack: » en tête de texte", strategy.has_attack_trigger(
        {"descriptionRaw": "Attack: Plant 3 Chimes in your deck."}))
    check("« Attack: » après une ligne", strategy.has_attack_trigger(
        {"descriptionRaw": "Origin: The Wandering Caretaker.\r\nAttack: Plant 3 Chimes in your deck."}))
    check("« When you attack » n'en est pas un", not strategy.has_attack_trigger(
        {"descriptionRaw": "When you attack, pay my cost to summon me."}))
    check("« Nexus Strike » non plus", not strategy.has_attack_trigger(
        {"descriptionRaw": "Nexus Strike: Draw 1."}))
    check("texte vide", not strategy.has_attack_trigger({"descriptionRaw": ""}))


def pressure_board():
    """Trois 4/3 face à un 3/5 et un 1/5 — le plateau du chantier 5."""
    with_db({**ALL_CARDS, **KEYWORD_CARDS,
             "FOUR3": card("Quatre-trois", 3, attack=4, health=3),
             "BARD43": card("Barde", 3, attack=4, health=3,
                            text="Attack: Plant 3 Chimes in your deck."),
             "WALL35": card("Mur", 4, attack=3, health=5),
             "SPONGE15": card("Éponge", 3, attack=1, health=5)})
    rects, card_id = list(nexus_rects()), 300
    for index in range(3):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code="FOUR3", card_id=card_id, x=400 + 130 * index))
    rects.append(rect_at_ratio(0.800, code="WALL35", card_id=900, local=False, x=600))
    rects.append(rect_at_ratio(0.800, code="SPONGE15", card_id=901, local=False, x=760))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


def test_the_strategy_changes_the_attack():
    """
    Même plateau qu'au chantier 5 : un seul attaquant passe, 4 dégâts pour
    une unité perdue (7). À 30 PV adverses, la stratégie par défaut garde
    le banc (poids 1,33 : -7 + 5,3) ; un deck agressif attaque (poids 2 :
    -7 + 8 = +1). Et le plancher n'achète jamais une attaque qui ne touche
    pas le nexus.
    """
    print("\nLa stratégie change l'attaque, à plateau égal")
    snap = pressure_board()

    actions.set_strategy(strategy.DEFAULT)
    kept, _, why = actions.plan_attack(snap, 30)
    check("défaut, 30 PV : on garde le banc", kept == [], why)

    engaged, report, why = actions.plan_attack(snap, 30, strategy.AGGRO)
    check("aggro, 30 PV : on attaque", len(engaged) == 3, (why, len(engaged)))
    check("   le motif nomme la stratégie", "[aggro]" in why, why)
    check("   et le poids 2", "vaut 2.0" in why, why)

    # La stratégie courante est celle qu'on a fixée, sans la passer.
    actions.set_strategy(strategy.AGGRO)
    engaged, _, why = actions.plan_attack(snap, 30)
    check("STRATEGY courante appliquée", len(engaged) == 3, why)
    actions.set_strategy(None)
    check("set_strategy(None) → défaut", actions.STRATEGY is strategy.DEFAULT)
    kept, _, why = actions.plan_attack(snap, 30)
    check("   et le banc reste en défense", kept == [], why)

    # Le plancher : bilan -1 accepté SEULEMENT si des dégâts passent.
    flat = strategy.Strategy("test", "test", nexus_base_weight=1.0, attack_floor=-2.0)
    engaged, report, why = actions.plan_attack(snap, None, flat)
    check("plancher -2, PV inconnus : perdre 7 pour 4 reste refusé (-3)", engaged == [], why)
    floor = strategy.Strategy("test", "test", nexus_base_weight=1.0, attack_floor=-3.0)
    engaged, report, why = actions.plan_attack(snap, None, floor)
    check("plancher -3 : accepté parce que 4 dégâts passent",
          len(engaged) == 3 and report["nexus_damage"] == 4, (why, report and report["nexus_damage"]))

    # Sans dégât au nexus, le plancher ne joue pas : un 4/3 seul face à un
    # 3/5 et un 1/5 est bloqué, ne tue rien, et le plancher -10 ne l'envoie pas.
    with_db({**ALL_CARDS, **KEYWORD_CARDS,
             "FOUR3": card("Quatre-trois", 3, attack=4, health=3),
             "WALL35": card("Mur", 4, attack=3, health=5),
             "SPONGE15": card("Éponge", 3, attack=1, health=5)})
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.150, code="FOUR3", card_id=301, x=400))
    rects.append(rect_at_ratio(0.800, code="WALL35", card_id=900, local=False, x=600))
    rects.append(rect_at_ratio(0.800, code="SPONGE15", card_id=901, local=False, x=760))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    alone = state_reader().snapshot()
    suicidal = strategy.Strategy("test", "test", attack_floor=-10.0)
    engaged, _, why = actions.plan_attack(alone, None, suicidal)
    check("aucun dégât au nexus : le plancher n'achète rien", engaged == [], why)


def test_attack_triggers_weigh_in_the_balance():
    print("\nUn « Attack: » qui part compte dans le bilan")
    with_db({**ALL_CARDS, **KEYWORD_CARDS,
             "BARD43": card("Barde", 3, attack=4, health=3,
                            text="Attack: Plant 3 Chimes in your deck."),
             "WALL35": card("Mur", 4, attack=3, health=5)})
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.150, code="BARD43", card_id=301, x=400))
    rects.append(rect_at_ratio(0.800, code="WALL35", card_id=900, local=False, x=600))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = state_reader().snapshot()
    ours = list(actions.attackers_available(snap))
    theirs = [c for c in snap.enemy_board if c.is_unit]

    plain = actions.evaluate_attack(ours, theirs)
    bonus = actions.evaluate_attack(ours, theirs, None, 1.0, 1.0)
    check("sans bonus : aucun déclencheur compté", plain["triggers"] == 0 and plain["profit"] == -7,
          plain)
    check("avec bonus : un déclencheur, +1 au bilan", bonus["triggers"] == 1 and bonus["profit"] == -6,
          bonus)


def deck_snapshot(decklist, db):
    with_db({**ALL_CARDS, **db})
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.150, code="UNIT_A", card_id=301, x=400))
    install_fakes(rects, screen=make_screen(orb_active=True, token=None), decklist=decklist)
    return state_reader().snapshot()


def test_the_combat_loop_reads_the_deck():
    """
    La boucle lit la decklist dès qu'elle est visible, fixe
    `actions.STRATEGY`, journalise l'archétype et les champions, passe le
    seuil de mulligan — et repart de DEFAULT à chaque combat.
    """
    print("\nLa boucle de combat déduit la stratégie du deck")

    snap = deck_snapshot(deck_of(AGGRO_DB), AGGRO_DB)
    check("le deck est dans l'instantané", bool(snap.deck), snap.deck)
    object.__setattr__(snap, "phase", Phase.MULLIGAN)

    seen = {}

    def mulligan_spy(reader, snapshot, max_cost=actions.MULLIGAN_MAX_COST, dry_run=False):
        seen["max_cost"] = max_cost
        return actions.ActionLog()

    actions.set_strategy(strategy.CONTROL)      # un reste du combat précédent
    with patched(do_mulligan=mulligan_spy, mulligan_is_calibrated=lambda: True):
        reader = ScriptedReader([snap])
        reader.card_db = {**ALL_CARDS, **AGGRO_DB}
        loop = make_loop(reader, max_duration=0.6)
        report = loop.run()
    check("archétype journalisé", loop.config.get("archetype") == "aggro", loop.config)
    check("champions journalisés", loop.config.get("champions") == "Ziggs, Lucian", loop.config)
    check("STRATEGY fixée pour le combat", actions.STRATEGY.name == "aggro", actions.STRATEGY)
    check("le rapport l'annonce", any(e.startswith("Stratégie :") for e in report.log), report.log[:6])
    check("mulligan au seuil de la stratégie", seen.get("max_cost") == 2, seen)

    # Sans decklist : DEFAULT, et le reste du combat précédent est effacé.
    snap2 = deck_snapshot(None, AGGRO_DB)
    object.__setattr__(snap2, "phase", Phase.MULLIGAN)
    with patched(do_mulligan=mulligan_spy, mulligan_is_calibrated=lambda: True):
        loop = make_loop(ScriptedReader([snap2]), max_duration=0.6)
        loop.run()
    check("sans decklist : stratégie par défaut", actions.STRATEGY is strategy.DEFAULT, actions.STRATEGY)
    check("   rien de journalisé", "archetype" not in loop.config, loop.config)
    check("   mulligan au seuil par défaut", seen.get("max_cost") == actions.MULLIGAN_MAX_COST, seen)
    actions.set_strategy(None)


def main() -> int:
    for test in (
        test_archetypes_are_recognised,
        test_attack_trigger_detection,
        test_the_strategy_changes_the_attack,
        test_attack_triggers_weigh_in_the_balance,
        test_the_combat_loop_reads_the_deck,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} échec(s) : {', '.join(FAILURES)}")
        return 1
    print("Tous les tests de stratégie passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
