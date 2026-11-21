#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lor_battle.py

Pont entre la navigation dans l'aventure (navigate.py) et le combat.

Ce module lançait auparavant l'ancien bot vendorisé
(LoR-Bot/code/LOR_Bot.py) dans un sous-processus. Il appelle désormais
notre propre boucle, `combat.CombatLoop`.

Ce que le changement apporte :
    - un seul bot à maintenir, et non deux dont un opaque ;
    - le résultat du combat est exploitable (victoire, tours joués,
      raison de l'arrêt) au lieu d'un simple code de sortie ;
    - plus de dépendance à pywin32/keyboard ni au constants.py de
      201 Ko de l'ancien projet.

Seul `LoR-Bot/card_sets/` reste nécessaire : c'est la base de cartes
utilisée par lor_api. `LoR-Bot/code/download_card_sets.py` sert à la
mettre à jour quand un nouveau set sort.
"""

import logging
import random
import time

import pyautogui

import journal
from click_utils import click_button, human_click, park_mouse


# Après le dernier tour, le jeu affiche le résultat (victoire / défaite)
# et attend UN CLIC quelconque pour passer à l'écran des récompenses.
# On n'y cherche plus d'image (l'ancien repère 'after_combat' a été
# retiré le 02/09/2026, à la demande d'Ewan) : on laisse l'animation se
# jouer, puis on clique au centre. Puis « Continuer ». La suite (second
# « Continuer » de fin d'aventure, « Relevez-vous ») est guettée par
# try_combat ; la fin d'aventure se ferme par un dernier clic au même
# endroit une fois l'écran suivant chargé.
POST_COMBAT_DELAY = 5.0
FINAL_BOSS_EXTRA_DELAY = 5.0
# Les deux repères connus du bouton, dans l'ordre où on les essaie.
CONTINUE_BUTTONS = ("continue_button_after_combat", "continue_button")

# Après « Réessayer », le jeu rend la CARTE et il faut recliquer l'adversaire
# avant que « Combat » ne soit proposé. La carte est alors RECENTRÉE SUR
# NOUS, donc sur lui : il est AU CENTRE DE L'ÉCRAN (capture d'Ewan du
# 03/09/2026 : notre portrait en (957, 540) sur 1920x1080). Le point où le
# nœud était quand on l'a cliqué la première fois ne vaut plus rien, et
# chercher un repère autour risque de cliquer le nœud voisin (le coffre,
# vu en jeu). Un clic au centre, comme pour fermer l'écran de résultat.
RETRY_MAP_DELAY = 3.0

# Après le premier « Continuer », on guette EN MÊME TEMPS un second
# « Continuer » et « Relevez-vous » (template `retry`), pendant
# AFTER_COMBAT_ROUNDS tours de ~4 s (un `click_button(timeout=1)` par
# repère, puis la souris est garée). Pourquoi les deux ensemble :
#
#   - hors boss final, un second « Continuer » est l'écran de fin
#     d'aventure, donc la preuve qu'on a perdu (la fin normale ne vient
#     qu'après le boss final) ;
#   - après le boss final, il vient AUSSI après une victoire ;
#   - « VOUS ÊTES MORT — Mais on vous a offert une nouvelle chance.
#     RELEVEZ-VOUS » (captures d'Ewan des 05/09/2026) arrive AVEC ou SANS
#     second « Continuer » avant lui. Le 05/09 à 20h30, boss final perdu :
#     un seul « Continuer », puis directement « Relevez-vous » — le bot
#     exigeait le second « Continuer », a conclu « aventure terminée » et
#     s'est perdu deux minutes sur cet écran, sans jamais chercher `retry`.
#
# Une fois le second « Continuer » cliqué, « Relevez-vous » peut encore
# suivre : on le guette RETRY_TIMEOUT de plus (il met un moment à se poser ;
# score 1.00 sur la capture, centre en (960, 912) sur 1920x1080).
AFTER_COMBAT_ROUNDS = 3
RETRY_TIMEOUT = 8.0

# ON NE GUETTE PAS « RELEVEZ-VOUS » APRÈS UNE VICTOIRE LUE (10/11/2026).
# Mesuré en jeu le 09/11, boss final GAGNÉ (défi 23) :
#
#     19:40:11,844  Second « Continuer » : fin d'aventure (boss final)
#     19:40:11,844  Recherche du bouton : retry
#     19:40:20,872  Bouton 'retry' introuvable            <- 9,0 s pleines
#     19:40:22,403  victoire (bilan : 50 PV restants)
#
# Le bilan au cœur portait DÉJÀ la victoire pendant ces neuf secondes : il
# a été lu une seconde et demie après, sans que l'écran ait changé entre
# temps. Le jeu n'offre pas de nouvelle chance à qui vient de gagner — un
# coup d'œil AVANT le guet suffit donc à s'en passer, et il coûte une
# image (≈ 1,5 s en jeu, dominées par la capture d'écran) contre neuf
# secondes à chaque boss final gagné.
#
# ZÉRO SECONDE, c'est-à-dire UNE SEULE IMAGE : `bilan.attendre_verdict`
# regarde, puis sort dès que le temps imparti est passé. Ce n'est pas un
# juge, c'est un coup d'œil — s'il ne voit rien, le guet se déroule
# exactement comme avant.
#
# ET SEULE UNE VICTOIRE Y AUTORISE. Un verdict None ou une DÉFAITE lue
# laissent la suite intacte, sans discuter : « Relevez-vous » est
# justement ce que le jeu offre à qui vient de perdre, et s'en passer a
# coûté 2 × 120 s et une tentative hebdomadaire le 05/09/2026.
COUP_D_OEIL_BILAN = 0.0


def _dismiss_click():
    """Un clic au centre de l'écran : ce qui ferme l'écran de résultat."""
    width, height = pyautogui.size()
    human_click(width // 2, height // 2)


def _click_continue(timeout=10, attempts=2, quiet=False):
    """Clique « Continuer », quel que soit son habillage. Rend (ok, point)."""
    for essai in range(attempts):
        for name in CONTINUE_BUTTONS:
            point = click_button(name, timeout=timeout)
            if point:
                logging.info("Bouton « Continuer » cliqué (%s).", name)
                return True, point
        if essai == 0 and attempts > 1:
            # Tous cherchés en vain : le curseur est peut-être posé sur le
            # bouton (il vient de cliquer au centre, juste à côté). On le
            # range et on refait un tour.
            park_mouse()
    if not quiet:
        logging.warning("Bouton « Continuer » introuvable après le combat.")
    return False, None


def _close_adventure_end(point):
    """La fin d'aventure : après son « Continuer », 5 s puis reclic au même point."""
    time.sleep(FINAL_BOSS_EXTRA_DELAY)
    human_click(*point)


def _declare_defeat(report, point):
    """Pas de nouvelle chance : on ferme la fin d'aventure et on marque la défaite."""
    _close_adventure_end(point)
    settle_verdict(report, won=False, verdict="écran de fin d'aventure",
                   reason="défaite (écran de fin d'aventure)")
    logging.info("Fin d'aventure fermée : retour attendu à l'écran du champion.")


def _reward_proves_victory(report) -> bool:
    """
    L'écran de RÉCOMPENSE DE COMBAT prouve que le combat a été gagné.

    06/11/2026, 16:05 — le bot a déclaré perdu un combat qu'il avait
    GAGNÉ, et la session entière s'est arrêtée là-dessus :

        16:05:09  Second « Continuer » : écran de fin, le combat perdu
        16:05:24  tentative 7 : DÉFAITE — combat perdu (boss intermédiaire)
        16:05:27  à l'écran : « RÉCOMPENSES DE COMBAT », +19 PV

    Trois secondes après le verdict, le jeu proposait un objet à équiper
    sur l'un de nos champions. ON NE REÇOIT PAS ÇA EN PERDANT.

    La règle du 05/09 — « second « Continuer » sans « Relevez-vous » =
    défaite » — reste vraie, elle vient d'observations en jeu. On lui
    ajoute une EXCEPTION PROUVÉE, qu'on ne paie que d'un coup d'œil de
    quelques secondes avant de conclure à la défaite.

    Et la cascade, c'est elle qui a tué la session : le verdict de
    défaite faisait arrêter le parcours, donc `play_reward` n'était
    jamais appelé, donc le panneau restait là — et `DISMISS_BUTTONS` n'a
    rien qui morde dessus (« Continuer » 0.32, « Quitter » 0.39).

    Import local comme `bilan` ci-dessous : `navigate` importe ce module,
    l'inverse ne peut pas se faire en tête de fichier.
    """
    import navigate

    if not navigate.play_reward("récompense (après le second « Continuer »)"):
        return False
    settle_verdict(report, won=True, verdict="récompense de combat",
                   reason="victoire (écran de récompense après le combat)")
    logging.info("Récompense de combat prise : ce combat était GAGNÉ.")
    return True


def _verdict_rendu(report) -> bool:
    """
    Le rapport porte-t-il DÉJÀ un verdict ?

    C'est, mot pour mot, la condition sous laquelle `settle_verdict`
    refuse de requalifier. Elle est écrite ici une seule fois parce que
    deux implémentations du même test finissent toujours par diverger —
    et parce qu'elle sert désormais aussi à NE PAS regarder un écran dont
    la réponse ne pourrait rien changer.
    """
    return (getattr(report, "won", None) is not None
            and bool(getattr(report, "verdict", "")))


def _lire_le_bilan(attente=None):
    """
    Ce que le bilan de fin de tentative affiché dit — ou None.

    SEUL POINT DE CE MODULE QUI PHOTOGRAPHIE L'ÉCRAN POUR JUGER, et donc
    le seul à bouchonner dans une suite hors ligne : `_judge_from_summary`
    comme `_victoire_deja_lue` passent par ici. Un bouchon par couture,
    pas un par appelant — la leçon du 08/11 sur `park_mouse`, qui avait
    deux noms importés et un seul bouchon.

    `attente` est le temps de guet ; None veut dire « celui de bilan.py ».

    L'import est local, comme celui de `CombatLoop` dans `play_combat` :
    navigate.py reste importable même si opencv manque.
    """
    import bilan

    if attente is None:
        return bilan.attendre_verdict()
    return bilan.attendre_verdict(timeout=attente)


def _victoire_deja_lue(report) -> bool:
    """
    UN COUP D'ŒIL AU BILAN AVANT DE GUETTER « RELEVEZ-VOUS ».

    Rend True seulement si l'écran prononce une VICTOIRE — auquel cas il
    n'y a aucune nouvelle chance à attendre, et les neuf secondes de
    `RETRY_TIMEOUT` sont dépensées pour rien (cf. `COUP_D_OEIL_BILAN`).

    UN VERDICT NON LU NE DÉCIDE DE RIEN. None comme une défaite rendent
    False, et la suite se déroule exactement comme avant : on ne retire
    pas le filet « Relevez-vous », on l'évite quand on a la PREUVE
    positive qu'il n'a rien à attraper. Une défaite lue, elle, n'est même
    pas enregistrée ici : le juge complet qui suit le fera, ou bien
    « Relevez-vous » rendra son propre verdict — on ne change le cours de
    rien sur un coup d'œil.
    """
    verdict = _lire_le_bilan(COUP_D_OEIL_BILAN)
    if verdict is None or not verdict.gagne:
        return False
    logging.info("Bilan de fin lu à l'écran : %s.", verdict.raison)
    settle_verdict(report, won=True, verdict=verdict.verdict, reason=verdict.raison)
    logging.info("Boss final GAGNÉ : « Relevez-vous » n'est pas guetté — le jeu "
                 "n'offre pas de nouvelle chance à qui vient de gagner.")
    return True


def _judge_from_summary(report, attente=None):
    """
    Lit le BILAN DE FIN DE TENTATIVE affiché et en tire le verdict.

    C'est le SEUL juge du boss final. Partout ailleurs, un combat est
    jugé par l'écran (« Relevez-vous », fin d'aventure) ou par
    l'aventure qui continue (`navigate.confirm_victory`, nœud suivant
    rejoint) — mais le boss final n'a PAS de nœud suivant, et son second
    « Continuer » est la sortie normale. Résultat au 05/11/2026 : le
    combat le plus important de chaque aventure était le seul à finir
    systématiquement en `gagne: null`.

    Appelé DEUX FOIS, de part et d'autre de `_close_adventure_end` :
    l'écran de défaite (le bilan au cœur) précède ce clic, l'écran de
    victoire le suit. Si rien n'est lisible, on ne rend rien : un
    verdict inventé corromprait le journal.

    MAIS ON NE RELIT PAS UN ÉCRAN DONT LE VERDICT EST DÉJÀ RENDU
    (10/11/2026). `settle_verdict` refuse de requalifier : le second de
    ces deux appels ne pouvait donc RIEN changer dès que le premier avait
    conclu — c'était une capture d'écran et un guet de plus par boss
    final, pour un résultat connu d'avance. Le garde est posé ici, en un
    seul endroit, plutôt qu'à chacun des trois appels.
    """
    if _verdict_rendu(report):
        logging.info("Bilan de fin : le verdict est déjà rendu (%s) — l'écran n'est "
                     "pas relu.", getattr(report, "verdict", ""))
        return None
    verdict = _lire_le_bilan(attente)
    if verdict is None:
        logging.info("Bilan de fin : écran non lisible — verdict laissé inconnu.")
        return None
    logging.info("Bilan de fin lu à l'écran : %s.", verdict.raison)
    settle_verdict(report, won=verdict.gagne, verdict=verdict.verdict,
                   reason=verdict.raison)
    return verdict


def settle_verdict(report, won: bool, verdict: str, reason: str) -> None:
    """
    Pose le verdict sur un rapport de combat ET le reporte au journal.

    La boucle de combat écrit sa ligne de journal en sortant, AVANT que
    l'écran ne dise qui a gagné : au 05/09/2026, 53 combats sur 53 y
    avaient `gagne: null`. Tout ce qui juge un combat après coup (l'écran
    de fin ici, l'aventure qui continue dans navigate) doit passer par
    ici, sinon le verdict reste dans les logs et jamais dans les
    statistiques.

    Un verdict déjà rendu par l'API n'est pas requalifié.
    """
    if report is None:
        return
    if _verdict_rendu(report):
        return
    report.won = won
    report.finished = True
    report.reason = reason
    try:
        report.verdict = verdict
    except Exception:       # noqa: BLE001 — un rapport sans ce champ reste jugeable
        pass
    if journal.conclude(report):
        logging.info("Journal : %s reporté (%s).", "VICTOIRE" if won else "DÉFAITE", verdict)
    else:
        logging.warning("Journal : verdict non reporté (ligne du combat introuvable).")


def confirm_victory(report) -> None:
    """
    L'aventure a continué après ce combat : il était gagné.

    Appelé par navigate quand le nœud SUIVANT a été rejoint. C'est le
    seul juge fiable d'une victoire en défi : l'API reste muette, et
    l'écran de résultat est fermé d'un clic sans être lu. Un combat perdu,
    lui, ne laisse pas continuer — il affiche la fin d'aventure ou
    « Relevez-vous », que try_combat traite lui-même.
    """
    settle_verdict(report, won=True, verdict="aventure poursuivie",
                   reason="victoire (l'aventure a continué)")


def _handle_post_combat():
    """
    Ferme l'écran de résultat et clique le premier « Continuer ». Rend True
    si « Continuer » a été trouvé et cliqué.

        1. attendre POST_COMBAT_DELAY, cliquer (écran de résultat) ;
        2. cliquer « Continuer ».

    Ce qui vient ENSUITE (second « Continuer » de fin d'aventure,
    « Relevez-vous ») dépend du résultat, que l'API ne dit pas : c'est
    try_combat qui le découvre en guettant les deux à la fois.
    """
    time.sleep(POST_COMBAT_DELAY)
    _dismiss_click()
    logging.info("Écran de résultat fermé d'un clic.")

    ok, _ = _click_continue()
    return ok


def _watch_after_continue(rounds=None):
    """
    Après le premier « Continuer » : guette à la fois un second
    « Continuer » et « Relevez-vous ». Rend (nom, point) du premier trouvé
    — nom dans CONTINUE_BUTTONS ou "retry" — ou (None, None).

    Un tour = chaque repère cherché ~1 s, puis la souris garée (le bouton
    est peut-être sous le curseur). Compté en TOURS et non en secondes
    pour rester déterministe hors ligne.
    """
    if rounds is None:
        rounds = AFTER_COMBAT_ROUNDS
    for _ in range(rounds):
        for name in CONTINUE_BUTTONS + ("retry",):
            point = click_button(name, timeout=1)
            if point:
                return name, point
        park_mouse()
    return None, None


def play_combat(**options):
    """
    Joue un combat entier avec notre boucle autonome.

    Renvoie le CombatReport : `finished`, `won`, `turns_played`,
    `reason`... L'import est fait ici et non en tête de fichier pour que
    navigate.py reste importable même si une dépendance de combat manque.
    """
    from combat import CombatLoop

    report = CombatLoop(**options).run()
    logging.info("Combat terminé — %s", report.summary())
    return report


def try_combat(node_x, node_y, final_boss=False, **options):
    """
    Joue le combat, puis gère les éventuelles nouvelles chances
    (« Relevez-vous », template `retry`) jusqu'à ce que le jeu n'en offre
    plus.

    Après le premier « Continuer », trois suites possibles (Ewan, 04 et
    05/09/2026), et l'API ne dit pas laquelle : on guette DONC À LA FOIS
    un second « Continuer » et « Relevez-vous » (_watch_after_continue).

        - « Relevez-vous », avec ou sans second « Continuer » avant :
          le combat était perdu, une nouvelle chance est offerte. La carte
          revient recentrée sur nous, l'adversaire est AU CENTRE : on le
          reclique, puis « Combat », et on rejoue.
        - second « Continuer » puis rien : écran de fin d'aventure. Hors
          boss final c'est une DÉFAITE sans nouvelle chance ; après le boss
          final c'est la sortie normale (FINAL_BOSS_EXTRA_DELAY puis reclic
          au même point) — et depuis le 05/11/2026 le verdict y est LU sur
          le bilan affiché (`_judge_from_summary`), au lieu de rester
          inconnu.
        - rien du tout : la carte est rendue, l'aventure continue (c'est
          navigate qui confirmera la victoire en rejoignant le nœud
          suivant).

    Une victoire rapportée par l'API n'est jamais requalifiée : hors boss
    final, rien n'est cherché après le premier « Continuer ».

    `node_x, node_y` : où le nœud était quand on l'a cliqué la première
    fois. On ne s'en sert PLUS pour le recliquer (la carte a bougé), gardé
    pour le journal et la compatibilité des appels.
    """
    report = play_combat(**options)
    if getattr(report, "interrupted", False):
        # La partie est ENCORE EN COURS : aucun écran de résultat à fermer,
        # aucun « Continuer » à chercher. On rend la main telle quelle ;
        # navigate et challenges savent quoi en dire.
        logging.warning("Combat interrompu par la durée maximale : la partie est "
                        "encore en cours, on ne clique rien.")
        return report
    if getattr(report, "never_started", False):
        # AUCUNE PARTIE N'A EU LIEU — donc aucun écran de résultat à
        # fermer. Le 08/11/2026, après les 122 s d'attente devant le
        # boss final, `_handle_post_combat` a cliqué au CENTRE DE LA
        # CARTE D'AVENTURE puis cherché « Continuer » pendant 48 s :
        # 48 s perdues, et un clic au hasard sur une carte où le moindre
        # nœud ouvre un panneau. On rend la main telle quelle ; navigate
        # nomme le motif, et l'écran du blocage est déjà gardé par
        # `navigate.confirmer_le_lancement`.
        logging.warning("La partie n'a jamais démarré : pas d'écran de résultat à "
                        "fermer, on ne clique rien.")
        return report
    if not _handle_post_combat():
        return report

    while True:
        if getattr(report, "won", None) is True and not final_boss:
            return report

        end_point = None
        name, point = _watch_after_continue()
        if name in CONTINUE_BUTTONS:
            end_point = point
            logging.info(
                "Second « Continuer » : %s.",
                "fin d'aventure (boss final)" if final_boss
                else "écran de fin, le combat était perdu",
            )
            # « Relevez-vous » peut encore suivre l'écran de fin — SAUF
            # si le bilan affiché dit déjà que le boss final a été gagné
            # (cf. COUP_D_OEIL_BILAN : 9,0 s mesurées en jeu le 09/11,
            # devant un écran qui portait déjà la victoire). Hors boss
            # final on ne regarde rien : ce combat-là a ses propres juges.
            if final_boss and _victoire_deja_lue(report):
                retry_point = None
            else:
                retry_point = click_button("retry", timeout=RETRY_TIMEOUT)
        else:
            retry_point = point if name == "retry" else None

        if not retry_point:
            if end_point is None:
                logging.info("Aucun « Relevez-vous » détecté, fin de la boucle de combat.")
                # MAIS LE BOSS FINAL EST JUGÉ QUAND MÊME.
                #
                # 06/11/2026, PREMIÈRE VICTOIRE SUR LE DÉFI 13 : le bot a
                # gagné et le journal a enregistré `gagne: null`. Le juge
                # n'était convoqué que si un SECOND « Continuer » s'était
                # présenté ; il n'y en a pas eu, on sortait par cette
                # ligne, et personne ne regardait l'écran. Or l'écran
                # « DÉFI 13 / VICTOIRE » s'est affiché TROIS SECONDES plus
                # tard — `bilan.juger` le lit à 0.99, et
                # `bilan.attendre_verdict` regarde justement pendant
                # quelques secondes. Il ne manquait que l'appel.
                #
                # C'est exactement le défaut que bilan.py existe pour
                # éviter : le combat le plus important de l'aventure fini
                # en `gagne: null`. Un combat ORDINAIRE, lui, garde ses
                # propres juges — on ne lui colle pas l'écran de fin de
                # TENTATIVE.
                if final_boss:
                    _judge_from_summary(report)
            elif final_boss:
                # DEUX FOIS, et ce n'est pas une ceinture-et-bretelles :
                # l'écran de DÉFAITE (le bilan au cœur) est là AVANT le clic
                # de fermeture, l'écran de VICTOIRE arrive APRÈS lui — mesuré
                # le 05/11/2026, 7 s plus tard. `settle_verdict` ne
                # requalifie pas un verdict déjà rendu : le premier qui lit
                # gagne, le second ne fait rien.
                _judge_from_summary(report)
                _close_adventure_end(end_point)
                logging.info("Boss final : dernier clic de sortie en %s.", end_point)
                _judge_from_summary(report)
            elif _reward_proves_victory(report):
                # L'écran de récompense l'emporte sur le second
                # « Continuer » : voir `_reward_proves_victory`.
                _close_adventure_end(end_point)
            else:
                _declare_defeat(report, end_point)
            return report

        settle_verdict(report, won=False, verdict="relevez-vous",
                       reason="défaite (nouvelle chance offerte)")
        logging.info("« Relevez-vous » cliqué : nouvelle chance.")
        time.sleep(RETRY_MAP_DELAY)
        # Recliquer l'adversaire : sans ce clic, pas de bouton « Combat ».
        # Il est au centre — pas en (node_x, node_y), la carte s'est recentrée.
        _dismiss_click()
        logging.info("Nouvelle chance : adversaire recliqué au centre de l'écran.")
        time.sleep(random.uniform(1.5, 2.5))

        if not click_button("combat_button"):
            logging.warning("Bouton « Combat » introuvable après « Relevez-vous ».")
            continue

        logging.info("Bouton Combat cliqué. Début du combat.")
        report = play_combat(**options)
        if not _handle_post_combat():
            return report
