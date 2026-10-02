// Danbooru tag autocomplete for prompt textareas, and a tag check list.

import {MODEL_WORDS, promptTag, replaceTag, splitTags, tagAt} from '../lib/tags.js';
import {t} from '../core/i18n.js';
import {preferences} from './preferences.js';

const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const count = (value) =>
  value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : String(value);
const CATEGORY_LABELS = {
  general: t('일반'),
  artist: t('작가'),
  copyright: t('작품'),
  character: t('캐릭터'),
  meta: t('메타'),
};

/**
 * Wrap ``textarea`` with a suggestion list fed by ``/api/tags/complete``.
 * Returns the wrapper to put in the page instead of the textarea. Accepting a suggestion
 * fires the textarea's own ``input`` event, so the page's handlers save it as usual.
 * ``separator`` goes after an inserted tag (one-tag-per-line fields pass '').
 * Turned off by the "tag autocomplete" setting.
 */
export function withTagComplete(textarea, api, onChange, {separator = ', '} = {}) {
  const wrap = el('div', 'tag-input');
  const list = el('ul', 'tag-suggest');
  list.hidden = true;
  list.setAttribute('role', 'listbox');
  wrap.append(textarea, list);
  let items = [];
  let active = 0;
  let timer = 0;
  let seq = 0;
  let unavailable = false;
  let accepting = false;

  const close = () => {
    list.hidden = true;
    items = [];
  };
  function accept(index) {
    const item = items[index];
    if (!item) return;
    const {start, end} = tagAt(textarea.value, textarea.selectionStart);
    const tag = promptTag(item.tag.replace(/ /g, '_'));
    const next = replaceTag(textarea.value, start, end, tag, separator);
    textarea.value = next.text;
    textarea.setSelectionRange(next.caret, next.caret);
    close();
    accepting = true;
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    accepting = false;
  }
  function draw() {
    list.replaceChildren();
    items.forEach((item, index) => {
      const row = el('li', index === active ? 'active' : '');
      row.setAttribute('role', 'option');
      row.append(
        el('span', '', item.tag),
        el('small', `tag-cat tag-cat-${item.category}`, CATEGORY_LABELS[item.category] || ''),
        el('small', '', count(item.count)),
      );
      if (item.alias) row.title = `${item.alias} → ${item.tag}`;
      else if (item.description) row.title = item.description;
      row.addEventListener('mousedown', (event) => {
        event.preventDefault();
        accept(index);
      });
      list.append(row);
    });
    list.hidden = !items.length;
  }
  async function suggest() {
    const {word} = tagAt(textarea.value, textarea.selectionStart);
    if (unavailable || word.length < 2 || /[()[\]{}:]/.test(word)) return close();
    const mine = ++seq;
    try {
      const result = await api(`/api/tags/complete?q=${encodeURIComponent(word)}&limit=12`);
      if (mine !== seq) return;
      unavailable = !result.available;
      items = result.tags || [];
      active = 0;
      draw();
    } catch {
      close();
    }
  }
  textarea.addEventListener('input', () => {
    onChange?.(textarea.value);
    if (accepting || !preferences.autocomplete) return;
    clearTimeout(timer);
    timer = setTimeout(suggest, 140);
  });
  textarea.addEventListener('keydown', (event) => {
    if (list.hidden) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      draw();
    } else if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault();
      accept(active);
    } else if (event.key === 'Escape') {
      close();
    }
  });
  textarea.addEventListener('blur', () => setTimeout(close, 120));
  return wrap;
}

// Natural-language parts of a mixed prompt: a full stop or more than five words.
const SENTENCE = /\.(\s|$)|(\S+\s+){5,}\S/;

/**
 * Check every tag of ``text`` and draw the result into ``box``. Unknown tags offer near
 * matches and aliases offer their main name; clicking one calls ``replace(old, next)``.
 */
export async function renderTagCheck(box, api, text, replace) {
  const tags = [...new Set(splitTags(text))];
  box.replaceChildren(el('p', 'tag-note', t('확인 중…')));
  const kind = (tag) => (MODEL_WORDS.test(tag) ? 'model' : SENTENCE.test(tag) ? 'sentence' : 'tag');
  const asked = tags.filter((tag) => kind(tag) === 'tag');
  // Anima writes artists as "@name"; Danbooru knows them without the mark.
  const result = await api('/api/tags/check', {tags: asked.map((tag) => tag.replace(/^@/, ''))});
  if (!result.available) {
    box.replaceChildren(el('p', 'tag-note', result.error || t('태그 데이터가 없습니다.')));
    return;
  }
  box.replaceChildren();
  const fix = (old, next) => {
    const chip = el('button', 'tag-chip tag-fix', `→ ${next}`);
    chip.type = 'button';
    const mark = old.startsWith('@') ? '@' : '';
    chip.addEventListener('click', () => replace(old, mark + promptTag(next.replace(/ /g, '_'))));
    return chip;
  };
  let problems = 0;
  for (const tag of tags.filter((t) => kind(t) !== 'tag')) {
    const row = el('div', 'tag-row tag-model');
    const short = tag.length > 40 ? `${tag.slice(0, 38)}…` : tag;
    row.append(
      el('span', 'tag-chip', short),
      el('small', '', kind(tag) === 'model' ? t('모델 품질어') : t('문장')),
    );
    row.title = tag;
    box.append(row);
  }
  result.tags.forEach((entry, index) => {
    const tag = asked[index];
    const row = el('div', `tag-row tag-${entry.status}`);
    if (entry.status === 'ok') {
      row.append(el('span', 'tag-chip', tag), el('small', '', count(entry.count)));
      row.title = entry.description || CATEGORY_LABELS[entry.category] || '';
    } else if (entry.status === 'alias') {
      problems++;
      row.append(
        el('span', 'tag-chip', tag),
        el('small', '', t('별칭')),
        fix(tag, entry.alias_of.tag),
      );
    } else {
      problems++;
      row.append(el('span', 'tag-chip', tag), el('small', '', t('없는 태그')));
      for (const near of entry.near || []) row.append(fix(tag, near.tag));
    }
    box.append(row);
  });
  box.prepend(
    el(
      'p',
      'tag-note',
      problems
        ? t('태그 {0}개 중 {1}개 확인 필요', [asked.length, problems])
        : t('태그 {0}개 모두 Danbooru에 있습니다.', [asked.length]),
    ),
  );
}
