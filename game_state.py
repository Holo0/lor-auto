#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game_state.py

Répond à UNE question : « où en est la partie, là, maintenant ? »

C'est la brique qui manquait avant de pouvoir agir. Savoir quelles
cartes on a et quelles stats elles ont (poc.py + detect_chiffres.py) ne
sert à rien si on ne sait pas s'il faut jouer une carte, déclarer une
attaque, assigner des bloqueurs ou simplement attendre. Aucune action
ne doit être déclenchée sans être passée par `GameStateReader`.

--------------------------------------------------------------------
DEUX SOURCES D'INFORMATION, ET POURQUOI
--------------------------------------------------------------------
1. L'API locale (`lor_api`) donne la POSITION et l'IDENTITÉ de chaque
   carte visible. C'est fiable, rapide, et indépendant de la
   résolution. On s'en sert pour tout ce qui est « qui est où ».

2. La vision (OpenCV sur une capture d'écran) donne ce que l'API ne
   dit PAS : à qui est le tour, et qui détient le jeton d'attaque.
   L'API n'expose aucun champ pour ça. Deux tests, de natures
   différentes et pour de bonnes raisons :
       - l'orbe de fin de tour (à droite, à mi-hauteur) est BLEUE quand
         c'est à nous d'agir, GRISE sinon -> test de COULEUR, le bleu
         saturé ne se confond avec rien d'autre à cet endroit ;
       - le jeton d'attaque est l'icône d'épée -> test de FORME
         (template matching). Un test de couleur est inutilisable ici :
         le décor du plateau est en laiton et bois doré, donc dans les
         teintes exactes de l'épée, et le moindre reflet sur un rouage
         passe le seuil. Une forme, non.

--------------------------------------------------------------------
ZONES DU PLATEAU
--------------------------------------------------------------------
L'API ne dit pas non plus dans quelle zone se trouve une carte : il
faut le déduire de sa hauteur. Les cartes sont classées par bandes
horizontales, de bas en haut :

    hand           notre main (les cartes dépassent sous le bord bas)
    board          notre banc
    attack         notre rangée d'attaque (cartes avancées)
    stack          la pile de sorts, au milieu
    enemy_attack   la rangée d'attaque adverse
    enemy_board    le banc adverse
    enemy_hand     la main adverse

Les bornes de `ZONE_BANDS` sont exprimées en ratio de la hauteur de la
fenêtre, mesuré depuis le BAS, sur un point d'ancrage situé à 25% sous
le bord haut de la carte. Elles viennent du bot de référence
(LoR-Bot/code/StateMachine.py) et fonctionnent en 1920x1080.

    >>> python game_state.py inspect

affiche, pour chaque carte réellement présente à l'écran, son ratio
calculé et la zone déduite. C'est l'outil pour valider ou réajuster ces
bornes en 30 secondes au lieu de deviner.

--------------------------------------------------------------------
DISTINGUER « JE BLOQUE » DE « J'AI ATTAQUÉ ET IL A BLOQUÉ »
--------------------------------------------------------------------
Piège classique : dans les deux cas il y a des cartes adverses dans la
bande `enemy_attack`. Le bot de référence s'en sort avec des temporisa-
tions. On fait mieux : notre rangée d'attaque vide et la sienne occupée,
c'est nous qui devons bloquer (phase BLOCKING) ; notre rangée occupée et
la sienne vide, c'est nous l'attaquant et il n'a pas encore répondu
(phase ATTACKING).

Reste le cas où LES DEUX sont occupées, et il est ambigu : soit nous
attaquons et ce sont ses bloqueurs, soit c'est lui qui attaque et un
Challenger a TIRÉ une de nos unités devant lui. Le jeton départage — il
dit à qui appartient ce round d'attaque — mais seulement quand il est
POSITIVEMENT vu du côté adverse : une détection manquée ne doit pas
inventer une attaque adverse. Dans le doute, `combat.CombatLoop` reprend
la question sans rien regarder, puisqu'elle SAIT ce qu'elle a déclaré.

Trois règles rendent cette lecture fiable, et toutes ont été apprises en
regardant le bot encaisser des attaques sans broncher :

1. LE CAMP PRIME SUR LA HAUTEUR. Une unité qui charge traverse trois
   bandes ; laquelle elle atteint dépend de l'animation. Son camp, lui,
   vient de l'API. `reconcile_combat_rows()` range donc toute unité
   avancée d'après `LocalPlayer`, la hauteur ne servant plus qu'à dire
   « elle est engagée ».

2. L'ATTAQUE SE LIT AVANT L'ORBE. L'orbe répond à « puis-je cliquer ? »,
   pas à « que se passe-t-il ? ». Elle est grise pendant la charge
   adverse ; tester l'orbe en premier donnait OPPONENT_TURN au moment
   précis où il fallait bloquer, et le tour se terminait sur un
   « pas d'attaque ce tour » parfaitement faux.

3. « NOTRE RANGÉE EST OCCUPÉE » N'EST PAS « NOUS ATTAQUONS ». Challenger
   et Vulnerable tirent une de nos unités en face de l'attaquant : elle
   traverse la ligne sans qu'on ait rien déclaré. Le 20/08/2026, le bot y
   a lu son attaque et a attendu une résolution qui ne venait pas pendant
   que le jeu réclamait des bloqueurs.

--------------------------------------------------------------------
UTILISATION
--------------------------------------------------------------------
    from game_state import GameStateReader, Phase

    reader = GameStateReader()
    snap = reader.snapshot()

    if snap.phase is Phase.ATTACK_TURN:
        for card in snap.hand:
            ...          # card.center est déjà en coordonnées écran

CLI :
    python game_state.py monitor      # boucle de surveillance en direct
    python game_state.py monitor --trace trace.jsonl   # + ratios, pour diagnostiquer
    python game_state.py inspect      # tableau des rectangles + zones
    python game_state.py vision       # crops de calibration + score du jeton
    python game_state.py snap avec    # capture d'écran nommée
    python game_state.py cut-token    # découpe le template de l'épée
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

import cv2
import numpy as np

import digits
import lor_api
import mots_cles_ecran
import sortie_utf8
from lor_api import ApiUnavailable, Window

LOGGER = logging.getLogger(__name__)


# ============================================================
# ZONES — bandes calibrées (réf. 1920x1080)
# ============================================================

# Point d'ancrage : 25% de la hauteur de la carte sous son bord haut.
# On n'utilise pas le centre de la carte parce que les cartes en main
# dépassent largement sous le bord bas de l'écran : leur centre tombe
# hors cadre et la bande devient impossible à calibrer.
ZONE_ANCHOR_RATIO = 0.25

# (borne supérieure du ratio depuis le BAS, nom de la zone), croissant.
ZONE_BANDS = (
    (0.030, "hand"),
    (0.250, "board"),
    (0.400, "attack"),
    (0.550, "stack"),
    (0.725, "enemy_attack"),
    (0.900, "enemy_board"),
)
FALLBACK_ZONE = "enemy_hand"

ZONE_ORDER = (
    "hand",
    "board",
    "attack",
    "stack",
    "enemy_attack",
    "enemy_board",
    "enemy_hand",
)

# Nombre maximum d'unités sur le banc (règle du jeu).
MAX_BOARD_SIZE = 6

# Où saisir une carte à la souris, en fraction de sa hauteur depuis son
# bord haut. Surtout PAS le centre : les cartes en main dépassent
# largement sous le bord bas de l'écran, leur centre géométrique tombe
# hors cadre, et un clic à cet endroit ne touche rien du tout.
CARD_GRAB_Y_RATIO = 0.15


# ============================================================
# VISION — zones et seuils de couleur
# ============================================================
# Zones exprimées en ratios de la fenêtre ((rx1, ry1), (rx2, ry2)),
# Y depuis le HAUT (convention image).
#
# Les seuils HSV sont en convention OpenCV : H sur 0-179 (donc moitié
# des degrés), S et V sur 0-255. L'image d'entrée est en BGR
# (cf. lor_api.capture_screen_bgr) — ne pas y passer du RGB, sinon
# rouge et bleu sont échangés et les deux tests renvoient n'importe quoi.
#
# ATTENTION — LA SATURATION EST LE SEUL GARDE-FOU QUI COMPTE ICI
# Le plateau de LoR est presque entièrement en laiton et bois doré, donc
# dans les teintes orange. Un test « teinte orange » avec une saturation
# permissive détecte le DÉCOR et renvoie systématiquement vrai. Seul un
# plancher de saturation élevé (>= 190) distingue un élément d'interface
# saturé de la ferronnerie du fond.
#
# Ces valeurs viennent du bot de référence, dont le code convertissait
# du RGB comme si c'était du BGR (rouge et bleu échangés). Pour un tel
# échange, H_vraie = 240° - H_lue, tandis que S et V sont INCHANGÉS
# (max et min d'un triplet sont invariants par permutation des canaux).
# Il ne fallait donc convertir que la teinte, et surtout pas desserrer
# S et V.
#
# `python game_state.py vision` exporte le crop et le masque, et indique
# quel critère (H, S ou V) écarte les pixels, pour réajuster.

TURN_ORB_REGION = ((0.77, 0.42), (0.93, 0.58))
TURN_ORB_HSV = ((100, 190, 180), (122, 255, 255))   # bleu saturé de l'orbe
TURN_ORB_MIN_PX = 100


# ============================================================
# JETON D'ATTAQUE — TEMPLATE MATCHING, PAS DE COULEUR
# ============================================================
# Le jeton est l'icône d'épée. Il est cherché par CORRESPONDANCE DE
# FORME et non par couleur, pour une raison de fond : le décor du
# plateau (laiton, bois doré, reflets sur les rouages) occupe exactement
# les teintes de l'épée. Même avec une saturation stricte, le liseré
# brillant d'un rouage passe le test — c'est ce qui donnait un faux
# positif permanent. Une forme, elle, ne se confond pas avec un reflet.
#
# Le template est à générer une fois depuis une capture :
#     python game_state.py snap avec        # pendant que tu as le jeton
#     python game_state.py cut-token        # entoure l'épée à la souris
#
# À VÉRIFIER EN JEU : si l'épée apparaît aussi du côté adverse quand
# c'est LUI qui a le jeton, alors la seule présence de l'icône ne suffit
# pas — c'est son côté qui compte. `find_attack_token()` gère déjà ce cas
# en comparant la position du match à la ligne médiane entre les deux
# nexus (donnée par l'API, donc fiable). Si l'icône ne s'affiche jamais
# côté adverse, ce test est simplement toujours vrai et ne coûte rien.

ATTACK_TOKEN_TEMPLATE = lor_api.PROJECT_ROOT / "assets" / "attack_token.png"

# 0.75 : valeur validée en jeu. Si un faux positif apparaît un jour, la
# bonne réaction est de RECADRER LE TEMPLATE plus serré, pas de remonter
# ce seuil. Un template qui embarque du décor a un score plafonné (le
# décor bouge), donc on est tenté de descendre le seuil pour compenser —
# et on finit par accepter des correspondances qui n'en sont pas. Le
# score affiché par `monitor` doit rester nettement au-dessus du seuil
# quand le jeton est là, et nettement en dessous quand il ne l'est pas.
# 02/09/2026 : avec le template MASQUÉ (fond exclu), Ewan mesure 0.60-0.70
# épée présente. Le masque a changé la nature du score — il ne porte plus
# que sur l'épée, dont les reflets et la légère pulsation font varier les
# pixels — et la recherche multi-échelle ci-dessous doit le remonter. Le
# seuil descend à 0.55 : sans fond dans le template, un faux positif sur
# le décor devient improbable (0.03 sur un fond quelconque hors ligne).
# À confirmer avec `monitor` : score SANS jeton nettement sous ce seuil.
ATTACK_TOKEN_MATCH_THRESHOLD = 0.55

# Échelles essayées pour le template. La capture qui a servi à découper
# l'épée date du 06/08 ; si la fenêtre du jeu n'a plus tout à fait la
# même taille, l'épée à l'écran n'a plus celle du template et le score
# plafonne. On garde la meilleure échelle — `TokenMatch.scale` le dit, et
# si elle est toujours la même (≠ 1.0), c'est un `cut-token` à refaire.
ATTACK_TOKEN_SCALES = (0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15)

# --- le prix des sept échelles, et comment on le paie -----------------
# Un matching MASQUÉ coûte cinq fois un matching simple : 104 ms contre
# 23 sur la région, mesuré le 10/11/2026. Sept échelles en pleine
# résolution, c'est près d'une seconde, et `snapshot()` en fait une à
# chaque lecture.
#
# MESURÉ LE 10/11/2026, en rejouant une trace réelle : le jeton est
# ABSENT dans 68 % des lectures (73 sur 107), et c'est le cas CHER —
# 911 ms de médiane contre 234 quand il est là, parce que l'échelle
# gagnante mise en cache échouait et déclenchait le balayage complet.
# Moyenne 696 ms, soit l'essentiel des 2,2 s de lecture d'une itération.
#
# D'où DEUX ÉTAGES : un relevé de TOUTES les échelles sur l'image
# RÉDUITE (43 ms pour les sept), puis la confirmation en PLEINE
# résolution des quelques PICS retenus (7 ms chacun). On ne paie plus
# jamais une corrélation pleine résolution sur toute la région.
#
# POURQUOI DEUX ÉTAGES PLUTÔT QU'UN SEUIL SUR L'IMAGE RÉDUITE : le score
# réduit n'est pas le score — mesuré sur 501 captures réelles, il est
# plus haut de 0,065 en médiane. Le confirmer en pleine résolution rend
# un score de même nature qu'avant, donc un seuil qui veut dire la même
# chose.
ATTACK_TOKEN_COARSE = 0.25

# Plancher de taille du template réduit : en dessous, la forme n'a plus
# assez de pixels pour que la corrélation veuille dire quelque chose. En
# dessous de ce plancher on ne réduit pas du tout (cas des templates
# minuscules des tests) et le relevé EST la lecture.
ATTACK_TOKEN_COARSE_MIN_SIDE = 24

# Pics du relevé grossier confirmés en pleine résolution. Un seul
# suffirait sur toutes les captures mesurées ; on en garde trois parce
# qu'un pic grossier mal placé coûterait une détection et que chaque pic
# supplémentaire ne coûte que 7 ms.
ATTACK_TOKEN_PEAKS = 2

# Marge (pixels pleine résolution) autour d'un pic : le relevé grossier
# situe le template au quart de pixel près, la confirmation doit pouvoir
# glisser autour.
ATTACK_TOKEN_CONFIRM_MARGIN = 32

# Région de recherche volontairement large en hauteur : elle doit couvrir
# les DEUX moitiés du plateau pour pouvoir déterminer de quel côté se
# trouve l'épée. La restreindre en largeur suffit à garder le matching
# rapide et à éviter de matcher une épée dessinée sur l'illustration
# d'une carte en main.
ATTACK_TOKEN_SEARCH_REGION = ((0.66, 0.18), (1.00, 0.92))


# ============================================================
# MULLIGAN
# ============================================================
# Pendant le mulligan, les cartes proposées sont toutes alignées à la
# même hauteur, au milieu de l'écran. Attention : les cartes en main en
# cours de partie sont ALIGNÉES AUSSI — c'est la hauteur (bien plus
# basse) et le plateau vide qui font la différence.

MULLIGAN_BAND = (0.45, 0.80)
MULLIGAN_MAX_SPREAD = 0.02
MULLIGAN_MIN_CARDS = 3


# ============================================================
# PHASES
# ============================================================

class Phase(Enum):
    """Phase de jeu courante. C'est le seul vocabulaire que la couche
    de décision doit connaître."""

    NO_API = "api_injoignable"       # client fermé ou API pas prête
    MENUS = "menus"                  # hors partie
    MULLIGAN = "mulligan"            # choix des cartes de départ
    OPPONENT_TURN = "tour_adverse"   # rien à faire, on attend
    ATTACK_TURN = "notre_tour_attaque"   # à nous, avec le jeton d'attaque
    DEFEND_TURN = "notre_tour_defense"   # à nous, sans le jeton
    OUR_TURN = "notre_tour_indetermine"  # à nous, jeton non déterminable
    BLOCKING = "blocage"             # l'adversaire attaque, il faut bloquer
    ATTACKING = "attaque_declaree"   # notre attaque est posée, ça résout
    SPELL_STACK = "sort_en_attente"  # un sort attend une réponse
    GAME_OVER = "partie_terminee"    # événement, émis UNE seule fois

    @property
    def is_our_move(self) -> bool:
        """True si le bot doit agir maintenant."""
        return self in (
            Phase.MULLIGAN,
            Phase.ATTACK_TURN,
            Phase.DEFEND_TURN,
            Phase.OUR_TURN,
            Phase.BLOCKING,
            Phase.SPELL_STACK,
        )

    @property
    def in_game(self) -> bool:
        """True si une partie est en cours (ni menus, ni API absente)."""
        return self not in (Phase.NO_API, Phase.MENUS, Phase.GAME_OVER)


# ============================================================
# MODÈLE DE CARTE
# ============================================================

def _normalize_keyword(value: str) -> str:
    """« Can't Block » et « CantBlock » doivent matcher : on retire tout
    ce qui n'est pas alphanumérique et on passe en minuscules."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


@dataclass
class BoardCard:
    """Une carte visible à l'écran, enrichie de sa zone et de ses
    coordonnées écran (prêtes à cliquer)."""

    card_id: int
    code: str
    name: str
    base_cost: int
    base_attack: int
    base_health: int
    type: str
    keywords: tuple
    keyword_refs: tuple
    description: str
    spell_speed: str          # Burst / Fast / Slow, depuis spellSpeedRef
    local: bool
    zone: str
    ratio: float
    box: tuple      # (left, top, right, bottom) en coordonnées bureau
    center: tuple   # (x, y) en coordonnées bureau
    known: bool     # False si le cardCode est absent de card_sets
    # `supertype` vaut "Champion" pour les champions — ET pour leur version
    # de niveau 2, qui a son propre cardCode (01IO015 Yasuo → 01IO015T1
    # une fois monté). L'API rapporte ce nouveau code : le level-up se lit
    # donc SANS vision, il suffit de regarder le code (cf. is_leveled).
    supertype: str = ""
    collectible: bool = True
    # Bord droit de la partie VISIBLE de la carte quand sa voisine de
    # droite la recouvre (main pleine). None = rien ne la recouvre. Posé
    # par group_by_zone, lu par grab_point.
    visible_right: Optional[int] = None

    # ÉTOURDIE — LU À L'ÉCRAN, PAS DANS L'API (14/11/2026, fait de jeu
    # d'Ewan). L'API ne rend que sept champs : l'étourdissement n'en fait
    # pas partie, et « Stun » n'existe même pas comme mot-clé de carte.
    # Rempli par `actions.lire_les_etourdies` avant un blocage, au vu du
    # tourbillon violet qui tourne au centre de la carte (cf. `stun.py`).
    # FAUX PAR DÉFAUT VEUT DIRE « ON N'A PAS REGARDÉ », pas « elle est
    # saine » : le filet de `execute_blocks` — remplacer un bloqueur qui
    # refuse son poste — reste derrière, et c'est lui qui tranche quand
    # la lecture n'a pas eu lieu.
    stunned: bool = False

    # MOTS-CLÉS LUS À L'ÉCRAN (20/11/2026). L'API ne rend qu'un CardCode :
    # un Challenger ou un Overwhelm ACCORDÉ en jeu est invisible. Mesuré
    # sur 06SI009 « Pâle orchestre », qui imprime 2 mots-clés et en
    # affiche 4. Rempli par `lire_les_mots_cles`.
    #
    # VIDE VEUT DIRE « ON N'A PAS REGARDÉ », pas « elle n'a rien » — même
    # règle que `stunned`. C'est pourquoi `has` fait une UNION : l'écran
    # COMPLÈTE la carte imprimée et ne retire jamais rien. Conséquence
    # assumée : un Silence ne se voit pas.
    keywords_lus: tuple = ()

    # Stats LUES à l'écran, remplies par enrich_with_live_stats().
    # None tant que l'OCR n'a pas tourné : ne pas confondre avec 0.
    cost_read: Optional[int] = None
    attack_read: Optional[int] = None
    health_read: Optional[int] = None

    # --- stats effectives ----------------------------------------------
    # `attack` et `health` sont des PROPRIÉTÉS : elles renvoient la valeur
    # lue à l'écran si on l'a, la valeur de base sinon. Tout le code de
    # décision utilise donc automatiquement les stats réelles dès que
    # l'OCR a tourné, sans qu'aucun appelant ait à le savoir — buffs,
    # dégâts subis et affaiblissements compris.
    @property
    def cost(self) -> int:
        return self.base_cost if self.cost_read is None else self.cost_read

    @property
    def attack(self) -> int:
        return self.base_attack if self.attack_read is None else self.attack_read

    @property
    def health(self) -> int:
        return self.base_health if self.health_read is None else self.health_read

    @property
    def stats_are_live(self) -> bool:
        return self.attack_read is not None or self.health_read is not None

    @property
    def cost_is_live(self) -> bool:
        """Le coût utilisé vient-il de l'écran plutôt que de card_sets ?"""
        return self.cost_read is not None

    @property
    def cost_gap(self) -> Optional[int]:
        """
        Écart entre le coût affiché et le coût de base, ou None.

        Négatif = la carte est RÉDUITE, positif = elle coûte plus cher que
        sur le papier. N'a de sens que pour une carte connue de card_sets :
        pour une carte inconnue le coût de base vaut 0, et l'écart ne
        mesurerait que cette absence.
        """
        if self.cost_read is None or not self.known:
            return None
        return self.cost_read - self.base_cost

    @property
    def cost_is_known(self) -> bool:
        """
        A-t-on un coût digne de confiance ?

        Une carte absente de card_sets a un coût de base à 0, ce qui la
        ferait passer pour gratuite. Elle n'est jouable que si son coût a
        été LU à l'écran.
        """
        return self.known or self.cost_read is not None

    # --- type de carte -------------------------------------------------
    @property
    def is_unit(self) -> bool:
        return self.type == "Unit"

    @property
    def is_spell(self) -> bool:
        return self.type == "Spell"

    @property
    def is_ability(self) -> bool:
        return self.type == "Ability"

    @property
    def is_equipment(self) -> bool:
        return self.type == "Equipment"

    @property
    def is_landmark(self) -> bool:
        return self.type == "Landmark"

    @property
    def is_champion(self) -> bool:
        return self.is_unit and self.supertype == "Champion"

    @property
    def is_leveled(self) -> bool:
        """
        Champion monté de niveau. Dans card_sets, la version de niveau 2
        est une carte NON collectionnable au code suffixé (…T1, …T2), et
        c'est ce code-là que l'API rapporte une fois le champion monté.
        """
        return self.is_champion and not self.collectible

    # --- mots-clés -----------------------------------------------------
    def has(self, keyword: str) -> bool:
        """Teste un mot-clé indifféremment sur le libellé affiché ou sur
        sa référence interne (insensible à la casse et à la ponctuation)."""
        target = _normalize_keyword(keyword)
        return any(
            _normalize_keyword(existing) == target
            for existing in (*self.keywords, *self.keyword_refs,
                             *self.keywords_lus)
        )

    # --- points de saisie ----------------------------------------------
    @property
    def grab_point(self) -> tuple:
        """
        Point où attraper la carte à la souris, en coordonnées bureau.

        Voir CARD_GRAB_Y_RATIO : on vise le haut de la carte, seule partie
        garantie visible pour une carte en main.

        EN X, LE MILIEU DE CE QUI EST VISIBLE, pas de la carte. Dans une
        main pleine les cartes se recouvrent (06/09/2026, 9 cartes : 175 px
        de large, espacées de 99 px — la voisine de DROITE couvre les trois
        quarts de la carte) ; viser le centre géométrique, c'est viser à
        11 px de la voisine, et c'est elle que le jeu attrape (« The List »
        partie sur la pile à la place de Buhru Lookout, quatorze fois).
        """
        left, top, right, bottom = self.box
        edge = right if self.visible_right is None else min(right, self.visible_right)
        return ((left + edge) // 2, int(top + CARD_GRAB_Y_RATIO * (bottom - top)))

    # --- mots-clés (suite) ----------------------------------------------
    @property
    def can_block(self) -> bool:
        # `stunned` est le PREMIER état lu à l'écran plutôt que dans
        # card_sets : une unité étourdie ne peut ni bloquer ni attaquer,
        # et rien dans l'API ne le dit. Le reste ne change pas — ce sont
        # toujours les deux mots-clés IMPRIMÉS.
        return not (self.stunned or self.has("CantBlock") or self.has("Immobile"))

    @property
    def can_attack(self) -> bool:
        return not (self.stunned or self.has("CantAttack") or self.has("Immobile"))

    def __str__(self) -> str:
        # L'astérisque signale une stat lue à l'écran plutôt que déduite
        # de card_sets : indispensable pour distinguer « le bot voit un
        # 5/5 » de « le bot suppose un 5/5 » quand une décision surprend.
        mark = "*" if self.stats_are_live else ""
        cost_mark = "*" if self.cost_is_live else ""
        suffix = "" if self.known else " (inconnue)"
        return (
            f"{self.name} ({self.cost}{cost_mark}) "
            f"{self.attack}/{self.health}{mark}{suffix}"
        )


# ============================================================
# CLASSIFICATION EN ZONES
# ============================================================

# Référence de géométrie : position des deux nexus, en ratio depuis le
# bas, dans la configuration où ZONE_BANDS a été validée. Enregistrée par
# `python game_state.py calibrate-zones`.
#
# POURQUOI : ZONE_BANDS est exprimée en fraction de la HAUTEUR DE FENÊTRE,
# ce qui suppose que le plateau occupe toujours la même proportion de
# l'écran. C'est faux dès que le rapport d'aspect change. Les deux nexus,
# eux, sont donnés par l'API et encadrent le plateau : en mesurant leur
# écartement, on sait de combien le plateau a grandi ou rétréci, et on
# rééchelonne les bandes en conséquence.
#
# Tant que la calibration n'a pas eu lieu, rien ne change : on ne va pas
# rééchelonner à partir d'une référence inventée.
ZONE_CALIBRATION_KEY = "zone_nexus_reference"


def nexus_span(rectangles: list, window: Window):
    """
    (ratio du nexus allié, ratio du nexus adverse), depuis le BAS.
    None si l'un des deux manque.
    """
    centres = {}
    for rect in rectangles:
        if rect.get("CardCode") == lor_api.NEXUS_CARD_CODE:
            centre = rect["TopLeftY"] - rect["Height"] / 2
            centres[bool(rect.get("LocalPlayer"))] = centre / window.height
    if True in centres and False in centres:
        return (centres[True], centres[False])
    return None


def rescale_bands(bands: tuple, reference: tuple, current: tuple) -> tuple:
    """
    Transpose des bandes mesurées dans une géométrie de référence vers la
    géométrie courante, en s'appuyant sur l'écartement des nexus.

    Une bande à mi-chemin entre les deux nexus le reste, quelle que soit
    la résolution.
    """
    ref_low, ref_high = reference
    cur_low, cur_high = current
    ref_span = ref_high - ref_low
    cur_span = cur_high - cur_low
    if abs(ref_span) < 1e-6 or abs(cur_span) < 1e-6:
        return bands
    return tuple(
        (cur_low + (bound - ref_low) / ref_span * cur_span, name)
        for bound, name in bands
    )


def zone_ratio(rect: dict, window: Window) -> float:
    """
    Position verticale normalisée d'un rectangle de l'API : 0.0 = bas de
    l'écran, 1.0 = haut. Les Y de l'API étant déjà mesurés depuis le bas,
    aucune inversion n'est nécessaire ici.
    """
    if window.height <= 0:
        return 0.0
    anchor = rect["TopLeftY"] - ZONE_ANCHOR_RATIO * rect["Height"]
    return anchor / window.height


def classify_zone(rect: dict, window: Window, bands: tuple = ZONE_BANDS) -> str:
    """Zone du plateau déduite de la hauteur du rectangle."""
    ratio = zone_ratio(rect, window)
    for upper_bound, name in bands:
        if ratio < upper_bound:
            return name
    return FALLBACK_ZONE


def zone_band(name: str) -> tuple:
    """
    Bornes (basse, haute) d'une zone, en ratio depuis le BAS de l'écran.
    Lève KeyError si la zone n'existe pas.
    """
    low = 0.0
    for upper_bound, zone in ZONE_BANDS:
        if zone == name:
            return (low, upper_bound)
        low = upper_bound
    if name == FALLBACK_ZONE:
        return (low, 1.0)
    raise KeyError(name)


def zone_center_from_top(name: str) -> float:
    """
    Milieu d'une zone, exprimé en ratio depuis le HAUT (convention écran).

    Sert à viser une zone à la souris. Le calculer à partir de ZONE_BANDS
    plutôt que d'écrire la valeur en dur garantit que le point visé et le
    classement des cartes ne peuvent pas diverger : retoucher une bande
    déplace automatiquement la cible.
    """
    low, high = zone_band(name)
    return 1.0 - (low + high) / 2


def empty_zones() -> dict:
    """Dict zone -> tuple vide, avec TOUTES les clés présentes, pour que
    l'appelant puisse faire zones["attack"] sans jamais se faire un KeyError."""
    return {name: () for name in ZONE_ORDER}


def group_by_zone(cards: Iterable[BoardCard]) -> dict:
    """Regroupe les cartes par zone, chaque zone triée de gauche à droite."""
    buckets = {name: [] for name in ZONE_ORDER}
    for card in cards:
        buckets.setdefault(card.zone, []).append(card)
    zones = {
        name: tuple(sorted(items, key=lambda c: c.center[0]))
        for name, items in buckets.items()
    }
    mark_hand_overlap(zones.get("hand", ()))
    return zones


# En dessous de cette part visible, on ne réduit plus la zone de saisie :
# un recouvrement quasi total serait une lecture en cours d'animation, et
# viser une bande de quelques pixels raterait à coup sûr.
HAND_MIN_VISIBLE_RATIO = 0.25


def mark_hand_overlap(hand) -> None:
    """
    Pose `visible_right` sur chaque carte de la main que sa voisine de
    droite recouvre. Le jeu dessine la main en éventail, chaque carte SOUS
    la suivante : la partie qui reste cliquable est entre son bord gauche
    et le bord gauche de la voisine.
    """
    for card, following in zip(hand, hand[1:]):
        left, _, right, _ = card.box
        next_left = following.box[0]
        if next_left < right and next_left - left >= (right - left) * HAND_MIN_VISIBLE_RATIO:
            card.visible_right = next_left
        else:
            card.visible_right = None
    if hand:
        hand[-1].visible_right = None


# Les trois bandes que les unités traversent quand elles chargent. Une
# unité qui s'y trouve est engagée dans un combat ; la seule question est
# de savoir dans quel camp.
COMBAT_BANDS = ("attack", "stack", "enemy_attack")


def reconcile_combat_rows(cards: Iterable[BoardCard]) -> list:
    """
    Range les unités avancées selon leur CAMP, et non selon la bande où
    leur hauteur les a fait tomber. Modifie `card.zone` sur place et
    renvoie la liste.

    Pourquoi c'est nécessaire. Une unité qui charge avance vers la ligne
    médiane, et la bande d'arrivée fait quinze centièmes de hauteur pour
    un mouvement dont l'amplitude dépend de l'animation, de la taille de
    la carte et du décalage du plateau. Il suffit de peu pour qu'un
    attaquant adverse dépasse et retombe dans `stack`, ou reste court et
    soit compté dans `enemy_board`. Le bot lisait alors « sort en
    attente » ou « rien à bloquer » au moment précis où il fallait poser
    des bloqueurs.

    La hauteur est une mesure bruitée ; le camp, lui, est donné par
    l'API et ne se trompe jamais. On garde donc la hauteur pour dire
    « cette unité est avancée » et le camp pour dire « de quel côté ».

    La bande `stack` est la seule ambiguë, et l'ambiguïté est facile à
    lever : on n'y voit JAMAIS d'unité. Une carte qui n'est pas une
    unité — ou dont on ignore le type — y reste, et sera traitée comme
    un sort : c'est le repli le moins destructeur, puisqu'il conduit à
    passer et non à traîner des cartes au hasard.
    """
    cards = list(cards)
    for card in cards:
        if card.zone in COMBAT_BANDS and card.is_unit:
            card.zone = "attack" if card.local else "enemy_attack"
        elif card.zone in COMBAT_BANDS and (card.is_spell or card.is_ability):
            # La réciproque : un SORT (ou une compétence) ne se tient jamais
            # dans une rangée d'attaque. Où qu'il tombe en hauteur, il est
            # sur la pile — sinon un sort adverse lu dans « enemy_attack »
            # passait pour une attaque, et dans « attack » pour la nôtre.
            card.zone = "stack"
    return cards


# ============================================================
# VISION
# ============================================================

def _mask_pixel_count(
    screen: np.ndarray, window: Window, region: tuple, hsv_range: tuple
) -> tuple:
    """
    Compte les pixels d'une zone qui tombent dans un intervalle HSV.
    Renvoie (pixels_retenus, pixels_total) ; (0, 0) si la zone est hors cadre.
    """
    crop = lor_api.crop_box(screen, window.rel_box(region))
    if crop is None or crop.size == 0:
        return 0, 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    low, high = hsv_range
    mask = cv2.inRange(hsv, np.array(low, dtype=np.uint8), np.array(high, dtype=np.uint8))
    return int(cv2.countNonZero(mask)), int(mask.size)


# LE TEXTE DU BOUTON DIT LA PHASE. Sur la capture d'Ewan
# (calibration_crops/orbe_de_tour_zone.png), le bouton bleu affiche
# « RÉSOUDRE » pendant une fenêtre de réponse : la couleur dit « à toi de
# cliquer », le texte dit POURQUOI. Un template par libellé dans
# assets/orb/ (`resoudre.png` est fourni ; `python game_state.py cut-button
# fin_du_tour` en ajoute d'autres). Le libellé lu est un TÉMOIN de plus :
# « resoudre » confirme SPELL_STACK même si l'API ne rapportait pas le sort.
# `cible.png` (« SÉLECTIONNER LA CIBLE », tiré de la capture bloquée du
# 05/09/2026) : le jeu attend que NOUS désignions une cible — un « OK » n'y
# fait rien, c'est une annulation qu'il faut (actions.respond_to_stack).
TURN_BUTTON_DIR = lor_api.PROJECT_ROOT / "assets" / "orb"
TURN_BUTTON_THRESHOLD = 0.80
_BUTTON_TEMPLATES: Optional[dict] = None
_BUTTON_TEMPLATES_STAMP: Optional[tuple] = None


def _button_templates() -> dict:
    """{libellé: template gris}, rechargé si le dossier change."""
    global _BUTTON_TEMPLATES, _BUTTON_TEMPLATES_STAMP
    try:
        files = sorted(TURN_BUTTON_DIR.glob("*.png"))
    except OSError:
        files = []
    stamp = tuple((f.name, f.stat().st_mtime) for f in files)
    if _BUTTON_TEMPLATES is None or stamp != _BUTTON_TEMPLATES_STAMP:
        templates = {}
        for path in files:
            image = cv2.imread(str(path))
            if image is not None:
                templates[path.stem] = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _BUTTON_TEMPLATES, _BUTTON_TEMPLATES_STAMP = templates, stamp
    return _BUTTON_TEMPLATES


def read_turn_button(screen: np.ndarray, window: Window) -> tuple:
    """
    Le libellé du bouton de tour : (libellé|None, meilleur score).

    Comparaison en niveaux de gris sur la zone de l'orbe, un template par
    libellé connu. Sans template ou sous le seuil : (None, score).
    """
    templates = _button_templates()
    if not templates:
        return None, 0.0
    crop = lor_api.crop_box(screen, window.rel_box(TURN_ORB_REGION))
    if crop is None or crop.size == 0:
        return None, 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    best, best_score = None, 0.0
    for label, template in templates.items():
        th, tw = template.shape[:2]
        if th > gray.shape[0] or tw > gray.shape[1]:
            continue
        score = float(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED).max())
        if score > best_score:
            best, best_score = label, score
    if best_score < TURN_BUTTON_THRESHOLD:
        return None, best_score
    return best, best_score


def turn_orb_is_active(screen: np.ndarray, window: Window) -> bool:
    """
    True si l'orbe de fin de tour est colorée (bleue) : c'est à nous
    d'agir. Grise = l'adversaire joue, ou une animation est en cours.
    """
    count, _ = _mask_pixel_count(screen, window, TURN_ORB_REGION, TURN_ORB_HSV)
    return count >= TURN_ORB_MIN_PX


# --- jeton d'attaque : correspondance de forme -------------------------

# Cache indexé sur (chemin, date de modification) : régénérer le template
# avec `cut-token` le recharge automatiquement, sans relancer le bot.
_TEMPLATE_CACHE: dict = {}


def load_template(path) -> Optional[np.ndarray]:
    """Charge un template BGR, avec cache invalidé par la date du fichier."""
    loaded = load_template_with_mask(path)
    return None if loaded is None else loaded[0]


def load_template_with_mask(path) -> Optional[tuple]:
    """
    Charge un template et son MASQUE : (BGR, masque ou None).

    Le masque est le canal alpha du PNG quand il en a un — les pixels
    transparents ne comptent pas dans la correspondance. C'est ce qui
    permet de chercher l'ÉPÉE et non « l'épée devant une gemme à 3 de
    mana de sort » : le décor derrière le jeton change (compteur de mana,
    reflets des rouages) et un template qui l'embarque voit son score
    s'effondrer dès que le compteur n'est plus celui de la capture. Vu en
    jeu le 02/09/2026 : jeton jamais reconnu, DEFEND_TURN permanent.
    """
    path = Path(path)
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE.clear()
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None:
            _TEMPLATE_CACHE[key] = None
        elif raw.ndim == 3 and raw.shape[2] == 4:
            mask = raw[:, :, 3]
            # Un alpha uniformément opaque n'est pas un masque.
            _TEMPLATE_CACHE[key] = (
                np.ascontiguousarray(raw[:, :, :3]),
                mask if int(mask.min()) < 255 else None,
            )
        elif raw.ndim == 2:
            _TEMPLATE_CACHE[key] = (cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR), None)
        else:
            _TEMPLATE_CACHE[key] = (raw, None)
    return _TEMPLATE_CACHE[key]


def icon_mask(crop: np.ndarray) -> np.ndarray:
    """
    Masque de l'ICÔNE dans un crop : les pixels orangés et saturés de
    l'épée, nettoyés (ouverture), réduits à la plus grande composante
    connexe, puis refermés. Les flammes qui la coiffent sont volontairement
    exclues : elles s'animent, et une forme qui bouge ne peut pas être un
    repère. C'est ce masque qui devient le canal alpha du template.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(ICON_HSV_LOW), np.array(ICON_HSV_HIGH))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = np.where(labels == biggest, 255, 0).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


# Teintes de l'épée (HSV OpenCV, H sur 0-179) : orange à jaune, franc et
# lumineux. Le laiton du décor est plus terne (S plus faible).
ICON_HSV_LOW = (5, 110, 120)
ICON_HSV_HIGH = (38, 255, 255)


@dataclass
class TokenMatch:
    """Résultat de la recherche de l'épée."""

    found: bool
    score: float
    position: Optional[tuple] = None   # centre du match, coords bureau
    ours: Optional[bool] = None        # None si indéterminable
    template_missing: bool = False
    scale: float = 1.0                 # facteur appliqué au template pour ce score

    @property
    def side(self) -> str:
        if not self.found:
            return "-"
        if self.ours is None:
            return "?"
        return "nous" if self.ours else "adversaire"


def nexus_points(rectangles: list, window: Window) -> tuple:
    """
    Centres écran des deux nexus : (le nôtre, celui d'en face).

    Le nexus adverse est une cible de sort toujours valide : c'est le
    repli qui évite de rester coincé en mode ciblage quand aucune unité
    ne convient.
    """
    centres = {}
    for rect in rectangles:
        if rect.get("CardCode") == lor_api.NEXUS_CARD_CODE:
            centres[bool(rect.get("LocalPlayer"))] = lor_api.rect_center_screen(rect, window)
    return centres.get(True), centres.get(False)


def nexus_boxes(rectangles: list, window: Window) -> tuple:
    """
    (rectangle écran du nôtre, rectangle écran de celui d'en face).

    L'API donne la POSITION des deux nexus. C'est ce qui permet de lire
    leurs PV sans coordonnées en dur : le chiffre se découpe relativement
    au rectangle du nexus, comme les badges de stats des cartes. Une seule
    calibration sert alors pour les deux camps et pour toute résolution.
    """
    boxes = {}
    for rect in rectangles:
        if rect.get("CardCode") == lor_api.NEXUS_CARD_CODE:
            boxes[bool(rect.get("LocalPlayer"))] = lor_api.rect_to_screen_box(rect, window)
    return boxes.get(True), boxes.get(False)


def nexus_midline_y(rectangles: list, window: Window) -> float:
    """
    Y écran de la ligne médiane entre les deux nexus.

    C'est la frontière « notre moitié / sa moitié », et elle vient de
    l'API : elle est donc juste quelle que soit la résolution, sans
    calibration. Repli sur le milieu de la fenêtre si un nexus manque.
    """
    centres = {}
    for rect in rectangles:
        if rect.get("CardCode") == lor_api.NEXUS_CARD_CODE:
            centres[bool(rect.get("LocalPlayer"))] = lor_api.rect_center_screen(rect, window)[1]

    if True in centres and False in centres:
        return (centres[True] + centres[False]) / 2
    return window.y + window.height / 2


def find_attack_token(
    screen: np.ndarray,
    window: Window,
    midline_y: Optional[float] = None,
    threshold: float = ATTACK_TOKEN_MATCH_THRESHOLD,
    region: tuple = ATTACK_TOKEN_SEARCH_REGION,
    template_path=ATTACK_TOKEN_TEMPLATE,
    scales: tuple = ATTACK_TOKEN_SCALES,
) -> TokenMatch:
    """
    Cherche l'icône d'épée par correspondance de forme, à plusieurs
    échelles (cf. ATTACK_TOKEN_SCALES) ; la meilleure est retenue. Le
    balayage se fait sur l'image réduite et la lecture est confirmée en
    pleine résolution (cf. ATTACK_TOKEN_COARSE) : le score rendu est
    donc toujours un score PLEINE RÉSOLUTION, de même nature qu'avant le
    10/11/2026 — seul son coût a changé.

    Renvoie toujours le score, même en cas d'échec : c'est ce qui permet
    de régler le seuil en connaissance de cause. Un score de 0.78 quand
    le jeton est visible signifie « seuil trop haut » ; un score de 0.85
    quand il est absent signifie « template trop générique, recadre-le
    plus serré sur l'épée ».

    `ours` compare la position du match à la ligne médiane des nexus :
    notre moitié est celle du BAS, donc les Y les plus grands.
    """
    loaded = load_template_with_mask(template_path)
    if loaded is None:
        return TokenMatch(found=False, score=0.0, template_missing=True)
    template, mask = loaded

    box = window.rel_box(region)
    crop = lor_api.crop_box(screen, box)
    if crop is None:
        LOGGER.warning("Région de recherche du jeton hors cadre : %s", box)
        return TokenMatch(found=False, score=0.0)

    c_h, c_w = crop.shape[:2]
    if template.shape[0] > c_h or template.shape[1] > c_w:
        LOGGER.warning(
            "Template (%dx%d) plus grand que la région de recherche (%dx%d) : "
            "élargis ATTACK_TOKEN_SEARCH_REGION ou recadre le template.",
            template.shape[1], template.shape[0], c_w, c_h,
        )
        return TokenMatch(found=False, score=0.0)

    # DEUX ÉTAGES, cf. ATTACK_TOKEN_COARSE : toutes les échelles sur
    # l'image réduite, puis les meilleurs PICS confirmés en pleine
    # résolution. Aucune corrélation pleine résolution ne porte plus sur
    # toute la région.
    best = _best_match(crop, template, mask, scales)
    score, location, (t_w, t_h), scale = best

    if score < threshold:
        return TokenMatch(found=False, score=score, scale=scale)

    centre = (
        box[0] + location[0] + t_w // 2,
        box[1] + location[1] + t_h // 2,
    )
    ours = None if midline_y is None else centre[1] > midline_y
    return TokenMatch(found=True, score=score, position=centre, ours=ours, scale=scale)


def _coarse_reduction(template, scales: tuple) -> float:
    """
    Facteur de réduction du relevé grossier, ou 1.0 s'il ne faut pas
    réduire. Le plus petit côté du template, à la plus petite échelle,
    doit rester au-dessus de `ATTACK_TOKEN_COARSE_MIN_SIDE`.
    """
    cote = min(template.shape[:2]) * min(scales or (1.0,))
    if cote <= 0:
        return 1.0
    reduction = max(ATTACK_TOKEN_COARSE, ATTACK_TOKEN_COARSE_MIN_SIDE / cote)
    return 1.0 if reduction >= 1.0 else reduction


def _best_match(crop, template, mask, scales: tuple) -> tuple:
    """
    Le meilleur matching du template dans `crop`, toutes échelles
    confondues : (score, position, (largeur, hauteur), échelle).

    Le relevé est fait sur une image RÉDUITE — sept corrélations masquées
    pour le prix d'un sixième — puis les meilleurs pics sont confirmés en
    PLEINE résolution dans une petite fenêtre. Le score rendu est donc
    toujours un score pleine résolution, comparable à celui d'avant le
    10/11/2026 ; seul son COÛT a changé.
    """
    scales = tuple(scales) or (1.0,)
    reduction = _coarse_reduction(template, scales)
    reduit = crop if reduction >= 1.0 else cv2.resize(
        crop, None, fx=reduction, fy=reduction, interpolation=cv2.INTER_AREA
    )

    # CHAQUE ÉCHELLE GARDE SES PICS, et c'est la leçon du 10/11/2026 :
    # une première version ne retenait que l'échelle la mieux notée sur
    # l'image réduite, puis la confirmait seule. Elle a PERDU 2 jetons
    # sur 118 au balayage des captures réelles — le relevé grossier y
    # préférait 1.05, et la lecture pleine résolution tombait à 0.48 là
    # où l'échelle 1.0 donnait 0.62. Un classement grossier ne décide
    # pas d'une échelle : il désigne des ENDROITS à regarder de près.
    releve = []
    for scale in scales:
        carte, taille = _score_map(reduit, template, mask, scale * reduction)
        if carte is None:
            continue
        releve.append((carte, taille, scale))

    if not releve:                          # template plus grand que la région
        return _match_at_scale(crop, template, mask, scales[0])
    if reduction >= 1.0:                    # pas de réduction : le relevé EST la lecture
        meilleur = (-1.0, (0, 0), (0, 0), scales[0])
        for carte, taille, scale in releve:
            _, score, _, location = cv2.minMaxLoc(carte)
            if score > meilleur[0]:
                meilleur = (float(score), location, taille, scale)
        return meilleur

    meilleur = (-1.0, (0, 0), (0, 0), scales[0])
    for carte, taille, scale in releve:
        for pic in _coarse_peaks(carte, taille, ATTACK_TOKEN_PEAKS):
            fenetre = _confirm_window(crop.shape, template, scale, pic, reduction)
            if fenetre is None:
                continue
            x0, y0, x1, y1 = fenetre
            score, location, dims, _ = _match_at_scale(
                crop[y0:y1, x0:x1], template, mask, scale
            )
            if score > meilleur[0]:
                meilleur = (score, (x0 + location[0], y0 + location[1]), dims, scale)
    return meilleur


def _coarse_peaks(carte: np.ndarray, taille: tuple, count: int) -> list:
    """
    Les `count` pics du relevé grossier, du meilleur au moins bon, en
    supprimant autour de chacun la largeur d'un template (un même pic
    déborde sur ses voisins et les trois meilleurs pixels d'une carte de
    scores sont presque toujours le MÊME pic).
    """
    t_w, t_h = taille
    travail = carte.copy()
    pics = []
    for _ in range(max(1, count)):
        _, score, _, (x, y) = cv2.minMaxLoc(travail)
        if score <= -1.0:
            break
        pics.append((x, y))
        travail[max(0, y - t_h):y + t_h, max(0, x - t_w):x + t_w] = -1.0
    return pics


def _confirm_window(shape: tuple, template, scale: float, pic: tuple,
                    reduction: float) -> Optional[tuple]:
    """
    Fenêtre pleine résolution (x0, y0, x1, y1) autour d'un pic du relevé
    grossier, assez large pour contenir le template plus la marge, et
    recadrée dans l'image. None si le template n'y tient pas.
    """
    hauteur, largeur = shape[:2]
    t_w = max(1, int(round(template.shape[1] * scale)))
    t_h = max(1, int(round(template.shape[0] * scale)))
    if t_w > largeur or t_h > hauteur:
        return None
    marge = ATTACK_TOKEN_CONFIRM_MARGIN
    x0 = int(round(pic[0] / reduction)) - marge
    y0 = int(round(pic[1] / reduction)) - marge
    x0 = min(max(0, x0), largeur - t_w)
    y0 = min(max(0, y0), hauteur - t_h)
    x1 = min(largeur, x0 + t_w + 2 * marge)
    y1 = min(hauteur, y0 + t_h + 2 * marge)
    return (x0, y0, x1, y1)


def _score_map(crop, template, mask, scale) -> tuple:
    """
    La carte des scores du template redimensionné à `scale` dans `crop` :
    (carte|None, (largeur, hauteur)). None si le template redimensionné
    déborde du crop.
    """
    if abs(scale - 1.0) < 1e-9:
        tpl, msk = template, mask
    else:
        size = (max(1, int(round(template.shape[1] * scale))),
                max(1, int(round(template.shape[0] * scale))))
        tpl = cv2.resize(template, size, interpolation=cv2.INTER_AREA)
        msk = None if mask is None else cv2.threshold(
            cv2.resize(mask, size, interpolation=cv2.INTER_AREA), 127, 255,
            cv2.THRESH_BINARY,
        )[1]
    t_h, t_w = tpl.shape[:2]
    if t_h > crop.shape[0] or t_w > crop.shape[1]:
        return (None, (t_w, t_h))
    if msk is not None:
        # Corrélation sur les seuls pixels de l'épée : le fond du template
        # n'entre pas dans le score. Sur une zone unie, la variante masquée
        # peut rendre NaN/inf — ramenés à 0 avant de chercher le max.
        result = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED, mask=msk)
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    else:
        result = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
    return (result, (t_w, t_h))


def _match_at_scale(crop, template, mask, scale) -> tuple:
    """
    Un matching du template redimensionné à `scale` dans `crop`. Rend
    (score, position, (largeur, hauteur), scale). Score -1 si le template
    redimensionné déborde du crop.
    """
    carte, taille = _score_map(crop, template, mask, scale)
    if carte is None:
        return (-1.0, (0, 0), taille, scale)
    _, score, _, location = cv2.minMaxLoc(carte)
    return (float(score), location, taille, scale)


# ============================================================
# STATS RÉELLES (OCR sur les badges des cartes)
# ============================================================
# card_sets donne les stats de BASE. Une unité 3/4 buffée à 5/6, ou
# blessée à 3/1, y figure toujours comme 3/4. Décider une attaque ou un
# blocage là-dessus produit des échanges perdants qu'on ne comprend pas
# en relisant les journaux.
#
# CE N'EST PAS FAIT À CHAQUE LECTURE D'ÉTAT, ET C'EST VOLONTAIRE.
# Un appel d'OCR par badge coûte cher : une dizaine d'unités en jeu font
# une vingtaine d'appels, soit plusieurs secondes. La boucle de combat
# interroge l'état en continu — payer ce prix à chaque tour de boucle la
# rendrait inutilisable. `enrich_with_live_stats()` est donc appelée
# explicitement, juste avant les décisions qui en dépendent (attaque,
# blocage), et nulle part ailleurs.

# Décalages des badges, calibrés sur une carte de banc de 126x159 px puis
# convertis en ratios pour suivre la taille réelle de la carte.
STAT_REFERENCE_CARD = (126, 159)
ATTACK_BADGE_BOX = (17, 8, 39, 26)     # (x, y, largeur, hauteur)
HEALTH_BADGE_BOX = (74, 8, 36, 26)

# Zones où les stats réelles changent quelque chose. Inutile de lire la
# main (les stats y sont celles de base, déjà connues) ni la main adverse.
LIVE_STAT_ZONES = ("board", "attack", "enemy_board", "enemy_attack")


def _badge_ratio(box: tuple, reference: tuple = STAT_REFERENCE_CARD) -> tuple:
    x, y, width, height = box
    ref_w, ref_h = reference
    return (x / ref_w, y / ref_h, width / ref_w, height / ref_h)


ATTACK_BADGE_REL = _badge_ratio(ATTACK_BADGE_BOX)
HEALTH_BADGE_REL = _badge_ratio(HEALTH_BADGE_BOX)


def _badge_crop(screen: np.ndarray, card: "BoardCard", relative: tuple):
    left, top, right, bottom = card.box
    width, height = right - left, bottom - top
    rx, ry, rw, rh = relative
    return lor_api.crop_box(
        screen,
        (
            left + rx * width,
            top + ry * height,
            left + (rx + rw) * width,
            top + (ry + rh) * height,
        ),
    )


# Cache des lectures de badge, indexé sur les PIXELS du badge lui-même.
#
# La clé est le contenu de l'image, pas la carte : si les pixels du badge
# sont identiques à une lecture précédente, le chiffre l'est forcément
# aussi. Le cache est donc toujours juste, sans expiration ni
# invalidation à gérer — contrairement à un cache par carte, qui servirait
# une valeur périmée dès qu'une unité prend des dégâts.
#
# En pratique la plupart des unités ne changent pas de stats entre deux
# décisions, et c'est là que l'économie se fait : l'OCR est de loin le
# poste le plus cher de la boucle.
_BADGE_CACHE: dict = {}
BADGE_CACHE_MAX = 512
# BORNES DE PLAUSIBILITÉ — UNE SEULE SOURCE PAR GRANDEUR.
# Il y en avait trois pour la même chose : `_MAX_FOR_TAG["stat"] = 30`,
# `detect_chiffres.STAT_MAX = 99`, et `COST_MAX = 12` contre
# `_MAX_FOR_TAG["cost"] = 15`. La lecture par forme était bornée à 30, le
# secours easyocr à 99 — et c'est 73 qui est sorti pour une unité 3/3
# (04/11/2026), jugée increvable et envoyée attaquer. Deux bornes pour une
# grandeur, c'est l'absence de borne : tout ce qui lit un badge passe
# désormais par celles-ci.
STAT_READ_MAX = 30     # attaque ou PV d'une unité, buffs compris
COST_MAX = 12          # le coût le plus élevé du jeu ; borne le bruit
_MAX_FOR_TAG = {"stat": STAT_READ_MAX, "cost": COST_MAX}


def _cached_ocr(crop, name, ocr_number, tag: str = "stat"):
    # `tag` sépare les familles de lecture dans le cache. Deux badges
    # différents peuvent avoir exactement les mêmes pixels (un crop noir,
    # un crop vide) alors qu'ils passent par des OCR différents — la gemme
    # de mana par `read_digits`, les stats par `ocr_number`. Sans le tag,
    # la première lecture servirait de réponse à l'autre famille.
    if crop is None or crop.size == 0:
        return None
    key = (tag, crop.shape, crop.tobytes())
    if key in _BADGE_CACHE:
        return _BADGE_CACHE[key]
    # LA FORME AVANT L'OCR. `digits.read_number` reconnaît la police du jeu
    # en une milliseconde ; quand il est SÛR, l'OCR (100-300 ms) n'est pas
    # appelé. Quand il doute, l'OCR tranche, et son candidat ne sert qu'en
    # dernier recours — jamais un chiffre douteux à la place d'un lu.
    limite = _MAX_FOR_TAG.get(tag, 99)
    value = digits.read_number(crop, maximum=limite)
    if value is None:
        # LA BORNE EST IMPOSÉE ICI, pas déléguée : `ocr_number` a sa propre
        # borne par défaut (STAT_MAX = 99, la bonne pour les PV du nexus) et
        # rendait donc 73 pour une stat. On la lui passe, ET on revérifie —
        # une valeur hors borne vaut un échec de lecture, pas une décision.
        value = ocr_number(crop, name=name, maximum=limite)
        if value is not None and value > limite:
            LOGGER.warning("Lecture %s invraisemblable (%s > %s) : ignorée.",
                           name, value, limite)
            value = None
        if value is None:
            value = digits.read_number(crop, maximum=limite, loose=True)
    if len(_BADGE_CACHE) >= BADGE_CACHE_MAX:
        _BADGE_CACHE.clear()
    _BADGE_CACHE[key] = value
    return value


def badge_cache_info() -> tuple:
    """(entrées en cache, taille maximale) — pour le diagnostic."""
    return len(_BADGE_CACHE), BADGE_CACHE_MAX


# La barre d'icônes n'existe que sur les unités DU PLATEAU : la main n'en
# a pas, et une carte au centre pendant une désignation est lue dans les
# bandes d'attaque (les deux horloges).
#
# CE SONT LES CLÉS DE `ZONE_ORDER` / `group_by_zone` (déjà utilisées en dur
# plus bas : `zones["attack"]`, `zones["enemy_attack"]`) — PAS les alias de
# propriété `GameSnapshot.attack_row` / `.enemy_attack_row`, qui n'existent
# pas comme clés de ce dict : ne pas « corriger » vers `attack_row`.
ZONES_DE_PLATEAU = ("board", "attack", "enemy_board", "enemy_attack")


def lire_les_mots_cles(screen, zones: dict) -> int:
    """
    Pose `keywords_lus` sur les unités du plateau, au vu de l'écran.

    Appelée une seule fois par instantané, là où la capture est DÉJÀ
    payée — et seulement en partie en cours hors mulligan, c'est-à-dire
    là où une unité de plateau existe.

    Ne lève jamais : une lecture impossible laisse le tuple vide, et vide
    veut dire « on n'a pas regardé ».

    COÛT MESURÉ (20/11/2026), sur `captures_reference/mots_cles/
    scene_20261120_201157.png`, 5 centres d'unité, commande :
        python -c "import time,cv2,mots_cles_ecran as m; img=cv2.imread(...);
        pts=[...]; t=time.perf_counter(); [m.identifier(img,p) for p in pts]"

    AVANT correctif (`mots_cles_ecran.identifier` segmentait trois fois la
    même bande par glyphe — voir `_icones_et_masque`) : 5 exécutions
    fraîches 57.1-62.8 ms (moyenne 59.7 ms) ; dans un même processus,
    gabarits déjà en cache (2e/3e appel, le régime réel pendant un
    combat) : 49.8-50.9 ms.

    APRÈS correctif (segmentation calculée UNE fois par unité) : 5
    exécutions fraîches 50.7-52.5 ms (moyenne 51.5 ms) ; gabarits en
    cache : 43.1-43.6 ms.

    **RESTE marginalement au-dessus du budget de 50 ms fixé pour cette
    tâche, à froid seulement** (à chaud — le régime réel — c'est sous la
    barre). Décision du contrôleur (20/11/2026) : commiter quand même,
    avec l'ÉTALON qui manquait au seuil de 50 ms. L'instantané du bot
    coûte déjà ~2200 ms par itération, dont ~900 ms pour la seule
    recherche multi-échelle du jeton d'attaque : cette lecture y pèse
    **2,3 % à froid (51,5/2200), 2,0 % à chaud (43,4/2200)**, contre
    2,7 % avant correctif. Le seuil de 50 ms visait à attraper une
    surprise d'un ORDRE DE GRANDEUR (500 ms), pas à bloquer à 51-57 ms.
    """
    if screen is None:
        return 0
    enrichies = 0
    for nom in ZONES_DE_PLATEAU:
        for carte in zones.get(nom, ()) or ():
            try:
                lus = mots_cles_ecran.identifier(screen, carte.center)
            except Exception as exc:   # une lecture ratée n'arrête pas un combat
                LOGGER.warning(
                    "Lecture des mots-clés de %s impossible (%s) : carte ignorée.",
                    carte.code, exc,
                )
                continue
            if lus:
                carte.keywords_lus = lus
                enrichies += 1
    return enrichies


def enrich_with_live_stats(
    snapshot: "GameSnapshot",
    screen: Optional[np.ndarray] = None,
    zones: tuple = LIVE_STAT_ZONES,
) -> "GameSnapshot":
    """
    Remplit `attack_read` / `health_read` des unités en jeu par OCR.

    `zones` restreint le travail à ce dont la décision a besoin : lire les
    quatre zones avant une attaque, alors que seul notre banc compte, coûte
    le double pour rien.

    Modifie l'instantané sur place et le renvoie. Une lecture qui échoue
    laisse la valeur à None, et la carte retombe alors sur sa stat de
    base : dégradation silencieuse plutôt qu'exception, parce qu'un badge
    illisible ne doit pas interrompre un combat.
    """
    try:
        from detect_chiffres import ocr_number
    except Exception as exc:
        LOGGER.warning(
            "OCR des stats indisponible (%s) : on reste sur les stats de base.", exc
        )
        return snapshot

    if screen is None:
        screen = lor_api.capture_screen_bgr()

    for zone in zones:
        for card in snapshot.zones.get(zone, ()):
            if not card.is_unit:
                continue
            card.attack_read = _cached_ocr(
                _badge_crop(screen, card, ATTACK_BADGE_REL), f"{card.code}_atk", ocr_number
            )
            card.health_read = _cached_ocr(
                _badge_crop(screen, card, HEALTH_BADGE_REL), f"{card.code}_hp", ocr_number
            )

    return snapshot


# ============================================================
# COÛT EN MANA LU À L'ÉCRAN
# ============================================================
# card_sets donne le coût IMPRIMÉ sur la carte. Ce n'est pas celui qu'on
# paie. Une réduction (« coûte 2 de moins ce tour-ci »), une majoration
# adverse, un effet de terrain : le chiffre affiché dans la gemme change,
# le cardCode non. Décider avec le coût de base, c'est passer son tour
# sans jouer une carte pourtant gratuite, ou tenter une pose qu'on ne peut
# pas payer et la mettre de côté pour rien.
#
# C'est exactement le raisonnement déjà appliqué aux stats (attaque / PV) :
# la valeur AFFICHÉE prime sur la valeur imprimée, et la valeur imprimée
# ne sert que de repli quand l'écran est illisible.
#
# CE QUE ÇA NE RÈGLE PAS : la carte ABSENTE de card_sets. On espérait que
# lire sa gemme la rendrait jouable — c'est faux. Le jeu ne nous donne que
# son cardCode : sans la base, on ignore aussi son TYPE, et
# `playable_cards` la refuse là-dessus, coût lu ou non. La seule réponse à
# une base en retard reste `download_card_sets.py`.
#
# La position de la gemme n'est pas devinée :
#
#     python actions.py cost --calibrate
#
# fait encadrer la gemme sur une carte en main, et l'enregistre en
# fractions du rectangle de la carte — donc valable pour toutes les
# cartes et toutes les résolutions.
#
# COMME POUR LES STATS, CE N'EST PAS FAIT À CHAQUE LECTURE D'ÉTAT.
# `enrich_with_live_costs()` est appelée juste avant de choisir une carte
# à poser, et nulle part ailleurs : la boucle de combat interroge l'état
# en continu, y glisser un OCR par carte de main la rendrait poussive.

COST_CALIBRATION_KEY = "cost_badge"

# Où le coût affiché change quelque chose : la main, puisque c'est de là
# qu'on joue. Le coût d'une unité déjà posée ne se paie plus.
LIVE_COST_ZONES = ("hand",)


def load_cost_offsets():
    """Offsets calibrés de la gemme de mana, ou None."""
    try:
        import json
        with open(lor_api.PROJECT_ROOT / "calibration.json", encoding="utf8") as handle:
            value = json.load(handle).get(COST_CALIBRATION_KEY)
    except (OSError, ValueError):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(value)
    return None


def read_costs(
    snapshot: "GameSnapshot",
    screen: Optional[np.ndarray] = None,
    zones: tuple = LIVE_COST_ZONES,
    only_unknown: bool = False,
    cards: Optional[list] = None,
) -> int:
    """
    Lit le coût en mana affiché sur les cartes, et renseigne `cost_read`.

    `only_unknown=False` par défaut : on lit TOUTES les cartes de la zone,
    y compris celles que card_sets connaît, parce que c'est justement là
    que se cachent les réductions et les majorations. Passer True limite la
    lecture aux cartes absentes de la base — c'est un repli, pas la règle.

    `cards` restreint la lecture à une liste explicite et ignore `zones` :
    l'appelant sait souvent qu'une carte sera refusée sur son type, et
    chaque lecture coûte six passes d'OCR.

    Une lecture qui échoue laisse `cost_read` à None, et la carte retombe
    sur son coût de base : dégradation silencieuse, jamais d'exception.

    Renvoie le nombre de coûts effectivement lus.
    """
    offsets = load_cost_offsets()
    if not offsets:
        LOGGER.info(
            "Gemme de mana non calibrée : le bot décide sur les coûts de base. "
            "Lance `python actions.py cost --calibrate`."
        )
        return 0

    try:
        from mana import read_digits
    except Exception as exc:
        LOGGER.warning(
            "Lecture des coûts indisponible (%s) : on reste sur les coûts de base.", exc
        )
        return 0

    def _ocr_cost(crop, name="", debug=False, maximum=COST_MAX):
        # `ocr_number` (detect_chiffres) exige du rouge ou du vert : c'est
        # fait pour les badges de stats et rejetterait systématiquement la
        # gemme de mana, qui est bleue. On passe donc par `read_digits`,
        # qui vote entre plusieurs binarisations sans test de couleur.
        return read_digits(crop, maximum)

    if screen is None:
        screen = lor_api.capture_screen_bgr()

    if cards is None:
        cards = [card for zone in zones for card in snapshot.zones.get(zone, ())]

    read = 0
    for card in cards:
        if only_unknown and card.known:
            continue
        try:
            value = _cached_ocr(
                _badge_crop(screen, card, offsets),
                f"{card.code}_cost",
                _ocr_cost,
                tag="cost",
            )
        except Exception as exc:
            # `read_digits` n'instancie easyocr qu'au premier appel : un
            # moteur absent ou un GPU indisponible ne se voit donc PAS à
            # l'import, mais ici, en plein combat. On retombe sur les
            # coûts de base plutôt que d'interrompre la partie.
            LOGGER.warning(
                "Lecture du coût impossible (%s) : coûts de base conservés.", exc
            )
            return read
        if value is not None:
            card.cost_read = value
            read += 1
    return read


def enrich_with_live_costs(
    snapshot: "GameSnapshot",
    screen: Optional[np.ndarray] = None,
    zones: tuple = LIVE_COST_ZONES,
    cards: Optional[list] = None,
) -> "GameSnapshot":
    """
    Remplit `cost_read` des cartes de la main par OCR de la gemme de mana.

    Pendant symétrique de `enrich_with_live_stats` : même contrat, même
    dégradation, même règle de priorité (l'écran prime sur card_sets).
    Modifie l'instantané sur place et le renvoie, pour être remplaçable
    par un bouchon d'un seul tenant dans les tests.
    """
    read_costs(snapshot, screen=screen, zones=zones, only_unknown=False, cards=cards)
    return snapshot


def cost_gaps(snapshot: "GameSnapshot", zones: tuple = LIVE_COST_ZONES) -> list:
    """
    Cartes dont le coût affiché diffère du coût imprimé : [(carte, écart)].

    Sert au journal. Un écart, c'est soit un vrai effet de jeu, soit une
    gemme mal calibrée — dans les deux cas on veut le voir écrit avant de
    comprendre une décision surprenante.
    """
    found = []
    for zone in zones:
        for card in snapshot.zones.get(zone, ()):
            gap = card.cost_gap
            if gap:
                found.append((card, gap))
    return found


# Sous-ensembles de zones utiles selon la décision à prendre.
OUR_UNITS_ZONES = ("board", "attack")
COMBAT_ZONES = ("board", "attack", "enemy_attack")


# ============================================================
# INSTANTANÉ DE PARTIE
# ============================================================

@dataclass
class GameSnapshot:
    """Photographie complète et cohérente de l'état de la partie."""

    phase: Phase
    window: Window
    zones: dict = field(default_factory=empty_zones)
    turn_orb_active: Optional[bool] = None
    # Libellé lu sur le bouton de tour (« resoudre », « cible » = le jeu
    # attend que NOUS désignions une cible…), None si inconnu.
    button_label: Optional[str] = None
    attack_token: Optional[bool] = None
    token_match: Optional["TokenMatch"] = None
    our_nexus: Optional[tuple] = None
    enemy_nexus: Optional[tuple] = None
    our_nexus_box: Optional[tuple] = None
    enemy_nexus_box: Optional[tuple] = None
    api_state: str = ""
    game_id: Optional[int] = None
    last_game_won: Optional[bool] = None
    unknown_codes: tuple = ()
    # Notre deck de départ ({code: exemplaires}), lu sur /static-decklist
    # une fois par partie ; {} tant qu'il n'est pas connu.
    deck: dict = field(default_factory=dict)
    # Heure de la lecture. Les POSITIONS d'un instantané périment vite : la
    # main se recentre à chaque pioche, et une lecture vieille d'une
    # seconde (le temps d'un OCR des coûts) ne sert plus à viser
    # (cf. actions.fresh_hand_card, 05/09/2026).
    taken_at: float = field(default_factory=time.time)

    # --- accès aux zones ----------------------------------------------
    @property
    def hand(self) -> tuple:
        return self.zones.get("hand", ())

    @property
    def board(self) -> tuple:
        return self.zones.get("board", ())

    @property
    def attack_row(self) -> tuple:
        return self.zones.get("attack", ())

    @property
    def stack(self) -> tuple:
        return self.zones.get("stack", ())

    @property
    def enemy_attack_row(self) -> tuple:
        return self.zones.get("enemy_attack", ())

    @property
    def stack_ours(self) -> tuple:
        """Nos cartes sur la pile."""
        return tuple(c for c in self.stack if c.local)

    @property
    def stack_theirs(self) -> tuple:
        """Les cartes ADVERSES sur la pile : il a joué, ou il a répondu."""
        return tuple(c for c in self.stack if not c.local)

    @property
    def spells_on_stack(self) -> tuple:
        """Les cartes de la pile dont on SAIT qu'elles sont des sorts."""
        return tuple(c for c in self.stack if c.is_spell or c.is_ability)

    @property
    def enemy_board(self) -> tuple:
        return self.zones.get("enemy_board", ())

    @property
    def enemy_hand(self) -> tuple:
        return self.zones.get("enemy_hand", ())

    def cards(self, *zones: str) -> tuple:
        """Toutes les cartes des zones demandées (toutes zones si aucune)."""
        wanted = zones or ZONE_ORDER
        return tuple(card for name in wanted for card in self.zones.get(name, ()))

    # --- deck ----------------------------------------------------------
    def is_generated(self, card) -> bool:
        """
        Cette carte À NOUS ne vient pas du deck : créée par un effet
        (Manifest, Invoke, pièce de champion…). Faux si le deck est inconnu —
        on n'affirme rien sans donnée.
        """
        return bool(self.deck) and card.local and card.code not in self.deck

    def deck_remaining(self) -> dict:
        """
        Estimation de ce qu'il reste À PIOCHER : le deck de départ moins
        nos cartes visibles (main, banc, rangée). Les cartes déjà jouées et
        parties au cimetière ne sont pas visibles, donc pas retranchées :
        c'est une borne HAUTE, à lire comme telle.
        """
        if not self.deck:
            return {}
        remaining = dict(self.deck)
        for card in self.cards("hand", "board", "attack"):
            if card.local and card.code in remaining:
                remaining[card.code] = max(0, remaining[card.code] - 1)
        return {code: n for code, n in remaining.items() if n > 0}

    # --- affichage ----------------------------------------------------
    def summary(self) -> str:
        def flag(value):
            return "?" if value is None else ("oui" if value else "non")

        # Le score du match est affiché en permanence : c'est lui qui dit
        # s'il faut bouger le seuil, et il est inutile une fois la partie
        # finie.
        token = f"jeton={flag(self.attack_token)}"
        if self.token_match is not None:
            if self.token_match.template_missing:
                token = "jeton=template_absent"
            else:
                token += (
                    f" (score {self.token_match.score:.2f}"
                    f" x{self.token_match.scale:.2f}"
                    f" cote {self.token_match.side})"
                )

        button = f" bouton={self.button_label}" if self.button_label else ""
        lines = [
            f"[{self.phase.name}] api={self.api_state or '-'} "
            f"orbe={flag(self.turn_orb_active)}{button} {token}"
        ]
        if self.deck:
            left = sum(self.deck_remaining().values())
            lines.append(f"  deck : {sum(self.deck.values())} cartes, ≤ {left} à piocher")
        for name in ZONE_ORDER:
            cards = self.zones.get(name, ())
            if cards:
                lines.append(f"    {name:<13} " + " | ".join(str(c) for c in cards))
        if self.unknown_codes:
            lines.append(f"    codes absents de card_sets : {', '.join(self.unknown_codes)}")
        return "\n".join(lines)


def load_zone_reference():
    """Référence de géométrie enregistrée, ou None."""
    try:
        import json
        with open(lor_api.PROJECT_ROOT / "calibration.json", encoding="utf8") as handle:
            value = json.load(handle).get(ZONE_CALIBRATION_KEY)
    except (OSError, ValueError):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return tuple(value)
    return None


def snapshot_signature(snapshot: "GameSnapshot") -> tuple:
    """
    Empreinte de l'état visible.

    Sert à deux choses : détecter qu'une action a produit un effet, et
    détecter que la boucle tourne en rond. On y met le CONTENU de chaque
    zone et pas seulement les tailles — une carte qui change de zone à
    effectif constant est un vrai progrès.
    """
    return (
        snapshot.phase,
        tuple(sorted(c.code for c in snapshot.hand)),
        tuple(sorted(c.code for c in snapshot.board)),
        tuple(sorted(c.code for c in snapshot.attack_row)),
        tuple(sorted(c.code for c in snapshot.stack)),
        tuple(sorted(c.code for c in snapshot.enemy_attack_row)),
        tuple(sorted(c.code for c in snapshot.enemy_board)),
    )


# ============================================================
# GÉOMÉTRIE — « les cartes ont-elles fini de bouger ? »
# ============================================================
# `snapshot_signature` répond à « le CONTENU des zones a-t-il changé ? ».
# Ce n'est pas la même question que « où sont les cartes MAINTENANT ? », et
# confondre les deux est la cause d'un bug tenace : quand une unité est
# engagée, l'API la fait passer du banc à la rangée d'attaque DÈS LE DÉPÔT,
# alors que le banc, lui, met le temps d'une animation à se recentrer.
# Agir sur la première lecture qui « a changé », c'est donc viser des
# coordonnées en cours de vol — et saisir la voisine, ou le vide.

# Zones dont la position compte avant un geste. Toutes se recentrent : la
# main et le banc quand une carte les quitte, les rangées de combat quand
# une unité s'y engage.
GEOMETRY_ZONES = ("hand", "board", "attack", "enemy_attack", "enemy_board")

# Tolérance en pixels entre deux lectures d'une carte IMMOBILE. Zéro serait
# trop strict : les rectangles renvoyés par l'API sont arrondis et oscillent
# d'un pixel sans que rien ne bouge à l'écran.
GEOMETRY_TOLERANCE = 3


def zone_geometry(snapshot: "GameSnapshot", zones: tuple = GEOMETRY_ZONES) -> dict:
    """
    Empreinte des POSITIONS : {clé de carte -> boîte} pour `zones`.

    La clé est le CardID quand l'API le donne (stable pour une instance,
    donc suivre une carte qui glisse est exact). À défaut, on retombe sur
    (zone, code, rang) : deux exemplaires d'une même carte ne sont alors
    distingués que par leur rang, ce qui suffit pour savoir si la rangée
    bouge encore.
    """
    geometry = {}
    for zone in zones:
        for rank, card in enumerate(snapshot.zones.get(zone, ())):
            key = (zone, card.card_id) if card.card_id >= 0 else (zone, card.code, rank)
            geometry[key] = tuple(card.box)
    return geometry


def geometry_is_stable(
    before: dict, after: dict, tolerance: int = GEOMETRY_TOLERANCE
) -> bool:
    """
    Mêmes cartes, aux mêmes places à `tolerance` pixels près ?

    Un changement d'effectif compte comme un mouvement : une carte qui
    apparaît ou disparaît annonce une animation qui commence.
    """
    if before.keys() != after.keys():
        return False
    return all(
        max(abs(a - b) for a, b in zip(before[key], after[key])) <= tolerance
        for key in before
    )


# ============================================================
# LECTEUR D'ÉTAT
# ============================================================

class GameStateReader:
    """
    Produit des `GameSnapshot`. À instancier UNE fois et à réutiliser :
    l'objet garde en mémoire le dernier GameID vu, ce qui est nécessaire
    pour détecter une fin de partie.
    """

    def __init__(
        self,
        card_db: Optional[dict] = None,
        token_threshold: float = ATTACK_TOKEN_MATCH_THRESHOLD,
        token_template=ATTACK_TOKEN_TEMPLATE,
    ):
        self.card_db = card_db if card_db is not None else lor_api.load_card_db()
        self.zone_reference = load_zone_reference()
        self.token_threshold = token_threshold
        self.token_template = token_template
        self._warned_template = False
        self._last_game_id: Optional[int] = None
        self._last_game_won: Optional[bool] = None
        self._warned_codes: set = set()
        # Deck de la partie en cours, relu quand l'API repasse InProgress.
        self._deck: dict = {}
        self._deck_state: str = ""

    # --- construction des cartes --------------------------------------
    def bands_for(self, rectangles: list, window: Window) -> tuple:
        """
        Bandes de zones adaptées à la géométrie courante.

        Sans référence calibrée, ce sont les bandes d'origine : on ne
        rééchelonne pas à partir d'un repère qu'on n'a pas mesuré.
        """
        if not self.zone_reference:
            return ZONE_BANDS
        current = nexus_span(rectangles, window)
        if current is None:
            return ZONE_BANDS
        return rescale_bands(ZONE_BANDS, tuple(self.zone_reference), current)

    def _build_cards(self, rectangles: list, window: Window, bands: tuple = ZONE_BANDS) -> tuple:
        cards, unknown = [], []

        for rect in rectangles:
            code = rect.get("CardCode")
            if not code or code == lor_api.NEXUS_CARD_CODE:
                continue

            info = self.card_db.get(code)
            known = info is not None
            if not known:
                info = {}
                unknown.append(code)
                if code not in self._warned_codes:
                    self._warned_codes.add(code)
                    LOGGER.warning(
                        "Carte %s absente de card_sets : conservée avec des "
                        "stats à 0 plutôt qu'ignorée, pour ne pas raisonner "
                        "sur un plateau incomplet.", code
                    )

            zone = classify_zone(rect, window, bands)
            cards.append(
                BoardCard(
                    card_id=rect.get("CardID", -1),
                    code=code,
                    name=info.get("name") or code,
                    base_cost=info.get("cost") or 0,
                    base_attack=info.get("attack") or 0,
                    base_health=info.get("health") or 0,
                    type=info.get("type") or "",
                    keywords=tuple(info.get("keywords") or ()),
                    keyword_refs=tuple(info.get("keywordRefs") or ()),
                    description=info.get("descriptionRaw") or "",
                    spell_speed=info.get("spellSpeedRef") or info.get("spellSpeed") or "",
                    local=bool(rect.get("LocalPlayer")),
                    zone=zone,
                    ratio=zone_ratio(rect, window),
                    box=lor_api.rect_to_screen_box(rect, window),
                    center=lor_api.rect_center_screen(rect, window),
                    known=known,
                    supertype=info.get("supertype") or "",
                    collectible=bool(info.get("collectible", True)),
                )
            )

        return cards, tuple(dict.fromkeys(unknown))

    # --- fin de partie -------------------------------------------------
    def _poll_game_result(self) -> tuple:
        """
        Renvoie (game_id, partie_vient_de_finir).

        `/game-result` décrit la dernière partie TERMINÉE : son GameID
        n'augmente qu'au moment où une partie se conclut. La toute
        première lecture ne déclenche donc rien — sinon le bot croirait
        qu'une partie vient de finir à chaque démarrage.
        """
        try:
            result = lor_api.get_game_result()
        except ApiUnavailable:
            return self._last_game_id, False

        if not result or result.get("GameID") is None:
            return self._last_game_id, False

        game_id = int(result["GameID"])
        won = bool(result.get("LocalPlayerWon"))

        if self._last_game_id is None:
            self._last_game_id = game_id
            self._last_game_won = won
            return game_id, False

        if game_id > self._last_game_id:
            self._last_game_id = game_id
            self._last_game_won = won
            return game_id, True

        return game_id, False

    def _deck_for_game(self, api_state: str) -> dict:
        """
        Le deck de la partie en cours, lu UNE fois à l'entrée en partie.

        /static-decklist ne coûte rien mais ne change pas pendant la
        partie : on le relit seulement quand on vient des menus (nouvelle
        partie), et on garde le dernier connu si l'appel échoue.
        """
        if self._deck and self._deck_state == api_state:
            return self._deck
        try:
            data = lor_api.get_static_decklist()
        except ApiUnavailable:
            return self._deck
        cards = (data or {}).get("CardsInDeck") or {}
        if cards:
            self._deck = {str(code): int(n) for code, n in cards.items()}
            self._deck_state = api_state
            LOGGER.info("Deck lu : %d cartes, %d distinctes.",
                        sum(self._deck.values()), len(self._deck))
        return self._deck

    def final_result(self, timeout: float = 8.0, poll: float = 0.5) -> Optional[bool]:
        """
        Le verdict de la partie qui vient de finir, ou None.

        `/game-result` ne bascule pas à l'instant où le client repasse aux
        menus : le journal du 03/09/2026 montrait 47 combats sans un seul
        `gagne` renseigné, tous sortis sur « retour aux menus ». On lui
        laisse donc quelques secondes — un GameID qui augmente est la
        seule preuve qu'une partie s'est conclue, et de qui l'a gagnée.
        """
        deadline = time.time() + timeout
        while True:
            _, just_finished = self._poll_game_result()
            if just_finished:
                return self._last_game_won
            if time.time() >= deadline:
                return None
            time.sleep(poll)

    # --- mulligan ------------------------------------------------------
    @staticmethod
    def _looks_like_mulligan(cards: list) -> bool:
        local = [c for c in cards if c.local]
        if len(local) < MULLIGAN_MIN_CARDS:
            return False

        # Toutes nos cartes à la même hauteur, au milieu de l'écran.
        ratios = [c.ratio for c in local]
        if max(ratios) - min(ratios) > MULLIGAN_MAX_SPREAD:
            return False

        middle = sum(ratios) / len(ratios)
        if not MULLIGAN_BAND[0] <= middle <= MULLIGAN_BAND[1]:
            return False

        # ATTENTION : les cartes de mulligan tombent elles-mêmes dans la
        # bande `enemy_attack` (elles sont au centre de l'écran). Le test
        # de plateau vide doit donc porter sur NOS zones pour nos cartes
        # et sur les zones adverses pour les leurs — sinon la condition
        # s'auto-invalide et le mulligan n'est jamais reconnu.
        if any(c.local and c.zone in ("board", "attack") for c in cards):
            return False
        if any(not c.local and c.zone in ("enemy_board", "enemy_attack") for c in cards):
            return False

        return True

    # --- instantané ----------------------------------------------------
    def snapshot(self) -> GameSnapshot:
        """Lit l'API, capture l'écran si nécessaire, et déduit la phase."""
        try:
            api_data = lor_api.get_positional_rectangles()
        except ApiUnavailable as exc:
            LOGGER.debug("API indisponible : %s", exc)
            return GameSnapshot(phase=Phase.NO_API, window=lor_api.get_window())

        window = lor_api.get_window(api_data)
        api_state = api_data.get("GameState") or ""
        rectangles = api_data.get("Rectangles") or []

        cards, unknown = self._build_cards(rectangles, window, self.bands_for(rectangles, window))

        # La réconciliation par camp n'a de sens qu'en jeu. Pendant le
        # mulligan, les cartes proposées sont alignées au milieu de
        # l'écran, donc en plein dans les bandes de combat : les ranger
        # comme des attaquantes ferait échouer la reconnaissance du
        # mulligan, qui exige justement un plateau vide.
        mulligan = self._looks_like_mulligan(cards)
        if not mulligan:
            cards = reconcile_combat_rows(cards)
        zones = group_by_zone(cards)
        game_id, just_finished = self._poll_game_result()
        our_nexus, enemy_nexus = nexus_points(rectangles, window)
        our_box, enemy_box = nexus_boxes(rectangles, window)

        base = dict(
            window=window,
            zones=zones,
            our_nexus=our_nexus,
            enemy_nexus=enemy_nexus,
            our_nexus_box=our_box,
            enemy_nexus_box=enemy_box,
            api_state=api_state,
            game_id=game_id,
            last_game_won=self._last_game_won,
            unknown_codes=unknown,
        )

        # La fin de partie prime sur tout le reste : c'est un événement,
        # et il n'est émis qu'une seule fois par partie.
        if just_finished:
            return GameSnapshot(phase=Phase.GAME_OVER, **base)

        if api_state != "InProgress":
            self._deck_state = api_state
            return GameSnapshot(phase=Phase.MENUS, **base)

        base["deck"] = self._deck_for_game(api_state)

        # Le mulligan se reconnaît sans vision : l'orbe peut être grise
        # pendant cet écran, donc le test doit venir AVANT.
        if mulligan:
            return GameSnapshot(phase=Phase.MULLIGAN, **base)

        screen = lor_api.capture_screen_bgr()
        lire_les_mots_cles(screen, zones)
        orb_active = turn_orb_is_active(screen, window)
        base["turn_orb_active"] = orb_active
        button_label, _ = read_turn_button(screen, window)
        base["button_label"] = button_label

        # Le jeton est évalué dans TOUTES les phases de partie, et pas
        # seulement là où il départage ATTACK_TURN et DEFEND_TURN.
        #
        # Rappel de règle : le jeton signifie « ce round est mon round
        # d'attaque », pas « je suis en train d'attaquer ». Il alterne à
        # chaque round quoi qu'on fasse. Le savoir pendant le tour adverse
        # ou pendant un blocage reste utile, et ça évite un « jeton=? »
        # permanent dans `monitor` — c'est-à-dire une information
        # manquante exactement là où on veut la vérifier.
        match = find_attack_token(
            screen,
            window,
            midline_y=nexus_midline_y(rectangles, window),
            threshold=self.token_threshold,
            template_path=self.token_template,
        )
        base["token_match"] = match
        base["attack_token"] = None if match.template_missing else bool(
            match.found and match.ours is not False
        )

        if match.template_missing and not self._warned_template:
            self._warned_template = True
            LOGGER.warning(
                "Template du jeton absent (%s) : la phase reste OUR_TURN au "
                "lieu de trancher ATTACK/DEFEND. Génère-le avec "
                "`python game_state.py snap avec` puis `cut-token`.",
                self.token_template,
            )

        # UNE ATTAQUE DÉCLARÉE SE LIT AVANT L'ORBE, ET C'EST DÉLIBÉRÉ.
        #
        # L'orbe répond à « puis-je cliquer maintenant ? », pas à « que se
        # passe-t-il ? ». Elle est grise pendant toute l'animation de la
        # charge adverse, et l'ordre inverse faisait donc lire
        # OPPONENT_TURN — une phase d'attente — au moment précis où il
        # fallait bloquer. La boucle attendait, l'orbe redevenait bleue,
        # et il ne restait plus qu'un tour ordinaire à jouer : le bot
        # annonçait « pas d'attaque ce tour » et passait, attaque encaissée.
        #
        # Des unités avancées sont un FAIT, pas une opinion sur le timing.
        # On les lit d'abord ; c'est `execute_blocks` qui attend ensuite
        # d'avoir la main pour agir.
        # UN SORT SUR LA PILE SE LIT AVANT TOUT LE RESTE, ORBE COMPRISE.
        #
        # Signalé par Ewan le 03/09/2026 : le bot ne voyait ni les sorts
        # adverses, ni la réponse adverse à nos sorts, et « jouait comme si
        # rien ». La pile n'était lue qu'après l'orbe : orbe grise (c'est
        # à lui de décider) → OPPONENT_TURN, et un sort tombé dans une
        # autre bande que « stack » passait pour une attaque.
        #
        # Une pile qui contient un SORT CONNU est une fenêtre de réponse,
        # quel que soit l'état des rangées : les compétences « Attaque : »
        # et les sorts joués pendant le combat s'empilent PENDANT que les
        # unités sont avancées, et le jeu attend un « OK » avant de
        # continuer. L'orbe dit alors seulement à qui c'est de parler
        # (`turn_orb_active`), et c'est la boucle de combat qui en tire
        # « on répond » ou « on attend ».
        #
        # Seuls les sorts CONNUS déclenchent cette lecture : une carte de
        # type inconnu dans la bande « stack » garde l'ancien traitement,
        # plus bas — sans base de cartes, tout est inconnu, et lire « sort »
        # partout empêcherait de bloquer.
        if any(c.is_spell or c.is_ability for c in zones["stack"]):
            return GameSnapshot(phase=Phase.SPELL_STACK, **base)
        # Le bouton dit « RÉSOUDRE » : le jeu attend une réponse, que l'API
        # ait rapporté le sort ou non. Témoin indépendant de la pile.
        if button_label == "resoudre" and orb_active:
            return GameSnapshot(phase=Phase.SPELL_STACK, **base)

        if zones["attack"] and zones["enemy_attack"]:
            # LES DEUX RANGÉES SONT AVANCÉES : DEUX SITUATIONS OPPOSÉES.
            #
            # Soit nous attaquons et ce sont ses bloqueurs qu'on voit en
            # face. Soit c'est LUI qui attaque, et un Challenger (ou un
            # Vulnerable) a TIRÉ une de nos unités devant lui : elle
            # traverse la ligne, la bande « attack » se remplit, et « notre
            # rangée est occupée » ne veut plus dire « c'est nous qui
            # attaquons ».
            #
            # Observé le 20/08/2026 : l'adversaire attire Mel avec
            # Challenger, le bot lit ATTACKING, attend une résolution qui
            # ne vient pas, et le jeu attend nos bloqueurs. Face-à-face
            # jusqu'à la durée maximale.
            #
            # Le jeton tranche, parce que c'est exactement la question
            # qu'il pose : à qui appartient CE round d'attaque. On ne s'en
            # sert que quand il est POSITIVEMENT vu du côté adverse — une
            # détection manquée ne doit pas nous faire croire à une
            # attaque adverse imaginaire.
            if match.found and match.ours is False:
                return GameSnapshot(phase=Phase.BLOCKING, **base)
            return GameSnapshot(phase=Phase.ATTACKING, **base)

        if zones["attack"]:
            # Notre rangée seule occupée => c'est NOUS qui attaquons, et
            # il n'a pas encore bloqué.
            return GameSnapshot(phase=Phase.ATTACKING, **base)

        if zones["enemy_attack"]:
            return GameSnapshot(phase=Phase.BLOCKING, **base)

        if not orb_active:
            return GameSnapshot(phase=Phase.OPPONENT_TURN, **base)

        if zones["stack"]:
            return GameSnapshot(phase=Phase.SPELL_STACK, **base)

        # Sans template, on ne PEUT pas trancher : renvoyer DEFEND_TURN
        # serait une affirmation fausse déguisée en information. OUR_TURN
        # dit honnêtement « à toi de jouer, jeton inconnu ».
        if match.template_missing:
            return GameSnapshot(phase=Phase.OUR_TURN, **base)

        return GameSnapshot(
            phase=Phase.ATTACK_TURN if base["attack_token"] else Phase.DEFEND_TURN,
            **base,
        )

    # --- lectures stabilisées -----------------------------------------
    def stable_snapshot(
        self, confirmations: int = 2, poll: float = 0.6, timeout: float = 12.0
    ) -> GameSnapshot:
        """
        Attend que la même phase soit lue `confirmations` fois de suite
        avant de la renvoyer.

        Indispensable avant toute action : les animations (pioche, pose
        de carte, résolution de combat) déplacent les cartes entre les
        bandes pendant une seconde ou deux, et une lecture isolée pendant
        ce laps de temps donne une phase fausse. Au bout de `timeout`, on
        renvoie la dernière lecture telle quelle plutôt que de bloquer.
        """
        deadline = time.time() + timeout
        streak, snap = 0, self.snapshot()
        previous = snap.phase

        while True:
            streak = streak + 1 if snap.phase is previous else 1
            if streak >= max(1, confirmations):
                return snap
            if time.time() >= deadline:
                LOGGER.debug("Phase instable après %.1fs, on renvoie %s", timeout, snap.phase.name)
                return snap
            previous = snap.phase
            time.sleep(poll)
            snap = self.snapshot()

# ============================================================
# CLI — surveillance et calibration
# ============================================================

def cmd_monitor(interval: float, trace_path: Optional[str] = None) -> None:
    """
    Affiche la phase et le plateau en boucle. Ctrl+C pour arrêter.

    Avec `--trace fichier.jsonl`, chaque lecture est aussi enregistrée
    AVEC LE RATIO DE CHAQUE CARTE. C'est ce qu'il faut quand une phase
    est mal lue : le tableau à l'écran dit « enemy_board », le fichier
    dit « 0.731 », et on sait alors si la borne est à deux centièmes ou
    à côté de la plaque. Sans les nombres, on ne peut que deviner.
    """
    import json

    reader = GameStateReader()
    handle = open(trace_path, "a", encoding="utf8") if trace_path else None
    print("Surveillance en cours — Ctrl+C pour arrêter.")
    if handle:
        print(f"Trace enregistrée dans {trace_path}\n")
    else:
        print()

    last = None
    try:
        while True:
            snap = reader.snapshot()
            changed = snap.phase is not last
            marker = ">>" if changed else "  "
            print(f"{marker} {time.strftime('%H:%M:%S')} {snap.summary()}")

            if handle:
                handle.write(json.dumps({
                    "t": time.strftime("%H:%M:%S"),
                    "phase": snap.phase.name,
                    "orbe": snap.turn_orb_active,
                    "jeton": snap.attack_token,
                    "cartes": [
                        {
                            "code": c.code, "nom": c.name, "moi": c.local,
                            "type": c.type, "ratio": round(c.ratio, 4), "zone": c.zone,
                        }
                        for c in snap.cards()
                    ],
                }, ensure_ascii=False) + "\n")
                handle.flush()

            last = snap.phase
            time.sleep(interval)
    finally:
        if handle:
            handle.close()


@dataclass
class LigneInspection:
    """Une ligne du tableau de `game_state.py inspect`."""

    code: str
    nom: str
    local: bool
    y: int
    hauteur: int
    ratio: float
    bande: str          # ce que la HAUTEUR dit
    zone: str           # ce que le bot RETIENT vraiment
    motif: str = ""     # pourquoi les deux diffèrent : "camp" ou "pile"


def lignes_inspection(reader: "GameStateReader", rectangles: list, window: Window) -> tuple:
    """
    Les lignes du tableau d'`inspect`. Renvoie (lignes, bandes, mulligan).

    Aucune capture d'écran, aucun appel à l'API : tout vient des
    rectangles passés en argument. C'est ce qui rend la colonne
    « zone retenue » testable sans le jeu.

    LA COLONNE REJOUE LE CHEMIN DU BOT, ELLE NE LE PARAPHRASE PAS
    (09/11/2026). Elle refaisait à la main la MOITIÉ de
    `reconcile_combat_rows` — le camp pour les unités — et oubliait
    l'autre : un SORT ou une compétence tombé dans une bande de combat
    va sur la PILE, où que sa hauteur l'ait mis. Mesuré sur un
    instantané fabriqué (sort adverse au ratio 0,65) : le tableau
    affichait « enemy_attack » quand l'instantané rangeait « stack »,
    c'est-à-dire exactement le classement qui déclenche SPELL_STACK.
    Et l'exception du mulligan manquait aussi : quatre cartes proposées
    au centre ressortaient « attack <- camp » alors que `snapshot` ne
    réconcilie rien dans cette phase. On appelle donc `_build_cards`,
    `_looks_like_mulligan` et `reconcile_combat_rows`, les mêmes que
    `snapshot`, plutôt que d'en réécrire un résumé qui dérive.
    """
    bands = reader.bands_for(rectangles, window)
    ordonnes = sorted(rectangles, key=lambda r: -r.get("TopLeftY", 0))

    # `_build_cards` garde les rectangles dans l'ordre reçu, et garde
    # exactement ceux qui portent un code autre que le nexus : la liste
    # des cartes se réaligne donc sur ces indices-là.
    gardes = [
        i for i, rect in enumerate(ordonnes)
        if rect.get("CardCode") and rect.get("CardCode") != lor_api.NEXUS_CARD_CODE
    ]
    cartes, _ = reader._build_cards(ordonnes, window, bands)
    bandes_lues = [card.zone for card in cartes]

    # La réconciliation n'a pas lieu pendant le mulligan — les cartes
    # proposées sont au centre, donc dans les bandes de combat.
    mulligan = reader._looks_like_mulligan(cartes)
    if not mulligan:
        reconcile_combat_rows(cartes)

    par_indice = {
        indice: (card, bande)
        for indice, card, bande in zip(gardes, cartes, bandes_lues)
    }

    lignes = []
    for indice, rect in enumerate(ordonnes):
        code = rect.get("CardCode", "?")
        ligne = LigneInspection(
            code=code, nom="?", local=bool(rect.get("LocalPlayer")),
            y=rect.get("TopLeftY", 0), hauteur=rect.get("Height", 0),
            ratio=zone_ratio(rect, window),
            bande="-", zone="-",
        )
        if code == lor_api.NEXUS_CARD_CODE:
            ligne.nom = "(nexus)"
        elif indice in par_indice:
            card, bande = par_indice[indice]
            ligne.nom = card.name
            ligne.bande = bande
            ligne.zone = card.zone
            if card.zone != bande:
                # Le motif se DÉDUIT du résultat : on ne rejuge pas la règle.
                ligne.motif = "pile" if card.zone == "stack" else "camp"
        else:
            # Rectangle sans code : le bot l'ignore, le tableau le montre
            # tel quel plutôt que de lui inventer une zone.
            ligne.bande = classify_zone(rect, window, bands)
            ligne.zone = ligne.bande
        lignes.append(ligne)

    return lignes, bands, mulligan


def cmd_inspect() -> None:
    """
    Tableau de tous les rectangles renvoyés par l'API, avec le ratio
    calculé et la zone déduite. C'est l'outil pour valider ZONE_BANDS :
    lance-le pendant un combat, et vérifie que chaque carte tombe dans
    la bonne colonne. Si une zone est décalée, ajuste la borne
    correspondante dans ZONE_BANDS.

    Le tableau lui-même est bâti par `lignes_inspection`, qui ne lit que
    les rectangles : ici il n'y a plus que l'appel à l'API et l'impression.
    """
    try:
        api_data = lor_api.get_positional_rectangles()
    except ApiUnavailable as exc:
        print(f"API injoignable : {exc}")
        return

    window = lor_api.get_window(api_data)
    card_db = lor_api.load_card_db()
    rectangles = api_data.get("Rectangles") or []

    # Les MÊMES bandes que celles utilisées en jeu. Avant, `inspect`
    # affichait toujours ZONE_BANDS d'origine : dès qu'une calibration
    # existait, l'outil de diagnostic et le bot ne parlaient pas de la
    # même chose, et c'est exactement dans ce cas qu'on vient l'ouvrir.
    reader = GameStateReader(card_db=card_db)
    lignes, bands, mulligan = lignes_inspection(reader, rectangles, window)
    rescaled = bands != ZONE_BANDS

    print(f"GameState : {api_data.get('GameState')}")
    print(f"Fenêtre   : {window}")
    print(f"Screen API: {api_data.get('Screen')}")
    print(f"{len(rectangles)} rectangles")
    print(f"Bandes    : {'recalibrées' if rescaled else 'valeurs par défaut'}")
    if mulligan:
        print("Mulligan  : reconnu — les bandes sont gardées telles quelles")
    print()

    header = (f"{'code':<10} {'nom':<26} {'moi':<4} {'Y':>6} {'H':>5} "
              f"{'ratio':>7}  {'bande':<13} zone retenue")
    print(header)
    print("-" * len(header))

    for ligne in lignes:
        retenue = ligne.zone + (f"  <- {ligne.motif}" if ligne.motif else "")
        print(
            f"{ligne.code:<10} {ligne.nom[:26]:<26} "
            f"{'oui' if ligne.local else 'non':<4} "
            f"{ligne.y:>6} {ligne.hauteur:>5} "
            f"{ligne.ratio:>7.3f}  {ligne.bande:<13} {retenue}"
        )

    print("\nBornes en vigueur (ratio depuis le bas) :")
    low = 0.0
    for upper, name in bands:
        print(f"    {name:<13} {low:.3f} -> {upper:.3f}")
        low = upper
    print(f"    {FALLBACK_ZONE:<13} {low:.3f} -> 1.000")


def cmd_vision(output_dir: str) -> None:
    """
    Exporte les deux zones de vision et leurs masques HSV, et surtout
    indique QUEL critère écarte les pixels.

    C'est la colonne « H seule » qu'il faut regarder en premier : si elle
    est énorme et que « H+S » s'effondre, c'est que la teinte attrape le
    décor doré et que seule la saturation fait le tri. Si « H+S+V » est
    non nul alors que tu ne vois pas l'élément à l'écran, la région pointe
    au mauvais endroit : refais `snap` puis `cut-token`.
    """
    from pathlib import Path

    try:
        api_data = lor_api.get_positional_rectangles()
    except ApiUnavailable:
        api_data = None

    window = lor_api.get_window(api_data)
    screen = lor_api.capture_screen_bgr()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Le jeton n'est plus ici : il est cherché par forme, pas par couleur.
    # Pour le diagnostiquer, `monitor` affiche son score de matching.
    targets = (
        ("orbe_de_tour", TURN_ORB_REGION, TURN_ORB_HSV, TURN_ORB_MIN_PX),
    )

    print(f"Fenêtre : {window}\n")
    for label, region, hsv_range, min_px in targets:
        box = window.rel_box(region)
        crop = lor_api.crop_box(screen, box)
        if crop is None:
            print(f"{label:<15} zone hors cadre {box}")
            continue

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        (h_lo, s_lo, v_lo), (h_hi, s_hi, v_hi) = hsv_range
        hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

        # Décomposition du filtre, pour voir lequel des trois critères
        # fait réellement le travail.
        m_h = (hue >= h_lo) & (hue <= h_hi)
        m_hs = m_h & (sat >= s_lo) & (sat <= s_hi)
        m_hsv = m_hs & (val >= v_lo) & (val <= v_hi)

        mask = (m_hsv * 255).astype(np.uint8)
        count = int(m_hsv.sum())
        total = hue.size

        cv2.imwrite(str(out / f"{label}_zone.png"), crop)
        cv2.imwrite(str(out / f"{label}_masque.png"), mask)

        verdict = "DÉTECTÉ" if count >= min_px else "absent"
        print(f"{label}  box={box}  seuil={min_px} px  -> {verdict}")
        print(f"    H seule   {int(m_h.sum()):>7} px ({100 * m_h.sum() / total:5.1f} %)")
        print(f"    H+S       {int(m_hs.sum()):>7} px ({100 * m_hs.sum() / total:5.1f} %)")
        print(f"    H+S+V     {count:>7} px ({100 * count / total:5.1f} %)")
        if m_hsv.any():
            print(
                f"    retenus   H {int(hue[m_hsv].min())}-{int(hue[m_hsv].max())}  "
                f"S {int(sat[m_hsv].min())}-{int(sat[m_hsv].max())}  "
                f"V {int(val[m_hsv].min())}-{int(val[m_hsv].max())}"
            )
        print()

    print(f"Crops exportés dans {out.resolve()}")

    # Diagnostic du jeton dans la même passe : c'est le score qui compte.
    match = find_attack_token(
        screen, window, midline_y=nexus_midline_y(
            (api_data or {}).get("Rectangles") or [], window
        )
    )
    print()
    if match.template_missing:
        print(f"jeton_attaque  template absent : {ATTACK_TOKEN_TEMPLATE}")
        print("               `snap avec` puis `cut-token` pour le générer.")
    else:
        print(
            f"jeton_attaque  score={match.score:.3f} "
            f"seuil={ATTACK_TOKEN_MATCH_THRESHOLD}  échelle x{match.scale:.2f}  "
            f"-> {'TROUVÉ' if match.found else 'absent'}  côté {match.side}"
        )
        if match.position:
            print(f"               position {match.position}")


def pick_box_tk(image: np.ndarray, max_width: int = 1400, title: str = "Entoure la zone") -> Optional[tuple]:
    """
    Sélecteur de zone en Tkinter.

    On n'utilise PAS cv2.selectROI : easyocr installe
    `opencv-python-headless`, une build d'OpenCV compilée SANS interface
    graphique, qui écrase la build normale. Toute fonction de fenêtrage
    d'OpenCV (imshow, selectROI, destroyAllWindows) lève alors « The
    function is not implemented ». Tkinter est dans la bibliothèque
    standard et ne dépend pas d'OpenCV, donc ce chemin marche quel que
    soit le paquet cv2 installé.

    Renvoie (x, y, largeur, hauteur) en pixels PLEINE RÉSOLUTION, ou None.
    """
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError as exc:
        print(f"Sélection interactive indisponible ({exc}).")
        return None

    height, width = image.shape[:2]
    scale = min(1.0, max_width / width)
    display = (
        cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else image
    )
    rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)

    state = {"start": None, "box": None, "rect": None}

    root = tk.Tk()
    root.title(title + " — ENTREE pour valider, ECHAP pour annuler")
    photo = ImageTk.PhotoImage(Image.fromarray(rgb))
    canvas = tk.Canvas(root, width=photo.width(), height=photo.height(), highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=photo)
    label = tk.Label(root, text="Clique-glisse autour de l'épée.")
    label.pack(fill="x")

    def on_press(event):
        state["start"] = (event.x, event.y)
        if state["rect"] is not None:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#00ff00", width=2
        )

    def on_drag(event):
        if state["start"] is None:
            return
        x0, y0 = state["start"]
        canvas.coords(state["rect"], x0, y0, event.x, event.y)
        state["box"] = (min(x0, event.x), min(y0, event.y),
                        abs(event.x - x0), abs(event.y - y0))
        bx, by, bw, bh = state["box"]
        label.config(
            text=f"Sélection {int(bw / scale)}x{int(bh / scale)} px "
                 f"en ({int(bx / scale)}, {int(by / scale)}) — ENTRÉE pour valider"
        )

    def validate(_=None):
        root.quit()

    def cancel(_=None):
        state["box"] = None
        root.quit()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_drag)
    root.bind("<Return>", validate)
    root.bind("<KP_Enter>", validate)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    root.destroy()

    if not state["box"] or state["box"][2] < 3 or state["box"][3] < 3:
        return None

    x, y, w, h = state["box"]
    return (int(x / scale), int(y / scale), int(w / scale), int(h / scale))


def pick_point_tk(image: np.ndarray, title: str = "Clique le point", max_width: int = 1400):
    """
    Demande à l'humain de désigner UN point sur une capture.

    Même raison que `pick_box_tk` d'utiliser Tkinter plutôt qu'OpenCV :
    easyocr installe `opencv-python-headless`, compilé sans interface
    graphique, et toute fenêtre cv2 lève alors « The function is not
    implemented ».

    Sert à calibrer les boutons dont je ne connais pas la position. Un
    clic humain vaut mieux qu'une constante devinée : c'est juste du
    premier coup, et ça reste juste si l'interface change.

    Renvoie (x, y) en pixels pleine résolution, ou None si annulé.
    """
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError as exc:
        print(f"Sélection interactive indisponible ({exc}).")
        return None

    height, width = image.shape[:2]
    scale = min(1.0, max_width / width)
    display = (
        cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1.0 else image
    )
    rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)

    state = {"point": None, "marker": None}

    root = tk.Tk()
    root.title(title + " — ENTREE pour valider, ECHAP pour annuler")
    photo = ImageTk.PhotoImage(Image.fromarray(rgb))
    canvas = tk.Canvas(root, width=photo.width(), height=photo.height(), highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=photo)
    label = tk.Label(root, text=title)
    label.pack(fill="x")

    def on_click(event):
        if state["marker"] is not None:
            canvas.delete(state["marker"])
        state["marker"] = canvas.create_oval(
            event.x - 9, event.y - 9, event.x + 9, event.y + 9, outline="#00ff00", width=3
        )
        state["point"] = (int(event.x / scale), int(event.y / scale))
        label.config(text=f"Point : {state['point']} — ENTRÉE pour valider")

    canvas.bind("<ButtonPress-1>", on_click)
    root.bind("<Return>", lambda _: root.quit())
    root.bind("<KP_Enter>", lambda _: root.quit())
    root.bind("<Escape>", lambda _: (state.update(point=None), root.quit()))
    root.protocol("WM_DELETE_WINDOW", lambda: (state.update(point=None), root.quit()))
    root.mainloop()
    root.destroy()

    return state["point"]


def _tighten_to_icon(crop: np.ndarray, value_floor: int = 90,
                     margin: int = 2, max_coverage: float = 0.80) -> Optional[tuple]:
    """
    Resserre une sélection approximative sur l'icône qu'elle contient.

    LE SEUIL EST CALCULÉ, PAS DEVINÉ. Un plancher de saturation en dur ne
    peut pas marcher : la saturation du décor de LoR varie selon la zone
    du plateau et la luminosité, et une valeur choisie à l'avance est soit
    trop basse (tout le décor est retenu, le resserrage ne resserre rien)
    soit trop haute (l'icône elle-même disparaît). Otsu trouve la
    séparation naturelle entre les deux populations de pixels PRÉSENTES
    DANS LA SÉLECTION, ce qui est exactement la question posée.

    Ce n'est pas le test qui décidera plus tard si l'épée est là — c'est
    seulement un moyen de recadrer proprement, sur une zone que l'humain
    a déjà désignée. Le risque d'erreur est donc borné.

    Renvoie (x, y, largeur, hauteur) relatifs au crop, ou None si aucune
    séparation nette n'apparaît.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]

    _, mask = cv2.threshold(saturation, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_and(mask, ((value >= value_floor) * 255).astype(np.uint8))

    area = int(np.count_nonzero(mask))
    if area == 0 or area > max_coverage * mask.size:
        # Pas de séparation nette : soit la sélection est uniforme, soit
        # elle est entièrement « saturée ». Dans les deux cas, resserrer
        # serait arbitraire — on préfère ne rien faire et le dire.
        return None

    # La plus grande composante connexe, et non l'étendue de tous les
    # pixels retenus : un reflet isolé dans un coin de la sélection
    # élargirait la boîte jusqu'à lui.
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return None
    biggest = max(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA])

    height, width = crop.shape[:2]
    x = int(stats[biggest, cv2.CC_STAT_LEFT])
    y = int(stats[biggest, cv2.CC_STAT_TOP])
    w = int(stats[biggest, cv2.CC_STAT_WIDTH])
    h = int(stats[biggest, cv2.CC_STAT_HEIGHT])

    x1, y1 = max(0, x - margin), max(0, y - margin)
    x2, y2 = min(width, x + w + margin), min(height, y + h + margin)
    return (x1, y1, x2 - x1, y2 - y1)


def cmd_cut_button(label: str) -> None:
    """
    Enregistre le TEXTE du bouton de tour tel qu'il s'affiche maintenant
    sous assets/orb/<label>.png. À lancer pendant que le jeu affiche ce
    libellé (« FIN DU TOUR », « ATTAQUER », « RÉSOUDRE »…). Le texte est
    isolé par ses pixels blancs dans la zone de l'orbe.
    """
    window = lor_api.get_window()
    screen = lor_api.capture_screen_bgr()
    crop = lor_api.crop_box(screen, window.rel_box(TURN_ORB_REGION))
    if crop is None or crop.size == 0:
        print("Zone de l'orbe hors écran : fenêtre du jeu introuvable ?")
        return
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 200)
    h, w = white.shape
    # On ne garde que la bande centrale : le liseré clair du cadran est
    # blanc aussi, mais il est au bord.
    inner = np.zeros_like(white)
    inner[int(h * 0.25):int(h * 0.75), int(w * 0.3):int(w * 0.95)] = white[int(h * 0.25):int(h * 0.75), int(w * 0.3):int(w * 0.95)]
    ys, xs = np.nonzero(inner)
    if len(xs) < 30:
        print("Aucun texte blanc lisible sur le bouton : est-il bien affiché ?")
        return
    y0, y1 = max(0, ys.min() - 3), min(h, ys.max() + 4)
    x0, x1 = max(0, xs.min() - 4), min(w, xs.max() + 5)
    TURN_BUTTON_DIR.mkdir(parents=True, exist_ok=True)
    out = TURN_BUTTON_DIR / f"{label}.png"
    cv2.imwrite(str(out), crop[y0:y1, x0:x1])
    print(f"Libellé « {label} » enregistré : {out} ({x1 - x0}x{y1 - y0} px)")
    read, score = read_turn_button(screen, window)
    print(f"Relecture immédiate : {read} (score {score:.2f})")


def cmd_cut_token(source: str, output_path: str, max_width: int,
                  box: Optional[list] = None, tighten: bool = True) -> None:
    """
    Découpe le template de l'épée dans une capture.

    Deux façons de désigner la zone :
        - à la souris (fenêtre Tkinter), par défaut ;
        - avec --box X Y LARGEUR HAUTEUR, si l'affichage n'est pas
          disponible ou pour ajuster au pixel.

    Le cadrage doit être SERRÉ sur l'icône : un template qui embarque du
    décor matche moins bien dès que le fond change, et un template trop
    générique matche n'importe quoi. Il faut aussi éviter le halo
    pulsant, dont l'intensité varie d'une frame à l'autre. Comme c'est
    difficile à faire à la souris, une sélection approximative est
    resserrée automatiquement sur les pixels saturés (--no-tighten pour
    désactiver).
    """
    src = Path(source)
    if not src.exists():
        print(f"Capture introuvable : {src}")
        print("Lance d'abord `python game_state.py snap avec` en tenant le jeton.")
        return

    image = cv2.imread(str(src))
    if image is None:
        print(f"Capture illisible : {src}")
        return

    height, width = image.shape[:2]

    if box:
        x, y, w, h = (int(v) for v in box)
    else:
        print("Une fenêtre va s'ouvrir : entoure l'épée, puis ENTRÉE (ÉCHAP pour annuler).")
        selection = pick_box_tk(image, max_width, "Entoure l'epee")
        if selection is None:
            print("\nSélection annulée ou impossible.")
            print("Solution de repli, sans affichage :")
            print("    python game_state.py cut-token --box X Y LARGEUR HAUTEUR")
            print(f"La capture fait {width}x{height} px.")
            return
        x, y, w, h = selection

    # Bornage : une saisie manuelle hors cadre donnerait un crop vide.
    x, y = max(0, min(x, width - 1)), max(0, min(y, height - 1))
    w, h = max(1, min(w, width - x)), max(1, min(h, height - y))
    crop = image[y:y + h, x:x + w]

    if tighten:
        inner = _tighten_to_icon(crop)
        if inner is None:
            print("Pas de séparation nette icône/décor : sélection gardée telle quelle.")
            print("Si le template embarque du décor, recadre à la main avec --box.")
        elif inner[2] < 6 or inner[3] < 6:
            print(f"Resserrage ignoré : résultat trop petit ({inner[2]}x{inner[3]} px).")
        elif (inner[0], inner[1], inner[2], inner[3]) == (0, 0, w, h):
            print(f"Sélection déjà serrée ({w}x{h} px), aucun resserrage nécessaire.")
        else:
            ix, iy, iw, ih = inner
            print(f"Sélection {w}x{h} resserrée en {iw}x{ih} px sur l'icône.")
            x, y, w, h = x + ix, y + iy, iw, ih
            crop = image[y:y + h, x:x + w]

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Le template est écrit AVEC SON MASQUE en canal alpha : seule l'épée
    # compte dans la correspondance, pas le compteur de mana ni les
    # rouages derrière elle (cf. load_template_with_mask).
    mask = icon_mask(crop)
    coverage = float(mask.mean()) / 255.0
    if coverage < 0.05:
        print("Masque trop maigre (l'épée n'est pas reconnue par sa couleur) : "
              "template écrit SANS masque.")
        cv2.imwrite(str(destination), crop)
    else:
        cv2.imwrite(str(destination), np.dstack([crop, mask]))
        print(f"Masque : {coverage:.0%} du cadre retenu (l'épée seule, sans le fond).")

    # Aperçu agrandi : à 20x20 px le template est illisible à l'œil, et
    # c'est pourtant la seule façon de voir qu'on a attrapé du décor.
    zoom = max(1, 160 // max(w, h))
    if zoom > 1:
        preview_path = destination.with_name(destination.stem + "_apercu.png")
        cv2.imwrite(
            str(preview_path),
            cv2.resize(crop, (w * zoom, h * zoom), interpolation=cv2.INTER_NEAREST),
        )
        print(f"Aperçu agrandi x{zoom} : {preview_path.resolve()}")

    print(f"\nTemplate écrit : {destination.resolve()}  ({w}x{h} px, box {x} {y} {w} {h})")

    # Région de recherche suggérée : large en hauteur pour couvrir les
    # deux moitiés du plateau, resserrée en largeur autour de la colonne
    # où se trouve l'épée.
    window = lor_api.get_window()
    centre_x = x + w / 2
    half_width = max(w * 3, int(window.width * 0.10))
    rx1 = max(0, centre_x - half_width) / window.width
    rx2 = min(window.width, centre_x + half_width) / window.width
    print(
        "\nRégion de recherche suggérée (ATTACK_TOKEN_SEARCH_REGION) :\n"
        f"    (({rx1:.4f}, 0.1800), ({rx2:.4f}, 0.9200))"
    )
    print(
        "\nVérifie ensuite avec :\n"
        "    python game_state.py vision      # score du matching\n"
        "    python game_state.py monitor     # le score doit chuter au round suivant"
    )


def cmd_calibrate_zones() -> None:
    """
    Enregistre la géométrie actuelle des nexus comme référence.

    À lancer PENDANT UN COMBAT, dans la configuration où `inspect` montre
    un classement correct. On ne mesure pas « les bonnes bandes » — elles
    sont déjà connues — mais la géométrie sous laquelle elles sont vraies.
    Les bandes seront ensuite rééchelonnées sur l'écartement des nexus, ce
    qui les rend valables à une autre résolution.
    """
    try:
        api_data = lor_api.get_positional_rectangles()
    except ApiUnavailable as exc:
        print(f"API injoignable : {exc}")
        return

    window = lor_api.get_window(api_data)
    rectangles = api_data.get("Rectangles") or []
    span = nexus_span(rectangles, window)

    if span is None:
        print("Les deux nexus ne sont pas visibles : lance ceci pendant un combat.")
        return

    import json
    path = lor_api.PROJECT_ROOT / "calibration.json"
    try:
        with open(path, encoding="utf8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    data[ZONE_CALIBRATION_KEY] = list(span)
    with open(path, "w", encoding="utf8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)

    print(f"Fenêtre        : {window.width}x{window.height}")
    print(f"Nexus allié    : {span[0]:.4f} depuis le bas")
    print(f"Nexus adverse  : {span[1]:.4f} depuis le bas")
    print(f"Écartement     : {span[1] - span[0]:.4f}")
    print(f"\nRéférence enregistrée dans {path.name}.")
    print("Les bandes de zones suivront désormais la géométrie du plateau,")
    print("y compris si tu changes de résolution.")


def cmd_snap(label: str, output_dir: str) -> None:
    """
    Capture l'écran complet sous un nom donné.

        python game_state.py snap avec    # pendant que tu AS le jeton
        python game_state.py cut-token    # découpe l'épée dedans
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ecran_{label}.png"

    screen = lor_api.capture_screen_bgr()
    cv2.imwrite(str(path), screen)

    window = lor_api.get_window()
    print(f"Écran capturé : {path.resolve()}")
    print(f"Fenêtre       : {window}")
    print(f"Taille        : {screen.shape[1]}x{screen.shape[0]}")


def main() -> None:
    # AVANT TOUT CE QUI IMPRIME. `GameSnapshot.summary()` écrit « deck :
    # N cartes, ≤ M à piocher », et ce « ≤ » n'existe pas en cp1252 :
    # `python game_state.py monitor > rapport.txt` mourait dessus dès que
    # `/static-decklist` avait répondu. Mesuré le 10/11/2026, et le
    # `logging` du projet ne le disait pas — stderr survit toujours, c'est
    # le `print` qui tombe. Cf. `sortie_utf8.py`.
    sortie_utf8.appliquer()
    parser = argparse.ArgumentParser(
        description="Lecture de l'état de partie Legends of Runeterra."
    )
    sub = parser.add_subparsers(dest="command")

    monitor = sub.add_parser("monitor", help="surveille la phase en direct")
    monitor.add_argument("--interval", type=float, default=1.0)
    monitor.add_argument("--record", nargs="?", const=True, default=None, metavar="DOSSIER",
                         help="enregistrer API + captures pour `replay.py` "
                              "(sans dossier : traces/monitor_<horodatage>/)")
    monitor.add_argument("--trace", metavar="FICHIER",
                         help="enregistre chaque lecture, ratios compris, en JSONL")

    sub.add_parser("inspect", help="tableau des rectangles et des zones déduites")
    sub.add_parser("calibrate-zones", help="ancrer les bandes sur la géométrie des nexus")

    vision = sub.add_parser("vision", help="exporte les crops de calibration couleur")
    vision.add_argument("--output", default="calibration_crops")

    snap = sub.add_parser("snap", help="capture l'écran complet sous un nom")
    snap.add_argument("label", help="nom de la capture, ex. avec / sans")
    snap.add_argument("--output", default="calibration_crops")

    cutb = sub.add_parser("cut-button", help="enregistre le texte du bouton de tour comme libellé")
    cutb.add_argument("label", help="nom du libellé affiché MAINTENANT, ex. fin_du_tour, attaquer, resoudre")

    cut = sub.add_parser("cut-token", help="découpe le template de l'épée à la souris")
    cut.add_argument("--source", default="calibration_crops/ecran_avec.png",
                     help="capture dans laquelle découper")
    cut.add_argument("--output", default=str(ATTACK_TOKEN_TEMPLATE),
                     help="chemin du template à écrire")
    cut.add_argument("--max-width", type=int, default=1400,
                     help="largeur max de l'aperçu de sélection")
    cut.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "LARGEUR", "HAUTEUR"),
                     help="zone à découper, sans passer par la souris")
    cut.add_argument("--no-tighten", action="store_true",
                     help="ne pas resserrer la sélection sur les pixels saturés")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.command == "inspect":
        cmd_inspect()
    elif args.command == "calibrate-zones":
        cmd_calibrate_zones()
    elif args.command == "vision":
        cmd_vision(args.output)
    elif args.command == "snap":
        cmd_snap(args.label, args.output)
    elif args.command == "cut-button":
        cmd_cut_button(args.label)
    elif args.command == "cut-token":
        cmd_cut_token(args.source, args.output, args.max_width,
                      box=args.box, tighten=not args.no_tighten)
    else:
        try:
            if getattr(args, "record", None):
                import replay
                record = args.record
                trace_dir = replay.start_recording(None if record is True else record, "monitor")
                print(f"Trace enregistrée dans {trace_dir}")
            cmd_monitor(getattr(args, "interval", 1.0), getattr(args, "trace", None))
        except KeyboardInterrupt:
            print("\nArrêt.")


if __name__ == "__main__":
    main()
