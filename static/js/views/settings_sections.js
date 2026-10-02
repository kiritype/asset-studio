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
const found = (ok, yes = t('settings.found'), no = t('common.missing')) =>
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
  ['auto', t('settings.follow_the_browser_language')],
  ['ko', t('settings.korean')],
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
    const save = el('button', 's-button s-primary', t('common.save'));
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
    parts.message.textContent = t('settings.saving');
    try {
      const result = await ctx.api('/api/settings/save', {section, values});
      data[section] = {values: result.values, status: result.status};
      parts.message.textContent = t('common.saved');
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

  const general = card(t('common.general'), t('settings.language_theme_and_prompt_input_help'));
  function renderGeneral() {
    const v = data.ui.values;
    const language = select(LANGUAGE_CHOICES, v.language);
    const theme = select(
      [
        ['system', t('settings.follow_the_system')],
        ['light', t('settings.light')],
        ['dark', t('settings.dark')],
      ],
      v.theme,
    );
    const autocomplete = input('checkbox', v.autocomplete);
    general.body.replaceChildren(
      field(t('settings.language'), language),
      field(t('settings.theme'), theme),
      check(
        autocomplete,
        t('settings.danbooru_tag_autocomplete'),
        t('settings.suggests_tags_while_you_type_a'),
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

  const lora = card(t('settings.lora_training'), t('settings.where_the_trainer_anima_lora_is'));
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
    const findLoraDir = el('button', 's-button', t('settings.find_in_comfyui'));
    findLoraDir.type = 'button';
    findLoraDir.addEventListener('click', async () => {
      try {
        const {lora_dir: suggested} = await ctx.api('/api/comfy/locate');
        if (!suggested) return ctx.notify(t('settings.comfyui_must_be_running_to_find'), true);
        loraDir.value = suggested;
        ctx.notify(t('settings.the_lora_folder_is_filled_in'));
      } catch (error) {
        ctx.notify(error.message, true);
      }
    });
    const bases = {};
    const baseBlocks = [];
    for (const [ident, title, hint] of [
      [
        'official',
        t('settings.official_anima_base'),
        'anima-base-v1.0, qwen_3_06b_base, qwen_image_vae',
      ],
      [
        'generation',
        t('settings.generation_model_optional'),
        t('settings.to_train_on_the_anima_fine'),
      ],
    ]) {
      const paths = v.bases?.[ident] || {};
      const okay = s.paths_found?.[ident] || {};
      bases[ident] = {};
      const block = el('fieldset', 's-fieldset');
      block.append(el('legend', '', title), el('small', 's-muted', hint));
      for (const [key, label] of [
        ['dit', t('settings.diffusion_model')],
        ['text_encoder', t('common.text_encoder')],
        ['vae', 'VAE'],
      ]) {
        const control = input('text', paths[key] || '', {
          placeholder: t('settings.path_to_a_safetensors_file'),
        });
        bases[ident][key] = control;
        block.append(field(label, row(control, okay[key])));
      }
      baseBlocks.push(block);
    }
    lora.body.replaceChildren(
      field(
        t('settings.trainer_folder'),
        row(trainer, s.trainer_found),
        t('settings.a_path_relative_to_the_asset'),
      ),
      field(
        t('settings.trainer_python'),
        row(python, s.python_found),
        t('settings.relative_to_the_trainer_folder'),
      ),
      field(
        t('settings.lora_output_folder'),
        row(loraDir, s.lora_dir_found, findLoraDir),
        t('settings.finished_epochs_are_copied_to_this'),
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
    t('settings.danbooru_tag_data'),
    t('settings.used_for_tag_autocomplete_and_tag'),
  );
  function renderTags() {
    const {values: v, status: s} = data.tags;
    const folder = input('text', v.danbooru_dir || '', {
      placeholder: t('settings.leave_empty_to_find_it_automatically'),
    });
    tags.body.replaceChildren(
      field(
        t('settings.tag_file_folder'),
        folder,
        t('settings.folder_that_contains_danbooru_2025_09'),
      ),
      el(
        'p',
        s.available ? 's-ok' : 's-missing',
        s.available ? t('settings.in_use_2', [s.folder]) : t('settings.tag_data_not_found'),
      ),
    );
    tags.save.onclick = () => store('tags', {danbooru_dir: folder.value}, tags);
  }

  // ---- GPU waiting -------------------------------------------------------------------

  const gpuWait = card(
    t('settings.gpu_wait_rules'),
    t('settings.while_another_program_uses_the_gpu'),
  );
  function renderGpu() {
    const v = data.gpu.values;
    const enabled = input('checkbox', v.enabled);
    const limits = {};
    const grid = el('div', 's-grid4');
    for (const [kind, label] of [
      ['generation', t('common.image_generation')],
      ['tool', t('common.image_tools')],
      ['vlm', t('settings.vlm_review')],
      ['training', t('settings.lora_training')],
    ]) {
      limits[kind] = input('number', v.min_free_vram_mb?.[kind] ?? 0, {min: 0, step: 256});
      grid.append(field(`${label} (MB)`, limits[kind]));
    }
    const processes = textarea(lines(v.watch_processes), 3);
    processes.placeholder = t('settings.e_g_blender_exe');
    gpuWait.body.replaceChildren(
      check(enabled, t('settings.use_gpu_wait_rules')),
      el('small', 's-muted', t('settings.minimum_free_vram_needed_to_start')),
      grid,
      field(
        t('settings.wait_while_these_programs_run'),
        processes,
        t('settings.one_executable_name_per_line'),
      ),
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

  const vlm = card(t('settings.vlm_server'), t('settings.the_local_vision_model_server_for'));
  function renderVlm() {
    const {values: v, status: s} = data.vlm;
    const enabled = input('checkbox', v.enabled);
    const url = input('text', v.url, {placeholder: 'http://127.0.0.1:1234'});
    const model = input('text', v.model, {placeholder: t('settings.model_identifier')});
    const keyEnv = input('text', v.api_key_env, {
      placeholder: t('settings.optional_name_of_the_environment_variable'),
    });
    const load = textarea(lines(v.load_command));
    const unload = textarea(lines(v.unload_command));
    const status = textarea(lines(v.status_command));
    const marker = input('text', v.loaded_marker, {
      placeholder: t('settings.loaded_when_the_status_output_contains'),
    });
    const commandTimeout = input('number', v.command_timeout_seconds, {min: 5, max: 3600});
    const requestTimeout = input('number', v.request_timeout_seconds, {min: 5, max: 3600});
    vlm.body.replaceChildren(
      check(enabled, t('settings.use_the_vlm_server')),
      el(
        'p',
        s.configured ? 's-ok' : 's-missing',
        s.configured
          ? t('settings.settings_are_valid')
          : tr(s.error) || t('settings.not_set_up_yet'),
      ),
      field(t('settings.address'), url, t('settings.only_an_http_address_on_this')),
      field(t('common.model'), model),
      field(t('settings.api_key_environment_variable'), keyEnv),
      field(t('settings.load_command'), load, t('settings.the_executable_and_each_argument_on')),
      field(t('settings.unload_command'), unload),
      field(t('settings.status_command'), status),
      field(t('settings.loaded_marker'), marker),
      field(t('settings.command_timeout_s'), commandTimeout),
      field(t('settings.request_timeout_s'), requestTimeout),
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
