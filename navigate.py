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
    - Reconnaissance de l'écran courant (`where_are_we`) et retour à un
      écran connu quand le jeu en affiche un autre (`back_to_known_screen`)
    - Entrée dans le Défi Hebdomadaire depuis la carte du monde, ou depuis
      n'importe quel écran connu (`enter_challenge_attempt`)
    - Parcours de la carte (`run_adventure`) : rejoindre le prochain nœud
      marqué par le jeu, puis faire ce que ce nœud propose — combat,
      événement, choix — jusqu'à ce qu'il n'y ait plus rien à rejoindre

Ce qui N'EST PAS géré ici (déjà pris en charge ailleurs dans le projet) :
    - Déroulement du combat lui-même (voir lor_battle.py)
    - L'ENCHAÎNEMENT des tentatives (voir challenges.py) : ce module
      conduit UNE aventure, du menu au boss final, et rien de plus.

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
    - Dossier assets/nodes/ : les images des nœuds ORDINAIRES, dont
      l'aspect varie, toutes mesurées sur une même capture ; le nœud
      retenu est LE PLUS À GAUCHE des candidats (cf. NODES_DIR).

Deux entrées, et il faut savoir laquelle appeler :
    - `enter_weekly_challenge()` part TOUJOURS de la carte du monde.
      C'est le chemin long, celui d'un lancement à froid.
    - `enter_challenge_attempt()` part de l'écran où l'on est. À la fin
      d'une aventure, le jeu rend l'écran de SÉLECTION DU CHAMPION et non
      la carte du monde : la tentative suivante s'y enchaîne directement,
      et c'est ce qui rend possible la boucle de challenges.py.
    Les deux partagent la même table d'étapes (STEPS_FROM), donc elles ne
    peuvent pas divergerr.

Pauses humaines :
    Toutes les fonctions de clic/détection utilisées ici (click_button,
    click_image, safe_click, wait_for_image, locate_node)
    appliquent déjà des délais aléatoires définis dans click_utils.py
    (DELAY_AFTER_CLICK, DELAY_AFTER_TRANSITION, DELAY_BEFORE_SEARCH).
    On y ajoute ici DELAY_BETWEEN_RETRIES entre deux tentatives d'une
    même étape, pour ne pas re-scanner l'écran en boucle serrée.
"""

import argparse
import logging
import math
import time

from enum import Enum
from pathlib import Path

import cv2

# `_capture_screen_bgr` est privé de nom mais public d'usage : c'est LA
# capture d'écran du projet côté navigation, et `where_are_we` en a besoin
# pour juger tous ses repères sur la même image.
import champions
import marqueur_joueur
from adventure_navigation import (
    MATCH_THRESHOLD,
    NODE_EXCLUDE_DISTANCE,
    TEMPLATES,
    _capture_screen_bgr,
    best_match,
    find_nodes_in_folder,
    pick_next_node,
)
from click_utils import (
    click_button,
    park_mouse,
    safe_click,
    topmost_match,
    wait_for_image,
    human_delay,
    DELAY_AFTER_TRANSITION,
    DELAY_BEFORE_SEARCH,
    DELAY_BETWEEN_RETRIES,
)

# ============================================================
# CONFIGURATION
# ============================================================

# Nombre de tentatives par étape en cas d'échec de détection.
DEFAULT_RETRIES = 3

DEFAULT_TIMEOUT = 10

# Après le dernier clic d'entrée dans le défi ('use_attempt'), le jeu
# charge la partie avant que le nœud du champion de soutien soit
# cliquable. Valeur donnée par observation directe du jeu — à ajuster si
# le chargement est plus lent ou plus rapide chez toi.
CHALLENGE_LOAD_DELAY = 5.0


# Boutons qu'on s'autorise à cliquer pour FERMER ce qui traîne à l'écran.
# Aucun d'eux ne lance quoi que ce soit : ni « Voyage », ni « Combat », ni
# « Réessayer » (celui-là relance un combat, et c'est le travail de
# lor_battle.try_combat). C'est cette liste qui rend
# `back_to_known_screen` sûre à appeler dans le doute.
DISMISS_BUTTONS = (
    "continue_button_after_combat",
    "continue_button",
    "quit_button",
)

# Au-delà, on cesse de chercher un écran connu. Deux minutes couvrent les
# écrans de récompense les plus bavards.
RECOVERY_TIMEOUT = 120.0


# ============================================================
# OÙ SOMMES-NOUS ?
# ============================================================

class Screen(Enum):
    """
    Les écrans que la boucle sait reconnaître.

    Quatre sont des points d'ENTRÉE — on peut y lancer une tentative.
    ADVENTURE, lui, dit le contraire : une aventure est déjà en cours,
    donc il n'y a rien à lancer, seulement à reprendre.

    ATTEMPT est un REPLI, pas un raccourci : voir SCREEN_ANCHORS.
    """

    CHAMPION = "sélection du champion"
    ATTEMPT = "tentative à confirmer"
    RESUME = "aventure à reprendre"
    LIST = "liste des défis actifs"
    WORLD_MAP = "carte du monde"
    ADVENTURE = "aventure en cours"
    UNKNOWN = "écran inconnu"


# (écran, repères qui le SIGNENT). Un seul repère quand c'est possible :
# plus il y en a, plus il y a d'occasions de se tromper.
#
# L'ORDRE EST CELUI DES GESTES D'EWAN, PAS CELUI DE L'AVANCEMENT. Le
# champion passe AVANT le bouton de lancement, alors que les deux sont
# visibles en même temps sur le même écran. C'est délibéré : sur cet
# écran, ce qu'il fait — à chaque fois, victoire ou défaite — c'est
# sélectionner le premier champion PUIS lancer. Tester `use_attempt`
# d'abord ferait reconnaître « il ne reste qu'un clic » et sauter la
# sélection ; si le jeu exige un champion, le bouton ne répond pas, la
# boucle croit qu'il n'y a plus de tentative et la session s'arrête pour
# rien.
#
# Screen.ATTEMPT reste utile en REPLI : le bouton est là mais la vignette
# du champion n'est plus reconnaissable (animation, champion déjà
# sélectionné et grisé). Alors, et alors seulement, on se contente de
# confirmer.
#
# ADVENTURE EST TESTÉ EN DERNIER, et c'est volontaire. Ses repères sont
# les plus nombreux, donc les plus susceptibles d'un faux positif : on ne
# conclut « une aventure est en cours » qu'après avoir écarté les quatre
# écrans d'entrée, qui sont chacun signés par un bouton unique. Mesuré le
# 21/08/2026 : sur la carte d'aventure, aucun des quatre ne correspond —
# c'est ce qui rend ce dernier recours sans danger.
# RESUME PASSE AVANT TOUT (06/11/2026). Sur le panneau d'un défi dont
# l'aventure est en cours, `use_attempt` note 0.68 : sous le seuil, mais
# c'est le même cadre de bouton à la même place, et le départager par
# l'ordre coûte moins cher que de l'espérer. Son libellé, lui, est franc
# — 1.00 contre ≤ 0.33 partout ailleurs.
SCREEN_ANCHORS = (
    (Screen.RESUME, ("reprendre_aventure",)),
    (Screen.CHAMPION, ("first_champion",)),
    (Screen.ATTEMPT, ("use_attempt",)),
    (Screen.LIST, ("active_encounter",)),
    (Screen.WORLD_MAP, ("monthly_challenge",)),
)

# L'aventure se reconnaît à ses repères de nœuds, testés en DERNIER :
# ils sont plusieurs et donc plus exposés au faux positif, alors que
# chaque écran d'entrée est signé par un bouton unique. Ici la question
# posée est seulement « suis-je sur une carte ? » — n'importe quel repère
# de nœud y répond, même approximativement.
ADVENTURE_ANCHORS = ("support_champion", "secondary_enemy_node", "final_boss",
                     "enemy_node", "normal_node")


class Entry(Enum):
    """
    Les issues d'une demande de tentative.

    RESUMED ne consomme RIEN : une aventure était déjà commencée, on la
    reprend. La distinction compte pour les garde-fous de challenges.py —
    brûler des tentatives hebdomadaires et reprendre une partie en cours
    n'ont pas le même prix.
    """

    LAUNCHED = "tentative lancée"
    RESUMED = "aventure déjà en cours, on la reprend"
    NO_ATTEMPT_LEFT = "plus de tentative disponible"
    LOST = "écran inconnu au moment d'entrer"


def where_are_we(threshold=MATCH_THRESHOLD, screen=None) -> Screen:
    """
    Reconnaît l'écran courant, SANS attendre et sans rien cliquer.

    UNE SEULE CAPTURE pour tous les repères : c'est moins de travail, et
    surtout tous les écrans sont jugés sur le MÊME instant. Pendant une
    animation, deux captures successives donnent deux réponses.

    Et quand rien ne correspond, les scores sont affichés. « Écran
    inconnu » tout seul ne dit pas s'il faut recadrer un template ou
    simplement changer d'écran — le chiffre, si.

    `screen` : une capture DÉJÀ PRISE, à juger telle quelle. C'est la
    même règle poussée d'un cran — un appelant qui lit plusieurs choses
    (le diagnostic `where`, par exemple) doit pouvoir tout juger sur le
    MÊME instant, pas seulement nos propres repères entre eux.
    """
    screen_bgr = _capture_screen_bgr() if screen is None else screen
    scores = {}

    for screen, keys in SCREEN_ANCHORS:
        for key in keys:
            score, _ = best_match(TEMPLATES[key], screen=screen_bgr)
            scores[key] = score
            if score is not None and score >= threshold:
                return screen

    for key in ADVENTURE_ANCHORS:
        score, _ = best_match(TEMPLATES[key], screen=screen_bgr)
        scores[key] = score
        if score is not None and score >= threshold:
            logging.info(f"« {key} » reconnu à {score:.2f} : carte d'aventure.")
            return Screen.ADVENTURE

    lisible = ", ".join(
        f"{key} {'absent' if score is None else format(score, '.2f')}"
        for key, score in scores.items()
    )
    logging.info(f"Écran inconnu — meilleurs scores (seuil {threshold:.2f}) : {lisible}")
    _keep_unknown_screen(screen_bgr)
    return Screen.UNKNOWN


# Un écran inconnu est CONSERVÉ en capture (04/09/2026 : après un boss
# perdu, le bot a fini sur un écran que personne n'a pu décrire ensuite —
# les scores seuls ne disent pas ce qu'il y avait). Au plus une capture
# toutes les UNKNOWN_SCREEN_SHOT_GAP secondes : `back_to_known_screen`
# relit l'écran en boucle, et la première image suffit.
UNKNOWN_SCREEN_SHOT_GAP = 30.0
_last_unknown_shot = 0.0


def _keep_unknown_screen(screen_bgr):
    global _last_unknown_shot
    if time.time() - _last_unknown_shot < UNKNOWN_SCREEN_SHOT_GAP:
        return
    _last_unknown_shot = time.time()
    try:
        save_screen(screen_bgr, "ecran_inconnu")
    except Exception as exc:  # une capture qui rate ne doit rien casser
        logging.debug(f"Capture de l'écran inconnu impossible : {exc}")


def back_to_known_screen(timeout=RECOVERY_TIMEOUT) -> Screen:
    """
    Ferme ce qui traîne jusqu'à retrouver un écran d'entrée connu.

    C'est la pièce qui rend une BOUCLE possible : sans elle, la fin d'une
    aventure laisse le bot devant un écran de récompense qu'il ne sait pas
    quitter, et la tentative suivante n'a aucun point de départ.

    Ne clique QUE `DISMISS_BUTTONS`. Au pire elle ne trouve rien et rend
    `Screen.UNKNOWN` : elle ne lance jamais une partie par accident.
    """
    deadline = time.time() + timeout

    while True:
        screen = where_are_we()
        if screen is not Screen.UNKNOWN:
            logging.info(f"Écran connu retrouvé : {screen.value}.")
            return screen

        if time.time() >= deadline:
            logging.warning(f"Aucun écran connu après {timeout:.0f}s de fermetures.")
            return Screen.UNKNOWN

        # « VOUS ÊTES MORT … RELEVEZ-VOUS » : une nouvelle chance que
        # lor_battle.try_combat aurait dû prendre. On ne la clique pas ici
        # (elle relance un combat, hors de toute boucle qui saurait le
        # jouer), et rien d'autre ne fermera cet écran : inutile de tourner
        # deux minutes, on le dit et on rend la main tout de suite.
        # (05/09/2026 : 2 × 120 s perdues sur cet écran avant l'arrêt.)
        score, _ = best_match(TEMPLATES["retry"])
        if score is not None and score >= MATCH_THRESHOLD:
            logging.warning(
                f"« Relevez-vous » à l'écran ({score:.2f}) : nouvelle chance non "
                "prise par la boucle de combat — on ne la clique pas ici."
            )
            return Screen.UNKNOWN

        # UNE RÉCOMPENSE DE COMBAT NE SE FERME PAS, ELLE SE PREND
        # (06/11/2026). « RÉCOMPENSES DE COMBAT — Choisissez un objet à
        # équiper sur l'un de vos champions », deux champions, trois
        # objets, +19 PV à la clé. Le bot a tourné 120 s dessus et la
        # SESSION ENTIÈRE s'est arrêtée sur « impossible de revenir à un
        # écran connu ».
        #
        # Le panneau était pourtant reconnu — mesuré sur
        # `captures_reference/recompense_combat_20261106.png` :
        # `recompense_select_grise` 1.00 — et `events.RECOMPENSE` sait le
        # jouer depuis le 05/11. Le trou n'était pas la reconnaissance,
        # c'était le MOMENT : `play_reward` ne la guette que quelques
        # secondes après le boss intermédiaire, et `DISMISS_BUTTONS` n'a
        # rien qui morde ici (« Continuer » 0.32, « Quitter » 0.39).
        #
        # Même esprit que le garde « Relevez-vous » juste au-dessus : la
        # fonction qui sert à se rattraper doit savoir reconnaître ce
        # qu'elle a devant elle.
        # ET UN COFFRE N'EST PAS UNE RÉCOMPENSE — mesuré le 08/11/2026.
        # C'était la dette laissée le 06/11 : ce garde sait prendre une
        # récompense, pas un coffre. Or `recompense_select_grise` note
        # **0.83 sur un coffre**, donc au-dessus du seuil : le garde a
        # reconnu « récompense » sur un COFFRE resté ouvert, et lui a
        # appliqué la géométrie de la récompense, qui est ancrée sur un
        # autre bouton (centre 961 contre 1442). Les clics sont partis en
        # (1270, 459) et (1096, 766) — nulle part — huit fois, puis
        # « écran inconnu » et la SESSION s'est arrêtée.
        #
        # Les deux panneaux se départagent sans ambiguïté, et on les
        # mesure SUR LA MÊME CAPTURE plutôt que de laisser un ordre
        # d'essai décider (règle de `where_are_we`) :
        #       sur un coffre      : coffre/trésor 1.00, récompense 0.83
        #       sur une récompense : coffre/trésor <= 0.32, récompense 1.00
        if prendre_panneau_ouvert("hors nœud"):
            continue

        # `any` s'arrête au premier bouton trouvé : un seul clic par tour
        # de boucle, puis on regarde de nouveau où on est.
        if not any(click_button(name, timeout=1) for name in DISMISS_BUTTONS):
            # Tous cherchés, aucun trouvé : peut-être que le curseur en
            # cache un. On le range avant le tour suivant.
            park_mouse()
            human_delay(DELAY_BETWEEN_RETRIES)


# ============================================================
# ÉTAPE 0 : ENTRÉE DANS LE DÉFI HEBDOMADAIRE
# ============================================================

def _open_challenge_list(timeout) -> bool:
    """Carte du monde -> liste des défis actifs."""
    return click_button("monthly_challenge", timeout=timeout, transition=True)


def _pick_first_challenge(timeout) -> bool:
    """
    Premier défi de la liste — TOUJOURS le premier, c'est le plus facile.

    Chaque entrée partage le même visuel (seul le texte du nom change) :
    c'est `topmost_match`, et non `click_button`, qui la gère, pour
    choisir explicitement la première plutôt que la correspondance la plus
    probable.
    """
    coords = topmost_match(TEMPLATES["active_encounter"], timeout=timeout)
    if not coords:
        logging.warning("Aucun défi actif détecté dans la liste.")
        return False
    return safe_click(*coords, transition=True)


def _pick_champion(timeout) -> bool:
    """
    Choix du champion joué — LE PLUS ÉTOILÉ encore jouable.

    Jusqu'au 05/11/2026 on cliquait `first_champion.png`, c'est-à-dire le
    HAUT de la grille. Mesure faite ce jour-là : la grille est triée du
    plus faible au plus fort, donc le bot prenait le PIRE champion du
    compte — Zoé 1 ★ en tête, Teemo « Fleur spirituelle » 7 ★ tout en
    bas. Le 04/11 il avait joué le défi 2 avec Shen à 1 ★, pour finir à
    0/20 PV. `champions.choisir_champion` lit les étoiles et choisit.

    L'ANCIEN COMPORTEMENT RESTE LE FILET : lecture impossible, grille
    inattendue, opencv en défaut — on retombe sur `first_champion`.
    Jamais un clic au hasard.
    """
    # ON N'ANNONCE PAS UN REPLI AVANT DE SAVOIR S'IL AURA LIEU.
    # Ces deux lignes disaient « on retombe sur le premier de la liste »
    # AVANT d'avoir regardé si le premier de la liste était seulement à
    # l'écran — et depuis le correctif du 08/11 au soir, la ligne
    # suivante le dément souvent : « Le haut de la grille n'est pas à
    # l'écran (0.50) : on rend la main pour relire ». Le lecteur du log
    # voit un repli annoncé, puis aucun clic, et part chercher le bogue
    # dans `click_button`. On dit donc ce qu'on va REGARDER ; le repli
    # est annoncé plus bas, une fois qu'il a lieu.
    try:
        if champions.choisir_champion():
            return True
        cause = "grille des champions illisible"
    except Exception as exc:                        # noqa: BLE001
        cause = f"choix du champion impossible ({exc})"
    logging.warning("%s — on regarde si le haut de la grille est à l'écran.",
                    cause[0].upper() + cause[1:])
    # LE REPLI VISE LE HAUT DE LA GRILLE : il faut donc y être revenu.
    # `choisir_champion` laisse la grille où son parcours l'a menée — en
    # bas — et `first_champion.png` n'y est plus visible (0.64 mesuré le
    # 08/11/2026, seuil 0.80). Sans ce retour, le filet ne tombait jamais.
    try:
        champions.revenir_en_haut()
    except Exception as exc:                        # noqa: BLE001
        # DANS LE DOUTE, ON GARDE LE FILET : une panne du retour n'est
        # pas la preuve que le bouton n'est pas là. C'est l'écran qui
        # tranche, juste en dessous.
        logging.warning("Retour en haut de la grille impossible (%s) — on "
                        "regarde quand même l'écran.", exc)

    # ET ON NE S'ENTÊTE PAS SUR UN BOUTON QUI N'EST PAS LÀ (08/11/2026,
    # soir). `choisir_champion` rend False dans DEUX cas qui demandent
    # deux conduites opposées :
    #   (a) la grille est là, mais rien de jouable n'y a été lu — le
    #       filet du 05/11 a tout son sens, on remonte et on clique ;
    #   (b) l'écran n'EST PAS la grille — ce soir-là la LISTE DES DÉFIS,
    #       que la première vague a appris à reconnaître pour ne plus y
    #       lire de palier ni y faire tourner la molette.
    # `_pick_champion` ne faisait pas la différence et cherchait le haut
    # d'une grille absente : « Recherche du bouton : first_champion »
    # 20:47:26, souris garée 20:47:32, « introuvable » 20:47:37 — ONZE
    # SECONDES par essai d'entrée, trois essais par tentative.
    #
    # LA QUESTION N'EST PAS « SUR QUEL ÉCRAN SOMMES-NOUS », C'EST « LE
    # BOUTON DU REPLI EST-IL LÀ » — ET ELLE SE MESURE. Le booléen de
    # `revenir_en_haut` serait un proxy à DEUX SENS : il rend False hors
    # de la grille, mais AUSSI quand la molette n'a pas été entendue
    # (fenêtre sans premier plan, le défaut mesuré le 08/11). Or dans ce
    # second cas rien n'a défilé : la grille est restée EN HAUT, où
    # `first_champion` note ~1.00. S'en remettre au booléen couperait le
    # filet du 05/11 juste là où il peut encore sauver la tentative.
    # Mesuré sur les captures gardées :
    #       liste des défis (l'écran du blocage)    0.502
    #       grille DÉFILÉE (champions_defi19)       0.641
    #       grille EN HAUT (champions_haut, …)      0.978 à 1.000
    # Un coup d'œil coûte 0.4 s ; insister en coûte onze. Et rendre
    # False n'est pas un échec : c'est « l'écran n'est plus celui qu'on
    # croyait », `enter_challenge_attempt` relit au tour suivant — même
    # esprit que `_halt_if_resume_offered` (06/11).
    score, _ = best_match(TEMPLATES["first_champion"])
    if score is None or score < MATCH_THRESHOLD:
        logging.info("Le haut de la grille n'est pas à l'écran (%s) : on rend "
                     "la main pour relire, au lieu d'insister sur "
                     "« first_champion ».",
                     "illisible" if score is None else f"{score:.2f}")
        return False
    logging.warning("%s — on retombe sur le premier de la liste (%.2f).",
                    cause[0].upper() + cause[1:], score)
    return click_button("first_champion", timeout=timeout, transition=True)


def _resume_adventure(timeout) -> bool:
    """
    Reprend une aventure déjà commencée — SANS consommer de tentative.

    Le jeu ne décompte rien : l'aventure était en cours, on y retourne.
    """
    return click_button("reprendre_aventure", timeout=timeout, transition=True)


def _halt_if_resume_offered(timeout) -> bool:
    """
    Coupe la chaîne quand le défi ouvert propose de REPRENDRE.

    Le chemin depuis la carte du monde enchaîne sans regarder : liste,
    défi, grille des champions, lancement. Or le panneau d'un défi dont
    l'aventure est en cours n'a PAS de grille des champions — et la
    parcourir quand même fait défiler à la molette, ce qui déplace la
    liste des défis sous le panneau. Le 06/11/2026 le bot y a parcouru
    six rangées d'une grille absente avant de se perdre.

    Rendre False ici n'est donc pas un échec : c'est « l'écran n'est plus
    celui qu'on croyait ». `enter_challenge_attempt` relit l'écran au
    tour suivant, y reconnaît `Screen.RESUME`, et reprend.
    """
    score, _ = best_match(TEMPLATES["reprendre_aventure"])
    if score is not None and score >= MATCH_THRESHOLD:
        logging.info("Ce défi propose de REPRENDRE une aventure en cours "
                     f"({score:.2f}) : on ne cherche pas de champion.")
        return False
    return True


def _confirm_attempt(timeout) -> bool:
    """
    Consomme une tentative et lance le chargement de la partie.

    SON ÉCHEC EST LE SIGNAL D'ARRÊT DE LA SESSION : quand il n'y a plus de
    tentative, le jeu ne dit rien, il cesse simplement d'afficher ce
    bouton. Voir `enter_challenge_attempt`.
    """
    return click_button("use_attempt", timeout=timeout, transition=True)


# Le chemin restant à parcourir DEPUIS chaque écran. Une seule table, donc
# un seul endroit à corriger si le jeu ajoute une étape.
STEPS_FROM = {
    Screen.WORLD_MAP: (_open_challenge_list, _pick_first_challenge,
                       _halt_if_resume_offered, _pick_champion,
                       _confirm_attempt),
    Screen.LIST: (_pick_first_challenge, _halt_if_resume_offered,
                  _pick_champion, _confirm_attempt),
    Screen.CHAMPION: (_pick_champion, _confirm_attempt),
    Screen.ATTEMPT: (_confirm_attempt,),
}


def enter_challenge_attempt(retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT) -> Entry:
    """
    Lance UNE tentative, depuis n'importe lequel des écrans connus.

    C'est là toute la différence avec `enter_weekly_challenge`, qui part
    toujours de la carte du monde : à la fin d'une aventure, le jeu ne rend
    pas la carte du monde mais l'écran de SÉLECTION DU CHAMPION. La
    tentative suivante s'y enchaîne directement, sans repasser par la liste
    des défis — et c'est ce qui rend la boucle de session possible.

    Sur l'écran du champion — celui que le jeu rend après chaque aventure —
    ce sont DEUX clics et toujours les mêmes : le premier champion, puis
    le bouton de lancement. Voir SCREEN_ANCHORS pour l'ordre de détection,
    qui existe précisément pour ne pas sauter le premier des deux.

    Issues :
        LAUNCHED         la partie charge, à l'appelant de naviguer ;
        RESUMED          une aventure était DÉJÀ en cours — rien n'est
                         cliqué, rien n'est consommé, on rend la main
                         pour qu'elle soit reprise là où elle en est ;
        NO_ATTEMPT_LEFT  on est bien devant un écran connu mais le bouton
                         de confirmation ne vient pas, même après
                         plusieurs essais. C'est ainsi que le jeu dit
                         « plus de tentative » — il n'y a pas d'autre
                         signal à lire, donc pas d'autre façon de le
                         savoir ;
        LOST             écran non reconnu. On rend la main TOUT DE SUITE :
                         rien à cliquer ici ne fait avancer, et c'est à
                         l'appelant de tenter un retour
                         (`back_to_known_screen`).
    """
    last_failed = None

    for attempt in range(1, retries + 1):
        screen = where_are_we()
        steps = STEPS_FROM.get(screen)
        logging.info(
            f"Entrée dans une tentative — écran : {screen.value} "
            f"(essai {attempt}/{retries})."
        )

        # DÉJÀ DEDANS : il n'y a rien à lancer. C'est le cas du bot
        # démarré alors qu'une aventure est ouverte — le plus naturel
        # quand on met le jeu en place à la main avant de lâcher le bot.
        if screen is Screen.ADVENTURE:
            return Entry.RESUMED

        # DÉJÀ DEDANS, MAIS VU DEPUIS LES MENUS : le panneau du défi
        # propose « REPRENDRE L'AVENTURE » à la place d'« UTILISER UNE
        # TENTATIVE ». Un clic, et rien n'est consommé — le jeu ne
        # décompte pas une aventure qu'on n'a jamais quittée.
        if screen is Screen.RESUME:
            if _resume_adventure(timeout):
                logging.info("Aventure en cours reprise depuis les menus "
                             f"(chargement, {CHALLENGE_LOAD_DELAY:.0f}s)...")
                time.sleep(CHALLENGE_LOAD_DELAY)
                return Entry.RESUMED
            human_delay(DELAY_BETWEEN_RETRIES)
            continue

        if steps is None:
            return Entry.LOST

        for step in steps:
            if not step(timeout):
                last_failed = step
                break
        else:
            logging.info(
                f"Tentative lancée, chargement de la partie "
                f"({CHALLENGE_LOAD_DELAY:.0f}s)..."
            )
            time.sleep(CHALLENGE_LOAD_DELAY)
            return Entry.LAUNCHED

        human_delay(DELAY_BETWEEN_RETRIES)

    # C'est le DERNIER échec qui renseigne : buter sur la confirmation
    # depuis un écran par ailleurs reconnu veut dire qu'il n'y a plus de
    # tentative à consommer. Buter avant, c'est s'être perdu.
    if last_failed is _confirm_attempt:
        logging.info("Le bouton de confirmation ne vient pas : plus de tentative.")
        return Entry.NO_ATTEMPT_LEFT
    return Entry.LOST



def enter_weekly_challenge(retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """
    Depuis la carte du monde, entre dans le Défi Hebdomadaire :
        clic sur 'monthly_challenge' (ouvre la liste des défis actifs)
        -> premier défi de la liste ('active_encounter' — toujours le
           premier, c'est le plus facile)
        -> choix du champion ('first_champion')
        -> 'use_attempt' pour consommer une tentative et lancer le
           chargement de la partie.

    La liste des défis actifs partage le même visuel pour chaque entrée
    (seul le texte du nom change) : c'est topmost_match, et non
    click_button, qui la gère, pour choisir explicitement la première
    plutôt que la correspondance la plus probable.

    Retourne True en cas de succès, False sinon.
    """
    logging.info("Étape : entrée dans le Défi Hebdomadaire.")

    for attempt in range(1, retries + 1):
        logging.info(f"Tentative {attempt}/{retries} : entrée dans le défi.")

        # Les quatre étapes sont celles de STEPS_FROM[WORLD_MAP] : une
        # seule définition du chemin, pour que `enter_challenge_attempt`
        # et cette fonction ne puissent pas diverger.
        if all(step(timeout) for step in STEPS_FROM[Screen.WORLD_MAP]):
            logging.info(
                f"Défi rejoint, chargement de la partie ({CHALLENGE_LOAD_DELAY:.0f}s)..."
            )
            time.sleep(CHALLENGE_LOAD_DELAY)
            return True

        human_delay(DELAY_BETWEEN_RETRIES)

    logging.error("Échec de l'entrée dans le Défi Hebdomadaire après plusieurs tentatives.")
    return False


# ============================================================
# PARCOURIR UNE CARTE D'AVENTURE
# ============================================================
# LA CARTE SUIT UN ORDRE, ET C'EST CET ORDRE QU'ON SUIT :
#
#     champion de soutien -> nœud -> BOSS INTERMÉDIAIRE -> nœud -> BOSS FINAL
#     champion de soutien -> nœud -> nœud -> BOSS FINAL
#
# Les nœuds sont repérés par les TEMPLATES capturés à la main, et par eux
# seuls. Une détection par couleur (le triangle vert que le jeu dessine
# sous un nœud) a été essayée le 21/08/2026 : elle ne tenait pas en jeu et
# a été retirée. Ce qui décidait avant décide de nouveau.
#
# CE QUI EST GARDÉ de cette tentative, parce que ça ne dépend pas de la
# façon de repérer un nœud :
#   - ON ATTEND qu'un nœud apparaisse (`NODE_WAIT`), on ne regarde pas une
#     seule fois : après un choix ou un combat, la carte revient avec une
#     animation, et c'est ce qui manquait à l'ancienne version comme à la
#     nouvelle ;
#   - ce qu'un nœud propose est découvert À L'ARRIVÉE (`resolve_arrival`)
#     et non deviné d'avance : un nœud est un combat parce que le jeu
#     affiche « Combat » ;
#   - un échec ENREGISTRE L'ÉCRAN (`save_screen`), sinon il ne reste qu'un
#     mot dans un journal ;
#   - le compte rendu NOMME ce qui s'est passé, nœud par nœud.

# Le dossier ne doit contenir QUE des images de nœuds ordinaires.
NODES_DIR = str(Path(__file__).resolve().parent / "assets" / "nodes")

# Ce que peut proposer un nœud une fois qu'on y est.
ARRIVAL_COMBAT = "combat"
ARRIVAL_EVENT = "événement"
ARRIVAL_CHOICE = "choix"
ARRIVAL_TREASURE = "coffre"
ARRIVAL_CLOSED = "écran fermé"
ARRIVAL_OPTIONS = "nœud à options"
ARRIVAL_NOTHING = "rien à faire"
ARRIVAL_MISSED = "nœud introuvable ou clic sans effet"

# COMBIEN DE TEMPS ON LAISSE LE PANNEAU D'ARRIVÉE S'OUVRIR. Ce délai
# couvre désormais l'ATTENTE ENTIÈRE, pas un bouton : les quatre repères
# sont lus d'un coup (`read_arrival`). Avant, chacun avait ses 3 secondes,
# et un nœud sans combat coûtait 12 secondes d'attente pour rien — les
# trois quarts passés à guetter des boutons absents.
ARRIVAL_TIMEOUT = 6.0

# Les boutons qu'un nœud peut proposer une fois qu'on y est.
ARRIVAL_BUTTONS = ("combat_button", "treasure_button", "event_option",
                   "select_button", "quit_button",
                   "choisissez_en_un")

# « SÉLECTIONNER » ET « QUITTER » NE SE DÉPARTAGENT PAS PAR L'ORDRE, MAIS
# PAR LE SCORE. Tous deux referment le panneau sans rien lancer ; rien ne
# dit qu'un nœud offre l'un plutôt que l'autre, et un ordre écrit d'avance
# tranchait donc à la place de ce qu'on voit. Le 22/08/2026, sur le nœud 1
# d'une carte qui n'affichait QUE « Quitter », `select_button.png` a trouvé
# une fausse correspondance au-dessus du seuil : essayé en premier, il a
# gagné, et le bot a cliqué un bouton qui n'existait pas.
ARRIVAL_CLOSERS = ("select_button", "quit_button")

# LE CLIC SUR « COMBAT » EST LE SEUL QUI LANCE QUELQUE CHOSE, ET C'ÉTAIT
# LE SEUL QUE PERSONNE NE VÉRIFIAIT (08/11/2026).
#
# 18:10:09 le panneau du boss final est lu — combat_button 0.96 ;
# 18:10:10 le bot clique et lance la boucle de combat ; 18:12:12 elle
# abandonne sur « la partie n'a pas démarré en 120 s ». L'API répondait
# (`GameState: Menus`, 0 rectangle) et l'écran montrait la CARTE : aucune
# partie n'avait été lancée. Coût mesuré : 122 s d'attente + 48 s à
# chercher « Continuer » sur une carte d'aventure, puis « aventure
# terminée » sur une aventure intacte — une tentative hebdomadaire.
#
# CE QUI SE MESURE DANS LES TRACES :
#   - 19 combats lancés les 04, 05 et 06/11 : combat_button = **1.00**
#     les 19 fois, event_option 0.55 les 19 fois. Le 08/11 : 0.96 et
#     0.27. Le panneau n'était donc PAS dans son état habituel.
#   - ces 19 parties ont démarré en 2,8 à 7,5 s. 120 s, c'est 16 fois le
#     pire cas : « le boss met plus longtemps à charger » ne tient pas.
#   - le clic sur « Voyage » quatre secondes plus tôt, lui, a bien été
#     reçu (le panneau s'est ouvert) : la fenêtre avait le premier plan.
#
# CE QUI NE SE MESURE PAS, ET POURQUOI : aucune des 453 captures du
# projet ne montre un panneau d'arrivée avec « Combat » — `resolve_arrival`
# ne garde l'écran que lorsqu'il ne reconnaît RIEN. Clic à côté, panneau
# dans un autre état, clic avalé : impossible de départager sans image.
#
# D'où ces deux-là, qui ne tranchent pas mais ne laissent plus passer :
# on REGARDE si le panneau est parti, et s'il est toujours là on garde
# l'écran, on range la souris (un bouton sous le curseur n'est pas
# reconnu — cf. park_mouse) et on reclique. Un clic de plus sur un écran
# de chargement ne coûte rien ; ne pas cliquer coûte la tentative.
#
# LA VÉRIFICATION N'EST PAS DANS `resolve_arrival`, ET C'EST VOLONTAIRE :
# cette fonction lit les repères d'arrivée en UN SEUL passage, et c'est
# ce passage unique qui permet au score de trancher plutôt qu'à un ordre
# d'essai (bogue du 22/08/2026, verrouillé par
# `test_challenges.test_arrival_is_decided_by_what_the_game_offers`). Elle
# clique donc une fois, note où, et c'est `combattre` — juste avant de
# lancer la boucle — qui regarde si le panneau est parti.
COMBAT_CLICK_ATTEMPTS = 3
COMBAT_START_GLANCE = 3.0          # le panneau doit avoir disparu dans ce délai
COMBAT_START_POLL = 0.5

# Le score et le point du dernier « Combat » cliqué à l'arrivée, ou None.
# Consommé par `confirmer_le_lancement`, remis à None par `run_adventure`.
DERNIER_COMBAT = None

# LE PANNEAU DU CHAMPION DE SOUTIEN S'AFFICHE AVANT SON CONTENU.
# Mesuré par Ewan le 22/08/2026 : après le « Voyage » vers ce nœud, il
# faut DEUX SECONDES DE PLUS pour que les champions apparaissent. Le cadre
# et son bouton, eux, sont déjà lisibles — lire à cet instant, c'est
# valider un panneau encore vide.
#
# Deux précisions qui font que ces deux secondes tiennent vraiment :
#
#   - LE PLANCHER VAUT LA BORNE BASSE, donc `--speed` ne les raccourcit
#     pas. `human_delay` divise par `GESTURE_SPEED` (2.0 par défaut) :
#     sans plancher, deux secondes en vaudraient une. Cette attente ne
#     décrit pas un geste humain qu'on peut accélérer, mais le temps que
#     le CLIENT met à remplir son panneau.
#   - ELLE NE S'APPLIQUE QU'À CE NŒUD. Partout ailleurs le panneau est
#     complet dès qu'il est lisible, et deux secondes par nœud seraient
#     payées pour rien à chaque étape de chaque tentative.
SUPPORT_CHAMPION_SETTLE = (2.0, 2.6)

# COMBIEN DE TEMPS ON LAISSE UN NŒUD APPARAÎTRE. Ce n'est pas du confort :
# après le choix du champion de soutien ou après un combat, la carte
# revient avec une animation, et chercher une seule fois juste après le
# clic tombe sur un écran qui n'a pas encore ses nœuds.
NODE_WAIT = 12.0
NODE_POLL = 0.5

# Combien de temps on cherche le boss intermédiaire avant de conclure
# qu'il n'y en a pas sur cette carte.
SCENARIO_WAIT = 6.0

# Un clic sur un nœud qui n'ouvre rien mérite une seconde chance : le
# geste peut avoir raté, la carte peut avoir bougé sous la souris.
MISSED_RETRIES = 2

CLEAN_END = "aventure terminée"
# Motif d'un combat coupé par sa durée maximale alors que la partie continue.
INTERRUPTED_PREFIX = "combat interrompu"

# L'API DU CLIENT NE RÉPOND PAS : la partie n'a jamais été lue. Distinct
# de INTERRUPTED_PREFIX (là, le bot jouait et a manqué de temps) : ici il
# n'a rien vu du tout. Rejouer ne répare rien et chaque tentative coûte
# un défi hebdomadaire, donc la session s'arrête dessus.
API_DOWN_PREFIX = "API du client injoignable"

# LE CLIC SUR « COMBAT » N'A RIEN LANCÉ. Voisin d'API_DOWN_PREFIX — rien
# n'a été joué — mais la cause est ici, pas dans le client : l'API
# répondait et disait « menus ». Le 08/11/2026 ce cas rendait
# CLEAN_END, « aventure terminée » : le motif affirmait qu'on était allé
# au bout d'une aventure dont le boss final n'avait pas été joué, et le
# journal l'enregistrait ainsi. Le nommer ne répare pas la tentative,
# mais il la rend lisible dans `python journal.py`.
NOT_STARTED_PREFIX = "la partie n'a pas démarré"



def save_screen(screen_bgr, etiquette="carte") -> str:
    """
    Enregistre un écran dans `screenshots/` et rend son chemin.

    UN ÉCHEC DOIT LAISSER UNE TRACE REGARDABLE. Sans ça, « nœud
    introuvable » est un mot dans un journal : impossible de savoir si le
    jeu affichait autre chose, si l'animation n'était pas finie, ou si un
    template a vieilli.
    """
    dossier = Path(__file__).resolve().parent / "screenshots"
    dossier.mkdir(exist_ok=True)
    chemin = dossier / f"{etiquette}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    try:
        cv2.imwrite(str(chemin), screen_bgr)
    except Exception as exc:      # noqa: BLE001 — perdre une capture n'arrête rien
        logging.warning(f"Capture non enregistrée : {exc}")
        return ""
    logging.info(f"Écran enregistré pour diagnostic : {chemin}")
    return str(chemin)


_EVENT_READER = None


def _event_reader():
    """Un GameStateReader partagé pour lire les cartes des panneaux (chargé à la demande)."""
    global _EVENT_READER
    if _EVENT_READER is None:
        from game_state import GameStateReader
        _EVENT_READER = GameStateReader()
    return _EVENT_READER


RECOMPENSE_ATTENTE = 10.0          # le panneau met un instant à s'ouvrir
RECOMPENSE_INTERVALLE = 1.0


def prendre_panneau_ouvert(etiquette: str, vue=None) -> bool:
    """
    Un coffre ou une récompense RESTÉ OUVERT : on le prend. Rend True si
    quelque chose a été joué.

    DEUX FOIS LE MÊME PIÈGE, DEUX JOURS DE SUITE. Le 06/11 une récompense
    de combat a arrêté la session entière ; le 08/11 un coffre a fait
    pareil, parce que `recompense_select_grise` note **0.83 sur un
    coffre** et que le garde lui a donc appliqué la géométrie de la
    récompense, ancrée sur un autre bouton (961 contre 1442).

    Les deux panneaux se départagent sans ambiguïté — à condition de les
    mesurer SUR LA MÊME CAPTURE, la règle de `where_are_we` :
        sur un coffre      : coffre/trésor 1.00, récompense 0.83
        sur une récompense : coffre/trésor <= 0.32, récompense 1.00

    ET ON REGARDE AVANT DE MARCHER SUR LA CARTE. Mesuré trois fois le
    08/11/2026 : quand une aventure est reprise alors qu'un panneau est
    encore ouvert, `where_are_we` reconnaît la CARTE (le panneau n'en
    couvre qu'une partie), et le parcours part chercher des nœuds
    DERRIÈRE le panneau — exactement la perte du 05/11. Le panneau passe
    donc avant le premier pas.
    """
    import events
    # `vue` reste la MÊME image pour toutes les mesures : c'est ce qui
    # permet de comparer les scores au lieu de laisser un ordre d'essai
    # décider. Si la capture n'est pas disponible (tests hors ligne),
    # `best_match` retombe sur son propre comportement.
    vue = _capture_screen_bgr() if vue is None else vue
    recompense = best_match(TEMPLATES["recompense_select_grise"], screen=vue)[0] or 0.0
    coffre = max((best_match(TEMPLATES[k], screen=vue)[0] or 0.0)
                 for k in ("treasure_button", "coffre_objets_champion"))
    if max(recompense, coffre) < MATCH_THRESHOLD:
        return False
    if coffre >= recompense:
        logging.info("Coffre resté ouvert (%.2f contre %.2f pour la "
                     "récompense) : on le RAMASSE avant d'aller plus loin.",
                     coffre, recompense)
        # Comme `resolve_arrival` : si « Prendre le trésor » n'est pas
        # encore là, c'est que le coffre n'est pas OUVERT — et « Quitter »
        # jetterait le trésor.
        pris, _ = best_match(TEMPLATES["take_treasure_button"], screen=vue)
        if (pris or 0.0) < MATCH_THRESHOLD:
            ouvrir = best_match(TEMPLATES["treasure_button"], screen=vue)
            if ouvrir[0] is not None and ouvrir[0] >= MATCH_THRESHOLD:
                safe_click(*ouvrir[1], transition=True)
        play_event(f"coffre ({etiquette})", panneau=events.COFFRE)
    else:
        logging.info("Récompense à l'écran (%.2f) : on la PREND avant "
                     "d'aller plus loin.", recompense)
        play_reward(f"récompense ({etiquette})")
    return True


def play_reward(etiquette: str, timeout: float = RECOMPENSE_ATTENTE):
    """
    La RÉCOMPENSE AUTOMATIQUE d'un boss intermédiaire : un objet à
    équiper sur l'un de ses champions (Ewan, 05/11/2026).

    Elle ne s'ouvre à AUCUN nœud — elle tombe toute seule après le
    combat, là où rien ne regardait : `resolve_arrival` n'est appelé
    qu'en arrivant quelque part. Le bot restait donc dessus, puis
    cherchait un nœud derrière le panneau et finissait par abandonner
    l'aventure.

    On la GUETTE quelques secondes (elle met un instant à se dessiner)
    et on ne fait rien si elle ne vient pas : tous les boss
    intermédiaires n'en donnent pas forcément. Rend le bilan du panneau,
    ou None.
    """
    import events
    fin = time.time() + timeout
    while True:
        vue = _capture_screen_bgr()
        score = max((best_match(TEMPLATES[k], screen=vue)[0] or 0.0)
                    for k in ("recompense_select_grise", "recompense_select"))
        if score >= MATCH_THRESHOLD:
            logging.info("%s : récompense proposée (%.2f).", etiquette, score)
            return play_event(f"{etiquette} : récompense", panneau=events.RECOMPENSE)
        if time.time() >= fin:
            logging.info("%s : aucune récompense proposée.", etiquette)
            return None
        time.sleep(RECOMPENSE_INTERVALLE)


def play_event(etiquette: str, panneau=None) -> dict:
    """
    Joue le panneau ouvert (événement, choix ou coffre) jusqu'à en sortir,
    et journalise le bilan. Voir events.resolve_event.
    """
    import events
    bilan = events.resolve_event(
        _event_reader(), _capture_screen_bgr, save_screen, log=logging.info,
        panneau=panneau if panneau is not None else events.EVENEMENT)
    pris = ", ".join(bilan["picked"]) or "rien"
    logging.info(f"{etiquette} : {bilan['steps']} geste(s), pris : {pris}"
                 + (", sortie par la flèche retour" if bilan["escaped"] else "") + ".")
    return bilan


def read_arrival(screen_bgr=None, threshold=MATCH_THRESHOLD) -> dict:
    """
    Le score et le point de CHAQUE bouton d'arrivée, sur UNE SEULE capture.

    Rend {nom: (score, point)}, score à None si le fichier manque.

    Une seule image pour les quatre, et c'est le fond du correctif du
    22/08/2026 : les lire l'un après l'autre, c'était les juger sur quatre
    instants différents, et surtout laisser le PREMIER à franchir le seuil
    décider — même quand un autre était bien plus net.
    """
    if screen_bgr is None:
        screen_bgr = _capture_screen_bgr()
    return {
        name: best_match(TEMPLATES[name], screen=screen_bgr)
        for name in ARRIVAL_BUTTONS
    }


def _say_scores(lectures) -> str:
    """Les scores d'une lecture d'arrivée, en une ligne lisible au journal."""
    return ", ".join(
        f"{name} " + ("FICHIER ABSENT" if score is None else f"{score:.2f}")
        for name, (score, _point) in lectures.items()
    )


def combat_panel_gone(threshold=MATCH_THRESHOLD,
                      glance=COMBAT_START_GLANCE) -> bool:
    """
    « Combat » a-t-il disparu de l'écran ? True = le clic a été reçu.

    On ne demande pas au jeu s'il a démarré (l'API met plusieurs
    secondes à le dire, et `combat.wait_for_game_start` s'en charge) :
    on demande si le PANNEAU est parti. C'est immédiat, c'est visible,
    et c'est la seule question à laquelle on sait répondre tout de
    suite.
    """
    fin = time.time() + glance
    while True:
        score, _ = best_match(TEMPLATES["combat_button"],
                              screen=_capture_screen_bgr())
        if score is None or score < threshold:
            return True
        if time.time() >= fin:
            return False
        time.sleep(COMBAT_START_POLL)


def confirmer_le_lancement(threshold=MATCH_THRESHOLD,
                           attempts=COMBAT_CLICK_ATTEMPTS) -> bool:
    """
    Le « Combat » cliqué à l'arrivée a-t-il pris ? Sinon, on RECLIQUE.

    Rend True dès que le panneau a disparu, False si « Combat » est
    toujours lisible après `attempts` clics — et dans ce cas l'écran est
    gardé, parce que c'est précisément l'image qui manquait le
    08/11/2026 (voir COMBAT_CLICK_ATTEMPTS).

    RENDRE FALSE N'ARRÊTE RIEN : un panneau encore lisible peut aussi
    être un écran de chargement qui n'a pas fini de se poser, et couper
    là-dessus abandonnerait un combat qui démarre. Ce qui change, c'est
    qu'on aura recliqué, et surtout qu'on aura une capture à regarder.

    Sans « Combat » cliqué juste avant (hors ligne, ou combat relancé
    autrement), il n'y a rien à vérifier : on rend True.
    """
    global DERNIER_COMBAT
    cible, DERNIER_COMBAT = DERNIER_COMBAT, None
    if cible is None:
        return True
    score, point = cible
    for essai in range(1, attempts + 1):
        if combat_panel_gone(threshold):
            return True
        save_screen(_capture_screen_bgr(), "combat_sans_effet")
        logging.warning("« Combat » est TOUJOURS à l'écran %.1f s après le clic "
                        "%d/%d : la partie n'a pas été lancée.",
                        COMBAT_START_GLANCE, essai, attempts)
        if essai == attempts:
            break
        # Le bouton est peut-être sous le curseur, qui vient de cliquer
        # dessus : survolé, le jeu l'éclaire, et le gabarit peut le voir
        # « encore là » alors qu'il a changé d'état. Ranger la souris
        # lève le doute ET redonne sa chance au clic.
        park_mouse()
        logging.info("« Combat » (%.2f) recliqué en %s.",
                     score if score is not None else -1.0, point)
        safe_click(*point, transition=True)
    logging.warning("« Combat » cliqué %d fois sans effet visible — on lance quand "
                    "même la boucle, l'écran est gardé pour diagnostic.", attempts)
    return False


def resolve_arrival(timeout=ARRIVAL_TIMEOUT, threshold=MATCH_THRESHOLD,
                    settle=None) -> str:
    """
    Ce que le nœud propose, une fois qu'on y est arrivé.

    ON NE PRÉSUME PAS DU CONTENU D'UN NŒUD : on regarde ce que le jeu
    offre. Mais REGARDER N'EST PAS ESSAYER DANS UN ORDRE. Les quatre
    repères sont lus sur la même capture, et ce qu'on lit décide :

      - « Combat » l'emporte quand il est là : c'est le seul qui LANCE
        quelque chose, et le manquer laisserait le jeu attendre ;
      - un événement propose une option PUIS demande de valider ;
      - entre « Sélectionner » et « Quitter », qui referment tous deux le
        panneau, LE MEILLEUR SCORE GAGNE. Rien d'autre ne les départage,
        et l'ordre qui les départageait avant a fait cliquer, le
        22/08/2026, un « Sélectionner » qui n'était pas à l'écran.

    Le score des quatre est écrit au journal À CHAQUE ARRIVÉE : sans ça,
    un mauvais clic ne laisse qu'un nom de bouton, et on ne peut pas
    savoir s'il était vraiment là.

    `settle` — (min, max) en secondes — laisse le panneau SE REMPLIR avant
    la première lecture. Attendre APRÈS la lecture ne servirait à rien :
    c'est la lecture elle-même qui doit tomber sur un panneau complet,
    sinon on clique un bouton lu sur un écran qui n'est pas encore celui
    qu'on croit. Voir SUPPORT_CHAMPION_SETTLE, le seul cas connu.
    """
    if settle:
        attendu = human_delay(settle, floor=settle[0])
        logging.info(
            f"Panneau laissé se remplir {attendu:.1f} s de plus avant lecture."
        )

    limite = time.time() + timeout

    while True:
        # Comme partout ailleurs dans le projet : on laisse l'animation
        # d'ouverture finir avant de juger l'écran. Le panneau d'arrivée
        # arrive en fondu, et une lecture prise trop tôt ne montre rien.
        human_delay(DELAY_BEFORE_SEARCH)
        ecran = _capture_screen_bgr()
        lectures = read_arrival(ecran, threshold)
        vus = {
            name: (score, point)
            for name, (score, point) in lectures.items()
            if score is not None and score >= threshold
        }
        if vus or time.time() >= limite:
            break
        time.sleep(NODE_POLL)

    logging.info(f"Arrivée, scores (seuil {threshold:.2f}) : {_say_scores(lectures)}")

    if not vus:
        logging.warning("Arrivée : aucun bouton reconnu.")
        save_screen(ecran, "arrivee_sans_bouton")
        return ARRIVAL_NOTHING

    if "combat_button" in vus:
        global DERNIER_COMBAT
        score, point = vus["combat_button"]
        # On note OÙ et à COMBIEN : le 08/11/2026, « Combat » a été lu à
        # 0.96 (1.00 les 19 fois précédentes), cliqué, et la partie n'a
        # jamais démarré — sans que rien dans le journal ne dise où le
        # clic était parti. Le point va aussi à `confirmer_le_lancement`,
        # qui recliquera si le panneau est encore là.
        DERNIER_COMBAT = (score, point)
        logging.info("Arrivée : « Combat » (%.2f) cliqué en %s.", score, point)
        safe_click(*point, transition=True)
        return ARRIVAL_COMBAT

    if "treasure_button" in vus:
        # UN COFFRE SE RAMASSE. Jusqu'au 04/11/2026 il n'y avait aucun
        # repère pour « Ouvrir le trésor » : seul `quit_button` passait le
        # seuil, le bot refermait le coffre et renonçait à un objet
        # permanent PLUS une copie de carte dans son deck — à chaque nœud
        # de ce type, sur toute l'aventure. Le panneau qui suit (trois
        # cartes, « Prendre le trésor ») se joue comme un événement, avec
        # les repères du coffre.
        safe_click(*vus["treasure_button"][1], transition=True)
        import events
        play_event("coffre", panneau=events.COFFRE)
        return ARRIVAL_TREASURE

    if "choisissez_en_un" in vus:
        # UN NŒUD À OPTIONS (le soigneur, 06/11/2026) : « Choisissez-en
        # 1. » — Soins / Acheter des soins / Retirer une carte — avec un
        # bouton qui porte LE NOM DE L'OPTION choisie. Aucun gabarit de
        # libellé ne le reconnaît : trois d'entre eux convergeaient sur
        # (1441, 1002) à 0.75, sous le seuil, et le bot restait planté
        # puis abandonnait l'aventure. On s'ancre sur l'invite, qui est
        # générique, et on valide la présélection.
        import events
        play_event("nœud à options", panneau=events.NOEUD_OPTIONS)
        return ARRIVAL_OPTIONS

    if "event_option" in vus:
        safe_click(*vus["event_option"][1], transition=True)
        # L'option ouvre souvent un CHOIX (cartes à ajouter, mot-clé à
        # poser sur une unité du deck…) que « Sélectionner » seul ne
        # valide pas : il est grisé tant qu'aucune carte n'est cliquée.
        # `events.resolve_event` lit l'offre, choisit pour le deck, puis
        # ferme — et sort par la flèche retour si rien ne bouge.
        play_event("événement")
        return ARRIVAL_EVENT

    fermetures = {name: vus[name] for name in ARRIVAL_CLOSERS if name in vus}
    garde = False
    if len(fermetures) > 1:
        # Les deux lisibles à la fois : le score tranche, mais l'écran est
        # gardé — c'est le cas où une fausse correspondance se cache.
        logging.warning("Arrivée : « Sélectionner » ET « Quitter » au-dessus du "
                        "seuil, le meilleur score tranche.")
        save_screen(ecran, "arrivee_ambigue")
        garde = True

    nom, (score, point) = max(fermetures.items(), key=lambda item: item[1][0])
    logging.info(f"Arrivée : '{nom}' retenu ({score:.2f}) en {point}.")
    if nom == "quit_button" and not garde:
        # FERMER UN NŒUD, C'EST RENONCER À CE QU'IL OFFRAIT — et le journal
        # n'en garde qu'un mot. Le 04/11/2026, sur une aventure de trois
        # nœuds, DEUX ont été fermés ainsi avant le boss final : rien dans
        # la trace ne dit ce que le bot avait alors sous les yeux, ni si
        # « Quitter » était le seul choix offert. Même raison que
        # `arrivee_sans_bouton` et `arrivee_ambigue` : ce qu'on refuse se
        # regarde après coup, ou ne se saura jamais.
        logging.info(f"Nœud quitté — écran gardé : {save_screen(ecran, 'noeud_quitte')}")
    safe_click(*point, transition=True)
    if nom == "select_button":
        # Le champion de soutien se valide d'un clic : un choix est
        # présélectionné. Mais un panneau de choix SANS présélection
        # (pouvoir, carte pour le deck) laisse « Sélectionner » grisé et
        # toujours à l'écran après le clic : là, il faut choisir d'abord.
        human_delay(DELAY_AFTER_TRANSITION)
        score, _ = best_match(TEMPLATES["select_button"], screen=_capture_screen_bgr())
        if score is not None and score >= threshold:
            logging.info("Arrivée : « Sélectionner » toujours affiché après le clic — "
                         "un choix est attendu d'abord.")
            play_event("choix")
        return ARRIVAL_CHOICE
    return ARRIVAL_CLOSED


def locate_node(cible, wait=NODE_WAIT, exclude=()):
    """
    Où est le nœud à rejoindre. Rend (x, y) ou None.

    `cible` est soit une clé de TEMPLATES — une rencontre nommée, champion
    de soutien ou boss —, soit un chemin de DOSSIER pour les nœuds
    ordinaires, dont l'aspect varie et qui ont donc plusieurs images.

    Pour un dossier, on ne prend PAS le premier template qui répond : on
    mesure toutes les images sur une même capture, on lit sur CETTE capture
    où nous sommes (`_player_position` : le médaillon au portrait du
    champion joué), et on retient le candidat le plus proche parmi ceux
    qui sont à droite de nous
    (cf. adventure_navigation.pick_next_node). « Le plus à gauche » tout
    court se trompait au deuxième nœud : après le nœud du haut, celui du
    bas, non visité et à la même hauteur en x, passait devant la suite du
    chemin.

    MARQUEUR NON TROUVÉ : la carte se recentre sur nous après chaque
    « Voyage », donc notre position est LE CENTRE DE L'ÉCRAN — on s'en sert
    à la place. « Le plus à gauche » n'est plus que l'ultime repli : le
    05/09/2026 (marqueur à 0.78, sous le seuil) il a renvoyé trois fois sur
    le nœud DÉJÀ VISITÉ derrière nous, reconnu à 0.81 malgré sa coche.

    LA RÈGLE « À DROITE » A ÉTÉ CALIBRÉE SUR UNE POSITION FAUSSE, et ça
    reste à reprendre (08/11/2026). Elle datait du temps où la position
    venait du losange, c'est-à-dire d'un décor posé 400 à 650 px trop à
    gauche : « à droite de nous » voulait alors dire « à droite d'un point
    quelconque derrière nous », et presque tout passait. Avec le
    médaillon, la position est juste et la règle devient stricte — sur
    `captures_reference/marqueur_carte_ahri_20261106.png` les deux nœuds
    joignables sont DESSOUS, et le seul candidat à droite est un faux
    positif sur le bouton boussole de l'interface (0.85 en (1819, 470)).
    Le repli « le plus proche » rattrape le premier cas ; le second se
    corrige tout seul au tour suivant (clic sans « Voyage » → écarté),
    au prix d'une vingtaine de secondes.
    Ce qu'il faudrait savoir avant de toucher à la règle elle-même est
    un FAIT DE JEU : dans quel sens un chemin peut-il repartir ? Il
    viendra d'Ewan, pas d'une capture. En attendant, la mesure dit déjà
    ceci : « le plus proche » TOUT COURT, sans règle de la droite,
    reproduit l'ancienne décision 49 fois sur 53 et ses quatre
    différences vont toutes vers un nœud mieux noté ou vers un écran où
    aucun choix n'avait de sens (panneau de boutique ouvert). C'est le
    candidat sérieux pour remplacer la règle — pas une capture ne
    l'infirme — mais il change une règle écrite sur une observation en
    jeu, alors il attend la sienne.

    `exclude` : points cliqués en vain (sans « Voyage »), plus candidats.

    Dans les deux cas on ATTEND, on ne regarde pas une fois.
    """
    if cible in TEMPLATES:
        return wait_for_image(TEMPLATES[cible], timeout=wait)

    limite = time.time() + wait
    while True:
        # Laisser le nœud fraîchement apparu finir son animation d'entrée
        # avant de le mesurer (même pause qu'avant la recherche d'un bouton).
        human_delay(DELAY_BEFORE_SEARCH)
        ecran = _capture_screen_bgr()
        noeuds = find_nodes_in_folder(cible, screen=ecran)
        if noeuds:
            # TOUS les candidats au journal, scores compris : si un jour le
            # bot part vers un faux positif, cette ligne dit lequel et
            # combien il valait — l'écran ne se rejoue pas, le journal si.
            logging.info("Nœuds candidats (gauche → droite) : "
                         + _say_nodes(noeuds))
            if exclude:
                logging.info("Écartés (cliqués sans « Voyage ») : "
                             + ", ".join(str(tuple(int(v) for v in p)) for p in exclude))
            position = _player_position(ecran)
            comment = "le plus proche devant nous"
            if position is None:
                position = _screen_center(ecran)
                comment = "le plus proche à droite du centre (marqueur non trouvé)"
            choix = pick_next_node(noeuds, position, exclude=exclude)
            if choix is None:
                # « RIEN DEVANT NOUS » EST DEVENU UN CAS ORDINAIRE
                # (08/11/2026). Tant que la position venait du losange —
                # un décor de tracé, posé 400 à 900 px DERRIÈRE nous — il
                # y avait presque toujours un candidat « à droite », et
                # ce repli ne servait qu'au marqueur introuvable. Avec le
                # médaillon, la position est juste, et la suite du chemin
                # est parfois DESSOUS : sur
                # `captures_reference/marqueur_carte_ahri_20261106.png`,
                # les deux nœuds joignables sont sous nous (les flèches
                # cyan le montrent), aucun à droite. Rendre None là
                # ferait abandonner l'aventure devant un chemin
                # parfaitement lisible.
                #
                # ET LE REPLI EST « LE PLUS PROCHE », PAS « LE PLUS À
                # GAUCHE ». Le plus à gauche existe pour le cas où l'on
                # ignore où l'on est ; quand on le sait, il envoie au
                # bout de l'écran. Mesuré en rejouant les 53 décisions
                # que les captures du projet permettent de rejouer : le
                # plus à gauche change 8 réponses sur 53, dont QUATRE
                # vers la flèche retour du coin haut-gauche (un faux
                # positif des gabarits de nœud, 0.81) ; le plus proche
                # n'en change que 6, et ses différences vont vers le
                # nœud le mieux noté.
                choix = _plus_proche(noeuds, position, exclude)
                comment = "le plus proche (rien devant nous)"
            if choix is None:
                logging.warning(f"Aucun candidat à droite de notre marqueur {position} ; on réessaie.")
            else:
                score, point, nom = choix
                logging.info(f"Nœud retenu : {nom} ({score:.2f}) en {point}, {comment}.")
                return point
        if time.time() >= limite:
            return None
        time.sleep(NODE_POLL)


# NOTRE POSITION EST UN MÉDAILLON ROND, PAS UN LOSANGE (08/11/2026,
# fait de jeu confirmé par Ewan). `assets/player_marker.png` découpe un
# losange doré vide : c'est un DÉCOR DE TRACÉ posé sur le chemin, et il
# était pris pour nous depuis l'origine. Le vrai repère est le médaillon
# qui porte le PORTRAIT DU CHAMPION JOUÉ — celui du HUD en bas à gauche.
# Comme le portrait change à chaque tentative, aucun PNG ne peut le
# reconnaître : `marqueur_joueur.py` le découpe à la volée dans le HUD.
# Ce qu'il en coûtait, mesuré sur la soirée du 08/11 : losange 0.90 en
# (318, 477) pendant que le médaillon était en (960, 451), soit 640 px
# d'erreur, et `pick_next_node` partant d'un point qui n'était pas nous.
#
# L'ANCIEN CHEMIN RESTE POSSIBLE : mettre `MARQUEUR_LOSANGE = True`
# remet le losange, avec ses deux seuils d'origine. Il n'est pas
# supprimé — il n'a simplement plus le droit de dire où nous sommes.
MARQUEUR_LOSANGE = False

# Le losange était parfois reconnu juste SOUS le seuil (0.78 le
# 05/09/2026, un panneau ouvert à côté). Entre ces deux seuils on
# l'acceptait s'il était dans la bande centrale de l'écran (largeur
# relative MARKER_CENTER_BAND de part et d'autre du milieu).
MARKER_SOFT_THRESHOLD = 0.70
MARKER_CENTER_BAND = 0.20


def _screen_center(ecran):
    """Le centre de la capture, là où la carte nous remet après un « Voyage »."""
    if ecran is None:
        import pyautogui        # import local : navigate reste importable sans écran
        width, height = pyautogui.size()
    else:
        height, width = ecran.shape[:2]
    return (width // 2, height // 2)


def _player_position(ecran):
    """
    Où est notre marqueur sur cette capture, ou None s'il n'y est pas.

    Lu sur la MÊME image que les nœuds : la carte se recentre sur nous
    après chaque « Voyage », une position d'il y a dix secondes est
    fausse.

    C'est le MÉDAILLON au portrait du champion joué (cf.
    `MARQUEUR_LOSANGE` ci-dessus et `marqueur_joueur.py`). Le point rendu
    est le centre du médaillon, qui flotte 70 à 120 px AU-DESSUS du nœud
    où nous sommes (mesuré : 83 px sur la carte d'Ahri, 118 px sur celle
    de la boutique, l'écart suit le zoom de la carte). Ça ne change rien
    à « qui est à droite de nous » ; ne pas le confondre avec le point à
    cliquer pour revenir sur notre propre nœud.

    Rien de trouvé rend None, et l'appelant garde ses replis : le centre
    de l'écran, puis « le plus à gauche ».
    """
    if not MARQUEUR_LOSANGE:
        medaillon = marqueur_joueur.trouver_medaillon(ecran)
        if medaillon is None:
            logging.warning("Médaillon du joueur non trouvé sur cette capture.")
            return None
        logging.info(f"Médaillon du joueur ({medaillon.score:.2f}, échelle "
                     f"{medaillon.echelle:.3f}) en {medaillon.point}.")
        return medaillon.point

    score, point = best_match(TEMPLATES["player_marker"], screen=ecran)
    if score is not None and MARKER_SOFT_THRESHOLD <= score < MATCH_THRESHOLD:
        cx, _ = _screen_center(ecran)
        if abs(point[0] - cx) <= cx * MARKER_CENTER_BAND:
            logging.info(f"Marqueur du joueur ({score:.2f}, sous le seuil mais "
                         f"près du centre) en {point}.")
            return point
    if score is None or score < MATCH_THRESHOLD:
        logging.warning("Marqueur du joueur non trouvé"
                        + ("" if score is None else f" ({score:.2f})") + ".")
        return None
    logging.info(f"Marqueur du joueur ({score:.2f}) en {point}.")
    return point


def _plus_proche(noeuds, position, exclude=()):
    """
    Le candidat le plus proche de `position`, hors points déjà écartés.

    Dernier recours de `locate_node` quand plus rien n'est « devant
    nous ». Même exclusion que `pick_next_node` — un nœud cliqué sans
    « Voyage » reste écarté — mais sans la règle de la droite.
    """
    restants = [n for n in noeuds
                if not any(math.hypot(n[1][0] - ex, n[1][1] - ey) < NODE_EXCLUDE_DISTANCE
                           for ex, ey in exclude)]
    if not restants:
        return None
    return min(restants, key=lambda n: math.hypot(n[1][0] - position[0],
                                                  n[1][1] - position[1]))


def _say_nodes(noeuds) -> str:
    """La liste des nœuds candidats, en une ligne lisible au journal."""
    return ", ".join(f"{nom} {score:.2f} en {point}" for score, point, nom in noeuds)


def goto_node(cible, etiquette, wait=NODE_WAIT, timeout=DEFAULT_TIMEOUT,
              settle=None):
    """
    Rejoint un nœud, et rend (ce qu'il propose, le point cliqué).

    Trois gestes, et le deuxième n'est pas décoratif : cliquer le nœud,
    confirmer par « Voyage », puis voir ce qui s'ouvre. SANS « VOYAGE », ON
    N'A PAS BOUGÉ — son absence veut dire que le clic n'a pas ouvert le
    nœud, et enchaîner reviendrait à agir sur un écran qu'on n'a pas.

    `settle` est transmis à `resolve_arrival` : le temps qu'il faut à CE
    nœud-là pour afficher le contenu de son panneau, et pas seulement son
    cadre (cf. SUPPORT_CHAMPION_SETTLE).
    """
    exclus = []     # cliqués sans « Voyage » : plus candidats
    for essai in range(1, MISSED_RETRIES + 2):
        point = locate_node(cible, wait, exclude=tuple(exclus))

        if point is None:
            logging.warning(f"{etiquette} : introuvable (essai {essai}).")
            if essai > MISSED_RETRIES:
                save_screen(_capture_screen_bgr(), "noeud_introuvable")
                return ARRIVAL_MISSED, None
            human_delay(DELAY_BETWEEN_RETRIES)
            continue

        logging.info(f"{etiquette} : clic en {point}.")
        if not safe_click(*point, transition=True):
            human_delay(DELAY_BETWEEN_RETRIES)
            continue

        if not click_button("voyage_button", timeout=timeout, transition=True):
            logging.warning(f"{etiquette} : « Voyage » non détecté, on n'a pas bougé ; "
                            f"ce nœud {point} est écarté.")
            exclus.append(point)
            if essai > MISSED_RETRIES:
                save_screen(_capture_screen_bgr(), "sans_voyage")
                return ARRIVAL_MISSED, point
            human_delay(DELAY_BETWEEN_RETRIES)
            continue

        return resolve_arrival(settle=settle), point

    return ARRIVAL_MISSED, None


def has_mid_boss(wait=SCENARIO_WAIT) -> bool:
    """
    Cette carte a-t-elle un boss intermédiaire ?

    C'est la seule question que la carte pose vraiment : le reste de
    l'ordre est fixe. On regarde s'il est là, et son absence est une
    réponse, pas un échec.
    """
    trouve = wait_for_image(TEMPLATES["secondary_enemy_node"], timeout=wait) is not None
    logging.info("Scénario : boss intermédiaire "
                 + ("présent." if trouve else "absent."))
    return trouve


def run_adventure(combat_options=None, reprise=False) -> dict:
    """
    Parcourt une carte d'aventure en suivant son ORDRE, combats compris.

    Rend {"nodes", "combats", "reason"} : les nœuds franchis, les rapports
    de combat dans l'ordre, et pourquoi on s'est arrêté. `CLEAN_END` veut
    dire que le boss final a été joué — c'est la seule fin normale.

    `reprise=True` : on REPREND une aventure déjà commencée. Les étapes
    du début ont alors le droit de MANQUER — elles ont été franchies
    avant qu'on reprenne la main — et on avance jusqu'à la première
    qu'on retrouve. Sans ça, l'enchaînement repartait toujours du
    champion de soutien et abandonnait une aventure POURTANT VIVANTE :
    deux tentatives mensuelles perdues ainsi le 05/11/2026, dont une où
    le combat suivant était gagnable.

    LE DROIT DE SAUTER S'ÉTEINT À LA PREMIÈRE ÉTAPE RETROUVÉE. Ensuite
    un nœud manquant redevient une panne — sinon le bot traverserait la
    carte en cliquant à côté. Le boss final, lui, n'est jamais sautable :
    c'est la fin, pas une étape.

    UN COMBAT PERDU ARRÊTE LE PARCOURS : l'aventure est finie, chercher la
    suite reviendrait à scanner un écran de fin de partie.
    """
    from lor_battle import confirm_victory, try_combat

    global DERNIER_COMBAT
    DERNIER_COMBAT = None       # aucun « Combat » en attente de vérification

    # UN PANNEAU ENCORE OUVERT PASSE AVANT LE PREMIER PAS : sinon on
    # cherche des nœuds DERRIÈRE lui (cf. `prendre_panneau_ouvert`).
    prendre_panneau_ouvert("au départ du parcours")

    combats, franchis = [], 0
    # Le dernier combat dont le verdict n'est pas encore connu. Rejoindre
    # le nœud suivant PROUVE qu'il était gagné : une défaite ne laisse pas
    # continuer (fin d'aventure ou « Relevez-vous », gérés par try_combat).
    en_attente = [None]

    def bilan(reason):
        return {"nodes": franchis, "combats": combats, "reason": reason}

    def etape(cible, etiquette, settle=None):
        """Rejoint un nœud et compte le pas. Rend l'arrivée."""
        nonlocal franchis
        arrivee, point = goto_node(cible, etiquette, settle=settle)
        if arrivee != ARRIVAL_MISSED:
            franchis += 1
            logging.info(f"{etiquette} : {arrivee}.")
            if en_attente[0] is not None:
                confirm_victory(en_attente[0])
                en_attente[0] = None
        return arrivee, point

    def combattre(point, etiquette, final_boss=False):
        """Joue le combat de ce nœud. Rend (rapport, motif d'arrêt)."""
        # LE CLIC SUR « COMBAT » EST VÉRIFIÉ AVANT D'ATTENDRE 120 SECONDES.
        confirmer_le_lancement()
        try:
            rapport = try_combat(*point, final_boss=final_boss, **(combat_options or {}))
        except Exception as exc:      # noqa: BLE001 — on veut la raison, pas la trace
            logging.error(f"{etiquette} : combat non joué ({exc}).")
            return None, f"{etiquette} : combat non joué ({exc})"
        combats.append(rapport)
        if rapport is not None and getattr(rapport, "api_down", False):
            return rapport, API_DOWN_PREFIX + f" ({etiquette}) : {rapport.reason}"
        if rapport is not None and getattr(rapport, "never_started", False):
            return rapport, NOT_STARTED_PREFIX + f" ({etiquette}) : {rapport.reason}"
        if rapport is not None and getattr(rapport, "interrupted", False):
            return rapport, INTERRUPTED_PREFIX + f" ({etiquette}) : durée maximale atteinte, partie encore en cours"
        if rapport is not None and rapport.won is False:
            return rapport, f"combat perdu ({etiquette})"
        if rapport is not None and rapport.won is None and not final_boss:
            en_attente[0] = rapport
        return rapport, None

    # En reprise, les étapes DÉJÀ FRANCHIES ont le droit de manquer —
    # jusqu'à la première qu'on retrouve, pas au-delà.
    sauter = [bool(reprise)]

    def manquante(etiquette, motif):
        """Rend le motif d'arrêt, ou None si on a le droit de sauter."""
        if not sauter[0]:
            return motif
        logging.info("Reprise : « %s » n'est plus sur la carte — déjà "
                     "franchi, on continue.", etiquette)
        return None

    # --- 1. le champion de soutien, toujours en premier ------------------
    arrivee, _ = etape("support_champion", "champion de soutien",
                       settle=SUPPORT_CHAMPION_SETTLE)
    if arrivee == ARRIVAL_MISSED:
        motif = manquante("champion de soutien", "champion de soutien introuvable")
        if motif:
            return bilan(motif)
    else:
        sauter[0] = False

    # --- 2. premier nœud ordinaire --------------------------------------
    arrivee, _ = etape(NODES_DIR, "nœud 1")
    if arrivee == ARRIVAL_MISSED:
        motif = manquante("nœud 1", "premier nœud introuvable")
        if motif:
            return bilan(motif)
    else:
        sauter[0] = False

    # --- 3. boss intermédiaire, si cette carte en a un ------------------
    if has_mid_boss():
        arrivee, point = etape("secondary_enemy_node", "boss intermédiaire")
        if arrivee == ARRIVAL_MISSED:
            motif = manquante("boss intermédiaire", "boss intermédiaire introuvable")
            if motif:
                return bilan(motif)
        else:
            sauter[0] = False
        if arrivee == ARRIVAL_COMBAT:
            _, arret = combattre(point, "boss intermédiaire")
            if arret:
                return bilan(arret)
            # La récompense tombe TOUTE SEULE après la victoire : pas un
            # nœud, donc personne ne la regardait.
            play_reward("boss intermédiaire")
        else:
            logging.warning(
                f"Boss intermédiaire rejoint mais aucun combat proposé "
                f"({arrivee})."
            )

        arrivee, _ = etape(NODES_DIR, "nœud 2")
        if arrivee == ARRIVAL_MISSED:
            motif = manquante("nœud 2",
                              "deuxième nœud introuvable (après le boss intermédiaire)")
            if motif:
                return bilan(motif)
        else:
            sauter[0] = False
    else:
        arrivee, _ = etape(NODES_DIR, "nœud 2")
        if arrivee == ARRIVAL_MISSED:
            motif = manquante("nœud 2", "deuxième nœud introuvable")
            if motif:
                return bilan(motif)
        else:
            sauter[0] = False

    # --- 4. boss final --------------------------------------------------
    arrivee, point = etape("final_boss", "boss final")
    if arrivee == ARRIVAL_MISSED:
        return bilan("boss final introuvable")
    if arrivee != ARRIVAL_COMBAT:
        return bilan(f"boss final rejoint mais aucun combat proposé ({arrivee})")

    _, arret = combattre(point, "boss final", final_boss=True)
    if arret:
        return bilan(arret)

    return bilan(CLEAN_END)


# DIAGNOSTIC — AUCUN CLIC, AUCUNE SOURIS
# ============================================================

def score_report(threshold=MATCH_THRESHOLD, screen=None) -> dict:
    """
    Le score de CHAQUE repère sur l'écran courant, en une capture.

    Sert à répondre à la seule question qui compte devant un « écran
    inconnu » : est-ce que le jeu n'est pas sur cet écran, ou est-ce que
    le template ne reconnaît plus l'écran sur lequel il est ?

    `screen` : une capture déjà prise, pour que l'appelant puisse juger
    TOUT sur le même instant (cf. `where_are_we`).
    """
    screen_bgr = _capture_screen_bgr() if screen is None else screen
    return {
        name: best_match(path, screen=screen_bgr)[0]
        for name, path in sorted(TEMPLATES.items())
    }


def cmd_where(snap: bool, threshold: float) -> None:
    """
    UNE SEULE CAPTURE POUR TOUT LE DIAGNOSTIC.

    C'est la règle du projet, écrite dans `CLAUDE.md` depuis le
    22/08/2026 : « quand plusieurs templates répondent de la même
    question, les mesurer sur UNE SEULE capture et comparer les scores —
    ne jamais laisser un ordre d'essai décider à la place de ce qu'on
    voit ». Et c'est la commande qui sert à VÉRIFIER cette règle qui
    l'enfreignait : elle prenait QUATRE photos — une pour
    `where_are_we`, une pour `score_report`, une pour le médaillon, une
    pour `--snap`. Pendant une animation, le verdict, le tableau des
    scores, la position du joueur et la capture gardée décrivaient
    quatre instants différents, et on comparait des chiffres qui
    n'avaient jamais coexisté.

    `--snap` enregistre donc L'IMAGE QUI A ÉTÉ JUGÉE, pas une neuve :
    sinon le rapport qu'on lit et la capture qu'on garde pour l'analyser
    ne montrent pas la même chose — exactement le piège qu'on vient de
    décrire, mais différé de plusieurs jours.
    """
    vue = _capture_screen_bgr()
    screen = where_are_we(threshold=threshold, screen=vue)
    scores = score_report(threshold, screen=vue)

    print()
    print(f"Écran reconnu : {screen.value}")
    steps = STEPS_FROM.get(screen)
    if steps:
        print("Pour entrer, il cliquerait : "
              + " puis ".join(f.__name__.lstrip("_").replace("_", " ") for f in steps))
    elif screen is Screen.ADVENTURE:
        print("Une aventure est en cours : elle serait reprise, sans dépenser "
              "de tentative.")

    signants = {key for _, keys in SCREEN_ANCHORS for key in keys}
    signants |= set(ADVENTURE_ANCHORS)
    print()
    print(f"Scores des repères (seuil {threshold:.2f}, * = repère d'écran) :")
    for name, score in sorted(scores.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0))):
        marque = "*" if name in signants else " "
        if score is None:
            print(f"  {marque} {name:<30} FICHIER ABSENT")
        else:
            verdict = "OUI" if score >= threshold else "   "
            print(f"  {marque} {name:<30} {score:.2f}  {verdict}")

    # OÙ SOMMES-NOUS — pas un repère d'écran, une position. Le losange de
    # `player_marker` reste affiché juste au-dessus pour comparaison :
    # c'est en les voyant côte à côte qu'on a compris, le 08/11/2026, que
    # le gabarit suivait un décor de tracé.
    contraste = marqueur_joueur.contraste_du_portrait(
        *marqueur_joueur.portrait_du_hud(vue))
    medaillon = marqueur_joueur.trouver_medaillon(vue, memoire=False)
    print()
    print(f"Médaillon du joueur (portrait du HUD, contraste {contraste:.0f}, "
          f"seuil {marqueur_joueur.SEUIL:.2f}) :")
    if medaillon is None:
        print("    non trouvé — la position retomberait sur le centre de l'écran")
    else:
        print(f"    {medaillon.score:.2f} en {medaillon.point} "
              f"(échelle {medaillon.echelle:.3f})")

    if snap:
        dossier = Path(__file__).resolve().parent / "screenshots"
        dossier.mkdir(exist_ok=True)
        chemin = dossier / f"ecran_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(chemin), vue)
        print()
        print(f"Écran enregistré : {chemin}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostic de navigation : où le bot croit-il être ?"
    )
    parser.add_argument("commande", nargs="?", default="where", choices=["where"],
                        help="where : écran reconnu + score de chaque repère")
    parser.add_argument("--snap", action="store_true",
                        help="enregistrer aussi l'écran dans screenshots/")
    parser.add_argument("--seuil", type=float, default=MATCH_THRESHOLD,
                        help="seuil de correspondance (0.80 par défaut)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    cmd_where(args.snap, args.seuil)


if __name__ == "__main__":
    main()
