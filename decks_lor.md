# Les decks du défi hebdomadaire et leur plan de jeu

Analyse du 06/09/2026, à partir des decklists lues par l'API
(`/static-decklist`) dans les trois traces du jour
(`python strategy.py --traces` régénère le tableau). Le bot choisit le
**premier champion de la liste** (`navigate._pick_champion`) : le deck
change donc d'une tentative à l'autre selon l'ordre que le jeu donne à
la liste, et il change *en cours d'aventure* quand un nœud d'événement
ajoute des cartes (Norra, Morgana + Lisa and Dolly, Ziggs ont été ajoutés
ainsi). Le journal ne disait pas quel deck avait joué : il le dit
maintenant (`config.archetype`, `config.champions`).

## Les trois decks vus

### Nilah / Jarvan IV (Bilgewater–Demacia) — *tirage et duels*

The List, Hired Gun, Pool Shark, Pick a Card, Tidal Invocation, Slotbot,
Cataclysm, Vikrash, Gallant Rider, Buhru Lookout, Nilah, Jarvan IV.

Plan de jeu : rendre l'adversaire **Vulnerable** (Hired Gun, The List) puis
le **tirer** en duel avec une grosse unité (Cataclysm, Gallant Rider qui
devient Vanguard Cavalry au premier défi, Jarvan qui s'invoque en
défiant au moment de l'attaque). Nilah et Vikrash piochent des Slipstream
(sorts de rafale) qui nourrissent Slotbot. Le deck **gagne en attaquant
chaque round** : Nilah (« Attack: ») et Jarvan (« When you attack ») ne
font rien si on n'attaque pas. Coût moyen des unités 3,2.

Ce que le bot faisait mal : garder le banc « en défense » (bilan à 0 ou
rien) alors que la valeur du deck est dans l'attaque déclarée ; les duels
dirigés ne sont pilotés que depuis le 06/09 (chantier 4).

Archétype détecté : **tirage** (8 votes : 4 Vulnerable accordés, 4 duels
dirigés).

### Nidalee / Nasus (Shurima) — *transformation et Vulnerable*

Bristlehog, Bushwhack Trap, All-Terrain Trooper, Weight of Judgment,
Merciless Hunter, Desert Duel, Aurora Hallunatis, Baccai Sandspinner,
Nidalee, Vekauran Bruiser, Nasus, Towering Pairofant.

Plan de jeu : les unités **Ambush** peuvent être posées cachées (Shadow in
the Brush) puis révélées par le sort Ambush — c'est une **transformation**,
qui déclenche Bristlehog (+2|+1), Bushwhack Trap (Vulnerable au plus
faible), Aurora (copie). Merciless Hunter, Baccai et la Trap rendent
l'ennemi Vulnerable pour que Pairofant (Overwhelm), Nidalee (Quick
Attack) ou Nasus le tuent en duel. Nasus grossit à chaque unité tuée.
Deck **midrange lourd** (coût moyen 3,8) qui veut *tuer des unités* avant
de frapper le nexus.

Ce que le bot faisait mal : il refuse les fenêtres « Play me as » hors de
portée, donc les Ambush sont toujours posées à découvert — pas de
transformation, Bristlehog et la Trap ne servent à rien (la Trap était de
plus écartée pour « coût > mana » alors qu'elle coûte 2 — à vérifier). Le
plan « rendre Vulnerable puis tirer » n'est chiffré que si l'unité a déjà
Vulnerable au moment de l'attaque ; le bot ne pose pas Merciless Hunter
*pour* l'attaque qui suit.

Archétype détecté : **tirage** (10 votes) ; **midrange** avec Norra (les
portails ajoutent des effets au nexus qui font monter le score aggro).

### Bard / Lucian (Bandle City–Demacia) puis Bard / Ziggs — *agressif à carillons*

Radiant Strike, Lucian, Byrd, Stone Stackers, Bandle Commando, Esmus,
Senna, Banana Blaster, Bard, Cosmic Binding, Minimorph, + une carte PoC
(99MT003, inconnue de card_sets).

Plan de jeu : **courbe basse** (coût moyen 2,4), Quick Attack (Lucian),
Nexus Strike (Bandle Commando), et les **Chimes** de Bard/Byrd/Esmus qui
grossissent les cartes piochées. Le deck veut attaquer *tous les rounds*
avec le jeton : Bard (« Attack: Plant 3 Chimes »), Ziggs (« Attack: 1 au
bloqueur et au nexus »). Cosmic Binding et Minimorph enlèvent le bloqueur
gênant. Contre l'IA, c'est le deck le plus simple à gagner : elle bloque
mal les petites unités et ne fait pas pression.

Ce que le bot faisait mal : deux bugs de 25 minutes (Banana Blaster,
Minimorph — corrigés le 06/09) ; et « aucune attaque rentable » face à des
bloqueurs plus gros alors que le deck n'a pas d'autre plan que la
pression.

Archétype détecté : **aggro** (16 votes avec Lucian, 14 avec Ziggs).

## Pourquoi le bot perdait (journal du 06/09 : 7 combats, 0 victoire)

1. **Un seul plan de jeu pour tous les decks** — bilan d'attaque ≥ 0
   exigé, un dégât au nexus = un point de plateau (1,33 à 30 PV). Le bot
   optimise son plateau pendant que le boss, avec son pouvoir passif,
   remplit le sien : à la 3e attaque il y a 6 unités en face et plus rien
   ne passe. Contre l'IA, la partie se gagne *tôt*.
2. **Les déclencheurs « Attack: » ne valaient rien** — Nilah, Bard, Ziggs,
   Jarvan sont des champions dont tout l'effet part à l'attaque déclarée.
3. **Mulligan uniforme (coût > 3 rejeté)** — juste pour un deck à courbe
   basse, trop sévère pour un deck de contrôle qui veut son 4.

## Ce qui a été fait (strategy.py)

Un module **`strategy.py`** lit la decklist et la base de cartes, compte
des signaux (déclencheurs « Attack: », effets au nexus, Overwhelm /
Elusive / Quick Attack / Fearsome, Challenger, Vulnerable accordés, duels
dirigés, sorts de retrait, courbe) et choisit un archétype :

| Archétype | 1 dégât au nexus (à pleine santé) | Plancher d'attaque | Bonus « Attack: » | Mulligan |
| --- | --- | --- | --- | --- |
| `defaut` (pas de decklist) | 1,0 | 0 | 0 | coût > 3 |
| `aggro` | 2,0 | −1 (si des dégâts passent) | +1 par déclencheur | coût > 2 |
| `tirage` | 1,2 | 0 | +1 | coût > 3 |
| `midrange` | 1,5 | 0 | +1 | coût > 3 |
| `controle` | 1,0 | 0 | +0,5 | coût > 4 |

`CombatLoop._note_deck` fixe `actions.STRATEGY` dès que la decklist est
lisible et journalise `archetype` + `champions` : **`python journal.py`
donnera le taux de victoire par archétype**, ce qui permettra de régler
ces nombres sur des parties réelles plutôt qu'au doigt mouillé. Sans
decklist, rien ne change (tous les tests existants passent tels quels).

## Ce qui reste à faire, par ordre d'impact

- **Poser les Ambush cachées** (fenêtre « Play me as Shadow in the Brush »)
  et lancer le sort Ambush : c'est tout le deck Nidalee. Hors de portée
  aujourd'hui (fenêtre de versions refusée).
- **Jouer *pour* l'attaque** : poser Merciless Hunter / Hired Gun avant de
  déclarer, quand on a le jeton, plutôt que par coût décroissant.
- **Modéliser l'IA** : `predict_enemy_blocks` prête à l'adversaire notre
  propre logique. L'IA de PoC bloque surtout quand elle tue, et laisse
  passer les petites unités — un modèle plus proche ferait attaquer plus.
- **Choisir le champion** : `_pick_champion` clique le premier de la
  liste. Quand le journal aura quelques dizaines de parties par
  archétype, cliquer le champion du meilleur archétype (Bard / Ziggs
  d'après cette analyse) sera le levier le plus simple — Ewan a demandé
  d'apprendre à jouer *tous* les decks, donc c'est un réglage à discuter,
  pas une décision prise ici.
