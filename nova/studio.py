"""The studio around Austin's game (Nova edition phase 2, from GTNW): advisors who weigh in on every casting with odds
you can overrule, a production crisis mid-shoot whose choice costs money and moves the result, and achievements.

The numbers are deterministic rules (same inputs, same answer) so the game is fair and testable; an AI brain only
writes the advisors' lines, and its output is coerced and clamped like every other model reply.
"""
import hashlib
import random

from nova import rules

# ── advisors ───────────────────────────────────────────────────────────────────────────────────────────────────
ADVISORS = [("exec", "Studio Exec"), ("agent", "Casting Agent"), ("director", "The Director")]
STANCES = ("approve", "caution", "oppose")
TIER_RANK = {"a-list": 3, "star": 2, "working actor": 1, "up-and-comer": 0, "no-name": 0}
LEAD_WORDS = ("lead", "protagonist", "hero", "heroine", "main", "title", "narrator")

ADVISOR_SYSTEM = (
    "You are three advisors at a 1990s Hollywood studio reacting to one casting decision: the Studio Exec (money, "
    "box office), the Casting Agent (star power, fit) and the Director (craft, chemistry). Each gets ONE short, "
    "punchy, in-character sentence that agrees with the stance given. Fun, no profanity, no real-person insults.")
ADVISOR_SCHEMA = {"type": "OBJECT", "properties": {
    "exec": {"type": "STRING"}, "agent": {"type": "STRING"}, "director": {"type": "STRING"}},
    "required": ["exec", "agent", "director"]}


def _rng(*parts) -> random.Random:
    seed = hashlib.sha256("|".join(str(p).strip().lower() for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _tier(popularity: str) -> int:
    p = (popularity or "").lower()
    return next((v for k, v in TIER_RANK.items() if k in p), 1)


def advise(d: dict) -> dict:
    """Stances + odds for one casting. d: character, characterDescription, actorName, fee, popularity,
    castingBudget, spentBefore (spent on the other roles)."""
    fee = rules.money(d.get("fee"))
    budget = max(1.0, rules.money(d.get("castingBudget"), 1.0))
    spent = rules.money(d.get("spentBefore"))
    share = fee / budget
    over = spent + fee > budget
    tier = _tier(str(d.get("popularity")))
    desc = f"{d.get('character', '')} {d.get('characterDescription', '')}".lower()
    lead = any(w in desc for w in LEAD_WORDS)
    r = _rng("advise", d.get("actorName"), d.get("character"))

    exec_ = "oppose" if over else "caution" if share > 0.45 else "approve"
    agent = "approve" if tier >= 2 or (not lead and tier >= 1) else ("oppose" if lead and tier == 0 else "caution")
    director = r.choice(["approve", "approve", "caution", "oppose"]) if tier < 3 else r.choice(["approve", "caution"])
    stances = {"exec": exec_, "agent": agent, "director": director}

    odds = 55 + 12 * tier - (25 if over else 0) - (10 if lead and tier == 0 else 0) - int(max(0, share - 0.35) * 40)
    odds += sum({"approve": 4, "caution": 0, "oppose": -6}[s] for s in stances.values()) + r.randint(-5, 5)
    odds = max(5, min(95, odds))

    lines = {
        "exec": {"approve": "Numbers work. Sign it before their agent wakes up.",
                 "caution": f"That's {int(share * 100)}% of the casting budget on one name. Make it count.",
                 "oppose": "We'd be over budget. I am not explaining that to the board."}[exec_],
        "agent": {"approve": "Right face, right price, people will buy the ticket.",
                  "caution": "Solid, but nobody's lining up around the block for this one.",
                  "oppose": "A no-name carrying the picture? That's a gamble, babe."}[agent],
        "director": {"approve": "I can see it. They'll disappear into the part.",
                     "caution": "Let me get them in a room first. Chemistry read.",
                     "oppose": "Wrong energy for this role. I'll fight you on it."}[director],
    }
    return {"advisors": [{"id": k, "name": n, "stance": stances[k], "line": lines[k]} for k, n in ADVISORS],
            "odds": odds, "opposed": sum(s == "oppose" for s in stances.values())}


def with_ai_lines(advice: dict, lines: dict | None) -> dict:
    """Replace the house lines with the AI's (already schema-coerced), trimmed. Stances and odds never change."""
    if not lines:
        return advice
    for a in advice["advisors"]:
        t = str(lines.get(a["id"]) or "").strip()
        if t:
            a["line"] = t[:220]
    return advice


def advisor_query(d: dict, advice: dict) -> str:
    stance = ", ".join(f"{a['name']}: {a['stance']}" for a in advice["advisors"])
    return (f"Book: {str(d.get('bookName'))[:200]}\nRole: {str(d.get('character'))[:120]} — "
            f"{str(d.get('characterDescription'))[:400]}\nCasting: {str(d.get('actorName'))[:120]} "
            f"({str(d.get('popularity'))[:40]}, fee ${rules.money(d.get('fee')):,.0f}, casting budget "
            f"${rules.money(d.get('castingBudget')):,.0f})\nStances (keep them): {stance}\n"
            "Respond with this JSON schema.")


# ── production crisis ──────────────────────────────────────────────────────────────────────────────────────────
# Each option: cost as a share of the movie budget, and a score delta the critics feel (hidden until results).
CRISES = [
    {"id": "walkout", "title": "STAR WALKS OFF SET", "text": "{lead} has locked themselves in their trailer over "
     "rewrites to their big scene. Day three of nobody shooting.",
     "options": [("meet", "Give them the rewrite they want", 0.03, -3, "The scene got longer. Not better."),
                 ("hold", "Hold firm and shoot around them", 0.05, +2, "The fight showed on screen in a good way."),
                 ("replace", "Threaten to recast", 0.0, -6, "They came back. They also phoned it in.")]},
    {"id": "weather", "title": "MONSOON ON LOCATION", "text": "A week of storms has flooded the exterior set. "
     "The insurance adjuster is not returning calls.",
     "options": [("wait", "Wait it out", 0.06, +1, "Patience paid: the light was gorgeous when it cleared."),
                 ("stage", "Move it to a soundstage", 0.04, -2, "The soundstage looks like a soundstage."),
                 ("rewrite", "Rewrite the scenes as interiors", 0.01, -4, "Fans of the book noticed.")]},
    {"id": "reshoots", "title": "TEST SCREENING DISASTER", "text": "The Pasadena test audience hated the ending. "
     "Scorecards say 'confusing' and 'why'.",
     "options": [("reshoot", "Full reshoot of the ending", 0.08, +5, "The new ending landed."),
                 ("recut", "Recut what we have", 0.01, 0, "Cleaner, if not braver."),
                 ("ignore", "Trust the vision, change nothing", 0.0, -2, "Critics called it 'bold'. Audiences didn't.")]},
    {"id": "tabloid", "title": "TABLOID SCANDAL", "text": "{lead} is on the cover of every checkout-aisle "
     "magazine for something that happened in Cabo.",
     "options": [("lean", "Lean into it for publicity", 0.0, -1, "Opening weekend got a curiosity bump."),
                 ("pr", "Hire a crisis PR firm", 0.02, +1, "The story died in a week."),
                 ("silence", "No comment", 0.0, 0, "It blew over. Mostly.")]},
    {"id": "budget", "title": "THE EFFECTS HOUSE WANTS MORE", "text": "The visual effects vendor says the big set "
     "piece needs another month and a lot more money.",
     "options": [("pay", "Pay for the full effects", 0.10, +4, "The set piece is the trailer."),
                 ("practical", "Go practical, build it for real", 0.05, +3, "Audiences felt the weight of it."),
                 ("cut", "Cut the set piece", 0.0, -5, "The movie lost its signature moment.")]},
    {"id": "feud", "title": "ON-SET FEUD", "text": "Two of your leads won't be in the same room. The director "
     "is shooting their scenes on different days and praying.",
     "options": [("retreat", "Send them on a bonding retreat", 0.02, +2, "They hate each other slightly less."),
                 ("split", "Keep shooting them apart", 0.01, -3, "Their big scene has zero chemistry."),
                 ("use", "Use the tension in the scene", 0.0, +3, "That argument scene? Real.")]},
]


def production_crisis(d: dict) -> dict:
    """One crisis for this production, picked deterministically from the book and the cast."""
    cast = [c.strip() for c in str(d.get("castDetails") or "").splitlines() if c.strip()]
    r = _rng("crisis", d.get("bookName"), "|".join(cast))
    c = r.choice(CRISES)
    lead = "Your lead"
    if cast:
        actor = cast[0].split(":", 1)[-1].split("(")[0].strip()
        lead = actor[:80] or lead
    budget = rules.money(d.get("movieBudget"), 50e6) or 50e6
    return {"id": c["id"], "title": c["title"], "text": c["text"].format(lead=lead),
            "options": [{"id": oid, "label": label, "cost": round(budget * cost, -4)}
                        for oid, label, cost, _, _ in c["options"]]}


def resolve_crisis(crisis_id: str, option_id: str, movie_budget) -> dict | None:
    """The chosen option's effect: cost, score delta and the note the critics get. None for an unknown choice."""
    c = next((x for x in CRISES if x["id"] == crisis_id), None)
    o = next((o for o in (c or {}).get("options", []) if o[0] == option_id), None)
    if not c or not o:
        return None
    budget = rules.money(movie_budget, 50e6) or 50e6
    return {"crisis": c["title"], "choice": o[1], "cost": round(budget * o[2], -4), "score_delta": o[3], "note": o[4]}


# ── achievements ───────────────────────────────────────────────────────────────────────────────────────────────
ACHIEVEMENTS = {
    "first_picture": ("First Picture", "Release your first movie"),
    "blockbuster": ("Blockbuster", "Gross over $1 billion"),
    "critics_darling": ("Critics' Darling", "Score 90 or higher"),
    "razzie": ("Razzie Night", "Score under 20"),
    "two_thumbs": ("Two Thumbs Up", "Both Siskel and Ebert give a thumbs up"),
    "under_budget": ("Under Budget", "Finish a picture without going over the casting budget"),
    "no_names": ("Nobody You've Heard Of", "Cast every role with a no-name and still score 60+"),
    "maverick": ("Maverick", "Overrule your advisors three times in one picture"),
    "crisis_manager": ("Crisis Manager", "Turn a production crisis into a better picture"),
}


def earned(d: dict, results: dict) -> list:
    """Achievement keys this release earns (the caller stores the new ones)."""
    score = float(results.get("overallGameScore") or 0)
    out = ["first_picture"]
    if float(results.get("boxOffice") or 0) >= 1e9:
        out.append("blockbuster")
    if score >= 90:
        out.append("critics_darling")
    if score < 20:
        out.append("razzie")
    if results.get("siskelVerdict") == "thumbs_up" and results.get("ebertVerdict") == "thumbs_up":
        out.append("two_thumbs")
    if str(d.get("wentOverBudget")).lower() not in ("true", "yes", "1"):
        out.append("under_budget")
    cast = [c for c in str(d.get("castDetails") or "").splitlines() if c.strip()]
    if cast and all("no-name" in c.lower() for c in cast) and score >= 60:
        out.append("no_names")
    if int(d.get("overrules") or 0) >= 3:
        out.append("maverick")
    if int((d.get("production") or {}).get("score_delta") or 0) > 0:
        out.append("crisis_manager")
    return out
