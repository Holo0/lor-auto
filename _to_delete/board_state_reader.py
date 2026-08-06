#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
board_state_reader.py

Lecture de l'état du plateau (Legends of Runeterra) par OCR sur des
zones d'écran fixes, et par segmentation d'image pour le banc.
Contrairement au template matching (qui détecte une image FIXE comme
un bouton ou une icône), ici on lit des VALEURS qui changent à chaque
tour (PV du nexus, mana, cartes du banc), donc on passe par de l'OCR
(Tesseract via pytesseract) sur des zones recadrées plutôt que du
matching d'image pur.

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

IMPORTANT — effets visuels sur les cartes (bouclier anti-sort, gel,
etc.) : ces effets posent un calque semi-transparent coloré sur toute
la carte, y compris sur les cases attaque/vie. Une lecture couleur
(chercher un orange/rouge précis) casse dans ce cas, car la teinte du
badge change avec l'effet actif. `_read_relative_number()` ne dépend
donc PAS d'une couleur : elle binarise en noir/blanc ET essaie la
version inversée (texte clair sur fond sombre ET texte sombre sur
fond clair), ce qui couvre le cas où l'effet éclaircit ou assombrit
le badge. C'est plus lent qu'un seuil fixe unique mais bien plus
robuste face aux effets visuels imprévisibles.

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ============================================================
# ZONES CALIBRÉES (left, top, right, bottom) en pixels, réf. 1920x1080
# ============================================================

REGIONS = {
    "nexus_health": (255, 620, 340, 690),
    "mana": (1591, 636, 1708, 676),
    "spell_mana": (1605, 682, 1660, 715),
}
BENCH_REGION = (500, 800, 880, 180)
# BENCH_REGION = (524, 800, 1400, 990)
ATTACK_REL = (0.30, 0.08, 0.28, 0.20)
HEALTH_REL = (0.62, 0.08, 0.28, 0.20)

BENCH_CARD_MIN_AREA = 15000
BENCH_CARD_MAX_AREA = 120000
BENCH_CARD_ASPECT_MIN = 0.4
BENCH_CARD_ASPECT_MAX = 2.0
BENCH_BINARY_THRESHOLD = 0
BENCH_SLOTS = 6

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
# LECTURE OCR — NEXUS / MANA / SPELL MANA
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


def _read_relative_number(slot_crop, rel_box):
    """
    Lit un nombre entier sur une zone relative d'un emplacement du banc.
    Plusieurs seuils de binarisation sont essayés pour la robustesse.
    Retourne un int, ou None si aucun chiffre valide n'est lu.
    """
    x, y, w, h = rel_box
    abs_box = (
        int(x * slot_crop.width),
        int(y * slot_crop.height),
        int((x + w) * slot_crop.width),
        int((y + h) * slot_crop.height),
    )
    crop = slot_crop.crop(abs_box)
    crop = crop.resize((crop.width * 4, crop.height * 4), Image.BICUBIC)
    grayscale = ImageOps.autocontrast(crop.convert("L"))

    for threshold in (140, 160, 180, 200):
        bw = grayscale.point(lambda p, t=threshold: 255 if p > t else 0)
        text = pytesseract.image_to_string(bw, config=OCR_CONFIG).strip()
        if text.isdigit():
            return int(text)

    return None


def read_bench_state(image=None):
    """
    Lit l'état du banc sans détection couleur ni segmentation :
    la zone BENCH_REGION est découpée en BENCH_SLOTS emplacements
    verticaux, et pour chacun on lit directement attaque / PV par OCR
    sur les zones relatives ATTACK_REL / HEALTH_REL.

    Retourne une liste, ex:
        [{"type": "monster", "attack": 3, "health": 4}, ...]
    """
    image = image or capture_screen()
    bench_crop = crop_region(image, BENCH_REGION)

    slot_width = bench_crop.width / BENCH_SLOTS
    slot_height = bench_crop.height

    result = []
    for i in range(BENCH_SLOTS):
        left = int(i * slot_width)
        right = int((i + 1) * slot_width)
        slot_crop = bench_crop.crop((left, 0, right, slot_height))

        attack = _read_relative_number(slot_crop, ATTACK_REL)
        health = _read_relative_number(slot_crop, HEALTH_REL)
        if attack is not None or health is not None:
            result.append({"type": "monster", "attack": attack, "health": health})

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
    et chaque emplacement du banc, en PNG dans output_dir.
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

    slot_width = bench_crop.width / BENCH_SLOTS
    slot_height = bench_crop.height
    for i in range(BENCH_SLOTS):
        left = int(i * slot_width)
        right = int((i + 1) * slot_width)
        slot_crop = bench_crop.crop((left, 0, right, slot_height))
        slot_path = os.path.join(output_dir, f"bench_slot_{i}.png")
        slot_crop.save(slot_path)
        logging.info(f"  Slot {i} exporté : {slot_path}")


if __name__ == "__main__":
    state = read_board_state()
    logging.info(f"État du plateau lu : {state}")