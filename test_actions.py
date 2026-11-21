#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_actions.py

Tests de la couche de décision et de pose, SANS souris, SANS OCR et SANS
le jeu. Le mana est injecté à la main, les instantanés sont fabriqués, et
le glisser-déposer est remplacé par un enregistreur.

Ça permet de vérifier les cas qui coûtent cher à reproduire en jeu : une
pose qui échoue, un banc plein, une carte inconnue, la règle du mana de
sort.

    python test_actions.py
"""

from __future__ import annotations

import json
import sys
import time
import types
from dataclasses import replace
from pathlib import Path

# --- bouchons pour tourner sans écran -----------------------------------
try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.size = lambda: (1920, 1080)
    stub.screenshot = lambda *a, **k: None
    stub.moveTo = lambda *a, **k: None
    stub.click = lambda *a, **k: None
    stub.mouseDown = lambda *a, **k: None
    stub.mouseUp = lambda *a, **k: None
    sys.modules["pyautogui"] = stub

# --- le temps aussi est simulé ------------------------------------------
# Sinon les `sleep` d'animation de actions.py s'exécutent pour de vrai :
# une trentaine de secondes d'attente pour rien (cf. test_clock.py).
from test_clock import install_virtual_clock

install_virtual_clock()

import actions
import game_state

# CES TESTS DÉCRIVENT LE MODE PRUDENT, QUI N'EST PLUS CELUI PAR DÉFAUT.
# `actions.CARD_RESTRICTIONS` vaut False en jeu : le bot tente désormais
# toute carte payable. Les refus vérifiés ci-dessous — sort non compris,
# carte absente de card_sets, pouvoir « Play: » sans cible — restent la
# spécification de `--prudent`, donc on l'active ici plutôt que de les
# supprimer : le jour où une partie se bloque, c'est vers ce mode qu'on
# revient, et il faut qu'il soit encore décrit quelque part.
#
# Le mode par défaut, lui, a ses propres tests : `test_restrictions_levees`.
actions.CARD_RESTRICTIONS = True

# L'enrichissement OCR est neutralisé : ces tests portent sur la DÉCISION,
# et les stats voulues sont déjà injectées via la base de cartes simulée.
actions.enrich_with_live_stats = lambda snapshot, *a, **k: snapshot
# Idem pour la gemme de mana. Les tests qui portent SUR la lecture des
# coûts remplacent ce bouchon par le leur (cf. `costs_read_as`).
actions.enrich_with_live_costs = lambda snapshot, *a, **k: snapshot

# UN GUET QUI PHOTOGRAPHIE L'ÉCRAN N'A RIEN À FAIRE DANS UNE SUITE HORS
# LIGNE. `journaliser_pile_bloquee` capture le jeu quand un sort reste
# sur la pile ; branché tel quel, il photographierait l'écran d'Ewan à
# chaque exécution — c'est la sixième fois que ce chemin se présente
# (park_mouse, choisir_champion, play_reward, revenir_en_haut,
# save_stuck_screen). On GARDE les appels : un test vérifie qu'elle est
# demandée au bon moment.
#
# LA LISTE EST PORTÉE PAR `actions`, PAS PAR CE MODULE : une suite
# lancée en script est `__main__`, et le moindre `from test_actions
# import …` ailleurs en charge une SECONDE copie qui rejoue ce bouchon.
# Les appels partiraient alors dans la liste de la copie, et le test
# verrait la sienne vide — c'est exactement ce qui est arrivé le
# 09/11/2026.
PILES_BLOQUEES = getattr(actions, "_piles_bloquees_test", None)
if PILES_BLOQUEES is None:
    PILES_BLOQUEES = actions._piles_bloquees_test = []
actions.journaliser_pile_bloquee = (
    lambda snapshot, card: PILES_BLOQUEES.append((snapshot, card)) or ""
)

# ET LA CAPTURE A CHANGÉ DE PLACE LE 11/11/2026 : elle est désormais
# prise EN TÊTE de `geste_pour_une_cible_reclamee`, avant le clic droit
# qui efface le blocage. Boucher `journaliser_pile_bloquee` seul NE
# PROTÈGE DONC PLUS RIEN — le chemin qui touche l'écran est
# `capturer_pour_diagnostic`, et c'est lui la couture. Un bouchon par
# COUTURE, pas un par appelant : `respond_to_stack` et
# `let_stack_resolve` y passent tous les deux.
#
# La liste est portée par `actions` pour la même raison que la
# précédente (une suite lancée en script est `__main__`).
CAPTURES_DIAGNOSTIC = getattr(actions, "_captures_diagnostic_test", None)
if CAPTURES_DIAGNOSTIC is None:
    CAPTURES_DIAGNOSTIC = actions._captures_diagnostic_test = []
actions.capturer_pour_diagnostic = (
    lambda: CAPTURES_DIAGNOSTIC.append(time.time()) or "ECRAN-BOUCHON"
)
from actions import (
    choose_card_to_play,
    free_board_slots,
    play_card,
    play_hand,
    playable_cards,
)
import spells
from game_state import Phase
from mana import ManaPool, can_pay
from test_game_state import (
    CALIBRATION_SANDBOX,
    CARD_DB,
    WINDOW,
    install_fakes,
    make_screen,
    nexus_rects,
    rect_at_ratio,
    reader as state_reader,
)

# `actions.CALIBRATION_FILE` est figé à l'import, donc AVANT que
# test_game_state ne redirige la racine du projet. On le réaligne ici :
# sinon une calibration réelle sur la machine ferait sauver et lire les
# tests dans le vrai fichier.
actions.CALIBRATION_FILE = CALIBRATION_SANDBOX / "calibration.json"

# Les captures et trames sur lesquelles des tests s'appuient. Elles ne
# doivent pas être effacées avec `screenshots/` (cf. CLAUDE.md).
CAPTURES_REFERENCE = Path(__file__).resolve().parent / "captures_reference"

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ============================================================
# OUTILLAGE
# ============================================================

EXTRA_CARDS = {
    "UNIT_BIG": {
        "name": "Colosse", "cost": 6, "attack": 8, "health": 8,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "UNIT_TWIN": {
        "name": "Jumeaux", "cost": 3, "attack": 2, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Invoque un allié supplémentaire.",
    },
    "GEAR_A": {
        "name": "Lame Runique", "cost": 1, "attack": 0, "health": 0,
        "type": "Equipment", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    # Deux cartes RÉELLES, celles vues en jeu le 20/08/2026.
    # Black Spear (01SI034) : le « an ally » de la condition en faisait un
    # sort ciblé sur NOTRE camp.
    "BLACK_SPEAR": {
        "name": "Lance noire", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "If an ally died this round, deal 4 to a unit.",
    },
    # Crumble (03SI008) : deux clics, un allié PUIS une unité.
    "CRUMBLE": {
        "name": "Éboulement", "cost": 4, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "descriptionRaw": "Kill an ally to kill a unit or destroy a landmark.",
    },
    # Lame féroce (06NX034), vue en jeu le 22/08/2026 : deux clics AUSSI,
    # un allié équipé PUIS un ennemi. L'adjectif « Equipped » masquait le
    # marqueur allié, il n'en restait qu'un — l'ennemi — et le bot
    # cliquait directement dessus.
    "FURIOUS_WIELDER": {
        "name": "Lame féroce", "cost": 4, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "An Equipped ally strikes an enemy.",
    },
    # UN CHAMPION, POUR LES SORTS QUI NE VISENT QUE LES SUIVANTS
    # (10/11/2026). « Charm an enemy FOLLOWER » (Beckoning Gaze) : la
    # base de test n'avait aucune carte à `supertype = "Champion"` sur le
    # plateau, donc aucun moyen de montrer la différence. Il est plus
    # GROS que les suivants des mêmes tests, exprès : c'est la cible que
    # le comportement naïf choisit, et celle que le jeu refuse.
    "CHAMPI": {
        "name": "Championne", "cost": 5, "attack": 7, "health": 7,
        "type": "Unit", "supertype": "Champion", "collectible": True,
        "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
}
FULL_DB = {**CARD_DB, **EXTRA_CARDS}


def snapshot_with(hand_codes=(), board_codes=(), attack_codes=(), token="nous"):
    """
    Fabrique un instantané avec la main et le banc demandés.

    `token` vaut "nous", "adversaire" ou None : certaines décisions de
    pose dépendent du jeton d'attaque (cf. `playable_cards`).
    """
    rects, card_id = list(nexus_rects()), 100

    for index, code in enumerate(hand_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.029, code=code, card_id=card_id,
                                   height=330, x=500 + 140 * index))
    for index, code in enumerate(board_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id,
                                   x=500 + 130 * index))
    for index, code in enumerate(attack_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.320, code=code, card_id=card_id,
                                   x=500 + 130 * index))

    install_fakes(rects, screen=make_screen(orb_active=True, token=token))
    return state_reader().snapshot()


class FakeReader:
    """Renvoie une suite d'instantanés préparés, sans toucher au jeu."""

    def __init__(self, sequence, resolved=None):
        self.sequence = list(sequence)
        self.resolved = resolved
        self.calls = 0

    def stable_snapshot(self, **_):
        # Le dernier état est REPÉTÉ plutôt que d'épuiser la liste : c'est
        # ce que fait le jeu quand rien ne bouge, et c'est justement le cas
        # que les attentes pilotées par l'état doivent gérer.
        self.calls += 1
        if len(self.sequence) > 1:
            return self.sequence.pop(0)
        if self.sequence:
            return self.sequence[0]
        raise AssertionError("stable_snapshot appelé sans état préparé")

    def snapshot(self):
        """Utilisé par l'attente de résolution du combat."""
        if self.resolved is not None:
            return self.resolved
        return self.stable_snapshot()


class DragRecorder:
    """Remplace le glisser-déposer et note les gestes demandés."""

    def __init__(self):
        self.drags = []

    def __call__(self, source, destination):
        self.drags.append((source, destination))


def with_db(db):
    """Recharge la base de cartes utilisée par les instantanés."""
    import test_game_state
    test_game_state.CARD_DB.clear()
    test_game_state.CARD_DB.update(db)


TRAMPLE_CARD = {
    "TRAMPLE": {
        "name": "Piétineur", "cost": 5, "attack": 6, "health": 6,
        "type": "Unit", "keywords": ["Overwhelm"], "keywordRefs": ["Overwhelm"],
        "descriptionRaw": "",
    },
}


# Une unité par mot-clé de combat, taillée pour que le mot-clé CHANGE la
# décision et pas seulement le calcul. Voir keywords.py pour les règles.
KEYWORD_CARDS = {
    "QUICK": {
        "name": "Lame Rapide", "cost": 3, "attack": 3, "health": 3,
        "type": "Unit", "keywords": ["Quick Strike"], "keywordRefs": ["QuickStrike"],
        "descriptionRaw": "",
    },
    "BARRIER": {
        "name": "Égide", "cost": 3, "attack": 2, "health": 2,
        "type": "Unit", "keywords": ["Barrier"], "keywordRefs": ["Barrier"],
        "descriptionRaw": "",
    },
    "TOUGHY": {
        "name": "Coriace", "cost": 2, "attack": 1, "health": 3,
        "type": "Unit", "keywords": ["Tough"], "keywordRefs": ["Tough"],
        "descriptionRaw": "",
    },
    "FORMIDABLE": {
        "name": "Titan", "cost": 6, "attack": 0, "health": 7,
        "type": "Unit", "keywords": ["Formidable"], "keywordRefs": ["Formidable"],
        "descriptionRaw": "",
    },
    "IMPACT": {
        "name": "Bélier", "cost": 3, "attack": 2, "health": 2,
        "type": "Unit", "keywords": ["Impact"], "keywordRefs": ["Impact"],
        "descriptionRaw": "",
    },
    "EPHEMERAL": {
        "name": "Spectre Éphémère", "cost": 3, "attack": 4, "health": 4,
        "type": "Unit", "keywords": ["Ephemeral"], "keywordRefs": ["Ephemeral"],
        "descriptionRaw": "",
    },
    "CHALLENGER": {
        "name": "Provocateur", "cost": 6, "attack": 6, "health": 6,
        "type": "Unit", "keywords": ["Challenger"], "keywordRefs": ["Challenger"],
        "descriptionRaw": "",
    },
    "VULNERABLE": {
        "name": "Proie", "cost": 2, "attack": 2, "health": 3,
        "type": "Unit", "keywords": ["Vulnerable"], "keywordRefs": ["Vulnerable"],
        "descriptionRaw": "",
    },
    "DEATHLESS": {
        "name": "Revenant", "cost": 3, "attack": 4, "health": 4,
        "type": "Unit", "keywords": ["Deathless"], "keywordRefs": ["Deathless"],
        "descriptionRaw": "",
    },
    "VANILLA33": {
        "name": "Milicien", "cost": 3, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "VANILLA44": {
        "name": "Soldat", "cost": 4, "attack": 4, "health": 4,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "STRIKER54": {
        "name": "Frappeur", "cost": 5, "attack": 5, "health": 4,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
}


def board_versus(ours, theirs, enemy_attackers=()):
    """Notre banc contre le leur, avec des attaquants adverses optionnels."""
    with_db({**ALL_CARDS, **TRAMPLE_CARD, **KEYWORD_CARDS})
    rects, card_id = list(nexus_rects()), 300
    for index, code in enumerate(ours):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=400 + 130 * index))
    for index, code in enumerate(theirs):
        card_id += 1
        rects.append(rect_at_ratio(0.800, code=code, card_id=card_id,
                                   local=False, x=400 + 130 * index))
    for index, code in enumerate(enemy_attackers):
        card_id += 1
        rects.append(rect_at_ratio(0.650, code=code, card_id=card_id,
                                   local=False, x=400 + 130 * index))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


# ============================================================
# TESTS
# ============================================================

def test_mana_rule():
    print("\nRègle du mana de sort")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "SPELL_A"])
    unit = next(c for c in snap.hand if c.code == "UNIT_A")     # coût 3
    spell = next(c for c in snap.hand if c.code == "SPELL_A")   # coût 1

    # 2 mana + 3 mana de sort = 5 au total, mais une unité à 3 n'est PAS
    # jouable : le mana de sort ne paie que les sorts.
    pool = ManaPool(mana=2, spell_mana=3)
    check("unité non payable avec du mana de sort", can_pay(unit, pool) is False)
    check("sort payable avec du mana de sort", can_pay(spell, pool) is True)

    check("unité payable avec assez de mana de tour", can_pay(unit, ManaPool(mana=3, spell_mana=0)))
    check("mana illisible -> rien n'est payable",
          can_pay(unit, ManaPool(mana=None, spell_mana=3)) is False)


def test_choice_order_and_filters():
    print("\nChoix de la carte")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "UNIT_B", "UNIT_BIG", "SPELL_A", "GEAR_A"])
    pool = ManaPool(mana=10, spell_mana=3)

    options = playable_cards(snap, pool)
    names = [c.name for c in options]
    check("la plus chère d'abord", names[0] == "Colosse", names)
    check("sorts exclus par défaut", "Éclair" not in names, names)
    check("équipements exclus", "Lame Runique" not in names, names)
    check("unités conservées", {"Garde de Fer", "Ombre Fuyante"} <= set(names), names)

    # Éclair vise un ennemi ; sans ennemi en jeu il reste écarté, faute de
    # cible — c'est le cas de ce plateau de test.
    with_spells = [c.name for c in playable_cards(snap, pool, allow_spells=True)]
    check("sort sans cible disponible écarté", "Éclair" not in with_spells, with_spells)

    # Mana serré : seules les cartes payables restent.
    tight = [c.name for c in playable_cards(snap, ManaPool(mana=2, spell_mana=0))]
    check("filtre par le mana disponible", tight == ["Ombre Fuyante"], tight)

    check("aucune option -> None",
          choose_card_to_play(snap, ManaPool(mana=0, spell_mana=0)) is None)


def test_unknown_card_is_not_played():
    print("\nCarte absente de card_sets")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "TOKEN_INCONNU"])
    options = playable_cards(snap, ManaPool(mana=10, spell_mana=0))
    codes = [c.code for c in options]

    # Elle est bien VUE (elle compte dans le plateau), mais son coût est
    # inconnu : la jouer serait un pari sur une donnée absente.
    check("carte inconnue visible en main", len(snap.hand) == 2, snap.hand)
    check("carte inconnue jamais choisie", "TOKEN_INCONNU" not in codes, codes)


HAND_POWER_CARDS = {
    "UPDRAFT_UNIT": {
        "name": "Gardien des traditions", "cost": 2, "attack": 3, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Updraft 1 to draw a card of the same type "
                          "(unit, spell, landmark or equipment).\r\n",
    },
    "UPDRAFT2_UNIT": {
        "name": "Janna", "cost": 4, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Updraft 2 to draw 2 at the next Round Start.\r\n",
    },
    "MANIFEST_UNIT": {
        "name": "Écuyer yordle", "cost": 2, "attack": 2, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Discard 1 to Manifest a Mecha Yordle.\r\n",
    },
    # Témoin : « in hand » sans aucun choix à faire. Elle DOIT rester
    # jouable, sinon le garde-fou mordrait sur 56 effets automatiques.
    "PORO_UNIT": {
        "name": "Ami des poros", "cost": 2, "attack": 2, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Create a Poro in hand.\r\n",
    },
    # ELORA (98PZ007), observée en jeu le 20/08/2026. Son « Play: » désigne
    # un sort DE NOTRE MAIN — et ce sort NE PART PAS : on en a deux après.
    "ELORA": {
        "name": "Elora", "cost": 3, "attack": 2, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Create an exact copy of a spell in hand.\r\n",
    },
    "SWORD": {
        "name": "Épée rouillée", "cost": 1, "attack": 0, "health": 0,
        "type": "Equipment", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "The equipped ally gets +2|+0.\r\n",
    },
    "SPELL_REFUSED": {
        "name": "Choix cornélien", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "descriptionRaw": "Choose one: deal 2 to an enemy, or heal 2.",
    },
}

# LES AILES ET LA VAGUE (04SI004) ET SES DEUX VERSIONS, telles que
# card_sets les décrit — c'est la carte sur laquelle le bot s'est figé le
# 22/08/2026. Codes et textes réels, seuls les noms restent en anglais
# puisque c'est la base anglaise que le bot lit.
CHOICE_CARDS = {
    "WINGS": {
        "name": "The Wings and The Wave", "cost": 1, "attack": 0, "health": 1,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Play me as First Wave or Last Wind.",
    },
    "FIRST_WAVE": {
        "name": "First Wave", "cost": 1, "attack": 0, "health": 1,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "When I'm summoned, summon a Prey.",
    },
    # Deux fois plus grosse, mais elle se paie d'un allié — et ce prix
    # ouvre une interface de plus après le choix.
    "LAST_WIND": {
        "name": "Last Wind", "cost": 1, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "To play me, kill an ally.",
    },
}

# CHOIX CAPITAL (Momentous Choice, 06IO034) ET SES DEUX VARIANTES, vues en
# jeu le 22/08/2026. Les trois portent LE MÊME NOM — c'est par là qu'on
# retrouve les versions à l'écran, le texte ne les nomme pas.
VARIANT_CARDS = {
    "MOMENTOUS": {
        "name": "Choix capital", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Give an ally +2|+0 or +0|+2 this round.",
    },
    "MOMENTOUS_FORCE": {
        "name": "Choix capital", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Give an ally +2|+0 this round.",
    },
    "MOMENTOUS_VIE": {
        "name": "Choix capital", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Give an ally +0|+2 this round.",
    },
    # IULA (05MT013), signalée par Ewan : même fenêtre, mais le choix
    # porte sur un MOT-CLÉ et non sur des statistiques. Les deux jetons
    # portent son nom, comme toujours dans cette famille.
    "IULA": {
        "name": "Iula", "cost": 3, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Grant an ally Spellshield or Overwhelm. "
                          "If you don't, grant it to me.",
    },
    "IULA_OVERWHELM": {
        "name": "Iula", "cost": 3, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Grant an ally Overwhelm. "
                          "If you don't, grant it to me.",
    },
    "IULA_SPELLSHIELD": {
        "name": "Iula", "cost": 3, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Grant an ally Spellshield. "
                          "If you don't, grant it to me.",
    },
    # Bouncing Bomb (05BC021) : les deux versions ne demandent PAS le même
    # clic, et c'est ça qui les départage.
    "BOMB": {
        "name": "Bombe rebondissante", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 2 to a unit or deal 1 to two enemies.",
    },
    "BOMB_UNITE": {
        "name": "Bombe rebondissante", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 2 to a unit.",
    },
    "BOMB_DEUX": {
        "name": "Bombe rebondissante", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 1 to two enemies.",
    },
}


def hand_at(cards, x0=500, step=140, ratio=0.029):
    """
    Main fabriquée avec des `CardID` CHOISIS.

    `snapshot_with` numérote les cartes d'après leur position, ce qui
    convient partout ailleurs — mais pas ici : suivre une carte d'un état
    au suivant demande justement que son identité ne dépende PAS de sa
    place, puisque c'est la place qui change.
    """
    rects = list(nexus_rects())
    for index, (code, card_id) in enumerate(cards):
        rects.append(rect_at_ratio(ratio, code=code, card_id=card_id,
                                   height=330, x=x0 + step * index))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


def test_unit_with_a_hand_power_is_played_and_designates():
    """
    Une unité dont le « Play: » désigne une carte EN MAIN est jouée, et le
    nombre de cartes à cliquer remonte jusqu'à `play_card`.

    Cas observé en jeu sur « Freljordian Lorekeeper » (98FR019) : le bot
    la posait sans rien désigner, et la partie restait figée sur ce choix.
    """
    print("\nPouvoir « Play: » qui désigne en main")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    snap = snapshot_with(hand_codes=["UPDRAFT_UNIT", "PORO_UNIT", "UNIT_A"])
    codes = [c.code for c in playable_cards(snap, ManaPool(mana=10, spell_mana=0))]

    check("Updraft jouable (2 cartes restent en main)", "UPDRAFT_UNIT" in codes, codes)
    check("effet automatique conservé", "PORO_UNIT" in codes, codes)

    by_code = {c.code: c for c in snap.hand}
    plan, point, description = actions.unit_play_plan(by_code["UPDRAFT_UNIT"], snap)
    check("plan renvoyé", plan is not None)
    check("1 carte à désigner", plan is not None and plan.picks == 1, plan)
    check("aucun point de plateau", point is None, point)
    check("rien ne bloque", actions.unit_play_blocker(by_code["UPDRAFT_UNIT"], snap) is None)

    plan, _, _ = actions.unit_play_plan(by_code["PORO_UNIT"], snap)
    check("aucun plan pour l'effet automatique", plan is None, plan)


def test_hand_power_needs_enough_cards():
    """
    Sans assez de cartes à donner, l'unité reste en main.

    « Updraft 2 » avec une seule autre carte en main ouvrirait une
    interface qu'on ne pourrait pas satisfaire : la partie se figerait
    exactement comme avant. Le refus vaut mieux que le blocage.
    """
    print("\nMain trop courte pour le pouvoir")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    snap = snapshot_with(hand_codes=["UPDRAFT2_UNIT", "UNIT_A"])
    pool = ManaPool(mana=10, spell_mana=0)
    codes = [c.code for c in playable_cards(snap, pool)]
    check("écartée : 2 à désigner, 1 disponible", "UPDRAFT2_UNIT" not in codes, codes)

    card = {c.code: c for c in snap.hand}["UPDRAFT2_UNIT"]
    reason = actions.rejection_reason(card, snap, pool, allow_spells=False)
    check("raison chiffrée", reason is not None and "2 carte(s)" in reason, reason)

    # Une carte de plus en main, et elle redevient jouable.
    snap = snapshot_with(hand_codes=["UPDRAFT2_UNIT", "UNIT_A", "UNIT_B"])
    codes = [c.code for c in playable_cards(snap, pool)]
    check("jouable dès qu'il y a de quoi payer", "UPDRAFT2_UNIT" in codes, codes)

    # « Discard 1 to Manifest » : la désignation en main se pilote, et la
    # fenêtre de Manifest aussi depuis le 02/09/2026. Avec de quoi payer,
    # l'unité est jouable ; sans rien à défausser, non.
    snap = snapshot_with(hand_codes=["MANIFEST_UNIT", "UNIT_A", "UNIT_B"])
    codes = [c.code for c in playable_cards(snap, pool)]
    check("Discard 1 to Manifest : jouable avec de quoi défausser",
          "MANIFEST_UNIT" in codes, codes)
    snap = snapshot_with(hand_codes=["MANIFEST_UNIT"])
    codes = [c.code for c in playable_cards(snap, pool)]
    check("   mais pas la main vide", "MANIFEST_UNIT" not in codes, codes)


def test_hand_sacrifice_order():
    """
    Quelle carte est donnée en premier : celle que le bot ne jouera jamais.

    Un sort qu'il refuse de lancer et une carte absente de card_sets sont
    des fardeaux POUR LUI, indépendamment de leur valeur pour un joueur.
    Vient ensuite la plus chère : c'est celle qui dormirait le plus
    longtemps en main.
    """
    print("\nChoix de la carte sacrifiée")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    snap = snapshot_with(hand_codes=["UNIT_A", "UNIT_BIG", "SPELL_REFUSED", "TOKEN_INCONNU"])
    order = [c.code for c in actions.choose_hand_sacrifice(snap, 4)]

    check("le fardeau part en premier",
          set(order[:2]) == {"SPELL_REFUSED", "TOKEN_INCONNU"}, order)
    check("puis la plus chère des jouables", order[2] == "UNIT_BIG", order)
    check("la moins chère est gardée pour la fin", order[3] == "UNIT_A", order)

    # La carte qu'on est en train de jouer ne peut pas être sa propre
    # monnaie d'échange.
    played = {c.code: c for c in snap.hand}["UNIT_BIG"]
    kept = [c.code for c in actions.choose_hand_sacrifice(snap, 4, exclude=(played,))]
    check("la carte jouée est exclue", "UNIT_BIG" not in kept, kept)


def test_hand_boost_picks_the_opposite_card():
    """
    Un renfort vise la MEILLEURE carte, un coût la pire.

    « Grant an ally in hand +3|+3 » et « Discard a card » cliquent tous
    deux dans la main, mais les deux clics n'ont rien à voir : se tromper
    de sens, c'est renforcer la carte qu'on allait jeter.
    """
    print("\nSens de la désignation")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    snap = snapshot_with(hand_codes=["UNIT_A", "UNIT_BIG", "SPELL_REFUSED"])

    pire = actions.choose_hand_targets(snap, 1, "any", pick_best=False)[0]
    meilleure = actions.choose_hand_targets(snap, 1, "any", pick_best=True)[0]
    check("le coût prend le fardeau", pire.code == "SPELL_REFUSED", pire)
    check("le cadeau prend une carte jouable", meilleure.code == "UNIT_A", meilleure)
    check("les deux ne se confondent pas", pire.code != meilleure.code)

    # Et le TYPE filtre : un renfort sur « an ally in hand » ne peut pas
    # désigner un sort, même si c'est la meilleure carte du lot.
    unites = actions.choose_hand_targets(snap, 3, "unit", pick_best=True)
    check("filtre par type", all(c.is_unit for c in unites), [c.code for c in unites])
    check("le sort est écarté", "SPELL_REFUSED" not in [c.code for c in unites])

    sorts = snapshot_with(hand_codes=["SPELL_REFUSED"])
    check("aucune unité à désigner dans une main de sorts",
          actions.choose_hand_targets(sorts, 1, "unit") == [])


def test_designation_rereads_between_clicks():
    """
    Entre deux désignations, les positions sont relues — ET STABILISÉES.

    La main se recentre dès qu'une carte la quitte : le deuxième clic d'un
    « Updraft 2 » calculé d'avance désignerait la voisine. C'est la même
    leçon que `relocate_card` a déjà servie à l'attaque et au blocage.

    Relire ne suffit pourtant pas, et c'est ce que le lecteur animé
    démontre ici : une relecture prise EN COURS de recentrage rend des
    rectangles en vol. Le clic part alors sur la position d'avant —
    quelques dizaines de pixels à côté, soit à gauche du sort visé.
    C'est ce qu'Elora a produit en jeu.
    """
    print("\nDésignation : relecture stabilisée entre deux clics")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    depart = hand_at([("UNIT_A", 11), ("UNIT_B", 12), ("UNIT_BIG", 13)])
    # Après le premier clic, la main a perdu UNIT_BIG et se RECENTRE : les
    # deux cartes restantes glissent de x0=500 vers x0=600, et l'API rend
    # des positions intermédiaires pendant tout le trajet.
    vol1 = hand_at([("UNIT_A", 11), ("UNIT_B", 12)], x0=520)
    apres = hand_at([("UNIT_A", 11), ("UNIT_B", 12)], x0=600)
    vol2 = hand_at([("UNIT_B", 12)], x0=640)
    fin = hand_at([("UNIT_B", 12)], x0=700)

    lecteur = AnimatedReader([(depart, depart), (vol1, apres), (vol2, fin)])

    clics = []
    original = actions.click

    def clic(x, y):
        clics.append((x, y))
        lecteur.advance()   # le clic déclenche l'animation suivante

    actions.click = clic
    try:
        ok, dernier, detail = actions.designate_in_hand(lecteur, depart, picks=2)
    finally:
        actions.click = original

    check("les deux désignations ont abouti", ok is True, detail)
    check("deux clics émis", len(clics) == 2, clics)

    # Le premier clic vise la plus chère de l'état de DÉPART ; le second
    # doit venir de l'état relu ET STABILISÉ, jamais de l'état en vol.
    cible1 = {c.code: c for c in depart.hand}["UNIT_BIG"].grab_point
    cible2 = {c.code: c for c in apres.hand}["UNIT_A"].grab_point
    en_vol = {c.code: c for c in vol1.hand}["UNIT_A"].grab_point
    ancienne = {c.code: c for c in depart.hand}["UNIT_A"].grab_point
    check("1er clic sur la plus chère", clics[0] == cible1, (clics[0], cible1))
    check("2e clic sur la position STABILISÉE", clics[1] == cible2, (clics[1], cible2))
    check("pas sur la position en vol", clics[1] != en_vol, en_vol)
    check("et surtout pas sur l'ancienne", clics[1] != ancienne, ancienne)


def test_copy_designation_leaves_the_card_in_hand():
    """
    ELORA : LA CARTE DÉSIGNÉE NE QUITTE PAS LA MAIN, ET C'EST NORMAL.

    « Play: Create an exact copy of a spell in hand » (98PZ007) copie le
    sort désigné : après le clic on en a DEUX, pas zéro. La vérification
    historique — « la carte désignée doit avoir quitté la main » — y voyait
    un clic raté, et `play_card` annulait dans la foulée une pose pourtant
    résolue. Treize cartes de la base sont dans ce cas (les « Grant ... to
    an ally in hand », les copies, les réductions de coût).

    Le verdict vient donc du plan (`pick_consumes`), pas d'une règle
    universelle.
    """
    print("\nDésignation qui ne consomme pas la carte (Elora)")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    plan = spells.classify_unit_play(HAND_POWER_CARDS["ELORA"]["descriptionRaw"])
    check("1 sort à désigner", (plan.picks, plan.pick_type) == (1, "spell"), plan)
    check("la carte reste en main", plan.pick_consumes is False, plan)
    check("on vise la meilleure", plan.pick_best is True, plan)

    # La main ne change pas : le sort désigné est toujours là après le clic.
    inchangee = snapshot_with(hand_codes=["SPELL_A", "UNIT_A"])

    original = actions.click
    actions.click = lambda x, y: None
    try:
        ok, _, detail = actions.designate_in_hand(
            FakeReader([inchangee]), inchangee, picks=1, pick_type="spell",
            pick_best=True, consumes=False,
        )
        # Le même état, jugé avec l'ancienne règle : voilà l'annulation à tort.
        strict, _, _ = actions.designate_in_hand(
            FakeReader([inchangee]), inchangee, picks=1, pick_type="spell",
            pick_best=True, consumes=True,
        )
    finally:
        actions.click = original

    check("pas d'échec inventé", ok is True, detail)
    check("le détail le dit", "reste en main" in detail, detail)
    check("la règle stricte, elle, aurait annulé", strict is False)


def test_elora_needs_a_spell_in_hand():
    """
    Sans sort en main, Elora n'est pas posée — même restrictions levées.

    Ce n'est pas une prudence : c'est le même genre de fait que le mana ou
    la place sur le banc. Le pouvoir demande UN SORT ; une main qui n'en
    contient aucun ne peut pas le résoudre, la pose finirait annulée et la
    carte serait mise de côté pour le tour. Les sorts appliquaient déjà
    cette règle, les unités non.
    """
    print("\nElora : il faut un sort à copier")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **HAND_POWER_CARDS})
        pool = ManaPool(mana=10, spell_mana=3)

        sans = snapshot_with(hand_codes=["ELORA", "UNIT_A", "UNIT_B"])
        codes = [c.code for c in playable_cards(sans, pool)]
        check("main sans sort : écartée", "ELORA" not in codes, codes)

        carte = {c.code: c for c in sans.hand}["ELORA"]
        raison = actions.rejection_reason(carte, sans, pool, allow_spells=False)
        check("raison chiffrée", raison is not None and "à désigner en main" in raison,
              raison)

        avec = snapshot_with(hand_codes=["ELORA", "SPELL_A", "UNIT_A"])
        codes = [c.code for c in playable_cards(avec, pool)]
        check("un sort en main : jouable", "ELORA" in codes, codes)

        carte = {c.code: c for c in avec.hand}["ELORA"]
        check("rien ne bloque", actions.unit_play_blocker(carte, avec) is None)

        # Et le sort désigné est bien un SORT : cliquer une unité ne
        # déclencherait rien et le jeu resterait en attente.
        plan, point, _ = actions.unit_play_plan(carte, avec)
        cibles = actions.choose_hand_targets(
            avec, plan.picks, plan.pick_type, plan.pick_best, exclude=(carte,),
        )
        check("aucun point de plateau", point is None, point)
        check("un sort désigné", [c.code for c in cibles] == ["SPELL_A"],
              [c.code for c in cibles])
    finally:
        actions.CARD_RESTRICTIONS = saved


def scene(specs, orb_active=True):
    """
    État fabriqué carte par carte : (code, card_id, ratio, x[, local[, hauteur]]).

    `hand_at` suppose que toutes les cartes sont dans la main ; il faut
    ici mélanger les hauteurs, puisque c'est justement la hauteur qui
    change pendant la fenêtre de désignation.

    Le CAMP et la HAUTEUR AFFICHÉE sont optionnels : la fenêtre de Yoink!
    montre des cartes de l'ADVERSAIRE, et toute fenêtre de choix dessine
    ses cartes bien plus grandes que la main (257x374 contre 176x246,
    mesuré le 05/11/2026). Les anciennes scènes à quatre éléments gardent
    exactement leur comportement.
    """
    rects = list(nexus_rects())
    for spec in specs:
        code, card_id, ratio, x = spec[:4]
        local = spec[4] if len(spec) > 4 else True
        height = spec[5] if len(spec) > 5 else 330
        rects.append(rect_at_ratio(ratio, code=code, card_id=card_id,
                                   height=height, x=x, local=local))
    install_fakes(rects, screen=make_screen(orb_active=orb_active, token="nous"))
    return state_reader().snapshot()


# Deux hauteurs, et tout le bug tient dans leur écart. La bande « hand »
# s'arrête à 0.030 (game_state.ZONE_BANDS) : une carte en main dépasse sous
# le bord bas de l'écran, c'est ce qui la distingue du banc. Quand le jeu
# ouvre une fenêtre de désignation, il REMONTE les cartes concernées pour
# les rendre cliquables — l'animation où elles s'entourent de bleu — et
# elles franchissent cette borne.
EN_MAIN = 0.029
REMONTEE = 0.100


def test_designation_survives_the_hand_being_lifted():
    """
    LA MAIN N'EST PLUS DANS LA BANDE « HAND » PENDANT LA DÉSIGNATION.

    Signalé par Ewan le 20/08/2026 : « il ne clique pas sur le sort après
    avoir joué la carte, il y a une courte animation où les sorts sont
    entourés de bleu ». C'est cette animation : le jeu remonte les cartes
    désignables, `classify_zone` les range dans « board », et une décision
    prise sur `snapshot.hand` à cet instant ne trouve plus rien à cliquer.

    D'où le partage : on DÉCIDE sur l'état d'avant le dépôt, on VISE par
    `CardID` dans l'état d'après, quelle que soit la zone lue.
    """
    print("\nDésignation pendant que la main est remontée")

    with_db({**ALL_CARDS, **HAND_POWER_CARDS})
    avant = hand_at([("SPELL_A", 21), ("UNIT_A", 22), ("ELORA", 23)])
    levee = scene([("SPELL_A", 21, REMONTEE, 700), ("UNIT_A", 22, REMONTEE, 840)])

    check("la bande « hand » est vide pendant l'animation", levee.hand == (), levee.hand)
    check("les cartes sont vues ailleurs", len(levee.board) == 2, levee.board)
    # Voilà pourquoi le bot renonçait : l'état d'APRÈS n'offre aucun sort
    # à désigner, alors que la main en contient un.
    check("l'état d'après ne propose rien",
          actions.choose_hand_targets(levee, 1, "spell", True) == [])
    check("l'état d'avant, si",
          [c.code for c in actions.choose_hand_targets(avant, 1, "spell", True)]
          == ["SPELL_A"])

    elora = {c.code: c for c in avant.hand}["ELORA"]
    clics = []
    original = actions.click
    actions.click = lambda x, y: clics.append((x, y))
    try:
        ok, _, detail = actions.designate_in_hand(
            FakeReader([levee]), avant, picks=1, pick_type="spell",
            pick_best=True, exclude=(elora,), consumes=False,
        )
    finally:
        actions.click = original

    vise = next(c for c in levee.board if c.code == "SPELL_A").grab_point
    ancienne = {c.code: c for c in avant.hand}["SPELL_A"].grab_point
    check("désignation aboutie", ok is True, detail)
    check("un clic émis", len(clics) == 1, clics)
    check("sur la position REMONTÉE du sort", clics[0] == vise, (clics, vise))
    check("pas sur sa position en main", clics[0] != ancienne, ancienne)


def test_elora_end_to_end():
    """
    Le parcours complet : Elora posée, le sort copié, aucune annulation.

    Les trois pièges se cumulaient sur cette carte — la main remontée, la
    position relue en pleine animation, et le sort qui NE QUITTE PAS la
    main. Un test qui ne les prend qu'un par un ne dit pas si la pose
    aboutit.
    """
    print("\nElora, de la pose à la copie")

    with_db({**ALL_CARDS, **HAND_POWER_CARDS})
    avant = hand_at([("SPELL_A", 21), ("UNIT_A", 22), ("ELORA", 23)])
    # Pendant la désignation : Elora n'est nulle part (elle attend sa
    # cible au centre de l'écran), les deux autres sont remontées.
    levee = scene([("SPELL_A", 21, REMONTEE, 700), ("UNIT_A", 22, REMONTEE, 840)])
    # Après : Elora est sur le banc, et le sort est en DOUBLE dans la main.
    apres = scene([
        ("ELORA", 23, REMONTEE, 900),
        ("SPELL_A", 21, EN_MAIN, 500), ("SPELL_A", 24, EN_MAIN, 640),
        ("UNIT_A", 22, EN_MAIN, 780),
    ])

    card = {c.code: c for c in avant.hand}["ELORA"]
    plan, point, _ = actions.unit_play_plan(card, avant)
    check("un plan de désignation", plan is not None and plan.needs_hand_pick, plan)
    check("aucune cible de plateau", point is None, point)

    recorder, cancels, clics = DragRecorder(), [], []
    saved_drag, saved_cancel, saved_click = (
        actions.drag, actions.cancel_pending_action, actions.click,
    )
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    actions.click = lambda x, y: clics.append((x, y))
    try:
        success, _ = play_card(
            FakeReader([levee, levee, apres]), avant, card, power_plan=plan,
        )
    finally:
        actions.drag = saved_drag
        actions.cancel_pending_action = saved_cancel
        actions.click = saved_click

    vise = next(c for c in levee.board if c.code == "SPELL_A").grab_point
    check("pose réussie", success is True)
    check("un seul dépôt", len(recorder.drags) == 1, recorder.drags)
    check("un clic de désignation", len(clics) == 1, clics)
    check("sur le sort remonté", clics[0] == vise, (clics, vise))
    check("aucune annulation", cancels == [], cancels)
    check("le sort est bien resté (en double)",
          len([c for c in apres.hand if c.code == "SPELL_A"]) == 2)


def test_designation_detects_a_click_that_did_not_take():
    """Une carte encore en main après son clic est un échec, pas un succès."""
    print("\nDésignation : clic sans effet")

    with_db({**FULL_DB, **HAND_POWER_CARDS})
    depart = snapshot_with(hand_codes=["UNIT_A", "UNIT_BIG"])

    original = actions.click
    actions.click = lambda x, y: None
    try:
        # Le lecteur renvoie un état INCHANGÉ : la carte est toujours là.
        ok, _, detail = actions.designate_in_hand(FakeReader([depart]), depart, picks=1)
    finally:
        actions.click = original

    check("échec signalé", ok is False)
    check("raison explicite", "n'a pas pris" in detail, detail)


# ============================================================
# CHOIX DE VERSION À LA POSE
# ============================================================
# La fenêtre s'ouvre au CENTRE de l'écran, comme celle du mulligan : les
# deux versions ne sont donc dans aucune zone du plateau, et c'est leur
# NOM qui les identifie.
FENETRE_DE_CHOIX = 0.500


def test_wings_and_the_wave_decision():
    """
    QUELLE VERSION POSER, ET POURQUOI PAS LA PLUS GROSSE.

    Le 22/08/2026, « Les ailes et la vague » (04SI004) a figé une partie :
    « Play me as First Wave or Last Wind » ne nomme aucune cible, donc la
    carte passait pour une pose ordinaire. Elle est posée, le jeu ouvre sa
    fenêtre de choix, et rien ne la referme — ni l'annulation, ni le clic
    de passe.

    Entre une 0|1 et une 3|3, on prend la 0|1 : la seconde se paie d'un
    allié (« To play me, kill an ally »), donc une interface de plus après
    le choix, donc une occasion de plus de se figer.
    """
    print("\nLes ailes et la vague : la décision")

    with_db({**ALL_CARDS, **CHOICE_CARDS})
    snap = snapshot_with(hand_codes=["WINGS", "UNIT_A"])
    carte = {c.code: c for c in snap.hand}["WINGS"]

    plan, point, description = actions.unit_play_plan(carte, snap)
    check("un plan est rendu", plan is not None and plan.needs_choice, plan)
    check("aucune cible de plateau", point is None, point)
    check("la description nomme les versions",
          "First Wave" in description and "Last Wind" in description, description)

    # Ni la prudence ni sa levée ne doivent l'écarter : c'est une fenêtre
    # qu'on SAIT piloter, contrairement à Manifest.
    for restrictions in (True, False):
        saved = actions.CARD_RESTRICTIONS
        actions.CARD_RESTRICTIONS = restrictions
        try:
            check(f"posable (restrictions={restrictions})",
                  actions.unit_play_blocker(carte, snap) is None,
                  actions.unit_play_blocker(carte, snap))
        finally:
            actions.CARD_RESTRICTIONS = saved

    fenetre = scene([
        ("FIRST_WAVE", 51, FENETRE_DE_CHOIX, 800),
        ("LAST_WIND", 52, FENETRE_DE_CHOIX, 1000),
    ])
    proposees = actions.offered_versions(fenetre, plan.options)
    check("les deux versions reconnues",
          sorted(c.code for c in proposees) == ["FIRST_WAVE", "LAST_WIND"],
          [c.code for c in proposees])
    check("la version gratuite l'emporte",
          actions.choose_offered_version(proposees).code == "FIRST_WAVE",
          actions.choose_offered_version(proposees))

    # Une Première vague DÉJÀ posée n'est pas une proposition : cliquer
    # l'unité du banc ne refermerait pas la fenêtre.
    deja = scene([
        ("FIRST_WAVE", 40, 0.150, 400),          # sur le banc depuis un tour
        ("FIRST_WAVE", 51, FENETRE_DE_CHOIX, 800),
        ("LAST_WIND", 52, FENETRE_DE_CHOIX, 1000),
    ])
    connues = {40}
    proposees = actions.offered_versions(deja, plan.options, connues)
    check("l'unité déjà en jeu est ignorée",
          sorted(c.card_id for c in proposees) == [51, 52],
          [c.card_id for c in proposees])


def test_wings_and_the_wave_end_to_end():
    """La pose complète : dépôt, choix cliqué, unité sur le banc."""
    print("\nLes ailes et la vague : de la pose au banc")

    with_db({**ALL_CARDS, **CHOICE_CARDS})
    avant = hand_at([("WINGS", 21), ("UNIT_A", 22)])
    # Pendant : la carte posée n'est nulle part, les deux versions
    # attendent au centre de l'écran.
    fenetre = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("FIRST_WAVE", 51, FENETRE_DE_CHOIX, 800),
        ("LAST_WIND", 52, FENETRE_DE_CHOIX, 1000),
    ])
    # Après : la version choisie est sur le banc, sous SON code à elle.
    apres = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("FIRST_WAVE", 51, 0.150, 800),
    ])

    carte = {c.code: c for c in avant.hand}["WINGS"]
    plan, _, _ = actions.unit_play_plan(carte, avant)

    recorder, cancels, clics = DragRecorder(), [], []
    saved_drag, saved_cancel, saved_click = (
        actions.drag, actions.cancel_pending_action, actions.click,
    )
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    actions.click = lambda x, y: clics.append((x, y))
    try:
        success, _ = play_card(
            FakeReader([fenetre, fenetre, apres]), avant, carte, power_plan=plan,
        )
    finally:
        actions.drag = saved_drag
        actions.cancel_pending_action = saved_cancel
        actions.click = saved_click

    vise = next(c for c in fenetre.cards() if c.code == "FIRST_WAVE").grab_point
    autre = next(c for c in fenetre.cards() if c.code == "LAST_WIND").grab_point
    check("pose réussie", success is True)
    check("un seul dépôt", len(recorder.drags) == 1, recorder.drags)
    check("un seul clic", len(clics) == 1, clics)
    check("sur la Première vague", clics and clics[0] == vise, (clics, vise))
    check("pas sur l'autre version", clics and clics[0] != autre, autre)
    check("aucune annulation", cancels == [], cancels)


# FENÊTRES DE CARTES — Manifest, Predict, Tellstones. Contrairement aux
# versions, on ne sait PAS d'avance ce qu'elles montrent : Manifest invente
# ses cartes. On les reconnaît à leur CardID NOUVEAU, hors main et hors
# banc. Codes inventés, textes réels.
CARD_WINDOW_CARDS = {
    "STONEWEAVING": {
        "name": "Stoneweaving", "cost": 1, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Manifest a landmark you can afford.",
    },
    "STARSHAPING": {
        "name": "Starshaping", "cost": 5, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "spellSpeedRef": "Slow",
        "descriptionRaw": "Invoke a Celestial card that costs 7 or more, "
                          "then heal an ally or your Nexus 5.",
    },
    "PAPARO": {
        "name": "Paparo the Great", "cost": 3, "attack": 3, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Manifest a Yordle.\r\nAttack: Grant Yordle allies +1|+0.",
    },
    # Ce que la fenêtre propose : une unité connue, une grosse unité, un
    # sort que le bot refuse (deux cibles), une carte absente de la base.
    "OFFER_SMALL": {
        "name": "Yordle Squire", "cost": 2, "attack": 2, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "OFFER_BIG": {
        "name": "Yordle Captain", "cost": 4, "attack": 4, "health": 4,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "OFFER_REFUSED": {
        "name": "Crumble", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "spellSpeedRef": "Slow",
        "descriptionRaw": "Kill an ally to kill a unit.",
    },
    # Yoink! (98SB003) et les trois cartes ADVERSES de sa fenêtre, telles
    # qu'elles étaient à l'écran le 05/11/2026 à 17:12:50.
    "YOINK": {
        "name": "Yoink!", "cost": 1, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Pick 1 of 3 non-champion cards from the enemy hand "
                          "to draw. They draw 1.",
    },
    "THEIR_SMITH": {
        "name": "Yordle Smith", "cost": 2, "attack": 2, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "THEIR_RISSU": {
        "name": "Rissu, The Silent Storm", "cost": 5, "attack": 1, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "THEIR_GRENADIER": {
        "name": "Gruff Grenadier", "cost": 4, "attack": 4, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
}

# Hauteur affichée des cartes d'une FENÊTRE DE CHOIX. Mesuré sur la trace
# du 05/11/2026 : 374 px pour les cartes proposées, 246 pour la main, 160
# pour le banc. C'est cet écart que `visible_card_window` exploite.
HAUTEUR_FENETRE = 430


def _record_gestures():
    """Remplace glisser, clic et annulation ; renvoie (enregistreurs, restaurer)."""
    recorder, cancels, clics = DragRecorder(), [], []
    saved = (actions.drag, actions.cancel_pending_action, actions.click)
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    actions.click = lambda x, y: clics.append((x, y))

    def restore():
        actions.drag, actions.cancel_pending_action, actions.click = saved

    return (recorder, cancels, clics), restore


def test_manifest_picks_the_best_new_card():
    """
    UNE FENÊTRE DE CARTES SE LIT À L'ÉCRAN, ET ON PREND CE QU'ON SAURA JOUER.

    Stoneweaving (Burst) : au dépôt, trois cartes NOUVELLES apparaissent au
    centre. Ni leur nom ni leur nombre n'étaient connus ; on les reconnaît
    à leur CardID absent de l'état d'avant. Le bot doit cliquer la plus
    grosse UNITÉ connue — pas le sort refusé, pas la carte inconnue — et
    conclure que le sort est résolu, sans annulation.
    """
    print("\nManifest : la fenêtre de cartes est lue et la meilleure prise")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    avant = hand_at([("STONEWEAVING", 21), ("UNIT_A", 22)])
    fenetre = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("OFFER_REFUSED", 61, FENETRE_DE_CHOIX, 700),
        ("OFFER_BIG", 62, FENETRE_DE_CHOIX, 900),
        ("OFFER_SMALL", 63, FENETRE_DE_CHOIX, 1100),
    ])
    # Après le clic : la carte prise est en main, plus aucune fenêtre.
    apres = scene([("UNIT_A", 22, EN_MAIN, 500), ("OFFER_BIG", 62, EN_MAIN, 640)])

    carte = {c.code: c for c in avant.hand}["STONEWEAVING"]
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        success, _ = actions.play_spell(FakeReader([fenetre, fenetre, apres, apres]), avant, carte)
    finally:
        restore()

    vise = next(c for c in fenetre.cards() if c.code == "OFFER_BIG").grab_point
    check("sort résolu", success is True)
    check("un seul dépôt", len(recorder.drags) == 1, recorder.drags)
    check("un seul clic", len(clics) == 1, clics)
    check("sur la plus grosse unité connue", clics and clics[0] == vise, (clics, vise))
    check("aucune annulation", cancels == [], cancels)

    # Le classement, isolément : l'inconnue et le sort refusé en dernier.
    offertes = actions.offered_cards(fenetre, {c.card_id for c in avant.cards()})
    check("trois cartes proposées", sorted(c.card_id for c in offertes) == [61, 62, 63],
          [c.card_id for c in offertes])
    check("la carte de la main n'est pas proposée",
          all(c.card_id != 22 for c in offertes))
    ordre = [c.code for c in sorted(offertes, key=actions.card_pick_rank)]
    check("le sort refusé est le dernier choix", ordre[0] == "OFFER_REFUSED", ordre)
    check("la grosse unité est le premier choix", ordre[-1] == "OFFER_BIG", ordre)


def test_unit_manifest_after_the_drop():
    """
    « Play: Manifest a Yordle » : la fenêtre s'ouvre après le dépôt de
    l'unité, qui arrive sur le banc sous son propre code. `unit_play_plan`
    doit rendre un plan (sinon `play_card` ignorerait la fenêtre), sans
    cible de plateau, et `unit_play_blocker` ne doit rien y trouver à
    redire.
    """
    print("\nPaparo : fenêtre de cartes après la pose d'une unité")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    avant = hand_at([("PAPARO", 21), ("UNIT_A", 22)])
    carte = {c.code: c for c in avant.hand}["PAPARO"]
    plan, point, description = actions.unit_play_plan(carte, avant)
    check("un plan est rendu", plan is not None, plan)
    check("sans cible de plateau", point is None, point)
    check("qui nomme la fenêtre", "Manifest" in description, description)
    check("aucun empêchement", actions.unit_play_blocker(carte, avant) is None,
          actions.unit_play_blocker(carte, avant))

    fenetre = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("PAPARO", 21, 0.150, 800),
        ("OFFER_SMALL", 63, FENETRE_DE_CHOIX, 700),
        ("OFFER_BIG", 62, FENETRE_DE_CHOIX, 900),
    ])
    apres = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("OFFER_BIG", 62, EN_MAIN, 640),
        ("PAPARO", 21, 0.150, 800),
    ])
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        success, _ = play_card(
            FakeReader([fenetre, fenetre, apres, apres, apres]), avant, carte, power_plan=plan,
        )
    finally:
        restore()

    vise = next(c for c in fenetre.cards() if c.code == "OFFER_BIG").grab_point
    check("pose réussie", success is True)
    check("un seul clic, dans la fenêtre", clics == [vise], (clics, vise))
    check("l'unité posée n'est pas prise pour une carte proposée",
          all(c != next(x for x in fenetre.cards() if x.code == "PAPARO").grab_point
              for c in clics))
    check("aucune annulation", cancels == [], cancels)


def test_unknown_card_with_a_surprise_choice_window():
    """
    NIDALEE, 04/09/2026 : « Quick Attack. Ambush 2 », ABSENTE de card_sets.
    Aucun plan ne prévoit sa fenêtre à deux versions ; pourtant elle
    s'ouvre au dépôt, et la version affichée au centre porte SON code dans
    la bande « attack » — que `_placed_counts` compte comme posée. Le bot
    concluait « posée » et passait à autre chose, fenêtre béante.

    Attendu : la fenêtre est reconnue SANS texte (deux cartes nouvelles à
    nous, hors main et hors banc), la championne elle-même est cliquée
    (à stats égales, la carte jouée l'emporte), puis la pose est vérifiée
    sur le banc. Aucune annulation.
    """
    print("\nNidalee : fenêtre de choix imprévue sur une carte inconnue")

    with_db(dict(ALL_CARDS))  # ni NIDALEE ni SHADOW n'y figurent
    avant = hand_at([("NIDALEE", 21), ("UNIT_A", 22)])
    carte = {c.code: c for c in avant.hand}["NIDALEE"]
    check("la carte est bien inconnue", carte.known is False, carte)
    plan, point, description = actions.unit_play_plan(carte, avant)
    check("aucun plan : rien à lire dans son texte", plan is None, plan)

    fenetre = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("SHADOW", 72, FENETRE_DE_CHOIX, 700),
        ("NIDALEE", 71, FENETRE_DE_CHOIX, 1100),
    ])
    apres = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("NIDALEE", 71, 0.150, 800),
    ])
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        success, _ = play_card(FakeReader([fenetre, fenetre, apres, apres, apres]), avant, carte)
    finally:
        restore()

    vise = next(c for c in fenetre.cards() if c.card_id == 71).grab_point
    check("pose réussie", success is True)
    check("un seul dépôt", len(recorder.drags) == 1, recorder.drags)
    check("un seul clic, sur la championne elle-même", clics == [vise], (clics, vise))
    check("aucune annulation", cancels == [], cancels)

    # Le classement, isolément : à stats égales (deux inconnues), la carte
    # jouée passe devant.
    offertes = actions.offered_cards(fenetre, {c.card_id for c in avant.cards()})
    check("deux versions proposées", sorted(c.card_id for c in offertes) == [71, 72],
          [c.card_id for c in offertes])
    meilleure = max(offertes, key=lambda c: actions.unforeseen_choice_rank(c, carte))
    check("la carte jouée l'emporte à égalité", meilleure.card_id == 71, meilleure)

    # Sans fenêtre, le filet ne coûte rien : une pose ordinaire reste une
    # pose ordinaire, sans clic parasite.
    #
    # ON RAFRAÎCHIT `avant` AVANT DE LE RÉUTILISER. Le premier `play_card`
    # ci-dessus prend plus d'une seconde, donc l'instantané qui a décidé
    # dépasse `AIM_MAX_AGE` (0,8 s) au second appel : `play_card` relit
    # alors la main pour viser frais (règle du 05/09, deck Nilah), n'y
    # trouve plus NIDALEE — elle est AU PLATEAU dans cette scène — et rend
    # False. Ce sous-cas teste le FILET de fenêtre imprévue, pas la
    # fraîcheur ; sans ce rafraîchissement il dépend de la vitesse de la
    # machine, et il a fini par basculer le 10/11/2026. CLAUDE.md le dit
    # depuis le 05/09 : « un test qui laisse vieillir un instantané avant
    # `play_card` doit le rafraîchir ».
    avant.taken_at = time.time()
    pose = scene([("UNIT_A", 22, EN_MAIN, 500), ("NIDALEE", 21, 0.150, 800)])
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        success, _ = play_card(FakeReader([pose, pose, pose]), avant, carte)
    finally:
        restore()
    check("pose ordinaire réussie", success is True)
    check("aucun clic quand rien n'est proposé", clics == [], clics)
    check("aucune annulation non plus", cancels == [], cancels)


def test_discard_then_window_ignores_the_lingering_card():
    """
    SPACEY SKETCHER, 02/09/2026 : « Play: Discard 1 to Invoke ». Le bot a
    cliqué la carte à défausser, la fenêtre d'Invoke s'est ouverte… et la
    carte défaussée est RESTÉE rapportée par l'API pendant plus de 7 s.
    Le bot attendait son départ, a conclu « le clic n'a pas pris », a
    annulé, et la fenêtre est restée béante. Quand une fenêtre de cartes
    suit, c'est SON apparition qui prouve la désignation — pas le départ
    de la carte.
    """
    print("\nDiscard 1 to Manifest : la carte défaussée traîne, la fenêtre s'ouvre quand même")

    with_db({**ALL_CARDS, **HAND_POWER_CARDS, **CARD_WINDOW_CARDS})
    avant = hand_at([("MANIFEST_UNIT", 21), ("UNIT_A", 22)])
    carte = {c.code: c for c in avant.hand}["MANIFEST_UNIT"]
    plan, _, _ = actions.unit_play_plan(carte, avant)
    check("plan avec désignation ET fenêtre",
          plan is not None and plan.needs_hand_pick and plan.opens_card_window, plan)

    # Panneau de défausse : UNIT_A remontée au centre, l'unité sur la pile.
    panneau = scene([("UNIT_A", 22, FENETRE_DE_CHOIX, 700), ("MANIFEST_UNIT", 21, 0.480, 960)])
    # Fenêtre ouverte, la carte défaussée TOUJOURS rapportée.
    fenetre = scene([
        ("UNIT_A", 22, FENETRE_DE_CHOIX, 700),
        ("MANIFEST_UNIT", 21, 0.480, 960),
        ("OFFER_SMALL", 63, FENETRE_DE_CHOIX, 900),
        ("OFFER_BIG", 62, FENETRE_DE_CHOIX, 1100),
    ])
    apres = scene([("OFFER_BIG", 62, EN_MAIN, 500), ("MANIFEST_UNIT", 21, 0.150, 800)])
    (recorder, cancels, clics), restore = _record_gestures()
    saved_glance = actions.CARD_WINDOW_CHAIN_GLANCE
    actions.CARD_WINDOW_CHAIN_GLANCE = 0.05
    try:
        success, _ = play_card(
            FakeReader([panneau, panneau, fenetre, fenetre, fenetre, fenetre, apres, apres, apres]),
            avant, carte, power_plan=plan,
        )
    finally:
        restore()
        actions.CARD_WINDOW_CHAIN_GLANCE = saved_glance

    defausse = next(c for c in panneau.cards() if c.code == "UNIT_A").grab_point
    prise = next(c for c in fenetre.cards() if c.code == "OFFER_BIG").grab_point
    check("pose réussie", success is True)
    check("deux clics : la défausse, puis la carte de la fenêtre",
          clics == [defausse, prise], (clics, defausse, prise))
    check("aucune annulation", cancels == [], cancels)


HARSH_WINDS = {
    "HARSH_WINDS": {
        "name": "Vents mordants", "cost": 4, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst", "descriptionRaw": "Frostbite 2 enemies. ",
    },
}


def test_harsh_winds_on_a_single_enemy():
    """
    VENTS MORDANTS face à UN ennemi (02/09/2026) : « Frostbite 2 enemies »
    passait pour « aucune cible » ; le sort partait sans clic et le jeu
    attendait. Le jeu accepte moins de cibles qu'annoncé quand il n'y en a
    pas plus : le sort doit être jugé jouable, avec un seul clic — et
    deux clics distincts quand deux ennemis sont là.
    """
    print("\nVents mordants : deux ennemis annoncés, un seul en face")

    with_db({**ALL_CARDS, **VARIANT_CARDS, **HARSH_WINDS})
    un_seul = variant_scene([
        ("HARSH_WINDS", 21, EN_MAIN, 500),
        ("UNIT_B", 40, 0.800, 400, False),
    ], "nous")
    carte = {c.code: c for c in un_seul.hand}["HARSH_WINDS"]
    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        castable, plan, targets, detail = actions.spell_is_castable(carte, un_seul)
        check("jouable avec un seul ennemi", castable is True, detail)
        check("un seul clic prévu", len(targets) == 1, targets)
        check("le détail le dit", "1/2" in detail, detail)

        deux = variant_scene([
            ("HARSH_WINDS", 21, EN_MAIN, 500),
            ("UNIT_B", 40, 0.800, 400, False),
            ("UNIT_A", 41, 0.800, 600, False),
        ], "nous")
        carte = {c.code: c for c in deux.hand}["HARSH_WINDS"]
        castable, plan, targets, detail = actions.spell_is_castable(carte, deux)
        check("deux ennemis : deux clics distincts",
              castable and len(targets) == 2 and targets[0] != targets[1], (targets, detail))

        # De bout en bout : un clic, le sort part, AUCUNE annulation.
        carte = {c.code: c for c in un_seul.hand}["HARSH_WINDS"]
        apres = variant_scene([("UNIT_B", 40, 0.800, 400, False)], "nous")
        (recorder, cancels, clics), restore = _record_gestures()
        try:
            success, _ = actions.play_spell(FakeReader([apres, apres, apres]), un_seul, carte)
        finally:
            restore()
        check("un seul ennemi : sort résolu", success is True)
        check("   un seul clic", len(clics) == 1, clics)
        check("   aucune annulation", cancels == [], cancels)

        aucun = variant_scene([("HARSH_WINDS", 21, EN_MAIN, 500)], "nous")
        carte = {c.code: c for c in aucun.hand}["HARSH_WINDS"]
        castable, _, _, detail = actions.spell_is_castable(carte, aucun)
        check("aucun ennemi : pas jouable", castable is False, detail)
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_yoink_prend_une_carte_dans_la_main_adverse():
    """
    LA FENÊTRE D'UN SORT QUI PIOCHE CHEZ L'ADVERSAIRE EST FAITE DE SES CARTES.

    05/11/2026, 17:12:37-17:15:54. Yoink! (98SB003) lancé ; le jeu ouvre
    « Pick 1 of 3 » sur TROIS CARTES DE L'ADVERSAIRE (CardID 1278610636,
    1566250659, 1153891470 — LocalPlayer FALSE, 257x374, bande
    `enemy_attack`). `offered_cards` ne regardait que les cartes à nous :
    « Fenêtre de cartes introuvable », annulation sans effet, 184 s de
    blocage, combat abandonné, tentative hebdomadaire perdue.

    Le plan porte désormais le camp (`spells.card_window_side`) et la
    fenêtre est lue du bon côté. On prend la meilleure carte — ici le
    Gruff Grenadier 4/3, la plus grosse unité — et le sort est résolu,
    sans annulation.
    """
    print("\nYoink! : la fenêtre montre les cartes de l'adversaire")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    avant = hand_at([("YOINK", 21), ("UNIT_A", 22)])
    carte = {c.code: c for c in avant.hand}["YOINK"]

    plan = spells.classify_card(carte, restricted=False)
    check("fenêtre annoncée", plan.card_window == "Pick 1 of N", plan.card_window)
    check("   cartes de l'adversaire", plan.card_window_side == "theirs", plan)

    # L'écran du blocage : notre main, et les trois cartes ADVERSES de la
    # fenêtre, alignées au centre et plus grandes que tout le reste.
    fenetre = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("THEIR_SMITH", 1278610636, FENETRE_DE_CHOIX, 670, False, HAUTEUR_FENETRE),
        ("THEIR_RISSU", 1566250659, FENETRE_DE_CHOIX, 959, False, HAUTEUR_FENETRE),
        ("THEIR_GRENADIER", 1153891470, FENETRE_DE_CHOIX, 1247, False, HAUTEUR_FENETRE),
    ])
    apres = scene([("UNIT_A", 22, EN_MAIN, 500),
                   ("THEIR_GRENADIER", 1153891470, EN_MAIN, 640)])

    offertes = actions.offered_cards(
        fenetre, {c.card_id for c in avant.cards()}, side="theirs",
    )
    check("trois cartes proposées",
          sorted(c.card_id for c in offertes)
          == [1153891470, 1278610636, 1566250659], [c.card_id for c in offertes])
    check("   côté « ours » : on ne voit rien",
          actions.offered_cards(fenetre, {c.card_id for c in avant.cards()}) == [],
          actions.offered_cards(fenetre, {c.card_id for c in avant.cards()}))

    (recorder, cancels, clics), restore = _record_gestures()
    try:
        success, _ = actions.play_spell(
            FakeReader([fenetre, fenetre, apres, apres]), avant, carte,
        )
    finally:
        restore()

    vise = next(c for c in fenetre.cards() if c.code == "THEIR_GRENADIER").grab_point
    check("sort résolu", success is True)
    check("   un seul clic", len(clics) == 1, clics)
    check("   sur la plus grosse unité adverse", clics and clics[0] == vise, (clics, vise))
    check("   aucune annulation", cancels == [], cancels)


def test_une_fenetre_de_choix_ne_se_laisse_pas_annuler():
    """
    « SÉLECTIONNER LA CIBLE » + ORBE ÉTEINTE : ON NE PEUT PAS ATTENDRE.

    Le blocage du 05/11/2026 tient dans l'ordre des tests de
    `respond_to_stack`. Pendant les 184 s, l'état lu était toujours
    « [SPELL_STACK] orbe=non bouton=cible » : l'orbe EST éteinte quand le
    jeu attend un geste de nous, donc la branche « le jeu attend une
    cible » écrite le 05/09/2026 n'était jamais atteinte — on tombait sur
    « l'adversaire a la priorité : on attend », 43 fois.

    Et même atteinte, elle n'aurait pas suffi : une FENÊTRE DE CHOIX ne
    s'annule pas (trois clics droits sans effet dans la trace). Il faut
    prendre une carte.
    """
    print("\nFenêtre de choix sous « SÉLECTIONNER LA CIBLE » : on prend une carte")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    # L'écran du blocage, à l'identique : notre main, notre banc, et les
    # trois cartes de la fenêtre. Orbe ÉTEINTE.
    bloque = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("UNIT_B", 23, EN_MAIN, 640),
        ("THEIR_SMITH", 1278610636, FENETRE_DE_CHOIX, 670, False, HAUTEUR_FENETRE),
        ("THEIR_RISSU", 1566250659, FENETRE_DE_CHOIX, 959, False, HAUTEUR_FENETRE),
        ("THEIR_GRENADIER", 1153891470, FENETRE_DE_CHOIX, 1247, False, HAUTEUR_FENETRE),
    ], orb_active=False)
    bloque = replace(bloque, phase=Phase.SPELL_STACK, button_label="cible")
    check("orbe éteinte, comme dans la trace", bloque.turn_orb_active is False, bloque)

    repere = actions.visible_card_window(bloque)
    check("la fenêtre est reconnue à sa forme", len(repere) == 3, [c.name for c in repere])

    (recorder, cancels, clics), restore = _record_gestures()
    saved_sleep = actions.time.sleep
    actions.time.sleep = lambda s: None
    try:
        log = actions.respond_to_stack(FakeReader([bloque]), bloque, allow_spells=True)
    finally:
        restore()
        actions.time.sleep = saved_sleep

    vise = next(c for c in bloque.cards() if c.code == "THEIR_GRENADIER").grab_point
    check("un clic, pas une attente", len(clics) == 1, clics)
    check("   sur une carte de la fenêtre", clics and clics[0] == vise, (clics, vise))
    check("   aucune annulation", cancels == [], cancels)
    check("   le journal dit pourquoi",
          any("ne s'annule pas" in e for e in log.entries), log.entries)
    check("   et surtout : on n'attend plus l'adversaire",
          not any("priorité" in e for e in log.entries), log.entries)


# Les CARTES ADVERSES de la trame réelle, avec les stats lues dans le log
# du 05/11/2026 à 17:13:50. On garde les rectangles tels que l'API les a
# envoyés ; seules les définitions de cartes sont fabriquées, pour que la
# suite ne dépende pas de card_sets.
CARTES_DE_LA_TRAME = {
    "05BC235": {"name": "Yordle Smith", "cost": 2, "attack": 2, "health": 2,
                "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
    "05BC127": {"name": "Rissu, The Silent Storm", "cost": 5, "attack": 1, "health": 3,
                "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
    "05BC039": {"name": "Gruff Grenadier", "cost": 4, "attack": 4, "health": 3,
                "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
    "98SB003": {"name": "Yoink!", "cost": 1, "attack": 0, "health": 0,
                "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
                "spellSpeedRef": "Burst",
                "descriptionRaw": "Pick 1 of 3 non-champion cards from the enemy "
                                  "hand to draw. They draw 1."},
    "05BC167T1": {"name": "Hungry Owlcat", "cost": 1, "attack": 2, "health": 1,
                  "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
}


def test_la_vraie_trame_du_blocage_de_yoink():
    """
    LA TRAME QUE L'API A VRAIMENT ENVOYÉE PENDANT LE BLOCAGE.

    `captures_reference/fenetre_yoink_20261105.json` est la lecture
    d'API du 05/11/2026 à 17:12:50 — 19 rectangles, copiés de la trace
    sans retouche. Elle vaut mieux qu'une scène fabriquée : elle fixe les
    MESURES sur lesquelles reposent les deux garde-fous.

      - les trois cartes proposées font 257x374 et partagent le bord haut
        TopLeftY=789, quand la main fait 176x246 et le banc 127x160 : le
        seuil « 1,25 fois le reste » et l'alignement sont confortables,
        pas limites ;
      - elles sont rapportées LocalPlayer=FALSE et tombent dans la bande
        `enemy_attack` (ratio 0,64) : c'est bien le camp, et non la zone,
        qui les distinguait.

    Si un jour ces chiffres bougent, c'est ici qu'on le saura.
    """
    print("\nLa trame réelle du blocage de Yoink! (05/11/2026, 17:12:50)")

    chemin = CAPTURES_REFERENCE / "fenetre_yoink_20261105.json"
    if not chemin.exists():
        check(f"capture de référence absente : {chemin.name}", False)
        return

    trame = json.loads(chemin.read_text(encoding="utf-8"))
    with_db({**ALL_CARDS, **CARTES_DE_LA_TRAME})
    install_fakes(trame["Rectangles"], screen=make_screen(orb_active=False, token=None))
    snap = state_reader().snapshot()

    proposees = [c for c in snap.cards()
                 if c.card_id in (1278610636, 1566250659, 1153891470)]
    check("les trois cartes de la fenêtre sont lues", len(proposees) == 3,
          [c.name for c in proposees])
    check("   elles sont à l'ADVERSAIRE", all(not c.local for c in proposees),
          [(c.name, c.local) for c in proposees])
    check("   lues dans la bande enemy_attack",
          {c.zone for c in proposees} == {"enemy_attack"},
          {c.zone for c in proposees})

    # Ce que voyait l'ancien code : les cartes à NOUS, nouvelles. Aucune.
    connues = {c.card_id for c in snap.cards()
               if c.card_id >= 0 and c.card_id not in
               (1278610636, 1566250659, 1153891470)}
    check("côté « ours » : rien — c'était le bogue",
          actions.offered_cards(snap, connues) == [],
          [c.name for c in actions.offered_cards(snap, connues)])
    check("côté « theirs » : les trois cartes",
          sorted(c.card_id for c in actions.offered_cards(snap, connues, side="theirs"))
          == [1153891470, 1278610636, 1566250659],
          [c.name for c in actions.offered_cards(snap, connues, side="theirs")])

    # Le filet géométrique, sur les vraies dimensions.
    repere = actions.visible_card_window(snap)
    check("la forme seule suffit à reconnaître la fenêtre",
          sorted(c.card_id for c in repere)
          == [1153891470, 1278610636, 1566250659], [c.name for c in repere])
    check("   on y prendrait le Gruff Grenadier 4/3",
          repere and actions.choose_offered_card(repere).code == "05BC039",
          actions.choose_offered_card(repere).name if repere else None)

    # Les mesures elles-mêmes, pour que les seuils restent justifiés.
    hauteurs = {c.card_id: c.box[3] - c.box[1] for c in snap.cards() if c.card_id >= 0}
    fenetre = max(hauteurs[i] for i in (1278610636, 1566250659, 1153891470))
    reste = max(h for i, h in hauteurs.items()
                if i not in (1278610636, 1566250659, 1153891470))
    check(f"la fenêtre dépasse le reste d'au moins 1,25 fois "
          f"({fenetre} contre {reste})",
          fenetre >= reste * actions.WINDOW_BIGGER_THAN_REST, (fenetre, reste))
    tops = [c.box[1] for c in repere]
    check(f"et ses trois cartes sont alignées (écart {max(tops) - min(tops)} px)",
          max(tops) - min(tops) <= actions.WINDOW_ALIGN_RATIO * 1080, tops)

    # Et le blocage lui-même : orbe éteinte, bouton « cible ».
    bloque = replace(snap, phase=Phase.SPELL_STACK, button_label="cible")
    (recorder, cancels, clics), restore = _record_gestures()
    saved_sleep = actions.time.sleep
    actions.time.sleep = lambda s: None
    try:
        log = actions.respond_to_stack(FakeReader([bloque]), bloque, allow_spells=True)
    finally:
        restore()
        actions.time.sleep = saved_sleep
    check("sur cet écran exact, le bot clique au lieu d'attendre",
          len(clics) == 1 and cancels == [], (clics, cancels, log.entries))


def test_ce_qui_nest_pas_une_fenetre_de_choix():
    """
    LA FORME D'UNE FENÊTRE, ET CE QUI LUI RESSEMBLE SANS EN ÊTRE.

    `visible_card_window` est le dernier recours — il clique sans rien
    savoir de la carte — donc il doit se taire partout ailleurs. Mesuré
    sur les 4192 lectures d'API des traces : avec ces garde-fous, 182
    lectures sont retenues, et ce sont des mulligans, des fenêtres de
    version et celle de Yoink!. Sans l'exclusion des zones de repos,
    1003 — la main alignée passait pour une fenêtre.
    """
    print("\nCe qui n'est pas une fenêtre de choix")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})

    main_seule = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("UNIT_B", 23, EN_MAIN, 640),
        ("UNIT_BIG", 24, EN_MAIN, 780),
    ])
    check("une main alignée n'est pas une fenêtre",
          actions.visible_card_window(main_seule) == [],
          [c.name for c in actions.visible_card_window(main_seule)])

    survol = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("UNIT_B", 23, EN_MAIN, 640),
        ("UNIT_BIG", 24, FENETRE_DE_CHOIX, 960, True, HAUTEUR_FENETRE),
    ])
    check("une seule carte grossie (survol) n'est pas une fenêtre",
          actions.visible_card_window(survol) == [],
          [c.name for c in actions.visible_card_window(survol)])

    eventail = scene([
        ("UNIT_A", 22, 0.42, 500, True, HAUTEUR_FENETRE),
        ("UNIT_B", 23, 0.46, 700, True, HAUTEUR_FENETRE),
        ("UNIT_BIG", 24, 0.50, 900, True, HAUTEUR_FENETRE),
    ])
    check("des cartes grandes mais NON alignées non plus",
          actions.visible_card_window(eventail) == [],
          [c.name for c in actions.visible_card_window(eventail)])

    banc = scene([
        ("UNIT_A", 22, 0.100, 500),
        ("UNIT_B", 23, 0.100, 640),
        ("UNIT_BIG", 24, 0.100, 780),
    ])
    check("le banc, aligné et seul à l'écran, n'est pas une fenêtre",
          actions.visible_card_window(banc) == [],
          [c.name for c in actions.visible_card_window(banc)])

    vraie = scene([
        ("UNIT_A", 22, EN_MAIN, 500),
        ("OFFER_SMALL", 61, FENETRE_DE_CHOIX, 700, True, HAUTEUR_FENETRE),
        ("OFFER_BIG", 62, FENETRE_DE_CHOIX, 1000, True, HAUTEUR_FENETRE),
    ])
    check("deux cartes alignées et plus grandes : une fenêtre",
          [c.code for c in actions.visible_card_window(vraie)]
          == ["OFFER_SMALL", "OFFER_BIG"],
          [c.code for c in actions.visible_card_window(vraie)])


def test_card_window_not_reported():
    """
    Si aucune carte nouvelle n'apparaît, on le dit et on rend la main —
    sans cliquer au hasard. La carte est alors mise de côté pour le tour.
    """
    print("\nManifest : fenêtre non rapportée")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    avant = hand_at([("STONEWEAVING", 21), ("UNIT_A", 22)])
    muet = scene([("UNIT_A", 22, EN_MAIN, 500)])
    carte = {c.code: c for c in avant.hand}["STONEWEAVING"]

    saved_timeout = actions.DESIGNATION_TIMEOUT
    actions.DESIGNATION_TIMEOUT = 0.05
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        picks, _, detail = actions.resolve_card_choice(
            FakeReader([muet]), carte, spells.classify_card(carte), avant, timeout=0.05,
        )
        success, _ = actions.play_spell(FakeReader([muet]), avant, carte)
    finally:
        restore()
        actions.DESIGNATION_TIMEOUT = saved_timeout

    check("rien de choisi", picks == [], picks)
    check("le détail dit ce qu'on a vu", "Manifest" in detail and "vu" in detail, detail)
    check("aucun clic", clics == [], clics)
    check("le sort est compté raté", success is False)
    check("la main est rendue (annulation tentée)", len(cancels) >= 1, cancels)


def test_slow_spell_window_opens_after_validation():
    """
    Starshaping (Slow) : la cible est cliquée AU LANCEMENT, la fenêtre
    s'ouvre À LA RÉSOLUTION — après la validation. Le bot doit donc :
    cliquer l'allié, valider (bouton de tour), PUIS lire la fenêtre.
    """
    print("\nStarshaping : cible au lancement, fenêtre après validation")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    rects_avant = [("STARSHAPING", 21, EN_MAIN, 500), ("UNIT_A", 40, 0.150, 800)]
    avant = scene(rects_avant)
    carte = {c.code: c for c in avant.hand}["STARSHAPING"]
    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        castable, plan, targets, _ = actions.spell_is_castable(carte, avant)
        check("jouable sans restrictions", castable is True, plan)
        check("une cible : l'allié", len(targets) == 1, targets)
        check("fenêtre Invoke annoncée", plan.card_window == "Invoke", plan)

        # Sur la pile après le dépôt ; puis, la pile vidée, la fenêtre.
        pile = scene([("UNIT_A", 40, 0.150, 800), ("STARSHAPING", 21, 0.480, 960)])
        fenetre = scene([
            ("UNIT_A", 40, 0.150, 800),
            ("OFFER_SMALL", 63, FENETRE_DE_CHOIX, 700),
            ("OFFER_BIG", 62, FENETRE_DE_CHOIX, 900),
        ])
        apres = scene([("UNIT_A", 40, 0.150, 800), ("OFFER_BIG", 62, EN_MAIN, 500)])
        # Trois scènes fabriquées depuis `avant` : au-delà de AIM_MAX_AGE
        # (temps RÉEL, cf. `test_clock`) `play_spell` relirait la main.
        avant.taken_at = time.time()

        (recorder, cancels, clics), restore = _record_gestures()
        try:
            success, _ = actions.play_spell(
                FakeReader([pile, fenetre, fenetre, fenetre, apres, apres]), avant, carte,
            )
        finally:
            restore()
    finally:
        actions.CARD_RESTRICTIONS = saved

    allie = targets[0]
    bouton = avant.window.rel(*actions.TURN_BUTTON_RATIO)
    vise = next(c for c in fenetre.cards() if c.code == "OFFER_BIG").grab_point
    check("sort résolu", success is True)
    check("trois clics : cible, validation, fenêtre", len(clics) == 3, clics)
    check("   l'allié d'abord", clics and clics[0] == allie, (clics, allie))
    check("   la validation ensuite", len(clics) > 1 and clics[1] == bouton, (clics, bouton))
    check("   la fenêtre en dernier", len(clics) > 2 and clics[2] == vise, (clics, vise))
    check("aucune annulation", cancels == [], cancels)


def test_chained_windows():
    """
    « Repeat two more times » (Songspinner), « Invoke a low, medium, and
    high cost Celestial » : plusieurs fenêtres à la suite. Après chaque
    clic, des cartes ENCORE plus neuves valent une nouvelle fenêtre.
    """
    print("\nFenêtres enchaînées")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    avant = hand_at([("STONEWEAVING", 21)])
    premiere = scene([("OFFER_SMALL", 61, FENETRE_DE_CHOIX, 700),
                      ("OFFER_BIG", 62, FENETRE_DE_CHOIX, 900)])
    seconde = scene([("OFFER_BIG", 62, EN_MAIN, 500),
                     ("OFFER_SMALL", 71, FENETRE_DE_CHOIX, 700),
                     ("OFFER_REFUSED", 72, FENETRE_DE_CHOIX, 900)])
    fin = scene([("OFFER_BIG", 62, EN_MAIN, 500), ("OFFER_SMALL", 71, EN_MAIN, 640)])
    carte = {c.code: c for c in avant.hand}["STONEWEAVING"]

    saved_glance = actions.CARD_WINDOW_CHAIN_GLANCE
    actions.CARD_WINDOW_CHAIN_GLANCE = 0.05
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        picks, _, detail = actions.resolve_card_choice(
            FakeReader([premiere, premiere, seconde, seconde, fin, fin]), carte,
            spells.classify_card(carte), avant,
        )
    finally:
        restore()
        actions.CARD_WINDOW_CHAIN_GLANCE = saved_glance

    check("deux cartes prises", [c.code for c in picks] == ["OFFER_BIG", "OFFER_SMALL"],
          [c.code for c in picks])
    check("deux clics", len(clics) == 2, clics)
    check("la carte déjà prise n'est pas recliquée",
          clics[1] == next(c for c in seconde.cards() if c.code == "OFFER_SMALL").grab_point
          if len(clics) > 1 else False, clics)


# Un « ou » qui n'ouvre AUCUNE fenêtre : il élargit la cible. C'est le cas
# le plus fréquent de la base, et celui qui ne doit rien coûter.
OR_TARGET_CARD = {
    "OR_TARGET": {
        "name": "Onde de choc", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 3 to a unit or destroy a landmark.",
    },
}


def variant_scene(specs, token):
    """
    Comme `scene`, mais le jeton d'attaque est choisi : il décide.

    Une spécification vaut (code, card_id, ratio, x) — ou un cinquième
    élément `local` à False pour poser une carte ADVERSE.
    """
    rects = list(nexus_rects())
    for spec in specs:
        code, card_id, ratio, x = spec[:4]
        local = spec[4] if len(spec) > 4 else True
        rects.append(rect_at_ratio(ratio, code=code, card_id=card_id,
                                   height=330, x=x, local=local))
    install_fakes(rects, screen=make_screen(orb_active=True, token=token))
    return state_reader().snapshot()


def test_momentous_choice_picks_a_variant_before_the_target():
    """
    LA VARIANTE D'ABORD, LA CIBLE ENSUITE.

    « Choix capital » (Momentous Choice, 06IO034) : « Give an ally +2|+0
    or +0|+2 this round. » Le jeu propose les deux versions AVANT de
    demander l'allié ; le bot ne voyait que la seconde étape et cliquait
    l'allié tout de suite, dans une fenêtre qui n'écoutait pas.

    La règle de choix est celle d'Ewan : la force quand on a le jeton
    d'attaque — la puissance se convertit en dégâts dès ce tour — les
    points de vie sinon, pour survivre au round adverse.
    """
    print("\nChoix capital : la variante avant la cible")

    with_db({**ALL_CARDS, **VARIANT_CARDS})

    def joue(token, reader_states=None):
        avant = variant_scene(
            [("MOMENTOUS", 21, EN_MAIN, 500), ("UNIT_A", 30, 0.150, 400)], token)
        fenetre = variant_scene([
            ("UNIT_A", 30, 0.150, 400),
            ("MOMENTOUS_FORCE", 51, FENETRE_DE_CHOIX, 800),
            ("MOMENTOUS_VIE", 52, FENETRE_DE_CHOIX, 1000),
        ], token)
        apres = variant_scene([("UNIT_A", 30, 0.150, 400)], token)

        carte = {c.code: c for c in avant.hand}["MOMENTOUS"]
        plan = spells.classify_card(carte, restricted=actions.CARD_RESTRICTIONS)
        cible, _ = spells.choose_target(plan, avant)
        # L'HORLOGE VIRTUELLE LAISSE PASSER LE TEMPS RÉEL (`test_clock`) :
        # chaque scène coûte ~0,17 s de vraie seconde à fabriquer, et
        # au-delà de `AIM_MAX_AGE` (0,8 s) `play_spell` relit la main au
        # lieu de viser — le test devient alors rouge selon la VITESSE DE
        # LA MACHINE, pas selon le code. On rafraîchit la lecture qui a
        # décidé, comme CLAUDE.md le prescrit.
        avant.taken_at = time.time()

        recorder, cancels, clics = DragRecorder(), [], []
        saved = (actions.drag, actions.cancel_pending_action, actions.click)
        actions.drag = recorder
        actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
        actions.click = lambda x, y: clics.append((x, y))
        try:
            success, _ = actions.play_spell(
                FakeReader(reader_states or [fenetre, fenetre, apres]),
                avant, carte,
            )
        finally:
            actions.drag, actions.cancel_pending_action, actions.click = saved

        points = {c.code: c.grab_point for c in fenetre.cards()}
        return success, clics, cancels, points, cible, plan, apres

    # ---- le jeton en main : on prend la FORCE ---------------------------
    success, clics, cancels, points, cible, plan, _ = joue("nous")
    check("le plan voit la variante", plan.needs_variant is True, plan)
    check("   et garde sa cible alliée",
          plan.targeting is spells.Targeting.ALLY, plan.targeting)
    check("sort lancé", success is True)
    check("deux clics : la variante puis l'allié", len(clics) == 2, clics)
    check("la force d'abord",
          clics and clics[0] == points["MOMENTOUS_FORCE"], (clics, points))
    check("l'allié ensuite", len(clics) > 1 and clics[1] == cible, (clics, cible))
    check("aucune annulation", cancels == [], cancels)

    # ---- pas de jeton : on prend les POINTS DE VIE -----------------------
    success, clics, _, points, _, _, _ = joue(None)
    check("sans le jeton, la vie",
          clics and clics[0] == points["MOMENTOUS_VIE"], (clics, points))

    # ---- fenêtre non rapportée : on ne clique RIEN à l'aveugle ----------
    sans_fenetre = variant_scene([("UNIT_A", 30, 0.150, 400)], "nous")
    success, clics, cancels, _, _, _, _ = joue("nous", [sans_fenetre])
    check("sort déclaré en échec", success is False)
    check("aucun clic au hasard", clics == [], clics)
    check("annulation tentée", len(cancels) == 1, cancels)


def test_iula_chooses_the_keyword_it_understands():
    """
    IULA (05MT013) : « Grant an ally Spellshield or Overwhelm. »

    Signalé par Ewan le 22/08/2026, juste après Choix capital : le bot
    cliquait l'allié sans avoir choisi le pouvoir. Même fenêtre, mais le
    choix porte sur un MOT-CLÉ — rien de chiffré dans le texte, donc rien
    que `stat_variants` puisse voir. C'est l'écran qui dit qu'une fenêtre
    s'est ouverte, et les deux jetons portent le nom d'Iula.

    Entre Spellshield et Overwhelm, on prend celui dont
    `keywords.resolve_duel` tient compte. Ce n'est pas « le meilleur en
    soi » : c'est le seul des deux que le bot sait chiffrer.
    """
    print("\nIula : le mot-clé qu'on sait évaluer")

    with_db({**ALL_CARDS, **VARIANT_CARDS})
    avant = variant_scene(
        [("IULA", 21, EN_MAIN, 500), ("UNIT_A", 30, 0.150, 400)], "nous")
    fenetre = variant_scene([
        ("UNIT_A", 30, 0.150, 400),
        ("IULA_SPELLSHIELD", 51, FENETRE_DE_CHOIX, 800),
        ("IULA_OVERWHELM", 52, FENETRE_DE_CHOIX, 1000),
    ], "nous")
    apres = variant_scene(
        [("UNIT_A", 30, 0.150, 400), ("IULA_OVERWHELM", 52, 0.150, 560)], "nous")

    carte = {c.code: c for c in avant.hand}["IULA"]
    plan, cible, _ = actions.unit_play_plan(carte, avant)
    check("une fenêtre est possible", plan is not None and plan.may_offer_variants,
          plan)
    check("   sans certitude chiffrée", plan.needs_variant is False, plan)
    check("   et l'allié reste à cibler", cible is not None, cible)

    recorder, cancels, clics = DragRecorder(), [], []
    saved = (actions.drag, actions.cancel_pending_action, actions.click)
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    actions.click = lambda x, y: clics.append((x, y))
    try:
        success, _ = play_card(
            FakeReader([fenetre, fenetre, apres]), avant, carte,
            power_target=cible, power_description="allié", power_plan=plan,
        )
    finally:
        actions.drag, actions.cancel_pending_action, actions.click = saved

    points = {c.code: c.grab_point for c in fenetre.cards()}
    check("pose réussie", success is True)
    check("deux clics : le pouvoir puis l'allié", len(clics) == 2, clics)
    check("Overwhelm plutôt que Spellshield",
          clics and clics[0] == points["IULA_OVERWHELM"], (clics, points))
    check("l'allié ensuite", len(clics) > 1 and clics[1] == cible, (clics, cible))
    check("aucune annulation", cancels == [], cancels)


def test_an_or_that_opens_nothing_costs_only_a_glance():
    """
    LE « OU » QUI N'OUVRE RIEN NE DOIT RIEN CASSER.

    « Deal 3 to a unit or destroy a landmark » : le « ou » élargit la
    CIBLE, il ne propose pas deux versions. 119 cartes jouables de la base
    contiennent un « ou » et la plupart sont dans ce cas — si les traiter
    coûtait une annulation, le correctif d'Iula ferait plus de dégâts que
    le bogue.

    Le bot regarde donc, ne trouve pas de version, et poursuit son
    ciblage comme avant.
    """
    print("\nUn « ou » qui n'ouvre aucune fenêtre")

    with_db({**ALL_CARDS, **VARIANT_CARDS, **OR_TARGET_CARD})
    avant = variant_scene([
        ("OR_TARGET", 21, EN_MAIN, 500),
        ("UNIT_A", 30, 0.150, 400),
        ("UNIT_B", 40, 0.800, 400, False),      # une cible adverse
    ], "nous")
    apres = variant_scene([
        ("UNIT_A", 30, 0.150, 400),
        ("UNIT_B", 40, 0.800, 400, False),
    ], "nous")

    carte = {c.code: c for c in avant.hand}["OR_TARGET"]
    plan = spells.classify_card(carte, restricted=actions.CARD_RESTRICTIONS)
    cible, _ = spells.choose_target(plan, avant)
    check("une fenêtre est jugée possible", plan.may_offer_variants is True, plan)
    check("   mais rien n'est promis", plan.needs_variant is False, plan)

    recorder, cancels, clics = DragRecorder(), [], []
    saved = (actions.drag, actions.cancel_pending_action, actions.click)
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    actions.click = lambda x, y: clics.append((x, y))
    try:
        success, _ = actions.play_spell(FakeReader([apres]), avant, carte)
    finally:
        actions.drag, actions.cancel_pending_action, actions.click = saved

    check("sort lancé quand même", success is True)
    check("un seul clic : la cible", clics == [cible], (clics, cible))
    check("aucune annulation", cancels == [], cancels)


def test_a_variant_that_would_not_accept_the_click_is_avoided():
    """
    ENTRE DEUX VERSIONS, ON PREND CELLE QUI ACCEPTE LE CLIC PRÉVU.

    « Deal 2 to a unit or deal 1 to two enemies » (Bouncing Bomb) : le
    ciblage est décidé sur le texte du PARENT — une unité — et part juste
    après la fenêtre. Prendre « deal 1 to two enemies », c'est cliquer
    dans le vide, puis laisser le jeu attendre deux cibles qu'on ne sait
    pas enchaîner.
    """
    print("\nLa version qui accepte le clic prévu")

    with_db({**ALL_CARDS, **VARIANT_CARDS})
    fenetre = variant_scene([
        ("BOMB_DEUX", 61, FENETRE_DE_CHOIX, 800),
        ("BOMB_UNITE", 62, FENETRE_DE_CHOIX, 1000),
    ], "nous")
    proposees = list(fenetre.cards())
    plan = spells.classify_text("Deal 2 to a unit or deal 1 to two enemies.",
                                restricted=actions.CARD_RESTRICTIONS)
    check("le parent vise une unité",
          plan.targeting is spells.Targeting.ANY_UNIT, plan.targeting)

    choisie = actions.choose_variant(proposees, plan, swinging=True)
    check("on prend celle qui vise une unité", choisie.code == "BOMB_UNITE",
          choisie.code)

    # Et sans plan parent, on ne se retrouve pas sans réponse : la fenêtre
    # est obligatoire, il FAUT cliquer quelque chose.
    check("un choix est rendu même sans plan",
          actions.choose_variant(proposees, None, swinging=True) is not None)


def test_choice_window_not_reported():
    """
    SI L'API NE RAPPORTE PAS LA FENÊTRE, ON LE DIT.

    C'est le seul pari de ce mécanisme : la fenêtre de choix s'affiche
    comme celle du mulligan, donc l'API doit la rapporter. Si elle ne le
    fait pas, le bot doit rendre la main avec un diagnostic utilisable —
    et non retenter le même geste — parce que la carte reste alors à
    jouer à la main.
    """
    print("\nLes ailes et la vague : fenêtre non rapportée")

    with_db({**ALL_CARDS, **CHOICE_CARDS})
    avant = hand_at([("WINGS", 21), ("UNIT_A", 22)])
    # Le jeu attend, mais rien de ce qu'on cherche n'est à l'écran.
    muet = scene([("UNIT_A", 22, EN_MAIN, 500)])

    carte = {c.code: c for c in avant.hand}["WINGS"]
    plan, _, _ = actions.unit_play_plan(carte, avant)

    recorder, cancels, clics = DragRecorder(), [], []
    saved_drag, saved_cancel, saved_click = (
        actions.drag, actions.cancel_pending_action, actions.click,
    )
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    actions.click = lambda x, y: clics.append((x, y))
    try:
        chosen, _, detail = actions.resolve_play_choice(
            FakeReader([muet]), plan, avant,
        )
        # `avant` a vieilli pendant resolve_play_choice : sans ce
        # rafraîchissement, play_card relirait la main (fresh_hand_card) et
        # n'y trouverait plus WINGS — ce n'est pas ce qu'on teste ici.
        avant.taken_at = time.time()
        success, _ = play_card(
            FakeReader([muet]), avant, carte, power_plan=plan, attempts=1,
        )
    finally:
        actions.drag = saved_drag
        actions.cancel_pending_action = saved_cancel
        actions.click = saved_click

    check("aucune version choisie", chosen is None, chosen)
    check("le détail nomme ce qu'on cherchait", "First Wave" in detail, detail)
    check("et ce qu'on a vu à la place", "vu :" in detail, detail)
    check("aucun clic à l'aveugle", clics == [], clics)
    check("pose déclarée en échec", success is False)
    check("annulation tentée quand même", len(cancels) == 1, cancels)


def test_real_spells_seen_in_game():
    """
    LES DEUX SORTS QUI SE SONT RETOURNÉS CONTRE NOUS.

    Black Spear : « If an ally died this round, deal 4 to a unit. » La
    condition comptait comme une cible ALLIÉE et masquait le `^deal`.
    Résultat en jeu — 4 dégâts sur une de nos unités.

    Crumble : « Kill an ally to kill a unit or destroy a landmark. » Deux
    clics. Le bot sacrifiait l'allié puis laissait le client en attente du
    second, sans même annuler (l'annulation ne partait que si AUCUNE cible
    n'avait été cliquée).

    Lame féroce : « An Equipped ally strikes an enemy. » Deux clics encore,
    mais le premier était INVISIBLE — aucun marqueur ne reconnaissait
    « an Equipped ally », alors que « an ally » l'aurait été. Il n'en
    restait qu'un, l'ennemi, et le bot cliquait dessus en croyant lancer
    un sort à une cible. Signalé par Ewan le 22/08/2026.
    """
    print("\nSorts réels vus en jeu : Lance noire, Éboulement, Lame féroce")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **HAND_POWER_CARDS})
        pool = ManaPool(mana=10, spell_mana=3)
        snap = snapshot_with(
            hand_codes=["BLACK_SPEAR", "CRUMBLE", "FURIOUS_WIELDER"],
            board_codes=["UNIT_A", "UNIT_BIG"],
        )
        lance = {c.code: c for c in snap.hand}["BLACK_SPEAR"]
        plan = spells.classify_card(lance, restricted=False)
        check("Lance noire : dégâts reconnus", plan.effect == "DAMAGE", plan)
        check("   sur une unité, pas sur un allié",
              plan.targeting is spells.Targeting.ANY_UNIT, plan.targeting)
        check("   et classée nuisible", plan.harmful is True, plan)

        crumble = {c.code: c for c in snap.hand}["CRUMBLE"]
        echange = spells.classify_card(crumble, restricted=False)
        check("Éboulement : un échange, plus un refus (05/09/2026)",
              echange.playable and echange.is_trade, echange)
        check("   deux clics, allié puis unité", echange.total_targets == 2, echange)

        lame = {c.code: c for c in snap.hand}["FURIOUS_WIELDER"]
        refus_lame = spells.classify_card(lame, restricted=False)
        check("Lame féroce : l'allié équipé compte comme une cible",
              not refus_lame.playable, refus_lame)
        check("   deux cibles, donc une incapacité",
              refus_lame.impossible is True, refus_lame)
        check("   et surtout PAS un simple ciblage d'ennemi",
              refus_lame.targeting is not spells.Targeting.ENEMY,
              refus_lame.targeting)

        codes = [c.code for c in playable_cards(snap, pool, allow_spells=True)]
        check("Éboulement sans ennemi en face : pas tenté", "CRUMBLE" not in codes, codes)
        check("Lame féroce non plus", "FURIOUS_WIELDER" not in codes, codes)
        raison = actions.rejection_reason(crumble, snap, pool, allow_spells=True)
        check("   et le diagnostic dit qu'il manque la récompense",
              raison is not None and "échange" in raison and "ennemi" in raison, raison)
        raison = actions.rejection_reason(lame, snap, pool, allow_spells=True)
        check("   pour la Lame féroce aussi",
              raison is not None and "cibles à cliquer" in raison, raison)
    finally:
        actions.CARD_RESTRICTIONS = saved


def trade_snapshot(hand_codes, board_codes, enemy_codes):
    """Notre main et notre banc, et des unités adverses sur LEUR banc (pas en attaque)."""
    rects, card_id = list(nexus_rects()), 300
    for index, code in enumerate(hand_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.029, code=code, card_id=card_id, height=330, x=500 + 140 * index))
    for index, code in enumerate(board_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=500 + 130 * index))
    for index, code in enumerate(enemy_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.800, code=code, card_id=card_id, local=False, x=500 + 130 * index))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


def test_trade_spells_pay_the_cheapest_and_hit_the_best():
    """
    Éboulement (« Kill an ally to kill a unit ») : on sacrifie la plus
    maigre, on tue le plus gros — et seulement si l'échange en vaut la
    peine. Astral Diffusion (« Deal 2 to an ally to Stun an enemy ») :
    l'allié qui ENCAISSE sans mourir, jamais celui qui en mourrait.
    """
    print("\nÉchanges : le coût le moins cher, la récompense la plus forte")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **HAND_POWER_CARDS, "ASTRAL": {
            "name": "Diffusion astrale", "cost": 2, "attack": 0, "health": 0,
            "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
            "descriptionRaw": "Deal 2 to an ally to Stun an enemy.",
        }, "FRAIL": {
            "name": "Fragile", "cost": 1, "attack": 1, "health": 1,
            "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
        }})
        pool = ManaPool(mana=10, spell_mana=3)

        # Éboulement : Fragile (1/1) contre Colosse adverse (8/8) → on y va.
        snap = trade_snapshot(["CRUMBLE"], ["FRAIL", "UNIT_A"], ["UNIT_BIG"])
        crumble = snap.hand[0]
        by_code = {c.code: c for c in snap.board}
        enemy = snap.enemy_board[0]
        castable, plan, targets, why = actions.spell_is_castable(crumble, snap)
        check("Éboulement jouable face au Colosse", castable, why)
        check("   deux points, dans l'ordre coût puis récompense",
              targets == (by_code["FRAIL"].center, enemy.center), (targets, why))
        check("   la description nomme les deux", "Fragile" in why and "Colosse" in why, why)
        codes = [c.code for c in playable_cards(snap, pool, allow_spells=True)]
        check("   et il est proposé à la pose", "CRUMBLE" in codes, codes)

        # Le même sort face à un 1/1 adverse, avec pour seule offrande le
        # Colosse (8/8) : échange à perte, on attend.
        snap = trade_snapshot(["CRUMBLE"], ["UNIT_BIG"], ["FRAIL"])
        castable, plan, targets, why = actions.spell_is_castable(snap.hand[0], snap)
        check("échange à perte : refusé", not castable and targets == (), (castable, targets))
        check("   et dit pourquoi", "défavorable" in why, why)
        raison = actions.rejection_reason(snap.hand[0], snap, pool, allow_spells=True)
        check("   motif de contexte pour le journal",
              raison is not None and raison.startswith("sort : échange"), raison)

        # Diffusion astrale : Fragile (1 PV) mourrait des 2 dégâts, Garde de
        # Fer (4 PV) les encaisse → c'est elle qui paie ; l'ennemi est étourdi.
        snap = trade_snapshot(["ASTRAL"], ["FRAIL", "UNIT_A"], ["UNIT_BIG"])
        by_code = {c.code: c for c in snap.board}
        castable, plan, targets, why = actions.spell_is_castable(snap.hand[0], snap)
        check("Diffusion astrale jouable", castable, why)
        check("   l'allié qui survit paie", targets[0] == by_code["UNIT_A"].center, why)
        check("   l'ennemi est la seconde cible", targets[1] == snap.enemy_board[0].center, why)

        # Plan à blanc : les deux clics sont annoncés.
        recorder = DragRecorder()
        saved_drag = actions.drag
        actions.drag = recorder
        try:
            ok, _ = actions.play_spell(FakeReader([snap]), snap, snap.hand[0], dry_run=True)
        finally:
            actions.drag = saved_drag
        check("   mode plan : accepté sans geste", ok and not recorder.drags, recorder.drags)
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_directed_duels_pick_the_pair_that_kills_and_survives():
    """
    CHANTIER 4 (06/09/2026) : Cataclysm (« An ally starts a free attack
    Challenging an enemy. »), Desert Duel (« Give an enemy -2|-0 this round.
    An ally and that enemy strike each other. ») et Weight of Judgment
    (« Deal 2 to a champion or 4 to a follower. ») étaient les refus les
    plus fréquents du journal. Les deux premiers sont des DUELS DIRIGÉS :
    on simule chaque paire (allié, ennemi) et on clique, dans l'ordre du
    texte, celle qui tue sans mourir. Le troisième est UN clic dont le
    montant dépend de la cible.
    """
    print("\nDuels dirigés et « champion ou suivant »")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **HAND_POWER_CARDS,
            "CATACLYSM": {"name": "Cataclysme", "cost": 3, "attack": 0, "health": 0,
                          "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
                          "descriptionRaw": "An ally starts a free attack Challenging an enemy."},
            "DESERT_DUEL": {"name": "Duel du désert", "cost": 3, "attack": 0, "health": 0,
                            "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
                            "descriptionRaw": "Give an enemy -2|-0 this round. An ally and that enemy strike each other."},
            "JUDGMENT": {"name": "Poids du jugement", "cost": 3, "attack": 0, "health": 0,
                         "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
                         "descriptionRaw": "Deal 2 to a champion or 4 to a follower."},
            "FRAIL": {"name": "Fragile", "cost": 1, "attack": 1, "health": 1,
                      "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
            "MID": {"name": "Moyen", "cost": 3, "attack": 3, "health": 3,
                    "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
            "CHAMP4": {"name": "Champion4", "cost": 4, "attack": 4, "health": 4, "supertype": "Champion",
                       "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
        })

        # Cataclysm : Colosse (8/8) et Fragile (1/1) chez nous ; Moyen (3/3) en face.
        # Le Colosse tue Moyen et survit ; Fragile mourrait. → Colosse puis Moyen.
        snap = trade_snapshot(["CATACLYSM"], ["FRAIL", "UNIT_BIG"], ["MID"])
        by_code = {c.code: c for c in snap.board}
        plan = spells.classify_card(snap.hand[0], restricted=False)
        check("Cataclysme : un duel à deux clics", plan.duel and plan.total_targets == 2, plan)
        castable, plan, targets, why = actions.spell_is_castable(snap.hand[0], snap)
        check("   jouable : le Colosse contre Moyen", castable, why)
        check("   ordre du texte : l'allié puis l'ennemi",
              targets == (by_code["UNIT_BIG"].center, snap.enemy_board[0].center), (targets, why))

        # Seul Fragile (1/1) face à Moyen (3/3) : on meurt sans tuer → on attend.
        snap = trade_snapshot(["CATACLYSM"], ["FRAIL"], ["MID"])
        castable, _, targets, why = actions.spell_is_castable(snap.hand[0], snap)
        check("duel perdant : refusé, et dit pourquoi", not castable and "défavorable" in why, why)

        # Desert Duel : Moyen (3/3) chez nous face à Moyen (3/3). Sans malus
        # les deux meurent ; avec -2 d'attaque l'ennemi ne frappe plus que 1
        # → notre Moyen survit. L'ENNEMI se clique d'abord (ordre du texte).
        snap = trade_snapshot(["DESERT_DUEL"], ["MID"], ["MID"])
        castable, plan, targets, why = actions.spell_is_castable(snap.hand[0], snap)
        check("Duel du désert : le malus -2 est compté", castable, why)
        check("   ordre du texte : l'ennemi puis l'allié",
              targets == (snap.enemy_board[0].center, snap.board[0].center), (targets, why))

        # Weight of Judgment : Champion4 (4 PV) ne meurt pas de 2 ; Moyen (3 PV)
        # meurt de 4 → c'est Moyen qu'on vise.
        snap = trade_snapshot(["JUDGMENT"], ["FRAIL"], ["CHAMP4", "MID"])
        plan = spells.classify_card(snap.hand[0], restricted=False)
        check("Poids du jugement : UN clic", plan.total_targets == 1 and plan.playable, plan)
        check("   4 au suivant, 2 au champion", (plan.amount, plan.amount_champion) == (4, 2), plan)
        castable, plan, targets, why = actions.spell_is_castable(snap.hand[0], snap)
        moyen = next(c for c in snap.enemy_board if c.code == "MID")
        check("   vise le suivant qu'on tue, pas le champion qu'on ne tue pas",
              castable and targets == (moyen.center,), (targets, why))

        # Les alliés QUALIFIÉS restent hors de portée (condition invérifiable).
        lame = spells.classify_text("An Equipped ally strikes an enemy.", restricted=False)
        check("« An Equipped ally strikes » : toujours refusé", not lame.playable and lame.impossible, lame)
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_damage_without_a_number_and_transform_hit_the_enemy():
    """
    06/09/2026 : Banana Blaster (« Play: Deal damage equal to my Power to a
    unit ») et Minimorph (« Transform a unit into a 3|3 Mini-Minitee and
    Silence it ») tombaient en effet AUTRE → cadeau à un allié → sans allié,
    posés SANS cible → partie figée (25 min pour la première). Les deux
    sont des malus : ils visent l'ennemi, et « equal to my Power » vaut
    l'attaque de la carte.
    """
    print("\nDégâts sans chiffre et Transform : des malus, donc sur l'ennemi")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS,
            "BANANA": {"name": "Lanceur de bananes", "cost": 4, "attack": 2, "health": 2,
                       "type": "Unit", "keywords": [], "keywordRefs": [],
                       "descriptionRaw": "Play: Deal damage equal to my Power to a unit."},
            "MINIMORPH": {"name": "Minimorph", "cost": 6, "attack": 0, "health": 0,
                          "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
                          "descriptionRaw": "Transform a unit into a 3|3 Mini-Minitee and Silence it."},
            "TWO2": {"name": "Deux-deux", "cost": 2, "attack": 2, "health": 2,
                     "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
        })
        # Aucun allié sur le banc (comme en jeu : que des landmarks), deux ennemis.
        snap = trade_snapshot(["BANANA", "MINIMORPH"], [], ["UNIT_BIG", "TWO2"])
        banana = {c.code: c for c in snap.hand}["BANANA"]
        plan, point, description = actions.unit_play_plan(banana, snap)
        two2 = next(c for c in snap.enemy_board if c.code == "TWO2")
        check("Lanceur de bananes : des DÉGÂTS, montant = sa puissance",
              plan is not None and plan.effect == "DAMAGE" and plan.amount == 2, plan)
        check("   cible : l'ennemi qu'on tue (2 PV), pas le Colosse",
              point == two2.center, (point, description))
        check("   rien ne bloque la pose", actions.unit_play_blocker(banana, snap) is None)

        mini = {c.code: c for c in snap.hand}["MINIMORPH"]
        castable, plan, targets, why = actions.spell_is_castable(mini, snap)
        big = next(c for c in snap.enemy_board if c.code == "UNIT_BIG")
        check("Minimorph : un malus, sur la plus grosse unité ADVERSE",
              castable and plan.effect == "TRANSFORM" and targets == (big.center,), (plan, targets, why))
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_black_spear_hits_the_enemy():
    """La cible choisie est bien une unité ADVERSE, pas la nôtre."""
    print("\nLance noire : sur qui elle part")

    with_db({**ALL_CARDS, **HAND_POWER_CARDS})
    snap = blocking_snapshot(["SMALL", "BRUTE"], ["ELUSIVE"])
    lance = type("C", (), {
        "description": "If an ally died this round, deal 4 to a unit.",
        "known": True,
    })()
    plan = spells.classify_card(lance, restricted=False)
    point, description = spells.choose_target(plan, snap)

    nos_points = {c.center for c in snap.board}
    leurs_points = {c.center for c in snap.enemy_attack_row}
    check("une cible a été trouvée", point is not None, description)
    check("ce n'est pas une des nôtres", point not in nos_points, description)
    check("c'est bien un ennemi", point in leurs_points, description)


def test_equipment_targets_an_ally():
    """
    Un équipement se pose sur notre plus grosse unité, et pas du tout sans
    unité — sinon le client attendrait un clic qui n'a nulle part où aller.
    """
    print("\nÉquipement")

    with_db({**ALL_CARDS, **HAND_POWER_CARDS})
    pool = ManaPool(mana=10, spell_mana=0)

    snap = snapshot_with(hand_codes=["SWORD"], board_codes=["SMALL", "BRUTE"])
    point, description = actions.equipment_plan(
        {c.code: c for c in snap.hand}["SWORD"], snap,
    )
    biggest = max(snap.board, key=lambda c: (c.attack + c.health, c.attack))
    check("cible la plus grosse unité alliée", point == biggest.center, (point, description))
    check("équipement jouable", "SWORD" in [c.code for c in playable_cards(snap, pool)])

    vide = snapshot_with(hand_codes=["SWORD"])
    check("sans allié, aucune cible", actions.equipment_plan(vide.hand[0], vide)[0] is None)
    check("sans allié, non jouable", playable_cards(vide, pool) == [], playable_cards(vide, pool))
    reason = actions.rejection_reason(vide.hand[0], vide, pool, allow_spells=False)
    check("raison nommée", reason is not None and "équipement" in reason, reason)


def test_unknown_card_playable_once_cost_is_read():
    print("\nCoût lu à l'écran pour une carte inconnue")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["TOKEN_INCONNU"])
    card = snap.hand[0]
    pool = ManaPool(mana=10, spell_mana=0)

    check("carte vue mais inconnue", card.known is False)
    # Son coût de base vaut 0 : la jouer serait parier sur une donnée
    # absente, donc elle est écartée.
    check("coût de base à 0", card.base_cost == 0, card.base_cost)
    check("coût jugé inconnu", card.cost_is_known is False)
    check("écartée sans coût", playable_cards(snap, pool) == [], playable_cards(snap, pool))

    # Une fois le coût lu à l'écran, elle redevient jouable.
    card.cost_read = 4
    check("coût effectif = valeur lue", card.cost == 4, card.cost)
    check("coût jugé connu", card.cost_is_known is True)
    # Elle reste écartée si le type n'est pas jouable ; ici l'API ne donne
    # pas de type pour une carte inconnue, donc on vérifie la raison.
    reason = actions.rejection_reason(card, snap, pool, allow_spells=False)
    check("raison portée par le type, plus par le coût",
          reason is not None and "type" in reason, reason)


def costs_read_as(mapping):
    """
    Bouchon de lecture de la gemme de mana.

    `mapping` associe un code de carte au coût AFFICHÉ à l'écran, celui
    qu'on paie réellement. Le bouchon compte ses appels : c'est ce qui
    permet de vérifier que la relecture a bien lieu à chaque pose, et pas
    une seule fois au début du tour.
    """
    def stub(snapshot, *args, **kwargs):
        stub.calls += 1
        for card in snapshot.hand:
            if card.code in mapping:
                card.cost_read = mapping[card.code]
        return snapshot

    stub.calls = 0
    return stub


def with_screen_costs(mapping):
    """Contexte : la gemme affiche `mapping`, restauré à la sortie."""
    class _Scope:
        def __enter__(self):
            self.saved = actions.enrich_with_live_costs
            self.stub = costs_read_as(mapping)
            actions.enrich_with_live_costs = self.stub
            return self.stub

        def __exit__(self, *exc):
            actions.enrich_with_live_costs = self.saved
            return False

    return _Scope()


def test_screen_cost_beats_card_sets():
    print("\nLe coût affiché prime sur le coût imprimé")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_BIG"])       # Colosse, imprimé à 6
    card = snap.hand[0]
    pool = ManaPool(mana=3, spell_mana=0)

    check("écartée sur le coût imprimé", playable_cards(snap, pool) == [],
          playable_cards(snap, pool))

    # Réduction en jeu : la gemme affiche 2, on a 3 mana.
    card.cost_read = 2
    check("coût effectif = valeur affichée", card.cost == 2, card.cost)
    check("origine signalée", card.cost_is_live is True)
    check("écart mesuré", card.cost_gap == -4, card.cost_gap)
    check("jouable une fois la réduction lue",
          [c.code for c in playable_cards(snap, pool)] == ["UNIT_BIG"],
          playable_cards(snap, pool))

    # L'inverse compte autant : une majoration doit ÉCARTER une carte que
    # le coût imprimé rendait jouable. C'est le cas qui, sans lecture,
    # fait tenter une pose que le jeu refuse — et perdre un tour.
    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_B"])         # Ombre Fuyante, imprimée à 2
    card = snap.hand[0]
    check("jouable sur le coût imprimé",
          [c.code for c in playable_cards(snap, ManaPool(mana=2))] == ["UNIT_B"])
    card.cost_read = 5
    check("écartée quand la gemme affiche plus cher",
          playable_cards(snap, ManaPool(mana=2)) == [],
          playable_cards(snap, ManaPool(mana=2)))
    check("écart positif", card.cost_gap == 3, card.cost_gap)


def test_screen_cost_reorders_the_choice():
    print("\nLa réduction change la carte choisie")

    with_db(FULL_DB)
    # Imprimés : Colosse 6, Garde 3, Ombre 2. Avec 6 mana et rien de lu,
    # le bot pose le Colosse.
    snap = snapshot_with(hand_codes=["UNIT_BIG", "UNIT_A", "UNIT_B"])
    pool = ManaPool(mana=6, spell_mana=0)
    check("sans lecture : la plus chère imprimée",
          playable_cards(snap, pool)[0].code == "UNIT_BIG",
          [c.code for c in playable_cards(snap, pool)])

    # En jeu, le Colosse est réduit à 1 : ce n'est plus la carte la plus
    # chère, et le tri doit suivre le coût RÉEL, pas l'imprimé.
    {c.code: c for c in snap.hand}["UNIT_BIG"].cost_read = 1
    order = [c.code for c in playable_cards(snap, pool)]
    check("tri sur le coût réel", order[0] == "UNIT_A", order)


def test_play_hand_rereads_costs_at_each_play():
    print("\nCoûts relus à chaque pose")

    with_db(FULL_DB)
    # Le Colosse est imprimé à 6, affiché à 2 : avec 4 mana il est jouable.
    snap = snapshot_with(hand_codes=["UNIT_BIG"])
    after = snapshot_with(hand_codes=[], board_codes=["UNIT_BIG"])

    recorder = DragRecorder()
    original_drag, original_mana = actions.drag, actions.read_mana_pool
    actions.drag = recorder
    actions.read_mana_pool = lambda **_: ManaPool(mana=4, spell_mana=0)

    try:
        with with_screen_costs({"UNIT_BIG": 2}) as stub:
            played, _, log = play_hand(FakeReader([snap, after, after]), snap)
    finally:
        actions.drag, actions.read_mana_pool = original_drag, original_mana

    check("carte réduite effectivement posée",
          [c.code for c in played] == ["UNIT_BIG"], played)
    check("un geste de pose émis", len(recorder.drags) == 1, recorder.drags)
    # Une itération lit le mana ET les coûts : les deux changent en cours
    # de tour, il n'y a pas de raison d'en relire un et pas l'autre.
    check("lecture au moins une fois par itération", stub.calls >= 1, stub.calls)
    check("écart journalisé",
          any("6->2" in entry for entry in log.entries), log.entries)


def test_cost_reading_is_pruned():
    print("\nOn ne lit que ce qui peut changer la décision")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A", "GEAR_A", "SPELL_A", "TOKEN_INCONNU"])

    codes = [c.code for c in actions.cost_reading_candidates(snap)]
    check("unité lue", "UNIT_A" in codes, codes)
    check("équipement ignoré", "GEAR_A" not in codes, codes)
    check("sort ignoré sans --spells", "SPELL_A" not in codes, codes)
    # Une carte absente de card_sets n'a pas de type : `playable_cards` la
    # refuse là-dessus, pas sur son prix. Lire sa gemme ne la rendrait pas
    # jouable — autant ne pas payer l'OCR.
    check("carte inconnue ignorée", "TOKEN_INCONNU" not in codes, codes)

    with_spells = [c.code for c in actions.cost_reading_candidates(snap, allow_spells=True)]
    check("sort lu avec --spells", "SPELL_A" in with_spells, with_spells)

    skipped = [c.code for c in actions.cost_reading_candidates(snap, skip={"UNIT_A"})]
    check("carte mise de côté ignorée", "UNIT_A" not in skipped, skipped)


def test_base_costs_switch_restores_card_sets():
    print("\nRepli sur les coûts imprimés")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_BIG"])

    saved = actions.READ_SCREEN_COSTS
    actions.READ_SCREEN_COSTS = False
    try:
        with with_screen_costs({"UNIT_BIG": 2}) as stub:
            actions.refresh_costs(snap)
        check("aucune lecture d'écran", stub.calls == 0, stub.calls)
        check("coût imprimé conservé", snap.hand[0].cost == 6, snap.hand[0].cost)
    finally:
        actions.READ_SCREEN_COSTS = saved


def test_rejection_reason_names_the_cause():
    print("\nLe diagnostic nomme la cause")

    with_db(FULL_DB)
    pool = ManaPool(mana=1, spell_mana=0)
    snap = snapshot_with(hand_codes=["UNIT_A", "GEAR_A", "SPELL_A"])
    by_code = {c.code: c for c in snap.hand}

    reason = actions.rejection_reason(by_code["UNIT_A"], snap, pool, False)
    check("coût trop élevé nommé", "coût 3" in reason and "mana 1" in reason, reason)
    check("origine du coût nommée", "card_sets" in reason, reason)

    # Le même refus, mais sur un coût LU : le diagnostic doit dire d'où
    # vient le chiffre, sinon on ne sait pas s'il faut incriminer la base
    # de cartes ou la calibration de la gemme.
    by_code["UNIT_A"].cost_read = 7
    reason = actions.rejection_reason(by_code["UNIT_A"], snap, pool, False)
    check("coût lu nommé comme tel", "coût 7" in reason and "écran" in reason, reason)
    by_code["UNIT_A"].cost_read = None

    reason = actions.rejection_reason(by_code["GEAR_A"], snap, pool, False)
    check("équipement nommé", "équipement" in reason, reason)

    reason = actions.rejection_reason(by_code["SPELL_A"], snap, pool, False)
    check("sort sans --spells nommé", "--spells" in reason, reason)

    # Une carte du banc n'est pas en main : c'est LE cas que `plan` ne
    # montrait pas, et qui explique un « rien à jouer » incompréhensible.
    board = snapshot_with(board_codes=["UNIT_A"])
    reason = actions.rejection_reason(board.board[0], board, ManaPool(mana=10), False)
    check("mauvaise zone nommée", "pas classée en main" in reason, reason)

    # Et une carte réellement jouable ne produit aucune raison.
    rich = snapshot_with(hand_codes=["UNIT_A"])
    check("carte jouable -> aucune raison",
          actions.rejection_reason(rich.hand[0], rich, ManaPool(mana=10), False) is None)


def test_board_limit():
    print("\nLimite du banc")

    with_db(FULL_DB)
    pool = ManaPool(mana=10, spell_mana=0)

    snap = snapshot_with(hand_codes=["UNIT_A"], board_codes=["UNIT_A"] * 4,
                         attack_codes=["UNIT_B"] * 2)
    check("rangée d'attaque comptée dans le banc", free_board_slots(snap) == 0,
          (len(snap.board), len(snap.attack_row)))
    check("banc plein -> rien de jouable", playable_cards(snap, pool) == [])

    # Une carte qui invoque un allié supplémentaire a besoin de 2 places.
    snap = snapshot_with(hand_codes=["UNIT_TWIN", "UNIT_A"], board_codes=["UNIT_A"] * 5)
    names = [c.name for c in playable_cards(snap, pool)]
    check("1 place libre", free_board_slots(snap) == 1, free_board_slots(snap))
    check("carte à 2 corps écartée", "Jumeaux" not in names, names)
    check("carte à 1 corps gardée", "Garde de Fer" in names, names)


def test_grab_point_is_on_screen():
    print("\nPoint de saisie")

    with_db(FULL_DB)
    snap = snapshot_with(hand_codes=["UNIT_A"])
    card = snap.hand[0]
    left, top, right, bottom = card.box
    centre_y = (top + bottom) // 2

    # Le cœur du problème : une carte en main dépasse sous l'écran, donc
    # son centre géométrique est hors cadre et cliquer là ne touche rien.
    check("le centre de la carte est hors écran", centre_y > WINDOW.height, centre_y)
    check("le point de saisie est dans l'écran", 0 <= card.grab_point[1] < WINDOW.height,
          card.grab_point)
    check("le point de saisie est sur la carte", top <= card.grab_point[1] <= bottom,
          (top, card.grab_point[1], bottom))

    target = actions.drop_point(card, snap.window)
    check("dépôt à la verticale de la saisie", target[0] == card.grab_point[0], target)
    check("dépôt au-dessus de la saisie", target[1] < card.grab_point[1], target)
    # Le dépôt vise la rangée d'ATTAQUE, pas le banc : c'est la zone que
    # le client accepte pour poser une carte.
    low, high = game_state.zone_band("attack")
    ratio_from_bottom = 1.0 - target[1] / WINDOW.height
    check("dépôt dans la bande d'attaque", low < ratio_from_bottom < high,
          (ratio_from_bottom, low, high))
    check("dépôt hors de la bande du banc",
          not (game_state.zone_band("board")[0] < ratio_from_bottom
               < game_state.zone_band("board")[1]),
          ratio_from_bottom)


def test_play_card_verifies_result():
    print("\nVérification de la pose")

    with_db(FULL_DB)
    before = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
    after_ok = snapshot_with(hand_codes=["UNIT_B"], board_codes=["UNIT_A"])
    card = next(c for c in before.hand if c.code == "UNIT_A")

    recorder = DragRecorder()
    original_drag = actions.drag
    actions.drag = recorder
    try:
        success, latest = play_card(FakeReader([after_ok]), before, card)
        check("pose réussie détectée", success is True)
        check("un seul geste effectué", len(recorder.drags) == 1, recorder.drags)
        check("carte absente de la main après", len(latest.hand) == 1, latest.hand)

        # Échec : la main ne change pas. Deux tentatives, puis abandon —
        # sans quoi le bot rejouerait le même geste indéfiniment.
        unchanged = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
        recorder = DragRecorder()
        actions.drag = recorder
        success, _ = play_card(
            FakeReader([unchanged, unchanged]), before, card, attempts=2
        )
        check("pose ratée détectée", success is False)
        check("exactement 2 tentatives", len(recorder.drags) == 2, len(recorder.drags))
    finally:
        actions.drag = original_drag


def test_the_hand_is_reread_between_two_plays():
    """
    LA MAIN SE RECENTRE : ON RELIT AVANT DE SAISIR LA SUIVANTE.

    Signalé par Ewan le 22/08/2026 : « lorsqu'une carte est jouée, les
    autres se déplacent ». Les coordonnées d'un `BoardCard` sont figées à
    la lecture ; celles d'après la pose valaient pour une main qui
    n'existe plus, et la saisie suivante partait sur la place de la
    voisine.

    C'est la même règle que pour le banc entre deux engagements
    (`relocate_card`) : on décide sur un état cohérent, on VISE sur des
    positions relues.
    """
    print("\nLa main est relue entre deux poses")

    with_db(FULL_DB)
    avant = hand_at([("UNIT_BIG", 21), ("UNIT_A", 22)])
    # Le Colosse est posé, mais LA MAIN N'A PAS ENCORE BOUGÉ : c'est le
    # battement qui précède l'animation. Deux lectures y montrent les
    # mêmes coordonnées, donc `wait_until_settled` conclut « le plateau
    # est immobile » et `play_card` rend un état dont les positions sont
    # déjà condamnées. C'est là que le bogue se logeait.
    perime = scene([("UNIT_A", 22, EN_MAIN, 640), ("UNIT_BIG", 21, 0.150, 400)])
    # Puis la main se recentre : le Garde a changé de place.
    recentre = scene([("UNIT_A", 22, EN_MAIN, 900), ("UNIT_BIG", 21, 0.150, 400)])
    # Et le Garde est posé à son tour.
    fini = scene([("UNIT_BIG", 21, 0.150, 400), ("UNIT_A", 22, 0.150, 560)])

    ancienne = next(c for c in perime.hand if c.code == "UNIT_A").grab_point
    nouvelle = next(c for c in recentre.hand if c.code == "UNIT_A").grab_point
    check("les deux places diffèrent bien", ancienne != nouvelle,
          (ancienne, nouvelle))
    # Trois scènes fabriquées depuis `avant` : au-delà de AIM_MAX_AGE
    # (temps RÉEL, cf. `test_clock`) `play_card` relirait la main.
    avant.taken_at = time.time()

    recorder = DragRecorder()
    original_drag, original_mana = actions.drag, actions.read_mana_pool
    actions.drag = recorder
    actions.read_mana_pool = lambda **_: ManaPool(mana=10, spell_mana=0)
    try:
        # Deux lectures périmées — celles que consomme `play_card` —, puis
        # la main recentrée.
        played, _, _ = play_hand(
            FakeReader([perime, perime, recentre, recentre, fini]),
            avant, max_plays=2,
        )
    finally:
        actions.drag, actions.read_mana_pool = original_drag, original_mana

    check("les deux cartes sont posées",
          [c.code for c in played] == ["UNIT_BIG", "UNIT_A"], played)
    check("deux gestes", len(recorder.drags) == 2, recorder.drags)
    check("la seconde saisie vise la place RELUE",
          len(recorder.drags) > 1 and recorder.drags[1][0] == nouvelle,
          (recorder.drags, nouvelle))
    check("et pas la place d'avant le recentrage",
          len(recorder.drags) > 1 and recorder.drags[1][0] != ancienne,
          ancienne)


def test_play_hand_stops_on_failure():
    print("\nBoucle de pose")

    with_db(FULL_DB)
    stuck = snapshot_with(hand_codes=["UNIT_A"])

    recorder = DragRecorder()
    original_drag, original_mana = actions.drag, actions.read_mana_pool
    actions.drag = recorder
    actions.read_mana_pool = lambda **_: ManaPool(mana=10, spell_mana=0)
    try:
        # La main ne change jamais : la pose échoue systématiquement.
        played, _, _ = play_hand(FakeReader([stuck] * 20), stuck, max_plays=8)
        check("aucune carte posée", played == [], played)
        # 2 tentatives pour la carte, puis mise de côté : la boucle ne
        # doit pas consommer ses 8 itérations sur la même carte.
        check("abandon après mise de côté", len(recorder.drags) == 2, len(recorder.drags))
    finally:
        actions.drag, actions.read_mana_pool = original_drag, original_mana


def test_a_failed_card_stays_aside_for_the_whole_round():
    """
    06/09/2026, 07:25 → 07:31 : « Buhru Lookout toujours en main » ×14. Chaque
    pose ratée rendait la main, la boucle revenait avec un `failed` vide et
    refaisait la même pose. Avec `carry`, la carte reste de côté d'un appel
    à l'autre tant que le mana ne remonte pas ; un round plus tard (mana
    plus haut), elle redevient jouable.
    """
    print("\nUne pose ratée met la carte de côté pour tout le round")

    with_db(FULL_DB)
    stuck = snapshot_with(hand_codes=["UNIT_A"])
    recorder = DragRecorder()
    original_drag, original_mana = actions.drag, actions.read_mana_pool
    actions.drag = recorder
    mana = {"v": 7}
    actions.read_mana_pool = lambda **_: ManaPool(mana=mana["v"], spell_mana=0)
    carry = {"codes": set(), "mana": None}
    try:
        play_hand(FakeReader([stuck] * 20), stuck, max_plays=8, carry=carry)
        check("deux tentatives, puis mise de côté", len(recorder.drags) == 2, len(recorder.drags))
        check("   la carte est dans la mémoire du round", "UNIT_A" in carry["codes"], carry)

        # Même round (mana inchangé) : la boucle revient, rien n'est retenté.
        recorder.drags.clear()
        _, _, log = play_hand(FakeReader([stuck] * 20), stuck, max_plays=8, carry=carry)
        check("même round : aucun nouveau glissé", recorder.drags == [], recorder.drags)

        # Round suivant : le mana remonte, la carte est de nouveau essayée.
        mana["v"] = 8
        _, _, log = play_hand(FakeReader([stuck] * 20), stuck, max_plays=8, carry=carry)
        check("nouveau round : la carte est retentée", len(recorder.drags) == 2, len(recorder.drags))
        check("   et le journal le dit", any("Nouveau round" in e for e in log.entries), log.entries)

        # Sans `carry` : comportement d'avant, mise de côté pour cet appel seulement.
        recorder.drags.clear()
        play_hand(FakeReader([stuck] * 20), stuck, max_plays=8)
        play_hand(FakeReader([stuck] * 20), stuck, max_plays=8)
        check("sans carry : retentée à chaque appel", len(recorder.drags) == 4, len(recorder.drags))
    finally:
        actions.drag, actions.read_mana_pool = original_drag, original_mana


def test_grab_point_avoids_the_overlapping_neighbour():
    """
    Main pleine (trace du 06/09/2026, 9 cartes) : 175 px de large, 99 px
    d'espacement, la voisine de DROITE recouvre les trois quarts de la
    carte. Le centre géométrique (à 11 px de la voisine) attrapait « The
    List » à la place de Buhru Lookout. On vise le milieu de la partie
    visible ; la dernière carte, que rien ne recouvre, garde son centre.
    """
    print("\nSaisie dans une main pleine : le milieu de la partie visible")

    with_db(FULL_DB)
    rects = list(nexus_rects())
    codes = ["UNIT_A", "UNIT_B", "SPELL_A", "UNIT_A", "UNIT_B", "SPELL_A", "UNIT_A", "UNIT_B", "SPELL_A"]
    for i, code in enumerate(codes):
        rects.append(rect_at_ratio(0.029, code=code, card_id=100 + i, height=245, width=175, x=478 + 99 * i))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    hand = state_reader().snapshot().hand
    check("neuf cartes lues", len(hand) == 9, len(hand))
    first, last = hand[0], hand[-1]
    left = first.box[0]
    check("première carte : saisie dans sa moitié visible (bord gauche + ~49 px)",
          left < first.grab_point[0] < left + 99 and first.grab_point[0] < hand[1].box[0] - 20,
          (first.grab_point, first.box, hand[1].box))
    check("dernière carte : centre géométrique",
          last.grab_point[0] == (last.box[0] + last.box[2]) // 2, (last.grab_point, last.box))

    # Main aérée (pas de recouvrement) : rien ne change.
    aeree = hand_at([("UNIT_A", 21), ("UNIT_B", 22)], step=300)
    c = aeree.hand[0]
    check("sans recouvrement : centre géométrique",
          c.grab_point[0] == (c.box[0] + c.box[2]) // 2 and c.visible_right is None, (c.grab_point, c.box))


def test_cancel_uses_a_left_click_only():
    print("\nL'annulation est un clic droit")

    import pyautogui
    import gestures
    events = []
    # `right_click`/`click` vivent dans gestures.py : c'est là que `move`
    # se résout. Le nom `actions.move` n'est qu'une réexportation.
    saved = (pyautogui.click, gestures.move, getattr(pyautogui, "press", None))

    pyautogui.click = lambda *a, **k: events.append(("click", k.get("button", "left")))
    pyautogui.press = lambda *a, **k: events.append(("press", a))
    gestures.move = lambda *a, **k: None
    try:
        actions.cancel_pending_action(WINDOW)
        # Précision d'Ewan (02/09/2026) : c'est le CLIC DROIT qui annule.
        # Un seul, jamais de touche clavier.
        check("un seul clic émis", len(events) == 1, events)
        check("clic droit", events[0] == ("click", "right"), events)
        check("aucune touche envoyée",
              not any(e[0] == "press" for e in events), events)
        # Le repli clic gauche reste disponible.
        events.clear()
        actions.CANCEL_WITH_LEFT_CLICK = True
        try:
            actions.cancel_pending_action(WINDOW)
        finally:
            actions.CANCEL_WITH_LEFT_CLICK = False
        check("repli : clic gauche", events == [("click", "left")], events)
    finally:
        pyautogui.click, gestures.move = saved[0], saved[1]
        if saved[2] is not None:
            pyautogui.press = saved[2]


def test_cancel_point_is_calibratable():
    print("\nZone d'annulation calibrable")

    saved = actions.load_calibration
    actions.load_calibration = lambda: {}
    try:
        check("repli sur la valeur de départ",
              actions.cancel_point_ratio() == actions.CANCEL_POINT_RATIO,
              actions.cancel_point_ratio())
        check("non calibrée signalée", actions.cancel_is_calibrated() is False)
    finally:
        actions.load_calibration = saved

    actions.load_calibration = lambda: {actions.CANCEL_CALIBRATION_KEY: [0.42, 0.11]}
    try:
        check("valeur calibrée utilisée",
              actions.cancel_point_ratio() == (0.42, 0.11),
              actions.cancel_point_ratio())
        check("calibrée signalée", actions.cancel_is_calibrated() is True)
    finally:
        actions.load_calibration = saved


def test_drag_always_releases_the_button():
    print("\nLe bouton est toujours relâché")

    import pyautogui
    import gestures
    events = []
    # `drag` vit dans gestures.py depuis le 05/09/2026 : c'est LÀ que `move`
    # se résout, pas dans actions (qui ne fait que réexporter le nom).
    saved = (pyautogui.mouseDown, pyautogui.mouseUp, gestures.move)

    def boom(*a, **k):
        # Le fail-safe se déclenche pendant le déplacement : c'est le
        # geste d'arrêt d'urgence de l'utilisateur.
        if events and events[-1] == "down":
            raise RuntimeError("failsafe")

    pyautogui.mouseDown = lambda *a, **k: events.append("down")
    pyautogui.mouseUp = lambda *a, **k: events.append("up")
    gestures.move = boom
    try:
        try:
            actions.drag((10, 10), (20, 20))
        except RuntimeError:
            pass
        # Sans le `finally`, la souris resterait enfoncée avec une carte
        # accrochée au curseur, au pire moment possible.
        check("bouton relâché malgré l'interruption", events == ["down", "up"], events)
    finally:
        pyautogui.mouseDown, pyautogui.mouseUp, gestures.move = saved


def test_spell_needs_a_target_to_be_played():
    print("\nUn sort n'est jouable que s'il a une cible")

    with_db(ALL_CARDS)
    pool = ManaPool(mana=10, spell_mana=3)

    # Éclair = « Deal 2 to an enemy ». Sans ennemi sur le plateau, le
    # lancer laisserait le client à attendre un clic impossible.
    alone = snapshot_with(hand_codes=["UNIT_A", "SPELL_A"])
    names = [c.name for c in playable_cards(alone, pool, allow_spells=True)]
    check("sans ennemi, sort écarté", "Éclair" not in names, names)
    check("unités toujours jouables", "Garde de Fer" in names, names)

    # Avec une cible valable, il devient jouable.
    with_enemy = blocking_snapshot(["BRUTE"], ["SMALL"])
    hand = snapshot_with(hand_codes=["SPELL_A"])
    object.__setattr__(with_enemy, "zones", {**with_enemy.zones, "hand": hand.hand})
    names = [c.name for c in playable_cards(with_enemy, pool, allow_spells=True)]
    check("avec un ennemi, sort jouable", "Éclair" in names, names)

    # Le paramètre reste respecté, et le verrou global aussi.
    names = [c.name for c in playable_cards(with_enemy, pool, allow_spells=False)]
    check("paramètre allow_spells respecté", "Éclair" not in names, names)

    saved = actions.SPELLS_ENABLED
    actions.SPELLS_ENABLED = False
    try:
        names = [c.name for c in playable_cards(with_enemy, pool, allow_spells=True)]
        check("verrou global coupe tout", "Éclair" not in names, names)
    finally:
        actions.SPELLS_ENABLED = saved


def test_restrictions_levees():
    """
    Le mode PAR DÉFAUT : tout ce qui est payable est tenté.

    Ce test est le miroir exact des refus vérifiés ailleurs dans ce
    fichier — mêmes cartes, verdict inverse. C'est voulu : la question
    « qu'est-ce que lever les restrictions change au juste » doit avoir
    une réponse lisible d'un seul coup d'œil.
    """
    print("\nRestrictions levées (mode par défaut)")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **HAND_POWER_CARDS})
        pool = ManaPool(mana=10, spell_mana=3)

        # Une main de tout ce que le mode prudent écartait : un sort dont
        # la cible n'existe pas sur ce plateau, un équipement sans allié à
        # équiper, une carte absente de card_sets, une unité dont le
        # « Play: » ouvre un Manifest, et un sort à choix multiple.
        main = ["SPELL_A", "SWORD", "TOKEN_INCONNU", "MANIFEST_UNIT", "SPELL_REFUSED"]
        snap = snapshot_with(hand_codes=main)
        codes = [c.code for c in playable_cards(snap, pool)]
        # CHANGÉ LE 08/11/2026, pour la MÊME raison que l'équipement
        # ci-dessous, et un an de logs plus tard. Éclair dit « Deal 2 to
        # an enemy » : sans ennemi, le jeu attend un clic qui n'a nulle
        # part où aller. Mesuré dans `logs/` : 25 poses lancées en
        # sachant qu'il n'y avait aucune cible, dont 13 figées en
        # « toujours sur la pile après validation », 23,3 s chacune
        # (303 s), et le tour rendu sans être terminé. Voir
        # `test_un_sort_dont_la_cible_ne_peut_pas_exister_nest_pas_lance`.
        check("sort sans cible en jeu : écarté", "SPELL_A" not in codes, codes)
        # Et le miroir, comme pour l'équipement : un ennemi, et il repart.
        avec_ennemi = main_et_plateau(main, ennemis=["UNIT_B"])
        codes_ennemi = [c.code for c in playable_cards(avec_ennemi, pool)]
        check("   mais avec un ennemi : tenté", "SPELL_A" in codes_ennemi,
              codes_ennemi)
        # CHANGÉ LE 05/11/2026 — et c'est un fait de jeu, pas un
        # assouplissement. « Tenté » se défendait tant que l'essai ne
        # coûtait qu'un geste. Mesuré en partie : The Darkin Lodestone
        # tentée HUIT fois dans un même combat (19:24 → 19:38), banc vide
        # à chaque round, ~11 s perdues par tentative. L'annulation
        # rattrape bien — il n'y a pas de blocage — mais elle ne rend pas
        # le temps. `CLAUDE.md` garde « la disponibilité d'une carte à
        # désigner » dans les DEUX modes : sans allié, il n'y a personne
        # à désigner.
        check("équipement sans allié : écarté, personne à désigner",
              "SWORD" not in codes, codes)
        # Et le miroir, pour que la règle soit lisible : dès qu'un allié
        # est là, il redevient jouable.
        avec_allie = snapshot_with(hand_codes=["SWORD"], board_codes=["UNIT_A"])
        check("   mais avec un allié : tenté",
              "SWORD" in [c.code for c in playable_cards(avec_allie, pool)],
              [c.code for c in playable_cards(avec_allie, pool)])
        check("carte absente de card_sets : tentée", "TOKEN_INCONNU" in codes, codes)

        # CE QUE LA LEVÉE NE DONNE PAS : LA CAPACITÉ DE FERMER UNE FENÊTRE.
        # Ces deux-là étaient tentées, au motif que l'annulation
        # rattraperait. Elle ne rattrape rien — un choix de carte est
        # obligatoire, le clic sur une zone vide ne le referme pas, et la
        # partie reste figée jusqu'à ce que la boucle abandonne. C'est le
        # blocage du 22/08/2026. Elles rejoignent donc le mana et la place
        # sur le banc : des faits, pas des prudences.
        check("sort à choix multiple : toujours écarté",
              "SPELL_REFUSED" not in codes, codes)
        # Manifest, lui, a changé de camp le 02/09/2026 : sa fenêtre se
        # lit à l'écran (resolve_card_choice), donc l'unité est tentée.
        check("« Play: Discard 1 to Manifest » : désormais tenté",
              "MANIFEST_UNIT" in codes, codes)

        # Le verrou `--spells` ne commande plus rien : c'était une
        # restriction, elle est levée comme les autres. Il faut un ennemi
        # pour le montrer, sinon c'est l'absence de cible qui écarte le
        # sort et le test ne prouverait plus rien.
        sans_spells = [c.code for c in playable_cards(avec_ennemi, pool, allow_spells=False)]
        check("--spells sans effet", "SPELL_A" in sans_spells, sans_spells)

        # Et le diagnostic dit la même chose que la décision : rien à
        # reprocher aux deux premières, un motif nommé pour le sort sans
        # cible et pour les deux fenêtres.
        raisons = {c.code: actions.rejection_reason(c, snap, pool, allow_spells=False)
                   for c in snap.hand}
        check("aucune raison pour ce qui est tenté",
              raisons["TOKEN_INCONNU"] is None, raisons)
        # CE TEST SE CONTREDISAIT LUI-MÊME, ET DEPUIS LE 05/11.
        # Trente lignes plus haut il vérifie « équipement sans allié :
        # écarté » — puis il exigeait ici que l'EXPLICATION réponde None
        # pour la même carte, c'est-à-dire « rien à lui reprocher ».
        # `rejection_reason` n'avait en effet aucun test d'équipement, et
        # le test gravait ce trou au lieu de le voir. Tant que `_describe`
        # tenait sa propre liste de motifs, personne n'en souffrait ;
        # depuis qu'il délègue (09/11), `python actions.py plan` écrivait
        # JOUABLE. Le motif est nommé, comme pour le sort sans cible.
        check("équipement sans porteur : motif nommé, pas None",
              raisons["SWORD"] == "équipement : aucun allié en jeu",
              raisons["SWORD"])
        check("sort sans cible : motif nommé",
              raisons["SPELL_A"] == "sort : aucun ennemi en jeu", raisons["SPELL_A"])
        check("Manifest : rien à reprocher", raisons["MANIFEST_UNIT"] is None,
              raisons["MANIFEST_UNIT"])
        check("choix multiple : motif nommé",
              raisons["SPELL_REFUSED"] and "choix" in raisons["SPELL_REFUSED"],
              raisons["SPELL_REFUSED"])

        # ---- ce qui subsiste : le mana ---------------------------------
        # Un ennemi sur le plateau, sinon c'est l'absence de cible qui
        # écarterait Éclair et le mana n'aurait rien décidé.
        cher = main_et_plateau(["UNIT_BIG", "SPELL_A"], ennemis=["UNIT_B"])
        codes = [c.code for c in playable_cards(cher, ManaPool(mana=2, spell_mana=0))]
        check("le mana décide encore", codes == ["SPELL_A"], codes)
        raison = actions.rejection_reason(
            next(c for c in cher.hand if c.code == "UNIT_BIG"),
            cher, ManaPool(mana=2, spell_mana=0), allow_spells=False,
        )
        check("raison du refus : le coût", raison is not None and "coût" in raison, raison)

        # ---- ce qui subsiste : la place sur le banc ---------------------
        # Même précaution : un ennemi, pour que le sort ne soit écarté
        # que par ce qu'on teste ici.
        plein = main_et_plateau(["UNIT_A", "SPELL_A"], banc=["UNIT_A"] * 4,
                                attaque=["UNIT_B"] * 2, ennemis=["UNIT_B"])
        codes = [c.code for c in playable_cards(plein, pool)]
        check("banc plein : unité écartée", "UNIT_A" not in codes, codes)
        check("banc plein : sort toujours jouable", "SPELL_A" in codes, codes)

        # ---- la lecture des coûts suit ----------------------------------
        # Une carte absente de card_sets n'est jouable QUE si son prix est
        # lu à l'écran : il faut donc qu'elle fasse partie des cartes dont
        # on lit la gemme, sans quoi le mana la refuserait sur un coût nul
        # au premier tour où il en manque.
        lus = [c.code for c in actions.cost_reading_candidates(snap)]
        check("toutes les cartes voient leur coût lu", set(lus) == set(main), lus)
    finally:
        actions.CARD_RESTRICTIONS = saved


# ============================================================
# UNE CIBLE QUI NE PEUT PAS EXISTER (08/11/2026)
# ============================================================

# LES SORTS QUI ONT FIGÉ UN TOUR, textes réels de card_sets — ce sont les
# codes et les libellés que le bot a lus en partie.
SORTS_SANS_CIBLE = {
    "MINIMORPH": {           # 05BC001
        "name": "Minimorph", "cost": 6, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "descriptionRaw": "Transform a unit into a 3|3 Mini-Minitee and Silence it.",
    },
    "QUICKEN": {             # 05BC180
        "name": "Quicken", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "Recall a unit with 3 or less Power.",
    },
    "SPIRIT_JOURNEY": {      # 04SI002
        "name": "Spirit Journey", "cost": 5, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "descriptionRaw": "Kill a unit, then revive it.",
    },
    "CALIBRUM": {            # 03MT217T8
        "name": "Calibrum", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "Deal 3 to a follower. Phase Severum or Gravitum.",
    },
    # ---- les témoins, qui doivent RESTER jouables ----------------------
    "PIOCHE": {              # aucun clic : rien à désigner, rien à refuser
        "name": "Pioche", "cost": 1, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "descriptionRaw": "Draw a card.",
    },
    "FROSTBITE2": {          # pluriel COMPTÉ : le jeu se contente d'un ennemi
        "name": "Vents mordants", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "Frostbite 2 enemies.",
    },
    "COSMIC": {              # 06BC044 : deux cibles STRICTES
        "name": "Lien cosmique", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "Deal 2 to an enemy and Stun another.",
    },
    "BEWITCH": {             # effet INCONNU sur « a unit » : il a un repli
        "name": "Bewitch", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "Bewitch a unit.",
    },
    # UN SORT LENT, pour vérifier que la VITESSE ne ressort jamais sous
    # un nom qui promet une histoire de cible. `spellSpeedRef` est ce que
    # `can_cast_now` lit — les `keywords` ci-dessus ne lui disent rien.
    "LENT": {
        "name": "Sort lent", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "spellSpeedRef": "Slow",
        "descriptionRaw": "Kill an enemy.",
    },
}


def main_et_plateau(main, banc=(), ennemis=(), attaque=()):
    """
    Main, notre banc, notre rangée d'attaque, et le BANC adverse.

    C'est `snapshot_with` AVEC un camp d'en face — ce que celui-ci ne
    sait pas faire, et dont tout sort ciblé a besoin.

    Les ennemis vont au banc (ratio 0.800) et non dans la rangée
    d'attaque : un sort lent ne se lance pas pendant un combat
    (`spells.can_cast_now`), et ces tests-ci portent sur les cibles, pas
    sur la vitesse.
    """
    rects, card_id = list(nexus_rects()), 700
    for index, code in enumerate(main):
        card_id += 1
        rects.append(rect_at_ratio(0.029, code=code, card_id=card_id,
                                   height=330, x=400 + 140 * index))
    for index, code in enumerate(banc):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=400 + 130 * index))
    for index, code in enumerate(attaque):
        card_id += 1
        rects.append(rect_at_ratio(0.320, code=code, card_id=card_id, x=400 + 130 * index))
    for index, code in enumerate(ennemis):
        card_id += 1
        rects.append(rect_at_ratio(0.800, code=code, card_id=card_id,
                                   local=False, x=400 + 130 * index))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


def test_un_sort_dont_la_cible_ne_peut_pas_exister_nest_pas_lance():
    """
    LE PLATEAU N'OFFRE AUCUN POINT À CLIQUER : ON GARDE LA CARTE.

    Mesuré dans `logs/` : 25 fois le bot a posé une carte en SACHANT
    qu'aucune cible n'existait (« restrictions levées, on tente et on
    annulera »), et 13 de ces poses ont fini en « toujours sur la pile
    après validation », 23,3 s perdues chacune, le tour rendu sans être
    terminé. C'est le même raisonnement que l'équipement sans porteur
    (05/11) : l'annulation rattrape, mais elle ne rend pas le temps.
    """
    print("\nUn sort dont la cible ne peut pas exister n'est pas lancé")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **SORTS_SANS_CIBLE})
        pool = ManaPool(mana=10, spell_mana=3)
        main = ["MINIMORPH", "QUICKEN", "SPIRIT_JOURNEY", "CALIBRUM", "PIOCHE"]

        # Un banc à NOUS, aucun ennemi. Les quatre sorts sont néfastes :
        # `spells.choose_target` ne regarde que le camp adverse, et rend
        # « aucun ennemi en jeu ».
        sans_ennemi = main_et_plateau(main, banc=["UNIT_A"])
        codes = [c.code for c in playable_cards(sans_ennemi, pool)]
        for code in ("QUICKEN", "SPIRIT_JOURNEY", "CALIBRUM"):
            check(f"{code} : écarté, aucune cible sur le plateau",
                  code not in codes, codes)
        # Minimorph est le cas le plus coûteux du relevé (7 poses figées
        # le 06/09) mais son classement dépend de `spells.py` : selon la
        # lecture de « Transform ... and Silence it », elle est refusée
        # pour deux cibles ou pour absence d'ennemi. Écartée dans les deux
        # cas — c'est tout ce qu'on lui demande ici.
        check("Minimorph : écartée", "MINIMORPH" not in codes, codes)
        check("un sort qui ne clique rien reste jouable",
              "PIOCHE" in codes, codes)

        # LE MIROIR : un ennemi arrive, les sorts repartent.
        avec_ennemi = main_et_plateau(main, banc=["UNIT_A"], ennemis=["VANILLA33"])
        codes = [c.code for c in playable_cards(avec_ennemi, pool)]
        for code in ("QUICKEN", "SPIRIT_JOURNEY", "CALIBRUM"):
            check(f"   {code} : tenté dès qu'un ennemi est là",
                  code in codes, codes)

        # ---- ce qu'il ne faut PAS refuser -------------------------------
        # « Frostbite 2 enemies » face à UN seul ennemi : le jeu prend ce
        # qu'il y a (invariant du 02/09). « Deal 2 to an enemy and Stun
        # another » en réclame deux pour de bon, mais `spell_is_castable`
        # rend quand même la cible trouvée, et ce clic-là peut résoudre le
        # sort (invariant du 26/08) : un point à cliquer, on tente.
        un_seul = main_et_plateau(["FROSTBITE2", "COSMIC", "BEWITCH"],
                                  ennemis=["VANILLA33"])
        codes = [c.code for c in playable_cards(un_seul, pool)]
        check("pluriel compté : un ennemi suffit", "FROSTBITE2" in codes, codes)
        check("deux cibles strictes, une seule trouvée : toujours tenté",
              "COSMIC" in codes, codes)
        # Effet INCONNU sur « a unit », sans allié : `choose_target` se
        # replie sur un ennemi (06/09). Un repli EST une cible.
        check("effet inconnu sans allié : le repli compte comme une cible",
              "BEWITCH" in codes, codes)

        # Et à ZÉRO ennemi, les deux premiers tombent — y compris le
        # pluriel souple, qui a besoin d'au moins une cible.
        aucun = main_et_plateau(["FROSTBITE2", "COSMIC", "BEWITCH"], banc=["UNIT_A"])
        codes = [c.code for c in playable_cards(aucun, pool)]
        check("pluriel compté sans aucun ennemi : écarté",
              "FROSTBITE2" not in codes, codes)
        check("deux cibles, zéro trouvée : écarté", "COSMIC" not in codes, codes)
        # Bewitch, elle, a un allié : son cadeau a une cible.
        check("   mais l'effet inconnu garde son allié", "BEWITCH" in codes, codes)

        # ---- la vitesse n'est pas une affaire de cible -------------------
        # `spell_is_castable` refuse AUSSI un sort lent pendant un
        # combat. Son motif ne doit jamais ressortir de `sort_sans_cible`,
        # qui promet par son nom de ne parler que de cibles — et dont le
        # motif part au journal sous ce nom-là. Mesuré sur la vraie base :
        # Dawn and Dusk, Shunpo et Guile rendaient « sort lent : combat en
        # cours ». Les appelants testent la vitesse d'abord, donc rien ne
        # change en décision : c'est la fonction qu'on empêche de tenir
        # par le seul ordre de ses appelants.
        en_combat = main_et_plateau(["LENT"], banc=["UNIT_A"], attaque=["UNIT_A"])
        lent = next(c for c in en_combat.hand if c.code == "LENT")
        check("le sort lent est bien bloqué par la vitesse",
              spells.can_cast_now(lent, en_combat)[0] is False,
              spells.can_cast_now(lent, en_combat))
        check("   et `sort_sans_cible` ne s'approprie pas ce motif",
              actions.sort_sans_cible(lent, en_combat) is None,
              actions.sort_sans_cible(lent, en_combat))
        # Hors combat, le même sort retrouve son vrai motif de cible.
        hors_combat = main_et_plateau(["LENT"], banc=["UNIT_A"])
        lent = next(c for c in hors_combat.hand if c.code == "LENT")
        check("   hors combat, c'est bien l'absence d'ennemi qui parle",
              actions.sort_sans_cible(lent, hors_combat) == "aucun ennemi en jeu",
              actions.sort_sans_cible(lent, hors_combat))

        # ---- la riposte passe par le même tri ---------------------------
        # `respond_to_stack` court-circuite exactement comme `play_hand`
        # (CLAUDE.md le dit), et il le fait via `response_options`, qui
        # est bâti sur `playable_cards` : le refus le suit tout seul.
        reponses = [c.code for c in actions.response_options(sans_ennemi, pool)]
        check("riposte : pas de sort sans cible",
              "SPIRIT_JOURNEY" not in reponses, reponses)
        reponses = [c.code for c in actions.response_options(avec_ennemi, pool)]
        check("   et il revient dès qu'il y a un ennemi",
              "SPIRIT_JOURNEY" in reponses, reponses)

        # ---- le diagnostic dit la même chose que la décision ------------
        raison = actions.rejection_reason(
            next(c for c in sans_ennemi.hand if c.code == "SPIRIT_JOURNEY"),
            sans_ennemi, pool, allow_spells=False,
        )
        check("motif nommé pour le journal",
              raison == "sort : aucun ennemi en jeu", raison)
        # Et `journal.py --ecartees` continue de le compter : le motif est
        # normalisable et rangé dans le CONTEXTE de la partie, pas dans le
        # backlog « ce que le bot ne sait pas jouer ».
        import journal
        motif = journal.normalize_reason(raison)
        check("motif rangé dans le contexte de la partie",
              journal.is_context_reason(motif), motif)
    finally:
        actions.CARD_RESTRICTIONS = saved


# ============================================================
# UN SUIVANT N'EST PAS UN CHAMPION (10/11/2026)
# ============================================================

# Textes RÉELS de card_sets, dont les deux relevées dans `logs/`.
SORTS_QUI_VISENT_UN_SUIVANT = {
    "BECKONING": {           # 98SB015, vue en jeu le 05/11/2026
        "name": "Beckoning Gaze", "cost": 8, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Focus"], "keywordRefs": ["Focus"],
        "spellSpeedRef": "Focus",
        "descriptionRaw": "Charm an enemy follower.",
    },
    "ARM_OF_LAW": {          # 99PZ120 : la forme nue, sans mention du camp
        "name": "Arm of the Law", "cost": 4, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 4 to a follower.",
    },
    # LE TÉMOIN : le MÊME effet sans le mot « follower ». Il doit rester
    # jouable face à un champion seul, sinon ce n'est pas la condition
    # qu'on teste mais le plateau.
    "DEGATS_NUS": {
        "name": "Dégâts nus", "cost": 4, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 4 to an enemy.",
    },
}


def test_un_sort_qui_vise_un_suivant_nest_pas_lance_sur_un_champion():
    """
    « CHARM AN ENEMY FOLLOWER » (Beckoning Gaze, 98SB015), relevé dans
    `logs/challenges_20261105_204758.log` :

        Lancement de Beckoning Gaze (AUTRE sur ennemi).
        Ciblage : Karma (5) 4/3 en (645, 180)
        Beckoning Gaze toujours sur la pile après validation.

    Karma est un CHAMPION, le sort ne vise que les SUIVANTS, et le jeu
    refusait le clic. Deux fois dans le même combat, ~23 s chacune.

    CE QUE CE TEST VERROUILLE, c'est la jonction : la condition lue dans
    `spells.py` doit arriver jusqu'à `playable_cards` ET jusqu'à
    `rejection_reason`, qui doivent répondre LA MÊME CHOSE — deux
    implémentations du même test finissent toujours par diverger, et
    c'est alors le diagnostic qui ment (09/11/2026).
    """
    print("\nUn sort qui vise un suivant n'est pas lancé sur un champion")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **SORTS_QUI_VISENT_UN_SUIVANT})
        pool = ManaPool(mana=10, spell_mana=3)
        main = ["BECKONING", "ARM_OF_LAW", "DEGATS_NUS"]

        # EN FACE, UN CHAMPION ET RIEN D'AUTRE : c'est exactement le
        # plateau du 05/11.
        champion_seul = main_et_plateau(main, ennemis=["CHAMPI"])
        codes = [c.code for c in playable_cards(champion_seul, pool)]
        check("Beckoning Gaze : écartée devant un champion seul",
              "BECKONING" not in codes, codes)
        check("« Deal 4 to a follower » aussi", "ARM_OF_LAW" not in codes, codes)
        check("   mais le même effet SANS la condition reste jouable",
              "DEGATS_NUS" in codes, codes)

        # LE DIAGNOSTIC DIT LA MÊME CHOSE QUE LA DÉCISION, et il NOMME
        # ce qui manque : « aucun ennemi en jeu » devant un plateau
        # adverse plein enverrait chercher le défaut ailleurs.
        raison = actions.rejection_reason(
            next(c for c in champion_seul.hand if c.code == "BECKONING"),
            champion_seul, pool, allow_spells=False,
        )
        check("motif nommé pour le journal",
              raison == "sort : aucun suivant en jeu", raison)

        # LE MIROIR : un suivant arrive, le sort repart — et il vise LE
        # SUIVANT, pas le champion, qui est pourtant le plus gros.
        avec_suivant = main_et_plateau(main, ennemis=["CHAMPI", "VANILLA33"])
        codes = [c.code for c in playable_cards(avec_suivant, pool)]
        check("   et il repart dès qu'un suivant est là",
              "BECKONING" in codes and "ARM_OF_LAW" in codes, codes)

        carte = next(c for c in avec_suivant.hand if c.code == "BECKONING")
        castable, plan, cibles, detail = actions.spell_is_castable(carte, avec_suivant)
        suivants = {c.center for c in avec_suivant.enemy_board if not c.is_champion}
        champions = {c.center for c in avec_suivant.enemy_board if c.is_champion}
        check("la cible visée est le suivant",
              castable and set(cibles) <= suivants, (cibles, detail))
        check("   et surtout pas le champion",
              not (set(cibles) & champions), (cibles, detail))
    finally:
        actions.CARD_RESTRICTIONS = saved


# ============================================================
# LE NEXUS ADVERSE EST UNE CIBLE (08/11/2026)
# ============================================================

# Textes RÉELS de card_sets. Les trois premiers offrent le nexus au clic,
# les trois derniers sont les témoins qui doivent rester écartés ou
# jouables sans rien cliquer.
SORTS_VERS_LE_NEXUS = {
    "SHOCK_BLAST": {         # 05PZ027
        "name": "Shock Blast", "cost": 4, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 3 to an enemy or the enemy Nexus, and 3 to another.",
    },
    "BARRAGE": {             # la forme à UN clic, 01PZ004 sans ses rebonds
        "name": "Barrage", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 3 to an enemy or the enemy Nexus.",
    },
    "SOLAR_SNARE": {         # 98PZ008 : « a unit or the enemy Nexus »
        "name": "Solar Snare", "cost": 5, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "spellSpeedRef": "Slow",
        "descriptionRaw": "Deal 1 to a unit or the enemy Nexus, and another, and another.",
    },
    "EBB": {                 # 05BW006 : c'est le JEU qui choisit
        "name": "Ebb", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Deal 2 randomly to an enemy or the enemy Nexus "
                          "and create a Flow in hand.",
    },
    "DEATHS_HAND": {         # 02NX008 : le nexus encaisse, il ne se clique pas
        "name": "Death's Hand", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 2 to an enemy and 1 to the enemy Nexus.",
    },
    "EBB_FLOW": {            # 05BW006T1 : le tir est au hasard, le SOIN se désigne
        "name": "Ebb and Flow", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Deal 2 randomly to an enemy or the enemy Nexus "
                          "and heal an ally or your Nexus 2.",
    },
    "NEXUS_SEUL": {          # aucun marqueur : rien à cliquer
        "name": "Décharge", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Deal 2 to the enemy Nexus.",
    },
}


def test_un_sort_qui_peut_frapper_le_nexus_nest_pas_ecarte():
    """
    CONTRE-ÉPREUVE DU CORRECTIF « SORT SANS CIBLE », AU NIVEAU D'ACTIONS.

    Le refus du matin (`sort_sans_cible`) est juste, mais il reposait sur
    `spells.choose_target`, qui ne donnait un repli sur le nexus qu'au
    `Targeting.ANYTHING`. Les sorts qui écrivent « an enemy OR the enemy
    Nexus » rendaient donc « aucun ennemi en jeu » et étaient écartés EN
    SILENCE, sur un plateau adverse vide — l'état même que `nexus_weight`
    et l'archétype « aggro » existent pour exploiter.

    Ce qui doit tenir des deux côtés de la frontière :
      - le nexus offert par le texte rend le sort jouable, et le point
        cliqué EST celui du nexus ;
      - un nexus AUTOMATIQUE (« and 1 to the enemy Nexus ») ne rend rien :
        le clic reste sur une unité, et sans unité on garde la carte ;
      - les trois sorts du relevé du 08/11 restent écartés.
    """
    print("\nUn sort qui peut frapper le nexus n'est pas écarté")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **SORTS_SANS_CIBLE, **SORTS_VERS_LE_NEXUS})
        pool = ManaPool(mana=10, spell_mana=3)
        main = ["BARRAGE", "SHOCK_BLAST", "SOLAR_SNARE", "EBB", "EBB_FLOW",
                "DEATHS_HAND", "NEXUS_SEUL", "QUICKEN", "SPIRIT_JOURNEY",
                "CALIBRUM"]

        sans_ennemi = main_et_plateau(main, banc=["UNIT_A"])
        codes = [c.code for c in playable_cards(sans_ennemi, pool)]
        # UN SEUL DE CES SORTS SE LANCE VRAIMENT SUR UN PLATEAU VIDE, et
        # ce n'est pas celui qu'on croit. « BARRAGE » est une forme à UN
        # clic qui N'EXISTE PAS dans la base : les six cartes que le
        # marqueur répare réclament toutes DEUX ou TROIS cibles. Face au
        # seul nexus, `choose_targets` n'en rend qu'une — le nexus ne se
        # clique pas deux fois — donc `spell_is_castable` rend False avec
        # un ciblage INCOMPLET.
        #
        # LA QUESTION EST TRANCHÉE DEPUIS LE 09/11/2026, par Ewan : le jeu
        # REFUSE, rien ne part. Il n'accepte pas de résoudre un sort avec
        # moins de cibles qu'il n'en annonce, et on ne peut pas envoyer
        # les trois tirs sur le nexus. Les laisser entrer dans
        # `playable_cards` revenait donc à payer ~23 s d'annulation par
        # tentative, sans aucune chance de gain — c'est maintenant
        # `sort_sans_cible` qui les écarte, sur un motif qui NOMME le
        # nexus plutôt que de dire « aucune cible », ce qui serait faux.
        check("BARRAGE (un seul clic) : le nexus adverse est une cible",
              "BARRAGE" in codes, codes)
        for code in ("SHOCK_BLAST", "SOLAR_SNARE"):
            carte = next(c for c in sans_ennemi.hand if c.code == code)
            castable, plan, cibles, pourquoi = actions.spell_is_castable(carte, sans_ennemi)
            check(f"   {code} : le ciblage est INCOMPLET "
                  f"({len(cibles)}/{plan.total_targets})",
                  castable is False and plan.total_targets > 1
                  and cibles == (sans_ennemi.enemy_nexus,),
                  (castable, cibles, pourquoi))
            check(f"   {code} : donc on ne le pose PAS (Ewan, 09/11)",
                  code not in codes, codes)
            raison = actions.rejection_reason(carte, sans_ennemi, pool, allow_spells=True)
            check(f"   {code} : et le motif nomme le nexus, pas une absence",
                  raison is not None and "nexus" in raison and "une fois" in raison,
                  raison)
        check("EBB : tir au hasard, jouable sans rien cliquer",
              "EBB" in codes, codes)
        check("NEXUS_SEUL : aucun marqueur, jouable", "NEXUS_SEUL" in codes, codes)
        check("DEATHS_HAND : le nexus encaisse, la cible reste une unité",
              "DEATHS_HAND" not in codes, codes)
        for code in ("QUICKEN", "SPIRIT_JOURNEY", "CALIBRUM"):
            check(f"   {code} : correctif du matin intact",
                  code not in codes, codes)

        # LE POINT CLIQUÉ EST CELUI DU NEXUS, pas un repli muet.
        barrage = next(c for c in sans_ennemi.hand if c.code == "BARRAGE")
        castable, plan, cibles, pourquoi = actions.spell_is_castable(barrage, sans_ennemi)
        check("Barrage : lançable", castable is True, pourquoi)
        check("   sur le point du nexus adverse",
              cibles == (sans_ennemi.enemy_nexus,), (cibles, sans_ennemi.enemy_nexus))
        check("   et `sort_sans_cible` ne l'écarte plus",
              actions.sort_sans_cible(barrage, sans_ennemi) is None,
              actions.sort_sans_cible(barrage, sans_ennemi))

        # LA DETTE EST PAYÉE — « FARDEAU » SE DEMANDE DANS LE MODE DU JEU.
        # Le garde « randomly » retire à Ebb and Flow le marqueur du tir ;
        # il ne reste que l'allié du soin, et `effect_clause` ne coupe pas
        # sur les « and » : le plan dit donc DAMAGE sur ALLIÉ. Sans
        # restrictions c'est un clic légal (le jeu soigne), mais en mode
        # PRUDENT c'est le refus « damage dirigé sur notre propre unité ».
        # `is_dead_weight` appelait `classify_card(card)` SANS argument,
        # donc restricted=True MÊME EN MODE PAR DÉFAUT : la carte passait
        # pour du fardeau pur — première défaussée au mulligan, dernière
        # renforcée — alors qu'elle est jouable.
        #
        # Ce n'était pas un cas particulier : mesuré le 09/11/2026 sur la
        # base entière, **75 sorts collectionnables sur 566** étaient dans
        # ce cas, dont Deny, Condemn et Bone Skewer. La question se pose
        # désormais dans le mode où le bot joue vraiment.
        ebb_flow = next(c for c in sans_ennemi.hand if c.code == "EBB_FLOW")
        check("Ebb and Flow : jouable sans restrictions",
              "EBB_FLOW" in codes, codes)
        check("   et plus comptée « fardeau pur » : la question suit le mode",
              actions.is_dead_weight(ebb_flow) is False,
              spells.classify_card(ebb_flow, restricted=False).reason)
        prudent = actions.CARD_RESTRICTIONS
        actions.CARD_RESTRICTIONS = True
        try:
            check("   en mode PRUDENT, elle redevient du fardeau — c'est juste",
                  actions.is_dead_weight(ebb_flow) is True,
                  spells.classify_card(ebb_flow, restricted=True).reason)
        finally:
            actions.CARD_RESTRICTIONS = prudent

        # EBB NE CLIQUE RIEN DU TOUT : ni unité, ni nexus.
        ebb = next(c for c in sans_ennemi.hand if c.code == "EBB")
        castable, plan, cibles, pourquoi = actions.spell_is_castable(ebb, sans_ennemi)
        check("Ebb : lançable sans aucun clic",
              castable is True and cibles == (), (castable, cibles, pourquoi))

        # ---- avec un ennemi, l'unité repasse devant ---------------------
        avec_ennemi = main_et_plateau(main, banc=["UNIT_A"], ennemis=["VANILLA33"])
        codes = [c.code for c in playable_cards(avec_ennemi, pool)]
        for code in ("BARRAGE", "DEATHS_HAND", "QUICKEN", "SPIRIT_JOURNEY",
                     "CALIBRUM"):
            check(f"   {code} : jouable dès qu'un ennemi est là",
                  code in codes, codes)
        barrage = next(c for c in avec_ennemi.hand if c.code == "BARRAGE")
        _, _, cibles, _ = actions.spell_is_castable(barrage, avec_ennemi)
        check("   et Barrage vise l'unité, pas le nexus",
              cibles and cibles[0] != avec_ennemi.enemy_nexus, cibles)
    finally:
        actions.CARD_RESTRICTIONS = saved


# Les deux familles de cartes dont le NEXUS change le verdict, écrites
# comme la base les écrit. Le premier groupe se résout SANS ennemi, le
# second se soigne SANS allié — deux dettes nommées le 09/11.
SORTS_ET_LES_DEUX_NEXUS = {
    "FINAL_SPARK": {         # 01DE042T3
        "name": "Final Spark", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Slow"], "keywordRefs": ["Slow"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal 4 to an enemy. If there are no enemies, "
                          "deal 4 to the enemy Nexus instead.",
    },
    "JAVELIN": {             # 07SH013T2
        "name": "Javelin Toss", "cost": 2, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "spellSpeedRef": "Fast",
        "descriptionRaw": "Deal  4 to an enemy. If there are no enemies when "
                          "I'm played, I target the enemy Nexus instead.",
    },
    "HEAL_NEXUS": {          # 01IO004 Health Potion
        "name": "Potion de soin", "cost": 1, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Heal an ally or your Nexus 3.",
    },
    "HEAL_SEUL": {           # le témoin : un soin SANS alternative
        "name": "Soin simple", "cost": 1, "attack": 0, "health": 0,
        "type": "Spell", "keywords": ["Burst"], "keywordRefs": ["Burst"],
        "spellSpeedRef": "Burst",
        "descriptionRaw": "Heal an ally 3.",
    },
    "TAVERNIER": {           # 01FR050 Kindly Tavernkeeper
        "name": "Tavernier bienveillant", "cost": 3, "attack": 2, "health": 3,
        "type": "Unit", "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Heal an ally or your Nexus 3.",
    },
}


def test_un_sort_qui_se_resout_sans_ennemi_nest_pas_ecarte():
    """
    « IF THERE ARE NO ENEMIES, … THE ENEMY NEXUS INSTEAD » — dette du 09/11.

    Final Spark (01DE042T3), Ace in the Hole (98PZ004) et Javelin Toss
    (07SH013T2) partent TOUTES SEULES sur le nexus quand le plateau
    adverse est vide. Le correctif du 08/11 (`sort_sans_cible`) les
    écartait pourtant, et il avait raison de son point de vue : le plan
    disait « un clic sur un ennemi », et aucun ennemi n'existait. Ce que
    le texte ajoute, lui seul pouvait le dire — `resolves_without_target`.

    LES DEUX EXIGENCES, ET ELLES SE TIENNENT :
      - AUCUN CLIC N'EST FABRIQUÉ : le sort est lançable avec ZÉRO cible,
        et surtout pas avec un point inventé sur le nexus. Un clic que le
        jeu refuse coûte plus cher qu'une carte gardée en main.
      - DÈS QU'UN ENNEMI EST LÀ, RIEN NE CHANGE : un clic, sur l'unité.

    ET LE SORT NE DOIT PAS ÊTRE ANNULÉ APRÈS LA POSE. C'est tout le prix
    du correctif : `play_spell` tenait « zéro cible pour un plan qui en
    réclame une » pour un ciblage INCOMPLET, donc pour une annulation —
    les ~23 s que `sort_sans_cible` existe justement pour épargner.
    """
    print("\nUn sort qui se résout sans ennemi n'est pas écarté")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **SORTS_SANS_CIBLE, **SORTS_ET_LES_DEUX_NEXUS})
        pool = ManaPool(mana=10, spell_mana=3)
        main = ["FINAL_SPARK", "JAVELIN", "CALIBRUM"]

        sans_ennemi = main_et_plateau(main, banc=["UNIT_A"])
        codes = [c.code for c in playable_cards(sans_ennemi, pool)]
        for code in ("FINAL_SPARK", "JAVELIN"):
            carte = next(c for c in sans_ennemi.hand if c.code == code)
            check(f"{code} : lançable sur un plateau adverse vide",
                  code in codes, codes)
            castable, plan, cibles, pourquoi = actions.spell_is_castable(carte, sans_ennemi)
            check("   et AUCUN clic fabriqué : zéro cible",
                  castable is True and cibles == (), (castable, cibles, pourquoi))
            check("   `sort_sans_cible` ne l'écarte plus",
                  actions.sort_sans_cible(carte, sans_ennemi) is None,
                  actions.sort_sans_cible(carte, sans_ennemi))
            # LE DIAGNOSTIC DIT LA MÊME CHOSE QUE LA DÉCISION, dans le
            # même ordre (invariant du 09/11 : deux implémentations du
            # même test finissent toujours par diverger).
            check("   et `rejection_reason` ne trouve rien à redire",
                  actions.rejection_reason(carte, sans_ennemi, pool,
                                           allow_spells=True) is None,
                  actions.rejection_reason(carte, sans_ennemi, pool, allow_spells=True))

        # LE CORRECTIF DU 08/11 N'EST PAS DÉFAIT : un sort dont le texte
        # ne promet aucun repli reste écarté.
        check("Calibrum : toujours écartée, elle ne promet rien",
              "CALIBRUM" not in codes, codes)

        # ---- de bout en bout : posé, résolu, AUCUNE annulation ---------
        # Un Burst quitte la main et se résout seul : s'il n'y a rien sur
        # la pile et rien à cliquer, `play_spell` ne doit pas conclure au
        # ciblage incomplet.
        carte = next(c for c in sans_ennemi.hand if c.code == "JAVELIN")
        apres = main_et_plateau(["FINAL_SPARK", "CALIBRUM"], banc=["UNIT_A"])
        (recorder, cancels, clics), restore = _record_gestures()
        try:
            success, _ = actions.play_spell(
                FakeReader([apres, apres, apres]), sans_ennemi, carte)
        finally:
            restore()
        check("sans ennemi : le sort est posé et tenu pour résolu",
              success is True, success)
        check("   aucun clic de ciblage", clics == [], clics)
        check("   et AUCUNE annulation", cancels == [], cancels)

        # ---- avec un ennemi, le clic revient ---------------------------
        avec_ennemi = main_et_plateau(main, banc=["UNIT_A"], ennemis=["VANILLA33"])
        for code in ("FINAL_SPARK", "JAVELIN"):
            carte = next(c for c in avec_ennemi.hand if c.code == code)
            castable, plan, cibles, pourquoi = actions.spell_is_castable(carte, avec_ennemi)
            check(f"   {code} : un ennemi est là, on le clique",
                  castable is True and len(cibles) == 1
                  and cibles[0] != avec_ennemi.enemy_nexus,
                  (cibles, pourquoi))
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_un_soin_sans_allie_vise_notre_nexus():
    """
    « HEAL AN ALLY OR YOUR NEXUS » — le symétrique, dette du 09/11.

    Le chantier du 08/11 a appris au bot que le nexus ADVERSE est une
    cible cliquable quand le texte l'offre. Le nôtre ne l'était pas :
    banc vide, « Heal an ally or your Nexus 3 » rendait « aucun allié en
    jeu », `sort_sans_cible` écartait la carte, et le soin était
    abandonné dans l'état même où il vaut le plus cher.

    NEUF CARTES, dont deux UNITÉS (« Play: Heal an ally or your Nexus
    3 ») — et pour celles-là le prix était pire : rien ne les écarte en
    mode par défaut, elles étaient donc POSÉES puis laissées devant un
    clic qu'on ne savait pas faire.
    """
    print("\nUn soin sans allié vise notre nexus")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **SORTS_ET_LES_DEUX_NEXUS})
        pool = ManaPool(mana=10, spell_mana=3)

        banc_vide = main_et_plateau(["HEAL_NEXUS", "HEAL_SEUL", "TAVERNIER"])
        codes = [c.code for c in playable_cards(banc_vide, pool)]
        potion = next(c for c in banc_vide.hand if c.code == "HEAL_NEXUS")
        check("le soin qui nomme notre nexus est jouable banc vide",
              "HEAL_NEXUS" in codes, codes)
        castable, plan, cibles, pourquoi = actions.spell_is_castable(potion, banc_vide)
        check("   et le point cliqué est NOTRE nexus",
              castable is True and cibles == (banc_vide.our_nexus,),
              (cibles, banc_vide.our_nexus, pourquoi))
        check("   `rejection_reason` ne trouve rien à redire",
              actions.rejection_reason(potion, banc_vide, pool,
                                       allow_spells=True) is None,
              actions.rejection_reason(potion, banc_vide, pool, allow_spells=True))

        # LE TÉMOIN : un soin SANS alternative reste écarté banc vide.
        # Lui inventer un repli ferait un clic que le jeu refuse.
        simple = next(c for c in banc_vide.hand if c.code == "HEAL_SEUL")
        check("un soin ordinaire reste écarté sans allié",
              "HEAL_SEUL" not in codes, codes)
        check("   et le motif parle bien d'allié",
              "allié" in (actions.sort_sans_cible(simple, banc_vide) or ""),
              actions.sort_sans_cible(simple, banc_vide))

        # L'UNITÉ PASSE PAR LE MÊME CHEMIN. Elle n'était pas écartée — en
        # mode par défaut rien ne l'écarte — elle était posée devant un
        # clic introuvable.
        tavernier = next(c for c in banc_vide.hand if c.code == "TAVERNIER")
        plan, point, description = actions.unit_play_plan(tavernier, banc_vide)
        check("Tavernier : son « Play: » sait où cliquer, banc vide",
              point == banc_vide.our_nexus, (point, description))

        # ---- avec un allié, rien ne change -----------------------------
        avec_allie = main_et_plateau(["HEAL_NEXUS", "TAVERNIER"], banc=["UNIT_A"])
        potion = next(c for c in avec_allie.hand if c.code == "HEAL_NEXUS")
        _, _, cibles, _ = actions.spell_is_castable(potion, avec_allie)
        check("avec un allié, c'est lui qu'on soigne, pas le nexus",
              cibles and cibles[0] != avec_allie.our_nexus, cibles)
        tavernier = next(c for c in avec_allie.hand if c.code == "TAVERNIER")
        _, point, _ = actions.unit_play_plan(tavernier, avec_allie)
        check("   et le « Play: » de l'unité suit la même règle",
              point is not None and point != avec_allie.our_nexus, point)
    finally:
        actions.CARD_RESTRICTIONS = saved



def test_le_plan_ne_declare_pas_jouable_ce_que_la_decision_refuse():
    """
    LE DIAGNOSTIC NE DOIT JAMAIS DIRE AUTRE CHOSE QUE LA DÉCISION.

    Vu sur un VRAI plateau le 09/11/2026, mana 3, phase ATTACKING :

        Spirit Leech   (4*) 4/2    non — trop chère
        Withering Wail (4*) 0/0    JOUABLE (DAMAGE 1 sur aucune)

    Deux cartes à 4, le même mana, deux verdicts opposés — et trois
    lignes plus bas, « Rien à jouer ». La DÉCISION avait raison ; c'est
    `_describe` qui mentait. Il tenait sa PROPRE liste de motifs, puis,
    dès qu'un sort était lançable, écrivait « JOUABLE » en JETANT les
    motifs déjà calculés, le mana compris.

    `actions.py` le dit pourtant au-dessus de `unit_play_blocker` :
    « deux implémentations du même test finissent toujours par diverger,
    et c'est alors le diagnostic qui ment ». Il y en avait TROIS —
    `playable_cards` décide, `rejection_reason` explique, et `_describe`
    recommençait pour son affichage.

    Ce que ça coûte n'est pas un pixel d'affichage : `python actions.py
    plan` est la première commande que le projet dit de lancer devant un
    « pourquoi a-t-il fait ça ». Une carte annoncée JOUABLE qui ne sera
    jamais jouée envoie chercher le défaut dans la pose, l'attaque ou la
    phase — partout sauf dans le mana.
    """
    print("\nLe plan ne déclare pas JOUABLE ce que la décision refuse")

    import contextlib
    import io

    def ligne_de(snap, pool, nom):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            actions._describe(snap, pool, allow_spells=True)
        return next(l for l in sortie.getvalue().splitlines() if nom in l)

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db(FULL_DB)
        snap = trade_snapshot(hand_codes=["BLACK_SPEAR"], board_codes=["UNIT_A"],
                              enemy_codes=["UNIT_BIG"])
        lance = snap.hand[0]

        # Le sort est LANÇABLE — une unité est en jeu, « deal 4 to a
        # unit » a sa cible. C'est exactement la branche qui mentait :
        # celle d'un sort dont le plan tient debout.
        castable, plan, _, pourquoi = actions.spell_is_castable(lance, snap)
        check("Lance noire (3 mana) est bien lançable", castable is True, pourquoi)

        pauvre = ManaPool(mana=2, spell_mana=0)
        motif = actions.rejection_reason(lance, snap, pauvre, allow_spells=True)
        check("   mais à 2 mana la DÉCISION la refuse",
              motif is not None and "mana" in motif, motif)
        codes = [c.code for c in playable_cards(snap, pauvre, allow_spells=True)]
        check("   et `playable_cards` ne la retient pas",
              "BLACK_SPEAR" not in codes, codes)

        ligne = ligne_de(snap, pauvre, "Lance noire")
        check("   le DIAGNOSTIC ne dit donc pas JOUABLE", "JOUABLE" not in ligne, ligne)
        check("   il reprend le motif de la décision, mot pour mot",
              motif in ligne, (ligne, motif))

        # Et le cas normal n'est pas perdu au passage : payable, la carte
        # redevient jouable ET son plan reste affiché — c'est lui qui dit
        # ce que le bot irait cliquer.
        riche = ManaPool(mana=5, spell_mana=0)
        ligne = ligne_de(snap, riche, "Lance noire")
        check("   payable, elle redevient JOUABLE", "JOUABLE" in ligne, ligne)
        check("   avec son plan de ciblage", str(plan) in ligne, (ligne, str(plan)))

        # Un refus qui ne vient PAS du mana reste dit comme avant : ici
        # la cible manque, et c'est le motif de `sort_sans_cible`.
        vide = trade_snapshot(hand_codes=["BLACK_SPEAR"], board_codes=["UNIT_A"],
                              enemy_codes=[])
        attendu = actions.rejection_reason(vide.hand[0], vide, riche, allow_spells=True)
        ligne = ligne_de(vide, riche, "Lance noire")
        check("   sans cible, le motif du sort est repris tel quel",
              attendu is not None and attendu in ligne, (ligne, attendu))
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_un_equipement_sans_porteur_nest_pas_annonce_jouable():
    """
    LE TROU QUE LE CORRECTIF DU MÊME JOUR A RENDU VISIBLE.

    `playable_cards` écarte un équipement sans porteur depuis le
    05/11/2026 — c'est l'invariant de The Darkin Lodestone, tentée HUIT
    fois banc vide, ~11 s perdues à chaque round. Mais `rejection_reason`,
    qui est censée être son explication dans le MÊME ordre, n'avait aucun
    test d'équipement dans sa branche « restrictions levées » : elle
    traversait et rendait None, c'est-à-dire JOUABLE.

    Personne ne l'avait vu parce que `_describe` tenait sa propre liste de
    motifs et écrivait « non — équipement » de son côté. En le faisant
    déléguer à `rejection_reason` le 09/11, on a hérité du trou, et
    `python actions.py plan` s'est mis à écrire JOUABLE sur une carte que
    le bot ne pose jamais.

    C'est l'argument de la source unique, pas son démenti : la divergence
    existait déjà, elle était seulement masquée par une deuxième erreur.
    Une fois les deux chemins réunis, il n'y a plus qu'un endroit où la
    réparer — et un seul test pour la garder fermée.
    """
    print()
    print("Un équipement sans porteur n'est pas annoncé JOUABLE")

    import contextlib
    import io

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**FULL_DB, **HAND_POWER_CARDS})
        pool = ManaPool(mana=10, spell_mana=0)

        # BANC VIDE : l'équipement n'a personne à équiper.
        vide = snapshot_with(hand_codes=["SWORD"])
        point, pourquoi = actions.equipment_plan(vide.hand[0], vide)
        check("sans allié, l'équipement n'a aucun point à viser",
              point is None, (point, pourquoi))
        codes = [c.code for c in playable_cards(vide, pool)]
        check("   la DÉCISION ne le retient pas", "SWORD" not in codes, codes)

        motif = actions.rejection_reason(vide.hand[0], vide, pool, allow_spells=True)
        check("   et l'EXPLICATION le dit aussi, au lieu de rendre None",
              motif is not None and "équipement" in motif, motif)

        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            actions._describe(vide, pool, allow_spells=True)
        ligne = next(l for l in sortie.getvalue().splitlines() if "rouillée" in l)
        check("   donc `plan` n'écrit pas JOUABLE", "JOUABLE" not in ligne, ligne)

        # AVEC UN ALLIÉ : rien n'est perdu au passage.
        avec = snapshot_with(hand_codes=["SWORD"], board_codes=["UNIT_A"])
        codes = [c.code for c in playable_cards(avec, pool)]
        check("avec un allié, l'équipement redevient jouable",
              "SWORD" in codes, codes)
        check("   et l'explication ne s'y oppose plus",
              actions.rejection_reason(avec.hand[0], avec, pool,
                                       allow_spells=True) is None,
              actions.rejection_reason(avec.hand[0], avec, pool, allow_spells=True))

        # LE MANA RESTE LE DERNIER MOT, dans le même ordre que la décision.
        pauvre = ManaPool(mana=0, spell_mana=0)
        motif = actions.rejection_reason(avec.hand[0], avec, pauvre, allow_spells=True)
        check("   porteur trouvé mais mana absent : c'est le mana qui parle",
              motif is not None and "mana" in motif, motif)
    finally:
        actions.CARD_RESTRICTIONS = saved


# LES QUATRE CARTES « ATTACH » DE LA BASE, vues le 11/11/2026. Le texte
# et les mots-clés sont ceux de `card_sets`, mot pour mot : c'est le
# mot-clé qui porte le refus, pas le texte — Rainbowfish, Quick Quill et
# Papercraft Dragon n'ont AUCUNE description.
ATTACH_CARDS = {
    # Yuumi (05BC029), celle qui a bloqué trois fois.
    "YUUMI": {
        "name": "Yuumi", "cost": 3, "attack": 2, "health": 1,
        "type": "Unit", "supertype": "Champion", "collectible": True,
        "keywords": ["Attach"], "keywordRefs": ["Attach"],
        "descriptionRaw": "Round Start: Grant the unit I'm Attached to "
                          "+1|+1. Otherwise, grant me +1|+1 instead.",
    },
    # Rainbowfish (05BC019) : aucun texte du tout, et elle était EN MAIN
    # dans le combat même qui a bloqué.
    "RAINBOWFISH": {
        "name": "Poisson arc-en-ciel", "cost": 2, "attack": 1, "health": 2,
        "type": "Unit", "collectible": True,
        "keywords": ["Attach"], "keywordRefs": ["Attach"],
        "descriptionRaw": "",
    },
}


def test_une_unite_attach_sans_allie_nest_pas_posee():
    """
    UNE UNITÉ « ATTACH » SANS ALLIÉ N'A PERSONNE À QUI S'ACCROCHER.

    Fait de jeu d'Ewan, 11/11/2026, dit en direct : « le bot bloque sur
    Yuumi car il n'y a pas d'unité sur le banc ». Mesuré dans
    `logs/challenges_20261111_130907.log` : TROIS paliers d'immobilité de
    50-51 s, 152 s au total, tous en phase ATTACKING, tous après une pose
    de Yuumi — `bouton=cible`, `orbe=non`, banc vide. `_check_progress`
    finit par annuler, et le bot repose la carte au tour suivant.

    C'est l'équipement sans porteur (05/11) sur une autre famille de
    cartes : le mot-clé est LU dans `keywords` / `keywordRefs`, donc ce
    n'est pas de la prudence mais une impossibilité, du même ordre que le
    mana. Elle vaut DANS LES DEUX MODES.

    LA NUANCE QU'ON N'ÉCRASE PAS : Yuumi dit « Otherwise, grant me +1|+1
    instead », donc elle FONCTIONNE sans attache — ce qui laisserait
    croire qu'on peut valider à vide. L'observation dit le contraire :
    le jeu a attendu 50 s, trois fois. S'il existe un geste de validation
    (comme l'orbe pour Vladimir), c'est un fait de jeu et il doit venir
    d'Ewan.
    """
    print()
    print("Une unité « Attach » sans allié n'est pas posée")

    import contextlib
    import io as _io

    saved = actions.CARD_RESTRICTIONS
    try:
        with_db({**FULL_DB, **ATTACH_CARDS})
        pool = ManaPool(mana=10, spell_mana=0)

        # BANC VIDE : personne à qui s'accrocher.
        vide = snapshot_with(hand_codes=["YUUMI", "RAINBOWFISH"])
        for carte in vide.hand:
            motif = actions.unit_play_blocker(carte, vide)
            check(f"{carte.name} : le refus NOMME la cause",
                  motif is not None and "accrocher" in motif, motif)

        for restrictions in (False, True):
            actions.CARD_RESTRICTIONS = restrictions
            mode = "levées" if not restrictions else "prudent"
            codes = [c.code for c in playable_cards(vide, pool)]
            check(f"la DÉCISION écarte les deux (restrictions {mode})",
                  "YUUMI" not in codes and "RAINBOWFISH" not in codes, codes)
            for carte in vide.hand:
                motif = actions.rejection_reason(carte, vide, pool,
                                                 allow_spells=True)
                check(f"   et l'EXPLICATION le dit aussi ({carte.name}, {mode})",
                      motif is not None and "accrocher" in motif, motif)

        # ET `plan` NE DOIT PAS ÉCRIRE JOUABLE : c'est par là que la
        # divergence se voit, et c'est ce qui l'a trahie pour
        # l'équipement le 09/11.
        actions.CARD_RESTRICTIONS = False
        sortie = _io.StringIO()
        with contextlib.redirect_stdout(sortie):
            actions._describe(vide, pool, allow_spells=True)
        for nom in ("Yuumi", "Poisson arc-en-ciel"):
            ligne = next(l for l in sortie.getvalue().splitlines() if nom in l)
            check(f"`plan` n'écrit pas JOUABLE ({nom})",
                  "JOUABLE" not in ligne, ligne)

        # NON-RÉGRESSION : un allié sur le BANC, et elles redeviennent
        # posables dans les deux modes.
        avec = snapshot_with(hand_codes=["YUUMI", "RAINBOWFISH"],
                             board_codes=["UNIT_A"])
        for restrictions in (False, True):
            actions.CARD_RESTRICTIONS = restrictions
            mode = "levées" if not restrictions else "prudent"
            codes = [c.code for c in playable_cards(avec, pool)]
            check(f"un allié au banc : elles redeviennent jouables ({mode})",
                  "YUUMI" in codes and "RAINBOWFISH" in codes, codes)
            for carte in avec.hand:
                check(f"   et l'explication ne s'y oppose plus ({carte.name}, {mode})",
                      actions.rejection_reason(carte, avec, pool,
                                               allow_spells=True) is None,
                      actions.rejection_reason(carte, avec, pool,
                                               allow_spells=True))

        # LE PLATEAU A DEUX HORLOGES : pendant une attaque nos unités sont
        # lues dans `attack_row`, pas dans `board`. Compter le seul banc
        # refuserait la pose au milieu d'une attaque, alors que l'allié est
        # bien là.
        actions.CARD_RESTRICTIONS = False
        engagee = snapshot_with(hand_codes=["YUUMI"], attack_codes=["UNIT_A"])
        check("un allié ENGAGÉ dans l'attaque compte aussi",
              "YUUMI" in [c.code for c in playable_cards(engagee, pool)],
              [c.code for c in playable_cards(engagee, pool)])

        # ZÉRO COLLATÉRAL : une unité ORDINAIRE sur un banc vide reste
        # posable. Le refus porte sur le mot-clé, pas sur le banc vide.
        ordinaire = snapshot_with(hand_codes=["UNIT_A"])
        for restrictions in (False, True):
            actions.CARD_RESTRICTIONS = restrictions
            mode = "levées" if not restrictions else "prudent"
            check(f"une unité sans Attach n'est pas touchée ({mode})",
                  "UNIT_A" in [c.code for c in playable_cards(ordinaire, pool)],
                  [c.code for c in playable_cards(ordinaire, pool)])
    finally:
        actions.CARD_RESTRICTIONS = saved


# VLADIMIR (01NX006) ET SA FAMILLE. Le texte est celui de la base, mot
# pour mot : « any number of » y laisse le NOMBRE de désignations à
# notre discrétion, donc le jeu attend une validation après la cible.
VLADIMIR_CARDS = {
    "VLADIMIR": {
        "name": "Vladimir", "cost": 5, "attack": 5, "health": 5,
        "type": "Unit", "supertype": "Champion", "collectible": True,
        "keywords": [], "keywordRefs": [],
        "descriptionRaw": "Play: Deal 1 to any number of allies to deal "
                          "that much to an enemy.\r\n",
    },
}


def test_vladimir_est_posee_en_validant_a_l_orbe():
    """
    LE BOUTON BLEU EST L'ORBE, ET IL ÉTAIT CALIBRÉ DEPUIS TOUJOURS.

    Vladimir a figé le combat DEUX FOIS le 06/11/2026, ~50 s chacune, en
    pleine phase ATTACKING, puis elle a été bannie et rendue à la main.
    On l'a donc refusée « hors de portée » au motif que le jeu attendait
    « des clics en nombre libre PLUS une validation, et ce bouton n'est
    pas calibré ».

    Ewan, 10/11/2026 : « on clique sur l'ennemi et on clique sur le
    bouton bleu à droite de la page ». Ce bouton bleu est l'ORBE DE TOUR.
    Mesuré sur les deux captures que le bot avait gardées de ses propres
    blocages — `screenshots/bloque_ATTACKING_20261106_105937.png` et
    `..._111227.png` : Vladimir au centre, l'invite « Infligez 1 pt(s) de
    dégâts », nos alliés surlignés, et à droite à mi-hauteur l'orbe BLEUE
    portant « PASSER », dans `game_state.TURN_ORB_REGION` dont
    `actions.TURN_BUTTON_RATIO` est le centre. Le log de ce combat dit
    que l'ennemi avait bien été cliqué (« Ciblage du pouvoir : Sapling
    (1) 2/1 en (1115, 180) ») : il ne manquait QUE ce clic-ci.

    DEUX GESTES, DANS CET ORDRE, ET AUCUNE COORDONNÉE NOUVELLE.
    """
    print()
    print("Vladimir : l'ennemi, puis la validation à l'orbe")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **VLADIMIR_CARDS})
        avant = scene([
            ("VLADIMIR", 21, EN_MAIN, 500),
            ("UNIT_B", 40, 0.800, 400, False),      # un ennemi à désigner
        ])
        apres = scene([
            ("UNIT_B", 40, 0.800, 400, False),
            ("VLADIMIR", 21, 0.150, 500),           # arrivée sur le banc
        ])

        carte = {c.code: c for c in avant.hand}["VLADIMIR"]
        plan, point, description = actions.unit_play_plan(carte, avant)
        ennemi = avant.enemy_board[0].center
        check("un plan de pouvoir, et il est jouable",
              plan is not None and plan.playable, plan)
        check("   un seul clic, sur l'ennemi", point == ennemi, (point, ennemi))
        check("   et une validation est due derrière",
              plan is not None and plan.free_designation is True, plan)
        check("rien ne bloque la pose",
              actions.unit_play_blocker(carte, avant) is None,
              actions.unit_play_blocker(carte, avant))
        codes = [c.code for c in playable_cards(avant, ManaPool(mana=10, spell_mana=0))]
        check("   la DÉCISION la retient", "VLADIMIR" in codes, codes)

        (recorder, cancels, clics), restore = _record_gestures()
        try:
            success, _ = play_card(
                FakeReader([apres, apres, apres]), avant, carte,
                power_target=point, power_plan=plan, power_description=description,
            )
        finally:
            restore()

        orbe = avant.window.rel(*actions.TURN_BUTTON_RATIO)
        check("pose réussie", success is True)
        check("un seul dépôt", len(recorder.drags) == 1, recorder.drags)
        check("deux clics : la cible, puis la validation",
              len(clics) == 2, clics)
        check("   l'ennemi d'abord (l'ordre qu'Ewan décrit)",
              clics and clics[0] == ennemi, (clics, ennemi))
        check("   l'orbe ensuite, au point déjà connu du projet",
              len(clics) > 1 and clics[1] == orbe, (clics, orbe))
        check("aucune annulation : plus rien ne fige", cancels == [], cancels)
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_vladimir_sans_ennemi_nest_pas_posee():
    """
    LA VALIDATION NE REMPLACE PAS LA CIBLE.

    Le geste d'Ewan en compte DEUX, et le premier est un clic sur un
    ennemi. Plateau adverse vide, il n'a nulle part où aller : poser la
    carte rouvrirait exactement l'attente que ce chantier referme.

    C'est la même règle que l'équipement sans porteur (05/11) et que
    `sort_sans_cible` (08/11) : une impossibilité LUE sur le plateau,
    donc valable DANS LES DEUX MODES — et la décision et son explication
    doivent la dire pareil, sinon c'est le diagnostic qui ment.
    """
    print()
    print("Vladimir sans ennemi : la cible manque, on ne pose pas")

    import contextlib
    import io as _io

    saved = actions.CARD_RESTRICTIONS
    try:
        with_db({**ALL_CARDS, **VLADIMIR_CARDS})
        pool = ManaPool(mana=10, spell_mana=0)
        vide = scene([("VLADIMIR", 21, EN_MAIN, 500)])
        carte = {c.code: c for c in vide.hand}["VLADIMIR"]

        for restrictions in (False, True):
            actions.CARD_RESTRICTIONS = restrictions
            mode = "levées" if not restrictions else "prudent"
            plan, point, _ = actions.unit_play_plan(carte, vide)
            check(f"aucun ennemi à viser (restrictions {mode})",
                  point is None, point)
            check("   la DÉCISION l'écarte",
                  "VLADIMIR" not in [c.code for c in playable_cards(vide, pool)],
                  [c.code for c in playable_cards(vide, pool)])
            motif = actions.rejection_reason(carte, vide, pool, allow_spells=True)
            check("   et l'EXPLICATION dit la même chose",
                  motif is not None and "cibler" in motif, motif)

        # ET `plan` NE DOIT PAS ÉCRIRE JOUABLE : c'est par là que la
        # divergence se voit, et c'est ce qui l'a trahie pour
        # l'équipement le 09/11.
        actions.CARD_RESTRICTIONS = False
        sortie = _io.StringIO()
        with contextlib.redirect_stdout(sortie):
            actions._describe(vide, pool, allow_spells=True)
        ligne = next(l for l in sortie.getvalue().splitlines() if "Vladimir" in l)
        check("`plan` n'écrit pas JOUABLE", "JOUABLE" not in ligne, ligne)

        # AVEC UN ENNEMI, RIEN N'EST PERDU : le refus est bien celui de
        # l'absence de cible, pas un refus déguisé de la famille.
        avec = scene([
            ("VLADIMIR", 21, EN_MAIN, 500),
            ("UNIT_B", 40, 0.800, 400, False),
        ])
        carte = {c.code: c for c in avec.hand}["VLADIMIR"]
        for restrictions in (False, True):
            actions.CARD_RESTRICTIONS = restrictions
            mode = "levées" if not restrictions else "prudent"
            check(f"un ennemi est là : elle redevient jouable ({mode})",
                  "VLADIMIR" in [c.code for c in playable_cards(avec, pool)],
                  [c.code for c in playable_cards(avec, pool)])
            check("   et plus aucun motif",
                  actions.rejection_reason(carte, avec, pool, allow_spells=True) is None,
                  actions.rejection_reason(carte, avec, pool, allow_spells=True))
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_lentete_de_why_ne_contredit_pas_ses_verdicts():
    """
    « Sorts : exclus » EN EN-TÊTE, « JOUABLE » TROIS LIGNES PLUS BAS.

    `python actions.py why` imprimait, sans `--spells` :

        Sorts        : exclus
        ...
        Éclair          hand      1     1   JOUABLE

    Les deux lignes sortent du MÊME écran, et elles se contredisent. La
    bonne est celle du bas : `CLAUDE.md` le dit depuis le 04/11/2026 —
    « `--spells` NE COMMANDE RIEN en mode par défaut », `playable_cards`
    court-circuite sur `if not CARD_RESTRICTIONS:` en tête de boucle et
    les sorts y passent sans condition. C'est l'EN-TÊTE qui mentait : il
    lisait l'option de ligne de commande au lieu du MODE.

    Même famille que `_describe` réparé la veille : deux endroits qui
    répondent à la même question, et c'est le diagnostic qui ment. La
    parade est la même — une seule source, `etat_des_sorts`, et un test
    qui l'oblige à être d'accord avec `rejection_reason`.

    Ce que ça coûtait : `why` est la commande qu'on lance pour savoir
    pourquoi une carte n'est pas jouée. Un en-tête qui annonce « exclus »
    envoie chercher un drapeau manquant — c'est-à-dire exactement nulle
    part — quand la vraie réponse est ailleurs.
    """
    print()
    print("L'en-tête de `why` ne contredit pas ses propres verdicts")

    saved = actions.CARD_RESTRICTIONS
    try:
        with_db({**ALL_CARDS, **HAND_POWER_CARDS})
        pool = ManaPool(mana=10, spell_mana=3)
        # Un ennemi en jeu, sinon c'est `sort_sans_cible` qui écarterait
        # Éclair et le test ne prouverait plus rien sur `--spells`.
        snap = main_et_plateau(["SPELL_A"], ennemis=["UNIT_B"])
        sort = next(c for c in snap.hand if c.code == "SPELL_A")

        # ---- mode PAR DÉFAUT : l'option ne commande rien --------------
        actions.CARD_RESTRICTIONS = False
        motif = actions.rejection_reason(sort, snap, pool, allow_spells=False)
        check("sans --spells, la DÉCISION joue quand même le sort",
              motif is None, motif)
        entete = actions.etat_des_sorts(allow_spells=False)
        check("   l'en-tête ne dit donc pas « exclus »",
              "exclus" not in entete, entete)
        check("   il dit qu'ils sont autorisés", "autorisés" in entete, entete)
        check("   et il nomme la raison : l'option est sans effet",
              "--spells" in entete, entete)
        check("   avec --spells, le même en-tête",
              actions.etat_des_sorts(allow_spells=True) == entete, entete)

        # ---- mode PRUDENT : là, l'option commande vraiment ------------
        actions.CARD_RESTRICTIONS = True
        motif = actions.rejection_reason(sort, snap, pool, allow_spells=False)
        check("en --prudent, sans l'option, la décision refuse le sort",
              motif is not None and "--spells" in motif, motif)
        check("   et l'en-tête dit « exclus »",
              actions.etat_des_sorts(allow_spells=False) == "exclus",
              actions.etat_des_sorts(allow_spells=False))
        check("   avec l'option, la décision l'accepte",
              actions.rejection_reason(sort, snap, pool, allow_spells=True) is None,
              actions.rejection_reason(sort, snap, pool, allow_spells=True))
        check("   et l'en-tête dit « autorisés »",
              actions.etat_des_sorts(allow_spells=True) == "autorisés",
              actions.etat_des_sorts(allow_spells=True))

        # ---- le garde-fou général : jamais « exclus » sur un sort joué -
        # Écrit comme une boucle plutôt que comme trois cas : c'est la
        # PROPRIÉTÉ qu'on veut tenir, et elle vaudra encore le jour où un
        # troisième mode apparaîtra.
        for restrictions in (False, True):
            actions.CARD_RESTRICTIONS = restrictions
            for option in (False, True):
                dit_exclus = "exclus" in actions.etat_des_sorts(option)
                joue = actions.rejection_reason(sort, snap, pool, option) is None
                check(f"   restrictions={restrictions} --spells={option} : "
                      "l'en-tête et le verdict s'accordent",
                      not (dit_exclus and joue),
                      (actions.etat_des_sorts(option), joue))
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_le_guet_dune_fenetre_imprevue_sarrete_des_que_la_carte_arrive():
    """
    ON N'ATTENDAIT PLUS POUR RIEN, MAIS ON ATTENDAIT JUSQU'AU BOUT.

    Après chaque pose, `play_card` guette une fenêtre de choix que rien
    n'annonçait (Nidalee, « Ambush 2 », toute carte absente de
    card_sets). La règle du 04/09/2026 dit : « on n'attend que si la
    carte n'est pas déjà sur le banc ». Elle était juste — mais évaluée
    UNE SEULE FOIS, avant la boucle. Or à cet instant-là la carte est
    toujours en train de voler : elle se pose une demi-seconde plus
    tard, et le guet continuait quand même ses 2,5 s entières.

    CE QUE ÇA COÛTAIT, MESURÉ le 10/11/2026 sur la tentative gagnée de
    la veille (`logs/challenges_20261109_192847.log`) : 6,77 s de
    médiane entre « Pose de X » et « X posée », pour 35 poses. Le
    plancher théorique est de 0,80 s — l'API du client répond en 67 ms
    (médiane sur 25 lectures, min 66, max 67) et trois confirmations
    d'immobilité ne coûtent que 0,20 s de réseau. Ce n'était donc ni le
    réseau ni la cadence de scrutation : c'était ce guet.

    LE FILET RESTE ENTIER, et c'est pour ça que la question porte sur le
    BANC. Quand une vraie fenêtre s'ouvre, la version affichée au centre
    porte le code de la carte jouée dans la bande « attack » — jamais
    sur le banc. Une carte arrivée SUR LE BANC prouve donc qu'aucune
    fenêtre n'est ouverte.
    """
    print()
    print("Le guet d'une fenêtre imprévue s'arrête dès que la carte arrive")

    with_db(FULL_DB)
    avant = snapshot_with(hand_codes=["UNIT_A"])
    apres = snapshot_with(board_codes=["UNIT_A"])
    carte = avant.hand[0]

    def lecteur():
        return FakeReader([apres])

    # (1) LA CARTE EST ARRIVÉE : on ne guette plus.
    arrive = lambda vue: True
    r = lecteur()
    choisie, _, detail = actions.resolve_unforeseen_choice(
        r, carte, avant, apres, wait=True, timeout=0.6, arrivee=arrive)
    check("carte arrivée : aucune fenêtre annoncée", choisie is None, detail)
    check("   et on n'a pas relu l'écran pour rien", r.calls == 0, r.calls)

    # (2) SANS LA QUESTION, l'ancien comportement : on guette jusqu'au
    #     bout. C'est ce qui prouve que c'est bien le nouvel arrêt qui
    #     fait la différence, et pas un hasard du montage.
    r = lecteur()
    choisie, _, _ = actions.resolve_unforeseen_choice(
        r, carte, avant, apres, wait=True, timeout=0.6)
    check("sans la question : on guette encore jusqu'au bout",
          choisie is None and r.calls >= 2, r.calls)

    # (3) LA CARTE N'ARRIVE PAS : le guet tient, c'est tout son intérêt.
    r = lecteur()
    jamais = lambda vue: False
    choisie, _, _ = actions.resolve_unforeseen_choice(
        r, carte, avant, apres, wait=True, timeout=0.6, arrivee=jamais)
    check("carte jamais arrivée : on guette comme avant",
          choisie is None and r.calls >= 2, r.calls)


def test_card_in_limbo_triggers_cancel():
    print("\nCarte en l'air : annulation")

    with_db(FULL_DB)
    before = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
    # La carte a quitté la main mais n'apparaît NI au banc NI en attaque :
    # c'est la signature du mode ciblage, celui qui fige la partie.
    limbo = snapshot_with(hand_codes=["UNIT_B"])
    card = next(c for c in before.hand if c.code == "UNIT_A")

    recorder, cancels = DragRecorder(), []
    saved_drag, saved_cancel = actions.drag, actions.cancel_pending_action
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    try:
        success, _ = play_card(FakeReader([limbo, limbo]), before, card)
        check("pose non déclarée réussie", success is False)
        check("annulation déclenchée", len(cancels) == 1, cancels)
        # Une seule tentative : réessayer alors que le jeu attend une cible
        # ne ferait qu'empiler les blocages.
        check("pas de seconde tentative", len(recorder.drags) == 1, recorder.drags)
    finally:
        actions.drag, actions.cancel_pending_action = saved_drag, saved_cancel


def test_normal_play_does_not_cancel():
    print("\nPose normale : aucune annulation")

    with_db(FULL_DB)
    before = snapshot_with(hand_codes=["UNIT_A", "UNIT_B"])
    placed = snapshot_with(hand_codes=["UNIT_B"], board_codes=["UNIT_A"])
    card = next(c for c in before.hand if c.code == "UNIT_A")

    recorder, cancels = DragRecorder(), []
    saved_drag, saved_cancel = actions.drag, actions.cancel_pending_action
    actions.drag = recorder
    actions.cancel_pending_action = lambda *a, **k: cancels.append(a)
    try:
        success, _ = play_card(FakeReader([placed]), before, card)
        check("pose réussie", success is True)
        check("aucune annulation parasite", cancels == [], cancels)
    finally:
        actions.drag, actions.cancel_pending_action = saved_drag, saved_cancel


def test_attackers_selection():
    print("\nChoix des attaquants")

    with_db(FULL_DB)
    # SPELL_A a 0 d'attaque, UNIT_B a « Can't Block » mais peut attaquer.
    snap = snapshot_with(board_codes=["UNIT_BIG", "UNIT_A", "UNIT_B", "SPELL_A"])
    names = [c.name for c in actions.attackers_available(snap)]

    check("le plus gros en premier", names[0] == "Colosse", names)
    check("0 d'attaque écarté", "Éclair" not in names, names)
    check("Can't Block peut quand même attaquer", "Ombre Fuyante" in names, names)
    check("3 attaquants retenus", len(names) == 3, names)


def test_attack_needs_token():
    print("\nAttaque et jeton")

    with_db(FULL_DB)
    rects = nexus_rects() + [rect_at_ratio(0.150, code="UNIT_A", card_id=1)]

    # Sans jeton, on ne doit RIEN faire : le bouton de confirmation est au
    # même endroit que celui de fin de tour, un clic à tort passe le tour.
    install_fakes(rects, screen=make_screen(orb_active=True, token="adversaire"))
    snap = state_reader().snapshot()
    check("phase DEFEND_TURN", snap.phase is Phase.DEFEND_TURN, snap.phase)

    recorder = DragRecorder()
    clicks = []
    original_drag, original_click = actions.drag, actions.click
    actions.drag = recorder
    actions.click = lambda *a, **k: clicks.append(a)
    try:
        engaged, _, log = actions.declare_attack(FakeReader([]), snap)
        check("aucune unité engagée sans jeton", engaged == [], engaged)
        check("aucun geste souris", recorder.drags == [], recorder.drags)
        check("aucun clic de confirmation", clicks == [], clicks)
        check("raison journalisée", any("jeton" in e for e in log.entries), log.entries)
    finally:
        actions.drag, actions.click = original_drag, original_click


def test_attack_does_not_confirm_when_nothing_engaged():
    print("\nConfirmation seulement si engagement")

    with_db(FULL_DB)
    stuck = snapshot_with(board_codes=["UNIT_A"])
    check("phase ATTACK_TURN", stuck.phase is Phase.ATTACK_TURN, stuck.phase)

    recorder = DragRecorder()
    clicks = []
    original_drag, original_click = actions.drag, actions.click
    actions.drag = recorder
    actions.click = lambda *a, **k: clicks.append(a)
    try:
        # Le banc ne se vide jamais : l'engagement échoue.
        engaged, _, log = actions.declare_attack(FakeReader([stuck] * 5), stuck)
        check("aucune unité engagée", engaged == [], engaged)
        # Une saisie ratée est retentée UNE fois avec des coordonnées
        # relues (cf. ENGAGE_ATTEMPTS) : deux gestes, pas plus. S'entêter
        # ferait perdre le tour aux unités suivantes.
        check("deux tentatives de saisie",
              len(recorder.drags) == actions.ENGAGE_ATTEMPTS, recorder.drags)
        # Le point critique : sans attaquant, ce clic terminerait le tour.
        check("pas de clic de confirmation", clicks == [], clicks)
        check("raison journalisée",
              any("passerait le tour" in e for e in log.entries), log.entries)
    finally:
        actions.drag, actions.click = original_drag, original_click


BLOCK_CARDS = {
    "ELUSIVE": {
        "name": "Spectre", "cost": 3, "attack": 3, "health": 2,
        "type": "Unit", "keywords": ["Elusive"], "keywordRefs": ["Elusive"],
        "descriptionRaw": "",
    },
    "FEARSOME": {
        "name": "Terreur", "cost": 4, "attack": 4, "health": 3,
        "type": "Unit", "keywords": ["Fearsome"], "keywordRefs": ["Fearsome"],
        "descriptionRaw": "",
    },
    "SMALL": {
        "name": "Recrue", "cost": 1, "attack": 1, "health": 2,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "WALL": {
        "name": "Muraille", "cost": 4, "attack": 1, "health": 7,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "BRUTE": {
        "name": "Brute", "cost": 5, "attack": 5, "health": 5,
        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": "",
    },
    "NOBLOCK": {
        "name": "Éclaireur", "cost": 2, "attack": 3, "health": 3,
        "type": "Unit", "keywords": ["Can't Block"], "keywordRefs": ["CantBlock"],
        "descriptionRaw": "",
    },
}
# Les cartes à mots-clés entrent dans la base COMMUNE : les tests de
# ciblage (test_spells) et de blocage passent par `blocking_snapshot`, et
# ils ont besoin d'une Éphémère au banc.
ALL_CARDS = {**FULL_DB, **BLOCK_CARDS, **KEYWORD_CARDS}


def blocking_snapshot(board_codes, enemy_codes):
    """Instantané en phase de blocage : eux dans la rangée d'attaque, nous au banc."""
    with_db(ALL_CARDS)
    rects, card_id = list(nexus_rects()), 200

    for index, code in enumerate(board_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=500 + 130 * index))
    for index, code in enumerate(enemy_codes):
        card_id += 1
        rects.append(rect_at_ratio(0.650, code=code, card_id=card_id,
                                   local=False, x=500 + 130 * index))

    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    return state_reader().snapshot()


def test_blocking_rules():
    print("\nRègles de blocage")

    snap = blocking_snapshot(["SMALL", "ELUSIVE", "BRUTE", "NOBLOCK"], ["ELUSIVE"])
    check("phase BLOCKING", snap.phase is Phase.BLOCKING, snap.phase)

    by_code = {c.code: c for c in snap.board}
    elusive_attacker = snap.enemy_attack_row[0]

    check("insaisissable non bloquable par une unité normale",
          actions.can_block_attacker(by_code["BRUTE"], elusive_attacker) is False)
    check("insaisissable bloquable par une insaisissable",
          actions.can_block_attacker(by_code["ELUSIVE"], elusive_attacker) is True)
    check("Can't Block ne bloque jamais",
          actions.can_block_attacker(by_code["NOBLOCK"], elusive_attacker) is False)

    # Redoutable : 3 d'attaque minimum.
    snap = blocking_snapshot(["SMALL", "BRUTE"], ["FEARSOME"])
    by_code = {c.code: c for c in snap.board}
    fearsome = snap.enemy_attack_row[0]
    check("redoutable non bloquable à 1 d'attaque",
          actions.can_block_attacker(by_code["SMALL"], fearsome) is False)
    check("redoutable bloquable à 5 d'attaque",
          actions.can_block_attacker(by_code["BRUTE"], fearsome) is True)


def test_block_scoring():
    print("\nQualité des blocages")

    snap = blocking_snapshot(["WALL", "BRUTE", "SMALL"], ["UNIT_A"])
    by_code = {c.code: c for c in snap.board}
    attacker = snap.enemy_attack_row[0]     # Garde de Fer 3/4

    # Brute 5/5 : tue le 3/4 et survit à ses 3 dégâts.
    check("tuer et survivre = 3",
          actions.block_score(by_code["BRUTE"], attacker) == actions.BLOCK_KILL_AND_SURVIVE)
    # Muraille 1/7 : survit largement mais ne tue pas.
    check("survivre sans tuer = 2",
          actions.block_score(by_code["WALL"], attacker) == actions.BLOCK_SURVIVE)
    # Recrue 1/2 : meurt et ne tue pas.
    check("mourir sans tuer = 0",
          actions.block_score(by_code["SMALL"], attacker) == actions.BLOCK_CHUMP)


def test_block_plan_prefers_small_at_equal_value():
    print("\nChoix du bloqueur")

    # Muraille 1/7 et Brute 5/5 survivent toutes deux à une Recrue 1/2,
    # mais seule la Brute la tue : elle doit être préférée.
    snap = blocking_snapshot(["WALL", "BRUTE"], ["SMALL"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("un blocage planifié", len(pairs) == 1, pairs)
    check("meilleur score choisi", pairs[0][0].code == "BRUTE", pairs[0][0].code)
    check("aucun dégât ne passe", leaking == 0, leaking)

    # Deux murailles équivalentes en valeur : la plus petite est engagée,
    # pour garder la grosse comme attaquante.
    snap = blocking_snapshot(["WALL", "UNIT_A"], ["SMALL"])
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    engaged = pairs[0][0]
    check("à valeur égale, la plus petite bloque",
          engaged.attack + engaged.health <= 7, str(engaged))


def test_no_chump_block_when_safe():
    print("\nPas de sacrifice inutile")

    # Recrue 1/2 face à une Brute 5/5 : elle meurt sans rien tuer.
    snap = blocking_snapshot(["SMALL"], ["BRUTE"])
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=20)

    check("aucun blocage sacrificiel", pairs == [], pairs)
    check("dégâts assumés", leaking == 5, leaking)
    check("raison chiffrée", "20 PV" in reason, reason)


def test_chump_block_when_lethal():
    print("\nSacrifice si létal")

    snap = blocking_snapshot(["SMALL"], ["BRUTE"])
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=4)

    check("blocage sacrificiel accepté", len(pairs) == 1, pairs)
    check("plus aucun dégât", leaking == 0, leaking)
    check("raison explicite", "létal" in reason, reason)

    # PV inconnus : on ne sacrifie pas, mais on le signale.
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=None)
    check("PV illisibles -> pas de sacrifice", pairs == [], pairs)
    check("incertitude signalée", "illisibles" in reason, reason)

    # Option explicite : sacrifier même hors situation létale.
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20, allow_chump=True)
    check("option chump respectée", len(pairs) == 1, pairs)


def test_one_blocker_per_attacker():
    print("\nUn bloqueur par attaquant")

    snap = blocking_snapshot(["BRUTE", "WALL"], ["UNIT_A", "UNIT_A"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)

    check("deux blocages", len(pairs) == 2, pairs)
    blockers = [b.card_id for b, _ in pairs]
    attackers = [a.card_id for _, a in pairs]
    check("aucun bloqueur réutilisé", len(set(blockers)) == 2, blockers)
    check("aucun attaquant doublé", len(set(attackers)) == 2, attackers)
    check("rien ne passe", leaking == 0, leaking)

    # Plus d'attaquants que de bloqueurs : le plus dangereux est traité
    # en premier, le reste passe.
    snap = blocking_snapshot(["BRUTE"], ["SMALL", "UNIT_A"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("le plus dangereux est bloqué", pairs[0][1].code == "UNIT_A", pairs[0][1].code)
    check("les dégâts restants sont comptés", leaking == 1, leaking)


def pulled_blocking_snapshot(bench, pulled, attackers):
    """
    L'adversaire attaque, et il a TIRÉ certaines de nos unités en face de
    ses attaquants (Challenger). `pulled` et `attackers` sont des couples
    (code, x) : l'unité tirée se tient à la verticale de son attaquant.
    """
    with_db(ALL_CARDS)
    rects, card_id = list(nexus_rects()), 400
    for index, code in enumerate(bench):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=300 + 130 * index))
    for code, x in pulled:
        card_id += 1
        rects.append(rect_at_ratio(0.320, code=code, card_id=card_id, x=x))
    for code, x in attackers:
        card_id += 1
        rects.append(rect_at_ratio(0.650, code=code, card_id=card_id, local=False, x=x))
    install_fakes(rects, screen=make_screen(orb_active=True, token="adversaire"))
    return state_reader().snapshot()


def test_pulled_units_already_block_their_attacker():
    """
    UNE UNITÉ TIRÉE PAR UN CHALLENGER BLOQUE DÉJÀ : ON NE LUI DOUBLE PAS
    UN BLOQUEUR DU BANC.

    Signalé par Ewan le 03/09/2026 : le bot glissait une unité du banc sur
    l'attaquant déjà bloqué par l'unité tirée — geste refusé par le jeu —
    pendant que l'autre attaquant passait.
    """
    print("\nChallenger : l'attaquant déjà bloqué ne l'est pas deux fois")

    snap = pulled_blocking_snapshot(
        bench=["WALL"], pulled=[("SMALL", 640)], attackers=[("BRUTE", 640), ("UNIT_A", 900)],
    )
    check("phase BLOCKING", snap.phase is Phase.BLOCKING, snap.phase)
    already = actions.pulled_blocks(snap)
    check("le blocage en place est reconnu : SMALL devant BRUTE",
          [(b.code, a.code) for b, a in already] == [("SMALL", "BRUTE")], already)

    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=20)
    check("un seul blocage à réaliser", len(pairs) == 1, pairs)
    check("   le banc va sur l'attaquant LIBRE (UNIT_A), pas sur BRUTE",
          pairs and pairs[0][1].code == "UNIT_A" and pairs[0][0].code == "WALL", pairs)
    check("   la raison le dit", "déjà bloqué" in reason, reason)
    check("   rien ne passe", leaking == 0, leaking)

    # Tout est déjà couvert : rien à glisser, et on le dit.
    snap = pulled_blocking_snapshot(bench=["WALL"], pulled=[("SMALL", 640)], attackers=[("BRUTE", 640)])
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=20)
    check("tout déjà bloqué : aucune paire", pairs == [], pairs)
    check("   et c'est nommé", "déjà bloqué" in reason, reason)

    # Une unité tirée LOIN de tout attaquant n'est associée à personne :
    # l'attaquant reste libre et le banc le bloque.
    snap = pulled_blocking_snapshot(bench=["WALL"], pulled=[("SMALL", 200)], attackers=[("UNIT_A", 900)])
    check("écart trop grand : aucun blocage supposé", actions.pulled_blocks(snap) == [])
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    check("   le banc bloque donc l'attaquant", len(pairs) == 1 and pairs[0][1].code == "UNIT_A", pairs)

    # De bout en bout : execute_blocks ne glisse QUE le bloqueur du banc.
    snap = pulled_blocking_snapshot(
        bench=["WALL"], pulled=[("SMALL", 640)], attackers=[("BRUTE", 640), ("UNIT_A", 900)],
    )
    saved = (actions.read_nexus_health, actions.wait_for_change, actions.wait_for_combat_resolution)
    actions.read_nexus_health = lambda *a, **k: 20
    actions.wait_for_change = lambda reader, before, **k: snap
    actions.wait_for_combat_resolution = lambda reader, **k: snap
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        done, _, log = actions.execute_blocks(FakeReader([snap]), snap)
    finally:
        restore()
        (actions.read_nexus_health, actions.wait_for_change, actions.wait_for_combat_resolution) = saved
    check("un seul glissé, celui du banc", len(recorder.drags) == 1, recorder.drags)
    unit_a = next(c for c in snap.enemy_attack_row if c.code == "UNIT_A")
    check("   vers UNIT_A", recorder.drags and recorder.drags[0][1] == unit_a.center, recorder.drags)
    check("   puis la confirmation", len(clics) == 1, clics)


def test_attack_under_the_stack_is_blocked_before_passing():
    """
    UNE ATTAQUE ADVERSE SOUS LA PILE SE BLOQUE AVANT LE « OK ».

    Signalé par Ewan le 04/09/2026 (boss Jhin) : ses attaquants portent
    des compétences « Attaque : », la pile se remplit à la déclaration, la
    phase lue est SPELL_STACK et « on passe (OK) » confirmait en fait
    « aucun blocage ». Quatre attaques encaissées, nexus détruit, sans
    qu'une seule ligne « Plan de blocage » apparaisse.
    """
    print("\nAttaque adverse sous la pile : bloquer avant de passer")

    with_db(ALL_CARDS)
    # Son sort sur la pile, SMALL avancée chez lui, BRUTE à notre banc.
    snap = variant_scene([
        ("SPELL_A", 90, 0.48, 900, False),
        ("SMALL", 91, 0.650, 700, False),
        ("BRUTE", 92, 0.150, 600),
    ], "adversaire")
    check("phase lue : SPELL_STACK (la pile prime)", snap.phase is Phase.SPELL_STACK, snap.phase)
    check("   et l'attaquant est bien vu", [c.code for c in snap.enemy_attack_row] == ["SMALL"],
          snap.enemy_attack_row)
    # Après le glissé : BRUTE a quitté le banc pour la ligne de front.
    apres = variant_scene([
        ("SPELL_A", 90, 0.48, 900, False),
        ("SMALL", 91, 0.650, 700, False),
        ("BRUTE", 92, 0.320, 700),
    ], "adversaire")

    saved = (actions.read_mana_pool, actions.read_nexus_health,
             actions.wait_for_change, actions.wait_for_combat_resolution)
    actions.read_mana_pool = lambda **_: ManaPool(mana=0, spell_mana=0)
    actions.read_nexus_health = lambda *a, **k: 20
    actions.wait_for_change = lambda reader, before, **k: apres
    actions.wait_for_combat_resolution = lambda reader, **k: apres
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        log = actions.respond_to_stack(FakeReader([snap]), snap, allow_spells=True)
    finally:
        restore()
        (actions.read_mana_pool, actions.read_nexus_health,
         actions.wait_for_change, actions.wait_for_combat_resolution) = saved

    brute = next(c for c in snap.board if c.code == "BRUTE")
    small = snap.enemy_attack_row[0]
    check("un glissé : BRUTE bloque SMALL",
          recorder.drags == [(brute.grab_point, small.center)], recorder.drags)
    check("   puis UN clic (la confirmation, qui résout aussi la pile)", len(clics) == 1, clics)
    check("   le blocage est compté", getattr(log, "blocks", 0) == 1, log.blocks)
    check("   le journal l'explique",
          any("sous la pile" in e for e in log.entries) and any("Plan de blocage" in e for e in log.entries),
          log.entries)
    check("   pas de « On passe » aveugle", not any(e.startswith("On passe") for e in log.entries), log.entries)

    # Sans attaquant avancé, rien ne change : on passe d'un clic.
    calme = variant_scene([("SPELL_A", 90, 0.48, 900, False), ("BRUTE", 92, 0.150, 600)], "adversaire")
    (recorder, cancels, clics), restore = _record_gestures()
    actions.read_mana_pool = lambda **_: ManaPool(mana=0, spell_mana=0)
    try:
        log = actions.respond_to_stack(FakeReader([calme]), calme, allow_spells=True)
    finally:
        restore()
        actions.read_mana_pool = saved[0]
    check("sans attaque : aucun glissé, un clic de passe",
          recorder.drags == [] and len(clics) == 1 and log.blocks == 0, (recorder.drags, clics))


def test_block_confirms_even_with_nothing():
    print("\nConfirmation du blocage")

    resolved = blocking_snapshot(["SMALL"], [])      # combat terminé
    snap = blocking_snapshot(["SMALL"], ["BRUTE"])   # aucun blocage rentable
    clicks = []
    recorder = DragRecorder()
    original_drag, original_click = actions.drag, actions.click
    original_health = actions.read_nexus_health
    actions.drag = recorder
    actions.click = lambda *a, **k: clicks.append(a)
    actions.read_nexus_health = lambda *a, **k: 20
    try:
        done, _, log = actions.execute_blocks(
            FakeReader([snap] * 4, resolved=resolved), snap
        )
        check("aucun blocage effectué", done == [], done)
        check("aucun drag", recorder.drags == [], recorder.drags)
        # Contrairement à l'attaque : le jeu ATTEND une réponse, et « je ne
        # bloque rien » en est une. Ne pas cliquer figerait la partie.
        check("confirmation quand même envoyée", len(clicks) == 1, clicks)
        check("décision journalisée", any("dégâts" in e for e in log.entries), log.entries)
    finally:
        actions.drag, actions.click = original_drag, original_click
        actions.read_nexus_health = original_health


def test_attack_avoids_suicide():
    print("\nPrudence à l'attaque")

    # Notre Recrue 1/2 face à leur Brute 5/5 : attaquer, c'est la donner.
    snap = blocking_snapshot(["SMALL"], [])
    # (il y avait ici un `from test_actions import blocking_snapshot as _bs`
    # inutilisé. Lancée en script, cette suite est `__main__` : cette ligne
    # IMPORTAIT UNE SECONDE COPIE du module et rejouait tout son corps —
    # donc tous les bouchons posés à l'import, qui écrivaient ensuite dans
    # les listes de la COPIE. `PILES_BLOQUEES` paraissait vide alors que la
    # capture avait bien été demandée. Ne pas la remettre.)
    snap = board_versus(["SMALL"], ["BRUTE"])
    engaged, report, reason = actions.plan_attack(snap)
    check("aucune attaque suicidaire", engaged == [], [c.name for c in engaged])
    check("raison explicite", "rentable" in reason or "défense" in reason, reason)

    # Notre Brute 5/5 face à leur Recrue 1/2 : l'échange est pour nous.
    snap = board_versus(["BRUTE"], ["SMALL"])
    engaged, report, reason = actions.plan_attack(snap)
    check("attaque rentable engagée", len(engaged) == 1, [c.name for c in engaged])

    # Sans bloqueur en face, tout passe au nexus.
    snap = board_versus(["SMALL", "BRUTE"], [])
    engaged, report, reason = actions.plan_attack(snap)
    check("plateau adverse vide -> tout attaque", len(engaged) == 2, len(engaged))
    check("dégâts au nexus comptés", report["nexus_damage"] == 6, report["nexus_damage"])


def test_lethal_overrides_value():
    print("\nLe létal passe avant la valeur")

    # Notre Recrue 1/2 face à leur Brute 5/5 : échange désastreux, donc
    # aucune attaque en temps normal.
    snap = board_versus(["SMALL"], ["BRUTE"])
    engaged, _, _ = actions.plan_attack(snap, enemy_nexus_health=None)
    check("sans PV connus, on n'attaque pas", engaged == [], [c.name for c in engaged])

    # Même plateau, mais l'adversaire est à 1 PV : la Recrue passe-t-elle ?
    # Non — la Brute la bloque, donc rien n'atteint le nexus.
    engaged, report, reason = actions.plan_attack(snap, enemy_nexus_health=1)
    check("bloqué -> pas de létal", engaged == [], reason)

    # Sans bloqueur en face et 1 PV : c'est gagné, il faut foncer.
    snap = board_versus(["SMALL"], [])
    engaged, report, reason = actions.plan_attack(snap, enemy_nexus_health=1)
    check("létal détecté", len(engaged) == 1, [c.name for c in engaged])
    check("raison explicite", "létal" in reason, reason)

    # Et le létal prime même sur un échange perdant : deux petites unités
    # face à une grosse, mais les dégâts suffisent à finir.
    snap = board_versus(["SMALL", "BRUTE"], ["WALL"])
    engaged, report, reason = actions.plan_attack(snap, enemy_nexus_health=1)
    check("échange perdant accepté si létal", "létal" in reason, reason)


def test_attack_keeps_the_useful_ones():
    print("\nAttaque partielle")

    # Une Brute 5/5 rentable et une Recrue 1/2 suicidaire : le bot doit
    # engager la première sans sacrifier la seconde.
    snap = board_versus(["BRUTE", "SMALL"], ["UNIT_A"])
    engaged, report, reason = actions.plan_attack(snap)
    names = [c.name for c in engaged]

    check("au moins un attaquant retenu", len(engaged) >= 1, names)
    check("bilan positif", report["profit"] >= 0, report["profit"])
    # Le point de l'exercice : ce n'est plus tout ou rien.
    check("tri effectué", len(engaged) <= 2, names)


def test_overwhelm_pierces_the_blocker():
    print("\nSubmersion au blocage")

    snap = board_versus([], [], enemy_attackers=["TRAMPLE"])
    attacker = snap.enemy_attack_row[0]
    check("attaquant Submersion reconnu", attacker.has("Overwhelm"))

    wall = next(c for c in board_versus(["WALL"], []).board)
    small = next(c for c in board_versus(["SMALL"], []).board)

    # 6 d'attaque contre un bloqueur à 2 PV : 4 passent quand même.
    check("excédent calculé", actions.damage_through(small, attacker) == 4,
          actions.damage_through(small, attacker))
    # Contre 7 PV, rien ne traverse.
    check("gros bloqueur absorbe tout", actions.damage_through(wall, attacker) == 0,
          actions.damage_through(wall, attacker))

    # Et le plan de blocage compte cet excédent dans les dégâts subis.
    snap = board_versus(["SMALL"], [], enemy_attackers=["TRAMPLE"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=3, allow_chump=True)
    check("blocage sacrificiel tenté", len(pairs) == 1, pairs)
    check("dégâts traversants comptés", leaking == 4, leaking)


# ============================================================
# LES MOTS-CLÉS DANS LA DÉCISION
# ============================================================
# La physique du duel est testée à part (test_keywords.py). Ici on
# vérifie qu'elle CHANGE bien ce que le bot décide — un calcul juste
# dont aucune décision ne dépend ne sert à rien.

def test_formidable_gets_to_attack():
    print("\nFormidable attaque enfin")

    # Un 0/7 Formidable frappe pour 7. L'ancien filtre `attack > 0` le
    # laissait au banc à chaque tour de la partie.
    snap = board_versus(["FORMIDABLE"], [])
    names = [c.name for c in actions.attackers_available(snap)]
    check("Formidable retenue comme attaquante", "Titan" in names, names)

    engaged, report, _ = actions.plan_attack(snap)
    check("engagée", len(engaged) == 1, [c.name for c in engaged])
    check("frappe comptée à 7", report["nexus_damage"] == 7, report["nexus_damage"])

    # Et elle a le droit de bloquer un Redoutable : c'est sa PUISSANCE
    # qui doit atteindre 3, pas son attaque affichée.
    snap = board_versus(["FORMIDABLE"], [], enemy_attackers=["FEARSOME"])
    titan = snap.board[0]
    fearsome = snap.enemy_attack_row[0]
    check("Formidable peut bloquer un Redoutable",
          actions.can_block_attacker(titan, fearsome) is True)


def test_quickstrike_changes_the_verdict():
    print("\nFrappe Rapide")

    # À l'ATTAQUE : notre 3/3 Frappe Rapide contre leur 4/4. Elle frappe
    # d'abord, ne tue pas (3 < 4), donc encaisse la riposte : l'échange
    # reste mauvais et le bot ne doit pas y aller.
    snap = board_versus(["QUICK"], ["VANILLA44"])
    engaged, _, _ = actions.plan_attack(snap)
    check("une frappe rapide qui ne tue pas ne suffit pas", engaged == [],
          [c.name for c in engaged])

    # AU BLOCAGE : leur 3/3 Frappe Rapide attaque, notre 3/3 vanille
    # voudrait échanger. Elle mourrait SANS RIPOSTER — ce n'est pas un
    # échange, c'est un cadeau. L'ancien score y voyait BLOCK_TRADE.
    snap = board_versus(["VANILLA33"], [], enemy_attackers=["QUICK"])
    blocker = snap.board[0]
    attacker = snap.enemy_attack_row[0]
    check("bloquer une frappe rapide n'échange rien",
          actions.block_score(blocker, attacker) == actions.BLOCK_CHUMP,
          actions.block_score(blocker, attacker))

    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("blocage gratuit refusé", pairs == [], pairs)
    check("dégâts assumés", leaking == 3, leaking)


def test_barrier_blocks_for_free():
    print("\nBarrière au blocage")

    # Notre 2/2 Barrière face à leur 6/6 Submersion : elle ne prend rien,
    # donc elle survit ET elle absorbe tout. C'est le meilleur blocage du
    # jeu, et l'ancien calcul le comptait comme une perte sèche.
    snap = board_versus(["BARRIER"], [], enemy_attackers=["TRAMPLE"])
    blocker, attacker = snap.board[0], snap.enemy_attack_row[0]

    check("le bloqueur survit", actions.block_score(blocker, attacker) == actions.BLOCK_SURVIVE,
          actions.block_score(blocker, attacker))
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("blocage engagé", len(pairs) == 1, pairs)
    check("rien ne traverse la barrière", leaking == 0, leaking)


def test_tough_survives_the_trade():
    print("\nCoriace au blocage")

    # Leur 3/3 attaque. Notre Coriace 1/3 ne prend que 2 dégâts : il
    # survit. Il passe donc devant une vanille de mêmes stats.
    snap = board_versus(["TOUGHY", "VANILLA33"], [], enemy_attackers=["VANILLA33"])
    attacker = snap.enemy_attack_row[0]
    toughy = next(c for c in snap.board if c.code == "TOUGHY")

    check("le Coriace survit au blocage",
          actions.block_score(toughy, attacker) == actions.BLOCK_SURVIVE,
          actions.block_score(toughy, attacker))

    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("un seul bloqueur engagé", len(pairs) == 1, pairs)
    check("et c'est le Coriace", pairs and pairs[0][0].code == "TOUGHY",
          [b.name for b, _ in pairs])
    check("rien ne passe", leaking == 0, leaking)


def test_impact_leaks_through_a_perfect_block():
    print("\nImpact traverse un blocage parfait")

    # Leur 2/2 Impact attaque, notre Muraille 1/7 le bloque et survit.
    # Le blocage est parfait et 1 dégât passe quand même : l'ancien
    # `damage_through` rendait 0, et le bot pouvait mourir sur ce point.
    snap = board_versus(["WALL"], [], enemy_attackers=["IMPACT"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("blocage engagé", len(pairs) == 1, pairs)
    check("le point d'Impact est compté", leaking == 1, leaking)

    # À 1 PV, ce point est LÉTAL même en bloquant tout.
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=1)
    check("létal détecté malgré le blocage", leaking == 1, (leaking, reason))


def test_ephemeral_costs_nothing_to_lose():
    print("\nÉphémère : sa mort est gratuite")

    # À L'ATTAQUE : notre Éphémère 4/4 contre leur 5/5. On la perd sans
    # rien tuer — mais elle meurt en fin de round de toute façon, donc
    # l'attaque ne coûte rien. Une vanille de mêmes stats resterait au banc.
    snap = board_versus(["EPHEMERAL"], ["BRUTE"])
    engaged, report, _ = actions.plan_attack(snap)
    check("l'Éphémère attaque quand même", len(engaged) == 1, [c.name for c in engaged])
    check("sa perte n'est pas comptée", report["our_loss"] == 0, report["our_loss"])

    snap = board_versus(["VANILLA44"], ["BRUTE"])
    engaged, _, _ = actions.plan_attack(snap)
    check("la vanille reste au banc", engaged == [], [c.name for c in engaged])

    # AU BLOCAGE : à qualité de blocage ÉGALE, on engage l'Éphémère et on
    # garde la vanille. Leur 5/4 se fait tuer par l'une comme par l'autre.
    snap = board_versus(["EPHEMERAL", "VANILLA44"], [], enemy_attackers=["STRIKER54"])
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    check("un bloqueur engagé", len(pairs) == 1, pairs)
    check("et c'est l'Éphémère", pairs and pairs[0][0].code == "EPHEMERAL",
          [b.name for b, _ in pairs])


def test_ephemeral_blocks_for_free():
    print("\nÉphémère : le blocage sacrificiel ne coûte rien")

    # Leur Piétineur 6/6 (Submersion) attaque. Notre Spectre 4/4 ne peut
    # que se jeter devant : il ne le tue pas, il meurt. À 20 PV ce n'est
    # PAS létal — l'ancienne règle refusait donc le blocage, alors qu'il
    # absorbe 4 dégâts et ne coûte RIEN : le Spectre meurt en fin de round
    # de toute façon, et ce round est celui de l'adversaire.
    snap = board_versus(["EPHEMERAL"], [], enemy_attackers=["TRAMPLE"])
    pairs, leaking, reason = actions.plan_blocks(snap, nexus_health=20)
    check("l'Éphémère se jette devant", len(pairs) == 1, (pairs, reason))
    check("seul l'excédent de Submersion passe", leaking == 2, (leaking, reason))
    check("le motif dit que c'est gratuit", "gratuit" in reason, reason)

    # La même unité SANS le mot-clé reste au banc : sa mort, elle, coûte.
    snap = board_versus(["VANILLA44"], [], enemy_attackers=["TRAMPLE"])
    pairs, leaking, _ = actions.plan_blocks(snap, nexus_health=20)
    check("la vanille ne se sacrifie pas", pairs == [], pairs)
    check("et les 6 dégâts passent", leaking == 6, leaking)

    # Une Sans-mort non plus : elle revient à 1 PV et sa résurrection est
    # dépensée. `death_cost` met les deux à zéro, `dies_anyway` les sépare
    # — c'est toute la raison d'être de cette seconde fonction.
    snap = board_versus(["DEATHLESS"], [], enemy_attackers=["TRAMPLE"])
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    check("la Sans-mort ne se sacrifie pas", pairs == [], pairs)

    # Le blocage gratuit ne remplace pas le bon blocage : la vanille prend
    # le duel qu'elle gagne, l'Éphémère va devant le second attaquant.
    snap = board_versus(["VANILLA44", "EPHEMERAL"], [],
                        enemy_attackers=["VANILLA33", "TRAMPLE"])
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    engaged = {b.code: a.code for b, a in pairs}
    check("la vanille garde son échange favorable",
          engaged.get("VANILLA44") == "VANILLA33", engaged)
    check("l'Éphémère prend le Piétineur",
          engaged.get("EPHEMERAL") == "TRAMPLE", engaged)


def test_ephemeral_is_played_when_it_can_swing():
    print("\nÉphémère : posée quand elle peut frapper")

    with_db({**ALL_CARDS, **KEYWORD_CARDS})
    pool = ManaPool(mana=3, spell_mana=0)
    main = ["EPHEMERAL", "VANILLA33"]

    # Même coût (3), et l'Éphémère est le PLUS GROS corps : 4/4 contre
    # 3/3. Le critère de corpulence la faisait donc toujours passer
    # devant — or elle ne vaut que le round en cours.
    #
    # AVEC LE JETON, elle va justement attaquer : sa taille compte.
    avec = snapshot_with(hand_codes=main, token="nous")
    codes = [c.code for c in playable_cards(avec, pool)]
    check("avec le jeton, l'Éphémère d'abord", codes[:1] == ["EPHEMERAL"], codes)

    # SANS LE JETON, elle mourra en fin de round sans avoir frappé : on
    # pose le corps qui reste, malgré ses stats plus faibles.
    sans = snapshot_with(hand_codes=main, token="adversaire")
    check("le jeton est bien à eux", sans.attack_token is False, sans.attack_token)
    codes = [c.code for c in playable_cards(sans, pool)]
    check("sans le jeton, la permanente d'abord", codes[:1] == ["VANILLA33"], codes)

    # Jeton ILLISIBLE : on suppose qu'on ne l'a pas. Se tromper dans ce
    # sens pose une permanente au lieu d'une Éphémère (anodin) ; l'inverse
    # gaspille une carte.
    muet = replace(sans, attack_token=None)
    codes = [c.code for c in playable_cards(muet, pool)]
    check("jeton illisible : prudence", codes[:1] == ["VANILLA33"], codes)

    # Le coût reste le critère PREMIER : le jeton ne réordonne qu'à coût
    # égal, il ne fait pas passer une petite carte devant une grosse.
    riche = snapshot_with(hand_codes=["EPHEMERAL", "UNIT_BIG"], token="adversaire")
    codes = [c.code for c in playable_cards(riche, ManaPool(mana=10, spell_mana=0))]
    check("le coût passe avant tout", codes[:1] == ["UNIT_BIG"], codes)


# ============================================================
# DÉFI (CHALLENGER / VULNERABLE)
# ============================================================
# Le tirage a deux effets, et le second vaut souvent plus que le
# premier : l'unité tirée bloque NOTRE unité, donc elle ne bloque plus
# personne d'autre. C'est ce que ces tests vérifient — pas seulement
# « le duel imposé est bon », mais « l'attaque entière devient bonne ».

def test_challenge_turns_a_bad_attack_into_a_good_one():
    print("\nDéfi : tirer le bon bloqueur")

    # Notre Provocateur 6/6 (Challenger) et notre Brute 5/5 contre leur
    # Frappeur 5/4 et leur Muraille 1/7.
    #
    # SANS DÉFI, l'adversaire choisit bien : la Muraille encaisse le
    # Provocateur sans mourir, et le Frappeur échange avec la Brute. On
    # perd 10, on tue 9, rien au nexus — bilan négatif, le bot renonce à
    # un attaquant.
    #
    # AVEC LE DÉFI, le Provocateur TIRE le Frappeur : il le tue sans
    # mourir (6 >= 4, et 5 < 6), et la Muraille — occupée par personne —
    # ne peut plus qu'encaisser la Brute. On ne perd rien, on tue 9.
    snap = board_versus(["CHALLENGER", "BRUTE"], ["STRIKER54", "WALL"])
    blockers = [c for c in snap.enemy_board if c.is_unit]
    ours = list(actions.attackers_available(snap))

    sans = actions.evaluate_attack(ours, blockers)
    check("sans défi, le bilan est négatif", sans["profit"] < 0, sans["profit"])

    challenges = actions.plan_challenges(ours, blockers)
    check("un tirage retenu", len(challenges) == 1, challenges)
    tire = list(challenges.values())
    check("et c'est le Frappeur qui est tiré",
          tire and tire[0].name == "Frappeur", [c.name for c in tire])

    avec = actions.evaluate_attack(ours, blockers, challenges)
    check("le bilan devient positif", avec["profit"] > 0, avec["profit"])
    check("on ne perd plus rien", avec["our_loss"] == 0, avec["our_loss"])

    # Et le plan complet engage donc les DEUX unités, au lieu d'en
    # sacrifier une.
    engaged, report, reason = actions.plan_attack(snap)
    check("les deux attaquent", len(engaged) == 2, [c.name for c in engaged])
    check("le tirage est dans le bilan", report["challenges"] == challenges, report["challenges"])
    check("et annoncé dans la raison", "tire Frappeur" in reason, reason)


def test_a_low_enemy_nexus_makes_the_bot_attack():
    """
    CHANTIER 5 (06/09/2026) : le nexus est l'objectif. Trois 4/3 face à un
    3/5 (qui tue le sien) et un 1/5 (qui absorbe) : un seul attaquant
    passe, 4 dégâts pour une unité perdue (7). À 30 PV adverses (poids
    1,33) c'est défavorable, le banc reste en défense ; à 10 PV (poids 4)
    les 4 dégâts valent 16, on attaque avec tout. PV inconnus : poids de
    base, ancien comportement.
    """
    print("\nPression sur le nexus : plus il est bas, plus on attaque")

    with_db({**ALL_CARDS, **KEYWORD_CARDS,
             "FOUR3": {"name": "Quatre-trois", "cost": 3, "attack": 4, "health": 3,
                       "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
             "WALL35": {"name": "Mur", "cost": 4, "attack": 3, "health": 5,
                        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
             "SPONGE15": {"name": "Éponge", "cost": 3, "attack": 1, "health": 5,
                          "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""}})
    rects, card_id = list(nexus_rects()), 300
    for index in range(3):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code="FOUR3", card_id=card_id, x=400 + 130 * index))
    rects.append(rect_at_ratio(0.800, code="WALL35", card_id=900, local=False, x=600))
    rects.append(rect_at_ratio(0.800, code="SPONGE15", card_id=901, local=False, x=760))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = state_reader().snapshot()

    check("poids : inconnu → 1, 30 PV → 1,33, 10 PV → 4, 2 PV → plafond 6",
          (actions.nexus_weight(None), round(actions.nexus_weight(30), 2),
           actions.nexus_weight(10), actions.nexus_weight(2)) == (1.0, 1.33, 4.0, 6.0),
          (actions.nexus_weight(None), actions.nexus_weight(30), actions.nexus_weight(10), actions.nexus_weight(2)))

    sans, _, why_sans = actions.plan_attack(snap, None)
    haut, _, why_haut = actions.plan_attack(snap, 30)
    bas, rapport, why_bas = actions.plan_attack(snap, 10)
    check("PV inconnus : perdre 7 pour passer 4, on garde le banc", sans == [], why_sans)
    check("30 PV : toujours défavorable", haut == [], why_haut)
    check("10 PV : on attaque avec tout le banc", len(bas) == 3, (why_bas, len(bas)))
    check("   et le journal donne le poids", "vaut 4" in why_bas, why_bas)
    check("   un attaquant passe : 4 au nexus", rapport["nexus_damage"] == 4, rapport)

    letal, _, why = actions.plan_attack(snap, 4)
    check("4 PV : attaque létale, quel qu'en soit le prix", len(letal) == 3 and "létale" in why, why)


def test_le_mode_plan_lit_les_pv_du_nexus():
    """
    `--plan` MONTRAIT UNE DÉCISION QUE LE BOT N'AURAIT PAS PRISE.

    `declare_attack` et `execute_blocks` écrivaient
    `None if dry_run else read_nexus_health(...)` : en mode plan, les PV
    du nexus n'étaient jamais lus, donc `nexus_weight` rendait son poids
    de BASE (1 par défaut) là où la vraie décision pouvait monter
    jusqu'à 6 (`max(1, 40/pv)`, plafond 6).

    Le même plateau que `test_a_low_enemy_nexus_makes_the_bot_attack`
    suffit à mesurer l'écart : trois 4/3 face à un 3/5 et un 1/5.
        PV inconnus (ce que `--plan` voyait) : « on garde le banc »
        10 PV adverses (ce que le bot fait)  : on attaque avec TOUT
    Au blocage c'est la même chose, et c'est pire : à 4 PV le sacrifice
    est accepté (« létal »), PV inconnus il est refusé — `python
    actions.py block --plan` annonçait donc « on encaisse » juste avant
    que le bot ne bloque.

    `dry_run` veut dire « AUCUN GESTE », pas « aucune lecture » : la
    preuve, `enrich_with_live_stats` est appelé dans les deux modes, deux
    lignes au-dessus, et `play_hand` lit les coûts à l'écran en mode plan
    comme ailleurs. Les PV du nexus étaient la seule lecture sautée.
    Corrigé le 10/11/2026.
    """
    print()
    print("Le mode plan lit les PV du nexus, comme la vraie décision")

    # ---- l'attaque -----------------------------------------------------
    # Le plateau de `test_a_low_enemy_nexus_makes_the_bot_attack`, repris
    # tel quel : c'est lui qui rend l'écart visible.
    with_db({**ALL_CARDS, **KEYWORD_CARDS,
             "FOUR3": {"name": "Quatre-trois", "cost": 3, "attack": 4, "health": 3,
                       "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
             "WALL35": {"name": "Mur", "cost": 4, "attack": 3, "health": 5,
                        "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""},
             "SPONGE15": {"name": "Éponge", "cost": 3, "attack": 1, "health": 5,
                          "type": "Unit", "keywords": [], "keywordRefs": [], "descriptionRaw": ""}})
    rects, card_id = list(nexus_rects()), 300
    for index in range(3):
        card_id += 1
        rects.append(rect_at_ratio(0.150, code="FOUR3", card_id=card_id, x=400 + 130 * index))
    rects.append(rect_at_ratio(0.800, code="WALL35", card_id=900, local=False, x=600))
    rects.append(rect_at_ratio(0.800, code="SPONGE15", card_id=901, local=False, x=760))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = state_reader().snapshot()

    # L'écart est bien réel sur ce plateau, sinon le test ne prouve rien.
    sans, _, _ = actions.plan_attack(snap, None)
    avec, _, _ = actions.plan_attack(snap, 10)
    check("plateau témoin : PV inconnus → on n'attaque pas", sans == [], sans)
    check("              : 10 PV adverses → on attaque avec tout",
          len(avec) == 3, len(avec))

    lectures = []
    (recorder, cancels, clics), restore = _record_gestures()
    original = actions.read_nexus_health

    def _lire(snapshot=None, local=True, **_):
        lectures.append(local)
        return 10

    actions.read_nexus_health = _lire
    try:
        engages, _, log = actions.declare_attack(FakeReader([snap]), snap, dry_run=True)
    finally:
        actions.read_nexus_health = original
        restore()

    check("le plan lit les PV du nexus ADVERSE", lectures == [False], lectures)
    check("   et engage les trois unités, comme la vraie attaque",
          len(engages) == 3, [c.name for c in engages])
    check("   le journal affiche le poids réel du nexus",
          any("vaut 4" in e for e in log.entries), log.entries)
    check("   et le plan n'a touché à rien",
          (recorder.drags, clics, cancels) == ([], [], []),
          (recorder.drags, clics, cancels))

    # ---- le blocage ----------------------------------------------------
    # À 4 PV le sacrifice devient létal-obligatoire ; PV inconnus, il est
    # refusé et le test le dit.
    bloc = blocking_snapshot(["SMALL"], ["BRUTE"])
    sans, _, _ = actions.plan_blocks(bloc, nexus_health=None)
    avec, _, raison = actions.plan_blocks(bloc, nexus_health=4)
    check("plateau témoin : PV inconnus → aucun sacrifice", sans == [], sans)
    check("              : 4 PV → on sacrifie", len(avec) == 1, raison)

    lectures = []
    (recorder, cancels, clics), restore = _record_gestures()
    original = actions.read_nexus_health

    def _lire_nous(snapshot=None, local=True, **_):
        lectures.append(local)
        return 4

    actions.read_nexus_health = _lire_nous
    try:
        paires, _, log = actions.execute_blocks(FakeReader([bloc]), bloc, dry_run=True)
    finally:
        actions.read_nexus_health = original
        restore()

    check("le plan lit les PV de NOTRE nexus", lectures == [True], lectures)
    check("   et prévoit le blocage sacrificiel", len(paires) == 1, paires)
    check("   en le nommant comme la vraie décision",
          any("létal" in e for e in log.entries), log.entries)
    check("   et le plan n'a toujours touché à rien",
          (recorder.drags, clics, cancels) == ([], [], []),
          (recorder.drags, clics, cancels))


def test_no_challenge_when_it_gains_nothing():
    print("\nDéfi : pas de geste inutile")

    # Notre Provocateur seul face à une Muraille 1/7 : elle le bloquerait
    # de toute façon, et le tirer ne change RIEN. Un défi coûte un
    # glisser-déposer, donc un risque de geste raté : à bilan égal on
    # engage normalement.
    snap = board_versus(["CHALLENGER"], ["WALL"])
    ours = list(actions.attackers_available(snap))
    blockers = [c for c in snap.enemy_board if c.is_unit]
    check("aucun tirage", actions.plan_challenges(ours, blockers) == {},
          actions.plan_challenges(ours, blockers))

    # Banc adverse vide : rien à tirer.
    snap = board_versus(["CHALLENGER"], [])
    ours = list(actions.attackers_available(snap))
    check("banc adverse vide", actions.plan_challenges(ours, []) == {})

    # Et une unité sans Challenger ne tire personne.
    snap = board_versus(["BRUTE"], ["STRIKER54", "WALL"])
    ours = list(actions.attackers_available(snap))
    blockers = [c for c in snap.enemy_board if c.is_unit]
    check("sans le mot-clé, aucun tirage",
          actions.plan_challenges(ours, blockers) == {})


def test_vulnerable_is_pulled_by_anyone():
    print("\nVulnerable : tirable par n'importe qui")

    # Vulnerable est sur l'unité ADVERSE : notre Brute 5/5, sans aucun
    # mot-clé, peut la tirer. Elle tue la Proie 2/3 sans mourir, alors
    # que l'adversaire aurait bloqué avec sa Muraille.
    snap = board_versus(["BRUTE"], ["VULNERABLE", "WALL"])
    ours = list(actions.attackers_available(snap))
    blockers = [c for c in snap.enemy_board if c.is_unit]

    challenges = actions.plan_challenges(ours, blockers)
    check("un tirage retenu", len(challenges) == 1, challenges)
    check("et c'est la Proie",
          list(challenges.values())[0].name == "Proie",
          [c.name for c in challenges.values()])

    report = actions.evaluate_attack(ours, blockers, challenges)
    check("la Proie meurt", report["their_loss"] == 5, report["their_loss"])
    check("et la Brute survit", report["our_loss"] == 0, report["our_loss"])


def test_challenge_is_a_single_drag_onto_the_enemy():
    print("\nDéfi : un seul glisser, sur l'unité adverse")

    # Notre Provocateur 6/6 contre leur Frappeur 5/4 laissé au banc. Sans
    # défi, le Frappeur ne bloquerait pas (il mourrait pour rien) et 6
    # dégâts passeraient. Le tirer vaut mieux : on tue 9 sans rien perdre.
    start = _challenge_snapshot(
        ours=[("CHALLENGER", 401, 400)], theirs=[("STRIKER54", 501, 900)]
    )
    after = _challenge_snapshot(
        attackers=[("CHALLENGER", 401, 400)], enemy_blockers=[("STRIKER54", 501, 900)]
    )
    resolved = _challenge_snapshot()

    ours = start.board[0]
    enemy = start.enemy_board[0]
    row_point = actions.drop_point(ours, start.window)

    reader = AnimatedReader([(start, start), (after, after)], resolved=resolved)
    recorder = DragRecorder()

    def drag_then_animate(source, destination):
        recorder(source, destination)
        reader.advance()

    original_drag, original_click = actions.drag, actions.click
    actions.drag, actions.click = drag_then_animate, lambda *a, **k: None
    try:
        engaged, _, log = actions.declare_attack(reader, start)
    finally:
        actions.drag, actions.click = original_drag, original_click

    check("un seul geste", len(recorder.drags) == 1, recorder.drags)
    check("unité engagée", len(engaged) == 1, len(engaged))
    if recorder.drags:
        source, destination = recorder.drags[0]
        check("on saisit notre unité", source == ours.grab_point, (source, ours.grab_point))
        check("on lâche SUR l'unité adverse", destination == enemy.center,
              (destination, enemy.center))
        check("    et pas dans la rangée d'attaque", destination != row_point,
              (destination, row_point))
    check("le tirage est journalisé",
          any("tirant" in e for e in log.entries), log.entries)


def test_failed_challenge_falls_back_to_a_plain_attack():
    print("\nDéfi raté : on engage quand même")

    # LE DÉFI A RATÉ, PAS L'ATTAQUE. Si le client refuse le tirage, il
    # vaut mieux engager l'unité sans lui que la laisser au banc parce
    # qu'un geste plus ambitieux a échoué.
    start = _challenge_snapshot(
        ours=[("CHALLENGER", 401, 400)], theirs=[("STRIKER54", 501, 900)]
    )
    engagee = _challenge_snapshot(
        attackers=[("CHALLENGER", 401, 400)], theirs=[("STRIKER54", 501, 900)]
    )
    resolved = _challenge_snapshot()

    ours = start.board[0]
    enemy = start.enemy_board[0]
    row_point = actions.drop_point(ours, start.window)

    reader = AnimatedReader([(start, start), (engagee, engagee)], resolved=resolved)
    recorder = DragRecorder()

    def drag_then_maybe_animate(source, destination):
        recorder(source, destination)
        # Le client REFUSE le défi : seul un dépôt dans la rangée
        # d'attaque fait avancer l'état.
        if destination != enemy.center:
            reader.advance()

    original_drag, original_click = actions.drag, actions.click
    actions.drag, actions.click = drag_then_maybe_animate, lambda *a, **k: None
    try:
        engaged, _, log = actions.declare_attack(reader, start)
    finally:
        actions.drag, actions.click = original_drag, original_click

    targets = [d for _, d in recorder.drags]
    challenge_attempts = [d for d in targets if d == enemy.center]
    check("le défi a été tenté deux fois", len(challenge_attempts) == 2, targets)
    check("puis un dépôt dans la rangée d'attaque", row_point in targets, targets)
    check("l'unité est engagée malgré tout", len(engaged) == 1, len(engaged))
    check("le repli est journalisé",
          any("engagement simple" in e for e in log.entries), log.entries)


def test_wait_for_change_returns_early():
    print("\nAttente pilotée par l'état")

    before = board_versus(["BRUTE"], [])
    after = board_versus(["BRUTE", "SMALL"], [])
    from game_state import snapshot_signature

    signature = snapshot_signature(before)
    reader = FakeReader([before, after])
    result = actions.wait_for_change(reader, signature, timeout=3.0, poll=0.0)
    check("rend la main dès que l'état change",
          snapshot_signature(result) != signature)
    # Trois lectures : deux pour voir le changement, une pour confirmer que
    # les cartes ne bougent plus. La boucle n'attend pas la fin du délai.
    check("pas d'attente inutile", reader.calls == 3, reader.calls)

    # Sans le recentrage à attendre, on retombe sur deux lectures : c'est
    # bien l'attente de stabilité qui coûte la troisième, et rien d'autre.
    reader = FakeReader([before, after])
    actions.wait_for_change(reader, signature, timeout=3.0, poll=0.0, settle=False)
    check("settle=False rend la main aussitôt", reader.calls == 2, reader.calls)


def test_play_hand_respects_phase():
    print("\nRespect de la phase")

    with_db(FULL_DB)
    rects = nexus_rects() + [rect_at_ratio(0.029, code="UNIT_A", card_id=1, height=330)]
    install_fakes(rects, screen=make_screen(orb_active=False, token="nous"))
    snap = state_reader().snapshot()

    check("phase lue OPPONENT_TURN", snap.phase is Phase.OPPONENT_TURN, snap.phase)

    recorder = DragRecorder()
    original_drag = actions.drag
    actions.drag = recorder
    try:
        played, _, log = play_hand(FakeReader([]), snap)
        check("rien joué pendant le tour adverse", played == [], played)
        check("aucun geste souris", recorder.drags == [], recorder.drags)
        check("raison journalisée", any("pas à nous" in e for e in log.entries), log.entries)
    finally:
        actions.drag = original_drag


class ClickDrivenReader:
    """
    Rend `pending` tant que moins de `after_clicks` clics ont été faits,
    puis `resolved`. C'est le jeu vu depuis la pile : l'état ne change
    qu'au clic « OK ».
    """

    def __init__(self, clics, pending, resolved, after_clicks):
        self.clics, self.pending, self.resolved, self.after = clics, pending, resolved, after_clicks
        self.calls = 0

    def stable_snapshot(self, **_):
        self.calls += 1
        return self.resolved if len(self.clics) >= self.after else self.pending

    def snapshot(self):
        return self.stable_snapshot()


def test_opponent_response_to_our_spell_is_passed_through():
    """
    L'ADVERSAIRE RÉPOND À NOTRE SORT : ON PASSE, ON N'ABANDONNE PAS.

    Signalé par Ewan le 03/09/2026. Après notre validation, son sort
    s'empile sur le nôtre ; le bot concluait « toujours sur la pile »,
    mettait la carte de côté et continuait à poser pendant que la pile
    était ouverte. Il faut recliquer « OK » jusqu'à ce que notre sort
    parte — et s'arrêter là, car une pile vide fait du bouton une fin de
    tour.
    """
    print("\nRéponse adverse à notre sort : on passe jusqu'à la résolution")

    with_db(ALL_CARDS)
    avant = variant_scene([("SPELL_A", 21, EN_MAIN, 500), ("UNIT_B", 40, 0.800, 400, False)], "nous")
    carte = {c.code: c for c in avant.hand}["SPELL_A"]
    # Notre sort ET le sien sur la pile, orbe bleue : à nous de dire OK.
    reponse = variant_scene([
        ("SPELL_A", 21, 0.48, 700), ("SPELL_A", 90, 0.48, 900, False),
        ("UNIT_B", 40, 0.800, 400, False),
    ], "nous")
    check("l'état intermédiaire est lu SPELL_STACK", reponse.phase is Phase.SPELL_STACK, reponse.phase)
    apres = variant_scene([("UNIT_B", 40, 0.800, 400, False)], "nous")

    (recorder, cancels, clics), restore = _record_gestures()
    try:
        # 1 clic de cible, 1 validation, 1 passe : la pile se vide au 3e.
        reader = ClickDrivenReader(clics, reponse, apres, after_clicks=3)
        success, _ = actions.play_spell(reader, avant, carte)
    finally:
        restore()
    check("sort résolu malgré la réponse adverse", success is True)
    check("   trois clics : cible, validation, passe", len(clics) == 3, clics)
    check("   aucune annulation", cancels == [], cancels)

    # L'adversaire répond, et répond encore : borné, on ne clique pas sans fin.
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        reader = ClickDrivenReader(clics, reponse, apres, after_clicks=999)
        success, _ = actions.play_spell(reader, avant, carte)
    finally:
        restore()
    check("pile qui ne se vide jamais : échec propre", success is False)
    check("   nombre de passes borné",
          len(clics) <= 2 + actions.STACK_PASS_ATTEMPTS, len(clics))

    # Orbe grise pendant qu'il décide : on attend, on ne clique pas.
    rects = list(nexus_rects())
    for code, cid, ratio, x, local in (("SPELL_A", 21, 0.48, 700, True),
                                        ("SPELL_A", 90, 0.48, 900, False),
                                        ("UNIT_B", 40, 0.800, 400, False)):
        rects.append(rect_at_ratio(ratio, code=code, card_id=cid, height=330, x=x, local=local))
    install_fakes(rects, screen=make_screen(orb_active=False, token="nous"))
    grise = state_reader().snapshot()
    check("orbe grise : SPELL_STACK", grise.phase is Phase.SPELL_STACK, grise.phase)
    saved_wait = actions.STACK_RESPONSE_WAIT
    actions.STACK_RESPONSE_WAIT = 0.05
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        latest = actions.let_stack_resolve(FakeReader([grise]), grise, carte)
    finally:
        restore()
        actions.STACK_RESPONSE_WAIT = saved_wait
    check("orbe grise : aucun clic, on attend", clics == [], clics)


def test_respond_to_stack():
    """
    Sort adverse sur la pile, orbe bleue : on répond avec un sort jouable
    si on en a un, sinon on passe. Orbe grise : rien.
    """
    print("\nRépondre à un sort adverse")

    with_db(ALL_CARDS)
    # SPELL_A en main (« Deal 2 to an enemy », Fast) et un ennemi à viser.
    pile = variant_scene([
        ("SPELL_A", 21, EN_MAIN, 500), ("SPELL_A", 90, 0.48, 900, False),
        ("UNIT_B", 40, 0.800, 400, False),
    ], "nous")
    check("SPELL_STACK lu", pile.phase is Phase.SPELL_STACK, pile.phase)

    saved_mana = actions.read_mana_pool
    actions.read_mana_pool = lambda **_: ManaPool(mana=4, spell_mana=0)
    joues = []
    saved_play = actions.play_spell
    actions.play_spell = (lambda reader, snap, card, dry_run=False, forced=None:
                          joues.append(card.code) or (True, snap))
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        # Son « Deal 2 to an enemy » ne menace AUCUNE de nos unités (banc
        # vide) et notre sort en main ne protège rien : la riposte
        # intelligente passe au lieu de gaspiller SPELL_A. Le cas où elle
        # riposte est dans test_riposte.py.
        log = actions.respond_to_stack(FakeReader([pile]), pile, allow_spells=True)
        check("rien à protéger : aucun sort gaspillé", joues == [], joues)
        check("   un clic de passe", len(clics) == 1, clics)
        check("   la menace est journalisée", any("Menace" in e for e in log.entries), log.entries)

        # Sorts interdits : on passe.
        clics.clear()
        log = actions.respond_to_stack(FakeReader([pile]), pile, allow_spells=False)
        check("sorts interdits : aucun sort lancé", joues == [], joues)
        check("   un clic de passe", len(clics) == 1, clics)

        # Pas de mana : on passe aussi.
        clics.clear()
        actions.read_mana_pool = lambda **_: ManaPool(mana=0, spell_mana=0)
        log = actions.respond_to_stack(FakeReader([pile]), pile, allow_spells=True)
        check("sans mana : on passe", joues == [] and len(clics) == 1, (joues, clics))

        # Orbe grise : on attend, rien n'est cliqué.
        clics.clear()
        rects = list(nexus_rects())
        rects.append(rect_at_ratio(0.48, code="SPELL_A", card_id=90, height=330, x=900, local=False))
        install_fakes(rects, screen=make_screen(orb_active=False, token="nous"))
        grise = state_reader().snapshot()
        log = actions.respond_to_stack(FakeReader([grise]), grise, allow_spells=True)
        check("orbe grise : aucun clic", clics == [] and joues == [], clics)
        check("   le journal dit qu'on attend", any("priorité" in e for e in log.entries), log.entries)
    finally:
        restore()
        actions.read_mana_pool = saved_mana
        actions.play_spell = saved_play


def test_our_spell_waiting_for_a_target_is_cancelled_not_passed():
    """
    « SÉLECTIONNER LA CIBLE » SUR LE BOUTON : C'EST NOTRE GESTE QU'ON ATTEND.

    05/09/2026 (deck Nilah) : 07BW043, un sort absent de card_sets, s'est
    retrouvé sur la pile (attrapé à la place de Slotbot pendant une
    pioche). Le jeu attendait une cible ; le bot a cliqué « OK » douze
    fois, 50 s, avant que la détection de blocage n'annule. Le libellé du
    bouton (`assets/orb/cible.png`, lu à 1.00 sur la capture) dit tout de
    suite qu'un « OK » ne servira à rien : on annule, sans passer.
    """
    print("\nNotre sort attend une cible : on annule, on ne passe pas")

    with_db(ALL_CARDS)
    rects = list(nexus_rects())
    # Une carte à NOUS sur la pile, inconnue de la base, orbe bleue.
    rects.append(rect_at_ratio(0.48, code="99XX999", card_id=90, height=330, x=900, local=True))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    snap = state_reader().snapshot()
    snap = replace(snap, phase=Phase.SPELL_STACK, button_label="cible")

    (recorder, cancels, clics), restore = _record_gestures()
    saved_sleep = actions.time.sleep
    actions.time.sleep = lambda s: None
    try:
        log = actions.respond_to_stack(FakeReader([snap]), snap, allow_spells=True)
        check("une annulation", len(cancels) == 1, cancels)
        check("   et aucun clic de passe", clics == [], clics)
        check("   le journal dit pourquoi", any("attend une cible" in e for e in log.entries), log.entries)

        # Le même écran SANS le libellé garde l'ancien traitement (passe).
        cancels.clear()
        sans = replace(snap, button_label=None)
        log = actions.respond_to_stack(FakeReader([sans]), sans, allow_spells=True)
        check("sans libellé : on passe comme avant", len(clics) == 1 and cancels == [], (clics, cancels))
    finally:
        restore()
        actions.time.sleep = saved_sleep


def _pile_avec_notre_sort(button_label, orb_active=False, fenetre=False):
    """
    L'écran d'un blocage de pile : notre sort en l'air, derrière le bouton.

    `fenetre` ajoute les trois cartes d'une fenêtre de choix, aux mesures
    de la trame réelle de Yoink! — plus grandes que tout le reste et au
    même bord haut.
    """
    specs = [("SPELL_A", 21, 0.48, 700, True),
             ("UNIT_B", 40, 0.800, 400, False)]
    if fenetre:
        specs += [
            ("THEIR_SMITH", 1278610636, FENETRE_DE_CHOIX, 670, False, HAUTEUR_FENETRE),
            ("THEIR_RISSU", 1566250659, FENETRE_DE_CHOIX, 959, False, HAUTEUR_FENETRE),
            ("THEIR_GRENADIER", 1153891470, FENETRE_DE_CHOIX, 1247, False, HAUTEUR_FENETRE),
        ]
    snap = scene(specs, orb_active=orb_active)
    return replace(snap, phase=Phase.SPELL_STACK, button_label=button_label)


def test_un_bouton_qui_reclame_une_cible_nest_pas_une_priorite_adverse():
    """
    LE LIBELLÉ DU BOUTON PASSE AVANT L'ORBE — DANS `let_stack_resolve` AUSSI.

    Le correctif du 05/11/2026 (blocage de Yoink!, 184 s, une tentative
    hebdomadaire perdue) n'avait été écrit que dans `respond_to_stack`.
    `let_stack_resolve` — l'autre endroit qui regarde la pile, celui où
    l'on arrive juste après avoir validé notre sort — ne lisait que
    `stack_theirs` puis l'orbe.

    Or l'orbe ne dit rien de qui doit agir quand le jeu réclame une
    cible : ÉTEINTE, on concluait « l'adversaire a la priorité : on
    attend » ; ALLUMÉE, on cliquait « OK » dans le vide. Les deux
    variantes ont été observées le 09/11/2026 — sept blocages, tous sur
    Flash Freeze (01FR001, « Frostbite an enemy. »), dont un au boss
    final, ~240 s — et c'est le MÊME test `turn_orb_active` qui les
    produit. D'où un seul correctif, placé AVANT lui.

    Relevé sur les 22 blocages de tout `logs/` : 4,5 s après l'abandon
    (médiane, max 5,3 s), la première lecture de `respond_to_stack`
    trouvait `button_label == "cible"` 21 fois sur 22 — le jeu affichait
    « SÉLECTIONNER LA CIBLE » pendant TOUT le blocage. 508 s perdues,
    23,1 s de moyenne.

    Ici : un tour, une annulation, zéro attente, dans les deux états de
    l'orbe.
    """
    print("\nPile : « SÉLECTIONNER LA CIBLE » l'emporte sur l'orbe")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    for orbe, nom in ((False, "orbe éteinte"), (True, "orbe allumée")):
        bloque = _pile_avec_notre_sort("cible", orb_active=orbe)
        check(f"{nom} : l'état est celui de la trace",
              bloque.turn_orb_active is orbe, bloque.turn_orb_active)
        carte = next(c for c in bloque.stack if c.local)
        check("   notre sort est bien sur la pile", carte.code == "SPELL_A", carte)
        check("   et aucune fenêtre n'est ouverte",
              actions.visible_card_window(bloque) == [],
              [c.name for c in actions.visible_card_window(bloque)])

        reader = FakeReader([bloque])
        (recorder, cancels, clics), restore = _record_gestures()
        try:
            latest = actions.let_stack_resolve(reader, bloque, carte)
        finally:
            restore()

        check("   une annulation", len(cancels) == 1, cancels)
        check("   aucun clic de passe (« OK » n'y fait rien)", clics == [], clics)
        check("   on n'a pas attendu l'adversaire une seule fois",
              reader.calls == 0, reader.calls)
        check("   la carte reste « sur la pile » : mise de côté, pas « résolue »",
              any(c.code == "SPELL_A" and c.local for c in latest.stack),
              [c.code for c in latest.stack])


def test_une_fenetre_de_choix_retient_aussi_notre_propre_sort():
    """
    LA MÊME RÈGLE, ET LE MÊME GARDE-FOU : UNE FENÊTRE NE S'ANNULE PAS.

    Sous « SÉLECTIONNER LA CIBLE », le clic droit n'a aucun effet quand
    des cartes sont proposées au centre (trois annulations sans effet
    dans la trace du 05/11). `let_stack_resolve` doit donc PRENDRE une
    carte, exactement comme `respond_to_stack` — c'est la source unique
    `geste_pour_une_cible_reclamee` qui le garantit, et c'est tout
    l'intérêt de ne pas recopier la logique : deux implémentations du
    même test finissent toujours par diverger, et ici la seconde n'avait
    même pas été écrite.
    """
    print("\nPile : une fenêtre de choix se prend, elle ne s'annule pas")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    bloque = _pile_avec_notre_sort("cible", fenetre=True)
    carte = next(c for c in bloque.stack if c.local)
    repere = actions.visible_card_window(bloque)
    check("la fenêtre est reconnue à sa forme", len(repere) == 3,
          [c.name for c in repere])

    reader = FakeReader([bloque])
    (recorder, cancels, clics), restore = _record_gestures()
    attentes = []
    saved_wait = actions.wait_for_change
    actions.wait_for_change = lambda *a, **k: (attentes.append(a), bloque)[1]
    try:
        actions.let_stack_resolve(reader, bloque, carte)
    finally:
        actions.wait_for_change = saved_wait
        restore()

    vise = next(c for c in bloque.cards() if c.code == "THEIR_GRENADIER").grab_point
    check("un clic, pas une attente", len(clics) == 1, clics)
    check("   sur la meilleure carte de la fenêtre",
          clics and clics[0] == vise, (clics, vise))
    check("   aucune annulation", cancels == [], cancels)
    # CE TEST DISAIT `reader.calls == 0`, ET C'ÉTAIT UNE VALEUR GRAVÉE,
    # PAS LA PROPRIÉTÉ VOULUE (15/11/2026). Depuis qu'une prise de carte
    # fait AVANCER la résolution, elle est suivie d'une relecture — c'est
    # tout l'objet du correctif du Joker. Ce qu'il faut garantir ici est
    # qu'on n'ATTEND PAS L'ADVERSAIRE, ce que `wait_for_change` seul
    # mesure. Troisième test du projet à tenir la main d'un défaut en
    # figeant un nombre au lieu de décrire un comportement.
    check("   et aucune attente de l'adversaire", attentes == [], attentes)
    check("   la relecture a bien eu lieu (le sort a pu avancer)",
          reader.calls == 1, reader.calls)


def test_une_orbe_grise_sans_libelle_sattend_comme_avant():
    """
    NON-RÉGRESSION : sans libellé, l'orbe grise reste une attente.

    C'est la règle d'Ewan du 03/09/2026 — l'adversaire réfléchit, il n'y
    a rien à cliquer — et le correctif ne doit surtout pas la défaire :
    annuler ici jetterait un sort que l'adversaire est en train de
    laisser passer. Seul le libellé « cible » dit que le jeu nous parle.
    """
    print("\nPile : orbe grise sans libellé, on attend comme avant")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})
    saved_wait = actions.STACK_RESPONSE_WAIT
    try:
        for libelle, nom in ((None, "aucun libellé"), ("fin_du_tour", "un autre libellé")):
            attente = _pile_avec_notre_sort(libelle)
            carte = next(c for c in attente.stack if c.local)
            actions.STACK_RESPONSE_WAIT = 0.05
            reader = FakeReader([attente])
            (recorder, cancels, clics), restore = _record_gestures()
            try:
                actions.let_stack_resolve(reader, attente, carte)
            finally:
                restore()
            check(f"{nom} : aucun clic", clics == [], clics)
            check("   aucune annulation", cancels == [], cancels)
            check("   mais on a bien attendu (l'état est relu)",
                  reader.calls > 0, reader.calls)
    finally:
        actions.STACK_RESPONSE_WAIT = saved_wait




# Les trois Destiny Cards de Twisted Fate, aux textes EXACTS de la base
# d'aventure (98BW004/5/6) — c'est ce que Wild Card (98BW003, « Play a
# Destiny Card. ») propose, et ce que le bot a vu 10 fois le 15/11.
DESTINY_CARDS = {
    "GOLD_CARD": {
        "name": "Gold Card", "cost": 0, "type": "Spell", "collectible": False,
        "descriptionRaw": "Deal 7 and Stun the strongest enemy.",
    },
    "RED_CARD": {
        "name": "Red Card", "cost": 0, "type": "Spell", "collectible": False,
        "descriptionRaw": "Deal 2 to all enemies and the enemy Nexus.",
    },
    "BLUE_CARD": {
        "name": "Blue Card", "cost": 0, "type": "Spell", "collectible": False,
        "descriptionRaw": "Refill 2 spell mana. Draw 2.",
    },
}


def test_la_destiny_card_se_choisit_sur_le_plateau():
    """
    RÈGLE DE JEU D'EWAN, 15/11/2026 — et la fin d'un tirage à pile ou face.

    Wild Card (98BW003, « Play a Destiny Card. ») ouvre une fenêtre de
    trois cartes, et le bot a pris **Blue Card 10 fois sur 10** : leurs
    clés `card_pick_rank` sont STRICTEMENT ÉGALES — (1, 0, 0, 0), trois
    sorts jouables, non-unités, de valeur 0, à coût 0 — donc `max` rendait
    la première de l'ordre de lecture. Troisième occurrence du même
    défaut après Yuumi (11/11) et Volibear (14/11).

    Ewan : « en fonction de si plusieurs unités ont 2 hp, si on a peu de
    carte en main ou besoin de piocher, et si on doit stun un ennemi
    fort ». Trois signaux, qui se lisent tous sur l'instantané.

    ON NE RECONNAÎT PAS CES TROIS CARTES. `spells.lire_effet_immediat`
    compte des marqueurs du texte anglais — « to all enemies », « the
    strongest enemy », « stun », « draw N », « and the enemy Nexus » —
    exactement comme le reste du module. Les Destiny Cards en sont
    l'occasion, pas le sujet.
    """
    print("\nDestiny Card : le choix se lit sur le plateau")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS, **DESTINY_CARDS})

    def fenetre_et_plateau(ennemis, en_main):
        """La fenêtre des trois cartes, plus un plateau adverse donné."""
        specs = [(code, 70 + i, FENETRE_DE_CHOIX, 670 + 290 * i, True,
                  HAUTEUR_FENETRE)
                 for i, code in enumerate(("GOLD_CARD", "RED_CARD", "BLUE_CARD"))]
        specs += [(code, 200 + i, 0.800, 500 + 150 * i, False)
                  for i, code in enumerate(ennemis)]
        specs += [("UNIT_A", 300 + i, EN_MAIN, 400 + 120 * i, True)
                  for i in range(en_main)]
        snap = scene(specs, orb_active=True)
        offertes = [c for c in snap.cards() if c.code in DESTINY_CARDS]
        assert len(offertes) == 3, [c.code for c in offertes]
        return snap, offertes

    # (0) LE POINT DE DÉPART : sans instantané, les trois sont à égalité
    # parfaite, et c'est tout le défaut.
    _, offertes = fenetre_et_plateau([], 5)
    cles = {actions.card_pick_rank(c) for c in offertes}
    check("sans instantané, les trois clés sont ÉGALES", len(cles) == 1, cles)
    check("   donc max() rend la première de l'ordre de lecture",
          actions.choose_offered_card(offertes).code == offertes[0].code,
          offertes[0].code)

    # (a) « PLUSIEURS UNITÉS ONT 2 HP » -> la zone nettoie le plateau.
    snap, offertes = fenetre_et_plateau(["SMALL"] * 3, 5)
    pris = actions.choose_offered_card(offertes, snap)
    check("trois ennemis à 2 PV : on prend RED (la zone)",
          pris.code == "RED_CARD", pris.code)

    # (b) « ON DOIT STUN UN ENNEMI FORT » -> le mono-cible.
    # Un seul gros ennemi : la zone à 2 ne le tue pas, les 7 dégâts si.
    snap, offertes = fenetre_et_plateau(["BRUTE"], 5)
    pris = actions.choose_offered_card(offertes, snap)
    check("un gros ennemi : on prend GOLD (7 dégâts + stun)",
          pris.code == "GOLD_CARD", pris.code)

    # (c) « PEU DE CARTE EN MAIN » -> la pioche.
    snap, offertes = fenetre_et_plateau([], 2)
    pris = actions.choose_offered_card(offertes, snap)
    check("plateau vide et main courte : on prend BLUE (pioche)",
          pris.code == "BLUE_CARD", pris.code)

    # (d) ET LA ZONE L'EMPORTE SUR LA PIOCHE QUAND ELLE PAIE VRAIMENT :
    # main courte ET trois ennemis à portée, c'est le plateau qui gagne.
    snap, offertes = fenetre_et_plateau(["SMALL"] * 3, 2)
    pris = actions.choose_offered_card(offertes, snap)
    check("main courte MAIS trois cibles : la zone passe devant",
          pris.code == "RED_CARD", pris.code)

    # (e) NON-RÉGRESSION, ET C'EST LE GARDE-FOU : le nouveau critère
    # n'arrive qu'en DERNIER. Une fenêtre ordinaire (Manifest) garde
    # exactement le choix d'avant — l'unité connue, pas le sort.
    avant = hand_at([("STONEWEAVING", 21)])
    manifest = scene([
        ("OFFER_REFUSED", 61, FENETRE_DE_CHOIX, 700),
        ("OFFER_UNIT", 62, FENETRE_DE_CHOIX, 959),
        ("OFFER_CHEAP", 63, FENETRE_DE_CHOIX, 1247),
    ])
    proposees = [c for c in manifest.cards()
                 if c.code in ("OFFER_REFUSED", "OFFER_UNIT", "OFFER_CHEAP")]
    sans = actions.choose_offered_card(proposees)
    avec = actions.choose_offered_card(proposees, manifest)
    check("fenêtre ordinaire : le choix ne change pas",
          sans.code == avec.code, (sans.code, avec.code))
    # ET LA RAISON SE MESURE, elle ne se suppose pas : aucune de ces
    # cartes ne promet d'effet immédiat, donc le critère vaut 0.0 pour
    # toutes les trois et ne peut RIEN renverser.
    valeurs = {c.code: actions.valeur_immediate(c, manifest) for c in proposees}
    check("   parce que le nouveau critère y vaut 0.0 partout",
          set(valeurs.values()) == {0.0}, valeurs)
    del avant

def test_une_fenetre_prise_fait_avancer_la_resolution():
    """
    PRENDRE UNE CARTE DANS UNE FENÊTRE N'EST PAS ANNULER — ET LE SORT ABOUTIT.

    Fait de jeu d'Ewan, 15/11/2026 : « le bot ne sait pas jouer la carte
    Joker ». Joker, c'est Wild Card (98BW003, « Play a Destiny Card. »),
    du deck Twisted Fate. Et le diagnostic est à l'envers du symptôme :
    LE BOT SAIT LA JOUER, IL CROIT AVOIR ÉCHOUÉ. La trace du 15/11
    (`logs/challenges_20261115_181438.log`) le dit en six lignes :

        18:29:23  Lancement de Wild Card (AUTRE sur aucune).
        18:29:26  Wild Card est sur la pile : validation.
        18:29:31  Fenêtre de choix ouverte (3 cartes) : on prend Blue Card
        18:29:31  Wild Card toujours sur la pile après validation.   <- ÉCHEC
        18:29:31    stack  Blue Card | Wild Card | Gold Card | Red Card
        18:29:32  Sort sur la pile (nous : Blue Card)                <- ÇA A MARCHÉ

    Une seconde plus tard, Blue Card est sur la pile : le choix a abouti.
    Mais la carte a été BANNIE pour le round et rejouée au suivant —
    10 fois dans la session, 7 fois le 14/11 au soir sur la même carte.

    LA CAUSE EST UN COMMENTAIRE JUSTE, APPLIQUÉ AU MAUVAIS GESTE.
    `geste_pour_une_cible_reclamee` en fait DEUX, aux conséquences
    OPPOSÉES : l'annulation REND la carte (il ne faut donc pas relire,
    sinon `play_spell` conclurait « résolu » pour un sort rendu), la
    prise de carte FAIT AVANCER la résolution (il faut relire, sinon on
    conclut à l'échec d'un sort qui a abouti). `let_stack_resolve`
    sortait dans les deux cas, sur le raisonnement de l'annulation seule.

    C'est aussi pourquoi `geste_pour_une_cible_reclamee` doit DIRE lequel
    des deux elle a fait : le déduire chez l'appelant serait une seconde
    implémentation du même test, et le projet sait où ça mène.
    """
    print("\nPile : une fenêtre PRISE fait avancer la résolution")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})

    # (a) LE GESTE SE NOMME. Sans ça l'appelant ne peut pas distinguer.
    fenetre = _pile_avec_notre_sort("cible", fenetre=True)
    sans_fenetre = _pile_avec_notre_sort("cible", orb_active=True)
    pris = actions.geste_pour_une_cible_reclamee(fenetre, dry_run=True)
    annule = actions.geste_pour_une_cible_reclamee(sans_fenetre, dry_run=True)
    check("une prise de carte se déclare comme telle",
          pris is not None and pris.fenetre_prise, pris)
    check("   une annulation NON",
          annule is not None and not annule.fenetre_prise, annule)
    check("   et les deux portent toujours leur phrase",
          "fenêtre" in str(pris.phrase).lower()
          and "annule" in str(annule.phrase).lower(),
          (pris, annule))

    # (b) APRÈS LA PRISE, ON RELIT — et le sort a quitté la pile.
    # L'état d'après est celui de la trace : notre carte est partie, la
    # Destiny Card choisie a pris sa place.
    carte = next(c for c in fenetre.stack if c.local)
    apres = replace(
        scene([("DESTINY_CHOISIE", 99, 0.48, 700, True),
               ("UNIT_B", 40, 0.800, 400, False)], orb_active=True),
        phase=Phase.SPELL_STACK, button_label="fin_du_tour",
    )
    # Une seule entrée : la relecture d apres le clic doit rendre l etat d apres.
    reader = FakeReader([apres])
    (recorder, cancels, clics), restore = _record_gestures()
    attentes = []
    saved_wait = actions.wait_for_change
    actions.wait_for_change = lambda *a, **k: (attentes.append(a), apres)[1]
    try:
        latest = actions.let_stack_resolve(reader, fenetre, carte)
    finally:
        actions.wait_for_change = saved_wait
        restore()

    check("un clic dans la fenêtre", len(clics) == 1, clics)
    check("   aucune annulation", cancels == [], cancels)
    check("   NOTRE SORT A QUITTÉ LA PILE DANS L'ÉTAT RENDU",
          not any(c.code == "SPELL_A" and c.local for c in latest.stack),
          [c.code for c in latest.stack])
    check("   on n'a pas attendu l'adversaire", attentes == [], attentes)

    # (c) NON-RÉGRESSION, ET C'EST LA MOITIÉ QUI COMPTE : une ANNULATION
    # ne relit toujours pas. Relire là rendrait un état sans la carte sur
    # la pile — elle est revenue en main — et `play_spell` conclurait
    # « résolu » pour un sort que l'annulation vient de rendre.
    bloque = _pile_avec_notre_sort("cible", orb_active=True)
    carte = next(c for c in bloque.stack if c.local)
    rendu = replace(
        scene([("UNIT_B", 40, 0.800, 400, False)], orb_active=True),
        phase=Phase.SPELL_STACK, button_label="fin_du_tour",
    )
    reader = FakeReader([bloque, rendu])
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        latest = actions.let_stack_resolve(reader, bloque, carte)
    finally:
        restore()
    check("annulation : une seule, et aucun clic",
          len(cancels) == 1 and clics == [], (cancels, clics))
    check("   l'état rendu dit ENCORE « sur la pile » : mise de côté",
          any(c.code == "SPELL_A" and c.local for c in latest.stack),
          [c.code for c in latest.stack])
    check("   l'état n'a pas été relu", reader.calls == 0, reader.calls)


def test_une_jumelle_en_main_ne_fait_pas_echouer_une_defausse():
    """
    « CETTE CARTE-LÀ EST-ELLE PARTIE ? » SE LIT PAR CardID, PAS PAR CODE.

    Mesuré le 15/11/2026, deck Twisted Fate (deux Wild Card, trois Pick a
    Card, trois Make it Rain en main). `Get Excited!` défausse, le clic
    PART, et le bot déclare « le clic n'a pas pris » — 12 fois dans la
    session. Le log montre les deux états à la suite :

        avant : Wild Card#1204492146[hand] ... Wild Card#1625478173[hand]
        après : Wild Card#1625478173[hand]

    La carte visée EST partie. `wait_until_card_left` passe par
    `find_our_card`, qui retombe sur une recherche PAR CODE quand le
    CardID ne correspond plus : le repli trouve la jumelle et conclut
    « toujours à l'écran ».

    Ce repli est LÉGITIME LÀ OÙ IL EST NÉ — `wait_for_designation_target`
    cherche une carte à CLIQUER, et attraper une jumelle identique n'a
    aucune conséquence. Il ne l'est pas pour constater un DÉPART, et le
    projet l'avait déjà écrit pour les zones : « un comptage par code ne
    distingue pas deux exemplaires d'une même carte » (`_left_zone`, deux
    Thrall Bulwark sur le banc). La même règle manquait ici.
    """
    print("\nDéfausse : une jumelle en main n'est pas la carte visée")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})

    # Deux exemplaires du même code, CardID distincts — la main du 15/11.
    avant = scene([("SPELL_A", 1204492146, EN_MAIN, 700),
                   ("SPELL_A", 1625478173, EN_MAIN, 900),
                   ("UNIT_B", 40, 0.800, 400)])
    visee = next(c for c in avant.cards() if c.card_id == 1204492146)
    jumelle = next(c for c in avant.cards() if c.card_id == 1625478173)
    check("deux cartes, même code, CardID distincts",
          visee.code == jumelle.code and visee.card_id != jumelle.card_id,
          (visee, jumelle))

    # La visée est partie ; la jumelle est toujours là.
    apres = scene([("SPELL_A", 1625478173, EN_MAIN, 871),
                   ("UNIT_B", 40, 0.800, 400)])
    partie, _ = actions.wait_until_card_left(FakeReader([apres]), visee, apres)
    check("LA CARTE VISÉE EST RECONNUE PARTIE", partie is True, partie)

    # Et le contraire tient : tant qu'elle est là, elle n'est pas partie.
    encore, _ = actions.wait_until_card_left(
        FakeReader([avant]), visee, avant, timeout=0.01)
    check("   une carte encore présente n'est pas déclarée partie",
          encore is False, encore)

    # NON-RÉGRESSION : sans CardID (API muette), le comptage par code
    # reste la seule identité disponible — on ne retire pas le repli, on
    # cesse de s'en servir quand l'API nous donne mieux.
    sans_id = replace(visee, card_id=-1)
    reste, _ = actions.wait_until_card_left(
        FakeReader([apres]), sans_id, apres, timeout=0.01)
    check("sans CardID : le comptage par code reste le repli",
          reste is False, reste)


def test_une_pile_qui_ne_se_vide_pas_laisse_une_image():
    """
    « TOUJOURS SUR LA PILE APRÈS VALIDATION » DOIT LAISSER UNE CAPTURE.

    C'est une image qui a permis de comprendre Yoink! le 05/11 ; les
    sept blocages du 09/11 n'ont laissé qu'une phrase dans le log, et on
    ne sait toujours pas POURQUOI le clic de ciblage de Flash Freeze n'a
    pas été pris. `play_spell` demande donc `journaliser_pile_bloquee`,
    qui écrit `screenshots/pile_bloquee_<carte>_<date>.png` et journalise
    l'état lu, le libellé du bouton et l'orbe.

    LE GUET EST BOUCHONNÉ EN TÊTE DE SUITE (cf. `PILES_BLOQUEES`) : un
    guet qui photographie l'écran n'a rien à faire dans une suite hors
    ligne, cinq fuites l'ont déjà prouvé. On garde les appels, et c'est
    ce test qui les relit.
    """
    print("\nPile bloquée : on garde une image, pas seulement un mot")

    with_db(ALL_CARDS)
    reponse = variant_scene([("SPELL_A", 21, 0.48, 700),
                             ("UNIT_B", 40, 0.800, 400, False)], "nous")
    avant = variant_scene([("SPELL_A", 21, EN_MAIN, 500),
                           ("UNIT_B", 40, 0.800, 400, False)], "nous")
    # La lecture qui sert à VISER doit être fraîche, sinon `play_spell`
    # relit la main et sort par « n'est plus dans la main » — un échec
    # qui ressemble au nôtre et ne passe pas par le même chemin. Et
    # l'horloge virtuelle laisse passer le TEMPS RÉEL (`test_clock`),
    # donc fabriquer les scènes ci-dessus suffit à la périmer.
    avant = replace(avant, taken_at=time.time())
    carte = {c.code: c for c in avant.hand}["SPELL_A"]

    del PILES_BLOQUEES[:]
    saved = actions.let_stack_resolve
    # La pile ne se vide pas : c'est l'état que `play_spell` doit juger.
    actions.let_stack_resolve = lambda reader, latest, card: reponse
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        # `reponse` est répété à chaque lecture : le sort est parti de la
        # main, il est sur la pile, et il y reste.
        success, _ = actions.play_spell(FakeReader([reponse]), avant, carte)
    finally:
        restore()
        actions.let_stack_resolve = saved

    check("pile non vidée : échec propre", success is False)
    check("   une capture de diagnostic demandée", len(PILES_BLOQUEES) == 1, PILES_BLOQUEES)
    check("   pour la bonne carte",
          PILES_BLOQUEES and PILES_BLOQUEES[0][1].code == "SPELL_A",
          PILES_BLOQUEES)
    check("   et l'état gardé est celui du blocage",
          PILES_BLOQUEES and any(c.code == "SPELL_A" and c.local
                                 for c in PILES_BLOQUEES[0][0].stack),
          PILES_BLOQUEES)


# L'image fabriquée par le bouchon de capture : n'importe quel objet
# reconnaissable fait l'affaire, on vérifie qu'il arrive intact jusqu'au
# rapport.
ECRAN_BOUCHON = "ECRAN-AVANT-LE-GESTE"


def _chronologie_capture_et_gestes():
    """
    UN SEUL JOURNAL POUR LA CAPTURE ET LES GESTES — l'ordre se lit dessus.

    Deux listes séparées diraient « les deux ont eu lieu » sans jamais
    dire LEQUEL D'ABORD, et c'est précisément la question : le 11/11 la
    capture avait bien lieu, après le clic droit qui efface le blocage.
    """
    chrono = []
    saved = (
        getattr(actions, "capturer_pour_diagnostic", None),
        actions.cancel_pending_action,
        actions.click,
        actions.drag,
    )
    # `setattr` et non une affectation directe : tant que la couture
    # n'existe pas dans `actions`, le bouchon n'est jamais appelé et le
    # test ROUGIT sur l'ordre au lieu de planter à l'installation.
    setattr(actions, "capturer_pour_diagnostic",
            lambda: chrono.append("capture") or ECRAN_BOUCHON)
    actions.cancel_pending_action = lambda *a, **k: chrono.append("annulation")
    actions.click = lambda x, y: chrono.append("clic")
    actions.drag = DragRecorder()

    def restore():
        if saved[0] is None:
            if hasattr(actions, "capturer_pour_diagnostic"):
                delattr(actions, "capturer_pour_diagnostic")
        else:
            actions.capturer_pour_diagnostic = saved[0]
        actions.cancel_pending_action, actions.click, actions.drag = saved[1:]

    return chrono, restore


def test_la_capture_du_blocage_precede_le_geste():
    """
    ON PHOTOGRAPHIE L'ÉCRAN BLOQUÉ AVANT DE LE DÉBLOQUER.

    Fait mesuré le 11/11/2026, et c'était le PREMIER LIVRABLE ATTENDU de
    la session (« le prochain blocage laissera une capture : c'est elle
    qu'il faudra regarder d'abord »). Dix captures ont bien été écrites.
    **Les dix sont inutilisables** : elles montrent le plateau une fois
    débloqué. Vérifié à l'image sur
    `screenshots/pile_bloquee_Beast_s_Frenzy_20261111_131538.png` —
    l'orbe y affiche « FIN DU ROUND », la pile est vide, le tour a
    repris. Le log dit la même chose, dans cet ordre :

        13:14:16  Annulation d'une action en attente (clic droit)
        13:14:18  Le jeu attend une cible pour Beast's Frenzy : on annule
        13:14:18  Beast's Frenzy toujours sur la pile après validation
        13:14:18  Écran gardé pour diagnostic : pile_bloquee_...png

    `geste_pour_une_cible_reclamee` avait DÉJÀ annulé quand
    `journaliser_pile_bloquee` photographiait. Le TEXTE de l'instantané,
    lui, est juste — il vient du `latest` d'avant le geste — ce qui rend
    la contradiction invisible à la seule lecture du log, et c'est pour
    ça qu'elle a survécu.

    LA CAPTURE APPARTIENT AU GESTE, PAS AU COMPTE RENDU : c'est « un
    bouchon par COUTURE, pas un par appelant » (10/11) appliqué au
    diagnostic. Photographier dans chacun des DEUX appelants recréerait
    exactement le défaut que la source unique existe pour éviter, d'où
    une assertion pour `let_stack_resolve` ET une pour
    `respond_to_stack`.
    """
    print("\nPile bloquée : on photographie AVANT le geste, pas après")

    with_db({**ALL_CARDS, **CARD_WINDOW_CARDS})

    # (a) l'annulation, par les DEUX appelants — c'est le cas du 11/11.
    for nom, appelant in (
        ("let_stack_resolve", "pile"),
        ("respond_to_stack", "reponse"),
    ):
        bloque = _pile_avec_notre_sort("cible", orb_active=True)
        carte = next(c for c in bloque.stack if c.local)
        chrono, restore = _chronologie_capture_et_gestes()
        try:
            if appelant == "pile":
                actions.let_stack_resolve(FakeReader([bloque]), bloque, carte)
            else:
                actions.respond_to_stack(FakeReader([bloque]), bloque, allow_spells=True)
        finally:
            restore()
        check(f"{nom} : le geste a bien eu lieu", "annulation" in chrono, chrono)
        check("   l'écran a été photographié", "capture" in chrono, chrono)
        check("   ET LA CAPTURE PRÉCÈDE LE GESTE", chrono == ["capture", "annulation"], chrono)

    # (b) la fenêtre de choix : l'autre geste de la même fonction.
    bloque = _pile_avec_notre_sort("cible", fenetre=True)
    carte = next(c for c in bloque.stack if c.local)
    chrono, restore = _chronologie_capture_et_gestes()
    try:
        actions.let_stack_resolve(FakeReader([bloque]), bloque, carte)
    finally:
        restore()
    check("fenêtre de choix : la capture précède le clic",
          chrono == ["capture", "clic"], chrono)

    # (c) L'IMAGE ARRIVE INTACTE JUSQU'AU RAPPORT. Photographier avant ne
    # sert à rien si le rapport reprend une image fraîche : c'est la
    # garde d'AVANT le geste qu'il doit écrire.
    bloque = _pile_avec_notre_sort("cible", orb_active=True)
    carte = next(c for c in bloque.stack if c.local)
    chrono, restore = _chronologie_capture_et_gestes()
    try:
        actions.let_stack_resolve(FakeReader([bloque]), bloque, carte)
        reprise = getattr(actions, "_reprendre_ecran_avant_geste", lambda: None)()
    finally:
        restore()
    check("le rapport reprend l'image d'AVANT le geste",
          reprise == ECRAN_BOUCHON, reprise)
    check("   et elle n'est servie qu'une fois (consommée)",
          getattr(actions, "_reprendre_ecran_avant_geste", lambda: None)() is None)

    # (d) UNE IMAGE PÉRIMÉE N'EST PAS CELLE DU BLOCAGE COURANT.
    # `respond_to_stack` fait le geste sans que personne n'appelle le
    # rapport : la garde resterait sinon en mémoire et serait servie,
    # des minutes plus tard, pour un blocage sans rapport.
    actions._ECRAN_AVANT_GESTE = (
        time.time() - actions.FRAICHEUR_CAPTURE_DIAGNOSTIC - 1.0, "VIEUX")
    check("une garde périmée est jetée",
          actions._reprendre_ecran_avant_geste() is None)

    # (e) UNE SIMULATION NE PHOTOGRAPHIE RIEN, et un bouton qui ne
    # réclame rien non plus : sinon chaque `actions.py plan` et chaque
    # tour ordinaire paierait une capture pour rien.
    chrono, restore = _chronologie_capture_et_gestes()
    try:
        bloque = _pile_avec_notre_sort("cible", orb_active=True)
        actions.geste_pour_une_cible_reclamee(bloque, dry_run=True)
        check("dry_run : aucune capture, aucun geste", chrono == [], chrono)
        ordinaire = _pile_avec_notre_sort("fin_du_tour", orb_active=True)
        check("   le bouton ne réclame rien : rien à lire",
              actions.geste_pour_une_cible_reclamee(ordinaire) is None)
        check("   et toujours aucune capture", chrono == [], chrono)
    finally:
        restore()


def test_the_hand_is_reread_before_grabbing_when_the_reading_is_old():
    """
    LA MAIN SE RECENTRE À CHAQUE PIOCHE ; UNE LECTURE VIEILLE NE SERT PLUS À VISER.

    Ewan, 05/09/2026 : « le bot tentait de jouer quelque chose alors que
    le jeu a pioché plusieurs fois ». Décision sur une lecture, OCR des
    coûts pendant une à deux secondes, glissé sur les coordonnées de la
    lecture : la voisine est attrapée. Désormais `play_card` et
    `play_spell` relisent la main si l'instantané a plus de AIM_MAX_AGE s,
    attendent qu'elle soit immobile (HAND_QUIET_CONFIRMATIONS relectures)
    et retrouvent la carte par son CardID.
    """
    print("\nLa main est relue avant la saisie quand la lecture a vieilli")

    with_db(ALL_CARDS)
    # Décision : UNIT_A (id 21) en x=500, UNIT_B (id 22) en x=640.
    avant = hand_at([("UNIT_A", 21), ("UNIT_B", 22)])
    carte = {c.code: c for c in avant.hand}["UNIT_A"]
    # Pendant l'OCR, le jeu a pioché : trois cartes, UNIT_A a glissé en x=360.
    en_vol = hand_at([("UNIT_A", 21), ("UNIT_B", 22), ("SPELL_A", 23)], x0=420)
    apres = hand_at([("UNIT_A", 21), ("UNIT_B", 22), ("SPELL_A", 23)], x0=360)
    # Après la pose : UNIT_A sur le banc, les deux autres en main.
    posee = scene([("UNIT_B", 22, EN_MAIN, 360), ("SPELL_A", 23, EN_MAIN, 500),
                   ("UNIT_A", 21, 0.150, 500)])

    (recorder, cancels, clics), restore = _record_gestures()
    saved_sleep = actions.time.sleep
    actions.time.sleep = lambda s: None
    try:
        # a) lecture FRAÎCHE : aucune relecture, on vise la position de la décision.
        #    Fraîche POUR DE BON : trois scènes ont été fabriquées depuis,
        #    et l'horloge virtuelle laisse passer le temps réel — sans ce
        #    rappel, le cas (a) devient le cas (b) sur une machine lente.
        avant.taken_at = time.time()
        reader = FakeReader([posee])
        success, _ = play_card(reader, avant, carte, attempts=1)
        check("lecture fraîche : saisie sur la position de la décision",
              success and recorder.drags and recorder.drags[0][0][0] == carte.grab_point[0],
              recorder.drags)

        # b) lecture VIEILLE : la main est relue jusqu'à être immobile
        #    (en_vol puis apres, apres), et on saisit UNIT_A là où elle est.
        recorder.drags.clear()
        avant.taken_at -= actions.AIM_MAX_AGE + 1
        reader = FakeReader([en_vol, apres, apres, apres, apres, posee])
        success, _ = play_card(reader, avant, carte, attempts=1)
        nouvelle = {c.code: c for c in apres.hand}["UNIT_A"].grab_point
        check("lecture vieille : saisie recalée sur la main relue",
              success and recorder.drags and recorder.drags[0][0][0] == nouvelle[0]
              and nouvelle[0] != carte.grab_point[0],
              (recorder.drags, nouvelle, carte.grab_point))

        # c) la carte n'est plus en main à la relecture : rien n'est glissé.
        recorder.drags.clear()
        reader = FakeReader([posee, posee, posee, posee])
        success, _ = play_card(reader, avant, carte, attempts=1)
        check("carte disparue à la relecture : pas de glissé, échec propre",
              success is False and recorder.drags == [], recorder.drags)
    finally:
        restore()
        actions.time.sleep = saved_sleep


def test_settling_waits_out_a_series_of_draws():
    """
    Une pioche en série : chaque carte arrive, la main se recentre, pause,
    la suivante arrive. Une seule relecture immobile tombe entre deux
    cartes ; `confirmations=3` attend que la série soit finie.
    """
    print("\nL'attente d'immobilité couvre une pioche en série")

    with_db(ALL_CARDS)
    m1 = hand_at([("UNIT_A", 21)])
    m2 = hand_at([("UNIT_A", 21), ("UNIT_B", 22)], x0=430)
    m3 = hand_at([("UNIT_A", 21), ("UNIT_B", 22), ("SPELL_A", 23)], x0=360)
    saved_sleep = actions.time.sleep
    actions.time.sleep = lambda s: None
    try:
        # m1 immobile UNE fois, puis la 2e carte arrive, immobile une fois, puis la 3e.
        reader = FakeReader([m1, m2, m2, m3, m3, m3, m3])
        final = actions.wait_until_settled(reader, m1, zones=("hand",), timeout=30, confirmations=3)
        check("avec 3 confirmations : on finit sur la main complète", len(final.hand) == 3, len(final.hand))
        reader = FakeReader([m1, m2, m2, m3, m3, m3, m3])
        final = actions.wait_until_settled(reader, m1, zones=("hand",), timeout=30, confirmations=1)
        check("avec 1 confirmation : on s'arrête entre deux pioches", len(final.hand) == 1, len(final.hand))
    finally:
        actions.time.sleep = saved_sleep


def test_play_hand_stops_when_a_spell_lands_on_the_stack():
    """On ne pose rien tant qu'un sort attend sur la pile."""
    print("\nPas de pose pendant que la pile est ouverte")

    with_db(ALL_CARDS)
    pile = variant_scene([
        ("UNIT_A", 21, EN_MAIN, 500), ("SPELL_A", 90, 0.48, 900, False),
    ], "nous")
    check("SPELL_STACK lu", pile.phase is Phase.SPELL_STACK, pile.phase)
    saved_mana = actions.read_mana_pool
    actions.read_mana_pool = lambda **_: ManaPool(mana=10, spell_mana=0)
    (recorder, cancels, clics), restore = _record_gestures()
    try:
        played, _, log = play_hand(FakeReader([pile]), pile)
    finally:
        restore()
        actions.read_mana_pool = saved_mana
    check("rien posé", played == [], played)
    check("aucun geste", recorder.drags == [] and clics == [], (recorder.drags, clics))
    check("raison journalisée", any("pile" in e for e in log.entries), log.entries)


def _bench_snapshot(units, attackers=()):
    """
    Banc et rangée d'attaque aux positions X demandées.
    `units` et `attackers` sont des couples (card_id, x).
    """
    with_db(ALL_CARDS)
    rects = list(nexus_rects())
    for card_id, x in units:
        rects.append(rect_at_ratio(0.150, code="BRUTE", card_id=card_id, x=x))
    for card_id, x in attackers:
        rects.append(rect_at_ratio(0.320, code="BRUTE", card_id=card_id, x=x))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


def _challenge_snapshot(ours=(), theirs=(), attackers=(), enemy_blockers=()):
    """
    Un plateau complet pour les tests de défi. Chaque entrée est un
    triplet (code, card_id, x) :

        ours            notre banc               (ratio 0.150)
        attackers       notre rangée d'attaque   (ratio 0.320)
        theirs          le banc adverse          (ratio 0.800)
        enemy_blockers  la rangée adverse        (ratio 0.650)
    """
    with_db({**ALL_CARDS, **TRAMPLE_CARD, **KEYWORD_CARDS})
    rects = list(nexus_rects())
    for code, card_id, x in ours:
        rects.append(rect_at_ratio(0.150, code=code, card_id=card_id, x=x))
    for code, card_id, x in attackers:
        rects.append(rect_at_ratio(0.320, code=code, card_id=card_id, x=x))
    for code, card_id, x in theirs:
        rects.append(rect_at_ratio(0.800, code=code, card_id=card_id, local=False, x=x))
    for code, card_id, x in enemy_blockers:
        rects.append(rect_at_ratio(0.650, code=code, card_id=card_id, local=False, x=x))
    install_fakes(rects, screen=make_screen(orb_active=True, token="nous"))
    return state_reader().snapshot()


class AnimatedReader:
    """
    Rejoue une suite d'états EN SIMULANT LE RECENTRAGE.

    Chaque étape est un couple (en_vol, stabilisé). La première lecture qui
    suit un geste renvoie les cartes en cours de glissement, les suivantes
    leur position finale. Ce n'est pas un raffinement gratuit : c'est
    exactement ce que fait le client. L'API annonce le nouveau CONTENU des
    zones dès le dépôt, mais continue de renvoyer des rectangles qui
    bougent pendant toute l'animation. Un lecteur qui livre tout de suite
    l'état final ne peut pas voir le bug qu'on corrige ici.
    """

    def __init__(self, steps, resolved=None):
        self.steps = list(steps)
        self.resolved = resolved
        self.calls = 0
        self.served = 0

    def advance(self):
        """Un geste vient d'être fait : l'étape suivante commence."""
        if len(self.steps) > 1:
            self.steps.pop(0)
        self.served = 0

    def stable_snapshot(self, **_):
        self.calls += 1
        self.served += 1
        in_flight, settled = self.steps[0]
        return in_flight if self.served == 1 else settled

    def snapshot(self):
        if self.resolved is not None:
            return self.resolved
        return self.stable_snapshot()


def _grab_x(snapshot, card_id):
    """Abscisse de saisie d'une carte du banc dans cet état."""
    return next(c.grab_point[0] for c in snapshot.board if c.card_id == card_id)


def test_attack_rereads_positions_between_drags():
    """
    LE PLATEAU EST CENTRÉ : ENGAGER UNE UNITÉ DÉPLACE LES AUTRES.

    Les points de saisie sont calculés au moment du plan. Dès que la
    première unité quitte le banc, les suivantes se réalignent et ces
    points désignent la voisine — ou le vide. Il faut relire la position
    entre chaque geste.

    ET IL FAUT LA RELIRE APRÈS L'ANIMATION, pas pendant. Relire trop tôt
    donnait des coordonnées en cours de vol : c'est le bug observé en
    partie dès trois unités sur le banc, où la souris partait entre deux
    cartes. Le lecteur ci-dessous sert donc une position intermédiaire
    avant la bonne, et le test échoue si le bot mord à l'hameçon.
    """
    print("\nLe banc se recentre entre deux engagements")

    # Trois unités espacées de 300 px pour 126 px de large : un décalage de
    # recentrage rate la carte franchement, sans ambiguïté de mesure.
    start = _bench_snapshot([(401, 400), (402, 700), (403, 1000)])

    # Après le 1er engagement : 402 et 403 glissent de 1000 vers 850.
    flight_1 = _bench_snapshot([(402, 640), (403, 940)], attackers=[(401, 400)])
    settled_1 = _bench_snapshot([(402, 550), (403, 850)], attackers=[(401, 400)])

    # Après le 2e : 403 glisse de 850 vers 700.
    flight_2 = _bench_snapshot([(403, 790)], attackers=[(401, 400), (402, 550)])
    settled_2 = _bench_snapshot([(403, 700)], attackers=[(401, 400), (402, 550)])

    # Après le 3e : le banc est vide.
    empty = _bench_snapshot([], attackers=[(401, 400), (402, 550), (403, 700)])

    check("phase ATTACK_TURN", start.phase is Phase.ATTACK_TURN, start.phase)

    # steps[0] est l'état COURANT : `advance()` (appelé par le faux geste)
    # fait passer à l'étape suivante, comme le client après un dépôt.
    reader = AnimatedReader(
        [(start, start), (flight_1, settled_1), (flight_2, settled_2), (empty, empty)],
        resolved=_bench_snapshot([]),
    )

    recorder = DragRecorder()

    def drag_then_animate(source, destination):
        recorder(source, destination)
        reader.advance()

    original_drag, original_click = actions.drag, actions.click
    actions.drag, actions.click = drag_then_animate, lambda *a, **k: None
    try:
        engaged, _, _ = actions.declare_attack(reader, start)
    finally:
        actions.drag, actions.click = original_drag, original_click

    check("trois gestes tentés", len(recorder.drags) == 3, len(recorder.drags))
    check("trois unités engagées", len(engaged) == 3, len(engaged))

    if len(recorder.drags) >= 3:
        # 2e geste : 402 doit être saisie là où elle s'est ARRÊTÉE, ni à son
        # point de départ, ni à sa position intermédiaire.
        second = recorder.drags[1][0][0]
        check("le 2e geste part de la position stabilisée",
              second == _grab_x(settled_1, 402), (second, _grab_x(settled_1, 402)))
        check("    et pas de l'ancienne",
              second != _grab_x(start, 402), second)
        check("    et pas d'une position en cours de vol",
              second != _grab_x(flight_1, 402), second)

        # 3e geste : même exigence pour 403, qui a bougé deux fois.
        third = recorder.drags[2][0][0]
        check("le 3e geste part de la position stabilisée",
              third == _grab_x(settled_2, 403), (third, _grab_x(settled_2, 403)))
        check("    et pas d'une position en cours de vol",
              third != _grab_x(flight_2, 403), third)


def test_engage_retries_a_missed_grab():
    """
    UNE SAISIE RATÉE NE DOIT PAS COÛTER L'ATTAQUANT.

    Si le glissé part à côté, le banc ne change pas. Plutôt que d'abandonner
    l'unité pour le tour, on relit sa position et on retente une fois.
    """
    print("\nSaisie ratée : une seconde tentative")

    # Une seule unité : le test porte sur la reprise après un geste raté,
    # pas sur l'enchaînement (couvert par le test précédent).
    bench = _bench_snapshot([(401, 400)])
    engaged_one = _bench_snapshot([], attackers=[(401, 400)])

    # 1re étape : rien ne bouge (saisie ratée). 2e : l'unité part.
    reader = AnimatedReader(
        [(bench, bench), (engaged_one, engaged_one)],
        resolved=_bench_snapshot([]),
    )
    recorder = DragRecorder()

    def drag_then_animate(source, destination):
        recorder(source, destination)
        # Le premier geste rate : l'état ne change pas, donc on n'avance pas.
        if len(recorder.drags) > 1:
            reader.advance()

    original_drag, original_click = actions.drag, actions.click
    actions.drag, actions.click = drag_then_animate, lambda *a, **k: None
    try:
        engaged, _, _ = actions.declare_attack(reader, bench)
    finally:
        actions.drag, actions.click = original_drag, original_click

    check("la 1re unité finit engagée malgré la saisie ratée",
          any(c.card_id == 401 for c in engaged), [c.card_id for c in engaged])
    check("deux gestes pour cette unité", len(recorder.drags) >= 2, len(recorder.drags))


def test_engage_does_not_retry_when_a_neighbour_left():
    """
    SI LA SAISIE A ATTRAPÉ LA VOISINE, ON N'INSISTE PAS.

    Le banc a perdu une unité, mais pas celle qu'on visait. Retenter
    viderait le banc carte par carte en croyant corriger l'erreur.
    """
    print("\nSaisie de la voisine : pas de deuxième tentative")

    bench = _bench_snapshot([(401, 400), (402, 700)])
    # 402 est partie alors qu'on visait 401.
    wrong = _bench_snapshot([(401, 550)], attackers=[(402, 700)])

    reader = AnimatedReader([(bench, bench), (wrong, wrong)],
                            resolved=_bench_snapshot([]))
    recorder = DragRecorder()

    def drag_then_animate(source, destination):
        recorder(source, destination)
        reader.advance()

    original_drag, original_click = actions.drag, actions.click
    actions.drag, actions.click = drag_then_animate, lambda *a, **k: None
    try:
        target = next(c for c in bench.board if c.card_id == 401)
        success, _ = actions.move_to_attack_row(reader, bench, target)
    finally:
        actions.drag, actions.click = original_drag, original_click

    check("échec signalé", success is False, success)
    check("un seul geste", len(recorder.drags) == 1, len(recorder.drags))


def test_block_rereads_positions_between_drags():
    """Même piège au blocage, sur les deux extrémités du glissé."""
    print("\nLe banc se recentre entre deux blocages")

    # Deux bloqueurs, deux attaquants sans mot-clé évasif : les deux
    # paires doivent être jouées, donc deux gestes.
    first = blocking_snapshot(["WALL", "BRUTE"], ["SMALL", "BRUTE"])

    # Après le premier blocage : un seul défenseur au banc, recentré
    # ailleurs, et la rangée adverse décalée elle aussi.
    with_db(ALL_CARDS)
    rects = list(nexus_rects())
    rects.append(rect_at_ratio(0.150, code="BRUTE", card_id=202, x=700))
    rects.append(rect_at_ratio(0.650, code="SMALL", card_id=203, local=False, x=560))
    rects.append(rect_at_ratio(0.650, code="BRUTE", card_id=204, local=False, x=860))
    install_fakes(rects, screen=make_screen(orb_active=True, token=None))
    second = state_reader().snapshot()

    old_x = {c.grab_point[0] for c in first.board}
    new_x = {c.grab_point[0] for c in second.board}
    check("les positions du banc ont changé", not (new_x & old_x), (old_x, new_x))

    resolved = blocking_snapshot(["BRUTE"], [])
    recorder = DragRecorder()
    original_drag, original_click = actions.drag, actions.click
    original_health = actions.read_nexus_health
    actions.drag, actions.click = recorder, lambda *a, **k: None
    actions.read_nexus_health = lambda *a, **k: 20
    try:
        actions.execute_blocks(
            FakeReader([second] * 4, resolved=resolved), first, allow_chump=True
        )
    finally:
        actions.drag, actions.click = original_drag, original_click
        actions.read_nexus_health = original_health

    sources = [d[0][0] for d in recorder.drags]
    check("deux gestes de blocage", len(sources) >= 2, sources)
    if len(sources) >= 2:
        check("le 1er part de l'état initial", sources[0] in old_x, (sources[0], old_x))
        check("le 2e part de la position À JOUR", sources[1] in new_x, (sources[1], new_x))
        check("et surtout pas de l'ancienne", sources[1] not in old_x, (sources[1], old_x))


def test_turn_does_not_pass_on_a_declared_attack():
    """
    LE BUG QUI FAISAIT ENCAISSER LES ATTAQUES.

    Poser une carte rend la priorité à l'adversaire : il peut déclarer
    son attaque entre deux de nos poses. `play_turn` reprenait ensuite
    sans relire ce qui venait de se passer, écrivait « Phase BLOCKING :
    pas d'attaque ce tour » — l'exact contraire de ce que la ligne
    affichait — puis cliquait l'orbe, ce qui PASSAIT le blocage. Toute
    l'attaque arrivait au nexus sans un seul bloqueur.
    """
    print("\nAttaque déclarée pendant la pose")

    attacked = blocking_snapshot(["SMALL", "WALL"], ["BRUTE", "ELUSIVE"])
    check("l'état de départ est bien un blocage", attacked.phase is Phase.BLOCKING, attacked.phase)

    clicks = []
    original_play_hand, original_click = actions.play_hand, actions.click
    actions.play_hand = lambda *a, **k: ([], attacked, actions.ActionLog())
    actions.click = lambda *a, **k: clicks.append(a)
    try:
        log = actions.play_turn(FakeReader([attacked]), attacked, finish_turn=True)
        check("aucun clic : le blocage n'est pas passé", clicks == [], clicks)
        check("la main est rendue à la boucle",
              any("rend la main" in e for e in log.entries), log.entries)
        check("plus de « pas d'attaque ce tour »",
              not any("pas d'attaque ce tour" in e for e in log.entries), log.entries)
    finally:
        actions.play_hand, actions.click = original_play_hand, original_click


def test_turn_still_ends_when_it_is_ours():
    """Le garde-fou ne doit pas empêcher un tour ordinaire de se terminer."""
    print("\nTour ordinaire terminé normalement")

    with_db(FULL_DB)
    quiet = blocking_snapshot(["SMALL"], [])
    check("phase à nous", quiet.phase.is_our_move is True, quiet.phase)

    clicks = []
    original_play_hand, original_click = actions.play_hand, actions.click
    actions.play_hand = lambda *a, **k: ([], quiet, actions.ActionLog())
    actions.click = lambda *a, **k: clicks.append(a)
    try:
        log = actions.play_turn(FakeReader([quiet]), quiet, finish_turn=True)
        check("un clic de fin de tour", len(clicks) == 1, clicks)
        check("fin de tour journalisée",
              any("Fin de tour" in e for e in log.entries), log.entries)
    finally:
        actions.play_hand, actions.click = original_play_hand, original_click


JINX_CARDS = {
    "GET_EXCITED": {
        "name": "Jinx's Get Excited!", "cost": 3, "attack": 0, "health": 0,
        "type": "Spell", "collectible": False,
        "keywords": ["Fast"], "keywordRefs": ["Fast"],
        "descriptionRaw": "To play, discard 1. Deal 3 to anything.\r\n",
    },
}


def test_une_defausse_est_suivie_du_clic_sur_la_cible():
    """
    LE COÛT EN MAIN, PUIS LA CIBLE (14/11/2026, fait de jeu d'Ewan).

    « Le bot n'arrive pas à utiliser Enthousiasme de Jinx ! — il arrive
    bien à défausser une carte de ma main mais n'a pas su viser le nexus
    ennemi quand il n'y avait pas d'ennemi sur le banc adverse. »

    Jinx's Get Excited! (01PZ040T3) dit « To play, discard 1. Deal 3 to
    anything. » Le plan sortait en `Targeting.HAND` et ses cibles étaient
    JETÉES : le bot payait le coût, le sort partait sur la pile, et le
    jeu attendait un clic que personne ne faisait — jusqu'au garde
    d'immobilité, ~50 s plus tard.

    L'ORDRE N'EST PAS LIBRE, et c'est l'observation d'Ewan qui le fixe :
    la défausse D'ABORD (« To play » est un coût), la cible ENSUITE. Un
    seul journal pour les deux gestes, parce que deux listes diraient
    « les deux ont eu lieu » sans dire lequel en premier — la leçon de
    `test_la_capture_du_blocage_precede_le_geste`.

    ET LE NEXUS COMPTE COMME CIBLE : c'est tout le cas d'Ewan. « to
    anything » rend `Targeting.ANYTHING`, que `choose_target` sait faire
    retomber sur le nexus adverse quand le plateau d'en face est vide.
    """
    print()
    print("Une défausse, puis le clic sur la cible")

    saved = actions.CARD_RESTRICTIONS
    actions.CARD_RESTRICTIONS = False
    try:
        with_db({**ALL_CARDS, **JINX_CARDS})

        # (a) LE PLAN, puis la CIBLE calculée malgré le coût en main.
        avant = scene([
            ("GET_EXCITED", 21, EN_MAIN, 500),
            ("UNIT_A", 22, EN_MAIN, 640),          # de quoi défausser
            ("UNIT_B", 40, 0.800, 400, False),     # un ennemi à frapper
        ])
        carte = {c.code: c for c in avant.hand}["GET_EXCITED"]
        plan = spells.classify_card(carte, restricted=False)
        check("le plan enchaîne la main puis le plateau",
              plan.needs_board_click_after_hand, str(plan))

        castable, _, cibles, _ = actions.spell_is_castable(carte, avant)
        check("le sort est lançable", castable is True)
        check("   et une cible de plateau est prévue",
              len(cibles) == 1, cibles)
        check("   sur l'ennemi en jeu",
              cibles and cibles[0] == avant.enemy_board[0].center,
              (cibles, avant.enemy_board[0].center))

        # (b) LE CAS D'EWAN : plus personne en face, le nexus reste une cible.
        sans_ennemi = scene([
            ("GET_EXCITED", 21, EN_MAIN, 500),
            ("UNIT_A", 22, EN_MAIN, 640),
        ])
        c2 = {c.code: c for c in sans_ennemi.hand}["GET_EXCITED"]
        castable2, _, cibles2, pourquoi2 = actions.spell_is_castable(c2, sans_ennemi)
        check("banc adverse vide : le sort reste lançable", castable2 is True, pourquoi2)
        check("   et la cible est le NEXUS adverse",
              cibles2 and cibles2[0] == sans_ennemi.enemy_nexus,
              (cibles2, sans_ennemi.enemy_nexus))

        # (c) LES DEUX GESTES, DANS L'ORDRE.
        apres = scene([
            ("UNIT_B", 40, 0.800, 400, False),
            ("GET_EXCITED", 21, 0.480, 500),       # le sort part sur la pile
        ])
        journal = []
        sauves = (actions.drag, actions.click, actions.cancel_pending_action)
        actions.drag = lambda *a, **k: journal.append(("drag", a[:2]))
        actions.click = lambda x, y: journal.append(("click", (x, y)))
        actions.cancel_pending_action = lambda *a, **k: journal.append(("annule", a))
        try:
            actions.play_spell(FakeReader([apres, apres, apres]), avant, carte)
        finally:
            actions.drag, actions.click, actions.cancel_pending_action = sauves

        gestes = [g for g, _ in journal]
        check("la carte est bien déposée", "drag" in gestes, journal)
        clics = [p for g, p in journal if g == "click"]
        ennemi = avant.enemy_board[0].center
        check("l'ennemi est cliqué quelque part", ennemi in clics, (clics, ennemi))

        # L'ORDRE, dans UN SEUL journal : deux listes diraient « les deux
        # ont eu lieu » sans dire laquelle d'abord. Le dépôt ouvre le
        # lancement, la cible le referme — et tout ce qui se joue entre
        # les deux (la désignation en main) est par construction au
        # milieu, puisque le clic de cible est émis APRÈS elle.
        check("le dépôt précède le clic de cible",
              gestes.index("drag") < gestes.index("click"), journal)
        check("   et la cible est le DERNIER clic du lancement",
              clics[-1] == ennemi, clics)
    finally:
        actions.CARD_RESTRICTIONS = saved


def test_un_bloqueur_qui_refuse_son_poste_est_remplace():
    """
    UN BLOQUEUR QUI NE PREND PAS SON POSTE LAISSAIT L'ATTAQUANT PASSER
    (14/11/2026, fait de jeu d'Ewan : « il a tenté de bloquer une unité
    attaquante de l'ennemi alors que le défenseur était stun »).

    Trace du soir même, 22:15 :

        Plan de blocage : tout est bloqué.
            Twisted Fate (2/8) bloque Ashe (5/3)
            Pool Shark (12/2) bloque Rimetusk Shaman (3/4)
        Twisted Fate n'a pas pris son poste, on passe au suivant.

    Le plan annonçait « tout est bloqué », le glissé a été REFUSÉ par le
    jeu, et Ashe 5/3 est passée au nexus. En face : un Rimetusk Shaman,
    qui applique justement du Frostbite.

    **L'ÉTAT N'EST PAS LISIBLE, LE REFUS L'EST.** L'API ne rend que sept
    champs — CardCode, CardID, LocalPlayer et la géométrie : ni état, ni
    statistique. `can_block` ne connaît donc que deux mots-clés IMPRIMÉS
    (`CantBlock`, `Immobile`), et un Stun n'y apparaît jamais — « Stun »
    n'existe même pas comme mot-clé de carte dans la base. Mais le bot
    VOIT que le bloqueur n'a pas bougé (`_left_zone`) : il le journalise
    depuis toujours, **41 fois dans `logs/`**, dont 11 le 14/11 et 15 le
    06/11. Il se contentait de passer au suivant.

    ON RÉAGIT DONC À UN FAIT OBSERVÉ, PAS À UN ÉTAT DEVINÉ : un autre
    bloqueur légal est envoyé sur le MÊME attaquant, et l'unité qui a
    refusé n'est plus proposée de ce round. Cela traite le Stun sans le
    lire, et avec lui toutes les causes qu'on ne connaît pas encore.

    UN SEUL REMPLAÇANT PAR ATTAQUANT : si le second refuse aussi, on
    passe. Réessayer en boucle devant un jeu qui dit non, c'est la perte
    de temps que ce projet paie à chaque fois.
    """
    print()
    print("Un bloqueur qui refuse son poste est remplacé")

    # WALL et BRUTE au banc, un seul attaquant : le plan n'en engage
    # qu'un, l'autre reste disponible comme remplaçant.
    snap = blocking_snapshot(["WALL", "BRUTE"], ["UNIT_A"])
    check("phase BLOCKING", snap.phase is Phase.BLOCKING, snap.phase)
    pairs, _, _ = actions.plan_blocks(snap, nexus_health=20)
    check("un blocage prévu", len(pairs) == 1, pairs)

    prevu = pairs[0][0].code
    autres = [c.code for c in snap.board if c.is_unit and c.code != prevu]
    check("   et un autre bloqueur est disponible", bool(autres), autres)

    # Le premier glissé ne change RIEN (le jeu refuse : l'unité est
    # étourdie) ; le second aboutit. `wait_for_change` rend donc deux
    # fois le même état, puis un état où le banc s'est vidé.
    apres = blocking_snapshot([], ["UNIT_A"])
    appels = {"n": 0}

    def change(reader, before, **kwargs):
        appels["n"] += 1
        return snap if appels["n"] == 1 else apres

    sauves = (actions.read_nexus_health, actions.wait_for_change,
              actions.wait_for_combat_resolution)
    actions.read_nexus_health = lambda *a, **k: 20
    actions.wait_for_change = change
    actions.wait_for_combat_resolution = lambda reader, **k: apres
    (recorder, _, _), restore = _record_gestures()
    try:
        done, _, log = actions.execute_blocks(FakeReader([snap, snap, apres]), snap)
    finally:
        actions.read_nexus_health, actions.wait_for_change, \
            actions.wait_for_combat_resolution = sauves
        restore()

    texte = " / ".join(log.entries) if hasattr(log, "entries") else str(log)
    check("le refus est toujours journalisé",
          "pris son poste" in texte, texte)
    check("DEUX glissés : le refusé, puis son remplaçant",
          len(recorder.drags) == 2, recorder.drags)
    check("   et le blocage est finalement réalisé", len(done) == 1, done)
    check("   le remplaçant n'est pas celui qui a refusé",
          done and done[0][0].code != prevu, (done, prevu))
    # Le journal doit NOMMER le remplaçant : c'est lui qu'on cherchera
    # dans le log le jour où un blocage surprendra.
    check("   le journal nomme le remplaçant",
          done and done[0][0].name in texte, texte)
    check("   ... et dit que c'est un remplacement",
          "à sa place" in texte, texte)


def test_un_remplacant_nest_cherche_quune_fois():
    """
    DEUX REFUS D'AFFILÉE NE DÉCLENCHENT PAS UNE TROISIÈME TENTATIVE.

    Le garde-fou du correctif ci-dessus : devant un jeu qui refuse, on
    ne s'entête pas. Même esprit que `locate_node`, qui ÉCARTE un nœud
    cliqué sans « Voyage » au lieu de le recliquer.
    """
    print()
    print("Un remplaçant, et un seul")

    snap = blocking_snapshot(["WALL", "BRUTE", "SMALL"], ["UNIT_A"])
    sauves = (actions.read_nexus_health, actions.wait_for_change,
              actions.wait_for_combat_resolution)
    actions.read_nexus_health = lambda *a, **k: 20
    # RIEN ne bouge jamais : tous les glissés sont refusés.
    actions.wait_for_change = lambda reader, before, **k: snap
    actions.wait_for_combat_resolution = lambda reader, **k: snap
    (recorder, _, _), restore = _record_gestures()
    try:
        done, _, log = actions.execute_blocks(FakeReader([snap, snap, snap]), snap)
    finally:
        actions.read_nexus_health, actions.wait_for_change, \
            actions.wait_for_combat_resolution = sauves
        restore()

    check("deux glissés au plus, jamais trois",
          len(recorder.drags) <= 2, recorder.drags)
    check("   aucun blocage réalisé", done == [], done)
    texte = " / ".join(log.entries) if hasattr(log, "entries") else str(log)
    check("   et la confirmation a quand même lieu",
          "Confirmation" in texte, texte)


def main():
    for test in (
        test_un_bloqueur_qui_refuse_son_poste_est_remplace,
        test_un_remplacant_nest_cherche_quune_fois,
        test_une_defausse_est_suivie_du_clic_sur_la_cible,
        test_mana_rule,
        test_choice_order_and_filters,
        test_unknown_card_is_not_played,
        test_unit_with_a_hand_power_is_played_and_designates,
        test_hand_power_needs_enough_cards,
        test_hand_sacrifice_order,
        test_hand_boost_picks_the_opposite_card,
        test_designation_rereads_between_clicks,
        test_copy_designation_leaves_the_card_in_hand,
        test_designation_survives_the_hand_being_lifted,
        test_elora_end_to_end,
        test_elora_needs_a_spell_in_hand,
        test_designation_detects_a_click_that_did_not_take,
        test_wings_and_the_wave_decision,
        test_wings_and_the_wave_end_to_end,
        test_momentous_choice_picks_a_variant_before_the_target,
        test_iula_chooses_the_keyword_it_understands,
        test_an_or_that_opens_nothing_costs_only_a_glance,
        test_a_variant_that_would_not_accept_the_click_is_avoided,
        test_choice_window_not_reported,
        test_manifest_picks_the_best_new_card,
        test_unit_manifest_after_the_drop,
        test_unknown_card_with_a_surprise_choice_window,
        test_yoink_prend_une_carte_dans_la_main_adverse,
        test_une_fenetre_de_choix_ne_se_laisse_pas_annuler,
        test_la_vraie_trame_du_blocage_de_yoink,
        test_ce_qui_nest_pas_une_fenetre_de_choix,
        test_card_window_not_reported,
        test_harsh_winds_on_a_single_enemy,
        test_discard_then_window_ignores_the_lingering_card,
        test_slow_spell_window_opens_after_validation,
        test_chained_windows,
        test_real_spells_seen_in_game,
        test_trade_spells_pay_the_cheapest_and_hit_the_best,
        test_directed_duels_pick_the_pair_that_kills_and_survives,
        test_damage_without_a_number_and_transform_hit_the_enemy,
        test_black_spear_hits_the_enemy,
        test_equipment_targets_an_ally,
        test_unknown_card_playable_once_cost_is_read,
        test_screen_cost_beats_card_sets,
        test_screen_cost_reorders_the_choice,
        test_play_hand_rereads_costs_at_each_play,
        test_cost_reading_is_pruned,
        test_base_costs_switch_restores_card_sets,
        test_rejection_reason_names_the_cause,
        test_board_limit,
        test_grab_point_is_on_screen,
        test_play_card_verifies_result,
        test_the_hand_is_reread_between_two_plays,
        test_play_hand_stops_on_failure,
        test_a_failed_card_stays_aside_for_the_whole_round,
        test_grab_point_avoids_the_overlapping_neighbour,
        test_drag_always_releases_the_button,
        test_cancel_uses_a_left_click_only,
        test_cancel_point_is_calibratable,
        test_spell_needs_a_target_to_be_played,
        test_restrictions_levees,
        test_le_plan_ne_declare_pas_jouable_ce_que_la_decision_refuse,
        test_un_equipement_sans_porteur_nest_pas_annonce_jouable,
        test_une_unite_attach_sans_allie_nest_pas_posee,
        test_vladimir_est_posee_en_validant_a_l_orbe,
        test_vladimir_sans_ennemi_nest_pas_posee,
        test_le_guet_dune_fenetre_imprevue_sarrete_des_que_la_carte_arrive,
        test_lentete_de_why_ne_contredit_pas_ses_verdicts,
        test_un_sort_dont_la_cible_ne_peut_pas_exister_nest_pas_lance,
        test_un_sort_qui_vise_un_suivant_nest_pas_lance_sur_un_champion,
        test_un_sort_qui_peut_frapper_le_nexus_nest_pas_ecarte,
        test_un_sort_qui_se_resout_sans_ennemi_nest_pas_ecarte,
        test_un_soin_sans_allie_vise_notre_nexus,
        test_card_in_limbo_triggers_cancel,
        test_normal_play_does_not_cancel,
        test_attackers_selection,
        test_attack_needs_token,
        test_attack_does_not_confirm_when_nothing_engaged,
        test_blocking_rules,
        test_block_scoring,
        test_block_plan_prefers_small_at_equal_value,
        test_no_chump_block_when_safe,
        test_chump_block_when_lethal,
        test_one_blocker_per_attacker,
        test_pulled_units_already_block_their_attacker,
        test_block_confirms_even_with_nothing,
        test_attack_avoids_suicide,
        test_lethal_overrides_value,
        test_attack_keeps_the_useful_ones,
        test_overwhelm_pierces_the_blocker,
        test_formidable_gets_to_attack,
        test_quickstrike_changes_the_verdict,
        test_barrier_blocks_for_free,
        test_tough_survives_the_trade,
        test_impact_leaks_through_a_perfect_block,
        test_ephemeral_costs_nothing_to_lose,
        test_ephemeral_blocks_for_free,
        test_ephemeral_is_played_when_it_can_swing,
        test_challenge_turns_a_bad_attack_into_a_good_one,
        test_a_low_enemy_nexus_makes_the_bot_attack,
        test_le_mode_plan_lit_les_pv_du_nexus,
        test_no_challenge_when_it_gains_nothing,
        test_vulnerable_is_pulled_by_anyone,
        test_challenge_is_a_single_drag_onto_the_enemy,
        test_failed_challenge_falls_back_to_a_plain_attack,
        test_wait_for_change_returns_early,
        test_play_hand_respects_phase,
        test_opponent_response_to_our_spell_is_passed_through,
        test_respond_to_stack,
        test_our_spell_waiting_for_a_target_is_cancelled_not_passed,
        test_un_bouton_qui_reclame_une_cible_nest_pas_une_priorite_adverse,
        test_une_fenetre_de_choix_retient_aussi_notre_propre_sort,
        test_une_orbe_grise_sans_libelle_sattend_comme_avant,
        test_la_destiny_card_se_choisit_sur_le_plateau,
        test_une_fenetre_prise_fait_avancer_la_resolution,
        test_une_jumelle_en_main_ne_fait_pas_echouer_une_defausse,
        test_une_pile_qui_ne_se_vide_pas_laisse_une_image,
        test_la_capture_du_blocage_precede_le_geste,
        test_the_hand_is_reread_before_grabbing_when_the_reading_is_old,
        test_settling_waits_out_a_series_of_draws,
        test_attack_under_the_stack_is_blocked_before_passing,
        test_play_hand_stops_when_a_spell_lands_on_the_stack,
        test_attack_rereads_positions_between_drags,
        test_engage_retries_a_missed_grab,
        test_engage_does_not_retry_when_a_neighbour_left,
        test_block_rereads_positions_between_drags,
        test_turn_does_not_pass_on_a_declared_attack,
        test_turn_still_ends_when_it_is_ours,
    ):
        test()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) en échec :")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("Tous les tests passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
