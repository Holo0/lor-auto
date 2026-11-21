#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_journal.py

LA BOUSSOLE DU PROJET. `python journal.py --ecartees` dit « la prochaine
brique à coder » ; encore faut-il qu'il la cherche dans des parties
RÉCENTES. Au 08/11/2026 il cumulait 142 lignes depuis le 07/08/2026 sans
aucun filtre de date, et désignait donc des bogues MORTS — « Buhru
Lookout ×14 » est la saisie dans une main pleine, corrigée le 06/09/2026.

    .venv/Scripts/python.exe test_journal.py

Hors ligne, et surtout : CETTE SUITE N'OUVRE JAMAIS LE VRAI
`journal.jsonl`. Elle travaille sur un fichier temporaire, et vérifie à
la fin que le journal d'Ewan est octet pour octet celui du départ — le
05/11/2026, une suite hors ligne y avait ajouté 30 fausses tentatives
qu'il a fallu nettoyer à la main.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

import journal

ROOT = Path(__file__).resolve().parent

FAILURES = []

# Le jour où ce bogue a été constaté : toutes les fenêtres des tests se
# calculent par rapport à cette date, jamais par rapport à « maintenant »
# — sinon la suite changerait de verdict demain.
AUJOURDHUI = "2026-11-08"


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ---------------------------------------------------------------- journal faux
#
# Une miniature du vrai journal, aux mêmes proportions : deux sessions de
# septembre dont le motif dominant n'existe PLUS dans le code (il a été
# renommé le 06/09/2026 avec la mise en place de `carry`), et trois
# combats de novembre qui portent, eux, le backlog vivant.

MOTIF_MORT = "pose ratée : mise de côté pour ce tour"
MOTIF_VIVANT = "pouvoir à cibler : N carte(s) à désigner en main, N disponible"
MOTIF_CONTEXTE = "coût N (lu à l'écran) > mana N"


def _combat(horodatage, config, ecartees, gagne=False, duree=120.0, id_=None):
    ligne = {
        "id": id_ or f"c{abs(hash(horodatage)) % 10 ** 6}",
        "tours": 6,
        "cartes": 4,
        "attaques": 2,
        "blocages": 1,
        "duree": duree,
        "gagne": gagne,
        "termine": True,
        "arret": "retour aux menus",
        "verdict": "",
        "config": config,
        "ecartees": ecartees,
    }
    if horodatage is not None:
        ligne["horodatage"] = horodatage
    return ligne


def _tentative(horodatage, palier, etoiles, gagne):
    return {
        "id": f"t{palier}-{etoiles}-{horodatage}",
        "type": "tentative",
        "horodatage": horodatage,
        "palier": palier,
        "etoiles": etoiles,
        "gagne": gagne,
        "raison": "fin de parcours",
        "duree": 900.0,
        "combats": 3,
    }


def _ecart(carte, motif, n):
    return {"carte": carte, "motif": motif, "n": n}


# LES CONFIGURATIONS DU VRAI JOURNAL, à la valeur près. Leur clé fait 87 à
# 106 caractères et les quatre ne diffèrent QUE par leur dernier champ :
# c'est exactement la forme qui s'affichait en quatre lignes identiques,
# tronquées au 40e caractère (mesuré le 09/11/2026 sur journal.jsonl).
def _config(archetype=None):
    config = {"restrictions": False, "spells": False, "chump": False,
              "nexus_weight": 1.0, "screen_costs": True, "ocr": True}
    if archetype is not None:
        config["archetype"] = archetype
    return config


LIGNES = [
    # --- septembre : le bogue de la main pleine, corrigé depuis ---------
    _combat("2026-09-05 21:10:00", {"restrictions": True},
            [_ecart("Buhru Lookout", MOTIF_MORT, 9)]),
    _combat("2026-09-06 11:02:00", {"restrictions": True},
            [_ecart("Buhru Lookout", MOTIF_MORT, 14),
             _ecart("07BW043", MOTIF_MORT, 6)]),
    _tentative("2026-09-06 11:40:00", 2, 1, False),

    # --- novembre : le backlog vivant -----------------------------------
    _combat("2026-11-05 19:24:00", {"restrictions": False},
            [_ecart("Jarro Lightfeather", MOTIF_VIVANT, 4),
             _ecart("99SH003", MOTIF_CONTEXTE, 40)]),
    _combat("2026-11-06 11:03:00", {"restrictions": False},
            [_ecart("Jarro Lightfeather", MOTIF_VIVANT, 6)], gagne=True),
    _combat("2026-11-08 20:19:00", {"restrictions": False},
            [_ecart("Vladimir", "bannie pour le reste du combat (pose figée, annulée)", 2)]),
    _tentative("2026-11-06 14:47:00", 13, 7, True),

    # --- une ligne abîmée : plus de date lisible -------------------------
    _combat(None, {"restrictions": False},
            [_ecart("Carte sans date", "motif orphelin", 1)], id_="sans-date"),
]


# Quatre combats qui ne diffèrent QUE par leur archétype — la question
# même que le tableau existe pour trancher (« quel plan de jeu gagne ? »).
LIGNES_CONFIGS = [
    _combat("2026-11-01 10:00:00", _config("aggro"), [], gagne=True),
    _combat("2026-11-02 10:00:00", _config("midrange"), []),
    _combat("2026-11-03 10:00:00", _config("tirage"), [], gagne=True),
    _combat("2026-11-04 10:00:00", _config(), []),
]


def _combat_sans_ecartees(horodatage):
    """Un combat d'avant le 05/09/2026 : le champ `ecartees` n'existe pas."""
    ligne = _combat(horodatage, {"restrictions": True}, [])
    ligne.pop("ecartees")
    return ligne


# Trois sortes de lignes hors fenêtre, en trois nombres DIFFÉRENTS, pour
# qu'aucune vue ne puisse réussir en recopiant le compte d'une autre :
# 3 combats, dont 1 seul porte des cartes écartées, et 2 tentatives.
LIGNES_EXCLUSIONS = [
    # --- avant la fenêtre ----------------------------------------------
    _combat("2026-09-05 21:10:00", {"restrictions": True},
            [_ecart("Buhru Lookout", MOTIF_MORT, 9)]),
    _combat_sans_ecartees("2026-09-04 18:00:00"),
    _combat_sans_ecartees("2026-09-03 18:00:00"),
    _tentative("2026-09-06 11:40:00", 2, 1, False),
    _tentative("2026-09-07 11:40:00", 3, 1, False),
    # --- dans la fenêtre ------------------------------------------------
    _combat("2026-11-05 19:24:00", {"restrictions": False},
            [_ecart("Jarro Lightfeather", MOTIF_VIVANT, 4)]),
    _tentative("2026-11-06 14:47:00", 13, 7, True),
]

# Le cas du vrai journal au 09/11/2026 : des combats hors fenêtre, et
# AUCUNE tentative. `--champions` ne doit pas crier à l'exclusion.
LIGNES_FAUSSE_ALERTE = [
    _combat("2026-09-05 21:10:00", {"restrictions": True}, []),
    _tentative("2026-11-06 14:47:00", 13, 7, True),
]


@contextlib.contextmanager
def journal_faux(lignes=LIGNES):
    """Un journal jetable, dans un dossier temporaire. Jamais celui d'Ewan."""
    with tempfile.TemporaryDirectory(prefix="lor-journal-") as dossier:
        chemin = Path(dossier) / "journal.jsonl"
        chemin.write_text(
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lignes),
            encoding="utf8")
        yield chemin


def sortie(fonction, *args, **kwargs):
    """Le texte imprimé par une vue, pour pouvoir l'interroger."""
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        fonction(*args, **kwargs)
    return tampon.getvalue()


# ------------------------------------------------------------------- les tests

def test_une_date_se_lit_ou_ne_se_lit_pas():
    print("\nLire la date d'une ligne — ou avouer qu'il n'y en a pas")
    check("un horodatage complet donne sa date",
          journal.date_de({"horodatage": "2026-11-08 20:19:00"}) == "2026-11-08")
    check("une date seule aussi",
          journal.date_de({"horodatage": "2026-09-06"}) == "2026-09-06")
    # Une ligne non datée ne doit NI faire planter la commande NI
    # disparaître en silence : `date_de` dit None, et c'est la vue qui
    # décide (elle la garde, et le dit).
    check("pas d'horodatage -> None", journal.date_de({}) is None)
    check("horodatage vide -> None", journal.date_de({"horodatage": ""}) is None)
    check("horodatage illisible -> None",
          journal.date_de({"horodatage": "hier soir"}) is None)
    check("un horodatage non ISO ne rend pas une date approchée",
          journal.date_de({"horodatage": "06/09/2026 11:02"}) is None)


def test_la_fenetre_par_defaut_est_de_trente_jours():
    print("\nLa fenêtre : trente jours par défaut, « tout » sur demande")
    check("par défaut, trente jours en arrière",
          journal.borne_depuis(aujourdhui=AUJOURDHUI) == "2026-10-09",
          journal.borne_depuis(aujourdhui=AUJOURDHUI))
    check("--depuis tout rend None (aucune borne)",
          journal.borne_depuis(depuis="tout", aujourdhui=AUJOURDHUI) is None)
    check("--jours N compte en arrière",
          journal.borne_depuis(jours=3, aujourdhui=AUJOURDHUI) == "2026-11-05",
          journal.borne_depuis(jours=3, aujourdhui=AUJOURDHUI))
    check("--jours 0 vaut « aujourd'hui »",
          journal.borne_depuis(jours=0, aujourdhui=AUJOURDHUI) == AUJOURDHUI)
    check("--depuis l'emporte sur --jours",
          journal.borne_depuis(depuis="2026-09-01", jours=3,
                               aujourdhui=AUJOURDHUI) == "2026-09-01")
    # Une date mal tapée doit se voir tout de suite, pas filtrer en silence.
    erreur = None
    try:
        journal.borne_depuis(depuis="06/09/2026", aujourdhui=AUJOURDHUI)
    except ValueError as exc:
        erreur = str(exc)
    check("une date mal écrite est refusée, avec le format attendu",
          erreur is not None and "AAAA-MM-JJ" in erreur, erreur)
    # ET LA FORME NE SUFFIT PAS : « 2026-13-45 » passe le gabarit
    # \d{4}-\d{2}-\d{2} sans etre une date. Compare tel quel, il vidait la
    # fenetre en ne disant rien de plus qu'un « Aucun combat » : le
    # filtrage silencieux que cette option existe pour empecher.
    impossible = None
    try:
        journal.borne_depuis(depuis="2026-13-45", aujourdhui=AUJOURDHUI)
    except ValueError as exc:
        impossible = str(exc)
    check("une date bien formee mais impossible est refusee aussi",
          impossible is not None, impossible)
    check("un 30 fevrier aussi",
          journal.borne_depuis.__name__ and _refuse("2026-02-30"))
    check("mais une vraie date passe",
          journal.borne_depuis(depuis="2026-02-28",
                               aujourdhui=AUJOURDHUI) == "2026-02-28")


def _refuse(texte):
    try:
        journal.borne_depuis(depuis=texte, aujourdhui=AUJOURDHUI)
    except ValueError:
        return True
    return False


def _code_de_sortie(options):
    """
    (code de sortie, texte d'erreur) de `python journal.py <options>`.

    `parser.error` sort par un SystemExit de code 2 ; le bogue, lui,
    laissait remonter une exception — c'est la différence qu'on mesure.
    Les trois vues sont bouchonnées : `main()` les appelle SANS `path`,
    donc sur le vrai journal d'Ewan.
    """
    erreur, vraies, argv = io.StringIO(), (journal.cmd_summary,
                                           journal.cmd_rejections,
                                           journal.cmd_champions), sys.argv

    def muette(last=None, depuis=None, path=None):
        pass

    journal.cmd_summary = journal.cmd_rejections = journal.cmd_champions = muette
    sys.argv = ["journal.py"] + list(options)
    code = "(aucune sortie)"
    try:
        with contextlib.redirect_stderr(erreur), contextlib.redirect_stdout(io.StringIO()):
            journal.main()
    except SystemExit as exc:
        code = exc.code
    except Exception as exc:          # noqa: BLE001 — LE BOGUE : il remontait tel quel
        code = repr(exc)
    finally:
        (journal.cmd_summary, journal.cmd_rejections, journal.cmd_champions) = vraies
        sys.argv = argv
    return code, erreur.getvalue()


def test_une_fenetre_qui_remonte_avant_le_calendrier_est_refusee():
    """
    LE BOGUE (09/11/2026) : `--jours` avec une valeur énorme sortait par
    un TRACEBACK, là où une date impossible est refusée proprement depuis
    le 08/11. Deux façons de demander l'impossible, deux sorties.

    Mesuré, depuis le 2026-11-08 (ordinal 739928, donc 739 927 jours de
    recul au maximum — l'an 1) :

        --jours 739000       -> 0003-07-17, légitime
        --jours 739999       -> OverflowError: date value out of range
        --jours 4000000      -> OverflowError: date value out of range
        --jours 100000000000 -> OverflowError: Python int too large to
                                convert to C int (dans le timedelta)

    On ne refuse que ce qui ne se CALCULE pas : une fenêtre simplement
    énorme reste une fenêtre, et vaut « tout l'historique ».
    """
    print("\nLE BOGUE : --jours énorme sortait par un traceback")
    check("une fenêtre énorme mais calculable reste acceptée",
          journal.borne_depuis(jours=739000, aujourdhui=AUJOURDHUI) == "0003-07-17",
          journal.borne_depuis(jours=739000, aujourdhui=AUJOURDHUI))
    for jours in (739999, 4_000_000, 100_000_000_000):
        erreur = None
        try:
            journal.borne_depuis(jours=jours, aujourdhui=AUJOURDHUI)
        except ValueError as exc:
            erreur = str(exc)
        except Exception as exc:      # noqa: BLE001 — l'OverflowError d'origine
            erreur = f"(exception non traduite) {exc!r}"
        check(f"--jours {jours} est refusé, sans traceback",
              erreur is not None and "non traduite" not in erreur, erreur)
        check(f"--jours {jours} renvoie vers l'option qui fait le travail",
              erreur is not None and "--depuis tout" in erreur, erreur)
    # Et de bout en bout : la commande doit SORTIR comme argparse sort,
    # pas s'effondrer.
    code, texte = _code_de_sortie(["--jours", "4000000"])
    check("la commande sort par un parser.error (code 2)", code == 2, (code, texte))
    check("et elle dit pourquoi", "--depuis tout" in texte, texte)
    # Le filet : une fenêtre normale ne doit pas être refusée au passage.
    code, texte = _code_de_sortie(["--jours", "7"])
    check("une fenêtre de sept jours passe toujours", code == "(aucune sortie)",
          (code, texte))


def _depuis_vu(options):
    """
    La borne que `main()` passe REELLEMENT a la vue, pour ces options.

    On espionne la vue au lieu de la laisser lire : `main()` appelle les
    trois vues SANS `path`, donc sur le vrai journal d'Ewan.
    """
    recus = []

    def espion(last=None, depuis=None, path=None):
        recus.append(depuis)

    vraies = (journal.cmd_summary, journal.cmd_rejections, journal.cmd_champions)
    argv = sys.argv
    journal.cmd_summary = espion
    journal.cmd_rejections = espion
    journal.cmd_champions = espion
    sys.argv = ["journal.py"] + list(options)
    try:
        journal.main()
    finally:
        journal.cmd_summary, journal.cmd_rejections, journal.cmd_champions = vraies
        sys.argv = argv
    return recus


def test_la_commande_applique_vraiment_sa_fenetre():
    """
    LE FIL QUI MANQUAIT ENTRE LES OPTIONS ET LES VUES.

    `borne_depuis` est juste, et les vues savent filtrer quand on leur
    passe une borne - les deux sont verrouilles plus haut. Mais RIEN ne
    verifiait que la commande les relie, parce que tous les autres tests
    appellent les vues en leur passant `depuis` a la main.

    Mesure le 08/11/2026 : remplacer `depuis = borne_depuis(args.depuis,
    args.jours)` par `depuis = None` dans `main()` remet le bogue
    d'origine en entier - `python journal.py --ecartees` relit tout
    l'historique et redesigne une brique deja posee - et les onze tests
    de cette suite restent VERTS. Un test qui passe dans les deux cas ne
    verrouille rien : celui-ci echoue.
    """
    print("")
    print("Le fil entre les options et les vues — sans lui, le bogue revient")
    attendue = journal.borne_depuis()
    check("la fenetre par defaut est bien une borne, pas « tout »",
          attendue is not None, attendue)
    for nom, options in (("python journal.py", []),
                         ("--ecartees", ["--ecartees"]),
                         ("--champions", ["--champions"])):
        vu = _depuis_vu(options)
        check(f"« {nom} » borne par defaut (il ne relit pas tout)",
              vu == [attendue], (vu, attendue))
    for nom, options in (("--depuis tout", ["--depuis", "tout"]),
                         ("--ecartees --depuis tout",
                          ["--ecartees", "--depuis", "tout"]),
                         ("--champions --depuis tout",
                          ["--champions", "--depuis", "tout"])):
        vu = _depuis_vu(options)
        check(f"« {nom} » rouvre bien l'historique entier", vu == [None], vu)
    check("--depuis AAAA-MM-JJ arrive tel quel jusqu'a la vue",
          _depuis_vu(["--ecartees", "--depuis", "2026-09-01"]) == ["2026-09-01"])
    check("--jours N arrive traduit en borne",
          _depuis_vu(["--jours", "3"]) == [journal.borne_depuis(jours=3)])


def _lignes_du_tableau(texte):
    """Les lignes de données du tableau des configurations."""
    lignes = texte.splitlines()
    debut = next(i for i, l in enumerate(lignes) if l.startswith("configuration"))
    corps = []
    for ligne in lignes[debut + 2:]:        # + l'en-tête et son soulignement
        if not ligne.strip():
            break
        corps.append(ligne)
    return corps


def _colonne_config(ligne):
    """
    Le libellé de configuration d'une ligne du tableau.

    Les chiffres sont séparés du libellé par au moins deux espaces (la
    colonne est cadrée à gauche, « joués » à droite) ; le libellé, lui,
    n'a que des espaces simples entre ses champs.
    """
    return re.split(r"\s{2,}", ligne.strip())[0]


def test_deux_configurations_differentes_ne_sappellent_pas_pareil():
    """
    LE BOGUE (09/11/2026) : la colonne « configuration » était cadrée à 40
    caractères, clé TRONQUÉE comprise. Mesuré sur journal.jsonl, les sept
    clés font 41 à 106 caractères et six partagent les mêmes 77 premiers :
    `python journal.py --depuis tout` affichait donc quatre lignes
    RIGOUREUSEMENT IDENTIQUES — « restrictions=False spells=False
    chump=Fa » — alors qu'elles comparaient aggro, midrange, tirage et
    aucun archétype. Le tableau censé répondre « quel réglage aide ? »
    répondait la même chose quatre fois.
    """
    print("\nLE BOGUE : quatre configurations, quatre libellés identiques")
    with journal_faux(LIGNES_CONFIGS) as chemin:
        texte = sortie(journal.cmd_summary, last=None, depuis=None, path=chemin)
    colonnes = [_colonne_config(l) for l in _lignes_du_tableau(texte)]
    check("le tableau porte bien quatre lignes", len(colonnes) == 4, colonnes)
    check("et quatre libellés DIFFÉRENTS", len(set(colonnes)) == 4, colonnes)
    for archetype in ("aggro", "midrange", "tirage"):
        check(f"l'archétype « {archetype} » se lit dans le tableau",
              archetype in texte, texte)
    # Le symptôme exact : un champ coupé en plein milieu de sa valeur.
    check("plus aucun champ coupé au 40e caractère",
          re.search(r"chump=Fa(?!lse)", texte) is None, texte)
    # Ce qui rend la lecture possible : le tronc commun est dit UNE fois,
    # et la colonne ne porte plus que ce qui distingue les lignes.
    tronc = [l for l in texte.splitlines() if l.startswith("Commun aux ")]
    check("le tronc commun est annoncé une seule fois, et en entier",
          len(tronc) == 1 and "ocr=True" in tronc[0] and "chump=False" in tronc[0],
          tronc)
    check("et il est annoncé AVANT le tableau",
          tronc and texte.index(tronc[0]) < texte.index("\nconfiguration"), texte)
    check("la colonne ne garde que ce qui distingue",
          set(colonnes) == {"archetype=aggro", "archetype=midrange",
                            "archetype=tirage", "(rien de plus)"}, colonnes)


def test_une_seule_configuration_sannonce_en_entier():
    """
    Pas de tronc commun quand il n'y a rien à distinguer : une seule
    configuration doit s'écrire ENTIÈRE dans la colonne, sinon elle
    deviendrait « (rien de plus) » et le tableau ne dirait plus rien.
    """
    print("\nUne seule configuration : elle s'écrit en entier")
    with journal_faux(LIGNES_CONFIGS[:1]) as chemin:
        texte = sortie(journal.cmd_summary, last=None, depuis=None, path=chemin)
    colonnes = [_colonne_config(l) for l in _lignes_du_tableau(texte)]
    check("une ligne, et c'est la clé complète",
          colonnes == [journal.config_key(_config("aggro"))], colonnes)


def test_la_boussole_ne_pointe_plus_un_bogue_mort():
    print("\nLE BOGUE : --ecartees désignait une brique déjà posée")
    with journal_faux() as chemin:
        recent = sortie(journal.cmd_rejections, last=None,
                        depuis="2026-10-09", path=chemin)
        tout = sortie(journal.cmd_rejections, last=None, depuis=None, path=chemin)

    # Sur tout l'historique, le motif de septembre écrase le reste : c'est
    # exactement ce que la commande répondait au 08/11/2026.
    check("sur tout l'historique, le motif mort est encore en tête",
          f"Prochaine brique suggérée : « {MOTIF_MORT} »" in tout, tout)
    check("et Buhru Lookout y figure", "Buhru Lookout" in tout)

    # Dans la fenêtre récente, il a disparu — il ne s'est plus produit une
    # seule fois depuis le 06/09/2026.
    check("dans la fenêtre, le motif mort a disparu",
          MOTIF_MORT not in recent, recent)
    check("et Buhru Lookout avec lui", "Buhru Lookout" not in recent)
    check("la brique suggérée est celle qui coûte ENCORE du temps",
          f"Prochaine brique suggérée : « {MOTIF_VIVANT} »" in recent, recent)


def _hors_fenetre(texte):
    """(combien, quelle sorte de ligne) la vue dit avoir laissées dehors."""
    trouve = re.search(r"hors fenêtre : (\d+) (\w+)\(s\)", texte)
    return (int(trouve.group(1)), trouve.group(2)) if trouve else None


def test_chaque_vue_compte_les_lignes_quelle_regarde():
    """
    LE BOGUE (09/11/2026) : `--champions` annonçait « 68 ligne(s)
    antérieure(s) non comptée(s) — `--depuis tout` » alors qu'AUCUNE
    tentative n'était exclue par la fenêtre.

    Mesuré sur le vrai journal ce jour-là : 145 lignes, dont 111 combats
    et 34 tentatives ; la fenêtre de trente jours en laisse 68 dehors, et
    ce sont **68 combats, 0 tentative**. La vue renvoyait donc vers un
    `--depuis tout` qui affiche exactement le même tableau — une boussole
    qui s'excuse de ne pas tout montrer alors qu'elle montre tout.

    `--ecartees` annonçait 68 aussi, et c'était faux dans l'autre sens :
    53 de ces combats sont antérieurs au 05/09/2026 et n'ont même pas de
    champ `ecartees` — cette vue ne les aurait jamais comptés. **15**
    seulement la concernaient.

    Seule la vue des configurations avait raison, et par accident : elle
    compte les combats, et les 68 exclues en étaient.
    """
    print("\nLE BOGUE : un compte d'exclues qui ne regarde pas la bonne pile")
    with journal_faux(LIGNES_EXCLUSIONS) as chemin:
        conf = sortie(journal.cmd_summary, last=None,
                      depuis="2026-10-09", path=chemin)
        ecartees = sortie(journal.cmd_rejections, last=None,
                          depuis="2026-10-09", path=chemin)
        champions = sortie(journal.cmd_champions, last=None,
                           depuis="2026-10-09", path=chemin)
    check("les configurations laissent dehors 3 COMBATS",
          _hors_fenetre(conf) == (3, "combat"), (_hors_fenetre(conf), conf))
    check("--ecartees n'en compte qu'UN : les deux autres n'ont pas le champ",
          _hors_fenetre(ecartees) == (1, "combat"),
          (_hors_fenetre(ecartees), ecartees))
    check("--champions compte 2 TENTATIVES, et le dit dans son mot à lui",
          _hors_fenetre(champions) == (2, "tentative"),
          (_hors_fenetre(champions), champions))

    # Et le cas qui a donné l'alerte : rien d'exclu de CETTE vue, donc
    # pas un mot d'exclusion — juste le rappel de la fenêtre.
    with journal_faux(LIGNES_FAUSSE_ALERTE) as chemin:
        champions = sortie(journal.cmd_champions, last=None,
                           depuis="2026-10-09", path=chemin)
        conf = sortie(journal.cmd_summary, last=None,
                      depuis="2026-10-09", path=chemin)
    check("aucune tentative exclue : --champions ne crie pas à l'exclusion",
          _hors_fenetre(champions) is None, champions)
    check("mais il rappelle quand même sa fenêtre",
          "fenêtre : depuis le 2026-10-09" in champions, champions)
    check("pendant que les configurations, elles, ont bien un combat dehors",
          _hors_fenetre(conf) == (1, "combat"), (_hors_fenetre(conf), conf))


def test_chaque_vue_ecrit_la_fenetre_quelle_a_lue():
    print("\nChaque vue dit sur quoi elle porte — sinon on croit tout lire")
    with journal_faux() as chemin:
        vues = {
            "configurations": sortie(journal.cmd_summary, last=None,
                                     depuis="2026-10-09", path=chemin),
            "écartées": sortie(journal.cmd_rejections, last=None,
                               depuis="2026-10-09", path=chemin),
            "champions": sortie(journal.cmd_champions, last=None,
                                depuis="2026-10-09", path=chemin),
        }
        tout = sortie(journal.cmd_summary, last=None, depuis=None, path=chemin)

    for nom, texte in vues.items():
        check(f"« {nom} » annonce la borne 2026-10-09",
              "depuis le 2026-10-09" in texte, texte[:200])
        check(f"« {nom} » dit comment voir l'historique entier",
              "--depuis tout" in texte, texte[:400])
    check("sans borne, la vue annonce l'historique entier",
          "tout l'historique" in tout, tout[:200])


def test_une_ligne_sans_date_est_gardee_et_annoncee():
    print("\nUne ligne non datée : gardée, et DITE — jamais perdue en silence")
    with journal_faux() as chemin:
        recent = sortie(journal.cmd_rejections, last=None,
                        depuis="2026-10-09", path=chemin)
    check("son motif est toujours compté", "motif orphelin" in recent, recent)
    check("et la vue prévient qu'elle en a gardé une",
          "sans date" in recent, recent)


def test_la_fenetre_porte_aussi_sur_les_tentatives():
    print("\n--champions : la table d'allocation se lit sur les tentatives récentes")
    with journal_faux() as chemin:
        recent = sortie(journal.cmd_champions, last=None,
                        depuis="2026-10-09", path=chemin)
        tout = sortie(journal.cmd_champions, last=None, depuis=None, path=chemin)
    check("la tentative de novembre (palier 13, 7 étoiles) est là",
          "13" in recent and "1 tentative" in recent, recent)
    check("celle de septembre (palier 2, 1 étoile) est hors fenêtre",
          "2 tentative" in tout and "2 tentative" not in recent, recent)


def test_une_tentative_ne_pollue_pas_le_tableau_des_configurations():
    print("\nUne ligne « tentative » n'est pas un combat, fenêtre ou pas")
    with journal_faux() as chemin:
        tout = sortie(journal.cmd_summary, last=None, depuis=None, path=chemin)
        entrees = journal.read_all(chemin)
    combats = [e for e in entrees if journal.est_combat(e)]
    check("le journal faux porte bien 6 combats et 2 tentatives",
          len(combats) == 6 and len(journal.tentatives(entrees)) == 2,
          (len(combats), len(journal.tentatives(entrees))))
    # L'en-tête comptait les LIGNES, tentatives comprises, sous le mot
    # « combats » : il compte désormais les combats.
    check("l'en-tête compte 6 combats, pas 8 lignes",
          "6 combat" in tout and "8 combat" not in tout, tout[:200])
    check("aucune configuration vide dans le tableau",
          "(par défaut)" not in tout, tout)


def test_les_motifs_de_contexte_restent_a_part():
    print("\nMana, place, cible : comptés, mais jamais suggérés comme brique")
    with journal_faux() as chemin:
        recent = sortie(journal.cmd_rejections, last=None,
                        depuis="2026-10-09", path=chemin)
    check("le motif de mana est bien dans la table de contexte",
          MOTIF_CONTEXTE in recent, recent)
    check("mais il n'est jamais la brique suggérée",
          f"Prochaine brique suggérée : « {MOTIF_CONTEXTE} »" not in recent)
    check("is_context_reason le classe toujours à part",
          journal.is_context_reason(MOTIF_CONTEXTE)
          and not journal.is_context_reason(MOTIF_VIVANT))


def test_une_fenetre_vide_le_dit_sans_planter():
    print("\nUne fenêtre sans rien dedans : on le dit, on ne devine pas")
    # Sans la ligne non datée : elle est gardée dans TOUTES les fenêtres
    # (on ne peut pas la situer), donc elle empêcherait une fenêtre d'être
    # vide — ce que le test précédent vérifie déjà.
    datees = [l for l in LIGNES if l.get("id") != "sans-date"]
    with journal_faux(datees) as chemin:
        vide = sortie(journal.cmd_rejections, last=None,
                      depuis="2027-01-01", path=chemin)
        vide_conf = sortie(journal.cmd_summary, last=None,
                           depuis="2027-01-01", path=chemin)
        vide_champ = sortie(journal.cmd_champions, last=None,
                            depuis="2027-01-01", path=chemin)
    check("--ecartees ne suggère aucune brique sur une fenêtre vide",
          "Prochaine brique suggérée" not in vide, vide)
    for nom, texte in (("écartées", vide), ("configurations", vide_conf),
                       ("champions", vide_champ)):
        check(f"« {nom} » renvoie vers --depuis tout",
              "--depuis tout" in texte, texte)


def test_un_journal_absent_ne_plante_pas():
    print("\nPas de journal du tout : aucune des trois vues ne lève")
    with tempfile.TemporaryDirectory(prefix="lor-journal-") as dossier:
        absent = Path(dossier) / "pas-de-journal.jsonl"
        for nom, vue in (("configurations", journal.cmd_summary),
                         ("écartées", journal.cmd_rejections),
                         ("champions", journal.cmd_champions)):
            try:
                texte = sortie(vue, last=None, depuis="2026-10-09", path=absent)
                check(f"« {nom} » survit à un journal absent", bool(texte.strip()))
            except Exception as exc:              # noqa: BLE001
                check(f"« {nom} » survit à un journal absent", False, repr(exc))
        check("et rien n'a été créé", not absent.exists())


def test_le_vrai_journal_nest_jamais_touche():
    """Le filet : la suite a-t-elle laissé `journal.jsonl` intact ?"""
    print("\nLe journal d'Ewan, octet pour octet")
    check("le vrai journal n'a pas bougé pendant la suite",
          _empreinte_vrai_journal() == EMPREINTE_DEPART,
          "le journal.jsonl du projet a été modifié par la suite !")


def _empreinte_vrai_journal():
    vrai = ROOT / "journal.jsonl"
    if not vrai.exists():
        return "(absent)"
    return hashlib.sha256(vrai.read_bytes()).hexdigest()


EMPREINTE_DEPART = _empreinte_vrai_journal()


def main():
    for test in (test_une_date_se_lit_ou_ne_se_lit_pas,
                 test_la_fenetre_par_defaut_est_de_trente_jours,
                 test_une_fenetre_qui_remonte_avant_le_calendrier_est_refusee,
                 test_la_commande_applique_vraiment_sa_fenetre,
                 test_deux_configurations_differentes_ne_sappellent_pas_pareil,
                 test_une_seule_configuration_sannonce_en_entier,
                 test_la_boussole_ne_pointe_plus_un_bogue_mort,
                 test_chaque_vue_compte_les_lignes_quelle_regarde,
                 test_chaque_vue_ecrit_la_fenetre_quelle_a_lue,
                 test_une_ligne_sans_date_est_gardee_et_annoncee,
                 test_la_fenetre_porte_aussi_sur_les_tentatives,
                 test_une_tentative_ne_pollue_pas_le_tableau_des_configurations,
                 test_les_motifs_de_contexte_restent_a_part,
                 test_une_fenetre_vide_le_dit_sans_planter,
                 test_un_journal_absent_ne_plante_pas,
                 test_le_vrai_journal_nest_jamais_touche):
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
