#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
champions.py — CHOISIR LE CHAMPION, au lieu de prendre le premier venu.

    python champions.py                  # lit la grille affichée, ne clique rien
    python champions.py <capture.png>    # lit une capture

--------------------------------------------------------------------
POURQUOI CE FICHIER
--------------------------------------------------------------------
`navigate._pick_champion` cliquait `first_champion.png`, c'est-à-dire le
HAUT de la grille. Or la grille est triée **du plus faible au plus
fort** : le bot prenait donc, à chaque tentative, le pire champion du
compte. Mesuré le 05/11/2026 sur la grille d'Ewan — Zoé 1 ★, Nunu 1 ★,
Hecarim 2 ★ en tête, et tout en bas Ahri et Teemo « Fleur spirituelle »
à **7 ★**. Le 04/11, le bot avait joué le défi 2 avec Shen à 1 ★ et fini
à 0/20 PV.

Le même jour, une tentative lancée à la main avec Teemo (7 ★) a donné la
PREMIÈRE VICTOIRE du bot, après 72 combats et zéro victoire avec des
champions à 1-3 ★. Un seul point de mesure, mais il porte.

--------------------------------------------------------------------
CE QU'ON LIT, ET POURQUOI COMME ÇA
--------------------------------------------------------------------
- LES ÉTOILES SE COMPTENT PAR LEUR ORANGE, en chaîne. Un glyphe fait
  23×23 px (aire 141-161) et les étoiles d'une vignette sont espacées de
  **26,0 px** exactement, depuis le x de leur colonne. On suit la chaîne
  et on s'arrête au premier trou.

  C'est ce qui écarte le bruit sans liste d'exceptions : sur Fiddlesticks
  le masque trouve 8 taches oranges, mais les écarts valent
  26, 26, 26, 26, 26, **59.8**, 15.9 — la chaîne casse à la sixième, les
  deux dernières étant l'icône de région. 6 ★, et non 8.

- ON NE COMPTE PAS LES ÉTOILES GRISES. Le nombre d'emplacements n'est
  pas fixe : Soraka affiche 3 oranges + 3 grises, Gnar 3 oranges et RIEN
  derrière. Les grises disent le potentiel restant, pas l'échelle. Un
  garde-fou « pleines + vides = 6 » aurait donc refusé Gnar à tort.

- L'ÉPUISEMENT SE LIT, il ne se déduit pas. Un champion sans tentative
  est grisé et renvoyé en fin de liste, bandeau « TENTATIVES ÉPUISÉES »
  au lieu de « N/3 tentatives » (Ewan, 05/11/2026 — chaque champion ne
  peut servir que TROIS fois par mois). Attention : le grisage NE
  désature PAS ses étoiles — l'étoile de Shen reste détectée jusqu'à une
  saturation de 40. Il faut donc le repère, mesuré à 1.00 sur la vignette
  épuisée contre 0.30 ailleurs.

- ON NE JUGE QUE CE QU'ON VOIT ENTIÈREMENT. Une vignette dont le bandeau
  sort de la zone de grille est ignorée : on ne peut pas savoir si elle
  est épuisée, et elle réapparaîtra entière à un autre cran de
  défilement.

- LE NIVEAU N'EST PAS LU. La pastille est trop petite pour les gabarits
  de `digits.py` (glyphes de 4 et 7 px de large, le cerclage doré entre
  dans le masque). À égalité d'étoiles on prend donc **la dernière
  vignette dans l'ordre de lecture** : la grille étant triée en ordre
  croissant, c'est le plus haut niveau — mesuré chez les 7 ★ : 44, 45,
  45, 50, 50. C'est la seule chose ici qui s'appuie sur l'ordre de la
  liste, et seulement pour départager des égaux ; le CHOIX, lui, vient
  de ce qu'on voit.

- LE SURVOL ABÎME LA LECTURE. La vignette sous le curseur change de
  rendu : Gnar est devenu illisible quand la souris était dessus. On
  gare la souris avant chaque lecture, comme `click_utils.park_mouse` le
  fait déjà ailleurs. Et le jeu IGNORE la molette si le curseur vient
  d'arriver : il faut le poser avant de défiler (sept captures
  identiques, mesuré).

- RIEN DE LISIBLE N'EST PAS UN CHOIX. `choisir_champion` rend False et
  `navigate` retombe sur `first_champion` : le comportement d'avant,
  jamais un clic au hasard.

- ON REGARDE OÙ L'ON EST AVANT DE CONCLURE QUOI QUE CE SOIT. « Palier
  illisible » n'est un fait que sur l'écran du champion ; sur la liste
  des défis, c'est seulement « je ne suis pas là où je crois ». Le
  08/11/2026 à 20:46 le bot a confondu les deux : lecture nulle sur la
  LISTE DES DÉFIS, « on prend le plus étoilé », puis tout le parcours —
  molette comprise, qui fait défiler cette liste — ~75 s et un essai
  d'entrée. `attendre_la_grille` pose la question d'abord.

- ET CE QU'ON A VU EN CHEMIN NE SE JETTE PAS. Quand le bas de la liste
  n'offre que des épuisés, le parcours retient la meilleure jouable
  rencontrée plus haut, revient à SA HAUTEUR, et RELIT avant de
  cliquer — on ne clique jamais une position mémorisée.
"""

from __future__ import annotations

import logging
import sys
import time
from collections import namedtuple
from pathlib import Path

import cv2
import numpy as np

import adventure_navigation as an
import digits
import gestures

try:                                   # la souris n'est pas nécessaire pour LIRE
    import pyautogui
except Exception:                      # noqa: BLE001
    pyautogui = None

# --------------------------------------------------------------------
# Repères, mesurés sur captures_reference/champions_*_20261105.png
# (1920×1080), exprimés en RATIOS de l'écran.
# --------------------------------------------------------------------
# x de la PREMIÈRE étoile de chaque colonne : 148.5, 485.8, 822.8
COLONNES = (0.07734, 0.25302, 0.42854)
PAS_ETOILE = 26.0 / 1920          # l'écart mesuré entre deux étoiles
TOLERANCE_X = 5.0 / 1920          # décalage accepté sur le x d'une colonne

# Un glyphe d'étoile : 23×23 px. L'AIRE dépend de l'état de la vignette —
# 141-156 au repos, 229-233 quand elle est SÉLECTIONNÉE : la surbrillance
# fait « grossir » le glyphe au masque. Avec un plafond à 200, une
# vignette déjà sélectionnée n'était plus lue du tout (5 vignettes au lieu
# de 6, mesuré le 05/11/2026) — et si le meilleur champion était celui
# déjà choisi, le bot le sautait.
# C'est la TAILLE (23×23) qui discrimine, pas l'aire : le bruit des
# illustrations fait 11×14 ou 19×25 et tombe sur le filtre de largeur.
GLYPHE_MIN, GLYPHE_MAX = 20, 27
AIRE_MIN, AIRE_MAX = 120, 260
# LA CHAÎNE SE SUIT SUR LE MASQUE, PAS SUR LES TACHES. En surbrillance,
# deux étoiles voisines se TOUCHENT et fusionnent en une seule tache (une
# de 101×32 mesurée le 05/11/2026) : la vignette sélectionnée rendait
# alors 6 étoiles au lieu de 7. On teste donc la densité d'orange à
# l'endroit attendu. Mesuré : 85 à 107 pixels sur 121 au centre d'une
# étoile, 0 à 9 dans un vide — le seuil est large.
FENETRE_ETOILE = 5        # demi-côté de la fenêtre, en pixels
DENSITE_ETOILE = 50
ORANGE_BAS = (5, 110, 110)
ORANGE_HAUT = (25, 255, 255)

# Au-delà, c'est une lecture aberrante, pas un champion.
MAX_ETOILES = 10

# Le bandeau de tentatives, au-dessus de la vignette, repéré depuis la
# première étoile. Le gabarit mesure 280×40 ; la bande est prise PLUS
# LARGE (311×64) pour que `matchTemplate` ait du jeu — une bande de la
# taille exacte du gabarit n'autorise qu'un seul alignement, et le
# centroïde d'une étoile décalé d'un pixel suffisait alors à faire
# tomber le score sous le seuil. La marge reste loin du bandeau voisin
# (les colonnes sont à 337 px, les rangées à 296).
BANDEAU_DX = (-68.0 / 1920, 243.0 / 1920)
BANDEAU_DY = (-252.0 / 1080, -188.0 / 1080)
EPUISE = "champion_epuise"
SEUIL_EPUISE = 0.80

# La grille commence sous le champ « Chercher ». Une vignette dont le
# bandeau remonte au-dessus n'est pas jugeable : on l'ignore.
GRILLE_HAUT = 0.29

# Le centre cliquable de la vignette, depuis sa première étoile.
CLIC_DX = 88.0 / 1920
CLIC_DY = -95.0 / 1080

# DÉFILEMENT. Un cran de molette vaut ~26 px et une rangée de vignettes
# fait 296 px : il faut donc ~11 crans pour avancer d'UNE rangée. La
# première version défilait de 3 crans par tour — 78 px — et 20 tours ne
# couvraient que cinq rangées : « 20 écrans parcourus sans atteindre le
# bas » (05/11/2026), lecture partielle, repli sur l'ancien choix.
CRANS_PAR_RANGEE = 11
# On descend par bonds, sans lire : seul le bas nous intéresse.
CRANS_PAR_BOND = 44
MAX_BONDS = 30
# Puis on remonte rangée par rangée tant qu'on n'a rien de jouable.
MAX_RANGEES_REMONTEES = 6
POSE_AVANT_MOLETTE = 0.6
POSE_APRES_MOLETTE = 1.1
# Le temps laissé au jeu pour redessiner la vignette que le curseur
# vient de quitter, avant de photographier. C'est le prix fixe d'un coup
# d'œil : nommé plutôt qu'enfoui dans `_capture_garee`, pour que le coût
# d'une confirmation de plus se CALCULE au lieu de s'estimer
# (cf. CONFIRMATIONS_AUTRE_ECRAN).
POSE_AVANT_CAPTURE = 0.5
POINT_MOLETTE = (0.3125, 0.648)       # (600, 700)
POINT_GARE = (0.599, 0.972)           # (1150, 1050), hors grille

# --- LE PALIER (brique 2) -------------------------------------------
# 70 défis, débloqués un par un : « le premier » est le palier courant,
# et sa difficulté monte tout le mois. Le titre « DÉFI N » est en haut
# du panneau de droite.
TITRE_X = (0.6406, 0.7812)        # 1230..1500 sur 1920
TITRE_Y = (0.1204, 0.1944)        # 130..210 sur 1080
TITRE_SEUIL = 120                 # clarté d'un glyphe du titre
TITRE_AIRE_MIN = 120
# UN VRAI TITRE A DES GLYPHES DE TAILLE RÉGULIÈRE. Mesuré : « DÉFI 6 »
# donne (17,35), (14,35), (14,35), (4,35), (15,36) — hauteurs identiques,
# largeurs modestes. Sur un écran QUI N'EST PAS CELUI DU CHAMPION, le
# seuil de clarté attrape des morceaux de décor : (126,79), (140,19),
# (63,29) le 06/11/2026, à 00:12 — le bot venait de cliquer le défi et
# l'écran n'était pas encore arrivé. Il a conclu « palier illisible »
# AUSSITÔT, donc aucune cible, donc « le plus étoilé » : un 7 étoiles
# dépensé pour un palier qui en demande 3.
# Sans ce garde-fou, `attendre_palier` ne sert à rien : il ne réessaie
# que tant que la lecture échoue, et celle-là ne « échouait » pas.
TITRE_GLYPHE_MAX = (30, 45)        # largeur, hauteur d'un glyphe de titre
TITRE_HAUTEUR_ECART = 4            # tolérance sur la hauteur commune
# Le titre est DORÉ, et `digits.glyph_mask` exclut l'orange à dessein
# (jeton d'attaque, gemme de mana) : il faut blanchir avant de lire,
# exactement comme les PV du bilan. Mesuré : sans ça, « 2 » est illisible.
DORE_BAS = (5, 60, 60)
DORE_HAUT = (40, 255, 255)
PALIER_MAX = 70
TITRE_POLICE = ("defi", "defi2")  # cf. digits.RESERVED_FAMILIES
# OÙ L'ON GARDE L'ÉCRAN QUAND LE PALIER NE SE LIT PAS. Même dossier et
# même forme de nom que `combat.save_stuck_screen` et
# `actions.journaliser_pile_bloquee` : un préfixe qui dit la panne, puis
# l'horodatage.
DOSSIER_CAPTURES = Path(__file__).resolve().parent / "screenshots"
ETIQUETTE_PALIER_ILLISIBLE = "palier_illisible"
# LE TITRE N'EST PAS LÀ TOUT DE SUITE. Mesuré en jeu le 05/11/2026 : la
# lecture tombait 1,8 s après le clic sur le défi, l'écran n'étant pas
# encore dessiné — « palier illisible », et la table d'allocation ne
# s'appliquait pas du tout. Même piège que `SUPPORT_CHAMPION_SETTLE`
# dans navigate : le panneau s'affiche avant son contenu. On REGARDE
# quelques secondes au lieu de juger une seule image.
ATTENTE_PALIER = 8.0
# Après un clic sur un défi, l'écran du champion met plusieurs secondes à
# ARRIVER — et entre-temps on voit encore l'écran d'avant. On attend donc
# LA GRILLE avant de lire quoi que ce soit (cf. `attendre_la_grille`).
ATTENTE_ECRAN_CHAMPION = 20.0
INTERVALLE_PALIER = 0.8

# --- SOMMES-NOUS SEULEMENT SUR LA GRILLE ? (08/11/2026) -------------
# « PALIER ILLISIBLE » N'EST UN FAIT QUE SUR L'ÉCRAN DU CHAMPION. Le
# 08/11 à 20:46, `choisir_champion` a été appelé alors que l'écran
# affichait encore LA LISTE DES DÉFIS (capture gardée :
# `captures_reference/liste_defis_20261108.png`). Le titre « DÉFI N »
# n'y existe pas — zone de titre 79×270, ZÉRO boîte — donc lecture
# nulle, donc « on prend le plus étoilé », puis tout le parcours de
# grille s'est déroulé sur la liste, MOLETTE COMPRISE, qui fait défiler
# cette liste. ~75 s et un essai d'entrée perdus.
#
# Ce qu'on mesure pour trancher, sur les captures déjà gardées :
#
#   capture                           vignettes  first_champion  active_encounter
#   champions_haut_20261105               6         1.000            0.386
#   champions_bas_20261105                6         0.985            0.286
#   champions_selection_20261105          6         0.978            0.304
#   champions_defi19_20261108 (défilée)   6         0.641            0.329
#   liste_defis_20261108                  0         0.502            0.957
#
# LES VIGNETTES PORTENT LA RÉPONSE (6 contre 0) ; `first_champion` ne
# suffit PAS seul — une grille DÉFILÉE n'en montre plus le haut et
# tombe à 0.641 pour un seuil de 0.80 — mais il ne monte jamais à 0.80
# ailleurs (≤ 0.526 sur les cinq autres captures de référence) : c'est
# donc un second témoin sans faux positif, qui rattrape une grille dont
# aucune vignette ne serait lisible.
GRILLE = "first_champion"
SEUIL_GRILLE = an.MATCH_THRESHOLD      # 0.80, celui de navigate
# ET LA LISTE SE DÉNONCE ELLE-MÊME : chaque écran d'entrée est signé par
# un bouton unique (`navigate.SCREEN_ANCHORS`). On garde ceux qui NE
# PEUVENT PAS apparaître sur la grille — mesurés ≤ 0.422 sur les quatre
# captures de grille. `use_attempt` en est EXCLU à dessein : il note
# **1.00** sur `champions_selection_20261105.png`, parce que le bouton
# « UTILISER UNE TENTATIVE » s'affiche à côté de la grille dès qu'un
# champion est sélectionné. Le prendre pour « un autre écran » ferait
# abandonner la grille au moment précis où elle est prête.
AUTRES_ECRANS = ("active_encounter", "monthly_challenge", "reprendre_aventure")
# MAIS UN SEUL COUP D'ŒIL NE SUFFIT PAS À CONCLURE « MAUVAIS ÉCRAN ».
# `_pick_champion` est appelé JUSTE APRÈS le clic sur le défi, et l'écran
# d'avant — la LISTE — est précisément un membre de cette liste-ci. Le
# garde se retournerait alors contre ce qu'il protège : rendre la main
# renvoie à `first_champion`, c'est-à-dire au HAUT de la grille, donc au
# PIRE champion du compte (Shen 1 ★, 0/20 PV le 04/11) — l'erreur même
# pour laquelle ce fichier existe.
# Mesuré dans les journaux des 05, 06 et 08/11 : sur les sept transitions
# où le palier a été lu, « Palier N » tombe 2,05 à 2,28 s après le clic,
# donc le premier coup d'œil (~1,5 s) voyait déjà la grille. Rien ne
# garantit ce 1,5 s. On exige donc de REVOIR l'autre écran : ~1,3 s de
# plus le jour où c'est vraiment le mauvais écran, contre les ~75 s que
# le garde fait économiser — et zéro seconde quand tout va bien, puisque
# `sur_la_grille` répond avant.
CONFIRMATIONS_AUTRE_ECRAN = 2

# LA TABLE D'ALLOCATION (Ewan, 05/11/2026). Trois tentatives par
# champion et par mois, 70 paliers : dépenser les 7 étoiles en bas de
# l'échelle, c'est arriver en haut avec des 3. Et les 1-2 étoiles ne
# gagnent pas, même au palier 1 — d'où le plancher.
# Table de DÉPART, à corriger par `python journal.py --champions` : ce
# sont les parties qui règlent ces nombres, pas l'intuition.
ETOILES_PLANCHER = 3
ETOILES_PLAFOND = 7
PALIERS_PAR_ETOILE = 14           # 70 paliers / 5 marches


def etoiles_requises(palier):
    """Combien d'étoiles viser pour ce palier. None si on l'ignore."""
    if palier is None:
        return None
    marche = (int(palier) - 1) // PALIERS_PAR_ETOILE
    return min(ETOILES_PLAFOND, ETOILES_PLANCHER + max(0, marche))


Vignette = namedtuple("Vignette", "etoiles x y epuisee clic")

# Le dernier champion retenu, pour que la TENTATIVE puisse le
# journaliser. Même procédé que `actions.STRATEGY` : un module porte
# l'état de la partie en cours, plutôt que de le faire transiter par
# cinq signatures. Remis à None à chaque nouveau choix.
DERNIER_CHOIX = None
DERNIER_PALIER = None


# --------------------------------------------------------------------
# Lecture — fonctions pures, une image en entrée
# --------------------------------------------------------------------
def _masque_orange(ecran):
    """Les pixels oranges de l'écran : le matériau des étoiles."""
    hsv = cv2.cvtColor(ecran, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, ORANGE_BAS, ORANGE_HAUT)


def _taches_orange(ecran, masque=None):
    """Les glyphes d'étoile : taches oranges de la bonne taille."""
    masque = _masque_orange(ecran) if masque is None else masque
    nombre, _, stats, centres = cv2.connectedComponentsWithStats(masque, 8)
    taches = []
    for i in range(1, nombre):
        largeur = stats[i][cv2.CC_STAT_WIDTH]
        hauteur = stats[i][cv2.CC_STAT_HEIGHT]
        aire = stats[i][cv2.CC_STAT_AREA]
        if (AIRE_MIN <= aire <= AIRE_MAX
                and GLYPHE_MIN <= largeur <= GLYPHE_MAX
                and GLYPHE_MIN <= hauteur <= GLYPHE_MAX):
            taches.append((float(centres[i][0]), float(centres[i][1])))
    return taches


def _chaine(masque, depart_x, y, pas):
    """
    Combien d'étoiles s'enchaînent depuis `depart_x`, de `pas` en `pas`.

    On interroge le MASQUE et non les taches : en surbrillance les
    glyphes se touchent et fusionnent, ce qui cassait la chaîne.
    """
    hauteur, largeur = masque.shape[:2]
    compte = 1
    while compte < MAX_ETOILES:
        cx = int(depart_x + compte * pas)
        cy = int(y)
        x0, x1 = max(0, cx - FENETRE_ETOILE), min(largeur, cx + FENETRE_ETOILE + 1)
        y0, y1 = max(0, cy - FENETRE_ETOILE), min(hauteur, cy + FENETRE_ETOILE + 1)
        fenetre = masque[y0:y1, x0:x1]
        if fenetre.size == 0 or int((fenetre > 0).sum()) < DENSITE_ETOILE:
            break
        compte += 1
    return compte


_TAILLE_BANDEAU = None


def _taille_du_bandeau():
    """La taille du gabarit « TENTATIVES ÉPUISÉES », lue une seule fois."""
    global _TAILLE_BANDEAU
    if _TAILLE_BANDEAU is None:
        gabarit = cv2.imread(an.TEMPLATES[EPUISE], cv2.IMREAD_UNCHANGED)
        _TAILLE_BANDEAU = (0, 0) if gabarit is None else gabarit.shape[:2]
    return _TAILLE_BANDEAU


def _est_epuisee(ecran, x1, y):
    """Le bandeau « TENTATIVES ÉPUISÉES » au-dessus de cette vignette."""
    hauteur, largeur = ecran.shape[:2]
    x0 = int(x1 + BANDEAU_DX[0] * largeur)
    x2 = int(x1 + BANDEAU_DX[1] * largeur)
    y0 = int(y + BANDEAU_DY[0] * hauteur)
    y2 = int(y + BANDEAU_DY[1] * hauteur)
    if x0 < 0 or y0 < 0 or x2 > largeur or y2 > hauteur:
        return None                     # on ne voit pas le bandeau en entier
    if y0 < GRILLE_HAUT * hauteur:
        return None                     # au-dessus de la grille : pas jugeable
    bande = ecran[y0:y2, x0:x2]
    # UNE BANDE PLUS PETITE QUE SON GABARIT N'EST PAS UNE LECTURE, C'EST
    # UNE EXCEPTION. `matchTemplate` lève (-215) quand l'image est plus
    # petite que le motif, et les repères d'ici sont des RATIOS : sur une
    # capture moins large que 1920 la bande rétrécit et le gabarit, lui,
    # garde ses 280×40. Mesuré en rejouant les 935 captures du projet :
    # `diag_scroll_apres.png` (1113×767) fait planter `lire_vignettes`.
    # Depuis le 08/11 cette fonction est atteinte par `sur_la_grille`,
    # donc par N'IMPORTE QUEL écran — le cas n'est plus théorique. C'est
    # exactement le sens déjà écrit deux lignes plus haut : on ne voit
    # pas le bandeau en entier, on ne juge pas.
    h_gabarit, l_gabarit = _taille_du_bandeau()
    if bande.shape[0] < h_gabarit or bande.shape[1] < l_gabarit:
        return None
    score, _ = an.best_match(an.TEMPLATES[EPUISE], screen=bande)
    return score is not None and score >= SEUIL_EPUISE


def lire_vignettes(ecran):
    """
    Les vignettes lisibles de la grille, dans l'ORDRE DE LECTURE
    (de haut en bas, de gauche à droite).

    Une vignette dont on ne peut pas voir le bandeau entier est écartée :
    on ne saurait pas si elle est encore jouable.
    """
    if ecran is None or ecran.size == 0 or min(ecran.shape[:2]) < 80:
        return []
    hauteur, largeur = ecran.shape[:2]
    masque = _masque_orange(ecran)
    taches = _taches_orange(ecran, masque)
    pas = PAS_ETOILE * largeur
    tol_x = TOLERANCE_X * largeur

    vues = []
    for colonne in COLONNES:
        x1 = colonne * largeur
        for tache in [t for t in taches if abs(t[0] - x1) <= tol_x]:
            y = tache[1]
            epuisee = _est_epuisee(ecran, x1, y)
            if epuisee is None:
                continue
            etoiles = _chaine(masque, x1, y, pas)
            if not 1 <= etoiles <= MAX_ETOILES:
                logging.warning("Grille des champions : %d étoiles lues en "
                                "(%.0f, %.0f) — lecture refusée.", etoiles, x1, y)
                continue
            vues.append(Vignette(
                etoiles=etoiles, x=int(x1), y=int(y), epuisee=epuisee,
                clic=(int(x1 + CLIC_DX * largeur), int(y + CLIC_DY * hauteur)),
            ))
    vues.sort(key=lambda v: (v.y, v.x))
    return vues


def _boites_claires(zone):
    """
    Les boîtes claires de la bande du titre, de gauche à droite, AVANT
    le garde-fou de hauteur.

    Séparée de `_glyphes_du_titre` pour que le diagnostic puisse dire
    ce que la bande contenait quand le lot a été REFUSÉ — « zéro boîte »
    et « des boîtes dépareillées » sont deux pannes différentes, et les
    confondre nous laisserait aussi démunis qu'avant.
    """
    gris = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
    _, masque = cv2.threshold(gris, TITRE_SEUIL, 255, cv2.THRESH_BINARY)
    nombre, _, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    return sorted((int(stats[i][0]), int(stats[i][1]), int(stats[i][2]), int(stats[i][3]))
                  for i in range(1, nombre)
                  if stats[i][cv2.CC_STAT_AREA] >= TITRE_AIRE_MIN
                  and stats[i][cv2.CC_STAT_WIDTH] <= TITRE_GLYPHE_MAX[0]
                  and stats[i][cv2.CC_STAT_HEIGHT] <= TITRE_GLYPHE_MAX[1])


def _bande_du_titre(ecran):
    """La bande où vit « DÉFI N », ou None si elle ne tient pas ici."""
    hauteur, largeur = ecran.shape[:2]
    x0, x1 = int(TITRE_X[0] * largeur), int(TITRE_X[1] * largeur)
    y0, y1 = int(TITRE_Y[0] * hauteur), int(TITRE_Y[1] * hauteur)
    if x1 <= x0 or y1 <= y0:
        return None
    return ecran[y0:y1, x0:x1]


def _glyphes_du_titre(ecran):
    """Les boîtes claires du titre, de gauche à droite."""
    zone = _bande_du_titre(ecran)
    if zone is None:
        return None, []
    boites = _boites_claires(zone)
    # Les lettres d'un titre partagent leur hauteur. Un lot dépareillé
    # n'est pas un titre : c'est du décor, et on ne lit rien dedans.
    if len(boites) >= 2:
        hauteurs = [b[3] for b in boites]
        if max(hauteurs) - min(hauteurs) > TITRE_HAUTEUR_ECART:
            return zone, []
    return zone, boites


def _nombre_du_titre(ecran):
    """
    La vignette du NOMBRE de « DÉFI N », dorure blanchie — telle que
    `digits` la lira — et les boîtes claires de la bande du titre.

    Rend `(crop, boites)` ; `crop` vaut None quand il n'y a rien à
    découper, et `boites` dit toujours ce que la bande contenait.

    SOURCE UNIQUE, ET C'EST DÉLIBÉRÉ : `lire_palier` DÉCIDE dessus,
    `_diagnostic_du_titre` EXPLIQUE dessus. Deux découpages du même
    nombre finiraient par diverger, et c'est alors le diagnostic qui
    mentirait — exactement le défaut payé deux fois ailleurs
    (`actions._describe`, `etat_des_sorts`).
    """
    zone, boites = _glyphes_du_titre(ecran)
    if zone is None or len(boites) < 2:
        return None, (boites or [])
    # On sépare le NOMBRE des lettres par le plus grand écart horizontal :
    # mesuré, les lettres sont espacées de 6-7 px et le nombre de 21.
    ecarts = [boites[i + 1][0] - (boites[i][0] + boites[i][2])
              for i in range(len(boites) - 1)]
    coupe = ecarts.index(max(ecarts)) + 1
    nombre = boites[coupe:]
    if not nombre:
        return None, boites
    x0 = min(b[0] for b in nombre); x1 = max(b[0] + b[2] for b in nombre)
    y0 = min(b[1] for b in nombre); y1 = max(b[1] + b[3] for b in nombre)
    marge = 3
    crop = zone[max(0, y0 - marge):y1 + marge, max(0, x0 - marge):x1 + marge].copy()
    if crop.size == 0:
        return None, boites
    # Le titre est DORÉ et `digits.glyph_mask` exclut l'orange à dessein :
    # sans ce blanchiment, le chiffre est tout simplement invisible.
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    crop[cv2.inRange(hsv, DORE_BAS, DORE_HAUT) > 0] = (255, 255, 255)
    return crop, boites


def lire_palier(ecran):
    """
    Le numéro du défi affiché, ou None.

    La police du titre n'est pas celle des coûts : elle vit dans
    `chiffres/N_defi.png`, amorcée avec le « 2 » du 05/11/2026 et
    complétée au fil des paliers (`python champions.py cut-defi`). Un
    chiffre absent de cette police rend None — jamais une valeur
    approchée.
    """
    crop, _ = _nombre_du_titre(ecran)
    if crop is None:
        return None
    # La police du titre est À PART : on ne lui mêle pas celle des
    # badges, et on ne pollue pas les badges avec la sienne.
    return digits.read_number(crop, maximum=PALIER_MAX, families=TITRE_POLICE)


def _diagnostic_du_titre(ecran):
    """
    CE QUE LA LECTURE DU TITRE A VU — en lignes, prêtes à journaliser.

    Fonction PURE : une image en entrée, du texte en sortie. Ni souris,
    ni disque, ni capture — c'est ce qui permet de la vérifier hors
    ligne, et c'est pour ça qu'elle est séparée du guet qui photographie.

    « ILLISIBLE » MUET EST PRÉCISÉMENT CE QU'ON REPROCHE AU 11/11 : le
    log disait « police incomplète » sans rien montrer, alors que les
    deux chiffres du palier 25 étaient dans la police. On rend donc les
    mêmes grandeurs que `digits.read_number(debug=True)` — combien de
    boîtes dans la bande du titre, puis pour chaque glyphe du nombre son
    meilleur chiffre, son score et sa MARGE au barème de
    `digits.match_glyph`. Les deux planchers à comparer sont
    `digits.CONFIDENT_SCORE` / `CONFIDENT_MARGIN` : c'est par eux que
    `read_number` refuse un candidat.
    """
    if ecran is None or getattr(ecran, "size", 0) == 0:
        return ["écran vide : rien à lire."]
    hauteur, largeur = ecran.shape[:2]
    lignes = [f"écran {largeur}×{hauteur}, bande du titre "
              f"x {TITRE_X[0]:.4f}-{TITRE_X[1]:.4f} / "
              f"y {TITRE_Y[0]:.4f}-{TITRE_Y[1]:.4f}"]
    zone = _bande_du_titre(ecran)
    brutes = _boites_claires(zone) if zone is not None else []
    lignes.append(f"{len(brutes)} boîte(s) claire(s) dans la bande"
                  + (" : " + ", ".join(f"{b[2]}×{b[3]} en x={b[0]}" for b in brutes)
                     if brutes else " — aucun glyphe à découper."))
    crop, boites = _nombre_du_titre(ecran)
    if brutes and not boites:
        # ZÉRO BOÎTE ET DES BOÎTES DÉPAREILLÉES SONT DEUX PANNES. Le
        # garde-fou de hauteur écarte le décor (06/11/2026) ; s'il écarte
        # un vrai titre, c'est ici qu'on le verra.
        hauteurs = [b[3] for b in brutes]
        lignes.append(f"lot REFUSÉ par le garde-fou de hauteur : "
                      f"{min(hauteurs)}-{max(hauteurs)} px pour un écart "
                      f"toléré de {TITRE_HAUTEUR_ECART}.")
    if crop is None:
        lignes.append("aucun nombre à lire : pas de titre « DÉFI N » ici, "
                      "ou des glyphes dépareillés (décor).")
        return lignes
    lignes.append(f"nombre découpé : {crop.shape[1]}×{crop.shape[0]} px "
                  f"(dorure blanchie), police {TITRE_POLICE}")
    masque = digits.glyph_mask(crop)
    composantes = digits.glyph_boxes(masque)
    lignes.append(f"{len(composantes)} glyphe(s) au masque de digits "
                  f"(plancher sûr : score {digits.CONFIDENT_SCORE}, "
                  f"marge {digits.CONFIDENT_MARGIN})")
    for x, y, w, h, composante in composantes:
        chiffre, score, marge = digits.match_glyph(composante, families=TITRE_POLICE)
        lu = "aucun" if chiffre is None else str(chiffre)
        sur = (chiffre is not None and score >= digits.CONFIDENT_SCORE
               and marge >= digits.CONFIDENT_MARGIN)
        lignes.append(f"  glyphe {w}×{h} en x={x} -> {lu} "
                      f"(score {score:.3f}, marge {marge:.3f})"
                      + ("" if sur else "  <- pas une lecture SÛRE"))
    return lignes


# Le dernier écran que `attendre_palier` a regardé. On garde CELUI-LÀ
# plutôt que d'en reprendre un : entre l'échec et le diagnostic il se
# passe une demi-seconde, et photographier plus tard, c'est le défaut
# mesuré le 11/11 sur `journaliser_pile_bloquee` — « la capture est
# prise APRÈS le geste, elle ne sert à rien ».
DERNIER_ECRAN_TITRE = None


def journaliser_palier_illisible(ecran=None):
    """
    Garde l'écran et dit ce qu'on y a lu, quand le palier ne se lit pas.

    LA CAPTURE EST LE VRAI LIVRABLE (leçon du 08/11/2026, redite le
    11/11). Ce jour-là à 13:09:27 : « Palier illisible alors que la
    grille EST affichée (police incomplète) », puis un **7 ★** engagé
    là où `etoiles_requises(25)` demande **4 ★** — sur trois tentatives
    par champion et par mois. Le palier était 25, et le 2 comme le 5
    sont dans `chiffres/N_defi.png` : la cause annoncée était une
    SUPPOSITION, et personne ne pouvait la vérifier, faute d'image.

    ET C'EST AUSSI LA SEULE FAÇON DE RÉCOLTER LE 0 ET LE 8, qui
    manquent toujours à la police du titre (aucun titre « DÉFI N » du
    dépôt n'en porte, 16 077 PNG relus le 10/11). Sur une capture
    gardée ici :
        python champions.py cut-defi <N> [capture x0 y0 x1 y1]

    SEUL POINT QUI TOUCHE L'ÉCRAN ET LE DISQUE sur ce chemin — un
    bouchon par COUTURE, pas un par appelant : c'est cette fonction que
    les suites remplacent, et rien d'autre.

    Rend le chemin, ou "" : un diagnostic ne doit jamais faire tomber le
    choix du champion.
    """
    if ecran is None:
        ecran = DERNIER_ECRAN_TITRE
    if ecran is None:
        ecran = _capture_garee()
    logging.warning("Palier illisible — ce que la lecture du titre a VU :")
    for ligne in _diagnostic_du_titre(ecran):
        logging.warning("  %s", ligne)
    try:
        DOSSIER_CAPTURES.mkdir(exist_ok=True)
        chemin = (DOSSIER_CAPTURES /
                  f"{ETIQUETTE_PALIER_ILLISIBLE}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        cv2.imwrite(str(chemin), ecran)
        return str(chemin)
    except Exception as exc:      # noqa: BLE001 — le diagnostic ne plante rien
        logging.warning("Capture du palier illisible impossible : %s", exc)
        return ""


def attendre_palier(timeout=ATTENTE_PALIER, intervalle=INTERVALLE_PALIER):
    """
    Le palier, en laissant au panneau le temps de SE DESSINER.

    Le 05/11 la lecture tombait 1,8 s après le clic sur le défi, avant
    que le panneau soit dessiné : « illisible » tout de suite, donc
    aucune cible, donc un 7 étoiles dépensé sur un palier qui en
    demandait 3. On REGARDE quelques secondes au lieu de juger une seule
    image.

    L'autre attente — celle de l'écran du champion lui-même, qui met
    plusieurs secondes à ARRIVER — a été sortie d'ici le 08/11/2026 :
    c'est `attendre_la_grille`, et elle se pose la question dans l'ordre.
    Tant qu'on ne SAIT PAS si la grille est affichée, « illisible » ne
    veut rien dire.
    """
    global DERNIER_ECRAN_TITRE
    DERNIER_ECRAN_TITRE = None
    fin = time.time() + timeout
    while True:
        ecran = _capture_garee()
        # L'ÉCRAN QUI A ÉCHOUÉ EST CELUI QU'IL FAUDRA REGARDER, pas un
        # suivant : on le garde sous la main pour
        # `journaliser_palier_illisible`.
        DERNIER_ECRAN_TITRE = ecran
        palier = lire_palier(ecran)
        if palier is not None:
            return palier
        if time.time() >= fin:
            return None
        time.sleep(intervalle)


def sur_la_grille(ecran):
    """
    Cet écran EST-IL celui du champion ?

    Deux témoins, et le premier suffit presque toujours : une grille de
    champions montre des VIGNETTES, fût-ce des épuisées ; un autre écran
    n'en montre aucune (6 contre 0 sur les cinq captures de référence).

    Le second rattrape le cas où aucune vignette ne serait lisible —
    rangée coupée, animation : `first_champion`, le repère de
    `Screen.CHAMPION`. Il ne vaut qu'en POSITIF (0.641 sur une grille
    défilée, sous le seuil), jamais en négatif.
    """
    if ecran is None or getattr(ecran, "size", 0) == 0:
        return False
    if lire_vignettes(ecran):
        return True
    gabarit = an.TEMPLATES.get(GRILLE)
    if gabarit is None:
        return False
    score, _ = an.best_match(gabarit, screen=ecran)
    return bool(score is not None and score >= SEUIL_GRILLE)


def autre_ecran(ecran):
    """
    Le nom de l'écran d'entrée reconnu ici, s'il y en a un — sinon None.

    Sert à ne pas ATTENDRE vingt secondes une grille qui ne viendra pas :
    quand la liste des défis se dénonce à 0.957, on rend la main tout de
    suite. À n'interroger qu'après `sur_la_grille`, jamais à sa place.
    """
    if ecran is None or getattr(ecran, "size", 0) == 0:
        return None
    for nom in AUTRES_ECRANS:
        gabarit = an.TEMPLATES.get(nom)
        if gabarit is None:
            continue
        score, _ = an.best_match(gabarit, screen=ecran)
        if score is not None and score >= SEUIL_GRILLE:
            return nom
    return None


def attendre_la_grille(timeout=ATTENTE_ECRAN_CHAMPION, intervalle=INTERVALLE_PALIER):
    """
    Attend que l'écran du champion soit là — et dit si on y est.

    ON REGARDE OÙ L'ON EST AVANT DE CONCLURE QUOI QUE CE SOIT. C'est la
    même leçon que la molette du 08/11 : « rien n'a bougé » ne veut dire
    « on est au bout » que si le geste est parti ; « le titre ne se lit
    pas » ne veut dire « palier illisible » que si le titre est là.

    Trois issues, et elles ne se confondent plus :
      - la grille est là : True, et le reste du travail a un sens ;
      - un AUTRE écran d'entrée est reconnu DEUX FOIS de suite : on rend
        la main sans user les secondes d'attente. Deux fois, parce que
        l'écran d'avant est justement un de ceux-là et qu'une
        transition en cours n'est pas un mauvais écran ;
      - rien de reconnaissable : on laisse à l'écran le temps d'arriver
        (il met plusieurs secondes après le clic sur le défi), puis on
        rend la main. Jamais on ne « conclut » sur ce qu'on n'a pas vu.
    """
    fin = time.time() + timeout
    vu, confirmations = None, 0
    while True:
        ecran = _capture_garee()
        if sur_la_grille(ecran):
            return True
        nouveau = autre_ecran(ecran)
        # LA TRANSITION N'EST PAS UN MAUVAIS ÉCRAN : on ne conclut qu'en
        # revoyant LA MÊME CHOSE. Un écran qui laisse la place à la
        # grille entre deux coups d'œil remet le compteur à zéro — et un
        # AUTRE écran d'entrée le remet à UN, pas à deux.
        #
        # 09/11/2026 : le compteur comptait « un écran d'entrée a été
        # reconnu », pas « le même ». Or les deux écrans traversés juste
        # avant la grille sont deux membres différents d'`AUTRES_ECRANS`
        # — mesuré sur les captures gardées, `liste_defis_20261108` note
        # 0.957 en `active_encounter` et `reprendre_aventure_20261106`
        # note 1.000 en `reprendre_aventure`. Cliquer un défi déjà
        # commencé enchaîne donc ces deux-là, un coup d'œil chacun, et le
        # garde concluait en journalisant « vu 2 fois de suite » un écran
        # qui venait d'apparaître. Un message faux dans un garde-fou est
        # pire que pas de message : c'est la ligne qu'on relira pour
        # comprendre pourquoi le choix du champion a été abandonné.
        if nouveau is None:
            vu, confirmations = None, 0
        elif nouveau == vu:
            confirmations += 1
        else:
            vu, confirmations = nouveau, 1
        if confirmations >= CONFIRMATIONS_AUTRE_ECRAN:
            logging.warning("Grille des champions : « %s » est à l'écran, vu %d "
                            "fois de suite — ce n'est pas la grille des "
                            "champions. On ne défile pas, on ne lit pas de "
                            "palier, on rend la main.", vu, confirmations)
            return False
        if time.time() >= fin:
            if vu is not None:
                logging.warning("Grille des champions : toujours pas affichée "
                                "après %.0f s, et « %s » à l'écran — on rend la "
                                "main.", timeout, vu)
            else:
                logging.warning("Grille des champions : toujours pas affichée "
                                "après %.0f s — on rend la main sans rien "
                                "conclure.", timeout)
            return False
        time.sleep(intervalle)


def meilleure(vignettes, cible=None):
    """
    Le champion à dépenser, parmi ceux qui ont encore une tentative.

    SANS CIBLE : le plus étoilé — c'est juste au premier palier et faux
    ensuite, puisque chaque champion n'a que trois tentatives par mois.

    AVEC UNE CIBLE : LE PLUS FAIBLE QUI L'ATTEINT. C'est tout l'objet de
    la table (Ewan, 05/11/2026) : sur 70 paliers de difficulté
    croissante, griller les 7 étoiles en bas de l'échelle, c'est arriver
    en haut avec des 3. Si personne n'atteint la cible, on prend le plus
    fort disponible : mieux vaut une tentative tendue qu'une tentative
    perdue d'avance.

    À égalité d'étoiles, LE DERNIER dans l'ordre de lecture : la grille
    est triée en ordre croissant, c'est donc le plus haut niveau.

    Rend None si rien n'est jouable — l'appelant retombe alors sur
    l'ancien choix.
    """
    jouables = [v for v in vignettes if not v.epuisee]
    if not jouables:
        return None
    if cible is not None:
        assez = [v for v in jouables if v.etoiles >= cible]
        if assez:
            minimum = min(v.etoiles for v in assez)
            return [v for v in assez if v.etoiles == minimum][-1]
        logging.warning("Grille des champions : personne n'atteint %d étoile(s) ; "
                        "on prend le plus fort disponible.", cible)
    maximum = max(v.etoiles for v in jouables)
    return [v for v in jouables if v.etoiles == maximum][-1]


# --------------------------------------------------------------------
# Parcours de la grille — ici seulement, la souris
# --------------------------------------------------------------------
def _capture_garee():
    """Une capture prise SANS que le curseur survole une vignette."""
    if pyautogui is not None:
        largeur, hauteur = pyautogui.size()
        pyautogui.moveTo(int(POINT_GARE[0] * largeur), int(POINT_GARE[1] * hauteur))
        time.sleep(POSE_AVANT_CAPTURE)
    return an._capture_screen_bgr()


def _focus_molette():
    """
    La fenêtre du jeu est-elle à l'écoute de la molette ?

    MESURÉ LE 08/11/2026 : sans le premier plan, `pyautogui.scroll` ne
    rend aucune erreur et la grille NE BOUGE PAS — écart entre deux
    captures 0.04 contre 33.6 fenêtre active. Les clics, eux, activaient
    la fenêtre au passage : la panne ne se voyait que sur le défilement,
    et elle se déguisait en « bout de liste atteint ».

    Rend True quand le geste a une chance d'arriver. En l'absence de
    pywin32 (hors Windows, tests hors ligne) on ne sait pas, et on dit
    True : l'ancien comportement, aveugle mais inchangé.
    """
    if gestures.game_window_handle() is None:
        return True
    return gestures.focus_game_window()


def _defiler(crans=CRANS_PAR_BOND):
    """Un écran de plus vers le bas. Le curseur se POSE avant la molette."""
    if pyautogui is None:
        return _focus_molette()
    _focus_molette()
    largeur, hauteur = pyautogui.size()
    pyautogui.moveTo(int(POINT_MOLETTE[0] * largeur), int(POINT_MOLETTE[1] * hauteur))
    time.sleep(POSE_AVANT_MOLETTE)
    for _ in range(crans):
        pyautogui.scroll(-5)
        time.sleep(0.08)
    time.sleep(POSE_APRES_MOLETTE)
    return _focus_molette()


def choisir_champion(max_bonds=MAX_BONDS, cible=None, attente=ATTENTE_ECRAN_CHAMPION):
    """
    Descend en bas de la grille, lit l'écran, et clique le meilleur.

    TROIS TEMPS, et c'est voulu :

      0. on s'assure d'être SUR LA GRILLE (`attendre_la_grille`) — sans
         quoi tout le reste juge un écran qui n'est pas le nôtre ;
      1. on DESCEND jusqu'au bas sans rien lire — par bonds, jusqu'à ce
         que l'écran cesse de changer ;
      2. on LIT l'écran courant et on clique dessus.

    La première version lisait en descendant, retenait la meilleure
    vignette, puis essayait de la RETROUVER en remontant : elle ne l'a
    jamais retrouvée en vrai jeu (meilleur score 0.51 contre un seuil de
    0.90) et le bot est reparti sur l'ancien choix, une tentative
    mensuelle à la clé. On ne clique donc plus que ce qu'on vient de
    lire, sur l'écran qu'on a sous les yeux : plus rien à retrouver.

    CE QUE ÇA SUPPOSE : que les plus étoilés soient en BAS. C'est le cas
    — la grille est triée en ordre croissant (mesuré : 1, 1, 2 en tête,
    puis des 3, et 6 et 7 tout en bas). Si cet ordre changeait, on
    choisirait le meilleur du bas de liste au lieu du meilleur absolu :
    moins bon, jamais absurde. Et les épuisés, eux, sont écartés par leur
    bandeau, où qu'ils soient.

    Rend True s'il a cliqué. False veut dire « je n'ai rien su lire » :
    l'appelant retombe sur son ancien comportement.
    """
    from click_utils import safe_click

    global DERNIER_CHOIX, DERNIER_PALIER
    DERNIER_CHOIX = None
    # OÙ SOMMES-NOUS, AVANT TOUT. « Palier illisible » n'est un fait que
    # sur l'écran du champion : le 08/11/2026 à 20:46 cette lecture a été
    # faite sur la LISTE DES DÉFIS, où le titre « DÉFI N » n'existe pas.
    # Lecture nulle, donc « on prend le plus étoilé », puis tout le
    # parcours de grille s'est déroulé sur la liste — molette comprise,
    # qui FAIT DÉFILER CETTE LISTE. Six « rien de jouable », un faux
    # « bas de liste atteint » en un bond, et le repli `first_champion`
    # qui a cherché dans le vide : ~75 s et un essai d'entrée.
    # Rien n'a été consommé ce jour-là parce que le repli n'a rien
    # trouvé. S'il avait trouvé, un 7 ★ partait sur un palier qui en
    # demande 4 — exactement ce que la table existe pour éviter.
    if not attendre_la_grille(attente):
        return False
    if cible is None:
        # Le palier se lit sur CET écran : le titre « DÉFI N » est à côté
        # de la grille. Illisible ALORS QUE LA GRILLE EST LÀ, on garde
        # l'ancien comportement plutôt que de viser au hasard — mais ON
        # NE DIT PLUS POURQUOI, parce qu'on ne le sait pas.
        #
        # 11/11/2026 : le message affirmait « police incomplète », et
        # c'était une CAUSE SUPPOSÉE. Le palier valait 25 et les deux
        # chiffres étaient dans la police (le 5 y avait même été récolté
        # la veille et relu tout seul dans un vrai titre). Le prix du
        # repli, lui, est mesuré : un 7 ★ engagé là où la table en
        # demandait 4. On garde donc l'écran et on journalise ce qu'on a
        # VU ; la cause est une enquête, pas une ligne de log.
        DERNIER_PALIER = attendre_palier()
        cible = etoiles_requises(DERNIER_PALIER)
        if cible is None:
            chemin = journaliser_palier_illisible()
            logging.warning("Palier illisible alors que la grille EST "
                            "affichée%s. On prend le plus étoilé "
                            "(comportement d'avant la table).",
                            f", écran gardé : {chemin}" if chemin else "")
        else:
            logging.info("Palier %s : on vise %d étoile(s) — le plus faible "
                         "qui suffit, pour garder les forts pour la suite.",
                         DERNIER_PALIER, cible)

    if cible is None:
        choisi = _le_plus_fort(max_bonds)
    else:
        choisi = _le_plus_faible_qui_suffit(cible, max_bonds)

    if choisi is None:
        logging.warning("Grille des champions : aucune vignette jouable lue.")
        return False
    clique = bool(safe_click(*choisi.clic, transition=True))
    if clique:
        DERNIER_CHOIX = choisi
    return clique


def revenir_en_haut(max_bonds=MAX_BONDS):
    """
    Ramène la grille tout en haut — pour que le REPLI soit encore possible.

    MESURÉ LE 08/11/2026 : quand `choisir_champion` échoue, il laisse la
    grille là où son parcours l'a menée, c'est-à-dire EN BAS. Or le filet
    de `navigate._pick_champion` cherche `first_champion.png`, qui est le
    HAUT de la grille : sur l'écran du jour il notait 0.64 pour un seuil
    de 0.80, et le bot a conclu « bouton introuvable ». Le filet
    documenté depuis le 05/11 — « on retombe sur le premier de la
    liste » — ne pouvait donc jamais se déclencher après un parcours.
    On remonte d'abord ; ensuite seulement le repli a un sens.

    ET ON NE REMONTE QUE CE QUI EST UNE GRILLE (08/11/2026, soir). Ce
    geste est appelé par `navigate._pick_champion` JUSTE APRÈS un échec
    de `choisir_champion` — c'est-à-dire, ce soir-là, sur la liste des
    défis, qu'il a fait défiler de bas en haut pour rien. Un écran qui
    n'est pas la grille n'a pas de haut de grille à retrouver.
    """
    if not sur_la_grille(_capture_garee()):
        logging.warning("Grille des champions : rien à remonter, ce n'est pas "
                        "la grille des champions.")
        return False
    return _parcourir(max_bonds, CRANS_PAR_BOND, descendre=False)


def _le_plus_fort(max_bonds):
    """
    Sans cible : on DESCEND jusqu'au bas et on lit ce qu'on voit.

    La grille étant triée en ordre croissant, les plus étoilés sont en
    bas. On ne clique que ce qu'on vient de lire : la première version
    retenait une vignette en descendant puis essayait de la RETROUVER en
    remontant, et ne l'a jamais retrouvée en vrai jeu (0.51 pour un
    seuil de 0.90).
    """
    _parcourir(max_bonds, CRANS_PAR_BOND, descendre=True)
    for _ in range(MAX_RANGEES_REMONTEES):
        vues = lire_vignettes(_capture_garee())
        choisi = meilleure(vues)
        if choisi is not None:
            logging.info("Grille des champions : %d vignette(s) lue(s), "
                         "retenu %d étoile(s) en %s.",
                         len(vues), choisi.etoiles, choisi.clic)
            return choisi
        logging.info("Rien de jouable sur cet écran — on remonte d'une rangée.")
        _remonter(CRANS_PAR_RANGEE)
    return None


def _le_plus_faible_qui_suffit(cible, max_bonds):
    """
    Le champion le moins cher qui atteint la cible — et, à étoiles
    égales, LE PLUS HAUT NIVEAU.

    On remonte en haut, puis on descend rangée par rangée. La grille
    étant triée en ordre croissant (étoiles, puis niveau), la première
    vignette qui atteint la cible est la moins chère EN ÉTOILES mais
    aussi la plus FAIBLE EN NIVEAU de sa bande — c'est ce que le bot a
    pris le 05/11/2026 au palier 6, et il a perdu. Ewan : « tente avec un
    3 étoiles de plus haut niveau ».

    On continue donc de descendre TANT QUE la bande dure, et on prend la
    dernière vignette qui en fait partie. Dès qu'un écran n'en contient
    plus, on remonte d'une rangée — la dernière est forcément là — et on
    clique ce qu'on voit. On ne clique jamais une position mémorisée :
    elle aurait défilé (leçon du 05/11, « retrouvé à 0.51 »).
    """
    _parcourir(max_bonds, CRANS_PAR_BOND, descendre=False)
    bande = None
    hauteur = 0                 # rangées parcourues depuis le haut
    carnet = _carnet()          # ce qu'on a vu de jouable en chemin
    precedent = None
    for _ in range(max_bonds):
        ecran = _capture_garee()
        vues = lire_vignettes(ecran)
        grille = _zone_grille(ecran)
        if _liste_immobile(precedent, grille):
            # BAS DE LISTE : la molette ne déplace plus rien. Continuer à
            # compter des rangées qu'on ne parcourt pas fausserait la
            # HAUTEUR du carnet — on remonterait trop haut en revenant
            # sur ses pas, et on relirait un autre écran que celui qu'on
            # vise. On décompte la rangée qui n'a pas eu lieu.
            hauteur -= 1
            break
        precedent = grille
        _noter(carnet, hauteur, vues)
        jouables = [v for v in vues if not v.epuisee]
        assez = [v for v in jouables if v.etoiles >= cible]
        if assez:
            minimum = min(v.etoiles for v in assez)
            if bande is None or minimum < bande:
                bande = minimum
        candidats = [v for v in jouables if bande is not None and v.etoiles == bande]
        if candidats:
            _defiler(CRANS_PAR_RANGEE)          # la bande continue peut-être
            hauteur += 1
            continue
        if bande is not None:
            # On vient de dépasser la bande : la dernière de la bande est
            # une rangée plus haut.
            _remonter(CRANS_PAR_RANGEE)
            hauteur -= 1
            choisi = _derniere_de_la_bande(bande)
            if choisi is not None:
                logging.info("Grille des champions : %d étoile(s) pour une cible "
                             "de %d, le plus haut niveau de la bande, en %s.",
                             choisi.etoiles, cible, choisi.clic)
                return choisi
            logging.warning("Grille des champions : la bande de %d étoile(s) a "
                            "disparu en remontant.", bande)
            return _sur_nos_pas_ou_le_plus_fort(carnet, hauteur, max_bonds)
        _defiler(CRANS_PAR_RANGEE)
        hauteur += 1

    # Bas de liste atteint sans jamais sortir de la bande : la dernière
    # vignette visible est la bonne.
    choisi = _derniere_de_la_bande(bande) if bande is not None else None
    if choisi is not None:
        logging.info("Grille des champions : %d étoile(s) pour une cible de %d, "
                     "en bas de la bande, en %s.", choisi.etoiles, cible, choisi.clic)
        return choisi
    logging.warning("Grille des champions : personne n'atteint %d étoile(s).", cible)
    return _sur_nos_pas_ou_le_plus_fort(carnet, hauteur, max_bonds)


def _carnet():
    """Ce qu'on a vu de JOUABLE en chemin, et à quelle hauteur de la liste."""
    return {"vignette": None, "hauteur": None}


def _noter(carnet, hauteur, vues):
    """
    Retient la meilleure vignette jouable de cet écran — et SA HAUTEUR.

    08/11/2026 : le parcours lisait des vignettes jouables en chemin puis
    les JETAIT. Sans palier, la cible est None, donc on descend au bas de
    la liste où sont les plus forts — et là, tous épuisés (trois
    tentatives par champion et par mois). « aucune vignette jouable
    lue », puis le filet `first_champion` à son tour : aucun choix du
    tout, alors que des champions jouables avaient défilé sous les yeux.

    À ÉTOILES ÉGALES ON GARDE LA PLUS BASSE DE LA LISTE (hauteur la plus
    grande) : la grille est triée en ordre croissant, donc c'est le plus
    haut niveau — la même règle que « la dernière de la bande ».
    """
    choisi = meilleure(vues)
    if choisi is None:
        return
    garde = carnet["vignette"]
    if (garde is None or choisi.etoiles > garde.etoiles
            or (choisi.etoiles == garde.etoiles and hauteur > carnet["hauteur"])):
        carnet["vignette"], carnet["hauteur"] = choisi, hauteur


def _sur_nos_pas_ou_le_plus_fort(carnet, hauteur, max_bonds):
    """
    Revient sur la meilleure jouable vue en chemin ; sinon, l'ancien repli.

    ON NE CLIQUE JAMAIS UNE POSITION MÉMORISÉE (leçon du 05/11/2026 :
    retrouver une vignette par gabarit après défilement notait 0.51 pour
    un seuil de 0.90). On revient à la HAUTEUR où on l'a vue, puis on
    RELIT et on choisit sur l'écran qu'on a sous les yeux. Si la grille a
    bougé entre-temps, on n'a rien perdu : on retombe sur `_le_plus_fort`,
    le comportement d'avant.
    """
    retenue = carnet["vignette"]
    if retenue is None:
        return _le_plus_fort(max_bonds)
    ecart = carnet["hauteur"] - hauteur
    for _ in range(abs(ecart)):
        (_defiler if ecart > 0 else _remonter)(CRANS_PAR_RANGEE)
    choisi = meilleure(lire_vignettes(_capture_garee()))
    if choisi is None:
        logging.warning("Grille des champions : la vignette à %d étoile(s) vue "
                        "en chemin n'est plus là où on l'avait laissée.",
                        retenue.etoiles)
        return _le_plus_fort(max_bonds)
    logging.info("Grille des champions : personne n'atteignait la cible ; on "
                 "revient sur la meilleure vue en chemin — %d étoile(s) en %s.",
                 choisi.etoiles, choisi.clic)
    return choisi


def _derniere_de_la_bande(bande):
    """La dernière vignette jouable à `bande` étoiles sur l'écran courant."""
    vues = lire_vignettes(_capture_garee())
    candidats = [v for v in vues if not v.epuisee and v.etoiles == bande]
    return candidats[-1] if candidats else None


def _parcourir(max_bonds, crans, descendre):
    """
    Va jusqu'au bout de la liste, sans rien lire.

    « RIEN N'A BOUGÉ » NE VEUT DIRE « ON EST AU BOUT » QUE SI LE GESTE
    EST PARTI. Le 08/11/2026 la fenêtre du jeu n'avait pas le premier
    plan : la molette tombait dans le vide, la grille restait fixe, et
    ce silence a été lu comme « bas de liste atteint » dès le premier
    bond utile. Le bot a jugé un écran de six vignettes toutes épuisées,
    n'a trouvé personne à jouer, et a renoncé au choix du champion.
    `_defiler` et `_remonter` disent maintenant si la fenêtre écoutait ;
    quand elle n'écoutait pas, on ne conclut rien.
    """
    precedent = None
    entendu = True
    for bond in range(max_bonds):
        grille = _zone_grille(_capture_garee())
        if _liste_immobile(precedent, grille):
            if not entendu:
                logging.warning("Grille des champions : rien n'a bougé, mais la "
                                "fenêtre du jeu n'était pas au premier plan — "
                                "on ne conclut pas au bout de la liste.")
                return False
            logging.info("Grille des champions : %s atteint (%d bond(s)).",
                         "bas de liste" if descendre else "haut de liste", bond)
            return True
        precedent = grille
        entendu = bool((_defiler if descendre else _remonter)(crans))
    logging.warning("Grille des champions : bout de liste non atteint en "
                    "%d bonds — on lit quand même ce qu'on voit.", max_bonds)
    return True


def _zone_grille(ecran):
    """La grille seule : ni l'en-tête, ni le panneau de droite."""
    hauteur, largeur = ecran.shape[:2]
    return ecran[int(GRILLE_HAUT * hauteur):, :int(0.58 * largeur)]


def _remonter(crans=CRANS_PAR_RANGEE):
    """Un écran vers le haut, mêmes précautions que `_defiler`."""
    if pyautogui is None:
        return _focus_molette()
    _focus_molette()
    largeur, hauteur = pyautogui.size()
    pyautogui.moveTo(int(POINT_MOLETTE[0] * largeur), int(POINT_MOLETTE[1] * hauteur))
    time.sleep(POSE_AVANT_MOLETTE)
    for _ in range(crans):
        pyautogui.scroll(5)
        time.sleep(0.08)
    time.sleep(POSE_APRES_MOLETTE)
    return _focus_molette()


def _memes(a, b):
    """Deux captures de la grille montrent-elles la même chose ?"""
    if a.shape != b.shape:
        return False
    return float(np.mean(cv2.absdiff(a, b))) < 1.0


def _liste_immobile(precedent, grille):
    """
    « La molette ne déplace plus rien » — LE critère, et il n'y en a qu'un.

    09/11/2026 : la question se posait de DEUX façons. `_parcourir`
    comparait les PIXELS avec une tolérance (`_memes`, écart moyen
    < 1.0) ; `_le_plus_faible_qui_suffit` comparait les VIGNETTES LUES
    par égalité EXACTE de namedtuples. Deux critères pour la même
    question finissent toujours par diverger, et celui-ci diverge très
    tôt — mesuré sur `captures_reference/champions_haut_20261105.png`
    (zone de grille 767×1113, 2 561 013 valeurs) : il faut ~3 348 pixels
    saturés pour que `_memes` dise « différent », et **110 pixels
    (0,013 %, écart moyen 0.0023, soit 430 fois sous le seuil)**
    suffisent à changer la liste lue — cinq lignes recopiées sous UN
    SEUL glyphe d'étoile, c'est-à-dire ce que fait la surbrillance d'une
    vignette, qui porte l'aire d'un glyphe de 141-156 à 229-233.

    Conséquence : au bas de la liste, la lecture bougeait encore alors
    que l'écran, lui, ne bougeait plus. Le parcours ne voyait pas le
    bout, comptait `hauteur += 1` pour des rangées QUI N'EXISTENT PAS, et
    `_sur_nos_pas_ou_le_plus_fort` remontait d'autant trop haut — il
    relisait un autre écran que celui qu'il visait. Exactement ce que le
    `hauteur -= 1` du 08/11 existe pour éviter.
    """
    return precedent is not None and _memes(precedent, grille)


def _forme_du_glyphe(glyphe):
    """
    La forme du SEUL glyphe, vue comme le lecteur la verra.

    `glyph_mask` rend 0/1 ; l'alpha d'un gabarit se relit à >= 128
    (`digits._read_mask`). Écrire le masque tel quel donnait un fichier
    à l'alpha « vide » : le gabarit était écrit, puis IGNORÉ au
    chargement, sans un mot.

    Et on ne garde que la PLUS GROSSE composante : la marge de découpe
    attrape des éclats du glyphe voisin, et un gabarit qui les emporte
    s'élargit en tache. Mesuré le 08/11/2026 — un « 9 » découpé avec ses
    éclats reconnaissait une ILLUSTRATION de carte comme un 9 (0.61,
    marge 0.12), là où le test exige qu'une illustration ne donne aucun
    chiffre.
    """
    masque = (digits.glyph_mask(glyphe) > 0).astype("uint8")
    nombre, _, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    if nombre <= 1:
        return masque * 255
    plus_gros = max(range(1, nombre), key=lambda i: stats[i][cv2.CC_STAT_AREA])
    _, labels, _, _ = cv2.connectedComponentsWithStats(masque, 8)
    return (labels == plus_gros).astype("uint8") * 255


def _boites_du_nombre(zone):
    """
    Les glyphes d'un rectangle CADRÉ SUR LE NOMBRE SEUL, de gauche à droite.

    Ici on ne cherche pas un titre au milieu du décor : l'appelant a déjà
    encadré le nombre. On segmente donc par le chemin du LECTEUR
    (`glyph_mask` + `glyph_boxes`, ce que fait `read_number`) et non par
    le seuil de clarté de `_glyphes_du_titre`, qui n'existe que pour
    isoler le titre dans sa bande.

    On BLANCHIT le doré d'abord, comme `lire_palier` : `glyph_mask`
    exclut l'orange à dessein, et sans ça un nombre doré ne rend aucune
    composante — mesuré le 10/11/2026 sur « VICTOIRES TOTALES : 23 ».
    """
    zone = zone.copy()
    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    zone[cv2.inRange(hsv, DORE_BAS, DORE_HAUT) > 0] = (255, 255, 255)
    masque = digits.glyph_mask(zone)
    return [(x, y, w, h) for (x, y, w, h, _) in digits.glyph_boxes(masque)]


def cut_defi(palier_affiche, ecran=None, zone=None):
    """
    Découpe les chiffres du titre « DÉFI N » dans `chiffres/<N>_defi.png`.

        python champions.py cut-defi 13
        python champions.py cut-defi 23 capture.png 1270 497 1320 529

    POURQUOI UNE COMMANDE : la police du titre n'est pas celle des coûts
    de cartes, et on ne peut pas inventer les chiffres qu'on n'a jamais
    vus. Elle est amorcée avec le « 2 » du 05/11/2026 et s'enrichit au
    fil des paliers rencontrés — exactement comme `chiffres/N_nexus.png`,
    livré avec 0-5 et 9 seulement. Tu donnes le nombre AFFICHÉ, chaque
    glyphe est rangé sous son chiffre.

    `zone = (x0, y0, x1, y1)` RÉCOLTE AILLEURS QUE DANS LE TITRE, sur un
    rectangle que l'appelant cadre sur le nombre seul. Pourquoi c'est
    permis : le 10/11/2026 il manquait 0, 3, 5 et 8, et AUCUNE capture du
    dépôt — 16 077 PNG balayés — ne montre un titre « DÉFI N » qui en
    contienne un. Or le même écran les écrit ailleurs, et c'est LA MÊME
    POLICE, mesuré et non supposé : sur un même chiffre, un glyphe de la
    LISTE des défis recouvre celui du TITRE à 0.74-0.90 (témoin interne,
    titre contre titre : 0.82-1.00 ; chiffres DIFFÉRENTS : 0.32-0.45), et
    la police des coûts, elle, ne sait pas les lire (None, 0.53-0.59).
    Ce n'est donc pas l'entorse du 08/11 (« une police sert là où elle a
    été récoltée ») : c'est la même police, à une autre taille.
    Ce qu'on ne fait toujours PAS : dessiner un glyphe, ou le prendre
    dans une police qui n'est pas celle-là — les pastilles de niveau des
    vignettes (5×15) portent bien un « 0 », mais à 15 px de haut contre
    27-36 pour un titre, et `digits` les lit déjà mal.
    """
    ecran = an._capture_screen_bgr() if ecran is None else ecran
    if zone is not None:
        x0, y0, x1, y1 = (int(v) for v in zone)
        zone, nombre = ecran[y0:y1, x0:x1], None
        if zone.size:
            nombre = _boites_du_nombre(zone)
        if not nombre:
            print("Aucun glyphe dans le rectangle donné.")
            return False
    else:
        zone, boites = _glyphes_du_titre(ecran)
        if zone is None or len(boites) < 2:
            print("Titre « DÉFI N » introuvable à l'écran.")
            return False
        ecarts = [boites[i + 1][0] - (boites[i][0] + boites[i][2])
                  for i in range(len(boites) - 1)]
        nombre = boites[ecarts.index(max(ecarts)) + 1:]
    chiffres = str(int(palier_affiche))
    if len(nombre) != len(chiffres):
        print(f"{len(nombre)} glyphe(s) trouvé(s) pour « {chiffres} » : "
              "on ne devine pas, rien n'est écrit.")
        return False
    dossier = digits.DIGITS_DIR
    marge = 3
    for (x, y, w, h), chiffre in zip(nombre, chiffres):
        # ON DÉCOUPE LA FORME QUE LE LECTEUR VERRA, PAS UNE AUTRE.
        # La première version prenait l'alpha d'un seuil de clarté à 120
        # sur le glyphe doré, alors que `lire_palier` BLANCHIT le doré
        # puis passe par `digits.glyph_mask`. Les deux masques ne sont pas
        # le même : mesuré le 08/11/2026 sur le « 9 » de « DÉFI 19 », 336
        # pixels contre 406, IoU 0.83. La police apprise ne se
        # reconnaissait donc pas elle-même — ce 9 notait 0.652 contre son
        # propre gabarit et 0.691 contre le 6 (un 6 est un 9 retourné),
        # marge 0.04 sous un plancher de 0.06 : refusé. En découpant par
        # le chemin de lecture, le gabarit colle à ce qu'on lira.
        h_img, l_img = zone.shape[:2]
        y0, y1 = max(0, y - marge), min(h_img, y + h + marge)
        x0, x1 = max(0, x - marge), min(l_img, x + w + marge)
        glyphe = zone[y0:y1, x0:x1].copy()
        hsv = cv2.cvtColor(glyphe, cv2.COLOR_BGR2HSV)
        glyphe[cv2.inRange(hsv, DORE_BAS, DORE_HAUT) > 0] = (255, 255, 255)
        # `glyph_mask` rend 0/1 ; l'alpha d'un gabarit se relit à >= 128
        # (`digits._read_mask`). Écrire le masque tel quel donnait un
        # fichier à l'alpha « vide » : le gabarit était écrit, puis
        # IGNORÉ au chargement, sans un mot.
        masque = _forme_du_glyphe(glyphe)
        rgba = cv2.cvtColor(glyphe, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = masque          # alpha = la FORME
        chemin = dossier / f"{chiffre}_defi.png"
        cv2.imwrite(str(chemin), rgba)
        print(f"  {chemin.name} écrit ({w}x{h})")
    digits._VARIANTS = {}
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 2 and sys.argv[1] == "cut-defi":
        # cut-defi <N> [capture [x0 y0 x1 y1]] — le rectangle récolte
        # AILLEURS que dans le titre (cf. la docstring de `cut_defi`).
        ecran = cv2.imread(sys.argv[3]) if len(sys.argv) > 3 else None
        if len(sys.argv) > 3 and ecran is None:
            print(f"Capture illisible : {sys.argv[3]}")
            raise SystemExit(1)
        zone = tuple(int(v) for v in sys.argv[4:8]) if len(sys.argv) >= 8 else None
        raise SystemExit(0 if cut_defi(sys.argv[2], ecran=ecran, zone=zone) else 1)
    ecran = cv2.imread(sys.argv[1]) if len(sys.argv) > 1 else an._capture_screen_bgr()
    if ecran is None:
        print(f"Capture illisible : {sys.argv[1]}")
        raise SystemExit(1)
    vues = lire_vignettes(ecran)
    if not vues:
        print("Aucune vignette de champion lue sur cet écran.")
        # On dit quand même ce que la bande du titre contenait : c'est
        # la question qu'on vient poser à une capture gardée.
        for ligne in _diagnostic_du_titre(ecran):
            print(f"    {ligne}")
        return
    for v in vues:
        etat = "ÉPUISÉ" if v.epuisee else "jouable"
        print(f"  ({v.x:4}, {v.y:4})  {v.etoiles} étoile(s)  {etat:8} "
              f"clic en {v.clic}")
    palier = lire_palier(ecran)
    cible = etoiles_requises(palier)
    choisi = meilleure(vues, cible)
    print()
    if palier is not None:
        print(f"palier lu : {palier}   cible : {cible} étoile(s)")
    else:
        # LE DIAGNOSTIC DIT CE QU'IL A VU, PAS CE QU'IL SUPPOSE. C'est la
        # même sortie que celle journalisée en jeu — une seule fonction,
        # donc la commande ne peut pas raconter autre chose que le bot.
        # C'est ici qu'on vient regarder une capture
        # `screenshots/palier_illisible_*.png`.
        print("palier illisible : aucune cible, on prend le plus fort")
        for ligne in _diagnostic_du_titre(ecran):
            print(f"    {ligne}")
    print(f"Choix : {choisi.etoiles} étoile(s), clic en {choisi.clic}"
          if choisi else "Aucun champion jouable sur cet écran.")


if __name__ == "__main__":
    main()
