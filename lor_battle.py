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

from click_utils import click_button, human_click


def _handle_post_combat():
    """
    Gère l'écran de fin de combat : détection de 'after_combat' puis clic
    sur 'continue_button' après un court délai. Retourne True si les deux
    écrans ont été détectés et cliqués avec succès.
    """
    if not click_button("after_combat", timeout=20):
        logging.warning("Image 'after_combat' non détectée après la fin du combat.")
        return False

    logging.info("Écran post-combat détecté et cliqué.")
    time.sleep(3)

    if not click_button("continue_button", timeout=5):
        logging.warning("Deuxième image 'continue_button' non détectée après le délai.")
        return False

    logging.info("Deuxième clic post-combat effectué après 3 secondes.")
    return True


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


def try_combat(node_x, node_y, **options):
    """
    Joue le combat, puis gère les éventuels réessais ('retry') jusqu'à
    validation.
    """
    report = play_combat(**options)

    if not _handle_post_combat():
        return report

    while click_button("retry", timeout=5):
        logging.info("Bouton 'Réessayer' cliqué.")
        time.sleep(3)
        human_click(node_x, node_y)
        time.sleep(random.uniform(1.5, 2.5))

        if not click_button("combat_button"):
            continue

        logging.info("Bouton Combat cliqué. Début du combat.")
        report = play_combat(**options)
        _handle_post_combat()

    logging.info("Aucun nouveau 'Réessayer' détecté, fin de la boucle de combat.")
    return report
