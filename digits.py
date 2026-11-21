#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
digits.py

Lire un nombre dans un badge du jeu SANS OCR : par la FORME des chiffres.

    python digits.py chiffres/3.png            # relit un template (test)
    python digits.py debug_cards/01SI058.png   # lit les badges d'une carte

--------------------------------------------------------------------
POURQUOI
--------------------------------------------------------------------
easyocr (torch sur CPU) coûte 100 à 300 ms par lecture, et le bot vote
entre six binarisations : une dizaine d'unités en jeu, c'est plusieurs
secondes avant chaque décision d'attaque ou de blocage. Or les chiffres
du jeu sont UNE police, toujours la même, dans trois couleurs (blanc,
vert renforcé, rouge affaibli). C'est le cas d'école où comparer des
formes bat un réseau de neurones : quelques millisecondes, un résultat
déterministe, et un score qui dit s'il faut se méfier.

--------------------------------------------------------------------
COMMENT
--------------------------------------------------------------------
`chiffres/0.png` … `9.png` sont des glyphes du jeu détourés (canal alpha
= la forme, capturés par Ewan). Pour lire un badge :

    1. isoler les pixels de GLYPHE : clairs, et soit blancs, soit verts,
       soit rouges — jamais l'orange doré de la gemme d'attaque ni le
       bleu de la gemme de mana (`glyph_mask`) ;
    2. découper les composantes connexes assez hautes pour être un
       chiffre, de gauche à droite (`glyph_boxes`) ;
    3. comparer chaque composante, redimensionnée, aux dix formes
       (`match_glyph`) : recouvrement des masques (IoU). On exige un score
       minimal ET un écart avec le deuxième candidat — un « 3 » et un
       « 8 » proches, c'est un doute, pas une lecture ;
    4. assembler les chiffres (« 1 » + « 0 » → 10) et vérifier la borne.

Quand le doute existe, `read_number` rend None et l'appelant retombe sur
l'OCR — la vitesse ne doit jamais coûter une erreur de mana.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

DIGITS_DIR = Path(__file__).resolve().parent / "chiffres"

# QUI A LU QUOI. Chaque lecture de chiffre du bot (mana, coût, stats)
# passe par la forme d'abord, easyocr ensuite ; ce compteur dit, à la fin
# d'un combat, combien de fois la forme a suffi et combien de fois torch
# a vraiment servi. C'est la mesure qui permet de décider si `--sans-ocr`
# peut devenir le défaut — pas une intuition.
#     forme     : lecture sûre par la forme, sans OCR
#     easyocr   : la forme doutait, easyocr a tranché
#     tolerant  : ni l'un ni l'autre, lecture par la forme en mode tolérant
#     echec     : rien lu du tout
USAGE = Counter()


def usage_summary() -> str:
    """Une ligne lisible pour le journal de fin de combat."""
    total = sum(USAGE.values())
    if not total:
        return "aucune lecture de chiffre"
    parts = ", ".join(f"{k} {v}" for k, v in USAGE.most_common())
    ocr = USAGE.get("easyocr", 0)
    return f"{total} lecture(s) de chiffres : {parts} — easyocr nécessaire {100 * ocr / total:.0f} %"

# Score IoU minimal pour accepter un chiffre, et écart minimal avec le
# second candidat. Mesurés sur les captures de debug_cards/ (03/09/2026) :
# les bons chiffres sortent à 0.80-0.90, le second candidat 0.10 à 0.25
# plus bas.
MIN_SCORE = 0.60
MIN_MARGIN = 0.06
# Au-dessus de ces deux-là, la lecture se suffit à elle-même et l'OCR
# n'est pas appelé. Entre les deux paliers, c'est un CANDIDAT : l'OCR
# tranche, et le candidat ne sert que si l'OCR ne lit rien.
CONFIDENT_SCORE = 0.72
CONFIDENT_MARGIN = 0.10
# Une composante plus basse que cette fraction du plus grand glyphe est
# un reflet ou un morceau de cadre, pas un chiffre.
MIN_RELATIVE_HEIGHT = 0.6
# UN CHIFFRE MANQUANT A LA TAILLE DE SES VOISINS — une police donne la
# même hauteur à tous ses chiffres : « DÉFI 19 » mesure 37 et 38 px.
# C'est une bande ÉTROITE, et il le faut : les vrais badges portent du
# décor que `glyph_boxes` laisse entrer exprès (bord de gemme à 15 px
# contre un chiffre de 23, éclat de cadre à 12 contre 16), et le large
# seuil de `MIN_RELATIVE_HEIGHT` aurait refusé ces lectures-là.
UNKNOWN_HEIGHT_BAND = (0.85, 1.15)
# Taille de comparaison : les glyphes sont ramenés à cette hauteur.
NORMAL_HEIGHT = 32

_TEMPLATES: Optional[dict] = None


# ============================================================
# TEMPLATES
# ============================================================

def _tight(mask: np.ndarray) -> np.ndarray:
    """Le masque recadré sur ses pixels non nuls."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return mask
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _normalized(mask: np.ndarray) -> np.ndarray:
    """Masque binaire ramené à NORMAL_HEIGHT de haut, largeur proportionnelle."""
    tight = _tight(mask)
    h, w = tight.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((NORMAL_HEIGHT, NORMAL_HEIGHT // 2), np.uint8)
    width = max(4, int(round(w * NORMAL_HEIGHT / h)))
    resized = cv2.resize(tight.astype(np.uint8) * 255, (width, NORMAL_HEIGHT),
                         interpolation=cv2.INTER_AREA)
    return (resized >= 128).astype(np.uint8)


def _read_mask(path: Path):
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 3 and image.shape[2] == 4:
        mask = image[:, :, 3] >= 128
    else:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = gray >= 128
    return mask if mask.any() else None


def load_templates(folder: Path = DIGITS_DIR) -> dict:
    """
    {chiffre: masque normalisé} — le template PRINCIPAL de chaque chiffre
    (`N.png`), ou {} si le dossier manque. Les VARIANTES (`N_*.png`, une
    autre police : les PV du nexus, cf. `chiffres/N_nexus.png`) sont
    servies par `load_variants` et comptent dans `match_glyph`.
    """
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    templates = {}
    for digit in range(10):
        mask = _read_mask(folder / f"{digit}.png")
        if mask is not None:
            templates[digit] = _normalized(mask)
    _TEMPLATES = templates
    return templates


_VARIANTS: dict = {}

# UNE POLICE SERT LÀ OÙ ELLE A ÉTÉ RÉCOLTÉE, PAS PARTOUT.
# `chiffres/N_defi.png` a été créé le 05/11/2026 pour le titre « DÉFI N »,
# avec une remarque explicite : « ce n'est pas la police des coûts ». Mais
# `load_variants` sert tous les `N*.png` à toutes les lectures, et les deux
# polices se polluaient l'une l'autre. Mesuré le 08/11/2026 : le « 9 » du
# titre, pourtant fidèle, reconnaissait un morceau d'ILLUSTRATION de carte
# comme un 9 (0.61, marge 0.12) — ce que `test_digits` interdit depuis
# toujours. Une famille par usage, et chaque lecture demande la sienne.
#
# Les familles communes (suffixe vide = `N.png`, `_nexus` = les PV du
# nexus) restent servies partout : elles ont été récoltées sur les écrans
# de jeu et se complètent. `_defi` est RÉSERVÉE, parce que le titre est
# une typographie à part qu'aucun badge n'affiche.
# `defi2` est une SECONDE VARIANTE du titre, pas une seconde police
# (14/11/2026) : le « 3 » avait été récolté sur la LISTE des défis faute
# de titre qui en porte un, et il n'atteignait pas la marge sur un vrai
# titre — le palier 31 se lisait « 3 à 0.779, marge 0.068 », refusé.
# `load_variants` prend le MAX des variantes d'un chiffre, donc en
# ajouter une ne peut que RELEVER son score. Les deux restent réservées :
# servies à une lecture de coût ou de stat, elles seraient une surface de
# faux positifs — c'est tout l'objet de cette liste.
RESERVED_FAMILIES = ("defi", "defi2")


def _family(stem: str) -> str:
    """La famille d'un gabarit : "" pour `N.png`, `nexus` pour `N_nexus.png`."""
    return stem[2:] if len(stem) > 2 else ""


def load_variants(folder: Path = DIGITS_DIR, families=None) -> dict:
    """
    {chiffre: [masques normalisés]} pour les fichiers `N*.png` du dossier.

    Une police de plus par chiffre, c'est une marge de plus : les PV du
    nexus (06/09/2026, « 24 » lu à 0.62 avec la seule police des gemmes
    de coût → « illisibles ») sont écrits plus fin que les coûts des
    cartes. Mais une police RÉCOLTÉE AILLEURS est une surface de faux
    positifs : `families` dit lesquelles on veut, et par défaut on prend
    toutes celles qui ne sont pas réservées (cf. `RESERVED_FAMILIES`).
    """
    cle = None if families is None else tuple(sorted(families))
    if cle in _VARIANTS:
        return _VARIANTS[cle]
    variants = {}
    try:
        files = sorted(folder.glob("*.png"))
    except OSError:
        files = []
    for path in files:
        stem = path.stem
        if not stem or not stem[0].isdigit() or (len(stem) > 1 and stem[1] not in "_"):
            continue
        famille = _family(stem)
        if families is None:
            if famille in RESERVED_FAMILIES:
                continue
        elif famille and famille not in families:
            continue
        digit = int(stem[0])
        mask = _read_mask(path)
        if mask is not None:
            variants.setdefault(digit, []).append(_normalized(mask))
    _VARIANTS[cle] = variants
    return variants


def templates_available() -> bool:
    return len(load_templates()) == 10


# ============================================================
# ISOLER LES GLYPHES
# ============================================================

def glyph_mask(crop: np.ndarray) -> np.ndarray:
    """
    Les pixels qui appartiennent à un chiffre.

    Un chiffre est CLAIR (V élevé) et de l'une de trois couleurs : blanc
    (peu saturé), vert (renforcé) ou rouge (affaibli). Tout le reste des
    badges — gemme orange de l'attaque, gemme rouge sombre des PV, gemme
    bleue du coût, cadre doré — est soit plus sombre, soit d'une autre
    teinte. L'orange est exclu EXPLICITEMENT : c'est la seule couleur de
    fond assez lumineuse pour passer le seuil de clarté.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    bright = v >= 150
    white = s <= 95          # blanc, et le bleu très clair du mana de sort
    green = (h >= 35) & (h <= 95) & (s >= 90)
    red = ((h <= 8) | (h >= 165)) & (s >= 150) & (v >= 200)
    orange = (h >= 9) & (h <= 34) & (s >= 90)
    mask = bright & (white | green | red) & ~orange
    return mask.astype(np.uint8)


def glyph_boxes(mask: np.ndarray) -> List[tuple]:
    """
    Les composantes connexes qui ont la taille d'un chiffre, de gauche à
    droite : [(x, y, w, h, masque)]. Les éclats trop petits sont écartés
    ici ; le tri entre chiffres et décor (cadre, reflets de gemme) se fait
    ensuite par la FORME, dans `read_number` — un anneau de cadre est plus
    grand qu'un chiffre, il ne ressemble à aucun.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < 6 or h < 6:
            continue
        boxes.append((int(x), int(y), int(w), int(h), labels == index))
    boxes.sort(key=lambda b: b[0])
    return boxes


# ============================================================
# RECONNAÎTRE
# ============================================================

def _iou(a: np.ndarray, b: np.ndarray, shifts: int = 3) -> float:
    """
    Recouvrement de deux masques normalisés : le MEILLEUR sur de petits
    décalages (±`shifts` px). L'anti-crénelage et le recadrage déplacent
    un glyphe d'un ou deux pixels ; sans cette tolérance, un « 3 » lu un
    peu gras ressemblait autant à un « 5 » qu'à lui-même.
    """
    pad = shifts
    height = max(a.shape[0], b.shape[0]) + 2 * pad
    width = max(a.shape[1], b.shape[1]) + 2 * pad
    canvas_a = np.zeros((height, width), np.uint8)
    ya, xa = (height - a.shape[0]) // 2, (width - a.shape[1]) // 2
    canvas_a[ya:ya + a.shape[0], xa:xa + a.shape[1]] = a
    area_a = int(canvas_a.sum())
    area_b = int(b.sum())
    best = 0.0
    yb0, xb0 = (height - b.shape[0]) // 2, (width - b.shape[1]) // 2
    for dy in range(-pad, pad + 1):
        for dx in range(-pad, pad + 1):
            yb, xb = yb0 + dy, xb0 + dx
            if yb < 0 or xb < 0 or yb + b.shape[0] > height or xb + b.shape[1] > width:
                continue
            window = canvas_a[yb:yb + b.shape[0], xb:xb + b.shape[1]]
            inter = int(np.logical_and(window, b).sum())
            union = area_a + area_b - inter
            if union and inter / union > best:
                best = inter / union
    return best


def _equalize_stroke(shape: np.ndarray, target_fill: float) -> np.ndarray:
    """
    Amincit ou épaissit le glyphe jusqu'à la densité du template comparé.

    Le masque couleur prend l'anti-crénelage : un chiffre lu à l'écran est
    plus GRAS que le template détouré, et un « 3 » gras remplit le creux
    qui le distingue d'un « 5 ». On ramène les deux à la même épaisseur de
    trait avant de comparer les formes — pas les graisses.
    """
    kernel = np.ones((3, 3), np.uint8)
    current = shape
    for _ in range(4):
        fill = current.mean()
        if abs(fill - target_fill) < 0.04:
            break
        step = cv2.erode(current, kernel) if fill > target_fill else cv2.dilate(current, kernel)
        if abs(step.mean() - target_fill) >= abs(fill - target_fill) or not step.any():
            break
        current = step
    return current


def match_glyph(component: np.ndarray, families=None) -> tuple:
    """
    Le chiffre le plus proche de ce glyphe : (chiffre|None, score, marge).
    None quand le score est trop bas ou le second candidat trop proche.
    """
    templates = load_templates()
    if not templates:
        return None, 0.0, 0.0
    shape = _normalized(component)
    variants = load_variants(families=families)
    # Le score d'un chiffre est celui de sa MEILLEURE variante ; la marge
    # se mesure entre deux chiffres différents, jamais entre deux polices
    # du même chiffre.
    scores = sorted(
        (
            max(_iou(_equalize_stroke(shape, float(t.mean())), t)
                for t in variants.get(digit, [templates[digit]])),
            digit,
        )
        for digit in templates
    )
    scores.reverse()
    best_score, best = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    margin = best_score - second
    if best_score < MIN_SCORE or margin < MIN_MARGIN:
        return None, best_score, margin
    return best, best_score, margin


def read_number(crop: Optional[np.ndarray], maximum: int = 99, debug: bool = False,
                loose: bool = False, families=None) -> Optional[int]:
    """
    Le nombre affiché dans ce badge, ou None si le doute existe.

    None n'est pas 0 : c'est « je ne sais pas », et l'appelant a alors
    l'OCR en repli. Un chiffre douteux vaut toujours mieux non lu que
    mal lu — un mana faux fait jouer n'importe quoi.

    Par défaut, seule une lecture SÛRE (CONFIDENT_*) est rendue. Avec
    `loose=True`, un simple candidat (MIN_*) suffit : c'est le dernier
    recours quand l'OCR n'a rien lu du tout.
    """
    if crop is None or crop.size == 0 or not templates_available():
        return None
    mask = glyph_mask(crop)
    recognized = []
    inconnus = []
    for x, y, w, h, component in glyph_boxes(mask):
        digit, score, margin = match_glyph(component, families=families)
        if debug:
            print(f"    glyphe {w}x{h} en x={x} -> {digit} (score {score:.2f}, marge {margin:.2f})")
        if digit is None:
            inconnus.append(h)
            continue
        if not loose and (score < CONFIDENT_SCORE or margin < CONFIDENT_MARGIN):
            if debug:
                print("       candidat seulement : l'OCR tranchera")
            return None
        recognized.append((x, h, digit))
    if not recognized:
        return None
    # Deux chiffres d'un même nombre ont la même hauteur : un reflet reconnu
    # par hasard comme un « 1 » minuscule à côté d'un vrai « 5 » ne fait pas
    # « 15 ».
    tallest = max(h for _, h, _ in recognized)
    # UN GLYPHE DE LA TAILLE D'UN CHIFFRE QU'ON N'A PAS SU LIRE REFUSE LE
    # NOMBRE ENTIER. Il était simplement SAUTÉ, et « 19 » devenait « 1 » :
    # mesuré le 08/11/2026 sur le titre « DÉFI 19 », dont le 9 n'était pas
    # encore dans la police (puis, une fois appris, restait ambigu avec le
    # 6). Le bot a lu le palier 1 au lieu de 19 — une table d'allocation
    # qui demande 4 étoiles en aurait réclamé 3. `lire_palier` promet
    # pourtant « jamais une valeur approchée » : c'est ici que la promesse
    # se tient. On ne refuse que ce qui a la TAILLE d'un chiffre du
    # nombre : même bande basse que `digits_found`, et un plafond pour
    # laisser passer le décor (bord de gemme, éclat de cadre, anneau),
    # que `glyph_boxes` laisse entrer exprès et qui n'a jamais tout à
    # fait la hauteur d'un chiffre.
    bas, haut = UNKNOWN_HEIGHT_BAND
    for h in inconnus:
        if tallest * bas <= h <= tallest * haut:
            if debug:
                print(f"    un glyphe de {h} px n'a pas été reconnu : "
                      "le nombre n'est pas lisible")
            return None
    digits_found = [(x, d) for x, h, d in recognized if h >= tallest * MIN_RELATIVE_HEIGHT]
    if len(digits_found) > 2:
        if debug:
            print(f"    {len(digits_found)} chiffres : pas un nombre")
        return None
    value = int("".join(str(d) for _, d in sorted(digits_found)))
    if value > maximum:
        if debug:
            print(f"    {value} hors borne [0, {maximum}]")
        return None
    return value


# ============================================================
# CLI
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Lecture d'un nombre par la forme des chiffres.")
    parser.add_argument("image", help="un badge découpé, un template, ou une carte de debug_cards/")
    parser.add_argument("--max", type=int, default=99)
    parser.add_argument("--loose", action="store_true", help="accepter un simple candidat")
    args = parser.parse_args()
    image = cv2.imread(args.image, cv2.IMREAD_UNCHANGED)
    if image is None:
        sys.exit(f"Image illisible : {args.image}")
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    print(f"{args.image} ({image.shape[1]}x{image.shape[0]})")
    print(f"  lu : {read_number(image, args.max, debug=True, loose=args.loose)}")


if __name__ == "__main__":
    main()
