#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_champions.py

La lecture de la GRILLE DES CHAMPIONS (champions.py), sur les vraies
captures du 05/11/2026 — celles qui ont montré que le bot prenait
systématiquement le plus faible du compte.

    python test_champions.py

Hors ligne : ni souris, ni jeu, ni OCR.
"""

from __future__ import annotations

from pathlib import Path

import logging
import time

import cv2
import numpy as np

import champions

# UN GUET QUI PHOTOGRAPHIE L'ÉCRAN N'A RIEN À FAIRE DANS UNE SUITE HORS
# LIGNE. `journaliser_palier_illisible` capture le jeu et ÉCRIT un PNG
# dans `screenshots/` quand le palier ne se lit pas sur la grille :
# branché tel quel, il photographierait l'écran d'Ewan à chaque
# exécution. C'est le SEPTIÈME chemin de ce genre — park_mouse,
# choisir_champion, play_reward, revenir_en_haut, _lire_le_bilan,
# journaliser_pile_bloquee — et les six premiers ont tous fini par le
# faire pour de bon. On GARDE les appels : un test vérifie qu'il est
# demandé au bon moment, et seulement là.
#
# LA LISTE EST PORTÉE PAR `champions`, PAS PAR CE MODULE : une suite
# lancée en script est `__main__`, et le moindre `from test_champions
# import …` ailleurs en charge une SECONDE copie qui rejoue ce bouchon.
# Les appels partiraient alors dans la liste de la copie, et le test
# verrait la sienne vide (heisenbug du 10/11/2026 sur `test_actions`).
PALIERS_ILLISIBLES = getattr(champions, "_paliers_illisibles_test", None)
if PALIERS_ILLISIBLES is None:
    PALIERS_ILLISIBLES = champions._paliers_illisibles_test = []
champions.journaliser_palier_illisible = (
    lambda ecran=None: PALIERS_ILLISIBLES.append(ecran) or ""
)

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT / "captures_reference"
HAUT = CAPTURES / "champions_haut_20261105.png"
BAS = CAPTURES / "champions_bas_20261105.png"
SELECTION = CAPTURES / "champions_selection_20261105.png"
DEFI19 = CAPTURES / "champions_defi19_20261108.png"
LISTE = CAPTURES / "liste_defis_20261108.png"
PAS_LA_GRILLE = CAPTURES / "bilan_defaite_20261104.png"

# L'heure du lancement : sert à prouver, en fin de suite, qu'aucun PNG
# neuf n'a été déposé dans `screenshots/`.
_DEBUT = time.time()

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def _lire(chemin):
    image = cv2.imread(str(chemin))
    if image is None:
        print(f"  (ignoré : {chemin.name} absent)")
    return image


def test_le_haut_de_la_grille_est_le_plus_faible():
    print("\nLe haut de la grille : Zoé 1, Nunu 1, Hecarim 2, puis trois 3")
    image = _lire(HAUT)
    if image is None:
        return
    vues = champions.lire_vignettes(image)
    check("six vignettes lues", len(vues) == 6, [v.etoiles for v in vues])
    check("les étoiles, dans l'ordre de lecture : 1, 1, 2, 3, 3, 3",
          [v.etoiles for v in vues] == [1, 1, 2, 3, 3, 3], [v.etoiles for v in vues])
    check("aucune n'est épuisée", not any(v.epuisee for v in vues),
          [v.epuisee for v in vues])

    # LE FAIT QUI A TOUT DÉCLENCHÉ : `first_champion` cliquait le haut de
    # la grille, c'est-à-dire le PIRE champion du compte.
    meilleure = champions.meilleure(vues)
    check("le choix ne tombe pas sur la première vignette",
          meilleure is not None and meilleure is not vues[0], meilleure)
    check("il prend 3 étoiles, pas 1", meilleure.etoiles == 3, meilleure.etoiles)


def test_le_bas_de_la_grille_porte_les_sept_etoiles():
    print("\nLe bas de la grille : les 7 étoiles, et Shen épuisé")
    image = _lire(BAS)
    if image is None:
        return
    vues = champions.lire_vignettes(image)
    check("six vignettes lues (la rangée du haut est coupée, donc écartée)",
          len(vues) == 6, [(v.etoiles, v.y) for v in vues])
    check("cinq à 7 étoiles et Shen à 1",
          sorted(v.etoiles for v in vues) == [1, 7, 7, 7, 7, 7],
          [v.etoiles for v in vues])

    epuisees = [v for v in vues if v.epuisee]
    check("une seule vignette épuisée", len(epuisees) == 1, len(epuisees))
    check("et c'est celle à 1 étoile (Shen)",
          epuisees and epuisees[0].etoiles == 1, [v.etoiles for v in epuisees])


def test_le_choix_prend_le_plus_etoile_encore_jouable():
    print("\nLe choix : le plus d'étoiles, parmi ceux qui ont encore une tentative")
    image = _lire(BAS)
    if image is None:
        return
    vues = champions.lire_vignettes(image)
    choisi = champions.meilleure(vues)
    check("un champion est choisi", choisi is not None)
    if choisi is None:
        return
    check("sept étoiles", choisi.etoiles == 7, choisi.etoiles)
    check("pas l'épuisé", not choisi.epuisee, choisi)

    # À ÉGALITÉ D'ÉTOILES, LE DERNIER DE LA LISTE. La grille est triée en
    # ordre croissant (mesuré : 44, 45, 45, 50, 50 chez les 7 étoiles),
    # donc le dernier est le plus haut niveau — sans lire la pastille, qui
    # est trop petite pour les gabarits de chiffres.
    sept = [v for v in vues if v.etoiles == 7 and not v.epuisee]
    check("c'est le DERNIER des sept-étoiles (le plus haut niveau)",
          choisi is sept[-1], (choisi.x, choisi.y))
    # Teemo Fleur Spirituelle : colonne du milieu, rangée du bas. C'est
    # exactement le point cliqué à la main le 05/11, qui a donné la
    # première victoire du bot.
    check("son point de clic tombe sur la vignette de Teemo (572, 930) ± 12",
          abs(choisi.clic[0] - 572) <= 12 and abs(choisi.clic[1] - 930) <= 12, choisi.clic)


def test_le_palier_se_lit_sur_le_titre():
    print(chr(10) + "Le palier : « DÉFI N » lu sur le titre, pas compté")
    image = _lire(HAUT)
    if image is None:
        return
    # Le titre est DORÉ et digits.glyph_mask exclut l'orange à dessein :
    # sans blanchiment, « 2 » est illisible. Mesuré le 05/11/2026.
    check("le palier affiché est lu", champions.lire_palier(image) == 2,
          champions.lire_palier(image))
    bas = _lire(BAS)
    if bas is not None:
        check("   et le même sur l'autre capture", champions.lire_palier(bas) == 2,
              champions.lire_palier(bas))
    autre = _lire(PAS_LA_GRILLE)
    if autre is not None:
        check("ailleurs : aucun palier inventé", champions.lire_palier(autre) is None,
              champions.lire_palier(autre))


def test_la_police_du_titre_sait_lire_un_palier_a_deux_chiffres():
    """
    06/11/2026 : la police `chiffres/N_defi.png` ne connaissait que 2, 6
    et 7. Tout palier écrit avec un autre chiffre rendait None, et
    `_pick_first_challenge` retombait alors sur « le plus étoilé » — il a
    dépensé des **7 ★** sur des paliers qui n'en demandaient pas, ce que
    la table d'allocation existe précisément pour éviter.

    Les chiffres manquants sont récoltés sur des captures déjà gardées,
    jamais inventés :
        « DÉFI 11 » sur `reprendre_aventure_20261106.png`  -> le 1
        « DÉFI 4 »  sur `champions_selection_20261105.png` -> le 4
        « DÉFI 19 » sur `champions_defi19_20261108.png`    -> le 9
    Restent 0 et 8 : le 10/11/2026, 16 077 PNG du dépôt ont été balayés
    et AUCUN titre « DÉFI N » n'en contient un. On ne les dessine pas.

    CE TEST EST LE FILET DE LA POLICE : chaque chiffre appris y gagne
    une capture témoin, et un fichier perdu ou réécrit de travers le
    fait virer au rouge au lieu de rendre silencieusement None.
    """
    print(chr(10) + "La police du titre : un palier à deux chiffres se lit")

    attendus = [
        ("reprendre_aventure_20261106.png", 11),
        ("champions_selection_20261105.png", 4),
        ("champions_haut_20261105.png", 2),
        ("champions_bas_20261105.png", 2),
        # 08/11/2026 : « DÉFI 19 », le premier palier à porter un 9.
        # Il a coûté deux défauts d'un coup, l'un derrière l'autre —
        # `cut_defi` découpait la forme avec un masque qui n'est PAS
        # celui de la lecture, et le fichier écrit avait un alpha à 0/1
        # que `digits._read_mask` (>= 128) jetait sans un mot. Le palier
        # se lisait « 1 », pas « 19 » : la table aurait demandé 3 étoiles
        # au lieu de 4.
        ("champions_defi19_20261108.png", 19),
    ]
    for nom, palier in attendus:
        image = _lire(CAPTURES / nom)
        if image is None:
            continue
        lu = champions.lire_palier(image)
        check("« DÉFI %-2s » lu sur %s" % (palier, nom[:34]), lu == palier, lu)

    # CHAQUE GLYPHE DE LA POLICE PORTE SA FORME EN ALPHA, comme les
    # chiffres du nexus : c'est l'alpha que `digits` compare, un PNG
    # opaque ne vaudrait rien. On le vérifie fichier par fichier plutôt
    # que de faire confiance à `cut-defi`.
    import digits
    import cv2 as _cv2
    fichiers = sorted(digits.DIGITS_DIR.glob("*_defi.png"))
    connus = {f.name.split("_")[0] for f in fichiers}
    check("la police connaît au moins 1, 2, 3, 4 et 5",
          {"1", "2", "3", "4", "5"} <= connus, sorted(connus))
    for fichier in fichiers:
        glyphe = _cv2.imread(str(fichier), _cv2.IMREAD_UNCHANGED)
        forme = (glyphe is not None and glyphe.ndim == 3
                 and glyphe.shape[2] == 4 and 0 < (glyphe[:, :, 3] > 0).mean() < 1)
        check("   %s porte sa forme en alpha" % fichier.name, forme,
              None if glyphe is None else glyphe.shape)


def _lire_nombre(capture, zone):
    """Un nombre encadré à la main, lu par le chemin de `lire_palier`."""
    image = _lire(CAPTURES / capture)
    if image is None:
        return "absent"
    x0, y0, x1, y1 = zone
    crop = image[y0:y1, x0:x1].copy()
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    crop[cv2.inRange(hsv, champions.DORE_BAS, champions.DORE_HAUT) > 0] = (255, 255, 255)
    import digits
    return digits.read_number(crop, maximum=99, families=champions.TITRE_POLICE)


def test_le_3_et_le_5_viennent_de_la_liste_des_defis():
    """
    10/11/2026 — LE 3 ET LE 5 N'EXISTENT DANS AUCUN TITRE DU DÉPÔT.

    Le 09/11 le bot a joué le défi 23 avec un champion 6 ★ là où la table
    en demandait 4 : le « 3 » manquait, `lire_palier` a refusé le nombre
    ENTIER (le garde-fou voulu du 08/11) et `_pick_first_challenge` est
    retombé sur « le plus étoilé ». Les tentatives étant limitées à trois
    par champion et par mois, sur-payer est une perte sèche.

    Or les 16 077 PNG du dépôt ne contiennent QUE des titres « DÉFI 1, 2,
    4, 11, 19 » : il n'y a nulle part un 0, un 3, un 5 ni un 8 écrit dans
    la bande du titre. Le même écran les écrit AILLEURS, et c'est LA MÊME
    POLICE — mesuré, pas supposé (cf. la docstring de `cut_defi`) :

        même chiffre, liste contre titre       0.74 à 0.90
        témoin interne, titre contre titre     0.82 à 1.00
        chiffres DIFFÉRENTS, même police       0.32 à 0.45
        la police des COÛTS sur ces glyphes    None, 0.53 à 0.59

    D'où le 3 pris sur « VICTOIRES TOTALES : 23 » (14×35 doré : la taille
    ET la couleur d'un glyphe de titre) et le 5 sur « 5 XP DE DÉFI »
    (11×24). Les témoins ci-dessous sont des rendus que la récolte n'a
    PAS servi de source : c'est tout ce qui distingue un gabarit mesuré
    d'un gabarit qui ne reconnaît que lui-même.
    """
    print(chr(10) + "Le 3 et le 5, récoltés hors du titre : les témoins")

    L8, L9 = "liste_defis_20261108.png", "liste_defis_20261109.png"
    # La SOURCE de chaque récolte — elle doit évidemment se relire.
    check("« VICTOIRES TOTALES : 23 » (source du 3) se lit 23",
          _lire_nombre(L9, (430, 605, 500, 655)) in (23, "absent"))
    check("« 5 XP DE DÉFI » (source du 5) se lit 5",
          _lire_nombre(L8, (175, 745, 200, 790)) in (5, "absent"))
    # LES TÉMOINS INDÉPENDANTS : d'autres rendus, d'autres captures.
    check("   le même « 5 », une autre capture, se lit encore 5",
          _lire_nombre(L9, (175, 745, 200, 790)) in (5, "absent"))
    # LA DIFFICULTÉ « ★ 3 » (8×19) NE SE LIT PLUS DEPUIS LE 14/11, ET
    # C'EST LE PRIX DU « 8 » — pas une régression du 3. Mesuré sur CE
    # glyphe, avant et après la récolte du 8 sur le palier 28 :
    #
    #     sans le 8 :  3=0.808, 9=0.697  ->  marge 0.111  ->  LU 3
    #     avec le 8 :  3=0.808, 8=0.728  ->  marge 0.080  ->  REFUSÉ
    #
    # Le 3 reste le MEILLEUR candidat à 0.808 : il n'est jamais lu
    # autrement, il perd sa marge face au 8, qui lui ressemble. Le
    # plancher (0.10) mord, et c'est lui qui tient l'invariant « jamais
    # une valeur approchée ». ENRICHIR UNE POLICE RESSERRE SES MARGES :
    # chaque chiffre ajouté est un concurrent de plus pour tous les
    # autres, et ce témoin-là est le plus fragile parce qu'il fait 19 px
    # là où un titre en fait 27-38 — à la frontière de ce que `digits`
    # sépare. CE QU'ON NE FAIT PAS pour le rattraper : récolter une
    # variante du 3 sur le témoin lui-même (un gabarit qui ne
    # reconnaîtrait que lui-même). Et la 3e source indépendante — le
    # « 3 » de « DÉFI 23 », testé juste en dessous — a été mesurée : en
    # variante, elle laisse le témoin à 0.808, marge inchangée. Même
    # forme que ce voisin, donc : 3 ou rien, jamais autre chose.
    lu = _lire_nombre(L8, (1270, 544, 1295, 571))
    check("   la difficulté « ★ 3 » (8×19) : 3 ou rien, jamais autre chose",
          lu in (3, None, "absent"), lu)
    # AVANT, « 5 XP DE DÉFI » SE LISAIT « 6 » — à 0.768 pour un plancher
    # de 0.72 et une marge de 0.182 pour 0.10 : une lecture CONFIANTE et
    # FAUSSE, pas un refus. Un palier 5, 15 ou 25 aurait donc rendu 6, 16
    # ou 26 sans un mot. C'est le vrai prix du chiffre manquant, et il
    # est pire que le refus qu'on croyait payer.
    check("   et plus jamais 6", _lire_nombre(L8, (175, 745, 200, 790)) != 6)

    # CE QUE LE 3 NE SAIT PAS ENCORE FAIRE, ÉCRIT ICI PLUTÔT QUE TU — le
    # « 3 » de « DÉFI 23 » dans la liste (11×27, crème) est bien
    # identifié comme un 3, mais à 0.746 pour une marge de 0.078 contre
    # le 9 : sous le plancher de 0.10, donc REFUSÉ. Récolter ce rendu-là
    # à la place inverse exactement le problème (il perd alors la ★ 3 et
    # le doré du titre, deux cas sur trois au lieu d'un). Ce qui compte
    # est qu'il ne soit jamais lu AUTREMENT.
    lu = _lire_nombre(L8, (1270, 497, 1320, 529))
    check("« DÉFI 23 » dans la liste : 23 ou rien, jamais autre chose",
          lu in (23, None, "absent"), lu)

    # Et les voisins déjà connus ne bougent pas.
    for capture, zone, attendu, libelle in (
            (L8, (1270, 278, 1320, 310), 22, "« DÉFI 22 »"),
            (L8, (1270, 716, 1320, 748), 24, "« DÉFI 24 »"),
            (L8, (430, 605, 500, 655), 21, "« VICTOIRES TOTALES : 21 »"),
            (L9, (1270, 278, 1320, 310), 24, "« DÉFI 24 » (09/11)"),
    ):
        valeur = _lire_nombre(capture, zone)
        check("   %s se lit toujours %d" % (libelle, attendu),
              valeur in (attendu, "absent"), valeur)


def test_le_decor_n_est_pas_un_titre():
    print(chr(10) + "Un écran sans titre ne rend JAMAIS un palier")
    decor = _lire(CAPTURES / "carte_sans_titre_20261106.png")
    if decor is None:
        return
    # LE BUG DU 06/11/2026, 00:12 : le bot a lu le palier AVANT que
    # l'écran du champion soit affiché. Le seuil de clarté a attrapé des
    # morceaux de décor — (126,79), (140,19), (63,29) — et la lecture a
    # rendu « illisible » TOUT DE SUITE. Donc aucune cible, donc « le
    # plus étoilé » : un 7 étoiles dépensé pour un palier qui en
    # demandait 3. Un faux « illisible » immédiat est pire qu'une
    # attente : `attendre_palier` ne réessaie que tant que ça échoue.
    zone, boites = champions._glyphes_du_titre(decor)
    check("les glyphes dépareillés du décor sont refusés", boites == [], boites)
    check("donc aucun palier", champions.lire_palier(decor) is None)
    check("   et aucune cible — on garde l'ancien choix",
          champions.etoiles_requises(champions.lire_palier(decor)) is None)

    # Et le vrai titre passe toujours : des glyphes de même hauteur.
    vrai = _lire(HAUT)
    if vrai is not None:
        _, b = champions._glyphes_du_titre(vrai)
        check("un vrai titre garde ses glyphes", len(b) >= 2, b)
        hauteurs = [x[3] for x in b]
        check("   tous de la même hauteur",
              max(hauteurs) - min(hauteurs) <= champions.TITRE_HAUTEUR_ECART, hauteurs)
        check("   et il se lit", champions.lire_palier(vrai) == 2,
              champions.lire_palier(vrai))


def test_la_table_garde_les_forts_pour_la_fin():
    print(chr(10) + "La table : le plus faible qui suffit, pas le plus fort")
    # 70 paliers, 3 tentatives par champion : dépenser les 7 étoiles en
    # bas de l'échelle, c'est arriver en haut avec des 3 (Ewan).
    attendu = {1: 3, 14: 3, 15: 4, 28: 4, 29: 5, 42: 5, 43: 6, 56: 6, 57: 7, 70: 7}
    for palier, etoiles in attendu.items():
        got = champions.etoiles_requises(palier)
        check(f"palier {palier} -> {etoiles} étoile(s)", got == etoiles, got)
    check("plancher à 3 : jamais moins", champions.etoiles_requises(1) == 3)
    check("palier inconnu -> aucune cible", champions.etoiles_requises(None) is None)

    image = _lire(HAUT)
    if image is None:
        return
    vues = champions.lire_vignettes(image)        # 1, 1, 2, 3, 3, 3
    vise3 = champions.meilleure(vues, cible=3)
    check("cible 3 : on prend un 3 étoiles, pas un 1",
          vise3 is not None and vise3.etoiles == 3, vise3)
    # Personne n'atteint 5 sur cet écran : on prend le plus fort plutôt
    # que de renoncer — une tentative tendue vaut mieux qu'aucune.
    vise5 = champions.meilleure(vues, cible=5)
    check("cible hors de portée : le plus fort disponible",
          vise5 is not None and vise5.etoiles == 3, vise5)
    check("sans cible : le plus fort (comportement d'avant)",
          champions.meilleure(vues).etoiles == 3)


def test_une_vignette_selectionnee_reste_lisible():
    print(chr(10) + "Une vignette DÉJÀ sélectionnée se lit comme les autres")
    image = _lire(SELECTION)
    if image is None:
        return
    # Mesuré le 05/11/2026 : en surbrillance, l'aire d'un glyphe passe de
    # 141-156 à 229-233 (plafond trop bas : la vignette disparaissait) et
    # des glyphes voisins FUSIONNENT en une seule tache de 101×32 (chaîne
    # cassée : 6 étoiles au lieu de 7). Si le meilleur champion était celui
    # déjà sélectionné, le bot le sautait.
    vues = champions.lire_vignettes(image)
    check("six vignettes, la sélectionnée comprise", len(vues) == 6,
          [(v.x, v.y, v.etoiles) for v in vues])
    selectionnee = [v for v in vues if v.x == 485 and v.y > 1000]
    check("la vignette sélectionnée est bien là", len(selectionnee) == 1, selectionnee)
    if selectionnee:
        check("   et elle garde ses 7 étoiles", selectionnee[0].etoiles == 7,
              selectionnee[0].etoiles)
    check("le choix la retient", champions.meilleure(vues) is not None
          and champions.meilleure(vues).etoiles == 7, champions.meilleure(vues))


def test_on_prend_la_DERNIERE_de_la_bande():
    print(chr(10) + "À étoiles égales, le plus haut niveau : la dernière de la bande")

    # La grille est triée en ordre croissant (étoiles, puis niveau). En
    # descendant, la PREMIÈRE vignette qui atteint la cible est la plus
    # faible EN NIVEAU de sa bande — c'est ce que le bot a pris au palier 6
    # le 05/11/2026, et il a perdu. On veut la DERNIÈRE de la bande.
    def tuile(etoiles, rang):
        return champions.Vignette(etoiles=etoiles, x=100 * rang, y=500,
                                  epuisee=False, clic=(100 * rang, 400))

    ecrans = [
        [tuile(1, 1), tuile(1, 2), tuile(2, 3)],      # rien d'assez fort
        [tuile(3, 4), tuile(3, 5), tuile(3, 6)],      # la bande commence
        [tuile(3, 7), tuile(3, 8), tuile(4, 9)],      # elle continue
        [tuile(4, 10), tuile(4, 11), tuile(5, 12)],   # on l'a dépassée
    ]
    # Un seul harnais pour tout le fichier (09/11/2026) : celui-ci était
    # recopié ici, avec un `_capture_garee` qui rendait la CHAÎNE
    # « écran ». Depuis que le bout de la liste se juge sur les pixels —
    # le même critère que `_parcourir` — une grille de papier doit avoir
    # des pixels, et deux copies du harnais finiraient par diverger comme
    # les deux critères qu'on vient d'unifier.
    choisi, position = _parcours_bouchonne(ecrans, cible=3, max_bonds=10)

    check("un champion est retenu", choisi is not None)
    if choisi is None:
        return
    check("il a bien 3 étoiles, pas 4", choisi.etoiles == 3, choisi.etoiles)
    # rang 8 = la dernière de la bande, sur l'avant-dernier écran.
    check("c'est la DERNIÈRE de la bande (le plus haut niveau)",
          choisi.clic == (800, 400), choisi.clic)
    check("on est remonté d'une rangée pour la cliquer", position[0] == 2, position[0])


def test_une_lecture_douteuse_ne_decide_pas():
    print("\nRien de lisible : aucun choix — on retombe sur l'ancien comportement")
    autre = _lire(PAS_LA_GRILLE)
    if autre is not None:
        check("l'écran de bilan n'est pas une grille de champions",
              champions.meilleure(champions.lire_vignettes(autre)) is None)
    bruit = np.random.default_rng(3).integers(0, 255, size=(1080, 1920, 3), dtype=np.uint8)
    check("bruit -> aucune vignette", champions.lire_vignettes(bruit) == [])
    check("aucune vignette -> aucun choix", champions.meilleure([]) is None)


def test_les_bornes_de_vraisemblance():
    print("\nUne vignette invraisemblable est refusée, pas jouée")
    image = _lire(HAUT)
    if image is None:
        return
    vues = champions.lire_vignettes(image)
    check("aucune vignette au-delà de la borne d'étoiles",
          all(1 <= v.etoiles <= champions.MAX_ETOILES for v in vues),
          [v.etoiles for v in vues])
    # Le bruit orange des illustrations faisait compter jusqu'à 8 étoiles
    # avant que la chaîne des 26 px ne soit imposée (mesuré le 05/11 :
    # Fiddlesticks, écarts 26, 26, 26, 26, 26, 59.8, 15.9).
    check("la chaîne des 26 px coupe le bruit des illustrations",
          all(v.etoiles <= 7 for v in vues), [v.etoiles for v in vues])


def test_une_molette_qui_nest_pas_entendue_nest_pas_un_bout_de_liste():
    """
    08/11/2026 : la panne la plus coûteuse de la session, et la plus muette.

    La fenêtre du jeu n'avait pas le premier plan. Un clic active la
    fenêtre qu'il touche, donc tant que le bot ne faisait que cliquer, le
    focus se réparait tout seul. LA MOLETTE NON : Unity ne traite les
    événements de molette que fenêtre ACTIVE, et `pyautogui.scroll` ne
    rend aucune erreur quand ils tombent dans le vide. Mesuré, même
    geste, même point :

        fenêtre au premier plan   écart entre deux captures : 33.6
        VS Code au premier plan   écart entre deux captures :  0.04

    `_parcourir` lisait ce silence comme « bas de liste atteint », dès le
    premier bond. Le bot a jugé un écran de six vignettes TOUTES
    épuisées, n'a trouvé personne à jouer, et a renoncé au choix du
    champion — puis son filet `first_champion` a échoué à son tour,
    parce que le haut de la grille n'était plus à l'écran.

    « Rien n'a bougé » ne veut dire « on est au bout » QUE SI LE GESTE
    EST PARTI.
    """
    print(chr(10) + "Une molette qui tombe dans le vide n'est pas un bout de liste")
    image = _lire(BAS)
    if image is None:
        return

    vrai_capture = champions._capture_garee
    vrai_defiler, vrai_remonter = champions._defiler, champions._remonter
    try:
        champions._capture_garee = lambda: image        # l'écran ne bouge pas
        gestes = []

        champions._defiler = lambda crans=0: (gestes.append("bas"), False)[1]
        champions._remonter = lambda crans=0: (gestes.append("haut"), False)[1]
        conclu = champions._parcourir(4, 44, descendre=True)
        check("molette inaudible : on ne conclut pas au bout de la liste",
              conclu is False, conclu)
        check("et on a bien tenté le geste", gestes == ["bas"], gestes)

        gestes.clear()
        champions._defiler = lambda crans=0: (gestes.append("bas"), True)[1]
        conclu = champions._parcourir(4, 44, descendre=True)
        check("molette entendue et écran fixe : c'est le bout de la liste",
              conclu is True, conclu)
    finally:
        champions._capture_garee = vrai_capture
        champions._defiler, champions._remonter = vrai_defiler, vrai_remonter


def test_le_repli_a_besoin_du_haut_de_la_grille():
    """
    08/11/2026 : `choisir_champion` échoue, et le filet ne peut pas jouer.

    Le filet documenté depuis le 05/11 est « on retombe sur le premier de
    la liste », c'est-à-dire `first_champion.png` — le HAUT de la grille.
    Mais `choisir_champion` laisse la grille là où son parcours l'a
    menée : EN BAS. Mesuré sur l'écran du jour, `first_champion` y notait
    0.64 pour un seuil de 0.80, et le bot a conclu « bouton introuvable »
    après avoir aussi garé la souris. Le filet ne pouvait donc JAMAIS se
    déclencher après un parcours. On remonte d'abord.
    """
    print(chr(10) + "Le repli vise le haut de la grille : il faut y être revenu")
    check("champions expose de quoi remonter", hasattr(champions, "revenir_en_haut"))

    import navigate
    import inspect
    source = inspect.getsource(navigate._pick_champion)
    check("et `_pick_champion` remonte avant de chercher first_champion",
          source.index("revenir_en_haut") < source.index('click_button("first_champion"'),
          None)


def test_une_grille_sans_vignette_nest_pas_la_grille():
    """
    08/11/2026, vu en jeu juste après une victoire : `_pick_champion` a
    été appelé alors que l'écran affichait encore la LISTE DES DÉFIS.

    Le titre « DÉFI N » n'y est pas — il est dans le panneau de l'écran
    du champion. Lecture nulle, donc « palier illisible », donc « on
    prend le plus étoilé »... et tout le parcours de grille s'est
    déroulé sur la liste des défis, **molette comprise, qui fait
    défiler cette liste**. Cinq « rien de jouable », un faux « bas de
    liste atteint » après un seul bond, puis le repli `first_champion`
    qui a cherché dans le vide.

    Rien n'a été consommé ce jour-là parce que le repli n'a rien
    trouvé. S'il avait trouvé, un 7 ★ partait sur un palier qui en
    demande 4 — exactement ce que la table d'allocation existe pour
    éviter.

    LE SIGNE EST SIMPLE : une grille de champions montre des vignettes,
    fût-ce des épuisées ; un autre écran n'en montre AUCUNE. On le
    vérifie AVANT de toucher la molette.
    """
    print(chr(10) + "Un écran sans la moindre vignette n'est pas la grille")

    import click_utils
    vrai_capture = champions._capture_garee
    vrai_palier = champions.attendre_palier
    vrai_defiler, vrai_remonter = champions._defiler, champions._remonter
    vrai_clic = click_utils.safe_click
    try:
        # `choisir_champion` CLIQUE la vignette retenue — et il l'importe
        # depuis `click_utils` à l'appel, donc c'est là qu'on bouchonne.
        # Sans ça, la branche (b) déplaçait vraiment la souris 42 fois et
        # cliquait une vignette sur l'écran d'Ewan ; le garde-machine de
        # `check.py` l'a dit dans la minute, le jour même où il est né.
        click_utils.safe_click = lambda *a, **k: True
        champions.attendre_palier = lambda **k: None      # palier illisible
        gestes = []
        champions._defiler = lambda crans=0: (gestes.append("bas"), True)[1]
        champions._remonter = lambda crans=0: (gestes.append("haut"), True)[1]

        # (a) un écran qui n'est pas la grille : aucune vignette.
        autre = _lire(PAS_LA_GRILLE)
        if autre is not None:
            champions._capture_garee = lambda: autre
            check("aucune vignette lue sur cet écran",
                  champions.lire_vignettes(autre) == [], champions.lire_vignettes(autre))
            # `attente=0` : un écran inconnu a droit à quelques secondes
            # pour ARRIVER (l'écran du champion met plusieurs secondes
            # après le clic sur le défi), et une suite hors ligne n'a pas
            # à les subir. Un seul coup d'œil suffit ici.
            check("choisir_champion refuse",
                  champions.choisir_champion(attente=0.0) is False)
            check("   et la molette n'a PAS été touchée", gestes == [], gestes)

        # (b) une vraie grille, toutes vignettes épuisées : on ne refuse
        #     PAS d'avance, on parcourt — c'est le comportement d'avant,
        #     et la grille peut avoir des jouables ailleurs.
        gestes.clear()
        grille = _lire(BAS)
        if grille is not None:
            champions._capture_garee = lambda: grille
            check("une vraie grille montre des vignettes",
                  len(champions.lire_vignettes(grille)) > 0,
                  len(champions.lire_vignettes(grille)))
            champions.choisir_champion(max_bonds=2)
            check("   et là, on parcourt bien", gestes != [], gestes)
    finally:
        champions._capture_garee = vrai_capture
        champions.attendre_palier = vrai_palier
        champions._defiler, champions._remonter = vrai_defiler, vrai_remonter
        click_utils.safe_click = vrai_clic


def test_la_liste_des_defis_nest_pas_un_palier_illisible():
    """
    08/11/2026, 20:46 — ON A LU LE MAUVAIS ÉCRAN, ET ON EN A CONCLU UN FAIT.

    Juste après une victoire, `_pick_champion` a été appelé alors que
    l'écran affichait encore LA LISTE DES DÉFIS : « DÉFI MENSUEL
    D'AURELION SOL », « ENCORE 22 JOURS », DÉFI 22 / 23 / 24. La capture
    gardée ce jour-là est `captures_reference/liste_defis_20261108.png`.

    Le titre « DÉFI N » n'y est pas — il vit dans le panneau de l'écran
    du champion. Mesuré sur cette capture : la zone du titre rend 79×270
    et **zéro boîte**. `attendre_palier` a donc tourné ses secondes sur
    un écran où le titre N'EXISTE PAS, puis a conclu « palier illisible :
    on prend le plus étoilé » — alors que la règle du projet (« un
    chiffre absent rend None, jamais une valeur approchée ») suppose
    qu'on regarde le BON écran. Le code ne distinguait pas « le panneau
    n'est pas affiché » de « ce chiffre, je ne le connais pas ».

    La suite a coûté ~75 s et un essai d'entrée : molette sur la LISTE
    (qui défile), faux « bas de liste atteint » en un bond, six « rien de
    jouable », puis `first_champion` cherché dans le vide.

    CE QU'ON MESURE POUR TRANCHER, sur les captures déjà gardées :

        capture                            vignettes  first_champion  active_encounter
        champions_haut_20261105                6          1.000            0.386
        champions_bas_20261105                 6          0.985            0.286
        champions_selection_20261105           6          0.978            0.304
        champions_defi19_20261108 (défilée)    6          0.641            0.329
        liste_defis_20261108                   0          0.502            0.957

    Les vignettes séparent 6 contre 0 ; `first_champion` ne suffit PAS
    seul (0.641 sur une grille défilée, pour un seuil de 0.80) mais ne
    monte jamais à 0.80 ailleurs. Et la liste se DÉNONCE : son propre
    repère d'écran note 0.957, contre ≤ 0.422 sur les quatre grilles.
    """
    print(chr(10) + "La liste des défis n'est pas une grille au palier illisible")
    liste = _lire(CAPTURES / "liste_defis_20261108.png")
    if liste is None:
        return

    # Un `best_match` coûte 0,4 s sur une capture 1920×1080 : on lit une
    # fois et on juge sur la valeur, plutôt que de rappeler la fonction
    # dans le détail du check.
    lu = champions.sur_la_grille(liste)
    check("la liste des défis n'est PAS la grille des champions", lu is False, lu)
    for nom in ("champions_haut_20261105.png", "champions_bas_20261105.png",
                "champions_selection_20261105.png", "champions_defi19_20261108.png"):
        grille = _lire(CAPTURES / nom)
        if grille is None:
            continue
        lu = champions.sur_la_grille(grille)
        check("   %s EST la grille" % nom[:34], lu is True, lu)
        vu = champions.autre_ecran(grille)
        check("   et aucun autre écran n'y est reconnu", vu is None, vu)
    vu = champions.autre_ecran(liste)
    check("la liste, elle, se dénonce par son propre repère",
          vu == "active_encounter", vu)

    # ET SURTOUT : on ne conclut RIEN sur le palier quand ce n'est pas
    # la grille. Pas même « illisible » — on rend la main.
    import click_utils
    sauve = (champions._capture_garee, champions.attendre_palier,
             champions._defiler, champions._remonter, click_utils.safe_click)
    gestes, paliers = [], []
    try:
        champions._capture_garee = lambda: liste
        champions.attendre_palier = lambda *a, **k: paliers.append("lu")
        champions._defiler = lambda crans=0: (gestes.append("bas"), True)[1]
        champions._remonter = lambda crans=0: (gestes.append("haut"), True)[1]
        click_utils.safe_click = lambda *a, **k: (gestes.append("clic"), True)[1]

        check("choisir_champion rend la main", champions.choisir_champion() is False)
        check("   sans toucher la molette ni cliquer", gestes == [], gestes)
        check("   et sans même interroger le palier", paliers == [], paliers)

        # Le repli de navigate remonte la grille AVANT de chercher
        # `first_champion` : sur la liste des défis, ce geste faisait
        # défiler LA LISTE. 220 coups de molette le 08/11.
        remonte = champions.revenir_en_haut()
        check("revenir_en_haut refuse aussi de défiler la liste",
              remonte is False, remonte)
        check("   toujours aucune molette", gestes == [], gestes)
    finally:
        (champions._capture_garee, champions.attendre_palier, champions._defiler,
         champions._remonter, click_utils.safe_click) = sauve


def test_une_jouable_vue_en_chemin_nest_pas_jetee():
    """
    08/11/2026 — LE REPLI S'EFFONDRE EN CASCADE, et il jette ce qu'il a vu.

    Sans palier, la cible est None, donc le parcours DESCEND au bas de la
    liste (où sont les plus forts) — et là, tous sont ÉPUISÉS (trois
    tentatives par champion et par mois). « aucune vignette jouable
    lue », puis le dernier filet `first_champion` échoue à son tour : en
    pratique, AUCUN choix. Or le bot AVAIT lu des vignettes jouables en
    chemin.

    Le même trou se referme sur la cible : quand personne n'atteint la
    cible, `_le_plus_faible_qui_suffit` repartait pour un tour de
    `_le_plus_fort`, qui ne regarde que le BAS de la liste — alors que la
    descente venait de lire toute la grille.

    ON RETIENT DONC LA MEILLEURE JOUABLE VUE EN CHEMIN, ET SA HAUTEUR.
    Les deux règles mesurées du 05/11 tiennent :
      - ON NE CLIQUE JAMAIS UNE POSITION MÉMORISÉE : on revient à la
        hauteur où on l'a vue, puis on RELIT et on choisit sur l'écran
        qu'on a sous les yeux (la retrouver par gabarit, essayé le
        05/11, notait 0.51 pour un seuil de 0.90) ;
      - à étoiles égales, la PLUS BASSE de la liste — la grille est
        triée en ordre croissant, donc c'est le plus haut niveau.
    """
    print(chr(10) + "Une vignette jouable vue en chemin n'est pas jetée")

    def tuile(etoiles, rang, epuisee=False):
        return champions.Vignette(etoiles=etoiles, x=100 * rang, y=500,
                                  epuisee=epuisee, clic=(100 * rang, 400))

    # Personne de JOUABLE n'atteint 5 : les forts du bas sont épuisés.
    ecrans = [
        [tuile(3, 1), tuile(3, 2), tuile(4, 3, epuisee=True)],
        [tuile(4, 4), tuile(5, 5, epuisee=True), tuile(5, 6, epuisee=True)],
        [tuile(7, 7, epuisee=True), tuile(7, 8, epuisee=True)],
    ]
    check("le bas de la liste ne propose rien de jouable",
          champions.meilleure(ecrans[-1]) is None, champions.meilleure(ecrans[-1]))

    choisi, position = _parcours_bouchonne(ecrans, cible=5)
    check("un champion est quand même retenu", choisi is not None, choisi)
    if choisi is None:
        return
    check("c'est la meilleure JOUABLE vue en chemin : 4 étoiles",
          choisi.etoiles == 4, choisi.etoiles)
    check("on est revenu à la hauteur où on l'avait vue", position[0] == 1, position[0])
    check("et on a cliqué ce qu'on venait d'y RELIRE",
          choisi is ecrans[1][0], choisi.clic)

    # À ÉTOILES ÉGALES, LA PLUS BASSE DE LA LISTE (le plus haut niveau).
    ecrans2 = [
        [tuile(4, 1)],                       # même force, mais plus haut
        [tuile(4, 2)],                       # la bonne : plus bas
        [tuile(7, 3, epuisee=True)],
    ]
    choisi, _ = _parcours_bouchonne(ecrans2, cible=6)
    check("à étoiles égales, celle d'en BAS (le plus haut niveau)",
          choisi is not None and choisi is ecrans2[1][0],
          None if choisi is None else choisi.clic)


def test_la_transition_nest_pas_un_mauvais_ecran():
    """
    08/11/2026, relecture — LE GARDE PEUT SE TROMPER DANS L'AUTRE SENS.

    `_pick_champion` est appelé JUSTE APRÈS le clic sur le défi, et
    l'écran d'avant est LA LISTE DES DÉFIS — c'est-à-dire précisément un
    membre d'`AUTRES_ECRANS`. Un garde qui conclut sur UNE image rend
    donc la main pendant la transition normale, et `_pick_champion`
    retombe alors sur `first_champion`, le HAUT de la grille : le PIRE
    champion du compte. C'est l'erreur exacte que ce fichier existe pour
    empêcher (Shen 1 ★, 0/20 PV le 04/11/2026).

    MESURÉ DANS LES JOURNAUX des 05, 06 et 08/11 : sur les sept
    transitions où le palier a été lu, « Palier N » tombe 2,05 à 2,28 s
    après le clic sur le défi — donc le premier coup d'œil (~1,5 s)
    voyait déjà la grille. Rien ne garantit ce 1,5 s, et se tromper ici
    est silencieux. On exige donc de REVOIR l'autre écran.

    Les deux sens tiennent, et c'est tout l'objet de ce test :
      - la liste qui laisse la place à la grille = une transition ;
      - la liste qui reste = le mauvais écran, on rend la main.

    09/11/2026 — ET LA VALEUR ELLE-MÊME EST VÉRIFIÉE. Ce test ne bornait
    `CONFIRMATIONS_AUTRE_ECRAN` que PAR LE BAS : il passait avec 2 comme
    avec 99, puisque (a) sort par la grille et (b) finit de toute façon
    par le délai d'attente. Les deux bords existent pourtant, et ils se
    calculent :

      - PAR LE BAS, c'est un fait de comportement : à 1, la transition
        normale (liste puis grille) est coupée — le test le joue ;
      - PAR LE HAUT, c'est une arithmétique : chaque confirmation de
        plus coûte un coup d'œil entier, et le garde ne sert à rien s'il
        ne conclut pas AVANT `ATTENTE_ECRAN_CHAMPION` (20 s), le délai
        qu'il existe précisément pour ne pas user. Mesuré ici sur la
        capture du mauvais écran : reconnaissance ~0,16 s, plus
        `POSE_AVANT_CAPTURE` (0,5 s) et `INTERVALLE_PALIER` (0,8 s) —
        soit **~1,5 s par confirmation supplémentaire** (le commentaire
        de `champions.py` disait ~1,3 s, sans compter la
        reconnaissance). La fenêtre praticable est donc 2 à 14 ; on
        prend 2, le minimum qui laisse passer la transition, parce
        qu'au-delà rien de mesuré ne s'achète.
    """
    print(chr(10) + "La liste vue une seule fois n'est qu'une transition")
    liste = _lire(CAPTURES / "liste_defis_20261108.png")
    grille = _lire(HAUT)
    if liste is None or grille is None:
        return

    sauve = champions._capture_garee
    try:
        # (a) LA TRANSITION : la liste au premier coup d'œil, la grille
        #     au second. C'est le chemin NORMAL depuis Screen.LIST.
        suite = [liste, grille]
        champions._capture_garee = lambda: suite.pop(0) if suite else grille
        check("une liste suivie de la grille N'EST PAS un mauvais écran",
              champions.attendre_la_grille(timeout=10.0) is True)

        # (b) LE VRAI MAUVAIS ÉCRAN : la liste ne s'en va pas.
        champions._capture_garee = lambda: liste
        check("une liste qui reste, elle, fait rendre la main",
              champions.attendre_la_grille(timeout=10.0) is False)

        # (c) LA VALEUR CHOISIE, ET SON PRIX.
        #
        # PAR LE BAS : une seule confirmation coupe la transition (a).
        exige = champions.CONFIRMATIONS_AUTRE_ECRAN
        try:
            champions.CONFIRMATIONS_AUTRE_ECRAN = 1
            suite = [liste, grille]
            champions._capture_garee = lambda: suite.pop(0) if suite else grille
            check("à UNE confirmation, la transition serait coupée",
                  champions.attendre_la_grille(timeout=10.0) is False)
        finally:
            champions.CONFIRMATIONS_AUTRE_ECRAN = exige
        check("donc le plancher est 2", exige >= 2, exige)

        # PAR LE HAUT : le prix se mesure. Un coup d'œil, c'est la pose
        # du curseur plus la reconnaissance ; entre deux coups d'œil il
        # y a l'intervalle.
        champions.sur_la_grille(liste); champions.autre_ecran(liste)   # chauffe
        depart = time.perf_counter()
        champions.sur_la_grille(liste)
        champions.autre_ecran(liste)
        reco = time.perf_counter() - depart
        oeil = champions.POSE_AVANT_CAPTURE + reco

        def cout(n):
            return n * oeil + (n - 1) * champions.INTERVALLE_PALIER

        supplement = cout(2) - cout(1)
        check("une confirmation de plus coûte ~1,5 s (mesuré %.2f s : pose "
              "%.1f + reconnaissance %.2f + intervalle %.1f)"
              % (supplement, champions.POSE_AVANT_CAPTURE, reco,
                 champions.INTERVALLE_PALIER),
              1.0 <= supplement <= 2.5, supplement)
        # Un garde qui conclurait APRÈS le délai d'attente ne servirait
        # à rien : on serait revenu au 08/11 — 20 s d'attente, puis tout
        # le parcours sur le mauvais écran.
        plafond = 1
        while cout(plafond + 1) < champions.ATTENTE_ECRAN_CHAMPION:
            plafond += 1
        check("le garde conclut en %.1f s, bien avant les %.0f s qu'il évite "
              "(plafond praticable : %d confirmations)"
              % (cout(exige), champions.ATTENTE_ECRAN_CHAMPION, plafond),
              cout(exige) < champions.ATTENTE_ECRAN_CHAMPION, cout(exige))
        check("et la valeur retenue est bien 2 — le minimum qui laisse "
              "passer la transition", exige == 2, exige)
    finally:
        champions._capture_garee = sauve


def test_une_capture_trop_petite_ne_fait_pas_planter_la_lecture():
    """
    08/11/2026, relecture — `lire_vignettes` LÈVE sur une capture étroite.

    Les repères du bandeau « TENTATIVES ÉPUISÉES » sont des RATIOS de la
    largeur : sur une capture plus étroite que 1920 la bande rétrécit,
    le gabarit garde ses 280×40, et `cv2.matchTemplate` lève (-215) au
    lieu de rendre un score. Mesuré en rejouant les 935 captures de
    `screenshots/` : une seule plante, `diag_scroll_apres.png`
    (1113×767) — mais depuis le 08/11 cette lecture est atteinte par
    `sur_la_grille`, donc par N'IMPORTE QUEL écran, et plus seulement
    par la grille. L'exception traversait `attendre_la_grille` et
    `revenir_en_haut` ; `navigate._pick_champion` l'attrape, mais au
    prix du repli `first_champion` — le pire champion du compte.

    La réponse juste était déjà écrite dans la fonction : « on ne voit
    pas le bandeau en entier » → on ne juge pas cette vignette.
    """
    print(chr(10) + "Une capture trop étroite ne fait pas planter la lecture")
    grille = _lire(HAUT)
    if grille is None:
        return
    # UN RECADRAGE, PAS UN REDIMENSIONNEMENT : réduire l'image réduit
    # aussi les étoiles sous les 20 px de `GLYPHE_MIN`, donc aucune
    # vignette n'est lue et le défaut ne se montre pas. Recadrer garde
    # les glyphes à leur taille — c'est la forme exacte des captures de
    # diagnostic du projet (`diag_scroll_apres.png`, 1113×767).
    # Mesuré ici : 1200×900 suffit à faire tomber la bande du bandeau
    # (141 px de large) sous les 280 px du gabarit.
    etroite = grille[:900, :1200].copy()
    try:
        vues = champions.lire_vignettes(etroite)
        check("lire_vignettes rend une liste au lieu de lever", isinstance(vues, list))
    except Exception as exc:                            # noqa: BLE001
        check("lire_vignettes rend une liste au lieu de lever", False,
              "%s: %s" % (type(exc).__name__, exc))
        return
    try:
        check("et sur_la_grille sait répondre dessus",
              champions.sur_la_grille(etroite) in (True, False))
    except Exception as exc:                            # noqa: BLE001
        check("et sur_la_grille sait répondre dessus", False,
              "%s: %s" % (type(exc).__name__, exc))

    # La pleine résolution, elle, n'a pas bougé : six vignettes.
    check("la grille 1920×1080 se lit toujours à six vignettes",
          len(champions.lire_vignettes(grille)) == 6,
          len(champions.lire_vignettes(grille)))


def test_deux_ecrans_differents_ne_se_confirment_pas():
    """
    09/11/2026 — LE GARDE DIT « VU 2 FOIS DE SUITE » UN ÉCRAN VU UNE FOIS.

    `attendre_la_grille` exige de REVOIR l'autre écran avant de rendre la
    main (CONFIRMATIONS_AUTRE_ECRAN, 08/11) : une liste qui laisse la
    place à la grille entre deux coups d'œil n'est qu'une transition. Mais
    le compteur comptait « un écran d'entrée a été reconnu », pas « LE
    MÊME écran a été reconnu » — il survivait à un changement de nom.

    Ce n'est pas théorique : les deux écrans traversés juste avant la
    grille sont justement deux membres différents d'`AUTRES_ECRANS`, et
    les captures gardées le mesurent.

        capture                             active_encounter  reprendre_aventure
        liste_defis_20261108                     0.957              0.232
        reprendre_aventure_20261106              0.293              1.000

    Cliquer un défi déjà commencé enchaîne donc LISTE puis PANNEAU DE
    REPRISE : deux noms, un seul coup d'œil chacun, et le garde
    concluait — en journalisant « « reprendre_aventure » est à l'écran,
    vu 2 fois de suite » alors que cet écran venait d'apparaître.

    UN MESSAGE FAUX DANS UN GARDE-FOU EST PIRE QUE PAS DE MESSAGE : c'est
    la ligne de log qu'on relira pour comprendre pourquoi le choix du
    champion a été abandonné, et elle désigne le mauvais coupable. Le
    compteur repart donc à 1 quand le nom change.
    """
    print(chr(10) + "Deux écrans différents ne se confirment pas l'un l'autre")
    liste = _lire(CAPTURES / "liste_defis_20261108.png")
    reprise = _lire(CAPTURES / "reprendre_aventure_20261106.png")
    if liste is None or reprise is None:
        return

    def _joue(suite):
        """Déroule `attendre_la_grille` sur cette suite de captures."""
        vus, avertis = [], []

        class _Mouchard(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    avertis.append(record.args)

        mouchard = _Mouchard()
        logging.getLogger().addHandler(mouchard)
        sauve = champions._capture_garee
        try:
            def capture():
                ecran = suite[min(len(vus), len(suite) - 1)]
                vus.append(champions.autre_ecran(ecran))
                return ecran
            champions._capture_garee = capture
            rendu = champions.attendre_la_grille(timeout=10.0, intervalle=0.0)
        finally:
            champions._capture_garee = sauve
            logging.getLogger().removeHandler(mouchard)
        return rendu, vus, avertis

    # (a) LA LISTE PUIS LE PANNEAU DE REPRISE : deux noms, un seul
    #     coup d'œil chacun. On ne conclut pas là-dessus.
    rendu, vus, avertis = _joue([liste, reprise, reprise])
    check("deux écrans DIFFÉRENTS ne valent pas une confirmation",
          len(vus) == 3, vus)
    check("   on rend bien la main une fois le second REVU", rendu is False, rendu)
    nomme = [a for a in avertis
             if a and len(a) == 2 and a[1] == champions.CONFIRMATIONS_AUTRE_ECRAN]
    check("   et le WARNING nomme l'écran vraiment revu",
          bool(nomme) and nomme[0][0] == "reprendre_aventure", nomme)
    if nomme:
        combien = nomme[0][1]
        check("   « vu %d fois de suite » est VRAI : les %d derniers coups "
              "d'oeil montrent bien cet écran" % (combien, combien),
              vus[-combien:] == [nomme[0][0]] * combien, vus)

    # (b) LE MÊME ÉCRAN DEUX FOIS : rien ne change, on conclut au second.
    rendu, vus, avertis = _joue([liste, liste, liste])
    check("le même écran deux fois fait toujours rendre la main",
          rendu is False and len(vus) == champions.CONFIRMATIONS_AUTRE_ECRAN,
          (rendu, vus))
    check("   et c'est bien lui qui est nommé",
          any(a[0] == "active_encounter" for a in avertis if a), avertis)


def _glyphe_etire(image, lignes=5):
    """
    La même grille, à `lignes` pixels près sur UN SEUL glyphe d'étoile.

    On recopie la dernière ligne du glyphe vers le bas : la forme grandit
    d'un cheveu, exactement comme la surbrillance d'une vignette fait
    « grossir » ses étoiles au masque (141-156 au repos, 229-233
    sélectionnée — mesuré le 05/11/2026). Rend None si aucun glyphe n'est
    trouvé, pour que le test s'ignore plutôt que de mentir.
    """
    masque = champions._masque_orange(image)
    nombre, _, stats, centres = cv2.connectedComponentsWithStats(masque, 8)
    colonne = champions.COLONNES[0] * image.shape[1]
    for i in range(1, nombre):
        w = int(stats[i][cv2.CC_STAT_WIDTH]); h = int(stats[i][cv2.CC_STAT_HEIGHT])
        aire = int(stats[i][cv2.CC_STAT_AREA])
        if not (champions.AIRE_MIN <= aire <= champions.AIRE_MAX
                and champions.GLYPHE_MIN <= w <= champions.GLYPHE_MAX
                and champions.GLYPHE_MIN <= h <= champions.GLYPHE_MAX):
            continue
        if abs(centres[i][0] - colonne) > champions.TOLERANCE_X * image.shape[1]:
            continue
        x, y = int(stats[i][0]), int(stats[i][1])
        copie = image.copy()
        derniere = image[y + h - 1:y + h, x:x + w].copy()
        for j in range(lignes):
            copie[y + h + j:y + h + j + 1, x:x + w] = derniere
        return copie
    return None


def test_le_bas_de_liste_se_juge_comme_dans__parcourir():
    """
    09/11/2026 — DEUX CRITÈRES POUR LA MÊME QUESTION, ET ILS DIVERGENT.

    « La liste a-t-elle cessé de bouger ? » se posait de deux façons :

      - `_parcourir` compare les PIXELS de la zone de grille, avec une
        tolérance (`_memes` : moyenne des écarts < 1.0) ;
      - `_le_plus_faible_qui_suffit` comparait les VIGNETTES LUES, par
        ÉGALITÉ EXACTE de namedtuples — étoiles, x, y, épuisée, clic.

    MESURÉ sur `champions_haut_20261105.png` (zone de grille 767×1113,
    2 561 013 valeurs) :

      - pour que `_memes` dise « différent », il faut ~3 348 pixels
        saturés, soit 0,4 % de la zone ;
      - 110 pixels (0,013 %) suffisent à changer la liste lue. En
        recopiant cinq lignes sous UN SEUL glyphe d'étoile — ce que fait
        la surbrillance d'une vignette, qui porte son aire de 141-156 à
        229-233 — l'écart moyen vaut **0.0023**, soit **430 fois sous le
        seuil de `_memes`**, et pourtant une vignette disparaît de la
        lecture.

    CE QUE ÇA COÛTE : au bas de la liste, la molette ne déplace plus
    rien, mais la lecture bouge encore. L'ancien critère ne voyait donc
    pas le bout, continuait de compter `hauteur += 1` pour des rangées
    QUI N'EXISTENT PAS, et `_sur_nos_pas_ou_le_plus_fort` remontait
    d'autant trop haut — il relisait un autre écran que celui qu'il
    visait. C'est exactement le défaut que le `hauteur -= 1` du 08/11
    avait été écrit pour éviter, et que le critère laissait entrer par la
    porte d'à côté.

    UN SEUL CRITÈRE DÉSORMAIS : `champions._liste_immobile`, appelé par
    les deux.
    """
    print(chr(10) + "Le bas de liste se juge d'une seule façon")
    image = _lire(HAUT)
    if image is None:
        return

    # (1) LA DIVERGENCE, SUR LA VRAIE CAPTURE.
    bruitee = _glyphe_etire(image)
    if bruitee is None:
        print("  (ignoré : aucun glyphe d'étoile isolé sur cette capture)")
    else:
        zone, zone2 = champions._zone_grille(image), champions._zone_grille(bruitee)
        moyenne = float(np.mean(cv2.absdiff(zone, zone2)))
        pixels = int((cv2.absdiff(image, bruitee).sum(axis=2) > 0).sum())
        avant, apres = champions.lire_vignettes(image), champions.lire_vignettes(bruitee)
        check("%d pixels modifiés : l'écran est le MÊME au pixel près "
              "(écart moyen %.4f)" % (pixels, moyenne),
              champions._memes(zone, zone2) is True, moyenne)
        check("   mais la liste des vignettes, elle, a changé",
              apres != avant, (len(avant), len(apres)))
        check("   et le critère unique tranche comme `_parcourir`",
              champions._liste_immobile(zone, zone2) is True)

    # (2) CE QUE ÇA CHANGE AU PARCOURS : la gigue de lecture ne doit plus
    #     faire compter des rangées qui n'existent pas.
    def tuile(etoiles, rang, epuisee=False):
        return champions.Vignette(etoiles=etoiles, x=100 * rang, y=500,
                                  epuisee=epuisee, clic=(100 * rang, 400))

    ecrans = [[tuile(3, 1)], [tuile(4, 2)], [tuile(7, 3, epuisee=True)]]
    choisi, position = _parcours_bouchonne(ecrans, cible=6, gigue=True)
    check("au bas de la liste, une lecture qui gigue n'empêche plus de "
          "voir le bout", choisi is not None and choisi.etoiles == 4,
          None if choisi is None else choisi.etoiles)
    check("   on revient donc à la bonne hauteur (la rangée 1, pas la 0)",
          position[0] == 1, position[0])


def _parcours_bouchonne(ecrans, cible, max_bonds=6, gigue=False):
    """
    `_le_plus_faible_qui_suffit` sur une grille de papier.

    La molette est remplacée par un index d'écran : ni souris, ni
    capture, ni fenêtre du jeu.

    LA DESCENTE S'ARRÊTE AU BAS DE LA LISTE, comme en vrai : une molette
    poussée au-delà du dernier écran ne déplace plus rien. C'est ce qui
    rend la HAUTEUR du carnet honnête — sans ça, le code compterait des
    rangées qu'il n'a pas parcourues et remonterait trop haut.

    LA GRILLE DE PAPIER A DES PIXELS (09/11/2026) : « le bout de la
    liste » se juge par `champions._liste_immobile`, c'est-à-dire sur
    l'image, le même critère que `_parcourir`. Une image constante par
    rangée suffit — deux rangées voisines diffèrent de 10 niveaux, bien
    au-dessus du seuil de 1.0, et la même image qui revient dit « la
    molette ne déplace plus rien ».

    `gigue=True` fait bouger la LECTURE d'un pixel à chaque appel sans
    toucher aux pixels : c'est le cas mesuré où les deux critères
    divergeaient.
    """
    position, lectures = [0], [0]
    images = [np.full((100, 100, 3), 10 * (i + 1), dtype=np.uint8)
              for i in range(len(ecrans))]

    def _vues(_=None):
        vues = ecrans[min(position[0], len(ecrans) - 1)]
        if not gigue:
            return vues
        lectures[0] += 1
        return [v._replace(y=v.y + lectures[0]) for v in vues]

    sauve = (champions._capture_garee, champions.lire_vignettes,
             champions._defiler, champions._remonter, champions._parcourir)
    champions._capture_garee = lambda: images[min(position[0], len(ecrans) - 1)]
    champions.lire_vignettes = _vues
    champions._defiler = lambda crans=None: position.__setitem__(
        0, min(position[0] + 1, len(ecrans) - 1))
    champions._remonter = lambda crans=None: position.__setitem__(0, max(0, position[0] - 1))
    champions._parcourir = lambda *a, **k: position.__setitem__(0, 0)
    try:
        return champions._le_plus_faible_qui_suffit(cible, max_bonds), position
    finally:
        (champions._capture_garee, champions.lire_vignettes, champions._defiler,
         champions._remonter, champions._parcourir) = sauve


def test_un_palier_illisible_sur_la_grille_laisse_une_image():
    """
    11/11/2026, 13:09:27 — « PALIER ILLISIBLE », ET PAS UNE IMAGE.

        13:09:27  Palier illisible alors que la grille EST affichée
                  (police incomplète) : on prend le plus étoilé.

    Le journal confirme le prix : `palier: null, etoiles: 7` — un 7 ★
    engagé là où `etoiles_requises(25)` demande 4 ★, sur un quota de
    trois tentatives par champion et par mois.

    ET LE MESSAGE AFFIRMAIT CE QU'IL NE SAVAIT PAS. Le palier était 25
    (le 24 a été gagné la veille) et **le 2 comme le 5 sont dans
    `chiffres/N_defi.png`** — le 5 y a même été récolté le 10/11 et
    relu tout seul dans un vrai titre le soir même. « Police
    incomplète » est donc une CAUSE SUPPOSÉE, et personne ne pourra la
    confirmer ni la démentir : aucune image n'a été gardée.

    C'est le manque du 08/11 à l'identique (« combat sans effet ») :
    LA CAPTURE EST LE VRAI LIVRABLE. On garde donc l'écran, et on dit
    ce que la lecture a VU — combien de boîtes dans la bande du titre,
    et pour chacune le meilleur chiffre avec son score et sa marge,
    au barème de `digits.match_glyph`.
    """
    print(chr(10) + "Palier illisible sur la grille : on garde l'écran et on dit ce qu'on a vu")

    import click_utils

    # (a) LE DIAGNOSTIC EST PUR : une image en entrée, des lignes en
    #     sortie. Il ne touche ni la souris ni le disque — c'est ce qui
    #     permet de le vérifier ici sans photographier quoi que ce soit.
    titre = _lire(DEFI19)
    if titre is not None:
        lignes = champions._diagnostic_du_titre(titre)
        texte = chr(10).join(lignes)
        check("le diagnostic rend des lignes", len(lignes) >= 2, lignes)
        check("il compte les boîtes de la bande du titre",
              "boîte" in texte, texte)
        # « DÉFI 19 » : deux glyphes de nombre, et la police les connaît.
        check("il note un score pour chaque glyphe du nombre",
              texte.count("score") >= 2, texte)
        check("   et la marge avec", "marge" in texte, texte)
        check("   le palier de cette capture se lit bien, lui",
              champions.lire_palier(titre) == 19, champions.lire_palier(titre))

    liste = _lire(LISTE)
    if liste is not None:
        lignes = champions._diagnostic_du_titre(liste)
        # La liste des défis n'a pas de titre « DÉFI N » : zéro boîte.
        # Le diagnostic doit le DIRE, pas se taire.
        check("sur un écran sans titre, il le dit au lieu de se taire",
              lignes and "0 boîte" in chr(10).join(lignes), lignes)

    # ZÉRO BOÎTE ET DES BOÎTES DÉPAREILLÉES SONT DEUX PANNES. Le décor
    # du 06/11 passe le seuil de clarté puis se fait refuser par le
    # garde-fou de hauteur : si ce garde venait un jour à écarter un
    # VRAI titre, c'est la seule ligne qui le dirait.
    # Seule capture du dossier où le lot passe le filtre de TAILLE puis
    # se fait refuser sur la HAUTEUR : deux boîtes de 12 et 26 px.
    decor = _lire(CAPTURES / "marqueur_comparaison_20261108.png")
    if decor is not None:
        check("   le garde-fou de hauteur refuse bien ce lot-là",
              champions._glyphes_du_titre(decor)[1] == [],
              champions._glyphes_du_titre(decor)[1])
        texte = chr(10).join(champions._diagnostic_du_titre(decor))
        check("un lot dépareillé est nommé comme tel, pas compté zéro",
              "REFUSÉ par le garde-fou de hauteur" in texte, texte)
        check("   et ses deux boîtes sont montrées",
              "2 boîte(s)" in texte, texte)

    # (b) LA GRILLE EST LÀ, LE PALIER NE SE LIT PAS : on photographie.
    grille = _lire(BAS)
    if grille is None:
        return
    sauve = (champions._capture_garee, champions.attendre_palier,
             champions._defiler, champions._remonter, click_utils.safe_click)
    try:
        click_utils.safe_click = lambda *a, **k: True
        champions._capture_garee = lambda: grille
        champions._defiler = lambda crans=0: True
        champions._remonter = lambda crans=0: True

        PALIERS_ILLISIBLES.clear()
        champions.attendre_palier = lambda **k: None
        clique = champions.choisir_champion(max_bonds=2)
        check("l'écran est gardé une fois, et une seule",
              len(PALIERS_ILLISIBLES) == 1, len(PALIERS_ILLISIBLES))
        # LE REPLI NE CHANGE PAS. On ajoute un diagnostic, pas une
        # décision de jeu : sans palier, on prend toujours le plus
        # étoilé encore jouable.
        check("   et le repli reste celui d'avant : on a cliqué", clique is True)
        check("   sur le plus étoilé jouable (7 ★)",
              champions.DERNIER_CHOIX is not None
              and champions.DERNIER_CHOIX.etoiles == 7, champions.DERNIER_CHOIX)

        # (c) PALIER LU : rien à diagnostiquer, rien à photographier.
        PALIERS_ILLISIBLES.clear()
        champions.attendre_palier = lambda **k: 25
        champions.choisir_champion(max_bonds=2)
        check("palier lu : aucune capture demandée",
              PALIERS_ILLISIBLES == [], PALIERS_ILLISIBLES)
        check("   et la cible vient bien de la table (25 → 4 ★)",
              champions.etoiles_requises(25) == 4, champions.etoiles_requises(25))
    finally:
        (champions._capture_garee, champions.attendre_palier, champions._defiler,
         champions._remonter, click_utils.safe_click) = sauve


def test_la_suite_necrit_rien_dans_screenshots():
    """
    « NE TOUCHE PAS LA MACHINE » ET « NE LAISSE RIEN DERRIÈRE SOI » SONT
    DEUX PROPRIÉTÉS DIFFÉRENTES (leçon du 09/11/2026, `test_combat`).

    `journaliser_palier_illisible` est le SEPTIÈME guet du projet
    capable de photographier l'écran d'Ewan, et le second à écrire un
    PNG. Les six premiers ont tous fini par le faire pour de bon. Ce
    test vérifie que le bouchon posé à l'import tient encore à la fin
    de la suite — un test qui remplacerait la fonction sans la rendre
    le ferait sauter en silence.
    """
    print(chr(10) + "La suite ne photographie rien et n'écrit rien dans screenshots/")
    check("le guet est toujours bouchonné",
          champions.journaliser_palier_illisible.__name__ == "<lambda>",
          champions.journaliser_palier_illisible)
    nouveaux = sorted(p.name for p in (ROOT / "screenshots").glob("palier_illisible_*.png")
                      if p.stat().st_mtime >= _DEBUT)
    check("aucun palier_illisible_*.png écrit par la suite",
          nouveaux == [], nouveaux)


def main():
    for test in (test_le_haut_de_la_grille_est_le_plus_faible,
                 test_le_bas_de_la_grille_porte_les_sept_etoiles,
                 test_le_choix_prend_le_plus_etoile_encore_jouable,
                 test_on_prend_la_DERNIERE_de_la_bande,
                 test_une_vignette_selectionnee_reste_lisible,
                 test_le_palier_se_lit_sur_le_titre,
        test_la_police_du_titre_sait_lire_un_palier_a_deux_chiffres,
                 test_le_3_et_le_5_viennent_de_la_liste_des_defis,
                 test_le_decor_n_est_pas_un_titre,
                 test_la_table_garde_les_forts_pour_la_fin,
                 test_une_lecture_douteuse_ne_decide_pas,
                 test_les_bornes_de_vraisemblance,
                 test_une_molette_qui_nest_pas_entendue_nest_pas_un_bout_de_liste,
                 test_le_repli_a_besoin_du_haut_de_la_grille,
                 test_une_grille_sans_vignette_nest_pas_la_grille,
                 test_la_liste_des_defis_nest_pas_un_palier_illisible,
                 test_une_jouable_vue_en_chemin_nest_pas_jetee,
                 test_la_transition_nest_pas_un_mauvais_ecran,
                 test_deux_ecrans_differents_ne_se_confirment_pas,
                 test_le_bas_de_liste_se_juge_comme_dans__parcourir,
                 test_une_capture_trop_petite_ne_fait_pas_planter_la_lecture,
                 test_un_palier_illisible_sur_la_grille_laisse_une_image,
                 test_la_suite_necrit_rien_dans_screenshots):
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
