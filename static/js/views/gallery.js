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
  if (!value) return t('gallery.no_date');
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
    node('h1', '', t('common.gallery')),
    node('p', '', t('gallery.browse_generated_images_by_work_and')),
  );
  const refresh = node('button', 'g-button', t('gallery.refresh'));
  refresh.type = 'button';
  heading.append(titleBox, refresh);

  const layout = node('div', 'g-layout');
  const sidebar = node('aside', 'g-sidebar');
  sidebar.append(node('h2', '', t('gallery.work_library')));
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
  const characterSelect = makeSelect(
    t('common.character'),
    [['', t('gallery.all_characters')]],
    () => changeFilter('character', characterSelect.value),
  );
  const outfitSelect = makeSelect(t('common.outfit'), [['', t('gallery.all_outfits')]], () =>
    changeFilter('outfit', outfitSelect.value),
  );
  const expressionSelect = makeSelect(
    t('common.expression'),
    [['', t('gallery.all_expressions')]],
    () => changeFilter('expression', expressionSelect.value),
  );
  const categorySelect = makeSelect(
    t('gallery.rating'),
    [
      ['', t('common.all')],
      ['sfw', t('gallery.general_sfw')],
      ['nsfw', t('gallery.adult_nsfw')],
    ],
    () => changeFilter('category', categorySelect.value),
  );
  const familySelect = makeSelect(
    t('common.model'),
    [
      ['', t('gallery.all_models')],
      ['anima', 'Anima'],
      ['sdxl', 'SDXL·IL'],
      ['unknown', t('gallery.no_record')],
    ],
    () => changeFilter('family', familySelect.value),
  );
  const sortSelect = makeSelect(
    t('gallery.sort'),
    [
      ['newest', t('gallery.newest_first')],
      ['oldest', t('gallery.oldest_first')],
      ['code', t('gallery.by_code')],
    ],
    () => changeFilter('sort', sortSelect.value),
  );
  const pageSizeSelect = makeSelect(
    t('gallery.per_page'),
    [
      ['48', t('gallery.48_per_page')],
      ['96', t('gallery.96_per_page')],
    ],
    () => changeFilter('pageSize', Number(pageSizeSelect.value)),
  );
  const latestLabel = node('label', 'g-latest');
  const latestCheck = node('input');
  latestCheck.type = 'checkbox';
  latestLabel.append(latestCheck, node('span', '', t('gallery.latest_image_of_each')));
  latestCheck.addEventListener('change', () => changeFilter('latest', latestCheck.checked));
  filters.append(latestLabel);
  const humanSelect = makeSelect(
    t('gallery.my_verdict'),
    [
      ['', t('common.all')],
      ['unreviewed', t('gallery.unreviewed')],
      ['pass', t('common.pass')],
      ['fail', t('common.failed')],
    ],
    () => changeFilter('human', humanSelect.value),
  );
  const autoSelect = makeSelect(
    t('gallery.vlm_note'),
    [
      ['', t('common.all')],
      ['pending', t('common.queued')],
      ['pass', t('common.pass')],
      ['fail', t('common.failed')],
      ['uncertain', t('gallery.uncertain')],
      ['error', t('common.error')],
    ],
    () => changeFilter('auto', autoSelect.value),
  );
  const selectedLabel = node('label', 'g-latest');
  const selectedCheck = node('input');
  selectedCheck.type = 'checkbox';
  selectedLabel.append(selectedCheck, node('span', '', t('gallery.adopted_only')));
  selectedCheck.addEventListener('change', () =>
    changeFilter('selectedOnly', selectedCheck.checked),
  );
  filters.append(selectedLabel);
  toolbar.append(filters);
  const statusLine = node('div', 'g-status');
  const count = node('span', '', t('gallery.loading'));
  const updateBanner = node('button', 'g-update', t('gallery.new_images_refresh'));
  updateBanner.type = 'button';
  updateBanner.hidden = true;
  updateBanner.addEventListener('click', () => loadResults(true));
  statusLine.append(count, updateBanner);
  const actionBar = node('section', 'g-actions');
  actionBar.setAttribute('aria-label', t('gallery.image_selection_and_review'));
  const selectionCount = node('strong', 'g-selection-count', t('gallery.0_selected'));
  const selectionMessage = node('span', 'g-inline-message');
  selectionMessage.setAttribute('role', 'status');
  const actionButton = (label, fn) => {
    const button = node('button', 'g-button', label);
    button.type = 'button';
    button.onclick = fn;
    return button;
  };
  const selectPage = actionButton(t('gallery.select_this_page'), () => addSelection(state.results));
  const selectFiltered = actionButton(t('gallery.select_all_filtered'), selectAllFiltered);
  const clearSelection = actionButton(t('common.clear_selection'), () => {
    state.chosen.clear();
    renderResults();
  });
  const reviewPass = actionButton(t('gallery.pass_selected'), () => reviewChosen('pass'));
  const reviewFail = actionButton(t('gallery.fail_selected'), () => reviewChosen('fail'));
  const reviewReset = actionButton(t('gallery.mark_selected_unreviewed'), () =>
    reviewChosen('unreviewed'),
  );
  const regenerate = actionButton(t('gallery.regenerate_with_a_new_seed'), () =>
    regenerateItems([...state.chosen.values()]),
  );
  const toTools = actionButton(t('gallery.send_to_image_tools'), async () => {
    try {
      const paths = [...state.chosen.values()].map((item) => item.path);
      const result = await ctx.api('/api/tools/gallery', {paths});
      ctx.notify(t('gallery.added_images_to_the_image_tools', [result.added.length]));
      ctx.navigate('/tools');
    } catch (error) {
      setMessage(error.message || String(error), true);
    }
  });
  const exportButton = actionButton(t('gallery.export_current_scope_as_zip'), () =>
    exportCurrent(),
  );
  const exportPartial = actionButton(t('gallery.export_without_the_missing_ones'), () =>
    exportCurrent(true),
  );
  exportPartial.hidden = true;
  const exportHint = node('p', 'g-muted', t('gallery.exports_images_a_person_passed_that'));
  const regenHint = node('p', 'g-muted', t('gallery.generates_new_images_from_the_original'));
  const roundPanel = node('details', 'g-rounds');
  const roundSummary = node('summary');
  const roundList = node('div', 'g-round-list');
  const roundDismiss = actionButton(t('gallery.clear_finished_rounds'), dismissRounds);
  roundDismiss.title = t('gallery.clears_rounds_that_are_not_running');
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
  pagination.setAttribute('aria-label', t('gallery.gallery_pages'));
  main.append(toolbar, statusLine, roundPanel, actionBar, grid, pagination);
  layout.append(sidebar, main);
  root.append(heading, layout);

  const dialog = node('dialog', 'g-lightbox');
  dialog.setAttribute('aria-label', t('gallery.image_details'));
  const lightbox = node('div', 'g-lightbox-layout');
  const viewer = node('div', 'g-viewer');
  const viewerBar = node('div', 'g-viewer-bar');
  const prev = node('button', 'g-icon', '←');
  prev.type = 'button';
  prev.setAttribute('aria-label', t('gallery.previous_image'));
  const next = node('button', 'g-icon', '→');
  next.type = 'button';
  next.setAttribute('aria-label', t('gallery.next_image'));
  const zoom = node('button', 'g-button', t('gallery.view_at_100'));
  zoom.type = 'button';
  const close = node('button', 'g-icon', '×');
  close.type = 'button';
  close.setAttribute('aria-label', t('gallery.close'));
  viewerBar.append(prev, next, zoom, close);
  const imageScroll = node('div', 'g-image-scroll');
  const fullImage = node('img');
  fullImage.alt = t('gallery.generated_image');
  fullImage.addEventListener('error', () => {
    viewerCaption.textContent = t('gallery.cannot_open_the_image');
  });
  imageScroll.append(fullImage);
  const viewerCaption = node('div', 'g-viewer-caption');
  viewer.append(viewerBar, imageScroll, viewerCaption);
  const details = node('aside', 'g-details');
  const detailsHead = node('div', 'g-details-head');
  detailsHead.append(node('h2', '', t('gallery.record')));
  const detailReview = node('div', 'g-detail-review');
  const detailBadges = node('div', 'g-badges');
  const detailPass = actionButton(t('gallery.pass_p'), () => reviewItems([currentItem()], 'pass'));
  const detailFail = actionButton(t('gallery.fail_f'), () => reviewItems([currentItem()], 'fail'));
  const detailReset = actionButton(t('gallery.unreviewed_u'), () =>
    reviewItems([currentItem()], 'unreviewed'),
  );
  const detailRegen = actionButton(t('gallery.regenerate_with_a_new_seed'), () =>
    regenerateItems([currentItem()]),
  );
  const detailButtons = {pass: detailPass, fail: detailFail, unreviewed: detailReset};
  // The lab starts from this image's prompt and settings and keeps it as the reference.
  const detailLab = actionButton(t('common.open_in_lab'), () => {
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
  const humanLabel = {
    unreviewed: t('gallery.unreviewed'),
    pass: t('common.pass'),
    fail: t('common.failed'),
  };
  const autoLabel = {
    pending: t('common.queued'),
    pass: t('common.pass'),
    fail: t('common.failed'),
    uncertain: t('gallery.uncertain'),
    error: t('common.error'),
  };
  const autoMark = {pass: '✓', fail: '✕', uncertain: '?', error: '!'};
  const humanOf = (item) => item.human_status || 'unreviewed';
  const autoOf = (item) => item.auto_status || 'pending';
  /** The person's verdict as one chip; nothing for an image not judged yet. */
  function humanChip(item) {
    if (item.selected) {
      const chip = node('span', 'g-chip pass selected', t('gallery.adopted'));
      chip.title = t('gallery.passed_the_currently_adopted_image_of');
      return chip;
    }
    if (humanOf(item) === 'pass') {
      const chip = node('span', 'g-chip pass', t('gallery.pass'));
      chip.title = t('gallery.passed_but_another_image_of_the');
      return chip;
    }
    if (humanOf(item) === 'fail') return node('span', 'g-chip fail', t('gallery.fail'));
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
      t('gallery.vlm_verdict_reference', [autoLabel[autoOf(item)]]),
      disagrees ? t('gallery.differs_from_my_verdict') : '',
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
    setMessage(t('gallery.added', [added]));
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
        setMessage(t('gallery.selecting_filtered_images', [selected]));
        if (page >= Number(payload.pages || 1)) break;
      }
      setMessage(t('gallery.added_filtered_images', [selected]));
    } catch (error) {
      setMessage(t('gallery.selection_stopped', [error.message || error]), true);
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
        t('gallery.images_2', [
          ids.length - errors.length,
          humanLabel[verdict],
          errors.length
            ? t('gallery.failed', [
                errors.length,
                tr(errors[0].error) || tr(errors[0].message) || t('gallery.status_changed'),
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
        t('gallery.queued_images_with_new_seeds', [
          count,
          response.reviewing ? t('gallery.the_vlm_reviews_them_after_generation') : '',
          response.warning ? t('gallery.edits_applied_after_generation_are_not') : '',
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
    selectionCount.textContent = t('common.selected', [state.chosen.size.toLocaleString(locale)]);
    for (const button of [reviewPass, reviewFail, reviewReset, regenerate, toTools])
      button.disabled = !has || state.actionBusy || ctx.preview;
    for (const button of [detailPass, detailFail, detailReset, detailRegen])
      button.disabled = !currentItem() || state.actionBusy || ctx.preview;
    clearSelection.disabled = !has || state.actionBusy;
  }
  const ROUND_STATUS = {
    waiting_generation: t('gallery.waiting_to_generate'),
    pending_review: t('gallery.waiting_for_vlm_review'),
    reviewing: t('gallery.vlm_reviewing'),
    switching: t('gallery.switching_gpu_use'),
    queueing: t('gallery.preparing_regeneration'),
    failed_review: t('gallery.vlm_failed_check_needed'),
    needs_attention: t('gallery.check_needed'),
    limit_reached: t('gallery.auto_regeneration_limit_reached'),
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
      roundSummary.textContent = t('gallery.vlm_review_in_progress_to_check', [
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
            t('gallery.auto_regenerations', [
              asList(round.combo).join('/'),
              round.stale ? t('gallery.stalled_no_job_in_the_queue') : ROUND_STATUS[round.status],
              n,
              limit,
              round.error ? ` · ${tr(round.error)}` : '',
            ]),
          ),
        );
      }
      if (state.rounds.length > ROUND_LIST_LIMIT)
        roundList.append(
          node(
            'div',
            'g-round-item',
            t('gallery.and_more', [state.rounds.length - ROUND_LIST_LIMIT]),
          ),
        );
      roundDismiss.disabled = ctx.preview || state.actionBusy;
    } catch {
      /* Round polling must not spam notices. */
    }
  }
  async function dismissRounds() {
    if (!confirm(t('gallery.clear_vlm_review_rounds_that_are'))) return;
    try {
      const result = await ctx.api('/api/review/rounds/dismiss', {});
      setMessage(t('gallery.cleared_vlm_review_rounds', [result.dismissed]));
      await loadRounds();
    } catch (error) {
      setMessage(error.message || String(error), true);
    }
  }
  async function exportCurrent(allowPartial = false) {
    if (state.actionBusy) return;
    if (!state.category) {
      setMessage(t('gallery.choose_sfw_or_nsfw_to_export'), true);
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
              ? t('gallery.missing_2', [
                  missing.length,
                  missing.slice(0, 5).join(', '),
                  missing.length > 5 ? '…' : '',
                ])
              : tr(data.error) || t('gallery.missing_required_fields');
          setMessage(t('gallery.export_incomplete', [summary]), true);
          exportPartial.hidden = false;
          return;
        }
        throw new Error(
          tr(data.error) || tr(data.message) || t('gallery.export_failed', [response.status]),
        );
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
        t('gallery.zip_export_done', [
          exported ? t('gallery.images', [exported]) : '',
          complete === 'false' || allowPartial ? t('gallery.partial') : t('common.all'),
          missingCount && Number(missingCount) ? t('gallery.missing', [missingCount]) : '',
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
      t('gallery.all_works', [
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
    if (folders.length) treeBox.append(node('h3', 'g-tree-heading', t('gallery.other_folders')));
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
    updateSelect(characterSelect, characterNodes(), t('gallery.all_characters'), state.character);
    updateSelect(outfitSelect, outfitNodes(), t('gallery.all_outfits'), state.outfit);
    // Expression names are derived from currently loaded images; the API tree may also provide them.
    const expressions = asList(state.tree?.expressions).length
      ? state.tree.expressions
      : state.results.map((item) => ({
          id: item.expression_id,
          name: item.expression_name || item.expression_id,
        }));
    updateSelect(expressionSelect, expressions, t('gallery.all_expressions'), state.expression);
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
    count.textContent = t('gallery.loading_images');
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
      count.textContent = t('gallery.could_not_load_the_image');
      notice(error);
      return false;
    }
  }
  function renderResults() {
    count.textContent = t('gallery.images_page', [
      state.total.toLocaleString(locale),
      state.page,
      state.pages,
    ]);
    selectPage.textContent = t('gallery.select_this_page_2', [state.results.length]);
    selectFiltered.textContent = t('gallery.select_all_filtered_2', [
      state.total.toLocaleString(locale),
    ]);
    updateActions();
    grid.replaceChildren();
    if (!state.results.length) grid.append(node('p', 'g-empty', t('gallery.no_images_match')));
    state.results.forEach((item, index) => {
      const card = node('article', 'g-card');
      const checkLabel = node('label', 'g-card-select');
      const check = node('input');
      check.type = 'checkbox';
      check.checked = state.chosen.has(identityKey(item));
      check.disabled = !identity(item);
      check.setAttribute('aria-label', t('common.select', [item.filename || t('gallery.image')]));
      check.addEventListener('change', () => {
        const id = identity(item);
        if (!id) return;
        if (check.checked) state.chosen.set(identityKey(item), id);
        else state.chosen.delete(identityKey(item));
        card.classList.toggle('chosen', check.checked);
        updateActions();
      });
      checkLabel.append(check, node('span', '', t('gallery.select')));
      card.classList.toggle('chosen', check.checked);
      const open = node('button', 'g-card-open');
      open.type = 'button';
      open.setAttribute('aria-label', t('gallery.details', [item.filename || t('gallery.image')]));
      const frame = node('span', 'g-card-image');
      const image = node('img');
      image.loading = 'lazy';
      image.decoding = 'async';
      image.alt = t('gallery.preview', [item.filename || t('gallery.image')]);
      const thumbnail = safeUrl(item.thumbnail_url || item.image_url);
      if (thumbnail) {
        image.src = thumbnail;
        frame.append(image);
      } else {
        frame.classList.add('failed');
        frame.append(node('span', '', t('gallery.no_preview')));
      }
      image.onerror = () => {
        frame.classList.add('failed');
        image.remove();
        frame.append(node('span', '', t('gallery.no_preview')));
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
    pagination.append(pageButton(t('gallery.previous'), state.page - 1, state.page <= 1));
    const start = Math.max(1, Math.min(state.page - 2, state.pages - 4));
    for (let page = start; page <= Math.min(state.pages, start + 4); page++)
      pagination.append(pageButton(String(page), page, false, page === state.page));
    pagination.append(pageButton(t('gallery.next'), state.page + 1, state.page >= state.pages));
  }
  function renderDetailReview(item) {
    const row = (title, ...content) => {
      const line = node('div', 'g-verdict-row');
      line.append(node('span', 'g-verdict-title', title), ...content.filter(Boolean));
      return line;
    };
    detailBadges.replaceChildren(
      row(
        t('gallery.my_verdict'),
        humanChip(item) || node('span', 'g-chip', t('gallery.unreviewed')),
      ),
    );
    // A stored VLM verdict stays visible here even after review is switched off.
    if (autoOf(item) !== 'pending') {
      const chip = node(
        'span',
        `g-chip auto ${autoOf(item)}`,
        `${autoMark[autoOf(item)]} ${autoLabel[autoOf(item)]}`,
      );
      detailBadges.append(row(t('gallery.vlm_note'), chip));
      if (item.auto_reason) detailBadges.append(node('p', 'g-muted', item.auto_reason));
    } else if (state.vlmEnabled) {
      detailBadges.append(
        row(t('gallery.vlm_note'), node('span', 'g-chip', t('gallery.not_reviewed_yet'))),
      );
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
    const button = node('button', 'g-copy', t('gallery.copy', [label]));
    button.type = 'button';
    button.onclick = async () => {
      try {
        await navigator.clipboard.writeText(String(value));
        ctx.notify?.(t('gallery.copied', [label]));
      } catch (error) {
        ctx.notify?.(t('gallery.cannot_copy', [label]), true);
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
    detailsBody.replaceChildren(node('p', '', t('gallery.loading_the_record')));
    if (item.metadata_available === false) {
      detailsBody.replaceChildren(node('p', 'g-muted', t('gallery.this_image_has_no_json_record')));
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
        node('h3', '', t('gallery.image')),
        table([
          [t('common.file'), item.filename],
          [t('common.generate'), metadata.created_at || item.created_at],
          [t('common.work'), metadata.work_id || item.work_id],
          [t('common.character'), metadata.character_id || item.character_id],
          [t('common.outfit_set'), metadata.outfit_id || item.outfit_id],
          [
            t('gallery.outfit_slots'),
            asList(metadata.outfit_slots || metadata.outfit_parts).join(', '),
          ],
          [t('common.expression'), metadata.expression_name || item.expression_id],
          [t('gallery.rating'), metadata.category || item.category],
          [t('common.size'), asList(metadata.image_size).join(' × ')],
          [t('gallery.batch_id'), metadata.batch_id],
        ]),
      );
      if (metadata.generation_preset)
        detailsBody.append(
          node('h3', '', t('gallery.generation_presets')),
          table([
            [t('common.name'), metadata.generation_preset.name],
            ['ID', metadata.generation_preset.id],
            [
              t('gallery.edit_settings'),
              metadata.generation_preset.settings_modified === true
                ? t('gallery.edited_by_you')
                : t('gallery.use_original'),
            ],
          ]),
        );
      detailsBody.append(
        node('h3', '', t('common.generation_settings')),
        table([
          [t('common.model'), settings.model],
          [t('common.text_encoder'), settings.text_encoder],
          ['VAE', settings.vae],
          [t('common.clip_type'), settings.clip_type],
          [t('gallery.step'), settings.steps],
          ['CFG', settings.cfg],
          [t('common.sampler'), settings.sampler],
          [t('common.scheduler'), settings.scheduler],
          [t('common.seed'), metadata.seed ?? settings.seed],
          [t('common.width'), settings.width],
          [t('common.height'), settings.height],
        ]),
      );
      if (
        (metadata.seed !== undefined && metadata.seed !== null) ||
        (settings.seed !== undefined && settings.seed !== null)
      )
        detailsBody.append(copyButton(t('common.seed'), metadata.seed ?? settings.seed));
      if (asList(settings.loras).length) {
        detailsBody.append(node('h3', '', 'LoRA'));
        for (const lora of settings.loras)
          detailsBody.append(
            table([
              [t('common.name'), lora.name],
              [t('common.model_strength'), lora.strength_model],
              [t('common.clip_strength'), lora.strength_clip],
            ]),
          );
      }
      detailsBody.append(node('h3', '', t('gallery.prompt_layout')));
      for (const [key, label] of [
        ['work', t('gallery.work_wide')],
        ['common', t('common.common_positive')],
        ['quality', t('common.quality')],
        ['artist', t('common.style')],
        ['composition', t('common.composition')],
        ['appearance', t('common.appearance')],
        ['expression', t('common.expression')],
        ['outfit', t('common.outfit')],
        ['negative', t('gallery.negatives')],
      ]) {
        if (parts[key]) detailsBody.append(textSection(label, parts[key]));
      }
      detailsBody.append(
        textSection(t('gallery.positive_prompt_text'), metadata.positive, true),
        textSection(t('gallery.negative_prompt_text'), metadata.negative),
      );
      if (metadata.positive !== undefined && metadata.positive !== null)
        detailsBody.append(copyButton(t('common.positive_prompt'), metadata.positive));
      if (metadata.negative !== undefined && metadata.negative !== null)
        detailsBody.append(copyButton(t('gallery.negative_prompt'), metadata.negative));
      if (metadata.workflow) {
        const workflowButton = node('button', 'g-button', t('gallery.download_workflow_json'));
        workflowButton.type = 'button';
        workflowButton.onclick = () =>
          downloadJson(
            metadata.workflow,
            `${(item.filename || 'workflow').replace(/\.[^.]+$/, '')}-workflow.json`,
          );
        detailsBody.append(workflowButton);
      }
      const metadataButton = node('button', 'g-button', t('gallery.download_record_json'));
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
      detailsBody.replaceChildren(node('p', 'g-muted', t('gallery.cannot_open_the_record')));
      const retry = node('button', 'g-button', t('gallery.retry'));
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
    zoom.textContent = t('gallery.view_at_100');
    imageScroll.scrollTop = 0;
    imageScroll.scrollLeft = 0;
    const imageUrl = safeUrl(item.image_url);
    if (imageUrl) fullImage.src = imageUrl;
    else fullImage.removeAttribute('src');
    fullImage.alt = t('gallery.original', [item.filename || t('gallery.image')]);
    viewerCaption.textContent = imageUrl
      ? t('gallery.page', [
          item.filename || t('gallery.image'),
          state.page,
          index + 1,
          state.dialogItems.length,
        ])
      : t('gallery.cannot_open_the_image_address');
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
    zoom.textContent = state.fullSize ? t('common.fit_to_screen') : t('gallery.view_at_100');
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
