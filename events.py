#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
events.py

Tirer parti d'un nœud d'événement au lieu de le fuir.

--------------------------------------------------------------------
LE PROBLÈME
--------------------------------------------------------------------
Jusqu'ici la navigation traitait un nœud d'événement comme un obstacle :
cliquer la première option, chercher « Sélectionner » ou « Quitter »,
repartir. Or beaucoup d'événements OFFRENT quelque chose au deck — et
certains ne se ferment pas sans qu'on ait choisi. Vu par Ewan le
04/09/2026 sur « La Grand-place » : l'option « S'entraîner » ouvre un
panneau « Ajoutez Challenger sur une unité de votre deck » avec trois
cartes ; « Sélectionner » reste grisé tant qu'aucune carte n'est cliquée,
le bot l'a cliqué dans le vide, puis a cherché le nœud suivant derrière
un panneau toujours ouvert (capture screenshots/noeud_introuvable_*).

--------------------------------------------------------------------
L'IDÉE : LIRE CE QU'ON NOUS PROPOSE, CHOISIR, PUIS FERMER
--------------------------------------------------------------------
Une fois l'option cliquée, on tourne en boucle sur l'écran, et à chaque
tour on fait UNE chose, la plus utile que l'écran permet :

    1. des cartes sont proposées (l'API rapporte les rectangles des
       fenêtres de choix, cf. fenetres-de-choix) → on clique la meilleure
       POUR LE DECK, puis « Sélectionner » ;
    2. « Sélectionner » est visible sans qu'on lise de carte → repli
       géométrique : les trois cartes du panneau sont AU-DESSUS du bouton,
       on clique celle du milieu, puis le bouton ;
    3. « Continuer » ou « Quitter » est visible → on ferme ;
    4. une nouvelle option d'événement apparaît → on la prend ;
    5. rien de tout ça et l'écran n'a pas bougé depuis notre dernier geste
       → flèche « retour » en haut à gauche, le seul geste qui sorte de
       n'importe quel panneau. On perd la récompense, pas la tentative.

On s'arrête quand plus rien d'un événement n'est à l'écran, ou après
EVENT_MAX_STEPS gestes. L'écran est GARDÉ à chaque geste de secours :
c'est ce qui permettra de reconnaître le panneau suivant.

--------------------------------------------------------------------
QUELLE CARTE POUR LE DECK
--------------------------------------------------------------------
Le titre du panneau (« Ajoutez Challenger… », « Ajoutez … à votre
deck ») ne se lit pas encore : on ne fait pas d'OCR de texte. La règle
est donc générale : un champion d'abord (il porte le deck), puis l'unité
la plus grosse (un mot-clé ou un bonus profite plus à un gros corps),
puis les cartes connues avant les inconnues. Ce n'est pas la finesse d'un
joueur ; c'est une amélioration à chaque nœud au lieu d'aucune.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import cv2

import keywords
from adventure_navigation import MATCH_THRESHOLD, TEMPLATES, best_match
from click_utils import click_button, human_click, human_delay, park_mouse

# Nombre maximal de gestes pour un événement. Chaque geste est suivi d'une
# relecture : six suffisent à un choix de carte (clic + Sélectionner +
# Continuer) et laissent de la marge pour un second panneau.
EVENT_MAX_STEPS = 8
# Temps laissé au panneau pour se dessiner après un geste.
EVENT_SETTLE = (1.2, 1.8)
# Les boutons d'événement qu'on sait lire, dans l'ordre où on les préfère.
EVENT_CLOSERS = ("continue_button", "quit_button")
EVENT_BUTTONS = ("select_button", "continue_button", "quit_button", "event_option")
# Flèche « retour » en haut à gauche de tous les panneaux (ratio fenêtre).
BACK_ARROW_RATIO = (0.052, 0.079)
# Repli géométrique : la carte du milieu est à la verticale du bouton
# « Sélectionner », cette fraction de la hauteur d'écran au-dessus
# (mesuré sur la capture du 04/09 : bouton y≈1000, cartes y≈380 sur 1080).
CARD_ABOVE_SELECT = 0.575
# Deux cartes proposées ensemble sont à la même hauteur, à ce ratio près.
OFFER_ROW_TOLERANCE = 0.08

# --- LE COFFRE D'OBJETS (04/11/2026) --------------------------------
# Même panneau qu'un événement — trois cartes et un bouton — mais le
# bouton s'appelle « Prendre le trésor ». Faute de ce repère, le bot ne
# voyait que « Quitter » et renonçait à l'objet ET à la copie de carte, à
# chaque coffre : il arrivait au boss final avec un deck jamais amélioré.
TREASURE_BUTTONS = ("take_treasure_button", "continue_button", "quit_button")
# « Quitter » FERME LE COFFRE SANS RIEN PRENDRE : il est lu (pour savoir
# que l'écran n'est pas vide) mais n'est cliqué qu'une fois le trésor
# pris — voir `Panneau.renoncer_sans_prendre`.
TREASURE_CLOSERS = ("continue_button", "quit_button")
# Mesuré sur la capture du 04/11 : « Prendre le trésor » centré en
# (1442, 1002), la carte du milieu à la même verticale, centrée y≈390,
# sur 1080 de haut.
CARD_ABOVE_TAKE = 0.567

# --- LE COFFRE EST UN CHOIX CROISÉ (05/11/2026, Ewan) ---------------
# « Le coffre est sur le champion : il faut cliquer sur un champion ET
# sur le buff qu'on veut lui donner. » Ce n'est donc PAS « trois cartes
# et un bouton » : le panneau porte DEUX rangées, et « Prendre le
# trésor » reste grisé tant que les deux ne sont pas choisies.
#
# Vu en jeu le 05/11 : le bot a cliqué sept fois en (1442, 389) — pile
# dans le VIDE entre les deux cartes de champion (celle de gauche finit
# à x≈1420, celle de droite commence à ≈1470) — puis a abandonné, et
# l'aventure s'est perdue. `CARD_ABOVE_TAKE` avait été mesuré sur une
# capture où le coffre n'était pas encore OUVERT.
#
# Mesures sur captures_reference/coffre_choix_20261105.png (1920×1080,
# bouton en (1442, 1002)) :
#   cartes de champion : centres (1277, 361) et (1615, 371), 298×410
#   objets             : trois cadres de 260 px, centres 1126/1441/1756
#                        à y≈735, espacés de 315
# Le milieu des objets tombe PILE sous le bouton : c'est ce qui rendait
# le clic unique plausible — et faux.
#
# ON PREND CELUI DE GAUCHE dans les deux rangées : sur cette capture la
# carte de gauche est le champion QU'ON JOUE (Teemo, vu en bas à
# gauche), et le coffre offre « une copie supplémentaire de ce
# champion » — autant que ce soit le nôtre. UNE seule observation : à
# revoir au prochain coffre.
CHAMPION_GAUCHE = (-0.0859, -0.5935)
OBJET_GAUCHE = (-0.1641, -0.2472)
# IL Y A PLUSIEURS SORTES DE COFFRES, et le jeu l'ÉCRIT (Ewan). On lit
# donc le titre avant d'appliquer une géométrie : une mise en page par
# titre reconnu, et le clic unique d'origine pour tout titre inconnu.
GESTES_PAR_TITRE = (("coffre_objets_champion", (CHAMPION_GAUCHE, OBJET_GAUCHE)),)

# --- LA RÉCOMPENSE DU BOSS INTERMÉDIAIRE (05/11/2026, Ewan) ---------
# « Après la victoire d'un boss intermédiaire, le bot s'arrête sur la
# sélection d'un objet à équiper à l'un des champions. C'est une
# récompense automatique. » Donc : pas un nœud, pas un coffre — un
# panneau qui s'ouvre tout seul après le combat, là où personne ne
# regardait.
# Même forme que le coffre (deux champions, trois objets, un bouton)
# mais PAS la même géométrie, mesurée sur
# captures_reference/recompense_boss_20261105.png (bouton en (961,1002)) :
#   champions : centres (790, 460) et (1127, 453)
#   objets    : centres (615, 767), (960, 767), (1305, 767)
# Le jeu PRÉSÉLECTIONNE notre champion (celui du bas à gauche) et un
# objet : `resolve_event` tente donc le bouton seul avant ces gestes.
# DEUX ÉTATS DU MÊME BOUTON : doré quand un choix est déjà fait,
# GRISÉ quand rien ne l'est — et c'est l'état grisé qu'on rencontre
# en arrivant. Le 06/11/2026, le gabarit doré n'y notait que 0.42 :
# le bot ne voyait pas le bouton et restait planté sur le panneau.
RECOMPENSE_BUTTONS = ("recompense_select_grise", "recompense_select",
                      "continue_button", "quit_button")
RECOMPENSE_CLOSERS = ("continue_button",)
CHAMPION_RECOMPENSE = (-0.0891, -0.5019)
OBJET_RECOMPENSE = (-0.1802, -0.2176)
RECOMPENSE_GESTES = (("recompense_select_grise",
                      (CHAMPION_RECOMPENSE, OBJET_RECOMPENSE)),
                     ("recompense_select",
                      (CHAMPION_RECOMPENSE, OBJET_RECOMPENSE)))


# COMBIEN DE CHAMPIONS ? ON COMPARE LES DEUX COLONNES CANDIDATES.
# La première version jugeait la luminosité du CENTRE contre un seuil
# absolu (70, « entre 50 en gouttière et 97 sur une carte »). Mesuré le
# 08/11/2026 sur un vrai coffre à trois champions — Rek'Sai, Poppy,
# Aurelion Sol — le centre notait **68.8** : 1.2 sous le seuil, parce
# que la carte du milieu avait une illustration sombre. Le bot a conclu
# « deux cartes », cliqué en (1284, 361) PILE DANS LA GOUTTIÈRE, et
# rejoué le couple sept fois ; le trésor a été perdu et l'aventure
# avec — « boss final introuvable », tentative mensuelle brûlée.
#
# Une luminosité absolue dépend de l'illustration ; un ÉCART entre deux
# colonnes n'en dépend pas. Les deux dispositions placent exactement une
# carte là où l'autre place du vide :
#       trois cartes -> `centre - pas`    est une carte, `centre - pas/2` une gouttière
#       deux cartes  -> `centre - pas/2`  est une carte, `centre - pas`   du décor
# Mesuré sur les 9 captures de référence (coffres et récompenses, deux
# et trois champions) : la comparaison les sépare TOUTES, avec 38 points
# d'écart dans le pire cas, là où le seuil absolu en ratait une.
CHAMPIONS_ECART_MIN = 12.0         # pire écart mesuré : 38.4
# LE COFFRE SUIT LA MÊME LOI (06/11/2026, 20:33) : une fois la
# récompense réparée, il a reproduit l'histoire au geste près — trois
# champions là où la géométrie du 05/11 en supposait deux, et le clic
# dans la gouttière. D'où un RÉGLAGE par panneau plutôt que deux
# fonctions : (centre, pas, haut de bande, bas de bande). Le centre est
# celui du bouton qui valide — mesuré, la rangée est centrée dessus.
#   récompense : bouton 961,  pas 342 -> 790/1127  ou 618/960/1301
#   coffre     : bouton 1442, pas 315 -> 1284/1600 ou 1127/1442/1757
RANGEE_RECOMPENSE = (960, 342, 320, 600)
RANGEE_COFFRE = (1442, 315, 220, 520)


@dataclass(frozen=True)
class Panneau:
    """
    Ce qui change d'un panneau de choix à l'autre.

    Le déroulé est le même — lire l'offre, cliquer une carte, valider,
    fermer — seuls le bouton qui valide, ceux qu'on sait lire et le mot
    écrit au journal diffèrent. D'où un descripteur plutôt qu'une copie
    de `resolve_event`.
    """

    nom: str                   # ce qu'on écrit au journal
    etiquette: str             # préfixe des captures de diagnostic
    valider: str               # le bouton qui prend le choix
    boutons: tuple             # ce qu'on sait lire sur ce panneau
    fermetures: tuple          # ce qui ferme le panneau
    carte_au_dessus: float     # fraction de hauteur : du bouton à la carte
    # À False, une fermeture n'est cliquée qu'APRÈS avoir pris quelque
    # chose : sur un coffre, « Quitter » avant le choix jette le trésor.
    renoncer_sans_prendre: bool = True
    # LE REPLI À L'AVEUGLE EST UNE SUITE DE CLICS, PAS UN CLIC. Un
    # événement n'a qu'une rangée (la carte au-dessus du bouton) ; le
    # coffre d'objets de champion en a DEUX. Chaque entrée associe un
    # TITRE reconnu à ses gestes, en fractions d'écran depuis le bouton
    # qui valide. Titre inconnu : on retombe sur `carte_au_dessus`.
    gestes_par_titre: tuple = ()
    # OÙ TOMBE LE CLIC QUI VALIDE. Vide : sur le repère lui-même (c'est un
    # bouton). Renseigné : à ce décalage du repère — le nœud à options
    # s'ancre sur son INVITE (« Choisissez-en 1. »), parce que son bouton
    # porte le nom de l'option choisie et qu'aucun gabarit de libellé ne
    # le reconnaît. Cliquer l'invite ne validerait rien : c'est du texte.
    valider_decalage: tuple = ()
    # UN BOUTON DORÉ DIT QUE LES CHOIX SONT FAITS (06/11/2026). Sur un
    # panneau à plusieurs clics, recliquer une carte déjà prise la
    # DÉSÉLECTIONNE : il faut donc savoir s'arrêter. Voir
    # `bouton_est_actif` — seule la récompense porte ce signal
    # aujourd'hui, les autres panneaux n'ont pas de bouton qui s'allume.
    bouton_dore_vaut_pret: bool = False
    # LA RANGÉE DES CHAMPIONS N'A PAS TOUJOURS LE MÊME NOMBRE DE CARTES.
    # (centre, pas, haut, bas) — vide quand le panneau n'a pas de rangée
    # de champions. Voir `champion_le_plus_a_gauche`.
    rangee_champions: tuple = ()


EVENEMENT = Panneau("Événement", "evenement", "select_button",
                    EVENT_BUTTONS, EVENT_CLOSERS, CARD_ABOVE_SELECT)
# --- LE NŒUD À OPTIONS (soigneur, 06/11/2026) -----------------------
# « Choisissez-en 1. » : Soins / Acheter des soins / Retirer une carte,
# et un bouton qui porte LE NOM DE L'OPTION CHOISIE — « Soins », pas
# « Sélectionner ». Aucun gabarit de libellé ne le reconnaît : trois
# d'entre eux convergeaient sur (1441, 1002) à 0.75, tous sous le seuil,
# et le bot restait planté sur le nœud puis abandonnait l'aventure.
#
# On s'ancre donc sur l'INVITE, qui est générique, et on valide. Mesuré
# sur captures_reference/soigneur_20261106.png (invite en (716, 721)) :
#   bouton       : dx +0.3776, dy +0.2602
#   1re option   : dx -0.0552, dy +0.0620   (déjà encadrée à l'ouverture)
# La première option est PRÉSÉLECTIONNÉE : valider seul suffit, et le
# repli géométrique ne sert que si le jeu attend vraiment un choix.
# « SÉLECTIONNER » EST DANS LA LISTE, ET C'EST LE POINT DU MÉDECIN
# SINISTRE (06/11/2026) : certains nœuds à options ouvrent un CHOIX DE
# CARTES au lieu de se résoudre seuls. Sans ce repère, on ne savait même
# pas qu'un second panneau attendait. Voir `resolve_event`.
OPTIONS_BUTTONS = ("choisissez_en_un", "select_button",
                   "continue_button", "quit_button")
OPTIONS_CLOSERS = ("continue_button", "quit_button")
OPTION_PREMIERE = (-0.0552, 0.0620)
BOUTON_DEPUIS_INVITE = (0.3776, 0.2602)

NOEUD_OPTIONS = Panneau("Nœud à options", "options", "choisissez_en_un",
                        OPTIONS_BUTTONS, OPTIONS_CLOSERS, -0.0620,
                        gestes_par_titre=(("choisissez_en_un",
                                           (OPTION_PREMIERE,)),),
                        valider_decalage=BOUTON_DEPUIS_INVITE)

RECOMPENSE = Panneau("Récompense", "recompense", "recompense_select_grise",
                     RECOMPENSE_BUTTONS, RECOMPENSE_CLOSERS, 0.5019,
                     renoncer_sans_prendre=False,
                     gestes_par_titre=RECOMPENSE_GESTES,
                     bouton_dore_vaut_pret=True,
                     rangee_champions=RANGEE_RECOMPENSE)
COFFRE = Panneau("Coffre", "coffre", "take_treasure_button",
                 TREASURE_BUTTONS, TREASURE_CLOSERS, CARD_ABOVE_TAKE,
                 renoncer_sans_prendre=False,
                 gestes_par_titre=GESTES_PAR_TITRE,
                 bouton_dore_vaut_pret=True,
                 rangee_champions=RANGEE_COFFRE)


# ============================================================
# LIRE L'OFFRE
# ============================================================

def offered_cards(snapshot) -> list:
    """
    Les cartes qu'un panneau nous propose : au moins deux cartes À NOUS,
    alignées à la même hauteur. Vide si l'API n'en rapporte pas.
    """
    ours = [c for c in snapshot.cards() if c.local]
    if len(ours) < 2:
        return []
    rows: List[list] = []
    for card in sorted(ours, key=lambda c: c.ratio):
        if rows and abs(rows[-1][-1].ratio - card.ratio) <= OFFER_ROW_TOLERANCE:
            rows[-1].append(card)
        else:
            rows.append([card])
    best_row = max(rows, key=len)
    if len(best_row) < 2:
        return []
    return sorted(best_row, key=lambda c: c.center[0])


def deck_pick_rank(card) -> tuple:
    """Plus c'est haut, plus la carte mérite d'entrer (ou d'être renforcée) dans le deck."""
    return (
        1 if getattr(card, "is_leveled", False) else 0,
        1 if getattr(card, "is_champion", False) else 0,
        1 if card.is_unit else 0,
        keywords.unit_value(card) if card.is_unit else 0,
        card.cost,
        1 if card.known else 0,
    )


def choose_deck_card(cards) -> Optional[object]:
    return max(cards, key=deck_pick_rank, default=None)


# ============================================================
# RÉSOUDRE L'ÉVÉNEMENT
# ============================================================

def _fingerprint(screen) -> bytes:
    """L'écran réduit à 32x18 en gris : de quoi dire « rien n'a bougé »."""
    small = cv2.resize(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY), (32, 18), interpolation=cv2.INTER_AREA)
    return small.tobytes()


def _visible(screen, names, threshold=MATCH_THRESHOLD) -> dict:
    """{nom: point} des boutons lisibles sur cette capture."""
    seen = {}
    for name in names:
        score, point = best_match(TEMPLATES[name], screen=screen)
        if score is not None and score >= threshold:
            seen[name] = point
    return seen


def valider(panneau, screen, seen=None):
    """
    Clique ce qui valide ce panneau. Rend True si le clic est parti.

    Le repère n'est pas toujours le bouton : voir `valider_decalage`.
    """
    if not panneau.valider_decalage:
        return bool(click_button(panneau.valider, timeout=4, transition=True))
    point = (seen or {}).get(panneau.valider)
    if point is None:
        point = _visible(screen, (panneau.valider,)).get(panneau.valider)
    if point is None:
        return False
    hauteur, largeur = screen.shape[:2]
    dx, dy = panneau.valider_decalage
    human_click(int(point[0] + dx * largeur), int(point[1] + dy * hauteur))
    human_delay(EVENT_SETTLE)
    return True


# ---- LA RANGÉE DES CHAMPIONS N'A PAS TOUJOURS DEUX CARTES ------------
# 06/11/2026, 20:19 : une récompense à TROIS champions (Sejuani, Aurelion
# Sol, Leona). Le geste mesuré le 05/11 vise (789, 459) — à trois cartes
# c'est PILE LA GOUTTIÈRE entre la première et la deuxième. L'objet était
# pris, le champion non, « Sélectionner » restait grisé, et le bot a
# cliqué dans le vide en boucle. Même bogue que le coffre du 05/11.
#
# LA RANGÉE EST CENTRÉE, À PAS CONSTANT : 790/1127 à deux cartes,
# 617/959/1301 à trois — pas ~340, centre 960 des deux côtés. Le seul
# inconnu est le NOMBRE, et le CENTRE le dit. Mesuré sur les quatre
# captures de référence (luminosité moyenne de la bande y 320-600) :
#       x=960 : 37-50 à deux cartes, 97 à trois.
# On ne devine pas le nombre, on le lit — et seule cette colonne-là est
# fiable : les positions extérieures descendent à 44-62 selon l'éclairage
# de la carte, le centre, lui, sépare de 50 contre 97.


# ---- « C'EST PRÊT » SE LIT À LA COULEUR DU BOUTON --------------------
# 06/11/2026 : un clic sur une carte la SÉLECTIONNE, un second la
# DÉSÉLECTIONNE. Le repli géométrique rejouait la paire à chaque tour —
# et comme ses clics faisaient changer l'écran, le garde `unchanged == 0`
# le relançait indéfiniment. Le panneau oscillait : champion pris / objet
# rendu, champion rendu / objet pris, huit fois. Le bot défaisait ce
# qu'il venait de faire. Même piège que le clic à l'aveugle de
# l'événement, qui annule la présélection — ici il annule la sienne.
#
# LES GABARITS NE SAVENT PAS DIRE SI LE BOUTON EST PRÊT :
# `recompense_select_grise` matche les deux états (1.00 grisé, 0.94
# actif). C'est la COULEUR qui tranche, mesurée sur la bande du bouton :
#       actif : 67 % de pixels orangés ; grisé : 0 %, 0 %, 9 %.
BOUTON_ZONE = (120, 22)            # demi-largeur, demi-hauteur
BOUTON_ORANGE = ((10, 80, 90), (35, 255, 255))
BOUTON_ORANGE_MIN = 0.35           # entre 0.09 (grisé) et 0.67 (actif)


def bouton_est_actif(screen, point) -> bool:
    """Le bouton de validation est-il DORÉ, c'est-à-dire prêt ?"""
    x, y = point
    dx, dy = BOUTON_ZONE
    haut, bas = max(0, y - dy), y + dy
    gauche, droite = max(0, x - dx), x + dx
    zone = screen[haut:bas, gauche:droite]
    if zone.size == 0:
        return False
    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    bas_, haut_ = BOUTON_ORANGE
    return float((cv2.inRange(hsv, bas_, haut_) > 0).mean()) >= BOUTON_ORANGE_MIN


# UNE TUILE DÉJÀ PRISE SE VOIT — ET IL FAUT LA VOIR AVANT DE CLIQUER.
# Mesuré en jeu le 08/11/2026, un clic à la fois, sur le coffre d'objets
# de champion :
#       Rek'Sai seul            -> bouton GRIS
#       + clic sur Grande Massue -> LES DEUX pris, bouton ACTIF
#       re-clic sur Rek'Sai      -> la paire est cassée
# Le jeu PRÉSÉLECTIONNE un champion. Le repli à l'aveugle, lui, cliquait
# toujours les DEUX tuiles : il défaisait donc la présélection à chaque
# tour. Mesuré sur onze captures d'affilée, l'alternance est parfaite —
# champion pris / objet rendu, champion rendu / objet pris — et le
# bouton n'est JAMAIS doré (0 % d'orange sur les onze). Le garde du
# bouton doré ne pouvait pas s'armer : il arrive trop tard.
#
# Une tuile prise s'entoure d'un liseré clair. On le lit À LA HAUTEUR DU
# CLIC, sur les deux bords de la tuile, ce qui évite d'avoir à connaître
# ses bornes verticales : mesuré **255 prise contre 102 libre** sur les
# onze captures du coffre, sans un seul cas intermédiaire.
TUILE_DEMI = 131 / 315.0           # demi-largeur d'une tuile, en pas
TUILE_BORD = 4                     # épaisseur sondée du liseré
TUILE_HAUTEUR = 18                 # hauteur sondée autour du clic
TUILE_PRISE = 250.0                # 255 prise / 102 libre : on reste strict


def tuile_est_prise(screen, point, pas) -> bool:
    """Cette tuile porte-t-elle le liseré d'une tuile déjà choisie ?"""
    x, y = point
    hauteur, largeur = screen.shape[:2]
    demi = int(round(TUILE_DEMI * pas))
    gris = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    haut, bas = max(0, y - TUILE_HAUTEUR), min(hauteur, y + TUILE_HAUTEUR)
    meilleur = 0.0
    for bord in (x - demi, x + demi):
        g, d = max(0, bord - TUILE_BORD), min(largeur, bord + TUILE_BORD)
        if bas <= haut or d <= g:
            continue
        meilleur = max(meilleur, float(gris[haut:bas, g:d].max()))
    return meilleur >= TUILE_PRISE


def champion_le_plus_a_gauche(screen, rangee) -> int:
    """
    L'abscisse du premier champion de la rangée, à deux OU trois cartes.

    On ne juge pas une luminosité contre un seuil : on compare les DEUX
    colonnes possibles, et la plus claire porte la carte (cf.
    `CHAMPIONS_ECART_MIN`). À égalité — ce qu'aucune capture n'a encore
    montré — on garde la disposition à deux cartes, celle d'origine.
    """
    centre, pas, haut, bas = rangee
    bande = cv2.cvtColor(screen[haut:bas, :, :], cv2.COLOR_BGR2GRAY)

    def clarte(x):
        return float(bande[:, max(0, x - 25):x + 25].mean())

    trois, deux = centre - pas, centre - pas // 2
    if clarte(trois) - clarte(deux) >= CHAMPIONS_ECART_MIN:
        return trois                 # trois cartes : la gauche est à un pas
    return deux                      # deux cartes : un demi-pas


def gestes_du_repli(panneau, screen):
    # Les clics du repli à l'aveugle, dans l'ordre, et le nom de la mise
    # en page reconnue. On LIT LE TITRE : il y a plusieurs sortes de
    # coffres et elles n'ont pas la même géométrie. Titre inconnu : on
    # retombe sur le clic unique d'origine, jamais sur une géométrie
    # devinée.
    for cle, gestes in panneau.gestes_par_titre:
        score, _ = best_match(TEMPLATES[cle], screen=screen)
        if score is not None and score >= MATCH_THRESHOLD:
            if panneau.rangee_champions and gestes:
                # Le premier geste vise le champion, et sa colonne dépend
                # du NOMBRE de champions : on la relit à l'écran plutôt
                # que de la tenir pour acquise (cf.
                # `champion_le_plus_a_gauche`). Le reste ne bouge pas —
                # la rangée des objets en a toujours trois.
                rangee = panneau.rangee_champions
                largeur = screen.shape[1]
                dx = (champion_le_plus_a_gauche(screen, rangee)
                      - rangee[0] - 1) / largeur
                gestes = ((dx, gestes[0][1]),) + tuple(gestes[1:])
            return cle, gestes
    return "carte du milieu", ((0.0, -panneau.carte_au_dessus),)


def resolve_event(reader, capture, save_screen, log=None, max_steps=EVENT_MAX_STEPS,
                  panneau: Panneau = EVENEMENT) -> dict:
    """
    Joue un panneau de choix jusqu'à en sortir. Rend un bilan :
    {"picked": [noms], "steps": n, "closed": bool, "escaped": bool}.

    `reader` lit l'API (GameStateReader), `capture` rend l'écran BGR,
    `save_screen(image, etiquette)` garde une image — passés par
    navigate.py pour rester testable sans jeu.

    `panneau` dit de QUEL panneau il s'agit : un événement (le défaut) ou
    un coffre d'objets. Le déroulé ne change pas, seuls les repères.
    """
    say = log if log is not None else logging.info
    result = {"picked": [], "steps": 0, "closed": False, "escaped": False}
    last_print, unchanged = None, 0
    # Une seule option supplémentaire par événement : certaines coûtent
    # (or, PV), et en enchaîner sans lire ce qu'elles disent n'est pas un
    # choix, c'est un tic.
    options_taken = 0
    # LE JEU PRÉSÉLECTIONNE. Sur le panneau des renforts, un paquet est
    # déjà encadré d'or à l'ouverture : valider SUFFIT. Le clic « à
    # l'aveugle » sur la carte du milieu, lui, tombe au-dessus des cartes
    # (mesuré le 05/11/2026 : repère calculé en y=382, cartes à 455, 525,
    # 600) et ANNULE cette présélection — après quoi le bouton devient
    # inerte. Le 05/11 : huit tours sans sortir, tentative perdue au
    # premier nœud ; le même geste avait pourtant marché le matin, en deux
    # tours. C'était un coup de dés, pas une méthode.
    # On tente donc LE BOUTON SEUL d'abord. Inerte s'il manque un choix,
    # il ne coûte qu'un tour ; et il ne peut jamais DÉfaire une sélection,
    # contrairement au clic géométrique.
    validation_seule_tentee = False
    repli_tente = False
    # Le repli a d'abord le droit de SAUTER les tuiles déjà prises ; s'il
    # saute et que rien n'aboutit, le tour suivant reclique tout.
    tout_recliquer = False

    for _ in range(max_steps):
        human_delay(EVENT_SETTLE)
        result["steps"] += 1
        screen = capture()
        print_ = _fingerprint(screen)
        unchanged = unchanged + 1 if print_ == last_print else 0
        last_print = print_

        # 1. Une offre de cartes lue par l'API.
        snapshot = reader.snapshot()
        offer = offered_cards(snapshot)
        if offer:
            card = choose_deck_card(offer)
            say(f"{panneau.nom} : {len(offer)} carte(s) proposée(s) — "
                + ", ".join(c.name for c in offer) + f". On prend {card.name}.")
            human_click(*card.center)
            result["picked"].append(card.name)
            human_delay(EVENT_SETTLE)
            # `seen` n'est lu qu'après cette branche : `valider` relira
            # l'écran lui-même s'il a besoin du repère.
            if not valider(panneau, screen):
                say(f"« {panneau.valider} » introuvable après le choix ; "
                    "on continue à lire l'écran.")
            continue

        seen = _visible(screen, panneau.boutons)

        # 1bis. UN NŒUD À OPTIONS PEUT OUVRIR UN CHOIX DE CARTES.
        #
        # Le Médecin sinistre (vu en jeu le 06/11/2026) : « Choisissez-en
        # 1. » — Recruter une abomination / Suivre ses enseignements /
        # Quitter — mais l'option fait apparaître un panneau de TROIS
        # CARTES à droite, « Sélectionner » grisé tant qu'aucune n'est
        # prise. Le soigneur, lui, se contentait de valider.
        #
        # LE PIÈGE EST QUE L'INVITE RESTE AFFICHÉE À GAUCHE : mesuré sur
        # `captures_reference/medecin_sinistre_20261106.png`,
        # `choisissez_en_un` note 1.00 ET `select_button` 0.94. Le bot
        # rejouait donc le geste des options à l'infini — huit tours,
        # panneau laissé ouvert, puis « nœud 2 introuvable » parce qu'il
        # cherchait derrière le panneau.
        #
        # « Sélectionner » dit que ce n'est plus la colonne de gauche qui
        # attend : on bascule sur le panneau d'ÉVÉNEMENT, qui sait
        # cliquer la carte au-dessus du bouton puis le bouton. Les deux
        # compteurs repartent à zéro — c'est un autre panneau.
        if panneau is NOEUD_OPTIONS and "select_button" in seen:
            say(f"{panneau.nom} : un choix de cartes s'est ouvert "
                "(« Sélectionner » visible) — on le joue comme un événement.")
            panneau = EVENEMENT
            validation_seule_tentee = repli_tente = False
            tout_recliquer = False
            continue

        # 1ter. LE BOUTON EST DÉJÀ DORÉ : les choix sont faits, il ne
        # reste qu'à valider — et surtout PAS à recliquer les cartes, ce
        # qui les désélectionnerait (cf. `bouton_est_actif`). Sans ce
        # garde, le panneau de récompense oscillait huit tours durant.
        if (panneau.bouton_dore_vaut_pret and panneau.valider in seen
                and bouton_est_actif(screen, seen[panneau.valider])):
            say(f"{panneau.nom} : le bouton est doré — les choix sont faits, "
                "on valide sans rien recliquer.")
            valider(panneau, screen, seen)
            result["picked"].append("choix déjà faits")
            continue

        # 2a. Le bouton est là, l'API ne dit rien : VALIDER SEUL d'abord.
        if panneau.valider in seen and not validation_seule_tentee:
            validation_seule_tentee = True
            say(f"{panneau.nom} : « {panneau.valider} » vu sans carte lisible "
                "par l'API ; on valide SEUL d'abord (le jeu présélectionne).")
            valider(panneau, screen, seen)
            continue

        # 2b. Valider seul n'a pas suffi : repli géométrique sur la carte
        #     du milieu, puis le bouton.
        #
        #     LE GARDE N'EST PAS `unchanged == 0` SEUL. Valider sans rien
        #     avoir choisi ne change RIEN à l'écran (bouton grisé) : avec
        #     ce seul garde, le repli n'aurait plus jamais sa chance et on
        #     sortirait par la flèche retour en abandonnant l'événement.
        #     Le repli a donc droit à UN essai même sur un écran figé —
        #     ensuite seulement il se tait.
        if panneau.valider in seen and (unchanged == 0 or not repli_tente):
            repli_tente = True
            x, y = seen[panneau.valider]
            hauteur, largeur = screen.shape[:2]
            mise_en_page, gestes = gestes_du_repli(panneau, screen)
            points = [(int(x + dx * largeur), int(y + dy * hauteur)) for dx, dy in gestes]
            say(f"{panneau.nom} : « {panneau.valider} » vu sans carte lisible par "
                f"l'API ; mise en page « {mise_en_page} », clic(s) en "
                f"{points}, puis le bouton.")
            save_screen(screen, f"{panneau.etiquette}_choix_sans_api")
            # PLUSIEURS CLICS, DANS L'ORDRE : le coffre d'objets de champion
            # demande un champion PUIS un buff, et son bouton reste grisé
            # tant que les deux ne sont pas pris.
            # ON NE RECLIQUE PAS UNE TUILE DÉJÀ PRISE : cela la rend.
            # `tout_recliquer` est la PORTE DE SORTIE — si le tour
            # précédent a sauté des clics sans que le bouton s'allume,
            # c'est que la lecture du liseré s'est trompée, et on
            # reprend l'ancien comportement plutôt que de rester bloqué.
            pas = panneau.rangee_champions[1] if panneau.rangee_champions else 0
            for point in points:
                if (pas and not tout_recliquer
                        and tuile_est_prise(screen, point, pas)):
                    say(f"{panneau.nom} : {point} est déjà pris — on ne le "
                        "reclique pas, cela le rendrait.")
                    continue
                human_click(*point)
                human_delay(EVENT_SETTLE)
            sautes = pas and not tout_recliquer and any(
                tuile_est_prise(screen, point, pas) for point in points)
            valider(panneau, screen, seen)
            tout_recliquer = bool(sautes)
            result["picked"].append(f"{mise_en_page} (sans lecture)")
            continue

        # 3. Fermer ce qui se ferme.
        closer = next((name for name in panneau.fermetures if name in seen), None)
        # SUR UN COFFRE, FERMER AVANT D'AVOIR PRIS, C'EST JETER LE TRÉSOR.
        # « Quitter » est lu pour savoir que l'écran n'est pas vide, mais
        # il n'est cliqué qu'une fois le choix fait — sinon le premier
        # passage, pris pendant que le panneau se dessine encore, le
        # refermerait exactement comme avant le 04/11/2026.
        if closer and not panneau.renoncer_sans_prendre and not result["picked"]:
            closer = None
        if closer:
            say(f"{panneau.nom} : « {closer} » cliqué.")
            human_click(*seen[closer])
            result["closed"] = True
            continue

        # 4. Une autre option d'événement.
        if "event_option" in seen and unchanged == 0 and options_taken < 1:
            say(f"{panneau.nom} : nouvelle option proposée, on la prend.")
            options_taken += 1
            human_click(*seen["event_option"])
            continue

        # 5. Plus rien d'un événement à l'écran : on est sorti.
        if not seen:
            result["closed"] = True
            say(f"{panneau.nom} : plus aucun bouton lisible, on reprend la route.")
            return result

        # 6. Un écran qui ne bouge pas malgré nos gestes : flèche retour.
        say(f"{panneau.nom} : l'écran ne change plus (" + ", ".join(seen)
            + ") — flèche retour.")
        save_screen(screen, f"{panneau.etiquette}_bloque")
        h, w = screen.shape[:2]
        human_click(int(w * BACK_ARROW_RATIO[0]), int(h * BACK_ARROW_RATIO[1]))
        park_mouse()
        result["escaped"] = True

    say(f"{panneau.nom} : {max_steps} gestes sans sortie nette.")
    return result
