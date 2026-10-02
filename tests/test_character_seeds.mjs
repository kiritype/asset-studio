import assert from 'node:assert/strict';

const {withCharacterSeeds, samePreset, buildRequest, suggestedSlots} = await import(
  new URL('../static/js/lib/job_requests.js', import.meta.url)
);
const request = (character, outfit, work = 'W001', seed = -1) => ({
  work_id: work,
  character_id: character,
  outfit_id: outfit,
  expressions: [{id: '002'}, {id: '004'}],
  count: 3,
  settings: {seed, steps: 28},
});
const original = [
  request('C001', '001'),
  request('C001', '002'),
  request('C002', '001'),
  request('C001', '001', 'W002'),
];
const before = structuredClone(original);
let next = 100;
const random = () => next++;
const first = withCharacterSeeds(original, true, random);
assert.deepEqual(
  first.map((r) => r.settings.seed),
  [100, 100, 101, 102],
);
assert.deepEqual(original, before, 'draft settings must not acquire generated seeds');
assert.deepEqual(
  withCharacterSeeds(original, true, random).map((r) => r.settings.seed),
  [103, 103, 104, 105],
  'each submission draws fresh seeds',
);
assert.equal(first[0].count, 3);
assert.deepEqual(first[0].expressions, original[0].expressions);
assert.equal(first[0].settings.steps, 28);
const neverRandom = () => {
  throw new Error('must not draw random seed');
};
assert.deepEqual(
  withCharacterSeeds(original, false, neverRandom),
  before,
  'unchecked retains per-image random mode',
);
for (const seed of [0, 4262164242, 4294967295]) {
  const fixed = [request('C001', '001', 'W001', seed), request('C002', '002', 'W001', seed)];
  assert.deepEqual(
    withCharacterSeeds(fixed, true, neverRandom),
    fixed,
    'explicit fixed seeds take precedence',
  );
}
assert.equal(
  withCharacterSeeds([request('C001', '001')], undefined, () => 17)[0].settings.seed,
  17,
  'grouping defaults on',
);
const actual = withCharacterSeeds([request('C001', '001')])[0].settings.seed;
assert.ok(Number.isInteger(actual) && actual >= 0 && actual <= 4294967295);

assert.ok(
  samePreset({id: 'G1', settings: {a: 1, b: [1, 2]}}, {settings: {b: [1, 2], a: 1}, id: 'G1'}),
);
assert.ok(!samePreset({id: 'G1', settings: {a: 1}}, {id: 'G1', settings: {a: 2}}));

const categories = {
  roles: {outfit: {level: 'slot', order: ['full', 'hands', 'top', 'bottom', 'shoes']}},
};
const draft = {
  work: 'W001',
  slots: ['top', 'hands'],
  composition: '',
  artists: ['A001'],
  commonPositive: ['Q004'],
  commonNegative: [],
  count: 2,
};
const target = {
  character: {id: 'C001'},
  outfitSet: {id: '001', slots: {bottom: {}, top: {}, hands: {}}},
};
const built = buildRequest(draft, categories, target, ['001', '002'], {seed: -1}, {outfit: 'x'});
assert.deepEqual(built, {
  work_id: 'W001',
  character_id: 'C001',
  outfit_id: '001',
  outfit_slots: ['hands', 'top'],
  expressions: [{id: '001'}, {id: '002'}],
  composition_id: null,
  artist_ids: ['A001'],
  common_positive_ids: ['Q004'],
  common_negative_ids: [],
  count: 2,
  settings: {seed: -1},
  overrides: {outfit: 'x'},
  auto_lora: true,
});
const whole = {character: {id: 'C040'}, outfitSet: {id: '002', slots: {full: {}}}};
assert.deepEqual(
  buildRequest(draft, categories, whole, ['001'], {}).outfit_slots,
  ['full'],
  'a set without the ticked slots is used as a whole',
);
assert.deepEqual(
  buildRequest({...draft, slots: null}, categories, target, ['001'], {}).outfit_slots,
  ['hands', 'top', 'bottom'],
  'no selection means every slot, in the defined order',
);
assert.deepEqual(suggestedSlots({suggest_slots: ['hands', 'top']}), ['hands', 'top']);
assert.equal(suggestedSlots({suggest_slots: []}), null);
assert.equal(suggestedSlots(null), null);
console.log('Job request tests passed.');
