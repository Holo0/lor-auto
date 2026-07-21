import cv2
import numpy as np
import time
import math
import logging
import os
import pyautogui

# ============================================================
# TEMPLATES
# ============================================================

ASSETS_DIR = "assets"
MATCH_THRESHOLD = 0.80

TEMPLATES = {
    "monthly_challenge": os.path.join(ASSETS_DIR, "monthly_challenge.png"),
    "active_encounter": os.path.join(ASSETS_DIR, "active_encounter.png"),

    "first_champion": os.path.join(ASSETS_DIR, "first_champion.png"),
    "use_attempt": os.path.join(ASSETS_DIR, "use_attempt.png"),
    "retry": os.path.join(ASSETS_DIR, "retry.png"),
    "after_combat": os.path.join(ASSETS_DIR, "after_combat.png"),

    "select_button": os.path.join(ASSETS_DIR, "select_button.png"),
    "quit_button": os.path.join(ASSETS_DIR, "quit_button.png"),
    "combat_button": os.path.join(ASSETS_DIR, "combat_button.png"),
    "continue_button": os.path.join(ASSETS_DIR, "continue_button.png"),
    "voyage_button": os.path.join(ASSETS_DIR, "voyage_button.png"),

    "normal_node": os.path.join(ASSETS_DIR, "normal_node.png"),
    "enemy_node": os.path.join(ASSETS_DIR, "enemy_node.png"),
    "secondary_enemy_node": os.path.join(ASSETS_DIR, "secondary_enemy_node.png"),

    # Défi hebdomadaire
    "support_champion": os.path.join(ASSETS_DIR, "support_champion_node.png"),
    "travel_button": os.path.join(ASSETS_DIR, "travel_button.png"),
    "final_boss": os.path.join(ASSETS_DIR, "final_boss.png"),
    "mid_boss": os.path.join(ASSETS_DIR, "mid_boss.png"),
}

# ============================================================
# TEMPLATE MATCHING
# ============================================================

def _capture_screen_bgr():
    screenshot = pyautogui.screenshot()
    screenshot_np = np.array(screenshot)
    return cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)


def find_template_on_screen(template_path, threshold=MATCH_THRESHOLD):
    """
    Recherche un template et retourne son centre (x, y).
    """
    if not os.path.exists(template_path):
        logging.error(f"Template manquant : {template_path}")
        return None

    template = cv2.imread(template_path)
    if template is None:
        logging.error(f"Impossible de charger le template : {template_path}")
        return None

    screen_bgr = _capture_screen_bgr()
    result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        h, w = template.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)

    return None