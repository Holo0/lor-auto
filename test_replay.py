#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_replay.py — enregistrer ce que le bot voit, puis le rejouer à l'identique.

    python test_replay.py

Hors ligne : le « jeu » est simulé par les fausses entrées de
test_game_state (API, écran, résultat), l'enregistrement passe par
`replay.Recorder`, et le rejeu doit rendre exactement les mêmes
instantanés — phase, cartes, zones — sans le jeu.
"""

from __future__ import annotations

import ast
import gc
import io
import json
import sys
import tempfile
from pathlib import Path

import replay                       # installe le pyautogui factice si besoin
import actions
import lor_api
from game_state import Phase

# UNE SUITE HORS LIGNE NE LAISSE RIEN DERRIÈRE ELLE (09/11/2026).
# `actions.journaliser_pile_bloquee` écrit un PNG dans `screenshots/`
# quand un sort reste sur la pile — et le rejeu d'une vraie trace passe
# par `play_spell`. `capture_screen_bgr` est bien bouchonné ici, donc
# l'écran d'Ewan n'est pas photographié, mais l'écran SYNTHÉTIQUE serait
# quand même écrit sur disque, exactement comme `save_stuck_screen` l'a
# fait 621 fois dans `test_combat`. On garde les appels.
PILES_BLOQUEES = []
actions.journaliser_pile_bloquee = (
    lambda snapshot, card: PILES_BLOQUEES.append((snapshot, card)) or "")
from test_game_state import (
    CARD_DB, install_fakes, make_screen, nexus_rects, rect_at_ratio, reader as state_reader,
)

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def board_rects(unit_ratio=0.75):
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(unit_ratio, code="UNIT_A", card_id=101, x=500))
    rects.append(rect_at_ratio(0.029, code="UNIT_B", card_id=102, height=330, x=700))
    return rects


def install_world(world: dict):
    """
    Comme install_fakes, mais les fonctions LISENT `world` à chaque appel :
    on peut changer l'écran ou l'API entre deux lectures sans remplacer les
    fonctions — donc sans passer sous l'enregistreur déjà branché.
    """
    install_fakes(world["rects"], screen=world["screen"], game_result=world["result"],
                  decklist=world.get("deck"))
    payload = lor_api.get_positional_rectangles()
    lor_api.get_positional_rectangles = lambda: dict(payload, Rectangles=world["rects"])
    lor_api.capture_screen_bgr = lambda: world["screen"]
    lor_api.get_game_result = lambda: world["result"]


def record_two_frames(directory):
    """Deux lectures : notre tour (orbe bleue), puis tour adverse (orbe grise)."""
    world = {"rects": board_rects(), "screen": make_screen(orb_active=True, token="nous"),
             "result": {"GameID": 7, "LocalPlayerWon": True}, "deck": {"UNIT_A": 3}}
    install_world(world)
    recorder = replay.Recorder(directory).install()
    try:
        reader = state_reader()
        first = reader.snapshot()
        world["screen"] = make_screen(orb_active=False)
        second = reader.snapshot()
    finally:
        recorder.close()
    return first, second


def test_record_then_replay_gives_the_same_snapshots():
    print("\nEnregistrer puis rejouer rend les mêmes instantanés")
    with tempfile.TemporaryDirectory() as tmp:
        first, second = record_two_frames(tmp)
        check("phases enregistrées lisibles",
              first.phase is Phase.ATTACK_TURN and second.phase is Phase.OPPONENT_TURN,
              (first.phase, second.phase))

        events = [json.loads(l) for l in (Path(tmp) / replay.EVENTS_FILE).read_text(encoding="utf8").splitlines()]
        kinds = [e["k"] for e in events]
        check("deux lectures d'API", kinds.count("api") == 2, kinds)
        check("les captures sont là", kinds.count("screen") >= 2, kinds)
        pngs = sorted(p.name for p in Path(tmp).glob("*.png"))
        check("deux captures différentes -> deux fichiers", len(pngs) == 2, pngs)

        frames = replay.load_frames(tmp)
        check("deux frames", len(frames) == 2, len(frames))
        check("chaque frame a sa capture", all(f.screens for f in frames), [f.screens for f in frames])
        check("le deck est rattaché à la première lecture",
              frames[0].deck and frames[0].deck["CardsInDeck"] == {"UNIT_A": 3}, frames[0].deck)

        # Rejeu FIXÉ sur chaque lecture : même phase, mêmes cartes.
        replayer = replay.Replayer(tmp, fixed=True)
        with replayer:
            reader = state_reader()
            replayer.seek(0)
            again = reader.snapshot()
            check("lecture 0 rejouée : même phase", again.phase is first.phase, again.phase)
            check("lecture 0 rejouée : mêmes cartes",
                  [c.code for c in again.cards()] == [c.code for c in first.cards()],
                  [c.code for c in again.cards()])
            check("lecture 0 rejouée : jeton vu", again.attack_token is True, again.attack_token)
            replayer.seek(1)
            again = reader.snapshot()
            check("lecture 1 rejouée : tour adverse", again.phase is Phase.OPPONENT_TURN, again.phase)
            check("fixé : relire ne bouge pas", reader.snapshot().phase is Phase.OPPONENT_TURN)
        check("désinstallé : lor_api rendu", lor_api.get_positional_rectangles is not replayer._api)

        # Rejeu qui AVANCE : une lecture par appel, puis épuisé.
        replayer = replay.Replayer(tmp, fixed=False)
        with replayer:
            reader = state_reader()
            phases = [reader.snapshot().phase for _ in range(2)]
            check("avance : les deux phases dans l'ordre",
                  phases == [Phase.ATTACK_TURN, Phase.OPPONENT_TURN], phases)
            check("puis épuisé", replayer.exhausted)


def test_missing_pieces_fall_back_to_the_last_known():
    print("\nCe qui manque à une lecture vient de la précédente")
    with tempfile.TemporaryDirectory() as tmp:
        record_two_frames(tmp)
        # On retire la capture et la fenêtre de la seconde lecture.
        path = Path(tmp) / replay.EVENTS_FILE
        events = [json.loads(l) for l in path.read_text(encoding="utf8").splitlines()]
        seen_api = 0
        kept = []
        for event in events:
            if event["k"] == "api":
                seen_api += 1
            if seen_api == 2 and event["k"] in ("screen", "window", "deck"):
                continue
            kept.append(event)
        path.write_text("\n".join(json.dumps(e) for e in kept) + "\n", encoding="utf8")

        replayer = replay.Replayer(tmp, fixed=True).seek(1)
        with replayer:
            check("fenêtre reprise", lor_api.get_window().width == 1920)
            check("capture reprise", lor_api.capture_screen_bgr() is not None)
            check("deck repris", lor_api.get_static_decklist()["CardsInDeck"] == {"UNIT_A": 3})
            snap = state_reader().snapshot()
            check("l'instantané se construit quand même", snap.phase.in_game, snap.phase)


def test_api_errors_are_replayed_as_such():
    print("\nUne API absente est rejouée absente")
    with tempfile.TemporaryDirectory() as tmp:
        def down():
            raise lor_api.ApiUnavailable("jeu fermé")
        install_fakes(board_rects())
        lor_api.get_positional_rectangles = down
        recorder = replay.Recorder(tmp).install()
        try:
            snap = state_reader().snapshot()
        finally:
            recorder.close()
        check("enregistré comme NO_API", snap.phase is Phase.NO_API, snap.phase)

        replayer = replay.Replayer(tmp, fixed=True)
        with replayer:
            check("rejoué comme NO_API", state_reader().snapshot().phase is Phase.NO_API)
            check("la trace le dit", replayer.frame.game_state == "NO_API", replayer.frame.game_state)


def test_start_recording_is_idempotent_and_restores():
    print("\nstart_recording : une seule fois, et lor_api rendu à la fin")
    install_fakes(board_rects())
    before = lor_api.get_positional_rectangles
    with tempfile.TemporaryDirectory() as tmp:
        first = replay.start_recording(tmp)
        second = replay.start_recording(Path(tmp) / "autre")
        check("le second appel rend le premier dossier", first == second, (first, second))
        check("lor_api enveloppé", lor_api.get_positional_rectangles is not before)
        replay.stop_recording()
        check("lor_api rendu", lor_api.get_positional_rectangles is before)
        check("un second stop est sans effet", replay.stop_recording() is None)



# ============================================================
# LA SORTIE DANS UN TUBE
# ============================================================

LIGNE_QUI_TUE = "  deck : 24 cartes, ≤ 19 à piocher"
# La vraie ligne, telle que `GameSnapshot.summary()` l'écrit
# (game_state.py:1504). Le « ≤ » n'existe pas en cp1252.


def _flux_cp1252(tampon):
    """Un stdout comme Python en fabrique un quand la sortie part dans un tube."""
    return io.TextIOWrapper(tampon, encoding="cp1252", errors="strict",
                            line_buffering=True)


class _FluxRecalcitrant(io.TextIOWrapper):
    """Un flux dont `reconfigure` refuse — le cas qui mène au repli.

    C'est exactement le `ValueError` que `sortie_en_utf8` rattrape : une
    capture de banc d'essai, ou un `TextIOWrapper` détaché.
    """

    def reconfigure(self, **_):
        raise ValueError("ce flux ne se reconfigure pas")


def test_la_sortie_tient_dans_un_tube_cp1252():
    """
    09/11/2026 — `replay.py` est l'outil du projet qu'on REDIRIGE le plus,
    et il mourait dès que la lecture portait un deck.

    Mesuré, `PYTHONIOENCODING=cp1252` et stdout dans un fichier, sur
    `traces/combat_20261104_200516` :

        replay.py list    → code 0  (aucun « ≤ » dans ce tableau)
        replay.py show 40 → code 1, UnicodeEncodeError '≤' pos. 93
        replay.py monitor → code 1, UnicodeEncodeError '≤' pos. 79

    Le caractère vient d'une seule ligne, « deck : N cartes, ≤ M à
    piocher » (`GameSnapshot.summary()`), et elle passe par TROIS
    impressions de `replay.py` : `cmd_show`, `cmd_monitor`, et le
    « --- déroulé --- » de `cmd_combat` (les lignes « [état] » que
    `CombatLoop._describe_stuck` verse dans `report.log` — mesuré : sur
    4 lignes de journal, 1 est hors cp1252, et c'est celle-là).
    """
    print("\nLa sortie de replay.py tient dans un tube cp1252")
    vrai = sys.stdout
    constats = []
    try:
        # 1. LE DÉFAUT EXISTE : sans parade, cette ligne tue le processus.
        tampon = io.BytesIO()
        sys.stdout = _flux_cp1252(tampon)
        try:
            print(LIGNE_QUI_TUE)
            constats.append(("sans parade, un tube cp1252 refuse la ligne", False, "rien levé"))
        except UnicodeEncodeError as exc:
            constats.append(("sans parade, un tube cp1252 refuse la ligne", True, exc.object[:0]))

        # 2. AVEC LA PARADE : la ligne part, et elle part en UTF-8.
        tampon = io.BytesIO()
        sys.stdout = _flux_cp1252(tampon)
        replay.sortie_en_utf8()
        print(LIGNE_QUI_TUE)
        sys.stdout.flush()
        octets = tampon.getvalue()
        constats.append(("avec la parade, la ligne est écrite", b"" != octets, octets[:20]))
        constats.append(("et elle est en UTF-8",
                         octets.decode("utf-8").strip() == LIGNE_QUI_TUE.strip(),
                         octets))

        # 3. LE PIÈGE DU REPLI : quand `reconfigure` refuse, on réemballe le
        #    tampon — et si personne ne garde l'ancien emballage, son
        #    `__del__` FERME le tampon qu'on vient de reprendre. L'erreur
        #    tomberait au premier print, à mille lieues de sa cause.
        tampon = io.BytesIO()
        sys.stdout = _FluxRecalcitrant(tampon, encoding="cp1252", errors="strict")
        replay.sortie_en_utf8()
        gc.collect()            # l'ancien emballage n'est plus référencé que par la parade
        try:
            print(LIGNE_QUI_TUE)
            sys.stdout.flush()
            ok, detail = True, None
        except ValueError as exc:
            ok, detail = False, exc
        constats.append(("le repli ne ferme pas le tampon qu'il reprend", ok, detail))
        if ok:
            constats.append(("le repli écrit lui aussi en UTF-8",
                             tampon.getvalue().decode("utf-8").strip() == LIGNE_QUI_TUE.strip(),
                             tampon.getvalue()))

        # 4. Un flux sans `buffer` et sans `reconfigure` est laissé tel quel :
        #    la seule chose interdite, c'est de faire tomber l'outil.
        class _Muet:
            def write(self, _): return 0
            def flush(self): pass
        sys.stdout = _Muet()
        try:
            replay.sortie_en_utf8()
            constats.append(("un flux exotique ne fait pas tomber l'outil", True, None))
        except Exception as exc:        # noqa: BLE001
            constats.append(("un flux exotique ne fait pas tomber l'outil", False, exc))
    finally:
        sys.stdout = vrai

    for label, ok, detail in constats:
        check(label, ok, detail)


def test_la_parade_est_le_premier_geste_de_main():
    """
    « AVANT TOUT LE RESTE » n'est pas une formule : les commandes de
    `replay.py` importent `game_state`, `actions` et `combat` au fil de
    l'eau, et le moindre avertissement d'import doit déjà sortir en
    UTF-8. La parade est donc la PREMIÈRE instruction de `main()`, et
    c'est ce que ce test verrouille — sinon elle redevient une ligne
    qu'un correctif voisin déplace sans s'en apercevoir.
    """
    print("\nLa parade est le premier geste de main()")
    arbre = ast.parse(Path(replay.__file__).read_text(encoding="utf-8"))
    fonctions = [n for n in arbre.body
                 if isinstance(n, ast.FunctionDef) and n.name == "main"]
    check("replay.main existe", len(fonctions) == 1, fonctions)
    if not fonctions:
        return
    premier = fonctions[0].body[0]
    appel = (isinstance(premier, ast.Expr) and isinstance(premier.value, ast.Call)
             and getattr(premier.value.func, "id", None) == "sortie_en_utf8")
    check("sortie_en_utf8() est la première instruction de main()",
          appel, ast.dump(premier)[:120])


def main():
    for test in (
        test_record_then_replay_gives_the_same_snapshots,
        test_missing_pieces_fall_back_to_the_last_known,
        test_api_errors_are_replayed_as_such,
        test_start_recording_is_idempotent_and_restores,
        test_la_sortie_tient_dans_un_tube_cp1252,
        test_la_parade_est_le_premier_geste_de_main,
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
