"""NBA teams: canonical tricodes and the names people actually type."""

import re
from difflib import get_close_matches
from typing import Optional

# tricode -> (city, nickname)
TEAMS = {
    "ATL": ("Atlanta", "Hawks"),
    "BOS": ("Boston", "Celtics"),
    "BKN": ("Brooklyn", "Nets"),
    "CHA": ("Charlotte", "Hornets"),
    "CHI": ("Chicago", "Bulls"),
    "CLE": ("Cleveland", "Cavaliers"),
    "DAL": ("Dallas", "Mavericks"),
    "DEN": ("Denver", "Nuggets"),
    "DET": ("Detroit", "Pistons"),
    "GSW": ("Golden State", "Warriors"),
    "HOU": ("Houston", "Rockets"),
    "IND": ("Indiana", "Pacers"),
    "LAC": ("LA", "Clippers"),
    "LAL": ("Los Angeles", "Lakers"),
    "MEM": ("Memphis", "Grizzlies"),
    "MIA": ("Miami", "Heat"),
    "MIL": ("Milwaukee", "Bucks"),
    "MIN": ("Minnesota", "Timberwolves"),
    "NOP": ("New Orleans", "Pelicans"),
    "NYK": ("New York", "Knicks"),
    "OKC": ("Oklahoma City", "Thunder"),
    "ORL": ("Orlando", "Magic"),
    "PHI": ("Philadelphia", "76ers"),
    "PHX": ("Phoenix", "Suns"),
    "POR": ("Portland", "Trail Blazers"),
    "SAC": ("Sacramento", "Kings"),
    "SAS": ("San Antonio", "Spurs"),
    "TOR": ("Toronto", "Raptors"),
    "UTA": ("Utah", "Jazz"),
    "WAS": ("Washington", "Wizards"),
}

# Nicknames, plus alternate codes used by data feeds (ESPN: GS, NY, SA, UTAH, WSH, ...).
# "NO" (New Orleans) is left out: it reads as the word "no" in DMs. Map it in the data-source adapter.
EXTRA_ALIASES = {
    "hawks": "ATL", "celts": "BOS", "bkn": "BKN", "bk": "BKN", "brk": "BKN",
    "cha": "CHA", "cho": "CHA", "cavs": "CLE", "mavs": "DAL", "nugs": "DEN",
    "gs": "GSW", "dubs": "GSW", "golden state warriors": "GSW",
    "clips": "LAC", "la clippers": "LAC", "los angeles clippers": "LAC",
    "la lakers": "LAL", "grizz": "MEM", "wolves": "MIN", "twolves": "MIN",
    "nola": "NOP", "pels": "NOP", "ny": "NYK", "nyk": "NYK",
    "sixers": "PHI", "philly": "PHI", "phx": "PHX", "pho": "PHX",
    "blazers": "POR", "trailblazers": "POR", "sa": "SAS", "utah": "UTA", "utah jazz": "UTA",
    "wsh": "WAS", "wiz": "WAS",
}

# Cities shared by two teams are left out on purpose ("los angeles", "la").
_AMBIGUOUS = {"la", "los angeles"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _build_aliases() -> dict:
    aliases = {}
    for code, (city, nickname) in TEAMS.items():
        for name in (code, city, nickname, f"{city} {nickname}"):
            if _norm(name) not in _AMBIGUOUS:
                aliases[_norm(name)] = code
    aliases.update(EXTRA_ALIASES)
    return aliases


ALIASES = _build_aliases()
MAX_ALIAS_WORDS = max(len(a.split()) for a in ALIASES)


def team_name(code: str) -> str:
    city, nickname = TEAMS[code]
    return f"{city} {nickname}"


def resolve_team(text: str) -> Optional[str]:
    """Return the tricode for a team name, code or nickname, allowing small typos. None if unrecognised."""
    key = _norm(text)
    if key in ALIASES:
        return ALIASES[key]
    match = get_close_matches(key, ALIASES.keys(), n=1, cutoff=0.8) if len(key) >= 4 else []
    return ALIASES[match[0]] if match else None


def find_teams(text: str) -> list:
    """Teams mentioned in free text, in order, longest names first ("Golden State" before "State")."""
    words = _norm(text).split()
    found, i = [], 0
    while i < len(words):
        for size in range(min(MAX_ALIAS_WORDS, len(words) - i), 0, -1):
            phrase = " ".join(words[i:i + size])
            code = ALIASES.get(phrase) or (resolve_team(phrase) if size == 1 else None)
            if code:
                found.append(code)
                i += size
                break
        else:
            i += 1
    return found
