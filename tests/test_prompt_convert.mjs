import assert from 'node:assert/strict';
import {convertPrompts} from '../static/js/lib/prompt_convert.js';
const run = (positive, source = 'nai', target = 'anima', extra = {}) =>
  convertPrompts({positive, source, target, ...extra});
assert.equal(run('1girl, artist:some_artist, blue sky').positive, '1girl, @some artist, blue sky');
assert.equal(
  run('1girl, 1.5::artist:some_artist, smile::').positive,
  '1girl, (@some artist, smile:1.5)',
);
assert.equal(run('{smile}, [blur]').positive, '(smile:1.05), (blur:0.952381)');
assert.equal(run('(@some artist:1.2)', 'anima', 'nai').positive, '1.2::artist:some_artist::');
assert.equal(
  run('some_artist, smile', 'sdxl', 'anima', {artists: ['some artist']}).positive,
  '@some artist, smile',
);
assert.equal(run('unknown_artist, smile', 'sdxl', 'anima').positive, 'unknown_artist, smile');
assert.equal(run('@name \\(circle\\)', 'anima', 'sdxl').positive, 'name \\(circle\\)');
const prose = 'A woman holds a red umbrella, while a child stands behind her.\n"smile, blue sky"';
assert.equal(run(prose).positive, prose);
for (const raw of ['1.2::smile', '{smile', 'smile}', '1.2::smile, [blue::']) {
  const result = run(raw);
  assert.equal(result.positive, raw);
  assert.ok(result.warnings.some((w) => w.code === 'unbalanced'));
}
const negativeWeight = run('-1::hat::');
assert.equal(negativeWeight.positive, '-1::hat::');
assert.equal(negativeWeight.warnings[0].code, 'nonpositive_weight');
assert.equal(run('(red:blue:0.5)', 'sdxl', 'nai').positive, '(red:blue:0.5)');
assert.equal(run('x, <lora:test:1>').positive, 'x, <lora:test:1>');
assert.equal(run('artist:a', 'nai', 'nai').changes.length, 0);
for (const raw of ['1::red:: 2::blue::', '0.00000001::smile::']) {
  const result = run(raw);
  assert.equal(result.positive, raw);
  assert.ok(result.warnings.some((warning) => warning.code === 'unsupported'));
}
assert.equal(run('', 'nai', 'sdxl', {negative: '2::blur::'}).negative, '(blur:2)');
console.log('Prompt conversion tests passed.');
