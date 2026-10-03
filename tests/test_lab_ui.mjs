import assert from 'node:assert/strict';
import {t} from '../static/js/core/i18n.js';

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.listeners = new Map();
    this.attributes = {};
    this.style = {};
    this.className = '';
    this.classList = {
      add: (name) => {
        if (!this.className.split(' ').includes(name)) this.className += ` ${name}`.trim();
      },
      toggle: (name, enabled) => {
        if (enabled) this.classList.add(name);
        else
          this.className = this.className
            .split(' ')
            .filter((item) => item !== name)
            .join(' ');
      },
    };
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  prepend(node) {
    this.children.unshift(node);
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

  get firstChild() {
    return this.children[0];
  }
}

const walk = (node) => [node, ...node.children.flatMap(walk)];
const find = (root, predicate) => walk(root).find(predicate);
const storage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
};

globalThis.document = {
  hidden: false,
  createElement: (tagName) => new Element(tagName),
};
globalThis.window = {matchMedia: () => null};
globalThis.localStorage = storage();
globalThis.sessionStorage = storage();
globalThis.setInterval = () => 1;
globalThis.clearInterval = () => {};

const {createLab} = await import('../static/js/views/lab.js');

const labRequests = [];
const ctx = {
  api: async (path, body) => {
    if (path === '/api/comfy') return {defaults: {family: 'anima', seed: 17}};
    if (path === '/api/catalog') return {presets: {generation: []}};
    if (path === '/api/jobs/lab') {
      labRequests.push(body);
      return {jobs: [], lab_group: 'group-1'};
    }
    if (path === '/api/jobs') return {jobs: []};
    throw new Error(`Unexpected API path: ${path}`);
  },
  notify: () => {},
};

const lab = createLab(ctx);
const form = lab.element.children[1];
await lab.enter(new URLSearchParams());
await lab.leave();
await lab.enter(new URLSearchParams());

const textareas = walk(form).filter((node) => node.tagName === 'textarea');
assert.equal(textareas[0].attributes['aria-label'], t('common.positive_prompt'));
assert.equal(textareas[1].attributes['aria-label'], t('common.negative_prompt'));
assert.equal(
  textareas[0].listeners.get('input').length,
  1,
  'positive autocomplete is attached once',
);
assert.equal(
  textareas[0].listeners.get('keydown').length,
  1,
  'positive key handler is attached once',
);
assert.equal(
  textareas[1].listeners.get('input').length,
  1,
  'negative autocomplete is attached once',
);
assert.equal(
  walk(form).filter((node) => node.className === 'tag-input').length,
  2,
  'prompt autocomplete wrappers are constructed once',
);

const modeRow = find(form, (node) => node.className === 'lab-tabs');
const countField = find(
  form,
  (node) => node.tagName === 'label' && node.children[0].textContent === t('lab.seeds'),
);
const sweepRow = find(form, (node) => node.className === 'lab-row' && node.children.length === 4);
const modeHeading = find(form, (node) => node.className === 'lab-mode-heading');
const countInput = countField.children[1];
assert.equal(countField.hidden, true, 'single mode hides seed count');
assert.equal(sweepRow.hidden, true, 'single mode hides sweep controls');
assert.equal(modeHeading.textContent, t('lab.single'));
const valuesField = sweepRow.children.find(
  (node) => node.children[0].textContent === t('lab.values'),
);
const loraField = sweepRow.children.find((node) => node.children[0].textContent === 'LoRA');
const noArtistField = sweepRow.children.find(
  (node) => node.children[0].textContent === t('lab.include_no_artist_baseline'),
);
await modeRow.children[1].listeners.get('click')[0]();
assert.equal(countField.hidden, false, 'compare mode shows seed count');
assert.equal(sweepRow.hidden, false, 'compare mode shows sweep controls');
assert.equal(modeHeading.textContent, t('lab.result'));
assert.equal(valuesField.hidden, true, 'unused values wrapper is hidden');
assert.equal(loraField.hidden, true, 'unused LoRA wrapper is hidden');
assert.equal(noArtistField.hidden, true, 'unused artist baseline option is hidden');

const sweepSelect = sweepRow.children[0].children[1];
sweepSelect.value = 'artist';
await sweepSelect.listeners.get('change')[0]();
const artistValues = sweepRow.children.find(
  (node) => node.children[0].textContent === t('lab.values'),
).children[1];
assert.equal(valuesField.hidden, false, 'artist values wrapper is shown');
assert.equal(noArtistField.hidden, false, 'artist baseline option is shown');
assert.equal(loraField.hidden, true, 'LoRA wrapper remains hidden for artist sweep');
artistValues.value = 'artist_a\nartist_b';
await artistValues.listeners.get('input')[0]();
const noArtist = noArtistField.children[1];
noArtist.checked = true;
await noArtist.listeners.get('change')[0]();
countInput.value = '3';
await countInput.listeners.get('input')[0]();

const runButton = find(form, (node) => node.className === 'lab-primary');
assert.equal(runButton.disabled, false, 'two candidates plus baseline can run');

artistValues.value = 'artist_a\n artist_a ';
await artistValues.listeners.get('input')[0]();
assert.equal(runButton.disabled, true, 'trimmed duplicate artist candidates are rejected');
artistValues.value = 'artist_a\nartist_b';
await artistValues.listeners.get('input')[0]();

sweepSelect.value = 'cfg';
await sweepSelect.listeners.get('change')[0]();
const cfgValues = valuesField.children[1];
cfgValues.value = Array.from({length: 13}, (_, index) => index + 1).join(', ');
await cfgValues.listeners.get('input')[0]();
assert.equal(runButton.disabled, true, 'the 12-value limit applies to every sweep');

sweepSelect.value = 'artist';
await sweepSelect.listeners.get('change')[0]();
const restoredArtistValues = valuesField.children[1];
restoredArtistValues.value = 'artist_a\nartist_b';
await restoredArtistValues.listeners.get('input')[0]();
noArtist.checked = true;
await noArtist.listeners.get('change')[0]();

await modeRow.children[0].listeners.get('click')[0]();
assert.equal(modeHeading.textContent, t('lab.single'));
assert.equal(countField.hidden, true);
assert.equal(sweepRow.hidden, true);
assert.equal(runButton.disabled, false, 'single mode can run despite stored compare values');
await runButton.listeners.get('click')[0]();
assert.equal(labRequests[0].count, 1);
assert.equal(labRequests[0].sweep, null);

await modeRow.children[1].listeners.get('click')[0]();
assert.equal(modeHeading.textContent, t('lab.result'));
assert.equal(countInput.value, '3', 'returning to compare restores the seed count');
assert.equal(sweepSelect.value, 'artist', 'returning to compare restores the sweep');
assert.equal(restoredArtistValues.value, 'artist_a\nartist_b');
assert.equal(noArtist.checked, true, 'returning to compare restores the baseline option');
assert.equal(runButton.disabled, false);
await runButton.listeners.get('click')[0]();
assert.deepEqual(labRequests[1].sweep, {
  key: 'artist',
  values: ['artist_a', 'artist_b', ''],
  lora_index: 0,
});
assert.equal(labRequests[1].count, 3);

console.log('Lab UI lifecycle and artist sweep checks passed.');
