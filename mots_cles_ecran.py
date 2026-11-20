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
      une icône fait    12 à 34 px de côté, aire ≥ 60 px

Les icônes se répartissent en TROIS FAMILLES DE COULEUR, orange, bleu
clair et magenta (ce dernier ajouté le 20/11/2026, cf. `MAGENTA`
ci-dessous), nettes et franches sur fond noir.

CE QUI EST MESURÉ, ET CE QUI NE L'EST PAS
-----------------------------------------
Sur la seule scène étiquetée dont on dispose — sept unités dont les
mots-clés imprimés sont connus par `card_sets` :

      unité                   imprimés   icônes détectées
      Swain (Fearsome)            1            5
      Enraged Firespitter          1            1
      Legion Saboteur              0            2
      Arachnoid Sentry             0            0
      House Spider                 0            0
      Spiderling                   0            0
      Imperial Demolitionist       0            0

**LA PRÉSENCE EST FIABLE ; LE COMPTE L'EST DEVENU, EN PARTIE**
(20/11/2026). Les quatre unités sans aucun mot-clé ne déclenchent
RIEN : zéro faux positif. Un glyphe FRAGMENTÉ (ombre interne,
antialiasing) ne vaut plus pour plusieurs icônes : `_colonnes` le
recolle en une seule boîte avant de le juger — c'est ce qui fait
passer Swain de 4 à 5 (le 5e glyphe était là, vu « à l'œil » depuis le
14/11, jamais recollé) et Firespitter de 3 à 1 (ses deux fragments
en trop n'étaient que le bord d'une tache de bordure voisine, pas des
icônes). Ce qui reste VRAI : deux glyphes VOISINS qui se touchent sans
former un rectangle plausible ne sont toujours pas fusionnés à tort —
`_est_un_glyphe` refuse toute boîte recollée hors de `ICONE_COTE_MAX`,
et c'est ce refus qui protège Firespitter d'une sur-fusion. On ne rend
donc toujours pas un compte comme une vérité absolue à l'usage externe
du module : on rend d'abord « il y en a » ou « il n'y en a pas ».

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

MESURE DE L'IDENTIFICATION (20/11/2026), sur les trois Pâle orchestre
qui n'ont PAS servi à récolter les gabarits (`scene_20261120_201157.png`,
centres (959, 900), (1115, 900), (1272, 900) — les gabarits viennent de
(645, 900) et (802, 900)) :

      pire score    0.714   (Hallowed en (959, 900))
      pire marge    0.320   (même glyphe, Hallowed contre Ephemeral)

Les deux dépassent largement SCORE_SUR (0.60) et MARGE_SURE (0.10). En
élargissant aux cinq Pâle orchestre (les deux sources comprises, à 1.000
par construction) et à la validation croisée du 14/11 (Firespitter,
score 0.710, marge 0.317), l'ensemble des vrais positifs mesurés tient
dans [0.710, 1.000] en score et [0.317, 0.640] en marge — à comparer aux
glyphes ÉTRANGERS de Swain (14/11), qui ne dépassent jamais 0.409 de
score ni 0.073 de marge contre nos quatre gabarits (`test_mots_cles_ecran.
test_un_glyphe_etranger_nest_identifie_comme_rien`).

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

from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

import digits

# La barre d'icônes, en coordonnées relatives à `card.center`. Mesurée
# sur les trois unités porteuses de la capture de référence ; les bornes
# excluent le liseré bleu du plateau (qui commence vers dy +85) et les
# badges de statistiques (au-dessus de l'illustration).
BARRE_DY_HAUT = 38
BARRE_DY_BAS = 82
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
# `icones()` recolle donc les fragments d'une même COLONNE (plages en x
# qui se touchent) avant de juger leur taille. Fragments exclus de la
# fusion : sous `FRAGMENT_AIRE_MIN` (bruit d'antialiasing/compression,
# jamais un bout de glyphe réel) et, au moment de juger la boîte
# recollée, tout chevauchement dont le résultat dépasserait
# `ICONE_COTE_MAX` — deux icônes VOISINES qui se touchent ne sont pas un
# glyphe fragmenté, et c'est ce garde, lui seul, qui empêche Firespitter
# (un vrai glyphe 22×20 collé à une grande tache de bordure 40×30) de
# fusionner en un rectangle refusé puis de disparaître.
FRAGMENT_AIRE_MIN = 20

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


def _colonnes(fragments: list) -> list:
    """
    Chaîne les fragments dont les plages en x se TOUCHENT ou se
    chevauchent, triés de gauche à droite : la coupure d'un glyphe
    fragmenté (ombre interne, antialiasing) reste dans sa colonne —
    deux glyphes voisins qui ne se touchent pas en ouvrent une autre.
    """
    groupes: list = []
    fin_courante = None
    for fragment in sorted(fragments, key=lambda f: f[0]):
        x, _, largeur = fragment[0], fragment[1], fragment[2]
        if groupes and x <= fin_courante:
            groupes[-1].append(fragment)
            fin_courante = max(fin_courante, x + largeur)
        else:
            groupes.append([fragment])
            fin_courante = x + largeur
    return groupes


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
    fragments = [tuple(int(v) for v in stats[i]) for i in range(1, nombre)
                 if stats[i][4] >= FRAGMENT_AIRE_MIN]

    trouvees = []
    for groupe in _colonnes(fragments):
        x, y, largeur, hauteur, aire = _boite_recollee(groupe)
        if _est_un_glyphe(largeur, hauteur, aire):
            # La colonne ENTIÈRE forme un glyphe plausible : recollée.
            trouvees.append((x, y, largeur, hauteur, aire))
        elif len(groupe) > 1:
            # Recollée, la colonne n'a plus la taille d'un glyphe — soit
            # elle a trop grossi (deux icônes qui se touchent), soit elle
            # reste trop pauvre (débris). On refuse la fusion et on
            # rejuge chaque fragment pour ce qu'il est, seul.
            for fx, fy, fw, fh, faire in groupe:
                if _est_un_glyphe(fw, fh, faire):
                    trouvees.append((fx, fy, fw, fh, faire))
    return sorted(trouvees, key=lambda b: b[0])


def decouper(image, centre: tuple, index: int):
    """Le masque 0/255 du glyphe d'indice `index`, ou None."""
    boites = icones(image, centre)
    if not 0 <= index < len(boites):
        return None
    cx, cy = int(centre[0]), int(centre[1])
    x0, y0 = cx - BARRE_DEMI_LARGEUR, cy + BARRE_DY_HAUT
    x, y, w, h, _ = boites[index]
    bande = image[y0:cy + BARRE_DY_BAS, x0:cx + BARRE_DEMI_LARGEUR]
    return _masque_icones(bande)[y:y + h, x:x + w]


def cut_icone(capture: str, centre: tuple, index: int, nom: str) -> str:
    """
    Récolte un gabarit depuis une capture ÉTIQUETÉE.

    ON NE RÉCOLTE QUE CE QU'UN HUMAIN A NOMMÉ. Deviner l'identité d'une
    icône serait inventer — c'est ce que ce module refusait de faire
    depuis le 14/11, et il avait raison. L'ordre vient d'Ewan, pas de
    l'image.

    Le masque écrit est celui que `identifier` relira : on découpe PAR LE
    CHEMIN DE LECTURE, jamais par un seuil choisi à part. Le piège est
    documenté (`cut_defi`, 08/11) — une police découpée autrement ne se
    reconnaît pas elle-même (IoU 0.83, marge sous le plancher).
    """
    image = cv2.imread(capture)
    if image is None:
        raise SystemExit(f"capture introuvable : {capture}")
    masque = decouper(image, centre, index)
    if masque is None or masque.size == 0:
        raise SystemExit(f"aucune icône d'indice {index} sous {centre}")
    chemin = Path(__file__).parent / "mots_cles" / f"{nom}.png"
    chemin.parent.mkdir(exist_ok=True)
    rgba = np.zeros((*masque.shape, 4), np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = masque
    cv2.imwrite(str(chemin), rgba)
    return str(chemin)


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


# LES SEUILS SONT MESURÉS POUR CE PROBLÈME, pas hérités (20/11/2026).
# `digits.CONFIDENT_SCORE` (0.72) a été calibré pour les CHIFFRES : dix
# classes de formes voisines. Ici les pictogrammes sont très distincts et
# c'est la MARGE qui discrimine. Mesuré sur les 5 Pâle orchestre du 20/11
# et les glyphes ÉTRANGERS de la scène du 14/11 :
#
#     vrais positifs   score 0.710 à 0.988 | marge 0.119 à 0.630
#     glyphes étrangers score <= 0.429     | marge <= 0.073
#
# Le score reste indispensable : seul lui peut refuser un mot-clé dont on
# n'a AUCUN gabarit. 0.60 laisse 0.11 sous le pire vrai positif et 0.17
# au-dessus du meilleur étranger. Les DEUX planchers doivent être franchis.
SCORE_SUR = digits.MIN_SCORE              # 0.60
MARGE_SURE = digits.CONFIDENT_MARGIN      # 0.10

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
    """
    if _GABARITS:
        return _GABARITS
    dossier = Path(__file__).parent / "mots_cles"
    for png in sorted(dossier.glob("*.png")):
        brut = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
        if brut is None or brut.ndim < 3 or brut.shape[2] < 4:
            continue
        famille = _famille(png.stem)
        nom = NOMS.get(famille, famille)
        _GABARITS.setdefault(nom, []).append((brut[:, :, 3] >= 128).astype(np.uint8))
    return _GABARITS


def _score(glyphe, gabarit) -> float:
    """Le chemin de `digits.match_glyph`, appliqué à nos pictogrammes."""
    forme = digits._normalized((glyphe > 0).astype(np.uint8))
    cible = digits._normalized((gabarit > 0).astype(np.uint8))
    return digits._iou(digits._equalize_stroke(forme, float(cible.mean())), cible)


def identifier(image, centre: tuple) -> tuple:
    """
    Les mots-clés SÛREMENT lus sous cette unité, dans l'ordre de lecture.

    Un glyphe sous les paliers n'est PAS identifié : il est absent du
    tuple. Il reste compté par `porte_des_mots_cles`, qui ne prétend
    qu'à la présence. Ne jamais rendre une valeur approchée.
    """
    gabarits = charger_gabarits()
    if not gabarits:
        return ()
    trouves = []
    for index in range(len(icones(image, centre))):
        glyphe = decouper(image, centre, index)
        if glyphe is None or glyphe.size == 0:
            continue
        notes = sorted(((max(_score(glyphe, v) for v in variantes), nom)
                        for nom, variantes in gabarits.items()), reverse=True)
        meilleur = notes[0]
        second = notes[1] if len(notes) > 1 else (0.0, "")
        if meilleur[0] >= SCORE_SUR and meilleur[0] - second[0] >= MARGE_SURE:
            trouves.append(meilleur[1])
    return tuple(trouves)
