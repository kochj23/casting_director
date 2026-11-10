/**
 * Nova Service
 * The Nova edition's storage: the local server (nova/server.py) and the Nova Games DB, in place of Firebase.
 * Same exports as firebaseService.js, so the screens don't care which edition they run in.
 */

import { setFirebaseInstances, getState, getUserId } from './stateService.js';
import { buildMovieRecord } from '../game/movieRecord.js';

/**
 * POST/PUT JSON to the local server; throws with the server's error text.
 * @param {string} path
 * @param {object} body
 * @param {object} [options] - { method, signal }
 */
export async function novaFetch(path, body, options = {}) {
    const response = await fetch(path, {
        method: options.method || (body === undefined ? 'GET' : 'POST'),
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: options.signal
    });
    if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try { message = (await response.json()).error || message; } catch { /* not JSON */ }
        throw new Error(message);
    }
    return response.json();
}

/**
 * Starts the Nova edition: no login screen (the director is this Mac's player), then the normal flow.
 * @param {function} onAuthSuccess - Called like Firebase's auth callback
 */
export async function initNova(onAuthSuccess) {
    const edition = await novaFetch('/api/edition');
    setFirebaseInstances(null, null, null, edition.player);
    document.getElementById('login-screen')?.classList.remove('active');
    const who = document.getElementById('user-id-display');
    if (who) who.textContent = 'Director: Little Mister';
    (await import('../ui/novaSettings.js')).mountNovaHeader();
    if (onAuthSuccess) await onAuthSuccess({ uid: edition.player });
    return edition;
}

export async function saveMovie(results) {
    const state = getState();
    const record = buildMovieRecord(results, state, getUserId());
    record.studio = state.bookInfo?.studio || null;
    record.edition = 'nova';
    const { id } = await novaFetch('/api/movies', record);
    return id;
}

export async function loadRecentMovies() {
    try {
        return (await novaFetch('/api/movies/recent')).movies || [];
    } catch (error) {
        console.error('Error loading recent movies:', error);
        return [];
    }
}

export async function getMovieById(movieId) {
    try {
        return await novaFetch(`/api/movies/${encodeURIComponent(movieId)}`);
    } catch {
        return null;
    }
}

export { displayRecentMovies } from '../ui/recentMovies.js';
