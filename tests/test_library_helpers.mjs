import assert from 'node:assert/strict';

const lib = await import(new URL('../static/js/lib/library.js', import.meta.url));

const categories = {
  roles: {
    outfit: {
      label: '의상',
      level: 'slot',
      order: ['full', 'hands', 'top', 'bottom', 'shoes'],
      labels: {top: '상의'},
    },
    expression: {
      label: '감정',
      level: 'rating',
      order: ['sfw', 'nsfw'],
      unique_across_levels: true,
    },
    composition: {label: '구도'},
    common: {label: '공통', level: 'target', order: ['positive', 'negative']},
  },
};
assert.deepEqual(lib.parseCategory(categories, 'outfit/top/winter'), {
  role: 'outfit',
  level: 'slot',
  value: 'top',
  bucket: 'outfit/top',
});
assert.deepEqual(lib.parseCategory(categories, 'expression/sfw/daily'), {
  role: 'expression',
  level: 'rating',
  value: 'sfw',
  bucket: 'expression',
});
assert.equal(lib.parseCategory(categories, 'composition').bucket, 'composition');
assert.equal(lib.parseCategory(categories, 'outfit'), null, 'a role with a level needs that level');
assert.equal(lib.parseCategory(categories, 'unknown/x'), null);
assert.deepEqual(lib.orderedLevels(categories, 'outfit', ['cape', 'shoes', 'top', 'full', 'top']), [
  'full',
  'top',
  'shoes',
  'cape',
]);
assert.equal(lib.levelLabel(categories, 'outfit', 'top'), '상의');
assert.equal(lib.levelLabel(categories, 'outfit', 'cape'), 'cape');

const piece = (scope, bucket, id, extra = {}) => ({scope, bucket, id, category: bucket, ...extra});
const hero = {
  id: 'C001',
  pieces: [
    piece('character', 'outfit/top', '001'),
    piece('character', 'expression', '001', {name: 'hero'}),
  ],
  outfit_sets: [
    {
      scope: 'character',
      id: '001',
      slots: {top: {scope: 'character', id: '001'}, full: {scope: 'global', id: 'nude'}},
    },
  ],
};
const other = {id: 'C002', pieces: [], outfit_sets: []};
const catalog = {
  characters: [hero, other],
  work_pieces: [
    piece('work', 'expression', '001', {name: 'work'}),
    piece('work', 'expression', '003'),
  ],
  work_outfit_sets: [{scope: 'work', id: '050', slots: {}}],
  global_pieces: [
    piece('global', 'expression', '001', {name: 'global'}),
    piece('global', 'expression', '002'),
    piece('global', 'outfit/full', 'nude'),
    piece('global', 'outfit/top', '001', {name: 'global top'}),
  ],
  global_outfit_sets: [
    {scope: 'global', id: '099', slots: {full: {scope: 'global', id: 'nude'}}},
    {scope: 'global', id: '001', slots: {}},
  ],
};
assert.equal(lib.characterOf(catalog, 'C002'), other);
assert.equal(lib.findPiece(catalog, hero, 'expression', '001').name, 'hero');
assert.equal(lib.findPiece(catalog, other, 'expression', '001').name, 'work');
assert.equal(lib.findPiece(catalog, null, 'expression', '001', 'global').name, 'global');
assert.equal(lib.findPiece(catalog, hero, 'expression', '404'), null);
assert.deepEqual(
  lib.visiblePieces(catalog, hero, 'expression').map((p) => [p.id, p.scope]),
  [
    ['001', 'character'],
    ['002', 'global'],
    ['003', 'work'],
  ],
);
assert.deepEqual(
  lib.visibleOutfitSets(catalog, hero).map((s) => [s.id, s.scope]),
  [
    ['001', 'character'],
    ['050', 'work'],
    ['099', 'global'],
  ],
  'the character set hides the global one',
);
assert.deepEqual(
  lib.visibleOutfitSets(catalog, other).map((s) => s.scope),
  ['global', 'work', 'global'],
);
assert.equal(lib.slotPiece(catalog, hero, hero.outfit_sets[0], 'top').scope, 'character');
assert.equal(lib.slotPiece(catalog, hero, hero.outfit_sets[0], 'full').id, 'nude');
assert.equal(lib.slotPiece(catalog, hero, hero.outfit_sets[0], 'shoes'), null);
const shared = {scope: 'work', id: '060', slots: {top: {scope: 'character', id: '001'}}};
assert.equal(
  lib.slotPiece(catalog, hero, shared, 'top'),
  null,
  'a shared set cannot reach into a character',
);

assert.deepEqual(lib.slotsForSet(categories, hero.outfit_sets[0], null), ['full', 'top']);
assert.deepEqual(lib.slotsForSet(categories, {slots: {hands: {}, top: {}, bottom: {}}}, ['top']), [
  'top',
]);
assert.deepEqual(lib.slotsForSet(categories, {slots: {full: {}}}, ['top']), ['full']);
assert.deepEqual(lib.slotsForSet(categories, {slots: {bottom: {}}}, ['top']), ['bottom']);
assert.deepEqual(lib.slotsForSet(categories, {slots: {hands: {}, top: {}}}, []), ['hands', 'top']);

assert.deepEqual(
  lib.locationOf({scope: 'character', work_id: 'W001', character_id: 'C001', id: 'x'}),
  {scope: 'character', work_id: 'W001', character_id: 'C001'},
);
assert.deepEqual(lib.locationOf({scope: 'global', work_id: 'ignored'}), {scope: 'global'});
assert.equal(lib.scopeLabel({scope: 'work', work_id: 'W001'}), 'Shared in W001');
assert.equal(
  lib.scopeLabel({scope: 'character', work_id: 'W001', character_id: 'C001'}),
  'W001/C001',
);

const tree = lib.folderTree(categories, 'outfit', [
  {category: 'outfit/top/winter', id: 'coat'},
  {category: 'outfit/cape', id: 'c1'},
  {category: 'outfit/top', id: '001'},
  {category: 'expression/sfw', id: '001'},
]);
assert.deepEqual(
  tree.children.map((c) => c.name),
  ['full', 'hands', 'top', 'bottom', 'shoes', 'cape'],
);
const top = tree.children.find((c) => c.name === 'top');
assert.deepEqual(
  top.pieces.map((p) => p.id),
  ['001'],
);
assert.deepEqual(
  top.children.map((c) => [c.path, c.pieces.length]),
  [['outfit/top/winter', 1]],
);
assert.equal(
  lib.folderTree(categories, 'composition', [{category: 'composition', id: 'P001'}]).pieces.length,
  1,
);
console.log('Library helper tests passed.');
