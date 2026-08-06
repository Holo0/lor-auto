#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_combat.py

Tests de l'aiguillage de la boucle de combat, sans jeu ni souris.

On vérifie surtout ce qui est coûteux à reproduire en vrai : l'arrêt sur
fin de partie, la détection de blocage, le respect du mulligan manuel, et
le fait qu'aucune phase d'attente ne déclenche d'action.

    python test_combat.py
"""

from __future__ import annotations

import sys
import types

try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.FailSafeException = type("FailSafeException", (Exception,), {})
    stub.size = lambda: (1920, 1080)
    for name in ("screenshot", "moveTo", "click", "mouseDown", "mouseUp"):
        setattr(stub, name, lambda *a, **k: None)
    sys.modules["pyautogui"] = stub

import actions
import combat
from combat import CombatLoop, snapshot_signature
from game_state import Phase
from test_actions import DragRecorder, blocking_snapshot, snapshot_with, with_db, ALL_CARDS

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


class ScriptedReader:
    """Rejoue une suite d'états, puis répète le dernier indéfiniment."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.index = 0

    def stable_snapshot(self, **_):
        snapshot = self.sequence[min(self.index, len(self.sequence) - 1)]
        self.index += 1
        return snapshot

    def snapshot(self):
        return self.stable_snapshot()


class Spy:
    """Remplace une action et note ses appels."""

    def __init__(self, result=None):
        self.calls = 0
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.result


def make_loop(reader, **kwargs):
    kwargs.setdefault("poll", 0.0)
    kwargs.setdefault("max_duration", 5.0)
    loop = CombatLoop(reader=reader, **kwargs)
    return loop


def patched(**replacements):
    """Contexte simple pour remplacer des attributs de `actions`."""
    class _Ctx:
        def __enter__(self):
            self.saved = {k: getattr(actions, k) for k in replacements}
            for key, value in replacements.items():
                setattr(actions, key, value)
            return self

        def __exit__(self, *exc):
            for key, value in self.saved.items():
                setattr(actions, key, value)
            return False
    return _Ctx()


# ============================================================
# TESTS
# ============================================================

def test_stops_on_game_over():
    print("\nArrêt en fin de partie")

    with_db(ALL_CARDS)
    playing = snapshot_with(hand_codes=["UNIT_A"])
    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)
    object.__setattr__(over, "last_game_won", True)

    turn_spy = Spy(actions.ActionLog())
    with patched(play_turn=turn_spy):
        report = make_loop(ScriptedReader([playing, over])).run()

    check("partie marquée terminée", report.finished is True)
    check("victoire enregistrée", report.won is True, report.won)
    check("un tour joué avant l'arrêt", turn_spy.calls == 1, turn_spy.calls)
    check("raison renseignée", report.reason == "partie terminée", report.reason)


def test_waiting_phases_do_nothing():
    print("\nPhases d'attente")

    with_db(ALL_CARDS)
    waiting = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(waiting, "phase", Phase.OPPONENT_TURN)

    turn_spy, block_spy, click_spy = Spy(actions.ActionLog()), Spy(([], None, actions.ActionLog())), Spy()
    with patched(play_turn=turn_spy, execute_blocks=block_spy, click=click_spy):
        report = make_loop(ScriptedReader([waiting]), max_duration=0.6).run()

    check("aucun tour joué", turn_spy.calls == 0, turn_spy.calls)
    check("aucun blocage", block_spy.calls == 0, block_spy.calls)
    check("aucun clic", click_spy.calls == 0, click_spy.calls)
    check("arrêt sur la durée", "durée maximale" in report.reason, report.reason)


def test_dispatches_blocking():
    print("\nAiguillage vers le blocage")

    snap = blocking_snapshot(["BRUTE"], ["UNIT_A"])
    check("phase BLOCKING", snap.phase is Phase.BLOCKING, snap.phase)

    block_spy = Spy(([("b", "a")], snap, actions.ActionLog()))
    turn_spy = Spy(actions.ActionLog())
    with patched(execute_blocks=block_spy, play_turn=turn_spy):
        report = make_loop(ScriptedReader([snap]), dry_run=True).run()

    check("blocage déclenché", block_spy.calls == 1, block_spy.calls)
    check("aucun tour joué", turn_spy.calls == 0, turn_spy.calls)
    check("blocage compté", report.blocks == 1, report.blocks)


def test_manual_mulligan_by_default():
    print("\nMulligan manuel par défaut")

    with_db(ALL_CARDS)
    snap = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(snap, "phase", Phase.MULLIGAN)

    mulligan_spy, click_spy = Spy(actions.ActionLog()), Spy()
    with patched(do_mulligan=mulligan_spy, click=click_spy):
        report = make_loop(ScriptedReader([snap]), max_duration=0.6).run()

    # La position du bouton de validation n'étant pas vérifiée, cliquer
    # d'office gâcherait la main de départ.
    check("mulligan non automatisé", mulligan_spy.calls == 0, mulligan_spy.calls)
    check("aucun clic à l'aveugle", click_spy.calls == 0, click_spy.calls)
    check("consigne affichée", any("à toi de jouer" in e for e in report.log), report.log)

    with patched(do_mulligan=mulligan_spy, click=click_spy):
        make_loop(ScriptedReader([snap]), auto_mulligan=True, max_duration=0.6).run()
    check("automatisé si demandé", mulligan_spy.calls >= 1, mulligan_spy.calls)


def test_stuck_detection_aborts():
    print("\nDétection de blocage")

    snap = blocking_snapshot(["BRUTE"], ["UNIT_A"])

    # execute_blocks ne fait jamais progresser l'état : la signature reste
    # identique, la boucle doit finir par abandonner d'elle-même.
    block_spy = Spy(([], snap, actions.ActionLog()))
    click_spy = Spy()
    with patched(execute_blocks=block_spy, click=click_spy):
        report = make_loop(ScriptedReader([snap]), max_duration=30.0).run()

    check("arrêt sur blocage", "bloqué" in report.reason, report.reason)
    check("tentative de déblocage par un clic", click_spy.calls >= 1, click_spy.calls)
    check("pas de boucle infinie", block_spy.calls < combat.STUCK_ABORT + 5, block_spy.calls)


def test_signature_detects_real_progress():
    print("\nEmpreinte d'état")

    with_db(ALL_CARDS)
    first = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
    same = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
    played = snapshot_with(hand_codes=["UNIT_B"], board_codes=["UNIT_A"])

    check("états identiques -> même empreinte",
          snapshot_signature(first) == snapshot_signature(same))
    check("carte posée -> empreinte différente",
          snapshot_signature(first) != snapshot_signature(played))

    # Une carte qui change de zone à effectif constant est un progrès réel :
    # ne compter que les tailles le manquerait.
    moved = snapshot_with(board_codes=["UNIT_A"], attack_codes=["UNIT_B"])
    other = snapshot_with(board_codes=["UNIT_B"], attack_codes=["UNIT_A"])
    check("permutation entre zones détectée",
          snapshot_signature(moved) != snapshot_signature(other))


def test_plan_mode_touches_nothing():
    print("\nMode plan")

    with_db(ALL_CARDS)
    snap = snapshot_with(hand_codes=["UNIT_A"], board_codes=["UNIT_B"])
    recorder = DragRecorder()
    click_spy = Spy()

    with patched(drag=recorder, click=click_spy, read_mana_pool=lambda **_: _POOL):
        report = make_loop(ScriptedReader([snap]), dry_run=True).run()

    check("aucun glisser-déposer", recorder.drags == [], recorder.drags)
    check("aucun clic", click_spy.calls == 0, click_spy.calls)
    check("une seule itération", "mode plan" in report.reason, report.reason)
    check("décisions journalisées", len(report.log) > 1, report.log)


from mana import ManaPool
_POOL = ManaPool(mana=10, spell_mana=0)


def main():
    for test in (
        test_stops_on_game_over,
        test_waiting_phases_do_nothing,
        test_dispatches_blocking,
        test_manual_mulligan_by_default,
        test_stuck_detection_aborts,
        test_signature_detects_real_progress,
        test_plan_mode_touches_nothing,
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
