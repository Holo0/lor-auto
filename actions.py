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
"""

from __future__ import annotations

import argparse
import logging
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional

import pyautogui

import lor_api
from lor_api import Window
from game_state import (
    MAX_BOARD_SIZE,
    BoardCard,
    GameSnapshot,
    GameStateReader,
    Phase,
    TURN_ORB_REGION,
    enrich_with_live_stats,
    zone_center_from_top,
)
from mana import ManaPool, can_pay, read_mana_pool, read_nexus_health

LOGGER = logging.getLogger(__name__)

# Le coin de l'écran interrompt tout : indispensable quand un script
# pilote la souris.
pyautogui.FAILSAFE = True

# Mouvement de souris « humain » : on réutilise celui déjà écrit pour la
# navigation plutôt que d'en avoir deux qui divergent.
try:
    from click_utils import human_move_mouse as _human_move_mouse
except Exception as exc:  # click_utils tire adventure_navigation
    LOGGER.debug("click_utils indisponible (%s) : mouvement pyautogui simple.", exc)
    _human_move_mouse = None


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

HOVER_BEFORE_GRAB = 0.55   # la carte s'agrandit au survol : la laisser finir
HOLD_DELAY = 0.12
DROP_SETTLE = 0.35
AFTER_PLAY_DELAY = 1.1     # animation de pose avant de relire l'API

MAX_PLAYS_PER_TURN = 8     # garde-fou anti-boucle

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

    def add(self, message: str) -> None:
        self.entries.append(message)
        LOGGER.info(message)


def move(x: float, y: float) -> None:
    if _human_move_mouse is not None:
        _human_move_mouse(int(x), int(y))
    else:
        pyautogui.moveTo(int(x), int(y), duration=random.uniform(0.25, 0.45))


def click(x: float, y: float) -> None:
    move(x, y)
    time.sleep(random.uniform(0.06, 0.14))
    pyautogui.click()
    time.sleep(random.uniform(0.15, 0.30))


def drag(source: tuple, destination: tuple) -> None:
    """
    Glisser-déposer, avec un survol préalable.

    Le survol n'est pas cosmétique : au passage de la souris, LoR agrandit
    la carte. Appuyer avant la fin de cette animation attrape la carte
    dans un état intermédiaire et le drag part de travers.
    """
    move(*source)
    time.sleep(HOVER_BEFORE_GRAB)
    pyautogui.mouseDown()
    time.sleep(HOLD_DELAY)
    move(*destination)
    time.sleep(DROP_SETTLE)
    pyautogui.mouseUp()
    time.sleep(DROP_SETTLE)


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


# ============================================================
# DÉCISION
# ============================================================

def summons_extra_body(card: BoardCard) -> bool:
    description = (card.description or "").lower()
    return any(marker in description for marker in SUMMON_MARKERS)


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
    """
    skip = skip or set()
    slots = free_board_slots(snapshot)
    candidates = []

    for card in snapshot.hand:
        if card.code in skip:
            continue
        if not card.known:
            continue
        if card.is_spell or card.is_ability:
            if not allow_spells:
                continue
        elif card.is_equipment:
            continue  # demande une cible : brique à part
        elif not (card.is_unit or card.is_landmark):
            continue
        else:
            needed = 2 if summons_extra_body(card) else 1
            if needed > slots:
                continue
        if not can_pay(card, pool):
            continue
        candidates.append(card)

    # Coût décroissant, puis corpulence : à coût égal, la plus grosse.
    return sorted(candidates, key=lambda c: (c.cost, c.attack + c.health), reverse=True)


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


def _zone_counts(snapshot: GameSnapshot, zone: str) -> dict:
    """Nombre d'exemplaires de chaque code de carte dans une zone."""
    counts = {}
    for card in snapshot.zones.get(zone, ()):
        counts[card.code] = counts.get(card.code, 0) + 1
    return counts


def _hand_counts(snapshot: GameSnapshot) -> dict:
    return _zone_counts(snapshot, "hand")


def play_card(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    card: BoardCard,
    dry_run: bool = False,
    attempts: int = 2,
) -> tuple:
    """
    Pose une carte et VÉRIFIE qu'elle a quitté la main.

    Renvoie (succès, instantané_le_plus_récent). En mode plan, décrit le
    geste et renvoie (True, snapshot) sans rien toucher.
    """
    source = card.grab_point
    target = drop_point(card, snapshot.window)

    if dry_run:
        LOGGER.info(
            "[plan] jouer %s : saisie %s -> dépôt %s", card, source, target
        )
        return True, snapshot

    before = _hand_counts(snapshot)
    latest = snapshot

    for attempt in range(1, attempts + 1):
        LOGGER.info("Pose de %s (tentative %d/%d)", card, attempt, attempts)
        drag(source, target)
        time.sleep(AFTER_PLAY_DELAY)

        latest = reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)
        after = _hand_counts(latest)
        if after.get(card.code, 0) < before.get(card.code, 0):
            LOGGER.info("%s posée.", card.name)
            return True, latest

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
        target = drop_point(refreshed, latest.window)

    return False, latest


def play_hand(
    reader: GameStateReader,
    snapshot: Optional[GameSnapshot] = None,
    allow_spells: bool = False,
    dry_run: bool = False,
    max_plays: int = MAX_PLAYS_PER_TURN,
) -> tuple:
    """
    Pose des cartes tant qu'il en reste de jouables.

    Renvoie (cartes_posées, dernier_instantané, journal).
    """
    log = ActionLog()
    snapshot = snapshot or reader.stable_snapshot()
    played: List[BoardCard] = []
    failed: set = set()

    if not snapshot.phase.is_our_move:
        log.add(f"Phase {snapshot.phase.name} : ce n'est pas à nous, rien à faire.")
        return played, snapshot, log

    for turn in range(max_plays):
        # Le mana est relu à CHAQUE itération : il diminue à chaque pose,
        # et se fier à la valeur du début ferait tenter une carte qu'on ne
        # peut plus payer.
        pool = read_mana_pool(window=snapshot.window)
        if not pool.readable:
            log.add("Mana illisible : on s'arrête plutôt que de jouer à l'aveugle.")
            break

        slots = free_board_slots(snapshot)
        options = playable_cards(snapshot, pool, allow_spells, skip=failed)
        log.add(
            f"[{turn + 1}] {pool} | {slots} place(s) | "
            f"main {len(snapshot.hand)} | jouables : "
            + (", ".join(f"{c.name}({c.cost})" for c in options) or "aucune")
        )

        if not options:
            break

        card = options[0]
        success, snapshot = play_card(reader, snapshot, card, dry_run=dry_run)
        if success:
            played.append(card)
        else:
            # On met la carte de côté au lieu de réessayer sans fin : si
            # elle refuse de se poser, la cause ne disparaîtra pas en
            # refaisant le même geste.
            failed.add(card.code)
            log.add(f"{card.name} mise de côté pour ce tour.")

        if dry_run:
            # Sans action réelle, l'état ne change pas : continuer
            # produirait la même décision à l'infini.
            log.add("[plan] simulation d'une seule pose (l'état ne change pas).")
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
    Unités du banc qui peuvent attaquer, la plus grosse en premier.

    `card.attack` reflète la stat LUE À L'ÉCRAN si `enrich_with_live_stats`
    a tourné sur cet instantané, la stat de base sinon. Les appelants de
    ce module enrichissent avant de décider — sans quoi une unité buffée
    de 0 à 3 serait écartée à tort, et une unité affaiblie à 0 engagée
    pour rien.
    """
    candidates = [
        card for card in snapshot.board
        if card.is_unit and card.can_attack and card.attack > 0
    ]
    return sorted(candidates, key=lambda c: (c.attack, c.health), reverse=True)


def move_to_attack_row(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    card: BoardCard,
    dry_run: bool = False,
) -> tuple:
    """Avance une unité dans la rangée d'attaque, et vérifie qu'elle y est."""
    source = card.grab_point
    target = (source[0], int(snapshot.window.y + PLAY_DROP_RATIO * snapshot.window.height))

    if dry_run:
        LOGGER.info("[plan] engager %s : %s -> %s", card, source, target)
        return True, snapshot

    before = _zone_counts(snapshot, "board")
    drag(source, target)
    time.sleep(AFTER_PLAY_DELAY)

    latest = reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)
    if _zone_counts(latest, "board").get(card.code, 0) < before.get(card.code, 0):
        LOGGER.info("%s engagée.", card.name)
        return True, latest

    LOGGER.warning("%s n'a pas quitté le banc.", card.name)
    return False, latest


def wait_for_combat_resolution(
    reader: GameStateReader, timeout: float = 30.0, poll: float = 0.8
) -> GameSnapshot:
    """
    Attend que la rangée d'attaque se vide, c'est-à-dire que le combat
    soit résolu. On n'attend PAS une durée fixe : la résolution dure de
    deux secondes à beaucoup plus selon les blocages et les effets.
    """
    deadline = time.time() + timeout
    snapshot = reader.snapshot()
    while time.time() < deadline:
        if not snapshot.attack_row and not snapshot.enemy_attack_row:
            return snapshot
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
    # un 3/1 réel change le résultat de l'échange.
    enrich_with_live_stats(snapshot)
    candidates = attackers_available(snapshot)
    if not candidates:
        log.add("Aucune unité en état d'attaquer.")
        return [], snapshot, log

    log.add("Attaquants : " + ", ".join(f"{c.name}({c.attack}/{c.health})" for c in candidates))

    engaged: List[BoardCard] = []
    for card in candidates:
        success, snapshot = move_to_attack_row(reader, snapshot, card, dry_run=dry_run)
        if success:
            engaged.append(card)
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

# NON VÉRIFIÉ EN JEU : je ne connais pas la position exacte du bouton de
# validation du mulligan. C'est pourquoi le mulligan automatique est
# DÉSACTIVÉ par défaut dans la boucle — un clic au mauvais endroit gâche
# la main de départ. Si tu l'actives et que la phase ne change pas, c'est
# ce ratio qu'il faut corriger ; les coordonnées cliquées sont
# journalisées exprès.
MULLIGAN_CONFIRM_RATIO = (0.50, 0.88)


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


def do_mulligan(
    reader: GameStateReader,
    snapshot: GameSnapshot,
    max_cost: int = MULLIGAN_MAX_COST,
    dry_run: bool = False,
) -> ActionLog:
    """Sélectionne les cartes trop chères et valide."""
    log = ActionLog()
    to_replace = mulligan_candidates(snapshot, max_cost)
    kept = [c for c in snapshot.cards() if c.local and c not in to_replace]

    log.add("Mulligan — gardées : " + (", ".join(c.name for c in kept) or "aucune"))
    log.add("Mulligan — rejetées : " + (", ".join(c.name for c in to_replace) or "aucune"))

    confirm = snapshot.window.rel(*MULLIGAN_CONFIRM_RATIO)
    if dry_run:
        for card in to_replace:
            log.add(f"[plan] clic sur {card.name} en {card.center}")
        log.add(f"[plan] validation en {confirm}")
        return log

    for card in to_replace:
        click(*card.center)
        time.sleep(0.4)

    log.add(f"Validation du mulligan en {confirm}.")
    click(*confirm)
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
    if attacker.has("Fearsome") and blocker.attack < FEARSOME_MIN_ATTACK:
        return False
    return True


def block_score(blocker: BoardCard, attacker: BoardCard) -> int:
    """Qualité d'un blocage : tuer sans mourir > survivre > échanger > mourir."""
    kills = blocker.attack >= attacker.health
    survives = attacker.attack < blocker.health
    if kills and survives:
        return BLOCK_KILL_AND_SURVIVE
    if survives:
        return BLOCK_SURVIVE
    if kills:
        return BLOCK_TRADE
    return BLOCK_CHUMP


def _assign(attackers, blockers, minimum_score):
    """
    Associe un bloqueur à chaque attaquant, du plus dangereux au moins
    dangereux. Un attaquant ne peut recevoir qu'un seul bloqueur.

    À qualité de blocage égale, on engage la PLUS PETITE unité : garder
    les grosses pour attaquer vaut mieux que les user en défense.
    """
    pairs, remaining = [], list(blockers)

    for attacker in sorted(attackers, key=lambda c: (c.attack, c.health), reverse=True):
        legal = [b for b in remaining if can_block_attacker(b, attacker)]
        if not legal:
            continue
        best = max(
            legal,
            key=lambda b: (block_score(b, attacker), -(b.attack + b.health)),
        )
        if block_score(best, attacker) < minimum_score:
            continue
        pairs.append((best, attacker))
        remaining.remove(best)

    return pairs, remaining


def plan_blocks(snapshot: GameSnapshot, nexus_health: Optional[int] = None,
                allow_chump: bool = False) -> tuple:
    """
    Décide qui bloque quoi. Fonction pure : aucune souris, aucune capture.

    Deux passes. La première n'accepte que des blocages qui rapportent
    quelque chose (on tue, ou on survit). On calcule alors les dégâts qui
    passeraient quand même, et si le nexus n'y survit pas, une seconde
    passe autorise les blocages sacrificiels avec les unités restantes.

    Perdre des unités est mauvais ; perdre la partie est pire. Mais se
    sacrifier sans nécessité l'est aussi, d'où la condition.

    Renvoie (paires, dégâts_non_bloqués, raison).
    """
    attackers = list(snapshot.enemy_attack_row)
    blockers = [c for c in snapshot.board if c.is_unit and c.can_block]

    if not attackers:
        return [], 0, "aucun attaquant"
    if not blockers:
        return [], sum(c.attack for c in attackers), "aucun bloqueur disponible"

    pairs, remaining = _assign(attackers, blockers, BLOCK_TRADE)
    blocked = {id(attacker) for _, attacker in pairs}
    leaking = sum(c.attack for c in attackers if id(c) not in blocked)

    if leaking == 0:
        return pairs, 0, "tout est bloqué"

    lethal = nexus_health is not None and leaking >= nexus_health
    if not (lethal or allow_chump):
        if nexus_health is None:
            reason = f"{leaking} dégâts encaissés (PV du nexus illisibles)"
        else:
            reason = f"{leaking} dégâts encaissés, nexus à {nexus_health} PV"
        return pairs, leaking, reason

    # Blocage sacrificiel avec ce qu'il reste.
    unblocked = [c for c in attackers if id(c) not in blocked]
    extra, _ = _assign(unblocked, remaining, BLOCK_CHUMP)
    pairs += extra

    blocked |= {id(attacker) for _, attacker in extra}
    leaking = sum(c.attack for c in attackers if id(c) not in blocked)
    reason = (
        f"létal évité : {len(extra)} blocage(s) sacrificiel(s)"
        if lethal else f"{len(extra)} blocage(s) sacrificiel(s) (option chump)"
    )
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

    # Le blocage est la décision la plus sensible aux stats réelles : un
    # attaquant déjà blessé se tue avec une unité qu'on croyait trop
    # faible, et un bloqueur affaibli meurt à un échange qu'on croyait
    # gagnant.
    enrich_with_live_stats(snapshot)

    health = None if dry_run else read_nexus_health(window=snapshot.window)
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
    for blocker, attacker in pairs:
        before = _zone_counts(snapshot, "board")
        drag(blocker.grab_point, attacker.center)
        time.sleep(AFTER_PLAY_DELAY)
        snapshot = reader.stable_snapshot(confirmations=2, poll=0.4, timeout=6.0)

        if _zone_counts(snapshot, "board").get(blocker.code, 0) < before.get(blocker.code, 0):
            done.append((blocker, attacker))
        else:
            log.add(f"{blocker.name} n'a pas pris son poste, on passe au suivant.")

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
        reader, snapshot, allow_spells=allow_spells, dry_run=dry_run
    )
    log.entries.extend(play_log.entries)
    log.add(f"{len(played)} carte(s) posée(s).")

    if snapshot.phase is Phase.ATTACK_TURN:
        engaged, snapshot, attack_log = declare_attack(reader, snapshot, dry_run=dry_run)
        log.entries.extend(attack_log.entries)
        log.add(f"{len(engaged)} unité(s) engagée(s).")
    else:
        log.add(f"Phase {snapshot.phase.name} : pas d'attaque ce tour.")

    if finish_turn:
        end_turn(snapshot.window, dry_run=dry_run)
        log.add("Fin de tour.")

    return log


# ============================================================
# CLI
# ============================================================

def _describe(snapshot: GameSnapshot, pool: ManaPool) -> None:
    print(f"\nPhase        : {snapshot.phase.name}")
    print(f"Mana         : {pool}")
    print(f"Places banc  : {free_board_slots(snapshot)} / {MAX_BOARD_SIZE}")
    print(f"\nMain ({len(snapshot.hand)}) :")
    if not snapshot.hand:
        print("    (vide)")
    for card in snapshot.hand:
        reasons = []
        if not card.known:
            reasons.append("absente de card_sets")
        if card.is_spell or card.is_ability:
            reasons.append("sort")
        if card.is_equipment:
            reasons.append("équipement")
        if not can_pay(card, pool):
            reasons.append("trop chère")
        verdict = "JOUABLE" if not reasons else "non — " + ", ".join(reasons)
        print(f"    {str(card):<44} saisie {card.grab_point}  {verdict}")

    print(f"\nBanc ({len(snapshot.board)}) :")
    for card in snapshot.board:
        print(f"    {card}")


def cmd_plan(allow_spells: bool) -> None:
    """Décision complète, sans aucun événement souris."""
    reader = GameStateReader()
    snapshot = reader.stable_snapshot()
    pool = read_mana_pool(window=snapshot.window)

    _describe(snapshot, pool)

    print(f"\nAttaquants possibles ({len(attackers_available(snapshot))}) :")
    for card in attackers_available(snapshot):
        print(f"    {str(card):<44} saisie {card.grab_point}")
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
        engaged, _, log = declare_attack(reader, snapshot, dry_run=True)
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
        traits = [k for k in ("Elusive", "Fearsome", "Overwhelm") if card.has(k)]
        print(f"    {str(card):<44} {' '.join(traits)}")
    print(f"\nBloqueurs disponibles ({len(snapshot.board)}) :")
    for card in snapshot.board:
        print(f"    {str(card):<44} {'peut bloquer' if card.can_block else 'NE PEUT PAS bloquer'}")

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
    sub = parser.add_subparsers(dest="command")

    plan = sub.add_parser("plan", help="affiche la décision sans rien exécuter")
    plan.add_argument("--spells", action="store_true", help="inclure les sorts")

    play = sub.add_parser("play", help="pose réellement les cartes")
    play.add_argument("--spells", action="store_true", help="inclure les sorts")
    play.add_argument("--end-turn", action="store_true", help="terminer le tour après")

    attack = sub.add_parser("attack", help="engage les unités et confirme l'attaque")
    attack.add_argument("--plan", action="store_true", help="décrire sans exécuter")

    block = sub.add_parser("block", help="assigne les bloqueurs et confirme")
    block.add_argument("--plan", action="store_true", help="décrire sans exécuter")
    block.add_argument("--chump", action="store_true",
                       help="autoriser les blocages sacrificiels hors situation létale")

    turn = sub.add_parser("turn", help="tour complet : poser, attaquer, terminer")
    turn.add_argument("--plan", action="store_true", help="décrire sans exécuter")
    turn.add_argument("--spells", action="store_true", help="inclure les sorts")
    turn.add_argument("--keep-turn", action="store_true", help="ne pas terminer le tour")

    sub.add_parser("mana", help="lit seulement le mana")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.command == "play":
        cmd_play(args.spells, args.end_turn)
    elif args.command == "attack":
        cmd_attack(args.plan)
    elif args.command == "block":
        cmd_block(args.plan, args.chump)
    elif args.command == "turn":
        cmd_turn(args.plan, args.spells, not args.keep_turn)
    elif args.command == "mana":
        print(read_mana_pool(debug=True))
    else:
        cmd_plan(getattr(args, "spells", False))


if __name__ == "__main__":
    main()
