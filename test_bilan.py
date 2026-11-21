#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_bilan.py

Le JUGE DE FIN DE TENTATIVE (bilan.py), sur la VRAIE capture de la
défaite du 04/11/2026 au boss final — celle que le bot avait
photographiée sous le nom « écran inconnu » sans jamais la lire.

    python test_bilan.py

Hors ligne : ni souris, ni jeu, ni OCR easyocr.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import adventure_navigation as an
import bilan

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT / "captures_reference"
DEFAITE = CAPTURES / "bilan_defaite_20261104.png"
VICTOIRE = CAPTURES / "bilan_victoire_20261105.png"
VICTOIRE_DEFI13 = CAPTURES / "victoire_defi13_20261106.png"
AUTRE_ECRAN = CAPTURES / "champions_haut_20261105.png"
CARTE = CAPTURES / "carte_marqueur_20261106.png"
BOUTIQUE = CAPTURES / "boutique_20261105.png"
# Les deux écrans sur lesquels le mot « VICTOIRE » est ÉCRIT sans qu'on
# ait rien gagné : « (22 VICTOIRES TOTALES) », le compteur du palier.
LISTE_DEFIS = CAPTURES / "liste_defis_20261108.png"
REPRISE = CAPTURES / "reprendre_aventure_20261106.png"

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


CREME = (222, 235, 240)             # le crème du « / 20 », mesuré


def _sans_orange(image):
    """
    La même capture, mais avec les PV courants repeints en CRÈME.

    On obtient « 0 / 20 » tout en crème. ATTENTION : ce N'EST PAS un
    nexus intact — c'est une défaite dont le nombre a changé de couleur.
    L'éprouvette sert justement à vérifier qu'on ne confond pas les
    deux : un nexus intact affiche son MAXIMUM à gauche, pas un zéro.
    """
    copie = image.copy()
    hsv = cv2.cvtColor(copie, cv2.COLOR_BGR2HSV)
    masque = cv2.inRange(hsv, bilan.ORANGE_BAS, bilan.ORANGE_HAUT)
    copie[masque > 0] = CREME
    return copie


def _origine_bande(image, centre):
    """Le coin haut-gauche de la bande des PV, en pixels d'écran."""
    hauteur, largeur = image.shape[:2]
    return (max(0, int(centre[0] + bilan.PV_DX[0] * largeur)),
            max(0, int(centre[1] + bilan.PV_DY[0] * hauteur)))


def _nexus_intact(image, centre):
    """
    La même capture, mais la bande affiche « 20 / 20 » tout en crème.

    C'est notre seule façon d'éprouver le cas « nexus intact » : on n'a
    jamais vu de bilan au cœur avec un nexus au maximum — une victoire
    envoie sur l'écran de récompenses. On repeint donc le « 0 » orange
    en crème (il devient le chiffre des unités) et on lui ajoute un
    « 2 » devant, COPIÉ du « 2 » du maximum : bonne police, bonne
    couleur, bonne hauteur.

    Mesuré sur la capture du 04/11, en coordonnées de la bande : le
    « 0 » orange est en x=34, le « / » en x=58, le « 20 » crème en x=76
    et x=94. Le « 2 » recopié tombe donc en x≈16, et la bande se lit
    « 20 / 20 ».

    Ce qu'elle vaut, et ce qu'elle ne vaut pas : elle reproduit une MISE
    EN PAGE, pas une capture. Si le jeu gardait l'orange sur un nexus à
    plein, la branche ne se déclencherait jamais — sans dommage, elle
    rendrait None.
    """
    copie = _sans_orange(image)
    x0, y0 = _origine_bande(copie, centre)
    copie[y0 + 5:y0 + 36, x0 + 12:x0 + 35] = copie[y0 + 5:y0 + 36, x0 + 72:x0 + 95]
    return copie


def _fondu_sur(image, fond, alpha):
    """
    La même capture, fondue sur un AUTRE écran du projet.

    C'est la dégradation que l'assombrissement ne sait pas imiter, et
    c'est la réaliste : un panneau qui s'efface laisse voir l'écran de
    dessous. Le crème est presque blanc, donc peu saturé, et il traverse
    le fondu ; l'orange est reconnu à sa SATURATION, qui s'effondre dès
    qu'on le mélange. L'ordre « le crème meurt avant l'orange », vrai en
    assombrissant, s'INVERSE ici — et c'est tout l'objet de
    `test_un_fondu_enchaine_nefface_que_l_orange`.
    """
    redim = cv2.resize(fond, (image.shape[1], image.shape[0]))
    return cv2.addWeighted(image.astype(np.float32), alpha,
                           redim.astype(np.float32), 1 - alpha, 0).astype(np.uint8)


def _assombri(image, facteur):
    """
    La même capture, mais à `facteur` de sa clarté : un panneau en fondu.

    Le fait de jeu du 08/11/2026 (logs/bot_run.log, 20:53:37 et
    20:53:38) : DEUX lectures du MÊME écran à une seconde d'écart, deux
    réponses contradictoires — « PV illisibles, aucun verdict » puis
    « victoire (bilan : nexus intact) ». Le panneau n'était pas encore
    dessiné ; l'orange des PV courants n'y passait pas le seuil de
    saturation, et l'ABSENCE de chiffre valait victoire.

    Mesuré sur la capture de défaite, en assombrissant par pas de 1 % :
    le « / » crème s'efface dès **0,85**, plus aucun glyphe crème dès
    **0,70**, et l'orange ne disparaît qu'à **0,37**. Autrement dit,
    partout où l'orange manque, le crème manquait déjà : exiger le
    maximum est strictement plus sévère que de se fier à l'absence.
    """
    return (image.astype(np.float32) * facteur).astype(np.uint8)


def test_le_coeur_ancre_l_ecran():
    print("\nL'ancre : le cœur des PV, et lui seul")
    image = _lire(DEFAITE)
    if image is None:
        return
    score, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=image)
    check("le cœur est trouvé sur l'écran de bilan", score is not None and score >= bilan.SEUIL_ANCRE,
          f"score={score}")
    # best_match rend le centre de la BOÎTE du template, pas le centroïde
    # du cœur (mesuré, lui, en (94, 755)) : 7 px plus bas. C'est ce point-là
    # qui ancre la bande des PV, donc c'est lui qu'on verrouille.
    check("et il ancre bien le cœur, en (95, 762)",
          centre is not None and abs(centre[0] - 95) <= 5 and abs(centre[1] - 762) <= 5, centre)

    autre = _lire(AUTRE_ECRAN)
    if autre is None:
        return
    score_autre, _ = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=autre)
    check("et il n'est PAS sur l'écran de sélection du champion",
          score_autre is not None and score_autre < bilan.SEUIL_ANCRE, f"score={score_autre}")


def test_zero_pv_est_une_defaite():
    print("\nPV à 0 : défaite — le combat le plus important cesse d'être muet")
    image = _lire(DEFAITE)
    if image is None:
        return
    verdict = bilan.juger(image)
    check("un verdict est rendu", verdict is not None)
    if verdict is None:
        return
    check("c'est une défaite", verdict.gagne is False, verdict)
    check("les PV lus valent 0", verdict.pv == 0, verdict.pv)
    check("le juge se nomme dans le verdict", "bilan" in verdict.verdict.lower(), verdict.verdict)


def test_le_piege_du_bloc_entier():
    print("\nLe piège : lire tout le bloc « 0 / 20 » ne doit JAMAIS rendre 20")
    image = _lire(DEFAITE)
    if image is None:
        return
    import digits
    score, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=image)
    bande = bilan._bande_pv(image, centre)
    # On VÉRIFIE le piège : la lecture naïve de toute la bande rend le
    # MAXIMUM, parce que digits.glyph_mask exclut l'orange des PV
    # courants. Une implémentation qui ferait ça conclurait « 20 PV donc
    # victoire » sur un écran de défaite.
    #
    # DEPUIS LE 08/11/2026 LE PIÈGE EST DÉSAMORCÉ À LA SOURCE : le « 0 »
    # orange reste invisible au masque, mais il laisse une composante de
    # la taille d'un chiffre que `read_number` ne reconnaît pas — et un
    # glyphe de la taille d'un chiffre qu'on ne sait pas lire REFUSE
    # désormais le nombre entier au lieu d'être sauté. La lecture naïve
    # avoue donc « je ne sais pas ». Ce qui compte n'a pas changé et ne
    # doit jamais changer : elle ne rend pas 20.
    naif = digits.read_number(bande, maximum=99)
    check("la lecture naïve de la bande ne rend surtout pas 20", naif != 20, naif)
    check("et elle avoue ne pas savoir plutôt que d'inventer", naif is None, naif)
    verdict = bilan.juger(image)
    check("le juge, lui, ne tombe pas dedans", verdict is not None and verdict.gagne is False, verdict)


def test_un_nexus_intact_est_une_victoire():
    print("\nLa bande se lit « 20 / 20 » EN ENTIER : le nexus est intact — victoire")
    image = _lire(DEFAITE)
    if image is None:
        return
    _, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=image)
    intact = _nexus_intact(image, centre)

    # L'éprouvette est d'abord vérifiée POUR ELLE-MÊME : si elle ne porte
    # pas « 20 / 20 », le test qui suit ne prouverait rien.
    bande = bilan._bande_pv(intact, centre)
    check("l'éprouvette porte bien « 20 / 20 » en crème",
          bilan._nombres_creme(bande) == (20, 20), bilan._nombres_creme(bande))
    check("et plus un seul chiffre orange à lire",
          len(bilan._glyphes_orange(bande)) == 0)

    verdict = bilan.juger(intact)
    check("un verdict est rendu", verdict is not None)
    if verdict is None:
        return
    check("c'est une victoire", verdict.gagne is True, verdict)
    check("et le verdict dit pourquoi (nexus intact)", "intact" in verdict.verdict.lower(), verdict.verdict)
    # La PREUVE POSITIVE : les DEUX nombres ont été lus, et ils sont ÉGAUX.
    # On rend ce nombre-là comme PV — un nexus intact est un nexus à son
    # maximum, ce n'est pas un trou dans le journal.
    check("et les PV rendus sont le maximum lu (20)", verdict.pv == 20, verdict.pv)

    # ET LE CONTRE-EXEMPLE, à une couleur près : « 0 / 20 » tout en crème
    # n'est PAS un nexus intact. C'était l'ancienne éprouvette du cas
    # « intact », et elle suffisait à décrocher une victoire tant que le
    # seul maximum faisait preuve.
    zero = bilan.juger(_sans_orange(image))
    check("« 0 / 20 » en crème n'est pas un nexus intact — aucun verdict",
          zero is None, zero)


def test_un_panneau_a_moitie_dessine_nest_pas_une_victoire():
    print("\nUn panneau pas encore dessiné : l'ABSENCE de chiffre ne prouve RIEN")
    image = _lire(DEFAITE)
    if image is None:
        return

    # L'ÉPROUVETTE EST UNE VRAIE CAPTURE DE DÉFAITE, assombrie à 35 %.
    # Mesuré : l'orange disparaît sous 0,37, et le cœur reste trouvé à
    # 1.000 — `matchTemplate` en TM_CCOEFF_NORMED est insensible à un
    # facteur de clarté. Donc l'ancre tient, la bande est au bon endroit,
    # et il n'y a plus un seul chiffre : c'est exactement l'état qui
    # faisait écrire « victoire (bilan : nexus intact) » le 08/11/2026
    # sur un écran de DÉFAITE.
    fondu = _assombri(image, 0.35)
    score, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=fondu)
    check("le cœur est toujours trouvé sur le panneau en fondu",
          score is not None and score >= bilan.SEUIL_ANCRE, f"score={score}")
    check("et il n'y a plus aucun chiffre orange à lire",
          len(bilan._glyphes_orange(bilan._bande_pv(fondu, centre))) == 0)

    verdict = bilan.juger(fondu)
    check("AUCUN verdict n'est rendu : une victoire ne se prouve pas par une absence",
          verdict is None, verdict)

    # Et le cas symétrique : tant que l'orange se lit, la défaite se lit.
    # Mesuré, elle tient jusqu'à 0,38 de clarté, bien au-delà du point où
    # le crème a disparu (0,70). On ne durcit QUE la branche « intact ».
    presque = bilan.juger(_assombri(image, 0.40))
    check("une défaite encore lisible reste une défaite",
          presque is not None and presque.gagne is False, presque)


def test_le_maximum_creme_prouve_que_la_bande_est_lue():
    print("\nLe maximum crème : la preuve POSITIVE que le panneau est dessiné")
    defaite = _lire(DEFAITE)
    defi13 = _lire(VICTOIRE_DEFI13)
    if defaite is None:
        return

    _, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=defaite)
    check("« 0 / 20 » : le maximum vaut 20",
          bilan.lire_maximum(bilan._bande_pv(defaite, centre)) == 20,
          bilan.lire_maximum(bilan._bande_pv(defaite, centre)))

    if defi13 is not None:
        # La VRAIE victoire du défi 13 (06/11/2026) : son écran porte le
        # mot « VICTOIRE » ET le cœur, avec « 26 / 63 » — le seul autre
        # bilan chiffré qu'on possède, et un maximum qui n'est pas 20.
        _, c13 = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=defi13)
        bande13 = bilan._bande_pv(defi13, c13)
        check("« 26 / 63 » : le maximum vaut 63",
              bilan.lire_maximum(bande13) == 63, bilan.lire_maximum(bande13))
        courant, maximum, orange = bilan.lire_pv(defi13, c13)
        check("et le courant y vaut 26", courant == 26, courant)
        check("avec son maximum à côté", maximum == 63, maximum)
        check("et deux glyphes oranges comptés", orange == 2, orange)

    # Dès que le panneau se dégrade, le maximum se tait AVANT l'orange :
    # le « / » est le trait le plus fin du bloc. Mesuré : illisible dès
    # 0,85 de clarté, plus un seul glyphe crème dès 0,70.
    bande_fondue = bilan._bande_pv(_assombri(defaite, 0.35), centre)
    check("sur un panneau en fondu, le maximum ne se lit pas",
          bilan.lire_maximum(bande_fondue) is None, bilan.lire_maximum(bande_fondue))
    check("une bande vide ne rend jamais de maximum",
          bilan.lire_maximum(np.zeros((0, 0, 3), np.uint8)) is None)


def test_deux_lectures_du_meme_ecran_ne_se_contredisent_plus():
    print("\nLe couple du 08/11 : « PV illisibles » puis « nexus intact », à 1 s d'écart")
    image = _lire(DEFAITE)
    if image is None:
        return

    # Les deux images sont le MÊME écran de défaite, dans deux états de
    # dessin. Mesuré : floutée, la bande garde son glyphe orange mais ne
    # le lit plus (-> le WARNING de 20:53:37) ; assombrie, l'orange a
    # disparu (-> le « victoire : nexus intact » de 20:53:38). Le juge
    # regardant pendant plusieurs secondes, il voyait fatalement la
    # seconde — et une tentative perdue entrait au journal en VICTOIRE.
    flou = cv2.GaussianBlur(image, (7, 7), 0)
    fondu = _assombri(image, 0.35)
    _, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=flou)
    check("image A : l'orange est là mais ne se lit pas",
          len(bilan._glyphes_orange(bilan._bande_pv(flou, centre))) == 1
          and bilan.lire_pv(flou, centre)[0] is None)
    check("image B : plus d'orange du tout",
          len(bilan._glyphes_orange(bilan._bande_pv(fondu, centre))) == 0)

    class HorlogeFausse:
        def __init__(self): self.t = 0.0
        def time(self): return self.t
        def sleep(self, d): self.t += d

    vrai_capture, vrai_temps = bilan.an._capture_screen_bgr, bilan.time
    try:
        ecrans = [flou, fondu] * 20
        bilan.an._capture_screen_bgr = lambda: ecrans.pop(0) if ecrans else fondu
        bilan.time = HorlogeFausse()
        check("le juge regarde les deux et ne conclut RIEN",
              bilan.attendre_verdict() is None)
    finally:
        bilan.an._capture_screen_bgr, bilan.time = vrai_capture, vrai_temps


def test_un_fondu_enchaine_nefface_que_l_orange():
    print("\nLe fondu enchaîné : l'orange meurt AVANT le crème — l'inverse de l'assombrissement")
    image = _lire(DEFAITE)
    if image is None:
        return
    _, centre = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=image)

    # LE FAIT QUI A FAIT ÉCHOUER LA PREMIÈRE RÉPARATION. Elle se fiait au
    # MAXIMUM crème pour attester que le panneau était dessiné, sur la foi
    # d'un assombrissement : le crème y meurt à 0,70, l'orange à 0,37,
    # donc « partout où l'orange manque, le crème manquait déjà ».
    #
    # Un panneau réel ne s'efface pas vers le noir, il laisse voir l'écran
    # de DESSOUS. Le crème est presque blanc, donc peu saturé, et il
    # traverse le fondu ; l'orange est reconnu à sa SATURATION, qui
    # s'effondre dès qu'on le mélange. L'ordre s'inverse, et avec lui tout
    # l'argument. On fige ici les deux faits : l'inversion elle-même, et
    # le fait que le juge n'en rende plus de verdict.
    for nom, chemin in (("la carte d'aventure", CARTE), ("la boutique", BOUTIQUE)):
        fond = _lire(chemin)
        if fond is None:
            continue
        inversions, lectures = [], []
        for pas in range(45, 19, -1):
            alpha = pas / 100.0
            melange = _fondu_sur(image, fond, alpha)
            bande = bilan._bande_pv(melange, centre)
            orange = len(bilan._glyphes_orange(bande))
            courant, maximum = bilan._nombres_creme(bande)
            if orange == 0 and maximum is not None:
                inversions.append(alpha)
                lectures.append((courant, maximum))
        check(f"sur {nom}, il existe bien des opacités où l'orange a disparu "
              f"mais où le maximum se lit encore",
              len(inversions) > 0, inversions)
        # Et dans AUCUNE la bande ne se lit « N / N ». Les deux façons d'y
        # échouer se rencontrent pour de vrai, et il faut les deux :
        #   - sur la carte, rien à gauche du séparateur (le zéro est
        #     orange, donc absent du masque crème) -> courant None ;
        #   - sur la boutique, le zéro désaturé FINIT par entrer dans le
        #     masque crème et se lit « 0 » -> courant 0, et c'est
        #     l'ÉGALITÉ qui refuse, pas l'illisibilité.
        # C'est pour ce second cas que la règle est « courant == maximum »
        # et non « courant lisible ».
        check(f"et la bande ne s'y lit JAMAIS « N / N »",
              all(courant != maximum for courant, maximum in lectures), lectures)

    # Enfin le juge lui-même, sur les deux opacités les plus traîtresses :
    # le cœur y est encore à 0,95-0,99, donc l'ancre tient et la bande est
    # au bon endroit. C'est exactement l'état qui rendait « victoire
    # (nexus intact, 20/20) » sur un écran affichant 0 PV.
    for chemin, alpha in ((CARTE, 0.35), (CARTE, 0.25), (BOUTIQUE, 0.35), (BOUTIQUE, 0.25)):
        fond = _lire(chemin)
        if fond is None:
            continue
        melange = _fondu_sur(image, fond, alpha)
        score, _ = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=melange)
        check(f"à {alpha:.2f} d'opacité le cœur est toujours trouvé",
              score is not None and score >= bilan.SEUIL_ANCRE, f"score={score}")
        verdict = bilan.juger(melange)
        check(f"et AUCUNE victoire n'y est prononcée sur un écran à 0 PV",
              verdict is None or verdict.gagne is False, verdict)


def test_la_victoire_est_un_AUTRE_ecran():
    print("\nLa victoire : un écran de récompenses, sans cœur ni PV")
    image = _lire(VICTOIRE)
    if image is None:
        return
    # Le fait de jeu du 05/11/2026 : gagner ne mène PAS au bilan au cœur.
    # Si ce test tombe, c'est que le jeu a changé d'écran, pas que le code
    # est cassé.
    score_coeur, _ = an.best_match(an.TEMPLATES[bilan.ANCRE], screen=image)
    check("pas de cœur sur l'écran de victoire — les deux écrans diffèrent",
          score_coeur is not None and score_coeur < bilan.SEUIL_ANCRE, f"score={score_coeur}")

    verdict = bilan.juger(image)
    check("un verdict est rendu", verdict is not None)
    if verdict is None:
        return
    check("c'est une victoire", verdict.gagne is True, verdict)
    check("aucun PV n'est inventé", verdict.pv is None, verdict.pv)

    defaite = _lire(DEFAITE)
    if defaite is not None:
        score, _ = an.best_match(an.TEMPLATES[bilan.ANCRE_VICTOIRE], screen=defaite)
        check("et le mot « VICTOIRE » ne se trouve PAS sur l'écran de défaite",
              score is not None and score < bilan.SEUIL_ANCRE, f"score={score}")


def _decale(image, dx, dy):
    """La même capture, glissée de quelques pixels — un écran qui bouge."""
    matrice = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(image, matrice, (image.shape[1], image.shape[0]))


def test_le_mot_victoire_doit_etre_a_sa_place():
    print("\n« 22 VICTOIRES TOTALES » n'est pas une victoire : le mot doit être À SA PLACE")

    # LE FAIT DE JEU (08/11/2026). Le gabarit du mot « VICTOIRE » est
    # trouvé, bien au-dessus du seuil, sur DEUX écrans que le bot traverse
    # à chaque tentative : la liste des défis et le panneau de reprise
    # d'aventure. Ce qu'il y lit est le compteur « XP DE DÉFI (22
    # VICTOIRES TOTALES) » — même police, même casse, même mot au pluriel
    # près — à 650 px de l'endroit où un vrai écran de victoire l'écrit.
    #
    # Ce n'est pas un écran rare : la trace du 08/11 montre « Bilan de fin
    # lu à l'écran : victoire (écran de fin de défi) » à 20:53:48, suivi
    # UNE SECONDE plus tard de « Écran connu retrouvé : liste des défis
    # actifs ». Et `attendre_verdict` REGARDE pendant huit secondes.
    #
    # C'est la leçon du marqueur du joueur, à la lettre : un bon score ne
    # prouve que la fidélité du gabarit, jamais la justesse de la lecture.
    for nom, chemin in (("la liste des défis", LISTE_DEFIS),
                        ("le panneau de reprise", REPRISE)):
        image = _lire(chemin)
        if image is None:
            continue
        score, point = an.best_match(an.TEMPLATES[bilan.ANCRE_VICTOIRE], screen=image)
        # On vérifie d'abord que le DÉFAUT est bien là : si ce test devait
        # tomber un jour, il faut savoir si c'est le gabarit qui a cessé
        # de matcher (alors le test ne prouve plus rien) ou le juge qui
        # s'est corrigé.
        check(f"sur {nom}, le gabarit passe toujours le seuil — le piège est réel",
              score is not None and score >= bilan.SEUIL_ANCRE, f"score={score}")
        check(f"et il le trouve loin de sa place, en {point}",
              point is not None and abs(point[1] - 119) > 400, point)
        rendu = bilan.juger(image)
        check(f"MAIS le juge ne prononce AUCUN verdict sur {nom}", rendu is None, rendu)

    # ET LA NON-RÉGRESSION : les deux vrais écrans de victoire du projet
    # restent des victoires. Le mot y est mesuré AU PIXEL près au même
    # endroit, (272, 119) sur 1920×1080, sur les onze captures de victoire
    # du dépôt — défi 2 à un chiffre comme défi 13 à deux : le numéro ne
    # pousse pas le mot, il est sur une autre ligne.
    for nom, chemin in (("l'écran de récompenses du 05/11", VICTOIRE),
                        ("la victoire du défi 13", VICTOIRE_DEFI13)):
        image = _lire(chemin)
        if image is None:
            continue
        score, point = an.best_match(an.TEMPLATES[bilan.ANCRE_VICTOIRE], screen=image)
        check(f"sur {nom}, le mot est bien en (272, 119)",
              point is not None and abs(point[0] - 272) <= 5 and abs(point[1] - 119) <= 5,
              point)
        verdict = bilan.juger(image)
        check(f"et {nom} reste une VICTOIRE",
              verdict is not None and verdict.gagne is True, verdict)

    # ON NE DURCIT PAS AU POINT DE REFUSER UN ÉCRAN QUI BOUGE. La
    # tolérance vaut DEUX tailles de gabarit (135×46 px), soit ±270 px en
    # largeur et ±92 px en hauteur sur 1920×1080 ; le faux positif, lui,
    # est à 647 px — quatorze hauteurs de gabarit.
    image = _lire(VICTOIRE)
    if image is not None:
        glisse = _decale(image, 40, 30)
        score, _ = an.best_match(an.TEMPLATES[bilan.ANCRE_VICTOIRE], screen=glisse)
        check("un écran de victoire glissé de 40×30 px : le mot est toujours lu",
              score is not None and score >= bilan.SEUIL_ANCRE, f"score={score}")
        verdict = bilan.juger(glisse)
        check("et il reste une victoire — on ne refuse pas un écran qui bouge",
              verdict is not None and verdict.gagne is True, verdict)

    # ON RAISONNE EN RATIOS, PAS EN PIXELS : un point absolu ne vaudrait
    # rien le jour où le jeu tournerait dans une autre résolution. Les
    # mêmes ratios, sur un écran de 1280×720.
    petit = np.zeros((720, 1280, 3), np.uint8)
    place = (int(bilan.POSITION_VICTOIRE[0] * 1280), int(bilan.POSITION_VICTOIRE[1] * 720))
    ailleurs = (int(0.2359 * 1280), int(0.7093 * 720))
    check(f"en 1280×720, {place} est à sa place",
          bilan._a_sa_place(petit, place, bilan.POSITION_VICTOIRE, bilan.TOLERANCE_VICTOIRE),
          place)
    check(f"et {ailleurs} — le compteur du palier — ne l'est pas",
          not bilan._a_sa_place(petit, ailleurs, bilan.POSITION_VICTOIRE,
                                bilan.TOLERANCE_VICTOIRE),
          ailleurs)
    check("un point absent n'est jamais à sa place",
          not bilan._a_sa_place(petit, None, bilan.POSITION_VICTOIRE,
                                bilan.TOLERANCE_VICTOIRE))

    # ENFIN LE SCÉNARIO DE TERRAIN : le juge regarde pendant huit
    # secondes, et c'est la liste des défis qui s'affiche. Il doit
    # renoncer, pas enregistrer une victoire — `journal.conclude` écrit
    # ce verdict dans journal.jsonl, d'où sort `journal.py --champions`,
    # d'où sort la table `champions.etoiles_requises`.
    liste = _lire(LISTE_DEFIS)
    if liste is None:
        return

    class HorlogeFausse:
        def __init__(self): self.t = 0.0
        def time(self): return self.t
        def sleep(self, d): self.t += d

    vrai_capture, vrai_temps = bilan.an._capture_screen_bgr, bilan.time
    try:
        bilan.an._capture_screen_bgr = lambda: liste
        bilan.time = HorlogeFausse()
        attendu = bilan.attendre_verdict()
        check("huit secondes devant la liste des défis : aucun verdict",
              attendu is None, attendu)
    finally:
        bilan.an._capture_screen_bgr, bilan.time = vrai_capture, vrai_temps


def _fondu_entre(avant, apres, alpha):
    """Les deux écrans superposés : la transition de l'un vers l'autre."""
    return cv2.addWeighted(avant.astype(np.float32), alpha,
                           apres.astype(np.float32), 1 - alpha, 0).astype(np.uint8)


def test_un_concurrent_lointain_ne_masque_pas_le_vrai_mot():
    print(chr(10) + "Le compteur ne doit pas MASQUER le vrai mot : on cherche DANS la zone")

    # LE REVERS DU GARDE-FOU, mesuré (08/11/2026). `best_match` ne rend
    # que son ARGMAX. Chercher le mot sur tout l'écran puis refuser le
    # point hors de sa place marche tant que le vrai mot est le plus net —
    # mais dès qu'il faiblit, le compteur « VICTOIRES TOTALES » rafle
    # l'argmax et le juge ne voit même plus le mot qui est pourtant là, au
    # bon endroit, au-dessus du seuil. Une victoire RÉELLE se perdait en
    # silence.
    #
    # L'éprouvette est la transition même qui a motivé le garde-fou : la
    # victoire du boss final s'efface, la liste des défis apparaît. C'est
    # ce que le bot regarde pendant huit secondes.
    victoire = _lire(VICTOIRE)
    liste = _lire(LISTE_DEFIS)
    if victoire is None or liste is None:
        return

    melange = _fondu_entre(victoire, liste, 0.65)
    score, point = an.best_match(an.TEMPLATES[bilan.ANCRE_VICTOIRE], screen=melange)
    # (1) le piège est réel : l'argmax de l'écran entier est le COMPTEUR.
    check("à 0,65 d'opacité, l'argmax de l'écran entier est bien le compteur",
          point is not None and abs(point[1] - 119) > 400, (score, point))
    # (2) et pourtant le mot est là, à sa place, au-dessus du seuil.
    zone, pz = bilan._mot_de_victoire(melange)
    check("mais le mot est lu à SA place, au-dessus du seuil",
          zone is not None and zone >= bilan.SEUIL_ANCRE
          and bilan._a_sa_place(melange, pz, bilan.POSITION_VICTOIRE,
                                bilan.TOLERANCE_VICTOIRE), (zone, pz))
    # (3) donc le juge doit la prononcer.
    verdict = bilan.juger(melange)
    check("et le juge prononce la victoire — elle ne se perd pas en route",
          verdict is not None and verdict.gagne is True, verdict)

    # ET L'AUTRE BOUT : quand le mot a vraiment disparu, le compteur ne le
    # remplace pas. C'est le même écran, plus effacé — l'écran est alors
    # pour l'essentiel la liste des défis, et une liste des défis n'est
    # pas un verdict.
    efface = _fondu_entre(victoire, liste, 0.40)
    zone_efface, _ = bilan._mot_de_victoire(efface)
    check("à 0,40 d'opacité, le mot n'est plus lisible à sa place",
          zone_efface is not None and zone_efface < bilan.SEUIL_ANCRE, zone_efface)
    check("et AUCUN verdict n'est rendu — surtout pas depuis le compteur",
          bilan.juger(efface) is None, bilan.juger(efface))

    # LA RECHERCHE EN ZONE NE CHANGE PAS CE QU'ON LIT, elle change
    # seulement ce qui peut le cacher : sur un vrai écran de victoire, le
    # score et le point sont les mêmes que sur l'écran entier.
    plein, point_plein = an.best_match(an.TEMPLATES[bilan.ANCRE_VICTOIRE], screen=victoire)
    en_zone, point_zone = bilan._mot_de_victoire(victoire)
    check("sur un vrai écran de victoire, zone et écran entier disent la même chose",
          abs(plein - en_zone) < 1e-6 and point_plein == point_zone,
          (plein, point_plein, en_zone, point_zone))


def test_aucune_autre_capture_de_reference_ne_gagne():
    print("\nSur les 35 captures de référence, DEUX seulement sont des victoires")
    # La vraie non-régression n'est pas « ces deux écrans-ci » mais la
    # MARGE sur toute la population qu'on possède. Mesuré en restreignant
    # la recherche à la zone attendue : pire vrai positif 0.983, meilleur
    # score de n'importe quel autre écran 0.456 — 0.53 de marge, contre
    # 0.12 pour un seuil tout seul (0.983 contre 0.862).
    gagnantes = set()
    vues = 0
    for chemin in sorted(CAPTURES.glob("*.png")):
        image = cv2.imread(str(chemin))
        if image is None:
            continue
        vues += 1
        verdict = bilan.juger(image)
        if verdict is not None and verdict.gagne:
            gagnantes.add(chemin.name)
    check("les 35 captures de référence ont été relues", vues >= 30, vues)
    check("et seules les deux vraies victoires en sont",
          gagnantes == {VICTOIRE.name, VICTOIRE_DEFI13.name}, sorted(gagnantes))


def test_un_ecran_qui_arrive_en_retard_est_quand_meme_lu():
    print(chr(10) + "L'écran de verdict arrive en retard : on REGARDE, on ne juge pas une image")
    victoire = _lire(VICTOIRE)
    autre = _lire(AUTRE_ECRAN)
    if victoire is None or autre is None:
        return

    # Le fait mesuré en jeu le 05/11/2026 : second « Continuer » cliqué à
    # 15:05:31, juge appelé à 15:05:40 sur un écran encore muet, écran de
    # victoire affiché à 15:05:47. Une seule image, c'était pile ou face.
    class HorlogeFausse:
        def __init__(self): self.t = 0.0
        def time(self): return self.t
        def sleep(self, d): self.t += d

    vrai_capture, vrai_temps = bilan.an._capture_screen_bgr, bilan.time
    try:
        ecrans = [autre, autre, autre, autre, autre, autre, victoire]
        bilan.an._capture_screen_bgr = lambda: ecrans.pop(0) if ecrans else victoire
        bilan.time = HorlogeFausse()
        verdict = bilan.attendre_verdict()
        check("l'écran tardif finit par être lu", verdict is not None and verdict.gagne is True,
              verdict)

        # Et l'attente est BORNÉE : un écran qui ne dit jamais rien ne
        # bloque pas la fin d'aventure.
        bilan.an._capture_screen_bgr = lambda: autre
        bilan.time = HorlogeFausse()
        check("un écran qui ne dit jamais rien : on renonce, sans inventer",
              bilan.attendre_verdict() is None)
    finally:
        bilan.an._capture_screen_bgr, bilan.time = vrai_capture, vrai_temps


def test_un_ecran_quelconque_ne_juge_rien():
    print("\nAilleurs, le juge se tait — il n'invente jamais de verdict")
    autre = _lire(AUTRE_ECRAN)
    if autre is not None:
        check("écran de sélection du champion -> aucun verdict", bilan.juger(autre) is None)
    bruit = np.random.default_rng(7).integers(0, 255, size=(1080, 1920, 3), dtype=np.uint8)
    check("bruit -> aucun verdict", bilan.juger(bruit) is None)
    check("image vide -> aucun verdict", bilan.juger(np.zeros((4, 4, 3), np.uint8)) is None)
    # ET IL NE LÈVE PAS NON PLUS. Le plancher de 80 px laissait passer des
    # images plus petites que les gabarits (le mot fait 135 px de large,
    # le cœur 86) et `cv2.matchTemplate` lève sur ce cas : le juge
    # PLANTAIT entre 85 et 134 px de côté. Jamais vu en jeu — on capture
    # l'écran entier — mais « illisible n'est pas un verdict » ne veut pas
    # dire « illisible est une exception ».
    for cote in (85, 100, 134):
        try:
            rendu = bilan.juger(np.zeros((cote, cote, 3), np.uint8))
        except Exception as erreur:          # noqa: BLE001 — c'est le défaut testé
            rendu = erreur
        check(f"une image de {cote} px ne fait pas lever le juge", rendu is None, rendu)


def main():
    for test in (test_le_coeur_ancre_l_ecran,
                 test_zero_pv_est_une_defaite,
                 test_le_piege_du_bloc_entier,
                 test_un_nexus_intact_est_une_victoire,
                 test_un_panneau_a_moitie_dessine_nest_pas_une_victoire,
                 test_le_maximum_creme_prouve_que_la_bande_est_lue,
                 test_deux_lectures_du_meme_ecran_ne_se_contredisent_plus,
                 test_un_fondu_enchaine_nefface_que_l_orange,
                 test_la_victoire_est_un_AUTRE_ecran,
                 test_le_mot_victoire_doit_etre_a_sa_place,
                 test_un_concurrent_lointain_ne_masque_pas_le_vrai_mot,
                 test_aucune_autre_capture_de_reference_ne_gagne,
                 test_un_ecran_qui_arrive_en_retard_est_quand_meme_lu,
                 test_un_ecran_quelconque_ne_juge_rien):
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
