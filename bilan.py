#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bilan.py — LE JUGE DE FIN DE TENTATIVE.

    python bilan.py                 # juge l'écran affiché maintenant
    python bilan.py <capture.png>   # juge une capture

--------------------------------------------------------------------
POURQUOI CE FICHIER
--------------------------------------------------------------------
Au 05/11/2026, le journal comptait 72 combats et **aucune victoire** —
mais surtout 62 combats sans aucun verdict. Le trou n'était pas
aléatoire, il était structurel : en défi, l'API ne juge rien
(`final_result` rend `None`, 53 fois sur 53), et les seuls juges
étaient l'ÉCRAN (« Relevez-vous », fin d'aventure) et l'aventure qui
continue (`confirm_victory`, quand le nœud SUIVANT est rejoint).

Or au BOSS FINAL il n'y a pas de nœud suivant, et le second
« Continuer » y est la sortie NORMALE — pas une défaite. Donc le
combat le plus important de chaque aventure était le SEUL à n'être
jamais jugé. `try_combat` le disait sans en tirer la conséquence :
« fin d'aventure (boss final) ... verdict inconnu ».

Et pendant ce temps, l'écran le disait en toutes lettres. Le 04/11 à
20:49:38, le bot a PHOTOGRAPHIÉ le bilan — « DÉFI 2 · SHEN · PV 0/20 »
— pour le classer « écran inconnu ». Ce fichier lit cette capture-là.

--------------------------------------------------------------------
CE QU'ON LIT, ET POURQUOI COMME ÇA
--------------------------------------------------------------------
- L'ANCRE est le grand cœur blanc des PV (`assets/bilan_coeur.png`,
  découpé de la capture du 04/11, 86×76 px). Il est mesuré en (94, 755)
  sur 1920×1080. Pas de lecture de texte : le titre du panneau n'est
  pas lu, ici non plus (cf. `events.py`).

- LA FENÊTRE DU NOMBRE NE PEUT PAS ÊTRE FIXE. Le bloc « 0 / 20 » est
  CENTRÉ sous le label : « 12 / 20 » serait plus large et décalerait
  tout. On prend donc une bande généreuse à droite du cœur, et c'est la
  COULEUR qui sépare les deux nombres.

- LES PV COURANTS SONT ORANGE, le maximum est crème. C'est la clé, et
  c'est aussi le PIÈGE : `digits.glyph_mask` exclut l'orange
  VOLONTAIREMENT (cf. CLAUDE.md). Donc une lecture naïve de toute la
  bande ne voit pas le « 0 » et rend **20** — elle conclurait « 20 PV,
  donc victoire » sur un écran de défaite. Mesuré, et verrouillé par
  `test_bilan.test_le_piege_du_bloc_entier`.

  On repeint donc l'orange en blanc AVANT de lire, et seulement sur la
  sous-image des glyphes oranges. Le masque global n'est pas touché :
  l'orange reste exclu partout ailleurs, où il désigne le jeton
  d'attaque et la gemme de mana.

- DEUX ÉCRANS, PAS UN. Première aventure gagnée le 05/11/2026 (Teemo
  Fleur Spirituelle, 7 étoiles) : l'écran de VICTOIRE n'est pas celui
  de la défaite. C'est un écran de RÉCOMPENSES — « DÉFI 2 / VICTOIRE »
  en haut à gauche, « XP DE DÉFI ×5 », un bouton « Continuer » — SANS
  cœur et SANS PV. Le juge écrit ce jour-là avait donc rendu, à juste
  titre, « écran non lisible » : il ne devine pas. D'où une seconde
  ancre, le mot « VICTOIRE » (`assets/bilan_victoire.png`, 1.000 sur
  l'écran de victoire contre 0.46 sur celui de défaite). Le gabarit
  exclut « DÉFI 2 » : le numéro change d'un défi à l'autre.

- ET CE MOT-LÀ DOIT ÊTRE À SA PLACE (08/11/2026). Le gabarit est fidèle,
  et c'est tout le problème : il retrouve le mot partout où il est
  ÉCRIT, y compris dans le compteur « XP DE DÉFI (22 VICTOIRES TOTALES) »
  de la LISTE DES DÉFIS et du PANNEAU DE REPRISE D'AVENTURE — deux
  écrans que le bot traverse à CHAQUE tentative. Mesuré sur les 980
  captures du dépôt :

      1.000 à 0.983   le mot, en (272, 119)         11 écrans de victoire
      0.862 à 0.860   « VICTOIRES », en (453, 766)   6 listes de défis
      0.552 et moins  tout le reste

  647 px plus bas, même police, même casse, au pluriel près. Et le juge
  y prononçait VICTOIRE. La trace du 08/11 ne permet même pas de
  trancher après coup : « 20:53:48 Bilan de fin lu à l'écran : victoire
  (écran de fin de défi) » est suivi UNE SECONDE plus tard de
  « 20:53:49 Écran connu retrouvé : liste des défis actifs » — et
  `attendre_verdict` REGARDE pendant huit secondes, donc il voit
  fatalement la liste dès qu'elle s'affiche. Ce verdict part dans
  `journal.conclude`, donc dans `journal.jsonl`, donc dans
  `journal.py --champions`, donc dans la table
  `champions.etoiles_requises` qui décide quel champion dépenser sur
  quel palier : un seul faux « gagne: true » corrompt la seule mesure
  sur laquelle ce projet s'appuie.

  C'EST LA LEÇON DU MARQUEUR DU JOUEUR, RETOURNÉE. Le 08/11 au matin, un
  repère « presque reconnu » avait été réparé sans vérifier qu'il
  désignait la bonne chose. Ici le repère est PARFAITEMENT reconnu, et
  il désigne la mauvaise chose. Un bon score ne prouve que la fidélité
  du gabarit, jamais la justesse de la lecture.

  ON CONTRÔLE DONC LA POSITION, PAS LE SEUIL. Le seuil se défendrait
  (0.983 contre 0.862), mais il ne laisse que 0.12 de marge, et c'est
  exactement le genre de nombre que ce projet a appris à ne pas croire.
  La position, elle, a un écart NUL : les onze vrais positifs tombent au
  MÊME PIXEL. En exigeant que le mot soit à sa place, la marge devient
  0.53 — pire vrai positif 0.983, meilleur score de n'importe quel autre
  écran à cet endroit-là 0.456. Le seuil de 0.80 n'a donc pas bougé : il
  se retrouve au milieu d'un trou deux fois plus large qu'avant.

  ET ON CHERCHE DANS LA ZONE, ON NE FILTRE PAS L'ARGMAX APRÈS COUP.
  `best_match` ne rend que son maximum : chercher partout puis refuser le
  point hors de sa place laisse le compteur, plus net, MASQUER le vrai
  mot — et c'est alors une victoire réelle qui se perd. Mesuré sur le
  fondu enchaîné de l'écran de victoire vers la liste des défis : à 0,65
  d'opacité le mot vaut encore 0.835 À SA PLACE, au-dessus du seuil,
  tandis que le compteur vaut 0.862 647 px plus bas et rafle l'argmax.
  C'est la mesure elle-même qui l'imposait : les 0.983 contre 0.456 ont
  été calculés sur la carte de scores complète, pas sur un argmax.

  La tolérance vaut deux tailles de gabarit (`TOLERANCE_VICTOIRE`), de
  quoi encaisser un écran qui glisse sans rien devoir au hasard, et tout
  est en RATIOS : un point absolu ne vaudrait rien dans une autre
  résolution. Hors de sa place, le mot est journalisé en WARNING — on ne
  se tait pas sur un repère qu'on refuse. Tests :
  `test_bilan.test_le_mot_victoire_doit_etre_a_sa_place` et
  `test_aucune_autre_capture_de_reference_ne_gagne`.

- AUCUN GLYPHE ORANGE = NEXUS AU MAXIMUM, donc vivant, donc victoire —
  MAIS SEULEMENT SI LE MAXIMUM, LUI, SE LIT (08/11/2026). Pendant des
  jours cette règle s'est contentée de l'ABSENCE, et l'erreur était
  asymétrique dans le pire sens : conclure à la DÉFAITE exigeait de
  LIRE « 0 », tandis que ne rien voir du tout donnait la VICTOIRE. Un
  panneau à moitié dessiné suffisait donc à enregistrer une défaite
  comme une victoire.

  Vu dans `logs/bot_run.log` le 08/11/2026, DEUX FOIS (20:45:48 et
  20:53:37) : le MÊME écran, à une seconde d'écart, et deux réponses
  contradictoires —

      20:53:37 [WARNING] cœur trouvé (0.81) mais PV illisibles
      20:53:38 [INFO]    victoire (bilan : nexus intact)

  Le cœur à 0.81 au lieu de 1.00 le disait : le panneau n'était pas
  dans son état normal. Et comme `attendre_verdict` REGARDE pendant
  plusieurs secondes, il tombait fatalement sur l'image où l'orange
  manquait. Une tentative hebdomadaire perdue entrait au journal en
  VICTOIRE — or `journal.py --champions` est précisément l'outil qui
  règle la table `etoiles_requises` de `champions.py` : un seul faux
  « gagne: true » la corrompt.

  LE MAXIMUM SEUL NE PROUVE RIEN, et s'en contenter a été la première
  réparation — fausse. L'idée était que le maximum crème, s'il se lit,
  atteste que le panneau est dessiné ; elle reposait sur une mesure
  faite en ASSOMBRISSANT la capture (le « / » s'efface dès 0,85 de
  clarté, tout le crème dès 0,70, l'orange seulement à 0,37 — donc
  « partout où l'orange manque, le crème manquait déjà »).

  Cet ordre S'INVERSE dès que le panneau ne s'efface pas vers le noir
  mais se FOND SUR L'ÉCRAN DE DESSOUS, ce qui est le cas réel : le
  crème est presque blanc, donc peu saturé, et il traverse le fondu ;
  l'orange, lui, est reconnu à sa SATURATION (≥ 80), qui s'effondre dès
  qu'on le mélange à autre chose. Mesuré en fondant la capture de
  défaite sur deux écrans du projet (la carte d'aventure, la boutique) :
  entre 0,22 et 0,41 d'opacité, PLUS UN SEUL chiffre orange, le maximum
  toujours lu « 20 », et le cœur encore à 0,95-0,99 — soit « victoire
  (nexus intact, 20/20) » rendu sur un écran qui affiche 0 PV. Le bogue
  survivait à sa propre correction.

  LA PREUVE EST DONC « N / N » EN ENTIER, courant compris. Sur un bilan
  de DÉFAITE les PV courants sont orange, donc INVISIBLES au masque des
  glyphes crème : mesuré sur la capture du 04/11, la bande « 0 / 20 » ne
  laisse que trois glyphes crème — `[« / », « 2 », « 0 »]` — et il n'y a
  RIEN à gauche du séparateur. Un panneau dégradé ne peut donc pas
  fabriquer le nombre de gauche, alors qu'un nexus réellement au maximum
  l'affiche. L'égalité des deux nombres est ce qui tranche, et elle
  tient quel que soit le MODE de dégradation, parce qu'elle ne demande
  plus à une couleur de témoigner pour l'autre.

  Le cas reste théorique sur l'écran de BILAN (celui au cœur) : on ne
  l'a jamais vu, puisqu'une victoire envoie sur l'écran de récompenses.
  Il est éprouvé dans les tests en fabriquant « 20 / 20 » tout en crème
  à partir de la capture de défaite. ATTENTION, c'est une HYPOTHÈSE sur
  ce que le jeu affiche : nos deux seules captures chiffrées (« 0 / 20 »
  et « 26 / 63 ») dessinent toutes deux les PV courants en orange, et
  nul n'a jamais vu un nexus intact sur cet écran. Si le jeu gardait
  l'orange même à plein, cette branche ne se déclencherait jamais — ce
  qui serait sans dommage, puisqu'elle rendrait None, l'ancien
  comportement sûr. Le fait de jeu viendra d'Ewan.

- LES DEUX ÉCRANS NE SE SUIVENT PAS AU MÊME INSTANT. Mesuré le
  05/11 : second « Continuer » cliqué à 15:05:31, juge appelé à
  15:05:40 sur un écran encore muet, écran de victoire affiché à
  15:05:47 — APRÈS le clic de fermeture. D'où `attendre_verdict`, qui
  REGARDE pendant quelques secondes au lieu de juger une seule image,
  et deux appels dans `lor_battle` : avant et après la fermeture.

- ILLISIBLE N'EST PAS UN VERDICT. Pas de cœur, bande vide, chiffre
  invraisemblable : on rend `None` et le combat reste `gagne: null`.
  Inventer un verdict corromprait `journal.py`, qui est précisément ce
  qu'on essaie de réparer.

La borne des PV vient de `mana.NEXUS_HEALTH_MAX` et de nulle part
ailleurs : UNE SEULE BORNE PAR GRANDEUR LUE.
"""

from __future__ import annotations

import logging
import sys
import time
from collections import namedtuple

import cv2
import numpy as np

import adventure_navigation as an
import digits
from mana import NEXUS_HEALTH_MAX

# --------------------------------------------------------------------
# Repères, tous mesurés sur captures_reference/bilan_defaite_20261104.png
# --------------------------------------------------------------------
ANCRE = "bilan_coeur"
ANCRE_VICTOIRE = "bilan_victoire"
SEUIL_ANCRE = 0.80

# OÙ LE MOT « VICTOIRE » EST ÉCRIT, en ratios de l'écran. Mesuré sur les
# ONZE captures d'écran de victoire du dépôt : toutes donnent (272, 119)
# sur 1920×1080, AU PIXEL PRÈS — défi 2 à un chiffre comme défi 13 à
# deux, le numéro ne pousse pas le mot (il est sur la ligne du dessus).
#
# En RATIOS et pas en pixels : un point absolu ne vaudrait rien le jour
# où le jeu tournerait dans une autre résolution, et tout le reste du
# projet raisonne déjà ainsi.
POSITION_VICTOIRE = (0.1417, 0.1102)

# DEUX TAILLES DE GABARIT (135×46 px) de tolérance dans chaque direction,
# soit ±270 px en largeur et ±92 px en hauteur sur 1920×1080. L'écart
# mesuré entre les onze vrais positifs est NUL : cette tolérance n'est
# que de la marge, pour ne pas refuser un écran qui aurait glissé. Le
# faux positif, lui, est à 647 px — quatorze hauteurs de gabarit.
TOLERANCE_VICTOIRE = (0.1406, 0.0852)

# Combien de temps REGARDER avant de renoncer. L'écran de verdict
# n'arrive pas à l'instant où on l'interroge (cf. en-tête) ; une seule
# image, c'est une chance sur plusieurs de tomber au bon moment.
ATTENTE_VERDICT = 8.0
INTERVALLE_VERDICT = 1.0

# La bande du nombre de PV, en RATIOS de l'écran, depuis le point que
# rend `best_match` — le centre de la BOÎTE du template, (95, 762), et
# non le centroïde du cœur (94, 755) : 7 px plus bas, et c'est le
# premier qui ancre. Bande généreuse à dessein (cf. en-tête : le bloc
# est centré, sa largeur dépend du nombre). Bornée en haut pour ne pas
# mordre sur le label « PV » — des lettres lues comme des chiffres — et
# à droite pour ne pas atteindre l'icône des PO.
PV_DX = (0.035, 0.110)
PV_DY = (0.000, 0.058)

# L'orange des PV courants. Même famille que le masque d'étoiles des
# champions ; seuil bas volontairement permissif (sur la capture du
# 04/11 le glyphe reste détecté jusqu'à une saturation de 40).
ORANGE_BAS = (5, 80, 80)
ORANGE_HAUT = (30, 255, 255)

# Un glyphe de chiffre fait ~15×22 px (aire mesurée : 203). La borne
# écarte les miettes d'anticrénelage et les grands aplats colorés.
AIRE_GLYPHE = (60, 600)

# Deux chiffres d'un même nombre ont la même hauteur. Même borne que
# `digits.UNKNOWN_HEIGHT_BAND`, et pas une de plus : UNE SEULE BORNE
# PAR GRANDEUR LUE.
HAUTEURS_EGALES = digits.UNKNOWN_HEIGHT_BAND[1]

Verdict = namedtuple("Verdict", "gagne verdict raison pv")
# Ce que porte la bande : les PV courants (orange), le maximum (crème),
# et le NOMBRE de glyphes oranges trouvés. Ce dernier n'est pas un
# détail d'implémentation : « aucun orange » et « de l'orange qu'on ne
# sait pas lire » sont deux états que le juge doit distinguer, et les
# confondre, c'est le bogue du 08/11/2026.
LecturePV = namedtuple("LecturePV", "courant maximum orange")


def _a_sa_place(screen, centre, position, tolerance):
    """
    Le repère est-il là où la chose qu'il nomme est écrite ?

    Tout en RATIOS de l'écran, des deux côtés : `centre` vient de
    `best_match`, donc en pixels de CETTE capture-là, et c'est la capture
    qui donne l'échelle.
    """
    if centre is None:
        return False
    hauteur, largeur = screen.shape[:2]
    if hauteur == 0 or largeur == 0:
        return False
    return (abs(centre[0] / largeur - position[0]) <= tolerance[0]
            and abs(centre[1] / hauteur - position[1]) <= tolerance[1])


def _gabarit_taille(chemin):
    """`(hauteur, largeur)` d'un gabarit, ou None s'il manque."""
    image = cv2.imread(chemin, cv2.IMREAD_UNCHANGED)
    return None if image is None else image.shape[:2]


def _chercher(screen, chemin):
    """
    `best_match`, mais une image PLUS PETITE que le gabarit est une
    absence, pas une erreur.

    `cv2.matchTemplate` lève sur ce cas, et `juger` ne s'en protégeait
    que par un plancher de 80 px — alors que le mot fait 135 px de large
    et le cœur 86. Une image de 85 à 134 px de côté faisait donc PLANTER
    le juge, dans un fichier entièrement construit sur « illisible n'est
    pas un verdict ». Jamais vu en jeu (on capture l'écran entier) :
    jamais non plus une raison de lever.
    """
    taille = _gabarit_taille(chemin)
    if taille is None or screen.shape[0] < taille[0] or screen.shape[1] < taille[1]:
        return None, None
    return an.best_match(chemin, screen=screen)


def _zone_attendue(screen, chemin, position, tolerance):
    """
    La PORTION d'écran où le repère est censé être écrit, et son coin.

    ON CHERCHE DANS LA ZONE, ON NE FILTRE PAS APRÈS COUP (08/11/2026).
    `best_match` ne rend que son ARGMAX : chercher sur tout l'écran puis
    refuser le point hors de sa place laisse un concurrent lointain plus
    net MASQUER le vrai mot, au lieu d'être écarté. Mesuré en fondant
    l'écran de victoire sur la liste des défis — la transition même qui a
    motivé ce garde-fou :

        opacité 0,70   mot 0.887 à sa place            -> argmax = le mot
        opacité 0,65   mot 0.835 à sa place            -> argmax = le COMPTEUR
                       compteur 0.862 à 647 px de là      (0.835 ≥ seuil,
                                                           victoire perdue)
        opacité 0,60   mot 0.771, sous le seuil        -> rien, des deux façons

    Une victoire RÉELLE se perdait donc en silence dans cette bande,
    alors que le mot y était encore lisible à sa place. C'est la mesure
    qui justifie ce fichier (pire vrai positif 0.983 DANS la zone contre
    0.456 pour n'importe quel autre écran) : elle a été faite sur la
    carte de scores complète, il fallait que le code la fasse aussi.

    La portion est la boîte de tolérance ÉLARGIE D'UN GABARIT : une
    fenêtre dont le CENTRE est au bord de la boîte doit y tenir ENTIÈRE,
    sinon la boîte réelle serait plus étroite que celle annoncée.
    `_a_sa_place` reste l'arbitre : la portion n'est qu'un champ de
    recherche, elle ne décide de rien.
    """
    taille = _gabarit_taille(chemin)
    if taille is None:
        return None, (0, 0)
    th, tw = taille
    hauteur, largeur = screen.shape[:2]
    x0 = max(0, int((position[0] - tolerance[0]) * largeur) - tw)
    x1 = min(largeur, int((position[0] + tolerance[0]) * largeur) + tw)
    y0 = max(0, int((position[1] - tolerance[1]) * hauteur) - th)
    y1 = min(hauteur, int((position[1] + tolerance[1]) * hauteur) + th)
    if x1 - x0 < tw or y1 - y0 < th:
        return None, (0, 0)
    return screen[y0:y1, x0:x1], (x0, y0)


def _mot_de_victoire(screen):
    """
    Le mot « VICTOIRE » LÀ OÙ IL DOIT ÊTRE : `(score, point)` sur l'écran.

    Le point est rendu en pixels de l'écran entier, pas de la portion :
    c'est lui qu'on repasse à `_a_sa_place`, et un point relatif y
    mentirait.
    """
    portion, coin = _zone_attendue(screen, an.TEMPLATES[ANCRE_VICTOIRE],
                                   POSITION_VICTOIRE, TOLERANCE_VICTOIRE)
    if portion is None:
        return None, None
    score, point = _chercher(portion, an.TEMPLATES[ANCRE_VICTOIRE])
    if point is None:
        return score, None
    return score, (point[0] + coin[0], point[1] + coin[1])


def _avertir_mot_ailleurs(screen):
    """
    Dire tout haut qu'on a VU le mot, ailleurs — on ne se tait pas sur un
    repère qu'on refuse.

    C'est le seul moyen de s'apercevoir, un jour, que l'en-tête a glissé
    au-delà de la tolérance : le juge rendrait None, ce qui est le bon
    sens de l'erreur, mais une perte muette.
    """
    score, point = _chercher(screen, an.TEMPLATES[ANCRE_VICTOIRE])
    if score is None or score < SEUIL_ANCRE:
        return
    logging.warning("Bilan de fin : le mot « VICTOIRE » est lu (%.2f) en %s, hors de "
                    "sa place (attendue vers %s) — c'est le compteur « VICTOIRES "
                    "TOTALES » d'un autre écran, aucune victoire prononcée.",
                    score, point,
                    (int(POSITION_VICTOIRE[0] * screen.shape[1]),
                     int(POSITION_VICTOIRE[1] * screen.shape[0])))


def _bande_pv(screen, centre):
    """La bande d'image qui contient « <courant> / <max> »."""
    hauteur, largeur = screen.shape[:2]
    cx, cy = centre
    x0 = max(0, int(cx + PV_DX[0] * largeur))
    x1 = min(largeur, int(cx + PV_DX[1] * largeur))
    y0 = max(0, int(cy + PV_DY[0] * hauteur))
    y1 = min(hauteur, int(cy + PV_DY[1] * hauteur))
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0, 3), np.uint8)
    return screen[y0:y1, x0:x1]


def _glyphes_orange(bande):
    """Les taches oranges de la bande : les chiffres des PV courants."""
    if bande.size == 0:
        return []
    hsv = cv2.cvtColor(bande, cv2.COLOR_BGR2HSV)
    masque = cv2.inRange(hsv, ORANGE_BAS, ORANGE_HAUT)
    nombre, _, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    return [stats[i] for i in range(1, nombre)
            if AIRE_GLYPHE[0] <= stats[i][cv2.CC_STAT_AREA] <= AIRE_GLYPHE[1]]


def _glyphes_creme(bande):
    """
    Les glyphes NON oranges de la bande, de gauche à droite.

    Rend `[(x, hauteur, chiffre|None)]`. Le chiffre n'est posé que pour
    une lecture SÛRE — les paliers `CONFIDENT_*` de `digits`, la même
    exigence que `digits.read_number` par défaut. Un glyphe non reconnu
    n'est pas jeté : il garde sa place dans la liste, parce que c'est
    lui, le séparateur « / », qui prouve la mise en page.
    """
    if bande is None or bande.size == 0:
        return []
    lus = []
    for x, _y, _w, hauteur, composante in digits.glyph_boxes(digits.glyph_mask(bande)):
        chiffre, score, marge = digits.match_glyph(composante)
        certain = (chiffre is not None
               and score >= digits.CONFIDENT_SCORE
               and marge >= digits.CONFIDENT_MARGIN)
        lus.append((x, hauteur, chiffre if certain else None))
    return lus


def _assembler(chiffres, minimum):
    """Un nombre à partir de glyphes voisins, ou None au moindre doute."""
    if not chiffres:
        return None
    hauteurs = [hauteur for _x, hauteur, _chiffre in chiffres]
    if max(hauteurs) > HAUTEURS_EGALES * min(hauteurs):
        return None
    valeur = int("".join(str(chiffre) for _x, _h, chiffre in chiffres))
    if not minimum <= valeur <= NEXUS_HEALTH_MAX:
        return None
    return valeur


def _nombres_creme(bande):
    """
    Les DEUX nombres crème de la bande : `(courant, maximum)`.

    On lit de DROITE à GAUCHE : on ramasse les chiffres sûrs en partant
    du dernier glyphe, et on s'arrête au premier qui n'en est pas — le
    séparateur. Exiger qu'un glyphe PRÉCÈDE le nombre, c'est exiger
    d'avoir vu la mise en page « courant / maximum » : un nombre tombé
    seul dans la bande ne prouverait pas qu'on lit au bon endroit.

    Ce qui reste À GAUCHE du séparateur est le nombre COURANT — il n'est
    rendu que s'il est entièrement lisible. Sur un bilan de DÉFAITE il
    est orange, donc invisible à ce masque-ci : mesuré sur la capture du
    04/11, la bande « 0 / 20 » ne laisse que trois glyphes crème,
    `[« / », « 2 », « 0 »]`, et il n'y a RIEN avant le séparateur. C'est
    exactement ce qui distingue un nexus intact d'un panneau dégradé.

    On ne cherche PAS à reconnaître le « / » : il n'a pas de gabarit, et
    s'en donner un reviendrait à apprendre un cas particulier.
    """
    glyphes = _glyphes_creme(bande)
    index = len(glyphes) - 1
    chiffres = []
    while index >= 0 and glyphes[index][2] is not None:
        chiffres.append(glyphes[index])
        index -= 1
    if not chiffres or index < 0:
        # Rien de lisible à droite, ou rien du tout à gauche : ce n'est
        # pas un « X / Y », donc ce n'est pas la bande des PV.
        return None, None
    chiffres.reverse()
    maximum = _assembler(chiffres, 1)
    if maximum is None:
        return None, None
    gauche = glyphes[:index]
    if not gauche or any(chiffre is None for _x, _h, chiffre in gauche):
        return None, maximum
    return _assembler(gauche, 0), maximum


def lire_maximum(bande):
    """
    Le MAXIMUM de PV : le nombre crème, à droite du « / ».

    C'est la preuve que la bande est au bon endroit et que le panneau
    porte bien une mise en page « courant / maximum ». Rend None dès que
    le moindre doute existe — illisible n'est pas un verdict.
    """
    return _nombres_creme(bande)[1]


def lire_pv(screen, centre):
    """
    Ce que porte la bande des PV : `LecturePV(courant, maximum, orange)`.

    `maximum` est le nombre CRÈME, `orange` le nombre de glyphes oranges
    trouvés. `courant` est le nombre de GAUCHE, lu dans l'orange quand il
    y en a, et dans le crème sinon — un nexus au maximum n'a rien à
    afficher en orange, mais il affiche quand même son nombre. Un nombre
    vaut None quand il n'a pas pu être lu : ce n'est jamais un zéro.

    `orange == 0` ne veut pas dire « nexus intact » à soi tout seul : il
    faut alors que la bande se lise « N / N » EN ENTIER, courant compris
    (cf. en-tête). Le juge s'en charge.
    """
    bande = _bande_pv(screen, centre)
    courant_creme, maximum = _nombres_creme(bande)
    glyphes = _glyphes_orange(bande)
    if not glyphes:
        # Pas un seul chiffre orange : les PV courants, s'ils sont
        # affichés, le sont forcément en crème — c'est là qu'on les lit.
        return LecturePV(courant_creme, maximum, 0)

    x0 = min(int(g[cv2.CC_STAT_LEFT]) for g in glyphes)
    y0 = min(int(g[cv2.CC_STAT_TOP]) for g in glyphes)
    x1 = max(int(g[cv2.CC_STAT_LEFT] + g[cv2.CC_STAT_WIDTH]) for g in glyphes)
    y1 = max(int(g[cv2.CC_STAT_TOP] + g[cv2.CC_STAT_HEIGHT]) for g in glyphes)
    marge = 4
    sous = bande[max(0, y0 - marge):y1 + marge, max(0, x0 - marge):x1 + marge].copy()
    if sous.size == 0:
        return LecturePV(None, maximum, len(glyphes))

    # Repeindre l'orange en blanc : digits.glyph_mask l'exclut à dessein.
    hsv = cv2.cvtColor(sous, cv2.COLOR_BGR2HSV)
    sous[cv2.inRange(hsv, ORANGE_BAS, ORANGE_HAUT) > 0] = (255, 255, 255)
    return LecturePV(digits.read_number(sous, maximum=NEXUS_HEALTH_MAX),
                     maximum, len(glyphes))


def juger(screen=None):
    """
    Le verdict que porte l'écran affiché, ou None si ce n'est pas lui.

    Ne clique rien, n'attend rien : une image, une réponse.
    """
    if screen is None:
        screen = an._capture_screen_bgr()
    if screen is None or screen.size == 0 or min(screen.shape[:2]) < 80:
        return None

    # L'ÉCRAN DE VICTOIRE EN PREMIER : il n'a ni cœur ni PV, et c'est le
    # seul des deux qu'on a vu conclure une aventure gagnée.
    #
    # MAIS LE MOT DOIT ÊTRE À SA PLACE (08/11/2026). Le gabarit est aussi
    # trouvé, au-dessus du seuil, sur le compteur « (22 VICTOIRES
    # TOTALES) » de la liste des défis et du panneau de reprise — deux
    # écrans que le bot traverse à CHAQUE tentative, à 647 px de là où un
    # vrai écran de victoire écrit son mot. Un score élevé ne prouve que
    # la fidélité du gabarit, jamais la justesse de la lecture.
    # ET ON CHERCHE DANS LA ZONE, plutôt que de filtrer l'argmax après
    # coup (cf. `_zone_attendue`) : sinon le compteur, plus net, masque le
    # mot au lieu d'être écarté, et c'est une VRAIE victoire qui se perd.
    score_victoire, point = _mot_de_victoire(screen)
    if (score_victoire is not None and score_victoire >= SEUIL_ANCRE
            and _a_sa_place(screen, point, POSITION_VICTOIRE, TOLERANCE_VICTOIRE)):
        return Verdict(True, "écran de victoire",
                       "victoire (écran de fin de défi)", None)
    _avertir_mot_ailleurs(screen)

    score, centre = _chercher(screen, an.TEMPLATES[ANCRE])
    if score is None or score < SEUIL_ANCRE or centre is None:
        return None

    lu = lire_pv(screen, centre)
    if lu.orange == 0:
        # UNE VICTOIRE NE SE PROUVE PAS PAR UNE ABSENCE (08/11/2026).
        # Pas de chiffre orange, c'est soit un nexus au maximum, soit un
        # panneau dégradé — et la SEULE preuve qui les départage est de
        # lire « N / N » en entier, courant compris. Le maximum seul ne
        # suffit pas : il est crème, donc il survit à un fondu enchaîné
        # qui a déjà effacé l'orange (mesuré, cf. en-tête).
        if lu.maximum is None:
            logging.warning("Bilan de fin : cœur trouvé (%.2f), aucun chiffre orange, "
                            "mais le maximum ne se lit pas non plus — panneau pas "
                            "encore dessiné, aucun verdict rendu.", score)
            return None
        if lu.courant != lu.maximum:
            logging.warning("Bilan de fin : cœur trouvé (%.2f), maximum lu (%s), mais les "
                            "PV courants ne se lisent pas « %s / %s » (lus : %s) — panneau "
                            "dégradé, aucun verdict rendu.",
                            score, lu.maximum, lu.maximum, lu.maximum, lu.courant)
            return None
        return Verdict(True, f"bilan de fin (nexus intact, {lu.maximum}/{lu.maximum})",
                       f"victoire (bilan : nexus intact, {lu.maximum} PV)", lu.maximum)
    if lu.courant is None:
        logging.warning("Bilan de fin : cœur trouvé (%.2f) mais PV illisibles — "
                        "aucun verdict rendu.", score)
        return None
    if lu.courant <= 0:
        return Verdict(False, "bilan de fin (0 PV)",
                       "défaite (bilan : nexus à 0)", 0)
    return Verdict(True, f"bilan de fin ({lu.courant} PV)",
                   f"victoire (bilan : {lu.courant} PV restants)", lu.courant)


def attendre_verdict(timeout=ATTENTE_VERDICT, intervalle=INTERVALLE_VERDICT):
    """
    Regarde l'écran jusqu'à ce qu'il porte un verdict, ou renonce.

    Mesuré le 05/11/2026 : l'écran de victoire s'affiche SEPT SECONDES
    après le moment où le juge était appelé. Une seule image, c'était
    jouer à pile ou face ; on regarde donc pendant quelques secondes.
    Rend None si rien n'a été lisible — jamais un verdict inventé.
    """
    fin = time.time() + timeout
    while True:
        verdict = juger()
        if verdict is not None:
            return verdict
        if time.time() >= fin:
            return None
        time.sleep(intervalle)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    screen = cv2.imread(sys.argv[1]) if len(sys.argv) > 1 else None
    if len(sys.argv) > 1 and screen is None:
        print(f"Capture illisible : {sys.argv[1]}")
        raise SystemExit(1)
    verdict = juger(screen)
    if verdict is None:
        print("Ce n'est pas un écran de bilan de fin de tentative "
              "(ou les PV sont illisibles) — aucun verdict.")
        return
    print(f"{'VICTOIRE' if verdict.gagne else 'DÉFAITE'} — {verdict.raison}")


if __name__ == "__main__":
    main()
