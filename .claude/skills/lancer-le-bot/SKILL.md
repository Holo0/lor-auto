---
name: lancer-le-bot
description: Lancer le bot LoR sur les défis hebdomadaires et le surveiller en direct. À utiliser quand Ewan dit « lance le bot », « fais le maximum de défis », « surveille-le », « lance l'œil », ou demande de noter ce qu'il faut améliorer pendant qu'il joue.
---

# Lancer le bot et le surveiller

Procédure complète. **Un seul interpréteur : `.\.venv\Scripts\python.exe`**
(le dossier `venv` 3.11 est un vestige incomplet — ne jamais l'utiliser).

## 1. Avant de lancer — PAS de diagnostic

**On ne lance plus `check.py` au démarrage d'une session** (décision d'Ewan,
20/11/2026) : c'est trois minutes de tests avant le premier clic, et la
session est précisément le moment où on veut jouer. Il reste l'outil de
DÉPANNAGE, à lancer quand quelque chose cloche :

- **« il ne clique sur rien »** → ligne « base de cartes » (> 1000 cartes).
  Son absence est SILENCIEUSE : sans descriptions, `classify_card` rend
  `Targeting.NONE`. Remplissage :
  `.\.venv\Scripts\python.exe LoR-Bot/code/download_card_sets.py`.
- **« NO_API » alors que le jeu tourne** → **le port n'est PAS fixe**. 21337
  est celui que le client prend *quand il est libre* ; `lor_api.find_api_base`
  sonde 21337-21347. Regarder le port AVANT de lire le code.
- **« écran inconnu » dès l'entrée** → « fenêtre du jeu » doit être trouvée.

`check.py --offline` ne valide que la logique (à faire avant/après un
changement de code, pas avant une session) ; `--live` que le diagnostic.

## 2. Le jeu doit être DEVANT et non couvert

Le bot photographie le **bureau**, pas la fenêtre du jeu. Une fenêtre
d'éditeur par-dessus = meilleur gabarit à 0.51, « écran inconnu », tentative
perdue (mesuré le 09/11/2026). `challenges._mettre_le_jeu_devant` le remet
devant à chaque tentative, mais **la dégradation est douce** : si Windows
refuse la bascule, le bot lit l'écran tel quel. Donc prévenir Ewan de ne rien
poser devant le jeu, et **n'ouvrir aucune fenêtre par-dessus pendant la
session** (navigateur et éditeur sur le second écran).

## 3. Lancer le bot (en arrière-plan)

```powershell
.\.venv\Scripts\python.exe challenges.py
```

Options réelles de `challenges.py` : `--tentatives N` (par défaut : jusqu'à
ce que le jeu n'en donne plus), `--duree`, `--abandons`, `--speed`
(2 = défaut), `--duree-combat`, `--record`, `--sans-ocr`, `--plan` (ne
clique rien), `--chump`, `--mulligan`, `--spells`. **Il n'y a pas de
`--prudent` ici** (il est dans `combat.py` et `actions.py`).

Lancer avec `run_in_background`. Le log est écrit par `logfile.setup` dans
`logs/challenges_AAAAMMJJ_HHMMSS.log`, et son chemin est la **première
ligne** imprimée (« Journal de ce lancement : … ») — le relever tout de suite.

## 4. Lancer l'œil

```powershell
.\.venv\Scripts\python.exe monitor_web.py --interval 2 --sans-ocr
```

En arrière-plan, sur http://127.0.0.1:8765/. Options réelles : `--host`,
`--port`, `--interval`, `--width`, `--sans-ocr` (ne charge jamais torch).
**Il ne fait AUCUN geste et n'enregistre rien.** Il montre la capture avec les
rectangles de l'API, `summary()`, la fin du log et le journal (`/state.json`,
`/screen.jpg`, `/plan.txt`, `/why.txt`). Claude in Chrome peut l'ouvrir sur le
second écran — mais **le suivi principal se fait en lisant le log**.

## 5. Surveiller

```powershell
Get-Content -Wait -Tail 40 logs\challenges_<date>.log
```

Motifs à guetter : `[WARNING]`, « bloqué » / « Rien ne bouge depuis »,
« toujours sur la pile après validation », « écran inconnu », « introuvable »,
« illisible », « inachevée », « entrée manquée », et tout combat qui finit
en `gagne: null`.

**La capture est le premier livrable d'un blocage — on la REGARDE avant de
lire le code** : `screenshots/bloque_<PHASE>_<date>.png` (posée par
`combat.save_stuck_screen`) et `screenshots/pile_bloquee_<carte>_<date>.png`
(posée par `actions.journaliser_pile_bloquee`).

## 6. Ne pas interrompre pour rien

- **Arrêt d'urgence : amener la souris dans un coin de l'écran** (fail-safe
  pyautogui).
- **Ne pas bouger la souris pendant que le bot joue** : un bouton sous le
  curseur n'est pas reconnu, et le survol abîme la vignette qu'il lit.
- Une défaite n'arrête rien. Laisser la session aller au bout.

## 7. Après la session

```powershell
.\.venv\Scripts\python.exe journal.py              # 30 derniers jours par défaut
.\.venv\Scripts\python.exe journal.py --ecartees   # le backlog des cartes écartées
.\.venv\Scripts\python.exe journal.py --champions  # taux par (palier, étoiles)
```

(`--depuis AAAA-MM-JJ` / `--depuis tout` / `--jours N` / `--last N` : la
fenêtre vaut pour les trois vues.)

Puis **écrire ce qu'on a observé dans `CLAUDE.md`**, en nommant ce qui a été
**VU TOURNER EN JEU** : le projet distingue explicitement *mesuré* de
*supposé*, et beaucoup de sections portent « PAS ENCORE VU TOURNER EN JEU »
qu'une seule observation réelle permet de lever. Noter aussi ce qui a raté,
avec l'horodatage du log et le nom de la capture.

## Règle de méthode, à ne jamais contourner

**Les faits de jeu viennent d'Ewan**, pas d'une mesure sur une capture. Il
joue depuis des semaines. Proposer, mesurer en jeu, n'échanger qu'après.
