"""
Lire à l'écran les MOTS-CLÉS d'une unité — y compris ceux ACCORDÉS en jeu.

POURQUOI CE MODULE EXISTE (14/11/2026). `CLAUDE.md` annonce ce chantier
depuis le début : « `keywords.has()` est le SEUL point qui interroge une
carte ; c'est là qu'on branchera un jour la lecture des mots-clés
ACCORDÉS ». Aujourd'hui le bot ne lit que les mots-clés IMPRIMÉS, pris
dans `card_sets` (2254 cartes sur 2898). Un Overwhelm donné par un sort,
une Barrier posée ce round, un Challenger accordé : invisibles — comme
l'était le Stun avant `stun.py`. L'API ne rend que SEPT champs :
CardCode, CardID, LocalPlayer et la géométrie.

CE QUE LE JEU DESSINE, ET OÙ
----------------------------
Sur chaque unité DU PLATEAU, le jeu pose une barre noire hexagonale
portant une icône par mot-clé — SOUS l'illustration chez nous, AU-DESSUS
chez l'adversaire (ses statistiques et sa barre sont inversées). Mesuré
le 21/11/2026 sur NEUF unités : celles des scènes du 20 et du 21/11
qui sont de NOTRE côté (les cinq Pâle orchestre, les deux Kennen, les
deux Viktor). Les trois porteuses du 14/11 en sont absentes parce que
le repère n'y est pas net — sur Swain et Legion Saboteur la composante
sombre se prolonge dans l'illustration, comme elle le fait chez
l'adversaire. Le bandeau se détecte lui-même (la composante sombre,
V < 70, qui touche la colonne du centre) ; coordonnées RELATIVES à
`card.center` :

      le bandeau occupe   dy +47 à +89 chez nous (enveloppe des neuf) ;
                          en face, seul son bord HAUT est net : -88 (sa
                          composante sombre s'y prolonge dans
                          l'illustration, elle n'a donc pas de bord bas
                          mesurable)
      sa demi-largeur     65 px (Pâle orchestre) à 71 px (Kennen, Viktor)
      une icône fait      12 à 34 px de côté, aire ≥ 60 px

La bande LUE descend jusqu'à +82 chez nous : le liseré bleu du plateau
monte jusqu'à dy +79 sous nos unités et fusionne avec les icônes qu'il
touche (voir `BARRE_DY_BAS`). Côté adverse, le bord bas de la bande
n'est PAS déduit d'une symétrie — il est mesuré par balayage, voir
`BARRE_ADVERSE_DY_BAS`.

AU-DELÀ DE QUATRE MOTS-CLÉS, LE JEU TASSE LES ICÔNES SUR DEUX NIVEAUX
en quinconce — centres mesurés à dy +59..+62 pour la rangée du haut,
+74..+78 pour celle du bas, le bandeau gardant la même hauteur. C'est
ce que ni la scène du 14/11 (≤ 5 icônes alignées) ni celle du 20/11
(4 alignées) ne pouvaient montrer.

Les icônes se répartissent en TROIS FAMILLES DE COULEUR, orange, bleu
clair et magenta (ce dernier ajouté le 20/11/2026, cf. `MAGENTA`
ci-dessous), nettes et franches sur fond noir.

CE QUI EST MESURÉ, ET CE QUI NE L'EST PAS
-----------------------------------------
Quatre scènes, dont trois étiquetées par Ewan. Les comptes ci-dessous
sont ceux du 21/11/2026 au SOIR, après la refonte du masque ; la colonne
« icônes » est le nombre d'icônes VISIBLES sur la capture, « boîtes » ce
que `icones()` rend. **Une ligne « ×N » vaut N vignettes, et les deux
colonnes y sont données PAR VIGNETTE** — c'est le piège qui a fait
écrire un total faux la première fois.

      scène    unité                     imprimés  icônes  boîtes
      14/11    Swain                         1       5      5
      14/11    Enraged Firespitter           1       2      2
      14/11    Legion Saboteur               0       1      1
      14/11    Arachnoid Sentry              0       0      0
      14/11    House Spider      (adverse)   0       0      0
      14/11    Spiderling        (adverse)   0       0      0
      14/11    Imperial Demol.   (adverse)   0       0      0
      20/11    Pâle orchestre ×5             2       4      4
      20/11    Vaults of Helia   (adverse)   1       1      1
      20/11    Cursed Keeper     (adverse)   2       2      2
      21/11    Kennen (capture kennen)       1       6      6
      21/11    Kennen (capture victor)       1       6      6
      21/11    Viktor n°1                    1       7      7
      21/11    Viktor n°2                    1       7      7
      21/11    Powder Keg ×2     (adverse)   2       3      3
      21/11    Jagged Butcher    (adverse)   1       0      0

      TOTAL, lignes ×N développées :
          21 unités de plateau (16 porteuses, 5 vierges dont 4 adverses)
          63 icônes visibles — 63 boîtes, AUCUNE fausse

**ET CHAQUE BOÎTE EST SUR LA BONNE ICÔNE**, pas seulement en nombre : le
centre de chacune tombe dans l'intervalle du glyphe qu'Ewan a nommé à
cette position (`test_chaque_icone_du_lexique_a_sa_boite`). C'est cette
propriété-là, et pas le compte, qui autorise la récolte à l'INDEX — voir
l'avertissement de `cut_icone`.

CE QUE LE 21/11 AU MATIN RENDAIT, POUR MÉMOIRE : **53 boîtes dont 1
fausse, donc 11 icônes sans boîte à elles.** Les onze manquantes et la
fausse ne venaient PAS de la segmentation mais du MASQUE DE COULEUR, qui
ne connaissait que trois familles — et de trois bornes de taille calées
sur des glyphes qui, eux, étaient déjà rognés par ce masque :

  - le CERCLE ROUGE de Régénération (les deux Kennen) sortait aux teintes
    2 à 11 quand `ORANGE` commençait à 8 : il n'en restait qu'un ruban de
    19×8, refusé par la hauteur ;
  - la CROIX BLANCHE d'Immobile (les deux Powder Keg) et le BOUCLIER
    BLANC de « Can't Block » (Cursed Keeper) ont une saturation médiane
    de **17** : aucune famille de teinte ne peut les voir ;
  - la TOUR DORÉE d'Immortalité (les deux Viktor) a une saturation
    médiane de **129** pour un plancher à 130, et une teinte médiane de
    **28** pour une borne haute à 28 : il n'en passait qu'un fragment ;
  - la FLAMME de Volonté fait **10 px** de large, l'icône de NIVEAU de
    Kennen **19×11** sur une des deux captures : sous `ICONE_COTE_MIN`,
    qui valait 12 ;
  - l'œil droit de Redoutable est une composante de **15 px d'aire**,
    sous `FRAGMENT_AIRE_MIN`, qui valait 20 : sans lui le glyphe pesait
    58 px pour un plancher à 60 ;
  - et la fausse boîte était le HALO BLEU du plateau sous Kennen, à
    dx +65, que la bande (±80 px) laisse entrer là où le bandeau n'en
    fait que 71 — voir `_touche_un_bord_lateral`.

ET LE 21/11 AU SOIR, LES COMPTES ÉTAIENT JUSTES PENDANT QUE DEUX
GABARITS ÉTAIENT FAUX. C'est la leçon de cette journée, et elle vaut
pour la suite : **une boîte peut être au bon endroit et ne pas contenir
la bonne matière.** 218 assertions étaient vertes — dont « chaque icône
du lexique a sa boîte », qui juge un CENTRE dans un intervalle de 29 px
— pendant que :

  - l'AILE GAUCHE de l'Augmentation de Kennen (6×7, aire 27, CYAN à la
    teinte 95) était agglomérée au cercle ROUGE de Régénération (teinte
    5), dont la BOÎTE la chevauche en x. `augment` sortait amputé de
    19 % (15×14 / 115 px au lieu de 22×14 / 142) et `regeneration`
    lesté de 27 px qui n'étaient pas à lui — assez pour qu'il ne note
    plus que **0.339** contre la même icône vue ailleurs, au lieu de
    **0.838**. Corrigé dans l'AGGLOMÉRATION (voir `ECART_X_DEBRIS` et
    la clé de `_grouper`) ;
  - `identifier` tranchait le MASQUE PARTAGÉ de la bande à la boîte,
    si bien qu'un glyphe emportait les pixels de son voisin quand les
    deux boîtes se chevauchent — `augment2` portait **31 px de
    `deathless` sur 177, 18 %**. Mesuré : **11 des 63 crops** étaient
    dans ce cas. Corrigé dans le DÉCOUPAGE (voir `_icones_et_glyphes`).

Les deux défauts ne se voyaient pas par le même chemin, et c'est
pourquoi `test_la_matiere_dun_gabarit_est_a_lui` porte DEUX assertions.
**Onze des 23 gabarits ont changé** à la re-récolte ; les douze autres
sont identiques au bit près.

**SEIZE FORMES RÉCOLTÉES : QUATORZE MOTS-CLÉS ET DEUX DESSINS
D'AFFICHAGE** (21/11/2026). Ewan a étiqueté trois scènes — cinq Pâle
orchestre (06SI009) le 20/11 « dans l'ordre, de gauche à droite,
éphémère, sanctification, challenger et enfin surpuissance », puis
Kennen (05BC058) et les deux Viktor (03PZ003) le 21/11. L'identité
d'une icône vient donc d'un FAIT DE JEU, jamais d'une ressemblance.
`identifier()` compare chaque glyphe DÉCOUPÉ aux gabarits de
`mots_cles/` par le chemin de `digits.py` (IoU, égalisation du trait,
rapport d'aspect conservé) et ne rend que ce qui franchit SCORE_SUR ET
MARGE_SURE. Les six mots-clés modélisés qui en sortent — `QuickStrike`,
`Elusive`, `Deathless`, `Impact`, `Fearsome`, `Overwhelm` — changent
chacun un calcul que le bot sait déjà faire.

⚠⚠ LA BANDE COUPE LES GLYPHES, ET LA TRONCATURE EST GRAVÉE DANS LA
BIBLIOTHÈQUE (mesuré le 21/11/2026 au soir). C'est la dette la plus
lourde de cette récolte, et elle n'est PAS réparée ici — la géométrie
de la bande a été mesurée et verrouillée par une autre tâche.

      **17 des 63 boîtes touchent un bord horizontal de la bande** —
      2 en haut, 15 en bas, soit **27 %** ;
      **7 des 23 gabarits livrés en viennent** : `quickstrike`,
      `spellshield`, `aura`, `deathless`, `fearsome`, `niveau2` et
      `hallowed2` ;
      et `augment` est tronqué SANS toucher le bord, ses dernières
      lignes tombant sous `FRAGMENT_AIRE_MIN`.

⚠⚠ ET LA TRONCATURE RONGE LE DROIT DE NOMMER. `COTE_MIN_POUR_NOMMER`
vaut 11 et porte sur le PLUS PETIT CÔTÉ du gabarit. Or trois des
gabarits rognés sont déjà à un ou deux pixels de ce plancher, et leur
petit côté est précisément la HAUTEUR que la bande a coupée :

      quickstrike  (47, 23, 15, 12)   petit côté 12   ⚠ MODÉLISÉ
      aura         (38, 23, 21, 12)   petit côté 12     (affichage)
      fearsome     (105, 22, 16, 13)  petit côté 13   ⚠ MODÉLISÉ

(y + h = 35 = la hauteur de la bande : les trois boîtes finissent sur
sa dernière ligne.) UNE LIGNE DE PLUS rognée à la prochaine re-récolte
met `quickstrike` à 11, DEUX LIGNES à 10 — et il devient MUET sur ses
deux positions. Frappe rapide est l'un des mots-clés que `keywords.py`
chiffre : le perdre changerait un calcul de combat, en silence.

AVANT DE RE-RÉCOLTER, LIRE CE QUE LE FILET DIT. Le garde est
`test_un_mot_cle_modelise_ne_devient_pas_muet`, qui compare les familles
muettes à `keywords.MODELLED_KEYWORDS` ; il rougit si un gabarit maigrit
sous le plancher comme si l'on montait le plancher. Le remède de fond,
lui, est le même que pour les deux `augment` : rendre à la bande le
quart de glyphe qu'elle coupe — ce qui demande d'abord de régler la
fusion avec le liseré bleu (voir `BARRE_DY_BAS`).

Ce n'est pas une imprécision de mesure, c'est une conséquence assumée de
`BARRE_DY_BAS` = 82 : le liseré bleu du plateau monte jusqu'à dy +79 et
fusionnerait avec les icônes si l'on descendait plus bas (voir le
commentaire de cette constante — « un glyphe rogné reste compté, un
glyphe fusionné est perdu »). Mais un glyphe rogné RÉCOLTÉ devient un
gabarit rogné, et un gabarit rogné ne reconnaît plus la même icône vue
en rangée HAUTE : c'est toute l'histoire des deux `augment`, 0.388 l'un
contre l'autre, et c'est pour ça qu'il faut une variante par rangée.
Chiffré sur l'Augmentation de Kennen : lue jusqu'à dy +86 elle ferait
22×19 pour 189 px, contre 22×14 et 142 px dans la bande — **un quart du
dessin manque**. À reprendre le jour où la géométrie de la bande sera
rouverte.

LES GABARITS SONT DÉCOUPÉS PAR LE CHEMIN DE LECTURE, DONC ILS SUIVENT
LA SEGMENTATION. Le masque ayant été refait le 21/11 au soir, TOUS les
PNG de `mots_cles/` ont été redécoupés : les huit d'avant sur la même
capture, aux mêmes centres et dans le même ordre étiqueté par Ewan, et
les treize autres à des positions nommées. C'est la règle que
`cut_icone` énonce et que le piège de `cut_defi` (08/11) a payée : une
forme découpée autrement ne se reconnaît plus elle-même.

ON NE RÉCOLTE QU'UNE SOURCE PAR FORME QUAND IL Y EN A DEUX, pour garder
un TÉMOIN INDÉPENDANT — un gabarit comparé à son propre découpage rend
1.0 et ne prouve rien. Mesuré sur ces témoins :

      Kennen, capture `victor` (ses six gabarits viennent de l'autre
      capture)                              0.805 à 0.992 | marges 0.422-0.569
      Viktor n°2 : `aura`, `deathless`      0.962 et 0.932
      les trois derniers Pâle orchestre     0.784 à 0.990 | marges 0.378-0.609
      Firespitter (14/11) contre les
      gabarits du 20/11                     0.942 et 0.797

DEUX FORMES ONT DEMANDÉ UNE SECONDE VARIANTE, et la mesure dit pourquoi
— ce n'est pas du confort :
  - `augment` : la MÊME icône est en rangée BASSE chez Kennen et en
    rangée HAUTE chez Viktor. La bande s'arrêtant à dy +82, celle du bas
    est ROGNÉE : **0.388** entre les deux, contre **0.987** entre les
    deux Viktor. Une icône de rangée basse et la même en rangée haute ne
    sont pas la même forme, et il faut une variante par rangée ;
  - `niveau` : l'indicateur de niveau est ANIMÉ. Viktor n°1 montre un
    disque bleu entier, Viktor n°2 le même disque mangé par son éclat —
    0.337 à 0.452 entre les trois variantes. (Chez Kennen c'est un
    chevron, troisième dessin de la même famille.)

⚠ ET LES DEUX `augment` NE SE RECOLLENT TOUJOURS PAS, APRÈS RÉPARATION.
Le 21/11 au soir, l'aile gauche a été rendue à l'Augmentation de Kennen
(15×14 → 22×14) et `augment2` a été débarrassé des 31 px de son voisin :
le score entre les deux est passé de 0.424 à **0.388** — il a BAISSÉ.
Regardées à l'image, les deux sont pourtant le MÊME dessin, et l'écart a
une cause mesurée : **la bande COUPE celle du bas**. En lisant jusqu'à
dy +86 au lieu de +82, le glyphe de Kennen passe de 22×14 / 142 px à
22×19 / **189 px** — un quart du dessin manque, et ce sont ses deux
pattes inférieures. Normaliser un glyphe amputé à 32 px ne redonne pas
la forme entière. La variante par rangée reste donc justifiée **et le
restera tant que la bande s'arrêtera là**.

ET CE N'EST PLUS « MON ŒIL SUR UNE IMAGE » : EN RENDANT LA MATIÈRE, LE
SCORE MONTE (mesuré le 21/11 en re-revue, en faisant varier `BARRE_DY_
BAS` sur l'Augmentation de Kennen, comparée à `augment2`) :

      bande +82   22×14 / 142 px   0.388
      bande +83   22×16 / 157 px   0.488
      bande +84   22×17 / 163 px   0.576
      bande +85   22×18 / 184 px   0.706   > SCORE_SUR
      bande +86   22×19 / 189 px   0.674

Rendre le quart manquant fait FRANCHIR le plancher d'identification à
un couple qui était à 0.388 : l'écart est entièrement dû à la
troncature, et les deux étiquettes d'Ewan tiennent. (Montée stricte de
+82 à +85, creux à +86 : la segmentation rend une boîte légèrement
différente à chaque pas, la direction n'est pas ambiguë pour autant.)
ON NE DESCEND PAS LA BANDE POUR AUTANT, et c'est mesuré sur la même
commande : à +84 Sanctification FUSIONNE avec le liseré du plateau (H
114, bleu) et le Pâle orchestre tombe de 4 icônes à 3 ; à +86 deux des
cinq vignettes tombent. Il reste à Ewan de confirmer sur la planche que
ces deux icônes sont bien la même (la planche est faite pour ça).

MESURE DE L'IDENTIFICATION, bibliothèque complète (21/11/2026 au soir,
après la réparation des gabarits), sur les 63 glyphes des quatre
captures. Les classes sont trois, et il faut les distinguer :

      44 positions NOMMÉES par Ewan     les 24 du lexique (hors les deux
                                        « 7e ») plus les 5 × 4 du Pâle
                                        orchestre
      2 TÉMOINS EXTERNES                Firespitter, dont `card_sets`
                                        imprime Challenger
      2 icônes NON nommées              les 7e des deux Viktor
      15 glyphes ÉTRANGERS              ceux dont AUCUN gabarit n'existe :
                                        les 5 de Swain, celui de Legion
                                        Saboteur, les 3 de chaque Powder
                                        Keg, les 2 de Cursed Keeper,
                                        celui de Vaults of Helia

      les 43 positions RENDUES          score 0.784 à 1.000 | marge 0.378-0.644
      les 15 ÉTRANGÈRES                 **aucune nommée**, et aucune ne
                                        franchit LES DEUX planchers.
                                        (Deux franchissent celui de
                                        MARGE — 0.112 et 0.120 — et
                                        leur tête est `spirit` : c'est
                                        la marge que `COTE_MIN_POUR_
                                        NOMMER` rachète. La formule
                                        « l'un OU l'autre » écrite ici
                                        jusqu'au 21/11 était fausse.)
      les 2 témoins                     0.942 et 0.797, identifiés
      les 2 « 7e »                      Elusive 0.715 et Regeneration
                                        0.838, identifiées

LA 44e POSITION EST RENDUE `None`, ET C'EST UNE DÉCISION : la Volonté de
Viktor n°1 a pour gabarit `spirit`, 10×13, trop petit pour NOMMER (voir
`COTE_MIN_POUR_NOMMER`). Son glyphe reste LU et COMPTÉ.

UNE ICÔNE NON NOMMÉE PEUT SE FAIRE RECONNAÎTRE, ET C'EST LE CONTRÔLE
QU'ON ATTEND D'ELLE. Les deux 7e qu'Ewan a laissées de côté (« oublie le
7e »), et qui ne sont donc PAS récoltées, sortent `Elusive` à **0.715,
marge 0.287** chez Viktor n°1 et `Regeneration` à **0.838, marge 0.316**
chez Viktor n°2 : ce sont les mêmes dessins que la position 3 de Kennen
et que sa position 5. Deux chemins indépendants, la même réponse — et le
second est la contre-épreuve du gabarit de Régénération réparé, qui ne
notait que **0.339** tant qu'il portait l'aile de son voisin.

⚠ LA MARGE DE SÉCURITÉ S'EST RESSERRÉE EN GRANDISSANT, ET IL A FALLU LA
RACHETER. À quatre familles, le meilleur étranger notait 0.472 ; à
seize, `spirit` le portait à **0.576 — 0.024 sous le plancher de
score — et DEUX étrangers franchissaient déjà le plancher de MARGE**
(0.112 et 0.120 contre 0.10). Un seul des deux planchers tenait encore.
Depuis que `spirit` ne nomme plus, le meilleur étranger nommable retombe
à **0.504 (marge 0.075)** : **+0.096 et +0.025** de distance aux deux
planchers, sans qu'aucun seuil ait été touché. C'est exactement ce que
le projet a mesuré sur la police des chiffres le 14/11 (« enrichir une
police resserre ses marges »). **Ne pas élargir la bibliothèque sans
remesurer ces deux colonnes.**

CE QUE ÇA PERMET DÉJÀ. Une unité SANS mot-clé imprimé qui porte une
icône a forcément été RENFORCÉE en jeu — et c'est observé : Legion
Saboteur (01NX040, `keywords=[]`) porte une icône bleue. `identifier()`
rend désormais un second verdict, plus fort : le NOM du mot-clé.

⚠ ET LA BIBLIOTHÈQUE COÛTE CE QU'ELLE PÈSE (21/11/2026 au soir). La
comparaison est LINÉAIRE en nombre de gabarits, et CLAUDE.md l'annonçait
(« 46,6 ms à 4 mots-clés contre 239,7 ms à 20 — ×5,1 »). Mesuré sur la
MÊME scène, le MÊME code, médiane de 9 tours, 7 unités de plateau :

      4 familles /  8 gabarits (le 21/11 au matin)    53,4 ms
      16 familles / 23 gabarits (aujourd'hui)        153,9 ms   ×2,88

— à comparer au rapport des gabarits, 23/8 = ×2,875 : c'est la taille
de la bibliothèque, rien d'autre. Par glyphe : **2,1 ms avant, 6,7 ms
maintenant**. Rapporté aux ~2200 ms d'un instantané, la lecture des
mots-clés passe de **2,3 % à 7,0 %**, pour un budget annoncé à 50 ms.
(Le découpage par groupe du 21/11 au soir y ajoute 0,09 ms par unité :
segmentation 0,41 → 0,50 ms, soit +1 % sur le total.)
Le remède est déjà nommé dans CLAUDE.md et n'est PAS fait ici : un
PRÉ-TRI PAR FAMILLE DE COULEUR — les teintes sont déjà séparées, un
glyphe magenta n'a rien à comparer à un gabarit orange.
`game_state.MOTS_CLES_ECRAN = False` reste l'interrupteur de repli.

Le coût de `porte_des_mots_cles` suit le même chemin depuis qu'elle
identifie : 0,4 ms par unité avant, ~22 ms maintenant. Elle n'a aucun
appelant en jeu (`lire_les_mots_cles` appelle `identifier`), mais c'est
à savoir avant de lui en donner un.

PIÈGES MESURÉS ET ÉCARTÉS
-------------------------
  - LA BARRE NOIRE SEULE. « Le plus long segment sombre sous la carte »
    donne 109 px pour Swain mais 62 px pour Legion Saboteur (UNE icône)
    contre 55 px pour Firespitter (DEUX) : la largeur ne compte pas les
    icônes, elle suit l'illustration. Et Arachnoid Sentry, qui n'a
    aucune barre, atteint quand même 34 px d'ombre.
  - LA COULEUR SANS BORNE VERTICALE. Compter les pixels orange ou bleus
    sous la carte sature à 100 % pour TOUT LE MONDE : le liseré bleu
    électrique du plateau et la rangée suivante entrent dans la fenêtre.
    C'est la fenêtre verticale qui les exclut, pas la teinte.
  - LE CLAIR À LA PLACE DES FAMILLES DE COULEUR (essayé deux fois, le
    21/11/2026 matin puis soir, et ÉCARTÉ sur la mesure). Segmenter
    « tout ce qui est brillant » voit bien le cercle rouge et la croix
    blanche, mais il voit AUSSI tout ce qui entoure le bandeau, et il
    n'a aucun moyen de l'en distinguer. Compté sur les 21 unités, avec
    la segmentation et les gardes actuels :

          seuil de clarté    icônes vues / 63    fausses boîtes
                100                 53                4
                120                 53                4
                140                 55                0
                160                 55                0
          les quatre familles       63                0

    Et son échec est le PIRE possible : il porte sur la scène du 14/11,
    la seule dont les mots-clés IMPRIMÉS servent d'oracle. Swain y tombe
    de 5 icônes à 3, Firespitter de 2 à 1, et **Legion Saboteur à ZÉRO**
    — c'est-à-dire que le cas qui justifie tout le module disparaît. La
    raison est mesurée au §1.1 : sur cette capture-là le bandeau noir
    « fuit » dans l'illustration, donc le clair n'y délimite plus rien.
    S'y ajoutait, au matin, que les glyphes grossissent du bord
    inférieur du bandeau (Provocateur 23×30 au lieu de 23×22) et que
    Sanctification cessait d'être identifiée.
  - L'ENVELOPPE CONVEXE DU BANDEAU comme masque spatial : elle déborde
    sur les coins de l'hexagone et le liseré du plateau y rentre
    (Kennen, une 7e boîte de 31×14 px). Le remplissage ligne à ligne de
    la composante sombre, lui, perd les glyphes qui touchent le bord du
    bandeau — deux icônes sur quatre du Pâle orchestre.

QUATRE SCÈNES (mis à jour le 21/11/2026 au soir). La géométrie du
bandeau est mesurée sur les neuf unités de NOTRE côté, et par balayage
côté adverse (cf. `BARRE_ADVERSE_DY_BAS`). L'IDENTIFICATION repose sur
les trois scènes étiquetées par Ewan — les cinq Pâle orchestre du
20/11, Kennen et les deux Viktor du 21/11 — chacune gardant au moins un
exemplaire NON récolté comme témoin. Les seize glyphes qui n'ont pas de
gabarit (Swain, les Powder Keg, Cursed Keeper, Vaults of Helia, Legion
Saboteur, la 7e de Viktor n°2) servent de témoins NÉGATIFS.

RIEN DE TOUT CECI N'A ENCORE TOURNÉ EN JEU : tout est mesuré sur quatre
captures appariées à leur trame d'API.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

import digits

# UNE DÉGRADATION MUETTE EST LE PIRE DÉFAUT DU PROJET. Ce module peut
# cesser de rendre un mot-clé sans que rien ne casse : gabarit sans
# alpha, dossier `mots_cles/` vidé, bande décalée. Tout ce qui le fait
# RETOMBER sur le comportement d'avant passe donc par ce logger.
LOGGER = logging.getLogger(__name__)

# La barre d'icônes, en coordonnées relatives à `card.center`.
#
# OÙ EST LE BANDEAU, MESURÉ (21/11/2026). Le rectangle noir se détecte
# tout seul (la composante sombre, V < 70, qui touche la colonne du
# centre) : sur les NEUF unités du 20 et du 21/11 qui sont de NOTRE côté
# (cf. le relevé en tête de module) il occupe **dy +47..+89** —
# enveloppe des neuf, de +47 (Pâle orchestre) à +89 (Kennen sur la
# capture `victor`). Sa demi-largeur va de 65 (Pâle orchestre) à 71 px
# (Kennen, Viktor).
#
# CÔTÉ ADVERSE, SEUL LE BORD HAUT EST MESURABLE : **-88**. La composante
# sombre s'y prolonge dans l'illustration, donc le bandeau n'a pas de
# bord bas net, et on NE SUPPOSE PAS la symétrie — voir
# `BARRE_ADVERSE_DY_BAS`, dont la valeur vient d'un balayage.
#
# ON NE LIT PAS LE BANDEAU ENTIER DE NOTRE CÔTÉ, ET C'EST MESURÉ. Le
# liseré bleu du plateau MONTE jusqu'à dy +79 sous nos unités et touche
# les icônes : porter `BARRE_DY_BAS` de 82 à 88 (le vrai bas du bandeau)
# fait fusionner Sanctification avec ce liseré en une composante de
# 118×32 px, et le Pâle orchestre tombe de 4 icônes à 3 sur DEUX des
# cinq vignettes du 20/11, plus une icône fantôme sur une troisième. On
# garde donc +82 et on accepte que le bas d'un glyphe de la rangée
# inférieure soit rogné (Kennen : épée lue +70..+82 au lieu de +70..+86)
# — un glyphe rogné reste compté, un glyphe fusionné est perdu.
#
# ⚠ ET UN GLYPHE ROGNÉ QU'ON RÉCOLTE DEVIENT UN GABARIT ROGNÉ : 15 des
# 63 boîtes finissent sur la dernière ligne de la bande, et 7 des 23
# gabarits livrés en viennent. Voir le bloc « LA BANDE COUPE LES
# GLYPHES » en tête de module pour le relevé et pour ce qu'il coûte.
#
# CÔTÉ ADVERSE IL N'Y A PAS DE LISERÉ AU-DESSUS DES CARTES, et la bande
# y est BORNÉE PAR BALAYAGE, pas par symétrie (21/11/2026). Les icônes
# adverses occupent **dy -82..-56** sur les quatre unités porteuses
# (Powder Keg ×2, Cursed Keeper, Vaults of Helia). En faisant varier le
# bord bas px par px, le compte — 2, 2, 1, 1 sur les porteuses et ZÉRO
# sur les quatre vierges — est **stable de -66 à -41** ; le PREMIER faux
# positif apparaît à **-40** (Powder Keg passe à 3 : une composante
# 28×12 à dy -52..-40, sous le bandeau, dans le cadre de la carte).
# -48 est au milieu de ce plateau de 26 px, à 8 px du premier faux
# positif. Au-dessus, -70 fait perdre Cursed Keeper et -68 les deux
# Powder Keg, tandis que le compte tient sans une seule fausse boîte
# jusqu'à -120 : **-88 a 17 px de marge du bon côté, et aucune du
# mauvais, parce qu'il n'y en a pas à avoir.**
BARRE_DY_HAUT = 47
BARRE_DY_BAS = 82
BARRE_ADVERSE_DY_HAUT = 88      # distance AU-DESSUS du centre
BARRE_ADVERSE_DY_BAS = 48
BARRE_DEMI_LARGEUR = 80

# Une icône : ni un éclat de décor, ni la barre entière.
#
# LES TROIS BORNES SONT MESURÉES, ET CHACUNE A SA FENÊTRE (21/11/2026,
# balayage sur les 21 unités des quatre captures — 63 icônes étiquetées,
# zéro fausse boîte attendue) :
#
#   ICONE_COTE_MIN   8  9 10 | 11 12        10 est la plus STRICTE qui
#                    63 63 63| 62 61        voie encore la flamme de
#                            |              Volonté, large de 10 px dans
#                            |              le masque (Viktor n1) ; 11
#                            |              la perd, 12 perd en plus le
#                            |              chevron de niveau de Kennen
#                            |              (19×11 sur la capture
#                            |              `victor`).
#   ICONE_COTE_MAX  31 32 33 | 34 36        33 est forcé des DEUX côtés :
#                    63 63 63| 62 56        le plus grand glyphe VRAI
#                            |              mesuré fait 32×29 (Swain), et
#                            |              l'union fautive qui avale
#                            |              Redoutable ET l'icône 7 de
#                            |              Viktor n2 fait 34×30. Seuls
#                            |              32 et 33 séparent les deux ;
#                            |              on prend le plus permissif.
#   ICONE_AIRE_MIN  55 60 64 | 65 70        INCHANGÉ. En dessous de 55 on
#                    63 63 63| 61 61        fabrique des fausses boîtes
#                            |              (1 à 50, 2 à 40 — le coin
#                            |              haut-droit du plateau sous
#                            |              Kennen) ; à 65 on perd Frappe
#                            |              rapide, dont le masque ne
#                            |              pèse que 63 px.
ICONE_COTE_MIN, ICONE_COTE_MAX = 10, 33
ICONE_AIRE_MIN = 60

# UN GLYPHE FRAGMENTÉ N'EST PAS TROIS PETITES ICÔNES (20/11/2026).
# Le glyphe « Surpuissance » (orange, teinte 19, Pâle orchestre 06SI009)
# a une ombre interne qui coupe son masque en plusieurs morceaux — un
# trait du GLYPHE, pas de la famille de couleur : 22×11 (aire 117) +
# 9×8 (52) + 4×8 (23) + 16×8 (61), alors que le glyphe ENTIER fait
# 22×24. Abaisser `ICONE_COTE_MIN` à 11 n'aurait laissé passer QUE le
# plus gros fragment (22×11, toujours pas le bon rectangle) — et rien
# n'aurait rougi si `icones()` avait un jour tort sur le DÉCOUPAGE,
# puisque les cinq vignettes de la scène se fragmentent à l'identique
# (auto-cohérence sans vérité : le piège de `cut_defi` le 08/11).
# `icones()` recolle donc les fragments voisins avant de juger leur
# taille. Sont exclus de la fusion les fragments sous
# `FRAGMENT_AIRE_MIN` : du bruit d'antialiasing ou de compression.
#
# 20 JETAIT UN MORCEAU DE GLYPHE RÉEL (21/11/2026). L'œil DROIT du
# visage de Redoutable (Viktor n°2, position 6) est une composante de
# 5×5 et d'aire **15** : sans lui, le glyphe recollé pèse 58 px et
# tombe sous `ICONE_AIRE_MIN` = 60 — Redoutable disparaissait, et c'est
# l'un des quatorze gabarits à récolter. Fenêtre mesurée sur les 21
# unités : **8 à 15 rendent les 63 icônes sans une seule fausse boîte**,
# 16 et 20 perdent Redoutable. On prend 14, juste sous le plus petit
# fragment RÉEL mesuré — la borne la plus stricte compatible avec lui.
FRAGMENT_AIRE_MIN = 14

# LE RECOLLAGE PAR COLONNE SUPPOSAIT UNE SEULE LIGNE (corrigé le
# 21/11/2026). Au-delà de quatre mots-clés le jeu TASSE les icônes sur
# DEUX niveaux en quinconce : chaîner les fragments par leurs seules
# plages en x mariait alors une icône du haut à sa voisine du bas (elles
# se chevauchent en x de 5 px sur Viktor), la boîte dépassait
# `ICONE_COTE_MAX`, et le repli rejugeait chaque fragment seul — une
# icône sur deux perdue ou fragmentée (mesuré : 5 boîtes pour 7 icônes,
# 4 pour 6, 4 pour 7).
#
# ON AGGLOMÈRE DONC LES PLUS PROCHES D'ABORD, ET JAMAIS AU-DELÀ DE LA
# TAILLE D'UN GLYPHE. Les fragments d'UN MÊME glyphe sont séparés de 0
# ou 1 px (Surpuissance : 0 partout ; le symbole cyan de Kennen : 1),
# tandis que deux icônes voisines de la MÊME rangée sont séparées de 1 à
# 9 px — c'est donc le plafond de taille, et non l'écart, qui les sépare
# (Challenger + Surpuissance feraient 51 px de large).
#
# L'ÉCART TOLÉRÉ N'EST PAS LE MÊME EN X ET EN Y (21/11/2026), et la
# raison est dans la façon dont la barre est dessinée : le jeu range ses
# icônes HORIZONTALEMENT. Un trou d'un pixel EN HAUTEUR sépare deux
# morceaux d'un même dessin (Swain : la face grimaçante est coupée en
# deux par une ombre, y 17..25 puis 26..35) ; un trou d'un pixel EN
# LARGEUR sépare deux icônes voisines (Viktor n°1 : la flamme de Volonté
# finit à x=118, l'œil barré commence à x=119 — leur union fait 32×26,
# taille de glyphe parfaitement plausible, et Volonté était perdue).
#
# Mesuré sur les 21 unités, les trois règles possibles :
#       max(ex, ey) <= 1   62/63   (perd Volonté)
#       ex = ey = 0        62/63   (perd la face grimaçante de Swain)
#       ex <= 0, ey <= 1   63/63   <- retenue
ECART_X, ECART_Y = 0, 1

# MAIS UN DÉBRIS N'EST PAS UNE ICÔNE, ET LE TROU D'UN PIXEL NE DIT RIEN
# DE LUI (21/11/2026 au soir). `ECART_X` = 0 existe pour empêcher que
# deux ICÔNES voisines se soudent — le cas mesuré est la flamme de
# Volonté et l'œil barré de Viktor n°1, SÉPARÉS d'un pixel et tous DEUX
# de taille de glyphe. Appliqué sans nuance, il coupait aussi un glyphe
# de son propre morceau : l'AILE GAUCHE de l'Augmentation de Kennen
# (6×7, aire 27, à un pixel du corps de l'icône) partait dans le groupe
# du cercle rouge de Régénération, dont la boîte la CHEVAUCHE en x —
# mesuré, teinte 95 (cyan, celle de l'Augmentation) contre 5 (rouge,
# celle de la Régénération). Les deux gabarits en sortaient faux :
# `augment` amputé de 19 % (15×14, aire 115 au lieu de 22×14, aire 142)
# et `regeneration` lesté de 27 px qui ne sont pas à lui.
#
# UN FRAGMENT TROP PETIT POUR ÊTRE UNE ICÔNE a donc le droit de franchir
# UN pixel en largeur — il ne peut pas être « l'autre icône », c'est
# précisément ce que `_est_un_glyphe` répond. Deux glyphes plausibles,
# eux, restent séparés par le trou : Volonté est intacte.
#
# ET IL DOIT ÊTRE POSÉ SUR LE BANDEAU, sans quoi la parade en ouvrirait
# une autre. Mesuré sur les 21 unités, luminosité médiane de l'anneau
# des douze débris qui franchiraient un trou d'un pixel : **23 à 51,5**
# pour ceux qui appartiennent vraiment à un glyphe, et **138** pour le
# seul intrus — l'éclat mauve du décor au-dessus du bord oblique du
# bandeau de Viktor n°1, à 4 px du disque de niveau, qui aurait lesté
# `niveau2` de 24 px de fond de carte. `FOND_SOMBRE_MAX` = 70 les
# sépare avec 18,5 de marge d'un côté et 68 de l'autre : c'est le garde
# qui existe déjà, appliqué un cran plus tôt.
ECART_X_DEBRIS = 1

# UNE ICÔNE EST POSÉE SUR LE BANDEAU NOIR (21/11/2026). C'est ce qui la
# distingue d'un éclat d'illustration de la même couleur, et c'est la
# seule chose qui le fasse : la teinte, la taille et l'aire ne suffisent
# pas.
#
# ⚠ MESURE REFAITE LE 21/11/2026 AU SOIR, ET LA FENÊTRE N'EST PLUS DU
# TOUT CELLE QU'ON ANNONÇAIT. Le commentaire disait « 19 à 38 pour les
# vraies icônes », « 139 et 193 » pour les taches, « 32 de marge de
# chaque côté » : ces chiffres dataient d'AVANT la refonte du masque,
# qui a fait entrer des icônes que les trois anciennes familles ne
# voyaient pas. Remesuré par le chemin du module (canal V, anneau de
# `MARGE_ANNEAU` px) sur les 21 unités, luminosité MÉDIANE de l'anneau :
#
#       les 63 vraies icônes            **19 à 64**
#       les 5 candidates refusées ici   **91, 94,5, 112, 128, 170**
#
# La plus claire des vraies est le disque de niveau de Viktor n°2 (64) ;
# la plus sombre des refusées est le liseré magenta du bord de carte sous
# Swain (91). **La fenêtre réelle est donc 65 à 90**, et le plancher
# retenu laisse **6** points au-dessus de la pire vraie icône et **21**
# sous la plus sombre des taches — pas 32 de chaque côté. On NE monte
# PAS le seuil pour recentrer : ce serait desserrer un garde, et le
# garde en question est celui qui tient « les vierges à zéro ».
# Balayé de 60 à 95 : 60 perd une vraie icône, 95 admet deux taches,
# 65 à 90 ne changent rien.
FOND_SOMBRE_MAX = 70
MARGE_ANNEAU = 3

# Les familles de couleur, en HSV OpenCV. Franches sur fond noir.
#
# QUATRE FAMILLES (21/11/2026), ET C'EST LE MASQUE QUI TENAIT TOUT LE
# RESTE. Il en connaissait trois — ORANGE (teinte 8-28, S ≥ 130), BLEU
# et MAGENTA — construites sur deux captures où toutes les icônes
# étaient de ces teintes. Le vrai jeu en a d'autres, et elles coûtaient
# ONZE icônes sur 63 :
#
#   famille      ce qu'elle rattrape          mesure qui l'a fixée
#   CHAUD        le cercle rouge de           teintes **2 à 11** : ORANGE
#                Régénération (Kennen)        commençait à 8, et il ne
#                                             restait du cercle qu'un
#                                             ruban de 19×8, refusé par
#                                             la hauteur
#   CHAUD        la tour dorée d'Immortalité  S médiane **129** et H
#                (les deux Viktor)            médiane **28** — sous le
#                                             plancher S ≥ 130 d'ORANGE
#                                             et à sa borne haute de
#                                             teinte : elle n'en laissait
#                                             passer qu'un fragment 7×10
#   BLANC        la croix d'Immobile et le    saturation médiane **17** :
#                bouclier de « Can't Block »  AUCUNE famille de teinte ne
#                (Powder Keg, Cursed Keeper)  peut la voir
#
# CHAUD remplace donc ORANGE en élargissant des deux côtés : teintes
# **0 à 34** (du rouge au doré pâle) et saturation **≥ 95**. Mesuré, la
# contre-épreuve : remettre l'ancien ORANGE à sa place fait retomber le
# compte de 63 à **58** icônes (Régénération ×2, Immortalité ×2, et
# l'icône 7 de Viktor n°2).
#
# LE PLANCHER DE CLARTÉ RESTE À 120, et il a de la marge : le bandeau
# noir est à V ≈ 26-38 sous les glyphes. Balayé de 110 à 130, le compte
# ne bouge pas (63/63, zéro fausse) — c'est un plateau, pas un réglage.
CHAUD = ((0, 95, 120), (34, 255, 255))
BLEU = ((88, 100, 120), (112, 255, 255))

# MAGENTA (20/11/2026). Mesuré sur les quatre icônes du Pâle orchestre
# (06SI009), étiquetées par Ewan : Éphémère sort à la teinte 144,
# Sanctification à 95, Challenger à 16, Surpuissance à 19. Les deux
# premières familles dataient du 14/11 et laissaient le sablier
# d'Éphémère dans l'angle mort — une icône VUE et jamais comptée.
MAGENTA = ((132, 90, 110), (156, 255, 255))

# BLANC : ce qui est CLAIR et SANS COULEUR. Les deux icônes concernées
# ont une saturation médiane de 17 ; on coupe à 60, très loin au-dessus
# d'elles et très loin sous les glyphes colorés (S ≥ 95 pour le plus
# pâle d'entre eux, la tour dorée). Le plancher de clarté est plus haut
# que celui des familles de teinte (150) parce qu'un gris sombre n'a
# rien qui le distingue du bandeau.
BLANC = ((0, 0, 150), (180, 60, 255))

# L'ORDRE N'A AUCUNE IMPORTANCE : on en fait une union.
FAMILLES = (CHAUD, BLEU, MAGENTA, BLANC)


def _masque_icones(image) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masque = None
    for basse, haute in FAMILLES:
        bande = cv2.inRange(hsv, np.array(basse), np.array(haute))
        masque = bande if masque is None else cv2.bitwise_or(masque, bande)
    return masque


def _est_un_glyphe(largeur: int, hauteur: int, aire: int) -> bool:
    """Une taille et une aire de glyphe plausibles — le SEUL juge de
    taille, qu'on l'applique à un fragment brut ou à une boîte recollée."""
    return (ICONE_COTE_MIN <= largeur <= ICONE_COTE_MAX
            and ICONE_COTE_MIN <= hauteur <= ICONE_COTE_MAX
            and aire >= ICONE_AIRE_MIN)


def _boite_recollee(fragments: list) -> tuple:
    """Boîte englobante d'un groupe de fragments, et la somme de leurs
    aires (une aire de pixels ne se moyenne pas, elle s'additionne)."""
    x0 = min(f[0] for f in fragments)
    y0 = min(f[1] for f in fragments)
    x1 = max(f[0] + f[2] for f in fragments)
    y1 = max(f[1] + f[3] for f in fragments)
    aire = sum(f[4] for f in fragments)
    return (x0, y0, x1 - x0, y1 - y0, aire)


def _ecart(a: tuple, b: tuple) -> tuple:
    """Les deux écarts (en x, en y) entre deux boîtes ; zéro sur un axe
    si elles s'y touchent ou s'y chevauchent."""
    ex = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0)
    ey = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0)
    return ex, ey


def _voisins(a: tuple, b: tuple, pose) -> bool:
    """
    Ces deux fragments sont-ils assez proches pour appartenir au même
    glyphe ?

    Voir `ECART_X` / `ECART_Y` : la barre range ses icônes
    horizontalement, donc un trou en LARGEUR sépare, un trou en HAUTEUR
    non — SAUF quand l'un des deux est trop petit pour être une icône.
    Un débris ne peut pas être « l'autre icône » que le trou sépare, et
    `_est_un_glyphe` est le seul juge de taille du module : voir
    `ECART_X_DEBRIS` pour la mesure et pour le cas qu'elle répare.

    `pose(fragment)` dit si ce fragment est POSÉ SUR LE BANDEAU. Un
    débris qui ne l'est pas n'appartient à aucune icône — c'est du décor
    de carte, et il ne franchit rien.
    """
    ex, ey = _ecart(a, b)
    if ey > ECART_Y:
        return False
    if ex <= ECART_X:
        return True
    if ex > ECART_X_DEBRIS:
        return False
    return any(not _est_un_glyphe(z[2], z[3], z[4]) and pose(z) for z in (a, b))


def _trop_grand(largeur: int, hauteur: int) -> bool:
    """Cette boîte dépasse-t-elle la taille d'un glyphe ? C'est le seul
    plafond de l'agglomération : il empêche le liseré du plateau (87×24
    px sous Kennen) et la tache de bordure de Firespitter (40×30) de
    servir de pont entre des icônes qu'ils touchent sans leur
    appartenir, et il sépare les deux rangées d'une barre tassée."""
    return largeur > ICONE_COTE_MAX or hauteur > ICONE_COTE_MAX


def _grouper(fragments: list, pose=None) -> list:
    """
    Agglomère les fragments d'un même glyphe : la plus PETITE union
    d'abord, et jamais une boîte plus grande qu'un glyphe.

    L'ordre compte, et il est la moitié du correctif du 21/11/2026 : sur
    le Pâle orchestre, les quatre morceaux de Surpuissance se touchent
    (écart 0) alors que Surpuissance et Challenger sont séparés de 1 px.
    En reformant Surpuissance d'abord (26×24), le couple qu'elle forme
    ensuite avec Challenger (51 px de large) est refusé par la taille.
    Fusionner dans l'ordre de lecture aurait soudé les deux et perdu
    l'une des deux icônes.

    LA CLÉ EST LA SURFACE DE L'UNION, PAS L'ÉCART (21/11/2026 au soir),
    et c'est l'autre moitié du correctif de l'aile d'Augmentation. Les
    deux ordres rendent le MÊME découpage sur les 21 unités tant que
    `ECART_X` est absolu — mesuré, aucune boîte ne bouge. Dès qu'un
    débris a le droit de franchir un pixel (`ECART_X_DEBRIS`), ils
    divergent, et seule la surface donne la bonne réponse : l'aile de
    l'Augmentation de Kennen chevauche la BOÎTE du cercle rouge (donc
    écart nul) alors qu'elle est à un pixel du corps de sa propre icône,
    et « l'écart d'abord » la donnait au cercle. Les deux unions se
    mesurent pourtant sans ambiguïté — **308 px avec l'Augmentation
    contre 624 avec la Régénération**.

    ET LA SURFACE D'ABORD EST CE QUI PROTÈGE VOLONTÉ : chaque glyphe se
    reforme de ses propres morceaux qui se TOUCHENT (unions petites)
    avant qu'un débris puisse franchir quoi que ce soit, si bien que
    l'œil barré de Viktor n°1 est déjà un glyphe entier — donc plus un
    débris — quand la question de la flamme voisine se pose.

    `pose(fragment)` est passée à `_voisins` ; sans elle, aucun débris
    ne franchit de trou (un appel sans fond lu reste donc l'ancien
    comportement, strictement).
    """
    if pose is None:
        pose = lambda _fragment: False
    paquets = [[f] for f in fragments]
    boites = list(fragments)
    while True:
        meilleur = None
        for i in range(len(paquets)):
            for j in range(i + 1, len(paquets)):
                if not _voisins(boites[i], boites[j], pose):
                    continue
                union = _boite_recollee([boites[i], boites[j]])
                if _trop_grand(union[2], union[3]):
                    continue
                # Clé totalement ordonnée : surface de l'union, puis
                # écart, puis position — deux exécutions sur la même
                # image doivent rendre le même découpage.
                ex, ey = _ecart(boites[i], boites[j])
                cle = (union[2] * union[3], ex + ey, union[0], union[1])
                if meilleur is None or cle < meilleur[0]:
                    meilleur = (cle, i, j, union)
        if meilleur is None:
            return paquets
        _, i, j, union = meilleur
        paquets[i] = paquets[i] + paquets[j]
        boites[i] = union
        del paquets[j]
        del boites[j]


def _touche_un_bord_lateral(largeur_bande: int, boite: tuple) -> bool:
    """
    Cette boîte est-elle collée au bord GAUCHE ou DROIT de la bande lue ?

    LA BANDE EST PLUS LARGE QUE LE BANDEAU, ET C'EST MESURÉ. On lit
    `BARRE_DEMI_LARGEUR` = 80 px de part et d'autre du centre quand le
    bandeau noir, lui, ne fait que 65 (Pâle orchestre) à 71 px (Kennen,
    Viktor) de demi-largeur : au moins 9 px de marge de chaque côté. Ce
    qui touche le bord est donc HORS du bandeau — c'est la lueur bleue du
    plateau, et sous Kennen (capture `victor`) elle formait une boîte de
    15×20 à dx +65, de taille parfaitement plausible et cernée de noir,
    donc invisible à `_pose_sur_le_bandeau`. C'était le seul faux positif
    des quatre captures.

    Rien de RÉEL ne touche ce bord : sur les 63 icônes étiquetées, la
    boîte la plus à gauche commence à x = 16 et la plus à droite finit à
    x = 140, pour une bande large de 160 — 16 et 20 px de marge.

    On ne resserre PAS `BARRE_DEMI_LARGEUR` à la place : mesuré le
    21/11/2026, 72 / 68 / 66 / 64 font disparaître ce halo mais en créent
    un autre sur Swain. Un garde qui échange un faux positif contre un
    autre n'en est pas un.
    """
    x, _, largeur, _, _ = boite
    return x <= 0 or x + largeur >= largeur_bande


def _pose_sur_le_bandeau(fond, boite: tuple) -> bool:
    """
    Cette boîte est-elle posée sur le bandeau NOIR ?

    On lit la luminosité médiane de l'anneau de `MARGE_ANNEAU` px qui
    l'entoure : une icône est cernée de noir, un éclat d'illustration
    est cerné d'illustration. Voir `FOND_SOMBRE_MAX` pour les mesures.
    """
    x, y, largeur, hauteur, _ = boite
    hauteur_bande, largeur_bande = fond.shape
    gx0, gy0 = max(0, x - MARGE_ANNEAU), max(0, y - MARGE_ANNEAU)
    gx1 = min(largeur_bande, x + largeur + MARGE_ANNEAU)
    gy1 = min(hauteur_bande, y + hauteur + MARGE_ANNEAU)
    autour = fond[gy0:gy1, gx0:gx1]
    dehors = np.ones(autour.shape, bool)
    dehors[y - gy0:y - gy0 + hauteur, x - gx0:x - gx0 + largeur] = False
    valeurs = autour[dehors]
    return bool(valeurs.size) and float(np.median(valeurs)) < FOND_SOMBRE_MAX


def _icones_et_glyphes(image, centre: tuple, adverse: bool = False):
    """
    Calcule EN UNE SEULE FOIS les boîtes d'icônes de la bande et, pour
    chacune, SES pixels : `(boites, glyphes)`, alignés terme à terme.

    ⚠ LE MASQUE EST PARTAGÉ, LES GLYPHES NE LE SONT PAS (21/11/2026 au
    soir). Cette fonction rendait le masque de toute la bande, et ses
    appelants le TRANCHAIENT à la boîte — si bien qu'un glyphe emportait
    tout ce qui passait dans son rectangle, y compris les pixels du
    VOISIN. Sur une barre tassée en quinconce les boîtes se chevauchent
    pour de bon : `augment2` (Viktor n°1, 21×18) et `deathless` (23×18)
    se croisent sur x 67..74 × y 17..21, et le gabarit d'Augmentation
    récolté là portait **31 px de la tour d'Immortalité sur 177, soit
    18 %**. Mesuré sur les 21 unités : **11 des 63 crops** portaient des
    pixels d'un AUTRE glyphe retenu, deux massivement (`augment2` 18 %,
    `niveau3` 4 %, `fury` 4 %).
    ET LA PREUVE OFFERTE EN FAVEUR DE CES GABARITS ÉTAIT AUTO-CONFIRMANTE
    — « 0.977 entre les deux Viktor » : les deux Viktor ont le même
    voisin au même endroit, donc la même pollution. C'est exactement
    l'auto-cohérence sans vérité que `cut_defi` a payée le 08/11.
    On découpe donc chaque glyphe dans les LABELS DE SON GROUPE.

    CE QUI RESTE DANS LE CROP, ET C'EST VOULU : les MIETTES sous
    `FRAGMENT_AIRE_MIN` ne sont dans aucun groupe, donc elles sortent
    aussi. C'est cohérent avec l'aire que le module juge déjà —
    `_boite_recollee` somme les aires des FRAGMENTS, pas les pixels du
    rectangle : Frappe rapide pesait 63 px pour le juge de taille et 79
    dans son gabarit. Les deux ne disent plus deux choses différentes.

    `adverse=True` lit la bande EN HAUT de la carte : chez l'adversaire,
    statistiques et barre de mots-clés sont inversées (21/11/2026).

    `adverse=True` lit la bande EN HAUT de la carte : chez l'adversaire,
    statistiques et barre de mots-clés sont inversées (21/11/2026).

    SOURCE UNIQUE DE LA SEGMENTATION (20/11/2026, revue de la tâche 3).
    `icones()` segmentait, puis `decouper()` segmentait DE NOUVEAU (en
    rappelant `icones()`) pour chaque glyphe demandé : `identifier()`
    payait donc le masque + `connectedComponentsWithStats` + le recollage
    par colonnes UNE fois pour compter, puis ENCORE une fois PAR GLYPHE
    rien que pour en retrouver les boîtes, plus une troisième segmentation
    du masque (strictement identique, même bande) pour en extraire les
    pixels. Pour 4 icônes : 1 + 4 + 4 = 9 segmentations au lieu d'1.

    MESURÉ (tâche 3, 20/11/2026), 5 unités, gabarits en cache (régime réel
    d'un combat) : 49.8-50.9 ms AVANT ce correctif, 43.1-43.6 ms APRÈS —
    voir `game_state.lire_les_mots_cles` pour le chiffrage complet (à
    froid aussi) et sa mise en regard des ~2200 ms d'un instantané.
    `icones()` et `decouper()` restent la même INTERFACE (même signature,
    même contrat, y compris leurs cas limites) ; ils délèguent ici pour ne
    plus JAMAIS pouvoir diverger entre deux chemins de découpe.

    Rend `([], None)` dès qu'on ne peut pas lire — pas d'image, cadre hors
    écran, forme inattendue. Même règle que `stun.mouvement` et
    `bilan.juger` : ne rien pouvoir lire n'est pas un verdict.
    """
    forme = getattr(image, "shape", None)
    if forme is None or len(forme) < 3:
        return [], None
    cx, cy = int(centre[0]), int(centre[1])
    h, w = forme[0], forme[1]
    x0, x1 = cx - BARRE_DEMI_LARGEUR, cx + BARRE_DEMI_LARGEUR
    if adverse:
        y0, y1 = cy - BARRE_ADVERSE_DY_HAUT, cy - BARRE_ADVERSE_DY_BAS
    else:
        y0, y1 = cy + BARRE_DY_HAUT, cy + BARRE_DY_BAS
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return [], None

    bande = image[y0:y1, x0:x1]
    masque = _masque_icones(bande)
    # La luminosité de la bande, pour `_pose_sur_le_bandeau` : calculée
    # UNE fois ici, comme le masque — deux conversions HSV de la même
    # sous-image finiraient par diverger.
    fond = cv2.cvtColor(bande, cv2.COLOR_BGR2HSV)[:, :, 2]
    nombre, etiquettes, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    # ON NE FILTRE PAS LES FRAGMENTS TROP GRANDS ICI, ET C'EST MESURÉ :
    # l'agglomération refuse déjà toute union qui dépasse un glyphe, donc
    # un fragment déjà trop grand ne peut fusionner avec rien et finit
    # seul, refusé par `_est_un_glyphe`. Les écarter en tête ne change
    # AUCUN compte sur les quatre captures témoins — un garde de plus
    # sans gain mesuré est un garde de trop.
    etiquette_de = {}
    fragments = []
    for i in range(1, nombre):
        if stats[i][4] < FRAGMENT_AIRE_MIN:
            continue
        fragment = tuple(int(v) for v in stats[i])
        fragments.append(fragment)
        # Deux fragments peuvent avoir la MÊME boîte et la même aire sans
        # être le même objet : on retient donc une LISTE d'étiquettes par
        # clé, et on la consomme dans l'ordre.
        etiquette_de.setdefault(fragment, []).append(i)

    largeur_bande = fond.shape[1]

    def retenue(boite):
        return (_pose_sur_le_bandeau(fond, boite)
                and not _touche_un_bord_lateral(largeur_bande, boite))

    def glyphe_de(boite, groupe, rangs):
        """Les pixels de CE glyphe, et d'aucun autre : on ne garde dans
        le rectangle que les étiquettes des fragments du groupe."""
        x, y, largeur, hauteur, _ = boite
        fenetre = etiquettes[y:y + hauteur, x:x + largeur]
        a_nous = np.isin(fenetre, rangs)
        return (a_nous.astype(np.uint8) * 255)

    trouvees = []
    for groupe in _grouper(fragments, lambda f: _pose_sur_le_bandeau(fond, f)):
        rangs = [etiquette_de[f].pop(0) for f in groupe]
        boite = _boite_recollee(groupe)
        if _est_un_glyphe(boite[2], boite[3], boite[4]):
            # Le groupe ENTIER forme un glyphe plausible : recollé.
            if retenue(boite):
                trouvees.append((boite, glyphe_de(boite, groupe, rangs)))
        elif len(groupe) > 1:
            # Recollé, le groupe n'a pas la taille d'un glyphe — il reste
            # trop pauvre (des débris). On refuse la fusion et on rejuge
            # chaque fragment pour ce qu'il est, seul.
            for fragment, rang in zip(groupe, rangs):
                if (_est_un_glyphe(fragment[2], fragment[3], fragment[4])
                        and retenue(fragment)):
                    trouvees.append((fragment, glyphe_de(fragment, [fragment],
                                                         [rang])))
    trouvees.sort(key=lambda t: t[0][0])
    return [b for b, _ in trouvees], [g for _, g in trouvees]


def icones(image, centre: tuple, adverse: bool = False) -> list:
    """
    Les icônes de mots-clés lues sous cette unité : [(x, y, w, h, aire)].

    `adverse=True` pour une unité de l'ADVERSAIRE : sa barre est en haut
    de la carte, pas en bas.

    Rend une liste VIDE dès qu'on ne peut pas lire — pas d'image, cadre
    hors écran, forme inattendue. Même règle que `stun.mouvement` et
    `bilan.juger` : ne rien pouvoir lire n'est pas un verdict.
    """
    boites, _ = _icones_et_glyphes(image, centre, adverse)
    return boites


def decouper(image, centre: tuple, index: int, adverse: bool = False):
    """
    Le masque 0/255 du glyphe d'indice `index`, ou None.

    CE SONT LES PIXELS DE CE GLYPHE SEUL : depuis le 21/11/2026 au soir,
    `_icones_et_glyphes` découpe dans les étiquettes du groupe et non
    dans le masque partagé de la bande — un gabarit n'emporte plus un
    morceau de son voisin (cf. `augment2`, 31 px sur 177).
    """
    boites, glyphes = _icones_et_glyphes(image, centre, adverse)
    if not glyphes or not 0 <= index < len(boites):
        return None
    return glyphes[index]


def cut_icone(capture: str, centre: tuple, index: int, nom: str,
              adverse: bool = False) -> str:
    """
    Récolte un gabarit depuis une capture ÉTIQUETÉE.

    ON NE RÉCOLTE QUE CE QU'UN HUMAIN A NOMMÉ. Deviner l'identité d'une
    icône serait inventer — c'est ce que ce module refusait de faire
    depuis le 14/11, et il avait raison. L'ordre vient d'Ewan, pas de
    l'image.

    ⚠⚠ L'INDEX N'EST PAS UNE POSITION DANS LA BARRE, ET SUR LES DEUX
    CAPTURES DU 21/11 IL NE DÉSIGNE PAS LA MÊME ICÔNE (mesuré le
    21/11/2026). Le lexique d'Ewan nomme les icônes PAR POSITION
    (« Kennen n°1 = niveau, n°2 = Frappe rapide… ») ; `cut-icone`, lui,
    prend le rang de la boîte dans ce que la segmentation a RENDU. Les
    deux ne coïncident que si toutes les icônes sortent, et elles ne
    sortent pas. Le MÊME Kennen, sur les deux captures du 21/11 :

        kennen_20261121_034644  dx  -62  -33  -20   +2  +37
        victor_20261121_035752  dx       -32  -19   +3  +38  +65

    (`dx` = le `x` qu'imprime le rapport MOINS `BARRE_DEMI_LARGEUR`,
    c'est-à-dire la position relative au centre de la carte.)
    Les quatre communes s'alignent à 1 px près — c'est bien la même
    barre, au même endroit. Mais l'index 0 vaut **dx -62** sur la
    première capture et **dx -32** sur la seconde, et la seconde liste
    se termine par un **+65 (15×20, teinte 104) qui est le HALO BLEU du
    plateau, pas une icône** : il déborde la demi-largeur du bandeau
    (71 px sous Kennen) que `BARRE_DEMI_LARGEUR` = 80 laisse entrer.
    Récolter à l'index sur ces captures-là graverait donc un gabarit
    FAUX — c'est le piège de `cut_defi` (08/11) par un autre chemin, et
    il est pire ici, parce que rien ne rougirait : une icône mal nommée
    se reconnaîtrait elle-même.

    CE QU'IL FAUT FAIRE À LA PLACE : lire d'abord le rapport
    (`python mots_cles_ecran.py <capture.png>`), qui imprime le `x` de
    CHAQUE boîte, apparier ces `x` à la position nommée par Ewan, et ne
    récolter que les index ainsi confirmés — en vérifiant sur les DEUX
    captures quand la carte y figure deux fois.

    Le masque écrit est celui que `identifier` relira : on découpe PAR LE
    CHEMIN DE LECTURE, jamais par un seuil choisi à part. Le piège est
    documenté (`cut_defi`, 08/11) — une police découpée autrement ne se
    reconnaît pas elle-même (IoU 0.83, marge sous le plancher).

    ⚠⚠ ET UN GABARIT QUI MAIGRIT PERD LE DROIT DE NOMMER (21/11, en
    re-revue). `COTE_MIN_POUR_NOMMER` = 11 porte sur le PLUS PETIT CÔTÉ
    du PNG écrit ici. Trois gabarits sont déjà à un ou deux pixels de ce
    plancher — `quickstrike` et `aura` à 12, `fearsome` à 13 — et leur
    petit côté est la HAUTEUR, c'est-à-dire exactement ce que la bande
    rogne : leurs trois boîtes finissent sur la dernière ligne
    (y + h = 35). Une ligne de moins et `quickstrike`, un mot-clé que
    `keywords.py` chiffre, devient MUET sur ses deux positions.

    DONC : APRÈS TOUTE RE-RÉCOLTE, relancer
    `test_un_mot_cle_modelise_ne_devient_pas_muet` — c'est lui qui
    rougit, pas la reconnaissance, qui continuerait de marcher en
    rendant `None`.
    """
    image = cv2.imread(capture)
    if image is None:
        raise SystemExit(f"capture introuvable : {capture}")
    masque = decouper(image, centre, index, adverse)
    if masque is None or masque.size == 0:
        raise SystemExit(f"aucune icône d'indice {index} sous {centre}")
    chemin = Path(__file__).parent / "mots_cles" / f"{nom}.png"
    chemin.parent.mkdir(exist_ok=True)
    rgba = np.zeros((*masque.shape, 4), np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = masque
    cv2.imwrite(str(chemin), rgba)
    return str(chemin)


def porte_des_mots_cles(image, centre: tuple, adverse: bool = False) -> bool:
    """
    Cette unité affiche-t-elle AU MOINS un mot-clé ?

    C'EST LE VERDICT LE MIEUX ÉTABLI : juste sur les VINGT ET UNE unités
    de plateau des quatre captures témoins — seize porteuses, cinq
    vierges dont quatre ADVERSES.

    IL N'EST PLUS LE MOINS CHER (21/11/2026) : il passe désormais par
    l'IDENTIFICATION, parce que deux des dessins de la barre ne sont pas
    des mots-clés — l'indicateur de niveau et l'effet de zone (voir
    `AFFICHAGE`). Les compter faisait déclarer « a reçu un mot-clé » tout
    champion monté de niveau sans mot-clé imprimé. On n'écarte que ce
    qui est POSITIVEMENT reconnu comme un dessin d'affichage : un glyphe
    inconnu compte toujours, sans quoi les mots-clés sans gabarit
    deviendraient invisibles.
    """
    return any(_est_un_mot_cle(f)
               for f in familles_lues(image, centre, adverse))


def a_recu_un_mot_cle(image, carte) -> bool:
    """
    Cette unité porte-t-elle un mot-clé qu'elle n'a pas IMPRIMÉ ?

    Vrai seulement dans le cas SANS AMBIGUÏTÉ : la carte n'a aucun
    mot-clé dans `card_sets` et une icône s'affiche quand même. Observé
    sur Legion Saboteur (01NX040, `keywords=[]`, une icône bleue).

    LE FAUX POSITIF DU NIVEAU EST CORRIGÉ (21/11/2026 au soir). La
    PREMIÈRE place de la barre n'est pas un mot-clé : c'est
    l'indicateur de NIVEAU (fait de jeu d'Ewan), et la deuxième place
    des Viktor est un « effet de zone » que la base nomme elle-même
    `AuraVisualFakeKeyword` (48 cartes, plus `LandmarkVisualOnly` sur
    133 autres). Ils sont désormais RÉCOLTÉS (`AFFICHAGE`), reconnus, et
    écartés par `_est_un_mot_cle` : un champion monté de niveau sans
    mot-clé imprimé n'est plus déclaré renforcé. Un glyphe INCONNU, lui,
    compte toujours.

    ⚠ ET L'ICÔNE DE LEGION SABOTEUR N'EST PAS UN « EFFET DE ZONE » —
    c'est le contraire qui était écrit ici, et c'est une supposition
    qui n'avait jamais été mesurée. Relevé le 21/11/2026 au soir sur la
    capture du 14/11 : son unique icône fait **19×24**, teinte 95
    (cyan), et elle note **0.219** contre le gabarit `aura`. Le module
    rend `None` pour elle (son meilleur candidat, `spirit` à 0.576, est
    une famille MUETTE — voir `COTE_MIN_POUR_NOMMER`), donc elle COMPTE,
    et `a_recu_un_mot_cle` reste vrai sur elle.
    **C'EST LE CAS FONDATEUR DU MODULE** : si une variante d'`aura`
    venait un jour à le couvrir, l'exclusion éteindrait l'exemple même
    qui justifie la fonction. `test_un_mot_cle_accorde_se_voit` est le
    filet ; le jour où il rougit, c'est la récolte qu'il faut regarder,
    pas lui.

    ON NE COMPARE PAS LES NOMBRES au-delà de ça. Même là où le compte
    est exact (les cinq Pâle orchestre du 20/11), « 5 icônes pour 1
    mot-clé imprimé » ne prouverait pas quatre dons : l'écran ne montre
    que ce qu'il DESSINE, et rien ne dit qu'un mot-clé imprimé ait
    toujours son icône.
    """
    imprimes = tuple(getattr(carte, "keywords", ()) or ())
    refs = tuple(getattr(carte, "keyword_refs", ()) or ())
    if imprimes or refs:
        return False
    # LE CÔTÉ VIENT DE LA CARTE, pas d'un argument de plus : `BoardCard`
    # le porte (`local`), et une carte sans ce champ est à nous — c'est
    # le comportement d'avant le 21/11/2026.
    return porte_des_mots_cles(image, carte.center,
                               adverse=not getattr(carte, "local", True))


def cartes_renforcees(image, cartes: Iterable) -> set:
    """Les CardID des unités qui affichent un mot-clé non imprimé."""
    trouvees = set()
    for carte in cartes or ():
        card_id = getattr(carte, "card_id", -1)
        if card_id is None or card_id < 0:
            continue
        if a_recu_un_mot_cle(image, carte):
            trouvees.add(card_id)
    return trouvees


# LES SEUILS SONT MESURÉS POUR CE PROBLÈME, pas hérités (20/11/2026).
# `digits.CONFIDENT_SCORE` (0.72) a été calibré pour les CHIFFRES : dix
# classes de formes voisines. Ici les pictogrammes sont très distincts et
# c'est la MARGE qui discrimine.
#
# MESURE À JOUR (20/11/2026 au soir, DEUX variantes par mot-clé — les 21
# vrais positifs sont les 5 Pâle orchestre × 4 icônes plus le Challenger
# imprimé de Firespitter ; les 5 étrangers sont les icônes de Swain) :
#
#     vrais positifs    score 0.710 à 1.000 | marge 0.317 à 0.640
#     glyphes étrangers score <= 0.409      | marge <= 0.073
#
# La plage de marge « 0.119 à 0.630 » qui figurait ici datait d'AVANT le
# second gabarit par mot-clé : elle annonçait 0.019 de sécurité là où il
# y en a 0.217. Mesure refaite, ancienne plage supprimée.
#
# Le score reste indispensable : seul lui peut refuser un mot-clé dont on
# n'a AUCUN gabarit. 0.60 laisse 0.11 sous le pire vrai positif et 0.19
# au-dessus du meilleur étranger ; 0.10 laisse 0.217 sous la pire vraie
# marge et 0.027 au-dessus de la meilleure marge étrangère. Les DEUX
# planchers doivent être franchis.
#
# ÉCRITS EN DUR, ET C'EST VOULU. Ce sont aujourd'hui les mêmes valeurs
# que `digits.MIN_SCORE` / `digits.CONFIDENT_MARGIN` — mais prises à DEUX
# paliers différents de `digits` (le palier « candidat » pour l'un, le
# palier « sûr » pour l'autre), un assemblage qui n'a de sens que pour
# les chiffres. Les rebrancher ferait bouger EN SILENCE le plancher qui
# empêche d'inventer un Challenger le jour où quelqu'un règle `digits`
# (trois fois en novembre). Ne pas rebrancher : mesurer ici.
SCORE_SUR = 0.60
MARGE_SURE = 0.10

# UN GABARIT TROP PETIT POUR ÊTRE DISTINCTIF N'A PAS LE DROIT DE NOMMER
# (21/11/2026 au soir). Il reste dans le lot — il concourt, donc il
# consomme de la marge comme n'importe quelle autre famille — mais s'il
# arrive EN TÊTE, on ne rend rien.
#
# POURQUOI. `spirit` (la flamme de Volonté) fait **10×13 pour 75 px**,
# exactement sur le plancher `ICONE_COTE_MIN` : normalisé à 32 px et
# égalisé en trait, c'est un pâté générique qui ressemble à tout. Mesuré
# sur les 15 glyphes ÉTRANGERS des quatre captures (ceux dont AUCUN
# gabarit n'existe), il arrive EN TÊTE de huit d'entre eux, et il met la
# bibliothèque à **0.024 du plancher de score** (0.576 sur Legion
# Saboteur) tandis que le plancher de MARGE est franchi par deux d'entre
# eux (0.112 et 0.120 contre 0.10).
#
# ⚠ CE QU'IL ACHÈTE EST DE LA DISTANCE, PAS UNE ERREUR CORRIGÉE, et il
# faut le dire honnêtement : **aucun des 15 étrangers ne franchit LES
# DEUX planchers aujourd'hui**, même sans ce garde — le plancher de
# score les arrête tous (le pire est à 0.576 pour 0.60). Les deux qui
# franchissent la marge sont justement des glyphes dont la tête est
# `spirit`. Ce plancher-ci ne répare donc pas un faux positif observé :
# il rend au module la marge de sécurité que la doctrine lui demande
# (« les DEUX planchers doivent être franchis », et un seul tenait).
#
# LA FENÊTRE EST MESURÉE, et le plancher porte sur le PLUS PETIT CÔTÉ du
# gabarit (ni son aire — `quickstrike` ne pèse que 63 px et reste
# distinctif — ni son nom) :
#
#   côté minimal pour NOMMER      10 |    11 |    12 |    13 |    14
#   positions nommées / 44        44 |    43 |    43 |    39 |    38
#   pire score étranger        0.576 | 0.504 | 0.504 | 0.504 | 0.504
#   pire marge étrangère       0.120 | 0.075 | 0.075 | 0.075 | 0.075
#   distance au score         +0.024 |+0.096 |+0.096 |+0.096 |+0.096
#   distance à la marge       -0.020 |+0.025 |+0.025 |+0.025 |+0.025
#   familles muettes          aucune | spirit| spirit| + aura| + fearsome
#                                    |       |       | +quick|
#                                    |       |       | strike|
#
# ⚠ CETTE TABLE A ÉTÉ FAUSSE UNE PREMIÈRE FOIS, ET C'EST LA RÈGLE QUI
# AVAIT ÉTÉ MAL LUE (corrigé le 21/11 en re-revue). Elle annonçait 35/44
# et neuf positions perdues à 13, avec `niveau` parmi les muettes :
# c'était supposer qu'une famille devient muette dès qu'UNE de ses
# variantes passe sous le plancher. `_peut_nommer` dit le contraire —
# elle est muette quand TOUTES le sont, exactement comme le score d'une
# famille est celui de sa MEILLEURE variante (`digits.load_variants`).
# `niveau` a trois variantes, 23×12, 20×24 et 20×27 : elle ne tombe pas à
# 13. Les vrais chiffres sont ceux du tableau ci-dessus — **39/44 et
# CINQ positions perdues**. Même défaut que celui qu'on venait de
# corriger sur `FOND_SOMBRE_MAX` : un nombre écrit comme mesuré qui ne
# mesure pas ce que la fonction fait.
#
# 11 et 12 donnent le MÊME résultat et ne coûtent que `spirit` ; 13
# n'améliore AUCUNE des deux distances et fait tomber `aura` et
# `quickstrike` avec, soit CINQ positions nommées au lieu d'une. On
# prend le plus permissif des deux, comme pour `ICONE_COTE_MAX`.
#
# CE QUE ÇA COÛTE, EXACTEMENT : **une position nommée sur 44**, la
# Volonté de Viktor n°1 — qui redevient un glyphe COMPTÉ mais non nommé,
# donc `porte_des_mots_cles` la compte toujours (un inconnu compte).
# `Spirit` n'est pas l'un des mots-clés que `keywords.py` modélise, donc
# aucun calcul du bot ne change. Et aucun seuil n'a été desserré pour
# compenser : `SCORE_SUR` et `MARGE_SURE` sont ceux du 20/11.
#
# ⚠⚠ FRAGILITÉ LATENTE — CE PLANCHER EST À DEUX PIXELS D'UN MOT-CLÉ
# MODÉLISÉ (mesuré le 21/11 en re-revue). Le plus petit côté des
# gabarits qui NOMMENT encore :
#
#       spirit        10   MUETTE
#       aura          12   (dessin d'affichage)
#       quickstrike   12   ⚠ MODÉLISÉ (`keywords.strikes_before_blocker`)
#       fearsome      13   ⚠ MODÉLISÉ (légalité d'un blocage)
#       elusive       15   puis 15, 16, 16, 18, 18, 19, 20, 20, 22, 24, 24
#
# `quickstrike` est découpé dans la boîte (47, 23, 15, 12), dont le bas
# — y + h = 35 — EST le bas de la bande : c'est un glyphe ROGNÉ (voir
# « LA BANDE COUPE LES GLYPHES » en tête de module). Une ligne de plus
# rognée à la prochaine re-récolte le met à 11, deux lignes à 10, et il
# devient MUET sur ses deux positions — un mot-clé qui change une
# décision de combat, éteint par un effet de bord de la géométrie de la
# bande. `aura` (38, 23, 21, 12) et `fearsome` (105, 22, 16, 13) sont
# dans le même cas, boîte collée au même bord.
#
# LE FILET EST UN TEST, PAS UN COMMENTAIRE :
# `test_mots_cles_ecran.test_un_mot_cle_modelise_ne_devient_pas_muet`
# compare les familles muettes à `keywords.MODELLED_KEYWORDS` et rougit
# aussi bien si un gabarit maigrit que si l'on montait ce plancher à 13.
COTE_MIN_POUR_NOMMER = 11

_GABARITS: dict = {}

# Radical de fichier -> mot-clé. `BoardCard.has` normalise la casse et la
# ponctuation ; on écrit donc la forme que `keywords.py` INTERROGE, qui
# est la seule consommatrice de `keywords_lus`. Elle diffère du libellé
# affiché sur un seul de ces quatorze : `card_sets` écrit « Quick Attack »
# dans `keywords` et « QuickStrike » dans `keywordRefs`, et les deux NE
# se normalisent PAS pareil (« quickattack » contre « quickstrike »).
# `keywords.strikes_before_blocker` demande « QuickStrike » : c'est donc
# cette forme-là qu'on pose, et une carte qui l'imprime la porte déjà par
# sa référence, si bien que le journal dira « porte bien son QuickStrike
# imprimé » plutôt que d'inventer un don.
#
# LES DIX DERNIERS VIENNENT DU LEXIQUE D'EWAN (21/11/2026), qui nomme une
# POSITION dans la barre et jamais une ressemblance — Kennen (05BC058)
# n°2 à n°6, Viktor (03PZ003) n°3 à n°6 sur ses deux exemplaires. Six
# d'entre eux changent un calcul que le bot sait déjà faire :
# `QuickStrike`, `Elusive`, `Deathless`, `Impact`, `Fearsome` et
# `Overwhelm`. Les autres ne sont pas modélisés, et les récolter sert
# quand même : c'est ce qui permet de COMPTER honnêtement les icônes
# qu'on ne sait pas encore nommer.
NOMS = {
    "ephemeral": "Ephemeral",
    "hallowed": "Hallowed",
    "challenger": "Challenger",
    "overwhelm": "Overwhelm",
    "quickstrike": "QuickStrike",
    "elusive": "Elusive",
    "spellshield": "SpellShield",
    "regeneration": "Regeneration",
    "augment": "Augment",
    "deathless": "Deathless",
    "impact": "Impact",
    "spirit": "Spirit",
    "fury": "Fury",
    "fearsome": "Fearsome",
}

# CE QUE LA BARRE DESSINE ET QUI N'EST PAS UN MOT-CLÉ (21/11/2026).
#
# La PREMIÈRE place de la barre est l'indicateur de NIVEAU du champion
# (fait de jeu d'Ewan) et la deuxième place des Viktor est un « effet de
# zone » que la base nomme elle-même `AuraVisualFakeKeyword` — 48 cartes,
# plus `LandmarkVisualOnly` sur 133 autres : Riot les DÉCLARE comme des
# mots-clés d'affichage. On s'appuie donc sur la donnée, pas sur une
# liste devinée, exactement comme « on compte les marqueurs, on ne
# reconnaît pas des sorts ».
#
# ON LES RÉCOLTE POUR LES ÉCARTER, et il faut les deux moitiés : sans
# gabarit, ces glyphes resteraient des inconnus COMPTÉS, et
# `a_recu_un_mot_cle` déclarerait « cette carte a reçu un mot-clé » pour
# TOUT CHAMPION MONTÉ DE NIVEAU sans mot-clé imprimé — un faux positif
# sur la seule promesse que cette fonction porte. Les charger en classes
# de comparaison sert aussi à autre chose : une classe de plus empêche
# un glyphe d'affichage d'aller se faire prendre pour un mot-clé.
#
# LE NIVEAU N'A PAS UNE SEULE FORME : chez Kennen c'est un chevron
# orange, chez Viktor un disque bleu barré d'un éclair. Les deux sont
# nommés « niveau du champion » par Ewan, et ce sont donc deux VARIANTES
# d'une même famille — le score d'une famille étant celui de sa meilleure
# variante, comme dans `digits.load_variants`.
AFFICHAGE = {
    "niveau": "indicateur de niveau",
    "aura": "effet de zone (AuraVisualFakeKeyword)",
}


def _est_un_mot_cle(famille) -> bool:
    """Ce glyphe compte-t-il comme un mot-clé ?

    Un glyphe NON reconnu (famille None) compte : on ne connaît qu'une
    poignée de formes, et refuser ce qu'on ne sait pas nommer reviendrait
    à déclarer vierge toute unité portant un mot-clé sans gabarit. Seul
    un glyphe POSITIVEMENT reconnu comme un dessin d'affichage est
    écarté."""
    return famille not in AFFICHAGE


def _peut_nommer(variantes) -> bool:
    """Cette famille a-t-elle au moins un gabarit assez grand pour
    NOMMER ? Voir `COTE_MIN_POUR_NOMMER` : un pâté de 10 px de côté
    ressemble à tout, et il mangeait la marge de sécurité du module."""
    return any(min(v.shape) >= COTE_MIN_POUR_NOMMER for v in variantes)


def _famille(radical: str) -> str:
    """« hallowed2 » appartient à la famille « hallowed ». Même rôle que
    `digits._family` : plusieurs variantes d'un même mot-clé."""
    return radical.rstrip("0123456789") or radical


def charger_gabarits() -> dict:
    """
    FAMILLE -> ses VARIANTES, masques 0/1. L'ALPHA porte la forme, comme
    `chiffres/` — un glyphe opaque ne vaudrait rien.

    La clé est le RADICAL de fichier (« challenger », « niveau »), pas le
    mot-clé : depuis le 21/11/2026 le lot contient aussi les deux dessins
    d'AFFICHAGE, qui n'ont pas de mot-clé à porter et qu'il faut pourtant
    reconnaître pour les écarter. `NOMS` fait la traduction au moment où
    `identifier` rend son tuple, et lui seul.

    Le score d'une famille est celui de sa MEILLEURE variante ; la marge
    se mesure entre deux familles DIFFÉRENTES, jamais entre deux variantes
    de la même. C'est mot pour mot la règle de `digits.match_glyph`.

    RIEN N'EST ÉCARTÉ EN SILENCE (20/11/2026). Un PNG ré-enregistré par un
    éditeur qui aplatit l'alpha disparaissait du lot sans un mot, et
    `identifier` cessait de rendre ce mot-clé-là : c'est littéralement le
    défaut du 08/11 (« le gabarit était écrit, puis IGNORÉ au chargement,
    sans un mot »). Les deux refus sont désormais journalisés.

    ET ON N'ACCEPTE QUE LES FAMILLES CONNUES (`NOMS` et `AFFICHAGE`).
    N'importe quel PNG à alpha déposé là devenait une classe candidate :
    il ne peut rien gagner (son nom n'est ni un mot-clé ni un dessin
    d'affichage) mais il CONSOMME de la marge, et peut faire passer un
    vrai glyphe sous le plancher.
    """
    if _GABARITS:
        return _GABARITS
    dossier = Path(__file__).parent / "mots_cles"
    for png in sorted(dossier.glob("*.png")):
        brut = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
        if brut is None or brut.ndim < 3 or brut.shape[2] < 4:
            LOGGER.warning(
                "Gabarit de mot-clé ignoré, pas de canal alpha : %s — "
                "l'alpha porte la forme, un glyphe opaque ne vaut rien.",
                png.name,
            )
            continue
        famille = _famille(png.stem)
        if famille not in NOMS and famille not in AFFICHAGE:
            LOGGER.warning(
                "Gabarit de mot-clé ignoré, famille inconnue : %s "
                "(familles connues : %s) — une classe de plus consomme de "
                "la marge sans pouvoir rien nommer.",
                png.name, ", ".join(sorted((*NOMS, *AFFICHAGE))),
            )
            continue
        _GABARITS.setdefault(famille, []).append(
            (brut[:, :, 3] >= 128).astype(np.uint8))
    return _GABARITS


def _score(glyphe, gabarit) -> float:
    """Le chemin de `digits.match_glyph`, appliqué à nos pictogrammes."""
    forme = digits._normalized((glyphe > 0).astype(np.uint8))
    cible = digits._normalized((gabarit > 0).astype(np.uint8))
    return digits._iou(digits._equalize_stroke(forme, float(cible.mean())), cible)


def familles_lues(image, centre: tuple, adverse: bool = False) -> list:
    """
    La FAMILLE de chaque icône lue sous cette unité, ou None, dans
    l'ordre de lecture — UNE entrée par boîte rendue par `icones()`.

    SOURCE UNIQUE DE L'IDENTIFICATION (21/11/2026) : `identifier`,
    `porte_des_mots_cles` et le rapport de diagnostic s'y branchent tous
    les trois. Avant, le rapport REDEVINAIT l'alignement entre les boîtes
    et le tuple d'`identifier` (« si les deux listes ont la même
    longueur ») et renonçait dès qu'un glyphe n'était pas nommé — deux
    implémentations du même test finissent toujours par diverger, et
    c'est alors le diagnostic qui ment.

    Un glyphe sous les paliers rend None : on ne rend jamais une valeur
    approchée.

    Appelle `_icones_et_glyphes` UNE SEULE FOIS (boîtes + pixels de
    chaque glyphe) — au lieu de rappeler `icones()` pour compter et
    `decouper()` pour chaque indice, qui redemandait la même
    segmentation à chaque fois. Voir `_icones_et_glyphes` pour le
    chiffrage et la mesure du coût avant/après (tâche 3, 20/11/2026).
    """
    gabarits = charger_gabarits()
    # UNE MARGE A BESOIN DE DEUX CANDIDATS. Avec une seule famille
    # chargée, `second` vaudrait 0.0, la marge vaudrait le score, et le
    # second plancher ne filtrerait plus rien — alors que tout le module
    # repose sur « les DEUX planchers doivent être franchis ». Ça ne peut
    # pas arriver aujourd'hui (seize familles), mais rien ne le disait :
    # un `mots_cles/` à moitié vidé aurait fait inventer un mot-clé.
    if len(gabarits) < 2:
        if gabarits:
            LOGGER.warning(
                "Identification des mots-clés désactivée : %d famille(s) de "
                "gabarits chargée(s), il en faut au moins 2 pour qu'une "
                "marge veuille dire quelque chose.", len(gabarits),
            )
        return []
    _, glyphes = _icones_et_glyphes(image, centre, adverse)
    if not glyphes:
        return []
    lues = []
    for glyphe in glyphes:
        if glyphe is None or glyphe.size == 0:
            lues.append(None)
            continue
        notes = sorted(((max(_score(glyphe, v) for v in variantes), famille)
                        for famille, variantes in gabarits.items()), reverse=True)
        meilleur, second = notes[0], notes[1]
        sure = (meilleur[0] >= SCORE_SUR
                and meilleur[0] - second[0] >= MARGE_SURE)
        # UNE FAMILLE TROP PETITE CONCOURT MAIS NE NOMME PAS : elle reste
        # dans le classement — donc dans la marge du second — et si elle
        # arrive en tête, on ne rend rien. Voir `COTE_MIN_POUR_NOMMER`.
        if sure and not _peut_nommer(gabarits[meilleur[1]]):
            sure = False
        lues.append(meilleur[1] if sure else None)
    return lues


def identifier(image, centre: tuple, adverse: bool = False) -> tuple:
    """
    Les mots-clés SÛREMENT lus sous cette unité, dans l'ordre de lecture.

    `adverse=True` pour une unité de l'ADVERSAIRE : sa barre est en haut
    de la carte (21/11/2026).

    Un glyphe sous les paliers n'est PAS identifié : il est absent du
    tuple. Ne jamais rendre une valeur approchée.

    ET LES DESSINS D'AFFICHAGE N'EN SONT PAS (21/11/2026) : l'indicateur
    de niveau et l'effet de zone occupent une place dans la barre, sont
    reconnus par leur gabarit, et sont ÉCARTÉS ici. Voir `AFFICHAGE`.
    """
    return tuple(NOMS[f] for f in familles_lues(image, centre, adverse)
                 if f in NOMS)


# ============================================================
# LA PLANCHE — tous les gabarits, chacun sous son nom
# ============================================================
PLANCHE = (Path(__file__).parent / "captures_reference" / "mots_cles"
           / "planche_gabarits.png")

# Hauteur du bandeau de légende sous chaque vignette, et grossissement.
# Les glyphes font 10 à 32 px de côté : à l'échelle 1 la planche est
# illisible, à 4 elle tient encore dans un écran.
_PLANCHE_ZOOM = 4
_PLANCHE_LEGENDE = 30
_PLANCHE_MARGE = 6
_PLANCHE_COLONNES = 8


def planche(chemin=None) -> str:
    """
    Écrit une image de TOUS les gabarits, chacun avec son nom dessous.

    DEMANDÉE PAR EWAN LE 21/11/2026, et ce n'est pas de la décoration :
    c'est le seul moyen de vérifier d'un coup d'œil qu'aucun gabarit
    n'est MAL ÉTIQUETÉ. `cut_icone` prend un INDEX pendant que le lexique
    nomme une POSITION ; si les deux se décalent, rien ne rougit — une
    icône mal nommée se reconnaît parfaitement elle-même. C'est le piège
    de `cut_defi` (08/11) par un autre chemin, et la planche est la
    contre-épreuve qu'on peut montrer à celui qui a étiqueté.

    Une fonction du module, pas un script jetable : elle relit les PNG
    par le MÊME chemin que `charger_gabarits` (l'alpha porte la forme),
    donc ce qu'elle montre est exactement ce que `identifier` compare.

    Les légendes sont en ASCII : `cv2.putText` ne dispose que des polices
    Hershey, qui n'ont pas d'accents — un libellé accentué y sortirait
    troué. C'est le seul endroit du projet où le français cède, et il
    cède à une limite de la bibliothèque.
    """
    gabarits = charger_gabarits()
    vignettes = []
    for famille in sorted(gabarits):
        quoi = NOMS.get(famille) or "affichage"
        for rang, masque in enumerate(gabarits[famille], 1):
            vignettes.append((f"{famille}{rang if rang > 1 else ''}",
                              quoi, masque))
    if not vignettes:
        raise SystemExit("aucun gabarit à mettre en planche")

    zoom = _PLANCHE_ZOOM
    cases = [(m.shape[1] * zoom, m.shape[0] * zoom) for _, _, m in vignettes]
    case_l = max(l for l, _ in cases) + 2 * _PLANCHE_MARGE
    case_h = max(h for _, h in cases) + 2 * _PLANCHE_MARGE + _PLANCHE_LEGENDE
    colonnes = min(_PLANCHE_COLONNES, len(vignettes))
    lignes = (len(vignettes) + colonnes - 1) // colonnes
    image = np.zeros((lignes * case_h, colonnes * case_l, 3), np.uint8)

    for index, (etiquette, quoi, masque) in enumerate(vignettes):
        ligne, colonne = divmod(index, colonnes)
        x0, y0 = colonne * case_l, ligne * case_h
        cv2.rectangle(image, (x0, y0), (x0 + case_l - 1, y0 + case_h - 1),
                      (60, 60, 60), 1)
        grand = cv2.resize((masque > 0).astype(np.uint8) * 255, None,
                           fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        gx = x0 + (case_l - grand.shape[1]) // 2
        gy = y0 + _PLANCHE_MARGE
        image[gy:gy + grand.shape[0], gx:gx + grand.shape[1]] = \
            cv2.cvtColor(grand, cv2.COLOR_GRAY2BGR)
        base = y0 + case_h - _PLANCHE_LEGENDE + 12
        cv2.putText(image, etiquette, (x0 + 4, base),
                    cv2.FONT_HERSHEY_PLAIN, 0.9, (255, 255, 255), 1)
        couleur = (120, 200, 255) if quoi == "affichage" else (120, 255, 150)
        cv2.putText(image, quoi, (x0 + 4, base + 13),
                    cv2.FONT_HERSHEY_PLAIN, 0.9, couleur, 1)

    sortie = Path(chemin) if chemin else PLANCHE
    sortie.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(sortie), image)
    return str(sortie)


# ============================================================
# DIAGNOSTIC — « que lit-on sous chaque unité ? »
# ============================================================
# `champions.py <capture>`, `bilan.py <capture>` et `spells.py explain`
# ont tous leur point d'entrée ; celui-ci manquait, et `cut_icone` — le
# SEUL outil de récolte de gabarits — n'était atteignable que par
# `python -c`. C'est pourtant par lui que passeront les seize mots-clés
# qui n'en ont pas encore.
USAGE = """\
Que lit-on sous les unités d'un plateau ?

    python mots_cles_ecran.py                       écran en direct (API + capture)
    python mots_cles_ecran.py <capture.png>         une capture et sa trame .json appariée
    python mots_cles_ecran.py <capture.png> <x> <y> un centre d'unité donné à la main
    python mots_cles_ecran.py cut-icone <capture.png> <x> <y> <index> <nom>
    python mots_cles_ecran.py planche               la bibliothèque, en image

Ajouter `adverse` EN DERNIER ARGUMENT lit la barre en HAUT de la carte
— c'est là qu'elle est chez l'adversaire. Inutile avec une trame
appariée : le côté y est lu dans `LocalPlayer`.

    python mots_cles_ecran.py <capture.png> <x> <y> adverse
    python mots_cles_ecran.py cut-icone <capture.png> <x> <y> <index> <nom> adverse

`cut-icone` récolte un gabarit : l'INDEX est celui qu'affiche la
commande sans argument, le NOM est celui d'Ewan — on ne récolte que ce
qu'un humain a nommé. ⚠ L'index n'est PAS la position dans la barre et
ne désigne pas la même icône d'une capture à l'autre : lire
l'avertissement de `cut_icone` AVANT de récolter.\
"""


def unites_de_la_trame(trame: dict, window=None) -> list:
    """
    Les cartes d'une trame : [(CardCode, centre, à nous ?)].

    LE CÔTÉ EST DANS LA TRAME (`LocalPlayer`) : on ne le devine pas, et
    il décide de quel côté de la carte on va lire la barre.

    ON NE REFAIT PAS LE CLASSEMENT EN ZONES ICI. `game_state.group_by_zone`
    en est la source unique, et l'importer d'ici importerait une SECONDE
    COPIE de ce module-ci (ce fichier étant alors `__main__`) — le piège
    du 10/11. On rend donc TOUTES les cartes, main comprise : une carte
    en main n'a pas de barre d'icônes, elle sort à zéro, et le diagnostic
    le montre au lieu de la cacher.
    """
    import lor_api

    if window is None:
        ecran = (trame or {}).get("Screen") or {}
        window = lor_api.Window(0, 0, int(ecran.get("ScreenWidth") or 1920),
                                int(ecran.get("ScreenHeight") or 1080))
    unites = []
    for rect in (trame or {}).get("Rectangles") or ():
        if rect.get("CardCode") in (None, "face"):
            continue
        unites.append((rect["CardCode"], lor_api.rect_center_screen(rect, window),
                       bool(rect.get("LocalPlayer", True))))
    return unites


def _rapport(image, unites) -> None:
    """
    Ce que l'écran dit de chaque unité — boîtes comprises, parce que
    c'est leur INDEX que `cut-icone` demande.

    LA LIGNE D'UNE BOÎTE DIT CE QU'ELLE EST, et elle le tient de
    `familles_lues`, qui rend UNE entrée par boîte. L'ancien rapport
    réalignait le tuple d'`identifier` sur les boîtes « si les deux
    listes ont la même longueur », et renonçait à tout nommer dès qu'un
    seul glyphe passait sous les planchers : le diagnostic racontait
    alors autre chose que la décision.
    """
    for code, centre, local in unites:
        adverse = not local
        boites = icones(image, centre, adverse=adverse)
        familles = familles_lues(image, centre, adverse=adverse)
        cote = "à nous " if local else "ADVERSE"
        print(f"  {code:<12} {cote} centre {str(centre):<14} {len(boites)} icône(s)")
        for i, (x, y, w, h, aire) in enumerate(boites):
            famille = familles[i] if i < len(familles) else None
            if famille is None:
                quoi = "?"
            elif famille in NOMS:
                quoi = NOMS[famille]
            else:
                quoi = f"{famille} (pas un mot-clé)"
            print(f"       [{i}] x={x:<4} y={y:<4} {w}×{h} (aire {aire})   {quoi}")


def main(argv=None) -> int:
    # Ce rapport imprime des « × » et des accents : redirigé dans un
    # fichier ou un tube, Python retombe sur cp1252 et MEURT dessus. Cf.
    # `sortie_utf8.py`, point unique de la parade — on l'applique AVANT
    # la première impression, comme `game_state.main` et `combat.main`.
    import sortie_utf8
    sortie_utf8.appliquer()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    adverse = bool(argv) and argv[-1] == "adverse"
    if adverse:
        argv = argv[:-1]

    if argv and argv[0] == "planche":
        # LA PLANCHE EST LA CONTRE-ÉPREUVE DE LA RÉCOLTE : on y relit
        # d'un coup d'œil que chaque gabarit porte le bon nom.
        print(planche(argv[1] if len(argv) > 1 else None))
        return 0

    if argv and argv[0] == "cut-icone":
        if len(argv) != 6:
            print(USAGE)
            return 1
        capture, x, y, index, nom = argv[1], *argv[2:6]
        print(cut_icone(capture, (int(x), int(y)), int(index), nom, adverse))
        return 0

    if argv:
        image = cv2.imread(argv[0])
        if image is None:
            print(f"Capture illisible : {argv[0]}")
            return 1
        if len(argv) >= 3:
            unites = [("(donné)", (int(argv[1]), int(argv[2])), not adverse)]
        else:
            # LA TRAME APPARIÉE, OU RIEN. Deviner où sont les unités sur
            # une capture, c'est exactement ce que ce module refuse de
            # faire des icônes.
            trame = Path(argv[0]).with_suffix(".json")
            if not trame.exists():
                print(f"Pas de trame appariée ({trame.name}) : donnez un centre "
                      f"d'unité à la main.\n\n{USAGE}")
                return 1
            import json
            unites = unites_de_la_trame(json.loads(trame.read_text("utf-8")))
    else:
        import lor_api
        trame = lor_api.get_positional_rectangles()
        image = lor_api.capture_screen_bgr()
        if image is None:
            print("Aucune capture d'écran.")
            return 1
        unites = unites_de_la_trame(trame, lor_api.get_window(trame))

    familles = charger_gabarits()
    # LE DÉCOMPTE DIT LA VÉRITÉ : deux des formes récoltées ne sont PAS
    # des mots-clés (cf. `AFFICHAGE`), et annoncer « 16 mots-clés » ferait
    # mentir la première ligne du diagnostic.
    affichage = sorted(f for f in familles if f in AFFICHAGE)
    mots = sorted(f for f in familles if f in NOMS)
    print(f"{len(unites)} carte(s), {len(mots)} mot(s)-clé(s) avec gabarit : "
          f"{', '.join(mots) or 'aucun'}")
    if affichage:
        print(f"{'':14}et {len(affichage)} dessin(s) d'affichage, reconnus "
              f"pour être écartés : {', '.join(affichage)}")
    _rapport(image, unites)
    return 0


if __name__ == "__main__":
    sys.exit(main())
