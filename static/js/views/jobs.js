// Generation menu. Left: the characters of one work. Right: every prompt piece those
// characters can use, as check lists. Jobs = characters x outfit sets x expressions x count.

import {renderGenerationSettings} from '../core/generation_settings.js';
import {buildRequest, samePreset, suggestedSlots, withCharacterSeeds} from '../lib/job_requests.js';
import {
  SCOPE_LABELS,
  characterOf,
  findOutfitSet,
  MODEL_FAMILY_LABELS,
  findPiece,
  fitsFamily,
  modelFamily,
  levelLabel,
  orderedLevels,
  slotsForSet,
  visibleOutfitSets,
  visiblePieces,
} from '../lib/library.js';
import {sendToLab} from './lab.js';
import {locale, t, tr} from '../core/i18n.js';
import {withTagComplete} from '../core/tag_input.js';

const STORE = 'asset-studio-jobs-v2';
const MAX_JOBS = 3000;
const freshTabId = () =>
  globalThis.crypto?.randomUUID?.() ||
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
const arr = (value) => (Array.isArray(value) ? value : []);
const copy = (value) => JSON.parse(JSON.stringify(value));
const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const btn = (text, action, cls = '') => {
  const n = el('button', cls, text);
  n.type = 'button';
  n.addEventListener('click', action);
  return n;
};
const opt = (value, text) => {
  const n = el('option', '', text);
  n.value = value;
  return n;
};
const label = (text, control, hint) => {
  const n = el('label', 'jobs-field');
  n.append(el('span', '', text), control);
  if (hint) n.append(el('small', '', hint));
  return n;
};
const input = (value = '') => {
  const n = el('input');
  n.value = value;
  return n;
};
const select = (choices, selected = '') => {
  const n = el('select');
  n.append(...choices.map(([value, text]) => opt(value, text)));
  n.value = selected;
  return n;
};
const checkbox = (checked, onChange) => {
  const n = input();
  n.type = 'checkbox';
  n.checked = checked;
  n.addEventListener('change', () => onChange(n.checked));
  return n;
};
/** Small tag that tells where a piece is stored: global, shared by the work, or one character. */
const scopeBadge = (scope, text = SCOPE_LABELS[scope]) => {
  const n = el('small', `jobs-scope jobs-scope-${scope}`, text);
  n.title = {
    global: t('전역: 어느 작품·캐릭터에서나 쓰는 조각'),
    work: t('작품 공용: 이 작품의 모든 캐릭터가 쓰는 조각'),
    character: t('캐릭터 귀속: 이 캐릭터만 쓰는 조각'),
  }[scope];
  return n;
};
const lines = (value) =>
  Array.isArray(value) ? value.join('\n') : value == null ? '' : String(value);
const message = (error) => String(error?.message || error);
const conflicted = (error) => error?.status === 409;
const targetKey = (character, outfit) => `${character}/${outfit}`;
const defaults = () => ({
  work: '',
  characters: [],
  outfits: [],
  expressions: [],
  rating: 'sfw',
  expressionSet: '',
  composition: '',
  slots: null,
  slotsTouched: false,
  artists: [],
  commonPositive: [],
  commonNegative: [],
  preset: '',
  combination: '',
  settings: {},
  settingsModified: false,
  count: 1,
  characterSeeds: true,
  overrides: {},
  overrideEnabled: {},
});
const OVERRIDES = [
  ['appearance', t('외형'), 'target'],
  ['outfit', t('의상'), 'target'],
  ['expression', t('감정·동작'), 'expression'],
  ['composition', t('구도'), 'expression'],
  ['negative', t('전체 제외 프롬프트'), 'both'],
];
const OVERRIDE_HINT = {
  target: t('캐릭터와 의상 세트를 하나씩 선택하면 사용할 수 있습니다.'),
  expression: t('감정·동작 하나를 선택하면 사용할 수 있습니다.'),
  both: t('캐릭터, 의상 세트, 감정·동작을 각각 하나씩 선택하면 사용할 수 있습니다.'),
};
// Draft fields a combination preset stores and restores (characters and outfits stay).
const COMBINATION_FIELDS = [
  'rating',
  'expressions',
  'expressionSet',
  'composition',
  'slots',
  'artists',
  'commonPositive',
  'commonNegative',
  'preset',
  'settings',
  'count',
  'characterSeeds',
];
// How many characters the summary lists one by one before it switches to totals only.
const BREAKDOWN_LIMIT = 8;

/** A draft saved by an older layout kept character/outfit pairs. */
function normalizeDraft(saved) {
  if (!saved || !Array.isArray(saved.targets) || saved.characters) return saved;
  const pairs = saved.targets.map((key) => String(key).split('/'));
  return {
    ...saved,
    characters: [...new Set(pairs.map(([character]) => character))],
    outfits: [...new Set(pairs.map(([, outfit]) => outfit).filter(Boolean))],
  };
}

export function createJobs(ctx) {
  const state = {
    works: [],
    catalog: null,
    comfy: null,
    version: null,
    draft: defaults(),
    search: '',
    busy: false,
    loading: true,
    previewSeq: 0,
    tab: '',
    channel: null,
  };
  const session = (() => {
    try {
      return sessionStorage;
    } catch {
      return null;
    }
  })();
  const storage = (() => {
    try {
      localStorage.setItem(`${STORE}:test`, '1');
      localStorage.removeItem(`${STORE}:test`);
      return localStorage;
    } catch {
      return null;
    }
  })();
  state.tab = session?.getItem(`${STORE}:tab`) || freshTabId();
  session?.setItem(`${STORE}:tab`, state.tab);
  const draftKey = (work) => `${STORE}:draft:${state.tab}:${work}`;
  const readDraft = (work) => {
    try {
      return JSON.parse(storage?.getItem(draftKey(work)) || 'null');
    } catch {
      return null;
    }
  };
  const persist = () => {
    if (!state.draft.work) return;
    storage?.setItem(draftKey(state.draft.work), JSON.stringify(state.draft));
    session?.setItem(`${STORE}:work`, state.draft.work);
  };
  const notify = (text, error = false) => {
    status.textContent = text;
    status.classList.toggle('error', error);
    ctx.notify?.(text, error);
  };

  // ---- layout -------------------------------------------------------------------

  const root = el('section');
  root.id = 'app-jobs';
  const header = el('header', 'jobs-header');
  header.append(
    el('h1', '', t('이미지 생성')),
    btn(t('프롬프트 라이브러리'), () => ctx.navigate?.('/prompts'), 'jobs-muted'),
  );
  const aside = el('aside', 'jobs-aside');
  const main = el('main', 'jobs-main');
  const workSelect = el('select');
  const search = input();
  search.type = 'search';
  search.placeholder = t('캐릭터 검색');
  const tree = el('div', 'jobs-tree');
  const characterButtons = el('div', 'jobs-row');
  characterButtons.append(
    btn(t('전체 선택'), () => chooseCharacters(true), 'jobs-muted'),
    btn(t('선택 해제'), () => chooseCharacters(false), 'jobs-muted'),
  );
  workSelect.disabled = true;
  search.disabled = true;
  aside.append(label(t('작품'), workSelect), label(t('검색'), search), characterButtons, tree);
  const status = el('p', 'jobs-status');
  status.setAttribute('role', 'status');
  const summary = el('section', 'jobs-card jobs-summary');
  const combinationSection = el('section', 'jobs-card');
  const outfitSection = el('section', 'jobs-card');
  const slotSection = el('div', 'jobs-sub');
  const expressionSection = el('section', 'jobs-card');
  const pieceSection = el('section', 'jobs-card');
  const settingsSection = el('section', 'jobs-card');
  const overrideSection = el('details', 'jobs-card jobs-overrides');
  const previewSection = el('section', 'jobs-card');
  const actions = el('section', 'jobs-card jobs-actions');
  const sections = [
    combinationSection,
    outfitSection,
    expressionSection,
    pieceSection,
    settingsSection,
    overrideSection,
    previewSection,
    actions,
  ];
  main.append(status, summary, ...sections);
  root.append(header, aside, main);
  workSelect.addEventListener('change', () => changeWork(workSelect.value));
  search.addEventListener('input', () => {
    state.search = search.value.toLocaleLowerCase().trim();
    renderCharacters();
  });

  // ---- what is selected -----------------------------------------------------------

  const categories = () => state.catalog?.categories;
  /** The model family being generated for; it decides which prompt pieces are offered. */
  const family = () => state.draft.settings?.family || 'anima';
  const familyBadge = (record) => {
    const value = modelFamily(record);
    return el('small', `jobs-scope jobs-family-${value}`, MODEL_FAMILY_LABELS[value]);
  };
  const characters = () => arr(state.catalog?.characters);
  const presets = (type) => arr(state.catalog?.presets?.[type]);
  const chosenCharacters = () =>
    state.draft.characters.map((id) => characterOf(state.catalog, id)).filter(Boolean);
  /** Every chosen character paired with every chosen outfit set that character can use. */
  const chosenTargets = () =>
    chosenCharacters().flatMap((character) =>
      state.draft.outfits
        .map((setId) => {
          const outfitSet = findOutfitSet(state.catalog, character, setId);
          return outfitSet && {character, outfitSet, key: targetKey(character.id, setId)};
        })
        .filter(Boolean),
    );
  /** Outfit sets to offer: the union over the chosen characters, by set code. */
  function outfitChoices() {
    const byId = new Map();
    for (const character of chosenCharacters())
      for (const outfitSet of visibleOutfitSets(state.catalog, character)) {
        if (!fitsFamily(outfitSet, family())) continue;
        const entry = byId.get(outfitSet.id) || {
          id: outfitSet.id,
          names: new Map(),
          owners: 0,
          defaults: 0,
          scopes: new Set(),
        };
        const name = outfitSet.name || outfitSet.id;
        entry.names.set(name, (entry.names.get(name) || 0) + 1);
        entry.owners += 1;
        entry.scopes.add(outfitSet.scope);
        if (character.default_outfit === outfitSet.id) entry.defaults += 1;
        byId.set(outfitSet.id, entry);
      }
    return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id));
  }
  /** Expressions to offer: shared ones, plus those only the chosen characters have. */
  function expressionChoices() {
    const byId = new Map();
    for (const piece of visiblePieces(state.catalog, null, 'expression'))
      if (fitsFamily(piece, family())) byId.set(piece.id, {piece, only: ''});
    for (const character of chosenCharacters())
      for (const piece of arr(character.pieces))
        if (piece.bucket === 'expression' && !byId.has(piece.id) && fitsFamily(piece, family()))
          byId.set(piece.id, {piece, only: character.id});
    return [...byId.values()].sort((a, b) => a.piece.id.localeCompare(b.piece.id));
  }
  const chosenExpressions = () => {
    const known = new Map(expressionChoices().map((choice) => [choice.piece.id, choice.piece]));
    return state.draft.expressions.map((id) => known.get(id)).filter(Boolean);
  };
  /** Per target, the chosen expressions that character can actually use. */
  const eligible = () =>
    chosenTargets().map((target) => ({
      target,
      ids: chosenExpressions()
        .map((piece) => piece.id)
        .filter((id) => findPiece(state.catalog, target.character, 'expression', id)),
    }));
  const totals = () => {
    const groups = eligible();
    const usable = groups.filter((g) => g.ids.length);
    const pairs = usable.reduce((sum, g) => sum + g.ids.length, 0);
    return {
      groups,
      usable,
      pairs,
      skipped: groups.reduce((sum, g) => sum + chosenExpressions().length - g.ids.length, 0),
      jobs: pairs * Number(state.draft.count || 0),
    };
  };
  /**
   * Slots the compositions in use suggest. `agreed` is false when the chosen
   * expressions use compositions that suggest different slots.
   */
  function slotSuggestion() {
    const character = chosenCharacters()[0] || null;
    const ids = state.draft.composition
      ? [state.draft.composition]
      : [...new Set(chosenExpressions().map((piece) => piece.composition_id || ''))];
    const compositions = ids.map((id) =>
      id ? findPiece(state.catalog, character, 'composition', id) : null,
    );
    const suggestions = compositions.map((piece) => suggestedSlots(piece));
    const agreed = new Set(suggestions.map((slots) => JSON.stringify(slots))).size === 1;
    return {
      agreed,
      slots: agreed ? suggestions[0] : null,
      names: compositions.filter(Boolean).map((piece) => piece.name || piece.id),
    };
  }
  function applySuggestion() {
    state.draft.slots = slotSuggestion().slots;
    state.draft.slotsTouched = false;
  }
  function selectionChanged() {
    if (!state.draft.slotsTouched) applySuggestion();
    persist();
    renderSlots();
    renderSummary();
    renderOverrides();
  }

  // ---- loading --------------------------------------------------------------------

  function setLoading(loading) {
    state.loading = loading;
    workSelect.disabled = loading;
    search.disabled = loading;
    for (const section of [tree, characterButtons, ...sections]) section.inert = loading;
    enqueueButton.disabled =
      loading || !!ctx.preview || totals().jobs < 1 || totals().jobs > MAX_JOBS;
  }
  async function loadCatalog() {
    setLoading(true);
    state.catalog = null;
    renderCharacters();
    try {
      if (state.draft.work)
        state.catalog = await ctx.api(`/api/catalog?work=${encodeURIComponent(state.draft.work)}`);
      if (!state.draft.slotsTouched) applySuggestion();
      renderAll();
    } finally {
      setLoading(false);
    }
  }
  async function loadVersion() {
    const data = await ctx.api('/api/library/version');
    state.version = data.revision;
    state.draft.libraryRevision = data.revision;
    persist();
    return state.version;
  }
  async function changeWork(work) {
    const saved = normalizeDraft(readDraft(work));
    state.draft = {...defaults(), ...saved, work};
    workSelect.value = work;
    if (!saved) state.draft.settings = copy(state.comfy?.defaults || {});
    persist();
    try {
      await loadCatalog();
      await loadVersion();
    } catch (error) {
      notify(t('작품을 불러오지 못했습니다: {0}', [message(error)]), true);
    }
  }

  // ---- characters (left) and their outfit sets (right) ------------------------------

  const characterName = (character) =>
    character.name && character.name !== character.id
      ? `${character.name} · ${character.id}`
      : character.id;
  function charactersChanged() {
    // With nothing picked yet, start from the default outfit so one click gives a usable setup.
    if (!state.draft.outfits.length)
      state.draft.outfits = [
        ...new Set(chosenCharacters().map((character) => character.default_outfit)),
      ].filter(Boolean);
    renderOutfits();
    renderExpressions();
    selectionChanged();
  }
  function renderCharacters() {
    tree.replaceChildren();
    if (!state.catalog) {
      tree.append(el('p', 'jobs-empty', t('작품을 선택하세요.')));
      return;
    }
    const shown = characters().filter(
      (character) =>
        !state.search ||
        `${character.name} ${character.id}`.toLocaleLowerCase().includes(state.search),
    );
    for (const character of shown) {
      const check = checkbox(state.draft.characters.includes(character.id), (checked) => {
        const set = new Set(state.draft.characters);
        if (checked) set.add(character.id);
        else set.delete(character.id);
        // Keep the work's order so requests and the summary do not depend on click order.
        state.draft.characters = characters()
          .map((c) => c.id)
          .filter((id) => set.has(id));
        charactersChanged();
      });
      const row = el('label', 'jobs-check');
      const caption = el('span', '', characterName(character));
      caption.title = caption.textContent;
      row.append(check, caption);
      tree.append(row);
    }
    if (!shown.length) tree.append(el('p', 'jobs-empty', t('캐릭터가 없습니다.')));
  }
  /** Tick or untick every character currently listed (the search narrows the list). */
  function chooseCharacters(on) {
    if (state.loading || !state.catalog) return;
    const listed = characters()
      .filter(
        (character) =>
          !state.search ||
          `${character.name} ${character.id}`.toLocaleLowerCase().includes(state.search),
      )
      .map((character) => character.id);
    const set = new Set(state.draft.characters);
    for (const id of listed) {
      if (on) set.add(id);
      else set.delete(id);
    }
    state.draft.characters = characters()
      .map((c) => c.id)
      .filter((id) => set.has(id));
    renderCharacters();
    charactersChanged();
  }
  function outfitCaption(choice, total) {
    const [[name]] = [...choice.names].sort((a, b) => b[1] - a[1]);
    const tags = [];
    if (choice.names.size > 1) tags.push(t('캐릭터마다 이름 다름'));
    if (choice.defaults === total) tags.push(t('기본'));
    else if (choice.defaults) tags.push(t('기본 {0}명', [choice.defaults]));
    if (choice.owners < total) tags.push(t('{0}명 중 {1}명', [total, choice.owners]));
    return [`${name} · ${choice.id}`, ...tags].join(' · ');
  }
  function renderOutfits() {
    outfitSection.replaceChildren(el('h2', '', t('의상 세트')));
    const total = chosenCharacters().length;
    if (!total) {
      outfitSection.append(el('p', 'jobs-note', t('왼쪽에서 캐릭터를 선택하세요.')));
      return;
    }
    const choices = outfitChoices();
    const list = el('div', 'jobs-checks');
    for (const choice of choices) {
      const check = checkbox(state.draft.outfits.includes(choice.id), (checked) => {
        const set = new Set(state.draft.outfits);
        if (checked) set.add(choice.id);
        else set.delete(choice.id);
        state.draft.outfits = [...set].sort();
        selectionChanged();
      });
      const row = el('label', 'jobs-check');
      const caption = el('span', '', outfitCaption(choice, total));
      caption.title = caption.textContent;
      row.append(check, caption);
      for (const scope of ['character', 'work', 'global'])
        if (choice.scopes.has(scope)) row.append(scopeBadge(scope));
      list.append(row);
    }
    if (!choices.length) list.append(el('p', 'jobs-empty', t('의상 세트가 없습니다.')));
    outfitSection.append(list);
    if (total > 1)
      outfitSection.append(
        el(
          'p',
          'jobs-note',
          t(
            '같은 코드의 의상 세트를 선택한 캐릭터 각각에 적용합니다. 그 코드가 없는 캐릭터는 건너뜁니다.',
          ),
        ),
      );
    outfitSection.append(slotSection);
  }

  // ---- outfit slots -----------------------------------------------------------------

  function renderSlots() {
    slotSection.replaceChildren(el('h3', '', t('넣을 부위')));
    const targets = chosenTargets();
    const slots = orderedLevels(
      categories(),
      'outfit',
      targets.flatMap((target) => Object.keys(target.outfitSet.slots || {})),
    ).filter((slot) => slot !== 'full');
    if (!targets.length) {
      slotSection.append(
        el('p', 'jobs-note', t('의상 세트를 체크하면 넣을 부위를 고를 수 있습니다.')),
      );
      return;
    }
    if (!slots.length) {
      slotSection.append(
        el('p', 'jobs-note', t('선택한 의상 세트는 부위로 나뉘어 있지 않아 전체를 씁니다.')),
      );
      return;
    }
    const row = el('div', 'jobs-checks');
    for (const slot of slots) {
      const checked = !state.draft.slots || state.draft.slots.includes(slot);
      const check = checkbox(checked, (on) => {
        const next = new Set(state.draft.slots || slots);
        if (on) next.add(slot);
        else next.delete(slot);
        state.draft.slots = orderedLevels(categories(), 'outfit', [...next]);
        state.draft.slotsTouched = true;
        persist();
        renderSlots();
        renderOverrides();
      });
      const item = el('label', 'jobs-check');
      item.append(check, el('span', '', levelLabel(categories(), 'outfit', slot)));
      row.append(item);
    }
    slotSection.append(row);
    const suggestion = slotSuggestion();
    const names = (list) => list.map((slot) => levelLabel(categories(), 'outfit', slot)).join(', ');
    const note = !suggestion.names.length
      ? t(
          '감정을 선택하면 그 구도가 제안하는 부위가 체크됩니다. 체크하지 않은 부위는 프롬프트에서 빠집니다.',
        )
      : suggestion.agreed
        ? t('구도({0})의 제안: {1}', [
            suggestion.names.join(' / '),
            suggestion.slots ? names(suggestion.slots) : t('전체'),
          ])
        : t(
            '선택한 감정들의 구도가 제안하는 부위가 서로 달라 전체를 체크했습니다. 필요한 부위만 남기세요.',
          );
    const hint = el('div', 'jobs-row');
    hint.append(el('p', 'jobs-note', note));
    if (suggestion.agreed && state.draft.slotsTouched)
      hint.append(
        btn(
          t('제안대로'),
          () => {
            applySuggestion();
            persist();
            renderSlots();
            renderOverrides();
          },
          'jobs-muted',
        ),
      );
    slotSection.append(hint);
    if (state.draft.slots && !state.draft.slots.length)
      slotSection.append(
        el('p', 'jobs-error', t('부위를 하나도 고르지 않으면 의상 세트 전체를 씁니다.')),
      );
    const whole = targets.filter((target) => target.outfitSet.slots?.full);
    if (whole.length)
      slotSection.append(
        el(
          'p',
          'jobs-note',
          t('부위로 나뉘지 않은 세트({0})는 항상 전체를 씁니다.', [
            whole.map((t) => t.key).join(', '),
          ]),
        ),
      );
  }

  // ---- expressions ------------------------------------------------------------------

  function renderExpressions() {
    expressionSection.replaceChildren(el('h2', '', t('감정·동작')));
    const controls = el('div', 'jobs-row');
    const ratings = orderedLevels(categories(), 'expression', [
      ...arr(categories()?.roles?.expression?.order),
    ]);
    const rating = select(
      ratings.map((value) => [value, levelLabel(categories(), 'expression', value)]),
      state.draft.rating,
    );
    rating.addEventListener('change', () => {
      state.draft.rating = rating.value;
      persist();
      renderExpressions();
    });
    const sets = select(
      [['', t('직접 선택')], ...presets('expression_set').map((p) => [p.id, p.name || p.id])],
      state.draft.expressionSet,
    );
    sets.addEventListener('change', () => {
      state.draft.expressionSet = sets.value;
      const found = presets('expression_set').find((p) => p.id === sets.value);
      if (found) state.draft.expressions = arr(found.expressions).map((ref) => ref.id);
      renderExpressions();
      selectionChanged();
    });
    const choices = expressionChoices().filter((c) => c.piece.rating === state.draft.rating);
    const all = btn(
      t('이 분류 전체 선택'),
      () => {
        state.draft.expressions = [
          ...new Set([...state.draft.expressions, ...choices.map((c) => c.piece.id)]),
        ];
        state.draft.expressionSet = '';
        renderExpressions();
        selectionChanged();
      },
      'jobs-muted',
    );
    const none = btn(
      t('선택 해제'),
      () => {
        state.draft.expressions = [];
        state.draft.expressionSet = '';
        renderExpressions();
        selectionChanged();
      },
      'jobs-muted',
    );
    controls.append(label(t('분류'), rating), label(t('묶음'), sets), all, none);
    expressionSection.append(controls);
    const list = el('div', 'jobs-expressions');
    for (const {piece, only} of choices) {
      const check = checkbox(state.draft.expressions.includes(piece.id), (checked) => {
        const set = new Set(state.draft.expressions);
        if (checked) set.add(piece.id);
        else set.delete(piece.id);
        state.draft.expressions = [...set];
        state.draft.expressionSet = '';
        sets.value = '';
        selectionChanged();
      });
      const row = el('label', 'jobs-check');
      const caption = `${piece.name || piece.id} · ${piece.id}`;
      row.append(
        check,
        el('span', '', caption),
        scopeBadge(piece.scope, only ? t('{0} 전용', [only]) : undefined),
        familyBadge(piece),
      );
      row.title = caption;
      list.append(row);
    }
    if (!choices.length) list.append(el('p', 'jobs-empty', t('이 분류에 감정·동작이 없습니다.')));
    expressionSection.append(list);
  }

  // ---- composition, artist, common pieces ---------------------------------------------

  function pieceChecks(title, bucket, key) {
    const box = el('div', 'jobs-piece-group');
    box.append(el('h3', '', title));
    const pieces = visiblePieces(state.catalog, null, bucket).filter((piece) =>
      fitsFamily(piece, family()),
    );
    const list = el('div', 'jobs-checks');
    for (const piece of pieces) {
      const check = checkbox(state.draft[key].includes(piece.id), (checked) => {
        const set = new Set(state.draft[key]);
        if (checked) set.add(piece.id);
        else set.delete(piece.id);
        // Keep the library order so the prompt order does not depend on click order.
        state.draft[key] = pieces.map((p) => p.id).filter((id) => set.has(id));
        state.draft.settingsModified = true;
        persist();
      });
      const row = el('label', 'jobs-check');
      const caption = `${piece.name || piece.id} · ${piece.id}`;
      row.append(check, el('span', '', caption), scopeBadge(piece.scope), familyBadge(piece));
      row.title = lines(piece.prompt).replace(/\n/g, ', ');
      list.append(row);
    }
    if (!pieces.length) list.append(el('p', 'jobs-empty', t('조각이 없습니다.')));
    box.append(list);
    return box;
  }
  function renderPieces() {
    pieceSection.replaceChildren(el('h2', '', t('구도 · 화풍 · 공통')));
    const compositions = visiblePieces(state.catalog, null, 'composition').filter((piece) =>
      fitsFamily(piece, family()),
    );
    const composition = select(
      [
        ['', t('감정별 기본 구도')],
        ...compositions.map((p) => [
          p.id,
          `${p.name || p.id} · ${p.id} (${SCOPE_LABELS[p.scope]})`,
        ]),
      ],
      state.draft.composition,
    );
    composition.addEventListener('change', () => {
      state.draft.composition = composition.value;
      applySuggestion();
      persist();
      renderSlots();
      renderOverrides();
    });
    pieceSection.append(
      label(
        t('구도'),
        composition,
        t('고르면 모든 감정에 이 구도를 씁니다. 고르지 않으면 각 감정에 지정된 구도를 씁니다.'),
      ),
      pieceChecks(t('화풍'), 'artist', 'artists'),
      pieceChecks(t('공통 긍정'), 'common/positive', 'commonPositive'),
      pieceChecks(t('공통 제외'), 'common/negative', 'commonNegative'),
    );
  }

  // ---- summary ------------------------------------------------------------------------

  function renderSummary() {
    const total = totals();
    const count = Number(state.draft.count || 0);
    const people = chosenCharacters();
    const expressions = chosenExpressions();
    const sets = state.draft.outfits.filter((id) =>
      people.some((character) => findOutfitSet(state.catalog, character, id)),
    );
    const formula = t('캐릭터 {0} × 의상 {1} × 감정 {2} × {3}장 = {4}장', [
      people.length,
      sets.length,
      expressions.length,
      count,
      total.jobs.toLocaleString(locale),
    ]);
    summary.replaceChildren(el('h2', '', t('생성 수')), el('p', 'jobs-formula', formula));
    const full = people.length * sets.length * expressions.length * count;
    if (total.jobs && total.jobs < full)
      summary.append(
        el(
          'p',
          'jobs-note',
          t('일부 캐릭터에 없는 의상·감정 조합 {0}장은 빠졌습니다.', [
            (full - total.jobs).toLocaleString(locale),
          ]),
        ),
      );
    if (total.groups.length && people.length <= BREAKDOWN_LIMIT) {
      const lines = el('ul', 'jobs-breakdown');
      for (const character of people) {
        const groups = total.groups.filter((g) => g.target.character.id === character.id);
        const images = groups.reduce((sum, g) => sum + g.ids.length, 0) * count;
        const names = groups.map((g) => g.target.outfitSet.name || g.target.outfitSet.id);
        lines.append(
          el(
            'li',
            '',
            t('{0}: {1} × 감정 {2} = {3}장', [
              characterName(character),
              names.join(', ') || t('의상 없음'),
              groups[0]?.ids.length ?? 0,
              images,
            ]),
          ),
        );
      }
      summary.append(lines);
    }
    if (!people.length) summary.append(el('p', 'jobs-note', t('왼쪽에서 캐릭터를 선택하세요.')));
    else if (!total.groups.length)
      summary.append(el('p', 'jobs-note', t('의상 세트를 체크하세요.')));
    else if (!expressions.length)
      summary.append(el('p', 'jobs-note', t('감정·동작을 체크하세요.')));
    if (total.jobs > MAX_JOBS)
      summary.append(el('p', 'jobs-error', t('한 번에 최대 3,000개 작업을 등록할 수 있습니다.')));
    actionFormula.textContent = formula;
    enqueueButton.textContent = t('{0}장 등록', [total.jobs.toLocaleString(locale)]);
    enqueueButton.disabled =
      state.loading || !!ctx.preview || total.jobs < 1 || total.jobs > MAX_JOBS;
  }

  // ---- generation settings ------------------------------------------------------------

  const selectedPreset = () => presets('generation').find((p) => p.id === state.draft.preset);
  /** Settings to send and to store in a preset: ComfyUI values plus the piece selection. */
  function currentSettings() {
    return {
      ...copy(state.draft.settings),
      artist_ids: [...state.draft.artists],
      common_positive_ids: [...state.draft.commonPositive],
      common_negative_ids: [...state.draft.commonNegative],
    };
  }
  function applyPreset(preset) {
    const value = copy(preset?.settings || {});
    const known = (bucket, ids) =>
      arr(ids).filter((id) => visiblePieces(state.catalog, null, bucket).some((p) => p.id === id));
    if (Array.isArray(value.artist_ids)) state.draft.artists = known('artist', value.artist_ids);
    if (Array.isArray(value.common_positive_ids))
      state.draft.commonPositive = known('common/positive', value.common_positive_ids);
    if (Array.isArray(value.common_negative_ids))
      state.draft.commonNegative = known('common/negative', value.common_negative_ids);
    for (const key of ['artist_ids', 'common_positive_ids', 'common_negative_ids'])
      delete value[key];
    state.draft.settings = value;
    state.draft.settingsModified = false;
    persist();
    renderSettings();
    renderPieces();
  }
  function renderSettings() {
    settingsSection.replaceChildren(el('h2', '', t('생성 설정')));
    const presetRow = el('div', 'jobs-row');
    const chooser = select(
      [
        ['', t('직접 설정')],
        ...presets('generation').map((p) => [p.id, `${p.name || p.id} · ${p.id}`]),
      ],
      state.draft.preset,
    );
    chooser.addEventListener('change', () => {
      state.draft.preset = chooser.value;
      const found = selectedPreset();
      if (found) applyPreset(found);
      else {
        state.draft.settingsModified = true;
        persist();
        renderSettings();
      }
    });
    presetRow.append(
      label(t('설정 프리셋'), chooser, t('모델·샘플러와 함께 화풍·공통 선택도 저장합니다.')),
      btn(t('새 프리셋 저장'), () => savePreset(false), 'jobs-muted'),
      btn(t('프리셋 덮어쓰기'), () => savePreset(true), 'jobs-muted'),
      btn(t('프리셋 삭제'), deletePreset, 'jobs-danger'),
    );
    settingsSection.append(presetRow);
    const autoLora = el('input');
    autoLora.type = 'checkbox';
    autoLora.checked = state.draft.autoLora !== false;
    autoLora.addEventListener('change', () => {
      state.draft.autoLora = autoLora.checked;
      persist();
    });
    const autoLabel = el('label', 'jobs-row');
    autoLabel.append(
      autoLora,
      el('span', '', t('등록된 LoRA 자동 적용')),
      el(
        'small',
        'jobs-note',
        t('LoRA 메뉴에서 자동 적용을 켠 LoRA와 트리거 단어를 캐릭터별로 넣습니다.'),
      ),
    );
    settingsSection.append(autoLabel);
    const form = el('div', 'jobs-settings-form');
    renderGenerationSettings(form, {
      comfy: state.comfy,
      settings: state.draft.settings,
      onChange(next, structural) {
        state.draft.settings = next;
        state.draft.settingsModified = true;
        persist();
        if (structural) {
          // A family switch changes which pieces fit.
          renderSettings();
          renderOutfits();
          renderExpressions();
          renderPieces();
          renderSummary();
        }
      },
    });
    settingsSection.append(form);
    const grid = el('div', 'jobs-grid');
    const count = input(String(state.draft.count));
    count.type = 'number';
    count.min = '1';
    count.max = '50';
    count.addEventListener('input', () => {
      state.draft.count = Number(count.value);
      persist();
      renderSummary();
    });
    grid.append(label(t('조합당 장수'), count));
    settingsSection.append(grid);
    const seedChoice = el('label', 'jobs-check');
    seedChoice.append(
      checkbox(state.draft.characterSeeds, (checked) => {
        state.draft.characterSeeds = checked;
        persist();
      }),
      el('span', '', t('캐릭터별 고정 시드 사용')),
    );
    settingsSection.append(
      seedChoice,
      el(
        'p',
        'jobs-note',
        t(
          '기본값: 시드 -1(랜덤). 체크하면 등록할 때마다 캐릭터별 새 시드를 뽑아 모든 의상·감정·반복 장수에 함께 사용합니다. 해제하면 이미지마다 랜덤입니다. 시드에 0 이상의 값을 입력하면 체크 여부와 관계없이 모든 대상에 그 값을 사용합니다.',
        ),
      ),
    );
  }

  // ---- presets: generation settings and whole combinations ------------------------------

  const presetURL = (type, id) =>
    `/api/library/entity?kind=preset&preset_type=${type}&id=${encodeURIComponent(id)}`;
  function nextPresetId(type, prefix) {
    const used = new Set(presets(type).map((p) => p.id));
    for (let i = 1; i < 1000; i++) {
      const id = `${prefix}${String(i).padStart(3, '0')}`;
      if (!used.has(id)) return id;
    }
    return '';
  }
  /** Ask for the id and name of a new preset; null when cancelled or invalid. */
  function askNewPreset(type, prefix) {
    const id = window
      .prompt(t('새 프리셋 코드 (영문·숫자·_·-)'), nextPresetId(type, prefix))
      ?.trim();
    if (id == null) return null;
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) {
      notify(t('프리셋 코드를 확인하세요.'), true);
      return null;
    }
    const name = window.prompt(t('프리셋 이름'), id)?.trim();
    if (name == null) return null;
    if (!name) {
      notify(t('프리셋 이름을 입력하세요.'), true);
      return null;
    }
    return {id, name};
  }
  /** Create or overwrite a preset. `fill` turns the stored record into the new payload. */
  async function writePreset(type, current, fresh, fill) {
    let expected = null;
    let base = fresh;
    if (current) {
      const latest = await ctx.api(presetURL(type, current.id));
      if (!samePreset(latest.entity, current)) {
        await loadCatalog();
        throw new Error(t('프리셋이 다른 곳에서 변경되었습니다. 최신 목록을 확인하세요.'));
      }
      expected = latest.revision;
      base = latest.entity;
    }
    await ctx.api('/api/library/save', {
      kind: 'preset',
      preset_type: type,
      payload: fill(base),
      expected_revision: expected,
    });
    await loadCatalog();
    await loadVersion();
    ctx.onLibraryChanged?.();
    return base.id;
  }
  async function removePreset(type, current) {
    const latest = await ctx.api(presetURL(type, current.id));
    if (!samePreset(latest.entity, current)) {
      await loadCatalog();
      throw new Error(t('프리셋이 다른 곳에서 변경되었습니다. 최신 목록을 확인하세요.'));
    }
    await ctx.api('/api/library/delete', {
      kind: 'preset',
      preset_type: type,
      id: current.id,
      expected_revision: latest.revision,
    });
  }
  function previewBlocked() {
    if (ctx.preview) notify(t('미리보기 모드에서는 프리셋을 변경할 수 없습니다.'), true);
    return !!ctx.preview;
  }
  async function savePreset(overwrite) {
    if (previewBlocked() || !state.draft.work) return;
    const current = overwrite ? selectedPreset() : null;
    if (overwrite && !current) {
      notify(t('덮어쓸 프리셋을 선택하세요.'), true);
      return;
    }
    const fresh = overwrite ? null : askNewPreset('generation', 'G');
    if (!overwrite && !fresh) return;
    try {
      const id = await writePreset(
        'generation',
        current,
        fresh && {...fresh, repeat: 1},
        (base) => ({
          ...base,
          settings: currentSettings(),
        }),
      );
      state.draft.preset = id;
      state.draft.settingsModified = false;
      persist();
      renderSettings();
      notify(t('설정 프리셋을 저장했습니다.'));
    } catch (error) {
      notify(t('프리셋 저장 실패: {0}', [message(error)]), true);
    }
  }
  async function deletePreset() {
    if (previewBlocked()) return;
    const current = selectedPreset();
    if (
      !current ||
      !window.confirm(t('{0} 프리셋을 삭제하고 휴지통으로 이동할까요?', [current.name]))
    )
      return;
    try {
      await removePreset('generation', current);
      state.draft.preset = '';
      state.draft.settingsModified = true;
      persist();
      await loadCatalog();
      await loadVersion();
      notify(t('프리셋을 휴지통으로 이동했습니다. 현재 설정은 유지됩니다.'));
    } catch (error) {
      notify(t('프리셋 삭제 실패: {0}', [message(error)]), true);
    }
  }
  const selectedCombination = () =>
    presets('combination').find((p) => p.id === state.draft.combination);
  function renderCombination() {
    combinationSection.replaceChildren(el('h2', '', t('조합 프리셋')));
    const chooser = select(
      [
        ['', t('선택 안 함')],
        ...presets('combination').map((p) => [p.id, `${p.name || p.id} · ${p.id}`]),
      ],
      state.draft.combination,
    );
    chooser.addEventListener('change', () => {
      state.draft.combination = chooser.value;
      const found = selectedCombination();
      if (found) {
        for (const key of COMBINATION_FIELDS)
          if (key in (found.draft || {})) state.draft[key] = copy(found.draft[key]);
        state.draft.slotsTouched = true;
        state.draft.settingsModified = false;
        state.draft.overrides = {};
        state.draft.overrideEnabled = {};
      }
      persist();
      renderAll();
    });
    const row = el('div', 'jobs-row');
    row.append(
      label(
        t('불러오기'),
        chooser,
        t(
          '감정 선택, 구도, 의상 부위, 화풍·공통, 생성 설정을 한 번에 불러옵니다. 캐릭터와 의상 세트 선택은 그대로 둡니다.',
        ),
      ),
      btn(t('새 조합 저장'), () => saveCombination(false), 'jobs-muted'),
      btn(t('덮어쓰기'), () => saveCombination(true), 'jobs-muted'),
      btn(t('삭제'), deleteCombination, 'jobs-danger'),
    );
    combinationSection.append(row);
  }
  async function saveCombination(overwrite) {
    if (previewBlocked() || !state.draft.work) return;
    const current = overwrite ? selectedCombination() : null;
    if (overwrite && !current) {
      notify(t('덮어쓸 조합 프리셋을 선택하세요.'), true);
      return;
    }
    const fresh = overwrite ? null : askNewPreset('combination', 'K');
    if (!overwrite && !fresh) return;
    const draft = Object.fromEntries(
      COMBINATION_FIELDS.map((key) => [key, copy(state.draft[key])]),
    );
    try {
      state.draft.combination = await writePreset('combination', current, fresh, (base) => ({
        ...base,
        generation_preset_id: state.draft.preset || '',
        expressions: state.draft.expressions.map((id) => ({id})),
        composition_id: state.draft.composition || '',
        artist_ids: [...state.draft.artists],
        common_positive_ids: [...state.draft.commonPositive],
        common_negative_ids: [...state.draft.commonNegative],
        draft,
      }));
      persist();
      renderCombination();
      notify(t('조합 프리셋을 저장했습니다.'));
    } catch (error) {
      notify(t('조합 프리셋 저장 실패: {0}', [message(error)]), true);
    }
  }
  async function deleteCombination() {
    if (previewBlocked()) return;
    const current = selectedCombination();
    if (!current || !window.confirm(t('{0} 조합 프리셋을 휴지통으로 이동할까요?', [current.name])))
      return;
    try {
      await removePreset('combination', current);
      state.draft.combination = '';
      persist();
      await loadCatalog();
      await loadVersion();
      notify(t('조합 프리셋을 휴지통으로 이동했습니다. 현재 선택은 유지됩니다.'));
    } catch (error) {
      notify(t('조합 프리셋 삭제 실패: {0}', [message(error)]), true);
    }
  }

  // ---- one-off prompt overrides ---------------------------------------------------------

  const overrideAvailable = (needs) => {
    const oneTarget = chosenTargets().length === 1;
    const oneExpression = chosenExpressions().length === 1;
    return needs === 'both'
      ? oneTarget && oneExpression
      : needs === 'target'
        ? oneTarget
        : oneExpression;
  };
  function renderOverrides() {
    const wasOpen = overrideSection.open;
    overrideSection.replaceChildren();
    overrideSection.open = wasOpen;
    overrideSection.append(
      el('summary', '', t('이번 생성에서만 프롬프트 수정')),
      el(
        'p',
        'jobs-note',
        t(
          '켜진 항목만 현재 요청에 적용합니다. 라이브러리 원본은 그대로 유지됩니다. 켜는 순간의 조합 결과를 가져와 고칩니다.',
        ),
      ),
    );
    for (const [key, title, needs] of OVERRIDES) {
      const available = overrideAvailable(needs);
      const check = checkbox(!!state.draft.overrideEnabled[key], async (checked) => {
        state.draft.overrideEnabled[key] = checked;
        if (checked && !(key in state.draft.overrides)) {
          // The server composes the text, so the starting point is exactly what would be sent.
          try {
            const result = await ctx.api('/api/compose/preview', firstBody({}));
            state.draft.overrides[key] = result.parts[key] || '';
          } catch (error) {
            state.draft.overrideEnabled[key] = false;
            notify(t('프롬프트를 가져오지 못했습니다: {0}', [message(error)]), true);
          }
        }
        persist();
        renderOverrides();
      });
      check.disabled = !available;
      const head = el('label', 'jobs-check');
      head.append(check, el('span', '', title));
      const box = el('div', 'jobs-override');
      box.append(head);
      if (available && check.checked) {
        const area = el('textarea');
        area.rows = 4;
        area.value = state.draft.overrides[key] ?? '';
        area.addEventListener('input', () => {
          state.draft.overrides[key] = area.value;
          persist();
        });
        const areaBox = withTagComplete(area, ctx.api);
        const reset = btn(
          t('조합 결과로 되돌리기'),
          () => {
            delete state.draft.overrides[key];
            state.draft.overrideEnabled[key] = false;
            persist();
            renderOverrides();
          },
          'jobs-muted',
        );
        box.append(areaBox, reset);
      } else if (!available) box.append(el('small', 'jobs-note', OVERRIDE_HINT[needs]));
      overrideSection.append(box);
    }
  }
  function activeOverrides() {
    const result = {};
    for (const [key, , needs] of OVERRIDES)
      if (state.draft.overrideEnabled[key] && overrideAvailable(needs))
        result[key] = state.draft.overrides[key] ?? '';
    return result;
  }

  // ---- preview and submit -----------------------------------------------------------------

  const bodyFor = (group, ids, overrides = activeOverrides()) =>
    buildRequest(state.draft, categories(), group.target, ids, currentSettings(), overrides);
  function firstBody(overrides) {
    const group = eligible().find((g) => g.ids.length);
    return group && {...bodyFor(group, [group.ids[0]], overrides), count: 1};
  }
  async function preview() {
    const body = firstBody();
    if (!body) {
      notify(t('미리 볼 의상과 감정·동작을 선택하세요.'), true);
      return;
    }
    const seq = ++state.previewSeq;
    try {
      const result = await ctx.api('/api/compose/preview', body);
      if (seq !== state.previewSeq) return;
      previewTitle.textContent = t('{0} / {1} · 감정 {2} {3} · 부위: {4}', [
        body.character_id,
        body.outfit_id,
        result.expression_id,
        result.expression_name,
        result.outfit_slots.map((slot) => levelLabel(categories(), 'outfit', slot)).join(', '),
      ]);
      positive.textContent = lines(result.positive) || '—';
      previewWarnings.replaceChildren(
        ...(result.warnings || []).map((warning) => el('p', 'jobs-error', tr(warning))),
        ...(result.auto_loras?.length
          ? [
              el(
                'p',
                'jobs-note',
                t('자동 LoRA: {0}', [
                  result.auto_loras.map((l) => `${l.name} (${l.strength})`).join(', '),
                ]),
              ),
            ]
          : []),
      );
      negative.textContent = lines(result.negative) || '—';
    } catch (error) {
      notify(t('미리보기 실패: {0}', [message(error)]), true);
    }
  }
  /** Hand the first combination's prompt and settings to the lab (and generate once). */
  async function toLab(runNow) {
    const body = firstBody();
    if (!body) {
      notify(t('의상과 감정·동작을 선택하세요.'), true);
      return;
    }
    if (runNow && ctx.preview) {
      notify(t('미리보기 모드에서는 생성할 수 없습니다.'), true);
      return;
    }
    try {
      const result = await ctx.api('/api/compose/preview', body);
      sendToLab(
        ctx,
        {
          positive: result.positive,
          negative: result.negative,
          settings: copy(state.draft.settings),
          source: {
            work_id: body.work_id,
            character_id: body.character_id,
            outfit_id: body.outfit_id,
            expression_id: result.expression_id,
          },
        },
        runNow,
      );
    } catch (error) {
      notify(t('실험실로 보내지 못했습니다: {0}', [message(error)]), true);
    }
  }
  async function workflow() {
    const body = firstBody();
    if (!body) {
      notify(t('워크플로를 만들 대상을 선택하세요.'), true);
      return;
    }
    try {
      const graph = await ctx.api('/api/workflow', {...body, format: 'ui'});
      const blob = new Blob([JSON.stringify(graph, null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const link = el('a');
      link.href = url;
      link.download = `${body.character_id}_${body.expressions[0].id}_workflow.json`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify(t('워크플로를 다운로드했습니다.'));
    } catch (error) {
      notify(t('워크플로 실패: {0}', [message(error)]), true);
    }
  }
  async function checkVersion() {
    const now = await ctx.api('/api/library/version');
    if (state.version && now.revision !== state.version) {
      state.version = now.revision;
      await loadCatalog();
      notify(t('라이브러리가 변경되었습니다. 선택과 프롬프트를 확인한 뒤 다시 등록하세요.'), true);
      return false;
    }
    state.version = now.revision;
    return true;
  }
  function validate() {
    const total = totals();
    const s = state.draft.settings;
    if (!total.pairs) return t('유효한 의상과 감정·동작 조합이 없습니다.');
    if (!Number.isInteger(state.draft.count) || state.draft.count < 1 || state.draft.count > 50)
      return t('조합당 장수는 1~50 사이여야 합니다.');
    if (total.jobs > MAX_JOBS || total.usable.length > 500)
      return t('한 번에 등록할 수 있는 작업 수를 초과했습니다.');
    if (
      !(
        s.family === 'sdxl'
          ? ['model', 'sampler', 'scheduler']
          : ['model', 'text_encoder', 'vae', 'sampler', 'scheduler', 'clip_type']
      ).every((key) => !!s[key])
    )
      return t('모델과 생성 설정을 선택하세요.');
    if (
      !Number.isInteger(s.steps) ||
      s.steps < 1 ||
      s.steps > 100 ||
      !Number.isFinite(s.cfg) ||
      s.cfg < 0 ||
      s.cfg > 30
    )
      return t('Steps 또는 CFG 값을 확인하세요.');
    if (
      ![s.width, s.height].every(
        (n) => Number.isInteger(n) && n >= 256 && n <= 3072 && n % 16 === 0,
      )
    )
      return t('가로와 세로는 256~3072 사이의 16배수여야 합니다.');
    return '';
  }
  async function enqueue() {
    if (state.busy) return;
    if (ctx.preview) {
      notify(t('미리보기 모드에서는 작업을 등록할 수 없습니다.'), true);
      return;
    }
    const invalid = validate();
    if (invalid) {
      notify(invalid, true);
      return;
    }
    state.busy = true;
    try {
      if (!(await checkVersion())) return;
      const total = totals();
      const description = total.usable
        .map((g) => {
          const slots = slotsForSet(categories(), g.target.outfitSet, state.draft.slots);
          const names = slots.map((slot) => levelLabel(categories(), 'outfit', slot)).join('+');
          return t('{0} / {1} ({2}): {3}개 감정·동작', [
            g.target.character.name,
            g.target.outfitSet.name,
            names,
            g.ids.length,
          ]);
        })
        .join('\n');
      if (
        !window.confirm(
          t('{0}개 작업을 대기열에 등록합니다.\n\n{1}\n\n등록 후 이 화면의 선택은 유지됩니다.', [
            total.jobs,
            description,
          ]),
        )
      )
        return;
      const requests = withCharacterSeeds(
        total.usable.map((group) => bodyFor(group, group.ids)),
        state.draft.characterSeeds,
      );
      const result = await ctx.api('/api/jobs/batch', {
        requests,
        library_revision: state.version,
        generation_preset_id: state.draft.preset || undefined,
        settings_modified: state.draft.settingsModified,
      });
      notify(t('{0}개 작업을 등록했습니다. 배치 {1}', [result.count, result.batch_id]));
      ctx.onQueueChanged?.();
    } catch (error) {
      if (conflicted(error)) {
        try {
          await loadVersion();
          await loadCatalog();
        } catch {
          /* The next attempt reports the problem. */
        }
        notify(t('라이브러리가 변경되었습니다. 선택을 확인한 뒤 다시 등록하세요.'), true);
      } else notify(t('등록 실패: {0}', [message(error)]), true);
    } finally {
      state.busy = false;
    }
  }
  const previewTitle = el('p', 'jobs-note', t('대상을 선택하고 미리보기를 누르세요.'));
  const positive = el('pre', '', '—');
  const previewWarnings = el('div');
  const negative = el('pre', '', '—');
  const actionFormula = el('span', 'jobs-formula');
  const enqueueButton = btn(t('0장 등록'), enqueue, 'jobs-primary');
  enqueueButton.disabled = true;
  function renderPreview() {
    previewSection.replaceChildren(el('h2', '', t('첫 번째 조합 미리보기')));
    const row = el('div', 'jobs-row');
    row.append(
      btn(t('미리보기'), preview, 'jobs-muted'),
      btn(t('워크플로 다운로드'), workflow, 'jobs-muted'),
      btn(t('이 설정으로 단일 생성'), () => toLab(true), 'jobs-muted'),
      btn(t('실험실에서 열기'), () => toLab(false), 'jobs-muted'),
    );
    previewSection.append(
      row,
      previewTitle,
      previewWarnings,
      el('h3', '', t('긍정 프롬프트')),
      positive,
      el('h3', '', t('제외 프롬프트')),
      negative,
    );
  }
  function renderAll() {
    renderCharacters();
    renderCombination();
    renderOutfits();
    renderSlots();
    renderExpressions();
    renderPieces();
    renderSettings();
    renderOverrides();
    renderSummary();
    renderPreview();
    actions.replaceChildren(actionFormula, enqueueButton);
  }

  // ---- view lifecycle -------------------------------------------------------------------

  async function enter(params = new URLSearchParams()) {
    if ('BroadcastChannel' in window) {
      state.channel = new BroadcastChannel(`${STORE}:tabs`);
      state.channel.onmessage = (event) => {
        if (event.data?.tab !== state.tab) return;
        if (event.data.type === 'hello')
          state.channel.postMessage({type: 'occupied', tab: state.tab});
        if (event.data.type === 'occupied') {
          state.tab = freshTabId();
          session?.setItem(`${STORE}:tab`, state.tab);
          persist();
        }
      };
      state.channel.postMessage({type: 'hello', tab: state.tab});
    }
    try {
      const [works, comfy] = await Promise.all([ctx.api('/api/works'), ctx.api('/api/comfy')]);
      state.works = arr(works.works);
      state.comfy = comfy;
      workSelect.replaceChildren(
        opt('', t('작품 선택')),
        ...state.works.map((w) => opt(w.id, `${w.name || w.id} · ${w.id}`)),
      );
      const preferred = params.get('work') || session?.getItem(`${STORE}:work`) || '';
      const requested = state.works.some((w) => w.id === preferred)
        ? preferred
        : state.works[0]?.id || '';
      const saved = normalizeDraft(readDraft(requested));
      state.draft = {...defaults(), ...saved, work: requested};
      if (!saved) state.draft.settings = copy(comfy.defaults || {});
      workSelect.value = requested;
      await loadCatalog();
      await loadVersion();
      if (saved?.libraryRevision && saved.libraryRevision !== state.version)
        notify(t('라이브러리가 변경되었습니다. 선택과 프롬프트를 확인하세요.'));
      if (!comfy.connected)
        notify(t('ComfyUI 연결 안 됨{0}', [comfy.error ? ` · ${comfy.error}` : '']), true);
    } catch (error) {
      notify(t('생성 화면을 불러오지 못했습니다: {0}', [message(error)]), true);
    }
  }
  function leave() {
    state.channel?.close();
    state.channel = null;
    persist();
  }
  return {element: root, enter, leave};
}
