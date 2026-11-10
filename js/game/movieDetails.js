/**
 * Movie Details
 * Handles the movie details screen (screen5) display and deep linking
 */

import { getMovieById } from '../services/storeService.js';
import { showScreen, showLoading } from '../ui/screenManager.js';
import { showModal } from '../ui/modalManager.js';
import { formatCurrency, formatLetterboxdStars, generateThumbIcon } from '../utils/formatters.js';
import { getVerdictDisplay } from './movieResults.js';

/**
 * Show movie details screen for a specific movie
 * @param {string} movieId - The Firestore document ID of the movie
 * @param {boolean} updateUrl - Whether to update the browser URL (default: true)
 */
export async function showMovieDetails(movieId, updateUrl = true) {
    showLoading(true);

    try {
        const movieData = await getMovieById(movieId);

        if (!movieData) {
            showModal("Movie not found.");
            showLoading(false);
            return;
        }

        // Store for sharing
        currentMovieId = movieId;
        currentMovieData = movieData;

        populateMovieDetails(movieData);
        updateShareUrl();
        showScreen('screen5');

        // Update URL with movie ID for deep linking
        if (updateUrl) {
            const newUrl = new URL(window.location);
            newUrl.searchParams.set('movieId', movieId);
            window.history.pushState({ movieId }, '', newUrl);
        }

        showLoading(false);
    } catch (error) {
        console.error("Error loading movie details:", error);
        showModal("Error: Could not load movie details. Check console.");
        showLoading(false);
    }
}

/**
 * Populates Screen 5 with movie details from database
 * @param {object} movieData - Movie data from Firestore
 */
export function populateMovieDetails(movieData) {
    // Basic info
    setElementText('detail-project-title', movieData.bookName);
    setElementText('detail-director',
        movieData.directorId ? movieData.directorId.substring(0, 12) + '...' : 'Unknown');
    setElementText('detail-movie-budget', formatCurrency(movieData.movieBudget));
    setElementText('detail-box-office', formatCurrency(movieData.boxOffice));

    // Profit/loss
    const profit = movieData.boxOffice - movieData.movieBudget;
    const profitElement = document.getElementById('detail-profit-loss');
    if (profitElement) {
        profitElement.textContent = `Profit: ${formatCurrency(profit)}`;
        profitElement.style.color = profit >= 0 ? 'var(--dos-green)' : 'var(--dos-error)';
    }

    // Overall Game Score
    setElementText('detail-overall-score', movieData.overallGameScore);
    setElementText('detail-score-descriptor', movieData.scoreDescriptor);

    // IMDB Review
    setElementText('detail-imdb-score', `${movieData.imdbScore} / 10`);
    setElementText('detail-imdb-review', movieData.imdbReview);
    setElementText('detail-imdb-username', `- ${movieData.imdbUsername}`);

    // Letterboxd Review
    const letterboxdStars = formatLetterboxdStars(movieData.letterboxdScore);
    setElementText('detail-letterboxd-score', `${letterboxdStars} (${movieData.letterboxdScore} / 5)`);
    setElementText('detail-letterboxd-review', movieData.letterboxdReview);
    setElementText('detail-letterboxd-username', `- ${movieData.letterboxdUsername}`);

    // Rotten Tomatoes Review
    const rtCriticsElement = document.getElementById('detail-rt-critics');
    if (rtCriticsElement) {
        rtCriticsElement.textContent = `Critics: ${movieData.rtCriticsScore}%`;
        rtCriticsElement.className = movieData.rtCriticsScore >= 60 ? 'rt-fresh' : 'rt-rotten';
    }

    const rtAudienceElement = document.getElementById('detail-rt-audience');
    if (rtAudienceElement) {
        rtAudienceElement.textContent = `Audience: ${movieData.rtAudienceScore}%`;
        rtAudienceElement.className = movieData.rtAudienceScore >= 60 ? 'rt-fresh' : 'rt-rotten';
    }

    setElementText('detail-rt-review', movieData.rtReview);
    setElementText('detail-rt-username', `- ${movieData.rtUsername}`);

    // Siskel & Ebert Verdict
    setElementText('detail-siskel-review', movieData.siskelReview);
    setElementText('detail-siskel-verdict', generateThumbIcon(movieData.siskelVerdict));
    setElementText('detail-ebert-review', movieData.ebertReview);
    setElementText('detail-ebert-verdict', generateThumbIcon(movieData.ebertVerdict));

    // Final verdict
    const verdictDisplay = getVerdictDisplay(movieData.finalVerdict);
    const finalVerdictElement = document.getElementById('detail-final-verdict');
    if (finalVerdictElement) {
        finalVerdictElement.textContent = verdictDisplay.text;
        finalVerdictElement.className = verdictDisplay.className;
    }

    // Awards
    const awardsList = document.getElementById('detail-awards');
    if (awardsList) {
        if (movieData.awards && movieData.awards.length > 0) {
            awardsList.innerHTML = movieData.awards.map(award => `<li>• ${award}</li>`).join('');
        } else {
            awardsList.innerHTML = '<li>None. Not even a nomination. Ouch.</li>';
        }
    }

    // Cast list with casting scores
    const castListElement = document.getElementById('detail-cast-list');
    if (castListElement) {
        if (movieData.castingScores && movieData.castingScores.length > 0) {
            castListElement.innerHTML = movieData.castingScores.map((castScore, index) => {
                const scoreEmoji = castScore.score >= 8 ? ' ⭐' : '';
                // Fallback to castList if API values are undefined
                const actor = castScore.actor || (movieData.castList && movieData.castList[index] ? movieData.castList[index].actor : 'Unknown');
                const character = castScore.character || (movieData.castList && movieData.castList[index] ? movieData.castList[index].character : 'Unknown');
                const score = castScore.score !== undefined ? castScore.score : 0;
                return `<li>${character}: ${actor} - ${score}/10${scoreEmoji}<br/><span style="color: var(--dos-gray); font-size: 14px;">${castScore.reasoning || ''}</span></li>`;
            }).join('');
        } else {
            castListElement.innerHTML = '<li>No cast information available.</li>';
        }
    }
}

/**
 * Helper function to safely set element text content
 * @param {string} id - Element ID
 * @param {string} text - Text content to set
 */
function setElementText(id, text) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = text;
    }
}

// Store current movie data for sharing
let currentMovieData = null;
let currentMovieId = null;

/**
 * Initialize movie details event listeners
 */
export function initMovieDetails() {
    const backButton = document.getElementById('back-to-main-from-details');
    if (backButton) {
        backButton.addEventListener('click', () => {
            // Clear movieId from URL when going back to main
            const newUrl = new URL(window.location);
            newUrl.searchParams.delete('movieId');
            window.history.pushState({}, '', newUrl);
            showScreen('screen1');
        });
    }

    // Copy link button
    const copyButton = document.getElementById('copy-share-btn');
    if (copyButton) {
        copyButton.addEventListener('click', handleCopyLink);
    }
}

/**
 * Update the share URL input field
 */
function updateShareUrl() {
    const shareUrlInput = document.getElementById('share-url');
    const confirmation = document.getElementById('copy-confirmation');

    if (shareUrlInput && currentMovieId) {
        const shareUrl = `${window.location.origin}${window.location.pathname}?movieId=${currentMovieId}`;
        shareUrlInput.value = shareUrl;
    }

    // Hide confirmation when loading new movie
    if (confirmation) {
        confirmation.classList.remove('visible');
    }
}

/**
 * Handle copying the share link
 */
async function handleCopyLink() {
    const shareUrlInput = document.getElementById('share-url');
    const confirmation = document.getElementById('copy-confirmation');

    if (!shareUrlInput || !shareUrlInput.value) {
        return;
    }

    try {
        await navigator.clipboard.writeText(shareUrlInput.value);

        // Show confirmation
        if (confirmation) {
            confirmation.classList.add('visible');

            // Hide after 3 seconds
            setTimeout(() => {
                confirmation.classList.remove('visible');
            }, 3000);
        }
    } catch (error) {
        // Fallback: select the text
        shareUrlInput.select();
        document.execCommand('copy');

        if (confirmation) {
            confirmation.classList.add('visible');
            setTimeout(() => {
                confirmation.classList.remove('visible');
            }, 3000);
        }
    }
}

/**
 * Check URL for movie deep link and show movie if present
 * @returns {string|null} Movie ID if found, null otherwise
 */
export function checkDeepLink() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('movieId');
}
