// LoRA menu: pick a character, choose training images, train, and register the results.
// Datasets and runs belong to one work/character; the registry decides what is applied.

import {visibleOutfitSets} from '../lib/library.js';
import {t, tr} from '../core/i18n.js';
import {withTagComplete} from '../core/tag_input.js';

const POLL_MS = 3000;
const ACTIVE = ['waiting_gpu', 'preprocessing', 'training'];
const RUN_LABELS = {
  waiting_gpu: t('GPU 대기'),
  preprocessing: t('전처리 중'),
  training: t('학습 중'),
  done: t('완료'),
  failed: t('실패'),
  cancelled: t('취소'),
  interrupted: t('중단'),
};
const FAMILY_LABELS = {anima: 'Anima', sdxl: 'SDXL·IL', shared: t('공용')};

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
  const n = el('label', 'lr-field');
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
const select = (choices, value) => {
  const n = el('select');
  for (const [key, text] of choices) {
    const option = el('option', '', text);
    option.value = key;
    n.append(option);
  }
  n.value = value ?? '';
  return n;
};
const arr = (value) => (Array.isArray(value) ? value : []);
const query = (values) => new URLSearchParams(values).toString();

export function createLora(ctx) {
  const root = el('section');
  root.id = 'app-lora';
  const state = {
    works: [],
    work: '',
    catalog: null,
    character: '',
    tab: 'dataset',
    datasets: [],
    runs: [],
    loras: [],
    options: null,
    dataset: '', // '' = a new dataset
    outfit: '',
    candidates: [],
    chosen: new Set(),
    draft: {name: '', character: '', outfit: ''},
    captions: {},
    train: null,
    timer: 0,
  };

  const header = el('header', 'lr-header');
  header.append(
    el('h1', '', 'LoRA'),
    el(
      'p',
      '',
      t('캐릭터별로 학습 이미지를 고르고 학습한 뒤, 결과를 등록해 생성에 자동으로 적용합니다.'),
    ),
  );
  const side = el('aside', 'lr-side');
  const main = el('div', 'lr-main');
  root.append(header, side, main);

  const who = () => ({work_id: state.work, character_id: state.character});
  const whoQuery = () => query({work: state.work, character: state.character});
  const character = () => arr(state.catalog?.characters).find((c) => c.id === state.character);
  const currentDataset = () => state.datasets.find((d) => d.id === state.dataset);
  const fail = (error) => ctx.notify(error.message || String(error), true);

  // ---- side: work and characters ------------------------------------------------------

  function renderSide() {
    const workSelect = select(
      state.works.map((w) => [w.id, `${w.id} · ${w.name || ''}`]),
      state.work,
    );
    workSelect.addEventListener('change', async () => {
      state.work = workSelect.value;
      state.character = '';
      await loadCatalog();
    });
    const list = el('div', 'lr-characters');
    for (const item of arr(state.catalog?.characters)) {
      const button = btn(`${item.id} ${item.name && item.name !== item.id ? item.name : ''}`, () =>
        chooseCharacter(item.id),
      );
      if (item.id === state.character) button.setAttribute('aria-current', 'true');
      list.append(button);
    }
    side.replaceChildren(field(t('작품'), workSelect), list);
  }

  async function chooseCharacter(id) {
    state.character = id;
    state.dataset = '';
    state.candidates = [];
    state.chosen.clear();
    state.captions = {};
    renderSide();
    await loadCharacter();
  }

  // ---- dataset tab --------------------------------------------------------------------

  async function loadCandidates() {
    if (!state.outfit) {
      state.candidates = [];
      return;
    }
    const result = await ctx.api(`/api/lora/candidates?${whoQuery()}&outfit=${state.outfit}`);
    state.candidates = arr(result.items);
  }
  async function chooseDataset(id) {
    state.dataset = id;
    state.captions = {};
    const dataset = currentDataset();
    if (dataset) {
      state.outfit = dataset.outfit_set_id;
      state.chosen = new Set(dataset.items.map((item) => item.path));
      state.draft = {
        name: dataset.name || '',
        character: dataset.triggers?.character || '',
        outfit: dataset.triggers?.outfit || '',
      };
    } else {
      state.outfit = state.outfit || character()?.default_outfit || '';
      state.draft = {name: '', character: '', outfit: ''};
      state.chosen = new Set();
    }
    await loadCandidates().catch(fail);
    // A new dataset starts from the images marked as adopted in the gallery.
    if (!dataset)
      for (const item of state.candidates) if (item.selected) state.chosen.add(item.path);
    renderMain();
  }
  async function saveDataset() {
    const triggers = {};
    if (state.draft.character.trim()) triggers.character = state.draft.character.trim();
    if (state.draft.outfit.trim()) triggers.outfit = state.draft.outfit.trim();
    const paths = state.candidates.filter((c) => state.chosen.has(c.path)).map((c) => c.path);
    try {
      const result = await ctx.api('/api/lora/datasets/save', {
        ...who(),
        id: state.dataset || undefined,
        outfit_set_id: state.outfit,
        name: state.draft.name.trim() || undefined,
        triggers: Object.keys(triggers).length ? triggers : undefined,
        paths,
      });
      ctx.notify(t('데이터셋 {0}을 저장했습니다 ({1}장).', [result.entity.id, paths.length]));
      await loadCharacter();
      await chooseDataset(result.entity.id);
    } catch (error) {
      fail(error);
    }
  }
  async function datasetRevision(id) {
    const address = query({kind: 'dataset', ...who(), id});
    return ctx.api(`/api/library/entity?${address}`);
  }
  async function saveCaptions() {
    const dataset = currentDataset();
    const edits = Object.entries(state.captions);
    if (!dataset || !edits.length) return;
    try {
      const latest = await datasetRevision(dataset.id);
      const items = latest.entity.items.map((item) =>
        item.path in state.captions
          ? {...item, caption: state.captions[item.path], caption_edited: true}
          : item,
      );
      await ctx.api('/api/library/save', {
        kind: 'dataset',
        ...who(),
        payload: {...latest.entity, items},
        expected_revision: latest.revision,
      });
      ctx.notify(
        t('캡션 {0}개를 저장했습니다. 직접 고친 캡션은 다시 만들 때도 유지됩니다.', [edits.length]),
      );
      state.captions = {};
      await loadCharacter();
      renderMain();
    } catch (error) {
      fail(error);
    }
  }
  async function recaption() {
    const dataset = currentDataset();
    if (!dataset) return;
    try {
      const latest = await datasetRevision(dataset.id);
      await ctx.api('/api/lora/datasets/captions', {
        ...who(),
        id: dataset.id,
        expected_revision: latest.revision,
      });
      ctx.notify(t('자동 캡션을 다시 만들었습니다. 직접 고친 캡션은 그대로입니다.'));
      await loadCharacter();
      renderMain();
    } catch (error) {
      fail(error);
    }
  }

  function datasetTab() {
    const box = el('div');
    const dataset = currentDataset();
    const chooser = select(
      [
        ['', t('+ 새 데이터셋')],
        ...state.datasets.map((d) => [
          d.id,
          t('{0} · {1} · {2}장', [d.id, d.name || '', d.items.length]),
        ]),
      ],
      state.dataset,
    );
    chooser.addEventListener('change', () => chooseDataset(chooser.value));
    const outfits = visibleOutfitSets(state.catalog, character()).map((o) => [
      o.id,
      `${o.id} · ${o.name || ''}`,
    ]);
    const outfit = select([['', t('의상 세트 선택')], ...outfits], state.outfit);
    outfit.disabled = !!dataset; // A dataset belongs to one outfit set.
    outfit.addEventListener('change', async () => {
      state.outfit = outfit.value;
      state.chosen.clear();
      await loadCandidates().catch(fail);
      for (const item of state.candidates) if (item.selected) state.chosen.add(item.path);
      renderMain();
    });
    const name = input('text', state.draft.name, {placeholder: t('예: 평상복 v3')});
    name.addEventListener('input', () => (state.draft.name = name.value));
    const triggerCharacter = input('text', state.draft.character, {
      placeholder: `${state.work}_${state.character}`.toLowerCase(),
    });
    triggerCharacter.addEventListener(
      'input',
      () => (state.draft.character = triggerCharacter.value),
    );
    const triggerOutfit = input('text', state.draft.outfit, {placeholder: t('비우면 넣지 않음')});
    triggerOutfit.addEventListener('input', () => (state.draft.outfit = triggerOutfit.value));
    const top = el('div', 'lr-grid2');
    top.append(
      field(t('데이터셋'), chooser),
      field(t('의상 세트'), outfit),
      field(t('이름'), name),
      field(t('캐릭터 트리거'), triggerCharacter, t('캡션 맨 앞쪽에 들어가는 이 캐릭터 전용 단어')),
      field(t('의상 트리거'), triggerOutfit, t('의상을 따로 배우게 할 때만')),
    );
    box.append(top);

    const tools = el('div', 'lr-row');
    const picked = state.candidates.filter((c) => state.chosen.has(c.path)).length;
    tools.append(
      el('strong', '', t('{0}/{1}장 선택', [picked, state.candidates.length])),
      btn(t('채택 이미지만'), () => {
        state.chosen = new Set(state.candidates.filter((c) => c.selected).map((c) => c.path));
        renderMain();
      }),
      btn(t('통과 이미지 전부'), () => {
        state.chosen = new Set(
          state.candidates.filter((c) => c.human_status === 'pass').map((c) => c.path),
        );
        renderMain();
      }),
      btn(t('선택 해제'), () => {
        state.chosen.clear();
        renderMain();
      }),
    );
    const save = btn(
      dataset ? t('데이터셋 고쳐 저장') : t('데이터셋 만들기'),
      saveDataset,
      'lr-primary',
    );
    save.disabled = !picked || !state.outfit || !!ctx.preview;
    tools.append(save);
    box.append(tools);

    const grid = el('div', 'lr-images');
    if (!state.outfit) grid.append(el('p', 'lr-muted', t('의상 세트를 고르세요.')));
    else if (!state.candidates.length)
      grid.append(el('p', 'lr-muted', t('이 의상 세트의 이미지가 없습니다.')));
    for (const item of state.candidates) {
      const card = el('label', 'lr-image');
      if (state.chosen.has(item.path)) card.classList.add('chosen');
      const check = input('checkbox', state.chosen.has(item.path));
      check.addEventListener('change', () => {
        if (check.checked) state.chosen.add(item.path);
        else state.chosen.delete(item.path);
        card.classList.toggle('chosen', check.checked);
        renderMain();
      });
      const image = el('img');
      image.src = item.thumbnail_url;
      image.alt = item.path;
      image.loading = 'lazy';
      const caption = el('div', 'lr-image-caption');
      caption.append(check, el('span', '', item.path.split('/').pop()));
      if (item.selected) caption.append(el('small', 'lr-badge lr-adopted', t('채택')));
      else if (item.human_status === 'pass') caption.append(el('small', 'lr-badge', t('통과')));
      else if (item.human_status === 'fail')
        caption.append(el('small', 'lr-badge lr-failed', t('실패')));
      card.title = item.path;
      card.append(image, caption);
      grid.append(card);
    }
    box.append(grid);

    if (dataset) {
      const head = el('div', 'lr-row lr-between');
      head.append(el('h3', '', t('캡션 · {0}장', [dataset.items.length])));
      const buttons = el('div', 'lr-row');
      const saveButton = btn(t('고친 캡션 저장'), saveCaptions, 'lr-primary');
      saveButton.disabled = !Object.keys(state.captions).length || !!ctx.preview;
      const again = btn(t('자동 캡션 다시 만들기'), recaption);
      again.disabled = !!ctx.preview;
      buttons.append(again, saveButton);
      head.append(buttons);
      const list = el('div', 'lr-captions');
      for (const item of dataset.items) {
        const row = el('div', 'lr-caption');
        const thumb = el('img');
        thumb.src = `/api/gallery/thumbnail?path=${encodeURIComponent(item.path)}`;
        thumb.alt = item.path;
        thumb.loading = 'lazy';
        const area = el('textarea');
        area.rows = 3;
        area.value = state.captions[item.path] ?? item.caption;
        area.addEventListener('input', () => {
          state.captions[item.path] = area.value;
          saveButton.disabled = !!ctx.preview;
        });
        const areaBox = withTagComplete(area, ctx.api);
        const label = el(
          'small',
          'lr-muted',
          `${item.path}${item.caption_edited ? t(' · 직접 고침') : ''}`,
        );
        const text = el('div');
        text.append(label, areaBox);
        row.append(thumb, text);
        list.append(row);
      }
      box.append(head, list);
    }
    return box;
  }

  // ---- training tab -------------------------------------------------------------------

  async function startRun() {
    const train = state.train;
    try {
      const result = await ctx.api('/api/lora/runs/start', {
        ...who(),
        dataset_id: train.dataset,
        params: {
          epochs: Number(train.epochs),
          save_every: Number(train.save_every),
          learning_rate: String(train.learning_rate),
          method: train.method,
          base: train.base,
        },
      });
      ctx.notify(
        t('{0} 학습을 시작했습니다. 생성 중인 이미지가 끝나면 GPU를 잡습니다.', [result.run.id]),
      );
      await loadRuns();
    } catch (error) {
      fail(error);
    }
  }
  async function cancelRun(run) {
    if (!window.confirm(t('{0} 학습을 취소할까요?', [run.id]))) return;
    try {
      await ctx.api('/api/lora/runs/cancel', {...who(), run_id: run.id});
      await loadRuns();
    } catch (error) {
      fail(error);
    }
  }
  async function register(run, output) {
    const name = window.prompt(
      t('등록할 LoRA 이름'),
      `${state.character} ${run.id} e${output.epoch}`,
    );
    if (name == null) return;
    try {
      await ctx.api('/api/loras/register', {
        ...who(),
        run_id: run.id,
        epoch: output.epoch,
        name: name.trim() || undefined,
      });
      ctx.notify(t('LoRA 목록에 등록했습니다. "LoRA 목록" 탭에서 자동 적용을 켤 수 있습니다.'));
      await loadLoras();
    } catch (error) {
      fail(error);
    }
  }

  function trainTab() {
    const box = el('div');
    const options = state.options;
    if (!options) {
      box.append(el('p', 'lr-muted', t('읽는 중…')));
      return box;
    }
    if (!state.train) state.train = {...options.defaults, dataset: state.datasets.at(-1)?.id || ''};
    const train = state.train;
    if (!state.datasets.some((d) => d.id === train.dataset))
      train.dataset = state.datasets.at(-1)?.id || '';
    const form = el('div', 'lr-grid2');
    const dataset = select(
      state.datasets.map((d) => [
        d.id,
        t('{0} · {1} · {2}장', [d.id, d.name || '', d.items.length]),
      ]),
      train.dataset,
    );
    dataset.addEventListener('change', () => (train.dataset = dataset.value));
    const method = select(
      options.methods.map((m) => [m.id, tr(m.label)]),
      train.method,
    );
    method.addEventListener('change', () => (train.method = method.value));
    const base = select(
      options.bases.map((b) => [b.id, tr(b.label)]),
      train.base,
    );
    base.addEventListener('change', () => (train.base = base.value));
    const number = (key, attrs) => {
      const control = input('number', train[key], attrs);
      control.addEventListener('input', () => (train[key] = control.value));
      return control;
    };
    const lr = input('text', train.learning_rate);
    lr.addEventListener('input', () => (train.learning_rate = lr.value));
    form.append(
      field(t('데이터셋'), dataset),
      field(t('방식'), method),
      field(t('베이스 모델'), base, t('기본값은 공식 base로 학습하는 T-LoRA 설정입니다.')),
      field(t('에폭'), number('epochs', {min: 1, max: 400})),
      field(
        t('저장 간격(에폭)'),
        number('save_every', {min: 1, max: 400}),
        t('저장한 에폭마다 파일이 생깁니다.'),
      ),
      field(t('학습률'), lr, t('예: 1e-4')),
    );
    const active = state.runs.some((r) => ACTIVE.includes(r.status));
    const start = btn(t('학습 시작'), startRun, 'lr-primary');
    start.disabled = !train.dataset || active || !!ctx.preview;
    box.append(
      form,
      start,
      el(
        'p',
        'lr-muted',
        t('학습 중에는 새 이미지 생성이 멈춥니다. 대기열에 있던 작업은 학습이 끝난 뒤 이어집니다.'),
      ),
    );

    box.append(el('h3', '', t('학습 기록')));
    if (!state.runs.length) box.append(el('p', 'lr-muted', t('아직 학습한 적이 없습니다.')));
    for (const run of [...state.runs].reverse()) {
      const card = el('div', `lr-run lr-run-${run.status}`);
      const head = el('div', 'lr-row lr-between');
      const s = run.settings || {};
      head.append(
        el('strong', '', `${run.id} · ${RUN_LABELS[run.status] || run.status}`),
        el(
          'small',
          'lr-muted',
          t('{0} · {1} · {2} · {3}에폭 · lr {4}', [
            run.dataset_id,
            s.method || '',
            s.base_model || '',
            s.epochs || '',
            s.learning_rate ?? '',
          ]),
        ),
      );
      card.append(head);
      if (run.note) card.append(el('p', 'lr-muted', run.note));
      const p = run.progress || {};
      if (ACTIVE.includes(run.status)) {
        const bar = el('progress');
        bar.max = p.total_steps || 1;
        bar.value = p.step || 0;
        card.append(
          bar,
          el(
            'p',
            'lr-muted',
            p.step
              ? t('스텝 {0}/{1} · 에폭 {2}/{3}{4}', [
                  p.step,
                  p.total_steps,
                  p.epoch,
                  p.total_epochs,
                  p.loss != null ? ` · loss ${Number(p.loss).toFixed(4)}` : '',
                ])
              : RUN_LABELS[run.status],
          ),
          btn(t('취소'), () => cancelRun(run), 'lr-danger'),
        );
      }
      if (run.error) card.append(el('p', 'lr-error', tr(run.error)));
      if (run.outputs?.length) {
        const outputs = el('div', 'lr-row');
        const registered = new Set(
          state.loras.filter((l) => l.origin?.run_id === run.id).map((l) => l.origin.epoch),
        );
        for (const output of run.outputs) {
          const done = registered.has(output.epoch);
          const b = btn(
            done ? t('e{0} 등록됨', [output.epoch]) : t('e{0} 등록', [output.epoch]),
            () => register(run, output),
          );
          b.disabled = done || !!ctx.preview || run.status !== 'done';
          b.title = output.file;
          outputs.append(b);
        }
        card.append(outputs);
      }
      if (run.log_path) {
        // Show the part under the Studio folder (logs/lora/...); the full path stays in the tooltip.
        const short = run.log_path.replace(/^.*?[\\/](logs[\\/]lora[\\/])/, '$1');
        const log = el('small', 'lr-muted lr-path', t('로그: {0}', [short]));
        log.title = run.log_path;
        card.append(log);
      }
      box.append(card);
    }
    return box;
  }

  // ---- registry tab -------------------------------------------------------------------

  async function saveLora(lora, changes) {
    try {
      const latest = await ctx.api(`/api/library/entity?${query({kind: 'lora', id: lora.id})}`);
      await ctx.api('/api/loras/save', {
        payload: {...latest.entity, ...changes},
        expected_revision: latest.revision,
      });
      await loadLoras();
      ctx.onLibraryChanged?.();
    } catch (error) {
      fail(error);
      await loadLoras();
    }
  }
  async function deleteLora(lora) {
    if (
      !window.confirm(
        t('{0}를 목록에서 지울까요? 휴지통으로 가고 LoRA 파일은 남습니다.', [lora.name || lora.id]),
      )
    )
      return;
    try {
      const latest = await ctx.api(`/api/library/entity?${query({kind: 'lora', id: lora.id})}`);
      await ctx.api('/api/loras/delete', {id: lora.id, expected_revision: latest.revision});
      await loadLoras();
    } catch (error) {
      fail(error);
    }
  }

  function lorasTab() {
    const box = el('div');
    const mine = state.loras.filter(
      (l) =>
        l.scope === 'global' ||
        (l.origin?.work_id === state.work && l.origin?.character_id === state.character),
    );
    box.append(
      el(
        'p',
        'lr-muted',
        t(
          '자동 적용을 켠 LoRA는 작업 메뉴에서 이 캐릭터를 생성할 때 설정에 들어가고, 트리거 단어가 외형 앞에 붙습니다. 캐릭터·의상·모델 계열마다 하나만 켤 수 있습니다.',
        ),
      ),
    );
    if (!mine.length) box.append(el('p', 'lr-muted', t('이 캐릭터에 등록된 LoRA가 없습니다.')));
    for (const lora of mine) {
      const card = el('div', 'lr-lora');
      const head = el('div', 'lr-row lr-between');
      head.append(el('strong', '', lora.name || lora.id), el('small', 'lr-muted', lora.file));
      const auto = input('checkbox', lora.auto_apply);
      auto.addEventListener('change', () => saveLora(lora, {auto_apply: auto.checked}));
      const applyTo = select(
        [
          ['character', t('이 캐릭터 전체')],
          ['outfit', t('의상 {0}일 때만', [lora.origin?.outfit_set_id || ''])],
        ],
        lora.apply_to || 'character',
      );
      applyTo.addEventListener('change', () => saveLora(lora, {apply_to: applyTo.value}));
      const scope = select(
        [
          ['character', t('캐릭터 전용')],
          ['global', t('전역 (모든 캐릭터)')],
        ],
        lora.scope,
      );
      scope.addEventListener('change', () => saveLora(lora, {scope: scope.value}));
      const strength = input('number', lora.strength ?? 1, {min: -2, max: 3, step: 0.05});
      strength.addEventListener('change', () => saveLora(lora, {strength: Number(strength.value)}));
      const family = select(Object.entries(FAMILY_LABELS), lora.model_family || 'anima');
      family.addEventListener('change', () => saveLora(lora, {model_family: family.value}));
      const autoLabel = el('label', 'lr-check');
      autoLabel.append(auto, el('span', '', t('자동 적용')));
      const controls = el('div', 'lr-grid4');
      controls.append(
        autoLabel,
        field(t('적용 대상'), applyTo),
        field(t('범위'), scope),
        field(t('강도'), strength),
        field(t('모델 계열'), family),
      );
      for (const control of [auto, applyTo, scope, strength, family])
        control.disabled = !!ctx.preview;
      const triggers = Object.values(lora.triggers || {}).filter(Boolean);
      const origin = lora.origin
        ? `${lora.origin.work_id}/${lora.origin.character_id}/${lora.origin.outfit_set_id} · ${lora.origin.run_id || ''} e${lora.origin.epoch ?? ''}`
        : t('외부 파일');
      const remove = btn(t('목록에서 지우기'), () => deleteLora(lora), 'lr-danger');
      remove.disabled = !!ctx.preview;
      card.append(
        head,
        controls,
        el(
          'p',
          'lr-muted',
          t('트리거: {0} · 출처: {1}', [triggers.join(', ') || t('없음'), origin]),
        ),
        remove,
      );
      box.append(card);
    }
    return box;
  }

  // ---- layout and loading -------------------------------------------------------------

  function renderMain() {
    if (!state.character) {
      main.replaceChildren(el('p', 'lr-muted', t('왼쪽에서 캐릭터를 고르세요.')));
      return;
    }
    const tabs = el('div', 'lr-tabs');
    for (const [key, text] of [
      ['dataset', t('데이터셋')],
      ['train', t('학습')],
      ['loras', t('LoRA 목록')],
    ]) {
      const tab = btn(text, () => {
        state.tab = key;
        renderMain();
      });
      tab.setAttribute('aria-pressed', String(state.tab === key));
      tabs.append(tab);
    }
    const body =
      state.tab === 'dataset' ? datasetTab() : state.tab === 'train' ? trainTab() : lorasTab();
    main.replaceChildren(el('h2', '', `${state.work} / ${state.character}`), tabs, body);
  }

  async function loadRuns() {
    const result = await ctx.api(`/api/lora/runs?${whoQuery()}`);
    state.runs = arr(result.runs);
    renderMain();
    clearTimeout(state.timer);
    if (state.runs.some((r) => ACTIVE.includes(r.status)))
      state.timer = setTimeout(() => loadRuns().catch(() => {}), POLL_MS);
  }
  async function loadLoras() {
    state.loras = arr((await ctx.api('/api/loras')).loras);
    renderMain();
  }
  async function loadCharacter() {
    const [datasets] = await Promise.all([
      ctx.api(`/api/lora/datasets?${whoQuery()}`),
      loadRuns(),
      loadLoras(),
    ]);
    state.datasets = arr(datasets.datasets);
    if (state.dataset && !currentDataset()) state.dataset = '';
    if (!state.candidates.length) await chooseDataset(state.dataset);
    else renderMain();
  }
  async function loadCatalog() {
    state.catalog = await ctx.api(`/api/catalog?work=${encodeURIComponent(state.work)}`);
    renderSide();
    renderMain();
  }

  async function enter(params) {
    const [works, options] = await Promise.all([
      ctx.api('/api/works'),
      ctx.api('/api/lora/options').catch(() => null),
    ]);
    state.works = arr(works.works);
    state.options = options;
    state.work = params?.get('work') || state.work || state.works[0]?.id || '';
    await loadCatalog();
    const wanted = params?.get('character');
    if (wanted && wanted !== state.character) await chooseCharacter(wanted);
    else if (state.character) await loadCharacter();
  }
  function leave() {
    clearTimeout(state.timer);
  }

  return {element: root, enter, leave};
}
