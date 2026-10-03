// Image tools: a workspace of uploaded and gallery images, what each image says about
// how it was made (PNG text, EXIF, Studio record, WD14 tags), and WebP conversion.

import {MODEL_WORDS, splitTags} from '../lib/tags.js';
import {sendToLab} from './lab.js';
import {withTagComplete} from '../core/tag_input.js';
import {createMaskEditor} from '../core/mask_editor.js';
import {t, tr} from '../core/i18n.js';
import {createPromptConverter} from './prompt_converter.js';

const POLL_MS = 2000;
const ACCEPT = '.png,.webp,.jpg,.jpeg,.zip';
const SOURCE_LABELS = {
  asset_studio: t('tools.asset_studio_record'),
  parameters: 'A1111/Forge parameters',
  comfyui: t('tools.comfyui_workflow'),
};

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
  const n = el('label', 'tl-field');
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
const bytes = (value) =>
  value >= 1024 ** 2 ? `${(value / 1024 ** 2).toFixed(1)}MB` : `${Math.round(value / 1024)}KB`;
const norm = (tag) => tag.toLowerCase().replace(/_/g, ' ').replace(/^@/, '').trim();

export function createTools(ctx) {
  const root = el('section');
  root.id = 'app-tools';
  const state = {
    items: [],
    chosen: new Set(),
    current: '',
    analysis: null,
    tagger: null,
    tab: 'convert',
    convert: {quality: 95, lossless: false, keep_metadata: false, long_side: 0, suffix: ''},
    tag: {model: '', threshold: 0.35, character_threshold: 0.85},
    task: null,
    timer: 0,
    waitingTags: new Set(),
    postInfo: null,
    post: {
      op: 'upscale',
      alpha: {method: 'isnet', confidence: 0.35, grow: 0, feather: 1},
      upscale: {model: '', scale: 2},
      detail: {face: true, eye: true, mouth: false, hand: true, denoise: 0.4, steps: 20},
      // ``for``: the image whose record filled the prompts.
      inpaint: {
        positive: '',
        negative: '',
        denoise: 0.6,
        steps: 0,
        grow: 8,
        feather: 8,
        area: 'crop',
        padding: 64,
        for: '',
      },
    },
    postPending: 0,
    censor: {
      treatment: 'mosaic',
      intensity: 15,
      color: '#ffffff',
      opacity: 100,
      grow: 0,
      feather: 0,
      confidence: 0.35,
      labels: [],
    },
    editor: null,
    editorKey: '',
    compare: 'side',
    slider: 50,
  };

  const header = el('header', 'tl-header');
  header.append(
    el('h1', '', t('common.image_tools')),
    el('p', '', t('tools.upload_images_or_send_them_from')),
  );
  const listPanel = el('aside', 'tl-list');
  const detail = el('div', 'tl-detail');
  const toolPanel = el('aside', 'tl-tools');
  root.append(header, listPanel, detail, toolPanel);
  const promptConverter = createPromptConverter(ctx, {onOpenLab: (draft) => sendToLab(ctx, draft)});

  const current = () => state.items.find((item) => item.id === state.current);
  const chosenIds = () => state.items.filter((i) => state.chosen.has(i.id)).map((i) => i.id);

  // ---- list --------------------------------------------------------------------------

  const fileInput = input('file', '', {accept: ACCEPT, multiple: ''});
  fileInput.hidden = true;
  fileInput.addEventListener('change', () => upload([...fileInput.files]));
  const uploadStatus = el('p', 'tl-muted');

  async function upload(files) {
    if (!files.length) return;
    if (ctx.preview) return ctx.notify(t('tools.uploads_are_off_on_the_preview'), true);
    let added = 0;
    const problems = [];
    for (const [index, file] of files.entries()) {
      uploadStatus.textContent = t('tools.uploading', [index + 1, files.length, file.name]);
      try {
        const response = await fetch('/api/tools/upload', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-File-Name': encodeURIComponent(file.name),
          },
          body: file,
        });
        const data = await response.json();
        if (!response.ok || data.ok === false)
          throw new Error(tr(data.error) || t('tools.upload_failed'));
        added += data.added.length;
        for (const skip of data.skipped || []) problems.push(`${skip.name}: ${tr(skip.error)}`);
      } catch (error) {
        problems.push(`${file.name}: ${error.message}`);
      }
    }
    fileInput.value = '';
    uploadStatus.textContent = t('tools.added', [
      added,
      problems.length ? t('tools.skipped', [problems.length]) : '',
    ]);
    uploadStatus.title = problems.join('\n');
    if (problems.length) ctx.notify(problems.slice(0, 3).join(' / '), true);
    await loadItems();
  }

  async function removeChosen() {
    const ids = chosenIds();
    if (!ids.length) return;
    if (!window.confirm(t('tools.remove_images_from_the_list_uploaded', [ids.length]))) return;
    try {
      await ctx.api('/api/tools/remove', {ids});
      state.chosen.clear();
      if (ids.includes(state.current)) state.current = '';
      await loadItems();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  function renderList() {
    const tools = el('div', 'tl-row');
    const pick = btn(t('tools.upload_files_or_zip'), () => fileInput.click(), 'tl-primary');
    pick.disabled = !!ctx.preview;
    const all = btn(
      state.chosen.size === state.items.length && state.items.length
        ? t('common.clear_selection')
        : t('common.select_all'),
      () => {
        if (state.chosen.size === state.items.length) state.chosen.clear();
        else for (const item of state.items) state.chosen.add(item.id);
        renderList();
        renderTools();
      },
    );
    const remove = btn(t('tools.remove_from_list'), removeChosen);
    remove.disabled = !state.chosen.size || !!ctx.preview;
    const download = btn(t('tools.download_zip', [state.chosen.size]), () => {
      window.location.href = `/api/tools/zip?ids=${chosenIds().join(',')}`;
    });
    download.disabled = !state.chosen.size || state.chosen.size > 500;
    tools.append(pick, all, remove, download, fileInput);
    const grid = el('div', 'tl-grid');
    if (!state.items.length)
      grid.append(el('p', 'tl-drop-hint', t('tools.drop_png_webp_jpeg_or_zip')));
    for (const item of state.items) {
      const card = el('div', 'tl-card');
      if (item.id === state.current) card.classList.add('current');
      const check = input('checkbox', state.chosen.has(item.id));
      check.setAttribute('aria-label', t('common.select', [item.name]));
      check.addEventListener('change', () => {
        if (check.checked) state.chosen.add(item.id);
        else state.chosen.delete(item.id);
        renderList();
        renderTools();
      });
      const image = el('img');
      image.src = `/api/tools/thumbnail?id=${item.id}`;
      image.alt = item.name;
      image.loading = 'lazy';
      image.addEventListener('click', () => show(item.id));
      const caption = el('div', 'tl-card-caption');
      caption.append(
        check,
        el('span', 'tl-name', item.name),
        el(
          'small',
          `tl-badge tl-${item.source}`,
          item.source === 'gallery' ? t('common.gallery') : t('tools.upload'),
        ),
      );
      if (item.tags) caption.append(el('small', 'tl-badge tl-tagged', t('tools.tags')));
      card.title = `${item.name} · ${item.width}×${item.height} · ${item.format}`;
      card.append(image, caption);
      grid.append(card);
    }
    listPanel.replaceChildren(tools, uploadStatus, grid);
  }
  listPanel.addEventListener('dragover', (event) => {
    event.preventDefault();
    listPanel.classList.add('dragging');
  });
  listPanel.addEventListener('dragleave', () => listPanel.classList.remove('dragging'));
  listPanel.addEventListener('drop', (event) => {
    event.preventDefault();
    listPanel.classList.remove('dragging');
    upload([...(event.dataTransfer?.files || [])]);
  });

  // ---- detail: image, metadata, tags ------------------------------------------------

  /** False when the user keeps unsaved mask edits. */
  function leaveEditor() {
    if (!state.editor?.isDirty()) return true;
    if (!window.confirm(t('tools.there_are_unsaved_mask_edits_discard'))) return false;
    state.editor = null;
    state.editorKey = '';
    return true;
  }

  async function show(id) {
    if (id !== state.current && !leaveEditor()) return;
    state.current = id;
    state.analysis = null;
    renderList();
    renderDetail();
    // The forms read the current image (its masks, record), so redraw them too.
    renderTools();
    try {
      state.analysis = await ctx.api(`/api/tools/analyze?id=${id}`);
    } catch (error) {
      state.analysis = {error: error.message};
    }
    if (state.current === id) {
      renderDetail();
      renderTools();
    }
  }

  const excluded = () => new Set((state.tagger?.exclude || []).map(norm));
  const visibleTags = (item) => (item.tags?.tags || []).filter((tag) => !excluded().has(norm(tag)));

  async function copyTags(item) {
    try {
      await navigator.clipboard.writeText(visibleTags(item).join(', '));
      ctx.notify(t('tools.tags_copied'));
    } catch (error) {
      ctx.notify(t('tools.could_not_copy', [error.message]), true);
    }
  }

  async function saveExcludes(text) {
    try {
      const result = await ctx.api('/api/settings/save', {
        section: 'tags',
        values: {exclude: splitTags(text)},
      });
      state.tagger = {...state.tagger, exclude: result.values.exclude || []};
      ctx.notify(t('tools.excluded_tags_saved'));
      renderTools();
      renderDetail();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  function tagReview(tags, prompt) {
    const box = el('div', 'tl-tags');
    const inPrompt = new Set(splitTags(prompt).map(norm));
    const seen = new Set(tags.map(norm));
    const both = tags.filter((t) => inPrompt.has(norm(t)));
    const imageOnly = tags.filter((t) => !inPrompt.has(norm(t)));
    const promptOnly = splitTags(prompt).filter(
      // Quality words, artists and sentences are never visible in the picture itself.
      (t) =>
        !seen.has(norm(t)) && !MODEL_WORDS.test(t) && !t.startsWith('@') && !/\s\S+\s\S+\s/.test(t),
    );
    const group = (title, list, cls, hint) => {
      if (!list.length) return;
      const head = el('h4', '', `${title} ${list.length}`);
      head.title = hint;
      const chips = el('div', 'tl-chips');
      for (const tag of list) chips.append(el('span', `tl-chip ${cls}`, tag));
      box.append(head, chips);
    };
    if (!prompt) {
      group(t('tools.tags_read_by_the_tagger'), tags, 'tl-seen', '');
      return box;
    }
    group(t('tools.matches_the_prompt'), both, 'tl-both', t('tools.tags_in_the_prompt_that_were'));
    group(
      t('tools.only_seen_in_the_image'),
      imageOnly,
      'tl-seen',
      t('tools.tags_the_tagger_read_in_the'),
    );
    group(
      t('tools.not_seen_in_the_image'),
      promptOnly,
      'tl-missing',
      t('tools.tags_in_the_prompt_that_the'),
    );
    return box;
  }

  /** Source and result of a post-processing step, side by side or under a slider. */
  function comparison(parent, item) {
    const box = el('div', 'tl-compare');
    const modes = el('div', 'tl-row');
    for (const [key, text] of [
      ['side', t('common.side_by_side')],
      ['slider', t('common.slider')],
    ]) {
      const b = btn(text, () => {
        state.compare = key;
        renderDetail();
      });
      b.setAttribute('aria-pressed', String(state.compare === key));
      modes.append(b);
    }
    modes.append(el('small', 'tl-muted', t('tools.original_2', [parent.name])));
    const before = el('img');
    before.src = `/api/tools/image?id=${parent.id}`;
    before.alt = t('tools.original');
    const after = el('img');
    after.src = `/api/tools/image?id=${item.id}`;
    after.alt = t('tools.result');
    if (state.compare === 'slider') {
      const frame = el('div', 'tl-slider');
      after.className = 'tl-over';
      const line = el('div', 'tl-line');
      const range = el('input');
      range.type = 'range';
      range.min = '0';
      range.max = '100';
      range.value = String(state.slider);
      range.setAttribute('aria-label', t('tools.border_between_original_and_result'));
      const place = () => {
        after.style.clipPath = `inset(0 0 0 ${state.slider}%)`;
        line.style.left = `${state.slider}%`;
      };
      range.addEventListener('input', () => {
        state.slider = Number(range.value);
        place();
      });
      place();
      frame.append(before, after, line, range);
      box.append(modes, frame);
    } else {
      const pair = el('div', 'tl-pair');
      pair.append(before, after);
      box.append(modes, pair);
    }
    return box;
  }

  // Censor masks say what to cover (red); alpha masks say what to keep (blue).
  const MASK_KINDS = {
    censor: {field: 'mask', color: [255, 40, 60], preview: false},
    alpha: {field: 'alpha_mask', color: [40, 120, 255], preview: true},
    inpaint: {field: 'inpaint_mask', color: [40, 200, 90], preview: false},
  };

  function maskEditor(item, kind) {
    const spec = MASK_KINDS[kind];
    const saved = item[spec.field];
    const key = `${kind}:${item.id}:${saved?.updated_at || ''}`;
    // Keep the open editor (and its strokes) unless the image, kind or saved mask changed.
    if (state.editor && state.editorKey === key) return state.editor.element;
    state.editorKey = key;
    state.editor = createMaskEditor({
      imageUrl: `/api/tools/image?id=${item.id}`,
      maskUrl: saved
        ? `/api/tools/mask?id=${item.id}&kind=${kind}&v=${encodeURIComponent(saved.updated_at)}`
        : null,
      width: item.width,
      height: item.height,
      color: spec.color,
      preview: spec.preview,
      onSave: async (blob) => {
        const response = await fetch('/api/tools/mask', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-Item-Id': item.id,
            'X-Mask-Kind': kind,
          },
          body: blob,
        });
        const data = await response.json();
        if (!response.ok || data.ok === false)
          throw new Error(tr(data.error) || t('common.could_not_save', [response.status]));
        // The saved mask is what the editor already shows; keep it open.
        Object.assign(item, data.item);
        state.editorKey = `${kind}:${item.id}:${item[spec.field]?.updated_at || ''}`;
      },
      onChange: () => renderTools(),
    });
    if (!saved)
      state.editor.setStatus(
        {
          alpha: t('tools.no_mask_split_the_background_or'),
          censor: t('common.no_mask_paint_with_the_brush'),
          inpaint: t('tools.no_mask_paint_the_area_to'),
        }[kind],
      );
    return state.editor.element;
  }

  function renderDetail() {
    if (state.tab === 'prompt') {
      root.classList.add('prompt-mode');
      detail.replaceChildren(promptConverter.element);
      return;
    }
    root.classList.remove('prompt-mode');
    const item = current();
    if (!item) {
      detail.replaceChildren(el('p', 'tl-muted', t('tools.choose_an_image_on_the_left')));
      return;
    }
    if (state.tab === 'alpha') {
      detail.replaceChildren(
        maskEditor(item, 'alpha'),
        el('p', 'tl-muted', t('tools.the_blue_area_stays_and_the')),
      );
      return;
    }
    if (state.tab === 'inpaint') {
      detail.replaceChildren(
        maskEditor(item, 'inpaint'),
        el('p', 'tl-muted', t('tools.only_the_green_area_is_redrawn')),
      );
      return;
    }
    if (state.tab === 'censor') {
      detail.replaceChildren(
        maskEditor(item, 'censor'),
        el('p', 'tl-muted', t('tools.the_red_area_gets_covered_widen')),
      );
      return;
    }
    const figure = el('figure', 'tl-figure');
    const image = el('img');
    image.src = `/api/tools/image?id=${item.id}`;
    image.alt = item.name;
    const parent = item.parent && state.items.find((i) => i.id === item.parent);
    figure.append(
      parent ? comparison(parent, item) : image,
      el(
        'figcaption',
        '',
        `${item.name} · ${item.width}×${item.height} · ${item.format} · ${bytes(item.bytes || 0)}`,
      ),
    );
    const info = el('div', 'tl-info');
    const a = state.analysis;
    if (!a) info.append(el('p', 'tl-muted', t('tools.reading_metadata')));
    else if (a.error) info.append(el('p', 'tl-error', tr(a.error)));
    else {
      const found = a.prompt || {};
      const head = el('div', 'tl-row tl-between');
      head.append(
        el(
          'h3',
          '',
          found.source
            ? t('tools.prompt', [SOURCE_LABELS[found.source]])
            : t('tools.no_prompt_record'),
        ),
      );
      if (found.positive)
        head.append(
          btn(t('common.open_in_lab'), () =>
            sendToLab(ctx, {
              positive: found.positive,
              negative: found.negative || '',
              // Only Studio records carry settings the lab form understands.
              settings: found.source === 'asset_studio' ? found.settings : undefined,
              source: {label: t('tools.image_tools', [item.name])},
            }),
          ),
          btn(t('prompt_converter.open_in_prompt_format'), () => {
            if (!leaveEditor()) return;
            state.tab = 'prompt';
            promptConverter.setPrompts({
              positive: found.positive,
              negative: found.negative || '',
              settings: found.settings || null,
              family: found.settings?.family || '',
              label: item.name,
            });
            renderTools();
            renderDetail();
          }),
        );
      info.append(head);
      if (found.positive) {
        info.append(el('h4', '', t('tools.positive')), el('pre', '', found.positive));
        if (found.negative)
          info.append(el('h4', '', t('tools.negative')), el('pre', '', found.negative));
        const settings = Object.entries(found.settings || {}).filter(
          ([, v]) => typeof v !== 'object',
        );
        if (settings.length) {
          const table = el('dl', 'tl-dl');
          for (const [key, value] of settings)
            table.append(el('dt', '', key), el('dd', '', String(value)));
          info.append(el('h4', '', t('common.settings')), table);
        }
      }
      const models = a.comfy?.models || [];
      if (models.length) {
        info.append(el('h4', '', t('tools.models_used')));
        const list = el('ul', 'tl-models');
        for (const model of models)
          list.append(el('li', '', `${model.node}: ${Object.values(model).slice(1).join(', ')}`));
        info.append(list);
      }
      const facts = el('p', 'tl-muted');
      facts.textContent = [
        a.has_alpha ? t('tools.has_transparency') : t('tools.no_transparency'),
        a.has_workflow ? t('tools.contains_a_comfyui_workflow') : '',
        a.text_keys.length
          ? t('tools.text_entries', [a.text_keys.join(', ')])
          : t('tools.no_text_entries'),
      ]
        .filter(Boolean)
        .join(' · ');
      info.append(facts);
      const exif = Object.entries(a.exif || {});
      if (exif.length) {
        const more = el('details');
        more.append(el('summary', '', t('tools.exif', [exif.length])));
        const table = el('dl', 'tl-dl');
        for (const [key, value] of exif) table.append(el('dt', '', key), el('dd', '', value));
        more.append(table);
        info.append(more);
      }
      const tags = item.tags?.tags && visibleTags(item);
      const tagHead = el('div', 'tl-row tl-between');
      tagHead.append(el('h3', '', t('tools.wd14_tags')));
      if (tags) {
        const actions = el('div', 'tl-row');
        actions.append(
          btn(t('tools.copy_tags'), () => copyTags(item)),
          btn(t('tools.open_tags_in_lab'), () =>
            sendToLab(ctx, {
              positive: tags.join(', '),
              negative: '',
              source: {label: t('tools.image_tools', [item.name])},
            }),
          ),
        );
        tagHead.append(actions);
      }
      info.append(tagHead);
      if (tags) {
        const hidden = item.tags.tags.length - tags.length;
        if (hidden) info.append(el('p', 'tl-muted', t('tools.excluded_tags_are_hidden', [hidden])));
        info.append(
          el(
            'p',
            'tl-muted',
            t('tools.general_character', [
              item.tags.model,
              item.tags.threshold,
              item.tags.character_threshold,
            ]),
          ),
          tagReview(tags, found.positive || ''),
        );
      } else
        info.append(
          el(
            'p',
            'tl-muted',
            state.waitingTags.has(item.id)
              ? t('tools.waiting_for_tagging')
              : t('tools.not_analyzed_yet_run_it_from'),
          ),
        );
    }
    detail.replaceChildren(figure, info);
  }

  // ---- tools: WebP conversion and tagging ---------------------------------------------

  async function startConvert() {
    const ids = chosenIds();
    try {
      const result = await ctx.api('/api/tools/convert', {...state.convert, ids});
      state.task = result.task;
      renderTools();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  async function startTags() {
    const ids = chosenIds();
    try {
      await ctx.api('/api/jobs/tags', {...state.tag, ids});
      for (const id of ids) state.waitingTags.add(id);
      ctx.notify(t('tools.queued_images_for_tagging', [ids.length]));
      ctx.onQueueChanged?.();
      renderDetail();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  function convertForm() {
    const box = el('div');
    const c = state.convert;
    const quality = input('range', c.quality, {min: 1, max: 100});
    const qualityNumber = input('number', c.quality, {min: 1, max: 100});
    const setQuality = (value) => {
      c.quality = Math.max(1, Math.min(100, Number(value) || 95));
      quality.value = qualityNumber.value = String(c.quality);
    };
    quality.addEventListener('input', () => setQuality(quality.value));
    qualityNumber.addEventListener('input', () => setQuality(qualityNumber.value));
    const qualityRow = el('div', 'tl-row');
    qualityRow.append(quality, qualityNumber);
    const lossless = input('checkbox', c.lossless);
    lossless.addEventListener('change', () => {
      c.lossless = lossless.checked;
      quality.disabled = qualityNumber.disabled = c.lossless;
    });
    quality.disabled = qualityNumber.disabled = c.lossless;
    const keep = input('checkbox', c.keep_metadata);
    keep.addEventListener('change', () => (c.keep_metadata = keep.checked));
    const longSide = input('number', c.long_side, {min: 0, max: 8192, step: 16});
    longSide.addEventListener(
      'input',
      () => (c.long_side = Math.max(0, Number(longSide.value) || 0)),
    );
    const suffix = input('text', c.suffix, {placeholder: t('tools.e_g_web')});
    suffix.addEventListener('input', () => (c.suffix = suffix.value));
    const check = (control, text, hint) => {
      const n = el('label', 'tl-check');
      n.append(control, el('span', '', text));
      if (hint) n.title = hint;
      return n;
    };
    const count = chosenIds().length;
    const run = btn(t('tools.convert_selected_to_webp', [count]), startConvert, 'tl-primary');
    run.disabled = !count || !!ctx.preview || state.task?.status === 'running';
    box.append(
      field(t('common.quality'), qualityRow, t('tools.default_95_ignored_when_lossless_is')),
      check(lossless, t('tools.lossless')),
      check(keep, t('tools.keep_metadata'), t('tools.keeps_the_comfyui_prompt_and_workflow')),
      el('small', 'tl-muted', t('tools.off_default_removes_the_prompt_workflow')),
      field(t('tools.long_side_px'), longSide, t('tools.0_keeps_the_original_size')),
      field(t('tools.file_name_suffix'), suffix, t('tools.results_are_saved_in_outputs_tools')),
      run,
    );
    const task = state.task;
    if (task) {
      const result = el('div', 'tl-task');
      result.append(
        el(
          'p',
          '',
          `${task.status === 'running' ? t('tools.converting') : t('common.done')} ${task.done}/${task.total}`,
        ),
      );
      let before = 0;
      let after = 0;
      for (const r of task.results) {
        before += r.source_bytes || 0;
        after += r.bytes;
      }
      if (task.results.length)
        result.append(
          el(
            'p',
            'tl-muted',
            `${bytes(before)} → ${bytes(after)} (${before ? Math.round((after / before) * 100) : 0}%)`,
          ),
        );
      for (const error of task.errors)
        result.append(el('p', 'tl-error', `${error.name}: ${tr(error.error)}`));
      if (task.status !== 'running' && task.results.length) {
        const zip = el('a', 'tl-link', t('tools.download_zip', [task.results.length]));
        zip.href = `/api/tools/convert/zip?id=${task.id}`;
        result.append(zip);
      }
      box.append(result);
    }
    return box;
  }

  function tagForm() {
    const box = el('div');
    const info = state.tagger;
    if (!info) {
      box.append(el('p', 'tl-muted', t('tools.reading_tagger_information')));
      return box;
    }
    if (!info.available) {
      box.append(el('p', 'tl-error', tr(info.error)));
      return box;
    }
    const tagging = state.tag;
    if (!tagging.model) tagging.model = info.defaults.model;
    const model = el('select');
    for (const name of info.models) {
      const option = el('option', '', name);
      option.value = name;
      model.append(option);
    }
    model.value = tagging.model;
    model.addEventListener('change', () => (tagging.model = model.value));
    const threshold = input('number', tagging.threshold, {min: 0, max: 1, step: 0.05});
    threshold.addEventListener('input', () => (tagging.threshold = Number(threshold.value)));
    const character = input('number', tagging.character_threshold, {min: 0, max: 1, step: 0.05});
    character.addEventListener(
      'input',
      () => (tagging.character_threshold = Number(character.value)),
    );
    const count = chosenIds().length;
    const run = btn(t('tools.tag_selected', [count]), startTags, 'tl-primary');
    run.disabled = !count || !!ctx.preview;
    box.append(
      field(t('common.model'), model, t('tools.comfyui_downloads_a_model_from_hugging')),
      field(t('tools.general_tag_threshold'), threshold),
      field(t('tools.character_tag_threshold'), character),
      run,
      el('p', 'tl-muted', t('tools.shares_the_generation_queue_so_it')),
    );

    box.append(el('h4', '', t('tools.excluded_tags')));
    const exclude = el('textarea');
    exclude.rows = 3;
    exclude.value = (info.exclude || []).join(', ');
    exclude.placeholder = 'simple background, white background';
    const saveExclude = btn(t('tools.save_exclusions'), () => saveExcludes(exclude.value));
    saveExclude.disabled = !!ctx.preview;
    box.append(
      exclude,
      saveExclude,
      el('small', 'tl-muted', t('tools.separate_with_commas_they_are_left')),
    );

    box.append(el('h4', '', t('tools.export_tags')));
    const tagged = state.items.filter((i) => state.chosen.has(i.id) && i.tags);
    const exportAs = (format) => {
      const ids = tagged.map((i) => i.id).join(',');
      window.location.href = `/api/tools/tags/export?format=${format}&ids=${ids}`;
    };
    const asText = btn(t('tools.txt', [tagged.length]), () => exportAs('txt'));
    const asJson = btn(t('tools.json', [tagged.length]), () => exportAs('json'));
    asText.disabled = asJson.disabled = !tagged.length || tagged.length > 500;
    const row = el('div', 'tl-row');
    row.append(asText, asJson);
    box.append(row, el('small', 'tl-muted', t('tools.txt_packs_one_caption_file_per')));
    return box;
  }

  async function startPost() {
    const ids = chosenIds();
    const op = state.post.op;
    const options = {...state.post[op]};
    if (op === 'censor' && !options.labels.length) delete options.labels;
    try {
      const result = await ctx.api('/api/jobs/postprocess', {ids, op, options});
      state.postPending += result.jobs.length;
      ctx.notify(t('tools.queued_images_for_post_processing_results', [result.jobs.length]));
      ctx.onQueueChanged?.();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  const CENSOR_LABELS = [
    'nipples',
    'pussy',
    'penis',
    'anus',
    'testicles',
    'x-ray',
    'cross-section',
  ];

  async function startDetect() {
    const ids = chosenIds();
    const masked = state.items.filter((i) => ids.includes(i.id) && i.mask).length;
    if (masked && !window.confirm(t('tools.of_these_images_already_have_a', [masked]))) return;
    const options = {confidence: state.censor.confidence};
    if (state.censor.labels.length) options.labels = state.censor.labels;
    try {
      const result = await ctx.api('/api/jobs/postprocess', {ids, op: 'detect', options});
      state.postPending += result.jobs.length;
      ctx.notify(t('tools.queued_area_detection_for_images', [result.jobs.length]));
      ctx.onQueueChanged?.();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  async function startSplit() {
    const ids = chosenIds();
    const masked = state.items.filter((i) => ids.includes(i.id) && i.alpha_mask).length;
    if (masked && !window.confirm(t('tools.of_these_images_already_have_a', [masked]))) return;
    const a = state.post.alpha;
    try {
      const result = await ctx.api('/api/jobs/postprocess', {
        ids,
        op: 'alpha',
        options: {method: a.method, confidence: Number(a.confidence)},
      });
      state.postPending += result.jobs.length;
      ctx.notify(t('tools.queued_background_splitting_for_images', [result.jobs.length]));
      ctx.onQueueChanged?.();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  const alphaBody = () => ({
    grow: Number(state.post.alpha.grow),
    feather: Number(state.post.alpha.feather),
  });
  const censorBody = () => {
    const c = state.censor;
    return {
      treatment: c.treatment,
      intensity: Number(c.intensity),
      color: c.color,
      opacity: Number(c.opacity),
      grow: Number(c.grow),
      feather: Number(c.feather),
    };
  };
  const APPLY = {
    alpha: {url: '/api/tools/alpha', body: alphaBody},
    censor: {url: '/api/tools/censor', body: censorBody},
  };
  const chosenWithMask = (kind) =>
    state.items.filter((i) => state.chosen.has(i.id) && i[MASK_KINDS[kind].field]);

  async function applyAlpha() {
    try {
      if (state.editor?.isDirty()) await state.editor.save();
      await ctx.api('/api/tools/alpha', {id: state.current, ...alphaBody()});
      ctx.notify(t('tools.added_the_image_with_a_transparent'));
      await loadItems();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  // Apply to every chosen image with its own saved mask; images without one are skipped.
  async function applyChosen(kind) {
    try {
      if (state.editor?.isDirty()) await state.editor.save();
    } catch (error) {
      return ctx.notify(error.message, true);
    }
    const targets = chosenWithMask(kind);
    const skipped = state.chosen.size - targets.length;
    let done = 0;
    for (const target of targets) {
      try {
        await ctx.api(APPLY[kind].url, {id: target.id, ...APPLY[kind].body()});
        done += 1;
      } catch (error) {
        ctx.notify(`${target.name}: ${error.message}`, true);
      }
    }
    ctx.notify(t('tools.applied_to_images_without_a_mask', [done, skipped]));
    await loadItems();
  }
  function applyChosenButton(kind) {
    const count = chosenWithMask(kind).length;
    const button = btn(t('tools.apply_to_chosen_images_with_a', [count]), () => applyChosen(kind));
    button.disabled = !count || !!ctx.preview;
    return button;
  }

  function alphaForm() {
    const box = el('div');
    const a = state.post.alpha;
    const info = state.postInfo;
    const item = current();
    box.append(el('h4', '', t('tools.1_split_the_background_optional')));
    const method = el('select');
    for (const [value, text] of [
      ['isnet', t('tools.isnet_anime_anime_illustrations')],
      ['person', t('tools.person_segmentation_yolo_person')],
    ]) {
      const option = el('option', '', text);
      option.value = value;
      method.append(option);
    }
    method.value = a.method;
    method.addEventListener('change', () => {
      a.method = method.value;
      renderTools();
    });
    box.append(field(t('common.method'), method));
    if (a.method === 'person') {
      const confidence = input('number', a.confidence, {min: 0, max: 1, step: 0.05});
      confidence.addEventListener('input', () => (a.confidence = Number(confidence.value)));
      box.append(field(t('tools.detection_confidence'), confidence));
    }
    const count = chosenIds().length;
    const split = btn(t('tools.split_the_background_of_selected', [count]), startSplit);
    split.disabled = !count || !!ctx.preview || !info?.available || !info.ops?.alpha;
    box.append(split);
    if (info && !info.available) box.append(el('p', 'tl-error', tr(info.error)));

    box.append(el('h4', '', t('tools.2_fix_the_mask')));
    const save = btn(t('tools.save_mask'), saveMask);
    save.disabled = !item || !state.editor?.isDirty() || !!ctx.preview;
    box.append(
      el(
        'p',
        'tl-muted',
        item?.alpha_mask
          ? t('tools.mask', [
              item.alpha_mask.source === 'detected'
                ? t('tools.detected')
                : t('tools.edited_by_hand'),
            ])
          : t('tools.no_mask'),
      ),
      save,
    );

    box.append(el('h4', '', t('tools.3_apply')));
    const numberOf = (key, attrs) => {
      const control = input('number', a[key], attrs);
      control.addEventListener('input', () => (a[key] = Number(control.value)));
      return control;
    };
    const apply = btn(t('tools.apply_to_this_image_2'), applyAlpha, 'tl-primary');
    apply.disabled = !item || (!item.alpha_mask && !state.editor?.isDirty()) || !!ctx.preview;
    box.append(
      field(
        t('tools.grow_mask_px'),
        numberOf('grow', {min: -64, max: 64}),
        t('tools.negative_values_shrink_it'),
      ),
      field(
        t('tools.soft_edge_px'),
        numberOf('feather', {min: 0, max: 64}),
        t('tools.for_a_1536px_image_start_with'),
      ),
      apply,
      applyChosenButton('alpha'),
      el('small', 'tl-muted', t('tools.saves_a_new_png_with_only')),
    );
    box.append(whereSaved());
    return box;
  }

  async function startInpaint() {
    try {
      if (state.editor?.isDirty()) await state.editor.save();
      const {for: filledFor, ...options} = state.post.inpaint;
      // Prompts not yet filled from this image's record are left to the server, which
      // uses the record; once shown, what is in the boxes is sent (an emptied box too).
      if (filledFor !== state.current) {
        delete options.positive;
        delete options.negative;
      }
      const result = await ctx.api('/api/jobs/postprocess', {
        ids: [state.current],
        op: 'inpaint',
        options,
      });
      state.postPending += result.jobs.length;
      ctx.notify(t('tools.inpaint_queued_the_result_is_added'));
      ctx.onQueueChanged?.();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  function inpaintForm() {
    const box = el('div');
    const p = state.post.inpaint;
    const info = state.postInfo;
    const item = current();
    const analysis = state.analysis?.item?.id === item?.id ? state.analysis : null;
    const found = analysis?.prompt;
    const recorded = found?.source === 'asset_studio' && !!found.positive;
    if (item && analysis && p.for !== item.id) {
      p.for = item.id;
      p.positive = recorded ? found.positive : '';
      p.negative = recorded ? found.negative || '' : '';
    }

    box.append(el('h4', '', t('tools.1_area_to_redraw')));
    const save = btn(t('tools.save_mask'), saveMask);
    save.disabled = !item || !state.editor?.isDirty() || !!ctx.preview;
    box.append(
      el(
        'p',
        'tl-muted',
        item?.inpaint_mask ? t('tools.mask', [t('tools.edited_by_hand')]) : t('tools.no_mask'),
      ),
      save,
    );

    box.append(el('h4', '', t('tools.2_prompt')));
    const prompt = (key, label, hint) => {
      const area = el('textarea');
      area.rows = key === 'positive' ? 5 : 3;
      area.value = p[key];
      area.addEventListener('input', () => (p[key] = area.value));
      return field(
        label,
        withTagComplete(area, ctx.api, (value) => (p[key] = value)),
        hint,
      );
    };
    box.append(
      prompt('positive', t('tools.positive'), t('tools.starts_from_the_image_s_recorded')),
      prompt('negative', t('tools.negative')),
    );

    box.append(el('h4', '', t('tools.3_redraw')));
    const numberOf = (key, attrs) => {
      const control = input('number', p[key], attrs);
      control.addEventListener('input', () => (p[key] = Number(control.value)));
      return control;
    };
    const area = el('select');
    for (const [value, text] of [
      ['crop', t('tools.mask_area_enlarged_recommended')],
      ['full', t('tools.whole_image')],
    ]) {
      const option = el('option', '', text);
      option.value = value;
      area.append(option);
    }
    area.value = p.area;
    area.addEventListener('change', () => {
      p.area = area.value;
      renderTools();
    });
    box.append(field(t('tools.area_to_redraw'), area, t('tools.crops_around_the_mask_redraws_it')));
    if (p.area === 'crop')
      box.append(
        field(
          t('tools.context_padding_px'),
          numberOf('padding', {min: 0, max: 512, step: 16}),
          t('tools.how_much_around_the_mask_the'),
        ),
      );
    box.append(
      field(
        t('tools.denoise'),
        numberOf('denoise', {min: 0.05, max: 1, step: 0.05}),
        t('tools.higher_changes_more_for_hands_or'),
      ),
      field(
        t('tools.steps'),
        numberOf('steps', {min: 0, max: 60}),
        t('tools.0_uses_the_image_s_own'),
      ),
      field(
        t('tools.grow_mask_px'),
        numberOf('grow', {min: -64, max: 64}),
        t('tools.negative_values_shrink_it'),
      ),
      field(t('tools.soft_edge_px'), numberOf('feather', {min: 0, max: 64})),
    );
    const run = btn(t('tools.inpaint_this_image'), startInpaint, 'tl-primary');
    run.disabled =
      !item ||
      !recorded ||
      (!item.inpaint_mask && !state.editor?.isDirty()) ||
      !!ctx.preview ||
      !info?.available ||
      !info.ops?.inpaint;
    box.append(run);
    if (item && analysis && !recorded)
      box.append(el('p', 'tl-error', t('tools.inpaint_needs_an_image_made_with')));
    if (info && !info.available) box.append(el('p', 'tl-error', tr(info.error)));
    box.append(el('small', 'tl-muted', t('tools.redraws_with_the_image_s_own')), whereSaved());
    return box;
  }

  async function saveMask() {
    try {
      await state.editor.save();
      ctx.notify(t('tools.saved_the_mask'));
      renderTools();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  async function applyCensor() {
    try {
      if (state.editor?.isDirty()) await state.editor.save();
      await ctx.api('/api/tools/censor', {id: state.current, ...censorBody()});
      ctx.notify(t('tools.added_the_censored_image_at_the'));
      await loadItems();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }

  function censorForm() {
    const box = el('div');
    const c = state.censor;
    const info = state.postInfo;
    const item = current();
    box.append(el('h4', '', t('tools.1_detect_areas_optional')));
    const labels = el('div', 'tl-chips');
    for (const label of CENSOR_LABELS) {
      const check = el('label', 'tl-check');
      const control = input('checkbox', !c.labels.length || c.labels.includes(label));
      control.addEventListener('change', () => {
        const current = c.labels.length ? c.labels : CENSOR_LABELS;
        c.labels = control.checked
          ? [...new Set([...current, label])]
          : current.filter((l) => l !== label);
      });
      check.append(control, el('span', '', label));
      labels.append(check);
    }
    const confidence = input('number', c.confidence, {min: 0, max: 1, step: 0.05});
    confidence.addEventListener('input', () => (c.confidence = Number(confidence.value)));
    const count = chosenIds().length;
    const detect = btn(t('tools.detect_areas_in_selected', [count]), startDetect);
    detect.disabled = !count || !!ctx.preview || !info?.available || !info.ops?.detect;
    box.append(
      field(t('tools.areas_to_cover'), labels),
      field(t('tools.detection_confidence'), confidence),
      detect,
    );
    if (info && !info.available) box.append(el('p', 'tl-error', tr(info.error)));
    box.append(el('small', 'tl-muted', t('tools.you_can_also_paint_in_the')));

    box.append(el('h4', '', t('tools.2_fix_the_mask')));
    const save = btn(t('tools.save_mask'), saveMask);
    save.disabled = !item || !state.editor?.isDirty() || !!ctx.preview;
    box.append(
      el(
        'p',
        'tl-muted',
        item?.mask
          ? t('tools.mask', [
              item.mask.source === 'detected' ? t('tools.detected') : t('tools.edited_by_hand'),
            ])
          : t('tools.no_mask'),
      ),
      save,
    );

    box.append(el('h4', '', t('tools.3_apply')));
    const treatment = el('select');
    for (const [value, text] of [
      ['mosaic', t('tools.mosaic')],
      ['blur', t('tools.blur')],
      ['color', t('tools.solid_color')],
    ]) {
      const option = el('option', '', text);
      option.value = value;
      treatment.append(option);
    }
    // Older choices map onto the solid fill.
    if (c.treatment === 'white' || c.treatment === 'white_solid') c.treatment = 'color';
    treatment.value = c.treatment;
    treatment.addEventListener('change', () => {
      c.treatment = treatment.value;
      renderTools();
    });
    const numberOf = (key, attrs) => {
      const control = input('number', c[key], attrs);
      control.addEventListener('input', () => (c[key] = Number(control.value)));
      return control;
    };
    box.append(field(t('common.method'), treatment));
    if (c.treatment === 'color') {
      const color = input('color', c.color);
      color.addEventListener('input', () => (c.color = color.value));
      box.append(
        field(t('tools.color'), color),
        field(t('tools.opacity'), numberOf('opacity', {min: 0, max: 100, step: 5})),
      );
    } else {
      box.append(
        field(
          c.treatment === 'mosaic' ? t('tools.block_size_px') : t('tools.blur_radius_px'),
          numberOf('intensity', {min: 1, max: 256}),
        ),
      );
    }
    box.append(
      field(
        t('tools.grow_mask_px'),
        numberOf('grow', {min: -64, max: 64}),
        t('tools.negative_values_shrink_it'),
      ),
      field(t('tools.soft_edge_px'), numberOf('feather', {min: 0, max: 64})),
    );
    const apply = btn(t('tools.apply_to_this_image'), applyCensor, 'tl-primary');
    apply.disabled = !item || (!item.mask && !state.editor?.isDirty()) || !!ctx.preview;
    box.append(
      apply,
      applyChosenButton('censor'),
      el('small', 'tl-muted', t('tools.the_original_stays_the_covered_image')),
    );
    box.append(whereSaved());
    return box;
  }

  // Results of work images go beside the source, so passing one in the gallery adopts it.
  function whereSaved() {
    return el('p', 'tl-muted', t('tools.results_of_work_images_work_character'));
  }

  function postForm() {
    const box = el('div');
    const info = state.postInfo;
    if (!info) {
      box.append(el('p', 'tl-muted', t('tools.checking_post_processing_nodes')));
      return box;
    }
    if (!info.available) {
      box.append(el('p', 'tl-error', tr(info.error)));
      return box;
    }
    const p = state.post;
    const op = el('select');
    // Censor-area detection has its own tab with the mask editor.
    for (const [key, text] of Object.entries(info.ops).filter(
      ([key]) => !['detect', 'alpha', 'inpaint'].includes(key),
    )) {
      const option = el('option', '', tr(text));
      option.value = key;
      op.append(option);
    }
    op.value = p.op;
    op.addEventListener('change', () => {
      p.op = op.value;
      renderTools();
    });
    box.append(field(t('common.jobs'), op));
    const choose = (target, key, choices) => {
      const n = el('select');
      for (const [value, text] of choices) {
        const option = el('option', '', text);
        option.value = value;
        n.append(option);
      }
      n.value = target[key];
      n.addEventListener('change', () => {
        target[key] = n.value;
        renderTools();
      });
      return n;
    };
    const number = (target, key, attrs) => {
      const n = input('number', target[key], attrs);
      n.addEventListener('input', () => (target[key] = Number(n.value)));
      return n;
    };
    if (p.op === 'detail') {
      const stages = el('div', 'tl-chips');
      for (const [key, text] of [
        ['face', t('tools.face')],
        ['eye', t('tools.eyes')],
        ['mouth', t('tools.mouth')],
        ['hand', t('tools.hands')],
      ]) {
        const check = el('label', 'tl-check');
        const c = input('checkbox', p.detail[key]);
        c.addEventListener('change', () => (p.detail[key] = c.checked));
        check.append(c, el('span', '', text));
        stages.append(check);
      }
      box.append(
        field(t('tools.areas_to_redraw'), stages, t('tools.processed_in_order_face_eyes_mouth')),
        field(
          t('tools.denoise'),
          number(p.detail, 'denoise', {min: 0.05, max: 1, step: 0.05}),
          t('tools.higher_changes_more_0_3_0'),
        ),
        field(t('tools.steps'), number(p.detail, 'steps', {min: 1, max: 60})),
        el('small', 'tl-muted', t('tools.only_images_made_with_asset_studio')),
      );
    } else {
      if (!p.upscale.model) p.upscale.model = info.upscale_models[0] || '';
      box.append(
        field(
          t('common.model'),
          choose(
            p.upscale,
            'model',
            info.upscale_models.map((m) => [m, m]),
          ),
        ),
        field(
          t('tools.final_scale'),
          number(p.upscale, 'scale', {min: 0.25, max: 8, step: 0.25}),
          t('tools.resized_at_the_end_if_it'),
        ),
        el('p', 'tl-caution', t('tools.upscaling_removes_transparency_alpha_if_you')),
      );
    }
    const count = chosenIds().length;
    const run = btn(t('tools.process_selected', [count]), startPost, 'tl-primary');
    run.disabled = !count || !!ctx.preview;
    const source =
      info.prefix === 'AssetStudio'
        ? t('tools.asset_studio_copy')
        : t('tools.atelierx_original_before_the_copy_is');
    box.append(run, el('p', 'tl-muted', t('tools.nodes_shares_the_generation_queue', [source])));
    box.append(whereSaved());
    return box;
  }

  function renderTools() {
    const tabs = el('div', 'tl-tabs');
    for (const [key, text] of [
      ['prompt', t('prompt_converter.tab')],
      ['convert', t('tools.webp_conversion')],
      ['tag', t('tools.tagging')],
      ['post', t('tools.post_processing')],
      ['censor', t('tools.censor')],
      ['alpha', t('tools.background_removal')],
      ['inpaint', t('tools.inpaint')],
    ]) {
      const tab = btn(text, () => {
        if (!leaveEditor()) return;
        state.tab = key;
        renderTools();
        renderDetail();
      });
      tab.setAttribute('aria-pressed', String(state.tab === key));
      tabs.append(tab);
    }
    root.classList.toggle('prompt-mode', state.tab === 'prompt');
    toolPanel.replaceChildren(tabs);
    if (state.tab !== 'prompt')
      toolPanel.append(
        el('p', 'tl-muted', t('common.selected', [chosenIds().length])),
        {
          convert: convertForm,
          tag: tagForm,
          post: postForm,
          censor: censorForm,
          alpha: alphaForm,
          inpaint: inpaintForm,
        }[state.tab](),
      );
  }

  // ---- loading -----------------------------------------------------------------------

  async function loadItems() {
    const result = await ctx.api('/api/tools/items');
    state.items = result.items || [];
    const known = new Set(state.items.map((i) => i.id));
    for (const id of [...state.chosen]) if (!known.has(id)) state.chosen.delete(id);
    for (const item of state.items) if (item.tags) state.waitingTags.delete(item.id);
    renderList();
    renderTools();
    renderDetail();
  }
  function poll() {
    clearTimeout(state.timer);
    state.timer = setTimeout(async () => {
      let again = false;
      if (state.task?.status === 'running') {
        try {
          state.task = await ctx.api(`/api/tools/convert/task?id=${state.task.id}`);
        } catch {
          state.task = null;
        }
        again ||= state.task?.status === 'running';
        renderTools();
      }
      if (state.waitingTags.size || state.postPending) {
        await loadItems().catch(() => {});
        again ||= state.waitingTags.size > 0;
      }
      if (state.postPending) {
        try {
          const queue = await ctx.api('/api/jobs');
          state.postPending = queue.jobs.filter(
            (j) => j.kind === 'post' && ['queued', 'running'].includes(j.status),
          ).length;
        } catch {
          state.postPending = 0;
        }
        again ||= state.postPending > 0;
      }
      if (again) poll();
    }, POLL_MS);
  }

  async function enter(params = new URLSearchParams()) {
    const supplied = params instanceof URLSearchParams ? params : new URLSearchParams(params);
    const requestedTab = supplied.get('tab');
    if (requestedTab === 'prompt') state.tab = 'prompt';
    const focusHandoff = (() => {
      try {
        const data = JSON.parse(
          sessionStorage.getItem('asset-studio-tools-gallery-handoff') || 'null',
        );
        sessionStorage.removeItem('asset-studio-tools-gallery-handoff');
        return data;
      } catch {
        return null;
      }
    })();
    if (focusHandoff?.paths?.length && requestedTab !== 'prompt') state.tab = 'convert';
    await loadItems();
    if (focusHandoff?.paths?.length) {
      const path = focusHandoff.paths[0];
      const item = state.items.find(
        (candidate) => candidate.source === 'gallery' && candidate.path === path,
      );
      if (item) await show(item.id);
    }
    if (state.tab === 'prompt') await promptConverter.enter();
    ctx
      .api('/api/tools/tagger')
      .then((info) => {
        state.tagger = info;
        renderTools();
      })
      .catch((error) => {
        state.tagger = {available: false, error: error.message};
        renderTools();
      });
    ctx
      .api('/api/tools/postprocess')
      .then((info) => {
        state.postInfo = info;
        renderTools();
      })
      .catch((error) => {
        state.postInfo = {available: false, error: error.message};
        renderTools();
      });
    if (!state.current && state.items.length) show(state.items[state.items.length - 1].id);
  }
  function leave() {
    clearTimeout(state.timer);
  }

  return {element: root, enter, leave};
}
