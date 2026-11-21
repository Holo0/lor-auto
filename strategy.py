"""
strategy.py — le PROFIL DU DECK, et ce qu'il change dans les décisions.

Le bot jouait tous les decks de la même façon : bilan d'attaque à zéro
ou rien, un dégât au nexus vaut un point de valeur, mulligan à coût > 3.
Or les decks du Chemin des champions n'ont pas le même plan de jeu, et
le journal du 06/09/2026 (7 défaites sur 7 au boss intermédiaire) montre
un bot qui « garde le banc en défense » pendant que le boss remplit le
sien : contre l'IA, qui monte en puissance chaque round avec son pouvoir
passif, ne pas presser le nexus, c'est perdre lentement.

Ce module lit la decklist (`/static-decklist`, déjà dans `snapshot.deck`)
et la base de cartes, en tire des SIGNAUX (déclencheurs « Attack: »,
Overwhelm/Elusive, Challenger et Vulnerable accordés, sorts de retrait,
courbe de coûts…) et choisit un ARCHÉTYPE qui fixe quelques paramètres :

    - `nexus_base_weight` : ce que vaut UN dégât au nexus adverse quand
      il a beaucoup de PV (`actions.nexus_weight` monte de toute façon
      quand ils baissent) ;
    - `attack_floor` : le bilan minimal accepté pour déclarer une attaque
      qui touche le nexus (0 = l'ancien comportement) ;
    - `attack_trigger_bonus` : la valeur d'UN déclencheur « Attack: » qui
      part (Nilah, Bard, Ziggs, Jarvan… — l'effet est réel même si son
      montant ne se lit pas dans le texte) ;
    - `mulligan_max_cost` : le seuil de rejet au mulligan.

Sans decklist (tests, base de cartes absente), `DEFAULT` rend EXACTEMENT
l'ancien comportement : rien ne change tant qu'on ne sait rien du deck.

    python strategy.py              # profil du deck de la partie ouverte
    python strategy.py --traces     # tous les decks des traces enregistrées
    python strategy.py 07SH013 04SH047 ...   # profil d'une liste de codes

Aucune souris ici : pure décision, testée dans `test_strategy.py`.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional


# ============================================================
# LES ARCHÉTYPES
# ============================================================

@dataclass(frozen=True)
class Strategy:
    name: str                       # clé courte, journalisée (`config.archetype`)
    label: str                      # phrase pour les logs
    nexus_base_weight: float = 1.0  # poids d'UN dégât au nexus à pleine santé
    attack_floor: float = 0.0       # bilan minimal d'une attaque qui touche le nexus
    attack_trigger_bonus: float = 0.0   # valeur d'un « Attack: » qui part
    mulligan_max_cost: int = 3
    champions: tuple = ()
    regions: tuple = ()
    signals: tuple = ()             # ce qui a été vu dans le deck, pour le log

    def describe(self) -> str:
        who = ", ".join(self.champions) or "champions inconnus"
        return (
            f"{self.label} ({who}) — 1 dégât au nexus vaut {self.nexus_base_weight:g}, "
            f"attaque acceptée dès un bilan de {self.attack_floor:+g}, "
            f"mulligan à coût > {self.mulligan_max_cost}"
            + (f" ; signaux : {', '.join(self.signals)}" if self.signals else "")
        )


# Sans information : l'ancien comportement, à l'identique.
DEFAULT = Strategy("defaut", "stratégie par défaut")

# Les quatre plans de jeu que le bot sait distinguer. Les nombres sont des
# RÉGLAGES, pas des vérités : ils sont là pour être comparés dans
# `journal.py` (le journal enregistre `archetype`).
AGGRO = Strategy(
    "aggro", "deck agressif : presser le nexus",
    nexus_base_weight=2.0, attack_floor=-1.0, attack_trigger_bonus=1.0,
    mulligan_max_cost=2,
)
PULL = Strategy(
    "tirage", "deck de tirage (Challenger / Vulnerable) : tuer les unités d'en face",
    nexus_base_weight=1.2, attack_floor=0.0, attack_trigger_bonus=1.0,
    mulligan_max_cost=3,
)
MIDRANGE = Strategy(
    "midrange", "deck de valeur : attaquer dès que l'échange tient",
    nexus_base_weight=1.5, attack_floor=0.0, attack_trigger_bonus=1.0,
    mulligan_max_cost=3,
)
CONTROL = Strategy(
    "controle", "deck de contrôle : nettoyer d'abord, frapper ensuite",
    nexus_base_weight=1.0, attack_floor=0.0, attack_trigger_bonus=0.5,
    mulligan_max_cost=4,
)

ARCHETYPES = {s.name: s for s in (DEFAULT, AGGRO, PULL, MIDRANGE, CONTROL)}


# ============================================================
# LES SIGNAUX LUS DANS LES CARTES
# ============================================================
# Tout se lit dans card_sets (textes ANGLAIS, cf. CLAUDE.md). On compte
# des OCCURRENCES pondérées par le nombre d'exemplaires dans le deck.

_ATTACK_TRIGGER_RX = re.compile(r"(?:^|[\r\n])\s*Attack:", re.IGNORECASE)
_NEXUS_STRIKE_RX = re.compile(r"Nexus Strike|to the enemy Nexus|enemy Nexus", re.IGNORECASE)
_VULNERABLE_RX = re.compile(r"\bVulnerable\b")
_FREE_ATTACK_RX = re.compile(r"free attack|strikes? an enemy|strike each other", re.IGNORECASE)
_REMOVAL_RX = re.compile(
    r"\b(kill|obliterate|stun|frostbite|silence|transform an enemy|transform a unit|"
    r"deal \d+ to (?:a|an|the) (?:unit|enemy|follower|champion))\b", re.IGNORECASE)
_TRANSFORM_RX = re.compile(r"\btransform", re.IGNORECASE)
_AMBUSH_RX = re.compile(r"\bAmbush\b")

AGGRO_KEYWORDS = ("Overwhelm", "Elusive", "QuickStrike", "Quick Attack", "Fearsome", "Impact")
PULL_KEYWORDS = ("Challenger",)


def has_attack_trigger(card) -> bool:
    """« Attack: … » en tête d'une ligne du texte — l'unité gagne à attaquer."""
    text = getattr(card, "description", None)
    if text is None and isinstance(card, dict):
        text = card.get("descriptionRaw") or ""
    return bool(_ATTACK_TRIGGER_RX.search(text or ""))


def _keywords_of(info: dict) -> set:
    return set(info.get("keywordRefs") or ()) | set(info.get("keywords") or ())


@dataclass
class DeckSignals:
    cards: int = 0
    units: int = 0
    spells: int = 0
    unit_cost_total: int = 0
    cheap: int = 0                  # cartes à coût ≤ 2
    expensive: int = 0              # cartes à coût ≥ 5
    attack_triggers: int = 0
    nexus_strikes: int = 0
    aggro_keywords: int = 0
    challengers: int = 0
    vulnerable_grants: int = 0
    free_attacks: int = 0
    removals: int = 0
    transforms: int = 0
    ambush: int = 0
    champions: List[str] = field(default_factory=list)
    regions: Dict[str, int] = field(default_factory=dict)
    unknown: List[str] = field(default_factory=list)

    @property
    def average_unit_cost(self) -> float:
        return self.unit_cost_total / self.units if self.units else 0.0


def read_signals(deck: Dict[str, int], card_db: dict) -> DeckSignals:
    """Compte ce que le deck contient, exemplaires compris."""
    sig = DeckSignals()
    for code, n in (deck or {}).items():
        info = card_db.get(code)
        n = int(n or 0)
        sig.cards += n
        if not info:
            sig.unknown.append(code)
            continue
        cost = int(info.get("cost") or 0)
        kind = (info.get("type") or "").lower()
        text = info.get("descriptionRaw") or ""
        kws = _keywords_of(info)

        if info.get("supertype") == "Champion":
            name = info.get("name") or code
            if name not in sig.champions:
                sig.champions.append(name)
        for region in info.get("regionRefs") or ():
            sig.regions[region] = sig.regions.get(region, 0) + n

        if kind == "unit":
            sig.units += n
            sig.unit_cost_total += cost * n
        elif kind == "spell":
            sig.spells += n
        if cost <= 2:
            sig.cheap += n
        if cost >= 5:
            sig.expensive += n

        if has_attack_trigger(info):
            sig.attack_triggers += n
        if _NEXUS_STRIKE_RX.search(text):
            sig.nexus_strikes += n
        sig.aggro_keywords += n * sum(1 for k in AGGRO_KEYWORDS if k in kws)
        sig.challengers += n * sum(1 for k in PULL_KEYWORDS if k in kws)
        if _VULNERABLE_RX.search(text):
            sig.vulnerable_grants += n
        if _FREE_ATTACK_RX.search(text):
            sig.free_attacks += n
        if kind == "spell" and _REMOVAL_RX.search(text):
            sig.removals += n
        if _TRANSFORM_RX.search(text):
            sig.transforms += n
        if _AMBUSH_RX.search(text) or "Ambush" in kws:
            sig.ambush += n
    return sig


# ============================================================
# LE CHOIX
# ============================================================

def scores(sig: DeckSignals) -> Dict[str, float]:
    """
    Trois scores concurrents, sur la même échelle (≈ nombre de cartes qui
    votent). MIDRANGE n'a pas de score : c'est ce qui reste quand aucun
    plan ne se détache.
    """
    aggro = (
        sig.attack_triggers
        + sig.nexus_strikes
        + 0.5 * sig.aggro_keywords
        + (3 if sig.average_unit_cost and sig.average_unit_cost <= 2.6 else 0)
        + (2 if sig.cards and sig.cheap / sig.cards >= 0.45 else 0)
    )
    pull = sig.challengers + sig.vulnerable_grants + sig.free_attacks
    control = (
        sig.removals
        + (2 if sig.spells >= 8 else 0)
        + (2 if sig.average_unit_cost >= 3.6 else 0)
    )
    return {"aggro": aggro, "tirage": pull, "controle": control}


# Un plan ne l'emporte qu'à partir de ce nombre de « votes », et s'il
# devance nettement le suivant ; sinon le deck est MIDRANGE.
MIN_VOTES = 5.0
LEAD = 1.5


def choose(sig: DeckSignals) -> Strategy:
    table = scores(sig)
    ranked = sorted(table.items(), key=lambda kv: -kv[1])
    (best, best_score), (_, second) = ranked[0], ranked[1]
    base = MIDRANGE
    if best_score >= MIN_VOTES and best_score - second >= LEAD:
        base = ARCHETYPES[best]

    signals = []
    if sig.attack_triggers:
        signals.append(f"{sig.attack_triggers} déclencheurs « Attack: »")
    if sig.nexus_strikes:
        signals.append(f"{sig.nexus_strikes} effets au nexus")
    if sig.aggro_keywords:
        signals.append(f"{sig.aggro_keywords} mots-clés offensifs")
    if sig.challengers or sig.vulnerable_grants:
        signals.append(f"{sig.challengers} Challenger, {sig.vulnerable_grants} Vulnerable accordés")
    if sig.free_attacks:
        signals.append(f"{sig.free_attacks} duels dirigés")
    if sig.removals:
        signals.append(f"{sig.removals} sorts de retrait")
    if sig.ambush:
        signals.append(f"{sig.ambush} Ambush")
    if sig.transforms:
        signals.append(f"{sig.transforms} cartes de transformation")
    signals.append(f"coût moyen des unités {sig.average_unit_cost:.1f}")
    if sig.unknown:
        signals.append(f"{len(sig.unknown)} codes inconnus")

    regions = tuple(sorted(sig.regions, key=lambda r: -sig.regions[r]))[:2]
    return replace(base, champions=tuple(sig.champions), regions=regions,
                   signals=tuple(signals))


def profile_deck(deck: Optional[Dict[str, int]], card_db: Optional[dict]) -> Strategy:
    """
    Le point d'entrée : decklist + base de cartes → stratégie.

    Deck vide ou base absente → `DEFAULT`, sans exception : la stratégie
    est un confort, jamais une condition pour jouer.
    """
    if not deck or not card_db:
        return DEFAULT
    try:
        return choose(read_signals(deck, card_db))
    except Exception:       # noqa: BLE001 — une decklist bizarre ne doit pas planter un combat
        return DEFAULT


# ============================================================
# LIGNE DE COMMANDE
# ============================================================

def _load_db() -> dict:
    # Sans souris ni écran (VM, CI) : `ensure_headless` remplace pyautogui,
    # exactement comme dans les suites de tests et le rejeu.
    from replay import ensure_headless
    ensure_headless()
    import lor_api
    return lor_api.load_card_db()


def describe_deck(deck: Dict[str, int], card_db: dict) -> str:
    lines = []
    for code, n in sorted(deck.items(), key=lambda kv: (card_db.get(kv[0], {}).get("cost", 99), kv[0])):
        info = card_db.get(code, {})
        kind = info.get("type") or "?"
        if info.get("supertype") == "Champion":
            kind = "Champion"
        lines.append(
            f"  {n}x {info.get('cost', '?')!s:>2} {info.get('name') or code:<28} {kind:<9} "
            f"{(info.get('descriptionRaw') or '').replace(chr(13), ' ').replace(chr(10), ' ')[:70]}"
        )
    return "\n".join(lines)


def decks_from_traces(root: Path) -> List[tuple]:
    """Les decklists distinctes vues dans `traces/*/events.jsonl`."""
    found, seen = [], set()
    for path in sorted(glob.glob(str(root / "traces" / "*" / "events.jsonl"))):
        with open(path, encoding="utf8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("k") != "deck":
                    continue
                cards = (event.get("data") or {}).get("CardsInDeck") or {}
                key = json.dumps(cards, sort_keys=True)
                if not cards or key in seen:
                    continue
                seen.add(key)
                found.append((Path(path).parent.name, event.get("t"), cards))
    return found


def _print_profile(deck: Dict[str, int], card_db: dict, title: str) -> None:
    sig = read_signals(deck, card_db)
    strat = choose(sig)
    print(f"== {title}")
    print(describe_deck(deck, card_db))
    print(f"  scores : {scores(sig)}")
    print(f"  -> {strat.describe()}")
    print()


def main(argv: Iterable[str]) -> None:
    args = list(argv)
    card_db = _load_db()
    import lor_api
    if not card_db:
        print("Base de cartes vide : lance LoR-Bot/code/download_card_sets.py.")
        sys.exit(1)
    if "--traces" in args:
        decks = decks_from_traces(lor_api.PROJECT_ROOT)
        if not decks:
            print("Aucune decklist dans traces/.")
        for name, t, cards in decks:
            _print_profile(cards, card_db, f"{name} (t={t})")
        return
    if args:
        deck = {}
        for token in args:
            code, _, n = token.partition(":")
            deck[code] = deck.get(code, 0) + int(n or 2)
        _print_profile(deck, card_db, "codes donnés")
        return
    try:
        data = lor_api.get_static_decklist()
    except Exception as exc:     # noqa: BLE001
        print(f"Partie ouverte illisible ({exc}). Donne des codes ou --traces.")
        sys.exit(1)
    cards = (data or {}).get("CardsInDeck") or {}
    if not cards:
        print("Aucune partie en cours (decklist vide).")
        sys.exit(1)
    _print_profile({str(k): int(v) for k, v in cards.items()}, card_db, "partie ouverte")


if __name__ == "__main__":
    main(sys.argv[1:])
