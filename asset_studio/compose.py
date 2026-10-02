"""Prompt composition: library pieces -> final positive / negative prompt.

A request names one character (always with its work), an outfit set with the slots
to include, one expression, and optional composition / artist / common pieces. Ids are
resolved with scope precedence: character, then work, then global.
"""

from .i18n import Msg
from .library.layout import Categories
from .library.resolve import character_of, find_outfit_set, find_piece, slot_piece
from .lora.apply import auto_loras
from .util import code, join, text

# Request fields that select pieces by id, and the bucket they are looked up in.
SELECTIONS = (
    ('common', 'common/positive', 'common_positive_ids'),
    ('common', 'common/negative', 'common_negative_ids'),
    ('artist', 'artist', 'artist_ids'),
)
NEGATIVE_ORDER = ('work', 'common', 'artist', 'appearance', 'outfit', 'expression', 'composition')
# With several expressions in one request, these overrides would apply to the wrong ones.
PER_EXPRESSION_OVERRIDES = ('expression', 'composition', 'negative')
MAX_OVERRIDE_LENGTH = 30000
FAMILY_NAMES = {'anima': 'Anima', 'sdxl': 'SDXL·IL'}


def family_warnings(records, family):
    """Records written for the other model family; composing still works, but warns."""
    warnings = []
    for label, record in records:
        written_for = (record or {}).get('model_family', 'anima')
        if record and written_for not in (family, 'shared'):
            warnings.append(
                Msg(
                    'server.compose.this_prompt_was_written_for',
                    '{value}: this prompt was written for {written_for}.',
                    value=label,
                    written_for=FAMILY_NAMES.get(written_for, written_for),
                )
            )
    return warnings


def _negative(record):
    return text(record.get('negative_prompt')) if record else ''


def _reference(piece):
    return {
        'role': piece['role'],
        'category': piece['category'],
        'scope': piece['scope'],
        'id': piece['id'],
        'name': piece.get('name', piece['id']),
    }


def _selected(catalog, character, bucket, ids):
    if ids is None:
        return []
    if not isinstance(ids, list) or not all(isinstance(ident, str) for ident in ids):
        raise ValueError(
            Msg(
                'server.compose.a_list_of_piece_ids_is',
                '{bucket}: a list of piece ids is required.',
                bucket=bucket,
            )
        )
    pieces = []
    for ident in ids:
        piece = find_piece(catalog, character, bucket, ident)
        if piece is None:
            raise ValueError(
                Msg(
                    'server.compose.selected_prompt_piece_not_found',
                    'Selected prompt piece not found: {bucket}/{ident}',
                    bucket=bucket,
                    ident=ident,
                )
            )
        pieces.append(piece)
    return pieces


def outfit_slots(catalog, character, outfit_set, selected, categories):
    """(slot, piece) pairs of the chosen slots, in the defined slot order.

    ``selected`` of None means every slot of the set.
    """
    available = categories.ordered('outfit', outfit_set.get('slots', {}))
    if selected is None:
        selected = available
    if (
        not isinstance(selected, list)
        or not selected
        or any(slot not in available for slot in selected)
    ):
        raise ValueError(
            Msg(
                'server.compose.the_selected_slots_are_not_in',
                'The selected slots are not in this outfit set: {selected}',
                selected=', '.join(map(str, selected or [])),
            )
        )
    pairs = []
    for slot in available:
        if slot not in selected:
            continue
        piece = slot_piece(catalog, character, outfit_set, slot)
        if piece is None:
            raise ValueError(
                Msg(
                    'server.compose.the_piece_of_outfit_set_was',
                    'The {slot} piece of outfit set {id_value} was not found.',
                    id_value=outfit_set['id'],
                    slot=slot,
                )
            )
        pairs.append((slot, piece))
    return pairs


def compose(store, request, expression_ref=None, single=True, catalog=None):
    """Combine the selected prompt pieces into the final positive and negative prompt."""
    work_id = code(request['work_id'])
    catalog = catalog or store.catalog(work_id)
    categories = Categories(catalog['categories'])
    character = character_of(catalog, request['character_id'])
    if not character:
        raise ValueError(
            Msg('server.compose.this_character_is_not_in_the', 'This character is not in the work.')
        )
    outfit_set = find_outfit_set(catalog, character, request['outfit_id'])
    if not outfit_set:
        raise ValueError(
            Msg(
                'server.compose.this_outfit_set_is_not_available',
                'This outfit set is not available to the selected character.',
            )
        )
    reference = expression_ref or request['expressions'][0]
    expression = find_piece(catalog, character, 'expression', reference.get('id'))
    if not expression:
        raise ValueError(Msg('server.compose.expression_not_found', 'Expression not found.'))
    composition_id = request.get('composition_id') or expression.get('composition_id')
    composition = (
        find_piece(catalog, character, 'composition', composition_id) if composition_id else None
    )
    if composition_id and composition is None:
        raise ValueError(
            Msg(
                'server.compose.composition_not_found',
                'Composition not found: {composition_id}',
                composition_id=composition_id,
            )
        )
    slots = outfit_slots(catalog, character, outfit_set, request.get('outfit_slots'), categories)

    work = catalog['work']
    positive = {
        'work': [text(work.get('prompt'))],
        'appearance': [text(character.get('prompt'))],
        'expression': [text(expression.get('prompt'))],
        'composition': [text(composition.get('prompt'))] if composition else [],
        'outfit': [text(piece.get('prompt')) for _, piece in slots],
    }
    negative = {
        'work': [_negative(work)],
        'appearance': [_negative(character)],
        'expression': [_negative(expression)],
        'composition': [_negative(composition)],
        'outfit': [_negative(outfit_set), *(_negative(piece) for _, piece in slots)],
    }
    used = [expression, *([composition] if composition else []), *(piece for _, piece in slots)]
    selections = [(role, bucket, request.get(field)) for role, bucket, field in SELECTIONS]
    extras = request.get('extras') or {}
    if not isinstance(extras, dict):
        raise ValueError(
            Msg(
                'server.compose.extras_must_map_categories_to_lists',
                'extras must map categories to lists of piece ids.',
            )
        )
    for bucket, ids in extras.items():
        role = categories.parse(bucket)['role']
        if role in ('outfit', 'expression', 'composition') or any(
            role == known for known, _, _ in SELECTIONS
        ):
            raise ValueError(
                Msg(
                    'server.compose.this_category_cannot_be_chosen_as',
                    'This category cannot be chosen as extras: {bucket}',
                    bucket=bucket,
                )
            )
        selections.append((role, bucket, ids))
    for role, bucket, ids in selections:
        for piece in _selected(catalog, character, bucket, ids):
            # A piece under common/negative contributes its text to the negative prompt.
            if bucket == 'common/negative':
                negative.setdefault(role, []).append(text(piece.get('prompt')))
            else:
                positive.setdefault(role, []).append(text(piece.get('prompt')))
            negative.setdefault(role, []).append(_negative(piece))
            used.append(piece)

    parts = {role: join(*positive.get(role, [])) for role in categories.compose_order}
    negative_order = [*NEGATIVE_ORDER, *(role for role in negative if role not in NEGATIVE_ORDER)]
    negative_parts = {role: join(*negative.get(role, [])) for role in negative_order}
    parts['negative'] = join(*negative_parts.values())

    overrides = request.get('overrides', {})
    if not isinstance(overrides, dict):
        raise ValueError(
            Msg('server.compose.the_prompt_edits_are_invalid', 'The prompt edits are invalid.')
        )
    for key in parts:
        if key in overrides and (single or key not in PER_EXPRESSION_OVERRIDES):
            value = overrides[key]
            if not isinstance(value, str) or len(value) > MAX_OVERRIDE_LENGTH:
                raise ValueError(
                    Msg(
                        'server.compose.a_prompt_must_be_text_of',
                        'A prompt must be text of at most 30,000 characters.',
                    )
                )
            parts[key] = value.strip()
    family = (request.get('settings') or {}).get('family') or 'anima'
    automatic = []
    if request.get('auto_lora', True):
        automatic = auto_loras(store, work_id, character['id'], outfit_set['id'], family)
        triggers = [t for lora in automatic for t in lora['triggers']]
        if triggers and 'appearance' not in overrides:
            # LoRAs were trained with their trigger words; they lead the character's description.
            parts['appearance'] = join(*dict.fromkeys(triggers), parts['appearance'])
    checked = [
        (Msg('server.compose.work', 'Work'), work),
        (Msg('server.compose.appearance', 'Appearance'), character),
        (Msg('server.compose.outfit_set', 'Outfit set'), outfit_set),
    ]
    checked += [(f'{piece["category"]}/{piece["id"]}', piece) for piece in used]
    return dict(
        model_family=family,
        auto_loras=automatic,
        warnings=family_warnings(checked, family),
        work_id=work_id,
        character_id=character['id'],
        outfit_id=outfit_set['id'],
        expression_id=expression['id'],
        category=expression['rating'],
        expression_name=expression.get('name', expression['id']),
        outfit_slots=[slot for slot, _ in slots],
        composition_id=composition['id'] if composition else None,
        parts=parts,
        negative_parts=negative_parts,
        pieces=[_reference(piece) for piece in used],
        outfit_set={
            'scope': outfit_set['scope'],
            'id': outfit_set['id'],
            'name': outfit_set.get('name', outfit_set['id']),
        },
        positive=join(*(parts[role] for role in categories.compose_order)),
        negative=parts['negative'],
    )
