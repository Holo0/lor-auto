# Lire à l'écran les mots-clés ACCORDÉS — design du 20/11/2026

## Pourquoi, et ce qui le prouve

`keywords.has()` porte depuis le début ce commentaire : « c'est ici, et
ici seulement, qu'il faudra brancher une lecture à l'écran des mots-clés
ACCORDÉS ». L'API ne rend qu'un CardCode : un Overwhelm donné par un
sort, une Barrier posée ce round, un Challenger accordé sont invisibles,
et le bot calcule ses duels sur la carte IMPRIMÉE.

**La preuve est désormais mesurée, pas supposée.** Capture appariée à sa
trame d'API, `captures_reference/mots_cles/scene_20261120_201157.png` et
son `.json` :

    carte       06SI009 « Pâle orchestre » (Ghastly Band), 5 exemplaires
    imprimés    Hallowed, Ephemeral          (card_sets, 2 mots-clés)
    à l'écran   Ephemeral, Hallowed, Challenger, Overwhelm   (4 icônes)

**Challenger et Overwhelm sont donc ACCORDÉS**, et ce sont deux mots-clés
MODÉLISÉS : le premier décide si un blocage est légal, le second change
l'excédent d'une attaque. Sur ces cinq unités, le bot décidait comme si
elles n'avaient ni l'un ni l'autre.

L'ordre vient d'Ewan (20/11, fait de jeu) : « chacun des Pâle orchestre a
dans l'ordre, de gauche à droite, éphémère, sanctification, challenger et
enfin surpuissance ». C'est la PREMIÈRE scène étiquetée du projet, et
c'est exactement ce qui manquait à `mots_cles_ecran.py` depuis le 14/11.

## Ce qui existe déjà, et qui ne change pas

`mots_cles_ecran.py` (14/11) sait déjà DÉTECTER la présence d'icônes :
bande en coordonnées relatives au centre de la carte, masque de couleur,
composantes connexes. Il est honnête sur sa limite — « la présence est
fiable, le compte ne l'est pas » — et ne prétend identifier personne.
Sa suite `test_mots_cles_ecran.py` est inscrite dans `check.py`.

**Sa géométrie est confirmée par la nouvelle capture**, ce qui est le
premier résultat de ce chantier :

    carte 06SI009   rect écran x 582-709, y 820-980, centre (645, 900)
    icônes          dy +58..+81, dx -46..+50
    bande du module dy +38..+82, demi-largeur 80      -> les deux tiennent

Conversion de l'axe Y vérifiée sur cette trame : `haut_écran =
hauteur - TopLeftY`.

## Les quatre pièces

### 1. Le masque gagne une troisième famille de couleur

Le module ne connaît que ORANGE (teinte 8-28) et BLEU (88-112). Mesuré
sur les quatre icônes de la capture :

    x=599  16x23  teinte 144   magenta   Éphémère      <- HORS des deux
    x=624  17x23  teinte  95   cyan      Sanctification
    x=648  23x22  teinte  16   orange    Challenger
    x=673  22x23  teinte  19   orange    Surpuissance

**Le sablier d'Éphémère est invisible au masque actuel.** Il y a au moins
trois familles, pas deux. On ajoute une bande autour de 144.

Pas entre icônes : **~24,7 px**. Glyphes de 16-23 x 22-23.

### 2. Une bibliothèque de gabarits ÉTIQUETÉE PAR EWAN

Un PNG par mot-clé dans `mots_cles/<nom>.png`, découpé des captures dont
Ewan nomme l'ordre — la méthode de `chiffres/N_defi.png`, y compris sa
règle : **on ne récolte un gabarit que là où il a été vu et nommé.**
Deviner l'identité d'une icône serait inventer, et le module le dit déjà.

Quatre disponibles aujourd'hui : Ephemeral, Hallowed, Challenger,
Overwhelm. Les 16 autres mots-clés modélisés attendent leur capture.

### 3. L'identification reprend `digits.py`, pas un algorithme neuf

Masque normalisé, comparaison de formes, DEUX PALIERS (sûr / candidat).
Un glyphe sous le seuil **n'est pas identifié** : il retombe sur « il y a
une icône », le verdict que le module rend déjà. Jamais une valeur
approchée — la règle de `lire_palier` et de `_cached_ocr`.

Conséquence assumée : les icônes qui se TOUCHENT (compte à ±1, mesuré le
14/11) ne seront pas identifiées. On n'identifie que les glyphes nets.

### 4. Le branchement est une UNION, et il passe par `keywords.has()`

Décision d'Ewan du 20/11 : **l'écran COMPLÈTE la carte imprimée, il ne
retire jamais rien.** Les mots-clés lus s'ajoutent à ceux de `card_sets`.

- Un glyphe raté ne fait rien perdre : on retombe sur l'imprimé, le
  comportement d'aujourd'hui.
- Un glyphe lu ajoute ce que l'API ne dit pas.
- **On ne verra pas les mots-clés RETIRÉS** (Silence) : prix assumé,
  écrit ici pour qu'il ne soit pas redécouvert comme un bogue.

`has()` reste le point unique. **LE PATRON EXISTE DÉJÀ : `stunned`.**
Lui aussi est lu à l'écran, absent de l'API, posé sur la carte après
coup, et son commentaire porte la règle qu'on reprend telle quelle —
« faux par défaut veut dire ON N'A PAS REGARDÉ, pas *elle est saine* ».

`BoardCard` gagne donc un champ `keywords_lus: tuple = ()`, DISTINCT de
`keywords` et `keyword_refs`, pour que les deux sources restent
séparables au diagnostic ; `BoardCard.has()` — la seule implémentation,
celle que `keywords.has()` appelle — teste l'union des trois.

La lecture est faite UNE FOIS par instantané, dans
`GameStateReader.snapshot()`, **après la ligne qui capture déjà l'écran**
(`screen = lor_api.capture_screen_bgr()`). C'est le bon endroit pour
trois raisons mesurées : la capture y est déjà payée, elle n'a lieu
qu'en partie EN COURS et hors mulligan — exactement là où une unité de
plateau existe — et `zones` y porte les mêmes objets `BoardCard`, donc
les enrichir suffit. `group_by_zone`, lui, ne reçoit PAS la capture. Interroger l'écran
depuis `has()` serait catastrophique : il est appelé des centaines de
fois par décision.

## Ce que ça ne fait pas

- Pas de lecture des mots-clés de la MAIN : la bande n'existe que sur
  les unités du plateau.
- Pas de compte : « quatre icônes pour deux imprimés » ne prouve pas
  deux dons, il prouve qu'il y a des dons.
- Pas de Silence, voir plus haut.
- Pas d'OCR de texte. On compare des formes, comme partout ailleurs.

## Tests

- La capture appariée du 20/11 devient un témoin : les quatre icônes de
  `06SI009` doivent être identifiées, et l'union doit rendre Challenger
  et Overwhelm **que `card_sets` n'imprime pas**.
- Non-régression : une unité sans icône ne gagne rien ; les quatre
  unités sans mot-clé de la capture du 14/11 ne déclenchent toujours
  rien (zéro faux positif, déjà verrouillé).
- Contre-épreuve : retirer la famille magenta doit faire perdre
  Éphémère, et rien d'autre.
- La suite reste inscrite dans `check.py`, et ne doit toucher ni la
  souris ni l'écran (garde-machine).

## Risques

1. **Une seule scène étiquetée.** Quatre gabarits sur vingt. Les bornes
   seront prises larges et revues à chaque capture ; c'est l'histoire de
   `chiffres/N_defi.png`, où enrichir la police resserre les marges.
2. **Un faux positif est pire qu'un manque.** Un Challenger inventé ferait
   glisser un bloqueur sur un geste que le jeu refuse. D'où les deux
   paliers et l'union plutôt que le remplacement.
3. **Le coût par instantané.** Quelques millisecondes attendues (découpe
   + composantes connexes), à comparer aux ~900 ms que coûte déjà la
   recherche multi-échelle du jeton d'attaque. À mesurer avant de livrer.
