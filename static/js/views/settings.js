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
    element('h1', '', t('설정')),
    element('p', '', t('화면, ComfyUI 연결, 학습, GPU, 검수 설정을 관리합니다.')),
  );
  root.append(heading);

  const statusCard = element('section', 's-card');
  const statusHead = element('div', 's-card-head');
  const statusTitle = element('div');
  statusTitle.append(element('h2', '', t('연결 상태')));
  const checkButton = element('button', 's-button', t('연결 확인'));
  checkButton.type = 'button';
  statusHead.append(statusTitle, checkButton);
  const statusLine = element('div', 's-status-line');
  const statusDot = element('span', 's-dot');
  const statusText = element('strong', '', t('확인 중…'));
  const ownership = element('span', 's-tag', '');
  statusLine.append(statusDot, statusText, ownership);
  const statusDetail = element('p', 's-muted');
  const stats = element('div', 's-stats');
  const controlRow = element('div', 's-control-row');
  const startButton = element('button', 's-button s-primary', t('ComfyUI 시작'));
  startButton.type = 'button';
  const stopButton = element('button', 's-button', t('종료'));
  stopButton.type = 'button';
  const restartButton = element('button', 's-button', t('재시작'));
  restartButton.type = 'button';
  for (const button of [startButton, stopButton, restartButton]) button.disabled = true;
  controlRow.append(startButton, stopButton, restartButton);
  const controlHint = element(
    'p',
    's-muted',
    t(
      '이 앱에서 시작한 ComfyUI만 제어할 수 있습니다. 종료와 재시작은 현재 이미지 작업이 끝날 때까지 기다립니다. 작업 대기열의 일시 정지 설정은 바뀌지 않습니다.',
    ),
  );
  statusCard.append(statusHead, statusLine, statusDetail, stats, controlRow, controlHint);

  const configCard = element('section', 's-card');
  const configHead = element('div', 's-card-head');
  configHead.append(element('div', '', ''));
  configHead.firstChild.append(
    element('h2', '', t('ComfyUI 연결 정보')),
    element('p', 's-muted', t('로컬 서버 주소와 실행 경로를 입력한 뒤 저장하세요.')),
  );
  const dirtyTag = element('span', 's-tag s-dirty', t('저장하지 않은 변경 사항'));
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
    t('로컬 ComfyUI 주소'),
    t('http://127.0.0.1:8188 형식의 로컬 주소'),
    'settings-comfy-url',
  );
  urlInput.type = 'url';
  urlInput.required = true;
  const pythonInput = makeField(
    t('Python 실행 파일'),
    t('ComfyUI 가상 환경의 python.exe 전체 경로'),
    'settings-python-path',
  );
  pythonInput.required = true;
  const comfyInput = makeField(
    t('ComfyUI 폴더'),
    t('main.py가 있는 폴더 전체 경로'),
    'settings-comfy-path',
  );
  comfyInput.required = true;
  const argsInput = makeField(
    t('실행 인자 · JSON 배열'),
    t('예: ["--preview-method", "auto"]'),
    'settings-comfy-arguments',
    'textarea',
  );
  argsInput.rows = 5;
  argsInput.spellcheck = false;
  const formActions = element('div', 's-form-actions');
  // Finds installed ComfyUIs; picking one only fills the form, saving stays explicit.
  const locateButton = element('button', 's-button', t('자동으로 찾기'));
  locateButton.type = 'button';
  const locateBox = element('div', 's-locate');
  const KIND_LABELS = {
    portable: t('ComfyUI 포터블'),
    stability_matrix: 'Stability Matrix',
    desktop: t('ComfyUI 데스크톱 앱'),
    venv: t('git 설치 (venv)'),
    unknown: t('알 수 없음'),
  };
  locateButton.addEventListener('click', async () => {
    locateButton.disabled = true;
    locateBox.replaceChildren(element('p', 's-muted', t('찾는 중…')));
    try {
      const {candidates} = await ctx.api('/api/comfy/locate');
      if (!candidates.length) {
        locateBox.replaceChildren(
          element('p', 's-muted', t('ComfyUI를 찾지 못했습니다. 경로를 직접 입력하세요.')),
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
                found.source === 'running' ? t('실행 중 · {0}', [found.version || '?']) : '',
                found.python_path || t('Python을 찾지 못함'),
              ]
                .filter(Boolean)
                .join(' · '),
            ),
          );
          const use = element('button', 's-button', t('이 설치 사용'));
          use.type = 'button';
          use.disabled = preview || !found.python_path;
          use.addEventListener('click', () => {
            putFields({
              ...fields(),
              comfy_path: found.comfy_path,
              python_path: found.python_path,
              ...(found.arguments ? {arguments: found.arguments} : {}),
            });
            ctx.notify?.(t('입력란을 채웠습니다. 확인한 뒤 저장하세요.'));
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
  const discardButton = element('button', 's-button', t('변경 취소'));
  discardButton.type = 'button';
  const saveButton = element('button', 's-button s-primary', t('설정 저장'));
  saveButton.type = 'submit';
  discardButton.disabled = true;
  saveButton.disabled = true;
  for (const input of [urlInput, pythonInput, comfyInput, argsInput]) input.disabled = true;
  formActions.append(locateButton, discardButton, saveButton);
  form.append(formActions, locateBox);
  const configHint = element(
    'p',
    's-muted',
    t(
      '설정을 저장하면 새 주소로 연결을 확인합니다. 관리 중인 ComfyUI나 실행 중인 작업이 있다면 작업을 마친 뒤 저장할 수 있습니다.',
    ),
  );
  configCard.append(configHead, form, configHint);
  const reviewCard = element('section', 's-card');
  const reviewHead = element('div', 's-card-head');
  const reviewTitle = element('div');
  reviewTitle.append(
    element('h2', '', t('VLM 검증')),
    element(
      'p',
      's-muted',
      t(
        '생성한 이미지를 로컬 VLM이 프롬프트와 비교해 참고 판정을 남기고, 실패하면 새 시드로 다시 생성합니다. 최종 판정은 언제나 사람이 합니다.',
      ),
    ),
  );
  const vlmCheck = element('button', 's-button', t('VLM 연결 시험'));
  vlmCheck.type = 'button';
  reviewHead.append(reviewTitle, vlmCheck);
  const vlmStatus = element('p', 's-review-status', t('VLM 설정 확인 중…'));
  vlmStatus.setAttribute('role', 'status');
  const vlmHint = element(
    'p',
    's-muted',
    t(
      'VLM 서버는 위의 "VLM 서버"에서 설정합니다. VLM 판정은 참고 정보이며 최종 채택은 사람의 검수로 결정됩니다.',
    ),
  );
  const vlmPath = element('p', 's-muted');
  const reviewForm = element('form', 's-review-form');
  const enabledLabel = element('label', 's-review-check');
  const enabledInput = element('input');
  enabledInput.type = 'checkbox';
  enabledInput.disabled = true;
  enabledLabel.append(enabledInput, element('span', '', t('VLM 검증 사용')));
  const enabledHint = element(
    'p',
    's-muted',
    t(
      '끄면 생성 후 자동 검증과 자동 재생성을 하지 않고, 갤러리의 VLM 필터·표시·회차 목록도 숨깁니다. 이미 남은 VLM 판정은 이미지 상세에서 볼 수 있고, 새 시드 재생성은 그대로 쓸 수 있습니다. 바꾸면 바로 저장됩니다.',
    ),
  );
  const maxLabel = element('label', 's-field');
  maxLabel.append(element('span', 's-label', t('최대 자동 재생성 횟수')));
  const maxInput = element('input');
  maxInput.type = 'number';
  maxInput.min = '0';
  maxInput.max = '100';
  maxInput.step = '1';
  maxInput.value = '10';
  maxInput.disabled = true;
  maxLabel.append(
    maxInput,
    element(
      'small',
      's-muted',
      t(
        '기본값 10회. 최초 생성은 제외하며 새 시드 수동 재생성은 별도 라운드로 시작합니다. 변경한 한도는 새 라운드부터 적용됩니다.',
      ),
    ),
  );
  const reviewSave = element('button', 's-button s-primary', t('재생성 횟수 저장'));
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
    element('h2', '', t('GPU 사용')),
    element(
      'p',
      's-muted',
      t(
        '이미지 생성, VLM 검증, LoRA 학습은 GPU를 하나씩 차례로 씁니다. 다른 작업이 GPU를 쓰는 동안 대기 중인 생성은 시작하지 않습니다.',
      ),
    ),
  );
  const gpuRelease = element('button', 's-button', t('외부 예약 해제'));
  gpuRelease.type = 'button';
  gpuRelease.hidden = true;
  gpuHead.append(gpuTitle, gpuRelease);
  const gpuLine = element('p', 's-review-status', t('GPU 상태 확인 중…'));
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
      ? t('사용 중: {0}{1}', [tr(gpu.label), gpu.state_label ? ` · ${tr(gpu.state_label)}` : ''])
      : t('사용 중: 이미지 생성{0}', [
          gpu.running_jobs ? t(' · {0}장 진행 중', [gpu.running_jobs]) : '',
        ]);
    const since = gpu.since ? new Date(gpu.since).toLocaleString(locale) : '';
    const vram = gpu.vram_total_mb
      ? t('남은 GPU 메모리: {0} / {1} GB', [
          (gpu.vram_free_mb / 1024).toFixed(1),
          (gpu.vram_total_mb / 1024).toFixed(1),
        ])
      : '';
    gpuDetail.textContent = [
      gpu.waiting ? t('대기 이유: {0}', [gpu.waiting.reason]) : '',
      vram,
      since ? t('시작: {0}', [since]) : '',
      gpu.error ? t('오류: {0}', [gpu.error]) : '',
      gpu.holder ? t('이 작업이 끝날 때까지 대기 중인 생성은 시작하지 않습니다.') : '',
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
      gpuLine.textContent = t('GPU 상태를 불러올 수 없습니다: {0}', [error.message || error]);
    }
  }
  gpuRelease.onclick = async () => {
    if (
      !window.confirm(
        t(
          '{0}의 GPU 예약을 해제할까요?\n그 작업이 아직 GPU를 쓰고 있다면 생성과 겹칠 수 있습니다.',
          [gpu?.label || t('외부 작업')],
        ),
      )
    )
      return;
    try {
      gpu = await ctx.api('/api/gpu/release', {force: true});
      renderGpu();
      ctx.notify?.(t('GPU 예약을 해제했습니다.'));
    } catch (error) {
      ctx.notify?.(error.message || String(error), true);
    }
  };

  function renderReview() {
    const configured = Boolean(vlmConfig?.configured);
    const stateNames = {idle: t('준비됨'), error: t('오류')};
    const state = !configured
      ? t('연결 정보가 없어 켤 수 없음')
      : stateNames[vlmConfig?.status] || vlmConfig?.status || t('설정됨');
    const usage = reviewConfig?.enabled ? t('사용 중') : t('꺼짐');
    vlmStatus.textContent =
      vlmTestMessage ||
      t('VLM 검증: {0} · 연결: {1}{2}', [
        usage,
        state,
        vlmConfig?.error ? ` · ${vlmConfig.error}` : '',
      ]);
    maxLabel.hidden = !enabledInput.checked;
    reviewSave.hidden = !enabledInput.checked;
    vlmPath.textContent = vlmConfig?.config_path
      ? t('설정 파일: {0}', [vlmConfig.config_path])
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
      reviewMessage.textContent = t('검수 설정을 불러올 수 없습니다: {0}', [
        settingsResult.reason.message || settingsResult.reason,
      ]);
    if (vlmResult.status === 'fulfilled') vlmConfig = vlmResult.value;
    else
      vlmConfig = {
        configured: false,
        status: t('상태 확인 실패'),
        error: vlmResult.reason.message || String(vlmResult.reason),
      };
    renderReview();
  }
  async function saveReview(event) {
    event?.preventDefault();
    const limit = Number(maxInput.value);
    if (reviewBusy || !Number.isInteger(limit) || limit < 0 || limit > 100) {
      reviewMessage.textContent = t('자동 재생성 횟수는 0~100 사이의 정수여야 합니다.');
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
        ? t('VLM 검증을 켰습니다.')
        : t('VLM 검증을 껐습니다. 갤러리의 VLM 표시도 숨깁니다.');
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
    vlmTestMessage = t('VLM 연결 시험 중…');
    renderReview();
    try {
      const result = await ctx.api('/api/vlm/test', {});
      vlmTestMessage = result.loaded
        ? t('VLM 모델 로드됨')
        : result.configured
          ? t('VLM 설정 확인됨 · 모델 미로드')
          : t('VLM 설정되지 않음');
      if (result.error) vlmTestMessage += ` · ${tr(result.error)}`;
    } catch (error) {
      vlmTestMessage = t('VLM 연결 시험 실패 · {0}', [error.message || error]);
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
      const gpu = device.name || device.type || t('장치');
      const memory = readableBytes(device.vram_total);
      entries.push(['GPU', memory ? `${gpu} · ${memory}` : gpu]);
    }
    entries.push([t('실행 중'), payload.running ?? 0], [t('대기 중'), payload.pending ?? 0]);
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
      ? {start: t('시작 중'), stop: t('종료 대기 중'), restart: t('재시작 대기 중')}[
          status.operation
        ] || t('처리 중')
      : status.connected
        ? t('연결됨')
        : t('연결되지 않음');
    ownership.textContent = status.owned
      ? t('이 앱에서 실행')
      : status.connected
        ? t('외부 프로세스')
        : t('실행 정보 없음');
    statusDetail.textContent = status.error
      ? t('상태: {0}', [tr(status.error)])
      : t('주소: {0}', [status.url || config?.url || '—']);
    controlRow.hidden = preview || Boolean(status.preview);
    startButton.disabled = busy || !status.can_start;
    stopButton.disabled = busy || !status.can_stop;
    restartButton.disabled = busy || !status.can_restart;
    controlHint.textContent =
      status.connected && !status.owned
        ? t('Stability Matrix 등 외부에서 실행한 ComfyUI는 해당 앱에서 관리하세요.')
        : t(
            '이 앱에서 시작한 ComfyUI만 제어할 수 있습니다. 종료와 재시작은 현재 이미지 작업이 끝날 때까지 기다립니다. 작업 대기열의 일시 정지 설정은 바뀌지 않습니다.',
          );
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
    if (
      action === 'stop' &&
      !window.confirm(t('현재 이미지 작업이 끝나면 이 앱에서 실행한 ComfyUI를 종료할까요?'))
    )
      return;
    if (
      action === 'restart' &&
      !window.confirm(t('현재 이미지 작업이 끝나면 이 앱에서 실행한 ComfyUI를 재시작할까요?'))
    )
      return;
    busy = true;
    renderStatus();
    try {
      await ctx.api('/api/connection/control', {action});
      ctx.notify?.(
        action === 'start'
          ? t('ComfyUI 시작을 요청했습니다.')
          : action === 'stop'
            ? t('현재 작업이 끝나면 종료합니다.')
            : t('현재 작업이 끝나면 재시작합니다.'),
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
      ctx.notify?.(t('실행 인자는 문자열로 이루어진 JSON 배열이어야 합니다.'), true);
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
      ctx.notify?.(t('연결 설정을 저장했습니다.'));
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
