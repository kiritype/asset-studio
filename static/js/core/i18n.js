// Interface translation. Every language, Korean included, has a catalog in
// static/i18n/<lang>.json that maps keys such as `jobs.queue_n` to text. Placeholders are
// {0}, {1}… (positional) or {name}. A missing text falls back to English, then to the key.
// The language comes from the server setting (data/settings/ui.json); "auto" follows the
// browser. This module loads its catalogs with top-level await, so every module that
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
  if (typeof document === 'undefined') return 'en';
  try {
    const response = await fetch('/api/settings');
    const settings = await response.json();
    return settings.ui?.values?.language || 'auto';
  } catch {
    return 'auto';
  }
}

async function load(lang) {
  if (typeof document === 'undefined') {
    // Node tests: read the catalog next to the code instead of fetching it.
    const {readFile} = await import('node:fs/promises');
    return JSON.parse(await readFile(new URL(`../../i18n/${lang}.json`, import.meta.url), 'utf-8'));
  }
  try {
    return await (await fetch(`/i18n/${lang}.json`)).json();
  } catch {
    return {};
  }
}

const setting = await configured();
export const language = LANGUAGES.includes(setting) ? setting : fromBrowser();
/** Locale for dates and numbers. */
export const locale = {ko: 'ko-KR', en: 'en-US', ja: 'ja-JP', 'zh-CN': 'zh-CN'}[language];
// Also loaded by node tests, which have no document and no server.
if (typeof document !== 'undefined') document.documentElement.lang = language;

const [catalog, fallback] = await Promise.all([
  load(language),
  language === 'en' ? Promise.resolve({}) : load('en'),
]);

function fill(text, params) {
  if (params == null) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    params[name] === undefined ? whole : String(params[name]),
  );
}

/** Translate ``key``; ``params`` is an array for {0}… or an object for {name}. */
export function t(key, params) {
  if (typeof key !== 'string') return key;
  return fill(catalog[key] ?? fallback[key] ?? key, params);
}

/**
 * Show something that came from the server. Messages arrive as
 * ``{i18n: key, params, text}`` (``text`` is the English original); plain strings, such as
 * names people typed or records from older versions, are shown as they are.
 */
export function tr(value) {
  if (value == null || typeof value !== 'object') return value;
  if (typeof value.i18n !== 'string') return value.text ?? '';
  const params = Object.fromEntries(
    Object.entries(value.params || {}).map(([name, part]) => [name, tr(part)]),
  );
  const text = catalog[value.i18n] ?? fallback[value.i18n];
  return text === undefined ? (value.text ?? value.i18n) : fill(text, params);
}

/** Text for elements marked with data-i18n, data-i18n-title and data-i18n-label. */
export function translatePage(root = document) {
  for (const node of root.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll('[data-i18n-title]'))
    node.title = t(node.dataset.i18nTitle);
  for (const node of root.querySelectorAll('[data-i18n-label]'))
    node.setAttribute('aria-label', t(node.dataset.i18nLabel));
}
