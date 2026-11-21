#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lor_automation.py

Point d'entrée historique : il lance maintenant la BOUCLE DE SESSION.

Avant, ce fichier faisait UNE aventure et s'arrêtait : navigation,
combat du boss final, fin du programme. Il fallait le relancer à la main
pour chaque tentative.

    python lor_automation.py            # enchaîne les tentatives
    python lor_automation.py --plan     # dit seulement où en est le jeu

Tout est dans `challenges.py` : les tentatives, les garde-fous et le
bilan. Ce fichier ne garde que le nom, pour ne pas casser les habitudes
ni les raccourcis existants — et parce que `python challenges.py` fait
exactement la même chose.
"""

from challenges import main

if __name__ == "__main__":
    main()
