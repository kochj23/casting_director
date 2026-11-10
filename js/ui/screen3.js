/**
 * Screen 3 - Casting Screen
 * Handles character casting interface and movie production
 */

import { getState, getBookInfo, getCastList, getCastingBudget } from '../services/stateService.js';
import { callGenerateMovieResults } from '../services/apiService.js';
import { saveMovie } from '../services/storeService.js';
import { formatCurrency } from '../utils/formatters.js';
import { showScreen, showLoading } from './screenManager.js';
import { showModal } from './modalManager.js';
import { handleCastActor, castNoNameActor, clearCast, updateCastInfoDisplay, updateSpentBudgetDisplay, calculateSpentBudget, allRolesCast, isOverBudget } from '../game/castingLogic.js';
import { populateScreen4 } from './screen4.js';
import { refreshRecentMovies } from './screen1.js';

/**
 * Populate Screen 3 with character cards
 */
export function populateScreen3() {
    const state = getState();

    document.getElementById('total-casting-budget').textContent = formatCurrency(state.castingBudget);
    updateSpentBudgetDisplay();

    const characterList = document.getElementById('character-list');
    characterList.innerHTML = "";

    // Create character cards
    state.bookInfo.characters.forEach((char, index) => {
        const card = document.createElement('div');
        card.className = 'character-card';
        card.innerHTML = `
            <h4>${char.name}</h4>
            <p>${char.description}</p>
            <div class="casting-input-group" id="casting-group-${index}">
                <label for="actor-name-${index}">Actor:</label>
                <input type="text" id="actor-name-${index}" data-index="${index}">
                <button class="cast-button" data-index="${index}">CAST</button>
            </div>
            <div class="checkbox-container">
                <input type="checkbox" id="no-name-${index}" data-index="${index}">
                <label for="no-name-${index}">Go "No-Name" ($100,000)</label>
            </div>
            <div id="cast-info-${index}" class="cast-info"></div>
        `;
        characterList.appendChild(card);
    });

    // Event delegation for buttons
    characterList.addEventListener('click', handleCharacterListClick);
    characterList.addEventListener('change', handleNoNameCheckbox);
}

async function handleCharacterListClick(event) {
    if (event.target.classList.contains('cast-button')) {
        const index = parseInt(event.target.dataset.index);
        const actorName = document.getElementById(`actor-name-${index}`).value;
        const castData = await handleCastActor(index, actorName);
        if (castData) {
            updateCastInfoDisplay(index, castData);
            updateSpentBudgetDisplay();
        }
    }

    if (event.target.classList.contains('recast-button')) {
        const index = parseInt(event.target.dataset.index);
        clearCast(index);
        updateCastInfoDisplay(index, null);
        updateSpentBudgetDisplay();
    }
}

function handleNoNameCheckbox(event) {
    if (event.target.matches('.checkbox-container input[type="checkbox"]')) {
        const index = parseInt(event.target.dataset.index);
        const actorNameInput = document.getElementById(`actor-name-${index}`);
        const castButton = document.querySelector(`.cast-button[data-index="${index}"]`);

        if (event.target.checked) {
            actorNameInput.disabled = true;
            actorNameInput.value = "";
            castButton.disabled = true;
            const castData = castNoNameActor(index);
            updateCastInfoDisplay(index, castData);
            updateSpentBudgetDisplay();
        } else {
            actorNameInput.disabled = false;
            castButton.disabled = false;
            clearCast(index);
            updateCastInfoDisplay(index, null);
            updateSpentBudgetDisplay();
        }
    }
}

/**
 * Handle Make Movie button - production and results
 */
async function handleMakeMovie() {
    if (!allRolesCast()) {
        showModal("You must cast all roles before making the movie!");
        return;
    }

    const state = getState();

    // Show Screen 3.5 (Movie Production)
    showScreen('screen3_5');
    const loadingOverlay = document.getElementById('screen3_5-loading');
    const movieMakingImage = document.getElementById('movie-making-image');
    const progressBar = document.getElementById('screen3_5-progress-bar');
    const progressPercent = document.getElementById('screen3_5-progress-percent');

    loadingOverlay.classList.add('active');

    let apiComplete = false;
    let apiResults = null;

    // Image cycling
    const images = ['images/movie_making_1.png', 'images/movie_making_2.png', 'images/movie_making_3.png', 'images/movie_making_4.png'];
    let currentImageIndex = 0;

    const cycleImage = () => {
        if (apiComplete) return;
        movieMakingImage.classList.add('fade-out');
        setTimeout(() => {
            currentImageIndex = (currentImageIndex + 1) % images.length;
            movieMakingImage.src = images[currentImageIndex];
            movieMakingImage.classList.remove('fade-out');
        }, 500);
    };

    const imageCycleInterval = setInterval(cycleImage, 15000);

    // Progress bar
    const totalDuration = 60000;
    const updateInterval = 100;
    const incrementPerUpdate = (100 / (totalDuration / updateInterval));
    let currentProgress = 0;

    const progressInterval = setInterval(() => {
        if (apiComplete) {
            currentProgress = 100;
            progressBar.style.width = '100%';
            progressPercent.textContent = '100';
            clearInterval(progressInterval);
            return;
        }
        currentProgress = Math.min(currentProgress + incrementPerUpdate, 100);
        progressBar.style.width = currentProgress + '%';
        progressPercent.textContent = Math.floor(currentProgress);
        if (currentProgress >= 100) clearInterval(progressInterval);
    }, updateInterval);

    // Format cast details
    const castDetails = state.castList.map((c, index) => {
        const characterInfo = state.bookInfo.characters[index];
        return `${characterInfo.name} (${characterInfo.description}): ${c.actor} (${formatCurrency(c.fee)}) - ${c.popularity}`;
    }).join("\n");

    try {
        const results = await callGenerateMovieResults({
            bookName: state.bookName,
            bookPopularity: state.bookInfo.popularity,
            movieBudget: formatCurrency(state.movieBudget),
            castingBudget: formatCurrency(state.castingBudget),
            spentBudget: formatCurrency(calculateSpentBudget()),
            wentOverBudget: isOverBudget(),
            castDetails: castDetails
        });

        apiResults = results;
        apiComplete = true;
        clearInterval(imageCycleInterval);

        const waitForProgress = () => {
            if (currentProgress >= 100) {
                setTimeout(() => {
                    loadingOverlay.classList.remove('active');
                    populateScreen4(apiResults);
                    showScreen('screen4');
                    saveMovie(apiResults).then(() => refreshRecentMovies()).catch(err => console.warn("Could not save:", err));
                }, 500);
            } else {
                setTimeout(waitForProgress, 100);
            }
        };
        waitForProgress();

    } catch (error) {
        console.error("Failed to make movie:", error);
        clearInterval(imageCycleInterval);
        clearInterval(progressInterval);
        loadingOverlay.classList.remove('active');
        showModal("Error: The studio computers crashed while making the movie. Check console.");
        showScreen('screen3');
    }
}

/**
 * Initialize screen3 event listeners
 */
export function initScreen3() {
    const backButton = document.getElementById('back-to-main-from-cast');
    if (backButton) {
        backButton.addEventListener('click', () => showScreen('screen1'));
    }

    const makeMovieButton = document.getElementById('make-movie');
    if (makeMovieButton) {
        makeMovieButton.addEventListener('click', handleMakeMovie);
    }
}
