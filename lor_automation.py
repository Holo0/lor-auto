#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lor_automation.py

Point d'entrée : navigue dans le défi hebdomadaire et enchaîne les
combats.

Le combat lui-même est joué par combat.CombatLoop, atteint via
navigate.py -> lor_battle.try_combat.
"""

import logging
import time

import pyautogui

from navigate import navigate_weekly_challenge

# ============================================================
# CONFIGURATION
# ============================================================

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Le dossier "assets/nodes" doit contenir UNIQUEMENT les images des nodes
# aléatoires possibles (normal_node.png, normal_node1.png, ...), séparées
# des boutons et des boss pour éviter les faux positifs de matching.
NODES_DIR = "assets/nodes"


def main():
    logging.info("Lancement du bot Legends of Runeterra...")
    time.sleep(1)

    navigate_weekly_challenge(NODES_DIR)

    logging.info("Fin de l'aventure.")


if __name__ == "__main__":
    main()
