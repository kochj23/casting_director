/**
 * Screen 1 - Book Entry Screen
 * Handles book/author input and recent movies display
 */

import { callGetBookInfo } from '../services/apiService.js';
import { loadRecentMovies, displayRecentMovies } from '../services/storeService.js';
import { updateBookInfo, updateBudgets } from '../services/stateService.js';
import { showScreen, showLoading } from './screenManager.js';
import { showModal } from './modalManager.js';
import { populateScreen2 } from './screen2.js';
import { showMovieDetails } from '../game/movieDetails.js';

/**
 * Handle book submission
 */
async function handleSubmitBook() {
    const bookName = document.getElementById('book-name').value;
    const author = document.getElementById('author-name').value;

    if (!bookName || !author) {
        showModal("Please enter both a book and author name.");
        return;
    }

    // Show Screen 1.5 (Incoming Offer) while loading
    showScreen('screen1_5');
    const loadingOverlay = document.getElementById('screen1_5-loading');
    const statusText = document.querySelector('.screen1_5-status-text');
    loadingOverlay.classList.add('active');

    let apiComplete = false;
    let skipWait = false;

    // Allow user to skip the wait
    const screen1_5 = document.getElementById('screen1_5');
    const skipHandler = () => {
        skipWait = true;
        if (apiComplete) {
            loadingOverlay.classList.remove('active');
            showScreen('screen2');
        }
    };
    screen1_5.addEventListener('click', skipHandler, { once: true });

    try {
        const result = await callGetBookInfo(bookName, author);

        updateBookInfo(bookName, author, result);
        updateBudgets(result.movieBudget, result.castingBudget);

        populateScreen2();
        apiComplete = true;

        statusText.innerHTML = 'ANALYSIS COMPLETE<span class="loading-dots"></span>';

        if (skipWait) {
            loadingOverlay.classList.remove('active');
            showScreen('screen2');
        } else {
            await new Promise(resolve => setTimeout(resolve, 2000));
            loadingOverlay.classList.remove('active');
            showScreen('screen2');
        }
    } catch (error) {
        console.error("Failed to get book info:", error);
        loadingOverlay.classList.remove('active');
        showModal("Error: Could not retrieve book information from the studio database. Check console.");
        showScreen('screen1');
    }
}

/**
 * Refresh and display recent movies
 */
export async function refreshRecentMovies() {
    const moviesList = document.getElementById('recent-movies-list');

    try {
        const movies = await loadRecentMovies();
        displayRecentMovies(movies, moviesList, showMovieDetails);
    } catch (error) {
        console.error("Error loading movies:", error);
        moviesList.innerHTML = '<li>Error loading movies. Check console.</li>';
    }
}

/**
 * Initialize screen1 event listeners
 */
export function initScreen1() {
    const submitButton = document.getElementById('submit-book');
    if (submitButton) {
        submitButton.addEventListener('click', handleSubmitBook);
    }

    const refreshButton = document.getElementById('refresh-movies');
    if (refreshButton) {
        refreshButton.addEventListener('click', refreshRecentMovies);
    }

    // Make showMovieDetails globally accessible for onclick handlers
    window.showMovieDetails = showMovieDetails;
}
