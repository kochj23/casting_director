/**
 * Recent Movies list (shared by both editions; moved out of firebaseService.js unchanged)
 */

import { formatCurrency } from '../utils/formatters.js';

/**
 * Displays recent movies in the list element
 * @param {Array} movies - Array of movie objects
 * @param {HTMLElement} listElement - The UL element to populate
 * @param {function} onMovieClick - Callback when a movie is clicked
 */
export function displayRecentMovies(movies, listElement, onMovieClick) {
    if (!movies || movies.length === 0) {
        listElement.innerHTML = '<li>No movies cast yet. Be the first!</li>';
        return;
    }

    listElement.innerHTML = movies.map(movie => {
        const boxOffice = formatCurrency(movie.boxOffice || 0);
        const directorShort = movie.directorId ? movie.directorId.substring(0, 8) : 'unknown';

        return `<li data-movie-id="${movie.id}">
            <strong>${movie.bookName}</strong> by ${movie.author}<br>
            Director: ${directorShort} | Box Office: ${boxOffice}
        </li>`;
    }).join('');

    // Add click handlers
    if (onMovieClick) {
        listElement.querySelectorAll('li[data-movie-id]').forEach(li => {
            li.addEventListener('click', () => {
                onMovieClick(li.dataset.movieId);
            });
        });
    }
}
