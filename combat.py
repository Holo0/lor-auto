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
ne doit jamais tourner à vide indéfiniment. Quatre protections :

1. COIN DE L'ÉCRAN — pyautogui.FAILSAFE reste actif : amener la souris
   dans un coin lève une exception et arrête tout, immédiatement.

2. DURÉE MAXIMALE — la boucle s'arrête au bout de `--duree` secondes,
   même si la partie n'est pas finie. Un combat LoR dépasse rarement
   quinze minutes ; au-delà, quelque chose ne va pas.

3. DÉTECTION DE BLOCAGE — si l'état du jeu ne change plus pendant
   plusieurs itérations, la boucle le remarque, tente de débloquer en
   passant, puis abandonne. Sans ça, un bouton mal placé fait tourner le
   script pour rien jusqu'à la limite de durée.

4. MULLIGAN MANUEL PAR DÉFAUT — la position du bouton de validation du
   mulligan n'est pas vérifiée (cf. actions.MULLIGAN_CONFIRM_RATIO). La
   boucle attend donc que tu fasses le mulligan toi-même, sauf si tu
   passes `--mulligan`.

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
from dataclasses import dataclass, field
from typing import Optional

import pyautogui

import actions
from game_state import GameSnapshot, GameStateReader, Phase

LOGGER = logging.getLogger(__name__)

# Phases où l'on n'a rien à faire qu'attendre.
WAITING_PHASES = (Phase.OPPONENT_TURN, Phase.ATTACKING, Phase.NO_API)

DEFAULT_POLL = 1.0
DEFAULT_MAX_DURATION = 900.0      # 15 minutes
STUCK_LIMIT = 25                  # itérations sans changement avant réaction
STUCK_ABORT = 40


@dataclass
class CombatReport:
    """Ce qui s'est passé pendant la boucle."""

    finished: bool = False
    won: Optional[bool] = None
    reason: str = ""
    turns_played: int = 0
    cards_played: int = 0
    attacks: int = 0
    blocks: int = 0
    duration: float = 0.0
    log: list = field(default_factory=list)

    def add(self, message: str) -> None:
        self.log.append(message)
        LOGGER.info(message)

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


def snapshot_signature(snapshot: GameSnapshot) -> tuple:
    """
    Empreinte de l'état visible, pour détecter qu'on tourne en rond.

    On y met la phase et le CONTENU de chaque zone, pas seulement les
    tailles : une carte qui se déplace sans que les comptes changent est
    un vrai progrès, et on ne veut pas la prendre pour une stagnation.
    """
    return (
        snapshot.phase,
        tuple(sorted(c.code for c in snapshot.hand)),
        tuple(sorted(c.code for c in snapshot.board)),
        tuple(sorted(c.code for c in snapshot.attack_row)),
        tuple(sorted(c.code for c in snapshot.enemy_attack_row)),
        tuple(sorted(c.code for c in snapshot.enemy_board)),
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

        self.report = CombatReport()
        self._last_signature = None
        self._stuck = 0

    # --- handlers par phase --------------------------------------------
    def _handle_our_turn(self, snapshot: GameSnapshot) -> None:
        log = actions.play_turn(
            self.reader,
            snapshot=snapshot,
            allow_spells=self.allow_spells,
            finish_turn=True,
            dry_run=self.dry_run,
        )
        self.report.log.extend(log.entries)
        self.report.turns_played += 1
        for entry in log.entries:
            if "carte(s) posée(s)" in entry:
                self.report.cards_played += int(entry.split()[0])
            if "unité(s) engagée(s)" in entry and not entry.startswith("0"):
                self.report.attacks += 1

    def _handle_blocking(self, snapshot: GameSnapshot) -> None:
        done, _, log = actions.execute_blocks(
            self.reader, snapshot, allow_chump=self.allow_chump, dry_run=self.dry_run
        )
        self.report.log.extend(log.entries)
        if done:
            self.report.blocks += 1

    def _handle_mulligan(self, snapshot: GameSnapshot) -> None:
        if not self.auto_mulligan:
            self.report.add(
                "Mulligan : à toi de jouer (--mulligan pour l'automatiser, "
                "mais la position du bouton de validation n'est pas vérifiée)."
            )
            time.sleep(2.0)
            return
        log = actions.do_mulligan(self.reader, snapshot, dry_run=self.dry_run)
        self.report.log.extend(log.entries)
        time.sleep(3.0)

    def _handle_spell_stack(self, snapshot: GameSnapshot) -> None:
        # On ne répond pas aux sorts : on passe. Ne rien faire figerait la
        # partie, puisque le jeu attend une réponse.
        self.report.add("Sort sur la pile : on passe.")
        if not self.dry_run:
            actions.click(*snapshot.window.rel(*actions.TURN_BUTTON_RATIO))
            time.sleep(2.0)

    # --- détection de blocage -------------------------------------------
    def _check_progress(self, snapshot: GameSnapshot) -> bool:
        """Renvoie False s'il faut arrêter la boucle."""
        signature = snapshot_signature(snapshot)
        if signature != self._last_signature:
            self._last_signature = signature
            self._stuck = 0
            return True

        self._stuck += 1
        if self._stuck == STUCK_LIMIT:
            self.report.add(
                f"Rien ne bouge depuis {STUCK_LIMIT} lectures en {snapshot.phase.name} : "
                "tentative de déblocage par un clic de passe."
            )
            if not self.dry_run:
                actions.click(*snapshot.window.rel(*actions.TURN_BUTTON_RATIO))
                time.sleep(2.0)
        elif self._stuck >= STUCK_ABORT:
            self.report.reason = (
                f"bloqué en {snapshot.phase.name} — vérifie la position des boutons "
                "et les bandes de zones"
            )
            return False
        return True

    # --- boucle -----------------------------------------------------------
    def run(self) -> CombatReport:
        start = time.time()
        self.report.add(
            f"Boucle démarrée{' en mode plan' if self.dry_run else ''} — "
            f"Ctrl+C ou souris dans un coin pour arrêter."
        )

        try:
            while True:
                elapsed = time.time() - start
                if elapsed > self.max_duration:
                    self.report.reason = f"durée maximale atteinte ({self.max_duration:.0f} s)"
                    break

                snapshot = self.reader.stable_snapshot()

                if snapshot.phase is Phase.GAME_OVER:
                    self.report.finished = True
                    self.report.won = snapshot.last_game_won
                    self.report.reason = "partie terminée"
                    break

                if snapshot.phase is Phase.MENUS:
                    self.report.reason = "retour aux menus"
                    break

                # Les phases d'attente sont examinées AVANT la détection de
                # blocage, et volontairement exclues de celle-ci : pendant
                # le tour adverse, un état qui ne change pas est la
                # situation normale, pas un symptôme. Compter ces
                # itérations ferait cliquer « pour débloquer » au milieu du
                # tour de l'adversaire. Le garde-fou ici, c'est la durée
                # maximale.
                if snapshot.phase in WAITING_PHASES:
                    if self.dry_run:
                        self.report.add(f"Phase {snapshot.phase.name} : rien à faire, on attendrait.")
                        self.report.reason = "mode plan : phase d'attente"
                        break
                    time.sleep(self.poll * 2)
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

                time.sleep(self.poll)

        except KeyboardInterrupt:
            self.report.reason = "interrompu au clavier"
        except pyautogui.FailSafeException:
            self.report.reason = "interrompu par le coin de l'écran"

        self.report.duration = time.time() - start
        return self.report


def main() -> None:
    parser = argparse.ArgumentParser(description="Boucle de combat autonome (LoR).")
    parser.add_argument("--plan", action="store_true",
                        help="décrire une itération sans rien exécuter")
    parser.add_argument("--spells", action="store_true", help="autoriser les sorts")
    parser.add_argument("--chump", action="store_true",
                        help="autoriser les blocages sacrificiels hors situation létale")
    parser.add_argument("--mulligan", action="store_true",
                        help="automatiser le mulligan (bouton non vérifié)")
    parser.add_argument("--duree", type=float, default=DEFAULT_MAX_DURATION,
                        help="durée maximale en secondes")
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL,
                        help="délai entre deux lectures d'état")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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


if __name__ == "__main__":
    main()
