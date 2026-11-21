#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_marqueur.py

OÙ NOUS SOMMES SUR LA CARTE — `marqueur_joueur.py`, sur les vraies
captures de la soirée du 08/11/2026, celle où le bot a perdu six
tentatives en suivant un DÉCOR.

    python test_marqueur.py

Hors ligne : aucune capture d'écran, aucun geste. Tout est lu par
`cv2.imread` dans `captures_reference/marqueur_*.png`.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

import adventure_navigation as an
import marqueur_joueur as mj

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT / "captures_reference"

# Les trois cartes témoins, avec le médaillon là où il a été MESURÉ.
# Deux champions différents : c'est tout l'enjeu du découpage à la volée.
CARTES = {
    # La capture du blocage du 08/11 à 18:01. Le losange y note 0.90 en
    # (318, 477) — 642 px à gauche du vrai repère.
    "marqueur_carte_20261108.png": (960, 451),
    # Même aventure, plus tard : la carte a défilé, le médaillon monte.
    "marqueur_carte_haute_20261108.png": (960, 349),
    # Une AUTRE aventure, un AUTRE champion (Ahri, portrait rose) : un
    # gabarit figé n'aurait aucune chance ici.
    "marqueur_carte_ahri_20261106.png": (960, 452),
}

# Un écran de combat : pas de carte, pas de HUD d'aventure, donc pas de
# portrait à découper — et surtout pas de position à inventer.
HORS_CARTE = "marqueur_combat_20260906.png"

TOLERANCE = 12          # px : on vise un médaillon de ~75 px de large

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def _lire(nom):
    image = cv2.imread(str(CAPTURES / nom))
    if image is None:
        print(f"  (ignoré : {nom} absent)")
    return image


def _loin(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def test_le_portrait_du_hud_se_decoupe_toujours_au_meme_endroit():
    print("\nLe portrait du champion est à une place FIXE dans le HUD")
    for nom in CARTES:
        image = _lire(nom)
        if image is None:
            continue
        gabarit, masque = mj.portrait_du_hud(image)
        check(f"{nom} : un disque est découpé", gabarit is not None)
        if gabarit is None:
            continue
        # L'ancre : l'anneau cyan d'expérience, ajusté en cercle. C'est
        # lui qui a donné le centre (116.5, 972.5) et le rayon 66.7.
        sous = image[880:1070, 20:230]
        hsv = cv2.cvtColor(sous, cv2.COLOR_BGR2HSV)
        cyan = ((hsv[:, :, 0] > 78) & (hsv[:, :, 0] < 105) &
                (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 110))
        ys, xs = np.nonzero(cyan)
        A = np.c_[2 * xs, 2 * ys, np.ones(len(xs))]
        sol, *_ = np.linalg.lstsq(A, xs ** 2 + ys ** 2, rcond=None)
        cx, cy = sol[0] + 20, sol[1] + 880
        attendu = (mj.PORTRAIT_CENTRE[0] * 1920, mj.PORTRAIT_CENTRE[1] * 1080)
        check(f"{nom} : anneau cyan centré sur le découpage",
              _loin((cx, cy), attendu) <= 4,
              f"anneau ({cx:.1f}, {cy:.1f}) contre {attendu}")
        contraste = mj.contraste_du_portrait(gabarit, masque)
        check(f"{nom} : le disque a bien un portrait dedans "
              f"(contraste {contraste:.1f})", contraste >= mj.CONTRASTE_MIN)


def test_le_medaillon_est_trouve_sur_la_carte():
    print("\nLe médaillon est retrouvé là où il est, quel que soit le champion")
    for nom, attendu in CARTES.items():
        image = _lire(nom)
        if image is None:
            continue
        mj.oublier_echelle()
        trouve = mj.trouver_medaillon(image, memoire=False)
        check(f"{nom} : un médaillon est trouvé", trouve is not None)
        if trouve is None:
            continue
        check(f"{nom} : en {trouve.point} (score {trouve.score:.2f}, "
              f"échelle {trouve.echelle:.3f})",
              _loin(trouve.point, attendu) <= TOLERANCE,
              f"attendu {attendu}")
        # La marge est le garde-fou, pas le seuil : au-dessous de 0.74 on
        # n'a jamais vu un vrai médaillon, au-dessus de 0.60 on n'a
        # jamais vu un faux.
        check(f"{nom} : score confortable", trouve.score >= 0.74,
              f"{trouve.score:.3f}")


def test_le_losange_nest_pas_nous():
    print("\nLE BUG DU 08/11 : le losange est un décor, pas notre position")
    image = _lire("marqueur_carte_20261108.png")
    if image is None:
        return
    score, point = an.best_match(an.TEMPLATES["player_marker"], screen=image)
    check(f"le losange est bien reconnu, à {score:.2f} en {point}",
          score is not None and score >= an.MATCH_THRESHOLD)
    mj.oublier_echelle()
    trouve = mj.trouver_medaillon(image, memoire=False)
    if trouve is None or point is None:
        check("les deux repères sont lisibles", False)
        return
    ecart = _loin(point, trouve.point)
    check(f"et il désigne un AUTRE point, à {ecart:.0f} px du médaillon",
          ecart > 400, f"losange {point}, médaillon {trouve.point}")
    # Le nœud candidat de ce soir-là était en (986, 173) : à droite du
    # losange (318), mais PAS à droite du médaillon (960). C'est la
    # décision que la fausse position retournait.
    noeuds = [(0.87, (986, 173), "normal_node.png")]
    depuis_losange = an.pick_next_node(noeuds, point)
    depuis_medaillon = an.pick_next_node(noeuds, trouve.point)
    check("depuis le losange, le nœud (986, 173) passait pour « devant »",
          depuis_losange is not None)
    check("depuis le médaillon, il n'est plus devant nous",
          depuis_medaillon is None)


def test_un_gabarit_fige_ne_marcherait_pas():
    print("\nUn gabarit figé ne marcherait pas : le portrait change de champion")
    carte = _lire("marqueur_carte_20261108.png")
    autre = _lire("marqueur_carte_ahri_20261106.png")
    if carte is None or autre is None:
        return
    # Le portrait d'UNE aventure cherché sur la carte d'une AUTRE, par
    # le chemin que le bot emprunte vraiment : il n'y a rien à trouver.
    mj.oublier_echelle()
    etranger = mj.trouver_medaillon(autre, memoire=False,
                                    portrait=mj.portrait_du_hud(carte))
    check("le portrait du 08/11 ne se retrouve pas sur la carte d'Ahri",
          etranger is None, f"trouvé {etranger}")
    # Et pourtant, découpé sur SA propre capture, il s'y retrouve.
    mj.oublier_echelle()
    check("alors qu'il se retrouve sur la sienne",
          mj.trouver_medaillon(carte, memoire=False) is not None)


def test_hors_de_la_carte_on_ne_trouve_rien():
    print("\nHors de la carte, aucune position n'est inventée")
    combat = _lire(HORS_CARTE)
    if combat is not None:
        gabarit, masque = mj.portrait_du_hud(combat)
        contraste = mj.contraste_du_portrait(gabarit, masque)
        check(f"écran de combat : pas de portrait dans le HUD "
              f"(contraste {contraste:.1f})", contraste < mj.CONTRASTE_MIN)
        mj.oublier_echelle()
        check("écran de combat -> aucun médaillon",
              mj.trouver_medaillon(combat, memoire=False) is None)
    # LE SCORE SEUL NE SUFFIT PAS, et c'est pour ça que le contraste
    # existe : un aplat corrélé à un aplat monte très haut. Deux zones
    # uniformes suffisent à le montrer.
    plat = np.full((1080, 1920, 3), 30, np.uint8)
    plat[300:500, 800:1000] = 31
    mj.oublier_echelle()
    check("un écran quasi uniforme -> aucun médaillon",
          mj.trouver_medaillon(plat, memoire=False) is None)
    bruit = np.random.default_rng(11).integers(0, 255, size=(1080, 1920, 3),
                                               dtype=np.uint8)
    mj.oublier_echelle()
    check("du bruit -> aucun médaillon",
          mj.trouver_medaillon(bruit, memoire=False) is None)
    check("une image minuscule -> aucun médaillon",
          mj.trouver_medaillon(np.zeros((8, 8, 3), np.uint8)) is None)
    check("pas d'image du tout -> aucun médaillon",
          mj.trouver_medaillon(None) is None)


def test_la_memoire_dechelle_ne_change_pas_la_reponse():
    print("\nLa mémoire d'échelle fait gagner du temps, pas changer d'avis")
    image = _lire("marqueur_carte_20261108.png")
    if image is None:
        return
    mj.oublier_echelle()
    seul = mj.trouver_medaillon(image, memoire=False)
    mj.oublier_echelle()
    premier = mj.trouver_medaillon(image)                 # balayage complet
    second = mj.trouver_medaillon(image)                  # échelle mémorisée
    if not (seul and premier and second):
        check("les trois lectures aboutissent", False)
        return
    check("l'échelle gagnante est mémorisée",
          mj._DERNIERE_ECHELLE == premier.echelle)
    check("et la seconde lecture rend le même point",
          second.point == premier.point == seul.point,
          f"{seul.point} / {premier.point} / {second.point}")
    mj.oublier_echelle()
    check("oublier_echelle() remet le balayage complet",
          mj._DERNIERE_ECHELLE is None)


def test_le_repli_quand_rien_nest_devant_nous():
    """
    La carte d'Ahri : les deux nœuds joignables sont SOUS nous.

    C'est le cas que la position fausse masquait. Depuis le losange
    (515, 454), posé 445 px à gauche, les deux nœuds passaient pour
    « devant » et le bot prenait le bon. Depuis le médaillon (960, 452),
    la règle de la droite ne retient plus qu'un faux positif des
    gabarits de nœud — le bouton boussole, 0.85 en (1819, 470) — et
    « le plus à gauche » enverrait sur la flèche retour. Le repli « le
    plus proche » retrouve le nœud que l'ancien code prenait.
    """
    print("\nQuand la suite du chemin est DESSOUS, le repli la retrouve")
    import navigate
    image = _lire("marqueur_carte_ahri_20261106.png")
    if image is None:
        return
    noeuds = an.find_nodes_in_folder(navigate.NODES_DIR, screen=image)
    points = [p for _s, p, _n in noeuds]
    COEUR, BAS, BOUSSOLE = (725, 633), (976, 795), (1819, 470)
    check(f"trois candidats sur cette carte : {points}",
          len(noeuds) == 3 and all(any(_loin(p, c) <= 10 for p in points)
                                   for c in (COEUR, BAS, BOUSSOLE)))
    losange = (515, 454)
    ancien = an.pick_next_node(noeuds, losange)
    check("depuis le losange, l'ancien code prenait le nœud du cœur",
          ancien is not None and _loin(ancien[1], COEUR) <= 10, ancien)

    mj.oublier_echelle()
    medaillon = mj.trouver_medaillon(image, memoire=False)
    if medaillon is None:
        check("le médaillon est trouvé", False)
        return
    devant = an.pick_next_node(noeuds, medaillon.point)
    check("depuis le médaillon, « à droite » ne laisse que la boussole "
          "(faux positif des gabarits)",
          devant is not None and _loin(devant[1], BOUSSOLE) <= 10, devant)
    # ICI, « le plus à gauche » tombe juste — il n'y a pas de faux
    # positif à gauche sur cette carte. C'est ailleurs qu'il se trompe
    # (quatre captures du projet où il part sur la flèche retour du coin
    # haut-gauche, reconnue 0.81 par les gabarits de nœud) : on le note
    # pour que la différence entre les deux replis ne soit pas lue ici.
    a_gauche = an.pick_next_node(noeuds, None)
    check("sur CETTE carte, « le plus à gauche » tombe juste lui aussi",
          a_gauche is not None and _loin(a_gauche[1], COEUR) <= 10, a_gauche)
    proche = navigate._plus_proche(noeuds, medaillon.point)
    check("le repli « le plus proche » retrouve le nœud du cœur",
          proche is not None and _loin(proche[1], COEUR) <= 10, proche)
    # Et une fois la boussole écartée (cliquée sans « Voyage »), la
    # règle de la droite ne propose plus rien : le repli joue.
    reste = an.pick_next_node(noeuds, medaillon.point, exclude=(BOUSSOLE,))
    check("boussole écartée -> plus rien « devant nous »", reste is None, reste)
    proche = navigate._plus_proche(noeuds, medaillon.point, exclude=(BOUSSOLE,))
    check("   et le repli prend toujours le nœud du cœur",
          proche is not None and _loin(proche[1], COEUR) <= 10, proche)

    # LÀ OÙ LES DEUX REPLIS SE SÉPARENT, relevé sur
    # `screenshots/noeud_quitte_20261105_180428.png` : les gabarits de
    # nœud reconnaissent la FLÈCHE RETOUR du coin haut-gauche à 0.82 en
    # (99, 43). Le médaillon y est en (279, 458), le vrai nœud en
    # (261, 205). Quatre captures du projet sont dans ce cas.
    flechette = [(0.82, (99, 43), "normal_node.png"),
                 (0.85, (261, 205), "normal_node.png")]
    check("« le plus à gauche » part sur la flèche retour",
          an.pick_next_node(flechette, None)[1] == (99, 43))
    check("« le plus proche » prend le vrai nœud",
          navigate._plus_proche(flechette, (279, 458))[1] == (261, 205))
    check("   et c'est ce que l'ancien code prenait aussi, par chance",
          an.pick_next_node(flechette, (60, 466))[1] == (261, 205))


def test_navigate_lit_le_medaillon():
    print("\n`navigate._player_position` passe bien par le médaillon")
    import navigate
    check("le losange ne décide plus", navigate.MARQUEUR_LOSANGE is False)
    image = _lire("marqueur_carte_20261108.png")
    if image is None:
        return
    mj.oublier_echelle()
    point = navigate._player_position(image)
    check(f"position rendue : {point}",
          point is not None and _loin(point, CARTES["marqueur_carte_20261108.png"]) <= TOLERANCE)
    combat = _lire(HORS_CARTE)
    if combat is not None:
        mj.oublier_echelle()
        check("hors carte, la position reste None (les replis jouent)",
              navigate._player_position(combat) is None)


def main():
    for test in (test_le_portrait_du_hud_se_decoupe_toujours_au_meme_endroit,
                 test_le_medaillon_est_trouve_sur_la_carte,
                 test_le_losange_nest_pas_nous,
                 test_un_gabarit_fige_ne_marcherait_pas,
                 test_hors_de_la_carte_on_ne_trouve_rien,
                 test_la_memoire_dechelle_ne_change_pas_la_reponse,
                 test_le_repli_quand_rien_nest_devant_nous,
                 test_navigate_lit_le_medaillon):
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
