#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
challenges.py

LA BOUCLE DE SESSION : enchaîner les tentatives du Défi Hebdomadaire
jusqu'à ce que le jeu n'en donne plus.

    python challenges.py --plan      # où en est le jeu, et ce qui serait fait
    python challenges.py             # enchaîne les tentatives

--------------------------------------------------------------------
CE QU'ELLE FAIT, ET CE QU'ELLE NE FAIT PAS
--------------------------------------------------------------------
Il existait déjà trois boucles, et il en manquait une quatrième :

    combat.CombatLoop        un COMBAT, phase par phase
    lor_battle.try_combat    les « Réessayer » d'un même combat
    navigate.py              les étapes d'UNE aventure
    ici                      les TENTATIVES, l'une après l'autre

`lor_automation.py` faisait une aventure et s'arrêtait. Ce module la
relance, note ce qui s'est passé, et ne s'arrête que sur une raison
NOMMÉE.

Comme les autres boucles du projet, celle-ci ne contient aucune logique
de jeu ni aucun clic : elle appelle `navigate` pour avancer et
`lor_battle` pour se battre. Son seul travail est de compter, de décider
quand s'arrêter, et de dire pourquoi. C'est ce qui la rend testable hors
ligne, sans jeu ni souris (`test_challenges.py`).

--------------------------------------------------------------------
LA CONDITION D'ARRÊT EST DONNÉE PAR LE JEU
--------------------------------------------------------------------
« Tant qu'il reste des tentatives » : le jeu ne l'annonce pas, il cesse
simplement d'afficher le bouton de confirmation
(`navigate.Entry.NO_ATTEMPT_LEFT`). C'est le signal d'arrêt normal de la
session, et c'est le seul qui ne soit pas un garde-fou.

Une DÉFAITE, elle, n'arrête rien : elle consomme une tentative comme une
victoire, donc la boucle repart. C'est le choix d'Ewan, et c'est aussi ce
que fait un joueur.

--------------------------------------------------------------------
GARDE-FOUS
--------------------------------------------------------------------
1. COIN DE L'ÉCRAN — pyautogui.FAILSAFE reste actif, comme partout.
2. DURÉE MAXIMALE de session (`--duree`), indépendante de celle d'un
   combat : une session qui dure trois heures a un problème.
3. NOMBRE DE TENTATIVES (`--tentatives`), facultatif : sans lui, on
   s'arrête quand le jeu s'arrête. IL NE COMPTE QUE CE QUI A ÉTÉ
   ENGAGÉ : une entrée qui n'aboutit pas n'a rien dépensé ni rien joué,
   donc elle ne prend pas la place d'une tentative. Le 09/11/2026 une
   fenêtre posée devant le jeu a suffi à consommer tout
   `--tentatives 1` sans qu'une seule carte soit jouée.
4. ÉCRANS PERDUS — après trois entrées manquées (ou trois retours à un
   écran connu qui échouent) d'affilée, on rend la main. C'est LE garde
   contre la boucle sans fin depuis que le point 3 ne compte plus les
   entrées manquées : sans ce compteur, un écran jamais reconnu ferait
   tourner la boucle jusqu'à la limite de durée.
5. TENTATIVES BRÛLÉES (`--abandons`) — trois tentatives consommées
   d'affilée sans qu'une seule partie se joue, et on s'arrête. C'est le
   seul garde-fou qui protège une ressource RARE : les tentatives du
   défi ne se rechargent qu'une fois par semaine, et s'acharner sur un
   template cassé les dépenserait toutes en quelques minutes. Une
   défaite ne compte pas : c'est un résultat, pas une panne.

--------------------------------------------------------------------
LANCÉ ALORS QU'UNE AVENTURE EST DÉJÀ OUVERTE
--------------------------------------------------------------------
C'est la façon la plus naturelle de s'en servir : on met le jeu en place
à la main, puis on lâche le bot. `navigate.where_are_we` reconnaît cet
écran (`Screen.ADVENTURE`), `enter_challenge_attempt` rend `RESUMED`, et
la boucle REPREND l'aventure sans dépenser de tentative.

Une limite à connaître : la navigation repart du champion de soutien.
Elle rattrape donc une aventure qui vient de commencer, pas une aventure
arrêtée au deuxième node. Dans ce cas la boucle le dit et s'arrête au
bout de trois essais, au lieu de tourner.

--------------------------------------------------------------------
CONSEIL POUR LE PREMIER LANCEMENT
--------------------------------------------------------------------
`python challenges.py --plan` ne clique rien : il dit seulement quel
écran il reconnaît là, maintenant. Si la réponse est « écran inconnu »
alors que tu es sur la carte du monde, le problème est un template à
recadrer — pas la boucle.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import pyautogui

import logfile
import champions
import gestures
import journal
import navigate
from navigate import Entry, Screen

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_DURATION = 3 * 3600.0     # trois heures
LOST_LIMIT = 3                        # écrans inconnus d'affilée avant abandon

# Tentatives ENGAGÉES mais perdues dans les menus, d'affilée, avant de
# rendre la main. Ce garde-fou-là protège quelque chose de rare : les
# tentatives du défi, qui ne se rechargent qu'une fois par semaine. Une
# navigation qui échoue trois fois de suite n'est pas de la malchance,
# c'est un template à recadrer — et s'acharner brûlerait le reste des
# tentatives pour rien. Une DÉFAITE, elle, n'entre pas dans ce compte :
# c'est un résultat de jeu, pas une panne.
ABANDON_LIMIT = 3


@dataclass
class AttemptReport:
    """Une tentative : ce qu'elle a coûté, ce qu'elle a rendu."""

    index: int
    entered: bool = False
    # Une TENTATIVE a-t-elle été dépensée ? Faux quand on a repris une
    # aventure déjà ouverte : rien n'a été consommé, et le garde-fou des
    # tentatives brûlées ne doit pas s'en émouvoir.
    consumed: bool = False
    # Au moins un combat a-t-il été JOUÉ ? Une aventure qui s'arrête avant
    # le premier combat est un problème de navigation, pas de jeu.
    fought: bool = False
    won: Optional[bool] = None
    reason: str = ""
    duration: float = 0.0

    @property
    def outcome(self) -> str:
        if self.won is True:
            return "VICTOIRE"
        if self.won is False:
            return "DÉFAITE"
        return "inachevée"

    def summary(self) -> str:
        # UNE ENTRÉE QUI N'A PAS EU LIEU N'EST NI UNE TENTATIVE NI UNE
        # REPRISE. Le 09/11/2026 le log de la session perdue disait
        # « reprise 1 : inachevée en 0 min — écran inconnu au moment
        # d'entrer » : les deux premiers mots étaient faux, et c'est sous
        # ce libellé que `--tentatives 1` a brûlé son unique créneau sans
        # que rien ne soit joué. Le libellé le dit maintenant.
        if not self.entered:
            return (
                f"entrée manquée {self.index} : {self.reason} "
                f"(en {self.duration:.0f} s — rien n'a été consommé)"
            )
        quoi = "tentative" if self.consumed else "reprise"
        return (
            f"{quoi} {self.index} : {self.outcome} "
            f"en {self.duration / 60:.0f} min — {self.reason}"
        )


@dataclass
class SessionReport:
    """Le bilan de la session entière."""

    attempts: list = field(default_factory=list)
    reason: str = ""
    duration: float = 0.0
    log: list = field(default_factory=list)
    # Entrées qui n'ont jamais abouti — écran non reconnu au moment
    # d'entrer. Elles ne sont PAS des tentatives (rien consommé, rien
    # joué, voir `run`), mais les effacer du bilan ferait disparaître la
    # seule trace d'une panne de LECTURE : fenêtre du jeu couverte,
    # gabarit à recadrer, résolution changée. On les compte à côté.
    entrees_manquees: int = 0

    def add(self, message: str) -> None:
        self.log.append(message)
        LOGGER.info(message)

    @property
    def wins(self) -> int:
        return sum(1 for a in self.attempts if a.won is True)

    @property
    def losses(self) -> int:
        return sum(1 for a in self.attempts if a.won is False)

    @property
    def unfinished(self) -> int:
        return sum(1 for a in self.attempts if a.won is None)

    def summary(self) -> str:
        manquees = (
            f", {self.entrees_manquees} entrée(s) manquée(s)"
            if self.entrees_manquees else ""
        )
        return (
            f"{len(self.attempts)} tentative(s) en {self.duration / 60:.0f} min : "
            f"{self.wins} victoire(s), {self.losses} défaite(s), "
            f"{self.unfinished} inachevée(s){manquees}. Arrêt : {self.reason}"
        )


class ChallengeSession:
    """Enchaîne les tentatives. Ne décide rien du jeu lui-même."""

    def __init__(
        self,
        max_attempts: Optional[int] = None,
        max_duration: float = DEFAULT_MAX_DURATION,
        abandon_limit: int = ABANDON_LIMIT,
        combat_options: Optional[dict] = None,
        dry_run: bool = False,
    ):
        self.max_attempts = max_attempts
        self.max_duration = max_duration
        self.abandon_limit = abandon_limit
        self.combat_options = dict(combat_options or {})
        self.dry_run = dry_run

        self.report = SessionReport()
        self._lost = 0          # écrans inconnus d'affilée
        self._abandons = 0      # engagements sans partie jouée, d'affilée
        self._burned = 0        # dont ceux qui ont VRAIMENT coûté une tentative

    # --- une tentative -------------------------------------------------
    def _play_one(self, index: int) -> AttemptReport:
        """
        Une tentative complète : entrer, naviguer, combattre.

        Chaque échec est NOMMÉ dans le rapport plutôt que d'être un
        simple False : c'est la seule façon de savoir, après une session
        de deux heures, si le bot a perdu des combats ou s'il s'est perdu
        dans les menus.
        """
        attempt = AttemptReport(index=index)
        start = time.time()

        entry = navigate.enter_challenge_attempt()
        if entry not in (Entry.LAUNCHED, Entry.RESUMED):
            attempt.reason = entry.value
            attempt.duration = time.time() - start
            return attempt

        attempt.entered = True
        # REPRENDRE N'EST PAS LANCER : une aventure déjà ouverte se
        # termine sans qu'une tentative soit dépensée.
        attempt.consumed = entry is Entry.LAUNCHED
        self._lost = 0

        # LA NAVIGATION JOUE TOUS LES COMBATS, boss final compris : elle
        # seule sait combien de nœuds la carte contient, et découvrir un
        # combat est justement ce qu'elle fait en arrivant sur un nœud.
        # UNE AVENTURE REPRISE NE REPART PAS DU DÉBUT. `enter_challenge_attempt`
        # rend RESUMED quand la carte était déjà ouverte : les premières
        # étapes ont alors été franchies avant nous, et les exiger
        # abandonnait une aventure pourtant vivante (deux tentatives
        # mensuelles perdues ainsi le 05/11/2026).
        parcours = navigate.run_adventure(combat_options=self.combat_options,
                                          reprise=(entry is Entry.RESUMED))
        combats = [c for c in parcours["combats"] if c is not None]
        attempt.fought = bool(combats)
        dernier = combats[-1] if combats else None

        if parcours["reason"].startswith("combat perdu"):
            attempt.won = False
            attempt.reason = parcours["reason"]
        elif parcours["reason"] == navigate.CLEAN_END and dernier is not None:
            # Le boss final a été joué : c'est LUI qui conclut l'aventure.
            attempt.won = dernier.won
            attempt.reason = (
                f"aventure terminée — {parcours['nodes']} nœud(s), "
                f"{len(combats)} combat(s)"
            )
        else:
            # Ni fin propre ni défaite : on ne sait pas ce qui s'est passé,
            # et le dire vaut mieux que de deviner une victoire — même si
            # un combat a été gagné en route.
            attempt.reason = parcours["reason"]

        attempt.duration = time.time() - start
        # LA TENTATIVE EST JOURNALISÉE, pas seulement ses combats. Sans
        # cette ligne, « quel champion pour quel palier ? » reste sans
        # réponse : ni les étoiles du champion ni le défi joué
        # n'apparaissaient nulle part. Le palier reste None tant que le
        # chiffre du défi n'est pas lu — la ligne vaut quand même.
        choisi = getattr(champions, "DERNIER_CHOIX", None)
        journal.record_attempt(
            palier=getattr(champions, "DERNIER_PALIER", None),
            etoiles=choisi.etoiles if choisi is not None else None,
            gagne=attempt.won,
            raison=attempt.reason,
            duree=attempt.duration,
            combats=len(combats),
        )
        return attempt

    # --- garde-fous ----------------------------------------------------
    def _mettre_le_jeu_devant(self) -> bool:
        """
        Met la fenêtre du jeu au premier plan. Rend False si on n'a pas pu,
        sans jamais arrêter la session.

        UNE FENÊTRE CACHÉE N'EST PAS UN ÉCRAN INCONNU. Tout ce que le bot
        sait de l'écran vient d'une photo du BUREAU : si une autre fenêtre
        couvre le jeu, aucun gabarit ne passe le seuil et chaque écran est
        déclaré « inconnu ». Vu le 09/11/2026 — la session a démarré
        derrière l'éditeur de texte, meilleur score 0.51 pour un seuil de
        0.80, une tentative comptée « inachevée — écran inconnu au moment
        d'entrer », et la capture gardée pour diagnostic montrait du code
        source.

        C'est la leçon du 08/11 d'un cran au-dessus : ce jour-là on a
        appris que la molette ne part nulle part si le jeu n'a pas le
        premier plan, et `gestures.focus_game_window` est né pour ça —
        mais seul `champions.py` l'appelait, au moment de faire défiler
        une grille. La condition est pourtant plus ancienne que la
        molette, et elle vaut pour TOUTE lecture d'écran.

        DÉGRADATION DOUCE, comme le reste de `gestures` : pas de jeu, pas
        de pywin32, ou bascule refusée par Windows — on le DIT et on
        continue. Refuser de démarrer serait pire : le jeu peut très bien
        être visible sans que Windows nous laisse le mettre devant.
        """
        if gestures.game_window_handle() is None:
            self.report.add(
                "Fenêtre du jeu introuvable : on lit l'écran tel qu'il est. "
                "Si une autre fenêtre le couvre, aucun gabarit ne sera reconnu."
            )
            return False
        if gestures.focus_game_window():
            return True
        self.report.add(
            "Le jeu n'a pas pu passer au premier plan : on lit l'écran tel "
            "qu'il est. Si une autre fenêtre le couvre, aucun gabarit ne "
            "sera reconnu."
        )
        return False

    def _stop_reason(self, start: float) -> Optional[str]:
        """
        La raison de s'arrêter AVANT d'engager une tentative de plus.

        `report.attempts` ne contient QUE ce qui a été engagé : `run`
        retire les entrées qui n'ont jamais abouti, qui n'ont rien
        dépensé ni rien joué. `--tentatives` compte donc des tentatives
        et non des tours de boucle — le 09/11/2026 une fenêtre posée
        devant le jeu avait suffi à consommer tout `--tentatives 1`.
        Ce qui borne les entrées manquées, c'est `LOST_LIMIT`.
        """
        if self.max_attempts is not None and len(self.report.attempts) >= self.max_attempts:
            return f"nombre de tentatives demandé atteint ({self.max_attempts})"
        elapsed = time.time() - start
        if elapsed > self.max_duration:
            return f"durée maximale de session atteinte ({self.max_duration / 60:.0f} min)"
        return None

    # --- la boucle -----------------------------------------------------
    def run(self) -> SessionReport:
        start = time.time()
        self.report.add(
            "Session démarrée — Ctrl+C ou souris dans un coin pour arrêter."
        )

        if self.dry_run:
            screen = navigate.where_are_we()
            self.report.add(f"[plan] écran reconnu : {screen.value}.")
            # Dire ce qui serait fait DEPUIS CET ÉCRAN-LÀ, et pas une
            # description générale : c'est la seule façon de vérifier
            # l'aiguillage sans rien cliquer.
            if screen is Screen.ADVENTURE:
                self.report.add(
                    "[plan] une aventure est en cours : elle serait REPRISE "
                    "(champion de soutien, nodes, boss final) sans dépenser "
                    "de tentative."
                )
            elif screen is Screen.UNKNOWN:
                self.report.add(
                    "[plan] aucun écran connu : la boucle fermerait ce qui "
                    "traîne pour retrouver un point de départ, puis "
                    "abandonnerait au bout de trois essais. Les scores "
                    "ci-dessus disent si un template est à recadrer ou si "
                    "cet écran n'est simplement pas prévu."
                )
            elif screen is Screen.RESUME:
                # L'écran que la DÉCISION sait traiter depuis le 06/11 et
                # que le PLAN ne savait pas décrire : il n'est pas dans
                # `STEPS_FROM` — il n'a pas de chemin d'entrée, il a un
                # bouton — et `STEPS_FROM[screen]` levait donc KeyError.
                # `challenges.py --plan` plantait là où le bot, lui,
                # aurait repris l'aventure sans encombre.
                self.report.add(
                    "[plan] une aventure est EN COURS et le jeu propose de la "
                    "REPRENDRE : un seul clic, aucune tentative consommée, "
                    "puis le parcours repart là où il s'était arrêté — les "
                    "étapes déjà franchies ont le droit de manquer."
                )
            else:
                # JAMAIS DE KeyError DANS UN DIAGNOSTIC. Un écran reconnu
                # sans chemin d'entrée décrit est une information, pas une
                # panne : c'est exactement ce qu'on vient lire ici.
                chemin = navigate.STEPS_FROM.get(screen)
                if chemin is None:
                    self.report.add(
                        f"[plan] écran « {screen.value} » reconnu, mais aucun "
                        "chemin d'entrée n'est décrit pour lui : la boucle "
                        "chercherait d'abord un écran connu."
                    )
                else:
                    etapes = " puis ".join(
                        f.__name__.lstrip("_").replace("_", " ") for f in chemin
                    )
                    self.report.add(f"[plan] pour entrer, il cliquerait : {etapes}.")
            self.report.add(
                "[plan] ensuite : naviguer jusqu'au boss final, jouer le "
                "combat, revenir à l'écran du champion — et recommencer "
                "jusqu'à ce que le jeu refuse une nouvelle tentative."
            )
            self.report.reason = "mode plan : rien n'a été cliqué"
            self.report.duration = time.time() - start
            return self.report

        try:
            while True:
                stop = self._stop_reason(start)
                if stop:
                    self.report.reason = stop
                    break

                # Le jeu DEVANT avant toute lecture d'écran : une fenêtre
                # cachée ferait déclarer « écran inconnu » à chaque tour.
                self._mettre_le_jeu_devant()

                attempt = self._play_one(len(self.report.attempts) + 1)
                self.report.attempts.append(attempt)
                self.report.add(attempt.summary())

                # UNE ENTRÉE QUI N'A PAS EU LIEU N'EST PAS UNE TENTATIVE.
                #
                # `_play_one` ne pose `entered` que sur LAUNCHED ou
                # RESUMED. Dans les deux autres cas le bot n'a RIEN
                # dépensé et RIEN joué, et ce n'est pas une supposition :
                # `_confirm_attempt` — le clic sur `use_attempt`, le seul
                # geste qui consomme une tentative hebdomadaire — est la
                # DERNIÈRE étape de chaque chemin de `navigate.STEPS_FROM`,
                # et quand il aboutit l'entrée rend LAUNCHED. Buter avant
                # lui, c'est s'être perdu sans rien payer.
                #
                # Le précédent était déjà écrit ici pour NO_ATTEMPT_LEFT
                # (« elle n'a rien joué ») ; il manquait de le dire de
                # l'AUTRE entrée qui n'a rien joué non plus. Le 09/11/2026
                # l'éditeur de texte couvrait le jeu, aucun gabarit ne
                # passait le seuil, et `--tentatives 1` s'est arrêté sur
                # une panne de LECTURE : la session entière pour un écran
                # mal photographié. La cause est réparée
                # (`_mettre_le_jeu_devant`), celle-ci est la comptabilité.
                #
                # LE GARDE CONTRE LA BOUCLE SANS FIN EST AILLEURS, ET IL
                # EST INDÉPENDANT DE CE COMPTEUR : `self._lost` plafonne
                # les entrées manquées CONSÉCUTIVES à `LOST_LIMIT` (plus
                # bas), et il n'est remis à zéro que par une entrée qui
                # réussit. Ne pas compter ici ne retire donc aucun
                # garde-fou — c'est verrouillé par
                # `test_une_entree_manquee_ne_brule_pas_la_session`,
                # cas (c) et (d).
                if not attempt.entered:
                    self.report.attempts.pop()
                    if attempt.reason != Entry.NO_ATTEMPT_LEFT.value:
                        self.report.entrees_manquees += 1

                # PLUS DE TENTATIVE : la fin normale de la session. Le jeu
                # l'annonce en cessant d'afficher le bouton, pas autrement.
                # Ce n'est pas une panne d'entrée : c'est le CONSTAT qu'il
                # n'en reste plus, et il ne doit pas gonfler le compte des
                # écrans mal lus.
                if attempt.reason == Entry.NO_ATTEMPT_LEFT.value:
                    self.report.reason = Entry.NO_ATTEMPT_LEFT.value
                    break

                # UN COMBAT COUPÉ PAR SA DURÉE MAXIMALE, PARTIE ENCORE EN
                # COURS : rien à fermer, rien à reprendre — chercher un écran
                # connu sur un plateau de jeu tournerait 2 × 120 s pour rien
                # (06/09/2026). On le dit et on rend la main.
                # L'API MUETTE N'EST PAS UN COMBAT PERDU : le bot n'a rien
                # vu du plateau. Enchaîner brûlerait les tentatives de la
                # semaine à l'aveugle, une par une — c'est ce qui serait
                # arrivé le 04/11/2026 sans `--tentatives 1`.
                if attempt.reason.startswith(navigate.API_DOWN_PREFIX):
                    self.report.reason = (
                        attempt.reason + " — vérifie que Legends of Runeterra "
                        "tourne et que son API locale répond "
                        "(`python check.py` le dit en une ligne)"
                    )
                    break

                if attempt.reason.startswith(navigate.INTERRUPTED_PREFIX):
                    self.report.reason = (
                        attempt.reason + " — termine la partie à la main, ou relance "
                        "avec `--duree-combat` plus long"
                    )
                    break

                # Engagé mais rien joué : la boucle n'avance pas. Deux
                # cas très différents derrière le même symptôme, et le
                # message doit dire lequel — l'un coûte des tentatives
                # hebdomadaires, l'autre non.
                if attempt.entered and attempt.won is None:
                    self._abandons += 1
                    self._burned += int(attempt.consumed)
                    if self._abandons >= self.abandon_limit:
                        if self._burned:
                            self.report.reason = (
                                f"{self._burned} tentative(s) consommée(s) sans "
                                "qu'une partie se joue — vérifie les templates de "
                                "assets/ avant de relancer, chaque essai coûte une "
                                "tentative hebdomadaire"
                            )
                        else:
                            self.report.reason = (
                                "impossible de reprendre l'aventure déjà en cours "
                                f"({self._abandons} essais) — la navigation repart "
                                "du champion de soutien, donc elle ne sait pas "
                                "rattraper une aventure commencée plus loin : "
                                "termine-la à la main, ou reviens à la carte du monde"
                            )
                        break
                elif attempt.entered:
                    self._abandons = 0
                    self._burned = 0

                # LE PLAFOND D'ENTRÉES MANQUÉES CONSÉCUTIVES. C'est lui,
                # et lui seul, qui empêche une panne de lecture
                # permanente de faire tourner la session sans fin depuis
                # qu'une entrée manquée ne compte plus dans
                # `--tentatives`. Il n'est remis à zéro que par une
                # entrée qui réussit (`_play_one`).
                if not attempt.entered:
                    self._lost += 1
                    if self._lost >= LOST_LIMIT:
                        # LA CAUSE N°1 MESURÉE N'EST PAS UN TEMPLATE, et
                        # le message ne le disait pas : sur les 13
                        # entrées manquées de `logs/`, celle du 09/11 a
                        # été lue sur l'éditeur de texte qui couvrait le
                        # jeu. Le bot photographie le BUREAU.
                        self.report.reason = (
                            f"{LOST_LIMIT} écrans inconnus d'affilée — vérifie "
                            "qu'aucune fenêtre ne couvre celle du jeu (le bot "
                            "photographie le bureau), puis les templates de "
                            "assets/ et la résolution du jeu"
                        )
                        break

                screen = navigate.back_to_known_screen()
                if screen is Screen.UNKNOWN:
                    self._lost += 1
                    self.report.add(
                        "Retour à un écran connu impossible après la tentative."
                    )
                    if self._lost >= LOST_LIMIT:
                        self.report.reason = (
                            "impossible de revenir à un écran connu — le jeu "
                            "est peut-être sur un écran dont aucun template "
                            "n'existe"
                        )
                        break

        except KeyboardInterrupt:
            self.report.reason = "interrompu au clavier"
        except pyautogui.FailSafeException:
            self.report.reason = "interrompu par le coin de l'écran"

        self.report.duration = time.time() - start
        self.report.add(self.report.summary())
        return self.report


def run_session(**kwargs) -> SessionReport:
    """Raccourci : une session, un rapport."""
    return ChallengeSession(**kwargs).run()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enchaîne les tentatives du Défi Hebdomadaire (navigation + combats)."
    )
    parser.add_argument("--plan", action="store_true",
                        help="dire quel écran est reconnu, sans rien cliquer")
    parser.add_argument("--tentatives", type=int, default=None,
                        help="s'arrêter après ce nombre de tentatives "
                             "(par défaut : quand le jeu n'en donne plus)")
    parser.add_argument("--duree", type=float, default=DEFAULT_MAX_DURATION,
                        help="durée maximale de la session, en secondes")
    parser.add_argument("--abandons", type=int, default=ABANDON_LIMIT,
                        help="tentatives perdues dans les menus, d'affilée, "
                             "avant d'abandonner la session")
    parser.add_argument("--speed", type=float, default=None,
                        help="échelle des gestes souris (1 = d'origine, 2 = deux fois plus rapide)")
    parser.add_argument("--spells", action="store_true",
                        help="sans effet en mode par défaut (les sorts y "
                             "sont déjà joués) ; n'autorise les sorts qu'avec "
                             "--prudent")
    parser.add_argument("--chump", action="store_true",
                        help="autoriser les blocages sacrificiels hors situation létale")
    parser.add_argument("--mulligan", action="store_true",
                        help="forcer le mulligan même sans calibration")
    parser.add_argument("--duree-combat", type=float, default=None,
                        help="durée maximale d'UN combat, en secondes")
    parser.add_argument("--record", nargs="?", const=True, default=None, metavar="DOSSIER",
                        help="enregistrer tout ce que le bot voit (API + captures) pour "
                             "`replay.py` ; sans dossier : traces/challenges_<horodatage>/")
    parser.add_argument("--sans-ocr", action="store_true",
                        help="ne pas charger easyocr : chiffres lus par la forme seule (digits.py)")
    args = parser.parse_args()

    logfile.setup("challenges")

    # PRÉ-VOL OCR ICI AUSSI : jusqu'au 05/09/2026 seul combat.py le faisait,
    # et une session de défi chargeait torch au milieu du premier tour
    # (5 s de gel, « Neither CUDA nor MPS… » dans le log) — ou plantait au
    # tour 1 hors de `.venv`, mulligan déjà validé.
    import mana
    if args.sans_ocr:
        mana.OCR_DISABLED = True
        print("Sans OCR : chiffres lus par la forme seule, easyocr jamais chargé.")
    else:
        print("Chargement du modèle OCR...")
    try:
        mana.preload_reader()
    except mana.OCRIndisponible as exc:
        print(f"\nArrêt avant d'entrer dans le défi.\n{exc}")
        raise SystemExit(1)

    if args.record:
        import replay
        trace = replay.start_recording(None if args.record is True else args.record, "challenges")
        print(f"Trace enregistrée dans {trace} — `python replay.py list {trace}` pour la relire.")

    # PAUSE À ZÉRO, ET C'EST VOLONTAIRE : c'est une pause implicite après
    # CHAQUE appel pyautogui, donc payée par chacun des dizaines de
    # `moveTo` d'un déplacement en courbe. Les temporisations utiles sont
    # explicites dans actions.py et click_utils.py.
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    if args.speed is not None:
        import actions
        actions.set_gesture_speed(args.speed)

    combat_options = {
        "allow_spells": args.spells,
        "allow_chump": args.chump,
        "auto_mulligan": args.mulligan,
    }
    if args.duree_combat is not None:
        combat_options["max_duration"] = args.duree_combat

    report = run_session(
        max_attempts=args.tentatives,
        max_duration=args.duree,
        abandon_limit=args.abandons,
        combat_options=combat_options,
        dry_run=args.plan,
    )

    print()
    print(report.summary())
    for attempt in report.attempts:
        print(f"  {attempt.summary()}")


if __name__ == "__main__":
    main()
