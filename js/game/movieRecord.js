/**
 * Movie Record
 * The saved shape of a finished movie, shared by both editions (moved out of firebaseService.saveMovie unchanged).
 */

/**
 * @param {object} results - The movie results from the AI (boxOffice, awards, summary, reviews, scores)
 * @param {object} state - Game state (bookName, author, bookInfo, movieBudget, castList)
 * @param {string} userId - The director's id
 * @returns {object} The record to store
 */
export function buildMovieRecord(results, state, userId) {
    return {
        directorId: userId,
        bookName: state.bookName,
        author: state.author,
        bookPopularity: state.bookInfo.popularity,
        movieBudget: state.movieBudget,
        castList: state.castList,           // Array of cast objects
        boxOffice: results.boxOffice,
        awards: results.awards || [],       // Array of award strings
        summary: results.summary,

        // Platform reviews
        imdbScore: results.imdbScore,
        imdbReview: results.imdbReview,
        imdbUsername: results.imdbUsername,
        letterboxdScore: results.letterboxdScore,
        letterboxdReview: results.letterboxdReview,
        letterboxdUsername: results.letterboxdUsername,
        rtCriticsScore: results.rtCriticsScore,
        rtAudienceScore: results.rtAudienceScore,
        rtReview: results.rtReview,
        rtUsername: results.rtUsername,

        // Overall game score
        overallGameScore: results.overallGameScore,
        scoreDescriptor: results.scoreDescriptor,

        // Siskel & Ebert verdict
        siskelReview: results.siskelReview,
        siskelVerdict: results.siskelVerdict,
        ebertReview: results.ebertReview,
        ebertVerdict: results.ebertVerdict,
        finalVerdict: results.finalVerdict,

        // Individual casting scores
        castingScores: results.castingScores || [],

        version: 2,  // Version for backward compatibility
        createdAt: new Date().toISOString()
    };
}
