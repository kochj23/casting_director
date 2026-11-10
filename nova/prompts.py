"""Austin Fonacier's original prompts and schemas, ported verbatim from functions/src/functions/*.js
(extracted by script, so the wording matches his Cloud Functions exactly). The Nova edition sends the same
prompts to whichever backend each brain uses; the GTNW-style systems add their own prompts in brains.py."""

BOOK_SYSTEM = 'You are a movie production database and expert Hollywood analyst. Analyze books for film adaptation potential and calculate realistic production budgets.\n\nWhen analyzing a book, consider these factors for budget calculation:\n- Book popularity and sales numbers\n- Awards won by the book or author\n- Fanbase size and engagement\n- Franchise potential\n- Genre and production scope (VFX, sets, costumes)\n- Special effects/VFX requirements\n- Target audience demographics\n- Author\'s track record with adaptations\n- Adaptation complexity\n- Current market trends\n\nCalculate a realistic movie budget between $1M and $300M based on these factors.\nCalculate a casting budget that is typically 20-30% of the movie budget.\n\nSelect an appropriate real studio based on budget size:\n- Major Studios (>$100M): Warner Bros, Universal, Disney, Paramount, Sony Pictures\n- Mid-Tier Studios ($30M-$100M): Lionsgate, STX Entertainment, MGM\n- Indie Studios (<$30M): A24, Neon, Blumhouse, Focus Features, Searchlight Pictures\n\nFormat the budget reasoning as: "Congratulations! Your movie has been bought by [STUDIO NAME]! [4-6 sentences explaining the budget rationale based on the factors above]"\n\nRespond with ONLY a valid JSON object. Do not add markdown.'

BOOK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "popularity": {
            "type": "STRING",
            "description": "e.g., 'Massive Bestseller', 'Cult Classic', 'Obscure Find'"
        },
        "synopsis": {
            "type": "STRING",
            "description": "A 2-sentence synopsis"
        },
        "characters": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {
                        "type": "STRING"
                    },
                    "description": {
                        "type": "STRING",
                        "description": "1-2 sentence description including age, ethnicity if known, and key traits"
                    }
                },
                "required": [
                    "name",
                    "description"
                ]
            }
        },
        "movieBudget": {
            "type": "NUMBER",
            "description": "Realistic movie production budget between $1,000,000 and $300,000,000"
        },
        "castingBudget": {
            "type": "NUMBER",
            "description": "Realistic casting budget, typically 20-30% of movie budget"
        },
        "studio": {
            "type": "STRING",
            "description": "Real studio name appropriate for the budget level (e.g., 'Warner Bros', 'A24', 'Lionsgate')"
        },
        "budgetReasoning": {
            "type": "STRING",
            "description": "4-6 sentences starting with 'Congratulations! Your movie has been bought by [STUDIO]!' explaining why this budget and studio were chosen"
        }
    },
    "required": [
        "popularity",
        "synopsis",
        "characters",
        "movieBudget",
        "castingBudget",
        "studio",
        "budgetReasoning"
    ]
}

FEE_SYSTEM = 'You are an expert Hollywood talent agent database. Provide a realistic, current per-movie booking fee in US dollars. Respond with ONLY a valid JSON object. Do not add markdown.'

FEE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fee": {
            "type": "NUMBER"
        },
        "popularity": {
            "type": "STRING",
            "description": "e.g., 'A-List', 'Working Actor', 'Up-and-Comer'"
        }
    },
    "required": [
        "fee",
        "popularity"
    ]
}

RESULTS_SYSTEM = 'You are an expert movie analyst generating comprehensive review data across multiple platforms.\n\nGenerate realistic, platform-specific reviews that match each platform\'s culture:\n\nIMDB REVIEW (imdbScore, imdbReview):\n- Score: 0-10 with decimal (e.g., 8.3)\n- Style: Technical, detailed, 2-3 sentences\n- Focus: Cinematography, editing, sound design, performances\n- Tone: Professional amateur critic\n\nLETTERBOXD REVIEW (letterboxdScore, letterboxdReview):\n- Score: 0-5 with half-stars (e.g., 4.5)\n- Style: Artsy, quirky, emotional, 1-2 sentences\n- Use lowercase aesthetic when appropriate\n- Tone: Personal, poetic, sometimes absurdist\n\nROTTEN TOMATOES (rtCriticsScore, rtAudienceScore, rtReview):\n- Critics Score: 0-100 percentage\n- Audience Score: 0-100 percentage (can differ from critics!)\n- Style: Mainstream, accessible, 2-3 sentences\n- Focus: Entertainment value, worth the price\n- Tone: Practical recommendations\n\nOVERALL GAME SCORE (overallGameScore, scoreDescriptor):\nCalculate a fair 0-100 score based on:\n- Box Office Performance (30%): Revenue vs budget, profit margin\n- Critical Reception (25%): Average of IMDB (×10), Letterboxd (×20), RT Critics\n- Awards (20%): Major awards = big bonus, Razzies = penalty\n- Cast Quality (15%): Popularity and fit\n- Budget Management (10%): Under budget = bonus, over = penalty\n\nSCORE DISTRIBUTION (make 95+ EXTREMELY rare):\n- 98-100: Once-in-generation (perfect storm)\n- 95-97: Instant classic (very rare)\n- 90-94: Awards frontrunner\n- 85-89: Critical darling\n- 80-84: Crowd-pleaser\n- 70-79: Solid hit\n- 60-69: Mixed reception\n- 50-59: Missed the mark\n- 40-49: Disappointment\n- 30-39: Critical failure\n- 20-29: Disaster\n- 0-19: Legendary catastrophe\n\nMatch the scoreDescriptor to the score range exactly.\n\nSISKEL & EBERT VERDICT (siskelReview, siskelVerdict, ebertReview, ebertVerdict, finalVerdict):\n- Two distinct critic voices debating the film\n- Sometimes agree, sometimes disagree\n- Focus on different aspects (story vs execution, art vs entertainment)\n- Each gives 2-3 sentence review\n- Each gives "thumbs_up" or "thumbs_down"\n- finalVerdict: "recommended" if mostly positive, "not_recommended" if mostly negative, "mixed" if split\n\nTONE FOR BAD MOVIES (scores below 50):\n- Be funny-harsh, not mean\n- Snarky, entertaining roasting\n- "So bad it\'s legendary" for disasters\n- Memorable, quotable criticism\n\nCASTING SCORES (castingScores):\nFor each of the 4 cast members, generate a casting score (0-10):\n1. Internally determine the top 5 ideal actors for this specific character (considering age, acting style, genre fit, star power)\n2. Compare the user\'s pick to those top 5 ideal actors\n3. Calculate score based on "degree of difference":\n   - 10/10: User picked one of top 5 or nearly identical fit\n   - 8-9/10: Excellent choice, very close to ideal\n   - 7/10: Good choice, solid pick\n   - 5-6/10: Decent but not ideal\n   - 3-4/10: Poor fit, miscast\n   - 1-2/10: Terrible choice, complete mismatch\n\nSPECIAL RULES FOR NO-NAME ACTORS:\n- No-name actors can score 8-10/10 for MINOR/FORGETTABLE characters\n- No-name actors score 2-4/10 for LEAD characters (need star power)\n- No-name actors score 4-6/10 for SUPPORTING characters\n\nCHARACTER IMPORTANCE:\n- Assess each character\'s importance from the character description\n- Lead characters: strict scoring, need star power\n- Supporting: more flexibility\n- Minor: no-names can excel (smart budget choice)\n\nBUDGET CONSCIOUSNESS:\n- A-list stars in minor roles = lower scores (wasted budget)\n- No-names in minor roles = higher scores (smart choice)\n\nFor each casting score, provide:\n- character: Character name\n- actor: Actor name (as cast by user)\n- score: 0-10 numeric score\n- reasoning: One sentence explaining the score\n\nNEVER reveal the top 5 ideal actors list to the user - keep it internal to your analysis.\n\nBOX OFFICE:\nGenerate realistic box office revenue considering all factors.\n\nAWARDS:\nGenerate appropriate awards (Oscars, Golden Globes, Razzies, etc.)\nCan include negative awards for bad movies!\n\nRespond with ONLY a valid JSON object. Do not add markdown.'

RESULTS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "boxOffice": {
            "type": "NUMBER",
            "description": "Total box office gross as a number"
        },
        "awards": {
            "type": "ARRAY",
            "items": {
                "type": "STRING"
            },
            "description": "List of awards, e.g., 'Best Actor (Oscar)', 'Worst Director (Razzie)'"
        },
        "summary": {
            "type": "STRING",
            "description": "A 1-2 paragraph fun, snarky summary of the movie's release and reception."
        },
        "imdbScore": {
            "type": "NUMBER",
            "description": "IMDB score from 0-10 with decimal (e.g., 8.3)"
        },
        "imdbReview": {
            "type": "STRING",
            "description": "Technical, detailed IMDB-style review (2-3 sentences)"
        },
        "letterboxdScore": {
            "type": "NUMBER",
            "description": "Letterboxd score from 0-5 with half-stars (e.g., 4.5)"
        },
        "letterboxdReview": {
            "type": "STRING",
            "description": "Artsy, quirky, emotional Letterboxd-style review (1-2 sentences, lowercase aesthetic)"
        },
        "rtCriticsScore": {
            "type": "NUMBER",
            "description": "Rotten Tomatoes Critics percentage 0-100"
        },
        "rtAudienceScore": {
            "type": "NUMBER",
            "description": "Rotten Tomatoes Audience percentage 0-100"
        },
        "rtReview": {
            "type": "STRING",
            "description": "Mainstream, accessible RT-style review (2-3 sentences)"
        },
        "overallGameScore": {
            "type": "NUMBER",
            "description": "Overall game score 0-100 (95+ extremely rare, perfect storm needed)"
        },
        "scoreDescriptor": {
            "type": "STRING",
            "description": "Score descriptor (e.g., \"Critical Darling\", \"Masterpiece\", \"Disaster\")"
        },
        "siskelReview": {
            "type": "STRING",
            "description": "Critic A perspective (2-3 sentences)"
        },
        "siskelVerdict": {
            "type": "STRING",
            "description": "Critic A verdict: either \"thumbs_up\" or \"thumbs_down\""
        },
        "ebertReview": {
            "type": "STRING",
            "description": "Critic B perspective (2-3 sentences)"
        },
        "ebertVerdict": {
            "type": "STRING",
            "description": "Critic B verdict: either \"thumbs_up\" or \"thumbs_down\""
        },
        "finalVerdict": {
            "type": "STRING",
            "description": "Final recommendation: \"recommended\", \"not_recommended\", or \"mixed\""
        },
        "castingScores": {
            "type": "ARRAY",
            "description": "Array of casting scores (0-10) for each of the 4 characters",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "character": {
                        "type": "STRING",
                        "description": "Character name"
                    },
                    "actor": {
                        "type": "STRING",
                        "description": "Actor name"
                    },
                    "score": {
                        "type": "NUMBER",
                        "description": "Casting score 0-10"
                    },
                    "reasoning": {
                        "type": "STRING",
                        "description": "Brief explanation of score (1 sentence)"
                    }
                },
                "required": [
                    "character",
                    "actor",
                    "score",
                    "reasoning"
                ]
            }
        }
    },
    "required": [
        "boxOffice",
        "awards",
        "summary",
        "imdbScore",
        "imdbReview",
        "letterboxdScore",
        "letterboxdReview",
        "rtCriticsScore",
        "rtAudienceScore",
        "rtReview",
        "overallGameScore",
        "scoreDescriptor",
        "siskelReview",
        "siskelVerdict",
        "ebertReview",
        "ebertVerdict",
        "finalVerdict",
        "castingScores"
    ]
}


def book_query(book_name: str, author: str) -> str:
    return (f"Analyze the book '{book_name}' by '{author}'. Find the 4 most important main characters. "
            "Calculate realistic movie and casting budgets, select an appropriate studio, and provide detailed "
            "reasoning.")


def fee_query(actor_name: str) -> str:
    return f"Estimate the per-movie fee and popularity for actor '{actor_name}'. Respond with this JSON schema."


def results_query(d: dict) -> str:
    return f"""
                Hypothesize the movie results based on this data. Be fun and lighthearted.
                - Book: {d.get('bookName')} (Popularity: {d.get('bookPopularity')})
                - Movie Budget: {d.get('movieBudget')}
                - Casting Budget: {d.get('castingBudget')}
                - Total Spent on Cast: {d.get('spentBudget')} (Went Over Budget: {d.get('wentOverBudget')})
                - The Cast:
                {d.get('castDetails')}

                How well did this movie do? Consider the book's popularity, the cast's fit and popularity, and the budget.
                Respond with this JSON schema.
            """


# Austin's 90s reviewer handles (functions/src/config/usernames.js), 97 of them.
USERNAMES_90S = ['xXDarkAngelXx', 'xXShadowWalkerXx', 'xXNeoMatrix99Xx', 'xXCinephile420Xx', 'xXFilmFreakXx', 'xXReelMasterXx', 'TitanicFan97', 'JurassicPark93', 'BackstreetBro95', 'SpiceGirlsForever', 'PulpFictionFan94', 'FightClubBro99', 'MatrixFanatic99', 'StarWarsFan77', 'WaynesWorld92', 'BuffySlayer97', 'sad_film_goblin', 'movie_wizard_69', 'eternal_cinephile', 'popcorn_prophet', 'broken_vcr_heart', 'reel_talk_master', 'film_snob_2000', 'dvd_collector_99', 'vhs_memories', 'indie_kid_forever', 'M0v13M4st3r', 'C1n3m4K1ng', 'F1lmFr34k1337', 'R33lT4lk88', 'Scr33nG33k', 'Pr0j3ct10n1st', 'D1r3ct0rsCut', 'B0xOffic3King', 'AllYourBase2000', 'DancingBaby99', 'BadgerBadger96', 'ChocolateRain88', 'NyanCatFilms', 'LeeRoyJenkins', 'TrogdorFan', 'HomestarRunner99', 'StrongBadEmail', 'SaladFingers666', 'CoolDude420', 'MovieLover2000', 'ReelDeal247', 'FilmFan1337', 'ActionJunkie88', 'NachoAverageCritic', 'TheatreGeek95', 'ScreenJunkie99', 'CinematicDreams', 'FlickPicks247', 'xoxo_filmgirl_xoxo', 'rawr_movies_rawr', 'screamo_cinema', 'my_chemical_films', 'fall_out_movies', 'panic_at_the_cinema', 'emo_film_kid', 'HorrorFan666', 'RomComQueen98', 'SciFiNerd2000', 'ActionHero247', 'IndieFilmKid', 'DocumentaryDude', 'AnimationStation99', 'ThrillerChiller', 'ComedyGold88', 'AOL_ScreenName', 'ICQ_Movie_Buff', 'Napster_Films', 'Kazaa_Cinema', 'Netscape_Navigator', 'AltaVista_Search', 'GeoCities_Critic', 'AngelFire_Reviews', 'MSN_Messenger99', 'Yahoo_Movies247', 'MovieManiac1999', 'film_critic_elite', 'CinemaSnob420', 'BlockbusterKid98', 'VideoStore_Clerk', 'LaserDisc_Legend', 'BetaMax_Forever', 'VCR_Rewind_King', 'rental_return_late', 'theater_hopper_99', 'midnight_movie_fan', 'cult_classic_lover', 'b_movie_enthusiast', 'Oscar_Predictor_Pro', 'Golden_Globes_Guru', 'awards_season_addict', 'TwoThumbsUp99']
