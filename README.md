> **This is a fork.** Casting Director was created by **[Austin Fonacier](https://github.com/austinrfnd)**
> ([austinrfnd/casting_director](https://github.com/austinrfnd/casting_director)). The game, its design, its
> prompts, its art and its 90s soul are his. This fork adds a **Nova edition** that runs on local AI and the Nova
> Games DB; see [docs/NOVA_EDITION.md](docs/NOVA_EDITION.md). The original Firebase edition is unchanged and still
> works exactly as Austin built it. All credit for the game goes to Austin — go star his repo.

# Casting Director C:>

A retro 90s DOS-style game where you play as a Hollywood casting director. Your mission: adapt best-selling books for the big screen and see if your casting choices lead to box office gold or critical disaster!

## About The Game

This app lets you and your friends (or book club!) step into the shoes of a movie executive. You'll be given a book, a budget, and a list of characters. It's your job to cast the movie, manage your budget, and then "MAKE THE MOVIE!" to see a fun, AI-generated summary of how your film performed.

## Features

**Retro DOS Aesthetic:** A fun, pixelated UI straight from the early 90s.

**AI-Powered:** Uses Google's Gemini AI to:
- Analyze real books and authors.
- Generate movie budgets based on the book's popularity.
- Fetch "realistic" (and sometimes hilarious) actor fees.
- Hypothesize your movie's box office and awards results.

**Firebase Integration:**
- Saves all final movie results to a public Firestore database.
- Displays a real-time list of "Recently Cast Movies" from all players.
- Uses anonymous authentication to give each player a unique "Director ID".

## How to Play

1. **Start a Project:** Enter a real book title and author. The AI will analyze it and give you a budget.

2. **Get to Casting:** On the casting screen, you'll see the main characters and their descriptions.

3. **Cast Your Actors:** For each character, you can either:
   - Type in a real actor's name and hit "CAST" to get their AI-generated fee.
   - Check the "No-Name" box for a flat $100,000 fee.
   - "Fire" an actor by hitting the [X] button if they're too expensive.

4. **Make the Movie!:** Once all roles are cast, hit the big button to see your results! Your movie's performance will be saved and shared with other players.

## Technical Implementation

For a comprehensive overview of the codebase architecture, see [Technical Architecture Documentation](requirements/TECHNICAL_ARCHITECTURE.md).

**Cloud Functions Architecture** (Refactored November 2025):
The backend has been refactored into a modular, well-tested structure:
- 3 Cloud Functions (getBookInfo, getActorFee, generateMovieResults)
- Shared services (Gemini API client, cache service)
- Utility modules (helpers, username config)
- **201 comprehensive tests** ensuring reliability

For detailed Cloud Functions documentation, see [functions/README.md](functions/README.md).

### Actor Data Caching System

The game implements a **hybrid caching strategy** using Firebase Firestore to optimize actor lookups:

**Architecture:**
- **Dual-layer caching:** Both frontend (app.js) and backend (Cloud Functions) check the cache before calling the Gemini API
- **Cache-first approach:** Always checks Firestore before making expensive API calls
- **30-day TTL:** Cached data expires after 30 days to ensure accuracy while maximizing cache hits
- **Graceful degradation:** Falls back to API calls if cache operations fail

**Data Flow:**
1. User enters actor name → Frontend normalizes name (lowercase, trimmed)
2. Frontend checks Firestore cache (`/artifacts/{appId}/public/data/actorCache/{actorName}`)
3. If cache hit & not expired: Return data immediately
4. If cache miss/expired: Call Cloud Function API
5. Backend also checks cache (redundancy layer)
6. Backend calls Gemini API and caches result
7. Frontend caches result for future lookups

**Storage Structure:**
```javascript
/artifacts/{appId}/public/data/actorCache/{normalizedActorName}: {
  actorName: "Original Name",
  fee: 15000000,
  popularity: "A-List Star",
  cachedAt: Timestamp,
  source: "gemini-api"
}
```

**Security:**
- Public read access (all users benefit from shared cache)
- Authenticated write access (prevents abuse)
- Immutable entries (no updates or deletes)

**Benefits:**
- ⚡ **10-100x faster** lookups for cached actors
- 💰 **Reduced API costs** (fewer Gemini calls)
- 🌐 **Shared cache** across all users
- 🛡️ **Fault-tolerant** with automatic fallbacks

## Planned Feature Enhancements

1. **Casting Grade & Perfect Match Suggestions:** Add AI-powered feedback on casting choices after "Make the Movie" is clicked. For each role (including no-name actors):
   - Assign a casting grade from 0-100 based on how well the actor fits the character description, their acting range, age appropriateness, and star power relative to the book's popularity
   - Display a "Perfect Cast" section showing 2-3 actors who would have been a 100/100 for each role
   - Provide justification for why each suggested actor would be perfect (e.g., "Daniel Day-Lewis - Perfect age range, method actor known for dramatic roles, Oscar-winning gravitas matches the character's complexity")
   - Benefits: educational feedback, inspiration for future casting, fun "what if" scenarios, deeper engagement with the game

## Running Tests

The project includes an end-to-end (e2e) test suite using Playwright to verify the complete user flow.

### Prerequisites

```bash
npm install
```

### Test Commands

- **Run all tests (headless):**
  ```bash
  npm test
  ```

- **Run tests with browser visible:**
  ```bash
  npm run test:headed
  ```

- **Open Playwright UI for interactive testing:**
  ```bash
  npm run test:ui
  ```

- **Debug tests step-by-step:**
  ```bash
  npm run test:debug
  ```

- **View test report:**
  ```bash
  npm run test:report
  ```

### Test Coverage

**End-to-End Tests** (Playwright):
- Homepage loading and Firebase authentication
- Book entry form validation
- Navigation from Screen 1 (book entry) to Screen 2 (budget reveal)
- Navigation to Screen 3 (casting screen)
- Recent movies display and refresh functionality
- Error handling and API error scenarios

**Cloud Functions Unit Tests** (Jest - 201 tests):
- Run with `npm test` in the `functions/` directory
- Comprehensive coverage of all Cloud Functions, services, and utilities
- Includes retry logic, caching, error handling, and API integration tests
- See [functions/README.md](functions/README.md) for details

## Setup for Deployment

To host this game on your own Firebase account, you only need to edit one file (casting_director_95.html) to add your API keys.

### Create a Firebase Project:

- Go to the Firebase Console and create a new project.
- Enable Firestore (start in test mode) and Authentication (enable "Anonymous" sign-in).
- Go to Hosting and set it up.

### Get Your Firebase Config:

- In your Firebase project, go to Project Settings > General.
- Scroll down to "Your apps" and create a Web app (if you haven't already).
- Firebase will give you a firebaseConfig object. Copy this.

### Get Your Gemini API Key:

- Go to Google AI Studio.
- Create a new API key. Copy this key.

### Paste Keys into the HTML File:

- Open casting_director_95.html.
- Find the const firebaseConfig section (around line 345) and paste your Firebase config object.
- Find the async function makeApiCall (around line 430) and paste your Gemini API key into the const apiKey variable.

### Deploy:

- Install the Firebase CLI.
- Run firebase login.
- Run firebase init and connect it to your project (select Hosting).
- Place the casting_director_95.html file in your public folder (rename it to index.html).
- Run firebase deploy.

Your game is now live and ready to be shared!