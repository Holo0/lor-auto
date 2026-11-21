# Lecture des mots-clés accordés — plan d'implémentation

> **Pour un agent exécutant :** SOUS-COMPÉTENCE REQUISE — utiliser
> `superpowers:subagent-driven-development` (recommandé) ou
> `superpowers:executing-plans` pour exécuter ce plan tâche par tâche.
> Les étapes sont des cases à cocher (`- [ ]`).

**But :** identifier à l'écran les mots-clés d'une unité du plateau — y
compris ceux ACCORDÉS en jeu — et les ajouter à ceux de `card_sets`, sans
jamais en retirer.

**Architecture :** `mots_cles_ecran.py` sait déjà DÉTECTER les icônes
(bande relative au centre de la carte, masque de couleur, composantes
connexes). On lui ajoute une troisième famille de couleur, puis une
IDENTIFICATION par gabarits (méthode de `digits.py`), puis on branche le
résultat sur `BoardCard` — patron de `stunned`, qui est déjà un attribut
lu à l'écran et absent de l'API.

**Pile technique :** Python 3.12 dans `.venv`, OpenCV, NumPy. Aucune
dépendance nouvelle.

**Spec :** `docs/superpowers/specs/2026-11-20-mots-cles-ecran-design.md`

## Contraintes globales

- **Un seul interpréteur : `.\.venv\Scripts\python.exe`.** Le dossier
  `venv` (3.11) est un vestige — ne jamais l'utiliser.
- **Le projet est en français** : code, commentaires, messages, noms de
  tests. Prose française obligatoire.
- **`python check.py --offline` doit être vert avant ET après chaque
  tâche.** C'est la commande de référence du projet.
- **Une suite ne doit JAMAIS toucher la machine** : ni souris, ni
  molette, ni capture d'écran, ni fenêtre. `garde_machine.py` le vérifie
  et `check.py` en fait un échec. Toutes les lectures de ce plan se font
  sur des PNG du dépôt, jamais sur l'écran vivant.
- **Jamais une valeur approchée.** Un glyphe sous le seuil n'est pas
  identifié ; il ne devient pas « probablement Challenger ». Règle de
  `lire_palier` et de `_cached_ocr`.
- **L'écran COMPLÈTE, il ne retire jamais** (décision d'Ewan, 20/11).
- `assets/` est ignoré par git ; `chiffres/` et `captures_reference/` ne
  le sont PAS. Les gabarits vont dans `mots_cles/`, à versionner comme
  `chiffres/` — vérifier `.gitignore` avant le commit de la tâche 2.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `mots_cles_ecran.py` | MODIFIÉ — famille magenta, découpe, identification |
| `mots_cles/<nom>.png` | CRÉÉ — un gabarit par mot-clé, alpha = forme |
| `test_mots_cles_ecran.py` | MODIFIÉ — témoins sur la scène étiquetée du 20/11 |
| `game_state.py` | MODIFIÉ — champ `keywords_lus`, union dans `BoardCard.has`, appel dans `snapshot()` |
| `test_game_state.py` | MODIFIÉ — l'union et son miroir |
| `CLAUDE.md` | MODIFIÉ — ce qui est mesuré, et ce qui ne l'est pas |

Capture témoin déjà présente, appariée à sa trame d'API :
`captures_reference/mots_cles/scene_20261120_201157.png` et son `.json`.

---

### Tâche 1 : la troisième famille de couleur

Le masque ne connaît qu'ORANGE (teinte 8-28) et BLEU (88-112). Le sablier
d'Éphémère est à **144** : invisible aujourd'hui. Mesuré sur les quatre
icônes de `06SI009` — 144 magenta, 95 cyan, 16 orange, 19 orange.

**Fichiers :**
- Modifier : `mots_cles_ecran.py` (constantes de couleur, `_masque_icones`)
- Tester : `test_mots_cles_ecran.py`

**Interfaces :**
- Consomme : rien.
- Produit : `MAGENTA = ((132, 90, 110), (156, 255, 255))` et un
  `_masque_icones` qui en tient compte. `icones(image, centre)` garde sa
  signature et son retour `list[tuple[int, int, int, int, int]]`.

- [ ] **Étape 1 : écrire le test qui échoue**

Ajouter dans `test_mots_cles_ecran.py`, et inscrire la fonction dans la
liste de `main()` :

```python
CAPTURE_20 = (Path(__file__).parent / "captures_reference" / "mots_cles"
              / "scene_20261120_201157.png")

# Pâle orchestre (06SI009), rect écran x 582-709 / y 820-980.
# L'ordre est un FAIT DE JEU donné par Ewan le 20/11/2026 : « chacun des
# Pâle orchestre a dans l'ordre, de gauche à droite, le mot clé éphémère,
# sanctification, challenger et enfin surpuissance ».
CENTRE_ORCHESTRE = (645, 900)


def test_le_sablier_magenta_entre_dans_le_masque():
    """
    QUATRE ICÔNES, PAS TROIS. Le masque du 14/11 ne connaissait que
    l'orange et le bleu ; le sablier d'Éphémère est à la teinte 144, donc
    entre les deux. Il manquait, et personne ne pouvait s'en apercevoir —
    le module ne rendait qu'un booléen « il y en a ».
    """
    print("\nLa famille magenta")
    img = cv2.imread(str(CAPTURE_20))
    if img is None:
        check("capture du 20/11 présente", False, CAPTURE_20)
        return
    lues = mce.icones(img, CENTRE_ORCHESTRE)
    check("quatre icônes sous le Pâle orchestre", len(lues) == 4,
          f"lu {len(lues)} : {lues}")
    if len(lues) == 4:
        xs = [b[0] for b in lues]
        ecarts = [xs[i + 1] - xs[i] for i in range(3)]
        check("pas régulier de ~25 px",
              all(20 <= e <= 30 for e in ecarts), ecarts)
```

- [ ] **Étape 2 : lancer le test, vérifier qu'il échoue**

Lancer : `.\.venv\Scripts\python.exe test_mots_cles_ecran.py`
Attendu : ÉCHEC — « quatre icônes sous le Pâle orchestre », lu 3.

- [ ] **Étape 3 : ajouter la famille**

Dans `mots_cles_ecran.py`, sous les constantes existantes :

```python
# TROIS FAMILLES, PAS DEUX (20/11/2026). Mesuré sur les quatre icônes du
# Pâle orchestre (06SI009), étiquetées par Ewan : Éphémère sort à la
# teinte 144, Sanctification à 95, Challenger à 16, Surpuissance à 19.
# Les deux premières familles dataient du 14/11 et laissaient le sablier
# d'Éphémère dans l'angle mort — une icône VUE et jamais comptée.
MAGENTA = ((132, 90, 110), (156, 255, 255))
```

et remplacer `_masque_icones` par :

```python
def _masque_icones(image) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masque = None
    for basse, haute in (ORANGE, BLEU, MAGENTA):
        bande = cv2.inRange(hsv, np.array(basse), np.array(haute))
        masque = bande if masque is None else cv2.bitwise_or(masque, bande)
    return masque
```

- [ ] **Étape 4 : lancer le test, vérifier qu'il passe**

Lancer : `.\.venv\Scripts\python.exe test_mots_cles_ecran.py`
Attendu : tous les tests passent, y compris les quatre anciens — les
sept unités du 14/11 ne doivent PAS changer de verdict.

- [ ] **Étape 5 : contre-épreuve**

Retirer temporairement `MAGENTA` de la boucle, relancer : le nouveau test
doit redevenir rouge (3 icônes) et **les anciens rester verts**. Remettre
la ligne. Mentionner le résultat dans le message de commit.

- [ ] **Étape 6 : `check.py`**

Lancer : `.\.venv\Scripts\python.exe check.py --offline`
Attendu : toutes les suites vertes, « machine intacte ».

- [ ] **Étape 7 : commit**

```bash
git add mots_cles_ecran.py test_mots_cles_ecran.py
git commit -m "mots-cles: une troisieme famille de couleur, le magenta d Ephemere"
```

---

### Tâche 2 : la bibliothèque de gabarits et l'identification

**Fichiers :**
- Créer : `mots_cles/ephemeral.png`, `mots_cles/hallowed.png`,
  `mots_cles/challenger.png`, `mots_cles/overwhelm.png`
- Modifier : `mots_cles_ecran.py` (découpe, chargement, identification)
- Tester : `test_mots_cles_ecran.py`

**Interfaces :**
- Consomme : `icones(image, centre)` de la tâche 1.
- Produit :
  - `decouper(image, centre, index) -> np.ndarray | None` — masque 0/255
    du glyphe d'indice `index`, dans l'ordre de lecture.
  - `charger_gabarits() -> dict[str, list[np.ndarray]]` — mot-clé → ses
    VARIANTES (masques 0/1), mises en cache au premier appel.
  - `identifier(image, centre) -> tuple[str, ...]` — les mots-clés
    SÛREMENT identifiés, dans l'ordre de lecture ; un glyphe non
    identifié est simplement ABSENT du tuple.
  - `SCORE_SUR = digits.MIN_SCORE` (0.60) et
    `MARGE_SURE = digits.CONFIDENT_MARGIN` (0.10) — **mesurés pour ce
    problème**, voir l'étape 5.
  - `NOMS: dict[str, str]` — radical de fichier → mot-clé tel que
    `card_sets` l'écrit.

- [ ] **Étape 1 : écrire la découpe et la récolte**

Ajouter `from pathlib import Path` en tête de `mots_cles_ecran.py`, puis :

```python
def decouper(image, centre: tuple, index: int):
    """Le masque 0/255 du glyphe d'indice `index`, ou None."""
    boites = icones(image, centre)
    if not 0 <= index < len(boites):
        return None
    cx, cy = int(centre[0]), int(centre[1])
    x0, y0 = cx - BARRE_DEMI_LARGEUR, cy + BARRE_DY_HAUT
    x, y, w, h, _ = boites[index]
    bande = image[y0:cy + BARRE_DY_BAS, x0:cx + BARRE_DEMI_LARGEUR]
    return _masque_icones(bande)[y:y + h, x:x + w]


def cut_icone(capture: str, centre: tuple, index: int, nom: str) -> str:
    """
    Récolte un gabarit depuis une capture ÉTIQUETÉE.

    ON NE RÉCOLTE QUE CE QU'UN HUMAIN A NOMMÉ. Deviner l'identité d'une
    icône serait inventer — c'est ce que ce module refusait de faire
    depuis le 14/11, et il avait raison. L'ordre vient d'Ewan, pas de
    l'image.

    Le masque écrit est celui que `identifier` relira : on découpe PAR LE
    CHEMIN DE LECTURE, jamais par un seuil choisi à part. Le piège est
    documenté (`cut_defi`, 08/11) — une police découpée autrement ne se
    reconnaît pas elle-même (IoU 0.83, marge sous le plancher).
    """
    image = cv2.imread(capture)
    if image is None:
        raise SystemExit(f"capture introuvable : {capture}")
    masque = decouper(image, centre, index)
    if masque is None or masque.size == 0:
        raise SystemExit(f"aucune icône d'indice {index} sous {centre}")
    chemin = Path(__file__).parent / "mots_cles" / f"{nom}.png"
    chemin.parent.mkdir(exist_ok=True)
    rgba = np.zeros((*masque.shape, 4), np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = masque
    cv2.imwrite(str(chemin), rgba)
    return str(chemin)
```

- [ ] **Étape 2 : produire les quatre PNG**

**DEUX VARIANTES PAR MOT-CLÉ, récoltées sur DEUX vignettes différentes.**
C'est le patron que `digits.load_variants` applique déjà aux chiffres
(« le score d'un chiffre est celui de sa MEILLEURE variante ») et que le
projet a employé le 14/11 avec `3_defi2.png`. Mesuré ici : avec une seule
variante, Sanctification plafonne à **0.545-0.597** ; avec deux, le pire
score remonte à **0.714** et la pire marge à **0.283**.

```bash
.\.venv\Scripts\python.exe -c "import mots_cles_ecran as m; p='captures_reference/mots_cles/scene_20261120_201157.png'; noms=('ephemeral','hallowed','challenger','overwhelm'); [print(m.cut_icone(p,c,i,n+s)) for c,s in (((645,900),''),((802,900),'2')) for i,n in enumerate(noms)]"
```

Attendu : huit chemins imprimés, huit fichiers dans `mots_cles/` —
`ephemeral.png` et `ephemeral2.png`, etc.

- [ ] **Étape 3 : écrire les tests qui échouent**

**ON NE TESTE PAS SUR LA VIGNETTE DONT ON A DÉCOUPÉ LES GABARITS.** Ce
serait un IoU proche de 1 par construction — le gabarit qui ne reconnaît
que lui-même, l'anti-patron que le projet a déjà payé (`cut_defi`, 08/11 :
IoU 0.83, marge sous le plancher). La capture porte CINQ Pâle orchestre
identiques : on récolte sur DEUX d'entre elles et on vérifie sur les
TROIS AUTRES. Centres déduits de la trame d'API appariée (x 582/739/896/1052/1209,
largeur 127, `haut_écran = 1080 − TopLeftY`).

```python
# Les vignettes qui n'ont PAS servi de source. Les gabarits sont récoltés
# sur (645, 900) et (802, 900) ; tester sur l'une d'elles serait comparer
# un gabarit à son propre découpage — 1.0 par construction, qui ne
# prouve rien.
AUTRES_ORCHESTRES = ((959, 900), (1115, 900), (1272, 900))


def test_les_quatre_icones_sont_identifiees():
    """
    L'ORDRE EST UN FAIT DE JEU, PAS UNE DÉDUCTION (Ewan, 20/11/2026).

    Et c'est le test qui justifie tout le module : 06SI009 n'imprime que
    Hallowed et Ephemeral. Challenger et Overwhelm lui ont été ACCORDÉS.

    Vérifié sur les trois exemplaires qui n'ont PAS servi de source :
    un gabarit comparé à son propre découpage rendrait 1.0 et ne
    prouverait rien.
    """
    print("\nIdentification des quatre icônes")
    img = cv2.imread(str(CAPTURE_20))
    if img is None:
        check("capture du 20/11 présente", False, CAPTURE_20)
        return
    attendu = ("Ephemeral", "Hallowed", "Challenger", "Overwhelm")
    for centre in AUTRES_ORCHESTRES:
        lu = mce.identifier(img, centre)
        check(f"Pâle orchestre en {centre} : les quatre, dans l'ordre",
              lu == attendu, lu)


def test_une_unite_sans_icone_nidentifie_rien():
    """Le miroir, sans lequel le test précédent ne prouverait rien."""
    print("\nUne unité vierge n'identifie rien")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    check("Arachnoid Sentry : aucun mot-clé identifié",
          mce.identifier(img, (1194, 900)) == ())


def test_un_glyphe_etranger_nest_identifie_comme_rien():
    """
    LE CAS QUI PROTÈGE DES SEIZE MOTS-CLÉS QU'ON N'A PAS.

    La marge sépare les quatre mots-clés CONNUS entre eux ; seul le score
    absolu peut refuser un cinquième dont on n'a aucun gabarit. Swain
    porte Fearsome et quatre autres icônes, dont AUCUNE n'est des nôtres.
    Mesuré : ses glyphes notent au mieux 0.409 contre nos gabarits, avec
    des marges de 0.003 à 0.073 — très en dessous de 0.60 / 0.10.

    Si ce test rougit, c'est qu'un seuil a été desserré et que le module
    s'est mis à inventer des mots-clés. C'est le pire défaut possible
    ici : un Challenger imaginaire ferait glisser un bloqueur sur un
    geste que le jeu refuse.
    """
    print("\nUn mot-clé qu'on ne connaît pas n'est pas deviné")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    lu = mce.identifier(img, (724, 900))      # Swain, 5 icônes étrangères
    check("Swain : aucune de ses icônes n'est prise pour une des nôtres",
          lu == (), lu)


def test_un_gabarit_franchit_les_captures():
    """
    VALIDATION CROISÉE, à six jours d'écart. Enraged Firespitter imprime
    `Challenger` dans `card_sets`, et sa capture date du 14/11 — les
    gabarits, eux, sont découpés sur celle du 20/11. Le reconnaître prouve
    que les gabarits ne collent pas à leur seule image d'origine.

    Mesuré : 0.710, marge 0.317.
    """
    print("\nUn gabarit du 20/11 reconnaît une icône du 14/11")
    img = cv2.imread(str(CAPTURE))
    if img is None:
        check("capture du 14/11 présente", False, CAPTURE)
        return
    check("Firespitter : son Challenger imprimé est reconnu",
          "Challenger" in mce.identifier(img, (880, 900)),
          mce.identifier(img, (880, 900)))
```

Inscrire les **quatre** dans `main()`.

- [ ] **Étape 4 : lancer, vérifier l'échec**

Lancer : `.\.venv\Scripts\python.exe test_mots_cles_ecran.py`
Attendu : ÉCHEC — `AttributeError: module has no attribute 'identifier'`.

- [ ] **Étape 5 : écrire l'identification**

**ON RÉUTILISE `digits.py`, ON NE LE RÉÉCRIT PAS.** Un IoU « resize 32×32 »
n'est pas ce que fait `digits` : il lui manque les décalages ±3 px,
l'ÉGALISATION D'ÉPAISSEUR du trait, et surtout `digits._normalized`
CONSERVE LE RAPPORT D'ASPECT — or les boîtes vont de 16×23 à 27×24, et
les écraser en carré détruit l'information. Écart mesuré sur Challenger :
**0.807** avec l'IoU simplifié contre **0.921** avec `digits`.

Attention : `digits._normalized` fait `tight * 255`, donc il attend un
masque **0/1**. Lui passer du 0/255 déborde en uint8 et rend des scores
nuls — mesuré.

```python
import digits

# LES SEUILS SONT MESURÉS POUR CE PROBLÈME, pas hérités (20/11/2026).
# `digits.CONFIDENT_SCORE` (0.72) a été calibré pour les CHIFFRES : dix
# classes de formes voisines. Ici les pictogrammes sont très distincts et
# c'est la MARGE qui discrimine. Mesuré sur les 5 Pâle orchestre du 20/11
# et les glyphes ÉTRANGERS de la scène du 14/11 :
#
#     vrais positifs   score 0.710 à 0.988 | marge 0.119 à 0.630
#     glyphes étrangers score <= 0.429     | marge <= 0.073
#
# Le score reste indispensable : seul lui peut refuser un mot-clé dont on
# n'a AUCUN gabarit. 0.60 laisse 0.11 sous le pire vrai positif et 0.17
# au-dessus du meilleur étranger. Les DEUX planchers doivent être franchis.
SCORE_SUR = digits.MIN_SCORE              # 0.60
MARGE_SURE = digits.CONFIDENT_MARGIN      # 0.10

_GABARITS: dict = {}

# Radical de fichier -> mot-clé tel que `card_sets` l'écrit. `BoardCard.has`
# normalise la casse et la ponctuation, mais on écrit la forme juste.
NOMS = {
    "ephemeral": "Ephemeral",
    "hallowed": "Hallowed",
    "challenger": "Challenger",
    "overwhelm": "Overwhelm",
}


def _famille(radical: str) -> str:
    """« hallowed2 » appartient à la famille « hallowed ». Même rôle que
    `digits._family` : plusieurs variantes d'un même mot-clé."""
    return radical.rstrip("0123456789") or radical


def charger_gabarits() -> dict:
    """
    mot-clé -> ses VARIANTES, masques 0/1. L'ALPHA porte la forme, comme
    `chiffres/` — un glyphe opaque ne vaudrait rien.

    Le score d'un mot-clé est celui de sa MEILLEURE variante ; la marge se
    mesure entre deux mots-clés DIFFÉRENTS, jamais entre deux variantes du
    même. C'est mot pour mot la règle de `digits.match_glyph`.
    """
    if _GABARITS:
        return _GABARITS
    dossier = Path(__file__).parent / "mots_cles"
    for png in sorted(dossier.glob("*.png")):
        brut = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
        if brut is None or brut.ndim < 3 or brut.shape[2] < 4:
            continue
        famille = _famille(png.stem)
        nom = NOMS.get(famille, famille)
        _GABARITS.setdefault(nom, []).append((brut[:, :, 3] >= 128).astype(np.uint8))
    return _GABARITS


def _score(glyphe, gabarit) -> float:
    """Le chemin de `digits.match_glyph`, appliqué à nos pictogrammes."""
    forme = digits._normalized((glyphe > 0).astype(np.uint8))
    cible = digits._normalized((gabarit > 0).astype(np.uint8))
    return digits._iou(digits._equalize_stroke(forme, float(cible.mean())), cible)


def identifier(image, centre: tuple) -> tuple:
    """
    Les mots-clés SÛREMENT lus sous cette unité, dans l'ordre de lecture.

    Un glyphe sous les paliers n'est PAS identifié : il est absent du
    tuple. Il reste compté par `porte_des_mots_cles`, qui ne prétend
    qu'à la présence. Ne jamais rendre une valeur approchée.
    """
    gabarits = charger_gabarits()
    if not gabarits:
        return ()
    trouves = []
    for index in range(len(icones(image, centre))):
        glyphe = decouper(image, centre, index)
        if glyphe is None or glyphe.size == 0:
            continue
        notes = sorted(((max(_score(glyphe, v) for v in variantes), nom)
                        for nom, variantes in gabarits.items()), reverse=True)
        meilleur = notes[0]
        second = notes[1] if len(notes) > 1 else (0.0, "")
        if meilleur[0] >= SCORE_SUR and meilleur[0] - second[0] >= MARGE_SURE:
            trouves.append(meilleur[1])
    return tuple(trouves)
```

- [ ] **Étape 6 : lancer, vérifier que ça passe**

Lancer : `.\.venv\Scripts\python.exe test_mots_cles_ecran.py`
Attendu : tous verts, anciens compris.

- [ ] **Étape 7 : mesurer les marges et les écrire**

```bash
.\.venv\Scripts\python.exe -c "import cv2,mots_cles_ecran as m; img=cv2.imread('captures_reference/mots_cles/scene_20261120_201157.png'); g=m.charger_gabarits(); [print(c,i,sorted(((round(max(m._score(m.decouper(img,c,i),v) for v in vs),3),k) for k,vs in g.items()),reverse=True)[:2]) for c in ((959,900),(1115,900),(1272,900)) for i in range(4)]"
```

Reporter scores et marges dans la docstring du module, en nommant les
vignettes mesurées. Repères attendus d'après la mesure du contrôleur :
pire score **0.714**, pire marge **0.283** sur les vignettes qui n'ont pas
servi de source.

Si une marge tombe sous `MARGE_SURE`, **ne pas baisser le seuil** :
nommer le couple qui se dispute et laisser le glyphe non identifié. C'est
la leçon du « etoile 3 » contre le 8 (14/11) — enrichir une police
resserre ses marges.

- [ ] **Étape 8 : vérifier que `mots_cles/` est versionné**

```bash
git check-ignore -v mots_cles/ephemeral.png
```

Attendu : AUCUNE sortie (donc non ignoré). Si une règle l'attrape,
corriger `.gitignore` — les gabarits sont des données du projet, comme
`chiffres/`.

- [ ] **Étape 9 : `check.py` puis commit**

```bash
.\.venv\Scripts\python.exe check.py --offline
git add mots_cles_ecran.py test_mots_cles_ecran.py mots_cles/
git commit -m "mots-cles: identifier les glyphes par gabarit, quatre recoltes sur scene etiquetee"
```

---

### Tâche 3 : le branchement — l'écran complète la carte

**Fichiers :**
- Modifier : `game_state.py` — champ près de `stunned` (vers la ligne
  413), `BoardCard.has` (vers la ligne 508), `GameStateReader.snapshot`
  après `screen = lor_api.capture_screen_bgr()` (vers la ligne 2018)
- Tester : `test_game_state.py`

**Interfaces :**
- Consomme : `mots_cles_ecran.identifier(image, centre) -> tuple[str, ...]`.
- Produit :
  - `BoardCard.keywords_lus: tuple = ()`
  - `BoardCard.has(keyword)` teste l'union de `keywords`, `keyword_refs`
    et `keywords_lus`.
  - `game_state.lire_les_mots_cles(screen, zones) -> int` — enrichit les
    unités des zones de plateau, rend le nombre de cartes enrichies.
  - `game_state.ZONES_DE_PLATEAU: tuple[str, ...]`

- [ ] **Étape 1 : écrire les tests qui échouent**

La suite ne construit pas de `BoardCard` à la main : elle passe par
`rect_at_ratio` (ligne 111) + `install_fakes` + `reader().snapshot()`.
On suit ce chemin, qui exerce en plus la construction réelle.

**Au passage, la conversion de l'axe Y est déjà verrouillée par cette
suite** : `test_card_model` affirme
`card.center == (863, 1080 - board["TopLeftY"] + 79)` avec `height=159`,
donc `haut_écran = hauteur − TopLeftY`. C'est exactement ce que la
capture appariée du 20/11 a mesuré. Ne rien y changer.

```python
def test_un_mot_cle_lu_a_lecran_complete_la_carte_imprimee():
    """
    L'ÉCRAN COMPLÈTE, IL NE RETIRE JAMAIS (décision d'Ewan, 20/11/2026).

    Pâle orchestre (06SI009) imprime DEUX mots-clés — Hallowed et
    Ephemeral — et l'écran en montre QUATRE : Challenger et Overwhelm lui
    ont été accordés en jeu. Ce sont deux mots-clés MODÉLISÉS : le
    premier décide si un blocage est légal, le second change l'excédent
    d'une attaque. Sans cette lecture, le bot jouait cinq unités comme si
    elles n'avaient ni l'un ni l'autre.
    """
    print("\nL'écran complète la carte imprimée")
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    install_fakes(nexus_rects() + [board])
    carte = reader().snapshot().board[0]

    imprime = tuple(carte.keywords)
    carte.keywords_lus = ("Challenger", "Overwhelm")

    check("l'imprimé est conservé", all(carte.has(k) for k in imprime), imprime)
    check("le mot-clé ACCORDÉ est vu", carte.has("Challenger"))
    check("et le second aussi", carte.has("Overwhelm"))
    check("ce qui n'est nulle part reste faux", carte.has("Formidable") is False)


def test_un_mot_cle_lu_ne_retire_jamais_un_imprime():
    """
    LE PRIX ASSUMÉ DU 20/11 : on ne voit pas les mots-clés RETIRÉS
    (Silence). Une lecture vide ne doit donc RIEN effacer — c'est la
    règle de `stunned`, « faux par défaut veut dire on n'a pas regardé ».
    """
    print("\nUne lecture vide n'efface rien")
    board = rect_at_ratio(0.15, code="UNIT_B", card_id=2)
    install_fakes(nexus_rects() + [board])
    carte = reader().snapshot().board[0]

    check("vide par défaut", carte.keywords_lus == (), carte.keywords_lus)
    check("l'imprimé survit à une lecture vide", carte.has("CantBlock"))
```

`UNIT_B` est « Ombre Fuyante », qui imprime `Can't Block` et `Elusive`
(cf. `test_card_model`) — donc `Formidable` est bien absent des deux
sources, et `CantBlock` bien imprimé. Inscrire les deux tests dans le
lanceur de la suite.

- [ ] **Étape 2 : lancer, vérifier l'échec**

Lancer : `.\.venv\Scripts\python.exe test_game_state.py`
Attendu : ÉCHEC — `keywords_lus` n'existe pas sur `BoardCard`.

- [ ] **Étape 3 : le champ et l'union**

Dans `game_state.py`, juste après `stunned: bool = False` :

```python
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
```

et dans `BoardCard.has` :

```python
        return any(
            _normalize_keyword(existing) == target
            for existing in (*self.keywords, *self.keyword_refs,
                             *self.keywords_lus)
        )
```

- [ ] **Étape 4 : lancer, vérifier que ça passe**

Lancer : `.\.venv\Scripts\python.exe test_game_state.py`
Attendu : les deux nouveaux tests verts, les autres inchangés.

- [ ] **Étape 5 : brancher la lecture dans l'instantané**

Ajouter `import mots_cles_ecran` en tête de `game_state.py`, puis la
fonction près de `enrich_with_live_stats` :

```python
# La barre d'icônes n'existe que sur les unités DU PLATEAU : la main n'en
# a pas, et une carte au centre pendant une désignation est lue dans les
# bandes d'attaque (les deux horloges).
ZONES_DE_PLATEAU = ("board", "attack_row", "enemy_board", "enemy_attack_row")


def lire_les_mots_cles(screen, zones: dict) -> int:
    """
    Pose `keywords_lus` sur les unités du plateau, au vu de l'écran.

    Appelée une seule fois par instantané, là où la capture est DÉJÀ
    payée — et seulement en partie en cours hors mulligan, c'est-à-dire
    là où une unité de plateau existe.

    Ne lève jamais : une lecture impossible laisse le tuple vide, et vide
    veut dire « on n'a pas regardé ».
    """
    if screen is None:
        return 0
    enrichies = 0
    for nom in ZONES_DE_PLATEAU:
        for carte in zones.get(nom, ()) or ():
            try:
                lus = mots_cles_ecran.identifier(screen, carte.center)
            except Exception:   # une lecture ratée n'arrête pas un combat
                continue
            if lus:
                carte.keywords_lus = lus
                enrichies += 1
    return enrichies
```

et, dans `GameStateReader.snapshot()`, juste après
`screen = lor_api.capture_screen_bgr()` :

```python
        lire_les_mots_cles(screen, zones)
```

- [ ] **Étape 6 : vérifier qu'aucune suite ne touche la machine**

Lancer : `.\.venv\Scripts\python.exe check.py --offline`
Attendu : toutes les suites vertes ET « aucune n'a touché la souris, la
molette, l'écran ni la fenêtre ». Si une suite se met à capturer l'écran,
c'est qu'un `snapshot()` tourne sans doublure : la bouchonner EN GARDANT
les appels, patron de `test_actions` pour `capturer_pour_diagnostic`.

- [ ] **Étape 7 : mesurer le coût par instantané**

```bash
.\.venv\Scripts\python.exe -c "import time,cv2,mots_cles_ecran as m; img=cv2.imread('captures_reference/mots_cles/scene_20261120_201157.png'); pts=[(645,900),(802,900),(959,900),(1115,900),(1272,900)]; t=time.perf_counter(); [m.identifier(img,p) for p in pts]; print('5 unites :', round((time.perf_counter()-t)*1000,1), 'ms')"
```

Reporter le chiffre dans la docstring du module. **Au-delà de 50 ms pour
cinq unités, s'arrêter et le signaler** : l'instantané coûte déjà ~2,2 s,
et le projet a pour dette explicite de le réduire, pas de l'alourdir.

- [ ] **Étape 8 : commit**

```bash
git add game_state.py test_game_state.py
git commit -m "mots-cles: l ecran complete la carte imprimee, jamais il ne retire"
```

---

### Tâche 4 : consigner dans `CLAUDE.md`

Le projet distingue explicitement *mesuré* de *supposé* : toute section
non observée en partie porte « PAS ENCORE VU TOURNER EN JEU ».

**Fichiers :**
- Modifier : `CLAUDE.md` — nouvelle section, plus une ligne dans la liste
  « Jamais vu tourner en jeu »

**Interfaces :**
- Consomme : les chiffres mesurés aux tâches 1, 2 et 3.
- Produit : deux finitions d'une ligne chacune, puis la documentation.

- [ ] **Étape 0 : les deux finitions retenues des revues**

Deux constats Mineurs ont été retenus parce qu'ils touchent des doctrines
du projet. Ils coûtent une ligne chacun et sont regroupés ici plutôt que
dans un tour de correctif.

**(a) Un échec silencieux est le pire défaut du projet.**
`game_state.py`, dans `lire_les_mots_cles` : la branche
`except Exception: continue` ne journalise RIEN. Toutes les autres
dégradations « une lecture ratée n'arrête pas un combat » du même fichier
journalisent un `LOGGER.warning` avec le message d'exception avant de
dégrader. Ici, un défaut futur dans `mots_cles_ecran.identifier()`
disparaîtrait pour toujours, et `enrichies` descendrait sans que personne
ne sache pourquoi. Ajoute la trace, en suivant exactement la forme des
`except` voisins du fichier (va les lire, ne l'invente pas). Le code vient
du plan, ce n'est la faute de personne.

**(b) Une docstring devenue fausse.**
`mots_cles_ecran.py` : la ligne « UNE SEULE SCÈNE OBSERVÉE (14/11/2026) »
ne l'est plus — la scène étiquetée du 20/11 existe, et c'est elle qui
porte toute l'identification. Mets-la à jour. C'est la même classe de
défaut que la table de mesures corrigée à la tâche 1 : dans ce module,
un chiffre ou une date laissés faux ont déjà coûté cher.

Puis `.\.venv\Scripts\python.exe check.py --offline` au premier plan, et
commit de ces deux finitions **séparément** de la documentation :

```bash
git add game_state.py mots_cles_ecran.py
git commit -m "mots-cles: tracer l echec de lecture, et une docstring a jour"
```

- [ ] **Étape 1 : écrire la section**

Y faire figurer, avec les nombres réels et non des arrondis de mémoire :

- la preuve `06SI009` — 2 mots-clés imprimés contre 4 à l'écran, dont
  **Challenger et Overwhelm accordés**, sur 5 unités ;
- les quatre teintes (144, 95, 16, 19) et le fait que le magenta
  manquait depuis le 14/11 ;
- la géométrie confirmée — icônes à dy +58..+81 dans une bande mesurée
  +38..+82, pas de ~24,7 px, et la conversion de l'axe Y de l'API
  (`haut_écran = hauteur − TopLeftY`), vérifiée sur une trame appariée ;
- les scores et marges d'identification relevés à la tâche 2 ;
- le coût en millisecondes relevé à la tâche 3 ;
- le prix assumé : pas de Silence, pas les icônes qui se touchent ;
- le nom de la capture témoin et de sa trame `.json`.

- [ ] **Étape 2 : marquer la dette d'observation**

Ajouter à la liste « Jamais vu tourner en jeu » : la lecture des
mots-clés accordés n'est mesurée que sur des captures tant qu'une session
ne l'a pas exercée.

- [ ] **Étape 3 : commit**

```bash
git add CLAUDE.md
git commit -m "doc: la lecture des mots-cles accordes, mesuree sur la scene du 20/11"
```

---

## Ce que ce plan NE fait pas

- **Les 16 autres mots-clés modélisés.** Quatre gabarits seulement sont
  récoltables aujourd'hui. Chaque nouveau demande une capture étiquetée
  par Ewan — « de gauche à droite : … » — et une phrase suffit.
- **Les icônes qui se touchent.** Le compte est à ±1 quand elles
  fusionnent (mesuré le 14/11) ; ces glyphes-là ne seront pas identifiés,
  et c'est voulu.
- **Le Silence**, ni aucun retrait de mot-clé. Prix assumé de l'union.
- **La main.** La barre n'existe que sur les unités du plateau.
