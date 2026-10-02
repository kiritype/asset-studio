"""Find the records that point at a piece or an outfit set.

Outfit sets name their slot pieces with an explicit scope. Everything else (an
expression's composition, a character's default outfit, presets) names an id and is
resolved with scope precedence when it is used.
"""

from .layout import PRESET_TYPES, Location

# Preset fields that hold piece ids, by bucket.
PRESET_ID_FIELDS = {
    'artist': ('artist_ids',),
    'common/positive': ('common_positive_ids',),
    'common/negative': ('common_negative_ids',),
    'composition': ('composition_id',),
    'expression': ('expressions',),
}


def slot_references(store, location, bucket, ident):
    """(set location, set file, slot) for every outfit-set slot that points at the piece."""
    if not bucket.startswith('outfit/'):
        return []
    slot = bucket.split('/', 1)[1]
    found = []
    for place in store.all_locations():
        if not place.can_see(location):
            continue
        for outfit_set in store.list_outfit_sets(place):
            reference = outfit_set.get('slots', {}).get(slot)
            if (
                isinstance(reference, dict)
                and reference.get('id') == ident
                and reference.get('scope') == location.scope
            ):
                found.append((place, store.set_file(place, outfit_set['id']), slot))
    return found


def composition_users(store, location, ident):
    """(expression location, expression file) whose composition resolves to this piece."""
    found = []
    for place in store.all_locations():
        if not place.can_see(location):
            continue
        resolved = store.resolve_piece(place, 'composition', ident)
        if resolved is None or Location.of(resolved) != location:
            continue
        for piece in store.list_pieces(place):
            if piece['role'] == 'expression' and piece.get('composition_id') == ident:
                found.append((place, store.piece_file(place, piece['category'], piece['id'])))
    return found


def _ids(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item.get('id') if isinstance(item, dict) else item for item in value]
    return []


def preset_references(store, bucket, ident):
    """Names of presets that use a piece id. Presets are not tied to a work or character."""
    fields = PRESET_ID_FIELDS.get(bucket, ())
    found = []
    for preset_type in PRESET_TYPES:
        for preset in store.list_presets(preset_type):
            containers = [
                preset,
                preset.get('settings') if isinstance(preset.get('settings'), dict) else {},
            ]
            if any(
                ident in _ids(container.get(field)) for container in containers for field in fields
            ):
                found.append(f'{preset_type}/{preset["id"]}')
    return found


def copies_elsewhere(store, location, bucket, ident):
    """True when another location also has a piece with this identity."""
    return any(
        place != location and store.find_piece(place, bucket, ident)
        for place in store.all_locations()
    )


def default_outfit_users(store, location, ident):
    """Character files whose default outfit resolves to the outfit set stored at ``location``."""
    found = []
    for place in store.all_locations():
        if place.scope != 'character' or not place.can_see(location):
            continue
        path = store.character_file(place.work_id, place.character_id)
        if store.read(path).get('default_outfit') != ident:
            continue
        closest = next(
            (
                place.widen(scope)
                for scope in ('character', 'work', 'global')
                if store.set_file(place.widen(scope), ident).is_file()
            ),
            None,
        )
        if closest == location:
            found.append(path)
    return found
