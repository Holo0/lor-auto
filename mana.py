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

    python mana.py                   # lit mana, mana de sort et les DEUX nexus
    python mana.py --crops           # exporte les crops pour recalibrer
    python mana.py --calibrate-nexus # encadre les PV des deux nexus à la souris
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import digits

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

# 20 PV au départ en partie classique, 30 dans le défi (vu le 05/09/2026),
# et DAVANTAGE pour certains boss et avec les reliques de Path of
# Champions. À 30, un nexus adverse à 35 PV était « illisible » — et sans
# ses PV, aucune attaque létale n'est jamais tentée. `digits.read_number`
# refuse déjà tout nombre à trois chiffres : la borne ne protège plus que
# de très peu de bruit, on la laisse large.
NEXUS_HEALTH_MAX = 99

UPSCALE = 4
FIXED_THRESHOLDS = (110, 140, 170, 200)
DIGITS = "0123456789"

_READER = None

# `--sans-ocr` : ne jamais charger easyocr. La forme (digits.py) lit tout,
# en mode tolérant quand elle doute. À comparer au journal (`config.ocr`)
# avant d'en faire le défaut : cf. digits.USAGE.
OCR_DISABLED = False


# ============================================================
# OCR
# ============================================================

class OCRIndisponible(RuntimeError):
    """easyocr est absent de l'interpréteur courant."""


OCR_MISSING_MSG = (
    "easyocr est introuvable : l'interpréteur qui exécute le bot n'est pas "
    "celui du projet (`.venv`, Python 3.12).\n"
    "    .\\.venv\\Scripts\\Activate.ps1\n"
    "    pip install -r requirements.txt        # seulement si easyocr manque vraiment\n"
    "Contrôle : python -c \"import sys, easyocr; print(sys.executable)\""
)


def _get_reader():
    """
    Instance easyocr partagée avec detect_chiffres si ce module est déjà
    chargé, sinon créée ici. Le partage évite un second modèle en VRAM.

    Lève OCRIndisponible — et pas ModuleNotFoundError — quand easyocr
    manque : le message dit alors quoi faire, et `preload_reader` peut
    l'attraper avant que la boucle ne touche à la partie.
    """
    global _READER
    if _READER is not None:
        return _READER
    if OCR_DISABLED:
        raise OCRIndisponible("easyocr désactivé (--sans-ocr) : lecture par la forme seule.")
    try:
        from detect_chiffres import get_reader
        _READER = get_reader()
        return _READER
    except ImportError as exc:
        raise OCRIndisponible(OCR_MISSING_MSG) from exc
    except Exception as exc:
        LOGGER.debug("Lecteur partagé indisponible (%s), création d'un lecteur dédié.", exc)
    try:
        import easyocr
    except ImportError as exc:
        raise OCRIndisponible(OCR_MISSING_MSG) from exc
    _READER = easyocr.Reader(["en"], gpu=True)
    return _READER


def preload_reader() -> None:
    """
    Charge le modèle OCR AVANT que la boucle ne touche à la partie.

    Deux raisons de le faire tôt plutôt qu'au premier `read_digits` :

    1. UN ENVIRONNEMENT SANS easyocr PLANTAIT AU TOUR 1, mulligan déjà
       validé et partie en cours — donc une partie abandonnée à chaque
       fois qu'on lance le bot hors de `.venv` (crash du 19/08/2026).
    2. Le chargement du modèle prend une dizaine de secondes ; elles
       tombaient dans le premier tour, chronomètre du jeu compris.

    Avec `--sans-ocr` (OCR_DISABLED), il n'y a rien à charger : on vérifie
    seulement que les glyphes de `chiffres/` sont là, sinon la forme ne
    peut rien lire non plus.
    """
    if OCR_DISABLED:
        if not digits.templates_available():
            raise OCRIndisponible(
                "--sans-ocr demandé mais chiffres/0.png … 9.png manquent : rien ne peut lire le mana."
            )
        return
    _get_reader()


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

    # La forme d'abord (digits.py, ~1 ms) : sûre, elle suffit ; douteuse,
    # l'OCR tranche et elle ne sert qu'en dernier recours.
    fast = digits.read_number(crop, maximum)
    if fast is not None:
        digits.USAGE["forme"] += 1
        if debug:
            print(f"    forme : {fast} (sûr, sans OCR)")
        return fast

    try:
        reader = _get_reader()
    except OCRIndisponible:
        # Pas d'easyocr ici (--sans-ocr, rejeu d'une trace dans une VM,
        # machine sans `.venv`) : la forme seule, en mode tolérant, vaut
        # mieux que rien. Sans --sans-ocr, on n'arrive jamais ici en
        # partie réelle : `preload_reader()` arrête le bot avant le combat.
        value = digits.read_number(crop, maximum, loose=True)
        digits.USAGE["tolerant" if value is not None else "echec"] += 1
        return value
    votes = Counter()

    for name, image in _binarisation_variants(crop):
        for text in reader.readtext(image, detail=0, allowlist=DIGITS):
            found = "".join(ch for ch in str(text) if ch.isdigit())
            if not found:
                continue
            value = int(found)
            if 0 <= value <= maximum:
                votes[value] += 1
            elif debug:
                print(f"    {name}: {value} rejeté (hors [0, {maximum}])")

    if debug:
        print(f"    votes : {dict(votes)}")
    if not votes:
        value = digits.read_number(crop, maximum, loose=True)
        digits.USAGE["tolerant" if value is not None else "echec"] += 1
        return value
    digits.USAGE["easyocr"] += 1
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


# ============================================================
# PV DES NEXUS — DÉCOUPE RELATIVE AU NEXUS
# ============================================================
# La zone n'est PAS en coordonnées d'écran : elle est exprimée en fractions
# du rectangle du nexus, que l'API nous donne pour les DEUX camps. Une
# seule calibration couvre donc notre nexus et celui d'en face, et elle
# survit à un changement de résolution — contrairement à une zone en dur,
# qui ne vaut que pour un côté et une taille d'écran.
#
#     python mana.py --calibrate-nexus
#
# fait encadrer les deux chiffres à la souris et enregistre les offsets.

NEXUS_RELATIVE_KEY = "nexus_health_relative"


def _calibration_path():
    return lor_api.PROJECT_ROOT / "calibration.json"


def _load_relative() -> dict:
    try:
        with open(_calibration_path(), encoding="utf8") as handle:
            value = json.load(handle).get(NEXUS_RELATIVE_KEY) or {}
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_relative(side: str, offsets) -> None:
    path = _calibration_path()
    try:
        with open(path, encoding="utf8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    block = data.get(NEXUS_RELATIVE_KEY)
    if not isinstance(block, dict):
        block = {}
    block[side] = list(offsets)
    data[NEXUS_RELATIVE_KEY] = block
    with open(path, "w", encoding="utf8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def crop_relative_to(screen: np.ndarray, box: tuple, offsets: tuple):
    """Découpe une zone exprimée en fractions d'un rectangle de référence."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    rx, ry, rw, rh = offsets
    return lor_api.crop_box(
        screen,
        (left + rx * width, top + ry * height,
         left + (rx + rw) * width, top + (ry + rh) * height),
    )


def read_nexus_health(
    snapshot=None,
    screen: Optional[np.ndarray] = None,
    window: Optional[Window] = None,
    local: bool = True,
    debug: bool = False,
) -> Optional[int]:
    """
    PV d'un nexus, le nôtre par défaut.

    None n'est pas 0 : l'appelant doit traiter « je ne sais pas »
    différemment de « je suis à un point de perdre ». Confondre les deux
    ferait sacrifier des unités sans raison à chaque tour.

    Trois chemins, du plus fiable au moins :
        1. offsets calibrés + rectangle du nexus donné par l'API ;
        2. pour NOTRE nexus seulement, la zone historique en dur ;
        3. None, plutôt qu'une lecture prise au hasard.
    """
    window = window or (snapshot.window if snapshot is not None else lor_api.get_window())
    if screen is None:
        screen = lor_api.capture_screen_bgr()

    side = "local" if local else "enemy"
    offsets = _load_relative().get(side)
    box = None
    if snapshot is not None:
        box = snapshot.our_nexus_box if local else snapshot.enemy_nexus_box

    if debug:
        print(f"  PV nexus {side} :")

    if offsets and box:
        crop = crop_relative_to(screen, box, offsets)
        return read_digits(crop, NEXUS_HEALTH_MAX, debug)

    if local:
        # Repli sur la zone calibrée à la main en 1920x1080. Elle ne vaut
        # que pour notre nexus et cette résolution, d'où l'intérêt de la
        # calibration relative.
        return read_digits(
            crop_region(screen, window, NEXUS_HEALTH_REGION), NEXUS_HEALTH_MAX, debug
        )

    LOGGER.info(
        "PV du nexus adverse non calibrés : lance `python mana.py --calibrate-nexus`."
    )
    return None


def calibrate_nexus_health() -> None:
    """
    Fait encadrer les deux chiffres de PV, et enregistre leur position
    RELATIVE au rectangle de chaque nexus.

    À lancer pendant un combat, les deux nexus visibles.
    """
    import game_state

    try:
        api_data = lor_api.get_positional_rectangles()
    except lor_api.ApiUnavailable as exc:
        print(f"API injoignable : {exc}")
        return

    window = lor_api.get_window(api_data)
    rectangles = api_data.get("Rectangles") or []
    our_box, enemy_box = game_state.nexus_boxes(rectangles, window)

    if not our_box or not enemy_box:
        print("Les deux nexus ne sont pas visibles : lance ceci pendant un combat.")
        return

    screen = lor_api.capture_screen_bgr()
    print(f"Nexus allié   : {our_box}")
    print(f"Nexus adverse : {enemy_box}\n")

    for side, box, label in (
        ("local", our_box, "TON nexus (gemme du bas)"),
        ("enemy", enemy_box, "le nexus ADVERSE (gemme du haut)"),
    ):
        print(f"Encadre le chiffre de PV de {label}, puis ENTRÉE.")
        selection = game_state.pick_box_tk(screen, title=f"Chiffre de PV — {label}")
        if selection is None:
            print("  annulé, on s'arrête là.")
            return

        x, y, w, h = selection
        left, top, right, bottom = box
        ref_w, ref_h = right - left, bottom - top
        offsets = (
            (x - left) / ref_w, (y - top) / ref_h,
            w / ref_w, h / ref_h,
        )
        _save_relative(side, offsets)

        value = read_digits(crop_relative_to(screen, box, offsets), NEXUS_HEALTH_MAX)
        print(f"  offsets ({offsets[0]:.3f}, {offsets[1]:.3f}, "
              f"{offsets[2]:.3f}, {offsets[3]:.3f}) -> lecture : {value}\n")

    print(f"Enregistré dans {_calibration_path().name}.")
    print("La lecture suivra désormais la position des nexus donnée par l'API,")
    print("des deux côtés et à n'importe quelle résolution.")


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
    parser.add_argument("--calibrate-nexus", action="store_true",
                        help="encadrer les PV des deux nexus à la souris")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.calibrate_nexus:
        calibrate_nexus_health()
        return

    if args.crops:
        save_crops()
        return

    import game_state
    reader = game_state.GameStateReader()
    snapshot = reader.snapshot()
    screen = lor_api.capture_screen_bgr()

    pool = read_mana_pool(screen=screen, window=snapshot.window, debug=args.debug)
    ours = read_nexus_health(snapshot, screen=screen, local=True, debug=args.debug)
    theirs = read_nexus_health(snapshot, screen=screen, local=False, debug=args.debug)

    print(f"\n{pool}")
    print(f"PV nexus allié   : {'?' if ours is None else ours}")
    print(f"PV nexus adverse : {'?' if theirs is None else theirs}")


if __name__ == "__main__":
    main()
