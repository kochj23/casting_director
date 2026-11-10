/**
 * API Service
 * Handles Cloud Function API calls with Firestore caching
 */

import { CLOUD_FUNCTIONS, appId } from '../config/firebase.js';
import { getDb } from './stateService.js';
import { IS_NOVA } from '../config/edition.js';
import { novaFetch } from './novaService.js';

// Dynamic Firebase imports for browser environment
let doc, getDoc, setDoc, serverTimestamp;

/**
 * Initialize Firebase Firestore functions
 * Must be called before using caching functions
 * @param {object} firestoreFunctions - Object containing doc, getDoc, setDoc, serverTimestamp
 */
export function initFirestoreFunctions(firestoreFunctions) {
    doc = firestoreFunctions.doc;
    getDoc = firestoreFunctions.getDoc;
    setDoc = firestoreFunctions.setDoc;
    serverTimestamp = firestoreFunctions.serverTimestamp;
}

// ============================================================================
// NORMALIZATION FUNCTIONS
// ============================================================================

/**
 * Normalizes book name and author for cache key (lowercase, trimmed)
 * @param {string} bookName - The book title to normalize
 * @param {string} author - The author name to normalize
 * @returns {string} Normalized cache key
 */
export function normalizeBookKey(bookName, author) {
    const normalizedBook = bookName.toLowerCase().trim();
    const normalizedAuthor = author.toLowerCase().trim();
    // Create a unique key by combining book and author
    return `${normalizedAuthor}::${normalizedBook}`;
}

/**
 * Normalizes actor name for cache key (lowercase, trimmed)
 * @param {string} actorName - The actor name to normalize
 * @returns {string} Normalized actor name
 */
export function normalizeActorName(actorName) {
    return actorName.toLowerCase().trim();
}

// ============================================================================
// API CALLS
// ============================================================================

/**
 * Calls the getBookInfo Cloud Function with Firestore caching
 * Checks cache first, then calls API if needed, and caches the result permanently
 * Retrieves book information including popularity, synopsis, and characters
 *
 * @param {string} bookName - The title of the book
 * @param {string} author - The author of the book
 * @returns {Promise<object>} Book information object
 * @throws {Error} If the API call fails
 */
export async function callGetBookInfo(bookName, author) {
    // Nova edition: the local server asks the analyst brain and caches in the Games DB.
    if (IS_NOVA) return novaFetch('/api/getBookInfo', { bookName, author });

    const db = getDb();
    const cacheKey = normalizeBookKey(bookName, author);
    const cacheDocRef = doc(db, `artifacts/${appId}/public/data/bookCache`, cacheKey);

    try {
        // Check cache first
        const cacheDoc = await getDoc(cacheDocRef);

        if (cacheDoc.exists()) {
            console.log(`Cache hit for book: ${bookName} by ${author}`);
            const cachedData = cacheDoc.data();
            // Return cached data immediately - no expiration check (permanent cache)
            return {
                popularity: cachedData.popularity,
                synopsis: cachedData.synopsis,
                characters: cachedData.characters,
                movieBudget: cachedData.movieBudget,
                castingBudget: cachedData.castingBudget,
                studio: cachedData.studio,
                budgetReasoning: cachedData.budgetReasoning
            };
        } else {
            console.log(`Cache miss for book: ${bookName} by ${author}`);
        }
    } catch (cacheError) {
        // If cache check fails, log and continue to API call
        console.warn('Cache check failed, falling back to API:', cacheError);
    }

    // Cache miss - call the API
    const response = await fetch(CLOUD_FUNCTIONS.getBookInfo, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bookName, author })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to get book information');
    }

    const result = await response.json();

    // Cache the result permanently for future lookups
    try {
        await setDoc(cacheDocRef, {
            bookName: bookName, // Store original book name
            author: author, // Store original author name
            popularity: result.popularity,
            synopsis: result.synopsis,
            characters: result.characters,
            movieBudget: result.movieBudget,
            castingBudget: result.castingBudget,
            studio: result.studio,
            budgetReasoning: result.budgetReasoning,
            cachedAt: serverTimestamp(),
            source: 'gemini-api'
        });
        console.log(`Cached book data for: ${bookName} by ${author}`);
    } catch (cacheWriteError) {
        // Log but don't fail if cache write fails
        console.warn('Failed to cache book data:', cacheWriteError);
    }

    return result;
}

/**
 * Calls the getActorFee Cloud Function with Firestore caching
 * Checks cache first, then calls API if needed, and caches the result
 * Estimates an actor's per-movie fee and popularity level
 *
 * @param {string} actorName - The name of the actor
 * @returns {Promise<object>} Object with fee and popularity
 * @throws {Error} If the API call fails
 */
export async function callGetActorFee(actorName) {
    if (IS_NOVA) return novaFetch('/api/getActorFee', { actorName });

    const db = getDb();
    const normalizedName = normalizeActorName(actorName);
    const cacheDocRef = doc(db, `artifacts/${appId}/public/data/actorCache`, normalizedName);

    try {
        // Check cache first
        const cacheDoc = await getDoc(cacheDocRef);

        if (cacheDoc.exists()) {
            const cachedData = cacheDoc.data();

            // Check if cache has expired (30 days)
            const now = Date.now();
            const cachedAt = cachedData.cachedAt?.toMillis() || 0;
            const thirtyDaysInMs = 30 * 24 * 60 * 60 * 1000;

            if (now - cachedAt < thirtyDaysInMs) {
                console.log(`Cache hit for actor: ${actorName}`);
                // Return cached data immediately - no write needed
                return {
                    fee: cachedData.fee,
                    popularity: cachedData.popularity
                };
            } else {
                console.log(`Cache expired for actor: ${actorName}`);
            }
        } else {
            console.log(`Cache miss for actor: ${actorName}`);
        }
    } catch (cacheError) {
        // If cache check fails, log and continue to API call
        console.warn('Cache check failed, falling back to API:', cacheError);
    }

    // Cache miss or expired - call the API
    const response = await fetch(CLOUD_FUNCTIONS.getActorFee, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actorName })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to get actor fee');
    }

    const result = await response.json();

    // Cache the result for future lookups
    try {
        await setDoc(cacheDocRef, {
            actorName: actorName, // Store original name
            fee: result.fee,
            popularity: result.popularity,
            cachedAt: serverTimestamp(),
            source: 'gemini-api'
        });
        console.log(`Cached actor data for: ${actorName}`);
    } catch (cacheWriteError) {
        // Log but don't fail if cache write fails
        console.warn('Failed to cache actor data:', cacheWriteError);
    }

    return result;
}

/**
 * Calls the generateMovieResults Cloud Function
 * Generates box office results, awards, and summary
 *
 * @param {object} movieData - Object containing all movie and cast information
 * @returns {Promise<object>} Object with boxOffice, awards, and summary
 * @throws {Error} If the API call fails
 */
export async function callGenerateMovieResults(movieData) {
    // Create AbortController with 3-minute timeout (Gemini Pro can take 1-2 minutes)
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), IS_NOVA ? 360000 : 180000); // 3 min (Nova: 6, local models)

    try {
        if (IS_NOVA) {
            const result = await novaFetch('/api/generateMovieResults', movieData, { signal: controller.signal });
            clearTimeout(timeoutId);
            return result;
        }
        const response = await fetch(CLOUD_FUNCTIONS.generateMovieResults, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(movieData),
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to generate movie results');
        }

        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            throw new Error('Request timed out after 3 minutes. The AI is taking longer than expected to generate results.');
        }
        throw error;
    }
}
