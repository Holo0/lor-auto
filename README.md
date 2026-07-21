# Legends of Runeterra - Automatisation PvE (Défi Mensuel)

Ce projet automatise une partie du parcours PvE de LoR via reconnaissance d'images (OpenCV) et actions souris/clavier (PyAutoGUI), puis délègue la phase de combat au bot présent dans `LoR-Bot`.

## Ce que fait actuellement le script

Le point d'entrée est `lor_automation.py`.

En mode `--run`, le script actuel :

1. Navigue sur la carte d'aventure (noeuds, voyage, événements).
2. Déclenche le combat quand un noeud ennemi est détecté.
3. Lance le bot de combat `LoR-Bot/code/LOR_Bot.py` via `lor_battle.py`.

Important : dans l'état actuel du code, les étapes d'ouverture du menu Défi Mensuel, sélection de rencontre/champion initial et clic "Utiliser 1 tentative" sont commentées dans `execute_complete_automation()`. Il faut donc démarrer depuis un écran déjà prêt pour la navigation sur la carte.

## Prérequis (Windows)

1. Python 3 installé.
2. LoR lancé en plein écran avec une configuration stable (meme résolution/scale que lors des captures templates).
3. Dossier `assets` rempli avec vos images `.png` de référence.

## Installation rapide

Depuis la racine du projet :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install numpy opencv-python pyautogui pillow keyboard pywin32 requests termcolor
```

Alternative : installer les dépendances historiques de `LoR-Bot` puis compléter avec `pyautogui` :

```powershell
pip install -r .\LoR-Bot\requirements.txt
pip install pyautogui
```

Imports utilises pour le suivi de chemin (`path_following.py`) :

```python
from skimage.morphology import skeletonize
from scipy.ndimage import distance_transform_edt
```

## Assets attendus

Le script lit les templates depuis `assets/`.

Noms utilisés par le code :

- `monthly_challenge.png`
- `active_encounter.png`
- `first_champion.png`
- `use_attempt.png`
- `voyage.png`
- `select_button.png`
- `quit_button.png`
- `combat_button.png`
- `after_combat.png`
- `continue_button.png`
- `retry.png`
- `normal_node.png` (et variantes possibles `normal_node*.png`)
- `enemy_node.png`
- `secondary_enemy_node.png`
- `support_champion_node.png`
- `event_option.png`

Conseils capture :

- capturer des zones nettes et contrastées (icones/boutons, pas de grandes zones floues)
- conserver la meme résolution, mode d'affichage et zoom Windows

## Lancer le projet

1. Activer l'environnement virtuel :

```powershell
.\.venv\Scripts\Activate.ps1
```

2. Vérifier les templates (diagnostic sans clics) :

```powershell
python .\lor_automation.py --test
```

3. Lancer l'automatisation :

```powershell
python .\lor_automation.py --run
```

## Arret d'urgence

PyAutoGUI fail-safe est actif.
Si le script fait n'importe quoi, deplacez immediatement la souris dans un coin de l'ecran pour provoquer l'arret.

## Depannage

- Si le combat ne se lance pas : verifier que `LoR-Bot/code/LOR_Bot.py` est present et que ses dependances sont installees.
- Si aucun element n'est detecte : refaire les captures template avec la meme resolution et la meme luminosite/qualite en jeu.
- Si vous voyez l'erreur "PyAutoGUI was unable to import pyscreeze" :

```powershell
python -m pip install pillow pyscreeze
```

Puis relancer le script dans le meme environnement virtuel.

- Si PowerShell bloque l'activation venv :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```
