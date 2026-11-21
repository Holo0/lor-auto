"""
Lecture des mots-clés à l'écran — sur la capture RÉELLE et étiquetée.

La scène du 14/11/2026 est la seule dont on connaisse à la fois les
positions (API) et les mots-clés IMPRIMÉS (`card_sets`) : sept unités,
trois porteuses d'icônes et quatre vierges. C'est donc trois positifs
et quatre négatifs, tous étiquetés par une source indépendante de
l'image.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

import mots_cles_ecran as mce

CAPTURE = Path(__file__).parent / "captures_reference" / "unite_stun_20261114_231607.png"

CAPTURE_20 = (Path(__file__).parent / "captures_reference" / "mots_cles"
              / "scene_20261120_201157.png")

# LES DEUX SCÈNES DU 21/11/2026, étiquetées par Ewan (cf. CLAUDE.md,
# « Le lexique des icônes »). Ce sont les premières où une barre porte
# PLUS DE QUATRE mots-clés : le jeu les tasse alors sur DEUX niveaux en
# quinconce, ce que ni le 14/11 (≤ 5 icônes alignées) ni le 20/11 (4
# alignées) ne pouvaient montrer. Elles portent aussi les premières
# unités ADVERSES dont la barre est garnie.
CAPTURE_KENNEN = (Path(__file__).parent / "captures_reference" / "mots_cles"
                  / "kennen_20261121_034644.png")
CAPTURE_VIKTOR = (Path(__file__).parent / "captures_reference" / "mots_cles"
                  / "victor_20261121_035752.png")

# Les CINQ Pâle orchestre (06SI009) de la même scène
# (`scene_20261120_201157.json`), centres recalculés par
# `lor_api.rect_center_screen` — pas une approximation à l'œil. La même
# carte, posée cinq fois : si le masque se fragmente pareil sur les cinq,
# c'est que le découpage est une propriété du GLYPHE, pas un accident
# d'une seule vignette. Rect écran de la première : x 582-709 / y 820-980.
#
# L'ordre des icônes est un FAIT DE JEU donné par Ewan le 20/11/2026 :
# « chacun des Pâle orchestre a dans l'ordre, de gauche à droite, le mot
# clé éphémère, sanctification, challenger et enfin surpuissance ».
CENTRES_ORCHESTRE = [(645, 900), (802, 900), (959, 900), (1115, 900), (1272, 900)]

# LA DISTINCTION EST STRUCTURELLE, PAS ORTHOGRAPHIQUE (20/11/2026, revue
# finale). Les deux listes ne se distinguaient que par un « S » final, et
# la première était la SOURCE des gabarits : un futur test qui s'en
# servirait pour `identifier()` comparerait un gabarit à son propre
# découpage — 1.0 par construction, qui ne prouve rien. On découpe donc
# la liste unique, et le nom dit à quoi chaque moitié sert.
SOURCES_GABARITS = CENTRES_ORCHESTRE[:2]      # (645, 900) et (802, 900)
AUTRES_ORCHESTRES = CENTRES_ORCHESTRE[2:]     # les trois qui PROUVENT quelque chose

FAILURES: list = []


def check(label, condition, detail=None):
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(label)
        print(f"  ÉCHEC {label}" + ("" if detail is None else f" {detail}"))


class _Carte:
    """Le minimum de BoardCard dont ce module a besoin."""

    def __init__(self, nom, card_id, centre, keywords=(), local=True):
        self.name, self.card_id, self.center = nom, card_id, centre
        self.keywords = tuple(keywords)
        self.keyword_refs = tuple(keywords)
        # LE CÔTÉ DÉCIDE OÙ REGARDER (21/11/2026) : chez l'adversaire la
        # barre est en HAUT de la carte, les statistiques en bas.
        self.local = local


# La scène, étiquetée par `card_sets` — PAS par l'image. Les trois
# dernières sont des unités ADVERSES (y = 180) : leur barre, si elles en
# avaient une, serait en HAUT de leur carte.
SCENE = [
    # nom,                   id,  centre,       imprimés,     à nous ? porte des icônes ?
    ("Swain", 201, (724, 900), ("Fearsome",), True, True),
    ("Enraged Firespitter", 202, (880, 900), ("Challenger",), True, True),
    ("Legion Saboteur", 203, (1037, 900), (), True, True),
    ("Arachnoid Sentry", 204, (1194, 900), (), True, False),
    ("House Spider", 301, (802, 180), (), False, False),
    ("Spiderling", 302, (959, 180), (), False, False),
    ("Imperial Demolitionist", 303, (1115, 180), (), False, False),
]


def _image():
    return cv2.imread(str(CAPTURE))


def test_la_barre_se_lit_la_ou_elle_est():
    """
    TROIS PORTEUSES, QUATRE VIERGES — et aucune confusion.

    C'est le résultat qui porte tout le module : les quatre unités sans
    aucun mot-clé imprimé ne déclenchent RIEN. Un faux positif ici
    rendrait le module inutilisable, puisque son seul verdict est « il y
    a quelque chose ».
    """
    print("\nLa barre d'icônes, sur la capture étiquetée")
    img = _image()
    if img is None:
        check("capture de référence présente", False, CAPTURE)
        return

    for nom, _, centre, _, local, attendu in SCENE:
        lu = mce.porte_des_mots_cles(img, centre, adverse=not local)
        check(f"{nom:<24} porte des icônes={attendu}", lu is attendu,
              f"lu {lu} — {len(mce.icones(img, centre, adverse=not local))} icône(s)")


def test_un_mot_cle_accorde_se_voit():
    """
    LE CAS QUI JUSTIFIE LE MODULE : Legion Saboteur (01NX040) n'a AUCUN
    mot-clé dans `card_sets` et porte pourtant une icône bleue. Elle lui
    a donc été donnée en jeu — exactement ce que l'API ne dit pas.

    Et le miroir : Arachnoid Sentry, vierge elle aussi, n'affiche rien.
    Sans ce second cas, le premier ne prouverait qu'un faux positif.
    """
    print("\nUn mot-clé accordé en jeu se voit")
    img = _image()
    if img is None:
        check("capture de référence présente", False, CAPTURE)
        return

    saboteur = _Carte("Legion Saboteur", 203, (1037, 900), ())
    sentry = _Carte("Arachnoid Sentry", 204, (1194, 900), ())
    swain = _Carte("Swain", 201, (724, 900), ("Fearsome",))

    check("Legion Saboteur a reçu un mot-clé", mce.a_recu_un_mot_cle(img, saboteur))
    check("   Arachnoid Sentry, vierge aussi, n'a rien reçu",
          mce.a_recu_un_mot_cle(img, sentry) is False)
    check("une carte qui a des mots-clés IMPRIMÉS n'est pas jugée ici",
          mce.a_recu_un_mot_cle(img, swain) is False)

    cartes = [_Carte(n, i, c, k, local) for n, i, c, k, local, _ in SCENE]
    check("une seule renforcée sur la scène",
          mce.cartes_renforcees(img, cartes) == {203},
          mce.cartes_renforcees(img, cartes))


def test_les_pistes_naives_sont_ecartees():
    """
    LES DEUX FAUSSES PISTES, GARDÉES COMME CONTRE-ÉPREUVE, parce que ce
    sont celles qu'on aurait prises sans mesurer.
    """
    print("\nPourquoi ni la barre noire ni la teinte ne suffisent")
    import numpy as np
    img = _image()
    if img is None:
        check("capture de référence présente", False, CAPTURE)
        return

    # (a) LA BARRE NOIRE : sa largeur ne compte pas les icônes.
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def plus_long_segment_noir(cx, cy):
        zone = gris[cy + 25:cy + 90, cx - 80:cx + 80] < 42
        best = 0
        for ligne in zone:
            cur = 0
            for v in ligne:
                cur = cur + 1 if v else 0
                best = max(best, cur)
        return best

    saboteur = plus_long_segment_noir(1037, 900)   # UNE icône
    firespitter = plus_long_segment_noir(880, 900)  # DEUX icônes
    check("la barre du porteur d'UNE icône est plus large que celle de DEUX",
          saboteur > firespitter, (saboteur, firespitter))
    check("   et une unité SANS barre garde de l'ombre",
          plus_long_segment_noir(1194, 900) > 25, plus_long_segment_noir(1194, 900))

    # (b) LA TEINTE SANS BORNE VERTICALE : le liseré du plateau sature.
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    colore = ((H >= 8) & (H <= 28) & (S >= 130) & (V >= 120)) | \
             ((H >= 88) & (H <= 112) & (S >= 100) & (V >= 120))
    large = colore[900 + 38:900 + 120, 1194 - 80:1194 + 80].mean() * 100
    serre = colore[900 + mce.BARRE_DY_HAUT:900 + mce.BARRE_DY_BAS,
                   1194 - 80:1194 + 80].mean() * 100
    check("fenêtre trop basse : une unité VIERGE paraît colorée",
          large > 5, large)
    check("   la fenêtre mesurée en garde bien moins", serre < large / 2, (serre, large))
    # ET C'EST LA FORME QUI TRANCHE, PAS LA COULEUR : il reste 2,5 % de
    # pixels colorés épars chez Arachnoid Sentry, et pourtant aucune
    # composante n'a la taille d'une icône. Compter des pixels aurait
    # déclaré un mot-clé ; exiger une forme ne le fait pas.
    check("   et malgré ce reste, aucune icône n'est reconnue",
          mce.icones(img, (1194, 900)) == [], mce.icones(img, (1194, 900)))


def test_une_lecture_impossible_ne_rend_pas_un_verdict():
    """Pas d'image, pas de verdict — et surtout, pas de plantage."""
    print("\nUne lecture impossible ne rend pas un verdict")
    img = _image()
    check("aucune image : aucune icône", mce.icones(None, (724, 900)) == [])
    check("une chaîne : aucune icône", mce.icones("pas une image", (724, 900)) == [])
    check("un entier : aucune icône", mce.icones(42, (724, 900)) == [])
    check("hors écran à gauche : aucune icône", mce.icones(img, (5, 900)) == [])
    check("hors écran en bas : aucune icône", mce.icones(img, (724, 1070)) == [])
    check("pas de mots-clés sans image",
          mce.porte_des_mots_cles(None, (724, 900)) is False)
    check("aucune carte : ensemble vide", mce.cartes_renforcees(img, []) == set())
    check("cartes None : ensemble vide", mce.cartes_renforcees(img, None) == set())

    sans_id = [_Carte("Anonyme", -1, (1037, 900), ())]
    check("une carte sans CardID est ignorée",
          mce.cartes_renforcees(img, sans_id) == set())


def test_le_sablier_magenta_entre_dans_le_masque():
    """
    QUATRE ICÔNES, PAS TROIS. Le masque du 14/11 ne connaissait que
    l'orange et le bleu ; le sablier d'Éphémère est à la teinte 144, donc
    entre les deux. Il manquait, et personne ne pouvait s'en apercevoir —
    le module ne rendait qu'un booléen « il y en a ».
    """
    print("\nLa famille magenta")
    img = cv2.imread(str(CAPTURE_20))
    if img is None:
        check("capture du 20/11 présente", False, CAPTURE_20)
        return
    lues = mce.icones(img, CENTRES_ORCHESTRE[0])
    check("quatre icônes sous le Pâle orchestre", len(lues) == 4,
          f"lu {len(lues)} : {lues}")
    if len(lues) == 4:
        xs = [b[0] for b in lues]
        ecarts = [xs[i + 1] - xs[i] for i in range(3)]
        check("pas régulier de ~25 px",
              all(20 <= e <= 30 for e in ecarts), ecarts)


def test_un_glyphe_fragmente_se_recolle_entier():
    """
    LE 4e GLYPHE (Surpuissance) N'EST PAS « UN PEU PETIT », IL EST
    FRAGMENTÉ. Une ombre interne coupe son masque en 22×11 + 9×8 + 4×8 +
    16×8 — abaisser `ICONE_COTE_MIN` aurait juste laissé passer le plus
    gros fragment (22×11), pas le glyphe (22×24). Et rien n'aurait rougi
    si le découpage avait un jour tort : les CINQ vignettes de cette
    scène se fragmentent à l'identique (auto-cohérence sans vérité, le
    piège de `cut_defi` le 08/11). D'où l'assertion sur la HAUTEUR, pas
    seulement le compte — c'est elle que la régression du 1er correctif
    (22×11 au lieu de 22×24) aurait fait rougir.
    """
    print("\nUn glyphe fragmenté se recolle entier")
    img = cv2.imread(str(CAPTURE_20))
    if img is None:
        check("capture du 20/11 présente", False, CAPTURE_20)
        return

    for centre in CENTRES_ORCHESTRE:
        lues = mce.icones(img, centre)
        check(f"quatre icônes en {centre}", len(lues) == 4,
              f"lu {len(lues)} : {lues}")
        if len(lues) != 4:
            continue
        hauteurs = [b[3] for b in lues]
        check(f"   aucun glyphe tronqué en {centre} (hauteurs {hauteurs})",
              all(h >= 20 for h in hauteurs), hauteurs)
        xs = [b[0] for b in lues]
        ecarts = [xs[i + 1] - xs[i] for i in range(3)]
        check(f"   pas régulier de ~25 px en {centre}",
              all(20 <= e <= 30 for e in ecarts), ecarts)

    print("Le garde contre la sur-fusion, sur la scène du 14/11")
    img14 = cv2.imread(str(CAPTURE))
    if img14 is None:
        check("capture de référence présente", False, CAPTURE)
        return
    # Firespitter colle à une tache de bordure, et CE N'EST PAS LA TAILLE
    # QUI L'ÉCARTE (remesuré le 21/11/2026). La description « 40×30 à
    # 92,0, donc écartée AVANT l'agglomération » datait de l'ancienne
    # bande `+38..+82` ; dans la bande actuelle `+47..+82` la tache fait
    # **25×21 à x=107**, ce qui est une taille de glyphe parfaitement
    # plausible. Et rien n'est écarté avant l'agglomération :
    # `_icones_et_masque` le dit en majuscules (« ON NE FILTRE PAS LES
    # FRAGMENTS TROP GRANDS ICI »). Ce qui l'écarte, c'est le garde du
    # bandeau : la médiane de son anneau vaut **111** pour un plancher à
    # `FOND_SOMBRE_MAX` = 70, quand les deux vraies icônes sont à 31 et
    # 28. Elle ne peut pas non plus servir de pont, parce que
    # l'agglomération refuse toute union plus grande qu'un glyphe.
    #
    # ON ASSERTE LA PROPRIÉTÉ, PAS LE TUPLE (20/11/2026, revue finale).
    # Ce test gravait `[(84, 20, 22, 20, 204)]` : l'origine exacte et
    # l'aire sont des incidents de SEGMENTATION, et élargir une famille
    # de couleur ou toucher à `FRAGMENT_AIRE_MIN` les aurait fait rougir
    # sans que rien de ce qu'il garde ait bougé — le motif qui a mordu le
    # projet quatre fois (`test_restrictions_levees`, `test_recovered_
    # screen_resets_the_counter`, `RESERVED_FAMILIES`, le Joker).
    #
    # DEUX GLYPHES, PAS UN (corrigé le 21/11/2026). Ce test exigeait UN
    # seul glyphe, au motif du 20/11 que « ses deux fragments en trop
    # n'étaient que le bord d'une tache de bordure voisine ». La capture
    # dit le contraire : la barre de Firespitter porte DEUX icônes
    # orange, et ce ne sont pas les tests qui le prouvent mais les
    # GABARITS — elles sortent nommées, Surpuissance (0.948, marge
    # 0.475) et Provocateur (0.797, marge 0.383), à six jours de la
    # capture dont les gabarits sont tirés. Provocateur est son mot-clé
    # IMPRIMÉ ; Surpuissance lui a été accordée en jeu. (Les deux
    # notaient 0.712 et 0.710 avant la refonte du masque du 21/11 au
    # soir : le gain vient de glyphes moins rognés.)
    lues = mce.icones(img14, (880, 900))
    check("Firespitter : ses DEUX glyphes, et pas la tache voisine",
          len(lues) == 2, lues)
    for index, boite in enumerate(lues):
        x, y, w, h, aire = boite
        check(f"   [{index}] a une taille de glyphe",
              mce._est_un_glyphe(w, h, aire), boite)
        # ET ON VÉRIFIE QU'ELLE N'A PAS MANGÉ LA TACHE, PAS QU'ELLE A
        # UNE TAILLE LÉGALE. L'assertion d'avant relisait
        # `w <= ICONE_COTE_MAX and h <= ICONE_COTE_MAX`, que
        # `_est_un_glyphe` vient d'imposer trois lignes plus haut :
        # elle ne pouvait pas rougir. La tache occupe x=107..132 ;
        # une boîte qui l'aurait avalée déborderait dedans.
        check(f"   [{index}] ne deborde pas sur la tache de bordure (x >= 107)",
              x + w <= 107, boite)

    # SWAIN EN PORTE CINQ, comptées sur la capture : bouclier orange,
    # face grimaçante orange, éclair cyan, arcs cyan, aile cyan.
    check("Swain : ses cinq icônes, les glyphes recollés compris",
          len(mce.icones(img14, (724, 900))) == 5, mce.icones(img14, (724, 900)))
    # Les quatre vierges restent à zéro — la propriété qui porte tout le
    # module ne doit RIEN céder à un recollage plus permissif. Les trois
    # dernières sont ADVERSES : leur barre, s'il y en avait une, serait
    # en haut de la carte.
    for nom, centre, adverse in (("Arachnoid Sentry", (1194, 900), False),
                                 ("House Spider", (802, 180), True),
                                 ("Spiderling", (959, 180), True),
                                 ("Imperial Demolitionist", (1115, 180), True)):
        check(f"{nom} reste vierge malgré le recollage",
              mce.icones(img14, centre, adverse=adverse) == [],
              mce.icones(img14, centre, adverse=adverse))


def test_les_quatre_icones_sont_identifiees():
    """
    L'ORDRE EST UN FAIT DE JEU, PAS UNE DÉDUCTION (Ewan, 20/11/2026).

    Et c'est le test qui justifie tout le module : 06SI009 n'imprime que
    Hallowed et Ephemeral. Challenger et Overwhelm lui ont été ACCORDÉS.

    Vérifié sur les trois exemplaires qui n'ont PAS servi de source :
    un gabarit comparé à son propre découpage rendrait 1.0 et ne
    prouverait rien.
    """
    print("\nIdentification des quatre icônes")
    img = cv2.imread(str(CAPTURE_20))
    if img is None:
        check("capture du 20/11 présente", False, CAPTURE_20)
        return
    attendu = ("Ephemeral", "Hallowed", "Challenger", "Overwhelm")
    for centre in AUTRES_ORCHESTRES:
        lu = mce.identifier(img, centre)
        check(f"Pâle orchestre en {centre} : les quatre, dans l'ordre",
              lu == attendu, lu)


def test_une_unite_sans_icone_nidentifie_rien():
    """Le miroir, sans lequel le test précédent ne prouverait rien."""
    print("\nUne unité vierge n'identifie rien")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    check("Arachnoid Sentry : aucun mot-clé identifié",
          mce.identifier(img, (1194, 900)) == ())


def test_un_glyphe_etranger_nest_identifie_comme_rien():
    """
    LE CAS QUI PROTÈGE DES SEIZE MOTS-CLÉS QU'ON N'A PAS.

    La marge sépare les mots-clés CONNUS entre eux ; seul le score absolu
    peut en refuser un dont on n'a aucun gabarit. Swain porte cinq icônes
    qu'Ewan n'a jamais étiquetées ; aucune n'est reconnue, et son
    `Fearsome` imprimé ne note que 0.474 contre le gabarit tiré de Viktor
    n°2 — ce qui est une LACUNE de rappel, pas un faux positif, et elle
    est au rapport de la tâche B.

    MESURÉ LE 21/11/2026, bibliothèque à SEIZE familles : ses glyphes
    notent au mieux **0.575** avec des marges de **0.010 à 0.078** — sous
    les deux planchers (0.60 / 0.10), et il faut franchir les DEUX.

    ⚠ LA MARGE DE SÉCURITÉ S'EST RESSERRÉE EN GRANDISSANT, et c'est le
    prix mesuré de la bibliothèque : à quatre familles le meilleur
    étranger notait 0.472, soit 0.128 sous le plancher ; à seize il note
    0.575, soit **0.025**. Chaque famille ajoutée est un concurrent de
    plus pour tous les glyphes inconnus — exactement ce que le projet a
    mesuré sur la police des chiffres le 14/11 (« enrichir une police
    resserre ses marges »). C'est le second plancher qui garde le plus de
    recul ici : 0.078 contre 0.10.

    Si ce test rougit, c'est qu'un seuil a été desserré et que le module
    s'est mis à inventer des mots-clés. C'est le pire défaut possible
    ici : un Challenger imaginaire ferait glisser un bloqueur sur un
    geste que le jeu refuse.
    """
    print("\nUn mot-clé qu'on ne connaît pas n'est pas deviné")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    lu = mce.identifier(img, (724, 900))      # Swain, 5 icônes étrangères
    check("Swain : aucune de ses icônes n'est prise pour une des nôtres",
          lu == (), lu)


def test_un_gabarit_franchit_les_captures():
    """
    VALIDATION CROISÉE, à six jours d'écart. Enraged Firespitter imprime
    `Challenger` dans `card_sets`, et sa capture date du 14/11 — les
    gabarits, eux, sont découpés sur celle du 20/11. Le reconnaître prouve
    que les gabarits ne collent pas à leur seule image d'origine.

    Mesuré le 21/11/2026 : **0.797, marge 0.383** (0.710 / 0.317 avant la
    refonte du masque du même jour).
    """
    print("\nUn gabarit du 20/11 reconnaît une icône du 14/11")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    check("Firespitter : son Challenger imprimé est reconnu",
          "Challenger" in mce.identifier(img, (880, 900)),
          mce.identifier(img, (880, 900)))


def test_le_decoupage_suit_le_chemin_de_lecture():
    """
    `decouper()` EST LE SEUL CHEMIN QUI ÉCRIT DES GABARITS, et il n'avait
    aucun test direct.

    Depuis le correctif de performance, elle n'est plus appelée que par
    `cut_icone` — `identifier()` tranche lui-même dans le masque qu'il
    vient de calculer. Si les deux dérivent, on fabrique des gabarits qui
    ne se reconnaissent pas eux-mêmes : c'est mot pour mot le piège du
    08/11 (`cut_defi`, IoU 0.83 contre son propre gabarit, marge sous le
    plancher) que la docstring de `cut_icone` invoque.

    Trois propriétés, aucune valeur gravée : la découpe a la forme de la
    boîte, elle se reconnaît elle-même, et elle est 0/255 — donc la
    relecture par `alpha >= 128` ne perd rien.
    """
    print("\nLe découpage d'un gabarit suit le chemin de lecture")
    img = cv2.imread(str(CAPTURE_20))
    img14 = cv2.imread(str(CAPTURE))
    if img is None or img14 is None:
        check("captures de référence présentes", False, (CAPTURE_20, CAPTURE))
        return

    for etiquette, image, centre in (("Pâle orchestre", img, CENTRES_ORCHESTRE[0]),
                                     ("Firespitter", img14, (880, 900))):
        boites = mce.icones(image, centre)
        check(f"{etiquette} : au moins un glyphe à découper", bool(boites), boites)
        for index, (_, _, w, h, _) in enumerate(boites):
            masque = mce.decouper(image, centre, index)
            check(f"   [{index}] la découpe a la forme de la boîte ({h}, {w})",
                  masque is not None and masque.shape == (h, w),
                  None if masque is None else masque.shape)
            if masque is None:
                continue
            check(f"   [{index}] elle se reconnaît elle-même (score 1.0)",
                  abs(mce._score(masque, masque) - 1.0) < 1e-9,
                  mce._score(masque, masque))
            # L'alpha écrit par `cut_icone` est ce masque tel quel, et
            # `charger_gabarits` le relit par `>= 128` : un masque qui ne
            # serait pas binaire perdrait des pixels EN SILENCE.
            valeurs = set(int(v) for v in set(masque.ravel()))
            check(f"   [{index}] masque binaire, relisible par >= 128",
                  valeurs <= {0, 255}, sorted(valeurs))

    boites = mce.icones(img, CENTRES_ORCHESTRE[0])
    check("un indice hors des boîtes ne rend rien",
          mce.decouper(img, CENTRES_ORCHESTRE[0], len(boites)) is None)
    check("un indice négatif non plus",
          mce.decouper(img, CENTRES_ORCHESTRE[0], -1) is None)
    check("une image illisible non plus",
          mce.decouper(None, CENTRES_ORCHESTRE[0], 0) is None)


# ============================================================
# Les deux défauts du 21/11/2026
# ============================================================
# MILIEU DU BANDEAU. Mesuré sur les neuf unités du 20 et du 21/11 qui
# sont de NOTRE côté (cinq Pâle orchestre, deux Kennen, deux Viktor) : le
# bandeau noir y occupe dy +47..+89. Son milieu, +68, sépare les deux
# niveaux d'une barre tassée — centres mesurés +59 à +62 en haut, +74 à
# +78 en bas.
MILIEU_BANDEAU = 68

def _centre_vertical(boite, haut_de_bande):
    """dy du centre d'une boîte, ramené au repère de `card.center`."""
    return haut_de_bande + boite[1] + boite[3] / 2


def _icones_couvertes(boite, lexique):
    """
    Combien d'icônes du lexique cette boîte recouvre-t-elle ?

    UNE BOÎTE QUI EN CONTIENT DEUX EST INUTILISABLE, et c'est ça qu'il
    faut interdire. La première version de ce test demandait qu'aucune
    boîte n'ATTEIGNE les deux rangées de la quinconce : cette propriété
    était un bon détecteur de fusion tant que le masque laissait tomber
    la moitié des glyphes, mais elle ne l'est plus — mesuré le
    21/11/2026, les trois boîtes qui atteignent les deux rangées sont
    maintenant des icônes UNIQUES et simplement hautes (le cercle rouge
    de Régénération, 24×26, dy +52..+78, sur les deux captures de
    Kennen ; le disque de niveau de Viktor n°2, 20×27, dy +50..+77).
    Exiger le contraire ferait rougir un correctif.

    On compte donc les CENTRES du lexique que l'étendue en x de la boîte
    enferme. La fusion que ce test existe pour attraper — la flamme de
    Volonté soudée à l'œil barré de Viktor n°1, x 108..140 — en enferme
    DEUX ; les trois boîtes hautes ci-dessus n'en enferment qu'UN.
    """
    return sum(1 for _, x0, x1 in lexique
               if boite[0] <= (x0 + x1) / 2 <= boite[0] + boite[2])


def test_la_barre_adverse_se_lit_en_haut_de_la_carte():
    """
    LE CAMP ADVERSE ÉTAIT ENTIÈREMENT AVEUGLE (21/11/2026).

    Chez l'adversaire, statistiques et barre de mots-clés sont
    INVERSÉES : statistiques en bas, barre en haut. `lire_les_mots_cles`
    lisait `dy +38..+82` pour tout le monde, donc chez l'adversaire la
    zone des STATISTIQUES. C'est le côté où Provocateur, Insaisissable
    et Redoutable décident de la légalité et de la survie d'un blocage.

    L'ORACLE NE VIENT PAS DE L'IMAGE : 02BW032T1 « Powder Keg » IMPRIME
    `Immobile` et `Vulnerable` dans `card_sets` — deux mots-clés, donc au
    moins deux icônes, quoi qu'on voie à l'écran. 01SI048 « Cursed
    Keeper » en imprime deux aussi (`Can't Block`, `Last Breath`).
    À l'inverse 02BW058 « Jagged Butcher » n'imprime que `Plunder`, un
    déclencheur sans icône : sa carte n'a aucune barre.

    POURQUOI LE PLANCHER DE CURSED KEEPER EST 1 ET NON 2, alors qu'elle
    imprime DEUX mots-clés : son icône « Can't Block » est un BOUCLIER
    BLANC, de saturation médiane 17, qu'aucune des trois familles de
    couleur ne voit (cf. le relevé en tête de `mots_cles_ecran`). Le
    plancher décrit donc ce que la SEGMENTATION doit rendre, pas ce que
    la carte imprime — et c'est le masque, pas la bande, qui coûte la
    seconde icône. Powder Keg est dans le même cas (croix blanche
    d'Immobile) et garde pourtant un plancher de 2, parce que ses DEUX
    autres icônes, elles, passent.
    """
    print("\nLa barre des unités ADVERSES")
    for etiquette, chemin, centre, mini in (
            ("Powder Keg (kennen)", CAPTURE_KENNEN, (880, 180), 2),
            ("Powder Keg (viktor)", CAPTURE_VIKTOR, (959, 180), 2),
            ("Cursed Keeper", CAPTURE_20, (1037, 180), 1),
            ("Vaults of Helia", CAPTURE_20, (880, 180), 1)):
        img = cv2.imread(str(chemin))
        if img is None:
            check(f"capture présente ({etiquette})", False, chemin)
            continue
        lues = mce.icones(img, centre, adverse=True)
        check(f"{etiquette:<22} : au moins {mini} icône(s) lue(s)",
              len(lues) >= mini, lues)
        # LA CONTRE-ÉPREUVE, sans laquelle le test ne prouverait rien :
        # dans la bande de NOS unités, la même carte ne rend rien — c'est
        # exactement l'état d'avant le correctif. (Le libellé portait un
        # `mini and 'zéro' or ''` dont la branche vide était
        # inatteignable : `mini` vaut toujours 1 ou 2.)
        check(f"{etiquette:<22} :    du mauvais côté, rien n'est lu",
              mce.icones(img, centre) == [], mce.icones(img, centre))

    img = cv2.imread(str(CAPTURE_KENNEN))
    if img is not None:
        check("Jagged Butcher (Plunder, aucune barre) reste à zéro",
              mce.icones(img, (1037, 180), adverse=True) == [],
              mce.icones(img, (1037, 180), adverse=True))

    # ZÉRO FAUX POSITIF SUR LES VIERGES DU 14/11 — trois des quatre sont
    # ADVERSES, et c'est la bande miroir qui les lit désormais.
    img14 = cv2.imread(str(CAPTURE))
    if img14 is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    for nom, centre in (("House Spider", (802, 180)),
                        ("Spiderling", (959, 180)),
                        ("Imperial Demolitionist", (1115, 180))):
        check(f"{nom:<24} (adverse, vierge) reste à zéro",
              mce.icones(img14, centre, adverse=True) == [],
              mce.icones(img14, centre, adverse=True))


def test_les_deux_rangees_dune_barre_tassee_ne_se_confondent_pas():
    """
    AU-DELÀ DE QUATRE MOTS-CLÉS, LE JEU TASSE LES ICÔNES SUR DEUX
    NIVEAUX (21/11/2026). Le recollage par colonne du 20/11 chaînait les
    fragments par leurs seules plages en x : sur deux niveaux il mariait
    une icône du haut à sa voisine du bas, la boîte dépassait la taille
    d'un glyphe, et le repli rejugeait chaque fragment seul.

    Ce qu'on exige ici :
      - la QUINCONCE est vue : au moins une boîte de chaque côté du
        milieu du bandeau, sur les quatre barres tassées ;
      - AUCUNE boîte ne contient DEUX icônes du lexique d'Ewan.

    LA SECONDE ASSERTION A CHANGÉ DE FORME LE 21/11/2026, et la raison
    est mesurée. Elle disait d'abord « au plus N boîtes atteignent les
    deux rangées », N étant un registre de défauts connus (0, 1, 1, 2).
    Une fois le masque refait, les SEULES boîtes qui atteignent encore
    les deux rangées sont des icônes UNIQUES et simplement hautes : le
    cercle rouge de Régénération (24×26, dy +52..+78) sur les deux
    captures de Kennen, et le disque de niveau de Viktor n°2 (20×27, dy
    +50..+77). Garder l'ancienne forme aurait fait rougir le correctif
    au lieu du défaut.

    CE QUE LA FORME ACTUELLE ATTRAPE ENCORE, et c'est le vrai sujet :
    une boîte qui enferme DEUX icônes. La fusion que ce test existe pour
    interdire est la flamme de Volonté soudée à l'œil barré de Viktor
    n°1 (x 108..140, 32×26) : elle enferme les centres des DEUX. Les
    trois boîtes hautes ci-dessus n'en enferment qu'un.
    """
    print("\nLes deux rangées d'une barre tassée")
    for etiquette, (chemin, centre, lexique) in LEXIQUE.items():
        img = cv2.imread(str(chemin))
        if img is None:
            check(f"capture présente ({etiquette})", False, chemin)
            continue
        lues = mce.icones(img, centre)
        hauts = [b for b in lues
                 if _centre_vertical(b, mce.BARRE_DY_HAUT) <= MILIEU_BANDEAU]
        bas = [b for b in lues
               if _centre_vertical(b, mce.BARRE_DY_HAUT) > MILIEU_BANDEAU]
        check(f"{etiquette:<16} : la rangée du HAUT est vue", len(hauts) >= 1,
              [b[:4] for b in lues])
        check(f"{etiquette:<16} :    et celle du BAS aussi", len(bas) >= 1,
              [b[:4] for b in lues])
        doubles = [b for b in lues if _icones_couvertes(b, lexique) > 1]
        check(f"{etiquette:<16} : aucune boîte n'enferme deux icônes",
              not doubles, [b[:4] for b in doubles])

    # LA RANGÉE DU BAS N'EST PLUS À MOITIÉ PERDUE, et c'est le cœur du
    # correctif du 21/11. Kennen porte TROIS icônes en bas (épée, aile
    # dorée, symbole cyan) : le recollage par colonne n'en rendait que
    # DEUX, l'aile ayant été mariée à sa voisine du haut.
    img = cv2.imread(str(CAPTURE_KENNEN))
    if img is not None:
        bas = [b for b in mce.icones(img, (959, 900))
               if _centre_vertical(b, mce.BARRE_DY_HAUT) > MILIEU_BANDEAU]
        check("Kennen : les TROIS icônes de sa rangée du bas sont lues",
              len(bas) == 3, [b[:4] for b in bas])


def test_une_tache_hors_du_bandeau_nest_pas_une_icone():
    """
    UNE ICÔNE EST POSÉE SUR LE BANDEAU NOIR, et c'est ce qui la
    distingue d'un éclat d'illustration de la même couleur.

    Legion Saboteur n'a qu'UNE icône — le module en comptait DEUX
    depuis le 14/11. Mesuré sur les quatre captures, luminosité médiane
    de l'anneau de 3 px qui entoure chaque boîte : 19 à 38 pour les
    vraies icônes, 139 et 193 pour les deux taches d'illustration qui
    passaient le garde de taille. Le plancher retenu, 70, laisse 32 de
    marge sous la pire tache et 32 au-dessus de la pire vraie icône.
    """
    print("\nUne tache hors du bandeau n'est pas une icône")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    lues = mce.icones(img, (1037, 900))
    check("Legion Saboteur : une seule icône, posée sur le bandeau",
          len(lues) == 1, lues)
    # Swain en porte CINQ, comptées sur la capture — le garde ne doit
    # pas mordre sur une barre pleine.
    check("Swain : ses cinq icônes restent", len(mce.icones(img, (724, 900))) == 5,
          mce.icones(img, (724, 900)))


# ============================================================
# LE LEXIQUE D'EWAN - la verite terrain, PAR POSITION
# ============================================================
# « La vérité terrain est une POSITION, pas une description » (CLAUDE.md).
# Chaque ligne donne, de gauche à droite, le nom donné par Ewan et
# l'INTERVALLE en x (coordonnées de bande) où tombe le centre du glyphe,
# relevé sur la capture agrandie ×7. Un intervalle, pas un x : ce qu'on
# exige est « une boîte EST SUR ce glyphe-là », pas « la boîte commence à
# tel pixel » — l'origine exacte d'une boîte est un incident de
# segmentation, et graver une valeur au lieu d'un comportement est le
# motif qui a mordu le projet sept fois.
#
# Les positions 7 des deux Viktor ne sont pas nommées (Ewan : « oublie le
# 7e ») mais elles EXISTENT : elles sont donc comptées, et seulement
# comptées — aucun gabarit n'en est tiré.
LEXIQUE = {
    "Kennen (kennen)": (CAPTURE_KENNEN, (959, 900), [
        ("niveau", 19, 46), ("quickstrike", 44, 63), ("elusive", 59, 86),
        ("spellshield", 80, 101), ("regeneration", 97, 123), ("augment", 117, 146)]),
    "Kennen (viktor)": (CAPTURE_VIKTOR, (1115, 900), [
        ("niveau", 20, 47), ("quickstrike", 45, 64), ("elusive", 60, 87),
        ("spellshield", 81, 102), ("regeneration", 98, 124), ("augment", 118, 147)]),
    "Viktor n1": (CAPTURE_VIKTOR, (802, 900), [
        ("niveau", 22, 45), ("aura", 38, 60), ("augment", 53, 78),
        ("deathless", 71, 93), ("impact", 87, 107), ("spirit", 106, 120),
        ("7e non nommee", 118, 145)]),
    "Viktor n2": (CAPTURE_VIKTOR, (959, 900), [
        ("niveau", 22, 45), ("aura", 38, 60), ("augment", 53, 78),
        ("deathless", 71, 93), ("fury", 86, 108), ("fearsome", 104, 122),
        ("7e non nommee", 119, 143)]),
}


def _appariement(boites, lexique):
    """Le nom du lexique porté par chaque boîte, ou None.

    Apparie dans l'ORDRE du lexique : la première boîte libre dont le
    centre tombe dans l'intervalle. Rend (noms_vus, boîtes_sans_nom)."""
    pris = [None] * len(boites)
    vus = []
    for nom, x0, x1 in lexique:
        for j, b in enumerate(boites):
            if pris[j] is None and x0 <= b[0] + b[2] / 2 <= x1:
                pris[j] = nom
                vus.append(nom)
                break
    return vus, [boites[j] for j in range(len(boites)) if pris[j] is None]


def test_chaque_icone_du_lexique_a_sa_boite():
    """
    LE COMPTE EST JUSTE, ET IL EST JUSTE AU BON ENDROIT (21/11/2026).

    C'est la propriété qui rend la RÉCOLTE possible : `cut_icone` prend un
    INDEX, le lexique nomme une POSITION, et les deux ne coïncident que si
    chaque icône étiquetée a UNE boîte et qu'aucune boîte n'est en trop.
    Avant ce correctif l'index 0 de Kennen désignait le chevron de niveau
    sur une capture et l'épée sur l'autre, et la seconde liste se
    terminait par un halo du plateau — récolter à l'index y aurait gravé
    un gabarit FAUX, sans que rien rougisse (`cut_defi`, 08/11).

    Les familles d'icônes que le masque de couleur ne voyait pas sont dans
    ce tableau : le cercle rouge de Régénération (teintes 2 à 11), la tour
    dorée d'Immortalité (saturation médiane 129), la flamme de Volonté
    (10 px de large), le chevron de niveau (19×11 sur la capture
    `victor`), et le ruban de Redoutable, dont l'œil droit ne fait que
    15 px d'aire.
    """
    print("\nChaque icône du lexique d'Ewan a sa boîte, et rien de plus")
    for etiquette, (chemin, centre, lexique) in LEXIQUE.items():
        img = cv2.imread(str(chemin))
        if img is None:
            check(f"capture présente ({etiquette})", False, chemin)
            continue
        boites = mce.icones(img, centre)
        vus, orphelines = _appariement(boites, lexique)
        manquants = [n for n, _, _ in lexique if n not in vus]
        check(f"{etiquette:<16} : les {len(lexique)} icônes étiquetées sont vues",
              not manquants, f"manque {manquants} - boîtes {[b[:4] for b in boites]}")
        check(f"{etiquette:<16} :    et aucune boîte en trop",
              not orphelines, [b[:4] for b in orphelines])


def test_les_familles_blanche_et_rouge_se_voient():
    """
    LES FAMILLES DE COULEUR AJOUTÉES, chacune sur son témoin ADVERSE.

    Le miroir du test précédent, côté adverse — où la barre est en haut de
    la carte — et avec des ORACLES EXTERNES : 02BW032T1 « Powder Keg »
    imprime `Immobile` (croix BLANCHE) et `Vulnerable` ; 01SI048 « Cursed
    Keeper » imprime `Can't Block` (bouclier BLANC) et `Last Breath`. Ces
    deux icônes-là ne sont dans aucune des trois familles d'avant
    (saturation médiane 17) : le compte passait de 3 à 2 et de 2 à 1.
    """
    print("\nLa famille blanche, sur les deux cartes qui l'impriment")
    for etiquette, chemin, centre, attendu in (
            ("Powder Keg (kennen)", CAPTURE_KENNEN, (880, 180), 3),
            ("Powder Keg (viktor)", CAPTURE_VIKTOR, (959, 180), 3),
            ("Cursed Keeper", CAPTURE_20, (1037, 180), 2)):
        img = cv2.imread(str(chemin))
        if img is None:
            check(f"capture présente ({etiquette})", False, chemin)
            continue
        lues = mce.icones(img, centre, adverse=True)
        check(f"{etiquette:<20} : ses {attendu} icônes, la blanche comprise",
              len(lues) == attendu, [b[:4] for b in lues])


def test_une_boite_qui_touche_le_bord_de_la_bande_nest_pas_une_icone():
    """
    LA BANDE EST PLUS LARGE QUE LE BANDEAU, ET C'EST MESURÉ.

    On lit `BARRE_DEMI_LARGEUR` = 80 px de part et d'autre du centre
    quand le bandeau noir, lui, ne fait que 65 (Pâle orchestre) à 71 px
    (Kennen, Viktor) de demi-largeur. Les 9 px de marge laissent entrer le
    HALO BLEU du plateau : sous Kennen (capture `victor`) il formait une
    boîte de 15×20 à dx +65, de taille parfaitement plausible et cernée de
    noir — donc invisible au garde du bandeau.

    Rien de réel ne touche ce bord : sur les 63 icônes des quatre
    captures, la boîte la plus à gauche commence à x = 16 et la plus à
    droite finit à x = 140, pour une bande large de 160.
    """
    print("\nUne boîte collée au bord latéral de la bande")
    vus = 0
    for chemin, centres, adverse in (
            (CAPTURE_VIKTOR, [(802, 900), (959, 900), (1115, 900)], False),
            (CAPTURE_KENNEN, [(959, 900)], False),
            (CAPTURE_20, CENTRES_ORCHESTRE, False),
            (CAPTURE, [(724, 900), (880, 900), (1037, 900)], False)):
        img = cv2.imread(str(chemin))
        if img is None:
            check(f"capture présente ({chemin.name})", False, chemin)
            continue
        largeur = 2 * mce.BARRE_DEMI_LARGEUR
        for centre in centres:
            for b in mce.icones(img, centre, adverse=adverse):
                vus += 1
                check(f"{chemin.name[:12]} {centre} : boîte x={b[0]} "
                      f"{b[2]}x{b[3]}, pas collée au bord",
                      b[0] > 0 and b[0] + b[2] < largeur, b[:4])
    check("   et il y avait bien des boîtes à juger", vus >= 30, vus)


def test_chaque_icone_du_lexique_est_nommee():
    """
    LA BIBLIOTHÈQUE REND À CHAQUE POSITION LE NOM D'EWAN (21/11/2026).

    C'est le test que la récolte existe pour rendre possible, et c'est
    aussi sa contre-épreuve : `cut_icone` prend un INDEX, le lexique
    nomme une POSITION, et un décalage entre les deux graverait un
    gabarit sous le nom du voisin — sans que rien rougisse, puisqu'une
    icône mal nommée se reconnaît parfaitement elle-même. Ici on relit
    les DEUX captures, dont celle qui n'a PAS servi de source.

    LES TÉMOINS INDÉPENDANTS, mesurés (score | marge) :
      - Kennen, capture `victor` : aucun de ses six gabarits n'en vient,
        ils sont tous découpés sur la capture `kennen` — 0.805 à 1.000,
        marges 0.428 à 0.584 ;
      - Viktor n°2 : `aura` et `deathless` viennent de Viktor n°1 —
        0.962 et 0.925 ;
      - les trois derniers Pâle orchestre : les gabarits viennent des
        deux premiers — 0.784 à 0.990.

    La position 7 des deux Viktor n'est pas dans le lexique (Ewan :
    « oublie le 7e ») : on ne dit rien de ce qu'elle devient.
    """
    print("\nChaque icône du lexique est NOMMÉE")
    for etiquette, (chemin, centre, lexique) in LEXIQUE.items():
        img = cv2.imread(str(chemin))
        if img is None:
            check(f"capture présente ({etiquette})", False, chemin)
            continue
        familles = mce.familles_lues(img, centre)
        check(f"{etiquette:<16} : une famille par boîte",
              len(familles) == len(mce.icones(img, centre)), familles)
        for index, (nom, _, _) in enumerate(lexique):
            if nom.startswith("7e"):
                continue
            check(f"{etiquette:<16} : position {index + 1} = {nom}",
                  index < len(familles) and familles[index] == nom,
                  familles[index] if index < len(familles) else "rien")


def test_un_dessin_daffichage_nest_pas_un_mot_cle():
    """
    L'INDICATEUR DE NIVEAU ET L'EFFET DE ZONE SONT RECONNUS, PUIS
    ÉCARTÉS (21/11/2026).

    La première place de la barre est le niveau du champion (fait de jeu
    d'Ewan) et la deuxième place des Viktor est un « effet de zone » que
    la base nomme elle-même `AuraVisualFakeKeyword`. Les COMPTER faisait
    de `a_recu_un_mot_cle` un faux positif pour tout champion monté de
    niveau sans mot-clé imprimé — la seule promesse que cette fonction
    porte.

    Trois choses, et il faut les trois : le dessin est bien reconnu
    (sinon l'exclusion n'aurait rien à écarter), `identifier` ne le rend
    pas, et `porte_des_mots_cles` ne le compte pas.
    """
    print("\nUn dessin d'affichage n'est pas un mot-clé")
    img = cv2.imread(str(CAPTURE_VIKTOR))
    if img is None:
        check("capture du 21/11 présente", False, CAPTURE_VIKTOR)
        return

    for etiquette, centre, attendues in (
            ("Viktor n1", (802, 900), ("niveau", "aura")),
            ("Viktor n2", (959, 900), ("niveau", "aura")),
            ("Kennen", (1115, 900), ("niveau",))):
        familles = mce.familles_lues(img, centre)
        for famille in attendues:
            check(f"{etiquette:<10} : le dessin « {famille} » EST reconnu",
                  famille in familles, familles)
        noms = mce.identifier(img, centre)
        check(f"{etiquette:<10} :    et `identifier` ne le rend pas",
              not (set(noms) & set(mce.AFFICHAGE.values())
                   or set(noms) & set(mce.AFFICHAGE)), noms)

    # LE CAS QUI N'EXISTE SUR AUCUNE DES QUATRE CAPTURES : une unité dont
    # TOUTES les icônes sont des dessins d'affichage — un champion monté
    # de niveau et sans aucun mot-clé. On ne le fabrique pas en image
    # (une éprouvette qui dessine l'état à refuser ne prouve rien, cf.
    # `bilan.py` le 08/11) : on bouchonne la LECTURE et on juge la
    # DÉCISION, qui est la seule chose en cause ici.
    vraie_lecture = mce.familles_lues
    try:
        mce.familles_lues = lambda *a, **k: ["niveau"]
        check("un champion qui n'affiche QUE son niveau n'a reçu aucun mot-clé",
              mce.porte_des_mots_cles(img, (802, 900)) is False)
        mce.familles_lues = lambda *a, **k: ["niveau", "aura"]
        check("   niveau + effet de zone non plus",
              mce.porte_des_mots_cles(img, (802, 900)) is False)
        # LA CONTRE-ÉPREUVE, sans laquelle la précédente ne prouverait
        # qu'un `False` systématique : un glyphe INCONNU compte toujours.
        mce.familles_lues = lambda *a, **k: ["niveau", None]
        check("   mais un glyphe inconnu à côté, OUI",
              mce.porte_des_mots_cles(img, (802, 900)) is True)
        mce.familles_lues = lambda *a, **k: ["niveau", "elusive"]
        check("   et un mot-clé reconnu, OUI",
              mce.porte_des_mots_cles(img, (802, 900)) is True)
    finally:
        mce.familles_lues = vraie_lecture


def test_la_planche_montre_chaque_gabarit():
    """
    LA PLANCHE EST LA CONTRE-ÉPREUVE DE L'ÉTIQUETAGE (demandée par Ewan
    le 21/11/2026).

    Rien dans le code ne peut dire qu'un gabarit porte le bon nom : une
    icône mal nommée se reconnaît elle-même, et tous les tests passent.
    Le seul recours est de MONTRER la bibliothèque à celui qui a
    étiqueté. On vérifie donc ici ce qu'une image peut garantir : une
    vignette par variante, aucune vide — une case noire serait un
    gabarit perdu au chargement, exactement le défaut du 08/11 (« le
    gabarit était écrit, puis IGNORÉ au chargement, sans un mot »).

    ELLE S'ÉCRIT DANS UN DOSSIER TEMPORAIRE. Une suite hors ligne ne
    laisse rien derrière elle (09/11) : le dépôt a ramassé 0,98 Go de
    captures produites par des tests avant qu'on s'en aperçoive.
    """
    print("\nLa planche des gabarits")
    import tempfile, shutil
    dossier = tempfile.mkdtemp(prefix="planche_")
    try:
        chemin = Path(dossier) / "planche.png"
        rendu = mce.planche(chemin)
        check("la planche est écrite", Path(rendu).exists(), rendu)
        image = cv2.imread(str(chemin))
        check("et elle est relisible", image is not None)
        if image is None:
            return
        variantes = sum(len(v) for v in mce.charger_gabarits().values())
        colonnes = min(mce._PLANCHE_COLONNES, variantes)
        lignes = (variantes + colonnes - 1) // colonnes
        case_h, case_l = image.shape[0] // lignes, image.shape[1] // colonnes
        check(f"une vignette par variante ({variantes})",
              image.shape[0] % lignes == 0 and image.shape[1] % colonnes == 0,
              image.shape)
        vides = []
        for index in range(variantes):
            ligne, colonne = divmod(index, colonnes)
            case = image[ligne * case_h:(ligne + 1) * case_h,
                         colonne * case_l:(colonne + 1) * case_l]
            # Au-dessus du bandeau de légende : le glyphe lui-même.
            glyphe = case[:case_h - mce._PLANCHE_LEGENDE]
            if int((glyphe > 200).sum()) < 20:
                vides.append(index)
        check("aucune vignette vide — aucun gabarit perdu", not vides, vides)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def main():
    for test in (test_la_barre_se_lit_la_ou_elle_est,
                 test_un_mot_cle_accorde_se_voit,
                 test_les_pistes_naives_sont_ecartees,
                 test_une_lecture_impossible_ne_rend_pas_un_verdict,
                 test_le_sablier_magenta_entre_dans_le_masque,
                 test_un_glyphe_fragmente_se_recolle_entier,
                 test_les_quatre_icones_sont_identifiees,
                 test_une_unite_sans_icone_nidentifie_rien,
                 test_un_glyphe_etranger_nest_identifie_comme_rien,
                 test_un_gabarit_franchit_les_captures,
                 test_le_decoupage_suit_le_chemin_de_lecture,
                 test_la_barre_adverse_se_lit_en_haut_de_la_carte,
                 test_les_deux_rangees_dune_barre_tassee_ne_se_confondent_pas,
                 test_une_tache_hors_du_bandeau_nest_pas_une_icone,
                 test_chaque_icone_du_lexique_a_sa_boite,
                 test_les_familles_blanche_et_rouge_se_voient,
                 test_une_boite_qui_touche_le_bord_de_la_bande_nest_pas_une_icone,
                 test_chaque_icone_du_lexique_est_nommee,
                 test_un_dessin_daffichage_nest_pas_un_mot_cle,
                 test_la_planche_montre_chaque_gabarit):
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
