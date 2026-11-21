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
    # Firespitter colle à une grande tache de bordure (40×30 à 92,0) :
    # celle-ci dépasse DÉJÀ la taille d'un glyphe, donc elle est écartée
    # avant l'agglomération et ne peut plus servir de pont (21/11/2026).
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
    # GABARITS — elles sortent nommées, Surpuissance (0.712, marge
    # 0.333) et Provocateur (0.710, marge 0.317), aux mêmes niveaux que
    # la validation croisée du 20/11. Provocateur est son mot-clé
    # IMPRIMÉ ; Surpuissance lui a été accordée en jeu.
    lues = mce.icones(img14, (880, 900))
    check("Firespitter : ses DEUX glyphes, et pas la tache voisine",
          len(lues) == 2, lues)
    for index, boite in enumerate(lues):
        x, y, w, h, aire = boite
        check(f"   [{index}] a une taille de glyphe",
              mce._est_un_glyphe(w, h, aire), boite)
        # La tache de bordure fait 40×30 : aucune boîte ne doit l'avoir
        # avalée.
        check(f"   [{index}] n'a pas avalé la tache de bordure (40×30)",
              w <= mce.ICONE_COTE_MAX and h <= mce.ICONE_COTE_MAX, boite)

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

    La marge sépare les quatre mots-clés CONNUS entre eux ; seul le score
    absolu peut refuser un cinquième dont on n'a aucun gabarit. Swain
    porte Fearsome et quatre autres icônes, dont AUCUNE n'est des nôtres.
    Mesuré : ses glyphes notent au mieux 0.409 contre nos gabarits, avec
    des marges de 0.003 à 0.073 — très en dessous de 0.60 / 0.10.

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

    Mesuré : 0.710, marge 0.317.
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
# MILIEU DU BANDEAU. Mesuré sur les neuf unités porteuses des quatre
# captures : le bandeau noir occupe dy +47..+88 de notre côté. Son
# milieu, +68, sépare les deux niveaux d'une barre tassée — centres
# mesurés +59 à +62 en haut, +74 à +78 en bas.
MILIEU_BANDEAU = 68


def _centre_vertical(boite, haut_de_bande):
    """dy du centre d'une boîte, ramené au repère de `card.center`."""
    return haut_de_bande + boite[1] + boite[3] / 2


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
        # exactement l'état d'avant le correctif.
        check(f"   et {mini and 'zéro' or ''} du mauvais côté, rien n'est lu",
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
    d'un glyphe, et le repli rejugeait chaque fragment seul — une icône
    sur deux perdue ou fragmentée.

    Comptes étiquetés par Ewan : Kennen (05BC058) SIX icônes, Viktor
    (03PZ003) SEPT. Ce qu'on exige ici :
      - la QUINCONCE est vue : au moins deux icônes de chaque côté du
        milieu du bandeau ;
      - aucune boîte n'en couvre deux : sa hauteur reste celle d'UNE
        icône (mesuré : 12 à 27 px, jamais les ~37 px des deux rangées) ;
      - le compte ne dépasse JAMAIS le nombre d'icônes étiquetées — un
        faux positif serait pire qu'une icône manquée.
    """
    print("\nLes deux rangées d'une barre tassée")
    for etiquette, chemin, centre, etiquetees in (
            ("Kennen (kennen)", CAPTURE_KENNEN, (959, 900), 6),
            ("Kennen (viktor)", CAPTURE_VIKTOR, (1115, 900), 6),
            ("Viktor gauche", CAPTURE_VIKTOR, (802, 900), 7),
            ("Viktor droite", CAPTURE_VIKTOR, (959, 900), 7)):
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
        check(f"{etiquette:<16} : aucune boîte ne couvre les deux rangées",
              all(b[3] <= mce.ICONE_COTE_MAX for b in lues), [b[:4] for b in lues])
        check(f"{etiquette:<16} : jamais plus que les {etiquetees} étiquetées",
              len(lues) <= etiquetees, len(lues))
        check(f"{etiquette:<16} : au moins quatre des {etiquetees}",
              len(lues) >= 4, len(lues))

    # LA RANGÉE DU BAS N'EST PLUS À MOITIÉ PERDUE, et c'est le cœur du
    # correctif. Kennen porte TROIS icônes en bas (épée, aile dorée,
    # symbole cyan) : le recollage par colonne n'en rendait que DEUX,
    # l'aile ayant été mariée à sa voisine du haut.
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
                 test_une_tache_hors_du_bandeau_nest_pas_une_icone):
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
