import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/js/lib/prompt_format.js', import.meta.url), 'utf8');
const {formatPromptLines} = await import(`data:text/javascript,${encodeURIComponent(source)}`);

assert.equal(formatPromptLines('1girl, solo, long hair'), '1girl\nsolo\nlong hair');
assert.equal(
  formatPromptLines('(foo,bar:1.2), solo, [blue, green], gold ring'),
  '(foo,bar:1.2)\nsolo\n[blue, green]\ngold ring',
);
assert.equal(formatPromptLines('red\\, blue, solo'), 'red\\, blue\nsolo');
assert.equal(
  formatPromptLines('A woman wears a navy dress, with two narrow slits on the skirt.'),
  'A woman wears a navy dress, with two narrow slits on the skirt.',
);
assert.equal(
  formatPromptLines(
    'She has blue eyes, pale skin, and long hair.\nHer coat has 1.2 cm trim, and a gold clasp.',
  ),
  'She has blue eyes, pale skin, and long hair.\nHer coat has 1.2 cm trim, and a gold clasp.',
);
const c041 =
  'navy maid dress, dress, high collar, long sleeves, side slit, white apron, frilled apron, back bow, white lace maid headdress. A navy-blue long classic maid dress with a high neckline and long sleeves, slit open on both sides from the underarms of the bodice down the sides of the skirt.';
const formatted = formatPromptLines(c041);
assert.ok(formatted.startsWith('navy maid dress\ndress\nhigh collar\n'));
assert.ok(
  formatted.endsWith(
    'white lace maid headdress.\nA navy-blue long classic maid dress with a high neckline and long sleeves, slit open on both sides from the underarms of the bodice down the sides of the skirt.',
  ),
);
assert.equal(
  formatPromptLines('The ring is worn over her glove, on the right ring finger.'),
  'The ring is worn over her glove, on the right ring finger.',
);
assert.equal(
  formatPromptLines('solo\nA closed book, with a brown cover, rests in her left hand.'),
  'solo\nA closed book, with a brown cover, rests in her left hand.',
);
assert.equal(formatPromptLines('unmatched (foo, bar'), 'unmatched (foo, bar');
assert.equal(
  formatPromptLines('She wears a coat. The lining is blue! Is the clasp gold? Yes, it is.'),
  'She wears a coat.\nThe lining is blue!\nIs the clasp gold?\nYes, it is.',
);
assert.equal(
  formatPromptLines('The trim is 1.2 cm wide. The (ribbon:1.25) is blue.'),
  'The trim is 1.2 cm wide.\nThe (ribbon:1.25) is blue.',
);
assert.equal(
  formatPromptLines('Dr. Vale wears a U.S. Navy coat. It is dark blue.'),
  'Dr. Vale wears a U.S. Navy coat.\nIt is dark blue.',
);
assert.equal(
  formatPromptLines('She says "Wait. Stay here" and smiles. Then she leaves.'),
  'She says "Wait. Stay here" and smiles.\nThen she leaves.',
);
assert.equal(
  formatPromptLines('She says "Stop!" Then she leaves.'),
  'She says "Stop!"\nThen she leaves.',
);
assert.equal(
  formatPromptLines("A woman's coat is blue. She's wearing gloves."),
  "A woman's coat is blue.\nShe's wearing gloves.",
);
assert.equal(formatPromptLines("woman's coat, solo"), "woman's coat\nsolo");
assert.equal(
  formatPromptLines('A (red. blue) ribbon is tied to her hair. The bow is large.'),
  'A (red. blue) ribbon is tied to her hair.\nThe bow is large.',
);
assert.equal(
  formatPromptLines('A label reads \"A. B.\" on her coat. It is embroidered.'),
  'A label reads \"A. B.\" on her coat.\nIt is embroidered.',
);
assert.equal(
  formatPromptLines('The sign says "Stop (now)!" She turns.'),
  'The sign says "Stop (now)!"\nShe turns.',
);
assert.equal(
  formatPromptLines('The mark is \\. visible. The trim is blue.'),
  'The mark is \\. visible.\nThe trim is blue.',
);
assert.equal(formatPromptLines(formatPromptLines(c041)), formatPromptLines(c041));
