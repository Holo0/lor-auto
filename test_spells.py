#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_spells.py

Tests du classement des sorts et du choix de cible.

Le classifieur est une fonction pure sur du texte : il se teste
exhaustivement, sans jeu ni souris. C'est important, parce que c'est la
pièce où une erreur se paie le plus cher — un sort mal ciblé peut se
retourner contre nous, et un sort mal classé fige la partie.

    python test_spells.py
"""

from __future__ import annotations

import io
import sys
import types

try:  # pragma: no cover
    import pyautogui  # noqa: F401
except Exception:
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.size = lambda: (1920, 1080)
    for name in ("screenshot", "moveTo", "click", "mouseDown", "mouseUp"):
        setattr(stub, name, lambda *a, **k: None)
    sys.modules["pyautogui"] = stub

import spells
from spells import Targeting, classify_text

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def plan_of(text):
    return classify_text(text)


def refus_tous_libelles(report) -> bool:
    """
    Tout refus du rapport de couverture porte-t-il un libellé lisible,
    et sont-ils TOUS comptés ?

    Deux questions, parce que deux façons de perdre un motif : un plan
    refusé dont `reason` est vide (la clé devient "" et le backlog
    d'`ecartees` montre une ligne blanche), et un plan refusé qui
    n'entre pas du tout dans le tableau des motifs (la somme des
    compteurs décroche alors du nombre de REFUSED).
    """
    motifs = report["reasons"]
    refus = sum(v for (_, ciblage), v in report["counts"].items()
                if ciblage == "REFUSED")
    if sum(motifs.values()) != refus:
        return False
    return all(isinstance(m, str) and m.strip() for m in motifs)


# ============================================================
# COMPTAGE DES CIBLES
# ============================================================

def test_target_counting():
    print("\nComptage des marqueurs de cible")

    # Zéro marqueur singulier : le jeu n'attend aucun clic.
    for text in (
        "Deal 3 to all enemies.",
        "Draw 2.",
        "Give allies +1|+1 this round.",
        "Summon a Spiderling.",
    ):
        plan = plan_of(text)
        check(f"aucune cible : {text[:34]}", plan.targeting is Targeting.NONE,
              plan.targeting)

    # Un marqueur : le camp vient du marqueur lui-même.
    cases = {
        "Deal 3 to an enemy.": Targeting.ENEMY,
        "Give an ally +2|+2 this round.": Targeting.ALLY,
        "Kill a unit.": Targeting.ANY_UNIT,
        "Deal 3 to anything.": Targeting.ANYTHING,
        "Silence a follower.": Targeting.ANY_UNIT,
        "Stun an attacking enemy.": Targeting.ENEMY,
    }
    for text, expected in cases.items():
        plan = plan_of(text)
        check(f"{expected.value:<16} : {text[:34]}", plan.targeting is expected,
              plan.targeting)

    # Deux marqueurs : on refuse, le bot ne sait pas enchaîner deux clics.
    for text in (
        "Deal 1 to an ally to give another ally +2|+2 this round.",
        "Remove Ephemeral from an ally to grant it to an enemy.",
        "An ally and an enemy strike each other.",
    ):
        plan = plan_of(text)
        check(f"cibles multiples refusées : {text[:30]}",
              plan.targeting is Targeting.REFUSED, plan.targeting)


def test_qualified_allies_are_still_allies():
    """
    UN ADJECTIF DEVANT « ALLY » RESTREINT LA CIBLE, IL NE LA SUPPRIME PAS.

    « An Equipped ally strikes an enemy. » — Lame féroce (06NX034), vue en
    jeu le 22/08/2026. `\\ban ally\\b` ne reconnaissait pas « an Equipped
    ally » : il ne restait qu'un marqueur, l'ennemi, et le bot cliquait
    directement dessus au lieu de refuser un sort à deux clics.

    Treize cartes de la base changent de verdict : neuf passent de
    « aucun clic » (donc partie figée puis annulation) à un clic sur un
    allié, et quatre — Lame féroce, Whirling Death et son jeton, Fish
    Fight — d'un clic SUR L'ENNEMI à un refus franc.
    """
    print("\nAlliés qualifiés")

    # Un seul marqueur, mais il est bien là : ces sorts DEMANDENT un clic
    # sur un allié, et avant ils n'en demandaient aucun.
    for text in (
        "Grant a damaged ally +3|+3.",
        "Remove an attacking ally from combat to Rally.",
        "A 1 cost ally starts a free attack.",
        "A battling ally strikes all battling enemies.",
    ):
        plan = classify_text(text, restricted=False)
        check(f"allié qualifié lu : {text[:38]:<40}",
              plan.targeting is Targeting.ALLY, plan.targeting)

    # Deux marqueurs : le refus d'INCAPACITÉ, celui qui survit à la levée
    # des restrictions. C'est le cas de la Lame féroce.
    for text, quoi in (
        ("An Equipped ally strikes an enemy.", "Lame féroce"),
        ("A battling ally strikes a battling enemy.", "Whirling Death"),
        ("An Equipped ally strikes an enemy, then is unequipped.", "Fish Fight"),
    ):
        plan = classify_text(text, restricted=False)
        check(f"{quoi} : refusé", plan.targeting is Targeting.REFUSED, plan)
        check(f"   {quoi} : incapacité, pas prudence", plan.impossible is True, plan)
        check(f"   {quoi} : et pas un ciblage d'ennemi",
              plan.targeting is not Targeting.ENEMY, plan.targeting)

    # « A RANDOM ALLY » N'EST PAS UNE CIBLE : c'est le jeu qui choisit.
    # Le compter ferait cliquer une unité au hasard sur un sort qui se
    # résout tout seul.
    for text in (
        "Revive a random ally that died this round.",
        "Deal 1 damage to a random ally.",
        "Grant a random ally in hand +1|+1.",
    ):
        plan = classify_text(text, restricted=False)
        check(f"aléatoire, aucun clic : {text[:34]:<36}",
              plan.targeting is Targeting.NONE, plan.targeting)

    # Et la désignation DANS LA MAIN garde la priorité sur le nouveau
    # marqueur : « an ally in hand » est un clic dans la main, pas sur le
    # plateau.
    plan = classify_text("Grant an ally in hand +3|+3.")
    check("« an ally in hand » reste une désignation en main",
          plan.targeting is Targeting.HAND, plan.targeting)


def test_overlapping_markers():
    print("\nMarqueurs qui se recouvrent")

    # « an allied follower » contient « a follower » : sans dédoublonnage
    # ça compterait deux cibles et le sort serait refusé à tort.
    plan = plan_of("Give an allied follower +1|+1.")
    check("un seul marqueur retenu", plan.targeting is Targeting.ALLY, plan.targeting)


def test_bare_another_is_a_second_target():
    """
    « ANOTHER » SEUL, SANS RÉPÉTER LE CAMP, RESTE UNE DEUXIÈME CIBLE DU
    MÊME GENRE — PAS UN REFUS, UN DEUXIÈME CLIC.

    « Deal 2 to an enemy and Stun another. » — Lien cosmique (Cosmic
    Binding, 06BC044), signalé en jeu le 26/08/2026 : le bot cliquait
    l'ennemi désigné par « an enemy », lançait les dégâts, et restait
    bloqué en attente du second clic que réclame « another » — jamais vu
    comme une cible puisqu'aucun marqueur de SINGULAR_TARGETS ne
    reconnaissait la forme nue. Le sort n'est PAS pour autant hors de
    portée : « another » ne répète pas le camp parce qu'il désigne un
    AUTRE exemplaire du même geste, exactement ce que `choose_targets`
    sait répéter en excluant la cible déjà prise. Trueshot Barrage,
    Statikk Shock et Shock Blast partagent le même moule.
    """
    print("\n« another » nu : une deuxième cible, pas un refus")

    # LE CAMP ATTENDU A CHANGÉ POUR TROIS DE CES QUATRE SORTS le
    # 08/11/2026, et c'est le sujet de
    # `test_un_sort_qui_peut_frapper_le_nexus_adverse_le_vise` : ce test-ci
    # porte sur le COMPTE des clics (« another » nu), pas sur le camp, et
    # il écrivait `Targeting.ENEMY` par simple constat de l'époque. Or
    # « an enemy OR THE ENEMY NEXUS » offre deux endroits où le clic peut
    # tomber, et le nexus, lui, est toujours là : c'est un
    # `Targeting.ANYTHING`. Lien cosmique, qui ne nomme aucun nexus, reste
    # un ciblage d'ennemi — le compte des cibles, lui, ne bouge nulle part.
    for text, quoi, extra, cible in (
        ("Deal 2 to an enemy and Stun another.", "Lien cosmique", 1, Targeting.ENEMY),
        ("Deal 1 to an enemy or the enemy Nexus, and 1 to another.", "Statikk Shock",
         1, Targeting.ANYTHING),
        ("Deal 3 to an enemy or the enemy Nexus, and 3 to another.", "Shock Blast",
         1, Targeting.ANYTHING),
        ("Deal 3 to an enemy or the enemy Nexus, 2 to another, and 1 to another.",
         "Trueshot Barrage", 2, Targeting.ANYTHING),
    ):
        for restricted in (True, False):
            plan = classify_text(text, restricted=restricted)
            check(f"[{'prudent' if restricted else 'permissif'}] {quoi} : jouable",
                  plan.playable, plan)
            check(f"   {quoi} : ciblage {cible.value}", plan.targeting is cible, plan)
            check(f"   {quoi} : {extra} cible(s) en plus", plan.extra_targets == extra, plan)
            check(f"   {quoi} : {extra + 1} clics au total",
                  plan.total_targets == extra + 1, plan)

    # La forme SUBSTANTIVÉE (« another unit », « another enemy », ...) est
    # une vraie cible à elle seule, pas seulement un compteur : « Swap my
    # stats with another unit. » (Robot défectueux, 04PZ020) n'a AUCUN
    # autre marqueur dans son texte. Sans substantif reconnu, le sort
    # passait pour n'avoir aucune cible, et le jeu restait bloqué en
    # attente d'un clic que rien ne prévoyait.
    plan = classify_text("Swap my stats with another unit.", restricted=False)
    check("« another unit » seul reste une cible", plan.targeting is Targeting.ANY_UNIT,
          plan.targeting)
    check("   et un seul clic", plan.total_targets == 1, plan)

    # « one after another » EST UN FAUX AMI : son sens est adverbial, sur
    # un effet de combat déjà écarté par le refus dédié « combat dirigé,
    # deux cibles ». Le confondre avec une deuxième cible ferait regretter
    # à ces cartes une capacité que restricted=False leur laisse tenter.
    for text in (
        "An ally strikes the strongest and weakest enemies one after another.",
        "Boost 2 allies, then they Strike an enemy one after another.",
    ):
        plan = classify_text(text, restricted=False)
        check(f"combat, pas une deuxième cible : {text[:34]}",
              plan.targeting is not Targeting.REFUSED or not plan.impossible, plan)

    # Un « another » qui n'accompagne AUCUN premier marqueur ne compte pas
    # : un effet automatique (« Summon another at the next Round Start »)
    # n'a rien à cliquer, et lui inventer une cible ferait chercher un clic
    # qui ne vient jamais.
    plan = classify_text("Summon another at the next Round Start.")
    check("« another » isolé, sans premier marqueur : aucune cible",
          plan.targeting is Targeting.NONE, plan.targeting)

    # UN MARQUEUR EXPLICITE RÉPÉTÉ N'EST PAS LA MÊME FAMILLE. « Deal 1 to
    # an ally to give another ally +2|+2 » (Transfusion, 01NX047) est un
    # COÛT puis une RÉCOMPENSE, pas deux fois le même geste : ça reste
    # refusé, exactement comme avant.
    plan = classify_text("Deal 1 to an ally to give another ally +2|+2 this round.")
    check("Transfusion : toujours refusée (coût puis récompense)",
          plan.targeting is Targeting.REFUSED, plan)
    check("   incapacité, pas prudence", plan.impossible is True, plan)


def test_choose_targets_excludes_previous_picks():
    """
    Les cibles supplémentaires sont des cibles DIFFÉRENTES.

    « another » désigne un AUTRE exemplaire : `choose_targets` doit donc
    exclure ce qu'il vient de choisir avant de redemander une cible, sans
    quoi Lien cosmique désignerait deux fois le même ennemi au lieu des
    deux qu'il réclame.
    """
    print("\nchoose_targets exclut les cibles déjà prises")

    snap = build_snapshot()
    plan = classify_text("Deal 2 to an enemy and Stun another.")
    check("plan à deux cibles", plan.total_targets == 2, plan)

    picks = spells.choose_targets(plan, snap)
    check("deux cibles trouvées", len(picks) == 2, picks)
    points = [p for p, _ in picks]
    check("des points DIFFÉRENTS", len(set(points)) == len(points), points)

    # Trop de cibles demandées pour ce que le plateau offre : on rend ce
    # qu'on peut, à l'appelant de constater que ça ne suffit pas plutôt
    # que de jouer le sort à moitié.
    from test_actions import blocking_snapshot
    seul = blocking_snapshot(["BRUTE"], ["SMALL"])   # un seul ennemi en jeu
    picks = spells.choose_targets(plan, seul)
    check("une seule cible disponible, une seule rendue", len(picks) == 1, picks)


# ============================================================
# GARDE-FOUS
# ============================================================

def test_harmful_on_ally_refused():
    print("\nEffet néfaste sur notre camp")

    # Ce sont des coûts : le bot sacrifierait sa meilleure unité sans
    # comprendre la contrepartie.
    cases = [
        "Kill an ally.",
        "Deal 1 to an allied follower.",
        "Drain 2 from an ally.",
        "Recall an ally.",
    ]
    for text in cases:
        plan = plan_of(text)
        check(f"refusé : {text}", plan.targeting is Targeting.REFUSED, plan.targeting)
        check(f"   raison nommée : {text[:20]}", "propre unité" in plan.reason, plan.reason)

    # Un renfort sur notre camp reste évidemment autorisé.
    plan = plan_of("Give an ally +3|+0 this round.")
    check("renfort sur allié autorisé", plan.targeting is Targeting.ALLY, plan.targeting)


def test_unknown_effect_on_ally_refused():
    print("\nEffet non reconnu sur notre camp")

    plan = plan_of("Flurbate an ally beyond the veil.")
    check("verbe inconnu sur allié refusé", plan.targeting is Targeting.REFUSED, plan.targeting)

    # Sur l'adversaire, un verbe inconnu est acceptable : au pire c'est
    # gaspillé, ça ne peut pas nous coûter une unité.
    plan = plan_of("Flurbate an enemy beyond the veil.")
    check("verbe inconnu sur ennemi autorisé", plan.targeting is Targeting.ENEMY, plan.targeting)


def test_buff_on_enemy():
    print("\nRenfort dirigé sur l'adversaire")

    # « give an enemy Vulnerable » est un MALUS déguisé en don : à jouer.
    plan = plan_of("Give an enemy Vulnerable this round.")
    check("malus déguisé autorisé", plan.targeting is Targeting.ENEMY, plan.targeting)

    # En revanche, donner des statistiques à un ennemi est un vrai cadeau.
    plan = plan_of("Give an enemy +2|+2 this round.")
    check("vrai renfort refusé", plan.targeting is Targeting.REFUSED, plan.targeting)
    check("   raison nommée", "adverse" in plan.reason, plan.reason)


def test_structural_refusals():
    print("\nRefus structurels")

    cases = {
        "To play, discard 1.": "coût additionnel",
        "Pick a follower.": "choix de carte",
        "Choose one: deal 2, or heal 2.": "choix de carte",
        "You may recall an ally.": "optionnel",
        "A battling ally strikes a battling enemy.": "combat dirigé",
        "Stop a Fast spell, Slow spell, or Skill.": "contresort",
        # « Transform a follower into a copy. » était ici, motif
        # « cibles ». Ce texte est inventé (il n'existe nulle part dans
        # la base) et il encodait le contresens corrigé le 08/11/2026 :
        # une transformation nomme un JETON, pas une seconde cible, et
        # ne demande qu'un clic. Le vrai sort à deux clics de cette
        # famille, Hextech Transmogulator, reste refusé — par le compte
        # générique des marqueurs, pas par un refus structurel. Voir
        # test_une_transformation_nomme_un_jeton_pas_une_seconde_cible.
    }
    # LE MOTIF EST VÉRIFIÉ, PAS SEULEMENT LE REFUS (08/11/2026). La
    # valeur du dictionnaire n'était lue par aucune assertion : la table
    # disait quel refus elle attendait, et le test se contentait de
    # « refusé ». N'importe quelle ligne de `REFUSALS` pouvait donc
    # prendre la place d'une autre sans que rien ne rougisse — c'est ce
    # qui a laissé vivre le contresens « transform » / « deux cibles ».
    for text, expected in cases.items():
        plan = plan_of(text)
        check(f"{text[:38]:<38} refusé", plan.targeting is Targeting.REFUSED, plan.targeting)
        check(f"   motif : {expected}", expected in plan.reason, plan.reason)


def test_hand_designation():
    """
    Les effets qui demandent de désigner une carte DANS LA MAIN sont
    reconnus, avec le bon nombre de cartes à cliquer.

    Textes réels, tirés de card_sets. Aucun ne nomme de cible au sens de
    SINGULAR_TARGETS : ils passaient donc pour des effets automatiques, et
    la partie restait figée sur un choix que rien n'honorait — le cas
    « Freljordian Lorekeeper » (98FR019), observé en jeu.
    """
    print("\nDésignation dans la main")

    # `consommée` est la quatrième question, et elle ne se déduit pas des
    # trois autres : « Equip me with an equipment from hand » est un cadeau
    # ET la carte s'en va ; « Create an exact copy of a spell in hand »
    # (Elora) est un cadeau ET elle reste. S'être trompé faisait annuler
    # une pose parfaitement résolue.
    #
    #                                            nombre, type, cadeau, consommée
    cases = {
        "Updraft 1 to draw a card of the same type (unit, spell, landmark or equipment).":
            (1, "any", False, True),
        "Updraft 2 to draw 2 at the next Round Start.": (2, "any", False, True),
        "Discard a card to draw 1.": (1, "any", False, True),
        "Discard 2 to draw 1.": (2, "any", False, True),
        # « costs 2 or less » est un seuil, pas un choix : la carte doit
        # rester jouable malgré son « or ».
        "Equip me with an equipment that costs 2 or less from hand.":
            (1, "equipment", True, True),
        "Create an exact copy of a spell in hand.": (1, "spell", True, False),
        "Create an exact copy of a card in hand other than Zephyr Sage.":
            (1, "any", True, False),
        "Grant Barrier to an ally in hand.": (1, "unit", True, False),
        "Grant an ally in hand +3|+3.": (1, "unit", True, False),
        "Reduce the cost of a card in hand by 1.": (1, "any", True, False),
        # Un coût, malgré la formulation « ... in hand » : l'effet est
        # néfaste, donc on donne la pire carte et non la meilleure — et
        # celle-là quitte bel et bien la main.
        "Obliterate a unit in hand to summon a Stormcarved Spire.":
            (1, "unit", False, True),
    }
    for text, (picks, kind, boon, spent) in cases.items():
        plan = plan_of(text)
        check(f"main : {text[:40]:<40}", plan.targeting is Targeting.HAND, plan.targeting)
        check(f"  {picks} carte(s), type {kind}, cadeau={boon}, consommée={spent}",
              (plan.picks, plan.pick_type, plan.pick_best, plan.pick_consumes)
              == (picks, kind, boon, spent),
              (plan.picks, plan.pick_type, plan.pick_best, plan.pick_consumes))
        check("  aucun point de plateau", spells.choose_target(plan, None)[0] is None)


def test_conditions_are_not_targets():
    """
    UNE CONDITION N'EST NI UNE CIBLE, NI UN EFFET.

    « If an ally died this round, deal 4 to a unit. » — Black Spear
    (01SI034), vu en jeu le 20/08/2026 lancé sur NOS PROPRES UNITÉS.

    Le « an ally » du début décrit ce qui doit s'être produit ; le compter
    comme marqueur en faisait DEUX, et sans restrictions on gardait le
    premier — donc « allié ». Pire, le préambule empêchait `^deal` de
    matcher : l'effet devenait « AUTRE », qui n'est pas classé nuisible,
    et un AUTRE sur notre camp vise notre plus petite unité. Le sort de
    dégâts se retournait contre nous deux fois plutôt qu'une.
    """
    print("\nLes conditions ne sont pas des cibles")

    #   texte                                            effet, ciblage, montant
    cases = {
        "If an ally died this round, deal 4 to a unit.":
            ("DAMAGE", Targeting.ANY_UNIT, 4),
        "If an ally died this round, summon 2 Spiderlings.":
            ("GENERATE", Targeting.NONE, None),
        # La condition peut être en QUEUE de phrase, et elle piégeait tout
        # autant : « Kill the 2 Weakest enemies » est automatique.
        "Kill the 2 Weakest enemies if an ally died this round.":
            ("KILL", Targeting.NONE, None),
        # Elle peut aussi être au MILIEU : le « a follower » de Sky Charge
        # comptait comme une deuxième cible pour un sort à un seul clic.
        "Stun an enemy. If it's a follower, Stun it again at the next Round Start.":
            ("STUN", Targeting.ENEMY, None),
        # Une remise n'est pas un effet non plus, et elle s'intercale
        # exactement au même endroit.
        "If you Behold a Titanic unit, I cost 3 less. Deal 7 to a unit.":
            ("DAMAGE", Targeting.ANY_UNIT, 7),
        "Once you've Equipped an ally this game, I cost 2 less. "
        "Give an ally SpellShield this round.":
            ("BUFF", Targeting.ALLY, None),
    }
    for text, (effect, targeting, amount) in cases.items():
        for restricted in (True, False):
            plan = classify_text(text, restricted=restricted)
            check(f"[{'prudent' if restricted else 'permissif'}] {text[:44]:<44}",
                  (plan.effect, plan.targeting, plan.amount) == (effect, targeting, amount),
                  plan)

    # Et le verdict compte VRAIMENT : un sort de dégâts reconnu comme tel
    # part sur l'adversaire, pas sur nous.
    plan = classify_text("If an ally died this round, deal 4 to a unit.", restricted=False)
    check("Black Spear est bien nuisible", plan.harmful is True, plan)


def test_uncontrollable_interfaces_still_refused():
    """
    Ce qui reste refusé, et la raison : une validation qu'on ne sait pas
    donner, ou deux interfaces qu'on ne sait pas enchaîner.

    « up to N » laisse le nombre à notre discrétion et attend une
    validation dont le bouton n'est pas calibré. Manifest, Invoke et les
    Tellstones, eux, ne sont PLUS ici : leur fenêtre se lit à l'écran
    depuis le 02/09/2026 (voir test_fenetre_de_cartes).
    """
    print("\nInterfaces non pilotables")

    for text in (
        "Discard up to 3 cards to grant allied Rumbles everywhere Impact for the first.",
        # Deux interfaces à la suite : la main PUIS le plateau.
        "Discard a card to deal 4 to an enemy.",
        # Un vrai choix après la désignation, dans une fenêtre illisible.
        "Updraft 1 to either draw 1 or refill your spell mana.",
        "Grant SpellShield or Overwhelm to an ally in hand.",
    ):
        plan = plan_of(text)
        check(f"refusé : {text[:42]:<42}", plan.targeting is Targeting.REFUSED, plan.targeting)
        check("  raison nommée", bool(plan.reason))

    # Et le garde-fou ne doit pas mordre sur les effets AUTOMATIQUES qui
    # parlent de la main : « in hand » apparaît dans 56 d'entre eux.
    for text in (
        "Create a Poro in hand.",
        "Grant allies in hand +1|+0.",
        "Reduce the cost of allies in hand by 1.",
        "Create 2 random Poros and 2 Poro Snax in hand.",
        "Draw 3. Discard any followers drawn.",
        "Your opponent discards the weakest follower from hand.",
    ):
        plan = plan_of(text)
        check(f"automatique : {text[:38]:<38}", plan.targeting is Targeting.NONE, plan.targeting)


def test_choix_de_version():
    """
    « Play me as First Wave or Last Wind » — LA CARTE DU 22/08/2026.

    Les ailes et la vague (04SI004) était lue comme une pose ordinaire :
    aucun marqueur de cible dans « Play me as First Wave or Last Wind »,
    donc aucun clic prévu. Le bot la posait, le jeu ouvrait sa fenêtre de
    choix, et plus rien n'avançait.

    Ce choix-là est PILOTABLE, contrairement à Manifest : les deux
    versions sont nommées dans le texte, donc reconnaissables à l'écran.
    """
    print("\nChoix de version à la pose")

    plan = spells.classify_unit_play("Play: Play me as First Wave or Last Wind.")
    check("un plan est rendu", plan is not None)
    check("classé comme un choix", plan.targeting is Targeting.CHOICE, plan)
    check("les deux versions sont nommées",
          plan.options == ("First Wave", "Last Wind"), plan.options)
    check("un clic est attendu", plan.needs_choice is True, plan)
    check("mais pas sur le plateau", plan.needs_click is False, plan)
    check("ni dans la main", plan.needs_hand_pick is False, plan)
    check("la carte reste jouable", plan.playable is True, plan)
    check("même verdict sans restrictions",
          spells.classify_unit_play(
              "Play: Play me as First Wave or Last Wind.", restricted=False
          ).options == ("First Wave", "Last Wind"))

    # Trois versions se liraient pareil : le motif ne compte pas jusqu'à
    # deux, il découpe sur « or » et sur les virgules.
    trois = classify_text("Play me as A, B or C.")
    check("trois versions lues", trois.options == ("A", "B", "C"), trois.options)

    # Sans alternative, il n'y a pas de fenêtre : chercher une carte à
    # cliquer ferait échouer une pose parfaitement normale.
    seule = classify_text("Play me as First Wave.")
    check("une seule version : pas un choix",
          seule.targeting is not Targeting.CHOICE, seule)

    # L'ancrage en tête distingue le choix OBLIGATOIRE de l'option payante
    # des armes Darkin, qui reste refusée dans les deux modes.
    darkin = classify_text("You may spend 8 mana to play me as Naganeka of Zuretta.")
    check("arme Darkin : pas un choix piloté",
          darkin.targeting is Targeting.REFUSED, darkin)

    # Le prix à la pose d'une des versions : « To play me, kill an ally. »
    check("coût à la pose reconnu",
          spells.has_extra_cost("To play me, kill an ally.") is True)
    check("et pas inventé ailleurs",
          spells.has_extra_cost("When I'm summoned, summon a Prey.") is False)


def test_choix_de_variante():
    """
    « +2|+0 OR +0|+2 » : UNE FENÊTRE S'OUVRE AVANT LE CIBLAGE.

    Choix capital (Momentous Choice, 06IO034), vu en jeu le 22/08/2026 :
    le jeu propose les deux versions du sort, PUIS demande l'allié. Le bot
    cliquait l'allié tout de suite.

    La variante se lit À PART de la cible : le texte demande toujours un
    allié, et le plan doit dire les deux — sinon on choisit entre « la
    fenêtre » et « la cible » alors que le jeu veut les deux, dans cet
    ordre.
    """
    print("\nChoix de variante")

    plan = classify_text("Give an ally +2|+0 or +0|+2 this round.")
    check("les deux gains sont lus",
          plan.variants == ((2, 0), (0, 2)), plan.variants)
    check("une fenêtre est annoncée", plan.needs_variant is True, plan)
    check("et la cible reste l'allié",
          plan.targeting is Targeting.ALLY, plan.targeting)
    check("le sort reste jouable", plan.playable is True, plan)

    # Scaled Snapper (01IO028) : même forme, mais sans cible — le pouvoir
    # se donne à lui-même. La fenêtre s'ouvre quand même.
    corps = spells.classify_unit_play("Play: Grant me +3|+0 or +0|+3.")
    check("une unité aussi peut proposer deux corps",
          corps is not None and corps.needs_variant, corps)
    check("   sans rien à cibler",
          corps.targeting is Targeting.NONE, corps.targeting)

    # Un renfort simple n'ouvre rien : chercher une fenêtre qui ne s'ouvre
    # pas ferait échouer un sort parfaitement normal.
    for text in ("Give an ally +2|+2 this round.",
                 "Grant an ally +1|+0 and Overwhelm."):
        plan = classify_text(text)
        check(f"aucune variante : {text[:34]:<36}", plan.needs_variant is False,
              plan.variants)

    # Un refus ne porte pas de variante : il n'y a rien à cliquer.
    refus = classify_text("Choose one: deal 2 to an enemy, or heal 2.")
    check("un refus n'annonce aucune variante", refus.variants == (), refus)

    # ---- LA FAMILLE EST PLUS LARGE QUE LES CHIFFRES ---------------------
    # 47 cartes de la base proposent deux effets — on le sait par leurs
    # JETONS DU MÊME NOM, un par branche du « ou ». Iula (05MT013) en fait
    # partie, et son choix ne porte que sur un mot-clé : rien à lire dans
    # le texte. Le plan dit donc « une fenêtre est POSSIBLE », et c'est
    # l'écran qui tranchera.
    iula = spells.classify_unit_play(
        "Play: Grant an ally Spellshield or Overwhelm. If you don't, grant it to me."
    )
    check("Iula : une fenêtre est possible", iula.may_offer_variants is True, iula)
    check("   sans certitude chiffrée", iula.needs_variant is False, iula)
    check("   et la cible reste l'allié",
          iula.targeting is Targeting.ALLY, iula.targeting)

    # Le « ou » qui élargit une CIBLE annonce la même possibilité — on ne
    # sait pas les distinguer par le texte, et c'est assumé : le coup
    # d'œil de `resolve_variant_choice` ne coûte qu'une lecture.
    large = classify_text("Deal 3 to a unit or destroy a landmark.")
    check("un « ou » de cible aussi", large.may_offer_variants is True, large)

    # Mais un texte sans « ou » ne fait rien chercher...
    simple = classify_text("Deal 3 to a unit.")
    check("aucun « ou » : rien à chercher", simple.may_offer_variants is False,
          simple)
    # ... et « Play me as A or B » non plus : cette fenêtre-là EST le
    # choix, elle est pilotée ailleurs. Chercher deux fois ferait cliquer
    # deux fois.
    version = spells.classify_unit_play("Play: Play me as First Wave or Last Wind.")
    check("un choix de version n'est pas une variante",
          version.may_offer_variants is False, version)


def test_amount_extracted():
    print("\nMontant lu")

    check("dégâts", plan_of("Deal 4 to an enemy.").amount == 4)
    check("drain", plan_of("Drain 3 from an enemy.").amount == 3)
    check("soin", plan_of("Heal 5 an ally.").amount == 5)
    check("absent si non chiffré", plan_of("Kill a unit.").amount is None)


# ============================================================
# CHOIX DE LA CIBLE
# ============================================================

def build_snapshot():
    """Instantané avec deux unités à nous et deux en face."""
    from test_actions import blocking_snapshot
    return blocking_snapshot(["WALL", "BRUTE"], ["SMALL", "UNIT_A"])


def test_target_selection():
    print("\nChoix de la cible")

    snap = build_snapshot()
    ours = {c.code for c in snap.board}
    theirs = {c.code for c in snap.enemy_attack_row}
    check("plateau de test cohérent", ours == {"WALL", "BRUTE"} and len(theirs) == 2,
          (ours, theirs))

    # Effet néfaste -> chez l'adversaire, même si le sort accepte les deux.
    point, who = spells.choose_target(plan_of("Kill a unit."), snap)
    check("effet néfaste visé sur l'adversaire", "Garde de Fer" in who or "Recrue" in who, who)

    # Effet bénéfique -> chez nous, et sur la plus grosse unité.
    point, who = spells.choose_target(plan_of("Give an ally +1|+1."), snap)
    check("renfort sur notre plus grosse unité", "Brute" in who, who)

    # Dégâts calibrés : on vise ce qu'on peut TUER, pas le plus gros.
    point, who = spells.choose_target(plan_of("Deal 2 to an enemy."), snap)
    check("dégâts sur une cible tuable", "Recrue" in who, who)


def test_ephemeral_is_the_wrong_gift_and_the_right_sacrifice():
    print("\nÉphémère : mauvaise receveuse, bonne sacrifiée")

    def permissif(text):
        return classify_text(text, restricted=False)

    from test_actions import blocking_snapshot
    # Recrue 1/2 permanente contre Spectre Éphémère 4/4, des deux côtés.
    snap = blocking_snapshot(["SMALL", "EPHEMERAL"], ["SMALL", "EPHEMERAL"])
    ours = {c.code: c for c in snap.board}
    theirs = {c.code: c for c in snap.enemy_attack_row}
    check("plateau de test cohérent", len(ours) == 2 and len(theirs) == 2,
          (list(ours), list(theirs)))

    # UN RENFORT NE VA PAS SUR CE QUI DISPARAÎT : l'Éphémère est le plus
    # gros corps du banc, donc `biggest` la désignait — et le bonus
    # partait avec elle en fin de round.
    point, who = spells.choose_target(plan_of("Give an ally +2|+2."), snap)
    check("renfort sur la permanente", point == ours["SMALL"].center, who)

    # Même règle pour un équipement : actions.equipment_plan réutilise
    # exactement ce ciblage.
    point, who = spells.choose_target(
        spells.SpellPlan("EQUIP", Targeting.ALLY), snap)
    check("équipement sur la permanente", point == ours["SMALL"].center, who)

    # « Kill an ally » : l'inverse exact. La mort de l'Éphémère est
    # gratuite, celle de la Recrue non — et « la plus petite » désignait
    # pourtant la Recrue.
    point, who = spells.choose_target(permissif("Kill an ally."), snap)
    check("sacrifice sur l'Éphémère", point == ours["EPHEMERAL"].center, who)

    # Un renfort qu'on est FORCÉ de donner à l'adversaire : sur ce qui va
    # quitter son banc de toute façon.
    point, who = spells.choose_target(permissif("Give an enemy +2|+2."), snap)
    check("cadeau subi sur leur Éphémère", point == theirs["EPHEMERAL"].center, who)

    # Un banc entièrement éphémère reste ciblable : le sort DOIT partir,
    # sinon le client attend un clic qui ne vient jamais.
    seul = blocking_snapshot(["EPHEMERAL"], ["SMALL"])
    point, who = spells.choose_target(plan_of("Give an ally +2|+2."), seul)
    check("faute de mieux, l'Éphémère est ciblée", point is not None, who)


def test_anything_falls_back_to_nexus():
    print("\nCible « anything »")

    snap = build_snapshot()
    # 1 dégât ne tue rien ici : le nexus adverse reste une cible valide,
    # ce qui évite de rester coincé en mode ciblage.
    point, who = spells.choose_target(plan_of("Deal 1 to anything."), snap)
    check("repli sur le nexus adverse", who == "nexus adverse", who)
    check("point de nexus connu", point == snap.enemy_nexus, (point, snap.enemy_nexus))

    # En revanche, si une cible est tuable, on la préfère au nexus.
    point, who = spells.choose_target(plan_of("Deal 2 to anything."), snap)
    check("unité tuable préférée au nexus", "Recrue" in who, who)


def test_no_target_available():
    print("\nAucune cible disponible")

    from test_actions import blocking_snapshot
    snap = blocking_snapshot(["BRUTE"], [])   # aucun ennemi en jeu

    point, why = spells.choose_target(plan_of("Deal 3 to an enemy."), snap)
    # Lancer ce sort laisserait le client à attendre un clic impossible.
    check("aucune cible -> None", point is None, point)
    check("raison explicite", "aucun ennemi" in why, why)


# ============================================================
# SANS RESTRICTIONS
# ============================================================

def test_classement_sans_restrictions():
    """
    `restricted=False` : le classement ne dit plus « je m'abstiens », il
    dit « voilà où cliquer, au mieux de ce que je comprends ». C'est le
    mode utilisé en jeu depuis que actions.CARD_RESTRICTIONS vaut False.
    """
    print("\nClassement sans restrictions")

    def permissif(text):
        return classify_text(text, restricted=False)

    # ---- les refus de PRUDENCE tombent ---------------------------------
    plan = permissif("Kill an ally.")
    check("effet néfaste sur notre camp : accepté",
          plan.playable and plan.targeting is Targeting.ALLY, plan)
    check("   et toujours reconnu comme néfaste", plan.harmful is True, plan)

    check("coût additionnel : accepté",
          permissif("To play, discard 1. Deal 4 to an enemy.").playable)
    check("renfort sur l'adversaire : accepté",
          permissif("Give an enemy +2|+2.").playable)

    # ---- ce qui NE tombe PAS : les incapacités --------------------------
    # Lever les restrictions lève de la PRUDENCE, pas des limites. Deux
    # cibles à cliquer restent deux cibles, et le bot n'en clique qu'une :
    # garder le premier marqueur, c'était laisser le client en attente du
    # second clic — sur Crumble, après avoir sacrifié une de nos unités.
    deux = permissif("Deal 2 to an enemy and stun an ally.")
    check("deux cibles sans coût chez nous : refusé même sans restrictions", not deux.playable, deux)
    check("   et signalé comme une incapacité", deux.impossible is True, deux)
    check("   avec un motif chiffré", "2 cibles" in deux.reason, deux.reason)

    # ---- L'ÉCHANGE, piloté depuis le 05/09/2026 -------------------------
    # « Kill an ally TO kill a unit » : un coût chez nous, puis une
    # récompense. Deux clics de genres différents, mais chacun se choisit
    # seul ; c'était le refus le plus fréquent du journal (Astral Diffusion
    # écartée à chaque tour du combat du 05/09).
    for texte, cout, gain in (
        ("Kill an ally to kill a unit or destroy a landmark.", ("KILL", Targeting.ALLY), ("KILL", Targeting.ANY_UNIT)),
        ("Deal 2 to an ally to Stun an enemy.", ("DAMAGE", Targeting.ALLY), ("STUN", Targeting.ENEMY)),
        ("Deal 3 to an ally to deal 3 to anything.", ("DAMAGE", Targeting.ALLY), ("DAMAGE", Targeting.ANYTHING)),
        ("Recall an ally to give an enemy Vulnerable this round.", ("RECALL", Targeting.ALLY), ("BUFF", Targeting.ENEMY)),
    ):
        for mode, plan in (("prudent", classify_text(texte)), ("permissif", permissif(texte))):
            check(f"échange ({mode}) : {texte[:34]}… jouable", plan.playable and plan.is_trade, plan)
            check("   deux clics", plan.total_targets == 2, plan.total_targets)
            steps = plan.steps()
            check("   coût puis récompense",
                  (steps[0].effect, steps[0].targeting) == cout
                  and (steps[1].effect, steps[1].targeting) == gain,
                  [(st.effect, st.targeting) for st in steps])
    check("le montant du coût est lu",
          permissif("Deal 2 to an ally to Stun an enemy.").steps()[0].amount == 2)
    check("le montant de la récompense aussi",
          permissif("Kill an ally to deal 5 to a unit.").steps()[1].amount == 5)

    # Ce qui RESSEMBLE à un échange sans en être un reste un seul clic ou un refus.
    for texte, quoi in (
        ("Deal 2 to a champion or 4 to a follower.", "un « ou », un seul clic"),
        ("Deal 1 to a follower. If you've Evolved, deal 3 to a unit instead.", "une condition, un seul clic"),
        ("Kill an ally to draw a champion.", "récompense sans clic"),
        ("Deal 1 to an ally to give another ally +2|+2 this round.", "deux alliés à départager"),
    ):
        plan = permissif(texte)
        check(f"pas un échange : {quoi}", not plan.is_trade, plan)

    # UNE FENÊTRE DE CHOIX EST UNE INCAPACITÉ, PAS UNE IMPRUDENCE.
    # Ces deux-là étaient ACCEPTÉES sans restrictions, au motif que le
    # filet d'annulation rattraperait. Il ne rattrape rien : le choix est
    # obligatoire, un clic sur une zone vide ne le referme pas, et la
    # partie reste figée jusqu'à ce que la boucle abandonne — une
    # tentative hebdomadaire perdue. C'est ce qui est arrivé le 22/08/2026
    # avec « Les ailes et la vague », dont le choix est aujourd'hui
    # PILOTÉ (voir test_choix_de_version) ; les fenêtres dont on ne
    # connaît pas le contenu, elles, restent refusées.
    for texte, quoi in (
        ("Choose one: deal 2 to an enemy, or heal 2.", "choix multiple"),
        ("Pick a follower.", "Pick nu"),
        ("You may spend 8 mana to play me as Naganeka of Zuretta.", "arme Darkin"),
    ):
        plan = permissif(texte)
        check(f"{quoi} : refusé même sans restrictions", not plan.playable, plan)
        check(f"   {quoi} : incapacité, pas prudence", plan.impossible is True, plan)
        # Le même verdict dans les deux modes, sinon `play_spell` annulerait
        # après le dépôt dans un mode et pas dans l'autre.
        strict = classify_text(texte)
        check(f"   {quoi} : même motif en mode prudent",
              strict.reason == plan.reason, (strict.reason, plan.reason))

    # Un seul marqueur reste jouable, évidemment.
    check("une seule cible : toujours jouable",
          permissif("Stun an enemy.").playable)

    # ---- mais la LECTURE du ciblage ne change pas ------------------------
    check("texte sans marqueur : aucun clic",
          permissif("Draw 2.").targeting is Targeting.NONE)
    check("marqueur ennemi lu pareil",
          permissif("Deal 3 to an enemy.").targeting is Targeting.ENEMY)
    check("désignation en main lue pareil",
          permissif("Discard 1 to draw 1.").targeting is Targeting.HAND)

    # ---- carte absente de card_sets --------------------------------------
    class Inconnue:
        description = ""
        known = False

    plan = spells.classify_card(Inconnue(), restricted=False)
    check("carte inconnue : plus un refus, une ignorance",
          plan.playable and plan.targeting is Targeting.NONE, plan)
    check("   toujours refusée en mode prudent",
          spells.classify_card(Inconnue()).playable is False)

    # ---- le sacrifié est CHOISI ------------------------------------------
    # C'est la contrepartie de la levée : si un effet néfaste doit viser
    # notre camp, autant que ce soit la plus PETITE unité — Muraille (1|7)
    # plutôt que Brute (5|5).
    snap = build_snapshot()
    _, who = spells.choose_target(permissif("Kill an ally."), snap)
    check("sacrifice sur notre plus petite unité", "Muraille" in who, who)

    _, who = spells.choose_target(permissif("Give an ally +1|+1."), snap)
    check("un vrai renfort vise toujours la plus grosse", "Brute" in who, who)

    _, who = spells.choose_target(permissif("Give an enemy +2|+2."), snap)
    check("renfort subi par l'adversaire : sa plus petite unité",
          "Recrue" in who, who)


# ============================================================
# VITESSE
# ============================================================

class FakeCard:
    def __init__(self, speed):
        self.spell_speed = speed


def test_speed_rules():
    print("\nVitesse des sorts")

    from test_actions import blocking_snapshot
    calm = blocking_snapshot(["BRUTE"], [])
    combat = blocking_snapshot(["BRUTE"], ["UNIT_A"])

    check("Burst hors combat", spells.can_cast_now(FakeCard("Burst"), calm)[0] is True)
    check("Burst pendant le combat", spells.can_cast_now(FakeCard("Burst"), combat)[0] is True)
    check("Slow hors combat", spells.can_cast_now(FakeCard("Slow"), calm)[0] is True)

    allowed, why = spells.can_cast_now(FakeCard("Slow"), combat)
    check("Slow refusé pendant le combat", allowed is False)
    check("   raison nommée", "combat" in why, why)


def test_coverage_runs():
    print("\nRapport de couverture")

    import pathlib
    sets = pathlib.Path("/mnt/user-data/uploads/LOR bot/LoR-Bot/card_sets")
    if not sets.is_dir():
        import lor_api
        sets = lor_api.CARD_SETS_PATH
    if not pathlib.Path(sets).is_dir():
        print("  (card_sets introuvable, test ignoré)")
        return

    # LE MODE EST DEMANDÉ, PAS SUBI (09/11/2026). `coverage_report` lit
    # désormais le mode du bot quand on ne lui dit rien — or cette suite
    # importe `test_actions`, qui pose `actions.CARD_RESTRICTIONS = True`
    # dès son import. Un rapport « par défaut » donnerait donc un chiffre
    # qui dépend de l'ordre des tests. On épingle les DEUX modes.
    report = spells.coverage_report(sets, restricted=True)
    libre = spells.coverage_report(sets, restricted=False)
    total = report["collectible"]
    refused = sum(v for (_, t), v in report["counts"].items() if t == "REFUSED")

    # UN DOSSIER VIDE N'EST PAS UN DOSSIER ABSENT, et les deux se
    # rattrapaient mal : absent, le test s'ignorait EN SILENCE — c'est ce
    # silence qui a laissé le bot jouer sans base de cartes pendant deux
    # séances (26/08/2026, cf. CLAUDE.md) ; vide, `ratio` divisait par
    # zéro et faisait planter toute la suite. Ni l'un ni l'autre : on le
    # dit, une fois, en clair.
    if total == 0:
        check("card_sets contient des cartes "
              "(sinon le bot joue à l'aveugle : aucun ciblage, aucun refus) — "
              "lance python LoR-Bot/code/download_card_sets.py", False, total)
        return

    check("des sorts ont été lus", total > 100, total)
    check("chaque sort est classé", sum(report["counts"].values()) == total,
          (sum(report["counts"].values()), total))
    # Le seuil n'est pas une note : il détecte une régression du
    # classifieur après un changement de motifs.
    ratio = 100 * (total - refused) / total
    check(f"taux de sorts jouables en PRUDENT >= 65 % (mesuré {ratio:.0f} %)",
          ratio >= 65, ratio)

    # ET LE MODE DANS LEQUEL LE BOT JOUE VRAIMENT. Mesuré le 09/11/2026
    # sur les 566 sorts collectionnables : 126 refus en prudent (78 %
    # jouables) contre 51 (91 %) pour le bot — 75 cartes de différence.
    # Le seuil n'est pas une note, c'est un détecteur de régression.
    refus_libre = sum(v for (_, t), v in libre["counts"].items() if t == "REFUSED")
    ratio_libre = 100 * (total - refus_libre) / total
    check(f"taux de sorts jouables pour LE BOT >= 85 % (mesuré {ratio_libre:.0f} %)",
          ratio_libre >= 85, ratio_libre)
    check("lever les restrictions ne referme jamais une carte",
          refus_libre < refused, (refus_libre, refused))
    # « CHAQUE REFUS A UNE RAISON » NE REGARDAIT PAS LES RAISONS
    # (09/11/2026). La ligne disait `all(report["reasons"].values())` : les
    # valeurs de ce dictionnaire sont des COMPTEURS d'occurrences, tous
    # >= 1, donc l'expression valait True quoi qu'il arrive. Mesuré sur
    # deux éprouvettes : un rapport dont les 3 refus sont TOUS sans
    # libellé passait, et un rapport annonçant 9 refus pour 1 seul motif
    # compté passait aussi. Le libellé est la CLÉ, pas la valeur — et le
    # motif est tout ce que `journal.py --ecartees` a pour classer un
    # refus : sans lui, le backlog d'Ewan désigne une ligne vide.
    check("chaque refus a une raison (libellé non vide)",
          refus_tous_libelles(report), report["reasons"])
    # Et ce contrôle-là SAIT échouer : on lui montre les deux rapports
    # que l'ancien laissait passer.
    check("   le contrôle refuse un rapport sans libellé",
          refus_tous_libelles({"counts": {("DAMAGE", "REFUSED"): 3},
                               "reasons": {"": 3}}) is False)
    check("   le contrôle refuse un refus non compté",
          refus_tous_libelles({"counts": {("DAMAGE", "REFUSED"): 9},
                               "reasons": {"un motif": 1}}) is False)


def test_la_commande_repond_dans_le_mode_du_bot():
    """
    `python spells.py explain` ET `coverage` DOIVENT DIRE CE QUE LE BOT
    FAIT (09/11/2026).

    Les deux commandes passaient par le défaut des fonctions
    (`restricted=True`), c'est-à-dire le mode PRUDENT — alors que le bot
    décide depuis le 26/08 avec `actions.CARD_RESTRICTIONS = False`.
    Mesuré sur la base : **150 cartes refusées en prudent que le bot joue
    quand même** (237 refus contre 87 sur 1125 sorts et capacités ; 126
    contre 51 sur les 566 collectionnables). `explain` est la commande
    qu'on interroge pour comprendre une carte : elle répondait sur un
    bot imaginaire.

    Même réparation que `actions.is_dead_weight` la veille : on ne
    redéclare pas le mode ici, on va le LIRE chez celui qui le porte.
    Le mode prudent reste accessible, mais il faut le demander
    (`--prudent`), et la sortie le nomme toujours.
    """
    print('\nLe mode dans lequel la commande répond')

    import contextlib

    def sortie(fonction, *args, **kwargs) -> str:
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            fonction(*args, **kwargs)
        return tampon.getvalue()

    # ---- le mode se LIT chez actions, il ne se redéclare pas ----------
    sauve = sys.modules.get("actions")
    try:
        sys.modules["actions"] = types.SimpleNamespace(CARD_RESTRICTIONS=True)
        check("mode_du_bot suit actions.CARD_RESTRICTIONS = True",
              spells.mode_du_bot() is True)
        sys.modules["actions"] = types.SimpleNamespace(CARD_RESTRICTIONS=False)
        check("   ... et = False", spells.mode_du_bot() is False)
        # `None` dans sys.modules fait lever ImportError à l'import : une
        # commande de diagnostic ne doit pas mourir parce qu'`actions` est
        # injoignable, elle retombe sur le mode du bot par défaut.
        sys.modules["actions"] = None
        check("   actions injoignable : on répond quand même, mode du bot",
              spells.mode_du_bot() is False)
    finally:
        if sauve is None:
            sys.modules.pop("actions", None)
        else:
            sys.modules["actions"] = sauve

    # ⚠ ON N'ASSERTE PAS LA VALEUR VIVE DE `actions.CARD_RESTRICTIONS`
    # ICI : `test_actions.py` la met à True DÈS SON IMPORT (ligne 59)
    # pour décrire le mode prudent, et `test_speed_rules`, juste
    # au-dessus dans cette suite, importe test_actions. La valeur vive ne
    # dit donc rien du mode LIVRÉ — ce qui se teste, c'est le CHEMIN :
    # que `mode_du_bot` aille bien chercher là-bas et nulle part ailleurs.
    import actions as _actions
    check("mode_du_bot rend ce qu'actions porte à l'instant T",
          spells.mode_du_bot() is bool(_actions.CARD_RESTRICTIONS),
          _actions.CARD_RESTRICTIONS)

    # Pour la suite, on fige le mode LIVRÉ (restrictions levées) : les
    # commandes doivent répondre comme le bot tel qu'Ewan le lance.
    sauve = sys.modules.get("actions")
    sys.modules["actions"] = types.SimpleNamespace(CARD_RESTRICTIONS=False)
    try:
        _verifier_les_commandes(sortie)
    finally:
        if sauve is None:
            sys.modules.pop("actions", None)
        else:
            sys.modules["actions"] = sauve


def _verifier_les_commandes(sortie):
    """Le corps du test ci-dessus, avec le mode du bot figé à « levées »."""

    # ---- explain : le verdict change de mode, et le dit ---------------
    # « Recall an ally. » (01IO011) est l'un des 150 : refusé par prudence
    # (« recall dirigé sur notre propre unité »), joué par le bot.
    texte = "Recall an ally."
    check("prudent : refusé", classify_text(texte, restricted=True).playable is False)
    check("bot     : joué", classify_text(texte, restricted=False).playable is True)

    libre = sortie(spells.cmd_explain, texte)
    prudent = sortie(spells.cmd_explain, texte, restricted=True)
    check("explain répond par défaut comme le bot", "Jouable  : oui" in libre, libre)
    check("   et nomme son mode", "restrictions levées" in libre, libre)
    check("explain --prudent refuse la carte", "Jouable  : NON" in prudent, prudent)
    check("   et nomme son mode", "PRUDENT" in prudent, prudent)
    # Le verdict de l'autre mode est RAPPELÉ quand les deux divergent :
    # c'est tout l'intérêt de la commande pour les 150 cartes concernées.
    check("   la divergence est dite", "prudent" in libre.lower(), libre)

    # ---- LA LIGNE QUI RELIE `--prudent` AU CLASSEMENT EST COUVERTE ----
    # Leçon de `test_journal.test_la_commande_applique_vraiment_sa_fenetre`
    # (08/11) : une option peut être déclarée, lue, et n'arriver nulle part.
    argv = sys.argv
    try:
        sys.argv = ["spells.py", "explain", texte]
        par_main = sortie(spells.main)
        sys.argv = ["spells.py", "explain", "--prudent", texte]
        par_main_prudent = sortie(spells.main)
    finally:
        sys.argv = argv
    check("main() explain : mode du bot", "Jouable  : oui" in par_main, par_main)
    check("main() explain --prudent : refus",
          "Jouable  : NON" in par_main_prudent, par_main_prudent)

    # ---- coverage compte les refus DU BOT -----------------------------
    import pathlib
    sets = pathlib.Path("/mnt/user-data/uploads/LOR bot/LoR-Bot/card_sets")
    if not sets.is_dir():
        import lor_api
        sets = lor_api.CARD_SETS_PATH
    if not pathlib.Path(sets).is_dir():
        print("  (card_sets introuvable, le reste du test est ignoré)")
        return

    def refus(rapport) -> int:
        return sum(v for (_, ciblage), v in rapport["counts"].items()
                   if ciblage == "REFUSED")

    defaut = refus(spells.coverage_report(sets))
    libre_n = refus(spells.coverage_report(sets, restricted=False))
    prudent_n = refus(spells.coverage_report(sets, restricted=True))
    check(f"coverage compte les refus du bot ({libre_n}), pas ceux du "
          f"prudent ({prudent_n})", defaut == libre_n and libre_n < prudent_n,
          (defaut, libre_n, prudent_n))
    texte_cov = sortie(spells.cmd_coverage, sets)
    check("   et la sortie nomme son mode",
          "restrictions levées" in texte_cov, texte_cov[:200])
    texte_cov_p = sortie(spells.cmd_coverage, sets, restricted=True)
    check("   --prudent aussi", "PRUDENT" in texte_cov_p, texte_cov_p[:200])


def test_fenetre_de_cartes():
    """
    LES FENÊTRES DE CARTES SONT ANNONCÉES, PLUS REFUSÉES.

    Manifest, Invoke, Predict, « Pick 1 of 3 », « Pick a Moon Weapon to
    create in hand », les Tellstones : le jeu affiche des cartes à choisir,
    et l'API les rapporte (vu en jeu par Ewan sur les fenêtres de
    version). Le plan dit donc QU'UNE fenêtre s'ouvrira — pas ce qu'elle
    contiendra — et `actions.resolve_card_choice` la lit à l'écran.

    Ce que le classement doit garantir, et que le jeu punit sinon :
      - les cartes DE LA FENÊTRE ne sont pas des cibles du plateau
        (« Manifest a follower » ne fait cliquer aucun follower) ;
      - les interfaces du lancement restent lues : cible (« then heal an
        ally »), désignation en main (« Discard 1 to Manifest ») ;
      - le « or » des Tellstones n'annonce pas une fenêtre de versions ;
      - ce qui n'est pas une fenêtre reste dehors : « Pick a follower. »
        nu, les deux versions d'Icathian Myths, un texte entre guillemets.
    """
    print("\nFenêtres de cartes")

    cas = {
        "Manifest a landmark you can afford.":                      "Manifest",
        "Manifest a follower you can afford.":                      "Manifest",
        "Invoke.":                                                  "Invoke",
        "Play: Predict.":                                           "Predict",
        "Pick 1 of 3 champions that started in your deck and draw it.": "Pick 1 of N",
        "Pick one of two new 2 cost spells to create in hand.":     "Pick 1 of N",
        "Pick a Moon Weapon to create in hand.":                    "Pick ... to create in hand",
        "Pick a follower from the top 4 cards in your deck. Draw it.":
            "Pick ... in the top of the deck",
        "Create a Fleeting Flash Freeze, Fury of the North, or Entomb in hand.":
            "Create A, B, or C in hand",
        "Create an Armed Gearhead, Ballistic Bot, or Nyandroid in hand and grant it +1|+1.":
            "Create A, B, or C in hand",
    }
    for texte, fenetre in cas.items():
        for restricted in (True, False):
            plan = classify_text(texte, restricted=restricted)
            mode = "prudent" if restricted else "libre"
            check(f"{texte[:40]:<40} jouable ({mode})", plan.playable, plan)
            check(f"   fenêtre annoncée : {fenetre}", plan.card_window == fenetre, plan.card_window)
            check("   s'ouvrira", plan.opens_card_window is True, plan)
            check("   aucune cible de plateau", plan.needs_click is False, plan.targeting)
            check("   pas de coup d'œil « variante »", plan.may_offer_variants is False, plan)

    # Les interfaces du LANCEMENT restent lues, la fenêtre vient après.
    plan = classify_text("Play: Discard 1 to Manifest a Mecha Yordle.")
    check("Discard 1 to Manifest : désignation en main", plan.needs_hand_pick is True, plan)
    check("   une carte à sacrifier", (plan.picks, plan.pick_best) == (1, False), plan)
    check("   puis la fenêtre", plan.card_window == "Manifest", plan)

    plan = classify_text(
        "Invoke a Celestial card that costs 7 or more, then heal an ally or your Nexus 5.",
        restricted=False,
    )
    check("Starshaping : la cible survit à la coupe",
          plan.targeting is Targeting.ALLY and plan.effect == "HEAL", plan)
    check("   et la fenêtre est annoncée", plan.card_window == "Invoke", plan)

    plan = classify_text("Predict. Give an enemy -2|-0 this round.")
    check("Scrying Sands : la cible ennemie est lue après « Predict. »",
          plan.targeting is Targeting.ENEMY, plan)
    check("   fenêtre Predict", plan.card_window == "Predict", plan)

    # Ce qui N'EST PAS une fenêtre de cartes.
    plan = classify_text("Pick a follower.", restricted=False)
    check("« Pick a follower. » nu : toujours refusé", not plan.playable, plan)
    check("   sans fenêtre", plan.card_window == "", plan)

    plan = classify_text(
        "Create an Icathian Mirage in hand that costs 0 this round, or create a Golden Spatula in hand.",
        restricted=False,
    )
    check("Icathian Myths : deux VERSIONS, pas une fenêtre de cartes", plan.card_window == "", plan)
    check("   donc un coup d'œil « variante »", plan.may_offer_variants is True, plan)

    plan = classify_text(
        'Grant followers in your hand "When you play me, pick 1 of 3 followers with my cost '
        'and transform me into that follower."', restricted=False,
    )
    check("texte entre guillemets : aucune fenêtre à cette pose", plan.card_window == "", plan)

    # La coupe de la clause de fenêtre, seule.
    check("coupe jusqu'à la virgule",
          spells.strip_card_window("Invoke a Celestial card that costs 7 or more, then heal an ally 5.")
          == "heal an ally 5.", spells.strip_card_window(
              "Invoke a Celestial card that costs 7 or more, then heal an ally 5."))
    check("coupe jusqu'au point",
          spells.strip_card_window("Predict. Give an enemy -2|-0 this round.")
          == "Give an enemy -2|-0 this round.", spells.strip_card_window(
              "Predict. Give an enemy -2|-0 this round."))
    check("rien à couper : texte intact",
          spells.strip_card_window("Deal 3 to a unit.") == "Deal 3 to a unit.")


def test_la_fenetre_peut_etre_celle_de_ladversaire():
    """
    « FROM THE ENEMY HAND » : LA FENÊTRE MONTRE SES CARTES, PAS LES NÔTRES.

    05/11/2026, défi 2, 17:12:37 : Yoink! (98SB003) est lancé — « Pick 1
    of 3 non-champion cards from the enemy hand to draw. They draw 1. »
    Le jeu affiche trois cartes À LUI au centre ; l'API les rapporte
    (CardID 1278610636 / 1566250659 / 1153891470, 257x374, LocalPlayer
    FALSE, bande `enemy_attack`). `actions.offered_cards` ne regardait
    que les cartes à NOUS : « Fenêtre de cartes introuvable », clic droit
    sans effet, 184 s devant « SÉLECTIONNER LA CIBLE », combat abandonné
    et tentative hebdomadaire perdue.

    Le texte le disait, et ce n'est pas un cas particulier : sept cartes
    de la base piochent « from the enemy hand/deck » — dont Entrapment
    (05BC223), QUI ÉTAIT EN MAIN pendant le blocage. On lit donc un
    marqueur de CAMP, on ne reconnaît pas des sorts.
    """
    print("\nFenêtre de cartes : le camp des cartes proposées")

    adverses = {
        "Pick 1 of 3 non-champion cards from the enemy hand to draw. They draw 1.":
            "Yoink!",
        "Pick 1 of 2 non-champion cards from the enemy hand and create a copy in your hand.":
            "Swindle",
        "Pick 1 of 2 non-champion cards from the enemy hand or deck and Prank it.":
            "Prank",
        "Play: Pick 1 of 2 non-champion cards from the enemy hand. I Capture it.":
            "Skip",
        "Pick 1 of 3 units or spells from the enemy deck and plant 3 Poison Puffcaps "
        "on all copies of it.": "Entrapment",
    }
    for texte, nom in adverses.items():
        check(f"{nom:<11} : fenêtre annoncée",
              spells.card_window(texte) == "Pick 1 of N", spells.card_window(texte))
        check(f"{nom:<11} : cartes de l'ADVERSAIRE",
              spells.card_window_side(texte) == "theirs", spells.card_window_side(texte))
        plan = classify_text(texte, restricted=False)
        check(f"{nom:<11} : le plan porte le camp",
              plan.opens_card_window and plan.card_window_side == "theirs", plan)

    # Les fenêtres ORDINAIRES ne bougent pas : c'est le comportement de
    # tous les autres sorts, et il ne doit pas changer d'un cheveu.
    for texte in (
        "Manifest a landmark you can afford.",
        "Invoke.",
        "Pick 1 of 3 champions that started in your deck and draw it.",
        "Pick a follower from the top 4 cards in your deck. Draw it.",
    ):
        plan = classify_text(texte, restricted=False)
        check(f"{texte[:34]:<34} : cartes à NOUS",
              plan.card_window_side == "ours", plan.card_window_side)

    # Sans fenêtre, le camp reste à sa valeur par défaut.
    plan = classify_text("Deal 3 to a unit.", restricted=False)
    check("sans fenêtre : camp par défaut", plan.card_window_side == "ours", plan)


def test_damaged_target_condition():
    """
    « A DAMAGED ALLY » N'EST PAS « AN ALLY » : le jeu refuse le clic sur une
    unité intacte et le sort reste en l'air. Vu en jeu le 02/09/2026 avec
    Courage de Braum (Take Heart, 01FR046) : le bot cliquait la plus
    grosse alliée, indemne. Le plan porte la condition, et `choose_target`
    ne retient que les unités dont les PV LUS sont sous les PV imprimés.
    """
    print("\nCondition « damaged » sur la cible")

    for text, side in (
        ("Grant a damaged ally +3|+3.", Targeting.ALLY),
        ("Kill a damaged unit to create a Fleeting Noxian Guillotine in hand.", Targeting.ANY_UNIT),
        ("Deal 2 to a damaged enemy.", Targeting.ENEMY),
    ):
        plan = classify_text(text, restricted=False)
        check(f"condition lue : {text[:32]}", plan.target_condition == "damaged", plan)
        check(f"   camp conservé", plan.targeting is side, plan.targeting)
    plan = classify_text("Grant an ally +3|+3.", restricted=False)
    check("sans adjectif, pas de condition", plan.target_condition == "", plan)
    plan = classify_text("When you heal a damaged ally, grant me +2|+0.", restricted=False)
    check("un déclencheur n'est pas un sort à cible",
          plan.target_condition == "" or plan.targeting is Targeting.NONE, plan)

    class Unit:
        def __init__(self, name, base_health, health_read=None, attack=2):
            self.name, self.base_health, self.health_read = name, base_health, health_read
            self.base_attack = attack
            self.attack_read = None
            self.is_unit, self.center, self.keywords = True, (hash(name) % 1000, 500), ()
            self.local = True
        @property
        def health(self):
            return self.base_health if self.health_read is None else self.health_read
        @property
        def attack(self):
            return self.base_attack
        def has(self, *_):
            return False
        def __str__(self):
            return self.name

    intact = Unit("Intacte", 4, 4)
    non_lue = Unit("Non lue", 5, None)
    blessee = Unit("Blessée", 3, 1)
    check("PV lus sous les PV imprimés : blessée", spells.is_damaged(blessee))
    check("PV lus égaux : intacte", not spells.is_damaged(intact))
    check("PV non lus : réputée intacte (on refuse dans le doute)",
          not spells.is_damaged(non_lue))

    class Snap:
        board = (intact, non_lue, blessee)
        attack_row = ()
        enemy_board = ()
        enemy_attack_row = ()
        enemy_nexus = None

    plan = classify_text("Grant a damaged ally +3|+3.", restricted=False)
    point, desc = spells.choose_target(plan, Snap())
    check("Courage de Braum va sur la blessée, pas sur la plus grosse",
          point == blessee.center, desc)

    class SnapIntact:
        board = (intact, non_lue)
        attack_row = ()
        enemy_board = ()
        enemy_attack_row = ()
        enemy_nexus = None

    point, desc = spells.choose_target(plan, SnapIntact())
    check("aucune blessée : aucune cible, le sort reste en main", point is None, desc)


def test_invisible_target_conditions_are_refused():
    """
    ASTRO-PONG (Paddle Star, 03MT093), vu en jeu le 02/09/2026 : « Deal 5
    to an enemy that attacked this round or is Stunned ». Le bot cliquait
    des ennemis ni étourdis ni attaquants ; le jeu refuse ce clic. Rien
    dans l'état lu ne dit « étourdi » ou « a attaqué ce round » : c'est
    hors de portée, dans les deux modes. Le bonus « If it's already
    Stunned, deal 6 instead » n'est PAS une condition sur la cible.
    """
    print("\nCibles sous condition invisible (étourdie, a attaqué ce round)")

    for text in (
        "Deal 5 to an enemy that attacked this round or is Stunned.",
        "Deal 4 to an enemy that attacked this round or is Stunned.",
        "Deal 4 to a unit if it's damaged or Stunned.",
    ):
        for restricted in (True, False):
            plan = classify_text(text, restricted=restricted)
            check(f"refusé (restrictions {'on' if restricted else 'off'}) : {text[:36]}",
                  not plan.playable and "invisible" in plan.reason, plan)
    plan = classify_text("Stun an enemy. If it's already Stunned, deal 6 to it instead.",
                         restricted=False)
    check("un bonus si déjà étourdi n'est pas une condition", plan.playable
          and plan.targeting is Targeting.ENEMY, plan)
    plan = classify_text("Grant a damaged ally +3|+3.", restricted=False)
    check("« damaged » seul reste jouable : il se lit dans les PV", plan.playable, plan)


def test_un_preambule_ne_doit_plus_masquer_leffet():
    """
    06/11/2026, remarque d'Ewan : « il y a des cartes qui ne sont jouées
    que sur des alliés alors qu'on peut les jouer sur des ennemis aussi ».

    La cause n'était pas le choix du camp mais la lecture de l'EFFET.
    `EFFECT_PATTERNS` est ancré en tête (`^deal`, `^kill`…) et le module
    le dit depuis toujours (cf. le commentaire de `strip_preamble`) :
    tout ce qui précède empêche le motif de correspondre, l'effet tombe
    en « AUTRE », et un AUTRE sur « a unit » part sur un ALLIÉ. Un sort
    de dégâts se retournait donc contre nous.

    `strip_preamble` ne retirait que les subordonnées de condition et
    « I cost N less. ». Mesuré sur la base par le chemin que le bot
    emprunte vraiment (sorts par `classify_card`, unités par
    `classify_unit_play`, qui extrait déjà la clause « Play: ») : il
    restait **onze** cartes dont un préambule masquait un effet hostile
    parfaitement connu — dont Scrapshot (7 dégâts) et Monster Harpoon
    (5 dégâts), tirés sur nos propres unités.

    On ne desserre pas l'ancrage : on l'applique à LA CLAUSE QUI PORTE
    LA CIBLE, après avoir retiré les étiquettes de déclencheur et les
    clauses de coût.
    """
    print("\nUn préambule ne masque plus l'effet (le sort part sur le bon camp)")

    # Chaque paire : le texte nu, puis le même précédé d'une clause. Les
    # deux doivent donner la MÊME famille d'effet.
    paires = [
        ("Deal 7 to a unit.",            "Toss 3. Deal 7 to a unit.",                       "DAMAGE"),
        ("Drain 2 from a unit.",         "Toss 3. Drain 2 from a unit.",                    "DRAIN"),
        ("Deal 5 to a unit.",            "Plunder: I cost 2 less. Deal 5 to a unit.",       "DAMAGE"),
        ("Recall a unit or landmark.",   "Flow: I cost 2 less. Recall a unit or landmark.", "RECALL"),
        ("Deal 4 to a unit.",            "Destroy one of your mana gems to deal 4 to a unit.", "DAMAGE"),
        ("Deal 3 to a unit.",            "When drawn, I cost 2 less this round. Deal 3 to a unit.", "DAMAGE"),
    ]
    for nu, habille, attendu in paires:
        a = classify_text(nu, restricted=False)
        b = classify_text(habille, restricted=False)
        check(f"nu : {nu[:28]} → {attendu}", a.effect == attendu, a.effect)
        check(f"  habillé, même effet : {habille[:40]}", b.effect == attendu, b.effect)
        check("  et donc néfaste, donc sur l'adversaire", b.harmful, b)

    # « To play, spend all your mana. Deal that much to a unit. »
    # (Thermogenic Beam) : des dégâts sans chiffre, comme Banana Blaster.
    plan = classify_text("To play, spend all your mana. Deal that much to a unit.",
                         restricted=False)
    check("Thermogenic Beam : des dégâts, pas un cadeau", plan.effect == "DAMAGE", plan)

    # LA REMISE QUI A PERDU SON POINT. « I cost 2 less if you have a
    # Tristana or if you have played cards from 4+ regions this game.
    # Deal 3 to a unit. » (Buster Shot, 05BC132) : la règle qui retire la
    # condition emporte le point final, et « I cost 2 less » survivait
    # sans ponctuation. Trois dégâts partaient sur une de NOS unités.
    plan = classify_text(
        "I cost 2 less if you have a Tristana or if you have played cards "
        "from 4+ regions this game. Deal 3 to a unit.", restricted=False)
    check("Buster Shot : une remise sans point reste une remise",
          plan.effect == "DAMAGE" and plan.harmful, plan)

    # ON NE DESSERRE PAS L'ANCRAGE POUR AUTANT : un effet cité dans une
    # clause qui n'est pas celle de la cible ne doit pas la colorer.
    plan = classify_text("Grant a unit +2|+2. When it dies, deal 3 to the enemy Nexus.",
                         restricted=False)
    check("un effet d'une AUTRE clause ne déteint pas sur la cible",
          plan.effect == "BUFF", plan)


def test_quatre_verbes_hostiles_qui_manquaient():
    """
    Mesuré le 06/11/2026 sur la base entière : onze cartes portent un
    verbe franchement hostile que le vocabulaire ne connaissait pas, donc
    rangées en « AUTRE » et jouées sur un ALLIÉ.

        Sleep a unit.                      Blooming Bud, Lillia's Blooming Bud
        Capture a unit or landmark.        Claim, Captain Arrika
        Destroy a unit's equipment.        Fracture, Quietus, Heavy Metal,
                                           Explorer's Malfunction,
                                           Silence and Suppress, Puzzling Signposts
        Place a unit or landmark into      Sunk Cost
        its deck.

    Endormir sa propre unité, se capturer soi-même ou détruire son propre
    équipement ne sont pas des maladresses de ciblage : ce sont des
    gestes que rien ne justifie. Ils rejoignent `HARMFUL`.
    """
    print("\nQuatre verbes hostiles qui manquaient au vocabulaire")

    cas = [
        ("Sleep a unit.",                          "SLEEP"),
        ("Capture a unit or landmark.",            "CAPTURE"),
        ("Destroy a unit's equipment.",            "DESEQUIP"),
        ("Destroy a unit's equipment and deal 2 to it.", "DESEQUIP"),
        ("Place a unit or landmark into its deck.", "BANISH"),
    ]
    for texte, attendu in cas:
        plan = classify_text(texte, restricted=False)
        check(f"{texte[:42]} → {attendu}", plan.effect == attendu, plan.effect)
        check("  et c'est néfaste (donc sur l'adversaire)", plan.harmful, plan)

    # GLOOM : UN MALUS DÉGUISÉ EN DON. « Grant a unit Gloom » passait par
    # ^grant -> BUFF -> notre plus grosse unité. Ce n'est pas une
    # supposition : la base ne l'accorde JAMAIS qu'à l'adversaire —
    # « Grant the strongest ENEMY Gloom » (Vex), « Grant ENEMIES 2 Gloom »
    # (Crowstorm, Fiddlesticks), « Grant AN ENEMY 2 Gloom » (Reap) — et
    # Blighted Battleaxe en fait une punition (« If my bearer didn't
    # attack this round, grant it Gloom »). Trouvé par la relecture du
    # diff : aucun des juges ne l'avait vu, c'est la critique de
    # complétude qui l'a sorti.
    for texte in ("Grant a unit Gloom.", "Grant a unit 4 Gloom.",
                  "Play: Grant a unit Gloom."):
        plan = classify_text(texte, restricted=False)
        check("%s -> malus, pas cadeau" % texte[:30],
              plan.effect == "GLOOM" and plan.harmful, plan)
    check("mais un vrai renfort reste un renfort",
          classify_text("Grant an ally +2|+2.", restricted=False).effect == "BUFF")

    # LE CAMP EST LA SEULE CHOSE QUI CHANGE : ces cartes restent jouables
    # et gardent leur ciblage « les deux camps ».
    plan = classify_text("Sleep a unit.", restricted=False)
    check("Blooming Bud reste jouable", plan.playable, plan)
    check("et vise toujours « une unité »", plan.targeting is Targeting.ANY_UNIT, plan)


def test_un_effet_qui_reecrit_les_stats_se_pese_sur_les_deux_camps():
    """
    DÉFENSE PANIQUÉE (Stress Defense, 05BC209) — l'exemple d'Ewan, vu en
    jeu le 06/11/2026 : « Set a unit's stats to 1|6 this round. » lancée
    sur NOTRE Mage aux miroirs 4/7, ramenée à 1/6. Trois points d'attaque
    perdus pour rien.

    Cet effet n'est ni néfaste ni bénéfique : il DÉPEND de qui on vise.
    Sur un gros attaquant adverse, le ramener à 1 d'attaque le neutralise ;
    sur une de nos unités, c'est un cadeau à l'adversaire. Aucune famille
    d'effet ne peut trancher — seule la comparaison le peut.

    On ne crée pas de barème pour ça : on réutilise `keywords.unit_value`,
    l'échelle qui sert déjà à comparer deux échanges, appliquée à l'unité
    AVANT et APRÈS réécriture. Gain sur un allié, perte infligée à un
    ennemi : on vise le plus grand des deux. Et si personne n'y gagne,
    ON NE LANCE PAS — un sort qui ne fait que du mal à son lanceur n'a
    pas de cible valable.
    """
    print("\nUn effet qui réécrit les stats se pèse sur les deux camps")

    plan = classify_text("Set a unit's stats to 1|6 this round.", restricted=False)
    check("les stats réécrites sont lues", plan.stat_override == (1, 6), plan.stat_override)
    check("et la carte reste jouable sur « une unité »",
          plan.playable and plan.targeting is Targeting.ANY_UNIT, plan)
    check("l'effet n'est rangé ni comme néfaste ni comme bénéfique",
          not plan.harmful and plan.effect not in spells.HELPFUL, plan.effect)

    from test_actions import blocking_snapshot

    # 1. NOS UNITÉS N'Y GAGNENT RIEN, UN ENNEMI Y PERD BEAUCOUP.
    #    Muraille 1/7 (valeur 8) et Brute 5/5 (10) chez nous ; en face une
    #    Brute 5/5 (10) et une Recrue 1/2 (3). Réécrites en 1|6, elles
    #    valent toutes 7 : nos deux unités perdent, la Brute adverse perd
    #    3 — c'est le seul gain, et il est pour nous.
    snap = blocking_snapshot(["WALL", "BRUTE"], ["BRUTE", "SMALL"])
    point, qui = spells.choose_target(plan, snap)
    cibles = {c.center: c for c in snap.enemy_attack_row}
    check("la cible est chez l'ADVERSAIRE", point in cibles, qui)
    check("et c'est sa plus grosse unité, celle qui y perd le plus",
          point in cibles and cibles[point].attack == 5, qui)

    # 2. QUAND C'EST NOUS QUI Y GAGNONS, ON VISE CHEZ NOUS. Une Recrue
    #    1/2 (valeur 3) passe à 1|6 (valeur 7) : +4. La même Recrue en
    #    face, elle, y gagnerait autant — ce serait un cadeau.
    snap = blocking_snapshot(["SMALL"], ["SMALL"])
    point, qui = spells.choose_target(plan, snap)
    notres = {c.center for c in snap.board}
    check("la cible est chez NOUS quand c'est nous qui y gagnons",
          point in notres, qui)

    # 3. PERSONNE N'Y GAGNE : ON NE LANCE PAS. Muraille 1/7 (8 -> 7, elle
    #    perd) chez nous, Recrue 1/2 (3 -> 7, elle gagnerait) en face.
    snap = blocking_snapshot(["WALL"], ["SMALL"])
    point, raison = spells.choose_target(plan, snap)
    check("aucune cible quand tout le monde y perd", point is None, raison)
    check("et la raison le dit", "gagne" in raison or "perd" in raison, raison)


def test_un_allie_qui_revient_nest_pas_un_sacrifie():
    """
    Relecture du 06/11/2026 : en rangeant SLEEP et CAPTURE parmi les
    effets néfastes, on a changé — sans le vouloir — le choix de l'allié
    quand c'est NOTRE camp que le texte impose.

    `choose_target` a deux façons de choisir chez nous : `gift_to_ally`
    (la MEILLEURE receveuse, Éphémères exclues) pour un bienfait, et
    `sacrifice` (la moins regrettable, Éphémères EN PREMIER) pour un
    effet néfaste. « Sleep an ally » basculait donc de la première à la
    seconde.

    Or la base de cartes dit que dormir n'est pas mourir :
        Drowsy Dewdrop (09IO045T1) « Countdown 1: Summon an exact copy
            of the sleeping unit inside » — l'unité revient ;
        Lillia niveau 2 (09IO052T1) « When you Sleep another ally,
            immediately wake it up and grant it Spirit » — c'est une
            RÉCOMPENSE, et on la veut sur notre meilleure unité.
    Endormir une Éphémère, qui disparaît en fin de round, gâche la carte
    à coup sûr.

    LA LIGNE DE PARTAGE N'EST PAS « NÉFASTE », C'EST « DÉFINITIF ».
    Tuée, transformée ou renvoyée dans son deck, l'unité ne revient pas :
    on sacrifie la moins regrettable. Endormie, rappelée ou capturée,
    elle revient : l'effet est un MOYEN, et il vaut ce que vaut l'unité
    qu'on y met. Les textes le montrent — « Recall an ally TO summon an
    exact Ephemeral copy in its place » (Go Get It), « Kill an ally to
    deal 3 to the enemy Nexus » (Astral Fox) : même tournure, deux prix
    très différents.
    """
    print("\nUn allié qui REVIENT n'est pas un sacrifié")

    from test_actions import blocking_snapshot
    # Au banc : une Éphémère 4/4 (que `sacrifice` prend en premier, elle
    # ne coûte rien), une Muraille 1/7 et une Brute 5/5 (la meilleure
    # receveuse).
    snap = blocking_snapshot(["EPHEMERAL", "WALL", "BRUTE"], ["SMALL"])
    par_nom = {c.name: c for c in snap.board}
    ephemere, brute = par_nom["Spectre Éphémère"], par_nom["Brute"]

    for texte in ("Sleep an ally.",
                  "Recall an ally to summon an Ephemeral copy of it.",
                  "Capture an ally."):
        plan = classify_text(texte, restricted=False)
        point, qui = spells.choose_target(plan, snap)
        check(f"{texte[:38]} → la meilleure, pas la jetable",
              point == brute.center, qui)
        check("  et surtout pas l'Éphémère", point != ephemere.center, qui)

    # CE QUI EST DÉFINITIF RESTE UN SACRIFICE. « Kill an ally to deal 3 »
    # coûte vraiment l'unité : on donne la moins regrettable, et une
    # Éphémère qui va disparaître en fin de round est exactement ça.
    plan = classify_text("Kill an ally.", restricted=False)
    point, qui = spells.choose_target(plan, snap)
    check("« Kill an ally » sacrifie toujours la moins regrettable",
          point == ephemere.center, qui)


def test_activer_leffet_dun_allie_est_un_bienfait():
    """
    Relecture du 06/11/2026, grief confirmé sur trois cartes : Morning
    Light (03MT082), Leona's Morning Light (03MT054T2) et Unto Dusk
    (04SI011) — « Activate an ally's Daybreak effect », « Activate an
    ally's Nightfall effect ».

    Lire l'effet sur la clause qui porte la cible a rendu ces cartes plus
    HONNÊTES (leur ancien BUFF/GENERATE décrivait une autre clause) mais
    les a fait tomber en « AUTRE » — et en mode `--prudent`, un AUTRE
    visant notre propre camp est refusé. Trois bons sorts n'étaient plus
    lancés du tout.

    Le correctif n'est pas de revenir en arrière : c'est d'apprendre le
    verbe. Déclencher l'effet d'un allié ne lui a jamais nui.
    """
    print("\nActiver l'effet d'un allié est un bienfait, pas un inconnu")

    for texte in ("Activate an ally's Daybreak effect.",
                  "Activate an ally's Nightfall effect, ignoring any targeted portions."):
        plan = classify_text(texte, restricted=False)
        check(f"{texte[:40]} → bienfait",
              plan.effect in spells.HELPFUL and not plan.harmful, plan)
        prudent = classify_text(texte, restricted=True)
        check("  et jouable même en --prudent", prudent.playable, prudent)

    # Les deux cartes réelles, texte complet.
    for texte in ("Give allies +1|+1 this round. Activate an ally's Daybreak effect.",
                  "Draw 1. Nightfall: Activate an ally's Nightfall effect, "
                  "ignoring any targeted portions."):
        check(f"{texte[:34]}… reste jouable en --prudent",
              classify_text(texte, restricted=True).playable, texte)


def test_une_carte_piochee_nest_pas_sur_le_plateau():
    """
    Dette relevée par la relecture du 06/11/2026, et antérieure au
    chantier du camp des sorts : « Draw a champion. » (Entreat, 01FR029)
    comptait « a champion » pour un marqueur de PLATEAU. Le bot prévoyait
    donc un clic sur une unité pour un sort qui pioche — un geste que le
    jeu n'attend pas, et qui laisse le sort en l'air.

    ON PIOCHE DANS LE DECK, JAMAIS SUR LE PLATEAU. Six cartes étaient
    dans ce cas : Entreat, Written in Stars (03MT032), Rite of Calling
    (04SH121T1), Legionary Charge (06NX022T1) et les deux Traveler's
    Call (06RU045, 06RU001T8).

    LE PIÈGE DU FILTRE, mesuré : chercher « in your deck » / « in hand »
    APRÈS le marqueur attrape des clauses qui n'ont rien à voir —
    « Deal 2 to a unit. Create a Ziggs in your deck. » (le marqueur est
    bien sur le plateau), « Recall an ally to create a Flawless Duet in
    hand » (le « in hand » porte sur le Duet). Six faux positifs sur
    douze candidats. Seul le VERBE QUI PRÉCÈDE le marqueur est fiable.
    """
    print("\nUne carte PIOCHÉE n'est pas sur le plateau")

    for texte in ("Draw a champion.",
                  "Draw a champion. Reduce its cost by 1 and grant it +2|+2.",
                  "Draw an ally with 5+ Power.",
                  "Destroy one of your mana gems to draw a Champion.",
                  "Draw a follower, then activate the effects of all boons "
                  "in the top 3 cards of your deck."):
        plan = classify_text(texte, restricted=False)
        check("%s -> aucun clic de plateau" % texte[:40],
              plan.targeting is Targeting.NONE, plan)
        check("  et la carte reste jouable", plan.playable, plan)

    # LES FAUX POSITIFS QU'IL NE FAUT PAS ATTRAPER. Dans ces trois-là le
    # marqueur est bel et bien sur le plateau, et la mention du deck ou
    # de la main porte sur une AUTRE carte.
    garde = [
        ("Deal 2 to a unit. Create a Ziggs in your deck.", Targeting.ANY_UNIT),
        ("Recall an ally to create a Flawless Duet in hand.", Targeting.ALLY),
        ("Place a unit or landmark into its deck.", Targeting.ANY_UNIT),
        ("Sleep a unit. Create a Lillia in your deck.", Targeting.ANY_UNIT),
    ]
    for texte, attendu in garde:
        plan = classify_text(texte, restricted=False)
        check("%s -> %s" % (texte[:44], attendu.name),
              plan.targeting is attendu, plan)


def test_une_cible_qui_attaque_se_lit_dans_la_rangee():
    """
    TEMPÊTE D'ACIER (Steel Tempest, 01IO046), remarquée par Ewan le
    06/11/2026 : « le bot n'a pas su utiliser ce sort sur une carte
    ennemie qui attaque ».

    Son texte est « Stun an ATTACKING enemy. » — et il était classé
    exactement comme « Stun an enemy. » : STUN / ENEMY / condition vide.
    Le bot visait donc le plus gros ou le plus tuable des ennemis, où
    qu'il soit. Si celui-là n'attaquait pas, le jeu REFUSAIT le clic et
    le sort restait en l'air.

    CE N'EST PAS UNE « CONDITION INVISIBLE ». CLAUDE.md refuse à juste
    titre « that attacked this round » et « is Stunned » : rien dans
    l'état lu ne les dit. Mais « QUI ATTAQUE » se lit directement —
    c'est `enemy_attack_row`, une zone que l'API rapporte à chaque
    lecture. Même famille que `target_condition = "damaged"`, qui filtre
    déjà sur les PV lus à l'écran.

    Quatre textes de la base : les deux Steel Tempest (le sort et le
    jeton de Yasuo) et les deux Playful Trickster, qui visent un ALLIÉ
    qui attaque (« Remove an attacking ally from combat to Rally »).
    """
    print("\nUne cible « qui attaque » se lit dans la rangée d'attaque")

    plan = classify_text("Stun an attacking enemy.", restricted=False)
    check("la condition est lue", plan.target_condition == "attacking",
          plan.target_condition)
    check("   le reste ne bouge pas (STUN sur ennemi, jouable)",
          plan.effect == "STUN" and plan.targeting is Targeting.ENEMY
          and plan.playable, plan)
    nu = classify_text("Stun an enemy.", restricted=False)
    check("   et « an enemy » tout court n'a toujours pas de condition",
          nu.target_condition == "", nu.target_condition)

    from test_actions import _challenge_snapshot

    # LE PIÈGE EN UNE IMAGE : la grosse unité adverse est AU BANC, la
    # petite ATTAQUE. Le comportement naïf vise la plus grosse — et se
    # fait refuser le clic.
    snap = _challenge_snapshot(ours=[("WALL", 301, 500)],
                               theirs=[("BRUTE", 401, 700)],
                               enemy_blockers=[("SMALL", 402, 900)])
    au_banc = {c.center for c in snap.enemy_board}
    qui_attaque = {c.center for c in snap.enemy_attack_row}
    check("le plateau de test est bien dans les deux zones",
          len(au_banc) == 1 and len(qui_attaque) == 1, (au_banc, qui_attaque))

    point, qui = spells.choose_target(plan, snap)
    check("la cible est celle QUI ATTAQUE", point in qui_attaque, qui)
    check("   et surtout pas la grosse restée au banc",
          point not in au_banc, qui)

    # Sans condition, le sort garde son ancien comportement : la plus
    # grosse, où qu'elle soit.
    point, qui = spells.choose_target(nu, snap)
    check("« Stun an enemy » vise toujours la plus grosse", point in au_banc, qui)

    # PERSONNE N'ATTAQUE : on ne lance pas. Un clic refusé laisse le sort
    # en l'air, ce qui coûte bien plus cher que de le garder en main.
    calme = _challenge_snapshot(ours=[("WALL", 301, 500)],
                                theirs=[("BRUTE", 401, 700)])
    point, raison = spells.choose_target(plan, calme)
    check("aucun attaquant en face : aucune cible", point is None, raison)
    check("   et la raison le dit", "attaque" in raison.lower(), raison)


def test_une_cible_marquee_est_hors_de_portee():
    """
    BEAST'S FRENZY (98SB047), mesurée en partie le 11/11/2026 : **15
    lancements, 10 blocages de pile, 5 « restée en main »** sur trois
    combats — ~80 s, et une carte forte (souvent à coût 0) jamais jouée.

    Son texte est « Summon a The Beast Challenging a MARKED enemy. », et
    l'adjectif `marked` ne RESTREIGNAIT pas le marqueur : il le faisait
    DISPARAÎTRE. Aucun motif de `SINGULAR_TARGETS` ne lit « a marked
    enemy » — l'inverse exact de la règle du 26/08 (« un adjectif devant
    *ally* restreint la cible, il ne la supprime pas »). Résultat :
    `Targeting.NONE`, donc aucun clic prévu, donc la carte était posée et
    le jeu attendait une cible que personne ne lui donnait.

    ON NE RÉTABLIT PAS LE MARQUEUR, et c'est tout le sujet : le marquage
    est un mot-clé ACCORDÉ EN JEU, donc INVISIBLE — l'API ne rend qu'un
    CardCode, et Dance of Arrows (98SB040) marque un ennemi AU HASARD.
    Cliquer un ennemi non marqué ferait refuser le clic par le jeu : on
    aurait échangé un blocage contre un autre. C'est la famille des
    cibles sous condition invisible (« est étourdi », « a attaqué ce
    round », 02/09/2026), donc un refus HORS DE PORTÉE, qui vaut dans
    LES DEUX MODES.

    À NE PAS CONFONDRE AVEC « AN ATTACKING ENEMY », ouvert le 06/11 :
    celui-là se LIT (`attack_row` / `enemy_attack_row`). C'est la
    distinction « lisible » / « invisible » qui tranche, pas la forme de
    la phrase.
    """
    print("\nUne cible MARQUÉE est hors de portée (le marquage ne se lit pas)")

    marquee = "Summon a The Beast Challenging a marked enemy."
    for restricted in (True, False):
        mode = "prudent" if restricted else "par défaut"
        plan = classify_text(marquee, restricted=restricted)
        check(f"Beast's Frenzy refusée en mode {mode}", not plan.playable, plan)
        check(f"   le motif nomme la condition invisible ({mode})",
              "invisible" in plan.reason and "marqu" in plan.reason, plan.reason)
        check(f"   et le refus est HORS DE PORTÉE, pas de la prudence ({mode})",
              plan.impossible is True, plan)
        check(f"   aucun clic prévu, donc aucune pose à annuler ({mode})",
              plan.targeting is Targeting.REFUSED, plan)

    # LES TROIS AUTRES « CHALLENGING AN ENEMY » DE LA FAMILLE 98SB NE
    # BOUGENT PAS : Unleashed Frenzy (98SB021) et les deux Spirit Rush
    # (98SB012, 98SB012T1). Seule Beast's Frenzy porte « marked ».
    for texte in (
        "Summon a The Beast Challenging an enemy.",
        "Summon a 3|3 Fox-Fire Challenging an enemy.",
    ):
        for restricted in (True, False):
            plan = classify_text(texte, restricted=restricted)
            check(f"« Challenging an enemy » reste jouable : {texte[:34]}",
                  plan.playable and plan.targeting is Targeting.ENEMY, plan)

    # GARDE-FOU N°1 — « ALL MARKED » N'EST PAS UN MARQUEUR DE CIBLE.
    # Dance of Arrows FONCTIONNE aujourd'hui (vue tourner, résolue
    # plusieurs fois dans la même session) : c'est le jeu qui marque, et
    # les dégâts tombent tout seuls sur TOUS les marqués. La refuser
    # casserait une carte qui marche.
    for texte, attendu in (
        ("Mark a random enemy, or spend 4 mana to deal 3 to all marked enemies.",
         "AUTRE"),
        ("Deal 3 to all marked enemies.", "DAMAGE"),
        ("Deal 3 to all marked enemies. Create a The Taker in your deck.",
         "DAMAGE"),
    ):
        for restricted in (True, False):
            plan = classify_text(texte, restricted=restricted)
            check(f"« all marked » reste jouable sans clic : {texte[:38]}",
                  plan.playable and plan.effect == attendu
                  and plan.targeting is Targeting.NONE, plan)

    # GARDE-FOU N°2 — LE VERBE « MARK » N'EST PAS L'ADJECTIF « MARKED ».
    # Patient Beast (98SB046) dit « Play: Mark an enemy. » : c'est NOUS
    # qui marquons, la cible est un ennemi ordinaire, et le clic est
    # parfaitement légitime.
    for restricted in (True, False):
        plan = classify_text("Mark an enemy.", restricted=restricted)
        check("« Mark an enemy » garde sa cible ennemie",
              plan.playable and plan.targeting is Targeting.ENEMY, plan)
    plan = spells.classify_unit_play(
        "Play: Mark an enemy.\nRound End: I strike all marked enemies.",
        restricted=False)
    check("   et le « Play: » de Patient Beast aussi",
          plan is not None and plan.playable
          and plan.targeting is Targeting.ENEMY, plan)

    # GARDE-FOU N°3 — un plateau DÉCRIT comme marqué n'est pas une cible.
    plan = spells.classify_unit_play(
        "I can't take damage or die. Enemies are marked.", restricted=False)
    check("« Enemies are marked » n'est pas un « Play: » à cibler",
          plan is None, plan)

    # ET LA VRAIE CARTE DE LA BASE, par le chemin que le bot emprunte
    # (`classify_card` sur le dict de card_sets, donc `descriptionRaw`).
    import pathlib
    import lor_api
    if pathlib.Path(lor_api.CARD_SETS_PATH).is_dir():
        db = lor_api.load_card_db()
        carte = db.get("98SB047")
        if carte is None:
            check("98SB047 Beast's Frenzy est dans la base", False, "absente")
        else:
            for restricted in (True, False):
                plan = spells.classify_card(carte, restricted=restricted)
                check("la VRAIE Beast's Frenzy est refusée "
                      f"({'prudent' if restricted else 'par défaut'})",
                      not plan.playable and plan.impossible is True, plan)
            # Et aucune autre carte de la base ne doit basculer : les
            # sept textes qui contiennent « marked » sont recensés, une
            # seule porte l'adjectif sur un marqueur.
            import re
            rx = re.compile(r"\bmarked\b", re.I)
            porteuses = [code for code, c in db.items()
                         if rx.search(c.get("descriptionRaw") or "")]
            check("sept cartes de la base écrivent « marked »",
                  len(porteuses) == 7, sorted(porteuses))
            barrees = [code for code in porteuses
                       if spells.MARKED_TARGET_RX.search(
                           db[code].get("descriptionRaw") or "")]
            check("   une seule porte l'adjectif sur un marqueur de cible",
                  barrees == ["98SB047"], barrees)
    else:
        print("  (card_sets introuvable, contrôle sur la base ignoré)")


def test_un_suivant_nest_pas_un_champion():
    """
    « CHARM AN ENEMY FOLLOWER » (Beckoning Gaze, 98SB015) — relevé dans
    `logs/challenges_20261105_204758.log`, deux fois d'affilée :

        Lancement de Beckoning Gaze (AUTRE sur ennemi).
        Ciblage : Karma (5) 4/3 en (645, 180)
        Beckoning Gaze toujours sur la pile après validation.

    Karma est un CHAMPION. Le mot « follower » était lu pour désigner le
    CAMP et sa restriction jetée : le plan sortait « AUTRE sur ennemi »,
    exactement comme « Charm an enemy », et le bot visait le plus gros —
    donc le champion. Le jeu refusait le clic, le sort restait en l'air.

    C'EST LA MÊME LIGNE DE PARTAGE QUE « ATTACKING » (06/11/2026) :
    « a attaqué ce round » ne se lit nulle part, mais « est un
    champion » se lit — `supertype` vient de card_sets, et
    `BoardCard.is_champion` le dit depuis le 03/09.

    ET LA CONDITION SE LIT SUR LE MARQUEUR, PAS SUR LA PHRASE. Sans ça,
    « Kill an ally to draw a Champion » (Rite of Calling, 04SH121T2)
    filtrerait NOS alliés sur les champions, alors que le champion y est
    PIOCHÉ — le marqueur, lui, dit « an ally ».
    """
    print("\nUn suivant n'est pas un champion")

    plan = classify_text("Charm an enemy follower.", restricted=False)
    check("la condition est lue", plan.target_condition == "follower",
          plan.target_condition)
    check("   le camp ne bouge pas (sur ennemi, jouable)",
          plan.targeting is Targeting.ENEMY and plan.playable, plan)

    degats = classify_text("Deal 3 to a follower.", restricted=False)
    check("« Deal 3 to a follower » (Calibrum) porte la même condition",
          degats.target_condition == "follower" and degats.amount == 3, degats)

    nu = classify_text("Charm an enemy.", restricted=False)
    check("« an enemy » tout court n'a toujours pas de condition",
          nu.target_condition == "", nu.target_condition)

    champ = classify_text(
        'Give an allied Champion "The next time I\'d die this round, '
        'fully heal me and grant me +3|+3 instead".', restricted=False)
    check("le symétrique se lit aussi (Chronoshift : allié CHAMPION)",
          champ.target_condition == "champion"
          and champ.targeting is Targeting.ALLY, champ)

    # --- LES FAUX POSITIFS, CHERCHÉS AVANT DE LIVRER ------------------
    pioche = classify_text("Kill an ally to draw a Champion.", restricted=False)
    check("un champion PIOCHÉ ne conditionne pas le clic sur l'allié",
          pioche.target_condition == "", pioche)

    # « Deal 2 to a champion or 4 to a follower » (Weight of Judgment,
    # 04SH004) : UN clic, et les DEUX sont acceptés. Une condition par
    # marqueur, deux marqueurs qui ne disent pas la même chose : on n'en
    # retient aucune, c'est la règle « une condition à la fois ».
    deux = classify_text("Deal 2 to a champion or 4 to a follower.",
                         restricted=False)
    check("une alternative champion/suivant ne restreint rien",
          deux.target_condition == "", deux)

    # « Stun an enemy. If it's a follower, Stun it again. » (Gravitum,
    # 03MT217T12) : « follower » y est un BONUS, pas une restriction. La
    # carte est refusée pour deux cibles — ce qu'on vérifie, c'est
    # qu'elle n'en ressort pas en « ennemi suivant seulement ».
    bonus = classify_text(
        "Stun an enemy. If it's a follower, Stun it again at the next "
        "Round Start.", restricted=False)
    check("« if it's a follower » ne restreint pas la cible",
          bonus.target_condition != "follower", bonus)

    from test_actions import _challenge_snapshot

    # LE PIÈGE EN UNE IMAGE : le champion adverse est le plus gros, donc
    # celui que le comportement naïf désigne — et celui que le jeu
    # refuse.
    snap = _challenge_snapshot(ours=[("WALL", 301, 500)],
                               theirs=[("CHAMPI", 401, 700), ("BRUTE", 402, 900)])
    champions = {c.center for c in snap.enemy_board if c.is_champion}
    suivants = {c.center for c in snap.enemy_board if not c.is_champion}
    check("le plateau de test a bien un champion et un suivant",
          len(champions) == 1 and len(suivants) == 1, (champions, suivants))

    point, qui = spells.choose_target(plan, snap)
    check("la cible est le SUIVANT", point in suivants, qui)
    check("   et surtout pas le champion", point not in champions, qui)

    point, qui = spells.choose_target(nu, snap)
    check("sans condition, le plus gros reste visé (le champion)",
          point in champions, qui)

    # QUE DES CHAMPIONS EN FACE : on ne lance pas. Un clic refusé laisse
    # le sort en l'air (23 s mesurées), le garder en main ne coûte rien.
    que_des_champions = _challenge_snapshot(ours=[("WALL", 301, 500)],
                                            theirs=[("CHAMPI", 401, 700)])
    point, raison = spells.choose_target(plan, que_des_champions)
    check("aucun suivant en face : aucune cible", point is None, raison)
    check("   et la raison le dit", "suivant" in raison.lower(), raison)


def test_un_nombre_libre_de_cibles_se_valide_a_l_orbe():
    """
    VLADIMIR (01NX006) : « Play: Deal 1 to ANY NUMBER OF allies to deal
    that much to an enemy. »

    CE TEST DISAIT LE CONTRAIRE JUSQU'AU 10/11/2026, et c'était la bonne
    réponse avec ce qu'on savait alors. Le 06/11, `classify_card` ne
    comptait qu'un marqueur — « an enemy » — le bot posait Vladimir,
    cliquait un ENNEMI, et la partie figeait : 12 lectures sans rien qui
    bouge, ~50 s perdues en pleine phase ATTACKING, deux fois dans le
    même combat, puis annulation et champion revenu EN MAIN. On a donc
    refusé la carte « hors de portée », au motif que le jeu attendait
    « des clics en nombre libre PLUS une validation, et ce bouton n'est
    pas calibré ».

    LE BOUTON ÉTAIT CALIBRÉ DEPUIS LE DÉBUT. Ewan, 10/11/2026 : « on
    clique sur l'ennemi et on clique sur le bouton bleu à droite de la
    page ». Ce bouton bleu est l'ORBE DE TOUR — celle que `read_turn_
    button` lit et que `actions.TURN_BUTTON_RATIO` clique déjà pour finir
    un tour ou valider un sort. Les deux captures que le bot avait
    gardées de ses propres blocages le montrent sans ambiguïté
    (`screenshots/bloque_ATTACKING_20261106_105937.png` et
    `..._111227.png`) : Vladimir au centre, l'invite « Infligez 1 pt(s)
    de dégâts », nos alliés surlignés, et à droite à mi-hauteur l'orbe
    BLEUE portant « PASSER ».

    LE COMPTE DES MARQUEURS NE CHANGE PAS : « any number of allies » n'en
    est pas un (aucun nombre écrit, donc pas de pluriel COMPTÉ), et il
    reste « an enemy ». Ce qui s'ajoute n'est pas une cible, c'est un
    GESTE : `SpellPlan.free_designation`.

    ZÉRO ALLIÉ, ET C'EST VOULU. Se blesser pour frapper plus fort est une
    décision de jeu ; poser le champion est déjà tout le gain.

    Trois cartes, toute la famille Vladimir : le champion, son niveau 2
    (01NX006T1) et sa compétence Crimson Pact (01NX006T2).
    """
    print("\nUn nombre LIBRE de cibles se valide à l'orbe (Vladimir)")

    textes = (
        "Play: Deal 1 to any number of allies to deal that much to an enemy.",
        "Deal 1 to any number of allies to deal that much to an enemy.",
    )
    for text in textes:
        for restricted in (True, False):
            plan = classify_text(text, restricted=restricted)
            mode = "on" if restricted else "off"
            check(f"jouable (restrictions {mode}) : {text[:34]}", plan.playable, plan)
            check("  un seul clic, sur un ENNEMI",
                  plan.targeting is Targeting.ENEMY and plan.total_targets == 1, plan)
            check("  et une validation est due derrière",
                  plan.free_designation is True, plan)
            check("  le plan le DIT (c'est ce qu'on lit dans les logs)",
                  "validation" in str(plan), str(plan))

    # AUCUN ALLIÉ N'EST DÉSIGNÉ : le plan ne demande qu'un clic, et les
    # alliés surlignés n'en sont pas. Si « any number of allies » comptait
    # pour une cible, `total_targets` vaudrait 2 et le sort retomberait
    # dans le refus générique « le bot ne clique qu'une fois ».
    plan = classify_text(textes[0], restricted=False)
    check("aucun allié dans le compte des cibles", plan.total_targets == 1, plan)
    check("pas de désignation en main non plus", not plan.needs_hand_pick, plan)

    # UN REFUS NE PORTE JAMAIS CE DRAPEAU : un plan injouable ne clique
    # rien, donc il n'a rien à valider. « Choose one » reste hors de
    # portée pour le motif qui le barre vraiment, sans que le drapeau
    # vienne suggérer un geste par-dessus.
    refuse = classify_text("Choose one: deal 2 to any number of allies, or heal 2.",
                           restricted=False)
    check("un refus ne porte pas la validation",
          not refuse.playable and refuse.free_designation is False, refuse)

    # ET « up to N » RESTE REFUSÉ. Ce n'est pas le même manque : ses clics
    # portent sur la MAIN, une interface dont on ne lit pas les cartes au
    # moment du choix. Confondre les deux familles parce qu'elles
    # demandent toutes deux « une validation » rouvrirait un blocage.
    for texte in ("Discard up to 3 cards to draw that many.",
                  "Updraft up to 2."):
        for restreint in (True, False):
            plan = classify_text(texte, restricted=restreint)
            check(f"« up to N » toujours hors de portée : {texte[:28]}",
                  plan.targeting is Targeting.REFUSED and plan.impossible is True, plan)

    # LE PLURIEL COMPTÉ RESTE CE QU'IL EST : le texte dit le nombre, donc
    # pas de validation à donner.
    plan = classify_text("Frostbite 2 enemies. ", restricted=False)
    check("« 2 enemies » : deux clics, aucune validation",
          plan.playable and plan.total_targets == 2 and not plan.free_designation, plan)

    # ET LA BASE RÉELLE : exactement trois cartes, toutes marquées.
    import lor_api
    db = lor_api.load_card_db()
    if db:
        touchees = {}
        for code, carte in db.items():
            # `descriptionRaw` est ce que `game_state` met dans
            # `BoardCard.description` : le texte SANS balises, donc le
            # seul où « Play: » se lise comme le bot le lit.
            texte = carte.get("descriptionRaw") or ""
            if "any number of" in texte.lower():
                plan = (spells.classify_unit_play(texte, restricted=False)
                        if (carte.get("type") or "").lower() == "unit"
                        else classify_text(texte, restricted=False))
                touchees[code] = plan
        check("trois cartes dans la base, la famille Vladimir",
              set(touchees) == {"01NX006", "01NX006T1", "01NX006T2"}, sorted(touchees))
        check("   toutes jouables et toutes à valider",
              all(p is not None and p.playable and p.free_designation
                  for p in touchees.values()),
              {c: str(p) for c, p in touchees.items()})
        check("   et toutes sur un seul clic, un ENNEMI",
              all(p.targeting is Targeting.ENEMY and p.total_targets == 1
                  for p in touchees.values()),
              {c: str(p) for c, p in touchees.items()})


def test_counted_plural_targets():
    """
    VENTS MORDANTS (Harsh Winds, 01FR042, « Frostbite 2 enemies »), vu en
    jeu le 02/09/2026 : aucun marqueur singulier, donc « aucune cible »,
    sort posé sans clic, jeu en attente. Un pluriel COMPTÉ vaut N clics du
    même camp — et le jeu accepte MOINS de cibles s'il n'y en a pas assez :
    un seul ennemi en face, le sort part sur lui.
    """
    print("\nPluriels comptés : « Frostbite 2 enemies »")

    plan = classify_text("Frostbite 2 enemies. ", restricted=False)
    check("deux ennemis à cliquer", plan.targeting is Targeting.ENEMY
          and plan.total_targets == 2, plan)
    check("cibles souples (le jeu se contente de ce qu'il y a)",
          plan.flexible_targets is True, plan)
    plan = classify_text("Deal 1 to 3 enemies.", restricted=False)
    check("trois ennemis, dégâts lus", plan.total_targets == 3 and plan.amount == 1, plan)
    plan = classify_text("Give two allies +1|+0 this round.", restricted=False)
    check("« two allies » : deux alliés", plan.targeting is Targeting.ALLY
          and plan.total_targets == 2, plan)
    for text in ("Deal 3 to all enemies.", "Deal 1 to up to 3 enemies.",
                 "Frostbite all enemies.", "Grant 2 allies in hand +2|+2.",
                 "Grant the top 3 units in your deck +1|+1."):
        plan = classify_text(text, restricted=False)
        check(f"pas de cible : {text[:28]}", plan.targeting is Targeting.NONE, plan)
    plan = classify_text("Deal 2 to an enemy and Stun another.", restricted=False)
    check("« an enemy ... another » reste STRICT", plan.total_targets == 2
          and plan.flexible_targets is False, plan)
    plan = classify_text("Frostbite an enemy and all other enemies with 3 or less Health.",
                         restricted=False)
    check("« an enemy and all other enemies » : un seul clic", plan.total_targets == 1, plan)


def test_une_transformation_nomme_un_jeton_pas_une_seconde_cible():
    """
    MINIMORPH (05BC001), 08/11/2026. Le texte « Transform a unit into a
    3|3 Mini-Minitee and Silence it. » était refusé, motif « deux
    cibles » — alors qu'il n'y a qu'UN clic : le Mini-Minitee est ce que
    l'unité DEVIENT, pas une seconde cible à désigner.

    LE MOTIF DÉSIGNAIT LE COUPABLE, MAIS CE N'ÉTAIT PAS LE COMPTEUR.
    Mesuré sur la base entière : `_scan_targets` ne compte JAMAIS un NOM
    DE JETON pour une cible — sur les 23 textes qui contiennent « into
    a/an », ni Mini-Minitee, ni Squirrel, ni Alpha Wildclaw, ni aucun des
    neuf jetons d'Ambush n'apparaît dans les marqueurs. Un seul marqueur
    suit directement un « into », et ce n'est pas un jeton : le « another
    follower » de Curious Changelings (06BC042), dans une clause de
    DÉCLENCHEUR — une unité sans « Play: », que `classify_unit_play`
    laisse tomber. (Correction du 08/11 : cette phrase nommait d'abord
    Hextech Transmogulator, dont le second marqueur arrive bien plus loin,
    après « into an exact copy of ». Il reste le contre-exemple de ce
    test, mais pour ses DEUX clics, pas pour la place de son marqueur.)
    Le refus venait d'une ligne de `REFUSALS` qui barrait le mot
    « transform » lui-même, avec ce motif pour toute justification.

    CE QUE ÇA COÛTAIT, et c'est le piège du 06/11 à l'identique :
    `actions.is_dead_weight` appelle `classify_card(card)` SANS argument,
    donc `restricted=True` MÊME en mode par défaut. Ces cartes étaient
    donc du « fardeau pur » — premières défaussées au mulligan
    (`sacrifice_rank`), dernières renforcées (`boost_rank`), dernières
    choisies dans une fenêtre de cartes (`card_pick_rank`). Minimorph,
    Whimsy!, et jusqu'à Go Hard — un simple « Drain 1 from a unit » dont
    le texte mentionne « transform » dans une clause qui ne parle que de
    ses propres copies.
    """
    print("\nUne transformation nomme un JETON, pas une seconde cible")

    # LE JETON N'EST PAS UNE CIBLE : un seul marqueur, un seul clic.
    for texte, attendu in (
        ("Transform a unit into a 3|3 Mini-Minitee and Silence it.", Targeting.ANY_UNIT),
        ("Transform a follower into a 1|1 Squirrel and Silence it this round.",
         Targeting.ANY_UNIT),
        ("Transform a follower into a 1|1 Squirrel and Silence it this round. "
         "Create a Lulu in your deck.", Targeting.ANY_UNIT),
    ):
        for restreint in (True, False):
            plan = classify_text(texte, restricted=restreint)
            check("%s -> %s (restreint=%s)" % (texte[:34], attendu.name, restreint),
                  plan.targeting is attendu and plan.effect == "TRANSFORM", plan)
            check("   et la carte est jouable", plan.playable, plan)

    # Le marqueur reste UNIQUE : c'est le compteur lui-même qu'on verrouille.
    cibles, _spans = spells._scan_targets(
        "Transform a unit into a 3|3 Mini-Minitee and Silence it.")
    check("« into a 3|3 Mini-Minitee » n'est pas un marqueur",
          cibles == ["ANY_UNIT"], cibles)

    # LE MOT « TRANSFORM » LOIN DE TOUTE CIBLE NE DOIT RIEN BARRER.
    # Go Hard (03SI016) est un Drain ; sa clause de transformation ne
    # parle que de ses propres copies, ailleurs dans le deck.
    plan = classify_text(
        "Drain 1 from a unit.\nCreate 2 copies of Go Hard in your deck. Every third "
        "time this happens, transform all copies of me everywhere into Pack Your Bags.")
    check("Go Hard : un DRAIN sur une unité, pas un refus",
          plan.targeting is Targeting.ANY_UNIT and plan.effect == "DRAIN"
          and plan.playable, plan)

    # Les jetons d'Ambush ne désignent rien : ils se posent sans clic.
    plan = classify_text("Transform my Shadow in the Brush into a Nidalee.\n"
                         "If my Shadow in the Brush leaves play, Obliterate me.")
    check("l'Ambush de Nidalee : aucun clic, et jouable",
          plan.targeting is Targeting.NONE and plan.playable, plan)

    # ---- CONTRE-EXEMPLES : ce que « into » ne doit RIEN changer -------
    #
    # HEXTECH TRANSMOGULATOR (01PZ005) demande bel et bien DEUX clics de
    # plateau : « an exact copy of another follower » nomme une unité à
    # désigner, pas un jeton. La base le dit en toutes lettres — dans le
    # champ `description`, tous les jetons de transformation portent un
    # lien <AssociatedCard> (« a 3|3 Mini-Minitee », « an Alpha
    # Wildclaw », les neuf Ambush) ; « another follower » est du texte
    # nu. Ce refus-là doit survivre, dans les DEUX modes.
    transmog = "Transform a follower into an exact copy of another follower."
    cibles, _spans = spells._scan_targets(transmog)
    check("Transmogulator : DEUX marqueurs de plateau",
          cibles == ["ANY_UNIT", "ANY_UNIT"], cibles)
    for restreint in (True, False):
        plan = classify_text(transmog, restricted=restreint)
        check("Transmogulator refusé (restreint=%s)" % restreint,
              plan.targeting is Targeting.REFUSED and not plan.playable, plan)
        check("   et hors de portée, pas de la prudence", plan.impossible is True, plan)

    # Transfusion : deux alliés à départager, un coût puis une récompense
    # que `choose_targets` ne sait pas répéter. (Crumble, « Kill an ally to
    # kill a unit », n'est plus de cette famille : c'est un ÉCHANGE piloté
    # depuis le 05/09/2026.)
    plan = classify_text("Deal 1 to an ally to give another ally +2|+2.",
                         restricted=False)
    check("« un allié puis un autre allié » reste refusé",
          plan.targeting is Targeting.REFUSED and plan.impossible is True, plan)

    # « Deal 2 to a champion or 4 to a follower » : deux marqueurs, UN clic.
    plan = classify_text("Deal 2 to a champion or 4 to a follower.", restricted=False)
    check("l'alternative « or » reste UN seul clic",
          plan.targeting is Targeting.ANY_UNIT and plan.playable, plan)

    # Les interfaces hors de portée ne bougent pas d'un pouce.
    #
    # « ANY NUMBER OF » A QUITTÉ CETTE LISTE LE 10/11/2026 : son bouton de
    # validation est l'orbe de tour, qu'on sait cliquer. Il est traité
    # par `test_un_nombre_libre_de_cibles_se_valide_a_l_orbe`, qui vérifie
    # aussi que « up to N » — lui — n'a PAS suivi : ses clics portent sur
    # la main, pas sur un bouton qui manquait.
    for texte in ("Pick a follower.",
                  "Choose one: deal 2, or heal 2.",
                  "Discard up to 3 cards to draw that many."):
        for restreint in (True, False):
            plan = classify_text(texte, restricted=restreint)
            check("hors de portée : %s (restreint=%s)" % (texte[:30], restreint),
                  plan.targeting is Targeting.REFUSED and plan.impossible is True, plan)

    # LA PRUDENCE RESTE ENTIÈRE. Une transformation visant NOTRE camp est
    # un effet néfaste sur notre propre unité : refusée en mode prudent,
    # tentée seulement quand les restrictions sont levées.
    for texte in ("Transform an allied follower into an Alpha Wildclaw.",
                  "Transform an ally into a random 5 cost follower."):
        plan = classify_text(texte, restricted=True)
        check("prudence : %s refusé" % texte[:36],
              plan.targeting is Targeting.REFUSED, plan)
        check("   motif : sur notre propre unité", "propre unité" in plan.reason, plan.reason)
        plan = classify_text(texte, restricted=False)
        check("   sans restrictions, le clic part sur l'allié",
              plan.targeting is Targeting.ALLY and plan.playable, plan)


def test_un_sort_qui_peut_frapper_le_nexus_adverse_le_vise():
    """
    « AN ENEMY OR THE ENEMY NEXUS » : LE NEXUS EST UNE CIBLE CLIQUABLE
    (08/11/2026).

    Le correctif « sort sans cible » du matin a rendu VISIBLE un trou qui
    existait déjà : `choose_target` donnait un repli sur le nexus au seul
    `Targeting.ANYTHING`, jamais à `Targeting.ENEMY`. Or sept sorts de la
    base écrivent noir sur blanc que le nexus est une ALTERNATIVE à
    l'unité — Trueshot Barrage, Statikk Shock, Shock Blast et son jeton
    de Jayce, Divine Draft, Timewinder, Solar Snare. Plateau adverse
    vide, tous rendaient « aucun ennemi en jeu » et le bot les gardait en
    main : exactement l'état de fin de partie que `nexus_weight` et
    l'archétype « aggro » existent pour exploiter.

    LA FRONTIÈRE EST DANS LE TEXTE, et elle a quatre bornes :
      - « an enemy OR the enemy Nexus » : un clic, qui peut tomber sur le
        nexus — c'est ce qu'on répare ;
      - « an enemy » tout court désigne une UNITÉ : lui inventer un repli
        sur le nexus ferait un clic que le jeu refuse ;
      - « RANDOMLY to an enemy or the enemy Nexus » (Ebb) : c'est le jeu
        qui choisit, aucun clic n'est attendu — même famille que
        « a random ally » ;
      - « deal 2 to an enemy AND 1 to the enemy Nexus » (Death's Hand) :
        le nexus prend des dégâts automatiques, il ne se clique pas.
    """
    print("\nLe nexus adverse comme cible d'un sort")

    from test_actions import blocking_snapshot

    # ---- ce que le texte OFFRE au clic ---------------------------------
    alternatives = {
        "Deal 3 to an enemy or the enemy Nexus.": 1,
        "Deal 1 to an enemy or the enemy Nexus, and 1 to another.": 2,
        "Deal 3 to an enemy or the enemy Nexus, 2 to another, and 1 to another.": 3,
        "Deal 1 to a unit or the enemy Nexus, and another, and another.": 3,
    }
    for texte, clics in alternatives.items():
        plan = classify_text(texte, restricted=False)
        check(f"nexus cliquable : {texte[:44]:<46}",
              plan.targeting is Targeting.ANYTHING, plan)
        check(f"   {clics} clic(s) annoncé(s)", plan.total_targets == clics, plan)

    # ---- et ce qu'il en fait sur un plateau VIDE ------------------------
    vide = blocking_snapshot(["BRUTE"], [])
    plan = classify_text("Deal 3 to an enemy or the enemy Nexus.", restricted=False)
    point, qui = spells.choose_target(plan, vide)
    check("plateau adverse vide : le sort part sur le nexus",
          point == vide.enemy_nexus, (point, qui))

    # LE NEXUS NE SE CLIQUE QU'UNE FOIS. Trueshot Barrage réclame trois
    # cibles ; face à un nexus seul, `choose_targets` n'en rend qu'une —
    # c'est l'invariant du 06/09 (« another » interdit de redésigner ce
    # qu'on vient de désigner) et il doit tenir ici aussi.
    barrage = classify_text(
        "Deal 3 to an enemy or the enemy Nexus, 2 to another, and 1 to another.",
        restricted=False)
    points = spells.choose_targets(barrage, vide)
    check("trois cibles réclamées, le nexus n'est rendu qu'UNE fois",
          [p for p, _ in points] == [vide.enemy_nexus], points)

    # ---- avec un ennemi en face, l'unité passe devant -------------------
    # « Deal 3 » tue la Recrue 1/2 : on préfère toujours tuer.
    avec = blocking_snapshot(["BRUTE"], ["SMALL"])
    point, qui = spells.choose_target(plan, avec)
    check("un ennemi tuable passe devant le nexus",
          point != avec.enemy_nexus and "Recrue" in qui, (point, qui))

    # ---- LE JEU CHOISIT : aucun clic -----------------------------------
    for texte in (
        "Deal 2 randomly to an enemy or the enemy Nexus and create a Flow in hand.",
        "Deal 2 randomly to an enemy or the enemy Nexus and create a Flow in hand. "
        "Create a Nami in your deck.",
        "Reputation: I cost 3 less. Deal 1 to a random enemy or the enemy Nexus 5 times.",
        "Each one targets a different random enemy or the enemy Nexus if none.",
    ):
        plan = classify_text(texte, restricted=False)
        check(f"tir au hasard, aucun clic : {texte[:38]:<40}",
              plan.targeting is Targeting.NONE, plan)

    # EBB AND FLOW (05BW006T1) EST LE SEUL CAS MIXTE de la base, et il
    # mérite d'être nommé : « Deal 2 randomly to an enemy or the enemy
    # Nexus AND heal an ally or your Nexus 2. » Le tir est au hasard, mais
    # le SOIN, lui, se désigne. Il ne restait donc qu'un marqueur — l'allié
    # du soin — là où le compte en voyait deux et refusait la carte. Le
    # clic part sur un allié, ce que le jeu accepte.
    #
    # DETTE ASSUMÉE : `effect_clause` coupe sur « . » et « ; », jamais sur
    # un « and », si bien que l'effet lu sur cette clause est le DEAL du
    # début et non le HEAL. Conséquence mesurée : l'allié est choisi comme
    # s'il encaissait des dégâts (le plus solide) au lieu du plus abîmé.
    # Le geste reste légal et la carte devient jouable ; élargir la coupe
    # aux « and » toucherait toute la base et n'a rien à faire ici.
    plan = classify_text(
        "Deal 2 randomly to an enemy or the enemy Nexus and heal an ally or your Nexus 2.",
        restricted=False)
    check("Ebb and Flow : le seul clic restant est l'allié du soin",
          plan.targeting is Targeting.ALLY and plan.total_targets == 1, plan)

    # ---- LE NEXUS AUTOMATIQUE N'EST PAS UNE CIBLE ----------------------
    # Death's Hand (02NX008), Spitfire (08NX003T1) : le nexus encaisse
    # tout seul, le clic reste sur une UNITÉ. Sans ennemi, on ne lance
    # pas — c'est le correctif du matin, et il doit survivre.
    for texte in (
        "Deal 2 to an enemy and 1 to the enemy Nexus.",
        "Deal 2 to an enemy and 2 to the enemy Nexus.",
    ):
        plan = classify_text(texte, restricted=False)
        check(f"nexus automatique : clic sur l'unité ({texte[:30]})",
              plan.targeting is Targeting.ENEMY, plan)
        point, pourquoi = spells.choose_target(plan, vide)
        check("   et sans ennemi, aucun clic fabriqué", point is None, (point, pourquoi))

    # « Deal 2 to the enemy Nexus » tout court : aucun marqueur, aucun
    # clic. Vérifié plutôt que supposé.
    for texte in ("Deal 2 to the enemy Nexus.", "Deal 2 to the enemy Nexus and draw 1."):
        plan = classify_text(texte, restricted=False)
        check(f"nexus seul : aucune cible ({texte[:34]})",
              plan.targeting is Targeting.NONE, plan)

    # ---- « S'IL N'Y A PAS D'ENNEMI, JE VISE LE NEXUS » -----------------
    # Final Spark (01DE042T3), Ace in the Hole (98PZ004), Javelin Toss
    # (07SH013T2) : le sort se résout SEUL, sans aucun clic. Le plan le
    # DIT depuis le 10/11 (`resolves_without_target`, dette du 09/11) —
    # voir `test_un_sort_qui_se_resout_sans_ennemi_le_dit_dans_son_plan`.
    # Ce qu'on garantit ici reste le minimum, et il n'a pas bougé :
    # AUCUN clic inventé sur le nexus.
    for texte in (
        "Deal 4 to an enemy. If there are no enemies, deal 4 to the enemy Nexus instead.",
        "Deal 4 to an enemy. If there are no enemies when I'm played, "
        "I target the enemy Nexus instead.",
    ):
        plan = classify_text(texte, restricted=False)
        check(f"repli automatique : clic sur l'unité ({texte[:30]})",
              plan.targeting is Targeting.ENEMY, plan)
        point, _ = spells.choose_target(plan, vide)
        check("   et aucun clic fabriqué sur le nexus", point is None, point)

    # ---- LE CORRECTIF DU MATIN N'EST PAS DÉFAIT ------------------------
    # Les trois sorts du relevé du 08/11 : plateau vide, aucune cible ;
    # un ennemi, et ils repartent.
    sans_nexus = {
        "Recall a unit with 3 or less Power.": "Quicken",
        "Kill a unit, then revive it.": "Spirit Journey",
        "Deal 3 to a follower. Phase Severum or Gravitum.": "Calibrum",
    }
    for texte, nom in sans_nexus.items():
        plan = classify_text(texte, restricted=False)
        point, pourquoi = spells.choose_target(plan, vide)
        check(f"{nom} : toujours sans cible sur un plateau vide",
              point is None, (point, pourquoi))
        point, _ = spells.choose_target(plan, avec)
        check(f"   {nom} : et de nouveau ciblé dès qu'un ennemi est là",
              point is not None, point)



def test_un_soin_peut_viser_notre_nexus():
    """
    « HEAL AN ALLY OR YOUR NEXUS » : LE MIROIR DU CHANTIER DU 08/11.

    Le 08/11 on a appris à lire « an enemy OR the enemy Nexus » : un seul
    clic, deux endroits où il peut tomber, et le second existe toujours.
    LE SYMÉTRIQUE N'AVAIT PAS ÉTÉ FAIT, et il se paie du même prix — banc
    vide, « Heal an ally or your Nexus 3 » rendait « aucun allié en jeu »
    et le soin était abandonné, dans l'état même où on en a le plus
    besoin.

    NEUF CARTES de la base écrivent cette alternative, mesurées : Health
    Potion (01IO004), Ritual of Renewal (01IO001), Guiding Touch
    (03MT051), Starshaping (03MT084), Explorer's Refreshments
    (08BW028T4), Flow (05BW006T2), Ebb and Flow (05BW006T1), et deux
    UNITÉS dont le « Play: » dit la même chose — Kindly Tavernkeeper
    (01FR050) et Smooth Mixologist (07IO019).

    LES GARDE-FOUS SONT CEUX DU MARQUEUR ORDINAIRE, ET PAS UN DE PLUS :
    le repère est ancré SUR le marqueur que `_scan_targets` a retenu, il
    hérite donc de son refus de « a random ally » et de la nullification
    par « randomly to ». Et un nexus qui se soigne TOUT SEUL (« heal your
    Nexus 3 ») n'est pas une cible : rien ne s'y clique.
    """
    print("\nUn soin peut viser notre nexus")

    from test_actions import blocking_snapshot

    # Banc vide des deux côtés : c'est l'état que le correctif vise.
    vide = blocking_snapshot([], [])
    avec_allie = blocking_snapshot(["BRUTE"], [])

    textes = (
        "Heal an ally or your Nexus 3.",
        "Heal an ally or your Nexus 4. Draw 1.",
        "Heal an ally or your Nexus 2, and create an Ebb and Flow in hand.",
        "Invoke a Celestial card that costs 7 or more, then heal an ally or your Nexus 5.",
    )
    for texte in textes:
        for restreint in (False, True):
            plan = classify_text(texte, restricted=restreint)
            etiquette = "prudent" if restreint else "permissif"
            check(f"[{etiquette}] notre nexus est l'autre point : {texte[:38]:<40}",
                  plan.our_nexus_is_target is True, plan)
            check("   le ciblage reste celui d'un allié",
                  plan.targeting is Targeting.ALLY, plan)
            check("   un seul clic", plan.total_targets == 1, plan)

        plan = classify_text(texte, restricted=False)
        point, qui = spells.choose_target(plan, vide)
        check(f"   banc vide : le soin part sur NOTRE nexus ({texte[:28]})",
              point == vide.our_nexus, (point, qui))
        point, qui = spells.choose_target(plan, avec_allie)
        check("   et avec un allié, rien ne change : c'est lui qu'on clique",
              point is not None and point != avec_allie.our_nexus, (point, qui))

    # LE « PLAY: » D'UNE UNITÉ DIT LA MÊME CHOSE, et passe par le même
    # chemin (`classify_unit_play`). Kindly Tavernkeeper, banc vide, était
    # posée puis laissée en attente d'un clic qu'on ne savait pas faire.
    for description in ("Play: Heal an ally or your Nexus 3.",
                        "Play: Heal an ally or your Nexus 3 and create a Coin in hand."):
        plan = spells.classify_unit_play(description, restricted=False)
        check(f"unité : {description[:34]:<36} vise notre nexus à défaut d'allié",
              plan is not None and plan.our_nexus_is_target is True, plan)
        point, qui = spells.choose_target(plan, vide)
        check("   et le point rendu est bien le nôtre", point == vide.our_nexus,
              (point, qui))

    # ---- CE QUI N'EST PAS UNE ALTERNATIVE ------------------------------
    # Un soin ordinaire ne gagne aucun repli : lui en inventer un ferait
    # cliquer un nexus que le jeu n'attend pas.
    for texte in ("Heal an ally 3.", "Heal an ally 3 and draw 1.",
                  "Grant an ally +0|+3."):
        plan = classify_text(texte, restricted=False)
        check(f"soin ordinaire, aucun repli : {texte[:30]:<32}",
              plan.our_nexus_is_target is False, plan)
        point, _ = spells.choose_target(plan, vide)
        check("   banc vide : aucun clic fabriqué", point is None, point)

    # « Heal your Nexus 3 » tout court : le nexus se soigne tout seul,
    # aucun marqueur, aucun clic. Vérifié plutôt que supposé.
    for texte in ("Heal your Nexus 3.", "Deal 3 to all enemies and heal your Nexus 3."):
        plan = classify_text(texte, restricted=False)
        check(f"nexus seul : aucune cible ({texte[:32]})",
              plan.targeting is Targeting.NONE and plan.our_nexus_is_target is False,
              plan)

    # C'EST LE JEU QUI CHOISIT : ni marqueur, ni repli. Les deux formes
    # qui NIENT la désignation sont celles du chantier d'en face —
    # « a random ally » et « randomly to ».
    for texte in ("Heal a random ally or your Nexus 2.",
                  "Heal 2 randomly to an ally or your Nexus."):
        plan = classify_text(texte, restricted=False)
        check(f"le jeu choisit, aucun clic : {texte[:34]:<36}",
              plan.targeting is Targeting.NONE and plan.our_nexus_is_target is False,
              plan)

    # EBB AND FLOW (05BW006T1) RESTE LE CAS MIXTE : le tir est au hasard
    # (aucun clic), le SOIN se désigne — et c'est lui qui gagne le repli.
    plan = classify_text(
        "Deal 2 randomly to an enemy or the enemy Nexus and heal an ally or your Nexus 2.",
        restricted=False)
    check("Ebb and Flow : un seul clic, celui du soin",
          plan.targeting is Targeting.ALLY and plan.total_targets == 1, plan)
    check("   et banc vide, il tombe sur notre nexus",
          plan.our_nexus_is_target is True
          and spells.choose_target(plan, vide)[0] == vide.our_nexus, plan)

    # NOTRE NEXUS NE SE CLIQUE QU'UNE FOIS, ici comme en face : s'il
    # fallait deux alliés, le nôtre ne peut pas tenir lieu des deux.
    double = classify_text("Heal an ally or your Nexus 2, and another.", restricted=False)
    if double.total_targets > 1:
        points = spells.choose_targets(double, vide)
        check("deux cibles réclamées, notre nexus n'est rendu qu'UNE fois",
              [p for p, _ in points] == [vide.our_nexus], points)


def test_un_sort_qui_se_resout_sans_ennemi_le_dit_dans_son_plan():
    """
    « IF THERE ARE NO ENEMIES, … THE ENEMY NEXUS INSTEAD » (dette du 09/11).

    TROIS CARTES, mesurées : Final Spark (01DE042T3), Ace in the Hole
    (98PZ004) et Javelin Toss (07SH013T2). Le MÊME texte demande un clic
    dès qu'un ennemi est là, et n'en demande AUCUN quand le plateau
    adverse est vide — le sort se résout seul sur le nexus. La
    classification ne peut pas trancher sur le texte seul : elle dit donc
    les deux, et c'est l'instantané qui choisit.

    CE QUI NE DOIT PAS BOUGER D'UN MILLIMÈTRE : aucun clic n'est
    FABRIQUÉ sur le nexus. `choose_target` rend toujours None sur un
    plateau vide — un clic que le jeu refuse coûte plus cher qu'une carte
    gardée en main. Le drapeau ne sert qu'à `actions`, pour qu'il sache
    que « zéro cible » n'est pas ici un empêchement.
    """
    print("\nUn sort qui se résout sans ennemi le dit dans son plan")

    from test_actions import blocking_snapshot

    vide = blocking_snapshot(["BRUTE"], [])
    avec = blocking_snapshot(["BRUTE"], ["SMALL"])

    textes = (
        "Deal 4 to an enemy. If there are no enemies, deal 4 to the enemy Nexus instead.",
        "Deal 10 to an enemy. If there are no enemies, deal 10 to the enemy Nexus "
        "instead.+50% chance to Critical Strike.",
        "Deal 4 to an enemy. If there are no enemies when I'm played, "
        "I target the enemy Nexus instead.",
    )
    for texte in textes:
        plan = classify_text(texte, restricted=False)
        check(f"la cible peut manquer : {texte[:34]:<36}",
              plan.resolves_without_target is True, plan)
        check("   le ciblage reste celui d'un ennemi",
              plan.targeting is Targeting.ENEMY, plan)
        check("   un seul clic annoncé", plan.total_targets == 1, plan)
        point, _ = spells.choose_target(plan, vide)
        check("   et AUCUN clic fabriqué sur le nexus", point is None, point)
        point, _ = spells.choose_target(plan, avec)
        check("   un ennemi est là : on le clique, comme avant",
              point == avec.enemy_attack_row[0].center, point)

    # ---- CE QUI N'EST PAS CETTE FAMILLE --------------------------------
    # « If it's dead or gone, deal N to the enemy Nexus instead » (Cannon
    # Barrage, Annie, Threaded Volley, Relentless Storm... quatorze textes
    # de la base contiennent « Nexus instead ») : la cible EXISTE au
    # moment du clic, c'est après coup que le jeu redirige. Sans ennemi,
    # le sort n'a toujours rien à viser.
    for texte in (
        "Deal 2 to a unit. If it's dead or gone, deal 1 to the enemy Nexus instead.",
        "Deal 4 to a unit. If it's dead or gone, deal 2 to the enemy Nexus instead.",
        "Deal 2 to an enemy and 1 to the enemy Nexus.",
        "Deal 3 to an enemy.",
    ):
        plan = classify_text(texte, restricted=False)
        check(f"la cible reste obligatoire : {texte[:34]:<36}",
              plan.resolves_without_target is False, plan)

    # Et la condition sans le nexus derrière ne dit rien non plus : c'est
    # le COUPLE « plus d'ennemis » + « le nexus à la place » qui parle.
    plan = classify_text(
        "Deal 4 to an enemy. If there are no enemies, draw a card instead.",
        restricted=False)
    check("sans le nexus derrière, aucun repli",
          plan.resolves_without_target is False, plan)


def test_une_defausse_ne_doit_pas_manger_la_cible():
    """
    « TO PLAY, DISCARD 1 » EST UN COÛT, PAS LA CIBLE (14/11/2026, fait de
    jeu d'Ewan : « le bot n'arrive pas à utiliser Enthousiasme de Jinx !
    — il arrive bien à défausser une carte de ma main mais n'a pas su
    viser le nexus ennemi »).

    Jinx's Get Excited! (01PZ040T3) dit « To play, discard 1. Deal 3 to
    anything. » Le plan rendu était `DAMAGE : 1 carte(s) à sacrifier en
    main` — `Targeting.HAND`, « Clic : non ». La désignation en main
    passait DEVANT le plateau et les cibles trouvées étaient JETÉES : le
    bot payait le coût, posait le sort, et le jeu attendait une cible que
    personne ne cliquait.

    CE N'ÉTAIT PAS UN OUBLI, c'était une décision écrite — « deux
    interfaces à la suite, c'est deux fois plus d'occasions de se
    tromper, et un échec au milieu laisse la partie dans un état qu'on ne
    sait pas décrire ». Ce que la partie du 14/11 montre, c'est que
    l'état redouté est DÉJÀ celui qu'on produit, systématiquement et sans
    exception : la carte est posée, la défausse est faite, et seul le
    garde d'immobilité (~50 s) finit par annuler. Ne pas cliquer n'est
    pas le choix prudent, c'est le pire des deux.

    CINQ CARTES, mesurées sur les 2898 de la base, dont TROIS
    collectionnables : Get Excited! (01PZ039) et le jeton de Jinx
    (01PZ040T3) « Deal 3 to anything » ; Timewinder (04PZ003), que
    CLAUDE.md nommait déjà en relecture le 08/11 sans la réparer ;
    Electro Harpoon (05BC078) ; Spinning Axe (01NX020T1).

    LE MODE PRUDENT NE CHANGE PAS : il refuse toujours « deux interfaces
    : la main puis le plateau ». C'est le mode par défaut — celui où le
    bot joue — qui apprend à enchaîner.

    ET UNE DÉFAUSSE SANS CIBLE DE PLATEAU RESTE UNE DÉFAUSSE : « Discard
    1 to draw 1 » ne gagne pas un clic qu'il n'a jamais demandé.
    """
    print("\nUne défausse est un coût, la cible vient après")

    JINX = "To play, discard 1. Deal 3 to anything.\nCreate a Jinx in your deck."

    plan = spells.classify_text(JINX, restricted=False)
    check("le coût en main est toujours lu", plan.picks == 1, plan.picks)
    check("   ... et la carte défaussée quitte bien la main", plan.pick_consumes)
    check("la cible de plateau n'est plus jetée",
          plan.board_targeting is not spells.Targeting.NONE, plan.board_targeting)
    check("   « anything » vise n'importe quoi, nexus compris",
          plan.board_targeting is spells.Targeting.ANYTHING, plan.board_targeting)
    check("   le montant survit au coût", plan.amount == 3, plan.amount)
    check("le plan annonce les DEUX gestes", plan.needs_board_click_after_hand)

    # Le sous-plan est ce que `choose_target` saura servir : la cible du
    # PLATEAU, sans la désignation en main qui a déjà été payée.
    sous = plan.board_plan()
    check("le sous-plan porte la cible de plateau",
          sous.targeting is spells.Targeting.ANYTHING, sous.targeting)
    check("   ... et plus aucune désignation en main", sous.picks == 0, sous.picks)
    check("   ... et il réclame bien un clic", sous.needs_click)

    # LES CINQ CARTES DE LA BASE, par le chemin que le bot emprunte.
    attendus = {
        "01PZ040T3": spells.Targeting.ANYTHING,   # Jinx's Get Excited!
        "01PZ039":   spells.Targeting.ANYTHING,   # Get Excited!
        # « an enemy OR the enemy Nexus » est le marqueur du 08/11 : il
        # donne ANYTHING, puisque le clic peut tomber sur le nexus.
        "04PZ003":   spells.Targeting.ANYTHING,   # Timewinder
        "05BC078":   spells.Targeting.ANY_UNIT,   # Electro Harpoon
        "01NX020T1": spells.Targeting.ALLY,       # Spinning Axe
    }
    import lor_api
    db = lor_api.load_card_db()
    for code, cible in sorted(attendus.items()):
        carte = db.get(code)
        if not carte:
            check(f"   {code} : absente de la base (base incomplète ?)", True)
            continue
        p = spells.classify_card(carte, restricted=False)
        check(f"   {code} enchaîne la défausse puis le plateau",
              p.needs_board_click_after_hand, str(p))
        check(f"   {code} vise {cible.name}", p.board_targeting is cible,
              p.board_targeting)

    # LE COMPTE DES CIBLES NE SE RECALCULE PAS. Timewinder dit « …and 1
    # to another » : deux clics. Recompter les marqueurs dans la branche
    # du coût en main donnait 1 — on n'aurait cliqué qu'une cible sur
    # deux, c'est-à-dire exactement le blocage qu'on répare. C'est
    # `extra_targets`, déjà calculé par le chemin normal, qui fait foi.
    tw = db.get("04PZ003")
    if tw:
        p = spells.classify_card(tw, restricted=False)
        check("   Timewinder réclame bien DEUX cibles après la défausse",
              p.board_plan().total_targets == 2, p.board_plan().total_targets)
    jinx = db.get("01PZ040T3")
    if jinx:
        p = spells.classify_card(jinx, restricted=False)
        check("   ... et Jinx's Get Excited! une seule",
              p.board_plan().total_targets == 1, p.board_plan().total_targets)

    # NON-RÉGRESSION 1 — une défausse SANS cible de plateau reste nue.
    nue = spells.classify_text("Discard 1 to draw 1.", restricted=False)
    check("une défausse sans cible de plateau ne gagne pas de clic",
          not nue.needs_board_click_after_hand, str(nue))
    check("   ... et reste une désignation en main",
          nue.targeting is spells.Targeting.HAND, nue.targeting)

    # NON-RÉGRESSION 2 — le mode prudent refuse toujours l'enchaînement.
    prudent = spells.classify_text(JINX, restricted=True)
    check("en mode prudent, la carte reste refusée",
          prudent.targeting is spells.Targeting.REFUSED, prudent.targeting)
    # Le motif vient de `REFUSALS` (« ^to play, »), qui mord AVANT la
    # branche « deux interfaces » — c'est le refus structurel du coût
    # additionnel. On vérifie le refus, pas le chemin qui l'a produit.
    check("   ... sur le coût additionnel, comme avant",
          "coût additionnel" in prudent.reason, prudent.reason)


def main():
    for test in (
        test_une_defausse_ne_doit_pas_manger_la_cible,
        test_target_counting,
        test_qualified_allies_are_still_allies,
        test_overlapping_markers,
        test_bare_another_is_a_second_target,
        test_choose_targets_excludes_previous_picks,
        test_harmful_on_ally_refused,
        test_unknown_effect_on_ally_refused,
        test_buff_on_enemy,
        test_structural_refusals,
        test_hand_designation,
        test_conditions_are_not_targets,
        test_uncontrollable_interfaces_still_refused,
        test_choix_de_version,
        test_choix_de_variante,
        test_amount_extracted,
        test_target_selection,
        test_ephemeral_is_the_wrong_gift_and_the_right_sacrifice,
        test_anything_falls_back_to_nexus,
        test_no_target_available,
        test_classement_sans_restrictions,
        test_speed_rules,
        test_la_commande_repond_dans_le_mode_du_bot,
        test_fenetre_de_cartes,
        test_la_fenetre_peut_etre_celle_de_ladversaire,
        test_damaged_target_condition,
        test_invisible_target_conditions_are_refused,
        test_un_preambule_ne_doit_plus_masquer_leffet,
        test_quatre_verbes_hostiles_qui_manquaient,
        test_un_effet_qui_reecrit_les_stats_se_pese_sur_les_deux_camps,
        test_un_allie_qui_revient_nest_pas_un_sacrifie,
        test_activer_leffet_dun_allie_est_un_bienfait,
        test_une_carte_piochee_nest_pas_sur_le_plateau,
        test_une_cible_qui_attaque_se_lit_dans_la_rangee,
        test_une_cible_marquee_est_hors_de_portee,
        test_un_suivant_nest_pas_un_champion,
        test_un_nombre_libre_de_cibles_se_valide_a_l_orbe,
        test_counted_plural_targets,
        test_une_transformation_nomme_un_jeton_pas_une_seconde_cible,
        test_un_sort_qui_peut_frapper_le_nexus_adverse_le_vise,
        test_un_soin_peut_viser_notre_nexus,
        test_un_sort_qui_se_resout_sans_ennemi_le_dit_dans_son_plan,
        test_coverage_runs,
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
