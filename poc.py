import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np
import pyautogui
import requests

from detect_chiffres import ocr_number

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_URL = "http://127.0.0.1:21337"
CARD_SETS_PATH = Path("LoR-Bot/card_sets")

DEBUG_DIR = Path("debug_cards")

ATTACK_REL = (0.05, 0.05, 0.25, 0.25)
HEALTH_REL = (0.70, 0.05, 0.25, 0.25)


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

    def __init__(self, card_sets_path=CARD_SETS_PATH):
        self.base_url = BASE_URL
        self.cards_db = self._load_cards(card_sets_path)

    def _load_cards(self, folder: Path) -> dict:
        db = {}
        for path in folder.glob("*.json"):
            with open(path, encoding="utf8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for card in data:
                        db[card["cardCode"]] = card
        return db

    def get(self, endpoint: str):
        r = requests.get(f"{self.base_url}/{endpoint}", timeout=2)
        r.raise_for_status()
        return r.json()

    def get_positional_rectangles(self):
        return self.get("positional-rectangles")

    def capture_screen(self):
        return cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)

    def _detect_zones(self, rectangles):
        local_nexus_y = None
        enemy_nexus_y = None

        for rect in rectangles:
            if rect["CardCode"] == "face":
                if rect["LocalPlayer"]:
                    local_nexus_y = rect["TopLeftY"]
                else:
                    enemy_nexus_y = rect["TopLeftY"]

        if local_nexus_y is None or enemy_nexus_y is None:
            return {}

        mid_y = (local_nexus_y + enemy_nexus_y) / 2

        zones = {}
        for rect in rectangles:
            if rect["CardCode"] == "face":
                continue

            code = rect["CardCode"]
            if code not in self.cards_db:
                continue

            y = rect["TopLeftY"]
            h = rect["Height"]
            local = rect["LocalPlayer"]

            if local:
                if y < mid_y:
                    zone = "hand" if h >= 200 else "board"
                else:
                    zone = "board"
            else:
                if y > mid_y:
                    zone = "enemy_hand" if h >= 200 else "enemy_board"
                else:
                    zone = "enemy_board"

            zones[rect["CardID"]] = zone

        return zones

    def _get_stat_crop(self, screen: np.ndarray, rect: dict, rel: tuple) -> Optional[np.ndarray]:
        x, y, w, h = rect["TopLeftX"], rect["TopLeftY"], rect["Width"], rect["Height"]
        # L'API positional-rectangles donne Y depuis le BAS de l'écran
        # (voir _save_debug_card, qui fait déjà cette conversion) : il
        # faut la même inversion ici, sinon on découpe au mauvais
        # endroit de l'écran et la case est vide -> aucun chiffre ne
        # peut jamais matcher.
        y = screen.shape[0] - y
        rx, ry, rw, rh = rel
        cx = int(x + w + rx)
        cy = int(y + h + ry)
        cw = int(w + rw)
        ch = int(h + rh)
        crop = screen[cy:cy + ch, cx:cx + cw]
        if crop.size == 0:
            logging.warning(f"Crop vide pour {rect.get('CardCode')} (cx={cx}, cy={cy}, cw={cw}, ch={ch})")
            return None
        return crop

    def _save_debug_card(self, screen: np.ndarray, rect: dict):
        x, y, w, h = rect["TopLeftX"], rect["TopLeftY"], rect["Width"], rect["Height"]
        y = screen.shape[0] - y
        card = screen[y:y + h, x:x + w]
        if card.size == 0:
            return
        DEBUG_DIR.mkdir(exist_ok=True)
        path = DEBUG_DIR / f"{rect['CardCode']}.png"
        cv2.imwrite(str(path), card)

    def get_cards(self, zones: Optional[dict] = None, screen: Optional[np.ndarray] = None) -> List[Card]:
        if screen is None:
            screen = self.capture_screen()
        data = self.get_positional_rectangles()
        rectangles = data.get("Rectangles", [])

        if zones is None:
            zones = self._detect_zones(rectangles)

        result = []
        for rect in rectangles:
            code = rect["CardCode"]
            if code == "face":
                continue
            if code not in self.cards_db:
                continue

            info = self.cards_db[code]
            card_type = info.get("type", "")

            attack_read = None
            health_read = None
            zone = zones.get(rect["CardID"], "unknown")

            if card_type == "Unit" and zone == "board":
                hauteurScreen = 159
                largeurScreen = 126
                atk_x, atk_y, atk_w, atk_h = 17, 8, 39, 26
                hp_x, hp_y, hp_w, hp_h = 74, 8, 36, 26

                atk_crop = self._get_stat_crop(screen, rect, (atk_x-largeurScreen, atk_y-hauteurScreen, atk_w-largeurScreen, atk_h-hauteurScreen))
                hp_crop = self._get_stat_crop(screen, rect, (hp_x-largeurScreen, hp_y-hauteurScreen, hp_w-largeurScreen, hp_h-hauteurScreen))
                attack_read = ocr_number(atk_crop, name=f"{code}_atk", debug=False)
                health_read = ocr_number(hp_crop, name=f"{code}_hp", debug=False)

            self._save_debug_card(screen, rect)

            card = Card(
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
            result.append(card)

        return sorted(result, key=lambda c: (c.zone, c.x))

    def my_hand(self):
        return [c for c in self.get_cards() if c.zone == "hand"]

    def my_board(self):
        return [c for c in self.get_cards() if c.zone == "board"]

    def enemy_hand(self):
        return [c for c in self.get_cards() if c.zone == "enemy_hand"]

    def enemy_board(self):
        return [c for c in self.get_cards() if c.zone == "enemy_board"]

    def cards_in_play(self):
        return self.my_board() + self.enemy_board()


if __name__ == "__main__":
    lor = LoRClient()

    print("========== TOUTES LES CARTES ==========")
    for card in lor.get_cards():
        print(card)

    print()
    print("========== MA MAIN ==========")
    for card in lor.my_hand():
        print(card)

    print()
    print("========== MON PLATEAU ==========")
    for card in lor.my_board():
        print(card)

    print()
    print("========== MAIN ADVERSE ==========")
    for card in lor.enemy_hand():
        print(card)

    print()
    print("========== PLATEAU ADVERSE ==========")
    for card in lor.enemy_board():
        print(card)

    print()
    print("========== CARTES EN JEU ==========")
    for card in lor.cards_in_play():
        print(card)