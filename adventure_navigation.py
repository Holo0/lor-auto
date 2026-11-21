import cv2
import numpy as np
import time
import math
import logging
import os
import pyautogui
from pathlib import Path

# ============================================================
# TEMPLATES
# ============================================================

# CHEMIN ABSOLU, ET C'EST VOLONTAIRE : "assets" en relatif ne marchait
# que si le bot était lancé depuis la racine du projet, et un raccourci
# Windows ou un `python "chemin\\complet\\challenges.py"` suffisait à
# rendre TOUS les templates introuvables — donc à ne rien reconnaître,
# sans que rien n'indique pourquoi.
ASSETS_DIR = str(Path(__file__).resolve().parent / "assets")
# Les captures sur lesquelles les tests s'appuient, et dont on redécoupe
# les gabarits : elles ne s'effacent pas avec `screenshots/`.
CAPTURES_DIR = str(Path(__file__).resolve().parent / "captures_reference")
MATCH_THRESHOLD = 0.80

TEMPLATES = {
    "monthly_challenge": os.path.join(ASSETS_DIR, "monthly_challenge.png"),
    "active_encounter": os.path.join(ASSETS_DIR, "active_encounter.png"),

    "first_champion": os.path.join(ASSETS_DIR, "first_champion.png"),

    # LE BILAN DE FIN DE TENTATIVE (05/11/2026). Le grand cœur des PV
    # ancre l'écran que le bot photographiait sous le nom « écran
    # inconnu » sans jamais le lire — alors qu'il porte le verdict du
    # boss final, le seul combat que rien d'autre ne juge. Voir bilan.py.
    "bilan_coeur": os.path.join(ASSETS_DIR, "bilan_coeur.png"),
    # Le mot « VICTOIRE » du bilan. L'écran de VICTOIRE n'est PAS
    # celui de la défaite (constaté en jeu le 05/11/2026) : c'est un
    # écran de récompenses, sans cœur ni PV. Le gabarit exclut
    # « DÉFI 2 » — le numéro change d'un défi à l'autre.
    "bilan_victoire": os.path.join(ASSETS_DIR, "bilan_victoire.png"),

    # LE CHAMPION ÉPUISÉ (05/11/2026). Chaque champion ne peut servir
    # que TROIS fois par mois ; sans tentative il est grisé, renvoyé en
    # fin de liste, et son bandeau dit « TENTATIVES ÉPUISÉES » au lieu
    # de « N/3 tentatives ». Le grisage ne désature PAS ses étoiles —
    # elles sont comptées comme les autres — d'où ce repère. Voir
    # champions.py.
    "champion_epuise": os.path.join(ASSETS_DIR, "champion_epuise.png"),

    # LE TITRE DU COFFRE (05/11/2026, Ewan : « tu peux savoir le type
    # de coffre, c'est écrit »). Il y a plusieurs sortes de coffres et
    # elles n'ont pas la même mise en page : « Coffre d'objets de
    # champion » demande DEUX clics (un champion, puis un buff). On lit
    # donc le titre avant d'appliquer une géométrie. 1.00 sur ce
    # panneau, 0.28 ailleurs. Voir events.py.
    "coffre_objets_champion": os.path.join(ASSETS_DIR, "coffre_objets_champion.png"),

    # LA RÉCOMPENSE DU BOSS INTERMÉDIAIRE (05/11/2026, Ewan) : un objet
    # à équiper sur l'un de ses champions, offert AUTOMATIQUEMENT après
    # la victoire — donc hors de tout nœud, là où rien ne regardait.
    # Son « Sélectionner » est dans un état que select_button.png ne
    # reconnaît pas (0.52, sous le seuil) : le bot ne voyait pas même
    # le bouton. 1.00 sur ce panneau, <= 0.45 partout ailleurs.
    "recompense_select": os.path.join(ASSETS_DIR, "recompense_select.png"),
    # LE MÊME BOUTON, GRISÉ — quand rien n'est encore choisi. Découpé
    # le 06/11/2026 : le gabarit doré n'y note que 0.42, et le bot
    # restait bloqué sur « RÉCOMPENSES DE COMBAT » faute de voir le
    # bouton. Un repère par ÉTAT, pas un seul.
    "recompense_select_grise": os.path.join(ASSETS_DIR, "recompense_select_grise.png"),

    # LE NŒUD À OPTIONS (soigneur, 06/11/2026). Son bouton porte le
    # NOM de l'option choisie — « Soins », pas « Sélectionner » — donc
    # aucun gabarit de libellé ne le reconnaît : trois d'entre eux
    # convergeaient sur (1441,1002) à 0.75, tous sous le seuil, et le
    # bot restait planté. L'invite « Choisissez-en 1. », elle, est
    # GÉNÉRIQUE : 1.00 ici, <= 0.33 sur les cinq autres captures.
    "choisissez_en_un": os.path.join(ASSETS_DIR, "choisissez_en_un.png"),
    "use_attempt": os.path.join(ASSETS_DIR, "use_attempt.png"),
    "retry": os.path.join(ASSETS_DIR, "retry.png"),
    "continue_button_after_combat": os.path.join(ASSETS_DIR, "continue_button_after_combat.png"),

    "select_button": os.path.join(ASSETS_DIR, "select_button.png"),
    "quit_button": os.path.join(ASSETS_DIR, "quit_button.png"),
    "combat_button": os.path.join(ASSETS_DIR, "combat_button.png"),
    "continue_button": os.path.join(ASSETS_DIR, "continue_button.png"),
    "voyage_button": os.path.join(ASSETS_DIR, "voyage_button.png"),
    "event_option": os.path.join(ASSETS_DIR, "event_option.png"),

    # LE COFFRE D'OBJETS. Découverts le 04/11/2026 : sans ces deux
    # repères, le bot ne VOYAIT pas « Ouvrir le trésor » et seul
    # `quit_button` passait le seuil (0.98) — il refermait donc le coffre
    # et renonçait à un objet permanent + une copie de carte, à chaque
    # nœud de ce type. Scores croisés mesurés sur la capture d'origine :
    # treasure_button 1.00 sur « Ouvrir » / 0.41 sur « Quitter », et
    # l'inverse pour quit_button — aucune confusion possible.
    "treasure_button": os.path.join(ASSETS_DIR, "treasure_button.png"),
    "take_treasure_button": os.path.join(ASSETS_DIR, "take_treasure_button.png"),

    # DANS "nodes/", PAS À LA RACINE : ce fichier-là n'a jamais existé à
    # la racine, donc ce repère renvoyait « Template manquant » depuis
    # toujours. Il sert à reconnaître qu'on est sur une carte d'aventure
    # (cf. navigate.SCREEN_ANCHORS) ; le dossier entier, lui, est scanné
    # séparément par find_nodes_in_folder pour CHOISIR un node.
    # LES QUATRE SUIVANTS NE DÉCIDENT PLUS RIEN. Ils décrivaient le
    # CONTENU d'un nœud (un boss, un événement), qui change d'une semaine
    # à l'autre ; la navigation repère désormais les nœuds aux marques du
    # jeu (cf. navigate.run_adventure). Gardés parce que
    # `navigate.py where` les affiche : voir qu'un boss est reconnu à 0.91
    # ou à 0.31 reste un renseignement.
    "normal_node": os.path.join(ASSETS_DIR, "nodes", "normal_node.png"),
    "enemy_node": os.path.join(ASSETS_DIR, "enemy_node.png"),
    "secondary_enemy_node": os.path.join(ASSETS_DIR, "secondary_enemy_node.png"),

    # Défi hebdomadaire
    "support_champion": os.path.join(ASSETS_DIR, "support_champion_node.png"),
    # LE NŒUD DU BOSS FINAL, DANS SES TROIS ÉTATS (08/11/2026). Le gabarit
    # d'avant était la CRÊTE dorée du médaillon, halo bleu compris : il ne
    # reconnaissait le nœud que JOIGNABLE (0.87) et ratait les deux autres
    # états — 0.59 sans halo (route bloquée), 0.33 une fois le voyage fait,
    # parce que NOTRE portrait de champion vient se poser juste au-dessus du
    # nœud courant et couvre exactement cette crête. D'où « boss final :
    # introuvable », trois essais, aventure abandonnée. Voir `masque_or` et
    # `decouper_final_boss` plus bas : on compare désormais l'OR du
    # médaillon — les deux ailes et l'anneau, qu'aucun des trois états ne
    # cache — et le halo, le portrait du boss et la crête sont hors masque.
    "final_boss": os.path.join(ASSETS_DIR, "final_boss.png"),

    # OÙ NOUS SOMMES SUR LA CARTE : le losange doré à intérieur sombre que
    # le jeu dessine sous notre portrait. Il ne dépend pas du champion joué
    # (le portrait, lui, change à chaque run) et n'embarque presque pas de
    # fond. Sert à choisir le nœud SUIVANT parmi les candidats
    # (cf. pick_next_node) : la carte se recentre sur nous après chaque
    # « Voyage », donc une position mémorisée ne vaudrait rien — il faut la
    # relire sur la même capture que les nœuds.
    "player_marker": os.path.join(ASSETS_DIR, "player_marker.png"),

    # UNE AVENTURE EN COURS, VUE DEPUIS LES MENUS (06/11/2026). Sur le
    # panneau du défi, là où s'affiche d'habitude « UTILISER UNE
    # TENTATIVE », le bouton porte « REPRENDRE L'AVENTURE » — même cadre,
    # même place, autre libellé. Le gabarit est pris sur le LIBELLÉ seul,
    # le cadre étant commun aux deux : 1.00 sur la capture du blocage,
    # ≤ 0.33 sur les douze autres captures de référence.
    "reprendre_aventure": os.path.join(ASSETS_DIR, "reprendre_aventure.png"),
}

# ============================================================
# LE NŒUD DU BOSS FINAL : UN GABARIT POUR SES TROIS ÉTATS
# ============================================================
#
# Mesuré le 08/11/2026 sur les 851 captures 1920×1080 du projet. Le nœud
# du boss se présente de TROIS façons, et l'ancien gabarit — la crête
# dorée du médaillon, prise avec son halo — n'en reconnaissait qu'une :
#
#     route bloquée, pas de halo ......... 0.59   (au bon endroit)
#     joignable, halo bleu ............... 0.87   (l'état d'où il venait)
#     nœud courant, notre portrait dessus  0.33   (au bon endroit ; le
#                                                  0.54 rendu tombait à
#                                                  970 px de là)
#
# Deux causes, et une seule des deux comptait vraiment :
#
# 1. LE DÉCOR DANS LA BOÎTE. Même défaut que `player_marker` le 06/11 :
#    la boîte portait le halo bleu, qui n'existe que dans l'état
#    « joignable ». C'est lui qui faisait la différence entre 0.87 et
#    0.59, bloqué ou non — le médaillon, lui, est identique.
# 2. NOTRE PORTRAIT PAR-DESSUS. Une fois le voyage fait, le jeu dessine
#    notre champion juste au-dessus du nœud : il couvre ENTIÈREMENT la
#    crête, c'est-à-dire exactement ce que l'ancien gabarit comparait.
#    Un masque ne rattrape pas une forme cachée ; il faut comparer
#    AUTRE CHOSE.
#
# Ce qu'aucun des trois états ne touche, ce sont les DEUX AILES dorées et
# l'ANNEAU du médaillon. D'où le gabarit : la boîte de l'emblème, moins
# sa crête, masquée à l'OR (`masque_or`). Hors masque, donc : le halo, le
# fond de carte, et le portrait du boss au centre — qui change à chaque
# aventure et n'a jamais rien eu à dire sur « est-ce le boss ? ».
#
# Ce que ça donne sur les mêmes captures : 0.99 bloqué, 1.00 joignable,
# 0.84 sous le portrait. Et sur les 851 captures, plus rien au-dessus de
# 0.80 qui ne soit un vrai nœud de boss (11 positions, quatre boss
# différents) ; les 525 captures de combat plafonnent à 0.53.
#
# L'ÉCHELLE, ELLE, N'EST PAS FIXE : la carte ne se contente pas de se
# recentrer après un voyage, elle zoome parfois. Mesuré sur
# `carte_boss_courant_zoom_20261106.png` : le même nœud y est 8 % plus
# grand, et à l'échelle 1.00 le gabarit n'y note que 0.50 — à 1.08, 0.83.
# C'est la seule différence avec `player_marker`, pour qui le
# multi-échelle ne rattrapait rien.
BOSS_BOITE = (1227, 186, 1387, 296)
BOSS_OR_HSV = ((12, 70, 80), (36, 255, 255))

# Le zoom mesuré sur le corpus vaut 1.00 ou 1.08 ; on balaie un cran de
# part et d'autre, par pas de 4 %. Plus serré ne sert à rien (le pic est
# large de ~4 %), plus large coûte du temps pour rien.
BOSS_ECHELLES = (1.00, 1.04, 1.08, 1.12, 0.96, 0.92)

# Les gabarits qui se cherchent à plusieurs échelles, et lesquelles. Tous
# les autres — l'immense majorité — gardent le chemin d'avant, à
# l'identique : le multi-échelle coûte cher et ne rattrape presque jamais
# rien (mesuré pour `player_marker` le 06/11, meilleure échelle 1.00
# partout).
ECHELLES_PAR_GABARIT = {
    TEMPLATES["final_boss"]: BOSS_ECHELLES,
}


def masque_or(boite):
    """
    Le masque de l'OR d'un médaillon de boss : ailes et anneau.

    On prend la couleur, pas une géométrie dessinée à la main : l'or du
    cadre est la seule chose que les trois états ont en commun, et il se
    décrit en une plage HSV. Le reste de la boîte — halo, fond de carte,
    portrait du boss — en sort tout seul.
    """
    hsv = cv2.cvtColor(boite, cv2.COLOR_BGR2HSV)
    bas, haut = BOSS_OR_HSV
    masque = cv2.inRange(hsv, np.array(bas, np.uint8), np.array(haut, np.uint8))
    # Fermeture puis ouverture : boucher les trous d'un pixel laissés par
    # les reflets, puis jeter les grains isolés du fond.
    noyau = np.ones((3, 3), np.uint8)
    masque = cv2.morphologyEx(masque, cv2.MORPH_CLOSE, noyau)
    masque = cv2.morphologyEx(masque, cv2.MORPH_OPEN, noyau)
    return masque


def decouper_final_boss(capture=None, sortie=None):
    """
    Refait `assets/final_boss.png` à partir d'une capture de référence.

    `assets/` N'EST PAS VERSIONNÉ : le masque de ce gabarit disparaît avec
    le dossier, et sans lui le bot retombe sur le bogue du 08/11 (« boss
    final introuvable » une fois le voyage fait). Cette fonction est la
    recette, en une ligne :

        python -c "import adventure_navigation as an; an.decouper_final_boss()"

    La capture par défaut est celle de `captures_reference/`, qui est
    gardée justement pour ça — aucune souris, aucune capture d'écran.
    """
    if capture is None:
        capture = os.path.join(CAPTURES_DIR, "carte_boss_joignable_20261108.png")
    if sortie is None:
        sortie = TEMPLATES["final_boss"]
    ecran = cv2.imread(str(capture))
    if ecran is None:
        raise FileNotFoundError(f"Capture de référence illisible : {capture}")
    x0, y0, x1, y1 = BOSS_BOITE
    boite = ecran[y0:y1, x0:x1]
    cv2.imwrite(sortie, np.dstack([boite, masque_or(boite)]))
    return sortie


# ============================================================
# TEMPLATE MATCHING
# ============================================================

def _capture_screen_bgr():
    screenshot = pyautogui.screenshot()
    screenshot_np = np.array(screenshot)
    return cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)


def best_match(template_path, screen=None):
    """
    Meilleure correspondance d'un template : (score, centre).

    Rend le SCORE et pas seulement un verdict, et c'est tout l'intérêt :
    « écran inconnu » sans chiffre est un diagnostic muet. Avec le score,
    on sait si le template est à recadrer (0.6, il y est presque) ou si
    l'écran n'est simplement pas celui-là (0.2).

    Rend (None, None) si le template est absent ou illisible — une
    absence n'est pas un mauvais score, et les confondre ferait chercher
    un problème de cadrage là où il manque un fichier.

    `screen` : image déjà capturée, à réutiliser. Comparer plusieurs
    templates à la MÊME image coûte une capture au lieu de N, et évite
    surtout de juger deux repères sur deux instants différents — pendant
    une animation, ça donne des réponses contradictoires.

    UN GABARIT À CANAL ALPHA EST COMPARÉ SUR SA FORME SEULE (06/11/2026),
    comme le jeton d'attaque : `matchTemplate` reçoit le masque, et le
    décor qui remplit les coins de la boîte n'entre plus dans le score.
    Sans ça, un repère découpé sur un fond donné n'est reconnu que sur ce
    fond-là — `player_marker.png` tenait 0.81 sur la capture dont il
    venait et retombait à 0.57 sur les cartes des tentatives suivantes,
    AU BON ENDROIT, sous le seuil. Les gabarits sans alpha — l'immense
    majorité — passent par le chemin d'avant, à l'identique.
    """
    if not os.path.exists(template_path):
        logging.error(f"Template manquant : {template_path}")
        return None, None

    # IMREAD_UNCHANGED d'abord, pour voir s'il y a un alpha ; mais un PNG
    # en niveaux de gris en reviendrait à DEUX dimensions, que
    # `matchTemplate` refuserait contre une capture en couleur. Hors du
    # cas « quatre canaux », on relit donc exactement comme avant.
    brut = cv2.imread(template_path, cv2.IMREAD_UNCHANGED)
    mask = None
    if brut is not None and brut.ndim == 3 and brut.shape[2] == 4:
        template = brut[:, :, :3]
        alpha = brut[:, :, 3]
        # UN MASQUE TOUT BLANC NE CACHE RIEN, ET IL COÛTE CHER.
        # Sur les 20 gabarits d'`assets/` qui portent un alpha, SEIZE
        # l'ont uniformément à 255 : le masque ne change alors rien au
        # résultat — CLAUDE.md l'avait mesuré dès le 06/11 (« écart
        # ≤ 0.00021 sur 52 captures ») et c'est reproductible (204
        # comparaisons, écart maximal 0,000209).
        #
        # CE QUI N'AVAIT PAS ÉTÉ MESURÉ, C'EST LE PRIX. `TM_CCOEFF_NORMED`
        # masqué n'a pas le chemin accéléré d'OpenCV : meilleur de 5 sur
        # une capture 1920×1080, `first_champion` 0,386 s contre 0,082 s
        # (×4,7), `monthly_challenge` 2,042 s contre 0,445 s (×4,6),
        # `quit_button` 1,495 s contre 0,240 s (×6,2). Et `where_are_we`
        # compare DIX gabarits quand aucun ne passe le seuil — c'est
        # exactement le « 9 à 11 s quand une recherche échoue » du relevé
        # de temps du 08/11, où CLAUDE.md note que « tout le gras est
        # dans les échecs ».
        #
        # Les quatre gabarits qui cachent VRAIMENT quelque chose —
        # `attack_token` (qui ne passe pas par ici), `continue_button`,
        # `final_boss`, `player_marker` — gardent leur masque : le test
        # porte sur l'alpha, pas sur un nom de fichier.
        mask = None if alpha.min() == 255 else cv2.merge([alpha] * 3)
    else:
        template = cv2.imread(template_path)

    if template is None:
        logging.error(f"Impossible de charger le template : {template_path}")
        return None, None

    screen_bgr = _capture_screen_bgr() if screen is None else screen

    echelles = ECHELLES_PAR_GABARIT.get(template_path)
    if echelles:
        return _best_match_multi_echelle(screen_bgr, template, mask, echelles)
    return _match(screen_bgr, template, mask)


def _match(screen_bgr, template, mask):
    """Un seul `matchTemplate` : (score, centre). Le cœur de `best_match`."""
    if mask is None:
        result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    else:
        result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED,
                                   mask=mask)
        # Masquée, la corrélation normalisée divise par l'écart-type SOUS
        # LE MASQUE : il est nul sur un aplat (un ciel uni, une barre
        # noire) et OpenCV y rend NaN ou l'infini. Les laisser passer
        # ferait gagner n'importe quelle zone unie.
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    h, w = template.shape[:2]
    return float(max_val), (max_loc[0] + w // 2, max_loc[1] + h // 2)


def _a_l_echelle(template, mask, facteur):
    """Le gabarit et son masque redimensionnés. Le masque au PLUS PROCHE :
    l'interpoler en ferait des bords à demi transparents, c'est-à-dire du
    décor repris à moitié dans le score."""
    if abs(facteur - 1.0) < 1e-9:
        return template, mask
    interp = cv2.INTER_AREA if facteur < 1.0 else cv2.INTER_LINEAR
    petit = cv2.resize(template, None, fx=facteur, fy=facteur, interpolation=interp)
    if mask is None:
        return petit, None
    return petit, cv2.resize(mask, None, fx=facteur, fy=facteur,
                             interpolation=cv2.INTER_NEAREST)


# Le balayage des échelles se fait en DEMI-RÉSOLUTION, et seule l'échelle
# gagnante est rejouée en pleine résolution. Un `matchTemplate` masqué de
# 160×110 sur 1920×1080 coûte ~0,5 s : six d'affilée feraient 3 s à chaque
# lecture d'écran, pour un repère qui n'est même pas toujours demandé. En
# demi-résolution il coûte ~5 fois moins, et il désigne la même échelle —
# c'est le score FINAL, lui, qu'on veut exact. CE QUE ÇA COÛTE, mesuré :
# 0,66 s quand il n'y a pas de boss à l'écran (le balayage seul), 1,12 s
# quand il y en a un (balayage + confirmation), contre 0,09 s pour
# l'ancien gabarit de 99×30 sans masque. C'est le prix d'un repère qui
# répond dans ses trois états ; il se paie une fois par lecture d'écran,
# là où un geste en prend déjà une à deux.
DEMI_RESOLUTION = 0.5

# ET ON NE PAIE PAS LA CONFIRMATION POUR RIEN. En demi-résolution, mesuré
# sur les captures de référence : 0.80 à 0.90 là où le médaillon est, 0.41
# à 0.52 là où il n'y en a pas. Sous ce plancher, l'écran n'est pas une
# carte d'aventure et la pleine résolution ne ferait que le redire plus
# lentement — on rend alors le score du BALAYAGE, qui est un refus, pas
# une mesure fine.
PLANCHER_CONFIRMATION = 0.60


def _best_match_multi_echelle(screen_bgr, template, mask, echelles):
    """
    Le meilleur score d'un gabarit sur plusieurs échelles.

    POURQUOI SEULEMENT POUR CERTAINS GABARITS : la carte d'aventure ne se
    contente pas de se recentrer après un voyage, elle zoome — mesuré 8 %
    le 06/11/2026 sur le nœud du boss. Un bouton de panneau, lui, est
    toujours à la même taille : lui faire payer le balayage serait du
    temps perdu pour rien (et `player_marker` l'a vérifié, meilleure
    échelle 1.00 sur 453 captures).
    """
    facteur_ecran = DEMI_RESOLUTION
    demi = cv2.resize(screen_bgr, None, fx=facteur_ecran, fy=facteur_ecran,
                      interpolation=cv2.INTER_AREA)
    gagnante, meilleur, point = echelles[0], None, None
    for facteur in echelles:
        petit, petit_masque = _a_l_echelle(template, mask,
                                           facteur * facteur_ecran)
        if petit.shape[0] < 2 or petit.shape[1] < 2:
            continue
        if petit.shape[0] > demi.shape[0] or petit.shape[1] > demi.shape[1]:
            continue
        score, centre = _match(demi, petit, petit_masque)
        if meilleur is None or score > meilleur:
            meilleur, gagnante, point = score, facteur, centre

    if meilleur is None:
        return 0.0, None
    if meilleur < PLANCHER_CONFIRMATION:
        return meilleur, (int(point[0] / facteur_ecran),
                          int(point[1] / facteur_ecran))

    grand, grand_masque = _a_l_echelle(template, mask, gagnante)
    if grand.shape[0] > screen_bgr.shape[0] or grand.shape[1] > screen_bgr.shape[1]:
        return meilleur, (int(point[0] / facteur_ecran),
                          int(point[1] / facteur_ecran))
    score, centre = _match(screen_bgr, grand, grand_masque)
    logging.debug("Gabarit multi-échelle : %.2f à l'échelle %.2f en %s",
                  score, gagnante, centre)
    return score, centre


def find_template_on_screen(template_path, threshold=MATCH_THRESHOLD):
    """
    Recherche un template et retourne son centre (x, y), ou None.
    """
    score, center = best_match(template_path)
    if score is None or score < threshold:
        return None
    return center


def find_all_matches_on_screen(template_path, threshold=MATCH_THRESHOLD, min_distance=None):
    """
    Comme find_template_on_screen, mais retourne TOUTES les occurrences du
    template au-dessus du seuil, triées du HAUT vers le BAS de l'écran.

    Sert aux listes où le même repère visuel se répète (ex: plusieurs
    entrées de défis dans la liste des défis actifs, toutes dessinées avec
    la même icône) : contrairement à un bouton unique, il faut ici
    distinguer les occurrences ET savoir laquelle est la première de la
    liste.

    cv2.matchTemplate donne un score élevé sur toute une zone autour d'une
    correspondance, pas un point isolé : min_distance (par défaut, une
    fraction de la taille du template) évite de compter plusieurs fois le
    même pic comme des entrées différentes.
    """
    if not os.path.exists(template_path):
        logging.error(f"Template manquant : {template_path}")
        return []

    template = cv2.imread(template_path)
    if template is None:
        logging.error(f"Impossible de charger le template : {template_path}")
        return []

    h, w = template.shape[:2]
    if min_distance is None:
        min_distance = min(h, w) * 0.6

    screen_bgr = _capture_screen_bgr()
    result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)

    ys, xs = np.where(result >= threshold)
    scored = sorted(
        ((result[y, x], x, y) for y, x in zip(ys, xs)),
        key=lambda item: item[0],
        reverse=True,
    )

    kept = []
    for _score, x, y in scored:
        center = (x + w // 2, y + h // 2)
        if all(math.hypot(center[0] - kx, center[1] - ky) >= min_distance for kx, ky in kept):
            kept.append(center)

    kept.sort(key=lambda c: c[1])  # haut vers le bas de l'écran
    return kept


# ============================================================
# NŒUDS D'UNE CARTE : TOUS LES CANDIDATS, PUIS LE PLUS PROCHE DEVANT NOUS
# ============================================================

# Deux pics plus proches que ça (en pixels) sont LE MÊME NŒUD vu par deux
# templates différents : un nœud fait ~100 px de diamètre, et les rubans
# de `assets/nodes/` tombent sur son arc à 2-3 px près l'un de l'autre.
NODE_MERGE_DISTANCE = 60


def _peaks(result, w, h, threshold, min_distance):
    """Les pics d'une carte de scores au-dessus du seuil : [(score, (x, y))]."""
    ys, xs = np.where(result >= threshold)
    scored = sorted(
        ((float(result[y, x]), x, y) for y, x in zip(ys, xs)),
        key=lambda item: item[0],
        reverse=True,
    )
    kept = []
    for score, x, y in scored:
        center = (int(x + w // 2), int(y + h // 2))
        if all(math.hypot(center[0] - kx, center[1] - ky) >= min_distance
               for _s, (kx, ky) in kept):
            kept.append((score, center))
    return kept


def find_nodes_in_folder(folder_path, screen=None, threshold=MATCH_THRESHOLD,
                         merge_distance=NODE_MERGE_DISTANCE):
    """
    TOUS les nœuds que les templates d'un dossier reconnaissent sur UNE
    capture, triés du PLUS À GAUCHE au plus à droite :
    [(score, (x, y), nom_du_template), ...].

    POURQUOI TOUS, ET POURQUOI À GAUCHE. Les rubans de `assets/nodes/`
    reconnaissent l'anneau d'un nœud, pas son accessibilité : mesuré le
    02/09/2026 sur une capture d'Ewan, les trois templates rendaient
    0.77-0.93 sur les trois nœuds non visités de l'écran, dont un BLOQUÉ
    (« Quelque chose vous bloque la route… »). Prendre « le premier fichier
    qui franchit le seuil, puis sa meilleure position » revenait à laisser
    l'ordre alphabétique choisir le nœud — et il choisissait le bloqué
    (0.93, anneau vert contre anneau vert).

    Or la carte avance de GAUCHE À DROITE : les nœuds déjà visités, à
    gauche, ne ressemblent plus aux templates (0.64-0.71, sous le seuil), et
    les nœuds bloqués sont toujours EN AVAL, donc à droite des atteignables.
    Le tri gauche → droite donne un ordre lisible au journal ; le CHOIX,
    lui, revient à `pick_next_node`, qui tient compte d'où nous sommes.

    Chaque template est mesuré sur la MÊME image (cf. read_arrival : ne
    jamais juger deux repères sur deux instants), et les pics de plusieurs
    templates qui tombent sur le même nœud sont fusionnés, en gardant le
    meilleur score et le nom du template qui l'a donné.

    Un dossier introuvable, vide, ou dont aucune image ne se charge rend
    une liste vide — comme un écran sans nœud.
    """
    if not os.path.isdir(folder_path):
        logging.error(f"Dossier introuvable : {folder_path}")
        return []

    valid_ext = (".png", ".jpg", ".jpeg")
    fichiers = sorted(f for f in os.listdir(folder_path) if f.lower().endswith(valid_ext))
    if not fichiers:
        logging.warning(f"Aucune image trouvée dans le dossier : {folder_path}")
        return []

    screen_bgr = _capture_screen_bgr() if screen is None else screen

    candidats = []  # (score, (x, y), nom)
    for nom in fichiers:
        template = cv2.imread(os.path.join(folder_path, nom))
        if template is None:
            logging.error(f"Impossible de charger le template : {nom}")
            continue
        h, w = template.shape[:2]
        result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
        for score, center in _peaks(result, w, h, threshold, merge_distance):
            candidats.append((score, center, nom))

    # Fusion inter-templates : le meilleur pic d'un nœud absorbe les autres.
    candidats.sort(key=lambda c: c[0], reverse=True)
    noeuds = []
    for score, center, nom in candidats:
        if all(math.hypot(center[0] - kx, center[1] - ky) >= merge_distance
               for _s, (kx, ky), _n in noeuds):
            noeuds.append((score, center, nom))

    noeuds.sort(key=lambda c: c[1][0])  # de gauche à droite
    return noeuds


# Un candidat doit être AU MOINS aussi loin à droite de notre marqueur pour
# compter comme « la suite du chemin ». Ça écarte le nœud de la MÊME
# COLONNE qu'on n'a pas pris : après le nœud du haut, celui du bas est
# toujours non visité, ressemble toujours aux templates, mais n'est plus
# relié à nous. Un nœud fait ~100 px de large ; deux nœuds d'une même
# colonne sont à 2-3 px l'un de l'autre en x.
NODE_FORWARD_MARGIN = 40


# Un nœud cliqué sans que « Voyage » n'apparaisse est écarté au tour
# suivant : tout candidat à moins de cette distance de lui est le même nœud.
NODE_EXCLUDE_DISTANCE = 60


def pick_next_node(noeuds, position, margin=NODE_FORWARD_MARGIN, exclude=()):
    """
    Parmi des candidats `[(score, (x, y), nom)]`, le nœud à rejoindre
    depuis `position` (notre marqueur), ou None s'il n'y en a pas.

    LA CARTE AVANCE VERS LA DROITE : on ne garde que les candidats
    franchement à droite de nous (x > position.x + margin), et parmi eux LE
    PLUS PROCHE. Les nœuds reliés à nous sont ceux de la colonne suivante ;
    un nœud bloqué est plus loin encore ; un nœud de notre colonne qu'on a
    laissé de côté est à notre hauteur en x, donc écarté par la marge.

    `exclude` : des points déjà cliqués en vain (pas de « Voyage ») — le
    nœud DÉJÀ VISITÉ derrière nous, typiquement, quand il ressemble encore
    aux templates (05/09/2026 : « Foyer — Confrontation terminée » cliqué
    trois fois). Ils ne sont plus candidats.

    Sans position (marqueur non trouvé), on retombe sur le plus à gauche —
    l'appelant fait mieux (le centre de l'écran, cf. navigate.locate_node),
    mais mieux vaut un choix journalisé qu'un arrêt.
    """
    noeuds = [n for n in noeuds
              if not any(math.hypot(n[1][0] - ex, n[1][1] - ey) < NODE_EXCLUDE_DISTANCE
                         for ex, ey in exclude)]
    if not noeuds:
        return None
    if position is None:
        return noeuds[0]
    px, py = position
    devant = [n for n in noeuds if n[1][0] > px + margin]
    if not devant:
        return None
    return min(devant, key=lambda n: math.hypot(n[1][0] - px, n[1][1] - py))
