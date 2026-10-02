// Interface preferences (language, theme, tag autocomplete), stored on the server in
// data/settings/ui.json. The theme is also cached in this browser only so the page does
// not flash light before the server answers; the server value always wins.

const THEME_CACHE = 'asset-studio-theme';
const listeners = new Set();
const darkQuery = window.matchMedia?.('(prefers-color-scheme: dark)');

export const preferences = {language: 'auto', theme: 'system', autocomplete: true};

/** 'light' or 'dark' for a theme setting; 'system' follows the operating system. */
export const resolveTheme = (theme) =>
  theme === 'dark' || (theme === 'system' && darkQuery?.matches) ? 'dark' : 'light';

export function applyTheme(theme = preferences.theme) {
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  try {
    localStorage.setItem(THEME_CACHE, theme);
  } catch {
    /* The cache only avoids a flash on load. */
  }
}
darkQuery?.addEventListener?.('change', () => {
  if (preferences.theme === 'system') applyTheme();
});

/** Called with the preferences whenever they change. Returns an unsubscribe function. */
export function onPreferences(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setPreferences(values) {
  Object.assign(preferences, values);
  applyTheme();
  for (const listener of listeners) listener(preferences);
}

export async function loadPreferences(api) {
  try {
    const all = await api('/api/settings');
    setPreferences(all.ui?.values || {});
  } catch {
    applyTheme();
  }
}
