// Prompt-format conversion workspace for direct text and gallery records.
import {convertPrompts} from '../lib/prompt_convert.js';
import {switchFamily} from '../core/generation_settings.js';
import {t} from '../core/i18n.js';

const el = (tag, cls = '', text) => {
  const item = document.createElement(tag);
  if (cls) item.className = cls;
  if (text != null) item.textContent = text;
  return item;
};
const button = (label, handler, cls = '') => {
  const item = el('button', cls, label);
  item.type = 'button';
  item.addEventListener('click', handler);
  return item;
};
const readHandoff = () => {
  try {
    const value = JSON.parse(
      sessionStorage.getItem('asset-studio-prompt-format-handoff') || 'null',
    );
    sessionStorage.removeItem('asset-studio-prompt-format-handoff');
    return value;
  } catch {
    return null;
  }
};

export function createPromptConverter(ctx, {onOpenLab, convert: convertProvider = convertPrompts}) {
  const root = el('section', 'pc-workspace');
  const state = {
    positive: '',
    negative: '',
    result: null,
    revision: 0,
    source: 'nai',
    target: 'sdxl',
    artists: '',
    settings: null,
    family: '',
    imageLabel: '',
    queue: [],
    queueIndex: 0,
    galleryPage: 1,
    galleryPages: 1,
    galleryResults: [],
    galleryRequest: 0,
    metadataRequest: 0,
    conversionRequest: 0,
    loading: false,
    converting: false,
    dialog: null,
  };

  const positiveSource = el('textarea', 'pc-text');
  positiveSource.rows = 12;
  positiveSource.addEventListener('input', () => {
    state.positive = positiveSource.value;
    invalidateResult();
  });
  const negativeSource = el('textarea', 'pc-text');
  negativeSource.rows = 7;
  negativeSource.addEventListener('input', () => {
    state.negative = negativeSource.value;
    invalidateResult();
  });
  const positiveResult = el('textarea', 'pc-text');
  positiveResult.rows = 12;
  positiveResult.addEventListener('input', () => {
    state.revision++;
  });
  const negativeResult = el('textarea', 'pc-text');
  negativeResult.rows = 7;
  negativeResult.addEventListener('input', () => {
    state.revision++;
  });
  const sourceSelect = document.createElement('select');
  const targetSelect = document.createElement('select');
  const formats = [
    ['nai', t('prompt_converter.nai_v5')],
    ['anima', t('prompt_converter.anima')],
    ['sdxl', t('prompt_converter.sdxl_illustrious_comfyui')],
  ];
  for (const [value, label] of formats) {
    const sourceOption = el('option', '', label);
    sourceOption.value = value;
    sourceSelect.append(sourceOption);
    const targetOption = el('option', '', label);
    targetOption.value = value;
    targetSelect.append(targetOption);
  }
  sourceSelect.value = state.source;
  targetSelect.value = state.target;
  sourceSelect.addEventListener('change', () => {
    state.source = sourceSelect.value;
    invalidateResult();
  });
  targetSelect.addEventListener('change', () => {
    state.target = targetSelect.value;
    invalidateResult();
  });

  const artistNames = el('textarea', 'pc-artists');
  artistNames.rows = 3;
  artistNames.placeholder = t('prompt_converter.artist_names_placeholder');
  artistNames.addEventListener('input', () => {
    state.artists = artistNames.value;
    invalidateResult();
  });
  const status = el('p', 'pc-status');
  const changes = el('ul', 'pc-list');
  const warnings = el('ul', 'pc-list pc-warnings');
  const changesPanel = el('section', 'pc-report');
  changesPanel.append(el('h3', '', t('prompt_converter.changes')), changes);
  const warningsPanel = el('section', 'pc-report');
  warningsPanel.append(el('h3', '', t('prompt_converter.warnings')), warnings);
  const sourcePositive = el('label', 'pc-field');
  sourcePositive.append(el('span', '', t('common.positive_prompt')), positiveSource);
  const sourceNegative = el('label', 'pc-field');
  sourceNegative.append(el('span', '', t('gallery.negative_prompt')), negativeSource);
  const resultPositive = el('label', 'pc-field');
  resultPositive.append(el('span', '', t('common.positive_prompt')), positiveResult);
  const resultNegative = el('label', 'pc-field');
  resultNegative.append(el('span', '', t('gallery.negative_prompt')), negativeResult);
  const sourcePane = el('div', 'pc-pane');
  const resultPane = el('div', 'pc-pane');
  sourcePane.append(
    el('h2', '', t('prompt_converter.source_text')),
    sourcePositive,
    sourceNegative,
  );
  resultPane.append(
    el('h2', '', t('prompt_converter.converted_text')),
    resultPositive,
    resultNegative,
  );
  const textColumns = el('div', 'pc-columns');
  textColumns.append(sourcePane, resultPane);
  const settingsRow = el('div', 'pc-settings');
  const sourceField = el('label', 'pc-field');
  sourceField.append(el('span', '', t('prompt_converter.source_format')), sourceSelect);
  const targetField = el('label', 'pc-field');
  targetField.append(el('span', '', t('prompt_converter.target_format')), targetSelect);
  const artistField = el('label', 'pc-field pc-artist-field');
  artistField.append(
    el('span', '', t('prompt_converter.known_artist_names')),
    artistNames,
    el('small', '', t('prompt_converter.artist_names_hint')),
  );
  settingsRow.append(sourceField, targetField, artistField);
  const actions = el('div', 'pc-actions');
  const convert = button(t('prompt_converter.convert'), convertNow, 'tl-primary');
  const copyPositive = button(t('prompt_converter.copy_positive'), () =>
    copyText(positiveResult.value),
  );
  const copyNegative = button(t('prompt_converter.copy_negative'), () =>
    copyText(negativeResult.value),
  );
  const openLab = button(t('prompt_converter.open_in_generation_compare'), openInLab);
  const labHint = el('small', 'pc-lab-hint', t('prompt_converter.nai_lab_hint'));
  const pickImage = button(t('prompt_converter.choose_gallery_image'), openPicker);
  const queueStatus = el('span', 'pc-queue-status');
  const queuePrevious = button(t('prompt_converter.previous_image'), () => moveQueue(-1));
  const queueNext = button(t('prompt_converter.next_image'), () => moveQueue(1));
  actions.append(pickImage, convert, copyPositive, copyNegative, openLab, labHint);
  const queueControls = el('div', 'pc-queue');
  queueControls.hidden = true;
  queueControls.append(queuePrevious, queueStatus, queueNext);
  const report = el('div', 'pc-reports');
  report.append(changesPanel, warningsPanel);
  root.append(
    el('p', 'pc-intro', t('prompt_converter.intro')),
    settingsRow,
    actions,
    queueControls,
    status,
    textColumns,
    report,
  );

  const dialog = el('dialog', 'pc-picker');
  state.dialog = dialog;
  const pickerHead = el('header', 'pc-picker-head');
  const pickerTitle = el('h2', '', t('prompt_converter.choose_gallery_image'));
  const pickerClose = button(t('gallery.close'), () => dialog.close());
  pickerHead.append(pickerTitle, pickerClose);
  const pickerMessage = el('p', 'pc-status');
  const pickerGrid = el('div', 'pc-gallery-grid');
  const pickerFooter = el('footer', 'pc-picker-foot');
  const pickerPrev = button(t('gallery.previous'), () => loadGalleryPage(state.galleryPage - 1));
  const pickerPage = el('span', 'pc-queue-status');
  const pickerNext = button(t('gallery.next'), () => loadGalleryPage(state.galleryPage + 1));
  pickerFooter.append(pickerPrev, pickerPage, pickerNext);
  dialog.append(pickerHead, pickerMessage, pickerGrid, pickerFooter);
  root.append(dialog);

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
      ctx.notify(t('prompt_converter.copied'));
    } catch (error) {
      ctx.notify(t('prompt_converter.copy_failed', [error.message]), true);
    }
  }

  function clearReport() {
    changes.replaceChildren();
    warnings.replaceChildren();
  }

  function fieldName(value) {
    return (
      {
        positive: t('prompt_converter.field.positive'),
        negative: t('prompt_converter.field.negative'),
      }[value] || String(value || '')
    );
  }

  function invalidateResult() {
    state.revision++;
    state.conversionRequest++;
    state.converting = false;
    state.result = null;
    positiveResult.value = '';
    negativeResult.value = '';
    clearReport();
    status.textContent = t('prompt_converter.source_changed');
    updateActions();
  }

  function renderReport(result) {
    clearReport();
    for (const change of result?.changes || []) {
      const item = el('li', '', t('prompt_converter.change_item', [fieldName(change.field)]));
      const before = el('pre', 'pc-before', change.before ?? '');
      const after = el('pre', 'pc-after', change.after ?? '');
      item.append(before, after);
      changes.append(item);
    }
    if (!changes.childElementCount)
      changes.append(el('li', 'pc-muted', t('prompt_converter.no_changes')));
    for (const warning of result?.warnings || []) {
      const message =
        {
          weight: t('prompt_converter.warning.weight', [fieldName(warning.field)]),
          nonpositive_weight: t('prompt_converter.warning.nonpositive_weight', [
            fieldName(warning.field),
          ]),
          unsupported: t('prompt_converter.warning.unsupported', [fieldName(warning.field)]),
          unbalanced: t('prompt_converter.warning.unbalanced', [fieldName(warning.field)]),
          bare_artists: t('prompt_converter.warning.bare_artists', [fieldName(warning.field)]),
        }[warning.code] || t('prompt_converter.warning.unknown', [fieldName(warning.field)]);
      const item = el('li', '', message);
      if (warning.text) item.append(el('pre', 'pc-warning-excerpt', warning.text));
      warnings.append(item);
    }
    if (!warnings.childElementCount)
      warnings.append(el('li', 'pc-muted', t('prompt_converter.no_warnings')));
  }

  async function convertNow() {
    if (state.loading) return;
    state.positive = positiveSource.value;
    state.negative = negativeSource.value;
    state.artists = artistNames.value;
    const revision = state.revision;
    const requestId = ++state.conversionRequest;
    const request = {
      positive: state.positive,
      negative: state.negative,
      source: state.source,
      target: state.target,
      artists: state.artists
        .split(/\r?\n/)
        .map((name) => name.trim())
        .filter(Boolean),
    };
    state.converting = true;
    updateActions();
    status.textContent = t('prompt_converter.converting');
    try {
      const result = await convertProvider(request);
      if (requestId !== state.conversionRequest || revision !== state.revision) return;
      state.result = result;
      positiveResult.value = result.positive ?? '';
      negativeResult.value = result.negative ?? '';
      renderReport(result);
      status.textContent = t('prompt_converter.converted');
    } catch (error) {
      if (requestId !== state.conversionRequest || revision !== state.revision) return;
      status.textContent = t('prompt_converter.conversion_failed');
      ctx.notify(status.textContent, true);
    } finally {
      if (requestId === state.conversionRequest) state.converting = false;
      updateActions();
    }
  }

  function updateActions() {
    const hasResult = !!state.result && !state.loading;
    convert.disabled = state.loading || state.converting;
    positiveSource.disabled = state.loading;
    negativeSource.disabled = state.loading;
    sourceSelect.disabled = state.loading;
    artistNames.disabled = state.loading;
    positiveResult.disabled = state.loading;
    negativeResult.disabled = state.loading;
    copyPositive.disabled = !hasResult;
    copyNegative.disabled = !hasResult;
    openLab.disabled = !hasResult || state.target === 'nai' || state.converting;
    labHint.hidden = state.target !== 'nai';
  }

  async function openInLab() {
    if (!state.result || state.loading || state.converting || state.target === 'nai') return;
    const family = state.target;
    const revision = state.revision;
    const positive = positiveResult.value;
    const negative = negativeResult.value;
    const source = state.imageLabel ? {label: state.imageLabel} : undefined;
    const sourceFamily = state.family;
    const sourceSettings = state.settings;
    let settings;
    if (sourceFamily === family && sourceSettings) settings = {...sourceSettings, family};
    else {
      const comfy = await ctx.api('/api/comfy').catch(() => null);
      settings = switchFamily(comfy, {}, family);
    }
    if (revision !== state.revision || family !== state.target || !state.result || state.loading)
      return;
    onOpenLab({
      positive,
      negative,
      settings,
      source,
    });
  }

  function setPrompts({
    positive = '',
    negative = '',
    settings = null,
    family = '',
    source = '',
    label = '',
    preserveQueue = false,
  } = {}) {
    state.revision++;
    state.conversionRequest++;
    state.converting = false;
    state.metadataRequest++;
    state.loading = false;
    if (!preserveQueue) {
      state.queue = [];
      state.queueIndex = 0;
      queueControls.hidden = true;
      queueStatus.textContent = '';
    }
    state.positive = String(positive ?? '');
    state.negative = String(negative ?? '');
    state.settings = settings && typeof settings === 'object' ? settings : null;
    state.family = ['anima', 'sdxl'].includes(family) ? family : '';
    if (['nai', 'anima', 'sdxl'].includes(source)) {
      state.source = source;
      sourceSelect.value = source;
    } else if (state.family) {
      state.source = state.family;
      sourceSelect.value = state.family;
    }
    state.imageLabel = label;
    state.result = null;
    positiveSource.value = state.positive;
    negativeSource.value = state.negative;
    positiveResult.value = '';
    negativeResult.value = '';
    status.textContent = label ? t('prompt_converter.loaded_image', [label]) : '';
    clearReport();
    updateActions();
  }

  function clearMissingPrompt(preserveQueue = false) {
    state.loading = false;
    setPrompts({preserveQueue});
    status.textContent = t('prompt_converter.no_stored_prompt');
  }

  function beginMetadataLoad(label) {
    state.revision++;
    state.conversionRequest++;
    state.converting = false;
    state.loading = true;
    state.positive = '';
    state.negative = '';
    state.result = null;
    state.settings = null;
    state.family = '';
    state.imageLabel = label;
    positiveSource.value = '';
    negativeSource.value = '';
    positiveResult.value = '';
    negativeResult.value = '';
    clearReport();
    status.textContent = t('prompt_converter.loading_image_record', [label]);
    updateActions();
  }

  async function loadGalleryMetadata(path, label) {
    const request = ++state.metadataRequest;
    pickerMessage.textContent = t('prompt_converter.loading_image_record', [label]);
    state.queue = [];
    state.queueIndex = 0;
    queueControls.hidden = true;
    queueStatus.textContent = '';
    beginMetadataLoad(label);
    try {
      const metadata = await ctx.api(`/api/gallery/metadata?${new URLSearchParams({path})}`);
      if (request !== state.metadataRequest) return;
      if (metadata.error || (metadata.positive == null && metadata.negative == null)) {
        pickerMessage.textContent = t('prompt_converter.no_stored_prompt');
        clearMissingPrompt();
        return;
      }
      const settings = metadata.settings || {};
      const item = state.galleryResults.find(
        (entry) => (entry.relative_path || entry.path) === path,
      );
      setPrompts({
        positive: metadata.positive || '',
        negative: metadata.negative || '',
        settings,
        family:
          metadata.family ||
          metadata.model_family ||
          item?.model_family ||
          item?.family ||
          settings.family ||
          '',
        source: metadata.prompt_profile || metadata.prompt_format || metadata.source_format || '',
        label,
      });
      state.dialog.close();
      ctx.notify(t('prompt_converter.loaded_image', [label]));
    } catch (error) {
      if (request !== state.metadataRequest) return;
      clearMissingPrompt();
      pickerMessage.textContent = error.message || t('prompt_converter.image_record_failed');
    }
  }

  async function loadGalleryPage(page) {
    state.galleryPage = Math.max(1, Math.min(state.galleryPages, page));
    const request = ++state.galleryRequest;
    pickerMessage.textContent = t('gallery.loading_images');
    try {
      const query = new URLSearchParams({page: String(state.galleryPage), page_size: '24'});
      const payload = await ctx.api(`/api/gallery?${query}`);
      if (request !== state.galleryRequest) return;
      state.galleryPage = Number(payload.page || state.galleryPage);
      state.galleryPages = Math.max(1, Number(payload.pages || 1));
      state.galleryResults = Array.isArray(payload.results) ? payload.results : [];
      pickerGrid.replaceChildren();
      for (const item of state.galleryResults) {
        const path = item.relative_path || item.path;
        if (!path) continue;
        const choice = button(
          '',
          () => loadGalleryMetadata(path, item.filename || path),
          'pc-gallery-item',
        );
        const image = el('img');
        image.src =
          item.thumbnail_url ||
          item.image_url ||
          `/api/gallery/thumbnail?${new URLSearchParams({path})}`;
        image.alt = item.filename || path;
        image.loading = 'lazy';
        choice.append(image, el('span', '', item.filename || path));
        pickerGrid.append(choice);
      }
      pickerMessage.textContent = state.galleryResults.length ? '' : t('gallery.no_images_match');
      pickerPage.textContent = t('prompt_converter.gallery_page', [
        state.galleryPage,
        state.galleryPages,
      ]);
      pickerPrev.disabled = state.galleryPage <= 1;
      pickerNext.disabled = state.galleryPage >= state.galleryPages;
    } catch (error) {
      if (request !== state.galleryRequest) return;
      pickerMessage.textContent = error.message || t('gallery.could_not_load_the_image');
    }
  }

  async function openPicker() {
    state.galleryPage = 1;
    state.galleryPages = 1;
    dialog.showModal();
    await loadGalleryPage(1);
  }

  async function loadPaths(paths) {
    state.queue = (Array.isArray(paths) ? paths : []).filter((path) => typeof path === 'string');
    state.queueIndex = 0;
    await loadQueueItem();
  }

  async function loadQueueItem() {
    const path = state.queue[state.queueIndex];
    const request = ++state.metadataRequest;
    queueControls.hidden = !state.queue.length;
    queuePrevious.disabled = state.queueIndex <= 0;
    queueNext.disabled = state.queueIndex >= state.queue.length - 1;
    queueStatus.textContent = state.queue.length
      ? t('prompt_converter.image_count', [state.queueIndex + 1, state.queue.length])
      : '';
    if (!path) return;
    beginMetadataLoad(path);
    try {
      const metadata = await ctx.api(`/api/gallery/metadata?${new URLSearchParams({path})}`);
      if (request !== state.metadataRequest) return;
      if (metadata.error || (metadata.positive == null && metadata.negative == null)) {
        clearMissingPrompt(true);
        return;
      }
      const settings = metadata.settings || {};
      setPrompts({
        positive: metadata.positive || '',
        negative: metadata.negative || '',
        settings,
        family:
          metadata.family ||
          metadata.model_family ||
          settings.family ||
          (metadata.settings && typeof metadata.settings === 'object' ? 'anima' : ''),
        source: metadata.prompt_profile || metadata.prompt_format || metadata.source_format || '',
        label: path,
        preserveQueue: true,
      });
      queueStatus.textContent = t('prompt_converter.image_count', [
        state.queueIndex + 1,
        state.queue.length,
      ]);
    } catch (error) {
      if (request !== state.metadataRequest) return;
      clearMissingPrompt(true);
      status.textContent = error.message || t('prompt_converter.image_record_failed');
    }
  }

  async function moveQueue(direction) {
    const next = state.queueIndex + direction;
    if (next < 0 || next >= state.queue.length) return;
    state.queueIndex = next;
    await loadQueueItem();
  }

  async function enter() {
    const handoff = readHandoff();
    if (handoff?.type === 'prompt-format' && Array.isArray(handoff.paths))
      await loadPaths(handoff.paths);
    else if (handoff?.positive != null || handoff?.negative != null) setPrompts(handoff);
  }

  function updateStrings() {
    // The app currently translates at startup; this hook keeps the view lifecycle explicit.
  }

  updateActions();
  return {element: root, enter, setPrompts, updateStrings};
}
