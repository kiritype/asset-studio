// LoRA menu: pick a character, choose training images, train, and register the results.
// Datasets and runs belong to one work/character; the registry decides what is applied.

import {visibleOutfitSets} from '../lib/library.js';
import {t, tr} from '../core/i18n.js';
import {withTagComplete} from '../core/tag_input.js';

const POLL_MS = 3000;
const ACTIVE = ['waiting_gpu', 'preprocessing', 'training'];
const RUN_LABELS = {
  waiting_gpu: t('lora.gpu_wait'),
  preprocessing: t('lora.preprocessing'),
  training: t('lora.training_2'),
  done: t('common.done'),
  failed: t('common.failed'),
  cancelled: t('common.cancel'),
  interrupted: t('common.interrupted'),
};
const FAMILY_LABELS = {anima: 'Anima', sdxl: 'SDXL·IL', shared: t('common.shared')};

const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const btn = (text, onClick, cls = '') => {
  const n = el('button', cls, text);
  n.type = 'button';
  n.addEventListener('click', onClick);
  return n;
};
const field = (text, control, hint) => {
  const n = el('label', 'lr-field');
  n.append(el('span', '', text), control);
  if (hint) n.append(el('small', '', hint));
  return n;
};
const input = (type, value, attrs = {}) => {
  const n = el('input');
  n.type = type;
  if (type === 'checkbox') n.checked = !!value;
  else n.value = value ?? '';
  for (const [key, val] of Object.entries(attrs)) n.setAttribute(key, val);
  return n;
};
const select = (choices, value) => {
  const n = el('select');
  for (const [key, text] of choices) {
    const option = el('option', '', text);
    option.value = key;
    n.append(option);
  }
  n.value = value ?? '';
  return n;
};
const arr = (value) => (Array.isArray(value) ? value : []);
const query = (values) => new URLSearchParams(values).toString();

export function createLora(ctx) {
  const root = el('section');
  root.id = 'app-lora';
  const state = {
    works: [],
    work: '',
    catalog: null,
    character: '',
    tab: 'dataset',
    datasets: [],
    runs: [],
    loras: [],
    options: null,
    dataset: '', // '' = a new dataset
    outfit: '',
    candidates: [],
    chosen: new Set(),
    draft: {name: '', character: '', outfit: ''},
    captions: {},
    train: null,
    timer: 0,
  };

  const header = el('header', 'lr-header');
  header.append(
    el('h1', '', 'LoRA'),
    el('p', '', t('lora.choose_training_images_per_character_train')),
  );
  const side = el('aside', 'lr-side');
  const main = el('div', 'lr-main');
  root.append(header, side, main);

  const who = () => ({work_id: state.work, character_id: state.character});
  const whoQuery = () => query({work: state.work, character: state.character});
  const character = () => arr(state.catalog?.characters).find((c) => c.id === state.character);
  const currentDataset = () => state.datasets.find((d) => d.id === state.dataset);
  const fail = (error) => ctx.notify(error.message || String(error), true);

  // ---- side: work and characters ------------------------------------------------------

  function renderSide() {
    const workSelect = select(
      state.works.map((w) => [w.id, `${w.id} · ${w.name || ''}`]),
      state.work,
    );
    workSelect.addEventListener('change', async () => {
      state.work = workSelect.value;
      state.character = '';
      await loadCatalog();
    });
    const list = el('div', 'lr-characters');
    for (const item of arr(state.catalog?.characters)) {
      const button = btn(`${item.id} ${item.name && item.name !== item.id ? item.name : ''}`, () =>
        chooseCharacter(item.id),
      );
      if (item.id === state.character) button.setAttribute('aria-current', 'true');
      list.append(button);
    }
    side.replaceChildren(field(t('common.work'), workSelect), list);
  }

  async function chooseCharacter(id) {
    state.character = id;
    state.dataset = '';
    state.candidates = [];
    state.chosen.clear();
    state.captions = {};
    renderSide();
    await loadCharacter();
  }

  // ---- dataset tab --------------------------------------------------------------------

  async function loadCandidates() {
    if (!state.outfit) {
      state.candidates = [];
      return;
    }
    const result = await ctx.api(`/api/lora/candidates?${whoQuery()}&outfit=${state.outfit}`);
    state.candidates = arr(result.items);
  }
  async function chooseDataset(id) {
    state.dataset = id;
    state.captions = {};
    const dataset = currentDataset();
    if (dataset) {
      state.outfit = dataset.outfit_set_id;
      state.chosen = new Set(dataset.items.map((item) => item.path));
      // A name the server chose (``{outfit} dataset``) arrives as a message to translate.
      const shown = tr(dataset.name) || '';
      state.draft = {
        name: shown,
        shownName: shown,
        character: dataset.triggers?.character || '',
        outfit: dataset.triggers?.outfit || '',
      };
    } else {
      state.outfit = state.outfit || character()?.default_outfit || '';
      state.draft = {name: '', character: '', outfit: ''};
      state.chosen = new Set();
    }
    await loadCandidates().catch(fail);
    // A new dataset starts from the images marked as adopted in the gallery.
    if (!dataset)
      for (const item of state.candidates) if (item.selected) state.chosen.add(item.path);
    renderMain();
  }
  async function saveDataset() {
    const triggers = {};
    if (state.draft.character.trim()) triggers.character = state.draft.character.trim();
    if (state.draft.outfit.trim()) triggers.outfit = state.draft.outfit.trim();
    const paths = state.candidates.filter((c) => state.chosen.has(c.path)).map((c) => c.path);
    try {
      const result = await ctx.api('/api/lora/datasets/save', {
        ...who(),
        id: state.dataset || undefined,
        outfit_set_id: state.outfit,
        // An untouched name is left to the server, which keeps the one it has.
        name:
          state.draft.name === state.draft.shownName
            ? undefined
            : state.draft.name.trim() || undefined,
        triggers: Object.keys(triggers).length ? triggers : undefined,
        paths,
      });
      ctx.notify(t('lora.saved_dataset_images', [result.entity.id, paths.length]));
      await loadCharacter();
      await chooseDataset(result.entity.id);
    } catch (error) {
      fail(error);
    }
  }
  async function datasetRevision(id) {
    const address = query({kind: 'dataset', ...who(), id});
    return ctx.api(`/api/library/entity?${address}`);
  }
  async function saveCaptions() {
    const dataset = currentDataset();
    const edits = Object.entries(state.captions);
    if (!dataset || !edits.length) return;
    try {
      const latest = await datasetRevision(dataset.id);
      const items = latest.entity.items.map((item) =>
        item.path in state.captions
          ? {...item, caption: state.captions[item.path], caption_edited: true}
          : item,
      );
      await ctx.api('/api/library/save', {
        kind: 'dataset',
        ...who(),
        payload: {...latest.entity, items},
        expected_revision: latest.revision,
      });
      ctx.notify(t('lora.saved_captions_captions_you_edited_are', [edits.length]));
      state.captions = {};
      await loadCharacter();
      renderMain();
    } catch (error) {
      fail(error);
    }
  }
  async function recaption() {
    const dataset = currentDataset();
    if (!dataset) return;
    try {
      const latest = await datasetRevision(dataset.id);
      await ctx.api('/api/lora/datasets/captions', {
        ...who(),
        id: dataset.id,
        expected_revision: latest.revision,
      });
      ctx.notify(t('lora.rebuilt_the_automatic_captions_captions_you'));
      await loadCharacter();
      renderMain();
    } catch (error) {
      fail(error);
    }
  }

  function datasetTab() {
    const box = el('div');
    const dataset = currentDataset();
    const chooser = select(
      [
        ['', t('lora.new_dataset')],
        ...state.datasets.map((d) => [
          d.id,
          t('lora.images', [d.id, tr(d.name) || '', d.items.length]),
        ]),
      ],
      state.dataset,
    );
    chooser.addEventListener('change', () => chooseDataset(chooser.value));
    const outfits = visibleOutfitSets(state.catalog, character()).map((o) => [
      o.id,
      `${o.id} · ${o.name || ''}`,
    ]);
    const outfit = select([['', t('lora.choose_an_outfit_set')], ...outfits], state.outfit);
    outfit.disabled = !!dataset; // A dataset belongs to one outfit set.
    outfit.addEventListener('change', async () => {
      state.outfit = outfit.value;
      state.chosen.clear();
      await loadCandidates().catch(fail);
      for (const item of state.candidates) if (item.selected) state.chosen.add(item.path);
      renderMain();
    });
    const name = input('text', state.draft.name, {placeholder: t('lora.e_g_casual_v3')});
    name.addEventListener('input', () => (state.draft.name = name.value));
    const triggerCharacter = input('text', state.draft.character, {
      placeholder: `${state.work}_${state.character}`.toLowerCase(),
    });
    triggerCharacter.addEventListener(
      'input',
      () => (state.draft.character = triggerCharacter.value),
    );
    const triggerOutfit = input('text', state.draft.outfit, {
      placeholder: t('lora.leave_empty_to_skip'),
    });
    triggerOutfit.addEventListener('input', () => (state.draft.outfit = triggerOutfit.value));
    const top = el('div', 'lr-grid2');
    top.append(
      field(t('lora.dataset'), chooser),
      field(t('common.outfit_set'), outfit),
      field(t('common.name'), name),
      field(
        t('lora.character_trigger'),
        triggerCharacter,
        t('lora.a_word_unique_to_this_character'),
      ),
      field(t('lora.outfit_trigger'), triggerOutfit, t('lora.only_to_learn_the_outfit_separately')),
    );
    box.append(top);

    const tools = el('div', 'lr-row');
    const picked = state.candidates.filter((c) => state.chosen.has(c.path)).length;
    tools.append(
      el('strong', '', t('lora.selected', [picked, state.candidates.length])),
      btn(t('lora.adopted_only'), () => {
        state.chosen = new Set(state.candidates.filter((c) => c.selected).map((c) => c.path));
        renderMain();
      }),
      btn(t('lora.all_passed_images'), () => {
        state.chosen = new Set(
          state.candidates.filter((c) => c.human_status === 'pass').map((c) => c.path),
        );
        renderMain();
      }),
      btn(t('common.clear_selection'), () => {
        state.chosen.clear();
        renderMain();
      }),
    );
    const save = btn(
      dataset ? t('lora.update_dataset') : t('lora.create_dataset'),
      saveDataset,
      'lr-primary',
    );
    save.disabled = !picked || !state.outfit || !!ctx.preview;
    tools.append(save);
    box.append(tools);

    const grid = el('div', 'lr-images');
    if (!state.outfit) grid.append(el('p', 'lr-muted', t('lora.choose_an_outfit_set_2')));
    else if (!state.candidates.length)
      grid.append(el('p', 'lr-muted', t('lora.no_images_for_this_outfit_set')));
    for (const item of state.candidates) {
      const card = el('label', 'lr-image');
      if (state.chosen.has(item.path)) card.classList.add('chosen');
      const check = input('checkbox', state.chosen.has(item.path));
      check.addEventListener('change', () => {
        if (check.checked) state.chosen.add(item.path);
        else state.chosen.delete(item.path);
        card.classList.toggle('chosen', check.checked);
        renderMain();
      });
      const image = el('img');
      image.src = item.thumbnail_url;
      image.alt = item.path;
      image.loading = 'lazy';
      const caption = el('div', 'lr-image-caption');
      caption.append(check, el('span', '', item.path.split('/').pop()));
      if (item.selected) caption.append(el('small', 'lr-badge lr-adopted', t('lora.adopted')));
      else if (item.human_status === 'pass')
        caption.append(el('small', 'lr-badge', t('common.pass')));
      else if (item.human_status === 'fail')
        caption.append(el('small', 'lr-badge lr-failed', t('common.failed')));
      card.title = item.path;
      card.append(image, caption);
      grid.append(card);
    }
    box.append(grid);

    if (dataset) {
      const head = el('div', 'lr-row lr-between');
      head.append(el('h3', '', t('lora.captions', [dataset.items.length])));
      const buttons = el('div', 'lr-row');
      const saveButton = btn(t('lora.save_edited_captions'), saveCaptions, 'lr-primary');
      saveButton.disabled = !Object.keys(state.captions).length || !!ctx.preview;
      const again = btn(t('lora.rebuild_automatic_captions'), recaption);
      again.disabled = !!ctx.preview;
      buttons.append(again, saveButton);
      head.append(buttons);
      const list = el('div', 'lr-captions');
      for (const item of dataset.items) {
        const row = el('div', 'lr-caption');
        const thumb = el('img');
        thumb.src = `/api/gallery/thumbnail?path=${encodeURIComponent(item.path)}`;
        thumb.alt = item.path;
        thumb.loading = 'lazy';
        const area = el('textarea');
        area.rows = 3;
        area.value = state.captions[item.path] ?? item.caption;
        area.addEventListener('input', () => {
          state.captions[item.path] = area.value;
          saveButton.disabled = !!ctx.preview;
        });
        const areaBox = withTagComplete(area, ctx.api);
        const label = el(
          'small',
          'lr-muted',
          `${item.path}${item.caption_edited ? t('lora.edited_by_hand') : ''}`,
        );
        const text = el('div');
        text.append(label, areaBox);
        row.append(thumb, text);
        list.append(row);
      }
      box.append(head, list);
    }
    return box;
  }

  // ---- training tab -------------------------------------------------------------------

  async function startRun() {
    const train = state.train;
    try {
      const result = await ctx.api('/api/lora/runs/start', {
        ...who(),
        dataset_id: train.dataset,
        params: {
          epochs: Number(train.epochs),
          save_every: Number(train.save_every),
          learning_rate: String(train.learning_rate),
          method: train.method,
          base: train.base,
        },
      });
      ctx.notify(t('lora.started_training_it_takes_the_gpu', [result.run.id]));
      await loadRuns();
    } catch (error) {
      fail(error);
    }
  }
  async function cancelRun(run) {
    if (!window.confirm(t('lora.cancel_training', [run.id]))) return;
    try {
      await ctx.api('/api/lora/runs/cancel', {...who(), run_id: run.id});
      await loadRuns();
    } catch (error) {
      fail(error);
    }
  }
  async function register(run, output) {
    const name = window.prompt(
      t('lora.name_for_the_lora'),
      `${state.character} ${run.id} e${output.epoch}`,
    );
    if (name == null) return;
    try {
      await ctx.api('/api/loras/register', {
        ...who(),
        run_id: run.id,
        epoch: output.epoch,
        name: name.trim() || undefined,
      });
      ctx.notify(t('lora.registered_turn_on_auto_apply_in'));
      await loadLoras();
    } catch (error) {
      fail(error);
    }
  }

  function trainTab() {
    const box = el('div');
    const options = state.options;
    if (!options) {
      box.append(el('p', 'lr-muted', t('lora.loading')));
      return box;
    }
    if (!state.train) state.train = {...options.defaults, dataset: state.datasets.at(-1)?.id || ''};
    const train = state.train;
    if (!state.datasets.some((d) => d.id === train.dataset))
      train.dataset = state.datasets.at(-1)?.id || '';
    const form = el('div', 'lr-grid2');
    const dataset = select(
      state.datasets.map((d) => [d.id, t('lora.images', [d.id, tr(d.name) || '', d.items.length])]),
      train.dataset,
    );
    dataset.addEventListener('change', () => (train.dataset = dataset.value));
    const method = select(
      options.methods.map((m) => [m.id, tr(m.label)]),
      train.method,
    );
    method.addEventListener('change', () => (train.method = method.value));
    const base = select(
      options.bases.map((b) => [b.id, tr(b.label)]),
      train.base,
    );
    base.addEventListener('change', () => (train.base = base.value));
    const number = (key, attrs) => {
      const control = input('number', train[key], attrs);
      control.addEventListener('input', () => (train[key] = control.value));
      return control;
    };
    const lr = input('text', train.learning_rate);
    lr.addEventListener('input', () => (train.learning_rate = lr.value));
    form.append(
      field(t('lora.dataset'), dataset),
      field(t('common.method'), method),
      field(t('lora.base_model'), base, t('lora.the_defaults_train_a_t_lora')),
      field(t('lora.epochs'), number('epochs', {min: 1, max: 400})),
      field(
        t('lora.save_every_epochs'),
        number('save_every', {min: 1, max: 400}),
        t('lora.each_saved_epoch_becomes_a_file'),
      ),
      field(t('lora.learning_rate'), lr, t('lora.e_g_1e_4')),
    );
    const active = state.runs.some((r) => ACTIVE.includes(r.status));
    const start = btn(t('lora.start_training'), startRun, 'lr-primary');
    start.disabled = !train.dataset || active || !!ctx.preview;
    box.append(form, start, el('p', 'lr-muted', t('lora.new_images_are_not_generated_while')));

    box.append(el('h3', '', t('lora.training_runs')));
    if (!state.runs.length) box.append(el('p', 'lr-muted', t('lora.no_trainings_yet')));
    for (const run of [...state.runs].reverse()) {
      const card = el('div', `lr-run lr-run-${run.status}`);
      const head = el('div', 'lr-row lr-between');
      const s = run.settings || {};
      head.append(
        el('strong', '', `${run.id} · ${RUN_LABELS[run.status] || run.status}`),
        el(
          'small',
          'lr-muted',
          t('lora.epochs_lr', [
            run.dataset_id,
            s.method || '',
            s.base_model || '',
            s.epochs || '',
            s.learning_rate ?? '',
          ]),
        ),
      );
      card.append(head);
      if (run.note) card.append(el('p', 'lr-muted', run.note));
      const p = run.progress || {};
      if (ACTIVE.includes(run.status)) {
        const bar = el('progress');
        bar.max = p.total_steps || 1;
        bar.value = p.step || 0;
        card.append(
          bar,
          el(
            'p',
            'lr-muted',
            p.step
              ? t('lora.step_epoch', [
                  p.step,
                  p.total_steps,
                  p.epoch,
                  p.total_epochs,
                  p.loss != null ? ` · loss ${Number(p.loss).toFixed(4)}` : '',
                ])
              : RUN_LABELS[run.status],
          ),
          btn(t('common.cancel'), () => cancelRun(run), 'lr-danger'),
        );
      }
      if (run.error) card.append(el('p', 'lr-error', tr(run.error)));
      if (run.outputs?.length) {
        const outputs = el('div', 'lr-row');
        const registered = new Set(
          state.loras.filter((l) => l.origin?.run_id === run.id).map((l) => l.origin.epoch),
        );
        for (const output of run.outputs) {
          const done = registered.has(output.epoch);
          const b = btn(
            done ? t('lora.e_registered', [output.epoch]) : t('lora.register_e', [output.epoch]),
            () => register(run, output),
          );
          b.disabled = done || !!ctx.preview || run.status !== 'done';
          b.title = output.file;
          outputs.append(b);
        }
        card.append(outputs);
      }
      if (run.log_path) {
        // Show the part under the Studio folder (logs/lora/...); the full path stays in the tooltip.
        const short = run.log_path.replace(/^.*?[\\/](logs[\\/]lora[\\/])/, '$1');
        const log = el('small', 'lr-muted lr-path', t('lora.log', [short]));
        log.title = run.log_path;
        card.append(log);
      }
      box.append(card);
    }
    return box;
  }

  // ---- registry tab -------------------------------------------------------------------

  async function saveLora(lora, changes) {
    try {
      const latest = await ctx.api(`/api/library/entity?${query({kind: 'lora', id: lora.id})}`);
      await ctx.api('/api/loras/save', {
        payload: {...latest.entity, ...changes},
        expected_revision: latest.revision,
      });
      await loadLoras();
      ctx.onLibraryChanged?.();
    } catch (error) {
      fail(error);
      await loadLoras();
    }
  }
  async function deleteLora(lora) {
    if (!window.confirm(t('lora.remove_from_the_list_it_goes', [lora.name || lora.id]))) return;
    try {
      const latest = await ctx.api(`/api/library/entity?${query({kind: 'lora', id: lora.id})}`);
      await ctx.api('/api/loras/delete', {id: lora.id, expected_revision: latest.revision});
      await loadLoras();
    } catch (error) {
      fail(error);
    }
  }

  function lorasTab() {
    const box = el('div');
    const mine = state.loras.filter(
      (l) =>
        l.scope === 'global' ||
        (l.origin?.work_id === state.work && l.origin?.character_id === state.character),
    );
    box.append(el('p', 'lr-muted', t('lora.a_lora_with_auto_apply_is')));
    if (!mine.length)
      box.append(el('p', 'lr-muted', t('lora.no_loras_registered_for_this_character')));
    for (const lora of mine) {
      const card = el('div', 'lr-lora');
      const head = el('div', 'lr-row lr-between');
      head.append(el('strong', '', lora.name || lora.id), el('small', 'lr-muted', lora.file));
      const auto = input('checkbox', lora.auto_apply);
      auto.addEventListener('change', () => saveLora(lora, {auto_apply: auto.checked}));
      const applyTo = select(
        [
          ['character', t('lora.whole_character')],
          ['outfit', t('lora.only_with_outfit', [lora.origin?.outfit_set_id || ''])],
        ],
        lora.apply_to || 'character',
      );
      applyTo.addEventListener('change', () => saveLora(lora, {apply_to: applyTo.value}));
      const scope = select(
        [
          ['character', t('lora.character_only')],
          ['global', t('lora.global_all_characters')],
        ],
        lora.scope,
      );
      scope.addEventListener('change', () => saveLora(lora, {scope: scope.value}));
      const strength = input('number', lora.strength ?? 1, {min: -2, max: 3, step: 0.05});
      strength.addEventListener('change', () => saveLora(lora, {strength: Number(strength.value)}));
      const family = select(Object.entries(FAMILY_LABELS), lora.model_family || 'anima');
      family.addEventListener('change', () => saveLora(lora, {model_family: family.value}));
      const autoLabel = el('label', 'lr-check');
      autoLabel.append(auto, el('span', '', t('lora.auto_apply')));
      const controls = el('div', 'lr-grid4');
      controls.append(
        autoLabel,
        field(t('lora.applies_to'), applyTo),
        field(t('common.scope'), scope),
        field(t('lora.strength'), strength),
        field(t('common.model_family'), family),
      );
      for (const control of [auto, applyTo, scope, strength, family])
        control.disabled = !!ctx.preview;
      const triggers = Object.values(lora.triggers || {}).filter(Boolean);
      const origin = lora.origin
        ? `${lora.origin.work_id}/${lora.origin.character_id}/${lora.origin.outfit_set_id} · ${lora.origin.run_id || ''} e${lora.origin.epoch ?? ''}`
        : t('lora.external_file');
      const remove = btn(t('lora.remove_from_list'), () => deleteLora(lora), 'lr-danger');
      remove.disabled = !!ctx.preview;
      card.append(
        head,
        controls,
        el(
          'p',
          'lr-muted',
          t('lora.triggers_origin', [triggers.join(', ') || t('common.missing'), origin]),
        ),
        remove,
      );
      box.append(card);
    }
    return box;
  }

  // ---- layout and loading -------------------------------------------------------------

  function renderMain() {
    if (!state.character) {
      main.replaceChildren(el('p', 'lr-muted', t('lora.choose_a_character_on_the_left')));
      return;
    }
    const tabs = el('div', 'lr-tabs');
    for (const [key, text] of [
      ['dataset', t('lora.dataset')],
      ['train', t('lora.training')],
      ['loras', t('lora.registered_loras')],
    ]) {
      const tab = btn(text, () => {
        state.tab = key;
        renderMain();
      });
      tab.setAttribute('aria-pressed', String(state.tab === key));
      tabs.append(tab);
    }
    const body =
      state.tab === 'dataset' ? datasetTab() : state.tab === 'train' ? trainTab() : lorasTab();
    main.replaceChildren(el('h2', '', `${state.work} / ${state.character}`), tabs, body);
  }

  async function loadRuns() {
    const result = await ctx.api(`/api/lora/runs?${whoQuery()}`);
    state.runs = arr(result.runs);
    renderMain();
    clearTimeout(state.timer);
    if (state.runs.some((r) => ACTIVE.includes(r.status)))
      state.timer = setTimeout(() => loadRuns().catch(() => {}), POLL_MS);
  }
  async function loadLoras() {
    state.loras = arr((await ctx.api('/api/loras')).loras);
    renderMain();
  }
  async function loadCharacter() {
    const [datasets] = await Promise.all([
      ctx.api(`/api/lora/datasets?${whoQuery()}`),
      loadRuns(),
      loadLoras(),
    ]);
    state.datasets = arr(datasets.datasets);
    if (state.dataset && !currentDataset()) state.dataset = '';
    if (!state.candidates.length) await chooseDataset(state.dataset);
    else renderMain();
  }
  async function loadCatalog() {
    state.catalog = await ctx.api(`/api/catalog?work=${encodeURIComponent(state.work)}`);
    renderSide();
    renderMain();
  }

  async function enter(params) {
    const [works, options] = await Promise.all([
      ctx.api('/api/works'),
      ctx.api('/api/lora/options').catch(() => null),
    ]);
    state.works = arr(works.works);
    state.options = options;
    state.work = params?.get('work') || state.work || state.works[0]?.id || '';
    await loadCatalog();
    const wanted = params?.get('character');
    if (wanted && wanted !== state.character) await chooseCharacter(wanted);
    else if (state.character) await loadCharacter();
  }
  function leave() {
    clearTimeout(state.timer);
  }

  return {element: root, enter, leave};
}
