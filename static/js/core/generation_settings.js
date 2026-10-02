// Generation settings form shared by the jobs and single-image menus.
// Tabs pick the model family: Anima (diffusion model + text encoder + VAE) or
// SDXL (one checkpoint with its own text encoder and VAE).

import {t, tr} from '../core/i18n.js';
export const FAMILY_LABELS = {anima: 'Anima', sdxl: 'SDXL·IL'};
// Starting values when switching to a family; models and samplers are picked from what exists.
const FAMILY_DEFAULTS = {
  anima: {steps: 32, cfg: 5, width: 1536, height: 1536, sampler: 'er_sde', scheduler: 'simple'},
  sdxl: {
    steps: 28,
    cfg: 5,
    width: 1024,
    height: 1024,
    clip_skip: 2,
    sampler: 'euler_ancestral',
    scheduler: 'normal',
  },
};
const NUMBERS = [
  ['steps', 'Steps', 1, 100, 1],
  ['cfg', 'CFG', 0, 30, 0.1],
  ['width', t('가로'), 256, 3072, 16],
  ['height', t('세로'), 256, 3072, 16],
  ['seed', t('시드'), -1, 4294967295, 1],
];
const arr = (value) => (Array.isArray(value) ? value : []);
const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const field = (text, control, hint) => {
  const n = el('label', 'gs-field');
  n.append(el('span', '', text), control);
  if (hint) n.append(el('small', '', hint));
  return n;
};
const choose = (choices, value) => {
  const n = el('select');
  for (const [key, text] of choices) {
    const option = el('option', '', text);
    option.value = key;
    n.append(option);
  }
  n.value = value ?? '';
  return n;
};
const number = (value, min, max, step) => {
  const n = el('input');
  n.type = 'number';
  n.value = value ?? '';
  n.min = String(min);
  n.max = String(max);
  n.step = String(step);
  return n;
};

/** Family of a catalog entry, or null when it could not be told. */
export function familyOf(comfy, key, name) {
  return comfy?.families?.[key]?.[name] ?? null;
}

/** Entries of one list that fit a family; files of unknown family fit both. */
export function entriesFor(comfy, key, family) {
  return arr(comfy?.[key]).filter((name) => {
    // An SDXL graph loads a whole checkpoint; diffusion-model files cannot be used there.
    if (key === 'models' && family === 'sdxl' && !name.startsWith('checkpoint::')) return false;
    const found = familyOf(comfy, key, name);
    return !found || found === family;
  });
}

/** Settings after switching family: keep what still fits, fill the rest with defaults. */
export function switchFamily(comfy, settings, family) {
  const next = {...settings, family, ...FAMILY_DEFAULTS[family], seed: settings.seed ?? -1};
  const pick = (key, list, ...preferred) => {
    const options = entriesFor(comfy, list, family);
    if (options.includes(settings[key])) return settings[key];
    for (const name of preferred) {
      const found = options.find((option) => option.endsWith(name));
      if (found) return found;
    }
    return options[0] || '';
  };
  next.model = pick(
    'model',
    'models',
    ...(family === 'anima'
      ? ['anima-aesthetic-v1.1.safetensors', 'anima_aestheticV11.safetensors']
      : ['waiIllustriousSDXL_v170.safetensors']),
  );
  next.sampler = arr(comfy?.samplers).includes(next.sampler)
    ? next.sampler
    : arr(comfy?.samplers)[0];
  next.scheduler = arr(comfy?.schedulers).includes(next.scheduler)
    ? next.scheduler
    : arr(comfy?.schedulers)[0];
  if (family === 'anima') {
    next.text_encoder = pick('text_encoder', 'text_encoders', 'qwen_3_06b_base.safetensors');
    next.vae = pick('vae', 'vaes', 'qwen_image_vae.safetensors');
    next.clip_type = settings.clip_type || 'stable_diffusion';
    delete next.clip_skip;
  } else {
    next.vae = '';
    for (const key of ['text_encoder', 'clip_type', 'text_encoder_device']) delete next[key];
  }
  // LoRAs of the other family would not load; drop them rather than fail at generation.
  next.loras = arr(settings.loras).filter((lora) => {
    const found = familyOf(comfy, 'loras', lora.name);
    return !found || found === family;
  });
  return next;
}

/**
 * Render the form into ``container``. ``onChange(settings, {structural})`` receives a
 * new settings object; ``structural`` is true when the form must be drawn again.
 */
export function renderGenerationSettings(container, {comfy, settings, onChange, disabled}) {
  const family = settings.family || 'anima';
  // Build on the latest values: several fields can change before the form is drawn again.
  let current = settings;
  const update = (changes, structural = false) => {
    current = {...current, ...changes};
    onChange(current, structural);
  };
  container.replaceChildren();
  const tabs = el('div', 'gs-tabs');
  tabs.setAttribute('role', 'tablist');
  for (const [key, text] of Object.entries(FAMILY_LABELS)) {
    const tab = el('button', 'gs-tab', text);
    tab.type = 'button';
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-selected', String(key === family));
    tab.disabled = !!disabled;
    tab.addEventListener('click', () => {
      if (key !== family) onChange(switchFamily(comfy, settings, key), true);
    });
    tabs.append(tab);
  }
  container.append(tabs);
  const grid = el('div', 'gs-grid');
  const list = (key, title, listKey, {optional, hint} = {}) => {
    const options = entriesFor(comfy, listKey, family);
    const choices = options.map((value) => [
      value,
      listKey === 'models' ? tr(comfy?.model_entries?.[value]?.label || value) : value,
    ]);
    if (settings[key] && !options.includes(settings[key]))
      choices.unshift([settings[key], t('{0} · 목록에 없음', [settings[key]])]);
    const control = choose(
      [['', optional ? t('체크포인트 내장') : t('선택하세요')], ...choices],
      settings[key],
    );
    control.disabled = !!disabled;
    control.addEventListener('change', () => update({[key]: control.value}));
    grid.append(field(title, control, hint));
  };
  list('model', family === 'sdxl' ? t('체크포인트') : t('모델'), 'models');
  if (family === 'anima') {
    list('text_encoder', t('텍스트 인코더'), 'text_encoders');
    list('vae', 'VAE', 'vaes');
    list('clip_type', t('CLIP 유형'), 'clip_types');
  } else {
    list('vae', 'VAE', 'vaes', {optional: true, hint: t('비우면 체크포인트의 VAE를 씁니다.')});
    const skip = number(settings.clip_skip ?? 2, 1, 12, 1);
    skip.disabled = !!disabled;
    skip.addEventListener('input', () => update({clip_skip: Number(skip.value)}));
    grid.append(field('CLIP skip', skip, t('IL·Pony 계열은 보통 2')));
  }
  list('sampler', t('샘플러'), 'samplers');
  list('scheduler', t('스케줄러'), 'schedulers');
  for (const [key, title, min, max, step] of NUMBERS) {
    const control = number(settings[key], min, max, step);
    control.disabled = !!disabled;
    control.addEventListener('input', () => update({[key]: Number(control.value)}));
    grid.append(field(title, control));
  }
  container.append(grid);

  const loraHead = el('div', 'gs-row');
  const add = el('button', 'gs-muted', '+ LoRA');
  add.type = 'button';
  add.disabled = !!disabled;
  add.addEventListener('click', () =>
    update(
      {loras: [...arr(current.loras), {name: '', strength_model: 1, strength_clip: 1}]},
      true,
    ),
  );
  loraHead.append(el('h3', '', 'LoRA'), add);
  container.append(loraHead);
  const loraOptions = entriesFor(comfy, 'loras', family);
  for (const [index, lora] of arr(settings.loras).entries()) {
    const row = el('div', 'gs-row gs-lora');
    const choices = loraOptions.map((name) => [name, name]);
    if (lora.name && !loraOptions.includes(lora.name))
      choices.unshift([lora.name, t('{0} · 이 계열 목록에 없음', [lora.name])]);
    const name = choose([['', t('선택하세요')], ...choices], lora.name);
    name.disabled = !!disabled;
    const replace = (changes) =>
      update({
        loras: current.loras.map((item, i) => (i === index ? {...item, ...changes} : item)),
      });
    name.addEventListener('change', () => replace({name: name.value}));
    row.append(field(t('파일'), name));
    for (const [key, title] of [
      ['strength_model', t('모델 강도')],
      ['strength_clip', t('CLIP 강도')],
    ]) {
      const control = number(lora[key] ?? 1, -10, 10, 0.05);
      control.disabled = !!disabled;
      control.addEventListener('input', () => replace({[key]: Number(control.value)}));
      row.append(field(title, control));
    }
    const remove = el('button', 'gs-danger', t('제거'));
    remove.type = 'button';
    remove.disabled = !!disabled;
    remove.addEventListener('click', () =>
      update({loras: current.loras.filter((_, i) => i !== index)}, true),
    );
    row.append(remove);
    container.append(row);
  }
}
