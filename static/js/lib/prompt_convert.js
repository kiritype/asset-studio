// Pure rule converter. Keep this request/result boundary independent of UI and transport:
// a future optional provider can implement it without changing saved source prompts.
export const PROFILES = ['nai', 'anima', 'sdxl'];
const NUMBER = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)';
const numeric = new RegExp(`^(${NUMBER})::([\\s\\S]*)::$`);
const numericStart = new RegExp(`^(${NUMBER})::`);
const canonical = (s) =>
  s
    .replace(/\\([()])/g, '$1')
    .replace(/_/g, ' ')
    .trim();
const weightText = (n) => String(Number(n.toFixed(6)));

// Preserve separators verbatim; commas inside groups, escaped literals, and quoted prose
// are not tag boundaries. Unsupported/unbalanced input is returned intact, never repaired.
function partsOf(text, source) {
  const parts = [];
  const stack = [];
  let quote = '',
    start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '\\') {
      i++;
      continue;
    }
    if (quote) {
      if (c === quote) quote = '';
      continue;
    }
    if (c === '"') {
      quote = c;
      continue;
    }
    if (source === 'nai') {
      const open = text.slice(i).match(numericStart);
      if (open && (i === 0 || /[\s,\[\{]/.test(text[i - 1]))) {
        stack.push('::');
        i += open[0].length - 1;
        continue;
      }
      if (text.slice(i, i + 2) === '::') {
        if (stack.pop() !== '::') return null;
        i++;
        continue;
      }
    }
    if ('([{'.includes(c)) stack.push({'(': ')', '[': ']', '{': '}'}[c]);
    else if (')]}'.includes(c)) {
      if (stack.pop() !== c) return null;
    } else if ((c === ',' || c === '\n') && !stack.length) {
      parts.push(text.slice(start, i), c);
      start = i + 1;
    }
  }
  if (stack.length || quote) return null;
  parts.push(text.slice(start));
  return parts;
}

function outerGroup(text) {
  if (!'([{'.includes(text[0]) || !')]}'.includes(text.at(-1))) return false;
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\\') {
      i++;
      continue;
    }
    if ('([{'.includes(text[i])) depth++;
    if (')]}'.includes(text[i])) depth--;
    if (depth === 0 && i < text.length - 1) return false;
  }
  return depth === 0;
}

/** Convert only explicit syntax. Bare artist names require a user-supplied artist list.
 * Warnings contain codes and original excerpts so a UI/provider can localize them.
 */
export function convertPrompts({positive = '', negative = '', source, target, artists = []}) {
  if (!PROFILES.includes(source) || !PROFILES.includes(target))
    throw new Error('Unknown prompt profile');
  if (typeof positive !== 'string' || typeof negative !== 'string' || !Array.isArray(artists))
    throw new TypeError('Prompts must be text and artists must be a list');
  if (positive.length > 30000 || negative.length > 30000) throw new RangeError('Prompt too long');
  const known = new Set(artists.filter((s) => typeof s === 'string').map(canonical));
  const changes = [],
    warnings = [];
  const warn = (field, code, text) => {
    if (!warnings.some((w) => w.field === field && w.code === code && w.text === text))
      warnings.push({field, code, text});
  };
  function convert(text, field, depth = 0) {
    if (depth > 30) {
      warn(field, 'unsupported', text);
      return text;
    }
    const parts = partsOf(text, source);
    if (!parts) {
      warn(field, 'unbalanced', text);
      return text;
    }
    return parts.map((part, index) => (index % 2 ? part : segment(part, field, depth))).join('');
  }
  function weighted(inner, weight, original, field, depth) {
    if (!Number.isFinite(weight) || weight <= 0) {
      warn(field, 'nonpositive_weight', original);
      return original;
    }
    // Adjacent numerical groups can match the outer pattern greedily. Never wrap
    // a body that cannot be parsed on its own, or emit rounded-to-zero weights.
    const encodedWeight = weightText(weight);
    if (!partsOf(inner, source) || Number(encodedWeight) <= 0 || /e/i.test(encodedWeight)) {
      warn(field, 'unsupported', original);
      return original;
    }
    // Nested NAI numerical emphasis has more complicated closure rules. Do not emit
    // ambiguous nested :: groups; leave the whole group for manual adjustment.
    if (target === 'nai' && /[\[\]{}]|(?<!\\)[()]/.test(inner)) {
      warn(field, 'unsupported', original);
      return original;
    }
    const body = convert(inner, field, depth + 1);
    warn(field, 'weight', original);
    return target === 'nai' ? `${encodedWeight}::${body}::` : `(${body}:${encodedWeight})`;
  }
  function segment(part, field, depth) {
    const text = part.trim();
    if (!text) return part;
    let result = text;
    const numericGroup = source === 'nai' && text.match(numeric);
    if (numericGroup)
      result = weighted(numericGroup[2], Number(numericGroup[1]), text, field, depth);
    else if (outerGroup(text)) {
      const bracket = text[0];
      const inner = text.slice(1, -1);
      if (source === 'nai' && (bracket === '{' || bracket === '['))
        result = weighted(inner, bracket === '{' ? 1.05 : 1 / 1.05, text, field, depth);
      else if (source !== 'nai' && (bracket === '(' || bracket === '[')) {
        const explicit = bracket === '(' && inner.match(new RegExp(`^([\\s\\S]*):(${NUMBER})$`));
        const content = explicit ? explicit[1] : inner;
        if (/[|]/.test(content) || /:/.test(content.replace(/artist:/g, '')))
          warn(field, 'unsupported', text);
        else
          result = weighted(
            explicit ? explicit[1] : inner,
            explicit ? Number(explicit[2]) : bracket === '(' ? 1.1 : 1 / 1.1,
            text,
            field,
            depth,
          );
      } else warn(field, 'unsupported', text);
    } else {
      const marked = text.match(/^(?:@|artist:)\s*(.+)$/);
      const artist = marked ? marked[1] : known.has(canonical(text)) ? text : null;
      if (artist && !/[.!?;"\n]|::/.test(artist)) {
        const name = canonical(artist);
        result =
          target === 'nai'
            ? `artist:${name.replace(/ /g, '_')}`
            : (target === 'anima' ? '@' : '') + name.replace(/([()])/g, '\\$1');
      } else if (/::|[{}[\]]|<[^>]+>|\b(?:BREAK|AND)\b|\|/.test(text))
        warn(field, 'unsupported', text);
      // Ordinary prose, punctuation, tag order and unknown names are deliberately intact.
    }
    if (result !== text) changes.push({field, before: text, after: result});
    return (
      part.slice(0, part.indexOf(text)) + result + part.slice(part.indexOf(text) + text.length)
    );
  }
  if (source === target)
    return {positive, negative, changes, warnings, engine: 'rules', version: 1};
  if (source === 'sdxl' && !known.size) warn('positive', 'bare_artists', '');
  return {
    positive: convert(positive, 'positive'),
    negative: convert(negative, 'negative'),
    changes,
    warnings,
    engine: 'rules',
    version: 1,
  };
}
