// This formatter is deliberately conservative. A comma is a separator only
// when the surrounding text looks like a short tag list.
const PROSE_START =
  /^(?:a|an|the|she|he|they|her|his|their|both|each|one|two|this|that|it|its|with|while|wearing|holding|there|on|in|at|from|through|her\b|그녀|양쪽|각각|하나의)\b/i;

function topLevelCommas(line) {
  const parts = [];
  const stack = [];
  let start = 0;
  let escaped = false;
  let quote = '';
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === '\\') {
      escaped = true;
      continue;
    }
    if (quote) {
      if (char === quote) quote = '';
      continue;
    }
    if (char === '"' || (char === "'" && !/[\p{L}\p{N}]/u.test(line[i - 1] || ''))) {
      quote = char;
      continue;
    }
    if (char === '(' || char === '[' || char === '{') {
      stack.push(char);
      continue;
    }
    if (')]}'.includes(char)) {
      if (stack.length) stack.pop();
      continue;
    }
    if (char === ',' && stack.length === 0) {
      parts.push(line.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(line.slice(start));
  return stack.length || quote || escaped ? [line] : parts;
}

function shortTag(part) {
  const value = part.trim();
  if (!value || PROSE_START.test(value) || /[.!?](?:\s|$)/.test(value)) return false;
  if (
    /\b(?:is|are|has|have|wears|holds|sits|falls|covers|extends|ends|starts|rests|grips)\b/i.test(
      value,
    )
  )
    return false;
  return value.split(/\s+/).length <= 5;
}

function formatLine(line) {
  const parts = topLevelCommas(line);
  if (parts.length < 2 || !shortTag(parts[0])) return line;
  const firstProse = parts.findIndex((part, index) => index > 0 && !shortTag(part));
  if (firstProse === 1) return line;
  // A mixed line keeps the last tag attached to the following prose. This
  // preserves the original punctuation and avoids inserting a comma mid-sentence.
  const limit = firstProse < 0 ? parts.length : firstProse - 1;
  if (limit < 1) return line;
  const formatted = parts.slice(0, limit).map((part) => part.trim());
  if (firstProse >= 0) formatted.push(parts.slice(limit).join(',').trim());
  return formatted.join('\n');
}

// Split only at a sentence ending in ordinary prose. Prompt weights, grouped
// syntax, and quoted fragments can contain punctuation of their own.
function sentenceLines(line) {
  const result = [];
  const stack = [];
  let quote = '';
  let escaped = false;
  let start = 0;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === '\\') {
      escaped = true;
      continue;
    }
    if (quote) {
      if (char === quote) {
        quote = '';
        continue;
      }
      if (!/[.!?]/.test(char)) continue;
    } else if (char === '"' || (char === "'" && !/[\p{L}\p{N}]/u.test(line[i - 1] || ''))) {
      quote = char;
      continue;
    }
    if (char === '(' || char === '[' || char === '{') {
      stack.push(char);
      continue;
    }
    if (')]}'.includes(char)) {
      if (stack.length) stack.pop();
      continue;
    }
    if (stack.length || !/[.!?]/.test(char)) continue;

    // A closing quote may be part of the sentence ending, but punctuation
    // elsewhere inside a quotation is left alone.
    let end = i + 1;
    while (/[.!?]/.test(line[end] || '')) end++;
    if (quote) {
      if (line[end] !== quote) continue;
      end++;
    }
    if (!/\s/.test(line[end] || '')) continue;
    const next = line.slice(end).search(/\S/);
    if (next < 0) continue;
    if (
      char === '.' &&
      /(?:^|[\s(])(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc|No|Fig|Eq|Dept|Inc|Ltd|Co|Capt|Gen|Rep|Sen|e\.g|i\.e|a\.m|p\.m|U\.S|U\.K|[A-Z])\.$/i.test(
        line.slice(start, i + 1),
      )
    )
      continue;
    result.push(line.slice(start, end).trim());
    start = end + next;
    i = start - 1;
    quote = '';
  }
  result.push(line.slice(start));
  return result.join('\n');
}

export function formatPromptLines(value) {
  if (typeof value !== 'string' || !value) return value;
  return value
    .split(/\r?\n/)
    .map((line) => formatLine(line).split('\n').map(sentenceLines).join('\n'))
    .join('\n');
}
