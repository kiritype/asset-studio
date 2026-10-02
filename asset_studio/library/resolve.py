"""Look records up in a work catalog with scope precedence: character > work > global."""


def character_of(catalog, character_id):
    return next((c for c in catalog.get('characters', []) if c['id'] == character_id), None)


def _layers(catalog, character, key):
    """Record lists visible to a character, closest scope first."""
    layers = []
    if character is not None:
        layers.append(('character', character.get(key, [])))
    layers.append(('work', catalog.get('work_' + key, [])))
    layers.append(('global', catalog.get('global_' + key, [])))
    return layers


def find_piece(catalog, character, bucket, ident, scope=None):
    """The piece a character sees for ``bucket`` + ``ident``; ``scope`` pins one layer."""
    for name, pieces in _layers(catalog, character, 'pieces'):
        if scope is not None and name != scope:
            continue
        found = next((p for p in pieces if p['bucket'] == bucket and p['id'] == ident), None)
        if found:
            return found
    return None


def visible_pieces(catalog, character, bucket):
    """Effective pieces of one bucket. A closer scope hides the same id further out."""
    seen, result = set(), []
    for _, pieces in _layers(catalog, character, 'pieces'):
        for piece in pieces:
            if piece['bucket'] == bucket and piece['id'] not in seen:
                seen.add(piece['id'])
                result.append(piece)
    return sorted(result, key=lambda piece: piece['id'])


def find_outfit_set(catalog, character, ident):
    for _, sets in _layers(catalog, character, 'outfit_sets'):
        found = next((s for s in sets if s['id'] == ident), None)
        if found:
            return found
    return None


def visible_outfit_sets(catalog, character):
    seen, result = set(), []
    for _, sets in _layers(catalog, character, 'outfit_sets'):
        for outfit_set in sets:
            if outfit_set['id'] not in seen:
                seen.add(outfit_set['id'])
                result.append(outfit_set)
    return sorted(result, key=lambda outfit_set: outfit_set['id'])


def slot_piece(catalog, character, outfit_set, slot):
    """The piece behind one slot of an outfit set, or None when the reference is broken."""
    reference = outfit_set.get('slots', {}).get(slot) or {}
    scope = reference.get('scope')
    # A reference is relative to where the set is stored, so a shared set cannot
    # reach into a character even when composing for that character.
    owner = character if outfit_set.get('scope') == 'character' else None
    if scope == 'character' and owner is None:
        return None
    return find_piece(catalog, owner, f'outfit/{slot}', reference.get('id'), scope=scope)
