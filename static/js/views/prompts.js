// Prompt library: pieces by category folder, in three scopes (global / work / character),
// plus outfit sets, character appearance and presets.

import {
  MODEL_FAMILY_LABELS,
  SCOPE_LABELS,
  characterOf,
  folderTree,
  levelLabel,
  orderedLevels,
  parseCategory,
  modelFamily,
  scopeLabel,
  visibleOutfitSets,
} from '../lib/library.js';
import {formatPromptLines} from '../lib/prompt_format.js';
import {t, tr} from '../core/i18n.js';
import {withTagComplete} from '../core/tag_input.js';

const KEY = 'asset-studio-library-v2';
const KIND_LABEL = {
  work: t('common.work'),
  character: t('common.character'),
  piece: t('prompts.piece_2'),
  outfit_set: t('common.outfit_set'),
  preset: t('prompts.preset'),
};
const PRESET_LABEL = {
  generation: t('common.generation_settings'),
  combination: t('common.combination_presets'),
  expression_set: t('prompts.expression_sets'),
};
const ADDRESS_FIELDS = ['scope', 'work_id', 'character_id', 'category', 'preset_type'];
// Sidebar order of the piece folders; roles added to the definition later follow.
const ROLE_ORDER = ['outfit', 'expression', 'composition', 'artist', 'common'];
const RENAMABLE = ['work', 'character', 'outfit_set'];
const MOVABLE = ['piece', 'outfit_set'];
// Filled in by the server from the file location; never sent back.
const DERIVED = ['category', 'role', 'bucket', 'scope', 'work_id', 'character_id'];
const PROMPT_HELP = t('prompts.one_tag_or_one_full_sentence');
const CODE = /^[A-Za-z0-9_-]{1,64}$/;

const arr = (value) => (Array.isArray(value) ? value : []);
const lines = (value) =>
  Array.isArray(value) ? value.join('\n') : value == null ? '' : String(value);
const split = (value) =>
  String(value)
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
const clone = (value) => JSON.parse(JSON.stringify(value));
const safe = (value) => String(value ?? '');
const elt = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};
const button = (text, action, className = '') => {
  const node = elt('button', className, text);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
};
const option = (value, text) => {
  const node = elt('option', '', text);
  node.value = value;
  return node;
};
const select = (items, value) => {
  const node = elt('select');
  for (const [key, text] of items) node.append(option(key, text));
  node.value = value;
  return node;
};
const field = (label, control, hint) => {
  const wrap = elt('label', 'lib-field');
  wrap.append(elt('span', '', label), control);
  if (hint) wrap.append(elt('small', '', hint));
  return wrap;
};
const textarea = (value, rows = 6) => {
  const node = elt('textarea');
  node.value = value;
  node.rows = rows;
  return node;
};
const input = (value = '') => {
  const node = elt('input');
  node.value = value;
  return node;
};
const freshTabId = () =>
  globalThis.crypto?.randomUUID?.() ||
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
const identity = (s) =>
  [s.kind, ...ADDRESS_FIELDS.map((key) => s[key] || ''), s.id].map(safe).join('|');
const asError = (error) => safe(error?.message || error);
const isConflict = (error) => error?.status === 409;
const endpoint = (kind, action) =>
  kind === 'piece'
    ? `/api/pieces/${action}`
    : kind === 'outfit_set'
      ? `/api/outfit-sets/${action}`
      : `/api/library/${action}`;
const addressOf = (selection) => {
  const address = {kind: selection.kind};
  for (const key of ADDRESS_FIELDS) if (selection[key]) address[key] = selection[key];
  return address;
};

export function createLibrary(ctx) {
  const root = elt('section');
  root.id = 'app-library';
  const state = {
    works: [],
    catalog: null,
    work: '',
    view: {scope: 'global', character: ''},
    selected: null,
    record: null,
    revision: null,
    draft: null,
    conflict: false,
    search: '',
    open: new Map(),
    busy: false,
    request: 0,
    tab: '',
    channel: null,
  };
  const storage = (() => {
    try {
      localStorage.setItem(`${KEY}:test`, '1');
      localStorage.removeItem(`${KEY}:test`);
      return localStorage;
    } catch {
      return null;
    }
  })();
  const session = (() => {
    try {
      return sessionStorage;
    } catch {
      return null;
    }
  })();
  state.tab = session?.getItem(`${KEY}:tab`) || freshTabId();
  session?.setItem(`${KEY}:tab`, state.tab);

  // ---- drafts (kept per browser tab until saved) ------------------------------

  const draftPrefix = () => `${KEY}:draft:${state.tab}:`;
  const draftKey = (selection) => draftPrefix() + identity(selection);
  const readJSON = (key) => {
    try {
      return JSON.parse(storage?.getItem(key) || 'null');
    } catch {
      return null;
    }
  };
  const readDraft = (selection) => readJSON(draftKey(selection))?.draft || null;
  const writeDraft = () => {
    if (state.selected && state.draft)
      storage?.setItem(
        draftKey(state.selected),
        JSON.stringify({selection: state.selected, draft: state.draft}),
      );
  };
  const clearDraft = (selection) => storage?.removeItem(draftKey(selection));
  const allDrafts = () => {
    if (!storage) return [];
    const result = [];
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (!key?.startsWith(draftPrefix())) continue;
      const saved = readJSON(key);
      if (saved?.selection && saved.draft) result.push(saved);
    }
    return result;
  };
  const rememberView = () =>
    storage?.setItem(
      `${KEY}:view`,
      JSON.stringify({work: state.work, view: state.view, selected: state.selected}),
    );

  // ---- layout -------------------------------------------------------------------

  const workSelect = elt('select');
  const scopeBar = elt('div', 'lib-scopes');
  scopeBar.setAttribute('role', 'tablist');
  const characterSelect = elt('select');
  const characterRow = elt('div', 'lib-works');
  const search = input();
  search.type = 'search';
  search.placeholder = t('prompts.search_name_or_code');
  const tree = elt('nav', 'lib-tree');
  tree.setAttribute('aria-label', t('prompts.library_item'));
  const editor = elt('div', 'lib-editor');
  const status = elt('p', 'lib-status');
  status.setAttribute('role', 'status');
  const sidebar = elt('aside', 'lib-sidebar');
  const main = elt('main', 'lib-main');
  const heading = elt('header', 'lib-heading');
  heading.append(elt('h1', '', t('common.prompt_library')), elt('span', 'lib-heading-actions'));
  heading.lastChild.append(
    button(t('prompts.import_sample'), importSample, 'lib-muted'),
    button(t('prompts.jobs'), () => ctx.navigate?.('/jobs'), 'lib-muted'),
  );
  const worksBar = elt('div', 'lib-works');
  worksBar.append(
    field(t('common.work'), workSelect),
    button(t('prompts.work'), () => newEntity({kind: 'work'})),
  );
  characterRow.append(
    field(t('common.character'), characterSelect),
    button(t('prompts.character'), () => newEntity({kind: 'character', work_id: state.work})),
  );
  sidebar.append(
    worksBar,
    field(t('common.scope'), scopeBar),
    characterRow,
    field(t('common.search'), search),
    tree,
    button(t('prompts.trash'), showTrash, 'lib-muted'),
  );
  main.append(status, editor);
  root.append(heading, sidebar, main);
  workSelect.addEventListener('change', () => changeWork(workSelect.value));
  characterSelect.addEventListener('change', () => {
    state.view.character = characterSelect.value;
    rememberView();
    renderTree();
  });
  search.addEventListener('input', () => {
    state.search = search.value.trim().toLocaleLowerCase();
    renderTree();
  });

  const report = (message, error = false) => {
    ctx.notify?.(message, error);
    status.textContent = message;
    status.classList.toggle('error', error);
  };
  const categories = () => state.catalog?.categories;
  const characters = () => arr(state.catalog?.characters);

  /** Where the sidebar is looking: scope plus its work / character. */
  function viewLocation() {
    const {scope, character} = state.view;
    if (scope === 'global') return {scope};
    if (scope === 'work') return {scope, work_id: state.work};
    return {scope, work_id: state.work, character_id: character};
  }
  function recordsAt(location, key) {
    if (location.scope === 'global') return arr(state.catalog?.[`global_${key}`]);
    if (location.scope === 'work') return arr(state.catalog?.[`work_${key}`]);
    return arr(characterOf(state.catalog, location.character_id)?.[key]);
  }
  /** Pieces a record stored at `location` may refer to: its own scope and the wider ones. */
  function reachablePieces(location) {
    const scopes = {global: ['global'], work: ['work', 'global']}[location.scope] || [
      'character',
      'work',
      'global',
    ];
    return scopes.flatMap((scope) => recordsAt({...location, scope}, 'pieces'));
  }
  const reachable = (location, bucket) =>
    reachablePieces(location).filter((piece) => piece.bucket === bucket);
  /** Outfit slots to offer: the defined ones plus any that reachable pieces already use. */
  function outfitSlots(location, extra = []) {
    return orderedLevels(categories(), 'outfit', [
      ...arr(categories().roles.outfit?.order),
      ...extra,
      ...reachablePieces(location)
        .filter((piece) => piece.role === 'outfit')
        .map((piece) => piece.slot),
    ]);
  }
  /** Keep the sidebar on the scope of the record being edited. */
  function syncView(selection) {
    if (selection.kind === 'work') state.view.scope = 'work';
    else if (selection.kind === 'preset') state.view.scope = 'global';
    else if (selection.kind === 'character')
      state.view = {scope: 'character', character: selection.id};
    else if (selection.scope) {
      state.view.scope = selection.scope;
      if (selection.character_id) state.view.character = selection.character_id;
    }
  }

  // ---- sidebar ------------------------------------------------------------------

  function renderWorks() {
    workSelect.replaceChildren(
      option('', t('common.choose_a_work')),
      ...state.works.map((w) => option(w.id, `${w.name || w.id} · ${w.id}`)),
    );
    workSelect.value = state.work;
  }
  function renderScopes() {
    scopeBar.replaceChildren();
    for (const scope of ['global', 'work', 'character']) {
      const tab = button(SCOPE_LABELS[scope], () => changeScope(scope), 'lib-scope');
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(state.view.scope === scope));
      tab.disabled = scope !== 'global' && !state.work;
      scopeBar.append(tab);
    }
    characterRow.hidden = state.view.scope !== 'character';
    characterSelect.replaceChildren(
      ...characters().map((c) => option(c.id, `${c.name || c.id} · ${c.id}`)),
    );
    if (!characters().some((c) => c.id === state.view.character))
      state.view.character = characters()[0]?.id || '';
    characterSelect.value = state.view.character;
  }
  function changeScope(scope) {
    state.view.scope = scope;
    rememberView();
    renderScopes();
    renderTree();
  }
  function matches(...values) {
    return !state.search || values.join(' ').toLocaleLowerCase().includes(state.search);
  }
  function addItem(parent, selection, title, record = null) {
    const row = button(title, () => choose(selection), 'lib-item');
    row.title = title;
    if (record) {
      const family = modelFamily(record);
      row.prepend(elt('small', `lib-family lib-family-${family}`, MODEL_FAMILY_LABELS[family]));
    }
    row.classList.toggle(
      'active',
      !!state.selected && identity(state.selected) === identity(selection),
    );
    if (readDraft(selection)) row.append(elt('b', 'lib-dot', ' ●'));
    parent.append(row);
  }
  function group(parent, key, title, defaultOpen = false) {
    const box = elt('details', 'lib-group');
    box.open = !!state.search || (state.open.has(key) ? state.open.get(key) : defaultOpen);
    box.addEventListener('toggle', () => {
      if (!state.search) state.open.set(key, box.open);
    });
    const summary = elt('summary', '', title);
    summary.title = title;
    box.append(summary);
    parent.append(box);
    return box;
  }
  function countPieces(node) {
    return node.pieces.length + node.children.reduce((sum, child) => sum + countPieces(child), 0);
  }
  function renderFolder(parent, node, role, depth, location) {
    const shown = node.pieces.filter((piece) => matches(piece.name, piece.id, node.path));
    const definition = categories().roles[role];
    const label =
      depth === 0
        ? tr(definition.label || role)
        : depth === 1 && definition.level
          ? levelLabel(categories(), role, node.name)
          : node.name;
    const box = group(
      parent,
      `${identity({kind: 'folder', ...location})}:${node.path}`,
      `${label} (${countPieces(node)})`,
    );
    if (depth) box.classList.add('lib-nested');
    for (const piece of shown)
      addItem(
        box,
        {kind: 'piece', ...location, category: piece.category, id: piece.id},
        `${piece.name || piece.id} · ${piece.id}`,
        piece,
      );
    for (const child of node.children) renderFolder(box, child, role, depth + 1, location);
    if (box.querySelector('.lib-item.active')) box.open = true;
    // A role with a level (slot, rating, ...) only holds pieces below that level.
    if (depth > 0 || !definition.level)
      box.append(
        button(
          t('prompts.piece'),
          () => newEntity({kind: 'piece', ...location, category: node.path}),
          'lib-add',
        ),
      );
    else
      box.append(
        button(
          t('prompts.piece_in_a_new_subcategory'),
          () => newEntity({kind: 'piece', ...location, category: `${node.path}/`}),
          'lib-add',
        ),
      );
  }
  function renderTree() {
    tree.replaceChildren();
    const drafts = allDrafts();
    if (drafts.length) {
      const box = group(tree, 'drafts', t('prompts.unsaved_draft_2', [drafts.length]), true);
      for (const {selection, draft} of drafts)
        addItem(
          box,
          selection,
          `${KIND_LABEL[selection.kind]} · ${draft.name || selection.id} · ${selection.id}`,
        );
    }
    if (!state.catalog) {
      tree.append(elt('p', 'lib-empty', t('prompts.loading')));
      return;
    }
    const location = viewLocation();
    if (location.scope !== 'global' && !state.work) {
      tree.append(elt('p', 'lib-empty', t('prompts.choose_a_work_or_create_a')));
      return;
    }
    if (location.scope === 'character' && !location.character_id) {
      tree.append(elt('p', 'lib-empty', t('prompts.no_characters_create_one')));
      return;
    }
    if (location.scope === 'work')
      addItem(
        tree,
        {kind: 'work', id: state.work},
        t('prompts.work_2', [state.catalog.work?.name || state.work]),
        state.catalog.work,
      );
    if (location.scope === 'character') {
      const character = characterOf(state.catalog, location.character_id);
      addItem(
        tree,
        {kind: 'character', work_id: state.work, id: character.id},
        t('prompts.appearance', [character.name || character.id, character.id]),
        character,
      );
    }
    const sets = recordsAt(location, 'outfit_sets');
    const setBox = group(
      tree,
      `${identity({kind: 'sets', ...location})}`,
      t('prompts.outfit_set_2', [sets.length]),
    );
    for (const outfitSet of sets)
      if (matches(outfitSet.name, outfitSet.id))
        addItem(
          setBox,
          {kind: 'outfit_set', ...location, id: outfitSet.id},
          `${outfitSet.name || outfitSet.id} · ${outfitSet.id}`,
          outfitSet,
        );
    if (setBox.querySelector('.lib-item.active')) setBox.open = true;
    setBox.append(
      button(
        t('prompts.outfit_set'),
        () => newEntity({kind: 'outfit_set', ...location}),
        'lib-add',
      ),
    );
    const pieces = recordsAt(location, 'pieces');
    const roles = Object.keys(categories().roles);
    const ordered = [
      ...ROLE_ORDER.filter((role) => roles.includes(role)),
      ...roles.filter((role) => !ROLE_ORDER.includes(role)),
    ];
    for (const role of ordered)
      renderFolder(tree, folderTree(categories(), role, pieces), role, 0, location);
    if (location.scope === 'global')
      for (const [type, label] of Object.entries(PRESET_LABEL)) {
        const presets = arr(state.catalog.presets?.[type]);
        const box = group(tree, `preset:${type}`, `${label} (${presets.length})`);
        for (const preset of presets)
          if (matches(preset.name, preset.id))
            addItem(
              box,
              {kind: 'preset', preset_type: type, id: preset.id},
              `${preset.name || preset.id} · ${preset.id}`,
            );
        if (box.querySelector('.lib-item.active')) box.open = true;
        box.append(
          button(`+ ${label}`, () => newEntity({kind: 'preset', preset_type: type}), 'lib-add'),
        );
      }
  }

  // ---- loading ------------------------------------------------------------------

  /** Import a bundled sample as a new work and open it. */
  async function importSample() {
    if (ctx.preview) return ctx.notify(t('common.saving_is_off_in_preview_mode'), true);
    try {
      const sample = (await ctx.api('/api/samples')).samples[0];
      if (!sample) return;
      const question = t('prompts.import_the_sample_as_a_new', [sample.name, sample.description]);
      if (!window.confirm(question)) return;
      const result = await ctx.api('/api/samples/import', {id: sample.id});
      ctx.onLibraryChanged?.();
      await fetchWorks();
      await changeWork(result.work_id);
      ctx.notify(t('prompts.imported_the_sample_as_work', [result.work_id]));
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  async function fetchWorks() {
    state.works = arr((await ctx.api('/api/works')).works);
    renderWorks();
  }
  async function fetchCatalog() {
    const work = state.work;
    const catalog = await ctx.api(
      work ? `/api/catalog?work=${encodeURIComponent(work)}` : '/api/catalog',
    );
    if (state.work !== work) return;
    state.catalog = catalog;
    renderScopes();
    renderTree();
  }
  async function changeWork(work, selection = null) {
    ++state.request;
    state.work = work;
    state.catalog = null;
    if (!work) state.view.scope = 'global';
    Object.assign(state, {selected: null, record: null, draft: null, conflict: false});
    renderWorks();
    renderScopes();
    renderTree();
    renderEditor();
    try {
      await fetchCatalog();
      if (selection) await choose(selection);
    } catch (error) {
      report(t('prompts.could_not_load_the_library', [asError(error)]), true);
    }
    rememberView();
  }
  function entityURL(selection) {
    const query = new URLSearchParams({kind: selection.kind, id: selection.id});
    for (const [key, name] of [
      ['scope', 'scope'],
      ['work_id', 'work'],
      ['character_id', 'character'],
      ['category', 'category'],
      ['preset_type', 'preset_type'],
    ])
      if (selection[key]) query.set(name, selection[key]);
    return `/api/library/entity?${query}`;
  }
  async function choose(selection) {
    if (!selection) return;
    const work = selection.kind === 'work' ? selection.id : selection.work_id;
    const draft = readDraft(selection);
    if (work && work !== state.work && !(selection.kind === 'work' && draft?.isNew)) {
      await changeWork(work, selection);
      return;
    }
    const request = ++state.request;
    Object.assign(state, {
      selected: selection,
      record: null,
      revision: null,
      draft,
      conflict: false,
    });
    syncView(selection);
    rememberView();
    renderScopes();
    renderTree();
    renderEditor();
    if (draft?.isNew) return;
    try {
      const data = await ctx.api(entityURL(selection));
      if (request !== state.request) return;
      state.record = data.entity;
      state.revision = data.revision;
      if (!state.draft) state.draft = {...clone(data.entity), baseRevision: data.revision};
      else if (state.draft.baseRevision !== data.revision) {
        state.conflict = true;
        report(t('prompts.the_saved_item_changed_your_draft'), true);
      }
      renderEditor();
    } catch (error) {
      if (request !== state.request) return;
      // Without a draft there is nothing to show for a record that no longer exists.
      if (!state.draft) state.selected = null;
      renderEditor();
      report(t('prompts.could_not_load_the_item', [asError(error)]), true);
    }
  }

  // ---- creating -------------------------------------------------------------------

  function newEntity(base) {
    ++state.request;
    const kind = base.kind;
    if (kind !== 'work' && kind !== 'preset' && base.scope !== 'global' && !state.work) return;
    const title =
      kind === 'preset'
        ? PRESET_LABEL[base.preset_type]
        : kind === 'piece'
          ? t('prompts.piece_2')
          : KIND_LABEL[kind];
    const panel = elt('div', 'lib-new');
    panel.append(elt('h2', '', t('prompts.new', [title])));
    if (kind === 'piece' || kind === 'outfit_set')
      panel.append(elt('p', 'lib-path', t('prompts.scope', [scopeLabel(base)])));
    const category = input(base.category || '');
    const id = input();
    id.placeholder = t('prompts.letters_digits_and');
    const name = input();
    name.placeholder = t('common.name');
    if (kind === 'piece')
      panel.append(
        field(t('prompts.category_path'), category, t('prompts.a_folder_path_e_g_outfit')),
      );
    panel.append(
      field(
        t('prompts.code'),
        id,
        kind === 'piece' ? t('prompts.must_be_unique_within_its_category') : '',
      ),
      field(t('common.name'), name),
    );
    panel.append(
      button(
        t('prompts.make_a_draft'),
        () => {
          const entityId = id.value.trim();
          const entityName = name.value.trim();
          if (!CODE.test(entityId) || !entityName) {
            report(t('prompts.check_the_code_and_name'), true);
            return;
          }
          const selection = {...base, id: entityId};
          const payload = {id: entityId, name: entityName};
          if (kind === 'piece') {
            selection.category = category.value.trim().replace(/^\/+|\/+$/g, '');
            const parsed = parseCategory(categories(), selection.category);
            if (!parsed) {
              report(t('prompts.check_the_category_path_the_first'), true);
              return;
            }
            if (parsed.role === 'expression' && !/^\d{3}$/.test(entityId)) {
              report(t('prompts.expression_codes_are_three_digits'), true);
              return;
            }
            Object.assign(payload, {prompt: [], negative_prompt: []});
          }
          if (kind === 'work' || kind === 'character')
            Object.assign(payload, {prompt: [], negative_prompt: []});
          if (kind === 'outfit_set') payload.slots = {};
          if (base.preset_type === 'generation') payload.settings = {};
          if (base.preset_type === 'expression_set') payload.expressions = [];
          Object.assign(state, {
            selected: selection,
            record: null,
            revision: null,
            conflict: false,
          });
          state.draft = {...payload, isNew: true, baseRevision: null};
          writeDraft();
          renderEditor();
          renderTree();
        },
        'lib-primary',
      ),
    );
    editor.replaceChildren(panel);
  }

  // ---- editor ---------------------------------------------------------------------

  const dirtyBadge = elt('span', 'lib-dirty');
  function update(prop, value) {
    state.draft[prop] = value;
    writeDraft();
    dirtyBadge.textContent = t('prompts.unsaved_draft');
  }
  function textControl(prop, label, help = PROMPT_HELP, rows = 6) {
    const node = textarea(lines(state.draft[prop]), rows);
    node.addEventListener('input', () => update(prop, split(node.value)));
    const control = field(label, withTagComplete(node, ctx.api, null, {separator: ''}), help);
    control.append(
      button(
        t('prompts.tidy_lines'),
        () => {
          const formatted = formatPromptLines(node.value);
          if (formatted === node.value) return;
          node.value = formatted;
          update(prop, split(formatted));
        },
        'lib-muted',
      ),
    );
    return control;
  }
  function jsonControl(prop, label, help, fallback) {
    const node = textarea(JSON.stringify(state.draft[prop] ?? fallback, null, 2), 11);
    node.spellcheck = false;
    node.addEventListener('input', () => update(`${prop}Text`, node.value));
    return field(label, node, help);
  }
  function notesControl() {
    const value = state.draft.notes;
    const node = textarea(
      value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2),
      3,
    );
    node.addEventListener('input', () => update('notes', node.value));
    return field(t('prompts.notes_not_used_for_generation'), node);
  }
  function pieceFields(s, d) {
    const parsed = parseCategory(categories(), s.category);
    const negativeTarget = parsed?.bucket === 'common/negative';
    editor.append(
      textControl(
        'prompt',
        negativeTarget ? t('prompts.text_for_the_negative_prompt') : t('common.positive_prompt'),
      ),
    );
    if (!negativeTarget) editor.append(textControl('negative_prompt', t('common.negative_prompt')));
    if (parsed?.role === 'expression') {
      const choices = reachable(s, 'composition').map((piece) => [
        piece.id,
        `${piece.name || piece.id} · ${piece.id} (${scopeLabel(piece)})`,
      ]);
      const composition = select([['', t('common.missing')], ...choices], d.composition_id || '');
      composition.addEventListener('change', () => update('composition_id', composition.value));
      editor.append(
        field(
          t('prompts.default_composition'),
          composition,
          t('prompts.used_when_no_composition_is_chosen'),
        ),
      );
    }
    if (parsed?.role === 'composition') {
      const box = elt('div', 'lib-checks');
      const slots = outfitSlots(viewLocation(), arr(d.suggest_slots)).filter(
        (slot) => slot !== 'full',
      );
      for (const slot of slots) {
        const check = elt('input');
        check.type = 'checkbox';
        check.checked = arr(d.suggest_slots).includes(slot);
        check.addEventListener('change', () => {
          const next = new Set(arr(state.draft.suggest_slots));
          if (check.checked) next.add(slot);
          else next.delete(slot);
          update('suggest_slots', orderedLevels(categories(), 'outfit', [...next]));
        });
        const label = elt('label', 'lib-check');
        label.append(check, elt('span', '', levelLabel(categories(), 'outfit', slot)));
        box.append(label);
      }
      editor.append(
        field(
          t('prompts.suggested_slots'),
          box,
          t('prompts.outfit_slots_ticked_when_this_composition'),
        ),
      );
    }
  }
  function outfitSetFields(s, d) {
    const slots = d.slots && typeof d.slots === 'object' ? d.slots : {};
    const candidates = (slot) => reachable(s, `outfit/${slot}`);
    const allSlots = outfitSlots(s, Object.keys(slots));
    const table = elt('div', 'lib-slots');
    for (const slot of allSlots) {
      const row = elt('div', 'lib-slot-row');
      const current = slots[slot] ? `${slots[slot].scope}:${slots[slot].id}` : '';
      const choices = candidates(slot).map((piece) => [
        `${piece.scope}:${piece.id}`,
        `${piece.name || piece.id} · ${piece.id} (${SCOPE_LABELS[piece.scope]})`,
      ]);
      if (current && !choices.some(([value]) => value === current))
        choices.unshift([current, t('prompts.not_found', [slots[slot].id])]);
      const picker = select([['', t('prompts.none')], ...choices], current);
      picker.addEventListener('change', () => {
        const next = {...state.draft.slots};
        if (picker.value) {
          const [scope, ...rest] = picker.value.split(':');
          next[slot] = {scope, id: rest.join(':')};
        } else delete next[slot];
        update('slots', next);
        renderEditor();
      });
      row.append(elt('strong', '', levelLabel(categories(), 'outfit', slot)), picker);
      const chosen = candidates(slot).find((piece) => `${piece.scope}:${piece.id}` === current);
      if (chosen) {
        row.append(
          button(
            t('prompts.open_piece'),
            () =>
              choose({
                kind: 'piece',
                scope: chosen.scope,
                work_id: chosen.work_id,
                character_id: chosen.character_id,
                category: chosen.category,
                id: chosen.id,
              }),
            'lib-muted',
          ),
        );
        row.append(elt('p', 'lib-slot-preview', lines(chosen.prompt).replace(/\n/g, ' · ')));
      } else
        row.append(
          button(
            t('prompts.new_piece'),
            () =>
              newEntity({
                kind: 'piece',
                scope: s.scope,
                work_id: s.work_id,
                character_id: s.character_id,
                category: `outfit/${slot}`,
              }),
            'lib-muted',
          ),
        );
      table.append(row);
    }
    editor.append(
      field(t('prompts.pieces_by_slot'), table, t('prompts.the_pieces_this_set_points_to')),
    );
    editor.append(
      textControl(
        'negative_prompt',
        t('prompts.set_negative_prompt'),
        t('prompts.always_applied_whatever_slots_are_chosen'),
        4,
      ),
    );
    const props = textarea(safe(d.props?.note), 2);
    props.addEventListener('input', () =>
      update('props', {
        ...(state.draft.props || {}),
        note: props.value,
        pieces: arr(state.draft.props?.pieces),
      }),
    );
    editor.append(field(t('prompts.props_note'), props, t('prompts.props_used_only_in_full_body')));
  }
  function moveControl(s) {
    const box = elt('details', 'lib-move');
    box.append(elt('summary', '', t('prompts.move_scope')));
    const targets = [['global', t('common.global')]];
    if (state.work) {
      targets.push([`work|${state.work}`, t('common.shared_in', [state.work])]);
      for (const character of characters())
        targets.push([
          `character|${state.work}|${character.id}`,
          t('prompts.character_2', [character.name || character.id, character.id]),
        ]);
    }
    const current = [s.scope, s.work_id, s.character_id].filter(Boolean).join('|');
    const target = select(targets, current);
    const category = input(s.category || '');
    box.append(field(t('prompts.target_scope'), target));
    if (s.kind === 'piece')
      box.append(
        field(t('prompts.category_path'), category, t('prompts.you_can_also_change_the_folder')),
      );
    box.append(
      elt('p', 'lib-hint', t('prompts.outfit_sets_that_point_to_this')),
      button(t('prompts.move'), () => move(s, target.value, category.value.trim()), 'lib-primary'),
    );
    return box;
  }
  function renderEditor() {
    editor.replaceChildren();
    const s = state.selected;
    const d = state.draft;
    if (!s) {
      editor.append(elt('p', 'lib-empty', t('prompts.select_an_item_on_the_left')));
      return;
    }
    if (!d) {
      editor.append(elt('p', 'lib-empty', t('prompts.loading_the_item')));
      return;
    }
    const top = elt('div', 'lib-editor-head');
    const title =
      s.kind === 'preset'
        ? PRESET_LABEL[s.preset_type]
        : s.kind === 'character'
          ? t('prompts.character_appearance')
          : KIND_LABEL[s.kind];
    top.append(elt('h2', '', `${title} · ${s.id}`), dirtyBadge);
    dirtyBadge.textContent = readDraft(s) ? t('prompts.unsaved_draft') : '';
    editor.append(top);
    if (MOVABLE.includes(s.kind))
      editor.append(
        elt(
          'p',
          'lib-path',
          t('prompts.scope_2', [
            scopeLabel(s),
            s.kind === 'piece' ? t('prompts.category', [s.category]) : '',
          ]),
        ),
      );
    if (s.kind === 'character')
      editor.append(elt('p', 'lib-path', t('prompts.work_3', [s.work_id])));
    if (state.conflict && state.record) {
      const comparison = elt('details', 'lib-conflict');
      comparison.append(
        elt('summary', '', t('prompts.show_the_latest_saved_version_your')),
        elt('pre', '', JSON.stringify(state.record, null, 2)),
      );
      editor.append(comparison);
    }
    if (RENAMABLE.includes(s.kind)) {
      const id = input(d.id);
      id.addEventListener('input', () => update('id', id.value.trim()));
      editor.append(field(t('prompts.code'), id, t('prompts.after_a_change_the_old_code')));
    }
    const name = input(safe(d.name));
    name.addEventListener('input', () => update('name', name.value));
    editor.append(field(t('common.name'), name));
    if (['work', 'character', 'piece', 'outfit_set'].includes(s.kind)) {
      const family = select(Object.entries(MODEL_FAMILY_LABELS), modelFamily(d));
      family.addEventListener('change', () => update('model_family', family.value));
      editor.append(
        field(t('common.model_family'), family, t('prompts.marks_which_model_this_prompt_was')),
      );
    }
    if (s.kind === 'work') {
      editor.append(
        textControl('prompt', t('prompts.work_wide_positive_prompt')),
        textControl('negative_prompt', t('prompts.work_wide_negative_prompt')),
      );
    }
    if (s.kind === 'character') {
      editor.append(
        textControl('prompt', t('prompts.appearance_prompt')),
        textControl('negative_prompt', t('common.negative_prompt')),
      );
      const character = characterOf(state.catalog, s.id);
      const sets = visibleOutfitSets(state.catalog, character).map((item) => [
        item.id,
        `${item.name || item.id} · ${item.id} (${SCOPE_LABELS[item.scope]})`,
      ]);
      const chooser = select([['', t('common.missing')], ...sets], d.default_outfit || '');
      chooser.addEventListener('change', () => update('default_outfit', chooser.value));
      editor.append(field(t('prompts.default_outfit_set'), chooser));
    }
    if (s.kind === 'piece') pieceFields(s, d);
    if (s.kind === 'outfit_set') outfitSetFields(s, d);
    if (s.preset_type === 'generation') {
      editor.append(
        jsonControl(
          'settings',
          t('prompts.generation_settings_json'),
          t('prompts.model_loras_sampler_and_so_on'),
          {},
        ),
      );
    }
    if (s.preset_type === 'expression_set')
      editor.append(
        jsonControl(
          'expressions',
          t('prompts.expression_list_json'),
          t('prompts.an_array_like'),
          [],
        ),
      );
    if (s.preset_type === 'combination')
      editor.append(elt('p', 'lib-hint', t('prompts.a_combination_preset_s_content_is')));
    editor.append(notesControl());
    const controls = elt('div', 'lib-actions');
    controls.append(
      button(t('common.save'), save, 'lib-primary'),
      button(t('prompts.restore_saved_version'), restoreSaved, 'lib-muted'),
    );
    if (!d.isNew) controls.append(button(t('common.delete'), remove, 'lib-danger'));
    editor.append(controls);
    if (!d.isNew && MOVABLE.includes(s.kind)) editor.append(moveControl(s));
  }

  // ---- saving, moving, deleting -----------------------------------------------------

  function payloadForSave() {
    const payload = clone(state.draft);
    for (const key of [
      'isNew',
      'baseRevision',
      ...(state.selected.kind === 'piece' ? DERIVED : []),
    ])
      delete payload[key];
    const level = parseCategory(categories(), state.selected.category)?.level;
    if (level) delete payload[level];
    if (['character', 'outfit_set'].includes(state.selected.kind))
      for (const key of ['scope', 'work_id', 'character_id', 'pieces', 'outfit_sets'])
        delete payload[key];
    for (const prop of ['settings', 'expressions']) {
      if (!(`${prop}Text` in payload)) continue;
      try {
        payload[prop] = JSON.parse(payload[`${prop}Text`]);
      } catch {
        throw new Error(t('prompts.check_the_json', [prop]));
      }
      delete payload[`${prop}Text`];
    }
    return payload;
  }
  async function refresh() {
    await fetchWorks();
    await fetchCatalog();
    ctx.onLibraryChanged?.();
  }
  async function save() {
    if (state.busy || !state.selected || !state.draft) return;
    const s = clone(state.selected);
    const isNew = !!state.draft.isNew;
    let payload;
    try {
      payload = payloadForSave();
    } catch (error) {
      report(asError(error), true);
      return;
    }
    if (!safe(payload.name).trim()) {
      report(t('prompts.enter_a_name'), true);
      return;
    }
    if (!CODE.test(payload.id || '')) {
      report(t('prompts.codes_may_use_only_letters_digits'), true);
      return;
    }
    state.busy = true;
    try {
      const body = {
        ...addressOf(s),
        payload,
        expected_revision: isNew ? null : (state.draft.baseRevision ?? state.revision),
      };
      if (!isNew && RENAMABLE.includes(s.kind) && payload.id !== s.id) body.original_id = s.id;
      const data = await ctx.api(endpoint(s.kind, 'save'), body);
      clearDraft(s);
      const selection = {...s, id: payload.id};
      Object.assign(state, {selected: selection, record: data.entity, revision: data.revision});
      state.conflict = false;
      state.draft = {...clone(data.entity), baseRevision: data.revision};
      if (s.kind === 'work') state.work = payload.id;
      if (s.kind === 'character' && state.view.character === s.id)
        state.view.character = payload.id;
      await refresh();
      rememberView();
      renderEditor();
      report(t('common.saved'));
    } catch (error) {
      if (isConflict(error)) {
        state.conflict = true;
        try {
          const latest = await ctx.api(entityURL(s));
          state.record = latest.entity;
          state.revision = latest.revision;
          renderEditor();
        } catch {
          /* The item may have been deleted or the code is taken. */
        }
      }
      report(t('common.could_not_save', [asError(error)]), true);
    } finally {
      state.busy = false;
    }
  }
  async function restoreSaved() {
    if (!state.selected) return;
    const s = clone(state.selected);
    const wasNew = !!state.draft?.isNew;
    clearDraft(s);
    if (wasNew) {
      Object.assign(state, {selected: null, draft: null});
      renderEditor();
      renderTree();
      return;
    }
    await choose(s);
    report(t('prompts.reloaded_the_saved_version'));
  }
  async function move(s, targetValue, category) {
    if (state.busy) return;
    const [scope, work_id, character_id] = targetValue.split('|');
    const to = {scope};
    if (work_id) to.work_id = work_id;
    if (character_id) to.character_id = character_id;
    if (s.kind === 'piece' && category) to.category = category.replace(/^\/+|\/+$/g, '');
    if (readDraft(s) && !window.confirm(t('prompts.there_is_an_unsaved_draft_discard'))) return;
    state.busy = true;
    try {
      const data = await ctx.api(endpoint(s.kind, 'move'), {
        ...addressOf(s),
        id: s.id,
        expected_revision: state.revision,
        to,
      });
      clearDraft(s);
      const selection = {...data.address};
      state.view.scope = selection.scope;
      if (selection.character_id) state.view.character = selection.character_id;
      Object.assign(state, {selected: selection, record: data.entity, revision: data.revision});
      state.draft = {...clone(data.entity), baseRevision: data.revision};
      await refresh();
      rememberView();
      renderEditor();
      report(t('prompts.moved_to', [scopeLabel(selection)]));
    } catch (error) {
      report(t('prompts.could_not_move', [asError(error)]), true);
    } finally {
      state.busy = false;
    }
  }
  async function remove() {
    const s = state.selected;
    if (!s || state.busy) return;
    const warning = ['work', 'character'].includes(s.kind)
      ? t('prompts.items_inside_it_go_to_the')
      : t('prompts.moves_the_item_to_the_trash');
    if (!window.confirm(t('prompts.delete', [KIND_LABEL[s.kind], s.id, warning]))) return;
    state.busy = true;
    try {
      await ctx.api(endpoint(s.kind, 'delete'), {
        ...addressOf(s),
        id: s.id,
        expected_revision: state.draft?.baseRevision ?? state.revision,
      });
      clearDraft(s);
      Object.assign(state, {selected: null, draft: null, record: null});
      await fetchWorks();
      if (s.kind === 'work') {
        state.work = state.works[0]?.id || '';
        if (!state.work) state.view.scope = 'global';
        renderWorks();
      }
      await fetchCatalog();
      ctx.onLibraryChanged?.();
      rememberView();
      renderEditor();
      report(t('prompts.moved_to_the_trash'));
    } catch (error) {
      report(t('prompts.could_not_delete', [asError(error)]), true);
    } finally {
      state.busy = false;
    }
  }
  async function showTrash() {
    ++state.request;
    let items;
    try {
      items = arr((await ctx.api('/api/library/trash')).items);
    } catch (error) {
      report(t('prompts.could_not_load_the_trash', [asError(error)]), true);
      return;
    }
    Object.assign(state, {selected: null, draft: null});
    renderTree();
    const panel = elt('div', 'lib-trash');
    panel.append(elt('h2', '', t('prompts.trash')));
    if (!items.length) panel.append(elt('p', 'lib-empty', t('prompts.the_trash_is_empty')));
    for (const item of items) {
      const row = elt('div', 'lib-trash-row');
      const kind =
        item.kind === 'preset'
          ? PRESET_LABEL[item.preset_type]
          : KIND_LABEL[item.kind] || item.kind;
      row.append(
        elt(
          'span',
          '',
          `${kind} · ${item.name || item.entity_id} · ${item.original_path} · ${item.deleted_at || ''}`,
        ),
        button(
          t('prompts.restore'),
          async () => {
            try {
              await ctx.api('/api/library/restore', {trash_id: item.id});
              await refresh();
              report(t('prompts.restored'));
              await showTrash();
            } catch (error) {
              report(t('prompts.could_not_restore', [asError(error)]), true);
            }
          },
          'lib-muted',
        ),
      );
      panel.append(row);
    }
    editor.replaceChildren(panel);
  }

  // ---- view lifecycle ---------------------------------------------------------------

  const beforeUnload = (event) => {
    if (allDrafts().length) {
      event.preventDefault();
      event.returnValue = '';
    }
  };
  async function enter(params = new URLSearchParams()) {
    window.addEventListener('beforeunload', beforeUnload);
    if ('BroadcastChannel' in window) {
      // Two tabs restored from one session would otherwise share a draft namespace.
      state.channel = new BroadcastChannel(`${KEY}:tabs`);
      state.channel.onmessage = (event) => {
        if (event.data?.tab !== state.tab) return;
        if (event.data.type === 'hello')
          state.channel.postMessage({type: 'occupied', tab: state.tab});
        else if (event.data.type === 'occupied') {
          state.tab = freshTabId();
          session?.setItem(`${KEY}:tab`, state.tab);
        }
      };
      state.channel.postMessage({type: 'hello', tab: state.tab});
    }
    try {
      await fetchWorks();
      const remembered = readJSON(`${KEY}:view`);
      const wanted = params.get('work') || remembered?.work || state.works[0]?.id || '';
      state.work = state.works.some((w) => w.id === wanted) ? wanted : '';
      if (remembered?.view && (state.work || remembered.view.scope === 'global'))
        state.view = {scope: remembered.view.scope, character: remembered.view.character || ''};
      else state.view.scope = state.work ? 'character' : 'global';
      renderWorks();
      await fetchCatalog();
      if (remembered?.selected && !params.get('work')) await choose(remembered.selected);
      else renderEditor();
    } catch (error) {
      report(t('prompts.could_not_load_the_library', [asError(error)]), true);
    }
  }
  function leave() {
    window.removeEventListener('beforeunload', beforeUnload);
    state.channel?.close();
    state.channel = null;
  }
  return {element: root, enter, leave};
}
