# Bot Legends of Runeterra — défis hebdomadaires

Automatisation du parcours PvE : navigation sur la carte d'aventure, puis
combat joué en autonomie.

Le combat n'est plus délégué à un bot externe. Tout est dans ce projet.

## Par où commencer

```powershell
python check.py
```

C'est la seule commande à retenir. Elle vérifie tout, puis **affiche la
liste ordonnée de ce qu'il te reste à faire** — calibrations manquantes
avec la commande exacte, puis l'échelle de lancement. Relance-la à chaque
fois que tu ne sais pas quoi faire ensuite.

Le reste de ce fichier explique le pourquoi ; `check.py` donne le quoi.

## Lancer les tests

`check.py` enchaîne deux choses de natures différentes :

- **hors ligne** — les cinq suites de tests. Ni jeu, ni souris, ni OCR :
  tout est simulé. Un échec signale une régression de la logique.
- **en ligne** — le diagnostic contre la partie ouverte : API, base de
  cartes, fenêtre, template du jeton, zones, mana, PV du nexus. Un échec
  signale un problème de branchement ou de calibration.
  Chaque contrôle raté dit **quoi faire**, pas seulement qu'il a raté.

```powershell
python check.py --offline    # sans le jeu
python check.py --live       # seulement le diagnostic
python check.py --skip-ocr   # évite de charger easyocr (~10 s de moins)
```

Les suites hors ligne ne dorment plus pour de vrai : le temps y est simulé
(`test_clock.py`). Les `sleep` d'animation d'`actions.py` n'attendaient
plus rien — ils coûtaient une trentaine de secondes à `test_actions.py`
pendant lesquelles `check.py`, qui capturait la sortie, semblait figé.
La progression s'affiche maintenant en direct, et une suite est déclarée
**bloquée** au bout de 120 s au lieu d'attendre indéfiniment.

## L'échelle de lancement

Monte les barreaux dans l'ordre. Chaque niveau suppose le précédent
validé, et **les trois premiers ne touchent jamais à la souris**.

| Commande                            | Ce que ça fait                      | Souris  |
| ----------------------------------- | ----------------------------------- | ------- |
| `python check.py`                   | tests + diagnostic                  | non     |
| `python journal.py`                 | taux de victoire par configuration  | non     |
| `python strategy.py`                | l'archétype du deck de la partie ouverte (`--traces` : ceux des traces) | non |
| `python game_state.py monitor`      | affiche la phase en direct          | non     |
| `python actions.py plan`            | ce qu'il jouerait ce tour           | non     |
| `python actions.py mulligan --plan` | ce qu'il garderait au mulligan      | non     |
| `python combat.py --plan`           | une itération de la boucle, à blanc | non     |
| `python replay.py list traces/...`  | relire une trace enregistrée (`--record`) | non |
| `python actions.py play`            | pose les cartes de ce tour          | **oui** |
| `python actions.py turn`            | poser → attaquer → finir le tour    | **oui** |
| `python challenges.py --plan`       | quel écran il reconnaît, là         | non     |
| `python combat.py`                  | un combat entier en autonomie       | **oui** |
| `python challenges.py --tentatives 1` | une aventure, du menu au boss     | **oui** |
| `python challenges.py`              | **toutes les tentatives, d'affilée**| **oui** |

Le premier essai en `--plan` pendant un combat que tu joues à la main
vaut mieux qu'un long débogage : la boucle annonce ses décisions sans
rien exécuter.

**Arrêt d'urgence : amène la souris dans un coin de l'écran.** Le
fail-safe de pyautogui lève une exception et tout s'arrête.

## Vitesse des gestes

`pyautogui.PAUSE` dort après **chaque** appel de la bibliothèque, et vaut
0.1 s par défaut. Un déplacement « humain » trace une courbe en dizaines
de `moveTo` : la pause invisible dominait donc tout le reste. Mesuré, un
seul glisser-déposer coûtait **11,2 s** et un clic **6,3 s** — d'où les
combats arrêtés à 900 s avec deux cartes posées.

`PAUSE` est maintenant à zéro et les temporisations sont explicites, avec
une échelle unique :

```powershell
python combat.py --speed 3          # plus nerveux
python actions.py --speed 1 turn    # les durées d'origine
python lor_automation.py --speed 2  # défaut
```

Au réglage par défaut (x2) : glisser-déposer **1,4 s**, clic **0,5 s**.

Monter plus haut se paie en fiabilité, et le symptôme n'est pas une erreur
mais une pose qui rate : `play_card` retente deux fois, donc une carte qui
n'arrive qu'à la seconde tentative dit que tu es allé trop loin. Trois
attentes gardent un plancher que la vitesse ne franchit pas — le survol
avant la saisie (0,25 s, le temps que la carte finisse de s'agrandir) et
les deux temps de dépôt (0,12 s). Ce sont elles qui rendent le geste
correct ; le reste n'est que du trajet.

## Calibration

À faire une fois, ou après un changement de résolution.

```powershell
python game_state.py inspect          # chaque carte tombe-t-elle dans la bonne zone ?
python game_state.py calibrate-zones  # ancrer les bandes sur la géométrie du plateau
python game_state.py vision           # seuils de couleur de l'orbe de tour
python mana.py --crops                # zones du cadran de mana et des PV
```

`calibrate-zones` mérite un mot : `ZONE_BANDS` est exprimée en fraction
de la hauteur de fenêtre, ce qui suppose que le plateau occupe toujours
la même proportion de l'écran — faux dès que le rapport d'aspect change.
Les deux nexus, eux, encadrent le plateau et sont donnés par l'API. En
enregistrant leur écartement une fois, dans une configuration où
`inspect` est correct, les bandes suivent ensuite la géométrie réelle,
y compris à une autre résolution.

Le **template du jeton d'attaque** se génère en deux commandes, pendant
que tu tiens le jeton :

```powershell
python game_state.py snap avec
python game_state.py cut-token    # entoure l'épée à la souris
```

Les **PV des deux nexus** s'apprennent en encadrant les deux chiffres,
pendant un combat :

```powershell
python mana.py --calibrate-nexus
```

La zone n'est pas enregistrée en coordonnées d'écran mais en fractions du
**rectangle du nexus**, que l'API donne pour les deux camps. Une seule
calibration couvre donc les deux côtés et survit à un changement de
résolution — contrairement à une zone en dur, qui ne vaut que pour un
côté et une taille d'écran. Sans elle, notre nexus reste lu via la zone
historique et celui d'en face reste inconnu.

La **zone d'annulation** : depuis le 02/09/2026 le bot sort d'un mode
ciblage par un **clic droit**, qui n'interagit avec rien — le point n'a
donc plus besoin d'être vide, mais on garde le point calibré comme
emplacement, et l'ancien clic gauche sur zone vide reste disponible en
repli (`actions.CANCEL_WITH_LEFT_CLICK = True`) :

```powershell
python actions.py cancel            # montre le point actuel
python actions.py cancel --calibrate  # en désigner un autre
```

La **gemme de mana** s'encadre sur une carte en main, pendant un combat :

```powershell
python actions.py cost --calibrate
```

Elle sert à lire le coût **réellement affiché** sur chaque carte de la
main, plutôt que le coût imprimé dans `card_sets`. Ce n'est pas la même
chose dès qu'un effet entre en jeu : une carte réduite à 1 reste à 6 dans
la base, et le bot passait son tour sans la jouer. Le principe est le
même que pour l'attaque et les PV — **l'écran fait foi, la base de cartes
n'est qu'un repli**. Un coût illisible retombe silencieusement sur la
valeur imprimée.

Pour vérifier ce que la gemme donne, ou pour désactiver la lecture :

```powershell
python actions.py plan                # les coûts lus apparaissent en tête
python actions.py why --read-costs    # écran contre card_sets, carte par carte
python actions.py plan --base-costs   # décider sur les coûts imprimés
python combat.py --base-costs         # idem pour un combat entier
```

Le **bouton de validation du mulligan** s'apprend d'un clic, pendant un
écran de mulligan :

```powershell
python actions.py mulligan --calibrate
```

Les calibrations mesurées sur ta machine vivent dans `calibration.json`
et dans `assets/attack_token.png` — pas dans le code, donc une mise à jour
du projet ne les écrase pas.

## Architecture

Une brique par question, et les dépendances vont toujours vers le bas.

```
challenges.py        LA SESSION : une tentative après l'autre
  navigate.py        carte d'aventure (templates), et où l'on se trouve
  lor_battle.py      pont navigation -> combat
    combat.py        boucle autonome : aiguillage phase -> action
      actions.py     DÉCISIONS : poser, attaquer, bloquer, annuler
        gestures.py  la souris : move, click, right_click, drag, vitesse
        keywords.py  qui meurt dans un duel, et ce qui passe au nexus
        spells.py    quel sort est jouable, et sur quelle cible
        mana.py      mana, mana de sort, PV du nexus (OCR)
        game_state.py phase, zones, cartes, stats réelles
        journal.py   résultats des combats, agrégés par configuration
        strategy.py  le profil du deck (archétype) et ce qu'il change
          lor_api.py  API locale, base de cartes, coordonnées, capture
          replay.py   enregistre / rejoue tout ce que lor_api a vu
```

`actions.py` ne touche plus pyautogui (05/09/2026) : les quatre gestes
vivent dans `gestures.py`, et `actions` les réimporte pour que
`actions.click`, `actions.drag`… restent les noms connus. Tout ce qui
DÉCIDE se rejoue donc hors ligne sur une trace (`replay.py`, ci-dessous)
ou dans les tests ; tout ce qui BOUGE tient en soixante lignes.

`lor_automation.py` reste le nom d'entrée historique : il appelle
`challenges.main()`, rien de plus.

`combat.py` ne contient **aucune** logique de jeu : seulement
l'aiguillage, la temporisation et l'arrêt propre. `challenges.py` non
plus : il compte les tentatives et décide quand s'arrêter.

## La boucle de session : quatre boucles, pas trois

Il y en avait trois, et il manquait la dernière :

| Boucle | Ce qu'elle répète |
|---|---|
| `combat.CombatLoop` | les phases d'**un** combat |
| `lor_battle.try_combat` | les « Réessayer » d'un **même** combat |
| `navigate.py` | les étapes d'**une** aventure |
| `challenges.py` | les **tentatives**, l'une après l'autre |

`lor_automation.py` faisait une aventure et s'arrêtait : il fallait le
relancer à la main pour chaque tentative. La boucle manquante tient à une
observation sur le jeu : **à la fin d'une aventure, on ne revient pas à
la carte du monde mais à l'écran de sélection du champion.** La tentative
suivante s'y enchaîne donc directement, sans repasser par la liste des
défis.

D'où deux fonctions nouvelles dans `navigate.py` :

- **`where_are_we()`** reconnaît l'écran courant — sélection du champion,
  bouton de lancement, liste des défis, carte du monde, ou carte
  d'aventure — et `STEPS_FROM` donne le chemin qui reste à parcourir
  depuis chacun. Une seule table :
  `enter_weekly_challenge` (le chemin long) et `enter_challenge_attempt`
  (depuis n'importe où) ne peuvent pas diverger.

  **L'ordre de détection suit les gestes, pas l'avancement.** Sur l'écran
  du champion, la vignette et le bouton de lancement sont visibles en même
  temps ; c'est la vignette qui est cherchée en premier, parce que le geste
  y est toujours le même : sélectionner le premier champion, *puis*
  lancer. Chercher le bouton d'abord ferait croire qu'il ne reste qu'un
  clic, sauterait la sélection, et — si le jeu exige un champion — le
  bouton ne répondrait pas : la boucle en conclurait « plus de tentative »
  et s'arrêterait sans avoir rien joué.
- **`Screen.ADVENTURE`** : si une aventure est **déjà ouverte** — le cas
  quand on met le jeu en place à la main puis qu'on lâche le bot — il n'y
  a rien à lancer. `enter_challenge_attempt` rend `RESUMED`, sans cliquer
  et sans dépenser de tentative, et la boucle reprend l'aventure. Ce cas
  est testé en **dernier** : ses repères de nœuds sont plusieurs, donc plus
  exposés au faux positif, alors que chaque écran d'entrée est signé par un
  bouton unique. Limite connue : la navigation repart du champion
  de soutien, donc elle rattrape une aventure qui vient de commencer, pas
  une aventure arrêtée au deuxième node — dans ce cas la boucle le dit et
  s'arrête au lieu de tourner.
- **`back_to_known_screen()`** ferme ce qui traîne — écrans de
  récompense, de fin de combat — jusqu'à retrouver un écran connu. Elle
  ne clique QUE des boutons qui ferment : jamais « Voyage », « Combat »
  ni « Réessayer ». C'est ce qui la rend sûre à appeler dans le doute,
  et un test vérifie cette liste.

**« Écran inconnu » n'est plus un diagnostic muet.** Quand aucun repère
ne correspond, `where_are_we` affiche le meilleur score de chacun :

```
Écran inconnu — meilleurs scores (seuil 0.80) : first_champion 0.61,
use_attempt 0.12, active_encounter absent, monthly_challenge 0.08, ...
```

0.61 veut dire « template à recadrer », 0.08 « ce n'est pas cet écran »,
et `absent` « le fichier n'est pas dans assets/ ». Les repères sont tous
jugés sur **une seule capture** : pendant une animation, deux captures
successives donnent deux réponses.

**La condition d'arrêt est donnée par le jeu, pas par un compteur.** Il
n'annonce pas « plus de tentative » : il cesse simplement d'afficher le
bouton de confirmation. C'est `Entry.NO_ATTEMPT_LEFT`, et c'est la fin
normale d'une session. Une **défaite n'arrête rien** — elle consomme une
tentative comme une victoire, donc la boucle repart.

Trois garde-fous en plus du coin de l'écran : la durée maximale de
session (`--duree`, trois heures par défaut), le plafond de tentatives
(`--tentatives`, facultatif), et **trois écrans inconnus d'affilée**.
Sans ce dernier, un écran sans template ferait cliquer dans le vide
pendant des heures.

Le garde-fou des tentatives brûlées distingue lui aussi deux cas sous le
même symptôme : trois **tentatives consommées** sans qu'une partie se
joue (« vérifie les templates, chaque essai coûte une tentative
hebdomadaire ») et trois **reprises** qui échouent (« termine l'aventure
à la main, ou reviens à la carte du monde »). Une reprise ne coûte rien,
et le message ne doit pas accuser à tort.

Le bilan distingue ce qu'un simple « échec » confondait :

```
3 tentative(s) en 47 min : 2 victoire(s), 1 défaite(s), 0 inachevée(s).
Arrêt : plus de tentative disponible
  tentative 1 : VICTOIRE en 14 min — partie terminée
  tentative 2 : DÉFAITE en 11 min — partie terminée
  tentative 3 : VICTOIRE en 22 min — partie terminée
```

Une tentative *inachevée* n'est ni une victoire ni une défaite : c'est
une navigation perdue avant le boss. Confondre les deux ferait chercher
un défaut de jeu là où il n'y a qu'un template à recadrer.

## Ce que le bot sait faire

- lire la phase : mulligan, tour adverse, notre tour, blocage, attaque
  déclarée, sort en attente, fin de partie ;
- poser l'unité la plus chère jouable, en respectant le mana et le banc,
  **au coût affiché à l'écran** et non au coût imprimé sur la carte ;
- attaquer **seulement quand l'échange est favorable** : il simule le
  blocage adverse, chiffre le bilan, et retire les attaquants qui coûtent
  plus qu'ils ne rapportent — sauf si l'attaque est **létale**, auquel cas
  le résultat prime sur la valeur et il fonce ;
- bloquer, en respectant Insaisissable / Redoutable / Ne peut pas
  bloquer, et se sacrifier seulement si le nexus ne survivrait pas ;
- **résoudre un duel mot-clé par mot-clé** — ordre des frappes, dégâts
  atténués, ce qui traverse le bloqueur (voir « Les mots-clés pèsent sur
  les décisions ») ;
- **défier** : tirer l'unité adverse de son choix en défense avec un
  Challenger, ou n'importe laquelle portant Vulnerable — en choisissant
  la cible qui rend l'attaque ENTIÈRE la meilleure, pas seulement le duel ;
- **jouer les échanges** (05/09/2026) : « Kill an ally to kill a unit »
  (Éboulement), « Deal 2 to an ally to Stun an enemy » (Diffusion
  astrale), « Recall an ally to deal 2 to anything »… Deux clics de
  genres différents, un COÛT puis une RÉCOMPENSE : il sacrifie la moins
  regrettable — ou, pour des dégâts, une unité qui y SURVIT — puis vise
  la meilleure cible, et ne lance que si ce qu'il gagne vaut ce qu'il
  perd (`spells.choose_trade_targets`). Un échange à perte attend un
  meilleur moment ; ce n'est plus une incapacité, c'est une décision ;
- **tenter toute carte de sa main qu'il peut payer** : plus aucun filtre
  de prudence ne l'écarte (voir « Les restrictions de cartes sont
  levées »). En `--prudent`, il s'en tient aux **72 %** de sorts
  collectionnables qu'il comprend (`python spells.py coverage` donne le
  chiffre à jour), les 28 % restants étant refusés pour une raison
  nommée ;
- **désigner une carte dans sa propre main** quand l'effet le demande —
  26 clauses de la base, dont le « Freljordian Lorekeeper » du défi
  Freljord ;
- **poser un équipement** sur sa plus grosse unité.

## Désigner une carte dans la main

« Play: Updraft 1 », « Discard a card to draw 1 », « Grant an ally in hand
+3|+3 » : le jeu attend un clic sur une carte de NOTRE MAIN, pas sur une
unité du plateau. Aucun marqueur de cible n'apparaît dans ces textes — ils
ne nomment rien à viser — si bien qu'ils passaient pour des effets
automatiques. La carte était posée, puis la partie restait figée sur un
choix que rien n'honorait.

Quatre questions, et il faut les quatre pour cliquer juste :

| Question | Exemple | Conséquence d'une erreur |
| --- | --- | --- |
| **combien** | « Updraft 2 » | un clic manquant, la partie reste en attente |
| **quel type** | « an ally in hand » veut une unité | cliquer un sort ne déclenche rien |
| **quel sens** | « Discard 1 » coûte, « Grant +3\|+3 » offre | on renforce la carte qu'on allait jeter |
| **elle s'en va ?** | « Discard 1 » la retire, « Create an exact copy of a spell in hand » la laisse | on croit le clic raté et on annule une pose réussie |

Le sens est la question qu'on oublie. Pour un coût, on donne la carte la
moins utile — d'abord celle que le bot ne jouera JAMAIS (absente de
card_sets, ou sort qu'il refuse de lancer : un fardeau pour lui, quoi
qu'elle vaille pour un joueur), puis la plus chère, celle qui dormirait le
plus longtemps en main. Pour un cadeau, l'ordre s'inverse : la moins
chère parmi les jouables, celle qu'on posera le plus tôt.

**La main n'est plus une main pendant la désignation.** La bande « hand »
de `ZONE_BANDS` ne couvre que les 3 % du bas de la fenêtre : une carte en
main dépasse sous le bord de l'écran, et c'est exactement ce qui la
distingue du banc. Or quand le jeu demande de désigner une carte de la
main, il la **remonte** pour la rendre cliquable — la courte animation où
les cartes concernées s'entourent de bleu. Leur ancre franchit alors la
borne et `classify_zone` les range dans « board » : `snapshot.hand` est
vide à cet instant précis.

D'où le partage, et c'est lui qui fait cliquer juste : on **décide** sur
l'état d'AVANT le dépôt, quand la main est encore une main ; on **vise**
par `CardID` dans l'état d'après, sans regarder la zone
(`actions.find_our_card`). Décider sur l'état d'après, c'était n'y voir
aucun sort, renoncer sans cliquer, puis annuler.

Entre deux désignations, les positions sont **relues ET stabilisées** : la
main se recentre dès qu'une carte la quitte, et le deuxième clic d'un
« Updraft 2 » calculé d'avance désignerait la voisine. Relire ne suffit
pas — une relecture prise EN COURS de recentrage rend des rectangles en
vol, et le clic part sur la position d'avant, quelques dizaines de pixels
plus à gauche. C'est ce qu'`actions.settled_snapshot` corrige, et c'est la
même leçon que `relocate_card` avait déjà servie à l'attaque et au
blocage : les deux horloges du plateau, encore.

La vérification ne compte pas les cartes, elle suit l'**identité** :
« Updraft 1 to draw 1 » rend une carte pour une, donc la main a la même
taille avant et après. C'est le `CardID` de la carte désignée qui dit si
le clic a pris — **quand elle est censée partir**. Dix-huit cartes de la
base ne consomment rien : Elora (« Create an exact copy of a spell in
hand ») en donne DEUX exemplaires, « Grant an ally in hand +3|+3 » laisse
la carte à sa place. Exiger leur départ, c'était conclure à l'échec d'un
clic réussi, puis annuler dans la foulée une pose déjà résolue. Le plan
porte donc la réponse (`spells.SpellPlan.pick_consumes`) ; quand la carte
reste, c'est l'arrivée de l'unité sur le plateau qui sert de preuve.

Enfin, une main qui n'offre **aucune** carte du type demandé écarte la
carte avant même le dépôt — restrictions levées ou non. Ce n'est pas de la
prudence mais un fait, du même ordre que le mana ou la place sur le banc :
Elora sans le moindre sort en main ne peut pas résoudre son pouvoir.

## Ce qu'il ne sait pas faire, et pourquoi

**Le mulligan demande une calibration, une seule fois.** Je n'ai jamais
vu cet écran, donc la position du bouton de validation est inconnue.
Pendant un écran de mulligan :

```powershell
python actions.py mulligan --calibrate
```

Une fenêtre s'ouvre sur la capture, tu cliques le bouton, c'est
enregistré dans `calibration.json`. La boucle l'automatise ensuite toute
seule. Tant que ce n'est pas fait, elle te laisse la main plutôt que de
cliquer sur une position devinée.

**Après le clic de validation, le bot attend trois secondes**
(`MULLIGAN_CONFIRM_WAIT`) avant de relire quoi que ce soit. Valider
déclenche une salve d'animations — les cartes rejetées partent, les
nouvelles arrivent, la main se recentre — pendant laquelle le client
annonce encore `MULLIGAN`. Relire trop tôt faisait conclure « le clic de
validation a raté » alors qu'il avait parfaitement pris. Monte cette
valeur si les animations sont plus lentes chez toi.

**Les mots-clés ACCORDÉS en cours de partie sont invisibles.** Une
Barrière donnée par un sort, un Vulnerable posé sur un ennemi, un
Frostbite : `/positional-rectangles` ne renvoie qu'un `CardCode`, donc le
bot ne voit que les mots-clés **imprimés** sur la carte. C'est la même
limite que les stats avant l'OCR, sauf qu'il n'y a pas de chiffre à lire
— seulement une icône. Le jour où une lecture à l'écran existe, c'est
`keywords.has()` **seule** qui change.

**Les sorts en réponse ne sont pas joués.** Quand un sort adverse est sur
la pile, le bot passe. Jouer un tour de combat au bon moment demande
d'évaluer le combat en cours, ce qui est une brique à part entière.

## Les restrictions de cartes sont levées

`actions.CARD_RESTRICTIONS` vaut **`False`** : le bot tente **toute carte
de sa main qu'il peut payer**. Tombent d'un coup le verrou `--spells`,
le refus des cartes absentes de `card_sets`, les sorts que `spells.py`
refusait par prudence (« you may », combat dirigé, contresort, effet
néfaste sur notre propre camp), les unités dont le pouvoir « Play: » n'a
pas de cible trouvable et les équipements sans allié à équiper.

**Six règles subsistent**, parce que ce ne sont pas des choix du bot
mais des faits — les enfreindre ne joue pas une carte de plus, ça ne fait
que promener la souris :

| Règle | Pourquoi elle survit |
| --- | --- |
| le **mana** | règle du jeu |
| la **place sur le banc** | règle du jeu |
| la **vitesse d'un sort** | règle du jeu : un sort lent ne part pas pendant un combat |
| **une carte à désigner en main doit exister** | Elora sans le moindre sort en main ne peut pas résoudre son pouvoir |
| **deux cibles à cliquer sur le plateau** | le bot n'en clique qu'une : `spells.SpellPlan.impossible` |
| **une fenêtre de choix dont on ne voit rien** | « Choose one », « Pick a follower. » nu, « Discard up to N » (validation non calibrée) : le choix est OBLIGATOIRE, rien ne le referme |

Les trois dernières ne sont pas de la prudence, c'est une **capacité qu'il
n'a pas**. Crumble (« Kill an ally to kill a unit ») le montre bien :
garder le premier marqueur et espérer, c'était sacrifier une de nos unités
puis laisser le client en attente du second clic — sans même annuler,
puisque l'annulation ne partait que si AUCUNE cible n'avait été cliquée.
74 sorts de la base sont dans ce cas.

La sixième a été ajoutée le **22/08/2026**, et elle corrige une erreur de
raisonnement : on croyait que lever les restrictions était sans danger
parce que `cancel_pending_action` rattraperait tout. C'est vrai d'un
ciblage, faux d'un **choix de carte** — celui-là est obligatoire, le clic
sur une zone vide ne le referme pas, le bouton de passe non plus, et la
partie ne repart jamais. La troisième colonne de `spells.REFUSALS` dit
maintenant, refus par refus, s'il s'agit de prudence (qui tombe) ou d'une
interface hors de portée (qui reste, dans les deux modes). **136 cartes**
de la base sont concernées ; le prix est connu et assumé : les huit armes
Darkin (« You may spend 8 mana to play me as... ») ne sont plus posées du
tout, alors qu'elles seraient jouables sous les 8 mana. Un équipement non
posé coûte un tempo, une partie figée coûte la tentative hebdomadaire.

**Ce que ça coûte.** Une carte que le bot ne sait pas résoudre est quand
même déposée, et le jeu attend alors une cible que personne ne cliquera.
Le filet est `cancel_pending_action` — un clic sur une zone vide remet la
carte en main, aucun mana dépensé — puis la carte est mise de côté pour le
tour. C'est du temps perdu, pas une partie perdue, à deux réserves près :

- un effet néfaste peut désormais viser nos propres unités. Dans ce cas
  la cible est la **plus petite** (Muraille 1|7 plutôt que Brute 5|5) ;
  attention, ça ne doit JAMAIS venir d'une lecture ratée — voir les
  préambules ci-dessous ;
- une fenêtre de choix ne se referme pas, elle : c'est pour ça qu'elle ne
  fait plus partie de ce que le bot tente (voir la sixième règle
  ci-dessus, et la section suivante pour le seul choix qu'il sait
  piloter).

### « Play me as A or B » : le seul choix piloté

**Les ailes et la vague** (04SI004, « Play: Play me as First Wave or Last
Wind ») a figé une partie le 22/08/2026. Le texte ne nomme aucune cible,
donc la carte passait pour une pose ordinaire : elle est déposée, le jeu
la remplace par ses deux versions au centre de l'écran, et plus rien
n'avance.

Ce choix-là est **pilotable** : les deux
versions sont **nommées dans le texte de la carte**. `spells` en tire un
plan (`Targeting.CHOICE`, `SpellPlan.options`), et
`actions.resolve_play_choice` les retrouve à l'écran **par leur nom** —
pas par leur position : la fenêtre n'est pas une zone du plateau, sa
hauteur ne veut rien dire. C'est le même endroit que les cartes du
mulligan, que l'API rapporte déjà.

**Laquelle il choisit** : celle qui **ne se paie pas**. Entre First Wave
(0|1) et Last Wind (3|3), c'est la 0|1 qui gagne, parce que la 3|3 exige
« To play me, kill an ally » — donc une interface de plus après le choix,
donc une occasion de plus de se figer. À prix égal, la plus grosse
l'emporte (`actions.version_rank`).

**Le pari, et comment le vérifier.** Tout repose sur le fait que l'API
rapporte cette fenêtre. Si elle ne le faisait pas, le journal le dirait
mot pour mot — « aucune version (First Wave ou Last Wind) reconnue à
l'écran (vu : ...) » — et la carte serait mise de côté pour le tour au
lieu de bloquer la partie. Pour trancher sans attendre la prochaine
partie, pendant que la fenêtre de choix est ouverte :

```powershell
python game_state.py inspect
```

### Les fenêtres de cartes : Manifest, Invoke, Predict, Tellstones (02/09/2026)

Le pari est gagné : Ewan a vu le bot cliquer dans les fenêtres de version.
L'API rapporte donc les cartes affichées au centre — et ça ouvre la famille
qu'on refusait faute d'en connaître le contenu : **Manifest**, **Invoke**,
**Predict**, « Pick 1 of 3 », « Pick a Moon Weapon to create in hand »,
« Pick a follower from the top 4 cards », les **Tellstones** (« Create a
Fleeting A, B, or C in hand »). **69 cartes** (`spells.CARD_WINDOWS`,
`SpellPlan.card_window`).

On ne sait toujours pas ce que la fenêtre montrera. On n'en a pas besoin :
les cartes proposées sont **celles à nous dont le `CardID` n'existait pas
avant la pose**, hors main et hors banc (`actions.offered_cards`). Le bot
prend celle qu'il **saura jouer** (`card_pick_rank` : pas une inconnue ni
un sort refusé, une unité plutôt qu'un sort, la plus grosse, la moins
chère), la clique, puis jette un coup d'œil : des cartes encore plus
neuves, c'est une **seconde fenêtre** (Sputtering Songspinner, Celestial
Trifecta).

**Quand elle s'ouvre** : à la *résolution*, donc après les interfaces du
lancement — la cible (« Predict. Give an enemy -2|-0 »), la désignation en
main (« Discard 1 to Manifest »). Tout de suite pour une unité ou un sort
Burst/Focus ; pour un Fast/Slow, **après la validation** et la réponse
adverse, d'où une attente plus longue (`CARD_WINDOW_SLOW_TIMEOUT`, 15 s).
Si rien n'apparaît, le journal dit ce qu'on a vu (« aucune fenêtre de
cartes (Manifest) reconnue à l'écran (vu : ...) ») et la carte est mise
de côté pour le tour.

Deux pièges évités par le classement : « Manifest a follower you can
afford » contient « a follower », qui n'est PAS une unité du plateau — la
clause de la fenêtre est retirée du texte avant de chercher la cible
(`spells.strip_card_window`) ; et le « or » des Tellstones n'annonce pas
une fenêtre de *versions* en plus. Restent dehors : « Pick a follower. »
nu (un clic de plateau dont on ne sait pas lire l'effet), « Choose one »,
et les textes entre guillemets (Concurrent Timelines), dont la fenêtre ne
s'ouvre pas à cette pose.

Les deux versions doivent apparaître dans le tableau, sous les codes
`04SI004T2` (First Wave) et `04SI004T1` (Last Wind).

### « +2|+0 or +0|+2 » : la variante avant la cible

**Choix capital** (Momentous Choice, 06IO034, « Give an ally +2|+0 or
+0|+2 this round ») ajoute une marche à la précédente : le jeu propose
les deux versions du sort **puis** demande l'allié. Le bot ne voyait que
la seconde étape et cliquait l'allié tout de suite — dans une fenêtre qui
n'écoutait pas (vu en jeu le 22/08/2026).

La variante se lit **à part de la cible** (`spells.stat_variants`,
`SpellPlan.variants`) : le plan dit toujours « BUFF sur allié », il
annonce en plus qu'une fenêtre s'ouvre avant. `play_spell` et `play_card`
enchaînent donc dans l'ordre imposé par le jeu — variante, puis cible.

**Les versions ne sont pas nommées dans le texte**, contrairement à « Play
me as A or B » : elles portent le **nom de la carte jouée** (06IO034T1 et
T2 s'appellent tous deux « Momentous Choice »). `resolve_variant_choice`
les retrouve donc sous ce nom-là et les départage par ce qu'elles
accordent — lu dans leur description pour un sort (« +2|+0 »), dans leurs
statistiques pour une unité (Scaled Snapper propose un 5|2 ou un 2|5).

**LA FAMILLE EST BIEN PLUS LARGE QUE LES CHIFFRES, et elle ne se lit pas
dans le texte.** Iula (05MT013, « Grant an ally Spellshield **or**
Overwhelm ») fait exactement la même chose sans qu'aucun nombre
n'apparaisse — signalé par Ewan juste après Choix capital. Recensement
sur ta base : **47 cartes** proposent deux effets au choix. On le sait
parce qu'elles ont des **jetons du même nom**, un par branche du « ou » —
le client a besoin d'une carte par option, et c'est la seule trace fiable
de la fenêtre. Seize d'entre elles sont de toute façon refusées avant
(deux cibles, choix inconnu) ; **trente et une** passent désormais par la
fenêtre.

**Et pourtant on ne peut pas trancher sur le texte** : « Deal 3 to a unit
**or** destroy a landmark » se joue en UN clic (la cible décide), « Give
an ally Barrier **or** SpellShield » en deux. 119 cartes jouables
contiennent un « ou ». D'où la règle, qui est celle de la navigation
appliquée aux cartes — *ce qui est proposé se découvre sur place, il ne
se devine pas* :

| ce que dit le texte | ce que fait le bot |
| --- | --- |
| `+X\|+0 or +0\|+X` — **certitude** | il attend la fenêtre ; ne pas la voir est une anomalie, le sort est abandonné |
| un « ou » quelconque — **possibilité** | il **jette un coup d'œil** (`VARIANT_GLANCE`, une lecture) ; s'il ne voit rien, il n'y avait pas de fenêtre et le ciblage suit son cours |
| « Play me as A or B » | ce n'est pas une variante : cette fenêtre-là **est** le choix, pilotée par `resolve_play_choice` |

**Laquelle il prend** (`variant_rank`), du plus contraignant au plus
fin — et les trois premiers critères ne parlent pas de force de jeu mais
de ce que le bot sait faire :

1. **exécutable** : la version est classée comme n'importe quelle carte ;
   celle qui demanderait deux clics passe derrière ;
2. **même cible que le plan** : le clic de ciblage est décidé sur le texte
   du parent et part juste après. « Deal 2 to a unit or deal 1 to two
   enemies » se règle là — la première version accepte le clic prévu, la
   seconde non ;
3. **mot-clé modélisé** : entre Spellshield et Overwhelm (Iula), on prend
   celui dont `keywords.resolve_duel` tient compte. Ce n'est pas « le
   meilleur », c'est le seul des deux que le bot sait chiffrer
   (`keywords.MODELLED_KEYWORDS`) ;
4. **statistiques** : la **force quand on a le jeton d'attaque** — elle se
   convertit en dégâts dès ce tour — les **points de vie sinon**. Jeton
   illisible vaut « on ne l'a pas », comme partout ailleurs.

**Un adjectif devant « ally » restreint la cible, il ne la supprime pas.**
« An Equipped ally strikes an enemy. » — Lame féroce (06NX034), vue en jeu
le 22/08/2026 : le bot cliquait **directement l'ennemi**, alors que le
sort demande d'abord un allié équipé. `\ban ally\b` ne reconnaissait pas
« an Equipped ally » ; il ne restait qu'un marqueur, et un sort à deux
clics passait pour un sort à un. Le marqueur accepte désormais jusqu'à
deux mots de qualificatif (« a damaged ally », « a battling ally »,
« a 1 cost ally »).

Treize cartes changent de verdict, dans les deux bons sens : quatre —
Lame féroce, Whirling Death et son jeton, Fish Fight — passent du mauvais
clic au **refus d'incapacité** (deux cibles, cf. le tableau ci-dessus) ;
neuf autres passent de « aucun clic », donc partie figée puis annulation,
à un clic sur l'allié qu'elles réclamaient depuis toujours (Take Heart,
Judgment, Playful Trickster, Buhru Leader...).

**Une seule exception, et elle va dans l'autre sens : « a random ally ».**
C'est le JEU qui choisit — compter un marqueur ferait cliquer une unité au
hasard sur un sort qui se résout tout seul (Mist's Call, Flashbomb Trap).
Le qualificatif `random` est donc explicitement exclu du motif.

**Une condition n'est ni une cible ni un effet.** « If an ally died this
round, deal 4 to a unit. » (Black Spear) : le « an ally » du début décrit
ce qui doit s'être produit. Compté comme marqueur il en faisait deux, donc
sans restrictions on gardait le premier — « allié ». Et le préambule
empêchait `^deal` de matcher, si bien que l'effet devenait « AUTRE », qui
n'est pas classé nuisible : un AUTRE sur notre camp vise notre plus petite
unité, un AUTRE sur « a unit » notre plus grosse. Le sort de dégâts se
retournait contre nous **deux fois plutôt qu'une**, et c'est exactement ce
qu'on a vu en jeu le 20/08/2026.

`spells.strip_preamble` retire donc, avant toute analyse, les
subordonnées de condition (`if`, `once`, `when`, `whenever`, `while`,
`unless`) et les remises (`I cost N less`) — en tête, au milieu ou en
queue de phrase. Quinze sorts changent de verdict, tous dans le bon sens :
« Kill the 2 Weakest enemies if an ally died this round » ne tue plus un
de nos alliés, Seismic Shard envoie ses 7 dégâts sur l'adversaire. Malgré
les 74 refus ajoutés plus haut, la couverture MONTE (68 % → 70 %).

**Pour revenir en arrière**, sans toucher au code :

```powershell
python combat.py --prudent
python actions.py plan --prudent
```

Ce mode reste la spécification testée : `test_actions.py` et
`test_spells.py` décrivent les deux comportements côte à côte
(`test_restrictions_levees`, `test_classement_sans_restrictions`). Et le
journal enregistre `restrictions=` à chaque combat, donc
`python journal.py` compare les deux modes sur les parties réelles plutôt
que sur une intuition.

## Les mots-clés pèsent sur les décisions

Les mots-clés étaient **lus** depuis toujours (`BoardCard.keywords`,
`card.has()`), mais six seulement pesaient sur une décision. Tout le
raisonnement de combat tenait en deux comparaisons — `attack >= health`
d'un côté, `attack < health` de l'autre — et ces deux comparaisons se
trompent sur **250 unités** de la base.

`keywords.py` remplace les deux comparaisons par une **résolution de
duel** : fonction pure, aucun clic, aucune lecture d'écran.

| Mot-clé | Unités | Ce que l'ancien calcul concluait |
|---|---|---|
| Frappe Rapide (`QuickStrike`) | 85 | un échange, alors qu'elle tue sans être touchée |
| Submersion (`Overwhelm`) | 107 | l'excédent, oui — mais sans Barrière ni Coriace |
| Impact | 34 | rien ne passe, alors qu'un point passe toujours |
| Coriace (`Tough`) | 26 | morte, alors qu'il lui reste 1 PV |
| Éphémère (`Ephemeral`) | 32 | une perte, alors que sa mort est gratuite |
| Vol d'âme (`Lifesteal`) | 17 | aucun soin compté |
| Barrière (`Barrier`) | 14 | une perte sèche, alors qu'elle ne prend rien |
| Frappe Double (`DoubleStrike`) | 7 | une seule frappe |
| Formidable | 7 | 0 d'attaque : **jamais engagée** |
| Sans-mort (`Deathless`) | 4 | une perte, alors qu'elle revient |
| Provocateur (`Challenger`) | 67 | lu pour la phase, jamais exploité |
| `Vulnerable` | granté | idem |

Les trois règles qui font le calcul, dans l'ordre où elles s'appliquent :

1. **Frappe Rapide et Frappe Double frappent d'abord, seules.** Le
   bloqueur ne riposte que s'il a survécu à cette frappe.
2. **Barrière annule l'instance entière puis se brise ; Coriace retire 1
   à chaque instance.** Dans cet ordre : une Barrière protège même d'une
   frappe qui aurait tué.
3. **Les frappes restantes sont simultanées de la riposte.** Une unité
   qui meurt frappe quand même.

Trois décisions changent concrètement :

- une **Formidable 0/7 attaque** (elle frappe avec ses PV, et l'ancien
  filtre `attack > 0` la laissait au banc toute la partie) et peut
  bloquer un Redoutable ;
- le bot **ne jette plus une unité** devant une Frappe Rapide qui la tue
  sans riposte — ce n'était pas un échange, c'était un cadeau ;
- une **Éphémère attaque et bloque librement** : elle meurt en fin de
  round de toute façon.

### Une Éphémère n'est pas seulement une mort gratuite

`death_cost` à zéro ne répond qu'à une question : *combien sa mort
coûte-t-elle ?* Trois décisions posaient l'autre — *sera-t-elle encore là
au round suivant ?* — et personne ne la posait. D'où
`keywords.dies_anyway`, vrai pour `Ephemeral` **seulement** : une
Sans-mort revient, affaiblie à 1 PV et sa résurrection dépensée, ce qui
est bon marché sans être gratuit.

- **La pose depuis la main** (`playable_cards`) trie par coût, puis par
  corpulence. Une Éphémère étant presque toujours surdimensionnée pour
  son coût, elle passait systématiquement devant un corps qui reste —
  alors que posée **sans le jeton d'attaque** elle meurt sans avoir
  frappé. À coût égal, la permanente passe maintenant devant ; avec le
  jeton, l'Éphémère retrouve sa place, puisqu'elle va justement attaquer.
  Jeton illisible = on suppose qu'on ne l'a pas.
- **Le blocage sacrificiel est gratuit** (`plan_blocks`). Se jeter devant
  un attaquant avec une Éphémère n'est pas un sacrifice : elle meurt en
  fin de round, et ce round est celui de l'adversaire. Une passe
  intermédiaire prend donc ces blocages **sans attendre la condition de
  létalité**. Et à qualité de blocage égale, `_blocker_preference` la
  **garde libre** quand le bloqueur survit — sinon elle prenait le bon
  blocage (sa mort gagnait l'égalité) et le gros attaquant passait sans
  rencontrer personne.
- **Le ciblage des sorts** (`spells.choose_target`). Un renfort ou un
  équipement visait « la plus grosse », c'est-à-dire souvent l'Éphémère :
  le bonus partait avec elle. Elle est maintenant la dernière receveuse —
  et la première sacrifiée quand un texte impose « Kill an ally ».

### Le parcours d'une carte suit l'ordre de la carte

Une carte de défi hebdomadaire a toujours l'une de ces deux formes :

```
champion de soutien -> nœud -> BOSS INTERMÉDIAIRE -> nœud -> BOSS FINAL
champion de soutien -> nœud -> nœud -> BOSS FINAL
```

`run_adventure` suit cet ordre, et les nœuds sont reconnus par les
**templates capturés à la main** — `support_champion_node.png`,
`secondary_enemy_node.png`, `final_boss.png`, et le dossier
`assets/nodes/` pour les nœuds ordinaires, dont l'aspect varie. La seule
question que la carte pose vraiment est « y a-t-il un boss
intermédiaire ? » : `has_mid_boss` y répond, et son absence est une
réponse, pas un échec.

Une détection par couleur — le triangle vert que le jeu dessine sous un
nœud accessible — a été essayée le 21/08/2026 et **retirée** : elle ne
tenait pas en jeu. Trois acquis de cette tentative sont restés, parce
qu'ils ne dépendent pas de la façon de repérer un nœud :

1. **On attend le nœud, on ne le regarde pas une fois** (`NODE_WAIT`,
   12 s, et deux réessais du geste). Après le choix du champion de soutien
   ou après un combat, la carte revient avec une animation : chercher une
   seule fois juste après le clic tombe sur un écran qui n'a pas encore
   ses nœuds. C'est ce qui manquait, et c'est indépendant du reste.
2. **Ce qu'un nœud propose se découvre à l'arrivée** (`resolve_arrival`) :
   bouton Combat, option d'événement puis validation, choix simple,
   fermeture. Un nœud est un combat parce que le jeu affiche « Combat ».
   La séquence du champion de soutien — option puis validation — ne vit
   plus qu'à cet endroit.

   **Et il se découvre EN UNE LECTURE, pas en quatre essais.** Les quatre
   repères sont mesurés sur la *même* capture (`read_arrival`), et leur
   score est écrit au journal à chaque arrivée. La version d'avant les
   essayait l'un après l'autre : le PREMIER template à franchir 0.80
   gagnait, même quand un autre était bien plus net. Le 22/08/2026, sur le
   nœud 1 d'une carte qui n'affichait **que** « Quitter »,
   `select_button.png` y a trouvé une fausse correspondance au-dessus du
   seuil ; essayé avant `quit_button`, il a été cliqué. « Sélectionner » et
   « Quitter » referment tous deux le panneau sans rien lancer : rien ne
   justifiait qu'un ordre écrit d'avance tranche à la place de ce qu'on
   voit, et c'est désormais **le meilleur score** qui décide. Quand les
   deux passent le seuil, l'écran est enregistré
   (`screenshots/arrivee_ambigue_*.png`) — c'est là que se cachent les
   fausses correspondances. Quand aucun ne passe, il l'est aussi
   (`arrivee_sans_bouton_*.png`) : « rien à faire » sans image n'apprend
   rien. Effet de bord bienvenu : un nœud sans combat coûtait douze
   secondes d'attente (quatre timeouts de trois), il en coûte au plus
   `ARRIVAL_TIMEOUT` = 6.
3. **Un échec enregistre l'écran** dans `screenshots/` et nomme l'étape :
   `champion de soutien introuvable`, `boss final introuvable`,
   `combat perdu (boss intermédiaire)`. « Aventure interrompue » sans
   précision ne servait à rien.

**Le panneau du champion de soutien s'affiche avant son contenu.** Mesuré
par Ewan le 22/08/2026 : après le « Voyage » vers ce nœud, il faut **deux
secondes de plus** pour que les champions apparaissent — le cadre et son
bouton, eux, sont déjà lisibles. Lire à cet instant, c'est valider un
panneau encore vide. `SUPPORT_CHAMPION_SETTLE` ajoute donc cette attente
**avant la première lecture** de ce nœud-là, et de lui seul : ailleurs le
panneau est complet dès qu'il est lisible, et deux secondes par nœud
seraient payées à chaque étape de chaque tentative. Son plancher vaut sa
borne basse, donc `--speed` ne la raccourcit pas : elle décrit le temps
que met le **client**, pas un geste humain qu'on peut accélérer. Si les
champions tardent davantage chez toi, c'est cette constante-là qu'il faut
monter (`navigate.py`).

**Seul le boss final fait une victoire.** Une aventure qui s'arrête avant
n'est ni gagnée ni perdue mais *inachevée*, même si le boss intermédiaire
avait été battu — sans cette règle, une navigation perdue à mi-chemin
passait pour une réussite.

`python navigate.py where --snap` reste le diagnostic : il donne le score
de **chaque** template sur l'écran courant, distingue un mauvais score
d'un `FICHIER ABSENT`, et enregistre la capture pour qu'on puisse rejouer
l'analyse hors ligne.

### Le défi : choisir son bloqueur

`Challenger` (67 cartes) laisse notre unité **tirer** l'ennemi de son
choix en défense ; `Vulnerable`, porté par l'unité adverse, ouvre le même
droit à n'importe lequel de nos attaquants. Le bot les lisait déjà — c'est
ce qui lui évite de confondre « notre rangée est avancée » avec « nous
attaquons » — sans jamais s'en servir.

**Le tirage a deux effets, et le second vaut souvent plus que le
premier :** l'unité tirée bloque *notre* unité, donc elle ne bloque plus
personne d'autre. Tirer le seul gros bloqueur d'en face ouvre la voie à
tout le reste de l'attaque. Aucune heuristique locale ne voit ça, donc
`plan_challenges` chiffre l'**attaque entière** pour chaque tirage
envisageable, garde celui qui améliore le plus le bilan, et recommence
avec les unités restantes.

Un exemple, tiré des tests : notre Provocateur 6/6 et notre Brute 5/5
contre leur Frappeur 5/4 et leur Muraille 1/7.

- **sans défi**, l'adversaire choisit bien — la Muraille encaisse le
  Provocateur sans mourir, le Frappeur échange avec la Brute. Bilan
  **−1**, le bot renonce à un attaquant ;
- **avec le défi**, le Provocateur tire le Frappeur et le tue sans mourir
  (6 ≥ 4, et 5 < 6). La Muraille ne peut plus qu'encaisser la Brute.
  Bilan **+9**, les deux unités attaquent.

Deux garde-fous, parce qu'un défi coûte un glisser-déposer :

- **strictement meilleur, pas « aussi bon »** : à bilan égal, on engage
  normalement plutôt que de risquer un geste de plus ;
- **la légalité du blocage doit être indiscutable** — on ne tire pas une
  unité Immobile, ni une unité à 2 d'attaque avec un attaquant Redoutable.
  L'interaction exacte entre le défi et Insaisissable / Redoutable est une
  règle que je ne connais pas de source sûre, alors le bot s'abstient au
  lieu de parier.

**Le geste est un seul glisser** : on saisit notre unité et on la lâche
*sur* l'unité adverse. Le client fait les deux d'un coup — notre unité
avance, la sienne est tirée en face. Un geste au lieu de deux, donc deux
fois moins d'occasions de rater, et aucun état intermédiaire à rattraper.
Les défis passent **avant** les engagements simples, tant que le plateau
n'a encore bougé pour personne.

Trois issues, et elles ne se confondent pas :

| Ce qu'on observe | Ce que fait le bot |
|---|---|
| notre unité a quitté le banc, l'ennemie est tirée | c'était le plan |
| notre unité est engagée, l'ennemie n'a pas bougé | **demi-succès** : le défi a été refusé, l'attaque est déclarée, on ne défait rien |
| notre unité est toujours au banc | on relit les deux positions, on retente une fois, puis **engagement simple** — le défi a raté, pas l'attaque |

Volontairement ignorés, parce qu'ils demandent de *comprendre un texte*
et pas de reconnaître un mot-clé : `LastBreath` (l'effet est dans la
description), `Fury`, `Regeneration`, `Scout`, `Support`. `SpellShield`
n'a d'effet que sur le choix de cible d'un sort, pas sur un combat.

```powershell
python test_keywords.py           # la physique du duel, 54 assertions
python actions.py attack --plan   # le banc adverse, les tirages prévus, rien d'exécuté
python actions.py block --plan    # les mots-clés de chaque unité, en clair
```

## Mesurer au lieu de deviner

Chaque combat s'enregistre dans `journal.jsonl`. `python journal.py`
agrège par configuration :

```
configuration                     joués  gagnés    taux   durée  tours
spells=True chump=False              12       9    75 %    198s    8.4
spells=False chump=False             11       6    55 %    221s    9.1
```

C'est ce qui rend les réglages décidables. `--max-cost 3` contre `4`,
`NEXUS_DAMAGE_WEIGHT` à 1.0 contre 1.5 : joue une dizaine de combats avec
chacun et compare. En dessous d'une dizaine par configuration, l'écart
observé est surtout du hasard.

### Le deck dit comment jouer (06/09/2026)

Le bot joue le premier champion de la liste, donc un deck différent à
chaque tentative — et il les jouait tous pareil. `strategy.py` lit la
decklist (`/static-decklist`) et la base de cartes, en déduit un
**archétype** (`aggro`, `tirage`, `midrange`, `controle`) et règle le
poids d'un dégât au nexus, le plancher du bilan d'attaque, la valeur des
déclencheurs « Attack: » et le seuil de mulligan. Le journal enregistre
`archetype` et `champions` : `python journal.py` compare les taux de
victoire par plan de jeu. `python strategy.py --traces` montre ce que le
bot a déduit des decks enregistrés ; `decks_lor.md` explique chaque deck.
Sans decklist, la stratégie par défaut est l'ancien comportement.

### D'où vient le verdict (05/09/2026)

Au 05/09/2026, **53 combats sur 53** avaient `gagne: null` : en défi,
l'API `/game-result` ne dit rien, et la boucle de combat écrit sa ligne
de journal en sortant — AVANT que l'écran n'ait dit qui a gagné. Le
verdict est donc rendu après coup et **reporté** dans la ligne du combat
(`journal.conclude`, retrouvée par son `id`) :

| verdict                          | qui le rend                       | sens |
| -------------------------------- | --------------------------------- | ---- |
| `API /game-result`               | `combat.py`                       | la seule source qui parle hors défi |
| `écran de fin d'aventure`        | `lor_battle._declare_defeat`      | second « Continuer » sans « Relevez-vous » : DÉFAITE |
| `relevez-vous`                   | `lor_battle.try_combat`           | « Relevez-vous » cliqué : le combat qui précède était PERDU, un nouveau est joué |
| `aventure poursuivie`            | `navigate.run_adventure`          | le nœud SUIVANT a été rejoint : le combat était GAGNÉ |
| *(vide, `termine: false`)*       | —                                 | inconnu, exclu du taux — le boss final perdu sans nouvelle chance reste là |

`python journal.py --last 10` marque d'un `*` les issues déduites de
l'écran, et l'écran ne requalifie jamais un verdict de l'API.

Le compteur `tours` compte les ROUNDS : un épisode de jeu qui démarre
avec plus de mana que le précédent n'en a laissé est un nouveau tour,
qu'une phase d'attente ait été lue ou non (le journal du 05/09 disait
« 1 tour » pour dix cartes posées en 230 s).

### Le backlog du bot : `journal.py --ecartees`

Chaque carte que le bot écarte pendant un combat est comptée avec son
motif, normalisé (« coût 3 > mana 2 » et « coût 5 > mana 1 » comptent
ensemble) et enregistrée dans la ligne du combat. Le classement sépare
deux choses :

```
=== Ce que le bot ne sait pas (encore) jouer — sur 12 combat(s) ===
motif                                                       fois  combats  cartes
sort : deux interfaces : la main puis le plateau              14        6  Rite funèbre ×9, ...
sort : un choix supplémentaire après la désignation            5        3  ...

=== Contexte de la partie (mana, place, cible) — pas une incapacité ===
coût N (lu à l'écran) > mana N                                 61       12  ...
```

Le premier tableau est l'ordre de travail : la forme de geste en haut
est celle qui coûte le plus de mana en jeu réel, donc la prochaine à
apprendre au bot. Le second dit seulement que la partie était ce qu'elle
était. Le compteur existe depuis le 05/09/2026 ; les combats d'avant n'y
figurent pas.

## Regarder le bot jouer depuis un navigateur

```powershell
python monitor_web.py                        # http://127.0.0.1:8765/
python monitor_web.py --interval 2 --sans-ocr
```

Une page locale, rafraîchie toutes les 2 s, qui montre ce que le bot voit
pendant qu'il joue : la capture de la fenêtre du jeu avec les rectangles de
l'API dessinés dessus (vert = à nous, rouge = adverse, bleu = nexus), le
`summary()` du plateau, les cartes par zone, la fin du log du lancement en
cours et le dernier combat du journal. Deux boutons calculent À LA DEMANDE
ce que `actions.py plan` et `actions.py why` diraient maintenant (le premier
appel charge l'OCR ; `--sans-ocr` lit par la forme seule).

C'est fait pour un lecteur qui ne voit pas la fenêtre du jeu — Claude in
Chrome, ou toi sur le second écran — et qui lit l'état en texte plutôt
qu'en pixels (`/state.json`, `/screen.jpg`, `/plan.txt`, `/why.txt`). Le
serveur ne fait aucun geste et n'enregistre rien ; il tourne à côté de
`challenges.py`, dans son propre processus, et ajoute un appel d'API toutes
les `--interval` secondes. Le jeu doit rester découvert sur l'écran
principal (c'est déjà la condition pour que le bot joue) ; le navigateur va
sur l'autre écran. Pour revoir une partie après coup, c'est `--record` et
`replay.py`, ci-dessous.

## Rejouer un combat sans le jeu

```powershell
python combat.py --record                    # enregistre dans traces/combat_<horodatage>/
python challenges.py --record                # idem pour toute la session
python replay.py list traces/combat_...      # une ligne par lecture d'état, >> aux changements
python replay.py show traces/combat_... 42   # l'état complet de la lecture 42, mana compris
python replay.py plan traces/combat_... 42   # ce que `actions.py plan` déciderait dessus
python replay.py combat traces/combat_... 42 # une itération de la boucle, à blanc
python replay.py monitor traces/combat_...   # rejoue toute la trace
```

Tout ce que le bot sait du jeu passe par cinq fonctions de `lor_api`
(API positionnelle, capture, fenêtre, résultat, decklist). `--record`
les enveloppe et consigne chaque appel dans `events.jsonl` (+ captures
PNG dédoublonnées) ; `replay.py` les rejoue à la place du jeu, et toute
la chaîne — lecture d'état, OCR, plans de pose, d'attaque, de blocage —
tourne sur exactement ce que le bot avait devant lui. Une question sur
une décision ne coûte plus une partie. Compter 1 à 2 Mo par capture :
`traces/` est dans `.gitignore`.

Le rejeu marche sans easyocr ni pyautogui (VM Linux) : les chiffres sont
alors lus par la forme seule, en mode tolérant.

## Se passer d'easyocr

```powershell
python combat.py --sans-ocr
python challenges.py --sans-ocr
```

Les chiffres (mana, coûts, stats) sont lus **par la forme d'abord**
(`digits.py`, ~1 ms, déterministe) partout, easyocr ne tranchant que les
lectures douteuses. Le modèle n'est plus chargé à l'import de
`detect_chiffres` mais au premier doute, et `challenges.py` fait le même
pré-vol que `combat.py` (plus de gel de 5 s au premier tour, plus de
plantage tour 1 hors de `.venv`).

À la fin de chaque combat, le log dit ce qui a servi :

```
Chiffres : 143 lecture(s) de chiffres : forme 139, easyocr 3, tolerant 1 — easyocr nécessaire 2 %
```

`--sans-ocr` ne charge jamais torch ; le journal enregistre `ocr=False`
pour que `python journal.py` compare le taux de victoire avec et sans.
C'est cette comparaison — pas une intuition — qui dira si la forme seule
peut devenir le défaut.

## Réglages utiles

| Constante                      | Fichier         | Rôle                                 |
| ------------------------------ | --------------- | ------------------------------------ |
| `ZONE_BANDS`                   | `game_state.py` | découpage du plateau en zones        |
| `ATTACK_TOKEN_MATCH_THRESHOLD` | `game_state.py` | sensibilité du jeton (0.75)          |
| `PLAY_DROP_ZONE`               | `actions.py`    | où lâcher une carte (`attack`)       |
| `CANCEL_POINT_RATIO`           | `actions.py`    | zone vide du clic d'annulation       |
| `SPELLS_ENABLED`               | `actions.py`    | coupe tous les sorts d'une ligne     |
| `CARD_RESTRICTIONS`            | `actions.py`    | `False` : tente toute carte payable (`--prudent` la remet à `True`) |
| `NEXUS_DAMAGE_WEIGHT`          | `actions.py`    | agressivité : >1 fonce, <1 préserve  |
| `MULLIGAN_MAX_COST`            | `actions.py`    | au-dessus, la carte part au mulligan |
| `MULLIGAN_CONFIRM_WAIT`        | `actions.py`    | attente après la validation (3 s), le temps des animations |
| `GESTURE_SPEED`                | `gestures.py`   | vitesse des gestes (2 = deux fois plus rapide) |
| `OCR_DISABLED`                 | `mana.py`       | `--sans-ocr` : forme seule, easyocr jamais chargé |
| `MANA_BOX`                     | `mana.py`       | zone OCR du cadran de mana           |
| `NEXUS_HEALTH_MAX`             | `mana.py`       | plafond de PV accepté à la lecture   |

## Prérequis

Windows, Python 3, LoR lancé en 1920x1080.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`easyocr` installe `opencv-python-headless`, une build d'OpenCV **sans
interface graphique**. Les outils de calibration en tiennent compte :
`cut-token` utilise Tkinter et non `cv2.selectROI`.

La base de cartes vit dans `LoR-Bot/card_sets/`. Pour la mettre à jour
après la sortie d'un set :

```powershell
python LoR-Bot/code/download_card_sets.py            # ajoute les sets manquants (set7b, tpoc…)
python LoR-Bot/code/download_card_sets.py --force    # retélécharge tout
```

Le script écrit dans `LoR-Bot/card_sets/` quel que soit le répertoire
courant et affiche un bilan (fichiers présents, téléchargés, total de
cartes). Des cartes « inconnues » en jeu (`07SH…`, `07BW043`) veulent dire
qu'un set manque : relance-le.

## Dépannage

**`ModuleNotFoundError: No module named 'easyocr'`.** Le bot tourne avec
un autre interpréteur que celui du projet. Deux environnements coexistent
dans le dossier : `.venv` (Python 3.12, complet — c'est le bon) et `venv`
(Python 3.11, vestige, sans easyocr ni pyautogui). Active `.venv` avant
de lancer, ou appelle son interpréteur directement :

```powershell
.\.venv\Scripts\Activate.ps1
python combat.py
# ou, sans activer :
.\.venv\Scripts\python.exe combat.py
```

Contrôle en une ligne : `python -c "import sys, easyocr; print(sys.executable)"`
doit afficher un chemin dans `.venv`. `combat.py` charge désormais le
modèle OCR AVANT d'entrer en partie : un mauvais interpréteur s'arrête
tout de suite au lieu de planter au tour 1 en laissant une partie en
cours.

**La partie reste figée, les cartes de la main en surbrillance.** Une
carte posée attend qu'on désigne une carte EN MAIN. Ces désignations sont
gérées (voir plus haut) ; si le symptôme apparaît, c'est que le texte de
la carte n'est reconnu ni comme désignation ni comme refus. Le
classifieur dit ce qu'il en pense :

```powershell
python spells.py explain "<le texte anglais de la carte>"
python spells.py coverage
```

**Le bot ne pose rien.** Le mana est probablement illisible : sans lui,
aucune pose n'est tentée. `python mana.py --crops`.

**Le bot croit que c'est son tour alors que non.** Le test de l'orbe
bleue est en cause : `python game_state.py vision`, regarde la ligne
`H+S+V`.

**Le bot attend indéfiniment pendant que l'adversaire attaque
(`Challenger`).** Son unité en tire une des nôtres en face d'elle : elle
traverse la ligne toute seule, notre rangée d'attaque se remplit, et
« notre rangée est occupée » ne veut plus dire « c'est nous qui
attaquons ». Le bot lisait `ATTACKING`, se mettait à attendre une
résolution qui ne venait pas, et le jeu attendait nos bloqueurs — jusqu'à
la durée maximale. Deux garde-fous depuis, indépendants l'un de l'autre :

- le **jeton** départage quand les deux rangées sont avancées, parce que
  c'est exactement la question qu'il pose (à qui appartient ce round
  d'attaque). Il ne sert qu'en évidence POSITIVE du côté adverse : une
  détection manquée n'invente pas une attaque ;
- la **boucle de combat** reprend la question sans rien regarder
  (`_reconsider_attacking`) : elle sait ce qu'elle a déclaré. Rangée
  avancée sans attaque déclarée depuis le dernier plateau dégagé = on
  nous a tirés, donc on bloque. Et `ATTACKING` n'est plus une attente
  sans limite : une résolution prend quelques secondes, au-delà
  l'escalade anti-blocage reprend la main.

**Le bot annonce « pas d'attaque ce tour » alors que l'adversaire
attaque.** Trois causes, toutes corrigées :

- **la principale** : poser une carte rend la priorité à l'adversaire,
  qui peut déclarer son attaque entre deux de nos poses. `play_turn`
  reprenait ensuite sans relire ce qui venait de se passer : il écrivait
  `Phase BLOCKING : pas d'attaque ce tour` — l'exact contraire de ce que
  la ligne affichait — puis cliquait l'orbe, ce qui **passait** le
  blocage. Toute l'attaque arrivait au nexus sans un seul bloqueur. Le
  tour rend maintenant la main à la boucle dès que la phase a changé, et
  ne clique que si c'est encore notre tour ;

- l'orbe est grise pendant l'animation de la charge adverse, et elle
  était testée AVANT les rangées d'attaque. La lecture donnait
  `OPPONENT_TURN`, la boucle attendait, et le tour reprenait comme un
  tour ordinaire — sans un seul bloqueur posé. Une attaque déclarée est
  désormais lue en premier : c'est un fait, pas une opinion sur le
  timing, et `execute_blocks` attend la main avant d'agir ;
- une unité qui charge traverse trois bandes, et laquelle elle atteint
  dépend de l'animation. Elle retombait parfois dans `stack`. Le camp,
  lui, vient de l'API et ne se trompe jamais : toute unité avancée est
  maintenant rangée d'après son camp, la hauteur ne servant plus qu'à
  dire qu'elle est engagée.

Si le symptôme persiste, c'est que les attaquants n'atteignent même pas
la bande `stack` et restent comptés dans `enemy_board`. Il faut alors
des nombres, pas des suppositions :

```powershell
python game_state.py monitor --trace trace.jsonl
```

Joue un tour où l'adversaire attaque, arrête avec Ctrl+C, et regarde le
`ratio` de ses unités au moment de la charge. S'il dépasse `0.725`,
c'est la borne `enemy_attack` de `ZONE_BANDS` qu'il faut remonter.
`python game_state.py inspect` affiche la même chose en direct, avec les
bandes réellement en vigueur et la zone finalement retenue.

**Le jeton est toujours détecté, ou jamais.** Le score affiché par
`monitor` doit être nettement au-dessus du seuil quand l'épée est là, et
nettement en dessous sinon. Si les deux se ressemblent, recadre le
template plus serré — remonter le seuil ne fait que déplacer le problème.

**La boucle s'arrête sur « bloqué en X ».** Elle a tenté une annulation
puis un clic de passe sans que rien ne bouge. Relance
`python game_state.py inspect` pendant ce blocage : le plus souvent une
zone est décalée, et le bot vise à côté.

**Le combat rend la main aussitôt après avoir été lancé.** La boucle
attend maintenant jusqu'à `STARTUP_TIMEOUT` (120 s) que la partie
démarre : le client annonce `Menus` pendant tout le chargement. Si le
message « la partie n'a pas démarré » apparaît, c'est que le clic sur
« Combat » n'a pas abouti — vérifie `assets/combat_button.png`.

**Le bot engage la mauvaise unité, ou attrape le vide.** Le plateau de
LoR est CENTRÉ : dès qu'une unité quitte le banc, toutes les autres se
réalignent. Les points de saisie calculés au moment du plan désignaient
alors la voisine. La décision se prend toujours une fois, sur un plateau
cohérent, mais l'exécution relit maintenant la position de chaque carte
juste avant de la saisir (`relocate_card`), à l'attaque comme au
blocage — où les deux extrémités du glissé sont concernées.

Relire ne suffisait pas : il faut relire APRÈS L'ANIMATION. Deux choses
changent à des moments différents, et les confondre était la cause des
saisies ratées dès trois unités sur le banc :

| ce qui change            | quand                        | ce qui le mesure       |
|--------------------------|------------------------------|------------------------|
| le contenu des zones     | au dépôt, immédiatement      | `snapshot_signature`   |
| la position des cartes   | à la fin du recentrage       | `zone_geometry`        |

`wait_for_change` attend donc les deux : d'abord un état qui diffère,
puis deux lectures consécutives où les rectangles ne bougent plus à trois
pixels près (`wait_until_settled`). Sans la seconde attente, l'appelant
recevait des coordonnées EN COURS DE VOL et visait entre deux cartes.
`wait_for_change(..., settle=False)` rend l'ancien comportement.

Deux garde-fous complètent l'engagement, dans `move_to_attack_row` :

- une saisie ratée est **retentée une fois** avec des coordonnées
  relues (`ENGAGE_ATTEMPTS`) plutôt que de coûter l'attaquant du tour ;
- si le banc a perdu une unité mais **pas celle qu'on visait**, on
  n'insiste pas — retenter viderait le banc carte par carte.

La vérification « l'unité est-elle partie ? » se fait par **CardID** et
non par code de carte (`_left_zone`). Avec deux exemplaires de la même
carte sur le banc — deux Thrall Bulwark, par exemple — le comptage par
code voyait un succès alors que la voisine était partie à la place de la
bonne.

**Le bot pose la mauvaise carte de la main à partir de la deuxième.** Même
cause, autre zone : **la main aussi est centrée**, et elle se recentre dès
qu'une carte la quitte (signalé par Ewan le 22/08/2026). `play_hand`
relit donc un instantané **stabilisé après chaque pose**
(`settled_snapshot`), et c'est celui-là qui sert à l'itération suivante —
au classement des jouables, à l'OCR des coûts qui découpe l'écran aux
coordonnées des cartes, et à la saisie.

Pourquoi `wait_for_change` ne suffisait pas, alors qu'il attend déjà la
fin du recentrage : la main ne commence pas à bouger à l'instant où la
carte la quitte. Pendant ce battement, deux lectures consécutives
montrent les mêmes rectangles, `wait_until_settled` conclut « immobile »
et rend des positions déjà condamnées. Il abandonne aussi au bout de
`SETTLE_TIMEOUT` (2 s) si l'animation traîne, et les chemins d'ÉCHEC de
`play_card` (annulation, carte restée en main) ne stabilisaient rien du
tout. La relecture d'après-pose couvre les trois cas d'un coup —
`test_the_hand_is_reread_between_two_plays` la verrouille.

**Une carte reste en main indéfiniment.** Elle est mise de côté après
deux tentatives ratées, donc la boucle ne s'y bloque pas — mais la cause
est réelle. `python actions.py plan` donne les coordonnées de saisie et
de dépôt qu'il utilise.
