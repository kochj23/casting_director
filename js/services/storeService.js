/**
 * Store Service
 * One door to storage for both editions. The Firebase modules are only loaded in the Firebase edition, so the
 * Nova edition never fetches anything from Google.
 */

import { IS_NOVA } from '../config/edition.js';

const backend = () => (IS_NOVA ? import('./novaService.js') : import('./firebaseService.js'));

export async function saveMovie(results) { return (await backend()).saveMovie(results); }
export async function loadRecentMovies() { return (await backend()).loadRecentMovies(); }
export async function getMovieById(movieId) { return (await backend()).getMovieById(movieId); }
export { displayRecentMovies } from '../ui/recentMovies.js';

/**
 * Start the edition's backend: Nova (no login) or Firebase (login screen, Google or guest).
 * @param {function} onAuthSuccess
 */
export async function initBackend(onAuthSuccess) {
    if (IS_NOVA) {
        return (await import('./novaService.js')).initNova(onAuthSuccess);
    }
    const { initFirebase } = await import('./firebaseService.js');
    const { initLoginScreen } = await import('../ui/loginScreen.js');
    const { auth } = initFirebase(onAuthSuccess, false);
    if (auth) {
        initLoginScreen(auth);
    } else {
        console.error('Auth not available for login screen');
    }
    return { auth };
}

/** Hide the login screen in either edition. */
export async function hideLogin() {
    if (IS_NOVA) {
        document.getElementById('login-screen')?.classList.remove('active');
        return;
    }
    (await import('../ui/loginScreen.js')).hideLoginScreen();
}
