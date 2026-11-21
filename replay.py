#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
replay.py

Enregistrer un combat tel que le bot l'a VU, puis le rejouer sans le jeu.

    python combat.py --record                 # enregistre dans traces/<horodatage>/
    python challenges.py --record             # idem, toute la session
    python game_state.py monitor --record     # idem, sans jouer

    python replay.py list traces/combat_20260905_110116      # une ligne par lecture d'état
    python replay.py show traces/combat_20260905_110116 42   # l'état complet de la lecture 42
    python replay.py plan traces/combat_20260905_110116 42   # ce que `actions.py plan` déciderait
    python replay.py combat traces/combat_20260905_110116 42 # une itération de la boucle, à blanc
    python replay.py monitor traces/combat_20260905_110116   # rejoue toute la trace

--------------------------------------------------------------------
POURQUOI
--------------------------------------------------------------------
Jusqu'au 05/09/2026, la seule façon de comprendre une décision du bot
était de lancer une partie, de la perdre, et de relire le log. Chaque
question (« pourquoi n'a-t-il pas bloqué là ? ») coûtait un combat
entier, et la réponse arrivait sans l'état qui l'avait produite.

Tout ce que le bot sait du jeu passe par CINQ fonctions de `lor_api` :
l'API positionnelle, la capture d'écran, la fenêtre, le résultat et la
decklist. Les enregistrer suffit à pouvoir rejouer, hors ligne, TOUTE la
chaîne de décision — lecture d'état, OCR, plan de pose, d'attaque, de
blocage — sur exactement ce que le bot avait devant lui. Les tests hors
ligne raisonnent sur des plateaux inventés ; une trace est un plateau
réel.

--------------------------------------------------------------------
FORMAT D'UNE TRACE
--------------------------------------------------------------------
Un dossier, avec `events.jsonl` (une ligne par appel, ajoutée au fil de
l'eau : un Ctrl+C ne perd rien) et des captures PNG. Chaque appel à
`get_positional_rectangles` ouvre une LECTURE (« frame ») ; les captures,
fenêtres, résultats et decklists qui suivent s'y rattachent.

    {"k": "api",    "t": 12.31, "data": {...}}          ou {"k": "api", "error": "..."}
    {"k": "screen", "t": 12.35, "file": "000042.png"}   (dédoublonné : même image, même fichier)
    {"k": "window", "t": 12.33, "rect": [0, 0, 1920, 1080]}
    {"k": "result", "t": 12.32, "data": {...}}
    {"k": "deck",   "t": 12.32, "data": {...}}

Une capture PNG 1920x1080 pèse 1 à 2 Mo : un combat de cinq minutes fait
quelques centaines de Mo. Le dossier `traces/` est dans `.gitignore`.

--------------------------------------------------------------------
CE QUE LE REJEU NE FAIT PAS
--------------------------------------------------------------------
Il ne rejoue pas les GESTES : le jeu n'est pas là pour y répondre. Les
commandes de rejeu sont donc toutes « à blanc » (`dry_run`), et une trace
montre ce que le bot a vu et ce qu'il aurait décidé — pas ce qu'il
aurait fait bouger. Sans easyocr (VM Linux, machine sans `.venv`), la
lecture des chiffres se rabat sur la forme seule (`digits.py`, mode
tolérant) : les valeurs douteuses peuvent différer de la partie réelle.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import time
import types
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)


# Les emballages que `sortie_en_utf8` a mis de côté. Les garder
# référencés ICI empêche le ramasse-miettes de fermer le tampon sous nos
# pieds ; cf. le commentaire du repli, plus bas.
_FLUX_REMPLACES: list = []


def sortie_en_utf8() -> None:
    """
    Écrire en UTF-8 quoi qu'il arrive — TUBE OU PAS.

    MÊME PARADE QUE `check.py._sortie_en_utf8` (05-08/11/2026), appliquée
    ici parce que `replay.py` est l'outil du projet qu'on REDIRIGE le
    plus : une trace se relit dans un fichier, pas dans une console.
    Mesuré le 09/11/2026 sur `traces/combat_20261104_200516`, avec
    `PYTHONIOENCODING=cp1252` et stdout dans un fichier :

        replay.py list                → code 0
        replay.py show <trace> 40     → code 1, UnicodeEncodeError '≤'
        replay.py monitor <trace>     → code 1, UnicodeEncodeError '≤'

    Le caractère vient d'UNE ligne, « deck : N cartes, ≤ M à piocher »
    (`GameSnapshot.summary()`), et elle traverse TROIS impressions d'ici :
    `cmd_show`, `cmd_monitor`, et le « --- déroulé --- » de `cmd_combat`
    — où elle arrive par les lignes « [état] » que
    `CombatLoop._describe_stuck` verse dans `report.log` (mesuré : 4
    lignes de journal, 1 hors cp1252, celle du deck).

    La console Windows écrit en UTF-8 depuis Python 3.6, mais dès que la
    sortie part dans un FICHIER ou un TUBE, Python retombe sur l'encodage
    local — cp1252 sur ce PC. `sys.stderr`, lui, ne meurt jamais : son
    gestionnaire d'erreurs est `backslashreplace` par défaut, et c'est
    pour ça que le `logging` du projet survit là où un `print` tombe.

    Aucun de ces réglages n'a le droit d'échouer bruyamment : si le flux
    n'est pas un `TextIOWrapper` (banc d'essai, flux remplacé), on le
    laisse tel quel plutôt que de faire tomber l'outil de diagnostic.
    """
    for nom in ("stdout", "stderr"):
        flux = getattr(sys, nom, None)
        if flux is None:
            continue
        try:
            flux.reconfigure(encoding="utf-8", errors="replace",
                             line_buffering=True)
            continue
        except (AttributeError, ValueError, OSError):
            pass
        # Repli : on réemballe le tampon binaire.
        tampon = getattr(flux, "buffer", None)
        if tampon is None:
            continue
        # ON GARDE L'ANCIEN FLUX EN VIE, ET CE N'EST PAS DE LA PRUDENCE
        # DÉCORATIVE. Dès qu'on remplace `sys.stdout`, plus personne ne
        # référence l'ancien emballage : il est collecté, et le `__del__`
        # d'un `TextIOWrapper` FERME le tampon qu'on vient justement de
        # réemballer. Le nouvel emballage écrit alors dans un fichier
        # fermé — « ValueError: I/O operation on closed file. », levée au
        # premier `print`, donc à mille lieues de sa cause. Sans cette
        # liste, le repli censé éviter la chute la GARANTIT, en silence.
        try:
            neuf = io.TextIOWrapper(
                tampon, encoding="utf-8", errors="replace",
                line_buffering=True)
        except (AttributeError, ValueError, OSError):
            continue
        _FLUX_REMPLACES.append(flux)
        setattr(sys, nom, neuf)


def ensure_headless() -> None:
    """
    Rend le projet importable SANS souris ni écran (VM Linux, CI).

    `lor_api` importe pyautogui, qui exige un affichage. Le rejeu n'en a
    aucun besoin : un module factice suffit, exactement comme dans les
    suites de tests. Ne fait rien si pyautogui est disponible.
    """
    try:
        import pyautogui  # noqa: F401
        return
    except Exception:       # noqa: BLE001 — ImportError, ou KeyError DISPLAY
        pass
    stub = types.ModuleType("pyautogui")
    stub.FAILSAFE = True
    stub.PAUSE = 0
    stub.FailSafeException = type("FailSafeException", (Exception,), {})
    stub.size = lambda: (1920, 1080)
    for name in ("moveTo", "click", "mouseDown", "mouseUp", "dragTo", "screenshot",
                 "rightClick", "position", "press", "keyDown", "keyUp"):
        setattr(stub, name, lambda *a, **k: None)
    sys.modules["pyautogui"] = stub


ensure_headless()

import cv2          # noqa: E402
import numpy as np  # noqa: E402

import lor_api      # noqa: E402
from lor_api import ApiUnavailable, Window  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent
TRACES_DIR = PROJECT_ROOT / "traces"
EVENTS_FILE = "events.jsonl"

# Les cinq portes vers le monde extérieur, et rien d'autre.
PATCHED = ("get_positional_rectangles", "capture_screen_bgr", "get_window",
           "get_game_result", "get_static_decklist", "find_game_window")


def default_trace_dir(program: str = "trace") -> Path:
    return TRACES_DIR / f"{program}_{time.strftime('%Y%m%d_%H%M%S')}"


# ============================================================
# ENREGISTREMENT
# ============================================================

class Recorder:
    """
    Enveloppe les fonctions de `lor_api` : chaque appel est exécuté
    normalement ET consigné. Le bot ne voit aucune différence.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.directory / EVENTS_FILE, "a", encoding="utf8")
        self._start = time.time()
        self._frames = 0
        self._screens = 0
        self._last_hash: Optional[str] = None
        self._last_file: Optional[str] = None
        self._originals = {name: getattr(lor_api, name) for name in PATCHED}
        self._installed = False

    # --- écriture ---------------------------------------------------------
    def _emit(self, kind: str, **fields) -> None:
        event = {"k": kind, "t": round(time.time() - self._start, 3)}
        event.update(fields)
        try:
            self._handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._handle.flush()
        except OSError as exc:      # l'enregistrement ne doit jamais casser le bot
            LOGGER.warning("Trace non écrite : %s", exc)

    # --- enveloppes -------------------------------------------------------
    def _api(self):
        try:
            data = self._originals["get_positional_rectangles"]()
        except ApiUnavailable as exc:
            self._frames += 1
            self._emit("api", error=str(exc))
            raise
        self._frames += 1
        self._emit("api", data=data)
        return data

    def _screen(self):
        image = self._originals["capture_screen_bgr"]()
        try:
            digest = hashlib.md5(np.ascontiguousarray(image).tobytes()).hexdigest()
            if digest != self._last_hash:
                self._screens += 1
                name = f"{self._screens:06d}.png"
                cv2.imwrite(str(self.directory / name), image,
                            [cv2.IMWRITE_PNG_COMPRESSION, 3])
                self._last_hash, self._last_file = digest, name
            self._emit("screen", file=self._last_file)
        except Exception as exc:    # noqa: BLE001
            LOGGER.warning("Capture non enregistrée : %s", exc)
        return image

    def _window(self, api_data=None):
        window = self._originals["get_window"](api_data)
        self._emit("window", rect=[window.x, window.y, window.width, window.height])
        return window

    def _result(self):
        data = self._originals["get_game_result"]()
        self._emit("result", data=data)
        return data

    def _deck(self):
        data = self._originals["get_static_decklist"]()
        self._emit("deck", data=data)
        return data

    # --- cycle de vie -----------------------------------------------------
    def install(self) -> "Recorder":
        if self._installed:
            return self
        lor_api.get_positional_rectangles = self._api
        lor_api.capture_screen_bgr = self._screen
        lor_api.get_window = self._window
        lor_api.get_game_result = self._result
        lor_api.get_static_decklist = self._deck
        self._installed = True
        LOGGER.info("Enregistrement de la trace dans %s", self.directory)
        return self

    def close(self) -> None:
        if self._installed:
            for name, function in self._originals.items():
                setattr(lor_api, name, function)
            self._installed = False
        try:
            self._handle.close()
        except OSError:
            pass
        LOGGER.info("Trace fermée : %d lecture(s), %d capture(s) dans %s",
                    self._frames, self._screens, self.directory)


_ACTIVE: Optional[Recorder] = None


def start_recording(directory=None, program: str = "trace") -> Path:
    """
    Branche l'enregistrement pour le reste du processus. Idempotent.
    Rend le dossier de la trace. Le débranchement est automatique à la
    sortie (atexit), donc un Ctrl+C laisse une trace complète.
    """
    global _ACTIVE
    if _ACTIVE is not None:
        return _ACTIVE.directory
    import atexit
    directory = Path(directory) if directory else default_trace_dir(program)
    _ACTIVE = Recorder(directory).install()
    atexit.register(stop_recording)
    return directory


def stop_recording() -> None:
    global _ACTIVE
    if _ACTIVE is not None:
        _ACTIVE.close()
        _ACTIVE = None


# ============================================================
# REJEU
# ============================================================

class Frame:
    """Une lecture d'état et tout ce qui a été vu jusqu'à la suivante."""

    def __init__(self, index: int, t: float, api=None, error: Optional[str] = None):
        self.index = index
        self.t = t
        self.api = api
        self.error = error
        self.screens: list = []
        self.window: Optional[list] = None
        self.result = None
        self.deck = None

    @property
    def game_state(self) -> str:
        return (self.api or {}).get("GameState", "?") if self.error is None else "NO_API"


def load_frames(directory) -> list:
    """Regroupe `events.jsonl` en lectures. Les lignes abîmées sont ignorées."""
    path = Path(directory) / EVENTS_FILE
    if not path.exists():
        raise FileNotFoundError(f"Pas de {EVENTS_FILE} dans {directory}")
    frames: list = []
    with open(path, encoding="utf8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("k")
            if kind == "api":
                frames.append(Frame(len(frames), event.get("t", 0.0),
                                    api=event.get("data"), error=event.get("error")))
                continue
            if not frames:
                continue        # une capture avant toute lecture : orpheline
            frame = frames[-1]
            if kind == "screen" and event.get("file"):
                frame.screens.append(event["file"])
            elif kind == "window":
                frame.window = event.get("rect")
            elif kind == "result":
                frame.result = event.get("data")
            elif kind == "deck":
                frame.deck = event.get("data")
    return frames


class Replayer:
    """
    Sert une trace à la place du jeu.

    `fixed=True` : chaque appel voit la MÊME lecture (pour examiner une
    décision) ; `fixed=False` : chaque appel à l'API avance d'une lecture
    (pour rejouer la trace comme `monitor`). Les valeurs absentes d'une
    lecture (capture, résultat, deck) sont reprises de la dernière connue,
    exactement comme le jeu les aurait laissées.
    """

    def __init__(self, directory, fixed: bool = True):
        self.directory = Path(directory)
        self.frames = load_frames(self.directory)
        if not self.frames:
            raise ValueError(f"Trace vide : {self.directory}")
        self.fixed = fixed
        self.index = 0
        self._screen_cursor = 0
        self._cache: dict = {}
        self._originals = {name: getattr(lor_api, name) for name in PATCHED}
        self._installed = False

    # --- position ---------------------------------------------------------
    @property
    def frame(self) -> Frame:
        return self.frames[min(self.index, len(self.frames) - 1)]

    @property
    def exhausted(self) -> bool:
        return self.index >= len(self.frames)

    def seek(self, index: int) -> "Replayer":
        if not 0 <= index < len(self.frames):
            raise IndexError(f"lecture {index} hors trace (0..{len(self.frames) - 1})")
        self.index = index
        self._screen_cursor = 0
        return self

    def _latest(self, attribute: str):
        """La dernière valeur connue de `attribute`, à cette lecture ou avant."""
        for frame in reversed(self.frames[: self.index + 1]):
            value = getattr(frame, attribute)
            if value:
                return value
        return None

    # --- services rejoués -------------------------------------------------
    def _api(self):
        frame = self.frame
        if not self.fixed:
            self.index += 1
            self._screen_cursor = 0
        if frame.error is not None:
            raise ApiUnavailable(f"(rejeu) {frame.error}")
        return frame.api

    def _screen(self):
        frame = self.frame if self.fixed else self.frames[max(0, self.index - 1)]
        files = frame.screens
        if not files:
            # Pas de capture à cette lecture (menus, mulligan) : la
            # dernière connue, comme l'écran l'aurait encore affichée.
            latest = self._latest("screens")
            files = [latest[-1]] if latest else []
        if not files:
            raise RuntimeError(f"Aucune capture dans la trace jusqu'à la lecture {frame.index}")
        name = files[min(self._screen_cursor, len(files) - 1)]
        self._screen_cursor += 1
        if name not in self._cache:
            image = cv2.imread(str(self.directory / name), cv2.IMREAD_COLOR)
            if image is None:
                raise RuntimeError(f"Capture illisible : {self.directory / name}")
            self._cache = {name: image}     # une seule image en mémoire à la fois
        return self._cache[name]

    def _window(self, api_data=None):
        rect = self._latest("window")
        if rect:
            return Window(*rect)
        screen = ((api_data or self.frame.api or {}).get("Screen") or {})
        return Window(0, 0, int(screen.get("ScreenWidth", 1920)),
                      int(screen.get("ScreenHeight", 1080)))

    def _result(self):
        return self._latest("result") or {}

    def _deck(self):
        return self._latest("deck") or {"CardsInDeck": None}

    # --- cycle de vie -----------------------------------------------------
    def install(self) -> "Replayer":
        if not self._installed:
            lor_api.get_positional_rectangles = self._api
            lor_api.capture_screen_bgr = self._screen
            lor_api.get_window = self._window
            lor_api.get_game_result = self._result
            lor_api.get_static_decklist = self._deck
            lor_api.find_game_window = lambda title=None: None
            self._installed = True
        return self

    def uninstall(self) -> None:
        if self._installed:
            for name, function in self._originals.items():
                setattr(lor_api, name, function)
            self._installed = False

    def __enter__(self):
        return self.install()

    def __exit__(self, *exc):
        self.uninstall()


# ============================================================
# CLI
# ============================================================

def _reader():
    """Un lecteur d'état qui ne repose que sur lor_api (déjà rejoué)."""
    from game_state import GameStateReader
    return GameStateReader()


def cmd_list(directory, only_phase: Optional[str]) -> None:
    replayer = Replayer(directory, fixed=True)
    print(f"{len(replayer.frames)} lecture(s) dans {directory}\n")
    header = f"{'n°':>5} {'t':>7}  {'API':<10} {'phase':<14} {'orbe':<5} {'jeton':<6} résumé"
    print(header)
    print("-" * len(header))
    with replayer:
        reader = _reader()
        last_phase = None
        for frame in replayer.frames:
            replayer.seek(frame.index)
            try:
                snap = reader.snapshot()
                phase = snap.phase.name
                orb = "" if snap.turn_orb_active is None else ("bleue" if snap.turn_orb_active else "grise")
                token = "" if snap.attack_token is None else ("nous" if snap.attack_token else "lui")
                resume = ", ".join(f"{z}={len(c)}" for z, c in snap.zones.items() if c)
            except Exception as exc:    # noqa: BLE001 — une lecture abîmée ne cache pas les autres
                phase, orb, token, resume = "ERREUR", "", "", str(exc)[:60]
            marker = ">>" if phase != last_phase else "  "
            if only_phase is None or phase == only_phase or marker == ">>":
                print(f"{marker}{frame.index:>4} {frame.t:>7.1f}  {frame.game_state:<10} "
                      f"{phase:<14} {orb:<5} {token:<6} {resume}")
            last_phase = phase


def cmd_show(directory, index: int) -> None:
    import mana
    replayer = Replayer(directory, fixed=True).seek(index)
    frame = replayer.frame
    with replayer:
        snap = _reader().snapshot()
        print(f"Lecture {index} à t={frame.t:.1f}s — API {frame.game_state}, "
              f"{len(frame.screens)} capture(s) : {', '.join(frame.screens) or 'aucune'}\n")
        print(snap.summary())
        if snap.phase.in_game and frame.screens:
            try:
                pool = mana.read_mana_pool(window=snap.window)
                print(f"\nMana lu : {pool}")
            except Exception as exc:    # noqa: BLE001
                print(f"\nMana non lu : {exc}")
        print("\nCartes :")
        for card in snap.cards():
            print(f"    {str(card):<48} zone {card.zone:<13} ratio {card.ratio:.3f}")


def cmd_plan(directory, index: int, allow_spells: bool) -> None:
    import actions
    replayer = Replayer(directory, fixed=True).seek(index)
    with replayer:
        actions.cmd_plan(allow_spells)


def cmd_combat(directory, index: int, allow_spells: bool, allow_chump: bool) -> None:
    from combat import CombatLoop
    replayer = Replayer(directory, fixed=True).seek(index)
    with replayer:
        report = CombatLoop(allow_spells=allow_spells, allow_chump=allow_chump,
                            dry_run=True, poll=0.0).run()
    print("\n--- déroulé ---")
    for entry in report.log:
        print(f"  {entry}")
    print(f"\n{report.summary()}")


def cmd_monitor(directory, start: int) -> None:
    replayer = Replayer(directory, fixed=False).seek(start)
    with replayer:
        reader = _reader()
        last = None
        while not replayer.exhausted:
            index = replayer.index
            t = replayer.frame.t
            snap = reader.snapshot()
            marker = ">>" if snap.phase is not last else "  "
            print(f"{marker} {index:>4} {t:>7.1f}s {snap.summary()}")
            last = snap.phase


def main() -> None:
    sortie_en_utf8()        # AVANT TOUT LE RESTE : les `cmd_*` importent
                            # game_state, actions et combat au fil de
                            # l'eau, et un avertissement d'import doit
                            # déjà sortir en UTF-8 (cf. sortie_en_utf8).
    parser = argparse.ArgumentParser(description="Enregistrer et rejouer ce que le bot a vu.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="une ligne par lecture d'état")
    p.add_argument("trace")
    p.add_argument("--phase", default=None, help="n'afficher que cette phase (et les changements)")

    p = sub.add_parser("show", help="l'état complet d'une lecture")
    p.add_argument("trace")
    p.add_argument("index", type=int)

    p = sub.add_parser("plan", help="ce que `actions.py plan` déciderait sur cette lecture")
    p.add_argument("trace")
    p.add_argument("index", type=int)
    p.add_argument("--spells", action="store_true")

    p = sub.add_parser("combat", help="une itération de la boucle de combat, à blanc")
    p.add_argument("trace")
    p.add_argument("index", type=int)
    p.add_argument("--spells", action="store_true")
    p.add_argument("--chump", action="store_true")

    p = sub.add_parser("monitor", help="rejoue toute la trace comme `game_state.py monitor`")
    p.add_argument("trace")
    p.add_argument("--from", dest="start", type=int, default=0)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "list":
        cmd_list(args.trace, args.phase)
    elif args.command == "show":
        cmd_show(args.trace, args.index)
    elif args.command == "plan":
        cmd_plan(args.trace, args.index, args.spells)
    elif args.command == "combat":
        cmd_combat(args.trace, args.index, args.spells, args.chump)
    elif args.command == "monitor":
        cmd_monitor(args.trace, args.start)


if __name__ == "__main__":
    main()
