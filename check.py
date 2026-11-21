#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py

Une seule commande pour savoir si tout va bien.

    python check.py              # tout
    python check.py --offline    # sans le jeu : juste les suites de tests
    python check.py --live       # seulement le diagnostic sur la partie en cours
    python check.py --skip-ocr   # évite de charger easyocr (gain de ~10 s)

Deux natures de vérification, et il faut les distinguer :

HORS LIGNE — les suites de tests. Elles n'ont besoin ni du jeu, ni de la
souris, ni d'easyocr : tout est simulé. Un échec ici signale une
régression dans la logique, indépendamment de ton installation.
Chacune tourne derrière le GARDE-MACHINE (`garde_machine.py`), qui
vérifie qu'elle n'a touché ni la souris, ni la molette, ni l'écran, ni la
fenêtre du jeu — quatre suites l'ont fait sans que personne le voie. Le
verdict d'ensemble distingue TROIS états — surveillée et propre /
TOUCHÉE / sans verdict — parce qu'une suite tuée, absente ou sortie
muette ne prouve rien, et qu'il l'annonçait pourtant « propre ».

EN LIGNE — le diagnostic contre la partie réellement ouverte. Un échec
ici est un problème de branchement ou de calibration : jeu fermé, base de
cartes absente, template du jeton manquant, zones décalées.

Chaque contrôle qui échoue affiche QUOI FAIRE, pas seulement qu'il a
échoué. Le code de sortie vaut 1 si au moins un contrôle bloquant a raté,
pour pouvoir enchaîner dans un script.
"""

from __future__ import annotations

import argparse
import io
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# Les emballages que `_sortie_en_utf8` a mis de côté. Les garder
# référencés ici empêche le ramasse-miettes de fermer le tampon sous nos
# pieds ; cf. le commentaire du repli, plus bas.
_FLUX_REMPLACES: list = []


def _sortie_en_utf8() -> None:
    """
    Écrire en UTF-8 quoi qu'il arrive — TUBE OU PAS.

    La console Windows écrit en UTF-8 depuis Python 3.6, mais dès que la
    sortie part dans un FICHIER ou dans un TUBE (`check.py > rapport.txt`,
    `check.py | tail`), Python retombe sur l'encodage local — cp1252 sur
    ce PC. `_run_suite` imposait déjà `PYTHONIOENCODING=utf-8` aux SUITES
    (05/11/2026) ; check.py LUI-MÊME ne l'avait jamais fait, et mourait
    sur sa propre dernière ligne décorée — le « ── garde-machine : … »
    de `run_offline`, qu'aucun des 16 verdicts verts ne pouvait sauver.

    Deux dégâts, pas un : la commande sortait en ERREUR (code 1) toutes
    suites vertes, et tout ce qui avait été écrit avant l'était en
    cp1252 — le « é » de « nécessaire » posé sur UN octet 0xE9 au lieu
    des deux de l'UTF-8, donc illisible pour le premier outil qui ouvre
    le rapport.

    `line_buffering` NE RÉPARE PAS UN TROISIÈME DÉGÂT — on a d'abord cru
    que le traceback sortait AVANT les suites dans un
    `check.py > rapport.txt 2>&1` (stdout bufferisé par blocs, stderr
    non). C'EST FAUX, et c'est mesuré : 3 000 lignes de stdout (90 Ko,
    dix fois le tampon) puis une exception non rattrapée, le traceback
    arrive en ligne 3 001 sur 3 005. CPython vide sys.stdout avant
    d'imprimer un traceback. Ne pas réécrire cette justification-là sans
    la remesurer.

    Ce que `line_buffering` achète vraiment : chaque ligne part écrite,
    donc rien ne traîne dans un tampon. C'est ce qui rend le repli
    ci-dessous sûr — il laisse DEUX emballages sur un même tampon, et
    celui qui le ferme le premier à la fin de l'interpréteur ne peut plus
    tronquer une queue qui n'existe pas. Vérifié : 500 lignes écrites par
    le repli, 501 relues, dernière intacte.

    Aucun de ces réglages n'a le droit d'échouer bruyamment : si le flux
    n'est pas un `TextIOWrapper` (banc d'essai, flux remplacé), on le
    laisse tel quel plutôt que de faire tomber la seule commande à
    retenir du projet.
    """
    for nom in ("stdout", "stderr"):
        flux = getattr(sys, nom, None)
        if flux is None:
            continue
        try:
            flux.reconfigure(encoding="utf-8", errors="replace",
                             line_buffering=True)
            continue
        except (AttributeError, ValueError, OSError):
            pass
        # Repli : on réemballe le tampon binaire. `sys.stderr` est relu à
        # chaque fois par l'interpréteur, donc le traceback final passe
        # lui aussi par le nouvel emballage.
        tampon = getattr(flux, "buffer", None)
        if tampon is None:
            continue
        # ON GARDE L'ANCIEN FLUX EN VIE, ET CE N'EST PAS DE LA PRUDENCE
        # DÉCORATIVE. Dès qu'on remplace `sys.stdout`, plus personne ne
        # référence l'ancien emballage : il est collecté, et le `__del__`
        # d'un `TextIOWrapper` FERME le tampon qu'on vient justement de
        # réemballer. Le nouvel emballage écrit alors dans un fichier
        # fermé — « ValueError: I/O operation on closed file. », levée
        # non pas ici mais au premier `print`, donc à mille lieues de sa
        # cause. Mesuré le 08/11/2026 sur les deux formes qui amènent ici :
        # un flux qui POSSÈDE son `TextIOWrapper` (capture pytest,
        # colorama) et un vrai `TextIOWrapper` dont `reconfigure` lève —
        # c'est-à-dire exactement le `ValueError` que le `except`
        # ci-dessus nomme. Sans cette liste, le repli censé éviter la
        # chute la GARANTIT, en silence.
        try:
            neuf = io.TextIOWrapper(
                tampon, encoding="utf-8", errors="replace",
                line_buffering=True)
        except (AttributeError, ValueError, OSError):
            continue
        _FLUX_REMPLACES.append(flux)
        setattr(sys, nom, neuf)


# AVANT TOUT LE RESTE : un import qui parle, un avertissement, un
# traceback d'import doivent déjà sortir en UTF-8.
_sortie_en_utf8()

# LE GARDE QUI DIT SI UNE SUITE A TOUCHÉ LA MACHINE. Chaque suite est
# lancée DERRIÈRE lui : il compte les gestes de pyautogui (souris,
# molette, captures) et les fonctions de fenêtre de `gestures`, puis
# rend un verdict dans le tube. Voir `garde_machine.py` pour le détail et
# pour les QUATRE fois où une suite hors ligne a piloté la vraie machine
# d'Ewan sans que personne le voie — c'est la raison d'être du mécanisme.
import garde_machine

TEST_SUITES = (
    "test_game_state.py",
    "test_keywords.py",
    "test_spells.py",
    "test_actions.py",
    "test_combat.py",
    "test_challenges.py",
    "test_replay.py",
    "test_strategy.py",
    # CES TROIS-LÀ EXISTAIENT SANS JAMAIS TOURNER (constaté le
    # 04/11/2026) : écrites, vertes, et absentes de cette liste — donc
    # muettes le jour où une régression les aurait cassées.
    "test_events.py",
    "test_digits.py",
    "test_riposte.py",
    "test_bilan.py",
    # LE JOURNAL EST CE QUI TRANCHE LES RÉGLAGES : taux de victoire par
    # configuration, et par (palier, étoiles) — c'est lui qui doit
    # corriger la table d'allocation des champions, pas l'intuition. Une
    # ligne mal écrite ou mal relue fausse tout ce qu'on décide ensuite,
    # en silence et pour des semaines.
    "test_journal.py",
    "test_champions.py",
    # L'ÉTOURDISSEMENT EST LU À L'ÉCRAN, DONC SUR DES CAPTURES RÉELLES
    # (14/11/2026) : l'API n'en dit rien, et les deux pistes naïves — la
    # teinte violette, le délavage — font un faux positif sur un champion
    # sain dès la première image. La suite garde ces contre-épreuves.
    "test_stun.py",
    # LES ICÔNES DE MOTS-CLÉS SE LISENT, MÊME SI ON NE SAIT PAS ENCORE
    # LES NOMMER (14/11/2026) : Legion Saboteur a `keywords=[]` dans
    # card_sets et porte pourtant une icône à l'écran — la preuve qu'un
    # mot-clé ACCORDÉ en jeu est visible là où l'API est muette.
    "test_mots_cles_ecran.py",
    "test_monitor_web.py",
    "test_lor_api.py",
    # OÙ NOUS SOMMES SUR LA CARTE (08/11/2026) : le losange de
    # `player_marker` est un décor de tracé, notre vraie position est le
    # médaillon au portrait du champion joué. Cf. `marqueur_joueur.py`.
    "test_marqueur.py",
    # CE FICHIER-CI SE VÉRIFIE LUI-MÊME (09/11/2026) : le verdict
    # d'ensemble du garde-machine, et le fait que toute suite `test_*.py`
    # du dossier soit bien dans cette liste. Une suite non inscrite est
    # MUETTE — et celle qui vérifie l'inscription, non inscrite, serait
    # l'ironie complète.
    "test_check.py",
)

# Au-delà, une suite est déclarée bloquée et tuée. Aucune ne dépasse
# quelques secondes depuis que le temps est simulé (cf. test_clock.py) ;
# cette borne existe pour qu'un blocage soit NOMMÉ plutôt que subi.
SUITE_TIMEOUT = 120.0

OK, WARN, FAIL = "OK  ", "ATTN", "ÉCHEC"


class Results:
    """Compte les verdicts et retient les consignes à afficher à la fin."""

    def __init__(self):
        self.failures = 0
        self.warnings = 0
        self.hints = []

    def report(self, status, label, detail="", hint=""):
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
        if status == FAIL:
            self.failures += 1
            if hint:
                self.hints.append(f"{label} : {hint}")
        elif status == WARN:
            self.warnings += 1
            if hint:
                self.hints.append(f"{label} : {hint}")


# ============================================================
# HORS LIGNE
# ============================================================

def _pump(stream, sink: "queue.Queue") -> None:
    """Vide le tube de la suite dans une file, puis signale la fin."""
    try:
        for line in stream:
            sink.put(line)
    finally:
        sink.put(None)


_last_draw = 0.0


def _progress(suite: str, passed: int, elapsed: float) -> None:
    """
    Réécrit la ligne d'avancement, au plus cinq fois par seconde.

    Muet dès que la sortie n'est pas un terminal : redirigée vers un
    fichier ou collée dans une conversation, une ligne rafraîchie au `\\r`
    devient des centaines de lignes illisibles.
    """
    global _last_draw
    if not sys.stdout.isatty():
        return
    now = time.time()
    if now - _last_draw < 0.2:
        return
    _last_draw = now
    line = f"  [ .. ] {suite} — {passed} assertions, {elapsed:.0f} s"
    print(f"\r{line:<70}", end="", flush=True)


def _run_suite(path: Path, timeout: float = SUITE_TIMEOUT):
    """
    Lance une suite en montrant sa progression, et rend
    `(returncode, lignes, elapsed, bloquée)`.

    La sortie est lue au fil de l'eau, dans un fil dédié : une suite qui
    n'écrit plus rien ne fige pas `check.py`, et l'échéance est vérifiée
    même quand aucune ligne n'arrive. `subprocess.run(capture_output=True)`
    ne permettait ni l'un ni l'autre — l'écran restait muet pendant toute
    la durée de la suite, ce qui rendait une simple lenteur indiscernable
    d'un blocage.
    """
    started = time.time()
    # La sortie est lue dans un TUBE : sans cette consigne, l'enfant
    # choisit l'encodage local (cp1252 sur ce PC) et meurt sur la
    # première flèche qu'il imprime (UnicodeEncodeError), alors que ses
    # assertions passent. Une vraie console n'a pas ce défaut (elle écrit
    # en UTF-8 depuis Python 3.6) : d'où une suite VERTE lancée à la main
    # et ROUGE ici — constaté le 05/11/2026 sur test_actions,
    # test_challenges et test_strategy. On impose donc l'UTF-8 des deux
    # côtés du tube, celui de la lecture étant juste en dessous.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # LA SUITE PASSE PAR LE GARDE-MACHINE : il pose ses mouchards, puis
    # lance le fichier comme si on l'avait lancé seul (même `__main__`,
    # même `sys.argv`, même `__file__`). Il n'empêche rien : il compte, et
    # il le dit dans le tube.
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "garde_machine.py"), str(path)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    sink: "queue.Queue" = queue.Queue()
    threading.Thread(target=_pump, args=(proc.stdout, sink), daemon=True).start()

    lines, passed, stalled = [], 0, False
    while True:
        try:
            line = sink.get(timeout=0.4)
        except queue.Empty:
            line = ""
        if line is None:
            break
        if line:
            text = line.rstrip("\n")
            lines.append(text)
            if text.startswith("  ok "):
                passed += 1
        elapsed = time.time() - started
        if elapsed > timeout:
            stalled = True
            proc.kill()
            break
        _progress(path.name, passed, elapsed)

    proc.wait()
    if sys.stdout.isatty():
        print("\r" + " " * 70 + "\r", end="")
    return proc.returncode, lines, time.time() - started, stalled


def _verdict_garde(lines) -> tuple:
    """
    Ce que le garde-machine a vu dans cette suite, lu dans le tube.

    Rend `(état, détail, pile)` où `état` vaut :

        "propre"  — aucun geste ; c'est le seul état acceptable ;
        "touché"  — la suite a bougé la souris, la molette, l'écran ou la
                    fenêtre du jeu, et `pile` nomme le coupable ;
        "muet"    — pas de verdict du tout : la suite a été tuée, ou le
                    garde ne s'est pas installé. Ne JAMAIS lire ça comme
                    « rien touché » — c'est « on ne sait pas ».
    """
    etat, detail = "muet", ""
    pile = []
    for line in lines:
        if not line.startswith(garde_machine.PREFIXE):
            continue
        reste = line[len(garde_machine.PREFIXE):].strip()
        if reste == garde_machine.PROPRE:
            etat = "propre"
        elif reste.startswith(garde_machine.SALE):
            etat, detail = "touché", reste
        else:
            pile.append(reste)

    # UN CRI SANS VERDICT RESTE UN GESTE (09/11/2026). Le garde crie au
    # PREMIER geste et ne récapitule qu'à la sortie : une suite tuée en
    # plein geste laisse donc le cri dans le tube SANS la ligne finale.
    # C'était classé « on ne sait pas » alors qu'on sait très bien — et
    # ce n'est pas un cas d'école : une fuite qui photographie l'écran
    # RALENTIT la suite (le 06/11/2026, `_reward_proves_victory` l'a fait
    # passer de 5 s à 15 s), donc c'est précisément une fuite qui peut
    # déclencher l'échéance et emporter son propre verdict.
    if etat == "muet" and pile:
        etat = "touché"
        detail = (f"{garde_machine.SALE} — geste vu en cours de route, "
                  f"verdict final emporté avec la suite")
    return etat, detail, pile


def run_offline(results: Results) -> None:
    print("\n=== Tests hors ligne (le jeu n'est pas nécessaire) ===\n")

    # TROIS ÉTATS, PAS DEUX (09/11/2026). Une suite n'est « propre » que
    # si son verdict a été LU dans le tube. Tout le reste — fichier
    # absent, suite tuée, sortie sans verdict — est un « on ne sait pas »
    # qui ne doit jamais se faire passer pour une preuve. Cf. le verdict
    # d'ensemble, en bas de cette fonction.
    propres, sales, sans_verdict = [], [], []

    for suite in TEST_SUITES:
        path = ROOT / suite
        if not path.exists():
            results.report(FAIL, suite, "fichier absent")
            # ELLE N'A ÉTÉ SURVEILLÉE PAR PERSONNE, et elle sortait d'ici
            # par un `continue` sec : ni propre, ni sale, ni muette. Le
            # compte final, tiré de `len(TEST_SUITES)`, la rangeait donc
            # avec les propres.
            sans_verdict.append((suite, "fichier absent — rien n'a été surveillé"))
            continue

        returncode, lines, elapsed, stalled = _run_suite(path)
        passed = sum(1 for line in lines if line.startswith("  ok "))
        etat, geste, pile = _verdict_garde(lines)
        machine = {"propre": "machine intacte",
                   "touché": "MACHINE TOUCHÉE",
                   "muet": "GARDE MUET"}[etat]

        if stalled:
            results.report(
                FAIL, suite,
                f"bloquée après {elapsed:.0f} s ({passed} assertions) — {machine}",
                hint=f"relance `python {suite}` pour voir où elle s'arrête",
            )
            for line in lines[-3:]:
                print(f"          {line}")
        elif returncode == 0:
            results.report(OK, suite, f"{passed} assertions en {elapsed:.1f} s — {machine}")
        else:
            failed = [line.strip() for line in lines if line.startswith("  ÉCHEC")]
            results.report(
                FAIL, suite, f"{len(failed) or 'des'} échec(s) — {machine}",
                hint=f"relance `python {suite}` pour le détail",
            )
            for line in (failed[:5] or lines[-3:]):
                print(f"          {line}")

        # LE VERDICT DE LA MACHINE EST SÉPARÉ DE CELUI DE LA SUITE, et il
        # est BLOQUANT. Une suite peut être verte et avoir quand même
        # piloté la souris d'Ewan : c'est exactement ce qui s'est produit
        # quatre fois (park_mouse, choisir_champion, _reward_proves_victory,
        # revenir_en_haut), et deux fois le vert était vert PAR ACCIDENT.
        if etat == "touché":
            sales.append((suite, geste))
            results.report(
                FAIL, f"{suite} · garde-machine", geste,
                hint="bouchonne l'appel dès l'import de la suite (cf. "
                     "`navigate.champions.choisir_champion` dans test_challenges) ; "
                     f"`GARDE_MACHINE=bloquer python garde_machine.py {suite}` "
                     "donne la pile complète",
            )
            for ligne in pile:
                print(f"          {ligne}")
        elif etat == "propre":
            propres.append(suite)
        elif stalled:
            sans_verdict.append(
                (suite, f"tuée après {elapsed:.0f} s — le garde est mort avec elle"))
        else:
            sans_verdict.append(
                (suite, f"sortie (code {returncode}) sans dire un mot"))

    # --- le verdict d'ensemble, impossible à rater --------------------
    #
    # IL COMPTE CE QU'IL A LU, PAS CE QU'IL A DÉCLARÉ (09/11/2026).
    # La phrase verte annonçait `len(TEST_SUITES)` suites « dont aucune
    # n'a touché la souris » — en comptant celles dont le fichier
    # manquait et celles que l'échéance avait tuées, qui ne rendent
    # AUCUN verdict. Mesuré en fabriquant le cas : une suite tuée
    # pendant que le garde criait « PREMIER GESTE SUR LA MACHINE :
    # pyautogui.click() » ressortait sous « 1 suites, aucune n'a
    # touché ». C'est le défaut que le projet poursuit depuis une
    # semaine — une ABSENCE lue comme une PREUVE — logé cette fois dans
    # l'outil même qui existe pour le détecter.
    #
    # D'où : le chiffre de la phrase verte vient de `propres`, jamais de
    # `TEST_SUITES`, et elle ne s'imprime que si les deux autres listes
    # sont vides.
    total = len(TEST_SUITES)
    print()
    if sales:
        print(f"  ######  GARDE-MACHINE : {len(sales)} suite(s) sur {total} ONT TOUCHÉ "
              f"LA SOURIS, L'ÉCRAN OU LA FENÊTRE  ######")
        for suite, geste in sales:
            print(f"  ######    {suite} — {geste}")

    if sans_verdict:
        # BLOQUANT, et pas un simple avertissement. Pour une suite tuée
        # ou absente ça ne change rien (elle a déjà son [ÉCHEC]) ; ça
        # compte pour le SEUL cas où l'absence de verdict est le seul
        # symptôme — code de retour 0, assertions vertes, et pas une
        # ligne du garde (mouchards non posés, `os._exit`, tube coupé).
        # Ce cas-là passait en vert, et le garde aurait pu être mort
        # depuis des semaines sans que rien ne le dise.
        results.report(
            FAIL, "garde-machine",
            f"{len(sans_verdict)} suite(s) NON SURVEILLÉE(S) : "
            + " ; ".join(f"{suite} ({raison})" for suite, raison in sans_verdict),
            hint="sans verdict, on ne sait pas si elle a touché la machine — ce "
                 "n'est pas « rien touché ». Relance-la à la main : "
                 "`python garde_machine.py <suite>` doit finir par "
                 f"« {garde_machine.PREFIXE} {garde_machine.PROPRE} »",
        )

    if sales or sans_verdict:
        print(f"  ──  garde-machine : {len(propres)} suite(s) surveillée(s) et "
              f"propre(s), {len(sales)} TOUCHÉE(S), {len(sans_verdict)} sans "
              f"verdict — sur {total}.")
    else:
        print(f"  ──  garde-machine : {len(propres)} suite(s) surveillée(s), aucune "
              f"n'a touché la souris, la molette, l'écran ni la fenêtre du jeu.")


# ============================================================
# EN LIGNE
# ============================================================

def run_live(results: Results, skip_ocr: bool = False) -> None:
    print("\n=== Diagnostic sur la partie en cours ===\n")

    # --- dépendances ---------------------------------------------------
    for module, why in (
        ("cv2", "vision"), ("numpy", "vision"), ("requests", "API"),
        ("pyautogui", "souris"),
    ):
        try:
            __import__(module)
            results.report(OK, f"module {module}")
        except Exception as exc:
            results.report(
                FAIL, f"module {module}", str(exc),
                hint=f"pip install {module} — nécessaire pour {why}",
            )
            return

    import lor_api

    # --- API du client ---------------------------------------------------
    try:
        data = lor_api.get_positional_rectangles()
        state = data.get("GameState", "?")
        count = len(data.get("Rectangles") or [])
        results.report(OK, "API du client", f"GameState={state}, {count} rectangles")
        in_game = state == "InProgress"
    except lor_api.ApiUnavailable as exc:
        results.report(
            FAIL, "API du client", str(exc),
            hint="lance Legends of Runeterra et entre dans une partie",
        )
        return

    # --- base de cartes ---------------------------------------------------
    card_db = lor_api.load_card_db()
    if len(card_db) > 1000:
        results.report(OK, "base de cartes", f"{len(card_db)} cartes")
    else:
        results.report(
            FAIL, "base de cartes", f"{len(card_db)} cartes",
            hint="lance LoR-Bot/code/download_card_sets.py",
        )

    # --- fenêtre ----------------------------------------------------------
    window = lor_api.get_window(data)
    detected = lor_api.find_game_window()
    if detected:
        results.report(OK, "fenêtre du jeu", f"{window.width}x{window.height} en ({window.x}, {window.y})")
    else:
        results.report(
            WARN, "fenêtre du jeu", f"repli sur {window.width}x{window.height}",
            hint="pywin32 absent ou jeu non détecté ; correct en plein écran, "
                 "faux en mode fenêtré",
        )

    # --- couverture des sorts --------------------------------------------
    import spells
    report = spells.coverage_report()
    total = report["collectible"]
    if total:
        refused = sum(v for (_, t), v in report["counts"].items() if t == "REFUSED")
        ratio = 100 * (total - refused) / total
        results.report(OK, "classement des sorts", f"{ratio:.0f} % jouables sur {total}")
    else:
        results.report(WARN, "classement des sorts", "aucun sort lu")

    # --- template du jeton -------------------------------------------------
    import game_state
    if game_state.load_template(game_state.ATTACK_TOKEN_TEMPLATE) is None:
        results.report(
            WARN, "template du jeton", "absent",
            hint="`python game_state.py snap avec` puis `cut-token` ; "
                 "sans lui la phase reste OUR_TURN au lieu de trancher ATTACK/DEFEND",
        )

    # --- inventaire des templates de navigation ------------------------------
    # navigate.py échoue en silence sur un template manquant : la fonction
    # se contente d'un log et renvoie None, et l'aventure s'arrête là. Mieux
    # vaut le savoir avant de lancer une session de farm.
    try:
        from adventure_navigation import TEMPLATES
        missing = sorted(
            name for name, path in TEMPLATES.items()
            if not (lor_api.PROJECT_ROOT / path).exists()
        )
        if missing:
            results.report(
                WARN, "templates de navigation", f"absents : {', '.join(missing)}",
                hint="l'aventure s'arrêtera à cette étape ; capture les images "
                     "manquantes dans assets/",
            )
        else:
            results.report(OK, "templates de navigation", f"{len(TEMPLATES)} présents")
    except Exception as exc:
        results.report(WARN, "templates de navigation", str(exc))

    # --- images des nœuds ordinaires ----------------------------------------
    # Le dossier est scanné image par image (find_first_match_in_folder) :
    # s'il est vide, aucun nœud ordinaire n'est jamais reconnu et le
    # parcours s'arrête au premier, sans autre symptôme qu'un « nœud
    # introuvable ».
    import navigate
    nodes = Path(navigate.NODES_DIR)
    images = sorted(nodes.glob("*.png")) if nodes.is_dir() else []
    if images:
        results.report(OK, "images des nœuds", f"{len(images)} dans {nodes.name}/")
    else:
        results.report(
            WARN, "images des nœuds", f"aucune image dans {nodes}",
            hint="le parcours s'arrêtera au premier nœud ordinaire ; capture "
                 "les variantes dans assets/nodes/",
        )

    # --- état de la partie --------------------------------------------------
    reader = game_state.GameStateReader(card_db=card_db)
    snapshot = reader.snapshot()
    results.report(OK, "phase détectée", snapshot.phase.name)

    if not in_game:
        results.report(
            WARN, "hors partie",
            "les contrôles de plateau sont ignorés",
            hint="relance ce diagnostic pendant un combat pour tout vérifier",
        )
        return

    if snapshot.token_match and not snapshot.token_match.template_missing:
        match = snapshot.token_match
        results.report(
            OK, "jeton d'attaque",
            f"score {match.score:.2f} (seuil {game_state.ATTACK_TOKEN_MATCH_THRESHOLD}), côté {match.side}",
        )

    populated = [name for name in game_state.ZONE_ORDER if snapshot.zones.get(name)]
    if populated:
        results.report(OK, "zones peuplées", ", ".join(populated))
    else:
        results.report(
            WARN, "zones peuplées", "aucune",
            hint="normal hors combat ; sinon vérifie ZONE_BANDS avec "
                 "`python game_state.py inspect`",
        )

    if snapshot.unknown_codes:
        results.report(
            WARN, "cartes hors base", ", ".join(snapshot.unknown_codes),
            hint="jetons non collectionnables, ou card_sets à mettre à jour",
        )

    if snapshot.enemy_nexus:
        results.report(OK, "nexus adverse", f"cliquable en {snapshot.enemy_nexus}")
    else:
        results.report(
            WARN, "nexus adverse", "introuvable",
            hint="les sorts visant « anything » n'auront pas de repli",
        )

    # --- OCR ----------------------------------------------------------------
    if skip_ocr:
        print("  [    ] lecture OCR ignorée (--skip-ocr)")
        return

    print("  [....] chargement d'easyocr, quelques secondes...")
    import mana
    pool = mana.read_mana_pool(window=window)
    health = mana.read_nexus_health(snapshot, local=True)

    if pool.readable:
        results.report(OK, "mana", str(pool))
    else:
        results.report(
            FAIL, "mana", "illisible",
            hint="`python mana.py --crops` puis ajuste MANA_BOX ; "
                 "sans mana, aucune carte ne sera posée",
        )

    entries, maximum = game_state.badge_cache_info()
    results.report(OK, "cache des badges", f"{entries}/{maximum} entrées")

    if health is not None:
        results.report(OK, "PV du nexus allié", str(health))
    else:
        results.report(
            WARN, "PV du nexus allié", "illisible",
            hint="`python mana.py --crops` ; sans PV, aucun blocage "
                 "sacrificiel même en situation létale",
        )

    enemy_health = mana.read_nexus_health(snapshot, local=False)
    if enemy_health is not None:
        results.report(OK, "PV du nexus adverse", str(enemy_health))
    else:
        results.report(
            WARN, "PV du nexus adverse", "non calibré",
            hint="`python mana.py --calibrate-nexus` ; sans eux le bot "
                 "évalue bien les échanges mais ne finit pas une partie gagnable",
        )


# ============================================================
# MAIN
# ============================================================

# ============================================================
# FEUILLE DE ROUTE
# ============================================================

def calibration_state() -> list:
    """
    Ce qui est déjà calibré et ce qui manque, dans l'ordre où il faut s'en
    occuper. Lisible SANS le jeu : tout est sur le disque.
    """
    import json
    try:
        with open(ROOT / "calibration.json", encoding="utf8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        saved = {}

    cards = ROOT / "LoR-Bot" / "card_sets"
    card_count = len(list(cards.glob("*.json"))) if cards.is_dir() else 0

    return [
        (
            card_count >= 5,
            "base de cartes",
            "python LoR-Bot/code/download_card_sets.py",
            "indispensable : sans elle le bot ne connaît aucune carte",
        ),
        (
            (ROOT / "assets" / "attack_token.png").exists(),
            "template du jeton d'attaque",
            "python game_state.py snap avec   puis   python game_state.py cut-token",
            "pendant que tu tiens le jeton ; sans lui, pas d'attaque déclarée",
        ),
        (
            "zone_nexus_reference" in saved,
            "ancrage des zones",
            "python game_state.py calibrate-zones",
            "pendant un combat ; facultatif en 1920x1080, requis ailleurs",
        ),
        (
            bool((saved.get("nexus_health_relative") or {}).get("enemy")),
            "PV des deux nexus",
            "python mana.py --calibrate-nexus",
            "pendant un combat ; sans eux le bot ne finit pas une partie gagnable",
        ),
        (
            "cost_badge" in saved,
            "gemme de mana",
            "python actions.py cost --calibrate",
            "sans elle le bot décide sur les coûts IMPRIMÉS : il ignore les "
            "réductions et tente des poses qu'il ne peut pas payer",
        ),
        (
            "cancel_point" in saved,
            "zone d'annulation",
            "python actions.py cancel --calibrate",
            "une zone VIDE du plateau : un clic gauche y sera émis pour annuler",
        ),
        (
            "mulligan_confirm" in saved,
            "bouton du mulligan",
            "python actions.py mulligan --calibrate",
            "pendant un écran de mulligan ; sinon tu fais le mulligan à la main",
        ),
    ]


def print_roadmap() -> None:
    print("\n=== Calibrations ===\n")
    todo = []
    for done, label, command, why in calibration_state():
        print(f"  [{'fait' if done else ' à faire '}] {label}")
        if not done:
            todo.append((label, command, why))

    if todo:
        print("\nÀ faire, dans cet ordre :\n")
        for label, command, why in todo:
            print(f"  {label}")
            print(f"      {command}")
            print(f"      ({why})\n")

    print("=== Lancer ===\n")
    print("  Sans jamais toucher la souris, pour vérifier :")
    print("      python game_state.py monitor    # la phase suit-elle le jeu ?")
    print("      python actions.py plan          # que jouerait-il ce tour ?")
    print("      python combat.py --plan         # une itération de la boucle")
    print("      python challenges.py --plan     # quel écran le bot reconnaît")
    print("\n  Puis, en prenant la souris :")
    print("      python combat.py               # un combat en autonomie")
    print("      python challenges.py --tentatives 1  # une seule aventure")
    print("      python challenges.py           # toutes les tentatives, d'affilée")
    print("\n  Et pour savoir si un réglage aide :")
    print("      python journal.py              # taux de victoire par configuration")
    print("\n  Arrêt d'urgence : souris dans un coin de l'écran.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Vérification complète du bot LoR.")
    parser.add_argument("--offline", action="store_true", help="seulement les tests")
    parser.add_argument("--live", action="store_true", help="seulement le diagnostic en jeu")
    parser.add_argument("--skip-ocr", action="store_true", help="ne pas charger easyocr")
    args = parser.parse_args()

    do_offline = args.offline or not args.live
    do_live = args.live or not args.offline

    results = Results()
    if do_offline:
        run_offline(results)
    if do_live:
        try:
            run_live(results, skip_ocr=args.skip_ocr)
        except Exception as exc:
            results.report(FAIL, "diagnostic en ligne", f"{type(exc).__name__}: {exc}")

    print("\n" + "=" * 60)
    if results.hints:
        print("À corriger :\n")
        for hint in results.hints:
            print(f"  - {hint}")
        print()

    if results.failures:
        print(f"{results.failures} problème(s) bloquant(s), {results.warnings} avertissement(s).")
        print_roadmap()
        return 1

    if results.warnings:
        print(f"Aucun problème bloquant, {results.warnings} avertissement(s).")
    else:
        print("Tout est vert.")

    print_roadmap()
    return 0


if __name__ == "__main__":
    sys.exit(main())
