import assert from 'node:assert/strict';
import {t} from '../static/js/core/i18n.js';
import {convertPrompts} from '../static/js/lib/prompt_convert.js';

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = new Map();
    this.attributes = {};
    this.style = {};
    this.className = '';
    this.value = '';
    this.textContent = '';
    this.classList = {
      add: (name) => {
        if (!this.className.split(' ').includes(name)) this.className += ` ${name}`.trim();
      },
    };
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  replaceChildren(...nodes) {
    this.children = nodes;
  }

  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
  }

  get firstChild() {
    return this.children[0];
  }

  get childElementCount() {
    return this.children.length;
  }
}

const walk = (node) => [node, ...node.children.flatMap(walk)];
const find = (root, predicate) => walk(root).find(predicate);
const button = (root, label) =>
  find(root, (node) => node.tagName === 'button' && node.textContent === label);
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return {promise, resolve, reject};
};

globalThis.document = {createElement: (tagName) => new Element(tagName)};
globalThis.window = {matchMedia: () => null};
let handoff = null;
globalThis.sessionStorage = {
  getItem: () => handoff,
  setItem: (_key, value) => {
    handoff = value;
  },
  removeItem: () => {
    handoff = null;
  },
};

const {createPromptConverter} = await import('../static/js/views/prompt_converter.js');
const delayed = new Map();
let delayedComfy = null;
let delayedConvert = null;
const opened = [];
const notices = [];
const gallery = [
  {relative_path: 'missing.png', filename: 'missing.png'},
  {relative_path: 'error.png', filename: 'error.png'},
  {relative_path: 'profile.png', filename: 'profile.png'},
  {relative_path: 'inferred.png', filename: 'inferred.png', model_family: 'anima'},
  {relative_path: 'slow-a.png', filename: 'slow-a.png'},
  {relative_path: 'slow-b.png', filename: 'slow-b.png'},
  {relative_path: 'queue-slow.png', filename: 'queue-slow.png'},
];
const ctx = {
  api: async (path) => {
    if (path.startsWith('/api/gallery?')) return {page: 1, pages: 1, results: gallery};
    if (path.startsWith('/api/gallery/metadata?')) {
      const image = new URL(path, 'http://localhost').searchParams.get('path');
      if (image === 'missing.png') return {positive: null, negative: null};
      if (image === 'error.png') throw new Error('Metadata service unavailable');
      if (image === 'profile.png')
        return {
          positive: '1girl, artist:some_artist',
          negative: 'blur',
          prompt_format: 'nai',
          model_family: 'sdxl',
          settings: {family: 'sdxl', seed: 44, cfg: 7},
        };
      if (image === 'inferred.png') return {positive: '1girl', negative: '', settings: {}};
      if (image === 'slow-a.png' || image === 'slow-b.png') return delayed.get(image).promise;
      if (image === 'queue-slow.png') return delayed.get(image).promise;
      throw new Error(`Unexpected metadata path ${image}`);
    }
    if (path === '/api/comfy' && delayedComfy) return delayedComfy.promise;
    if (path === '/api/comfy')
      return {
        models: ['anima-model'],
        text_encoders: ['anima-encoder'],
        vaes: ['anima-vae'],
        clip_types: ['stable_diffusion'],
        samplers: ['er_sde'],
        schedulers: ['simple'],
      };
    throw new Error(`Unexpected API path ${path}`);
  },
  notify: (...args) => notices.push(args),
};

const view = createPromptConverter(ctx, {
  onOpenLab: (draft) => opened.push(draft),
  convert: (request) => delayedConvert?.promise || convertPrompts(request),
});
const root = view.element;
const textColumns = find(root, (node) => node.className === 'pc-columns');
const positiveSource = textColumns.children[0].children[1].children[1];
const negativeSource = textColumns.children[0].children[2].children[1];
const positiveResult = textColumns.children[1].children[1].children[1];
const negativeResult = textColumns.children[1].children[2].children[1];
const sourceSelect = find(root, (node) => node.tagName === 'select');
const targetSelect = walk(root).filter((node) => node.tagName === 'select')[1];
const convert = button(root, t('prompt_converter.convert'));
const openLab = button(root, t('prompt_converter.open_in_generation_compare'));
const pickImage = button(root, t('prompt_converter.choose_gallery_image'));
const dialog = find(root, (node) => node.tagName === 'dialog');
const pickerMessage = find(dialog, (node) => node.className === 'pc-status');
const pickerGrid = find(dialog, (node) => node.className === 'pc-gallery-grid');
const queueControls = find(root, (node) => node.className === 'pc-queue');
const chooseImage = (name) =>
  find(
    pickerGrid,
    (node) => node.className === 'pc-gallery-item' && node.children[1].textContent === name,
  );
const selectImage = async (name) => {
  if (!dialog.open) await pickImage.listeners.get('click')[0]();
  await chooseImage(name).listeners.get('click')[0]();
};

// Missing and failed metadata stay in an error/empty state and do not enable handoff.
await view.setPrompts({positive: 'previous prompt', source: 'nai'});
await selectImage('missing.png');
assert.equal(positiveSource.value, '', 'missing metadata clears the previous prompt');
assert.equal(openLab.disabled, true, 'missing metadata cannot be handed to generation');
assert.equal(
  find(root, (node) => node.className === 'pc-status').textContent,
  t('prompt_converter.no_stored_prompt'),
);

view.setPrompts({});
await selectImage('error.png');
assert.equal(positiveSource.value, '', 'a request error does not populate a prompt');
assert.match(pickerMessage.textContent, /Metadata service unavailable/);
assert.equal(openLab.disabled, true, 'a request error does not create a conversion result');

// Gallery profile and family metadata select the source format and saved settings.
await selectImage('profile.png');
assert.equal(sourceSelect.value, 'nai', 'prompt_format selects the source profile');
targetSelect.value = 'sdxl';
await targetSelect.listeners.get('change')[0]();
await convert.listeners.get('click')[0]();
assert.equal(openLab.disabled, false);
await openLab.listeners.get('click')[0]();
assert.equal(opened.at(-1).settings.family, 'sdxl');
assert.equal(opened.at(-1).settings.seed, 44, 'matching metadata family keeps saved settings');

// A gallery item's model_family fills missing format/family metadata.
await selectImage('inferred.png');
assert.equal(
  sourceSelect.value,
  'anima',
  'gallery item model_family supplies a missing prompt profile',
);
targetSelect.value = 'anima';
await targetSelect.listeners.get('change')[0]();
await convert.listeners.get('click')[0]();
await openLab.listeners.get('click')[0]();
assert.equal(opened.at(-1).settings.family, 'anima');

// Editing either source prompt invalidates the displayed conversion and actions.
assert.equal(positiveResult.value, '1girl');
positiveSource.value = 'changed prompt';
await positiveSource.listeners.get('input')[0]();
assert.equal(positiveResult.value, '');
assert.equal(negativeResult.value, '');
assert.equal(openLab.disabled, true);

// A conversion that finishes after source edits cannot restore a stale result.
view.setPrompts({positive: 'pending source', source: 'nai'});
targetSelect.value = 'sdxl';
await targetSelect.listeners.get('change')[0]();
delayedConvert = deferred();
const converting = convert.listeners.get('click')[0]();
positiveSource.value = 'newer source';
await positiveSource.listeners.get('input')[0]();
delayedConvert.resolve({positive: 'stale output', negative: '', changes: [], warnings: []});
await converting;
assert.equal(positiveResult.value, '', 'stale conversion output is suppressed');
assert.equal(openLab.disabled, true);
delayedConvert = null;

// A saved SDXL family must not leak into an Anima handoff.
view.setPrompts({
  positive: '1girl',
  settings: {family: 'sdxl', seed: 901, cfg: 9},
  family: 'sdxl',
  source: 'nai',
});
targetSelect.value = 'anima';
await targetSelect.listeners.get('change')[0]();
await convert.listeners.get('click')[0]();
await openLab.listeners.get('click')[0]();
assert.equal(opened.at(-1).settings.family, 'anima');
assert.equal(opened.at(-1).settings.seed, -1, 'wrong-family saved seed is not reused');
assert.equal(opened.at(-1).settings.cfg, 5, 'wrong-family saved CFG is not reused');

// An in-flight ComfyUI lookup cannot hand off after the source prompt changes.
view.setPrompts({positive: '1girl', source: 'nai'});
targetSelect.value = 'sdxl';
await targetSelect.listeners.get('change')[0]();
await convert.listeners.get('click')[0]();
const openedBeforeStaleLookup = opened.length;
delayedComfy = deferred();
const openingLab = openLab.listeners.get('click')[0]();
await Promise.resolve();
positiveSource.value = 'edited during lookup';
await positiveSource.listeners.get('input')[0]();
delayedComfy.resolve({models: [], samplers: [], schedulers: []});
await openingLab;
assert.equal(opened.length, openedBeforeStaleLookup, 'stale async lab handoff is suppressed');
delayedComfy = null;

// Loading a queued image clears previous content and disables actions while pending.
view.setPrompts({positive: 'old prompt', source: 'nai'});
delayed.set('queue-slow.png', deferred());
handoff = JSON.stringify({type: 'prompt-format', paths: ['queue-slow.png']});
const loadingQueue = view.enter();
await Promise.resolve();
assert.equal(queueControls.hidden, false);
assert.equal(positiveSource.value, '', 'queue loading clears the previous prompt');
assert.equal(negativeSource.value, '');
assert.equal(convert.disabled, true, 'queue loading disables conversion');
assert.equal(openLab.disabled, true, 'queue loading disables handoff');
assert.equal(
  find(root, (node) => node.className === 'pc-status').textContent,
  t('prompt_converter.loading_image_record', ['queue-slow.png']),
);
delayed.get('queue-slow.png').resolve({positive: 'queued prompt', negative: 'queued negative'});
await loadingQueue;
assert.equal(positiveSource.value, 'queued prompt');

// One missing or failed record must not strand the rest of a gallery selection.
for (const failed of ['missing.png', 'error.png']) {
  view.setPrompts({source: 'sdxl'});
  handoff = JSON.stringify({type: 'prompt-format', paths: [failed, 'inferred.png']});
  await view.enter();
  assert.equal(queueControls.hidden, false);
  assert.equal(positiveSource.value, '');
  const nextImage = button(root, t('prompt_converter.next_image'));
  assert.equal(nextImage.disabled, false);
  await nextImage.listeners.get('click')[0]();
  assert.equal(positiveSource.value, '1girl');
  assert.equal(sourceSelect.value, 'anima', 'legacy gallery settings imply Anima');
}

// A slower earlier metadata request cannot overwrite the later selection.
delayed.set('slow-a.png', deferred());
delayed.set('slow-b.png', deferred());
await pickImage.listeners.get('click')[0]();
const requestA = chooseImage('slow-a.png').listeners.get('click')[0]();
const requestB = chooseImage('slow-b.png').listeners.get('click')[0]();
delayed.get('slow-b.png').resolve({positive: 'newer selection', negative: ''});
await requestB;
delayed.get('slow-a.png').resolve({positive: 'stale selection', negative: ''});
await requestA;
assert.equal(positiveSource.value, 'newer selection');

console.log('Prompt converter UI checks passed.');
