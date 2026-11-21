# CLAUDE.md — bot Legends of Runeterra

Automatisation des défis hebdomadaires PvE : navigation sur la carte
d'aventure, puis combat joué en autonomie. Tout est dans ce projet ; aucun
bot externe.

`README.md` (1000 lignes) explique **comment lancer** : commandes,
échelle de lancement, calibration, vitesse des gestes. Ce fichier-ci donne
les règles de travail et les décisions **qu'on ne peut pas relire dans le
code**. Les deux se lisent avant de toucher à quoi que ce soit.

## Règles de travail

- **Le projet est en français** : code, commentaires, docs, messages de
  log, noms de tests parfois anglais mais prose française. Écris en
  français.
- **Un seul environnement Python : `.venv` (3.12).** Il contient easyocr
  1.7.2, torch CPU, pyautogui, pywin32, opencv. Le dossier `venv` (3.11)
  est un vestige incomplet — ne pas l'utiliser, ne pas le réparer.
  Devant n'importe quel `ModuleNotFoundError`, **vérifier l'interpréteur
  avant de toucher au code** :
  `python -c "import sys, easyocr; print(sys.executable)"` doit pointer
  dans `.venv`. Lancer via `.\.venv\Scripts\Activate.ps1` ou
  `.\.venv\Scripts\python.exe combat.py`. Le 19/08/2026 un combat a été
  perdu au tour 1 pour cette seule raison, sans rien de cassé.
- **La base de cartes est indispensable, et son absence est SILENCIEUSE.**
  `LoR-Bot/card_sets/*.json` (descriptions en ANGLAIS — tout `spells.py`
  classe des textes anglais, ne jamais passer en `fr_fr`). Si le dossier
  manque, `lor_api.load_card_db` rend `{}` avec un simple warning : le bot
  démarre, joue, et **ne clique plus jamais sur une cible** — sans
  description, `classify_card` rend `Targeting.NONE`, et les refus « hors
  de portée » ne s'appliquent plus non plus. Vu le 26/08/2026 sur Lien
  cosmique (06BC044) et Trouvailles fortunées (Lucky Find, 04SH098) : deux
  sorts posés, aucun clic. **Devant un « il ne clique sur rien », vérifier
  la ligne « base de cartes » de `check.py` AVANT de lire le code.**
  Remplissage : `python LoR-Bot/code/download_card_sets.py`.

- **LE PORT DE L'API N'EST PAS FIXE.** 21337 est celui que le client
  prend *quand il est libre*. Le 04/11/2026 il écoutait sur **21338**, et
  rien ne le disait : `check.py` annonçait « API injoignable », le bot a
  traversé la carte, lancé le boss final, puis attendu 120 s devant un
  mulligan qu'il ne voyait pas — une tentative hebdomadaire brûlée.
  Changer la constante n'aurait rien réglé (le port suivant sera pris au
  lancement suivant) : `lor_api.find_api_base` SONDE `API_PORT_CANDIDATES`
  (21337-21347) et adopte le premier qui rend le JSON de l'API. La sonde
  n'est déclenchée que par un **refus de connexion** — répondre mal
  (HTML, JSON vide pendant un chargement) veut dire « c'est le bon port,
  attends », et partir en chasse là-dessus ferait perdre le bon. Le
  changement de port est journalisé en WARNING. Tests : `test_lor_api.py`.
  **Devant un « NO_API » alors que le jeu tourne, regarder le port AVANT
  de lire le code.**
- **Une API muette n'est pas un combat raté** : `CombatReport.api_down` →
  `navigate.API_DOWN_PREFIX` → `challenges.py` arrête la session. Avant,
  le motif disait « la partie n'a pas démarré » et la session enchaînait,
  brûlant les tentatives une par une.

- **UNE SEULE BORNE PAR GRANDEUR LUE.** Il y en avait trois pour la même
  chose : `game_state._MAX_FOR_TAG["stat"] = 30`,
  `detect_chiffres.STAT_MAX = 99` (la bonne pour les PV du nexus) et
  `COST_MAX = 12` contre `_MAX_FOR_TAG["cost"] = 15`. `_cached_ocr`
  bornait bien la lecture PAR FORME à 30, mais son secours easyocr
  rebornait à 99 en interne et sa valeur n'était jamais revérifiée.
  Résultat le 04/11/2026 : une Prancing Sea Spirits 3/3 lue **3/73**,
  jugée increvable, envoyée attaquer (« on perd 6, on tue 7 ») ; en
  rejouant la trace, **5 lectures aberrantes sur 888 badges** (77 d'attaque
  pour une Spiderling, 73/43/52 de PV). Désormais `game_state.
  STAT_READ_MAX` / `COST_MAX` sont la seule source, `ocr_number` prend un
  `maximum`, et `_cached_ocr` REVÉRIFIE ce qu'on lui rend : hors borne
  vaut échec de lecture (la carte retombe sur sa stat imprimée), pas
  décision. Rejet journalisé en WARNING. Tests :
  `test_game_state.test_an_implausible_reading_is_refused`.
- **`--spells` NE COMMANDE RIEN en mode par défaut** : `playable_cards`
  court-circuite sur `if not CARD_RESTRICTIONS:` en tête de boucle, et
  les sorts y passent sans condition — `respond_to_stack` et
  `cost_reading_candidates` font pareil. Le champ `spells` du journal
  n'est que l'option CLI : **il vaut `false` dans des combats où les
  sorts ONT été joués**, c'est `restrictions` qui distingue les parties.
  Piège de lecture vérifié le 04/11/2026 (on en a conclu à tort que le
  bot n'avait jamais joué un sort ; le log du combat disait
  « Lancement de Undergrowth »).

- **Une suite de tests non inscrite dans `check.py` est MUETTE.**
  `test_events.py`, `test_digits.py` et `test_riposte.py` existaient,
  vertes, et ne tournaient jamais (constaté le 04/11/2026) : elles
  n'étaient pas dans `TEST_SUITES`. En écrire une neuve, c'est l'y
  ajouter dans le même geste.

- **Une suite VERTE à la main peut être ROUGE dans `check.py`** : la
  console Windows écrit en UTF-8 (depuis Python 3.6), mais `check.py`
  lit ses suites par un TUBE, où Python retombe sur cp1252 — et meurt
  sur la première « → » imprimée. Trois suites ont planté comme ça le
  05/11/2026 avec toutes leurs assertions vertes. `_run_suite` impose
  donc `PYTHONIOENCODING=utf-8` à l'enfant. Devant un `UnicodeEncodeError`
  dans une suite, regarder l'encodage AVANT la logique.

- **`python check.py` avant et après chaque changement.** Il enchaîne les
  suites hors ligne (aucune souris, temps simulé) et le diagnostic contre
  la partie ouverte. `--offline` suffit pour valider une modification de
  logique.
- **Ne rien livrer qui ne soit vert hors ligne.** Les tests sont la
  spécification : ~900 assertions décrivent des comportements payés cher
  en jeu. Un test qui gêne est un fait de jeu qu'on a oublié, pas une
  contrainte à retirer.
- **Les faits de jeu viennent d'Ewan.** Il joue depuis des semaines ; une
  mesure sur une capture d'écran ne pèse pas contre son expérience de
  terrain. Proposer, mesurer en jeu, n'échanger qu'après. (Cas vécu : la
  détection des nœuds par couleur, écrite le 21/08 sur de bonnes mesures,
  retirée le 22/08 parce qu'elle ne tenait pas en jeu.)

## Les fichiers

| Fichier | Rôle |
| --- | --- |
| `game_state.py` | lecture du plateau via l'API du client (`/positional-rectangles`), phases, zones, instantanés |
| `actions.py` | les DÉCISIONS : mulligan, pose, attaque, blocage, défis — ne touche plus pyautogui |
| `gestures.py` | la SOURIS : `move`, `click`, `right_click`, `drag`, `GESTURE_SPEED` ; réexporté par `actions` (un espion sur `actions.click` marche, sur `gestures.move` pour l'intérieur de `drag`) |
| `replay.py` | `--record` (combat, challenges, monitor) enregistre les 5 appels de `lor_api` ; `replay.py list/show/plan/combat/monitor` rejoue sans le jeu, sans pyautogui ni easyocr |
| `keywords.py` | la PHYSIQUE d'un duel — fonction pure `resolve_duel` |
| `spells.py` | classification des textes de cartes, ciblage, choix de version |
| `mana.py`, `click_utils.py`, `detect_chiffres.py` | OCR des coûts, gestes souris, chiffres |
| `combat.py` | la boucle d'UN combat (phases) |
| `navigate.py`, `adventure_navigation.py` | la carte d'aventure : écrans, nœuds, templates |
| `challenges.py` | la boucle des TENTATIVES ; `lor_automation.py` n'est qu'une façade |
| `champions.py` | le CHOIX DU CHAMPION : lit les étoiles de la grille, écarte les épuisés, clique le plus fort ; repli sur `first_champion` |
| `bilan.py` | le JUGE DE FIN DE TENTATIVE : lit les PV du nexus sur l'écran de bilan et rend le verdict — seul juge du boss final |
| `journal.py` | `journal.jsonl`, taux de victoire par configuration ; `conclude()` reporte un verdict rendu après coup dans la ligne du combat (par `id`) |
| `strategy.py` | le PROFIL DU DECK : decklist + card_sets → archétype → poids du nexus, plancher d'attaque, bonus « Attack: », seuil de mulligan ; `actions.STRATEGY` |
| `sortie_utf8.py` | la parade UTF-8, POINT UNIQUE : écrire en UTF-8 même quand stdout part dans un TUBE ou un FICHIER |
| `check.py` | tests + diagnostic ; **la seule commande à retenir** |
| `monitor_web.py` | page web locale (`http://127.0.0.1:8765/`) montrant EN DIRECT ce que le bot voit : capture de la fenêtre avec les rectangles de l'API dessinés, `summary()`, fin du log, journal, `plan`/`why` à la demande — pour un lecteur externe (Claude in Chrome sur le second écran). Ne fait AUCUN geste, n'enregistre rien |

## Invariants à ne pas défaire

### Lecture du plateau

- **Le plateau a DEUX horloges.** Le *contenu* des zones change au dépôt,
  immédiatement ; les *positions* continuent de glisser pendant tout le
  recentrage. Tout code qui vise à la souris après une action doit partir
  d'un instantané **stabilisé** (`actions.settled_snapshot`,
  `wait_until_settled`). `stable_snapshot(confirmations=1)` n'attend rien :
  c'est une lecture brute, prise en pleine animation.
- **« La carte est-elle partie ? » se vérifie par CardID**
  (`actions._left_zone`), jamais par comptage de codes.
- **`play_hand` relit la main après chaque pose** — les autres cartes se
  recentrent. Point unique volontaire : ne pas faire relire `play_card` /
  `play_spell` chacun de leur côté.
- **Pendant une désignation, la main sort de sa bande** : le jeu remonte
  les cartes désignables, `classify_zone` les range dans « board » et
  `snapshot.hand` est vide. Donc : **décider sur l'état d'AVANT le dépôt,
  viser par CardID dans l'état d'après, sans regarder la zone.**
- **« Notre rangée est occupée » ≠ « nous attaquons »** : Challenger et
  Vulnerable tirent nos unités en face. Deux garde-fous indépendants, il
  faut les deux — le jeton d'attaque en évidence positive côté adverse
  (`game_state`), et `combat.CombatLoop._reconsider_attacking` qui sait ce
  qu'il a lui-même déclaré. `ATTACKING` est une attente **bornée**, pas
  une `WAITING_PHASE`.
- **Une unité tirée bloque DÉJÀ son attaquant** (03/09/2026) :
  `actions.pulled_blocks(snapshot)` apparie nos unités de `attack_row` aux
  attaquants à leur verticale (écart ≤ `PULLED_BLOCK_TOLERANCE` = 12 % de
  la largeur, le plus proche d'abord, un attaquant une seule fois).
  `plan_blocks` retire ces attaquants du problème, ne les met PAS dans les
  paires à glisser, et compte leurs dégâts traversants. Avant, le bot
  glissait un bloqueur du banc sur un attaquant déjà bloqué (geste refusé)
  pendant qu'un autre passait.

### Décisions de jeu

- **Les restrictions de cartes sont levées par défaut**
  (`actions.CARD_RESTRICTIONS = False`, `--prudent` rétablit l'ancien
  comportement). Ne subsistent que le mana, la place sur le banc, la
  vitesse des sorts, la disponibilité d'une carte à désigner, les
  interfaces hors de portée — et, depuis le 08/11/2026, **l'existence
  d'une cible sur le plateau** (`actions.sort_sans_cible`, voir plus
  bas). Ces six-là ne sont pas de la prudence : ce sont des
  impossibilités LUES, du même ordre que le mana.
- **UN ÉQUIPEMENT SANS ALLIÉ N'A PERSONNE À DÉSIGNER** (05/11/2026) :
  cette clause-là s'applique aussi à lui, et elle ne l'était pas. Le
  mode par défaut le tentait, au motif que l'annulation rattrape — ce
  qui est vrai, il n'y a pas de blocage, mais elle ne rend pas le temps.
  Mesuré en partie : **The Darkin Lodestone tentée HUIT fois** entre
  19:24 et 19:38, banc vide à chaque round, ~11 s perdues par tentative
  dans un combat de neuf minutes. Le reste du chemin était bon — la pose
  ouvre une fenêtre de versions, `resolve_unforeseen_choice` l'attrape,
  et `equipment_plan` sait viser un allié ; il manquait juste de ne pas
  commencer quand il n'y a personne à équiper.
- **`keywords.has()` est le SEUL point qui interroge une carte** ; c'est
  là qu'on branchera un jour la lecture des mots-clés accordés en jeu
  (aujourd'hui invisibles : l'API ne rend qu'un CardCode). Dans
  `resolve_duel`, **l'ordre des arguments n'est pas décoratif** :
  QuickStrike, Overwhelm et Impact ne valent qu'en attaquant.
- **Volontairement non modélisés** : LastBreath, Fury, Regeneration,
  Scout, Support — l'effet est dans la description, le chiffrer serait
  inventer un nombre. Ne pas les ajouter à la légère.
- **`dies_anyway` (Ephemeral seulement) ≠ `death_cost` à zéro** (une
  Sans-mort revient). Ne pas fusionner les deux fonctions.
- **Le défi est UN SEUL glisser** : `drag(notre.grab_point,
  ennemie.center)`. Ne pas le décomposer. Les tirages sont décidés une
  fois sur l'attaque entière, puis filtrés ; strictement meilleur, jamais
  « aussi bon ».
- **Quand le jeu contredit un test de `test_keywords.py`, c'est la RÈGLE
  qui est mal lue** : corriger là, pas dans `actions.py`.

### Textes de cartes (`spells.py`)

- **On COMPTE les marqueurs de cible du texte anglais**, on ne reconnaît
  pas les sorts. 0 marqueur → aucun clic ; 1 → une cible, et le marqueur
  dit le camp ; 2+ → refus d'**incapacité** (le bot ne clique qu'une
  fois). Ne pas remplacer ce principe par une liste de cas particuliers.
- **Un adjectif devant « ally » restreint la cible, il ne la supprime
  pas** (`an Equipped ally`). Mais **« a random ally » n'est pas une
  cible** — c'est le jeu qui choisit. Avant d'élargir un marqueur,
  chercher les qualificatifs qui NIENT la désignation.
- **« ANY NUMBER OF » SE VALIDE À L'ORBE** (10/11/2026, fait de jeu
  d'Ewan). Vladimir (01NX006) : « Play: Deal 1 to any number of allies
  to deal that much to an enemy. » Le 06/11 le bot la posait, cliquait
  un ENNEMI, et la partie figeait — 12 lectures sans rien qui bouge,
  **~55 s perdues**, deux fois dans le même combat, champion banni puis
  **revenu EN MAIN**. On l'a donc refusée « hors de portée », au motif
  que le jeu attendait « des clics en nombre libre PLUS une validation,
  et ce bouton n'est pas calibré ».
  **LE BOUTON ÉTAIT CALIBRÉ DEPUIS TOUJOURS.** Ewan : « on clique sur
  l'ennemi et on clique sur le bouton bleu à droite de la page ». Ce
  bouton bleu est **l'ORBE DE TOUR**, et le bot avait photographié la
  preuve lui-même : `screenshots/bloque_ATTACKING_20261106_105937.png`
  et `..._111227.png` — Vladimir au centre, l'invite « Infligez 1 pt(s)
  de dégâts », nos alliés surlignés, et à droite à mi-hauteur l'orbe
  **BLEUE portant « PASSER »**, dans `game_state.TURN_ORB_REGION` dont
  `actions.TURN_BUTTON_RATIO` (0.85, 0.50 → **1632, 540**) est le
  centre. Le log du même combat dit que l'ennemi avait bien été cliqué
  (« Ciblage du pouvoir : Sapling (1) 2/1 en (1115, 180) ») : **il ne
  manquait QUE ce clic-là**, sur un point que `end_turn`, `play_spell`
  et `respond_to_stack` cliquent déjà. Aucune coordonnée inventée.
  **ON NE LIT PAS LE LIBELLÉ POUR DÉCIDER**, et `assets/orb/passer.png`
  n'a PAS été créé : « PASSER » est aussi ce que l'orbe affiche en temps
  ordinaire — le voir ne prouverait rien, et un gabarit de plus ne
  pourrait que disputer le maximum de `read_turn_button` à « cible » et
  « resoudre ». C'est le TEXTE de la carte qui sait
  (`spells._FREE_DESIGNATION_RX` → `SpellPlan.free_designation`), comme
  partout ailleurs : on compte des marqueurs, on ne reconnaît pas des
  sorts.
  **LE COMPTE DES MARQUEURS NE CHANGE PAS** : « any number of allies »
  n'en est pas un (aucun nombre écrit, donc pas de pluriel COMPTÉ), il
  reste « an enemy » — un clic. Ce qui s'ajoute n'est pas une cible,
  c'est un GESTE : `actions.valider_designation_libre`, appelée APRÈS
  la cible, et **seulement si la cible a été cliquée** — ce bouton est
  aussi celui de fin de tour, le cliquer à vide passerait le tour.
  **ZÉRO ALLIÉ, ET C'EST VOULU** : se blesser pour frapper plus fort
  est une décision de jeu ; poser le champion est tout le gain.
  **ET LA CIBLE RESTE OBLIGATOIRE** : sans ennemi en jeu, le premier
  des deux gestes n'a nulle part où aller, et `unit_play_blocker`
  écarte la pose **dans les deux modes** — même famille que
  l'équipement sans porteur et que `sort_sans_cible`. Décision et
  diagnostic passent par la même fonction, donc ils ne peuvent pas
  diverger.
  **BILAN MESURÉ sur les 2898 cartes : 6 plans changent, sur 3 cartes,
  et ce sont exactement les trois** — Vladimir, son niveau 2
  (01NX006T1) et Crimson Pact (01NX006T2). Zéro collatéral. « up to N »
  reste hors de portée : ses clics portent sur la MAIN, ce n'était pas
  le bouton qui manquait.
  **RESTE OUVERT** : l'ordre exact des deux gestes. Les captures
  montrent l'ennemi cliqué ET le jeu encore en attente, ce qui est
  compatible avec « l'ennemi d'abord » (la description d'Ewan, suivie
  ici) comme avec « le jeu attendait d'abord les alliés ». Les deux
  donnent le même résultat — zéro allié, effet nul, champion posé.
  **PAS ENCORE VU TOURNER EN JEU** (10/11). Tests :
  `test_spells.test_un_nombre_libre_de_cibles_se_valide_a_l_orbe`,
  `test_actions.test_vladimir_est_posee_en_validant_a_l_orbe`,
  `test_actions.test_vladimir_sans_ennemi_nest_pas_posee`.
- **L'EFFET SE LIT SUR LA CLAUSE QUI PORTE LA CIBLE** (06/11/2026,
  `spells.effect_clause`). `EFFECT_PATTERNS` est ancré en tête (`^deal`,
  `^kill`…) et doit le rester — desserrer l'ancrage ferait déteindre
  l'effet d'une clause sur la cible d'une autre. Mais l'ancrer sur le
  TEXTE ENTIER suppose que l'effet est la première chose écrite, et le
  module le savait déjà : le commentaire de `strip_preamble` le dit
  depuis le début. `strip_preamble` ne retirait pourtant que les
  subordonnées de condition et « I cost N less. ». Résultat, mesuré sur
  la base par le chemin que le bot emprunte vraiment (sorts par
  `classify_card`, unités/landmarks par `classify_unit_play`, qui extrait
  déjà la clause « Play: ») : **22 cartes tiraient sur NOS propres
  unités** — Scrapshot (7 dégâts), Monster Harpoon (5), Thermogenic Beam,
  Gotcha! (3), les deux Buster Shot (3), Undergrowth (Drain 2), les
  quatre Rite of the Arcane (4), Unworthy Soul (Recall), Sunk Cost,
  Captain Arrika et Claim (Capture), les six « Destroy a unit's
  equipment », les deux Blooming Bud (Sleep). On lit donc l'effet sur la
  clause de la cible, après avoir retiré les ÉTIQUETTES DE DÉCLENCHEUR
  (`Play:`, `Plunder:`, `Flow:`, `I-II:`…) et les CLAUSES DE COÛT
  (`To play, …`, `Destroy an allied landmark / one of your mana gems
  to …`, nommées précisément pour ne pas avaler « Destroy a unit's
  equipment and deal 2 to it »). Origine de la remarque : Ewan, « il y a
  des cartes qui ne sont jouées que sur des alliés alors qu'on peut les
  jouer sur des ennemis aussi » — l'exemple était Défense paniquée, la
  cause était bien plus large.
- **UNE REMISE QUI A PERDU SON POINT RESTE UNE REMISE** : la règle qui
  retire la condition emporte le point final, et « I cost 2 less if you
  have a Tristana or … this game. Deal 3 to a unit. » laissait
  « I cost 2 less Deal 3 to a unit. ». Le point est donc facultatif.
  C'est ce qui faisait tirer les deux Buster Shot sur nous.
- **CINQ VERBES HOSTILES MANQUAIENT** : `sleep`, `capture`,
  `destroy … equipment`, `place … into its deck`, et **`gloom`**. Le
  dernier est un malus DÉGUISÉ EN DON (`^grant` l'envoyait sur notre plus
  grosse unité) — et ce n'est pas une supposition, la base ne l'accorde
  jamais qu'à l'adversaire : « Grant the strongest ENEMY Gloom » (Vex),
  « Grant ENEMIES 2 Gloom » (Crowstorm, Fiddlesticks), « Grant AN ENEMY
  2 Gloom » (Reap), et Blighted Battleaxe en fait une punition. Même
  famille que « give an enemy Vulnerable », déjà connue.
- **DES STATISTIQUES RÉÉCRITES NE SONT NI UN CADEAU NI UN MALUS**
  (`SpellPlan.stat_override`) : « Set a unit's stats to 1|6 this round »
  (Défense paniquée, 05BC209) neutralise un gros attaquant adverse et
  sabote une de nos unités. Vu en jeu le 06/11 sur NOTRE Mage aux
  miroirs 4/7, ramenée à 1/6. Aucune famille d'effet ne peut trancher,
  alors `choose_target` PÈSE les deux camps avec `keywords.unit_value` —
  le barème qui sert déjà aux échanges, appliqué avant et après, pas un
  barème neuf. Personne n'y gagne → on ne lance pas.
- **« L'UNITÉ REVIENT-ELLE ? » TRANCHE LE CHOIX CHEZ NOUS, PAS
  « EST-CE NÉFASTE ? »** (`spells.RETURNS`). Quand le texte impose notre
  camp, `choose_target` choisit entre `gift_to_ally` (la meilleure
  receveuse, Éphémères exclues) et `sacrifice` (la moins regrettable,
  Éphémères EN PREMIER). C'est « néfaste » qui tranchait — or tuée,
  l'unité ne revient pas, tandis qu'endormie, rappelée ou capturée, si.
  Même tournure, deux prix : « Kill an ally TO deal 3 to the enemy
  Nexus » (Astral Fox) contre « Recall an ally TO summon an exact
  Ephemeral copy in its place » (Go Get It). La base le dit aussi du
  sommeil : Drowsy Dewdrop « Countdown 1: Summon an exact copy of the
  sleeping unit inside », Lillia niveau 2 « When you Sleep another ally,
  immediately wake it up and grant it Spirit ». Sacrifier une Éphémère
  gâche ces cartes : elle disparaît en fin de round. 19 cartes
  concernées (4 Sleep, 14 Recall, The Black Flame).
- **« ACTIVATE » EST UN BIENFAIT** : déclencher l'effet d'un allié ne lui
  a jamais nui. Sans ce verbe, Morning Light, Leona's Morning Light et
  Unto Dusk tombaient en « AUTRE » — et un AUTRE visant notre camp est
  refusé par prudence. Piège à connaître : **ce refus ne reste PAS en
  mode prudent**, parce que `actions.is_dead_weight` appelle
  `classify_card(card)` SANS argument, donc `restricted=True` même en
  mode par défaut. Les trois sorts devenaient du « fardeau pur » :
  premiers défaussés, derniers renforcés.
- **BILAN MESURÉ du chantier** : sur les 2466 cartes décrites, **59
  plans changent, dont 23 changent le camp du clic — 22 d'allié vers
  ennemi, 1 vers la pesée, et ZÉRO d'ennemi vers allié.** La relecture
  du diff par 22 juges indépendants a rendu 30 « mieux », 28 « pareil »
  et 7 « pire » ; les sept griefs ont donné `RETURNS`, `ACTIVATE` et
  `GLOOM`. **PAS ENCORE VU TOURNER EN JEU** (06/11). Tests :
  `test_spells.test_un_preambule_ne_doit_plus_masquer_leffet`,
  `test_quatre_verbes_hostiles_qui_manquaient`,
  `test_un_effet_qui_reecrit_les_stats_se_pese_sur_les_deux_camps`,
  `test_un_allie_qui_revient_nest_pas_un_sacrifie`,
  `test_activer_leffet_dun_allie_est_un_bienfait`.
- **ON PIOCHE DANS LE DECK, JAMAIS SUR LE PLATEAU** (`_DRAWN_RX` dans
  `_scan_targets`, 06/11/2026). « Draw a champion. » (Entreat, 01FR029)
  comptait « a champion » pour une unité à cliquer : le bot prévoyait un
  geste que le jeu n'attend pas. Six cartes — Entreat, Written in Stars,
  Rite of Calling, Legionary Charge, les deux Traveler's Call. Défaut
  ANTÉRIEUR au chantier du camp, relevé par la relecture du diff.
  **LE VERBE QUI PRÉCÈDE EST LE SEUL SIGNAL FIABLE** : chercher « in
  your deck » ou « in hand » APRÈS le marqueur donne **six faux positifs
  sur douze candidats**, parce que la mention porte presque toujours sur
  une AUTRE carte — « Deal 2 to a unit. Create a Ziggs in your deck. »
  (le marqueur est bien sur le plateau), « Recall an ally to create a
  Flawless Duet in hand » (le « in hand » porte sur le Duet). Neuf
  cartes changent de ciblage ; deux passent de REFUSÉES à jouables
  parce qu'en retirant le faux marqueur il n'en reste qu'un vrai —
  « Kill an ally to draw a Champion » (04SH121T2) et Legionary Charge
  (06NX022), dont le « ou » reste à surveiller en jeu. Tests :
  `test_spells.test_une_carte_piochee_nest_pas_sur_le_plateau`, avec
  quatre garde-fous contre les faux positifs ci-dessus.
- **Les préambules ne sont ni cible ni effet** (`strip_preamble`).
- **`REFUSALS` a trois colonnes** : prudence (tombe avec les
  restrictions) / **hors de portée** (interface qu'on ne sait pas
  piloter — vaut dans les deux modes). Hors de portée : `pick a X` nu
  (un clic de plateau qu'on ne sait pas orienter), `choose`,
  `discard/updraft up to N`, `play me as`, et les **cibles sous condition
  invisible** (« that attacked this round or is Stunned » — Astro-Pong /
  Paddle Star, Falling Star, Ravenous Flock : l'état lu ne dit ni
  « étourdi » ni « a attaqué ce round », 02/09/2026). Prix assumé : les
  8 armes Darkin ne sont plus posées.
- **« AN ATTACKING ENEMY » N'EST PAS UNE CONDITION INVISIBLE**
  (06/11/2026, remarqué par Ewan : « il n'a pas su utiliser la Tempête
  d'acier sur une carte ennemie qui attaque »). Tempête d'acier
  (01IO046) dit « Stun an ATTACKING enemy » et était classée **à
  l'identique** de « Stun an enemy » — STUN / ENEMY / condition vide. Le
  bot visait donc le plus gros ou le plus tuable des ennemis, **où qu'il
  soit** ; si celui-là n'attaquait pas, le jeu REFUSAIT le clic et le
  sort restait en l'air.
  La distinction avec les refus « condition invisible » tient en une
  phrase : « a attaqué ce round » et « est étourdi » ne se lisent nulle
  part, **mais « qui attaque » se lit** — ce sont `attack_row` et
  `enemy_attack_row`, deux zones que l'API rapporte à chaque lecture.
  Même famille que « damaged », qui filtre déjà sur les PV lus. D'où
  `spells.target_condition_of` (une condition à la fois) et le filtre de
  `choose_target`, **par CardID** comme partout ailleurs. Personne
  n'attaque → aucune cible, on ne lance pas : un clic refusé coûte plus
  cher qu'une carte gardée en main.
  **ET SURTOUT PAS D'OCR POUR ÇA** : `actions.py` déclenchait
  `enrich_with_live_stats` dès qu'il y avait UNE condition. « damaged »
  l'exige (les PV affichés), « attacking » non — c'est dans l'instantané.
  Le test est donc désormais `== "damaged"`.
  **5 cartes** : les deux Steel Tempest, Rune Prison (06RU006T12), et
  les deux Playful Trickster qui visent un ALLIÉ qui attaque (« Remove
  an attacking ally from combat to Rally »). Les 6 cartes « damaged »
  sont inchangées. Test :
  `test_spells.test_une_cible_qui_attaque_se_lit_dans_la_rangee`.
  **PAS ENCORE VU TOURNER EN JEU** (06/11).
- **« a damaged ally » est une CONDITION lisible** (`SpellPlan.
  target_condition`, `spells.is_damaged` : PV lus par OCR < PV imprimés ;
  `spell_is_castable` lit les stats pour ces sorts). Courage de Braum
  partait sur des alliées intactes (02/09/2026).
- **Les fenêtres de cartes sont PILOTÉES depuis le 02/09/2026**
  (`spells.CARD_WINDOWS` → `SpellPlan.card_window` →
  `actions.resolve_card_choice`) : Manifest, Invoke, Predict, « Pick 1 of
  N », « Pick a X to create in hand », « Pick a X from the top N cards »,
  Tellstones (« Create A, B, or C in hand », trois NOMS en majuscules —
  « ..., or create a Golden Spatula in hand » reste une VARIANTE). 69
  cartes. On ne connaît pas le contenu : les cartes proposées sont celles
  à nous dont le **CardID n'existait pas avant la pose**, hors `hand` et
  `board` (une unité au centre est lue dans `attack`, cf. deux horloges).
  La fenêtre s'ouvre à la **résolution** : après cible et désignation en
  main ; tout de suite pour une unité ou un Burst/Focus, **après la
  validation** pour un Fast/Slow (`CARD_WINDOW_SLOW_TIMEOUT`). Fenêtres
  enchaînées (Songspinner, Trifecta) : coup d'œil après chaque clic.
  Choix : `card_pick_rank` — jouable, unité, valeur, moins chère. La
  clause de la fenêtre est **retirée du texte avant le ciblage**
  (`strip_card_window`) : « Manifest a follower » ne cible aucun follower.
- **L'annulation est un CLIC DROIT** (`cancel_pending_action`, précision
  d'Ewan du 02/09/2026 ; `CANCEL_WITH_LEFT_CLICK` remet l'ancien clic
  gauche sur zone vide). Elle annule un ciblage, pas une fenêtre.
- **Une fenêtre de choix ne s'annule pas.** Le choix est obligatoire, la
  partie fige. Toute la justification des restrictions levées tombe pour
  cette famille.
- **Un pluriel COMPTÉ vaut N clics souples** (`_COUNTED_PLURAL_RX`,
  `SpellPlan.flexible_targets`) : « Frostbite 2 enemies » (Vents mordants)
  se lance sur UN ennemi s'il n'y en a qu'un — le jeu se contente des
  cibles présentes (13 sorts). « an enemy ... and another » reste strict.
  Exclus : « all », « up to N », « N allies in hand », « N units in your
  deck ».
- **Filet du 04/09/2026 — la fenêtre qu'aucun plan n'annonce**
  (`actions.resolve_unforeseen_choice`, dans `play_card`) : Nidalee
  (07SH013, « Ambush 2 », ABSENTE de card_sets) ouvre deux versions au
  dépôt. Après tout dépôt sans plan de fenêtre, deux cartes à nous ou
  plus, NOUVELLES (CardID), hors main et hors banc = fenêtre → clic sur
  la meilleure (`unforeseen_choice_rank` : version_rank puis la carte
  jouée elle-même). Vérifié AVANT de juger la pose, parce que la version
  affichée au centre porte le code de la carte jouée dans la bande
  « attack », que `_placed_counts` compte comme posée. On n'attend
  (`UNFORESEEN_CHOICE_GLANCE` 2,5 s) que si la carte n'est pas déjà sur
  le banc. Vaut pour toute carte inconnue ou tout mot-clé non modélisé.
- **Une fenêtre de versions ne se lit pas dans le texte** : le signe
  fiable est que la carte a des **jetons du même nom**, un par branche du
  « ou » (recensement dans `cartes_a_variantes.md`, régénérable : 47
  cartes). D'où le coup d'œil `VARIANT_GLANCE` — ne rien trouver est une
  réponse, pas une anomalie.

### La fenêtre de choix qui a figé 184 s (05/11/2026)

- **UNE FENÊTRE PEUT ÊTRE FAITE DES CARTES DE L'ADVERSAIRE.** Yoink!
  (98SB003) : « Pick 1 of 3 non-champion cards **from the enemy hand** to
  draw. » Le jeu affiche trois cartes À LUI au centre, et l'API les
  rapporte très bien — CardID 1278610636 / 1566250659 / 1153891470,
  257×374, **LocalPlayer FALSE**, bande `enemy_attack` (ratio 0,64).
  `offered_cards` ne regardait que les cartes à nous (« les cartes
  proposées sont celles à nous » — c'était vrai des 115 autres fenêtres,
  pas de celles-là) : « Fenêtre de cartes introuvable », puis blocage.
  **Sept cartes de la base sont dans ce cas** — Yoink!, Swindle, Prank,
  Skip « King of the Reef », les trois Entrapment — et **Entrapment
  (05BC223) était EN MAIN** pendant le blocage : le mur suivant était
  déjà posé. Le texte le disait : `spells.card_window_side` lit « from
  the enemy hand/deck » et pose `SpellPlan.card_window_side`, que
  `offered_cards(…, side=)` applique en miroir (ses zones de repos sont
  `enemy_hand` / `enemy_board`, pas les nôtres). On lit un marqueur de
  CAMP, on ne reconnaît pas des sorts.
- **LE LIBELLÉ DU BOUTON PASSE AVANT L'ORBE, et c'est tout le bogue.**
  `respond_to_stack` testait `turn_orb_active` en premier : or **l'orbe
  est ÉTEINTE tant que le jeu attend un geste de nous**. Mesuré trois
  fois pendant le blocage — « [SPELL_STACK] orbe=non bouton=cible » à
  17:13:50, 17:14:47, 17:15:54. La branche « le jeu attend une cible »
  écrite le 05/09/2026 n'était donc **jamais atteinte** : on tombait sur
  « l'adversaire a la priorité : on attend », **43 fois, 184 s**, avant
  l'abandon — un combat de 455 s et une tentative hebdomadaire perdue.
  L'orbe dit à qui c'est de parler ; le libellé dit qu'on parle à NOUS.
- **ET MÊME ATTEINTE, L'ANNULATION N'AURAIT RIEN FAIT** : une fenêtre de
  choix ne s'annule pas (trois clics droits sans effet dans la trace).
  Sous « SÉLECTIONNER LA CIBLE », `respond_to_stack` cherche donc une
  fenêtre et **prend une carte** ; il n'annule que s'il n'en voit pas.
- **LE DERNIER RECOURS RECONNAÎT UNE FENÊTRE, PAS UNE CARTE**
  (`actions.visible_card_window`, aussi branché en fin de
  `resolve_card_choice`) : ≥ 2 cartes de même taille, **les plus grandes
  de l'écran** (≥ 1,25 × le reste) et au **même bord haut**, hors zones
  de repos. Mesures sur les 4192 lectures d'API des traces : 182
  retenues — mulligans, fenêtres de version, et celle de Yoink! ; sans
  l'exclusion des zones de repos, **1003**, parce qu'une main alignée a
  exactement cette forme. Ce qui lui ressemble et n'en est pas : le
  survol grossit **une seule** carte (248×361), l'éventail de la main en
  grossit six mais **à des hauteurs toutes différentes** (tops 395 à
  465). Sur la trame réelle : 374 contre 250, **0 px** de désalignement.
- La trame d'API du blocage est gardée telle quelle dans
  `captures_reference/fenetre_yoink_20261105.json` — c'est elle qui
  verrouille les seuils. Tests : `test_actions.test_yoink_prend_une_carte_dans_la_main_adverse`,
  `test_une_fenetre_de_choix_ne_se_laisse_pas_annuler`,
  `test_la_vraie_trame_du_blocage_de_yoink`,
  `test_ce_qui_nest_pas_une_fenetre_de_choix`,
  `test_spells.test_la_fenetre_peut_etre_celle_de_ladversaire`.
- **VU TOURNER EN JEU LE 06/11** : « Prank » (le même mécanisme que
  Yoink!, fenêtre faite des cartes de l'ADVERSAIRE) s'est résolu **deux
  fois dans le même combat**, à 11:03 et à 11:12 — « zone lue :
  enemy_attack », carte choisie parmi deux, « Prank résolu ». Le point
  qui avait figé 184 s le 05/11 passe donc sans accroc. Restent non
  observées : Yoink! elle-même et les Entrapment.

### Jeton d'attaque (`game_state.find_attack_token`, 02/09/2026)

- Le template `assets/attack_token.png` porte un **masque en canal alpha**
  (l'épée seule, flammes exclues : `icon_mask`, HSV orange saturé). Le
  matching est `TM_CCOEFF_NORMED` **avec `mask=`** : la gemme de mana de
  sort et les rouages derrière l'épée n'entrent plus dans le score — sans
  ça, le score s'effondrait dès que le compteur n'était plus « 3 » et le
  bot restait en DEFEND_TURN. `cut-token` écrit désormais ce PNG masqué.
- Seuil **0.55** (Ewan mesurait 0.60-0.70 épée présente avec le masque) et
  recherche **multi-échelle** `ATTACK_TOKEN_SCALES` (0.85-1.15) : dernière
  échelle gagnante en pleine résolution d'abord, sinon balayage à demi
  résolution puis confirmation. `TokenMatch.scale` (affiché par `monitor`
  et `summary`) : toujours ≠ 1.0 → refaire `cut-token`.
- Côté : `ours = centre_y > ligne médiane des nexus`. Le jeton adverse est
  une PETITE épée sans flammes, qui ne matche pas notre template.

### Coffres d'objets (04/11/2026) — `events.COFFRE`

- **Un coffre se RAMASSE.** Le nœud affiche « Ouvrir le trésor » et
  « Quitter ». Il n'existait aucun repère pour le premier : seul
  `quit_button` passait le seuil (0.98), le bot refermait donc le coffre
  et renonçait à un **objet permanent PLUS une copie de carte** dans son
  deck — à chaque coffre, sur toute l'aventure. Il arrivait au boss final
  avec un deck jamais amélioré. Vu en rejouant la capture que
  `resolve_arrival` garde désormais quand il ferme un nœud.
- `assets/treasure_button.png` et `take_treasure_button.png`, découpés de
  cette capture. Scores croisés : treasure_button **1.00** sur « Ouvrir »
  / 0.41 sur « Quitter », l'inverse pour quit_button. Au passage, le
  `select_button 0.68` qu'on voyait sans le comprendre dans les logs
  était une correspondance partielle sur « Prendre le trésor ».
- **Le panneau qui suit est celui d'un événement**, au bouton près : d'où
  `events.Panneau` (nom, étiquette des captures, bouton qui valide,
  boutons lus, fermetures, hauteur carte/bouton) et les deux instances
  `EVENEMENT` / `COFFRE`. `resolve_event(panneau=…)` — pas de copie.
- **`renoncer_sans_prendre=False` pour le coffre** : « Quitter » est LU
  (sinon l'écran paraîtrait vide) mais n'est **cliqué qu'une fois le
  trésor pris**. Il reste lisible pendant que le panneau se dessine, et
  le cliquer là jetterait le trésor — exactement l'ancien bogue.
  `CARD_ABOVE_TAKE = 0.567` : mesuré, « Prendre le trésor » centré en
  (1442, 1002), carte du milieu à la même verticale, y≈390 sur 1080.
- **VU TOURNER LE 05/11, ET IL NE MARCHAIT PAS.** Le repère
  `CARD_ABOVE_TAKE` avait été mesuré sur une capture où le coffre
  n'était pas encore OUVERT. Une fois ouvert, le panneau n'a pas du tout
  cette forme.
- **UN COFFRE D'OBJETS DE CHAMPION EST UN CHOIX CROISÉ** (Ewan,
  05/11/2026) : « il faut cliquer sur un champion ET sur le buff qu'on
  veut lui donner ». Deux rangées — 2 cartes de champion en haut, 3
  objets en dessous — et « Prendre le trésor » reste GRISÉ tant que les
  deux ne sont pas pris. Le bot cliquait sept fois en (1442, 389), **pile
  dans le vide entre les deux cartes** (gauche jusqu'à x≈1426, droite à
  partir de ≈1466), puis abandonnait : aventure perdue. Le milieu des
  objets tombe exactement sous le bouton, ce qui rendait le clic unique
  plausible — et faux.
- **IL Y A PLUSIEURS SORTES DE COFFRES, ET LE JEU L'ÉCRIT** (Ewan) :
  « Coffre d'objets de champion ». On LIT donc le titre
  (`assets/coffre_objets_champion.png`, 1.00 ici contre 0.28 ailleurs)
  avant d'appliquer une géométrie — `Panneau.gestes_par_titre`. Titre
  inconnu : on retombe sur le clic unique d'origine, jamais sur une
  géométrie devinée.
- **Le repli à l'aveugle est une SUITE de clics, pas un clic**
  (`events.gestes_du_repli`). Mesures : cartes de champion centrées en
  (1277, 361) et (1615, 371), 298×410 ; objets, trois cadres de 260 px
  centrés 1126/1441/1756 à y≈735. On prend celui de GAUCHE dans les deux
  rangées — sur cette capture la carte de gauche est le champion QU'ON
  JOUE, et le coffre offre « une copie supplémentaire de ce champion ».
  Une seule observation : à revoir au prochain coffre.
- Tests : `test_events.test_le_coffre_de_champion_demande_deux_clics`,
  sur `captures_reference/coffre_choix_20261105.png`.

### Le nœud à options (06/11/2026) — `events.NOEUD_OPTIONS`

- **SON BOUTON PORTE LE NOM DE L'OPTION CHOISIE**, pas « Sélectionner ».
  Le soigneur propose « Choisissez-en 1. » — Soins / Acheter des soins /
  Retirer une carte — et son bouton dit **« Soins »**. Aucun gabarit de
  libellé ne le reconnaît : `select_button`, `take_treasure_button` et
  `recompense_select_grise` convergeaient tous sur (1441, 1002) à ~0.75,
  **sous le seuil**. Le bot ne voyait donc aucun bouton, restait sur le
  nœud, puis cherchait le suivant derrière le panneau et abandonnait
  l'aventure.
- **ON S'ANCRE SUR L'INVITE, PAS SUR LE TITRE.** « Choisissez-en 1. » est
  GÉNÉRIQUE (1.00 ici, ≤ 0.33 sur les cinq autres captures de référence)
  et vaudra pour les autres nœuds du même genre ; « Soigneur » ne vaudrait
  que pour celui-là.
- **VALIDER, C'EST CLIQUER AILLEURS QUE SUR LE REPÈRE** : l'invite est du
  texte. D'où `Panneau.valider_decalage` — le clic part à (+0.3776,
  +0.2602) de l'invite, mesuré sur
  `captures_reference/soigneur_20261106.png`. Vide pour tous les autres
  panneaux, dont le repère EST le bouton.
- La première option est PRÉSÉLECTIONNÉE : valider seul suffit. Vérifié
  en jeu le 06/11 — deux gestes, panneau fermé, carte rendue.
- Tests : `test_events.test_le_noeud_a_options_sancre_sur_son_invite`.

### La session du 06/11 — PREMIÈRE VICTOIRE, et trois blocages levés

- **UN NŒUD À OPTIONS PEUT OUVRIR UN CHOIX DE CARTES** (« Médecin
  sinistre »). « Choisissez-en 1. » — Recruter une abomination / Suivre
  ses enseignements / Quitter — mais l'option fait apparaître un panneau
  de TROIS CARTES à droite, « Sélectionner » grisé tant qu'aucune n'est
  prise. Le soigneur, lui, se contentait de valider. **LE PIÈGE EST QUE
  L'INVITE RESTE AFFICHÉE À GAUCHE** : mesuré sur
  `captures_reference/medecin_sinistre_20261106.png`, `choisissez_en_un`
  note 1.00 ET `select_button` 0.94. Le bot rejouait donc le geste des
  options à l'infini — huit tours, panneau laissé ouvert, puis « nœud 2
  introuvable » parce qu'il cherchait derrière. `select_button` entre
  dans `OPTIONS_BUTTONS`, et le voir fait basculer sur le panneau
  d'ÉVÉNEMENT, qui sait cliquer la carte au-dessus du bouton puis le
  bouton. **VU TOURNER EN JEU** : bascule, validation seule, repli sur
  la carte du milieu en (1439, 378), panneau fermé.
  Test : `test_events.test_un_noeud_a_options_peut_ouvrir_un_choix_de_cartes`.

- **LE BOSS FINAL EST JUGÉ MÊME QUAND RIEN NE SE PRÉSENTE.** PREMIÈRE
  VICTOIRE SUR UN BOSS FINAL — « DÉFI 13 · VICTOIRE », rang A, 0:04:52,
  nouveau record, nexus 26/63, avec Maître Yi Fleur Spirituelle (7 ★) —
  **et le journal a écrit `gagne: null`.** Le juge n'était convoqué que
  si un SECOND « Continuer » s'était présenté ; il n'y en a pas eu, on
  sortait par « Aucun « Relevez-vous » détecté », et personne ne
  regardait l'écran :
      14:47:27  Aucun « Relevez-vous » détecté, fin de la boucle
      14:47:30  l'écran « DÉFI 13 / VICTOIRE » s'affiche
      14:47:33  Bouton 'continue_button' cliqué  (il était là, 6 s trop tard)
  Vérifié après coup sur la capture gardée
  (`captures_reference/victoire_defi13_20261106.png`) : `bilan.juger`
  rend `gagne=True`, gabarit « VICTOIRE » à **0.99**. Tout était en
  place — `bilan.attendre_verdict` regarde déjà quelques secondes — il
  manquait l'appel. Un combat ORDINAIRE, lui, garde ses propres juges :
  une assertion le verrouille. Tests : `test_challenges.
  test_final_boss_exits`, cas (c).

- **UNE RÉCOMPENSE DE COMBAT NE SE FERME PAS, ELLE SE PREND.**
  « RÉCOMPENSES DE COMBAT — Choisissez un objet à équiper sur l'un de
  vos champions », deux champions, trois objets, **+19 PV**. Le bot a
  tourné 120 s dessus et **la SESSION ENTIÈRE s'est arrêtée** sur
  « impossible de revenir à un écran connu ». Le panneau était pourtant
  reconnu — `recompense_select_grise` **1.00** sur
  `captures_reference/recompense_combat_20261106.png` — et
  `events.RECOMPENSE` sait le jouer depuis le 05/11. **Le trou n'était
  pas la reconnaissance, c'était le MOMENT** : `play_reward` ne la
  guette que quelques secondes après le boss intermédiaire, et
  `DISMISS_BUTTONS` n'a rien qui morde ici (« Continuer » 0.32,
  « Quitter » 0.39). `back_to_known_screen` la prend désormais, dans le
  même esprit que son garde « Relevez-vous ». Test : `test_challenges.
  test_une_recompense_de_combat_nest_pas_un_ecran_a_fermer`.

- **L'ÉCRAN DE RÉCOMPENSE PROUVE UNE VICTOIRE, ET IL L'EMPORTE SUR LE
  SECOND « CONTINUER »** (`lor_battle._reward_proves_victory`). C'est ce
  qui a tué la session, et le verdict était INVERSÉ :
      16:05:09  Second « Continuer » : écran de fin, le combat perdu
      16:05:24  tentative 7 : DÉFAITE — combat perdu (boss intermédiaire)
      16:05:27  à l'écran : « RÉCOMPENSES DE COMBAT », +19 PV
  Trois secondes après le verdict, le jeu proposait un objet à équiper
  sur l'un de nos champions. **ON NE REÇOIT PAS ÇA EN PERDANT.** La
  règle du 05/09 reste vraie — elle vient d'observations en jeu — mais
  elle a désormais une exception prouvée, payée d'un coup d'œil de
  `RECOMPENSE_ATTENTE` (10 s) avant de conclure à la défaite. Et la
  cascade explique l'arrêt : le verdict de défaite faisait arrêter le
  parcours, donc `play_reward` n'était jamais appelé, donc le panneau
  restait là. Décision validée par Ewan le 06/11.
- **LE CHOIX CROISÉ DE LA RÉCOMPENSE MARCHE — VU TOURNER DEUX FOIS**
  (14:57 et 15:49) : « récompense proposée (1.00) », validation seule,
  puis clics en **(789, 459)** (champion de gauche) et **(615, 766)**
  (objet de gauche), puis le bouton, puis « plus aucun bouton lisible ».
  Les trois points vérifiés à l'image sur
  `screenshots/recompense_choix_sans_api_20261106_145737.png`. La
  géométrie du 05/11 tient. **Ce qui reste arbitraire, c'est le CHOIX** :
  toujours le plus à gauche des deux rangées, sans rien lire.
- **UN GUET QUI CAPTURE L'ÉCRAN DOIT ÊTRE BOUCHONNÉ DANS LES TESTS.**
  `_reward_proves_victory` photographie pendant dix secondes : branché
  tel quel, il a fait passer la suite hors ligne de 5 s à 15 s et
  **photographié VRAIMENT l'écran d'Ewan 40 fois par exécution**
  (mesuré à l'espion sur `pyautogui.screenshot`). `test_challenges`
  bouchonne donc `navigate.play_reward` dès l'import, comme
  `champions.choisir_champion` et `park_mouse` avant lui. **Un espion
  sur pyautogui dit en une commande si une suite touche la machine** —
  s'en servir dès qu'on branche un guet.
- **CE QUE LA SESSION A DONNÉ** : 8 tentatives en 90 min, 1 victoire,
  4 défaites, 3 inachevées. Le marqueur du joueur masqué tient en jeu
  (0.89-0.99).
- **LA POLICE DU TITRE SE RÉCOLTE SUR LES CAPTURES DÉJÀ GARDÉES.**
  `chiffres/N_defi.png` ne connaissait que 2, 6 et 7 : tout palier écrit
  avec un autre chiffre rendait None, `_pick_first_challenge` retombait
  sur « le plus étoilé », et le bot a dépensé des **7 ★** sur des paliers
  qui n'en demandaient pas — exactement ce que la table d'allocation
  existe pour éviter. Les deux manquants ont été pris sur des captures
  de référence, pas inventés : « DÉFI 11 » sur
  `reprendre_aventure_20261106.png` donne le **1**, « DÉFI 4 » sur
  `champions_selection_20261105.png` donne le **4**. `cut_defi` accepte
  une capture en argument (`cut_defi('11', ecran=img)`) — pas besoin
  d'avoir l'écran sous les yeux. Restent **0, 3, 5, 8 et 9**. Le test
  `test_champions.test_la_police_du_titre_sait_lire_un_palier_a_deux_chiffres`
  est le filet : chaque chiffre appris y gagne une capture témoin, et il
  vérifie en plus que chaque PNG porte bien sa forme en ALPHA — un
  glyphe opaque ne vaudrait rien, `digits` compare l'alpha.
- **LA VICTOIRE DU DÉFI 13 A ÉTÉ REPORTÉE À LA MAIN** dans le journal
  (`journal.conclude` sur le combat `20261106144708-2c0f33`), avec sa
  provenance écrite dans le champ `verdict` : « écran de victoire (relu
  après coup sur la capture gardée) ». Le verdict n'est pas inventé —
  `bilan.juger` le relit sur
  `captures_reference/victoire_defi13_20261106.png`. Garder cette
  provenance est ce qui distingue un verdict mesuré d'un verdict
  supposé, le jour où l'un des deux se trompera.

### La récompense du boss intermédiaire (05/11/2026) — `events.RECOMPENSE`

- **ELLE TOMBE TOUTE SEULE, HORS DE TOUT NŒUD** (Ewan) : après la
  victoire d'un boss intermédiaire, le jeu propose un objet à équiper
  sur l'un de ses champions. `resolve_arrival` n'est appelé qu'en
  ARRIVANT quelque part : personne ne regardait là. Le bot restait
  dessus, cherchait ensuite un nœud derrière le panneau, et abandonnait
  l'aventure.
- **SON BOUTON N'ÉTAIT PAS RECONNU** : `select_button.png` n'y note que
  **0.52**, sous le seuil — le bot ne voyait pas même le bouton, donc ne
  pouvait rien tenter. D'où `assets/recompense_select.png` (1.00 ici,
  ≤ 0.45 sur les cinq autres captures de référence).
- **Même forme que le coffre, PAS la même géométrie.** Mesuré sur
  `captures_reference/recompense_boss_20261105.png`, bouton en
  (961, 1002) : champions centrés en (790, 460) et (1127, 453), objets
  en (615, 767), (960, 767), (1305, 767). Le coffre, lui, a ses
  champions à dy −0,59 et ses objets à −0,247. Une géométrie par
  panneau, reconnue à son repère.
- `navigate.play_reward` la GUETTE quelques secondes après le combat du
  boss intermédiaire et ne fait rien si elle ne vient pas — tous n'en
  donnent pas forcément. Vérifié le 05/11 : panneau absent, aucun clic.
- Tests : `test_events.test_la_recompense_du_boss_demande_deux_clics`.

### Les panneaux à deux rangées (06/11/2026, soir) — deux lois

Deux soirées à réparer le même panneau sous deux formes. Ce qui suit
vaut pour LA RÉCOMPENSE ET LE COFFRE : ils ont la même structure (une
rangée de champions, une rangée d'objets, un bouton qui reste grisé tant
que les deux ne sont pas pris), et donc les mêmes deux pièges.

- **LA RANGÉE DES CHAMPIONS N'A PAS TOUJOURS DEUX CARTES.** Vu en jeu à
  20:19 (récompense) puis à 20:33 (coffre) : TROIS champions là où la
  géométrie mesurée le 05/11 en supposait deux, et le clic tombé **pile
  dans la gouttière**. L'objet était pris, le champion non, le bouton
  restait grisé. C'est le bogue du coffre du 05/11, rejoué deux fois.
  **LA RANGÉE EST CENTRÉE SUR LE BOUTON, À PAS CONSTANT** — récompense :
  bouton 961, pas 342, donc 790/1127 ou 618/960/1301 ; coffre : bouton
  1442, pas 315, donc 1284/1600 ou 1127/1442/1757. Le seul inconnu est
  le NOMBRE, et **le centre le dit** : mesuré sur quatre captures,
  luminosité moyenne de la bande des champions à x=centre — **37-50 à
  deux cartes, 97 à trois**. Seule cette colonne est fiable : les
  positions extérieures descendent à 44-62 selon l'éclairage de la
  carte. D'où `events.champion_le_plus_a_gauche(screen, rangee)` et le
  réglage `Panneau.rangee_champions` — un réglage, pas deux fonctions.
- **RECLIQUER UNE CARTE DÉJÀ PRISE LA DÉSÉLECTIONNE**, et le repli
  géométrique rejouait la paire à chaque tour. Comme ses propres clics
  faisaient changer l'écran, le garde `unchanged == 0` le relançait sans
  fin : le panneau OSCILLAIT — champion pris / objet rendu, champion
  rendu / objet pris, huit tours. **Le bot défaisait ce qu'il venait de
  faire.** Même piège que le clic à l'aveugle de l'événement, qui annule
  la présélection ; ici il annule la sienne.
- **« C'EST PRÊT » SE LIT À LA COULEUR DU BOUTON, pas au gabarit.**
  `recompense_select_grise` matche les DEUX états (1.00 grisé, **0.94
  actif**) : impossible de les distinguer ainsi. La couleur, elle,
  tranche net — **67 % de pixels orangés actif, 0/0/9 % grisé** pour la
  récompense, **64,9 %** pour le coffre. D'où `events.bouton_est_actif`
  et `Panneau.bouton_dore_vaut_pret` : bouton doré = les choix sont
  faits, on valide **sans rien recliquer**.
- **VU TOURNER EN JEU** (20:31) : le panneau de récompense, qui tournait
  en boucle depuis dix minutes, s'est fermé en **2 gestes** — « pris :
  choix déjà faits ». Le coffre, lui, n'a pas été rejoué : à la reprise
  il n'affichait plus « Prendre le trésor » et le rattrapage a cliqué
  « Quitter ». **DETTE** : `back_to_known_screen` sait prendre une
  récompense, pas un coffre — et son `DISMISS_BUTTONS` contient
  `quit_button`, qui JETTE le trésor. À reprendre.
- Captures de référence : `recompense_trois_champions_20261106.png`,
  `recompense_bouton_actif_20261106.png`,
  `coffre_trois_champions_20261106.png`,
  `coffre_bouton_actif_20261106.png`. Tests :
  `test_events.test_la_recompense_peut_avoir_trois_champions`,
  `test_un_bouton_dore_dit_que_le_choix_est_fait`,
  `test_le_coffre_aussi_peut_avoir_trois_champions`.

### La session du 08/11 — une panne MUETTE et le coffre enfin ramassé

- **LA MOLETTE NE PART NULLE PART SI LE JEU N'A PAS LE PREMIER PLAN**, et
  `pyautogui.scroll` ne rend aucune erreur. Un clic ACTIVE la fenêtre
  qu'il touche : tant que le bot ne faisait que cliquer, le focus se
  réparait tout seul et personne n'avait à y penser. Unity, lui, ne
  traite la molette que fenêtre ACTIVE. Mesuré, même geste, même point :
  **écart entre deux captures 33.6 fenêtre active, 0.04 sans**.
  `champions._parcourir` lisait ce silence comme « bas de liste
  atteint », jugeait le premier écran venu — six vignettes TOUTES
  épuisées — et renonçait au choix du champion. D'où
  `gestures.focus_game_window()` (pywin32, dégradation douce : pas de
  pywin32, pas de jeu, ou bascule refusée par Windows → False sans rien
  casser), et `_defiler`/`_remonter` DISENT si le geste est parti.
  **« Rien n'a bougé » ne veut dire « on est au bout » que si le geste
  est parti.** Seul `champions.py` utilise la molette. Tests :
  `test_champions.test_une_molette_qui_nest_pas_entendue_nest_pas_un_bout_de_liste`.
- **LE REPLI `first_champion` VISE LE HAUT DE LA GRILLE — il faut donc y
  être revenu.** Quand `choisir_champion` échoue, il laisse la grille où
  son parcours l'a menée : EN BAS. Mesuré, `first_champion` y note
  **0.64** pour un seuil de 0.80. Le filet documenté depuis le 05/11 ne
  pouvait donc JAMAIS se déclencher après un parcours. D'où
  `champions.revenir_en_haut()`, appelé par `navigate._pick_champion`
  avant de chercher le bouton.

- **UN GLYPHE NON RECONNU ÉTAIT SAUTÉ, ET « 19 » DEVENAIT « 1 ».**
  `lire_palier` promet « jamais une valeur approchée » ; `read_number`
  ne la tenait pas. Le titre « DÉFI 19 » portait un 9 absent de la
  police du titre : le 9 était jeté en silence et le bot lisait le
  palier **1** — la table aurait demandé 3 étoiles au lieu de 4.
  Désormais un glyphe **de la taille d'un chiffre du nombre** qu'on ne
  sait pas lire REFUSE le nombre entier. La bande est ÉTROITE à dessein
  (`UNKNOWN_HEIGHT_BAND` = 0.85-1.15) : les vrais badges portent du
  décor que `glyph_boxes` laisse entrer exprès — bord de gemme à 15 px
  contre un chiffre de 23, éclat de cadre à 12 contre 16 — et la bande
  large de `MIN_RELATIVE_HEIGHT` aurait refusé ces lectures-là.
  **Effet de bord heureux** : le piège du bilan (« 0 / 20 » lu 20 sur un
  écran de DÉFAITE) est désamorcé à la source — la lecture naïve avoue
  maintenant ne pas savoir. `test_bilan` le dit désormais ainsi.
- **UNE POLICE SERT LÀ OÙ ELLE A ÉTÉ RÉCOLTÉE.** `chiffres/N_defi.png`
  a été créé le 05/11 pour le titre, avec la remarque « ce n'est pas la
  police des coûts » — mais `load_variants` la servait à TOUTES les
  lectures. Mesuré : le « 9 » du titre, pourtant fidèle, reconnaissait
  un morceau d'ILLUSTRATION de carte comme un 9 (0.61, marge 0.12), ce
  que `test_digits` interdit depuis toujours. D'où
  `digits.RESERVED_FAMILIES` et `load_variants(families=)` ;
  `lire_palier` demande `("defi",)`.
- **ET `cut_defi` DÉCOUPAIT UNE FORME QUE LE LECTEUR NE VOIT PAS.**
  L'alpha venait d'un seuil de clarté à 120 sur le glyphe DORÉ, alors
  que `lire_palier` BLANCHIT le doré puis passe par `digits.glyph_mask`.
  Mesuré sur le « 9 » : 336 pixels contre 406, **IoU 0.83** — la police
  apprise ne se reconnaissait pas elle-même (0.652 contre son propre
  gabarit, 0.691 contre le 6, marge 0.04 sous un plancher de 0.06).
  Deuxième défaut empilé dessus : `glyph_mask` rend **0/1** et
  `digits._read_mask` relit l'alpha à **>= 128** — le gabarit était
  écrit, puis IGNORÉ au chargement, sans un mot. On découpe désormais
  par le chemin de lecture, en ne gardant que la plus grosse composante.
  Palier 19 lu juste. Capture témoin :
  `captures_reference/champions_defi19_20261108.png`. Restent 0, 3, 5, 8.

- **UN COFFRE N'EST PAS UNE RÉCOMPENSE, et `recompense_select_grise`
  note 0.83 SUR UN COFFRE** — au-dessus du seuil. C'était la dette
  laissée le 06/11 (« `back_to_known_screen` sait prendre une
  récompense, pas un coffre ») et elle a coûté la session : la géométrie
  de la récompense est ancrée sur un AUTRE bouton (961 contre 1442), les
  clics sont partis en (1270, 459) et (1096, 766) — nulle part — huit
  fois, puis « écran inconnu » et arrêt. Les deux panneaux se
  départagent sans ambiguïté, **mesurés sur la MÊME capture** (règle de
  `where_are_we`) : coffre/trésor **1.00 contre 0.83** sur un coffre,
  **≤ 0.32 contre 1.00** sur une récompense.
- **ET ON REGARDE AVANT DE MARCHER SUR LA CARTE.** Vu TROIS fois le
  08/11 : quand une aventure est reprise alors qu'un panneau est encore
  ouvert, `where_are_we` reconnaît la CARTE (le panneau n'en couvre
  qu'une partie), et le parcours part chercher des nœuds DERRIÈRE le
  panneau — exactement la perte du 05/11. `back_to_known_screen` ne
  pouvait rien : il n'est appelé que sur un écran INCONNU. D'où
  `navigate.prendre_panneau_ouvert`, appelée aux DEUX endroits — au
  départ de `run_adventure` et dans le rattrapage. **Le jeu l'écrit
  lui-même** : tant que le coffre n'est pas résolu, son nœud affiche
  « Quelque chose vous bloque la route… » et AUCUN nœud n'est joignable.
  Tests :
  `test_challenges.test_un_coffre_reste_ouvert_nest_pas_une_recompense`.

- **TROISIÈME LOI DES PANNEAUX À DEUX RANGÉES : UNE TUILE DÉJÀ PRISE NE
  SE RECLIQUE PAS.** Mesuré en jeu, un clic à la fois :

      Rek'Sai seul                -> bouton GRIS
      + clic sur Grande Massue    -> LES DEUX pris, bouton ACTIF
      re-clic sur Rek'Sai         -> la paire est cassée

  **Le jeu PRÉSÉLECTIONNE un champion**, et le repli à l'aveugle
  cliquait toujours les DEUX tuiles : il défaisait donc la présélection
  à chaque tour. Sur onze captures d'affilée l'alternance est parfaite,
  et le bouton n'est **JAMAIS doré** (0 % d'orange sur les onze) — le
  garde `bouton_dore_vaut_pret` du 06/11 ne pouvait pas s'armer, **il
  regarde trop tard**. Le liseré d'une tuile prise se lit À LA HAUTEUR
  DU CLIC sur ses deux bords, ce qui évite d'avoir à connaître ses
  bornes verticales : **255 prise contre 102 libre**, sans cas
  intermédiaire (`events.tuile_est_prise`). Le liseré est moins net sur
  la rangée des champions de la RÉCOMPENSE (232/220/225) : d'où la porte
  de sortie `tout_recliquer` — un tour qui saute un clic sans que le
  bouton s'allume fait recliquer tout au tour suivant, l'ancien
  comportement.
- **ET LE SEUIL ABSOLU DU NOMBRE DE CHAMPIONS A LÂCHÉ.** Le 06/11 on
  lisait la luminosité du CENTRE contre 70 (« entre 50 en gouttière et
  97 sur une carte »). Un coffre à trois champions dont la carte du
  milieu avait une illustration sombre (Poppy) a noté **68.8** : 1.2
  sous le seuil, « deux cartes », clic PILE DANS LA GOUTTIÈRE. Une
  luminosité absolue dépend de l'illustration, **un ÉCART non** : les
  deux dispositions placent exactement une carte là où l'autre place du
  vide, donc on compare les deux colonnes candidates. Séparation
  **9 captures sur 9**, 38 points d'écart dans le pire cas. Tests :
  `test_events.test_une_carte_sombre_ne_fait_pas_disparaitre_un_champion`,
  `test_on_ne_reclique_pas_une_tuile_deja_prise`.
- **VU TOURNER EN JEU LE 08/11** : le coffre qui avait fait perdre trois
  aventures d'affilée s'est fermé en **3 gestes** — « Coffre resté
  ouvert (1.00 contre 0.83) : on le RAMASSE avant d'aller plus loin »,
  clics en (1126, 361) et (1126, 735), « plus aucun bouton lisible, on
  reprend la route » — le nœud a pris sa coche verte, et la route s'est
  ouverte jusqu'au boss final.
- **LE MARQUEUR DU JOUEUR N'ÉTAIT PAS LE MARQUEUR DU JOUEUR** (08/11,
  confirmé par Ewan). J'avais d'abord écrit ici que le gabarit masqué
  « tourne en jeu » parce qu'il notait **0.90** là où il tombait à
  0.56-0.61 avant. **Le score était bon, la cible non** : il suit un
  **losange doré vide**, un décor de tracé. Notre position est un
  **médaillon ROND portant le portrait du champion joué**, le même
  dessin que le portrait du HUD. Sur une capture du 08/11 : losange
  0.90 en (318, 477), médaillon en (960, 451) — **642 px d'erreur**.
  Sur les 94 captures de carte où le médaillon est lisible, l'ancien
  `_player_position` passait son seuil 43 fois **en désignant un point à
  219-913 px de nous** (médiane 445), et échouait les 51 autres.
  **LA LEÇON DU 06/11 RETOURNÉE CONTRE ELLE-MÊME** : on avait réparé un
  repère « presque reconnu » sans vérifier qu'il désignait la bonne
  chose. Un bon score ne prouve que la fidélité du gabarit, jamais la
  justesse de la lecture.
  **UN GABARIT FIGÉ NE PEUT PAS MARCHER** : le portrait change à chaque
  champion. D'où `marqueur_joueur.py`, qui DÉCOUPE LE GABARIT À LA VOLÉE
  dans le HUD (anneau d'XP ajusté en cercle, centre (116.5, 972.5),
  rayon 66.7, stable à ≤ 0.5 px), masque circulaire, multi-échelle
  0.575-0.875. Mesuré sur 285 captures : **128 médaillons de 0.775 à
  0.943**, meilleur pic sans médaillon **0.656**, seuil **0.70**, **zéro
  faux positif**. Second garde-fou indispensable : hors aventure il n'y
  a pas de portrait dans le HUD, on découpe un APLAT, et un aplat
  corrélé à un aplat monte à 0.94-0.96 sur un point qui ne veut rien
  dire — d'où le refus par contraste (écart-type des gris ≥ 30 : 48-64
  avec portrait, 0.9-20 sans). `MARQUEUR_LOSANGE = True` remet l'ancien
  chemin entier. Tests : `test_marqueur.py`. **PAS ENCORE VU TOURNER EN
  JEU.**
- **ET LA RÈGLE « LE PLUS PROCHE À DROITE » ÉTAIT CALIBRÉE SUR UNE
  POSITION FAUSSE.** Avec une origine 400-900 px trop à gauche, tout
  passait « à droite ». Avec la vraie position elle devient stricte, et
  sur une capture du 06/11 les deux nœuds joignables sont **DESSOUS**.
  Mesuré sur 53 décisions rejouées : « le plus proche » tout court est
  d'accord avec l'ancien code 49 fois sur 53, contre 47 pour la règle
  livrée. **Seul le dernier recours de `locate_node` a changé** (« le
  plus à gauche » → « le plus proche ») ; `pick_next_node` est intact.
  Passer à « le plus proche » partout remplacerait une règle écrite sur
  une observation en jeu du 02/09 : **c'est un fait de jeu, il doit
  venir d'Ewan.**
- **DEUX FAUX POSITIFS DE L'INTERFACE, jusqu'ici masqués par la position
  fausse** : les gabarits de nœud matchent le **bouton boussole** à 0.85
  en (1819, 470), et la **flèche retour** du coin haut-gauche à
  0.81-0.83 sur quatre captures. Le second disqualifie « le plus à
  gauche » comme dernier recours. À reprendre.
- **LE BOSS FINAL EST CACHÉ PAR NOTRE PROPRE PORTRAIT** (08/11). Une
  fois le voyage fait, le jeu dessine notre médaillon de champion
  par-dessus le nœud du boss et il couvre **entièrement la crête dorée**
  — c'est-à-dire exactement ce que `assets/final_boss.png` comparait.
  Score 0.33 au bon endroit, 0.54 à 970 px de là : le bot ne pouvait
  plus retrouver le boss après l'avoir rejoint. S'y ajoutait le défaut
  du 06/11 (le **halo bleu** dans la boîte, qui n'existe qu'à l'état
  « joignable » : 0.87 avec, 0.59 sans). **Un masque ne rattrape pas une
  forme cachée** : le gabarit vise désormais l'**or des ailes et de
  l'anneau**, seules parties qu'aucun des trois états ne couvre, en
  multi-échelle (le zoom de la carte varie de 8 %). Mesuré sur 880
  captures : 0.986 / 1.000 / 0.843 / 0.832 selon l'état, **0 régression,
  48 captures gagnées, 0 faux positif**, les combats plafonnent à 0.53.
  Le multi-échelle est déclaré **par gabarit** — tous les autres gardent
  le chemin d'avant. Prix : 0.66 à 1.12 s par lecture contre 0.09 s.
  Recette du masque (non versionné, `assets/` est ignoré par git) :
  `python -c "import adventure_navigation as an; an.decouper_final_boss()"`.
  **PAS ENCORE VU TOURNER EN JEU.**
- **UNE PARTIE QUI N'A JAMAIS DÉMARRÉ N'EST PAS UN COMBAT PERDU**
  (08/11). Le clic « Combat » du boss final n'a rien lancé ; personne ne
  regardait, et la cascade a coûté une tentative : 122 s d'attente API
  (`wait_for_game_start` ne regarde jamais l'écran), puis un clic au
  centre de la CARTE pour « fermer l'écran de résultat », 48 s de
  recherche de « Continuer », et le motif « aventure terminée » sur une
  aventure dont le boss était intact. `CombatReport.never_started` (API
  qui répond « menus », distinct de `api_down`) → `try_combat` rend la
  main aussitôt, `NOT_STARTED_PREFIX` nomme la panne.
  **ET ON VÉRIFIE QUE LE CLIC A PRIS** : `confirmer_le_lancement` regarde
  3 s si « Combat » a disparu, GARDE L'ÉCRAN sinon
  (`screenshots/combat_sans_effet_*.png`), range la souris et reclique,
  3 fois au plus. Rendre False n'arrête RIEN : un panneau encore lisible
  peut être un chargement qui se pose. **Pourquoi la capture est le vrai
  livrable** : ce jour-là `combat_button` notait **0.96** au lieu de 1.00
  sur les 19 combats lancés les 04-06/11, et `event_option` **0.27** au
  lieu de 0.55 — le panneau n'était pas dans son état habituel, et
  **aucune image n'avait été gardée** pour savoir lequel. Les 19 combats
  démarrent en 2,8 à 7,5 s : les 120 s n'ont jamais été la cause.
- **`check.py` REFUSE DÉSORMAIS UNE SUITE QUI TOUCHE LA MACHINE**
  (`garde_machine.py`). Chaque suite tourne derrière des mouchards posés
  sur `pyautogui` et sur les fonctions de fenêtre ; le verdict s'affiche
  à côté du `[OK]`, nomme la suite, compte les gestes et donne **la pile
  du premier appel de chaque geste distinct** — une seule pile aurait
  manqué le second chemin. **Compter, pas bloquer** : bloquer rendrait
  rouge une suite verte et son verdict ne dirait plus ce qu'elle teste ;
  c'est `check.py` qui fait du décompte un échec. `GARDE_MACHINE=bloquer`
  pour enquêter. Surcoût +0,5 %. Il a attrapé sa première fuite le jour
  de sa naissance.
- **UN BOUCHON PAR NOM IMPORTÉ, PAS UN PAR FONCTION** : `test_challenges`
  bouchonnait `lor_battle.park_mouse`, mais `navigate.py` en a importé sa
  PROPRE référence — 28 déplacements réels du curseur passaient par là,
  et `restore()` remettait la vraie. Le commentaire du bouchon le disait
  déjà (« ailleurs, il passait ») sans en tirer la conséquence.
- **UN ESPION SUR PYAUTOGUI DIT EN UNE COMMANDE SI UNE SUITE TOUCHE LA
  MACHINE — et c'est la QUATRIÈME fois qu'elle la touche.** Après
  `park_mouse`, `choisir_champion` et `play_reward`, c'est
  `revenir_en_haut` qui a glissé : **220 coups de molette et dix vols de
  focus** par exécution de `test_challenges`, plus une vraie capture
  d'écran introduite par le garde du coffre. Bouchonnés tous les deux.
  **DETTE** : cet espion gagnerait à entrer dans `check.py` plutôt que
  de rester un outil qu'on pense à lancer.

### Nœuds d'événement (04/09/2026) — `events.py`

- **Un événement se JOUE, il ne se fuit plus.** Vu sur « La Grand-place » :
  l'option « S'entraîner » ouvre « Ajoutez Challenger sur une unité de
  votre deck » (3 cartes) ; « Sélectionner » est GRISÉ tant qu'aucune
  carte n'est cliquée — le template `select_button.png` matche pourtant
  le bouton grisé à 0.94. `navigate.resolve_arrival` → `play_event` →
  `events.resolve_event(reader, capture, save_screen)` : à chaque tour,
  UN geste — (1) cartes proposées lues par l'API (`offered_cards` : ≥ 2
  cartes à nous à la même hauteur) → `choose_deck_card` (niveau 2 >
  champion > unité > `unit_value` > coût > connue) + « Sélectionner » ;
  (2) « Sélectionner » vu sans carte lisible → clic sur la carte du milieu
  (`CARD_ABOVE_SELECT` = 0.575 de la hauteur au-dessus du bouton) puis le
  bouton, écran gardé `evenement_choix_sans_api` ; (3) « Continuer » /
  « Quitter » → clic ; (4) une nouvelle `event_option` (UNE seule par
  événement) ; (5) plus rien d'un événement → sorti ; (6) écran figé →
  FLÈCHE RETOUR (`BACK_ARROW_RATIO` 0.052, 0.079), écran gardé
  `evenement_bloque`. `EVENT_MAX_STEPS` = 8.
- « Sélectionner » à l'ARRIVÉE : on le clique d'abord (le champion de
  soutien est présélectionné) ; s'il est toujours affiché après le clic,
  un choix est attendu → `play_event("choix")`.
- **VALIDER SEUL D'ABORD (05/11/2026).** Le jeu PRÉSÉLECTIONNE : sur
  « choisissez vos renforts », un paquet est déjà encadré d'or à
  l'ouverture, et valider suffit. Le clic « à l'aveugle » sur la carte du
  milieu, lui, tombe AU-DESSUS des cartes sur ce panneau-là
  (`CARD_ABOVE_SELECT` = 0.575 donne y≈382 ; les cartes sont à 455, 525,
  600) et **annule la présélection** — après quoi le bouton est inerte.
  Le 05/11 : huit tours sans sortir, panneau laissé ouvert, le bot est
  parti chercher un nœud derrière le panneau et la tentative s'est
  perdue. Le même geste avait pourtant marché le matin en deux tours :
  c'était un coup de dés. Donc `resolve_event` tente le bouton SEUL au
  premier tour — il ne peut jamais DÉfaire une sélection, contrairement
  au clic géométrique.
- **Le repli géométrique garde UN essai même sur un écran figé** : valider
  sans rien avoir choisi ne change rien à l'écran, et un garde
  `unchanged == 0` seul aurait privé le repli de sa chance — on serait
  sorti par la flèche retour en abandonnant l'événement.
- Le titre du panneau n'est PAS lu (pas d'OCR de texte) : le choix est
  générique. Tests : `test_events.py`.

### Chantiers du 03/09/2026 (soir) — audit « API ou autre »

- **Blocage diagnosticable** : à chaque palier de `_check_progress`
  (12 / 25 / 40 lectures), `snapshot.summary()` va au rapport (`[état] …`)
  et `save_stuck_screen` écrit `screenshots/bloque_<PHASE>_<date>.png`.
- **Champions** : `BoardCard.supertype` / `collectible` depuis card_sets →
  `is_champion`, `is_leveled` (niveau 2 = code non collectionnable …T1/T2,
  rapporté par l'API : AUCUNE vision). `keywords.unit_value` ajoute
  `CHAMPION_BONUS` 2 / `LEVELED_BONUS` 4 ; `CombatLoop._note_level_ups`
  journalise « Niveau 2 : notre/son champion X est monté » une fois par carte.
- **`/static-decklist`** (`lor_api.get_static_decklist`) : lu une fois par
  partie (`_deck_for_game`), `snapshot.deck`, `deck_remaining()` (borne
  haute), `is_generated(card)` ; ligne « deck : N cartes, ≤ M à piocher »
  dans `summary`.
- **Chiffres par la forme — `digits.py`** : masque de glyphe HSV (blanc /
  vert / rouge / bleu clair, orange exclu), composantes connexes, IoU sur
  masques normalisés à 32 px avec décalages ±3 et ÉGALISATION D'ÉPAISSEUR
  du trait (un glyphe lu est plus gras que le template). Deux paliers :
  SÛR (`CONFIDENT_SCORE` 0.72 / marge 0.10) → pas d'OCR ; CANDIDAT
  (`MIN_SCORE` 0.60 / 0.06) → l'OCR tranche, le candidat ne sert que si
  l'OCR ne lit rien (`loose=True`). Branché dans `game_state._cached_ocr`
  (stats, coûts) et `mana.read_digits` (mana, PV nexus). ~2-3 ms. Mesuré
  7/7 sur debug_cards/ et spell_mana.png (`test_digits.py`). Les templates
  sont `chiffres/0-9.png` (alpha = forme) ; en ajouter d'autres graisses
  améliore la marge.
- **Libellé du bouton de tour** : `assets/orb/<label>.png` (fourni :
  `resoudre.png`, tiré de calibration_crops/orbe_de_tour_zone.png — LE
  BOUTON EST BLEU ET DIT « RÉSOUDRE » pendant une fenêtre de réponse, donc
  la lecture couleur de l'orbe tient). `read_turn_button` → `snapshot.
  button_label` ; « resoudre » + orbe bleue → `SPELL_STACK` même si l'API
  n'a pas rapporté le sort. `python game_state.py cut-button fin_du_tour`
  enregistre le libellé affiché maintenant. **`cible.png`** (« SÉLECTIONNER
  LA CIBLE », 05/09/2026) : le jeu attend que NOUS désignions une cible →
  `respond_to_stack` ANNULE (clic droit) au lieu de cliquer « OK » (12 « OK »
  dans le vide, 50 s, sur un sort inconnu 07BW043 parti sur la pile).
- **On vise la main sur une lecture FRAÎCHE** (`actions.fresh_hand_card`,
  05/09/2026, deck Nilah qui pioche en série) : si l'instantané qui a
  décidé a plus de `AIM_MAX_AGE` = 0,8 s (le temps de l'OCR des coûts),
  `play_card` et `play_spell` relisent la main, attendent
  `HAND_QUIET_CONFIRMATIONS` = 3 relectures immobiles (`wait_until_settled(
  confirmations=…)` — une seule tombe ENTRE deux pioches) et retrouvent la
  carte par CardID. Sinon la voisine est attrapée. `GameSnapshot.taken_at`
  porte l'heure de lecture ; un test qui laisse vieillir un instantané avant
  `play_card` doit le rafraîchir (`snap.taken_at = time.time()`).
- `set7.json` n'a que 83 cartes : les extensions de milieu de saison sont
  des fichiers `set7b`… `LoR-Bot/code/download_card_sets.py` RÉÉCRIT le
  06/09/2026 (l'ancien n'avait pas de `__main__` et écrivait dans un
  `card_sets` relatif au cwd) : chemin absolu, toutes les variantes de nom
  par numéro, `--force`, bilan. À lancer sur le PC d'Ewan.
- **Saisie dans une main pleine** (06/09/2026) : `group_by_zone` →
  `mark_hand_overlap` pose `visible_right` sur chaque carte que sa voisine
  de DROITE recouvre (le jeu dessine la main en éventail, chaque carte SOUS
  la suivante) ; `grab_point` vise le milieu de la partie VISIBLE. Avant :
  centre géométrique à 11 px de la voisine → « The List » attrapée à la
  place de Buhru Lookout, 14 fois de suite.
- **Une pose ratée met la carte de côté pour TOUT LE ROUND** :
  `CombatLoop._carry = {"codes", "mana"}` → `play_turn(carry=)` →
  `play_hand(carry=)` ; vidé quand le mana lu REMONTE (= round suivant).
  Avant, `failed` renaissait à chaque ré-entrée après une pile : même geste
  raté en boucle jusqu'à la durée maximale du combat (900 s le 06/09).
- **La « fenêtre imprévue » 07SH013T6 + carte jouée N'EST PAS un faux
  positif** : 07SH013 est Nidalee (« Ambush »), la fenêtre est réelle et
  le bot y garde la carte jouée. Ne pas exclure la carte jouée des options
  (`test_unknown_card_with_a_surprise_choice_window` le verrouille).

### Chantiers 4-5-6 du 06/09/2026

- **Duels dirigés** (`spells._duel_steps`, `choose_duel_targets`) : « An
  ally strikes an enemy », « An ally starts a free attack Challenging an
  enemy » (Cataclysm), « Give an enemy -2|-0 … An ally and that enemy strike
  each other » (Desert Duel) → `SpellPlan(duel=True, sequence=…)`, deux
  clics DANS L'ORDRE DU TEXTE (Desert Duel : l'ennemi d'abord). Le choix se
  fait PAR PAIRE avec `keywords.resolve_duel` (malus d'attaque appliqué à
  l'ennemi) ; on lance seulement si l'ennemi meurt et que le bilan est
  positif, sinon « duel défavorable » (motif de contexte). Les marqueurs
  QUALIFIÉS (« An Equipped ally », « A battling ally ») restent refusés :
  condition invérifiable, le clic serait rejeté.
- **« Deal 2 to a champion or 4 to a follower »** (`_or_alternative`) : deux
  marqueurs reliés par « or » = UN clic ; `amount` (suivant) et
  `amount_champion`, `plan.damage_to(card)` dans `best_kill`.
- **Le nexus est l'objectif** : `actions.nexus_weight(pv)` = max(1, 40/pv),
  plafond 6, passé à `evaluate_attack`/`plan_challenges` par `plan_attack`.
  PV inconnus → poids 1 (ancien comportement). Le journal l'écrit :
  « (1 dégât au nexus vaut 4.0) ».
- **PV du nexus** : `chiffres/N_nexus.png` (police du nexus, découpée des
  captures de la trace du 06/09 ; 0-5 et 9 seulement) — `digits.load_variants`
  : le score d'un chiffre est celui de sa MEILLEURE variante, la marge entre
  deux chiffres différents. 66/66 lectures strictes sur la trace (0/66
  « illisibles » sur « 24 » et « 4 » avant). `mana.NEXUS_HEALTH_MAX` = 99
  (boss et reliques dépassent 30).
- **Des dégâts sans chiffre sont des dégâts** (`^deal damage` → DAMAGE ;
  « equal to my Power » → `unit_play_plan` met `amount = card.attack`) et
  **« transform » est un malus** (TRANSFORM dans HARMFUL → plus grosse unité
  adverse). Sans ça, Banana Blaster et Minimorph tombaient en AUTRE → cadeau
  à un allié → sans allié, posés SANS cible → partie figée (25 min le 06/09).
  Effet AUTRE sur « a unit » sans allié : on vise un ennemi plutôt que rien.
- **Une carte figée en l'air est BANNIE pour le combat**
  (`CombatLoop._ban_pending_cards` au palier d'annulation, orbe à nous, nos
  cartes en bande « attack »/« stack » → `carry["banned"]`, jamais vidé ;
  `play_hand` la saute). Le `carry` par round ne suffisait pas : l'annulation
  arrive un round plus tard et `play_card` avait conclu « posée ».
- **Combat coupé par la durée maximale** : `CombatReport.interrupted`
  (partie encore en cours) → `try_combat` ne clique rien, navigate rend
  `INTERRUPTED_PREFIX` (« combat interrompu »), challenges s'arrête sur ce
  motif sans chercher d'écran connu. `DEFAULT_MAX_DURATION` = 1500 s.
- `turns_played` : un tour coupé par la pile ne compte qu'une fois
  (`_turn_open`, réarmé en phase d'attente).

### Stratégie par deck (06/09/2026) — `strategy.py`

- **Le deck dit comment jouer.** Le bot prend le premier champion de la
  liste (`navigate._pick_champion`), donc un deck différent à chaque
  tentative (Nilah/Jarvan, Nidalee/Nasus, Bard/Lucian vus le 06/09) — et
  il les jouait tous pareil (7 défaites sur 7). `CombatLoop._note_deck`
  lit `snapshot.deck` (`/static-decklist`), `strategy.profile_deck` compte
  des SIGNAUX dans card_sets (déclencheurs « Attack: », effets au nexus,
  Overwhelm/Elusive/QuickStrike/Fearsome, Challenger, Vulnerable accordés,
  duels dirigés, sorts de retrait, courbe) et choisit un archétype :
  `aggro` (nexus ×2, bilan ≥ −1 si des dégâts passent, mulligan > 2),
  `tirage` (×1,2), `midrange` (×1,5), `controle` (×1, mulligan > 4). Un
  plan l'emporte à partir de `MIN_VOTES` = 5 et `LEAD` = 1,5 devant le
  suivant, sinon midrange.
- **`actions.STRATEGY` porte la stratégie du combat** (`set_strategy`,
  remise à `DEFAULT` au début de `run()`) ; `plan_attack(snapshot, pv,
  strat=None)` la lit par défaut, `nexus_weight(pv, base)` prend son
  poids de base, `evaluate_attack(..., trigger_bonus)` ajoute la valeur
  des « Attack: » (`strategy.has_attack_trigger`, tête de ligne
  seulement — « When you attack » n'en est pas un). **`DEFAULT` = l'ancien
  comportement à l'identique** : les tests qui n'en parlent pas jouent
  comme avant, ne pas changer ses nombres.
- **Le plancher n'achète qu'une attaque qui TOUCHE le nexus**
  (`acceptable` dans `plan_attack`) : perdre une unité pour rien n'est
  jamais de la pression.
- Le journal enregistre `archetype` (dans `CONFIG_FIELDS`) et
  `champions` : c'est `python journal.py` qui réglera ces nombres, pas
  l'intuition. `python strategy.py --traces` relit les decks enregistrés ;
  `decks_lor.md` décrit chaque deck et son plan. Tests : `test_strategy.py`.

### Fin de partie (03/09/2026)

- **Le verdict arrive APRÈS le retour aux menus.** Le journal montrait 47
  combats sans `gagne`. `GameStateReader.final_result(timeout=8)` relit
  `/game-result` quelques secondes quand `CombatLoop` sort sur « retour aux
  menus » ; GameID monté → `won` rempli, raison « partie terminée (résultat
  lu aux menus) ». Sans verdict lisible, `won` reste None — jamais inventé.

### Allouer les champions sur 70 paliers (05/11/2026, Ewan)

- **70 DÉFIS, DÉBLOQUÉS UN PAR UN** : « le premier » monte à mesure
  qu'on les réussit. `_pick_first_challenge` joue donc toujours le
  PALIER COURANT, et la difficulté croît toute seule au fil du mois.
- **TROIS TENTATIVES PAR CHAMPION ET PAR MOIS.** D'où un problème
  d'allocation, pas seulement de choix : griller les 7 ★ sur les
  premiers paliers, c'est arriver aux derniers avec des 3 ★. « Prendre
  le plus fort » est donc FAUX passé les premiers paliers.
- **PLANCHER À 3 ÉTOILES** : les 1 et 2 ★ ne gagnent pas, même en bas —
  ils sortent du pool, ils ne sont pas « les champions des paliers
  faciles ».
- **L'asymétrie qui règle la table** : une défaite coûte une tentative ET
  ne fait avancer de rien. Se tromper par excès de force gâche des
  tentatives de 7 ★ ; se tromper par défaut gâche la tentative *et* le
  palier.
- Table de DÉPART, à corriger par les parties :
  `étoiles ≥ 3 + (palier − 1) // 14`, plafond 7 — paliers 1-14 → 3 ★,
  15-28 → 4 ★, 29-42 → 5 ★, 43-56 → 6 ★, 57-70 → 7 ★.
- **LE JOURNAL NE CONNAISSAIT QUE DES COMBATS**, donc « quel champion
  pour quel palier ? » n'avait aucune réponse possible. `journal.
  record_attempt` écrit désormais une ligne de TENTATIVE (`type:
  "tentative"`) : palier, étoiles du champion retenu
  (`champions.DERNIER_CHOIX`), issue, durée, nombre de combats. Une
  ligne SANS `type` est un combat (`journal.est_combat`) — tout ce qui
  lit les statistiques de combat filtre là-dessus, sinon une tentative
  sans `config` polluerait le tableau des configurations.
- **LE PALIER SE LIT SUR LE TITRE** (`champions.lire_palier`) : les
  glyphes de « DÉFI N » sont espacés de 6-7 px et le NOMBRE de 21 — on
  coupe au plus grand écart, aucun OCR de texte. Deux pièges mesurés :
  le titre est **doré**, et `digits.glyph_mask` exclut l'orange à
  dessein, donc il faut BLANCHIR avant de lire (même parade que les PV
  du bilan) ; et ce n'est pas la police des coûts, d'où
  `chiffres/N_defi.png` — amorcée avec le seul « 2 » du 05/11/2026 et
  enrichie par `python champions.py cut-defi <N>`, comme `N_nexus.png`
  livré avec 0-5 et 9. Un chiffre absent rend None, jamais une valeur
  approchée. Le petit « DIFFICULTÉ ★ N », lui, reste illisible (le « 1 »
  fait 5×18).
- **À ÉTOILES ÉGALES, LE PLUS HAUT NIVEAU — DONC LA DERNIÈRE DE LA
  BANDE** (Ewan, 05/11/2026 : « tente avec un 3 étoiles de plus haut
  niveau »). La grille étant triée par étoiles PUIS par niveau, la
  première vignette qui atteint la cible est la moins chère en étoiles
  mais la plus FAIBLE en niveau de sa bande : c'est ce que le bot a pris
  au palier 6, et il a perdu. On descend donc tant que la bande dure, et
  dès qu'un écran n'en contient plus on remonte d'UNE rangée pour
  cliquer la dernière. On ne clique jamais une position mémorisée —
  elle aurait défilé.
- **LE SENS DU PARCOURS DÉPEND DE LA CIBLE.** Sans cible on descend au
  bas de la liste (les plus forts y sont). Avec une cible on REMONTE EN
  HAUT puis on descend rangée par rangée jusqu'au premier qui l'atteint :
  la grille étant croissante, c'est aussi le moins cher. Descendre dans
  les deux cas ramenait un 7 ★ pour un palier qui en demande 3 — le
  parcours annulait la table.
- `python journal.py --champions` : taux de victoire par (palier,
  étoiles). C'est lui qui doit corriger `etoiles_requises`.
- **UNE SUITE HORS LIGNE NE DOIT PAS ÉCRIRE DANS LE JOURNAL.** La
  première version de cette brique y a ajouté **30 fausses tentatives**
  en une exécution de `check.py --offline` (nettoyées le 05/11).
  `test_challenges` bouchonne `journal.record_attempt` et GARDE les
  appels, pour pouvoir quand même vérifier ce qui aurait été écrit.

### Le choix du champion (05/11/2026) — `champions.py`

- **LA GRILLE EST TRIÉE DU PLUS FAIBLE AU PLUS FORT**, donc
  `first_champion.png` — le haut de la grille — prenait **le pire
  champion du compte**, à chaque tentative. Mesuré sur la grille d'Ewan :
  Zoé 1 ★, Nunu 1 ★, Hecarim 2 ★ en tête ; tout en bas Ahri et Teemo
  « Fleur spirituelle » à **7 ★**. Le 04/11 le bot jouait le défi 2 avec
  Shen à 1 ★, pour finir à 0/20 PV. Première victoire du bot le 05/11,
  avec Teemo 7 ★ : 72 combats et 0 victoire avant, 1 victoire à la
  première tentative après. Un seul point, mais il porte.
- **Les étoiles se comptent par leur ORANGE, EN CHAÎNE** : glyphe 23×23
  (aire 141-161), écart **26,0 px** exactement depuis le x de la colonne,
  on s'arrête au premier trou. C'est ce qui écarte le bruit des
  illustrations sans liste d'exceptions — sur Fiddlesticks le masque
  trouve 8 taches, écarts `26, 26, 26, 26, 26, 59.8, 15.9` : la chaîne
  casse à la sixième, 6 ★ et non 8.
- **LA CHAÎNE SE SUIT SUR LE MASQUE, PAS SUR LES TACHES.** Une vignette
  SÉLECTIONNÉE est en surbrillance : l'aire d'un glyphe passe de 141-156
  à 229-233 (au-dessus de l'ancien plafond : la vignette disparaissait de
  la lecture) et des glyphes voisins FUSIONNENT en une seule tache de
  101×32 (chaîne cassée : 6 étoiles au lieu de 7). Si le meilleur
  champion se trouvait être celui déjà sélectionné, le bot le sautait.
  On teste donc la densité d'orange à l'endroit attendu — mesuré 85 à
  107 pixels sur 121 au centre d'une étoile, 0 à 9 dans un vide. C'est la
  TAILLE du glyphe (23×23) qui discrimine, pas son aire.
- **ON NE COMPTE PAS LES ÉTOILES GRISES** : le nombre d'emplacements
  n'est pas fixe (Soraka 3 oranges + 3 grises, Gnar 3 oranges et RIEN
  derrière). Les grises disent le potentiel, pas l'échelle — un garde-fou
  « pleines + vides = 6 » aurait refusé Gnar à tort.
- **TROIS TENTATIVES PAR CHAMPION ET PAR MOIS** (Ewan). Épuisé = grisé,
  renvoyé en fin de liste, bandeau « TENTATIVES ÉPUISÉES ». **Le grisage
  ne désature PAS ses étoiles** (celle de Shen reste détectée jusqu'à une
  saturation de 40) : il FAUT le repère `assets/champion_epuise.png`
  (1.00 là où il est, 0.30 ailleurs). La bande cherchée est prise plus
  large que le gabarit — à taille égale, `matchTemplate` n'a qu'un seul
  alignement et un centroïde décalé d'un pixel fait tomber le score.
- **Le niveau n'est pas lu** : la pastille est trop petite pour
  `digits.py` (glyphes de 4 et 7 px, le cerclage doré entre dans le
  masque). À égalité d'étoiles on prend **la dernière vignette dans
  l'ordre de lecture** — la liste étant croissante, c'est le plus haut
  niveau (mesuré chez les 7 ★ : 44, 45, 45, 50, 50). C'est le SEUL
  endroit qui s'appuie sur l'ordre, et seulement pour départager des
  égaux.
- **On ne juge que ce qu'on voit ENTIÈREMENT** : une vignette dont le
  bandeau sort de la grille est ignorée — elle reviendra entière à un
  autre cran.
- **Deux pièges de la souris, mesurés** : le **survol** abîme la vignette
  sous le curseur (Gnar est devenu illisible), donc on gare la souris
  avant chaque lecture ; et le jeu **ignore la molette** si le curseur
  vient d'arriver, donc on le pose avant de défiler (sept captures
  identiques sinon).
- **ON DESCEND D'ABORD, ON LIT ENSUITE, ON CLIQUE CE QU'ON VIENT DE
  LIRE.** La première version lisait en descendant, retenait la meilleure
  vignette, puis tentait de la RETROUVER en remontant : en vrai jeu elle
  ne l'a jamais retrouvée (meilleur score 0.51 pour un seuil de 0.90) et
  le bot est reparti sur l'ancien choix — une tentative mensuelle
  dépensée. Plus rien à retrouver désormais.
- **Un cran de molette vaut ~26 px, une rangée 296 px** : il en faut ~11
  pour avancer d'une rangée. La première version défilait de 3 crans par
  tour (78 px) : ses « 20 écrans » ne couvraient que CINQ rangées, d'où
  « bas de liste non atteint ». Mesurer le pas avant de compter les tours.
- **Rien de lisible n'est pas un choix** : `choisir_champion` rend False
  et `_pick_champion` retombe sur `first_champion`, l'ancien
  comportement. Jamais un clic au hasard.
- **UNE SUITE HORS LIGNE NE DOIT JAMAIS TOUCHER LA SOURIS.**
  `_pick_champion` fait défiler et photographie : `test_challenges`
  bouchonne donc `navigate.champions.choisir_champion` dès l'import.
  Sans ça : 10 captures et 15 coups de molette sur le jeu d'Ewan pendant
  `check.py --offline`, et un test vert **par accident** (il passait par
  le repli). Au passage, `lor_battle.park_mouse` déplaçait vraiment le
  curseur 29 fois par exécution, bien avant ce chantier : bouchonné aussi.
  **Mesurer, ne pas supposer** : un espion sur `pyautogui` dit en une
  commande si une suite touche la machine.

### Le bilan de fin de tentative (05/11/2026) — `bilan.py`

- **AU BOSS FINAL, RIEN NE JUGEAIT.** Les juges existants sont l'écran
  (« Relevez-vous », fin d'aventure) et l'aventure qui continue
  (`confirm_victory`, nœud SUIVANT rejoint). Or le boss final n'a pas de
  nœud suivant, et son second « Continuer » est la sortie NORMALE : le
  combat le plus important de chaque aventure était **le seul à finir
  toujours en `gagne: null`**. Sur 72 combats, 62 sans verdict, 0 victoire.
- **L'écran le disait pourtant en toutes lettres.** Le 04/11 à 20:49:38 le
  bot a PHOTOGRAPHIÉ le bilan — « DÉFI 2 · SHEN · PV 0/20 » — pour le
  classer « écran inconnu ». `bilan.juger()` lit cette capture-là :
  ancre = le grand cœur des PV (`assets/bilan_coeur.png`, (95, 762) sur
  1920×1080), appelée par `lor_battle._judge_from_summary` **avant**
  `_close_adventure_end`, qui referme justement l'écran lu.
- **LA FENÊTRE DU NOMBRE NE PEUT PAS ÊTRE FIXE** : « 0 / 20 » est centré
  sous son label, « 12 / 20 » serait plus large. C'est la COULEUR qui
  sépare : **PV courants en orange, maximum en crème**.
- **PIÈGE MESURÉ — lire toute la bande rend le MAXIMUM.**
  `digits.glyph_mask` exclut l'orange *à dessein* (jeton d'attaque, gemme
  de mana) : il ne voit donc pas le « 0 » et rend **20**. Une lecture
  naïve conclurait « 20 PV, donc victoire » sur un écran de défaite. On
  repeint l'orange en blanc sur la seule sous-image des glyphes oranges ;
  le masque global n'est pas touché. Verrouillé par
  `test_bilan.test_le_piege_du_bloc_entier`.
- **DEUX ÉCRANS, PAS UN — et c'est le jeu qui l'a dit.** Première
  victoire du bot le 05/11/2026 (Teemo Fleur Spirituelle, 7 ★, défi 2) :
  gagner ne mène PAS au bilan au cœur mais à un écran de RÉCOMPENSES
  — « DÉFI 2 / VICTOIRE », « XP DE DÉFI ×5 », un « Continuer » — **sans
  cœur et sans PV**. Le juge a donc répondu « écran non lisible », ce qui
  était la bonne réponse : il ne devine pas. D'où la seconde ancre, le mot
  « VICTOIRE » (`assets/bilan_victoire.png` : 1.00 sur l'écran de
  victoire, 0.46 sur celui de défaite). Le gabarit **exclut « DÉFI 2 »** —
  le numéro change d'un défi à l'autre.
- **LES DEUX ÉCRANS N'ARRIVENT PAS AU MÊME INSTANT.** Mesuré : second
  « Continuer » cliqué à 15:05:31, juge appelé à 15:05:40 sur un écran
  encore muet, écran de victoire affiché à 15:05:47 — **après** le clic de
  fermeture. D'où `bilan.attendre_verdict` (on REGARDE quelques secondes
  au lieu de juger une seule image) et **deux appels** dans `try_combat`,
  de part et d'autre de `_close_adventure_end`. `settle_verdict` ne
  requalifie pas : le premier qui lit gagne.
- **⚠ « Aucun glyphe orange = victoire » ÉTAIT FAUX, et ça a tenu trois
  jours** (corrigé le 08/11/2026, voir « Une victoire ne se prouve pas
  par une absence »). L'éprouvette d'alors — repeindre les PV de la
  capture de défaite — ne prouvait rien : elle fabriquait justement
  l'état qu'il fallait refuser. Le nexus au maximum se lit désormais
  « N / N » en entier.
- **Un test hors ligne ne doit jamais capturer l'écran** : `try_combat`
  lit désormais l'écran dans la branche du boss final, donc le harnais de
  `test_challenges` remplace `lb._judge_from_summary`. Sans ça, la suite
  allait voir le vrai écran et son résultat dépendait de ce qui était
  affiché.
- **Illisible n'est pas un verdict** : pas de cœur, PV illisibles → `None`,
  le combat reste `gagne: null`. Inventer corromprait `journal.py`, qui
  est précisément ce qu'on répare.
- `captures_reference/` garde les captures sur lesquelles les tests
  s'appuient — elles ne doivent pas être effacées avec `screenshots/`.

### Verdict en défi (05/09/2026)

- **L'API ne juge pas les défis** : 53/53 combats à `gagne: null` malgré
  `final_result`. Le verdict est rendu par l'ÉCRAN, après la boucle, et
  passe par `lor_battle.settle_verdict` → `journal.conclude` (sinon il
  reste dans les logs et jamais dans les statistiques). Trois juges :
  second « Continuer » sans « Relevez-vous » = DÉFAITE
  (`_declare_defeat`) ; « Relevez-vous » cliqué = DÉFAITE du combat qui
  précède (verdict `relevez-vous`) ; nœud suivant rejoint = VICTOIRE
  (`navigate.run_adventure` → `confirm_victory`). `report.verdict` dit
  qui a jugé ; l'écran ne requalifie jamais l'API. Le boss final sans
  nœud suivant reste `None`.
- **Les tours se comptent au mana qui remonte** (`ActionLog.mana_start /
  mana_end`, `CombatLoop._mana_last`) : après un blocage on rejoue le
  même round, et l'adversaire peut passer sans qu'OPPONENT_TURN soit lu.
- **Chiffres : la forme d'abord, partout.** `detect_chiffres.ocr_number`
  passe par `digits.read_number` avant easyocr ; le lecteur easyocr est
  paresseux (`get_reader`), partagé avec `mana`. `digits.USAGE` compte
  forme / easyocr / tolerant / echec, résumé au log en fin de combat.
  `--sans-ocr` (`mana.OCR_DISABLED`) ne charge jamais torch ; journalisé
  dans `config.ocr`. Ne pas en faire le défaut sans comparer les taux.
- **`test_replay.py`** est dans `check.py` ; le rejeu d'une trace réelle
  d'Ewan est le bon terrain pour toute question « pourquoi a-t-il fait ça ».
- **OBJECTIF D'EWAN : le bot doit apprendre à jouer TOUTES les cartes**, pas
  éviter celles qu'il ne sait pas jouer. Un refus « hors de portée » est une
  dette, pas un choix de conception. L'ordre de remboursement vient des
  parties : `ActionLog.reject` → `CombatReport.rejections` →
  `journal.jsonl["ecartees"]` → `python journal.py --ecartees` (motifs
  normalisés, `journal.normalize_reason` ; contexte mana/place/cible à part,
  `is_context_reason`). La forme en haut du tableau est la prochaine à coder.
- **Les échanges sont pilotés** (`SpellPlan.sequence`, `_trade_steps`) :
  « <malus> an ally TO <malus> <cible> » → deux pas (effet, Targeting,
  montant) ; `choose_trade_targets` choisit le coût (survivante aux dégâts
  ou sacrifiée la moins chère), puis la récompense, puis PÈSE (stats perdues
  vs stats tuées / attaque étourdie) et refuse à perte — dans les deux modes,
  et dès `playable_cards`, parce que le premier clic tue. Garde-fous :
  coût sur ALLY, phrase « to », récompense en HARMFUL (ou Vulnerable sur
  ennemi) ; « Deal 2 to a champion or 4 to a follower » reste UN clic.
  Reste refusé : deux alliés à départager (Transfusion), les strikes.

### Pile de sorts (03/09/2026)

- **Un SORT CONNU sur la pile se lit AVANT TOUT — rangées et orbe
  comprises** (`game_state.snapshot` → `SPELL_STACK`). L'orbe ne dit plus
  la phase, elle dit à qui c'est de parler (`turn_orb_active`). Avant,
  la pile n'était lue qu'après l'orbe : orbe grise → OPPONENT_TURN, et le
  bot ne voyait ni les sorts adverses ni la réponse adverse aux nôtres.
- `reconcile_combat_rows` : une unité dans une bande de combat va dans SA
  rangée (camp), un sort/compétence y va sur la PILE — où qu'il tombe.
  Une carte de type INCONNU garde l'ancien traitement (sans base de
  cartes, tout serait « sort » et on ne bloquerait plus).
- `GameSnapshot.stack_ours / stack_theirs / spells_on_stack`.
- `actions.respond_to_stack` (appelé par `CombatLoop._handle_spell_stack`) :
  orbe grise → on attend (borné par `_check_progress`) ; sort ADVERSE →
  `riposte.choose_response(snapshot, options, plan_of)` décide ; rien
  d'utile → clic « OK ». `response_options` = `playable_cards` filtré aux
  sorts + les CONTRESORTS (« Stop a spell », refusés par prudence ailleurs).
- **`riposte.py` — la réponse est INTELLIGENTE ou n'a pas lieu** (Ewan,
  03/09/2026). On lit la MENACE dans le texte du sort adverse
  (`spells.classify_card`, vu de lui « an enemy » = nous) : `REMOVAL`
  (tue / blesse / étourdit nos unités — `endangered` = celles que le montant
  tue, toutes pour Kill/Stun/Recall/Silence), `NEXUS`, `BUFF` (renforce les
  siennes), `NOTHING` (pioche…). Parades, dans l'ordre : CONTRER (cible =
  le sort adverse sur la pile, `enemy_spell.center`) ; PROTÉGER l'unité
  menacée la plus précieuse (Spellshield contre tout ; Barrier ou +PV
  seulement contre des dégâts qu'ils suffisent à encaisser) ; RETIRER la
  cible probable de son renfort (identifiable = une seule unité adverse
  engagée, ou une seule en jeu) si nos dégâts la tuent. Sinon ON PASSE et
  le journal dit pourquoi (« Menace : … », « Riposte : … »). La cible de
  la parade est IMPOSÉE à `play_spell(forced=(plan, cibles, raison))`.
  Tests : `test_riposte.py`.
- `actions.let_stack_resolve` après la validation d'un sort : tant que
  NOTRE carte est sur la pile, passer (« OK ») si l'orbe est bleue,
  attendre (`STACK_RESPONSE_WAIT`) si elle est grise, `STACK_PASS_ATTEMPTS`
  fois au plus. Chaque clic est gardé par une relecture de la pile : vide,
  le bouton devient « fin de tour ».
- `play_hand` ne pose RIEN en `SPELL_STACK`, et s'arrête dès qu'un sort
  apparaît sur la pile après une pose — c'était le « il joue comme si rien ».

### Sortie de combat (`lor_battle._handle_post_combat`, 02/09/2026)

- Plus AUCUNE image cherchée pour l'écran de résultat (`after_combat.png`
  supprimé) : 5 s (`POST_COMBAT_DELAY`), un clic au centre, puis
  « Continuer » (`continue_button_after_combat`, repli `continue_button`).
- **Après le premier « Continuer », `try_combat` guette EN MÊME TEMPS un
  second « Continuer » et « Relevez-vous »** (`_watch_after_continue`,
  `AFTER_COMBAT_ROUNDS` tours de ~4 s, puis `RETRY_TIMEOUT` pour un
  « Relevez-vous » qui suivrait le second « Continuer »). Jamais l'un
  APRÈS l'autre : le 05/09/2026 (boss final perdu) il n'y a eu qu'UN
  « Continuer » puis directement « VOUS ÊTES MORT … RELEVEZ-VOUS » ; le bot
  exigeait le second « Continuer » du boss final, a conclu « aventure
  terminée » et s'est perdu 2 × 120 s sur cet écran sans chercher `retry`.
- **Boss final** (`try_combat(final_boss=True)`, posé par `run_adventure`) :
  le second « Continuer » est la sortie NORMALE (pas une défaite), puis 5 s
  (`FINAL_BOSS_EXTRA_DELAY`), reclic AU MÊME POINT — `click_button` rend le
  point cliqué, pas True. `_handle_post_combat()` ne prend plus
  `final_boss` : il ne fait que le premier « Continuer ».
- **`navigate.back_to_known_screen` ne clique jamais `retry`** (il relance un
  combat), mais s'il le VOIT il rend `UNKNOWN` aussitôt avec un avertissement
  explicite, au lieu de tourner deux minutes.
- **Après « Réessayer », il faut RECLIQUER L'ADVERSAIRE** avant que
  « Combat » n'apparaisse, et il est AU CENTRE DE L'ÉCRAN : la carte s'est
  recentrée sur nous (capture d'Ewan, 03/09/2026). Ni le point cliqué la
  première fois, ni un repère cherché autour (ça a cliqué le coffre voisin).
  `try_combat` → `_dismiss_click()` puis `combat_button`.

### Souris garée (`click_utils.park_mouse`, 02/09/2026)

- Un bouton SOUS LE CURSEUR n'est pas reconnu (survol : éclairage,
  infobulle). Quand TOUS les boutons d'une liste ont été cherchés en vain
  (`back_to_known_screen`, `lor_battle._click_continue`), et à mi-parcours
  d'un `click_button` long (≥ 3 s), la souris est déplacée vers le bord
  gauche (`PARKING_SPOTS`, deux hauteurs en alternance) avant de rechercher.

### Carte d'aventure (`navigate.py`)

- **Les nœuds se repèrent par les templates d'Ewan, et par eux seuls**
  (décision explicite du 22/08/2026, après le retrait de la détection par
  couleur).
- **Quand plusieurs templates répondent de la même question, les mesurer
  sur UNE SEULE capture et comparer les scores** — ne jamais laisser un
  ordre d'essai décider à la place de ce qu'on voit (`where_are_we`,
  `read_arrival`). Un ordre d'essai a fait cliquer « Sélectionner » sur un
  écran qui n'offrait que « Quitter ».
- **L'ordre de détection des écrans compte** : `CHAMPION` avant `ATTEMPT`
  (les deux repères coexistent), `ADVENTURE` en dernier (repères les plus
  exposés au faux positif).
- **Le nœud suivant est le plus proche À DROITE de notre position**
  (`pick_next_node`, marge `NODE_FORWARD_MARGIN`). Position = `player_marker`
  lu sur la même capture ; **sous le seuil (0.70–0.80) il est accepté s'il
  est dans la bande centrale** (`MARKER_SOFT_THRESHOLD`, `MARKER_CENTER_BAND`) ;
  **absent, la position est LE CENTRE DE L'ÉCRAN** (la carte se recentre sur
  nous), et « le plus à gauche » n'est que l'ultime repli. Le 05/09/2026,
  marqueur à 0.78 → repli « à gauche » → le nœud DÉJÀ VISITÉ (coche verte,
  reconnu à 0.81) cliqué trois fois sans « Voyage ».
- **⚠ TOUT CE QUI SUIT SUR `player_marker` EST DÉPASSÉ** (08/11/2026) :
  ce gabarit suit un **décor de tracé**, pas nous. Lire « LE MARQUEUR DU
  JOUEUR N'ÉTAIT PAS LE MARQUEUR DU JOUEUR » dans la session du 08/11.
  Le passage reste ici parce que sa LEÇON sur les masques vaut toujours
  — et parce qu'il montre comment un repère peut être réparé, mesuré,
  verrouillé par un test, et désigner quand même la mauvaise chose.
- **UN GABARIT EST RECONNU SUR SON FOND, PAS SUR SA FORME — sauf s'il
  porte un masque** (06/11/2026). `player_marker.png` n'était trouvé que
  sur la capture dont il avait été découpé : 0.81 le 02/09 (celle du test
  voisin, vert depuis), **0.56-0.61 sur toutes les cartes du 05 et du
  06/11 — AU BON ENDROIT**, sous le seuil de 0.80. `_player_position`
  rendait donc None à chaque lecture, la position retombait sur le centre
  puis sur « le plus à gauche », et le bot a recliqué un nœud injoignable
  en (1819, 470) : **deux tentatives mensuelles perdues** dans la nuit
  (« deuxième nœud introuvable », « boss final introuvable »). La boîte
  fait 46 × 52 pour un losange qui n'en occupe que **46 %** ; le reste est
  du décor de carte — neige, roche, ciel, lignes de chemin cyan — plus,
  dans le gabarit lui-même, les décorations de sa capture d'origine. C'est
  ce décor que `TM_CCOEFF_NORMED` notait. Le PNG porte désormais le
  losange en **canal alpha** et `best_match` le passe en `mask=` (même
  parade que le jeton d'attaque) : **0.88-0.91 là où le marqueur est,
  ≤ 0.60 là où il n'y en a pas**, mesuré sur les 453 captures du projet —
  26 trouvés, **aucun faux positif**. Le multi-échelle, lui, ne rattrapait
  rien (meilleure échelle 1.00 partout) : ce n'était pas un problème de
  zoom. **Devant un repère « presque reconnu », regarder la part de fond
  dans sa boîte AVANT de toucher au seuil.**
- **Un marqueur ASSOMBRI reste refusé, et c'est sans conséquence** : sous
  un panneau qui voile la carte il tombe à 0.66-0.78 (mesuré sur
  `recompense_boss_20261105.png` et deux captures du 05/11) — mais dans
  cet état on résout un panneau, on ne choisit pas de nœud. Ne pas
  baisser le seuil pour ça : 0.78 contre un plancher de vrais positifs à
  0.88, la marge est le garde-fou.
- **Ce masque ne change rien aux autres gabarits, et c'est mesuré** : 22
  PNG d'`assets` portaient déjà un alpha, **20 sont opaques à 100 %**
  (masque tout blanc = le calcul d'avant, **écart ≤ 0.00021** sur 52
  captures). Le point rendu, lui, change parfois — jusqu'à 20 fois sur
  52 : à 1e-5 près, deux pics presque égaux s'échangent la première
  place. **Jamais au-dessus du seuil** : sur les 51 cas où un gabarit
  opaque passe 0.75, la position est identique 51 fois. En dessous, le
  point n'est de toute façon jamais utilisé — tous les appelants
  filtrent sur le score d'abord. Le seul autre à cacher quelque chose est `continue_button.
  png` — 1.7 %, **entièrement sur le bord**, un artefact de découpe — et
  le masquer AMÉLIORE les deux côtés : « Continuer » présent passe de
  0.984 à **1.000**, absent descend de 0.558 à 0.492. `attack_token.png`
  (53 %) ne passe jamais par `best_match` : `game_state` a son propre
  matching. Un gabarit en niveaux de gris reviendrait à deux dimensions
  avec `IMREAD_UNCHANGED` — hors du cas « quatre canaux », `best_match`
  relit donc exactement comme avant.
  `assets/` étant ignoré par git, ce masque n'est pas versionné : s'il
  disparaît (gabarit recoupé, dossier restauré), la suite ci-dessous
  repasse au rouge — et il se refait en une ligne, le losange inscrit
  dans la boîte avec un pixel de retrait :
  `cv2.fillConvexPoly(alpha, [[w//2,1],[w-2,h//2],[w//2,h-2],[1,h//2]], 255)`.
  Tests :
  `test_challenges.test_le_marqueur_du_joueur_tient_sur_dautres_cartes`,
  sur `captures_reference/carte_marqueur_20261106.png`,
  `soigneur_20261106.png` et `boutique_20261105.png`. **PAS ENCORE VU
  TOURNER EN JEU** (06/11) : tout est mesuré sur les captures des
  tentatives perdues.
- **Un nœud cliqué sans « Voyage » est ÉCARTÉ au tour suivant**
  (`goto_node` → `locate_node(exclude=…)` → `pick_next_node(exclude=…)`,
  rayon `NODE_EXCLUDE_DISTANCE`). Réessayer le même clic trois fois ne
  sert à rien.
- **Ce qu'un nœud propose se découvre à l'arrivée**, on ne le déduit pas.
- **On attend le nœud** (`NODE_WAIT` 12 s) et le geste a deux réessais.
  En réécrivant un module, **inventorier ses réessais**, pas seulement sa
  logique.
- `SUPPORT_CHAMPION_SETTLE = (2.0, 2.6)` : le panneau du champion de
  soutien s'affiche 2 s avant son contenu. Attente **avant** la première
  lecture, plancher insensible à `--speed`, **ce nœud seulement**.
- **UNE AVENTURE EN COURS SE VOIT AUSSI DEPUIS LES MENUS** (06/11/2026,
  `Screen.RESUME`). `Screen.ADVENTURE` ne reconnaît qu'une CARTE déjà
  ouverte. Or le jeu l'annonce aussi dans le panneau du défi : là où
  s'affiche « UTILISER UNE TENTATIVE », le bouton porte « REPRENDRE
  L'AVENTURE » — même cadre, même place, autre libellé, et `use_attempt`
  n'y note que **0.68**. Le 06/11 à 10:21 le bot a donc suivi le chemin
  de la carte du monde sans regarder : liste, défi, puis GRILLE DES
  CHAMPIONS — qui n'était pas affichée. Il a parcouru **six rangées
  d'une grille absente**, n'a pas trouvé `first_champion`, et a tourné
  en « écran inconnu » jusqu'à l'arrêt, sans jamais démarrer.
  `assets/reprendre_aventure.png` est pris sur le LIBELLÉ seul (1.00 ici,
  ≤ 0.33 sur les douze autres captures de référence) et `Screen.RESUME`
  est testé **EN PREMIER** — départager par l'ordre coûte moins cher que
  d'espérer que 0.68 reste sous le seuil. Un clic, et **rien n'est
  consommé** : le jeu ne décompte pas une aventure qu'on n'a pas quittée.
- **ET LA GRILLE DES CHAMPIONS NE DOIT PAS ÊTRE PARCOURUE LÀ**
  (`navigate._halt_if_resume_offered`) : elle défile à la MOLETTE, ce
  qui déplacerait la liste des défis sous le panneau. Le garde-fou rend
  False dès que le bouton de reprise est vu — ce n'est pas un échec,
  c'est « l'écran n'est plus celui qu'on croyait » ; `enter_challenge_
  attempt` relit l'écran au tour suivant et reprend. **VU TOURNER EN JEU
  le 06/11** : écran reconnu, bouton cliqué, carte chargée, étapes déjà
  franchies sautées. Tests :
  `test_challenges.test_une_aventure_en_cours_se_reprend_depuis_les_menus`,
  sur `captures_reference/reprendre_aventure_20261106.png`.
- **UNE AVENTURE REPRISE NE REPART PAS DU DÉBUT** (05/11/2026).
  `run_adventure(reprise=True)`, posé par `challenges` quand
  `enter_challenge_attempt` rend `RESUMED` : les étapes du début ont le
  droit de MANQUER — elles ont été franchies avant qu'on reprenne la
  main — et on avance jusqu'à la première qu'on retrouve. Avant, le
  parcours exigeait le champion de soutien et abandonnait une carte
  POURTANT VIVANTE : deux tentatives mensuelles perdues ainsi le
  05/11, dont une où le combat suivant était gagnable.
- **Le droit de sauter s'éteint à la PREMIÈRE étape retrouvée**, et le
  boss final n'est jamais sautable. Sinon le bot traverserait la carte
  en cliquant à côté — c'est exactement ce qu'il a fait le 05/11 en
  cherchant un « nœud 2 » derrière un panneau resté ouvert.
- Fin normale d'une session : le jeu cesse d'afficher `use_attempt` — il
  n'annonce jamais « plus de tentative ». Une défaite n'arrête rien.

## La nuit du 08-09/11 — neuf correctifs, et une leçon de méthode

Neuf défauts réparés d'affilée, chacun écrit par un agent puis **relu par
un adversaire chargé de le démolir**. Les neuf sont revenus « solide
APRÈS correction » : **aucun n'était bon du premier coup**, et deux des
griefs étaient assez graves pour justifier une seconde vague. Ce qui a
été attrapé en relecture vaut d'être retenu, parce que ce sont des
erreurs que le projet refait :

- **une mesure faite sur la mauvaise dégradation** : le correctif du
  bilan était fondé sur une capture ASSOMBRIE (« partout où l'orange
  manque, le crème manquait déjà »). L'ordre S'INVERSE sur un fondu
  enchaîné, mesuré sur de vraies captures : le bogue survivait à sa
  propre correction ;
- **un test qui n'assertait rien** : `test_structural_refusals` lisait
  `for text, expected in cases.items()` et **n'utilisait jamais
  `expected`** — n'importe quelle ligne de `REFUSALS` pouvait prendre la
  place d'une autre sans rougir. Depuis toujours ;
- **un garde qui coupe ce qu'il protège** : conclure « ce n'est pas la
  grille » sur UNE seule image faisait abandonner pendant la transition
  liste → grille, c'est-à-dire exactement quand le garde est appelé ;
- **un repli cassé par le ramasse-miettes** : réemballer `sys.stdout`
  sans garder l'ancien référencé laissait son `__del__` FERMER le tampon
  qu'on venait de reprendre ;
- **une régression créée par le correctif voisin** : le refus « aucune
  cible » a silencieusement privé le bot des sorts qui visent le nexus.
  C'est le point 2 ci-dessous, et personne ne l'avait vu avant la
  relecture.

### Une cible qui ne peut pas exister — `actions.sort_sans_cible`

- **ON NE POSE PAS UNE CARTE QUAND LE PLATEAU N'OFFRE RIEN À CLIQUER.**
  C'est le raisonnement de l'équipement sans porteur (05/11), appliqué
  enfin à ce qu'il visait. Mesuré dans `logs/` du 05/09 au 08/11 :
  **25 poses lancées en sachant qu'aucune cible n'existait** — le
  message le disait mot pour mot, « Minimorph : « aucun allié en jeu » —
  restrictions levées, on tente et on annulera ». **13 ont figé le
  tour** (« X toujours sur la pile après validation »), **20 à 26 s
  chacune, 303 s au total**, et le tour rendu sans être terminé. Le
  08/11 à 20:51:51 : Spirit Journey posée sans ennemi, quatre « on passe
  (OK) » dans le vide, annulation à 20:52:20, **29 s**.
- **LE REFUS SE PREND DANS `playable_cards`, PAS APRÈS LA POSE.**
  `spell_is_castable` savait déjà répondre ; personne ne lui posait la
  question avant le dépôt. `rejection_reason` rend le même motif dans le
  même ordre — le diagnostic ne doit jamais dire autre chose que la
  décision.
- **ON EXIGE ZÉRO POINT, PAS « MOINS QUE PRÉVU »**, et chacun de ces
  quatre cas est un invariant déjà payé : un sort qui ne clique rien
  reste jouable ; un pluriel COMPTÉ se lance sur un seul ennemi (02/09) ;
  un sort à deux cibles strictes dont UNE est trouvée garde sa chance,
  parce que notre comptage de marqueurs peut sur-compter (26/08) ; un
  REPLI est une cible (06/09). **ET SURTOUT PAS LA VITESSE** : un sort
  lent en plein combat ressortait d'ici sous un nom qui promet le
  contraire (Dawn and Dusk, Shunpo, Guile) — garde ajouté en relecture.
- **LE PRÉFIXE « sort : » N'EST PAS DÉCORATIF** : il range le motif dans
  `journal.CONTEXT_PREFIXES` (contexte de la partie) plutôt que dans le
  backlog de `journal.py --ecartees`.
- **CE QUE ÇA NE RÉPARE PAS** : les 8 autres blocages du relevé ont une
  cible TROUVÉE mais REFUSÉE par le jeu — « Deal 3 to a **follower** »
  (Calibrum) cliquée sur un champion, « Recall a unit with **3 or less
  Power** » (Quicken) cliquée sur une grosse unité. Ce sont des
  conditions de cible LISIBLES (`is_champion`, l'attaque lue) que
  `spells.py` ne modélise pas, exactement comme « attacking » avant le
  06/11. **PAS ENCORE VU TOURNER EN JEU.** Tests :
  `test_actions.test_un_sort_dont_la_cible_ne_peut_pas_exister_nest_pas_lance`,
  et le miroir retourné dans `test_restrictions_levees`.

### « An enemy OR the enemy Nexus » — le nexus est une cible

- **LE REFUS CI-DESSUS A PRIVÉ LE BOT DE LA BRÛLURE QUI FINIT LA
  PARTIE**, et personne ne l'a vu avant la relecture. `choose_target` ne
  connaissait le nexus que pour `Targeting.ANYTHING` ; les sorts qui
  écrivent « an enemy **or the enemy Nexus** » étaient rangés en
  `Targeting.ENEMY`, donc **plateau adverse vide ils rendaient « aucun
  ennemi en jeu »** — dans l'état même que `actions.nexus_weight` et
  l'archétype « aggro » existent pour exploiter.
- **UN REFUS MUET SUR UNE CAPACITÉ PERDUE EST PIRE QU'UNE PERTE DE TEMPS
  BRUYANTE.** Avant `sort_sans_cible`, ces cartes étaient posées puis
  annulées au bout de 23 s : le symptôme disait au moins qu'il se
  passait quelque chose. C'est ce qui a failli l'enterrer.
- **ON LE LIT DANS LE TEXTE** : un marqueur de plus dans
  `SINGULAR_TARGETS`, avec EXACTEMENT les qualificatifs du marqueur
  ordinaire et pas un de plus — un « n'importe quels deux mots »
  permissif aurait avalé « a **random** enemy or the enemy Nexus »
  (Ricochet, Volibear), où c'est le JEU qui tire. Et **« randomly to »
  est le même geste que « draw »** (`_RANDOM_RX`, lu dans ce qui
  PRÉCÈDE le marqueur, comme `_DRAWN_RX`) : les trois Ebb nomment une
  cible que personne ne désigne.
- **« AN ENEMY » TOUT COURT RESTE UNE UNITÉ.** Lui inventer un repli sur
  le nexus ferait un clic que le jeu refuse. Death's Hand (« Deal 2 to
  an enemy **and** 1 to the enemy Nexus ») frappe le nexus TOUT SEUL :
  la cible du clic reste une unité, et sans unité on ne lance pas.
- **BILAN MESURÉ sur les 2653 cartes** : **9 plans changent, les 9
  changent de camp, ZÉRO ne passe d'ennemi à allié.** Plateau adverse
  vide, les écartés passent de 313 à 304. Avec un ennemi en jeu, rien ne
  se ferme et **trois sorts deviennent complètement lançables au lieu
  d'être joués à une cible sur deux** — Statikk Shock, Shock Blast et
  Divine Draft cliquent l'unité PUIS le nexus. **Six plans seulement
  changent, pas sept** : Timewinder matche le marqueur mais son « To
  play, discard 1 » la fait basculer en `Targeting.HAND` (relevé en
  relecture — le commentaire de `spells.py` le dit maintenant).
  **PAS ENCORE VU TOURNER EN JEU.** Tests :
  `test_spells.test_un_sort_qui_peut_frapper_le_nexus_adverse_le_vise`,
  `test_actions.test_un_sort_qui_peut_frapper_le_nexus_nest_pas_ecarte`.

### Une victoire ne se prouve pas par une absence — `bilan.lire_pv`

- **`juger` déclarait « nexus intact » — donc VICTOIRE — dès que
  `_glyphes_orange` ne trouvait RIEN.** L'erreur était asymétrique dans
  le pire sens : conclure à la DÉFAITE exigeait de LIRE « 0 », tandis
  que ne rien voir du tout donnait la victoire. Vu DEUX FOIS le même
  soir, même écran, une seconde d'écart :

      20:53:37 [WARNING] cœur trouvé (0.81) mais PV illisibles
      20:53:38 [INFO]    victoire (bilan : nexus intact)

  (et le même couple à 20:45:48/49). Le cœur à 0.81 au lieu de 1.00 le
  disait : le panneau n'était pas dans son état normal. Comme
  `attendre_verdict` REGARDE 8 s, il tombait fatalement sur l'image où
  l'orange manquait.
- **LA PREUVE POSITIVE EST QUE LA BANDE SE LISE « N / N » EN ENTIER.**
  Première version : exiger le MAXIMUM crème, au motif mesuré que « sur
  une capture assombrie le crème meurt à 0,70 quand l'orange tient
  jusqu'à 0,37 — donc exiger le maximum est strictement plus sévère ».
  **La relecture a mesuré l'inverse sur un FONDU ENCHAÎNÉ** (le bilan
  fondu sur la carte d'aventure, opacités 0,45 à 0,20) : là, l'orange
  disparaît AVANT le crème, et la fausse victoire survivait. D'où la
  règle actuelle — les DEUX nombres, courant ET maximum, entièrement
  lisibles et égaux. Sur un bilan de DÉFAITE les PV courants sont
  orange donc invisibles au masque crème : la bande « 0 / 20 » ne laisse
  que `[« / », « 2 », « 0 »]`, rien à gauche du séparateur, pas de
  verdict.
- **`lire_pv` rend `LecturePV(courant, maximum, orange)`** : le nombre
  de glyphes oranges TROUVÉS fait partie de la lecture, parce que
  « aucun orange » et « de l'orange illisible » sont deux états, et les
  confondre EST le bogue.
- **L'ÉPROUVETTE DU CAS « INTACT » MENTAIT AUSSI** : repeindre « 0 / 20 »
  en crème et appeler ça « un nexus intact », c'est fabriquer l'état
  qu'il faut refuser. Elle lit maintenant vraiment « 20 / 20 », le « 2 »
  étant COPIÉ de celui du maximum (bonne police, bonne couleur, bonne
  hauteur). Tests :
  `test_bilan.test_un_panneau_a_moitie_dessine_nest_pas_une_victoire`,
  `test_un_fondu_enchaine_nefface_que_l_orange`,
  `test_deux_lectures_du_meme_ecran_ne_se_contredisent_plus`.
  Recoupement : `victoire_defi13_20261106.png` se lit « 26 / 63 », le
  nexus noté ici le 06/11.

### Le mot « VICTOIRE » doit être à SA PLACE — `bilan.POSITION_VICTOIRE`

- **`assets/bilan_victoire.png` est fidèle, et c'est tout le problème.**
  Il retrouve le mot partout où il est ÉCRIT, y compris dans le compteur
  « XP DE DÉFI (22 VICTOIRES TOTALES) » de la **liste des défis** et du
  **panneau de reprise d'aventure** — deux écrans traversés à CHAQUE
  tentative. Mesuré sur les 980 captures du dépôt :

      1.000 à 0.983   le mot, en (272, 119)           11 écrans de victoire
      0.862 à 0.860   « VICTOIRES », en (453, 766)     6 listes de défis
      0.552 et moins  tout le reste

  Même police, même casse, au pluriel près — et `juger` y prononçait
  VICTOIRE, à 647 px de la bonne place.
- **C'EST LA LEÇON DU MARQUEUR DU JOUEUR, RETOURNÉE.** Le matin même on
  réparait un repère « presque reconnu » sans vérifier qu'il désignait
  la bonne chose ; ici le repère est PARFAITEMENT reconnu et désigne la
  mauvaise chose. Un bon score ne prouve que la fidélité du gabarit.
- **ON CONTRÔLE LA POSITION, PAS LE SEUIL.** Le seuil se défendrait
  (0.983 contre 0.862) mais ne laisse que **0.12** de marge. La position
  a un écart **NUL** : les onze vrais positifs tombent AU MÊME PIXEL,
  défi 2 à un chiffre comme défi 13 à deux (le numéro est sur la ligne
  du dessus). En l'exigeant, la marge devient **0.53**. Ratios, pas
  pixels. Hors de sa place, le mot est journalisé en WARNING : on ne se
  tait pas sur un repère qu'on refuse.
- **ET ON CHERCHE DANS LA ZONE, ON NE FILTRE PAS L'ARGMAX** (corrigé en
  relecture) : `best_match` ne rend QUE son maximum, donc un concurrent
  lointain plus net **masquait** le vrai mot au lieu d'être écarté —
  reproduit en fondant l'écran de victoire sur la liste des défis.
- Après correctif, sur 987 captures : **11 VICTOIRE (les 11 vraies),
  8 DÉFAITE, 968 sans verdict — 6 faux positifs supprimés, 0
  régression.** Tests :
  `test_bilan.test_le_mot_victoire_doit_etre_a_sa_place`,
  `test_un_concurrent_lointain_ne_masque_pas_le_vrai_mot`.
  **PAS ENCORE VU TOURNER EN JEU.**
- **DETTE : les deux victoires du 08/11 sont de provenance incertaine.**
  Celle de 20:45 a une capture d'écran de victoire à l'appui (score
  1.000) ; celle de 20:53:48 n'en a aucune, et la liste des défis
  s'affichait 1,3 s plus tard. À trancher et à reporter par
  `journal.conclude` avec sa provenance écrite, comme pour le défi 13.

### Une transformation nomme un JETON, pas une seconde cible

- `spells.py explain "Transform a unit into a 3|3 Mini-Minitee…"` rendait
  « refusé — deux cibles ». **Le motif disait le bon contresens, mais
  pas le bon coupable** : `_scan_targets` n'a jamais compté le
  complément d'une transformation — sur 23 textes contenant « into
  a/an », un marqueur ne suit le « into » que DEUX fois, et aucun n'est
  un jeton. Le refus venait d'une ligne de `REFUSALS` barrant le mot
  « transform » lui-même. **Ajouter un filtre « into » aurait cassé le
  seul vrai cas** (Hextech Transmogulator, deux vrais clics).
- **CE QUE ÇA COÛTAIT EST LE PIÈGE DU 06/11 À L'IDENTIQUE** :
  `actions.is_dead_weight` appelle `classify_card(card)` SANS argument,
  donc `restricted=True` MÊME en mode par défaut. Les cartes barrées
  étaient du « fardeau pur » — premières défaussées, dernières
  renforcées, dernières choisies dans une fenêtre. **14 sorts en
  sortent** (219 → 205 sur 1125), dont Minimorph, Whimsy! et **Go Hard**
  (un simple « Drain 1 from a unit » qui ne dit « transform » que de ses
  propres copies dans le deck).
- **BILAN : 18 plans changent, TOUS en mode prudent — ZÉRO en mode par
  défaut, et ZÉRO change le camp du clic.** Le gain est donc réel mais
  **indirect** : il se voit dans ce qui est gardé ou défaussé, jamais
  dans un log de combat. **PAS ENCORE VU TOURNER EN JEU.** Test :
  `test_spells.test_une_transformation_nomme_un_jeton_pas_une_seconde_cible`.

### Le palier conclu sur le mauvais écran — `champions.sur_la_grille`

- **« PALIER ILLISIBLE » N'EST UN FAIT QUE SUR L'ÉCRAN DU CHAMPION.** Le
  08/11 à 20:46, `_pick_champion` a été appelé alors que l'écran
  affichait encore LA LISTE DES DÉFIS (capture :
  `captures_reference/liste_defis_20261108.png`). Le titre « DÉFI N »
  n'y existe pas — zone du titre 79×270, **ZÉRO boîte** — alors
  `attendre_palier` a brûlé ses 20 s puis conclu « on prend le plus
  étoilé », et tout le parcours s'est déroulé sur la liste, **molette
  comprise, qui fait défiler cette liste** : faux « bas de liste
  atteint » en un bond, six « rien de jouable », `first_champion`
  cherché dans le vide. **~75 s et un essai d'entrée.** Rien n'a été
  consommé seulement parce que le repli n'a rien trouvé ; s'il avait
  trouvé, un 7 ★ partait sur un palier qui en demande 4. Même leçon que
  la molette du matin : « le titre ne se lit pas » ne veut dire
  « illisible » que si le titre est là.
- **CE SONT LES VIGNETTES QUI RÉPONDENT**, `first_champion` n'est qu'un
  second témoin et **ne vaut qu'en positif** : 1.000 / 0.985 / 0.978 sur
  les grilles, **0.641 sur une grille DÉFILÉE** (sous le seuil), 0.502
  sur la liste. Et la liste se dénonce elle-même (**0.957** contre
  ≤ 0.422 sur les grilles). `AUTRES_ECRANS` exclut **`use_attempt` à
  dessein** : il note 1.00 sur `champions_selection` parce que
  « UTILISER UNE TENTATIVE » s'affiche à côté de la grille dès qu'un
  champion est pris.
- **UN SEUL COUP D'ŒIL NE SUFFIT PAS** (`CONFIRMATIONS_AUTRE_ECRAN = 2`,
  ajouté en relecture) : `_pick_champion` est appelé JUSTE APRÈS le clic
  sur le défi, et l'écran d'avant — la liste — est précisément un membre
  d'`AUTRES_ECRANS`. Une transition lente faisait abandonner. Coût de la
  confirmation : ~1,3 s le jour où c'est vraiment le mauvais écran.
- **CE QU'ON A VU EN CHEMIN NE SE JETTE PLUS** (`_carnet`). Sans palier
  la cible est None, donc on descend au bas de la liste — et là tous
  sont ÉPUISÉS : « aucune vignette jouable lue », puis le filet à son
  tour, donc **aucun choix du tout**. Le parcours retient désormais la
  meilleure JOUABLE rencontrée et SA HAUTEUR, y revient et **RELIT avant
  de cliquer**. Tests :
  `test_champions.test_la_liste_des_defis_nest_pas_un_palier_illisible`,
  `test_une_jouable_vue_en_chemin_nest_pas_jetee`,
  `test_la_transition_nest_pas_un_mauvais_ecran`.

### Deux échecs du choix de champion, deux conduites — `navigate._pick_champion`

- `choisir_champion` rend `False` pour deux raisons opposées, et
  `_pick_champion` les lisait pareil : il enchaînait sur son filet et
  cherchait le HAUT d'une grille absente — **onze secondes par essai
  d'entrée**, trois essais par tentative.
- **LA QUESTION N'EST PAS « SUR QUEL ÉCRAN SOMMES-NOUS », C'EST « LE
  BOUTON DU REPLI EST-IL LÀ » — ET ELLE SE MESURE.** La première
  version lisait le booléen de `revenir_en_haut` ; **c'est un proxy à
  deux sens** (relecture) : il rend False hors de la grille, mais AUSSI
  quand la molette n'a pas été entendue — or dans ce second cas rien n'a
  défilé, la grille est restée EN HAUT où `first_champion` note ~1.00,
  et s'en remettre au booléen couperait le filet du 05/11 juste là où il
  sauve encore la tentative. On regarde donc l'écran : 0.502 liste des
  défis / 0.641 grille défilée / 0.978-1.000 grille en haut. **Un coup
  d'œil coûte 0,4 s ; insister en coûte onze.**
- Rendre False n'est pas un échec : `enter_challenge_attempt` relit au
  tour suivant, aucune tentative n'est consommée — même esprit que
  `_halt_if_resume_offered`. Test :
  `test_challenges.test_le_repli_ne_sentete_pas_hors_de_la_grille`,
  dont le cas bout-en-bout part de l'écran RÉEL du blocage.

### La boussole était datée de septembre — `journal.py --depuis`

- **`--ecartees` DÉSIGNAIT UNE BRIQUE DÉJÀ POSÉE.** Les trois vues
  agrégeaient les 142 lignes depuis le 07/08 sans jamais regarder
  `horodatage` ni dire sur quelle période elles portaient. Mesuré :
  **« pose ratée : mise de côté pour ce tour » — 33 fois, 9 le 05/09 et
  24 le 06/09, plus une seule depuis**, et ce motif **n'existe plus dans
  le code** (renommé le 06/09). Ses « Buhru Lookout ×14 » datent toutes
  du 06/09 — le jour même où `mark_hand_overlap` a corrigé la saisie
  dans une main pleine. Il était **2e du classement**. À l'inverse,
  « pouvoir à cibler : N carte(s) à désigner en main » (10 fois, toutes
  le 06/11) était invisible et ressort 2e ex æquo dans la fenêtre.
- **LA FENÊTRE EST PAR DÉFAUT, ET C'EST LE POINT**
  (`FENETRE_DEFAUT_JOURS = 30`) : une boussole qu'il faut armer avant de
  la croire n'en est pas une. **Chaque vue écrit sa fenêtre** (« 41
  combat(s) depuis le 2026-10-09 », « 68 ligne(s) antérieure(s) non
  comptée(s) — `--depuis tout` »), et les options valent pour LES TROIS
  vues : un classement daté d'un côté et un tableau cumulé de l'autre se
  contrediraient sans prévenir. Une date mal écrite — **ou bien formée
  mais impossible**, `2026-02-30` (relecture) — est REFUSÉE, elle ne
  filtre pas en silence.
- **UNE LIGNE SANS DATE LISIBLE EST GARDÉE, ET DITE** : `date_de` rend
  None plutôt qu'une date approchée (même règle que `lire_palier`).
- **CE QUE LA COMMANDE RÉPOND MAINTENANT** : 41 combats au lieu de 56,
  et derrière la première place — inchangée, « pose ratée : mise de côté
  jusqu'au prochain round », 54 fois, bien vivante — un classement fait
  de bogues VIVANTS : « bannie pour le reste du combat » ×10, « pouvoir
  à cibler » ×10, « sort : N cibles à cliquer » ×8.
- Tests : `test_journal.py` (nouvelle suite, inscrite dans `TEST_SUITES`),
  dont `test_la_boussole_ne_pointe_plus_un_bogue_mort`,
  `test_la_commande_applique_vraiment_sa_fenetre` (la ligne qui relie
  `main()` aux vues n'était couverte par rien) et
  `test_le_vrai_journal_nest_jamais_touche`, qui compare le SHA-256 de
  `journal.jsonl` avant et après — le 05/11 une suite y avait ajouté
  30 fausses tentatives.

### `check.py` écrit en UTF-8, tube ou pas

- **LA PARADE DU 05/11 AVAIT ÉTÉ DONNÉE AUX SUITES, JAMAIS AU PARENT.**
  `check.py --offline > rapport.txt` et `| tail` affichaient les suites
  en [OK] puis mouraient sur la ligne SUIVANTE, la dernière —
  `UnicodeEncodeError` sur le « ── » du verdict du garde-machine, absent
  de cp1252. **Code de retour 1, tout vert.** Et « la seule commande à
  retenir » est précisément celle qu'on redirige.
- Ce n'était pas que la chute : les lignes d'avant sortaient aussi en
  cp1252 (« é » sur un seul octet), et le rapport était **dans le
  désordre** — stdout bufferisé par blocs, stderr non, donc le traceback
  en tête du fichier.
- `_sortie_en_utf8()` reconfigure **stdout ET stderr** au niveau module,
  avant le premier import qui parle et pour les tracebacks compris.
  **Le repli gardait un piège** (relecture) : réemballer le tampon sans
  garder l'ancien `TextIOWrapper` référencé laissait son `__del__` le
  FERMER — d'où `_FLUX_REMPLACES`. Aucun des deux chemins n'a le droit
  d'échouer bruyamment : mieux vaut un rapport en cp1252 qu'une commande
  de vérification qui tombe.
- **PAS DE TEST AUTOMATISÉ, ET C'EST ASSUMÉ** : le défaut ne se
  reproduit que là où stdout n'est pas une console, c'est-à-dire
  précisément dans l'environnement d'une suite lancée par `check.py`.
  Le verrou est la commande : `check.py --offline > rapport.txt 2>&1`
  doit rendre **0** et le fichier doit être de l'UTF-8.
- **LE MÊME DÉFAUT SURVIT AILLEURS** : `game_state.py` imprime un « ≤ »
  dans `GameSnapshot.summary()`, donc `python game_state.py monitor`
  redirigé **meurt** dès que `/static-decklist` a répondu — et
  `combat.py` avec lui, par `_describe_stuck`. Quatre suites
  (`test_strategy`, `test_challenges`, `test_spells`, `test_actions`)
  mourraient aussi si on les lançait à la main avec redirection ; elles
  ne tiennent que par le `PYTHONIOENCODING` que `check.py` leur impose.

## La session du 09/11 — LES NEUF CORRECTIFS ONT ENFIN TOURNÉ

La dette qui primait sur toutes les autres est payée : **une tentative
réelle, observée de bout en bout, et GAGNÉE** — défi 23, 12 min, 5 nœuds,
2 combats, boss final compris. Ce que la partie a prouvé, et ce qu'elle a
cassé, dans cet ordre.

### Une fenêtre cachée n'est pas un écran inconnu

- **LA PREMIÈRE TENTATIVE N'A JAMAIS DÉMARRÉ, ET LA CAUSE ÉTAIT DEVANT
  NOUS** : l'éditeur de texte couvrait le jeu. Le bot photographie le
  BUREAU, pas la fenêtre du jeu — il a donc analysé du code source,
  meilleur gabarit à **0.51** pour un seuil de 0.80, conclu « écran
  inconnu », compté une tentative « inachevée — écran inconnu au moment
  d'entrer », et `--tentatives 1` s'est arrêté là. La capture gardée pour
  diagnostic montrait VS Code.
- **C'EST LA LEÇON DU 08/11 D'UN CRAN AU-DESSUS.** Ce jour-là on a appris
  que « la molette ne part nulle part si le jeu n'a pas le premier
  plan », et `gestures.focus_game_window` est né pour ça — mais seul
  `champions.py` l'appelait, au moment de faire défiler une grille. La
  condition est pourtant plus ancienne que la molette : **TOUT ce que le
  bot sait de l'écran vient d'une photo du bureau.**
  `challenges._mettre_le_jeu_devant()` est donc appelé avant CHAQUE
  tentative. Dégradation douce : pas de jeu, pas de pywin32, bascule
  refusée par Windows → on le DIT et on lit l'écran tel qu'il est.
  Refuser de démarrer serait pire — le jeu peut être visible sans que
  Windows nous laisse le mettre devant. Test :
  `test_challenges.test_le_jeu_est_mis_devant_avant_de_regarder_lecran`.
- **DETTE LAISSÉE OUVERTE** : une entrée qui n'a jamais eu lieu COMPTE
  quand même dans `--tentatives` (`_stop_reason` lit
  `len(report.attempts)`). Le journal, lui, n'a pas été pollué. Le code
  a déjà le précédent qu'il faut — `NO_ATTEMPT_LEFT` fait
  `attempts.pop()` au motif qu'« elle n'a rien joué » — et `LOST_LIMIT`
  (3) garde déjà contre la boucle. Non fait : la cause est réparée, et
  changer la comptabilité de la boucle le même jour aurait mélangé deux
  risques.

### Le diagnostic mentait, et c'était sur la première commande du projet

- **`python actions.py plan` DÉCLARAIT JOUABLE UN SORT TROP CHER.** Vu
  sur un vrai plateau, mana 3 :

      Spirit Leech   (4*) 4/2    non — trop chère
      Withering Wail (4*) 0/0    JOUABLE (DAMAGE 1 sur aucune)

  Deux cartes à 4, le même mana, deux verdicts opposés — et trois lignes
  plus bas, « Rien à jouer ». La DÉCISION avait raison.
- **IL Y AVAIT TROIS IMPLÉMENTATIONS DU MÊME TEST** : `playable_cards`
  décide, `rejection_reason` explique, et `_describe` recommençait pour
  son affichage — il calculait ses motifs puis les JETAIT dès qu'un sort
  était lançable. `actions.py` nomme pourtant le piège au-dessus de
  `unit_play_blocker` : « deux implémentations du même test finissent
  toujours par diverger, et c'est alors le diagnostic qui ment ».
  `_describe` DÉLÈGUE désormais, et ne garde en propre que le PLAN du
  sort — la seule chose que `rejection_reason` ne donne pas, et celle
  pour laquelle on vient lire ce tableau. Test :
  `test_actions.test_le_plan_ne_declare_pas_jouable_ce_que_la_decision_refuse`.
- Ce que ça coûtait n'était pas un pixel : une carte annoncée jouable qui
  n'est jamais jouée envoie chercher le défaut dans la pose, l'attaque ou
  la phase — partout sauf dans le mana.

### Trois cibles et un seul nexus : LE JEU REFUSE (Ewan, 09/11/2026)

- La question ouverte depuis le 08/11 est tranchée : **le jeu n'accepte
  pas de résoudre un sort avec moins de cibles qu'il n'en annonce**, et
  on ne peut pas envoyer les trois tirs sur le nexus. Rien ne part.
- **SIX CARTES, MESURÉES SUR LA BASE** : Trueshot Barrage (01PZ004) et
  Solar Snare (98PZ008) réclament trois clics ; Statikk Shock (01PZ031),
  Shock Blast (05PZ027), Jayce's Shock Blast (05PZ022T2) et Divine Draft
  (07PZ022) en réclament deux. Plateau adverse vide, `choose_targets` ne
  rend qu'UN point — le nexus — et il ne se clique qu'une fois.
  `sort_sans_cible` les écarte désormais, **sur un motif qui NOMME le
  nexus** plutôt que de dire « aucune cible », ce qui serait faux.
- **LA CLAUSE EST ÉTROITE À DESSEIN** et ne défait pas la doctrine du
  26/08 (« on exige zéro point, pas moins que prévu ») : un sort à deux
  cibles strictes dont UNE UNITÉ est trouvée garde sa chance, parce que
  notre comptage de marqueurs peut sur-compter. Ici il n'y a aucune unité
  du tout. Avec un ennemi en jeu, les six redeviennent lançables et rien
  ne change.

### « Fardeau » se demandait dans le mauvais mode — 75 sorts sur 566

- `actions.is_dead_weight` appelait `classify_card(card)` SANS argument,
  donc **`restricted=True` — le mode PRUDENT — même quand le bot joue
  sans restrictions**. Le piège est documenté depuis le 06/11 et il a
  mordu encore deux fois dans la nuit du 08-09/11 ; chaque fois on a
  noté le cas particulier au lieu de la cause.
- **MESURÉ LE 09/11 SUR LA BASE ENTIÈRE : 126 sorts « fardeau » en mode
  prudent contre 51 en mode par défaut — 75 sorts collectionnables sur
  566 (13 %) étaient traités comme du fardeau pur alors que le bot les
  joue.** Premiers défaussés au mulligan, derniers renforcés, derniers
  choisis dans une fenêtre. Parmi eux **Deny** (un contresort), Condemn,
  Brutal Skirmish, Bone Skewer, Boomerang Blade. La question se pose
  désormais dans `CARD_RESTRICTIONS`, le mode où le bot joue vraiment.

### Une suite hors ligne ne laisse rien derrière elle

- **« NE TOUCHE PAS LA MACHINE » ET « NE LAISSE RIEN DERRIÈRE SOI » SONT
  DEUX PROPRIÉTÉS DIFFÉRENTES**, et la seconde n'avait aucun garde. Le
  garde-machine disait « machine intacte » et il avait raison — rien
  n'était photographié de l'écran d'Ewan — mais `check.py --offline`
  déposait quand même **4 PNG de 1,5 Mo** dans `screenshots/` à chaque
  exécution. `combat.save_stuck_screen` enregistre ce que
  `capture_screen_bgr` lui rend, et en test c'est l'écran SYNTHÉTIQUE des
  doublures : un gris uniforme.
- **MESURÉ : 621 des 660 `bloque_*.png` du dossier (94 %, 0,98 Go)
  venaient de là.** Le dossier où l'on va chercher un vrai blocage était
  noyé sous son propre bruit, et une capture datée pouvait très bien
  n'être qu'un test. `test_combat.py` bouchonne donc `save_stuck_screen`
  dès l'import — en GARDANT les appels, parce qu'un test vérifie déjà
  qu'elle est demandée au bon moment. Test :
  `test_combat.test_la_suite_necrit_rien_dans_screenshots`. **Le ménage
  du dossier reste à faire** (0,98 Go récupérables).

### Le garde-machine a attrapé sa première fuite NEUVE — la nôtre, le jour même

- Le correctif « mettre le jeu devant » a immédiatement fait appeler le
  VRAI `focus_game_window` par les quarante sessions de
  `test_challenges` : **132 appels, dont 44 vols de premier plan par
  exécution**. `check.py` l'a affiché en rouge à côté d'un `[OK]` :
  « MACHINE TOUCHÉE ». C'est la **cinquième** fuite de l'histoire du
  projet et **la première à ne pas avoir vécu des semaines** — les
  quatre précédentes ont été découvertes par hasard, longtemps après.
  Le garde né le 08/11 a payé sa dette en une journée.
- Bouchon au niveau de la suite, appels gardés (`PREMIERS_PLANS`), et le
  test de l'ordre « on met devant, PUIS on regarde » continue de passer.

### Vladimir : Ewan dit qu'on peut valider à ZÉRO allié

- Réponse du 09/11 à la question ouverte du 06/11 : **il existe un geste
  pour valider sans désigner aucun allié**. Vladimir (01NX006), son
  niveau 2 et Crimson Pact pourraient donc être posés sans leur effet, au
  lieu de n'être plus posés du tout. **Non fait** : le geste n'est pas
  calibré, et personne ne sait encore où il tombe à l'écran. C'est le
  prochain chantier qui demande d'avoir le jeu sous les yeux.

### L'audit des neuf correctifs — 78 relecteurs, 44 constats tenus

Les neuf correctifs de la nuit ont été relus par des agents indépendants,
chacun chargé de DÉMOLIR le constat d'un autre. **44 constats ont résisté,
22 sont tombés.** Les quatre réparés le jour même sont ci-dessous ; le
reste est en bas, par ordre de valeur.

- **LE PREMIER CONSTAT TENU PORTAIT SUR LE CORRECTIF DU MATIN.**
  `rejection_reason` n'avait **aucun test d'équipement** dans sa branche
  « restrictions levées » : elle rendait None — c'est-à-dire JOUABLE —
  sur un équipement sans porteur, alors que `playable_cards` l'écarte
  depuis le 05/11. Le trou était MASQUÉ tant que `_describe` tenait sa
  propre liste de motifs (il écrivait « non — équipement » de son côté) ;
  en le faisant déléguer le matin même, on en a hérité, et
  `python actions.py plan` s'est mis à écrire JOUABLE sur The Darkin
  Lodestone banc vide.
  **C'est l'argument de la source unique, pas son démenti** : la
  divergence existait déjà, cachée derrière une seconde erreur, et une
  fois les deux chemins réunis il n'y a plus qu'un endroit à réparer.
  Test : `test_actions.test_un_equipement_sans_porteur_nest_pas_annonce_jouable`.
  **ET LE TEST QUI AURAIT DÛ LE VOIR LE GRAVAIT** : trente lignes après
  avoir vérifié « équipement sans allié : écarté »,
  `test_restrictions_levees` exigeait que `rejection_reason` réponde
  `None` pour la MÊME carte, sous le libellé « aucune raison pour ce qui
  est tenté ». Il se contredisait lui-même depuis le 05/11, et c'est
  cette ligne-là qui a rougi quand le trou a été bouché — pas le nouveau
  test. Un test peut tenir la main du défaut qu'il est censé attraper.

- **UN MASQUE TOUT BLANC NE CACHE RIEN, ET IL COÛTE QUATRE FOIS LE PRIX.**
  Depuis le 06/11 `best_match` passe `mask=` dès qu'un gabarit a quatre
  canaux. Or **seize des vingt gabarits à alpha l'ont uniformément à
  255** : le masque ne change pas le résultat (CLAUDE.md le mesurait déjà
  — « écart ≤ 0.00021 ») mais il interdit le chemin accéléré d'OpenCV.
  Ce qui n'avait jamais été mesuré, c'est le PRIX. Mesuré ici, meilleur
  de trois, sur `where_are_we` devant un écran NON reconnu (dix gabarits
  comparés) : **1,25 s avant, 0,31 s après — ×4,0, soit 0,94 s par
  lecture**. C'est exactement le poste que le relevé de temps du 08/11
  désignait : « les recherches de bouton coûtent 0,8-1,0 s quand elles
  aboutissent, **9-11 s quand elles échouent** ; tout le gras est dans
  les échecs, pas dans la vitesse des gestes ».
  Les quatre gabarits qui cachent vraiment quelque chose — `attack_token`,
  `continue_button`, `final_boss`, `player_marker` — gardent leur masque :
  **le test porte sur l'ALPHA, jamais sur un nom de fichier**, pour que
  le jour où un gabarit opaque gagne un vrai masque il le reprenne seul.
  Test : `test_challenges.test_un_masque_tout_blanc_nest_pas_passe_a_matchtemplate`.

- **`challenges.py --plan` PLANTAIT SUR L'ÉCRAN RESUME.** `STEPS_FROM` ne
  contient que les écrans qui ont un CHEMIN D'ENTRÉE ; RESUME, ajouté le
  06/11, n'en a pas — il a un bouton. `STEPS_FROM[screen]` levait donc
  KeyError exactement là où le bot, lui, sait reprendre l'aventure : la
  commande qu'on lance pour comprendre tombait sur le seul écran qu'on ne
  comprenait pas. RESUME est nommé, et un écran reconnu sans chemin
  décrit est désormais une information, pas une panne. Test :
  `test_challenges.test_le_mode_plan_ne_plante_sur_aucun_ecran_reconnu`,
  qui passe en revue TOUS les `Screen`.

- **`.gitignore` ligne 8 était `chiffreslogs/`** — deux entrées collées,
  donc ni `logs/` ni `screenshots/` (1,6 Go) n'étaient ignorés. Séparé en
  `logs/` et `screenshots/`. **`chiffres` n'est PAS ignoré, et c'est
  délibéré** : ses PNG sont des données du projet, enrichies palier après
  palier, et les versionner est tout l'intérêt du garde-fou du 08/11.

## La session du 10/11 — six chantiers en parallèle, et une carte refaite

Six agents sur des fichiers disjoints, puis `check.py --offline` : **18
suites, ~2 770 assertions, machine intacte**. Ce qui suit est classé par
ce que ça coûte en jeu, pas par ordre d'écriture.

### LA CARTE DES DETTES ÉTAIT PÉRIMÉE D'UNE NUIT — et c'est la leçon de méthode

- **Une session du 09/11 23:58 → 10/11 00:26 a réparé NEUF des treize
  points de l'audit sans toucher aux listes.** Vérifié point par point :
  `is_dead_weight`, `spells.py explain`/`coverage`, la colonne cadrée à
  40 de `journal.py`, le message trompeur de `--champions`, `monitor_web`
  (tentative et archétype), `navigate.py where` et ses quatre captures,
  « Sorts : exclus » d'`actions.py why`, `test_monitor_web`,
  `test_spells:929`, `_zone_attendue`, le verdict d'ensemble du
  garde-machine. Tous DÉJÀ RÉPARÉS.
- **C'est exactement le reproche que `journal.py --depuis` faisait à la
  boussole du projet**, retourné contre la liste des dettes elle-même :
  une carte qu'il faut vérifier avant de la croire n'en est pas une. Les
  listes ci-dessous portent désormais leur date de vérification.
- **CE QUI RESTAIT VRAI tenait en cinq points**, et quatre ont été faits
  aujourd'hui. Le cinquième est en bas.

### Les cartes `99xx` : une base présente, et INCOMPLÈTE EN SILENCE

- **« 2653 cartes » avait l'air complet. Il manquait TOUT le préfixe
  « 99… »** — des cartes exclusives aux aventures PvE, rencontrées à
  CHAQUE tentative : 99SH003 (×114 dans les logs), 99MT003 (×55),
  99PZ130 (×35), 99PZ104 (×29), 99IO003. Sans elles, `game_state` lit
  « 0/0 (inconnue) », `classify_card` rend `Targeting.NONE`, et **chaque
  décision de plateau raisonne sur un plateau faux**. Coût direct mesuré
  sur UNE tentative de 12 min (09/11) : `19:31:01 Pose de 99PZ130
  (inconnue)` → `19:31:24 mise de côté`, **23 s pour rien**, plus 8 s au
  combat suivant.
- **RIOT NE PUBLIE PAS CES CARTES, ET IL N'Y A PAS DE GABARIT DE NOM À
  TROUVER.** Sondage HEAD de tout le CDN le 10/11 : il existe
  **exactement quatorze paquets** — `core`, `set1`…`set9`, `set6cde`,
  `set7b`, `tpoc`, `adventure` — et c'est tout (`set10`, `set99`,
  `setevent`, `poc`, `tpoc2` répondent 403). Les douze JSON de cartes
  donnent **2670 cartes, préfixes 01-09 et 98, zéro 99**. `adventure` ne
  contient AUCUNE carte : `powers`, `items`, `relics` seulement. **Ne
  pas repartir en chasse d'un nom de fichier : il n'y en a pas.**
- **D'OÙ UNE SECONDE SOURCE, PESÉE AVANT D'ÊTRE BRANCHÉE.**
  `Module:LoRData/data` du wiki anglais a les 2910 cartes, `99xx` et
  `00xx` comprises, en ANGLAIS. Comparée au Data Dragon sur les **2648
  cartes communes** : coût 99,5 %, attaque 99,6 %, PV 99,2 %, type
  99,4 %, **mots-clés modélisés 99,85 %**, et **même plan de sort
  903/969 (93,2 %)**. Sur les 66 plans qui diffèrent : **ZÉRO change le
  camp du clic**, 20 rendent le bot plus prudent (le wiki écrit « Pick
  an ally… » là où Riot écrit « An ally… », que `REFUSALS` écarte), 6
  ouvrent un clic que Riot refuse, 40 ne changent que l'effet.
  **LE TEXTE DU WIKI EST UNE PARAPHRASE, PAS LE TEXTE DU JEU** : il ne
  sert donc QUE là où Riot n'a rien. `card_sets/cartes_hors_ddragon.json`
  se trie AVANT `set*.json` — Riot l'emporte tout seul le jour où il
  publierait ces cartes — et chaque carte porte un champ `source` :
  aucune ligne ne doit pouvoir passer pour une donnée de Riot.
  **Base : 2653 → 2898 cartes** (+17 du rafraîchissement, +228 hors Data
  Dragon, dont 119 en `99`). Vérifié par `load_card_db()` : les cinq
  codes témoins ont nom, coût, type et mots-clés.
- **UN FICHIER PRÉSENT PEUT ÊTRE PÉRIMÉ, ET C'ÉTAIT LE CAS.**
  `download_card_sets.py` court-circuitait sur `path.exists()`, or Riot
  ENRICHIT ses paquets en place : `tpoc.json` avait **141 cartes sur le
  disque contre 158 au CDN** — périmé en silence depuis des semaines.
  Chaque set est désormais confronté au CDN à chaque lancement, et un
  set qui revient PLUS PAUVRE n'écrase rien (il le dit ; `--force` passe
  outre). `--sans-wiki` revient au comportement Riot seul.
- **LE DIAGNOSTIC DOIT NOMMER LE TROU, PAS COMPTER DES CARTES.**
  `lor_api.CODES_TEMOINS` (les cinq codes RELEVÉS DANS LES LOGS, pas
  choisis) et `lor_api.etat_base_cartes()` → (total, hors DDragon,
  témoins manquants). Un compte ne dit jamais qu'une base est complète ;
  un témoin manquant dit qu'elle ne l'est pas. Tests : `test_lor_api.py`,
  dont `test_le_script_de_telechargement_garde_ses_deux_garde_fous` — les
  deux défauts du 06/09 (pas de `__main__`, `card_sets` relatif)
  n'étaient verrouillés par rien jusqu'ici. **PAS ENCORE VU TOURNER EN
  JEU** ; le point à surveiller est `99SH003 Clever Camouflage`, dont le
  texte wiki est une paraphrase.

### La patience en secondes, et l'attente adaptative

- **LES TROIS BORNES DE BLOCAGE COMPTAIENT DES LECTURES, PAS DU TEMPS**
  (`STUCK_CANCEL_AT` 12 / `STUCK_LIMIT` 25 / `STUCK_ABORT` 40). Tant que
  la boucle tournait à rythme fixe c'était la même chose ; accélérer
  l'aurait fait abandonner un combat en proportion — la panne même qu'on
  voulait éviter, échangée contre quelques secondes. Elles sont devenues
  `STUCK_CANCEL_AFTER` / `STUCK_PASS_AFTER` / `STUCK_ABORT_AFTER` =
  **50 / 104 / 167 secondes**.
- **LA CONVERSION N'EST PAS « × poll », ET C'EST TOUT LE SUJET.** Une
  itération gelée ne dure pas `poll` : elle dure `poll` PLUS la lecture,
  et la lecture est la part la plus lourde. Mesuré sans instrumentation —
  entre « Rien ne bouge depuis 12 lectures » et « Toujours bloqué » il y
  a exactement 13 itérations, et les deux lignes sont horodatées :
  **19 blocages en ATTACKING (06/09) à 4,19 s de médiane** (3,74-4,30) et
  **2 paliers en SPELL_STACK (05/11) à 4,38 puis 4,48 s**. Dont **2,2 s
  de LECTURE**. `poll` n'était que la MOITIÉ d'une itération.
- **L'horloge est le temps mural d'immobilité, avec un PLANCHER par
  lecture** (`DUREE_LECTURE` = 2,2 s). Sans plancher, sous l'horloge
  fictive des suites hors ligne ou avec `--poll 0`, le temps réel d'une
  lecture est nul et **le garde-fou ne s'armerait jamais** : la boucle
  tournerait sans fin. Bornes **arrondies vers le bas** : une borne plus
  LÂCHE ferait traîner un combat bloqué, c'est un défaut au même titre
  qu'une borne plus stricte.
- **CE QU'UNE BORNE UNIQUE NE PEUT PAS FAIRE** : rendre le même compte de
  lectures dans toutes les phases, puisqu'une itération n'y coûte pas la
  même chose. Les 21 blocages mesurés sont tous dans des phases qui
  dorment 2 s — l'étalon vient de là et y rend **12 / 25 / 40 à
  l'identique**. Une phase qui ne dort qu'une seconde obtient ~30 % de
  lectures en plus pour la même patience. C'est la patience EN SECONDES
  qui est la grandeur conservée. Conséquence assumée : un mulligan laissé
  à la main a 167 s d'immobilité au lieu de ~208 s.
- **L'ATTENTE EST ADAPTATIVE, ET L'INSTANTANÉ TRANCHE** (`CombatLoop.
  _attente`) : `poll × 0,3` quand le jeu attend un geste de NOUS (notre
  tour, blocage, pile orbe à nous, **ATTACKING orbe à nous**), `poll` en
  régime normal, `poll × 2` pendant le tour adverse, une attaque qui se
  résout, ou les menus. Tous multiples de `poll` : `--poll` reste le
  rythme d'ensemble et `--poll 0` ne dort toujours pas.
  `ATTENTE_ADAPTATIVE = False` remet l'ancien barème à la seconde près.
- **LE SOMMEIL PÈSE 90 s SUR 195 s DE COMBAT (46 %), ET CE N'EST PAS
  L'ATTENTE DE L'ADVERSAIRE.** Mesuré en rejouant le combat du 04/11 et
  en passant chaque instantané dans les deux barèmes : **90 s → 58 s,
  gain brut 32 s**. Honnêtement **~25 s réalisables (13 %)** : dans
  `ATTACKING orbe=oui` on ne fait que REGARDER, le gain n'y vaut qu'une
  demi-période par transition ; partout ailleurs on vient d'AGIR et le
  sommeil est de la latence pure. **La ligne « 20,3 s d'attente de
  l'adversaire » du découpage du 08/11 sous-estimait le poste d'un
  facteur quatre** — le gros du sommeil est notre propre scrutation à
  vide, et c'est elle qu'on raccourcit ; l'attente adverse reste intacte.
- **LE VRAI PLAFOND EST AILLEURS** : 2,2 s de LECTURE par itération, dont
  ~0,9 s par `snapshot()` à cause de la recherche multi-échelle du jeton
  d'attaque. C'est le prochain gisement, bien plus gros que `poll`.
- **UNE SUITE QUI NE PAIE PAS LA LECTURE MESURE UNE BOUCLE QUI N'EXISTE
  PAS.** Hors ligne, `stable_snapshot` rend un instantané tout fait : une
  itération ne durait que son `time.sleep(poll)`. Tant que les bornes
  comptaient des lectures, l'écart ne se voyait pas ; en secondes, il
  fausse tout. `ScriptedReader(…, cout_lecture=)` fait donc payer les
  2,2 s à l'horloge fictive. Tests :
  `test_combat.test_les_bornes_de_blocage_comptent_des_secondes`,
  `test_un_poll_plus_court_nabandonne_pas_plus_tot`,
  `test_lattente_est_courte_quand_le_jeu_attend_un_geste_de_nous`,
  `test_la_boucle_utilise_vraiment_lattente_adaptative`.
  **PAS ENCORE VU TOURNER EN JEU.**

### On ne guette pas « Relevez-vous » après une victoire LUE

- **NEUF SECONDES PAR BOSS FINAL GAGNÉ, DEVANT UN ÉCRAN QUI DISAIT DÉJÀ
  « VICTOIRE ».** Mesuré sur la tentative gagnée du 09/11 :

      19:40:11,844  Second « Continuer » : fin d'aventure (boss final)
      19:40:11,844  Recherche du bouton : retry
      19:40:20,872  Bouton 'retry' introuvable            <- 9,03 s
      19:40:22,403  victoire (bilan : 50 PV restants)     <- 1,53 s, UNE image

  Le bilan au cœur portait la victoire pendant tout le guet. D'où
  `lor_battle._victoire_deja_lue`, un COUP D'ŒIL (`COUP_D_OEIL_BILAN =
  0.0`, exactement UNE image) avant la recherche de `retry`. Coût ancien
  10,61 s, nouveau 1,53 s : **≈ 9,1 s gagnées par boss final gagné**.
- **INTERDIT DE SUPPRIMER LE GUET, et la règle est étroite** : seule une
  VICTOIRE positivement lue autorise à le sauter. Un verdict `None`
  **comme une DÉFAITE lue** laissent la suite intacte — « Relevez-vous »
  est justement ce que le jeu offre à qui vient de perdre, et s'en passer
  a coûté 2 × 120 s et une tentative le 05/09.
- **ET ON NE RELIT PAS UN ÉCRAN DONT LE VERDICT EST RENDU.**
  `_verdict_rendu` porte cette condition **une seule fois** —
  `settle_verdict` et `_judge_from_summary` la partagent, parce que deux
  implémentations du même test finissent toujours par diverger.
- **`_lire_le_bilan` EST LA SEULE COUTURE VERS L'ÉCRAN** de
  `lor_battle` : le juge complet et le coup d'œil y passent tous les
  deux, et c'est elle qu'on bouchonne — un bouchon par COUTURE, pas un
  par appelant. `test_challenges` la bouchonne dès l'import et vérifie en
  fin de suite qu'aucun test n'est allé lire le bilan : c'était le
  **sixième** guet capable de photographier l'écran d'Ewan.
- Tests : `test_challenges.test_final_boss_exits` — le cas b compare
  désormais la liste de gestes à la **séquence littérale d'avant**
  (verdict `None` = comportement d'avant, au geste près), et un cas neuf
  vérifie qu'une **défaite lue guette quand même** la nouvelle chance.
  **PAS ENCORE VU TOURNER EN JEU.**
- **CE QUI N'A PAS ÉTÉ FAIT, ET POURQUOI** : la dette « `attendre_verdict`
  coûte 2 × 8 s, avec 9 WARNING par tentative » est **surestimée**.
  Mesuré sur le même log : le premier appel rend en **1,5 s** (les 8 s
  sont un PLAFOND, pas un coût), le second immédiatement, et il y a
  **ZÉRO** WARNING « hors de sa place » dans toute la session. Le
  contrôle de position de `bilan.py` reste entier.

### Les deux dernières dettes du nexus

- **« IF THERE ARE NO ENEMIES, … THE ENEMY NEXUS INSTEAD » : LE TEXTE DIT
  LES DEUX, L'INSTANTANÉ TRANCHE** (`SpellPlan.resolves_without_target`).
  Trois cartes, toutes des jetons : Final Spark (01DE042T3), Javelin Toss
  (07SH013T2), Ace in the Hole (98PZ004).
  **LE DRAPEAU N'AUTORISE AUCUN CLIC** : `choose_target` rend toujours
  None sur un plateau vide, et `spell_is_castable` rend un tuple de
  cibles **VIDE**. Fabriquer ici le point du nexus ferait un clic que le
  jeu refuse — c'est LUI qui redirige, pas nous. Ce que le drapeau change
  est ailleurs : `play_spell` sortait ce cas en « ciblage INCOMPLET »,
  donc en ANNULATION après la pose, les ~23 s que le correctif du 08/11
  existe pour épargner (`sans_clic_attendu`).
  **ON LIT LE REPÈRE SUR LE TEXTE ENTIER**, comme les refus :
  `strip_preamble` retire justement les subordonnées de condition. **ET
  C'EST LE COUPLE QUI PARLE** : il faut « plus d'ennemis » ET « le nexus
  à la place », dans la même phrase. À ne pas confondre avec « If it's
  DEAD OR GONE, … the enemy Nexus instead » — quatorze textes de la base
  contiennent « Nexus instead », et là la cible existe au moment du clic.
- **NOTRE NEXUS EST UNE CIBLE, LUI AUSSI** (`SpellPlan.our_nexus_is_
  target`). Le miroir exact du chantier du 08/11 : banc vide, « Heal an
  ally **or your Nexus** 3 » rendait « aucun allié en jeu » et le soin
  était abandonné dans l'état même où il vaut le plus cher. **NEUF
  CARTES**, dont Health Potion, Ritual of Renewal, Guiding Touch,
  Starshaping — plus **deux UNITÉS** dont le « Play: » dit la même chose,
  Kindly Tavernkeeper et Smooth Mixologist. Pour ces deux-là le prix
  était pire : rien ne les écarte en mode par défaut, elles étaient donc
  POSÉES puis laissées devant un clic qu'on ne savait pas faire.
  **UN DRAPEAU, PAS UN `Targeting` DE PLUS** : en créer un ferait rater
  notre camp à tout le code qui teste `is Targeting.ALLY` — `riposte.py`,
  `actions.equipment_plan`, les refus de prudence.
  **LE REPÈRE EST ANCRÉ SUR LE MARQUEUR QUE `_scan_targets` A RETENU**,
  et c'est tout son intérêt : il hérite ainsi, sans les réécrire, des
  garde-fous d'en face — « a random ALLY » et la nullification par
  « randomly to » / « draw ».
- **BILAN MESURÉ sur les 2653 cartes** : **12 plans changent en mode
  permissif, 10 en prudent ; 9 changent le camp du clic, les 9 de
  « RIEN » vers « NOTRE NEXUS », ZÉRO d'un camp vers l'autre.** Plateau
  peuplé, **aucun plan ne bouge**. Écartés par `sort_sans_cible` plateau
  vide : **521 → 511**, 0 perdu. Balayage sur `your nexus or`,
  `nexus or an`, `allied nexus`, `if there's no`, `if no enem` : **zéro
  autre formulation**. **PAS ENCORE VU TOURNER EN JEU.** Tests :
  `test_spells.test_un_soin_peut_viser_notre_nexus`,
  `test_un_sort_qui_se_resout_sans_ennemi_le_dit_dans_son_plan`,
  `test_actions.test_un_sort_qui_se_resout_sans_ennemi_nest_pas_ecarte`,
  `test_un_soin_sans_allie_vise_notre_nexus`.
- **CE QUE ÇA NE RÉPARE PAS** : banc NON vide, on clique toujours
  l'allié, même intact — or soigner un allié à pleins PV ne fait rien,
  tandis que soigner un nexus abîmé fait toujours quelque chose. Peser
  les deux est une décision de jeu : **il doit venir d'Ewan.**

### Une commande de diagnostic qui meurt sous redirection — `sortie_utf8.py`

- **LA PARADE AVAIT ÉTÉ ÉCRITE TROIS FOIS, ET IL EN MANQUAIT UNE
  QUATRIÈME.** `check.py._sortie_en_utf8` (05-08/11), puis
  `replay.py.sortie_en_utf8` (10/11) — et `game_state.py` n'avait rien.
  Trois copies de la même vingtaine de lignes, c'est l'invariant que le
  projet répète partout (« deux implémentations du même test finissent
  toujours par diverger ») appliqué à un CORRECTIF au lieu d'une
  décision. La quatrième n'a pas été écrite : `sortie_utf8.appliquer()`
  est le point unique, et `game_state.main()` l'appelle AVANT tout.
- Le « ≤ » vient d'UNE ligne, « deck : N cartes, ≤ M à piocher »
  (`game_state.py:1504`) : `python game_state.py monitor > rapport.txt`
  mourait dessus dès que `/static-decklist` avait répondu. **`logging` ne
  le disait pas** — `sys.stderr` a `backslashreplace` par défaut et
  survit toujours, c'est le `print` qui tombe. C'est pour ça que le
  défaut est resté invisible si longtemps.
- **ET LE TEST EST ÉCRIT, alors que `check.py` déclarait la chose non
  testable** (« le défaut ne se reproduit que là où stdout n'est pas une
  console »). C'est précisément ce qu'un sous-processus avec un TUBE
  fabrique. `test_game_state.test_une_redirection_ne_tue_plus_le_
  diagnostic` lance deux enfants en `PYTHONIOENCODING=cp1252` : **sans la
  parade l'enfant DOIT mourir** (contre-éprouvette), avec elle il rend 0
  et écrit de l'UTF-8.
- **ET IL A FAILLI ÊTRE LA SIXIÈME FUITE.** Sa première version
  vérifiait le branchement en appelant `game_state.main()` sans
  argument : la commande par défaut va chercher le JEU — la suite est
  partie pour dix minutes et elle aurait photographié l'écran d'Ewan.
  On coupe désormais à la construction de l'analyseur d'arguments, qui
  est la première chose que `main` fait après la parade. **Le test censé
  prévenir une fuite en introduisait une.**
- **`combat.py` EST MIGRÉ AUSSI** : son `--- déroulé ---` reverse les
  lignes « [état] » du rapport, donc `python combat.py --plan >
  rapport.txt` mourait sur le même « ≤ ». Test :
  `test_combat.test_la_sortie_est_en_utf8_avant_toute_impression`, qui
  verrouille le BRANCHEMENT (un module peut être parfait et n'être
  branché nulle part) sans exécuter la commande — on coupe à la
  construction de l'analyseur d'arguments.
- **RESTE À MIGRER** : `check.py` et `replay.py` gardent chacun leur
  copie de la parade. Elles marchent ; elles sont juste en trois
  exemplaires au lieu d'un.

### Une tentative qui n'a jamais eu lieu — `challenges.py`

- **`--tentatives` COMPTAIT DES TOURS DE BOUCLE, PAS DES TENTATIVES.**
  `_stop_reason` lit `len(report.attempts)`, et `run` y rangeait aussi
  les entrées qui n'avaient jamais abouti. Le 09/11 l'éditeur de texte
  couvrait le jeu ; la session entière tient en deux lignes
  (`logs/challenges_20261109_192611.log`) :

      reprise 1 : inachevée en 0 min — écran inconnu au moment d'entrer
      Arrêt : nombre de tentatives demandé atteint (1)

  La CAUSE avait été réparée le jour même (`_mettre_le_jeu_devant`), le
  COMPTEUR non : toute panne d'entrée future aurait encore brûlé la
  session.
- **RIEN N'EST CONSOMMÉ, ET CE N'EST PAS UNE SUPPOSITION** :
  `_confirm_attempt` — le clic sur `use_attempt`, LE seul geste qui
  dépense une tentative hebdomadaire — est la **dernière** étape de
  chaque chemin de `navigate.STEPS_FROM`, et quand il aboutit l'entrée
  rend `LAUNCHED`. Donc `Entry.LOST` veut dire, sans exception, qu'il
  n'a jamais abouti. La règle est désormais une seule ligne,
  `if not attempt.entered: attempts.pop()`, qui GÉNÉRALISE le précédent
  déjà écrit juste à côté pour `NO_ATTEMPT_LEFT` (« elle n'a rien
  joué ») — il manquait seulement de le dire de l'AUTRE entrée qui n'a
  rien joué non plus.
- **MESURÉ** : **13 entrées manquées** sur les 63 lignes de tentative de
  `logs/` — le premier motif du relevé, devant les 10 défaites au boss
  intermédiaire. Et elles se rattrapent :
  `logs/challenges_20261106_203911.log` enchaîne « écran inconnu au
  moment d'entrer » puis **DEUX VICTOIRES**.
- **LE GARDE ANTI-BOUCLE EXISTAIT DÉJÀ, ET ON L'A PROUVÉ AU LIEU D'EN
  ÉCRIRE UN SECOND** (deux implémentations du même test divergent) :
  `_lost` / `LOST_LIMIT` = 3 plafonne les entrées manquées
  **consécutives** et n'est remis à zéro que par une entrée qui réussit.
  Preuve, pas confiance : avec `LOST_LIMIT = 10**9`, le cas (c) du test
  **ne se termine jamais** (processus tué à 25 s). Sans ce verrou, le
  correctif aurait remplacé une session trop courte par une session SANS
  FIN, souris prise.
  Aucun des trois compteurs n'est remis à zéro par une entrée manquée :
  `LOST` fait monter `_lost` (3 tours), `RESUMED` stérile fait monter
  `_abandons` que `LOST` ne remet jamais à zéro (6 tours en alternance,
  vérifié), une entrée qui joue fait monter `attempts`. Prix assumé :
  une panne permanente coûte 3 tours au lieu d'1, soit une dizaine de
  minutes mesurées, contre une session hebdomadaire.
- **LE JOURNAL NE DOIT RIEN ÉCRIRE LÀ, ET C'EST PLUS FORT QUE « C'EST
  PROPRE »** : `champions.DERNIER_CHOIX` / `DERNIER_PALIER` ne sont
  remis à jour que par `choisir_champion`, qu'une entrée manquée
  n'atteint jamais. Une ligne écrite là porterait le champion et le
  palier de la tentative PRÉCÉDENTE — un échec fantôme imputé à un 7 ★
  innocent, et `journal.py --champions` faussé. Le comportement était
  déjà bon (`_play_one` rend la main avant `record_attempt`) ; il est
  maintenant verrouillé par un test.
- **LA TRACE N'EST PAS PERDUE** : `SessionReport.entrees_manquees` les
  compte à part et le bilan les affiche, et `AttemptReport.summary()`
  dit « entrée manquée » au lieu du « reprise 1 » doublement faux du
  09/11. Le message de `LOST_LIMIT` nomme désormais la cause n°1
  mesurée — **une fenêtre qui couvre le jeu**, pas un template.
- **UN TEST GRAVAIT LE DÉFAUT, ENCORE UNE FOIS.**
  `test_recovered_screen_resets_the_counter` affirmait « les deux
  tentatives réussies sont jouées » et exigeait `len(report.attempts)
  == 4` — les deux entrées manquées comprises. Même famille que la ligne
  de `test_restrictions_levees` qui tenait la main de l'équipement sans
  porteur.
- Tests : `test_challenges.test_une_entree_manquee_ne_brule_pas_la_session`
  (4 cas : le 09/11 à l'identique sous `--tentatives 1`,
  `NO_ATTEMPT_LEFT` qui n'est pas une panne, le garde seul, le garde
  composé). Rougeur vérifiée par trois mutations ciblées.
  **PAS ENCORE VU TOURNER EN JEU.**

### Les réponses d'Ewan du 10/11/2026 — trois faits, trois décisions

- **ON GARDE LE WIKI.** Décision d'Ewan sur la base de cartes : les
  cartes `99xx` restent peuplées depuis `Module:LoRData/data`, malgré le
  fait que ce soit une PARAPHRASE et non le texte du jeu. L'échange est
  assumé en connaissance des chiffres (93,2 % des plans de sort
  identiques, ZÉRO qui change le camp du clic, 6 qui ouvrent un clic que
  Riot refuse). `--sans-wiki` reste la porte de sortie si une carte se
  met à cliquer à côté. **Le point à surveiller en jeu est `99SH003`
  Clever Camouflage**, dont le texte wiki dit « Pick an allied
  follower… ».

- **« DIFFICULTÉ ★ N » N'EST PAS LA MÊME GRANDEUR QUE LES ÉTOILES DU
  CHAMPION**, et **le plancher de 3 ★ reste** (Ewan). La mesure du 10/11
  montrait « ★ 1 » aux paliers 2 et 4 là où la table demande 3 : ce
  n'était pas la table qui sur-payait, c'est que **le jeu note la
  difficulté du DÉFI, pas la force qu'il faut y engager**. On NE remplace
  donc PAS `etoiles_requises` par cette lecture, et les 1-2 ★ restent
  hors du pool. La table de départ (`3 + (palier - 1) // 14`, plafond 7)
  continue d'être corrigée par `python journal.py --champions`, c'est-à-
  dire par les parties.
  **Ce qui reste utilisable de cette mesure** : le PALIER lui-même se lit
  dans la liste des défis (« DÉFI 22 » → 22, « DÉFI 24 » → 24), ce qui
  ferait une SECONDE source quand le titre de la grille est illisible.
  Non fait.

- **VLADIMIR : ON CLIQUE L'ENNEMI, PUIS LE BOUTON BLEU À DROITE** (Ewan,
  10/11, réponse à la question ouverte depuis le 06/11). Il existe donc
  bien un geste pour valider **ZÉRO allié**, et il ne consiste pas à
  cliquer des alliés : on désigne l'ENNEMI, puis on valide par un bouton
  bleu situé à DROITE de l'écran (Ewan n'a pas le libellé exact). Zéro
  allié désigné = l'effet ne fait rien, mais **le champion est posé**, au
  lieu de ne plus l'être du tout. Piste à vérifier avant de coder : ce
  bouton est très probablement l'ORBE DE TOUR que le projet sait déjà
  lire et cliquer (`assets/orb/<label>.png`, `read_turn_button` →
  `snapshot.button_label` ; le projet note déjà que « LE BOUTON EST BLEU
  et dit RÉSOUDRE pendant une fenêtre de réponse »).

- **LA COULEUR DES PV DE NOTRE NEXUS NE CHANGE PAS : C'EST CRÈME**
  (Ewan). Donc un nexus au maximum n'affiche rien de particulier, et il
  ne faut attendre aucun changement de teinte entre « abîmé » et
  « plein ». C'était la question laissée ouverte en tête de
  `bilan.py:172-181`.
  **ET LA MESURE DIT AUTRE CHOSE SUR LE BILAN, il faut le savoir** : sur
  les deux captures chiffrées du dépôt, les PV COURANTS sortent dans une
  teinte que le masque orange attrape, le maximum non —
  `bilan_defaite_20261104.png` → `courant=0 maximum=20 glyphes_orange=1`,
  `victoire_defi13_20261106.png` → `courant=26 maximum=63
  glyphes_orange=2`. Les deux ne se contredisent utilement que sur UN
  point, et il est sans danger : **la branche « nexus intact par ABSENCE
  d'orange » (`lu.orange == 0`) ne se déclenchera jamais en vrai**, et le
  juge passera toujours par le chemin ordinaire (« victoire : N PV
  restants »). Les deux chemins sont testés, aucun ne peut inventer un
  verdict. **Ne pas « réparer » l'un au nom de l'autre sans une capture
  de bilan au nexus PLEIN** — c'est la seule image qui trancherait, et
  nous ne l'avons pas.

### Le correctif du 05/11 n'avait jamais été porté à l'autre bout (10/11/2026)

- **UNE RÈGLE ÉCRITE À UN SEUL ENDROIT N'EST PAS UNE RÈGLE.** Le
  05/11/2026, `respond_to_stack` a appris à lire le LIBELLÉ DU BOUTON
  avant l'orbe — c'est le correctif du blocage de Yoink!, 184 s et une
  tentative hebdomadaire. `let_stack_resolve`, **l'autre endroit qui
  regarde la pile**, ne l'a jamais appris : il ne lisait que
  `latest.stack_theirs` puis `latest.turn_orb_active`. Or c'est lui
  qu'on atteint juste après avoir validé NOTRE sort.
- **MESURÉ SUR LES 22 BLOCAGES DE TOUT `logs/`** : la première lecture
  de `respond_to_stack`, **4,5 s après l'abandon** (médiane, max 5,3 s),
  trouve `button_label == "cible"` **21 fois sur 22**. Le jeu affichait
  « SÉLECTIONNER LA CIBLE » pendant TOUT le blocage — il attendait un
  geste de nous pendant qu'on attendait l'adversaire. **508 s perdues,
  23,1 s de moyenne.**
- **LE 10/11 AU SOIR, SEPT FOIS, TOUTES SUR FLASH FREEZE** (01FR001,
  « Frostbite an enemy. »), dont une dans le combat du **boss final** —
  ~240 s. La carte n'est pas coupable : elle était en tête des
  « jouables » à chaque tour, c'est **la première carte jouée du tour
  qui essuie les plâtres**.
- **LES DEUX VARIANTES SONT LE MÊME DÉFAUT.** Selon l'état de l'orbe, le
  log disait « L'adversaire a la priorité : on attend » (orbe éteinte)
  ou « on passe (OK) » (orbe allumée) — **même test `turn_orb_active`,
  même issue**. D'où un seul correctif, placé AVANT lui, et non à côté.
- **SOURCE UNIQUE** : `actions.geste_pour_une_cible_reclamee(snapshot,
  dry_run)` rend `None` quand le bouton ne réclame rien, sinon FAIT le
  geste et rend la phrase à journaliser. `respond_to_stack` et
  `let_stack_resolve` l'appellent tous les deux, chacun en tête de son
  traitement. Recopier la logique aurait recréé exactement le défaut
  qu'on répare — « deux implémentations du même test finissent toujours
  par diverger », et ici la seconde n'avait même pas été écrite.
- **LA FENÊTRE PASSE AVANT L'ANNULATION, et c'est le garde-fou du
  05/11** : une fenêtre de choix ne s'annule pas (trois clics droits
  sans effet dans la trace). On cherche `visible_card_window`, on PREND
  une carte, et on n'annule que s'il n'y a rien.
- **ON NE RELIT PAS APRÈS LE GESTE**, et c'est délibéré : une annulation
  remet la carte en main, donc une relecture rendrait un état sans elle
  sur la pile et `play_spell` conclurait « résolu » pour une carte qui
  ne l'est pas. L'état rendu dit encore « sur la pile » → le sort est
  mis de côté jusqu'au prochain round, **ce qui se passait déjà, mais en
  ~3 s au lieu de ~23, et avec le mana rendu**.
- **PAS DE DOUBLE ANNULATION** : dans `play_spell`, la branche « sur la
  pile » rend la main avant le filet d'annulation de fin de fonction.
  Vérifié.
- **ET ON GARDE ENFIN UNE IMAGE.** `actions.journaliser_pile_bloquee`
  est appelée au « X toujours sur la pile après validation » : elle
  écrit `screenshots/pile_bloquee_<carte>_<date>.png` et journalise
  `snapshot.summary()`, le libellé du bouton et l'orbe. **C'est la
  partie du livrable qui manquait ce soir-là** — personne ne photographie
  l'écran sur ce chemin, et on ne sait toujours pas POURQUOI le clic de
  ciblage de Flash Freeze n'a pas été pris. Le guet est **bouchonné dès
  l'import** de `test_actions.py` (`PILES_BLOQUEES`, appels gardés) :
  c'est le sixième guet de ce genre, les cinq premiers ont tous fini par
  photographier l'écran d'Ewan.
- Tests : `test_actions.test_un_bouton_qui_reclame_une_cible_nest_pas_une_priorite_adverse`
  (les DEUX états de l'orbe), `test_une_fenetre_de_choix_retient_aussi_notre_propre_sort`,
  `test_une_orbe_grise_sans_libelle_sattend_comme_avant` (non-régression
  de la règle d'Ewan du 03/09), `test_une_pile_qui_ne_se_vide_pas_laisse_une_image`.
  **PAS ENCORE VU TOURNER EN JEU.**

### Une suite lancée en script peut s'importer ELLE-MÊME (10/11/2026)

- **`test_actions.py` contenait `from test_actions import
  blocking_snapshot as _bs`, inutilisé, au milieu d'un test.** Lancée en
  script, la suite est `__main__` : cette ligne chargeait donc une
  SECONDE COPIE du module et **rejouait tout son corps**, bouchons
  d'import compris. À partir de là, `actions.journaliser_pile_bloquee`
  pointait sur le bouchon de la COPIE, et la liste que le test relit —
  celle de `__main__` — restait vide.
- **LE SYMPTÔME ÉTAIT UN HEISENBUG PARFAIT** : rouge en lançant
  `python test_actions.py`, vert en lançant `python -c "import
  test_actions; test_actions.main()"` (le module est alors déjà dans
  `sys.modules`, l'import interne ne fait rien), vert aussi dès qu'on
  ajoutait un espion, puisque l'espion s'installait après coup. On a
  d'abord accusé la lenteur de la machine : à tort.
- **UN BOUCHON QUI GARDE UN ÉTAT DOIT PORTER CET ÉTAT SUR LE MODULE
  BOUCHONNÉ**, pas sur la suite — `actions._piles_bloquees_test`, lu
  avec `getattr(..., None)` avant d'en créer un. C'est le seul endroit
  que les deux copies partagent. La ligne fautive a été retirée ; la
  parade reste, parce que **onze fichiers font `from test_actions
  import …`** et que l'un d'eux suffirait à la rejouer.

### Une suite verte dépend de la VITESSE de la machine (10/11/2026)

- **L'HORLOGE VIRTUELLE LAISSE PASSER LE TEMPS RÉEL.**
  `test_clock.install_virtual_clock` pose `time.time = _REAL_TIME() +
  _offset` : dormir n'attend plus, mais **le temps réellement écoulé
  compte toujours**. Or `actions.AIM_MAX_AGE` vaut 0,8 s et fabriquer
  une scène de test coûte **~0,17 s de vraie seconde** (matching de
  gabarits sur l'écran synthétique). Quatre scènes construites avant
  l'appel, et la lecture qui a décidé est PÉRIMÉE : `play_card` /
  `play_spell` relisent la main au lieu de viser, et le test devient
  rouge **sans qu'une ligne de code ait changé**.
- Mesuré le 10/11 sur un dépôt INTACT : **10 assertions rouges** sur
  `test_actions.py`, 13 et 17 avec une seconde suite en parallèle, 0 sur
  une machine au repos. Quatre tests concernés — Starshaping/Invoke,
  Choix capital, « la main est relue entre deux poses », et le cas (a)
  de « la main est relue avant la saisie ». Le remède est l'idiome que
  CLAUDE.md prescrivait déjà : **`avant.taken_at = time.time()` juste
  avant l'appel**.
- **CE N'EST PAS UNE RUSE, C'EST LE SUJET DU TEST** : ces quatre-là
  décrivent la POSE, pas la fraîcheur de la lecture — celle-ci a son
  propre test, qui périme son instantané exprès
  (`avant.taken_at -= AIM_MAX_AGE + 1`).

## Diagnostiquer sans souris

```powershell
python check.py --offline                 # les suites de tests seules
python LoR-Bot/code/download_card_sets.py  # remplir/rafraîchir la base — Riot ENRICHIT ses paquets en place
python lor_api.py                         # la base est-elle complète ? (codes témoins relevés en jeu)
python game_state.py monitor              # la phase en direct
python game_state.py inspect              # ce que l'API rapporte, là
python actions.py plan                    # ce qu'il jouerait ce tour
python actions.py attack --plan           # attaque + tirages prévus
python actions.py block --plan            # blocages, « dont N gratuit(s) »
python combat.py --plan                   # une itération à blanc
python replay.py list traces/<dossier>    # relire une trace (--record), puis show/plan/combat N
python navigate.py where --snap           # score de CHAQUE template
python challenges.py --plan               # l'écran reconnu et la suite
python spells.py explain "..."            # un texte de carte
python spells.py coverage                 # la base entière
python journal.py                         # taux de victoire par config — 30 DERNIERS JOURS par défaut
python journal.py --ecartees              # cartes écartées par motif : le backlog
python journal.py --champions             # taux de victoire par (palier, étoiles)
python journal.py --depuis tout           # … sur tout l'historique (ou --depuis AAAA-MM-JJ / --jours N)
python champions.py cut-defi <N> [capture x0 y0 x1 y1]  # police du titre — le 3 et le 5 viennent de la LISTE, pas d'un titre
python bilan.py <capture.png>             # quel verdict porte un écran de fin de tentative
python champions.py [capture.png]         # étoiles lues par vignette, et le champion retenu
python mots_cles_ecran.py [capture.png]   # icônes de mots-clés sous chaque unité ; `cut-icone` récolte un gabarit
python monitor_web.py                     # tout ça dans un navigateur, en direct : http://127.0.0.1:8765/ (--sans-ocr pour ne pas charger torch)
```

**Arrêt d'urgence : amener la souris dans un coin de l'écran** (fail-safe
pyautogui).

## La session du 11/11 — DEUX CARTES ONT MANGÉ LA TENTATIVE

Session de 29 min (13:09-13:38), arrêtée par Ewan en plein combat. **Une
tentative achevée, perdue au boss final** (25 min, 3 combats), une seconde
interrompue. Le bilan tient en une phrase : la navigation et les juges
n'ont rien coûté, **deux cartes ont coûté presque tout**.

### UNE UNITÉ « ATTACH » SANS ALLIÉ N'EST PLUS POSÉE (11/11/2026)

- **LE REFUS SE PREND DANS `actions.unit_play_blocker`, ET AVANT
  `unit_play_plan`** (`actions.sans_allie_a_qui_s_accrocher`). Trois des
  quatre cartes `Attach` n'ont AUCUNE description — `classify_unit_play`
  rend None, et la fonction sortait aussitôt sur `if plan is None`. Mis
  dans une branche de plan, le refus n'aurait jamais tourné.
- **LE PÉRIMÈTRE EST CELUI DE L'ÉQUIPEMENT, PAS UN SECOND COMPTAGE** :
  on appelle `equipment_plan`, qui passe par `spells.choose_target(ALLY)`
  et lit `board` ET `attack_row`. Compter le seul banc refuserait la pose
  en pleine attaque, où nos unités sont lues au centre (deux horloges).
- **BILAN MESURÉ sur les 1579 unités/landmarks des 2898 cartes** : banc
  vide, **10 codes changent de verdict dans LES DEUX MODES** (41→51 en
  défaut, 149→159 en prudent) — les 10 `Attach`, et eux seuls. Banc
  peuplé, **ZÉRO plan ne bouge**. Zéro exception, zéro collatéral.
- **ET CE N'ÉTAIT PAS UN FAUX POSITIF DE `resolve_unforeseen_choice` —
  LA CAPTURE DIT LE CONTRAIRE.** Sur
  `screenshots/bloque_ATTACKING_20261111_133640.png`, (820, 410) marqué :
  le jeu propose **DEUX VERSIONS** de Yuumi, « LIEN » (05BC029T3,
  « Grant the unit I'm Attached to ») à GAUCHE et la libre (05BC029,
  « Otherwise, grant me ») à DROITE. Le filet du 04/09 a vu juste ; c'est
  **`unforeseen_choice_rank` qui a tiré à pile ou face** — même coût 3,
  même 2/1, même nom, donc clés ÉGALES, `max` rend le premier de l'ordre
  de lecture. Il est tombé **deux fois** sur la version qui réclame une
  cible. La version de droite aurait posé le champion sans rien demander.
- **DONC LE REFUS EST LA CONDUITE SÛRE, PAS LA BONNE.** Le vrai gain
  serait de CHOISIR la version libre quand le banc est vide : c'est un
  fait de jeu, il doit venir d'Ewan. Prix assumé en attendant : la
  version libre n'est plus posée non plus.
- Tests : `test_actions.test_une_unite_attach_sans_allie_nest_pas_posee`
  (19 assertions ; **10 rougissaient** avant le correctif, les 9 de
  non-régression étaient déjà vertes). **PAS ENCORE VU TOURNER EN JEU.**

### « CHALLENGING A MARKED ENEMY » — refusé hors de portée (11/11/2026)

- **L'ADJECTIF `marked` NE RESTREIGNAIT PAS LE MARQUEUR, IL LE FAISAIT
  DISPARAÎTRE** — l'inverse exact de la règle du 26/08. Aucun motif de
  `SINGULAR_TARGETS` ne lit « a marked enemy » : `Targeting.NONE`, aucun
  clic prévu, carte posée, jeu en attente d'une cible que personne ne
  donne. Prix mesuré : **Beast's Frenzy (98SB047) lancée 15 fois,
  10 blocages de pile, 5 « restée en main » sur trois combats, ~80 s**,
  pour une carte forte souvent à coût 0.
- **ON NE RÉTABLIT PAS LE MARQUEUR, ET C'EST TOUT LE SUJET** : le
  marquage est un mot-clé ACCORDÉ EN JEU, donc INVISIBLE — l'API ne rend
  qu'un CardCode, et Dance of Arrows marque un ennemi AU HASARD. Cliquer
  un ennemi non marqué ferait refuser le clic : on échangerait un blocage
  contre un autre. C'est la famille des cibles sous condition invisible
  (« est étourdi », « a attaqué ce round », 02/09), donc un refus
  **HORS DE PORTÉE**, qui vaut dans LES DEUX MODES.
- **À NE PAS CONFONDRE AVEC « AN ATTACKING ENEMY »** (ouvert le 06/11) :
  celui-là se LIT dans `attack_row` / `enemy_attack_row`. La ligne de
  partage est « lisible » contre « invisible », jamais la forme de la
  phrase.
- **LE MOTIF EXIGE UN DÉTERMINANT SINGULIER, ET C'EST LE GARDE-FOU**
  (`spells.MARKED_TARGET`) : « all marked enemies » n'est PAS un marqueur
  — c'est le jeu qui marque, les dégâts tombent seuls, et Dance of Arrows
  FONCTIONNE (vue tourner, résolue plusieurs fois le 11/11). Idem pour
  « Enemies are marked. » et pour le VERBE « Mark an enemy. » (Patient
  Beast, 98SB046), dont la cible est un ennemi ordinaire cliquable.
- **BILAN MESURÉ sur les 2898 cartes** : **SEPT écrivent « marked », UNE
  SEULE porte l'adjectif sur un marqueur. 1 plan change par mode, 0
  change le camp du clic, 0 carte passe d'écartée à jouable.** Refus au
  total 95 → 96 (défaut), 264 → 265 (prudent). `coverage` est inchangé :
  98SB047 est `collectible: False` (set Tpoc) — **le backlog ne regarde
  que les collectionnables, et les cartes d'aventure sont justement
  celles que le bot rencontre.**
- **EFFET DE BORD ASSUMÉ** : la carte devient du fardeau pur
  (`is_dead_weight` True dans les deux modes, le refus étant hors de
  portée) — première défaussée au mulligan. C'est cohérent pour une carte
  qu'on ne peut plus lancer, mais ça se verra en partie.
- **RESTE OUVERT** : lire le marquage à l'écran rendrait la carte, mais
  c'est un chantier de VISION, pas une ligne de `spells.py`.
  **PAS ENCORE VU TOURNER EN JEU.** Test :
  `test_spells.test_une_cible_marquee_est_hors_de_portee`.

### La capture du blocage est prise AVANT le geste (11/11/2026, soir)

- **LES DIX CAPTURES DU 11/11 MONTRAIENT LE PLATEAU DÉBLOQUÉ.**
  `journaliser_pile_bloquee` photographiait au moment d'écrire son
  rapport, c'est-à-dire APRÈS que `geste_pour_une_cible_reclamee` ait
  annulé — orbe « FIN DU ROUND », pile vide, tour repris. Le TEXTE de
  l'instantané, lui, était juste (il vient du `latest` d'avant le
  geste) : la contradiction était invisible à la lecture du log seul,
  et c'est pour ça qu'elle a survécu au premier livrable de la session.
- **LA CAPTURE APPARTIENT AU GESTE, PAS AU COMPTE RENDU** — « un bouchon
  par COUTURE, pas un par appelant » (10/11) appliqué au diagnostic. Elle
  est prise EN TÊTE de `geste_pour_une_cible_reclamee`, avant
  `visible_card_window` et avant les deux gestes qui effacent le blocage.
  Les DEUX appelants en héritent sans une ligne de plus : photographier
  dans chacun recréerait le défaut que la source unique existe pour
  éviter, et le test l'affirme pour `respond_to_stack` ET pour
  `let_stack_resolve`.
- **ON GARDE EN MÉMOIRE, ON N'ÉCRIT QUE SI LE BLOCAGE EST CONFIRMÉ** :
  mesuré sur tout `logs/`, **51 gestes pour 38 journalisations** —
  écrire au geste ajouterait jusqu'à 13 PNG de ~1,5 Mo inutiles, le
  bruit même qu'on a reproché aux tests le 09/11. Prix inverse : jusqu'à
  13 captures en MÉMOIRE pour rien, **une seule retenue à la fois**
  (~6 Mo), et un temps négligeable — les 10 journalisations du 11/11
  tiennent en **0,098 à 0,121 s**, encodage PNG et écriture comprises,
  sur un chemin qui dort déjà ~2 s. `dry_run` ne photographie RIEN.
- **UNE GARDE N'EST SERVIE QUE FRAÎCHE** (`FRAICHEUR_CAPTURE_DIAGNOSTIC`
  = 10 s, consommée à la lecture) : `respond_to_stack` fait le geste sans
  que personne n'appelle le rapport, et sans borne son image serait
  servie des minutes plus tard pour un blocage sans rapport. Trajet
  mesuré geste → rapport : ~2 s (13:14:16 → 13:14:18). Repli sur une
  capture fraîche quand aucun geste n'a eu lieu — l'écran est alors
  encore celui du blocage. Le log dit lequel des deux.
- **SEPTIÈME GUET CAPABLE DE PHOTOGRAPHIER L'ÉCRAN D'EWAN, ET IL A
  DÉMÉNAGÉ SUR UN CHEMIN PLUS FRÉQUENTÉ.** `capturer_pour_diagnostic`
  est la SEULE couture vers l'écran d'`actions.py` ; `test_actions.py`
  la bouchonne dès l'import, l'état porté par `actions` (piège du
  10/11 : une suite lancée en script s'importe elle-même). Mesuré :
  **6 appels par exécution** hors du test dédié. Contre-épreuve en
  `GARDE_MACHINE=bloquer` avec la vraie capture remise : « PREMIER
  GESTE SUR LA MACHINE : pyautogui.screenshot() ». Avec le bouchon :
  **774 assertions vertes, `[GARDE-MACHINE] rien touché`**.
- Test : `test_actions.test_la_capture_du_blocage_precede_le_geste`
  (ordre dans UN SEUL journal — deux listes diraient « les deux ont eu
  lieu » sans dire lequel d'abord). **PAS ENCORE VU TOURNER EN JEU.**

### Un « palier illisible » muet — `champions.journaliser_palier_illisible`

- **LE 11/11 À 13:09:27, LE MESSAGE AFFIRMAIT UNE CAUSE QU'IL NE
  CONNAISSAIT PAS** : « (police incomplète) ». Le palier était **25**,
  et le 2 comme le 5 sont dans `chiffres/N_defi.png` — le 5 y a été
  récolté le 10/11 et **relu tout seul dans un vrai titre** le soir
  même. Prix : `palier: null, etoiles: 7` au journal, un **7 ★** engagé
  là où `etoiles_requises(25)` demande **4 ★**, sur trois tentatives par
  champion et par mois.
- **ET PERSONNE NE POURRA TRANCHER : AUCUNE IMAGE N'A ÉTÉ GARDÉE.** Seul
  PNG du dépôt entre 12:00 et 13:11 ce jour-là : `noeud_quitte_
  20261111_131018.png`, la carte d'aventure, 51 s trop tard. Même manque
  que « combat sans effet » le 08/11 — **la capture est le vrai
  livrable**.
- **CE QU'ON A PU ÉCARTER SANS IMAGE, ET RIEN DE PLUS** : la police du
  titre se reconnaît elle-même, sûrement — chaque `N_defi.png` relu par
  son propre chemin rend son chiffre à **score 1.000**, marges 0.232 (5
  et 6) à 0.444 (2), loin au-dessus de 0.72/0.10. Le 2 et le 5 ne sont
  pas ambigus. La cause est ailleurs, et elle reste inconnue.
- **ON GARDE DONC L'ÉCRAN, ET ON DIT CE QU'ON A VU.**
  `journaliser_palier_illisible()` écrit
  `screenshots/palier_illisible_<date>.png` et journalise en WARNING les
  grandeurs de `digits.read_number(debug=True)` : taille de la bande,
  chaque boîte claire (`l×h` en x), le refus éventuel du garde-fou de
  hauteur avec les hauteurs mesurées, puis **chaque glyphe `-> chiffre
  (score, marge)`**, marqué quand il n'atteint pas
  `CONFIDENT_SCORE/MARGIN`. « Zéro boîte » et « boîtes dépareillées »
  sont deux pannes : les confondre nous laisserait aussi démunis
  qu'avant.
- **L'ÉCRAN GARDÉ EST CELUI QUI A ÉCHOUÉ**, pas un suivant
  (`DERNIER_ECRAN_TITRE`, posé par `attendre_palier`) — la leçon du
  11/11 sur `journaliser_pile_bloquee`, dont les 10 captures montrent le
  plateau DÉJÀ débloqué.
- **SOURCE UNIQUE** : `_nombre_du_titre` découpe, `lire_palier` DÉCIDE
  dessus, `_diagnostic_du_titre` EXPLIQUE dessus, et
  `python champions.py <capture>` imprime le même texte — le diagnostic
  ne peut pas raconter autre chose que la décision.
- **C'EST AUSSI LA SEULE FAÇON DE RÉCOLTER LE 0 ET LE 8**, qui manquent
  toujours à la police du titre : `python champions.py cut-defi <N>
  [capture x0 y0 x1 y1]` sur une capture gardée ici.
- **LE REPLI NE CHANGE PAS** : palier illisible → toujours le plus
  étoilé. On ajoute un diagnostic, pas une décision de jeu.
- **SEPTIÈME GUET QUI PHOTOGRAPHIE L'ÉCRAN** : bouchonné dès l'import de
  `test_champions`, liste portée par `champions._paliers_illisibles_test`,
  appels gardés ; et un test vérifie EN FIN DE SUITE que le bouchon tient
  et qu'aucun `palier_illisible_*.png` n'a été déposé. 16 assertions,
  **garde-machine « rien touché »**. Tests :
  `test_champions.test_un_palier_illisible_sur_la_grille_laisse_une_image`,
  `test_la_suite_necrit_rien_dans_screenshots`.
  **PAS ENCORE VU TOURNER EN JEU** (11/11).

## La session du 14/11 — QUATRE CORRECTIFS VUS TOURNER, et le 8 récolté

35 min (13:13-13:48), `check.py` vert au départ (18 suites, base à 2898,
API joignable, fenêtre trouvée). **5 tentatives : 1 VICTOIRE, 1 défaite,
3 inachevées. 4 combats, 4 VERDICTS** — zéro `gagne: null` pour la
troisième session d'affilée (historiquement 70 sur 111). Arrêt propre et
de lui-même sur « impossible de reprendre l'aventure déjà en cours ».

### LE 8 COÛTE LA MARGE D'UN TÉMOIN — et un témoin qui refuse reste un témoin

- `test_champions.test_le_3_et_le_5_viennent_de_la_liste_des_defis` a
  ROUGI sur un seul témoin : la difficulté « etoile 3 » (8x19 px) de
  `liste_defis_20261108.png`. Mesuré, le même glyphe :

      sans le 8 :  3=0.808, 9=0.697  -> marge 0.111  -> LU 3
      avec le 8 :  3=0.808, 8=0.728  -> marge 0.080  -> REFUSÉ (None)

  **Il n'est jamais lu AUTREMENT** — le 3 reste le meilleur candidat à
  0.808 — il perd seulement sa marge face au 8, qui lui ressemble.
  L'invariant « jamais une valeur approchée » est intact ; c'est le
  plancher de marge (0.10) qui mord.
- **ENRICHIR UNE POLICE RESSERRE SES MARGES**, et c'est la leçon
  générale : chaque chiffre ajouté est un concurrent de plus pour tous
  les autres. Le « etoile 3 » est le plus fragile parce qu'il fait
  **19 px** là où un titre en fait 27-38 — à la frontière de ce que
  `digits` sépare.
- **LA RÉPARATION PAR UNE 3e SOURCE EST UNE IMPASSE, MESURÉE.** Le
  troisième rendu indépendant du 3 que CLAUDE.md signalait — le « 3 » de
  « DÉFI 23 » dans la liste (13x31 après découpe, `liste_defis_20261108.png`
  ligne y=499, la seule des trois qui rende `None`) — **n'apporte
  rien** : ajouté comme variante, le témoin reste à **0.808**, marge
  inchangée à 0.080. Et il n'existe **aucun autre « etoile 3 »** dans le
  dépôt pour servir de source non circulaire (en récolter un sur le
  témoin lui-même ferait un gabarit qui ne reconnaît que lui-même —
  l'anti-patron que le projet dénonce).
- **ET LE NOMMAGE L'INTERDIRAIT DE TOUTE FAÇON** : `digits._family` rend
  `stem[2:]`, donc `3_defi2.png` est la famille « defi2 », pas « defi »,
  et `load_variants(families=('defi',))` l'ignore. **Une seconde
  variante dans une même famille n'est pas nommable aujourd'hui.** C'est
  la vraie dette technique derrière ce symptôme.
- **LE TÉMOIN A ÉTÉ ADAPTÉ, PAS RETIRÉ** (décision d'Ewan du 14/11, après
  que la réparation technique a été mesurée sans gain). Il prend la forme
  que le test emploie DÉJÀ trois lignes plus bas pour « DÉFI 23 », qui est
  dans exactement le même état depuis le 10/11 : **« 3 ou rien, jamais
  autre chose »**. Ce n'est pas un assouplissement de confort — c'est la
  seule chose qu'un témoin puisse encore garantir quand le plancher de
  marge mord, et c'est la chose qui compte : une lecture FAUSSE reste
  interdite. **Rougeur vérifiée par mutation** : forcer ce témoin à rendre
  8 fait échouer l'assertion. Les deux colonnes mesurées (0.111 → 0.080,
  concurrent = le 8) et la raison sont écrites DANS le test, pas
  seulement ici.
- **ÉTAT LIVRÉ : le 8 est EN PLACE, `check.py --offline` est VERT** — 18
  suites, ~2 970 assertions, machine intacte. Le 8 se retire en une ligne
  (`chiffres/8_defi.png`) et se re-récolte en une commande, la capture
  étant gardée dans `screenshots/`.

### « TO PLAY, DISCARD 1 » EST UN COÛT, PAS LA CIBLE (14/11/2026)

**Fait de jeu d'Ewan** : « le bot n'arrive pas à utiliser Enthousiasme de
Jinx ! — il arrive bien à défausser une carte de ma main mais n'a pas su
viser le nexus ennemi quand il n'y avait pas d'ennemi sur le banc
adverse. »

- **LA DÉSIGNATION EN MAIN MANGEAIT LA CIBLE DU PLATEAU.** Jinx's Get
  Excited! (01PZ040T3) dit « To play, discard 1. Deal 3 to anything. » ;
  `classify_text` rendait `Targeting.HAND` et **JETAIT** les cibles
  trouvées — `spells.py explain` répondait « Clic : non ». Le bot payait
  le coût, le sort partait sur la pile, et le jeu attendait un clic que
  personne ne faisait, jusqu'au garde d'immobilité (~50 s).
- **CE N'ÉTAIT PAS UN OUBLI, C'ÉTAIT UNE DÉCISION ÉCRITE** : « deux
  interfaces à la suite, c'est deux fois plus d'occasions de se tromper,
  et un échec au milieu laisse la partie dans un état qu'on ne sait pas
  décrire ». **Ce que la partie montre, c'est que l'état redouté est
  DÉJÀ celui qu'on produit, systématiquement et sans exception.** Ne pas
  cliquer n'était pas le choix prudent : c'était le pire des deux.
- **`targeting` RESTE `HAND`, LE PLATEAU PASSE DANS
  `SpellPlan.board_targeting`.** C'est `targeting is HAND` qui déclenche
  `designate_in_hand` (`needs_hand_pick`) : basculer le ciblage sur le
  plateau aurait fait perdre la défausse. `board_plan()` rend le
  sous-plan par `dataclasses.replace`, donc le montant, les cibles
  supplémentaires, la condition de cible et les deux nexus suivent sans
  être recopiés.
- **L'ORDRE VIENT D'EWAN, PAS D'UNE DÉDUCTION** : la défausse D'ABORD
  (« To play » est un coût, il l'a vue partir), la cible ENSUITE. Le
  clic est émis dans `play_spell` APRÈS `designate_in_hand`, sur
  l'instantané `fresh` que celle-ci vient de rendre — la main s'est
  recentrée, les points d'avant le dépôt ont glissé (les deux horloges).
- **LE REFUS SE PREND AVANT LA POSE**, comme `sort_sans_cible` :
  `spell_is_castable` calcule la cible dans la branche `needs_hand_pick`
  et rend un motif préfixé « sort : » s'il n'y en a pas. Poser puis
  découvrir qu'on n'a rien à cliquer, c'est le blocage qu'on répare.
- **SEPT CARTES, dont TROIS collectionnables et DEUX `98SB`** —
  c'est-à-dire la famille que le bot croise en aventure, comme Beast's
  Frenzy : Get Excited! (01PZ039) et le jeton de Jinx (01PZ040T3) vers
  `ANYTHING` ; Timewinder (04PZ003), que CLAUDE.md nommait en relecture
  le 08/11 sans la réparer, vers `ANYTHING` ×2 ; Electro Harpoon
  (05BC078) vers `ANY_UNIT` ; Spinning Axe (01NX020T1) vers `ALLY` ;
  Shroomsplosion! (98SB006) et celle de Teemo (98SB031T1) vers `ENEMY`.
  **ZÉRO en mode prudent** : il refuse toujours, sur « coût additionnel
  à payer » (`REFUSALS`, `^to play,`), qui mord avant la branche « deux
  interfaces ». Couverture inchangée : **515/566 jouables (91 %)**.
- **LE COMPTE DES CIBLES NE SE RECALCULE PAS, et l'avoir recalculé était
  un défaut de ce correctif même** — attrapé par le diagnostic, pas par
  les tests. Compter les marqueurs restants dans la branche du coût
  donnait **1** cible à Timewinder (« …and 1 to another ») là où le
  chemin normal en compte **2** : on n'aurait cliqué qu'une cible sur
  deux, donc recréé le blocage qu'on répare. C'est `extra_targets`, déjà
  calculé plus haut, qui fait foi. Encore la même leçon : deux
  implémentations du même calcul divergent.
- **ET LE DIAGNOSTIC DISAIT ENCORE « Clic : non »** une fois le geste
  en place — le défaut du 09/11 sur `actions.py plan`, à l'identique.
  `__str__` annonce désormais « …, puis unité_ou_nexus ×2 sur le
  plateau » et `cmd_explain` répond « oui ». On vient lire cette ligne
  pour savoir ce que le bot va FAIRE.

### LE MONTANT SE LIT SUR LA CLAUSE QUI PORTE LA CIBLE (14/11/2026)

- Trouvé en réparant la carte d'Ewan : son plan sortait **sans montant**.
  `amount_match = _AMOUNT_RX.match(core)` est **ancré en tête du texte**,
  alors que l'effet, lui, se lit depuis le 06/11 sur `effect_clause`.
  Pour un sort ordinaire la clause porteuse EST la tête — rien ne
  changeait ; dès qu'une clause de COÛT ou un déclencheur précède, le
  montant était perdu.
- **MESURÉ SUR LES 2898 CARTES : 37 changent, dont 36 passent de « aucun
  montant » à leur vrai montant** — Scrapshot (7), Monster Harpoon (5),
  Rite of the Arcane (4, la carte qui a bloqué le 14/11), Augmented
  Experimenter (3), Get Excited! (3), Sigil of Malice (2), Undergrowth,
  Vladimir, Avarosan Marksman… Sans lui, `best_kill` choisissait sa
  cible **à l'aveugle** : le sort partait, mais sur n'importe qui.
- **LA 37e VA DANS L'AUTRE SENS, ET C'EST TANT MIEUX** : Stylish Shot
  (07NX009) écrit « Deal 1 to the enemy Nexus. The next time an ally
  strikes… ». Ce « 1 » frappe le nexus **tout seul** ; il n'a jamais
  décrit la cible qu'on clique. Le montant appartient à la cible, donc à
  sa clause. Aucun test existant n'a bougé.

## La session du 14/11 au soir — le palier se lit, et un défaut neuf

18 minutes (22:10:35 → 22:28:26), arrêtée par Ewan en plein combat de boss
final. **Une seule tentative, non achevée** (aucune ligne `tentative N :`
dans le log), **un combat joué et GAGNÉ**. Log :
`logs/challenges_20261114_221035.log`.

### LE PALIER SE LIT ENFIN — VU TOURNER EN JEU

- **MESURÉ, 22:10:47** : « Palier 37 : on vise 5 étoile(s) — le plus
  faible qui suffit », puis 22:11:10 « Grille des champions : 5 étoile(s)
  pour une cible de 5, le plus haut niveau de la bande, en (573, 897) ».
  **ZÉRO palier illisible sur la session**, contre **7 sur 8 lectures**
  l'après-midi même (`logs/challenges_20261114_153145.log` : 7 « Palier
  illisible alors que la grille EST affichée » pour 1 seul palier lu) —
  et sept tentatives payées au « plus étoilé » faute de cible.
- **LA CAUSE ÉTAIT UNE POLICE RÉCOLTÉE AU MAUVAIS ENDROIT.**
  `chiffres/3_defi.png` avait été pris le 10/11 sur la LISTE des défis,
  faute d'un titre qui porte un 3. Sur un VRAI titre il identifiait bien
  le 3, mais sans la marge : **score 0.779, marge 0.068** pour un
  plancher de 0.72 / 0.10 — mesuré deux fois à l'identique, au palier 31
  (15:54:22) et au palier 36 (16:42:06). Refusé, donc, et c'est le
  garde-fou du 08/11 qui faisait son travail : jamais une valeur
  approchée.
- **UNE VARIANTE DE PLUS NE PEUT QUE RELEVER UN SCORE** — c'est la
  doctrine déjà écrite dans `load_variants` (« une police de plus par
  chiffre, c'est une marge de plus »), qui prend le MAX des variantes
  d'un chiffre. Seul le NOMMAGE l'interdisait : `_family` rend
  `stem[2:]`, donc `3_defi2.png` est la famille « defi2 ». D'où deux
  lignes — `digits.RESERVED_FAMILIES` et `champions.TITRE_POLICE`
  passent à `("defi", "defi2")` — et pas une de plus.
- **`3_defi2.png`** est découpé sur
  `screenshots/palier_illisible_20261114_155422.png` (le palier 31 de
  l'après-midi) : le glyphe passe de 0.779 / 0.068 à **1.000 / 0.290**.
- **LE `6` SOUFFRAIT DU MÊME MAL, ET LE LOG LE CHIFFRE** : au palier 36
  (16:42:06) le second glyphe sort « aucun (score 0.822, marge 0.013) ».
  Le concurrent était le **`8` récolté le matin même** — mesuré en
  rejouant l'état : 6 = 0.822 contre 8 = 0.809, soit exactement les
  0.013 du log. D'où `6_defi2.png`, découpé sur
  `screenshots/palier_illisible_20261114_164206.png` : **1.000 / 0.156**.
  **ET LE `0` RÉCOLTÉ LE SOIR AGGRAVAIT ENCORE** : avec lui dans le lot,
  c'est 0 = 0.844 qui coiffe le 6. Chaque chiffre ajouté est un
  concurrent de plus pour tous les autres — **enrichir une police
  resserre ses marges**, et c'est la rançon des récoltes du 14/11.
- **NON-RÉGRESSION MESURÉE** : les **8 captures de palier illisible du
  jour se lisent toutes** — 28, 30, 31, 32, 33, 34, 35, 36 — et les
  titres connus du dépôt sont inchangés (2, 2, 4, 11, 19).
- **RESTENT INTROUVABLES** : aucun titre du dépôt ne porte un `0` ni un
  `8` en premier chiffre ; ces deux-là n'ont que leur variante unique.

### `RESERVED_FAMILIES` : UN TEST QUI GRAVAIT UNE CONSTANTE

- `test_digits.test_une_police_sert_la_ou_elle_a_ete_recoltee` affirmait
  `digits.RESERVED_FAMILIES == ("defi",)`. **Il testait la VALEUR, pas la
  propriété** : ajouter une variante parfaitement légitime le faisait
  rougir **sans qu'aucune police de titre ait fui dans les badges**,
  c'est-à-dire sans que rien de ce qu'il protège ait bougé.
- Réécrit pour vérifier ce qu'il prétend : **chaque famille `*_defi*`
  présente dans `chiffres/` doit être réservée**, quel que soit son nom.
- **ROUGEUR PROUVÉE PAR MUTATION** : retirer `defi2` de
  `RESERVED_FAMILIES` fait rougir **3 assertions**, et le décompte dit
  pourquoi — le lot par défaut passe de **17 à 19** gabarits (10 de base
  + 7 du nexus, plus les 2 variantes qui auraient fui). Le garde-fou
  attrape donc toujours la vraie faute.
- **TROISIÈME TEST DU PROJET À TENIR LA MAIN DU DÉFAUT QU'IL GARDE**,
  après `test_restrictions_levees` (l'équipement sans porteur, 09/11) et
  `test_recovered_screen_resets_the_counter` (les entrées manquées,
  10/11). Le motif se répète : **une assertion qui fige une valeur au
  lieu de décrire un comportement finit par interdire la bonne
  correction.**

## La session du 15/11 — TROIS VICTOIRES SUR TROIS, et le Joker enfin compris

38 minutes (18:14:38 → 18:52), `check.py` vert au départ (20 suites, base à
2898, API joignable aux menus, fenêtre trouvée). Arrêtée par Ewan en pleine
quatrième tentative. Log : `logs/challenges_20261115_181438.log`.

**TROIS TENTATIVES, TROIS VICTOIRES.** Palier **39 → 42**.

| | |
| --- | --- |
| tentative 1 | VICTOIRE en 7 min — 4 nœuds, 1 combat |
| tentative 2 | VICTOIRE en 5 min — 4 nœuds, 1 combat |
| tentative 3 | VICTOIRE en 23 min — 5 nœuds, **2 combats dont le boss final** |

**4 combats, 4 verdicts** — zéro `gagne: null` pour la quatrième session
d'affilée (historiquement 70 sur 111). **Zéro « Rien ne bouge », zéro écran
inconnu, zéro entrée manquée.** Entrée en 38 s.

### LE JOKER — Ewan, 15/11 : « le bot ne sait pas jouer la carte Joker »

**ET LE DIAGNOSTIC EST À L'ENVERS DU SYMPTÔME : LE BOT SAIT LA JOUER, IL
CROIT AVOIR ÉCHOUÉ.** Joker, c'est **Wild Card** (98BW003, « Play a Destiny
Card. »), du deck Twisted Fate. La trace tient en six lignes :

    18:29:23  Lancement de Wild Card (AUTRE sur aucune).
    18:29:26  Wild Card est sur la pile : validation.
    18:29:31  Fenêtre de choix ouverte (3 cartes) : on prend Blue Card
    18:29:31  Wild Card toujours sur la pile après validation.   <- ÉCHEC
    18:29:31    stack  Blue Card | Wild Card | Gold Card | Red Card
    18:29:32  Sort sur la pile (nous : Blue Card)                <- ÇA A MARCHÉ

Une seconde après l'« échec », Blue Card est sur la pile : le choix a
abouti. Mais la carte a été **bannie pour le round** et rejouée au suivant,
en boucle — **10 fois** dans la session, 7 fois le 14/11 au soir.

- **LA CAUSE EST UN COMMENTAIRE JUSTE, APPLIQUÉ AU MAUVAIS GESTE.**
  `geste_pour_une_cible_reclamee` en fait **DEUX, aux conséquences
  OPPOSÉES** : l'annulation REND la carte à la main (il ne faut donc pas
  relire — c'est écrit depuis le 10/11, et c'est vrai), la prise de carte
  FAIT AVANCER la résolution (il faut relire, sinon on conclut à l'échec
  d'un sort qui a abouti). `let_stack_resolve` sortait dans les deux cas,
  sur le raisonnement de l'annulation seule.
- **LE GESTE SE NOMME DÉSORMAIS** (`actions.GesteReclame(phrase,
  fenetre_prise)`). Le redeviner chez l'appelant aurait été une seconde
  implémentation du même test — et c'est exactement ce que la source unique
  du 10/11 existe pour empêcher.
- **PENDANT LA FENÊTRE, LA CARTE JOUÉE ET SES OPTIONS SONT TOUTES DANS
  `stack`.** C'est le symétrique d'un piège déjà connu de l'autre côté :
  le 04/09 on apprenait, pour `play_card`, à ne pas conclure à la RÉUSSITE
  sur la foi d'un code vu au centre (« la version affichée porte le code de
  la carte jouée dans la bande attack »). Le miroir — ne pas conclure à
  l'ÉCHEC sur la foi d'un code vu sur la pile — n'avait jamais été écrit.
- **ON NE REPREND LA FENÊTRE QUE SI L'ÉCRAN A BOUGÉ** (`snapshot_signature`
  avant et après). Sans ce garde, un clic qui ne prend pas fait recliquer
  la MÊME carte jusqu'à `STACK_PASS_ATTEMPTS` — or le jeu DÉSÉLECTIONNE ce
  qu'on reclique (loi des panneaux à deux rangées, 08/11). Écran figé : on
  sort comme avant, la carte est mise de côté. C'est ce garde qui a fait
  rougir trois tests existants, et ils avaient raison.
- **BILAN MESURÉ sur tout `logs/`** : **61 blocages de pile toutes causes,
  dont 23 (38 %) avaient une fenêtre prise juste avant** — Wild Card **17**,
  Flash Freeze 2, Rite of the Arcane 2, Stance Swap 2. **Wild Card est la
  première cause de blocage de pile de tout l'historique du projet**,
  devant Beast's Frenzy. (L'appariement regarde les trois lignes qui
  précèdent : les trois cartes autres que Wild Card restent à confirmer.)
- **UN TEST GRAVAIT UNE VALEUR AU LIEU D'UN COMPORTEMENT, POUR LA
  QUATRIÈME FOIS.** `test_une_fenetre_de_choix_retient_aussi_notre_propre_sort`
  exigeait `reader.calls == 0` sous le libellé « aucune attente de
  l'adversaire ». Or une relecture n'est pas une attente : c'est
  `wait_for_change` qui attend. Le test interdisait donc la correction même
  qu'il aurait fallu faire. Il espionne désormais `wait_for_change`. Après
  `test_restrictions_levees` (09/11), `test_recovered_screen_resets_the_counter`
  (10/11) et `RESERVED_FAMILIES` (14/11).
- Tests : `test_actions.test_une_fenetre_prise_fait_avancer_la_resolution`
  (3 volets : le geste se nomme, la prise relit, **l'annulation ne relit
  toujours pas**). Rougeur prouvée par mutation — forcer la sortie après
  tout geste fait échouer « NOTRE SORT A QUITTÉ LA PILE DANS L'ÉTAT
  RENDU ». **PAS ENCORE VU TOURNER EN JEU.**
- **CE QUE ÇA NE FAIT PAS** : le texte « Play a X Card » n'est toujours pas
  déclaré dans `spells.CARD_WINDOWS`, donc le sort passe par le FILET
  (`visible_card_window`) et non par un plan de fenêtre — `spells.py
  explain` dit encore « Clic : non », ce qui reste exact. L'y ajouter est
  une piste, à mesurer sur toute la base avant.
- **ET LE CHOIX RESTE ARBITRAIRE** : **10 fois sur 10, « Blue Card »**, la
  première de l'ordre de lecture. Les trois Destiny Cards d'aventure ne se
  valent pourtant pas — **Gold Card** (98BW004) « Deal 7 and Stun the
  strongest enemy », **Red Card** (98BW006) « Deal 2 to all enemies and the
  enemy Nexus », **Blue Card** (98BW005) « Refill 2 spell mana. Draw 2 ».
  Leurs clés `card_pick_rank` sont strictement égales (trois sorts à coût
  0), donc `max` rend la première : c'est **le tirage à pile ou face**
  déjà vu sur Yuumi (11/11) et Volibear (14/11), une troisième fois.
  **RÉGLÉ LE SOIR MÊME PAR LA RÈGLE D'EWAN** — voir « LA DESTINY CARD
  SE CHOISIT SUR LE PLATEAU », juste en dessous.

### UNE JUMELLE EN MAIN N'EST PAS LA CARTE VISÉE

- **`wait_until_card_left` CONCLUAIT « LE CLIC N'A PAS PRIS » SUR UNE CARTE
  BIEN PARTIE.** Il passe par `find_our_card`, qui **retombe sur une
  recherche PAR CODE** quand le CardID ne correspond plus. Le deck Twisted
  Fate a des doublons (deux Wild Card, trois Pick a Card, trois Make it
  Rain) : le repli trouvait la jumelle restée en main. Le log montre les
  deux états à la suite —

      avant : Wild Card#1204492146[hand] ... Wild Card#1625478173[hand]
      après : Wild Card#1625478173[hand]

  — la carte visée EST partie. **12 fois dans la session.**
- **LE REPLI EST LÉGITIME LÀ OÙ IL EST NÉ, ET ON NE LE RETIRE PAS.**
  `wait_for_designation_target` cherche une carte à CLIQUER : attraper une
  jumelle de même code y est sans conséquence, les deux exemplaires étant
  identiques. Constater un DÉPART, non. D'où `actions._notre_carte_est_
  encore_la`, par CardID quand l'API le donne, comptage par code sinon —
  **la règle que `_left_zone` applique déjà aux zones** depuis les deux
  Thrall Bulwark du banc (« un comptage par code ne distingue pas deux
  exemplaires d'une même carte »). Elle manquait sur ce chemin-là.
- **BILAN MESURÉ sur tout `logs/`** : 21 désignations déclarées « le clic
  n'a pas pris », dont **5 où les CardID PROUVENT que la carte visée était
  partie** (Wild Card 3, Twisted Fate 1, Dreadway Deckhand 1). Les 16
  autres sont indéterminées — le log n'a pas les deux états consécutifs, ou
  il n'y avait pas de doublon.
- Tests : `test_actions.test_une_jumelle_en_main_ne_fait_pas_echouer_une_defausse`,
  avec la non-régression « sans CardID, le comptage par code reste le
  repli ». Rougeur prouvée par mutation. **PAS ENCORE VU TOURNER EN JEU.**

### LA DESTINY CARD SE CHOISIT SUR LE PLATEAU (règle d'Ewan, 15/11/2026)

**Ewan, en réponse à la question laissée ouverte le soir même** : « règle
ça toi-même, en fonction de si plusieurs unités ont 2 hp, si on a peu de
carte en main ou besoin de piocher, et si on doit stun un ennemi fort ».
Trois signaux, trois cartes — et les trois se lisent sur l'instantané.

- **LE DÉFAUT N'EST PAS DANS LE CLASSEMENT, IL EST DANS L'ÉGALITÉ.**
  Mesuré : les trois Destiny Cards ont des clés `card_pick_rank`
  **strictement égales — `(1, 0, 0, 0)`** : trois sorts jouables, non-
  unités, de `card_value` 0, à coût 0. `max` rendait donc la première de
  l'ordre de lecture de l'API, **10 fois sur 10 « Blue Card »**. Troisième
  occurrence du même tirage à pile ou face, après Yuumi (11/11) et
  Volibear (14/11) — et la première à être réparée.
- **LE CRITÈRE EST LE DERNIER, ET C'EST TOUT LE GARDE-FOU.** Il ne peut
  jamais renverser un choix que les quatre précédents tranchaient déjà ;
  il ne départage que des égalités parfaites. Et il vaut `0.0` sans
  instantané, donc `choose_offered_card(cards)` sans second argument
  rend exactement ce qu'il rendait avant.
- **ON NE RECONNAÎT PAS CES TROIS CARTES.** `spells.lire_effet_immediat`
  compte des marqueurs du texte anglais — « to all enem(y|ies) », « the
  strongest enemy », « stun », « draw N », « and the enemy Nexus » —
  comme tout le reste du module. **POURQUOI UNE LECTURE DE PLUS** :
  `classify_card` répond « que faut-il CLIQUER », et rend `DAMAGE 2`
  pour « Deal 2 to all enemies » comme pour « Deal 2 to an enemy »,
  parce que du point de vue du GESTE c'est pareil — aucun clic dans les
  deux cas. Pour CHOISIR, il manquait l'autre moitié : la PORTÉE, et les
  effets qui ne se voient pas sur le plateau (la pioche).
- **L'ÉCHELLE EST CELLE DES ÉCHANGES, PAS UN BARÈME NEUF** :
  `keywords.unit_value` (attaque + PV) pour ce qu'on tue, l'ATTAQUE pour
  ce qu'on étourdit — « le tempo d'un round », comme
  `choose_trade_targets` le chiffre déjà depuis le 05/09. Seule la pioche
  demandait un nombre, parce que rien dans le projet ne la chiffrait :
  `VALEUR_PIOCHE_MAIN_COURTE` = 2.0 jusqu'à `MAIN_COURTE` = 3 cartes,
  `VALEUR_PIOCHE` = 0.5 au-delà. **Ces trois nombres sont les seuls
  inventés, et c'est `journal.py` qui doit les corriger, pas
  l'intuition.**
- **PAS D'OCR POUR ÇA** : les PV du nexus adverse ne sont pas dans
  l'instantané (ils viennent de l'OCR que `plan_attack` déclenche
  explicitement). On prend le poids de BASE de la stratégie du deck —
  payer une lecture d'écran pour départager deux cartes déjà à égalité
  serait l'inverse de la leçon d'« an attacking enemy » (06/11).
- **CE QUE ÇA DONNE, mesuré sur les quatre scénarios du test** (poids de
  nexus 1.0) :

      plateau                        GOLD   RED   BLUE   pris
      3 ennemis 1/2, main 5           3.0  11.0    1.0   RED
      1 ennemi 5/5, main 5           10.0   2.0    1.0   GOLD
      plateau vide, main 2            0.0   2.0    4.0   BLUE
      3 ennemis 1/2, main 2           3.0  11.0    4.0   RED

  Le dernier cas est le plus instructif : main courte ET trois cibles, et
  c'est le plateau qui l'emporte — ce qui est bien l'ordre d'Ewan, la
  pioche n'étant nommée qu'en l'absence de meilleure affaire.
- **PORTÉE MESURÉE SUR LES 2 659 CARTES DÉCRITES** : **2 113 (79,5 %)
  ont un critère NUL** — pour elles le choix est identique à l'avant au
  bit près. Les 546 autres portent un trait lisible (216 dégâts seuls,
  162 pioche, 82 stun, 25 « le plus fort », 33 zone et/ou nexus), et même
  pour celles-là le critère ne joue que si les quatre premiers sont à
  égalité. **Zéro erreur de lecture sur la base entière.**
- Tests : `test_actions.test_la_destiny_card_se_choisit_sur_le_plateau`
  (les trois scénarios d'Ewan, plus « la zone l'emporte sur la pioche »
  et la non-régression d'une fenêtre ordinaire, dont la raison est
  MESURÉE — le critère y vaut 0.0 partout — et non supposée). **Rougeur
  prouvée par QUATRE mutations ciblées** : neutraliser le critère, la
  zone, la main courte ou le stun fait rougir exactement le scénario
  correspondant. **PAS ENCORE VU TOURNER EN JEU.**
- **CE QUE ÇA NE FAIT PAS** : le tirage à pile ou face d'
  `unforeseen_choice_rank` (Yuumi, Volibear) reste entier — c'est l'autre
  fonction, sur les fenêtres de VERSIONS, et ses options ont le même nom
  et les mêmes stats. La parade y sera différente.

## La session du 16/11 — deux victoires, et la boutique qu'on quitte

15 min (23:31 → 23:46), `check.py` vert au départ (20 suites, ~3 000
assertions, base à 2898, API joignable, fenêtre trouvée). Arrêtée par Ewan
pendant la tentative 3, **aventure laissée ouverte** — elle se reprendra
par « REPRENDRE L'AVENTURE », aucune tentative n'est perdue. Log :
`logs/challenges_20261116_233113.log`.

**2 tentatives, 2 victoires. 3 combats, 3 verdicts** — cinquième session
d'affilée sans un seul `gagne: null`. Palier **43 → 44 → 45**, lu à chaque
fois, cible 6 ★ honorée à chaque fois. **Zéro palier illisible, zéro
blocage de pile, zéro « Rien ne bouge », zéro entrée manquée, zéro carte
mise de côté.** Les trois juges ont tous donné de la voix : écran de
victoire (×2) et aventure poursuivie.

### LA BOUTIQUE EST QUITTÉE AVEC 840 PO EN POCHE

- **C'EST LE COFFRE DU 04/11, SUR UN AUTRE NŒUD.** Capture :
  `screenshots/noeud_quitte_20261116_234122.png` — le panneau « Boutique »
  offre **« Acheter des cartes » / « Acheter des objets » / « Quitter »**,
  des cartes à **45 et 60 PO** (Trésor piégé, épique ; Corne de héros,
  « Piochez un champion »), et le bot a **840 PO**. Il clique « Quitter ».
- Même conséquence que le coffre avant le 04/11, et elle est écrite ici
  depuis : « il arrivait au boss final avec un deck jamais amélioré ».
  Sauf qu'ici l'or s'accumule en plus — rien ne le dépense jamais.
- `captures_reference/boutique_20261105.png` existe depuis le 05/11, mais
  **seulement comme témoin NÉGATIF** pour d'autres gabarits : rien ne joue
  ce nœud. La capture gardée vient de `resolve_arrival`, exactement le
  chemin qui avait révélé le coffre.
- **NON FAIT** (décision d'Ewan le 16/11 : « la boutique mais demain »).
  Ce qu'il faudra trancher avant de coder, et qui est une DÉCISION DE JEU :
  quoi acheter, et quand s'arrêter. Le reste est de la mécanique déjà
  connue — un panneau, des tuiles, un bouton.

### L'ÉCRAN DE FIN DE DÉFI N'EST PAS UN ÉCRAN CONNU — et le bouton, lui, l'est

- **MON PREMIER DIAGNOSTIC ÉTAIT FAUX, ET LA MESURE L'A DIT.** J'avais
  écrit que le « CONTINUER » doré du bilan n'était reconnu par aucun
  gabarit. Mesuré sur la capture
  `screenshots/ecran_inconnu_20261116_233522.png` : **`continue_button`
  note 1.00 en (955, 939)**. Il n'y a aucun gabarit à découper. Ce que le
  log montrait n'était pas un bouton manqué, c'était **l'enchaînement de
  plusieurs écrans de fin différents**.
- **CE QUE COÛTENT VRAIMENT LES 23 s**, tour par tour (23:35:22 →
  23:35:45, quatre tours de `back_to_known_screen`) :

      tour 1   bilan affiché, CONTINUER cliqué                      2,9 s
      tour 2   écran suivant pas encore dessiné — 3 recherches
               ratées + souris garée + délai                        7,3 s
      tour 3   CONTINUER cliqué                                     4,6 s
      tour 4   même tour à vide pendant le fondu                    6,2 s

  **Les deux tours les plus chers sont des attentes de fondu déguisées en
  recherches**, et on ne peut pas les supprimer : il faut bien que le jeu
  dessine. Le gras réel est ailleurs, et il est petit.
- **CE QUI RESTE GAGNABLE, MESURÉ** : ~1,5 s (ne plus chercher
  `continue_button_after_combat` 0.58 ni `quit_button` 0.37 sur un écran
  reconnu à 1.00), **un PNG de 1,5 Mo par tentative gagnée** écrit dans
  `screenshots/` pour un écran parfaitement identifié, et un log qui
  dirait ce qu'il voit au lieu de vider dix scores sous « Écran inconnu ».
  Le repère existe déjà : `bilan_victoire` 1.00 **à sa place** et
  `bilan_coeur` 1.00. **NON FAIT** — Ewan a préféré la boutique.
- **ET ÇA CONFIRME UNE DETTE DÉJÀ ÉCRITE** : `bilan.py` affirme en
  commentaire que l'écran de victoire est « sans cœur et sans PV ». Mesuré
  de nouveau ce soir — cœur **1.00**, PV **49/56** — comme sur
  `victoire_defi13_20261106.png`. Sans conséquence (le mot est testé en
  premier), mais rien ne doit être construit dessus.
- **IL Y A BIEN DEUX ÉCRANS DE FIN, ET ILS NE SE RESSEMBLENT PAS** :
  `bilan_victoire_20261105.png` porte le mot mais **ni cœur (0.54) ni
  `continue_button` à cet endroit (0.38)** ; celui de ce soir et celui du
  défi 13 portent les deux à 1.00.

## La session du 20/11 — cinq correctifs vus tourner, et le boss qu'on ne relance pas

25 min (19:28:35 → 19:54:01), lancée **sans `check.py`** (décision d'Ewan
du jour : le diagnostic n'est plus une étape de lancement, c'est un outil
de dépannage). Log : `logs/challenges_20261120_192835.log`.

**5 tentatives : 1 VICTOIRE (palier 46), 1 DÉFAITE (palier 47), 3
inachevées. 3 combats, 3 verdicts** — sixième session d'affilée sans un
seul `gagne: null`. Arrêt propre de lui-même sur le garde `--abandons`.

### CINQ CORRECTIFS SONT ENFIN SORTIS DU « PAS ENCORE VU TOURNER »

Tous mesurés dans le log de la session, pas déduits :

- **Le médaillon du joueur** (08/11) : `0.86, échelle 0.725, en (960, 452)`
  — DEUX lectures, et le nœud retenu l'a été « le plus proche devant
  nous ». Le gabarit découpé à la volée dans le HUD tient en jeu.
- **Le gabarit multi-échelle du boss final** (08/11) : trouvé **trois
  fois**, à (1345, 602), (1200, 394) et (1160, 498) — dont une fois APRÈS
  avoir déjà voyagé jusqu'à lui, l'état que le masque « or des ailes »
  existe pour couvrir.
- **`champions.sur_la_grille`** (09/11) : à 19:37:58 il a reconnu la liste
  des défis, refusé de défiler et rendu la main en **1,3 s**. C'est la
  panne de 75 s du 08/11, éteinte.
- **Les deux coffres** (04-08/11) : ramassés d'affilée, l'un en mise en
  page « coffre_objets_champion », l'autre en « carte du milieu », avec
  la discrimination mesurée — treasure **1.00** contre quit **0.98**.
- **Le palier** : lu **deux fois sur deux** (46 puis 47), cible 6 ★
  honorée les deux fois. Zéro « palier illisible ».

### APRÈS « RELEVEZ-VOUS », ON EST DÉJÀ SUR LE NŒUD DU BOSS

**C'EST LA DETTE N°6 À L'ENVERS.** Elle disait « une aventure perdue au
boss final reste affichée… le parcours cherche des nœuds qui n'existent
plus ». **La carte n'est pas périmée : elle est VIVANTE.** Capture gardée,
`screenshots/noeud_introuvable_20261120_194610.png` — PV **58/58**, **690
PO**, trois nœuds cochés, et le boss final **entouré de son halo bleu,
donc joignable**. « Relevez-vous » avait bien rendu une nouvelle chance.

Ce qui échoue est précis : **on a DÉJÀ voyagé jusqu'au boss avant de le
perdre**, donc le cliquer n'offre pas « Voyage » mais « Combat ».
`goto_node` exige « Voyage » pour conclure qu'on a bougé, ne le trouve
pas, **écarte le nœud**, et `run_adventure` finit sur « boss final
introuvable ». Trois reprises stériles à **3 min chacune**, puis l'arrêt
de session.

- **LE PARCOURS DE REPRISE SAIT POURTANT ARRIVER JUSQU'AU BOSS** : à
  19:47:37 il l'a cliqué, après avoir déclaré « champion de soutien »,
  « nœud 1 » et « nœud 2 » déjà franchis. Le droit de sauter du 05/11
  fonctionne. Il coûte **~2 min** à épuiser des étapes mortes (3 essais
  × 12 s par étape) avant d'atteindre la seule qui compte.
- **ET LE NŒUD ÉCARTÉ EST RECLIQUÉ AU MÊME POINT.** Mesuré trois fois
  d'affilée dans le même tour : `(844, 501)` écarté à 19:50:44, recliqué
  à 19:50:46, écarté de nouveau, recliqué à 19:51:00.
  `NODE_EXCLUDE_DISTANCE` ne mord pas sur le chemin du boss final — le
  seul endroit où `locate_node` est appelé sans passer par
  `pick_next_node`.
- **CE QUE LE MESSAGE D'ARRÊT DIT DÉJÀ, ET QUI EST JUSTE** : « la
  navigation repart du champion de soutien, donc elle ne sait pas
  rattraper une aventure commencée plus loin ». Il nomme la cause ; il
  manque seulement de savoir que « Combat » est une sortie légitime.
- **PRIX MESURÉ** : 3 reprises × 3 min = **9 min**, plus la tentative
  gagnable perdue — le boss était à portée de clic, PV pleins.

### LE JETON D'ATTAQUE N'A JAMAIS ÉTÉ À NOUS — 18 TOURS

Le boss final de la tentative 2 : **308 s, 8 tours comptés, 23 cartes
posées, 0 ATTAQUE**. Le découpage par phase est sans appel :

    combat 1 (ordinaire)        7 ATTACK_TURN / 1 DEFEND_TURN
    combat 2 (boss, tent. 1)    5 ATTACK_TURN / 3 DEFEND_TURN
    combat 3 (boss, tent. 2)    0 ATTACK_TURN / 18 DEFEND_TURN

La détection marche donc dans la même session, sur le même écran, à trois
minutes d'intervalle. **Ce qui rend ce combat-là différent n'est pas
connu**, et les deux hypothèses sont ouvertes : soit ce boss garde le
jeton à chaque round (certains boss PvE le font), soit
`find_attack_token` a lâché sur cet adversaire. **AUCUNE CAPTURE
N'EXISTE** : il n'y a pas eu d'immobilité, donc pas de `bloque_*.png`.
C'est le même manque que « combat sans effet » le 08/11 et que le palier
illisible du 11/11 — **un combat entier sans une seule attaque devrait
laisser une image**.

### `unforeseen_choice_rank` TIRE À PILE OU FACE — TROIS FOIS EN 25 MIN

La dette n°2, désormais la mieux documentée du projet :

    19:32:02  The Darkin Lodestone, 2 options, zone enemy_attack
    19:32:16  The Darkin Lodestone, 2 options, zone enemy_attack
    19:36:10  Kayn,                 2 options, zone attack

Kayn est le cas cher : ses deux formes (Rhaast / Assassin de l'ombre) ne
se valent pas, portent le même nom et les mêmes stats, donc les clés sont
ÉGALES et `max` rend la première de l'ordre de lecture. Après Yuumi
(11/11) et Volibear (14/11), c'est la **quatrième et cinquième**
occurrences datées.

Au passage, la seconde Lodestone a raté ses deux poses (« toujours en
main ») et a été mise de côté — seule entrée du backlog de la session.

### CE QUE LA SESSION N'A PAS COÛTÉ

À inscrire aussi, parce que le projet mesure ses pertes : **zéro blocage
de pile, zéro « Rien ne bouge », zéro carte bannie, zéro palier
illisible, zéro entrée manquée.** L'écran de fin de défi (dette n°13) a
coûté ses ~23 s comme prévu, sans surprise.

## Les mots-clés ACCORDÉS en jeu — `mots_cles_ecran.py` (20/11/2026)

Chantier à quatre tâches, zéro tentative jouée : tout est mesuré sur des
captures du dépôt, rien sur une partie. `keywords.has()` porte depuis le
début ce commentaire : « c'est ici, et ici seulement, qu'on branchera un
jour la lecture des mots-clés ACCORDÉS ». L'API ne rend qu'un CardCode —
un Overwhelm donné par un sort, une Barrier posée ce round, un
Challenger accordé étaient INVISIBLES, comme l'était le Stun avant
`stun.py` : le bot calculait ses échanges, ses blocages et ses attaques
sur la carte IMPRIMÉE.

**LA PREUVE EST MESURÉE, PAS SUPPOSÉE.** Capture appariée à sa trame
d'API, `captures_reference/mots_cles/scene_20261120_201157.png` et son
`.json` — cinq exemplaires de 06SI009 « Pâle orchestre » (Ghastly Band) :
`card_sets` lui donne DEUX mots-clés (Hallowed, Ephemeral) ; l'écran en
affiche QUATRE (Ephemeral, Hallowed, Challenger, Overwhelm).
**Challenger et Overwhelm sont donc ACCORDÉS en jeu**, et ce sont deux
mots-clés MODÉLISÉS : le premier décide si un blocage est légal, le
second change l'excédent d'une attaque — sur ces cinq unités, le bot
décidait comme si elles n'avaient ni l'un ni l'autre. L'ordre de gauche
à droite est un FAIT DE JEU d'Ewan (20/11/2026) : « éphémère,
sanctification, challenger et enfin surpuissance » — la première fois
que l'identité d'une icône vient d'un fait de jeu, pas d'une
ressemblance à l'œil.

**CETTE CAPTURE, ET CELLE DONT DÉPENDAIT DÉJÀ LA SUITE, SONT MAINTENANT
VERSIONNÉES.** `captures_reference/mots_cles/scene_20261120_201157.png`
+ `.json`, et `captures_reference/unite_stun_20261114_231607.png` (sept
unités, celle du 14/11 dont `test_mots_cles_ecran.py` dépendait déjà) :
**avant ce plan, aucune des deux n'était dans git**, et la suite n'était
vraiment verte que sur la machine qui les avait sous la main.

**GÉOMÉTRIE CONFIRMÉE, PAS DEVINÉE.** Rect écran de la première
vignette : x 582-709, y 820-980, centre (645, 900). Icônes à dy
+58..+81, dans la bande que le module mesurait depuis le 14/11,
+38..+82 — les deux tiennent. Pas entre icônes ~24,7 px, glyphes
16-23 × 22-23. Conversion de l'axe Y de l'API vérifiée sur cette trame
appariée : `haut_écran = hauteur − TopLeftY`, déjà verrouillée par
ailleurs par `test_game_state.test_card_model`.

**TROIS FAMILLES DE COULEUR, PAS DEUX.** Teintes mesurées sur les quatre
icônes : **144** (Éphémère, magenta), **95** (Sanctification, cyan),
**16** (Challenger, orange), **19** (Surpuissance, orange). Le masque du
14/11 ne connaissait qu'ORANGE (8-28) et BLEU (88-112) : le sablier
d'Éphémère était dans l'angle mort du masque — une icône VUE à l'œil et
jamais comptée.

**UN GLYPHE FRAGMENTÉ SE RECOLLE, ON NE DESSERRE PAS LE SEUIL.**
Surpuissance sortait en quatre composantes — 22×11 (aire 117) + 9×8
(52) + 4×8 (23) + 16×8 (61) — alors que le glyphe ENTIER fait 22×24.
Deux parades ÉCARTÉES PAR LA MESURE, pas par préférence : la fermeture
morphologique fabrique un faux positif sur Arachnoid Sentry, une carte
VIERGE ; la fusion par colonne SANS garde fait tomber Firespitter à
zéro (une vraie icône fusionnée à tort avec une tache de bordure
voisine). Retenue : fusion par colonne avec REFUS de toute fusion
dépassant `ICONE_COTE_MAX`. Résultat : quatre glyphes entiers (le 4e
enfin à 22×24) et **zéro régression** sur la scène du 14/11 (sept
unités).

**IDENTIFICATION.** Deux variantes par mot-clé (le patron de
`digits.load_variants`, comme `3_defi2.png` le 14/11) ; le score passe
par `digits._normalized` + `_equalize_stroke` + `_iou`, **PAS un IoU
maison** — écart mesuré sur Challenger : 0.807 (IoU simplifié) contre
**0.921** (chemin de `digits`). Seuils **mesurés pour ce problème**, pas
hérités : score ≥ 0.60 (`digits.MIN_SCORE`) ET marge ≥ 0.10
(`digits.CONFIDENT_MARGIN`) — les pictogrammes sont très distincts entre
eux, c'est la MARGE qui discrimine, pas le score brut (`digits.
CONFIDENT_SCORE`, calibré pour dix classes de chiffres voisins, ne vaut
pas ici). Repères : vrais positifs **0.710 à 0.988** (marge 0.119 à
0.630), glyphes étrangers **≤ 0.429** (marge ≤ 0.073). Sur les trois
vignettes NON sources de la scène du 20/11 : pire score **0.714**, pire
marge **0.320** — les deux largement au-dessus des deux planchers.

**VALIDATION CROISÉE INATTENDUE.** Un gabarit découpé sur la capture du
20/11 reconnaît le Challenger IMPRIMÉ d'Enraged Firespitter sur celle du
14/11 — score **0.710**, marge **0.317**. Les gabarits franchissent donc
les captures, pas seulement les vignettes d'une même scène.

**COÛT — ET IL EST LINÉAIRE EN ICÔNES, PAS EN UNITÉS** (remesuré le
20/11 au soir, la première annonce était trompeuse). Le chiffre publié,
**43,1-43,6 ms à chaud / 50,7-52,5 ms à froid**, est celui de la SCÈNE
MESURÉE : `scene_20261120_201157.png`, **5 unités portant CHACUNE
4 icônes — 20 icônes**, c'est-à-dire un plateau entièrement renforcé.
Le ramener à « 8,7 ms par unité » et le multiplier par les 10-12 unités
d'un vrai plateau donnerait ~100 ms (4,7 % d'un instantané) : c'est
faux, parce que le coût ne suit pas les unités. Mesuré, gabarits en
cache, une unité à la fois :

      0 icône   0,10 ms      2 icônes   5,09 ms
      1 icône   2,63 ms      4 icônes   9,35 ms      5 icônes  11,68 ms

soit **~2,3 ms par ICÔNE** plus ~0,1 ms de segmentation par unité. Une
unité sans mot-clé — le cas ordinaire — coûte un dixième de
milliseconde. Les sept unités réelles de la scène du 14/11 (8 icônes en
tout) coûtent **19,7 ms**, soit **0,9 %** de l'instantané ; les 20
icônes du 20/11, **43 ms, 2,0 %** ; un plateau de douze unités portant
quatre mots-clés chacune (48 icônes) coûterait **~110 ms, ~5 %** — un
vrai pire cas, jamais observé. À rapporter à l'étalon du projet :
l'instantané coûte déjà ~2200 ms par itération, dont ~900 ms pour la
seule recherche multi-échelle du jeton d'attaque. Le budget de 50 ms
visait à attraper une surprise d'un ORDRE DE GRANDEUR (500 ms), pas à
bloquer sur 51-57 ms : décision du contrôleur de commiter quand même,
avec l'étalon qui manquait au seuil de 50 ms.

**L'INTERRUPTEUR DE REPLI : `game_state.MOTS_CLES_ECRAN = False`**
(20/11/2026, revue finale). Comme `MARQUEUR_LOSANGE`,
`ATTENTE_ADAPTATIVE`, `CANCEL_WITH_LEFT_CLICK` et `--sans-ocr` avant
lui. Trois des quatre mots-clés branchés ne sont PAS inertes —
Challenger décide de la légalité d'un blocage, Overwhelm change
l'excédent d'une attaque, Ephemeral pilote `dies_anyway` — et rien de
tout ça n'a jamais tourné en jeu. À False, `lire_les_mots_cles` rend 0
sans rien lire et tout le plateau retombe sur les mots-clés IMPRIMÉS,
le comportement d'avant le 20/11, sans éditer une fonction en pleine
session. Verrouillé par `test_game_state.
test_la_lecture_decran_est_vraiment_branchee`, qui vérifie les deux
sens : branché, l'écran est interrogé sous l'unité du banc et le
mot-clé lu ressort de `snapshot()` ; coupé, l'écran n'est pas lu du
tout.

**ET LA LECTURE PARLE** : chaque mot-clé lu est journalisé **une fois
par (CardID, mot-clé)** — le modèle de `CombatLoop._note_level_ups` —
en distinguant « porte bien son X imprimé » de « a reçu X (absent de
card_sets) ». Sans ça la branche entière aurait été MUETTE : bande
décalée, seuils qui ne mordent plus, `mots_cles/` vidé, et le bot
retombait sur son comportement d'avant sans un mot — avec, en prime,
l'impossibilité de lever la dette « pas encore vu tourner en jeu »,
puisqu'il n'y aurait rien eu à relire dans `logs/`.

**PRIX ASSUMÉ, NOIR SUR BLANC.** On ne voit PAS les mots-clés RETIRÉS
(un Silence, par exemple) : l'écran COMPLÈTE la carte imprimée et ne
retire JAMAIS rien — décision d'Ewan. `keywords_lus` vide veut dire « on
n'a pas regardé », pas « elle n'a rien », même règle que `stunned`. Les
icônes qui se TOUCHENT ne sont toujours pas séparées (compte à ±1,
mesuré le 14/11) : ces glyphes-là ne sont jamais identifiés, et c'est
voulu plutôt que deviné. La MAIN n'a pas cette barre — elle n'existe que
sur les unités DU PLATEAU. Et **seize des vingt mots-clés modélisés**
n'ont encore aucun gabarit : quatre seulement (Ephemeral, Hallowed,
Challenger, Overwhelm) sont récoltés, chacun des seize autres demandant
une capture étiquetée par Ewan — « de gauche à droite : … » suffit,
comme pour celle-ci.

**ON PEUT ENFIN INTERROGER UNE CAPTURE** (20/11, revue finale).
`champions.py <capture>`, `bilan.py <capture>` et `spells.py explain`
ont tous leur point d'entrée ; celui-ci n'en avait aucun, et
`cut_icone` — le SEUL outil de récolte de gabarits, donc le chemin
obligé des seize mots-clés manquants — n'était atteignable que par
`python -c` :

    python mots_cles_ecran.py                       écran en direct
    python mots_cles_ecran.py <capture.png>         + sa trame .json appariée
    python mots_cles_ecran.py <capture.png> <x> <y> un centre à la main
    python mots_cles_ecran.py cut-icone <capture.png> <x> <y> <index> <nom>

Il imprime, par unité, le nombre d'icônes, la boîte de chacune AVEC SON
INDEX (c'est lui que `cut-icone` demande) et ce qui est identifié. Une
capture sans trame appariée n'est pas devinée : on demande un centre.

**CE QUI RESTE OUVERT, ET QU'ON NE FAIT PAS MAINTENANT.** Trois pistes
sorties de la revue finale ; aucune n'est un correctif, toutes sont des
changements de CONCEPTION qu'il faudrait mesurer d'abord.
  - **Compter les icônes NON reconnues.** `identifier()` rend ce qu'il
    sait nommer et laisse tomber le reste en silence. S'il rendait
    aussi le nombre de glyphes refusés, on classerait tout seuls les
    seize gabarits manquants par FRÉQUENCE RÉELLE en partie — la
    méthode de `journal.py --ecartees`, qui a déjà servi à savoir quelle
    carte coder en premier. C'est la piste la plus rentable des trois.
  - **Reconstruire le glyphe depuis la carte des labels** au lieu de
    trancher le masque partagé. Le masque tranché contient les pixels
    des VOISINS tombés dans la même boîte : c'est probablement pourquoi
    le pire vrai positif mesuré (**0.710**, la validation croisée sur
    Firespitter, collée à une tache de bordure 40×30) est aussi le plus
    proche du plancher. `connectedComponentsWithStats` rend déjà la
    carte des labels, elle est jetée.
  - **Un pré-tri par famille de couleur.** `identifier` compare chaque
    glyphe à TOUS les gabarits, et la part IoU est linéaire en nombre de
    mots-clés : mesuré en dupliquant les gabarits, **46,6 ms à 4
    mots-clés contre 239,7 ms à 20** sur la même scène — **×5,1**, très
    exactement le facteur annoncé. Le jour où les vingt seront récoltés,
    ce n'est plus 2 % d'un instantané mais 10 %. Les teintes sont déjà
    séparées (ORANGE / BLEU / MAGENTA) : un glyphe magenta n'a rien à
    comparer à un gabarit orange.

**PAS ENCORE VU TOURNER EN JEU** : tout est mesuré sur des captures,
jamais exercé dans une partie. Tests :
`test_mots_cles_ecran.test_le_sablier_magenta_entre_dans_le_masque`,
`test_un_glyphe_fragmente_se_recolle_entier`,
`test_les_quatre_icones_sont_identifiees`,
`test_une_unite_sans_icone_nidentifie_rien`,
`test_un_glyphe_etranger_nest_identifie_comme_rien`,
`test_un_gabarit_franchit_les_captures`,
`test_le_decoupage_suit_le_chemin_de_lecture`,
`test_game_state.test_un_mot_cle_lu_a_lecran_complete_la_carte_imprimee`,
`test_un_mot_cle_lu_ne_retire_jamais_un_imprime`,
`test_la_lecture_decran_est_vraiment_branchee`.

### Le lexique des icônes — étiqueté par Ewan les 20 et 21/11/2026

**LA VÉRITÉ TERRAIN EST UNE POSITION, PAS UNE DESCRIPTION.** Premier
réflexe : décrire les icônes (« épée dorée », « tour dorée ») et les
apparier d'une carte à l'autre. **Ça s'est trompé deux fois en dix
minutes** — la tour notée « Robuste » était Immortalité, et l'« épée
dorée » du Viktor, prise pour la même que celle de Kennen, est Impact
quand celle de Kennen est Frappe rapide. Deux épées, deux mots-clés.
C'est exactement pourquoi la reconnaissance se fait au PIXEL et non à la
description : **le seul fait exploitable est le triplet (capture, carte,
position), et il vient d'Ewan.** Un gabarit se découpe à une position
nommée, jamais à une ressemblance.

Captures appariées à leur trame d'API :
`captures_reference/mots_cles/kennen_20261121_034644.png` et
`victor_20261121_035752.png` (+ leurs `.json`).

**Kennen (05BC058), 6 icônes** — imprimé : `Quick Attack` seul.

| # | mot-clé | modélisé ? |
| --- | --- | --- |
| 1 | *niveau du champion* | PAS un mot-clé |
| 2 | Frappe rapide | oui — `QuickStrike` |
| 3 | Insaisissable | oui — `Elusive` |
| 4 | Bouclier antisorts | non — `SpellShield`, connu de `riposte.py` seulement |
| 5 | Régénération | non — « volontairement non modélisé » |
| 6 | Augmentation | non — `Augment` |

**Viktor n°1 (03PZ003, banc), 7 icônes** — imprimé : `Augment` seul.

| # | mot-clé | modélisé ? |
| --- | --- | --- |
| 1 | *niveau du champion* | PAS un mot-clé |
| 2 | *effet de zone* (`AuraVisualFakeKeyword`) | PAS un mot-clé |
| 3 | **à confirmer** — « tu connais » | ? |
| 4 | Immortalité | oui — `Deathless` (confirmé par Ewan) |
| 5 | Impact | oui — `Impact` |
| 6 | Volonté | non — `Spirit` (12 cartes) |
| 7 | **à confirmer** — « tu connais » | ? |

**Viktor n°2 (03PZ003, banc), 7 icônes** — identique au n°1 sauf les
positions 5 et 6.

| # | mot-clé | modélisé ? |
| --- | --- | --- |
| 5 | Fureur | non — `Fury` |
| 6 | Redoutable | oui — `Fearsome` |

**CE QUI RESTE À NOMMER** : les positions **3 et 7 des deux Viktor**.
Ewan les a dites « tu connais », donc elles sont parmi les cinq de
Kennen — mais après la méprise sur les deux épées, **les déduire de leur
apparence serait refaire l'erreur**. À demander.

**CINQ MOTS-CLÉS MODÉLISÉS SONT DÉJÀ NOMMÉS** et donc récoltables :
`QuickStrike`, `Elusive`, `Deathless`, `Impact`, `Fearsome`. Chacun
change un calcul que le bot sait déjà faire.

**LA BASE NOMME ELLE-MÊME LE FAUX MOT-CLÉ.** L'« effet de zone » est
`AuraVisualFakeKeyword`, porté par **48 cartes**, avec `LandmarkVisualOnly`
sur **133** autres : Riot les déclare comme des mots-clés d'AFFICHAGE.
L'exclusion s'appuiera donc sur la donnée, pas sur une liste devinée —
même principe que « on compte les marqueurs, on ne reconnaît pas des
sorts ».

**ZÉRO FAUX POSITIF, VÉRIFIÉ SUR CE PLATEAU.** Face aux onze types de
glyphes ci-dessus, dont AUCUN n'a de gabarit, `identifier` rend `?` à
chaque fois. La promesse « jamais une valeur approchée » tient sur un
plateau réel, et pas seulement sur la scène témoin.

### TROIS DÉFAUTS MESURÉS LE 21/11, et le troisième aveugle le bot

**1. CÔTÉ ADVERSE, LA BARRE EST EN HAUT DE LA CARTE.** Les statistiques
et la barre de mots-clés sont INVERSÉES chez l'adversaire. `ZONES_DE_
PLATEAU` contient bien `enemy_board` et `enemy_attack`, mais
`lire_les_mots_cles` y lit la bande `dy +38..+82` — c'est-à-dire la zone
des statistiques. Mesuré : en bande MIROIR (`dy -87..-49`), l'unité
`02BW032T1` rend **deux composantes de 19×23 et 18×25 px**, exactement
la taille d'un glyphe, là où la bande actuelle en rend **zéro**.
**LA PREUVE LA PLUS NETTE** : `02BW032T1` « Powder Keg » IMPRIME
`Immobile` et `Vulnerable` — deux mots-clés MODÉLISÉS, et deux qui
décident d'un blocage. Le module rapporte 0 icône sur une carte qui en a
forcément. **Le côté adverse est entièrement aveugle**, et c'est celui où
Provocateur, Insaisissable et Redoutable comptent le plus.

**2. L'INDICATEUR DE NIVEAU EST COMPTÉ COMME UN GLYPHE.** Il occupe la
première place de la barre et n'est pas un mot-clé (fait de jeu d'Ewan).
Conséquence : `a_recu_un_mot_cle` déclarerait « cette carte a reçu un
mot-clé » pour **tout champion monté de niveau sans mot-clé imprimé** —
un faux positif sur la seule promesse que cette fonction porte. Sans
appelant aujourd'hui, donc sans coût en jeu ; à corriger avant qu'elle en
ait un.

**3. LA BARRE DÉBORDE, ET LES ICÔNES SE METTENT EN QUINCONCE.** Mesuré
sur Kennen : barre noire à `dy +49..+87` contre une bande lue `+38..+82`
— **5 px coupés par le bas**. Et au-delà de quatre mots-clés, le jeu
TASSE les icônes sur DEUX NIVEAUX au lieu d'une ligne : ce que les
scènes du 14/11 (≤ 5 icônes alignées) et du 20/11 (4 alignées) ne
pouvaient pas révéler. Résultat mesuré : **5 boîtes pour 7 icônes, 4
pour 6, 4 pour 7** — une sur deux est perdue ou fragmentée.

**RIEN DE TOUT ÇA N'EST CORRIGÉ** (21/11). Les captures et le lexique
sont là ; les gabarits des neuf mots-clés nommés ne sont PAS récoltés,
parce que segmenter avant de corriger graverait des gabarits faux.

## Journal des sessions

Une ligne par session jouée, pour remplacer les bilans « ce qui a tourné »
qui gonflaient le fichier. Le détail d'un correctif se lit dans sa section ;
ce tableau ne sert qu'à situer une date et à voir la tendance.

| date | tentatives | combats / verdits | ce qu'on en a tiré |
| --- | --- | --- | --- |
| 05/11 | 1 V (défi 2, Teemo 7 ★) | — | PREMIÈRE VICTOIRE du bot ; la grille est triée du plus FAIBLE au plus fort |
| 06/11 | 8 : 1 V, 4 D, 3 inach. | — | première victoire sur un BOSS FINAL, écrite `gagne: null` ; récompense et nœud à options |
| 08/11 | 3 aventures perdues | — | molette sans focus, marqueur du joueur faux, coffre enfin ramassé |
| 09/11 | 1 V (défi 23) | — | les neuf correctifs de la nuit tournent ; 6 ★ brûlé faute du « 3 » |
| 10/11 soir | 2 achevées, 1 V (défi 24) | 6 / 6 | six chantiers ; entrée en 25 s |
| 11/11 | 1 D au boss final | 4 / 4 | Yuumi et Beast's Frenzy mangent la tentative ; 7 ★ brûlé |
| 14/11 | 5 : 1 V, 1 D, 3 inach. | 4 / 4 | le 8 récolté ; « marked » refusé sans un seul blocage |
| 14/11 soir | 1 inachevée | 1 / 1 | le palier se lit (3_defi2, 6_defi2) ; Wild Card repérée |
| 15/11 | 3 V sur 3 (39 → 42) | 4 / 4 | le Joker compris ; 0 et 3 relus dans un vrai titre |
| 16/11 | 2 V sur 2 (43 → 45) | 3 / 3 | la boutique quittée avec 840 PO |
| 20/11 | 5 : 1 V, 1 D, 3 inach. (46 → 47) | 3 / 3 | cinq correctifs vus tourner ; le boss final qu'on ne sait pas relancer |

## Ce qui reste ouvert — liste UNIQUE, refaite le 16/11/2026

**Les listes qu'elle remplace se contredisaient entre elles**, et le
fichier le disait déjà de lui-même : « une carte des dettes qu'il faut
relire jusqu'en bas pour savoir qu'elle ment n'est pas une carte ». Il n'y
en a plus qu'une.

**Provenance** : les points 1 à 12 sont REPORTÉS des listes du 10 au 15/11
sans être revérifiés un par un ce soir ; seuls les points marqués
« (16/11) » ont été mesurés aujourd'hui. Avant d'attaquer l'un d'eux,
**le revérifier** — c'est la leçon du 10/11, où neuf dettes sur treize
étaient déjà réparées.

1. **LA BOUTIQUE (16/11)** — nœud quitté, 840 PO dormants, cartes à 45-60
   PO, à chaque aventure. C'est le gain le plus gros de la liste, et c'est
   le prochain chantier décidé par Ewan.
2. **`unforeseen_choice_rank` TIRE À PILE OU FACE** entre options à clés
   égales — **trois occurrences datées** : Yuumi (11/11, deux versions à
   mêmes coût/stats/nom, celle qui réclame une cible gagne), Volibear
   (14/11, trois « Relentless Storm » identiques, champion à 9 mana perdu
   un tour), et c'est aussi ce qui rendait le choix du Joker arbitraire.
   Le versant `card_pick_rank` est réglé (Destiny Cards, 15/11) ; celui
   des fenêtres de VERSIONS ne l'est pas, et il est plus dur : seul le
   TEXTE des options diffère. **Choisir la version qui ne réclame rien
   quand le banc est vide est une décision de jeu — elle doit venir
   d'Ewan.**
3. **Les quatre bloqueurs de sorts du relevé**, chacun indépendant :
   Calibrum (fenêtre de VERSIONS non déclarée dans `CARD_WINDOWS`),
   Quicken (« with 3 or less Power » — condition CHIFFRÉE sur la
   puissance vivante), Stress Defense (`choose_target` rend `None` et le
   sort part quand même : `sort_sans_cible` devrait l'attraper), et
   `frostbite` non modélisé — famille de **131 cartes** classées `AUTRE`
   avec un clic à faire, dont une seule changerait de camp.
4. **Le blocage de 51 s du 11/11 à 13:32:46 n'est pas Yuumi** — c'est une
   Patient Beast posée sur The Leviathan, banc NON vide, `orbe=oui`. Cause
   distincte, jamais diagnostiquée. Il laissera désormais une capture
   utilisable.
5. **Le faux positif du bouton boussole** : les gabarits de nœud matchent
   le bouton boussole (0.85 en (1819, 470)) et la flèche retour
   (0.81-0.83). Deuxième occurrence datée le 14/11 — `normal_node` **0.80
   en (1821, 45)**, clic, « Voyage » introuvable, **13 s**.
6. **LE BOSS FINAL QU'ON NE SAIT PAS RELANCER (20/11, 9 min et une
   tentative gagnable)** — c'est l'ancienne « boucle de reprise stérile »
   du 14/11, **diagnostiquée et retournée** : la carte n'est PAS périmée.
   Capture `screenshots/noeud_introuvable_20261120_194610.png` : PV
   58/58, 690 PO, boss final auréolé de bleu, donc joignable. **On a déjà
   voyagé jusqu'à lui avant de le perdre, donc le cliquer offre
   « Combat », pas « Voyage »** — `goto_node` exige « Voyage », écarte le
   nœud, et `run_adventure` conclut « boss final introuvable ».
   Sous-défaut mesuré trois fois le 20/11 : **le nœud écarté est
   recliqué au même point** `(844, 501)`, `NODE_EXCLUDE_DISTANCE` ne
   mordant pas sur ce chemin. Et le parcours de reprise **sait** arriver
   jusqu'au boss (19:47:37), au prix de ~2 min d'étapes mortes. C'est le
   gain le plus gros de la liste après la boutique.
7. **Un combat sans une seule attaque ne laisse aucune image** (20/11) :
   18 tours DEFEND_TURN d'affilée au boss final, **0 attaque**, alors que
   les deux combats précédents de la même session donnaient 7 et 5
   ATTACK_TURN. Jeton gardé par le boss, ou `find_attack_token` qui
   lâche ? **Indécidable sans capture**, et il n'y en a pas : pas
   d'immobilité, donc pas de `bloque_*.png`. Même manque que « combat
   sans effet » (08/11) et le palier illisible (11/11).
8. **Deux chemins de `dry_run` décident sans les PV du nexus** —
   `actions.py` `cmd_plan` et `cmd_block`. Zéro seconde de jeu, mais c'est
   la première commande de diagnostic du projet, et laisser deux appels
   diverger recrée le défaut payé deux fois (`_describe`, `etat_des_sorts`).
9. **`choose_target` juge toutes les cibles d'un sort dégressif avec le
   même montant** : Trueshot Barrage évalue ses 2e et 3e cibles à 3 dégâts
   alors qu'elles en prennent 2 et 1.
10. **`check.py` et `replay.py` gardent chacun leur copie de la parade
    UTF-8** au lieu d'appeler `sortie_utf8.appliquer()`. `game_state.py` et
    `combat.py` sont migrés et testés.
11. **Trois petites dettes de diagnostic** : `journal.is_context_reason`
    range « pouvoir à cibler : aucun allié » et « équipement : aucun allié
    en jeu » dans le backlog alors que ce sont des contextes de partie ;
    **`spells.py coverage` ne regarde que les COLLECTIONNABLES**, donc ne
    peut pas voir les cartes d'aventure — c'est la boussole du backlog, et
    elle a un angle mort ; et le journal **compte 2 combats pour une
    tentative qui en a joué 3** (le troisième après un « Relevez-vous »).
12. **Deux défauts anciens jamais touchés** : Ebb and Flow est classée
    `DAMAGE sur allié` (`effect_clause` ne coupe pas sur les « and »), et
    Ace in the Hole est refusée en mode PRUDENT pour « combat dirigé, deux
    cibles » parce que `\bstrikes?\b` matche « Critical **Strike** ».
    Et **le défi refusé par le client** (« The Taker est engagée mais
    Legion Grenadier n'a pas été tirée »), connu depuis le 06/11.
13. **L'ÉCRAN DE FIN DE DÉFI (16/11)** — ~1,5 s et un PNG de 1,5 Mo par
    tentative gagnée. Petit, sûr, mesuré ; voir sa section.
14. **Le prochain gisement de TEMPS est la LECTURE, pas l'attente** :
    2,2 s par itération, dont ~0,9 s par `snapshot()` à cause de la
    recherche multi-échelle du jeton d'attaque.
15. **Le ménage de `screenshots/`** (0,98 Go, dont 94 % de captures
    produites par les tests avant le bouchon du 09/11).

### Deux faits de jeu en attente d'Ewan

- **Une capture d'un bilan au nexus PLEIN.** C'est la seule image qui
  réconcilierait le fait d'Ewan (« les PV de notre nexus sont crème ») et
  la mesure (le courant sort en orange sur les deux captures chiffrées).
  Tant qu'on ne l'a pas, **ne pas « réparer » l'un au nom de l'autre**.
- **Le nœud suivant : « le plus proche à DROITE » ou « le plus proche tout
  court » ?** Avec la vraie position (médaillon), la règle du 02/09 devient
  stricte, et sur 53 décisions rejouées « le plus proche » gagne 49-47.

## Jamais vu tourner en jeu — refait le 16/11/2026

Ce que le code sait faire, que les tests verrouillent, et que personne n'a
encore vu s'exécuter dans une partie. **C'est la dette qui prime** : un
correctif non observé est une hypothèse.

- **Les décisions liées à l'ÉPHÉMÈRE** — aucune occurrence dans tout
  `logs/` ; c'est la dernière zone de décision du combat jamais vue.
- **Le chantier du CAMP du clic** (59 plans, 22 cartes, 06/11) : aucune des
  22 cartes concernées n'a été lancée depuis.
- **« An attacking enemy »** (5 cartes) : Steel Tempest n'apparaît qu'en
  main, jamais lancée.
- **« An enemy or the enemy Nexus »** (08/11) : Statikk Shock, Shock Blast
  et Divine Draft jamais en main depuis.
- **« If there are no enemies » et « or your Nexus »** (10/11).
- **Vladimir et « any number of »** — le bouton bleu ÉTAIT l'orbe de tour,
  déjà cliquée par le code. Reste à voir tourner, et à trancher l'ordre des
  deux gestes.
- **Les cartes `99xx`**, dont **`99SH003 Clever Camouflage`** : son texte
  vient du wiki, c'est une PARAPHRASE. Si le bot clique à côté, c'est là
  que ça se verra.
- **Beckoning Gaze.**
- **« TO PLAY, DISCARD 1 »** (14/11) : le PLAN a tourné le 15/11 — ciblage
  annoncé « puis nexus adverse », le cas exact d'Ewan — mais **le GESTE
  non**, la désignation en main ayant échoué avant sur le défaut de la
  jumelle. Le correctif du 15/11 devrait le débloquer.
- **Les trois correctifs du 15/11** — « une fenêtre prise fait avancer la
  résolution » (le Joker), « une jumelle en main n'est pas la carte visée »,
  et « la Destiny Card se choisit sur le plateau ». **Non exercés le
  16/11** : vérifié, zéro Wild Card et zéro blocage de pile dans le log du
  jour, le deck n'en contenait pas.
- **La lecture des mots-clés ACCORDÉS en jeu** (`mots_cles_ecran.py`,
  20/11) : mesurée sur deux captures du dépôt, jamais exercée pendant un
  combat. Reste à voir si `keywords.has()` reçoit vraiment un Challenger
  ou un Overwhelm accordé pendant une session jouée.
