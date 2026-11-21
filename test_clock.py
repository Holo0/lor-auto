#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_clock.py

Horloge virtuelle pour les suites hors ligne.

Les tests remplacent la souris, l'écran et le jeu — mais PAS le temps.
`actions.py`, `game_state.py` et `combat.py` appellent `time.sleep` pour
laisser une animation se terminer, et calculent leurs échéances sur
`time.time()`. Hors ligne, ces attentes ne protègent plus rien : il n'y a
aucune animation à attendre. Elles coûtaient une trentaine de secondes à
`test_actions.py` et une quinzaine à `test_combat.py`, pendant lesquelles
`check.py` — qui capture la sortie — semblait figé.

Ici, dormir AVANCE une horloge fictive au lieu d'attendre. Les délais
gardent leur ordre et leurs durées relatives : une échéance finit toujours
par échoir, une boucle de poll converge, `wait_for_change` rend la main au
même tour de boucle qu'en vrai. Seul le temps réel n'avance plus.

Ce n'est valable que parce que toute boucle bornée par `time.time()` dans
ce projet appelle `time.sleep` dans son corps. Une boucle d'attente active
qui ne dormirait pas ne se terminerait jamais sous cette horloge — si tu
en ajoutes une, dors-y, ne serait-ce que 0.
"""

from __future__ import annotations

import time as _time

_REAL_SLEEP = _time.sleep
_REAL_TIME = _time.time
_REAL_MONOTONIC = _time.monotonic
_REAL_PERF_COUNTER = _time.perf_counter

_offset = 0.0
_installed = False


def _advance(seconds) -> None:
    """Remplace `time.sleep` : avance l'horloge sans attendre."""
    global _offset
    try:
        _offset += max(0.0, float(seconds))
    except (TypeError, ValueError):
        pass


def install_virtual_clock() -> None:
    """Bascule le module `time` sur l'horloge fictive. Idempotent."""
    global _installed
    if _installed:
        return
    _installed = True

    _time.sleep = _advance
    _time.time = lambda: _REAL_TIME() + _offset
    _time.monotonic = lambda: _REAL_MONOTONIC() + _offset
    _time.perf_counter = lambda: _REAL_PERF_COUNTER() + _offset


def uninstall_virtual_clock() -> None:
    """Rend le vrai temps, pour un test qui aurait besoin de mesurer."""
    global _installed
    _installed = False
    _time.sleep = _REAL_SLEEP
    _time.time = _REAL_TIME
    _time.monotonic = _REAL_MONOTONIC
    _time.perf_counter = _REAL_PERF_COUNTER


def virtual_elapsed() -> float:
    """Temps total « dormi » depuis l'installation, en secondes fictives."""
    return _offset
