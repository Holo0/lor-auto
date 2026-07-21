#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
import pyautogui

# Modules externes (vision)
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

# ============================================================
# NAVIGATION DANS L’AVENTURE
# ============================================================

def run_adventure_navigation_loop():
    logging.info("Début de la navigation dans l'aventure...")

# ============================================================
# MAIN
# ============================================================

def main():
    logging.info("Lancement du bot Legends of Runeterra...")
    time.sleep(1)

    # Aller au défi mensuel
    # click_button("monthly_challenge")
    # click_button("active_encounter")

    # # Choisir le champion
    # click_button("first_champion")

    # # Lancer l’aventure
    # click_button("use_attempt")

    # Navigation
    # Le dossier "assets/nodes" doit contenir UNIQUEMENT les images des
    # nodes aléatoires possibles (node_type_1.png, node_type_2.png, ...),
    # séparées des boutons/boss pour éviter les faux positifs de matching.
    navigate_weekly_challenge("assets/nodes")

    logging.info("Fin de l'aventure.")

if __name__ == "__main__":
    main()