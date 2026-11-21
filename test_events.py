#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_events.py

Un nœud d'événement se JOUE : on lit l'offre, on choisit pour le deck, on
ferme — et on sort par la flèche retour si l'écran se fige.

    python test_events.py
"""

from __future__ import annotations

import numpy as np

from test_actions import ALL_CARDS, FakeReader, variant_scene, with_db, EN_MAIN   # noqa: E402 (bouchons)
from test_clock import install_virtual_clock

install_virtual_clock()

import events

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


def offer_scene(codes, ratio=0.55):
    """Des cartes À NOUS alignées au milieu de l'écran : une offre."""
    with_db({**ALL_CARDS, "CHAMP": {**ALL_CARDS["UNIT_A"], "name": "Hecarim", "supertype": "Champion"}})
    return variant_scene([(code, 30 + i, ratio, 600 + 300 * i) for i, code in enumerate(codes)], "nous")


class Screens:
    """Une suite d'écrans factices : chaque geste fait passer au suivant."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def capture(self):
        img = np.full((1080, 1920, 3), 40, np.uint8)
        # Le motif change avec l'écran : deux écrans différents ont deux empreintes.
        img[0:100, 0:100] = (self.index * 37) % 255
        return img

    def visible(self, screen, names, threshold=0.8):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        return {n: p for n, p in frame.get("buttons", {}).items() if n in names}

    def snapshot(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        return frame.get("snapshot") or offer_scene([])

    def advance(self, *_):
        self.index = min(self.index + 1, len(self.frames) - 1)


def run(frames, max_steps=8, panneau=None):
    screens = Screens(frames)
    saved = (events._visible, events.human_click, events.click_button, events.park_mouse, events.human_delay)
    clics, boutons, gardes = [], [], []
    events._visible = screens.visible
    events.human_click = lambda x, y: (clics.append((x, y)), screens.advance())
    events.click_button = lambda name, **k: (boutons.append(name), screens.advance(), True)[2]
    events.park_mouse = lambda: None
    events.human_delay = lambda *a, **k: None
    try:
        bilan = events.resolve_event(screens, screens.capture, lambda img, tag: gardes.append(tag),
                                     log=lambda m: None, max_steps=max_steps,
                                     panneau=panneau if panneau is not None else events.EVENEMENT)
    finally:
        events._visible, events.human_click, events.click_button, events.park_mouse, events.human_delay = saved
    return bilan, clics, boutons, gardes


def test_offer_and_ranking():
    print("\nLire l'offre et choisir pour le deck")
    snap = offer_scene(["UNIT_B", "CHAMP", "UNIT_A"])
    offer = events.offered_cards(snap)
    check("trois cartes alignées : une offre", [c.code for c in offer] == ["UNIT_B", "CHAMP", "UNIT_A"],
          [c.code for c in offer])
    check("le champion est pris", events.choose_deck_card(offer).code == "CHAMP")
    offer = events.offered_cards(offer_scene(["UNIT_B", "UNIT_A"]))
    check("sans champion : la plus grosse unité", events.choose_deck_card(offer).code == "UNIT_A")
    check("une seule carte n'est pas une offre", events.offered_cards(offer_scene(["UNIT_A"])) == [])
    # Notre main en jeu (cartes en bas) n'est pas une offre non plus… sauf
    # qu'alignées elles y ressemblent : c'est la navigation qui n'appelle
    # ceci que sur un panneau ouvert. On vérifie juste l'alignement.
    with_db(ALL_CARDS)
    mixte = variant_scene([("UNIT_A", 1, 0.55, 500), ("UNIT_B", 2, 0.30, 800), ("UNIT_A", 3, 0.56, 1100)], "nous")
    check("seule la rangée alignée compte", [c.card_id for c in events.offered_cards(mixte)] == [1, 3])


def test_pick_a_card_then_select_then_close():
    print("\nLa Grand-place : carte choisie, Sélectionner, Continuer, sortie")
    frames = [
        {"snapshot": offer_scene(["UNIT_B", "CHAMP", "UNIT_A"]), "buttons": {"select_button": (1440, 1000)}},
        {"buttons": {"select_button": (1440, 1000)}},          # après le clic carte : le bouton s'active
        {"buttons": {"continue_button": (1400, 900)}},         # après Sélectionner
        {"buttons": {}},                                        # panneau fermé
    ]
    bilan, clics, boutons, gardes = run(frames)
    champ = next(c for c in frames[0]["snapshot"].cards() if c.code == "CHAMP")
    check("la carte choisie est cliquée (le champion)", clics[:1] == [champ.center], clics)
    # Chemin INCHANGÉ quand l'API lit les cartes : une seule validation.
    # La « validation seule » ne sert qu'au repli, quand on ne lit rien.
    check("puis « Sélectionner »", boutons == ["select_button"], boutons)
    check("puis « Continuer »", (1400, 900) in clics, clics)
    check("bilan : pris Hecarim, fermé, sans fuite",
          bilan["picked"] == ["Hecarim"] and bilan["closed"] and not bilan["escaped"], bilan)
    check("aucun écran gardé : tout s'est lu", gardes == [], gardes)


def test_geometric_fallback_when_api_is_silent():
    print("\nSans lecture API : la carte du milieu, au-dessus du bouton")
    frames = [
        # 1er tour : on VALIDE SEUL (le jeu présélectionne) — aucun clic carte.
        {"buttons": {"select_button": (1440, 1000)}},
        # Le bouton est toujours là : un choix est vraiment attendu.
        {"buttons": {"select_button": (1440, 1000)}},
        {"buttons": {}},
    ]
    bilan, clics, boutons, gardes = run(frames)
    check("on ne touche aux cartes qu'au second tour", len(clics) == 1, clics)
    check("clic à la verticale du bouton, plus haut", clics[0][0] == 1440 and clics[0][1] < 700, clics)
    check("validé une fois seul, une fois après la carte",
          boutons == ["select_button"] * 2, boutons)
    check("l'écran est gardé pour apprendre ce panneau", gardes == ["evenement_choix_sans_api"], gardes)
    check("sortie propre", bilan["closed"] and not bilan["escaped"], bilan)


def test_frozen_screen_escapes_with_the_back_arrow():
    print("\nUn panneau qui ne bouge pas : flèche retour")
    # Sélectionner reste là quoi qu'on fasse et l'écran ne change pas.
    class Frozen(Screens):
        def advance(self, *_):
            pass
        def capture(self):
            return np.full((1080, 1920, 3), 40, np.uint8)
    frames = [{"buttons": {"select_button": (1440, 1000)}}]
    screens = Frozen(frames)
    saved = (events._visible, events.human_click, events.click_button, events.park_mouse, events.human_delay)
    clics, gardes = [], []
    events._visible = screens.visible
    events.human_click = lambda x, y: clics.append((x, y))
    events.click_button = lambda name, **k: True
    events.park_mouse = lambda: None
    events.human_delay = lambda *a, **k: None
    try:
        bilan = events.resolve_event(screens, screens.capture, lambda img, tag: gardes.append(tag),
                                     log=lambda m: None, max_steps=4)
    finally:
        events._visible, events.human_click, events.click_button, events.park_mouse, events.human_delay = saved
    back = (int(1920 * events.BACK_ARROW_RATIO[0]), int(1080 * events.BACK_ARROW_RATIO[1]))
    check("la flèche retour est cliquée", back in clics, clics)
    check("le repli géométrique n'est tenté qu'une fois", sum(1 for c in clics if c[1] < 700 and c != back) == 1, clics)
    check("bilan : sortie de secours", bilan["escaped"] is True, bilan)
    check("l'écran bloqué est gardé", "evenement_bloque" in gardes, gardes)


def test_nothing_to_do_returns_at_once():
    print("\nRien d'un événement à l'écran : on repart")
    bilan, clics, boutons, gardes = run([{"buttons": {}}])
    check("aucun clic", clics == [] and boutons == [], (clics, boutons))
    check("fermé, un seul geste", bilan["closed"] and bilan["steps"] == 1, bilan)


# ============================================================
# LE COFFRE D'OBJETS (04/11/2026)
# ============================================================

def test_a_treasure_is_taken_not_closed():
    """
    LE BOGUE DU 04/11/2026. Un nœud de coffre affiche « Ouvrir le trésor »
    et « Quitter ». Faute de repère pour le premier, seul `quit_button`
    passait le seuil (0.98) : le bot refermait le coffre et renonçait à un
    objet permanent PLUS une copie de carte dans son deck — à chaque
    coffre, sur toute l'aventure. Il arrivait au boss avec un deck jamais
    amélioré.
    """
    print("\nUn coffre se ramasse")

    # L'API rapporte les trois cartes : on choisit la meilleure, on valide.
    bilan, clics, boutons, _ = run([
        {"snapshot": offer_scene(["UNIT_A", "CHAMP", "UNIT_B"]),
         "buttons": {"take_treasure_button": (1442, 1002)}},
        {"buttons": {}},
    ], panneau=events.COFFRE)
    check("une carte est prise", bilan["picked"] == ["Hecarim"], bilan["picked"])
    check("validé par « Prendre le trésor »",
          boutons == ["take_treasure_button"], boutons)
    check("   et jamais par « Sélectionner »", "select_button" not in boutons, boutons)
    check("on sort du panneau", bilan["closed"] is True, bilan)


def test_a_treasure_is_never_closed_before_the_pick():
    """
    « Quitter » reste lisible pendant que le panneau se dessine. Le
    cliquer à ce moment-là JETTE le trésor — c'est exactement l'ancien
    comportement. Il n'est donc cliqué qu'une fois le choix fait.
    """
    print("\nOn ne referme pas un coffre les mains vides")

    # Premier écran : seul « Quitter » est lisible, rien n'a été pris.
    bilan, clics, boutons, gardes = run([
        {"buttons": {"quit_button": (755, 953)}},
        {"buttons": {"quit_button": (755, 953)}},
        {"buttons": {}},
    ], max_steps=3, panneau=events.COFFRE)
    check("« Quitter » n'est PAS cliqué", (755, 953) not in clics, clics)
    check("rien n'a été pris", bilan["picked"] == [], bilan["picked"])
    # L'écran ne bouge pas : on sort par la flèche retour plutôt que de
    # renoncer au trésor d'un clic.
    check("sortie par la flèche retour", bilan["escaped"] is True, bilan)
    check("l'écran est gardé sous l'étiquette du coffre",
          "coffre_bloque" in gardes, gardes)

    # Mais une fois le trésor pris, « Quitter » redevient la sortie.
    # (Le clic sur la carte PUIS la validation font avancer de deux
    # écrans : d'où la frame intercalaire.)
    bilan, clics, boutons, _ = run([
        {"snapshot": offer_scene(["UNIT_A", "UNIT_B"]),
         "buttons": {"take_treasure_button": (1442, 1002)}},
        {"buttons": {}},
        {"buttons": {"quit_button": (755, 953)}},
        {"buttons": {}},
    ], panneau=events.COFFRE)
    check("après la prise, « Quitter » ferme bien",
          (755, 953) in clics and bilan["picked"], (clics, bilan["picked"]))


def test_a_treasure_without_api_clicks_the_middle_card():
    """
    Hors partie, l'API ne rapporte pas les cartes du panneau : repli
    géométrique, comme pour un événement, mais avec la hauteur du coffre.
    """
    print("\nCoffre sans lecture d'API : la carte du milieu")

    bilan, clics, boutons, gardes = run([
        # Premier tour : « Prendre le trésor » cliqué SEUL.
        {"snapshot": offer_scene([]),
         "buttons": {"take_treasure_button": (1442, 1002)}},
        # Toujours là : il faut désigner une carte.
        {"buttons": {"take_treasure_button": (1442, 1002)}},
        {"buttons": {}},
    ], panneau=events.COFFRE)
    attendu = (1442, int(1002 - events.CARD_ABOVE_TAKE * 1080))
    check("clic à la verticale du bouton", clics == [attendu], (clics, attendu))
    check("   et ça tombe sur la carte, pas sur l'objet en dessous",
          225 < attendu[1] < 555, attendu)
    check("pris seul d'abord, puis après la carte",
          boutons == ["take_treasure_button"] * 2, boutons)
    check("l'écran est gardé sous l'étiquette du coffre",
          gardes == ["coffre_choix_sans_api"], gardes)


def test_le_coffre_de_champion_demande_deux_clics():
    print(chr(10) + "Coffre d'objets de champion : un champion ET un buff")
    import cv2
    from pathlib import Path

    capture = Path(__file__).resolve().parent / "captures_reference" / "coffre_choix_20261105.png"
    image = cv2.imread(str(capture))
    if image is None:
        print(f"  (ignore : {capture.name} absent)")
        return

    mise_en_page, gestes = events.gestes_du_repli(events.COFFRE, image)
    check("le titre du coffre est reconnu", mise_en_page == "coffre_objets_champion", mise_en_page)
    check("deux clics, pas un", len(gestes) == 2, gestes)

    bx, by = 1442, 1002                      # « Prendre le trésor », mesuré ici
    h, w = image.shape[:2]
    points = [(int(bx + dx * w), int(by + dy * h)) for dx, dy in gestes]
    champion, objet = points

    # LE BUG DU 05/11 : le clic unique tombait en (1442, 389), dans le VIDE
    # entre les deux cartes de champion (gauche jusqu'à x≈1426, droite à
    # partir de ≈1466). Sept clics sans effet, aventure perdue.
    ancien = (bx, int(by - events.CARD_ABOVE_TAKE * h))
    check("l'ancien clic unique tombait entre les deux cartes",
          1426 <= ancien[0] <= 1466, ancien)
    check("le 1er clic tombe DANS la carte de champion de gauche",
          1128 < champion[0] < 1426 and 156 < champion[1] < 566, champion)
    check("le 2e clic tombe DANS le cadre d'objet de gauche",
          996 < objet[0] < 1256 and 660 < objet[1] < 810, objet)

    autre = cv2.imread(str(capture.parent / "champions_haut_20261105.png"))
    if autre is not None:
        nom, gestes2 = events.gestes_du_repli(events.COFFRE, autre)
        check("titre inconnu : on retombe sur le clic unique",
              nom == "carte du milieu" and len(gestes2) == 1, (nom, gestes2))


def test_la_recompense_du_boss_demande_deux_clics():
    print(chr(10) + "Récompense du boss intermédiaire : un champion ET un objet")
    import cv2
    from pathlib import Path
    import adventure_navigation as an

    capture = (Path(__file__).resolve().parent / "captures_reference"
               / "recompense_boss_20261105.png")
    image = cv2.imread(str(capture))
    if image is None:
        print(f"  (ignore : {capture.name} absent)")
        return

    # Le bouton de CE panneau n'est pas reconnu par select_button.png
    # (0.52, sous le seuil) : le bot ne voyait pas même le bouton, donc
    # ne pouvait rien tenter. D'où un repère propre.
    score, centre = an.best_match(an.TEMPLATES["recompense_select"], screen=image)
    check("le bouton de récompense est reconnu", score is not None and score >= 0.80,
          f"score={score}")
    check("   là où il a été mesuré, en (961, 1002)",
          centre is not None and abs(centre[0] - 961) <= 6 and abs(centre[1] - 1002) <= 6,
          centre)
    vieux, _ = an.best_match(an.TEMPLATES["select_button"], screen=image)
    check("   et select_button.png, lui, ne le voit pas",
          vieux is not None and vieux < 0.80, f"score={vieux}")

    mise_en_page, gestes = events.gestes_du_repli(events.RECOMPENSE, image)
    check("deux clics, pas un", len(gestes) == 2, gestes)

    # LE BOUTON A DEUX ÉTATS, et c'est le GRISÉ qu'on rencontre en
    # arrivant (rien n'est encore choisi). Le gabarit doré n'y note que
    # 0.42 : le 06/11/2026 le bot ne voyait pas le bouton et restait
    # planté sur « RÉCOMPENSES DE COMBAT ». Un repère par état.
    grise = cv2.imread(str(capture.parent / "recompense_grisee_20261106.png"))
    if grise is not None:
        dore, _ = an.best_match(an.TEMPLATES["recompense_select"], screen=grise)
        check("   le gabarit doré ne voit PAS le bouton grisé",
              dore is not None and dore < 0.80, f"score={dore}")
        gris, centre_g = an.best_match(an.TEMPLATES["recompense_select_grise"], screen=grise)
        check("   mais le gabarit grisé, oui", gris is not None and gris >= 0.80,
              f"score={gris}")
        check("   au même endroit, (961, 1002)",
              centre_g is not None and abs(centre_g[0] - 961) <= 6
              and abs(centre_g[1] - 1002) <= 6, centre_g)
        mp2, g2 = events.gestes_du_repli(events.RECOMPENSE, grise)
        check("   et l'écran grisé donne aussi deux clics", len(g2) == 2, g2)

    h, w = image.shape[:2]
    bx, by = 961, 1002
    champion, objet = [(int(bx + dx * w), int(by + dy * h)) for dx, dy in gestes]
    # Boîtes mesurées sur cette capture : carte de Heimerdinger et cadre
    # de « Dent de Dragon ».
    check("le 1er clic tombe sur une carte de champion",
          645 < champion[0] < 935 and 280 < champion[1] < 640, champion)
    check("le 2e clic tombe sur un cadre d'objet",
          470 < objet[0] < 760 and 705 < objet[1] < 830, objet)


def test_le_noeud_a_options_sancre_sur_son_invite():
    print(chr(10) + "Nœud à options : le bouton porte le nom de l'option choisie")
    import cv2
    from pathlib import Path
    import adventure_navigation as an

    capture = (Path(__file__).resolve().parent / "captures_reference"
               / "soigneur_20261106.png")
    image = cv2.imread(str(capture))
    if image is None:
        print(f"  (ignore : {capture.name} absent)")
        return

    # LE BUG DU 06/11/2026 : le bouton de ce panneau s'appelle « Soins »,
    # pas « Sélectionner ». Trois gabarits de libellé convergeaient sur
    # (1441, 1002) à ~0.75 — tous sous le seuil — donc le bot ne voyait
    # aucun bouton, restait sur le nœud et abandonnait l'aventure.
    for nom in ("select_button", "take_treasure_button", "recompense_select_grise"):
        score, _ = an.best_match(an.TEMPLATES[nom], screen=image)
        check(f"   « {nom} » ne reconnaît pas ce bouton",
              score is not None and score < 0.80, f"score={score}")

    # L'INVITE, elle, est générique — et c'est pour ça qu'on s'ancre
    # dessus plutôt que sur le titre « Soigneur », qui change de nœud en
    # nœud.
    score, invite = an.best_match(an.TEMPLATES["choisissez_en_un"], screen=image)
    check("l'invite « Choisissez-en 1. » est reconnue", score is not None and score >= 0.80,
          f"score={score}")
    check("   en (716, 721)", invite is not None and abs(invite[0] - 716) <= 6
          and abs(invite[1] - 721) <= 6, invite)

    # VALIDER, C'EST CLIQUER AILLEURS QUE SUR LE REPÈRE : l'invite est du
    # texte, le bouton est plus bas à droite.
    h, w = image.shape[:2]
    dx, dy = events.NOEUD_OPTIONS.valider_decalage
    point = (int(invite[0] + dx * w), int(invite[1] + dy * h))
    check("le clic de validation tombe sur le bouton (1441, 1002)",
          abs(point[0] - 1441) <= 12 and abs(point[1] - 1002) <= 12, point)
    check("   et pas sur l'invite elle-même", point != invite, point)


def test_un_noeud_a_options_peut_ouvrir_un_choix_de_cartes():
    """
    LE MÉDECIN SINISTRE (06/11/2026, vu en jeu) : un nœud à options dont
    l'option ouvre un CHOIX DE CARTES.

    « Choisissez-en 1. » — Recruter une abomination / Suivre ses
    enseignements / Quitter — mais choisir la première fait apparaître un
    panneau de TROIS CARTES à droite, avec un « Sélectionner » GRISÉ tant
    qu'aucune n'est cliquée. Le soigneur, lui, se contentait de valider.

    Le piège : L'INVITE RESTE AFFICHÉE À GAUCHE. `choisissez_en_un` note
    toujours 1.00, donc le bot rejouait indéfiniment le geste des
    options — huit tours, panneau laissé ouvert, puis « nœud 2
    introuvable » parce qu'il cherchait derrière le panneau. Exactement
    la perte du 05/11 sur les renforts.

    Mesuré sur `captures_reference/medecin_sinistre_20261106.png` : les
    DEUX repères sont là, `choisissez_en_un` 1.00 ET `select_button`
    0.94. Le second dit que ce n'est plus la colonne de gauche qui
    attend : on bascule alors sur le panneau d'ÉVÉNEMENT, qui sait
    cliquer la carte au-dessus du bouton puis le bouton.
    """
    print(chr(10) + "Un nœud à options peut ouvrir un choix de cartes")

    import cv2
    from pathlib import Path
    import adventure_navigation as an

    capture = (Path(__file__).resolve().parent / "captures_reference"
               / "medecin_sinistre_20261106.png")
    image = cv2.imread(str(capture))
    if image is None:
        print("  (ignore : medecin_sinistre_20261106.png absent)")
    else:
        invite, _ = an.best_match(an.TEMPLATES["choisissez_en_un"], screen=image)
        select, point = an.best_match(an.TEMPLATES["select_button"], screen=image)
        check("l'invite du nœud à options est là", invite >= 0.80, invite)
        check("ET « Sélectionner » aussi — c'est ça qui distingue ce nœud",
              select >= 0.80, select)
        check("   le bouton est en bas à droite (1439, 999)",
              abs(point[0] - 1439) <= 8 and abs(point[1] - 999) <= 8, point)
        # Le repli géométrique de l'événement doit tomber SUR une carte :
        # bouton à y=999, cartes entre y=175 et y=710.
        y_carte = point[1] - events.CARD_ABOVE_SELECT * image.shape[0]
        check("   et la carte visée tombe bien dans la rangée (175-710)",
              175 < y_carte < 710, y_carte)
        check("« Sélectionner » fait partie des repères du nœud à options",
              "select_button" in events.NOEUD_OPTIONS.boutons,
              events.NOEUD_OPTIONS.boutons)

    # ET LE DÉROULÉ : invite + Sélectionner ensemble -> on joue le choix
    # de cartes, pas le geste des options.
    frames = [
        {"buttons": {"choisissez_en_un": (716, 721), "select_button": (1440, 999)}},
        {"buttons": {"choisissez_en_un": (716, 721), "select_button": (1440, 999)}},
        {"buttons": {}},
    ]
    bilan, clics, boutons, _gardes = run(frames, panneau=events.NOEUD_OPTIONS)
    check("« Sélectionner » est le bouton qu'on valide", boutons and
          set(boutons) == {"select_button"}, boutons)
    check("et on a cliqué une CARTE, en haut de l'écran",
          any(y < 700 for _x, y in clics), clics)
    check("jamais la rangée des options (y ~ 787)",
          not any(760 < y < 820 for _x, y in clics), clics)
    check("sortie propre", bilan["closed"] and not bilan["escaped"], bilan)


def test_la_recompense_peut_avoir_trois_champions():
    """
    06/11/2026, 20:19 — LE BOT A CLIQUÉ DANS LE VIDE, en boucle.

    La récompense de combat n'a pas toujours DEUX champions : celle-ci en
    proposait TROIS (Sejuani, Aurelion Sol, Leona). Le geste mesuré le
    05/11 vise (789, 459), qui tombe alors **pile dans la gouttière entre
    le premier et le deuxième**. L'objet, lui, était bien pris — donc
    « Sélectionner » restait grisé, faute de champion, et le panneau ne
    se fermait pas. Exactement le bogue du coffre du 05/11, à un panneau
    près.

    LA RANGÉE EST CENTRÉE, À PAS CONSTANT : mesuré, 790/1127 à deux
    cartes et 617/959/1301 à trois — pas de ~340, centre 960 dans les
    deux cas. Le seul inconnu est le NOMBRE, et le centre le dit :

        capture              x=617   x=790   x=960   x=1127  x=1301
        2 champions (×3)     40-57   91-112  37-50   62-106  44-62
        3 champions           95      44      97      47      61

    Centre sombre → deux cartes ; centre clair → trois. 50 contre 97, la
    marge est large. On ne devine pas le nombre, on le LIT.
    """
    print(chr(10) + "La récompense peut avoir TROIS champions")

    import cv2
    from pathlib import Path
    reference = Path(__file__).resolve().parent / "captures_reference"

    def point_du_champion(nom):
        """Où le repli irait cliquer le champion, en pixels."""
        image = cv2.imread(str(reference / nom))
        if image is None:
            return None, None
        _mise, gestes = events.gestes_du_repli(events.RECOMPENSE, image)
        h, w = image.shape[:2]
        bx, by = 961, 1002          # le bouton, mesuré sur ces captures
        dx, dy = gestes[0]
        return (int(bx + dx * w), int(by + dy * h)), image

    # TROIS CHAMPIONS : il faut viser 617, pas 790 (la gouttière).
    point, image = point_du_champion("recompense_trois_champions_20261106.png")
    if image is None:
        print("  (ignore : recompense_trois_champions_20261106.png absent)")
    else:
        check("trois champions : on vise celui de gauche (617)",
              point is not None and abs(point[0] - 617) <= 25, point)
        check("   et surtout pas la gouttière (789)",
              point is not None and abs(point[0] - 789) > 60, point)
        check("   la hauteur ne change pas (459)",
              point is not None and abs(point[1] - 459) <= 20, point)

    # DEUX CHAMPIONS : rien ne bouge, le geste du 05/11 reste bon.
    for nom in ("recompense_boss_20261105.png", "recompense_combat_20261106.png"):
        point, image = point_du_champion(nom)
        if image is None:
            continue
        check("deux champions : on vise toujours 790 (%s)" % nom[:28],
              point is not None and abs(point[0] - 790) <= 25, point)


def test_un_bouton_dore_dit_que_le_choix_est_fait():
    """
    06/11/2026, 20:26 — LE BOT A DÉFAIT CE QU'IL VENAIT DE FAIRE.

    Une fois la colonne du champion corrigée, les deux clics tombaient
    juste... et le panneau ne se fermait toujours pas. Vérifié à la main
    sur l'écran : un clic sur la carte la SÉLECTIONNE, un second la
    DÉSÉLECTIONNE. Or le repli géométrique rejouait la paire à chaque
    tour, tant que l'écran changeait — et il changeait, puisque les
    clics basculaient la sélection. Le panneau oscillait : champion pris
    / objet rendu, champion rendu / objet pris, huit fois.

    C'est le même piège que le clic à l'aveugle de l'événement, qui
    ANNULE la présélection (05/11) : ici il annule la sienne propre.

    IL FALLAIT UN SIGNAL DE « C'EST PRÊT », et les gabarits ne le
    donnent pas : `recompense_select_grise` matche les DEUX états (1.00
    grisé, 0.94 actif). C'est la COULEUR qui tranche — mesuré sur la
    bande du bouton (961, 1002), 240 x 44 :

        bouton ACTIF  : 67 % de pixels orangés
        bouton GRISÉ  : 0 %, 0 %, 9 % sur trois captures

    Doré = les deux choix sont faits, il ne reste qu'à valider.
    """
    print(chr(10) + "Un bouton doré dit que le choix est déjà fait")

    import cv2
    from pathlib import Path
    reference = Path(__file__).resolve().parent / "captures_reference"

    actif = cv2.imread(str(reference / "recompense_bouton_actif_20261106.png"))
    grise = cv2.imread(str(reference / "recompense_trois_champions_20261106.png"))
    if actif is None or grise is None:
        print("  (ignore : captures du bouton absentes)")
    else:
        check("le bouton doré est reconnu comme prêt",
              events.bouton_est_actif(actif, (961, 1002)), True)
        check("le bouton grisé ne l'est pas",
              not events.bouton_est_actif(grise, (961, 1002)), False)
        # Et le gabarit, lui, ne sait pas les distinguer : c'est bien la
        # couleur qu'il fallait.
        import adventure_navigation as an
        sa, _ = an.best_match(an.TEMPLATES["recompense_select_grise"], screen=actif)
        sg, _ = an.best_match(an.TEMPLATES["recompense_select_grise"], screen=grise)
        check("   le gabarit, lui, matche les deux (%.2f / %.2f)" % (sa, sg),
              sa >= 0.80 and sg >= 0.80, (sa, sg))

    # ET DANS LA BOUCLE : bouton doré -> on valide, on ne reclique PAS
    # les cartes (sinon on les désélectionne).
    frames = [
        {"buttons": {"recompense_select_grise": (961, 1002)}, "dore": True},
        {"buttons": {}},
    ]
    vrai = events.bouton_est_actif
    events.bouton_est_actif = lambda screen, point: True
    try:
        bilan, clics, boutons, _g = run(frames, panneau=events.RECOMPENSE)
    finally:
        events.bouton_est_actif = vrai
    check("bouton doré : on valide", "recompense_select_grise" in boutons, boutons)
    check("   et aucune carte n'est recliquée", clics == [], clics)
    check("   sortie propre", bilan["closed"], bilan)


def test_le_coffre_aussi_peut_avoir_trois_champions():
    """
    06/11/2026, 20:33 — LE MÊME BOGUE, L'AUTRE PANNEAU.

    Une fois la récompense réparée, le coffre d'objets de champion a
    reproduit l'histoire au geste près : trois champions (Leona, Sejuani,
    Aurelion Sol) là où la géométrie du 05/11 en supposait deux, et le
    clic (1277, 361) tombé **dans la gouttière** entre les deux premiers.
    L'objet était pris, pas le champion, « Prendre le trésor » restait
    grisé.

    LES DEUX PANNEAUX SUIVENT LA MÊME LOI, et c'est ce qui permet de ne
    pas dupliquer : la rangée est CENTRÉE SUR LE BOUTON, à pas constant.
        récompense : bouton 961,  pas ~342 -> 790/1127 ou 618/960/1301
        coffre     : bouton 1442, pas ~315 -> 1284/1600 ou 1127/1442/1757
    Et le NOMBRE se lit au centre : sombre à deux cartes, clair à trois.

    Le bouton du coffre s'allume comme celui de la récompense — mesuré
    64,9 % d'orange une fois le champion pris — donc le même garde
    l'empêche de défaire son propre choix.
    """
    print(chr(10) + "Le coffre aussi peut avoir trois champions")

    import cv2
    from pathlib import Path
    reference = Path(__file__).resolve().parent / "captures_reference"

    def point_du_champion(panneau, nom, bouton):
        image = cv2.imread(str(reference / nom))
        if image is None:
            return None
        _mise, gestes = events.gestes_du_repli(panneau, image)
        h, w = image.shape[:2]
        dx, dy = gestes[0]
        return (int(bouton[0] + dx * w), int(bouton[1] + dy * h))

    BOUTON_COFFRE = (1442, 1002)
    point = point_du_champion(events.COFFRE,
                              "coffre_trois_champions_20261106.png", BOUTON_COFFRE)
    if point is None:
        print("  (ignore : coffre_trois_champions_20261106.png absent)")
    else:
        check("trois champions : on vise celui de gauche (1127)",
              abs(point[0] - 1127) <= 28, point)
        check("   et pas la gouttière (1277)", abs(point[0] - 1277) > 60, point)

    point = point_du_champion(events.COFFRE,
                              "coffre_choix_20261105.png", BOUTON_COFFRE)
    if point is not None:
        check("deux champions : la géométrie du 05/11 ne bouge pas (1277)",
              abs(point[0] - 1277) <= 28, point)

    # LE BOUTON DU COFFRE S'ALLUME AUSSI.
    actif = cv2.imread(str(reference / "coffre_bouton_actif_20261106.png"))
    grise = cv2.imread(str(reference / "coffre_trois_champions_20261106.png"))
    if actif is not None and grise is not None:
        check("coffre : bouton doré reconnu",
              events.bouton_est_actif(actif, BOUTON_COFFRE), True)
        check("coffre : bouton grisé non reconnu",
              not events.bouton_est_actif(grise, BOUTON_COFFRE), False)
    check("et le coffre porte bien le garde du bouton doré",
          events.COFFRE.bouton_dore_vaut_pret is True)


def test_une_carte_sombre_ne_fait_pas_disparaitre_un_champion():
    """
    08/11/2026 : le même bogue une TROISIÈME fois, et cette fois c'est le
    SEUIL qui a lâché, pas la géométrie.

    Coffre d'objets de champion, trois cartes — Rek'Sai, Poppy, Aurelion
    Sol. Le nombre de champions se lisait à la luminosité du CENTRE
    contre un seuil absolu de 70 (« entre 50 en gouttière et 97 sur une
    carte »). Poppy a une illustration sombre : le centre a noté **68.8**,
    1.2 sous le seuil. Le bot a conclu « deux cartes », cliqué en
    (1284, 361) PILE DANS LA GOUTTIÈRE, rejoué le couple sept fois, perdu
    le trésor, puis l'aventure — « boss final introuvable », une
    tentative mensuelle brûlée.

    UNE LUMINOSITÉ ABSOLUE DÉPEND DE L'ILLUSTRATION, UN ÉCART NON. Les
    deux dispositions placent exactement une carte là où l'autre place du
    vide, donc on compare les deux colonnes candidates au lieu d'en juger
    une seule. Mesuré sur les neuf captures de référence : séparées
    toutes les neuf, 38 points d'écart dans le pire cas.
    """
    print(chr(10) + "Une carte du milieu sombre ne doit pas effacer un champion")

    import cv2
    from pathlib import Path
    reference = Path(__file__).resolve().parent / "captures_reference"

    cas = [
        # (capture, rangée, abscisse attendue, nombre de champions)
        ("coffre_trois_champions_sombre_20261108.png", events.RANGEE_COFFRE, 1127, 3),
        ("coffre_trois_champions_20261106.png", events.RANGEE_COFFRE, 1127, 3),
        ("coffre_bouton_actif_20261106.png", events.RANGEE_COFFRE, 1127, 3),
        ("coffre_choix_20261105.png", events.RANGEE_COFFRE, 1284, 2),
        ("recompense_trois_champions_20261106.png", events.RANGEE_RECOMPENSE, 618, 3),
        ("recompense_bouton_actif_20261106.png", events.RANGEE_RECOMPENSE, 618, 3),
        ("recompense_boss_20261105.png", events.RANGEE_RECOMPENSE, 789, 2),
        ("recompense_combat_20261106.png", events.RANGEE_RECOMPENSE, 789, 2),
        ("recompense_grisee_20261106.png", events.RANGEE_RECOMPENSE, 789, 2),
    ]
    for nom, rangee, attendu, combien in cas:
        image = cv2.imread(str(reference / nom))
        if image is None:
            print(f"  (ignoré : {nom} absent)")
            continue
        x = events.champion_le_plus_a_gauche(image, rangee)
        check(f"{combien} champions sur {nom[:40]} -> x={attendu}",
              abs(x - attendu) <= 2, x)

    # Et la capture du jour est bien celle qui piégeait le seuil absolu :
    # son centre est SOUS 70, alors qu'il y a trois cartes.
    image = cv2.imread(str(reference / "coffre_trois_champions_sombre_20261108.png"))
    if image is not None:
        c, pas, haut, bas = events.RANGEE_COFFRE
        bande = cv2.cvtColor(image[haut:bas, :, :], cv2.COLOR_BGR2GRAY)
        milieu = float(bande[:, c - 25:c + 25].mean())
        check("le centre de cette capture est sous l'ancien seuil de 70",
              milieu < 70.0, round(milieu, 1))


def test_on_ne_reclique_pas_une_tuile_deja_prise():
    """
    08/11/2026 : le coffre a oscillé ONZE tours, et le garde du bouton
    doré ne pouvait rien y faire.

    Le règle, mesurée en jeu un clic à la fois :
        Rek'Sai seul               -> bouton GRIS
        + clic sur Grande Massue   -> LES DEUX pris, bouton ACTIF
        re-clic sur Rek'Sai        -> la paire est cassée
    Le jeu PRÉSÉLECTIONNE un champion ; le repli à l'aveugle cliquait
    toujours les DEUX tuiles, donc il défaisait la présélection à chaque
    tour. Sur les onze captures d'affilée, l'alternance est parfaite et
    le bouton n'est JAMAIS doré (0 % d'orange sur les onze) : le garde
    `bouton_dore_vaut_pret` arrive trop tard, il faut regarder AVANT de
    cliquer.

    Le liséré d'une tuile prise se lit à la hauteur du clic, sur ses deux
    bords — 255 prise contre 102 libre, sans cas intermédiaire.
    """
    print(chr(10) + "Une tuile déjà prise ne se reclique pas : cela la rendrait")

    import cv2
    from pathlib import Path
    reference = Path(__file__).resolve().parent / "captures_reference"

    CHAMPION, OBJET = (1126, 361), (1126, 735)
    PAS = events.RANGEE_COFFRE[1]

    cas = [("coffre_champion_pris_20261108.png", True, False),
           ("coffre_objet_pris_20261108.png", False, True)]
    for nom, champion_pris, objet_pris in cas:
        image = cv2.imread(str(reference / nom))
        if image is None:
            print(f"  (ignoré : {nom} absent)")
            continue
        check(f"{nom[:40]} : champion pris ? {champion_pris}",
              events.tuile_est_prise(image, CHAMPION, PAS) is champion_pris)
        check(f"{nom[:40]} : objet pris ? {objet_pris}",
              events.tuile_est_prise(image, OBJET, PAS) is objet_pris)
        # ET LE BOUTON RESTE GRIS dans les deux cas : une seule tuile ne
        # suffit pas, c'est bien un choix CROISÉ.
        check("   le bouton reste gris avec une seule tuile",
              not events.bouton_est_actif(image, (1442, 1002)))


def test_the_event_panel_is_unchanged():
    """Le panneau par défaut reste l'événement, aux mêmes repères."""
    print("\nL'événement n'a pas bougé")
    check("bouton de validation", events.EVENEMENT.valider == "select_button")
    check("étiquette des captures", events.EVENEMENT.etiquette == "evenement")
    check("on peut y renoncer sans rien prendre",
          events.EVENEMENT.renoncer_sans_prendre is True)
    check("le coffre, non",
          events.COFFRE.renoncer_sans_prendre is False)
    check("« Quitter » est lu sur un coffre (l'écran n'est pas vide)",
          "quit_button" in events.COFFRE.boutons, events.COFFRE.boutons)


def main():
    for test in (test_offer_and_ranking, test_pick_a_card_then_select_then_close,
                 test_geometric_fallback_when_api_is_silent, test_frozen_screen_escapes_with_the_back_arrow,
                 test_nothing_to_do_returns_at_once,
                 test_a_treasure_is_taken_not_closed,
                 test_a_treasure_is_never_closed_before_the_pick,
                 test_a_treasure_without_api_clicks_the_middle_card,
                 test_le_coffre_de_champion_demande_deux_clics,
                 test_la_recompense_du_boss_demande_deux_clics,
                 test_le_noeud_a_options_sancre_sur_son_invite,
        test_un_noeud_a_options_peut_ouvrir_un_choix_de_cartes,
        test_la_recompense_peut_avoir_trois_champions,
        test_un_bouton_dore_dit_que_le_choix_est_fait,
        test_le_coffre_aussi_peut_avoir_trois_champions,
        test_une_carte_sombre_ne_fait_pas_disparaitre_un_champion,
        test_on_ne_reclique_pas_une_tuile_deja_prise,
                 test_the_event_panel_is_unchanged):
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
