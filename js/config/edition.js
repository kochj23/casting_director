/**
 * Edition switch.
 * The Nova edition's server (nova/server.py) adds <meta name="casting-edition" content="nova"> to index.html.
 * Without it this is Austin's original Firebase edition, unchanged.
 */
export const IS_NOVA = typeof document !== 'undefined'
    && !!document.querySelector('meta[name="casting-edition"][content="nova"]');
