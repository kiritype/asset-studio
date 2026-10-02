// Image tools: a workspace of uploaded and gallery images, what each image says about
// how it was made (PNG text, EXIF, Studio record, WD14 tags), and WebP conversion.

import {MODEL_WORDS, splitTags} from '../lib/tags.js';
import {sendToLab} from './lab.js';
import {withTagComplete} from '../core/tag_input.js';
import {createMaskEditor} from '../core/mask_editor.js';
import {t, tr} from '../core/i18n.js';

const POLL_MS = 2000;
const ACCEPT = '.png,.webp,.jpg,.jpeg,.zip';
const SOURCE_LABELS = {
  asset_studio: t('Asset Studio 기록'),
  parameters: 'A1111/Forge parameters',
  comfyui: t('ComfyUI 워크플로'),
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
    el('h1', '', t('이미지 도구')),
    el(
      'p',
      '',
      t('이미지를 올리거나 갤러리에서 보내 메타데이터와 태그를 확인하고 WebP로 변환합니다.'),
    ),
  );
  const listPanel = el('aside', 'tl-list');
  const detail = el('div', 'tl-detail');
  const toolPanel = el('aside', 'tl-tools');
  root.append(header, listPanel, detail, toolPanel);

  const current = () => state.items.find((item) => item.id === state.current);
  const chosenIds = () => state.items.filter((i) => state.chosen.has(i.id)).map((i) => i.id);

  // ---- list --------------------------------------------------------------------------

  const fileInput = input('file', '', {accept: ACCEPT, multiple: ''});
  fileInput.hidden = true;
  fileInput.addEventListener('change', () => upload([...fileInput.files]));
  const uploadStatus = el('p', 'tl-muted');

  async function upload(files) {
    if (!files.length) return;
    if (ctx.preview) return ctx.notify(t('미리보기 서버에서는 올릴 수 없습니다.'), true);
    let added = 0;
    const problems = [];
    for (const [index, file] of files.entries()) {
      uploadStatus.textContent = t('올리는 중 {0}/{1} · {2}', [index + 1, files.length, file.name]);
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
        if (!response.ok || data.ok === false) throw new Error(data.error || t('업로드 실패'));
        added += data.added.length;
        for (const skip of data.skipped || []) problems.push(`${skip.name}: ${skip.error}`);
      } catch (error) {
        problems.push(`${file.name}: ${error.message}`);
      }
    }
    fileInput.value = '';
    uploadStatus.textContent = t('{0}장 추가{1}', [
      added,
      problems.length ? t(' · {0}개 건너뜀', [problems.length]) : '',
    ]);
    uploadStatus.title = problems.join('\n');
    if (problems.length) ctx.notify(problems.slice(0, 3).join(' / '), true);
    await loadItems();
  }

  async function removeChosen() {
    const ids = chosenIds();
    if (!ids.length) return;
    if (
      !window.confirm(
        t('{0}장을 목록에서 뺄까요? 올린 사본은 지워지고 갤러리 원본은 남습니다.', [ids.length]),
      )
    )
      return;
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
    const pick = btn(t('파일·ZIP 올리기'), () => fileInput.click(), 'tl-primary');
    pick.disabled = !!ctx.preview;
    const all = btn(
      state.chosen.size === state.items.length && state.items.length
        ? t('선택 해제')
        : t('전체 선택'),
      () => {
        if (state.chosen.size === state.items.length) state.chosen.clear();
        else for (const item of state.items) state.chosen.add(item.id);
        renderList();
        renderTools();
      },
    );
    const remove = btn(t('목록에서 빼기'), removeChosen);
    remove.disabled = !state.chosen.size || !!ctx.preview;
    const download = btn(t('ZIP 내려받기 ({0}장)', [state.chosen.size]), () => {
      window.location.href = `/api/tools/zip?ids=${chosenIds().join(',')}`;
    });
    download.disabled = !state.chosen.size || state.chosen.size > 500;
    tools.append(pick, all, remove, download, fileInput);
    const grid = el('div', 'tl-grid');
    if (!state.items.length)
      grid.append(
        el(
          'p',
          'tl-drop-hint',
          t(
            '여기에 PNG·WebP·JPEG·ZIP 파일을 끌어다 놓거나, 갤러리에서 이미지를 골라 "이미지 도구로 보내기"를 누르세요.',
          ),
        ),
      );
    for (const item of state.items) {
      const card = el('div', 'tl-card');
      if (item.id === state.current) card.classList.add('current');
      const check = input('checkbox', state.chosen.has(item.id));
      check.setAttribute('aria-label', t('{0} 선택', [item.name]));
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
          item.source === 'gallery' ? t('갤러리') : t('업로드'),
        ),
      );
      if (item.tags) caption.append(el('small', 'tl-badge tl-tagged', t('태그')));
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
    if (!window.confirm(t('저장하지 않은 마스크 수정이 있습니다. 버릴까요?'))) return false;
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
  const visibleTags = (item) =>
    (item.tags?.tags || []).filter((tag) => !excluded().has(norm(tag)));

  async function copyTags(item) {
    try {
      await navigator.clipboard.writeText(visibleTags(item).join(', '));
      ctx.notify(t('태그를 복사했습니다.'));
    } catch (error) {
      ctx.notify(t('복사하지 못했습니다: {0}', [error.message]), true);
    }
  }

  async function saveExcludes(text) {
    try {
      const result = await ctx.api('/api/settings/save', {
        section: 'tags',
        values: {exclude: splitTags(text)},
      });
      state.tagger = {...state.tagger, exclude: result.values.exclude || []};
      ctx.notify(t('제외할 태그를 저장했습니다.'));
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
      group(t('태거가 읽은 태그'), tags, 'tl-seen', '');
      return box;
    }
    group(t('프롬프트와 일치'), both, 'tl-both', t('프롬프트에도 있고 그림에서도 읽힌 태그'));
    group(
      t('그림에서만 읽힘'),
      imageOnly,
      'tl-seen',
      t('프롬프트에는 없지만 태거가 그림에서 읽은 태그'),
    );
    group(
      t('그림에서 안 읽힘'),
      promptOnly,
      'tl-missing',
      t(
        '프롬프트에는 있지만 태거가 읽지 못한 태그. 그려지지 않았거나 태거가 모르는 표현일 수 있습니다.',
      ),
    );
    return box;
  }

  /** Source and result of a post-processing step, side by side or under a slider. */
  function comparison(parent, item) {
    const box = el('div', 'tl-compare');
    const modes = el('div', 'tl-row');
    for (const [key, text] of [
      ['side', t('나란히')],
      ['slider', t('슬라이더')],
    ]) {
      const b = btn(text, () => {
        state.compare = key;
        renderDetail();
      });
      b.setAttribute('aria-pressed', String(state.compare === key));
      modes.append(b);
    }
    modes.append(el('small', 'tl-muted', t('원본: {0}', [parent.name])));
    const before = el('img');
    before.src = `/api/tools/image?id=${parent.id}`;
    before.alt = t('원본');
    const after = el('img');
    after.src = `/api/tools/image?id=${item.id}`;
    after.alt = t('결과');
    if (state.compare === 'slider') {
      const frame = el('div', 'tl-slider');
      after.className = 'tl-over';
      const line = el('div', 'tl-line');
      const range = el('input');
      range.type = 'range';
      range.min = '0';
      range.max = '100';
      range.value = String(state.slider);
      range.setAttribute('aria-label', t('원본과 결과 경계'));
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
          throw new Error(tr(data.error) || t('저장하지 못했습니다: {0}', [response.status]));
        // The saved mask is what the editor already shows; keep it open.
        Object.assign(item, data.item);
        state.editorKey = `${kind}:${item.id}:${item[spec.field]?.updated_at || ''}`;
      },
      onChange: () => renderTools(),
    });
    if (!saved)
      state.editor.setStatus(
        {
          alpha: t('마스크 없음 · 배경을 분리하거나 남길 부분을 브러시로 칠하세요.'),
          censor: t('마스크 없음 · 브러시로 칠하거나 부위를 검출하세요.'),
          inpaint: t('마스크 없음 · 다시 그릴 부분을 브러시로 칠하세요.'),
        }[kind],
      );
    return state.editor.element;
  }

  function renderDetail() {
    const item = current();
    if (!item) {
      detail.replaceChildren(el('p', 'tl-muted', t('왼쪽에서 이미지를 고르세요.')));
      return;
    }
    if (state.tab === 'alpha') {
      detail.replaceChildren(
        maskEditor(item, 'alpha'),
        el(
          'p',
          'tl-muted',
          t(
            '파란 부분이 남고 나머지는 투명해집니다. 브러시로 더하고 지우개로 덜어 낸 뒤 저장하세요.',
          ),
        ),
      );
      return;
    }
    if (state.tab === 'inpaint') {
      detail.replaceChildren(
        maskEditor(item, 'inpaint'),
        el(
          'p',
          'tl-muted',
          t('초록 부분만 다시 그리고 나머지는 원본 그대로 둡니다. 칠한 뒤 저장하세요.'),
        ),
      );
      return;
    }
    if (state.tab === 'censor') {
      detail.replaceChildren(
        maskEditor(item, 'censor'),
        el(
          'p',
          'tl-muted',
          t('빨간 부분이 가려집니다. 브러시로 넓히고 지우개로 덜어 낸 뒤 저장하세요.'),
        ),
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
    if (!a) info.append(el('p', 'tl-muted', t('메타데이터 읽는 중…')));
    else if (a.error) info.append(el('p', 'tl-error', a.error));
    else {
      const found = a.prompt || {};
      const head = el('div', 'tl-row tl-between');
      head.append(
        el(
          'h3',
          '',
          found.source
            ? t('프롬프트 · {0}', [SOURCE_LABELS[found.source]])
            : t('프롬프트 기록 없음'),
        ),
      );
      if (found.positive)
        head.append(
          btn(t('실험실에서 열기'), () =>
            sendToLab(ctx, {
              positive: found.positive,
              negative: found.negative || '',
              // Only Studio records carry settings the lab form understands.
              settings: found.source === 'asset_studio' ? found.settings : undefined,
              source: {label: t('이미지 도구 {0}', [item.name])},
            }),
          ),
        );
      info.append(head);
      if (found.positive) {
        info.append(el('h4', '', t('긍정')), el('pre', '', found.positive));
        if (found.negative) info.append(el('h4', '', t('제외')), el('pre', '', found.negative));
        const settings = Object.entries(found.settings || {}).filter(
          ([, v]) => typeof v !== 'object',
        );
        if (settings.length) {
          const table = el('dl', 'tl-dl');
          for (const [key, value] of settings)
            table.append(el('dt', '', key), el('dd', '', String(value)));
          info.append(el('h4', '', t('설정')), table);
        }
      }
      const models = a.comfy?.models || [];
      if (models.length) {
        info.append(el('h4', '', t('사용한 모델')));
        const list = el('ul', 'tl-models');
        for (const model of models)
          list.append(el('li', '', `${model.node}: ${Object.values(model).slice(1).join(', ')}`));
        info.append(list);
      }
      const facts = el('p', 'tl-muted');
      facts.textContent = [
        a.has_alpha ? t('투명도 있음') : t('투명도 없음'),
        a.has_workflow ? t('ComfyUI 워크플로 포함') : '',
        a.text_keys.length
          ? t('텍스트 항목: {0}', [a.text_keys.join(', ')])
          : t('텍스트 항목 없음'),
      ]
        .filter(Boolean)
        .join(' · ');
      info.append(facts);
      const exif = Object.entries(a.exif || {});
      if (exif.length) {
        const more = el('details');
        more.append(el('summary', '', t('EXIF {0}개', [exif.length])));
        const table = el('dl', 'tl-dl');
        for (const [key, value] of exif) table.append(el('dt', '', key), el('dd', '', value));
        more.append(table);
        info.append(more);
      }
      const tags = item.tags?.tags && visibleTags(item);
      const tagHead = el('div', 'tl-row tl-between');
      tagHead.append(el('h3', '', t('WD14 태그')));
      if (tags) {
        const actions = el('div', 'tl-row');
        actions.append(
          btn(t('태그 복사'), () => copyTags(item)),
          btn(t('태그로 실험실 열기'), () =>
            sendToLab(ctx, {
              positive: tags.join(', '),
              negative: '',
              source: {label: t('이미지 도구 {0}', [item.name])},
            }),
          ),
        );
        tagHead.append(actions);
      }
      info.append(tagHead);
      if (tags) {
        const hidden = item.tags.tags.length - tags.length;
        if (hidden) info.append(el('p', 'tl-muted', t('제외할 태그 {0}개를 숨겼습니다.', [hidden])));
        info.append(
          el(
            'p',
            'tl-muted',
            t('{0} · 일반 {1} / 캐릭터 {2}', [
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
              ? t('태그 분석 대기 중…')
              : t('아직 분석하지 않았습니다. 오른쪽 "태그 분석"에서 실행하세요.'),
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
      ctx.notify(t('{0}장을 태그 분석 대기열에 넣었습니다.', [ids.length]));
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
    const suffix = input('text', c.suffix, {placeholder: t('예: _web')});
    suffix.addEventListener('input', () => (c.suffix = suffix.value));
    const check = (control, text, hint) => {
      const n = el('label', 'tl-check');
      n.append(control, el('span', '', text));
      if (hint) n.title = hint;
      return n;
    };
    const count = chosenIds().length;
    const run = btn(t('선택한 {0}장 WebP로 변환', [count]), startConvert, 'tl-primary');
    run.disabled = !count || !!ctx.preview || state.task?.status === 'running';
    box.append(
      field(t('품질'), qualityRow, t('기본 95. 무손실을 켜면 품질 값은 쓰지 않습니다.')),
      check(lossless, t('무손실')),
      check(
        keep,
        t('메타데이터 유지'),
        t('ComfyUI 프롬프트와 워크플로를 WebP EXIF에 남깁니다. 배포용이면 끄세요.'),
      ),
      el('small', 'tl-muted', t('끄면(기본) 프롬프트·워크플로·EXIF를 모두 지웁니다.')),
      field(t('긴 변 크기(px)'), longSide, t('0이면 원래 크기')),
      field(t('파일 이름 뒤에 붙일 말'), suffix, t('결과는 outputs/_tools/<날짜>/에 저장됩니다.')),
      run,
    );
    const task = state.task;
    if (task) {
      const result = el('div', 'tl-task');
      result.append(
        el(
          'p',
          '',
          `${task.status === 'running' ? t('변환 중') : t('완료')} ${task.done}/${task.total}`,
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
        result.append(el('p', 'tl-error', `${error.name}: ${error.error}`));
      if (task.status !== 'running' && task.results.length) {
        const zip = el('a', 'tl-link', t('ZIP 내려받기 ({0}장)', [task.results.length]));
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
      box.append(el('p', 'tl-muted', t('태거 정보를 읽는 중…')));
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
    const run = btn(t('선택한 {0}장 태그 분석', [count]), startTags, 'tl-primary');
    run.disabled = !count || !!ctx.preview;
    box.append(
      field(
        t('모델'),
        model,
        t('처음 쓰는 모델은 ComfyUI가 Hugging Face에서 내려받습니다 (수백 MB~1GB).'),
      ),
      field(t('일반 태그 임계값'), threshold),
      field(t('캐릭터 태그 임계값'), character),
      run,
      el(
        'p',
        'tl-muted',
        t(
          '생성 대기열을 함께 쓰므로 생성 중인 이미지가 끝난 뒤 실행됩니다. 결과는 가운데 패널에서 프롬프트와 비교합니다.',
        ),
      ),
    );

    box.append(el('h4', '', t('제외할 태그')));
    const exclude = el('textarea');
    exclude.rows = 3;
    exclude.value = (info.exclude || []).join(', ');
    exclude.placeholder = 'simple background, white background';
    const saveExclude = btn(t('제외 목록 저장'), () => saveExcludes(exclude.value));
    saveExclude.disabled = !!ctx.preview;
    box.append(
      exclude,
      saveExclude,
      el('small', 'tl-muted', t('쉼표로 구분합니다. 화면, 복사, 내보내기에서 모두 빠집니다.')),
    );

    box.append(el('h4', '', t('태그 내보내기')));
    const tagged = state.items.filter((i) => state.chosen.has(i.id) && i.tags);
    const exportAs = (format) => {
      const ids = tagged.map((i) => i.id).join(',');
      window.location.href = `/api/tools/tags/export?format=${format}&ids=${ids}`;
    };
    const asText = btn(t('TXT ({0}장)', [tagged.length]), () => exportAs('txt'));
    const asJson = btn(t('JSON ({0}장)', [tagged.length]), () => exportAs('json'));
    asText.disabled = asJson.disabled = !tagged.length || tagged.length > 500;
    const row = el('div', 'tl-row');
    row.append(asText, asJson);
    box.append(
      row,
      el(
        'small',
        'tl-muted',
        t(
          'TXT는 이미지마다 캡션 파일 하나를 이미지 ZIP과 같은 이름으로 묶어 LoRA 학습용으로 함께 풀 수 있습니다.',
        ),
      ),
    );
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
      ctx.notify(
        t('{0}장을 후처리 대기열에 넣었습니다. 결과는 목록 끝에 추가됩니다.', [result.jobs.length]),
      );
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
    if (
      masked &&
      !window.confirm(t('마스크가 이미 있는 {0}장은 검출 결과로 바뀝니다. 계속할까요?', [masked]))
    )
      return;
    const options = {confidence: state.censor.confidence};
    if (state.censor.labels.length) options.labels = state.censor.labels;
    try {
      const result = await ctx.api('/api/jobs/postprocess', {ids, op: 'detect', options});
      state.postPending += result.jobs.length;
      ctx.notify(t('{0}장의 가림 부위 검출을 대기열에 넣었습니다.', [result.jobs.length]));
      ctx.onQueueChanged?.();
      poll();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  async function startSplit() {
    const ids = chosenIds();
    const masked = state.items.filter((i) => ids.includes(i.id) && i.alpha_mask).length;
    if (
      masked &&
      !window.confirm(t('마스크가 이미 있는 {0}장은 검출 결과로 바뀝니다. 계속할까요?', [masked]))
    )
      return;
    const a = state.post.alpha;
    try {
      const result = await ctx.api('/api/jobs/postprocess', {
        ids,
        op: 'alpha',
        options: {method: a.method, confidence: Number(a.confidence)},
      });
      state.postPending += result.jobs.length;
      ctx.notify(t('{0}장의 배경 분리를 대기열에 넣었습니다.', [result.jobs.length]));
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
      ctx.notify(t('배경을 투명하게 만든 이미지를 목록 끝에 추가했습니다.'));
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
    ctx.notify(t('{0}장에 적용했습니다. 마스크가 없는 {1}장은 건너뛰었습니다.', [done, skipped]));
    await loadItems();
  }
  function applyChosenButton(kind) {
    const count = chosenWithMask(kind).length;
    const button = btn(t('마스크가 있는 선택 이미지 {0}장에 적용', [count]), () =>
      applyChosen(kind),
    );
    button.disabled = !count || !!ctx.preview;
    return button;
  }

  function alphaForm() {
    const box = el('div');
    const a = state.post.alpha;
    const info = state.postInfo;
    const item = current();
    box.append(el('h4', '', t('1. 배경 분리 (선택)')));
    const method = el('select');
    for (const [value, text] of [
      ['isnet', t('isnet-anime (애니 일러스트)')],
      ['person', t('인물 분할 (YOLO person)')],
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
    box.append(field(t('방식'), method));
    if (a.method === 'person') {
      const confidence = input('number', a.confidence, {min: 0, max: 1, step: 0.05});
      confidence.addEventListener('input', () => (a.confidence = Number(confidence.value)));
      box.append(field(t('검출 신뢰도'), confidence));
    }
    const count = chosenIds().length;
    const split = btn(t('선택한 {0}장 배경 분리', [count]), startSplit);
    split.disabled = !count || !!ctx.preview || !info?.available || !info.ops?.alpha;
    box.append(split);
    if (info && !info.available) box.append(el('p', 'tl-error', tr(info.error)));

    box.append(el('h4', '', t('2. 마스크 고치기')));
    const save = btn(t('마스크 저장'), saveMask);
    save.disabled = !item || !state.editor?.isDirty() || !!ctx.preview;
    box.append(
      el(
        'p',
        'tl-muted',
        item?.alpha_mask
          ? t('마스크: {0}', [
              item.alpha_mask.source === 'detected' ? t('검출됨') : t('직접 수정함'),
            ])
          : t('마스크 없음'),
      ),
      save,
    );

    box.append(el('h4', '', t('3. 적용')));
    const numberOf = (key, attrs) => {
      const control = input('number', a[key], attrs);
      control.addEventListener('input', () => (a[key] = Number(control.value)));
      return control;
    };
    const apply = btn(t('현재 이미지에 적용'), applyAlpha, 'tl-primary');
    apply.disabled = !item || (!item.alpha_mask && !state.editor?.isDirty()) || !!ctx.preview;
    box.append(
      field(
        t('마스크 확장(px)'),
        numberOf('grow', {min: -64, max: 64}),
        t('음수면 안쪽으로 줄입니다.'),
      ),
      field(
        t('경계 부드럽게(px)'),
        numberOf('feather', {min: 0, max: 64}),
        t('1536px 이미지라면 0~1px부터 보세요.'),
      ),
      apply,
      applyChosenButton('alpha'),
      el(
        'small',
        'tl-muted',
        t('원본 색은 그대로 두고 배경만 투명하게 만든 PNG를 새로 저장합니다.'),
      ),
    );
    box.append(whereSaved());
    return box;
  }

  async function startInpaint() {
    try {
      if (state.editor?.isDirty()) await state.editor.save();
      const {for: _, ...options} = state.post.inpaint;
      const result = await ctx.api('/api/jobs/postprocess', {
        ids: [state.current],
        op: 'inpaint',
        options,
      });
      state.postPending += result.jobs.length;
      ctx.notify(t('인페인트를 대기열에 넣었습니다. 결과는 목록 끝에 추가됩니다.'));
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

    box.append(el('h4', '', t('1. 다시 그릴 부분')));
    const save = btn(t('마스크 저장'), saveMask);
    save.disabled = !item || !state.editor?.isDirty() || !!ctx.preview;
    box.append(
      el(
        'p',
        'tl-muted',
        item?.inpaint_mask ? t('마스크: {0}', [t('직접 수정함')]) : t('마스크 없음'),
      ),
      save,
    );

    box.append(el('h4', '', t('2. 프롬프트')));
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
      prompt('positive', t('긍정'), t('이미지 기록의 프롬프트로 시작합니다. 고칠 부분을 설명하는 태그를 더해 보세요.')),
      prompt('negative', t('제외')),
    );

    box.append(el('h4', '', t('3. 다시 그리기')));
    const numberOf = (key, attrs) => {
      const control = input('number', p[key], attrs);
      control.addEventListener('input', () => (p[key] = Number(control.value)));
      return control;
    };
    const area = el('select');
    for (const [value, text] of [
      ['crop', t('마스크 주변만 크게 (권장)')],
      ['full', t('이미지 전체')],
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
    box.append(
      field(
        t('다시 그릴 영역'),
        area,
        t('마스크 주변만 잘라 생성 크기로 키워 그린 뒤 다시 붙입니다. 손가락처럼 작은 부분이 더 또렷해집니다.'),
      ),
    );
    if (p.area === 'crop')
      box.append(
        field(
          t('주변 여백(px)'),
          numberOf('padding', {min: 0, max: 512, step: 16}),
          t('마스크 바깥으로 함께 보여 줄 범위. 넓을수록 주변과 잘 어울립니다.'),
        ),
      );
    box.append(
      field(
        t('디노이즈'),
        numberOf('denoise', {min: 0.05, max: 1, step: 0.05}),
        t('높을수록 많이 바뀝니다. 손·소품 고치기는 0.5~0.7부터 보세요.'),
      ),
      field(t('스텝'), numberOf('steps', {min: 0, max: 60}), t('0이면 원본과 같은 스텝')),
      field(t('마스크 확장(px)'), numberOf('grow', {min: -64, max: 64}), t('음수면 안쪽으로 줄입니다.')),
      field(t('경계 부드럽게(px)'), numberOf('feather', {min: 0, max: 64})),
    );
    const run = btn(t('현재 이미지 인페인트'), startInpaint, 'tl-primary');
    run.disabled =
      !item ||
      !recorded ||
      (!item.inpaint_mask && !state.editor?.isDirty()) ||
      !!ctx.preview ||
      !info?.available ||
      !info.ops?.inpaint;
    box.append(run);
    if (item && analysis && !recorded)
      box.append(
        el('p', 'tl-error', t('Asset Studio 제작 기록이 없는 이미지는 인페인트를 쓸 수 없습니다.')),
      );
    if (info && !info.available) box.append(el('p', 'tl-error', tr(info.error)));
    box.append(
      el(
        'small',
        'tl-muted',
        t('그 이미지의 모델·LoRA로 다시 그립니다. 칠하지 않은 부분은 원본 픽셀 그대로 남습니다.'),
      ),
      whereSaved(),
    );
    return box;
  }

  async function saveMask() {
    try {
      await state.editor.save();
      ctx.notify(t('마스크를 저장했습니다.'));
      renderTools();
    } catch (error) {
      ctx.notify(error.message, true);
    }
  }
  async function applyCensor() {
    try {
      if (state.editor?.isDirty()) await state.editor.save();
      await ctx.api('/api/tools/censor', {id: state.current, ...censorBody()});
      ctx.notify(t('가림 처리한 이미지를 목록 끝에 추가했습니다.'));
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
    box.append(el('h4', '', t('1. 부위 검출 (선택)')));
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
    const detect = btn(t('선택한 {0}장 부위 검출', [count]), startDetect);
    detect.disabled = !count || !!ctx.preview || !info?.available || !info.ops?.detect;
    box.append(field(t('가릴 부위'), labels), field(t('검출 신뢰도'), confidence), detect);
    if (info && !info.available) box.append(el('p', 'tl-error', tr(info.error)));
    box.append(
      el(
        'small',
        'tl-muted',
        t('검출 없이 가운데에서 직접 칠해도 됩니다. 자동 검출은 놓칠 수 있으니 꼭 확인하세요.'),
      ),
    );

    box.append(el('h4', '', t('2. 마스크 고치기')));
    const save = btn(t('마스크 저장'), saveMask);
    save.disabled = !item || !state.editor?.isDirty() || !!ctx.preview;
    box.append(
      el(
        'p',
        'tl-muted',
        item?.mask
          ? t('마스크: {0}', [item.mask.source === 'detected' ? t('검출됨') : t('직접 수정함')])
          : t('마스크 없음'),
      ),
      save,
    );

    box.append(el('h4', '', t('3. 적용')));
    const treatment = el('select');
    for (const [value, text] of [
      ['mosaic', t('모자이크')],
      ['blur', t('흐림')],
      ['color', t('단색')],
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
    box.append(field(t('방식'), treatment));
    if (c.treatment === 'color') {
      const color = input('color', c.color);
      color.addEventListener('input', () => (c.color = color.value));
      box.append(
        field(t('색'), color),
        field(t('불투명도(%)'), numberOf('opacity', {min: 0, max: 100, step: 5})),
      );
    } else {
      box.append(
        field(
          c.treatment === 'mosaic' ? t('블록 크기(px)') : t('흐림 반경(px)'),
          numberOf('intensity', {min: 1, max: 256}),
        ),
      );
    }
    box.append(
      field(
        t('마스크 확장(px)'),
        numberOf('grow', {min: -64, max: 64}),
        t('음수면 안쪽으로 줄입니다.'),
      ),
      field(t('경계 부드럽게(px)'), numberOf('feather', {min: 0, max: 64})),
    );
    const apply = btn(t('현재 이미지에 가림 적용'), applyCensor, 'tl-primary');
    apply.disabled = !item || (!item.mask && !state.editor?.isDirty()) || !!ctx.preview;
    box.append(
      apply,
      applyChosenButton('censor'),
      el('small', 'tl-muted', t('원본은 그대로 두고 가린 이미지를 새 PNG로 저장합니다.')),
    );
    box.append(whereSaved());
    return box;
  }

  // Results of work images go beside the source, so passing one in the gallery adopts it.
  function whereSaved() {
    return el(
      'p',
      'tl-muted',
      t(
        '작업 이미지(작품/캐릭터/의상 폴더)의 결과는 원본 옆에 새 후보로 저장되고, 갤러리에서 통과시키면 채택됩니다. 그 밖의 이미지는 outputs/_tools/에 저장됩니다.',
      ),
    );
  }

  function postForm() {
    const box = el('div');
    const info = state.postInfo;
    if (!info) {
      box.append(el('p', 'tl-muted', t('후처리 노드를 확인하는 중…')));
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
    box.append(field(t('작업'), op));
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
        ['face', t('얼굴')],
        ['eye', t('눈')],
        ['mouth', t('입')],
        ['hand', t('손')],
      ]) {
        const check = el('label', 'tl-check');
        const c = input('checkbox', p.detail[key]);
        c.addEventListener('change', () => (p.detail[key] = c.checked));
        check.append(c, el('span', '', text));
        stages.append(check);
      }
      box.append(
        field(t('다시 그릴 부위'), stages, t('얼굴 → 눈 → 입 → 손 순서로 처리합니다.')),
        field(
          t('디노이즈'),
          number(p.detail, 'denoise', {min: 0.05, max: 1, step: 0.05}),
          t('높을수록 많이 바뀝니다. 0.3~0.5 권장'),
        ),
        field(t('스텝'), number(p.detail, 'steps', {min: 1, max: 60})),
        el(
          'small',
          'tl-muted',
          t(
            'Asset Studio로 만든 이미지만 됩니다. 그 이미지의 모델·LoRA·프롬프트로 다시 그립니다. 얼굴 인상이 바뀔 수 있으니 결과를 확인하세요.',
          ),
        ),
      );
    } else {
      if (!p.upscale.model) p.upscale.model = info.upscale_models[0] || '';
      box.append(
        field(
          t('모델'),
          choose(
            p.upscale,
            'model',
            info.upscale_models.map((m) => [m, m]),
          ),
        ),
        field(
          t('최종 배율'),
          number(p.upscale, 'scale', {min: 0.25, max: 8, step: 0.25}),
          t('모델 배율과 달라도 마지막에 맞춥니다.'),
        ),
        el(
          'p',
          'tl-caution',
          t(
            '업스케일하면 투명도(알파)가 사라집니다. 투명한 배경이 필요하면 업스케일한 뒤에 배경 투명화를 하세요.',
          ),
        ),
      );
    }
    const count = chosenIds().length;
    const run = btn(t('선택한 {0}장 처리', [count]), startPost, 'tl-primary');
    run.disabled = !count || !!ctx.preview;
    const source =
      info.prefix === 'AssetStudio' ? t('Asset Studio 사본') : t('AtelierX 원본 (사본 연결 전)');
    box.append(run, el('p', 'tl-muted', t('노드: {0} · 생성 대기열을 함께 씁니다.', [source])));
    box.append(whereSaved());
    return box;
  }

  function renderTools() {
    const tabs = el('div', 'tl-tabs');
    for (const [key, text] of [
      ['convert', t('WebP 변환')],
      ['tag', t('태그 분석')],
      ['post', t('후처리')],
      ['censor', t('가림 처리')],
      ['alpha', t('배경 투명화')],
      ['inpaint', t('인페인트')],
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
    toolPanel.replaceChildren(
      tabs,
      el('p', 'tl-muted', t('선택 {0}장', [chosenIds().length])),
      {convert: convertForm, tag: tagForm, post: postForm, censor: censorForm, alpha: alphaForm, inpaint: inpaintForm}[
        state.tab
      ](),
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

  async function enter() {
    await loadItems();
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
