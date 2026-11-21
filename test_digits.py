#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_digits.py

La lecture des chiffres par la forme (digits.py), sur les VRAIES captures
de debug_cards/ et calibration_crops/ quand elles sont là.

    python test_digits.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import digits

ROOT = Path(__file__).resolve().parent
FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def test_templates_read_themselves():
    print("\nChaque template se relit")
    for digit in range(10):
        image = cv2.imread(str(ROOT / "chiffres" / f"{digit}.png"), cv2.IMREAD_UNCHANGED)
        if image is None:
            print(f"  (ignoré : chiffres/{digit}.png absent)")
            return
        # Relu par la couleur (sans son alpha), un template est plus gras
        # que lui-même : la lecture doit être JUSTE OU MUETTE, jamais fausse.
        bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        value = digits.read_number(bgr, 9, loose=True)
        check(f"{digit} -> {digit} ou rien", value in (digit, None), value)


def test_real_badges():
    """Badges d'attaque / PV de vraies cartes : valeurs connues."""
    print("\nBadges réels de debug_cards/")
    cases = [("01SI058.png", 5, 4), ("02IO003T1.png", 3, 2)]
    for name, attack, health in cases:
        image = cv2.imread(str(ROOT / "debug_cards" / name))
        if image is None or image.shape[:2] != (160, 127):
            print(f"  (ignoré : {name} absent ou d'une autre taille)")
            continue
        atk = digits.read_number(image[118:152, 12:60], 30, loose=True)
        hp = digits.read_number(image[118:152, 68:118], 30, loose=True)
        check(f"{name} : attaque {attack}", atk == attack, atk)
        check(f"{name} : PV {health}", hp == health, hp)
        # La lecture SÛRE ne se trompe jamais : elle rend la bonne valeur ou rien.
        sure_atk = digits.read_number(image[118:152, 12:60], 30)
        sure_hp = digits.read_number(image[118:152, 68:118], 30)
        check(f"   lecture sûre : juste ou muette", sure_atk in (attack, None) and sure_hp in (health, None),
              (sure_atk, sure_hp))
        art = digits.read_number(image[30:90, 20:100], 30, loose=True)
        check(f"   l'illustration ne donne aucun chiffre", art is None, art)


def test_cost_gems():
    print("\nGemmes de coût et mana de sort")
    for name, cost in (("01IO012.png", 0), ("01IO041.png", 6)):
        image = cv2.imread(str(ROOT / "debug_cards" / name))
        if image is None:
            print(f"  (ignoré : {name} absent)")
            continue
        value = digits.read_number(image[0:48, 0:48], 12, loose=True)
        check(f"{name} : coût {cost}", value == cost, value)
        sure = digits.read_number(image[0:48, 0:48], 12)
        check("   lecture sûre : juste ou muette", sure in (cost, None), sure)
    sm = cv2.imread(str(ROOT / "calibration_crops" / "spell_mana.png"))
    if sm is None:
        print("  (ignoré : spell_mana.png absent)")
    else:
        check("mana de sort : 2 (bleu clair)", digits.read_number(sm, 3, loose=True) == 2,
              digits.read_number(sm, 3, loose=True))


def test_bounds_and_noise():
    print("\nBornes et bruit")
    image = cv2.imread(str(ROOT / "debug_cards" / "01SI058.png"))
    if image is None:
        print("  (ignoré : 01SI058.png absent)")
        return
    crop = image[118:152, 12:60]
    check("hors borne -> None", digits.read_number(crop, 3, loose=True) is None)
    noise = np.random.default_rng(1).integers(0, 255, size=(30, 40, 3), dtype=np.uint8)
    check("bruit -> None", digits.read_number(noise, 20, loose=True) is None)
    check("crop vide -> None", digits.read_number(np.zeros((0, 0, 3), np.uint8), 20) is None)
    check("None -> None", digits.read_number(None, 20) is None)


def test_un_glyphe_inconnu_refuse_le_nombre():
    """
    08/11/2026 : un glyphe non reconnu était SAUTÉ, et « 19 » devenait
    « 1 ».

    Le titre « DÉFI 19 » portait un 9 que la police du titre ne
    connaissait pas encore. `read_number` passait au suivant sans rien
    dire et rendait 1 — un nombre plausible, et faux. `lire_palier`
    promet pourtant « jamais une valeur approchée » : c'est ici que la
    promesse se tient. Le bot aurait cherché un champion à 3 étoiles là
    où le palier 19 en demande 4.

    La bande est ÉTROITE à dessein : les vrais badges portent du décor
    que `glyph_boxes` laisse entrer exprès (bord de gemme à 15 px contre
    un chiffre de 23), et le refuser casserait des lectures justes.
    """
    print(chr(10) + "Un glyphe de la taille d'un chiffre qu'on ne sait pas lire")

    def bande(hauteurs_inconnues, haut_chiffre=30):
        """Une image : un « 1 » lisible, plus des taches aux hauteurs voulues."""
        img = np.zeros((48, 40 + 22 * len(hauteurs_inconnues), 3), np.uint8)
        # un « 1 » bien net : une barre verticale blanche
        cv2.rectangle(img, (8, 8), (12, 8 + haut_chiffre), (255, 255, 255), -1)
        for i, h in enumerate(hauteurs_inconnues):
            x = 30 + 22 * i
            # un anneau : aucune forme de chiffre, mais la hauteur voulue
            cv2.rectangle(img, (x, 8), (x + 14, 8 + h), (255, 255, 255), 2)
        return img

    seul = digits.read_number(bande([]), 30, loose=True)
    check("le « 1 » seul se lit", seul == 1, seul)

    # Un inconnu de la MÊME hauteur : c'est un chiffre qu'on n'a pas su
    # lire, le nombre entier est refusé.
    meme = digits.read_number(bande([30]), 99, loose=True)
    check("un inconnu de la taille d'un chiffre refuse le nombre", meme is None, meme)

    # Du décor : nettement plus court, ou nettement plus grand.
    court = digits.read_number(bande([14]), 99, loose=True)
    check("un éclat bien plus court reste sauté", court == 1, court)
    grand = digits.read_number(bande([44]), 99, loose=True)
    check("un anneau bien plus grand reste sauté", grand == 1, grand)


def test_une_police_sert_la_ou_elle_a_ete_recoltee():
    """
    08/11/2026 : `chiffres/N_defi.png` est la police du TITRE « DÉFI N »,
    et `load_variants` la servait à toutes les lectures.

    Le commentaire du 05/11 le disait déjà — « ce n'est pas la police des
    coûts » — mais rien ne l'empêchait. Mesuré : le « 9 » du titre,
    pourtant fidèle, reconnaissait un morceau d'ILLUSTRATION de carte
    comme un 9 (0.61, marge 0.12), ce que `test_real_badges` interdit.
    Une police récoltée ailleurs est une surface de faux positifs.
    """
    print(chr(10) + "Une police par usage : le titre ne pollue pas les badges")
    # LE TITRE A PLUSIEURS VARIANTES DEPUIS LE 14/11/2026 (`defi2`) : le
    # « 3 » et le « 6 » récoltés sur la liste des défis n'atteignaient pas
    # la marge sur un VRAI titre, et `load_variants` prend le MAX des
    # variantes d'un chiffre. Le test porte donc sur TOUTES les familles
    # de titre, pas sur un nom de fichier.
    titre = tuple(f for f in digits.RESERVED_FAMILIES if f.startswith("defi"))
    par_defaut = digits.load_variants()
    du_titre = digits.load_variants(families=titre)
    check("la police du titre existe", any(du_titre.values()), None)
    # ON VÉRIFIE LA PROPRIÉTÉ, PAS LA CONSTANTE. L'assertion disait
    # `RESERVED_FAMILIES == ("defi",)` : elle gravait la valeur, donc
    # ajouter une variante légitime la faisait rougir sans qu'aucune
    # police de titre ait fui dans les badges. Ce qui compte est que
    # CHAQUE famille de titre présente dans `chiffres/` soit réservée —
    # le décompte ci-dessous le prouve ensuite en comptant les gabarits.
    familles = {f.stem[2:] for f in digits.DIGITS_DIR.glob("*_defi*.png")
                if len(f.stem) > 2}
    check("chaque police de titre est réservée",
          familles <= set(digits.RESERVED_FAMILIES),
          (familles, digits.RESERVED_FAMILIES))
    # Le décompte le dit mieux qu'un principe : il y a des `N_defi*.png`
    # dans le dossier, et aucun ne doit entrer dans le lot par défaut.
    fichiers = sorted(digits.DIGITS_DIR.glob("*_defi*.png"))
    if not fichiers:
        print("  (ignoré : aucune police de titre dans chiffres/)")
        return
    # CETTE ASSERTION NE POUVAIT PAS ÉCHOUER (relevé le 10/11/2026) :
    # elle disait `total_titre - total_defaut != 0 or total_defaut > 0`,
    # et `total_defaut` vaut 17 — la seconde moitié du « ou » était donc
    # vraie quoi qu'il arrive, y compris si TOUTE la police du titre
    # entrait dans le lot par défaut. Elle gardait la main du défaut
    # qu'elle était censée attraper.
    #
    # ON COMPTE LES FAMILLES SÉPARÉMENT. Le lot par défaut doit valoir
    # exactement « base + nexus », et le lot du titre « base + defi » :
    # chacun des deux rougit si un gabarit passe d'un lot à l'autre.
    base = [f for f in digits.DIGITS_DIR.glob("*.png") if len(f.stem) == 1]
    nexus = sorted(digits.DIGITS_DIR.glob("*_nexus.png"))
    total_defaut = sum(len(v) for v in par_defaut.values())
    total_titre = sum(len(v) for v in du_titre.values())
    check(f"le lot par défaut vaut base + nexus ({len(base)} + {len(nexus)}), "
          f"sans aucun des {len(fichiers)} gabarit(s) de titre",
          total_defaut == len(base) + len(nexus),
          (total_defaut, len(base), len(nexus)))
    check(f"le lot du titre vaut base + defi ({len(base)} + {len(fichiers)})",
          total_titre == len(base) + len(fichiers),
          (total_titre, len(base), len(fichiers)))
    base = {d for d, v in digits.load_variants(families=()).items() if v}
    check("la police de base reste commune aux deux", base and base <= set(par_defaut), base)


def main():
    for test in (test_templates_read_themselves, test_real_badges, test_cost_gems,
                 test_bounds_and_noise, test_un_glyphe_inconnu_refuse_le_nombre,
                 test_une_police_sert_la_ou_elle_a_ete_recoltee):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} test(s) en échec :")
        for name in FAILURES:
            print(f"  - {name}")
        raise SystemExit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
