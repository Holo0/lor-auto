#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_web.py

Page de monitoring EN DIRECT, lisible par un navigateur — et donc par
Claude in Chrome — pendant que le bot joue.

    python monitor_web.py                        # http://127.0.0.1:8765/
    python monitor_web.py --port 8765 --interval 2 --sans-ocr

--------------------------------------------------------------------
POURQUOI
--------------------------------------------------------------------
Claude in Chrome ne voit que des onglets : la fenêtre du jeu lui est
invisible. Ce serveur publie, sur le PC, ce que le bot voit lui-même :
la capture de la fenêtre du jeu avec les rectangles de l'API dessinés
dessus, `GameSnapshot.summary()`, les cartes par zone, la fin du log du
lancement en cours et la dernière ligne du journal. Un lecteur externe
lit tout ça EN TEXTE (pas en pixels), et peut demander, à la demande,
ce que `actions.py plan` ou `actions.py why` diraient maintenant.

Le jeu doit rester sur l'écran principal, découvert (c'est déjà la
condition pour que le bot joue) ; le navigateur va sur l'autre écran.

--------------------------------------------------------------------
CE QUE ÇA NE FAIT PAS
--------------------------------------------------------------------
Aucun geste : ni souris, ni clavier. Le serveur ne fait que LIRE (API,
écran, fichiers). Il tourne dans SON processus, à côté de
`challenges.py`, et ajoute un appel d'API toutes les `--interval`
secondes — Riot demande ≤ 1/s ; avec l'intervalle par défaut (2 s) le
bot et le moniteur réunis restent raisonnables. Il n'enregistre rien :
pour revoir une partie après coup, c'est `--record` et `replay.py`.

--------------------------------------------------------------------
ENDPOINTS
--------------------------------------------------------------------
    GET /              la page (se rafraîchit toutes les `interval` s)
    GET /state.json    phase, summary, cartes par zone, log, journal
    GET /screen.jpg    capture de la fenêtre du jeu, rectangles de l'API
                       dessinés (vert = à nous, rouge = adverse, bleu =
                       nexus) ; `?brut=1` pour l'image nue
    GET /plan.txt      `actions.py plan` à blanc, calculé À LA DEMANDE
                       (lent au premier appel : OCR) ; `?spells=1`
    GET /why.txt       `actions.py why` à blanc (pourquoi chaque carte
                       n'est pas jouée)

Écoute sur 127.0.0.1 seulement.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

import lor_api
from game_state import ZONE_ORDER, GameSnapshot, GameStateReader

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
JOURNAL_PATH = ROOT / "journal.jsonl"

DEFAULT_PORT = 8765
DEFAULT_INTERVAL = 2.0     # secondes entre deux lectures
DEFAULT_WIDTH = 1280       # largeur max de l'image servie
LOG_TAIL_LINES = 80        # lignes de log affichées
JPEG_QUALITY = 80

COLOR_OURS = (0, 200, 0)       # BGR
COLOR_THEIRS = (0, 0, 230)
COLOR_NEXUS = (230, 160, 0)
COLOR_TEXT_BG = (0, 0, 0)


# ============================================================
# ÉTAT PARTAGÉ ENTRE LA BOUCLE DE LECTURE ET LE SERVEUR
# ============================================================

class Etat:
    """Dernière lecture, protégée par un verrou : la boucle écrit, les
    requêtes lisent."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.lecture = 0
        self.taken_at: Optional[float] = None
        self.phase = ""
        self.api_state = ""
        self.summary = ""
        self.zones: dict = {}
        self.fenetre: Optional[tuple] = None
        self.jpeg: Optional[bytes] = None
        self.jpeg_brut: Optional[bytes] = None
        self.erreur = ""


# ============================================================
# IMAGE
# ============================================================

def cadrer(screen: np.ndarray, window: lor_api.Window) -> np.ndarray:
    """La fenêtre du jeu seule, ou tout l'écran si elle n'est pas cadrable."""
    box = (window.x, window.y, window.x + window.width, window.y + window.height)
    crop = lor_api.crop_box(screen, box)
    return crop if crop is not None and crop.size else screen


def reduire(image: np.ndarray, max_width: int) -> np.ndarray:
    height, width = image.shape[:2]
    if width <= max_width:
        return image
    scale = max_width / width
    return cv2.resize(image, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)


def jpeg(image: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("encodage JPEG impossible")
    return data.tobytes()


def _texte(image: np.ndarray, text: str, origin: tuple, color: tuple, scale: float = 0.45) -> None:
    """Texte lisible sur n'importe quel fond : un bandeau noir dessous."""
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = origin
    cv2.rectangle(image, (x, y - h - base), (x + w + 2, y + base), COLOR_TEXT_BG, -1)
    cv2.putText(image, text, (x + 1, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def dessiner(image: np.ndarray, snapshot: GameSnapshot) -> np.ndarray:
    """Les rectangles de l'API par-dessus la capture : ce que le bot voit,
    tel qu'il le classe (nom, stats, zone)."""
    out = image.copy()
    ox, oy = snapshot.window.x, snapshot.window.y

    for box, color in (
        (snapshot.our_nexus_box, COLOR_NEXUS),
        (snapshot.enemy_nexus_box, COLOR_NEXUS),
    ):
        if box:
            left, top, right, bottom = (int(v) for v in box)
            cv2.rectangle(out, (left - ox, top - oy), (right - ox, bottom - oy), color, 2)

    for card in snapshot.cards():
        left, top, right, bottom = (int(v) for v in card.box)
        color = COLOR_OURS if card.local else COLOR_THEIRS
        cv2.rectangle(out, (left - ox, top - oy), (right - ox, bottom - oy), color, 2)
        label = card.name[:20]
        if card.type == "Unit":
            label += f" {card.attack}/{card.health}"
        _texte(out, label, (left - ox, max(12, top - oy - 4)), color)
        _texte(out, card.zone, (left - ox, min(out.shape[0] - 4, bottom - oy - 4)), color, 0.4)

    header = f"{time.strftime('%H:%M:%S')}  [{snapshot.phase.name}]  api={snapshot.api_state or '-'}"
    _texte(out, header, (8, 20), (255, 255, 255), 0.6)
    return out


# ============================================================
# FICHIERS : LOG DU LANCEMENT EN COURS, JOURNAL
# ============================================================

def dernier_log() -> Optional[Path]:
    """Le fichier de `logs/` le plus récemment modifié."""
    try:
        files = [p for p in LOG_DIR.glob("*.log") if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def queue_fichier(path: Path, lines: int = LOG_TAIL_LINES, max_bytes: int = 64_000) -> str:
    """Les dernières lignes, sans relire tout le fichier."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError as exc:
        return f"(log illisible : {exc})"
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])


def dernier_combat() -> dict:
    """La dernière ligne de `journal.jsonl`, résumée et brute."""
    try:
        with open(JOURNAL_PATH, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 64_000))
            lines = [l for l in handle.read().decode("utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return {"resume": "(pas de journal)", "brut": None}
    if not lines:
        return {"resume": "(journal vide)", "brut": None}
    try:
        entry = json.loads(lines[-1])
    except ValueError:
        return {"resume": "(dernière ligne illisible)", "brut": lines[-1]}
    ecartees = entry.get("ecartees") or []
    ecartees = sorted(ecartees, key=lambda e: -int(e.get("n") or 0))[:5]
    resume = (
        f"{entry.get('horodatage', '?')} — {entry.get('tours', '?')} tours, "
        f"{entry.get('attaques', '?')} attaques, {entry.get('blocages', '?')} blocages, "
        f"{entry.get('duree', '?')} s, gagné={entry.get('gagne')}, "
        f"arrêt={entry.get('arret') or '-'}, verdict={entry.get('verdict') or '-'}"
    )
    if entry.get("archetype"):
        resume += f", archétype={entry['archetype']}"
    if ecartees:
        resume += "\nécartées : " + " ; ".join(
            f"{e.get('carte')} ×{e.get('n')} ({e.get('motif')})" for e in ecartees
        )
    return {"resume": resume, "brut": entry}


# ============================================================
# BOUCLE DE LECTURE
# ============================================================

def boucle(etat: Etat, reader: GameStateReader, interval: float, max_width: int) -> None:
    while True:
        started = time.time()
        try:
            snapshot = reader.snapshot()
            screen = lor_api.capture_screen_bgr()
            image = cadrer(screen, snapshot.window)
            brut = jpeg(reduire(image, max_width))
            annote = jpeg(reduire(dessiner(image, snapshot), max_width))
            zones = {
                name: [str(c) + ("" if c.local else " [adv]") for c in snapshot.zones.get(name, ())]
                for name in ZONE_ORDER
                if snapshot.zones.get(name)
            }
            with etat.lock:
                etat.lecture += 1
                etat.taken_at = snapshot.taken_at
                etat.phase = snapshot.phase.name
                etat.api_state = snapshot.api_state
                etat.summary = snapshot.summary()
                etat.zones = zones
                etat.fenetre = (snapshot.window.x, snapshot.window.y,
                                snapshot.window.width, snapshot.window.height)
                etat.jpeg = annote
                etat.jpeg_brut = brut
                etat.erreur = ""
        except Exception as exc:  # la boucle ne doit jamais mourir
            LOGGER.exception("lecture impossible")
            with etat.lock:
                etat.erreur = f"{type(exc).__name__}: {exc}"
        time.sleep(max(0.2, interval - (time.time() - started)))


# ============================================================
# PLAN / WHY À LA DEMANDE
# ============================================================

_CALCUL = threading.Lock()


def calculer(commande: str, spells: bool) -> str:
    """`actions.py plan` ou `why`, à blanc, sortie capturée. Un seul à la
    fois : le second appel reçoit un message, pas une file d'attente."""
    if not _CALCUL.acquire(blocking=False):
        return "Un calcul est déjà en cours, réessaie dans quelques secondes."
    # Les décisions elles-mêmes (« [plan] jouer X : saisie -> dépôt ») passent
    # par `logging`, pas par `print` : on capture les deux dans le même texte,
    # sinon la page montre la main et le mana mais pas ce qu'il jouerait.
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    try:
        import actions  # lourd (templates, OCR paresseux) : chargé au premier appel seulement
        with contextlib.redirect_stdout(buffer):
            if commande == "plan":
                actions.cmd_plan(allow_spells=spells)
            else:
                actions.cmd_why(allow_spells=spells, read_screen_costs=True)
        return buffer.getvalue() or "(rien)"
    except Exception as exc:
        return f"Échec : {type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
    finally:
        logging.getLogger().removeHandler(handler)
        _CALCUL.release()


# ============================================================
# SERVEUR
# ============================================================

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>LoR bot — moniteur</title>
<style>
  body{margin:0;background:#111;color:#ddd;font:13px/1.45 Consolas,"Courier New",monospace}
  header{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding:8px 12px;background:#1c1c1c;position:sticky;top:0}
  header strong{color:#fff} #phase{color:#9ad;font-weight:bold} #erreur{color:#f66}
  main{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:12px;padding:12px}
  @media (max-width:1100px){main{grid-template-columns:1fr}}
  img{width:100%;height:auto;background:#000;display:block}
  h2{font-size:12px;margin:10px 0 4px;color:#9ad;text-transform:uppercase;letter-spacing:.04em}
  pre{white-space:pre-wrap;word-break:break-word;background:#181818;padding:8px;margin:0;max-height:38vh;overflow:auto}
  button{background:#2a3a4a;color:#fff;border:1px solid #456;padding:3px 10px;cursor:pointer;font:inherit}
  label{cursor:pointer}
</style></head>
<body>
<header>
  <strong>LoR bot — moniteur</strong>
  <span id="phase">…</span>
  <span id="heure"></span>
  <label><input type="checkbox" id="brut"> image nue</label>
  <label><input type="checkbox" id="spells"> avec les sorts</label>
  <button id="btnplan">Calculer le plan</button>
  <button id="btnwhy">Pourquoi pas jouées</button>
  <span id="erreur"></span>
</header>
<main>
  <section>
    <img id="ecran" alt="capture de la fenêtre du jeu, rectangles de l'API dessinés">
    <h2>Plan (à la demande)</h2>
    <pre id="plan">— cliquer « Calculer le plan » ou « Pourquoi pas jouées » —</pre>
  </section>
  <section>
    <h2>État du plateau (summary)</h2>
    <pre id="summary"></pre>
    <h2>Cartes par zone</h2>
    <pre id="zones"></pre>
    <h2>Log du lancement en cours — <span id="logname"></span></h2>
    <pre id="log"></pre>
    <h2>Dernier combat du journal</h2>
    <pre id="journal"></pre>
  </section>
</main>
<script>
const INTERVAL = __INTERVAL_MS__;
const $ = id => document.getElementById(id);
let derniereLecture = -1;
async function maj() {
  try {
    const r = await fetch('/state.json', {cache: 'no-store'});
    const s = await r.json();
    $('phase').textContent = s.phase ? '[' + s.phase + '] api=' + (s.api || '-') : '(pas encore de lecture)';
    $('heure').textContent = s.heure ? 'lecture ' + s.lecture + ' à ' + s.heure : '';
    $('erreur').textContent = s.erreur || '';
    $('summary').textContent = s.summary || '';
    $('zones').textContent = Object.entries(s.zones || {}).map(([z, cs]) => z + '\\n    ' + cs.join('\\n    ')).join('\\n') || '(aucune carte)';
    $('logname').textContent = s.log.fichier || '(aucun log)';
    $('log').textContent = s.log.queue || '';
    $('journal').textContent = s.journal.resume || '';
    if (s.lecture !== derniereLecture) {
      derniereLecture = s.lecture;
      $('ecran').src = '/screen.jpg?t=' + Date.now() + ($('brut').checked ? '&brut=1' : '');
    }
  } catch (e) {
    $('erreur').textContent = 'moniteur injoignable : ' + e;
  }
}
async function calcul(quoi) {
  $('plan').textContent = quoi + ' en cours… (le premier appel charge l\\'OCR, compter quelques secondes)';
  try {
    const r = await fetch('/' + quoi + '.txt?spells=' + ($('spells').checked ? 1 : 0), {cache: 'no-store'});
    $('plan').textContent = await r.text();
  } catch (e) {
    $('plan').textContent = 'échec : ' + e;
  }
}
$('btnplan').onclick = () => calcul('plan');
$('btnwhy').onclick = () => calcul('why');
$('brut').onchange = () => { derniereLecture = -1; maj(); };
setInterval(maj, INTERVAL);
maj();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    etat: Etat
    interval_ms: int = int(DEFAULT_INTERVAL * 1000)

    def log_message(self, fmt, *args):  # pas une ligne par requête dans la console
        LOGGER.debug("%s " + fmt, self.address_string(), *args)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _state(self) -> dict:
        etat = self.etat
        log_path = dernier_log()
        with etat.lock:
            state = {
                "lecture": etat.lecture,
                "heure": time.strftime("%H:%M:%S", time.localtime(etat.taken_at)) if etat.taken_at else None,
                "phase": etat.phase,
                "api": etat.api_state,
                "summary": etat.summary,
                "zones": etat.zones,
                "fenetre": etat.fenetre,
                "erreur": etat.erreur,
            }
        state["log"] = {
            "fichier": log_path.name if log_path else None,
            "queue": queue_fichier(log_path) if log_path else "",
        }
        state["journal"] = dernier_combat()
        return state

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            page = PAGE.replace("__INTERVAL_MS__", str(self.interval_ms))
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif url.path == "/state.json":
            body = json.dumps(self._state(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif url.path == "/screen.jpg":
            with self.etat.lock:
                data = self.etat.jpeg_brut if query.get("brut", ["0"])[0] == "1" else self.etat.jpeg
            if data is None:
                self._send(503, "text/plain; charset=utf-8", "pas encore de capture".encode("utf-8"))
            else:
                self._send(200, "image/jpeg", data)
        elif url.path in ("/plan.txt", "/why.txt"):
            spells = query.get("spells", ["0"])[0] == "1"
            text = calculer(url.path[1:-4], spells)
            self._send(200, "text/plain; charset=utf-8", text.encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"inconnu : / , /state.json , /screen.jpg , /plan.txt , /why.txt")


# ============================================================
# ENTRÉE
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Page web locale montrant en direct ce que le bot voit (aucun geste)."
    )
    parser.add_argument("--host", default="127.0.0.1", help="adresse d'écoute (laisser 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help="secondes entre deux lectures (API + capture)")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH,
                        help="largeur max de l'image servie, en pixels")
    parser.add_argument("--sans-ocr", action="store_true",
                        help="ne jamais charger easyocr pour /plan.txt et /why.txt (forme seule)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if args.sans_ocr:
        import mana
        mana.OCR_DISABLED = True

    reader = GameStateReader()
    etat = Etat()
    threading.Thread(
        target=boucle, args=(etat, reader, args.interval, args.width),
        name="lecture", daemon=True,
    ).start()

    Handler.etat = etat
    Handler.interval_ms = max(500, int(args.interval * 1000))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Moniteur sur http://{args.host}:{args.port}/ — Ctrl+C pour arrêter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()