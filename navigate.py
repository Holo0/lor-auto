#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
navigate.py

Module de navigation automatisée pour le Défi Hebdomadaire du mode
Path of Champions (PvE) de Legends of Runeterra.

Ce module simule un utilisateur humain via reconnaissance d'image
(opencv) et pilotage souris (pyautogui). Il ne modifie jamais le client
du jeu, n'injecte aucun code et n'interagit avec aucun serveur : il se
contente d'observer l'écran et de cliquer, comme le ferait un joueur.

Ce qui est GÉRÉ ICI :
    - Choix du champion de soutien
    - Sélection des 2 nodes aléatoires (via un dossier d'images de nodes)
    - Détection et clic sur le boss final ou intermédiaire

Ce qui N'EST PAS géré ici (déjà pris en charge ailleurs dans le projet) :
    - Entrée dans Path of Champions / Défis Hebdomadaires
    - Choix de l'aventure
    - Choix du champion principal
    - Déroulement du combat (voir lor_battle.py)

Prérequis :
    - Dossier ASSETS_DIR (adventure_navigation.py) contenant :
        support_champion.png, select_button.png, voyage_button.png,
        final_boss.png, mid_boss.png, combat_button.png
    - Un dossier dédié (node_folder) contenant UNIQUEMENT les images
      des nodes aléatoires possibles (node_type_1.png, node_type_2.png, ...)
"""

import logging

from adventure_navigation import TEMPLATES
from click_utils import (
    click_button,
    click_image,
    find_first_match_in_folder,
    safe_click,
    wait_for_image,
)

# ============================================================
# CONFIGURATION
# ============================================================

# Nombre de nodes aléatoires à traverser avant le boss (fixé par la spec).
NUMBER_OF_RANDOM_NODES = 1

# Nombre de tentatives par étape en cas d'échec de détection.
DEFAULT_RETRIES = 3

DEFAULT_TIMEOUT = 10


# ============================================================
# ÉTAPE 1 : CHAMPION DE SOUTIEN
# ============================================================

def choose_support_champion(retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Détecte et clique sur le champion de soutien, puis confirme
    la sélection via 'select_button'.

    Retourne True si les deux étapes ont réussi, False sinon.
    """
    logging.info("Étape : sélection du champion de soutien.")

    for attempt in range(1, retries + 1):
        logging.info(f"Tentative {attempt}/{retries} : détection du champion de soutien.")

        if not click_image(TEMPLATES["support_champion"], timeout=timeout):
            logging.warning("Champion de soutien non détecté, nouvelle tentative...")
            continue

        if not click_button("voyage_button", timeout=timeout):
            logging.warning("Bouton 'voyage_button' non détecté après sélection du champion.")
            continue

        if not click_button("event_option", timeout=timeout):
            logging.warning("Bouton 'event_option' non détecté après voyage vers champion.")
            continue
        
        if not click_button("select_button", timeout=timeout):
            logging.warning("Bouton 'select_button' non détecté après voyage vers champion.")
            continue
        logging.info("Champion de soutien sélectionné avec succès.")
        return True

    logging.error("Échec de la sélection du champion de soutien après plusieurs tentatives.")
    return False


# ============================================================
# ÉTAPE 2 : NODES ALÉATOIRES
# ============================================================

def _handle_single_node(node_folder, retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Gère un seul node aléatoire : détecte quelle image du dossier
    correspond à l'écran, clique dessus, puis clique sur 'voyage_button'.

    Retourne True en cas de succès, False sinon.
    """
    for attempt in range(1, retries + 1):
        logging.info(f"Tentative {attempt}/{retries} : recherche d'un node dans '{node_folder}'.")

        image_path, coords = find_first_match_in_folder(node_folder)
        if not image_path:
            logging.warning("Aucun node reconnu à l'écran, nouvelle tentative...")
            continue

        x, y = coords
        if not safe_click(x, y):
            logging.warning(f"Échec du clic sur le node '{image_path}'.")
            continue

        logging.info(f"Node cliqué : {image_path}")

        if not click_button("voyage_button", timeout=timeout):
            logging.warning("Bouton 'voyage_button' non détecté après clic sur le node.")
            continue

        logging.info("Déplacement vers le node confirmé.")
        
        if not click_button("quit_button", timeout=timeout):
            logging.warning("Bouton 'quit_button' non détecté après ouverture node.")
            continue
        return True

    logging.error(f"Échec de la gestion du node après {retries} tentatives.")
    return False


def handle_random_nodes(node_folder, number_of_nodes=NUMBER_OF_RANDOM_NODES,
                         retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Gère la sélection successive des nodes aléatoires du Défi Hebdomadaire.

    node_folder : dossier contenant UNIQUEMENT les images des nodes possibles
                  (node_type_1.png, node_type_2.png, etc.)

    Retourne True si tous les nodes ont été traversés avec succès.
    """
    logging.info(f"Étape : gestion de {number_of_nodes} node(s) aléatoire(s).")

    for i in range(1, number_of_nodes + 1):
        logging.info(f"--- Node {i}/{number_of_nodes} ---")
        if not _handle_single_node(node_folder, retries=retries, timeout=timeout):
            logging.error(f"Échec au node {i}/{number_of_nodes}. Arrêt de la navigation.")
            return False

    logging.info("Tous les nodes aléatoires ont été traversés avec succès.")
    return True


# ============================================================
# ÉTAPE 3 : BOSS FINAL OU INTERMÉDIAIRE
# ============================================================

def handle_final_or_mid_boss(retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Détecte lequel de 'final_boss' ou 'mid_boss' apparaît à l'écran,
    clique dessus, puis clique sur 'combat_button' pour lancer le combat.

    Le déroulement du combat lui-même n'est PAS géré ici.

    Retourne True en cas de succès, False sinon.
    """
    logging.info("Étape : détection du boss (final ou intermédiaire).")

    for attempt in range(1, retries + 1):
        logging.info(f"Tentative {attempt}/{retries} : recherche du boss.")

        boss_key = None
        coords = wait_for_image(TEMPLATES["enemy_node"], timeout=timeout)
        if coords:
            boss_key = "final_boss"
        else:
            coords = wait_for_image(TEMPLATES["secondary_enemy_node"], timeout=timeout)
            if coords:
                boss_key = "mid_boss"

        if not boss_key:
            logging.warning("Ni 'final_boss' ni 'mid_boss' détecté, nouvelle tentative...")
            continue

        x, y = coords
        if not safe_click(x, y):
            logging.warning(f"Échec du clic sur '{boss_key}'.")
            continue

        logging.info(f"Boss détecté et cliqué : {boss_key}")

        if not click_button("combat_button", timeout=timeout):
            logging.warning("Bouton 'combat_button' non détecté après sélection du boss.")
            continue

        logging.info("Combat lancé (délégué au module de combat).")
        return True

    logging.error("Échec de la détection/sélection du boss après plusieurs tentatives.")
    return False


# ============================================================
# FONCTION PRINCIPALE
# ============================================================

def navigate_weekly_challenge(node_folder):
    """
    Orchestre la navigation complète du Défi Hebdomadaire :
        1. Choix du champion de soutien
        2. Sélection des 2 nodes aléatoires
        3. Détection et clic sur le boss (final ou intermédiaire)

    node_folder : dossier dédié contenant uniquement les images de nodes
                  aléatoires possibles (ex: "assets/nodes").

    Retourne True si toute la navigation s'est déroulée avec succès,
    False si une étape a échoué de façon définitive.
    """
    logging.info("=== Début de la navigation du Défi Hebdomadaire ===")

    if not choose_support_champion():
        logging.error("Navigation interrompue : échec du choix du champion de soutien.")
        return False

    if not handle_random_nodes(node_folder):
        logging.error("Navigation interrompue : échec de la gestion des nodes aléatoires.")
        return False

    if not handle_final_or_mid_boss():
        logging.error("Navigation interrompue : échec de la détection du boss.")
        return False

    logging.info("=== Navigation du Défi Hebdomadaire terminée avec succès ===")
    return True