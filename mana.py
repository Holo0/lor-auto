#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mana.py

Lecture du mana de tour et du mana de sort sur le cadran en bas à droite.

--------------------------------------------------------------------
POURQUOI PAS detect_chiffres.ocr_number
--------------------------------------------------------------------
`ocr_number` filtre les crops AVANT de lire : il exige au moins 3 % de
pixels verts/jaunes (attaque) ou rouges (PV), et rejette les crops
majoritairement blancs. C'est exactement ce qu'il faut pour les stats
d'une unité, et exactement ce qu'il ne faut pas ici : les chiffres du
cadran de mana sont BLANCS sur fond bleu et doré. Ils seraient écartés
avant même d'atteindre l'OCR. Le prétraitement pertinent est différent,
donc le code est différent.

Le modèle easyocr est en revanche PARTAGÉ avec detect_chiffres (voir
`_get_reader`) : en charger un deuxième doublerait le temps de démarrage
et l'occupation VRAM pour rien.

--------------------------------------------------------------------
ZONES
--------------------------------------------------------------------
Calibrées par Ewan en 1920x1080 dans board_state_reader.py :
    mana        (1591, 636, 1708, 676)
    mana de sort(1605, 682, 1660, 715)
Converties ici en RATIOS de la fenêtre : identiques au pixel près en
1920x1080, mais elles suivent si la résolution change.

--------------------------------------------------------------------
FIABILITÉ DE LA LECTURE
--------------------------------------------------------------------
Deux garde-fous, parce qu'un mana mal lu fait jouer n'importe quoi :

1. VOTE. Le crop est binarisé de plusieurs façons (Otsu, Otsu inversé,
   seuils fixes) et chaque variante est lue. On garde la valeur
   majoritaire, pas la première qui tombe : sur un fond chargé les
   variantes sont souvent en désaccord, et la majorité tranche mieux
   qu'un ordre arbitraire.

2. BORNES. Une valeur hors plage est rejetée. Le mana de tour ne dépasse
   pas 10 et le mana de sort pas 3 : lire « 18 » signifie qu'on a lu du
   décor, pas un chiffre. Sans cette borne, un bruit plausible passe.

    python mana.py            # lit et affiche
    python mana.py --crops    # exporte les crops pour recalibrer
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import lor_api
from lor_api import Window

LOGGER = logging.getLogger(__name__)

# ============================================================
# ZONES ET BORNES
# ============================================================

REFERENCE_SIZE = (1920, 1080)
MANA_BOX = (1591, 636, 1708, 676)        # (left, top, right, bottom)
SPELL_MANA_BOX = (1605, 682, 1660, 715)

# PV de NOTRE nexus : la gemme bleue dans la moitié BASSE de l'écran.
# À ne pas confondre avec la grosse gemme rouge en haut, qui est celle de
# l'adversaire — se tromper de gemme inverserait complètement la décision
# de blocage sacrificiel.
NEXUS_HEALTH_BOX = (255, 620, 340, 690)


def _to_region(box, reference=REFERENCE_SIZE):
    """(left, top, right, bottom) en pixels -> ((rx1, ry1), (rx2, ry2))."""
    left, top, right, bottom = box
    width, height = reference
    return ((left / width, top / height), (right / width, bottom / height))


MANA_REGION = _to_region(MANA_BOX)
SPELL_MANA_REGION = _to_region(SPELL_MANA_BOX)
NEXUS_HEALTH_REGION = _to_region(NEXUS_HEALTH_BOX)

# Plafonds du jeu. Si une lecture légitime les dépasse un jour (effet
# exotique), remonter la borne — mais la resserrer est ce qui filtre le
# bruit, donc ne pas la retirer.
MANA_MAX = 10
SPELL_MANA_MAX = 3

# 20 PV au départ en partie classique, davantage dans certaines aventures.
# 30 est un compromis : assez large pour les aventures, assez serré pour
# que du bruit lu à trois chiffres soit rejeté.
NEXUS_HEALTH_MAX = 30

UPSCALE = 4
FIXED_THRESHOLDS = (110, 140, 170, 200)
DIGITS = "0123456789"

_READER = None


# ============================================================
# OCR
# ============================================================

def _get_reader():
    """
    Instance easyocr partagée avec detect_chiffres si ce module est déjà
    chargé, sinon créée ici. Le partage évite un second modèle en VRAM.
    """
    global _READER
    if _READER is not None:
        return _READER
    try:
        from detect_chiffres import reader as shared_reader
        _READER = shared_reader
    except Exception as exc:
        LOGGER.debug("Lecteur partagé indisponible (%s), création d'un lecteur dédié.", exc)
        import easyocr
        _READER = easyocr.Reader(["en"], gpu=True)
    return _READER


def _binarisation_variants(crop: np.ndarray):
    """Plusieurs binarisations du même crop, pour faire voter l'OCR."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants = [("otsu", otsu), ("otsu_inverse", cv2.bitwise_not(otsu))]
    for threshold in FIXED_THRESHOLDS:
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        variants.append((f"seuil{threshold}", binary))
    return variants


def read_digits(crop: Optional[np.ndarray], maximum: int, debug: bool = False) -> Optional[int]:
    """
    Lit un entier dans un crop, par vote entre plusieurs binarisations.
    Renvoie None si aucune lecture ne tombe dans [0, maximum].
    """
    if crop is None or crop.size == 0:
        return None

    reader = _get_reader()
    votes = Counter()

    for name, image in _binarisation_variants(crop):
        for text in reader.readtext(image, detail=0, allowlist=DIGITS):
            digits = "".join(ch for ch in str(text) if ch.isdigit())
            if not digits:
                continue
            value = int(digits)
            if 0 <= value <= maximum:
                votes[value] += 1
            elif debug:
                print(f"    {name}: {value} rejeté (hors [0, {maximum}])")

    if debug:
        print(f"    votes : {dict(votes)}")
    if not votes:
        return None
    return votes.most_common(1)[0][0]


# ============================================================
# RÉSERVE DE MANA
# ============================================================

@dataclass
class ManaPool:
    """Mana disponible. None = lecture échouée, à ne pas confondre avec 0."""

    mana: Optional[int] = None
    spell_mana: Optional[int] = None

    @property
    def readable(self) -> bool:
        return self.mana is not None

    def __str__(self) -> str:
        def fmt(value):
            return "?" if value is None else str(value)
        return f"mana {fmt(self.mana)} + sort {fmt(self.spell_mana)}"


def can_pay(card, pool: ManaPool) -> bool:
    """
    Le coût de la carte est-il payable ?

    RÈGLE DU JEU À NE PAS RATER : le mana de sort ne paie QUE les sorts.
    Une unité à 4 avec 3 mana et 3 mana de sort n'est pas jouable, même si
    le total fait 6. Confondre les deux réserves fait tenter des poses
    impossibles à chaque tour.
    """
    if pool.mana is None:
        return False
    available = pool.mana
    if card.is_spell:
        available += pool.spell_mana or 0
    return card.cost <= available


def crop_region(screen: np.ndarray, window: Window, region: tuple) -> Optional[np.ndarray]:
    return lor_api.crop_box(screen, window.rel_box(region))


def read_mana_pool(
    screen: Optional[np.ndarray] = None,
    window: Optional[Window] = None,
    debug: bool = False,
) -> ManaPool:
    """Lit les deux réserves sur une seule capture d'écran."""
    window = window or lor_api.get_window()
    if screen is None:
        screen = lor_api.capture_screen_bgr()

    if debug:
        print("  mana :")
    mana = read_digits(crop_region(screen, window, MANA_REGION), MANA_MAX, debug)
    if debug:
        print("  mana de sort :")
    spell = read_digits(crop_region(screen, window, SPELL_MANA_REGION), SPELL_MANA_MAX, debug)

    if mana is None:
        LOGGER.warning(
            "Mana illisible : aucune action de pose ne sera tentée. "
            "Vérifie les zones avec `python mana.py --crops`."
        )
    return ManaPool(mana=mana, spell_mana=spell)


def read_nexus_health(
    screen: Optional[np.ndarray] = None,
    window: Optional[Window] = None,
    debug: bool = False,
) -> Optional[int]:
    """
    PV de NOTRE nexus, ou None si illisible.

    None n'est pas 0 : l'appelant doit traiter le cas « je ne sais pas »
    différemment de « je suis à un point de perdre ». Confondre les deux
    ferait sacrifier des unités sans raison à chaque tour.
    """
    window = window or lor_api.get_window()
    if screen is None:
        screen = lor_api.capture_screen_bgr()
    if debug:
        print("  PV nexus :")
    return read_digits(
        crop_region(screen, window, NEXUS_HEALTH_REGION), NEXUS_HEALTH_MAX, debug
    )


# ============================================================
# CALIBRATION
# ============================================================

def save_crops(output_dir: str = "calibration_crops") -> None:
    """Exporte les deux crops et leurs binarisations, pour recalibrer."""
    window = lor_api.get_window()
    screen = lor_api.capture_screen_bgr()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for label, region in (
        ("mana", MANA_REGION),
        ("mana_sort", SPELL_MANA_REGION),
        ("pv_nexus", NEXUS_HEALTH_REGION),
    ):
        box = window.rel_box(region)
        crop = crop_region(screen, window, region)
        if crop is None:
            print(f"{label:<10} zone hors cadre {box}")
            continue
        cv2.imwrite(str(out / f"{label}_zone.png"), crop)
        for name, image in _binarisation_variants(crop):
            cv2.imwrite(str(out / f"{label}_{name}.png"), image)
        print(f"{label:<10} box={box} taille={crop.shape[1]}x{crop.shape[0]}")

    print(f"\nCrops exportés dans {out.resolve()}")
    print("La zone doit contenir UNIQUEMENT le chiffre, sans le contour du")
    print("cadran : un bord doré est lu comme un 0 ou un 8 une fois sur deux.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lecture du mana (Legends of Runeterra).")
    parser.add_argument("--crops", action="store_true", help="exporte les crops de calibration")
    parser.add_argument("--debug", action="store_true", help="détaille les votes de l'OCR")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.crops:
        save_crops()
        return

    screen = lor_api.capture_screen_bgr()
    window = lor_api.get_window()
    pool = read_mana_pool(screen=screen, window=window, debug=args.debug)
    health = read_nexus_health(screen=screen, window=window, debug=args.debug)
    print(f"\n{pool}")
    print(f"PV nexus : {'?' if health is None else health}")


if __name__ == "__main__":
    main()
