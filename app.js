/**
 * CASTING DIRECTOR - Main Application Orchestrator
 *
 * A retro DOS-style movie casting game where players select actors for book adaptations
 * and see how well their movie performs at the box office.
 *
 * This is the main entry point that initializes and coordinates all modules.
 */

// ============================================================================
// MODULE IMPORTS
// ============================================================================

// Config
import { initConstants } from './js/config/constants.js';
import { setRandomDefaultBook } from './js/config/books.js';

// Services
import { initBackend, hideLogin } from './js/services/storeService.js';

// UI Core
import { showScreen, showLoading } from './js/ui/screenManager.js';
import { initModal } from './js/ui/modalManager.js';
import { showWelcomeScreen, hideWelcomeScreen, initWelcomeScreen, clearIntroTimers } from './js/ui/welcomeScreen.js';

// Screens
import { initScreen1, refreshRecentMovies } from './js/ui/screen1.js';
import { initScreen2 } from './js/ui/screen2.js';
import { initScreen3 } from './js/ui/screen3.js';
import { initScreen4 } from './js/ui/screen4.js';

// Game Logic
import { showMovieDetails, initMovieDetails, checkDeepLink } from './js/game/movieDetails.js';

// Utils
import { displayVersion } from './js/utils/helpers.js';

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize all event listeners for screens and UI components
 */
function initializeEventListeners() {
    initModal();
    initWelcomeScreen();
    initScreen1();
    initScreen2();
    initScreen3();
    initScreen4();
    initMovieDetails();
}

// Track if we should show welcome after login
let pendingWelcomeScreen = false;
let pendingMovieId = null;

/**
 * Handle successful Firebase authentication
 * @param {object} user - Firebase user object
 */
async function onAuthSuccess(user) {
    console.log("Auth success, user:", user.uid);

    // Hide login screen
    await hideLogin();

    // Load recent movies after authentication
    await refreshRecentMovies();

    // Show welcome screen if pending (normal flow)
    if (pendingWelcomeScreen) {
        showWelcomeScreen();
        pendingWelcomeScreen = false;
    } else if (pendingMovieId) {
        // Deep link flow - show movie details directly
        showLoading(false);
        await showMovieDetails(pendingMovieId, false);
        pendingMovieId = null;
    } else {
        // Already authenticated on load - just show screen1
        showScreen('screen1');
    }
}

/**
 * Application initialization
 * Runs when the DOM is fully loaded
 */
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize DOM references
    initConstants();

    // Display version
    displayVersion();

    // Check for deep link to a specific movie
    const movieId = checkDeepLink();

    // Determine flow based on deep linking
    if (movieId) {
        // Deep link flow - store movieId and show loading
        pendingMovieId = movieId;
        showLoading(true);
    } else {
        // Normal flow - will show welcome screen after login
        pendingWelcomeScreen = true;
    }

    // Set a random book as default suggestion
    setRandomDefaultBook();

    // Initialize all event listeners
    initializeEventListeners();

    try {
        // Firebase edition: auth + login screen. Nova edition: straight in (see js/services/storeService.js).
        await initBackend(onAuthSuccess);
    } catch (error) {
        console.error("Backend initialization failed:", error);
    }

    // Login screen is shown by default via HTML class
    // User will sign in via Google or Guest, which triggers onAuthSuccess
    // Don't show screen1 yet - it will be shown after welcome screen completes
});
