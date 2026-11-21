"""
Lire à l'écran les MOTS-CLÉS d'une unité — y compris ceux ACCORDÉS en jeu.

POURQUOI CE MODULE EXISTE (14/11/2026). `CLAUDE.md` annonce ce chantier
depuis le début : « `keywords.has()` est le SEUL point qui interroge une
carte ; c'est là qu'on branchera un jour la lecture des mots-clés
ACCORDÉS ». Aujourd'hui le bot ne lit que les mots-clés IMPRIMÉS, pris
dans `card_sets` (2254 cartes sur 2898). Un Overwhelm donné par un sort,
une Barrier posée ce round, un Challenger accordé : invisibles — comme
l'était le Stun avant `stun.py`. L'API ne rend que SEPT champs :
CardCode, CardID, LocalPlayer et la géométrie.

CE QUE LE JEU DESSINE, ET OÙ
----------------------------
Sur chaque unité DU PLATEAU, le jeu pose une barre noire hexagonale
portant une icône par mot-clé — SOUS l'illustration chez nous, AU-DESSUS
chez l'adversaire (ses statistiques et sa barre sont inversées). Mesuré
le 21/11/2026 sur NEUF unités : celles des scènes du 20 et du 21/11
qui sont de NOTRE côté (les cinq Pâle orchestre, les deux Kennen, les
deux Viktor). Les trois porteuses du 14/11 en sont absentes parce que
le repère n'y est pas net — sur Swain et Legion Saboteur la composante
sombre se prolonge dans l'illustration, comme elle le fait chez
l'adversaire. Le bandeau se détecte lui-même (la composante sombre,
V < 70, qui touche la colonne du centre) ; coordonnées RELATIVES à
`card.center` :

      le bandeau occupe   dy +47 à +89 chez nous (enveloppe des neuf) ;
                          en face, seul son bord HAUT est net : -88 (sa
                          composante sombre s'y prolonge dans
                          l'illustration, elle n'a donc pas de bord bas
                          mesurable)
      sa demi-largeur     65 px (Pâle orchestre) à 71 px (Kennen, Viktor)
      une icône fait      12 à 34 px de côté, aire ≥ 60 px

La bande LUE descend jusqu'à +82 chez nous : le liseré bleu du plateau
monte jusqu'à dy +79 sous nos unités et fusionne avec les icônes qu'il
touche (voir `BARRE_DY_BAS`). Côté adverse, le bord bas de la bande
n'est PAS déduit d'une symétrie — il est mesuré par balayage, voir
`BARRE_ADVERSE_DY_BAS`.

AU-DELÀ DE QUATRE MOTS-CLÉS, LE JEU TASSE LES ICÔNES SUR DEUX NIVEAUX
en quinconce — centres mesurés à dy +59..+62 pour la rangée du haut,
+74..+78 pour celle du bas, le bandeau gardant la même hauteur. C'est
ce que ni la scène du 14/11 (≤ 5 icônes alignées) ni celle du 20/11
(4 alignées) ne pouvaient montrer.

Les icônes se répartissent en TROIS FAMILLES DE COULEUR, orange, bleu
clair et magenta (ce dernier ajouté le 20/11/2026, cf. `MAGENTA`
ci-dessous), nettes et franches sur fond noir.

CE QUI EST MESURÉ, ET CE QUI NE L'EST PAS
-----------------------------------------
Quatre scènes, dont trois étiquetées par Ewan. Les comptes ci-dessous
sont ceux du 21/11/2026 (recomptés le même jour, voir plus bas) ; la
colonne « icônes » est le nombre d'icônes VISIBLES sur la capture,
« boîtes » ce que `icones()` rend. **Une ligne « ×N » vaut N vignettes,
et les deux colonnes y sont données PAR VIGNETTE** — c'est le piège qui
a fait écrire un total faux la première fois.

      scène    unité                     imprimés  icônes  boîtes
      14/11    Swain                         1       5      5
      14/11    Enraged Firespitter           1       2      2
      14/11    Legion Saboteur               0       1      1
      14/11    Arachnoid Sentry              0       0      0
      14/11    House Spider      (adverse)   0       0      0
      14/11    Spiderling        (adverse)   0       0      0
      14/11    Imperial Demol.   (adverse)   0       0      0
      20/11    Pâle orchestre ×5             2       4      4
      20/11    Vaults of Helia   (adverse)   1       1      1
      20/11    Cursed Keeper     (adverse)   2       2      1
      21/11    Kennen (capture kennen)       1       6      5
      21/11    Kennen (capture victor)       1       6      5 ⚠ dont 1 FAUX
      21/11    Viktor gauche                 1       7      5
      21/11    Viktor droite                 1       7      4
      21/11    Powder Keg ×2     (adverse)   2       3      2
      21/11    Jagged Butcher    (adverse)   1       0      0

      TOTAL, lignes ×N développées :
          21 unités de plateau (16 porteuses, 5 vierges dont 4 adverses)
          63 icônes visibles — 53 boîtes, dont 1 FAUSSE — 52 vraies
          → 11 icônes n'ont pas de boîte à elles

**LA PRÉSENCE RESTE LA PROMESSE PRINCIPALE, ET ELLE EST INTACTE** : les
5 unités sans barre (dont 4 adverses) rendent zéro, et les 16 qui en ont
une rendent au moins une icône. Zéro faux positif, zéro faux négatif sur
la PRÉSENCE.

**LE COMPTE, LUI, N'EST PAS EXACT, ET PAS SEULEMENT PAR DÉFAUT.** La
première version de ce tableau annonçait « huit icônes manquantes sur
quarante-six » ; les deux nombres étaient faux (les lignes « ×N »
n'avaient pas été développées) et la colonne « lues » confondait « une
boîte est sortie » avec « la bonne icône a été vue ». Le relevé exact,
boîte par boîte :

  LES 11 ICÔNES SANS BOÎTE, par capture — les causes de MASQUE d'abord :
  - Kennen (capture kennen), 1 : le CERCLE ROUGE (lexique : Régénération)
    sort aux teintes 2 à 11 quand `ORANGE` commence à 8 — 55 px sur 202
    passent, il ne reste qu'un ruban de 19×8, refusé par la hauteur ;
  - Kennen (capture victor), 2 : le MÊME cercle rouge (ruban 19×8), plus
    l'icône de NIVEAU, dont le masque ne laisse ici qu'un 19×11 —
    **1 px sous `ICONE_COTE_MIN`**, alors que sur l'autre capture la
    même icône sort en 28×25. Deux captures de la même carte, deux
    résultats : c'est ce qui interdit de récolter un gabarit à l'INDEX
    (voir `cut_icone`) ;
  - Powder Keg ×2, 1 chacune : la CROIX BLANCHE d'Immobile, saturation
    médiane 17 — aucune des trois familles ne la couvre ;
  - Cursed Keeper, 1 : le BOUCLIER BLANC de « Can't Block », même cause ;
  - Viktor gauche, 2 : la TOUR DORÉE (lexique : position 4, Immortalité —
    elle avait d'abord été décrite « Robuste », cf. CLAUDE.md, « la
    vérité terrain est une POSITION, pas une description ») touche le
    liseré doré du cadre et forme avec lui une composante de 94×11 ; et
    la FLAMME BLEUE fait 10×13, sous `ICONE_COTE_MIN` ;
  - Viktor droite, 3 : la tour dorée (idem), un ruban de 17×8 en dx
    +40..+57 (même symptôme que le cercle rouge de Kennen), et une
    troisième que la FUSION ci-dessous peut avoir avalée.

  ET QUATRE BOÎTES ATTEIGNENT LES DEUX RANGÉES À LA FOIS — mesuré, et
  nommées une par une dans `test_les_deux_rangees_dune_barre_tassee_ne_
  se_confondent_pas` : deux vraies fusions (Viktor), une composante
  connexe trop haute (Viktor droite) et le halo (Kennen). Une boîte qui
  couvre deux rangées peut contenir deux icônes : le compte « 11 sans
  boîte » est donc un MAJORANT du nombre d'icônes vraiment perdues, et
  un minorant du nombre de boîtes inutilisables pour un gabarit.

Élargir les familles est un changement de MASQUE : il déplacerait aussi
les quatre gabarits existants, qui sont découpés par ce masque-là. C'est
la tâche qui récolte les gabarits qui devra le faire, pas celle-ci.

**L'IDENTIFICATION EST FAITE POUR QUATRE MOTS-CLÉS, ET C'EST TOUT**
(20/11/2026). Ewan a étiqueté une scène de cinq Pâle orchestre (06SI009)
dans l'ordre « Ephemeral, Hallowed, Challenger, Overwhelm » : la
première fois que l'identité d'une icône vient d'un fait de jeu, pas
d'une ressemblance à l'œil. `identifier()` compare chaque glyphe
DÉCOUPÉ (`decouper`) aux gabarits de `mots_cles/` par le chemin de
`digits.py` (IoU, égalisation du trait, rapport d'aspect conservé) et
ne rend que ce qui franchit SCORE_SUR ET MARGE_SURE. Les seize autres
mots-clés n'ont aucun gabarit : une icône qui leur appartient reste,
à dessein, ABSENTE du tuple rendu — jamais devinée. `keywords.has()`
reste donc non branché pour tout ce qui dépasse ces quatre-là.

LES GABARITS SONT DÉCOUPÉS PAR LE CHEMIN DE LECTURE, DONC ILS SUIVENT
LA SEGMENTATION (21/11/2026). Celle-ci ayant changé, les huit PNG de
`mots_cles/` ont été redécoupés sur la MÊME capture, aux MÊMES centres
et dans le MÊME ordre étiqueté par Ewan — aucune identité nouvelle n'a
été inventée. C'est la règle que `cut_icone` énonce et que le piège de
`cut_defi` (08/11) a payée : une forme découpée autrement ne se
reconnaît plus elle-même. Au passage, Sanctification est désormais
ENTIÈRE : son gabarit était tronqué à 16×22 parce que le recollage par
colonne laissait tomber le chevron qui la termine (23×22 avec lui).

MESURE DE L'IDENTIFICATION (refaite le 21/11/2026) sur les trois Pâle
orchestre qui n'ont PAS servi à récolter les gabarits (centres
(959, 900), (1115, 900), (1272, 900) — les sources sont (645, 900) et
(802, 900)), plus la validation croisée du 14/11 :

      pire score    0.710   (Provocateur sur Firespitter, capture du 14/11)
      pire marge    0.317   (le même glyphe)
      vrais positifs            score 0.710 à 1.000 | marge 0.317 à 0.676
      glyphes ÉTRANGERS         score ≤ 0.472       | marge ≤ 0.126

Les étrangers sont désormais les 22 glyphes des scènes du 14/11 et du
21/11 dont AUCUN n'a de gabarit — les onze types nommés par Ewan
compris. Aucun n'est identifié : le plancher de SCORE_SUR (0.60) les
refuse tous, avec 0.128 de marge sous le meilleur d'entre eux et 0.11
au-dessus du pire vrai positif.

CE QUE ÇA PERMET DÉJÀ. Une unité SANS mot-clé imprimé qui porte une
icône a forcément été RENFORCÉE en jeu — et c'est observé : Legion
Saboteur (01NX040, `keywords=[]`) porte une icône bleue. C'était le seul
verdict de ce module jusqu'au 20/11 ; `identifier()` en rend désormais
un second, plus fort — le NOM du mot-clé — mais seulement pour les
quatre dont on a un gabarit. Celui-ci reste le plus robuste des deux :
il ne demande aucun gabarit, et il est sans ambiguïté.

PIÈGES MESURÉS ET ÉCARTÉS
-------------------------
  - LA BARRE NOIRE SEULE. « Le plus long segment sombre sous la carte »
    donne 109 px pour Swain mais 62 px pour Legion Saboteur (UNE icône)
    contre 55 px pour Firespitter (DEUX) : la largeur ne compte pas les
    icônes, elle suit l'illustration. Et Arachnoid Sentry, qui n'a
    aucune barre, atteint quand même 34 px d'ombre.
  - LA COULEUR SANS BORNE VERTICALE. Compter les pixels orange ou bleus
    sous la carte sature à 100 % pour TOUT LE MONDE : le liseré bleu
    électrique du plateau et la rangée suivante entrent dans la fenêtre.
    C'est la fenêtre verticale qui les exclut, pas la teinte.
  - LE CLAIR DANS LE BANDEAU SOMBRE, au lieu des familles de couleur
    (essayé le 21/11/2026). Segmenter « tout ce qui est brillant à
    l'intérieur du rectangle noir » voit TOUT, y compris le cercle
    rouge et la croix blanche : Kennen passe à 6 icônes sur 6 et Powder
    Keg à 3 sur 3, du premier coup. Mais les glyphes y grossissent du
    bord inférieur du bandeau (Provocateur 23×30 au lieu de 23×22) et
    **Sanctification cesse d'être identifiée sur deux à quatre des cinq
    Pâle orchestre, à tous les seuils de clarté essayés (120, 140, 160,
    180)**. Changer de masque, c'est refaire les gabarits : ça
    appartient à la tâche qui les récolte.
  - L'ENVELOPPE CONVEXE DU BANDEAU comme masque spatial : elle déborde
    sur les coins de l'hexagone et le liseré du plateau y rentre
    (Kennen, une 7e boîte de 31×14 px). Le remplissage ligne à ligne de
    la composante sombre, lui, perd les glyphes qui touchent le bord du
    bandeau — deux icônes sur quatre du Pâle orchestre.

QUATRE SCÈNES, DÉSORMAIS (mis à jour le 21/11/2026). La géométrie du
bandeau est mesurée sur les neuf unités de NOTRE côté, et par balayage
côté adverse (cf. `BARRE_ADVERSE_DY_BAS`). L'IDENTIFICATION repose sur
la scène du 20/11/2026 (cinq Pâle orchestre étiquetés par Ewan) avec
Firespitter (14/11) en validation croisée ; les onze types de glyphes
nommés par Ewan le 21/11 n'ont AUCUN gabarit et servent de témoins
NÉGATIFS.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

import digits

# UNE DÉGRADATION MUETTE EST LE PIRE DÉFAUT DU PROJET. Ce module peut
# cesser de rendre un mot-clé sans que rien ne casse : gabarit sans
# alpha, dossier `mots_cles/` vidé, bande décalée. Tout ce qui le fait
# RETOMBER sur le comportement d'avant passe donc par ce logger.
LOGGER = logging.getLogger(__name__)

# La barre d'icônes, en coordonnées relatives à `card.center`.
#
# OÙ EST LE BANDEAU, MESURÉ (21/11/2026). Le rectangle noir se détecte
# tout seul (la composante sombre, V < 70, qui touche la colonne du
# centre) : sur les NEUF unités du 20 et du 21/11 qui sont de NOTRE côté
# (cf. le relevé en tête de module) il occupe **dy +47..+89** —
# enveloppe des neuf, de +47 (Pâle orchestre) à +89 (Kennen sur la
# capture `victor`). Sa demi-largeur va de 65 (Pâle orchestre) à 71 px
# (Kennen, Viktor).
#
# CÔTÉ ADVERSE, SEUL LE BORD HAUT EST MESURABLE : **-88**. La composante
# sombre s'y prolonge dans l'illustration, donc le bandeau n'a pas de
# bord bas net, et on NE SUPPOSE PAS la symétrie — voir
# `BARRE_ADVERSE_DY_BAS`, dont la valeur vient d'un balayage.
#
# ON NE LIT PAS LE BANDEAU ENTIER DE NOTRE CÔTÉ, ET C'EST MESURÉ. Le
# liseré bleu du plateau MONTE jusqu'à dy +79 sous nos unités et touche
# les icônes : porter `BARRE_DY_BAS` de 82 à 88 (le vrai bas du bandeau)
# fait fusionner Sanctification avec ce liseré en une composante de
# 118×32 px, et le Pâle orchestre tombe de 4 icônes à 3 sur DEUX des
# cinq vignettes du 20/11, plus une icône fantôme sur une troisième. On
# garde donc +82 et on accepte que le bas d'un glyphe de la rangée
# inférieure soit rogné (Kennen : épée lue +70..+82 au lieu de +70..+86)
# — un glyphe rogné reste compté, un glyphe fusionné est perdu.
#
# CÔTÉ ADVERSE IL N'Y A PAS DE LISERÉ AU-DESSUS DES CARTES, et la bande
# y est BORNÉE PAR BALAYAGE, pas par symétrie (21/11/2026). Les icônes
# adverses occupent **dy -82..-56** sur les quatre unités porteuses
# (Powder Keg ×2, Cursed Keeper, Vaults of Helia). En faisant varier le
# bord bas px par px, le compte — 2, 2, 1, 1 sur les porteuses et ZÉRO
# sur les quatre vierges — est **stable de -66 à -41** ; le PREMIER faux
# positif apparaît à **-40** (Powder Keg passe à 3 : une composante
# 28×12 à dy -52..-40, sous le bandeau, dans le cadre de la carte).
# -48 est au milieu de ce plateau de 26 px, à 8 px du premier faux
# positif. Au-dessus, -70 fait perdre Cursed Keeper et -68 les deux
# Powder Keg, tandis que le compte tient sans une seule fausse boîte
# jusqu'à -120 : **-88 a 17 px de marge du bon côté, et aucune du
# mauvais, parce qu'il n'y en a pas à avoir.**
BARRE_DY_HAUT = 47
BARRE_DY_BAS = 82
BARRE_ADVERSE_DY_HAUT = 88      # distance AU-DESSUS du centre
BARRE_ADVERSE_DY_BAS = 48
BARRE_DEMI_LARGEUR = 80

# Une icône : ni un éclat de décor, ni la barre entière.
ICONE_COTE_MIN, ICONE_COTE_MAX = 12, 34
ICONE_AIRE_MIN = 60

# UN GLYPHE FRAGMENTÉ N'EST PAS TROIS PETITES ICÔNES (20/11/2026).
# Le glyphe « Surpuissance » (orange, teinte 19, Pâle orchestre 06SI009)
# a une ombre interne qui coupe son masque en plusieurs morceaux — un
# trait du GLYPHE, pas de la famille de couleur : 22×11 (aire 117) +
# 9×8 (52) + 4×8 (23) + 16×8 (61), alors que le glyphe ENTIER fait
# 22×24. Abaisser `ICONE_COTE_MIN` à 11 n'aurait laissé passer QUE le
# plus gros fragment (22×11, toujours pas le bon rectangle) — et rien
# n'aurait rougi si `icones()` avait un jour tort sur le DÉCOUPAGE,
# puisque les cinq vignettes de la scène se fragmentent à l'identique
# (auto-cohérence sans vérité : le piège de `cut_defi` le 08/11).
# `icones()` recolle donc les fragments voisins avant de juger leur
# taille. Sont exclus de la fusion les fragments sous
# `FRAGMENT_AIRE_MIN` (bruit d'antialiasing/compression, jamais un bout
# de glyphe réel).
FRAGMENT_AIRE_MIN = 20

# LE RECOLLAGE PAR COLONNE SUPPOSAIT UNE SEULE LIGNE (corrigé le
# 21/11/2026). Au-delà de quatre mots-clés le jeu TASSE les icônes sur
# DEUX niveaux en quinconce : chaîner les fragments par leurs seules
# plages en x mariait alors une icône du haut à sa voisine du bas (elles
# se chevauchent en x de 5 px sur Viktor), la boîte dépassait
# `ICONE_COTE_MAX`, et le repli rejugeait chaque fragment seul — une
# icône sur deux perdue ou fragmentée (mesuré : 5 boîtes pour 7 icônes,
# 4 pour 6, 4 pour 7).
#
# ON AGGLOMÈRE DONC LES PLUS PROCHES D'ABORD, ET JAMAIS AU-DELÀ DE LA
# TAILLE D'UN GLYPHE. Deux mesures fixent `ECART_FRAGMENT` : les
# fragments d'UN MÊME glyphe sont séparés de 0 ou 1 px (Surpuissance :
# 0 partout ; le symbole cyan de Kennen : 1), tandis que deux icônes
# voisines de la MÊME rangée sont séparées de 1 à 9 px — c'est donc le
# plafond de taille, et non l'écart, qui les sépare (Challenger +
# Surpuissance feraient 51 px de large).
ECART_FRAGMENT = 1

# UNE ICÔNE EST POSÉE SUR LE BANDEAU NOIR (21/11/2026). C'est ce qui la
# distingue d'un éclat d'illustration de la même couleur, et c'est la
# seule chose qui le fasse : la teinte, la taille et l'aire ne suffisent
# pas. Mesuré sur les quatre captures, luminosité MÉDIANE de l'anneau de
# 3 px qui entoure chaque boîte retenue : **19 à 38 pour les vraies
# icônes**, **139 et 193 pour les deux taches d'illustration** qui
# passaient tous les autres gardes (le liseré violet du bord de carte
# sous House Spider, et la tache de l'illustration que Legion Saboteur
# comptait comme une seconde icône depuis le 14/11). Le plancher laisse
# 32 de marge de chaque côté.
FOND_SOMBRE_MAX = 70
MARGE_ANNEAU = 3

# Les familles de couleur, en HSV OpenCV. Franches sur fond noir.
ORANGE = ((8, 130, 120), (28, 255, 255))
BLEU = ((88, 100, 120), (112, 255, 255))

# TROIS FAMILLES, PAS DEUX (20/11/2026). Mesuré sur les quatre icônes du
# Pâle orchestre (06SI009), étiquetées par Ewan : Éphémère sort à la
# teinte 144, Sanctification à 95, Challenger à 16, Surpuissance à 19.
# Les deux premières familles dataient du 14/11 et laissaient le sablier
# d'Éphémère dans l'angle mort — une icône VUE et jamais comptée.
MAGENTA = ((132, 90, 110), (156, 255, 255))


def _masque_icones(image) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masque = None
    for basse, haute in (ORANGE, BLEU, MAGENTA):
        bande = cv2.inRange(hsv, np.array(basse), np.array(haute))
        masque = bande if masque is None else cv2.bitwise_or(masque, bande)
    return masque


def _est_un_glyphe(largeur: int, hauteur: int, aire: int) -> bool:
    """Une taille et une aire de glyphe plausibles — le SEUL juge de
    taille, qu'on l'applique à un fragment brut ou à une boîte recollée."""
    return (ICONE_COTE_MIN <= largeur <= ICONE_COTE_MAX
            and ICONE_COTE_MIN <= hauteur <= ICONE_COTE_MAX
            and aire >= ICONE_AIRE_MIN)


def _boite_recollee(fragments: list) -> tuple:
    """Boîte englobante d'un groupe de fragments, et la somme de leurs
    aires (une aire de pixels ne se moyenne pas, elle s'additionne)."""
    x0 = min(f[0] for f in fragments)
    y0 = min(f[1] for f in fragments)
    x1 = max(f[0] + f[2] for f in fragments)
    y1 = max(f[1] + f[3] for f in fragments)
    aire = sum(f[4] for f in fragments)
    return (x0, y0, x1 - x0, y1 - y0, aire)


def _ecart(a: tuple, b: tuple) -> int:
    """Le plus grand des deux écarts (en x, en y) entre deux boîtes ;
    zéro si elles se touchent ou se chevauchent sur cet axe."""
    ex = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0)
    ey = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0)
    return max(ex, ey)


def _trop_grand(largeur: int, hauteur: int) -> bool:
    """Cette boîte dépasse-t-elle la taille d'un glyphe ? C'est le seul
    plafond de l'agglomération : il empêche le liseré du plateau (87×24
    px sous Kennen) et la tache de bordure de Firespitter (40×30) de
    servir de pont entre des icônes qu'ils touchent sans leur
    appartenir, et il sépare les deux rangées d'une barre tassée."""
    return largeur > ICONE_COTE_MAX or hauteur > ICONE_COTE_MAX


def _grouper(fragments: list) -> list:
    """
    Agglomère les fragments d'un même glyphe : la paire la plus PROCHE
    d'abord, et jamais une boîte plus grande qu'un glyphe.

    L'ordre compte, et il est la moitié du correctif du 21/11/2026 : sur
    le Pâle orchestre, les quatre morceaux de Surpuissance se touchent
    (écart 0) alors que Surpuissance et Challenger sont séparés de 1 px.
    En fusionnant les écarts nuls d'abord, Surpuissance se reforme
    (26×24) et le couple qu'elle forme ensuite avec Challenger (51 px de
    large) est refusé par la taille. Fusionner dans l'ordre de lecture
    aurait soudé les deux et perdu l'une des deux icônes.
    """
    paquets = [[f] for f in fragments]
    boites = list(fragments)
    while True:
        meilleur = None
        for i in range(len(paquets)):
            for j in range(i + 1, len(paquets)):
                ecart = _ecart(boites[i], boites[j])
                if ecart > ECART_FRAGMENT:
                    continue
                union = _boite_recollee([boites[i], boites[j]])
                if _trop_grand(union[2], union[3]):
                    continue
                # Clé totalement ordonnée : écart, puis surface de
                # l'union, puis position — deux exécutions sur la même
                # image doivent rendre le même découpage.
                cle = (ecart, union[2] * union[3], union[0], union[1])
                if meilleur is None or cle < meilleur[0]:
                    meilleur = (cle, i, j, union)
        if meilleur is None:
            return paquets
        _, i, j, union = meilleur
        paquets[i] = paquets[i] + paquets[j]
        boites[i] = union
        del paquets[j]
        del boites[j]


def _pose_sur_le_bandeau(fond, boite: tuple) -> bool:
    """
    Cette boîte est-elle posée sur le bandeau NOIR ?

    On lit la luminosité médiane de l'anneau de `MARGE_ANNEAU` px qui
    l'entoure : une icône est cernée de noir, un éclat d'illustration
    est cerné d'illustration. Voir `FOND_SOMBRE_MAX` pour les mesures.
    """
    x, y, largeur, hauteur, _ = boite
    hauteur_bande, largeur_bande = fond.shape
    gx0, gy0 = max(0, x - MARGE_ANNEAU), max(0, y - MARGE_ANNEAU)
    gx1 = min(largeur_bande, x + largeur + MARGE_ANNEAU)
    gy1 = min(hauteur_bande, y + hauteur + MARGE_ANNEAU)
    autour = fond[gy0:gy1, gx0:gx1]
    dehors = np.ones(autour.shape, bool)
    dehors[y - gy0:y - gy0 + hauteur, x - gx0:x - gx0 + largeur] = False
    valeurs = autour[dehors]
    return bool(valeurs.size) and float(np.median(valeurs)) < FOND_SOMBRE_MAX


def _icones_et_masque(image, centre: tuple, adverse: bool = False):
    """
    Calcule EN UNE SEULE FOIS le masque de la bande d'icônes et les boîtes
    qu'il contient : (boites, masque), `masque` étant celui dont chaque
    boîte est issue — donc directement tranchable par un appelant qui veut
    aussi les PIXELS d'une icône, pas que sa position.

    `adverse=True` lit la bande EN HAUT de la carte : chez l'adversaire,
    statistiques et barre de mots-clés sont inversées (21/11/2026).

    SOURCE UNIQUE DE LA SEGMENTATION (20/11/2026, revue de la tâche 3).
    `icones()` segmentait, puis `decouper()` segmentait DE NOUVEAU (en
    rappelant `icones()`) pour chaque glyphe demandé : `identifier()`
    payait donc le masque + `connectedComponentsWithStats` + le recollage
    par colonnes UNE fois pour compter, puis ENCORE une fois PAR GLYPHE
    rien que pour en retrouver les boîtes, plus une troisième segmentation
    du masque (strictement identique, même bande) pour en extraire les
    pixels. Pour 4 icônes : 1 + 4 + 4 = 9 segmentations au lieu d'1.

    MESURÉ (tâche 3, 20/11/2026), 5 unités, gabarits en cache (régime réel
    d'un combat) : 49.8-50.9 ms AVANT ce correctif, 43.1-43.6 ms APRÈS —
    voir `game_state.lire_les_mots_cles` pour le chiffrage complet (à
    froid aussi) et sa mise en regard des ~2200 ms d'un instantané.
    `icones()` et `decouper()` restent la même INTERFACE (même signature,
    même contrat, y compris leurs cas limites) ; ils délèguent ici pour ne
    plus JAMAIS pouvoir diverger entre deux chemins de découpe.

    Rend `([], None)` dès qu'on ne peut pas lire — pas d'image, cadre hors
    écran, forme inattendue. Même règle que `stun.mouvement` et
    `bilan.juger` : ne rien pouvoir lire n'est pas un verdict.
    """
    forme = getattr(image, "shape", None)
    if forme is None or len(forme) < 3:
        return [], None
    cx, cy = int(centre[0]), int(centre[1])
    h, w = forme[0], forme[1]
    x0, x1 = cx - BARRE_DEMI_LARGEUR, cx + BARRE_DEMI_LARGEUR
    if adverse:
        y0, y1 = cy - BARRE_ADVERSE_DY_HAUT, cy - BARRE_ADVERSE_DY_BAS
    else:
        y0, y1 = cy + BARRE_DY_HAUT, cy + BARRE_DY_BAS
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return [], None

    bande = image[y0:y1, x0:x1]
    masque = _masque_icones(bande)
    # La luminosité de la bande, pour `_pose_sur_le_bandeau` : calculée
    # UNE fois ici, comme le masque — deux conversions HSV de la même
    # sous-image finiraient par diverger.
    fond = cv2.cvtColor(bande, cv2.COLOR_BGR2HSV)[:, :, 2]
    nombre, _, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    # ON NE FILTRE PAS LES FRAGMENTS TROP GRANDS ICI, ET C'EST MESURÉ :
    # l'agglomération refuse déjà toute union qui dépasse un glyphe, donc
    # un fragment déjà trop grand ne peut fusionner avec rien et finit
    # seul, refusé par `_est_un_glyphe`. Les écarter en tête ne change
    # AUCUN compte sur les quatre captures témoins — un garde de plus
    # sans gain mesuré est un garde de trop.
    fragments = [tuple(int(v) for v in stats[i]) for i in range(1, nombre)
                 if stats[i][4] >= FRAGMENT_AIRE_MIN]

    trouvees = []
    for groupe in _grouper(fragments):
        boite = _boite_recollee(groupe)
        if _est_un_glyphe(boite[2], boite[3], boite[4]):
            # Le groupe ENTIER forme un glyphe plausible : recollé.
            if _pose_sur_le_bandeau(fond, boite):
                trouvees.append(boite)
        elif len(groupe) > 1:
            # Recollé, le groupe n'a pas la taille d'un glyphe — il reste
            # trop pauvre (des débris). On refuse la fusion et on rejuge
            # chaque fragment pour ce qu'il est, seul.
            for fragment in groupe:
                if (_est_un_glyphe(fragment[2], fragment[3], fragment[4])
                        and _pose_sur_le_bandeau(fond, fragment)):
                    trouvees.append(fragment)
    return sorted(trouvees, key=lambda b: b[0]), masque


def icones(image, centre: tuple, adverse: bool = False) -> list:
    """
    Les icônes de mots-clés lues sous cette unité : [(x, y, w, h, aire)].

    `adverse=True` pour une unité de l'ADVERSAIRE : sa barre est en haut
    de la carte, pas en bas.

    Rend une liste VIDE dès qu'on ne peut pas lire — pas d'image, cadre
    hors écran, forme inattendue. Même règle que `stun.mouvement` et
    `bilan.juger` : ne rien pouvoir lire n'est pas un verdict.
    """
    boites, _ = _icones_et_masque(image, centre, adverse)
    return boites


def decouper(image, centre: tuple, index: int, adverse: bool = False):
    """Le masque 0/255 du glyphe d'indice `index`, ou None."""
    boites, masque = _icones_et_masque(image, centre, adverse)
    if masque is None or not 0 <= index < len(boites):
        return None
    x, y, w, h, _ = boites[index]
    return masque[y:y + h, x:x + w]


def cut_icone(capture: str, centre: tuple, index: int, nom: str,
              adverse: bool = False) -> str:
    """
    Récolte un gabarit depuis une capture ÉTIQUETÉE.

    ON NE RÉCOLTE QUE CE QU'UN HUMAIN A NOMMÉ. Deviner l'identité d'une
    icône serait inventer — c'est ce que ce module refusait de faire
    depuis le 14/11, et il avait raison. L'ordre vient d'Ewan, pas de
    l'image.

    ⚠⚠ L'INDEX N'EST PAS UNE POSITION DANS LA BARRE, ET SUR LES DEUX
    CAPTURES DU 21/11 IL NE DÉSIGNE PAS LA MÊME ICÔNE (mesuré le
    21/11/2026). Le lexique d'Ewan nomme les icônes PAR POSITION
    (« Kennen n°1 = niveau, n°2 = Frappe rapide… ») ; `cut-icone`, lui,
    prend le rang de la boîte dans ce que la segmentation a RENDU. Les
    deux ne coïncident que si toutes les icônes sortent, et elles ne
    sortent pas. Le MÊME Kennen, sur les deux captures du 21/11 :

        kennen_20261121_034644  dx  -62  -33  -20   +2  +37
        victor_20261121_035752  dx       -32  -19   +3  +38  +65

    (`dx` = le `x` qu'imprime le rapport MOINS `BARRE_DEMI_LARGEUR`,
    c'est-à-dire la position relative au centre de la carte.)
    Les quatre communes s'alignent à 1 px près — c'est bien la même
    barre, au même endroit. Mais l'index 0 vaut **dx -62** sur la
    première capture et **dx -32** sur la seconde, et la seconde liste
    se termine par un **+65 (15×20, teinte 104) qui est le HALO BLEU du
    plateau, pas une icône** : il déborde la demi-largeur du bandeau
    (71 px sous Kennen) que `BARRE_DEMI_LARGEUR` = 80 laisse entrer.
    Récolter à l'index sur ces captures-là graverait donc un gabarit
    FAUX — c'est le piège de `cut_defi` (08/11) par un autre chemin, et
    il est pire ici, parce que rien ne rougirait : une icône mal nommée
    se reconnaîtrait elle-même.

    CE QU'IL FAUT FAIRE À LA PLACE : lire d'abord le rapport
    (`python mots_cles_ecran.py <capture.png>`), qui imprime le `x` de
    CHAQUE boîte, apparier ces `x` à la position nommée par Ewan, et ne
    récolter que les index ainsi confirmés — en vérifiant sur les DEUX
    captures quand la carte y figure deux fois.

    Le masque écrit est celui que `identifier` relira : on découpe PAR LE
    CHEMIN DE LECTURE, jamais par un seuil choisi à part. Le piège est
    documenté (`cut_defi`, 08/11) — une police découpée autrement ne se
    reconnaît pas elle-même (IoU 0.83, marge sous le plancher).
    """
    image = cv2.imread(capture)
    if image is None:
        raise SystemExit(f"capture introuvable : {capture}")
    masque = decouper(image, centre, index, adverse)
    if masque is None or masque.size == 0:
        raise SystemExit(f"aucune icône d'indice {index} sous {centre}")
    chemin = Path(__file__).parent / "mots_cles" / f"{nom}.png"
    chemin.parent.mkdir(exist_ok=True)
    rgba = np.zeros((*masque.shape, 4), np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = masque
    cv2.imwrite(str(chemin), rgba)
    return str(chemin)


def porte_des_mots_cles(image, centre: tuple, adverse: bool = False) -> bool:
    """
    Cette unité affiche-t-elle AU MOINS un mot-clé ?

    C'EST LE VERDICT LE MOINS CHER ET LE MIEUX ÉTABLI : juste sur les
    VINGT ET UNE unités de plateau des quatre captures témoins — seize
    porteuses, cinq vierges dont quatre ADVERSES — et il ne demande
    aucun gabarit.

    Le COMPTE, lui, n'est pas exact. Voir le tableau en tête de module,
    recompté le 21/11/2026 : sur 63 icônes visibles, 53 boîtes sortent,
    dont UNE FAUSSE (le halo bleu du plateau sous Kennen, capture
    `victor`) — donc 11 icônes n'ont pas de boîte à elles. On ne bâtit
    donc rien sur le nombre (cf. `a_recu_un_mot_cle`), et surtout pas la
    récolte d'un gabarit (cf. `cut_icone`).
    """
    return bool(icones(image, centre, adverse))


def a_recu_un_mot_cle(image, carte) -> bool:
    """
    Cette unité porte-t-elle un mot-clé qu'elle n'a pas IMPRIMÉ ?

    Vrai seulement dans le cas SANS AMBIGUÏTÉ : la carte n'a aucun
    mot-clé dans `card_sets` et une icône s'affiche quand même. Observé
    sur Legion Saboteur (01NX040, `keywords=[]`, une icône bleue).

    ⚠ CETTE PROMESSE A UN FAUX POSITIF CONNU, ET IL N'EST PAS CORRIGÉ
    ICI (21/11/2026). La PREMIÈRE place de la barre n'est pas un
    mot-clé : c'est l'indicateur de NIVEAU (fait de jeu d'Ewan), et la
    deuxième place des Viktor est un « effet de zone » que la base
    nomme elle-même `AuraVisualFakeKeyword` (48 cartes, plus
    `LandmarkVisualOnly` sur 133 autres). L'unique icône de Legion
    Saboteur — l'exemple qui a justifié cette fonction — est justement
    un éclair cyan de ce genre. La segmentation les COMPTE, à dessein :
    ils occupent bien une place dans la barre. Les EXCLURE demande de
    les reconnaître, donc un gabarit par forme, et c'est la tâche qui
    récolte les gabarits qui s'en chargera. Aucun appelant aujourd'hui.

    ON NE COMPARE PAS LES NOMBRES au-delà de ça. Même là où le compte
    est exact (les cinq Pâle orchestre du 20/11), « 5 icônes pour 1
    mot-clé imprimé » ne prouverait pas quatre dons : l'écran ne montre
    que ce qu'il DESSINE, et rien ne dit qu'un mot-clé imprimé ait
    toujours son icône.
    """
    imprimes = tuple(getattr(carte, "keywords", ()) or ())
    refs = tuple(getattr(carte, "keyword_refs", ()) or ())
    if imprimes or refs:
        return False
    # LE CÔTÉ VIENT DE LA CARTE, pas d'un argument de plus : `BoardCard`
    # le porte (`local`), et une carte sans ce champ est à nous — c'est
    # le comportement d'avant le 21/11/2026.
    return porte_des_mots_cles(image, carte.center,
                               adverse=not getattr(carte, "local", True))


def cartes_renforcees(image, cartes: Iterable) -> set:
    """Les CardID des unités qui affichent un mot-clé non imprimé."""
    trouvees = set()
    for carte in cartes or ():
        card_id = getattr(carte, "card_id", -1)
        if card_id is None or card_id < 0:
            continue
        if a_recu_un_mot_cle(image, carte):
            trouvees.add(card_id)
    return trouvees


# LES SEUILS SONT MESURÉS POUR CE PROBLÈME, pas hérités (20/11/2026).
# `digits.CONFIDENT_SCORE` (0.72) a été calibré pour les CHIFFRES : dix
# classes de formes voisines. Ici les pictogrammes sont très distincts et
# c'est la MARGE qui discrimine.
#
# MESURE À JOUR (20/11/2026 au soir, DEUX variantes par mot-clé — les 21
# vrais positifs sont les 5 Pâle orchestre × 4 icônes plus le Challenger
# imprimé de Firespitter ; les 5 étrangers sont les icônes de Swain) :
#
#     vrais positifs    score 0.710 à 1.000 | marge 0.317 à 0.640
#     glyphes étrangers score <= 0.409      | marge <= 0.073
#
# La plage de marge « 0.119 à 0.630 » qui figurait ici datait d'AVANT le
# second gabarit par mot-clé : elle annonçait 0.019 de sécurité là où il
# y en a 0.217. Mesure refaite, ancienne plage supprimée.
#
# Le score reste indispensable : seul lui peut refuser un mot-clé dont on
# n'a AUCUN gabarit. 0.60 laisse 0.11 sous le pire vrai positif et 0.19
# au-dessus du meilleur étranger ; 0.10 laisse 0.217 sous la pire vraie
# marge et 0.027 au-dessus de la meilleure marge étrangère. Les DEUX
# planchers doivent être franchis.
#
# ÉCRITS EN DUR, ET C'EST VOULU. Ce sont aujourd'hui les mêmes valeurs
# que `digits.MIN_SCORE` / `digits.CONFIDENT_MARGIN` — mais prises à DEUX
# paliers différents de `digits` (le palier « candidat » pour l'un, le
# palier « sûr » pour l'autre), un assemblage qui n'a de sens que pour
# les chiffres. Les rebrancher ferait bouger EN SILENCE le plancher qui
# empêche d'inventer un Challenger le jour où quelqu'un règle `digits`
# (trois fois en novembre). Ne pas rebrancher : mesurer ici.
SCORE_SUR = 0.60
MARGE_SURE = 0.10

_GABARITS: dict = {}

# Radical de fichier -> mot-clé tel que `card_sets` l'écrit. `BoardCard.has`
# normalise la casse et la ponctuation, mais on écrit la forme juste.
NOMS = {
    "ephemeral": "Ephemeral",
    "hallowed": "Hallowed",
    "challenger": "Challenger",
    "overwhelm": "Overwhelm",
}


def _famille(radical: str) -> str:
    """« hallowed2 » appartient à la famille « hallowed ». Même rôle que
    `digits._family` : plusieurs variantes d'un même mot-clé."""
    return radical.rstrip("0123456789") or radical


def charger_gabarits() -> dict:
    """
    mot-clé -> ses VARIANTES, masques 0/1. L'ALPHA porte la forme, comme
    `chiffres/` — un glyphe opaque ne vaudrait rien.

    Le score d'un mot-clé est celui de sa MEILLEURE variante ; la marge se
    mesure entre deux mots-clés DIFFÉRENTS, jamais entre deux variantes du
    même. C'est mot pour mot la règle de `digits.match_glyph`.

    RIEN N'EST ÉCARTÉ EN SILENCE (20/11/2026). Un PNG ré-enregistré par un
    éditeur qui aplatit l'alpha disparaissait du lot sans un mot, et
    `identifier` cessait de rendre ce mot-clé-là : c'est littéralement le
    défaut du 08/11 (« le gabarit était écrit, puis IGNORÉ au chargement,
    sans un mot »). Les deux refus sont désormais journalisés.

    ET ON N'ACCEPTE QUE LES FAMILLES DE `NOMS`. N'importe quel PNG à alpha
    déposé là devenait une classe candidate : il ne peut rien gagner (son
    nom n'est pas un mot-clé de `card_sets`) mais il CONSOMME de la marge,
    et peut faire passer un vrai glyphe sous le plancher.
    """
    if _GABARITS:
        return _GABARITS
    dossier = Path(__file__).parent / "mots_cles"
    for png in sorted(dossier.glob("*.png")):
        brut = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
        if brut is None or brut.ndim < 3 or brut.shape[2] < 4:
            LOGGER.warning(
                "Gabarit de mot-clé ignoré, pas de canal alpha : %s — "
                "l'alpha porte la forme, un glyphe opaque ne vaut rien.",
                png.name,
            )
            continue
        famille = _famille(png.stem)
        if famille not in NOMS:
            LOGGER.warning(
                "Gabarit de mot-clé ignoré, famille inconnue : %s "
                "(familles connues : %s) — une classe de plus consomme de "
                "la marge sans pouvoir rien nommer.",
                png.name, ", ".join(sorted(NOMS)),
            )
            continue
        nom = NOMS[famille]
        _GABARITS.setdefault(nom, []).append((brut[:, :, 3] >= 128).astype(np.uint8))
    return _GABARITS


def _score(glyphe, gabarit) -> float:
    """Le chemin de `digits.match_glyph`, appliqué à nos pictogrammes."""
    forme = digits._normalized((glyphe > 0).astype(np.uint8))
    cible = digits._normalized((gabarit > 0).astype(np.uint8))
    return digits._iou(digits._equalize_stroke(forme, float(cible.mean())), cible)


def identifier(image, centre: tuple, adverse: bool = False) -> tuple:
    """
    Les mots-clés SÛREMENT lus sous cette unité, dans l'ordre de lecture.

    `adverse=True` pour une unité de l'ADVERSAIRE : sa barre est en haut
    de la carte (21/11/2026).

    Un glyphe sous les paliers n'est PAS identifié : il est absent du
    tuple. Il reste compté par `porte_des_mots_cles`, qui ne prétend
    qu'à la présence. Ne jamais rendre une valeur approchée.

    Appelle `_icones_et_masque` UNE SEULE FOIS (boîtes + masque), puis
    tranche dedans pour chaque glyphe — au lieu de rappeler `icones()`
    pour compter et `decouper()` pour chaque indice, qui redemandait la
    même segmentation à chaque fois. Voir `_icones_et_masque` pour le
    chiffrage et la mesure du coût avant/après (tâche 3, 20/11/2026).
    """
    gabarits = charger_gabarits()
    # UNE MARGE A BESOIN DE DEUX CANDIDATS. Avec une seule famille
    # chargée, `second` vaudrait 0.0, la marge vaudrait le score, et le
    # second plancher ne filtrerait plus rien — alors que tout le module
    # repose sur « les DEUX planchers doivent être franchis ». Ça ne peut
    # pas arriver aujourd'hui (quatre familles), mais rien ne le disait :
    # un `mots_cles/` à moitié vidé aurait fait inventer un mot-clé.
    if len(gabarits) < 2:
        if gabarits:
            LOGGER.warning(
                "Identification des mots-clés désactivée : %d famille(s) de "
                "gabarits chargée(s), il en faut au moins 2 pour qu'une "
                "marge veuille dire quelque chose.", len(gabarits),
            )
        return ()
    boites, masque = _icones_et_masque(image, centre, adverse)
    if masque is None:
        return ()
    trouves = []
    for x, y, w, h, _ in boites:
        glyphe = masque[y:y + h, x:x + w]
        if glyphe is None or glyphe.size == 0:
            continue
        notes = sorted(((max(_score(glyphe, v) for v in variantes), nom)
                        for nom, variantes in gabarits.items()), reverse=True)
        meilleur, second = notes[0], notes[1]
        if meilleur[0] >= SCORE_SUR and meilleur[0] - second[0] >= MARGE_SURE:
            trouves.append(meilleur[1])
    return tuple(trouves)


# ============================================================
# DIAGNOSTIC — « que lit-on sous chaque unité ? »
# ============================================================
# `champions.py <capture>`, `bilan.py <capture>` et `spells.py explain`
# ont tous leur point d'entrée ; celui-ci manquait, et `cut_icone` — le
# SEUL outil de récolte de gabarits — n'était atteignable que par
# `python -c`. C'est pourtant par lui que passeront les seize mots-clés
# qui n'en ont pas encore.
USAGE = """\
Que lit-on sous les unités d'un plateau ?

    python mots_cles_ecran.py                       écran en direct (API + capture)
    python mots_cles_ecran.py <capture.png>         une capture et sa trame .json appariée
    python mots_cles_ecran.py <capture.png> <x> <y> un centre d'unité donné à la main
    python mots_cles_ecran.py cut-icone <capture.png> <x> <y> <index> <nom>

Ajouter `adverse` EN DERNIER ARGUMENT lit la barre en HAUT de la carte
— c'est là qu'elle est chez l'adversaire. Inutile avec une trame
appariée : le côté y est lu dans `LocalPlayer`.

    python mots_cles_ecran.py <capture.png> <x> <y> adverse
    python mots_cles_ecran.py cut-icone <capture.png> <x> <y> <index> <nom> adverse

`cut-icone` récolte un gabarit : l'INDEX est celui qu'affiche la
commande sans argument, le NOM est celui d'Ewan — on ne récolte que ce
qu'un humain a nommé. ⚠ L'index n'est PAS la position dans la barre et
ne désigne pas la même icône d'une capture à l'autre : lire
l'avertissement de `cut_icone` AVANT de récolter.\
"""


def unites_de_la_trame(trame: dict, window=None) -> list:
    """
    Les cartes d'une trame : [(CardCode, centre, à nous ?)].

    LE CÔTÉ EST DANS LA TRAME (`LocalPlayer`) : on ne le devine pas, et
    il décide de quel côté de la carte on va lire la barre.

    ON NE REFAIT PAS LE CLASSEMENT EN ZONES ICI. `game_state.group_by_zone`
    en est la source unique, et l'importer d'ici importerait une SECONDE
    COPIE de ce module-ci (ce fichier étant alors `__main__`) — le piège
    du 10/11. On rend donc TOUTES les cartes, main comprise : une carte
    en main n'a pas de barre d'icônes, elle sort à zéro, et le diagnostic
    le montre au lieu de la cacher.
    """
    import lor_api

    if window is None:
        ecran = (trame or {}).get("Screen") or {}
        window = lor_api.Window(0, 0, int(ecran.get("ScreenWidth") or 1920),
                                int(ecran.get("ScreenHeight") or 1080))
    unites = []
    for rect in (trame or {}).get("Rectangles") or ():
        if rect.get("CardCode") in (None, "face"):
            continue
        unites.append((rect["CardCode"], lor_api.rect_center_screen(rect, window),
                       bool(rect.get("LocalPlayer", True))))
    return unites


def _rapport(image, unites) -> None:
    """Ce que l'écran dit de chaque unité — boîtes comprises, parce que
    c'est leur INDEX que `cut-icone` demande."""
    for code, centre, local in unites:
        boites = icones(image, centre, adverse=not local)
        noms = identifier(image, centre, adverse=not local)
        cote = "à nous " if local else "ADVERSE"
        print(f"  {code:<12} {cote} centre {str(centre):<14} {len(boites)} icône(s)")
        for i, (x, y, w, h, aire) in enumerate(boites):
            nom = noms[i] if i < len(noms) and len(noms) == len(boites) else "?"
            print(f"       [{i}] x={x:<4} y={y:<4} {w}×{h} (aire {aire})   {nom}")
        if noms and len(noms) != len(boites):
            # Un glyphe sous les planchers n'est PAS identifié : le tuple
            # est plus court que la liste des boîtes, et on ne sait plus
            # dire laquelle est laquelle. On le dit, on ne l'invente pas.
            print(f"       identifiés (sans correspondance sûre) : {', '.join(noms)}")


def main(argv=None) -> int:
    # Ce rapport imprime des « × » et des accents : redirigé dans un
    # fichier ou un tube, Python retombe sur cp1252 et MEURT dessus. Cf.
    # `sortie_utf8.py`, point unique de la parade — on l'applique AVANT
    # la première impression, comme `game_state.main` et `combat.main`.
    import sortie_utf8
    sortie_utf8.appliquer()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    adverse = bool(argv) and argv[-1] == "adverse"
    if adverse:
        argv = argv[:-1]

    if argv and argv[0] == "cut-icone":
        if len(argv) != 6:
            print(USAGE)
            return 1
        capture, x, y, index, nom = argv[1], *argv[2:6]
        print(cut_icone(capture, (int(x), int(y)), int(index), nom, adverse))
        return 0

    if argv:
        image = cv2.imread(argv[0])
        if image is None:
            print(f"Capture illisible : {argv[0]}")
            return 1
        if len(argv) >= 3:
            unites = [("(donné)", (int(argv[1]), int(argv[2])), not adverse)]
        else:
            # LA TRAME APPARIÉE, OU RIEN. Deviner où sont les unités sur
            # une capture, c'est exactement ce que ce module refuse de
            # faire des icônes.
            trame = Path(argv[0]).with_suffix(".json")
            if not trame.exists():
                print(f"Pas de trame appariée ({trame.name}) : donnez un centre "
                      f"d'unité à la main.\n\n{USAGE}")
                return 1
            import json
            unites = unites_de_la_trame(json.loads(trame.read_text("utf-8")))
    else:
        import lor_api
        trame = lor_api.get_positional_rectangles()
        image = lor_api.capture_screen_bgr()
        if image is None:
            print("Aucune capture d'écran.")
            return 1
        unites = unites_de_la_trame(trame, lor_api.get_window(trame))

    familles = charger_gabarits()
    print(f"{len(unites)} carte(s), {len(familles)} mot(s)-clé(s) avec gabarit : "
          f"{', '.join(sorted(familles)) or 'aucun'}")
    _rapport(image, unites)
    return 0


if __name__ == "__main__":
    sys.exit(main())
