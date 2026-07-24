import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict

import cv2
import numpy as np
import pyautogui
import requests

BASE_URL = "http://127.0.0.1:21337"
CARD_SETS_PATH = Path("LoR-Bot/card_sets")
CHIFFRES_PATH = Path("chiffres")

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

    def __init__(self, card_sets_path=CARD_SETS_PATH, chiffres_path=CHIFFRES_PATH):
        self.base_url = BASE_URL
        self.cards_db = self._load_cards(card_sets_path)
        self.digit_templates = self._load_digit_templates(chiffres_path)

    def _load_cards(self, folder: Path) -> dict:
        db = {}
        for path in folder.glob("*.json"):
            with open(path, encoding="utf8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for card in data:
                        db[card["cardCode"]] = card
        return db

    def _load_digit_templates(self, folder: Path) -> Dict[str, np.ndarray]:
        templates = {}
        for path in folder.glob("*.png"):
            digit = path.stem
            if not digit.isdigit():
                continue
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            if img.shape[2] == 4:
                alpha = img[:, :, 3]
                gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
                gray[alpha == 0] = 255
            else:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            templates[digit] = gray
        return templates

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

    def _read_number_from_crop(self, crop: np.ndarray) -> Optional[int]:
        if not self.digit_templates or crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
        if np.mean(bw) < 128:
            bw = cv2.bitwise_not(bw)

        h, w = bw.shape
        detections = []

        for digit, tmpl in self.digit_templates.items():
            th, tw = tmpl.shape
            scale = h / th
            if scale <= 0:
                continue
            new_tw = int(tw * scale)
            if new_tw <= 0 or new_tw > w:
                continue
            resized = cv2.resize(tmpl, (new_tw, h), interpolation=cv2.INTER_LINEAR)
            _, resized_bw = cv2.threshold(resized, 128, 255, cv2.THRESH_BINARY)
            if np.mean(resized_bw) < 128:
                resized_bw = cv2.bitwise_not(resized_bw)
            res = cv2.matchTemplate(bw, resized_bw, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val >= 0.3:
                detections.append((max_loc[0], digit, max_val))

        if not detections:
            return None

        detections.sort(key=lambda d: d[0])
        digits = []
        for x, digit, score in detections:
            if any(abs(x - ux) < 15 for ux, _ in digits):
                continue
            digits.append((x, digit))

        if not digits:
            return None

        try:
            return int("".join(d[1] for d in digits))
        except ValueError:
            return None

    def _get_stat_crop(self, screen: np.ndarray, rect: dict, rel: tuple) -> Optional[np.ndarray]:
        x, y, w, h = rect["TopLeftX"], rect["TopLeftY"], rect["Width"], rect["Height"]
        rx, ry, rw, rh = rel
        cx = int(x + w * rx)
        cy = int(y + h * ry)
        cw = int(w * rw)
        ch = int(h * rh)
        return screen[cy:cy + ch, cx:cx + cw]

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

            if card_type == "Unit":
                atk_crop = self._get_stat_crop(screen, rect, ATTACK_REL)
                hp_crop = self._get_stat_crop(screen, rect, HEALTH_REL)
                attack_read = self._read_number_from_crop(atk_crop)
                health_read = self._read_number_from_crop(hp_crop)

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
                zone=zones.get(rect["CardID"], "unknown"),
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
