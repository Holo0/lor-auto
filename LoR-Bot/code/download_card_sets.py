#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_card_sets.py — met à jour la base de cartes `LoR-Bot/card_sets/`.

    python LoR-Bot/code/download_card_sets.py            # met la base à jour
    python LoR-Bot/code/download_card_sets.py --force    # réécrit tout
    python LoR-Bot/code/download_card_sets.py --sans-wiki  # Riot seulement

Pourquoi ce fichier a été réécrit le 06/09/2026 : l'ancien n'avait AUCUN
bloc `if __name__ == "__main__"` — le lancer n'exécutait rien et ne créait
donc aucun fichier — et il écrivait dans un dossier `card_sets` RELATIF au
répertoire courant, donc à côté de `challenges.py` quand on le lançait
depuis la racine, là où `lor_api` ne regarde jamais. Les deux défauts sont
verrouillés par `test_lor_api.py` : ne pas les réintroduire.

--------------------------------------------------------------------
DEUX SOURCES, ET IL FAUT LES DEUX
--------------------------------------------------------------------
1. LE DATA DRAGON DE RIOT, source de référence :
       https://dd.b.pvp.net/latest/<set>/en_us/data/<set>-en_us.json

   NOMS DES SETS. Riot ne numérote pas tout : `set6cde`, `set7b`, et
   `tpoc` (cartes exclusives à Path of Champions, codes « 98… »).

   RECENSÉ LE 10/11/2026, par sondage HEAD de tout le CDN : il existe
   EXACTEMENT quatorze paquets — `core`, `set1`…`set9`, `set6cde`,
   `set7b`, `tpoc`, `adventure` — et c'est tout. `set10`, `set99`,
   `setevent`, `poc`, `tpoc2` répondent 403. `adventure` ne contient
   PAS de cartes : seulement `powers`, `items` et `relics`. Total
   mesuré : 2670 cartes, préfixes 01 à 09 et 98. **Inutile d'inventer
   un gabarit de nom de plus : il n'y en a pas d'autre.**

2. LE WIKI, pour ce que Riot NE PUBLIE PAS. Les cartes au préfixe
   « 99… » (et « 00… ») sont exclusives au mode Path of Champions,
   marquées « cannot be collected », et ABSENTES du Data Dragon. Le bot
   les rencontre pourtant à chaque aventure : 99PZ130 (Pow-Pow),
   99PZ104 (Rocketboarder), 99SH003, 99MT003, 99IO003 sont dans les
   logs du 09/11/2026. Sans elles, `game_state` lit « 0/0 (inconnue) »,
   `classify_card` rend `Targeting.NONE`, et une pose part à l'aveugle :
   23 s perdues sur 99PZ130 le 09/11 à 19:31, 8 s de plus au combat
   suivant.

   `Module:LoRData/data` du wiki anglais donne nom, coût, attaque, PV,
   type, mots-clés et texte, en ANGLAIS — la langue que `spells.py`
   classe (ne JAMAIS passer en fr_fr).

   CE QUE VAUT CETTE SECONDE SOURCE, MESURÉ le 10/11/2026 en comparant
   ses 2648 cartes communes avec le Data Dragon :

       coût identique                 2636 / 2648   (99,5 %)
       attaque d'unité identique      1326 / 1331   (99,6 %)
       PV d'unité identiques          1320 / 1331   (99,2 %)
       type identique                 2633 / 2648   (99,4 %)
       mots-clés MODÉLISÉS identiques 2644 / 2648   (99,85 %)
       même plan de sort              903  / 969    (93,2 %)

   Et surtout, sur les 66 plans de sorts qui diffèrent : **ZÉRO ne
   change le camp du clic**, 20 rendent le bot PLUS prudent (le wiki
   écrit « Pick an ally… » là où Riot écrit « An ally… », ce que
   `REFUSALS` écarte), 6 ouvrent un clic que Riot refuse, 40 ne
   changent que le nom de l'effet. Le texte du wiki est une
   PARAPHRASE, pas le texte du jeu : c'est pourquoi il ne sert que là
   où Riot n'a rien. Le fichier produit, `cartes_hors_ddragon.json`,
   se trie AVANT `set*.json` : si Riot publiait ces cartes un jour,
   ses valeurs écraseraient les nôtres toutes seules.

   Chaque carte produite porte un champ `source` : aucune ligne de
   cette base ne doit pouvoir passer pour une donnée de Riot.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests

# Chemin ABSOLU : le script doit marcher quel que soit le répertoire courant.
CARD_SET_FOLDER = Path(__file__).resolve().parent.parent / "card_sets"

SET_NAME_TEMPLATES = ["set{}", "set{}b", "set{}cde"]
EXTRA_SET_NAMES = ["tpoc"]
URL = "https://dd.b.pvp.net/latest/{name}/en_us/data/{name}-en_us.json"
# Au-delà de ce nombre de numéros consécutifs sans aucun fichier, on arrête.
MAX_EMPTY_NUMBERS = 2

# --- la seconde source ----------------------------------------------
WIKI_API = "https://wiki.leagueoflegends.com/en-us/api.php"
WIKI_MODULE = "Module:LoRData/data"
WIKI_FILE = "cartes_hors_ddragon.json"
WIKI_SOURCE = "wiki.leagueoflegends.com/" + WIKI_MODULE
# Un vrai code de carte : deux chiffres, deux lettres, trois chiffres,
# puis éventuellement un suffixe de jeton (T1, T11…). Le module du wiki
# contient aussi quelques clés parasites ("keywordRefs" mal indenté) que
# ce filtre écarte sans avoir à les nommer.
CODE_RX = re.compile(r"^[0-9]{2}[A-Z]{2}[0-9]{3}[A-Za-z0-9]*$")
HTTP_HEADERS = {"User-Agent": "LoR-bot/1.0 (base de cartes hors DDragon)"}


# ============================================================
# SOURCE 1 — LE DATA DRAGON DE RIOT
# ============================================================

def download_card_set(name: str):
    """Le contenu JSON du set, ou None s'il n'existe pas sur le CDN."""
    try:
        res = requests.get(URL.format(name=name), timeout=60)
    except requests.RequestException as exc:
        print(f"  {name}: erreur réseau ({exc})")
        return None
    if not res.ok:
        return None
    try:
        return res.json()
    except ValueError:
        print(f"  {name}: réponse illisible")
        return None


def fetch(name: str, force: bool) -> str:
    """
    Met `name` à jour. Rend 'present', 'downloaded' ou 'absent'.

    ON INTERROGE LE CDN MÊME QUAND LE FICHIER EST DÉJÀ LÀ. L'ancienne
    version court-circuitait sur `path.exists()`, et Riot ENRICHIT ses
    paquets en place : mesuré le 10/11/2026, `tpoc.json` avait 141
    cartes sur le disque contre 158 au CDN — dix-sept cartes de Path of
    Champions manquaient depuis des semaines, sans un mot. Un fichier
    présent mais périmé est exactement le défaut que ce script existe
    pour éviter.
    """
    path = CARD_SET_FOLDER / f"{name}.json"
    data = download_card_set(name)
    if data is None:
        return "absent"
    texte = json.dumps(data, indent=2)
    if path.exists() and not force:
        try:
            ancien = path.read_text(encoding="utf-8")
        except OSError:
            ancien = None
        if ancien == texte:
            return "present"
        avant = _nb_cartes(ancien)
        # UNE MISE À JOUR NE DOIT PAS APPAUVRIR LA BASE. Un CDN qui
        # répond une liste tronquée rendrait des cartes inconnues en
        # silence — exactement le défaut qu'on répare. On garde
        # l'ancien fichier et on le DIT ; `--force` passe outre.
        if len(data) < avant:
            print(f"  {name}: le CDN rend {len(data)} cartes contre {avant} "
                  f"sur le disque — fichier GARDÉ (--force pour passer outre)")
            return "present"
        print(f"  {name}: {avant} -> {len(data)} cartes (mis à jour)")
    else:
        print(f"  {name}: {len(data)} cartes -> {path.name}")
    path.write_text(texte, encoding="utf-8")
    return "downloaded"


def _nb_cartes_du_fichier(chemin: Path) -> int:
    try:
        return _nb_cartes(chemin.read_text(encoding="utf-8"))
    except OSError:
        return 0


def _nb_cartes(texte) -> int:
    try:
        return len(json.loads(texte))
    except (TypeError, ValueError):
        return 0


def update(force: bool = False) -> dict:
    CARD_SET_FOLDER.mkdir(parents=True, exist_ok=True)
    print(f"Base de cartes : {CARD_SET_FOLDER}")
    outcome = {"present": [], "downloaded": [], "absent": []}

    number, empty_numbers = 1, 0
    while empty_numbers < MAX_EMPTY_NUMBERS:
        found_any = False
        for template in SET_NAME_TEMPLATES:
            name = template.format(number)
            status = fetch(name, force)
            outcome[status].append(name)
            found_any = found_any or status != "absent"
        empty_numbers = 0 if found_any else empty_numbers + 1
        number += 1

    for name in EXTRA_SET_NAMES:
        outcome[fetch(name, force)].append(name)
    return outcome


# ============================================================
# SOURCE 2 — LE WIKI, POUR CE QUE RIOT NE PUBLIE PAS
# ============================================================
#
# Le module est une table Lua. On ne l'exécute pas : on la lit.

_GUILLEMET = '"((?:[^"' + "\\\\" + ']|' + "\\\\" + '.)*)"'
_ENTREE_RX = re.compile(r'\["([0-9A-Za-z]+)"\]\s*=\s*\{')
_CHAINE_RX = re.compile(r'\["(\w+)"\]\s*=\s*' + _GUILLEMET)
_NOMBRE_RX = re.compile(r'\["(\w+)"\]\s*=\s*(-?\d+)')
_BOOLEEN_RX = re.compile(r'\["(\w+)"\]\s*=\s*(true|false)')
_LISTE_RX = re.compile(r'\["(\w+)"\]\s*=\s*\{([^{}]*)\}')
_DANS_LISTE_RX = re.compile(_GUILLEMET)

# Nettoyage du wikicode : {{TipLoR|Fleeting}}, {{LoR|Heimerdinger}},
# <br/>, [[lien|texte]], ''italique''.
_MODELE_RX = re.compile(r"\{\{(\w+)\|([^{}]*)\}\}")
_LIEN_RX = re.compile(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]")
_SAUT_RX = re.compile(r"</?br\s*/?>", re.I)
_BALISE_RX = re.compile(r"</?(?:nowiki|ul|li|small|pre|b|i)\s*/?>", re.I)

VITESSES = ("Burst", "Fast", "Slow")


def _deséchappe(texte: str) -> str:
    try:
        return json.loads('"' + texte + '"')
    except ValueError:
        return texte


def _developpe_modele(m) -> str:
    """{{TipLoR|Fleeting}} -> Fleeting ; {{tt|texte|infobulle}} -> texte."""
    nom = m.group(1).lower()
    args = m.group(2).split("|")
    if nom in ("tiplor", "lor"):
        return args[-1] if len(args) > 1 else args[0]
    return args[0]


def nettoyer_wikicode(texte: str) -> str:
    """Le texte anglais de la carte, débarrassé du balisage du wiki."""
    if not texte:
        return ""
    sortie = texte
    for _ in range(4):  # modèles imbriqués
        suivant = _MODELE_RX.sub(_developpe_modele, sortie)
        if suivant == sortie:
            break
        sortie = suivant
    sortie = _LIEN_RX.sub(r"\1", sortie)
    sortie = _SAUT_RX.sub("\n", sortie)
    sortie = _BALISE_RX.sub("", sortie)
    sortie = sortie.replace("'''", "").replace("''", "")
    sortie = re.sub(r"[ \t]+", " ", sortie)
    return sortie.strip()


def _entrees_lua(texte: str):
    """Les tables de PREMIER niveau de la table Lua, (clé, corps)."""
    for m in _ENTREE_RX.finditer(texte):
        debut = texte.rfind("\n", 0, m.start()) + 1
        if texte[debut:m.start()].strip():
            continue  # une clé imbriquée, pas une carte
        profondeur, i = 1, m.end()
        while profondeur and i < len(texte):
            car = texte[i]
            if car == '"':
                i += 1
                while i < len(texte) and texte[i] != '"':
                    i += 2 if texte[i] == "\\" else 1
            elif car == "{":
                profondeur += 1
            elif car == "}":
                profondeur -= 1
            i += 1
        yield m.group(1), texte[m.end():i - 1]


def _champs_lua(corps: str) -> dict:
    champs = {}
    for m in _LISTE_RX.finditer(corps):
        champs[m.group(1)] = [_deséchappe(x)
                              for x in _DANS_LISTE_RX.findall(m.group(2))]
    for m in _CHAINE_RX.finditer(corps):
        champs.setdefault(m.group(1), _deséchappe(m.group(2)))
    for m in _NOMBRE_RX.finditer(corps):
        champs[m.group(1)] = int(m.group(2))
    for m in _BOOLEEN_RX.finditer(corps):
        champs[m.group(1)] = m.group(2) == "true"
    return champs


def lire_module_wiki(texte: str) -> dict:
    """{code: champs bruts} pour toutes les cartes de la table Lua."""
    cartes = {}
    for code, corps in _entrees_lua(texte):
        if CODE_RX.match(code):
            cartes[code] = _champs_lua(corps)
    return cartes


def telecharger_module_wiki() -> str:
    """Le wikicode du module, ou '' si le wiki ne répond pas."""
    params = {
        "action": "query", "titles": WIKI_MODULE, "prop": "revisions",
        "rvprop": "content", "rvslots": "main",
        "format": "json", "formatversion": "2",
    }
    try:
        res = requests.get(WIKI_API, params=params, timeout=180,
                           headers=HTTP_HEADERS)
        res.raise_for_status()
        page = res.json()["query"]["pages"][0]
        return page["revisions"][0]["slots"]["main"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        print(f"  wiki injoignable ({exc})")
        return ""


def correspondances(base_riot: dict) -> tuple:
    """
    (mots-clés, régions) : libellé affiché -> référence interne.

    DÉDUITES DE LA BASE DE RIOT, jamais inventées : dans chaque carte,
    `keywords` et `keywordRefs` sont parallèles (vérifié : 0 carte sur
    2653 où les deux listes n'ont pas la même longueur). D'où
    « Quick Attack » -> « QuickStrike », « Piltover & Zaun » ->
    « PiltoverZaun ».
    """
    mots, regions = {}, {}
    for carte in base_riot.values():
        for table, libelles, refs in (
            (mots, carte.get("keywords"), carte.get("keywordRefs")),
            (regions, carte.get("regions"), carte.get("regionRefs")),
        ):
            libelles, refs = libelles or [], refs or []
            if len(libelles) != len(refs):
                continue
            for libelle, ref in zip(libelles, refs):
                # Un libellé peut porter deux refs (Overwhelm /
                # SpellOverwhelm) : la référence IDENTIQUE au libellé
                # l'emporte, sinon la première vue.
                if table.get(libelle) == libelle:
                    continue
                if libelle not in table or ref == libelle:
                    table[libelle] = ref
    return mots, regions


def _reference(libelle: str, table: dict) -> str:
    return table.get(libelle) or re.sub(r"[^A-Za-z0-9]", "", libelle)


def en_forme_ddragon(code: str, brut: dict, mots: dict, regions: dict) -> dict:
    """Une carte du wiki, dans la forme que `lor_api.load_card_db` lit."""
    type_carte = brut.get("type") or ""
    est_unite = type_carte.strip().lower() == "unit"
    libelles = list(brut.get("keywords") or [])
    texte = nettoyer_wikicode(brut.get("desc") or "")
    montee = nettoyer_wikicode(brut.get("lvldesc") or "")
    vitesse = next((v for v in VITESSES if v in libelles), "")
    sous_types = brut.get("subtype") or []
    if isinstance(sous_types, str):
        sous_types = [sous_types]
    noms_regions = list(brut.get("regions") or [])
    return {
        "cardCode": code,
        "name": brut.get("name") or code,
        "cost": int(brut.get("cost") or 0),
        # Les stats n'ont de sens que sur une unité : le wiki range
        # parfois des chiffres de sort (la valeur d'une frappe) dans
        # `power` / `health`, là où le Data Dragon met 0.
        "attack": int(brut.get("power") or 0) if est_unite else 0,
        "health": int(brut.get("health") or 0) if est_unite else 0,
        "type": type_carte,
        "supertype": brut.get("supertype") or "",
        "subtypes": sous_types,
        "keywords": libelles,
        "keywordRefs": [_reference(k, mots) for k in libelles],
        "description": texte,
        "descriptionRaw": texte,
        "levelupDescription": montee,
        "levelupDescriptionRaw": montee,
        "spellSpeed": vitesse,
        "spellSpeedRef": vitesse,
        "rarity": (brut.get("rarity") or "None").upper(),
        "rarityRef": brut.get("rarity") or "None",
        "collectible": bool(brut.get("collectible", False)),
        "regions": noms_regions,
        "regionRefs": [_reference(r, regions) for r in noms_regions],
        "associatedCardRefs": [],
        "set": "HorsDDragon",
        "flavorText": nettoyer_wikicode(brut.get("flavor") or ""),
        "artistName": brut.get("artist") or "",
        # PROVENANCE : aucune ligne de cette base ne doit pouvoir passer
        # pour une donnée de Riot.
        "source": WIKI_SOURCE,
    }


def charger_base_riot() -> dict:
    """{code: carte} pour tous les `set*.json` / `tpoc.json` déjà écrits."""
    base = {}
    for chemin in sorted(CARD_SET_FOLDER.glob("*.json")):
        if chemin.name == WIKI_FILE:
            continue
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, list):
            for carte in data:
                code = carte.get("cardCode")
                if code:
                    base[code] = carte
    return base


def completer_hors_ddragon(force: bool = False) -> dict:
    """
    Écrit `cartes_hors_ddragon.json` : ce que le wiki a et Riot pas.

    Rend un bilan {'ecrites', 'ignorees_riot', 'retirees', 'statut'}.
    """
    base = charger_base_riot()
    if not base:
        print("  base Riot vide : on ne complète rien "
              "(lancer d'abord sans --sans-wiki une fois le réseau ouvert)")
        return {"ecrites": 0, "ignorees_riot": 0, "retirees": 0,
                "statut": "base Riot absente"}

    texte = telecharger_module_wiki()
    if not texte:
        return {"ecrites": 0, "ignorees_riot": 0, "retirees": 0,
                "statut": "wiki injoignable"}

    mots, regions = correspondances(base)
    brutes = lire_module_wiki(texte)
    cartes, ignorees, retirees = [], 0, 0
    for code, brut in sorted(brutes.items()):
        if code in base:
            ignorees += 1
            continue
        if brut.get("removed"):
            retirees += 1
            continue
        cartes.append(en_forme_ddragon(code, brut, mots, regions))

    chemin = CARD_SET_FOLDER / WIKI_FILE
    sortie = json.dumps(cartes, indent=2, ensure_ascii=False)
    if chemin.exists() and not force and \
            chemin.read_text(encoding="utf-8") == sortie:
        statut = "inchangé"
    else:
        chemin.write_text(sortie, encoding="utf-8")
        statut = "écrit"
    print(f"  {WIKI_FILE}: {len(cartes)} cartes absentes du Data Dragon "
          f"({statut}) — {ignorees} déjà chez Riot, {retirees} retirées du jeu")
    return {"ecrites": len(cartes), "ignorees_riot": ignorees,
            "retirees": retirees, "statut": statut}


# ============================================================
# COMMANDE
# ============================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="réécrit les fichiers même s'ils sont à jour")
    parser.add_argument("--sans-wiki", action="store_true",
                        help="Data Dragon de Riot seulement (laisse les "
                             "cartes « 99… » du mode aventure inconnues)")
    args = parser.parse_args(argv)

    outcome = update(force=args.force)
    print()
    if args.sans_wiki:
        print("Cartes hors Data Dragon : NON RÉCUPÉRÉES (--sans-wiki) — "
              "sans elles, les cartes « 99… » des aventures restent inconnues.")
        bilan = {"statut": "sauté (--sans-wiki)"}
    else:
        print("Cartes que Riot ne publie pas :")
        bilan = completer_hors_ddragon(force=args.force)

    print()
    print(f"À jour        : {', '.join(outcome['present']) or '-'}")
    print(f"Écrits        : {', '.join(outcome['downloaded']) or '-'}")
    total = sum(1 for _ in CARD_SET_FOLDER.glob("*.json"))
    cards = 0
    for path in CARD_SET_FOLDER.glob("*.json"):
        try:
            cards += len(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    hors = _nb_cartes_du_fichier(CARD_SET_FOLDER / WIKI_FILE)
    print(f"{total} fichier(s), {cards} cartes au total "
          f"(dont {hors} hors Data Dragon).")
    if not hors:
        print("AUCUNE carte hors Data Dragon : les « 99… » du mode "
              "aventure resteront lues « 0/0 (inconnue) ».")
    if not outcome["downloaded"] and bilan["statut"] in ("inchangé",
                                                         "sauté (--sans-wiki)"):
        print("Rien de nouveau.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
