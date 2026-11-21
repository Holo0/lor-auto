#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_riposte.py

La réponse à un sort adverse est décidée d'après la MENACE lue, jamais
d'après le prix du sort qu'on a en main.

    python test_riposte.py
"""

from __future__ import annotations

from test_actions import (          # noqa: E402  (bouchons pyautogui inclus)
    ALL_CARDS, EN_MAIN, FakeReader, ManaPool, _record_gestures, variant_scene, with_db,
)
import actions
import riposte
from game_state import Phase

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def spell(name, text, cost=2, speed="Fast"):
    return {
        "name": name, "cost": cost, "attack": 0, "health": 0, "type": "Spell",
        "keywords": [speed], "keywordRefs": [speed], "spellSpeedRef": speed,
        "descriptionRaw": text,
    }


RIPOSTE_CARDS = {
    # Les siens
    "E_DEAL2":   spell("Coup de poignard", "Deal 2 to an enemy."),
    "E_DEAL5":   spell("Foudre", "Deal 5 to an enemy.", cost=4),
    "E_KILL":    spell("Exécution", "Kill an enemy.", cost=5),
    "E_DRAW":    spell("Pioche", "Draw 2.", cost=2, speed="Burst"),
    "E_BUFF":    spell("Élan", "Give an ally +3|+3 this round.", cost=2, speed="Burst"),
    "E_AOE":     spell("Avalanche", "Deal 2 to all units.", cost=4, speed="Slow"),
    "E_STUN":    spell("Entrave", "Stun an enemy.", cost=3),
    # Les nôtres
    "HP_BUFF":   spell("Cuirasse", "Give an ally +0|+3 this round.", cost=2, speed="Burst"),
    "BARRIER":   spell("Égide", "Give an ally Barrier this round.", cost=3, speed="Burst"),
    "SHIELD":    spell("Bouclier runique", "Grant an ally Spellshield.", cost=3, speed="Burst"),
    "COUNTER":   spell("Déni", "Stop a spell.", cost=4),
    "SKILL_CTR": spell("Contre-compétence", "Stop a skill.", cost=2),
    "PING":      spell("Éclat", "Deal 2 to an enemy.", cost=2),
    "BIG_BURN":  spell("Brasier", "Deal 6 to an enemy.", cost=6),
}


def scene(hand, stack_theirs, ours=(), theirs=(), engaged=()):
    """
    Notre main, SES sorts sur la pile, nos unités au banc, les siennes au
    banc ou engagées. Le camp est explicite partout.
    """
    with_db({**ALL_CARDS, **RIPOSTE_CARDS})
    specs, cid = [], 20
    for code in hand:
        cid += 1
        specs.append((code, cid, EN_MAIN, 400 + 140 * cid))
    for code in stack_theirs:
        cid += 1
        specs.append((code, cid, 0.48, 700 + 150 * cid, False))
    for code in ours:
        cid += 1
        specs.append((code, cid, 0.150, 400 + 130 * cid, True))
    for code in theirs:
        cid += 1
        specs.append((code, cid, 0.800, 400 + 130 * cid, False))
    for code in engaged:
        cid += 1
        specs.append((code, cid, 0.650, 400 + 130 * cid, False))
    snap = variant_scene(specs, "nous")
    assert snap.phase is Phase.SPELL_STACK, snap.phase
    return snap


def decide(snap, mana=10):
    pool = ManaPool(mana=mana, spell_mana=0)
    options = actions.response_options(snap, pool)
    plan_of = lambda c: actions.spell_is_castable(c, snap)[1:4]  # noqa: E731
    return riposte.choose_response(snap, options, plan_of)


def test_threat_is_read_from_the_enemy_text():
    print("\nLa menace se lit dans le texte du sort adverse")

    snap = scene(["HP_BUFF"], ["E_DEAL2"], ours=["UNIT_A", "UNIT_B"])
    threat = riposte.read_threats(snap)[0]
    check("Deal 2 : retrait", threat.kind == riposte.REMOVAL, threat)
    check("   seule l'unité à 1 PV est menacée",
          [c.code for c in threat.endangered] == ["UNIT_B"], threat.endangered)

    snap = scene([], ["E_KILL"], ours=["UNIT_A", "UNIT_B"])
    threat = riposte.read_threats(snap)[0]
    check("Kill : toutes nos unités sont menacées", len(threat.endangered) == 2, threat)

    snap = scene([], ["E_AOE"], ours=["UNIT_A", "UNIT_B"])
    threat = riposte.read_threats(snap)[0]
    check("Deal 2 to all units : zone", threat.aoe is True and threat.kind == riposte.REMOVAL, threat)

    snap = scene([], ["E_DRAW"], ours=["UNIT_A"])
    threat = riposte.read_threats(snap)[0]
    check("Draw 2 : rien à parer", threat.kind == riposte.NOTHING, threat)

    snap = scene([], ["E_BUFF"], theirs=["UNIT_B"])
    threat = riposte.read_threats(snap)[0]
    check("Give an ally +3|+3 : renfort adverse", threat.kind == riposte.BUFF, threat)


def test_protect_the_endangered_unit_not_the_biggest():
    print("\nProtéger l'unité MENACÉE, pas la plus grosse")

    # Deal 2 menace UNIT_B (2/1) ; UNIT_A (3/4) n'a rien à craindre.
    snap = scene(["HP_BUFF"], ["E_DEAL2"], ours=["UNIT_A", "UNIT_B"])
    response, why = decide(snap)
    check("on riposte", response is not None, why)
    unit_b = next(c for c in snap.board if c.code == "UNIT_B")
    check("   avec le +PV", response.card.code == "HP_BUFF", response)
    check("   sur UNIT_B, la menacée", response.targets == (unit_b.center,), response.targets)
    check("   et la raison le dit", "UNIT_B" in response.reason or "Ombre" in response.reason, response.reason)

    # Deal 5 menace les deux : on protège la plus précieuse si le +PV suffit.
    snap = scene(["HP_BUFF"], ["E_DEAL5"], ours=["UNIT_A", "UNIT_B"])
    response, why = decide(snap)
    unit_a = next(c for c in snap.board if c.code == "UNIT_A")
    check("Deal 5 : on protège la plus précieuse (4+3=7 > 5)",
          response is not None and response.targets == (unit_a.center,), (response, why))

    # Un +3 PV ne sauve pas UNIT_B (1+3=4 <= 5) et UNIT_A absente : on passe.
    snap = scene(["HP_BUFF"], ["E_DEAL5"], ours=["UNIT_B"])
    response, why = decide(snap)
    check("le +PV ne suffit pas : on passe", response is None, response)
    check("   et on dit pourquoi", "sauve" in why, why)

    # Barrier encaisse n'importe quels dégâts.
    snap = scene(["BARRIER"], ["E_DEAL5"], ours=["UNIT_B"])
    response, _ = decide(snap)
    check("Barrier sauve des 5 dégâts", response is not None and response.card.code == "BARRIER", response)

    # Contre Kill / Stun, seul Spellshield sert.
    snap = scene(["HP_BUFF", "BARRIER"], ["E_KILL"], ours=["UNIT_A"])
    response, why = decide(snap)
    check("Kill : ni +PV ni Barrier ne servent, on passe", response is None, response)
    snap = scene(["HP_BUFF", "SHIELD"], ["E_STUN"], ours=["UNIT_A"])
    response, _ = decide(snap)
    check("Stun : Spellshield, pas le +PV", response is not None and response.card.code == "SHIELD", response)


def test_counter_is_the_best_answer_and_targets_the_stack():
    print("\nLe contresort vise la pile")

    snap = scene(["HP_BUFF", "COUNTER"], ["E_DEAL2"], ours=["UNIT_B"])
    response, _ = decide(snap)
    enemy = snap.stack_theirs[-1]
    check("le contresort passe devant la protection",
          response is not None and response.card.code == "COUNTER", response)
    check("   il cible le sort adverse sur la pile", response.targets == (enemy.center,), response.targets)

    # Un contresort trop cher n'est pas une option.
    response, _ = decide(snap, mana=3)
    check("sans le mana du contresort : la protection", response is not None and response.card.code == "HP_BUFF", response)

    # « Stop a skill » ne contre pas un SORT.
    snap = scene(["SKILL_CTR"], ["E_DEAL2"], ours=["UNIT_A"])
    response, _ = decide(snap)
    check("« Stop a skill » ne contre pas un sort", response is None, response)


def test_no_useful_answer_means_pass():
    print("\nSans parade utile, on garde son mana")

    # Il pioche : on ne gaspille pas Brasier, même jouable.
    snap = scene(["BIG_BURN", "PING"], ["E_DRAW"], ours=["UNIT_A"], theirs=["UNIT_B"])
    response, why = decide(snap)
    check("il pioche : on passe", response is None, response)
    check("   la raison parle de mana gardé", "mana" in why, why)

    # Il nous vise, on n'a que des dégâts en main : rien à protéger, on passe.
    snap = scene(["PING"], ["E_DEAL2"], ours=["UNIT_B"], theirs=["UNIT_B"])
    response, _ = decide(snap)
    check("rien qui protège : on passe", response is None, response)


def test_fizzle_their_buff_when_the_target_is_obvious():
    print("\nFaire tomber son renfort dans le vide")

    # Une seule unité adverse ENGAGÉE : c'est elle qu'il renforce.
    snap = scene(["PING"], ["E_BUFF"], ours=["UNIT_A"], theirs=["UNIT_A"], engaged=["UNIT_B"])
    response, why = decide(snap)
    engaged = snap.enemy_attack_row[0]
    check("on retire l'attaquant qu'il renforce",
          response is not None and response.kind == "retirer", (response, why))
    check("   la cible est l'unité engagée", response and response.targets == (engaged.center,), response)

    # Deux unités, aucune engagée : cible inconnue, on passe.
    snap = scene(["PING"], ["E_BUFF"], theirs=["UNIT_A", "UNIT_B"])
    response, why = decide(snap)
    check("cible du renfort inconnue : on passe", response is None and "identifiable" in why, why)

    # Nos 2 dégâts ne tuent pas un 3/4 : on passe.
    snap = scene(["PING"], ["E_BUFF"], engaged=["UNIT_A"])
    response, why = decide(snap)
    check("nos dégâts ne suffisent pas : on passe", response is None, (response, why))


def test_respond_to_stack_uses_the_riposte():
    print("\nrespond_to_stack lance la riposte choisie, avec SA cible")

    snap = scene(["HP_BUFF"], ["E_DEAL2"], ours=["UNIT_A", "UNIT_B"])
    unit_b = next(c for c in snap.board if c.code == "UNIT_B")
    saved_mana, saved_play = actions.read_mana_pool, actions.play_spell
    actions.read_mana_pool = lambda **_: ManaPool(mana=10, spell_mana=0)
    lances = []
    actions.play_spell = (lambda reader, s, card, dry_run=False, forced=None:
                          lances.append((card.code, forced)) or (True, s))
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        log = actions.respond_to_stack(FakeReader([snap]), snap, allow_spells=True)
    finally:
        restore()
        actions.read_mana_pool, actions.play_spell = saved_mana, saved_play
    check("le +PV est lancé", [c for c, _ in lances] == ["HP_BUFF"], lances)
    check("   avec la cible imposée : UNIT_B",
          lances and lances[0][1][1] == (unit_b.center,), lances)
    check("   aucun clic de passe (play_spell valide)", clics == [], clics)
    check("   le journal explique la menace et la riposte",
          any("Menace" in e for e in log.entries) and any("Riposte" in e for e in log.entries), log.entries)


def main():
    for test in (
        test_threat_is_read_from_the_enemy_text,
        test_protect_the_endangered_unit_not_the_biggest,
        test_counter_is_the_best_answer_and_targets_the_stack,
        test_no_useful_answer_means_pass,
        test_fizzle_their_buff_when_the_target_is_obvious,
        test_respond_to_stack_uses_the_riposte,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) en échec :")
        for name in FAILURES:
            print(f"  - {name}")
        raise SystemExit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
