"""
Tests de monitor_web.py — ce que la page doit garantir, c'est de ne pas
MENTIR au lecteur.

    python test_monitor_web.py

Deux mensonges constatés le 04/11/2026, jeu ouvert en plein écran :

  * `/screen.jpg`, légendée « capture de la fenêtre du jeu », servait
    l'éditeur de texte — la capture est celle du BUREAU, pas de la
    fenêtre, et rien ne disait que le jeu était derrière ;
  * « Log du lancement en cours » coiffait un fichier vieux de deux mois,
    si bien qu'on commentait un combat terminé depuis longtemps comme
    s'il se jouait.

Hors ligne : ni souris, ni jeu, ni OCR, ni win32gui.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

import monitor_web

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ============================================================
# RECOUVREMENT : QUELLE PART DU JEU EST MASQUÉE
# ============================================================

CIBLE = (0, 0, 100, 100)     # 10 000 px²


def test_recouvrement():
    print("\n-- recouvrement de la fenêtre du jeu --")
    part = monitor_web.recouvrement

    check("rien au-dessus ne masque rien", part(CIBLE, []) == 0.0)
    check("une fenêtre à côté ne masque rien",
          part(CIBLE, [(200, 0, 300, 100)]) == 0.0)
    check("une fenêtre qui touche le bord ne masque rien",
          part(CIBLE, [(100, 0, 200, 100)]) == 0.0)
    check("un plein écran par-dessus masque tout",
          part(CIBLE, [(-10, -10, 110, 110)]) == 1.0)
    check("une moitié masquée vaut 0,5",
          abs(part(CIBLE, [(0, 0, 50, 100)]) - 0.5) < 1e-9)
    check("deux fenêtres s'additionnent",
          abs(part(CIBLE, [(0, 0, 30, 100), (70, 0, 100, 100)]) - 0.6) < 1e-9)

    # Borne supérieure assumée : deux fenêtres superposées comptent deux
    # fois, le résultat reste borné à 1.
    check("le total ne dépasse jamais 1", part(CIBLE, [CIBLE, CIBLE]) == 1.0)
    check("une cible vide ne divise pas par zéro",
          part((0, 0, 0, 0), [(0, 0, 10, 10)]) == 0.0)

    # Une infobulle ou une barre des tâches ne doit pas faire crier au
    # loup : seul un masquage franc remplace la capture.
    bandeau = part(CIBLE, [(0, 0, 100, 10)])
    check("une barre de 10 % reste sous le seuil",
          bandeau < monitor_web.OCCLUSION_SEUIL, bandeau)

    # Le cas réel d'Ewan : deux écrans, le navigateur à GAUCHE (x < 0) et
    # le jeu sur l'écran principal. Le focus est au navigateur et le jeu
    # reste parfaitement visible — d'où la géométrie plutôt que le focus.
    jeu = (0, 0, 1920, 1080)
    second_ecran = (-1928, -8, 8, 1040)
    deborde = part(jeu, [second_ecran])
    check("le navigateur sur l'autre écran ne masque pas le jeu",
          deborde < monitor_web.OCCLUSION_SEUIL, deborde)

    # Mode fenêtré : la cible n'est pas à l'origine.
    fenetre = (500, 300, 1000, 600)
    check("en mode fenêtré, la cible est bien située",
          part(fenetre, [(0, 0, 500, 1080)]) == 0.0)
    check("   et son masquage partiel est mesuré",
          abs(part(fenetre, [(0, 0, 750, 1080)]) - 0.5) < 1e-9)


# ============================================================
# QUELLES FENÊTRES COMPTENT
# ============================================================

WS_EX_LAYERED = 0x00080000


def test_masque_vraiment():
    print("\n-- les overlays ne masquent pas --")
    vrai = monitor_web.masque_vraiment

    check("une fenêtre ordinaire masque", vrai(0))

    # Relevé du 04/11/2026 sur le PC d'Ewan : « Discord Overlay »,
    # LAYERED|TRANSPARENT|TOOLWINDOW, 1920×1080, position 0 de l'ordre
    # d'affichage — au-dessus du jeu EN PERMANENCE. Sans ce filtre la
    # page crierait « jeu masqué » pendant toute la partie.
    overlay = WS_EX_LAYERED | monitor_web.WS_EX_TRANSPARENT | monitor_web.WS_EX_TOOLWINDOW
    check("l'overlay de Discord ne masque pas", not vrai(overlay))
    check("une palette flottante ne masque pas",
          not vrai(monitor_web.WS_EX_TOOLWINDOW))
    check("une fenêtre aux clics traversants ne masque pas",
          not vrai(monitor_web.WS_EX_TRANSPARENT))

    # La fenêtre « Claude » est LAYERED et parfaitement opaque : ce seul
    # style ne doit pas l'excuser.
    check("LAYERED seul masque quand même", vrai(WS_EX_LAYERED))


# ============================================================
# L'ÂGE DU LOG
# ============================================================

def test_duree_humaine():
    print("\n-- l'âge de ce qu'on lit --")
    dire = monitor_web.duree_humaine

    check("secondes", dire(0) == "il y a 0 s" and dire(12.7) == "il y a 12 s", dire(12.7))
    check("juste avant la minute", dire(59.9) == "il y a 59 s", dire(59.9))
    check("minutes", dire(60) == "il y a 1 min" and dire(3599) == "il y a 59 min", dire(3599))
    check("heures", dire(3600) == "il y a 1 h" and dire(86399) == "il y a 23 h", dire(86399))
    check("jours", dire(86400) == "il y a 1 j", dire(86400))

    # Le cas vécu : un log du 06/09 relu le 04/11 sous le titre « en cours ».
    check("le log de deux mois le dit", dire(59 * 86400) == "il y a 59 j", dire(59 * 86400))

    # Horloge qui recule, fichier daté du futur : pas de « il y a -3 s ».
    check("un âge négatif ne remonte pas le temps", dire(-5) == "il y a 0 s", dire(-5))

    check("le seuil de fraîcheur sépare le direct du passé",
          30 < monitor_web.LOG_FRAIS < 59 * 86400, monitor_web.LOG_FRAIS)


# ============================================================
# LA VIGNETTE SERVIE À LA PLACE DE LA CAPTURE
# ============================================================

def test_vignette():
    print("\n-- la vignette --")
    image = monitor_web.vignette(1280, "JEU NON LANCE", "detail")
    check("format 16/9, largeur bornée", image.shape == (540, 960, 3), image.shape)

    petite = monitor_web.vignette(50, "JEU MASQUE", "detail")
    check("une largeur minuscule reste lisible", petite.shape[1] == 480, petite.shape)

    # Le fond est noir, le texte gris : aucun pixel du bureau n'y passe.
    check("aucun pixel du bureau n'y passe", int(image.max()) <= 90, int(image.max()))


# ============================================================
# CE QUI REMPLACE LA CAPTURE, ET CE QUI S'ÉCRIT DESSUS
# ============================================================
#
# Il y avait ici, depuis l'origine, une condition 100 % LITTÉRALE :
#
#     check("les libellés de vignette sont en ASCII",
#           all(t.isascii() for t in ("JEU NON LANCE", "JEU MASQUE", …)))
#
# Elle recopiait les quatre libellés et n'appelait jamais `monitor_web` —
# mesuré le 10/11/2026, elle vaut encore True avec `sys.modules
# ["monitor_web"] = None`, c'est-à-dire le module effacé. Changer un
# libellé dans le moniteur ne pouvait pas la faire rougir.

def _glyphe(caractere: str):
    """Le dessin d'un caractère par `cv2.putText`, en masque booléen."""
    image = np.zeros((44, 80, 3), np.uint8)
    cv2.putText(image, caractere, (4, 32), cv2.FONT_HERSHEY_SIMPLEX,
                0.9, (255, 255, 255), 1, cv2.LINE_AA)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) > 40


def test_les_libelles_de_vignette_se_dessinent():
    print("\n-- les libellés de la vignette se dessinent vraiment --")

    # Le repère, c'est ce que cv2 dessine quand il NE CONNAÎT PAS un
    # caractère. Mesuré le 10/11/2026 (OpenCV 5.0.0) : « 😀 » rend
    # exactement le même masque que « ? », tandis que É, è, œ, «, ≤ et —
    # ont chacun leur glyphe — les OpenCV 4, eux, remplaçaient tout accent
    # par « ? ». `requirements.txt` n'épingle aucune version : on mesure
    # sur l'OpenCV installé, on ne suppose pas.
    interdit = _glyphe("?")
    check("un caractère inconnu se dessine comme « ? »",
          bool((_glyphe("😀") == interdit).all()))
    check("   un caractère connu, non", not bool((_glyphe("E") == interdit).all()))

    libelles = [texte for couple in (monitor_web.VIGNETTE_ABSENT,
                                     monitor_web.VIGNETTE_MASQUE)
                for texte in couple]
    check("le moniteur expose les libellés qu'il dessine",
          len(libelles) == 4 and all(libelles), libelles)

    for texte in libelles:
        # « ? » est écarté du relevé : c'est le dessin de secours, pas un
        # caractère illisible. Aucun libellé n'en porte aujourd'hui.
        illisibles = [c for c in texte if c not in " ?"
                      and (not _glyphe(c).any() or bool((_glyphe(c) == interdit).all()))]
        check(f"« {texte} » se dessine en entier", not illisibles, illisibles)

    # Et ces libellés-là passent bien par `vignette` : l'image servie à la
    # place de la capture porte vraiment de l'encre.
    encre = int((monitor_web.vignette(1280, *monitor_web.VIGNETTE_MASQUE) > 0).sum())
    check("la vignette « jeu masqué » porte du texte", encre > 1000, encre)


def test_ce_qui_remplace_la_capture():
    print("\n-- quand la capture n'est pas publiée --")
    decider = monitor_web.contexte_de_capture

    avertissement, libelles = decider(False, 0.0, "")
    check("jeu visible : la capture est publiée",
          libelles is None and not avertissement, (avertissement, libelles))

    sous_le_seuil = monitor_web.OCCLUSION_SEUIL - 0.01
    avertissement, libelles = decider(False, sous_le_seuil, "Claude")
    check("sous le seuil, on publie quand même",
          libelles is None and not avertissement, (avertissement, libelles))

    avertissement, libelles = decider(False, 0.80, "Visual Studio Code")
    check("masqué : la vignette remplace la capture",
          libelles is monitor_web.VIGNETTE_MASQUE, libelles)
    check("   l'avertissement dit la part masquée et la fenêtre",
          "80" in avertissement and "Visual Studio Code" in avertissement, avertissement)

    avertissement, _ = decider(False, 0.80, "")
    check("   sans nom de fenêtre, pas de guillemets vides",
          "«" not in avertissement, avertissement)

    avertissement, libelles = decider(True, 0.0, "")
    check("jeu non lancé : sa propre vignette",
          libelles is monitor_web.VIGNETTE_ABSENT, libelles)
    check("   et l'avertissement le dit", "lancé" in avertissement, avertissement)

    # Le jeu fermé l'emporte sur le masquage : sans fenêtre, « masqué à
    # 100 % » ne voudrait rien dire — `boucle` ne cherche même pas ce qui
    # est au-dessus dans ce cas-là.
    _, libelles = decider(True, 1.0, "Visual Studio Code")
    check("jeu absent ET masqué : c'est l'absence qu'on annonce",
          libelles is monitor_web.VIGNETTE_ABSENT, libelles)


# ============================================================
# LA DERNIÈRE LIGNE DU JOURNAL
# ============================================================
#
# La page titre cet encart « Dernier combat du journal ». Le 09/11/2026 le
# journal réel finissait par une TENTATIVE (34 lignes sur 145, et 25 des 50
# dernières) : la page affichait « ? tours, ? attaques, ? blocages, 695.5 s »
# — trois champs inconnus, et une durée qui est celle de l'aventure entière,
# pas d'un combat. Une tentative n'a ni tours, ni cartes, ni config.

COMBAT = {
    "id": "combat-1", "horodatage": "2026-11-09 19:40:01",
    "tours": 7, "cartes": 11, "attaques": 3, "blocages": 2, "duree": 214.0,
    "gagne": True, "arret": "", "verdict": "bilan",
    "config": {"restrictions": False, "archetype": "aggro"},
    "ecartees": [{"carte": "Vladimir", "n": 3, "motif": "hors de portée"}],
}

TENTATIVE = {
    "id": "tentative-1", "type": "tentative", "horodatage": "2026-11-09 19:40:28",
    "palier": None, "etoiles": 6, "gagne": True,
    "raison": "aventure terminée — 5 nœud(s), 2 combat(s)",
    "duree": 695.5, "combats": 2,
}


def _ecrire_journal(dossier, entrees, premiere_ligne=None):
    """Un journal fabriqué — le vrai `journal.jsonl` n'est jamais touché."""
    chemin = Path(dossier) / "journal.jsonl"
    lignes = [json.dumps(e, ensure_ascii=False) for e in entrees]
    if premiere_ligne is not None:
        lignes.insert(0, premiere_ligne)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf8")
    return chemin


def test_le_dernier_combat_nest_pas_une_tentative():
    print("\n-- la dernière ligne du journal --")
    with tempfile.TemporaryDirectory(prefix="lor-moniteur-") as dossier:
        chemin = _ecrire_journal(dossier, [COMBAT, TENTATIVE, TENTATIVE])
        lu = monitor_web.dernier_combat(path=chemin)

        check("la ligne retenue est un combat, pas la dernière ligne",
              (lu["brut"] or {}).get("id") == "combat-1", (lu["brut"] or {}).get("id"))
        check("le résumé porte les tours du combat",
              "7 tours" in lu["resume"], lu["resume"])
        check("aucun « ? » là où une tentative n'a rien à dire",
              "?" not in lu["resume"], lu["resume"])
        check("la durée affichée n'est pas celle de l'aventure",
              "695.5" not in lu["resume"], lu["resume"])
        check("les cartes écartées du combat sont là",
              "Vladimir ×3" in lu["resume"], lu["resume"])

        # L'archétype vit dans `config` (journal.CONFIG_FIELDS), jamais à la
        # racine de la ligne : mesuré le 09/11/2026 sur les 111 combats du
        # vrai journal, 0 à la racine, 40 dans `config`. La ligne qui
        # l'affiche était donc morte depuis qu'elle existe.
        check("l'archétype du deck est affiché",
              "archétype=aggro" in lu["resume"], lu["resume"])
        sans_archetype = _ecrire_journal(
            dossier, [{**COMBAT, "config": {"restrictions": False}}])
        check("un combat sans archétype n'en invente pas",
              "archétype" not in monitor_web.dernier_combat(path=sans_archetype)["resume"])

        # Une ligne coupée en deux par la fenêtre de lecture (on ne lit que
        # la fin du fichier) est NORMALE : mesuré le 09/11/2026, la fenêtre
        # de 64 ko du vrai journal contient 85 lignes dont 1 tronquée.
        coupee = _ecrire_journal(dossier, [COMBAT, TENTATIVE],
                                 premiere_ligne='es": [], "duree": 3}')
        lu = monitor_web.dernier_combat(path=coupee)
        check("une ligne tronquée par la fenêtre de lecture est sautée",
              (lu["brut"] or {}).get("id") == "combat-1", lu["resume"])

        # Rien à montrer se DIT. « (journal vide) » serait faux : il est
        # plein, mais de tentatives.
        que_des_tentatives = _ecrire_journal(dossier, [TENTATIVE, TENTATIVE])
        lu = monitor_web.dernier_combat(path=que_des_tentatives)
        check("un journal sans aucun combat le dit",
              lu["brut"] is None and "combat" in lu["resume"] and "vide" not in lu["resume"],
              lu["resume"])

        vide = Path(dossier) / "vide.jsonl"
        vide.write_text("", encoding="utf8")
        check("un journal vide le dit",
              monitor_web.dernier_combat(path=vide)["resume"] == "(journal vide)")
        check("un journal absent le dit",
              monitor_web.dernier_combat(path=Path(dossier) / "pas-la.jsonl")["resume"]
              == "(pas de journal)")


def main() -> int:
    for test in (
        test_recouvrement,
        test_masque_vraiment,
        test_duree_humaine,
        test_vignette,
        test_les_libelles_de_vignette_se_dessinent,
        test_ce_qui_remplace_la_capture,
        test_le_dernier_combat_nest_pas_une_tentative,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} échec(s) : {', '.join(FAILURES)}")
        return 1
    print("Tous les tests du moniteur passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
