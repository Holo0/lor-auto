#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spells.py

Décider si un sort est jouable, et sur quoi.

    python spells.py coverage     # taux de couverture sur TOUTE ta base
    python spells.py explain "Deal 3 to anything."

--------------------------------------------------------------------
LE PROBLÈME
--------------------------------------------------------------------
Un sort à cible fait passer le jeu en MODE CIBLAGE : il attend un clic
sur une unité ou un nexus. Se tromper coûte cher dans les deux sens —
ne pas cliquer fige la partie, cliquer au mauvais endroit gaspille la
carte ou, pire, retourne l'effet contre nous.

Aucun champ de card_sets ne dit si un sort demande une cible. Il n'y a
que `descriptionRaw`, en anglais. La question est donc : comment en
tirer une décision fiable sans écrire mille motifs ?

--------------------------------------------------------------------
L'IDÉE : COMPTER LES CIBLES, PAS RECONNAÎTRE LES SORTS
--------------------------------------------------------------------
Le jeu n'entre en ciblage que si l'effet nomme une cible AU SINGULIER.
« Deal 3 to all enemies » ne demande rien ; « Deal 3 to an enemy » si.
On compte donc les marqueurs singuliers présents dans le texte :

    0 marqueur  -> aucun clic attendu
    1 marqueur  -> une cible, et le marqueur dit de quel camp
    2 et plus   -> plusieurs cibles, on refuse

C'est une règle générale et non une liste de cas particuliers : elle
couvre les sorts qui n'existent pas encore. Reconnaître le VERBE ne sert
alors qu'à deux choses : choisir une bonne cible, et détecter les effets
néfastes.

--------------------------------------------------------------------
LE GARDE-FOU QUI COMPTE
--------------------------------------------------------------------
Un effet néfaste dirigé sur NOTRE camp est refusé. « Kill an ally » ou
« Deal 1 to an allied follower » sont des coûts que le bot paierait sans
comprendre la contrepartie, en sacrifiant sa meilleure unité. De même,
un renfort dirigé sur l'adversaire est refusé — sauf s'il s'agit d'un
malus déguisé (« give an enemy Vulnerable »), reconnaissable au fait
qu'il n'accorde pas de +X|+X.

En cas de doute, on ne joue pas. Un sort non joué coûte un tour de
tempo ; un sort mal joué peut coûter la partie. Et le filet
`cancel_pending_action` d'actions.py rattrape les erreurs restantes.

--------------------------------------------------------------------
CE QUE LE FILET NE RATTRAPE PAS (22/08/2026)
--------------------------------------------------------------------
Le clic sur une zone vide annule un CIBLAGE. Il ne referme PAS une
fenêtre de choix de carte : ce choix-là est obligatoire, le bouton de
passe n'y peut rien non plus, et la partie ne repart jamais. C'est
pourquoi `REFUSALS` a une troisième colonne — « hors de portée » — qui
distingue les refus de PRUDENCE, levés avec les restrictions, de ceux
qui décrivent une interface qu'on ne sait pas piloter et qui valent dans
les DEUX modes.

Une seule fenêtre fait exception, parce qu'elle nomme son contenu :
« Play me as First Wave or Last Wind » (cf. `play_as_options`). Celle-là
est pilotée par `actions.resolve_play_choice`.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Optional

import keywords

# ============================================================
# MARQUEURS DE CIBLE
# ============================================================
# Ordre important : les formulations les plus longues d'abord, pour que
# « an ally in hand » ne soit pas lu comme « an ally ».

SINGULAR_TARGETS = [
    (r"\ban? (ally|unit|follower|card|champion|spell|equipment) (in|from) hand\b", "HAND"),
    # « AN ENEMY OR THE ENEMY NEXUS » : LE NEXUS EST UNE CIBLE CLIQUABLE
    # (08/11/2026). Un seul clic, mais il a DEUX endroits où tomber, et le
    # second existe toujours — un nexus ne quitte jamais le plateau.
    #
    # Le marqueur « an enemy » seul désignait l'unité, le nexus n'était
    # écrit nulle part, et `choose_target` ne donnait son repli sur le
    # nexus qu'au `Targeting.ANYTHING` de « Deal 3 to anything ». Plateau
    # adverse VIDE, ces sorts rendaient donc « aucun ennemi en jeu » : le
    # bot gardait en main la brûlure qui finit la partie, dans l'état même
    # que `actions.nexus_weight` et l'archétype « aggro » existent pour
    # exploiter. Le refus d'`actions.sort_sans_cible` (08/11, matin) n'a
    # pas creusé ce trou, il l'a rendu VISIBLE — et silencieux.
    #
    # SEPT SORTS de la base, mesurés : Trueshot Barrage (01PZ004), Statikk
    # Shock (01PZ031), Shock Blast (05PZ027) et le jeton de Jayce
    # (05PZ022T2), Divine Draft (07PZ022), Timewinder (04PZ003) et Solar
    # Snare (98PZ008, « a unit or the enemy Nexus »).
    #
    # MAIS SIX SEULEMENT CHANGENT DE PLAN, et ça se mesure sur la base :
    # Timewinder (04PZ003) porte bien le marqueur dans son texte et n'en
    # tire RIEN — son « To play, discard 1. » la fait basculer en
    # `Targeting.HAND` sans restrictions (la désignation en main passe
    # devant le plateau) et la refuse en mode prudent (« coût
    # additionnel à payer »). Elle est nommée ici parce que le marqueur
    # la matche, pas parce qu'elle est réparée.
    #
    # LES QUALIFICATIFS SONT CEUX DU MARQUEUR ORDINAIRE, ET PAS UN DE
    # PLUS : « a random enemy or the enemy Nexus » (Ricochet, 04SH119) et
    # « a different random enemy or the enemy Nexus » (Volibear, 08FR001)
    # ne doivent PAS entrer — c'est le jeu qui tire, aucun clic n'est
    # attendu, exactement comme « a random ally ». Un « n'importe quels
    # deux mots » permissif les aurait avalés tous les deux.
    (r"\ban? (attacking |battling |damaged )?(?:enemy|unit|follower|champion)"
     r" or the enemy nexus\b",                                     "ANYTHING"),
    (r"\ban? \w*\s?allied \w+\b",                                  "ALLY"),
    (r"\banother ally\b",                                          "ALLY"),
    # « another », avec substantif, DÉSIGNE UNE VRAIE CIBLE — la même
    # famille que « an ally »/« an enemy », juste au singulier exclusif
    # (« un AUTRE que celui déjà en jeu »). « Swap my stats with another
    # unit. » (Robot défectueux, 04PZ020) n'a AUCUN autre marqueur dans son
    # texte : sans cette ligne, le sort passait pour n'avoir aucune cible,
    # et le jeu restait bloqué en attente d'un clic que rien ne prévoyait.
    (r"\banother (attacking |battling |damaged )?enemy\b",         "ENEMY"),
    (r"\banother (damaged |battling )?unit\b",                     "ANY_UNIT"),
    (r"\banother follower\b",                                      "ANY_UNIT"),
    (r"\banother champion\b",                                      "ANY_UNIT"),
    # « an ally », MAIS AUSSI « an Equipped ally », « a damaged ally »,
    # « a battling ally », « a 1 cost ally ». Un adjectif devant « ally »
    # RESTREINT la cible, il ne la supprime pas : sans ces deux mots
    # facultatifs, « An Equipped ally strikes an enemy » (Lame féroce,
    # 06NX034) ne montrait qu'UN marqueur — l'ennemi — et le bot cliquait
    # directement dessus au lieu de refuser un sort à deux clics. Vu en
    # jeu le 22/08/2026 ; Whirling Death (01NX011) et Fish Fight (06DE017)
    # avaient exactement le même angle mort.
    #
    # « A RANDOM ALLY » EST EXCLU, et c'est le seul cas où l'adjectif
    # change la nature de la phrase : c'est le JEU qui choisit, aucun clic
    # n'est attendu. En faire une cible ferait cliquer une unité au hasard
    # sur un sort qui se résout tout seul (Mist's Call 01SI046, Flashbomb
    # Trap 05PZ008).
    (r"\ban? (?!random\b)(?:\w+ ){0,2}ally\b",                     "ALLY"),
    # « AN ENEMY FOLLOWER » DOIT ÊTRE LU D'UN SEUL TENANT (10/11/2026).
    # Le marqueur court « an enemy » recouvrait déjà ces textes et rendait
    # le bon CAMP, mais son span s'arrêtait avant le substantif — or
    # `target_condition_of` lit la condition SUR LE MARQUEUR. Sans cette
    # ligne, « Charm an enemy follower » (Beckoning Gaze, 98SB015) est
    # indiscernable de « Charm an enemy », et le bot vise le plus gros :
    # un CHAMPION, que le jeu refuse (vu deux fois sur Karma, le
    # 05/11/2026). Le COMPTE de marqueurs ne change pas d'un pouce — à
    # position égale, le plus long l'emporte et consomme la zone, comme
    # « an ally in hand » devant « an ally ».
    (r"\ban? (attacking |battling |damaged )?enemy (?:follower|champion)\b",
                                                                   "ENEMY"),
    (r"\ban? (attacking |battling |damaged )?enemy\b",             "ENEMY"),
    (r"\ba (damaged |battling )?unit\b",                           "ANY_UNIT"),
    (r"\ba follower\b",                                            "ANY_UNIT"),
    (r"\ba champion\b",                                            "ANY_UNIT"),
    (r"\banything\b",                                              "ANYTHING"),
]

# Formulations qu'on refuse d'emblée : elles ouvrent une interface que le
# bot ne sait pas piloter, ou engagent une ressource sans contrepartie
# évaluable.
#
# LA TROISIÈME COLONNE DIT SI LE REFUS SURVIT AUX RESTRICTIONS LEVÉES.
# Elle sépare deux natures de refus qui étaient mélangées :
#
#   PRUDENCE (False) — « ça pourrait se retourner contre nous ». Lever les
#   restrictions, c'est justement accepter ce risque : le bot tente, et le
#   filet est `cancel_pending_action` APRÈS le dépôt.
#
#   HORS DE PORTÉE (True) — « le jeu va ouvrir une fenêtre que je ne sais
#   pas fermer ». Lever les restrictions n'accorde aucune capacité
#   nouvelle, et le filet ne rattrape rien : un choix de carte est
#   OBLIGATOIRE, un clic sur une zone vide ne l'annule pas. La partie se
#   fige, la boucle s'épuise (`_check_progress`), la tentative
#   hebdomadaire est perdue. C'est ce qui est arrivé le 22/08/2026 avec
#   « Les ailes et la vague » (04SI004).
#
#   63 cartes de la base sont dans ce cas. Le prix à payer est connu et
#   assumé : les armes Darkin (« You may spend 8 mana to play me as... »)
#   ne sont plus posées du tout, alors qu'elles seraient jouables sous les
#   8 mana. Un équipement non posé coûte un tempo ; une partie figée coûte
#   la tentative.

# UNE CIBLE MARQUÉE NE SE LIT NULLE PART (11/11/2026).
#
# « Summon a The Beast Challenging a MARKED enemy. » (Beast's Frenzy,
# 98SB047). Mesuré en partie : 15 lancements, 10 blocages de pile,
# 5 « restée en main » sur trois combats — ~80 s, et une carte forte
# (souvent à coût 0) jamais jouée.
#
# Le défaut tenait à UN MOT : aucun motif de SINGULAR_TARGETS ne lit
# « a marked enemy », si bien que l'adjectif ne RESTREIGNAIT pas le
# marqueur, il le faisait DISPARAÎTRE — l'inverse exact de la règle du
# 26/08 (« un adjectif devant *ally* restreint la cible, il ne la
# supprime pas »). Targeting.NONE, donc aucun clic prévu, donc la carte
# posée et le jeu attendant une cible que personne ne lui donnait.
#
# ON NE RÉTABLIT PAS LE MARQUEUR, ET C'EST TOUT LE SUJET : le marquage
# est un mot-clé ACCORDÉ EN JEU, donc INVISIBLE. L'API ne rend qu'un
# CardCode, et Dance of Arrows (98SB040) marque un ennemi AU HASARD :
# rien ne dit lequel l'est. Cliquer un ennemi non marqué ferait refuser
# le clic par le jeu — on aurait échangé un blocage contre un autre.
# C'est exactement la famille des cibles sous condition invisible
# (« est étourdi », « a attaqué ce round », 02/09/2026), donc un refus
# HORS DE PORTÉE, qui vaut dans LES DEUX MODES.
#
# À NE PAS CONFONDRE AVEC « AN ATTACKING ENEMY », ouvert le 06/11 :
# celui-là se LIT dans `attack_row` / `enemy_attack_row`, deux zones que
# l'API rapporte à chaque lecture — comme « damaged » se lit dans les PV
# affichés. La ligne de partage est « lisible » contre « invisible »,
# jamais la forme de la phrase.
#
# LE MOTIF EXIGE UN DÉTERMINANT SINGULIER, ET C'EST LE GARDE-FOU.
# « all marked enemies » n'est PAS un marqueur de cible : c'est le jeu
# qui marque et les dégâts tombent tout seuls sur TOUS les marqués.
# Dance of Arrows et ses trois variantes Kindred FONCTIONNENT (vues
# tourner, résolues plusieurs fois dans la session du 11/11), et les
# refuser casserait une carte qui marche. Même chose pour « Enemies are
# marked. » (une description d'état) et pour le VERBE « Mark an enemy. »
# (Patient Beast, 98SB046), dont la cible est un ennemi ordinaire,
# parfaitement cliquable.
#
# MESURÉ SUR LES 2898 CARTES : SEPT écrivent « marked », UNE SEULE porte
# l'adjectif sur un marqueur de cible.
MARKED_TARGET = r"\b(?:an?|the) marked (?:enemy|ally|unit|follower|champion)\b"
MARKED_TARGET_RX = re.compile(MARKED_TARGET, re.I)

REFUSALS = [
    (r"^to play,",                  "coût additionnel à payer",                    False),
    # « Pick a follower. » : le verbe est celui des fenêtres de cartes,
    # mais ici il désigne une UNITÉ DU PLATEAU (Fading Memories,
    # Disintegrate : « Pick a unit. The next time it takes damage, kill
    # it. »). L'effet qui suit ne se lit pas avec nos motifs ancrés, donc
    # on ne saurait pas dans quel camp cliquer. Les formes qui ouvrent une
    # vraie fenêtre (« Pick 1 of 3 », « Pick a Moon Weapon to create in
    # hand », « Pick a follower from the top 4 cards ») sont reconnues
    # AVANT ce refus — voir CARD_WINDOWS.
    (r"\bpick (a|an|one|\d+)\b",    "ouvre un choix de carte",                     True),
    (r"\bchoose\b",                 "ouvre un choix de carte",                     True),
    (r"\byou may\b",                "effet optionnel",                             False),
    (r"\bstrikes?\b",               "combat dirigé, deux cibles",                  False),
    (r"^stop a ",                   "contresort, cible la pile",                   False),
    # UNE TRANSFORMATION NOMME UN JETON, PAS UNE SECONDE CIBLE
    # (08/11/2026). Il y avait ici un refus barrant le mot « transform »
    # lui-même, motif « deux cibles » — et ce motif était un contresens :
    # « Transform a unit into a 3|3 Mini-Minitee and Silence it. »
    # (Minimorph, 05BC001) ne demande qu'UN clic, sur « a unit » ; le
    # Mini-Minitee est ce que l'unité DEVIENT.
    #
    # Mesuré sur la base entière avant de le retirer : 23 textes
    # contiennent « into a/an », et `_scan_targets` n'y compte JAMAIS un
    # nom de jeton pour une cible — aucun des Mini-Minitee, Squirrel,
    # Alpha Wildclaw ni des neuf jetons d'Ambush n'apparaît dans les
    # marqueurs. Un seul marqueur suit directement un « into », et ce
    # n'est pas un jeton : le « another follower » de Curious Changelings
    # (06BC042, « When an allied follower transforms into another
    # follower »), une clause de DÉCLENCHEUR sur une unité — donc lue par
    # `classify_unit_play`, qui n'y voit aucun « Play: » et ne rend rien.
    # ATTENTION, DEUX CORRECTIONS DU 08/11 (relecture adverse) : ce
    # commentaire nommait ici Hextech Transmogulator et The Wingsgiving.
    # Ni l'un ni l'autre ne place de marqueur juste après « into » — le
    # second marqueur du Transmogulator arrive après « into an exact copy
    # of », et les deux marqueurs du Wingsgiving sont ses « an ally »,
    # son « into » étant en fin de phrase. Ce qu'il fallait retenir d'eux
    # tient debout : le Transmogulator demande DEUX vrais clics et reste
    # refusé par le compte générique, le Wingsgiving est déjà refusé pour
    # « pick » — un filtre « into » dans `_scan_targets` coûterait le
    # premier sans rien rapporter.
    # Le champ `description` de la base le confirme en toutes lettres :
    # TOUS les jetons de transformation y portent un lien
    # <AssociatedCard> (« a 3|3 Mini-Minitee », « an Alpha Wildclaw », les
    # neuf jetons d'Ambush), et « another follower » est du texte nu. Le
    # compteur de cibles n'a donc jamais eu tort ; c'est ce refus-ci qui
    # nommait mal ce qu'il barrait.
    #
    # CE QUE ÇA COÛTAIT, et c'est le piège du 06/11 à l'identique :
    # `actions.is_dead_weight` appelle `classify_card(card)` SANS
    # argument, donc `restricted=True` MÊME en mode par défaut. Les 18
    # cartes touchées étaient du « fardeau pur » — premières défaussées,
    # dernières renforcées, dernières choisies dans une fenêtre — dont
    # Minimorph, Whimsy!, et jusqu'à Go Hard (03SI016), un simple
    # « Drain 1 from a unit » dont le texte ne mentionne « transform »
    # que pour ses propres copies dans le deck. Le mode par défaut, lui,
    # ne change pas d'un plan : ce refus-là était de PRUDENCE, il y
    # tombait déjà.
    #
    # La prudence reste entière sans lui : TRANSFORM est dans HARMFUL,
    # donc une transformation visant notre camp (Wildclaw's Ferocity,
    # Mystifying Magician) est toujours refusée en mode prudent par le
    # garde-fou « néfaste sur notre propre unité ».
    (r"\bcaptures?\b",              "deux cibles",                                 False),

    # ---- interfaces qu'on ne sait pas piloter -------------------------
    # À distinguer des désignations DANS LA MAIN (HAND_PICKS) et des
    # FENÊTRES DE CARTES (CARD_WINDOWS : Manifest, Invoke, Predict,
    # Tellstones...), qui sont pilotées depuis le 02/09/2026 — l'API
    # rapporte bel et bien les cartes de ces fenêtres, Ewan l'a vu en jeu
    # sur les choix de version. Ce qui reste ici, c'est ce qui demande
    # une VALIDATION ou un choix dont on ne voit rien.
    #
    # « up to N » laisse le nombre à notre discrétion : le jeu attend donc
    # une VALIDATION en plus des clics, et ce bouton n'est pas calibré.
    #
    # « ANY NUMBER OF » A QUITTÉ CETTE LISTE LE 10/11/2026, et le bouton
    # de validation est la raison : c'est l'ORBE DE TOUR, que le projet
    # sait lire et cliquer depuis toujours. Voir `_FREE_DESIGNATION_RX`
    # et `SpellPlan.free_designation` plus bas — le refus est devenu un
    # geste de plus, pas une incapacité.
    (r"\bdiscard up to \d+\b",      "défausse optionnelle : demande une validation", True),
    (r"\bupdraft up to \d+\b",      "Updraft optionnel : demande une validation",  True),
    # « You may spend 8 mana to play me as Naganeka » (les huit armes
    # Darkin) : le client demande LAQUELLE des deux versions poser. Le
    # choix PILOTÉ, lui, est reconnu avant ce refus — voir
    # `play_as_options` : il est ancré en tête de clause, ce qui distingue
    # « Play me as A or B » (obligatoire, deux cartes nommées) de cette
    # option payante.
    (r"\bplay me as\b",             "ouvre un choix de version de la carte",       True),

    # CIBLE SOUS CONDITION INVISIBLE. « Deal 5 to an enemy that attacked
    # this round or is Stunned » (Astro-Pong / Paddle Star, 03MT093, vu en
    # jeu le 02/09/2026 sur des cibles non étourdies), Falling Star
    # (07MT001), Ravenous Flock (« if it's damaged or Stunned », 02NX009).
    # Le jeu REFUSE le clic sur une unité qui ne remplit pas la condition,
    # et le sort reste en l'air. Or rien dans l'état lu ne dit qu'une
    # unité est étourdie ni qu'elle a attaqué ce round : l'API ne rapporte
    # que des rectangles, et le bot ne suit pas les rounds. Une condition
    # qu'on ne peut pas vérifier est une interface hors de portée — dans
    # les deux modes — et non de la prudence. (« damaged » seul, lui, se
    # lit dans les PV affichés : cf. SpellPlan.target_condition.)
    # « Stun an enemy. If it's already Stunned, deal 6 instead » ne matche
    # PAS : c'est un bonus, la cible reste libre.
    (r"\b(that|who|which) attacked this round\b", "cible sous condition invisible (a attaqué ce round)", True),
    (r"\bor is stunned\b",           "cible sous condition invisible (étourdie)",   True),
    (r"\bif it'?s (damaged or stunned|stunned)\b", "cible sous condition invisible (étourdie)", True),
    # Voir MARKED_TARGET plus haut : le marquage est accordé EN JEU,
    # donc invisible à l'API. Beast's Frenzy (98SB047), 11/11/2026.
    (MARKED_TARGET, "cible sous condition invisible (marquée)", True),
]

# ============================================================
# DÉSIGNATION DANS LA MAIN
# ============================================================
# Certains effets demandent de cliquer une carte de NOTRE MAIN, pas une
# unité du plateau : « Updraft 1 », « Discard 1 to draw 1 », « Equip me
# with an equipment ... from hand ». Aucun marqueur de SINGULAR_TARGETS
# ne les voit — ils ne nomment aucune cible — si bien qu'ils passaient
# pour des effets automatiques. La carte était posée, puis la partie
# restait figée sur un choix que rien n'honorait (98FR019, observé en
# jeu).
#
# C'est une interface PILOTABLE, contrairement à Manifest : les cartes de
# la main sont dans l'état rapporté par l'API, avec leur position. On sait
# donc quoi cliquer, et `actions.choose_hand_sacrifice` décide laquelle.
#
# Le nombre est lu dans le texte quand il y est (« Updraft 2 »), sinon
# c'est un. Le marqueur « ... in hand » de SINGULAR_TARGETS vaut lui aussi
# une désignation : « Grant Barrier to an ally in hand » demande bien un
# clic dans la main.

# Trois choses à savoir avant de cliquer, et pas une seule :
#   COMBIEN de cartes désigner ;
#   de QUEL TYPE — « Grant an ally in hand » veut une unité, cliquer un
#     sort ne déclenche rien et le jeu reste en attente ;
#   dans QUEL SENS — « Discard 1 » est un coût, on donne la pire ; « Grant
#     an ally in hand +3|+3 » est un cadeau, on vise la meilleure. Se
#     tromper de sens, c'est renforcer la carte qu'on allait jeter.
#
#   ET UNE QUATRIÈME, DÉCOUVERTE EN JEU SUR ELORA (98PZ007) : la carte
#   désignée QUITTE-T-ELLE LA MAIN ? « Discard 1 » la retire, « Create an
#   exact copy of a spell in hand » la laisse exactement où elle est. C'est
#   ce qui distingue un clic réussi d'un clic raté, et s'être trompé
#   revenait à annuler une pose parfaitement résolue (cf.
#   actions.designate_in_hand).
#
#             motif                            nombre  type         cadeau  consommée
HAND_PICKS = [
    (r"\bupdraft (\d+)\b",                     None,  "any",        False,  True),
    (r"\bdiscard (\d+)\b",                     None,  "any",        False,  True),
    (r"\bdiscard a card\b",                    1,     "any",        False,  True),
    # « Equip me with an equipment ... from hand », mais aussi « Equip an
    # ally with an equipment in hand » et « ... or equip it with an
    # equipment in hand » : c'est le même clic, et l'équipement PART de la
    # main dans les trois cas. Le mot « hand » est exigé pour ne pas
    # confondre avec un équipement créé de toutes pièces.
    (r"\bequip\b[^.]*\ban equipment\b[^.]*\b(?:in|from) hand\b",
                                               1,     "equipment",  True,   True),
    # « To play, place a card from hand into your deck » : la carte s'en
    # va, même si aucun verbe de défausse ne le dit.
    (r"\bplace a card from (?:your )?hand\b", 1,     "any",        False,  True),
]

_HAND_PICK_RX = [
    (re.compile(p, re.I), n, t, b, c) for p, n, t, b, c in HAND_PICKS
]

# Le type demandé, quand la phrase le nomme : « an ally in hand », « a
# spell in hand »... « card » ne contraint rien, c'est n'importe laquelle.
HAND_NOUN_TYPES = {
    "ally": "unit", "unit": "unit", "follower": "unit", "champion": "unit",
    "card": "any", "spell": "spell", "equipment": "equipment",
}
_HAND_NOUN_RX = re.compile(
    r"\ban? (ally|unit|follower|champion|card|spell|equipment) (?:in|from) hand\b", re.I
)
# Deux « ou » qui n'en sont pas. Une parenthèse ÉNUMÈRE : « a card of the
# same type (unit, spell, landmark or equipment) » ne propose rien. Un
# comparatif SEUILLE : « an equipment that costs 2 or less » non plus. Les
# retirer avant de chercher un vrai choix évite de refuser des cartes
# parfaitement jouables.
_PARENTHESES_RX = re.compile(r"\([^)]*\)")
_COMPARATIVE_RX = re.compile(
    r"\b(\d+|more|less|fewer|greater) or (more|less|fewer|greater)\b", re.I
)
# « either » sans « or » reste un choix : « draw a card that costs either
# more or less » en est un, une fois le comparatif retiré.
_CHOICE_RX = re.compile(r"\beither\b|\bor\b", re.I)


# ============================================================
# PRÉAMBULES : NI L'EFFET, NI LA CIBLE
# ============================================================
# « If an ally died this round, deal 4 to a unit. » — Black Spear
# (01SI034), vu en jeu le 20/08/2026 lancé sur NOS PROPRES UNITÉS.
#
# Deux dégâts en un, et le second est le pire :
#
# 1. LA CONDITION N'EST PAS UNE CIBLE. « an ally » du début décrit ce qui
#    doit s'être produit, pas ce qu'il faut cliquer. Compté comme
#    marqueur, il en faisait DEUX — et sans restrictions on gardait le
#    premier, donc « allié ».
#
# 2. LA CONDITION AVEUGLE LA DÉTECTION D'EFFET. Les motifs de
#    EFFECT_PATTERNS sont ancrés au début (`^deal`, `^kill`...) : tout ce
#    qui les précède les empêche de matcher. L'effet devient « AUTRE »,
#    qui n'est pas classé nuisible — et un AUTRE sur notre camp vise notre
#    plus petite unité, un AUTRE sur « a unit » notre plus GROSSE. Le sort
#    de dégâts se retournait donc contre nous deux fois plutôt qu'une.
#
# On retire donc ces clauses avant toute analyse. Elles sont peu
# nombreuses (une vingtaine de sorts) mais elles cassent tout ce qui
# suit. « I cost N less » est du même genre : une remise, pas un effet, et
# elle s'intercale exactement au même endroit.
# Une condition n'est pas forcément en tête : « Stun an enemy. If it's a
# follower, Stun it again at the next Round Start. » (Sky Charge) en place
# une au milieu, et son « a follower » comptait comme une SECONDE cible —
# un sort à un seul clic passait pour un sort à deux.
_CONDITION_WORDS = r"if|once|when|whenever|while|unless"
_PREAMBLE_RX = [
    # Une subordonnée de condition : elle dit QUAND l'effet se produit,
    # jamais sur QUOI cliquer.
    re.compile(rf"\b(?:{_CONDITION_WORDS})\b[^,.]*[,.]\s*", re.I),
    # Une remise n'est pas un effet : « Once you've Equipped an ally this
    # game, I cost 2 less. Give an ally SpellShield. » ne demande qu'un
    # clic, mais en comptait deux.
    #
    # « ... CE ROUND » EST LA MÊME REMISE (06/11/2026). Sans ces deux mots,
    # « When drawn, I cost 2 less this round. Deal 3 to a unit. » (Gotcha!,
    # 02PZ006) gardait sa remise en tête, l'effet n'était plus en position
    # 0, et trois dégâts partaient sur une de NOS unités.
    #
    # ET LE POINT FINAL EST FACULTATIF, parce que la règle précédente l'a
    # parfois déjà mangé : « I cost 2 less if you have a Tristana or if
    # you've played cards from 4+ regions this game. Deal 3 to a unit. »
    # (Buster Shot, 05BC132) laisse « I cost 2 less Deal 3 to a unit. »
    # une fois la condition retirée — la remise n'a plus de point, elle
    # survivait, et trois dégâts partaient sur une de NOS unités.
    re.compile(r"\bi cost \d+ (?:less|more)(?: this round)?[.,]?\s*", re.I),
]

# ============================================================
# LA CLAUSE QUI PORTE LA CIBLE
# ============================================================
# `EFFECT_PATTERNS` est ancré en tête (`^deal`, `^kill`…) et doit le
# rester : desserrer l'ancrage ferait déteindre l'effet d'une clause sur
# la cible d'une autre (« Grant a unit +2|+2. When it dies, deal 3 to the
# enemy Nexus. » deviendrait un sort de dégâts). Mais l'ancrer sur le
# TEXTE ENTIER suppose que l'effet est la première chose écrite, ce qui
# est faux dès qu'une clause le précède.
#
# Mesuré le 06/11/2026 sur la base, par le chemin que le bot emprunte
# vraiment : ONZE cartes dont un préambule masquait un effet hostile
# connu — Scrapshot (« Toss 3. Deal 7 to a unit. »), Monster Harpoon
# (« Plunder: I cost 2 less. Deal 5 to a unit. »), Undergrowth, les Rite
# of the Arcane, Unworthy Soul, Gotcha!, Thermogenic Beam. Toutes
# rangées en « AUTRE », donc tirées sur NOS unités.
#
# On garde donc l'ancrage, et on l'applique à la clause qui porte la
# cible : c'est elle qui dit ce qu'on fait à ce qu'on clique.
_CLAUSE_SPLIT = ".;"
# « Play: », « Plunder: », « Flow: », « I-II: »… Le déclencheur dit QUAND,
# jamais QUOI. (Les unités passent déjà par `extract_play_clause` ; ceci
# vaut pour les sorts, compétences et reliques qui en portent aussi.)
_TRIGGER_LABEL_RX = re.compile(r"^[A-Za-z][\w'’ -]{0,24}:\s*")
# Un COÛT à payer avant l'effet. Les formes relevées dans la base sont
# peu nombreuses et toutes nomment ce qu'on sacrifie de NOTRE côté — on
# les nomme précisément plutôt que d'attraper tout « Destroy ... to »,
# qui avalerait « Destroy a unit's equipment and deal 2 to it. ».
_COST_CLAUSE_RX = re.compile(
    r"^(?:to play(?: me)?[^.]*\.\s*"
    r"|destroy (?:an allied landmark|one of your mana gems)"
    r"(?: or one of your mana gems)? to\s+)",
    re.I,
)


def effect_clause(core: str) -> str:
    """
    La clause sur laquelle lire l'effet : celle qui porte la cible.

    Sans marqueur de cible, c'est le texte entier — exactement le
    comportement d'avant, pour tout ce qui ne désigne rien.
    """
    debut = None
    for regex, _side in _TARGET_RX:
        found = regex.search(core)
        if found and (debut is None or found.start() < debut):
            debut = found.start()
    if debut is None:
        return core

    coupe = max((core.rfind(s, 0, debut) for s in _CLAUSE_SPLIT), default=-1)
    clause = core[coupe + 1:].strip()

    # Étiquettes puis coût, en boucle : « Plunder: To play, discard 1.
    # Deal 5 to a unit. » enchaîne les deux.
    previous = None
    while previous != clause:
        previous = clause
        clause = _TRIGGER_LABEL_RX.sub("", clause, count=1).strip()
        clause = _COST_CLAUSE_RX.sub("", clause, count=1).strip()
    return clause or core


# « Set a unit's stats to 1|6 this round. » (Défense paniquée, 05BC209).
# Le seul effet de la base dont le CAMP ne se déduit pas du verbe : il
# réécrit les statistiques, donc il aide ou il nuit selon qui on vise.
_STAT_OVERRIDE_RX = re.compile(r"\bset\b[^.]*?\bstats? to (\d+)\|(\d+)", re.I)


def stat_override(clause: str):
    """Les statistiques que cet effet IMPOSE à sa cible, ou None."""
    found = _STAT_OVERRIDE_RX.search(clause or "")
    return (int(found.group(1)), int(found.group(2))) if found else None


def strip_preamble(text: str) -> str:
    """
    Retire les clauses qui ne disent ni quoi faire ni sur quoi.

    Toutes les occurrences, pas seulement celles de tête, et en boucle :
    « If you Behold a Titanic unit, I cost 3 less. Deal 7 to a unit. » en
    enchaîne deux, et n'en retirer qu'une laisse le sort illisible.
    """
    previous = None
    while previous != text:
        previous = text
        for regex in _PREAMBLE_RX:
            text = regex.sub("", text).strip()
    return text


def opens_a_second_choice(text: str) -> bool:
    """Reste-t-il un vrai « ou » une fois les faux amis écartés ?"""
    reduced = _COMPARATIVE_RX.sub("", _PARENTHESES_RX.sub("", text))
    return bool(_CHOICE_RX.search(reduced))


def hand_pick_spec(text: str, effect: str = "AUTRE"):
    """
    Ce que cet effet demande de désigner dans la main, ou None.

    Renvoie (nombre, type, cadeau, consommée). `cadeau` dit le SENS de la
    désignation : vrai quand la carte désignée en profite, faux quand elle
    est le prix à payer. `consommée` dit si elle QUITTE LA MAIN — c'est une
    question différente, et les deux réponses ne se déduisent pas l'une de
    l'autre : « Equip me with an equipment from hand » est un cadeau pour
    l'unité équipée mais l'équipement part bel et bien.
    """
    for regex, fixed, kind, boon, spent in _HAND_PICK_RX:
        match = regex.search(text)
        if match:
            if fixed is not None:
                return fixed, kind, boon, spent
            captured = match.group(1)
            picks = int(captured) if captured and captured.isdigit() else 1
            return picks, kind, boon, spent

    noun = _HAND_NOUN_RX.search(text)
    if noun:
        # Le sens vient de l'effet : « Obliterate a unit in hand » est un
        # coût, « Grant an ally in hand +3|+3 » est un renfort.
        #
        # Et c'est le même critère qui dit si la carte s'en va : seuls les
        # effets NÉFASTES la retirent de la main. Un renfort la laisse en
        # place (« Grant an ally in hand +3|+3 »), une copie aussi
        # (« Create an exact copy of a spell in hand » : on en a deux
        # après, pas zéro).
        return (
            1,
            HAND_NOUN_TYPES.get(noun.group(1).lower(), "any"),
            effect not in HARMFUL,
            effect in HARMFUL,
        )
    return None

EFFECT_PATTERNS = [
    (r"^deal (\d+)",                            "DAMAGE"),
    # « Deal damage equal to my Power to a unit » (Banana Blaster, 06BC051,
    # 06/09/2026 : 25 min de boucle) : des dégâts SANS chiffre. Le montant
    # reste None ici ; pour un pouvoir « equal to my Power », c'est
    # l'appelant qui connaît la carte (actions.unit_play_plan).
    (r"^deal damage\b",                         "DAMAGE"),
    # « Transform a unit into a 3|3 Mini-Minitee » (Minimorph, 05BC001) :
    # on ne transforme jamais un allié pour son bien, c'est un malus.
    (r"^transform\b",                           "TRANSFORM"),
    (r"^drain (\d+)",                           "DRAIN"),
    (r"\bobliterate\b",                         "KILL"),
    (r"^kill\b",                                "KILL"),
    (r"^recall\b",                              "RECALL"),
    (r"^stun\b",                                "STUN"),
    (r"^silence\b",                             "SILENCE"),

    # ---- quatre verbes franchement hostiles (06/11/2026) --------------
    # Mesurés sur la base : onze cartes les portaient sans que le
    # vocabulaire les connaisse, donc rangées en « AUTRE » — et un AUTRE
    # sur « a unit » part sur un ALLIÉ. Le bot endormait sa propre unité
    # (Blooming Bud), se capturait lui-même (Claim, Captain Arrika),
    # détruisait son propre équipement (Fracture, Quietus, Heavy Metal,
    # Explorer's Malfunction, Silence and Suppress, Puzzling Signposts)
    # et renvoyait sa propre unité dans son deck (Sunk Cost).
    #
    # L'ÉQUIPEMENT AVANT LE RESTE : « Destroy a unit's equipment and deal
    # 2 to it » (Heavy Metal) ne doit pas être lu comme un simple
    # « destroy », et sa clause de dégâts n'est pas en tête.
    (r"^destroy (?:a|an|the)\b[^.]*?\bequipment\b", "DESEQUIP"),
    (r"^sleep\b",                               "SLEEP"),
    (r"^capture\b",                             "CAPTURE"),
    (r"^place\b[^.]*?\binto (?:its|their) deck\b", "BANISH"),

    # GLOOM EST UN MALUS DÉGUISÉ EN DON, et c'est la base de cartes qui
    # le dit, pas une supposition (relevé le 06/11/2026) : il n'est
    # jamais accordé qu'à l'adversaire — « Grant the strongest ENEMY
    # Gloom » (Vex), « Grant ENEMIES 2 Gloom » (Crowstorm, Fiddlesticks),
    # « Grant AN ENEMY 2 Gloom » (Reap) — et sur Blighted Battleaxe c'est
    # une punition (« If my bearer didn't attack this round, grant it
    # Gloom »). Sans cette ligne, « Grant a unit Gloom » (Allay, Vex's
    # Glare) passait par `^grant` → BUFF → notre plus grosse unité.
    # Même famille que « give an enemy Vulnerable », déjà connue plus bas.
    (r"^(?:give|grant)\b[^.]*\bgloom\b",        "GLOOM"),
    (r"^(give|grant)\b",                        "BUFF"),
    # « Activate an ally's Daybreak effect. » (Morning Light, 03MT082).
    # Déclencher l'effet d'un allié ne lui a jamais nui. Relevé le
    # 06/11/2026 : sans ce verbe, trois bons sorts tombaient en « AUTRE »
    # — et en `--prudent`, un AUTRE visant notre propre camp est refusé,
    # donc ils n'étaient plus lancés du tout.
    (r"^activate\b",                            "ACTIVATE"),
    (r"^heal\b",                                "HEAL"),
    (r"^(create|summon|draw|refill|plant)\b",   "GENERATE"),
    # « To play, spend all your mana. Deal that much to a unit. »
    # (Thermogenic Beam, 01PZ027) : des dégâts dont le montant est le
    # mana dépensé. Comme « deal damage equal to my Power », le chiffre
    # reste inconnu ici — mais le CAMP, lui, ne fait aucun doute. Rangé
    # après GENERATE pour ne jamais passer devant une forme chiffrée.
    (r"^deal that much\b",                      "DAMAGE"),
]

_TARGET_RX = [(re.compile(p, re.I), s) for p, s in SINGULAR_TARGETS]

# ============================================================
# CE QUE LE MARQUEUR EXIGE DE LA CIBLE
# ============================================================
# Un adjectif (ou un substantif) devant le marqueur ne dit pas toujours
# que le camp : il peut RESTREINDRE ce que le jeu accepte sous le clic.
# Chaque entrée ci-dessous est une condition que le bot sait VÉRIFIER —
# c'est toute la ligne de partage avec les « conditions invisibles » de
# REFUSALS (« that attacked this round », « or is Stunned »), qui ne se
# lisent nulle part et valent refus.
#
#   damaged    « a damaged ally » (Courage de Braum, 01FR046) : se lit
#              dans les PV AFFICHÉS, donc par OCR — c'est la seule qui
#              coûte une lecture d'écran (cf. le test `== "damaged"`
#              d'`actions.spell_is_castable`, à ne surtout pas élargir).
#              Vu en jeu le 02/09/2026 : le sort partait sur des alliées
#              intactes.
#   attacking  « Stun an ATTACKING enemy » (Tempête d'acier, 01IO046),
#              remarqué par Ewan le 06/11/2026. « Qui attaque » se lit
#              directement : ce sont `attack_row` et `enemy_attack_row`,
#              deux zones que l'API rapporte à chaque lecture.
#   follower   « Charm an enemy FOLLOWER » (Beckoning Gaze, 98SB015),
#   champion   « Give an allied CHAMPION ... » (Chronoshift, 04SH030).
#              Relevé dans `logs/` le 10/11/2026 : le substantif servait
#              à lire le CAMP et sa restriction était jetée, si bien que
#              Beckoning Gaze visait Karma — un champion — et restait en
#              l'air. `supertype` vient de card_sets et
#              `BoardCard.is_champion` le dit depuis le 03/09/2026 :
#              aucune lecture d'écran n'est en jeu.
_MARKER_CONDITIONS = (
    ("damaged",   re.compile(r"\bdamaged\b", re.I)),
    ("attacking", re.compile(r"\battacking\b", re.I)),
    ("follower",  re.compile(r"\bfollowers?\b", re.I)),
    ("champion",  re.compile(r"\bchampions?\b", re.I)),
)


def target_condition_of(core: str, spans=()) -> str:
    """
    La condition que le MARQUEUR porte, ou "" — une seule à la fois.

    `spans` sont les positions des marqueurs retenus par `_scan_targets`.
    ON LIT LA CONDITION SUR LE MARQUEUR, PAS SUR LA PHRASE, et ce n'est
    pas un raffinement : « Kill an ally to draw a Champion » (Rite of
    Calling, 04SH121T2) ne garde qu'un marqueur — « an ally », le
    champion étant PIOCHÉ, écarté par `_DRAWN_RX`. Lire « champion »
    dans la phrase entière y filtrerait NOS alliés sur les champions, un
    clic que le jeu n'attend pas. Pour les deux conditions d'avant
    (« damaged », « attacking ») le marqueur contient déjà l'adjectif :
    mesuré sur les 2898 cartes, aucun plan ne change.

    DEUX MARQUEURS QUI NE DISENT PAS LA MÊME CHOSE N'EN FONT AUCUNE :
    « Deal 2 to a champion or 4 to a follower » (Weight of Judgment,
    04SH004) est UN clic qui accepte les deux, et c'est `amount_champion`
    qui s'en occupe. Restreindre serait inventer un refus.

    Sans marqueur, pas de condition : il n'y a rien à restreindre.
    """
    fragments = [core[start:end] for start, end in spans]
    if not fragments:
        return ""
    found = {name for fragment in fragments
             for name, regex in _MARKER_CONDITIONS if regex.search(fragment)}
    if len(found) != 1:
        return ""
    return found.pop()


# « ANY NUMBER OF » : LE NOMBRE EST À NOUS, DONC LE JEU ATTEND UNE
# VALIDATION (10/11/2026, fait de jeu d'Ewan).
#
# Vladimir (01NX006), « Play: Deal 1 to any number of allies to deal that
# much to an enemy » : le jeu surligne nos alliés, affiche « Infligez
# 1 pt(s) de dégâts », et n'en exige AUCUN — on valide à zéro et le
# champion est posé sans son effet. Ewan, mot pour mot : « on clique sur
# l'ennemi et on clique sur le bouton bleu à droite de la page ».
#
# CE BOUTON BLEU EST L'ORBE DE TOUR, et c'est ce qui fait tomber le refus
# écrit le 06/11 (« ce bouton n'est pas calibré »). Mesuré sur les deux
# captures que le bot a gardées de ses propres blocages —
# `screenshots/bloque_ATTACKING_20261106_105937.png` et
# `..._111227.png`, les deux poses de Vladimir du log
# `logs/challenges_20261106_105419.log` : l'orbe y est BLEUE et porte
# « PASSER », à l'endroit exact de `game_state.TURN_ORB_REGION`, c'est-à-
# dire le point que `actions.TURN_BUTTON_RATIO` clique déjà pour valider
# un sort ou finir un tour. Aucune coordonnée nouvelle n'est inventée.
#
# Le compte des marqueurs, lui, ne change pas d'un pouce : « any number
# of allies » n'est pas un marqueur (pas de nombre écrit, donc pas de
# pluriel COMPTÉ — cf. `_COUNTED_PLURAL_RX`), et il ne reste que « an
# enemy ». Le plan rendu est donc « DAMAGE sur ennemi, un clic », plus
# ce drapeau qui dit à `actions` de valider derrière.
#
# À NE PAS CONFONDRE AVEC « up to N », qui reste refusé : là, les clics
# portent sur la MAIN (défausse, Updraft), une interface dont on ne sait
# pas lire les cartes au moment du choix — ce n'est pas le bouton qui
# manquait.
_FREE_DESIGNATION_RX = re.compile(r"\bany number of\b", re.I)


_REFUSE_RX = [(re.compile(p, re.I), r, hors) for p, r, hors in REFUSALS]
_EFFECT_RX = [(re.compile(p, re.I), e) for p, e in EFFECT_PATTERNS]
_STAT_BUFF_RX = re.compile(r"\+\d+\|\+\d+")
_AMOUNT_RX = re.compile(r"^(?:deal|drain|heal) (\d+)", re.I)
# Voir `_find_targets` : une deuxième cible qui ne répète pas le nom du
# camp (« Stun another. »), et le faux ami du combat (« one after
# another ») qu'on ne veut surtout pas confondre avec elle.
_BARE_ANOTHER_RX = re.compile(r"\banother\b", re.I)
# « Frostbite 2 enemies », « Deal 1 to 3 enemies », « Give two allies +1|+0 » :
# N clics du même genre, sans « another ». « all enemies » n'a pas de
# nombre et reste sans cible ; « up to N » demande une validation, on ne
# le prend pas.
# « 2 allies in hand » (Purifying Flames) et « the top 3 units in your
# deck » (Shared Spoils) ne sont pas des clics de plateau : exclus.
_COUNTED_PLURAL_RX = re.compile(
    r"(?<!up to )\b(\d+|two|three|four) (enemies|allies|units|followers)\b"
    r"(?! in (?:your )?(?:hand|deck))", re.I
)
_COUNT_WORDS = {"two": 2, "three": 3, "four": 4}
_PLURAL_SIDES = {"enemies": "ENEMY", "allies": "ALLY", "units": "ANY_UNIT",
                 "followers": "ANY_UNIT"}
_STRIKE_RX = re.compile(r"\bstrikes?\b", re.I)
# LE VERBE QUI PRÉCÈDE IMMÉDIATEMENT UN MARQUEUR DIT S'IL EST SUR LE
# PLATEAU. « Draw a champion » puise dans le deck : il n'y a rien à
# cliquer. Mesuré le 06/11/2026 : c'est le SEUL signal fiable — chercher
# « in your deck » ou « in hand » APRÈS le marqueur attrape six faux
# positifs sur douze candidats, parce que la mention porte presque
# toujours sur une AUTRE carte (« Deal 2 to a unit. Create a Ziggs in
# your deck. », « Recall an ally to create a Flawless Duet in hand »).
_DRAWN_RX = re.compile(r"\b(?:draw|search for)\s+$", re.I)
# ET C'EST LE JEU QUI TIRE QUAND LE TEXTE DIT « RANDOMLY » (08/11/2026).
# « Deal 2 randomly to an enemy or the enemy Nexus » (Ebb, 05BW006, plus
# Nami's Ebb 05BW005T2 et Ebb and Flow 05BW006T1) : le marqueur est là,
# la cible non — le client ne demande rien et résout seul. Même famille
# que « a random ally », déjà exclue dans SINGULAR_TARGETS ; la seule
# différence est que l'adverbe se place AVANT le verbe de destination,
# donc il se lit dans ce qui PRÉCÈDE le marqueur, comme « draw ».
#
# Sans ce garde, le marqueur « or the enemy Nexus » ajouté le même jour
# matche leur texte à la lettre et leur offrirait un clic sur le nexus
# que le jeu refuserait.
#
# TROIS CARTES, MAIS DEUX SEULEMENT SONT JOUÉES SANS CLIC — le
# commentaire d'origine promettait les trois, et c'était faux pour la
# dernière (relevé et mesuré le 09/11/2026) :
#
#     05BW006    Ebb           DAMAGE/NONE   0 clic   (les deux modes)
#     05BW005T2  Nami's Ebb    DAMAGE/NONE   0 clic   (les deux modes)
#     05BW006T1  Ebb and Flow  DAMAGE/ALLY   1 clic   (restrictions levées)
#
# Ebb and Flow est le seul cas MIXTE de la base : « Deal 2 randomly to an
# enemy or the enemy Nexus AND heal an ally or your Nexus 2. » Le tir est
# au hasard, mais le SOIN se désigne — il reste donc un marqueur, celui
# de l'allié, et le clic part sur lui. Ce que `_RANDOM_RX` lui a vraiment
# donné, ce n'est pas l'absence de clic : c'est de passer de DEUX
# marqueurs (donc « 2 cibles à cliquer », refus d'incapacité) à UN SEUL,
# donc d'être jouable. En mode prudent elle reste refusée, parce que
# l'effet lu sur la clause est le DEAL du début (cf. la dette nommée dans
# `test_un_sort_qui_peut_frapper_le_nexus_adverse_le_vise` : `effect_clause`
# coupe sur « . » et « ; », jamais sur un « and »).
_RANDOM_RX = re.compile(r"\brandomly (?:to|at)\s+$", re.I)

# ============================================================
# NOTRE NEXUS EST UNE CIBLE, LUI AUSSI (10/11/2026)
# ============================================================
# LE MIROIR EXACT DU CHANTIER « AN ENEMY OR THE ENEMY NEXUS » (08/11).
# Ce jour-là on a appris que « an enemy OR the enemy Nexus » est UN clic
# avec DEUX endroits où tomber, dont le second ne quitte jamais le
# plateau. Le symétrique n'avait pas été fait, et il coûtait le même
# prix : « Heal an ally or your Nexus 3 » rendait « aucun allié en jeu »
# sur un banc vide, et le soin était abandonné dans l'état même où il
# vaut le plus cher.
#
# NEUF CARTES de la base, recomptées : Health Potion (01IO004), Ritual of
# Renewal (01IO001), Guiding Touch (03MT051), Starshaping (03MT084),
# Explorer's Refreshments (08BW028T4), Flow (05BW006T2), Ebb and Flow
# (05BW006T1), et deux UNITÉS dont le « Play: » dit la même chose —
# Kindly Tavernkeeper (01FR050) et Smooth Mixologist (07IO019). Toutes
# disent « heal ... » ; on ne reconnaît pourtant pas le verbe, on lit le
# marqueur de CAMP, comme en face.
#
# POURQUOI UN DRAPEAU ET PAS UN `Targeting` DE PLUS : le côté adverse
# avait déjà `Targeting.ANYTHING` (« unité ou nexus ») sous la main ; ce
# côté-ci n'a aucun équivalent, et en créer un ferait rater notre camp à
# tout le code qui teste `is Targeting.ALLY` — `riposte.py`,
# `actions.equipment_plan`, les refus de prudence. Le drapeau ne change
# RIEN tant que `gift_to_ally` trouve quelqu'un.
#
# LE REPÈRE EST ANCRÉ SUR LE MARQUEUR QUE `_scan_targets` A RETENU, et
# c'est tout l'intérêt : il hérite ainsi, sans les réécrire, des deux
# garde-fous du chantier d'en face — « a random ALLY » (le jeu choisit)
# et la nullification par « randomly to » / « draw ». Son préfixe est
# celui du marqueur ordinaire, et PAS UN QUALIFICATIF DE PLUS : un
# « n'importe quels deux mots » permissif avalerait « a random ally or
# your Nexus », exactement ce que Ricochet et Volibear ont failli coûter
# en face.
_OUR_NEXUS_RX = re.compile(r"an? (?!random\b)(?:\w+ ){0,2}ally or your nexus\b", re.I)

# « S'IL N'Y A PLUS D'ENNEMI, JE VISE LE NEXUS » (10/11/2026).
# Final Spark (01DE042T3), Ace in the Hole (98PZ004), Javelin Toss
# (07SH013T2) — et elles seules. Le sort se résout SEUL quand le plateau
# adverse est vide, mais le MÊME texte exige un clic dès qu'un ennemi est
# là : aucune lecture du texte ne peut trancher, puisque la réponse est
# dans l'instantané. Le classement dit donc les deux, et `actions` tranche.
#
# ON LIT CE REPÈRE SUR LE TEXTE ENTIER, PAS SUR `core` : `strip_preamble`
# retire justement les subordonnées de condition, donc « If there are no
# enemies, » a déjà disparu quand le ciblage se décide. Les refus se
# lisent eux aussi sur le texte entier, pour la même raison.
#
# LE COUPLE COMPTE, PAS LA CONDITION SEULE : il faut « plus d'ennemis »
# ET « le nexus à la place », dans la même phrase (`[^.]*`). Sans la
# seconde moitié, on ne sait pas ce que le jeu fait d'un plateau vide.
# À NE PAS CONFONDRE avec « If it's DEAD OR GONE, deal N to the enemy
# Nexus instead » (Cannon Barrage, Annie, Threaded Volley, Relentless
# Storm... quatorze textes de la base contiennent « Nexus instead ») :
# là, la cible existe au moment du clic et c'est après coup que le jeu
# redirige — sans ennemi, le sort n'a toujours rien à viser.
_NO_ENEMY_FALLBACK_RX = re.compile(
    r"\bif there (?:are|is) no enemies\b[^.]*\bthe enemy nexus\b", re.I)


def our_nexus_is_alternative(core: str, targets: list, spans: list) -> bool:
    """
    Le texte offre-t-il NOTRE NEXUS comme autre point de ce clic ?

    On ne cherche pas la tournure n'importe où : on la vérifie À LA
    POSITION du marqueur allié que `_scan_targets` a effectivement
    retenu. Un marqueur nullifié (« randomly to an ally or your Nexus »)
    n'a pas de position dans `spans`, et il ne peut donc pas offrir de
    repli — ce qui serait un clic que le jeu refuse.
    """
    for side, (start, _end) in zip(targets, spans):
        if side == "ALLY" and _OUR_NEXUS_RX.match(core, start):
            return True
    return False


# Effets qui NUISENT à leur cible.
# SLEEP, CAPTURE, DESEQUIP et BANISH rejoignent la liste le 06/11/2026 :
# s'endormir, se capturer, détruire son propre équipement ou renvoyer sa
# propre unité dans son deck ne sont pas des maladresses de ciblage, ce
# sont des gestes que rien ne justifie.

# --- ce qu'une carte fait TOUT DE SUITE, lu dans son texte ------------
#
# POURQUOI UNE LECTURE DE PLUS (15/11/2026, règle de jeu d'Ewan).
# `classify_card` répond « que faut-il CLIQUER » ; il rend DAMAGE 2 pour
# « Deal 2 to all enemies » comme pour « Deal 2 to an enemy », parce que
# du point de vue du geste c'est pareil — aucun clic dans les deux cas.
# Pour CHOISIR entre deux cartes offertes, il faut l'autre moitié : la
# PORTÉE, et les effets qui ne se voient pas sur le plateau (la pioche).
#
# ON COMPTE DES MARQUEURS, ON NE RECONNAÎT PAS DES SORTS — même
# principe qu'ailleurs dans ce module. Les trois Destiny Cards de
# Twisted Fate (Wild Card, « Play a Destiny Card. ») en sont l'occasion,
# pas le sujet : la lecture vaut pour tout texte.
_ZONE_ENNEMIS_RX = re.compile(r"\bto all enem(?:y|ies)\b", re.I)
_NEXUS_AUSSI_RX = re.compile(r"\band the enemy nexus\b", re.I)
_STUN_RX = re.compile(r"\bstun\b", re.I)
_PIOCHE_RX = re.compile(r"\bdraw\s+(\d+)\b", re.I)
_PLUS_FORT_ENNEMI_RX = re.compile(r"\bthe strongest enemy\b", re.I)


class EffetImmediat(NamedTuple):
    """
    Ce qu'une carte fait au moment où elle se résout.

    `degats` est le montant du plan (0 si l'effet n'en est pas un) ;
    `zone_ennemis` dit qu'il tombe sur TOUS les ennemis ; `plus_fort`
    qu'il vise le plus fort d'entre eux — deux portées que le jeu choisit
    lui-même, donc sans clic, et que `classify_card` ne distingue pas.
    """

    degats: int = 0
    zone_ennemis: bool = False
    plus_fort: bool = False
    stun: bool = False
    pioche: int = 0
    nexus_aussi: bool = False


def lire_effet_immediat(card) -> EffetImmediat:
    """Lit sur le texte anglais ce que la carte fait en se résolvant."""
    if hasattr(card, "description"):
        texte = card.description or ""
    else:
        texte = card.get("descriptionRaw") or ""
    if not texte:
        return EffetImmediat()
    plan = classify_card(card, restricted=False)
    degats = plan.amount or 0 if plan.effect in ("DAMAGE", "DRAIN") else 0
    pioche = _PIOCHE_RX.search(texte)
    return EffetImmediat(
        degats=degats,
        zone_ennemis=bool(_ZONE_ENNEMIS_RX.search(texte)),
        plus_fort=bool(_PLUS_FORT_ENNEMI_RX.search(texte)),
        stun=bool(_STUN_RX.search(texte)),
        pioche=int(pioche.group(1)) if pioche else 0,
        nexus_aussi=bool(_NEXUS_AUSSI_RX.search(texte)),
    )


HARMFUL = {"DAMAGE", "DRAIN", "KILL", "STUN", "SILENCE", "RECALL", "TRANSFORM",
           "SLEEP", "CAPTURE", "DESEQUIP", "BANISH", "GLOOM"}
# Effets qui la RENFORCENT.
HELPFUL = {"BUFF", "HEAL", "GENERATE", "ACTIVATE"}

# L'UNITÉ REVIENT-ELLE ? C'est la vraie ligne de partage quand le texte
# nous impose de viser NOTRE camp (06/11/2026).
#
# `choose_target` a deux façons de choisir chez nous : `gift_to_ally` (la
# meilleure receveuse, Éphémères exclues) et `sacrifice` (la moins
# regrettable, Éphémères EN PREMIER). Jusqu'ici c'est « néfaste » qui
# tranchait — or tuée, l'unité ne revient pas, tandis qu'endormie,
# rappelée ou capturée, si. Les textes ont la même tournure et des prix
# très différents : « Kill an ally TO deal 3 to the enemy Nexus »
# (Astral Fox) contre « Recall an ally TO summon an exact Ephemeral copy
# in its place » (Go Get It). Dans le second cas l'allié est un MOYEN :
# l'effet vaut ce que vaut l'unité qu'on y met, et sacrifier une
# Éphémère gâche la carte — elle disparaît en fin de round.
#
# La base le dit aussi pour le sommeil : Drowsy Dewdrop (09IO045T1)
# « Countdown 1: Summon an exact copy of the sleeping unit inside », et
# Lillia niveau 2 « When you Sleep another ally, immediately wake it up
# and grant it Spirit » — une récompense, qu'on veut sur notre meilleure
# unité. Relevé par la relecture du diff de ce jour, sur 19 cartes.
RETURNS = {"SLEEP", "RECALL", "CAPTURE"}


class Targeting(Enum):
    NONE = "aucune"          # rien à cliquer
    ALLY = "allié"
    ENEMY = "ennemi"
    ANY_UNIT = "unité"       # les deux camps sont des cibles légales
    ANYTHING = "unité_ou_nexus"
    HAND = "carte en main"   # le clic va dans NOTRE main, pas sur le plateau
    CHOICE = "version à poser"  # le clic va sur une des cartes proposées
    REFUSED = "refusé"


# ============================================================
# « PLAY ME AS A OR B » : LE SEUL CHOIX QU'ON SACHE PILOTER
# ============================================================
# « Play: Play me as First Wave or Last Wind. » (Les ailes et la vague,
# 04SI004). Le jeu remplace la carte par DEUX cartes au centre de l'écran
# et attend qu'on en clique une. Le choix est OBLIGATOIRE : ni le clic
# d'annulation ni le bouton de passe ne le referment, et sans clic la
# partie ne repart pas — c'est le blocage observé le 22/08/2026.
#
# Ce qui rend ce cas-là pilotable, contrairement à Manifest ou Invoke :
# les deux options sont NOMMÉES DANS LE TEXTE. On sait donc quoi chercher
# à l'écran, où l'API rapporte les cartes avec leur cardCode — comme elle
# rapporte déjà celles du mulligan, qui s'affichent au même endroit.
#
# Le motif est ANCRÉ en tête de clause. « You may spend 8 mana to play me
# as Naganeka » (armes Darkin) n'est pas le même geste : l'option est
# payante, la seconde version n'est pas nommée comme une alternative de
# pose, et elle reste refusée.
_PLAY_AS_RX = re.compile(r"^play me as (.+?)\.?$", re.I)
# « You may spend 8 mana to play me as Horazi. » — les armes Darkin. Le
# repère ci-dessus exige que la phrase soit TOUTE la ligne ; celui-ci la
# cherche n'importe où, parce que le texte complet commence par l'effet
# de l'équipement (« Support: Grant my supported ally +1|+1. »).
_VERSION_CHOICE_RX = re.compile(r"\bplay me as\b", re.I)
_OPTION_SPLIT_RX = re.compile(r"\s*\bor\b\s*|\s*,\s*", re.I)


def play_as_options(text: str) -> tuple:
    """
    Les versions proposées par « Play me as A or B », ou () si le texte
    n'est pas de cette forme.

    Deux options au minimum : un « play me as X » sans alternative ne
    demande aucun clic, et en faire un choix ferait chercher une fenêtre
    qui ne s'ouvre jamais.
    """
    match = _PLAY_AS_RX.match((text or "").strip())
    if not match:
        return ()
    names = [part.strip(" .") for part in _OPTION_SPLIT_RX.split(match.group(1))]
    names = tuple(name for name in names if name)
    return names if len(names) >= 2 else ()


# ============================================================
# FENÊTRES DE CARTES : MANIFEST, INVOKE, PREDICT, « PICK 1 OF 3 »...
# ============================================================
# Le jeu affiche deux ou trois cartes au centre de l'écran et attend qu'on
# en clique UNE : Manifest et Invoke (cartes inventées à la volée),
# Predict (le haut de notre deck), « Pick 1 of 3 champions », « Pick a
# Moon Weapon to create in hand », les Tellstones (« Create a Fleeting A,
# B, or C in hand »). Le choix est OBLIGATOIRE — comme pour « Play me as
# A or B », ni l'annulation ni le bouton de passe ne le referment.
#
# Longtemps refusées (« contenu inconnu »), ces fenêtres sont PILOTABLES
# depuis qu'Ewan a vu, en jeu, le bot cliquer dans les fenêtres de
# version : l'API rapporte les cartes affichées là, avec leur cardCode et
# leur position, exactement comme celles du mulligan. On n'a pas besoin
# de connaître leur nom à l'avance : ce sont les cartes à nous dont le
# CardID n'existait pas avant la pose (`actions.resolve_card_choice`).
#
# QUAND LA FENÊTRE S'OUVRE : à la RÉSOLUTION, jamais au lancement. Pour
# une unité ou un sort Burst/Focus, c'est immédiat, APRÈS les interfaces
# du lancement (cible, désignation en main : « Discard 1 to Manifest »,
# « Predict. Give an enemy -2|-0 »). Pour un sort Fast/Slow, c'est après
# la validation et la réponse adverse. C'est `actions` qui suit cet
# ordre ; ici on ne fait que dire qu'une fenêtre s'ouvrira, et laquelle.
#
# CE QUI N'EST PAS UNE FENÊTRE, et doit rester en dehors :
#   - « Pick a follower. » nu : un clic sur le plateau (refus REFUSALS) ;
#   - « Pick an ally in hand » : une désignation dans la main (HAND_PICKS) ;
#   - « ..., or create a Golden Spatula in hand » (Icathian Myths, Tag
#     Out!) : deux VERSIONS du sort, qui portent son nom — c'est la
#     famille des variantes (`variant_choice`), pas celle-ci. D'où la
#     forme exigée pour les Tellstones : trois NOMS de cartes (majuscule),
#     séparés par des virgules ;
#   - un texte ENTRE GUILLEMETS (Concurrent Timelines : « Grant followers
#     in your hand "When you play me, pick 1 of 3 followers..." ») : la
#     fenêtre s'ouvrira plus tard, pas à cette pose.
#             motif                                            fenêtre                         casse
CARD_WINDOWS = [
    (r"\bmanifest\b",                                        "Manifest",                     re.I),
    (r"\binvoke\b",                                          "Invoke",                       re.I),
    (r"\bpredict\b",                                         "Predict",                      re.I),
    (r"\bpick (?:1|one) of (?:\d+|two|three)\b",             "Pick 1 of N",                  re.I),
    (r"\bpick an? [^.]*?\bto create in hand\b",              "Pick ... to create in hand",   re.I),
    (r"\bpick an? [^.]*?\b(?:from|in) the top \d+ cards\b",  "Pick ... in the top of the deck", re.I),
    # Trois NOMS de cartes — les majuscules comptent, c'est ce qui
    # distingue les Tellstones de « ..., or create a Golden Spatula in
    # hand » (deux versions du même sort : famille des variantes).
    (r"\b[Cc]reate an? (?:Fleeting )?[A-Z][^,.]*, [A-Z][^,.]*, or [A-Z][^,.]* in hand\b",
                                                             "Create A, B, or C in hand",    0),
]
_CARD_WINDOW_RX = [(re.compile(p, flags), label) for p, label, flags in CARD_WINDOWS]
_QUOTED_RX = re.compile(r'"[^"]*"')


def card_window(text: str) -> str:
    """Le nom de la fenêtre de cartes que ce texte ouvrira, ou "" si aucune."""
    cleaned = _QUOTED_RX.sub("", text or "")
    for regex, label in _CARD_WINDOW_RX:
        if regex.search(cleaned):
            return label
    return ""


# UNE FENÊTRE PEUT MONTRER LES CARTES DE L'ADVERSAIRE (05/11/2026).
#
# Yoink! (98SB003) : « Pick 1 of 3 non-champion cards from the enemy hand
# to draw. » Le jeu affiche TROIS CARTES À LUI au centre de l'écran, et
# l'API les rapporte — avec LocalPlayer=FALSE. `actions.offered_cards` ne
# regardait que les cartes à nous : fenêtre « introuvable », annulation
# sans effet (une fenêtre ne s'annule pas), partie figée 184 s sur
# « SÉLECTIONNER LA CIBLE », tentative hebdomadaire perdue.
#
# Le texte le disait. Sept cartes de la base sont dans ce cas — Yoink!,
# Swindle, Prank, Skip "King of the Reef", et les trois Entrapment, dont
# l'une était EN MAIN au moment du blocage : le mur suivant était posé.
# C'est un marqueur de CAMP, pas une liste de sorts : on lit « from the
# enemy hand/deck », on ne reconnaît pas les cartes.
_ENEMY_WINDOW_RX = re.compile(r"\bfrom the enemy\s+(?:hand|deck)\b", re.I)


def opens_version_choice(card) -> bool:
    """
    Cette carte ouvre-t-elle une fenêtre de VERSIONS au dépôt ?

    Le jeu propose alors DEUX versions — l'équipement, ou la créature —
    AVANT de poser la moindre autre question. Il faut donc la refermer
    avant de désigner quoi que ce soit : cliquer la cible tout de suite,
    c'est cliquer DERRIÈRE la fenêtre.

    Accepte une carte de la base (dict) ou une `BoardCard`.
    """
    if card is None:
        return False
    texte = (card.get("descriptionRaw") if hasattr(card, "get")
             else getattr(card, "description", "")) or ""
    return bool(_VERSION_CHOICE_RX.search(texte))


def card_window_side(text: str) -> str:
    """À qui sont les cartes de la fenêtre : "ours" (défaut) ou "theirs"."""
    if _ENEMY_WINDOW_RX.search(_QUOTED_RX.sub("", text or "")):
        return "theirs"
    return "ours"


def strip_card_window(text: str) -> str:
    """
    Retire la clause de la fenêtre, jusqu'à la virgule ou au point suivant.

    « Manifest a follower you can afford. » contient « a follower », et
    « Pick a follower from the top 4 cards » aussi : ce sont des cartes DE
    LA FENÊTRE, pas des unités du plateau. Laissés dans le texte, ces
    marqueurs feraient cliquer une unité que personne n'attend. La
    virgule borne la coupe pour garder ce qui suit : « Invoke a Celestial
    card that costs 7 or more, then heal an ally » garde son allié.
    """
    for regex, _ in _CARD_WINDOW_RX:
        match = regex.search(text)
        if match:
            end = re.compile(r"[,.]").search(text, match.end())
            cut = end.start() if end else len(text)
            text = (text[:match.start()] + text[cut:]).lstrip(" ,.;").rstrip()
            text = re.sub(r"^\s*(?:then|and)\s+", "", text, flags=re.I)
            return re.sub(r"\s+", " ", text)
    return text


_EXTRA_COST_RX = re.compile(r"^to play\b", re.I)


def has_extra_cost(description: str) -> bool:
    """
    Cette carte réclame-t-elle un prix à la pose (« To play me, kill an
    ally. ») ?

    Sert à départager les versions proposées : celle qui coûte un allié
    ouvre une SECONDE interface après le choix, donc deux occasions de se
    tromper au lieu d'une.
    """
    return bool(_EXTRA_COST_RX.match((description or "").strip()))


# ============================================================
# « +2|+0 OR +0|+2 » : LE CHOIX DE VARIANTE
# ============================================================
# « Give an ally +2|+0 or +0|+2 this round. » — Choix capital (Momentous
# Choice, 06IO034), vu en jeu le 22/08/2026. Le jeu propose D'ABORD les
# deux versions du sort, PUIS demande l'allié. Le bot ne voyait que la
# seconde étape et cliquait l'allié tout de suite.
#
# C'est une fenêtre de choix comme celle des « Play me as A or B », avec
# une différence qui change la façon de la piloter : les versions ne sont
# pas NOMMÉES dans le texte. Elles portent le nom de la carte jouée (les
# jetons 06IO034T1 et T2 s'appellent tous deux « Momentous Choice ») et se
# distinguent par ce qu'elles accordent. C'est donc `actions` qui les
# retrouve à l'écran par le nom de la carte jouée ; ce qu'on lit ici, ce
# sont les deux gains, dans l'ordre du texte.
#
# Trois cartes de la base suivent la forme CHIFFRÉE : Choix capital, Twin
# Disciplines (01IO012), Scaled Snapper (01IO028, dont le « Play: » suit
# la même forme).
#
# MAIS LA FAMILLE EST BIEN PLUS LARGE, ET ELLE NE SE LIT PAS DANS LE
# TEXTE. « Grant an ally Spellshield or Overwhelm » (Iula, 05MT013),
# « Summon a Powder Keg or a random 1 cost follower » (Petty Officer),
# « Deal 2 to a unit or deal 1 to two enemies » (Bouncing Bomb) : **47
# cartes** de la base proposent deux effets au choix. On le sait parce
# qu'elles ont des JETONS DU MÊME NOM, un par branche du « ou » — c'est
# le client qui a besoin d'une carte par option, et c'est la seule trace
# fiable de la fenêtre.
#
# ET POURTANT ON NE PEUT PAS TRANCHER SUR LE TEXTE. « Deal 3 to a unit or
# destroy a landmark » se joue en UN clic (la cible décide), « Give an
# ally Barrier or SpellShield » en deux. 119 cartes jouables contiennent
# un « or » ; refuser sur ce seul mot en casserait la majorité, et
# reconnaître les bonnes formulations demanderait une liste sans fin.
#
# D'OÙ LA RÈGLE : le texte dit qu'une fenêtre est POSSIBLE
# (`variant_choice`, un vrai « ou »), et c'est L'ÉCRAN qui tranche —
# `actions.resolve_variant_choice` cherche les versions ; s'il n'en
# trouve pas, il n'y avait pas de fenêtre et le ciblage suit son cours.
# C'est la même doctrine que la navigation : ce qu'un nœud propose se
# découvre à l'arrivée, il ne se devine pas.
#
# La forme chiffrée, elle, reste une CERTITUDE (`variants`) : là, ne pas
# trouver la fenêtre est une anomalie, et le sort est abandonné plutôt
# que lancé de travers.
_VARIANT_RX = re.compile(r"\+(\d+)\|\+(\d+)\s+or\s+\+(\d+)\|\+(\d+)")


def stat_variants(text: str) -> tuple:
    """
    Les deux gains proposés — ((force, vie), (force, vie)) — ou ().

    Ne dit RIEN de la cible : « Give an ally +2|+0 or +0|+2 » demande
    toujours un allié, et c'est `classify_text` qui le dit. Les deux
    lectures sont indépendantes, et le geste les enchaîne dans cet ordre :
    la variante d'abord, la cible ensuite.
    """
    match = _VARIANT_RX.search(text or "")
    if not match:
        return ()
    a, b, c, d = (int(n) for n in match.groups())
    return ((a, b), (c, d))


@dataclass
class SpellPlan:
    """Verdict sur un sort : jouable ou non, et sur quelle sorte de cible."""

    effect: str
    targeting: Targeting
    amount: Optional[int] = None
    reason: str = ""
    picks: int = 0             # cartes à désigner DANS LA MAIN
    pick_type: str = "any"     # unit / spell / equipment / any
    pick_best: bool = False    # vrai si la désignation PROFITE à la carte
    pick_consumes: bool = True  # la carte désignée QUITTE-T-ELLE la main ?
    # LE COÛT EN MAIN NE MANGE PLUS LA CIBLE DU PLATEAU (14/11/2026).
    # « To play, discard 1. Deal 3 to anything. » (Jinx's Get Excited!,
    # 01PZ040T3) rendait `Targeting.HAND` et JETAIT ses cibles : le bot
    # payait le coût, posait le sort, et le jeu attendait un clic que
    # personne ne faisait. `targeting` reste HAND — c'est lui qui
    # déclenche la désignation en main — et le PLATEAU est porté ici,
    # servi ensuite par `board_plan()`. Targeting.NONE pour l'immense
    # majorité des sorts, y compris « Discard 1 to draw 1 ».
    board_targeting: Targeting = Targeting.NONE
    # Refus qui n'est PAS de la prudence : le bot n'a pas la capacité, et
    # lever les restrictions n'y change rien (cf. classify_text).
    impossible: bool = False
    # Versions proposées par « Play me as A or B », dans l'ordre du texte.
    options: tuple = ()
    # Gains proposés par « +2|+0 or +0|+2 », dans l'ordre du texte. Une
    # fenêtre s'ouvre AVANT le ciblage, à coup sûr ; voir stat_variants.
    variants: tuple = ()
    # Un vrai « ou » dans l'effet : une fenêtre de versions PEUT s'ouvrir
    # avant le ciblage. C'est l'écran qui tranchera.
    variant_choice: bool = False
    # Une fenêtre de CARTES s'ouvrira à la résolution (Manifest, Invoke,
    # Predict, Tellstones...) : son nom, ou "" (cf. card_window). On ne
    # sait pas ce qu'elle contiendra, mais on saura la lire à l'écran.
    card_window: str = ""
    # À QUI sont les cartes de cette fenêtre : "ours" ou "theirs"
    # (cf. card_window_side — Yoink! pioche dans la main ADVERSE).
    card_window_side: str = "ours"
    # Cibles SUPPLÉMENTAIRES du MÊME camp, désignées par un « another » nu
    # (cf. `_find_targets`) : « Deal 2 to an enemy and Stun another. »
    # (Lien cosmique, 06BC044) en vaut un, Trueshot Barrage (01PZ004,
    # trois clics) deux. Zéro dans l'immense majorité des sorts.
    extra_targets: int = 0
    # Vrai quand les N cibles viennent d'un PLURIEL COMPTÉ (« Frostbite 2
    # enemies ») : le jeu accepte alors de lancer le sort sur MOINS de
    # cibles s'il n'y en a pas assez en jeu — un seul ennemi suffit. Faux
    # pour « an enemy ... and another » : là, chaque clic est exigé.
    flexible_targets: bool = False
    # CONDITION SUR LA CIBLE, quand l'adjectif devant le marqueur ne fait
    # pas que restreindre le camp : « a damaged ally » (Take Heart /
    # Courage de Braum, 01FR046) n'accepte QUE les unités blessées, et le
    # jeu refuse le clic sur une unité intacte — le sort reste en l'air.
    # Vu en jeu le 02/09/2026 : le bot cliquait la plus grosse alliée,
    # indemne. Une seule valeur pour l'instant : "damaged".
    target_condition: str = ""
    # ÉCHANGE : deux clics de GENRES DIFFÉRENTS, dans l'ordre du texte, un
    # COÛT puis une RÉCOMPENSE. « Deal 2 to an ally to Stun an enemy. »
    # (Astral Diffusion, 98MT009), « Kill an ally to kill a unit »
    # (Crumble, 03SI008). Chaque pas est (effet, Targeting, montant) ;
    # `steps()` en fait des sous-plans que `choose_target` sait servir un
    # par un. Vide pour tout sort ordinaire. Jusqu'au 05/09/2026 ces sorts
    # étaient refusés (« N cibles à cliquer, le bot n'en clique qu'une »).
    sequence: tuple = ()
    # DUEL DIRIGÉ : « An ally strikes an enemy », « An ally starts a free
    # attack Challenging an enemy » (Cataclysm, 04DE003), « An ally and that
    # enemy strike each other » (Desert Duel, 05SH022). Deux clics dans
    # l'ordre du texte, portés par `sequence` (effet "DUEL"), mais le choix
    # se fait PAR PAIRE : `choose_duel_targets` simule le combat singulier
    # (keywords.resolve_duel) et prend la paire qui tue sans mourir.
    # Jusqu'au 06/09/2026 ces sorts étaient refusés (« N cibles à cliquer »).
    duel: bool = False
    # Malus d'attaque appliqué à l'ennemi AVANT le duel (« Give an enemy
    # -2|-0 this round. » : -2). 0 sinon.
    duel_enemy_attack_delta: int = 0
    # « Deal 2 to a champion or 4 to a follower » (Weight of Judgment,
    # 04SH004) : UN clic, un montant qui dépend de la cible. `amount` vaut
    # pour un suivant, `amount_champion` pour un champion (None = pareil).
    amount_champion: Optional[int] = None
    # « Set a unit's stats to 1|6 this round. » (Défense paniquée,
    # 05BC209) : les stats que l'effet IMPOSE à sa cible. Ni néfaste ni
    # bénéfique — ça dépend entièrement de qui on vise, et c'est la seule
    # famille où le camp ne se déduit pas du verbe. Voir `choose_target`.
    stat_override: Optional[tuple] = None
    # NOTRE NEXUS EST L'AUTRE ENDROIT OÙ CE CLIC PEUT TOMBER (10/11/2026).
    # Le miroir de `Targeting.ANYTHING` du côté allié : « Heal an ally OR
    # YOUR NEXUS 3 » (9 cartes) est UN clic, avec deux cibles légales, et
    # la seconde ne quitte jamais le plateau. Sans ce drapeau, le banc
    # vide rendait « aucun allié en jeu » et le soin était abandonné dans
    # l'état même où il vaut le plus cher. Voir `our_nexus_is_alternative`.
    our_nexus_is_target: bool = False
    # LA CIBLE PEUT MANQUER, ET LE SORT PART QUAND MÊME (10/11/2026).
    # « Deal 4 to an enemy. IF THERE ARE NO ENEMIES, deal 4 to the enemy
    # Nexus instead. » — Final Spark, Ace in the Hole, Javelin Toss. Le
    # même texte exige un clic dès qu'un ennemi est là : le classement ne
    # peut pas trancher sur le texte seul, il dit les deux et c'est
    # l'instantané qui choisit (`actions.spell_is_castable`).
    #
    # CE DRAPEAU N'AUTORISE AUCUN CLIC — `choose_target` rend toujours
    # None sur un plateau vide. Il dit seulement que « zéro cible » n'est
    # pas, pour ces cartes-là, un empêchement.
    resolves_without_target: bool = False
    # LE JEU ATTEND DES DÉSIGNATIONS EN NOMBRE LIBRE, ET UNE VALIDATION
    # (10/11/2026). « Deal 1 to ANY NUMBER OF allies to deal that much to
    # an enemy » — Vladimir, son niveau 2, Crimson Pact : trois cartes.
    #
    # Ce drapeau n'ajoute NI cible NI clic de plateau : les marqueurs
    # sont comptés comme partout ailleurs (ici un seul, « an enemy »).
    # Il dit à `actions` qu'un geste de plus est dû APRÈS les cibles —
    # un clic sur l'orbe de tour — pour clore une désignation qu'on
    # décline. Zéro allié : poser le champion EST le gain, et choisir de
    # se blesser pour frapper plus fort est une décision de jeu qui
    # n'appartient pas à cette brique. Voir `_FREE_DESIGNATION_RX`.
    free_designation: bool = False

    def damage_to(self, card) -> Optional[int]:
        """Le montant de dégâts que CE sort inflige à CETTE carte."""
        if self.amount_champion is not None and getattr(card, "is_champion", False):
            return self.amount_champion
        return self.amount

    def steps(self) -> tuple:
        """Les sous-plans d'un échange, un par clic, dans l'ordre."""
        return tuple(SpellPlan(effect, kind, amount) for effect, kind, amount in self.sequence)

    @property
    def is_trade(self) -> bool:
        return len(self.sequence) >= 2

    @property
    def playable(self) -> bool:
        return self.targeting is not Targeting.REFUSED

    @property
    def needs_click(self) -> bool:
        """Un point à cliquer SUR LE PLATEAU. La main est à part."""
        return self.targeting in (
            Targeting.ALLY, Targeting.ENEMY, Targeting.ANY_UNIT, Targeting.ANYTHING
        )

    @property
    def total_targets(self) -> int:
        """
        Combien de clics de PLATEAU au total, extra_targets compris.

        Zéro pour tout ce qui ne clique pas le plateau (HAND, CHOICE,
        NONE, REFUSED) : `extra_targets` n'a de sens qu'accolé à un
        marqueur de plateau, jamais posé seul.
        """
        if self.is_trade:
            return len(self.sequence)
        return (1 + self.extra_targets) if self.needs_click else 0

    @property
    def needs_hand_pick(self) -> bool:
        return self.targeting is Targeting.HAND and self.picks > 0

    @property
    def needs_board_click_after_hand(self) -> bool:
        """Un coût payé en main, PUIS un clic sur le plateau."""
        return (self.needs_hand_pick
                and self.board_targeting is not Targeting.NONE)

    def board_plan(self) -> "SpellPlan":
        """
        Le sous-plan du PLATEAU, une fois le coût en main payé.

        `replace` plutôt qu'un SpellPlan neuf : le montant, les cibles
        supplémentaires, la condition de cible et les deux nexus sont
        déjà portés par le plan complet, et les recopier à la main
        créerait la divergence que ce projet paie à chaque fois qu'un
        même test existe en deux exemplaires.
        """
        return replace(self, targeting=self.board_targeting, picks=0,
                       board_targeting=Targeting.NONE)

    @property
    def needs_choice(self) -> bool:
        """Une fenêtre de choix va s'ouvrir, et on sait laquelle cliquer."""
        return self.targeting is Targeting.CHOICE and len(self.options) >= 2

    @property
    def needs_variant(self) -> bool:
        """
        Une fenêtre de VARIANTE s'ouvre avant tout le reste, à coup sûr.

        Elle ne remplace pas le ciblage, elle le précède : « Give an ally
        +2|+0 or +0|+2 » demande la variante PUIS l'allié.
        """
        return self.playable and len(self.variants) >= 2

    @property
    def opens_card_window(self) -> bool:
        """
        Une fenêtre de cartes s'ouvrira à la résolution, et on la lira à
        l'écran (`actions.resolve_card_choice`). Elle vient APRÈS les
        interfaces du lancement — cible, désignation en main.
        """
        return self.playable and bool(self.card_window)

    @property
    def may_offer_variants(self) -> bool:
        """
        Une fenêtre de versions POURRAIT s'ouvrir : on regardera.

        Le texte propose deux effets, mais rien n'y distingue « Deal 3 to
        a unit or destroy a landmark » (un seul clic, la cible tranche) de
        « Grant an ally Spellshield or Overwhelm » (une fenêtre, puis la
        cible). L'écran, lui, le dit sans ambiguïté.

        JAMAIS POUR UN `Targeting.CHOICE` : « Play me as First Wave or
        Last Wind » EST déjà une fenêtre, pilotée par
        `actions.resolve_play_choice`, et son « ou » n'en annonce pas une
        seconde. Les deux familles s'excluent ; les confondre ferait
        chercher deux fois, sur un écran qui n'attend qu'un clic.
        """
        if self.targeting is Targeting.CHOICE:
            return False
        # Même exclusion pour une fenêtre de CARTES : le « or » de « Create
        # a Fleeting A, B, or C in hand » EST la fenêtre, pas l'annonce
        # d'une seconde. La forme chiffrée, elle, reste une certitude.
        if self.card_window and not self.needs_variant:
            return False
        return self.playable and (self.variant_choice or self.needs_variant)

    @property
    def harmful(self) -> bool:
        return self.effect in HARMFUL

    def __str__(self) -> str:
        if not self.playable:
            return f"refusé — {self.reason}"
        if self.targeting is Targeting.CHOICE:
            return f"{self.effect} : choix entre " + " ou ".join(self.options)
        if self.targeting is Targeting.HAND:
            quoi = "" if self.pick_type == "any" else f" de type {self.pick_type}"
            sens = "à renforcer" if self.pick_best else "à sacrifier"
            suite = "" if self.pick_consumes else ", qui reste en main"
            if self.needs_board_click_after_hand:
                # LE DIAGNOSTIC DOIT DIRE LES DEUX GESTES. Taire le
                # second, c'est reproduire le défaut du 09/11 où
                # `actions.py plan` annonçait jouable ce que la décision
                # refusait : on vient lire cette ligne pour savoir ce que
                # le bot va FAIRE.
                # `total_targets` vaut 0 sur un plan HAND (il ne compte
                # que les clics de plateau d'un ciblage direct) : c'est
                # le SOUS-PLAN qui sait combien de cibles viennent après.
                vise = self.board_plan().total_targets
                combien = "" if vise <= 1 else f" ×{vise}"
                suite += f", puis {self.board_targeting.value}{combien} sur le plateau"
            return (
                f"{self.effect} : {self.picks} carte(s){quoi} {sens} en main{suite}"
            )
        if self.is_trade:
            return "échange : " + " puis ".join(
                f"{e}{'' if a is None else ' ' + str(a)} sur {k.value}" for e, k, a in self.sequence
            )
        amount = f" {self.amount}" if self.amount is not None else ""
        suite = f" (+{self.extra_targets} cible(s))" if self.extra_targets else ""
        # LES DEUX NEXUS SE DISENT DANS LE PLAN, parce que c'est cette
        # ligne-là qu'on relit dans un log de combat et dans
        # `spells.py explain`. Sans elle, « DAMAGE 4 sur ennemi » promet
        # un clic que Final Spark ne fait pas toujours, et « HEAL sur
        # allié » tait l'autre moitié de la cible.
        if self.our_nexus_is_target:
            suite += " ou notre nexus"
        if self.resolves_without_target:
            suite += " (ou le nexus adverse si le plateau est vide)"
        if self.target_condition == "damaged":
            suite += " blessé(e)"
        if self.card_window:
            suite += f", puis fenêtre de cartes ({self.card_window})"
        if self.free_designation:
            suite += ", puis validation (aucun allié désigné)"
        return f"{self.effect}{amount} sur {self.targeting.value}{suite}"


def _find_targets(text: str) -> list:
    """Marqueurs de cible singuliers, sans doublon de recouvrement."""
    return _scan_targets(text)[0]


def _scan_targets(text: str) -> tuple:
    """
    Comme `_find_targets`, mais rend aussi les POSITIONS (début, fin) des
    marqueurs singuliers trouvés, dans l'ordre du texte — ce qu'il faut
    pour découper un échange en « coût » et « récompense » (`_trade_steps`).
    Les cibles muettes (« another » nu, pluriels comptés) n'ont pas de
    position propre : `spans` peut être plus court que la liste rendue.
    """
    hits = []
    for regex, side in _TARGET_RX:
        for match in regex.finditer(text):
            hits.append((match.start(), match.end(), side))

    # Tri par position, puis par longueur DÉCROISSANTE : à position égale,
    # le marqueur le plus long l'emporte. Sans ça, « an ally in hand » est
    # lu comme un simple « an ally » et le sort passerait pour ciblable
    # sur le plateau alors qu'il vise une carte de la main.
    hits.sort(key=lambda h: (h[0], -h[1]))

    kept, spans, last_end = [], [], -1
    for start, end, side in hits:
        # « an allied follower » contient « a follower » : on ne compte
        # qu'un marqueur par zone de texte.
        if start >= last_end:
            if _DRAWN_RX.search(text[:start]) or _RANDOM_RX.search(text[:start]):
                # ON PIOCHE DANS LE DECK, JAMAIS SUR LE PLATEAU
                # (06/11/2026). « Draw a champion. » (Entreat, 01FR029)
                # comptait « a champion » pour une unité à cliquer : le
                # bot prévoyait un geste que le jeu n'attend pas. Six
                # cartes étaient dans ce cas. On consomme quand même la
                # zone (`last_end`) pour qu'un marqueur imbriqué ne
                # reprenne pas sa place.
                #
                # MÊME GESTE POUR « RANDOMLY TO » (08/11/2026, cf.
                # `_RANDOM_RX`), et là consommer la zone n'est plus une
                # précaution mais une nécessité : « randomly to an enemy
                # or the enemy Nexus » recouvre un « an enemy » plus
                # court qui, sans ça, reprendrait sa place et ferait
                # cliquer une unité que le jeu ne laisse pas désigner.
                last_end = end
                continue
            kept.append(side)
            spans.append((start, end))
            last_end = end

    # « another » SEUL, SANS SUBSTANTIF, RESTE UNE DEUXIÈME CIBLE.
    #
    # « Deal 2 to an enemy and Stun another. » (Lien cosmique / Cosmic
    # Binding, 06BC044), vu en jeu le 26/08/2026 : le bot cliquait
    # l'ennemi désigné par « an enemy », lançait les dégâts, puis restait
    # bloqué en attente d'un second clic pour l'Étourdissement — celui que
    # réclame « another », qui ne répète pas le mot « enemy » mais désigne
    # bel et bien une DEUXIÈME cible du même genre. Rien dans
    # SINGULAR_TARGETS ne le voit : seule la forme « another ally/enemy/
    # unit/... » y est écrite, jamais la forme nue. Trueshot Barrage
    # (01PZ004, TROIS cibles : « ..., 2 to another, and 1 to another »),
    # Statikk Shock (01PZ031) et Shock Blast (05PZ027) suivent le même
    # moule : « Deal N to an enemy or the enemy Nexus, and M to another. »
    #
    # ON NE DEVINE PAS LE CAMP DE CETTE CIBLE MUETTE — ça n'a pas besoin
    # d'être su : il suffit de savoir qu'elle EXISTE, pour que le compte
    # total dépasse un et déclenche le refus « deux cibles » déjà en place
    # dans `_classify_text`. D'où le marqueur générique OTHER, absent de
    # la table `targeting` de cette fonction : s'il survivait jusque-là,
    # ce serait le signe que `len(targets) == 1` — impossible, puisqu'on
    # ne l'ajoute que quand un premier marqueur existe déjà.
    #
    # « one after another » EST UN FAUX AMI, employé dans son sens
    # adverbial par les sorts de combat (« An ally strikes ... one after
    # another » — Souffle ardent, Lame en boomerang) : leur cas est déjà
    # tranché par le refus dédié « combat dirigé, deux cibles »
    # (REFUSALS), et le mélanger ferait regretter à ces cartes une
    # capacité que restricted=False leur laisse par ailleurs tenter.
    if kept and not _STRIKE_RX.search(text):
        for match in _BARE_ANOTHER_RX.finditer(text):
            start = match.start()
            if not any(s <= start < e for s, e in spans):
                kept.append("OTHER")

    # UN PLURIEL COMPTÉ VAUT N CLICS DU MÊME GENRE. « Frostbite 2 enemies »
    # (Vents mordants / Harsh Winds, 01FR042) n'a aucun marqueur singulier :
    # il passait pour « aucune cible », le sort partait sans clic, le jeu
    # attendait deux ennemis. Vu en jeu le 02/09/2026 — avec UN SEUL
    # ennemi en face, que le jeu aurait accepté : quand les cibles valables
    # manquent, il se contente de celles qui existent (cf.
    # SpellPlan.flexible_targets).
    if not kept:
        match = _COUNTED_PLURAL_RX.search(text)
        if match:
            count = _COUNT_WORDS.get(match.group(1).lower()) or int(match.group(1))
            kept = [_PLURAL_SIDES[match.group(2).lower()]] + ["OTHER"] * (count - 1)

    return kept, spans


_BOARD_SIDES = {
    "ALLY": Targeting.ALLY,
    "ENEMY": Targeting.ENEMY,
    "ANY_UNIT": Targeting.ANY_UNIT,
    "ANYTHING": Targeting.ANYTHING,
}


def _clause_effect(clause: str) -> tuple:
    """(effet, montant) d'un bout de texte, avec les mêmes tables que le tout."""
    clause = re.sub(r"^\s*(?:to|and|then)\s+", "", clause.strip(" ,.;"), flags=re.I)
    effect = "AUTRE"
    for regex, name in _EFFECT_RX:
        if regex.search(clause):
            effect = name
            break
    match = _AMOUNT_RX.match(clause)
    return effect, (int(match.group(1)) if match else None)


def _trade_steps(core: str, targets: list, spans: list) -> tuple:
    """
    Découpe « X une cible pour Y une autre » en deux pas cliquables.

    Conditions, toutes nécessaires : exactement deux marqueurs, tous deux
    de plateau (pas de main, pas de « another » muet), chacun avec sa
    position, et une première clause qui NUIT à sa cible — c'est ce qui
    fait d'elle un coût et de la seconde une récompense. « Deal 2 to an
    ally to Stun an enemy » passe ; « An ally strikes an enemy » (combat
    dirigé, refusé ailleurs) et « Deal 1 to an ally to give another ally
    +2|+2 » (deux alliés à départager) ne passent pas : rend ().
    """
    if len(targets) != 2 or len(spans) < 2:
        return ()
    if any(t not in _BOARD_SIDES for t in targets):
        return ()
    # LE COÛT SE PAIE CHEZ NOUS, ET LA PHRASE DIT « POUR » : « Kill an ally
    # TO kill a unit ». Sans ces deux garde-fous, « Deal 2 to a champion or
    # 4 to a follower » (un seul clic, un « ou ») ou « Deal 1 to a follower.
    # If you've Evolved, deal 3 to a unit instead » (un clic, une condition)
    # passaient pour deux clics — et le bot aurait cliqué deux fois sur un
    # sort qui n'en attend qu'un, exactement le blocage qu'on veut éviter.
    if targets[0] != "ALLY" or targets[1] == "ALLY":
        return ()
    cut = spans[0][1]
    rest = core[cut:].lstrip(" ,")
    if not re.match(r"to\s+\w", rest, re.I):
        return ()
    first_effect, first_amount = _clause_effect(core[:cut])
    second_effect, second_amount = _clause_effect(rest)
    if first_effect not in HARMFUL:
        return ()
    # La récompense doit être un effet qu'on sait juger : un malus
    # (dégâts, mort, étourdissement…) ou « give an enemy Vulnerable ».
    # « to draw a champion », « to summon a follower from your deck » ne
    # cliquent rien sur le plateau : ce ne sont pas des échanges.
    if second_effect not in HARMFUL and not (second_effect == "BUFF" and targets[1] == "ENEMY"):
        return ()
    return (
        (first_effect, _BOARD_SIDES[targets[0]], first_amount),
        (second_effect, _BOARD_SIDES[targets[1]], second_amount),
    )


_OR_RX = re.compile(r"^\s*or\b", re.I)
_DUEL_RX = re.compile(r"\bstrikes?\b|\bfree attack\b|\bchalleng", re.I)
_ENEMY_ATTACK_MALUS_RX = re.compile(r"an enemy -(\d+)\|-0", re.I)


def _or_alternative(core: str, targets: list, spans: list):
    """
    « Deal 2 to a champion or 4 to a follower » : deux marqueurs reliés par
    « or » = UN clic. Rend (camp, montant_suivant, montant_champion) ou None.

    Le camp est celui des deux marqueurs s'ils s'accordent, sinon la
    réunion (« a unit »). Les montants sont lus clause par clause ; sans
    nombre dans la seconde, les deux valent le montant global.
    """
    if len(targets) != 2 or len(spans) < 2:
        return None
    if any(t not in _BOARD_SIDES for t in targets):
        return None
    between = core[spans[0][1]:spans[1][0]]
    if not _OR_RX.match(between):
        return None
    side = targets[0] if targets[0] == targets[1] else "ANY_UNIT"
    first = re.search(r"(\d+)", core[:spans[0][0]])
    second = re.search(r"(\d+)", between)
    a1 = int(first.group(1)) if first else None
    a2 = int(second.group(1)) if second else a1
    # Quel montant va à quel type ? « a champion » / « a follower » dans
    # les marqueurs eux-mêmes.
    m1, m2 = core[spans[0][0]:spans[0][1]].lower(), core[spans[1][0]:spans[1][1]].lower()
    amount_follower, amount_champion = a1, None
    if "champion" in m1 and "follower" in m2:
        amount_follower, amount_champion = a2, a1
    elif "follower" in m1 and "champion" in m2:
        amount_follower, amount_champion = a1, a2
    elif a1 != a2:
        amount_follower = max(x for x in (a1, a2) if x is not None)
    return side, amount_follower, amount_champion


def _duel_steps(core: str, targets: list, spans: list):
    """
    Un DUEL DIRIGÉ : un allié et un ennemi, et le texte parle de frappe,
    d'attaque libre ou de Challenger. Rend ((pas, pas), malus_attaque_ennemi)
    dans l'ordre du texte, ou None.

    « An ally strikes an enemy » (frappe à sens unique : l'ennemi ne
    riposte pas — on le simule quand même en duel, prudence), « An ally
    starts a free attack Challenging an enemy » (Cataclysm), « Give an
    enemy -2|-0 this round. An ally and that enemy strike each other »
    (Desert Duel : l'ENNEMI se clique d'abord, c'est l'ordre du texte).
    """
    if len(targets) != 2 or len(spans) < 2:
        return None
    if sorted(targets) != ["ALLY", "ENEMY"]:
        return None
    if not _DUEL_RX.search(core):
        return None
    # UN MARQUEUR QUALIFIÉ EST UNE CONDITION QU'ON NE SAIT PAS VÉRIFIER :
    # « An Equipped ally » (Lame féroce, 06NX034), « A battling ally »
    # (Whirling Death) — le jeu refuse le clic sur un allié qui ne remplit
    # pas la condition, et le sort reste en l'air. Seuls les marqueurs nus
    # (« an ally », « an enemy », « that enemy ») font un duel pilotable.
    for start, end in spans[:2]:
        marker = re.sub(r"\s+", " ", core[start:end].strip().lower())
        if marker not in ("an ally", "an enemy", "that enemy", "a unit"):
            return None
    malus = _ENEMY_ATTACK_MALUS_RX.search(core)
    delta = -int(malus.group(1)) if malus else 0
    steps = tuple(("DUEL", _BOARD_SIDES[t], None) for t in targets)
    return steps, delta


def counted_plural(text: str) -> bool:
    """Le texte cible-t-il « N ennemis/alliés/unités » (pluriel compté) ?"""
    return _COUNTED_PLURAL_RX.search(text) is not None


def classify_text(description: str, restricted: bool = True) -> SpellPlan:
    """
    Analyse une description brute. Cœur testable du module.

    `restricted` à False lève tous les refus de PRUDENCE — ceux qui
    disent « je ne sais pas piloter cette interface » ou « ça pourrait se
    retourner contre nous ». La question posée n'est alors plus « peut-on
    jouer cette carte » mais « où cliquer, au mieux de ce qu'on
    comprend » : c'est le mode voulu par actions.CARD_RESTRICTIONS à
    False, où le filet est l'annulation APRÈS le dépôt plutôt que
    l'abstention avant.

    Vrai dans les deux modes : un texte sans marqueur de cible ne demande
    aucun clic, et un marqueur dit toujours de quel camp.

    LA VARIANTE EST LUE À PART, et attachée au plan quel qu'il soit
    (`_with_variants`) : « +2|+0 or +0|+2 » ne change ni l'effet ni la
    cible, il ajoute une fenêtre AVANT. Le faire dans le corps du
    classement obligerait à y penser à chacun de ses dix retours.
    """
    return _with_free_designation(
        _with_variants(
            _with_card_window(_classify_text(description, restricted), description),
            description,
        ),
        description,
    )


def _with_free_designation(plan: SpellPlan, description: str) -> SpellPlan:
    """
    Marque le plan quand le texte laisse le NOMBRE de désignations à
    notre discrétion (« any number of ») : le jeu attendra une
    validation sur l'orbe, et `actions` la donnera.

    Attaché à part, comme la fenêtre de cartes et les variantes : le
    corps du classement a dix retours, et y penser à chacun est
    exactement ce qu'on finit par oublier.

    UN REFUS N'EN PORTE JAMAIS : un plan injouable ne clique rien, donc
    il n'a rien à valider. C'est ce qui garde « Choose one: … any number
    of … » hors de portée pour le motif qui le barre vraiment.
    """
    if plan.playable and _FREE_DESIGNATION_RX.search(description or ""):
        plan.free_designation = True
    return plan


def _with_card_window(plan: SpellPlan, description: str) -> SpellPlan:
    """
    Attache au plan la fenêtre de cartes que le texte annonce, s'il en
    annonce une et si la carte est jouable. Un refus n'ouvre rien.
    """
    if plan.playable:
        cleaned = re.sub(r"\s+", " ", description or "")
        plan.card_window = card_window(cleaned)
        if plan.card_window:
            plan.card_window_side = card_window_side(cleaned)
    return plan


def _with_variants(plan: SpellPlan, description: str) -> SpellPlan:
    """
    Attache au plan ce que le texte dit d'une éventuelle fenêtre de
    versions : les gains chiffrés (certitude) et le simple « ou »
    (possibilité).

    Le « ou » est cherché sur le texte NETTOYÉ de ses préambules et de
    ses faux amis — parenthèses qui énumèrent, comparatifs « 2 or
    less » — sinon la moitié de la base semblerait proposer un choix.
    """
    if plan.playable:
        text = re.sub(r"\s+", " ", description or "").strip()
        plan.variants = stat_variants(text)
        plan.variant_choice = opens_a_second_choice(strip_preamble(text))
    return plan


def _classify_text(description: str, restricted: bool = True) -> SpellPlan:
    """Le classement proprement dit. Voir `classify_text`."""
    text = re.sub(r"\s+", " ", description or "").strip()
    if not text:
        # Pas de texte : rien à cibler, l'effet est automatique.
        return SpellPlan("AUCUN", Targeting.NONE)

    # AVANT LES REFUS : le seul choix de carte qu'on sache piloter.
    # « Play me as First Wave or Last Wind » tomberait sinon dans le refus
    # « play me as » écrit pour les armes Darkin.
    options = play_as_options(text)
    if options:
        return SpellPlan("CHOIX", Targeting.CHOICE, options=options)

    # Les refus HORS DE PORTÉE s'appliquent dans les deux modes : lever
    # les restrictions accepte un risque, ça n'apprend pas au bot à fermer
    # une fenêtre de choix. Les refus de PRUDENCE, eux, tombent.
    #
    # Ils sont testés EN PREMIER, avant ceux de prudence, pour qu'une même
    # carte reçoive le même verdict dans les deux modes : les armes Darkin
    # relèvent des deux motifs (« you may » et « play me as »), et l'ordre
    # de la liste faisait autrement dépendre `impossible` du mode — donc
    # l'annulation d'après-dépôt de `play_spell` aussi.
    # « Pick 1 of 3 champions », « Pick a Moon Weapon to create in hand » :
    # le verbe est celui du refus « pick », mais la phrase annonce une
    # FENÊTRE DE CARTES qu'on sait lire (CARD_WINDOWS). Le refus ne vaut
    # que pour le « Pick a follower. » nu, qui désigne le plateau.
    window = card_window(text)
    for out_of_reach in (True, False):
        if not (restricted or out_of_reach):
            continue
        for regex, reason, refusal_is_out_of_reach in _REFUSE_RX:
            if window and regex.pattern.startswith(r"\bpick"):
                continue
            if refusal_is_out_of_reach is out_of_reach and regex.search(text):
                return SpellPlan("REFUSE", Targeting.REFUSED, reason=reason,
                                 impossible=out_of_reach)

    # Les refus se lisent sur le texte ENTIER (un « you may » caché dans
    # une condition reste un « you may ») ; tout le reste se lit sur le
    # texte NETTOYÉ de ses préambules.
    core = strip_preamble(text)
    if window:
        # Les cartes de la fenêtre ne sont pas des cibles du plateau.
        core = strip_card_window(core)

    # L'EFFET SE LIT SUR LA CLAUSE QUI PORTE LA CIBLE, pas en tête de
    # texte (cf. `effect_clause`) : c'est elle qui dit ce qu'on fait à ce
    # qu'on clique. Sans marqueur de cible, c'est le texte entier, donc
    # le comportement d'avant à l'identique.
    effect = "AUTRE"
    porteuse = effect_clause(core)
    for regex, name in _EFFECT_RX:
        if regex.search(porteuse):
            effect = name
            break

    # LE MONTANT SE LIT SUR LA MÊME CLAUSE QUE L'EFFET (14/11/2026).
    # Il était lu sur `core`, ancré en tête : pour un sort ordinaire la
    # clause porteuse EST la tête, donc rien ne changeait — mais dès
    # qu'une clause de COÛT ou un déclencheur précède, le montant était
    # perdu. Mesuré sur les 2898 cartes : 37 changent, dont 36 passent
    # de « aucun montant » à leur vrai montant — Scrapshot (7), Monster
    # Harpoon (5), Rite of the Arcane (4), Get Excited! (3), Undergrowth,
    # Vladimir… Sans lui, `best_kill` choisissait sa cible à l'aveugle.
    # LA 37e VA DANS L'AUTRE SENS, ET C'EST TANT MIEUX : Stylish Shot
    # (07NX009) écrit « Deal 1 to the enemy Nexus. The next time an ally
    # strikes… » — ce 1 frappe le nexus TOUT SEUL, il n'a jamais décrit
    # la cible qu'on clique. Le montant appartient à la cible, donc à sa
    # clause.
    amount_match = _AMOUNT_RX.match(porteuse)
    amount = int(amount_match.group(1)) if amount_match else None

    targets, spans = _scan_targets(core)
    extra_targets = 0
    if len(targets) > 1:
        # « another » NU N'OUVRE PAS UNE AUTRE INTERFACE : C'EST LE MÊME
        # CLIC, REFAIT SUR UN AUTRE EXEMPLAIRE DU MÊME CAMP.
        #
        # « Deal 2 to an enemy and Stun another. » (Lien cosmique / Cosmic
        # Binding, 06BC044) ne demande pas deux GENRES de cible comme
        # Crumble ci-dessous : les deux clics visent le même camp, l'un
        # après l'autre, sans rien à décider entre eux — exactement le
        # geste que `choose_targets` sait répéter en excluant la cible
        # déjà prise. Statikk Shock (01PZ031), Shock Blast (05PZ027) et
        # Trueshot Barrage (01PZ004, jusqu'à TROIS clics) suivent le même
        # moule. On le reconnaît au marqueur OTHER de `_find_targets` :
        # lui seul dit « encore un du même genre », jamais « autre chose ».
        #
        # UN MARQUEUR EXPLICITE RÉPÉTÉ (« another ally », dans
        # SINGULAR_TARGETS depuis le début) N'EN FAIT PAS PARTIE. «Deal 1
        # to an ally to give another ally +2|+2 » (Transfusion, 01NX047)
        # ou « An ally Captures another ally » (Bayou Brunch, 03BW010) ne
        # sont pas deux fois le même geste : c'est un COÛT puis une
        # RÉCOMPENSE, et savoir laquelle sacrifier échappe à
        # `choose_targets`. Ceux-là restent refusés ci-dessous.
        if targets[0] in ("ALLY", "ENEMY", "ANY_UNIT", "ANYTHING") and all(
            t == "OTHER" for t in targets[1:]
        ):
            extra_targets = len(targets) - 1
            targets = targets[:1]
        elif _or_alternative(core, targets, spans):
            # « Deal 2 to a champion or 4 to a follower. » (Weight of
            # Judgment, 04SH004) : deux marqueurs, UN SEUL clic — le « or »
            # dit que la seconde clause est une alternative, pas un second
            # geste. Le montant dépend de ce qu'on clique.
            side, amount, amount_champion = _or_alternative(core, targets, spans)
            targets = [side]
            return SpellPlan(
                effect, _BOARD_SIDES[side], amount,
                amount_champion=amount_champion,
                target_condition=target_condition_of(core, spans),
            )
        elif _duel_steps(core, targets, spans):
            steps, delta = _duel_steps(core, targets, spans)
            return SpellPlan(
                "DUEL", steps[0][1], None, sequence=steps, duel=True,
                duel_enemy_attack_delta=delta,
            )
        elif _trade_steps(core, targets, spans):
            # UN ÉCHANGE : un coût sur notre camp, puis une récompense. Deux
            # clics de genres différents, mais chacun se choisit seul —
            # le sacrifié le moins regrettable (ou celui qui SURVIT aux
            # dégâts), puis la meilleure cible de l'effet. Piloté depuis le
            # 05/09/2026 (`choose_trade_targets`) ; c'était le refus le plus
            # fréquent du journal (Astral Diffusion, 98MT009, écartée à
            # chaque tour du combat du 05/09).
            steps = _trade_steps(core, targets, spans)
            return SpellPlan(
                steps[-1][0], steps[0][1], steps[-1][2],
                sequence=steps,
                target_condition=target_condition_of(core, spans),
            )
        else:
            # DEUX CIBLES À CLIQUER, DE GENRES DIFFÉRENTS, ET LE BOT N'EN
            # CLIQUE QU'UNE.
            #
            # Ce refus-là survit aux restrictions levées, parce qu'il ne
            # parle pas de prudence mais de capacité — au même titre que
            # le mana ou la place sur le banc. « Kill an ally to kill a
            # unit » (Crumble, 03SI008) demande un allié PUIS une unité :
            # garder le premier marqueur et espérer, c'était sacrifier une
            # de nos unités et laisser le client en attente du second
            # clic, sans même annuler (l'annulation ne se déclenchait que
            # si AUCUNE cible n'avait été cliquée). Observé en jeu le
            # 20/08/2026.
            return SpellPlan(
                effect, Targeting.REFUSED, amount,
                reason=f"{len(targets)} cibles à cliquer, le bot n'en clique qu'une",
                impossible=True,
            )

    # ---- désignation dans la main --------------------------------------
    spec = hand_pick_spec(core, effect)
    if spec:
        picks, pick_type, pick_best, pick_consumes = spec

        # Deux interfaces à la suite — désigner en main PUIS cliquer une
        # unité — c'est deux fois plus d'occasions de se tromper, et un
        # échec au milieu laisse la partie dans un état qu'on ne sait pas
        # décrire. « Discard a card to deal 4 to an enemy » attend donc son
        # tour : chaque interface se pilote, leur enchaînement non.
        if restricted and any(t != "HAND" for t in targets):
            return SpellPlan(
                effect, Targeting.REFUSED,
                reason="deux interfaces : la main puis le plateau",
            )

        # Un vrai « ou » est un deuxième choix à faire, dans une fenêtre
        # qu'on ne sait pas lire : « Updraft 1 to either draw 1 or refill
        # your spell mana », « Grant SpellShield or Overwhelm to an ally in
        # hand ». Les faux amis sont écartés par opens_a_second_choice.
        if restricted and opens_a_second_choice(core):
            return SpellPlan(
                effect, Targeting.REFUSED,
                reason="un choix supplémentaire après la désignation",
            )

        # LE COÛT EN MAIN NE MANGE PLUS LA CIBLE (14/11/2026, fait de jeu
        # d'Ewan sur Jinx's Get Excited!). Jusqu'ici les cibles trouvées
        # étaient JETÉES ici même : le sort partait, le coût était payé,
        # et le jeu attendait un clic que personne ne faisait. L'état
        # redouté par le commentaire ci-dessus — « un échec au milieu
        # laisse la partie dans un état qu'on ne sait pas décrire » —
        # était donc DÉJÀ celui qu'on produisait, systématiquement, et
        # seul le garde d'immobilité (~50 s) finissait par annuler.
        # CINQ CARTES de la base, dont trois collectionnables.
        board = [t for t in targets if t != "HAND"]
        board_targeting = Targeting.NONE
        if board:
            board_targeting = {
                "ALLY": Targeting.ALLY,
                "ENEMY": Targeting.ENEMY,
                "ANY_UNIT": Targeting.ANY_UNIT,
                "ANYTHING": Targeting.ANYTHING,
            }[board[0]]
        return SpellPlan(effect, Targeting.HAND, amount, picks=picks,
                         pick_type=pick_type, pick_best=pick_best,
                         pick_consumes=pick_consumes,
                         board_targeting=board_targeting,
                         # `extra_targets` est celui que le chemin normal
                         # vient de calculer — le « another » NU a sa
                         # logique propre (c'est le MÊME clic refait sur
                         # un autre exemplaire du même camp), et la
                         # recompter ici donnait 0 là où Timewinder en
                         # veut 1 : on n'aurait cliqué qu'une cible sur
                         # deux, donc recréé le blocage qu'on répare.
                         extra_targets=extra_targets,
                         target_condition=target_condition_of(core, spans),
                         our_nexus_is_target=(
                             board_targeting is Targeting.ALLY
                             and our_nexus_is_alternative(core, board, spans)),
                         )

    if not targets:
        return SpellPlan(effect, Targeting.NONE, amount)

    targeting = {
        "ALLY": Targeting.ALLY,
        "ENEMY": Targeting.ENEMY,
        "ANY_UNIT": Targeting.ANY_UNIT,
        "ANYTHING": Targeting.ANYTHING,
    }[targets[0]]

    # ---- garde-fous ----------------------------------------------------
    # Ce sont eux, et rien d'autre, que `restricted=False` désactive : ils
    # ne parlent pas de ce que le bot sait CLIQUER mais de ce qu'il juge
    # imprudent. `choose_target` sait s'accommoder de leur absence — un
    # effet néfaste sur notre camp y vise la PLUS PETITE unité.
    if restricted and targeting is Targeting.ALLY:
        if effect in HARMFUL:
            return SpellPlan(
                effect, Targeting.REFUSED,
                reason=f"{effect.lower()} dirigé sur notre propre unité",
            )
        if effect == "AUTRE":
            # Verbe non reconnu visant NOTRE camp : impossible de
            # distinguer un renfort d'un sacrifice. On s'abstient.
            return SpellPlan(
                effect, Targeting.REFUSED,
                reason="effet non reconnu sur notre propre unité",
            )

    if restricted and targeting is Targeting.ENEMY and effect in HELPFUL:
        # « give an enemy Vulnerable » est un malus déguisé en don. Ce qui
        # trahit un vrai renfort, c'est l'octroi de statistiques.
        if _STAT_BUFF_RX.search(core):
            return SpellPlan(
                effect, Targeting.REFUSED,
                reason="renforce une unité adverse",
            )

    # LES DEUX NEXUS, CHACUN SOUS SA CONDITION.
    #
    # Le nôtre est l'AUTRE POINT d'un clic allié, et il existe toujours :
    # c'est une propriété du marqueur, lue à sa position (10/11/2026).
    #
    # Celui d'en face est une DISPENSE DE CLIC, et seulement quand le
    # texte dit ce que devient le sort sans ennemi. On l'exige sur un
    # ciblage d'ENNEMI — la condition parle d'eux — et sur un seul clic :
    # avec des cibles supplémentaires, « zéro cible » ne voudrait plus
    # dire la même chose, et aucune carte de la base n'est dans ce cas.
    return SpellPlan(
        effect, targeting, amount, extra_targets=extra_targets,
        flexible_targets=extra_targets > 0 and counted_plural(core),
        target_condition=target_condition_of(core, spans),
        stat_override=stat_override(porteuse),
        our_nexus_is_target=(targeting is Targeting.ALLY
                             and our_nexus_is_alternative(core, targets, spans)),
        resolves_without_target=(targeting is Targeting.ENEMY
                                 and not extra_targets
                                 and bool(_NO_ENEMY_FALLBACK_RX.search(text))),
    )


def classify_card(card, restricted: bool = True) -> SpellPlan:
    """
    Analyse un BoardCard ou un dict de card_sets.

    Une carte absente de card_sets n'a pas de description : on ne peut
    rien en dire, donc on refuse.

    Sans restrictions, l'absence de description n'est plus un refus mais
    une ignorance assumée : aucun clic prévu, et `play_spell` annulera si
    le jeu attend malgré tout une cible.
    """
    if hasattr(card, "description"):
        description = card.description
        known = getattr(card, "known", True)
    else:
        description = card.get("descriptionRaw")
        known = True

    if not known:
        if restricted:
            return SpellPlan("REFUSE", Targeting.REFUSED,
                             reason="carte absente de card_sets")
        return SpellPlan("INCONNU", Targeting.NONE,
                         reason="carte absente de card_sets : effet inconnu")
    return classify_text(description, restricted=restricted)


# ============================================================
# POUVOIR « PLAY: » D'UNE UNITÉ
# ============================================================
# Une unité peut avoir, en plus de ses stats, un pouvoir qui se résout à
# la pose et demande une cible (« Play: Frostbite an enemy. » par
# exemple) : le jeu la garde alors au centre de l'écran, en attente d'un
# clic, exactement comme un sort. Rien ne distingue ça d'un sort dans le
# CLASSEMENT de la cible — c'est le même classify_text qui s'applique —
# mais il faut d'abord isoler le bon passage du texte : une unité a
# souvent PLUSIEURS déclencheurs (Attack:, Last Breath:, Round Start:...)
# qui ne se résolvent pas à la pose, et les mélanger ferait chercher un
# clic pour un effet qui ne se déclenche pas encore.

_TRIGGER_CLAUSE_RX = re.compile(r"\r\n|\n")
_PLAY_CLAUSE_RX = re.compile(r"^Play\b[^:]*:\s*(.*)$")


def extract_play_clause(description: str) -> Optional[str]:
    """
    Isole le texte du déclencheur « Play » dans la description d'une
    unité, et renvoie ce qui suit les deux-points.

    Chaque déclencheur occupe sa propre ligne dans descriptionRaw (les
    retours à la ligne les séparent) : c'est cette segmentation, et non
    une recherche de « Play » n'importe où dans le texte, qui isole le
    bon passage. Couvre aussi « Play and Round Start: ... », où le
    pouvoir se répète à un autre moment mais doit déjà être ciblé ici.

    Renvoie None si la carte n'a pas de déclencheur « Play ».
    """
    if not description:
        return None
    for clause in _TRIGGER_CLAUSE_RX.split(description):
        match = _PLAY_CLAUSE_RX.match(clause.strip())
        if match:
            return match.group(1)
    return None


def classify_unit_play(description: str, restricted: bool = True) -> Optional[SpellPlan]:
    """
    Comme classify_text, mais pour le déclencheur « Play » d'une unité.

    Renvoie None si la carte n'a pas de « Play: » à résoudre : la pose
    reste alors un simple dépôt, sans clic à prévoir.
    """
    clause = extract_play_clause(description)
    if clause is None:
        return None
    return classify_text(clause, restricted=restricted)


# ============================================================
# VITESSE
# ============================================================

def can_cast_now(card, snapshot) -> tuple:
    """
    La vitesse du sort permet-elle de le jouer maintenant ?

    Contrairement au ciblage, la vitesse est une donnée STRUCTURÉE
    (`spellSpeedRef`), donc fiable :
        Burst / Focus : à tout moment où l'on peut agir ;
        Fast          : à notre tour, ou en réponse ;
        Slow          : à notre tour seulement, hors combat et pile vide.

    Renvoie (autorisé, raison).
    """
    speed = (getattr(card, "spell_speed", "") or "").lower()

    if speed in ("burst", "focus"):
        return True, ""

    if snapshot.stack:
        if speed == "slow":
            return False, "sort lent : la pile n'est pas vide"
    if snapshot.attack_row or snapshot.enemy_attack_row:
        if speed == "slow":
            return False, "sort lent : combat en cours"

    return True, ""


# ============================================================
# CHOIX DE LA CIBLE
# ============================================================

def is_damaged(card) -> bool:
    """
    Cette unité a-t-elle PERDU des PV ?

    Se lit en comparant les PV affichés (OCR, `health_read`) aux PV
    imprimés : en dessous, elle est blessée. Sans lecture à l'écran on
    répond non — mieux vaut garder Courage de Braum en main qu'un sort
    en l'air. Une unité renforcée (+3|+3) puis blessée de 1 passe pour
    intacte : c'est le prix de ne pas connaître ses PV MAXIMUM, et il
    ne coûte qu'une occasion manquée, jamais un blocage.
    """
    return card.health_read is not None and card.health_read < card.base_health


def choose_target(plan: SpellPlan, snapshot, exclude_points: frozenset = frozenset()):
    """
    Choisit la cible d'un sort. Renvoie (point_écran, description) ou
    (None, raison) si aucune cible valable n'existe.

    Principe : un effet néfaste va sur l'adversaire, un effet bénéfique
    sur nous. Quand le sort accepte les deux camps (« a unit »), c'est
    donc l'effet qui tranche, jamais le hasard.

    RESTE LE CAS QUE LA PRUDENCE ÉCARTAIT : un effet néfaste qui n'accepte
    QUE notre camp (« Kill an ally »). Sans restrictions il faut bien
    désigner quelqu'un — on prend alors la MOINS REGRETTABLE, pas la plus
    grosse. Le choix du sacrifié suit la même logique que
    `actions.sacrifice_rank` pour la main : ce qu'on perd doit être ce
    qu'on regrettera le moins.

    LES ÉPHÉMÈRES CHANGENT LES DEUX BOUTS DE CE RAISONNEMENT, parce
    qu'elles quittent le plateau en fin de round : ce sont les sacrifiées
    idéales, et les pires receveuses d'un renfort ou d'un équipement —
    alors que « la plus grosse » les désignait en premier. D'où
    `gift_to_ally` / `sacrifice` plutôt que `biggest` / `smallest`.

    `exclude_points` écarte des candidats déjà retenus par un appel
    précédent — c'est le seul besoin de `choose_targets` (sorts à cibles
    multiples du même camp, cf. SpellPlan.extra_targets) : rien d'autre ne
    le passe, et un appel isolé se comporte exactement comme avant.
    """
    # Ces deux verdicts ne regardent pas le plateau, et ne doivent donc pas
    # avoir besoin d'un instantané : la main se pilote ailleurs, et « aucune
    # cible » se sait rien qu'au texte.
    if plan.targeting is Targeting.NONE:
        return None, "aucune cible à désigner"

    if plan.targeting is Targeting.HAND:
        # Le point ne se calcule pas ici : il dépend de QUELLE carte de la
        # main on désigne, ce qui relève de la décision de jeu
        # (actions.choose_hand_targets) et non du classement du texte.
        return None, f"{plan.picks} carte(s) à désigner dans la main"

    ours = [
        c for c in snapshot.board + snapshot.attack_row
        if c.is_unit and c.center not in exclude_points
    ]
    theirs = [
        c for c in snapshot.enemy_board + snapshot.enemy_attack_row
        if c.is_unit and c.center not in exclude_points
    ]
    if plan.target_condition == "attacking":
        # « Stun an attacking enemy » (Tempête d'acier) : le jeu REFUSE le
        # clic sur une unité qui n'attaque pas. Contrairement aux
        # conditions invisibles, celle-ci se lit — ce sont les deux
        # rangées d'attaque, que l'API rapporte à chaque lecture. Filtrer
        # ici, c'est la différence entre « aucune cible, on ne lance
        # pas » et « sort en l'air, annulation ».
        # PAR CARDID, comme partout ailleurs dans le projet : c'est la
        # seule identité stable d'une carte, et elle ne dépend pas de
        # l'objet Python qui la porte.
        engages = {c.card_id for c in snapshot.attack_row}
        engages_eux = {c.card_id for c in snapshot.enemy_attack_row}
        ours = [c for c in ours if c.card_id in engages]
        theirs = [c for c in theirs if c.card_id in engages_eux]
        if not ours and not theirs:
            return None, "aucune unité engagée dans l'attaque"

    if plan.target_condition in ("follower", "champion"):
        # UN SUIVANT N'EST PAS UN CHAMPION. « Charm an enemy FOLLOWER »
        # (Beckoning Gaze, 98SB015) : le jeu refuse le clic sur un
        # champion, et le sort reste en l'air — mesuré deux fois sur
        # Karma le 05/11/2026, 23 s à chaque fois.
        #
        # ON REFUSE DANS LE DOUTE, comme `is_damaged` : une carte absente
        # de card_sets n'a pas de `supertype`, donc `is_champion` la
        # donnerait pour un suivant sans rien en savoir. Un clic refusé
        # coûte plus cher qu'une carte gardée en main.
        veut_un_champion = plan.target_condition == "champion"

        def correspond(carte):
            return carte.known and carte.is_champion == veut_un_champion

        ours = [c for c in ours if correspond(c)]
        theirs = [c for c in theirs if correspond(c)]
        # LE MOTIF NOMME LE CAMP QUAND LE SORT N'EN VISE QU'UN. Sinon le
        # journal lirait « aucun ennemi en jeu » devant un plateau adverse
        # PLEIN de champions, et `journal.py --ecartees` désignerait le
        # mauvais chantier. Notre nexus, lui, garde sa chance : il n'est
        # ni suivant ni champion, mais c'est l'AUTRE point du même clic.
        en_jeu = {Targeting.ALLY: ours, Targeting.ENEMY: theirs}.get(
            plan.targeting, ours + theirs)
        if not en_jeu and not (plan.targeting is Targeting.ALLY
                               and plan.our_nexus_is_target):
            manquant = "champion" if veut_un_champion else "suivant"
            return None, f"aucun {manquant} en jeu"

    if plan.target_condition == "damaged":
        # Le jeu N'ACCEPTE PAS le clic sur une unité intacte : filtrer ici,
        # c'est ce qui sépare « aucune cible, on ne lance pas » de « sort
        # en l'air, annulation ». Une unité dont les PV n'ont pas été lus
        # à l'écran n'est pas réputée blessée : on refuse dans le doute.
        ours = [c for c in ours if is_damaged(c)]
        theirs = [c for c in theirs if is_damaged(c)]
        if not ours and not theirs:
            return None, "aucune unité blessée en jeu (PV lus à l'écran)"

    def biggest(cards):
        return max(cards, key=lambda c: (c.attack + c.health, c.attack), default=None)

    def best_kill(cards, damage):
        """
        Le plus gros ennemi que ces dégâts suffisent à tuer. `damage` est
        le montant pour un suivant ; un champion prend `plan.damage_to`
        (« Deal 2 to a champion or 4 to a follower »).
        """
        def dealt(c):
            return plan.damage_to(c) if plan.amount_champion is not None else damage
        killable = [c for c in cards if dealt(c) is not None and c.health <= dealt(c)]
        return biggest(killable)

    def gift_to_ally(cards):
        """
        La meilleure receveuse d'un renfort ou d'un équipement.

        La plus grosse, MAIS PAS UNE ÉPHÉMÈRE : le bonus disparaît avec
        elle en fin de round, et une Éphémère est justement souvent le
        plus gros corps du banc — `biggest` la choisissait donc en
        priorité. À défaut de toute autre unité elle reste une cible
        valable : le sort doit bien partir, sinon le client attend un
        clic qui ne vient pas.
        """
        return biggest([c for c in cards if not keywords.dies_anyway(c)]) or biggest(cards)

    def gift_to_enemy(cards):
        """
        Un renfort qu'on est FORCÉ de donner à l'adversaire (sans
        restrictions seulement) : sur ce qui va disparaître de son banc
        de toute façon, et à défaut sur sa plus petite unité.
        """
        return min(
            cards,
            key=lambda c: (0 if keywords.dies_anyway(c) else 1, c.attack + c.health, c.attack),
            default=None,
        )

    def sacrifice(cards):
        """
        « Kill an ally » : ce qu'on regrettera le moins.

        `keywords.death_cost` d'abord — une Éphémère ou une Sans-mort ne
        coûte rien, quelle que soit sa taille — puis la plus maigre.
        Même logique que `actions.sacrifice_rank` pour la main.
        """
        return min(
            cards,
            key=lambda c: (keywords.death_cost(c), c.attack + c.health, c.attack),
            default=None,
        )

    def survivor(cards, damage):
        """
        « Deal N to an ally » : celle qui ENCAISSE sans mourir, la plus
        solide d'abord (PV lus à l'écran quand on les a). Personne ne
        survit : on retombe sur la sacrifiée. Une Éphémère survivante
        passe devant — elle disparaît de toute façon en fin de round.
        """
        if damage is None:
            return None
        alive = [c for c in cards if c.health > damage]
        return min(
            alive,
            key=lambda c: (keywords.death_cost(c), -c.health, -c.attack),
            default=None,
        )

    if plan.stat_override:
        # DES STATISTIQUES RÉÉCRITES NE SONT NI UN CADEAU NI UN MALUS :
        # ça dépend entièrement de qui on vise. « Set a unit's stats to
        # 1|6 » (Défense paniquée, 05BC209) neutralise un gros attaquant
        # adverse et sabote une de nos unités — vu en jeu le 06/11/2026,
        # lancée sur NOTRE Mage aux miroirs 4/7, ramenée à 1/6.
        #
        # Aucune famille d'effet ne peut trancher, alors on PÈSE. Pas de
        # barème neuf : `keywords.unit_value`, celui qui sert déjà à
        # comparer deux échanges, appliqué à l'unité avant et après. Un
        # allié nous rapporte ce qu'il gagne, un ennemi ce qu'il perd.
        force, vie = plan.stat_override

        class Reecrite:
            """
            La même unité, avec d'autres statistiques.

            `BoardCard.attack` et `.health` sont DÉRIVÉS (stat imprimée ou
            lue à l'écran) : `dataclasses.replace` les refuse. On délègue
            donc tout le reste à l'originale, pour que `unit_value` reste
            la seule et même formule des deux côtés — mots-clés et bonus
            de champion compris.
            """

            def __init__(self, card):
                self._card = card
                self.attack = force
                self.health = vie

            def __getattr__(self, nom):
                return getattr(self._card, nom)

        def gain(card, mien):
            ecart = keywords.unit_value(Reecrite(card)) - keywords.unit_value(card)
            return ecart if mien else -ecart

        candidats = [(gain(c, True), c) for c in ours] + [(gain(c, False), c) for c in theirs]
        if not candidats:
            return None, "aucune unité en jeu"
        meilleur, cible = max(candidats, key=lambda x: (x[0], x[1].attack + x[1].health))
        if meilleur <= 0:
            # PERSONNE N'Y GAGNE : on ne lance pas. Le jeu accepterait le
            # clic, mais un sort qui ne fait du mal qu'à son lanceur n'a
            # pas de cible valable — et `playable_cards` le gardera en
            # main plutôt que de le gâcher.
            return None, "personne n'y gagne (stats réécrites)"
        return cible.center, f"{cible} (réécrite en {force}|{vie}, gain {meilleur})"

    if plan.targeting is Targeting.ALLY:
        # Un effet néfaste sur notre propre camp n'arrive que sans
        # restrictions (ou comme COÛT d'un échange) : on donne la moins
        # regrettable, pas la meilleure — et pour des dégâts, une unité
        # qui y survit plutôt qu'une qui en meurt.
        # ... SAUF SI ELLE REVIENT (cf. RETURNS) : endormie, rappelée ou
        # capturée, l'unité n'est pas perdue, l'effet est un MOYEN, et on
        # le met sur notre meilleure unité comme un bienfait.
        if plan.harmful and plan.effect not in RETURNS:
            target = (survivor(ours, plan.amount) if plan.effect == "DAMAGE" else None) or sacrifice(ours)
        else:
            target = gift_to_ally(ours)
        if target:
            return target.center, str(target)
        if plan.our_nexus_is_target:
            # « Heal an ally OR YOUR NEXUS 3 » : le banc est vide, le
            # texte offre l'autre point, et celui-là ne quitte jamais le
            # plateau. Même geste qu'en face pour `Targeting.ANYTHING`,
            # exclusion comprise : notre nexus est UNE cible, donc il
            # s'exclut comme une autre — sans quoi un sort à deux clics
            # le rendrait deux fois, et le second ne prendrait pas.
            if snapshot.our_nexus and snapshot.our_nexus not in exclude_points:
                return snapshot.our_nexus, "notre nexus"
        return None, "aucun allié en jeu"

    if plan.targeting is Targeting.ENEMY:
        if plan.effect in HELPFUL:
            # Renfort dirigé sur l'adversaire, autre cas que seule
            # l'absence de restrictions laisse passer : au moins, qu'il
            # profite le moins possible — d'abord ce qui va quitter son
            # banc de toute façon.
            target = gift_to_enemy(theirs)
            return (target.center, str(target)) if target else (None, "aucun ennemi en jeu")
        target = best_kill(theirs, plan.amount) or biggest(theirs)
        return (target.center, str(target)) if target else (None, "aucun ennemi en jeu")

    if plan.targeting is Targeting.ANY_UNIT:
        if plan.harmful:
            target = best_kill(theirs, plan.amount) or biggest(theirs)
            return (target.center, str(target)) if target else (None, "aucun ennemi en jeu")
        target = gift_to_ally(ours)
        if target is None and plan.effect == "AUTRE" and theirs:
            # Effet INCONNU sur « a unit », sans allié : le jeu exigera quand
            # même un clic (06/09/2026, un pouvoir « Play: » posé sans cible a
            # figé la partie 55 s, seize fois). Un ennemi vaut mieux qu'un
            # sort en l'air — et un effet qu'on ne sait pas lire a autant de
            # chances d'être un malus qu'un cadeau.
            target = biggest(theirs)
            return target.center, f"{target} (effet inconnu, faute d'allié)"
        return (target.center, str(target)) if target else (None, "aucun allié en jeu")

    if plan.targeting is Targeting.ANYTHING:
        # « Deal 3 to anything » : tuer une unité vaut mieux que taper le
        # nexus, sauf si rien n'est à portée — auquel cas le nexus est une
        # cible toujours valide, ce qui évite un ciblage sans issue.
        target = best_kill(theirs, plan.amount)
        if target:
            return target.center, str(target)
        # LE NEXUS EST UNE CIBLE COMME UNE AUTRE, DONC IL S'EXCLUT COMME
        # UNE AUTRE. Sans ce test, un sort à cibles multiples le rendait
        # à CHAQUE appel : Trueshot Barrage (01PZ004, « Deal 3 to an
        # enemy or the enemy Nexus, 2 to another, and 1 to another. »)
        # face à un plateau vide rendait trois fois le même point,
        # `choose_targets` comptait trois cibles, et le bot cliquait
        # trois fois le nexus — alors que « another » interdit justement
        # de redésigner ce qu'on vient de désigner. Le deuxième clic ne
        # prend pas, le client attend, la partie fige.
        if snapshot.enemy_nexus and snapshot.enemy_nexus not in exclude_points:
            return snapshot.enemy_nexus, "nexus adverse"
        target = biggest(theirs)
        return (target.center, str(target)) if target else (None, "aucune cible en jeu")

    return None, "ciblage refusé"


def choose_targets(plan: SpellPlan, snapshot) -> list:
    """
    Les points de TOUTES les cibles d'un sort à cibles multiples du même
    camp (cf. SpellPlan.extra_targets), un par clic, dans l'ordre où ils
    seront cliqués.

    « Deal 2 to an enemy and Stun another. » (Lien cosmique / Cosmic
    Binding, 06BC044) veut deux ennemis DIFFÉRENTS : chaque appel exclut
    donc les points déjà choisis avant de redemander une cible à
    `choose_target`, sans quoi le même ennemi serait désigné deux fois —
    ce que « another » exclut justement par construction.

    Peut rendre MOINS de cibles que `plan.total_targets` si le plateau
    n'en offre pas assez (deux ennemis demandés, un seul en jeu) : à
    l'appelant de vérifier avant de jouer le sort, plutôt que de laisser
    le client en attente d'un clic qui ne viendra jamais.
    """
    exclude, picks = set(), []
    for _ in range(max(plan.total_targets, 1)):
        point, description = choose_target(plan, snapshot, exclude_points=frozenset(exclude))
        if point is None:
            break
        picks.append((point, description))
        exclude.add(point)
    return picks


def _stat_value(card) -> int:
    return int(getattr(card, "attack", 0) or 0) + int(getattr(card, "health", 0) or 0)


def choose_trade_targets(plan: SpellPlan, snapshot) -> tuple:
    """
    Les cibles d'un ÉCHANGE (cf. SpellPlan.sequence) : rend
    ([(point, description), ...], raison). `raison` est vide quand
    l'échange vaut le coup et que chaque pas a sa cible ; sinon la liste
    est vide et la raison dit pourquoi — et le sort n'est pas lancé.

    Le coût se choisit d'abord (le moins regrettable, ou une survivante
    aux dégâts), la récompense ensuite en excluant le point déjà pris.
    Puis on PÈSE : ce qu'on perd contre ce qu'on obtient.
        - coût KILL : les stats de la sacrifiée (0 si elle mourait de
          toute façon, cf. keywords.death_cost) ;
        - coût DAMAGE : 0 si elle survit, ses stats sinon ;
        - récompense KILL, ou DAMAGE qui tue : les stats de la victime ;
          STUN / autre malus : son attaque (le tempo d'un round).
    On lance si la récompense atteint le coût. Un échange à perte n'est
    pas une incapacité, c'est une décision : le sort attend un meilleur
    moment, et le journal le range dans le contexte de la partie.
    """
    if not plan.is_trade:
        return [], "pas un échange"
    if plan.duel:
        return choose_duel_targets(plan, snapshot)
    picks, exclude = [], set()
    steps = plan.steps()
    for step in steps:
        point, description = choose_target(step, snapshot, exclude_points=frozenset(exclude))
        if point is None:
            return [], f"échange : {description} ({step.effect.lower()} sur {step.targeting.value})"
        picks.append((point, description))
        exclude.add(point)

    def unit_at(point):
        for card in snapshot.board + snapshot.attack_row + snapshot.enemy_board + snapshot.enemy_attack_row:
            if card.center == point:
                return card
        return None

    cost_step, reward_step = steps[0], steps[-1]
    paid = unit_at(picks[0][0])
    gained = unit_at(picks[-1][0])
    cost = 0
    if paid is not None:
        if cost_step.effect == "KILL":
            cost = 0 if keywords.death_cost(paid) == 0 else _stat_value(paid)
        elif cost_step.effect == "DAMAGE":
            dies = cost_step.amount is not None and paid.health <= cost_step.amount
            cost = _stat_value(paid) if dies else 0
        else:
            cost = _stat_value(paid) // 2
    reward = 0
    if gained is not None and not gained.local:
        kills = reward_step.effect == "KILL" or (
            reward_step.effect == "DAMAGE" and reward_step.amount is not None
            and gained.health <= reward_step.amount
        )
        reward = _stat_value(gained) if kills else int(gained.attack or 0)
    elif gained is None and reward_step.targeting is Targeting.ANYTHING:
        reward = reward_step.amount or 1        # le nexus adverse
    if reward < cost or reward == 0:
        return [], (f"échange défavorable : perdre {picks[0][1]} ({cost}) "
                    f"pour {picks[-1][1]} ({reward})")
    return picks, ""


def choose_duel_targets(plan: SpellPlan, snapshot) -> tuple:
    """
    Les deux cibles d'un DUEL DIRIGÉ, dans l'ordre des clics du texte :
    rend ([(point, description), (point, description)], raison).

    On essaie TOUTES les paires (allié, ennemi) et on simule le combat
    singulier (`keywords.resolve_duel`, l'allié frappe en attaquant) après
    avoir appliqué le malus d'attaque à l'ennemi s'il y en a un. Score :
        + valeur de l'ennemi s'il meurt,
        - valeur de l'allié s'il meurt (0 s'il mourait de toute façon),
        + un peu pour les dégâts infligés sinon.
    On lance seulement si la meilleure paire tue l'ennemi sans perdre
    plus qu'elle ne gagne. Sinon le sort attend un meilleur moment — c'est
    une décision, pas une incapacité.
    """
    from dataclasses import replace as _replace

    ours = [c for c in snapshot.board + snapshot.attack_row if c.is_unit and c.local]
    theirs = [c for c in snapshot.enemy_board + snapshot.enemy_attack_row if c.is_unit]
    if not ours:
        return [], "duel : aucun allié en jeu"
    if not theirs:
        return [], "duel : aucun ennemi en jeu"

    def weakened(enemy):
        if not plan.duel_enemy_attack_delta:
            return enemy
        return _replace(enemy, attack_read=max(0, int(enemy.attack or 0) + plan.duel_enemy_attack_delta))

    best, best_score = None, None
    for ally in ours:
        for enemy in theirs:
            duel = keywords.resolve_duel(ally, weakened(enemy))
            score = 0
            if duel.blocker_dies:
                score += _stat_value(enemy)
            else:
                score += min(int(ally.attack or 0), int(enemy.health or 0)) // 2
            if duel.attacker_dies:
                score -= 0 if keywords.death_cost(ally) == 0 else _stat_value(ally)
            if best_score is None or score > best_score:
                best, best_score = (ally, enemy, duel), score

    ally, enemy, duel = best
    if not duel.blocker_dies or best_score <= 0:
        return [], (f"duel défavorable : {ally} contre {enemy} "
                    f"({'tue' if duel.blocker_dies else 'ne tue pas'}, "
                    f"{'meurt' if duel.attacker_dies else 'survit'})")
    by_side = {Targeting.ALLY: (ally.center, str(ally)), Targeting.ENEMY: (enemy.center, str(enemy))}
    return [by_side[step.targeting] for step in plan.steps()], ""


# ============================================================
# LE MODE DANS LEQUEL LES COMMANDES RÉPONDENT
# ============================================================
# `restricted=True` EST LE DÉFAUT DES FONCTIONS, PAS CELUI DU BOT
# (réparé le 09/11/2026). `classify_text` et `classify_card` gardent ce
# défaut prudent parce que c'est le comportement que décrivent les tests
# les plus anciens ; mais le bot, lui, décide depuis le 26/08 avec
# `actions.CARD_RESTRICTIONS = False`, et il le passe explicitement à
# chacun de ses appels.
#
# `python spells.py explain` et `coverage`, eux, prenaient le défaut.
# Ils répondaient donc sur un bot imaginaire — et c'est précisément la
# commande qu'on interroge pour comprendre pourquoi une carte n'a pas
# été jouée. Mesuré sur la base le 09/11 : **150 cartes refusées en
# prudent que le bot joue quand même** (237 refus contre 87 sur les 1125
# sorts et capacités ; 126 contre 51 sur les 566 collectionnables).
# « Recall an ally. » (01IO011) sortait « REFUSÉ — recall dirigé sur
# notre propre unité » alors que le bot la joue à chaque partie.
#
# ON NE REDÉCLARE PAS LE MODE ICI, ON VA LE LIRE CHEZ CELUI QUI LE PORTE
# — même réparation qu'`actions.is_dead_weight` la veille, et même
# raison : deux sources pour une seule grandeur finissent toujours par
# diverger en silence. L'import est TARDIF (actions importe spells : au
# niveau module ce serait un cycle) et son échec n'est pas une panne —
# une commande de diagnostic doit répondre même si `actions` est
# injoignable, et elle répond alors dans le mode du bot par défaut.
def mode_du_bot() -> bool:
    """Le mode dans lequel le bot DÉCIDE : True = prudent."""
    try:
        import actions
        return bool(actions.CARD_RESTRICTIONS)
    except Exception:
        return False


def _mode_demande(restricted) -> bool:
    """`None` veut dire « celui du bot » ; un booléen s'impose."""
    return mode_du_bot() if restricted is None else bool(restricted)


def nom_du_mode(restricted: bool) -> str:
    """Comment la sortie des commandes nomme son mode."""
    return ("PRUDENT (--prudent) — ce n'est PAS ainsi que le bot décide"
            if restricted else
            "restrictions levées (celui du bot)")


# ============================================================
# COUVERTURE
# ============================================================

def coverage_report(card_sets_path=None, restricted=None) -> dict:
    """
    Passe toute la base de cartes au classifieur et compte les verdicts.

    C'est la mesure honnête de « on gère tous les sorts » : un chiffre,
    pas une promesse. À relancer après chaque nouveau set.

    `restricted=None` (le défaut) interroge le classifieur dans le mode
    où le BOT décide — cf. `mode_du_bot`. True force le mode prudent.
    """
    restricted = _mode_demande(restricted)
    if card_sets_path is None:
        import lor_api
        card_sets_path = lor_api.CARD_SETS_PATH

    folder = Path(card_sets_path)
    spells = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.load(open(path, encoding="utf8"))
        except (OSError, json.JSONDecodeError):
            continue
        for card in data:
            if card.get("type") in ("Spell", "Ability"):
                spells.append(card)

    collectible = [s for s in spells if s.get("collectible")]
    counts, reasons, examples = {}, {}, {}

    for card in collectible:
        plan = classify_card(card, restricted=restricted)
        key = (plan.effect, plan.targeting.name)
        counts[key] = counts.get(key, 0) + 1
        examples.setdefault(key, []).append(card["name"])
        if not plan.playable:
            reasons[plan.reason] = reasons.get(plan.reason, 0) + 1

    return {
        "total": len(spells),
        "collectible": len(collectible),
        "counts": counts,
        "reasons": reasons,
        "examples": examples,
        "restricted": restricted,
    }


def cmd_coverage(card_sets_path=None, restricted=None) -> None:
    restricted = _mode_demande(restricted)
    report = coverage_report(card_sets_path, restricted=restricted)
    total = report["collectible"]
    if not total:
        print("Aucun sort trouvé — vérifie le chemin de card_sets.")
        return

    refused = sum(v for (_, t), v in report["counts"].items() if t == "REFUSED")
    playable = total - refused

    print(f"Mode : {nom_du_mode(restricted)}\n")
    print(f"{report['total']} sorts et capacités, dont {total} collectionnables\n")
    print(f"  jouables            {playable:>4}  ({100 * playable / total:.0f} %)")
    print(f"  refusés sciemment   {refused:>4}  ({100 * refused / total:.0f} %)\n")

    print("Motifs de refus :")
    for reason, number in sorted(report["reasons"].items(), key=lambda x: -x[1]):
        print(f"  {number:>4}  {reason}")

    print(f"\n{'effet':<10} {'ciblage':<12} {'n':>4}  exemples")
    print("-" * 74)
    for (effect, targeting), number in sorted(report["counts"].items(), key=lambda x: -x[1]):
        if targeting == "REFUSED":
            continue
        sample = ", ".join(report["examples"][(effect, targeting)][:3])
        print(f"{effect:<10} {targeting:<12} {number:>4}  {sample[:44]}")


def cmd_explain(text: str, restricted=None) -> None:
    restricted = _mode_demande(restricted)
    plan = classify_text(text, restricted=restricted)
    print(f"\nTexte    : {text}")
    print(f"Mode     : {nom_du_mode(restricted)}")
    print(f"Verdict  : {plan}")
    print(f"Jouable  : {'oui' if plan.playable else 'NON'}")
    # Un coût payé en main EST suivi d'un clic de plateau : répondre
    # « non » ici ferait mentir le diagnostic sur ce que le bot va faire.
    clique = plan.needs_click or plan.needs_board_click_after_hand
    print(f"Clic     : {'oui' if clique else 'non'}")
    print(f"Néfaste  : {'oui' if plan.harmful else 'non'}")
    if plan.target_condition:
        # LA CONDITION DÉCIDE, DONC ELLE S'AFFICHE. « Charm an enemy
        # follower » et « Charm an enemy » rendaient le même verdict
        # ligne à ligne ; c'est justement la différence qu'on vient
        # lire ici quand un sort n'a pas été lancé.
        print(f"Condition: la cible doit être « {plan.target_condition} »")

    # LES 150 CARTES QUI CHANGENT DE VERDICT MÉRITENT QU'ON LE DISE.
    # Répondre dans le bon mode ne suffit pas : quand les deux modes ne
    # s'accordent pas, c'est l'information la plus utile de la commande —
    # et la seule façon de voir d'un coup d'œil que l'autre mode
    # raconterait autre chose de la même carte.
    autre = classify_text(text, restricted=not restricted)
    if (autre.playable, autre.effect, autre.targeting) != (
            plan.playable, plan.effect, plan.targeting):
        etiquette = "restrictions levées" if restricted else "prudent"
        verdict = "jouable" if autre.playable else f"REFUSÉ — {autre.reason}"
        print(f"           (en mode {etiquette} : {verdict})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Classement des sorts (LoR).")
    sub = parser.add_subparsers(dest="command")

    # `--prudent` porte le même nom que l'option du bot (`actions.py
    # --prudent`) et fait la même chose : rétablir les refus de PRUDENCE.
    # Sans elle, les deux commandes répondent comme le bot décide.
    aide_prudent = ("répondre en mode prudent (restrictions rétablies) "
                    "au lieu du mode dans lequel le bot décide")

    cov = sub.add_parser("coverage", help="taux de couverture sur toute la base")
    cov.add_argument("--sets", default=None, help="dossier card_sets")
    cov.add_argument("--prudent", action="store_true", help=aide_prudent)

    exp = sub.add_parser("explain", help="analyse un texte de sort")
    exp.add_argument("text")
    exp.add_argument("--prudent", action="store_true", help=aide_prudent)

    args = parser.parse_args()
    # `--prudent` absent vaut None, pas False : None veut dire « demande
    # son mode au bot », et c'est ce qui garde la commande fidèle le jour
    # où `actions.CARD_RESTRICTIONS` changerait de valeur.
    restricted = True if getattr(args, "prudent", False) else None
    if args.command == "explain":
        cmd_explain(args.text, restricted=restricted)
    else:
        cmd_coverage(getattr(args, "sets", None), restricted=restricted)


if __name__ == "__main__":
    main()
