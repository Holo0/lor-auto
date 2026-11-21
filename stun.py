"""
Lire l'ÉTOURDISSEMENT à l'écran — ce que l'API ne dit pas.

POURQUOI CE MODULE EXISTE (14/11/2026, fait de jeu d'Ewan : « le bot ne
sait pas lire les stuns — il a tenté de bloquer une unité attaquante
alors que le défenseur était stun »).

L'API ne rend que SEPT champs : CardCode, CardID, LocalPlayer et la
géométrie. Ni état, ni statistique. `game_state.BoardCard.can_block` ne
connaît donc que `CantBlock` et `Immobile`, deux mots-clés IMPRIMÉS, et
« Stun » n'existe même pas comme mot-clé de carte dans la base. Une
unité étourdie était donc proposée comme bloqueur, le jeu refusait le
glissé, et l'attaquant passait : **41 fois dans `logs/`**, dont 11 le
14/11, chaque fois après un plan qui venait d'annoncer « tout est
bloqué ».

CE QU'ON LIT, ET CE QU'ON NE LIT PAS
------------------------------------
Le jeu dessine sur la carte étourdie un TOURBILLON VIOLET QUI TOURNE
(description d'Ewan, vérifiée à l'image). Deux pistes évidentes ont été
mesurées et ÉCARTÉES sur la capture de référence :

  - LA TEINTE. « % de pixels violets » donne 63,6 % sur l'unité étourdie
    — mais **50,7 % sur Swain**, un champion à l'illustration violette
    qui n'était pas étourdi du tout. Un faux positif dès la première
    image. C'est la leçon du marqueur du joueur (08/11) et du mot
    « VICTOIRE » (09/11) : un signal fort au mauvais endroit.
  - LE DÉLAVAGE. L'illustration étourdie PARAÎT lavée, mais l'écart-type
    de luminance la place à 59,3 contre 56,8 pour une unité normale :
    non séparable.

CE QUI SÉPARE EST LE MOUVEMENT, ET SURTOUT SA POSITION. Le tourbillon
tourne AU CENTRE de la carte ; l'animation d'un champion vit sur ses
BORDS. Mesuré entre deux captures espacées de 0,7 s, sur une zone
centrée sur `card.center` :

      unité                    centre     bord   ratio
      House Spider ÉTOURDIE     38.04     8.71    4.37
      Swain (animé, sain)        0.00     8.73    0.00
      les cinq autres            0.00     0.00       -

ON EXIGE LES DEUX CONDITIONS, et ce n'est pas de la ceinture-bretelles :
le mouvement central seul suffirait sur cette scène (38 contre 0), mais
Swain prouve qu'une carte PEUT s'animer sans être étourdie. Le jour où
une illustration s'animera en son centre, c'est le ratio qui parlera —
et s'il ne suffit pas, le filet de `actions.execute_blocks` (remplacer
un bloqueur qui refuse son poste) reste derrière.

UNE SEULE SCÈNE OBSERVÉE (14/11/2026). Les seuils sont pris avec une
marge large parce qu'ils reposent sur UNE unité étourdie et six saines.
À revoir au prochain étourdissement rencontré : c'est un fait de jeu,
il viendra d'Ewan ou d'une capture, pas d'un ajustement au jugé.
"""

from __future__ import annotations

from typing import Iterable, Optional

import numpy as np

# Demi-côté de la vignette examinée, en pixels, autour de `card.center`.
# Mesuré sur la capture de référence : les unités du plateau y occupent
# ~110 px. Trop large ferait entrer le décor et la carte voisine.
DEMI_COTE = 55

# Rayon du DISQUE CENTRAL, dans cette vignette. Le tourbillon y tient
# entièrement (pic mesuré à 8-13 px du centre) ; l'animation de Swain
# culmine à 48 px, donc dehors.
RAYON_CENTRE = 28

# Le tourbillon bouge de 38 unités de luminance entre deux captures,
# contre 0,00 pour toute unité saine de la scène. Le plancher est posé
# bien au-dessus du bruit, et bien en dessous de l'observation.
MOUVEMENT_CENTRAL_MIN = 8.0

# Et il bouge PLUS AU CENTRE QU'AU BORD : 4,37 contre 0,00 pour Swain,
# qui bouge uniquement sur ses bords.
RATIO_CENTRE_BORD_MIN = 1.5

# Délai entre les deux captures. Le tourbillon fait un tour en continu ;
# 0,7 s suffit à le déplacer franchement. C'est le SEUL coût en temps de
# cette lecture, et il n'est payé qu'une fois par phase de blocage.
DELAI_ENTRE_CAPTURES = 0.7


def mouvement(avant, apres, centre: tuple) -> tuple:
    """
    (mouvement_central, mouvement_du_bord) autour de `centre`.

    Rend (0.0, 0.0) si la vignette sort de l'image ou si les deux
    captures n'ont pas la même forme : on ne devine pas, on s'abstient.
    """
    # ON NE SUPPOSE RIEN DE CE QU'ON REÇOIT. La couture d'`actions` est
    # bouchonnée dans les suites, et son bouchon rend parfois autre chose
    # qu'une image (une chaîne, par exemple). Une lecture d'écran ne doit
    # JAMAIS faire tomber la boucle de combat : ce qui n'est pas une
    # image se lit « on n'a pas regardé », comme une capture absente.
    forme_a = getattr(avant, "shape", None)
    forme_b = getattr(apres, "shape", None)
    if forme_a is None or forme_a != forme_b or len(forme_a) < 2:
        return 0.0, 0.0
    cx, cy = int(centre[0]), int(centre[1])
    h, w = avant.shape[:2]
    x0, x1 = cx - DEMI_COTE, cx + DEMI_COTE
    y0, y1 = cy - DEMI_COTE, cy + DEMI_COTE
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return 0.0, 0.0

    za = avant[y0:y1, x0:x1].astype(float)
    zb = apres[y0:y1, x0:x1].astype(float)
    ecart = np.abs(za - zb)
    if ecart.ndim == 3:
        ecart = ecart.mean(axis=2)

    hh, ww = ecart.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    rayons = np.sqrt((yy - hh / 2) ** 2 + (xx - ww / 2) ** 2)
    dedans = rayons <= RAYON_CENTRE
    if not dedans.any() or dedans.all():
        return 0.0, 0.0
    return float(ecart[dedans].mean()), float(ecart[~dedans].mean())


def est_etourdie(avant, apres, centre: tuple) -> bool:
    """Cette unité porte-t-elle le tourbillon de l'étourdissement ?"""
    central, bord = mouvement(avant, apres, centre)
    if central < MOUVEMENT_CENTRAL_MIN:
        return False
    return central >= RATIO_CENTRE_BORD_MIN * max(bord, 0.01)


def cartes_etourdies(avant, apres, cartes: Iterable) -> set:
    """
    Les CardID des unités étourdies parmi `cartes`.

    On rend des CardID — l'identité STABLE d'une instance, celle que tout
    le projet utilise pour viser (« la carte est-elle partie ? » se
    vérifie par CardID, jamais par comptage de codes). Une carte sans
    CardID (-1) ne peut pas être suivie : elle est ignorée.
    """
    etourdies = set()
    for carte in cartes or ():
        card_id = getattr(carte, "card_id", -1)
        if card_id is None or card_id < 0:
            continue
        if est_etourdie(avant, apres, carte.center):
            etourdies.add(card_id)
    return etourdies
