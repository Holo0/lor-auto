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
Sous l'illustration de chaque unité DU PLATEAU, le jeu pose une barre
noire hexagonale portant une icône par mot-clé. Mesuré sur
`captures_reference/unite_stun_20261114_231607.png`, en coordonnées
RELATIVES à `card.center` (donc valables quelle que soit la position de
l'unité sur le banc) :

      la barre occupe   dy +38 à +82      centrée en x sur card.center
      une icône fait    11 à 34 px de côté, aire ≥ 60 px

Les icônes se répartissent en TROIS FAMILLES DE COULEUR, orange, bleu
clair et magenta (ce dernier ajouté le 20/11/2026, cf. `MAGENTA`
ci-dessous), nettes et franches sur fond noir.

CE QUI EST MESURÉ, ET CE QUI NE L'EST PAS
-----------------------------------------
Sur la seule scène étiquetée dont on dispose — sept unités dont les
mots-clés imprimés sont connus par `card_sets` :

      unité                   imprimés   icônes détectées
      Swain (Fearsome)            1            4
      Enraged Firespitter          1            3
      Legion Saboteur              0            2
      Arachnoid Sentry             0            0
      House Spider                 0            0
      Spiderling                   0            0
      Imperial Demolitionist       0            0

**LA PRÉSENCE EST FIABLE, LE COMPTE NE L'EST PAS.** Les quatre unités
sans aucun mot-clé ne déclenchent RIEN : zéro faux positif. Mais le
nombre exact d'icônes varie de ±1 selon qu'elles se touchent ou se
fragmentent (sur cette image, Swain en porte 5 à l'œil et 4 au masque,
Firespitter 2 et 3). On ne rend donc JAMAIS un compte comme une
vérité : on rend « il y en a » ou « il n'y en a pas ».

**L'IDENTIFICATION N'EST PAS FAITE, ET C'EST ASSUMÉ.** Les icônes sont
assez nettes pour être reconnues par gabarit — deux ont même pu être
rapprochées de `card_sets` à l'œil (le visage effrayant de Swain est son
`Fearsome` imprimé, la forme angulaire de Firespitter son `Challenger`).
Mais étiqueter les AUTRES demande de savoir quel mot-clé a été accordé,
et ça ne se devine pas : c'est un fait de jeu. Tant qu'on n'a pas de
captures étiquetées, dire « cette icône est un Overwhelm » serait
inventer. `keywords.has()` n'est donc PAS branché ici.

CE QUE ÇA PERMET DÉJÀ. Une unité SANS mot-clé imprimé qui porte une
icône a forcément été RENFORCÉE en jeu — et c'est observé : Legion
Saboteur (01NX040, `keywords=[]`) porte une icône bleue. C'est le seul
verdict que ce module rend, et il est sans ambiguïté.

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
    C'est la fenêtre dy +38..+82 qui les exclut, pas la teinte.

UNE SEULE SCÈNE OBSERVÉE (14/11/2026), sept unités. Les bornes sont
prises large. À revoir dès qu'une capture étiquetée sera disponible.
"""

from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np

# La barre d'icônes, en coordonnées relatives à `card.center`. Mesurée
# sur les trois unités porteuses de la capture de référence ; les bornes
# excluent le liseré bleu du plateau (qui commence vers dy +85) et les
# badges de statistiques (au-dessus de l'illustration).
BARRE_DY_HAUT = 38
BARRE_DY_BAS = 82
BARRE_DEMI_LARGEUR = 80

# Une icône : ni un éclat de décor, ni la barre entière.
# CÔTÉ MINIMAL ABAISSÉ DE 12 À 11 (20/11/2026). Mesuré sur la scène du
# Pâle orchestre (06SI009) : le glyphe « Surpuissance » (orange, teinte
# 19) a une ombre interne qui fragmente son masque en plusieurs
# morceaux — un trait du GLYPHE, pas de la famille de couleur. Le plus
# gros morceau mesure 22×11 (aire 117, largement au-dessus
# d'ICONE_AIRE_MIN) : à 1 px près de l'ancien seuil, il restait invisible
# alors que c'est une vraie icône. Vérifié SANS RÉGRESSION sur les sept
# unités de la capture du 14/11 (unite_stun_20261114_231607.png) : les
# quatre vierges restent à zéro icône, les trois porteuses restent
# porteuses — aucun débris ne passe la barre avec ce seuil.
ICONE_COTE_MIN, ICONE_COTE_MAX = 11, 34
ICONE_AIRE_MIN = 60

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


def icones(image, centre: tuple) -> list:
    """
    Les icônes de mots-clés lues sous cette unité : [(x, y, w, h, aire)].

    Rend une liste VIDE dès qu'on ne peut pas lire — pas d'image, cadre
    hors écran, forme inattendue. Même règle que `stun.mouvement` et
    `bilan.juger` : ne rien pouvoir lire n'est pas un verdict.
    """
    forme = getattr(image, "shape", None)
    if forme is None or len(forme) < 3:
        return []
    cx, cy = int(centre[0]), int(centre[1])
    h, w = forme[0], forme[1]
    x0, x1 = cx - BARRE_DEMI_LARGEUR, cx + BARRE_DEMI_LARGEUR
    y0, y1 = cy + BARRE_DY_HAUT, cy + BARRE_DY_BAS
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return []

    masque = _masque_icones(image[y0:y1, x0:x1])
    nombre, _, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    trouvees = []
    for i in range(1, nombre):
        x, y, lw, lh, aire = stats[i]
        if (ICONE_COTE_MIN <= lw <= ICONE_COTE_MAX
                and ICONE_COTE_MIN <= lh <= ICONE_COTE_MAX
                and aire >= ICONE_AIRE_MIN):
            trouvees.append((int(x), int(y), int(lw), int(lh), int(aire)))
    return sorted(trouvees, key=lambda b: b[0])


def porte_des_mots_cles(image, centre: tuple) -> bool:
    """
    Cette unité affiche-t-elle AU MOINS un mot-clé ?

    C'est le seul verdict que le compte d'icônes permette : il est juste
    sur les sept unités de la capture de référence, là où le nombre
    exact varie de ±1.
    """
    return bool(icones(image, centre))


def a_recu_un_mot_cle(image, carte) -> bool:
    """
    Cette unité porte-t-elle un mot-clé qu'elle n'a pas IMPRIMÉ ?

    Vrai seulement dans le cas SANS AMBIGUÏTÉ : la carte n'a aucun
    mot-clé dans `card_sets` et une icône s'affiche quand même. Observé
    sur Legion Saboteur (01NX040, `keywords=[]`, une icône bleue).

    ON NE COMPARE PAS LES NOMBRES au-delà de ça : le compte est à ±1, et
    « 4 icônes pour 1 mot-clé imprimé » ne prouverait pas trois dons.
    """
    imprimes = tuple(getattr(carte, "keywords", ()) or ())
    refs = tuple(getattr(carte, "keyword_refs", ()) or ())
    if imprimes or refs:
        return False
    return porte_des_mots_cles(image, carte.center)


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
