import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

import lor_api
from detect_chiffres import ocr_number

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEBUG_DIR = "debug_cards"

# ============================================================
# ZONES DE STATS SUR UNE CARTE
# ============================================================
# Décalages calibrés à la main sur une carte de banc de 126x159 px
# (résolution 1920x1080). On les convertit en RATIOS de la taille de la
# carte : à 126x159 les crops sont identiques au pixel près, mais la
# calibration continue de fonctionner si la carte est rendue plus grande
# ou plus petite (autre résolution, carte survolée).

REF_CARD_SIZE = (126, 159)
ATTACK_BOX = (17, 8, 39, 26)    # (x, y, largeur, hauteur) dans la carte
HEALTH_BOX = (74, 8, 36, 26)


def _to_ratio(box, ref=REF_CARD_SIZE):
    x, y, width, height = box
    ref_w, ref_h = ref
    return (x / ref_w, y / ref_h, width / ref_w, height / ref_h)


ATTACK_REL = _to_ratio(ATTACK_BOX)
HEALTH_REL = _to_ratio(HEALTH_BOX)


@dataclass
class Card:
    id: int
    code: str
    name: str
    cost: int
    attack: int
    health: int
    attack_read: Optional[int]
    health_read: Optional[int]
    x: int
    y: int
    width: int
    height: int
    local_player: bool
    zone: str = ""

    def __str__(self):
        atk = self.attack_read if self.attack_read is not None else self.attack
        hp = self.health_read if self.health_read is not None else self.health
        return f"{self.name} ({self.cost}) {atk}/{hp} [{self.zone}]"


class LoRClient:
    """
    Lecture des cartes en jeu : identité et coût via l'API locale,
    stats réelles (buffs, dégâts subis) via OCR sur la carte.

    NOTE — la détection de PHASE (à qui le tour, jeton d'attaque, faut-il
    bloquer) vit dans game_state.py, pas ici. Ce module répond seulement
    à « quelles cartes, où, avec quelles stats ».
    """

    def __init__(self, card_sets_path=lor_api.CARD_SETS_PATH, save_debug_cards=False):
        self.cards_db = lor_api.load_card_db(card_sets_path)
        self.save_debug_cards = save_debug_cards
        self.window = lor_api.get_window()

    # --- accès API -----------------------------------------------------
    def get_positional_rectangles(self):
        return lor_api.get_positional_rectangles()

    def capture_screen(self) -> np.ndarray:
        return lor_api.capture_screen_bgr()

    # --- zones ---------------------------------------------------------
    def _detect_zones(self, rectangles):
        """
        Classement main / plateau à partir de la position des deux nexus.

        À TERME : remplacé par game_state.classify_zone(), qui distingue
        en plus la rangée d'attaque et la pile de sorts. On garde cette
        version tant que les bandes de game_state.py n'ont pas été
        validées avec `python game_state.py inspect`.
        """
        local_nexus_y = None
        enemy_nexus_y = None

        for rect in rectangles:
            if rect["CardCode"] == lor_api.NEXUS_CARD_CODE:
                if rect["LocalPlayer"]:
                    local_nexus_y = rect["TopLeftY"]
                else:
                    enemy_nexus_y = rect["TopLeftY"]

        if local_nexus_y is None or enemy_nexus_y is None:
            return {}

        mid_y = (local_nexus_y + enemy_nexus_y) / 2

        zones = {}
        for rect in rectangles:
            code = rect["CardCode"]
            if code == lor_api.NEXUS_CARD_CODE or code not in self.cards_db:
                continue

            y = rect["TopLeftY"]
            h = rect["Height"]

            if rect["LocalPlayer"]:
                zone = "hand" if (y < mid_y and h >= 200) else "board"
            else:
                zone = "enemy_hand" if (y > mid_y and h >= 200) else "enemy_board"

            zones[rect["CardID"]] = zone

        return zones

    # --- crops de stats ------------------------------------------------
    def _get_stat_crop(self, screen: np.ndarray, rect: dict, rel: tuple) -> Optional[np.ndarray]:
        """
        Découpe une case de stat (attaque ou PV) sur une carte.

        La conversion Y de l'API -> Y écran est faite par
        lor_api.rect_to_screen_box : l'API mesure depuis le BAS de la
        fenêtre, OpenCV depuis le HAUT. Oublier cette inversion donne un
        crop vide, et aucun chiffre ne peut alors jamais être lu.
        """
        left, top, right, bottom = lor_api.rect_to_screen_box(rect, self.window)
        width, height = right - left, bottom - top
        rx, ry, rw, rh = rel

        box = (
            left + rx * width,
            top + ry * height,
            left + (rx + rw) * width,
            top + (ry + rh) * height,
        )
        crop = lor_api.crop_box(screen, box)
        if crop is None:
            logging.warning("Crop vide pour %s (box=%s)", rect.get("CardCode"), box)
        return crop

    def _save_debug_card(self, screen: np.ndarray, rect: dict):
        """Exporte la carte entière en PNG, pour recalibrer ATTACK_BOX/HEALTH_BOX."""
        import cv2
        from pathlib import Path

        crop = lor_api.crop_box(screen, lor_api.rect_to_screen_box(rect, self.window))
        if crop is None:
            return
        folder = Path(DEBUG_DIR)
        folder.mkdir(exist_ok=True)
        cv2.imwrite(str(folder / f"{rect['CardCode']}.png"), crop)

    # --- lecture des cartes --------------------------------------------
    def get_cards(self, zones: Optional[dict] = None, screen: Optional[np.ndarray] = None) -> List[Card]:
        self.window = lor_api.get_window()
        if screen is None:
            screen = self.capture_screen()

        data = self.get_positional_rectangles()
        rectangles = data.get("Rectangles") or []

        if zones is None:
            zones = self._detect_zones(rectangles)

        result = []
        for rect in rectangles:
            code = rect["CardCode"]
            if code == lor_api.NEXUS_CARD_CODE or code not in self.cards_db:
                continue

            info = self.cards_db[code]
            zone = zones.get(rect["CardID"], "unknown")

            attack_read = None
            health_read = None
            # L'OCR n'a de sens que sur le banc : en main les stats
            # affichées sont les stats de base, déjà connues via l'API.
            if info.get("type") == "Unit" and zone == "board":
                attack_read = ocr_number(
                    self._get_stat_crop(screen, rect, ATTACK_REL), name=f"{code}_atk"
                )
                health_read = ocr_number(
                    self._get_stat_crop(screen, rect, HEALTH_REL), name=f"{code}_hp"
                )

            if self.save_debug_cards:
                self._save_debug_card(screen, rect)

            result.append(
                Card(
                    id=rect["CardID"],
                    code=code,
                    name=info.get("name", code),
                    cost=info.get("cost", 0),
                    attack=info.get("attack", 0),
                    health=info.get("health", 0),
                    attack_read=attack_read,
                    health_read=health_read,
                    x=rect["TopLeftX"],
                    y=rect["TopLeftY"],
                    width=rect["Width"],
                    height=rect["Height"],
                    local_player=rect["LocalPlayer"],
                    zone=zone,
                )
            )

        return sorted(result, key=lambda c: (c.zone, c.x))

    # --- raccourcis ----------------------------------------------------
    def my_hand(self, cards=None):
        return [c for c in (cards or self.get_cards()) if c.zone == "hand"]

    def my_board(self, cards=None):
        return [c for c in (cards or self.get_cards()) if c.zone == "board"]

    def enemy_hand(self, cards=None):
        return [c for c in (cards or self.get_cards()) if c.zone == "enemy_hand"]

    def enemy_board(self, cards=None):
        return [c for c in (cards or self.get_cards()) if c.zone == "enemy_board"]

    def cards_in_play(self, cards=None):
        cards = cards or self.get_cards()
        return self.my_board(cards) + self.enemy_board(cards)


if __name__ == "__main__":
    lor = LoRClient(save_debug_cards=True)

    # Une seule lecture, réutilisée pour toutes les vues : sinon chaque
    # appel refaisait une capture d'écran + un appel API + tout l'OCR.
    cards = lor.get_cards()

    print("========== TOUTES LES CARTES ==========")
    for card in cards:
        print(card)

    for title, subset in (
        ("MA MAIN", lor.my_hand(cards)),
        ("MON PLATEAU", lor.my_board(cards)),
        ("MAIN ADVERSE", lor.enemy_hand(cards)),
        ("PLATEAU ADVERSE", lor.enemy_board(cards)),
        ("CARTES EN JEU", lor.cards_in_play(cards)),
    ):
        print(f"\n========== {title} ==========")
        for card in subset:
            print(card)
