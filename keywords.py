#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
keywords.py

RÉSOLUTION D'UN COMBAT SINGULIER, MOTS-CLÉS COMPRIS.

--------------------------------------------------------------------
POURQUOI CE MODULE EXISTE
--------------------------------------------------------------------
Les mots-clés étaient LUS depuis toujours (`BoardCard.keywords`,
`BoardCard.has()`), mais six seulement pesaient sur une décision :
Elusive et Fearsome pour la légalité d'un blocage, Overwhelm pour
l'excédent, CantBlock / CantAttack / Immobile pour l'état de l'unité.
Tout le reste du raisonnement de combat tenait en deux comparaisons —
`attack >= health` d'un côté, `attack < health` de l'autre.

Ces deux comparaisons se trompent sur 250 cartes de la base :

    Frappe Rapide (QuickStrike, 89 cartes)  compté comme un échange,
        alors qu'elle tue sans être touchée ;
    Barrière (Barrier, 14)                  comptée comme morte,
        alors qu'elle ne prend aucun dégât ;
    Coriace (Tough, 29)                     tuée par une frappe qui
        lui laisse en réalité 1 PV ;
    Redoutable au sens Formidable (7)       comptée à 0 d'attaque,
        alors qu'elle frappe avec ses PV ;
    Impact (37), Vol d'âme (17)             dégâts et soins au nexus
        purement ignorés ;
    Éphémère (32), Sans-mort (4)            leur mort comptée comme
        une perte, alors qu'elle est gratuite.

D'où un module à part : la résolution d'une frappe est une fonction
PURE, la partie du bot la plus facile à tester exhaustivement et la
plus coûteuse à se tromper. `actions.py` n'y garde que les décisions
(qui attaque, qui bloque) et lui délègue la physique.

--------------------------------------------------------------------
CE QUE CE MODULE NE SAIT PAS
--------------------------------------------------------------------
LES MOTS-CLÉS SONT CEUX IMPRIMÉS SUR LA CARTE, PLUS QUATRE QUI SE
LISENT À L'ÉCRAN (20/11/2026). `/positional-rectangles` ne renvoie
qu'un CardCode : une Barrière donnée par un sort, un Vulnerable posé
sur un ennemi, un Frostbite sont INVISIBLES à l'API. C'est la même
limite que les stats avant l'OCR — sauf qu'ici il n'y a pas de chiffre
à lire, seulement une icône.

Depuis le 20/11/2026 cette icône se lit, pour QUATRE mots-clés
seulement (Ephemeral, Hallowed, Challenger, Overwhelm) : les seize
autres n'ont pas encore de gabarit, et un mot-clé RETIRÉ (un Silence)
ne se voit toujours pas — l'écran COMPLÈTE la carte imprimée, il ne
retire jamais rien. Cf. `mots_cles_ecran.py`, et l'interrupteur de
repli `game_state.MOTS_CLES_ECRAN`.

Tout passe par `has()` ci-dessous, point d'entrée UNIQUE ; la lecture
d'écran y arrive par l'union que fait `BoardCard.has`, et aucune
décision de ce module n'a eu à le savoir.

--------------------------------------------------------------------
LES RÈGLES MODÉLISÉES
--------------------------------------------------------------------
    Formidable      frappe avec ses PV au lieu de son attaque
    Tough           -1 sur CHAQUE instance de dégâts reçue
    Barrier         annule ENTIÈREMENT la première instance, puis se brise
    QuickStrike     en attaquant, frappe AVANT son bloqueur
    DoubleStrike    frappe avant, puis une seconde fois avec la riposte
    Overwhelm       l'excédent au-delà des PV du bloqueur va au nexus
    Impact          1 dégât au nexus adverse à chaque frappe en attaquant
    Lifesteal       soigne son nexus des dégâts infligés
    Ephemeral       meurt en fin de round : sa mort en combat est gratuite
    Deathless       revient une fois : sa mort en combat est gratuite
    Challenger      en attaquant, tire l'ennemi de son choix en défense
    Vulnerable      peut être tirée par n'importe quel attaquant

Volontairement absents, parce qu'ils demandent de COMPRENDRE un texte
et non de reconnaître un mot-clé : LastBreath (l'effet est écrit dans
la description), Fury, Regeneration, Scout, Support, SpellShield —
voir « PISTES » en bas de fichier.

--------------------------------------------------------------------
UTILISATION
--------------------------------------------------------------------
    import keywords

    duel = keywords.resolve_duel(attacker, blocker)
    duel.attacker_dies, duel.blocker_dies, duel.nexus_damage

    keywords.strike_power(card)       # Formidable
    keywords.unblocked_damage(card)   # ce qui passe si personne ne bloque
    keywords.death_cost(card)         # ce que sa mort coûte VRAIMENT
    keywords.dies_anyway(card)        # Éphémère : elle ne verra pas le round suivant

`attacker` est l'unité qui ATTAQUE et `blocker` celle qui bloque :
l'ordre n'est pas décoratif, QuickStrike / Overwhelm / Impact ne
valent qu'en attaquant. Au blocage, c'est l'unité ADVERSE qui est
l'attaquant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ============================================================
# SOURCE DES MOTS-CLÉS
# ============================================================

def has(card, keyword: str) -> bool:
    """
    Cette carte porte-t-elle ce mot-clé ?

    SEUL point du module qui interroge la carte. `BoardCard.has()`
    compare indifféremment le libellé affiché (« Can't Block ») et la
    référence interne (« CantBlock »), casse et ponctuation ignorées.

    Passer par une fonction plutôt que par `card.has()` directement
    n'est pas une politesse : c'est le point unique par lequel la
    lecture à l'écran des mots-clés ACCORDÉS est arrivée (20/11/2026).

    ELLE EST BRANCHÉE UN CRAN PLUS BAS, et c'est le bon endroit :
    `BoardCard.has` fait l'UNION des mots-clés imprimés et de
    `keywords_lus` (posé par `game_state.lire_les_mots_cles`, cf.
    `mots_cles_ecran.py`). Tout ce qui interroge une carte en profite —
    y compris les quelques appels qui passent directement par
    `card.has()` — et aucune décision n'a eu à le savoir.
    """
    return card is not None and bool(card.has(keyword))


# ============================================================
# CE QUE LE BOT SAIT ÉVALUER
# ============================================================
# Les mots-clés dont `resolve_duel` tient compte — autrement dit ceux
# dont l'octroi change un calcul, et pas seulement une ligne de texte.
#
# Sert à DÉPARTAGER DEUX VERSIONS D'UN MÊME POUVOIR quand le jeu nous
# demande de choisir : « Grant an ally Spellshield or Overwhelm » (Iula,
# 05MT013). Entre les deux, on prend celui qu'on sait chiffrer —
# Overwhelm change l'excédent d'une attaque, SpellShield ne concerne que
# le ciblage d'un sort adverse, que le bot ne modélise pas.
#
# Ce n'est pas une échelle de valeur : c'est un OUI/NON honnête. Classer
# les mots-clés entre eux demanderait des nombres qu'on n'a pas.
MODELLED_KEYWORDS = (
    "Formidable", "Tough", "Barrier", "QuickStrike", "Quick Attack",
    "DoubleStrike", "Double Attack", "Overwhelm", "Impact", "Lifesteal",
    "Ephemeral", "Deathless", "Challenger", "Vulnerable", "Elusive",
    "Fearsome", "CantBlock", "Can't Block", "CantAttack", "Immobile",
)

_MODELLED_RX = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in MODELLED_KEYWORDS) + r")\b", re.I
)


def names_a_modelled_keyword(text: str) -> bool:
    """Ce texte accorde-t-il un mot-clé dont le bot sait tenir compte ?"""
    return bool(_MODELLED_RX.search(text or ""))


# Coriace retire ce nombre de dégâts à chaque instance reçue.
TOUGH_REDUCTION = 1

# Impact ajoute ce nombre de dégâts au nexus par frappe en attaquant.
# La base ne dit pas COMBIEN de fois le mot-clé est empilé — un buff
# « +1 Impact » est invisible — donc on compte une occurrence.
IMPACT_DAMAGE = 1


# ============================================================
# LECTURES DÉRIVÉES D'UNE CARTE
# ============================================================

def strike_power(card) -> int:
    """
    Puissance de frappe RÉELLE de l'unité.

    Formidable frappe avec ses PV : une 0/7 Formidable frappe pour 7.
    Sans ce détour, `attackers_available` l'écartait purement et
    simplement (filtre `attack > 0`) — le bot ne l'engageait jamais.

    `card.attack` et `card.health` sont déjà les stats LUES à l'écran
    quand l'OCR a tourné : buffs et dégâts subis sont donc pris en
    compte gratuitement ici.
    """
    return max(0, card.health if has(card, "Formidable") else card.attack)


def impact_damage(card) -> int:
    """Dégâts d'Impact d'UNE frappe de cette unité en attaquant."""
    return IMPACT_DAMAGE if has(card, "Impact") else 0


def strikes_before_blocker(card) -> bool:
    """Frappe-t-elle avant son bloqueur ? (Frappe Rapide et Frappe Double)"""
    return has(card, "QuickStrike") or has(card, "DoubleStrike")


def strike_count(card) -> int:
    """Nombre de frappes de cette unité en attaquant."""
    return 2 if has(card, "DoubleStrike") else 1


def unblocked_damage(card) -> int:
    """
    Dégâts au nexus adverse d'un attaquant que PERSONNE ne bloque.

    Impact compte : frapper le nexus est une frappe.
    """
    return strike_power(card) + impact_damage(card)


def can_challenge(attacker, target) -> bool:
    """
    Notre attaquant peut-il TIRER cette unité adverse en défense ?

    Deux mots-clés ouvrent ce droit, et ils sont sur des cartes
    différentes :
        - Challenger sur NOTRE unité : elle choisit n'importe quel
          ennemi (67 cartes) ;
        - Vulnerable sur l'unité ADVERSE : n'importe lequel de nos
          attaquants peut la tirer.

    `target.can_block` est exigé : tirer une unité Immobile ou « Ne peut
    pas bloquer » n'aurait aucun sens, et le client refuserait le geste
    — un glisser perdu, et le tour qui traîne.

    LA LÉGALITÉ DU BLOCAGE QUI SUIT N'EST PAS TESTÉE ICI, mais elle doit
    l'être par l'appelant (`actions.can_block_attacker`). Tirer une unité
    à 2 d'attaque avec un attaquant Redoutable, ou n'importe qui avec un
    attaquant Insaisissable, place l'adversaire dans une situation dont
    je ne connais pas la règle exacte — on s'en tient donc aux tirages
    dont le blocage est indiscutablement légal.
    """
    if not target.is_unit or not target.can_block:
        return False
    return has(attacker, "Challenger") or has(target, "Vulnerable")


# Un champion vaut plus que ses chiffres : il monte de niveau, porte le
# plan du deck, et l'adversaire le vise en premier. Monté, davantage
# encore. Les deux bonus valent des deux côtés du plateau : on protège
# les nôtres et on cherche à tuer les siens (cf. riposte.most_precious,
# plan_attack, plan_blocks).
CHAMPION_BONUS = 2
LEVELED_BONUS = 4


def unit_value(card) -> int:
    """
    Valeur approchée d'une unité, pour comparer deux échanges.

    Puissance de frappe (Formidable comprise) plus PV, plus un bonus de
    champion (lu dans card_sets via `supertype`, et le niveau 2 via le
    cardCode rapporté par l'API). Ce n'est pas une évaluation de
    deck-builder : juste une échelle commune, la même des deux côtés.
    """
    value = strike_power(card) + card.health
    if getattr(card, "is_leveled", False):
        value += LEVELED_BONUS
    elif getattr(card, "is_champion", False):
        value += CHAMPION_BONUS
    return value


def death_cost(card) -> int:
    """
    Ce que la mort de cette unité coûte VRAIMENT à son camp.

    Deux morts sont gratuites, et les compter comme des pertes rendait
    le bot craintif là où il n'avait rien à perdre :
        - Ephemeral meurt à la fin du round de toute façon. La garder
          en défense n'a aucun sens : autant qu'elle frappe ou qu'elle
          bloque, c'est du gratuit.
        - Deathless revient avec 1 PV la première fois qu'elle meurt.
          Comme on ignore si elle est déjà morte ce round, on suppose
          que non : se tromper dans ce sens fait attaquer une fois de
          trop, l'inverse ferait renoncer à un échange toujours gagnant.
    """
    if has(card, "Ephemeral") or has(card, "Deathless"):
        return 0
    return unit_value(card)


def dies_anyway(card) -> bool:
    """
    Cette unité disparaît-elle en fin de round, quoi qu'il arrive ?

    UNIQUEMENT Ephemeral, et c'est TOUT L'INTÉRÊT de cette fonction : ne
    pas se confondre avec `death_cost`, qui met aussi Deathless à zéro.
    Les deux morts sont bon marché, elles ne sont pas de même nature :
        - une Éphémère est déjà perdue, l'engager ne coûte RIEN ;
        - une Sans-mort revient — affaiblie à 1 PV, et sa résurrection
          est dépensée. C'est peu cher, ce n'est pas gratuit.

    D'où deux questions séparées : « combien sa mort coûte-t-elle ? »
    (`death_cost`, pour chiffrer un échange) et « sera-t-elle encore là
    au round suivant ? » (ici, pour décider quoi poser, quoi jeter
    devant un attaquant, et quoi renforcer).
    """
    return has(card, "Ephemeral")


# ============================================================
# RÉSOLUTION D'UNE FRAPPE
# ============================================================

class _Fighter:
    """
    L'état d'une unité PENDANT le duel : ses PV fondent, sa barrière se
    brise. La `BoardCard` d'origine n'est jamais modifiée.
    """

    def __init__(self, card):
        self.card = card
        self.health = card.health
        self.barrier = has(card, "Barrier")

    def hit(self, power: int) -> int:
        """
        Encaisse une instance de `power` dégâts, renvoie les dégâts
        RÉELLEMENT infligés (ce que Vol d'âme soigne, et ce dont
        Submersion calcule l'excédent).

        L'ordre compte : la Barrière annule l'instance ENTIÈRE avant que
        Coriace n'ait à retirer quoi que ce soit, et une Barrière se
        brise même sur une frappe qui n'aurait pas tué.
        """
        if power <= 0:
            return 0
        if self.barrier:
            self.barrier = False
            return 0
        dealt = max(0, power - (TOUGH_REDUCTION if has(self.card, "Tough") else 0))
        self.health -= dealt
        return dealt

    @property
    def dead(self) -> bool:
        return self.health <= 0


@dataclass
class Duel:
    """
    Bilan d'un combat singulier, du point de vue de l'ATTAQUANT.

    `overwhelm` et `impact` frappent le nexus du DÉFENSEUR ;
    `attacker_lifesteal` soigne le nexus de l'attaquant, et
    `blocker_lifesteal` celui du bloqueur.
    """

    attacker_dies: bool
    blocker_dies: bool
    overwhelm: int = 0
    impact: int = 0
    attacker_lifesteal: int = 0
    blocker_lifesteal: int = 0

    @property
    def nexus_damage(self) -> int:
        """Tout ce qui atteint le nexus du défenseur malgré le blocage."""
        return self.overwhelm + self.impact


def resolve_duel(attacker, blocker) -> Duel:
    """
    Qui meurt, et qu'est-ce qui passe au nexus ?

    Fonction PURE : aucune carte n'est modifiée, aucune lecture d'écran.

    L'ordre des frappes est le cœur du calcul, et c'est lui que
    l'ancien `attack >= health` ne pouvait pas exprimer :

        1. Frappe Rapide et Frappe Double frappent d'abord, seules.
        2. Le bloqueur ne riposte QUE s'il a survécu à cette frappe.
        3. Les frappes restantes de l'attaquant sont SIMULTANÉES de la
           riposte — une unité qui meurt frappe quand même, on
           n'interrompt donc rien parce que l'attaquant vient de tomber.

    Cas limite assumé : si Frappe Double tue son bloqueur du premier
    coup, sa seconde frappe ne rencontre plus personne. Elle ne va au
    nexus que si l'unité a Submersion. Sept cartes concernées.
    """
    a, b = _Fighter(attacker), _Fighter(blocker)
    power = strike_power(attacker)
    overwhelm = impact = a_heal = b_heal = 0

    def attacker_strike() -> None:
        nonlocal overwhelm, impact, a_heal
        impact += impact_damage(attacker)
        if b.dead:
            # Plus rien en face : seule Submersion continue vers le nexus.
            if has(attacker, "Overwhelm"):
                overwhelm += power
            return
        health_before = b.health
        dealt = b.hit(power)
        if has(attacker, "Lifesteal"):
            a_heal += dealt
        if has(attacker, "Overwhelm"):
            overwhelm += max(0, dealt - health_before)

    def blocker_strike() -> None:
        nonlocal b_heal
        dealt = a.hit(strike_power(blocker))
        if has(blocker, "Lifesteal"):
            b_heal += dealt

    strikes = strike_count(attacker)

    if strikes_before_blocker(attacker):
        attacker_strike()
        strikes -= 1

    if not b.dead:
        blocker_strike()

    for _ in range(strikes):
        attacker_strike()

    return Duel(
        attacker_dies=a.dead,
        blocker_dies=b.dead,
        overwhelm=overwhelm,
        impact=impact,
        attacker_lifesteal=a_heal,
        blocker_lifesteal=b_heal,
    )


# ============================================================
# AFFICHAGE
# ============================================================
# Mots-clés qui changent une décision de combat, dans l'ordre où ils
# comptent. Sert aux commandes de diagnostic (`actions.py block`,
# `actions.py attack`) : voir sur une ligne pourquoi le bot a tranché
# comme il l'a fait vaut mieux que de relire le calcul.
COMBAT_KEYWORDS = (
    "Elusive", "Fearsome", "Overwhelm", "QuickStrike", "DoubleStrike",
    "Barrier", "Tough", "Formidable", "Impact", "Lifesteal",
    "Ephemeral", "Deathless", "CantBlock", "CantAttack", "Immobile",
    "Challenger", "Vulnerable", "SpellShield",
)


def describe(card) -> str:
    """Les mots-clés de combat portés par cette carte, en une ligne."""
    return " ".join(k for k in COMBAT_KEYWORDS if has(card, k))


# ============================================================
# PISTES
# ============================================================
# Ce qui reste ignoré, et pourquoi :
#
#   SpellShield (28) — n'a d'effet que sur le CHOIX DE CIBLE d'un sort,
#       pas sur un combat : à traiter dans `spells.choose_target`.
#   LastBreath (49) — l'effet est écrit dans la description, pas dans
#       le mot-clé. Le quantifier demanderait de comprendre le texte ;
#       le compter comme un bonus fixe serait un chiffre inventé.
#   Fury, Regeneration, Scout, Support — modifient la valeur d'une
#       unité APRÈS le combat, ou selon sa position sur le banc. Rien
#       dans la couche de décision actuelle ne sait raisonner sur un
#       tour suivant.
