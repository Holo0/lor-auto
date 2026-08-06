import cv2
import numpy as np
import easyocr
from pathlib import Path

reader = easyocr.Reader(['en'], gpu=True)

DEBUG_DIR = Path("debug_ocr")


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


def ocr_number(crop, name="unknown", debug=False):
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

    result = reader.readtext(
        processed,
        detail=0,
        allowlist='0123456789'
    )

    if not result:
        return None

    digits = ''.join([c for c in result if c.isdigit()])
    return int(digits) if digits else None


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
