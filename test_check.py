#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_check.py

LE VERDICT D'ENSEMBLE DU GARDE-MACHINE, ET LA LISTE DES SUITES.

    .venv/Scripts/python.exe test_check.py

La chaîne `check.py` + `garde_machine.py` — l'outil qui dit si une suite
hors ligne a touché la machine d'Ewan. Trois choses se vérifient ici, et
les trois sont des ABSENCES que le projet a déjà lues comme des PREUVES :

1. `run_offline` imprimait « 17 suites, aucune n'a touché la souris, la
   molette, l'écran ni la fenêtre du jeu » en comptant `len(TEST_SUITES)`
   — c'est-à-dire les suites DÉCLARÉES, pas celles dont un verdict a été
   LU. Une suite tuée par l'échéance ou dont le fichier manque ne rend
   aucun verdict ; elle sortait de la boucle sans entrer dans aucune
   liste, et la phrase verte l'annonçait propre avec les autres.
   « Aucune » voulait donc parfois dire « je n'ai pas pu regarder ».

2. Le garde parlait par `print`, donc au `sys.stdout` DU MOMENT. Quatre
   suites du projet détournent le leur (`contextlib.redirect_stdout`) :
   un geste fait là-dedans voyait son cri ET SA PILE tomber dans leur
   tampon — la pile étant précisément ce qui NOMME le coupable — et une
   suite qui ne rendait jamais son `sys.stdout` emportait le verdict
   final avec elle.

3. Une suite `test_*.py` absente de `TEST_SUITES` est MUETTE : elle ne
   tourne jamais, et le jour où une régression la casse personne ne le
   voit. C'est arrivé TROIS fois (test_events, test_digits, test_riposte,
   constaté le 04/11/2026).

Hors ligne et sans sous-processus : `_run_suite` est bouchonné, les
suites « lancées » ici rendent la sortie qu'on leur dicte.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

import check
import garde_machine

ROOT = Path(__file__).resolve().parent

FAILURES = []


def check_(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  ÉCHEC {label} {detail}")
        FAILURES.append(label)


# ------------------------------------------------------------------ harnais
#
# Les lignes que le garde écrit vraiment dans le tube, telles que
# `_verdict_garde` les relit. On les fabrique à partir des constantes de
# `garde_machine` : si le préfixe change, le harnais suit.

LIGNE_PROPRE = f"{garde_machine.PREFIXE} {garde_machine.PROPRE}"
LIGNE_SALE = f"{garde_machine.PREFIXE} {garde_machine.SALE} 3 fois : pyautogui.click×3"
CRI = [
    f"{garde_machine.PREFIXE} PREMIER GESTE SUR LA MACHINE : pyautogui.click()",
    f"{garde_machine.PREFIXE}     navigate.py:412  _pick_champion()",
]

# Une suite verte ordinaire, vue du tube.
VERTE = ["  ok    un test", "  ok    un autre", "Tous les tests passent."]

# LA PHRASE DANGEREUSE, en toutes lettres. C'est elle qu'on poursuit : le
# test la cherche telle que l'utilisateur la lit, pas via une constante
# du module — sinon une reformulation passerait sans rien dire.
PHRASE_VERTE = "aucune n'a touché"


def _lancer(suites, sorties):
    """
    Fait tourner `run_offline` sur une liste de suites FICTIVE.

    `sorties` associe un nom de suite au quadruplet que `_run_suite`
    rendrait — (code de retour, lignes du tube, durée, tuée). Aucun
    sous-processus n'est lancé : le bouchon rend le quadruplet tel quel.
    """
    def _faux_run_suite(path, timeout=check.SUITE_TIMEOUT):
        return sorties[path.name]

    vrai_run, vraies_suites = check._run_suite, check.TEST_SUITES
    check._run_suite = _faux_run_suite
    check.TEST_SUITES = tuple(suites)
    tube = io.StringIO()
    resultats = check.Results()
    try:
        with contextlib.redirect_stdout(tube):
            check.run_offline(resultats)
    finally:
        check._run_suite = vrai_run
        check.TEST_SUITES = vraies_suites
    return tube.getvalue(), resultats


# ============================================================
# 1. UNE ABSENCE DE VERDICT N'EST PAS UNE PREUVE DE PROPRETÉ
# ============================================================

def test_une_suite_propre_reste_propre():
    """Le cas normal ne doit pas changer : tout vert, phrase verte."""
    print("\nUne suite surveillée et propre est annoncée propre")
    sortie, resultats = _lancer(
        ["test_digits.py"],
        {"test_digits.py": (0, VERTE + [LIGNE_PROPRE], 1.2, False)},
    )
    check_("la phrase verte est écrite", PHRASE_VERTE in sortie, sortie)
    check_("aucun échec", resultats.failures == 0, resultats.failures)
    check_("aucun avertissement", resultats.warnings == 0, resultats.warnings)
    check_("la suite est comptée surveillée",
           re.search(r"garde-machine : 1 suite", sortie) is not None, sortie)


def test_une_suite_tuee_nest_jamais_propre():
    """
    Une suite tuée par l'échéance n'a rendu AUCUN verdict : le garde est
    mort avec elle (son `atexit` ne tourne pas sur un `kill`). C'est le
    cas que `elif etat == "muet" and not stalled` excluait explicitement
    des muettes — et la phrase verte la comptait propre.
    """
    print("\nUne suite TUÉE n'est pas comptée propre")
    sortie, resultats = _lancer(
        ["test_digits.py"],
        {"test_digits.py": (1, ["  ok    un test"], 130.0, True)},
    )
    check_("la phrase verte n'est PAS écrite", PHRASE_VERTE not in sortie, sortie)
    check_("le verdict dit « sans verdict »", "sans verdict" in sortie, sortie)
    check_("la suite est nommée", "test_digits.py" in sortie, sortie)


def test_une_suite_absente_nest_jamais_propre():
    """
    Un fichier qui manque n'a été surveillé par personne. Il sortait de
    la boucle par un `continue` sec, donc il n'était ni propre, ni sale,
    ni muet — et le compte final, tiré de `len(TEST_SUITES)`, le rangeait
    avec les propres.
    """
    print("\nUne suite ABSENTE n'est pas comptée propre")
    sortie, resultats = _lancer(["test_fantome.py"], {})
    check_("la phrase verte n'est PAS écrite", PHRASE_VERTE not in sortie, sortie)
    check_("le verdict dit « sans verdict »", "sans verdict" in sortie, sortie)
    check_("le fichier absent est signalé", "absent" in sortie, sortie)


def test_une_suite_qui_sort_sans_verdict_nest_jamais_propre():
    """
    Code de retour 0, assertions vertes, et PAS UNE LIGNE du garde : le
    mouchard ne s'est pas posé, ou la suite est sortie par `os._exit`, ou
    le tube a été coupé. Le plus dangereux des trois états, parce que
    rien d'autre ne cloche — c'est le seul cas où « sans verdict » est le
    SEUL problème, et il doit quand même être bloquant.
    """
    print("\nUne suite qui sort VERTE sans verdict n'est pas propre")
    sortie, resultats = _lancer(
        ["test_digits.py"],
        {"test_digits.py": (0, VERTE, 1.0, False)},
    )
    check_("la phrase verte n'est PAS écrite", PHRASE_VERTE not in sortie, sortie)
    check_("le verdict dit « sans verdict »", "sans verdict" in sortie, sortie)
    check_("c'est bloquant", resultats.failures >= 1, resultats.failures)


def test_un_geste_crie_avant_la_mort_compte_comme_touche():
    """
    Le cri part au PREMIER geste, le verdict final seulement à la sortie.
    Une suite tuée en plein geste laisse donc le cri dans le tube sans le
    verdict : on sait qu'elle a touché la machine, il ne faut pas ranger
    ça dans « on ne sait pas ».

    C'est exactement la forme de la fuite du 06/11/2026 —
    `_reward_proves_victory` photographiait l'écran 40 fois et faisait
    passer la suite de 5 s à 15 s : une fuite qui ralentit est une fuite
    qui peut déclencher l'échéance.
    """
    print("\nUn geste crié avant la mort de la suite n'est pas « on ne sait pas »")
    etat, detail, pile = check._verdict_garde(["  ok    un test"] + CRI)
    check_("état « touché »", etat == "touché", etat)
    check_("le geste est nommé", "pyautogui.click" in " ".join(pile), pile)

    sortie, resultats = _lancer(
        ["test_digits.py"],
        {"test_digits.py": (1, ["  ok    un test"] + CRI, 130.0, True)},
    )
    check_("le verdict d'ensemble crie", "ONT TOUCHÉ" in sortie, sortie)
    check_("la phrase verte n'est PAS écrite", PHRASE_VERTE not in sortie, sortie)


def test_le_verdict_densemble_distingue_les_trois_etats():
    """
    Trois suites, trois états : le compte final doit les séparer, et le
    nombre annoncé propre doit venir des verdicts LUS, pas de la longueur
    de `TEST_SUITES`.
    """
    print("\nLe verdict d'ensemble sépare propre / touchée / sans verdict")
    sortie, resultats = _lancer(
        ["test_digits.py", "test_riposte.py", "test_marqueur.py"],
        {
            "test_digits.py": (0, VERTE + [LIGNE_PROPRE], 1.0, False),
            "test_riposte.py": (0, VERTE + [LIGNE_SALE], 1.0, False),
            "test_marqueur.py": (1, VERTE, 1.0, False),
        },
    )
    # Le compte final est la ligne au tiret long ; les `######` du bloc
    # des sales et le `[ÉCHEC]` des sans-verdict sont des lignes à part.
    ligne = [l for l in sortie.splitlines() if l.lstrip().startswith("──")]
    check_("une ligne de compte final", len(ligne) == 1, ligne)
    compte = ligne[0] if ligne else ""
    check_("1 propre", re.search(r"\b1 .{0,30}propre", compte) is not None, compte)
    check_("1 touchée", re.search(r"\b1 .{0,20}TOUCH", compte) is not None, compte)
    check_("1 sans verdict", "1 sans verdict" in compte, compte)
    check_("sur 3", "3" in compte, compte)
    check_("la phrase verte n'est PAS écrite", PHRASE_VERTE not in sortie, sortie)


def test_le_compte_propre_vient_des_verdicts_lus():
    """
    Le nombre de la phrase verte ne doit PAS pouvoir être
    `len(TEST_SUITES)` : quatre suites déclarées, quatre verdicts
    « propre » lus, le compte est quatre — mais il vient des verdicts.
    Le garde-fou est le test précédent ; celui-ci vérifie qu'on n'a pas
    simplement supprimé le chiffre.
    """
    print("\nLe chiffre annoncé est celui des verdicts lus")
    noms = ["test_digits.py", "test_riposte.py", "test_marqueur.py", "test_bilan.py"]
    sortie, resultats = _lancer(
        noms, {nom: (0, VERTE + [LIGNE_PROPRE], 1.0, False) for nom in noms})
    check_("4 suites annoncées",
           re.search(r"garde-machine : 4 suite", sortie) is not None, sortie)
    check_("la phrase verte est écrite", PHRASE_VERTE in sortie, sortie)


# ============================================================
# 2. LE GARDE PARLE AU TUBE, PAS À LA SUITE
# ============================================================
#
# Le cri et le verdict partent par `print`, donc vers le `sys.stdout` du
# MOMENT. Or quatre suites du projet — test_actions, test_challenges,
# test_journal, test_spells — détournent `sys.stdout` dans un
# `contextlib.redirect_stdout` pour relire ce qu'une fonction imprime.
# Un geste fait là-dedans voyait sa PILE tomber dans leur tampon : or
# c'est la pile qui NOMME le coupable, et c'est toute la valeur du cri.
#
# Ces tests manipulent les privés du garde (`_SORTIE`, `_compteur`,
# `_cries`) parce qu'on teste le mouchard lui-même. Ils n'appellent
# JAMAIS pyautogui : `_noter` est la fonction sous test, elle ne touche
# rien.


def _sous_garde(tube, corps):
    """
    Fait tourner `corps()` avec le garde réglé pour écrire dans `tube`,
    puis rend au module son état d'avant — compteur compris, sinon la
    suite elle-même finirait sur un verdict « TOUCHÉ ».
    """
    avant = (getattr(garde_machine, "_SORTIE", None),
             garde_machine._compteur.copy(),
             set(garde_machine._cries),
             garde_machine._rapport_rendu)
    setattr(garde_machine, "_SORTIE", tube)
    garde_machine._compteur.clear()
    garde_machine._cries.clear()
    garde_machine._rapport_rendu = False
    try:
        return corps()
    finally:
        setattr(garde_machine, "_SORTIE", avant[0])
        garde_machine._compteur.clear()
        garde_machine._compteur.update(avant[1])
        garde_machine._cries.clear()
        garde_machine._cries.update(avant[2])
        garde_machine._rapport_rendu = avant[3]


def test_le_cri_du_garde_ne_tombe_pas_dans_un_tampon_de_la_suite():
    print("\nLe cri du garde va au tube, pas au tampon de la suite")
    tube, tampon = io.StringIO(), io.StringIO()

    def corps():
        with contextlib.redirect_stdout(tampon):
            garde_machine._noter("pyautogui.click")     # aucun geste réel
            return garde_machine.resume()

    resume = _sous_garde(tube, corps)
    check_("le tampon de la suite n'a rien avalé",
           tampon.getvalue() == "", tampon.getvalue())
    check_("le cri est dans le tube",
           "PREMIER GESTE" in tube.getvalue(), tube.getvalue())
    check_("la pile qui NOMME le coupable aussi",
           "test_check.py" in tube.getvalue(), tube.getvalue())
    check_("et le geste reste compté", "pyautogui.click" in resume, resume)


def test_le_verdict_final_survit_a_un_stdout_detourne():
    """
    Le verdict est posé en `atexit` : il s'imprime APRÈS la suite, donc
    sur le `sys.stdout` que la suite a laissé derrière elle. Une suite
    qui remplace le sien sans le rendre emportait le verdict avec elle —
    mesuré : sortie code 0, pas une ligne du garde, un geste compté et
    jamais dit.
    """
    print("\nLe verdict final survit à un sys.stdout laissé détourné")
    tube, perdu = io.StringIO(), io.StringIO()

    def corps():
        garde_machine._noter("pyautogui.screenshot")
        vrai = sys.stdout
        sys.stdout = perdu                  # la suite ne le rend jamais
        try:
            garde_machine.rapporter()
        finally:
            sys.stdout = vrai

    _sous_garde(tube, corps)
    check_("rien n'est tombé dans le flux perdu",
           perdu.getvalue() == "", perdu.getvalue())
    check_("le verdict est dans le tube",
           garde_machine.SALE in tube.getvalue(), tube.getvalue())
    check_("et il nomme le geste",
           "pyautogui.screenshot" in tube.getvalue(), tube.getvalue())


def test_un_tube_ferme_ne_fait_pas_tomber_la_suite():
    """
    Le garde n'a JAMAIS le droit de casser la suite qu'il surveille : il
    compte, il ne bloque pas. Si le flux qu'il a mis de côté est fermé,
    il se rabat sur celui du moment plutôt que de lever.
    """
    print("\nUn tube fermé ne fait pas tomber la suite surveillée")
    ferme, tampon = io.StringIO(), io.StringIO()
    ferme.close()

    def corps():
        with contextlib.redirect_stdout(tampon):
            garde_machine._noter("pyautogui.scroll")
        return True

    ok = True
    try:
        _sous_garde(ferme, corps)
    except Exception as exc:                            # noqa: BLE001
        ok = False
        print(f"        ({type(exc).__name__}: {exc})")
    check_("aucune exception", ok)
    check_("le repli a parlé quand même",
           "pyautogui.scroll" in tampon.getvalue(), tampon.getvalue())


# ============================================================
# 3. UNE SUITE NON INSCRITE EST MUETTE
# ============================================================

def suites_du_dossier():
    """
    Les fichiers `test_*.py` qui sont de vraies SUITES.

    Le critère est mesuré, pas listé à la main : une suite DÉFINIT des
    fonctions `test_...`. `test_clock.py` n'en définit aucune — c'est
    l'horloge virtuelle, un module d'aide qui porte ce nom parce qu'il
    sert aux tests, pas parce qu'il en contient. Au 09/11/2026, sur les
    18 fichiers `test_*.py` du dossier, c'est le seul dans ce cas (les
    17 autres ont entre 4 et 107 fonctions de test).
    """
    vraies = []
    for chemin in sorted(ROOT.glob("test_*.py")):
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^def test_", texte, re.M):
            vraies.append(chemin.name)
    return vraies


def test_toutes_les_suites_du_dossier_sont_inscrites():
    """
    Une suite absente de `TEST_SUITES` ne tourne JAMAIS. Trois l'étaient
    le 04/11/2026 — test_events, test_digits, test_riposte — écrites,
    vertes, et muettes le jour où une régression les aurait cassées.
    """
    print("\nToutes les suites du dossier sont inscrites dans TEST_SUITES")
    presentes = suites_du_dossier()
    inscrites = set(check.TEST_SUITES)
    manquantes = [nom for nom in presentes if nom not in inscrites]
    check_(f"{len(presentes)} suite(s) dans le dossier, aucune hors liste",
           not manquantes, manquantes)

    # Et le symétrique : une suite inscrite qui n'existe plus ferait un
    # [ÉCHEC] « fichier absent » à chaque `check.py`.
    fantomes = [nom for nom in inscrites if not (ROOT / nom).exists()]
    check_("aucune suite inscrite n'a disparu du dossier", not fantomes, fantomes)


def test_cette_suite_est_inscrite():
    """
    L'ironie à éviter : la suite qui vérifie que tout est inscrit, non
    inscrite.
    """
    print("\nCette suite-ci est inscrite")
    check_("test_check.py est dans TEST_SUITES",
           "test_check.py" in check.TEST_SUITES, check.TEST_SUITES)


def main():
    for test in (
        test_une_suite_propre_reste_propre,
        test_une_suite_tuee_nest_jamais_propre,
        test_une_suite_absente_nest_jamais_propre,
        test_une_suite_qui_sort_sans_verdict_nest_jamais_propre,
        test_un_geste_crie_avant_la_mort_compte_comme_touche,
        test_le_verdict_densemble_distingue_les_trois_etats,
        test_le_compte_propre_vient_des_verdicts_lus,
        test_le_cri_du_garde_ne_tombe_pas_dans_un_tampon_de_la_suite,
        test_le_verdict_final_survit_a_un_stdout_detourne,
        test_un_tube_ferme_ne_fait_pas_tomber_la_suite,
        test_toutes_les_suites_du_dossier_sont_inscrites,
        test_cette_suite_est_inscrite,
    ):
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
