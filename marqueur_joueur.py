#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
marqueur_joueur.py

OÙ NOUS SOMMES SUR LA CARTE D'AVENTURE.

    python marqueur_joueur.py <capture.png> [...]

--------------------------------------------------------------------
LE LOSANGE N'EST PAS NOUS (08/11/2026, fait de jeu confirmé par Ewan)
--------------------------------------------------------------------
`assets/player_marker.png` découpe un LOSANGE DORÉ À INTÉRIEUR SOMBRE.
Le commentaire de `adventure_navigation.TEMPLATES` le décrit comme « le
losange que le jeu dessine sous notre portrait », et c'était faux : ce
losange est un DÉCOR DE TRACÉ, posé sur le chemin entre deux nœuds. Il
n'a rien à voir avec nous, et il y en a un par carte.

Notre position, elle, est marquée par un MÉDAILLON ROND — anneau doré,
anneau sombre, et dedans le PORTRAIT DU CHAMPION JOUÉ, le même dessin
que celui du HUD en bas à gauche. Comparaison faite à l'image :
`screenshots/diag_marqueur_compare.png` (losange | médaillon | HUD).

Ce que ça coûtait : le 08/11 au soir, le losange était reconnu à 0.90 en
(318, 477) pendant que le médaillon était en (960, 451) — 642 px
d'erreur. `pick_next_node` cherche « le nœud le plus proche À DROITE de
notre position » : parti d'un point qui n'était pas nous, il a retenu
(986, 173), « Voyage » n'est jamais apparu, le nœud a été écarté et
l'aventure s'est perdue en « nœud introuvable ». Six tentatives y sont
passées entre 17:32 et 18:14.
Sur les 94 captures de carte du projet où le médaillon est lisible, le
losange ne passait son seuil que 43 fois, et il désignait alors un point
à 219-913 px du médaillon (médiane 445). Les 51 autres fois il ne
passait pas du tout : la position était simplement perdue.

--------------------------------------------------------------------
UN GABARIT FIGÉ NE PEUT PAS MARCHER — D'OÙ LE DÉCOUPAGE À LA VOLÉE
--------------------------------------------------------------------
Le médaillon porte le portrait du champion joué, et le bot joue un
champion différent à chaque tentative : aucun PNG d'`assets/` ne peut le
reconnaître. C'est probablement pour ça que le losange avait été retenu
— lui est stable.

Mais le portrait est AFFICHÉ À L'ÉCRAN, en permanence, dans le HUD en
bas à gauche. On le DÉCOUPE donc sur la capture courante et on le
cherche sur la même capture : le gabarit change de champion en même
temps que le jeu, sans qu'on ait rien à livrer.

GÉOMÉTRIE DU HUD, MESURÉE. L'anneau cyan d'expérience se laisse ajuster
en cercle (moindres carrés sur son masque HSV) : centre (116.5, 972.5)
et rayon 66.7 sur 1920×1080, IDENTIQUES à un demi-pixel près sur toutes
les captures de carte du projet. L'illustration tient à l'intérieur :
rayon 54 la laisse entière sans mordre sur l'anneau sombre.

ON NE GARDE QUE LE DISQUE. La boîte carrée du portrait contient les
anneaux du HUD (doré, cyan) que le médaillon de la carte n'a PAS : un
masque circulaire en `mask=` les retire du calcul, comme le jeton
d'attaque et comme le losange lui-même. Le liseré des deux objets n'est
pas le même ; seule l'illustration l'est.

MULTI-ÉCHELLE, PARCE QUE LA CARTE ZOOME. Le médaillon fait ~0,70 fois
le portrait du HUD, mais pas toujours : mesuré de 0.65 à 0.75 selon la
carte. `ECHELLES` balaie 0.575-0.875 ; la dernière échelle gagnante est
essayée en pleine résolution d'abord, sinon balayage en résolution
réduite puis confirmation — la recette du jeton d'attaque
(`game_state.ATTACK_TOKEN_SCALES`).

ON S'EFFACE SOI-MÊME avant de chercher : sans ça le meilleur pic serait
le portrait du HUD, qui est son propre gabarit à l'échelle 1.

RIEN D'INVENTÉ : sous le seuil, on rend None et l'appelant garde ses
replis (le centre de l'écran, puis le plus proche / le plus à gauche).
"""

from __future__ import annotations

import logging
import sys
from collections import namedtuple

import cv2
import numpy as np


# --------------------------------------------------------------------
# GÉOMÉTRIE DU PORTRAIT DU HUD
# --------------------------------------------------------------------
# En RATIOS de la capture : tout le projet mesure ainsi (cf. events.py).
# Mesure : anneau cyan ajusté en cercle, centre (116.5, 972.5) / rayon
# 66.7 sur 1920×1080 — soit (0.0607, 0.9005) et 0.0618 de la hauteur.
# L'illustration s'arrête avant l'anneau sombre : 54 px, soit 0.0500.
PORTRAIT_CENTRE = (0.0607, 0.9005)
PORTRAIT_RAYON = 0.0500

# La zone à effacer avant de chercher, pour ne pas se trouver soi-même :
# le portrait du HUD et son cartouche de statistiques, en ratios
# (x0, y0, x1, y1). Large à dessein — il n'y a jamais de nœud là.
ZONE_HUD = (0.0, 0.805, 0.167, 1.0)

# Le médaillon fait entre 0.65 et 0.75 fois le portrait du HUD selon le
# zoom de la carte ; on balaie un peu plus large des deux côtés.
ECHELLES = tuple(x / 1000 for x in range(575, 876, 25))

# Résolution du balayage grossier. Un gabarit de 36 px y suffit à
# désigner la bonne échelle ; la confirmation se fait en pleine taille.
RESOLUTION_GROSSIERE = 0.33

# Combien d'échelles du balayage grossier sont confirmées en pleine
# résolution. Deux voisines s'échangent souvent la tête en réduit.
ECHELLES_CONFIRMEES = 3

# Seuil d'acceptation du pic. MESURÉ SUR 285 CAPTURES du projet (toutes
# celles de carte, plus un échantillon de combats, de coffres, de
# récompenses et d'événements) : 128 médaillons retenus, scores 0.775 à
# 0.943, et le meilleur pic d'une capture SANS médaillon mais qui passe
# le garde de contraste reste à 0.656 — la grille des champions, où le
# HUD montre bien un portrait mais où il n'y a pas de carte. Entre les
# deux, 0.70 ; aucun faux positif, et les vrais médaillons qu'on refuse
# (0.51-0.69 : infobulle ouverte, animation en cours) font retomber
# l'appelant sur le centre de l'écran — on abstient, on n'invente pas.
SEUIL = 0.70

# DEUXIÈME GARDE-FOU, INDÉPENDANT DU PREMIER : le contraste du disque
# découpé. Hors de la carte d'aventure il n'y a PAS de portrait en bas à
# gauche, et on découpe alors un bout d'écran quelconque — souvent un
# aplat sombre. Un aplat corrélé à un autre aplat note très haut : sur
# `screenshots/ecran_inconnu_20261105_201234.png` (écran de bilan) le
# pic monte à 0.94, à un endroit qui ne veut rien dire. Le score seul ne
# peut donc pas trancher, et baisser le seuil ne ferait qu'empirer.
# Mesure de l'écart-type des gris sous le masque : 48 à 64 quand le
# portrait est là, 0.9 à 20 quand il n'y est pas. Le seul entre-deux est
# la GRILLE DES CHAMPIONS (40-44), que le score refuse de son côté
# (0.44-0.66). Sur les 285 captures mesurées ce garde écarte 115
# écrans — bilans, écrans de victoire, « reprendre l'aventure »,
# récompenses de combat — où le score SEUL serait monté jusqu'à 0.96 sur
# un point qui ne veut rien dire. Il coûte deux captures de carte
# (contraste 20, portrait en fondu) : on y renonce à une position
# qu'on avait, et le centre de l'écran prend le relais.
CONTRASTE_MIN = 30.0


Medaillon = namedtuple("Medaillon", "score point echelle")


# La dernière échelle qui a gagné : essayée en pleine résolution d'abord
# au coup suivant. La carte ne change pas de zoom entre deux lectures.
_DERNIERE_ECHELLE = None


def _disque(rayon: int) -> np.ndarray:
    """Le masque circulaire du gabarit, en trois canaux."""
    m = np.zeros((2 * rayon, 2 * rayon), np.uint8)
    cv2.circle(m, (rayon, rayon), rayon - 2, 255, -1)
    return cv2.merge([m] * 3)


def portrait_du_hud(ecran):
    """
    Le portrait du champion joué, découpé dans le HUD : (gabarit, masque).

    Rend (None, None) si la capture est absente ou trop petite pour
    contenir le HUD — une absence n'est pas un mauvais score.
    """
    if ecran is None or ecran.ndim != 3:
        return None, None
    h, w = ecran.shape[:2]
    cx = int(round(PORTRAIT_CENTRE[0] * w))
    cy = int(round(PORTRAIT_CENTRE[1] * h))
    r = int(round(PORTRAIT_RAYON * h))
    if r < 8 or cx - r < 0 or cy - r < 0 or cx + r > w or cy + r > h:
        return None, None
    return ecran[cy - r:cy + r, cx - r:cx + r].copy(), _disque(r)


def contraste_du_portrait(gabarit, masque) -> float:
    """L'écart-type des gris sous le masque : y a-t-il un portrait ici ?"""
    if gabarit is None:
        return 0.0
    gris = cv2.cvtColor(gabarit, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(gris[masque[:, :, 0] > 0].std())


def _sans_le_hud(ecran):
    """La capture avec le HUD effacé : on cherche le médaillon, pas nous."""
    h, w = ecran.shape[:2]
    x0, y0, x1, y1 = ZONE_HUD
    sans = ecran.copy()
    cv2.rectangle(sans, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)),
                  (0, 0, 0), -1)
    return sans


def _pic(ecran, gabarit, masque, echelle):
    """Meilleur pic du gabarit redimensionné : (score, centre)."""
    g = cv2.resize(gabarit, None, fx=echelle, fy=echelle,
                   interpolation=cv2.INTER_AREA)
    m = cv2.resize(masque, None, fx=echelle, fy=echelle,
                   interpolation=cv2.INTER_NEAREST)
    if g.shape[0] >= ecran.shape[0] or g.shape[1] >= ecran.shape[1]:
        return 0.0, None
    res = cv2.matchTemplate(ecran, g, cv2.TM_CCOEFF_NORMED, mask=m)
    # Masquée, la corrélation normalisée divise par l'écart-type SOUS LE
    # MASQUE : nul sur un aplat, OpenCV y rend NaN ou l'infini. Même
    # parade que `adventure_navigation.best_match`.
    res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
    _, score, _, loc = cv2.minMaxLoc(res)
    return float(score), (loc[0] + g.shape[1] // 2, loc[1] + g.shape[0] // 2)


def trouver_medaillon(ecran, seuil=SEUIL, memoire=True,
                      portrait=None) -> Medaillon | None:
    """
    Le médaillon du joueur sur cette capture, ou None.

    `ecran` est une image DÉJÀ CAPTURÉE : ce module ne photographie
    jamais rien de lui-même, et reste donc utilisable hors ligne.

    `memoire` : réessayer d'abord la dernière échelle gagnante. Les
    tests la coupent pour que chaque capture soit jugée seule.

    `portrait` : (gabarit, masque) à chercher au lieu de celui du HUD de
    cette capture. Ne sert qu'à éprouver le découpage à la volée — on
    cherche le portrait d'UNE aventure sur la carte d'une AUTRE, et il
    ne doit rien y trouver.
    """
    global _DERNIERE_ECHELLE

    gabarit, masque = portrait if portrait is not None else portrait_du_hud(ecran)
    if gabarit is None:
        return None
    contraste = contraste_du_portrait(gabarit, masque)
    if contraste < CONTRASTE_MIN:
        logging.debug("Pas de portrait dans le HUD (contraste %.1f) : "
                      "on ne cherche pas de médaillon.", contraste)
        return None
    champ = _sans_le_hud(ecran)

    if memoire and _DERNIERE_ECHELLE is not None:
        score, point = _pic(champ, gabarit, masque, _DERNIERE_ECHELLE)
        if score >= seuil:
            return Medaillon(score, point, _DERNIERE_ECHELLE)

    petit = cv2.resize(champ, None, fx=RESOLUTION_GROSSIERE,
                       fy=RESOLUTION_GROSSIERE, interpolation=cv2.INTER_AREA)
    g_petit = cv2.resize(gabarit, None, fx=RESOLUTION_GROSSIERE,
                         fy=RESOLUTION_GROSSIERE, interpolation=cv2.INTER_AREA)
    m_petit = cv2.resize(masque, None, fx=RESOLUTION_GROSSIERE,
                         fy=RESOLUTION_GROSSIERE, interpolation=cv2.INTER_NEAREST)
    grossier = sorted((_pic(petit, g_petit, m_petit, e)[0], e) for e in ECHELLES)

    meilleur = None
    for _score, echelle in grossier[-ECHELLES_CONFIRMEES:]:
        score, point = _pic(champ, gabarit, masque, echelle)
        if point is not None and (meilleur is None or score > meilleur.score):
            meilleur = Medaillon(score, point, echelle)

    if meilleur is None or meilleur.score < seuil:
        return None
    if memoire:
        _DERNIERE_ECHELLE = meilleur.echelle
    return meilleur


def oublier_echelle() -> None:
    """Repartir d'un balayage complet (changement d'aventure, tests)."""
    global _DERNIERE_ECHELLE
    _DERNIERE_ECHELLE = None


def _main(argv) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[2])
        print("usage : python marqueur_joueur.py <capture.png> [...]")
        return 2
    for chemin in argv:
        ecran = cv2.imread(chemin)
        if ecran is None:
            print(f"{chemin} : illisible")
            continue
        oublier_echelle()
        m = trouver_medaillon(ecran, memoire=False)
        if m is None:
            print(f"{chemin} : aucun médaillon au-dessus de {SEUIL:.2f}")
        else:
            print(f"{chemin} : médaillon {m.score:.3f} en {m.point} "
                  f"(échelle {m.echelle:.3f})")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    sys.exit(_main(sys.argv[1:]))
