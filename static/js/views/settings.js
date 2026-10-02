'use strict';

import {createSettingsSections} from './settings_sections.js';
import {locale, t, tr} from '../core/i18n.js';

const element = (tag, className = '', text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
const copy = (value) => JSON.parse(JSON.stringify(value));
const readableBytes = (value) => {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return '';
  return `${(number / 1024 ** 3).toFixed(1)} GB`;
};

export function createSettings(ctx) {
  const root = element('section');
  root.id = 'app-settings';
  const heading = element('div', 's-heading');
  heading.append(
    element('div', 's-eyebrow', 'SETTINGS'),
    element('h1', '', t('common.settings')),
    element('p', '', t('settings.interface_comfyui_connection_training_gpu_and')),
  );
  root.append(heading);

  const statusCard = element('section', 's-card');
  const statusHead = element('div', 's-card-head');
  const statusTitle = element('div');
  statusTitle.append(element('h2', '', t('settings.connection')));
  const checkButton = element('button', 's-button', t('settings.check_connection'));
  checkButton.type = 'button';
  statusHead.append(statusTitle, checkButton);
  const statusLine = element('div', 's-status-line');
  const statusDot = element('span', 's-dot');
  const statusText = element('strong', '', t('common.checking'));
  const ownership = element('span', 's-tag', '');
  statusLine.append(statusDot, statusText, ownership);
  const statusDetail = element('p', 's-muted');
  const stats = element('div', 's-stats');
  const controlRow = element('div', 's-control-row');
  const startButton = element('button', 's-button s-primary', t('settings.start_comfyui'));
  startButton.type = 'button';
  const stopButton = element('button', 's-button', t('settings.stop'));
  stopButton.type = 'button';
  const restartButton = element('button', 's-button', t('settings.restart'));
  restartButton.type = 'button';
  for (const button of [startButton, stopButton, restartButton]) button.disabled = true;
  controlRow.append(startButton, stopButton, restartButton);
  const controlHint = element('p', 's-muted', t('settings.only_a_comfyui_started_by_this'));
  statusCard.append(statusHead, statusLine, statusDetail, stats, controlRow, controlHint);

  const configCard = element('section', 's-card');
  const configHead = element('div', 's-card-head');
  configHead.append(element('div', '', ''));
  configHead.firstChild.append(
    element('h2', '', t('settings.comfyui_connection_settings')),
    element('p', 's-muted', t('settings.enter_the_local_address_and_paths')),
  );
  const dirtyTag = element('span', 's-tag s-dirty', t('settings.unsaved_changes'));
  dirtyTag.hidden = true;
  configHead.append(dirtyTag);
  const form = element('form', 's-form');
  const makeField = (label, description, id, tag = 'input') => {
    const wrapper = element('label', 's-field');
    wrapper.append(element('span', 's-label', label));
    const input = element(tag);
    input.id = id;
    if (tag === 'input') input.type = 'text';
    input.autocomplete = 'off';
    wrapper.append(input);
    if (description) wrapper.append(element('small', 's-muted', description));
    form.append(wrapper);
    return input;
  };
  const urlInput = makeField(
    t('settings.local_comfyui_address'),
    t('settings.a_local_address_like_http_127'),
    'settings-comfy-url',
  );
  urlInput.type = 'url';
  urlInput.required = true;
  const pythonInput = makeField(
    t('settings.python_executable'),
    t('settings.full_path_to_python_exe_in'),
    'settings-python-path',
  );
  pythonInput.required = true;
  const comfyInput = makeField(
    t('settings.comfyui_folder'),
    t('settings.full_path_to_the_folder_with'),
    'settings-comfy-path',
  );
  comfyInput.required = true;
  const argsInput = makeField(
    t('settings.launch_arguments_json_array'),
    t('settings.e_g_preview_method_auto'),
    'settings-comfy-arguments',
    'textarea',
  );
  argsInput.rows = 5;
  argsInput.spellcheck = false;
  const formActions = element('div', 's-form-actions');
  // Finds installed ComfyUIs; picking one only fills the form, saving stays explicit.
  const locateButton = element('button', 's-button', t('settings.find_automatically'));
  locateButton.type = 'button';
  const locateBox = element('div', 's-locate');
  const KIND_LABELS = {
    portable: t('settings.comfyui_portable'),
    stability_matrix: 'Stability Matrix',
    desktop: t('settings.comfyui_desktop_app'),
    venv: t('settings.git_install_venv'),
    unknown: t('settings.unknown'),
  };
  locateButton.addEventListener('click', async () => {
    locateButton.disabled = true;
    locateBox.replaceChildren(element('p', 's-muted', t('settings.searching')));
    try {
      const {candidates} = await ctx.api('/api/comfy/locate');
      if (!candidates.length) {
        locateBox.replaceChildren(
          element('p', 's-muted', t('settings.no_comfyui_was_found_enter_the')),
        );
        return;
      }
      locateBox.replaceChildren(
        ...candidates.map((found) => {
          const row = element('div', 's-locate-row');
          const text = element('div');
          text.append(
            element('strong', '', found.comfy_path),
            element(
              'small',
              's-muted',
              [
                KIND_LABELS[found.kind] || found.kind,
                found.source === 'running' ? t('settings.running', [found.version || '?']) : '',
                found.python_path || t('settings.python_not_found'),
              ]
                .filter(Boolean)
                .join(' · '),
            ),
          );
          const use = element('button', 's-button', t('settings.use_this_install'));
          use.type = 'button';
          use.disabled = preview || !found.python_path;
          use.addEventListener('click', () => {
            putFields({
              ...fields(),
              comfy_path: found.comfy_path,
              python_path: found.python_path,
              ...(found.arguments ? {arguments: found.arguments} : {}),
            });
            ctx.notify?.(t('settings.the_fields_are_filled_in_check'));
          });
          row.append(text, use);
          return row;
        }),
      );
    } catch (error) {
      locateBox.replaceChildren(element('p', 's-error', error.message));
    } finally {
      locateButton.disabled = false;
    }
  });
  const discardButton = element('button', 's-button', t('settings.discard_changes'));
  discardButton.type = 'button';
  const saveButton = element('button', 's-button s-primary', t('settings.save_settings'));
  saveButton.type = 'submit';
  discardButton.disabled = true;
  saveButton.disabled = true;
  for (const input of [urlInput, pythonInput, comfyInput, argsInput]) input.disabled = true;
  formActions.append(locateButton, discardButton, saveButton);
  form.append(formActions, locateBox);
  const configHint = element('p', 's-muted', t('settings.saving_checks_the_connection_at_the'));
  configCard.append(configHead, form, configHint);
  const reviewCard = element('section', 's-card');
  const reviewHead = element('div', 's-card-head');
  const reviewTitle = element('div');
  reviewTitle.append(
    element('h2', '', t('settings.vlm_review_2')),
    element('p', 's-muted', t('settings.a_local_vlm_compares_each_image')),
  );
  const vlmCheck = element('button', 's-button', t('settings.test_vlm_connection'));
  vlmCheck.type = 'button';
  reviewHead.append(reviewTitle, vlmCheck);
  const vlmStatus = element('p', 's-review-status', t('settings.checking_the_vlm_settings'));
  vlmStatus.setAttribute('role', 'status');
  const vlmHint = element('p', 's-muted', t('settings.set_the_vlm_server_in_the'));
  const vlmPath = element('p', 's-muted');
  const reviewForm = element('form', 's-review-form');
  const enabledLabel = element('label', 's-review-check');
  const enabledInput = element('input');
  enabledInput.type = 'checkbox';
  enabledInput.disabled = true;
  enabledLabel.append(enabledInput, element('span', '', t('settings.use_vlm_review')));
  const enabledHint = element('p', 's-muted', t('settings.when_off_nothing_is_reviewed_or'));
  const maxLabel = element('label', 's-field');
  maxLabel.append(element('span', 's-label', t('settings.max_automatic_regenerations')));
  const maxInput = element('input');
  maxInput.type = 'number';
  maxInput.min = '0';
  maxInput.max = '100';
  maxInput.step = '1';
  maxInput.value = '10';
  maxInput.disabled = true;
  maxLabel.append(
    maxInput,
    element('small', 's-muted', t('settings.default_10_the_first_generation_does')),
  );
  const reviewSave = element('button', 's-button s-primary', t('settings.save_regeneration_limit'));
  reviewSave.type = 'submit';
  reviewSave.disabled = true;
  const reviewMessage = element('p', 's-muted');
  reviewMessage.setAttribute('role', 'status');
  reviewForm.append(enabledLabel, enabledHint, maxLabel, reviewSave);
  reviewCard.append(reviewHead, vlmStatus, vlmHint, vlmPath, reviewForm, reviewMessage);
  const gpuCard = element('section', 's-card');
  const gpuHead = element('div', 's-card-head');
  const gpuTitle = element('div');
  gpuTitle.append(
    element('h2', '', t('settings.gpu_use')),
    element('p', 's-muted', t('settings.generation_vlm_review_and_lora_training')),
  );
  const gpuRelease = element('button', 's-button', t('settings.release_external_reservation'));
  gpuRelease.type = 'button';
  gpuRelease.hidden = true;
  gpuHead.append(gpuTitle, gpuRelease);
  const gpuLine = element('p', 's-review-status', t('settings.checking_the_gpu'));
  gpuLine.setAttribute('role', 'status');
  const gpuDetail = element('p', 's-muted');
  gpuCard.append(gpuHead, gpuLine, gpuDetail);
  const sections = createSettingsSections(ctx, {onVlmSaved: () => loadReview()});
  const {general, lora, tags, gpuWait, vlm} = sections.cards;
  root.append(general, statusCard, configCard, tags, lora, gpuCard, gpuWait, vlm, reviewCard);

  let active = false;
  let timer = null;
  let status = null;
  let config = null;
  let preview = Boolean(ctx.preview);
  let busy = false;
  let statusSequence = 0;
  let storageKey = '';
  let reviewConfig = null;
  let vlmConfig = null;
  let reviewBusy = false;
  let vlmTestMessage = '';
  let reviewDraft = null;
  let gpu = null;

  function renderGpu() {
    if (!gpu) return;
    gpuLine.textContent = gpu.holder
      ? t('settings.in_use_3', [tr(gpu.label), gpu.state_label ? ` · ${tr(gpu.state_label)}` : ''])
      : t('settings.in_use_image_generation', [
          gpu.running_jobs ? t('settings.in_progress', [gpu.running_jobs]) : '',
        ]);
    const since = gpu.since ? new Date(gpu.since).toLocaleString(locale) : '';
    const vram = gpu.vram_total_mb
      ? t('settings.free_gpu_memory_gb', [
          (gpu.vram_free_mb / 1024).toFixed(1),
          (gpu.vram_total_mb / 1024).toFixed(1),
        ])
      : '';
    gpuDetail.textContent = [
      gpu.waiting ? t('settings.waiting_because', [tr(gpu.waiting.reason)]) : '',
      vram,
      since ? t('settings.started', [since]) : '',
      gpu.error ? t('settings.error', [tr(gpu.error)]) : '',
      gpu.holder ? t('settings.queued_images_wait_until_this_finishes') : '',
    ]
      .filter(Boolean)
      .join(' · ');
    // Only an outside reservation can be cleared here; in-process holders finish by themselves.
    gpuRelease.hidden = gpu.holder !== 'external';
    gpuRelease.disabled = preview;
  }
  async function loadGpu() {
    try {
      gpu = await ctx.api('/api/gpu');
      if (active) renderGpu();
    } catch (error) {
      gpuLine.textContent = t('settings.cannot_read_the_gpu_status', [error.message || error]);
    }
  }
  gpuRelease.onclick = async () => {
    if (
      !window.confirm(
        t('settings.release_the_gpu_reservation_of_if', [
          gpu?.label || t('settings.external_work'),
        ]),
      )
    )
      return;
    try {
      gpu = await ctx.api('/api/gpu/release', {force: true});
      renderGpu();
      ctx.notify?.(t('settings.released_the_gpu_reservation'));
    } catch (error) {
      ctx.notify?.(error.message || String(error), true);
    }
  };

  function renderReview() {
    const configured = Boolean(vlmConfig?.configured);
    const stateNames = {idle: t('settings.ready'), error: t('common.error')};
    const state = !configured
      ? t('settings.cannot_turn_on_without_connection_settings')
      : stateNames[vlmConfig?.status] || vlmConfig?.status || t('settings.set_up');
    const usage = reviewConfig?.enabled ? t('settings.in_use') : t('settings.off');
    vlmStatus.textContent =
      vlmTestMessage ||
      t('settings.vlm_review_connection', [
        usage,
        state,
        vlmConfig?.error ? ` · ${tr(vlmConfig.error)}` : '',
      ]);
    maxLabel.hidden = !enabledInput.checked;
    reviewSave.hidden = !enabledInput.checked;
    vlmPath.textContent = vlmConfig?.config_path
      ? t('settings.settings_file', [vlmConfig.config_path])
      : '';
    enabledInput.disabled = reviewBusy || preview || !reviewConfig || !configured;
    maxInput.disabled = reviewBusy || preview || !reviewConfig;
    reviewSave.disabled =
      reviewBusy ||
      preview ||
      !reviewConfig ||
      !Number.isInteger(Number(maxInput.value)) ||
      Number(maxInput.value) < 0 ||
      Number(maxInput.value) > 100 ||
      (enabledInput.checked && !configured);
    vlmCheck.disabled = reviewBusy || preview || !configured;
  }
  async function loadReview() {
    const [settingsResult, vlmResult] = await Promise.allSettled([
      ctx.api('/api/review/settings'),
      ctx.api('/api/vlm/status'),
    ]);
    if (!active) return;
    if (settingsResult.status === 'fulfilled') {
      reviewConfig = settingsResult.value;
      maxInput.value = String(
        reviewDraft?.max_auto_regenerations ?? reviewConfig.max_auto_regenerations ?? 10,
      );
      enabledInput.checked = Boolean(reviewDraft?.enabled ?? reviewConfig.enabled);
    } else
      reviewMessage.textContent = t('settings.cannot_load_the_review_settings', [
        settingsResult.reason.message || settingsResult.reason,
      ]);
    if (vlmResult.status === 'fulfilled') vlmConfig = vlmResult.value;
    else
      vlmConfig = {
        configured: false,
        status: t('settings.status_check_failed'),
        error: vlmResult.reason.message || String(vlmResult.reason),
      };
    renderReview();
  }
  async function saveReview(event) {
    event?.preventDefault();
    const limit = Number(maxInput.value);
    if (reviewBusy || !Number.isInteger(limit) || limit < 0 || limit > 100) {
      reviewMessage.textContent = t('settings.auto_regenerations_must_be_a_whole');
      return;
    }
    reviewBusy = true;
    renderReview();
    try {
      reviewConfig = await ctx.api('/api/review/settings', {
        enabled: enabledInput.checked,
        max_auto_regenerations: limit,
      });
      reviewDraft = null;
      reviewMessage.textContent = reviewConfig.enabled
        ? t('settings.vlm_review_is_on')
        : t('settings.vlm_review_is_off_the_gallery');
    } catch (error) {
      // The switch shows the stored state again when saving fails.
      reviewDraft = null;
      enabledInput.checked = Boolean(reviewConfig?.enabled);
      reviewMessage.textContent = error.message || String(error);
    } finally {
      reviewBusy = false;
      renderReview();
    }
  }
  reviewForm.addEventListener('submit', saveReview);
  const updateReviewDraft = () => {
    reviewDraft = {enabled: enabledInput.checked, max_auto_regenerations: maxInput.value};
    renderReview();
  };
  maxInput.addEventListener('input', updateReviewDraft);
  enabledInput.addEventListener('change', () => {
    updateReviewDraft();
    saveReview();
  });
  vlmCheck.onclick = async () => {
    if (reviewBusy || !vlmConfig?.configured) return;
    reviewBusy = true;
    vlmTestMessage = t('settings.testing_the_vlm_connection');
    renderReview();
    try {
      const result = await ctx.api('/api/vlm/test', {});
      vlmTestMessage = result.loaded
        ? t('settings.vlm_model_loaded')
        : result.configured
          ? t('settings.vlm_settings_ok_model_not_loaded')
          : t('settings.vlm_not_set_up');
      if (result.error) vlmTestMessage += ` · ${tr(result.error)}`;
    } catch (error) {
      vlmTestMessage = t('settings.vlm_connection_test_failed', [error.message || error]);
    } finally {
      reviewBusy = false;
      renderReview();
    }
  };

  function keyForDraft() {
    return `asset-studio:connection-draft:${location.origin}:${preview ? 'preview' : 'live'}`;
  }
  function fields() {
    return {
      url: urlInput.value.trim(),
      python_path: pythonInput.value.trim(),
      comfy_path: comfyInput.value.trim(),
      arguments: argsInput.value,
    };
  }
  function edited() {
    if (!config) return false;
    const value = fields();
    return (
      value.url !== config.url ||
      value.python_path !== config.python_path ||
      value.comfy_path !== config.comfy_path ||
      value.arguments.trim() !== JSON.stringify(config.arguments || [], null, 2)
    );
  }
  function updateDirty() {
    const dirty = edited();
    dirtyTag.hidden = !dirty;
    discardButton.disabled = !dirty || preview || busy;
    saveButton.disabled =
      !dirty || preview || busy || Boolean(status?.owned) || Boolean(status?.operation);
    if (!storageKey) return;
    try {
      if (dirty) localStorage.setItem(storageKey, JSON.stringify(fields()));
      else localStorage.removeItem(storageKey);
    } catch {
      /* The form still works when storage is unavailable. */
    }
  }
  function putFields(value) {
    urlInput.value = value.url || '';
    pythonInput.value = value.python_path || '';
    comfyInput.value = value.comfy_path || '';
    argsInput.value =
      typeof value.arguments === 'string'
        ? value.arguments
        : JSON.stringify(value.arguments || [], null, 2);
    updateDirty();
  }
  function renderStats(payload) {
    stats.replaceChildren();
    if (!payload?.connected) return;
    const entries = [];
    if (payload.system?.comfyui_version) entries.push(['ComfyUI', payload.system.comfyui_version]);
    if (payload.system?.python_version) entries.push(['Python', payload.system.python_version]);
    for (const device of Array.isArray(payload.devices) ? payload.devices : []) {
      const gpu = device.name || device.type || t('settings.device');
      const memory = readableBytes(device.vram_total);
      entries.push(['GPU', memory ? `${gpu} · ${memory}` : gpu]);
    }
    entries.push(
      [t('common.running'), payload.running ?? 0],
      [t('settings.waiting'), payload.pending ?? 0],
    );
    for (const [label, value] of entries) {
      const item = element('div', 's-stat');
      item.append(element('span', '', label), element('strong', '', value));
      stats.append(item);
    }
  }
  function renderStatus() {
    if (!status) return;
    statusDot.classList.toggle('connected', Boolean(status.connected));
    statusDot.classList.toggle('working', Boolean(status.operation));
    statusText.textContent = status.operation
      ? {
          start: t('settings.starting'),
          stop: t('settings.waiting_to_stop'),
          restart: t('settings.waiting_to_restart'),
        }[status.operation] || t('settings.processing')
      : status.connected
        ? t('settings.connected')
        : t('settings.not_connected');
    ownership.textContent = status.owned
      ? t('settings.started_by_this_app')
      : status.connected
        ? t('settings.external_process')
        : t('settings.no_run_information');
    statusDetail.textContent = status.error
      ? t('settings.status', [tr(status.error)])
      : t('settings.address_2', [status.url || config?.url || '—']);
    controlRow.hidden = preview || Boolean(status.preview);
    startButton.disabled = busy || !status.can_start;
    stopButton.disabled = busy || !status.can_stop;
    restartButton.disabled = busy || !status.can_restart;
    controlHint.textContent =
      status.connected && !status.owned
        ? t('settings.manage_a_comfyui_started_elsewhere_for')
        : t('settings.only_a_comfyui_started_by_this');
    renderStats(status);
    updateDirty();
  }
  async function fetchStatus() {
    const sequence = ++statusSequence;
    try {
      const next = await ctx.api('/api/connection/status');
      if (!active || sequence !== statusSequence) return;
      status = next;
      if (next.preview !== undefined && next.preview !== preview) {
        preview = Boolean(next.preview);
        storageKey = keyForDraft();
      }
      renderStatus();
    } catch (error) {
      if (!active || sequence !== statusSequence) return;
      status = {
        connected: false,
        owned: false,
        error: error.message || String(error),
        can_start: false,
        can_stop: false,
        can_restart: false,
      };
      renderStatus();
    }
  }
  async function loadConfig() {
    try {
      const response = await ctx.api('/api/connection/settings');
      if (!active) return;
      preview = Boolean(response.preview ?? preview);
      storageKey = keyForDraft();
      config = copy(response.config || {});
      let saved = null;
      try {
        saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      } catch {
        /* Ignore stale storage. */
      }
      putFields(saved && typeof saved === 'object' ? saved : config);
      for (const input of [urlInput, pythonInput, comfyInput, argsInput]) input.disabled = preview;
      updateDirty();
      renderReview();
    } catch (error) {
      ctx.notify?.(error.message || String(error), true);
    }
  }
  async function control(action) {
    if (!status?.[`can_${action}`] || busy || preview) return;
    if (action === 'stop' && !window.confirm(t('settings.stop_the_comfyui_this_app_started')))
      return;
    if (action === 'restart' && !window.confirm(t('settings.restart_the_comfyui_this_app_started')))
      return;
    busy = true;
    renderStatus();
    try {
      await ctx.api('/api/connection/control', {action});
      ctx.notify?.(
        action === 'start'
          ? t('settings.asked_comfyui_to_start')
          : action === 'stop'
            ? t('settings.stops_after_the_current_job')
            : t('settings.restarts_after_the_current_job'),
      );
    } catch (error) {
      ctx.notify?.(error.message || String(error), true);
    } finally {
      busy = false;
      await fetchStatus();
    }
  }
  async function save(event) {
    event.preventDefault();
    if (preview || busy || !config || !edited()) return;
    let argumentsList;
    try {
      argumentsList = JSON.parse(argsInput.value);
      if (
        !Array.isArray(argumentsList) ||
        !argumentsList.every((value) => typeof value === 'string')
      )
        throw new Error();
    } catch {
      ctx.notify?.(t('settings.launch_arguments_must_be_a_json'), true);
      argsInput.focus();
      return;
    }
    busy = true;
    updateDirty();
    try {
      const response = await ctx.api('/api/connection/settings', {
        url: urlInput.value.trim(),
        python_path: pythonInput.value.trim(),
        comfy_path: comfyInput.value.trim(),
        arguments: argumentsList,
      });
      config = copy(
        response.config || {
          url: urlInput.value.trim(),
          python_path: pythonInput.value.trim(),
          comfy_path: comfyInput.value.trim(),
          arguments: argumentsList,
        },
      );
      putFields(config);
      ctx.notify?.(t('settings.saved_the_connection_settings'));
      await fetchStatus();
    } catch (error) {
      ctx.notify?.(error.message || String(error), true);
    } finally {
      busy = false;
      updateDirty();
    }
  }
  for (const input of [urlInput, pythonInput, comfyInput, argsInput])
    input.addEventListener('input', updateDirty);
  form.addEventListener('submit', save);
  discardButton.onclick = () => {
    if (config) putFields(config);
  };
  checkButton.onclick = fetchStatus;
  startButton.onclick = () => control('start');
  stopButton.onclick = () => control('stop');
  restartButton.onclick = () => control('restart');

  async function enter() {
    active = true;
    await Promise.all([
      loadConfig(),
      fetchStatus(),
      loadReview(),
      loadGpu(),
      sections.load().catch((error) => ctx.notify(error.message, true)),
    ]);
    clearInterval(timer);
    timer = setInterval(() => {
      if (active && !document.hidden) {
        fetchStatus();
        loadGpu();
      }
    }, 5000);
  }
  function leave() {
    active = false;
    statusSequence++;
    clearInterval(timer);
    timer = null;
  }
  return {element: root, enter, leave};
}
