// Pure helpers for reading a work catalog (/api/catalog). No DOM access, so they
// can be tested with node. The rules mirror asset_studio/library on the server.

import {t, tr} from '../core/i18n.js';
export const SCOPE_LABELS = {global: t('전역'), work: t('작품 공용'), character: t('캐릭터')};
export const MODEL_FAMILY_LABELS = {anima: 'Anima', sdxl: 'SDXL·IL', shared: t('공용')};

/** The model a prompt record was written for; older records were written for Anima. */
export const modelFamily = (record) => record?.model_family || 'anima';

/** True when the record can be used to generate with ``family`` (anima / sdxl). */
export const fitsFamily = (record, family) =>
  ['shared', family || 'anima'].includes(modelFamily(record));
const asList = (value) => (Array.isArray(value) ? value : []);

/** Split a category path into role, level value and the bucket ids are unique in. */
export function parseCategory(categories, category) {
  const segments = String(category || '').split('/');
  const role = categories?.roles?.[segments[0]];
  if (!role) return null;
  const parsed = {role: segments[0], level: role.level || null, value: null, bucket: segments[0]};
  if (role.level) {
    if (segments.length < 2) return null;
    parsed.value = segments[1];
    if (!role.unique_across_levels) parsed.bucket = `${segments[0]}/${segments[1]}`;
  }
  return parsed;
}

/** Sort level values (outfit slots, ratings) by the defined order; unknown ones last. */
export function orderedLevels(categories, role, values) {
  const order = asList(categories?.roles?.[role]?.order);
  const rank = (value) => (order.includes(value) ? order.indexOf(value) : order.length);
  return [...new Set(values)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function levelLabel(categories, role, value) {
  // Default category names are Korean in the data; translate them (renamed ones stay).
  return tr(categories?.roles?.[role]?.labels?.[value] || value);
}

export function characterOf(catalog, characterId) {
  return asList(catalog?.characters).find((character) => character.id === characterId) || null;
}

// Record lists a character can see, closest scope first.
function layers(catalog, character, key) {
  const result = [];
  if (character) result.push(['character', asList(character[key])]);
  result.push(['work', asList(catalog?.[`work_${key}`])]);
  result.push(['global', asList(catalog?.[`global_${key}`])]);
  return result;
}

export function findPiece(catalog, character, bucket, id, scope = null) {
  for (const [name, pieces] of layers(catalog, character, 'pieces')) {
    if (scope && name !== scope) continue;
    const found = pieces.find((piece) => piece.bucket === bucket && piece.id === id);
    if (found) return found;
  }
  return null;
}

/** Effective pieces of one bucket: a closer scope hides the same id further out. */
export function visiblePieces(catalog, character, bucket) {
  const seen = new Set();
  const result = [];
  for (const [, pieces] of layers(catalog, character, 'pieces')) {
    for (const piece of pieces) {
      if (piece.bucket !== bucket || seen.has(piece.id)) continue;
      seen.add(piece.id);
      result.push(piece);
    }
  }
  return result.sort((a, b) => a.id.localeCompare(b.id));
}

export function visibleOutfitSets(catalog, character) {
  const seen = new Set();
  const result = [];
  for (const [, sets] of layers(catalog, character, 'outfit_sets')) {
    for (const outfitSet of sets) {
      if (seen.has(outfitSet.id)) continue;
      seen.add(outfitSet.id);
      result.push(outfitSet);
    }
  }
  return result.sort((a, b) => a.id.localeCompare(b.id));
}

export function findOutfitSet(catalog, character, id) {
  return visibleOutfitSets(catalog, character).find((outfitSet) => outfitSet.id === id) || null;
}

/** The piece behind one slot of an outfit set (null when the reference is broken). */
export function slotPiece(catalog, character, outfitSet, slot) {
  const reference = outfitSet?.slots?.[slot];
  if (!reference) return null;
  const owner = outfitSet.scope === 'character' ? character : null;
  if (reference.scope === 'character' && !owner) return null;
  return findPiece(catalog, owner, `outfit/${slot}`, reference.id, reference.scope);
}

/**
 * Slots to request for one outfit set given the slots ticked on screen.
 * `chosen` of null means every slot. A whole-outfit slot (`full`) is always kept,
 * and a set that has none of the ticked slots is used as a whole.
 */
export function slotsForSet(categories, outfitSet, chosen) {
  const available = orderedLevels(categories, 'outfit', Object.keys(outfitSet?.slots || {}));
  if (!chosen) return available;
  const picked = available.filter((slot) => slot === 'full' || chosen.includes(slot));
  return picked.length ? picked : available;
}

/** Address fields (scope + owner) of a record, for API calls. */
export function locationOf(record) {
  const location = {scope: record.scope};
  if (record.scope !== 'global') location.work_id = record.work_id;
  if (record.scope === 'character') location.character_id = record.character_id;
  return location;
}

export function scopeLabel(record) {
  if (record.scope === 'character') return `${record.work_id}/${record.character_id}`;
  return record.scope === 'work' ? t('{0} 공용', [record.work_id]) : t('전역');
}

/** Folder tree of category paths: {name, path, children: [...]}, levels in defined order. */
export function folderTree(categories, role, pieces) {
  const root = {name: role, path: role, children: [], pieces: []};
  const definition = categories?.roles?.[role] || {};
  const ensure = (node, name) => {
    let child = node.children.find((item) => item.name === name);
    if (!child) {
      child = {name, path: `${node.path}/${name}`, children: [], pieces: []};
      node.children.push(child);
    }
    return child;
  };
  if (definition.level) for (const value of asList(definition.order)) ensure(root, value);
  for (const piece of pieces) {
    const segments = piece.category.split('/');
    if (segments[0] !== role) continue;
    let node = root;
    for (const segment of segments.slice(1)) node = ensure(node, segment);
    node.pieces.push(piece);
  }
  if (definition.level) {
    const order = orderedLevels(
      categories,
      role,
      root.children.map((child) => child.name),
    );
    root.children.sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  }
  return root;
}
