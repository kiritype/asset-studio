// Settings sections stored in data/settings/ through /api/settings: interface, LoRA
// training, tag data, GPU waiting rules and the VLM server. Each card saves on its own.

import {setPreferences} from '../core/preferences.js';
import {t, tr} from '../core/i18n.js';

const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
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
  n.value = value;
  return n;
};
const field = (label, control, hint) => {
  const n = el('label', 's-form-field');
  n.append(el('span', '', label), control);
  if (hint) n.append(el('small', 's-muted', hint));
  return n;
};
const check = (control, label, hint) => {
  const n = el('label', 's-check-line');
  n.append(control, el('span', '', label));
  if (hint) n.title = hint;
  return n;
};
const found = (ok, yes = t('찾음'), no = t('없음')) =>
  el('small', ok ? 's-ok' : 's-missing', ok ? yes : no);
const lines = (list) => (Array.isArray(list) ? list.join('\n') : '');
const textarea = (value, rows = 3) => {
  const n = el('textarea');
  n.rows = rows;
  n.value = value;
  n.spellcheck = false;
  return n;
};

export const LANGUAGE_CHOICES = [
  ['auto', t('브라우저 언어 따르기')],
  ['ko', t('한국어')],
  ['en', 'English'],
  ['ja', '日本語'],
  ['zh-CN', '简体中文'],
];

export function createSettingsSections(ctx, {onVlmSaved} = {}) {
  let data = null;

  function card(title, description) {
    const box = el('section', 's-card');
    const head = el('div', 's-card-head');
    const text = el('div');
    text.append(el('h2', '', title));
    if (description) text.append(el('p', 's-muted', description));
    head.append(text);
    const body = el('div', 's-section-form');
    const actions = el('div', 's-control-row');
    const save = el('button', 's-button s-primary', t('저장'));
    save.type = 'button';
    save.disabled = !!ctx.preview;
    const message = el('p', 's-muted');
    message.setAttribute('role', 'status');
    actions.append(save, message);
    box.append(head, body, actions);
    return {box, body, save, message};
  }

  async function store(section, values, parts, after) {
    parts.save.disabled = true;
    parts.message.textContent = t('저장 중…');
    try {
      const result = await ctx.api('/api/settings/save', {section, values});
      data[section] = {values: result.values, status: result.status};
      parts.message.textContent = t('저장했습니다.');
      after?.(result);
      render();
    } catch (error) {
      parts.message.textContent = error.message;
      ctx.notify(error.message, true);
    } finally {
      parts.save.disabled = !!ctx.preview;
    }
  }

  // ---- interface ---------------------------------------------------------------------

  const general = card(
    t('일반'),
    t('화면 언어, 테마, 프롬프트 입력 도우미. 이 PC의 모든 브라우저에 적용됩니다.'),
  );
  function renderGeneral() {
    const v = data.ui.values;
    const language = select(LANGUAGE_CHOICES, v.language);
    const theme = select(
      [
        ['system', t('시스템 설정 따르기')],
        ['light', t('라이트')],
        ['dark', t('다크')],
      ],
      v.theme,
    );
    const autocomplete = input('checkbox', v.autocomplete);
    general.body.replaceChildren(
      field(t('언어'), language),
      field(t('테마'), theme),
      check(
        autocomplete,
        t('Danbooru 태그 자동완성'),
        t('프롬프트를 입력할 때 태그 후보를 보여 줍니다.'),
      ),
    );
    general.save.onclick = () =>
      store(
        'ui',
        {language: language.value, theme: theme.value, autocomplete: autocomplete.checked},
        general,
        (result) => {
          const languageChanged = result.values.language !== v.language;
          setPreferences(result.values);
          if (languageChanged) location.reload();
        },
      );
  }

  // ---- LoRA training -----------------------------------------------------------------

  const lora = card(
    t('LoRA 학습'),
    t('학습 도구(anima_lora) 위치와 학습에 쓸 모델 파일. README의 "LoRA 학습" 준비를 먼저 하세요.'),
  );
  function renderLora() {
    const {values: v, status: s} = data.lora;
    const trainer = input('text', v.trainer_dir, {placeholder: 'vendor/anima_lora'});
    const python = input('text', v.trainer_python, {placeholder: '.venv/Scripts/python.exe'});
    const loraDir = input('text', v.lora_dir, {placeholder: 'C:/.../Models/Lora/anima'});
    const row = (control, ok, extra) => {
      const n = el('div', 's-inline');
      n.append(control, found(ok));
      if (extra) n.append(extra);
      return n;
    };
    // ComfyUI knows its LoRA folders (extra_model_paths.yaml included); suggest one.
    const findLoraDir = el('button', 's-button', t('ComfyUI에서 찾기'));
    findLoraDir.type = 'button';
    findLoraDir.addEventListener('click', async () => {
      try {
        const {lora_dir: suggested} = await ctx.api('/api/comfy/locate');
        if (!suggested)
          return ctx.notify(t('ComfyUI가 켜져 있어야 LoRA 폴더를 찾을 수 있습니다.'), true);
        loraDir.value = suggested;
        ctx.notify(t('LoRA 폴더를 채웠습니다. 확인한 뒤 저장하세요.'));
      } catch (error) {
        ctx.notify(error.message, true);
      }
    });
    const bases = {};
    const baseBlocks = [];
    for (const [ident, title, hint] of [
      ['official', t('공식 Anima base'), 'anima-base-v1.0, qwen_3_06b_base, qwen_image_vae'],
      ['generation', t('생성 모델 (선택)'), t('생성에 쓰는 Anima 파인튜닝 모델로 학습할 때')],
    ]) {
      const paths = v.bases?.[ident] || {};
      const okay = s.paths_found?.[ident] || {};
      bases[ident] = {};
      const block = el('fieldset', 's-fieldset');
      block.append(el('legend', '', title), el('small', 's-muted', hint));
      for (const [key, label] of [
        ['dit', t('확산 모델')],
        ['text_encoder', t('텍스트 인코더')],
        ['vae', 'VAE'],
      ]) {
        const control = input('text', paths[key] || '', {placeholder: t('.safetensors 파일 경로')});
        bases[ident][key] = control;
        block.append(field(label, row(control, okay[key])));
      }
      baseBlocks.push(block);
    }
    lora.body.replaceChildren(
      field(
        t('학습 도구 폴더'),
        row(trainer, s.trainer_found),
        t('Asset Studio 폴더 기준 상대 경로도 됩니다.'),
      ),
      field(t('학습 도구 Python'), row(python, s.python_found), t('학습 도구 폴더 기준')),
      field(
        t('LoRA 저장 폴더'),
        row(loraDir, s.lora_dir_found, findLoraDir),
        t('끝난 에폭이 이 ComfyUI LoRA 폴더로 복사됩니다.'),
      ),
      ...baseBlocks,
    );
    lora.save.onclick = () => {
      const values = {
        trainer_dir: trainer.value,
        trainer_python: python.value,
        lora_dir: loraDir.value,
        bases: Object.fromEntries(
          Object.entries(bases).map(([ident, controls]) => [
            ident,
            Object.fromEntries(Object.entries(controls).map(([key, c]) => [key, c.value])),
          ]),
        ),
      };
      store('lora', values, lora);
    };
  }

  // ---- tag data ----------------------------------------------------------------------

  const tags = card(
    t('Danbooru 태그 데이터'),
    t(
      '태그 자동완성과 태그 확인에 씁니다. 비워 두면 ComfyUI 폴더의 ComfyUI-EasyUseAnima에서 찾습니다.',
    ),
  );
  function renderTags() {
    const {values: v, status: s} = data.tags;
    const folder = input('text', v.danbooru_dir || '', {placeholder: t('비우면 자동으로 찾음')});
    tags.body.replaceChildren(
      field(t('태그 파일 폴더'), folder, t('danbooru_2025-09-01.csv가 있는 폴더')),
      el(
        'p',
        s.available ? 's-ok' : 's-missing',
        s.available ? t('사용 중: {0}', [s.folder]) : t('태그 데이터를 찾지 못했습니다.'),
      ),
    );
    tags.save.onclick = () => store('tags', {danbooru_dir: folder.value}, tags);
  }

  // ---- GPU waiting -------------------------------------------------------------------

  const gpuWait = card(
    t('GPU 대기 조건'),
    t(
      '다른 프로그램이 GPU를 쓰고 있으면 작업을 시작하지 않고 기다립니다. nvidia-smi로 남은 VRAM을 확인합니다.',
    ),
  );
  function renderGpu() {
    const v = data.gpu.values;
    const enabled = input('checkbox', v.enabled);
    const limits = {};
    const grid = el('div', 's-grid4');
    for (const [kind, label] of [
      ['generation', t('이미지 생성')],
      ['tool', t('이미지 도구')],
      ['vlm', t('VLM 검수')],
      ['training', t('LoRA 학습')],
    ]) {
      limits[kind] = input('number', v.min_free_vram_mb?.[kind] ?? 0, {min: 0, step: 256});
      grid.append(field(`${label} (MB)`, limits[kind]));
    }
    const processes = textarea(lines(v.watch_processes), 3);
    processes.placeholder = t('예: blender.exe');
    gpuWait.body.replaceChildren(
      check(enabled, t('GPU 대기 조건 사용')),
      el('small', 's-muted', t('작업을 시작하는 데 필요한 최소 남은 VRAM')),
      grid,
      field(t('이 프로그램이 실행 중이면 기다림'), processes, t('한 줄에 실행 파일 이름 하나')),
    );
    gpuWait.save.onclick = () =>
      store(
        'gpu',
        {
          enabled: enabled.checked,
          min_free_vram_mb: Object.fromEntries(
            Object.entries(limits).map(([kind, c]) => [kind, Number(c.value) || 0]),
          ),
          watch_processes: processes.value,
        },
        gpuWait,
      );
  }

  // ---- VLM server --------------------------------------------------------------------

  const vlm = card(
    t('VLM 서버'),
    t(
      '자동 검수에 쓰는 로컬 비전 모델 서버(OpenAI 호환 API). 모델을 GPU에 올리고 내리는 명령도 적습니다.',
    ),
  );
  function renderVlm() {
    const {values: v, status: s} = data.vlm;
    const enabled = input('checkbox', v.enabled);
    const url = input('text', v.url, {placeholder: 'http://127.0.0.1:1234'});
    const model = input('text', v.model, {placeholder: t('모델 식별자')});
    const keyEnv = input('text', v.api_key_env, {
      placeholder: t('선택: API 키가 든 환경변수 이름'),
    });
    const load = textarea(lines(v.load_command));
    const unload = textarea(lines(v.unload_command));
    const status = textarea(lines(v.status_command));
    const marker = input('text', v.loaded_marker, {
      placeholder: t('상태 출력에 이 글자가 있으면 로드됨'),
    });
    const commandTimeout = input('number', v.command_timeout_seconds, {min: 5, max: 3600});
    const requestTimeout = input('number', v.request_timeout_seconds, {min: 5, max: 3600});
    vlm.body.replaceChildren(
      check(enabled, t('VLM 서버 사용')),
      el(
        'p',
        s.configured ? 's-ok' : 's-missing',
        s.configured ? t('설정이 올바릅니다.') : tr(s.error) || t('아직 설정되지 않았습니다.'),
      ),
      field(t('주소'), url, t('이 PC의 http 주소만 됩니다.')),
      field(t('모델'), model),
      field(t('API 키 환경변수'), keyEnv),
      field(t('모델 올리기 명령'), load, t('한 줄에 실행 파일과 인자를 하나씩')),
      field(t('모델 내리기 명령'), unload),
      field(t('상태 확인 명령'), status),
      field(t('로드 확인 문자열'), marker),
      field(t('명령 제한 시간(초)'), commandTimeout),
      field(t('요청 제한 시간(초)'), requestTimeout),
    );
    vlm.save.onclick = () =>
      store(
        'vlm',
        {
          enabled: enabled.checked,
          url: url.value,
          model: model.value,
          api_key_env: keyEnv.value,
          load_command: load.value,
          unload_command: unload.value,
          status_command: status.value,
          loaded_marker: marker.value,
          command_timeout_seconds: Number(commandTimeout.value),
          request_timeout_seconds: Number(requestTimeout.value),
        },
        vlm,
        () => onVlmSaved?.(),
      );
  }

  function render() {
    if (!data) return;
    renderGeneral();
    renderLora();
    renderTags();
    renderGpu();
    renderVlm();
  }

  async function load() {
    data = await ctx.api('/api/settings');
    render();
  }

  return {
    cards: {
      general: general.box,
      lora: lora.box,
      tags: tags.box,
      gpuWait: gpuWait.box,
      vlm: vlm.box,
    },
    load,
  };
}
