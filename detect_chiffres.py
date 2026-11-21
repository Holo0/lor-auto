import cv2
import numpy as np
from pathlib import Path

import digits

DEBUG_DIR = Path("debug_ocr")

# LE MODÈLE N'EST PLUS CHARGÉ À L'IMPORT. Jusqu'au 05/09/2026, importer ce
# module (fait par game_state avant chaque lecture de stats) créait un
# easyocr.Reader : torch en mémoire, plusieurs secondes, et un
# ModuleNotFoundError fatal hors de `.venv`. Le lecteur est maintenant
# créé au premier besoin réel, et partagé avec mana.py (`get_reader`).
reader = None

# Borne des stats lues sur un badge : au-delà, c'est du bruit.
STAT_MAX = 99


def get_reader():
    """L'instance easyocr, créée au premier appel. Lève ImportError sans easyocr."""
    global reader
    if reader is None:
        import easyocr
        reader = easyocr.Reader(['en'], gpu=True)
    return reader


def is_mostly_white(crop):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # Blanc = saturation faible + valeur élevée
    mask_white = cv2.inRange(
        hsv,
        np.array([0, 0, 180]),     # H=0-180, S=0-30, V=180-255
        np.array([180, 30, 255])
    )

    white_pixels = np.count_nonzero(mask_white)
    total_pixels = crop.shape[0] * crop.shape[1]

    # Si plus de 40% du crop est blanc → ce n'est PAS une stat LoR
    return white_pixels / total_pixels > 0.40


def crop_has_stat_color(crop):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # Vert / jaune (attaque)
    mask_atk = cv2.inRange(hsv,
                           np.array([20, 80, 80]),
                           np.array([90, 255, 255]))

    # Rouge (PV)
    mask_hp1 = cv2.inRange(hsv,
                           np.array([0, 80, 80]),
                           np.array([10, 255, 255]))
    mask_hp2 = cv2.inRange(hsv,
                           np.array([170, 80, 80]),
                           np.array([180, 255, 255]))
    mask_hp = mask_hp1 | mask_hp2

    colored_pixels = np.count_nonzero(mask_atk | mask_hp)
    total_pixels = crop.shape[0] * crop.shape[1]

    # Si moins de 3% de pixels colorés → ce n'est PAS une stat
    return colored_pixels / total_pixels > 0.03


def ocr_number(crop, name="unknown", debug=False, maximum=STAT_MAX):
    """
    Le nombre lu sur ce badge, ou None.

    `maximum` BORNE TOUTES LES LECTURES, celle d'easyocr comprise. Le
    04/11/2026, `game_state._cached_ocr` croyait borner les stats à 30 :
    il passait bien `maximum=30` à `digits.read_number`, mais le secours
    `ocr_number` rebornait à STAT_MAX (99) en interne, et sa valeur
    n'était jamais revérifiée. Une Prancing Sea Spirits 3/3 a été lue
    **3/73**, jugée increvable, et envoyée attaquer sur cette base. Deux
    bornes pour la même grandeur, c'est l'absence de borne.
    """
    if crop is None or crop.size == 0:
        return None

    # 1. Bloquer les chiffres blancs
    if is_mostly_white(crop):
        if debug:
            print(f"{name}: ignoré (crop blanc détecté)")
        return None

    # 2. Exiger des pixels colorés (rouge/vert/jaune)
    if not crop_has_stat_color(crop):
        if debug:
            print(f"{name}: ignoré (pas de couleur de stat)")
        return None

    # L'export de debug doit rester ENTIÈREMENT sous le drapeau `debug` :
    # dans la version précédente l'écriture du PNG était en dehors du
    # `if`, ce qui provoquait un NameError sur debug_dir dès que la
    # fonction était appelée avec debug=False (c'est-à-dire depuis poc.py).
    if debug:
        DEBUG_DIR.mkdir(exist_ok=True)
        cv2.imwrite(str(DEBUG_DIR / f"{name}_crop.png"), crop)

    # LA FORME D'ABORD (digits.py, ~1 ms) : c'est la même police que le
    # mana, déjà lue ainsi. easyocr ne sert que si la forme doute.
    fast = digits.read_number(crop, maximum)
    if fast is not None:
        digits.USAGE["forme"] += 1
        if debug:
            print(f"{name}: {fast} (forme, sans OCR)")
        return fast

    try:
        ocr = get_reader()
    except Exception:       # noqa: BLE001 — easyocr absent ou indisponible
        value = digits.read_number(crop, maximum, loose=True)
        digits.USAGE["tolerant" if value is not None else "echec"] += 1
        return value

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    gray = cv2.resize(gray, None, fx=4, fy=4,
                      interpolation=cv2.INTER_CUBIC)

    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    _, processed = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    if debug:
        cv2.imwrite(str(DEBUG_DIR / f"{name}_processed.png"), processed)

    result = ocr.readtext(
        processed,
        detail=0,
        allowlist='0123456789'
    )

    # Pas de variable locale nommée `digits` : elle masquerait le module
    # (UnboundLocalError du 04/09/2026 dans mana.read_digits).
    found = ''.join(c for c in ''.join(result) if c.isdigit()) if result else ''
    if found and int(found) <= maximum:
        digits.USAGE["easyocr"] += 1
        return int(found)
    value = digits.read_number(crop, maximum, loose=True)
    digits.USAGE["tolerant" if value is not None else "echec"] += 1
    return value


def main():
    screenshot_path = Path("debug_cards/06MT008.png")

    if not screenshot_path.exists():
        print(f"Fichier introuvable : {screenshot_path}")
        return

    image = cv2.imread(str(screenshot_path))
    if image is None:
        print("Impossible de charger l'image.")
        return

    # === ZONES EXACTES CALIBRÉES ===
    atk_x, atk_y, atk_w, atk_h = 17, 10, 39, 26
    hp_x, hp_y, hp_w, hp_h = 74, 10, 36, 26

    atk_crop = image[atk_y:atk_y+atk_h, atk_x:atk_x+atk_w]
    hp_crop = image[hp_y:hp_y+hp_h, hp_x:hp_x+hp_w]

    atk = ocr_number(atk_crop, name="attack", debug=True)
    hp = ocr_number(hp_crop, name="health", debug=True)

    print("\n=== Résultats OCR LoR ===")
    print(f"Attack : {atk}")
    print(f"Health : {hp}")

    print("\nChiffres détectés :", [v for v in (atk, hp) if v is not None])


if __name__ == "__main__":
    main()
