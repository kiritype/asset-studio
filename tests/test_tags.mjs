import assert from 'node:assert/strict';

import {promptTag, replaceTag, splitTags, tagAt} from '../static/js/lib/tags.js';

assert.deepEqual(tagAt('1girl, smi', 10), {start: 7, end: 10, word: 'smi'});
assert.deepEqual(tagAt('1girl,  long hair , red', 12), {start: 8, end: 17, word: 'long hair'});
assert.deepEqual(splitTags('(smile:1.2), kaname madoka \\(magical girl\\)\nblue sky,,'), [
  'smile',
  'kaname madoka (magical girl)',
  'blue sky',
]);
assert.deepEqual(splitTags('(@n_(m_ohkamotoh):0.7), (masterpiece, score_8), ((blush))'), [
  '@n_(m_ohkamotoh)',
  'masterpiece',
  'score_8',
  'blush',
]);
assert.equal(promptTag('kaname_madoka_(magical_girl)'), 'kaname madoka \\(magical girl\\)');
assert.deepEqual(replaceTag('1girl, smi', 7, 10, 'smile'), {text: '1girl, smile, ', caret: 14});
assert.deepEqual(replaceTag('a, smi, b', 3, 6, 'smile'), {text: 'a, smile, b', caret: 8});
// One tag per line: a line break ends a tag, and no comma is added.
assert.deepEqual(tagAt('1girl\nsmi\nblue sky', 9), {start: 6, end: 9, word: 'smi'});
assert.deepEqual(replaceTag('1girl\nsmi\nblue sky', 6, 9, 'smile', ''), {
  text: '1girl\nsmile\nblue sky',
  caret: 11,
});
assert.deepEqual(replaceTag('1girl\nsmi', 6, 9, 'smile', ''), {text: '1girl\nsmile', caret: 11});
console.log('tags ok');
