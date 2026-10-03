// Lab: generate one image or compare one prompt across seeds and changing values.
// Results are not assets; they are saved under outputs/_lab/<date>/ with full metadata.

import {renderGenerationSettings} from '../core/generation_settings.js';
import {renderTagCheck, withTagComplete} from '../core/tag_input.js';
import {splitTags} from '../lib/tags.js';
import {locale, t, tr} from '../core/i18n.js';

const DRAFT_KEY = 'asset-studio-lab-draft-v1';
const HANDOFF_KEY = 'asset-studio-lab-handoff';
const POLL_MS = 2500;
const MAX_JOBS = 48;
const SWEEPS = [
  ['', t('lab.none_compare_seeds_only')],
  ['cfg', 'CFG'],
  ['steps', 'Steps'],
  ['sampler', t('common.sampler')],
  ['scheduler', t('common.scheduler')],
  ['clip_skip', 'CLIP skip'],
  ['lora_strength', t('lab.lora_strength')],
  ['artist', t('lab.artist')],
];
const SWEEP_HINTS = {
  cfg: t('lab.e_g_3_4_5_6'),
  steps: t('lab.e_g_20_28_36'),
  sampler: t('lab.comma_separated_empty_means_the_whole'),
  scheduler: t('lab.comma_separated_empty_means_the_whole'),
  clip_skip: t('lab.e_g_1_2'),
  lora_strength: t('lab.e_g_0_4_0_7'),
  artist: t('lab.one_candidate_per_line_tags_within'),
};
const DONE = ['completed', 'failed', 'cancelled', 'interrupted'];
const MAX_CANDIDATES = 12;

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
const arr = (value) => (Array.isArray(value) ? value : []);
const copy = (value) => JSON.parse(JSON.stringify(value ?? null));
const field = (text, control, hint) => {
  const n = el('label', 'lab-field');
  n.append(el('span', '', text), control);
  if (hint) n.append(el('small', '', hint));
  return n;
};
const readStore = (store, key) => {
  try {
    return JSON.parse(store.getItem(key) || 'null');
  } catch {
    return null;
  }
};
const writeStore = (store, key, value) => {
  try {
    if (value == null) store.removeItem(key);
    else store.setItem(key, JSON.stringify(value));
  } catch {
    /* Private windows may refuse storage; the lab works without it. */
  }
};

/** Open the lab with a prompt and settings; ``run`` starts one generation right away. */
export function sendToLab(ctx, draft, run = false) {
  writeStore(sessionStorage, HANDOFF_KEY, {...draft, run});
  ctx.navigate('/lab');
}

export function createLab(ctx) {
  const root = el('section');
  root.id = 'app-lab';
  const state = {
    comfy: null,
    presets: [],
    draft: {
      positive: '',
      negative: '',
      settings: {},
      count: 4,
      sweep: {key: '', values: '', no_artist: false},
    },
    source: null,
    jobs: [],
    group: '',
    asIs: null,
    toBe: null,
    mode: 'side',
    slider: 50,
    timer: 0,
    busy: false,
    tab: 'single',
  };

  const form = el('div', 'lab-form');
  const view = el('div', 'lab-view');
  const header = el('header', 'lab-header');
  header.append(
    el('h1', '', t('common.lab')),
    el('p', '', t('lab.generate_one_prompt_with_several_seeds')),
  );
  root.append(header, form, view);

  const saveDraft = () => writeStore(localStorage, DRAFT_KEY, state.draft);

  // ---- form ---------------------------------------------------------------------------

  const sourceLine = el('p', 'lab-source');
  const positive = el('textarea');
  positive.rows = 7;
  positive.spellcheck = false;
  positive.setAttribute('aria-label', t('common.positive_prompt'));
  const negative = el('textarea');
  negative.rows = 4;
  negative.spellcheck = false;
  negative.setAttribute('aria-label', t('common.negative_prompt'));
  const checkBox = el('div', 'lab-tagcheck');
  const settingsBox = el('div', 'lab-settings');
  const presetSelect = el('select');
  const countInput = el('input');
  countInput.type = 'number';
  countInput.min = '1';
  countInput.max = '16';
  const sweepKey = el('select');
  for (const [key, text] of SWEEPS) {
    const option = el('option', '', text);
    option.value = key;
    sweepKey.append(option);
  }
  const sweepValues = el('textarea');
  sweepValues.rows = 4;
  sweepValues.spellcheck = false;
  const sweepLora = el('select');
  const noArtist = el('input');
  noArtist.type = 'checkbox';
  const sweepRow = el('div', 'lab-row');
  const sweepLoraField = field('LoRA', sweepLora);
  const sweepValuesField = field(t('lab.values'), sweepValues);
  const noArtistField = field(
    t('lab.include_no_artist_baseline'),
    noArtist,
    t('lab.shared_prompt_artists_kept'),
  );
  const countField = field(t('lab.seeds'), countInput, t('lab.a_fixed_seed_counts_up_by'));
  const modeHeading = el('h2', 'lab-mode-heading');
  const totalLine = el('p', 'lab-total');
  const runButton = btn(t('common.generate'), () => run(), 'lab-primary');
  const modeRow = el('div', 'lab-tabs');
  const singleTab = btn(t('lab.single'), () => {
    state.tab = 'single';
    renderTab();
  });
  const compareTab = btn(t('lab.compare'), () => {
    state.tab = 'compare';
    renderTab();
  });
  singleTab.setAttribute('aria-pressed', 'true');
  compareTab.setAttribute('aria-pressed', 'false');
  modeRow.append(singleTab, compareTab);

  positive.value = '';
  // Replace one tag everywhere it appears, keeping the spacing around it.
  const replaceIn = (area, key) => (old, next) => {
    area.value = area.value
      .split(',')
      .map((part) => (splitTags(part)[0] === old ? part.replace(part.trim(), next) : part))
      .join(',');
    state.draft[key] = area.value;
    saveDraft();
    checkTags(area, key);
  };
  async function checkTags(area, key) {
    try {
      await renderTagCheck(checkBox, ctx.api, area.value, replaceIn(area, key));
    } catch (error) {
      checkBox.replaceChildren(el('p', 'tag-note', error.message));
    }
  }

  function sweepList() {
    const {key, values} = state.draft.sweep;
    if (!key) return [];
    if (key === 'artist') {
      const candidates = String(values || '')
        .split(/\r?\n/)
        .map((value) => value.trim())
        .filter(Boolean);
      if (state.draft.sweep.no_artist) candidates.push('');
      return candidates;
    }
    const parts = String(values || '')
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
    if (!parts.length && ['sampler', 'scheduler'].includes(key))
      return arr(state.comfy?.[`${key}s`]);
    return parts;
  }
  function totals() {
    const comparing = state.tab === 'compare';
    const variants = comparing && state.draft.sweep.key ? sweepList().length : 1;
    const seeds = comparing ? Number(state.draft.count) || 0 : 1;
    return {variants, jobs: seeds * variants, seeds};
  }
  function renderTotal() {
    const total = totals();
    const sweepKey = state.tab === 'compare' ? state.draft.sweep.key : '';
    totalLine.textContent = sweepKey
      ? t('lab.seeds_values_images', [total.seeds, total.variants, total.jobs])
      : t('lab.seeds_images', [total.seeds, total.jobs]);
    runButton.textContent = t('lab.generate', [total.jobs]);
    const sweepBad = sweepKey && total.variants < 2;
    const valuesTooMany = sweepKey && total.variants > MAX_CANDIDATES;
    const artistValues = sweepKey === 'artist' ? sweepList() : [];
    const duplicateArtists =
      sweepKey === 'artist' && new Set(artistValues).size !== artistValues.length;
    runButton.disabled =
      state.busy ||
      !!ctx.preview ||
      total.jobs < 1 ||
      total.jobs > MAX_JOBS ||
      sweepBad ||
      valuesTooMany ||
      duplicateArtists;
    if (total.jobs > MAX_JOBS) totalLine.textContent += t('lab.up_to', [MAX_JOBS]);
    if (sweepBad) totalLine.textContent += t('lab.enter_at_least_two_values_to');
    if (valuesTooMany) totalLine.textContent += t('lab.use_at_most_values', [MAX_CANDIDATES]);
    if (duplicateArtists) totalLine.textContent += t('lab.remove_duplicate_artist_values');
  }
  function renderSweep() {
    const {key} = state.draft.sweep;
    sweepKey.value = key;
    sweepValues.value = state.draft.sweep.values || '';
    sweepValues.placeholder = SWEEP_HINTS[key] || '';
    sweepValuesField.hidden = !key;
    sweepValues.rows = key === 'artist' ? 6 : 2;
    sweepLora.replaceChildren();
    arr(state.draft.settings.loras).forEach((lora, index) => {
      const option = el('option', '', lora.name || `LoRA ${index + 1}`);
      option.value = String(index);
      sweepLora.append(option);
    });
    sweepLora.value = String(state.draft.sweep.lora_index || 0);
    sweepLoraField.hidden = key !== 'lora_strength';
    noArtist.checked = !!state.draft.sweep.no_artist;
    noArtistField.hidden = key !== 'artist';
    renderTotal();
  }
  function renderTab() {
    const comparing = state.tab === 'compare';
    countField.hidden = !comparing;
    sweepRow.hidden = !comparing;
    modeHeading.textContent = comparing ? t('lab.result') : t('lab.single');
    for (const [key, tab] of [
      ['single', singleTab],
      ['compare', compareTab],
    ])
      tab.setAttribute('aria-pressed', String(state.tab === key));
    renderTotal();
  }
  function renderSettings() {
    renderGenerationSettings(settingsBox, {
      comfy: state.comfy,
      settings: state.draft.settings,
      disabled: false,
      onChange(next, structural) {
        state.draft.settings = next;
        saveDraft();
        if (structural) renderSettings();
        renderSweep();
      },
    });
  }
  function renderPresets() {
    presetSelect.replaceChildren(el('option', '', t('lab.load_a_preset')));
    presetSelect.firstChild.value = '';
    for (const preset of state.presets) {
      const option = el('option', '', `${preset.name || preset.id} · ${preset.id}`);
      option.value = preset.id;
      presetSelect.append(option);
    }
  }
  presetSelect.addEventListener('change', () => {
    const preset = state.presets.find((p) => p.id === presetSelect.value);
    presetSelect.value = '';
    if (!preset) return;
    const keep = ['artist_ids', 'common_positive_ids', 'common_negative_ids'];
    const settings = copy(preset.settings || {});
    for (const key of keep) delete settings[key];
    state.draft.settings = {...state.draft.settings, ...settings};
    saveDraft();
    renderSettings();
    renderSweep();
    ctx.notify(t('lab.loaded_the_generation_settings_of_preset', [preset.name || preset.id]));
  });
  async function savePreset() {
    if (ctx.preview) return ctx.notify(t('common.saving_is_off_in_preview_mode'), true);
    const used = new Set(state.presets.map((p) => p.id));
    let suggestion = '';
    for (let i = 1; i < 1000 && !suggestion; i++) {
      const id = `G${String(i).padStart(3, '0')}`;
      if (!used.has(id)) suggestion = id;
    }
    const id = window.prompt(t('lab.code_for_the_new_generation_preset'), suggestion)?.trim();
    if (!id) return;
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id) || used.has(id))
      return ctx.notify(t('lab.the_code_is_invalid_or_the'), true);
    const name = window.prompt(t('common.preset_name'), id)?.trim();
    if (!name) return;
    const settings = copy(state.draft.settings);
    delete settings.seed;
    try {
      await ctx.api('/api/library/save', {
        kind: 'preset',
        preset_type: 'generation',
        payload: {id, name, settings},
        expected_revision: null,
      });
      ctx.onLibraryChanged?.();
      await loadPresets();
      ctx.notify(t('lab.saved_generation_preset', [name]));
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  function buildForm() {
    const promptHead = el('div', 'lab-row lab-between');
    promptHead.append(
      el('h2', '', t('lab.prompt')),
      btn(t('lab.check_positive_tags'), () => checkTags(positive, 'positive'), 'lab-muted'),
    );
    const negativeHead = el('div', 'lab-row lab-between');
    negativeHead.append(
      el('h3', '', t('common.negative_prompt')),
      btn(t('lab.check_negative_tags'), () => checkTags(negative, 'negative'), 'lab-muted'),
    );
    const settingsHead = el('div', 'lab-row lab-between');
    settingsHead.append(el('h2', '', t('common.generation_settings')), presetSelect);
    const presetRow = el('div', 'lab-row');
    presetRow.append(btn(t('lab.save_current_settings_as_a_preset'), savePreset, 'lab-muted'));
    sweepRow.append(
      field(t('lab.value_to_vary'), sweepKey),
      sweepLoraField,
      sweepValuesField,
      noArtistField,
    );
    form.replaceChildren(
      modeRow,
      sourceLine,
      promptHead,
      withTagComplete(positive, ctx.api, (value) => {
        state.draft.positive = value;
        saveDraft();
      }),
      negativeHead,
      withTagComplete(negative, ctx.api, (value) => {
        state.draft.negative = value;
        saveDraft();
      }),
      checkBox,
      settingsHead,
      settingsBox,
      presetRow,
      modeHeading,
      countField,
      sweepRow,
      totalLine,
      runButton,
    );
  }
  countInput.addEventListener('input', () => {
    state.draft.count = Math.max(1, Math.min(16, Number(countInput.value) || 1));
    saveDraft();
    renderTotal();
  });
  sweepKey.addEventListener('change', () => {
    state.draft.sweep = {key: sweepKey.value, values: '', lora_index: 0, no_artist: false};
    saveDraft();
    renderSweep();
  });
  sweepValues.addEventListener('input', () => {
    state.draft.sweep.values = sweepValues.value;
    saveDraft();
    renderTotal();
  });
  sweepLora.addEventListener('change', () => {
    state.draft.sweep.lora_index = Number(sweepLora.value);
    saveDraft();
  });
  noArtist.addEventListener('change', () => {
    state.draft.sweep.no_artist = noArtist.checked;
    saveDraft();
    renderTotal();
  });

  function fillForm() {
    positive.value = state.draft.positive || '';
    negative.value = state.draft.negative || '';
    countInput.value = String(state.draft.count || 1);
    const from = state.source;
    sourceLine.textContent = from
      ? t('lab.from', [
          from.label ||
            [from.work_id, from.character_id, from.outfit_id, from.expression_id]
              .filter(Boolean)
              .join(' / '),
        ])
      : '';
    sourceLine.hidden = !from;
    renderSettings();
    renderSweep();
    renderTab();
  }

  /** Queue the form; ``once`` sends a single image with the form's seed setting. */
  async function run(once = state.tab === 'single') {
    if (state.busy) return;
    const sweep =
      !once && state.draft.sweep.key
        ? {
            key: state.draft.sweep.key,
            values: sweepList(),
            lora_index: state.draft.sweep.lora_index || 0,
          }
        : null;
    state.busy = true;
    renderTotal();
    try {
      const result = await ctx.api('/api/jobs/lab', {
        positive: state.draft.positive,
        negative: state.draft.negative,
        settings: state.draft.settings,
        count: once ? 1 : Number(state.draft.count) || 1,
        sweep,
        source: state.source,
      });
      ctx.notify(t('lab.queued_images', [result.jobs.length]));
      ctx.onQueueChanged?.();
      state.group = result.lab_group;
      // A gallery image stays the reference; otherwise the first result becomes it.
      if (state.asIs && !state.asIs.fixed) state.asIs = null;
      state.toBe = null;
      await loadJobs();
    } catch (error) {
      ctx.notify(error.message, true);
    } finally {
      state.busy = false;
      renderTotal();
    }
  }

  // ---- results and compare -------------------------------------------------------------

  const groups = () => {
    const found = new Map();
    for (const job of state.jobs) {
      if (job.kind !== 'lab') continue;
      if (!found.has(job.lab_group)) found.set(job.lab_group, []);
      found.get(job.lab_group).push(job);
    }
    return [...found.entries()]
      .map(([id, jobs]) => ({id, jobs: jobs.sort((a, b) => a.lab_index - b.lab_index)}))
      .sort((a, b) => String(b.jobs[0].created_at).localeCompare(String(a.jobs[0].created_at)));
  };
  const picture = (job) =>
    job?.image_url && {
      url: job.image_url,
      label: [tr(job.lab_variant), t('lab.seed', [job.seed])].filter(Boolean).join(' · '),
      job,
    };

  function figure(side, title) {
    const box = el('figure', 'lab-figure');
    if (!side) {
      box.append(
        el(
          'div',
          'lab-empty',
          title === t('lab.reference') ? t('lab.no_reference_image') : t('lab.waiting_for_results'),
        ),
      );
    } else {
      const image = el('img');
      image.src = side.url;
      image.alt = side.label;
      box.append(image);
    }
    box.append(el('figcaption', '', `${title} · ${side?.label || '—'}`));
    return box;
  }
  function renderCompare(stage) {
    stage.replaceChildren();
    if (state.mode === 'slider' && state.asIs && state.toBe) {
      const frame = el('div', 'lab-slider');
      const under = el('img');
      under.src = state.asIs.url;
      under.alt = state.asIs.label;
      const over = el('img', 'lab-over');
      over.src = state.toBe.url;
      over.alt = state.toBe.label;
      const line = el('div', 'lab-line');
      const range = el('input');
      range.type = 'range';
      range.min = '0';
      range.max = '100';
      range.value = String(state.slider);
      range.setAttribute('aria-label', t('lab.border_between_reference_and_result'));
      const place = () => {
        over.style.clipPath = `inset(0 0 0 ${state.slider}%)`;
        line.style.left = `${state.slider}%`;
      };
      range.addEventListener('input', () => {
        state.slider = Number(range.value);
        place();
      });
      place();
      frame.append(under, over, line, range);
      const caption = el(
        'p',
        'lab-caption',
        t('lab.left_reference_right_result', [state.asIs.label, state.toBe.label]),
      );
      stage.append(frame, caption);
      return;
    }
    const pair = el('div', 'lab-pair');
    pair.append(figure(state.asIs, t('lab.reference')), figure(state.toBe, t('lab.result')));
    stage.append(pair);
  }
  async function useSettingsOf(job) {
    try {
      const response = await fetch(job.metadata_url);
      const meta = await response.json();
      state.draft.positive = meta.positive ?? state.draft.positive;
      state.draft.negative = meta.negative ?? state.draft.negative;
      state.draft.settings = {...meta.settings};
      saveDraft();
      fillForm();
      ctx.notify(t('lab.loaded_this_result_s_prompt_and'));
    } catch {
      ctx.notify(t('lab.could_not_read_the_metadata'), true);
    }
  }
  function renderView() {
    const list = groups();
    if (!state.group && list.length) state.group = list[0].id;
    const current = list.find((g) => g.id === state.group);
    const done = current?.jobs.filter((j) => j.image_url) || [];
    if (!state.asIs && done.length) state.asIs = picture(done[0]);
    if (!state.toBe && done.length) state.toBe = picture(done[done.length > 1 ? 1 : 0]);

    const top = el('div', 'lab-row lab-between');
    const chooser = el('select');
    if (!list.length) {
      chooser.append(el('option', '', t('lab.no_lab_runs_yet')));
      chooser.firstChild.value = '';
    }
    for (const group of list) {
      const first = group.jobs[0];
      const option = el(
        'option',
        '',
        t('lab.images', [
          new Date(first.created_at).toLocaleString(locale),
          group.jobs.length,
          first.lab_variant ? t('lab.value_sweep') : '',
        ]),
      );
      option.value = group.id;
      chooser.append(option);
    }
    chooser.value = state.group;
    chooser.addEventListener('change', () => {
      state.group = chooser.value;
      if (!state.asIs?.fixed) state.asIs = null;
      state.toBe = null;
      renderView();
    });
    const modes = el('div', 'lab-modes');
    for (const [key, text] of [
      ['side', t('common.side_by_side')],
      ['slider', t('common.slider')],
    ]) {
      const b = btn(text, () => {
        state.mode = key;
        renderView();
      });
      b.setAttribute('aria-pressed', String(state.mode === key));
      modes.append(b);
    }
    top.append(chooser, modes);

    const stage = el('div', 'lab-stage');
    renderCompare(stage);

    const tools = el('div', 'lab-row');
    if (state.toBe?.job)
      tools.append(
        btn(t('lab.load_the_result_s_settings'), () => useSettingsOf(state.toBe.job), 'lab-muted'),
      );
    if (state.asIs && state.toBe)
      tools.append(
        btn(
          t('lab.swap_reference_and_result'),
          () => {
            [state.asIs, state.toBe] = [state.toBe, state.asIs];
            renderView();
          },
          'lab-muted',
        ),
      );

    const strip = el('div', 'lab-strip');
    const columns = current ? Math.max(...current.jobs.map((j) => j.lab_column || 0)) + 1 : 1;
    const jobs = current?.jobs || [];
    const candidateGrid = columns > 1;
    strip.classList.toggle('lab-candidate-grid', candidateGrid);
    strip.style.gridTemplateColumns = candidateGrid
      ? `minmax(56px, 0.45fr) repeat(${columns}, minmax(100px, 1fr))`
      : 'repeat(auto-fill, minmax(110px, 140px))';
    const renderCard = (job) => {
      if (!job) return el('div', 'lab-grid-empty');
      const card = el('div', 'lab-thumb');
      if (state.toBe?.job?.id === job.id) card.classList.add('to-be');
      if (state.asIs?.job?.id === job.id) card.classList.add('as-is');
      if (job.image_url) {
        const image = el('img');
        image.src = job.image_url;
        image.alt = tr(job.title) || '';
        image.loading = 'lazy';
        image.addEventListener('click', () => {
          state.toBe = picture(job);
          renderView();
        });
        card.append(image);
      } else {
        card.append(
          el(
            'div',
            'lab-empty',
            job.status === 'failed'
              ? t('common.failed')
              : job.status === 'running'
                ? t('common.generating')
                : DONE.includes(job.status)
                  ? t('common.cancel')
                  : t('common.queued'),
          ),
        );
      }
      const caption = el('div', 'lab-thumb-caption');
      caption.append(el('span', '', tr(job.lab_variant) || t('lab.seed', [job.seed])));
      if (job.image_url)
        caption.append(
          btn(t('lab.reference'), () => {
            state.asIs = picture(job);
            renderView();
          }),
        );
      card.title = tr(job.title) || '';
      card.append(caption);
      return card;
    };
    if (candidateGrid) {
      strip.append(el('div', 'lab-grid-corner', t('common.seed')));
      for (let column = 0; column < columns; column++) {
        const candidate = jobs.find((job) => (job.lab_column || 0) === column);
        const label = candidate?.lab_variant
          ? tr(candidate.lab_variant)
          : t('lab.no_artist_baseline');
        strip.append(el('div', 'lab-candidate-heading', `${t('lab.candidate')}: ${label}`));
      }
      const rows = new Map();
      for (const job of jobs) {
        const key = String(job.seed);
        if (!rows.has(key)) rows.set(key, new Map());
        rows.get(key).set(job.lab_column || 0, job);
      }
      for (const [seed, row] of rows) {
        strip.append(el('div', 'lab-seed-heading', t('lab.seed', [seed])));
        for (let column = 0; column < columns; column++) strip.append(renderCard(row.get(column)));
      }
    } else {
      for (const job of jobs) strip.append(renderCard(job));
    }
    const hint = el('p', 'lab-caption', t('lab.click_a_thumbnail_to_compare_it'));
    view.replaceChildren(top, stage, tools, strip, hint);
  }

  async function loadJobs() {
    try {
      const result = await ctx.api('/api/jobs');
      state.jobs = arr(result.jobs);
    } catch {
      /* The queue drawer reports connection problems. */
    }
    renderView();
  }
  async function loadPresets() {
    try {
      const catalog = await ctx.api('/api/catalog');
      state.presets = arr(catalog.presets?.generation);
    } catch {
      state.presets = [];
    }
    renderPresets();
  }

  // ---- lifecycle ---------------------------------------------------------------------

  async function enter(params) {
    state.comfy = await ctx.api('/api/comfy').catch(() => null);
    const saved = readStore(localStorage, DRAFT_KEY);
    if (saved)
      state.draft = {...state.draft, ...saved, sweep: {key: '', values: '', ...saved.sweep}};
    if (!Object.keys(state.draft.settings || {}).length)
      state.draft.settings = copy(state.comfy?.defaults || {});
    const handoff = readStore(sessionStorage, HANDOFF_KEY);
    writeStore(sessionStorage, HANDOFF_KEY, null);
    if (handoff) {
      state.draft.positive = handoff.positive || '';
      state.draft.negative = handoff.negative || '';
      if (handoff.settings) state.draft.settings = copy(handoff.settings);
      state.source = handoff.source || null;
      state.asIs = null;
      state.toBe = null;
    }
    const image = params?.get('image');
    if (image) {
      const meta = await ctx.api(`/api/gallery/metadata?path=${encodeURIComponent(image)}`);
      if (meta.error) ctx.notify(t('lab.no_metadata', [tr(meta.error)]), true);
      else {
        state.draft.positive = meta.positive || '';
        state.draft.negative = meta.negative || '';
        if (meta.settings) state.draft.settings = {...meta.settings};
      }
      state.source = {label: t('lab.gallery', [image]), image};
      state.asIs = {
        url: `/outputs/${image.split('/').map(encodeURIComponent).join('/')}`,
        label: t('lab.gallery_original'),
        fixed: true,
      };
      state.toBe = null;
    }
    saveDraft();
    fillForm();
    await Promise.all([loadPresets(), loadJobs()]);
    if (handoff?.run) await run(true);
    clearInterval(state.timer);
    state.timer = setInterval(() => {
      if (document.hidden) return;
      const current = groups().find((g) => g.id === state.group);
      if (current?.jobs.some((j) => !DONE.includes(j.status))) loadJobs();
    }, POLL_MS);
  }
  function leave() {
    clearInterval(state.timer);
  }

  buildForm();
  return {element: root, enter, leave};
}
