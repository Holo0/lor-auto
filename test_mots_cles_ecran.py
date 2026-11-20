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

# Pâle orchestre (06SI009), rect écran x 582-709 / y 820-980.
# L'ordre est un FAIT DE JEU donné par Ewan le 20/11/2026 : « chacun des
# Pâle orchestre a dans l'ordre, de gauche à droite, le mot clé éphémère,
# sanctification, challenger et enfin surpuissance ».
CENTRE_ORCHESTRE = (645, 900)

# Les CINQ Pâle orchestre de la même scène (`scene_20261120_201157.json`,
# CardCode 06SI009), centres recalculés par `lor_api.rect_center_screen` —
# pas une approximation à l'œil. La même carte, posée cinq fois : si le
# masque se fragmente pareil sur les cinq, c'est que le découpage est une
# propriété du GLYPHE, pas un accident d'une seule vignette.
CENTRES_ORCHESTRE = [(645, 900), (802, 900), (959, 900), (1115, 900), (1272, 900)]

FAILURES: list = []


def check(label, condition, detail=None):
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(label)
        print(f"  ÉCHEC {label}" + ("" if detail is None else f" {detail}"))


class _Carte:
    """Le minimum de BoardCard dont ce module a besoin."""

    def __init__(self, nom, card_id, centre, keywords=()):
        self.name, self.card_id, self.center = nom, card_id, centre
        self.keywords = tuple(keywords)
        self.keyword_refs = tuple(keywords)


# La scène, étiquetée par `card_sets` — PAS par l'image.
SCENE = [
    # nom,                   id,  centre,       imprimés,        porte des icônes ?
    ("Swain", 201, (724, 900), ("Fearsome",), True),
    ("Enraged Firespitter", 202, (880, 900), ("Challenger",), True),
    ("Legion Saboteur", 203, (1037, 900), (), True),
    ("Arachnoid Sentry", 204, (1194, 900), (), False),
    ("House Spider", 301, (802, 180), (), False),
    ("Spiderling", 302, (959, 180), (), False),
    ("Imperial Demolitionist", 303, (1115, 180), (), False),
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

    for nom, _, centre, _, attendu in SCENE:
        lu = mce.porte_des_mots_cles(img, centre)
        check(f"{nom:<24} porte des icônes={attendu}", lu is attendu,
              f"lu {lu} — {len(mce.icones(img, centre))} icône(s)")


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

    cartes = [_Carte(n, i, c, k) for n, i, c, k, _ in SCENE]
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
    lues = mce.icones(img, CENTRE_ORCHESTRE)
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
    # recoller la colonne entière donnerait une boîte > ICONE_COTE_MAX,
    # refusée — c'est ce refus qui laisse son glyphe réel (22×20) compter
    # tout seul, plutôt que de faire disparaître les deux.
    check("Firespitter garde son glyphe malgré la tache voisine",
          mce.icones(img14, (880, 900)) == [(84, 20, 22, 20, 204)],
          mce.icones(img14, (880, 900)))
    # Les quatre vierges restent à zéro — la propriété qui porte tout le
    # module ne doit RIEN céder à un recollage plus permissif.
    for nom, centre in (("Arachnoid Sentry", (1194, 900)),
                         ("House Spider", (802, 180)),
                         ("Spiderling", (959, 180)),
                         ("Imperial Demolitionist", (1115, 180))):
        check(f"{nom} reste vierge malgré le recollage par colonne",
              mce.icones(img14, centre) == [], mce.icones(img14, centre))


# Les vignettes qui n'ont PAS servi de source. Les gabarits sont récoltés
# sur (645, 900) et (802, 900) ; tester sur l'une d'elles serait comparer
# un gabarit à son propre découpage — 1.0 par construction, qui ne
# prouve rien.
AUTRES_ORCHESTRES = ((959, 900), (1115, 900), (1272, 900))


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
                 test_un_gabarit_franchit_les_captures):
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
