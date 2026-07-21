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
    - Sélection des nodes aléatoires (via un dossier d'images de nodes)
    - Détection du scénario du défi (avec ou sans boss intermédiaire)
    - Détection et clic sur le boss final ou intermédiaire

Ce qui N'EST PAS géré ici (déjà pris en charge ailleurs dans le projet) :
    - Entrée dans Path of Champions / Défis Hebdomadaires
    - Choix de l'aventure
    - Choix du champion principal
    - Déroulement du combat lui-même (voir lor_battle.py)

--------------------------------------------------------------------
Les DEUX scénarios possibles du Défi Hebdomadaire
--------------------------------------------------------------------

Cas 1 - AVEC boss intermédiaire :
    champion de soutien -> Node 1 -> Boss intermédiaire (combat) ->
    Node 2 -> Boss final (combat)

Cas 2 - SANS boss intermédiaire :
    champion de soutien -> Node 1 -> Node 2 -> Boss final (combat)

Le script ne sait pas à l'avance dans quel cas il se trouve : après le
Node 1, il observe l'écran pour déterminer si c'est le boss
intermédiaire ou un nouveau node aléatoire qui apparaît, et adapte la
suite de la navigation en conséquence.

Différence de traitement importante entre les deux boss :
    - Le combat du boss FINAL est délégué à l'appelant (comme avant) :
      ce module clique juste sur le boss puis sur 'combat_button', et
      s'arrête là.
    - Le combat du boss INTERMÉDIAIRE doit au contraire être résolu ICI
      (via lor_battle.try_combat), car la navigation doit reprendre
      juste après (Node 2) : on ne peut pas rendre la main à l'appelant
      au milieu du parcours.

Prérequis :
    - Dossier ASSETS_DIR (adventure_navigation.py) contenant :
        support_champion_node.png, select_button.png, voyage_button.png,
        final_boss.png, secondary_enemy_node.png, combat_button.png, quit_button.png
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

    Retourne True si les étapes ont réussi, False sinon.
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

def _handle_single_node(node_folder, known_match=None, retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Gère un seul node aléatoire : détecte quelle image du dossier
    correspond à l'écran, clique dessus, puis clique sur 'voyage_button'
    et 'quit_button'.

    known_match : tuple optionnel (image_path, (x, y)) si le node a déjà
                  été détecté en amont (ex: par _detect_next_step), pour
                  éviter un scan redondant de l'écran. N'est utilisé que
                  pour la première tentative ; en cas d'échec, les
                  tentatives suivantes re-scannent normalement.

    Retourne True en cas de succès, False sinon.
    """
    for attempt in range(1, retries + 1):
        logging.info(f"Tentative {attempt}/{retries} : recherche d'un node dans '{node_folder}'.")

        if known_match is not None:
            image_path, coords = known_match
            known_match = None  # ne sert qu'une fois
        else:
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


# ============================================================
# ÉTAPE 2bis : DÉTECTION DU SCÉNARIO (avec ou sans boss intermédiaire)
# ============================================================

def _detect_next_step(node_folder, timeout=DEFAULT_TIMEOUT):
    """
    Après le Node 1, observe l'écran pour déterminer lequel des deux
    scénarios est en cours :
        - le boss intermédiaire ('secondary_enemy_node') est visible
        - ou un nouveau node aléatoire (du dossier node_folder) est visible

    La détection du boss intermédiaire est prioritaire : on la teste en
    premier, puis on scanne le dossier de nodes si rien n'est trouvé.

    Retourne un tuple (step_type, image_path, (x, y)) où step_type vaut
    "secondary_enemy_node" ou "node". Retourne (None, None, None) si rien n'est
    détecté dans le délai imparti.
    """
    logging.info("Détection du scénario du défi (boss intermédiaire ou 2ème node)...")

    coords = wait_for_image(TEMPLATES["secondary_enemy_node"], timeout=timeout)
    if coords:
        logging.info("Scénario détecté : boss intermédiaire présent.")
        return "mid_boss", TEMPLATES["secondary_enemy_node"], coords

    image_path, coords = find_first_match_in_folder(node_folder)
    if image_path:
        logging.info("Scénario détecté : 2ème node aléatoire (pas de boss intermédiaire).")
        return "node", image_path, coords

    logging.warning("Ni boss intermédiaire ni node détecté.")
    return None, None, None


# ============================================================
# ÉTAPE 3 : ENGAGER UN BOSS (intermédiaire ou final)
# ============================================================

def _engage_boss(boss_key, coords=None, retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Clique sur le boss désigné (boss_key = "secondary_enemy_node" ou "final_boss")
    puis sur 'combat_button' pour lancer le combat.

    coords : coordonnées déjà connues (issues de _detect_next_step), le
             cas échéant, pour éviter un scan redondant à la première
             tentative.

    Ne gère PAS le déroulement du combat lui-même : voir
    _resolve_intermediate_combat pour le cas du boss intermédiaire, et
    le module appelant (lor_battle.py) pour le boss final.

    Retourne True en cas de succès, False sinon.
    """
    template_path = TEMPLATES[boss_key]
    logging.info(f"Étape : engagement du '{boss_key}'.")

    for attempt in range(1, retries + 1):
        logging.info(f"Tentative {attempt}/{retries} : recherche de '{boss_key}'.")

        current_coords = coords if coords is not None else wait_for_image(template_path, timeout=timeout)
        coords = None  # ne réutiliser les coordonnées connues qu'une fois

        if not current_coords:
            logging.warning(f"'{boss_key}' non détecté, nouvelle tentative...")
            continue

        x, y = current_coords
        if not safe_click(x, y):
            logging.warning(f"Échec du clic sur '{boss_key}'.")
            continue

        logging.info(f"'{boss_key}' cliqué.")

        if not click_button("voyage_button", timeout=timeout):
            logging.warning("Bouton 'voyage_button' non détecté après sélection du boss.")
            continue

        if not click_button("combat_button", timeout=timeout):
            logging.warning("Bouton 'combat_button' non détecté après sélection du boss.")
            continue

        logging.info(f"Combat contre '{boss_key}' lancé.")
        return True

    logging.error(f"Échec de l'engagement de '{boss_key}' après plusieurs tentatives.")
    return False


def _resolve_intermediate_combat(node_coords):
    """
    Résout le combat contre le boss intermédiaire en déléguant au module
    lor_battle (try_combat), puis attend que la carte redevienne
    navigable avant de rendre la main.

    Contrairement au boss final, on ne peut pas s'arrêter ici : la
    navigation doit reprendre ensuite vers le 2ème node, donc ce module
    a besoin d'attendre la fin effective du combat.

    Retourne True si le combat a été résolu sans erreur, False sinon.
    """
    # Import local pour éviter tout couplage/import circulaire inutile
    # tant que le combat intermédiaire n'est pas requis.
    from lor_battle import try_combat

    logging.info("Résolution du combat contre le boss intermédiaire...")
    try:
        try_combat(*node_coords)
        logging.info("Combat contre le boss intermédiaire terminé.")
        return True
    except Exception as exc:
        logging.error(f"Erreur lors de la résolution du combat intermédiaire : {exc}")
        return False


# ============================================================
# FONCTION PRINCIPALE
# ============================================================

def navigate_weekly_challenge(node_folder):
    """
    Orchestre la navigation complète du Défi Hebdomadaire, en gérant les
    deux scénarios possibles :

        Cas 1 (avec boss intermédiaire) :
            champion de soutien -> Node 1 -> boss intermédiaire (combat)
            -> Node 2 -> boss final (combat délégué à l'appelant)

        Cas 2 (sans boss intermédiaire) :
            champion de soutien -> Node 1 -> Node 2 -> boss final
            (combat délégué à l'appelant)

    node_folder : dossier dédié contenant uniquement les images de nodes
                  aléatoires possibles (ex: "assets/nodes").

    Retourne True si toute la navigation s'est déroulée avec succès,
    False si une étape a échoué de façon définitive.
    """
    logging.info("=== Début de la navigation du Défi Hebdomadaire ===")

    # # --- Étape 1 : champion de soutien ---
    if not choose_support_champion():
        logging.error("Navigation interrompue : échec du choix du champion de soutien.")
        return False

    # --- Étape 2 : Node 1 (toujours présent, quel que soit le scénario) ---
    logging.info("--- Node 1/2 ---")
    if not _handle_single_node(node_folder):
        logging.error("Navigation interrompue : échec au Node 1.")
        return False

    # --- Étape 3 : détection du scénario ---
    step_type, image_path, coords = _detect_next_step(node_folder)

    if step_type == "mid_boss":
        # Cas 1 : boss intermédiaire
        if not _engage_boss("secondary_enemy_node", coords=coords):
            logging.error("Navigation interrompue : échec de l'engagement du boss intermédiaire.")
            return False

        if not _resolve_intermediate_combat(coords):
            logging.error("Navigation interrompue : échec de la résolution du combat intermédiaire.")
            return False

        logging.info("--- Node 2/2 (après boss intermédiaire) ---")
        if not _handle_single_node(node_folder):
            logging.error("Navigation interrompue : échec au Node 2.")
            return False

    elif step_type == "node":
        # Cas 2 : pas de boss intermédiaire, 2ème node directement
        logging.info("--- Node 2/2 (sans boss intermédiaire) ---")
        if not _handle_single_node(node_folder, known_match=(image_path, coords)):
            logging.error("Navigation interrompue : échec au Node 2.")
            return False

    else:
        logging.error(
            "Navigation interrompue : impossible de déterminer le scénario "
            "(ni boss intermédiaire, ni node détecté après le Node 1)."
        )
        return False

    # --- Étape 4 : boss final (toujours présent, combat délégué à l'appelant) ---
    if not _engage_boss("final_boss"):
        logging.error("Navigation interrompue : échec de l'engagement du boss final.")
        return False

    logging.info("=== Navigation du Défi Hebdomadaire terminée avec succès ===")
    return True