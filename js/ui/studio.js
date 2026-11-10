/**
 * Studio (Nova edition, phase 2)
 * The people around the picture, in the GTNW style: three advisors weigh in on every casting with odds you can
 * overrule, a production crisis lands mid-shoot, and achievements pop on the premiere screen.
 * Everything here is text-only DOM (nothing from the server or the player is ever written as HTML).
 */

import { IS_NOVA } from '../config/edition.js';
import { novaFetch } from '../services/novaService.js';
import { getState } from '../services/stateService.js';
import { formatCurrency } from '../utils/formatters.js';

const STANCE = { approve: ['✔', '#33ff66'], caution: ['?', '#ffcc33'], oppose: ['✘', '#ff5555'] };

function el(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (k === 'style') node.style.cssText = v;
        else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v);
    }
    for (const kid of kids) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid ?? '')));
    return node;
}

/** The advisor panel under a character card, after a casting. Calls onRecast when the player backs down. */
export async function showAdvice(index, castData, spentBefore, onRecast) {
    if (!IS_NOVA || !castData) return;
    const state = getState();
    const character = state.bookInfo?.characters?.[index] || {};
    const box = document.getElementById(`advice-${index}`) || document.getElementById(`cast-info-${index}`)
        ?.insertAdjacentElement('afterend', el('div', { id: `advice-${index}`, class: 'studio-advice' }));
    if (!box) return;
    box.textContent = 'THE STUDIO IS CONFERRING…';
    let advice;
    try {
        advice = await novaFetch('/api/advise', {
            bookName: state.bookName || '', character: character.name || `Role ${index + 1}`,
            characterDescription: character.description || '', actorName: castData.actor || 'No-Name',
            fee: castData.fee || 0, popularity: castData.popularity || '', castingBudget: state.castingBudget || 0,
            spentBefore
        });
    } catch {
        box.textContent = '';
        return;
    }
    box.textContent = '';
    box.style.cssText = 'margin-top:6px;padding:6px;border:1px dashed #888;font-size:.85em';
    box.append(el('div', { style: 'margin-bottom:4px' }, `ODDS THIS CASTING WORKS: ${advice.odds}%`));
    for (const a of advice.advisors) {
        const [mark, color] = STANCE[a.stance] || ['·', '#ccc'];
        box.append(el('div', {}, el('span', { style: `color:${color}` }, `${mark} ${a.name}: `), a.line));
    }
    if (advice.opposed > 0) {
        const keep = el('button', { type: 'button', class: 'overrule-button', onclick: async () => {
            keep.disabled = true; back.disabled = true;
            try { await novaFetch('/api/overrule', { character: character.name || '', actorName: castData.actor || '', opposed: advice.opposed }); } catch { /* logged best-effort */ }
            keep.textContent = 'OVERRULED';
        } }, '[OVERRULE THEM]');
        const back = el('button', { type: 'button', onclick: () => { box.textContent = ''; onRecast?.(); } }, '[RECAST]');
        box.append(el('div', { style: 'margin-top:4px' }, keep, ' ', back));
    }
}

/** The mid-shoot crisis. Resolves once the player has chosen (or at once outside the Nova edition / on error). */
export async function runProductionCrisis(castDetails) {
    if (!IS_NOVA) return null;
    const state = getState();
    let crisis;
    try {
        crisis = await novaFetch('/api/production/crisis', {
            bookName: state.bookName || 'Untitled', castDetails, movieBudget: state.movieBudget || 0
        });
    } catch {
        return null;
    }
    return new Promise(resolve => {
        const panel = el('div', { id: 'studio-crisis', role: 'dialog', 'aria-label': crisis.title,
            style: 'position:fixed;inset:12% 15%;z-index:100000;overflow:auto;background:#000080;color:#fff;' +
                   'border:3px double #fff;padding:1.2em;font-family:inherit' },
            el('h2', {}, `⚠ ${crisis.title}`), el('p', {}, crisis.text), el('p', {}, 'WHAT DO YOU DO?'));
        for (const o of crisis.options) {
            panel.append(el('div', { style: 'margin:6px 0' }, el('button', { type: 'button', 'data-option': o.id,
                onclick: async () => {
                    panel.querySelectorAll('button').forEach(b => { b.disabled = true; });
                    let res = null;
                    try {
                        res = await novaFetch('/api/production/choose', { crisis: crisis.id, option: o.id, movieBudget: state.movieBudget || 0 });
                    } catch { /* the picture goes on */ }
                    panel.remove();
                    resolve(res);
                } }, `[${o.label.toUpperCase()}]`), o.cost ? ` costs ${formatCurrency(o.cost)}` : ' no cost'));
        }
        document.body.append(panel);
    });
}

/** Premiere screen extras: what happened on set, and any achievements unlocked. */
export function showPremiereExtras(results) {
    if (!IS_NOVA) return;
    document.getElementById('studio-premiere')?.remove();
    const host = document.querySelector('#screen4 fieldset');
    if (!host) return;
    const box = el('div', { id: 'studio-premiere', style: 'margin:10px 0;padding:6px;border:1px dashed #888' });
    if (results.production) {
        box.append(el('div', {}, `ON SET: ${results.production.crisis} — you chose to ${String(results.production.choice).toLowerCase()}. ${results.production.note}`));
    }
    for (const a of results._achievements || []) {
        box.append(el('div', { class: 'achievement-unlocked', style: 'color:#ffcc33' }, `🏆 ACHIEVEMENT UNLOCKED: ${a.name} — ${a.description}`));
    }
    if (box.childNodes.length) host.insertBefore(box, host.children[2] || null);
}
