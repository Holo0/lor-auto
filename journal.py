#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
journal.py

Enregistre le résultat de chaque combat, et les agrège.

    python journal.py            # taux de victoire par configuration
    python journal.py --last 10  # les dix derniers combats
    python journal.py --reset    # repartir de zéro
    python journal.py --ecartees # cartes écartées en jeu, par motif : le backlog du bot
    python journal.py --champions         # taux de victoire par (palier, étoiles)
    python journal.py --depuis 2026-11-01 # ne lire que depuis cette date
    python journal.py --depuis tout       # tout l'historique
    python journal.py --jours 7           # la semaine écoulée

TOUTES LES VUES SONT DATÉES — et par défaut elles ne lisent que les
FENETRE_DEFAUT_JOURS derniers jours. Pourquoi : voir « LA FENÊTRE »
plus bas.

--------------------------------------------------------------------
POURQUOI
--------------------------------------------------------------------
Sans ça, chaque réglage est une intuition. `--max-cost 3` vaut-il mieux
que `--max-cost 4` ? Les sorts améliorent-ils vraiment le résultat ?
Baisser NEXUS_DAMAGE_WEIGHT rend-il le bot meilleur ou juste timide ?

Impossible à trancher de mémoire, sur quelques parties observées. Une
ligne par combat, avec la configuration qui l'a produit, et la question
devient une comparaison de taux de victoire.

C'est l'outil qui rend toutes les autres améliorations mesurables — donc
celui qui aurait dû exister en premier.

Le format est du JSONL : une ligne de JSON par combat, ajoutée à la fin.
Illisible pour rien, incassable en cas d'arrêt brutal, et exploitable
avec n'importe quel outil.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional

import lor_api

JOURNAL_PATH = lor_api.PROJECT_ROOT / "journal.jsonl"

# Champs de configuration qui influencent le jeu, et donc selon lesquels
# il est pertinent de regrouper les résultats.
CONFIG_FIELDS = ("restrictions", "spells", "chump", "max_cost", "nexus_weight", "screen_costs", "ocr",
                 # L'archétype du deck (strategy.py) : la question « quel plan de
                 # jeu gagne ? » se lit ici. `champions` est journalisé aussi,
                 # mais grouper par champion émietterait les statistiques.
                 "archetype")


_DIGITS = re.compile(r"\d+")

# Motifs qui décrivent la PARTIE, pas une incapacité du bot : trop cher ce
# tour-ci, plateau plein, cible absente. Ils comptent, mais à part — le
# classement « ce que le bot ne sait pas jouer » ne doit pas être noyé
# par « pas assez de mana », qui arrive à chaque tour et se règle tout seul.
CONTEXT_PREFIXES = ("coût ", "il faut ", "sort : sort lent", "sort : aucune cible",
                    "sort : aucun allié", "sort : aucun ennemi", "sort : aucune unité",
                    "sort : N cibles requises", "sort : échange", "pas classée en main")


def normalize_reason(reason: str) -> str:
    """« coût 3 (lu à l'écran) > mana 2 » -> « coût N (lu à l'écran) > mana N »."""
    return _DIGITS.sub("N", (reason or "").strip())


# --------------------------------------------------------------------
# LA FENÊTRE
# --------------------------------------------------------------------
# `--ecartees` est la BOUSSOLE du projet : « la forme en haut du tableau
# est la prochaine à coder ». Au 08/11/2026 elle cumulait 142 lignes
# depuis le 07/08/2026, sans aucun filtre de date, et désignait donc des
# bogues MORTS. Mesuré ce jour-là, motif par motif et jour par jour :
#
#   « pose ratée : mise de côté pour ce tour »   33 fois — 9 le 05/09,
#       24 le 06/09, et PLUS JAMAIS ENSUITE : ce motif n'existe même plus
#       dans le code (renommé le 06/09 avec la mise en place de `carry`).
#       Il était 2e du classement, et « Buhru Lookout ×14 » — la saisie
#       dans une main pleine, corrigée le 06/09/2026 par mark_hand_overlap
#       — en tête de ses cartes.
#   « sort : N cibles à cliquer »                25 fois, dont 17 le 06/09 :
#       3e sur tout l'historique, 4e sur les trente derniers jours.
#   « pouvoir à cibler : N carte(s) à désigner » 10 fois, TOUTES le 06/11 :
#       invisible au classement général, 2e ex æquo dans la fenêtre.
#
# D'OÙ LA FENÊTRE PAR DÉFAUT, et non une option à penser à taper : une
# boussole qu'il faut armer avant de la croire n'est pas une boussole.
# Le changement de sens de la commande est assumé, mais il est DIT : chaque
# vue écrit sa fenêtre dans son en-tête et rappelle `--depuis tout`.
FENETRE_DEFAUT_JOURS = 30

_DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}")


def date_de(entry) -> Optional[str]:
    """
    La date AAAA-MM-JJ d'une ligne, ou None si elle n'en porte pas de
    LISIBLE.

    On ne devine jamais : « 06/09/2026 » rend None plutôt qu'une date
    approchée — même règle que `champions.lire_palier`, qui refuse un
    nombre dont un glyphe manque plutôt que d'en inventer un.
    """
    found = _DATE_RX.search(str(entry.get("horodatage") or ""))
    return found.group(0) if found else None


def borne_depuis(depuis=None, jours=None, aujourdhui=None) -> Optional[str]:
    """
    Traduit les options en une borne basse AAAA-MM-JJ, ou None = « tout ».

    `--depuis` l'emporte sur `--jours` ; sans l'un ni l'autre, la fenêtre
    par défaut. `aujourdhui` n'existe que pour les tests : une suite dont
    le verdict change avec le calendrier ne vaut rien.
    """
    if depuis is not None:
        texte = str(depuis).strip().lower()
        if texte in ("tout", "all", "*"):
            return None
        if not _DATE_RX.fullmatch(texte):
            raise ValueError(
                f"date illisible : « {depuis} ». Format attendu : AAAA-MM-JJ "
                "(ou « tout » pour l'historique entier).")
        # LA FORME NE SUFFIT PAS : « 2026-13-45 » passe le gabarit et n'est
        # pas une date. Comparee telle quelle (l'ordre des chaines ISO vaut
        # celui du calendrier), elle VIDAIT la fenetre sans rien dire de plus
        # qu'un « Aucun combat » - exactement le filtrage silencieux que
        # cette option existe pour empecher. On la refuse comme on refuse
        # « 06/09/2026 » : par un `parser.error`, jamais par un tableau vide.
        try:
            datetime.date.fromisoformat(texte)
        except ValueError:
            raise ValueError(
                f"date impossible : « {depuis} ». Format attendu : AAAA-MM-JJ "
                "(ou « tout » pour l'historique entier).") from None
        return texte
    if jours is None:
        jours = FENETRE_DEFAUT_JOURS
    base = aujourdhui or time.strftime("%Y-%m-%d")
    try:
        jour = (datetime.date.fromisoformat(base)
                - datetime.timedelta(days=max(0, int(jours))))
    except OverflowError:
        # UNE SECONDE FAÇON DE DEMANDER L'IMPOSSIBLE, et elle sortait par
        # un TRACEBACK (09/11/2026) là où « 2026-13-45 » est refusé
        # proprement depuis le 08/11. Mesuré depuis le 2026-11-08
        # (ordinal 739928, donc 739 927 jours de recul au maximum) :
        # `--jours 739999` et `--jours 4000000` lèvent « date value out
        # of range » à la soustraction, `--jours 100000000000` lève
        # « Python int too large to convert to C int » dès la
        # construction du timedelta. Les trois sont des OverflowError,
        # et les trois décrivent la MÊME demande : remonter avant le
        # calendrier. On la nomme, et on renvoie vers l'option qui fait
        # déjà ce travail.
        #
        # ON NE REFUSE QUE CE QUI NE SE CALCULE PAS : `--jours 739000`
        # tombe en l'an 3 et reste une fenêtre parfaitement valide, qui
        # vaut « tout l'historique ».
        raise ValueError(
            f"fenêtre impossible : « {jours} » jour(s) remonte avant le "
            "calendrier. « --depuis tout » fait déjà ce que vous demandez."
        ) from None
    return jour.isoformat()


def fenetre(entries, depuis: Optional[str]):
    """
    Ne garde que les lignes à partir de `depuis` ; rend
    (gardées, exclues, sans_date).

    UNE LIGNE SANS DATE LISIBLE EST GARDÉE. On ne peut pas la situer, donc
    on ne peut pas l'exclure honnêtement — et la faire disparaître en
    silence serait exactement le défaut qu'on répare ici. Elle est comptée
    à part pour que la vue le dise. Au 08/11/2026 il n'y en a AUCUNE sur
    les 142 lignes du journal : le cas ne coûte rien et ne se tait pas.
    """
    if depuis is None:
        return list(entries), 0, 0
    gardees, exclues, sans_date = [], 0, 0
    for entry in entries:
        jour = date_de(entry)
        if jour is None:
            sans_date += 1
            gardees.append(entry)
        elif jour >= depuis:
            gardees.append(entry)
        else:
            exclues += 1
    return gardees, exclues, sans_date


# --------------------------------------------------------------------
# CHAQUE VUE COMPTE SES PROPRES LIGNES
# --------------------------------------------------------------------
# Les trois vues ne lisent pas la même chose : les configurations et le
# backlog lisent des COMBATS (et le backlog, seulement ceux qui portent
# un champ `ecartees` — il n'existe que depuis le 05/09/2026), `--champions`
# lit des TENTATIVES. Elles appelaient pourtant `fenetre` sur le journal
# ENTIER, puis triaient : le compte des exclues portait donc sur des
# lignes dont la plupart ne les concernaient pas.
#
# Mesuré sur journal.jsonl le 09/11/2026 — 145 lignes, 111 combats,
# 34 tentatives, fenêtre de trente jours :
#
#   exclues annoncées par les TROIS vues ................ 68
#   exclues qui concernent `--champions` ................. 0  (toutes les
#       tentatives sont dans la fenêtre ; les 68 sont des combats)
#   exclues qui concernent `--ecartees` .................. 15 (53 des 68
#       combats n'ont pas de champ `ecartees`)
#   exclues qui concernent le tableau des configurations . 68 (juste, par
#       accident : cette vue compte justement les combats)
#
# `--champions` renvoyait donc vers un `--depuis tout` qui affiche
# EXACTEMENT le même tableau. Une boussole qui s'excuse de ne pas tout
# montrer alors qu'elle montre tout apprend à se faire ignorer — et le
# jour où le compte dit vrai, personne ne le lit plus.
#
# D'où la règle : ON FILTRE D'ABORD, ON FENÊTRE ENSUITE. Une ligne que la
# vue ne compte pas ne doit ni gonfler son compte d'exclues, ni voler une
# place dans son `--last`.
def libelle_fenetre(depuis: Optional[str], n: int, mot: str = "combat") -> str:
    """« 41 combat(s) depuis le 2026-10-09 » / « 109 combat(s), tout l'historique »."""
    if depuis is None:
        return f"{n} {mot}(s), tout l'historique"
    return f"{n} {mot}(s) depuis le {depuis}"


def rappel_fenetre(depuis: Optional[str], exclues: int = 0, sans_date: int = 0,
                   mot: str = "ligne") -> None:
    """
    La ligne qui empêche de croire qu'on lit tout l'historique.

    Elle est imprimée par les TROIS vues, même quand rien n'a été exclu :
    c'est le seul endroit où le lecteur apprend que la commande a une
    fenêtre, et comment l'ouvrir en grand.

    `exclues` COMPTE CE QUE CETTE VUE-LÀ AURAIT COMPTÉ, et `mot` le
    nomme — pourquoi : voir « CHAQUE VUE COMPTE SES PROPRES LIGNES ».
    """
    if depuis is None:
        return
    if exclues:
        print(f"(hors fenêtre : {exclues} {mot}(s) avant le {depuis} — "
              "`--depuis tout` pour l'historique entier.)")
    else:
        print(f"(fenêtre : depuis le {depuis} — "
              "`--depuis tout` pour l'historique entier.)")
    if sans_date:
        print(f"({sans_date} {mot}(s) sans date lisible : on ne les situe "
              "pas, on les garde.)")
    print()


def is_context_reason(motif: str) -> bool:
    return motif.startswith(CONTEXT_PREFIXES)


def _verdict_fields(report) -> dict:
    """Les champs qui portent l'issue du combat — les seuls que `conclude` retouche."""
    return {
        "gagne": report.won,
        "termine": report.finished,
        "arret": report.reason,
        # D'OÙ VIENT LE VERDICT. Au 05/09/2026, 53 combats sur 53 avaient
        # `gagne: null` : l'API `/game-result` reste muette en défi, et
        # le seul juge est l'écran (second « Continuer » = défaite,
        # aventure qui continue = victoire). Sans cette provenance, un
        # `true` lu à l'API et un `true` déduit de l'écran sont
        # indiscernables — et le jour où l'un des deux se trompe, on ne
        # sait pas lequel.
        "verdict": getattr(report, "verdict", "") or "",
    }


def record(report, config: Optional[dict] = None, path: Path = JOURNAL_PATH) -> dict:
    """
    Ajoute une ligne au journal. Ne lève jamais : perdre une statistique
    ne doit pas interrompre une session de farm.

    La ligne reçoit un `id` que `conclude()` retrouvera : le verdict d'un
    combat de défi n'est connu QU'APRÈS la boucle de combat, quand
    lor_battle a fermé les écrans de fin. `record` écrit donc la ligne au
    plus tôt (un combat interrompu est une donnée) et `conclude` la
    complète.
    """
    entry = {
        # Horodatage + hasard : deux combats dans la même seconde (ou sous
        # l'horloge simulée des tests) ne doivent pas partager un id.
        "id": f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "horodatage": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tours": report.turns_played,
        "cartes": report.cards_played,
        "attaques": report.attacks,
        "blocages": report.blocks,
        "duree": round(report.duration, 1),
        "config": config or {},
        # Cartes écartées et pourquoi : le backlog de ce que le bot ne
        # sait pas encore jouer, trié par `python journal.py --ecartees`.
        "ecartees": list(getattr(report, "rejections", None) or []),
    }
    entry.update(_verdict_fields(report))
    try:
        setattr(report, "journal_id", entry["id"])
    except Exception:       # noqa: BLE001 — un rapport figé n'empêche pas d'écrire
        pass
    try:
        with open(path, "a", encoding="utf8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Journal non écrit ({exc}).")
    return entry


def conclude(report, path: Path = JOURNAL_PATH) -> bool:
    """
    Reporte dans le journal le verdict connu APRÈS la boucle de combat.

    Retrouve la ligne écrite par `record` (même `id`, cherchée depuis la
    fin) et n'y remplace que les champs d'issue : gagne, termine, arret,
    verdict. Rend True si une ligne a été mise à jour. Ne lève jamais.

    POURQUOI RÉÉCRIRE PLUTÔT QU'AJOUTER : une seconde ligne « verdict »
    forcerait tous les lecteurs à recoller les morceaux, et
    `journal.py` (taux de victoire par configuration) lit une ligne par
    combat. Le fichier reste petit (une ligne par combat), la réécriture
    est instantanée, et elle passe par un fichier temporaire renommé
    pour qu'un arrêt brutal ne laisse jamais un journal tronqué.
    """
    journal_id = getattr(report, "journal_id", None)
    if not journal_id:
        return False
    path = Path(path)
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf8").splitlines()
    except OSError as exc:
        print(f"Journal illisible ({exc}).")
        return False

    for index in range(len(lines) - 1, -1, -1):
        raw = lines[index].strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if entry.get("id") != journal_id:
            continue
        entry.update(_verdict_fields(report))
        lines[index] = json.dumps(entry, ensure_ascii=False)
        try:
            tmp = path.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf8")
            tmp.replace(path)
        except OSError as exc:
            print(f"Journal non mis à jour ({exc}).")
            return False
        return True
    return False


def record_attempt(palier, etoiles, gagne, raison, duree=None,
                   combats=0, path: Path = JOURNAL_PATH) -> dict:
    """
    Ajoute une ligne de TENTATIVE (une aventure entière), distincte des
    lignes de combat.

    POURQUOI UNE LIGNE À PART : le journal ne connaissait que des
    combats. Impossible donc de répondre à « quel champion pour quel
    palier ? » — ni les étoiles du champion ni le défi joué n'y
    figuraient. Les défis se débloquant l'un après l'autre (70 au
    total), chaque tentative perdue coûte une tentative ET ne fait
    avancer de rien : c'est cet arbitrage que `python journal.py
    --champions` doit éclairer, avec des parties et non de l'intuition.

    `palier` peut être None tant que le chiffre du défi n'est pas lu :
    la ligne vaut quand même, elle porte les étoiles et l'issue.
    """
    entry = {
        "id": f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "type": "tentative",
        "horodatage": time.strftime("%Y-%m-%d %H:%M:%S"),
        "palier": palier,
        "etoiles": etoiles,
        "gagne": gagne,
        "raison": raison,
        "duree": round(duree, 1) if duree is not None else None,
        "combats": combats,
    }
    try:
        with open(path, "a", encoding="utf8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Journal non écrit ({exc}).")
    return entry


def est_combat(entry) -> bool:
    """
    Les lignes écrites avant le 05/11/2026 n'ont pas de champ `type` :
    une ligne sans type est un COMBAT. Tout ce qui lit les statistiques
    de combat doit filtrer là-dessus, sinon une tentative (sans `config`)
    viendrait polluer le tableau des configurations.
    """
    return entry.get("type", "combat") == "combat"


def tentatives(entries) -> list:
    """Les lignes de tentative seules."""
    return [e for e in entries if e.get("type") == "tentative"]


def read_all(path: Path = JOURNAL_PATH) -> list:
    """Lit le journal en ignorant les lignes abîmées."""
    if not Path(path).exists():
        return []
    entries = []
    with open(path, encoding="utf8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            # Une ligne de JSON VALIDE qui n'est pas un OBJET (« 5 »,
            # « [1,2] ») n'est pas une ligne de journal : gardee, elle fait
            # tomber `date_de`, `est_combat` et les trois vues sur un `.get`
            # introuvable. « En ignorant les lignes abimees » vaut aussi
            # pour celles-la.
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


LABEL_DEFAUT = "(par défaut)"
LABEL_RIEN_DE_PLUS = "(rien de plus)"


def config_key(config: dict) -> str:
    parts = [f"{k}={config.get(k)}" for k in CONFIG_FIELDS if k in config]
    return " ".join(parts) or LABEL_DEFAUT


def tronc_commun(cles):
    """
    Ce que TOUTES les clés de configuration partagent, et ce qui reste de
    chacune une fois ce tronc retiré. Rend (tronc, {clé: ce qui distingue}).

    POURQUOI (09/11/2026) : la colonne « configuration » était cadrée à 40
    caractères, clé TRONQUÉE comprise. Mesuré sur journal.jsonl, les sept
    clés font 41 à 106 caractères et six d'entre elles commencent par les
    mêmes 77 — « restrictions=False spells=False chump=False
    nexus_weight=1.0 screen_costs=True ». `python journal.py --depuis tout`
    affichait donc QUATRE LIGNES RIGOUREUSEMENT IDENTIQUES
    (« restrictions=False spells=False chump=Fa »), alors qu'elles
    comparaient aggro, midrange, tirage et aucun archétype. Le tableau
    censé répondre « quel réglage aide ? » répondait la même chose quatre
    fois — et l'archétype, le seul champ qui les sépare, est le DERNIER de
    CONFIG_FIELDS, donc le premier perdu.

    On ne se contente pas d'élargir la colonne : 106 caractères de clé
    dont 77 recopiés à l'identique sur chaque ligne ne se lisent pas non
    plus. Le tronc est dit UNE fois, au-dessus du tableau, et la colonne
    ne porte plus que la différence — ce qu'on y cherche.

    Un tronc qui avalerait TOUT (une seule configuration, ou des
    configurations identiques) rendrait la colonne muette : dans ce cas on
    n'en retire rien et chaque clé s'écrit entière.
    """
    cles = list(cles)
    if not cles:
        return [], {}
    # « (par défaut) » est un libellé, pas une suite de paires : il ne se
    # découpe pas, et sa présence suffit à ce qu'il n'y ait aucun tronc.
    paires = {cle: (cle.split(" ") if cle != LABEL_DEFAUT else []) for cle in cles}
    commun = [p for p in paires[cles[0]] if all(p in paires[c] for c in cles[1:])]
    if len(cles) < 2 or not commun:
        return [], {cle: cle for cle in cles}
    restes = {}
    for cle in cles:
        reste = [p for p in paires[cle] if p not in commun]
        restes[cle] = " ".join(reste) or LABEL_RIEN_DE_PLUS
    return commun, restes


def summarise(entries: list) -> dict:
    """Regroupe par configuration : victoires, défaites, durée moyenne."""
    groups = defaultdict(lambda: {"joues": 0, "gagnes": 0, "inacheves": 0,
                                  "duree": 0.0, "tours": 0})
    # Une TENTATIVE n'a pas de `config` : la laisser entrer créerait une
    # ligne de configuration vide dans le tableau.
    for entry in (e for e in entries if est_combat(e)):
        stats = groups[config_key(entry.get("config") or {})]
        stats["joues"] += 1
        stats["duree"] += entry.get("duree") or 0
        stats["tours"] += entry.get("tours") or 0
        if not entry.get("termine"):
            stats["inacheves"] += 1
        elif entry.get("gagne"):
            stats["gagnes"] += 1
    return groups


def cmd_summary(last: Optional[int] = None, depuis: Optional[str] = None,
                path: Path = JOURNAL_PATH) -> None:
    """
    Taux de victoire par configuration, sur la fenêtre `depuis`.

    `depuis=None` veut dire ICI « aucune borne » : c'est `main()` qui
    traduit les options en borne (`borne_depuis`), et lui seul qui
    connaît la fenêtre par défaut. Une vue ne doit pas avoir d'avis sur
    la date du jour — sinon aucun test ne peut la fixer.
    """
    entries = read_all(path)
    if not entries:
        print(f"Journal vide ({Path(path).name}).")
        print("Il se remplit tout seul à chaque `python combat.py`.")
        return

    # Une TENTATIVE n'est pas un combat : ni tours, ni cartes, ni `config`.
    # L'en-tête comptait les LIGNES sous le mot « combats » ; il compte
    # désormais les combats. ON TRIE AVANT DE FENÊTRER, pour que le compte
    # des exclues porte sur des combats lui aussi.
    combats, exclues, sans_date = fenetre([e for e in entries if est_combat(e)],
                                          depuis)

    if last:
        recents = combats[-last:]
        print(f"=== {len(recents)} derniers combats ===\n")
        header = f"{'quand':<20} {'issue':<10} {'tours':>5} {'cartes':>7} {'durée':>7}  arrêt"
        print(header)
        print("-" * len(header))
        for entry in recents:
            issue = ("—" if not entry.get("termine")
                     else "VICTOIRE" if entry.get("gagne") else "défaite")
            if entry.get("termine") and entry.get("verdict"):
                issue += "*"       # verdict déduit de l'écran, pas de l'API (cf. légende)
            print(
                f"{entry.get('horodatage', '(sans date)'):<20} {issue:<10} "
                f"{entry.get('tours', 0):>5} {entry.get('cartes', 0):>7} "
                f"{entry.get('duree', 0):>6.0f}s  {entry.get('arret', '')[:34]}"
            )
        if any(e.get("termine") and e.get("verdict") for e in recents):
            print("  * verdict : " + ", ".join(sorted({
                e["verdict"] for e in recents if e.get("termine") and e.get("verdict")
            })))
        print()

    print(f"=== {libelle_fenetre(depuis, len(combats))} ===\n")
    rappel_fenetre(depuis, exclues, sans_date, "combat")

    if not combats:
        print("Aucun combat dans cette fenêtre.")
        return

    groupes = summarise(combats)
    tronc, restes = tronc_commun(groupes)
    if tronc:
        print(f"Commun aux {len(groupes)} configurations : " + " ".join(tronc))
        print()

    # LA COLONNE SE DIMENSIONNE SUR CE QU'ELLE DOIT MONTRER. Une colonne
    # large se lit encore ; deux lignes identiques, non. Plus aucune
    # troncature ici : c'était le bogue du 09/11/2026 (cf. `tronc_commun`).
    largeur = max([len("configuration")] + [len(v) for v in restes.values()])
    header = (f"{'configuration':<{largeur}} {'joués':>6} {'gagnés':>7} "
              f"{'taux':>7} {'durée':>7} {'tours':>6}")
    print(header)
    print("-" * len(header))

    for key, stats in sorted(groupes.items(), key=lambda x: -x[1]["joues"]):
        decided = stats["joues"] - stats["inacheves"]
        rate = f"{100 * stats['gagnes'] / decided:.0f} %" if decided else "—"
        print(
            f"{restes[key]:<{largeur}} {stats['joues']:>6} {stats['gagnes']:>7} {rate:>7} "
            f"{stats['duree'] / stats['joues']:>6.0f}s "
            f"{stats['tours'] / stats['joues']:>6.1f}"
        )

    unfinished = sum(s["inacheves"] for s in groupes.values())
    if unfinished:
        print(f"\n{unfinished} combat(s) non terminé(s), exclus du taux de victoire.")
    print(
        "\nPour comparer deux réglages, joue une dizaine de combats avec chacun :\n"
        "  python combat.py --spells\n"
        "  python combat.py\n"
        "puis relance `python journal.py`. En dessous d'une dizaine de parties\n"
        "par configuration, l'écart observé sera surtout du hasard."
    )


def summarise_rejections(entries: list) -> dict:
    """
    Regroupe les cartes écartées par MOTIF, tous combats confondus :
    {motif: {"n": occurrences, "combats": nb de combats, "cartes": {nom: n}}}.
    """
    groups = defaultdict(lambda: {"n": 0, "combats": 0, "cartes": defaultdict(int)})
    for entry in (e for e in entries if est_combat(e)):
        seen = set()
        for item in entry.get("ecartees") or []:
            motif = normalize_reason(item.get("motif", ""))
            n = int(item.get("n") or 1)
            stats = groups[motif]
            stats["n"] += n
            stats["cartes"][item.get("carte") or item.get("code") or "?"] += n
            if motif not in seen:
                seen.add(motif)
                stats["combats"] += 1
    return groups


def cmd_rejections(last: Optional[int] = None, depuis: Optional[str] = None,
                   path: Path = JOURNAL_PATH) -> None:
    """
    LE BACKLOG DU BOT. Ce qu'il a écarté en jeu, classé par motif et par
    fréquence : la prochaine forme de geste à lui apprendre est en haut.
    Les motifs de contexte (mana, place, cible absente) sont à part — ils
    ne disent rien de ce que le bot ne sait pas faire.

    ET C'EST DATÉ. Sans fenêtre, le classement cumule des bogues déjà
    corrigés et désigne une brique déjà posée : cf. « LA FENÊTRE ».
    """
    entries = read_all(path)
    # Les cartes écartées ne vivent que sur des lignes de COMBAT, et
    # seulement sur celles qui portent le champ `ecartees` (il existe
    # depuis le 05/09/2026). Tout le reste, cette vue ne le compte pas :
    # il ne doit donc ni voler une place dans `last`, ni gonfler le compte
    # des exclues — au 09/11/2026 il le gonflait de 68 à la place de 15.
    comptables = [e for e in entries if est_combat(e) and "ecartees" in e]
    with_data, exclues, sans_date = fenetre(comptables, depuis)
    if last:
        with_data = with_data[-last:]
    if not with_data:
        print("Aucun combat avec cartes écartées dans cette fenêtre "
              "(le champ existe depuis le 05/09/2026 : rejoue un combat).")
        print()
        rappel_fenetre(depuis, exclues, sans_date, "combat")
        return

    groups = summarise_rejections(with_data)
    capacity = {m: s for m, s in groups.items() if not is_context_reason(m)}
    context = {m: s for m, s in groups.items() if is_context_reason(m)}

    def table(title, data):
        if not data:
            print(f"=== {title} : rien ===\n")
            return
        print(f"=== {title} — sur {libelle_fenetre(depuis, len(with_data))} ===\n")
        header = f"{'motif':<58} {'fois':>5} {'combats':>8}  cartes"
        print(header)
        print("-" * len(header))
        for motif, stats in sorted(data.items(), key=lambda x: -x[1]["n"]):
            cards = sorted(stats["cartes"].items(), key=lambda x: -x[1])
            shown = ", ".join(f"{c} ×{n}" for c, n in cards[:4])
            if len(cards) > 4:
                shown += f" (+{len(cards) - 4})"
            print(f"{motif[:58]:<58} {stats['n']:>5} {stats['combats']:>8}  {shown}")
        print()

    table("Ce que le bot ne sait pas (encore) jouer", capacity)
    table("Contexte de la partie (mana, place, cible) — pas une incapacité", context)
    rappel_fenetre(depuis, exclues, sans_date, "combat")
    if capacity:
        top = max(capacity.items(), key=lambda x: x[1]["n"])[0]
        print(f"Prochaine brique suggérée : « {top} ».")


def summarise_champions(entries: list) -> dict:
    """
    Taux de victoire par (palier, étoiles), sur les lignes de TENTATIVE.

    C'est ce tableau qui doit régler la table d'allocation de
    `champions.etoiles_requises` — 70 paliers, trois tentatives par
    champion et par mois : viser trop haut gâche les champions forts,
    viser trop bas gâche la tentative ET le palier. Les parties
    tranchent, pas l'intuition.
    """
    groupes = defaultdict(lambda: {"jouees": 0, "gagnees": 0, "perdues": 0,
                                   "inachevees": 0})
    for e in tentatives(entries):
        cle = (e.get("palier"), e.get("etoiles"))
        g = groupes[cle]
        g["jouees"] += 1
        if e.get("gagne") is True:
            g["gagnees"] += 1
        elif e.get("gagne") is False:
            g["perdues"] += 1
        else:
            g["inachevees"] += 1
    return groupes


def cmd_champions(last: Optional[int] = None, depuis: Optional[str] = None,
                  path: Path = JOURNAL_PATH) -> None:
    entries = read_all(path)
    # CETTE VUE NE LIT QUE DES TENTATIVES. On les isole AVANT de fenêtrer :
    # sinon elle annonce les combats laissés dehors par la fenêtre — 68 au
    # 09/11/2026, pour 0 tentative exclue — et renvoie vers un
    # `--depuis tout` qui affiche exactement le même tableau.
    lignes, exclues, sans_date = fenetre(tentatives(entries), depuis)
    if last:
        lignes = lignes[-last:]
    groupes = summarise_champions(lignes)
    total = sum(g["jouees"] for g in groupes.values())
    print(f"=== {libelle_fenetre(depuis, total, 'tentative')} ===")
    print()
    rappel_fenetre(depuis, exclues, sans_date, "tentative")
    if not groupes:
        print("Aucune tentative dans cette fenêtre : le champ est rempli par")
        print("`challenges.py` depuis le 05/11/2026 — joue une aventure.")
        return
    print(f"{'palier':>7}  {'étoiles':>7}  {'jouées':>6}  {'gagnées':>7}  {'taux':>6}")
    print("-" * 44)
    for (palier, etoiles) in sorted(groupes, key=lambda c: (c[0] is None, c[0],
                                                            c[1] is None, c[1])):
        g = groupes[(palier, etoiles)]
        jugees = g["gagnees"] + g["perdues"]
        taux = f"{100 * g['gagnees'] / jugees:.0f} %" if jugees else "—"
        print(f"{str(palier):>7}  {str(etoiles):>7}  {g['jouees']:>6}  "
              f"{g['gagnees']:>7}  {taux:>6}")
    print()
    print("Moins d'une dizaine de tentatives par case : l'écart observé est")
    print("surtout du hasard. La table de départ est dans champions.py")
    print("(`etoiles_requises`) — c'est ce tableau qui doit la corriger.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Journal des combats (LoR).")
    parser.add_argument("--last", type=int, default=None, help="détailler les N derniers")
    parser.add_argument("--reset", action="store_true", help="vider le journal")
    parser.add_argument("--champions", action="store_true",
                        help="taux de victoire par (palier, étoiles) : la table d'allocation")
    parser.add_argument("--ecartees", action="store_true",
                        help="les cartes écartées en jeu, classées par motif : le backlog du bot")
    # LA FENÊTRE. Elle vaut pour les TROIS vues : un classement daté d'un
    # côté et un tableau cumulé de l'autre se contrediraient sans prévenir.
    parser.add_argument("--depuis", default=None, metavar="AAAA-MM-JJ",
                        help="ne lire que les lignes à partir de cette date ; "
                             "« tout » pour l'historique entier")
    parser.add_argument("--jours", type=int, default=None, metavar="N",
                        help=f"fenêtre glissante de N jours "
                             f"(défaut : {FENETRE_DEFAUT_JOURS})")
    args = parser.parse_args()

    try:
        depuis = borne_depuis(args.depuis, args.jours)
    except ValueError as exc:
        parser.error(str(exc))
        return

    if args.champions:
        cmd_champions(args.last, depuis)
        return
    if args.ecartees:
        cmd_rejections(args.last, depuis)
        return

    if args.reset:
        if JOURNAL_PATH.exists():
            backup = JOURNAL_PATH.with_suffix(".jsonl.bak")
            JOURNAL_PATH.replace(backup)
            print(f"Journal déplacé vers {backup.name} — rien n'est perdu.")
        else:
            print("Journal déjà vide.")
        return

    cmd_summary(args.last, depuis)


if __name__ == "__main__":
    main()
