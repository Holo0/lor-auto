"""
Tests de lor_api.py — l'accès à l'API locale du client.

    python test_lor_api.py

LE PORT DE L'API N'EST PAS FIXE. Le 04/11/2026, le client écoutait sur
21338 et non 21337. Rien ne le disait : `check.py` annonçait « API
injoignable », le bot a traversé la carte d'aventure, lancé le boss
final, puis attendu 120 s devant un écran de mulligan qu'il ne voyait
pas. Une tentative de défi hebdomadaire brûlée.

Changer la constante n'aurait rien réglé : le client prend le premier
port libre, donc le suivant au lancement suivant. D'où la sonde.

Hors ligne : aucune connexion réelle, `_SESSION` et `socket` sont
remplacés.
"""

from __future__ import annotations

import sys
from pathlib import Path

import lor_api

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ============================================================
# OUTILLAGE : UN FAUX CLIENT SUR UN PORT DONNÉ
# ============================================================

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        pass


class FakeSession:
    """Répond sur UN port et nulle part ailleurs."""

    def __init__(self, port, payload=None, muets=()):
        self.port = port
        self.payload = payload if payload is not None else {
            "GameState": "InProgress", "Rectangles": [], "Screen": {},
        }
        self.muets = set(muets)      # ports ouverts qui répondent autre chose
        self.appels = []

    def get(self, url, timeout=None):
        port = int(url.split(":")[2].split("/")[0])
        self.appels.append(port)
        if port in self.muets:
            return FakeResponse({"ceci": "n'est pas l'API"})
        if port != self.port:
            raise lor_api.requests.ConnectionError("connexion refusée")
        return FakeResponse(self.payload)


class Contexte:
    """Pose une fausse session, un faux socket, et restaure tout."""

    def __init__(self, session, port_ouvert=None):
        self.session = session
        self.port_ouvert = port_ouvert

    def __enter__(self):
        self._sauve = (lor_api._SESSION, lor_api.API_BASE, lor_api.socket)
        lor_api._SESSION = self.session

        ouvert = self.port_ouvert

        class FauxSocket:
            def __init__(self, *a, **k):
                pass

            def settimeout(self, _):
                pass

            def connect(self, addr):
                if ouvert is None or addr[1] != ouvert:
                    raise ConnectionRefusedError("refusé")

            def close(self):
                pass

        lor_api.socket = type("mod", (), {"socket": FauxSocket})
        lor_api.set_api_port(lor_api.API_PORT_DEFAULT)
        return self

    def __exit__(self, *exc):
        lor_api._SESSION, lor_api.API_BASE, lor_api.socket = self._sauve
        return False


# ============================================================
# LES TESTS
# ============================================================

def test_le_port_par_defaut_ne_coute_rien():
    print("\n-- le port habituel reste le premier essayé --")
    session = FakeSession(lor_api.API_PORT_DEFAULT)
    with Contexte(session):
        data = lor_api.get_positional_rectangles()
    check("la lecture réussit", data.get("GameState") == "InProgress", data)
    check("un seul appel : aucune sonde", session.appels == [lor_api.API_PORT_DEFAULT],
          session.appels)
    check("la base n'a pas bougé",
          lor_api.API_BASE.endswith(str(lor_api.API_PORT_DEFAULT)), lor_api.API_BASE)


def test_le_port_voisin_est_trouve():
    print("\n-- le cas du 04/11/2026 : le client est sur 21338 --")
    session = FakeSession(21338)
    with Contexte(session):
        data = lor_api.get_positional_rectangles()
        base = lor_api.API_BASE
    check("la lecture réussit malgré le port changé",
          data.get("GameState") == "InProgress", data)
    check("la base a été adoptée", base.endswith(":21338"), base)
    check("21337 a bien été essayé d'abord",
          session.appels[0] == lor_api.API_PORT_DEFAULT, session.appels)


def test_un_port_ouvert_qui_repond_autre_chose_est_ecarte():
    print("\n-- un voisin bavard n'est pas l'API --")
    # 21339 répond du JSON, mais pas celui de l'API ; le vrai est 21340.
    session = FakeSession(21340, muets={21339})
    with Contexte(session):
        lor_api.get_positional_rectangles()
        base = lor_api.API_BASE
    check("le bavard est écarté", not base.endswith(":21339"), base)
    check("le vrai port est retenu", base.endswith(":21340"), base)


def test_aucun_port_ne_repond():
    print("\n-- personne ne répond --")
    session = FakeSession(None)      # aucun port ne répond
    with Contexte(session):
        try:
            lor_api.get_positional_rectangles()
            leve = False
        except lor_api.ApiUnavailable:
            leve = True
    check("ApiUnavailable est levée", leve)
    check("tous les candidats ont été essayés",
          set(lor_api.API_PORT_CANDIDATES) <= set(session.appels), session.appels)


def test_un_port_qui_repond_mal_ne_declenche_pas_de_recherche():
    print("\n-- répondre mal n'est pas se taire --")
    # LE PIÈGE : pendant un écran de chargement, l'API répond du HTML ou
    # un JSON vide. Le port est le BON. Partir en chasse à ce moment-là
    # ferait adopter un autre port — ou n'en trouver aucun — alors qu'il
    # suffisait d'attendre. Seul un refus de connexion déclenche la sonde.
    session = FakeSession(lor_api.API_PORT_DEFAULT,
                          payload=ValueError("pas du JSON"))
    with Contexte(session, port_ouvert=lor_api.API_PORT_DEFAULT):
        try:
            lor_api.get_positional_rectangles()
            leve = False
        except lor_api.ApiUnavailable:
            leve = True
    check("ApiUnavailable est levée", leve)
    check("aucune sonde des voisins",
          set(session.appels) == {lor_api.API_PORT_DEFAULT}, session.appels)
    check("la base n'a pas bougé",
          lor_api.API_BASE.endswith(str(lor_api.API_PORT_DEFAULT)), lor_api.API_BASE)


def test_set_et_lecture_du_port():
    print("\n-- fixer le port à la main --")
    sauve = lor_api.API_BASE
    try:
        base = lor_api.set_api_port(21345)
        check("la base est reconstruite", base == "http://127.0.0.1:21345", base)
        check("le port courant est relu", lor_api._port_courant() == 21345,
              lor_api._port_courant())
    finally:
        lor_api.API_BASE = sauve


def test_les_candidats_couvrent_le_cas_vu():
    print("\n-- la plage sondée --")
    check("21337 en premier",
          lor_api.API_PORT_CANDIDATES[0] == lor_api.API_PORT_DEFAULT,
          lor_api.API_PORT_CANDIDATES[:3])
    check("21338 (le cas du 04/11/2026) est dedans",
          21338 in lor_api.API_PORT_CANDIDATES)
    # Sonder large coûte une connexion refusée par port, mais seulement
    # quand plus rien ne répond : garder la plage courte.
    check("la plage reste courte", len(lor_api.API_PORT_CANDIDATES) <= 16,
          len(lor_api.API_PORT_CANDIDATES))


# ============================================================
# LA BASE DE CARTES — ET CE QUE RIOT NE PUBLIE PAS
# ============================================================
#
# Le 09/11/2026, le bot a posé 99PZ130 sans rien en savoir : 23 s
# perdues, puis 8 s de plus au combat suivant. La base comptait 2653
# cartes et paraissait complète — aucune ne portait le préfixe « 99 ».
# Recensé le 10/11/2026 par sondage du CDN : Riot publie quatorze
# paquets, et AUCUN ne contient ces cartes. La seconde source du
# script de téléchargement existe pour ça, et ces tests la tiennent.

_ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(_ICI / "LoR-Bot" / "code"))
import download_card_sets as dcs  # noqa: E402


MODULE_LUA_FACTICE = '''-- <pre>
return {
    ["99PZ130"] = {
        ["name"]         = "Pow-Pow",
        ["type"]         = "Spell",
        ["rarity"]       = "None",
        ["collectible"]  = false,
        ["keywords"]     = {"Burst"},
        ["keywordRefs"]  = {"Burst",},
        ["cost"]         = 2,
        ["power"]        = 7,
        ["desc"]         = "Deal 3 to a {{TipLoR|unit}}.<br/>See {{LoR|Jinx}}.",
        ["mode"]         = "The Path of Champions"
    },
    ["99PZ104"] = {
        ["name"]         = "Rocketboarder",
        ["type"]         = "Unit",
        ["collectible"]  = false,
        ["keywords"]     = {"Quick Attack"},
        ["regions"]      = {"Piltover & Zaun"},
        ["cost"]         = 2,
        ["power"]        = 3,
        ["health"]       = 3
    },
    ["99XX999"] = {
        ["name"]         = "Carte retirée",
        ["type"]         = "Spell",
        ["cost"]         = 1,
        ["removed"]      = true
    },
    ["keywordRefs"] = {"ceci n'est pas une carte"},
}
'''

# Deux cartes de Riot, juste assez pour que les correspondances
# libellé -> référence se DÉDUISENT au lieu d'être inventées.
BASE_RIOT_FACTICE = {
    "01PZ019": {"cardCode": "01PZ019", "keywords": ["Quick Attack"],
                "keywordRefs": ["QuickStrike"],
                "regions": ["Piltover & Zaun"],
                "regionRefs": ["PiltoverZaun"]},
    "01DE007": {"cardCode": "01DE007", "keywords": ["Fast"],
                "keywordRefs": ["Fast"], "regions": ["Demacia"],
                "regionRefs": ["Demacia"]},
}


def test_le_script_de_telechargement_garde_ses_deux_garde_fous():
    print("\n-- les deux défauts du 06/09/2026 --")
    # L'ancien script n'avait AUCUN bloc __main__ : le lancer
    # n'exécutait rien et ne créait aucun fichier.
    source = (_ICI / "LoR-Bot" / "code" / "download_card_sets.py").read_text(
        encoding="utf-8")
    check('le script a un bloc __main__', '__name__ == "__main__"' in source)
    # Et il écrivait dans un `card_sets` RELATIF au répertoire courant,
    # donc là où `lor_api` ne regarde jamais.
    check("le dossier de sortie est absolu", dcs.CARD_SET_FOLDER.is_absolute(),
          dcs.CARD_SET_FOLDER)
    check("le dossier de sortie est celui que lor_api lit",
          dcs.CARD_SET_FOLDER == lor_api.CARD_SETS_PATH,
          (dcs.CARD_SET_FOLDER, lor_api.CARD_SETS_PATH))


def test_le_module_du_wiki_se_lit_sans_etre_execute():
    print("\n-- lecture de la table Lua --")
    cartes = dcs.lire_module_wiki(MODULE_LUA_FACTICE)
    check("trois cartes lues, la clé parasite écartée",
          set(cartes) == {"99PZ130", "99PZ104", "99XX999"}, sorted(cartes))
    pow_pow = cartes["99PZ130"]
    check("le coût est lu", pow_pow.get("cost") == 2, pow_pow.get("cost"))
    check("les mots-clés sont une liste",
          pow_pow.get("keywords") == ["Burst"], pow_pow.get("keywords"))
    check("une carte retirée du jeu est reconnue comme telle",
          cartes["99XX999"].get("removed") is True)


def test_le_wikicode_ne_passe_pas_dans_la_description():
    print("\n-- nettoyage du wikicode --")
    # `spells.py` compte des marqueurs dans un texte ANGLAIS : un
    # « {{TipLoR|unit}} » resté dans le texte ferait rater « a unit ».
    texte = dcs.nettoyer_wikicode(
        "Deal 3 to a {{TipLoR|unit}}.<br/>See {{LoR|Jinx|the Loose Cannon}}.")
    check("les modèles sont développés", "{{" not in texte and "}}" not in texte,
          texte)
    check("le marqueur de cible survit", "to a unit." in texte, texte)
    check("le libellé affiché l'emporte", "the Loose Cannon" in texte, texte)
    check("<br/> devient un saut de ligne", "\n" in texte, repr(texte))
    check("un lien perd ses crochets",
          dcs.nettoyer_wikicode("[[LoR:Pow-Pow|Pow-Pow]] fires.")
          == "Pow-Pow fires.")
    check("un texte vide reste vide", dcs.nettoyer_wikicode("") == "")


def test_les_references_se_deduisent_de_la_base_de_riot():
    print("\n-- libellé affiché -> référence interne --")
    mots, regions = dcs.correspondances(BASE_RIOT_FACTICE)
    check("« Quick Attack » -> « QuickStrike »",
          mots.get("Quick Attack") == "QuickStrike", mots)
    check("« Piltover & Zaun » -> « PiltoverZaun »",
          regions.get("Piltover & Zaun") == "PiltoverZaun", regions)
    # Rien n'est inventé : un libellé inconnu retombe sur lui-même,
    # débarrassé de sa ponctuation — `BoardCard.has()` compare
    # justement casse et ponctuation ignorées.
    check("un mot-clé inconnu retombe sur lui-même",
          dcs._reference("Can't Block", mots) == "CantBlock")


def test_une_carte_du_wiki_prend_la_forme_du_data_dragon():
    print("\n-- conversion vers la forme DDragon --")
    cartes = dcs.lire_module_wiki(MODULE_LUA_FACTICE)
    mots, regions = dcs.correspondances(BASE_RIOT_FACTICE)
    sort = dcs.en_forme_ddragon("99PZ130", cartes["99PZ130"], mots, regions)
    unite = dcs.en_forme_ddragon("99PZ104", cartes["99PZ104"], mots, regions)

    check("le code est porté", sort["cardCode"] == "99PZ130")
    check("la description est en clair",
          sort["descriptionRaw"].startswith("Deal 3 to a unit."),
          sort["descriptionRaw"])
    # Le wiki range parfois un chiffre de sort dans `power` ; le Data
    # Dragon met 0, et `game_state` lit `attack` sans se demander si la
    # carte est une unité.
    check("un SORT n'a ni attaque ni PV",
          (sort["attack"], sort["health"]) == (0, 0),
          (sort["attack"], sort["health"]))
    check("la vitesse du sort est déduite des mots-clés",
          sort["spellSpeedRef"] == "Burst", sort["spellSpeedRef"])
    check("une UNITÉ garde ses stats",
          (unite["attack"], unite["health"]) == (3, 3))
    check("les mots-clés sont traduits en références",
          unite["keywordRefs"] == ["QuickStrike"], unite["keywordRefs"])
    check("la région est traduite",
          unite["regionRefs"] == ["PiltoverZaun"], unite["regionRefs"])
    # PROVENANCE : aucune ligne de cette base ne doit pouvoir passer
    # pour une donnée de Riot.
    check("la provenance est écrite sur chaque carte",
          sort["source"] == dcs.WIKI_SOURCE and unite["source"] == dcs.WIKI_SOURCE)


def test_le_fichier_hors_ddragon_ne_peut_pas_ecraser_riot():
    print("\n-- l'ordre de chargement --")
    # `load_card_db` parcourt le dossier TRIÉ et écrase au fur et à
    # mesure : le dernier fichier gagne. Le nôtre doit donc passer
    # AVANT `set*.json` et `tpoc.json`, pour que Riot l'emporte le jour
    # où il publierait une de ces cartes.
    noms = sorted([dcs.WIKI_FILE, "set1.json", "set9.json", "tpoc.json"])
    check("il se trie avant les paquets de Riot", noms[0] == dcs.WIKI_FILE,
          noms)


def test_les_cartes_des_aventures_sont_connues():
    print("\n-- les cinq codes vus en jeu --")
    total, hors, manquants = lor_api.etat_base_cartes()
    if total < 1000:
        print(f"  (base absente ou vide : {total} cartes — "
              f"lance LoR-Bot/code/download_card_sets.py)")
        check("base de cartes présente", False, total)
        return
    check("aucun code témoin ne manque", not manquants, manquants)
    check("des cartes hors Data Dragon sont chargées", hors > 0, hors)
    db = lor_api.load_card_db()
    for code in lor_api.CODES_TEMOINS:
        carte = db.get(code) or {}
        check(f"{code} a un nom et un coût",
              bool(carte.get("name")) and carte.get("cost") is not None,
              carte.get("name"))
        check(f"{code} a un type",
              (carte.get("type") or "").lower() in ("unit", "spell",
                                                    "landmark", "equipment",
                                                    "ability"),
              carte.get("type"))
    # Le texte doit rester en ANGLAIS : tout `spells.py` classe des
    # textes anglais, passer en fr_fr casserait le classifieur.
    pow_pow = db.get("99PZ130") or {}
    check("la description est en anglais",
          "Deal" in (pow_pow.get("descriptionRaw") or ""),
          pow_pow.get("descriptionRaw"))


def main() -> int:
    for test in (
        test_le_port_par_defaut_ne_coute_rien,
        test_le_port_voisin_est_trouve,
        test_un_port_ouvert_qui_repond_autre_chose_est_ecarte,
        test_aucun_port_ne_repond,
        test_un_port_qui_repond_mal_ne_declenche_pas_de_recherche,
        test_set_et_lecture_du_port,
        test_les_candidats_couvrent_le_cas_vu,
        test_le_script_de_telechargement_garde_ses_deux_garde_fous,
        test_le_module_du_wiki_se_lit_sans_etre_execute,
        test_le_wikicode_ne_passe_pas_dans_la_description,
        test_les_references_se_deduisent_de_la_base_de_riot,
        test_une_carte_du_wiki_prend_la_forme_du_data_dragon,
        test_le_fichier_hors_ddragon_ne_peut_pas_ecraser_riot,
        test_les_cartes_des_aventures_sont_connues,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} échec(s) : {', '.join(FAILURES)}")
        return 1
    print("Tous les tests de l'API passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
