'use strict';

// The gallery owns only its root and its dialog. It can be mounted by any shell.
import {locale, t, tr} from '../core/i18n.js';
const node = (tag, className = '', value) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined && value !== null) element.textContent = String(value);
  return element;
};
const option = (value, label) => {
  const item = node('option', '', label);
  item.value = value;
  return item;
};
const safeUrl = (value) => {
  if (!value) return '';
  try {
    const url = new URL(String(value), location.href);
    return url.origin === location.origin &&
      (url.pathname.startsWith('/outputs/') || url.pathname.startsWith('/api/gallery/'))
      ? url.href
      : '';
  } catch {
    return '';
  }
};
const asList = (value) => (Array.isArray(value) ? value : []);
const display = (value) =>
  value === undefined || value === null || value === ''
    ? '—'
    : Array.isArray(value)
      ? value.join(', ')
      : typeof value === 'object'
        ? JSON.stringify(value, null, 2)
        : String(value);
const dateLabel = (value) => {
  if (!value) return t('날짜 정보 없음');
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(locale);
};

export function createGallery(ctx) {
  const root = node('section', '', '');
  root.id = 'app-gallery';
  const state = {
    active: false,
    tree: null,
    results: [],
    total: 0,
    pages: 1,
    revision: '',
    snapshot: '',
    work: '',
    // Folder of images that do not belong to a work (single generations, imports).
    folder: '',
    character: '',
    outfit: '',
    expression: '',
    category: '',
    family: '',
    sort: 'newest',
    latest: false,
    page: 1,
    pageSize: 48,
    selected: -1,
    pending: false,
    requestId: 0,
    poll: null,
    newAvailable: false,
    previousFocus: null,
    fullSize: false,
    drag: null,
    metadataRequestId: 0,
    chosen: new Map(),
    human: '',
    auto: '',
    selectedOnly: false,
    dialogItems: null,
    actionBusy: false,
    selectBusy: false,
    rounds: [],
    // VLM review is optional; when it is off the gallery shows human verdicts only.
    vlmEnabled: false,
  };

  const heading = node('div', 'g-heading');
  const titleBox = node('div');
  titleBox.append(
    node('div', 'g-eyebrow', 'GALLERY / ARCHIVE'),
    node('h1', '', t('갤러리')),
    node('p', '', t('생성한 이미지를 작품별로 탐색하고 제작 기록을 확인하세요.')),
  );
  const refresh = node('button', 'g-button', t('새로고침'));
  refresh.type = 'button';
  heading.append(titleBox, refresh);

  const layout = node('div', 'g-layout');
  const sidebar = node('aside', 'g-sidebar');
  sidebar.append(node('h2', '', t('작품 라이브러리')));
  const treeBox = node('div', 'g-tree');
  sidebar.append(treeBox);
  const main = node('div', 'g-main');
  const toolbar = node('div', 'g-toolbar');
  const filters = node('div', 'g-filters');
  const makeSelect = (label, entries, change) => {
    const wrapper = node('label', 'g-field');
    wrapper.append(node('span', '', label));
    const select = node('select');
    entries.forEach(([value, text]) => select.append(option(value, text)));
    select.addEventListener('change', change);
    wrapper.append(select);
    filters.append(wrapper);
    return select;
  };
  const characterSelect = makeSelect(t('캐릭터'), [['', t('전체 캐릭터')]], () =>
    changeFilter('character', characterSelect.value),
  );
  const outfitSelect = makeSelect(t('의상'), [['', t('전체 의상')]], () =>
    changeFilter('outfit', outfitSelect.value),
  );
  const expressionSelect = makeSelect(t('감정·동작'), [['', t('전체 감정·동작')]], () =>
    changeFilter('expression', expressionSelect.value),
  );
  const categorySelect = makeSelect(
    t('구분'),
    [
      ['', t('전체')],
      ['sfw', t('일반 · SFW')],
      ['nsfw', t('성인 · NSFW')],
    ],
    () => changeFilter('category', categorySelect.value),
  );
  const familySelect = makeSelect(
    t('모델'),
    [
      ['', t('전체 모델')],
      ['anima', 'Anima'],
      ['sdxl', 'SDXL·IL'],
      ['unknown', t('기록 없음')],
    ],
    () => changeFilter('family', familySelect.value),
  );
  const sortSelect = makeSelect(
    t('정렬'),
    [
      ['newest', t('최신순')],
      ['oldest', t('오래된순')],
      ['code', t('코드순')],
    ],
    () => changeFilter('sort', sortSelect.value),
  );
  const pageSizeSelect = makeSelect(
    t('페이지당'),
    [
      ['48', t('48장')],
      ['96', t('96장')],
    ],
    () => changeFilter('pageSize', Number(pageSizeSelect.value)),
  );
  const latestLabel = node('label', 'g-latest');
  const latestCheck = node('input');
  latestCheck.type = 'checkbox';
  latestLabel.append(latestCheck, node('span', '', t('각 항목의 최신 이미지')));
  latestCheck.addEventListener('change', () => changeFilter('latest', latestCheck.checked));
  filters.append(latestLabel);
  const humanSelect = makeSelect(
    t('내 판정'),
    [
      ['', t('전체')],
      ['unreviewed', t('미검수')],
      ['pass', t('통과')],
      ['fail', t('실패')],
    ],
    () => changeFilter('human', humanSelect.value),
  );
  const autoSelect = makeSelect(
    t('VLM 참고'),
    [
      ['', t('전체')],
      ['pending', t('대기')],
      ['pass', t('통과')],
      ['fail', t('실패')],
      ['uncertain', t('불확실')],
      ['error', t('오류')],
    ],
    () => changeFilter('auto', autoSelect.value),
  );
  const selectedLabel = node('label', 'g-latest');
  const selectedCheck = node('input');
  selectedCheck.type = 'checkbox';
  selectedLabel.append(selectedCheck, node('span', '', t('확정 채택만')));
  selectedCheck.addEventListener('change', () =>
    changeFilter('selectedOnly', selectedCheck.checked),
  );
  filters.append(selectedLabel);
  toolbar.append(filters);
  const statusLine = node('div', 'g-status');
  const count = node('span', '', t('불러오는 중…'));
  const updateBanner = node('button', 'g-update', t('새 이미지가 있습니다 · 갱신'));
  updateBanner.type = 'button';
  updateBanner.hidden = true;
  updateBanner.addEventListener('click', () => loadResults(true));
  statusLine.append(count, updateBanner);
  const actionBar = node('section', 'g-actions');
  actionBar.setAttribute('aria-label', t('이미지 선택과 검수'));
  const selectionCount = node('strong', 'g-selection-count', t('선택 0장'));
  const selectionMessage = node('span', 'g-inline-message');
  selectionMessage.setAttribute('role', 'status');
  const actionButton = (label, fn) => {
    const button = node('button', 'g-button', label);
    button.type = 'button';
    button.onclick = fn;
    return button;
  };
  const selectPage = actionButton(t('이 페이지 선택'), () => addSelection(state.results));
  const selectFiltered = actionButton(t('필터 결과 전체 선택'), selectAllFiltered);
  const clearSelection = actionButton(t('선택 해제'), () => {
    state.chosen.clear();
    renderResults();
  });
  const reviewPass = actionButton(t('선택 통과'), () => reviewChosen('pass'));
  const reviewFail = actionButton(t('선택 실패'), () => reviewChosen('fail'));
  const reviewReset = actionButton(t('선택 미검수'), () => reviewChosen('unreviewed'));
  const regenerate = actionButton(t('새 시드로 재생성'), () =>
    regenerateItems([...state.chosen.values()]),
  );
  const toTools = actionButton(t('이미지 도구로 보내기'), async () => {
    try {
      const paths = [...state.chosen.values()].map((item) => item.path);
      const result = await ctx.api('/api/tools/gallery', {paths});
      ctx.notify(t('{0}장을 이미지 도구에 추가했습니다.', [result.added.length]));
      ctx.navigate('/tools');
    } catch (error) {
      setMessage(error.message || String(error), true);
    }
  });
  const exportButton = actionButton(t('현재 범위 ZIP 내보내기'), () => exportCurrent());
  const exportPartial = actionButton(t('누락 제외하고 부분 내보내기'), () => exportCurrent(true));
  exportPartial.hidden = true;
  const exportHint = node(
    'p',
    'g-muted',
    t(
      '사람이 통과로 확정한 이미지 중 작품·캐릭터·의상·구분 필터에 맞는 파일을 내보냅니다. 누락 항목이 있으면 부분 내보내기를 선택할 수 있습니다.',
    ),
  );
  const regenHint = node(
    'p',
    'g-muted',
    t(
      '원본 제작 기록을 사용해 시드만 바꾸어 새 이미지를 생성합니다. 원본 이미지에 나중에 적용한 편집은 재현되지 않습니다.',
    ),
  );
  const roundPanel = node('details', 'g-rounds');
  const roundSummary = node('summary');
  const roundList = node('div', 'g-round-list');
  const roundDismiss = actionButton(t('끝난 회차 정리'), dismissRounds);
  roundDismiss.title = t(
    '진행 중이 아닌 회차를 목록에서 치웁니다. 이미지와 판정 기록은 그대로 남습니다.',
  );
  roundPanel.append(roundSummary, roundList, roundDismiss);
  roundPanel.hidden = true;
  actionBar.append(
    selectionCount,
    selectPage,
    selectFiltered,
    clearSelection,
    reviewPass,
    reviewFail,
    reviewReset,
    regenerate,
    toTools,
    exportButton,
    exportPartial,
    selectionMessage,
    exportHint,
    regenHint,
  );
  const grid = node('div', 'g-grid');
  const pagination = node('nav', 'g-pagination');
  pagination.setAttribute('aria-label', t('갤러리 페이지'));
  main.append(toolbar, statusLine, roundPanel, actionBar, grid, pagination);
  layout.append(sidebar, main);
  root.append(heading, layout);

  const dialog = node('dialog', 'g-lightbox');
  dialog.setAttribute('aria-label', t('이미지 상세 정보'));
  const lightbox = node('div', 'g-lightbox-layout');
  const viewer = node('div', 'g-viewer');
  const viewerBar = node('div', 'g-viewer-bar');
  const prev = node('button', 'g-icon', '←');
  prev.type = 'button';
  prev.setAttribute('aria-label', t('이전 이미지'));
  const next = node('button', 'g-icon', '→');
  next.type = 'button';
  next.setAttribute('aria-label', t('다음 이미지'));
  const zoom = node('button', 'g-button', t('100% 보기'));
  zoom.type = 'button';
  const close = node('button', 'g-icon', '×');
  close.type = 'button';
  close.setAttribute('aria-label', t('닫기'));
  viewerBar.append(prev, next, zoom, close);
  const imageScroll = node('div', 'g-image-scroll');
  const fullImage = node('img');
  fullImage.alt = t('생성 이미지');
  fullImage.addEventListener('error', () => {
    viewerCaption.textContent = t('이미지를 열 수 없습니다.');
  });
  imageScroll.append(fullImage);
  const viewerCaption = node('div', 'g-viewer-caption');
  viewer.append(viewerBar, imageScroll, viewerCaption);
  const details = node('aside', 'g-details');
  const detailsHead = node('div', 'g-details-head');
  detailsHead.append(node('h2', '', t('제작 기록')));
  const detailReview = node('div', 'g-detail-review');
  const detailBadges = node('div', 'g-badges');
  const detailPass = actionButton(t('✓ 통과 (P)'), () => reviewItems([currentItem()], 'pass'));
  const detailFail = actionButton(t('✕ 실패 (F)'), () => reviewItems([currentItem()], 'fail'));
  const detailReset = actionButton(t('미검수 (U)'), () =>
    reviewItems([currentItem()], 'unreviewed'),
  );
  const detailRegen = actionButton(t('새 시드로 재생성'), () => regenerateItems([currentItem()]));
  const detailButtons = {pass: detailPass, fail: detailFail, unreviewed: detailReset};
  // The lab starts from this image's prompt and settings and keeps it as the reference.
  const detailLab = actionButton(t('실험실에서 열기'), () => {
    const item = currentItem();
    if (!item) return;
    dialog.close();
    ctx.navigate(`/lab?image=${encodeURIComponent(item.relative_path)}`);
  });
  detailReview.append(detailBadges, detailPass, detailFail, detailReset, detailRegen, detailLab);
  const detailsBody = node('div', 'g-details-body');
  details.append(detailsHead, detailReview, detailsBody);
  lightbox.append(viewer, details);
  dialog.append(lightbox);
  root.append(dialog);

  function syncUrl() {
    if (!state.active) return;
    const query = new URLSearchParams();
    for (const key of ['work', 'character', 'outfit', 'expression', 'category', 'folder', 'family'])
      if (state[key]) query.set(key, state[key]);
    if (state.sort !== 'newest') query.set('sort', state.sort);
    if (state.latest) query.set('latest', 'true');
    if (state.human) query.set('human_status', state.human);
    if (state.auto) query.set('auto_status', state.auto);
    if (state.selectedOnly) query.set('selected_only', 'true');
    if (state.page !== 1) query.set('page', String(state.page));
    if (state.pageSize !== 48) query.set('page_size', String(state.pageSize));
    const suffix = query.toString();
    history.replaceState(history.state, '', `/gallery${suffix ? `?${suffix}` : ''}`);
    try {
      localStorage.setItem(storageKey(), JSON.stringify({query: suffix, snapshot: state.snapshot}));
    } catch {
      /* Storage is optional. */
    }
  }
  const storageKey = () =>
    `asset-studio:gallery:${location.origin}:${ctx.preview ? 'preview' : 'live'}`;
  function savedLocation() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey()) || 'null');
      return saved && typeof saved.query === 'string' ? saved : null;
    } catch {
      return null;
    }
  }
  function sameSelection(left, right) {
    return [
      'work',
      'folder',
      'character',
      'outfit',
      'expression',
      'category',
      'family',
      'sort',
      'latest',
      'human_status',
      'auto_status',
      'selected_only',
      'page',
      'page_size',
    ].every((key) => (left.get(key) || '') === (right.get(key) || ''));
  }
  function paramsFromState() {
    const query = new URLSearchParams();
    for (const key of ['work', 'character', 'outfit', 'expression', 'category', 'folder', 'family'])
      if (state[key]) query.set(key, state[key]);
    query.set('sort', state.sort);
    query.set('latest', String(state.latest));
    if (state.human) query.set('human_status', state.human);
    if (state.auto) query.set('auto_status', state.auto);
    query.set('selected_only', state.selectedOnly ? '1' : '0');
    query.set('page', String(state.page));
    query.set('page_size', String(state.pageSize));
    if (state.snapshot) query.set('snapshot', state.snapshot);
    return query;
  }
  function notice(error) {
    ctx.notify?.(error instanceof Error ? error.message : String(error), true);
  }
  const identity = (item) =>
    (item?.relative_path || item?.path) && item?.sha256
      ? {path: item.relative_path || item.path, sha256: item.sha256}
      : null;
  const identityKey = (item) => `${item.relative_path || item.path}\u0000${item.sha256}`;
  const humanLabel = {unreviewed: t('미검수'), pass: t('통과'), fail: t('실패')};
  const autoLabel = {
    pending: t('대기'),
    pass: t('통과'),
    fail: t('실패'),
    uncertain: t('불확실'),
    error: t('오류'),
  };
  const autoMark = {pass: '✓', fail: '✕', uncertain: '?', error: '!'};
  const humanOf = (item) => item.human_status || 'unreviewed';
  const autoOf = (item) => item.auto_status || 'pending';
  /** The person's verdict as one chip; nothing for an image not judged yet. */
  function humanChip(item) {
    if (item.selected) {
      const chip = node('span', 'g-chip pass selected', t('★ 채택'));
      chip.title = t('통과 판정을 받은, 이 감정의 현재 채택본입니다.');
      return chip;
    }
    if (humanOf(item) === 'pass') {
      const chip = node('span', 'g-chip pass', t('✓ 통과'));
      chip.title = t('통과 판정을 받았지만, 같은 감정의 다른 이미지가 채택본입니다.');
      return chip;
    }
    if (humanOf(item) === 'fail') return node('span', 'g-chip fail', t('✕ 실패'));
    return null;
  }
  /** The VLM verdict as a small reference chip; hidden when review is off or not done. */
  function autoChip(item) {
    if (!state.vlmEnabled || autoOf(item) === 'pending') return null;
    const chip = node('span', `g-chip auto ${autoOf(item)}`, `VLM ${autoMark[autoOf(item)]}`);
    const disagrees =
      (humanOf(item) === 'pass' && autoOf(item) === 'fail') ||
      (humanOf(item) === 'fail' && autoOf(item) === 'pass');
    chip.classList.toggle('disagree', disagrees);
    chip.title = [
      t('VLM 참고 판정: {0}', [autoLabel[autoOf(item)]]),
      disagrees ? t('내 판정과 다릅니다.') : '',
      item.auto_reason || '',
    ]
      .filter(Boolean)
      .join('\n');
    return chip;
  }
  function currentItem() {
    return state.dialogItems?.[state.selected] || null;
  }
  function setMessage(message, error = false) {
    selectionMessage.textContent = message;
    selectionMessage.classList.toggle('error', error);
  }
  function addSelection(items) {
    let added = 0;
    for (const item of items) {
      const id = identity(item);
      if (!id) continue;
      const key = identityKey(item);
      if (!state.chosen.has(key)) {
        state.chosen.set(key, id);
        added++;
      }
    }
    setMessage(t('{0}장 추가', [added]));
    renderResults();
  }
  async function selectAllFiltered() {
    if (state.selectBusy || state.pending) return;
    state.selectBusy = true;
    selectFiltered.disabled = true;
    const query = paramsFromState();
    query.set('page_size', '96');
    query.delete('snapshot');
    let selected = 0;
    try {
      let snapshot = '';
      for (let page = 1; ; page++) {
        query.set('page', String(page));
        if (snapshot) query.set('snapshot', snapshot);
        const payload = await ctx.api(`/api/gallery?${query}`);
        if (!snapshot) snapshot = payload.snapshot || '';
        for (const item of asList(payload.results)) {
          const id = identity(item);
          if (!id) continue;
          const key = identityKey(item);
          if (!state.chosen.has(key)) {
            state.chosen.set(key, id);
            selected++;
          }
        }
        setMessage(t('필터 결과 선택 중 · {0}장', [selected]));
        if (page >= Number(payload.pages || 1)) break;
      }
      setMessage(t('필터 결과 {0}장 추가', [selected]));
    } catch (error) {
      setMessage(t('선택 중단: {0}', [error.message || error]), true);
    } finally {
      state.selectBusy = false;
      selectFiltered.disabled = false;
      renderResults();
    }
  }
  async function reviewItems(items, verdict) {
    const ids = items.map(identity).filter(Boolean);
    if (!ids.length || state.actionBusy) return;
    state.actionBusy = true;
    updateActions();
    try {
      const response = await ctx.api('/api/gallery/review', {items: ids, verdict});
      const errors = asList(response.errors);
      setMessage(
        t('{0}장 {1} 처리{2}', [
          ids.length - errors.length,
          humanLabel[verdict],
          errors.length
            ? t(' · {0}장 실패: {1}', [
                errors.length,
                errors[0].error || errors[0].message || t('상태가 바뀌었습니다'),
              ])
            : '',
        ]),
        Boolean(errors.length),
      );
      // The open image and its navigation list remain fixed until the user moves or closes it.
      if (currentItem()) {
        const updated = asList(response.results).find(
          (result) => identityKey(result) === identityKey(currentItem()),
        );
        if (updated) {
          Object.assign(currentItem(), updated);
          renderDetailReview(currentItem());
        }
      }
      await loadResults(true);
    } catch (error) {
      setMessage(error.message || String(error), true);
    } finally {
      state.actionBusy = false;
      updateActions();
    }
  }
  function reviewChosen(verdict) {
    return reviewItems([...state.chosen.values()], verdict);
  }
  async function regenerateItems(items) {
    const ids = items.map(identity).filter(Boolean);
    if (!ids.length || state.actionBusy) return;
    state.actionBusy = true;
    updateActions();
    try {
      const response = await ctx.api('/api/gallery/regenerate', {items: ids});
      const count = response.count ?? asList(response.rounds).length;
      setMessage(
        t('{0}장을 새 시드로 대기열에 등록했습니다.{1}{2}', [
          count,
          response.reviewing ? t(' 생성 후 VLM이 검증합니다.') : '',
          response.warning ? t(' 생성 후 따로 적용한 편집은 재현되지 않습니다.') : '',
        ]),
      );
      ctx.onQueueChanged?.();
      await loadRounds();
    } catch (error) {
      setMessage(error.message || String(error), true);
    } finally {
      state.actionBusy = false;
      updateActions();
    }
  }
  function updateActions() {
    const has = state.chosen.size > 0;
    selectionCount.textContent = t('선택 {0}장', [state.chosen.size.toLocaleString(locale)]);
    for (const button of [reviewPass, reviewFail, reviewReset, regenerate, toTools])
      button.disabled = !has || state.actionBusy || ctx.preview;
    for (const button of [detailPass, detailFail, detailReset, detailRegen])
      button.disabled = !currentItem() || state.actionBusy || ctx.preview;
    clearSelection.disabled = !has || state.actionBusy;
  }
  const ROUND_STATUS = {
    waiting_generation: t('생성 대기'),
    pending_review: t('VLM 검증 대기'),
    reviewing: t('VLM 검증 중'),
    switching: t('GPU 전환 중'),
    queueing: t('재생성 준비 중'),
    failed_review: t('VLM 실패 · 확인 필요'),
    needs_attention: t('확인 필요'),
    limit_reached: t('자동 재생성 한도 도달'),
  };
  const ROUND_ACTIVE = [
    'waiting_generation',
    'pending_review',
    'reviewing',
    'switching',
    'queueing',
  ];
  const ROUND_LIST_LIMIT = 20;
  /** Show the VLM parts of the gallery only while VLM review is switched on. */
  function applyVlmVisibility() {
    autoSelect.parentElement.hidden = !state.vlmEnabled;
    if (!state.vlmEnabled) roundPanel.hidden = true;
  }
  async function loadRounds() {
    try {
      const payload = await ctx.api('/api/review/rounds');
      if (!state.active) return;
      const changed = state.vlmEnabled !== Boolean(payload.enabled);
      state.vlmEnabled = Boolean(payload.enabled);
      applyVlmVisibility();
      if (changed) {
        if (!state.vlmEnabled && state.auto) changeFilter('auto', '');
        else renderResults();
      }
      if (!state.vlmEnabled) return;
      // Rounds waiting for a person or already settled need no place here: the
      // images themselves show that state.
      state.rounds = asList(payload.rounds).filter(
        (round) =>
          ROUND_STATUS[round.status] &&
          (!state.work || round.combo?.[0] === state.work) &&
          (!state.character || round.combo?.[1] === state.character) &&
          (!state.outfit || round.combo?.[2] === state.outfit),
      );
      const isActive = (round) => ROUND_ACTIVE.includes(round.status) && !round.stale;
      const active = state.rounds.filter(isActive);
      const attention = state.rounds.length - active.length;
      roundPanel.hidden = !state.rounds.length;
      roundSummary.textContent = t('VLM 검증 · 진행 {0}건 · 확인 필요 {1}건', [
        active.length,
        attention,
      ]);
      roundList.replaceChildren();
      for (const round of [...state.rounds].reverse().slice(0, ROUND_LIST_LIMIT)) {
        const n = Number(round.regenerations || 0);
        const limit = Number(round.max_auto_regenerations ?? 10);
        roundList.append(
          node(
            'div',
            `g-round-item${isActive(round) ? '' : ' attention'}`,
            t('{0} · {1} · 자동 재생성 {2}/{3}{4}', [
              asList(round.combo).join('/'),
              round.stale ? t('멈춤 · 대기열에 작업이 없음') : ROUND_STATUS[round.status],
              n,
              limit,
              round.error ? ` · ${tr(round.error)}` : '',
            ]),
          ),
        );
      }
      if (state.rounds.length > ROUND_LIST_LIMIT)
        roundList.append(
          node('div', 'g-round-item', t('… 외 {0}건', [state.rounds.length - ROUND_LIST_LIMIT])),
        );
      roundDismiss.disabled = ctx.preview || state.actionBusy;
    } catch {
      /* Round polling must not spam notices. */
    }
  }
  async function dismissRounds() {
    if (
      !confirm(
        t(
          '진행 중이 아닌 VLM 검증 회차를 목록에서 치울까요?\n이미지와 판정 기록은 그대로 남습니다.',
        ),
      )
    )
      return;
    try {
      const result = await ctx.api('/api/review/rounds/dismiss', {});
      setMessage(t('VLM 검증 회차 {0}건을 정리했습니다.', [result.dismissed]));
      await loadRounds();
    } catch (error) {
      setMessage(error.message || String(error), true);
    }
  }
  async function exportCurrent(allowPartial = false) {
    if (state.actionBusy) return;
    if (!state.category) {
      setMessage(t('내보낼 구분을 SFW 또는 NSFW로 선택하세요.'), true);
      categorySelect.focus();
      return;
    }
    state.actionBusy = true;
    exportButton.disabled = true;
    try {
      const filters = Object.fromEntries(
        ['work', 'character', 'outfit', 'category']
          .map((key) => [key, state[key]])
          .filter(([, value]) => value),
      );
      const response = await fetch('/api/gallery/export', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filters, allow_partial: allowPartial}),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        if (response.status === 409 && !allowPartial) {
          const missing = data.missing || data.summary?.missing || [];
          const summary =
            Array.isArray(missing) && missing.length
              ? t('{0}개 항목 누락: {1}{2}', [
                  missing.length,
                  missing.slice(0, 5).join(', '),
                  missing.length > 5 ? '…' : '',
                ])
              : data.error || t('필수 항목 누락');
          setMessage(t('내보내기 불완전 · {0}', [summary]), true);
          exportPartial.hidden = false;
          return;
        }
        throw new Error(data.error || data.message || t('내보내기 실패 ({0})', [response.status]));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = node('a');
      link.href = url;
      link.download = 'asset-studio-accepted.zip';
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      const exported = response.headers.get('X-Export-Count');
      const complete = response.headers.get('X-Export-Complete');
      const missingCount = response.headers.get('X-Export-Missing-Count');
      setMessage(
        t('ZIP 내보내기 완료 · {0}{1}{2}', [
          exported ? t('{0}장 · ', [exported]) : '',
          complete === 'false' || allowPartial ? t('부분') : t('전체'),
          missingCount && Number(missingCount) ? t(' · 누락 {0}개', [missingCount]) : '',
        ]),
      );
      exportPartial.hidden = true;
    } catch (error) {
      setMessage(error.message || String(error), true);
    } finally {
      state.actionBusy = false;
      exportButton.disabled = false;
      updateActions();
    }
  }
  function workNode() {
    return asList(state.tree?.works).find((item) => String(item.id) === state.work);
  }
  function characterNodes() {
    return state.work
      ? asList(workNode()?.characters)
      : asList(state.tree?.works).flatMap((item) => asList(item.characters));
  }
  function outfitNodes() {
    return characterNodes()
      .filter((item) => !state.character || String(item.id) === state.character)
      .flatMap((item) => asList(item.outfits));
  }
  function updateSelect(select, items, allLabel, value) {
    select.replaceChildren(option('', allLabel));
    const grouped = new Map();
    for (const item of items) {
      const id = String(item.id ?? '');
      if (!id) continue;
      const previous = grouped.get(id);
      grouped.set(id, {
        id,
        name: previous?.name || item.name || id,
        count: (previous?.count || 0) + Number(item.count || 0),
      });
    }
    for (const item of grouped.values())
      select.append(
        option(
          item.id,
          `${item.id}${item.name && item.name !== item.id ? ` · ${item.name}` : ''} (${item.count})`,
        ),
      );
    select.value = value;
    if (select.value !== value) select.value = '';
  }
  function renderTree() {
    treeBox.replaceChildren();
    const all = node(
      'button',
      `g-tree-item${state.work ? '' : ' active'}`,
      t('전체 작품 ({0})', [
        asList(state.tree?.works).reduce((n, w) => n + Number(w.count || 0), 0),
      ]),
    );
    all.type = 'button';
    all.title = all.textContent;
    all.onclick = () => {
      state.folder = '';
      changeFilter('work', '');
    };
    all.classList.toggle('active', !state.work && !state.folder);
    treeBox.append(all);
    for (const work of asList(state.tree?.works)) {
      const workButton = node(
        'button',
        `g-tree-item${state.work === String(work.id) ? ' active' : ''}`,
        `${work.name || work.id} (${work.count ?? 0})`,
      );
      workButton.type = 'button';
      workButton.title = workButton.textContent;
      workButton.onclick = () => changeFilter('work', String(work.id));
      treeBox.append(workButton);
      if (state.work !== String(work.id)) continue;
      for (const character of asList(work.characters)) {
        const chButton = node(
          'button',
          `g-tree-item g-indent-1${state.character === String(character.id) ? ' active' : ''}`,
          `${character.name || character.id} (${character.count ?? 0})`,
        );
        chButton.type = 'button';
        chButton.title = chButton.textContent;
        chButton.onclick = () => changeFilter('character', String(character.id));
        treeBox.append(chButton);
        if (state.character !== String(character.id)) continue;
        for (const outfit of asList(character.outfits)) {
          const outButton = node(
            'button',
            `g-tree-item g-indent-2${state.outfit === String(outfit.id) ? ' active' : ''}`,
            `${outfit.name || outfit.id} (${outfit.count ?? 0})`,
          );
          outButton.type = 'button';
          outButton.title = outButton.textContent;
          outButton.onclick = () => changeFilter('outfit', String(outfit.id));
          treeBox.append(outButton);
        }
      }
    }
    const folders = asList(state.tree?.folders);
    if (folders.length) treeBox.append(node('h3', 'g-tree-heading', t('기타 폴더')));
    for (const folder of folders) {
      const depth = folder.path.split('/').length - 1;
      const name = folder.path.split('/').at(-1);
      const button = node(
        'button',
        `g-tree-item g-indent-${Math.min(depth, 2)}${state.folder === folder.path ? ' active' : ''}`,
        `${name} (${folder.count})`,
      );
      button.type = 'button';
      button.title = folder.path;
      button.onclick = () => changeFilter('folder', folder.path);
      treeBox.append(button);
    }
    updateSelect(characterSelect, characterNodes(), t('전체 캐릭터'), state.character);
    updateSelect(outfitSelect, outfitNodes(), t('전체 의상'), state.outfit);
    // Expression names are derived from currently loaded images; the API tree may also provide them.
    const expressions = asList(state.tree?.expressions).length
      ? state.tree.expressions
      : state.results.map((item) => ({
          id: item.expression_id,
          name: item.expression_name || item.expression_id,
        }));
    updateSelect(expressionSelect, expressions, t('전체 감정·동작'), state.expression);
    categorySelect.value = state.category;
    familySelect.value = state.family;
    sortSelect.value = state.sort;
    pageSizeSelect.value = String(state.pageSize);
    latestCheck.checked = state.latest;
    humanSelect.value = state.human;
    autoSelect.value = state.auto;
    selectedCheck.checked = state.selectedOnly;
  }
  function changeFilter(key, value) {
    if (state[key] === value) return;
    state[key] = value;
    if (key === 'selectedOnly' && value) state.latest = false;
    if (key === 'latest' && value) state.selectedOnly = false;
    if (key === 'work') {
      state.character = '';
      state.outfit = '';
      state.folder = '';
    }
    // A folder and a work are two separate places; choosing one clears the other.
    if (key === 'folder') {
      state.work = '';
      state.character = '';
      state.outfit = '';
    }
    if (key === 'character') state.outfit = '';
    state.page = 1;
    state.snapshot = '';
    exportPartial.hidden = true;
    renderTree();
    syncUrl();
    loadResults(false);
  }
  async function fetchTree(initial = false) {
    try {
      const nextTree = await ctx.api('/api/gallery/tree');
      if (!state.active) return;
      const changed =
        state.tree &&
        (String(nextTree.revision) !== String(state.tree.revision) ||
          JSON.stringify(nextTree.works) !== JSON.stringify(state.tree.works));
      state.tree = nextTree;
      if (!initial && changed) {
        state.newAvailable = true;
        updateBanner.hidden = false;
      }
      renderTree();
    } catch (error) {
      if (initial) notice(error);
    }
  }
  async function checkNewerThanSnapshot() {
    try {
      const query = paramsFromState();
      query.delete('snapshot');
      query.set('page', '1');
      const latest = await ctx.api(`/api/gallery?${query}`);
      if (state.active && Number(latest.total) > state.total) {
        state.newAvailable = true;
        updateBanner.hidden = false;
      }
    } catch {
      /* The banner is a hint; the list itself already loaded. */
    }
  }
  async function loadResults(fresh = false) {
    const previousSnapshot = state.snapshot;
    const previousUpdate = state.newAvailable;
    if (fresh) {
      state.snapshot = '';
      state.newAvailable = false;
      updateBanner.hidden = true;
    }
    const requestId = ++state.requestId;
    state.pending = true;
    count.textContent = t('이미지 불러오는 중…');
    try {
      const payload = await ctx.api(`/api/gallery?${paramsFromState()}`);
      if (!state.active || requestId !== state.requestId) return false;
      state.results = asList(payload.results);
      state.total = Number(payload.total ?? state.results.length);
      state.pages = Math.max(1, Number(payload.pages ?? 1));
      state.page = Number(payload.page ?? state.page);
      state.revision = payload.revision ?? state.revision;
      state.snapshot = payload.snapshot ?? state.snapshot;
      state.pending = false;
      renderResults();
      renderTree();
      syncUrl();
      return true;
    } catch (error) {
      if (requestId !== state.requestId) return false;
      if (fresh) {
        state.snapshot = previousSnapshot;
        state.newAvailable = previousUpdate;
        updateBanner.hidden = !previousUpdate;
      }
      state.pending = false;
      count.textContent = t('이미지를 불러오지 못했습니다.');
      notice(error);
      return false;
    }
  }
  function renderResults() {
    count.textContent = t('{0}장 · {1} / {2}페이지', [
      state.total.toLocaleString(locale),
      state.page,
      state.pages,
    ]);
    selectPage.textContent = t('이 페이지 선택 ({0}장)', [state.results.length]);
    selectFiltered.textContent = t('필터 결과 전체 선택 ({0}장)', [
      state.total.toLocaleString(locale),
    ]);
    updateActions();
    grid.replaceChildren();
    if (!state.results.length)
      grid.append(node('p', 'g-empty', t('조건에 맞는 이미지가 없습니다.')));
    state.results.forEach((item, index) => {
      const card = node('article', 'g-card');
      const checkLabel = node('label', 'g-card-select');
      const check = node('input');
      check.type = 'checkbox';
      check.checked = state.chosen.has(identityKey(item));
      check.disabled = !identity(item);
      check.setAttribute('aria-label', t('{0} 선택', [item.filename || t('이미지')]));
      check.addEventListener('change', () => {
        const id = identity(item);
        if (!id) return;
        if (check.checked) state.chosen.set(identityKey(item), id);
        else state.chosen.delete(identityKey(item));
        card.classList.toggle('chosen', check.checked);
        updateActions();
      });
      checkLabel.append(check, node('span', '', t('선택')));
      card.classList.toggle('chosen', check.checked);
      const open = node('button', 'g-card-open');
      open.type = 'button';
      open.setAttribute('aria-label', t('{0} 상세 보기', [item.filename || t('이미지')]));
      const frame = node('span', 'g-card-image');
      const image = node('img');
      image.loading = 'lazy';
      image.decoding = 'async';
      image.alt = t('{0} 미리보기', [item.filename || t('이미지')]);
      const thumbnail = safeUrl(item.thumbnail_url || item.image_url);
      if (thumbnail) {
        image.src = thumbnail;
        frame.append(image);
      } else {
        frame.classList.add('failed');
        frame.append(node('span', '', t('미리보기 없음')));
      }
      image.onerror = () => {
        frame.classList.add('failed');
        image.remove();
        frame.append(node('span', '', t('미리보기 없음')));
      };
      const caption = node('span', 'g-card-caption');
      const work = asList(state.tree?.works).find(
        (entry) => String(entry.id) === String(item.work_id),
      );
      const character = asList(work?.characters).find(
        (entry) => String(entry.id) === String(item.character_id),
      );
      const outfit = asList(character?.outfits).find(
        (entry) => String(entry.id) === String(item.outfit_id),
      );
      const namedCode = (id, entry) =>
        `${id || '?'}${entry?.name && entry.name !== id ? ` · ${entry.name}` : ''}`;
      const pathLabel = item.work_id
        ? [
            namedCode(item.work_id, work),
            namedCode(item.character_id, character),
            namedCode(item.outfit_id, outfit),
          ].join(' / ')
        : item.folder || 'outputs';
      const path = node('span', 'g-card-path', pathLabel);
      path.title = pathLabel;
      const expressionName =
        item.expression_name ||
        asList(state.tree?.expressions).find(
          (entry) => String(entry.id) === String(item.expression_id),
        )?.name;
      const expression = `${item.expression_id || '?'}${expressionName && expressionName !== item.expression_id ? ` · ${expressionName}` : ''}`;
      caption.append(
        node('strong', '', expression),
        path,
        node('small', '', `${item.filename || ''} · ${dateLabel(item.created_at)}`),
      );
      card.classList.add(`human-${humanOf(item)}`);
      const chips = node('span', 'g-card-chips');
      for (const chip of [humanChip(item), autoChip(item)]) if (chip) chips.append(chip);
      if (chips.childElementCount) frame.append(chips);
      open.append(frame, caption);
      card.append(checkLabel, open);
      open.onclick = () => openItem(index);
      grid.append(card);
    });
    pagination.replaceChildren();
    const pageButton = (label, page, disabled, current = false) => {
      const element = node('button', `g-page${current ? ' active' : ''}`, label);
      element.type = 'button';
      element.disabled = disabled;
      element.onclick = () => goPage(page);
      return element;
    };
    pagination.append(pageButton(t('이전'), state.page - 1, state.page <= 1));
    const start = Math.max(1, Math.min(state.page - 2, state.pages - 4));
    for (let page = start; page <= Math.min(state.pages, start + 4); page++)
      pagination.append(pageButton(String(page), page, false, page === state.page));
    pagination.append(pageButton(t('다음'), state.page + 1, state.page >= state.pages));
  }
  function renderDetailReview(item) {
    const row = (title, ...content) => {
      const line = node('div', 'g-verdict-row');
      line.append(node('span', 'g-verdict-title', title), ...content.filter(Boolean));
      return line;
    };
    detailBadges.replaceChildren(
      row(t('내 판정'), humanChip(item) || node('span', 'g-chip', t('미검수'))),
    );
    // A stored VLM verdict stays visible here even after review is switched off.
    if (autoOf(item) !== 'pending') {
      const chip = node(
        'span',
        `g-chip auto ${autoOf(item)}`,
        `${autoMark[autoOf(item)]} ${autoLabel[autoOf(item)]}`,
      );
      detailBadges.append(row(t('VLM 참고'), chip));
      if (item.auto_reason) detailBadges.append(node('p', 'g-muted', item.auto_reason));
    } else if (state.vlmEnabled) {
      detailBadges.append(row(t('VLM 참고'), node('span', 'g-chip', t('아직 검증 전'))));
    }
    for (const [verdict, button] of Object.entries(detailButtons))
      button.setAttribute('aria-pressed', String(humanOf(item) === verdict));
    updateActions();
  }
  async function goPage(page) {
    if (state.pending || page < 1 || page > state.pages || page === state.page) return;
    const previous = state.page;
    state.page = page;
    if (await loadResults(false)) main.scrollIntoView({block: 'start', behavior: 'smooth'});
    else if (state.page === page) {
      state.page = previous;
      syncUrl();
      renderResults();
    }
  }

  const table = (entries) => {
    const element = node('dl', 'g-meta-table');
    for (const [key, value] of entries) {
      if (value === undefined || value === null || value === '') continue;
      element.append(node('dt', '', key), node('dd', '', display(value)));
    }
    return element;
  };
  function textSection(title, value, open = false) {
    const section = node('details', 'g-text-section');
    section.open = open;
    section.append(node('summary', '', title), node('pre', '', display(value)));
    return section;
  }
  function copyButton(label, value) {
    const button = node('button', 'g-copy', t('{0} 복사', [label]));
    button.type = 'button';
    button.onclick = async () => {
      try {
        await navigator.clipboard.writeText(String(value));
        ctx.notify?.(t('{0}를 복사했습니다.', [label]));
      } catch (error) {
        ctx.notify?.(t('{0}를 복사할 수 없습니다.', [label]), true);
      }
    };
    return button;
  }
  function downloadJson(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = node('a');
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function renderMetadata(item, itemIndex) {
    const metadataRequestId = ++state.metadataRequestId;
    detailsBody.replaceChildren(node('p', '', t('제작 기록을 불러오는 중…')));
    if (item.metadata_available === false) {
      detailsBody.replaceChildren(
        node('p', 'g-muted', t('이 이미지에는 JSON 제작 기록이 없습니다.')),
      );
      return;
    }
    try {
      const metadata = await ctx.api(
        `/api/gallery/metadata?${new URLSearchParams({path: item.relative_path})}`,
      );
      if (
        !dialog.open ||
        state.selected !== itemIndex ||
        metadataRequestId !== state.metadataRequestId
      )
        return;
      const settings = metadata.settings || {};
      const parts = metadata.parts || {};
      detailsBody.replaceChildren();
      detailsBody.append(
        node('h3', '', t('이미지')),
        table([
          [t('파일'), item.filename],
          [t('생성'), metadata.created_at || item.created_at],
          [t('작품'), metadata.work_id || item.work_id],
          [t('캐릭터'), metadata.character_id || item.character_id],
          [t('의상 세트'), metadata.outfit_id || item.outfit_id],
          [t('의상 부위'), asList(metadata.outfit_slots || metadata.outfit_parts).join(', ')],
          [t('감정·동작'), metadata.expression_name || item.expression_id],
          [t('구분'), metadata.category || item.category],
          [t('크기'), asList(metadata.image_size).join(' × ')],
          [t('배치 ID'), metadata.batch_id],
        ]),
      );
      if (metadata.generation_preset)
        detailsBody.append(
          node('h3', '', t('생성 프리셋')),
          table([
            [t('이름'), metadata.generation_preset.name],
            ['ID', metadata.generation_preset.id],
            [
              t('설정 수정'),
              metadata.generation_preset.settings_modified === true
                ? t('사용자 수정')
                : t('원본 사용'),
            ],
          ]),
        );
      detailsBody.append(
        node('h3', '', t('생성 설정')),
        table([
          [t('모델'), settings.model],
          [t('텍스트 인코더'), settings.text_encoder],
          ['VAE', settings.vae],
          [t('CLIP 유형'), settings.clip_type],
          [t('단계'), settings.steps],
          ['CFG', settings.cfg],
          [t('샘플러'), settings.sampler],
          [t('스케줄러'), settings.scheduler],
          [t('시드'), metadata.seed ?? settings.seed],
          [t('가로'), settings.width],
          [t('세로'), settings.height],
        ]),
      );
      if (
        (metadata.seed !== undefined && metadata.seed !== null) ||
        (settings.seed !== undefined && settings.seed !== null)
      )
        detailsBody.append(copyButton(t('시드'), metadata.seed ?? settings.seed));
      if (asList(settings.loras).length) {
        detailsBody.append(node('h3', '', 'LoRA'));
        for (const lora of settings.loras)
          detailsBody.append(
            table([
              [t('이름'), lora.name],
              [t('모델 강도'), lora.strength_model],
              [t('CLIP 강도'), lora.strength_clip],
            ]),
          );
      }
      detailsBody.append(node('h3', '', t('프롬프트 구성')));
      for (const [key, label] of [
        ['work', t('작품 공통')],
        ['common', t('공통 긍정')],
        ['quality', t('품질')],
        ['artist', t('화풍')],
        ['composition', t('구도')],
        ['appearance', t('외형')],
        ['expression', t('감정·동작')],
        ['outfit', t('의상')],
        ['negative', t('제외 요소')],
      ]) {
        if (parts[key]) detailsBody.append(textSection(label, parts[key]));
      }
      detailsBody.append(
        textSection(t('긍정 프롬프트 원문'), metadata.positive, true),
        textSection(t('부정 프롬프트 원문'), metadata.negative),
      );
      if (metadata.positive !== undefined && metadata.positive !== null)
        detailsBody.append(copyButton(t('긍정 프롬프트'), metadata.positive));
      if (metadata.negative !== undefined && metadata.negative !== null)
        detailsBody.append(copyButton(t('부정 프롬프트'), metadata.negative));
      if (metadata.workflow) {
        const workflowButton = node('button', 'g-button', t('워크플로 JSON 다운로드'));
        workflowButton.type = 'button';
        workflowButton.onclick = () =>
          downloadJson(
            metadata.workflow,
            `${(item.filename || 'workflow').replace(/\.[^.]+$/, '')}-workflow.json`,
          );
        detailsBody.append(workflowButton);
      }
      const metadataButton = node('button', 'g-button', t('제작 기록 JSON 다운로드'));
      metadataButton.type = 'button';
      metadataButton.onclick = () =>
        downloadJson(metadata, `${(item.filename || 'image').replace(/\.[^.]+$/, '')}.json`);
      detailsBody.append(metadataButton);
    } catch (error) {
      if (
        !dialog.open ||
        state.selected !== itemIndex ||
        metadataRequestId !== state.metadataRequestId
      )
        return;
      detailsBody.replaceChildren(node('p', 'g-muted', t('제작 기록을 열 수 없습니다.')));
      const retry = node('button', 'g-button', t('다시 시도'));
      retry.type = 'button';
      retry.onclick = () => renderMetadata(item, itemIndex);
      detailsBody.append(retry);
    }
  }
  function showItem(index) {
    const item = state.dialogItems?.[index];
    if (!item) return;
    state.selected = index;
    state.fullSize = false;
    imageScroll.classList.remove('full-size');
    zoom.textContent = t('100% 보기');
    imageScroll.scrollTop = 0;
    imageScroll.scrollLeft = 0;
    const imageUrl = safeUrl(item.image_url);
    if (imageUrl) fullImage.src = imageUrl;
    else fullImage.removeAttribute('src');
    fullImage.alt = t('{0} 원본', [item.filename || t('이미지')]);
    viewerCaption.textContent = imageUrl
      ? t('{0} · {1}페이지 {2}/{3}', [
          item.filename || t('이미지'),
          state.page,
          index + 1,
          state.dialogItems.length,
        ])
      : t('이미지 주소를 열 수 없습니다.');
    prev.disabled = state.page === 1 && index === 0;
    next.disabled = state.page === state.pages && index === state.dialogItems.length - 1;
    renderDetailReview(item);
    renderMetadata(item, index);
  }
  function openItem(index) {
    state.previousFocus = document.activeElement;
    state.dialogItems = state.results.map((item) => ({...item}));
    dialog.showModal();
    showItem(index);
    close.focus();
  }
  async function moveItem(direction) {
    if (!dialog.open || state.pending) return;
    const target = state.selected + direction;
    if (target >= 0 && target < state.dialogItems.length) {
      showItem(target);
      return;
    }
    const page = state.page + direction;
    if (page < 1 || page > state.pages) return;
    const previous = state.page;
    state.page = page;
    if (!(await loadResults(false))) {
      if (state.page === page) {
        state.page = previous;
        syncUrl();
        renderResults();
      }
      return;
    }
    if (!dialog.open || !state.results.length) return;
    state.dialogItems = state.results.map((item) => ({...item}));
    showItem(direction > 0 ? 0 : state.dialogItems.length - 1);
  }
  function closeDialog() {
    if (dialog.open) dialog.close();
  }
  dialog.addEventListener('close', () => {
    state.metadataRequestId++;
    state.selected = -1;
    state.dialogItems = null;
    fullImage.removeAttribute('src');
    state.previousFocus?.focus?.();
  });
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) closeDialog();
  });
  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      moveItem(-1);
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      moveItem(1);
    }
    // Review without leaving the keyboard: P pass, F fail, U back to unreviewed.
    const verdict = {p: 'pass', f: 'fail', u: 'unreviewed'}[event.key.toLowerCase()];
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName);
    if (verdict && !typing && !event.ctrlKey && !event.metaKey && !event.altKey && !ctx.preview) {
      event.preventDefault();
      reviewItems([currentItem()], verdict);
    }
  });
  close.onclick = closeDialog;
  prev.onclick = () => moveItem(-1);
  next.onclick = () => moveItem(1);
  zoom.onclick = () => {
    state.fullSize = !state.fullSize;
    imageScroll.classList.toggle('full-size', state.fullSize);
    zoom.textContent = state.fullSize ? t('화면에 맞춤') : t('100% 보기');
  };
  imageScroll.addEventListener('pointerdown', (event) => {
    if (!state.fullSize) return;
    state.drag = {
      x: event.clientX,
      y: event.clientY,
      left: imageScroll.scrollLeft,
      top: imageScroll.scrollTop,
    };
    imageScroll.setPointerCapture(event.pointerId);
  });
  imageScroll.addEventListener('pointermove', (event) => {
    if (!state.drag) return;
    imageScroll.scrollLeft = state.drag.left + state.drag.x - event.clientX;
    imageScroll.scrollTop = state.drag.top + state.drag.y - event.clientY;
  });
  imageScroll.addEventListener('pointerup', () => {
    state.drag = null;
  });
  imageScroll.addEventListener('pointercancel', () => {
    state.drag = null;
  });
  refresh.onclick = () => {
    fetchTree(true);
    loadResults(true);
  };

  async function enter(params = new URLSearchParams()) {
    state.active = true;
    applyVlmVisibility();
    const saved = savedLocation();
    const supplied = params instanceof URLSearchParams ? params : new URLSearchParams(params);
    params = supplied.toString() ? supplied : new URLSearchParams(saved?.query || '');
    state.work = params.get('work') || '';
    state.folder = params.get('folder') || '';
    state.character = params.get('character') || '';
    state.outfit = params.get('outfit') || '';
    state.expression = params.get('expression') || '';
    state.category = ['sfw', 'nsfw'].includes(params.get('category')) ? params.get('category') : '';
    state.family = ['anima', 'sdxl', 'unknown'].includes(params.get('family'))
      ? params.get('family')
      : '';
    state.sort = ['newest', 'oldest', 'code'].includes(params.get('sort'))
      ? params.get('sort')
      : 'newest';
    state.latest = params.get('latest') === 'true';
    state.human = ['unreviewed', 'pass', 'fail'].includes(params.get('human_status'))
      ? params.get('human_status')
      : '';
    state.auto = ['pending', 'pass', 'fail', 'uncertain', 'error'].includes(
      params.get('auto_status'),
    )
      ? params.get('auto_status')
      : '';
    state.selectedOnly = ['true', '1'].includes(params.get('selected_only'));
    state.page = Math.max(1, parseInt(params.get('page') || '1', 10) || 1);
    state.pageSize = params.get('page_size') === '96' ? 96 : 48;
    state.snapshot =
      saved && sameSelection(params, new URLSearchParams(saved.query))
        ? String(saved.snapshot || '')
        : '';
    state.newAvailable = false;
    updateBanner.hidden = true;
    const restored = state.snapshot;
    await Promise.all([fetchTree(true), loadResults(false), loadRounds()]);
    // A snapshot kept from an earlier visit hides images made since; say so.
    if (restored) checkNewerThanSnapshot();
    clearInterval(state.poll);
    state.poll = setInterval(() => {
      if (state.active && !document.hidden) {
        fetchTree(false);
        loadRounds();
      }
    }, 10000);
  }
  function leave() {
    state.active = false;
    state.requestId++;
    clearInterval(state.poll);
    state.poll = null;
    state.previousFocus = null;
    closeDialog();
  }
  return {element: root, enter, leave};
}
