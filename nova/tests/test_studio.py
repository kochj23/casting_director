"""Phase 2 studio: advisors, production crises and achievements (unit, functional, security)."""
import json

import pytest

from nova import studio
from nova.tests.test_nova import call


BASE = {"bookName": "Dune", "character": "Paul Atreides", "characterDescription": "The lead, a young duke",
        "castingBudget": 10_000_000}


@pytest.mark.unit
def test_advisors_are_deterministic_and_bounded():
    d = dict(BASE, actorName="Zendaya", fee=3_000_000, popularity="Star", spentBefore=0)
    a, b = studio.advise(d), studio.advise(d)
    assert a == b and 5 <= a["odds"] <= 95
    assert [x["id"] for x in a["advisors"]] == ["exec", "agent", "director"]
    assert all(x["stance"] in studio.STANCES for x in a["advisors"])


@pytest.mark.unit
def test_going_over_budget_turns_the_exec_against_you():
    d = dict(BASE, actorName="Big Star", fee=9_000_000, popularity="A-List", spentBefore=5_000_000)
    adv = studio.advise(d)
    assert next(x for x in adv["advisors"] if x["id"] == "exec")["stance"] == "oppose"
    cheap = studio.advise(dict(d, fee=500_000, spentBefore=0))
    assert cheap["odds"] > adv["odds"] - 30 and next(x for x in cheap["advisors"] if x["id"] == "exec")["stance"] == "approve"


@pytest.mark.unit
def test_a_no_name_lead_worries_the_agent():
    adv = studio.advise(dict(BASE, actorName="Unknown Actor", fee=100_000, popularity="No-Name", spentBefore=0))
    assert next(x for x in adv["advisors"] if x["id"] == "agent")["stance"] == "oppose"


@pytest.mark.unit
def test_ai_lines_replace_words_never_stances():
    adv = studio.advise(dict(BASE, actorName="Z", fee=1, popularity="Star", spentBefore=0))
    stances = [x["stance"] for x in adv["advisors"]]
    out = studio.with_ai_lines(adv, {"exec": "x" * 500, "agent": "", "director": "Love it."})
    assert [x["stance"] for x in out["advisors"]] == stances
    assert len(out["advisors"][0]["line"]) == 220 and out["advisors"][2]["line"] == "Love it."


@pytest.mark.unit
def test_every_crisis_option_resolves():
    for c in studio.CRISES:
        for oid, *_ in c["options"]:
            r = studio.resolve_crisis(c["id"], oid, "$100,000,000")
            assert r and r["cost"] >= 0 and -10 <= r["score_delta"] <= 10
    assert studio.resolve_crisis("walkout", "nope", 1) is None and studio.resolve_crisis("nope", "meet", 1) is None


@pytest.mark.unit
def test_achievement_rules():
    d = {"wentOverBudget": False, "castDetails": "A (x): Unknown (100000) - No-Name", "overrules": 3,
         "production": {"score_delta": 2}}
    got = set(studio.earned(d, {"overallGameScore": 92, "boxOffice": 2e9, "siskelVerdict": "thumbs_up",
                                "ebertVerdict": "thumbs_up"}))
    assert got == {"first_picture", "blockbuster", "critics_darling", "two_thumbs", "under_budget", "no_names",
                   "maverick", "crisis_manager"}
    assert "razzie" in studio.earned({"wentOverBudget": "true"}, {"overallGameScore": 10})


@pytest.mark.functional
def test_a_picture_with_advice_overrules_and_a_crisis(server):
    base, srv = server
    game = srv.RequestHandlerClass.game
    call(base, "/api/getBookInfo", {"bookName": "Dune", "author": "Frank Herbert"})
    st, b, _ = call(base, "/api/advise", dict(BASE, actorName="Zendaya", fee=3e6, popularity="Star", spentBefore=0))
    assert st == 200 and "odds" in json.loads(b)
    for _ in range(3):
        call(base, "/api/overrule", {"character": "Paul", "actorName": "Zendaya", "opposed": 1})
    crisis = json.loads(call(base, "/api/production/crisis", {"bookName": "Dune", "castDetails": "Paul: Zendaya",
                                                               "movieBudget": 1e8})[1])
    st, b, _ = call(base, "/api/production/choose", {"crisis": crisis["id"], "option": crisis["options"][0]["id"],
                                                     "movieBudget": 1e8})
    chosen = json.loads(b)
    assert st == 200 and "score_delta" not in chosen and chosen["note"]
    res = json.loads(call(base, "/api/generateMovieResults", {"bookName": "Dune", "bookPopularity": "Bestseller",
                                                              "castDetails": "Paul: Zendaya", "wentOverBudget": False})[1])
    keys = {a["key"] for a in res["_achievements"]}
    assert {"first_picture", "maverick", "under_budget"} <= keys and res["production"]["choice"]
    assert game.overrules == 0 and game.production is None                  # reset for the next picture
    again = json.loads(call(base, "/api/generateMovieResults", {"bookName": "Dune", "bookPopularity": "Bestseller",
                                                                "castDetails": "Paul: Zendaya"})[1])
    assert "first_picture" not in {a["key"] for a in again["_achievements"]}  # once only
    ach = json.loads(call(base, "/api/achievements")[1])
    assert "first_picture" in ach["unlocked"] and len(ach["all"]) == len(studio.ACHIEVEMENTS)


@pytest.mark.security
def test_crisis_choices_are_checked_server_side(server):
    base, _ = server
    assert call(base, "/api/production/choose", {"crisis": "walkout", "option": "meet"})[0] == 400   # none dealt
    crisis = json.loads(call(base, "/api/production/crisis", {"bookName": "B", "castDetails": "R: <img src=x>"})[1])
    assert call(base, "/api/production/choose", {"crisis": crisis["id"], "option": "pay_me"})[0] == 400
    assert call(base, "/api/production/choose", {"crisis": "budget" if crisis["id"] != "budget" else "walkout",
                                                 "option": "pay"})[0] == 400
    assert call(base, "/api/advise", {"character": "x" * 400, "actorName": "y"})[0] == 400
    assert call(base, "/api/overrule", {"x": 1}, headers={"Origin": "http://evil"})[0] == 403


@pytest.mark.security
def test_studio_ui_writes_no_html():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "js/ui/studio.js").read_text()
    assert "innerHTML" not in src and "insertAdjacentHTML" not in src
