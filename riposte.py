#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
riposte.py

Répondre à un sort adverse — à propos, ou pas du tout.

    python riposte.py explain "Deal 3 to an enemy." "Give an ally +0|+3."

--------------------------------------------------------------------
LE PROBLÈME
--------------------------------------------------------------------
Quand un sort adverse attend sur la pile, le bot a une fenêtre pour
répondre. « Lancer le sort le plus cher qu'on a » n'est pas une réponse :
c'est dépenser du mana sur une menace qu'on n'a pas lue. Et l'API ne dit
pas sur QUI l'adversaire a lancé son sort — elle rapporte la carte, pas
sa cible.

--------------------------------------------------------------------
L'IDÉE : LIRE LA MENACE, DÉDUIRE LA PARADE, SINON PASSER
--------------------------------------------------------------------
La description du sort adverse est dans la base de cartes, et
`spells.classify_card` sait déjà en tirer l'effet, le camp visé et le
montant. Vu de LUI, « an enemy » c'est NOUS. On en déduit une menace :

    REMOVAL   il tue, blesse, étourdit, rappelle ou réduit au silence
              une de nos unités (ou toutes) ;
    NEXUS     il frappe notre nexus ;
    BUFF      il renforce une de ses unités (en combat, surtout) ;
    RIEN      il pioche, crée, invoque : rien à parer.

Puis on cherche dans NOS sorts jouables la parade qui répond à CETTE
menace, dans cet ordre de préférence :

    1. CONTRER  « Stop a spell » : la réponse parfaite, cible la pile ;
    2. PROTÉGER une unité menacée — Spellshield contre tout, Barrier ou
                +PV contre des dégâts qu'ils suffisent à encaisser ;
    3. RETIRER  la cible probable de SON renfort, pour le faire tomber
                dans le vide (fizzle) — seulement si elle est identifiable
                (une seule unité adverse engagée, ou une seule en jeu).

Faute de parade UTILE, on passe. Garder son mana vaut mieux qu'un sort
jeté au hasard : c'est exactement ce qu'Ewan a demandé le 03/09/2026 —
une réponse « intelligente », pas une réponse systématique.

--------------------------------------------------------------------
CE QU'ON NE SAIT PAS, ET COMMENT ON TRANCHE
--------------------------------------------------------------------
La cible du sort adverse. On protège donc l'unité MENACÉE LA PLUS
PRÉCIEUSE : celle qu'un adversaire raisonnable vise. Se tromper coûte un
sort de protection ; ne rien faire coûte l'unité.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from typing import List, Optional

import keywords
import spells
from spells import Targeting

# Ce que le sort adverse fait à NOTRE camp. Lu depuis SON texte, où
# « enemy » désigne nos unités et « ally » les siennes.
REMOVAL = "retrait"
NEXUS = "nexus"
BUFF = "renfort"
NOTHING = "rien"

# Effets qui neutralisent une unité sans la tuer : seules Spellshield et
# le contresort y font quelque chose, un +PV ne sert à rien.
NEUTRALIZING = {"STUN", "RECALL", "SILENCE"}

_ALL_ENEMIES_RX = re.compile(r"\ball (?:enemies|enemy units|units|followers)\b", re.I)
_ALL_ALLIES_RX = re.compile(r"\ball allies\b", re.I)
_ENEMY_NEXUS_RX = re.compile(r"\benemy nexus\b", re.I)
_COUNTER_RX = re.compile(r"^stop an? (.+?)\.?(?:\s|$)", re.I)
_STAT_BUFF_RX = re.compile(r"\+(\d+)\|\+(\d+)")
_GRANT_RX = re.compile(r"\b(?:give|grant)\b[^.]*\b(barrier|spellshield|tough)\b", re.I)


@dataclass
class Threat:
    """Ce que le sort adverse va faire, et à qui."""

    kind: str                       # REMOVAL / NEXUS / BUFF / NOTHING
    effect: str = ""                # DAMAGE, KILL, STUN, BUFF...
    amount: Optional[int] = None    # dégâts, quand chiffrés
    aoe: bool = False               # toutes nos unités à la fois
    source: str = ""                # nom du sort adverse
    endangered: list = field(default_factory=list)   # nos unités concernées

    def __str__(self) -> str:
        if self.kind == NOTHING:
            return f"{self.source} : rien à parer"
        who = "toutes nos unités" if self.aoe else (
            ", ".join(c.name for c in self.endangered) or "aucune unité en jeu"
        )
        amount = f" {self.amount}" if self.amount is not None else ""
        return f"{self.source} : {self.kind} ({self.effect}{amount}) sur {who}"


@dataclass
class Response:
    """La parade retenue : quel sort, quels clics, pourquoi."""

    card: object
    targets: tuple
    reason: str
    kind: str                       # contrer / protéger / retirer

    def __str__(self) -> str:
        return f"{self.kind} avec {self.card.name} — {self.reason}"


# ============================================================
# LIRE LA MENACE
# ============================================================

def our_units(snapshot) -> list:
    return [c for c in snapshot.board + snapshot.attack_row if c.is_unit]


def their_units(snapshot) -> list:
    return [c for c in snapshot.enemy_board + snapshot.enemy_attack_row if c.is_unit]


def _would_kill(card, effect: str, amount: Optional[int]) -> bool:
    if effect == "KILL":
        return True
    if effect in ("DAMAGE", "DRAIN") and amount is not None:
        return card.health <= amount
    return False


def read_threat(enemy_spell, snapshot) -> Threat:
    """
    Ce qu'un sort ADVERSE sur la pile nous fait. Le texte est lu sans
    restrictions : on veut comprendre, pas décider si on le jouerait.
    """
    plan = spells.classify_card(enemy_spell, restricted=False)
    text = getattr(enemy_spell, "description", "") or ""
    name = getattr(enemy_spell, "name", "?")
    ours = our_units(snapshot)

    if plan.effect in spells.HARMFUL:
        # Vu de lui, ENEMY et ANYTHING c'est nous ; ANY_UNIT peut l'être.
        on_us = plan.targeting in (Targeting.ENEMY, Targeting.ANY_UNIT, Targeting.ANYTHING)
        aoe = bool(_ALL_ENEMIES_RX.search(text))
        if aoe or on_us:
            if plan.effect in NEUTRALIZING:
                endangered = list(ours)
            else:
                endangered = [c for c in ours if _would_kill(c, plan.effect, plan.amount)]
            kind = REMOVAL
            if not endangered and (_ENEMY_NEXUS_RX.search(text)
                                   or plan.targeting is Targeting.ANYTHING):
                kind = NEXUS
            return Threat(kind, plan.effect, plan.amount, aoe, name, endangered)
        if _ENEMY_NEXUS_RX.search(text):
            return Threat(NEXUS, plan.effect, plan.amount, False, name, [])
        return Threat(NOTHING, plan.effect, plan.amount, False, name, [])

    if plan.effect in ("BUFF", "HEAL"):
        # Un renfort sur SES unités. « an ally », « all allies », ou une
        # unité quelconque quand c'est bénéfique (il ne renforce pas les
        # nôtres).
        if plan.targeting in (Targeting.ALLY, Targeting.ANY_UNIT) or _ALL_ALLIES_RX.search(text):
            return Threat(BUFF, plan.effect, None, bool(_ALL_ALLIES_RX.search(text)), name, [])

    return Threat(NOTHING, plan.effect, plan.amount, False, name, [])


def read_threats(snapshot) -> List[Threat]:
    """Une menace par sort adverse sur la pile, le plus récent d'abord."""
    return [read_threat(c, snapshot) for c in reversed(snapshot.stack_theirs)]


# ============================================================
# LIRE NOS PARADES
# ============================================================

def counter_scope(card) -> Optional[str]:
    """
    « Stop a spell. » → "spell" ; « Stop a fast spell, slow spell, or
    skill. » → "spell skill". None si ce n'est pas un contresort.
    """
    text = getattr(card, "description", "") or ""
    match = _COUNTER_RX.search(text)
    if not match:
        return None
    what = match.group(1).lower()
    scopes = []
    if "spell" in what:
        scopes.append("spell")
    if "skill" in what:
        scopes.append("skill")
    return " ".join(scopes) or None


def can_counter(card, enemy_spell) -> bool:
    scope = counter_scope(card)
    if not scope:
        return False
    if enemy_spell.is_spell:
        return "spell" in scope
    if enemy_spell.is_ability:
        return "skill" in scope
    return False


def protection(card) -> tuple:
    """
    Ce qu'un sort de renfort ALLIÉ apporte en défense : (mot-clé, +PV).

    Spellshield vaut contre tout ce qui cible ; Barrier contre des dégâts
    (un seul coup) ; Tough retire 1. Un +X|+Y protège de Y points.
    """
    text = getattr(card, "description", "") or ""
    grant = _GRANT_RX.search(text)
    keyword = grant.group(1).lower() if grant else ""
    buff = _STAT_BUFF_RX.search(text)
    hp = int(buff.group(2)) if buff else 0
    return keyword, hp


def saves(card, unit, threat: Threat) -> Optional[str]:
    """Ce sort-là sauve-t-il cette unité-là de cette menace ? La raison, ou None."""
    keyword, hp = protection(card)
    if keyword == "spellshield":
        return "Spellshield annule le sort"
    if threat.effect in NEUTRALIZING or threat.effect == "KILL":
        return None
    if threat.effect in ("DAMAGE", "DRAIN"):
        if keyword == "barrier":
            return "Barrier encaisse les dégâts"
        amount = threat.amount or 0
        bonus = hp + (1 if keyword == "tough" else 0)
        if bonus and unit.health + bonus > amount:
            return f"+{bonus} PV : {unit.health} -> {unit.health + bonus} > {amount}"
    return None


def most_precious(cards) -> Optional[object]:
    """L'unité qu'un adversaire raisonnable vise : la plus précieuse, hors Éphémères."""
    real = [c for c in cards if not keywords.dies_anyway(c)] or list(cards)
    return max(real, key=lambda c: (keywords.unit_value(c), c.attack), default=None)


def likely_buff_target(snapshot) -> Optional[object]:
    """
    La cible probable d'un renfort adverse — seulement quand elle est
    IDENTIFIABLE : une seule unité engagée de son côté, ou une seule en jeu.
    """
    engaged = [c for c in snapshot.enemy_attack_row if c.is_unit]
    if len(engaged) == 1:
        return engaged[0]
    theirs = their_units(snapshot)
    if len(theirs) == 1:
        return theirs[0]
    return None


# ============================================================
# DÉCIDER
# ============================================================

def choose_response(snapshot, options, plan_of) -> tuple:
    """
    La parade à la pile adverse, ou (None, raison).

    `options` : nos sorts jouables maintenant (mana, vitesse), les plus
    chers d'abord — cf. actions.response_options. `plan_of(card)` rend
    (plan, cibles, description) tels que `spell_is_castable` les calcule,
    pour les parades qui gardent leur ciblage normal.
    """
    threats = read_threats(snapshot)
    if not threats:
        return None, "aucun sort adverse sur la pile"
    threat = next((t for t in threats if t.kind != NOTHING), threats[0])
    if threat.kind == NOTHING:
        return None, f"{threat} — on garde notre mana"

    enemy_spell = snapshot.stack_theirs[-1]
    counters = [c for c in options if can_counter(c, enemy_spell)]
    protectors = [c for c in options if counter_scope(c) is None]

    # 1. Contrer : la réponse exacte, quelle que soit la menace lue.
    if counters:
        card = min(counters, key=lambda c: c.cost)
        return Response(card, (enemy_spell.center,), f"contre {enemy_spell.name}", "contrer"), str(threat)

    # 2. Protéger l'unité menacée la plus précieuse.
    if threat.kind == REMOVAL and threat.endangered:
        unit = most_precious(threat.endangered)
        for card in sorted(protectors, key=lambda c: c.cost):
            plan, _, _ = plan_of(card)
            if plan.effect not in ("BUFF", "HEAL") or plan.targeting is not Targeting.ALLY:
                continue
            why = saves(card, unit, threat)
            if why:
                return Response(card, (unit.center,), f"protège {unit.name} : {why}", "protéger"), str(threat)
        return None, f"{threat} — aucune parade ne sauve {unit.name}"

    if threat.kind == REMOVAL:
        return None, f"{threat} — rien à sauver"

    # 3. Retirer la cible probable de son renfort.
    if threat.kind == BUFF:
        target = likely_buff_target(snapshot)
        if target is None:
            return None, f"{threat} — cible du renfort non identifiable, on passe"
        for card in sorted(protectors, key=lambda c: c.cost):
            plan, targets, _ = plan_of(card)
            if plan.effect not in spells.HARMFUL or not plan.needs_click:
                continue
            if plan.targeting not in (Targeting.ENEMY, Targeting.ANY_UNIT, Targeting.ANYTHING):
                continue
            if _would_kill(target, plan.effect, plan.amount) or plan.effect in NEUTRALIZING:
                return Response(card, (target.center,), f"retire {target.name} avant son renfort", "retirer"), str(threat)
        return None, f"{threat} — rien ne retire {target.name}"

    return None, f"{threat} — pas de parade prévue"


# ============================================================
# CLI
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Lecture d'une menace adverse.")
    parser.add_argument("texts", nargs="+", help="descriptions de sorts adverses")
    args = parser.parse_args()
    for text in args.texts:
        plan = spells.classify_text(text, restricted=False)
        print(f"« {text} »")
        print(f"   effet {plan.effect}, cible {plan.targeting.value}, montant {plan.amount}")
        print(f"   contresort : {counter_scope(type('C', (), {'description': text})())}")
        print(f"   protection : {protection(type('C', (), {'description': text})())}")


if __name__ == "__main__":
    main()
