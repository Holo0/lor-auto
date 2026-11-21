#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_challenges.py

Tests de la boucle de session, sans jeu ni souris.

Ce qui est vérifié ici est exactement ce qu'on ne peut PAS observer
autrement qu'en laissant tourner le bot une heure : est-ce qu'une défaite
arrête la session ? est-ce qu'un écran inconnu la fait tourner à vide ?
est-ce que le bilan compte juste ?

Les étapes qui touchent l'écran (`navigate.*`, `lor_battle.try_combat`)
sont remplacées par des doublures scriptées. La boucle, elle, est la
vraie.

    python test_challenges.py
"""

from __future__ import annotations

import collections
import sys
import time
import types

try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.FailSafeException = type("FailSafeException", (Exception,), {})
    stub.size = lambda: (1920, 1080)
    stub.position = lambda: (0, 0)
    for name in ("screenshot", "moveTo", "click", "mouseDown", "mouseUp"):
        setattr(stub, name, lambda *a, **k: None)
    sys.modules["pyautogui"] = stub

# La session temporise entre deux tentatives : hors ligne, ces attentes
# sont fictives (cf. test_clock.py).
from test_clock import install_virtual_clock

install_virtual_clock()

import challenges
import journal
import lor_battle
import navigate

# Les écrans factices des tests ne doivent pas remplir screenshots/.
navigate._keep_unknown_screen = lambda *_: None
from challenges import ChallengeSession
from navigate import Entry, Screen

# LE LECTEUR DE LA GRILLE DES CHAMPIONS EST BOUCHONNÉ POUR TOUTE LA SUITE.
# `navigate._pick_champion` fait défiler la grille et la photographie :
# sans ce bouchon, une suite HORS LIGNE piloterait la vraie souris
# d'Ewan — mesuré le 05/11/2026 : 10 captures, 15 coups de molette.
# Un test qui veut l'autre branche le dit explicitement.
navigate.champions.choisir_champion = lambda *a, **k: False
# ET LE RETOUR EN HAUT DE LA GRILLE AVEC LUI (08/11/2026). Le repli
# `first_champion` vise le HAUT de la grille, donc `_pick_champion` l'y
# ramène avant de chercher le bouton — et ce retour est un PARCOURS :
# mesuré à l'espion, il ajoutait 220 coups de molette sur le vrai jeu
# par exécution de la suite, plus dix vols de focus. Bouchonner le
# lecteur ne suffisait plus : il faut bouchonner les deux gestes.
navigate.champions.revenir_en_haut = lambda *a, **k: True

# ET LA RÉCOMPENSE DE COMBAT AUSSI, pour la même raison (06/11/2026).
# `lor_battle._reward_proves_victory` guette le panneau pendant dix
# secondes AVANT de conclure à une défaite — en capturant l'écran. Sans
# ce bouchon, la suite hors ligne photographiait VRAIMENT l'écran
# d'Ewan : mesuré à l'espion, **40 captures** par exécution, et
# test_challenges passait de 5 s à 15 s. Un test qui veut la branche
# « la récompense est là » le dit explicitement.
navigate.play_reward = lambda *a, **k: None

# ET LA SOURIS GARÉE AUSSI. `lor_battle._watch_after_continue` appelle
# `park_mouse`, qui déplace VRAIMENT le curseur : 29 déplacements par
# exécution de cette suite, mesurés le 05/11/2026, antérieurs au choix du
# champion. Le harnais du boss final le remplaçait déjà par un témoin ;
# ailleurs, il passait. Hors ligne, aucune souris : c'est l'invariant.
import lor_battle as _lor_battle
_lor_battle.park_mouse = lambda: None
# ET IL FAUT BOUCHONNER LES DEUX LIAISONS (08/11/2026). `navigate.py` a
# importé `park_mouse` POUR LUI : remplacer celle de `lor_battle` laisse
# l'autre intacte, et `restore()` remet la vraie dans `navigate`. Mesuré
# à l'espion pendant ce chantier : 28 déplacements réels du curseur par
# `navigate.lancer_le_combat` → `park_mouse`, depuis
# `test_arrival_is_decided_by_what_the_game_offers`. Le commentaire
# ci-dessus le disait déjà — « ailleurs, il passait » — sans en tirer la
# conséquence. Un bouchon par NOM importé, pas un par fonction.
navigate.park_mouse = lambda: None

# ET LE JOURNAL N'EST PAS ÉCRIT. `challenges` journalise désormais chaque
# TENTATIVE : sans ce bouchon, une exécution de cette suite ajoutait 30
# fausses tentatives dans le vrai `journal.jsonl` — constaté et nettoyé le
# 05/11/2026. Le journal est l'instrument de mesure du projet ; une suite
# hors ligne ne doit pas y toucher. Le bouchon GARDE les appels pour qu'on
# puisse quand même vérifier ce qui aurait été écrit.
import journal as _journal
TENTATIVES_JOURNALISEES = []
_journal.record_attempt = lambda **champs: (TENTATIVES_JOURNALISEES.append(champs)
                                            or champs)

# NI LE BILAN DE FIN DE TENTATIVE, QUI PHOTOGRAPHIE L'ÉCRAN (10/11/2026).
# `lor_battle._lire_le_bilan` est le SEUL point du module qui capture
# l'écran pour juger — `_judge_from_summary` et le coup d'œil d'avant
# « Relevez-vous » passent tous les deux par lui. C'est donc le seul à
# bouchonner, et il faut le faire DÈS L'IMPORT : jusqu'ici seul
# `test_final_boss_exits` remplaçait `_judge_from_summary`, et tout autre
# test qui atteindrait la branche du boss final irait voir le vrai écran
# d'Ewan — la sixième fuite, après `park_mouse`, `choisir_champion`,
# `play_reward`, `revenir_en_haut` et `focus_game_window`.
#
# On GARDE les appels : le harnais du boss final a besoin de les voir, et
# de pouvoir dire ce que le juge parvient à lire.
LECTURES_DU_BILAN = []
_lor_battle._lire_le_bilan = lambda attente=None: (LECTURES_DU_BILAN.append(attente)
                                                   and None)

# NI LE PREMIER PLAN DE LA FENÊTRE DU JEU. `challenges._mettre_le_jeu_devant`
# appelle `gestures.focus_game_window` avant CHAQUE tentative (09/11/2026),
# et cette suite enchaîne les sessions : sans bouchon, elle VOLE le premier
# plan 44 fois par exécution de `check.py --offline`, plus 88 interrogations
# de la liste des fenêtres. Le garde-machine du 08/11 l'a attrapé le jour
# même où le correctif a été écrit — c'est la cinquième fuite de l'histoire
# du projet, et la première à ne pas avoir vécu des semaines.
#
# On GARDE les appels : le test qui vérifie l'ordre « on met devant, PUIS
# on regarde » a besoin de les voir.
import gestures as _gestures
PREMIERS_PLANS = []
_gestures.focus_game_window = lambda: (PREMIERS_PLANS.append("devant") or True)
_gestures.game_window_handle = lambda: 4242

# LES FONCTIONS RÉELLES, GARDÉES À L'IMPORT. `install()` remplace des
# attributs du module `navigate` pour tester la boucle ; les tests qui
# vérifient `navigate` lui-même doivent donc pouvoir remettre les vraies —
# sinon ils s'interrogent sur les doublures et passent sans rien prouver.
VRAI = {
    name: getattr(navigate, name)
    for name in ("enter_challenge_attempt", "where_are_we", "best_match",
                 "click_button", "safe_click", "run_adventure", "goto_node",
                 "locate_node", "resolve_arrival", "has_mid_boss",
                 "save_screen", "back_to_known_screen", "_capture_screen_bgr",
                 "park_mouse", "play_event")
}


def restore(*names):
    for name in names or tuple(VRAI):
        setattr(navigate, name, VRAI[name])


_VRAI_TOPMOST = navigate.topmost_match

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

class FakeCombat:
    """Le strict minimum d'un CombatReport, vu par la session."""

    def __init__(self, won, reason="partie terminée"):
        self.won = won
        self.reason = reason


class Scripted:
    """
    Rejoue une suite de valeurs, puis répète la dernière indéfiniment.

    Répéter plutôt qu'épuiser est délibéré : c'est ce que fait le jeu
    quand rien ne change, et c'est justement le cas qu'une boucle mal
    gardée transforme en boucle infinie.
    """

    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


def montre(noms):
    """
    Fabrique un écran factice où SEULS ces templates correspondent.

    Seul `best_match` est bouchonné : le vrai `where_are_we` tourne, avec
    son ordre de détection — c'est justement ce qu'on veut vérifier.
    """
    navigate._capture_screen_bgr = lambda: None
    navigate.best_match = lambda path, screen=None: (
        (0.95, (10, 10)) if any(path.endswith(n + ".png") for n in noms)
        else (0.30, (0, 0))
    )


def parcours(reason=None, combats=(), nodes=None):
    """
    Fabrique un compte rendu de `navigate.run_adventure`.

    Par défaut : une aventure menée à son terme. `reason` explicite sert
    aux cas d'échec (« combat perdu », « clic sur le nœud sans effet »…).
    """
    import navigate as nav
    liste = list(combats)
    return {
        "nodes": nodes if nodes is not None else max(len(liste), 1),
        "combats": liste,
        "reason": reason or nav.CLEAN_END,
    }


def install(entries, runs=None, recoveries=(Screen.CHAMPION,)):
    """
    Branche les doublures et rend les espions.

    `runs` : suite de comptes rendus de `run_adventure`. Un raccourci est
    accepté — un FakeCombat seul vaut « aventure terminée sur ce
    combat » — parce que c'est le cas de la moitié des tests.
    """
    def normalise(valeur):
        if isinstance(valeur, dict):
            return valeur
        if valeur is None:
            return parcours(combats=[])
        return parcours(combats=[valeur],
                        reason="combat perdu" if valeur.won is False else None)

    if runs is None:
        runs = [parcours(combats=[FakeCombat(True)])]

    enter = Scripted(*entries)
    aventure = Scripted(*[normalise(r) for r in runs])
    recover = Scripted(*recoveries)

    navigate.enter_challenge_attempt = enter
    navigate.run_adventure = aventure
    navigate.back_to_known_screen = recover
    return enter, aventure, recover


# ============================================================
# TESTS
# ============================================================

def test_un_masque_tout_blanc_nest_pas_passe_a_matchtemplate():
    """
    UN MASQUE OPAQUE NE CACHE RIEN, ET IL COÛTE QUATRE À SIX FOIS LE PRIX.

    Depuis le 06/11, `best_match` lit ses gabarits en IMREAD_UNCHANGED et
    passe `mask=` dès qu'il voit quatre canaux. C'était juste pour les
    quatre repères qui cachent vraiment quelque chose — `player_marker`
    et sa boîte à 54 % de décor, `final_boss`, `continue_button` — mais
    **seize des vingt gabarits à alpha l'ont uniformément à 255**. Pour
    ceux-là le masque ne change pas le score (CLAUDE.md : « écart
    ≤ 0.00021 ») et il interdit le chemin accéléré d'OpenCV.

    Mesuré : `quit_button` 1,495 s masqué contre 0,240 s sans. Et
    `where_are_we` compare DIX gabarits quand aucun ne passe le seuil —
    c'est le « 9 à 11 s quand une recherche échoue » du relevé de temps
    du 08/11, où le même document note que « tout le gras est dans les
    échecs, pas dans la vitesse des gestes ».

    On teste donc l'ALPHA, jamais un nom de fichier : le jour où un
    gabarit opaque gagne un vrai masque, il le reprend tout seul.
    """
    print()
    print("Un masque tout blanc n'est pas passé à matchTemplate")

    import tempfile

    import cv2
    import numpy as np
    from pathlib import Path

    import adventure_navigation as an

    motif = np.zeros((24, 32, 3), dtype=np.uint8)
    motif[6:18, 8:24] = (40, 180, 220)
    ecran = np.zeros((300, 400, 3), dtype=np.uint8)
    ecran[100:124, 150:182] = motif

    def bgra(alpha_valeur):
        img = np.dstack([motif, np.full((24, 32), 255, dtype=np.uint8)])
        if alpha_valeur is not None:
            img[:4, :, 3] = alpha_valeur          # un vrai trou dans le masque
        return img

    masques = []
    vrai_match = an._match

    def espion(screen_bgr, template, mask):
        masques.append(mask)
        return vrai_match(screen_bgr, template, mask)

    dossier = tempfile.mkdtemp(prefix="masque_")
    try:
        an._match = espion
        opaque = Path(dossier) / "opaque.png"
        troue = Path(dossier) / "troue.png"
        cv2.imwrite(str(opaque), bgra(None))
        cv2.imwrite(str(troue), bgra(0))

        score_opaque, point_opaque = an.best_match(str(opaque), screen=ecran)
        check("un gabarit opaque est comparé SANS masque", masques[-1] is None,
              type(masques[-1]))
        check("   et il est quand même trouvé", score_opaque > 0.95,
              (score_opaque, point_opaque))

        an.best_match(str(troue), screen=ecran)
        check("un gabarit qui cache vraiment quelque chose garde le sien",
              masques[-1] is not None, type(masques[-1]))

        # LE RÉSULTAT EST LE MÊME QU'AVANT : c'est toute la justification.
        sans_alpha = Path(dossier) / "sans_alpha.png"
        cv2.imwrite(str(sans_alpha), motif)
        score_nu, point_nu = an.best_match(str(sans_alpha), screen=ecran)
        check("   score identique à celui d'un gabarit sans alpha",
              abs(score_opaque - score_nu) < 1e-6, (score_opaque, score_nu))
        check("   et même point", point_opaque == point_nu,
              (point_opaque, point_nu))
    finally:
        an._match = vrai_match
        import shutil
        shutil.rmtree(dossier, ignore_errors=True)


def test_le_mode_plan_ne_plante_sur_aucun_ecran_reconnu():
    """
    UN DIAGNOSTIC NE PLANTE PAS.

    `challenges.py --plan` décrit, pour l'écran affiché, les étapes qu'il
    cliquerait — en lisant `navigate.STEPS_FROM[screen]`. Or cette table
    ne contient que les écrans qui ont un CHEMIN D'ENTRÉE : carte du
    monde, liste, champion, confirmation. L'écran RESUME, ajouté le
    06/11/2026, n'en a pas : il a un bouton. `--plan` levait donc
    KeyError exactement là où le bot, lui, sait reprendre l'aventure —
    la commande qu'on lance pour comprendre tombait sur le seul écran
    qu'on ne comprenait pas.

    On nomme donc RESUME, et aucun écran ne peut plus faire tomber la
    commande : un écran reconnu sans chemin décrit est une information.
    """
    print()
    print("Le mode plan ne plante sur aucun écran reconnu")

    vrai = navigate.where_are_we
    try:
        for ecran in Screen:
            navigate.where_are_we = lambda e=ecran: e
            try:
                rapport = ChallengeSession(dry_run=True).run()
            except Exception as exc:          # noqa: BLE001 — c'est le sujet
                check(f"{ecran.name} : --plan ne lève rien", False, repr(exc))
                continue
            check(f"{ecran.name} : --plan décrit l'écran sans lever",
                  any("[plan]" in ligne for ligne in rapport.log), rapport.log)

        navigate.where_are_we = lambda: Screen.RESUME
        rapport = ChallengeSession(dry_run=True).run()
        check("   et RESUME est nommé pour ce qu'il est : une REPRISE",
              any("REPRENDRE" in l or "REPRISE" in l for l in rapport.log),
              rapport.log)
        check("   en disant qu'aucune tentative n'est consommée",
              any("aucune tentative" in l for l in rapport.log), rapport.log)
    finally:
        navigate.where_are_we = vrai
        restore()


def test_le_jeu_est_mis_devant_avant_de_regarder_lecran():
    """
    UNE FENÊTRE CACHÉE N'EST PAS UN ÉCRAN INCONNU.

    Mesuré le 09/11/2026, en vrai : la session a démarré pendant que
    l'éditeur de texte couvrait le jeu. Le bot photographie le BUREAU,
    pas la fenêtre du jeu — il a donc lu l'éditeur, n'a reconnu aucun
    gabarit (meilleur score 0.51 pour un seuil de 0.80), a compté une
    tentative « inachevée — écran inconnu au moment d'entrer », et s'est
    arrêté. `--tentatives 1` avait brûlé son unique créneau sans que rien
    ne soit joué, et la capture gardée pour diagnostic montrait… du code
    source.

    C'est la leçon du 08/11 d'un cran au-dessus. Ce jour-là on a appris
    que « la molette ne part nulle part si le jeu n'a pas le premier
    plan », et `gestures.focus_game_window` est né pour ça — mais seul
    `champions.py` l'appelait, au moment de faire défiler une grille. Or
    la condition est plus ancienne que la molette : TOUT ce que le bot
    sait de l'écran vient d'une photo du bureau, donc rien ne marche si
    une autre fenêtre est devant. On met donc le jeu devant avant CHAQUE
    tentative, pas seulement avant un défilement.

    Dégradation douce, comme le veut `gestures` : pas de fenêtre de jeu,
    pas de pywin32, ou bascule refusée par Windows — on le DIT et on
    continue de lire l'écran tel qu'il est. Refuser de démarrer serait
    pire : le jeu peut très bien être visible sans que Windows nous
    laisse le mettre au premier plan.
    """
    print()
    print("Le jeu est mis devant avant de regarder l'écran")

    traces = []
    vrai_focus = challenges.gestures.focus_game_window
    vrai_handle = challenges.gestures.game_window_handle
    try:
        challenges.gestures.focus_game_window = lambda: (traces.append("devant") or True)
        challenges.gestures.game_window_handle = lambda: 4242

        enter = Scripted(Entry.LAUNCHED, Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT)

        def regarde(*args, **kwargs):
            traces.append("regarde")
            return enter(*args, **kwargs)

        navigate.enter_challenge_attempt = regarde
        navigate.run_adventure = Scripted(parcours(combats=[FakeCombat(True)]))
        navigate.back_to_known_screen = Scripted(Screen.CHAMPION)

        report = ChallengeSession().run()
        check("la session joue bien ses tentatives", len(report.attempts) == 2,
              report.summary())
        check("   le jeu passe devant AVANT la première lecture d'écran",
              traces[:2] == ["devant", "regarde"], traces)
        avant = [traces[i - 1] for i, quoi in enumerate(traces)
                 if quoi == "regarde" and i > 0]
        check("   et avant CHAQUE tentative, pas seulement la première",
              traces and traces[0] == "devant" and all(x == "devant" for x in avant),
              traces)

        # SANS FENÊTRE DE JEU, ON NE S'ARRÊTE PAS : on le dit, et on lit
        # l'écran tel qu'il est. C'est ce que fait déjà `gestures`.
        traces.clear()
        challenges.gestures.game_window_handle = lambda: None
        enter2 = Scripted(Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT)

        def regarde2(*args, **kwargs):
            traces.append("regarde")
            return enter2(*args, **kwargs)

        navigate.enter_challenge_attempt = regarde2
        rapport = ChallengeSession().run()
        check("   fenêtre introuvable : la session tourne quand même",
              "regarde" in traces, traces)
        check("   et aucun passage au premier plan n'est tenté",
              "devant" not in traces, traces)
        check("   mais c'est DIT dans le compte rendu",
              any("premier plan" in ligne or "introuvable" in ligne
                  for ligne in rapport.log),
              rapport.log[:4])
    finally:
        challenges.gestures.focus_game_window = vrai_focus
        challenges.gestures.game_window_handle = vrai_handle
        restore()


def test_repeats_until_the_game_refuses():
    print("\nLa session s'arrête quand le jeu n'a plus de tentative")

    # Deux tentatives jouées, puis le jeu cesse d'afficher le bouton de
    # confirmation. C'est le seul signal disponible, et c'est la fin
    # NORMALE d'une session.
    install(entries=[Entry.LAUNCHED, Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
            runs=[FakeCombat(True)])
    avant = len(TENTATIVES_JOURNALISEES)
    report = ChallengeSession().run()
    journalisees = TENTATIVES_JOURNALISEES[avant:]

    check("deux tentatives jouées", len(report.attempts) == 2, len(report.attempts))
    # LA TENTATIVE EST UNE DONNÉE, pas seulement ses combats : sans cette
    # ligne, « quel champion pour quel palier ? » reste sans réponse.
    check("chaque tentative part au journal",
          len(journalisees) == 2, len(journalisees))
    check("   avec son issue et de quoi la relier au champion",
          all(set(("palier", "etoiles", "gagne", "raison")) <= set(t)
              for t in journalisees), journalisees[:1])
    check("deux victoires comptées", report.wins == 2, report.wins)
    check("arrêt nommé", report.reason == Entry.NO_ATTEMPT_LEFT.value, report.reason)
    # Le constat « plus de tentative » n'est pas une tentative : la compter
    # ferait mentir le bilan d'une ligne à chaque session.
    check("le constat n'est pas compté comme une tentative",
          all(a.entered for a in report.attempts),
          [a.reason for a in report.attempts])


def test_a_defeat_does_not_stop_the_session():
    print("\nUne défaite ne stoppe pas la session")

    # Ewan a tranché : on réessaie tant qu'il reste des tentatives. Une
    # défaite consomme une tentative comme une victoire, donc on repart.
    install(entries=[Entry.LAUNCHED, Entry.LAUNCHED, Entry.LAUNCHED,
                     Entry.NO_ATTEMPT_LEFT],
            runs=[FakeCombat(False), FakeCombat(False), FakeCombat(True)])
    report = ChallengeSession().run()

    check("trois tentatives jouées", len(report.attempts) == 3, len(report.attempts))
    check("deux défaites puis une victoire",
          (report.losses, report.wins) == (2, 1), (report.losses, report.wins))
    check("ce n'est pas la défaite qui a arrêté la session",
          report.reason == Entry.NO_ATTEMPT_LEFT.value, report.reason)


def test_a_silent_api_stops_the_session_before_burning_attempts():
    """
    04/11/2026 : le port 21337 était fermé. Le bot a traversé la carte,
    lancé le boss final, attendu 120 s sans rien lire, conclu « combat
    terminé, 0 tour » et cherché « Continuer ». Une tentative de défi
    brûlée pour rien — et sans `--tentatives 1` il les aurait toutes
    passées ainsi. Un combat qui n'a jamais été LU arrête la session.
    """
    print("\nL'API muette arrête la session avant de brûler les tentatives")

    muet = FakeCombat(None, reason="API du client injoignable depuis 120 s "
                                   "(http://127.0.0.1:21337) — le jeu tourne "
                                   "peut-être, mais il ne rapporte rien")
    muet.api_down = True
    install(entries=[Entry.LAUNCHED, Entry.LAUNCHED],
            runs=[parcours(reason=navigate.API_DOWN_PREFIX + " (boss final) : "
                           "API du client injoignable depuis 120 s",
                           combats=[muet], nodes=3)])
    recoveries = []
    navigate.back_to_known_screen = lambda *a, **k: recoveries.append(1) or Screen.UNKNOWN
    report = ChallengeSession().run()

    check("une seule tentative engagée", len(report.attempts) == 1, len(report.attempts))
    check("le motif nomme l'API",
          report.reason.startswith(navigate.API_DOWN_PREFIX), report.reason)
    check("   et renvoie à check.py", "check.py" in report.reason, report.reason)
    check("aucune recherche d'écran connu", recoveries == [], recoveries)

    # Le préfixe doit rester DISTINCT de celui d'un combat interrompu :
    # l'un se répare en allongeant `--duree-combat`, l'autre non.
    check("distinct de « combat interrompu »",
          not navigate.API_DOWN_PREFIX.startswith(navigate.INTERRUPTED_PREFIX)
          and not navigate.INTERRUPTED_PREFIX.startswith(navigate.API_DOWN_PREFIX))


def test_an_interrupted_combat_stops_the_session_cleanly():
    """
    06/09/2026 : la boucle de combat a atteint sa durée maximale ALORS QUE
    LA PARTIE CONTINUAIT. La navigation a cherché « nœud 2 » sur le plateau,
    puis 2 × 120 s d'écran inconnu. Désormais : `report.interrupted` →
    try_combat ne clique rien, navigate rend « combat interrompu … partie
    encore en cours », la session s'arrête sur ce motif SANS chercher un
    écran connu.
    """
    print("\nUn combat coupé par la durée maximale arrête la session proprement")

    coupe = FakeCombat(None, reason="durée maximale atteinte (1500 s)")
    coupe.interrupted = True
    install(entries=[Entry.LAUNCHED, Entry.LAUNCHED],
            runs=[parcours(reason=navigate.INTERRUPTED_PREFIX + " (boss intermédiaire) : "
                           "durée maximale atteinte, partie encore en cours",
                           combats=[coupe], nodes=2)])
    recoveries = []
    navigate.back_to_known_screen = lambda *a, **k: recoveries.append(1) or Screen.UNKNOWN
    report = ChallengeSession().run()

    check("une seule tentative", len(report.attempts) == 1, len(report.attempts))
    check("le motif dit que la partie continue",
          report.reason.startswith(navigate.INTERRUPTED_PREFIX) and "à la main" in report.reason,
          report.reason)
    check("aucune recherche d'écran connu", recoveries == [], recoveries)

    # Le pont : un rapport interrompu ne déclenche AUCUN clic d'après-combat.
    import lor_battle as lb
    saved = (lb.play_combat, lb._handle_post_combat)
    clics = []
    lb.play_combat = lambda **o: coupe
    lb._handle_post_combat = lambda **k: clics.append("post") or True
    try:
        rendu = lb.try_combat(1, 2)
    finally:
        lb.play_combat, lb._handle_post_combat = saved
    check("try_combat rend le rapport sans rien fermer", rendu is coupe and clics == [], clics)

    # Et navigate nomme l'arrêt.
    restore()
    saved_try = lor_battle.try_combat
    lor_battle.try_combat = lambda x, y, **k: coupe
    navigate.has_mid_boss = lambda wait=None: True
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT
    navigate.goto_node = lambda cible, etiquette, settle=None, **k: (navigate.ARRIVAL_COMBAT, (1, 2))
    # ET LE PANNEAU RESTÉ OUVERT (08/11/2026). `run_adventure` regarde
    # d'abord si un coffre ou une récompense traîne — et pour les
    # départager sur UNE SEULE image, `prendre_panneau_ouvert` CAPTURE
    # l'écran. Les autres tests qui appellent `run_adventure` bouchonnent
    # déjà `_capture_screen_bgr` ; celui-ci ne le faisait pas, et il
    # photographiait vraiment l'écran d'Ewan à chaque `check.py
    # --offline`. Cinquième récidive de l'invariant « une suite hors
    # ligne ne touche pas la machine », et la première attrapée par le
    # garde-machine, né le même jour. Bouchon LOCAL : le garde du coffre
    # est vérifié ailleurs (`test_un_coffre_reste_ouvert_nest_pas_une_recompense`),
    # un bouchon global l'aurait rendu muet.
    vrai_panneau = navigate.prendre_panneau_ouvert
    navigate.prendre_panneau_ouvert = lambda etiquette, vue=None: False
    try:
        bilan = navigate.run_adventure()
    finally:
        lor_battle.try_combat = saved_try
        navigate.prendre_panneau_ouvert = vrai_panneau
        restore()
    check("navigate : « combat interrompu » au boss intermédiaire",
          bilan["reason"].startswith(navigate.INTERRUPTED_PREFIX) and "boss intermédiaire" in bilan["reason"],
          bilan["reason"])


def test_a_lost_navigation_is_named_and_recovered():
    print("\nUne navigation perdue est nommée, pas confondue avec une défaite")

    # La tentative est bien lancée mais le boss final n'est jamais
    # atteint : sans distinction, ce cas se lirait comme une défaite au
    # combat, et on chercherait à améliorer le jeu au lieu des templates.
    install(entries=[Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
            runs=[parcours(reason=navigate.ARRIVAL_MISSED, combats=[], nodes=0)])
    report = ChallengeSession().run()

    check("une tentative enregistrée", len(report.attempts) == 1, len(report.attempts))
    perdue = report.attempts[0]
    check("entrée réussie", perdue.entered is True)
    check("aucun combat joué", perdue.fought is False)
    check("ni victoire ni défaite", perdue.won is None, perdue.won)
    check("le motif vient de la navigation",
          perdue.reason == navigate.ARRIVAL_MISSED, perdue.reason)


def test_a_lost_combat_is_a_defeat_wherever_it_happens():
    print("\nUn combat perdu est une défaite, où qu'il arrive")

    # AVANT, une défaite au boss intermédiaire ressemblait à une
    # navigation perdue : le boss final n'était jamais atteint. Maintenant
    # c'est `run_adventure` qui le dit — « combat perdu » — et le nœud où
    # c'est arrivé figure dans le motif.
    install(entries=[Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
            runs=[parcours(reason="combat perdu (boss intermédiaire)",
                           combats=[FakeCombat(False)], nodes=3)])
    report = ChallengeSession().run()

    check("une tentative", len(report.attempts) == 1, len(report.attempts))
    perdue = report.attempts[0]
    check("comptée comme une défaite", perdue.won is False, perdue.won)
    check("l'endroit est nommé", "intermédiaire" in perdue.reason, perdue.reason)
    check("un combat a bien été joué", perdue.fought is True)


def test_burning_attempts_for_nothing_stops_the_session():
    print("\nTrois tentatives brûlées sans jouer arrêtent la session")

    # Le cas coûteux : chaque tour consomme une tentative HEBDOMADAIRE et
    # ne joue aucune partie. « Réessayer tant qu'il reste des tentatives »
    # ne doit pas vouloir dire « les dépenser toutes sur un template
    # cassé ».
    enter, _, _ = install(
        entries=[Entry.LAUNCHED],
        runs=[parcours(reason=navigate.ARRIVAL_MISSED, combats=[], nodes=0)],
    )
    report = ChallengeSession().run()

    check("arrêt au plafond d'abandons",
          len(report.attempts) == challenges.ABANDON_LIMIT, len(report.attempts))
    check("pas une entrée de plus",
          len(enter.calls) == challenges.ABANDON_LIMIT, len(enter.calls))
    check("le message dit ce que ça coûte",
          "consommée(s) sans qu'une partie se joue" in report.reason
          and "hebdomadaire" in report.reason, report.reason)

    # Une défaite au milieu ne doit PAS remplir ce compteur : sinon trois
    # combats perdus d'affilée arrêteraient la session, ce qui est
    # exactement ce qu'Ewan ne veut pas.
    install(entries=[Entry.LAUNCHED, Entry.LAUNCHED, Entry.LAUNCHED,
                     Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
            runs=[FakeCombat(False)])
    report = ChallengeSession().run()
    check("quatre défaites n'arrêtent rien", report.losses == 4, report.losses)
    check("c'est le jeu qui a arrêté la session",
          report.reason == Entry.NO_ATTEMPT_LEFT.value, report.reason)


def test_unknown_screens_do_not_spin_forever():
    print("\nUn écran inconnu n'entretient pas une boucle à vide")

    # Le pire cas : le jeu affiche un écran dont aucun template n'existe,
    # et le retour échoue aussi. Sans compteur, la boucle tournerait
    # jusqu'à la limite de DURÉE — des heures de clics dans le vide.
    enter, _, recover = install(entries=[Entry.LOST], recoveries=[Screen.UNKNOWN])
    report = ChallengeSession().run()

    check("arrêt après quelques essais",
          len(enter.calls) <= challenges.LOST_LIMIT + 1, len(enter.calls))
    check("le retour a été tenté", len(recover.calls) >= 1, len(recover.calls))
    check("raison explicite", "inconnu" in report.reason, report.reason)
    check("aucune tentative comptée comme jouée",
          report.wins == 0 and report.losses == 0, (report.wins, report.losses))


def test_recovered_screen_resets_the_counter():
    print("\nUn écran retrouvé remet le compteur d'échecs à zéro")

    # Deux ratés isolés, séparés par des tentatives qui marchent, ne
    # doivent pas s'additionner jusqu'à l'abandon : c'est ce qui
    # arriverait avec un compteur global au lieu d'un compteur
    # d'échecs CONSÉCUTIFS.
    install(entries=[Entry.LOST, Entry.LAUNCHED, Entry.LOST, Entry.LAUNCHED,
                     Entry.NO_ATTEMPT_LEFT],
            runs=[FakeCombat(True)])
    report = ChallengeSession().run()

    # CE QUI SE COMPTE, CE SONT LES TENTATIVES, PAS LES TOURS DE BOUCLE.
    # Cette ligne disait « les deux tentatives réussies sont jouées » et
    # exigeait QUATRE lignes dans le bilan — elle gravait le défaut
    # qu'elle était censée décrire, comme le `rejection_reason` de
    # l'équipement le 09/11. Les deux entrées manquées ne coûtent rien et
    # ne jouent rien : elles ne sont pas des tentatives.
    check("les deux tentatives réussies sont jouées",
          len(report.attempts) == 2, [a.reason for a in report.attempts])
    check("   et les deux entrées manquées sont dites, pas comptées",
          report.entrees_manquees == 2, report.entrees_manquees)
    check("deux victoires", report.wins == 2, report.wins)
    check("arrêt sur épuisement, pas sur écran inconnu",
          report.reason == Entry.NO_ATTEMPT_LEFT.value, report.reason)


def test_une_entree_manquee_ne_brule_pas_la_session():
    """
    UNE TENTATIVE QUI N'A JAMAIS EU LIEU NE SE COMPTE PAS.

    09/11/2026, `logs/challenges_20261109_192611.log`, la session entière
    en deux lignes :

        reprise 1 : inachevée en 0 min — écran inconnu au moment d'entrer
        Arrêt : nombre de tentatives demandé atteint (1)

    L'éditeur de texte couvrait le jeu. Le bot photographie le BUREAU :
    aucun gabarit ne passait le seuil (meilleur score 0.51 pour 0.80),
    `enter_challenge_attempt` a rendu `LOST`, et `_stop_reason` lit
    `len(report.attempts)` — le créneau de `--tentatives 1` était brûlé
    par une panne de LECTURE. La cause est réparée depuis
    (`_mettre_le_jeu_devant`) ; le compteur, lui, ne l'était pas, et
    toute panne d'entrée future aurait coûté la session.

    CE QUI JUSTIFIE DE NE PAS COMPTER, et c'est mesuré dans `navigate` :
    `_confirm_attempt` — le clic sur `use_attempt`, LE seul geste qui
    dépense une tentative hebdomadaire — est la DERNIÈRE étape de chaque
    chemin de `STEPS_FROM`, et quand il réussit l'entrée rend `LAUNCHED`.
    Donc `LOST` veut dire, sans exception, qu'il n'a jamais abouti : rien
    consommé, rien joué, et `_play_one` rend la main avant même
    `journal.record_attempt`. Le précédent était déjà écrit juste à côté
    pour `NO_ATTEMPT_LEFT` — « elle n'a rien joué » ; il ne manquait que
    de le dire de l'autre entrée qui n'a rien joué non plus.

    ET CE N'EST PAS RÉCUPÉRER UNE SESSION PERDUE POUR UNE BOUCLE SANS
    FIN : le garde existe déjà et il est INDÉPENDANT du compteur de
    tentatives — `_lost` / `LOST_LIMIT` plafonne les entrées manquées
    CONSÉCUTIVES à trois. Les deux derniers cas ci-dessous le vérifient
    dans le pire scénario pour le correctif, celui où rien d'autre ne
    peut arrêter la boucle.

    Mesuré dans `logs/` : **13 entrées manquées** sur 63 lignes de
    tentative, le premier motif du relevé. Et elles se rattrapent —
    `logs/challenges_20261106_203911.log` enchaîne « reprise 1 :
    inachevée — écran inconnu au moment d'entrer » puis DEUX VICTOIRES.
    """
    print()
    print("Une entrée qui n'a jamais eu lieu ne brûle pas la session")

    # (a) LE CAS DU 09/11, À L'IDENTIQUE : `--tentatives 1`, et la
    #     première lecture d'écran échoue.
    avant = len(TENTATIVES_JOURNALISEES)
    enter, _, _ = install(entries=[Entry.LOST, Entry.LAUNCHED],
                          runs=[FakeCombat(True)])
    report = ChallengeSession(max_attempts=1).run()
    journalisees = TENTATIVES_JOURNALISEES[avant:]

    check("la vraie tentative est quand même jouée",
          len(report.attempts) == 1 and report.wins == 1,
          (len(report.attempts), report.wins))
    check("   l'entrée manquée n'a pas pris sa place",
          all(a.entered for a in report.attempts),
          [a.reason for a in report.attempts])
    check("   le créneau demandé a bien servi",
          "tentatives demandé" in report.reason, report.reason)
    check("   deux entrées, une tentative", len(enter.calls) == 2,
          len(enter.calls))

    # LE JOURNAL RESTE JUSTE, et c'est la raison la plus forte de ne rien
    # y écrire : `champions.DERNIER_CHOIX` / `DERNIER_PALIER` ne sont
    # remis à jour que par `choisir_champion`, qu'une entrée manquée
    # n'atteint jamais. Une ligne écrite là porterait le champion et le
    # palier de la tentative PRÉCÉDENTE — un échec fantôme imputé à un
    # 7 ★ innocent, et `journal.py --champions` fausse.
    check("une entrée manquée ne laisse aucune ligne de journal",
          len(journalisees) == 1, [t.get("raison") for t in journalisees])
    check("   mais elle est DITE dans le compte rendu",
          any(Entry.LOST.value in ligne for ligne in report.log),
          report.log)
    check("   et comptée à part du bilan",
          report.entrees_manquees == 1, report.entrees_manquees)
    check("   sans se faire passer pour une reprise",
          not any(ligne.startswith("reprise") for ligne in report.log),
          [l for l in report.log if l.startswith("reprise")])
    check("   le bilan le dit aussi",
          "entrée(s) manquée(s)" in report.summary(), report.summary())

    # (b) LE CONSTAT « PLUS DE TENTATIVE » N'EST PAS UNE PANNE D'ENTRÉE :
    #     c'est la fin normale de la session, et la mélanger aux deux
    #     ferait croire à un écran mal reconnu à chaque session.
    install(entries=[Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
            runs=[FakeCombat(True)])
    report = ChallengeSession().run()
    check("« plus de tentative » n'est pas une entrée manquée",
          report.entrees_manquees == 0, report.entrees_manquees)
    check("   et reste la raison d'arrêt",
          report.reason == Entry.NO_ATTEMPT_LEFT.value, report.reason)

    # (c) LE GARDE ANTI-BOUCLE, DANS SON PIRE CAS. Toutes les entrées
    #     échouent ET le retour à un écran connu RÉUSSIT : plus rien ne
    #     peut arrêter la session — ni `--tentatives` (aucune tentative
    #     ne se compte), ni les abandons (aucune entrée ne réussit), ni
    #     le retour d'écran. Il ne reste que `LOST_LIMIT`, et il doit
    #     suffire. Sans lui, le correctif échangerait une session trop
    #     courte contre une session SANS FIN, souris prise.
    enter, _, recover = install(entries=[Entry.LOST],
                                recoveries=[Screen.CHAMPION])
    report = ChallengeSession(max_duration=10 * 3600).run()
    check("entrées toutes manquées : la session s'arrête quand même",
          len(enter.calls) <= challenges.LOST_LIMIT, len(enter.calls))
    check("   au plafond d'entrées manquées consécutives",
          report.entrees_manquees == challenges.LOST_LIMIT,
          report.entrees_manquees)
    check("   le motif nomme l'écran inconnu", "inconnu" in report.reason,
          report.reason)
    check("   et la fenêtre couverte, cause n°1 mesurée",
          "fenêtre" in report.reason, report.reason)
    check("   aucune tentative au bilan", len(report.attempts) == 0,
          [a.reason for a in report.attempts])

    # (d) ET LE GARDE COMPOSÉ, parce qu'une entrée RÉUSSIE remet `_lost`
    #     à zéro : en alternant « écran inconnu » et « aventure reprise
    #     qui ne joue rien », aucun des deux compteurs ne monte seul
    #     jusqu'à son plafond. C'est `_abandons` qui prend le relais —
    #     il n'est JAMAIS remis à zéro par une entrée manquée.
    class Alterne:
        def __init__(self, *valeurs):
            self.valeurs = list(valeurs)
            self.calls = []

        def __call__(self, *a, **k):
            self.calls.append((a, k))
            return self.valeurs[(len(self.calls) - 1) % len(self.valeurs)]

        def __len__(self):
            return len(self.calls)

    alterne = Alterne(Entry.LOST, Entry.RESUMED)
    navigate.enter_challenge_attempt = alterne
    navigate.run_adventure = Scripted(
        parcours(reason=navigate.ARRIVAL_MISSED, combats=[], nodes=0))
    navigate.back_to_known_screen = Scripted(Screen.CHAMPION)
    report = ChallengeSession(max_duration=10 * 3600).run()
    check("alterner entrée manquée et reprise stérile s'arrête aussi",
          len(alterne.calls) <= 2 * challenges.ABANDON_LIMIT,
          len(alterne.calls))
    check("   sur le garde des abandons, pas sur la durée",
          "reprendre l'aventure" in report.reason, report.reason)
    restore()


def test_attempt_cap_is_respected():
    print("\nLe plafond de tentatives est respecté")

    # Le jeu en donnerait davantage : c'est l'option qui arrête, ce qui
    # permet un essai court et surveillé avant de laisser tourner.
    enter, _, _ = install(entries=[Entry.LAUNCHED], runs=[FakeCombat(True)])
    report = ChallengeSession(max_attempts=2).run()

    check("deux tentatives", len(report.attempts) == 2, len(report.attempts))
    check("pas une entrée de plus", len(enter.calls) == 2, len(enter.calls))
    check("raison explicite", "tentatives demandé" in report.reason, report.reason)


def test_session_duration_is_a_hard_stop():
    print("\nLa durée maximale de session arrête la boucle")

    # Chaque tentative consomme du temps virtuel : la boucle doit
    # s'arrêter d'elle-même, sans compter les tentatives.
    def aventure_lente(*args, **kwargs):
        import time
        time.sleep(400)
        return parcours(combats=[FakeCombat(True)])

    install(entries=[Entry.LAUNCHED])
    navigate.run_adventure = aventure_lente

    report = ChallengeSession(max_duration=1000).run()
    check("la session s'arrête sur la durée", "durée maximale" in report.reason,
          report.reason)
    check("mais les tentatives jouées sont gardées",
          len(report.attempts) >= 2, len(report.attempts))


def test_keyboard_interrupt_still_reports():
    print("\nUn Ctrl+C rend quand même un bilan")

    # Un arrêt manuel après deux heures de farm doit laisser le compte des
    # victoires, sinon la session ne sert à rien.
    calls = {"n": 0}

    def interrupted(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return Entry.LAUNCHED

    install(entries=[Entry.LAUNCHED], runs=[FakeCombat(True)])
    navigate.enter_challenge_attempt = interrupted

    report = ChallengeSession().run()
    check("une tentative gardée", len(report.attempts) == 1, len(report.attempts))
    check("victoire comptée", report.wins == 1, report.wins)
    check("raison explicite", "clavier" in report.reason, report.reason)


def test_plan_mode_touches_nothing():
    print("\nLe mode plan ne clique rien")

    enter, aventure, recover = install(entries=[Entry.LAUNCHED],
                                      runs=[FakeCombat(True)])
    navigate.where_are_we = lambda: Screen.WORLD_MAP

    report = ChallengeSession(dry_run=True).run()
    check("aucune entrée tentée", enter.calls == [], enter.calls)
    check("aucune aventure jouée", aventure.calls == [], aventure.calls)
    check("l'écran reconnu est annoncé",
          any("carte du monde" in line for line in report.log), report.log)


def test_combat_options_reach_the_combat():
    print("\nLes options de jeu arrivent bien au combat")

    # Un réglage passé en ligne de commande qui n'atteindrait pas
    # CombatLoop serait invisible : la session tournerait, et le réglage
    # ne servirait à rien.
    _, aventure, _ = install(entries=[Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
                             runs=[FakeCombat(True)])
    ChallengeSession(combat_options={"allow_spells": True, "allow_chump": True}).run()

    check("une aventure jouée", len(aventure.calls) == 1, len(aventure.calls))
    _, kwargs = aventure.calls[0]
    check("les options de combat descendent jusqu'à l'aventure",
          kwargs.get("combat_options") == {"allow_spells": True, "allow_chump": True},
          kwargs)


def test_the_champion_is_selected_before_launching():
    print("\nÉcran du champion : on sélectionne PUIS on lance")

    # LE GESTE D'EWAN, À CHAQUE FIN DE DÉFI : premier champion, puis
    # bouton de lancement. Les deux repères sont visibles en même temps sur
    # cet écran ; si la détection préférait `use_attempt`, le bot ne
    # cliquerait QUE le bouton et le jeu resterait sans champion
    # sélectionné — la boucle en concluerait « plus de tentative » et la
    # session s'arrêterait sans rien jouer.
    restore()
    ordre = [key for _, keys in navigate.SCREEN_ANCHORS for key in keys]
    # C'est l'ORDRE RELATIF qui porte le fait, pas la place dans la liste :
    # `Screen.RESUME` est passé devant les deux le 06/11/2026 sans rien
    # changer à celui-ci.
    check("le champion est cherché avant le bouton de lancement",
          ordre.index("first_champion") < ordre.index("use_attempt"), ordre)
    # SCREEN_ANCHORS ne contient que des écrans signés par un BOUTON
    # UNIQUE. L'aventure, elle, n'est pas dans cette table : elle se
    # reconnaît aux marques du jeu, et seulement après que les écrans
    # d'entrée ont été écartés. `RESUME` y a sa place — « REPRENDRE
    # L'AVENTURE » est un bouton unique comme les autres — mais il dit
    # l'inverse des quatre : il n'y a rien à lancer, seulement à reprendre.
    check("la table ne contient que des écrans signés par un bouton",
          {ecran for ecran, _ in navigate.SCREEN_ANCHORS}
          == {Screen.CHAMPION, Screen.ATTEMPT, Screen.LIST, Screen.WORLD_MAP,
              Screen.RESUME},
          [e for e, _ in navigate.SCREEN_ANCHORS])
    check("et l'aventure n'y est toujours pas",
          Screen.ADVENTURE not in {e for e, _ in navigate.SCREEN_ANCHORS})

    # Écran où TOUT est visible : la vignette du champion, le bouton de
    # lancement, et même le bouton de la carte du monde derrière.
    tout_visible = {"first_champion", "use_attempt", "monthly_challenge"}
    montre(tout_visible)
    check("cet écran est reconnu comme la sélection du champion",
          navigate.where_are_we() is Screen.CHAMPION, navigate.where_are_we())

    clics = []

    def fake_click(name, timeout=10, **kwargs):
        clics.append(name)
        return True

    navigate.click_button = fake_click
    verdict = navigate.enter_challenge_attempt(timeout=1)

    check("la tentative est lancée", verdict is Entry.LAUNCHED, verdict)
    check("grille illisible : on retombe sur le premier, puis on lance",
          clics == ["first_champion", "use_attempt"], clics)

    # ET QUAND LA GRILLE EST LISIBLE : le champion est choisi par ses
    # ÉTOILES, pas par sa place. `first_champion` n'est alors plus cliqué
    # du tout — c'était lui qui prenait le pire champion du compte.
    clics.clear()
    lu = navigate.champions.choisir_champion
    navigate.champions.choisir_champion = lambda *a, **k: True
    try:
        verdict = navigate.enter_challenge_attempt(timeout=1)
    finally:
        navigate.champions.choisir_champion = lu
    check("grille lisible : le champion est choisi par ses étoiles",
          clics == ["use_attempt"], clics)
    check("   et la tentative part quand même", verdict is Entry.LAUNCHED, verdict)


def test_le_repli_ne_sentete_pas_hors_de_la_grille():
    print("\nLe repli « premier champion » ne s'entête pas hors de la grille")

    # LES DEUX ÉCHECS DE `champions` ÉTAIENT LUS PAREIL (08/11/2026).
    # `choisir_champion` rend False dans deux cas qui demandent deux
    # conduites OPPOSÉES — et `_pick_champion` enchaînait sur le même
    # filet dans les deux. La trace du soir (logs/bot_run.log) :
    #     20:47:20  Grille des champions : aucune vignette jouable lue.
    #     20:47:20  Grille des champions illisible — on retombe sur le premier.
    #     20:47:26  Recherche du bouton : first_champion
    #     20:47:32  Souris garée en (79, 547) : un bouton est peut-être caché.
    #     20:47:37  Bouton first_champion introuvable.
    # Onze secondes à chercher le HAUT D'UNE GRILLE ABSENTE — l'écran
    # était la LISTE DES DÉFIS — et autant à chaque essai d'entrée.
    restore()

    clics = []
    navigate.click_button = lambda name, timeout=10, **k: (clics.append(name) or True)

    # `choisir_champion` est bouchonné à False pour toute la suite : ici
    # c'est justement le cas qui nous intéresse. CE QUI TRANCHE, C'EST
    # L'ÉCRAN — « le bouton du repli est-il là ? » — et PAS le booléen de
    # `revenir_en_haut`, qui rend False pour deux raisons opposées.
    haut = navigate.champions.revenir_en_haut
    try:
        # (a) LA GRILLE EST LÀ, mais rien de jouable n'y a été lu : le
        #     filet documenté depuis le 05/11 garde tout son sens, et il
        #     passe par le retour en haut (0.64 en bas pour un seuil de
        #     0.80, mesuré le 08/11). Ne pas casser ça.
        montre({"first_champion", "use_attempt", "monthly_challenge"})
        navigate.champions.revenir_en_haut = lambda *a, **k: True
        clics.clear()
        pris = navigate._pick_champion(1)
        check("grille illisible : le filet « premier champion » joue encore",
              clics == ["first_champion"], clics)
        check("   et l'étape est franchie", pris is True, pris)

        # (b) LA MOLETTE N'A PAS ÉTÉ ENTENDUE — `revenir_en_haut` rend
        #     False pour CETTE raison-là aussi (fenêtre sans premier
        #     plan, 08/11/2026). Mais rien n'a défilé non plus : la
        #     grille est restée EN HAUT, `first_champion` y est, et le
        #     filet est le dernier moyen de sauver la tentative. Se fier
        #     au booléen le couperait justement là. C'est pour ça qu'on
        #     REGARDE au lieu de déduire.
        navigate.champions.revenir_en_haut = lambda *a, **k: False
        clics.clear()
        pris = navigate._pick_champion(1)
        check("molette muette mais grille en haut : le filet joue quand même",
              clics == ["first_champion"], clics)
        check("   et l'étape est franchie", pris is True, pris)

        # (c) CE N'EST PAS LA GRILLE. L'écran du blocage était la LISTE
        #     DES DÉFIS, où `first_champion` note **0.502** — mesuré sur
        #     `captures_reference/liste_defis_20261108.png`, pour un
        #     seuil de 0.80. Insister n'a aucun sens : le bouton n'est
        #     pas là et ne viendra pas.
        montre({"active_encounter", "monthly_challenge"})
        clics.clear()
        pris = navigate._pick_champion(1)
        check("ce n'est pas la grille : aucun bouton n'est cherché",
              clics == [], clics)
        check("   et on rend la main pour relire l'écran", pris is False, pris)

        # ET LE REFUS REMONTE JUSQU'À L'APPELANT, DEPUIS L'ÉCRAN DU
        # BLOCAGE LUI-MÊME : ce soir-là `where_are_we` lisait « liste des
        # défis actifs », pas la grille — c'est de là qu'il faut partir,
        # sinon on vérifie un chemin où `first_champion` est visible et
        # où les onze secondes n'ont jamais été dépensées.
        check("l'écran du blocage est bien la liste des défis",
              navigate.where_are_we() is Screen.LIST, navigate.where_are_we())
        clics.clear()
        navigate.topmost_match = lambda *a, **k: (100, 100)
        navigate.safe_click = lambda *a, **k: True
        try:
            verdict = navigate.enter_challenge_attempt(retries=2, timeout=1)
        finally:
            navigate.topmost_match = _VRAI_TOPMOST
        check("on est perdu, pas « à court de tentatives »",
              verdict is Entry.LOST, verdict)
        check("   et `first_champion` n'a jamais été cherché",
              "first_champion" not in clics, clics)
        check("   ni la tentative consommée", "use_attempt" not in clics, clics)
    finally:
        navigate.champions.revenir_en_haut = haut


def test_le_diagnostic_juge_tous_ses_reperes_sur_une_seule_capture():
    """
    `navigate.py where` ENFREIGNAIT LA RÈGLE QU'IL SERT À VÉRIFIER.

    La règle du projet est écrite dans CLAUDE.md depuis le 22/08/2026 :
    « Quand plusieurs templates répondent de la même question, les
    mesurer sur UNE SEULE capture et comparer les scores — ne jamais
    laisser un ordre d'essai décider à la place de ce qu'on voit. »
    `where_are_we` l'applique depuis toujours (une capture, dix
    gabarits) et `back_to_known_screen` la cite mot pour mot pour
    départager un coffre d'une récompense.

    `cmd_where`, lui, prenait QUATRE captures différentes — une pour
    `where_are_we`, une pour `score_report`, une pour le médaillon, une
    quatrième pour `--snap` — et imprimait leurs résultats comme une
    seule lecture. Pendant une animation (un panneau qui se dessine, un
    fondu de bilan) les quatre ne montrent pas la même chose : l'écran
    annoncé peut être celui d'avant, les scores celui d'après, et le
    médaillon un troisième. C'est pourtant l'outil qu'on lance
    précisément quand on ne comprend pas ce que le bot voit.

    Et `--snap` enregistrait une image de plus, pas celle qui venait
    d'être jugée : impossible de refaire les mesures hors ligne sur la
    trame qui a produit le rapport.

    Le test injecte une vraie capture de `captures_reference/` — on ne
    photographie jamais l'écran d'Ewan dans une suite hors ligne — et
    compte les prises de vue. Chaque prise rend un OBJET DIFFÉRENT :
    c'est ce qui permet de vérifier que tout le monde a regardé la MÊME
    image, et pas seulement le même décor.
    """
    print("\nLe diagnostic « where » juge tous ses repères sur UNE capture")
    restore()

    import contextlib
    import io
    from pathlib import Path

    import cv2

    import marqueur_joueur

    chemin = (Path(navigate.__file__).resolve().parent / "captures_reference"
              / "champions_haut_20261105.png")
    reference = cv2.imread(str(chemin))
    check("la capture de référence est lisible", reference is not None, chemin)

    prises = []

    def photographe():
        prises.append(len(prises))
        return reference.copy()        # un objet NEUF à chaque prise de vue

    navigate._capture_screen_bgr = photographe

    vues = []
    navigate.best_match = lambda path, screen=None: (
        vues.append(screen)
        or ((0.99, (10, 10)) if path.endswith("first_champion.png")
            else (0.30, (0, 0))))

    # Le médaillon est lu par `marqueur_joueur`, sur l'image qu'on lui
    # donne : on espionne ce qu'il reçoit plutôt que de le faire
    # travailler pour rien (multi-échelle, ~1 s par lecture).
    regards = []
    vrai_portrait = marqueur_joueur.portrait_du_hud
    vrai_contraste = marqueur_joueur.contraste_du_portrait
    vrai_medaillon = marqueur_joueur.trouver_medaillon
    marqueur_joueur.portrait_du_hud = lambda img: (regards.append(img)
                                                   or (None, None))
    marqueur_joueur.contraste_du_portrait = lambda *a, **k: 55.0
    marqueur_joueur.trouver_medaillon = lambda img, **k: (regards.append(img)
                                                          or None)

    # ET ON N'ÉCRIT RIEN DANS screenshots/ : `--snap` est jugé sur
    # l'image qu'il enregistre, pas sur le fichier qu'il crée.
    ecrits = []
    vrai_imwrite = navigate.cv2.imwrite
    navigate.cv2.imwrite = lambda ou, image: (ecrits.append((ou, image))
                                              or True)
    try:
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            navigate.cmd_where(False, 0.80)

        check("une seule capture pour tout le diagnostic",
              len(prises) == 1, len(prises))
        regardees = vues + regards
        check("   tous les repères ont été jugés sur une image",
              bool(regardees) and all(img is not None for img in regardees),
              len(regardees))
        check("   et c'est la MÊME pour tous",
              bool(regardees) and all(img is regardees[0] for img in regardees),
              [id(img) for img in regardees])
        check("   le médaillon compris",
              len(regards) == 2 and bool(vues) and regards[0] is vues[0],
              (len(regards), len(vues)))
        check("   l'écran reconnu est quand même annoncé",
              "Écran reconnu" in sortie.getvalue(), sortie.getvalue()[:120])

        # `--snap` enregistre L'IMAGE QUI A ÉTÉ JUGÉE, pas une neuve :
        # sinon le rapport et la capture gardée décrivent deux instants.
        prises.clear()
        vues.clear()
        regards.clear()
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            navigate.cmd_where(True, 0.80)
        check("--snap ne rephotographie pas l'écran",
              len(prises) == 1, len(prises))
        check("   et il enregistre l'image jugée",
              len(ecrits) == 1 and bool(vues) and ecrits[0][1] is vues[0],
              [ou for ou, _ in ecrits])
    finally:
        marqueur_joueur.portrait_du_hud = vrai_portrait
        marqueur_joueur.contraste_du_portrait = vrai_contraste
        marqueur_joueur.trouver_medaillon = vrai_medaillon
        navigate.cv2.imwrite = vrai_imwrite
        restore()


def test_un_log_nannonce_pas_un_repli_qui_na_pas_lieu():
    """
    UN LOG QUI ANNONCE CE QUI NE SE PASSE PAS COÛTE DES HEURES.

    `_pick_champion` écrivait « Grille des champions illisible — on
    retombe sur le premier de la liste. » AVANT de regarder si le
    premier de la liste était seulement à l'écran. Depuis le correctif
    du 08/11 au soir, la ligne suivante dit souvent le contraire :
    « Le haut de la grille n'est pas à l'écran (0.50) : on rend la main
    pour relire ». Le lecteur de `logs/bot_run.log` voit un repli
    annoncé, puis aucun clic, et cherche le bogue dans `click_button`.

    On n'annonce donc plus une intention : on dit ce qu'on va REGARDER,
    puis ce qu'on a fait. Même exigence que partout ailleurs dans le
    projet — le diagnostic ne doit jamais dire autre chose que la
    décision.
    """
    print("\nUn log n'annonce pas un repli qui n'aura pas lieu")
    restore()

    import logging as _logging

    class Collecteur(_logging.Handler):
        def __init__(self):
            super().__init__(level=_logging.DEBUG)
            self.lignes = []

        def emit(self, record):
            self.lignes.append(record.getMessage())

    racine = _logging.getLogger()
    collecteur = Collecteur()
    niveau = racine.level
    racine.addHandler(collecteur)
    racine.setLevel(_logging.DEBUG)

    clics = []
    navigate.click_button = lambda name, timeout=10, **k: (clics.append(name)
                                                           or True)
    try:
        # Le cas du 08/11 : l'écran N'EST PAS la grille — c'était la
        # liste des défis. Aucun repli n'aura lieu.
        montre({"active_encounter", "monthly_challenge"})
        collecteur.lignes.clear()
        clics.clear()
        pris = navigate._pick_champion(1)
        dit = "\n".join(collecteur.lignes)
        check("hors de la grille : aucun clic", clics == [] and pris is False,
              (clics, pris))
        check("   et aucun repli annoncé",
              "retombe sur le premier" not in dit, dit)
        check("   mais le lecteur sait qu'on a regardé",
              "haut de la grille n'est pas à l'écran" in dit, dit)

        # La grille EST là : le repli joue, et il est annoncé — une fois
        # qu'il a eu lieu.
        montre({"first_champion", "use_attempt", "monthly_challenge"})
        collecteur.lignes.clear()
        clics.clear()
        pris = navigate._pick_champion(1)
        dit = "\n".join(collecteur.lignes)
        check("sur la grille : le repli clique bien",
              clics == ["first_champion"] and pris is True, (clics, pris))
        check("   et là il est annoncé", "retombe sur le premier" in dit, dit)
    finally:
        racine.removeHandler(collecteur)
        racine.setLevel(niveau)
        restore()


def test_no_attempt_left_is_only_the_launch_button():
    print("\nSeul le bouton de lancement absent veut dire « plus de tentative »")

    # Le champion se sélectionne, mais le bouton ne vient pas : c'est la
    # seule façon dont le jeu dit qu'il n'y a plus de tentative.
    restore()
    montre({"first_champion"})
    navigate.click_button = lambda name, timeout=10, **k: name != "use_attempt"
    check("plus de tentative", navigate.enter_challenge_attempt(retries=2, timeout=1)
          is Entry.NO_ATTEMPT_LEFT)

    # Mais buter AVANT — sur la vignette du champion — n'est pas la même
    # chose : là, on s'est perdu, et confondre les deux arrêterait la
    # session alors qu'il restait des tentatives à jouer.
    navigate.click_button = lambda name, timeout=10, **k: False
    check("échouer sur le champion, c'est être perdu",
          navigate.enter_challenge_attempt(retries=2, timeout=1) is Entry.LOST)


def test_an_open_adventure_is_resumed_not_relaunched():
    print("\nUne aventure déjà ouverte est REPRISE, pas relancée")

    # LE CAS DU 21/08/2026 : Ewan entre dans un défi à la main, puis lance
    # le bot. Aucun des quatre écrans d'entrée n'est là — l'ancienne
    # version rendait la main aussitôt, alors qu'il n'y avait qu'à
    # continuer.
    restore()
    # Aucun bouton d'entrée à l'écran, mais un repère de nœud : c'est une
    # carte d'aventure.
    montre({"support_champion_node"})
    # L'aventure est cherchée APRÈS les quatre écrans d'entrée : ses
    # repères sont plusieurs, donc plus exposés au faux positif, alors que
    # chaque écran d'entrée est signé par un bouton unique.
    check("l'aventure n'est pas dans la table des écrans d'entrée",
          all(Screen.ADVENTURE is not ecran
              for ecran, _ in navigate.SCREEN_ANCHORS),
          [e for e, _ in navigate.SCREEN_ANCHORS])
    check("elle a ses propres repères", "support_champion" in navigate.ADVENTURE_ANCHORS,
          navigate.ADVENTURE_ANCHORS)
    check("l'écran est reconnu comme une aventure en cours",
          navigate.where_are_we() is Screen.ADVENTURE, navigate.where_are_we())

    clics = []
    navigate.click_button = lambda name, timeout=10, **k: clics.append(name) or True
    verdict = navigate.enter_challenge_attempt(timeout=1)
    check("on reprend", verdict is Entry.RESUMED, verdict)
    check("sans cliquer quoi que ce soit", clics == [], clics)

    # Et la session la joue : la reprise n'est PAS comptée comme une
    # tentative consommée, puisque le jeu n'en a pas décompté.
    install(entries=[Entry.RESUMED, Entry.NO_ATTEMPT_LEFT],
            runs=[FakeCombat(True)])
    report = ChallengeSession().run()
    check("l'aventure est jouée", len(report.attempts) == 1, len(report.attempts))
    check("et gagnée", report.wins == 1, report.wins)
    check("aucune tentative dépensée",
          report.attempts[0].consumed is False, report.attempts[0].consumed)
    check("le bilan dit « reprise »",
          report.attempts[0].summary().startswith("reprise"),
          report.attempts[0].summary())


def test_une_aventure_en_cours_se_reprend_depuis_les_menus():
    """
    06/11/2026, 10:21 : le bot lancé devant le Défi 11 n'a jamais démarré.

    Une aventure était EN COURS. Le jeu le dit en toutes lettres : sur le
    panneau du défi, là où s'affiche d'habitude « UTILISER UNE TENTATIVE »,
    le bouton porte « REPRENDRE L'AVENTURE ». Le bot, lui, a suivi le
    chemin de la carte du monde sans regarder : liste des défis, défi,
    puis GRILLE DES CHAMPIONS — qui n'était pas affichée. Il a parcouru
    six rangées d'une grille absente, n'a pas trouvé `first_champion`, et
    a tourné en « écran inconnu » jusqu'à l'arrêt.

    `Screen.ADVENTURE` ne couvrait pas ce cas : il ne reconnaît qu'une
    CARTE d'aventure déjà ouverte, pas une aventure en cours vue DEPUIS
    LES MENUS. D'où `Screen.RESUME`, signé par son propre libellé
    (`assets/reprendre_aventure.png` : 1.00 ici, ≤ 0.33 sur les douze
    autres captures de référence). Il est testé EN PREMIER : sur cet
    écran `use_attempt` note 0.68 — sous le seuil, mais c'est le même
    cadre de bouton, et le départager par l'ordre coûte moins cher que de
    l'espérer.

    ET LA GRILLE DES CHAMPIONS NE DOIT PAS ÊTRE PARCOURUE sur cet
    écran-là : elle fait défiler à la molette, ce qui déplacerait la
    liste des défis sous le panneau. D'où le garde-fou dans le chemin
    depuis la carte du monde — dès que le bouton de reprise est là, la
    chaîne s'arrête et l'écran est relu.
    """
    print("\nUne aventure en cours se reprend DEPUIS LES MENUS")

    import cv2
    from pathlib import Path

    # 1. SUR LA VRAIE CAPTURE DU BLOCAGE, avec le vrai best_match.
    restore()
    capture = Path(__file__).resolve().parent / "captures_reference" / "reprendre_aventure_20261106.png"
    if not capture.exists():
        print("  (ignoré : reprendre_aventure_20261106.png absent)")
    else:
        ecran = cv2.imread(str(capture))
        navigate._capture_screen_bgr = lambda: ecran
        try:
            vu = navigate.where_are_we()
        finally:
            restore("_capture_screen_bgr")
        check("l'écran du blocage est reconnu : une aventure à reprendre",
              vu is Screen.RESUME, vu)
        score, _point = navigate.best_match(
            navigate.TEMPLATES["reprendre_aventure"], screen=ecran)
        check("son libellé est franc (≥ 0.90)", score is not None and score >= 0.90, score)
        attempt, _ = navigate.best_match(navigate.TEMPLATES["use_attempt"], screen=ecran)
        check("« utiliser une tentative » reste sous le seuil",
              attempt is not None and attempt < navigate.MATCH_THRESHOLD, attempt)

    # 2. DEPUIS CET ÉCRAN : un clic, et rien n'est consommé.
    restore()
    montre({"reprendre_aventure"})
    clics = []
    navigate.click_button = lambda name, timeout=10, **k: clics.append(name) or True
    verdict = navigate.enter_challenge_attempt(timeout=1)
    check("on reprend", verdict is Entry.RESUMED, verdict)
    check("en cliquant « reprendre l'aventure », et rien d'autre",
          clics == ["reprendre_aventure"], clics)

    # 3. LE GARDE-FOU : depuis la carte du monde, le bouton de reprise
    #    n'apparaît qu'APRÈS le choix du défi. La chaîne doit s'arrêter
    #    là, sans toucher à la grille des champions.
    restore()
    visibles = {"monthly_challenge", "active_encounter"}
    navigate._capture_screen_bgr = lambda: None
    navigate.best_match = lambda path, screen=None: (
        (0.95, (10, 10)) if any(path.endswith(n + ".png") for n in visibles)
        else (0.30, (0, 0))
    )
    clics = []

    def _clic(name, timeout=10, **k):
        clics.append(name)
        if name == "monthly_challenge":
            visibles.discard("monthly_challenge")
        return True

    def _defi(*_a, **_k):
        clics.append("défi")
        # le panneau du défi s'ouvre : une aventure y est en cours
        visibles.discard("active_encounter")
        visibles.add("reprendre_aventure")
        return True

    navigate.click_button = _clic
    navigate.topmost_match = lambda *a, **k: (100, 100)
    navigate.safe_click = _defi
    try:
        verdict = navigate.enter_challenge_attempt(timeout=1)
    finally:
        navigate.topmost_match = _VRAI_TOPMOST

    check("depuis les menus aussi, on reprend", verdict is Entry.RESUMED, verdict)
    check("la grille des champions n'est jamais parcourue",
          "first_champion" not in clics, clics)
    check("et aucune tentative n'est consommée",
          "use_attempt" not in clics, clics)
    check("le bouton de reprise est bien celui qu'on a cliqué",
          clics[-1] == "reprendre_aventure", clics)


def test_an_unresumable_adventure_says_so():
    print("\nUne aventure qu'on ne sait pas rattraper est nommée")

    # La navigation repart du champion de soutien : une aventure arrêtée
    # au deuxième node n'est pas rattrapable. Il faut le DIRE — et
    # surtout ne pas accuser les tentatives brûlées, puisqu'aucune ne l'a
    # été.
    install(entries=[Entry.RESUMED],
            runs=[parcours(reason=navigate.ARRIVAL_MISSED, combats=[], nodes=0)])
    report = ChallengeSession().run()

    check("arrêt après quelques essais",
          len(report.attempts) == challenges.ABANDON_LIMIT, len(report.attempts))
    check("le message parle de reprise impossible",
          "reprendre l'aventure" in report.reason, report.reason)
    check("et n'accuse pas les tentatives consommées",
          "consommée" not in report.reason, report.reason)


def test_recovery_only_closes_screens():
    print("\nLe retour à un écran connu ne lance jamais rien")

    # C'est la garantie qui permet d'appeler cette fonction dans le doute.
    # Un « Combat » ou un « Voyage » cliqué par erreur consommerait une
    # tentative, ou lancerait une partie que personne n'attend.
    interdits = {"combat_button", "voyage_button", "select_button", "retry",
                 "use_attempt", "monthly_challenge"}
    check("aucun bouton qui engage dans la liste de fermeture",
          not (set(navigate.DISMISS_BUTTONS) & interdits),
          navigate.DISMISS_BUTTONS)

    # Et concrètement : tant qu'aucun écran connu n'apparaît, elle clique
    # les fermetures ; dès qu'il apparaît, elle s'arrête.
    restore()
    vus = []
    ecrans = [Screen.UNKNOWN, Screen.UNKNOWN, Screen.CHAMPION]

    navigate.where_are_we = lambda: ecrans[min(len(vus), len(ecrans) - 1)]

    def fake_click(name, timeout=10, **kwargs):
        vus.append(name)
        return False        # rien ne se ferme : on force plusieurs tours

    garages = []
    navigate.click_button = fake_click
    navigate.park_mouse = lambda: garages.append(len(vus))
    # Pas de « Relevez-vous » à l'écran (sans ce bouchon, une vraie capture).
    navigate.best_match = lambda path, screen=None: (0.30, (0, 0))
    # NI DE CAPTURE POUR DÉPARTAGER COFFRE ET RÉCOMPENSE (08/11/2026) :
    # le garde les mesure sur UNE SEULE capture, qu'il prend lui-même.
    # Sans ce bouchon, la suite hors ligne photographiait VRAIMENT
    # l'écran d'Ewan — mesuré à l'espion, une fois par exécution.
    navigate._capture_screen_bgr = lambda: None
    screen = navigate.back_to_known_screen(timeout=60)

    check("elle rend l'écran retrouvé", screen is Screen.CHAMPION, screen)
    check("elle a bien cliqué quelque chose", len(vus) > 0, vus)
    check("elle n'a cliqué que des fermetures",
          vus and set(vus) <= set(navigate.DISMISS_BUTTONS), set(vus))
    # Demandé par Ewan (02/09/2026) : quand TOUS les boutons ont été
    # cherchés en vain, la souris est déplacée — elle cachait peut-être
    # le bouton. Une fois par tour complet, jamais au milieu d'un tour.
    n = len(navigate.DISMISS_BUTTONS)
    check("la souris est garée après le tour complet sans bouton",
          garages == [n], (garages, n))

    # « VOUS ÊTES MORT … RELEVEZ-VOUS » (05/09/2026) : ce bouton relance un
    # combat, la récupération ne le clique pas — et comme rien d'autre ne
    # fermera cet écran, elle rend la main TOUT DE SUITE au lieu de tourner
    # deux minutes (le bot y a perdu 2 × 120 s ce jour-là).
    vus.clear()
    navigate.where_are_we = lambda: Screen.UNKNOWN
    navigate.best_match = lambda path, screen=None: (
        (1.00, (960, 912)) if path.endswith("retry.png") else (0.30, (0, 0)))
    t0 = time.time()
    screen = navigate.back_to_known_screen(timeout=60)
    check("« Relevez-vous » à l'écran : écran inconnu rendu aussitôt",
          screen is Screen.UNKNOWN and time.time() - t0 < 5, (screen, time.time() - t0))
    check("   sans le cliquer", "retry" not in vus, vus)


# ============================================================
# PARCOURIR LA CARTE, DANS SON ORDRE
# ============================================================

def scripter_carte(*points):
    """
    Fait apparaître les nœuds demandés, l'un après l'autre.

    Chaque appel à `locate_node` rend le point suivant — ou None quand la
    liste est épuisée, ce qui simule un nœud introuvable. Les cibles
    demandées sont notées : c'est l'ORDRE qu'on veut vérifier.
    """
    suite = list(points)
    cibles = []

    def fake_locate(cible, wait=None, exclude=()):
        cibles.append(cible)
        return suite.pop(0) if suite else None

    navigate.locate_node = fake_locate
    navigate.safe_click = lambda *a, **k: True
    navigate.click_button = lambda name, timeout=10, **k: name == "voyage_button"
    navigate.save_screen = lambda *a, **k: ""
    # Aucune capture d'écran réelle dans les tests : `save_screen` est
    # bouchonné, mais `goto_node` capture AVANT de l'appeler.
    navigate._capture_screen_bgr = lambda: None
    # Ce que le nœud propose n'est pas le sujet de ces tests-là : l'écran
    # d'arrivée n'offre que « Quitter ». Sans ce bouchon, `resolve_arrival`
    # appellerait le vrai `best_match`, donc une vraie capture d'écran.
    navigate.best_match = lambda path, screen=None: (
        (0.95, (10, 10)) if path.endswith("quit_button.png") else (0.30, (0, 0))
    )
    return cibles


def test_une_recompense_de_combat_nest_pas_un_ecran_a_fermer():
    """
    06/11/2026, fin d'une session de 90 minutes : « RÉCOMPENSES DE
    COMBAT — Choisissez un objet à équiper sur l'un de vos champions ».
    Deux champions, trois objets, « Sélectionner » grisé, +19 PV à la
    clé. Le bot a tourné 120 s dessus puis la SESSION ENTIÈRE s'est
    arrêtée : « impossible de revenir à un écran connu ».

    Pourtant le panneau est parfaitement reconnu — mesuré sur
    `captures_reference/recompense_combat_20261106.png` :
    `recompense_select_grise` 1.00, `select_button` 0.94. Et `events.
    RECOMPENSE` sait le jouer depuis le 05/11.

    LE TROU N'ÉTAIT PAS LA RECONNAISSANCE, C'ÉTAIT LE MOMENT.
    `navigate.play_reward` ne guette cette récompense que quelques
    secondes après le combat du boss INTERMÉDIAIRE ; celle-ci est tombée
    ailleurs. Et `back_to_known_screen` ne clique que `DISMISS_BUTTONS`
    — « Continuer » 0.32, « Quitter » 0.39, rien ne passait.

    UNE RÉCOMPENSE N'EST PAS UN ÉCRAN À FERMER, C'EST UN CADEAU À
    PRENDRE : la fonction qui sert à se rattraper doit la jouer, comme
    elle sait déjà reconnaître « Relevez-vous » pour ne pas tourner
    dessus.
    """
    print("\nUne récompense de combat se PREND, elle ne se ferme pas")

    restore()
    montre({"recompense_select_grise"})
    vrai_reward = navigate.play_reward
    clics = []
    pris = []
    navigate.click_button = lambda name, timeout=10, **k: clics.append(name) or False
    navigate.play_reward = lambda etiquette, **k: (pris.append(etiquette), {"closed": True})[1]
    try:
        ecran = navigate.back_to_known_screen(timeout=0.1)
    finally:
        navigate.play_reward = vrai_reward
        restore()

    check("la récompense est JOUÉE, pas fermée", pris, pris)
    check("   et aucun bouton de fermeture n'a été cliqué à sa place",
          not any(n in ("continue_button", "quit_button",
                        "continue_button_after_combat") for n in clics), clics)

    # ET LA MESURE QUI LE JUSTIFIE, sur la capture réelle.
    import cv2
    from pathlib import Path
    import adventure_navigation as an
    capture = (Path(__file__).resolve().parent / "captures_reference"
               / "recompense_combat_20261106.png")
    image = cv2.imread(str(capture))
    if image is None:
        print("  (ignore : recompense_combat_20261106.png absent)")
        return
    score, point = an.best_match(an.TEMPLATES["recompense_select_grise"], screen=image)
    check("le panneau est reconnu sur la vraie capture", score >= 0.80, score)
    check("   bouton en (961, 1002)",
          abs(point[0] - 961) <= 8 and abs(point[1] - 1002) <= 8, point)
    for nom in ("continue_button", "quit_button"):
        s, _ = an.best_match(an.TEMPLATES[nom], screen=image)
        check(f"   « {nom} » n'y est pas ({s:.2f}) — d'où les 120 s perdues",
              s < 0.80, s)


def test_un_coffre_reste_ouvert_nest_pas_une_recompense():
    """
    08/11/2026 : la dette du 06/11, et ce qu'elle a coûté.

    « `back_to_known_screen` sait prendre une récompense, pas un
    coffre » — c'était écrit, et c'est arrivé. Un coffre d'objets de
    champion est resté ouvert ; le garde l'a pris pour une récompense,
    parce que `recompense_select_grise` note **0.83 sur un coffre**,
    au-dessus du seuil. Il lui a donc appliqué la géométrie de la
    récompense, qui est ancrée sur un AUTRE bouton (centre 961 contre
    1442) : les clics sont partis en (1270, 459) et (1096, 766) — nulle
    part — huit fois, puis « écran inconnu », puis la SESSION s'est
    arrêtée.

    LES DEUX PANNEAUX SE DÉPARTAGENT SANS AMBIGUÏTÉ, à condition de les
    mesurer SUR LA MÊME CAPTURE plutôt que de laisser un ordre d'essai
    décider — la règle de `where_are_we`, qui vaut ici aussi.
    """
    print(chr(10) + "Un coffre resté ouvert se RAMASSE, il ne se joue pas en récompense")

    import cv2
    from pathlib import Path
    import adventure_navigation as an
    reference = Path(__file__).resolve().parent / "captures_reference"

    # LA MESURE D'ABORD : c'est elle qui justifie le code.
    cas = [("coffre_trois_champions_sombre_20261108.png", "coffre"),
           ("coffre_choix_20261105.png", "coffre"),
           ("coffre_trois_champions_20261106.png", "coffre"),
           ("recompense_combat_20261106.png", "récompense"),
           ("recompense_trois_champions_20261106.png", "récompense"),
           ("recompense_grisee_20261106.png", "récompense")]
    for nom, attendu in cas:
        image = cv2.imread(str(reference / nom))
        if image is None:
            print(f"  (ignoré : {nom} absent)")
            continue
        recompense = an.best_match(an.TEMPLATES["recompense_select_grise"], screen=image)[0] or 0.0
        coffre = max((an.best_match(an.TEMPLATES[k], screen=image)[0] or 0.0)
                     for k in ("treasure_button", "coffre_objets_champion"))
        lu = "coffre" if coffre >= recompense else "récompense"
        check(f"{nom[:42]} -> {attendu} (coffre {coffre:.2f} / récomp. {recompense:.2f})",
              lu == attendu, lu)

    # ET LE GARDE S'EN SERT : sur un écran de coffre, il joue le COFFRE.
    restore()
    navigate._capture_screen_bgr = lambda: None
    navigate.best_match = lambda path, screen=None: (
        (1.00, (1442, 1002)) if any(path.endswith(n + ".png") for n in
                                    ("treasure_button", "coffre_objets_champion",
                                     "take_treasure_button"))
        else (0.83, (961, 1002)) if path.endswith("recompense_select_grise.png")
        else (0.30, (0, 0)))
    joues, recompenses, clics = [], [], []
    vrai_event, vrai_reward = navigate.play_event, navigate.play_reward
    navigate.play_event = lambda etiquette, panneau=None: (
        joues.append((etiquette, getattr(panneau, "nom", None))), {"closed": True})[1]
    navigate.play_reward = lambda etiquette, **k: (recompenses.append(etiquette),
                                                   {"closed": True})[1]
    navigate.click_button = lambda name, timeout=10, **k: clics.append(name) or False
    try:
        navigate.back_to_known_screen(timeout=0.1)
    finally:
        navigate.play_event, navigate.play_reward = vrai_event, vrai_reward
        restore()

    check("le coffre est RAMASSÉ", joues, joues)
    check("   avec le panneau du coffre, pas celui de la récompense",
          any(nom == "Coffre" for _, nom in joues), joues)
    check("   et `play_reward` n'est jamais appelé", not recompenses, recompenses)
    check("   et « Quitter » n'est pas cliqué à sa place (il jetterait le trésor)",
          "quit_button" not in clics, clics)


def test_arrival_is_decided_by_what_the_game_offers():
    print("\nCe qu'un nœud propose se découvre à l'arrivée, en UNE lecture")

    restore()
    clics, captures, valides, evenements = [], [], [], []
    navigate.safe_click = lambda x, y, **k: (clics.append((x, y)), True)[1]
    navigate.save_screen = lambda ecran, etiquette="carte": captures.append(etiquette)
    navigate.click_button = lambda name, timeout=10, **k: valides.append(name) or True
    navigate._capture_screen_bgr = lambda: None
    navigate.play_event = lambda etiquette: evenements.append(etiquette) or {"picked": [], "steps": 0, "closed": True, "escaped": False}

    lectures = []

    def ecran(**scores):
        """
        L'écran d'arrivée, bouton par bouton, avec le score de chacun.

        Chaque bouton reçoit un point distinct : on veut pouvoir dire
        LEQUEL a été cliqué, pas seulement qu'un clic a eu lieu.
        """
        points = {name: (100 + 10 * n, 200) for n, name in enumerate(scores)}

        def fake(path, screen=None):
            lectures.append(path)
            for name, score in scores.items():
                if path.endswith(name + ".png"):
                    return score, points[name]
            return 0.30, (0, 0)

        navigate.best_match = fake
        return points

    def rejoue():
        clics.clear(), captures.clear(), valides.clear(), lectures.clear(), evenements.clear()

    # Un combat : c'est le bouton « Combat » qui le dit, et il l'emporte —
    # le manquer laisserait le jeu attendre.
    rejoue()
    points = ecran(combat_button=0.95, quit_button=0.99)
    check("combat reconnu",
          navigate.resolve_arrival(timeout=1) == navigate.ARRIVAL_COMBAT)
    check("et c'est « Combat » qui est cliqué, même moins net que « Quitter »",
          clics == [points["combat_button"]], clics)

    # TOUS les repères d'arrivée sont lus sur la MÊME capture, en un seul
    # passage — c'est ce qui permet au score de trancher plutôt qu'à un
    # ordre d'essai (bogue du 22/08/2026). On compte donc par rapport à
    # ARRIVAL_BUTTONS et non par un nombre figé : le coffre en a ajouté un
    # cinquième le 04/11/2026.
    check("tous les boutons d'arrivée lus en une fois",
          len(lectures) == len(navigate.ARRIVAL_BUTTONS), (lectures, navigate.ARRIVAL_BUTTONS))

    # Un événement : une option, puis le PANNEAU qu'elle ouvre est joué
    # (choix de carte, fermeture) par events.resolve_event — plus un simple
    # « Sélectionner » à l'aveugle (La Grand-place, 04/09/2026).
    rejoue()
    points = ecran(event_option=0.91)
    check("événement reconnu",
          navigate.resolve_arrival(timeout=1) == navigate.ARRIVAL_EVENT)
    check("l'option est cliquée", clics == [points["event_option"]], clics)
    check("puis le panneau est joué", evenements == ["événement"], evenements)
    check("   et plus de « Sélectionner » à l'aveugle", valides == [], valides)

    # LE BOGUE DU 22/08/2026. L'écran n'offrait que « Quitter », mais
    # `select_button.png` y trouvait une fausse correspondance au-dessus du
    # seuil. Essayé en premier, il gagnait. Le score le lui retire.
    rejoue()
    points = ecran(select_button=0.82, quit_button=0.96)
    check("le meilleur score l'emporte sur l'ordre d'essai",
          navigate.resolve_arrival(timeout=1) == navigate.ARRIVAL_CLOSED)
    check("c'est « Quitter » qui est cliqué", clics == [points["quit_button"]], clics)
    check("et l'écran ambigu est gardé", captures == ["arrivee_ambigue"], captures)

    # FERMER UN NŒUD, C'EST RENONCER À CE QU'IL OFFRAIT. Le 04/11/2026, sur
    # une aventure de trois nœuds, DEUX ont été fermés par « Quitter » avant
    # le boss final : la trace n'en garde qu'un mot, et rien ne dit ce que le
    # bot avait sous les yeux ni si « Quitter » était le seul choix.
    rejoue()
    points = ecran(quit_button=0.98)
    check("« Quitter » seul ferme le nœud",
          navigate.resolve_arrival(timeout=1) == navigate.ARRIVAL_CLOSED)
    check("   le bouton est bien cliqué", clics == [points["quit_button"]], clics)
    check("   et l'écran quitté est gardé", captures == ["noeud_quitte"], captures)

    # « Sélectionner » referme aussi, mais c'est le cas ORDINAIRE (champion
    # de soutien présélectionné) : le garder remplirait screenshots/ pour rien.
    rejoue()
    ecran(select_button=0.95)
    navigate.resolve_arrival(timeout=1)
    check("« Sélectionner » ne garde rien", captures == [], captures)

    # L'inverse doit rester vrai : un vrai « Sélectionner » gagne contre un
    # « Quitter » douteux. Le correctif ne doit pas renverser la règle,
    # seulement la faire dépendre de ce qu'on voit.
    rejoue()
    points = ecran(select_button=0.97, quit_button=0.81)
    check("un « Sélectionner » net l'emporte à son tour",
          navigate.resolve_arrival(timeout=1) == navigate.ARRIVAL_CHOICE)
    check("c'est lui qui est cliqué", clics == [points["select_button"]], clics)
    # Le bouton est toujours là après le clic (l'écran factice ne change
    # pas) : un choix est attendu, le panneau est joué.
    check("   toujours affiché après le clic -> le choix est joué", evenements == ["choix"], evenements)

    # Rien de connu : on ne suppose rien, on ne clique pas ailleurs pour
    # voir — et l'écran est gardé, sinon « rien à faire » n'apprend rien.
    rejoue()
    ecran()
    check("rien à faire",
          navigate.resolve_arrival(timeout=1) == navigate.ARRIVAL_NOTHING)
    check("aucun clic au hasard", clics == [], clics)
    check("et l'écran muet est gardé", captures == ["arrivee_sans_bouton"], captures)


def test_the_arrival_panel_is_waited_for():
    print("\nLe panneau d'arrivée est attendu, pas lu une seule fois")

    # Le panneau s'ouvre avec une animation : la première lecture tombe
    # sur un écran encore vide. C'est la même leçon que pour les nœuds —
    # attendre, plutôt que conclure « rien à faire » trop tôt.
    restore()
    clics = []
    navigate.safe_click = lambda x, y, **k: (clics.append((x, y)), True)[1]
    navigate.save_screen = lambda *a, **k: ""
    navigate._capture_screen_bgr = lambda: None

    tours = []

    def tardif(path, screen=None):
        tours.append(path)
        if len(tours) <= 4:          # la première lecture ne voit rien
            return 0.20, (0, 0)
        return (0.95, (300, 400)) if path.endswith("quit_button.png") else (0.30, (0, 0))

    navigate.best_match = tardif
    check("on finit par lire le panneau",
          navigate.resolve_arrival(timeout=5) == navigate.ARRIVAL_CLOSED)
    check("et on a bien relu l'écran", len(tours) > 4, len(tours))


def test_the_support_champion_panel_is_given_time_to_fill():
    """
    LE PANNEAU S'AFFICHE AVANT SON CONTENU (mesuré par Ewan, 22/08/2026).

    Après le « Voyage » vers le nœud du champion de soutien, le cadre et
    son bouton sont lisibles environ deux secondes avant les champions
    eux-mêmes. Lire à cet instant, c'est valider un panneau vide.

    Deux choses sont vérifiées, et la seconde est celle qu'on oublie :
    l'attente existe, et `--speed` ne la raccourcit pas — `human_delay`
    divise par `GESTURE_SPEED`, donc sans plancher deux secondes en
    vaudraient une à la vitesse par défaut.
    """
    print("\nLe panneau du champion de soutien a le temps de se remplir")

    import click_utils
    from test_clock import virtual_elapsed

    restore()
    navigate.safe_click = lambda x, y, **k: True
    navigate.click_button = lambda name, timeout=10, **k: True
    navigate.save_screen = lambda *a, **k: ""
    navigate._capture_screen_bgr = lambda: None
    # Le bouton reste « visible » sur cet écran factice : le panneau serait
    # joué ; ici on mesure seulement l'attente, on le neutralise.
    navigate.play_event = lambda etiquette: {"picked": [], "steps": 0, "closed": True, "escaped": False}
    navigate.best_match = lambda path, screen=None: (
        (0.95, (300, 400)) if path.endswith("select_button.png") else (0.30, (0, 0))
    )

    def duree(**kwargs):
        depart = virtual_elapsed()
        navigate.resolve_arrival(timeout=1, **kwargs)
        return virtual_elapsed() - depart

    sans = duree()
    avec = duree(settle=navigate.SUPPORT_CHAMPION_SETTLE)
    # Les délais « humains » sont tirés au sort : on compare à la pause de
    # 2 s, pas à un chiffre rond (1,1-1,2 s de gestes mesurés sans elle).
    check("les autres nœuds lisent tout de suite", sans < navigate.SUPPORT_CHAMPION_SETTLE[0], sans)
    check("celui-ci attend deux secondes de plus",
          avec >= navigate.SUPPORT_CHAMPION_SETTLE[0] and avec > sans, (sans, avec))

    vitesse = click_utils.GESTURE_SPEED
    click_utils.GESTURE_SPEED = 8.0
    try:
        presse = duree(settle=navigate.SUPPORT_CHAMPION_SETTLE)
    finally:
        click_utils.GESTURE_SPEED = vitesse
    check("et la vitesse des gestes ne les raccourcit pas", presse >= 2.0, presse)

    # L'attente est réservée à CE nœud : la payer partout coûterait deux
    # secondes par étape et par tentative, pour rien.
    restore()
    cibles = scripter_carte(*[(100 + 10 * i, 200) for i in range(4)])
    attentes = []
    navigate.has_mid_boss = lambda wait=None: False
    navigate.resolve_arrival = lambda timeout=None, settle=None: (
        attentes.append(settle) or navigate.ARRIVAL_COMBAT
    )
    lor_battle.try_combat = lambda x, y, **k: FakeCombat(True)
    navigate.run_adventure()
    check("le champion de soutien est le premier nœud",
          cibles[0] == "support_champion", cibles)
    check("lui seul attend",
          attentes == [navigate.SUPPORT_CHAMPION_SETTLE, None, None, None],
          attentes)


def test_goto_node_needs_the_voyage_button():
    print("\nSans « Voyage », on n'a pas bougé")

    restore()
    scripter_carte((10, 20), (10, 20), (10, 20))
    captures = []
    navigate.save_screen = lambda ecran, etiquette="carte": captures.append(etiquette)
    navigate.click_button = lambda name, timeout=10, **k: False   # rien ne répond
    navigate._capture_screen_bgr = lambda: None

    arrivee, _ = navigate.goto_node("final_boss", "boss final", wait=1)
    check("le déplacement raté est nommé", arrivee == navigate.ARRIVAL_MISSED, arrivee)
    check("et l'écran est gardé", captures == ["sans_voyage"], captures)


def test_a_node_that_arrives_late_is_waited_for():
    print("\nUn nœud qui tarde est attendu, pas abandonné")

    # La carte revient avec une animation : les deux premières lectures ne
    # voient rien. C'est la régression du 21/08 — corrigée ici par les
    # réessais, pas par la chance.
    restore()
    scripter_carte(None, None, (500, 400))
    arrivee, point = navigate.goto_node("support_champion", "champion", wait=1)
    check("on finit par le trouver", point == (500, 400), point)
    check("et on voit ce qu'il propose", arrivee != navigate.ARRIVAL_MISSED, arrivee)


def test_the_leftmost_node_is_chosen_not_the_first_template():
    print("\nSur une carte réelle, le nœud retenu est devant nous — ni le bloqué, ni celui laissé de côté")

    # Capture d'Ewan du 02/09/2026 (1912x1075) : trois nœuds non visités,
    # le coffre (~1110, 385) et le « ! » (~1112, 590) atteignables, le
    # combat (~1435, 595) BLOQUÉ. Les templates sont des rubans de l'ARC
    # SUPÉRIEUR de l'anneau : le point rendu est ~40 px au-dessus du centre
    # du nœud — c'est là que le bot clique depuis toujours, et l'anneau
    # est cliquable. Avec « premier template qui franchit le
    # seuil, puis sa meilleure position », normal_node.png choisissait le
    # bloqué à 0.93. Le nœud visité (~563, 610) et le portrait du
    # personnage doivent rester sous le seuil.
    import cv2
    from pathlib import Path
    import adventure_navigation as an

    capture = Path(__file__).resolve().parent / "calibration_crops" / "carte_noeud_bloque_20260902.png"
    if not capture.exists():
        print(f"  (ignoré : {capture.name} absent)")
        return
    ecran = cv2.imread(str(capture))
    noeuds = an.find_nodes_in_folder(navigate.NODES_DIR, screen=ecran)
    points = [p for _s, p, _n in noeuds]

    COFFRE, EVENEMENT, BLOQUE = (1110, 348), (1112, 555), (1435, 562)

    def pres(point, cible, tol=25):
        return abs(point[0] - cible[0]) <= tol and abs(point[1] - cible[1]) <= tol

    check("les trois nœuds non visités sont vus, une fois chacun",
          len(noeuds) == 3 and all(any(pres(p, c) for p in points)
                                   for c in (COFFRE, EVENEMENT, BLOQUE)),
          noeuds)
    check("le nœud visité et le portrait ne sont pas des candidats",
          not any(pres(p, c, 40) for p in points for c in ((563, 610), (793, 450))), points)
    check("le premier de la liste est un nœud atteignable",
          noeuds and (pres(points[0], COFFRE) or pres(points[0], EVENEMENT)), noeuds[:1])
    check("le nœud bloqué est le dernier", noeuds and pres(points[-1], BLOQUE), noeuds[-1:])

    # NOTRE MARQUEUR (le losange sous le portrait) est lu sur la même
    # capture : ~ (793, 537), à gauche de tout.
    score, marqueur = an.best_match(an.TEMPLATES["player_marker"], screen=ecran)
    check("le marqueur du joueur est trouvé", score is not None and score >= 0.80
          and pres(marqueur, (793, 537)), (score, marqueur))

    # LE CHOIX TIENT COMPTE D'OÙ ON EST. Depuis le champion de soutien, les
    # deux nœuds de la colonne suivante sont atteignables ; on prend le plus
    # proche. Depuis le COFFRE (chemin du haut), le « ! » du bas est à la
    # même hauteur en x — non visité, toujours reconnu, mais plus relié à
    # nous : la marge l'écarte, il reste le combat.
    choix = an.pick_next_node(noeuds, marqueur)
    check("depuis le champion : un des deux nœuds de la colonne suivante",
          choix and (pres(choix[1], COFFRE) or pres(choix[1], EVENEMENT)), choix)
    depuis_coffre = (COFFRE[0], COFFRE[1] + 130)  # le losange est sous le portrait
    choix = an.pick_next_node(noeuds, depuis_coffre)
    check("depuis le coffre : le combat, pas le « ! » du bas", choix and pres(choix[1], BLOQUE), choix)
    check("rien devant nous → None", an.pick_next_node(noeuds, (1500, 500)) is None)
    check("sans marqueur : le plus à gauche", an.pick_next_node(noeuds, None) == noeuds[0])
    check("sans candidat : None", an.pick_next_node([], marqueur) is None)

    # Et c'est bien ce que locate_node rend, sans souris ni attente réelle.
    restore()
    an_capture = an._capture_screen_bgr
    an._capture_screen_bgr = lambda: ecran
    navigate._capture_screen_bgr = lambda: ecran
    try:
        point = navigate.locate_node(navigate.NODES_DIR, wait=1)
    finally:
        an._capture_screen_bgr = an_capture
        restore("_capture_screen_bgr")
    check("locate_node rend un nœud atteignable",
          point is not None and (pres(point, COFFRE) or pres(point, EVENEMENT)), point)


def test_le_marqueur_du_joueur_tient_sur_dautres_cartes():
    """
    06/11/2026 : le marqueur n'était trouvé QUE sur la capture dont son
    gabarit avait été découpé.

    Le test voisin l'exige à 0.80 sur `carte_noeud_bloque_20260902.png` —
    l'écran du jour où `player_marker.png` a été taillé — et il est vert
    depuis. Sur les cartes des tentatives du 05 et du 06/11, le même
    gabarit plafonne à 0.56-0.61 : AU BON ENDROIT, et pourtant sous le
    seuil. `_player_position` rendait donc None à chaque lecture, la
    position retombait sur le centre de l'écran puis sur « le plus à
    gauche », et deux tentatives mensuelles se sont perdues à recliquer un
    nœud injoignable en (1819, 470) — journal du 06/11 : « deuxième nœud
    introuvable », « boss final introuvable ».

    LA BOÎTE DU GABARIT N'EST PAS LE MARQUEUR. Elle fait 46 × 52 pour un
    losange qui n'en occupe que 46 % : le reste est du décor de carte
    (neige, roche, ciel, lignes de chemin cyan) qui change d'un écran à
    l'autre — plus, dans le gabarit lui-même, les décorations de sa
    capture d'origine, une ligne cyan et un triangle bleu qui ne font pas
    partie du losange. C'est ce décor que TM_CCOEFF_NORMED note. Masqué au
    losange (canal alpha du PNG, même parade que le jeton d'attaque), le
    même gabarit donne 0.88-0.91 là où le marqueur est, et ne dépasse pas
    0.60 là où il n'y en a pas : le seuil de 0.80 sépare enfin les deux.

    Les trois captures sont gardées dans `captures_reference/` — ce sont
    elles qui verrouillent les seuils.
    """
    print("\nLe marqueur du joueur tient sur d'autres cartes que la sienne")

    import cv2
    from pathlib import Path
    import adventure_navigation as an

    reference = Path(__file__).resolve().parent / "captures_reference"

    def pres(point, cible, tol=8):
        return point is not None and abs(point[0] - cible[0]) <= tol \
            and abs(point[1] - cible[1]) <= tol

    def lire(nom):
        chemin = reference / nom
        if not chemin.exists():
            return None, (None, None)
        ecran = cv2.imread(str(chemin))
        return ecran, an.best_match(an.TEMPLATES["player_marker"], screen=ecran)

    # 1. CARTE OUVERTE, losange en plein décor de neige (capture
    #    `noeud_introuvable_20261106_002429.png` de la tentative perdue :
    #    le marqueur est à (515, 454), le bot l'a lu 0.61 et l'a refusé).
    ecran, (score, point) = lire("carte_marqueur_20261106.png")
    if ecran is None:
        print("  (ignoré : carte_marqueur_20261106.png absent)")
    else:
        check("carte ouverte : le marqueur est trouvé, au-dessus du seuil",
              score is not None and score >= navigate.MATCH_THRESHOLD, score)
        check("carte ouverte : et c'est bien le losange, en (515, 454)",
              pres(point, (515, 454)), point)

    # 2. PANNEAU OUVERT, losange au BORD GAUCHE de l'écran (capture du
    #    soigneur du 06/11 : le panneau couvre la moitié de la carte, le
    #    losange n'en déborde pas moins à (31, 323)). C'est le cas que la
    #    bande centrale du seuil souple ne rattrapait pas : il est loin du
    #    centre.
    ecran, (score, point) = lire("soigneur_20261106.png")
    if ecran is None:
        print("  (ignoré : soigneur_20261106.png absent)")
    else:
        check("panneau ouvert : le marqueur du bord gauche est trouvé",
              score is not None and score >= navigate.MATCH_THRESHOLD, score)
        check("panneau ouvert : en (31, 323), hors de la bande centrale",
              pres(point, (31, 323)), point)
        # MAIS CE LOSANGE N'EST PAS NOUS (08/11/2026, confirmé par Ewan).
        # Le gabarit reconnaît très bien un DÉCOR DE TRACÉ ; notre
        # position est un médaillon rond au portrait du champion joué.
        # L'assertion d'origine demandait ici la position DU LOSANGE :
        # elle mesurait la fidélité du gabarit et la prenait pour la
        # justesse de la lecture. C'est la leçon du projet retournée
        # contre lui-même — « un repère presque reconnu » avait été
        # réparé, sans qu'on vérifie qu'il désignait la bonne chose.
        check("mais la position lue est le MÉDAILLON, en (246, 452)",
              pres(navigate._player_position(ecran), (246, 452)),
              navigate._player_position(ecran))

    # 3. CARTE MASQUÉE : le panneau de la boutique couvre tout ce qui
    #    compte, il n'y a AUCUN losange à l'écran. Un masque qui ferait
    #    monter les scores partout rendrait ici un faux positif — et un
    #    faux marqueur est pire qu'un marqueur absent : il oriente le
    #    choix du nœud suivant vers un point qui n'existe pas.
    ecran, (score, point) = lire("boutique_20261105.png")
    if ecran is None:
        print("  (ignoré : boutique_20261105.png absent)")
    else:
        check("aucun losange ne passe, même pas le seuil souple",
              score is not None and score < navigate.MARKER_SOFT_THRESHOLD, (score, point))
        # ET LA CARTE N'ÉTAIT PAS MASQUÉE (08/11/2026). L'assertion
        # d'origine demandait `None` ici, au motif que « le panneau de la
        # boutique couvre tout ce qui compte ». Vérifié à l'image : le
        # médaillon du champion est parfaitement visible en (261, 449),
        # le panneau ne couvre pas cette partie de la carte. Ce n'était
        # pas une absence de marqueur, c'était l'absence d'un LOSANGE —
        # et on en avait conclu qu'il n'y avait rien à voir.
        check("et pourtant le médaillon est là, en (261, 449)",
              pres(navigate._player_position(ecran), (261, 449)),
              navigate._player_position(ecran))

    # 4. ET LE RESTE DES GABARITS NE BOUGE PAS. Vingt-deux PNG d'`assets`
    #    portaient déjà un canal alpha avant ce chantier ; vingt sont
    #    opaques à 100 % — un masque tout blanc, donc le calcul d'avant.
    #    Mesuré sur 52 captures : écart maximum 0.00021. Le POINT rendu
    #    change parfois (deux pics presque égaux s'échangent la première
    #    place), mais jamais au-dessus du seuil : 51 cas à 0.75 ou plus,
    #    51 positions identiques.
    #    Le seul autre à cacher quelque chose est `continue_button.png`
    #    (1.7 %, entièrement sur le bord : un artefact de découpe), et le
    #    masquer AMÉLIORE les deux côtés — « Continuer » présent passe de
    #    0.984 à 1.000, absent descend de 0.558 à 0.492.
    #    (Le témoin était `final_boss` jusqu'au 08/11/2026 ; il porte
    #    maintenant un masque à lui — cf. le test suivant — donc le rôle
    #    revient à `enemy_node`, opaque à 100 % lui aussi.)
    if ecran is not None:
        opaque = an.TEMPLATES.get("enemy_node")
        if opaque:
            import numpy as np
            brut_tpl = cv2.imread(opaque, cv2.IMREAD_UNCHANGED)
            nu = cv2.matchTemplate(ecran, brut_tpl[:, :, :3], cv2.TM_CCOEFF_NORMED)
            _, attendu, _, _ = cv2.minMaxLoc(nu)
            score, _point = an.best_match(opaque, screen=ecran)
            check("un gabarit opaque est comparé exactement comme avant",
                  abs(score - attendu) < 1e-4, (score, attendu))


def test_le_boss_final_se_reconnait_dans_ses_trois_etats():
    """
    08/11/2026 : le nœud du boss n'était reconnu que dans UN de ses états.

    `assets/final_boss.png` était la CRÊTE dorée du médaillon, découpée
    avec son halo bleu. Mesuré sur les quatre captures du diagnostic :

        route bloquée, pas de halo ......... 0.59  au bon endroit
        joignable, halo bleu ............... 0.87  au bon endroit
        nœud courant, voyage fait .......... 0.33  au bon endroit
                                             (0.54 rendu à 970 px de là)

    DEUX CAUSES, MESURÉES SÉPARÉMENT, ET AUCUNE N'EST L'ÉCHELLE DU
    CADRAGE. La première est celle de `player_marker` : la boîte portait
    du DÉCOR — le halo bleu, qui n'existe que dans l'état « joignable »,
    et c'est tout l'écart entre 0.87 et 0.59, le médaillon étant par
    ailleurs identique. La seconde est nouvelle et plus dure : une fois
    le voyage fait, le jeu pose NOTRE portrait de champion juste
    au-dessus du nœud, et il couvre ENTIÈREMENT la crête — c'est-à-dire
    exactement ce que le gabarit comparait. Vérifié à l'image : dans la
    boîte du gabarit, à sa vraie position, il n'y a plus que le médaillon
    du joueur. Un masque ne rattrape pas une forme cachée : il faut
    comparer autre chose.
    Ce que les trois états ont en commun, ce sont les deux AILES dorées
    et l'ANNEAU. Le gabarit est donc la boîte de l'emblème moins sa
    crête, masquée à l'OR (canal alpha, même mécanique que le jeton
    d'attaque et le losange du joueur). Hors masque : le halo, le fond de
    carte, et le portrait du boss — qui change à chaque aventure.

    L'ÉCHELLE EXISTE QUAND MÊME, mais elle n'explique pas la panne : sur
    `carte_boss_courant_20261108.png` le nœud est à l'échelle 1.00, la
    même que sur la capture d'origine, et il était raté tout pareil. Elle
    se voit ailleurs — `carte_boss_courant_zoom_20261106.png`, où la
    carte a zoomé de 8 % : 0.50 à l'échelle 1.00, 0.83 à 1.08. D'où le
    balayage `BOSS_ECHELLES`, pour ce gabarit SEULEMENT.

    `assets/` N'EST PAS VERSIONNÉ : si le dossier est restauré, le masque
    disparaît et ce test repasse au rouge. Il se refait en une ligne, à
    partir d'une capture de `captures_reference/` :

        python -c "import adventure_navigation as an; an.decouper_final_boss()"
    """
    print("\nLe boss final est reconnu dans ses trois états")

    import cv2
    import numpy as np
    from pathlib import Path
    import adventure_navigation as an

    reference = Path(__file__).resolve().parent / "captures_reference"
    gabarit = an.TEMPLATES["final_boss"]

    def lire(nom):
        chemin = reference / nom
        if not chemin.exists():
            return None, (None, None)
        ecran = cv2.imread(str(chemin))
        return ecran, an.best_match(gabarit, screen=ecran)

    def pres(point, cible, tol=18):
        return point is not None and abs(point[0] - cible[0]) <= tol \
            and abs(point[1] - cible[1]) <= tol

    # 0. LE MASQUE EST LÀ, ET C'EST BIEN CELUI DE LA RECETTE. Sans alpha,
    #    tout le reste du test est une illusion : le gabarit serait
    #    comparé avec son halo et son fond, comme avant.
    brut = cv2.imread(gabarit, cv2.IMREAD_UNCHANGED)
    a_un_masque = (brut is not None and brut.ndim == 3 and brut.shape[2] == 4
                   and not (brut[:, :, 3] == 255).all())
    check("le gabarit du boss porte un masque (sinon : decouper_final_boss())",
          a_un_masque, None if brut is None else brut.shape)

    origine = reference / "carte_boss_joignable_20261108.png"
    if a_un_masque and origine.exists():
        x0, y0, x1, y1 = an.BOSS_BOITE
        boite = cv2.imread(str(origine))[y0:y1, x0:x1]
        refait = np.dstack([boite, an.masque_or(boite)])
        check("et il est exactement ce que la recette redécoupe",
              refait.shape == brut.shape and np.array_equal(refait, brut))

    # 1. LES TROIS ÉTATS DU MÊME NŒUD, sur la même aventure. Le deuxième
    #    est celui qui marchait déjà (0.87) : une régression là serait
    #    pire que le bogue.
    for nom, etat, cible in (
        ("carte_boss_bloque_20261108.png", "route bloquée, aucun halo", (1307, 241)),
        ("carte_boss_joignable_20261108.png", "joignable, halo bleu", (1307, 241)),
        ("carte_boss_courant_20261108.png", "voyage fait, notre portrait dessus", (960, 442)),
    ):
        ecran, (score, point) = lire(nom)
        if ecran is None:
            print(f"  (ignoré : {nom} absent)")
            continue
        check(f"{etat} : reconnu au-dessus du seuil",
              score is not None and score >= navigate.MATCH_THRESHOLD, score)
        check(f"{etat} : et c'est bien le médaillon, en {cible}",
              pres(point, cible), point)

    # 2. UNE AUTRE AVENTURE, UN AUTRE BOSS, UN AUTRE FOND. Le portrait du
    #    boss est hors masque : c'est ce qui rend le gabarit générique, et
    #    c'est la seule façon de le vérifier.
    ecran, (score, point) = lire("carte_boss_autre_aventure_20261106.png")
    if ecran is None:
        print("  (ignoré : carte_boss_autre_aventure_20261106.png absent)")
    else:
        check("autre aventure, autre boss : reconnu quand même",
              score is not None and score >= navigate.MATCH_THRESHOLD, score)
        check("   → en (1439, 256)", pres(point, (1439, 256)), point)

    # 3. LA CARTE ZOOME. Même état qu'au point 1 (portrait par-dessus),
    #    mais 8 % plus grand : à l'échelle 1.00 le gabarit n'y note que
    #    0.50. C'est le seul endroit du projet où le multi-échelle
    #    rattrape vraiment quelque chose.
    ecran, (score, point) = lire("carte_boss_courant_zoom_20261106.png")
    if ecran is None:
        print("  (ignoré : carte_boss_courant_zoom_20261106.png absent)")
    else:
        sans_balayage, _ = an._match(
            ecran, *(lambda b: (b[:, :, :3], cv2.merge([b[:, :, 3]] * 3)))(brut))
        check("carte zoomée : à une seule échelle, le nœud est raté",
              sans_balayage < navigate.MATCH_THRESHOLD, sans_balayage)
        check("carte zoomée : le balayage le retrouve",
              score is not None and score >= navigate.MATCH_THRESHOLD, score)
        check("   → en (959, 476)", pres(point, (959, 476)), point)

    # 4. ET RIEN NE PASSE LÀ OÙ IL N'Y A PAS DE BOSS. Un masque fait
    #    monter tous les scores : c'est le prix à surveiller. Sur les 851
    #    captures du projet, les 525 écrans de combat plafonnent à 0.53 et
    #    tout ce qui dépasse 0.80 est un vrai médaillon (11 positions,
    #    quatre boss) — ces trois-là sont les témoins du cas général.
    for nom in ("bilan_defaite_20261104.png", "champions_bas_20261105.png",
                "recompense_combat_20261106.png"):
        ecran, (score, _point) = lire(nom)
        if ecran is None:
            print(f"  (ignoré : {nom} absent)")
            continue
        check(f"pas de carte d'aventure ({nom}) : rien ne passe",
              score is not None and score < navigate.MATCH_THRESHOLD, score)


def test_a_visited_node_behind_us_is_not_clicked_three_times():
    """
    05/09/2026 22:45, capture `sans_voyage_20260905_224545.png` : après
    l'événement du champion de soutien, le nœud VISITÉ (coche verte, panneau
    « Foyer — Confrontation terminée ») était encore reconnu à 0.81, le
    marqueur du joueur lu à 0.78 — sous le seuil — et le repli « le plus à
    gauche » a cliqué ce nœud derrière nous trois fois de suite, sans
    « Voyage ». Trois parades, chacune suffisante :
      1. le marqueur juste sous le seuil est accepté s'il est près du centre ;
      2. sans marqueur, la position est le CENTRE de l'écran, pas None ;
      3. un nœud cliqué sans « Voyage » est écarté au tour suivant.
    """
    print("\nLe nœud déjà visité derrière nous n'est pas recliqué")

    import cv2
    from pathlib import Path

    import adventure_navigation as an
    capture = Path(__file__).resolve().parent / "screenshots" / "sans_voyage_20260905_224545.png"
    if not capture.exists():
        print("  (capture absente : test sauté)")
        return
    ecran = cv2.imread(str(capture))
    VISITE, SUIVANT = (717, 580), (1181, 433)

    def pres(point, cible, tol=25):
        return abs(point[0] - cible[0]) <= tol and abs(point[1] - cible[1]) <= tol

    noeuds = an.find_nodes_in_folder(navigate.NODES_DIR, screen=ecran)
    check("les deux nœuds sont candidats (le visité ressemble encore aux templates)",
          len(noeuds) == 2 and pres(noeuds[0][1], VISITE) and pres(noeuds[1][1], SUIVANT), noeuds)

    # 1. le marqueur, juste sous le seuil mais au centre, est accepté
    position = navigate._player_position(ecran)
    check("marqueur accepté sous le seuil (près du centre)",
          position is not None and pres(position, (960, 541)), position)
    choix = an.pick_next_node(noeuds, position)
    check("   → le nœud SUIVANT, à droite", choix and pres(choix[1], SUIVANT), choix)

    # 2. sans marqueur du tout : le centre de l'écran tient lieu de position
    check("le centre de la capture", navigate._screen_center(ecran) == (960, 540))
    choix = an.pick_next_node(noeuds, navigate._screen_center(ecran))
    check("   depuis le centre → le nœud SUIVANT aussi", choix and pres(choix[1], SUIVANT), choix)

    # 3. un nœud cliqué sans « Voyage » n'est plus candidat, même « à gauche »
    choix = an.pick_next_node(noeuds, None, exclude=(VISITE,))
    check("exclu → le nœud SUIVANT même sans position", choix and pres(choix[1], SUIVANT), choix)
    check("tout exclu → None", an.pick_next_node(noeuds, None, exclude=(VISITE, SUIVANT)) is None)

    # Et de bout en bout : locate_node sur cette capture rend le bon nœud.
    restore()
    an_capture = an._capture_screen_bgr
    an._capture_screen_bgr = lambda: ecran
    navigate._capture_screen_bgr = lambda: ecran
    try:
        point = navigate.locate_node(navigate.NODES_DIR, wait=1)
    finally:
        an._capture_screen_bgr = an_capture
        restore("_capture_screen_bgr")
    check("locate_node rend le nœud suivant, pas le visité", point is not None and pres(point, SUIVANT), point)

    # goto_node : sans « Voyage », le point cliqué est transmis à locate_node en exclusion.
    restore()
    vus = []
    navigate.locate_node = lambda cible, wait=None, exclude=(): vus.append(tuple(exclude)) or (
        VISITE if not exclude else SUIVANT)
    navigate.safe_click = lambda x, y, **k: True
    navigate.click_button = lambda name, **k: False if name == "voyage_button" and not vus[-1] else (900, 900)
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT
    navigate.save_screen = lambda *a, **k: None
    arrivee, point = navigate.goto_node(navigate.NODES_DIR, "nœud 1")
    check("goto_node écarte le nœud cliqué sans « Voyage » au tour suivant",
          len(vus) >= 2 and vus[0] == () and VISITE in vus[1] and point == SUIVANT
          and arrivee == navigate.ARRIVAL_COMBAT, (vus, arrivee, point))
    restore()


def test_the_map_order_is_followed():
    print("\nL'ordre de la carte est suivi, dans ses deux formes")

    restore()

    def jouer(avec_boss_intermediaire):
        cibles = scripter_carte(*[(100 + 10 * i, 200) for i in range(5)])
        navigate.has_mid_boss = lambda wait=None: avec_boss_intermediaire
        # Tout nœud propose un combat : on veut l'ORDRE, pas le contenu.
        navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT
        lor_battle.try_combat = lambda x, y, **k: FakeCombat(True)
        return navigate.run_adventure(), cibles

    # SANS boss intermédiaire : champion, nœud, nœud, boss final.
    bilan, cibles = jouer(False)
    check("quatre nœuds", bilan["nodes"] == 4, bilan)
    check("dans l'ordre attendu",
          cibles == ["support_champion", navigate.NODES_DIR, navigate.NODES_DIR,
                     "final_boss"], cibles)
    check("fin normale", bilan["reason"] == navigate.CLEAN_END, bilan["reason"])

    # AVEC boss intermédiaire : il s'insère après le premier nœud, et le
    # deuxième nœud vient après lui.
    bilan, cibles = jouer(True)
    check("cinq nœuds", bilan["nodes"] == 5, bilan)
    check("le boss intermédiaire s'insère au bon endroit",
          cibles == ["support_champion", navigate.NODES_DIR,
                     "secondary_enemy_node", navigate.NODES_DIR, "final_boss"],
          cibles)
    check("deux combats joués", len(bilan["combats"]) == 2, bilan["combats"])


def test_une_aventure_en_cours_est_reprise_la_ou_elle_en_est():
    """
    Le 05/11/2026, deux tentatives mensuelles ont été perdues ainsi : la
    carte était OUVERTE et jouable, mais `run_adventure` repartait
    toujours du champion de soutien — déjà franchi — et abandonnait. Dans
    un cas le combat suivant était gagnable.
    """
    print("\nUne aventure déjà commencée est reprise là où elle en est")

    restore()
    navigate.has_mid_boss = lambda wait=None: False
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT
    lor_battle.try_combat = lambda x, y, **k: FakeCombat(True)

    def carte(restants):
        """Ce qui est ENCORE sur la carte ; le reste a été franchi avant nous."""
        scripter_carte()                       # pose les bouchons communs
        file = {cle: list(points) for cle, points in restants.items()}
        cibles = []

        def locate(cible, wait=None, exclude=()):
            cibles.append(cible)
            reste = file.get(cible)
            return reste.pop(0) if reste else None

        navigate.locate_node = locate
        return cibles

    # Le champion de soutien a déjà été fait ; le reste de la carte est là.
    reste = {navigate.NODES_DIR: [(20, 20), (30, 30)], "final_boss": [(40, 40)]}
    cibles = carte(reste)
    bilan = navigate.run_adventure(reprise=True)
    check("l'aventure va jusqu'au bout", bilan["reason"] == navigate.CLEAN_END,
          bilan["reason"])
    check("   trois nœuds franchis, pas quatre", bilan["nodes"] == 3, bilan["nodes"])
    check("   le champion de soutien a quand même été CHERCHÉ",
          cibles[0] == "support_champion", cibles)
    check("   et le boss final a été combattu", len(bilan["combats"]) == 1,
          bilan["combats"])

    # La MÊME carte sans reprise : on s'arrête, et on dit pourquoi.
    carte(reste)
    bilan = navigate.run_adventure()
    check("sans reprise, la même carte arrête le parcours",
          bilan["reason"] == "champion de soutien introuvable", bilan["reason"])

    # LE DROIT DE SAUTER S'ÉTEINT À LA PREMIÈRE ÉTAPE RETROUVÉE : sinon le
    # bot traverserait la carte en cliquant à côté.
    carte({"support_champion": [(10, 10)], "final_boss": [(40, 40)]})
    bilan = navigate.run_adventure(reprise=True)
    check("après une étape retrouvée, un nœud manquant redevient une panne",
          bilan["reason"] == "premier nœud introuvable", bilan["reason"])


def test_a_missing_node_stops_the_run_and_says_which():
    print("\nUn nœud manquant arrête le parcours, et on sait lequel")

    restore()
    navigate.has_mid_boss = lambda wait=None: False
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_CLOSED
    lor_battle.try_combat = lambda x, y, **k: FakeCombat(True)

    # Le champion de soutien n'est pas trouvé : c'est la toute première
    # étape, et le motif doit le dire — pas « aventure interrompue ».
    scripter_carte()
    bilan = navigate.run_adventure()
    check("le motif nomme l'étape",
          bilan["reason"] == "champion de soutien introuvable", bilan["reason"])
    check("aucun nœud franchi", bilan["nodes"] == 0, bilan["nodes"])

    # Le boss final manque : trois nœuds faits, et surtout AUCUN combat.
    scripter_carte((10, 10), (20, 20), (30, 30))
    bilan = navigate.run_adventure()
    check("le boss final est nommé", bilan["reason"] == "boss final introuvable",
          bilan["reason"])
    check("et rien n'a été combattu", bilan["combats"] == [], bilan["combats"])


def test_reaching_the_next_node_settles_the_previous_combat():
    """
    Journal du 05/09/2026 : 53 combats, aucun verdict. En défi l'API ne
    dit rien ; c'est l'aventure qui juge — rejoindre le nœud suivant prouve
    que le combat du boss intermédiaire était gagné. Le boss final, lui,
    n'a pas de nœud suivant : son verdict reste à qui l'a lu.
    """
    print("\nRejoindre le nœud suivant conclut le combat précédent")

    restore()
    scripter_carte(*[(100, 200)] * 5)
    navigate.has_mid_boss = lambda wait=None: True
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT
    rapports = []

    def combat_sans_verdict(x, y, **k):
        rapport = FakeCombat(None, reason="retour aux menus")
        rapports.append(rapport)
        return rapport

    lor_battle.try_combat = combat_sans_verdict
    conclus = []
    saved = journal.conclude
    journal.conclude = lambda report, path=None: conclus.append(report) or True
    try:
        bilan = navigate.run_adventure()
    finally:
        journal.conclude = saved

    check("fin normale", bilan["reason"] == navigate.CLEAN_END, bilan["reason"])
    check("deux combats", len(rapports) == 2, len(rapports))
    check("le boss intermédiaire est jugé gagné",
          rapports[0].won is True and rapports[0].verdict == "aventure poursuivie",
          vars(rapports[0]))
    check("et reporté au journal", conclus == [rapports[0]], len(conclus))
    check("le boss final n'est pas jugé par l'aventure (c'est try_combat, ici bouchonné)",
          rapports[1].won is None, vars(rapports[1]))


def test_a_lost_combat_stops_the_run():
    print("\nUn combat perdu arrête le parcours")

    restore()
    scripter_carte(*[(100, 200)] * 5)
    navigate.has_mid_boss = lambda wait=None: True
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT
    lor_battle.try_combat = lambda x, y, **k: FakeCombat(False)

    bilan = navigate.run_adventure()
    check("l'arrêt est nommé", bilan["reason"].startswith("combat perdu"),
          bilan["reason"])
    check("et l'endroit aussi", "intermédiaire" in bilan["reason"], bilan["reason"])
    check("un seul combat joué", len(bilan["combats"]) == 1, bilan["combats"])


def test_only_the_final_boss_makes_a_victory():
    print("\nSeul le boss final peut faire une victoire")

    # Une aventure qui s'arrête avant le boss final n'est ni gagnée ni
    # perdue : inachevée. Sans cette règle, un boss intermédiaire gagné
    # puis une navigation perdue passeraient pour une victoire.
    install(entries=[Entry.LAUNCHED, Entry.NO_ATTEMPT_LEFT],
            runs=[parcours(reason="boss final introuvable",
                           combats=[FakeCombat(True)], nodes=4)])
    report = ChallengeSession().run()
    check("aucune victoire", report.wins == 0, report.wins)
    check("tentative inachevée", report.attempts[0].won is None,
          report.attempts[0].won)
    check("et le motif vient de la navigation",
          report.attempts[0].reason == "boss final introuvable",
          report.attempts[0].reason)


def test_combat_options_reach_the_fight():
    print("\nLes options de jeu descendent jusqu'au combat")

    restore()
    vus = {}
    scripter_carte(*[(100, 200)] * 5)
    navigate.has_mid_boss = lambda wait=None: False
    navigate.resolve_arrival = lambda timeout=None, settle=None: navigate.ARRIVAL_COMBAT

    finals = []

    def fake_fight(x, y, final_boss=False, **options):
        vus.update(options)
        finals.append(final_boss)
        return FakeCombat(True)

    lor_battle.try_combat = fake_fight
    navigate.run_adventure(combat_options={"allow_spells": True})
    check("l'option arrive à try_combat", vus == {"allow_spells": True}, vus)
    check("seul le dernier combat est marqué boss final",
          finals and finals[-1] is True and not any(finals[:-1]), finals)


def test_post_combat_sequence():
    """
    SORTIE D'UN COMBAT (02/09/2026, à la demande d'Ewan) : attendre, un
    clic pour fermer le résultat, « Continuer ». Après le BOSS FINAL :
    « Continuer » une seconde fois, attendre, recliquer AU MÊME ENDROIT.
    Plus aucune image 'after_combat' n'est cherchée.
    """
    print("\nSortie de combat : clic, Continuer, et la fin d'aventure")

    import lor_battle as lb
    saved = (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
             lb.POST_COMBAT_DELAY, lb.FINAL_BOSS_EXTRA_DELAY, lb.park_mouse)
    gestes, dodos = [], []
    lb.park_mouse = lambda: gestes.append(("souris garée", None))
    lb.click_button = lambda name, timeout=10, **k: gestes.append(("bouton", name)) or (900, 800)
    lb.human_click = lambda x, y: gestes.append(("clic", (x, y)))
    lb.pyautogui.size = lambda: (1920, 1080)
    lb.time.sleep = lambda s: dodos.append(s)
    lb.POST_COMBAT_DELAY, lb.FINAL_BOSS_EXTRA_DELAY = 5.0, 5.0
    try:
        ok = lb._handle_post_combat()
        check("combat ordinaire : réussi", ok is True)
        check("   on attend 5 s avant le premier clic", dodos[:1] == [5.0], dodos)
        check("   un clic au centre, puis Continuer",
              gestes == [("clic", (960, 540)), ("bouton", "continue_button_after_combat")], gestes)
        check("   aucune image after_combat cherchée",
              all(g != ("bouton", "after_combat") for g in gestes), gestes)

        # Le boss final ne change plus rien ICI : son second « Continuer »
        # et le reclic de sortie sont l'affaire de try_combat, qui guette
        # en même temps « Relevez-vous » (cf. test_final_boss_exits).
        gestes.clear(); dodos.clear()
        ok = lb._handle_post_combat()
        check("un seul Continuer, quel que soit le nœud",
              ok is True and gestes.count(("bouton", "continue_button_after_combat")) == 1
              and ("clic", (900, 800)) not in gestes, gestes)

        # Le second habillage du bouton est essayé si le premier manque.
        gestes.clear()
        lb.click_button = (lambda name, timeout=10, **k: gestes.append(("bouton", name))
                           or (name == "continue_button" and (700, 900)))
        ok = lb._handle_post_combat()
        check("repli sur continue_button", ok is True and ("bouton", "continue_button") in gestes, gestes)

        # Aucun des deux habillages : la souris est garée, puis on refait
        # UN tour — et on le trouve cette fois (il était sous le curseur).
        gestes.clear()
        tours = []
        def cache_puis_visible(name, timeout=10, **k):
            tours.append(name)
            return (750, 950) if ("souris garée", None) in gestes else False
        lb.click_button = cache_puis_visible
        ok = lb._handle_post_combat()
        check("bouton caché sous la souris : trouvé après l'avoir garée",
              ok is True and gestes.count(("souris garée", None)) == 1, gestes)
        check("   les deux habillages ont été cherchés avant de garer",
              tours[:2] == list(lb.CONTINUE_BUTTONS), tours)
    finally:
        (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
         lb.POST_COMBAT_DELAY, lb.FINAL_BOSS_EXTRA_DELAY, lb.park_mouse) = saved


def test_retry_reclicks_the_opponent_at_screen_center():
    """
    Après « Réessayer », le jeu rend la carte recentrée sur nous : il faut
    recliquer l'adversaire, et il est AU CENTRE DE L'ÉCRAN (Ewan,
    03/09/2026). Pas au point d'avant le Voyage, et pas un repère cherché
    autour — ça cliquait le coffre voisin.
    """
    print("\nRéessai : l'adversaire est recliqué au centre de l'écran")

    import lor_battle as lb
    saved = (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
             lb.play_combat, lb._handle_post_combat)
    gestes = []
    retries = {"restants": 1}

    def faux_click_button(name, timeout=10, **k):
        gestes.append(("bouton", name))
        if name == "retry":
            if retries["restants"] == 0:
                return False
            retries["restants"] -= 1
            return (960, 700)
        if name in lb.CONTINUE_BUTTONS:
            return False          # pas d'écran de fin : la carte est rendue
        return (960, 800)

    lb.click_button = faux_click_button
    lb.human_click = lambda x, y: gestes.append(("clic", (x, y)))
    lb.pyautogui.size = lambda: (1920, 1080)
    lb.time.sleep = lambda s: None
    lb.play_combat = lambda **o: gestes.append(("combat", None)) or FakeCombat(False)
    lb._handle_post_combat = lambda **k: True
    try:
        lb.try_combat(1263, 610)
        check("le centre est cliqué, pas le point d'avant le Voyage",
              ("clic", (960, 540)) in gestes and ("clic", (1263, 610)) not in gestes, gestes)
        i_retry = gestes.index(("bouton", "retry"))
        i_clic = gestes.index(("clic", (960, 540)))
        i_combat = gestes.index(("bouton", "combat_button"))
        check("   ordre : Réessayer, clic au centre, Combat, puis le combat",
              i_retry < i_clic < i_combat < gestes.index(("combat", None), i_combat), gestes)
        check("   un seul clic sur la carte par réessai",
              sum(1 for g in gestes if g[0] == "clic") == 1, gestes)
    finally:
        (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
         lb.play_combat, lb._handle_post_combat) = saved


def test_une_recompense_apres_le_second_continuer_est_une_victoire():
    """
    06/11/2026, 16:05 — LE BOT A DÉCLARÉ PERDU UN COMBAT QU'IL AVAIT
    GAGNÉ, et la session entière s'est arrêtée là-dessus.

        16:05:09  Second « Continuer » : écran de fin, le combat était perdu
        16:05:24  Journal : DÉFAITE reporté
        16:05:24  tentative 7 : DÉFAITE — combat perdu (boss intermédiaire)
        16:05:27  à l'écran : « RÉCOMPENSES DE COMBAT », +19 PV

    Trois secondes après le verdict, l'écran affichait la récompense de
    boss intermédiaire — « Choisissez un objet à équiper sur l'un de vos
    champions ». ON NE REÇOIT PAS ÇA EN PERDANT.

    La règle du 05/09 (« second Continuer sans Relevez-vous = défaite »)
    reste vraie : elle vient d'observations en jeu. On lui ajoute une
    EXCEPTION PROUVÉE — l'écran de récompense l'emporte, parce qu'il ne
    s'affiche qu'après une victoire.

    Et la conséquence en cascade, c'est elle qui a tué la session : le
    verdict de défaite faisait arrêter le parcours, donc `play_reward`
    n'était jamais appelé, donc le panneau restait à l'écran, et
    `back_to_known_screen` n'a rien qui morde dessus (« Continuer » 0.32,
    « Quitter » 0.39). 120 s, puis arrêt.
    """
    print("\nUne récompense après le second « Continuer » est une VICTOIRE")

    import lor_battle as lb
    import navigate
    saved = (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
             lb.play_combat, lb.park_mouse, navigate.play_reward)
    gestes = []
    recompense = {"vue": None}

    def faux_click_button(name, timeout=10, **k):
        gestes.append(("bouton", name))
        if name in lb.CONTINUE_BUTTONS and gestes.count(("bouton", "continue_button_after_combat")) <= 2:
            return (960, 900)
        if name == "combat_button":
            return (960, 800)
        return False

    lb.click_button = faux_click_button
    lb.human_click = lambda x, y: gestes.append(("clic", (x, y)))
    lb.pyautogui.size = lambda: (1920, 1080)
    lb.time.sleep = lambda s: None
    lb.park_mouse = lambda: None
    lb.play_combat = lambda **o: FakeCombat(None, reason="retour aux menus")
    navigate.play_reward = lambda etiquette, **k: (
        gestes.append(("récompense", etiquette)) or recompense["vue"])
    try:
        # a) LA RÉCOMPENSE EST LÀ : c'est une victoire, et on la prend.
        recompense["vue"] = {"closed": True, "picked": ["objet"]}
        rendu = lb.try_combat(1199, 330, final_boss=False)
        check("la récompense fait le verdict : VICTOIRE", rendu.won is True, rendu.won)
        check("   la récompense a bien été jouée",
              any(g[0] == "récompense" for g in gestes), gestes)

        # b) PAS DE RÉCOMPENSE : la règle du 05/09 s'applique, défaite.
        gestes.clear()
        recompense["vue"] = None
        rendu = lb.try_combat(1199, 330, final_boss=False)
        check("sans récompense : la défaite reste la défaite",
              rendu.won is False, rendu.won)
        check("   et on a quand même regardé avant de conclure",
              any(g[0] == "récompense" for g in gestes), gestes)
    finally:
        (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
         lb.play_combat, lb.park_mouse, navigate.play_reward) = saved


def test_a_lost_combat_closes_the_adventure_end():
    """
    UN COMBAT PERDU FINIT L'AVENTURE : LE JEU MONTRE UN SECOND « CONTINUER ».

    Ewan, 04/09/2026 : premier combat perdu, verdict API absent, le bot a
    cherché « Réessayer » (il n'y en a pas dans le défi) puis « nœud 2 » sur
    l'écran de fin. Le second « Continuer » EST le verdict : on ferme la fin
    comme après le boss final, on marque la défaite, on ne cherche ni
    réessai ni nœud.
    """
    print("\nDéfaite : le second « Continuer » ferme la fin d'aventure")

    import lor_battle as lb
    saved = (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
             lb.play_combat, lb.park_mouse)
    gestes = []
    continues = {"restants": 2}   # celui d'après-combat, puis celui de fin

    def faux_click_button(name, timeout=10, **k):
        gestes.append(("bouton", name))
        if name in lb.CONTINUE_BUTTONS and continues["restants"] > 0:
            continues["restants"] -= 1
            return (960, 900)
        return False

    lb.click_button = faux_click_button
    lb.human_click = lambda x, y: gestes.append(("clic", (x, y)))
    lb.pyautogui.size = lambda: (1920, 1080)
    lb.time.sleep = lambda s: None
    lb.park_mouse = lambda: None
    rapport = FakeCombat(None, reason="retour aux menus")
    lb.play_combat = lambda **o: gestes.append(("combat", None)) or rapport
    try:
        rendu = lb.try_combat(1263, 610)
        check("la défaite est marquée sur le rapport", rendu.won is False, rendu.won)
        check("   « Relevez-vous » est cherché, en vain, AVANT de conclure",
              gestes.index(("bouton", "retry")) < gestes.index(("clic", (960, 900))), gestes)
        check("   deux « Continuer », puis le reclic de fin au même point",
              sum(1 for g in gestes if g == ("clic", (960, 900))) == 1
              and continues["restants"] == 0, gestes)

        # Victoire lue par l'API : jamais requalifiée, même si un bouton
        # « Continuer » traîne à l'écran.
        gestes.clear()
        continues["restants"] = 2
        rapport = FakeCombat(True)
        rendu = lb.try_combat(1263, 610)
        check("victoire API : elle reste une victoire", rendu.won is True, rendu.won)
        check("   et l'écran de fin n'est pas cherché : un seul « Continuer »",
              continues["restants"] == 1, continues)

        # Rien de plus après le premier « Continuer » : carte rendue, on
        # cherche « Réessayer » comme avant.
        gestes.clear()
        continues["restants"] = 1
        rapport = FakeCombat(None)
        rendu = lb.try_combat(1263, 610)
        check("carte rendue : pas de défaite inventée", rendu.won is None, rendu.won)
        check("   et « Réessayer » est cherché", ("bouton", "retry") in gestes, gestes)
    finally:
        (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
         lb.play_combat, lb.park_mouse) = saved


def test_a_second_chance_is_taken_after_the_defeat_screens():
    """
    « VOUS ÊTES MORT — on vous a offert une nouvelle chance. RELEVEZ-VOUS »
    (Ewan, 05/09/2026). Le bot avait cliqué les deux « Continuer », conclu
    à la défaite et s'était perdu sur cet écran. Il faut : cliquer
    « Relevez-vous » (template `retry`), recliquer l'adversaire au centre,
    puis « Combat » — et ne marquer la défaite QUE si « Relevez-vous »
    manque.
    """
    print("\nNouvelle chance : « Relevez-vous » après les deux « Continuer »")

    import lor_battle as lb
    saved = (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
             lb.play_combat, lb.park_mouse)
    gestes = []
    ecran = {"continues": 2, "retries": 1}

    def faux_click_button(name, timeout=10, **k):
        gestes.append(("bouton", name))
        if name in lb.CONTINUE_BUTTONS and ecran["continues"] > 0:
            ecran["continues"] -= 1
            return (960, 900)
        if name == "retry" and ecran["retries"] > 0:
            ecran["retries"] -= 1
            return (960, 912)
        if name == "combat_button":
            return (960, 800)
        return False

    rapports = [FakeCombat(None, reason="retour aux menus"), FakeCombat(True)]

    def faux_combat(**o):
        gestes.append(("combat", None))
        return rapports.pop(0)

    lb.click_button = faux_click_button
    lb.human_click = lambda x, y: gestes.append(("clic", (x, y)))
    lb.pyautogui.size = lambda: (1920, 1080)
    lb.time.sleep = lambda s: None
    lb.park_mouse = lambda: None
    lb.play_combat = faux_combat
    try:
        rendu = lb.try_combat(1263, 610)
        check("le second combat est joué et son verdict rendu",
              rendu.won is True and gestes.count(("combat", None)) == 2, gestes)
        check("   la défaite n'a pas été déclarée : pas de reclic de fin",
              ("clic", (960, 900)) not in gestes, gestes)
        i_retry = gestes.index(("bouton", "retry"))
        # Le premier clic au centre ferme l'écran de résultat ; celui qui
        # nous intéresse est APRÈS « Relevez-vous ».
        i_centre = gestes.index(("clic", (960, 540)), i_retry)
        i_combat = gestes.index(("bouton", "combat_button"))
        check("   ordre : Relevez-vous, clic au centre, Combat, puis le combat",
              i_retry < i_centre < i_combat < gestes.index(("combat", None), i_combat), gestes)
        check("   les deux « Continuer » sont cliqués avant « Relevez-vous »",
              ecran["continues"] == 0, gestes)
    finally:
        (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
         lb.play_combat, lb.park_mouse) = saved


def test_final_boss_exits():
    """
    BOSS FINAL, 05/09/2026 20h30 : combat perdu, UN « Continuer », pas de
    second, puis « VOUS ÊTES MORT … RELEVEZ-VOUS ». Le bot exigeait le
    second « Continuer » (sortie du boss final), a rendu la main sur
    « aventure terminée » et s'est perdu deux minutes sur cet écran.

    Après le premier « Continuer », on guette DONC les deux : second
    « Continuer » ET « Relevez-vous ». Trois sorties du boss final :
      - « Relevez-vous » direct : défaite marquée, on rejoue ;
      - second « Continuer » puis « Relevez-vous » : idem ;
      - second « Continuer » seul : sortie normale, reclic au même point.
    """
    print("\nBoss final : « Relevez-vous » sans second « Continuer », et la sortie normale")

    import lor_battle as lb
    saved = (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
             lb.play_combat, lb.park_mouse, lb._lire_le_bilan)
    gestes = []
    # Ce que le jeu affiche APRÈS CHAQUE COMBAT : combien de « Continuer »
    # se présentent, puis « Relevez-vous » ou non. Un écran par combat joué.
    ecran = {"suites": []}

    def suite_courante():
        return ecran["suites"][gestes.count(("combat", None)) - 1]

    def dernier_clic():
        # Le juge de fin de tentative passe APRÈS le clic de sortie sans
        # rien cliquer : c'est le dernier CLIC qui dit la sortie, pas le
        # dernier geste.
        return [g for g in gestes if g[0] == "clic"][-1]

    def faux_click_button(name, timeout=10, **k):
        gestes.append(("bouton", name))
        suite = suite_courante()
        if name in lb.CONTINUE_BUTTONS and suite["continues"] > 0:
            suite["continues"] -= 1
            return (960, 900)
        if name == "retry" and suite["continues"] == 0 and suite["retry"]:
            suite["retry"] = False
            return (960, 912)
        if name == "combat_button":
            return (960, 800)
        return False

    rapports = []

    def faux_combat(**o):
        gestes.append(("combat", None))
        return rapports.pop(0)

    lb.click_button = faux_click_button
    lb.human_click = lambda x, y: gestes.append(("clic", (x, y)))
    lb.pyautogui.size = lambda: (1920, 1080)
    lb.time.sleep = lambda s: None
    lb.park_mouse = lambda: gestes.append(("souris garée", None))
    lb.play_combat = faux_combat

    # Le juge de fin de tentative (bilan.py) est remplacé À LA COUTURE DE
    # L'ÉCRAN : ici on teste la CHORÉGRAPHIE des boutons, pas la lecture
    # d'image — et une suite HORS LIGNE ne doit jamais capturer l'écran.
    # `verdict_du_juge` dit ce que le juge parvient à lire ; None = écran
    # illisible. Le geste porte l'ATTENTE demandée, ce qui distingue le
    # coup d'œil (0 s) du guet complet (None = le temps plein).
    verdict_du_juge = {"valeur": None}
    VerdictFactice = collections.namedtuple("VerdictFactice",
                                            "gagne verdict raison pv")

    def faux_bilan(attente=None):
        gestes.append(("juge", attente))
        if verdict_du_juge["valeur"] is None:
            return None
        gagne = verdict_du_juge["valeur"]
        return VerdictFactice(gagne, "écran de victoire" if gagne else "bilan de fin (0 PV)",
                              "victoire (écran de fin de défi)" if gagne
                              else "défaite (bilan : nexus à 0)", None)

    lb._lire_le_bilan = faux_bilan
    try:
        # a) un seul Continuer, puis Relevez-vous, puis victoire au second combat
        perdu = FakeCombat(None, reason="retour aux menus")
        rapports[:] = [perdu, FakeCombat(True)]
        ecran["suites"] = [{"continues": 1, "retry": True}, {"continues": 2, "retry": False}]
        rendu = lb.try_combat(1199, 330, final_boss=True)
        check("boss final perdu sans second Continuer : la nouvelle chance est prise",
              gestes.count(("combat", None)) == 2 and rendu.won is True, gestes)
        check("   le combat perdu est marqué comme tel", perdu.won is False, perdu.won)
        i_combat2 = gestes.index(("combat", None), 1)
        check("   « Relevez-vous » cherché sans attendre 40 s de Continuer",
              ("souris garée", None) not in gestes[:i_combat2], gestes[:i_combat2])
        check("   puis la sortie normale du boss final : reclic au même point",
              dernier_clic() == ("clic", (960, 900)), gestes[-3:])

        # b) victoire au boss final : second Continuer, pas de Relevez-vous,
        #    puis le reclic de sortie AU MÊME POINT.
        gestes.clear()
        ecran["suites"] = [{"continues": 2, "retry": False}]
        rapports[:] = [FakeCombat(None, reason="retour aux menus")]
        rendu = lb.try_combat(1199, 330, final_boss=True)
        check("boss final gagné : deux Continuer puis reclic au même point",
              ecran["suites"][0]["continues"] == 0
              and dernier_clic() == ("clic", (960, 900)), gestes)
        check("   « Relevez-vous » a été guetté après le second Continuer",
              gestes.index(("bouton", "retry"), gestes.index(("clic", (960, 540))))
              < gestes.index(("clic", (960, 900))), gestes)
        check("   juge muet : verdict inconnu, pas de défaite inventée",
              rendu.won is None, rendu.won)
        check("   un seul combat joué", gestes.count(("combat", None)) == 1, gestes)
        # L'écran de DÉFAITE précède le clic de sortie, l'écran de VICTOIRE
        # le suit (mesuré en jeu le 05/11/2026) : il faut regarder deux fois.
        sortie = gestes.index(("clic", (960, 900)))
        check("   le juge regarde avant ET après le clic de sortie",
              ("juge", None) in gestes[:sortie] and ("juge", None) in gestes[sortie:],
              gestes)

        # LA CHORÉGRAPHIE D'AVANT, AU GESTE PRÈS, quand le juge est muet.
        # C'est le verrou de la règle : verdict None = comportement
        # d'avant, sans discuter. Le coup d'œil au bilan n'est PAS un
        # geste — il ne clique ni ne bouge rien — donc les clics et les
        # recherches de bouton doivent être exactement ceux du 09/11.
        attendu = [("combat", None), ("clic", (960, 540)),
                   ("bouton", "continue_button_after_combat"),
                   ("bouton", "continue_button_after_combat"),
                   ("bouton", "retry"),
                   ("clic", (960, 900))]
        check("   juge muet : la chorégraphie est celle d'avant, au geste près",
              [g for g in gestes if g[0] != "juge"] == attendu,
              [g for g in gestes if g[0] != "juge"])

        # b bis) même enchaînement, mais l'écran est lisible : le verdict
        #        doit remonter jusqu'au rapport du combat.
        gestes.clear()
        ecran["suites"] = [{"continues": 2, "retry": False}]
        rapports[:] = [FakeCombat(None, reason="retour aux menus")]
        verdict_du_juge["valeur"] = True
        rendu = lb.try_combat(1199, 330, final_boss=True)
        verdict_du_juge["valeur"] = None
        check("   écran lisible : la victoire du boss final est enfin enregistrée",
              rendu.won is True and rendu.finished is True, (rendu.won, rendu.finished))

        # ON NE GUETTE PAS « RELEVEZ-VOUS » APRÈS UNE VICTOIRE LUE
        # (10/11/2026). Mesuré en jeu le 09/11, boss final GAGNÉ :
        #
        #     19:40:11,844  Second « Continuer » : fin d'aventure
        #     19:40:11,844  Recherche du bouton : retry
        #     19:40:20,872  Bouton 'retry' introuvable        <- 9,0 s
        #     19:40:22,403  victoire (bilan : 50 PV restants)
        #
        # Le bilan au cœur portait déjà la victoire pendant ces neuf
        # secondes — il a été lu une seconde et demie après, sans que
        # l'écran ait changé. Le jeu n'offre pas de nouvelle chance à qui
        # vient de gagner : un coup d'œil AVANT le guet suffit à s'en
        # passer. Seule une victoire POSITIVEMENT lue y autorise.
        check("   victoire lue : « Relevez-vous » n'est plus guetté du tout",
              ("bouton", "retry") not in gestes, gestes)
        check("   et le coup d'œil précède le second « Continuer » fermé",
              gestes.index(("juge", lb.COUP_D_OEIL_BILAN))
              < gestes.index(("clic", (960, 900))), gestes)
        check("   la sortie du boss final reste la même : reclic au même point",
              dernier_clic() == ("clic", (960, 900)), gestes)
        # ET LE VERDICT RENDU NE SE RELIT PAS. `settle_verdict` refuse de
        # requalifier : regarder l'écran une seconde fois ne pouvait rien
        # changer, et c'était une capture de plus à chaque boss final.
        check("   un verdict déjà rendu ne fait pas relire l'écran",
              len([g for g in gestes if g[0] == "juge"]) == 1, gestes)

        # UNE DÉFAITE LUE N'AUTORISE RIEN : « Relevez-vous » est
        # justement ce qu'on offre à qui vient de perdre. Si le coup
        # d'œil servait de laissez-passer pour n'importe quel verdict, le
        # bot renoncerait à la nouvelle chance — c'est la panne du
        # 05/09/2026, 2 × 120 s et une tentative hebdomadaire.
        gestes.clear()
        ecran["suites"] = [{"continues": 2, "retry": True}, {"continues": 1, "retry": False}]
        rapports[:] = [FakeCombat(None, reason="retour aux menus"),
                       FakeCombat(None, reason="retour aux menus")]
        verdict_du_juge["valeur"] = False
        rendu = lb.try_combat(1199, 330, final_boss=True)
        verdict_du_juge["valeur"] = None
        check("   défaite lue : « Relevez-vous » est guetté quand même",
              ("bouton", "retry") in gestes, gestes)
        check("   et la nouvelle chance est prise",
              gestes.count(("combat", None)) == 2, gestes)

        # c) rien après le premier Continuer : on rend la main après
        #    AFTER_COMBAT_ROUNDS tours, sans tourner indéfiniment.
        gestes.clear()
        ecran["suites"] = [{"continues": 1, "retry": False}]
        rapports[:] = [FakeCombat(None, reason="retour aux menus")]
        rendu = lb.try_combat(1199, 330, final_boss=True)
        check("rien après le Continuer : fin propre après les tours de guet",
              gestes.count(("souris garée", None)) == lb.AFTER_COMBAT_ROUNDS
              and gestes.count(("combat", None)) == 1, gestes)
        # LE BOSS FINAL EST JUGÉ MÊME QUAND RIEN NE SE PRÉSENTE.
        #
        # 06/11/2026, première victoire sur le défi 13 : le bot a gagné et
        # le journal a enregistré `gagne: null`. Le juge n'était appelé que
        # si un SECOND « Continuer » avait été vu — ici il n'y en avait
        # pas, on tombait sur « Aucun « Relevez-vous » détecté » et
        # personne ne regardait l'écran. Or l'écran « DÉFI 13 / VICTOIRE »
        # s'est affiché TROIS SECONDES plus tard, et `bilan.juger` le lit
        # à 0.99. C'est précisément le défaut que bilan.py existe pour
        # éviter : le combat le plus important de l'aventure fini en
        # `gagne: null`.
        check("   et le boss final est jugé quand même (l'écran peut tarder)",
              ("juge", None) in gestes, gestes)

        gestes.clear()
        ecran["suites"] = [{"continues": 1, "retry": False}]
        rapports[:] = [FakeCombat(None, reason="retour aux menus")]
        verdict_du_juge["valeur"] = True
        rendu = lb.try_combat(1199, 330, final_boss=True)
        verdict_du_juge["valeur"] = None
        check("   écran de victoire tardif : la victoire est enregistrée",
              rendu.won is True, rendu.won)

        # UN COMBAT ORDINAIRE, LUI, N'EST PAS JUGÉ PAR LE BILAN : il a ses
        # propres juges (« Relevez-vous », le nœud suivant rejoint). Ne pas
        # lui coller l'écran de fin de TENTATIVE.
        gestes.clear()
        ecran["suites"] = [{"continues": 1, "retry": False}]
        rapports[:] = [FakeCombat(None, reason="retour aux menus")]
        lb.try_combat(1199, 330, final_boss=False)
        check("   un combat ordinaire ne convoque pas le juge de fin",
              ("juge", None) not in gestes, gestes)
    finally:
        (lb.click_button, lb.human_click, lb.pyautogui.size, lb.time.sleep,
         lb.play_combat, lb.park_mouse, lb._lire_le_bilan) = saved


def main():
    print("=" * 60)
    print("Tests de la boucle de session (challenges.py)")
    print("=" * 60)

    for test in (
        test_un_masque_tout_blanc_nest_pas_passe_a_matchtemplate,
        test_le_mode_plan_ne_plante_sur_aucun_ecran_reconnu,
        test_le_jeu_est_mis_devant_avant_de_regarder_lecran,
        test_repeats_until_the_game_refuses,
        test_a_defeat_does_not_stop_the_session,
        test_a_silent_api_stops_the_session_before_burning_attempts,
        test_an_interrupted_combat_stops_the_session_cleanly,
        test_a_lost_navigation_is_named_and_recovered,
        test_a_lost_combat_is_a_defeat_wherever_it_happens,
        test_burning_attempts_for_nothing_stops_the_session,
        test_unknown_screens_do_not_spin_forever,
        test_recovered_screen_resets_the_counter,
        test_une_entree_manquee_ne_brule_pas_la_session,
        test_attempt_cap_is_respected,
        test_session_duration_is_a_hard_stop,
        test_keyboard_interrupt_still_reports,
        test_plan_mode_touches_nothing,
        test_combat_options_reach_the_combat,
        test_post_combat_sequence,
        test_retry_reclicks_the_opponent_at_screen_center,
        test_final_boss_exits,
        test_a_lost_combat_closes_the_adventure_end,
        test_une_recompense_apres_le_second_continuer_est_une_victoire,
        test_a_second_chance_is_taken_after_the_defeat_screens,
        test_the_champion_is_selected_before_launching,
        test_le_repli_ne_sentete_pas_hors_de_la_grille,
        test_le_diagnostic_juge_tous_ses_reperes_sur_une_seule_capture,
        test_un_log_nannonce_pas_un_repli_qui_na_pas_lieu,
        test_an_open_adventure_is_resumed_not_relaunched,
        test_une_aventure_en_cours_se_reprend_depuis_les_menus,
        test_an_unresumable_adventure_says_so,
        test_no_attempt_left_is_only_the_launch_button,
        test_recovery_only_closes_screens,
        test_une_recompense_de_combat_nest_pas_un_ecran_a_fermer,
        test_un_coffre_reste_ouvert_nest_pas_une_recompense,
        test_arrival_is_decided_by_what_the_game_offers,
        test_the_arrival_panel_is_waited_for,
        test_the_support_champion_panel_is_given_time_to_fill,
        test_goto_node_needs_the_voyage_button,
        test_a_node_that_arrives_late_is_waited_for,
        test_the_leftmost_node_is_chosen_not_the_first_template,
        test_le_marqueur_du_joueur_tient_sur_dautres_cartes,
        test_le_boss_final_se_reconnait_dans_ses_trois_etats,
        test_a_visited_node_behind_us_is_not_clicked_three_times,
        test_the_map_order_is_followed,
        test_une_aventure_en_cours_est_reprise_la_ou_elle_en_est,
        test_a_missing_node_stops_the_run_and_says_which,
        test_reaching_the_next_node_settles_the_previous_combat,
        test_a_lost_combat_stops_the_run,
        test_only_the_final_boss_makes_a_victory,
        test_combat_options_reach_the_fight,
    ):
        test()

    # LE FILET DU BOUCHON POSÉ À L'IMPORT. Hors du harnais du boss final,
    # qui pose le sien, PERSONNE ne doit aller lire le bilan à l'écran :
    # une lecture ici voudrait dire qu'un test photographie vraiment
    # l'écran d'Ewan. C'est la façon la moins chère de s'en apercevoir —
    # les cinq fuites précédentes ont toutes été trouvées par hasard.
    check("aucun test n'est allé lire le bilan à l'écran",
          LECTURES_DU_BILAN == [], LECTURES_DU_BILAN)

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
