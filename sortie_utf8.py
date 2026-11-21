#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sortie_utf8.py

Écrire en UTF-8 quoi qu'il arrive — TUBE OU PAS.

POURQUOI CE MODULE EXISTE (10/11/2026). La parade a été écrite trois
fois : `check.py._sortie_en_utf8` (05-08/11), puis `replay.py.
sortie_en_utf8` (10/11), et il en manquait une troisième. Trois copies
de la même vingtaine de lignes, c'est l'invariant que le projet répète
partout — « deux implémentations du même test finissent toujours par
diverger » — appliqué à un correctif au lieu d'une décision. La
quatrième copie n'a pas été écrite : elle est ici.

LE DÉFAUT, MESURÉ. La console Windows écrit en UTF-8 depuis Python 3.6,
mais dès que la sortie part dans un FICHIER ou un TUBE, Python retombe
sur l'encodage local — cp1252 sur ce PC — et meurt sur le premier
caractère qui n'y est pas. Reproduit le 10/11/2026 :

    PYTHONIOENCODING=cp1252 python -c "print('… ≤ …')" > rapport.txt
        -> code 1, UnicodeEncodeError '\u2264'

Le « ≤ » vient d'UNE ligne, « deck : N cartes, ≤ M à piocher »
(`GameSnapshot.summary()`, game_state.py:1504), et elle traverse tout
ce qui affiche un instantané : `game_state.py monitor`, `inspect`, et
les lignes « [état] » que `CombatLoop._describe_stuck` verse dans le
rapport d'un combat.

`sys.stderr`, lui, ne meurt jamais : son gestionnaire d'erreurs est
`backslashreplace` par défaut. C'est pour ça que le `logging` du projet
survit exactement là où un `print` tombe — et donc pourquoi le défaut
est resté invisible si longtemps.

AUCUN DE CES RÉGLAGES N'A LE DROIT D'ÉCHOUER BRUYAMMENT : si le flux
n'est pas un `TextIOWrapper` (banc d'essai, flux remplacé par une
doublure de test), on le laisse tel quel plutôt que de faire tomber
l'outil de diagnostic qu'on était venu lire.
"""

from __future__ import annotations

import io
import sys

# LES EMBALLAGES MIS DE CÔTÉ PAR LE REPLI, gardés référencés.
#
# Le piège a été relevé en relecture le 08/11/2026 : réemballer un
# tampon binaire sans garder l'ancien `TextIOWrapper` référencé laisse
# son `__del__` FERMER le tampon qu'on vient de reprendre. Deux
# emballages vivent donc sur le même tampon, et celui qui le ferme en
# dernier ne peut plus tronquer une queue qui n'existe pas — c'est
# `line_buffering=True` qui le garantit.
_FLUX_REMPLACES: list = []


def appliquer() -> None:
    """Reconfigure `sys.stdout` ET `sys.stderr` en UTF-8. Ne lève jamais."""
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
        try:
            _FLUX_REMPLACES.append(flux)
            setattr(sys, nom, io.TextIOWrapper(
                tampon, encoding="utf-8", errors="replace",
                line_buffering=True))
        except Exception:       # noqa: BLE001 — mieux vaut du cp1252 qu'un arrêt
            pass
