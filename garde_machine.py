#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
garde_machine.py

L'ESPION QUI DIT SI UNE SUITE HORS LIGNE A TOUCHÉ LA MACHINE.

    python garde_machine.py test_actions.py      # lance la suite sous surveillance

C'est le lanceur que `check.py` place devant CHAQUE suite : plus personne
n'a à penser à faire le geste.

--------------------------------------------------------------------
POURQUOI CE FICHIER EXISTE
--------------------------------------------------------------------
Règle dure du projet : **une suite hors ligne ne doit JAMAIS toucher la
souris, l'écran ni la fenêtre du jeu.** Elle a été violée QUATRE fois, et
chaque fois découverte par hasard, après coup, alors qu'elle pilotait la
vraie machine d'Ewan pendant un `check.py --offline` :

    05/11/2026  lor_battle.park_mouse ................ 29 déplacements
    05/11/2026  navigate.champions.choisir_champion .. 10 captures,
                                                       15 coups de molette,
                                                       et un test vert PAR ACCIDENT
    06/11/2026  lor_battle._reward_proves_victory .... 40 captures,
                                                       la suite passée de 5 s à 15 s
    08/11/2026  champions.revenir_en_haut ............ 220 coups de molette,
                                                       10 vols de focus

À chaque fois le diagnostic a été le même — « un espion sur pyautogui dit
en une commande si une suite touche la machine » — et à chaque fois il est
resté un geste MANUEL qu'il fallait penser à faire. CLAUDE.md l'inscrit
d'ailleurs comme une DETTE le 08/11 : « cet espion gagnerait à entrer dans
`check.py` plutôt que de rester un outil qu'on pense à lancer. » C'est
cette dette-là.

--------------------------------------------------------------------
COMPTER, PAS BLOQUER (et pourquoi)
--------------------------------------------------------------------
Deux façons de tenir la règle, et elles ne coûtent pas la même chose :

    BLOQUER — lever une exception au premier geste. Rien ne bouge, mais
    la suite CHANGE de comportement sous surveillance : une suite verte
    devient rouge, et son verdict ne dit plus ce qu'elle teste mais ce
    que le garde a interrompu. On perdrait la seule chose qui compte
    quand on cherche une régression : un échec qui désigne la logique.
    Pire, on remplacerait un faux vert (le défaut d'origine) par un faux
    rouge, et l'histoire du projet dit que les deux se croient.

    COMPTER — laisser passer, et le DIRE. La suite se comporte
    exactement comme aujourd'hui, son verdict reste honnête, et le garde
    rend un second verdict, à part. C'est `check.py` qui en fait un échec
    bloquant : la suite dit la logique, le garde dit la machine.

On compte donc. Un décompte qu'on peut ignorer ne vaudrait rien, alors il
PARLE FORT : il crie au PREMIER geste, avec la pile d'appel — un
compteur dit « quelque chose a bougé », une pile NOMME le coupable, et
c'est la différence entre une enquête de dix minutes et une de deux
heures. `check.py` le répète ensuite à côté du [OK] de chaque suite.

Pour l'enquête, et seulement pour elle, `GARDE_MACHINE=bloquer` fait
lever `GesteInterdit` à la place : rien ne part vers la machine et la
pile complète remonte dans son contexte. Ce n'est PAS le mode par défaut,
pour la raison ci-dessus.

--------------------------------------------------------------------
COMMENT IL S'ACCROCHE
--------------------------------------------------------------------
Les mouchards sont posés sur les ATTRIBUTS DE MODULE (`pyautogui.click`,
`gestures.focus_game_window`), parce que tout le projet appelle ainsi —
`import pyautogui` puis `pyautogui.moveTo(...)`, jamais
`from pyautogui import moveTo`. Et ils sont posés À L'INSTANT où le
module finit de s'importer, par un chercheur dans `sys.meta_path` :

    - une suite qui n'importe pas pyautogui ne le charge pas à cause de
      nous (le garde ne doit RIEN coûter — `--offline` reste hors ligne
      et rapide) ;
    - aucun module ne peut faire `from pyautogui import click` avant
      nous, puisque nous passons avant la fin de son import.

Les bouchons que les suites posent elles-mêmes (test_actions remplace
`pyautogui.click` le temps d'un test) écrasent le mouchard puis le
restaurent : ils ne comptent pas, et c'est correct — un bouchon ne touche
pas la machine.
"""

from __future__ import annotations

import atexit
import collections
import importlib.util
import os
import runpy
import sys
import traceback
from pathlib import Path

# ============================================================
# CE QUI COMPTE COMME « TOUCHER LA MACHINE »
# ============================================================
# Les gestes de pyautogui qui BOUGENT quelque chose ou PHOTOGRAPHIENT.
# `size()` et `position()` n'y sont pas : ils interrogent, ils ne
# touchent rien — et le code les appelle légitimement hors ligne.
#
# Côté `gestures`, les deux fonctions de fenêtre ajoutées le 08/11/2026 :
# `focus_game_window` VOLE le premier plan (c'est elle qui a fait les dix
# vols de focus de `revenir_en_haut`), et `game_window_handle` interroge
# la liste des fenêtres du système — elle ne casse rien, mais elle est le
# premier pas de l'autre, et la voir dans une suite hors ligne veut dire
# que le chemin du vrai jeu a été emprunté.
GESTES = {
    "pyautogui": (
        "moveTo", "moveRel", "move", "dragTo", "dragRel", "drag",
        "click", "doubleClick", "tripleClick", "rightClick", "middleClick",
        "mouseDown", "mouseUp",
        "scroll", "hscroll", "vscroll",
        "screenshot",
        "press", "keyDown", "keyUp", "hotkey", "typewrite", "write",
    ),
    "gestures": ("focus_game_window", "game_window_handle"),
}

# Préfixe des lignes de verdict. `check.py` les relit dans le tube ; il
# doit rester unique et stable.
PREFIXE = "[GARDE-MACHINE]"
PROPRE = "rien touché"
SALE = "TOUCHÉ"

# Profondeur de la pile criée au premier geste : assez pour remonter du
# geste jusqu'au test, pas assez pour noyer la sortie.
PROFONDEUR_PILE = 6

_MOI = Path(__file__).name


class GesteInterdit(RuntimeError):
    """Levée à la place du geste quand `GARDE_MACHINE=bloquer`."""


_compteur: "collections.Counter[str]" = collections.Counter()
_cries = set()               # les gestes dont la pile a déjà été criée
_rapport_rendu = False

# LE FLUX QU'ON A MIS DE CÔTÉ EN S'INSTALLANT, et à qui l'on parle.
#
# Le garde s'adresse à `check.py` qui relit le TUBE, pas à la suite. Or
# un simple `print` écrit sur le `sys.stdout` DU MOMENT, et quatre suites
# du projet — test_actions, test_challenges, test_journal, test_spells —
# détournent le leur dans un `contextlib.redirect_stdout` pour relire ce
# qu'une fonction imprime. Mesuré le 09/11/2026 : un geste fait là-dedans
# voyait son cri ET SA PILE tomber dans leur tampon — c'est-à-dire la
# seule chose qui NOMME le coupable. Et une suite qui remplace son
# `sys.stdout` sans le rendre emportait carrément le verdict final, posé
# en `atexit` donc imprimé après elle : code de retour 0, pas une ligne
# du garde, un geste compté et jamais dit.
#
# Effet de bord voulu : une suite qui relit sa propre sortie capturée ne
# trouve plus de `[GARDE-MACHINE]` mélangé à ses assertions.
_SORTIE = None


def _bloquant() -> bool:
    return os.environ.get("GARDE_MACHINE", "").lower() == "bloquer"


def _ecrire(ligne: str) -> None:
    """
    Écrit une ligne de verdict sur le flux mis de côté, et sinon sur ce
    qui reste.

    LE GARDE N'A JAMAIS LE DROIT DE CASSER LA SUITE QU'IL SURVEILLE —
    c'est tout le principe « compter, pas bloquer ». Si le flux de côté
    est fermé (interpréteur en fin de vie, banc d'essai), on se rabat sur
    celui du moment puis sur stderr, qui arrive dans le même tube
    (`stderr=subprocess.STDOUT` côté `check.py`). Si rien ne marche, on
    se tait : un verdict perdu est un `sans verdict` dans `check.py`,
    une exception serait une suite rouge par la faute du garde.
    """
    for flux in (_SORTIE, sys.stdout, sys.stderr):
        if flux is None:
            continue
        try:
            print(ligne, file=flux, flush=True)
            return
        except (ValueError, OSError, AttributeError):
            continue


# ============================================================
# LE MOUCHARD
# ============================================================

def _pile(profondeur: int = PROFONDEUR_PILE) -> list:
    """
    Les derniers cadres d'appel, du plus proche du geste au plus lointain,
    SANS les cadres du garde lui-même — ils n'apprennent rien.
    """
    lignes = []
    for cadre in reversed(traceback.extract_stack()):
        # Ni les cadres du garde, ni la plomberie du lanceur (`runpy`) :
        # on veut le chemin du TEST jusqu'au geste, pas le nôtre.
        if Path(cadre.filename).name == _MOI or "runpy" in cadre.filename:
            continue
        lignes.append(f"{Path(cadre.filename).name}:{cadre.lineno}  {cadre.name}()")
        if len(lignes) >= profondeur:
            break
    return lignes


def _noter(nom: str) -> None:
    """
    Compte le geste, et CRIE la première fois qu'on voit CHACUN d'eux.

    Une pile par geste DIFFÉRENT, pas une seule pour toute la suite : le
    08/11/2026 `test_challenges` touchait la machine par deux chemins
    sans rapport — une capture d'écran dans `prendre_panneau_ouvert` et
    des déplacements de souris ailleurs. Une seule pile n'aurait nommé
    que le premier, et la deuxième fuite serait repartie pour un tour.
    Le nombre de cris est borné par le nombre de gestes surveillés.
    """
    _compteur[nom] += 1
    if nom in _cries:
        return
    _cries.add(nom)
    rang = "PREMIER GESTE" if len(_cries) == 1 else "AUTRE GESTE"
    _ecrire(f"{PREFIXE} {rang} SUR LA MACHINE : {nom}()")
    for ligne in _pile():
        _ecrire(f"{PREFIXE}     {ligne}")


def _mouchard(nom: str, fonction):
    """Enveloppe `fonction` : elle compte, puis fait (ou refuse) le geste."""

    def espion(*args, **kwargs):
        _noter(nom)
        if _bloquant():
            raise GesteInterdit(
                f"{nom}() refusé : une suite hors ligne ne touche pas la machine."
            )
        return fonction(*args, **kwargs)

    espion.__name__ = getattr(fonction, "__name__", "espion")
    espion.__doc__ = getattr(fonction, "__doc__", None)
    espion._garde_machine = True        # pour ne jamais empiler deux mouchards
    espion._garde_original = fonction
    return espion


def poser_les_mouchards(module, nom_module: str) -> int:
    """Remplace les gestes surveillés de `module` par leurs mouchards."""
    poses = 0
    for geste in GESTES.get(nom_module, ()):
        fonction = getattr(module, geste, None)
        if not callable(fonction) or getattr(fonction, "_garde_machine", False):
            continue
        setattr(module, geste, _mouchard(f"{nom_module}.{geste}", fonction))
        poses += 1
    return poses


# ============================================================
# L'ACCROCHE À L'IMPORT
# ============================================================

class _ChargeurEspion:
    """
    Le chargeur d'origine, plus un geste : poser les mouchards dès que le
    module a fini de s'exécuter — donc avant que quiconque puisse en tirer
    une fonction par `from ... import ...`.
    """

    _interne = None

    def __init__(self, interne, nom: str):
        self._interne = interne
        self._nom = nom

    def create_module(self, spec):
        return self._interne.create_module(spec)

    def exec_module(self, module):
        self._interne.exec_module(module)
        poser_les_mouchards(module, self._nom)

    def __getattr__(self, attribut):        # get_filename, is_package, etc.
        return getattr(self._interne, attribut)


class _Guetteur:
    """
    Chercheur placé en tête de `sys.meta_path`. Il ne charge rien lui-même :
    il laisse les chercheurs normaux trouver le module, puis habille leur
    chargeur. Coût pour tous les autres imports : une appartenance à un
    dictionnaire de deux clés.
    """

    def __init__(self):
        self._en_cours = set()

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in GESTES or fullname in self._en_cours:
            return None
        self._en_cours.add(fullname)           # sinon on se rappelle soi-même
        try:
            spec = importlib.util.find_spec(fullname)
        except Exception:                      # noqa: BLE001 — jamais au garde de casser un import
            return None
        finally:
            self._en_cours.discard(fullname)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _ChargeurEspion(spec.loader, fullname)
        return spec


def installer() -> None:
    """Pose le guet. Idempotent."""
    global _SORTIE
    if any(isinstance(chercheur, _Guetteur) for chercheur in sys.meta_path):
        return
    # LE TUBE, PRIS AVANT QUE LA SUITE N'EXISTE : c'est à `check.py`
    # qu'on parle, pas au tampon que la suite se posera devant la bouche.
    _SORTIE = sys.stdout
    sys.meta_path.insert(0, _Guetteur())
    # Déjà importés avant nous (cas du lanceur interactif) : on les habille
    # tout de suite.
    for nom in GESTES:
        module = sys.modules.get(nom)
        if module is not None:
            poser_les_mouchards(module, nom)
    atexit.register(rapporter)


# ============================================================
# LE VERDICT
# ============================================================

def resume() -> str:
    """La ligne de verdict, telle que `check.py` la relit."""
    if not _compteur:
        return f"{PREFIXE} {PROPRE}"
    total = sum(_compteur.values())
    detail = ", ".join(f"{nom}×{n}" for nom, n in _compteur.most_common())
    return f"{PREFIXE} {SALE} {total} fois : {detail}"


def rapporter() -> None:
    """
    Écrit le verdict une seule fois, à la fin de la suite.

    Posé en `atexit`, donc rendu aussi quand la suite sort sur un
    `sys.exit()` ou sur une exception. Une suite TUÉE (échéance de
    `check.py`) n'en rend aucun : le cri du premier geste, lui, est déjà
    parti — c'est pour ça qu'il part tout de suite.
    """
    global _rapport_rendu
    if _rapport_rendu:
        return
    _rapport_rendu = True
    _ecrire(resume())


# ============================================================
# LANCEUR
# ============================================================

def main(argv) -> int:
    if len(argv) < 2:
        print(f"usage: python {_MOI} <suite.py> [arguments...]", file=sys.stderr)
        return 2

    cible = Path(argv[1]).resolve()
    if not cible.exists():
        print(f"{_MOI}: suite introuvable : {cible}", file=sys.stderr)
        return 2

    installer()
    # La suite doit se croire lancée seule : même `sys.argv`, même
    # `__name__`, même `__file__` qu'avec `python <suite.py>`.
    sys.argv = [str(cible)] + list(argv[2:])
    runpy.run_path(str(cible), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
