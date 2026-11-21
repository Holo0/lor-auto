#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
combat.py

Boucle autonome de combat : lire la phase, agir, recommencer.

    python combat.py --plan     # décrit chaque décision, SANS toucher la souris
    python combat.py            # joue le combat en autonomie

--------------------------------------------------------------------
CE QUE FAIT LA BOUCLE, ET CE QU'ELLE NE FAIT PAS
--------------------------------------------------------------------
Elle ne contient AUCUNE logique de jeu. Tout est déjà dans game_state
(quelle phase) et actions (quoi faire). Son seul travail est
l'aiguillage, la temporisation et l'arrêt propre. C'est délibéré : une
boucle qui décide en plus d'orchestrer devient impossible à tester.

--------------------------------------------------------------------
GARDE-FOUS
--------------------------------------------------------------------
Un script qui pilote la souris en autonomie doit pouvoir être arrêté et
ne doit jamais tourner à vide indéfiniment. Cinq protections :

1. COIN DE L'ÉCRAN — pyautogui.FAILSAFE reste actif : amener la souris
   dans un coin lève une exception et arrête tout, immédiatement.

2. DURÉE MAXIMALE — la boucle s'arrête au bout de `--duree` secondes,
   même si la partie n'est pas finie. Un combat LoR dépasse rarement
   quinze minutes ; au-delà, quelque chose ne va pas.

3. DÉTECTION DE BLOCAGE — si l'état du jeu ne change plus pendant
   plusieurs DIZAINES DE SECONDES, la boucle le remarque, tente de
   débloquer en passant, puis abandonne. Sans ça, un bouton mal placé
   fait tourner le script pour rien jusqu'à la limite de durée. La
   patience se compte en secondes et non en lectures depuis le
   10/11/2026 : sinon, changer le rythme de la boucle changerait en
   silence le moment où elle renonce (cf. `STUCK_CANCEL_AFTER`).

4. ATTENTE DU DÉMARRAGE — après un clic sur « Combat », le client reste
   en `Menus` pendant tout le chargement. La boucle attend donc une
   partie réellement en cours avant de considérer que `Menus` signifie
   « terminé ». Sans ça, lancée depuis navigate.py, elle rendait la main
   aussitôt sans jouer un seul tour.

5. MULLIGAN TANT QU'IL N'EST PAS CALIBRÉ — la position du bouton de
   validation s'apprend d'un clic (`python actions.py mulligan
   --calibrate`). Tant qu'elle n'est pas connue, la boucle te laisse la
   main plutôt que de cliquer sur une position devinée.

--------------------------------------------------------------------
CONSEIL POUR LE PREMIER TEST
--------------------------------------------------------------------
Lance `python combat.py --plan` pendant un vrai combat que tu joues à la
main. La boucle annonce ce qu'elle ferait à chaque phase sans rien
exécuter : tu vois si l'aiguillage est juste avant de lui confier la
souris.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

import cv2
import pyautogui

import actions
import logfile
import journal
import lor_api
import digits
import mana
import sortie_utf8
import strategy
from game_state import GameSnapshot, GameStateReader, Phase, snapshot_signature

LOGGER = logging.getLogger(__name__)

# Phases où l'on n'a rien à faire qu'attendre, SANS LIMITE de patience :
# pendant le tour de l'adversaire, un état qui ne bouge pas est normal.
WAITING_PHASES = (Phase.OPPONENT_TURN, Phase.NO_API)

# ATTACKING, lui, est une attente BORNÉE et c'est délibéré. Une attaque
# déclarée se résout en quelques secondes ; au-delà, ce n'est plus une
# résolution mais un face-à-face — le jeu attend quelque chose de nous.
# C'est ce qui manquait le 20/08/2026 : la boucle a attendu jusqu'à la
# durée maximale pendant que le jeu réclamait des bloqueurs.

DEFAULT_POLL = 1.0
# 25 minutes depuis le 06/09/2026 : un combat de défi légitime a duré 521 s
# le 05/09, et une boucle qui tournait en rond (Buhru Lookout ×14) a
# consommé les 900 s d'avant — ce cas-là est traité à la source (`carry`
# dans actions.play_hand). La limite reste un garde-fou, pas un rythme.
DEFAULT_MAX_DURATION = 1500.0

# Délai laissé à la partie pour DÉMARRER après le lancement du combat.
# Entre le clic sur « Combat » et le premier tour, il y a l'écran de
# chargement, l'animation d'entrée et éventuellement le mulligan : le
# client annonce `GameState = Menus` pendant tout ce temps.
STARTUP_TIMEOUT = 120.0

# --------------------------------------------------------------------
# LA PATIENCE SE COMPTE EN SECONDES, PLUS EN LECTURES (10/11/2026)
# --------------------------------------------------------------------
# Les trois bornes d'escalade comptaient des ITÉRATIONS (12 / 25 / 40).
# Tant que la boucle tournait à un rythme fixe, c'était la même chose ;
# dès qu'on l'accélère, ce ne l'est plus — et une boucle deux fois plus
# vive aurait abandonné un combat en deux fois moins de temps, c'est-à-dire
# exactement la panne qu'on cherche à éviter, échangée contre quelques
# secondes.
#
# LA CONVERSION NE SE FAIT PAS EN MULTIPLIANT PAR `poll`. Une itération
# gelée ne dure pas `poll` : elle dure `poll` PLUS la lecture, et la
# lecture est la part la plus lourde. Mesuré sur les logs — entre
# « Rien ne bouge depuis 12 lectures » et « Toujours bloqué » il y a
# exactement 13 itérations, et les deux lignes sont horodatées :
#
#     19 blocages en ATTACKING (06/09/2026)  : 4,19 s de médiane (3,74-4,30)
#      2 paliers en SPELL_STACK (05/11/2026) : 4,38 s puis 4,48 s
#
# Dont ~2,2 s de LECTURE : `stable_snapshot(confirmations=2)` fait deux
# `snapshot()` à ~0,9 s pièce (appel d'API, capture d'écran, recherche
# multi-échelle du jeton d'attaque) séparés de ses 0,6 s de confirmation.
# Cette part-là ne dépend pas de `poll` — c'est le plancher du rythme.
DUREE_LECTURE = 2.2

# Les bornes d'avant, converties par cette durée mesurée et ARRONDIES VERS
# LE BAS : une borne plus lâche qu'avant ferait traîner un combat bloqué,
# ce qui est un défaut au même titre qu'une borne plus stricte.
#     12 x 4,19 = 50,3   25 x 4,19 = 104,8   40 x 4,19 = 167,6
STUCK_CANCEL_AFTER = 50.0         # s d'immobilité avant la tentative d'annulation
STUCK_PASS_AFTER = 104.0          # s d'immobilité avant le clic de passe
STUCK_ABORT_AFTER = 167.0         # s d'immobilité avant l'abandon
# CE QUE L'ÉTALONNAGE NE PEUT PAS FAIRE, ET IL FAUT LE SAVOIR : une borne
# UNIQUE en secondes ne peut pas rendre le même compte de lectures dans
# toutes les phases, parce qu'une itération n'y coûte pas la même chose.
# Les 21 blocages mesurés sont tous dans des phases qui dorment 2 s
# (ATTACKING, et SPELL_STACK orbe grise où le handler ajoute la sienne) :
# l'étalon vient de là, et il y rend 12 / 25 / 40 à l'identique. Une phase
# qui ne dort qu'une seconde (un blocage, un mulligan resté à la main)
# tourne plus vite, donc la même patience lui achète ~30 % de lectures en
# plus. C'est la patience, en secondes, qui est la grandeur conservée — et
# c'est elle qu'on voulait conserver.

# --------------------------------------------------------------------
# L'ATTENTE EST ADAPTATIVE (10/11/2026)
# --------------------------------------------------------------------
# `poll` était le même partout : une seconde après avoir joué notre tour
# comme une seconde pendant que l'adversaire réfléchit. Or l'instantané
# dit déjà laquelle des deux situations on est en train de vivre —
# `turn_orb_active` nomme celui qui a la parole, la phase dit le reste.
#
# Trois régimes, tous multiples de `poll` pour que `--poll` reste le
# rythme d'ensemble (et qu'un `--poll 0` ne dorme toujours pas) :
#
#     poll x 0,3  le jeu attend un geste de NOUS — tout ce qu'on gagne à
#                 relire tôt est du temps rendu au combat ;
#     poll        régime normal ;
#     poll x 2    c'est à l'adversaire de parler, ou le jeu résout une
#                 attaque : relire plus souvent ne rapporte rien, et
#                 chaque lecture coûte 2,2 s.
#
# CE CHANTIER N'ÉTAIT PAS TENABLE AVANT LA CONVERSION CI-DESSUS : des
# bornes en lectures auraient fait abandonner trois fois plus tôt partout
# où l'attente raccourcit.
ATTENTE_ADAPTATIVE = True
ATTENTE_COURTE_RATIO = 0.3

# UN BLOCAGE DOIT LAISSER UNE TRACE REGARDABLE. Le journal du 03/09/2026
# comptait 5 combats arrêtés sur « durée maximale (900 s) » avec pour seule
# explication « bloqué en X » : sans image ni état, impossible de savoir ce
# que le jeu attendait. À chaque palier d'escalade, on écrit l'état complet
# (`snapshot.summary()`) dans le rapport et l'écran dans screenshots/.
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"


def save_stuck_screen(phase_name: str) -> str:
    """Écran du jeu au moment d'un blocage. Rend le chemin, ou "" si impossible."""
    try:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        path = SCREENSHOT_DIR / f"bloque_{phase_name}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(path), lor_api.capture_screen_bgr())
        return str(path)
    except Exception as exc:      # noqa: BLE001 — le diagnostic ne doit pas planter la boucle
        LOGGER.warning("Capture du blocage impossible : %s", exc)
        return ""


@dataclass
class CombatReport:
    """Ce qui s'est passé pendant la boucle."""

    finished: bool = False
    won: Optional[bool] = None
    reason: str = ""
    # La boucle s'est arrêtée (durée maximale) ALORS QUE LA PARTIE CONTINUE :
    # rien d'après-combat n'a de sens (pas d'écran de résultat à fermer,
    # pas de nœud suivant). 06/09/2026 : la navigation cherchait « nœud 2 »
    # sur un plateau de jeu, puis 2 × 120 s d'écran inconnu.
    interrupted: bool = False
    # LA PARTIE N'A JAMAIS ÉTÉ LUE : l'API du client n'a rien rapporté de
    # tout le temps d'attente. Ce n'est pas un combat raté, c'est une
    # panne — et elle ne se répare pas en rejouant. 04/11/2026 : le jeu
    # affichait le mulligan du boss final pendant que le bot attendait
    # 120 s, concluait « la partie n'a pas démarré » puis cherchait
    # « Continuer » ; le port 21337 était fermé. Une tentative de défi
    # brûlée pour rien, et rien dans le rapport ne désignait la cause.
    api_down: bool = False
    # AUCUNE PARTIE N'A ÉTÉ LANCÉE : l'API a répondu tout du long, et
    # elle a dit « menus » du premier au dernier coup d'œil. Ce n'est ni
    # un combat raté ni une panne d'API — c'est le clic sur « Combat »
    # qui n'a rien déclenché (08/11/2026, boss final : 122 s d'attente
    # devant la carte d'aventure). La différence compte pour l'APRÈS :
    # il n'y a pas d'écran de résultat à fermer, donc rien à cliquer au
    # centre et aucun « Continuer » à chercher — 48 s de gestes sur une
    # carte, ce soir-là, pour rien.
    never_started: bool = False
    # QUI A RENDU LE VERDICT. Vide tant qu'aucun juge ne s'est prononcé ;
    # sinon « API /game-result », « écran de fin d'aventure » (lor_battle),
    # « aventure poursuivie » (navigate)... Le journal l'enregistre : un
    # `won` sans provenance ne se vérifie pas (cf. journal.conclude).
    verdict: str = ""
    # Identifiant de la ligne écrite par `journal.record`, pour que
    # `journal.conclude` la retrouve quand le verdict tombe après coup.
    journal_id: Optional[str] = None
    turns_played: int = 0
    cards_played: int = 0
    attacks: int = 0
    blocks: int = 0
    duration: float = 0.0
    log: list = field(default_factory=list)
    # Cartes écartées pendant le combat, agrégées : [{carte, code, motif, n}].
    # `motif` est le motif NORMALISÉ (chiffres remplacés par N, cf.
    # journal.normalize_reason) pour que « coût 3 > mana 2 » et « coût 5 >
    # mana 1 » comptent ensemble. `n` = nombre d'épisodes de jeu où la
    # carte a été écartée pour ce motif.
    rejections: list = field(default_factory=list)

    def add(self, message: str) -> None:
        self.log.append(message)
        LOGGER.info(message)

    def note_rejections(self, rejections) -> None:
        for name, code, reason in rejections or ():
            motif = journal.normalize_reason(reason)
            for entry in self.rejections:
                if entry["code"] == code and entry["motif"] == motif:
                    entry["n"] += 1
                    break
            else:
                self.rejections.append({"carte": name, "code": code, "motif": motif, "n": 1})

    def summary(self) -> str:
        outcome = "—"
        if self.finished:
            outcome = {True: "VICTOIRE", False: "DÉFAITE", None: "terminé"}[self.won]
        return (
            f"{outcome} après {self.duration:.0f} s — "
            f"{self.turns_played} tour(s), {self.cards_played} carte(s) posée(s), "
            f"{self.attacks} attaque(s), {self.blocks} blocage(s). "
            f"Arrêt : {self.reason}"
        )


class CombatLoop:
    """Aiguillage phase -> action, avec arrêt propre."""

    def __init__(
        self,
        reader: Optional[GameStateReader] = None,
        allow_spells: bool = False,
        allow_chump: bool = False,
        auto_mulligan: bool = False,
        dry_run: bool = False,
        poll: float = DEFAULT_POLL,
        max_duration: float = DEFAULT_MAX_DURATION,
    ):
        self.reader = reader or GameStateReader()
        self.allow_spells = allow_spells
        self.allow_chump = allow_chump
        self.auto_mulligan = auto_mulligan
        self.dry_run = dry_run
        self.poll = poll
        self.max_duration = max_duration

        self.config = {
            "spells": allow_spells,
            "chump": allow_chump,
            "nexus_weight": actions.NEXUS_DAMAGE_WEIGHT,
            # Sans restrictions, `spells` ne veut plus rien dire (tous les
            # sorts partent) : c'est cette ligne-là qui distingue les
            # parties, et sans elle le journal comparerait des combats
            # joués selon deux règles différentes sous la même étiquette.
            "restrictions": actions.CARD_RESTRICTIONS,
            # Enregistré pour que `journal.py` puisse répondre à « est-ce
            # que lire les coûts à l'écran fait gagner plus de parties ? »
            "screen_costs": actions.READ_SCREEN_COSTS,
            # Et à « la forme seule (--sans-ocr) fait-elle perdre des
            # parties ? » — la question à trancher avant d'enlever torch.
            "ocr": not mana.OCR_DISABLED,
        }
        self.report = CombatReport()
        self._last_signature = None
        # Temps d'IMMOBILITÉ accumulé (secondes) et heure de la dernière
        # lecture : c'est lui qui déclenche l'escalade, pas un compte de
        # lectures. `_stuck` ne sert plus qu'à le dire dans le rapport.
        self._immobile = 0.0
        self._derniere_lecture = None
        self._stuck = 0
        # « Menus » ne veut PAS dire la même chose avant et après. Tant
        # qu'on n'a jamais vu de partie en cours, c'est un chargement ;
        # ensuite, c'est une partie terminée. Sans ce drapeau, la boucle
        # rendait la main aussitôt après le lancement du combat, avant
        # même que la partie s'affiche.
        self._seen_in_game = False
        # AVONS-NOUS DÉCLARÉ CETTE ATTAQUE ? Trois réponses, pas deux.
        # None = on ne sait pas (boucle lancée au milieu d'un combat) :
        # dans le doute on ne requalifie rien. False = on a vu le plateau
        # dégagé depuis, donc non. C'est cette réponse-là qui démasque un
        # Challenger.
        self._we_attacked = None
        # Le tour courant a-t-il déjà été compté ? (cf. _handle_our_turn)
        self._turn_open = False
        # Dernier mana vu à la FIN d'un de nos épisodes de jeu : un mana de
        # début d'épisode supérieur veut dire que le round a tourné.
        self._mana_last = None
        # CardID des champions déjà annoncés montés (cf. _note_level_ups).
        self._leveled_seen = set()
        # La decklist dont la stratégie a été déduite (cf. _note_deck) :
        # relue seulement si le deck change (nouvelle partie, événement).
        self._strategy_deck = None
        # Cartes mises de côté (pose ratée) et dernier mana lu : partagé
        # entre les épisodes d'un même round, vidé quand le mana remonte
        # (cf. actions.play_hand, `carry`).
        self._carry = {"codes": set(), "mana": None}

    # --- handlers par phase --------------------------------------------
    def _handle_our_turn(self, snapshot: GameSnapshot) -> None:
        log = actions.play_turn(
            self.reader,
            snapshot=snapshot,
            allow_spells=self.allow_spells,
            finish_turn=True,
            dry_run=self.dry_run,
            carry=self._carry,
        )
        self.report.log.extend(log.entries)
        # Un tour interrompu par un sort sur la pile revient ici après la
        # riposte : c'est le MÊME tour, on ne le compte qu'une fois. Le
        # compteur se réarme quand la main repasse à l'adversaire...
        #
        # ...SAUF QUE LA MAIN NE REPASSE PAS TOUJOURS PAR UNE PHASE
        # D'ATTENTE. Journal du 05/09/2026 : « 1 tour(s), 10 carte(s)
        # posée(s), 230 s ». L'adversaire attaque (BLOCKING), on bloque,
        # on rejoue dans le MÊME round avec le mana restant, puis il passe
        # et le round suivant commence — sans qu'OPPONENT_TURN ait été lu
        # entre deux, parce qu'il joue plus vite que la boucle ne relit.
        # Le mana tranche : il ne REMONTE qu'au changement de round. Un
        # épisode qui démarre avec plus de mana que le précédent n'en a
        # laissé est un nouveau tour, phase d'attente vue ou non.
        mana_start = getattr(log, "mana_start", None)
        refilled = (
            mana_start is not None
            and self._mana_last is not None
            and mana_start > self._mana_last
        )
        if not self._turn_open or refilled:
            self.report.turns_played += 1
            self._turn_open = True
        mana_end = getattr(log, "mana_end", None)
        if mana_end is not None:
            self._mana_last = mana_end
        elif mana_start is not None:
            self._mana_last = mana_start
        self.report.note_rejections(getattr(log, "rejections", None))
        for entry in log.entries:
            if "carte(s) posée(s)" in entry:
                self.report.cards_played += int(entry.split()[0])
            if "unité(s) engagée(s)" in entry and not entry.startswith("0"):
                self.report.attacks += 1
                self._we_attacked = True

    def _note_deck(self, snapshot: GameSnapshot) -> None:
        """
        LE DECK DIT COMMENT JOUER. Dès que `/static-decklist` est lisible
        (`snapshot.deck`), `strategy.profile_deck` en tire l'archétype et
        `actions.STRATEGY` le porte pour tout le combat : poids du nexus,
        plancher d'attaque, bonus des « Attack: », seuil de mulligan. Le
        journal reçoit `archetype` et `champions` pour que `journal.py`
        compare les taux de victoire par plan de jeu.
        """
        deck = getattr(snapshot, "deck", None)
        if not deck or deck == self._strategy_deck:
            return
        self._strategy_deck = dict(deck)
        card_db = getattr(self.reader, "card_db", None)
        if card_db is None:
            card_db = lor_api.load_card_db()
        strat = actions.set_strategy(strategy.profile_deck(deck, card_db))
        self.config["archetype"] = strat.name
        self.config["champions"] = ", ".join(strat.champions)
        self.report.add(f"Stratégie : {strat.describe()}")

    def _note_level_ups(self, snapshot: GameSnapshot) -> None:
        """
        Un champion monté de niveau change de cardCode dans l'API : on le
        journalise une fois par carte, de chaque côté. Pas de vision, pas
        d'OCR — c'est la donnée la plus fiable du plateau.
        """
        for card in snapshot.cards("board", "attack", "enemy_board", "enemy_attack"):
            if card.is_leveled and card.card_id not in self._leveled_seen:
                self._leveled_seen.add(card.card_id)
                side = "notre" if card.local else "son"
                self.report.add(f"Niveau 2 : {side} champion {card.name} est monté.")

    def _reconsider_attacking(self, snapshot: GameSnapshot) -> GameSnapshot:
        """
        « ATTACKING » dit que NOTRE rangée est avancée. Ça ne dit pas que
        c'est nous qui attaquons.

        Challenger et Vulnerable TIRENT une de nos unités en face de
        l'attaquant : elle traverse la ligne toute seule, sans qu'on ait
        rien déclaré. La lecture d'état y voit notre attaque et la boucle
        se met à attendre une résolution qui n'arrivera pas, pendant que
        le jeu attend nos bloqueurs.

        `game_state` tranche déjà quand le jeton est visible du côté
        adverse. Ici on répond à la même question SANS RIEN REGARDER :
        la boucle sait ce qu'elle a déclaré. Si elle n'a rien déclaré
        depuis que le plateau est dégagé, notre rangée ne s'est pas
        remplie toute seule.
        """
        if snapshot.phase is not Phase.ATTACKING:
            if not snapshot.attack_row and not snapshot.enemy_attack_row:
                # Plateau dégagé : le combat qui vient part d'une page
                # blanche, et on n'y a encore rien déclaré.
                self._we_attacked = False
            return snapshot

        # `is not False` couvre le doute (None) : on ne requalifie que sur
        # une certitude.
        if self._we_attacked is not False or not snapshot.enemy_attack_row:
            return snapshot

        self.report.add(
            "Notre rangée est avancée alors qu'on n'a déclaré aucune "
            "attaque : une unité a été tirée en défense (Challenger). "
            "C'est à nous de bloquer, pas d'attendre."
        )
        return replace(snapshot, phase=Phase.BLOCKING)

    def _handle_blocking(self, snapshot: GameSnapshot) -> None:
        done, _, log = actions.execute_blocks(
            self.reader, snapshot, allow_chump=self.allow_chump, dry_run=self.dry_run
        )
        self.report.log.extend(log.entries)
        if done:
            self.report.blocks += 1

    def _handle_mulligan(self, snapshot: GameSnapshot) -> None:
        # Le mulligan s'automatise dès que le bouton a été calibré. Tant
        # qu'il ne l'est pas, cliquer reviendrait à parier sur une
        # position devinée, et un mauvais clic gâche la main de départ.
        if not self.auto_mulligan and not actions.mulligan_is_calibrated():
            self.report.add(
                "Mulligan : à toi de jouer. Pour l'automatiser, lance "
                "`python actions.py mulligan --calibrate` pendant cet écran."
            )
            time.sleep(2.0)
            return
        log = actions.do_mulligan(
            self.reader, snapshot,
            max_cost=actions.STRATEGY.mulligan_max_cost, dry_run=self.dry_run,
        )
        self.report.log.extend(log.entries)
        # `do_mulligan` a déjà laissé passer les animations d'échange
        # (MULLIGAN_CONFIRM_WAIT) ; cette pause-ci couvre la mise en place
        # du premier tour, qui suit.
        time.sleep(actions.MULLIGAN_CONFIRM_WAIT)

    def _handle_spell_stack(self, snapshot: GameSnapshot) -> None:
        # Un sort attend sur la pile — le nôtre, le sien, ou sa réponse au
        # nôtre. Orbe grise : c'est à lui de parler, on attend (attente
        # BORNÉE par _check_progress, la phase n'est pas dans
        # WAITING_PHASES). Orbe bleue : on répond avec un sort si on en a
        # un de jouable, sinon on passe. Ne rien faire figerait la partie.
        log = actions.respond_to_stack(
            self.reader, snapshot, allow_spells=self.allow_spells, dry_run=self.dry_run,
            allow_chump=self.allow_chump,
        )
        self.report.log.extend(log.entries)
        # Blocages posés sous la pile (attaque adverse à compétences).
        self.report.blocks += getattr(log, "blocks", 0)
        if not self.dry_run and not snapshot.turn_orb_active:
            time.sleep(self.poll)

    # --- rythme -----------------------------------------------------------
    def _attente(self, snapshot: GameSnapshot) -> float:
        """
        Combien attendre avant la prochaine lecture.

        ON NE DEVINE PAS : la réponse est dans l'instantané. L'orbe dit à
        qui c'est de parler (cf. la fenêtre de Yoink!, 05/11 : « l'orbe dit
        à qui c'est de parler ») et la phase dit ce que le jeu est en
        train de faire. Quand c'est NOUS qu'il attend, chaque dixième de
        seconde d'attente est du temps perdu ; quand c'est l'adversaire,
        relire plus souvent ne rapporte rien.

        `ATTENTE_ADAPTATIVE = False` remet l'ancien barème à l'identique.
        """
        phase = snapshot.phase
        long, normal = self.poll * 2, self.poll

        if not ATTENTE_ADAPTATIVE:
            return long if (phase in WAITING_PHASES
                            or phase is Phase.MENUS
                            or phase is Phase.ATTACKING) else normal

        court = self.poll * ATTENTE_COURTE_RATIO

        # Le tour de l'adversaire, l'API muette, les menus : rien à
        # gagner, et `_check_progress` ne compte même pas ces lectures.
        if phase in WAITING_PHASES or phase is Phase.MENUS:
            return long
        # ATTACKING orbe GRISE : le jeu résout l'attaque, on regarde.
        # Orbe à NOUS : il attend quelque chose de nous — c'est le cas du
        # 20/08/2026, où la boucle a attendu la durée maximale pendant que
        # le jeu réclamait des bloqueurs.
        if phase is Phase.ATTACKING:
            return court if snapshot.turn_orb_active else long
        # Un sort sur la pile : orbe grise, c'est à lui de répondre et il
        # peut prendre son temps (l'attente du handler s'y ajoute, le
        # total reste 2 x poll comme avant).
        if phase is Phase.SPELL_STACK:
            return court if snapshot.turn_orb_active else normal
        # Notre tour, un blocage, un mulligan : on vient d'agir.
        return court

    # --- détection de blocage -------------------------------------------
    def _describe_stuck(self, snapshot: GameSnapshot) -> None:
        """L'état complet et une capture : ce qu'il faut pour comprendre après coup."""
        for line in snapshot.summary().splitlines():
            self.report.add(f"    [état] {line}")
        if not self.dry_run:
            path = save_stuck_screen(snapshot.phase.name)
            if path:
                self.report.add(f"    [écran] {path}")

    def _check_progress(self, snapshot: GameSnapshot) -> bool:
        """
        Renvoie False s'il faut arrêter la boucle.

        LA PATIENCE EST UNE DURÉE, PAS UN NOMBRE DE LECTURES. On accumule
        le temps RÉELLEMENT écoulé depuis que la signature s'est figée :
        c'est la seule grandeur qui garde son sens quand le rythme de la
        boucle change. Une itération lourde (une pose, une pile) mange sa
        part du budget, une itération vive la sienne.

        Plancher `DUREE_LECTURE` par lecture : sous une horloge fictive
        (les suites hors ligne) ou avec `--poll 0`, le temps réel d'une
        lecture est nul et le garde-fou ne s'armerait JAMAIS. En jeu ce
        plancher ne mord pas — une lecture coûte toujours ses 2,2 s.
        """
        maintenant = time.time()
        signature = snapshot_signature(snapshot)
        if signature != self._last_signature:
            self._last_signature = signature
            self._immobile = 0.0
            self._stuck = 0
            self._derniere_lecture = maintenant
            return True

        ecart = maintenant - (self._derniere_lecture or maintenant)
        self._derniere_lecture = maintenant
        self._stuck += 1
        avant = self._immobile
        self._immobile += max(ecart, DUREE_LECTURE)

        def franchi(borne: float) -> bool:
            """Le palier vient d'être dépassé par cette lecture-ci."""
            return avant < borne <= self._immobile

        # ESCALADE, DU PLUS INOFFENSIF AU PLUS DESTRUCTEUR.
        # L'annulation ne fait que remettre une carte en main : on la
        # tente en premier, et c'est le cas de blocage le plus fréquent
        # (le jeu attend une cible). Le clic de passe, lui, TERMINE LE
        # TOUR quand c'est le nôtre — le faire d'emblée sacrifierait un
        # tour entier pour un blocage qu'un clic droit aurait levé.
        # Un seul palier par lecture, comme avant.
        if franchi(STUCK_CANCEL_AFTER):
            self._describe_stuck(snapshot)
            self.report.add(
                f"Rien ne bouge depuis {self._immobile:.0f} s "
                f"({self._stuck} lectures) en {snapshot.phase.name} : "
                "tentative d'annulation."
            )
            self._ban_pending_cards(snapshot)
            if not self.dry_run:
                actions.cancel_pending_action(snapshot.window)
        elif franchi(STUCK_PASS_AFTER):
            self._describe_stuck(snapshot)
            self.report.add(
                f"Toujours bloqué en {snapshot.phase.name} après "
                f"{self._immobile:.0f} s : clic de passe "
                "(cela terminera le tour si c'est le nôtre)."
            )
            if not self.dry_run:
                actions.click(*snapshot.window.rel(*actions.TURN_BUTTON_RATIO))
                time.sleep(2.0)
        elif self._immobile >= STUCK_ABORT_AFTER:
            self._describe_stuck(snapshot)
            self.report.reason = (
                f"bloqué en {snapshot.phase.name} depuis {self._immobile:.0f} s "
                "— vérifie la position des boutons et les bandes de zones"
            )
            return False
        return True

    def _ban_pending_cards(self, snapshot: GameSnapshot) -> None:
        """
        La carte que l'annulation va RENVOYER EN MAIN ne doit plus être
        rejouée de la partie.

        06/09/2026 : Banana Blaster (« Play: Deal damage equal to my
        Power to a unit ») posée sans cible → le jeu attend, la carte au
        centre est lue en ATTACKING, 55 s, annulation, la carte revient en
        main… et le round suivant on la rejoue, seize fois, jusqu'à la
        durée maximale. Le `carry` par round ne la voyait pas : `play_card`
        avait conclu « posée », et le mana remonté vidait la mémoire.

        On bannit donc, pour le RESTE DU COMBAT, nos cartes en l'air (bande
        « attack » ou « stack », à nous) quand c'est à NOUS d'agir : c'est
        le jeu qui attend notre clic, pas une attaque en cours.
        """
        if not snapshot.turn_orb_active:
            return
        pending = [c for c in snapshot.attack_row + snapshot.stack if c.local]
        if not pending:
            return
        banned = self._carry.setdefault("banned", set())
        new = sorted({c.code for c in pending} - banned)
        if not new:
            return
        banned.update(new)
        names = ", ".join(next(c.name for c in pending if c.code == code) for code in new)
        self.report.add(f"{names} : bannie(s) pour le reste du combat (pose figée, annulée).")

    # --- démarrage ---------------------------------------------------------
    def wait_for_game_start(self, timeout: float = STARTUP_TIMEOUT):
        """
        Attend que la partie soit réellement en cours, et RENVOIE le premier
        instantané en jeu.

        Indispensable quand la boucle est lancée juste après un clic sur
        « Combat » : le client reste en `Menus` pendant le chargement, et
        confondre ce moment avec une fin de partie faisait rendre la main
        sans jouer un seul tour.

        L'instantané est renvoyé plutôt que jeté : la première itération
        s'en sert directement, ce qui évite une lecture d'état de plus —
        et surtout garantit que l'état sur lequel on a décidé de continuer
        est bien celui qu'on va traiter.
        """
        deadline = time.time() + timeout
        announced = False
        derniere = None

        while time.time() < deadline:
            snapshot = self.reader.stable_snapshot(confirmations=1)
            derniere = snapshot.phase
            if snapshot.phase.in_game:
                self._seen_in_game = True
                self.report.add(f"Partie détectée en phase {snapshot.phase.name}.")
                return snapshot
            if not announced:
                announced = True
                self.report.add(
                    f"En attente du démarrage de la partie "
                    f"(phase {snapshot.phase.name})..."
                )
            if self.dry_run:
                self.report.add("[plan] on n'attend pas le démarrage en mode plan.")
                return None
            time.sleep(self.poll * 2)

        if derniere is Phase.NO_API:
            # « La partie n'a pas démarré » envoie chercher au mauvais
            # endroit : le jeu PEUT être en pleine partie, c'est le client
            # qui ne rapporte rien. Nommer le port évite de relire le code
            # de combat pour une panne d'infrastructure.
            self.report.api_down = True
            self.report.reason = (
                f"API du client injoignable depuis {timeout:.0f} s "
                f"({lor_api.API_BASE}) — le jeu tourne peut-être, "
                f"mais il ne rapporte rien"
            )
        else:
            # L'API a parlé, et elle a dit « menus » : aucune partie n'a
            # été lancée. Rien d'après-combat n'a de sens.
            self.report.never_started = True
            self.report.reason = f"la partie n'a pas démarré en {timeout:.0f} s"
        return None

    # --- boucle -----------------------------------------------------------
    def run(self) -> CombatReport:
        start = time.time()
        digits.USAGE.clear()        # le bilan de lecture des chiffres est par combat
        actions.set_strategy(strategy.DEFAULT)   # relue sur la decklist de CE combat
        self.report.add(
            f"Boucle démarrée{' en mode plan' if self.dry_run else ''} — "
            f"Ctrl+C ou souris dans un coin pour arrêter."
        )

        pending = self.wait_for_game_start()
        if pending is None and not self.dry_run:
            self.report.duration = time.time() - start
            journal.record(self.report, self.config)
            return self.report

        try:
            while True:
                elapsed = time.time() - start
                if elapsed > self.max_duration:
                    self.report.reason = f"durée maximale atteinte ({self.max_duration:.0f} s)"
                    self.report.interrupted = self._seen_in_game
                    break

                snapshot = pending or self.reader.stable_snapshot()
                pending = None
                snapshot = self._reconsider_attacking(snapshot)
                self._note_deck(snapshot)
                self._note_level_ups(snapshot)

                if snapshot.phase is Phase.GAME_OVER:
                    self.report.finished = True
                    self.report.won = snapshot.last_game_won
                    self.report.verdict = "API /game-result"
                    self.report.reason = "partie terminée"
                    break

                if snapshot.phase.in_game:
                    self._seen_in_game = True
                elif snapshot.phase is Phase.MENUS:
                    # Terminal SEULEMENT si une partie a bien eu lieu.
                    if self._seen_in_game:
                        self.report.reason = "retour aux menus"
                        # Le verdict arrive APRÈS le retour aux menus : on
                        # le relit ici plutôt que de rendre un `won` vide.
                        final = getattr(self.reader, "final_result", None)
                        won = final() if callable(final) else None
                        if won is not None:
                            self.report.finished = True
                            self.report.won = won
                            self.report.verdict = "API /game-result (relu aux menus)"
                            self.report.reason = "partie terminée (résultat lu aux menus)"
                        break
                    self.report.add("Encore aux menus, on patiente.")
                    time.sleep(self._attente(snapshot))
                    continue

                # Les phases d'attente sont examinées AVANT la détection de
                # blocage, et volontairement exclues de celle-ci : pendant
                # le tour adverse, un état qui ne change pas est la
                # situation normale, pas un symptôme. Compter ces
                # itérations ferait cliquer « pour débloquer » au milieu du
                # tour de l'adversaire. Le garde-fou ici, c'est la durée
                # maximale.
                if snapshot.phase in WAITING_PHASES:
                    self._turn_open = False
                    if self.dry_run:
                        self.report.add(f"Phase {snapshot.phase.name} : rien à faire, on attendrait.")
                        self.report.reason = "mode plan : phase d'attente"
                        break
                    time.sleep(self._attente(snapshot))
                    continue

                if snapshot.phase is Phase.ATTACKING:
                    # Attente BORNÉE : `_check_progress` remet son compteur
                    # à zéro à chaque changement de plateau, donc une vraie
                    # résolution passe sans encombre. C'est l'immobilité
                    # qui déclenche l'escalade.
                    if self.dry_run:
                        self.report.add("Phase ATTACKING : on attendrait la résolution.")
                        self.report.reason = "mode plan : phase d'attente"
                        break
                    if not self._check_progress(snapshot):
                        break
                    time.sleep(self._attente(snapshot))
                    continue

                if not self._check_progress(snapshot):
                    break

                if snapshot.phase is Phase.MULLIGAN:
                    self._handle_mulligan(snapshot)
                elif snapshot.phase is Phase.BLOCKING:
                    self._handle_blocking(snapshot)
                elif snapshot.phase is Phase.SPELL_STACK:
                    self._handle_spell_stack(snapshot)
                elif snapshot.phase in (Phase.ATTACK_TURN, Phase.DEFEND_TURN, Phase.OUR_TURN):
                    self._handle_our_turn(snapshot)
                else:
                    self.report.add(f"Phase {snapshot.phase.name} non gérée : on attend.")

                if self.dry_run:
                    # En mode plan rien ne change dans le jeu : continuer
                    # rejouerait la même décision en boucle. On rend la
                    # main après une itération d'aiguillage.
                    self.report.reason = "mode plan : une seule itération"
                    break

                time.sleep(self._attente(snapshot))

        except KeyboardInterrupt:
            self.report.reason = "interrompu au clavier"
        except pyautogui.FailSafeException:
            self.report.reason = "interrompu par le coin de l'écran"

        self.report.duration = time.time() - start
        if sum(digits.USAGE.values()):
            self.report.add("Chiffres : " + digits.usage_summary())
        if self.report.rejections:
            top = sorted(self.report.rejections, key=lambda e: -e["n"])[:5]
            self.report.add("Écartées : " + ", ".join(
                f"{e['carte']} ×{e['n']} ({e['motif']})" for e in top
            ) + (" …" if len(self.report.rejections) > 5 else ""))

        # Journalisé même en cas d'interruption : un combat abandonné est
        # une donnée, et c'est justement celle qui révèle les blocages.
        if not self.dry_run:
            journal.record(self.report, self.config)

        return self.report


def main() -> None:
    # AVANT TOUT CE QUI IMPRIME. Le « --- déroulé --- » de `--plan`
    # reverse les lignes « [état] » du rapport, et `GameSnapshot.summary()`
    # y écrit « deck : N cartes, ≤ M à piocher ». Ce « ≤ » n'existe pas en
    # cp1252 : `python combat.py --plan > rapport.txt` mourait dessus. Le
    # `logging` ne le disait pas — stderr survit toujours, c'est le
    # `print` qui tombe. Cf. `sortie_utf8.py`, point unique de la parade.
    sortie_utf8.appliquer()
    parser = argparse.ArgumentParser(description="Boucle de combat autonome (LoR).")
    parser.add_argument("--plan", action="store_true",
                        help="décrire une itération sans rien exécuter")
    parser.add_argument("--spells", action="store_true",
                        help="autoriser les sorts (sans effet hors --prudent : ils le sont déjà)")
    parser.add_argument("--chump", action="store_true",
                        help="autoriser les blocages sacrificiels hors situation létale")
    parser.add_argument("--mulligan", action="store_true",
                        help="forcer le mulligan même sans calibration")
    parser.add_argument("--duree", type=float, default=DEFAULT_MAX_DURATION,
                        help="durée maximale en secondes")
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL,
                        help="rythme des lectures d'état : l'attente vaut 0,3 x "
                             "ce délai quand le jeu attend un geste de nous, "
                             "2 x pendant le tour de l'adversaire")
    parser.add_argument("--base-costs", action="store_true",
                        help="ignorer la gemme à l'écran et décider sur les coûts de card_sets")
    parser.add_argument("--prudent", action="store_true",
                        help="rétablir les restrictions de cartes (cf. actions.CARD_RESTRICTIONS)")
    parser.add_argument("--speed", type=float, default=None,
                        help="échelle des gestes souris (1 = d'origine, 2 = deux fois plus rapide)")
    parser.add_argument("--record", nargs="?", const=True, default=None, metavar="DOSSIER",
                        help="enregistrer tout ce que le bot voit (API + captures) pour "
                             "`replay.py` ; sans dossier : traces/combat_<horodatage>/")
    parser.add_argument("--sans-ocr", action="store_true",
                        help="ne pas charger easyocr : chiffres lus par la forme seule (digits.py)")
    args = parser.parse_args()

    logfile.setup("combat")

    if args.sans_ocr:
        mana.OCR_DISABLED = True
        print("Sans OCR : chiffres lus par la forme seule, easyocr jamais chargé.")

    if args.record:
        import replay
        trace = replay.start_recording(None if args.record is True else args.record, "combat")
        print(f"Trace enregistrée dans {trace} — `python replay.py list {trace}` pour la relire.")

    if args.speed is not None:
        actions.set_gesture_speed(args.speed)

    # Même réglage que `actions.py --base-costs` : la lecture des coûts
    # affichés vit dans actions, la boucle ne fait que la basculer.
    if args.base_costs:
        actions.READ_SCREEN_COSTS = False
        print("Coûts à l'écran désactivés : décision sur les coûts de card_sets.")

    if args.prudent:
        actions.CARD_RESTRICTIONS = True
        print("Mode prudent : sorts filtrés, cartes inconnues et effets non compris écartés.")

    # PRÉ-VOL OCR, avant de toucher à quoi que ce soit. La lecture du mana
    # est indispensable à la pose de cartes : sans easyocr, autant s'arrêter
    # ici plutôt qu'au tour 1 avec une partie déjà entamée.
    if not mana.OCR_DISABLED:
        print("Chargement du modèle OCR...")
    try:
        mana.preload_reader()
    except mana.OCRIndisponible as exc:
        print(f"\nArrêt avant d'entrer en partie.\n{exc}")
        raise SystemExit(1)

    if not args.plan:
        print("Contrôle de la souris dans 5 s — souris dans un coin pour tout arrêter.")
        time.sleep(5)

    loop = CombatLoop(
        allow_spells=args.spells,
        allow_chump=args.chump,
        auto_mulligan=args.mulligan,
        dry_run=args.plan,
        poll=args.poll,
        max_duration=args.duree,
    )
    report = loop.run()

    print("\n--- déroulé ---")
    for entry in report.log:
        print(f"  {entry}")
    print(f"\n{report.summary()}")
    if not args.plan:
        print("Enregistré dans journal.jsonl — `python journal.py` pour le bilan.")


if __name__ == "__main__":
    main()
