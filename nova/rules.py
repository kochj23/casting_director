"""The rules brain: deterministic answers when no AI backend is reachable (GTNW's rule-based AI).

Same input, same output (seeded by a hash of the name), so a book or actor always gets the same numbers.
The game stays playable offline; anything an AI analysed earlier comes from the Games DB cache instead.
"""
import hashlib
import random

STOCK_ROLES = [
    ("The Lead", "The story's protagonist, late 20s to 40s; carries the film and needs real star power."),
    ("The Rival", "The antagonist or foil, any age; a showy part that rewards a strong character actor."),
    ("The Mentor", "An older guide figure, 50s to 70s; a supporting role where gravitas matters more than fame."),
    ("The Wildcard", "A memorable minor character; a smart place for an unknown to steal scenes."),
]
POPULARITY = ["Massive Bestseller", "Bestseller", "Cult Classic", "Book Club Favorite", "Obscure Find"]
STUDIOS = [(100e6, ["Warner Bros", "Universal", "Disney", "Paramount", "Sony Pictures"]),
           (30e6, ["Lionsgate", "STX Entertainment", "MGM"]),
           (0, ["A24", "Neon", "Blumhouse", "Focus Features", "Searchlight Pictures"])]
TIERS = [("A-List", 15e6, 30e6), ("Star", 4e6, 15e6), ("Working Actor", 500e3, 4e6), ("Up-and-Comer", 100e3, 500e3)]
DESCRIPTORS = [(98, "Once-in-a-Generation"), (95, "Instant Classic"), (90, "Awards Frontrunner"),
               (85, "Critical Darling"), (80, "Crowd-Pleaser"), (70, "Solid Hit"), (60, "Mixed Reception"),
               (50, "Missed the Mark"), (40, "Disappointment"), (30, "Critical Failure"), (20, "Disaster"),
               (0, "Legendary Catastrophe")]


def _rng(*parts) -> random.Random:
    seed = hashlib.sha256("|".join(str(p).strip().lower() for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def book_info(book_name: str, author: str) -> dict:
    r = _rng("book", book_name, author)
    pop_i = r.choices(range(5), weights=[3, 4, 2, 2, 1])[0]
    budget = round(r.uniform([120e6, 60e6, 20e6, 25e6, 3e6][pop_i], [300e6, 150e6, 60e6, 80e6, 25e6][pop_i]), -5)
    studio = r.choice(next(s for floor, s in STUDIOS if budget >= floor))
    return {
        "popularity": POPULARITY[pop_i],
        "synopsis": f"{book_name} by {author}, adapted for the screen. (Offline mode: the AI analyst is unavailable, "
                    "so the studio is working from the cover copy.)",
        "characters": [{"name": n, "description": d} for n, d in STOCK_ROLES],
        "movieBudget": budget,
        "castingBudget": round(budget * r.uniform(0.2, 0.3), -4),
        "studio": studio,
        "budgetReasoning": f"Congratulations! Your movie has been bought by {studio}! The book's standing as a "
                           f"{POPULARITY[pop_i].lower()} sets the ceiling, and the studio's accountants did the rest. "
                           "No analyst was reachable, so these are house numbers from the rules engine.",
    }


def actor_fee(actor_name: str) -> dict:
    r = _rng("actor", actor_name)
    tier, lo, hi = TIERS[r.choices(range(4), weights=[1, 2, 4, 3])[0]]
    return {"fee": round(r.uniform(lo, hi), -4), "popularity": tier}


def money(v, default=0.0) -> float:
    """The frontend sends formatted currency ("$28,200,000"); the AI path passes it through as text."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return default


def descriptor(score: float) -> str:
    return next(d for floor, d in DESCRIPTORS if score >= floor)


def movie_results(d: dict) -> dict:
    """Score from the numbers alone: book popularity, budget discipline, star power vs. role."""
    r = _rng("results", d.get("bookName"), d.get("castDetails"))
    pop = str(d.get("bookPopularity") or "")
    base = {"Massive Bestseller": 62, "Bestseller": 56, "Cult Classic": 52, "Book Club Favorite": 50}.get(pop, 45)
    over = str(d.get("wentOverBudget")).lower() in ("true", "yes", "1")
    score = max(5, min(94, base + r.randint(-18, 22) - (12 if over else 0)))
    budget = money(d.get("movieBudget"), 50e6) or 50e6
    box = round(budget * (0.3 + score / 30) * r.uniform(0.7, 1.3), -5)
    up = score >= 55
    cast = [line.strip("-• ").strip() for line in str(d.get("castDetails") or "").splitlines() if line.strip()]
    scores = []
    for line in cast[:8]:
        char, _, actor = line.partition(":")
        scores.append({"character": char.strip()[:80] or "Role", "actor": actor.strip()[:80] or "Unknown",
                       "score": r.randint(3, 9), "reasoning": "Scored by the rules engine (no AI critic available)."})
    return {
        "boxOffice": box,
        "awards": (["Best Picture (Critics' Circle)"] if score >= 85 else []) + (["Worst Picture (Razzie)"]
                                                                               if score < 25 else []),
        "summary": f"{d.get('bookName')} opened to a {'warm' if up else 'chilly'} reception and grossed "
                   f"${box:,.0f}. With no AI critics on duty, the trades ran the numbers instead.",
        "imdbScore": round(score / 10, 1), "imdbReview": "Competently assembled; the numbers speak for themselves.",
        "letterboxdScore": round(score / 20 * 2) / 2, "letterboxdReview": "a movie happened. i was there.",
        "rtCriticsScore": score, "rtAudienceScore": max(0, min(100, score + r.randint(-10, 10))),
        "rtReview": "Worth a matinee." if up else "Wait for streaming.",
        "overallGameScore": score, "scoreDescriptor": descriptor(score),
        "siskelReview": "The adaptation keeps its promises." if up else "It forgets what made the book work.",
        "siskelVerdict": "thumbs_up" if up else "thumbs_down",
        "ebertReview": "The cast earns their paychecks." if score >= 50 else "Expensive faces, empty frames.",
        "ebertVerdict": "thumbs_up" if score >= 50 else "thumbs_down",
        "finalVerdict": "recommended" if score >= 60 else ("mixed" if score >= 45 else "not_recommended"),
        "castingScores": scores,
    }
