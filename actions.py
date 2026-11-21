#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
actions.py

Poser des cartes de la main sur le banc.

--------------------------------------------------------------------
COMMENCE PAR `plan`
--------------------------------------------------------------------
    python actions.py plan     # dit ce qu'il jouerait, SANS toucher à rien
    python actions.py play     # joue pour de vrai

Ce module prend le contrôle de ta souris. `plan` affiche la décision
complète — mana lu, cartes jugées jouables, ordre choisi, coordonnées de
saisie et de dépôt — sans émettre le moindre événement souris. C'est la
façon de vérifier que le raisonnement est juste avant de lui laisser les
commandes, et c'est aussi ce qu'il faut relancer en premier le jour où le
bot fait n'importe quoi.

--------------------------------------------------------------------
TOUTE ACTION EST VÉRIFIÉE
--------------------------------------------------------------------
Un drag peut échouer pour dix raisons : animation en cours, carte non
jouable, clic tombé à côté, mana mal lu. On ne suppose donc JAMAIS
qu'une action a réussi — après chaque pose on relit l'API et on vérifie
que la carte a bien quitté la main. Sans cette vérification, une seule
pose ratée fait boucler le bot indéfiniment sur la même carte.

La comparaison se fait sur le NOMBRE d'exemplaires de chaque code de
carte en main, et non sur le CardID : rien ne garantit qu'un CardID reste
stable quand la carte change de zone, alors que « j'avais deux Gardes en
main, je n'en ai plus qu'un » est vrai dans tous les cas.

--------------------------------------------------------------------
STRATÉGIE
--------------------------------------------------------------------
« Simple et robuste » : on pose l'unité la plus chère qu'on peut payer,
tant qu'il reste de la place. Pas de sorts pour l'instant (ils demandent
souvent une cible, ce qui est une brique à part).

« La plus chère » se juge sur le coût AFFICHÉ à l'écran, pas sur celui
imprimé dans card_sets. Une carte réduite à 1 reste à 6 dans la base :
décider sur la base, c'est passer son tour sans la jouer. La gemme de
mana est donc relue avant chaque pose, exactement comme les stats le sont
avant une attaque. `--base-costs` revient aux coûts imprimés.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import time
from dataclasses import dataclass, field, replace
from typing import List, NamedTuple, Optional, Tuple


import lor_api
from lor_api import Window
from game_state import (
    COST_CALIBRATION_KEY,
    COMBAT_ZONES,
    GEOMETRY_ZONES,
    MAX_BOARD_SIZE,
    OUR_UNITS_ZONES,
    BoardCard,
    GameSnapshot,
    GameStateReader,
    Phase,
    TURN_ORB_REGION,
    cost_gaps,
    enrich_with_live_costs,
    enrich_with_live_stats,
    geometry_is_stable,
    read_costs,
    snapshot_signature,
    zone_center_from_top,
    zone_geometry,
)
import keywords
from mana import ManaPool, can_pay, read_mana_pool, read_nexus_health
import riposte
import spells
import strategy
import stun
from spells import Targeting

LOGGER = logging.getLogger(__name__)

# Les gestes souris vivent dans gestures.py ; on les réimporte ici pour que
# `actions.click`, `actions.drag`… restent les noms que tout le monde
# connaît (tests compris : les espions posés sur `actions.click` marchent,
# les fonctions de ce module résolvent `click` dans leur propre espace).
from gestures import (  # noqa: E402,F401 — réexportés volontairement
    GESTURE_SPEED, HOVER_BEFORE_GRAB, HOLD_DELAY, DROP_SETTLE,
    _pause, set_gesture_speed, move, right_click, click, drag,
)


# ============================================================
# RÉGLAGES
# ============================================================

# Où lâcher une carte pour la poser : sur la RANGÉE D'ATTAQUE, pas sur le
# banc. C'est contre-intuitif — la carte finit bien sur le banc — mais
# c'est la zone de dépôt que le client accepte. Lâcher plus bas, sur le
# banc lui-même, ne pose rien.
#
# La valeur est dérivée de game_state.ZONE_BANDS et non écrite en dur :
# le point visé et le classement des cartes en zones restent ainsi
# forcément cohérents.
PLAY_DROP_ZONE = "attack"
PLAY_DROP_RATIO = zone_center_from_top(PLAY_DROP_ZONE)

# Centre de la zone de l'orbe de fin de tour.
TURN_BUTTON_RATIO = (
    (TURN_ORB_REGION[0][0] + TURN_ORB_REGION[1][0]) / 2,
    (TURN_ORB_REGION[0][1] + TURN_ORB_REGION[1][1]) / 2,
)

# Plafond d'attente après une action. Ce n'est PAS une durée de pause :
# `wait_for_change` rend la main dès que l'état bouge, et ce nombre n'est
# que la limite au-delà de laquelle on considère que rien ne viendra.
# 3 s : un effet visible arrive en une à deux secondes. Au-delà, il ne
# viendra pas, et attendre davantage ne fait que ralentir le chemin
# d'échec — celui qu'on emprunte justement quand quelque chose cloche.
AFTER_PLAY_TIMEOUT = 3.0
AFTER_PLAY_DELAY = 1.1     # animations sans effet observable (sorts résolus)

MAX_PLAYS_PER_TURN = 8     # garde-fou anti-boucle

# Combien de temps attendre la main après une attaque adverse déclarée.
# L'animation de la charge, plus le temps que le jeu rende la priorité :
# quatre secondes couvrent largement les deux, et au-delà il vaut mieux
# rendre la main à la boucle qu'attendre indéfiniment.
BLOCK_PRIORITY_TIMEOUT = 4.0

# Un combat SANS blocage se résout tout seul. Un combat AVEC blocage
# attend un clic sur le bouton « Résoudre » pour continuer — sinon la
# partie reste figée sur le combat, unités engagées, indéfiniment. Ce
# bouton occupe le MÊME emplacement à l'écran que la validation du
# mulligan (cf. mulligan_confirm_ratio), donc on réutilise ce ratio
# plutôt que d'en maintenir un second qui dirait la même chose.
#
# RESOLVE_BUTTON_INITIAL_DELAY laisse le bouton le temps d'apparaître
# avant le premier clic : cliquer trop tôt, avant que le blocage soit
# rendu à l'écran, tomberait sur autre chose (la main, par exemple).
# RESOLVE_BUTTON_RETRY_DELAY espace les clics suivants si le premier n'a
# pas suffi, pour ne pas marteler cette zone à chaque scrutation.
RESOLVE_BUTTON_INITIAL_DELAY = 0.8
RESOLVE_BUTTON_RETRY_DELAY = 2.5

# PILE DE SORTS. Après notre validation, l'adversaire peut RÉPONDRE : son
# sort s'empile sur le nôtre et le jeu attend de nouveau un « OK » de
# nous. Chaque passage de priorité est un clic sur le même bouton, gardé
# par une relecture de la pile (une pile vide ferait du clic une fin de
# tour). STACK_PASS_ATTEMPTS borne les allers-retours ; STACK_RESPONSE_WAIT
# est le temps laissé à l'adversaire pour décider quand l'orbe est grise.
STACK_PASS_ATTEMPTS = 4
STACK_RESPONSE_WAIT = 12.0

# ------------------------------------------------------------
# COÛTS RÉELS
# ------------------------------------------------------------
# Le coût qu'on paie n'est pas celui imprimé sur la carte. Une réduction,
# une majoration, un effet de terrain : la gemme affichée change, le
# cardCode non. Avant de choisir quoi poser, on relit donc la gemme de
# chaque carte en main et c'est cette valeur qui décide — exactement comme
# `enrich_with_live_stats` fait primer l'attaque et les PV affichés sur
# ceux de card_sets avant une attaque ou un blocage.
#
# CE QUE ÇA COÛTE : une lecture de gemme par carte de main réellement
# jouable (cf. `cost_reading_candidates`), une fois par pose, servie par
# le cache de badges indexé sur les pixels. `read_digits` vote entre six
# binarisations, donc ce n'est pas gratuit. Si ça se révèle trop lent ou
# trop bruyant en jeu, mettre False ici suffit à revenir aux coûts
# imprimés — ou passer `--base-costs`, sans toucher au code.
#
# Sans calibration de la gemme (`python actions.py cost --calibrate`),
# la lecture ne fait rien et on retombe silencieusement sur les coûts de
# base : le bot reste fonctionnel, simplement aveugle aux réductions.
READ_SCREEN_COSTS = True

# Combien vaut 1 point de dégât au nexus face à 1 point de valeur d'unité,
# dans le bilan d'une attaque. Au-dessus de 1, le bot devient agressif et
# accepte des échanges perdants pour passer des dégâts ; en dessous, il
# préserve son plateau. 1.0 traite les deux à égalité — c'est le poids
# quand les PV adverses sont INCONNUS ; connus, `nexus_weight` l'augmente
# (voir ci-dessous). C'est le réglage à bouger si le bot te paraît trop
# timide ou trop suicidaire.
NEXUS_DAMAGE_WEIGHT = 1.0

# LE POIDS D'UN DÉGÂT AU NEXUS MONTE QUAND LE NEXUS BAISSE : 40 / PV
# adverses, jamais moins que NEXUS_DAMAGE_WEIGHT, plafonné à
# NEXUS_WEIGHT_CAP. À 30 PV un dégât vaut 1,33 point de plateau ; à 20 PV
# deux ; à 10 PV quatre. Sans ça (logs des 05 et 06/09/2026 : 1, 0 et 3
# attaques par combat, « aucune attaque rentable » à presque tous les
# tours avec le jeton, quatre unités gardées « en défense » face à des 1/1
# Éphémères), le bot optimise sa valeur de plateau jusqu'à la fin et ne
# finit jamais une partie gagnable : perdre un 4/3 pour passer 4 dégâts
# est « défavorable » (-7 + 4) même quand l'adversaire est à 6 PV. Le
# nexus est l'objectif, pas le plateau. Les PV adverses se lisent à
# l'écran (mana.read_nexus_health, police du nexus dans chiffres/N_nexus.png).
NEXUS_WEIGHT_REFERENCE = 40.0
NEXUS_WEIGHT_CAP = 6.0


def nexus_weight(enemy_health: Optional[int], base: float = NEXUS_DAMAGE_WEIGHT) -> float:
    """
    Ce que vaut 1 dégât au nexus adverse, selon ses PV (inconnus : le poids
    de base). `base` vient de la stratégie du deck (`strategy.py`) : un deck
    agressif presse le nexus dès 30 PV, un deck de contrôle attend.
    """
    if enemy_health is None or enemy_health <= 0:
        return base
    return min(NEXUS_WEIGHT_CAP, max(base, NEXUS_WEIGHT_REFERENCE / enemy_health))


# LA STRATÉGIE DU DECK EN COURS. Fixée par `CombatLoop` quand la decklist
# est lue (`strategy.profile_deck`), remise à DEFAULT à chaque combat.
# DEFAULT = exactement l'ancien comportement : les tests qui n'en parlent
# pas jouent comme avant.
STRATEGY = strategy.DEFAULT


def set_strategy(strat: Optional["strategy.Strategy"]) -> "strategy.Strategy":
    global STRATEGY
    STRATEGY = strat or strategy.DEFAULT
    return STRATEGY

# Combien vaut 1 point de soin de notre nexus (Vol d'âme) dans le même
# bilan. Moitié moins qu'un dégât infligé : regagner des PV ne rapproche
# pas de la victoire, ça éloigne de la défaite — utile, mais moins.
LIFESTEAL_WEIGHT = 0.5

# ------------------------------------------------------------
# SORTS
# ------------------------------------------------------------
# Le tri « avec ou sans cible » vit dans spells.py, qui refuse tout ce
# qu'il ne comprend pas. Les sorts sont donc autorisés — mais le verrou
# reste, pour pouvoir tout couper d'une ligne si un cas imprévu se
# présente en jeu.
#
# `cancel_pending_action()` demeure le filet : il rattrape une erreur de
# classification, et sert aussi pour une unité à effet de ciblage.
SPELLS_ENABLED = True

# ------------------------------------------------------------
# RESTRICTIONS DE CARTES
# ------------------------------------------------------------
# À False (le réglage par défaut), le bot TENTE TOUTE CARTE DE SA MAIN.
# Tombent alors :
#   - le verrou `--spells` : les sorts sont joués sans rien demander ;
#   - le refus des cartes absentes de card_sets (coût inconnu) ;
#   - tous les refus de prudence de spells.py — Manifest, Invoke, « pick
#     a », « you may », deux cibles, effet néfaste sur notre propre camp ;
#   - le refus d'une unité dont le pouvoir « Play: » n'a pas de cible
#     trouvable, et celui d'un équipement sans allié à équiper.
#
# NE TOMBENT PAS, parce que ce ne sont pas des choix du bot mais les
# règles du jeu — les enfreindre ne joue pas une carte de plus, ça ne fait
# que promener la souris pour rien :
#   - payer le mana (`can_pay`) ;
#   - la place sur le banc (`free_board_slots`) ;
#   - la vitesse d'un sort (`spells.can_cast_now`) : un sort lent ne part
#     pas pendant un combat, le client le refuse.
#
# CE QUE ÇA COÛTE. Une carte que le bot ne sait pas résoudre est quand
# même déposée : le jeu attend alors une cible que personne ne cliquera.
# Le filet est `cancel_pending_action` — un clic sur une zone vide remet
# la carte en main, sans mana dépensé — et la carte est mise de côté pour
# le tour. C'est donc du temps perdu, pas une partie perdue, à deux
# réserves près : un effet néfaste peut désormais viser nos propres unités
# (on choisit alors la plus petite, cf. spells.choose_target), et une
# fenêtre de choix (Manifest) que le clic d'annulation ne fermerait pas
# obligerait la boucle à passer le tour au bout de ~25 lectures.
#
# Repasser à True — ou lancer avec `--prudent` — restaure exactement
# l'ancien comportement, celui que décrivent les tests.
CARD_RESTRICTIONS = False

# Délai laissé au client pour entrer en mode ciblage après le dépôt.
TARGETING_DELAY = 0.8

# Point d'annulation : une zone VIDE du plateau, où un clic gauche ne
# touche rien. Valeur de départ au bord gauche, à l'écart des cartes et
# des nexus — mais c'est un point à vérifier, pas à croire :
#
#     python actions.py cancel --calibrate
#
# ouvre une capture et te fait désigner la zone vide de ton choix.
CANCEL_POINT_RATIO = (0.03, 0.55)
CANCEL_CALIBRATION_KEY = "cancel_point"

# Marqueurs d'invocation supplémentaire, dans les deux langues possibles
# des card_sets. Heuristique VOLONTAIREMENT approximative : si elle rate,
# on tente une pose que le jeu refuse, et la vérification le détecte. Elle
# évite juste des tentatives inutiles quand le banc est presque plein.
SUMMON_MARKERS = ("summon a", "invoque un", "invoquez un", "invoque une")


# ============================================================
# PRIMITIVES SOURIS
# ============================================================

@dataclass
class ActionLog:
    """Trace de ce qui a été fait (ou serait fait en mode plan)."""

    entries: List[str] = field(default_factory=list)
    # Blocages réalisés en passant (cf. `respond_to_stack`), pour que la
    # boucle de combat les compte même quand ils ne passent pas par
    # `_handle_blocking`.
    blocks: int = 0
    # Mana lu au début et à la fin de l'épisode de pose (None : jamais
    # lu). C'est avec ça que la boucle de combat compte les TOURS : le
    # mana ne remonte qu'au changement de round (cf. CombatLoop).
    mana_start: Optional[int] = None
    mana_end: Optional[int] = None
    # Cartes ÉCARTÉES pendant l'épisode : (nom, code, motif). C'est la
    # matière première de `python journal.py --ecartees` — le classement
    # de ce que le bot ne sait pas encore jouer, tiré des parties réelles
    # et non d'une intuition. Une même carte pour un même motif n'est
    # comptée qu'une fois par épisode.
    rejections: List[tuple] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.entries.append(message)
        LOGGER.info(message)

    def reject(self, card, reason: str) -> None:
        entry = (card.name, card.code, reason)
        if entry not in self.rejections:
            self.rejections.append(entry)

    def note_mana(self, pool) -> None:
        """Retient le mana d'une lecture réussie : le premier, et le dernier."""
        value = getattr(pool, "mana", None)
        if value is None:
            return
        if self.mana_start is None:
            self.mana_start = value
        self.mana_end = value

    def adopt_mana(self, other: "ActionLog") -> None:
        """Reprend les relevés de mana d'un sous-journal (play_hand → play_turn)."""
        if other is None:
            return
        if other.mana_start is not None and self.mana_start is None:
            self.mana_start = other.mana_start
        if other.mana_end is not None:
            self.mana_end = other.mana_end


def cancel_pending_action(window: Window, dry_run: bool = False) -> None:
    """
    Sort d'un mode ciblage ou d'une carte « en l'air ».

    C'est le filet de sécurité du bot. Quand le jeu attend une cible que
    personne ne va cliquer, plus rien n'avance : ni la pose, ni la fin de
    tour, ni la boucle.

    UN CLIC DROIT annule — précision d'Ewan le 02/09/2026, qui remplace
    l'ancien clic gauche sur zone vide. L'avantage est net : un clic droit
    n'INTERAGIT avec rien, donc le point n'a plus besoin d'être
    authentiquement vide. On garde tout de même le point calibré (ou son
    défaut) comme emplacement : rien ne s'y trouve, et si un jour le clic
    droit ne suffisait plus, le clic gauche au même endroit reste le repli
    connu (`CANCEL_WITH_LEFT_CLICK`).

    L'action reste la MOINS destructrice dont on dispose : elle n'engage
    aucune attaque et ne termine pas le tour, contrairement au clic sur
    l'orbe. C'est pour ça qu'elle est tentée en premier partout où quelque
    chose semble coincé.
    """
    x, y = window.rel(*cancel_point_ratio())
    if dry_run:
        LOGGER.info("[plan] annulation : clic gauche sur zone vide en (%d, %d)", x, y)
        return

    if CANCEL_WITH_LEFT_CLICK:
        LOGGER.info("Annulation d'une action en attente (clic gauche en %d, %d).", x, y)
        click(x, y)
    else:
        LOGGER.info("Annulation d'une action en attente (clic droit en %d, %d).", x, y)
        right_click(x, y)
    time.sleep(_pause(0.4, floor=0.15))


# Repli : remettre à True pour retrouver l'annulation par clic gauche sur
# zone vide (comportement d'avant le 02/09/2026).
CANCEL_WITH_LEFT_CLICK = False


def end_turn(window: Window, dry_run: bool = False) -> None:
    """
    Termine le tour en CLIQUANT l'orbe.

    Pas de raccourci clavier : les clics souris sont démontrés fonctionnels
    sur ce client (toute la navigation repose dessus), alors que rien ne
    prouve que le jeu accepte des frappes synthétiques — et le module
    `keyboard` demande en plus des privilèges administrateur sous Windows.
    """
    x, y = window.rel(*TURN_BUTTON_RATIO)
    if dry_run:
        LOGGER.info("[plan] clic fin de tour en (%d, %d)", x, y)
        return
    click(x, y)


def valider_designation_libre(window: Window, dry_run: bool = False) -> None:
    """
    Clôt une désignation EN NOMBRE LIBRE sans désigner personne.

    « Play: Deal 1 to ANY NUMBER OF allies to deal that much to an
    enemy » (Vladimir, 01NX006) : le jeu surligne nos alliés et n'en
    exige aucun. Ewan, 10/11/2026, mot pour mot : « on clique sur
    l'ennemi et on clique sur le bouton bleu à droite de la page ».

    CE BOUTON BLEU EST L'ORBE DE TOUR, mesuré et non supposé. Les deux
    poses de Vladimir du 06/11 ont figé 50 s chacune, et le bot a gardé
    l'écran les deux fois : `screenshots/bloque_ATTACKING_20261106_105937
    .png` et `..._111227.png`. On y voit Vladimir au centre, l'invite
    « Infligez 1 pt(s) de dégâts », nos alliés surlignés — et, à droite
    à mi-hauteur, l'orbe BLEUE portant « PASSER », dans la zone
    `game_state.TURN_ORB_REGION` dont `TURN_BUTTON_RATIO` est le centre.
    Le log dit que l'ennemi avait bien été cliqué (« Ciblage du pouvoir :
    Sapling (1) 2/1 en (1115, 180) ») : il ne manquait que ce clic-ci.

    On ne vise donc AUCUNE coordonnée nouvelle — c'est le point que
    `end_turn`, `play_spell` et `respond_to_stack` cliquent déjà.

    ON NE LIT PAS LE LIBELLÉ POUR DÉCIDER, et c'est volontaire :
    « PASSER » est aussi ce que l'orbe affiche en temps ordinaire, donc
    le voir ne prouverait rien. C'est le PLAN qui sait qu'une
    désignation libre est ouverte (`SpellPlan.free_designation`), et il
    le sait du texte de la carte — la règle du projet, on compte les
    marqueurs, on ne reconnaît pas les sorts.
    """
    x, y = window.rel(*TURN_BUTTON_RATIO)
    if dry_run:
        LOGGER.info("[plan] validation de la désignation libre en (%d, %d)", x, y)
        return
    LOGGER.info("Désignation libre : aucun allié, on valide en (%d, %d).", x, y)
    click(x, y)
    time.sleep(AFTER_PLAY_DELAY)


# ============================================================
# DÉCISION
# ============================================================

def summons_extra_body(card: BoardCard) -> bool:
    description = (card.description or "").lower()
    return any(marker in description for marker in SUMMON_MARKERS)


def spell_is_castable(card: BoardCard, snapshot: GameSnapshot) -> tuple:
    """
    Ce sort est-il jouable maintenant, et sur quoi ?

    Renvoie (jouable, plan, cibles, description). Trois conditions, et
    elles se cumulent :
        1. spells.py comprend l'effet et le ciblage ;
        2. la vitesse autorise le moment présent ;
        3. autant de cibles valables que le sort en réclame existent
           réellement sur le plateau.

    La troisième compte autant que les autres : lancer « Deal 3 to an
    enemy » sans aucun ennemi en jeu laisse le client en attente d'un clic
    impossible.

    `cibles` est un TUPLE de points, jamais un point seul — vide quand
    rien n'est à cliquer (aucune cible, désignation en main, refus), et
    de PLUSIEURS points pour un sort à cibles multiples du même camp
    (cf. spells.SpellPlan.extra_targets, « Deal 2 to an enemy and Stun
    another. » — Lien cosmique, 06BC044). C'est `play_spell` qui les
    clique tous, dans l'ordre.

    Sans restrictions (CARD_RESTRICTIONS à False), la première condition
    ne refuse plus rien : la classification devient permissive, et il ne
    reste que la vitesse et l'existence des cibles. Le verdict garde
    toute son utilité même alors — `play_spell` s'en sert pour savoir
    qu'il faudra probablement annuler après le dépôt.
    """
    plan = spells.classify_card(card, restricted=CARD_RESTRICTIONS)
    if not plan.playable:
        return False, plan, (), plan.reason

    allowed, why = spells.can_cast_now(card, snapshot)
    if not allowed:
        return False, plan, (), why

    if plan.needs_hand_pick:
        available = hand_picks_available(plan, snapshot, card)
        if available < plan.picks:
            return False, plan, (), (
                f"{plan.picks} carte(s) à désigner en main, {available} disponible(s)"
            )
        if plan.needs_board_click_after_hand:
            # LE COÛT EN MAIN NE DISPENSE PAS DE LA CIBLE (14/11/2026).
            # « To play, discard 1. Deal 3 to anything. » : on payait le
            # coût et on ne cliquait jamais la cible — le sort restait en
            # l'air jusqu'au garde d'immobilité. La cible se décide ICI,
            # avec le reste, pour que le refus tombe AVANT la pose comme
            # pour `sort_sans_cible` : poser puis découvrir qu'on n'a
            # rien à cliquer, c'est le blocage qu'on paie déjà.
            sous = plan.board_plan()
            picks = spells.choose_targets(sous, snapshot)
            if len(picks) < sous.total_targets:
                return False, plan, (), (
                    f"sort : {sous.total_targets} cible(s) après la défausse, "
                    f"{len(picks)} disponible(s)"
                )
            return (True, plan, tuple(p for p, _ in picks),
                    str(plan) + " puis " + " puis ".join(d for _, d in picks))
        return True, plan, (), str(plan)

    if not plan.needs_click:
        return True, plan, (), "sans cible"

    if plan.target_condition == "damaged":
        # « a damaged ally » se juge sur les PV AFFICHÉS, que l'instantané
        # ne porte pas par défaut (l'OCR coûte, il n'est fait qu'avant un
        # combat). On le fait ici, pour ce sort-là seulement, et sans
        # lecture d'écran en mode plan hors jeu.
        #
        # SEULEMENT « damaged » (06/11/2026) : la condition « attacking »
        # se lit dans les ZONES de l'instantané, pas à l'écran. Déclencher
        # l'OCR pour elle serait payer une lecture d'écran pour rien, à
        # chaque Tempête d'acier.
        enrich_with_live_stats(snapshot, zones=("board", "attack", "enemy_board", "enemy_attack"))

    if plan.is_trade:
        # Un coût puis une récompense, pesés l'un contre l'autre : sans
        # cible pour l'un des deux pas, ou à perte, le sort attend.
        picks, why = spells.choose_trade_targets(plan, snapshot)
        if why:
            return False, plan, (), why
        return True, plan, tuple(p for p, _ in picks), " puis ".join(d for _, d in picks)

    if plan.total_targets > 1:
        picks = spells.choose_targets(plan, snapshot)
        if len(picks) < plan.total_targets and plan.flexible_targets and picks:
            # « Frostbite 2 enemies » face à UN ennemi (Vents mordants,
            # 02/09/2026) : le jeu prend ce qu'il y a, le sort part sur
            # les cibles présentes. Seul « an enemy ... and another »
            # exige tous ses clics.
            return True, plan, tuple(p for p, _ in picks), (
                " puis ".join(d for _, d in picks)
                + f" ({len(picks)}/{plan.total_targets} cibles en jeu, le sort s'en contente)"
            )
        if len(picks) < plan.total_targets:
            # Moins de cibles que le sort n'en réclame : le jeu resterait
            # en attente d'un clic sur une cible qui n'existe pas.
            #
            # ON REND QUAND MÊME CE QU'ON A TROUVÉ, on ne le jette pas.
            # Le refus suffit à écarter le sort en mode prudent ; mais
            # sans restrictions, `play_spell` tente la pose — et rendre
            # un tuple VIDE lui faisait cliquer ZÉRO fois. Or notre
            # comptage de marqueurs peut sur-compter : s'il n'y avait en
            # vérité qu'une cible à désigner, le clic résout le sort.
            # S'il en fallait bien deux, on n'est pas plus mal qu'avant —
            # `play_spell` annule sur un ciblage INCOMPLET. Vu en jeu le
            # 26/08/2026 sur Lien cosmique (06BC044) : sort posé, aucun
            # clic, personne ciblé.
            return False, plan, tuple(p for p, _ in picks), (
                f"{plan.total_targets} cibles requises, {len(picks)} disponible(s)"
            )
        return True, plan, tuple(p for p, _ in picks), " puis ".join(d for _, d in picks)

    point, description = spells.choose_target(plan, snapshot)
    if point is None:
        if plan.resolves_without_target:
            # « Deal 4 to an enemy. IF THERE ARE NO ENEMIES, deal 4 to
            # the enemy Nexus instead. » — Final Spark, Ace in the Hole,
            # Javelin Toss. Le texte dit ce que devient le sort sur un
            # plateau vide : il part SEUL. Aucune cible n'est donc un
            # état normal, pas un empêchement.
            #
            # ON NE FABRIQUE AUCUN POINT. Rendre ici le nexus adverse
            # ferait un clic que le jeu refuse — c'est le jeu qui
            # redirige, pas nous. Le tuple vide est le livrable :
            # `play_spell` ne clique rien, et surtout n'annule pas.
            return True, plan, (), f"{description} : le sort part seul sur le nexus"
        return False, plan, (), description
    return True, plan, (point,), description


def unit_play_plan(card: BoardCard, snapshot: GameSnapshot) -> tuple:
    """
    Le pouvoir « Play: » de cette unité, s'il exige une cible, et sur
    quoi. Renvoie (plan, point_cible, description).

    plan vaut None quand l'unité n'a pas de « Play: » à cibler : la pose
    reste alors un simple dépôt, sans clic à prévoir — c'est le cas de
    loin le plus fréquent, à ne pas confondre avec un pouvoir refusé.

    Sans ce clic sur les unités concernées (« Play: Frostbite an
    enemy. », par exemple), le jeu garde la carte au centre de l'écran en
    attente d'une cible, exactement comme un sort non ciblé — sauf qu'ici
    rien ne clique jamais, puisque play_card ne prévoyait pas cette
    étape.
    """
    plan = spells.classify_unit_play(card.description, restricted=CARD_RESTRICTIONS)
    if plan is None:
        return None, None, ""
    if plan.effect == "DAMAGE" and plan.amount is None and re.search(
        r"equal to my power", card.description or "", re.I
    ):
        # « Deal damage equal to my Power to a unit » : le montant, c'est
        # l'attaque de la carte — lue à l'écran quand on l'a.
        plan = replace(plan, amount=int(card.attack or 0))

    # L'ORDRE DE CES DEUX TESTS EST LE FOND DU PROBLÈME.
    # `needs_click` ne vaut True que pour les ciblages RECONNUS : un
    # pouvoir REFUSÉ n'a pas de cible, donc `needs_click` est faux. Testé
    # en premier, il renvoyait (None, None, "") — indiscernable d'une
    # unité sans pouvoir. `playable_cards`, qui ne skippe que sur un plan
    # non nul, posait donc l'unité quand même, et la partie restait figée
    # sur une interface que le bot ne sait pas piloter (« Updraft 1 »,
    # « Discard 1 to Manifest... » : 63 unités de la base). Le refus doit
    # remonter AVANT.
    if not plan.playable:
        return plan, None, plan.reason
    if plan.needs_hand_pick:
        # Le point ne se calcule pas ici : il dépend de la carte qu'on
        # décidera de sacrifier, une fois l'unité posée et la main
        # recentrée. play_card s'en charge via designate_in_hand.
        return plan, None, f"{plan.picks} carte(s) à désigner en main"
    if plan.needs_choice:
        # Même raison : les versions proposées n'existent pas encore au
        # moment de décider. play_card s'en charge via resolve_play_choice.
        return plan, None, "choix entre " + " ou ".join(plan.options)
    if not plan.needs_click:
        if plan.opens_card_window:
            # « Play: Manifest a Yordle », « Play: Predict » : rien à
            # cibler sur le plateau, mais une fenêtre à lire après la
            # pose. play_card s'en charge via resolve_card_choice.
            return plan, None, f"fenêtre de cartes ({plan.card_window})"
        return None, None, ""

    point, description = spells.choose_target(plan, snapshot)
    return plan, point, description


def hand_picks_available(plan, snapshot: GameSnapshot, played: BoardCard) -> int:
    """
    Combien de cartes de la main peuvent RÉELLEMENT être désignées.

    Compter la main entière serait faux : « Grant an ally in hand » n'accepte
    qu'une unité, et une main de trois sorts n'en offre aucune. La carte
    qu'on est en train de jouer est exclue — elle n'est déjà plus là quand
    l'interface s'ouvre.
    """
    return len(choose_hand_targets(
        snapshot, plan.picks, plan.pick_type, plan.pick_best, exclude=(played,),
    ))


def sans_allie_a_qui_s_accrocher(card: BoardCard, snapshot: GameSnapshot) -> Optional[str]:
    """
    Motif de refus d'une unité « Attach » posée alors qu'AUCUN allié
    n'est en jeu — None sinon.

    UNE UNITÉ « ATTACH » S'ACCROCHE À UNE AUTRE, ET LE JEU EXIGE QU'ON
    LA DÉSIGNE. Fait de jeu d'Ewan, 11/11/2026, dit en direct pendant la
    partie : « le bot bloque sur Yuumi car il n'y a pas d'unité sur le
    banc ». Mesuré dans `logs/challenges_20261111_130907.log` : TROIS
    paliers d'immobilité de 50-51 s, 152 s au total, tous en phase
    ATTACKING, tous après une pose de Yuumi (05BC029) — les instantanés
    gardés disent `bouton=cible`, `orbe=non`, banc vide. `_check_progress`
    finit par annuler, puis le bot repose la carte au tour suivant.

    CE N'EST PAS DE LA PRUDENCE : le mot-clé est LU dans `keywords` /
    `keywordRefs` de la base, pas déduit d'un texte. C'est donc une
    impossibilité du même ordre que le mana ou la place sur le banc, et
    elle vaut DANS LES DEUX MODES — exactement comme l'équipement sans
    porteur (05/11) et `sort_sans_cible` (08/11). L'annulation rattrape,
    elle ne rend pas le temps.

    DIX CODES, QUATRE CARTES, mesurés sur les 2898 cartes de la base :
    Yuumi (05BC029 + T3/T4/T5), Rainbowfish (05BC019 + T1), Quick Quill
    (05BC066 + T1), Papercraft Dragon (05BC177 + T1). Les quatre sont des
    unités ; trois d'entre elles n'ont AUCUNE description, donc aucun
    plan « Play: » — c'est pour ça que ce test passe AVANT
    `unit_play_plan` plutôt que dans l'une de ses branches.

    LE PÉRIMÈTRE EST CELUI DE L'ÉQUIPEMENT, ET C'EST VOULU. On réutilise
    `equipment_plan`, qui demande une cible ALLIÉE à `spells.choose_target`
    — lequel lit `board` ET `attack_row`. Compter le seul banc serait
    faux : le plateau a deux horloges, et pendant une attaque nos unités
    sont lues au centre, dans `attack`. Une seconde façon de compter les
    alliés finirait par diverger de la première.

    LA NUANCE QU'ON N'ÉCRASE PAS : Yuumi dit « Round Start: Grant the
    unit I'm Attached to +1|+1. OTHERWISE, grant me +1|+1 instead. » —
    elle fonctionne donc sans attache, ce qui laisserait croire qu'on
    peut valider à vide. L'observation dit le contraire : le jeu a
    attendu 50 s, trois fois de suite. S'il existe un geste de validation
    (comme l'orbe de tour pour Vladimir), c'est un FAIT DE JEU et il doit
    venir d'Ewan — on ne l'invente pas.
    """
    if not (card.is_unit or card.is_landmark):
        return None
    if not keywords.has(card, "Attach"):
        return None
    if equipment_plan(card, snapshot)[0] is not None:
        return None
    return "aucun allié à qui s'accrocher (mot-clé Attach)"


def unit_play_blocker(card: BoardCard, snapshot: GameSnapshot) -> Optional[str]:
    """
    Ce qui EMPÊCHE de poser cette unité à cause de son pouvoir « Play: »,
    ou None si rien ne l'empêche.

    Une seule fonction pour la décision (`playable_cards`) et pour son
    explication (`rejection_reason`) : deux implémentations du même test
    finissent toujours par diverger, et c'est alors le diagnostic qui ment.

    Sans restrictions, plus rien n'empêche une pose : la carte est posée
    même sans cible connue, et c'est `cancel_pending_action` qui rattrape
    si le jeu reste en attente.

    UNE SEULE EXCEPTION, ET ELLE SURVIT AUX DEUX MODES : une main qui
    n'offre AUCUNE carte du type demandé. Ce n'est pas de la prudence,
    c'est un fait, du même ordre que le mana ou la place sur le banc — le
    pouvoir ne peut pas se résoudre, la pose finira annulée, et la carte
    sera mise de côté pour le tour. Les sorts appliquaient déjà cette
    règle (`spell_is_castable`) ; les unités, non.
    """
    motif = sans_allie_a_qui_s_accrocher(card, snapshot)
    if motif:
        return motif

    plan, point, description = unit_play_plan(card, snapshot)
    if plan is None:
        return None

    # Même logique que pour les sorts : un pouvoir qui demande deux clics
    # sur le plateau est hors de portée, restrictions ou pas.
    if plan.impossible:
        return description or plan.reason

    if plan.playable and plan.needs_hand_pick:
        available = hand_picks_available(plan, snapshot, card)
        if available < plan.picks:
            return f"{plan.picks} carte(s) à désigner en main, {available} disponible(s)"
        return None

    if plan.playable and plan.needs_choice:
        # La fenêtre de choix se pilote (resolve_play_choice) : rien à
        # vérifier ici, et surtout pas l'absence de cible de plateau — le
        # test `point is None` plus bas bloquerait la carte dans les deux
        # modes alors que c'est justement celle qu'on sait maintenant
        # jouer.
        return None
    if plan.playable and plan.opens_card_window and not plan.needs_click:
        # Même chose pour une fenêtre de cartes (resolve_card_choice) :
        # « Play: Manifest a Yordle » n'a aucune cible de plateau, et ce
        # n'est pas un empêchement.
        return None

    # UNE DÉSIGNATION LIBRE SE VALIDE, MAIS SA CIBLE RESTE OBLIGATOIRE.
    # Vladimir demande un clic sur un ENNEMI puis une validation (cf.
    # `valider_designation_libre`) : sans ennemi en jeu, le premier des
    # deux gestes n'a nulle part où aller, et poser la carte rouvrirait
    # exactement l'attente de 50 s que ce chantier referme. Même famille
    # que l'équipement sans porteur et que `sort_sans_cible` : une
    # impossibilité LUE sur le plateau, donc valable dans LES DEUX MODES
    # — d'où sa place AVANT le court-circuit ci-dessous.
    #
    # La clause est étroite à dessein : elle ne vaut que pour les plans
    # qui portent ce drapeau. Les autres pouvoirs « Play: » sans cible
    # gardent le comportement du mode par défaut — on pose, et
    # l'annulation rattrape.
    if plan.playable and plan.free_designation and plan.needs_click and point is None:
        return description or "aucune cible valable"

    if not CARD_RESTRICTIONS:
        return None

    if not plan.playable:
        return description or plan.reason
    if point is None:
        return description or "aucune cible valable"
    return None


def equipment_plan(card: BoardCard, snapshot: GameSnapshot) -> tuple:
    """
    Sur quelle unité poser cet équipement. Renvoie (point, description).

    Un équipement demande une cible ALLIÉE, comme un renfort — on réutilise
    donc la règle déjà écrite et déjà testée pour les sorts bénéfiques,
    plutôt que d'en écrire une deuxième qui dirait la même chose.

    À DÉFAUT D'UNITÉ, IL N'EST PAS JOUABLE. Ce n'est pas un détail de
    prudence : sans allié, le client resterait en attente d'un clic
    impossible.
    """
    plan = spells.SpellPlan("EQUIP", spells.Targeting.ALLY)
    return spells.choose_target(plan, snapshot)


def sort_sans_cible(card: BoardCard, snapshot: GameSnapshot) -> Optional[str]:
    """
    Motif de refus d'un sort dont le plan réclame une désignation alors
    que l'instantané n'offre RIEN à désigner — None sinon.

    CE N'EST PAS DE LA PRUDENCE, C'EST UNE IMPOSSIBILITÉ LUE SUR LE
    PLATEAU, du même ordre que le mana ou la place sur le banc : le
    refus vaut donc dans LES DEUX MODES. Même famille que « an attacking
    enemy » (06/11/2026) — la condition se lit dans les zones que l'API
    rapporte, et un clic refusé coûte plus cher qu'une carte gardée en
    main.

    Mesuré dans `logs/` au 08/11/2026 : 25 poses lancées en sachant
    qu'aucune cible n'existait (« X : « aucun ennemi en jeu » —
    restrictions levées, on tente et on annulera »), dont 13 ont fini en
    « X toujours sur la pile après validation », 23,3 s perdues chacune
    (303 s au total) et le tour rendu sans être terminé. C'est mot pour
    mot le raisonnement de l'équipement sans porteur (05/11) :
    l'annulation rattrape — il n'y a pas de blocage — mais elle ne rend
    pas le temps.

    DEUX CAS, ET DEUX SEULEMENT :
        - le plan exige un clic de PLATEAU et `spell_is_castable` ne
          trouve AUCUN point ;
        - le plan exige une désignation EN MAIN et la main n'offre pas
          assez de cartes du type demandé — c'est « la disponibilité
          d'une carte à désigner » que `CLAUDE.md` garde dans les deux
          modes, et que `unit_play_blocker` applique déjà aux unités.

    CE QU'ON NE REFUSE PAS, et c'est tout l'équilibre de cette fonction :
        - un sort qui ne clique rien (`needs_click` faux) ;
        - un pluriel COMPTÉ face à moins d'ennemis qu'annoncé
          (« Frostbite 2 enemies » sur un seul ennemi, 02/09) ;
        - un sort à deux cibles strictes dont UNE seule est trouvée :
          `spell_is_castable` rend quand même ce point, et ce clic peut
          résoudre le sort (26/08) — on exige zéro point, pas « moins
          que prévu » ;
        - un REPLI : « effet inconnu sur a unit » sans allié vise un
          ennemi (06/09), et un repli est une cible comme une autre.

    ET SURTOUT PAS LA VITESSE. `spell_is_castable` refuse AUSSI un sort
    lent pendant un combat, et son motif ressortirait d'ici sous un nom
    qui promet exactement le contraire. Mesuré sur la vraie base avec
    une rangée d'attaque occupée : Dawn and Dusk, Shunpo et Guile
    rendaient « sort lent : combat en cours » — un motif de VITESSE que
    `playable_cards` aurait compté comme une absence de cible, et que le
    journal aurait rangé sous ce nom-là. Les deux appelants testent déjà
    `can_cast_now` avant d'arriver ici, donc aucune décision ne change
    aujourd'hui : c'est le piège qu'on désamorce, pour que la fonction
    ne tienne pas uniquement par l'ordre de ses appelants.
    """
    if not spells.can_cast_now(card, snapshot)[0]:
        return None
    castable, plan, targets, why = spell_is_castable(card, snapshot)
    if castable:
        return None
    if plan.needs_click:
        if not targets:
            return why
        # LE NEXUS NE SE CLIQUE QU'UNE FOIS (fait de jeu, Ewan,
        # 09/11/2026). Six sorts réclament DEUX ou TROIS désignations et
        # acceptent le nexus adverse à la place d'une unité — Trueshot
        # Barrage et Solar Snare (trois), Statikk Shock, Shock Blast,
        # Jayce's Shock Blast et Divine Draft (deux). Plateau adverse
        # vide, `choose_targets` ne rend qu'UN point, le nexus, et il ne
        # peut pas tenir lieu des trois : la question « le jeu résout-il
        # un sort avec moins de cibles qu'il n'en annonce ? » était
        # ouverte depuis le 08/11, la réponse est NON — il refuse, rien
        # ne part. Les poser coûtait donc ~23 s d'annulation chacune,
        # pour rien.
        #
        # LA CLAUSE EST ÉTROITE À DESSEIN, et elle ne défait pas la
        # doctrine du 26/08 (« on exige zéro point, pas moins que
        # prévu ») : un sort à deux cibles strictes dont UNE UNITÉ est
        # trouvée garde sa chance, parce que notre comptage de marqueurs
        # peut sur-compter. Ici il n'y a aucune unité du tout — le seul
        # point rendu est le nexus, et le sur-comptage n'y change rien.
        if (plan.total_targets > len(targets)
                and snapshot.enemy_nexus is not None
                and all(point == snapshot.enemy_nexus for point in targets)):
            return (f"{plan.total_targets} cibles à désigner et le nexus "
                    "adverse pour seul point : il ne se clique qu'une fois")
        return None
    if plan.needs_hand_pick:
        return why
    return None


def free_board_slots(snapshot: GameSnapshot) -> int:
    """Places restantes sur le banc, rangée d'attaque comprise."""
    occupied = len(snapshot.board) + len(snapshot.attack_row)
    return max(0, MAX_BOARD_SIZE - occupied)


def playable_cards(
    snapshot: GameSnapshot,
    pool: ManaPool,
    allow_spells: bool = False,
    skip: Optional[set] = None,
) -> List[BoardCard]:
    """
    Cartes de la main qu'on peut poser maintenant, la plus chère d'abord.

    Une carte absente de card_sets est écartée : son coût est inconnu, et
    tenter de la jouer serait un pari sur une donnée qu'on n'a pas.

    SANS RESTRICTIONS (CARD_RESTRICTIONS à False), tout ce paragraphe
    tombe : il ne reste que le mana, la place sur le banc et la vitesse
    des sorts, c'est-à-dire les seules règles que le client fait respecter
    de toute façon. Voir le commentaire de CARD_RESTRICTIONS.
    """
    skip = skip or set()
    slots = free_board_slots(snapshot)
    candidates = []

    for card in snapshot.hand:
        if card.code in skip:
            continue

        if not CARD_RESTRICTIONS:
            # Un type inconnu (carte absente de card_sets) ne réserve pas
            # de place : on ne sait même pas si c'est une unité, et
            # refuser sur un banc plein écarterait un sort pour rien.
            if card.is_unit or card.is_landmark:
                if (2 if summons_extra_body(card) else 1) > slots:
                    continue
                # Un « Play: » qui exige une carte à désigner en main et
                # une main qui n'en offre aucune : la pose ne peut PAS
                # aboutir. Voir unit_play_blocker — dans ce mode, c'est le
                # seul motif qu'il oppose encore.
                if unit_play_blocker(card, snapshot):
                    continue
            if card.is_spell or card.is_ability:
                if not spells.can_cast_now(card, snapshot)[0]:
                    continue
                # TOUS LES REFUS NE SONT PAS DE LA PRUDENCE. Un sort qui
                # demande DEUX clics sur le plateau (« Kill an ally to
                # kill a unit ») ne peut pas aboutir : le bot n'en clique
                # qu'un, et le client reste en attente du second. Lever
                # les restrictions ne donne pas une capacité qu'on n'a
                # pas — ce refus-là vaut dans les deux modes.
                plan = spells.classify_card(card, restricted=False)
                if plan.impossible:
                    continue
                # UN ÉCHANGE SE PÈSE AVANT LE DÉPÔT, même sans restrictions :
                # le filet « on tente et on annule » ne vaut rien quand le
                # premier clic a déjà TUÉ une de nos unités. Pas de cible
                # pour l'un des deux pas, ou échange à perte : on attend.
                if plan.is_trade and spells.choose_trade_targets(plan, snapshot)[1]:
                    continue
                # UN SORT DONT LA CIBLE NE PEUT PAS EXISTER N'EST PAS
                # LANCÉ. Exactement le refus de l'équipement sans porteur
                # ci-dessous, et pour la même raison : l'annulation
                # rattrape, mais elle ne rend pas les 23 s. Voir
                # `sort_sans_cible` pour ce qui est refusé et ce qui ne
                # l'est pas.
                if sort_sans_cible(card, snapshot):
                    continue
            if card.is_equipment and equipment_plan(card, snapshot)[0] is None:
                # UN ÉQUIPEMENT SANS PORTEUR N'A PERSONNE À DÉSIGNER.
                # `CLAUDE.md` garde ce refus dans les DEUX modes — « la
                # disponibilité d'une carte à désigner » — mais il n'était
                # appliqué qu'aux unités et aux sorts.
                #
                # Ce n'est pas un blocage : l'annulation rattrape bien. Ce
                # sont onze secondes perdues par round, à vide. Mesuré le
                # 05/11/2026 : The Darkin Lodestone tentée HUIT fois entre
                # 19:24 et 19:38, banc vide à chaque fois, dans un combat
                # qui a duré neuf minutes.
                continue
            if not can_pay(card, pool):
                continue
            candidates.append(card)
            continue

        # Une carte absente de card_sets a un coût de base à 0 : la jouer
        # serait parier sur une donnée absente. Elle redevient jouable dès
        # que son coût a été lu à l'écran (cf. game_state.read_costs).
        if not card.cost_is_known:
            continue
        if card.is_spell or card.is_ability:
            if not (allow_spells and SPELLS_ENABLED):
                continue
            if not spell_is_castable(card, snapshot)[0]:
                continue
        elif card.is_equipment:
            # Il ne prend pas de place sur le banc — il s'attache — mais il
            # lui faut une unité à équiper, sinon le client attend un clic
            # qui n'a nulle part où aller.
            if equipment_plan(card, snapshot)[0] is None:
                continue
        elif not (card.is_unit or card.is_landmark):
            continue
        else:
            needed = 2 if summons_extra_body(card) else 1
            if needed > slots:
                continue
            # Un pouvoir « Play: » qu'on ne sait pas résoudre — cible
            # introuvable, main trop courte, ou refusé par les mêmes
            # garde-fous que les sorts — laisserait la carte bloquée au
            # centre de l'écran une fois posée.
            if unit_play_blocker(card, snapshot):
                continue
        if not can_pay(card, pool):
            continue
        candidates.append(card)

    # Coût décroissant, puis corpulence : à coût égal, la plus grosse.
    #
    # UNE ÉPHÉMÈRE NE VAUT QUE LE ROUND EN COURS. Posée sans le jeton
    # d'attaque, elle meurt en fin de round sans avoir frappé — et comme
    # elle est presque toujours surdimensionnée pour son coût, le critère
    # de corpulence la faisait passer DEVANT un corps qui reste. À coût
    # égal on lui préfère donc l'unité permanente, sauf quand on a le
    # jeton : là, elle va justement attaquer, et sa taille compte.
    #
    # Jeton illisible (`attack_token is None`) = on suppose que non. Se
    # tromper dans ce sens fait poser une permanente à la place d'une
    # Éphémère — anodin ; l'inverse gaspille une carte.
    swinging = snapshot.attack_token is True
    return sorted(
        candidates,
        key=lambda c: (
            c.cost,
            0 if (keywords.dies_anyway(c) and not swinging) else 1,
            c.attack + c.health,
        ),
        reverse=True,
    )


def choose_card_to_play(
    snapshot: GameSnapshot,
    pool: ManaPool,
    allow_spells: bool = False,
    skip: Optional[set] = None,
) -> Optional[BoardCard]:
    cards = playable_cards(snapshot, pool, allow_spells, skip)
    return cards[0] if cards else None


# ============================================================
# EXÉCUTION
# ============================================================

def drop_point(card: BoardCard, window: Window) -> tuple:
    """
    Où lâcher la carte : à la verticale de sa position, sur la rangée
    d'attaque (cf. PLAY_DROP_RATIO).

    On garde le X de la carte plutôt que de viser le centre du plateau :
    un dépôt au milieu d'un banc déjà peuplé insère la carte entre deux
    unités et change leur ordre, ce dont dépend l'assignation des
    bloqueurs.
    """
    return (card.grab_point[0], int(window.y + PLAY_DROP_RATIO * window.height))


# Attente du RECENTRAGE, à ne pas confondre avec l'attente d'un
# changement d'état. Le plateau de LoR est centré : quand une carte quitte
# une rangée, toutes les autres glissent vers le milieu pendant une
# fraction de seconde. Pendant ce temps l'API renvoie déjà le nouveau
# contenu des zones, mais des rectangles EN COURS DE VOL.
SETTLE_POLL = 0.2
SETTLE_TIMEOUT = 2.0


def wait_until_settled(
    reader,
    snapshot: GameSnapshot,
    zones: tuple = GEOMETRY_ZONES,
    poll: float = SETTLE_POLL,
    timeout: float = SETTLE_TIMEOUT,
    confirmations: int = 1,
) -> GameSnapshot:
    """
    Attend que les cartes ARRÊTENT DE BOUGER, et renvoie la dernière
    lecture. `snapshot` sert de première mesure : on ne relit donc qu'une
    fois de plus quand le plateau est déjà immobile.

    C'EST CE QUI MANQUAIT AUX ENGAGEMENTS EN CHAÎNE. Relire la position
    entre deux gestes ne suffit pas si la relecture tombe au milieu de
    l'animation : à trois unités ou plus sur le banc, le décalage dépasse
    la largeur d'une carte et la saisie suivante rate sa cible.

    `confirmations` : combien de relectures consécutives doivent être
    immobiles. 1 suffit pour un recentrage (une seule animation) ; une
    PIOCHE EN SÉRIE (« Draw 2 », Slipstream, Pick a Card au début du
    round) enchaîne plusieurs vols séparés de pauses plus longues que
    `poll`, et une seule relecture immobile tombe entre deux cartes.
    """
    geometry = zone_geometry(snapshot, zones)
    deadline = time.time() + timeout
    quiet = 0
    while time.time() < deadline:
        time.sleep(poll)
        latest = reader.stable_snapshot(confirmations=1, poll=poll, timeout=poll)
        latest_geometry = zone_geometry(latest, zones)
        if geometry_is_stable(geometry, latest_geometry):
            quiet += 1
            if quiet >= max(1, confirmations):
                return latest
        else:
            quiet = 0
        snapshot, geometry = latest, latest_geometry
    LOGGER.debug("Le plateau bouge encore après %.1f s : on agit sur la dernière lecture.", timeout)
    return snapshot


def wait_for_change(reader, before, timeout: float = 6.0, poll: float = 0.3, settle: bool = True):
    """
    Attend que l'état visible change, et rend la main dès que c'est le cas.

    Remplace les `sleep` de durée fixe. Un délai en dur est faux dans les
    deux sens : trop court sur une machine lente, il lit un état
    intermédiaire ; trop long sur une machine rapide, il perdait du temps
    à chaque action — et il y en a des dizaines par combat.

    Avec `settle` (par défaut), la fonction ne rend PAS la main au premier
    instantané qui diffère : elle attend en plus la fin du recentrage. Les
    deux attentes sont distinctes et toutes les deux nécessaires — le
    contenu des zones change au dépôt, les positions une animation plus
    tard. Rendre la main entre les deux livre des coordonnées périmées à
    l'appelant, qui s'en sert pour viser à la souris.

    Renvoie le premier instantané qui diffère (stabilisé), ou le dernier
    lu si rien n'a bougé avant l'échéance.
    """
    deadline = time.time() + timeout
    snapshot = reader.stable_snapshot(confirmations=1, poll=poll, timeout=timeout)
    while time.time() < deadline:
        if snapshot_signature(snapshot) != before:
            return wait_until_settled(reader, snapshot) if settle else snapshot
        time.sleep(poll)
        snapshot = reader.stable_snapshot(confirmations=1, poll=poll, timeout=timeout)
    return snapshot


def settled_snapshot(reader, poll: float = 0.3, timeout: float = 4.0) -> GameSnapshot:
    """
    Une lecture dont les POSITIONS sont utilisables pour viser à la souris.

    `stable_snapshot(confirmations=1)` ne fait attendre RIEN DU TOUT : la
    phase est confirmée dès la première lecture, qui tombe donc en pleine
    animation. C'est suffisant pour savoir ce que contiennent les zones,
    jamais pour savoir où sont les cartes — les deux horloges du plateau,
    encore (cf. wait_until_settled).

    Le piège s'est refermé sur ELORA (98PZ007), « Play: Create an exact
    copy of a spell in hand » : la main venait de perdre la carte posée,
    elle se recentrait, et le clic de désignation partait sur la position
    d'AVANT le recentrage — à côté du sort visé.
    """
    first = reader.stable_snapshot(confirmations=1, poll=poll, timeout=timeout)
    return wait_until_settled(reader, first)


def relocate_card(
    snapshot: GameSnapshot,
    card: BoardCard,
    zone: str,
    skip: Optional[set] = None,
) -> Optional[BoardCard]:
    """
    Retrouve la MÊME carte dans un instantané plus récent, avec ses
    coordonnées à jour. None si elle n'y est plus.

    POURQUOI CETTE FONCTION EXISTE.
    Un `BoardCard` porte des coordonnées d'écran figées au moment de la
    lecture. Or le plateau de LoR est CENTRÉ : dès qu'une unité quitte le
    banc, toutes les autres se réalignent. Les points de saisie calculés
    avant le premier geste ne désignent donc plus les bonnes cartes — au
    mieux on attrape la voisine, au pire le vide.

    La décision (qui attaque, qui bloque) se prend une fois sur un
    plateau cohérent ; l'exécution, elle, doit relire les coordonnées
    entre chaque geste. C'est exactement le partage que fait cette
    fonction : on garde le choix, on rafraîchit la position.

    L'identité vient du `CardID` de l'API, stable pour une instance. En
    dernier recours on retombe sur le code de carte : deux exemplaires
    d'une même carte sont interchangeables pour ce qu'on veut en faire.
    """
    skip = skip or set()
    pool = [
        c for c in snapshot.zones.get(zone, ())
        if not (c.card_id >= 0 and c.card_id in skip)
    ]

    if card.card_id >= 0:
        for candidate in pool:
            if candidate.card_id == card.card_id:
                return candidate

    for candidate in pool:
        if candidate.code == card.code:
            return candidate
    return None


# VISER DANS LA MAIN SUR UNE LECTURE FRAÎCHE.
#
# Ewan, 05/09/2026 (deck Nilah : Slipstream, Pick a Card, Vikrash — le jeu
# PIOCHE PLUSIEURS FOIS au début du round, et à chaque pioche la main se
# recentre) : « le bot tentait de jouer quelque chose alors que le jeu a
# pioché plusieurs fois ». La décision se prenait sur une lecture, puis
# l'OCR des coûts durait une à deux secondes, et la saisie partait sur
# les coordonnées de cette lecture : la voisine était attrapée (un sort
# inconnu 07BW043 s'est retrouvé sur la pile à la place de Slotbot, et le
# jeu a attendu une cible 50 s), ou le vide (« toujours en main »).
#
# Une lecture de plus de AIM_MAX_AGE secondes ne sert donc plus à viser :
# on relit, on attend que la main soit IMMOBILE (HAND_QUIET_CONFIRMATIONS
# relectures de suite, le temps que la série de pioches finisse) et on
# retrouve la carte par son CardID. Hors ligne, décision et geste sont
# instantanés : rien n'est relu, les scénarios préparés restent valables.
AIM_MAX_AGE = 0.8
HAND_QUIET_CONFIRMATIONS = 3
HAND_SETTLE_TIMEOUT = 6.0


def fresh_hand_card(reader, snapshot: GameSnapshot, card: BoardCard, max_age: float = AIM_MAX_AGE):
    """
    La carte à saisir, avec des coordonnées assez fraîches pour viser.

    Rend (carte, instantané) : les mêmes objets si `snapshot` est récent ;
    sinon la carte relue dans une main immobile, et cette relecture.
    (None, relecture) si la carte n'est plus en main.
    """
    age = time.time() - getattr(snapshot, "taken_at", time.time())
    if age <= max_age:
        return card, snapshot
    latest = wait_until_settled(
        reader,
        reader.stable_snapshot(confirmations=1, poll=SETTLE_POLL, timeout=SETTLE_POLL),
        zones=("hand",), timeout=HAND_SETTLE_TIMEOUT,
        confirmations=HAND_QUIET_CONFIRMATIONS,
    )
    refreshed = relocate_card(latest, card, "hand")
    if refreshed is None:
        LOGGER.warning(
            "%s n'est plus dans la main au moment de la saisir (lecture vieille de %.1f s).",
            card.name, age,
        )
        return None, latest
    if refreshed.grab_point != card.grab_point or len(latest.hand) != len(snapshot.hand):
        LOGGER.info(
            "La main a bougé depuis la lecture (%.1f s, %d -> %d cartes) : saisie de %s "
            "recalée %s -> %s.",
            age, len(snapshot.hand), len(latest.hand), card.name,
            card.grab_point, refreshed.grab_point,
        )
    return refreshed, latest


# ============================================================
# DÉSIGNER UNE CARTE DANS LA MAIN
# ============================================================
# « Play: Updraft 1 », « Play: Discard a card to draw 1 », « Equip me with
# an equipment from hand » : le jeu attend un clic dans NOTRE MAIN, pas
# sur une unité du plateau. C'est une interface pilotable — les cartes de
# la main sont dans l'état rapporté par l'API, avec leur position — mais
# elle demande deux choses que le ciblage plateau n'exige pas.
#
# 1. UNE DÉCISION DE JEU : laquelle sacrifier. Le classement du texte
#    (spells.py) dit COMBIEN de cartes désigner ; il ne peut pas dire
#    lesquelles, parce que ça dépend de la main du moment.
# 2. UNE RELECTURE ENTRE CHAQUE CLIC. La main se recentre dès qu'une
#    carte la quitte, exactement comme le banc entre deux engagements.
#    Le deuxième clic d'un « Updraft 2 » calculé d'avance désignerait la
#    voisine.

# Le jeu peut mettre un instant à ouvrir la fenêtre de désignation, et
# l'animation qui l'accompagne déplace les cartes. On lui laisse le temps
# plutôt que de renoncer à la première lecture.
DESIGNATION_TIMEOUT = 5.0
DESIGNATION_POLL = 0.3


def find_our_card(snapshot: GameSnapshot, card: BoardCard, skip=()) -> Optional[BoardCard]:
    """
    Retrouve NOTRE carte par `CardID`, DANS N'IMPORTE QUELLE ZONE.

    POURQUOI PAS `relocate_card("hand")`.
    La bande « hand » ne fait que 3 % de la hauteur de la fenêtre
    (ZONE_BANDS) : les cartes en main dépassent sous le bord bas de
    l'écran, et c'est ce qui les distingue du banc. Or QUAND LE JEU
    DEMANDE DE DÉSIGNER UNE CARTE DE LA MAIN, IL LA REMONTE pour la
    rendre cliquable — c'est l'animation où les cartes concernées
    s'entourent de bleu. Leur ancre repasse alors au-dessus de 0.030 et
    `classify_zone` les range dans « board ».

    Chercher dans « hand » à cet instant ne trouve plus rien : le bot
    renonçait sans avoir cliqué, puis annulait. Le `CardID`, lui, ne
    bouge pas — c'est la seule identité fiable pendant l'animation.
    """
    skip = set(skip or ())
    pool = [
        c for c in snapshot.cards()
        if c.local and not (c.card_id >= 0 and c.card_id in skip)
    ]
    if card.card_id >= 0:
        for candidate in pool:
            if candidate.card_id == card.card_id:
                return candidate
    for candidate in pool:
        if candidate.code == card.code:
            return candidate
    return None


def wait_for_designation_target(
    reader, card: BoardCard, skip=(), timeout: float = DESIGNATION_TIMEOUT,
) -> tuple:
    """
    Attend que la carte à désigner soit VISIBLE ET IMMOBILE. Renvoie
    (carte_à_jour, instantané) ; la carte vaut None si elle n'est jamais
    apparue.

    Les deux attentes comptent. Visible : la fenêtre de désignation met un
    instant à s'ouvrir. Immobile : elle s'ouvre EN ANIMANT les cartes, et
    viser pendant ce trajet, c'est cliquer à côté (cf. settled_snapshot).
    """
    deadline = time.time() + timeout
    latest = settled_snapshot(reader)
    found = find_our_card(latest, card, skip)
    while found is None and time.time() < deadline:
        time.sleep(DESIGNATION_POLL)
        latest = settled_snapshot(reader)
        found = find_our_card(latest, card, skip)
    return found, latest


def _notre_carte_est_encore_la(snapshot: GameSnapshot, card: BoardCard) -> bool:
    """
    CETTE carte-là est-elle encore à nous, quelque part à l'écran ?

    PAR CardID, SANS REPLI PAR CODE — et c'est toute la différence
    avec `find_our_card`. Celle-ci cherche une carte à CLIQUER :
    attraper une jumelle de même code y est sans conséquence, les
    deux exemplaires étant identiques. Constater un DÉPART, non : le
    repli trouve la jumelle restée en main et conclut que rien n'est
    parti.

    Mesuré le 15/11/2026, deck Twisted Fate — deux Wild Card en main,
    `Get Excited!` en défausse une, et le bot déclare « le clic n'a
    pas pris » 12 fois dans la session. Le log montre pourtant les
    deux états à la suite : `Wild Card#1204492146` et
    `Wild Card#1625478173` avant, la seule `#1625478173` après.

    C'est la règle que `_left_zone` applique déjà aux zones depuis
    les deux Thrall Bulwark du banc ; elle manquait ici. Le comptage
    par code reste le repli des cartes SANS identifiant, où il est la
    seule identité disponible.
    """
    if card.card_id >= 0:
        return any(
            c.local and c.card_id == card.card_id for c in snapshot.cards()
        )
    return find_our_card(snapshot, card) is not None


def wait_until_card_left(
    reader, card: BoardCard, snapshot: GameSnapshot,
    timeout: float = DESIGNATION_TIMEOUT,
) -> tuple:
    """
    Attend que la carte disparaisse de NOTRE côté. Renvoie (partie, instantané).

    Sert de vérification aux désignations qui CONSOMMENT la carte
    (« Discard 1 », « Updraft 1 »). Comme `find_our_card`, ça ne regarde
    pas la zone : pendant que la fenêtre se referme, les cartes restantes
    redescendent vers la main, et une lecture prise à cet instant les
    range n'importe où.
    """
    latest = snapshot
    deadline = time.time() + timeout
    while _notre_carte_est_encore_la(latest, card) and time.time() < deadline:
        time.sleep(DESIGNATION_POLL)
        latest = settled_snapshot(reader)
    return not _notre_carte_est_encore_la(latest, card), latest


def wait_until_placed(
    reader, card: BoardCard, before_placed: dict, snapshot: GameSnapshot,
    timeout: float = DESIGNATION_TIMEOUT,
) -> GameSnapshot:
    """
    Laisse à la carte le temps d'ARRIVER sur le plateau avant de conclure
    qu'elle est restée en l'air. Renvoie la dernière lecture.

    « Partie de la main, arrivée nulle part » est la signature du mode
    ciblage, et `play_card` annule quand il la voit. Mais c'est aussi, une
    seconde durant, ce à quoi ressemble un pouvoir qui VIENT de se
    résoudre : l'unité traverse l'écran depuis le centre. Conclure trop
    tôt, c'est annuler une pose réussie — on ne le fait donc qu'après
    avoir laissé l'animation finir.
    """
    latest = snapshot
    deadline = time.time() + timeout
    while (
        _placed_counts(latest).get(card.code, 0) <= before_placed.get(card.code, 0)
        and time.time() < deadline
    ):
        time.sleep(DESIGNATION_POLL)
        latest = settled_snapshot(reader)
    return latest


def is_dead_weight(card: BoardCard) -> bool:
    """
    Cette carte est-elle un fardeau POUR LE BOT ?

    Pas « mauvaise dans l'absolu » : injouable par lui. Une carte absente
    de card_sets ne sera jamais posée faute de coût connu, et un sort que
    le classifieur refuse ne sera jamais lancé. Ces cartes occupent une
    place en main sans aucune chance d'en sortir — ce sont les meilleures
    candidates au sacrifice, et ça n'a rien à voir avec leur valeur pour
    un joueur humain.
    """
    if not card.cost_is_known:
        return True
    if card.is_spell or card.is_ability:
        # LA MÊME QUESTION QUE LA DÉCISION, DANS LE MÊME MODE. L'appel
        # était fait SANS argument, donc `restricted=True` — le mode
        # PRUDENT — même quand le bot joue sans restrictions. Des sorts
        # parfaitement jouables passaient donc pour du fardeau pur :
        # premiers défaussés au mulligan, derniers renforcés, derniers
        # choisis dans une fenêtre. Mesuré le 09/11/2026 sur la base
        # entière : **75 sorts collectionnables sur 566** (13 %) étaient
        # dans ce cas — Deny, Condemn, Brutal Skirmish, Bone Skewer,
        # Boomerang Blade… Le piège est documenté depuis le 06/11 (les
        # trois sorts « Activate »), il a mordu encore deux fois dans la
        # nuit du 08-09/11 (les 14 sorts « transform », puis Ebb and
        # Flow), et il se refermait à chaque fois sur un cas particulier
        # au lieu de la cause.
        return not spells.classify_card(card, restricted=CARD_RESTRICTIONS).playable
    return False


def sacrifice_rank(card: BoardCard) -> tuple:
    """Clé de tri : la première carte du classement est la plus sacrifiable."""
    return (
        0 if is_dead_weight(card) else 1,   # le fardeau pur d'abord
        -card.cost,                          # puis la plus chère : elle dort le plus longtemps
        card.attack + card.health,           # à coût égal, la plus maigre
    )


def boost_rank(card: BoardCard) -> tuple:
    """
    Clé de tri inverse : la première carte est la meilleure RECEVEUSE.

    Un renfort sur une carte qu'on ne jouera jamais est perdu, d'où le
    fardeau relégué en dernier. Vient ensuite la moins chère — celle qu'on
    posera le plus tôt, donc celle dont le bonus servira le plus vite —
    puis la plus grosse à coût égal.
    """
    return (
        1 if is_dead_weight(card) else 0,
        card.cost,
        -(card.attack + card.health),
    )


def matches_pick_type(card: BoardCard, pick_type: str) -> bool:
    """
    Ce type de carte peut-il être désigné ?

    « Grant an ally in hand +3|+3 » n'accepte qu'une UNITÉ : cliquer un
    sort ne déclenche rien, et le jeu reste en attente d'un clic valide.
    """
    if pick_type == "unit":
        return card.is_unit
    if pick_type == "spell":
        return card.is_spell or card.is_ability
    if pick_type == "equipment":
        return card.is_equipment
    return True


# ============================================================
# CHOIX DE VERSION À LA POSE
# ============================================================
# « Play: Play me as First Wave or Last Wind. » — Les ailes et la vague
# (04SI004), vue en jeu le 22/08/2026. Le jeu remplace la carte posée par
# les DEUX versions au centre de l'écran et attend qu'on en clique une.
#
# CE BLOCAGE-LÀ N'A PAS DE FILET. Le choix est obligatoire : le clic sur
# une zone vide ne le referme pas, le bouton de passe non plus. Sans clic,
# la partie ne repart jamais — `_check_progress` épuise ses trois
# escalades et la tentative hebdomadaire est perdue.
#
# Ce qui le rend PILOTABLE, contrairement à Manifest : les deux versions
# sont nommées dans le texte de la carte (`spells.play_as_options`), donc
# on sait quoi chercher à l'écran. Et l'API rapporte ces cartes-là comme
# elle rapporte celles du mulligan, qui s'affichent au même endroit.
#
# On les reconnaît par leur NOM plutôt que par leur position : la fenêtre
# n'est pas une zone du plateau, sa hauteur ne veut rien dire, et les
# ranger dans une bande serait inventer une géométrie de plus.

def _folded(name: str) -> str:
    """Nom réduit à ses lettres et chiffres, pour comparer sans piège."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def offered_versions(
    snapshot: GameSnapshot, options, exclude_ids=(),
) -> List[BoardCard]:
    """
    Les versions proposées, retrouvées à l'écran par leur nom.

    `exclude_ids` écarte ce qui était DÉJÀ là avant la pose : rien
    n'interdit d'avoir une Première vague sur le banc quand on en propose
    une seconde, et cliquer l'unité déjà posée ne résoudrait rien.
    """
    wanted = {_folded(name) for name in options}
    return [
        card for card in snapshot.cards()
        if card.local
        and _folded(card.name) in wanted
        and card.card_id not in exclude_ids
    ]


def version_rank(card: BoardCard) -> tuple:
    """
    Clé de tri des versions proposées : la MEILLEURE en dernier (max).

    Un prix à la pose passe en dernier, avant toute considération de
    corpulence : « To play me, kill an ally » ouvre une SECONDE interface
    après le choix, et c'est une occasion de plus de figer la partie. Une
    3|3 gratuite vaut mieux qu'une 3|3 payée d'un allié — et à défaut de
    version gratuite, c'est la seule qu'on ait.
    """
    return (
        0 if spells.has_extra_cost(card.description) else 1,
        card_value(card),
        -card.cost,
    )


def choose_offered_version(cards: List[BoardCard]) -> BoardCard:
    """Laquelle des versions proposées poser."""
    return max(cards, key=version_rank)


def resolve_play_choice(
    reader, plan, before: GameSnapshot, dry_run: bool = False,
) -> tuple:
    """
    Clique une des versions proposées. Renvoie (carte_choisie, instantané, détail).

    `carte_choisie` vaut None quand la fenêtre n'a pas été reconnue — et le
    détail dit alors CE QU'ON A VU, pas seulement qu'on n'a rien trouvé :
    c'est la seule façon de distinguer « l'API ne rapporte pas cette
    fenêtre » de « les noms ne correspondent pas ».

    `before` est l'état d'AVANT le dépôt : il sert à ignorer les cartes du
    même nom déjà en jeu.
    """
    described = " ou ".join(plan.options)
    if dry_run:
        return None, before, f"choisirait entre {described}"

    known_ids = {c.card_id for c in before.cards() if c.card_id >= 0}
    deadline = time.time() + DESIGNATION_TIMEOUT
    latest = settled_snapshot(reader)
    offered = offered_versions(latest, plan.options, known_ids)
    while not offered and time.time() < deadline:
        time.sleep(DESIGNATION_POLL)
        latest = settled_snapshot(reader)
        offered = offered_versions(latest, plan.options, known_ids)

    if not offered:
        seen = ", ".join(
            f"{c.name}[{c.zone}]" for c in latest.cards() if c.local
        ) or "aucune"
        LOGGER.warning(
            "Fenêtre de choix introuvable (%s). Nos cartes à l'écran : %s",
            described, seen,
        )
        return None, latest, (
            f"aucune version ({described}) reconnue à l'écran (vu : {seen})"
        )

    chosen = choose_offered_version(offered)
    LOGGER.info(
        "Choix de version : %s en %s (zone lue : %s), parmi %s",
        chosen.name, chosen.grab_point, chosen.zone,
        ", ".join(c.name for c in offered),
    )
    click(*chosen.grab_point)
    if spells.has_extra_cost(chosen.description):
        # Elle sera cliquée quand même — le choix est obligatoire — mais
        # le prix à payer ouvre une interface de plus, que personne
        # n'honore ici. Le dire au journal évite de chercher la cause
        # ailleurs.
        LOGGER.warning(
            "%s réclame un prix à la pose (« %s ») : une seconde interface "
            "peut s'ouvrir.", chosen.name, chosen.description.splitlines()[0],
        )
    latest = settled_snapshot(reader)
    return chosen, latest, (
        f"{chosen.name} choisie parmi {', '.join(c.name for c in offered)}"
    )


# ============================================================
# CHOIX IMPRÉVU : la fenêtre qu'aucun plan n'annonçait
# ============================================================
# Nidalee (07SH013, vue en jeu le 04/09/2026) : « Quick Attack. Ambush 2 ».
# Rien dans son texte ne dit « Play me as », et elle est de toute façon
# ABSENTE de card_sets (set7.json ne compte que 83 cartes). Pourtant sa
# pose ouvre une fenêtre à deux versions — elle-même, ou l'embuscade —
# et le jeu n'écoute plus rien tant qu'aucune n'est cliquée. Le bot, qui
# ne prévoyait rien, concluait « posée » (la version affichée au centre
# porte son code et tombe dans la bande « attack », que `_placed_counts`
# compte) ou « partie sans arriver » puis annulait — dans les deux cas la
# fenêtre restait béante.
#
# Le filet ne lit pas de texte : il regarde ce qui est À L'ÉCRAN. Deux
# cartes à nous ou plus, NOUVELLES (CardID inconnu avant la pose), hors
# main et hors banc, juste après un dépôt = une fenêtre de choix. C'est
# le même critère que `offered_cards` pour les fenêtres de Manifest,
# appliqué sans qu'un plan l'ait demandé — donc valable pour les cartes
# inconnues comme pour un mot-clé qu'on ne modélise pas.
#
# LE CHOIX : `version_rank` (sans prix à la pose, la plus corpulente),
# et à égalité LA CARTE JOUÉE ELLE-MÊME — deux inconnues ont toutes deux
# des stats à 0, et entre Nidalee et une embuscade dont on ne sait rien
# faire, c'est la championne qu'on voulait poser.

# Après « partie de la main, arrivée nulle part », combien de temps
# guetter une fenêtre avant de conclure au mode ciblage et d'annuler.
UNFORESEEN_CHOICE_GLANCE = 2.5


def unforeseen_choice_rank(card: BoardCard, played: BoardCard) -> tuple:
    """Clé de tri : `version_rank`, puis la carte jouée elle-même."""
    same = 1 if (card.code == played.code or _folded(card.name) == _folded(played.name)) else 0
    return (
        0 if spells.has_extra_cost(card.description) else 1,
        card_value(card),
        same,
        -card.cost,
    )


def resolve_unforeseen_choice(
    reader, card: BoardCard, before: GameSnapshot, latest: GameSnapshot,
    wait: bool, timeout: float = UNFORESEEN_CHOICE_GLANCE,
    arrivee=None,
) -> tuple:
    """
    Clique dans une fenêtre de choix qu'on n'attendait pas.
    Renvoie (carte_choisie, instantané, détail) ; `carte_choisie` vaut
    None quand aucune fenêtre n'est visible.

    `wait` : guetter la fenêtre pendant `timeout` (la carte a quitté la
    main sans arriver nulle part : soit une cible attendue, soit une
    fenêtre en train de s'ouvrir). Faux quand la lecture montre déjà la
    carte sur le banc : on ne regarde qu'une fois, sans rien attendre.

    `arrivee` : une question posée à CHAQUE lecture — « la carte est-elle
    arrivée ? ». Dès que oui, on arrête de guetter.

    ON N'ATTENDAIT PLUS POUR RIEN, MAIS ON ATTENDAIT JUSQU'AU BOUT.
    La règle « on ne guette que si la carte n'est pas déjà sur le banc »
    existe depuis le 04/09/2026 — elle n'était évaluée qu'UNE FOIS, avant
    la boucle. Or au moment où on la pose, la carte est TOUJOURS en train
    de voler : elle arrive une demi-seconde plus tard, et le guet
    continuait quand même jusqu'à ses 2,5 s, à chaque pose.
    Mesuré le 10/11/2026 sur la tentative gagnée de la veille : 6,77 s de
    médiane entre « Pose de X » et « X posée », pour un plancher
    théorique de 0,80 s — l'API répond en 67 ms (médiane sur 25 lectures,
    min 66, max 67), et trois confirmations d'immobilité coûtent 0,20 s
    de réseau. 35 poses par tentative.

    LE FILET N'EST PAS TOUCHÉ, et c'est la raison pour laquelle la
    question porte sur le BANC et pas sur « posée » au sens large : quand
    une vraie fenêtre s'ouvre, la version affichée au centre porte le
    code de la carte jouée dans la bande « attack » — jamais sur le banc.
    Une carte réellement arrivée sur le banc est donc la preuve qu'aucune
    fenêtre n'est ouverte, et c'est exactement ce que la règle d'origine
    voulait dire.
    """
    known_ids = {c.card_id for c in before.cards() if c.card_id >= 0}
    offered = offered_cards(latest, known_ids)
    deadline = time.time() + (timeout if wait else 0)
    while len(offered) < 2 and time.time() < deadline:
        if arrivee is not None and arrivee(latest):
            break
        time.sleep(DESIGNATION_POLL)
        latest = settled_snapshot(reader)
        offered = offered_cards(latest, known_ids)
    if len(offered) < 2:
        return None, latest, "aucune fenêtre imprévue"

    chosen = max(offered, key=lambda c: unforeseen_choice_rank(c, card))
    LOGGER.warning(
        "Fenêtre de choix IMPRÉVUE après %s (texte non modélisé%s) : %s "
        "retenue en %s (zone lue : %s), parmi %s",
        card.name, "" if card.known else ", carte absente de card_sets",
        chosen.name, chosen.grab_point, chosen.zone,
        ", ".join(f"{c.name}[{c.zone}]" for c in offered),
    )
    click(*chosen.grab_point)
    latest = settled_snapshot(reader)
    return chosen, latest, (
        f"{chosen.name} choisie parmi {', '.join(c.name for c in offered)}"
    )


def _plan_handles_windows(plan) -> bool:
    """Le plan prévoit-il déjà une fenêtre (version, variante, cartes) ?"""
    return plan is not None and (
        plan.needs_choice or plan.may_offer_variants or plan.opens_card_window
    )


# ============================================================
# CHOIX DE VARIANTE : « +2|+0 OR +0|+2 »
# ============================================================
# « Give an ally +2|+0 or +0|+2 this round. » — Choix capital (06IO034),
# vu en jeu le 22/08/2026 : le bot cliquait l'allié tout de suite, sans
# avoir choisi laquelle des deux versions lancer.
#
# DEUX INTERFACES À LA SUITE, ET L'ORDRE EST IMPOSÉ PAR LE JEU : la
# variante d'abord, la cible ensuite. C'est la seule différence avec le
# choix de version des « Play me as A or B » — là, le choix REMPLAÇAIT la
# carte ; ici il la précise, et le ciblage suit.
#
# Les versions ne sont pas nommées dans le texte : elles portent le NOM DE
# LA CARTE JOUÉE (06IO034T1 et T2 s'appellent tous deux « Momentous
# Choice »). On les retrouve donc par ce nom-là, et on les départage par
# ce qu'elles accordent.

_GAIN_RX = re.compile(r"\+(\d+)\|\+(\d+)")


def variant_gain(card: BoardCard) -> tuple:
    """
    Ce que cette version accorde : (force, vie).

    Deux formes dans la base, et il faut les deux : un SORT le dit dans sa
    description (« Give an ally +2|+0 this round. »), une UNITÉ le porte
    dans ses statistiques (Scaled Snapper propose un 5|2 ou un 2|5).
    """
    match = _GAIN_RX.search(card.description or "")
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (card.attack, card.health)


def variant_rank(card: BoardCard, plan, swinging: bool) -> tuple:
    """
    Clé de tri des versions proposées : la MEILLEURE en dernier (max).

    Quatre critères, du plus contraignant au plus fin — les trois
    premiers ne parlent pas de force de jeu mais de ce que le bot SAIT
    FAIRE, et c'est délibéré : entre deux effets qu'on ne sait pas
    comparer, mieux vaut celui qu'on sait exécuter jusqu'au bout.

    1. EXÉCUTABLE. La version est classée comme n'importe quelle carte
       (`spells.classify_card`) : celle qui demanderait deux clics ou une
       fenêtre inconnue passe derrière.
    2. MÊME CIBLE QUE LE PLAN. Le clic de ciblage est décidé sur le texte
       du PARENT et part juste après ; prendre une version qui ne le
       veut pas, c'est cliquer dans le vide. « Deal 2 to a unit or deal 1
       to two enemies » (Bouncing Bomb) se règle là : la première version
       accepte le clic prévu, la seconde non.
    3. MOT-CLÉ MODÉLISÉ. « Grant an ally Spellshield or Overwhelm »
       (Iula) : on prend celui dont `keywords.resolve_duel` tient compte.
       Ce n'est pas « le meilleur », c'est celui qu'on sait chiffrer.
    4. STATISTIQUES, selon le round : la force quand on a le jeton
       d'attaque — elle se convertit en dégâts dès ce tour — les points
       de vie sinon. Règle choisie par Ewan le 22/08/2026 ; jeton
       illisible vaut « on ne l'a pas ».
    """
    # Une UNITÉ se lit par son déclencheur « Play: », pas par sa
    # description entière — sinon « Play: Grant an ally Overwhelm » passe
    # pour un verbe inconnu (le motif d'effet est ancré en tête) et les
    # deux versions d'Iula se valent à tort.
    if card.is_unit:
        version = spells.classify_unit_play(
            card.description, restricted=CARD_RESTRICTIONS,
        ) or spells.SpellPlan("AUCUN", spells.Targeting.NONE)
    else:
        version = spells.classify_card(card, restricted=CARD_RESTRICTIONS)
    executable = version.playable and not version.impossible
    same_target = version.targeting is plan.targeting if plan is not None else False
    power, health = variant_gain(card)
    stats = (power, health) if swinging else (health, power)
    return (
        executable,
        same_target,
        keywords.names_a_modelled_keyword(card.description),
    ) + stats


def choose_variant(cards: List[BoardCard], plan, swinging: bool) -> BoardCard:
    """Laquelle des versions proposées lancer. Voir `variant_rank`."""
    return max(cards, key=lambda c: variant_rank(c, plan, swinging))


# Combien de temps on cherche une fenêtre dont on n'est PAS sûr qu'elle
# existe. Un coup d'œil, pas une attente : la plupart des « ou » de la
# base élargissent une cible au lieu d'ouvrir une fenêtre, et leur faire
# payer cinq secondes à chaque lancement coûterait plus que tout ce que
# ce mécanisme rapporte.
VARIANT_GLANCE = 0.6


def resolve_variant_choice(
    reader, card: BoardCard, plan, before: GameSnapshot, swinging: bool,
    dry_run: bool = False,
) -> tuple:
    """
    Clique la version à lancer. Renvoie (carte_choisie, instantané, détail).

    Même mécanique que `resolve_play_choice` — ne jamais cliquer à
    l'aveugle, dire ce qu'on a vu quand on ne reconnaît rien — avec deux
    différences qui viennent de la carte elle-même :

    - LES VERSIONS PORTENT LE NOM DE LA CARTE JOUÉE. Le texte ne les
      nomme pas (« Grant an ally Spellshield or Overwhelm ») ; les jetons,
      eux, s'appellent tous « Iula ». C'est donc sous ce nom qu'on les
      cherche, et `before` fournit les `CardID` déjà connus — ce qui
      écarte la carte jouée comme un exemplaire déjà en jeu.
    - ON N'EST PAS TOUJOURS SÛR QU'UNE FENÊTRE S'OUVRE. Quand le plan
      l'affirme (`needs_variant`, la forme chiffrée), on l'attend ; quand
      il dit seulement qu'elle est possible (un « ou » dans le texte), on
      jette un coup d'œil et on repart. Ne rien trouver n'est alors pas
      une anomalie : c'est la réponse.
    """
    if dry_run:
        sens = "la force" if swinging else "les points de vie"
        return None, before, f"choisirait la version qui donne {sens}"

    required = plan is not None and plan.needs_variant
    known_ids = {c.card_id for c in before.cards() if c.card_id >= 0}
    deadline = time.time() + (DESIGNATION_TIMEOUT if required else VARIANT_GLANCE)
    latest = settled_snapshot(reader)
    offered = offered_versions(latest, (card.name,), known_ids)
    while not offered and time.time() < deadline:
        time.sleep(DESIGNATION_POLL)
        latest = settled_snapshot(reader)
        offered = offered_versions(latest, (card.name,), known_ids)

    if not offered:
        seen = ", ".join(
            f"{c.name}[{c.zone}]" for c in latest.cards() if c.local
        ) or "aucune"
        if required:
            LOGGER.warning(
                "Aucune version de %s à l'écran alors que le texte en promet "
                "deux. Nos cartes : %s", card.name, seen,
            )
        else:
            LOGGER.info(
                "Pas de fenêtre de versions pour %s : le « ou » de son texte "
                "élargissait une cible.", card.name,
            )
        return None, latest, (
            f"aucune version de {card.name} reconnue à l'écran (vu : {seen})"
        )

    chosen = choose_variant(offered, plan, swinging)
    LOGGER.info(
        "Version retenue pour %s : « %s » en %s (jeton d'attaque : %s), "
        "parmi %s",
        card.name, (chosen.description or "").splitlines()[0][:60],
        chosen.grab_point, "oui" if swinging else "non",
        " / ".join((c.description or "?").splitlines()[0][:40] for c in offered),
    )
    click(*chosen.grab_point)
    latest = settled_snapshot(reader)
    return chosen, latest, f"version « {(chosen.description or '').splitlines()[0][:48]} »"


# ============================================================
# FENÊTRE DE CARTES : MANIFEST, INVOKE, PREDICT, TELLSTONES...
# ============================================================
# « Manifest a landmark you can afford », « Invoke », « Play: Predict »,
# « Create a Fleeting A, B, or C in hand », « Pick 1 of 3 champions » : le
# jeu affiche deux ou trois cartes au centre de l'écran et attend qu'on en
# clique UNE. Le choix est obligatoire, comme pour « Play me as A or B ».
#
# CE QU'ON NE SAIT PAS : ce que la fenêtre contiendra — Manifest invente
# ses cartes à la volée, Predict montre le haut de notre deck. Le texte ne
# nomme rien qu'on puisse chercher. CE QU'ON SAIT : l'API rapporte les
# cartes affichées là, avec leur cardCode, comme celles du mulligan et
# des fenêtres de version (vu en jeu par Ewan). Et chacune est une carte
# NOUVELLE : son CardID n'existait pas avant la pose. C'est ce critère —
# et non un nom, ni une hauteur — qui les distingue de tout le reste.
#
# La main et le banc sont exclus du repérage : une carte piochée ou une
# unité invoquée entre-temps est nouvelle elle aussi, mais elle n'est pas
# à choisir. Les cartes de la fenêtre, elles, flottent au milieu.
#
# QUAND : à la RÉSOLUTION, donc après les interfaces du lancement (cible,
# désignation en main). Immédiat pour une unité ou un sort Burst ; après
# la validation et la réponse adverse pour un sort Fast/Slow — d'où un
# délai plus long dans ce cas (`CARD_WINDOW_SLOW_TIMEOUT`).
#
# ENCHAÎNEMENTS : « Repeat two more times » (Sputtering Songspinner),
# « Invoke a low, medium, and high cost Celestial card » (Trifecta)
# ouvrent plusieurs fenêtres à la suite. Après chaque clic on jette un
# coup d'œil (`CARD_WINDOW_CHAIN_GLANCE`) : de nouvelles cartes inconnues
# valent une nouvelle fenêtre ; rien, c'est fini.

CARD_WINDOW_SLOW_TIMEOUT = 15.0
CARD_WINDOW_CHAIN_GLANCE = 1.2
# Même à résolution immédiate, la fenêtre suit l'ANIMATION de ce qui la
# précède — la défausse de « Discard 1 to Invoke » (Spacey Sketcher,
# 02/09/2026) met plus d'une seconde à partir avant que les cartes
# n'apparaissent. Les 5 s de DESIGNATION_TIMEOUT sont trop justes.
CARD_WINDOW_TIMEOUT = 10.0
MAX_CHAINED_WINDOWS = 4
# Zones où une carte NOUVELLE n'est PAS une carte à choisir. La rangée
# d'attaque n'y est PAS : une UNITÉ affichée au centre de l'écran tombe
# dans la bande de la pile, que `game_state` rebaptise « attack » pour
# toute unité (les deux horloges du plateau). Les unités d'une fenêtre
# sont donc lues dans « attack » — comme l'étaient déjà celles des
# fenêtres de version — et rien de neuf n'y arrive autrement pendant
# qu'on pose une carte.
_NOT_A_WINDOW_ZONE = ("hand", "board")
# LE MIROIR, POUR UNE FENÊTRE QUI MONTRE SES CARTES À LUI (05/11/2026).
# Yoink! (98SB003) pioche « from the enemy hand » : les trois cartes
# proposées sont rapportées avec LocalPlayer=FALSE, et elles tombent dans
# la bande `enemy_attack` (mesuré : 257x374 en TopLeftY=789 sur 1080,
# ratio 0.64). Ses zones de REPOS sont donc sa main et son banc ; tout le
# reste est le centre de l'écran. Un SORT proposé y serait requalifié
# « stack » par `reconcile_combat_rows` (un sort ne tient pas dans une
# rangée d'attaque) : la bande de la pile reste donc autorisée elle aussi.
_NOT_A_WINDOW_ZONE_THEIRS = ("enemy_hand", "enemy_board")


def offered_cards(
    snapshot: GameSnapshot, known_ids, side: str = "ours",
) -> List[BoardCard]:
    """
    Les cartes NOUVELLES hors de leurs zones de repos : la fenêtre.

    `side` dit de QUEL CAMP sont les cartes proposées — « ours » pour
    Manifest, Invoke, Predict et compagnie, « theirs » pour les sept
    cartes de la base qui piochent « from the enemy hand/deck »
    (`spells.card_window_side`). Le critère ne change pas : un CardID
    qui n'existait pas avant la pose.
    """
    theirs = side == "theirs"
    forbidden = _NOT_A_WINDOW_ZONE_THEIRS if theirs else _NOT_A_WINDOW_ZONE
    return [
        card for card in snapshot.cards()
        if bool(card.local) != theirs
        and card.card_id >= 0
        and card.card_id not in known_ids
        and card.zone not in forbidden
    ]


# ------------------------------------------------------------------
# LE FILET GÉOMÉTRIQUE : UNE FENÊTRE QU'AUCUN CARDID N'A SU NOMMER
# ------------------------------------------------------------------
# UNE FENÊTRE DE CHOIX NE S'ANNULE PAS, et c'est ce qui coûte cher : le
# 05/11/2026 le bot a lancé Yoink!, n'a pas reconnu la fenêtre, a cliqué
# droit (sans effet), puis a attendu 184 s devant « SÉLECTIONNER LA
# CIBLE » avant d'abandonner le combat — une tentative hebdomadaire.
#
# Le camp (`offered_cards(side=)`) règle les sept cartes que la base
# annonce. Reste tout ce qu'on ne sait pas lire : une carte absente de
# card_sets, un texte qu'aucun motif ne couvre. Pour celles-là on ne
# reconnaît plus une carte, on reconnaît UNE FENÊTRE — par sa forme.
#
# MESURES, sur la trace du 05/11 (4192 lectures d'API, toutes traces
# confondues) : les cartes d'une fenêtre sont les PLUS GRANDES de
# l'écran (257x374 contre 176x246 en main et 127x160 au banc), il y en a
# au moins deux, et elles partagent le MÊME BORD HAUT (789 pour les
# trois). Ce qui leur ressemble et n'en est pas : le survol grossit UNE
# seule carte (248x361), et l'éventail de la main en grossit six mais à
# des hauteurs toutes différentes (tops 395 à 465). Avec ces trois
# conditions plus l'exclusion des zones de repos, 182 lectures sur 4192
# sont retenues — et ce sont les mulligans, les fenêtres de version et
# celle de Yoink!, c'est-à-dire de vraies fenêtres.
WINDOW_MIN_CARDS = 2
WINDOW_SAME_SIZE = 0.95          # écart toléré entre cartes d'une fenêtre
WINDOW_BIGGER_THAN_REST = 1.25   # fois la plus grande carte du reste
WINDOW_ALIGN_RATIO = 0.02        # de la hauteur de fenêtre
# Les zones où une carte est POSÉE, jamais proposée. Une fenêtre s'ouvre
# au centre : sans ce garde-fou, une main alignée (6 cartes, même taille,
# même bord haut) passerait pour une fenêtre — mesuré, 1003 lectures sur
# 4192 au lieu de 182.
_RESTING_ZONES = ("hand", "board", "enemy_board", "enemy_hand")


def visible_card_window(snapshot: GameSnapshot) -> List[BoardCard]:
    """
    Les cartes d'une fenêtre de choix repérée PAR SA FORME, ou [].

    Ne demande ni plan, ni état d'avant, ni base de cartes : c'est le
    dernier recours, celui qui vaut pour une carte dont on ne sait rien.
    """
    mesures = [(c, c.box[3] - c.box[1]) for c in snapshot.cards() if c.card_id >= 0]
    if len(mesures) < WINDOW_MIN_CARDS:
        return []
    tallest = max(h for _, h in mesures)
    if tallest <= 0:
        return []
    seuil = tallest * WINDOW_SAME_SIZE
    group = [c for c, h in mesures if h >= seuil]
    if len(group) < WINDOW_MIN_CARDS:
        return []
    # Même bord haut : c'est ce qui sépare une fenêtre d'une main
    # déployée en éventail, dont les cartes sont grandes mais étagées.
    tops = [c.box[1] for c in group]
    tolerance = max(8.0, WINDOW_ALIGN_RATIO * snapshot.window.height)
    if max(tops) - min(tops) > tolerance:
        return []
    # Plus grandes que tout le reste : c'est ce qui sépare une fenêtre du
    # survol d'une carte (une seule) et d'une rangée ordinaire.
    reste = [h for _, h in mesures if h < seuil]
    if reste and tallest < max(reste) * WINDOW_BIGGER_THAN_REST:
        return []
    # Hors des zones de repos : une carte posée n'est jamais proposée.
    if all(c.zone in _RESTING_ZONES for c in group):
        return []
    return group


# --- départager deux cartes offertes qui se valent sur le papier ------
#
# RÈGLE DE JEU D'EWAN, 15/11/2026, sur les trois Destiny Cards de
# Twisted Fate : « en fonction de si plusieurs unités ont 2 hp, si on a
# peu de carte en main ou besoin de piocher, et si on doit stun un
# ennemi fort ». Trois signaux, trois cartes — et le bot prenait la
# première de l'ordre de lecture, 10 fois sur 10 le 15/11, parce que
# leurs clés `card_pick_rank` sont STRICTEMENT ÉGALES (1, 0, 0, 0) :
# trois sorts jouables, non-unités, de valeur 0, à coût 0.
#
# L'ÉCHELLE EST CELLE DES ÉCHANGES, pas un barème neuf : `unit_value`
# (attaque + PV) pour ce qu'on tue, l'ATTAQUE pour ce qu'on étourdit —
# « le tempo d'un round », comme `choose_trade_targets` le chiffre déjà.
# Seule la pioche demandait un nombre, parce que rien dans le projet ne
# la chiffrait encore : elle ne vaut que main courte, et c'est
# exactement ce qu'Ewan en dit.
MAIN_COURTE = 3
VALEUR_PIOCHE_MAIN_COURTE = 2.0
VALEUR_PIOCHE = 0.5


def valeur_immediate(card: BoardCard, snapshot: GameSnapshot) -> float:
    """
    Ce que la carte rapporterait si elle se résolvait MAINTENANT.

    Rend 0.0 dès que le texte ne promet rien de lisible — et c'est le cas
    de l'écrasante majorité des cartes offertes (Manifest, Invoke…), qui
    vont EN MAIN et ne se résolvent pas tout de suite. Pour celles-là
    rien ne change : le critère arrive en DERNIER dans `card_pick_rank`,
    donc il ne départage que des cartes déjà à égalité parfaite.
    """
    try:
        effet = spells.lire_effet_immediat(card)
    except Exception:  # noqa: BLE001 — une lecture ne doit jamais décider d'un plantage
        return 0.0

    valeur = 0.0
    ennemis = [c for c in list(snapshot.enemy_board) + list(snapshot.enemy_attack_row)
               if c.is_unit]

    if effet.degats and effet.zone_ennemis:
        # « plusieurs unités ont 2 hp » : ce que la zone NETTOIE.
        valeur += sum(keywords.unit_value(e) for e in ennemis
                      if e.health <= effet.degats)
    elif effet.degats or effet.stun:
        # Mono-cible désigné par le JEU (« the strongest enemy ») : on
        # pèse sur l'ennemi qu'il prendra, c'est-à-dire le plus fort.
        cible = max(ennemis, key=keywords.unit_value, default=None)
        if cible is not None:
            if effet.degats >= cible.health:
                valeur += keywords.unit_value(cible)
            elif effet.stun:
                valeur += cible.attack

    if effet.nexus_aussi and effet.degats:
        # LES PV DU NEXUS NE SONT PAS DANS L'INSTANTANÉ : ils viennent de
        # l'OCR, que `plan_attack` déclenche explicitement. On ne va pas
        # le payer pour départager deux cartes déjà à égalité — c'est la
        # leçon d'« an attacking enemy » (06/11, « ET SURTOUT PAS D'OCR
        # POUR ÇA »). Poids de BASE, donc, celui de la stratégie du deck
        # en cours — exactement ce que `actions.py attack --plan`
        # utilisait avant le 10/11, et le même ordre de grandeur.
        valeur += effet.degats * nexus_weight(None, STRATEGY.nexus_base_weight)

    if effet.pioche:
        # « peu de carte en main ou besoin de piocher ».
        en_main = len(snapshot.hand)
        taux = (VALEUR_PIOCHE_MAIN_COURTE if en_main <= MAIN_COURTE
                else VALEUR_PIOCHE)
        valeur += effet.pioche * taux

    return valeur


def card_pick_rank(card: BoardCard, snapshot=None) -> tuple:
    """
    Clé de tri des cartes proposées : la MEILLEURE en dernier (max).

    Ce n'est pas la valeur pour un joueur humain, c'est ce que le bot
    SAURA FAIRE de la carte une fois en main : d'abord une carte qu'il
    peut jouer (`is_dead_weight` écarte l'inconnue et le sort refusé),
    puis une unité — c'est ce qu'il joue le mieux — la plus corpulente,
    et à égalité la moins chère, qu'on posera le plus tôt.

    LE DERNIER CRITÈRE DÉPARTAGE LES ÉGALITÉS PARFAITES, et rien d'autre
    (15/11/2026). Sans lui, `max` rendait la première de l'ordre de
    lecture — le tirage à pile ou face vu trois fois : Yuumi (11/11),
    Volibear (14/11) et les trois Destiny Cards de Wild Card (15/11, 10
    fois sur 10 « Blue Card »). Il vaut 0.0 sans instantané et pour tout
    texte qui ne promet rien d'immédiat, donc il ne peut jamais renverser
    un choix que les quatre premiers critères tranchaient déjà.
    """
    return (
        0 if is_dead_weight(card) else 1,
        1 if card.is_unit else 0,
        card_value(card),
        -card.cost,
        0.0 if snapshot is None else valeur_immediate(card, snapshot),
    )


def choose_offered_card(cards: List[BoardCard], snapshot=None) -> BoardCard:
    """
    Laquelle des cartes proposées prendre.

    `snapshot` est facultatif : sans lui le choix est exactement celui
    d'avant le 15/11/2026. Les appelants qui l'ont le passent, parce que
    certaines fenêtres offrent des cartes qui se résolvent TOUT DE SUITE
    (« Play a Destiny Card. ») et que leur valeur dépend alors du plateau.
    """
    return max(cards, key=lambda c: card_pick_rank(c, snapshot))


def resolve_card_choice(
    reader, card: BoardCard, plan, before: GameSnapshot,
    dry_run: bool = False, timeout: float = CARD_WINDOW_TIMEOUT,
) -> tuple:
    """
    Clique une carte dans la fenêtre. Renvoie (cartes_choisies, instantané, détail).

    `cartes_choisies` est vide quand aucune fenêtre n'a été vue avant
    `timeout` — et le détail dit alors ce qu'on a vu, comme pour les
    versions. `before` est l'état d'AVANT la pose : tout ce qui y figure
    déjà n'est pas à choisir.
    """
    label = plan.card_window if plan is not None else "fenêtre de cartes"
    side = getattr(plan, "card_window_side", "ours") if plan is not None else "ours"
    if dry_run:
        camp = " (cartes de l'adversaire)" if side == "theirs" else ""
        return [], before, f"choisirait une carte dans la fenêtre ({label}){camp}"

    known_ids = {c.card_id for c in before.cards() if c.card_id >= 0}
    chosen_all: List[BoardCard] = []
    deadline = time.time() + timeout
    latest = before

    for round_index in range(MAX_CHAINED_WINDOWS):
        latest = settled_snapshot(reader)
        offered = offered_cards(latest, known_ids, side)
        while not offered and time.time() < deadline:
            time.sleep(DESIGNATION_POLL)
            latest = settled_snapshot(reader)
            offered = offered_cards(latest, known_ids, side)

        if not offered:
            if chosen_all:
                break   # pas de fenêtre suivante : l'enchaînement est fini

            # DERNIER RECOURS : LA FORME. Aucun CardID neuf du bon camp,
            # mais des cartes alignées au centre et plus grandes que tout
            # le reste — c'est une fenêtre, et une fenêtre ne s'annule
            # pas. Mieux vaut un clic sur la carte la mieux classée que
            # 184 s d'attente et un combat abandonné (05/11/2026).
            secours = visible_card_window(latest)
            if secours:
                pick = choose_offered_card(secours, latest)
                LOGGER.warning(
                    "Fenêtre de cartes (%s) non identifiée par CardID, mais "
                    "%d cartes alignées au centre : on prend %s en %s "
                    "(une fenêtre ne s'annule pas).",
                    label, len(secours), pick.name, pick.grab_point,
                )
                click(*pick.grab_point)
                chosen_all.append(pick)
                known_ids.update(c.card_id for c in secours)
                deadline = time.time() + CARD_WINDOW_CHAIN_GLANCE
                continue

            seen = ", ".join(
                f"{c.name}[{c.zone}]" for c in latest.cards() if c.local
            ) or "aucune"
            # TOUTES les cartes, camp compris : si le jeu rapporte la
            # fenêtre avec LocalPlayer=False, c'est ici qu'on le verra.
            LOGGER.warning(
                "Fenêtre de cartes introuvable (%s, %s, cartes %s). Connues "
                "avant : %s. À l'écran : %s",
                card.name, label,
                "de l'adversaire" if side == "theirs" else "à nous",
                sorted(known_ids),
                ", ".join(
                    f"{c.name}#{c.card_id}[{c.zone}]{'' if c.local else '(adv)'}"
                    f"@{c.grab_point}" for c in latest.cards()
                ) or "aucune",
            )
            return [], latest, (
                f"aucune fenêtre de cartes ({label}) reconnue à l'écran (vu : {seen})"
            )

        pick = choose_offered_card(offered, latest)
        LOGGER.info(
            "Fenêtre de cartes (%s) : %s en %s (zone lue : %s), parmi %s",
            label, pick.name, pick.grab_point, pick.zone,
            ", ".join(c.name for c in offered),
        )
        click(*pick.grab_point)
        chosen_all.append(pick)
        # Tout ce qui vient d'être proposé est désormais connu : une
        # SECONDE fenêtre se reconnaît à des cartes encore plus neuves.
        known_ids.update(c.card_id for c in offered)
        deadline = time.time() + CARD_WINDOW_CHAIN_GLANCE

    latest = settled_snapshot(reader)
    return chosen_all, latest, (
        " puis ".join(c.name for c in chosen_all) + f" pris dans la fenêtre ({label})"
    )


def choose_hand_targets(
    snapshot: GameSnapshot,
    count: int,
    pick_type: str = "any",
    pick_best: bool = False,
    exclude=(),
) -> List[BoardCard]:
    """Les `count` cartes de la main à désigner, la première d'abord."""
    excluded = {c.card_id for c in exclude if c.card_id >= 0}
    candidates = [
        c for c in snapshot.hand
        if c.card_id not in excluded and matches_pick_type(c, pick_type)
    ]
    return sorted(candidates, key=boost_rank if pick_best else sacrifice_rank)[:count]


def choose_hand_sacrifice(
    snapshot: GameSnapshot, count: int, exclude=(),
) -> List[BoardCard]:
    """Les `count` cartes les moins utiles : le cas d'un coût à payer."""
    return choose_hand_targets(snapshot, count, exclude=exclude)


def designate_in_hand(
    reader,
    snapshot: GameSnapshot,
    picks: int,
    pick_type: str = "any",
    pick_best: bool = False,
    exclude=(),
    dry_run: bool = False,
    consumes: bool = True,
) -> tuple:
    """
    Clique `picks` cartes de notre main. Renvoie (succès, instantané, détail).

    LA VÉRIFICATION NE COMPTE PAS LES CARTES, ELLE SUIT L'IDENTITÉ.
    « Updraft 1 to draw 1 » rend une carte pour une : la main a la même
    taille avant et après, et un décompte conclurait à l'échec. On vérifie
    donc que la carte DÉSIGNÉE, elle, a bien quitté la main — son `CardID`
    est stable, c'est un fait vérifiable là où la taille de la main n'est
    qu'une coïncidence.

    ENCORE FAUT-IL QU'ELLE SOIT CENSÉE PARTIR, et c'est ce que dit
    `consumes` (spells.SpellPlan.pick_consumes). « Discard 1 » retire la
    carte ; « Create an exact copy of a spell in hand » (Elora) et
    « Grant an ally in hand +3|+3 » la laissent exactement où elle est —
    treize cartes de la base sont dans ce cas. Exiger leur départ, c'était
    conclure à l'échec d'un clic RÉUSSI, puis annuler une pose déjà
    résolue.

    Quand la carte reste, aucune vérification locale n'est possible : rien
    ne distingue « cliquée » de « pas cliquée » dans l'état rapporté. On
    rend donc la main sans verdict, et c'est `play_card` qui tranchera —
    l'unité posée arrive sur le plateau si le pouvoir s'est résolu, et
    l'annulation reste le filet dans le cas contraire.

    `snapshot` EST L'ÉTAT OÙ L'ON DÉCIDE, PAS CELUI OÙ L'ON CLIQUE.
    On le prend AVANT le dépôt, quand la main est encore une main : c'est
    là que « quel sort copier » a un sens. Les POSITIONS, elles, sont
    relues juste avant chaque clic — et cherchées par `CardID` dans toutes
    les zones, parce que la fenêtre de désignation remonte les cartes hors
    de la bande « hand » (cf. find_our_card).
    """
    # `consumes` NE DOIT PAS être demandé quand une fenêtre de cartes suit
    # (« Discard 1 to Invoke », Spacey Sketcher, 02/09/2026) : la carte
    # défaussée est restée rapportée par l'API pendant plus de 7 s alors
    # que la fenêtre d'Invoke était déjà ouverte à l'écran. Attendre son
    # départ, c'était conclure « le clic n'a pas pris », annuler, et
    # laisser la fenêtre béante. Dans ce cas, c'est l'apparition des
    # cartes proposées qui prouve la désignation — resolve_card_choice
    # s'en charge, et son propre délai couvre l'échec du clic.
    chosen = choose_hand_targets(snapshot, picks, pick_type, pick_best, exclude)
    if len(chosen) < picks:
        quoi = "" if pick_type == "any" else f" de type {pick_type}"
        return False, snapshot, (
            f"{picks} carte(s){quoi} à désigner, {len(chosen)} disponible(s) en main"
        )

    described = ", ".join(str(c) for c in chosen)
    if dry_run:
        return True, snapshot, f"désignerait {described}"

    latest = snapshot
    done = []
    for card in chosen:
        current, latest = wait_for_designation_target(
            reader, card, skip={c.card_id for c in done if c.card_id >= 0},
        )
        if current is None:
            # Le diagnostic dit CE QU'ON A VU, pas seulement qu'on n'a pas
            # trouvé : sans ça, « introuvable » ne distingue pas une
            # fenêtre qui ne s'est pas ouverte d'une carte mal identifiée.
            vues = ", ".join(
                f"{c.name}[{c.zone}]" for c in latest.cards() if c.local
            ) or "aucune"
            LOGGER.warning("Désignation impossible. Nos cartes à l'écran : %s", vues)
            return False, latest, f"{card.name} introuvable à l'écran (vu : {vues})"

        LOGGER.info("Désignation en main : %s en %s (zone lue : %s)",
                    current, current.grab_point, current.zone)
        click(*current.grab_point)
        t_click = time.time()
        # Relecture STABILISÉE : la main se recentre après chaque départ,
        # et le clic suivant se calcule sur ces coordonnées-là.
        latest = settled_snapshot(reader)
        # Journal de ce qu'on voit APRÈS le clic : c'est la seule trace qui
        # dira, en partie réelle, si la désignation a pris (carte partie),
        # si le jeu attend une confirmation (carte encore là, même zone) ou
        # si la fenêtre suivante s'est ouverte (cartes nouvelles).
        LOGGER.info("Après le clic de désignation, nos cartes : %s",
                    _describe_ours(latest))

        if consumes:
            gone, latest = wait_until_card_left(reader, current, latest)
            if not gone:
                LOGGER.warning("%s n'est pas partie ; à l'écran : %s",
                               current.name, _describe_ours(latest))
                return False, latest, (
                    f"{current.name} est toujours à l'écran : le clic n'a pas pris"
                )
            LOGGER.info("%s a quitté l'écran (%.1f s).", current.name,
                        0.0 if latest is None else time.time() - t_click)
        done.append(current)

    if consumes:
        return True, latest, f"désigné {described}"
    return True, latest, (
        f"désigné {described} (la carte reste en main : "
        "vérification renvoyée à la pose)"
    )


def _describe_ours(snapshot: GameSnapshot) -> str:
    """« Nom#id[zone]@(x, y) » pour chacune de nos cartes : le journal doit
    permettre de rejouer une désignation ratée sans la revoir."""
    return ", ".join(
        f"{c.name}#{c.card_id}[{c.zone}]@{c.grab_point}"
        for c in snapshot.cards() if c.local
    ) or "aucune"


def _zone_counts(snapshot: GameSnapshot, zone: str) -> dict:
    """Nombre d'exemplaires de chaque code de carte dans une zone."""
    counts = {}
    for card in snapshot.zones.get(zone, ()):
        counts[card.code] = counts.get(card.code, 0) + 1
    return counts


def _left_zone(snapshot: GameSnapshot, card: BoardCard, zone: str, before: dict) -> bool:
    """
    CETTE carte-là a-t-elle quitté `zone` ?

    Par CardID quand l'API le donne, et c'est essentiel : un comptage par
    code ne distingue pas deux exemplaires d'une même carte. Avec deux
    Thrall Bulwark sur le banc, engager la mauvaise passait pour un
    succès — le compte du code avait bien baissé, mais l'unité visée était
    toujours là. Le comptage ne sert donc que de repli pour les cartes sans
    identifiant.
    """
    if card.card_id >= 0:
        return all(c.card_id != card.card_id for c in snapshot.zones.get(zone, ()))
    return _zone_counts(snapshot, zone).get(card.code, 0) < before.get(card.code, 0)


def _hand_counts(snapshot: GameSnapshot) -> dict:
    return _zone_counts(snapshot, "hand")


def _placed_counts(snapshot: GameSnapshot) -> dict:
    """
    Cartes effectivement en jeu de notre côté, banc et rangée d'attaque
    confondus. Sert à distinguer « posée » de « partie on ne sait où ».
    """
    counts = dict(_zone_counts(snapshot, "board"))
    for code, number in _zone_counts(snapshot, "attack").items():
        counts[code] = counts.get(code, 0) + number
    return counts


def play_card(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    card: BoardCard,
    dry_run: bool = False,
    attempts: int = 2,
    power_target: Optional[tuple] = None,
    power_description: str = "",
    power_plan=None,
    expect_on_board: bool = True,
) -> tuple:
    """
    Pose une carte et VÉRIFIE qu'elle a quitté la main.

    power_target : point à cliquer après le dépôt si l'unité a un
    pouvoir « Play: » à cible unique (cf. unit_play_plan). Sans ce clic,
    le jeu reste bloqué en attente d'une cible, la carte au centre de
    l'écran — exactement le même piège qu'un sort non ciblé.

    power_plan : le plan du pouvoir « Play: » quand il ouvre une interface
    plutôt qu'un simple ciblage. Deux cas, chacun avec son geste :

        - DÉSIGNATION DANS LA MAIN (« Play: Updraft 1 », « Grant an ally
          in hand +3|+3 »). Le plan porte les trois choses nécessaires au
          clic : combien, de quel type, et dans quel sens.
        - CHOIX DE VERSION (« Play: Play me as First Wave or Last Wind »).
          Le plan porte les noms des versions proposées ; le clic est
          OBLIGATOIRE et sans lui la partie ne repart pas, contrairement
          au ciblage que `cancel_pending_action` rattrape.

    Une carte qui se pose « as » une autre n'arrive pas sur le banc sous
    SON code : c'est la version choisie qui s'y trouve, et c'est donc elle
    que la vérification de placement suit.

    expect_on_board : faux pour un équipement, qui s'attache à une unité
    au lieu d'occuper une place. Le succès se lit alors au seul départ de
    la main — exiger son apparition sur le banc conclurait à l'échec pour
    une pose pourtant réussie, et déclencherait une annulation à tort.

    Renvoie (succès, instantané_le_plus_récent). En mode plan, décrit le
    geste et renvoie (True, snapshot) sans rien toucher.
    """
    source = card.grab_point
    drop = drop_point(card, snapshot.window)

    if dry_run:
        détail = ""
        if power_target:
            détail += f", pouvoir ciblé sur {power_description} en {power_target}"
        if power_plan is not None and power_plan.free_designation:
            détail += ", puis validation sans désigner d'allié (orbe)"
        if power_plan is not None and power_plan.needs_hand_pick:
            _, _, how = designate_in_hand(
                reader, snapshot, power_plan.picks, power_plan.pick_type,
                power_plan.pick_best, exclude=(card,), dry_run=True,
            )
            détail += f", puis {how}"
        if power_plan is not None and power_plan.needs_choice:
            _, _, how = resolve_play_choice(reader, power_plan, snapshot, dry_run=True)
            détail += f", puis {how}"
        if power_plan is not None and power_plan.may_offer_variants:
            _, _, how = resolve_variant_choice(
                reader, card, power_plan, snapshot,
                snapshot.attack_token is True, dry_run=True,
            )
            détail += f", {how} si le jeu en propose"
        if power_plan is not None and power_plan.opens_card_window:
            _, _, how = resolve_card_choice(reader, card, power_plan, snapshot, dry_run=True)
            détail += f", puis {how}"
        LOGGER.info("[plan] jouer %s : saisie %s -> dépôt %s%s", card, source, drop, détail)
        return True, snapshot

    before = _hand_counts(snapshot)
    before_placed = _placed_counts(snapshot)
    latest = snapshot
    # Ce qu'on s'attend à VOIR ARRIVER sur le banc. C'est la carte posée,
    # sauf quand elle se pose « as » une autre : c'est alors la version
    # choisie, et l'attendre sous le code de la carte d'origine ferait
    # conclure à l'échec — donc annuler — une pose parfaitement réussie.
    placed = card

    for attempt in range(1, attempts + 1):
        LOGGER.info("Pose de %s (tentative %d/%d)", card, attempt, attempts)
        # LA MAIN A PU BOUGER DEPUIS LA DÉCISION (pioches en série) : on
        # vise sur une lecture fraîche, et on juge la pose sur elle aussi.
        aimed, fresh = fresh_hand_card(reader, snapshot, card)
        if aimed is None:
            return False, fresh
        if fresh is not snapshot:
            snapshot = fresh
            before = _hand_counts(snapshot)
            before_placed = _placed_counts(snapshot)
            source = aimed.grab_point
            drop = drop_point(aimed, snapshot.window)
        before_signature = snapshot_signature(snapshot)
        drag(source, drop)

        if power_plan is not None and power_plan.may_offer_variants:
            # AVANT LE CIBLAGE : quand le jeu propose deux versions du
            # pouvoir, il n'écoute rien d'autre tant qu'aucune n'est
            # choisie. Cliquer la cible ici, c'est cliquer dans le vide —
            # c'est ce que faisait Iula (05MT013).
            time.sleep(TARGETING_DELAY)
            chosen, latest, detail = resolve_variant_choice(
                reader, card, power_plan, snapshot,
                snapshot.attack_token is True,
            )
            LOGGER.info("Version à la pose : %s", detail)
            if chosen is None and power_plan.needs_variant:
                # Le texte PROMETTAIT deux versions : ne pas les voir est
                # une anomalie, et poursuivre le ciblage cliquerait dans
                # une fenêtre ouverte.
                cancel_pending_action(latest.window)
                return False, reader.stable_snapshot(
                    confirmations=2, poll=0.4, timeout=6.0,
                )
            if chosen is not None and chosen.is_unit:
                # Scaled Snapper arrive sur le banc sous le code de la
                # version choisie, pas sous le sien.
                placed = chosen

        if power_target is not None:
            if spells.opens_version_choice(card):
                # UNE FENÊTRE DE VERSIONS S'OUVRE AVANT LA CIBLE. Les armes
                # Darkin disent « You may spend 8 mana to play me as X » :
                # le jeu propose d'abord l'équipement OU la créature.
                # Cliquer l'allié tout de suite, c'est cliquer DERRIÈRE la
                # fenêtre — elle reste ouverte, la carte revient en main au
                # round suivant, et ses exemplaires restent plantés dans la
                # bande « attack », où ils sont lus comme des ATTAQUANTS
                # ENNEMIS fantômes.
                #
                # Mesuré le 05/11/2026 : The Darkin Lodestone rejouée toutes
                # les 90 s (20:35, 20:37, 20:38, 20:40) en se croyant
                # « posée », et « Acorn, the Hextechnician (1/1) bloque The
                # Darkin Lodestone (0/0) » — notre unité bloquant un
                # fantôme de la fenêtre.
                #
                # Le filet d'après le dépôt ne rattrape PAS ce cas : il ne
                # tourne que si `expect_on_board`, qui vaut False pour un
                # équipement dès qu'un allié existe — c'est-à-dire
                # exactement quand on en a besoin.
                vue = reader.stable_snapshot(confirmations=1, poll=0.3, timeout=3.0)
                chosen, _, detail = resolve_unforeseen_choice(
                    reader, card, snapshot, vue, wait=True,
                )
                if chosen is not None:
                    LOGGER.info("Choix de version avant ciblage : %s", detail)
            time.sleep(TARGETING_DELAY)
            LOGGER.info("Ciblage du pouvoir : %s en %s", power_description, power_target)
            click(*power_target)

            if power_plan is not None and power_plan.free_designation:
                # APRÈS LA CIBLE, PAS AVANT : c'est l'ordre qu'Ewan décrit
                # (« on clique sur l'ennemi et on clique sur le bouton
                # bleu ») et celui que les deux captures du 06/11
                # montrent — l'ennemi déjà cliqué, l'orbe encore à
                # « PASSER ».
                #
                # ET SEULEMENT SI LA CIBLE A ÉTÉ CLIQUÉE — d'où la place
                # de ce bloc DANS le `if power_target is not None`. Ce
                # bouton est aussi celui de fin de tour : le cliquer
                # alors que le jeu n'attend rien PASSERAIT LE TOUR. Les
                # trois cartes de la famille ont toutes une cible
                # (« an enemy »), et `unit_play_blocker` écarte la pose
                # quand elle manque ; rien n'arrive donc ici sans clic.
                time.sleep(TARGETING_DELAY)
                valider_designation_libre(snapshot.window)

        if power_plan is not None and power_plan.needs_choice:
            # AVANT TOUT LE RESTE : tant que la fenêtre de choix est
            # ouverte, aucune autre lecture ne veut dire quoi que ce soit
            # — la carte n'est ni en main, ni sur le banc.
            time.sleep(TARGETING_DELAY)
            chosen, latest, detail = resolve_play_choice(reader, power_plan, snapshot)
            LOGGER.info("Choix de version : %s", detail)
            if chosen is None:
                # L'annulation ne referme PAS une fenêtre de choix — on la
                # tente quand même, elle est sans effet dans le pire des
                # cas — mais l'essentiel est de rendre la main : la carte
                # sera mise de côté pour le tour au lieu d'être reposée
                # deux fois dans le vide.
                cancel_pending_action(latest.window)
                return False, reader.stable_snapshot(
                    confirmations=2, poll=0.4, timeout=6.0,
                )
            placed = chosen

        if power_plan is not None and power_plan.needs_hand_pick:
            # LE CHOIX SE FAIT SUR `snapshot`, L'ÉTAT D'AVANT LE DÉPÔT.
            # Après le dépôt, le jeu remonte les cartes désignables hors
            # de la bande « hand » : `snapshot.hand` y est vide, et
            # décider là-dessus revenait à conclure « rien à désigner »
            # puis à annuler sans avoir cliqué. Les positions, elles, sont
            # relues et stabilisées carte par carte (designate_in_hand).
            time.sleep(TARGETING_DELAY)
            picked, latest, detail = designate_in_hand(
                reader, snapshot, power_plan.picks, power_plan.pick_type,
                power_plan.pick_best, exclude=(card,),
                consumes=power_plan.pick_consumes and not power_plan.opens_card_window,
            )
            LOGGER.info("Pouvoir dans la main : %s", detail)
            if not picked:
                cancel_pending_action(latest.window)
                return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

        if power_plan is not None and power_plan.opens_card_window:
            # EN DERNIER : la fenêtre s'ouvre à la RÉSOLUTION du pouvoir,
            # donc après la cible et après la désignation en main
            # (« Play: Discard 1 to Manifest a Mecha Yordle »).
            time.sleep(TARGETING_DELAY)
            picks, latest, detail = resolve_card_choice(reader, card, power_plan, snapshot)
            LOGGER.info("Fenêtre de cartes : %s", detail)
            if not picks:
                # Même filet que le choix de version : l'annulation ne
                # referme rien, mais rendre la main met la carte de côté
                # au lieu de la reposer dans le vide.
                cancel_pending_action(latest.window)
                return False, reader.stable_snapshot(
                    confirmations=2, poll=0.4, timeout=6.0,
                )

        latest = wait_for_change(reader, before_signature, timeout=AFTER_PLAY_TIMEOUT)
        if expect_on_board and not _plan_handles_windows(power_plan):
            # FILET : une fenêtre de choix que rien n'annonçait (Nidalee,
            # « Ambush 2 » ; toute carte absente de card_sets). Tant
            # qu'elle est ouverte, ni « posée » ni « partie sans arriver »
            # ne veut rien dire — et la version affichée au centre porte
            # parfois le code de la carte jouée, que `_placed_counts`
            # compterait comme posée. On regarde donc AVANT de juger. On
            # n'attend que si la carte n'est pas déjà sur le banc.
            on_bench = (
                _zone_counts(latest, "board").get(card.code, 0)
                > _zone_counts(snapshot, "board").get(card.code, 0)
            )
            chosen, latest, detail = resolve_unforeseen_choice(
                reader, card, snapshot, latest, wait=not on_bench,
                # La MÊME question que `on_bench`, reposée à chaque
                # lecture au lieu d'une seule fois avant la boucle.
                arrivee=lambda vue: (
                    _zone_counts(vue, "board").get(card.code, 0)
                    > _zone_counts(snapshot, "board").get(card.code, 0)
                ),
            )
            if chosen is not None:
                LOGGER.info("Choix imprévu : %s", detail)
                if chosen.code != card.code:
                    placed = chosen
                latest = wait_until_placed(reader, placed, before_placed, latest)
        if expect_on_board and (power_target is not None or power_plan is not None):
            # Un pouvoir vient de se résoudre : l'unité met une seconde de
            # plus à rejoindre le banc, et l'annuler pendant ce trajet
            # défait une pose réussie.
            latest = wait_until_placed(reader, placed, before_placed, latest)
        left_hand = _hand_counts(latest).get(card.code, 0) < before.get(card.code, 0)
        appeared = (
            _placed_counts(latest).get(placed.code, 0)
            > before_placed.get(placed.code, 0)
        )
        if not expect_on_board:
            appeared = left_hand

        if left_hand and appeared:
            LOGGER.info("%s posée.", card.name)
            return True, latest

        if left_hand and not appeared:
            # La carte a quitté la main mais n'est arrivée nulle part :
            # le jeu attend quelque chose de nous — une cible, le plus
            # souvent. Sans annulation, plus rien n'avance ensuite.
            LOGGER.warning(
                "%s a quitté la main sans arriver sur le plateau : "
                "le jeu attend probablement une cible.", card.name
            )
            cancel_pending_action(latest.window)
            latest = reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)
            return False, latest

        LOGGER.warning("%s est toujours en main après la pose.", card.name)

        # La carte a pu bouger dans la main entre-temps : on reprend ses
        # coordonnées à jour plutôt que de refaire exactement le même
        # geste raté.
        refreshed = next(
            (c for c in latest.hand if c.code == card.code), None
        )
        if refreshed is None:
            return False, latest
        source = refreshed.grab_point
        drop = drop_point(refreshed, latest.window)
        # power_target, lui, ne bouge pas d'une tentative à l'autre : c'est
        # une unité ou un nexus déjà sur le plateau, pas une carte de
        # notre main qui vient de se recentrer.

    return False, latest


def _resolves_at_once(card: BoardCard) -> bool:
    """Burst et Focus se résolvent au dépôt ; Fast et Slow attendent la validation."""
    return (getattr(card, "spell_speed", "") or "").lower() in ("burst", "focus")


def play_spell(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    card: BoardCard,
    dry_run: bool = False,
    forced: Optional[tuple] = None,
) -> tuple:
    """
    Lance un sort : dépôt, ciblage éventuel, puis validation.

    `forced` = (plan, cibles, description) impose le ciblage au lieu de
    le recalculer : c'est la riposte qui s'en sert, quand la cible n'est
    pas « la meilleure en général » mais « celle que le sort adverse
    menace », ou le sort adverse lui-même (contresort).

    LA SÉQUENCE EST PILOTÉE PAR L'ÉTAT OBSERVÉ, PAS PAR UNE RÈGLE.
    Selon sa vitesse, un sort se résout immédiatement au dépôt ou attend
    d'être validé — et je ne sais pas avec certitude lequel fait quoi sur
    ce client. Or le bouton de validation est AUSSI celui de fin de tour :
    cliquer à tort ferait passer le tour.

    On regarde donc ce qui s'est réellement passé après le dépôt :
        - le sort est sur la pile  -> il attend, on valide ;
        - il a disparu             -> il s'est déjà résolu, on ne touche
                                      à rien ;
        - il est encore en main    -> le dépôt a raté ;
        - il n'est nulle part      -> mode ciblage bloqué, on annule.

    Aucune supposition sur le comportement du client n'est nécessaire.
    """
    castable, plan, targets, description = spell_is_castable(card, snapshot)
    if forced is not None:
        plan, targets, description = forced
        castable = True
    # CIBLAGE INCOMPLET : moins de points que le plan n'en réclame. À ne
    # pas confondre avec « aucun point », qui peut être parfaitement
    # normal (un sort sans cible). Ici le client a reçu un clic et en
    # attend un autre qui ne viendra pas : c'est le cas qui FIGE la
    # partie, donc celui qui doit toujours finir par une annulation.
    # Sauf pour un pluriel compté (« Frostbite 2 enemies ») face à moins
    # d'ennemis qu'annoncé : là, cliquer tout ce qu'il y a RÉSOUT le sort.
    # « IF THERE ARE NO ENEMIES, … THE ENEMY NEXUS INSTEAD » : zéro clic
    # est le déroulé NORMAL de ces trois sorts-là, pas un ciblage raté.
    # Sans cette exception, le plan réclamait un clic, `targets` était
    # vide, et le sort posé repartait en annulation — les ~23 s que le
    # correctif du 08/11 existe pour épargner. `spell_is_castable` est le
    # seul à pouvoir le dire : lui seul a vu l'instantané.
    sans_clic_attendu = plan.resolves_without_target and not targets
    incomplete = (
        plan.needs_click and len(targets) < plan.total_targets
        and not (plan.flexible_targets and targets)
        and not sans_clic_attendu
    )
    if not castable:
        # Sans restrictions on tente quand même — SAUF si c'est la vitesse
        # qui bloque : là, le client refuserait le dépôt, et le geste
        # serait perdu d'avance.
        allowed_now = spells.can_cast_now(card, snapshot)[0]
        if CARD_RESTRICTIONS or not allowed_now:
            LOGGER.info("%s non jouable : %s", card.name, description)
            return False, snapshot
        LOGGER.info(
            "%s : « %s » — restrictions levées, on tente et on annulera "
            "si le jeu attend une cible.", card.name, description
        )

    source = card.grab_point
    drop = drop_point(card, snapshot.window)

    if dry_run:
        suite = f", cible{'s' if len(targets) > 1 else ''} {description} en {targets}" if targets else ""
        if plan.free_designation:
            suite += ", puis validation sans désigner d'allié (orbe)"
        if incomplete:
            suite += (f" — CIBLAGE INCOMPLET ({len(targets)}/{plan.total_targets}), "
                      "le sort sera annulé après la pose")
        if plan.may_offer_variants:
            _, _, how = resolve_variant_choice(
                reader, card, plan, snapshot,
                snapshot.attack_token is True, dry_run=True,
            )
            suite = f", {how} si le jeu en propose{suite}"
        if plan.needs_hand_pick:
            _, _, how = designate_in_hand(
                reader, snapshot, plan.picks, plan.pick_type, plan.pick_best,
                exclude=(card,), dry_run=True,
            )
            suite = f", puis {how}"
        if plan.opens_card_window:
            _, _, how = resolve_card_choice(reader, card, plan, snapshot, dry_run=True)
            when = "au dépôt" if _resolves_at_once(card) else "après validation"
            suite += f", puis {how} {when}"
        LOGGER.info("[plan] lancer %s (%s) : %s -> %s%s",
                    card.name, plan, source, drop, suite)
        return True, snapshot

    # Même règle qu'à la pose d'une unité : la main a pu se recentrer
    # (pioches) depuis la lecture qui a décidé, on vise sur une lecture
    # fraîche. Les cibles, elles, sont sur le plateau et ne bougent pas.
    aimed, fresh = fresh_hand_card(reader, snapshot, card)
    if aimed is None:
        return False, fresh
    if fresh is not snapshot:
        snapshot = fresh
        source = aimed.grab_point
        drop = drop_point(aimed, snapshot.window)
    before = _hand_counts(snapshot)
    LOGGER.info("Lancement de %s (%s).", card.name, plan)
    drag(source, drop)

    if plan.may_offer_variants:
        # « Give an ally +2|+0 or +0|+2 » : la version D'ABORD, la cible
        # ensuite. C'est l'ordre du jeu, pas une préférence — tant que la
        # fenêtre est ouverte, le clic sur l'allié ne va nulle part.
        time.sleep(TARGETING_DELAY)
        chosen, fresh, detail = resolve_variant_choice(
            reader, card, plan, snapshot, snapshot.attack_token is True,
        )
        LOGGER.info("Version du sort : %s", detail)
        if chosen is None and plan.needs_variant:
            cancel_pending_action(fresh.window)
            return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

    # UN CLIC PAR CIBLE, DANS L'ORDRE. L'immense majorité des sorts n'en
    # ont qu'une ; « Deal 2 to an enemy and Stun another. » (Lien
    # cosmique, 06BC044) en a deux, Trueshot Barrage jusqu'à trois — le
    # jeu attend un clic, en résout les conséquences visuelles, puis
    # attend le suivant, exactement comme s'il s'agissait de sorts
    # distincts lancés à la chaîne.
    for point in targets:
        time.sleep(TARGETING_DELAY)
        LOGGER.info("Ciblage : %s en %s", description, point)
        click(*point)

    if plan.free_designation and targets:
        # SEULEMENT SI UNE CIBLE A ÉTÉ CLIQUÉE, pour la raison dite dans
        # `play_card` : ce bouton est aussi celui de fin de tour.
        #
        # Le pendant de `play_card` pour la forme SORT de la famille :
        # Crimson Pact (01NX006T2), la compétence de Vladimir niveau 2.
        # Elle ne passe presque jamais par ici — une Ability est mise
        # sur la pile par son champion, pas jouée de la main — mais le
        # geste est le même, et le laisser manquer d'un côté serait
        # rouvrir le blocage par la petite porte. Ce qui suit ne suppose
        # rien de plus : `play_spell` juge ensuite sur l'état OBSERVÉ
        # (sur la pile, déjà résolu, encore en main) comme pour tout
        # autre sort.
        time.sleep(TARGETING_DELAY)
        valider_designation_libre(snapshot.window)

    if plan.needs_hand_pick:
        # Même règle que play_card : on décide sur l'état d'avant le
        # dépôt, on clique sur des positions relues.
        time.sleep(TARGETING_DELAY)
        picked, fresh, detail = designate_in_hand(
            reader, snapshot, plan.picks, plan.pick_type, plan.pick_best,
            exclude=(card,), consumes=plan.pick_consumes and not plan.opens_card_window,
        )
        LOGGER.info("Sort avec désignation en main : %s", detail)
        if not picked:
            cancel_pending_action(fresh.window)
            return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

        if plan.needs_board_click_after_hand:
            # LA CIBLE VIENT APRÈS LE COÛT, et c'est l'ordre qu'Ewan a
            # observé le 14/11/2026 : « il arrive bien à défausser une
            # carte de ma main mais n'a pas su viser le nexus ennemi ».
            # « To play » est un coût — le jeu le réclame d'abord.
            #
            # ON RELIT AVANT DE VISER : la défausse vient de retirer une
            # carte, donc la main s'est recentrée et les points décidés
            # avant le dépôt ont glissé (les deux horloges du plateau).
            # `fresh` est l'instantané stabilisé que `designate_in_hand`
            # vient de rendre.
            sous = plan.board_plan()
            picks = spells.choose_targets(sous, fresh)
            if len(picks) < sous.total_targets:
                LOGGER.warning(
                    "%s : plus de cible après la défausse (%d/%d).",
                    card.name, len(picks), sous.total_targets,
                )
                cancel_pending_action(fresh.window)
                return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)
            for point, description in picks:
                LOGGER.info("Ciblage après la défausse : %s", description)
                time.sleep(TARGETING_DELAY)
                click(*point)

    if plan.opens_card_window and _resolves_at_once(card):
        # Burst / Focus : le sort se résout au dépôt, la fenêtre s'ouvre
        # tout de suite — après la cible et la désignation en main, qui
        # sont des interfaces du LANCEMENT.
        time.sleep(TARGETING_DELAY)
        picks, fresh, detail = resolve_card_choice(reader, card, plan, snapshot)
        LOGGER.info("Fenêtre de cartes : %s", detail)
        if not picks:
            cancel_pending_action(fresh.window)
            return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

    time.sleep(AFTER_PLAY_DELAY)
    latest = reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

    if _hand_counts(latest).get(card.code, 0) >= before.get(card.code, 0):
        LOGGER.warning("%s est resté en main.", card.name)
        cancel_pending_action(latest.window)
        return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

    on_stack = any(c.code == card.code and c.local for c in latest.stack)
    if on_stack:
        LOGGER.info("%s est sur la pile : validation.", card.name)
        click(*latest.window.rel(*TURN_BUTTON_RATIO))
        time.sleep(AFTER_PLAY_DELAY)
        latest = reader.stable_snapshot(confirmations=2, poll=0.5, timeout=8.0)
        if plan.opens_card_window:
            # Fast / Slow : la fenêtre s'ouvre à la RÉSOLUTION, c'est-à-
            # dire après la validation et la réponse adverse — d'où un
            # délai plus long. Tant qu'elle est ouverte, rien ne repart.
            picks, latest, detail = resolve_card_choice(
                reader, card, plan, snapshot, timeout=CARD_WINDOW_SLOW_TIMEOUT,
            )
            LOGGER.info("Fenêtre de cartes : %s", detail)
            if not picks:
                cancel_pending_action(latest.window)
                return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)
        latest = let_stack_resolve(reader, latest, card)
        if any(c.code == card.code and c.local for c in latest.stack):
            LOGGER.warning("%s toujours sur la pile après validation.", card.name)
            # SANS IMAGE, CE MESSAGE N'EST QU'UN MOT — c'est tout ce
            # qu'ont laissé les blocages du 09/11.
            journaliser_pile_bloquee(latest, card)
            return False, latest
        LOGGER.info("%s résolu.", card.name)
        return True, latest

    # Parti de la main, absent de la pile : soit déjà résolu (Burst), soit
    # en attente d'une cible qu'on n'a pas su désigner. Une annulation est
    # sans effet dans le premier cas et salvatrice dans le second, donc on
    # la tente quand un ciblage était attendu mais n'a pas abouti.
    #
    # Une carte absente de card_sets entre dans le même cas sans qu'aucun
    # plan ne le dise : sans description, `needs_click` est faux alors
    # qu'on n'en sait strictement rien. Le doute vaut annulation.
    # `plan.impossible` couvre le ciblage INCOMPLET : un sort à deux
    # cibles dont on n'a cliqué que la première (ou dont `spell_is_castable`
    # n'a pas trouvé assez de cibles pour toutes les cliquer, `targets`
    # alors vide) a bien reçu un point, et l'ancienne condition (« aucune
    # cible cliquée ») le laissait donc passer — le client restait en
    # attente du clic suivant, sans filet.
    #
    # `sans_clic_attendu` est la seule carte qui sorte de ce filet : son
    # texte DIT que le jeu la résout sans cible (Final Spark, Ace in the
    # Hole, Javelin Toss). Annuler là serait annuler un sort qui est déjà
    # parti.
    if plan.impossible or incomplete or (
            not targets and (plan.needs_click or not card.known)
            and not sans_clic_attendu):
        cancel_pending_action(latest.window)
        return False, reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

    LOGGER.info("%s résolu.", card.name)
    return True, latest


def describe_stack(snapshot: GameSnapshot) -> str:
    """La pile en une ligne : qui a posé quoi."""
    ours = ", ".join(c.name for c in snapshot.stack_ours) or "rien"
    theirs = ", ".join(c.name for c in snapshot.stack_theirs) or "rien"
    return f"nous : {ours} | adversaire : {theirs}"


def _our_card_on_stack(snapshot: GameSnapshot, card: BoardCard) -> bool:
    return any(c.code == card.code and c.local for c in snapshot.stack)


# --- l'écran du blocage, photographié AVANT le geste qui l'efface ------
#
# LA CAPTURE APPARTIENT AU GESTE, PAS AU COMPTE RENDU (11/11/2026).
# `journaliser_pile_bloquee` photographiait au moment d'écrire son
# rapport, c'est-à-dire APRÈS que `geste_pour_une_cible_reclamee` ait
# annulé : les dix captures de la session du 11/11 montrent le plateau
# DÉBLOQUÉ — orbe « FIN DU ROUND », pile vide, tour repris. Le texte de
# l'instantané, lui, était juste (il vient du `latest` d'avant le
# geste), ce qui rendait la contradiction invisible à la lecture du log.
#
# ON GARDE EN MÉMOIRE, ON N'ÉCRIT QUE SI LE BLOCAGE EST CONFIRMÉ.
# Toutes les cibles réclamées ne finissent pas en blocage : mesuré sur
# tout `logs/`, 51 gestes pour 38 journalisations. Écrire au geste
# ajouterait jusqu'à 13 PNG de ~1,5 Mo qui ne servent à rien — et le
# projet a déjà payé ce bruit (621 des 660 `bloque_*.png`, 94 %,
# 0,98 Go, produits par les tests avant le bouchon du 09/11). Le prix
# de ce choix est l'inverse : jusqu'à 13 captures en MÉMOIRE prises pour
# rien. Elles ne coûtent aucun octet sur le disque, et la mesure dit
# qu'elles sont négligeables en temps — les 10 journalisations du 11/11
# tiennent toutes en 0,098 à 0,121 s, capture ET encodage PNG ET
# écriture comprises, sur un chemin qui dort déjà ~2 s (annulation +
# AFTER_PLAY_DELAY).
#
# En mémoire, une garde AU PLUS : la suivante remplace la précédente, et
# le rapport la consomme. Soit ~6 Mo (1920×1080×3) retenus au pire, le
# temps d'un geste.
_ECRAN_AVANT_GESTE: Optional[Tuple[float, object]] = None

# UNE GARDE N'EST SERVIE QUE SI ELLE EST FRAÎCHE. `respond_to_stack`
# fait le geste sans que personne n'appelle le rapport : sans borne, son
# image resterait en mémoire et serait servie, des minutes plus tard,
# pour un blocage qui n'a rien à voir. Mesuré sur les 10 cas du 11/11,
# le trajet geste → rapport dure ~2 s (13:14:16 → 13:14:18) : 10 s est
# large sans jamais permettre un appariement d'un tour sur l'autre.
FRAICHEUR_CAPTURE_DIAGNOSTIC = 10.0


def capturer_pour_diagnostic():
    """
    LA SEULE COUTURE VERS L'ÉCRAN de ce module — c'est elle qu'on bouchonne.

    Un bouchon par COUTURE, pas un par appelant (10/11/2026) : le
    bouchon de `journaliser_pile_bloquee` ne protégeait plus rien dès
    que la capture a déménagé dans le geste. Rend None plutôt que de
    lever : un diagnostic ne doit jamais faire tomber la boucle.
    """
    try:
        return lor_api.capture_screen_bgr()
    except Exception as exc:      # noqa: BLE001 — le diagnostic ne plante pas la boucle
        LOGGER.warning("Capture de diagnostic impossible : %s", exc)
        return None


def lire_les_etourdies(snapshot: GameSnapshot) -> int:
    """
    Marque `stunned` sur les unités qui portent le tourbillon violet.

    POURQUOI ICI, ET PAS DANS `game_state` : c'est une LECTURE D'ÉCRAN,
    et ce module a déjà sa couture unique (`capturer_pour_diagnostic`).
    En ouvrir une seconde, c'est ce que le projet paie à chaque fois —
    sept guets ont fini par photographier l'écran d'Ewan depuis une
    suite hors ligne, chacun parce qu'il avait son propre chemin.

    DEUX CAPTURES ESPACÉES, parce que le signal est un MOUVEMENT : la
    teinte seule ferait un faux positif sur un champion violet (mesuré
    le 14/11 : Swain, sain, 50,7 % de pixels violets contre 63,6 % pour
    l'unité étourdie). Voir `stun.py` pour les mesures et les seuils.

    COÛT : `DELAI_ENTRE_CAPTURES` (0,7 s) plus deux captures, payés UNE
    fois par phase de blocage — pas par itération de la boucle. À
    comparer aux 41 blocages ratés de `logs/`, où l'attaquant passait au
    nexus après un plan qui annonçait « tout est bloqué ».

    Rend le nombre d'unités marquées. Capture impossible → aucune, et on
    ne dit rien de plus : `stunned` reste faux, ce qui veut dire « on n'a
    pas regardé », et le filet d'`execute_blocks` reprend la main.
    """
    avant = capturer_pour_diagnostic()
    if avant is None:
        return 0
    time.sleep(stun.DELAI_ENTRE_CAPTURES)
    apres = capturer_pour_diagnostic()
    if apres is None:
        return 0

    # Les deux camps : une unité étourdie à NOUS ne peut pas bloquer,
    # une étourdie EN FACE ne peut pas attaquer — et les deux rangées
    # de combat comptent autant que les bancs (deux horloges).
    cartes = [c for zone in (snapshot.board, snapshot.attack_row,
                             snapshot.enemy_board, snapshot.enemy_attack_row)
              for c in zone if c.is_unit]
    etourdies = stun.cartes_etourdies(avant, apres, cartes)
    for carte in cartes:
        if carte.card_id in etourdies:
            carte.stunned = True
    if etourdies:
        noms = ", ".join(sorted(c.name for c in cartes if c.stunned))
        LOGGER.info("Étourdie(s) lue(s) à l'écran : %s", noms)
    return len(etourdies)


def _garder_ecran_avant_geste() -> None:
    """Photographie et met de côté, sans rien écrire sur le disque."""
    global _ECRAN_AVANT_GESTE
    image = capturer_pour_diagnostic()
    _ECRAN_AVANT_GESTE = None if image is None else (time.time(), image)


def _reprendre_ecran_avant_geste():
    """Rend l'image gardée si elle est fraîche, et la CONSOMME."""
    global _ECRAN_AVANT_GESTE
    garde, _ECRAN_AVANT_GESTE = _ECRAN_AVANT_GESTE, None
    if garde is None:
        return None
    quand, image = garde
    if time.time() - quand > FRAICHEUR_CAPTURE_DIAGNOSTIC:
        return None
    return image


class GesteReclame(NamedTuple):
    """
    Ce que `geste_pour_une_cible_reclamee` a fait, et sa phrase.

    LES DEUX GESTES ONT DES CONSÉQUENCES OPPOSÉES, et c'est pour ça
    que la nature du geste remonte avec la phrase au lieu d'être
    redevinée chez l'appelant : une ANNULATION rend la carte à la
    main (le sort est perdu pour le round), une PRISE DE CARTE fait
    AVANCER sa résolution (le sort aboutit). Les déduire à nouveau
    dans `let_stack_resolve` serait une seconde implémentation du
    même test, et le projet sait où ça mène.
    """

    phrase: str
    fenetre_prise: bool


def geste_pour_une_cible_reclamee(
    snapshot: GameSnapshot, dry_run: bool = False,
) -> Optional[GesteReclame]:
    """
    « SÉLECTIONNER LA CIBLE » SUR LE BOUTON : fait le geste, et dit lequel.

    Rend None quand le bouton ne réclame rien — l'appelant garde alors
    son traitement ordinaire. Sinon le geste EST FAIT (sauf `dry_run`),
    et la phrase rendue est destinée au journal.

    SOURCE UNIQUE, ET C'EST TOUT L'ENJEU. La règle est née le 05/11/2026
    dans `respond_to_stack` — blocage de Yoink!, 184 s, une tentative
    hebdomadaire perdue — et n'a jamais été portée à `let_stack_resolve`,
    l'autre endroit qui regarde la pile. Relevé sur les 22 blocages de
    `logs/` : la première lecture de `respond_to_stack`, 4,5 s après
    l'abandon (médiane, max 5,3 s), trouve `button_label == "cible"`
    21 fois sur 22. Le jeu affichait « SÉLECTIONNER LA CIBLE » pendant
    TOUT le blocage — il attendait un geste de nous pendant qu'on
    attendait l'adversaire. 508 s perdues sur 22 cas, 23,1 s de moyenne.

    L'ORDRE N'EST PAS DÉCORATIF, et c'est pour ça que ce test doit être
    appelé AVANT celui de l'orbe : l'orbe est ÉTEINTE tant que le jeu
    attend notre désignation. L'orbe dit à qui c'est de parler ; le
    libellé dit qu'on parle à NOUS. Le second l'emporte.

    UNE FENÊTRE DE CHOIX NE S'ANNULE PAS : quand des cartes sont
    proposées au centre, le clic droit ne fait rien (trois annulations
    sans effet dans la trace du 05/11) — il faut EN PRENDRE UNE. On ne
    passe à l'annulation qu'après avoir regardé.
    """
    if snapshot.button_label != "cible":
        return None

    # ON PHOTOGRAPHIE ICI, ET NULLE PART AILLEURS. En dessous de cette
    # ligne, tout geste EFFACE le blocage : le clic droit rend la carte
    # à la main, le clic de fenêtre referme le panneau. Les dix captures
    # du 11/11, prises par le rapport quelques centaines de ms plus
    # tard, montrent toutes un plateau déjà reparti.
    #
    # `dry_run` ne photographie RIEN : une simulation (`actions.py
    # plan`, `combat.py --plan`) ne touche à rien, l'écran non plus.
    # Rien n'est écrit sur le disque ici — seul le rapport écrit, et
    # seulement si le blocage se confirme.
    if not dry_run:
        _garder_ecran_avant_geste()

    fenetre = visible_card_window(snapshot)
    if fenetre:
        pick = choose_offered_card(fenetre, snapshot)
        detail = (
            f"Fenêtre de choix ouverte ({len(fenetre)} carte(s)) : "
            f"on prend {pick.name} — une fenêtre ne s'annule pas."
        )
        if not dry_run:
            click(*pick.grab_point)
            time.sleep(AFTER_PLAY_DELAY)
        return GesteReclame(detail, fenetre_prise=True)

    ours = ", ".join(c.name for c in snapshot.stack_ours) or "une carte à nous"
    detail = f"Le jeu attend une cible pour {ours} : on annule plutôt que de passer."
    if not dry_run:
        cancel_pending_action(snapshot.window)
        time.sleep(AFTER_PLAY_DELAY)
    return GesteReclame(detail, fenetre_prise=False)


def journaliser_pile_bloquee(snapshot: GameSnapshot, card: BoardCard) -> str:
    """
    Garde l'écran et l'état quand notre sort reste sur la pile.

    LA CAPTURE EST LE VRAI LIVRABLE (leçon du 08/11/2026). Le blocage de
    Yoink! n'a été compris que parce qu'une image existait ; les blocages
    de Flash Freeze du 09/11, eux, n'ont laissé qu'une phrase, et le
    diagnostic a dû être reconstitué depuis les logs.

    On écrit donc `screenshots/pile_bloquee_<carte>_<date>.png` et, au
    journal, les trois choses qui ont manqué : l'état lu, le LIBELLÉ du
    bouton et l'orbe — c'est exactement le couple qui distingue « il
    réfléchit » de « il nous attend ».

    L'IMAGE N'EST PLUS PRISE ICI (11/11/2026). Elle vient de
    `geste_pour_une_cible_reclamee`, qui l'a mise de côté AVANT
    d'annuler : prise ici, elle montrait le plateau DÉBLOQUÉ, et les dix
    captures de la session du 11/11 sont perdues pour cette raison.
    Le TEXTE, lui, reste juste et reste écrit ici — il vient du `latest`
    d'avant le geste.

    Rend le chemin, ou "" : un diagnostic ne doit jamais faire tomber la
    boucle.
    """
    LOGGER.warning(
        "Pile bloquée sur %s : bouton=%s orbe=%s",
        card.name,
        snapshot.button_label or "-",
        "?" if snapshot.turn_orb_active is None
        else ("oui" if snapshot.turn_orb_active else "non"),
    )
    for ligne in snapshot.summary().splitlines():
        LOGGER.warning("  %s", ligne)
    try:
        import cv2
        dossier = lor_api.PROJECT_ROOT / "screenshots"
        dossier.mkdir(exist_ok=True)
        nom = re.sub(r"[^A-Za-z0-9]+", "_", card.name).strip("_") or "carte"
        chemin = dossier / f"pile_bloquee_{nom}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        # L'IMAGE D'AVANT LE GESTE D'ABORD. Si le blocage est passé par
        # « SÉLECTIONNER LA CIBLE », `geste_pour_une_cible_reclamee` a
        # mis l'écran de côté AVANT d'annuler : c'est celui-là qui
        # montre la pile pleine et le bouton qui réclame.
        #
        # Repli sur une capture fraîche quand il n'y a pas de garde :
        # une pile peut rester bloquée sans que le bouton ait jamais
        # réclamé quoi que ce soit (l'adversaire garde la priorité), et
        # là aucun geste n'a été fait — l'écran est encore celui du
        # blocage, il vaut toujours mieux que rien.
        image = _reprendre_ecran_avant_geste()
        quand = "avant le geste"
        if image is None:
            image, quand = capturer_pour_diagnostic(), "à l'instant"
        if image is None:
            LOGGER.warning("Aucune image à garder pour %s.", card.name)
            return ""
        cv2.imwrite(str(chemin), image)
        LOGGER.warning("Écran gardé pour diagnostic (%s) : %s", quand, chemin)
        return str(chemin)
    except Exception as exc:      # noqa: BLE001 — le diagnostic ne plante pas la boucle
        LOGGER.warning("Capture de la pile bloquée impossible : %s", exc)
        return ""


def let_stack_resolve(reader, latest: GameSnapshot, card: BoardCard) -> GameSnapshot:
    """
    Notre sort est validé ; on attend qu'il quitte la pile.

    TROIS choses peuvent l'y retenir. Le jeu attend un geste de NOUS —
    le bouton dit « SÉLECTIONNER LA CIBLE » — et aucun « OK » n'y fera
    rien : c'est `geste_pour_une_cible_reclamee` qui tranche, et il passe
    AVANT l'orbe, parce que l'orbe est éteinte précisément dans ce
    cas-là. Ou l'adversaire RÉPOND : son sort s'empile, et le jeu nous
    rend la main pour un nouveau « OK » — on passe, autant de fois qu'il
    répond (borné par STACK_PASS_ATTEMPTS). Ou c'est à lui de décider
    (orbe grise) : on attend qu'il ait parlé.

    Signalé par Ewan le 03/09/2026 : le bot concluait « toujours sur la
    pile » à la première réponse adverse et continuait à poser des cartes
    pendant que la pile était ouverte.
    """
    for _ in range(STACK_PASS_ATTEMPTS):
        if not _our_card_on_stack(latest, card):
            return latest
        if latest.stack_theirs:
            LOGGER.info(
                "L'adversaire répond à %s avec %s.",
                card.name, ", ".join(c.name for c in latest.stack_theirs),
            )
        # LE LIBELLÉ DU BOUTON PASSE AVANT L'ORBE (09/11/2026). Le
        # correctif du 05/11 n'avait été écrit que dans
        # `respond_to_stack` : ici, un sort resté en l'air faisait lire
        # une orbe ÉTEINTE, conclure « l'adversaire a la priorité » et
        # attendre STACK_PASS_ATTEMPTS × STACK_RESPONSE_WAIT dans le vide.
        geste = geste_pour_une_cible_reclamee(latest)
        if geste is not None:
            LOGGER.info("%s", geste.phrase)
            if not geste.fenetre_prise:
                # ON NE RELIT PAS. Une annulation remet la carte en main :
                # relire rendrait un état où elle n'est plus sur la pile, et
                # `play_spell` conclurait « résolu » pour une carte qui ne
                # l'est pas. L'état rendu dit encore « sur la pile », donc le
                # sort est mis de côté jusqu'au prochain round — ce qui se
                # passait déjà, mais en 3 s au lieu de 23, et avec le mana
                # rendu par l'annulation.
                return latest
            # ON RELIT, ET C'EST L'INVERSE EXACT (15/11/2026, Ewan : « le
            # bot ne sait pas jouer la carte Joker »). Prendre une carte
            # dans une fenêtre ne rend rien : ça fait AVANCER la
            # résolution. Le raisonnement ci-dessus, écrit pour
            # l'annulation, s'appliquait aussi à ce geste-là, et faisait
            # donc conclure à l'échec d'un sort qui venait d'aboutir.
            #
            # Wild Card (98BW003, « Play a Destiny Card. ») : pendant la
            # fenêtre, la carte jouée ET ses trois options sont toutes
            # dans `stack` — « Blue Card | Wild Card | Gold Card | Red
            # Card ». Sans relecture, `play_spell` retrouvait forcément
            # Wild Card et la bannissait pour le round, alors que le log
            # montrait Blue Card sur la pile une seconde plus tard.
            # 10 fois le 15/11, 7 fois le 14/11 au soir.
            #
            # On repart dans la boucle plutôt que de rendre la main : une
            # fenêtre peut en ouvrir une autre (Songspinner, Trifecta).
            #
            # MAIS SEULEMENT SI L'ÉCRAN A BOUGÉ. Un clic qui ne prend pas
            # laisse la même fenêtre ouverte, et reprendre le geste
            # reclique la MÊME carte jusqu'à `STACK_PASS_ATTEMPTS` — le
            # jeu, lui, DÉSÉLECTIONNE ce qu'on reclique (loi des panneaux
            # à deux rangées, 08/11). Écran figé : on sort comme avant,
            # la carte est encore sur la pile, elle est mise de côté.
            empreinte = snapshot_signature(latest)
            latest = reader.stable_snapshot(confirmations=2, poll=0.5, timeout=8.0)
            if snapshot_signature(latest) == empreinte:
                LOGGER.warning(
                    "La fenêtre de %s n'a pas bougé après le clic : on n'insiste pas.",
                    card.name,
                )
                return latest
            continue
        if not latest.turn_orb_active:
            # Il réfléchit : rien à cliquer, on attend que ça bouge.
            LOGGER.info("L'adversaire a la priorité : on attend.")
            latest = wait_for_change(
                reader, snapshot_signature(latest), timeout=STACK_RESPONSE_WAIT, settle=False,
            )
            continue
        LOGGER.info("Pile : %s — on passe (OK).", describe_stack(latest))
        click(*latest.window.rel(*TURN_BUTTON_RATIO))
        time.sleep(AFTER_PLAY_DELAY)
        latest = reader.stable_snapshot(confirmations=2, poll=0.5, timeout=8.0)
    return latest


def response_options(snapshot: GameSnapshot, pool: ManaPool) -> List[BoardCard]:
    """
    Les sorts de la main qu'on peut lancer EN RÉPONSE, la plus chère d'abord.

    `playable_cards` fait déjà le tri qui compte : mana, cibles présentes,
    et vitesse — `spells.can_cast_now` refuse les sorts lents dès que la
    pile n'est pas vide. On ne garde ici que les sorts, les unités ne se
    posent pas en réponse.
    """
    options = [
        c for c in playable_cards(snapshot, pool, allow_spells=True)
        if c.is_spell or c.is_ability
    ]
    # Les CONTRESORTS (« Stop a spell ») sont refusés par prudence en mode
    # restreint — leur cible est la pile, que le ciblage ordinaire ne sait
    # pas viser. En riposte, c'est justement la parade la plus précise, et
    # `riposte` fournit la cible : on les remet dans la liste.
    seen = {c.code for c in options}
    for card in snapshot.hand:
        if card.code in seen or not (card.is_spell or card.is_ability):
            continue
        if riposte.counter_scope(card) and can_pay(card, pool) and spells.can_cast_now(card, snapshot)[0]:
            options.append(card)
    return options


def respond_to_stack(
    reader,
    snapshot: GameSnapshot,
    allow_spells: bool = False,
    dry_run: bool = False,
    allow_chump: bool = False,
) -> ActionLog:
    """
    Un sort attend sur la pile. Quatre cas, dans l'ordre :

        - le bouton dit « SÉLECTIONNER LA CIBLE » : c'est NOUS que le jeu
          attend. Une fenêtre de choix est ouverte → on prend une carte
          (elle ne s'annule pas) ; sinon → on annule ;
        - l'orbe est grise : c'est à l'adversaire de parler, on attend ;
        - un sort ADVERSE est là et on a un sort de réponse jouable :
          on le lance (`play_spell` valide et laisse la pile se résoudre) ;
        - sinon on passe (« OK »), et la pile se résout.

    L'ORDRE N'EST PAS DÉCORATIF : le libellé passe avant l'orbe, parce
    que l'orbe est ÉTEINTE pendant qu'on attend notre désignation.

    Ce que veut Ewan (03/09/2026) : répondre quand on peut, jamais rester
    figé, et surtout ne plus poser de cartes pendant que la pile est
    ouverte.
    """
    log = ActionLog()
    log.add(f"Pile : {describe_stack(snapshot)}.")

    # LE BOUTON DIT « SÉLECTIONNER LA CIBLE » : c'est NOTRE geste que le
    # jeu attend, pas un « OK ». Une carte à nous est partie sur la pile
    # sans cible — un sort inconnu de card_sets, ou la voisine attrapée
    # pendant une pioche (05/09/2026 : 07BW043 à la place de Slotbot, 12
    # « OK » dans le vide, 50 s). Cliquer « OK » n'y fait rien.
    #
    # CE TEST PASSE AVANT CELUI DE L'ORBE (05/11/2026), et c'est tout le
    # bogue : tant que le jeu attend un geste de nous, l'ORBE EST ÉTEINTE.
    # Mesuré trois fois pendant le blocage de Yoink! — « orbe=non
    # bouton=cible » à 17:13:50, 17:14:47 et 17:15:54 — donc la branche
    # écrite le 05/09 n'était jamais atteinte : on tombait sur
    # « l'adversaire a la priorité : on attend », 43 fois de suite, 184 s,
    # puis le combat était abandonné. L'orbe dit à qui c'est de parler ;
    # le libellé dit qu'on nous parle à NOUS. Le second l'emporte.
    #
    # LE GESTE LUI-MÊME VIT DANS `geste_pour_une_cible_reclamee`, parce
    # que `let_stack_resolve` doit appliquer la MÊME règle : écrite ici
    # seulement, elle n'existait pas là-bas, et c'est tout le défaut du
    # 09/11 (22 blocages, 508 s).
    geste = geste_pour_une_cible_reclamee(snapshot, dry_run=dry_run)
    if geste is not None:
        log.add(geste.phrase)
        return log

    if not snapshot.turn_orb_active:
        log.add("L'adversaire a la priorité : on attend.")
        return log

    # Sans restrictions (le mode par défaut d'Ewan), les sorts se jouent
    # déjà sans `--spells` : la riposte suit la même règle. Le journal du
    # 03/09 montrait 47 combats avec `spells: false` — l'option n'est
    # jamais passée, la riposte ne se serait jamais déclenchée.
    if snapshot.stack_theirs and (allow_spells or not CARD_RESTRICTIONS) and SPELLS_ENABLED:
        pool = read_mana_pool(window=snapshot.window)
        if not pool.readable:
            log.add("Mana illisible : pas de réponse.")
        else:
            options = response_options(snapshot, pool)
            plan_of = lambda c: spell_is_castable(c, snapshot)[1:4]  # noqa: E731
            response, why = riposte.choose_response(snapshot, options, plan_of)
            log.add(f"Menace : {why}.")
            if response is not None:
                card = response.card
                log.add(f"Riposte : {response}.")
                if dry_run:
                    log.add("[plan] on lancerait ce sort, puis on validerait.")
                    return log
                plan = spells.classify_card(card, restricted=False)
                success, _ = play_spell(
                    reader, snapshot, card, dry_run=dry_run,
                    forced=(plan, response.targets, response.reason),
                )
                log.add(f"{card.name} : " + ("résolu." if success else "n'a pas abouti."))
                return log
            log.add("Pas de riposte utile : on passe.")

    # UNE ATTAQUE ADVERSE SOUS LA PILE : « OK » N'EST PAS UN PASSE ANODIN.
    #
    # Signalé par Ewan le 04/09/2026 (boss intermédiaire, Jhin) : quatre
    # attaques adverses encaissées sans qu'un seul bloqueur soit posé, le
    # nexus détruit. Ses attaquants portaient des compétences « Attaque : »
    # (Crackshot, Blade's Edge, Lotus Trap…) : elles s'empilent au moment
    # de la déclaration, la lecture d'état rend SPELL_STACK — qui prime
    # sur BLOCKING, à raison — et le bot cliquait « OK » pour passer. Ce
    # clic est aussi le bouton de confirmation des blocages : la phase de
    # blocage n'a JAMAIS été lue, l'attaque entière arrivait au nexus.
    #
    # Quand des unités adverses sont avancées, on pose donc les bloqueurs
    # AVANT le clic, par `execute_blocks` sur l'instantané requalifié en
    # BLOCKING (mêmes glissés, mêmes vérifications, même confirmation).
    # Si le jeu refuse les glissés tant que la pile est ouverte, chaque
    # bloqueur est vu « n'a pas pris son poste », la confirmation résout
    # la pile, et la fenêtre de blocage qui suit sera lue BLOCKING par la
    # boucle : rien n'est perdu dans un cas comme dans l'autre.
    attackers = [c for c in snapshot.enemy_attack_row if c.is_unit]
    if attackers:
        log.add(
            f"Attaque adverse sous la pile ({len(attackers)} attaquant(s)) : "
            "on pose les bloqueurs avant de répondre."
        )
        done, _, block_log = execute_blocks(
            reader,
            replace(snapshot, phase=Phase.BLOCKING),
            allow_chump=allow_chump,
            dry_run=dry_run,
        )
        log.entries.extend(block_log.entries)
        log.blocks = 1 if done else 0
        return log

    log.add("On passe (OK).")
    if not dry_run:
        click(*snapshot.window.rel(*TURN_BUTTON_RATIO))
        time.sleep(AFTER_PLAY_DELAY)
    return log


def cost_reading_candidates(
    snapshot: GameSnapshot,
    allow_spells: bool = False,
    skip: Optional[set] = None,
) -> List[BoardCard]:
    """
    Cartes de la main dont le coût affiché peut encore changer la décision.

    Chaque lecture coûte six passes d'OCR : inutile de la payer pour une
    carte que `playable_cards` refusera de toute façon sur autre chose que
    son prix. Sont écartées :

    - les équipements et les types non gérés — dont, au passage, les cartes
      ABSENTES de card_sets : le jeu ne nous donne que leur cardCode, donc
      leur type est vide et elles restent refusées quel que soit le coût
      lu. C'est la raison pour laquelle lire la gemme ne « rattrape » pas
      une base de cartes en retard, contrairement à ce qu'on espérait ;
    - les sorts quand ils ne sont pas autorisés ;
    - les cartes déjà mises de côté ce tour-ci.

    La liste suit délibérément les mêmes tests que `playable_cards`, moins
    ceux qui portent sur le prix : c'est ce qui garantit qu'on ne saute
    jamais une carte pour laquelle le coût aurait été déterminant.

    Sans restrictions, ce même principe ne laisse plus rien à élaguer :
    toute carte de la main peut être jouée, donc son prix affiché compte,
    y compris celui d'un équipement ou d'une carte absente de card_sets —
    c'est même le seul moyen de la jouer, puisque son coût de base est nul
    et que le mana, lui, reste vérifié.
    """
    skip = skip or set()
    keep = []
    for card in snapshot.hand:
        if card.code in skip:
            continue
        if not CARD_RESTRICTIONS:
            keep.append(card)
            continue
        if card.is_spell or card.is_ability:
            if allow_spells and SPELLS_ENABLED:
                keep.append(card)
            continue
        if card.is_unit or card.is_landmark:
            keep.append(card)
    return keep


def refresh_costs(
    snapshot: GameSnapshot,
    log: Optional[ActionLog] = None,
    allow_spells: bool = False,
    skip: Optional[set] = None,
) -> GameSnapshot:
    """
    Relit le coût affiché des cartes en main et journalise les écarts.

    À appeler juste avant de choisir quoi poser, sur l'instantané COURANT :
    une réduction peut apparaître ou disparaître entre deux poses du même
    tour, et un instantané fraîchement relu repart de `cost_read = None`.
    """
    if not READ_SCREEN_COSTS:
        return snapshot

    enrich_with_live_costs(
        snapshot, cards=cost_reading_candidates(snapshot, allow_spells, skip)
    )

    if log is not None:
        gaps = cost_gaps(snapshot)
        if gaps:
            log.add(
                "Coûts modifiés à l'écran : "
                + ", ".join(
                    f"{card.name} {card.base_cost}->{card.cost} ({gap:+d})"
                    for card, gap in gaps
                )
            )
    return snapshot


def play_hand(
    reader: GameStateReader,
    snapshot: Optional[GameSnapshot] = None,
    allow_spells: bool = False,
    dry_run: bool = False,
    max_plays: int = MAX_PLAYS_PER_TURN,
    carry: Optional[dict] = None,
) -> tuple:
    """
    Pose des cartes tant qu'il en reste de jouables.

    `carry` : mémoire PARTAGÉE entre les appels d'un même round,
    `{"codes": set, "mana": int|None}`, fournie par la boucle de combat.
    Une carte dont la pose a raté y est mise de côté et le RESTE tant que
    le mana ne remonte pas — c'est-à-dire jusqu'au round suivant.

    Pourquoi (06/09/2026, 07:25 → 07:31) : chaque pose ratée rendait la
    main, un sort partait sur la pile, la boucle revenait ici avec un
    `failed` VIDE et refaisait exactement la même pose ratée. « Buhru
    Lookout toujours en main » ×14, le tour ne finissait jamais, jusqu'à
    la durée maximale du combat (900 s) — et la navigation s'est perdue
    derrière. Sans `carry`, le comportement d'avant : mise de côté pour
    cet appel seulement.

    Renvoie (cartes_posées, dernier_instantané, journal).
    """
    log = ActionLog()
    snapshot = snapshot or reader.stable_snapshot()
    played: List[BoardCard] = []
    failed: set = carry.setdefault("codes", set()) if carry is not None else set()
    # Bannies pour TOUT LE COMBAT (cf. combat.CombatLoop._ban_pending_cards) :
    # une pose que la détection de blocage a dû annuler. Ne se vide jamais.
    banned: set = carry.get("banned", set()) if carry is not None else set()

    if not snapshot.phase.is_our_move:
        log.add(f"Phase {snapshot.phase.name} : ce n'est pas à nous, rien à faire.")
        return played, snapshot, log
    if snapshot.phase is Phase.SPELL_STACK:
        log.add("Sort sur la pile : on ne pose rien tant qu'elle n'est pas résolue.")
        return played, snapshot, log

    for turn in range(max_plays):
        # Le mana est relu à CHAQUE itération : il diminue à chaque pose,
        # et se fier à la valeur du début ferait tenter une carte qu'on ne
        # peut plus payer.
        pool = read_mana_pool(window=snapshot.window)
        if not pool.readable:
            log.add("Mana illisible : on s'arrête plutôt que de jouer à l'aveugle.")
            break
        log.note_mana(pool)
        if carry is not None:
            # LE MANA NE REMONTE QU'AU CHANGEMENT DE ROUND : s'il est plus
            # haut qu'à notre dernière lecture, les mises de côté du round
            # précédent ne valent plus.
            last = carry.get("mana")
            if last is not None and pool.mana > last and failed:
                log.add("Nouveau round : les cartes mises de côté redeviennent jouables.")
                failed.clear()
            carry["mana"] = pool.mana

        # Les coûts aussi sont relus à chaque itération, et pour la même
        # raison : poser une carte peut en réduire une autre, et une
        # réduction « ce tour-ci » disparaît dès qu'elle est consommée.
        skipped = failed | banned
        refresh_costs(snapshot, log, allow_spells=allow_spells, skip=skipped)

        slots = free_board_slots(snapshot)
        options = playable_cards(snapshot, pool, allow_spells, skip=skipped)
        log.add(
            f"[{turn + 1}] {pool} | {slots} place(s) | "
            f"main {len(snapshot.hand)} | jouables : "
            + (
                ", ".join(
                    f"{c.name}({c.cost}{'*' if c.cost_is_live else ''})" for c in options
                )
                or "aucune"
            )
        )

        if not options:
            # « Aucune jouable » ne dit pas POURQUOI : sans ça, un coût mal
            # lu à l'écran (ou une réduction non prise en compte) ressemble
            # à un bug de décision alors que la cause est une donnée en
            # amont. On journalise donc, carte par carte, le motif exact —
            # cmd_why() fait la même chose en CLI, mais seulement sur
            # demande manuelle ; ici c'est automatique, au moment même où
            # le refus se produit.
            for card in snapshot.hand:
                if card.code in banned:
                    reason = "bannie pour le reste du combat (pose figée, annulée)"
                else:
                    reason = rejection_reason(card, snapshot, pool, allow_spells)
                if reason:
                    log.add(f"    {card} -> {reason}")
                    log.reject(card, reason)
            break

        card = options[0]
        if card.is_spell or card.is_ability:
            success, snapshot = play_spell(reader, snapshot, card, dry_run=dry_run)
        elif card.is_equipment:
            # Un équipement se dépose comme une carte, puis se dirige sur
            # une unité comme un pouvoir ciblé. Il ne réclame en revanche
            # aucune place sur le banc, d'où `expect_on_board=False`.
            point, description = equipment_plan(card, snapshot)
            success, snapshot = play_card(
                reader, snapshot, card, dry_run=dry_run,
                power_target=point, power_description=f"équiper {description}",
                # Sans allié à équiper (cas qui n'existe que sans
                # restrictions), l'équipement ne peut s'attacher nulle
                # part : exiger de le VOIR arriver quelque part est alors
                # ce qui déclenche l'annulation au lieu de conclure à
                # tort qu'il est bien parti.
                expect_on_board=point is None,
            )
        else:
            # Recalculé sur l'instantané COURANT plutôt que réutilisé
            # depuis playable_cards : le plateau (donc la cible) a pu
            # changer entre les deux, exactement comme pour spell_is_castable.
            plan, power_target, power_description = unit_play_plan(card, snapshot)
            success, snapshot = play_card(
                reader, snapshot, card, dry_run=dry_run,
                power_target=power_target, power_description=power_description,
                power_plan=plan,
            )
        if success:
            played.append(card)
        else:
            # On met la carte de côté au lieu de réessayer sans fin : si
            # elle refuse de se poser, la cause ne disparaîtra pas en
            # refaisant le même geste.
            failed.add(card.code)
            log.add(f"{card.name} mise de côté jusqu'au prochain round.")
            log.reject(card, "pose ratée : mise de côté jusqu'au prochain round")

        if dry_run:
            # Sans action réelle, l'état ne change pas : continuer
            # produirait la même décision à l'infini.
            log.add("[plan] simulation d'une seule pose (l'état ne change pas).")
            break

        # LA MAIN SE RECENTRE DÈS QU'UNE CARTE LA QUITTE, ET C'EST LA
        # DERNIÈRE LECTURE QUI SERT À VISER.
        #
        # Signalé par Ewan le 22/08/2026 : « lorsqu'une carte est jouée,
        # les autres se déplacent ». Les coordonnées d'un `BoardCard` sont
        # figées au moment de la lecture ; celles d'après la pose valaient
        # donc pour une main qui n'existe plus. La saisie suivante partait
        # sur la place de la voisine — au mieux on joue la mauvaise carte,
        # au pire on attrape le vide et le tour se passe à agiter la
        # souris.
        #
        # C'est la MÊME règle que pour le banc entre deux engagements
        # (`relocate_card`, `move_to_attack_row`) : on décide sur un état
        # cohérent, on vise sur des positions relues. Ici la relecture
        # profite à tout ce qui suit dans l'itération suivante — le
        # classement des jouables, l'OCR des coûts qui découpe l'écran aux
        # coordonnées des cartes, et la saisie elle-même.
        #
        # `play_card` rend déjà un instantané stabilisé quand tout va
        # bien, mais pas dans ses chemins d'échec (annulation, carte
        # restée en main), et `wait_until_settled` abandonne au bout de
        # SETTLE_TIMEOUT si l'animation traîne. Relire ici est la seule
        # place qui couvre les deux cas.
        snapshot = settled_snapshot(reader)

        # POSER UNE CARTE REND LA PRIORITÉ À L'ADVERSAIRE.
        # C'est la règle du jeu, et elle veut dire qu'entre deux poses il
        # peut déclarer son attaque. Continuer à poser des cartes à ce
        # moment-là, c'est agir dans une fenêtre qui ne nous appartient
        # plus : les gestes ne prennent pas, et surtout on laisse filer
        # le seul instant où l'on peut bloquer.
        if not snapshot.phase.is_our_move:
            log.add(f"La main est repassée à l'adversaire ({snapshot.phase.name}) : on arrête de poser.")
            break
        if snapshot.phase in (Phase.BLOCKING, Phase.ATTACKING):
            log.add(f"Attaque déclarée pendant la pose ({snapshot.phase.name}) : on arrête de poser.")
            break
        if snapshot.phase is Phase.SPELL_STACK:
            # L'adversaire a répondu à ce qu'on vient de poser (ou joué un
            # sort entre deux cartes). Continuer à poser, c'est agir dans
            # une fenêtre qui attend un « OK » : les gestes ne prennent
            # pas. La boucle de combat répond ou passe, puis on reprend.
            log.add(f"Sort sur la pile ({describe_stack(snapshot)}) : on arrête de poser.")
            break

    return played, snapshot, log


# ============================================================
# ATTAQUE
# ============================================================
# Poser une carte et déclarer une attaque visent la MÊME zone de dépôt.
# Ce qui les distingue, c'est la zone de DÉPART : depuis la main, le
# client pose la carte sur le banc ; depuis le banc, il l'engage dans
# l'attaque. D'où la réutilisation de PLAY_DROP_RATIO ici.

def attackers_available(snapshot: GameSnapshot) -> List[BoardCard]:
    """
    Unités du banc EN ÉTAT d'attaquer. Ce n'est pas encore un choix : voir
    `plan_attack` pour décider lesquelles engager réellement.

    `card.attack` reflète la stat LUE À L'ÉCRAN si `enrich_with_live_stats`
    a tourné sur cet instantané, la stat de base sinon.

    LE FILTRE PORTE SUR LES DÉGÂTS, PAS SUR L'ATTAQUE. Une unité
    Formidable frappe avec ses PV : une 0/7 a bien 0 d'attaque et vaut
    pourtant 7 au nexus, et l'ancien filtre `attack > 0` l'écartait de
    toutes les attaques du bot. Impact compte pareil : une 0/3 Impact
    passe 1 dégât.
    """
    candidates = [
        card for card in snapshot.board
        if card.is_unit and card.can_attack and keywords.unblocked_damage(card) > 0
    ]
    return sorted(
        candidates,
        key=lambda c: (keywords.strike_power(c), c.health),
        reverse=True,
    )


def card_value(card: BoardCard) -> int:
    """Valeur approchée d'une unité, pour comparer des échanges."""
    return keywords.unit_value(card)


def predict_enemy_blocks(attackers, blockers) -> list:
    """
    Comment l'adversaire bloquerait probablement.

    On lui prête NOTRE propre logique de blocage — `_assign`, la même
    fonction. Ce n'est pas de la paresse : supposer que l'adversaire joue
    raisonnablement est la seule hypothèse défendable, et n'importe quelle
    autre reviendrait à parier sur sa maladresse.
    """
    pairs, _ = _assign(attackers, [b for b in blockers if b.is_unit], BLOCK_TRADE)
    return pairs


def forced_blocks(attackers, challenges: Optional[dict] = None) -> tuple:
    """
    Traduit un plan de tirage en blocages IMPOSÉS.

    Renvoie (forcés, verrouillés) : `forcés` associe `id()` de notre
    attaquant à l'unité adverse qu'il tire, `verrouillés` réunit les
    `CardID` adverses ainsi immobilisés.

    LE TIRAGE A DEUX EFFETS, et le second est souvent le plus précieux :
    l'unité tirée bloque NOTRE unité, donc elle ne bloque plus AUCUNE
    autre. Tirer le seul gros bloqueur d'en face ouvre la voie à tout le
    reste de notre attaque.
    """
    challenges = challenges or {}
    forced, locked = {}, set()
    for attacker in attackers:
        target = challenges.get(attacker.card_id)
        if target is None:
            continue
        forced[id(attacker)] = target
        if target.card_id >= 0:
            locked.add(target.card_id)
    return forced, locked


def evaluate_attack(attackers, blockers, challenges: Optional[dict] = None,
                    nexus_weight_value: float = NEXUS_DAMAGE_WEIGHT,
                    trigger_bonus: float = 0.0) -> dict:
    """
    Bilan chiffré d'une attaque : ce qu'on perd, ce qu'on tue, ce qui
    passe au nexus, ce qu'on regagne en PV.

    `trigger_bonus` — la valeur d'un déclencheur « Attack: » qui part
    (Nilah, Bard, Ziggs, Jarvan IV…). Il part que l'unité soit bloquée
    ou non ; le montant vient de la stratégie du deck, 0 par défaut.

    `challenges` — {CardID de notre unité: unité adverse tirée} — retire
    les unités tirées du vivier de bloqueurs et impose leur duel. C'est
    ce qui permet de CHIFFRER un tirage au lieu de le deviner.

    QUI MEURT EST DÉLÉGUÉ À `keywords.resolve_duel`. Les deux
    comparaisons d'origine — « son attaque dépasse mes PV, je meurs » —
    se trompaient dès qu'un mot-clé changeait l'ordre ou le montant des
    frappes : une Frappe Rapide qui tue avant d'être touchée était
    comptée comme un échange, une Barrière comme une perte sèche.

    Et une mort n'est pas toujours une perte : `keywords.death_cost`
    rend zéro pour une Éphémère ou une Sans-mort.
    """
    forced, locked = forced_blocks(attackers, challenges)

    # L'adversaire ne choisit que pour les attaquants qu'il n'est pas
    # obligé de bloquer, et avec les unités qu'on ne lui a pas prises.
    free_attackers = [a for a in attackers if id(a) not in forced]
    free_blockers = [b for b in blockers if b.card_id not in locked]

    pairs = predict_enemy_blocks(free_attackers, free_blockers)
    blocked = {id(attacker): blocker for blocker, attacker in pairs}
    for attacker in attackers:
        target = forced.get(id(attacker))
        if target is not None:
            blocked[id(attacker)] = target
            pairs = pairs + [(target, attacker)]

    our_loss = their_loss = nexus_damage = healing = 0
    triggers = sum(1 for a in attackers if strategy.has_attack_trigger(a)) if trigger_bonus else 0
    for attacker in attackers:
        blocker = blocked.get(id(attacker))

        if blocker is None:
            nexus_damage += keywords.unblocked_damage(attacker)
            # Vol d'âme soigne les dégâts infligés — au nexus aussi.
            if keywords.has(attacker, "Lifesteal"):
                healing += keywords.strike_power(attacker)
            continue

        duel = keywords.resolve_duel(attacker, blocker)
        if duel.attacker_dies:
            our_loss += keywords.death_cost(attacker)
        if duel.blocker_dies:
            their_loss += keywords.death_cost(blocker)
        # Submersion et Impact traversent le bloqueur.
        nexus_damage += duel.nexus_damage
        healing += duel.attacker_lifesteal

    return {
        "pairs": pairs,
        "challenges": dict(challenges or {}),
        "our_loss": our_loss,
        "their_loss": their_loss,
        "nexus_damage": nexus_damage,
        "healing": healing,
        "triggers": triggers,
        "profit": (
            their_loss
            + nexus_damage * nexus_weight_value
            + healing * LIFESTEAL_WEIGHT
            + triggers * trigger_bonus
            - our_loss
        ),
    }


def plan_challenges(attackers, blockers, nexus_weight_value: float = NEXUS_DAMAGE_WEIGHT,
                    trigger_bonus: float = 0.0) -> dict:
    """
    QUI TIRE QUI. Renvoie {CardID de notre unité: unité adverse tirée}.

    Défier n'est pas un bonus qu'on ajoute à une attaque : ça CHANGE
    l'attaque. Une unité tirée ne bloque plus personne d'autre, si bien
    qu'un tirage même perdant en duel peut ouvrir la voie à trois autres
    attaquants. Aucune heuristique locale ne voit ça — on chiffre donc
    l'attaque ENTIÈRE pour chaque tirage envisageable.

    Méthode : glouton par paire. On essaie tous les couples
    (notre attaquant, sa cible) légaux, on garde celui qui améliore le
    plus le bilan global, et on recommence avec les unités restantes.
    On s'arrête dès qu'aucun tirage n'améliore plus rien.

    STRICTEMENT MEILLEUR, pas « aussi bon » : un tirage coûte un
    glisser-déposer, donc un risque de geste raté. À bilan égal on
    engage normalement.
    """
    pool = [
        (ours, target)
        for ours in attackers
        if ours.card_id >= 0
        for target in blockers
        if keywords.can_challenge(ours, target)
        # La règle du blocage doit rester indiscutable : voir
        # keywords.can_challenge sur Insaisissable et Redoutable.
        and can_block_attacker(target, ours)
    ]
    if not pool:
        return {}

    challenges: dict = {}
    locked: set = set()
    best_profit = evaluate_attack(attackers, blockers, challenges, nexus_weight_value,
                                  trigger_bonus)["profit"]

    while True:
        best = None
        for ours, target in pool:
            if ours.card_id in challenges or target.card_id in locked:
                continue
            trial = dict(challenges)
            trial[ours.card_id] = target
            profit = evaluate_attack(attackers, blockers, trial, nexus_weight_value,
                                     trigger_bonus)["profit"]
            if best is None or profit > best[0]:
                best = (profit, ours, target)

        if best is None or best[0] <= best_profit:
            return challenges

        best_profit, ours, target = best
        challenges[ours.card_id] = target
        if target.card_id >= 0:
            locked.add(target.card_id)


def plan_attack(snapshot: GameSnapshot, enemy_nexus_health: Optional[int] = None,
                strat: Optional["strategy.Strategy"] = None) -> tuple:
    """
    Choisit AVEC QUOI attaquer, et pas seulement si on peut.

    `strat` (défaut : `STRATEGY`, la stratégie du deck en cours) donne le
    poids de base d'un dégât au nexus, la valeur d'un déclencheur
    « Attack: » et le PLANCHER : un deck agressif accepte un bilan
    légèrement négatif du moment que des dégâts passent au nexus. Avec
    `strategy.DEFAULT`, rien de tout ça ne joue.

    Le bot engageait auparavant toutes ses unités à chaque tour. Face à un
    plateau adverse plus solide, ça revient à jeter son propre banc tour
    après tour : c'était la plus grosse faiblesse de jeu.

    Méthode : on simule le blocage adverse, on chiffre le bilan, et tant
    qu'il est défavorable on retire l'attaquant qui coûte le plus cher —
    puis on recalcule, parce que retirer une unité change l'affectation
    des bloqueurs d'en face.

    `enemy_nexus_health` change tout quand il est connu : une attaque
    létale se joue quel qu'en soit le coût. Sans cette information, le bot
    évalue correctement les échanges mais ne finit jamais une partie
    gagnable — il continue à optimiser sa valeur de plateau alors qu'il
    suffisait de foncer.

    Renvoie (attaquants retenus, bilan, explication).
    """
    candidates = attackers_available(snapshot)
    if not candidates:
        return [], None, "aucune unité en état d'attaquer"

    blockers = [c for c in snapshot.enemy_board if c.is_unit and c.can_block]
    strat = strat or STRATEGY
    weight = nexus_weight(enemy_nexus_health, strat.nexus_base_weight)
    bonus = strat.attack_trigger_bonus

    # LES TIRAGES SE DÉCIDENT UNE FOIS, sur l'attaque complète, et ne
    # sont plus remis en cause ensuite. Les recalculer à chaque
    # attaquant retiré serait plus fin mais imbriquerait deux boucles
    # gloutonnes — quelques milliers d'évaluations pendant que le
    # chronomètre du tour tourne. Et l'approximation se tient : retirer
    # un attaquant retire son tirage avec lui, donc le bilan reste
    # cohérent à chaque étape.
    challenges = plan_challenges(candidates, blockers, weight, bonus)

    def evaluate(engaged, chall):
        return evaluate_attack(engaged, blockers, chall, weight, bonus)

    def acceptable(report) -> bool:
        if report["profit"] >= 0:
            return True
        # Le plancher ne vaut que pour une attaque qui TOUCHE le nexus :
        # perdre une unité pour rien n'est jamais de la pression.
        return report["nexus_damage"] > 0 and report["profit"] >= strat.attack_floor

    def challenges_for(engaged) -> dict:
        keep = {c.card_id for c in engaged}
        return {k: v for k, v in challenges.items() if k in keep}

    def note(report) -> str:
        pulled = report["challenges"]
        if not pulled:
            return ""
        return ", tire " + ", ".join(sorted(c.name for c in pulled.values()))

    # LE LÉTAL PASSE AVANT LA VALEUR, et se teste donc en premier. Un
    # échange catastrophique qui gagne la partie reste le bon coup.
    if enemy_nexus_health is not None:
        total = evaluate(candidates, challenges)
        if total["nexus_damage"] >= enemy_nexus_health:
            return candidates, total, (
                f"attaque létale : {total['nexus_damage']} dégâts prévus "
                f"pour {enemy_nexus_health} PV adverses" + note(total)
            )

    if not blockers:
        report = evaluate_attack(candidates, [], None, weight, bonus)
        return candidates, report, "aucun bloqueur en face : tout passe"

    pressure = f" (1 dégât au nexus vaut {weight:.1f})" if weight != NEXUS_DAMAGE_WEIGHT else ""
    if strat is not strategy.DEFAULT:
        pressure += f" [{strat.name}]"
    engaged = list(candidates)
    while engaged:
        report = evaluate(engaged, challenges_for(engaged))
        if acceptable(report):
            dropped = len(candidates) - len(engaged)
            reason = (
                f"bilan {report['profit']:+g}, {report['nexus_damage']} au nexus"
                + (f", {dropped} unité(s) gardée(s) en défense" if dropped else "")
                + note(report) + pressure
            )
            return engaged, report, reason

        # Retirer celui dont le retrait améliore le plus le bilan.
        best_without, best_profit = None, None
        for card in engaged:
            rest = [c for c in engaged if c is not card]
            profit = (
                evaluate(rest, challenges_for(rest))["profit"]
                if rest else 0
            )
            if best_profit is None or profit > best_profit:
                best_without, best_profit = card, profit
        engaged = [c for c in engaged if c is not best_without]

    return [], None, "aucune attaque rentable : on garde le banc en défense" + pressure


# Tentatives de saisie par unité. Une deuxième passe ne coûte que le temps
# d'un geste et récupère les rares saisies ratées ; au-delà, s'entêter sur
# une unité qui refuse de bouger fait perdre le tour aux suivantes.
ENGAGE_ATTEMPTS = 2


def move_to_attack_row(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    card: BoardCard,
    dry_run: bool = False,
    attempts: int = ENGAGE_ATTEMPTS,
) -> tuple:
    """
    Avance une unité dans la rangée d'attaque, et vérifie qu'elle y est.

    L'INSTANTANÉ RENVOYÉ A DES COORDONNÉES STABILISÉES. C'est lui qui sert
    à retrouver l'unité suivante (cf. `relocate_card` dans
    `declare_attack`), et le banc met le temps d'une animation à se
    recentrer après chaque engagement : le rendre trop tôt, c'est faire
    saisir la voisine au geste suivant.

    En cas de saisie ratée, on relit la position et on retente une fois
    plutôt que d'abandonner l'attaquant pour le tour.
    """
    if dry_run:
        LOGGER.info("[plan] engager %s : %s -> %s",
                    card, card.grab_point, drop_point(card, snapshot.window))
        return True, snapshot

    live = card
    for attempt in range(1, max(1, attempts) + 1):
        before = _zone_counts(snapshot, "board")
        before_signature = snapshot_signature(snapshot)
        drag(live.grab_point, drop_point(live, snapshot.window))

        # `wait_for_change` attend le changement PUIS la fin du recentrage.
        snapshot = wait_for_change(reader, before_signature, timeout=AFTER_PLAY_TIMEOUT)
        after = _zone_counts(snapshot, "board")

        if _left_zone(snapshot, live, "board", before):
            LOGGER.info("%s engagée.", card.name)
            return True, snapshot

        # UNE AUTRE UNITÉ EST PARTIE À SA PLACE : la saisie a attrapé la
        # voisine. Surtout ne pas retenter — on viderait le banc unité par
        # unité en croyant corriger une erreur.
        if sum(after.values()) < sum(before.values()):
            LOGGER.warning(
                "Une autre unité que %s a été engagée : on ne retente pas.", card.name
            )
            return False, snapshot

        refreshed = relocate_card(snapshot, live, "board")
        if refreshed is None:
            LOGGER.warning("%s n'est plus sur le banc.", card.name)
            return False, snapshot
        if attempt < attempts:
            LOGGER.info("%s n'a pas quitté le banc, nouvelle saisie en %s (%d/%d).",
                        card.name, refreshed.grab_point, attempt + 1, attempts)
        live = refreshed

    LOGGER.warning("%s n'a pas quitté le banc après %d tentative(s).", card.name, attempts)
    return False, snapshot


def challenge_into_attack(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    card: BoardCard,
    target: BoardCard,
    dry_run: bool = False,
    attempts: int = ENGAGE_ATTEMPTS,
) -> tuple:
    """
    Engage une unité EN TIRANT une unité adverse en défense (Challenger).

    LE GESTE EST UN SEUL GLISSER, et c'est ce qui le rend fiable : on ne
    dépose pas dans la rangée d'attaque puis on ne clique pas l'ennemi.
    On saisit notre unité et on la lâche SUR l'unité adverse. Le client
    fait les deux d'un coup — notre unité avance, la sienne est tirée en
    face. Un geste au lieu de deux, donc deux fois moins d'occasions de
    rater, et aucun état intermédiaire à rattraper.

    DEUX RÉSULTATS À DISTINGUER, d'où le triplet renvoyé
    (engagée, tirée, instantané) :
        - notre unité a quitté le banc mais l'ennemie n'a pas bougé :
          l'attaque est déclarée, le tirage a été refusé. C'est un
          demi-succès, pas un échec — surtout ne rien défaire ;
        - notre unité est toujours au banc : la saisie a raté, on relit
          les deux positions et on retente.

    Les positions des DEUX cartes sont relues entre deux tentatives : le
    banc adverse se recentre lui aussi (`GEOMETRY_ZONES` le couvre).
    """
    if dry_run:
        LOGGER.info("[plan] %s tire %s : %s -> %s",
                    card.name, target.name, card.grab_point, target.center)
        return True, True, snapshot

    live, live_target = card, target
    for attempt in range(1, max(1, attempts) + 1):
        before_board = _zone_counts(snapshot, "board")
        before_enemy = _zone_counts(snapshot, "enemy_board")
        before_signature = snapshot_signature(snapshot)

        drag(live.grab_point, live_target.center)
        snapshot = wait_for_change(reader, before_signature, timeout=AFTER_PLAY_TIMEOUT)

        if _left_zone(snapshot, live, "board", before_board):
            pulled = _left_zone(snapshot, live_target, "enemy_board", before_enemy)
            if pulled:
                LOGGER.info("%s engagée en tirant %s.", card.name, target.name)
            else:
                LOGGER.warning(
                    "%s est engagée mais %s n'a pas été tirée : le client a "
                    "refusé le défi. L'attaque reste déclarée.",
                    card.name, target.name
                )
            return True, pulled, snapshot

        # UNE AUTRE UNITÉ EST PARTIE À SA PLACE : même règle qu'à
        # l'engagement simple, on ne retente pas — on viderait le banc.
        after = _zone_counts(snapshot, "board")
        if sum(after.values()) < sum(before_board.values()):
            LOGGER.warning(
                "Une autre unité que %s a été engagée : on ne retente pas.", card.name
            )
            return False, False, snapshot

        refreshed = relocate_card(snapshot, live, "board")
        if refreshed is None:
            LOGGER.warning("%s n'est plus sur le banc.", card.name)
            return False, False, snapshot
        refreshed_target = relocate_card(snapshot, live_target, "enemy_board")
        if refreshed_target is None:
            LOGGER.warning("%s a quitté le banc adverse : plus rien à tirer.", target.name)
            return False, False, snapshot

        if attempt < attempts:
            LOGGER.info("Défi raté, nouvelle saisie en %s vers %s (%d/%d).",
                        refreshed.grab_point, refreshed_target.center,
                        attempt + 1, attempts)
        live, live_target = refreshed, refreshed_target

    LOGGER.warning("%s n'a pas quitté le banc après %d tentative(s) de défi.",
                   card.name, attempts)
    return False, False, snapshot


def wait_for_combat_resolution(
    reader: GameStateReader, timeout: float = 30.0, poll: float = 0.8
) -> GameSnapshot:
    """
    Attend que la rangée d'attaque se vide, c'est-à-dire que le combat
    soit résolu. On n'attend PAS une durée fixe : la résolution dure de
    deux secondes à beaucoup plus selon les blocages et les effets.

    SANS BLOCAGE, ÇA SUFFIT : la rangée se vide seule. AVEC BLOCAGE, NON :
    des bloqueurs apparus dans `enemy_attack_row` signalent que le jeu
    attend un clic sur « Résoudre » pour faire avancer le combat — sans
    ce clic, les deux rangées restent engagées jusqu'au timeout. On
    retente ce clic à intervalles si le premier n'a pas suffi (plusieurs
    bloqueurs peuvent redemander la main autant de fois).
    """
    deadline = time.time() + timeout
    first_seen_blocked = None
    last_click = None
    snapshot = reader.snapshot()

    while time.time() < deadline:
        if not snapshot.attack_row and not snapshot.enemy_attack_row:
            return snapshot

        if snapshot.enemy_attack_row:
            now = time.time()
            if first_seen_blocked is None:
                first_seen_blocked = now
            due = (last_click or first_seen_blocked) + (
                RESOLVE_BUTTON_INITIAL_DELAY if last_click is None
                else RESOLVE_BUTTON_RETRY_DELAY
            )
            if now >= due:
                LOGGER.info("Attaque bloquée : clic sur 'Résoudre'.")
                click(*snapshot.window.rel(*mulligan_confirm_ratio()))
                last_click = now

        time.sleep(poll)
        snapshot = reader.snapshot()

    LOGGER.warning("Combat toujours non résolu après %.0f s.", timeout)
    return snapshot


def declare_attack(
    reader: GameStateReader,
    snapshot: Optional[GameSnapshot] = None,
    dry_run: bool = False,
) -> tuple:
    """
    Engage toutes les unités capables d'attaquer, puis confirme.

    Renvoie (unités_engagées, dernier_instantané, journal).
    """
    log = ActionLog()
    snapshot = snapshot or reader.stable_snapshot()

    if snapshot.phase is not Phase.ATTACK_TURN:
        log.add(f"Phase {snapshot.phase.name} : pas de jeton d'attaque, on n'attaque pas.")
        return [], snapshot, log

    # Stats réelles lues juste avant de décider, et pas plus tôt : l'OCR
    # coûte cher, et c'est ici que la différence entre un 3/4 supposé et
    # un 3/1 réel change le résultat de l'échange. On restreint aux zones
    # qui pèsent sur cette décision-là.
    enrich_with_live_stats(snapshot, zones=COMBAT_ZONES + ("enemy_board",))

    # `dry_run` VEUT DIRE « AUCUN GESTE », PAS « AUCUNE LECTURE ».
    # Les PV adverses étaient la SEULE lecture sautée en mode plan —
    # `enrich_with_live_stats` deux lignes au-dessus lit bien l'écran
    # dans les deux modes, et `play_hand` y lit les coûts comme ailleurs.
    # Résultat : `python actions.py attack --plan` décidait avec
    # `nexus_weight(None)` = poids de BASE (1 par défaut) quand la vraie
    # attaque montait jusqu'à 6 (`max(base, 40/pv)`, plafond 6), et
    # annonçait « on garde le banc en défense » juste avant que le bot
    # n'attaque avec tout. Le plan ne servait plus à prévoir.
    # Mesuré sur le plateau témoin du 06/09 (trois 4/3 face à 3/5 + 1/5) :
    # PV inconnus → aucun attaquant, 10 PV → les trois. Corrigé le
    # 10/11/2026.
    enemy_health = read_nexus_health(snapshot, local=False)
    candidates, report, reason = plan_attack(snapshot, enemy_health)
    log.add(f"Plan d'attaque : {reason}.")
    if report:
        log.add(
            f"    prévision : on perd {report['our_loss']}, on tue "
            f"{report['their_loss']}, {report['nexus_damage']} au nexus"
        )
    if not candidates:
        return [], snapshot, log

    log.add("Attaquants : " + ", ".join(f"{c.name}({c.attack}/{c.health})" for c in candidates))

    # {CardID de notre unité: unité adverse à tirer}. Décidé par
    # `plan_challenges`, exécuté ci-dessous par un glisser sur l'ennemi.
    challenges = report.get("challenges") or {} if report else {}
    for ours in candidates:
        target = challenges.get(ours.card_id)
        if target is not None:
            log.add(f"    {ours.name} tirera {target.name} en défense (défi)")

    # LES DÉFIS D'ABORD. Chaque geste peut rater, et celui-là vaut plus
    # que les autres : autant le tenter quand le plateau n'a encore bougé
    # pour personne. Tri STABLE, donc l'ordre par puissance de frappe est
    # conservé à l'intérieur de chaque groupe.
    ordered = sorted(candidates, key=lambda c: c.card_id not in challenges)

    engaged: List[BoardCard] = []
    handled: set = set()
    for card in ordered:
        # Le banc se recentre à CHAQUE unité engagée : les points de
        # saisie calculés au moment du plan sont périmés dès le premier
        # geste. On relit donc la position de la carte juste avant de la
        # saisir, sinon on attrape sa voisine — ou le vide.
        live = relocate_card(snapshot, card, "board", skip=handled)
        if live is None:
            log.add(f"{card.name} a quitté le banc entre-temps : on passe à la suivante.")
            continue
        if live.card_id >= 0:
            handled.add(live.card_id)

        # --- le défi, quand il y en a un -------------------------------
        target = challenges.get(live.card_id)
        live_target = (
            relocate_card(snapshot, target, "enemy_board") if target is not None else None
        )
        if target is not None and live_target is None:
            log.add(f"{target.name} a quitté le banc adverse : "
                    f"{live.name} attaque normalement.")

        if live_target is not None:
            done, pulled, snapshot = challenge_into_attack(
                reader, snapshot, live, live_target, dry_run=dry_run
            )
            if done:
                engaged.append(live)
                log.add(
                    f"{live.name} engagée en tirant {live_target.name}." if pulled
                    else f"{live.name} engagée, mais le défi sur "
                         f"{live_target.name} a été refusé."
                )
                continue

            # LE DÉFI A RATÉ, PAS L'ATTAQUE. On ne renonce pas à
            # l'attaquant : il vaut mieux l'engager sans tirage que le
            # laisser au banc parce qu'un geste plus ambitieux a échoué.
            log.add(f"Défi de {live.name} sur {live_target.name} raté : "
                    f"engagement simple.")
            live = relocate_card(snapshot, live, "board")
            if live is None:
                log.add(f"{card.name} n'est plus sur le banc : on passe.")
                continue

        success, snapshot = move_to_attack_row(reader, snapshot, live, dry_run=dry_run)
        if success:
            engaged.append(live)
        else:
            log.add(f"{card.name} non engagée, on continue avec les autres.")

    if dry_run:
        log.add("[plan] puis clic de confirmation de l'attaque.")
        return engaged, snapshot, log

    if not engaged:
        log.add("Aucune unité engagée : pas de confirmation, sinon on passerait le tour.")
        return [], snapshot, log

    # Le bouton de confirmation occupe la même place que l'orbe de fin de
    # tour. C'est pour ça qu'il ne faut cliquer QU'APRÈS avoir engagé au
    # moins une unité : sans attaquant déclaré, ce clic termine le tour.
    log.add(f"Confirmation de l'attaque avec {len(engaged)} unité(s).")
    click(*snapshot.window.rel(*TURN_BUTTON_RATIO))

    snapshot = wait_for_combat_resolution(reader)
    log.add("Combat résolu.")
    return engaged, snapshot, log


# ============================================================
# MULLIGAN
# ============================================================

MULLIGAN_MAX_COST = 3

# Attente APRÈS le clic de validation, avant de relire la phase.
#
# Valider le mulligan déclenche une salve d'animations : les cartes
# rejetées partent, les nouvelles arrivent, la main se recentre, puis le
# premier tour se met en place. Pendant tout ce temps le client annonce
# encore MULLIGAN — relire trop tôt faisait donc conclure « le clic de
# validation a raté » alors qu'il avait parfaitement pris, et la boucle
# recliquait par-dessus une main déjà validée.
#
# Trois secondes est un PLANCHER, pas une durée totale : la lecture qui
# suit est un `stable_snapshot`, qui attend de son côté deux lectures
# concordantes. Monter cette valeur si les animations sont plus lentes
# chez toi (client sur disque dur, machine chargée).
MULLIGAN_CONFIRM_WAIT = 3.0

# Valeur de DÉPART, probablement fausse : je n'ai jamais vu cet écran.
# Elle n'est utilisée que tant que la calibration n'a pas eu lieu.
#
#     python actions.py mulligan --calibrate
#
# ouvre une capture de l'écran de mulligan, te fait cliquer le bouton de
# validation, et enregistre le ratio dans calibration.json. Un clic humain
# vaut mieux qu'une constante devinée.
MULLIGAN_CONFIRM_RATIO = (0.50, 0.88)


# ============================================================
# CALIBRATION PERSISTÉE
# ============================================================
# Les positions apprises vont dans un fichier plutôt que dans le code :
# recalibrer ne demande alors pas de modifier une constante, et une mise
# à jour du projet n'écrase pas ce qui a été mesuré sur ta machine.

CALIBRATION_FILE = lor_api.PROJECT_ROOT / "calibration.json"


def load_calibration() -> dict:
    try:
        import json
        with open(CALIBRATION_FILE, encoding="utf8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_calibration(key: str, value) -> None:
    import json
    data = load_calibration()
    data[key] = value
    with open(CALIBRATION_FILE, "w", encoding="utf8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    LOGGER.info("Calibration « %s » enregistrée dans %s", key, CALIBRATION_FILE.name)


def mulligan_confirm_ratio() -> tuple:
    """Ratio calibré s'il existe, valeur de départ sinon."""
    saved = load_calibration().get("mulligan_confirm")
    if isinstance(saved, (list, tuple)) and len(saved) == 2:
        return tuple(saved)
    return MULLIGAN_CONFIRM_RATIO


def mulligan_is_calibrated() -> bool:
    return "mulligan_confirm" in load_calibration()


def cancel_point_ratio() -> tuple:
    """Zone vide calibrée s'il en existe une, valeur de départ sinon."""
    saved = load_calibration().get(CANCEL_CALIBRATION_KEY)
    if isinstance(saved, (list, tuple)) and len(saved) == 2:
        return tuple(saved)
    return CANCEL_POINT_RATIO


def cancel_is_calibrated() -> bool:
    return CANCEL_CALIBRATION_KEY in load_calibration()


def calibrate_cancel_point() -> Optional[tuple]:
    """
    Fait désigner une zone vide du plateau, où un clic gauche n'aura aucun
    effet de jeu.

    À lancer pendant un combat, pour voir le plateau tel qu'il sera au
    moment de l'annulation.
    """
    import game_state

    window = lor_api.get_window()
    screen = lor_api.capture_screen_bgr()

    print("Clique une zone VIDE du plateau : ni carte, ni bouton, ni nexus.")
    print("C'est là que le bot cliquera pour annuler une action en attente.")
    point = game_state.pick_point_tk(screen, "Clique une zone vide du plateau")
    if point is None:
        print("Calibration annulée.")
        return None

    ratio = (
        (point[0] - window.x) / window.width,
        (point[1] - window.y) / window.height,
    )
    save_calibration(CANCEL_CALIBRATION_KEY, list(ratio))
    print(f"\nZone d'annulation : {point} soit ({ratio[0]:.4f}, {ratio[1]:.4f}).")
    return ratio


def mulligan_candidates(snapshot: GameSnapshot, max_cost: int = MULLIGAN_MAX_COST):
    """
    Cartes à remplacer : tout ce qui coûte plus de `max_cost`.

    ATTENTION : on ne peut PAS utiliser snapshot.hand ici. Pendant le
    mulligan les cartes sont affichées au milieu de l'écran, donc elles
    tombent dans la bande `enemy_attack` du classement par zones. Il faut
    donc prendre toutes nos cartes, quelle que soit leur zone.
    """
    return [
        card for card in snapshot.cards()
        if card.local and card.known and card.cost > max_cost
    ]


def calibrate_mulligan_button() -> Optional[tuple]:
    """
    Fait désigner le bouton de validation du mulligan, et l'enregistre.

    À lancer PENDANT l'écran de mulligan : la capture est prise
    immédiatement, donc le bouton doit être visible à l'écran.
    """
    import game_state

    window = lor_api.get_window()
    screen = lor_api.capture_screen_bgr()

    print("Une fenêtre va s'ouvrir sur la capture de l'écran de mulligan.")
    print("Clique le bouton de validation, puis ENTRÉE.")
    point = game_state.pick_point_tk(screen, "Clique le bouton de validation du mulligan")
    if point is None:
        print("Calibration annulée.")
        return None

    ratio = (
        (point[0] - window.x) / window.width,
        (point[1] - window.y) / window.height,
    )
    save_calibration("mulligan_confirm", list(ratio))
    print(f"\nBouton mémorisé : {point} soit ({ratio[0]:.4f}, {ratio[1]:.4f}) de la fenêtre.")
    return ratio


def do_mulligan(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    max_cost: int = MULLIGAN_MAX_COST,
    dry_run: bool = False,
) -> ActionLog:
    """
    Remplace les cartes trop chères, puis valide.

    La validation est VÉRIFIÉE : on relit la phase après le clic. Si elle
    est toujours MULLIGAN, le bouton n'a pas été touché — on le dit
    clairement plutôt que de laisser la boucle tourner dans le vide, et
    on nomme la commande qui corrige le tir.
    """
    log = ActionLog()
    to_replace = mulligan_candidates(snapshot, max_cost)
    kept = [c for c in snapshot.cards() if c.local and c not in to_replace]

    log.add(f"Mulligan (seuil : coût > {max_cost})")
    log.add("    gardées  : " + (", ".join(f"{c.name}({c.cost})" for c in kept) or "aucune"))
    log.add("    rejetées : " + (", ".join(f"{c.name}({c.cost})" for c in to_replace) or "aucune"))

    ratio = mulligan_confirm_ratio()
    confirm = snapshot.window.rel(*ratio)
    calibrated = mulligan_is_calibrated()

    if dry_run:
        for card in to_replace:
            log.add(f"[plan] clic sur {card.name} en {card.center}")
        log.add(
            f"[plan] validation en {confirm}"
            + ("" if calibrated else " — POSITION NON CALIBRÉE, probablement fausse")
        )
        return log

    if not calibrated:
        log.add(
            "Position du bouton non calibrée : lance "
            "`python actions.py mulligan --calibrate` pendant cet écran."
        )

    for card in to_replace:
        click(*card.center)
        time.sleep(0.4)

    log.add(f"Validation en {confirm}.")
    click(*confirm)
    # Les animations d'échange de cartes passent AVANT qu'on relise quoi
    # que ce soit : cf. MULLIGAN_CONFIRM_WAIT.
    time.sleep(MULLIGAN_CONFIRM_WAIT)

    after = reader.stable_snapshot(confirmations=2, poll=0.6, timeout=8.0)
    if after.phase is Phase.MULLIGAN:
        log.add(
            "La phase est toujours MULLIGAN : le clic de validation a raté. "
            "Recalibre avec `python actions.py mulligan --calibrate`."
        )
    else:
        log.add(f"Mulligan validé, phase {after.phase.name}.")
    return log


# ============================================================
# BLOCAGE
# ============================================================
# La DÉCISION est une fonction pure (`plan_blocks`) séparée de
# l'EXÉCUTION (`execute_blocks`). C'est la phase avec le plus de règles,
# et une erreur de raisonnement y coûte la partie : pouvoir la tester
# exhaustivement sans souris ni jeu vaut la séparation.

# Valeur d'un blocage, du meilleur au pire.
BLOCK_KILL_AND_SURVIVE = 3
BLOCK_SURVIVE = 2
BLOCK_TRADE = 1
BLOCK_CHUMP = 0

# Attaque minimale pour bloquer une unité Fearsome (règle du jeu).
FEARSOME_MIN_ATTACK = 3


def can_block_attacker(blocker: BoardCard, attacker: BoardCard) -> bool:
    """
    Ce bloqueur a-t-il le DROIT de bloquer cet attaquant ?

    Trois règles du jeu, et elles ne se devinent pas depuis les stats :
        - Insaisissable (Elusive) : seule une unité Insaisissable peut la
          bloquer ;
        - Redoutable (Fearsome) : il faut au moins 3 d'attaque ;
        - Ne peut pas bloquer / Immobile : l'unité est hors jeu défensif.
    Les ignorer produit des blocages que le client refuse, donc des drags
    perdus et un tour qui traîne.
    """
    if not blocker.can_block:
        return False
    if attacker.has("Elusive") and not blocker.has("Elusive"):
        return False
    # Redoutable se mesure à la puissance de FRAPPE : une 0/5 Formidable
    # frappe pour 5 et a donc le droit de bloquer.
    if attacker.has("Fearsome") and keywords.strike_power(blocker) < FEARSOME_MIN_ATTACK:
        return False
    return True


def damage_through(blocker: BoardCard, attacker: BoardCard) -> int:
    """
    Dégâts qui atteignent notre nexus MALGRÉ le blocage.

    Submersion fait passer l'excédent au-delà des PV du bloqueur, Impact
    ajoute son point à chaque frappe. Sans ce calcul, un blocage
    sacrificiel sur un attaquant Submersion est compté comme protecteur
    alors qu'il ne l'est presque pas — exactement le cas où l'erreur
    coûte la partie.

    Le détail (Barrière qui annule l'excédent, Coriace qui le réduit,
    Frappe Double qui frappe deux fois) vit dans `keywords.resolve_duel`.
    """
    return keywords.resolve_duel(attacker, blocker).nexus_damage


def block_score(blocker: BoardCard, attacker: BoardCard) -> int:
    """
    Qualité d'un blocage : tuer sans mourir > survivre > échanger > mourir.

    Le duel est résolu par `keywords.resolve_duel`, ordre des frappes
    compris. C'est ce qui distingue enfin les trois situations que
    l'ancien `attack >= health` confondait : bloquer une Frappe Rapide
    (on meurt sans riposter), bloquer avec une Barrière (on ne prend
    rien), bloquer une unité Coriace (notre frappe fait 1 de moins).
    """
    duel = keywords.resolve_duel(attacker, blocker)
    kills = duel.attacker_dies
    survives = not duel.blocker_dies
    if kills and survives:
        return BLOCK_KILL_AND_SURVIVE
    if survives:
        return BLOCK_SURVIVE
    if kills:
        return BLOCK_TRADE
    return BLOCK_CHUMP


def _blocker_preference(blocker: BoardCard, attacker: BoardCard) -> tuple:
    """
    Départage deux bloqueurs de MÊME qualité de blocage. Plus grand vaut
    mieux.

    « Qualité égale » veut dire même verdict sur les deux morts — c'est
    exactement ce que `block_score` résume — donc les deux cas ci-dessous
    ne se mélangent jamais dans un même arbitrage.

    LE BLOQUEUR MEURT (échange, sacrifice) : on engage la mort la moins
    chère, `death_cost` tranche, et une Éphémère passe donc devant.

    LE BLOQUEUR SURVIT : le blocage ne lui coûte rien, et ce qui compte
    alors est ce qui RESTE disponible derrière. On garde l'Éphémère
    LIBRE : sa seule utilité restante ce round est de se jeter
    gratuitement devant un autre attaquant, tandis qu'une unité
    permanente servira encore au round suivant. Sans cette réserve,
    l'Éphémère prenait le bon blocage — sa mort étant « gratuite », elle
    gagnait l'égalité — et le gros attaquant passait sans rencontrer
    personne, alors qu'elle pouvait l'encaisser pour rien.

    À défaut, `-death_cost` garde la règle d'origine : engager la plus
    petite unité, garder les grosses pour attaquer.
    """
    survives = not keywords.resolve_duel(attacker, blocker).blocker_dies
    reserved = survives and keywords.dies_anyway(blocker)
    return (-1 if reserved else 0, -keywords.death_cost(blocker))


def _assign(attackers, blockers, minimum_score):
    """
    Associe un bloqueur à chaque attaquant, du plus dangereux au moins
    dangereux. Un attaquant ne peut recevoir qu'un seul bloqueur.

    À qualité de blocage égale, `_blocker_preference` tranche.
    """
    pairs, remaining = [], list(blockers)

    # « Le plus dangereux » se mesure aux dégâts qu'il passerait, pas à sa
    # seule attaque : Formidable et Impact comptent.
    ordered = sorted(attackers, key=lambda c: (keywords.unblocked_damage(c), c.health),
                     reverse=True)

    for attacker in ordered:
        legal = [b for b in remaining if can_block_attacker(b, attacker)]
        if not legal:
            continue
        best = max(
            legal,
            key=lambda b: (block_score(b, attacker),) + _blocker_preference(b, attacker),
        )
        if block_score(best, attacker) < minimum_score:
            continue
        pairs.append((best, attacker))
        remaining.remove(best)

    return pairs, remaining


# Une unité TIRÉE devant un attaquant (Challenger, Vulnerable) se tient à
# la verticale de celui-ci. Au-delà de cet écart en x, on ne l'associe à
# aucun attaquant : mieux vaut la croire libre que lui inventer un poste.
PULLED_BLOCK_TOLERANCE = 0.12   # fraction de la largeur de la fenêtre


def pulled_blocks(snapshot: GameSnapshot) -> list:
    """
    Les blocages DÉJÀ EN PLACE avant qu'on ait rien fait : nos unités que
    l'adversaire a tirées en face de ses attaquants.

    Signalé par Ewan le 03/09/2026 : « le bot essaye de bloquer les
    unités qui ont grab avec des unités du banc ». Un Challenger tire une
    de nos unités dans notre rangée d'attaque, face à lui ; cet
    attaquant-là est bloqué, le jeu ne le laissera pas l'être une seconde
    fois — et le bot glissait quand même un bloqueur du banc dessus, en
    vain, pendant qu'un autre attaquant passait.

    L'appariement se lit sur l'écran : l'unité tirée est à la verticale
    de son attaquant. Chaque attaquant n'est pris qu'une fois, le plus
    proche d'abord. Renvoie [(notre_unité_tirée, attaquant)].
    """
    pulled = [c for c in snapshot.attack_row if c.is_unit]
    attackers = [c for c in snapshot.enemy_attack_row if c.is_unit]
    if not pulled or not attackers:
        return []
    tolerance = snapshot.window.width * PULLED_BLOCK_TOLERANCE
    candidates = sorted(
        ((abs(b.center[0] - a.center[0]), b, a) for b in pulled for a in attackers),
        key=lambda t: t[0],
    )
    pairs, used_b, used_a = [], set(), set()
    for gap, blocker, attacker in candidates:
        if gap > tolerance:
            break
        if id(blocker) in used_b or id(attacker) in used_a:
            continue
        pairs.append((blocker, attacker))
        used_b.add(id(blocker))
        used_a.add(id(attacker))
    return pairs


def plan_blocks(snapshot: GameSnapshot, nexus_health: Optional[int] = None,
                allow_chump: bool = False) -> tuple:
    """
    Décide qui bloque quoi. Fonction pure : aucune souris, aucune capture.

    Trois passes. La première n'accepte que des blocages qui rapportent
    quelque chose (on tue, ou on survit). La deuxième jette devant les
    attaquants restants les unités qui MEURENT DE TOUTE FAÇON en fin de
    round (Éphémères) : ça n'a rien d'un sacrifice, donc c'est
    inconditionnel. La troisième, elle, autorise de vrais blocages
    sacrificiels — mais seulement si le nexus ne survit pas aux dégâts
    encore attendus, ou si l'appelant l'a explicitement demandé.

    Perdre des unités est mauvais ; perdre la partie est pire. Mais se
    sacrifier sans nécessité l'est aussi, d'où la condition.

    Renvoie (paires, dégâts_non_bloqués, raison). Les paires sont celles
    À RÉALISER : les blocages déjà en place (unités tirées par un
    Challenger, cf. `pulled_blocks`) n'y figurent pas, mais leurs
    attaquants sont retirés du problème et leurs dégâts traversants
    comptés.
    """
    already = pulled_blocks(snapshot)
    covered = {id(attacker) for _, attacker in already}
    all_attackers = list(snapshot.enemy_attack_row)
    attackers = [c for c in all_attackers if id(c) not in covered]
    blockers = [c for c in snapshot.board if c.is_unit and c.can_block]
    pulled_note = f", {len(already)} déjà bloqué(s) par une unité tirée" if already else ""

    def leaking_damage(pairs, attackers):
        """
        Dégâts au nexus : attaquants non bloqués, plus ce qui traverse les
        bloqueurs (Submersion, Impact) — y compris les bloqueurs tirés.
        """
        by_attacker = {id(attacker): blocker for blocker, attacker in pairs + already}
        total = 0
        for attacker in attackers:
            blocker = by_attacker.get(id(attacker))
            total += (
                keywords.unblocked_damage(attacker) if blocker is None
                else damage_through(blocker, attacker)
            )
        return total

    if not attackers:
        if already:
            return [], leaking_damage([], all_attackers), f"tout est déjà bloqué{pulled_note}"
        return [], 0, "aucun attaquant"
    if not blockers:
        return (
            [],
            leaking_damage([], all_attackers),
            f"aucun bloqueur disponible{pulled_note}",
        )

    pairs, remaining = _assign(attackers, blockers, BLOCK_TRADE)
    blocked = {id(attacker) for _, attacker in pairs}
    leaking = leaking_damage(pairs, all_attackers)

    # JETER UNE ÉPHÉMÈRE DEVANT UN ATTAQUANT NE COÛTE RIEN. Elle meurt en
    # fin de round de toute façon, et ce round est celui de l'adversaire :
    # elle n'attaquera pas. Le blocage sacrificiel n'est donc pas un
    # sacrifice, et il n'a pas à attendre la condition de létalité — c'est
    # des dégâts absorbés pour rien. Volontairement limité à
    # `dies_anyway` : une Sans-mort revient à 1 PV, sa mort est bon marché
    # mais pas gratuite.
    free = [b for b in remaining if keywords.dies_anyway(b)]
    gifts = []
    if leaking > 0 and free:
        gifts, _ = _assign(
            [c for c in attackers if id(c) not in blocked], free, BLOCK_CHUMP
        )
        for blocker, attacker in gifts:
            remaining.remove(blocker)
            blocked.add(id(attacker))
        pairs += gifts
        leaking = leaking_damage(pairs, all_attackers)

    free_note = (f", dont {len(gifts)} gratuit(s)" if gifts else "") + pulled_note

    if leaking == 0:
        return pairs, 0, f"tout est bloqué{free_note}"

    lethal = nexus_health is not None and leaking >= nexus_health
    if not (lethal or allow_chump):
        if nexus_health is None:
            reason = f"{leaking} dégâts encaissés (PV du nexus illisibles){free_note}"
        else:
            reason = f"{leaking} dégâts encaissés, nexus à {nexus_health} PV{free_note}"
        return pairs, leaking, reason

    # Blocage sacrificiel avec ce qu'il reste.
    unblocked = [c for c in attackers if id(c) not in blocked]
    extra, _ = _assign(unblocked, remaining, BLOCK_CHUMP)
    pairs += extra

    blocked |= {id(attacker) for _, attacker in extra}
    leaking = leaking_damage(pairs, all_attackers)
    if lethal:
        # « Évité » est une CONSTATATION, pas une intention : les blocages
        # sacrificiels ne suffisent pas toujours, et l'annoncer à tort
        # rendrait le diagnostic menteur au moment où il compte le plus.
        verdict = "létal évité" if leaking < nexus_health else "létal INÉVITABLE"
        reason = f"{verdict} : {len(extra)} blocage(s) sacrificiel(s){free_note}"
    else:
        reason = f"{len(extra)} blocage(s) sacrificiel(s) (option chump){free_note}"
    return pairs, leaking, reason


def execute_blocks(
    reader: GameStateReader,
    snapshot: Optional[GameSnapshot] = None,
    allow_chump: bool = False,
    dry_run: bool = False,
) -> tuple:
    """
    Assigne les bloqueurs puis confirme.

    Renvoie (paires_réalisées, dernier_instantané, journal).
    """
    log = ActionLog()
    snapshot = snapshot or reader.stable_snapshot()

    if snapshot.phase is not Phase.BLOCKING:
        log.add(f"Phase {snapshot.phase.name} : rien à bloquer.")
        return [], snapshot, log

    # La phase BLOCKING se lit dès que les unités adverses sont avancées,
    # y compris pendant l'animation de la charge — c'est voulu, sinon
    # l'attaque passait inaperçue. Mais agir demande d'avoir la main :
    # tant que l'orbe est grise, un glissé ne ferait rien et le bot
    # conclurait à tort que le bloqueur refuse son poste. On attend donc
    # ici, une fois, plutôt que de rendre la lecture d'état frileuse.
    if not dry_run and snapshot.turn_orb_active is False:
        log.add("Attaque déclarée, orbe encore grise : on attend la main.")
        deadline = time.time() + BLOCK_PRIORITY_TIMEOUT
        while time.time() < deadline and snapshot.turn_orb_active is False:
            time.sleep(0.4)
            snapshot = reader.snapshot()
        if snapshot.phase is not Phase.BLOCKING:
            log.add(f"L'attaque s'est résolue seule (phase {snapshot.phase.name}).")
            return [], snapshot, log
        if snapshot.turn_orb_active is False:
            log.add("Toujours pas la main : on repassera à la lecture suivante.")
            return [], snapshot, log

    # Le blocage est la décision la plus sensible aux stats réelles : un
    # attaquant déjà blessé se tue avec une unité qu'on croyait trop
    # faible, et un bloqueur affaibli meurt à un échange qu'on croyait
    # gagnant.
    enrich_with_live_stats(snapshot, zones=COMBAT_ZONES)

    # Même correction qu'à l'attaque, et l'écart y est plus brutal
    # encore : sans les PV, `plan_blocks` refuse le blocage sacrificiel
    # et écrit « PV du nexus illisibles » — donc `block --plan` annonçait
    # « 5 dégâts encaissés » quand le bot, lui, allait sacrifier pour
    # survivre. Une lecture n'est pas un geste. 10/11/2026.
    # L'ÉTOURDISSEMENT SE LIT AVANT DE PLANIFIER, pas après le refus du
    # jeu (14/11/2026). Une unité étourdie ne peut pas bloquer, et rien
    # dans l'API ne le dit : sans cette lecture, `plan_blocks` l'engage,
    # le glissé est refusé, et l'attaquant passe — 41 fois dans `logs/`.
    # En mode plan on ne regarde pas l'écran : `block --plan` doit rester
    # une lecture, jamais un geste ni une capture.
    if not dry_run:
        lire_les_etourdies(snapshot)

    health = read_nexus_health(snapshot, local=True)
    pairs, leaking, reason = plan_blocks(snapshot, health, allow_chump)
    log.add(f"Plan de blocage : {reason}.")
    for blocker, attacker in pairs:
        log.add(
            f"    {blocker.name} ({blocker.attack}/{blocker.health})"
            f" bloque {attacker.name} ({attacker.attack}/{attacker.health})"
            f" [valeur {block_score(blocker, attacker)}]"
        )
    if leaking:
        log.add(f"    {leaking} dégâts passeront au nexus.")

    if dry_run:
        log.add("[plan] puis clic de confirmation des blocages.")
        return pairs, snapshot, log

    done = []
    handled: set = set()
    refuses: set = set()
    for index, (blocker, attacker) in enumerate(pairs):
        # Même piège qu'à l'attaque, en pire : chaque bloqueur posé
        # recentre le banc ET peut décaler la rangée adverse. Les deux
        # extrémités du glissé sont donc relues avant chaque geste.
        live_blocker = relocate_card(snapshot, blocker, "board", skip=handled)
        live_attacker = relocate_card(snapshot, attacker, "enemy_attack")
        if live_blocker is None or live_attacker is None:
            missing = blocker.name if live_blocker is None else attacker.name
            log.add(f"{missing} n'est plus là où on l'attendait : blocage abandonné.")
            continue
        if live_blocker.card_id >= 0:
            handled.add(live_blocker.card_id)

        before = _zone_counts(snapshot, "board")
        before_signature = snapshot_signature(snapshot)
        drag(live_blocker.grab_point, live_attacker.center)
        snapshot = wait_for_change(reader, before_signature, timeout=AFTER_PLAY_TIMEOUT)

        if _left_zone(snapshot, live_blocker, "board", before):
            done.append((live_blocker, live_attacker))
            continue

        # UN REFUS EST UN FAIT OBSERVÉ, ET IL VAUT MIEUX QUE L'ÉTAT QU'ON
        # NE SAIT PAS LIRE (14/11/2026, fait de jeu d'Ewan : « il a tenté
        # de bloquer alors que le défenseur était stun »).
        #
        # L'API ne rend que sept champs — CardCode, CardID, LocalPlayer
        # et la géométrie : ni état, ni statistique. `can_block` ne
        # connaît donc que `CantBlock` et `Immobile`, deux mots-clés
        # IMPRIMÉS, et un Stun n'y apparaît jamais. Mais le glissé, lui,
        # a VISIBLEMENT été refusé. Mesuré dans `logs/` : 41 fois, dont
        # 11 le 14/11 — et à chaque fois l'attaquant passait au nexus
        # alors que le plan venait d'annoncer « tout est bloqué ».
        #
        # On envoie donc un autre bloqueur LÉGAL sur le MÊME attaquant.
        # Cela traite le Stun sans le lire, et avec lui toutes les causes
        # qu'on ne connaît pas encore.
        refuses.add(id(live_blocker))
        if live_blocker.card_id >= 0:
            refuses.add(live_blocker.card_id)
        log.add(f"{blocker.name} n'a pas pris son poste.")

        # On ne VOLE PAS un bloqueur encore attendu ailleurs : les paires
        # suivantes n'ont pas encore été jouées, et leur retirer leur
        # unité déplacerait simplement le trou.
        promis = {id(b) for b, _ in pairs[index + 1:]}
        promis |= {b.card_id for b, _ in pairs[index + 1:] if b.card_id >= 0}
        candidats = [
            c for c in snapshot.board
            if c.is_unit and c.can_block
            and id(c) not in refuses and c.card_id not in refuses
            and c.card_id not in handled
            and id(c) not in promis and c.card_id not in promis
            and can_block_attacker(c, live_attacker)
        ]
        if not candidats:
            log.add("    aucun remplaçant disponible, on passe au suivant.")
            continue

        # UN SEUL REMPLAÇANT, PUIS ON PASSE : devant un jeu qui refuse,
        # s'entêter coûte le temps que ce projet paie à chaque fois.
        remplacant = max(candidats, key=lambda c: block_score(c, live_attacker))
        log.add(f"    on tente {remplacant.name} à sa place.")
        if remplacant.card_id >= 0:
            handled.add(remplacant.card_id)
        before = _zone_counts(snapshot, "board")
        before_signature = snapshot_signature(snapshot)
        drag(remplacant.grab_point, live_attacker.center)
        snapshot = wait_for_change(reader, before_signature, timeout=AFTER_PLAY_TIMEOUT)
        if _left_zone(snapshot, remplacant, "board", before):
            done.append((remplacant, live_attacker))
        else:
            log.add(f"    {remplacant.name} refuse aussi : {live_attacker.name} passera.")

    # Ici on confirme MÊME sans aucun blocage, contrairement à l'attaque :
    # le jeu attend une réponse pour continuer, et « je ne bloque rien »
    # est une réponse valide. Ne pas cliquer bloquerait la partie.
    log.add(f"Confirmation de {len(done)} blocage(s).")
    click(*snapshot.window.rel(*TURN_BUTTON_RATIO))
    snapshot = wait_for_combat_resolution(reader)
    return done, snapshot, log


# ============================================================
# TOUR COMPLET
# ============================================================

def play_turn(
    reader: GameStateReader,
    snapshot: Optional[GameSnapshot] = None,
    allow_spells: bool = False,
    finish_turn: bool = True,
    dry_run: bool = False,
    carry: Optional[dict] = None,
) -> ActionLog:
    """
    Un tour de bout en bout : poser des cartes, attaquer si on a le
    jeton, terminer le tour.

    L'ordre n'est pas arbitraire. On pose AVANT d'attaquer pour que les
    unités posées ce tour comptent dans le plateau, et on attaque avant de
    terminer parce que le bouton de fin de tour et celui de confirmation
    de l'attaque sont au même endroit : inverser l'ordre passerait le tour
    sans attaquer.
    """
    log = ActionLog()
    snapshot = snapshot or reader.stable_snapshot()
    log.add(f"Début de tour en phase {snapshot.phase.name}.")

    if not snapshot.phase.is_our_move:
        log.add("Ce n'est pas à nous : rien à faire.")
        return log

    played, snapshot, play_log = play_hand(
        reader, snapshot, allow_spells=allow_spells, dry_run=dry_run, carry=carry,
    )
    log.entries.extend(play_log.entries)
    log.adopt_mana(play_log)
    log.rejections.extend(r for r in play_log.rejections if r not in log.rejections)
    log.add(f"{len(played)} carte(s) posée(s).")

    # LA PHASE A PU CHANGER PENDANT QU'ON POSAIT, ET C'EST NORMAL.
    #
    # Chaque pose rend la priorité à l'adversaire : il peut déclarer son
    # attaque entre deux de nos cartes. Le tour reprenait ici sans jamais
    # relire ce qui venait de se passer, et il en sortait deux erreurs
    # enchaînées — la ligne « Phase BLOCKING : pas d'attaque ce tour »,
    # qui affirmait le contraire de ce qu'elle affichait, puis le clic de
    # fin de tour, qui PASSAIT le blocage. L'attaque entière arrivait au
    # nexus sans qu'une seule unité soit posée en défense.
    #
    # On rend donc la main à la boucle, qui aiguillera vers le blocage.
    # Terminer le tour n'a de sens que si c'est encore notre tour.
    if snapshot.phase in (Phase.BLOCKING, Phase.ATTACKING, Phase.SPELL_STACK):
        log.add(
            f"L'adversaire a agi pendant la pose (phase {snapshot.phase.name}) : "
            "on rend la main sans terminer le tour."
        )
        return log

    if not snapshot.phase.is_our_move:
        log.add(f"Phase {snapshot.phase.name} : ce n'est plus à nous, on ne clique pas.")
        return log

    if snapshot.phase is Phase.ATTACK_TURN:
        engaged, snapshot, attack_log = declare_attack(reader, snapshot, dry_run=dry_run)
        log.entries.extend(attack_log.entries)
        log.add(f"{len(engaged)} unité(s) engagée(s).")

        # Même prudence après l'attaque : la confirmation peut nous
        # ramener en résolution de combat, où le bouton ne veut plus dire
        # « fin de tour ».
        if snapshot.phase in (Phase.BLOCKING, Phase.ATTACKING, Phase.SPELL_STACK):
            log.add(f"Combat en cours (phase {snapshot.phase.name}) : on ne termine pas le tour.")
            return log
    else:
        # Formulation prudente : cette ligne ne parle que de NOTRE
        # attaque. Elle a longtemps été lue comme « l'adversaire
        # n'attaque pas », ce qu'elle n'a jamais voulu dire.
        log.add(f"Phase {snapshot.phase.name} : nous n'avons pas le jeton, on n'attaque pas.")

    if finish_turn:
        end_turn(snapshot.window, dry_run=dry_run)
        log.add("Fin de tour.")

    return log


# ============================================================
# CLI
# ============================================================

def _describe(snapshot: GameSnapshot, pool: ManaPool,
              allow_spells: bool = True) -> None:
    print(f"\nPhase        : {snapshot.phase.name}")
    print(f"Mana         : {pool}")
    print(f"Places banc  : {free_board_slots(snapshot)} / {MAX_BOARD_SIZE}")

    live = sum(1 for c in snapshot.hand if c.cost_is_live)
    if READ_SCREEN_COSTS:
        print(f"Coûts écran  : {live} / {len(snapshot.hand)} carte(s) de main lues")
        for card, gap in cost_gaps(snapshot):
            print(f"               {card.name} : {card.base_cost} -> {card.cost} ({gap:+d})")
    else:
        print("Coûts écran  : désactivés (--base-costs) — coûts imprimés uniquement")

    print(f"\nMain ({len(snapshot.hand)}) :")
    if not snapshot.hand:
        print("    (vide)")
    for card in snapshot.hand:
        # UNE SEULE SOURCE, ET C'EST CELLE DE LA DÉCISION.
        # `rejection_reason` est déjà l'explication de `playable_cards` ;
        # ce tableau n'a pas à refaire le test une TROISIÈME fois. Il
        # l'a fait longtemps, et il mentait : ses motifs étaient
        # calculés puis JETÉS dès qu'un sort était lançable, si bien
        # qu'un sort TROP CHER s'affichait « JOUABLE » pendant que la
        # décision le refusait. Vu sur un vrai plateau le 09/11/2026 —
        # Withering Wail à 4 avec 3 de mana, annoncée JOUABLE trois
        # lignes au-dessus de « Rien à jouer », pendant qu'une Spirit
        # Leech au MÊME coût était bien dite « trop chère ».
        # C'est le piège que `unit_play_blocker` nomme plus haut : deux
        # implémentations du même test finissent toujours par diverger,
        # et c'est alors le diagnostic qui ment.
        motif = rejection_reason(card, snapshot, pool, allow_spells)
        if motif is not None:
            verdict = f"non — {motif}"
        elif card.is_spell or card.is_ability:
            # Le PLAN dit ce que le bot irait CLIQUER : c'est la seule
            # chose que `rejection_reason` ne donne pas, et c'est pour
            # elle qu'on vient lire ce tableau.
            _, spell_plan, _, _ = spell_is_castable(card, snapshot)
            verdict = f"JOUABLE ({spell_plan})"
        else:
            verdict = "JOUABLE"
        print(f"    {str(card):<44} saisie {card.grab_point}  {verdict}")

    print(f"\nBanc ({len(snapshot.board)}) :")
    for card in snapshot.board:
        print(f"    {card}")


def rejection_reason(card: BoardCard, snapshot: GameSnapshot, pool: ManaPool,
                    allow_spells: bool) -> Optional[str]:
    """Pourquoi cette carte n'est pas jouable, ou None si elle l'est."""
    if card.zone != "hand":
        return f"pas classée en main (zone « {card.zone} »)"

    if not CARD_RESTRICTIONS:
        # Mêmes tests que `playable_cards` dans ce mode, dans le même
        # ordre : le diagnostic ne doit jamais dire autre chose que la
        # décision.
        if card.is_unit or card.is_landmark:
            needed = 2 if summons_extra_body(card) else 1
            slots = free_board_slots(snapshot)
            if needed > slots:
                return f"il faut {needed} place(s), il en reste {slots}"
            blocker = unit_play_blocker(card, snapshot)
            if blocker:
                return f"pouvoir à cibler : {blocker}"
        if card.is_spell or card.is_ability:
            allowed, why = spells.can_cast_now(card, snapshot)
            if not allowed:
                return f"sort : {why}"
            plan = spells.classify_card(card, restricted=False)
            if plan.impossible:
                return f"sort : {plan.reason}"
            if plan.is_trade:
                _, why = spells.choose_trade_targets(plan, snapshot)
                if why:
                    return f"sort : {why}"
            # Le préfixe « sort : » n'est pas décoratif : c'est lui qui
            # range « aucun ennemi en jeu », « aucune cible » et
            # « N cibles requises » dans le CONTEXTE de la partie plutôt
            # que dans le backlog de `journal.py --ecartees`
            # (journal.CONTEXT_PREFIXES).
            motif = sort_sans_cible(card, snapshot)
            if motif:
                return f"sort : {motif}"
        # UN ÉQUIPEMENT SANS PORTEUR, EXACTEMENT COMME DANS LA DÉCISION.
        # Ce test manquait ici, et SEULEMENT ici : la branche jumelle de
        # `playable_cards` l'applique depuis le 05/11 (« The Darkin
        # Lodestone tentée HUIT fois, banc vide »), mais l'explication ne
        # l'a jamais eu. Elle rendait donc None — c'est-à-dire JOUABLE —
        # sur une carte que le bot ne pose pas.
        #
        # Le défaut est resté invisible tant que `_describe` tenait sa
        # PROPRE liste de motifs : il écrivait « non — équipement » de son
        # côté. En le faisant déléguer (09/11/2026), on a hérité du trou
        # et `python actions.py plan` s'est mis à écrire JOUABLE. C'est la
        # démonstration de l'invariant plutôt que son démenti : il n'y a
        # qu'un seul endroit à réparer, et le voilà.
        if card.is_equipment:
            _, description = equipment_plan(card, snapshot)
            if _ is None:
                return f"équipement : {description}"
        if not can_pay(card, pool):
            source = "lu à l'écran" if card.cost_is_live else "de card_sets"
            return f"coût {card.cost} ({source}) > mana {pool.mana}"
        return None

    if not card.cost_is_known:
        return "absente de card_sets et coût non lu à l'écran"
    if card.is_spell or card.is_ability:
        if not SPELLS_ENABLED:
            return "sort, et SPELLS_ENABLED est à False"
        if not allow_spells:
            return "sort, et --spells n'est pas passé"
        castable, _, _, why = spell_is_castable(card, snapshot)
        return None if castable else f"sort : {why}"
    if card.is_equipment:
        point, description = equipment_plan(card, snapshot)
        if point is None:
            return f"équipement : {description}"
        return None if can_pay(card, pool) else (
            f"coût {card.cost} > mana {pool.mana}"
        )
    if not (card.is_unit or card.is_landmark):
        return f"type « {card.type or 'inconnu'} » non géré"
    needed = 2 if summons_extra_body(card) else 1
    slots = free_board_slots(snapshot)
    if needed > slots:
        return f"il faut {needed} place(s), il en reste {slots}"
    blocker = unit_play_blocker(card, snapshot)
    if blocker:
        return f"pouvoir à cibler : {blocker}"
    if not can_pay(card, pool):
        source = "lu à l'écran" if card.cost_is_live else "de card_sets"
        return f"coût {card.cost} ({source}) > mana {pool.mana}"
    return None


def etat_des_sorts(allow_spells: bool) -> str:
    """
    Ce que l'en-tête de `why` doit dire des sorts — et c'est le MODE qui
    répond, pas l'option de ligne de commande.

    L'en-tête lisait `SPELLS_ENABLED and allow_spells`, donc « exclus »
    sans `--spells` ; trois lignes plus bas, le même écran déclarait les
    mêmes sorts JOUABLE. Les deux ne pouvaient pas avoir raison, et c'est
    l'en-tête qui mentait : en mode par défaut `playable_cards`
    court-circuite sur `if not CARD_RESTRICTIONS:` et les sorts y passent
    SANS CONDITION — ni `allow_spells`, ni `SPELLS_ENABLED`. C'est écrit
    dans `CLAUDE.md` depuis le 04/11/2026 (« `--spells` NE COMMANDE RIEN
    en mode par défaut ») ; l'en-tête ne l'avait jamais appris.

    Corrigé le 10/11/2026, même famille que `_describe` la veille : deux
    endroits qui répondent à la même question finissent par diverger, et
    c'est toujours le diagnostic qui ment. D'où une fonction, pour que
    `rejection_reason` et l'en-tête ne puissent plus se contredire — un
    test les oblige désormais à s'accorder.
    """
    if not CARD_RESTRICTIONS:
        return "autorisés (mode par défaut : --spells ne commande rien)"
    if SPELLS_ENABLED and allow_spells:
        return "autorisés"
    return "exclus"


def cmd_why(allow_spells: bool, read_screen_costs: bool) -> None:
    """
    Passe en revue TOUTES nos cartes vues par l'API et dit, pour chacune,
    pourquoi elle n'est pas jouée.

    Contrairement à `plan`, qui ne regarde que la main, ce diagnostic part
    de tout ce que l'API rapporte. C'est la différence qui compte : si les
    cartes de la main sont classées dans la mauvaise zone, `plan` affiche
    « main vide » sans expliquer pourquoi, alors qu'ici la zone erronée
    apparaît noir sur blanc.
    """
    reader = GameStateReader()
    snapshot = reader.stable_snapshot()
    pool = read_mana_pool(window=snapshot.window)

    print(f"\nPhase        : {snapshot.phase.name}")
    print(f"Mana         : {pool}")
    print(f"Places banc  : {free_board_slots(snapshot)} / {MAX_BOARD_SIZE}")
    print(f"Sorts        : {etat_des_sorts(allow_spells)}")

    if read_screen_costs:
        count = read_costs(snapshot, zones=("hand",), only_unknown=False)
        print(f"Coûts lus à l'écran : {count}")
        for card, gap in cost_gaps(snapshot):
            print(f"    {card.name} : {card.base_cost} -> {card.cost} ({gap:+d})")

    ours = [c for c in snapshot.cards() if c.local]
    print(f"\n{len(ours)} carte(s) à nous vue(s) par l'API :\n")
    header = f"{'carte':<26} {'zone':<12} {'coût':>5} {'base':>5}  verdict"
    print(header)
    print("-" * (len(header) + 20))

    playable = 0
    for card in sorted(ours, key=lambda c: (c.zone, c.name)):
        why = rejection_reason(card, snapshot, pool, allow_spells)
        if why is None:
            playable += 1
        source = "écran" if card.cost_read is not None else "base"
        print(
            f"{card.name[:26]:<26} {card.zone:<12} "
            f"{card.cost:>5} {card.base_cost:>5}  "
            f"{'JOUABLE' if why is None else why}"
            + (f"  [{source}]" if card.cost_read is not None else "")
        )

    print(f"\n{playable} carte(s) jouable(s).")

    if not snapshot.hand:
        print(
            "\nAUCUNE carte classée en main. C'est la cause la plus probable :\n"
            "    python game_state.py inspect\n"
            "montre le ratio de chaque carte et la zone déduite. Si tes cartes\n"
            "de main tombent ailleurs, ajuste la première borne de ZONE_BANDS."
        )
    elif any(not c.known for c in snapshot.hand):
        print(
            "\nDes cartes de ta main sont absentes de card_sets, et elles resteront\n"
            "écartées : sans la base on ignore aussi leur TYPE, donc lire leur coût\n"
            "à l'écran ne suffit pas. La seule réponse est de mettre la base à jour :\n"
            "    python LoR-Bot/code/download_card_sets.py"
        )


def cmd_cost(calibrate: bool) -> None:
    import game_state

    if not calibrate:
        offsets = game_state.load_cost_offsets()
        if offsets:
            print(f"Gemme de mana calibrée : offsets {tuple(round(v, 4) for v in offsets)}")
        else:
            print("Gemme de mana NON calibrée.")
            print("    python actions.py cost --calibrate")
        return

    reader = GameStateReader()
    snapshot = reader.stable_snapshot()
    if not snapshot.hand:
        print("Aucune carte en main détectée : impossible de désigner la gemme.")
        print("Lance `python actions.py why` pour comprendre pourquoi.")
        return

    card = snapshot.hand[0]
    screen = lor_api.capture_screen_bgr()
    left, top, right, bottom = card.box

    print(f"Carte de référence : {card.name}  box {card.box}")
    print("Encadre sa GEMME DE MANA (le rond en haut de la carte), puis ENTRÉE.")
    selection = game_state.pick_box_tk(screen, title=f"Gemme de mana de {card.name}")
    if selection is None:
        print("Calibration annulée.")
        return

    x, y, w, h = selection
    ref_w, ref_h = right - left, bottom - top
    offsets = ((x - left) / ref_w, (y - top) / ref_h, w / ref_w, h / ref_h)
    save_calibration(COST_CALIBRATION_KEY, list(offsets))

    read_costs(snapshot, screen=screen, zones=("hand",), only_unknown=False)
    print(f"\nOffsets : {tuple(round(v, 4) for v in offsets)}")
    print("\nRelecture de ta main avec ces offsets :")
    for hand_card in snapshot.hand:
        read = hand_card.cost_read
        flag = "" if read == hand_card.base_cost or not hand_card.known else "   <-- écart"
        print(f"    {hand_card.name[:26]:<26} lu {read}   base {hand_card.base_cost}{flag}")
    print("\nSi les valeurs lues collent aux coûts réels, c'est bon.")


def cmd_plan(allow_spells: bool) -> None:
    """Décision complète, sans aucun événement souris."""
    reader = GameStateReader()
    snapshot = reader.stable_snapshot()
    pool = read_mana_pool(window=snapshot.window)

    # Avant de décrire quoi que ce soit : `plan` doit montrer les MÊMES
    # coûts que ceux sur lesquels `play` décidera, sinon il ne sert plus à
    # prédire ce que le bot va faire — mêmes cartes lues comprises.
    refresh_costs(snapshot, allow_spells=allow_spells)

    _describe(snapshot, pool, allow_spells)

    plan_attack_result = plan_attack(snapshot)
    print(f"\nAttaque : {plan_attack_result[2]}")
    print(f"\nAttaquants possibles ({len(attackers_available(snapshot))}) :")
    for card in attackers_available(snapshot):
        print(f"    {str(card):<44} {keywords.describe(card):<34} saisie {card.grab_point}")
    if snapshot.phase is not Phase.ATTACK_TURN:
        print(f"    (phase {snapshot.phase.name} : aucune attaque ne serait déclarée)")

    print("\n--- décision ---")
    played, _, log = play_hand(reader, snapshot, allow_spells=allow_spells, dry_run=True)
    if not played:
        print("Rien à jouer.")
    print("\nAucune action n'a été exécutée. `python actions.py play` pour jouer.")


def cmd_play(allow_spells: bool, finish_turn: bool) -> None:
    reader = GameStateReader()
    snapshot = reader.stable_snapshot()

    if not snapshot.phase.is_our_move:
        print(f"Phase {snapshot.phase.name} : ce n'est pas à nous de jouer.")
        return

    print("Contrôle de la souris dans 3 s — coin de l'écran pour interrompre.")
    time.sleep(3)

    played, snapshot, _ = play_hand(reader, snapshot, allow_spells=allow_spells)
    print(f"\n{len(played)} carte(s) posée(s) : " + (", ".join(c.name for c in played) or "—"))

    if finish_turn:
        end_turn(snapshot.window)
        print("Tour terminé.")


def _countdown(action: str) -> None:
    print(f"{action} dans 3 s — coin de l'écran pour interrompre.")
    time.sleep(3)


def cmd_attack(plan_only: bool) -> None:
    reader = GameStateReader()
    snapshot = reader.stable_snapshot()

    if plan_only:
        print(f"\nBanc adverse ({len(snapshot.enemy_board)}) :")
        for card in snapshot.enemy_board:
            print(f"    {str(card):<44} {keywords.describe(card)}")

        engaged, _, log = declare_attack(reader, snapshot, dry_run=True)
        print()
        for entry in log.entries:
            print(f"  {entry}")
        print(f"\n{len(engaged)} unité(s) seraient engagées. Rien n'a été exécuté.")
        return

    if snapshot.phase is not Phase.ATTACK_TURN:
        print(f"Phase {snapshot.phase.name} : pas de jeton d'attaque.")
        return

    _countdown("Attaque")
    engaged, _, _ = declare_attack(reader, snapshot)
    print(f"\n{len(engaged)} unité(s) engagée(s).")


def cmd_block(plan_only: bool, allow_chump: bool) -> None:
    reader = GameStateReader()
    snapshot = reader.stable_snapshot()

    if snapshot.phase is not Phase.BLOCKING:
        print(f"Phase {snapshot.phase.name} : l'adversaire n'attaque pas.")
        if not plan_only:
            return

    print(f"\nAttaquants ({len(snapshot.enemy_attack_row)}) :")
    for card in snapshot.enemy_attack_row:
        print(f"    {str(card):<44} {keywords.describe(card)}")
    print(f"\nBloqueurs disponibles ({len(snapshot.board)}) :")
    for card in snapshot.board:
        state = "peut bloquer" if card.can_block else "NE PEUT PAS bloquer"
        print(f"    {str(card):<44} {state:<20} {keywords.describe(card)}")

    if plan_only:
        pairs, leaking, reason = plan_blocks(snapshot, None, allow_chump)
        print(f"\nPlan : {reason}")
        for blocker, attacker in pairs:
            print(f"    {blocker.name} -> {attacker.name} "
                  f"[valeur {block_score(blocker, attacker)}]")
        print(f"    {leaking} dégâts non bloqués")
        print("\nRien n'a été exécuté.")
        return

    _countdown("Blocage")
    done, _, log = execute_blocks(reader, snapshot, allow_chump=allow_chump)
    print(f"\n{len(done)} blocage(s) effectué(s).")


def cmd_cancel(calibrate: bool) -> None:
    if calibrate:
        calibrate_cancel_point()
        return

    window = lor_api.get_window()
    ratio = cancel_point_ratio()
    point = window.rel(*ratio)
    state = "calibrée" if cancel_is_calibrated() else "NON CALIBRÉE (valeur de départ)"
    print(f"Zone d'annulation : {point}  ratio ({ratio[0]:.4f}, {ratio[1]:.4f})  — {state}")
    print("\nUn clic gauche y sera émis pour annuler une action en attente.")
    print("Vérifie qu'il n'y a rien de cliquable à cet endroit, sinon :")
    print("    python actions.py cancel --calibrate")


def cmd_mulligan(plan_only: bool, calibrate: bool, max_cost: int) -> None:
    if calibrate:
        calibrate_mulligan_button()
        return

    reader = GameStateReader()
    snapshot = reader.stable_snapshot()

    if snapshot.phase is not Phase.MULLIGAN:
        print(f"Phase {snapshot.phase.name} : on n'est pas à l'écran de mulligan.")
        if not plan_only:
            return

    cards = [c for c in snapshot.cards() if c.local]
    print(f"\nCartes proposées ({len(cards)}) :")
    for card in cards:
        verdict = "REJETÉE" if card.cost > max_cost else "gardée"
        print(f"    {str(card):<44} {verdict}")

    ratio = mulligan_confirm_ratio()
    print(f"\nBouton de validation : {snapshot.window.rel(*ratio)} "
          f"({'calibré' if mulligan_is_calibrated() else 'NON CALIBRÉ'})")

    if plan_only:
        do_mulligan(reader, snapshot, max_cost=max_cost, dry_run=True)
        print("\nRien n'a été exécuté.")
        return

    _countdown("Mulligan")
    do_mulligan(reader, snapshot, max_cost=max_cost)


def cmd_turn(plan_only: bool, allow_spells: bool, finish_turn: bool) -> None:
    reader = GameStateReader()
    if not plan_only:
        _countdown("Tour complet")

    log = play_turn(
        reader, allow_spells=allow_spells, finish_turn=finish_turn, dry_run=plan_only
    )

    print("\n--- déroulé ---")
    for entry in log.entries:
        print(f"  {entry}")
    if plan_only:
        print("\nRien n'a été exécuté.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Actions de combat (Legends of Runeterra).")
    parser.add_argument("--speed", type=float, default=None,
                        help="échelle des gestes souris (1 = d'origine, 2 = deux fois plus rapide)")
    sub = parser.add_subparsers(dest="command")

    # Options partagées par les commandes qui DÉCIDENT quoi poser. Un
    # parent commun plutôt qu'un drapeau global : `python actions.py plan
    # --base-costs` se lit dans le bon ordre, et la commande qui ne décide
    # rien (cost, cancel, mana) n'affiche pas une option sans effet.
    deciding = argparse.ArgumentParser(add_help=False)
    deciding.add_argument(
        "--base-costs", action="store_true",
        help="ignorer la gemme à l'écran et décider sur les coûts de card_sets",
    )
    deciding.add_argument(
        "--prudent", action="store_true",
        help="rétablir les restrictions de cartes (sorts refusés, coûts inconnus écartés…)",
    )

    plan = sub.add_parser("plan", parents=[deciding],
                          help="affiche la décision sans rien exécuter")
    plan.add_argument("--spells", action="store_true", help="inclure les sorts")

    play = sub.add_parser("play", parents=[deciding], help="pose réellement les cartes")
    play.add_argument("--spells", action="store_true", help="inclure les sorts")
    play.add_argument("--end-turn", action="store_true", help="terminer le tour après")

    attack = sub.add_parser("attack", help="engage les unités et confirme l'attaque")
    attack.add_argument("--plan", action="store_true", help="décrire sans exécuter")

    block = sub.add_parser("block", help="assigne les bloqueurs et confirme")
    block.add_argument("--plan", action="store_true", help="décrire sans exécuter")
    block.add_argument("--chump", action="store_true",
                       help="autoriser les blocages sacrificiels hors situation létale")

    turn = sub.add_parser("turn", parents=[deciding],
                          help="tour complet : poser, attaquer, terminer")
    turn.add_argument("--plan", action="store_true", help="décrire sans exécuter")
    turn.add_argument("--spells", action="store_true", help="inclure les sorts")
    turn.add_argument("--keep-turn", action="store_true", help="ne pas terminer le tour")

    why = sub.add_parser("why", parents=[deciding],
                         help="pourquoi telle carte n'est pas jouée")
    why.add_argument("--spells", action="store_true", help="considérer les sorts")
    why.add_argument("--read-costs", action="store_true",
                     help="lire aussi les coûts à l'écran, pour comparer")

    cost = sub.add_parser("cost", help="gemme de mana lue à l'écran")
    cost.add_argument("--calibrate", action="store_true",
                      help="encadrer la gemme sur une carte en main")

    cancel = sub.add_parser("cancel", help="zone vide utilisée pour annuler")
    cancel.add_argument("--calibrate", action="store_true",
                        help="désigner la zone vide à la souris")

    mull = sub.add_parser("mulligan", help="remplace les cartes trop chères et valide")
    mull.add_argument("--plan", action="store_true", help="décrire sans exécuter")
    mull.add_argument("--calibrate", action="store_true",
                      help="désigner le bouton de validation à la souris")
    mull.add_argument("--max-cost", type=int, default=MULLIGAN_MAX_COST,
                      help="au-dessus de ce coût, la carte est rejetée")

    sub.add_parser("mana", help="lit seulement le mana")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if getattr(args, "speed", None) is not None:
        set_gesture_speed(args.speed)

    # Le drapeau bascule le RÉGLAGE du module plutôt que d'être traîné de
    # fonction en fonction : `play_hand` est appelée depuis combat.py et
    # depuis les tests, et aucun de ces appelants n'a à connaître une
    # option de ligne de commande.
    global READ_SCREEN_COSTS, CARD_RESTRICTIONS
    if getattr(args, "base_costs", False):
        READ_SCREEN_COSTS = False
        LOGGER.info("Coûts à l'écran désactivés : décision sur les coûts de card_sets.")

    if getattr(args, "prudent", False):
        CARD_RESTRICTIONS = True
        LOGGER.info("Mode prudent : les restrictions de cartes sont rétablies.")

    if args.command == "play":
        cmd_play(args.spells, args.end_turn)
    elif args.command == "attack":
        cmd_attack(args.plan)
    elif args.command == "block":
        cmd_block(args.plan, args.chump)
    elif args.command == "turn":
        cmd_turn(args.plan, args.spells, not args.keep_turn)
    elif args.command == "why":
        cmd_why(args.spells, args.read_costs)
    elif args.command == "cost":
        cmd_cost(args.calibrate)
    elif args.command == "cancel":
        cmd_cancel(args.calibrate)
    elif args.command == "mulligan":
        cmd_mulligan(args.plan, args.calibrate, args.max_cost)
    elif args.command == "mana":
        print(read_mana_pool(debug=True))
    else:
        cmd_plan(getattr(args, "spells", False))


if __name__ == "__main__":
    main()
