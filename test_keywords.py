#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_keywords.py

Tests de la RÉSOLUTION D'UNE FRAPPE, mots-clés compris.

`keywords.resolve_duel` est une fonction pure : pas de souris, pas
d'écran, pas d'API. C'est la partie du bot la plus facile à vérifier
exhaustivement, et celle où une erreur de règle coûte le plus cher —
un blocage jugé protecteur qui ne l'est pas, c'est la partie.

Chaque test énonce la règle du jeu qu'il vérifie. Quand le
comportement en jeu contredit un de ces tests, c'est ma lecture de la
règle qui est fausse : corriger ici, pas dans `actions.py`.

    python test_keywords.py
"""

from __future__ import annotations

import sys
import types

# --- bouchon pyautogui pour tourner sans écran --------------------------
try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:
    stub = types.ModuleType("pyautogui")
    stub.size = lambda: (1920, 1080)
    stub.screenshot = lambda *a, **k: None
    sys.modules["pyautogui"] = stub

import keywords
from game_state import BoardCard

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ============================================================
# FABRICATION DES UNITÉS
# ============================================================

def unit(attack: int, health: int, *kw: str, name: str = "") -> BoardCard:
    """
    Une unité de test. Les mots-clés sont passés en RÉFÉRENCE interne
    (« QuickStrike »), comme card_sets les fournit.
    """
    return BoardCard(
        card_id=id(kw) % 10_000,
        code="TEST",
        name=name or f"{attack}/{health} {'+'.join(kw) or 'vanille'}",
        base_cost=1,
        base_attack=attack,
        base_health=health,
        type="Unit",
        keywords=kw,
        keyword_refs=kw,
        description="",
        spell_speed="",
        local=True,
        zone="board",
        ratio=0.15,
        box=(0, 0, 100, 100),
        center=(50, 50),
        known=True,
    )


# ============================================================
# LECTURES DÉRIVÉES
# ============================================================

def test_reading_the_keywords():
    print("\nLecture des mots-clés")

    # Le libellé affiché et la référence interne doivent matcher tous deux.
    card = BoardCard(
        card_id=1, code="X", name="X", base_cost=1, base_attack=2, base_health=2,
        type="Unit", keywords=("Can't Block",), keyword_refs=("CantBlock",),
        description="", spell_speed="", local=True, zone="board", ratio=0.15,
        box=(0, 0, 1, 1), center=(0, 0), known=True,
    )
    check("libellé affiché reconnu", keywords.has(card, "Can't Block"))
    check("référence interne reconnue", keywords.has(card, "CantBlock"))
    check("ponctuation et casse ignorées", keywords.has(card, "cant block"))
    check("mot-clé absent", keywords.has(card, "Barrier") is False)

    # Formidable frappe avec ses PV. C'est le cas que l'ancien filtre
    # `attack > 0` écartait complètement.
    formidable = unit(0, 7, "Formidable")
    check("Formidable frappe avec ses PV", keywords.strike_power(formidable) == 7)
    check("attaque de base inchangée", formidable.attack == 0)
    check("une vanille frappe avec son attaque", keywords.strike_power(unit(3, 2)) == 3)

    # Impact ajoute son point au nexus, même sans bloqueur.
    check("Impact non bloqué", keywords.unblocked_damage(unit(2, 2, "Impact")) == 3)
    check("vanille non bloquée", keywords.unblocked_damage(unit(2, 2)) == 2)
    check("Formidable non bloquée", keywords.unblocked_damage(unit(0, 7, "Formidable")) == 7)

    # Deux morts gratuites.
    check("mort d'une Éphémère gratuite", keywords.death_cost(unit(4, 4, "Ephemeral")) == 0)
    check("mort d'une Sans-mort gratuite", keywords.death_cost(unit(4, 4, "Deathless")) == 0)
    check("mort d'une vanille coûteuse", keywords.death_cost(unit(4, 4)) == 8)

    # `dies_anyway` ne dit PAS la même chose que `death_cost` à zéro : une
    # Sans-mort revient (affaiblie), une Éphémère non. Les décisions qui
    # demandent « sera-t-elle encore là au round suivant ? » — quoi poser,
    # quoi jeter devant un attaquant, quoi renforcer — dépendent de cette
    # distinction, et les confondre ferait sacrifier une Sans-mort pour rien.
    check("l'Éphémère ne verra pas le round suivant",
          keywords.dies_anyway(unit(4, 4, "Ephemeral")) is True)
    check("la Sans-mort, si", keywords.dies_anyway(unit(4, 4, "Deathless")) is False)
    check("une vanille aussi", keywords.dies_anyway(unit(4, 4)) is False)
    check("valeur d'une Formidable", keywords.unit_value(unit(0, 7, "Formidable")) == 14)


# ============================================================
# LE DUEL DE BASE, SANS MOT-CLÉ
# ============================================================

def test_vanilla_duel():
    print("\nDuel sans mot-clé")

    # Frappes SIMULTANÉES : deux unités qui se tuent meurent toutes deux.
    duel = keywords.resolve_duel(unit(3, 3), unit(3, 3))
    check("échange mutuel", duel.attacker_dies and duel.blocker_dies)

    # Le gros mange le petit sans une égratignure.
    duel = keywords.resolve_duel(unit(5, 5), unit(1, 2))
    check("le petit meurt", duel.blocker_dies)
    check("le gros survit", duel.attacker_dies is False)

    # Une muraille absorbe sans tuer.
    duel = keywords.resolve_duel(unit(5, 5), unit(1, 7))
    check("la muraille survit", duel.blocker_dies is False)
    check("l'attaquant survit aussi", duel.attacker_dies is False)

    # Sans mot-clé, rien ne passe au nexus.
    check("aucun dégât traversant", duel.nexus_damage == 0)


# ============================================================
# ORDRE DES FRAPPES
# ============================================================

def test_quick_strike():
    print("\nFrappe Rapide : elle frappe d'abord")

    # 3/3 Frappe Rapide contre 3/3 vanille : elle tue avant d'être
    # touchée. L'ancien calcul (attack >= health des deux côtés) y voyait
    # un échange mutuel — c'est-à-dire exactement l'inverse.
    duel = keywords.resolve_duel(unit(3, 3, "QuickStrike"), unit(3, 3))
    check("le bloqueur meurt", duel.blocker_dies)
    check("l'attaquant est INTACT", duel.attacker_dies is False)

    # En DÉFENSE, Frappe Rapide ne sert à rien : seul l'attaquant en
    # bénéficie. Même duel dans l'autre sens.
    duel = keywords.resolve_duel(unit(3, 3), unit(3, 3, "QuickStrike"))
    check("inutile en défense : échange mutuel", duel.attacker_dies and duel.blocker_dies)

    # Si la frappe rapide ne tue pas, la riposte a lieu normalement.
    duel = keywords.resolve_duel(unit(2, 2, "QuickStrike"), unit(3, 5))
    check("bloqueur survivant riposte", duel.attacker_dies)
    check("et il est encore là", duel.blocker_dies is False)


def test_double_strike():
    print("\nFrappe Double : avant, puis avec")

    # 2/3 Frappe Double contre 0/4 : 2 puis 2 = 4, le bloqueur tombe
    # alors qu'une seule frappe n'y suffisait pas.
    duel = keywords.resolve_duel(unit(2, 3, "DoubleStrike"), unit(0, 4))
    check("deux frappes cumulées tuent", duel.blocker_dies)

    # Contre un 3/3 : la première frappe (2) ne tue pas, il riposte (3)
    # et tue l'attaquant à 3 PV — qui frappe quand même une seconde fois,
    # les frappes étant simultanées. Total 4 : le bloqueur meurt aussi.
    duel = keywords.resolve_duel(unit(2, 3, "DoubleStrike"), unit(3, 3))
    check("l'attaquant meurt", duel.attacker_dies)
    check("mais sa 2e frappe porte quand même", duel.blocker_dies)


# ============================================================
# ATTÉNUATION DES DÉGÂTS
# ============================================================

def test_barrier():
    print("\nBarrière : la première instance est annulée")

    # 9/9 contre 1/1 Barrière : le bloqueur ne prend RIEN.
    duel = keywords.resolve_duel(unit(9, 9), unit(1, 1, "Barrier"))
    check("le bloqueur survit à tout", duel.blocker_dies is False)

    # Une seule instance : la Frappe Double la traverse au second coup.
    duel = keywords.resolve_duel(unit(2, 3, "DoubleStrike"), unit(0, 2, "Barrier"))
    check("la 2e frappe passe la barrière brisée", duel.blocker_dies)

    # Et une Barrière à l'attaque protège l'attaquant.
    duel = keywords.resolve_duel(unit(1, 1, "Barrier"), unit(9, 9))
    check("l'attaquant sous barrière survit", duel.attacker_dies is False)

    # Barrière annule aussi l'excédent de Submersion : rien n'est infligé,
    # donc rien ne traverse.
    duel = keywords.resolve_duel(unit(6, 6, "Overwhelm"), unit(0, 2, "Barrier"))
    check("Submersion ne traverse pas une barrière", duel.nexus_damage == 0, duel)


def test_tough():
    print("\nCoriace : -1 par instance")

    # 3/3 contre 1/3 Coriace : 3-1 = 2 dégâts, il reste 1 PV. L'ancien
    # calcul le déclarait mort.
    duel = keywords.resolve_duel(unit(3, 3), unit(1, 3, "Tough"))
    check("le Coriace survit d'un PV", duel.blocker_dies is False)

    # PAR INSTANCE : deux frappes de 3 sur un Coriace à 3 PV font 2+2.
    duel = keywords.resolve_duel(unit(3, 9, "DoubleStrike"), unit(0, 3, "Tough"))
    check("deux frappes réduites suffisent", duel.blocker_dies)

    # Une frappe de 1 sur un Coriace ne fait rien du tout.
    duel = keywords.resolve_duel(unit(1, 5), unit(1, 1, "Tough"))
    check("une frappe de 1 est absorbée", duel.blocker_dies is False)


# ============================================================
# CE QUI ATTEINT LE NEXUS
# ============================================================

def test_overwhelm_and_impact():
    print("\nSubmersion et Impact")

    # 6/6 Submersion contre 1/2 : 4 traversent.
    duel = keywords.resolve_duel(unit(6, 6, "Overwhelm"), unit(1, 2))
    check("excédent calculé", duel.overwhelm == 4, duel.overwhelm)
    check("nexus touché", duel.nexus_damage == 4, duel)

    # Contre 1/7, rien ne traverse.
    duel = keywords.resolve_duel(unit(6, 6, "Overwhelm"), unit(1, 7))
    check("gros bloqueur absorbe tout", duel.nexus_damage == 0, duel)

    # Coriace réduit l'excédent : 6-1 = 5 dégâts sur 2 PV = 3 qui passent.
    duel = keywords.resolve_duel(unit(6, 6, "Overwhelm"), unit(1, 2, "Tough"))
    check("Coriace réduit aussi l'excédent", duel.overwhelm == 3, duel.overwhelm)

    # Impact touche le nexus MÊME quand le blocage tient : c'est
    # exactement le cas que l'ancien `damage_through` rendait à 0.
    duel = keywords.resolve_duel(unit(2, 2, "Impact"), unit(1, 9))
    check("Impact passe malgré le blocage", duel.nexus_damage == 1, duel)

    # Frappe Double + Impact : deux frappes, deux points.
    duel = keywords.resolve_duel(unit(1, 5, "DoubleStrike", "Impact"), unit(0, 9))
    check("Impact compte par frappe", duel.impact == 2, duel.impact)


def test_lifesteal():
    print("\nVol d'âme")

    duel = keywords.resolve_duel(unit(3, 3, "Lifesteal"), unit(1, 5))
    check("soigne les dégâts infligés", duel.attacker_lifesteal == 3, duel)

    # On ne soigne que ce qui est RÉELLEMENT infligé : une barrière en
    # face, et le vol d'âme ne rend rien.
    duel = keywords.resolve_duel(unit(3, 3, "Lifesteal"), unit(1, 5, "Barrier"))
    check("rien d'infligé, rien de soigné", duel.attacker_lifesteal == 0, duel)

    # Un bloqueur Vol d'âme soigne SON nexus, pas le nôtre.
    duel = keywords.resolve_duel(unit(1, 5), unit(3, 3, "Lifesteal"))
    check("le soin est du côté du bloqueur", duel.blocker_lifesteal == 3, duel)
    check("et pas du côté attaquant", duel.attacker_lifesteal == 0, duel)


# ============================================================
# COMBINAISONS
# ============================================================

def test_challenge_legality():
    print("\nDroit de tirer une unité en défense")

    challenger = unit(4, 4, "Challenger")
    vanilla = unit(3, 3)
    vulnerable = unit(3, 3, "Vulnerable")

    # Challenger est sur NOTRE unité : elle choisit n'importe quel ennemi.
    check("un Challenger tire n'importe qui",
          keywords.can_challenge(challenger, vanilla) is True)
    # Vulnerable est sur l'unité ADVERSE : n'importe qui peut la tirer.
    check("une Vulnerable est tirable par tous",
          keywords.can_challenge(vanilla, vulnerable) is True)
    check("sans l'un ni l'autre, aucun tirage",
          keywords.can_challenge(vanilla, vanilla) is False)

    # Tirer une unité qui ne peut pas bloquer n'a aucun sens : le client
    # refuserait le geste.
    check("Immobile n'est pas tirable",
          keywords.can_challenge(challenger, unit(3, 3, "Immobile")) is False)
    check("Ne peut pas bloquer n'est pas tirable",
          keywords.can_challenge(challenger, unit(3, 3, "CantBlock")) is False)


def test_combinations():
    print("\nCombinaisons")

    # Frappe Rapide + Submersion : elle tue d'abord, l'excédent passe, et
    # elle ne prend rien.
    duel = keywords.resolve_duel(unit(6, 3, "QuickStrike", "Overwhelm"), unit(5, 2))
    check("tué avant de riposter", duel.blocker_dies and not duel.attacker_dies)
    check("excédent quand même compté", duel.overwhelm == 4, duel.overwhelm)

    # Formidable + Submersion : c'est bien la PUISSANCE (les PV) qui
    # déborde, pas l'attaque à 0.
    duel = keywords.resolve_duel(unit(0, 7, "Formidable", "Overwhelm"), unit(1, 2))
    check("Formidable déborde de 5", duel.overwhelm == 5, duel.overwhelm)

    # Barrière + Coriace : la barrière prend la première instance,
    # Coriace la suivante.
    duel = keywords.resolve_duel(unit(2, 9, "DoubleStrike"), unit(0, 2, "Barrier", "Tough"))
    check("barrière puis coriace : survit", duel.blocker_dies is False, duel)


def main():
    print("=" * 60)
    print("TESTS DE keywords.py")
    print("=" * 60)

    test_reading_the_keywords()
    test_vanilla_duel()
    test_quick_strike()
    test_double_strike()
    test_barrier()
    test_tough()
    test_overwhelm_and_impact()
    test_lifesteal()
    test_challenge_legality()
    test_combinations()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} échec(s) : " + ", ".join(FAILURES))
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
