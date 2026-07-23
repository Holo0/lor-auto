#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""

board_state_reader.py

 

Lecture de l'état du plateau (Legends of Runeterra) par OCR sur des

zones d'écran fixes. Contrairement au template matching (qui détecte

une image FIXE comme un bouton ou une icône), ici on lit des VALEURS

qui changent à chaque tour (PV du nexus, mana), donc on passe par de

l'OCR (Tesseract via pytesseract) sur une zone recadrée plutôt que du

matching d'image.

 

Outil de test QA local : lecture d'écran uniquement, aucune

interaction avec le client ni les serveurs.

 

--------------------------------------------------------------------

ÉTAT ACTUEL (résolution de référence : 1920x1080)

--------------------------------------------------------------------

Les valeurs suivantes sont calibrées et peuvent être lues :

    - nexus_health : PV du nexus joueur (gemme bleue, moitié basse

      de l'écran, sous l'icône œil — attention, NE PAS confondre avec

      le gros gemme rouge en haut de l'écran, qui est le nexus de

      l'ADVERSAIRE)

    - mana         : mana de tour, affiché sur le cadran rond en bas

      à droite de l'écran (label "10" sur le cadran)

    - spell_mana   : mana de sort stocké, juste en dessous du mana sur

      le même cadran (label "3", avec des points représentant le

      stock actuel)

    - bench        : cartes sur le banc, détectées dynamiquement par

      slots. Pour chaque carte présente :

        - monstre : {"type": "monster", "attack": X, "health": Y}

        - landmark : {"type": "landmark"}

 

Les zones bench sont détectées automatiquement dans la zone rectangulaire

BENCH_REGION. Si la lecture des stats attaque/health échoue pour une

carte, elle est classée en "landmark" par défaut.

 

Le texte des stats attaque (case jaune) et vie (case rouge/rose) est

lu par OCR après prétraitement par binarisation.

 

Le texte de ces trois zones est blanc sur fond très chargé (feuillage,

dorures) : une lecture OCR brute échoue souvent ou renvoie du bruit.

Il faut donc binariser (niveaux de gris + seuillage) chaque zone avant

l'OCR — voir `_preprocess_for_ocr()`.

 

--------------------------------------------------------------------

CALIBRAGE / ADAPTATION À UNE AUTRE RÉSOLUTION

--------------------------------------------------------------------

Les coordonnées ci-dessous sont en pixels absolus, calibrées pour du

1920x1080. Si votre résolution diffère, utilisez `save_region_crops()`

pour exporter chaque zone en PNG et ajuster les coordonnées à l'oeil

jusqu'à ce que la zone n'entoure QUE les chiffres (pas le contour du

gemme/icône, qui perturbe l'OCR).

"""

 

import os

import logging

 

from PIL import Image, ImageOps

import pyautogui

import pytesseract

import cv2

import numpy as np

 

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

 

logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s [%(levelname)s] %(message)s",

)

 

# ============================================================

# ZONES CALIBRÉES (left, top, right, bottom) en pixels, réf. 1920x1080

# ============================================================

 

REGIONS = {

    "nexus_health": (255, 620, 340, 690),

    "mana": (1591, 636, 1638, 676),

    "spell_mana": (1625, 682, 1660, 715),

}

BENCH_REGION = (524, 813, 1415, 980)

ATTACK_REL = (0.05, 0.10, 0.22, 0.30)

HEALTH_REL = (0.70, 0.60, 0.25, 0.35)



BENCH_CARD_MIN_AREA = 15000

BENCH_CARD_MAX_AREA = 120000

BENCH_CARD_ASPECT_MIN = 0.4

BENCH_CARD_ASPECT_MAX = 2.0

BENCH_BINARY_THRESHOLD = 120

 

# Configuration Tesseract : une seule ligne de texte, chiffres uniquement.

OCR_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789"

 

# Seuil de binarisation (0-255) : les pixels plus clairs que ce seuil

# deviennent blancs, les autres noirs. À ajuster si l'OCR échoue sur

# votre thème d'interface (contour doré plus ou moins lumineux selon

# la luminosité en jeu).

BW_THRESHOLD = 180

 

# ============================================================

# CAPTURE / CROP / PRÉTRAITEMENT

# ============================================================

 

def capture_screen():

    """Capture l'écran courant (image PIL)."""

    return pyautogui.screenshot()

 

def crop_region(image, region):

    """Découpe une zone (left, top, right, bottom) d'une image PIL."""

    return image.crop(region)

 

def _preprocess_for_ocr(crop, threshold=BW_THRESHOLD):

    """

    Convertit une zone en noir et blanc pur pour fiabiliser l'OCR sur

    un fond de jeu chargé (texte blanc sur feuillage/dorures). Sans ce

    prétraitement, Tesseract confond souvent les motifs du décor avec

    des chiffres.

    """

    grayscale = ImageOps.autocontrast(crop.convert("L"))

    return grayscale.point(lambda p: 255 if p > threshold else 0)

 

# ============================================================

# LECTURE OCR

# ============================================================

 

def read_number(image, region_name):

    """

    Lit un nombre entier dans la zone `region_name` de l'image donnée.

 

    Essaie d'abord une version binarisée (fiable sur fond très chargé),

    puis retombe sur la version brute si la binarisation échoue — le

    seuil optimal peut varier légèrement selon la luminosité en jeu ou

    la compression (PNG vs JPG), la version brute rattrape ces cas.

 

    Retourne un int, ou None si aucune des deux lectures n'est un

    nombre valide.

    """

    if region_name not in REGIONS:

        logging.error(f"Zone inconnue : {region_name}")

        return None

 

    crop = crop_region(image, REGIONS[region_name])

 

    bw = _preprocess_for_ocr(crop)

    text_bw = pytesseract.image_to_string(bw, config=OCR_CONFIG).strip()

    if text_bw.isdigit():

        return int(text_bw)

 

    text_raw = pytesseract.image_to_string(crop, config=OCR_CONFIG).strip()

    if text_raw.isdigit():

        return int(text_raw)

 

    logging.warning(f"OCR illisible pour '{region_name}' : bw={text_bw!r} raw={text_raw!r}")

    return None

 

def read_nexus_health(image=None):

    """Retourne les PV actuels du nexus joueur, ou None si illisible."""

    image = image or capture_screen()

    return read_number(image, "nexus_health")

 

def read_mana(image=None):

    """Retourne le mana de tour disponible, ou None si illisible."""

    image = image or capture_screen()

    return read_number(image, "mana")

 

def read_spell_mana(image=None):

    """Retourne le mana de sort stocké, ou None si illisible."""

    image = image or capture_screen()

    return read_number(image, "spell_mana")

 

def _is_slot_occupied(slot_crop):

    grayscale = slot_crop.convert("L")

    min_val, max_val = grayscale.getextrema()

    return (max_val - min_val) > 30

 

def _find_card_crops(bench_crop):

    cv_img = cv2.cvtColor(np.array(bench_crop), cv2.COLOR_RGB2GRAY)

    _, binary = cv2.threshold(cv_img, BENCH_BINARY_THRESHOLD, 255, cv2.THRESH_BINARY)

 

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    cards = []

    for i in range(1, num_labels):

        x, y, w, h, area = stats[i]

        if area < BENCH_CARD_MIN_AREA or area > BENCH_CARD_MAX_AREA:

            continue

        if h == 0:

            continue

        aspect = w / h

        if aspect < BENCH_CARD_ASPECT_MIN or aspect > BENCH_CARD_ASPECT_MAX:

            continue

        cards.append(bench_crop.crop((x, y, x + w, y + h)))

    return cards

 

def _read_relative_number(slot_crop, rel_zone):

    w, h = slot_crop.size

    x = int(rel_zone[0] * w)

    y = int(rel_zone[1] * h)

    rw = int(rel_zone[2] * w)

    rh = int(rel_zone[3] * h)

 

    case_crop = slot_crop.crop((x, y, x + rw, y + rh))

    grayscale = ImageOps.autocontrast(case_crop.convert("L"))

 

    bw = grayscale.point(lambda p: 255 if p > BW_THRESHOLD else 0)

    text = pytesseract.image_to_string(bw, config=OCR_CONFIG).strip()

    if text.isdigit():

        return int(text)

 

    inv = grayscale.point(lambda p: 255 if p < BW_THRESHOLD else 0)

    text = pytesseract.image_to_string(inv, config=OCR_CONFIG).strip()

    if text.isdigit():

        return int(text)

 

    return None

 

def read_bench_state(image=None):

    """

    Lit l'état du banc en détectant dynamiquement les cartes présentes

    par segmentation, au lieu de découper la zone en slots fixes.

    Le nombre de cartes peut donc varier d'un tour à l'autre.

 

    Retourne une liste, ex:

        [

            {"type": "monster", "attack": 3, "health": 2},

            {"type": "landmark"},

        ]

    """

    image = image or capture_screen()

    bench_crop = crop_region(image, BENCH_REGION)

    card_crops = _find_card_crops(bench_crop)

    card_crops.sort(key=lambda c: c.size)

 

    result = []

    for card_crop in card_crops:

        attack = _read_relative_number(card_crop, ATTACK_REL)

        health = _read_relative_number(card_crop, HEALTH_REL)

 

        if attack is not None and health is not None:

            result.append({"type": "monster", "attack": attack, "health": health})

        else:

            result.append({"type": "landmark"})

 

    return result

 

def read_board_state():

    """

    Capture l'écran une seule fois et lit toutes les valeurs connues

    en une passe (évite un screenshot par valeur).

 

    Retourne un dict, ex: {"nexus_health": 2, "mana": 10, "spell_mana": 3, "bench": [...]}

    Les clés dont la lecture échoue valent None. "bench" vaut [] si aucune

    carte n'est détectée.

    """

    image = capture_screen()

    return {

        "nexus_health": read_number(image, "nexus_health"),

        "mana": read_number(image, "mana"),

        "spell_mana": read_number(image, "spell_mana"),

        "bench": read_bench_state(image),

    }

 

# ============================================================

# CALIBRAGE

# ============================================================

 

def save_region_crops(output_dir="calibration_crops", image=None):

    """

    Exporte chaque zone de REGIONS, ainsi que la zone bench complète

    et chaque slot individuel, en PNG dans output_dir. Utile pour

    recalibrer les positions relatives des cases d'attaque / PV

    (ATTACK_REL, HEALTH_REL) et vérifier la détection des slots occupés.

    """

    os.makedirs(output_dir, exist_ok=True)

    image = image or capture_screen()

 

    for name, region in REGIONS.items():

        crop = crop_region(image, region)

        path = os.path.join(output_dir, f"{name}.png")

        crop.save(path)

        logging.info(f"Zone '{name}' exportée : {path}")

 

    bench_crop = crop_region(image, BENCH_REGION)

    bench_path = os.path.join(output_dir, "bench.png")

    bench_crop.save(bench_path)

    logging.info(f"Zone 'bench' exportée : {bench_path}")

    cv_img = cv2.cvtColor(np.array(bench_crop), cv2.COLOR_RGB2GRAY)

    _, binary = cv2.threshold(cv_img, BENCH_BINARY_THRESHOLD, 255, cv2.THRESH_BINARY)

    binary_pil = Image.fromarray(binary)

    binary_path = os.path.join(output_dir, "bench_binary.png")

    binary_pil.save(binary_path)

    logging.info(f"Binarisation bench exportée : {binary_path}")

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    logging.info(f"Composantes connectées détectées : {num_labels - 1}")

    for i in range(1, num_labels):

        x, y, w, h, area = stats[i]

        aspect = w / h if h != 0 else 0

        keep = area >= BENCH_CARD_MIN_AREA and area <= BENCH_CARD_MAX_AREA and BENCH_CARD_ASPECT_MIN <= aspect <= BENCH_CARD_ASPECT_MAX

        logging.info(f"  Composante {i}: x={x} y={y} w={w} h={h} area={area} aspect={aspect:.2f} -> {'GARDÉE' if keep else 'REJETÉE'}")

        if keep:

            card_path = os.path.join(output_dir, f"bench_card_{i}.png")

            bench_crop.crop((x, y, x + w, y + h)).save(card_path)

            logging.info(f"    Carte exportée : {card_path}")

 

if __name__ == "__main__":

    state = read_board_state()

    logging.info(f"État du plateau lu : {state}")