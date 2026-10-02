// Pure helpers for building generation requests. No DOM access.

import {slotsForSet} from './library.js';

// Materialize seeds only at submission: drafts and presets retain their seed mode.
export function withCharacterSeeds(
  requests,
  enabled = true,
  randomSeed = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0],
) {
  const seeds = new Map();
  return requests.map((request) => {
    const settings = {...request.settings};
    if (enabled && (settings.seed == null || settings.seed === -1)) {
      // A character code is only unique inside its work.
      const key = JSON.stringify([request.work_id, request.character_id]);
      if (!seeds.has(key)) seeds.set(key, randomSeed());
      settings.seed = seeds.get(key);
    }
    return {...request, settings};
  });
}

/** True when two presets hold the same values, whatever the key order. */
export function samePreset(left, right) {
  const ordered = (value) =>
    Array.isArray(value)
      ? value.map(ordered)
      : value && typeof value === 'object'
        ? Object.fromEntries(
            Object.keys(value)
              .sort()
              .map((key) => [key, ordered(value[key])]),
          )
        : value;
  return JSON.stringify(ordered(left)) === JSON.stringify(ordered(right));
}

/** One /api/jobs request for a character + outfit set and the chosen expressions. */
export function buildRequest(draft, categories, target, expressionIds, settings, overrides = {}) {
  return {
    work_id: draft.work,
    character_id: target.character.id,
    outfit_id: target.outfitSet.id,
    outfit_slots: slotsForSet(categories, target.outfitSet, draft.slots),
    expressions: expressionIds.map((id) => ({id})),
    composition_id: draft.composition || null,
    artist_ids: [...draft.artists],
    common_positive_ids: [...draft.commonPositive],
    common_negative_ids: [...draft.commonNegative],
    count: Number(draft.count),
    settings,
    overrides,
    // Registered LoRAs marked "자동 적용" are added on the server unless turned off here.
    auto_lora: draft.autoLora !== false,
  };
}

/** Slots to tick by default for a composition, or null for "all". */
export function suggestedSlots(composition) {
  const slots = composition?.suggest_slots;
  return Array.isArray(slots) && slots.length ? [...slots] : null;
}
