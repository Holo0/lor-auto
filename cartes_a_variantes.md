# Les cartes à fenêtre de versions

Recensement automatique de `LoR-Bot/card_sets/` : une carte ouvre une
fenêtre quand elle a des **jetons du même nom**, un par branche de son
« ou ». C'est la seule trace fiable — le texte, lui, ne distingue pas
« Deal 3 to a unit or destroy a landmark » (un clic) de « Grant an ally
Spellshield or Overwhelm » (une fenêtre, puis un clic).

**47 cartes** au total : 31 passent
par la fenêtre, 16 sont refusées avant d'être jouées.


## Pilotées — le bot choisit une version, puis cible (31)

| code | nom | type | texte | après le choix | versions |
| --- | --- | --- | --- | --- | --- |
| `06BW015` | Answered Prayer | Spell | Spawn 2, or spend 5 mana to Spawn 4 instead. | aucune | Spawn 2. // Spawn 4. |
| `05BC112` | Blastcone Seedling | Unit | Give me Barrier this round or grant me Impact. | aucune | Give me Barrier this round. // Grant me Impact. |
| `05BC021` | Bouncing Bomb | Spell | Deal 2 to a unit or deal 1 to two enemies. | unité | Deal 1 to two enemies. // Deal 2 to a unit. |
| `05IO024` | Children of the Forest | Spell | Recall an ally, or spend 8 mana to summon Ephemeral copies of the 3 st | allié | Recall an ally. // Summon Ephemeral copies of the 3 strongest f |
| `98SB040` | Dance of Arrows | Spell | Mark a random enemy, or spend 4 mana to deal 3 to all marked enemies. | aucune | Deal 3 to all marked enemies. // Mark a random enemy. |
| `07NX001` | Daring Demolisher | Unit | Deal 1 to the enemy Nexus or activate an ally's Plunder effect. | allié | Activate an ally's Plunder effect. // Deal 1 to the enemy Nexus. |
| `07NX007T8` | Flair | Spell | Give an allied Samira Challenger this round or deal 1 to the enemy Nex | allié | Deal 1 to the enemy Nexus. // Give an allied Samira Challenger this round. |
| `06FR020` | Fracture | Spell | Deal 1 to EVERYTHING or destroy a unit's equipment. | unité | Deal 1 to EVERYTHING. // Destroy a unit's equipment. |
| `06FR030` | Harbinger of Thralls | Unit | Summon a Frozen Thrall or advance all your Frozen Thralls 1 round. | aucune | Advance all your Frozen Thralls 1 round. // Summon a Frozen Thrall. |
| `04SH120` | Imagined Possibilities | Spell | Create a random landmark with Countdown in hand, or advance your landm | aucune | Advance your landmarks 1 round. // Create a random landmark with Countdown in h |
| `04SH034T1` | Instant Century | Spell | Summon a random landmark with Countdown, or advance a landmark 4 round | aucune | Advance a landmark 4 rounds. // Summon a random landmark with Countdown. |
| `05MT013` | Iula | Unit | Grant an ally Spellshield or Overwhelm. grant it to me. | allié | Grant an ally Overwhelm. grant it to me. // Grant an ally Spellshield. grant it to me. |
| `98SB044T4` | Kindred's Dance of Arrows | Spell | Mark a random enemy, or spend 4 mana to deal 3 to all marked enemies.  | aucune | Deal 3 to all marked enemies. Create a The T // Mark a random enemy. Create a The Taker in y |
| `06IO012` | Kinkou's Call | Spell | Summon a Keeper of Masks now or at the next Round Start. Draw 1. | aucune | Summon a Keeper of Masks at the next Round S // Summon a Keeper of Masks. Draw 1. |
| `08PZ008` | Maryam, Temple Caretaker | Unit | Updraft 1 to either draw 1 or refill your spell mana. | carte en main | Updraft 1 to draw 1. // Updraft 1 to refill your spell mana. |
| `06IO034` | Momentous Choice | Spell | Give an ally +2|+0 or +0|+2 this round. | allié | Give an ally +0|+2 this round. // Give an ally +2|+0 this round. |
| `09BC016` | Monstrous Eruption | Spell | Grow an ally's Power or Health to 5 this round. | allié | Grow an ally's Health to 5 this round. // Grow an ally's Power to 5 this round. |
| `06IO039` | Navori Longtail | Unit | Summon a Navori Brigand or give other allies +1|+1 this round. | aucune | Give other allies +1|+1 this round. // Summon a Navori Brigand. |
| `98SB010` | Petals of Fate | Spell | Draw 1 and grant it a random Common item, or spend 3 mana to draw 1 an | aucune | Draw 1 and grant it a random Common item. // Draw 1 and grant it a random Epic item. |
| `02BW008` | Petty Officer | Unit | Summon a Powder Keg or a random 1 cost follower. | aucune | Summon a Powder Keg. // Summon a random 1 cost follower. |
| `04SH109` | Quicksand | Spell | Give an enemy -4|-0 or 2 enemies -1|-0 this round. Disable their posit | ennemi | Give 2 enemies -1|-0 and disable their posit // Give an enemy -4|-0 and disable its positive |
| `98SI002` | Reap | Spell | Grant two enemies Gloom or grant one enemy 2 Gloom. | aucune | Grant an enemy 2 Gloom. // Grant two enemies Gloom. |
| `04SH018` | Rite of Dominance | Spell | Kill an ally or destroy one of your mana gems to give all enemies -2|- | allié | Destroy one of your mana gems to give all en // Kill an ally to give all enemies -2|-0 this  |
| `04SH059` | Rite of Negation | Spell | Kill an ally or destroy one of your mana gems to stop all enemy Fast s | allié | Destroy one of your mana gems to stop all en // Kill an ally to stop all enemy Fast spells,  |
| `06DE037` | Royal Decree | Spell | Give an ally +2|+2 and Challenger this round or summon an Honored Lord | allié | Give an ally +2|+2 and Challenger this round // Summon an Honored Lord. |
| `08MT024` | Ruby-Eyed Conjurer | Unit | Grant SpellShield or Overwhelm to an ally in hand. | carte en main | Grant Overwhelm to an ally in hand. // Grant SpellShield to an ally in hand. |
| `04IO020` | Scattered Pod | Unit | Draw a Slow, Fast, or Burst spell. | aucune | Draw a Burst spell. // Draw a Fast spell. // Draw a Slow spell. |
| `98SB012` | Spirit Rush | Spell | Summon a 3|3 Fox-Fire Challenging an enemy, or spend 8 mana to summon  | ennemi | Summon a 1|1 Fox-Fire Challenging EACH enemy // Summon a 3|3 Fox-Fire Challenging an enemy. |
| `06NX033` | Strategic Execution | Spell | Stun 2 enemies or spend 6 mana to summon a Legion General. | aucune | Stun 2 enemies. // Summon a Legion General. |
| `05BC216` | Yordle Contraption | Spell | Destroy a landmark or create 2 random multi-region followers in hand. | aucune | Create 2 random multi-region followers in ha // Destroy a landmark. |
| `05BC163T3` | Ziggs' Bouncing Bomb | Spell | Deal 2 to a unit or deal 1 to two enemies. Create a Ziggs in your deck | unité | Deal 1 to two enemies. Create a Ziggs in you // Deal 2 to a unit. Create a Ziggs in your dec |

## Refusées avant la pose — rien à piloter (16)

| code | nom | type | texte | après le choix | versions |
| --- | --- | --- | --- | --- | --- |
| `98SB020T1` | Ahri's Orb of Deception | Spell | Deal 2 to an enemy unit, or spend 4 mana to deal 6 to an enemy unit. C | 2 cibles à cliquer, le bot n'en clique qu'une | Deal 2 to an enemy unit. Create a Spirit Blo // Deal 6 to an enemy unit. Create a Spirit Blo |
| `06DE024` | Catch! | Spell | Give an ally +1|+1 this round or equip it with an equipment in hand th | 2 cibles à cliquer, le bot n'en clique qu'une | Equip an ally with an equipment that costs 2 // Give an ally +1|+1 this round. |
| `05BC223` | Entrapment | Spell | Pick 1 of 3 units or spells from the enemy deck and plant 3 Poison Puf | ouvre un choix de carte | Pick 1 of 3 spells from the enemy deck and p // Pick 1 of 3 units from the enemy deck and pl |
| `06DE017` | Fish Fight | Spell | An ally and an enemy strike each other, or an Equipped ally strikes an | 4 cibles à cliquer, le bot n'en clique qu'une | An Equipped ally strikes an enemy, then is u // An ally and an enemy strike each other. |
| `06DE026` | Icathian Myths | Spell | Create an Icathian Mirage in hand that costs 0 this round, or create a | ouvre un choix entre plusieurs cartes créées | Create a Golden Spatula in hand. // Create an Icathian Mirage in hand that costs |
| `06NX022` | Legionary Charge | Spell | Draw an ally with 5+ Power, or grow an ally to 5 Power this round. | 2 cibles à cliquer, le bot n'en clique qu'une | Draw an ally with 5+ Power. // Grow an ally to 5 Power this round. |
| `98SB019` | Orb of Deception | Spell | Deal 2 to an enemy unit, or spend 4 mana to deal 6 to an enemy unit. | 2 cibles à cliquer, le bot n'en clique qu'une | Deal 2 to an enemy unit. // Deal 6 to an enemy unit. |
| `06SI032` | Quietus | Spell | Kill a unit with total Power and Health of 4 or less, or destroy a uni | 2 cibles à cliquer, le bot n'en clique qu'une | Destroy a unit's equipment. // Kill a unit with total Power and Health of 4 |
| `04SH130T10` | Relic of Power | Spell | Pick 1 - Predict then draw 1, summon a Sandstone Charger, or grant all | ouvre un choix de carte | Grant allies +1|+0. // Predict, then draw 1. // Summon a Sandstone Charger. |
| `04SH121` | Rite of Calling | Spell | Kill an ally or destroy one of your mana gems to draw a champion. | 2 cibles à cliquer, le bot n'en clique qu'une | Destroy one of your mana gems to draw a Cham // Kill an ally to draw a Champion. |
| `05SH007` | Rite of the Arcane | Spell | Destroy an allied landmark or one of your mana gems to deal 4 to a uni | 2 cibles à cliquer, le bot n'en clique qu'une | Destroy an allied landmark to deal 4 to a un // Destroy one of your mana gems to deal 4 to a |
| `07DE002` | Search Warrant | Spell | An ally with 4+ Power Captures a unit or an ally Captures a landmark. | 3 cibles à cliquer, le bot n'en clique qu'une | An ally Captures a landmark. // An ally with 4+ Power Captures a unit. |
| `07SI002` | Soul Harvest | Spell | Kill a follower with 3 or less Power, or spend 3 mana to kill a champi | 2 cibles à cliquer, le bot n'en clique qu'une | Kill a champion with 3 or less Power. // Kill a follower with 3 or less Power. |
| `07IO020` | Tag Out! | Spell | Recall an ally and create a Coin in hand, or spend 5 mana to Recall an | ouvre un choix entre plusieurs cartes créées | Recall an ally and create a Coin in hand. // Recall an enemy and create a Coin in hand. |
| `05SH004` | Unleashed Energy | Spell | Give an ally +2|+1 this round or destroy an allied landmark to give an | 3 cibles à cliquer, le bot n'en clique qu'une | Destroy an allied landmark to give an ally + // Give an ally +2|+1 this round. |
| `05SH014T3` | Xerath's Rite of the Arcane | Spell | Destroy an allied landmark or one of your mana gems to deal 4 to a uni | 2 cibles à cliquer, le bot n'en clique qu'une | Destroy an allied landmark to deal 4 to a un // Destroy one of your mana gems to deal 4 to a |
