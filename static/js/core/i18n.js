// Interface translation. Keys are the Korean source text; static/i18n/<lang>.json maps
// them to other languages. Placeholders are {0}, {1}… (positional) or {name}.
// The language comes from the server setting (data/settings/ui.json); "auto" follows the
// browser. This module loads its catalog with top-level await, so every module that
// imports it can translate at load time.

export const LANGUAGES = ['ko', 'en', 'ja', 'zh-CN'];

function fromBrowser() {
  const nav = typeof navigator === 'undefined' ? {} : navigator;
  for (const wanted of nav.languages || [nav.language || '']) {
    const code = wanted.toLowerCase();
    if (code.startsWith('ko')) return 'ko';
    if (code.startsWith('ja')) return 'ja';
    if (code.startsWith('zh')) return 'zh-CN';
    if (code.startsWith('en')) return 'en';
  }
  return 'en';
}

async function configured() {
  if (typeof document === 'undefined') return 'ko';
  try {
    const response = await fetch('/api/settings');
    const settings = await response.json();
    return settings.ui?.values?.language || 'auto';
  } catch {
    return 'auto';
  }
}

const setting = await configured();
export const language = LANGUAGES.includes(setting) ? setting : fromBrowser();
/** Locale for dates and numbers. */
export const locale = {ko: 'ko-KR', en: 'en-US', ja: 'ja-JP', 'zh-CN': 'zh-CN'}[language];
// Also loaded by node tests, which have no document and no server.
if (typeof document !== 'undefined') document.documentElement.lang = language;

let catalog = {};
const patterns = [];
if (language !== 'ko') {
  try {
    catalog = await (await fetch(`/i18n/${language}.json`)).json();
  } catch {
    catalog = {};
  }
  // Keys with placeholders also match messages that were built on the server.
  for (const [key, value] of Object.entries(catalog)) {
    if (!/\{\w+\}/.test(key)) continue;
    const names = [];
    const source = key
      .split(/(\{\w+\})/)
      .map((part) => {
        const match = part.match(/^\{(\w+)\}$/);
        if (match) {
          names.push(match[1]);
          return '([\\s\\S]+?)';
        }
        return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      })
      .join('');
    const fixed = key.replace(/\{\w+\}/g, '').length;
    patterns.push({regex: new RegExp(`^${source}$`), names, value, fixed});
  }
  // The pattern with the most fixed text wins when several match.
  patterns.sort((a, b) => b.fixed - a.fixed);
}

function fill(text, params) {
  if (params == null) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    params[name] === undefined ? whole : String(params[name]),
  );
}

/** Translate ``key``; ``params`` is an array for {0}… or an object for {name}. */
export function t(key, params) {
  if (typeof key !== 'string') return key;
  const text = language === 'ko' ? key : (catalog[key] ?? key);
  return fill(text, params);
}

/**
 * Translate text that came from the server (errors, labels) and may already contain
 * filled-in values: exact keys first, then keys with placeholders.
 */
export function tr(text) {
  if (typeof text !== 'string' || language === 'ko' || !/[가-힣]/.test(text)) return text;
  if (catalog[text] !== undefined) return catalog[text];
  for (const {regex, names, value} of patterns) {
    const match = text.match(regex);
    if (match) {
      const params = Object.fromEntries(names.map((name, index) => [name, tr(match[index + 1])]));
      return fill(value, params);
    }
  }
  return text;
}

/** Fill elements marked with data-i18n (text) / data-i18n-title / data-i18n-label. */
export function translatePage(root = document) {
  for (const node of root.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll('[data-i18n-title]'))
    node.title = t(node.dataset.i18nTitle);
  for (const node of root.querySelectorAll('[data-i18n-label]'))
    node.setAttribute('aria-label', t(node.dataset.i18nLabel));
}
