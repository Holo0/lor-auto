"""
Lecture de l'étourdissement à l'écran — sur les captures RÉELLES.

Les deux images de référence ont été prises le 14/11/2026 pendant une
vraie partie, à 0,7 s d'intervalle, avec Ewan confirmant à l'écran que
« l'ennemi le plus à gauche est stun ». Les sept unités de la scène sont
connues par l'API, donc le test porte sur un positif ET six négatifs,
dont le piège qui compte : un champion qui s'anime sans être étourdi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

import stun

CAPTURES = Path(__file__).parent / "captures_reference"
AVANT = CAPTURES / "stun_anim_a_20261114.png"
APRES = CAPTURES / "stun_anim_b_20261114.png"

FAILURES: list = []


def check(label, condition, detail=None):
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(label)
        print(f"  ÉCHEC {label}" + ("" if detail is None else f" {detail}"))


class _Carte:
    """Le minimum de BoardCard dont `stun` a besoin."""

    def __init__(self, nom, card_id, centre):
        self.name, self.card_id, self.center = nom, card_id, centre


# La scène, telle que l'API la rapportait au moment de la capture.
ENNEMIS = [
    ("House Spider", 301, (802, 180), True),    # <- celle qu'Ewan désigne
    ("Spiderling", 302, (959, 180), False),
    ("Imperial Demolitionist", 303, (1115, 180), False),
]
LES_NOTRES = [
    ("Swain", 201, (724, 900), False),          # champion ANIMÉ, pas étourdi
    ("Enraged Firespitter", 202, (880, 900), False),
    ("Legion Saboteur", 203, (1037, 900), False),
    ("Arachnoid Sentry", 204, (1194, 900), False),
]


def _images():
    return cv2.imread(str(AVANT)), cv2.imread(str(APRES))


def test_le_tourbillon_se_lit_sur_deux_captures():
    """
    UN POSITIF, SIX NÉGATIFS, SUR LA SCÈNE RÉELLE.

    C'est le seul test qui vaille ici : les seuils ont été posés sur ces
    images, donc les y vérifier ne prouverait rien de plus qu'une
    tautologie — sauf que les six négatifs, eux, n'ont pas servi à les
    poser, et que l'un d'eux (Swain) est précisément le cas qui fait
    tomber les deux pistes naïves.
    """
    print("\nLe tourbillon de l'étourdissement, sur la capture réelle")
    avant, apres = _images()
    if avant is None or apres is None:
        check("captures de référence présentes", False, (AVANT, APRES))
        return

    for nom, _, centre, attendu in ENNEMIS + LES_NOTRES:
        lu = stun.est_etourdie(avant, apres, centre)
        check(f"{nom:<24} étourdie={attendu}", lu is attendu,
              f"lu {lu} — {stun.mouvement(avant, apres, centre)}")


def test_la_teinte_et_le_delavage_ne_suffisaient_pas():
    """
    LES DEUX PISTES NAÏVES, GARDÉES COMME CONTRE-ÉPREUVE.

    Si un jour quelqu'un veut « simplifier » en regardant la couleur,
    ces chiffres sont là pour dire pourquoi c'est faux : Swain, à NOUS
    et parfaitement sain, est plus violet que la moitié du plateau.
    """
    print("\nPourquoi ni la teinte ni le délavage ne suffisent")
    import numpy as np
    avant, _ = _images()
    if avant is None:
        check("capture de référence présente", False, AVANT)
        return
    hsv = cv2.cvtColor(avant, cv2.COLOR_BGR2HSV)

    def part_violette(centre):
        cx, cy = centre
        sub = hsv[cy - 55:cy + 55, cx - 55:cx + 55]
        h, s, v = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        return ((h >= 120) & (h <= 170) & (s >= 60) & (v >= 40)).mean() * 100

    etourdie = part_violette((802, 180))
    swain = part_violette((724, 900))
    check("l'unité étourdie est très violette", etourdie > 40, etourdie)
    check("   mais Swain, SAIN, l'est presque autant", swain > 40, swain)
    check("   donc la teinte seule ferait un faux positif",
          abs(etourdie - swain) < 40, (etourdie, swain))

    # Le mouvement, lui, les sépare NETTEMENT.
    c_stun, _ = stun.mouvement(avant, cv2.imread(str(APRES)), (802, 180))
    c_swain, b_swain = stun.mouvement(avant, cv2.imread(str(APRES)), (724, 900))
    check("le mouvement central sépare, lui",
          c_stun > 10 * max(c_swain, 0.01), (c_stun, c_swain))
    check("   et Swain bouge bien, mais sur ses BORDS", b_swain > 1.0, b_swain)


def test_une_lecture_impossible_ne_rend_pas_un_verdict():
    """
    PAS D'IMAGE, PAS DE VERDICT — jamais « sain » par défaut silencieux.

    Même règle que `lire_palier` (« jamais une valeur approchée ») et que
    `bilan.juger` (« illisible n'est pas un verdict ») : ici, ne rien
    pouvoir lire doit rendre False, c'est-à-dire « on ne sait pas », et
    le filet de `execute_blocks` reprend la main.
    """
    print("\nUne lecture impossible ne rend pas un verdict")
    avant, apres = _images()
    check("aucune image : pas étourdie", stun.est_etourdie(None, None, (802, 180)) is False)
    check("une seule image : pas étourdie", stun.est_etourdie(avant, None, (802, 180)) is False)
    check("vignette hors de l'écran : pas étourdie",
          stun.est_etourdie(avant, apres, (5, 5)) is False)
    check("   ni au bord opposé", stun.est_etourdie(avant, apres, (1918, 1078)) is False)
    check("mouvement rendu nul hors cadre",
          stun.mouvement(avant, apres, (5, 5)) == (0.0, 0.0))

    # Deux captures IDENTIQUES : rien ne bouge, donc personne n'est étourdi.
    check("deux fois la même image : personne n'est étourdi",
          stun.est_etourdie(avant, avant, (802, 180)) is False)

    # CE QUI N'EST PAS UNE IMAGE NE DOIT PAS FAIRE TOMBER LA BOUCLE.
    # Trouvé en branchant : la couture d'`actions` est bouchonnée dans
    # les suites, et son bouchon rend une CHAÎNE — `est_etourdie` levait
    # un AttributeError en plein `execute_blocks`. Une lecture d'écran
    # qui plante coûte le combat entier ; une lecture qui s'abstient ne
    # coûte qu'un blocage, rattrapé par le filet.
    for bidon in ("une chaîne", 42, [1, 2, 3], object()):
        check(f"   {type(bidon).__name__} : pas de verdict, pas de plantage",
              stun.est_etourdie(bidon, bidon, (802, 180)) is False)
    check("   et une image contre une chaîne non plus",
          stun.est_etourdie(avant, "pas une image", (802, 180)) is False)


def test_les_cartes_sont_rendues_par_card_id():
    """`cartes_etourdies` rend des CardID, et saute ce qui n'en a pas."""
    print("\nLes étourdies se nomment par CardID")
    avant, apres = _images()
    cartes = [_Carte(n, i, c) for n, i, c, _ in ENNEMIS + LES_NOTRES]
    lues = stun.cartes_etourdies(avant, apres, cartes)
    check("une seule étourdie", lues == {301}, lues)

    sans_id = [_Carte("Anonyme", -1, (802, 180))]
    check("une carte sans CardID est ignorée",
          stun.cartes_etourdies(avant, apres, sans_id) == set())
    check("aucune carte : ensemble vide",
          stun.cartes_etourdies(avant, apres, []) == set())
    check("cartes None : ensemble vide",
          stun.cartes_etourdies(avant, apres, None) == set())


def main():
    for test in (test_le_tourbillon_se_lit_sur_deux_captures,
                 test_la_teinte_et_le_delavage_ne_suffisaient_pas,
                 test_une_lecture_impossible_ne_rend_pas_un_verdict,
                 test_les_cartes_sont_rendues_par_card_id):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} échec(s) :")
        for nom in FAILURES:
            print(f"  - {nom}")
        return 1
    print("Tous les tests passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
