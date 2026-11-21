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
import tempfile
import time
from pathlib import Path
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

# La boucle de combat temporise entre deux itérations : hors ligne, ces
# attentes sont fictives (cf. test_clock.py).
from test_clock import install_virtual_clock

install_virtual_clock()

import actions
import combat
import sortie_utf8
import journal
 
# Les tests ne doivent pas écrire dans le vrai journal.
_REAL_RECORD = journal.record
journal.record = lambda *a, **k: {}

# NI DANS `screenshots/`. `_check_progress` photographie l'écran à chaque
# palier de blocage, et cette suite pousse la boucle jusqu'aux paliers
# exprès : la capture partait donc pour de vrai. Elle ne montrait même
# pas le jeu — `capture_screen_bgr` est bouchonné et rend l'écran
# SYNTHÉTIQUE des tests, soit 1,5 Mo de gris uniforme écrit à chaque
# exécution. Mesuré le 09/11/2026 : **621 des 660 `bloque_*.png` du
# dossier (94 %, 0,98 Go) venaient d'ici**, 4 de plus à chaque
# `check.py --offline` — et le dossier où l'on va chercher un vrai
# blocage était noyé sous son propre bruit.
#
# On GARDE les appels plutôt que de les jeter : un test vérifie déjà que
# la capture est DEMANDÉE au bon moment, et il doit pouvoir continuer.
CAPTURES_DE_BLOCAGE = []
combat.save_stuck_screen = lambda phase: (
    CAPTURES_DE_BLOCAGE.append(phase) or f"screenshots/bloque_{phase}.png")
from combat import CombatLoop, snapshot_signature
from game_state import Phase
from test_actions import DragRecorder, blocking_snapshot, snapshot_with, with_db, ALL_CARDS
from test_game_state import (
    install_fakes,
    make_screen,
    nexus_rects,
    rect_at_ratio,
    reader as state_reader,
)
 
# CE QUE DURE UNE ITÉRATION GELÉE, EN VRAI — mesuré, pas supposé.
# Entre « Rien ne bouge depuis 12 lectures » et « Toujours bloqué » il y a
# exactement 13 itérations, et les deux lignes sont horodatées dans
# `logs/`. Sur les 21 blocages qui s'y trouvent (19 en ATTACKING le
# 06/09/2026, 2 en SPELL_STACK le 05/11) : médiane 4,19 s, étendue
# 3,74-4,30. C'est l'étalon de la conversion lectures -> secondes.
DUREE_ITERATION_GELEE = 4.19

FAILURES = []
 
 
def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)
 
 
class ScriptedReader:
    """Rejoue une suite d'états, puis répète le dernier indéfiniment."""
 
    def __init__(self, sequence, cout_lecture: float = 0.0):
        self.sequence = list(sequence)
        self.index = 0
        # CE QU'UNE LECTURE D'ÉTAT COÛTE EN VRAI, et qui ne coûte rien ici.
        # Hors ligne, `stable_snapshot` rend un instantané tout fait : une
        # itération ne dure que son `time.sleep(poll)`. En jeu elle dure
        # DEUX fois plus — deux appels d'API, deux captures d'écran et la
        # recherche multi-échelle du jeton, plus les 0,6 s de confirmation
        # de `stable_snapshot` : 2,2 s mesurées (cf. `combat.DUREE_LECTURE`).
        # Tant que les bornes de blocage comptaient des LECTURES, l'écart
        # ne se voyait pas. Maintenant qu'elles comptent des SECONDES, un
        # test qui ne paie pas la lecture mesure une boucle qui n'existe
        # pas : on la fait payer ici, à l'horloge fictive.
        self.cout_lecture = cout_lecture
 
    def stable_snapshot(self, **_):
        snapshot = self.sequence[min(self.index, len(self.sequence) - 1)]
        self.index += 1
        if self.cout_lecture:
            time.sleep(self.cout_lecture)
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
 
 
def rejouer_gel(loop, snapshot, jusqua, duree=DUREE_ITERATION_GELEE):
    """
    Rejoue des lectures IDENTIQUES jusqu'à `jusqua` secondes d'immobilité.

    La première pose la signature et ne compte pas, comme dans la boucle.
    Chaque suivante est précédée d'une itération complète d'horloge : la
    patience se dépense en secondes, pas en lectures.
    """
    loop._check_progress(snapshot)
    lectures = 0
    while loop._immobile < jusqua and lectures < 500:
        time.sleep(duree)
        lectures += 1
        if not loop._check_progress(snapshot):
            break
    return lectures


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
 
def challenged_snapshot():
    """
    L'adversaire attaque, et son Challenger TIRE une de nos unités en face
    de lui : notre rangée d'attaque se remplit sans qu'on ait rien
    déclaré. Jeton introuvable — c'est le cas où la vision ne tranche pas.
    """
    with_db(ALL_CARDS)
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.150, code="SMALL", card_id=301, x=500))
    rects.append(rect_at_ratio(0.320, code="BRUTE", card_id=302, x=640))
    rects.append(rect_at_ratio(0.650, code="BRUTE", card_id=303, local=False, x=640))
    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    return state_reader().snapshot()


def test_challenger_is_not_our_attack():
    """
    LA BOUCLE SAIT CE QU'ELLE A DÉCLARÉ, ET ÇA SUFFIT À TRANCHER.

    « ATTACKING » dit que notre rangée est avancée, pas que c'est nous qui
    attaquons : un Challenger tire une de nos unités en face de lui. Le
    20/08/2026, la boucle a attendu une résolution qui ne venait pas
    pendant que le jeu réclamait des bloqueurs — jusqu'à la durée
    maximale.

    Ce test ne se repose sur AUCUNE lecture d'écran : le jeton est
    introuvable dans l'instantané, exactement comme quand la vision ne
    tranche pas.
    """
    print("\nChallenger : requalifier une fausse attaque")

    tire = challenged_snapshot()
    check("l'état brut est bien lu ATTACKING", tire.phase is Phase.ATTACKING, tire.phase)

    loop = make_loop(ScriptedReader([tire]))

    loop._we_attacked = True
    check("attaque déclarée : on n'y touche pas",
          loop._reconsider_attacking(tire).phase is Phase.ATTACKING)

    loop._we_attacked = None
    check("dans le doute non plus (boucle lancée en cours de combat)",
          loop._reconsider_attacking(tire).phase is Phase.ATTACKING)

    loop._we_attacked = False
    requalifie = loop._reconsider_attacking(tire)
    check("rien de déclaré depuis un plateau dégagé -> BLOCKING",
          requalifie.phase is Phase.BLOCKING, requalifie.phase)
    check("le reste de l'instantané est intact",
          requalifie.zones is tire.zones and requalifie.window is tire.window)

    # Et le plateau dégagé remet bien le compteur à zéro.
    calme = snapshot_with(hand_codes=["UNIT_A"])
    loop._we_attacked = True
    loop._reconsider_attacking(calme)
    check("plateau dégagé -> on n'a plus rien déclaré",
          loop._we_attacked is False, loop._we_attacked)


def test_challenger_triggers_a_block():
    """Le parcours complet : la boucle finit par bloquer, pas par attendre."""
    print("\nChallenger : la boucle bloque au lieu d'attendre")

    calme = snapshot_with(hand_codes=["UNIT_A"])
    tire = challenged_snapshot()

    turn_spy = Spy(actions.ActionLog())
    block_spy = Spy(([("bloqueur",)], None, actions.ActionLog()))
    with patched(play_turn=turn_spy, execute_blocks=block_spy, click=Spy(),
                 cancel_pending_action=Spy()):
        report = make_loop(ScriptedReader([calme, tire]), max_duration=30.0).run()

    check("le blocage a été exécuté", block_spy.calls >= 1, block_spy.calls)
    check("requalification journalisée",
          any("Challenger" in e for e in report.log), report.log[-3:])


def test_spell_stack_is_answered_not_played_through():
    """
    La boucle aiguille SPELL_STACK vers la réponse à la pile — jamais vers
    le tour de jeu. Orbe grise : on attend sans cliquer.
    """
    print("\nSort sur la pile : on répond, on ne joue pas par-dessus")

    with_db(ALL_CARDS)
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.029, code="UNIT_A", card_id=501, height=330, x=500))
    rects.append(rect_at_ratio(0.48, code="SPELL_A", card_id=502, local=False, x=900))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    pile = state_reader().snapshot()
    check("l'état est bien lu SPELL_STACK", pile.phase is Phase.SPELL_STACK, pile.phase)

    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)

    turn_spy = Spy(actions.ActionLog())
    respond_spy = Spy(actions.ActionLog())
    with patched(play_turn=turn_spy, respond_to_stack=respond_spy, click=Spy()):
        make_loop(ScriptedReader([pile, over])).run()
    check("la réponse à la pile a été appelée", respond_spy.calls == 1, respond_spy.calls)
    check("le tour de jeu, lui, n'a pas été lancé", turn_spy.calls == 0, turn_spy.calls)

    # Orbe grise : même aiguillage, et le vrai respond_to_stack ne clique pas.
    install_fakes(rects, screen=make_screen(orb_active=False, token="nous"))
    grise = state_reader().snapshot()
    check("orbe grise : toujours SPELL_STACK", grise.phase is Phase.SPELL_STACK, grise.phase)
    click_spy = Spy()
    with patched(play_turn=turn_spy, click=click_spy):
        report = make_loop(ScriptedReader([grise, over])).run()
    check("aucun clic pendant que l'adversaire décide", click_spy.calls == 0, click_spy.calls)
    check("le journal dit qu'on attend",
          any("priorité" in e for e in report.log), report.log[-3:])


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
 
 
def test_waits_for_the_game_to_start():
    print("\nAttente du démarrage de la partie")
 
    with_db(ALL_CARDS)
    loading = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(loading, "phase", Phase.MENUS)
    playing = snapshot_with(hand_codes=["UNIT_A"])
    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)
    object.__setattr__(over, "last_game_won", True)
 
    # C'ÉTAIT LE BUG : après le clic sur « Combat », le client reste en
    # `Menus` pendant le chargement. La boucle y voyait une fin de partie
    # et rendait la main sans jouer un seul tour.
    turn_spy = Spy(actions.ActionLog())
    with patched(play_turn=turn_spy):
        report = make_loop(
            ScriptedReader([loading, loading, playing, over]), max_duration=10.0
        ).run()
 
    check("un tour a bien été joué", turn_spy.calls == 1, turn_spy.calls)
    check("partie reconnue terminée", report.finished is True, report.reason)
    check("chargement journalisé",
          any("démarrage" in e for e in report.log), report.log)
 
 
def test_gives_up_if_the_game_never_starts():
    print("\nLa partie ne démarre jamais")
 
    with_db(ALL_CARDS)
    loading = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(loading, "phase", Phase.MENUS)
 
    turn_spy = Spy(actions.ActionLog())
    with patched(play_turn=turn_spy):
        loop = make_loop(ScriptedReader([loading]), max_duration=10.0)
        loop.wait_for_game_start = lambda timeout=0.0: CombatLoop.wait_for_game_start(loop, 0.4)
        report = loop.run()
 
    check("aucun tour joué", turn_spy.calls == 0, turn_spy.calls)
    check("raison explicite", "n'a pas démarré" in report.reason, report.reason)
 
 
def test_a_silent_api_is_named_as_such():
    """
    04/11/2026 : le jeu affichait le mulligan du boss final — la partie
    AVAIT démarré — pendant que le bot attendait 120 s, annonçait « la
    partie n'a pas démarré » puis cherchait « Continuer ». Le port 21337
    était fermé. Le motif doit désigner la panne, pas la partie : c'est
    lui qui fait s'arrêter la session au lieu de brûler les tentatives
    hebdomadaires une à une.
    """
    print("\nL'API muette est nommée")

    with_db(ALL_CARDS)
    muet = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(muet, "phase", Phase.NO_API)

    turn_spy = Spy(actions.ActionLog())
    with patched(play_turn=turn_spy):
        loop = make_loop(ScriptedReader([muet]), max_duration=10.0)
        loop.wait_for_game_start = lambda timeout=0.0: CombatLoop.wait_for_game_start(loop, 0.4)
        report = loop.run()

    check("aucun tour joué", turn_spy.calls == 0, turn_spy.calls)
    check("le rapport porte le drapeau", report.api_down is True, report.api_down)
    check("le motif nomme l'API", "API du client injoignable" in report.reason, report.reason)
    check("   et le port", "21337" in report.reason, report.reason)
    check("il ne dit PAS « la partie n'a pas démarré »",
          "n'a pas démarré" not in report.reason, report.reason)

    # Une phase hors jeu qui n'est pas NO_API garde l'ancien message : ce
    # cas-là est bien « la partie n'a pas démarré ».
    menus = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(menus, "phase", Phase.MENUS)
    with patched(play_turn=Spy(actions.ActionLog())):
        loop = make_loop(ScriptedReader([menus]), max_duration=10.0)
        loop.wait_for_game_start = lambda timeout=0.0: CombatLoop.wait_for_game_start(loop, 0.4)
        autre = loop.run()
    check("aux menus, le message n'a pas changé",
          "n'a pas démarré" in autre.reason and not autre.api_down, autre.reason)


def test_menus_after_a_game_is_terminal():
    print("\nRetour aux menus après la partie")
 
    with_db(ALL_CARDS)
    playing = snapshot_with(hand_codes=["UNIT_A"])
    menus = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(menus, "phase", Phase.MENUS)
 
    turn_spy = Spy(actions.ActionLog())
    with patched(play_turn=turn_spy):
        report = make_loop(ScriptedReader([playing, menus]), max_duration=10.0).run()
 
    # Une fois la partie vue, « Menus » redevient un signal de fin.
    check("arrêt sur retour aux menus", report.reason == "retour aux menus", report.reason)
    check("le tour joué est compté", turn_spy.calls == 1, turn_spy.calls)
    check("sans verdict lisible, `won` reste inconnu", report.won is None, report.won)

    # LE VERDICT ARRIVE APRÈS LES MENUS. Le journal du 03/09/2026 : 47
    # combats, `gagne` jamais renseigné. Quand `/game-result` bascule dans
    # les secondes qui suivent, on le lit et on le garde.
    class ReaderWithVerdict(ScriptedReader):
        def final_result(self, **_):
            return False

    with patched(play_turn=turn_spy):
        report = make_loop(ReaderWithVerdict([playing, menus]), max_duration=10.0).run()
    check("verdict lu aux menus : défaite enregistrée", report.won is False, report.won)
    check("   et la partie est marquée finie", report.finished is True, report.finished)
    check("   la raison le dit", "résultat" in report.reason, report.reason)
 
 
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
 
    # Bouton non calibré : cliquer reviendrait à parier sur une position
    # devinée, et un mauvais clic gâche la main de départ.
    with patched(do_mulligan=mulligan_spy, click=click_spy,
                 mulligan_is_calibrated=lambda: False):
        report = make_loop(ScriptedReader([snap]), max_duration=0.6).run()
    check("non calibré -> manuel", mulligan_spy.calls == 0, mulligan_spy.calls)
    check("aucun clic à l'aveugle", click_spy.calls == 0, click_spy.calls)
    check("consigne de calibration affichée",
          any("--calibrate" in e for e in report.log), report.log)
 
    # Une fois le bouton calibré, plus besoin de rien demander.
    with patched(do_mulligan=mulligan_spy, click=click_spy,
                 mulligan_is_calibrated=lambda: True):
        make_loop(ScriptedReader([snap]), max_duration=0.6).run()
    check("calibré -> automatique", mulligan_spy.calls >= 1, mulligan_spy.calls)
 
    # Et l'option force le passage même sans calibration.
    mulligan_spy = Spy(actions.ActionLog())
    with patched(do_mulligan=mulligan_spy, click=click_spy,
                 mulligan_is_calibrated=lambda: False):
        make_loop(ScriptedReader([snap]), auto_mulligan=True, max_duration=0.6).run()
    check("--mulligan force le passage", mulligan_spy.calls >= 1, mulligan_spy.calls)
 
 
def test_stuck_detection_aborts():
    print("\nDétection de blocage")
 
    snap = blocking_snapshot(["BRUTE"], ["UNIT_A"])
 
    # execute_blocks ne fait jamais progresser l'état : la signature reste
    # identique, la boucle doit finir par abandonner d'elle-même.
    block_spy = Spy(([], snap, actions.ActionLog()))
    click_spy, cancel_spy = Spy(), Spy()
    order = []
    # La patience s'exprime en SECONDES depuis le 10/11/2026 : la boucle
    # doit donc avoir le droit de tourner assez longtemps pour les
    # dépenser, et chaque lecture doit coûter ce qu'elle coûte en jeu.
    with patched(execute_blocks=block_spy,
                 click=lambda *a, **k: (order.append("clic"), click_spy())[1],
                 cancel_pending_action=lambda *a, **k: (order.append("annule"), cancel_spy())[1]):
        report = make_loop(ScriptedReader([snap], cout_lecture=combat.DUREE_LECTURE),
                           poll=combat.DEFAULT_POLL, max_duration=10_000.0).run()
 
    check("arrêt sur blocage", "bloqué" in report.reason, report.reason)
    check("annulation tentée", cancel_spy.calls >= 1, cancel_spy.calls)
    check("clic de passe tenté ensuite", click_spy.calls >= 1, click_spy.calls)
    # L'annulation est inoffensive, le clic de passe termine le tour :
    # l'ordre d'escalade doit aller du moins destructeur au plus.
    check("annulation AVANT le clic de passe", order[0] == "annule", order[:3])
    # Borne : la patience totale divisée par le coût plancher d'une
    # lecture. C'est le nombre maximal de lectures qu'un blocage peut
    # consommer, quel que soit `poll`.
    check("pas de boucle infinie",
          block_spy.calls < combat.STUCK_ABORT_AFTER / combat.DUREE_LECTURE + 5,
          block_spy.calls)


def test_a_stuck_loop_leaves_a_readable_trace():
    """
    « Bloqué en X » ne suffit pas : le journal du 03/09/2026 comptait cinq
    combats arrêtés sur la durée maximale sans un mot sur ce que le jeu
    affichait. À chaque palier, l'état complet va au rapport et l'écran
    dans screenshots/.
    """
    print("\nUn blocage laisse une trace regardable")

    snap = blocking_snapshot(["BRUTE"], ["UNIT_A"])
    captures = []
    saved = combat.save_stuck_screen
    combat.save_stuck_screen = lambda phase: captures.append(phase) or f"screenshots/bloque_{phase}.png"
    try:
        with patched(execute_blocks=Spy(([], snap, actions.ActionLog())), click=Spy(),
                     cancel_pending_action=Spy()):
            report = make_loop(ScriptedReader([snap], cout_lecture=combat.DUREE_LECTURE),
                               poll=combat.DEFAULT_POLL, max_duration=10_000.0).run()
    finally:
        combat.save_stuck_screen = saved
    check("trois paliers, trois captures", captures == ["BLOCKING"] * 3, captures)
    check("l'état complet est dans le rapport",
          sum(1 for e in report.log if e.startswith("    [état] [BLOCKING]")) == 3,
          [e for e in report.log if "[état]" in e][:2])
    check("le chemin de la capture aussi",
          any("[écran] screenshots/bloque_BLOCKING.png" in e for e in report.log), report.log[-4:])


def test_les_bornes_de_blocage_comptent_des_secondes():
    """
    LES TROIS BORNES D'ESCALADE COMPTENT DES SECONDES, PLUS DES LECTURES —
    et à `--poll 1` elles tombent exactement où elles tombaient.

    C'était le piège nommé dans CLAUDE.md : `STUCK_CANCEL_AT` / `_LIMIT` /
    `_ABORT` comptaient des ITÉRATIONS, donc accélérer la boucle aurait
    fait abandonner un combat plus tôt — la panne même qu'on cherche à
    éviter, échangée contre quelques secondes.

    La conversion ne se fait PAS en multipliant par `poll` : une itération
    gelée ne dure pas `poll`, elle dure `poll` PLUS la lecture. Mesuré sur
    les 21 blocages des logs (19 en ATTACKING le 06/09, 2 en SPELL_STACK le
    05/11) : 4,19 s de médiane, étendue 3,74-4,30. Ici on rejoue une
    itération gelée à ce prix-là, et l'escalade doit tomber à la 12e, la
    25e et la 40e lecture, comme avant.
    """
    print("\nLes bornes de blocage comptent des secondes")

    with_db(ALL_CARDS)
    figee = blocking_snapshot(["BRUTE"], ["UNIT_A"])
    loop = make_loop(ScriptedReader([figee]), poll=combat.DEFAULT_POLL,
                     max_duration=10_000.0)

    paliers = {}
    n = [0]

    def note(nom):
        paliers.setdefault(nom, n[0])

    with patched(cancel_pending_action=lambda *a, **k: note("annulation"),
                 click=lambda *a, **k: note("passe")):
        loop._check_progress(figee)                 # la 1re lecture pose la signature
        arret = None
        while n[0] < 60:
            time.sleep(DUREE_ITERATION_GELEE)
            n[0] += 1
            if not loop._check_progress(figee):
                arret = n[0]
                break

    check("l'annulation tombe à la 12e lecture, comme avant",
          paliers.get("annulation") == 12, paliers)
    check("le clic de passe à la 25e, comme avant",
          paliers.get("passe") == 25, paliers)
    check("l'abandon à la 40e, comme avant", arret == 40, arret)
    check("les bornes sont écrites en secondes",
          (combat.STUCK_CANCEL_AFTER, combat.STUCK_PASS_AFTER,
           combat.STUCK_ABORT_AFTER) == (50.0, 104.0, 167.0),
          (combat.STUCK_CANCEL_AFTER, combat.STUCK_PASS_AFTER, combat.STUCK_ABORT_AFTER))
    check("   et le rapport dit des secondes, pas des lectures",
          any("s en BLOCKING" in e or "après" in e for e in loop.report.log),
          [e for e in loop.report.log if "bouge" in e or "bloqué" in e][:2])


def test_un_poll_plus_court_nabandonne_pas_plus_tot():
    """
    LE PIÈGE, RETOURNÉ : avec un `poll` deux fois plus court, l'abandon
    doit tomber à la même SECONDE qu'avant — donc après BEAUCOUP PLUS de
    lectures. Si la borne restait un compte de lectures, le combat serait
    abandonné en deux fois moins de temps.

    Et la réciproque est tout aussi importante : la borne ne doit pas être
    plus LÂCHE non plus, sinon un combat bloqué traîne.
    """
    print("\nUn poll plus court n'abandonne pas plus tôt")

    with_db(ALL_CARDS)
    figee = blocking_snapshot(["BRUTE"], ["UNIT_A"])
    # Deux fois plus vif : la lecture, elle, coûte toujours ses 2,2 s.
    poll = combat.DEFAULT_POLL / 2
    duree = combat.DUREE_LECTURE + poll * 0.3     # attente courte, cf. _attente
    loop = make_loop(ScriptedReader([figee]), poll=poll, max_duration=10_000.0)

    depart = time.time()
    lectures, arret = 0, False
    with patched(cancel_pending_action=Spy(), click=Spy()):
        loop._check_progress(figee)
        while lectures < 400:
            time.sleep(duree)
            lectures += 1
            if not loop._check_progress(figee):
                arret = True
                break
    ecoule = time.time() - depart

    check("la boucle a bien abandonné", arret, lectures)
    check("il a fallu BIEN PLUS de 40 lectures", lectures > 40, lectures)
    check("mais pas moins de patience qu'avant (en secondes)",
          ecoule >= combat.STUCK_ABORT_AFTER, round(ecoule, 1))
    check("   et pas beaucoup plus non plus",
          ecoule <= combat.STUCK_ABORT_AFTER + 2 * duree, round(ecoule, 1))


def test_lattente_est_courte_quand_le_jeu_attend_un_geste_de_nous():
    """
    L'ATTENTE EST ADAPTATIVE, ET C'EST L'INSTANTANÉ QUI TRANCHE — pas une
    devinette. Trois régimes :

      * le jeu attend un geste de NOUS (notre tour, blocage, orbe à nous
        sur la pile ou en ATTACKING) -> attente COURTE ;
      * on attend que le jeu résolve quelque chose (ATTACKING orbe grise,
        sort adverse sur la pile) -> attente normale ou longue ;
      * c'est le tour de l'adversaire -> attente LONGUE, relire plus
        souvent ne rapporterait rien et chaque lecture coûte 2,2 s.

    `ATTENTE_ADAPTATIVE = False` remet l'ancien barème à la seconde près.
    """
    print("\nL'attente est courte quand le jeu attend un geste de nous")

    with_db(ALL_CARDS)

    def vue(phase, orbe=False):
        snap = blocking_snapshot(["BRUTE"], ["UNIT_A"])
        object.__setattr__(snap, "phase", phase)
        object.__setattr__(snap, "turn_orb_active", orbe)
        return snap

    loop = make_loop(ScriptedReader([vue(Phase.OUR_TURN)]), poll=1.0)
    court = 1.0 * combat.ATTENTE_COURTE_RATIO

    cas = [
        ("notre tour", Phase.OUR_TURN, True, court),
        ("tour d'attaque", Phase.ATTACK_TURN, True, court),
        ("blocage", Phase.BLOCKING, False, court),
        ("pile, orbe à nous", Phase.SPELL_STACK, True, court),
        ("pile, orbe grise", Phase.SPELL_STACK, False, 1.0),
        ("attaque qui se résout", Phase.ATTACKING, False, 2.0),
        ("attaque, mais le jeu nous attend", Phase.ATTACKING, True, court),
        ("tour de l'adversaire", Phase.OPPONENT_TURN, False, 2.0),
        ("API muette", Phase.NO_API, False, 2.0),
        ("menus", Phase.MENUS, False, 2.0),
    ]
    for nom, phase, orbe, attendu in cas:
        obtenu = loop._attente(vue(phase, orbe))
        check(f"{nom} : {attendu} s", abs(obtenu - attendu) < 1e-9, obtenu)

    # L'ancien barème, à l'identique, quand on débranche l'adaptatif.
    sauve = combat.ATTENTE_ADAPTATIVE
    combat.ATTENTE_ADAPTATIVE = False
    try:
        anciens = {
            Phase.OUR_TURN: 1.0, Phase.BLOCKING: 1.0, Phase.SPELL_STACK: 1.0,
            Phase.ATTACKING: 2.0, Phase.OPPONENT_TURN: 2.0, Phase.NO_API: 2.0,
            Phase.MENUS: 2.0,
        }
        for phase, attendu in anciens.items():
            for orbe in (True, False):
                obtenu = loop._attente(vue(phase, orbe))
                check(f"sans adaptatif, {phase.name} orbe={orbe} : {attendu} s",
                      abs(obtenu - attendu) < 1e-9, obtenu)
    finally:
        combat.ATTENTE_ADAPTATIVE = sauve

    # `--poll` reste le rythme d'ensemble : les trois régimes en sont des
    # multiples, un `--poll 0` ne dort toujours pas.
    lent = make_loop(ScriptedReader([vue(Phase.OUR_TURN)]), poll=4.0)
    check("--poll commande encore les trois régimes",
          lent._attente(vue(Phase.OUR_TURN, True)) == 4.0 * combat.ATTENTE_COURTE_RATIO
          and lent._attente(vue(Phase.OPPONENT_TURN)) == 8.0,
          (lent._attente(vue(Phase.OUR_TURN, True)), lent._attente(vue(Phase.OPPONENT_TURN))))


def test_la_boucle_utilise_vraiment_lattente_adaptative():
    """
    Le barème ne sert à rien s'il n'est pas branché : on fait tourner la
    boucle sur un tour à NOUS et on compte le temps réellement dormi.
    """
    print("\nLa boucle utilise vraiment l'attente adaptative")

    with_db(ALL_CARDS)
    import test_clock

    def mesurer(phase, orbe, duree_max):
        snap = snapshot_with(hand_codes=["UNIT_A"])
        object.__setattr__(snap, "phase", phase)
        object.__setattr__(snap, "turn_orb_active", orbe)
        lecteur = ScriptedReader([snap])
        loop = make_loop(lecteur, poll=1.0, max_duration=duree_max)
        loop._seen_in_game = True
        avant = test_clock.virtual_elapsed()
        with patched(play_turn=Spy(actions.ActionLog()),
                     cancel_pending_action=Spy(), click=Spy()):
            loop.run()
        return (test_clock.virtual_elapsed() - avant) / max(1, lecteur.index)

    notre_tour = mesurer(Phase.OUR_TURN, True, 20.0)
    check("notre tour : ~0,3 s par lecture", 0.2 < notre_tour < 0.5, round(notre_tour, 3))

    adverse = mesurer(Phase.OPPONENT_TURN, False, 20.0)
    check("tour adverse : ~2 s par lecture, inchangé", 1.8 < adverse < 2.2, round(adverse, 3))


def test_a_card_stuck_in_the_air_is_banned_for_the_combat():
    """
    06/09/2026 : Banana Blaster posée sans cible, lue en ATTACKING au centre,
    annulée par la détection de blocage, REVENUE EN MAIN, rejouée au round
    suivant — seize fois. L'annulation doit bannir la carte en l'air pour
    le reste du combat, et play_hand doit la sauter même quand le mana
    remonte (le `carry` par round, lui, se vide).
    """
    print("\nUne carte figée en l'air est bannie pour le combat")

    from test_game_state import CARD_DB
    with_db(dict(ALL_CARDS))
    # Notre UNIT_A « en l'air » : bande attack, orbe à nous, phase ATTACKING.
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.320, code="UNIT_A", card_id=801, x=900))
    rects.append(rect_at_ratio(0.800, code="UNIT_B", card_id=803, x=900, local=False))
    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    figee = state_reader().snapshot()
    check("lue en ATTACKING, orbe à nous", figee.phase is Phase.ATTACKING and figee.turn_orb_active, figee.phase)

    loop = make_loop(ScriptedReader([figee]), poll=combat.DEFAULT_POLL, max_duration=10_000.0)
    with patched(click=Spy(), cancel_pending_action=Spy()):
        rejouer_gel(loop, figee, combat.STUCK_CANCEL_AFTER)
    check("UNIT_A bannie au palier d'annulation", "UNIT_A" in loop._carry.get("banned", set()), loop._carry)
    check("   et le rapport le dit", any("bannie" in e for e in loop.report.log), loop.report.log[-3:])

    # play_hand la saute, mana remonté ou pas.
    main = snapshot_with(hand_codes=["UNIT_A"])
    recorder = []
    saved_mana, saved_drag = actions.read_mana_pool, actions.drag
    actions.read_mana_pool = lambda **_: ManaPool(mana=10, spell_mana=0)
    actions.drag = lambda *a: recorder.append(a)
    try:
        played, _, log = actions.play_hand(ScriptedReader([main]), main, carry=loop._carry)
    finally:
        actions.read_mana_pool, actions.drag = saved_mana, saved_drag
    check("aucun glissé sur la bannie", recorder == [] and played == [], recorder)
    check("   le motif est journalisé", any("bannie pour le reste du combat" in e for e in log.entries), log.entries)

    # Une attaque NORMALE en cours (orbe grise : le jeu résout) ne bannit rien.
    install_fakes(rects, screen=make_screen(orb_active=False, token=None))
    attaque = state_reader().snapshot()
    loop2 = make_loop(ScriptedReader([attaque]), poll=combat.DEFAULT_POLL, max_duration=10_000.0)
    with patched(click=Spy(), cancel_pending_action=Spy()):
        rejouer_gel(loop2, attaque, combat.STUCK_CANCEL_AFTER)
    check("orbe grise : rien de banni", not loop2._carry.get("banned"), loop2._carry)


def test_level_ups_are_announced_once():
    """Le niveau 2 d'un champion se lit dans le cardCode rapporté par l'API."""
    print("\nNiveau 2 annoncé une fois")

    from test_game_state import CARD_DB
    db = dict(ALL_CARDS)
    db["CHAMPT1"] = {**db["UNIT_A"], "name": "Yasuo", "supertype": "Champion", "collectible": False}
    with_db(db)
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.029, code="UNIT_A", card_id=801, height=330, x=500))
    rects.append(rect_at_ratio(0.150, code="CHAMPT1", card_id=802, x=500))
    rects.append(rect_at_ratio(0.800, code="CHAMPT1", card_id=803, x=900, local=False))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    leveled = state_reader().snapshot()
    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)

    with patched(play_turn=Spy(actions.ActionLog())):
        report = make_loop(ScriptedReader([leveled, leveled, over])).run()
    notes = [e for e in report.log if e.startswith("Niveau 2")]
    check("un mot par champion monté, pas par lecture", len(notes) == 2, notes)
    check("le camp est nommé", any("notre champion" in n for n in notes) and any("son champion" in n for n in notes), notes)


def test_a_turn_interrupted_by_the_stack_counts_once():
    """Tour → pile → retour au tour : un seul tour joué."""
    print("\nUn tour coupé par la pile ne compte qu'une fois")

    with_db(ALL_CARDS)
    ours = snapshot_with(hand_codes=["UNIT_A"])
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.029, code="UNIT_A", card_id=811, height=330, x=500))
    rects.append(rect_at_ratio(0.48, code="SPELL_A", card_id=812, local=False, x=900))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    pile = state_reader().snapshot()
    theirs = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(theirs, "phase", Phase.OPPONENT_TURN)
    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)

    with patched(play_turn=Spy(actions.ActionLog()), respond_to_stack=Spy(actions.ActionLog()), click=Spy()):
        report = make_loop(ScriptedReader([ours, pile, ours, theirs, ours, over]), max_duration=30.0).run()
    check("deux tours joués, pas trois", report.turns_played == 2, report.turns_played)


def test_turns_are_counted_by_mana_refill():
    """
    Journal du 05/09/2026 : « 1 tour(s), 10 carte(s) posée(s), 230 s ».
    Tour → blocage → on rejoue le même round (mana en baisse) → round
    suivant (mana remonté) sans qu'OPPONENT_TURN ait été lu : trois
    épisodes de jeu, DEUX tours.
    """
    print("\nLes tours se comptent au mana qui remonte")

    with_db(ALL_CARDS)
    ours = snapshot_with(hand_codes=["UNIT_A"])
    block = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(block, "phase", Phase.BLOCKING)
    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)

    manas = iter([(10, 2), (2, 1), (10, 5)])

    def scripted_turn(*_, **__):
        log = actions.ActionLog()
        start, end = next(manas)
        log.mana_start, log.mana_end = start, end
        log.add("0 carte(s) posée(s).")
        return log

    with patched(play_turn=scripted_turn, click=Spy()):
        loop = make_loop(ScriptedReader([ours, block, ours, ours, over]), max_duration=30.0)
        loop._handle_blocking = lambda snapshot: None
        report = loop.run()
    check("deux tours (même round rejoué, puis round suivant)",
          report.turns_played == 2, report.turns_played)

    # Sans lecture de mana, l'ancien comptage par phase d'attente tient.
    theirs = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(theirs, "phase", Phase.OPPONENT_TURN)
    with patched(play_turn=Spy(actions.ActionLog()), click=Spy()):
        report = make_loop(ScriptedReader([ours, ours, theirs, ours, over]), max_duration=30.0).run()
    check("sans mana : un tour par passage de main", report.turns_played == 2, report.turns_played)


def test_journal_conclude_updates_the_right_line():
    """Le verdict tombe après la boucle : `conclude` retrouve la ligne et ne touche qu'elle."""
    print("\nLe journal reçoit le verdict après coup")
    import json
    import tempfile
    from pathlib import Path

    real_record = _REAL_RECORD
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "journal.jsonl"
        first = combat.CombatReport(reason="retour aux menus", turns_played=3)
        second = combat.CombatReport(reason="retour aux menus", turns_played=5)
        real_record(first, {"spells": False}, path=path)
        real_record(second, {"spells": False}, path=path)
        check("chaque ligne a un id distinct",
              first.journal_id and second.journal_id and first.journal_id != second.journal_id,
              (first.journal_id, second.journal_id))

        first.won, first.finished = True, True
        first.verdict, first.reason = "aventure poursuivie", "victoire (l'aventure a continué)"
        check("conclude trouve la ligne", journal.conclude(first, path=path))

        lines = [json.loads(l) for l in path.read_text(encoding="utf8").splitlines() if l.strip()]
        check("toujours deux lignes", len(lines) == 2, len(lines))
        check("la première porte le verdict",
              lines[0]["gagne"] is True and lines[0]["termine"] and lines[0]["verdict"] == "aventure poursuivie",
              lines[0])
        check("ses autres champs sont intacts", lines[0]["tours"] == 3 and lines[0]["config"] == {"spells": False}, lines[0])
        check("la seconde n'a pas bougé", lines[1]["gagne"] is None and lines[1]["tours"] == 5, lines[1])

        orphan = combat.CombatReport()
        check("sans id, rien n'est réécrit", journal.conclude(orphan, path=path) is False)

        # Le résumé compte la victoire, et le combat non conclu reste inachevé.
        stats = journal.summarise(lines)
        key = next(iter(stats))
        check("1 gagné, 1 inachevé", stats[key]["gagnes"] == 1 and stats[key]["inacheves"] == 1, stats[key])


def test_rejected_cards_reach_the_journal():
    """
    Les cartes écartées remontent de play_hand au journal, agrégées par
    motif NORMALISÉ : c'est le backlog de `journal.py --ecartees`.
    """
    print("\nLes cartes écartées remontent au journal")

    with_db(ALL_CARDS)
    ours = snapshot_with(hand_codes=["UNIT_A"])
    over = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(over, "phase", Phase.GAME_OVER)
    card = ours.hand[0]

    turns = iter([
        [(card.name, card.code, "coût 3 (lu à l'écran) > mana 2"),
         ("Astral", "98MT009", "sort : 2 cibles à cliquer, le bot n'en clique qu'une")],
        [(card.name, card.code, "coût 3 (lu à l'écran) > mana 1"),
         ("Astral", "98MT009", "sort : 2 cibles à cliquer, le bot n'en clique qu'une")],
    ])

    def scripted_turn(*_, **__):
        log = actions.ActionLog()
        for name, code, reason in next(turns):
            log.rejections.append((name, code, reason))
        log.add("0 carte(s) posée(s).")
        return log

    theirs = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(theirs, "phase", Phase.OPPONENT_TURN)
    with patched(play_turn=scripted_turn, click=Spy()):
        report = make_loop(ScriptedReader([ours, theirs, ours, over]), max_duration=30.0).run()

    by_motif = {(e["code"], e["motif"]): e["n"] for e in report.rejections}
    check("les deux motifs de la même carte sont fusionnés par normalisation",
          by_motif.get((card.code, "coût N (lu à l'écran) > mana N")) == 2, by_motif)
    check("l'incapacité est comptée deux fois",
          by_motif.get(("98MT009", "sort : N cibles à cliquer, le bot n'en clique qu'une")) == 2, by_motif)
    check("le résumé de fin les cite", any(e.startswith("Écartées :") for e in report.log), report.log[-1])

    # Le journal les enregistre, et le classement sépare contexte et incapacité.
    entry = _REAL_RECORD(report, {}, path=Path(tempfile.mkdtemp()) / "j.jsonl")
    check("champ ecartees écrit", len(entry["ecartees"]) == 2, entry["ecartees"])
    groups = journal.summarise_rejections([entry])
    capacity = [m for m in groups if not journal.is_context_reason(m)]
    context = [m for m in groups if journal.is_context_reason(m)]
    check("le mana est du contexte", context == ["coût N (lu à l'écran) > mana N"], context)
    check("les deux cibles sont une incapacité",
          capacity == ["sort : N cibles à cliquer, le bot n'en clique qu'une"], capacity)
    check("compté par carte", groups[capacity[0]]["cartes"]["Astral"] == 2, dict(groups[capacity[0]]["cartes"]))

    # ActionLog.reject dédoublonne dans un même épisode.
    log = actions.ActionLog()
    log.reject(card, "x"); log.reject(card, "x"); log.reject(card, "y")
    check("reject dédoublonne", len(log.rejections) == 2, log.rejections)


def test_settle_verdict_never_overrides_the_api():
    """lor_battle.settle_verdict : l'écran ne requalifie pas un verdict de l'API."""
    print("\nL'écran ne contredit pas l'API")
    import lor_battle

    calls = []
    saved = journal.conclude
    journal.conclude = lambda report, path=None: calls.append(report) or True
    try:
        report = combat.CombatReport()
        lor_battle.settle_verdict(report, won=False, verdict="écran de fin d'aventure", reason="défaite")
        check("verdict posé", report.won is False and report.finished and report.verdict == "écran de fin d'aventure")
        check("journal appelé", len(calls) == 1)

        api = combat.CombatReport(won=True, finished=True, verdict="API /game-result")
        lor_battle.confirm_victory(api)
        lor_battle.settle_verdict(api, won=False, verdict="écran de fin d'aventure", reason="défaite")
        check("l'API garde le dernier mot", api.won is True and api.verdict == "API /game-result")
        check("pas de second appel au journal", len(calls) == 1, len(calls))
    finally:
        journal.conclude = saved


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
 
 
def test_le_clic_sur_combat_est_verifie():
    """
    08/11/2026, BOSS FINAL : « Combat » lu à 0.96, cliqué, et la partie
    n'a jamais démarré. L'API répondait (`GameState: Menus`), l'écran
    montrait la carte d'aventure. Coût : 122 s d'attente, 48 s à
    chercher « Continuer » sur une carte, et une tentative hebdomadaire
    perdue sur une aventure dont le boss était intact.

    Les 19 combats lancés les 04, 05 et 06/11 donnent tous
    combat_button = 1.00 et démarrent en 2,8 à 7,5 s ; celui-là donnait
    0.96. Mais AUCUNE des 453 captures du projet ne montre un panneau
    d'arrivée avec « Combat » — `resolve_arrival` ne gardait l'écran que
    lorsqu'il ne reconnaissait rien — donc clic à côté, panneau dans un
    autre état, ou clic avalé : rien ne permet de trancher.

    Ce que ce test verrouille, c'est le minimum qui ne dépend d'aucune
    de ces hypothèses : ON REGARDE si le panneau s'en va, on RECLIQUE
    s'il est toujours là, et on GARDE L'ÉCRAN — pour que la prochaine
    fois soit diagnosticable.
    """
    print("\nLe clic sur « Combat » est vérifié")
    import navigate

    sauve = {k: getattr(navigate, k) for k in
             ("_capture_screen_bgr", "best_match", "safe_click",
              "save_screen", "park_mouse")}
    clics, gardes = [], []
    scores = []

    def faux_best_match(_path, screen=None):
        return (scores.pop(0) if scores else 0.0), (1440, 1002)

    try:
        navigate._capture_screen_bgr = lambda: "ECRAN"
        navigate.best_match = faux_best_match
        navigate.safe_click = lambda x, y, transition=False: clics.append((x, y))
        navigate.save_screen = lambda ecran, etiquette="carte": gardes.append(etiquette) or ""
        navigate.park_mouse = lambda: None

        # 0. Rien n'a été cliqué : il n'y a rien à vérifier.
        navigate.DERNIER_COMBAT = None
        check("sans « Combat » cliqué, on ne regarde rien",
              navigate.confirmer_le_lancement() is True and clics == [], clics)

        # 1. Le panneau s'en va : aucun reclic, aucune capture.
        navigate.DERNIER_COMBAT = (1.00, (1440, 1002))
        scores[:] = [0.10]
        ok = navigate.confirmer_le_lancement()
        check("panneau parti : c'est lancé", ok is True, ok)
        check("aucun reclic", clics == [], clics)
        check("aucun écran gardé", gardes == [], gardes)
        check("le point est consommé", navigate.DERNIER_COMBAT is None,
              navigate.DERNIER_COMBAT)

        # 2. Le panneau reste : on reclique, et chaque échec laisse une
        #    capture. C'est la situation du 08/11 — et elle ne doit PAS
        #    empêcher la boucle de combat de démarrer (un panneau encore
        #    lisible peut être un écran de chargement qui se pose).
        clics.clear(); gardes.clear()
        navigate.DERNIER_COMBAT = (0.96, (1440, 1002))
        scores[:] = [0.96] * 200
        ok = navigate.confirmer_le_lancement()
        check("panneau resté : on le dit", ok is False, ok)
        check("deux reclics après le premier clic",
              clics == [(1440, 1002)] * (navigate.COMBAT_CLICK_ATTEMPTS - 1), clics)
        check("un écran gardé par échec",
              gardes == ["combat_sans_effet"] * navigate.COMBAT_CLICK_ATTEMPTS, gardes)
    finally:
        navigate.DERNIER_COMBAT = None
        for key, value in sauve.items():
            setattr(navigate, key, value)

    # ET LA LECTURE D'ARRIVÉE RESTE UN PASSAGE UNIQUE. C'est elle qui
    # permet au score de trancher plutôt qu'à un ordre d'essai (bogue du
    # 22/08/2026) : la vérification devait donc vivre AILLEURS, dans
    # `combattre`, et pas dans `resolve_arrival`.
    import inspect
    source = inspect.getsource(navigate.run_adventure)
    check("`combattre` vérifie avant de lancer la boucle",
          "confirmer_le_lancement()" in source)


def test_une_partie_jamais_lancee_na_pas_decran_de_resultat():
    """
    Le 08/11/2026, après les 122 s d'attente, `try_combat` a quand même
    joué l'après-combat : un clic AU CENTRE DE LA CARTE D'AVENTURE, puis
    48 s à chercher « Continuer » (18:12:17 → 18:13:00). Il n'y avait
    pas d'écran de résultat — il n'y avait pas eu de partie.

    `interrupted` et `api_down` avaient déjà leur sortie ; ce cas-là
    n'en avait pas, et il tombait sur « aventure terminée » pour une
    aventure dont le boss final n'avait pas été joué.
    """
    print("\nUne partie jamais lancée n'a pas d'écran de résultat")
    import lor_battle
    import navigate

    report = combat.CombatReport(never_started=True,
                                 reason="la partie n'a pas démarré en 120 s")
    apres = Spy(True)
    joue = Spy(report)
    sauve = (lor_battle.play_combat, lor_battle._handle_post_combat)
    try:
        lor_battle.play_combat = joue
        lor_battle._handle_post_combat = apres
        rendu = lor_battle.try_combat(100, 200, final_boss=True)
    finally:
        lor_battle.play_combat, lor_battle._handle_post_combat = sauve

    check("le rapport est rendu tel quel", rendu is report)
    check("aucun geste d'après-combat", apres.calls == 0, apres.calls)

    # Et le motif ne dit plus « aventure terminée » : le boss n'a pas
    # été joué, l'aventure est intacte.
    check("navigate nomme le motif",
          navigate.NOT_STARTED_PREFIX == "la partie n'a pas démarré",
          navigate.NOT_STARTED_PREFIX)


def test_la_suite_necrit_rien_dans_screenshots():
    """
    UNE SUITE HORS LIGNE NE LAISSE RIEN DERRIÈRE ELLE.

    Le garde-machine (08/11) surveille la souris, la molette, le focus et
    `pyautogui.screenshot` — il disait « machine intacte », et il avait
    raison : rien n'était photographié de l'écran d'Ewan. Mais la suite
    ÉCRIVAIT quand même, parce que `save_stuck_screen` enregistre ce que
    `capture_screen_bgr` lui rend, et qu'en test c'est l'écran synthétique
    des doublures. Un gris uniforme de 1,5 Mo, quatre fois par
    `check.py --offline`, dans le dossier même où l'on cherche les vrais
    blocages : 621 fichiers sur 660, 0,98 Go, mesuré le 09/11/2026.

    « Ne touche pas la machine » et « ne laisse rien derrière soi » sont
    donc deux propriétés différentes, et la seconde n'avait pas de garde.
    Celui-ci en est un, au moins pour cette suite-là.
    """
    print()
    print("La suite n'écrit rien dans screenshots/")

    dossier = Path(__file__).resolve().parent / "screenshots"
    avant = len(list(dossier.glob("bloque_*.png"))) if dossier.exists() else 0
    marque = len(CAPTURES_DE_BLOCAGE)

    chemin = combat.save_stuck_screen("BLOCKING")

    apres = len(list(dossier.glob("bloque_*.png"))) if dossier.exists() else 0
    check("aucun fichier n'est apparu dans screenshots/", apres == avant,
          (avant, apres))
    check("   mais la demande de capture est bien enregistrée",
          len(CAPTURES_DE_BLOCAGE) == marque + 1
          and CAPTURES_DE_BLOCAGE[-1] == "BLOCKING",
          CAPTURES_DE_BLOCAGE[-3:])
    check("   et un chemin est rendu, comme la vraie fonction",
          isinstance(chemin, str) and "bloque_" in chemin, chemin)


def test_le_drapeau_distingue_les_trois_pannes():
    """
    Trois sorties sans partie jouée, trois drapeaux : API muette
    (`api_down`), clic sans effet (`never_started`), boucle coupée en
    pleine partie (`interrupted`). Les confondre, c'est cliquer là où il
    n'y a rien — ou arrêter une session qui pouvait continuer.
    """
    print("\nTrois pannes, trois drapeaux")

    with_db(ALL_CARDS)
    menus = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(menus, "phase", Phase.MENUS)
    with patched(play_turn=Spy(actions.ActionLog())):
        loop = make_loop(ScriptedReader([menus]), max_duration=10.0)
        loop.wait_for_game_start = lambda timeout=0.0: CombatLoop.wait_for_game_start(loop, 0.4)
        aux_menus = loop.run()
    check("aux menus : never_started", aux_menus.never_started is True, aux_menus.never_started)
    check("   et pas api_down", aux_menus.api_down is False, aux_menus.api_down)

    muet = snapshot_with(hand_codes=["UNIT_A"])
    object.__setattr__(muet, "phase", Phase.NO_API)
    with patched(play_turn=Spy(actions.ActionLog())):
        loop = make_loop(ScriptedReader([muet]), max_duration=10.0)
        loop.wait_for_game_start = lambda timeout=0.0: CombatLoop.wait_for_game_start(loop, 0.4)
        sans_api = loop.run()
    check("API muette : api_down", sans_api.api_down is True, sans_api.api_down)
    check("   et PAS never_started — le jeu tourne peut-être",
          sans_api.never_started is False, sans_api.never_started)


from mana import ManaPool
_POOL = ManaPool(mana=10, spell_mana=0)
 
 

def test_la_sortie_est_en_utf8_avant_toute_impression():
    """
    `combat.py --plan > rapport.txt` mourait sur son propre « ≤ ».

    Le « --- déroulé --- » de `--plan` reverse les lignes « [état] » du
    rapport, et `GameSnapshot.summary()` y écrit « deck : N cartes, ≤ M
    à piocher ». Dès que stdout part dans un FICHIER ou un TUBE, Python
    retombe sur cp1252, où ce caractère n'existe pas. Le `logging` ne
    disait rien : `sys.stderr` a `backslashreplace` par défaut et survit
    toujours — c'est le `print` qui tombe.

    UN MODULE PEUT ÊTRE PARFAIT ET N'ÊTRE BRANCHÉ NULLE PART : c'est
    précisément le défaut qu'on répare, donc c'est le BRANCHEMENT qu'on
    teste. On n'exécute pas la commande pour autant — elle va chercher le
    jeu : on coupe à la construction de l'analyseur d'arguments, la
    première chose que `main` fait après la parade.
    """
    print("\n-- la parade UTF-8 est branchée --")

    vus = []
    vrai_appliquer = sortie_utf8.appliquer
    vrai_parser = combat.argparse.ArgumentParser

    class Coupe(Exception):
        pass

    sortie_utf8.appliquer = lambda: vus.append("parade")
    combat.argparse.ArgumentParser = lambda *a, **k: (_ for _ in ()).throw(Coupe())
    try:
        combat.main()
    except Coupe:
        vus.append("analyseur")
    finally:
        sortie_utf8.appliquer = vrai_appliquer
        combat.argparse.ArgumentParser = vrai_parser

    check("combat.main() applique la parade AVANT d'analyser la ligne de commande",
          vus == ["parade", "analyseur"], vus)


def main():
    for test in (
        test_challenger_is_not_our_attack,
        test_challenger_triggers_a_block,
        test_spell_stack_is_answered_not_played_through,
        test_stops_on_game_over,
        test_waits_for_the_game_to_start,
        test_gives_up_if_the_game_never_starts,
        test_menus_after_a_game_is_terminal,
        test_waiting_phases_do_nothing,
        test_dispatches_blocking,
        test_manual_mulligan_by_default,
        test_stuck_detection_aborts,
        test_a_stuck_loop_leaves_a_readable_trace,
        test_les_bornes_de_blocage_comptent_des_secondes,
        test_un_poll_plus_court_nabandonne_pas_plus_tot,
        test_lattente_est_courte_quand_le_jeu_attend_un_geste_de_nous,
        test_la_boucle_utilise_vraiment_lattente_adaptative,
        test_la_sortie_est_en_utf8_avant_toute_impression,
        test_a_card_stuck_in_the_air_is_banned_for_the_combat,
        test_level_ups_are_announced_once,
        test_a_silent_api_is_named_as_such,
        test_a_turn_interrupted_by_the_stack_counts_once,
        test_turns_are_counted_by_mana_refill,
        test_journal_conclude_updates_the_right_line,
        test_rejected_cards_reach_the_journal,
        test_settle_verdict_never_overrides_the_api,
        test_signature_detects_real_progress,
        test_plan_mode_touches_nothing,
        test_le_clic_sur_combat_est_verifie,
        test_une_partie_jamais_lancee_na_pas_decran_de_resultat,
        test_le_drapeau_distingue_les_trois_pannes,
        test_la_suite_necrit_rien_dans_screenshots,
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
 