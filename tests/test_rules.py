from datetime import datetime

import rules
from conftest import ET, at, make_season, week_schedule
from schedule import POSTPONED, Game


def by_id(games):
    return {g.id: g for g in games}


def test_valid_week_accepted(season):
    games = week_schedule(season, 1)
    picks = [(g.id, g.away) for g in games[:10]]
    out = rules.validate_regular(season, 1, by_id(games), picks, set(), season.deadline(1), 10)
    assert all(d.accepted for d in out)


def test_each_rejection_reason(season):
    games = week_schedule(season, 1)
    early = Game("early", at(season, 1, 0, 18, 0), "BOS", "MIA")  # tips Monday before the 7pm deadline
    nextweek = week_schedule(season, 2)[0]
    g = by_id(games + [early, nextweek])
    tue = games[0]  # ATL @ ...
    picks = [("nope", "BOS"), (tue.id, "BOS"), (nextweek.id, nextweek.away), ("early", "BOS"),
             (games[1].id, games[1].away),  # used earlier in cycle
             (tue.id, "ATL"), (games[15].id, "ATL")]  # ATL twice: Tuesday kept, Thursday rejected
    out = {(d.game_id, d.team): d for d in rules.validate_regular(season, 1, g, picks, {games[1].away},
                                                                 season.deadline(1), 10)}
    assert out[("nope", "BOS")].code == rules.UNKNOWN_GAME
    assert out[(tue.id, "BOS")].code == rules.WRONG_TEAM
    assert out[(nextweek.id, nextweek.away)].code == rules.NOT_THIS_WEEK
    assert out[("early", "BOS")].code == rules.TIPPED
    assert out[(games[1].id, games[1].away)].code == rules.USED_THIS_CYCLE
    assert out[(tue.id, "ATL")].accepted
    assert out[(games[15].id, "ATL")].code == rules.DUPLICATE


def test_duplicate_keeps_earliest_game_regardless_of_order(season):
    games = week_schedule(season, 1)
    sat, tue = games[30], games[0]
    assert sat.away == tue.away
    out = rules.validate_regular(season, 1, by_id(games), [(sat.id, sat.away), (tue.id, tue.away)], set(),
                                 season.deadline(1), 10)
    assert [(d.game_id, d.accepted) for d in out] == [(tue.id, True), (sat.id, False)]


def test_over_limit(season):
    games = week_schedule(season, 1)
    out = rules.validate_regular(season, 1, by_id(games), [(g.id, g.away) for g in games[:12]], set(),
                                 season.deadline(1), 10)
    assert sum(d.accepted for d in out) == 10
    assert {d.code for d in out if not d.accepted} == {rules.OVER_LIMIT}


def test_special_games_are_not_regular_picks(season):
    xmas = Game("xmas1", datetime(2026, 12, 25, 12, 0, tzinfo=ET), "NYK", "SAS")
    out = rules.validate_regular(season, 9, {"xmas1": xmas}, [("xmas1", "NYK")], set(), season.deadline(9), 10)
    assert out[0].code == rules.SPECIAL_GAME
    assert rules.legal_options(season, 9, [xmas], set(), season.deadline(9)) == []


def test_legal_options_skip_used_teams_and_tipped_games(season):
    games = week_schedule(season, 1) + [Game("early", at(season, 1, 0, 18, 0), "BOS", "MIA")]
    opts = rules.legal_options(season, 1, games, {"ATL"}, season.deadline(1))
    teams = [t for _, t in opts]
    assert "ATL" not in teams and all(g.id != "early" for g, _ in opts)
    assert len(opts) == 3 * 30 - 3  # 3 games each for 29 teams


def test_validate_special(season):
    final = Game("cup", datetime(2026, 12, 11, 20, 30, tzinfo=ET), "NYK", "OKC")
    regular = week_schedule(season, 1)[0]
    g = {"cup": final, regular.id: regular}
    before = datetime(2026, 12, 11, 12, 0, tzinfo=ET)
    out = rules.validate_special(season, g, [("cup", "OKC"), ("cup", "NYK"), (regular.id, regular.home)], before)
    assert [d.accepted for d in out] == [True, False, False]
    assert not rules.validate_special(season, g, [("cup", "OKC")], datetime(2026, 12, 11, 21, 0, tzinfo=ET))[0].accepted


def test_pick_points(season):
    tip = datetime(2026, 12, 11, 20, 30, tzinfo=ET)
    cup = Game("cup", tip, "NYK", "OKC", "final", 99, 101)
    assert rules.pick_points(season, cup, "OKC") == 5 and rules.pick_points(season, cup, "NYK") == 0
    reg = Game("r", at(season, 1, 1), "BOS", "MIA", "final", 120, 100)
    assert rules.pick_points(season, reg, "BOS") == 1
    assert rules.pick_points(season, Game("p", reg.tip, "BOS", "MIA"), "BOS") is None
    assert rules.pick_points(season, Game("p", reg.tip, "BOS", "MIA", POSTPONED), "BOS") == 0
    assert rules.pick_points(make_season(points_per_win=3), reg, "BOS") == 3


def test_parse_picks(season):
    games = week_schedule(season, 1)
    after = season.deadline(1)
    atl = [g for g in games if "ATL" in g.teams]
    thu_opp = atl[1].home
    parsed = rules.parse_picks(f"Hawks vs {thu_opp}\nHawks sat\nHawks\nxyz", games, after, ET)
    assert parsed[0].game_id == atl[1].id
    assert parsed[1].game_id == atl[2].id
    assert "3 games left" in parsed[2].error and "say which" in parsed[2].error
    assert parsed[3].error == "couldn't find a team in that"


def test_parse_picks_one_per_line_with_commas_inside(season):
    games = week_schedule(season, 1)
    atl = [g for g in games if "ATL" in g.teams]
    text = f"hawks, ATL v {atl[1].home}\nATL sat"
    parsed = rules.parse_picks(text, games, season.deadline(1), ET)
    assert [p.game_id for p in parsed] == [atl[1].id, atl[2].id]
    single_line = rules.parse_picks(f"ATL v {atl[1].home}; ATL sat", games, season.deadline(1), ET)
    assert [p.game_id for p in single_line] == [atl[1].id, atl[2].id]


def test_parse_picks_winner_after_matchup(season):
    games = week_schedule(season, 1)
    g = [g for g in games if "ATL" in g.teams][1]
    text = f"{g.away} @ {g.home} -{g.home}\n{g.away} @ {g.home} - {g.away}\n{g.away} over {g.home}"
    parsed = rules.parse_picks(text, games, season.deadline(1), ET)
    assert [(p.team, p.game_id) for p in parsed] == [(g.home, g.id), (g.away, g.id), (g.away, g.id)]


def test_parse_picks_weekday_words():
    assert [rules._weekday(w) for w in ("wed", "wednesday", "thurs", "saturday", "sun", "suns", "mo")] == \
        [2, 2, 3, 5, 6, None, None]
