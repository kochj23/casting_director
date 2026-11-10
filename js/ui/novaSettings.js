/**
 * Nova Settings
 * The Nova edition's studio office: which AI plays each role (analyst, agent, critics), which model it runs,
 * API keys (stored in the macOS Keychain by the server, never in the browser) and the Games DB badge.
 */

import { novaFetch } from '../services/novaService.js';

const ROLE_NAMES = { analyst: 'STUDIO ANALYST', agent: "ACTORS' AGENT", critics: 'THE CRITICS', advisors: 'STUDIO ADVISORS' };

/** Text-only element helper: nothing from the server is ever written as HTML. */
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

/** Header badge (DB ONLINE / OFFLINE / LOCAL) plus the [SETTINGS] button. Refreshes every 20 s. */
export function mountNovaHeader() {
    const header = document.querySelector('header');
    if (!header || document.getElementById('nova-bar')) return;
    const badge = el('span', { id: 'nova-db-badge' }, 'DB …');
    const button = el('button', { id: 'nova-settings-button', type: 'button', style: 'margin-left:1em;padding:2px 8px',
                                  onclick: openSettings }, '[SETTINGS]');
    header.append(el('div', { id: 'nova-bar', style: 'font-size:.8em;margin-top:4px' }, badge, button));
    const refresh = async () => {
        try {
            const { db } = await novaFetch('/healthz');
            badge.textContent = db;
            badge.style.color = db === 'DB ONLINE' ? '#33ff66' : '#ffcc33';
        } catch {
            badge.textContent = 'SERVER DOWN';
            badge.style.color = '#ff5555';
        }
    };
    refresh();
    setInterval(refresh, 20000);
}

async function openSettings() {
    document.getElementById('nova-settings')?.remove();
    const panel = el('div', { id: 'nova-settings', role: 'dialog', 'aria-label': 'Settings',
        style: 'position:fixed;inset:5%;z-index:100000;overflow:auto;background:#000080;color:#fff;' +
               'border:3px double #fff;padding:1em;font-family:inherit' }, 'LOADING…');
    document.body.append(panel);
    const [settings, avail] = await Promise.all([novaFetch('/api/settings'),
        novaFetch('/api/backends/available').catch(() => ({ available: {} }))]);
    panel.textContent = '';
    const close = el('button', { type: 'button', onclick: () => panel.remove() }, '[CLOSE]');
    const status = el('div', { id: 'nova-settings-status', style: 'min-height:1.4em;color:#ffcc33' });
    panel.append(el('h2', {}, 'STUDIO OFFICE — WHO RUNS THE NUMBERS'), status);

    const backendNames = Object.keys(settings.backends);
    const rows = {};
    for (const [role, blurb] of Object.entries(settings.roles)) {
        const current = settings.brains[role] || {};
        const backend = el('select', { 'data-role': role, 'aria-label': `${role} backend` },
            ...backendNames.map(name => {
                const b = settings.backends[name];
                const up = avail.available[name];
                const option = el('option', { value: name },
                    `${b.label}${up === true ? '' : up === false ? ' (offline)' : ''}`);
                if (name === current.backend) option.selected = true;
                return option;
            }));
        const model = el('input', { 'data-role-model': role, 'aria-label': `${role} model`, list: `models-${role}`,
                                    value: current.model || '', placeholder: 'default model', style: 'width:18em' });
        const models = el('datalist', { id: `models-${role}` });
        const loadModels = async () => {
            models.textContent = '';
            try {
                const { models: names } = await novaFetch(`/api/models?backend=${encodeURIComponent(backend.value)}`);
                names.forEach(n => models.append(el('option', { value: n })));
            } catch { /* no list for this backend */ }
        };
        backend.addEventListener('change', () => { model.value = ''; loadModels(); });
        loadModels();
        rows[role] = { backend, model };
        panel.append(el('fieldset', {}, el('legend', {}, ROLE_NAMES[role] || role.toUpperCase()),
            el('div', { style: 'opacity:.8;margin-bottom:.4em' }, blurb), backend, ' ', model, models));
    }

    const save = el('button', { type: 'button', onclick: async () => {
        const brains = Object.fromEntries(Object.entries(rows).map(([role, r]) =>
            [role, { backend: r.backend.value, model: r.model.value.trim() }]));
        try {
            await novaFetch('/api/settings', { brains }, { method: 'PUT' });
            status.textContent = 'SAVED. The next call uses the new brains.';
        } catch (e) { status.textContent = `ERROR: ${e.message}`; }
    } }, '[SAVE BRAINS]');
    panel.append(save);

    const keyed = backendNames.filter(n => settings.backends[n].has_key !== null);
    const which = el('select', { 'aria-label': 'key backend' },
        ...keyed.map(n => el('option', { value: n },
            `${settings.backends[n].label} ${settings.backends[n].has_key ? '(key saved)' : '(no key)'}`)));
    const key = el('input', { type: 'password', autocomplete: 'off', 'aria-label': 'API key', placeholder: 'paste key',
                              style: 'width:22em' });
    const storeKey = el('button', { type: 'button', onclick: async () => {
        if (!key.value.trim()) return;
        try {
            await novaFetch('/api/keys', { backend: which.value, key: key.value.trim() });
            key.value = '';
            status.textContent = 'KEY STORED IN THE KEYCHAIN.';
        } catch (e) { status.textContent = `ERROR: ${e.message}`; }
    } }, '[STORE KEY]');
    panel.append(el('fieldset', {}, el('legend', {}, 'API KEYS (macOS KEYCHAIN)'), which, ' ', key, ' ', storeKey),
                 el('div', { style: 'margin-top:1em' }, close));
}
