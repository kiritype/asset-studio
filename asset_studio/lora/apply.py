"""Which registered LoRAs a generation request gets automatically.

A registry entry with ``auto_apply`` is used for its own character (``apply_to:
character``) or only with the outfit set it was trained on (``apply_to: outfit``);
a global entry with ``auto_apply`` is used everywhere. Entries written for another
model family are skipped. At most one entry is automatic per character / outfit,
enforced when saving.
"""

from . import records

APPLY_TO = ('character', 'outfit')


def model_family(record):
    return record.get('model_family') or 'anima'


def applies(record, work_id, character_id, outfit_id):
    if not record.get('auto_apply'):
        return False
    if record.get('scope') == 'global':
        return True
    origin = record.get('origin') or {}
    if (origin.get('work_id'), origin.get('character_id')) != (work_id, character_id):
        return False
    if record.get('apply_to', 'character') == 'outfit':
        return origin.get('outfit_set_id') == outfit_id
    return True


def auto_loras(store, work_id, character_id, outfit_id, family):
    """Registry entries to add, as ``{id, name, file, strength, triggers}``."""
    found = []
    for record in records.list_loras(store):
        if not applies(record, work_id, character_id, outfit_id):
            continue
        if model_family(record) not in (family, 'shared'):
            continue
        found.append(
            {
                'id': record['id'],
                'name': record.get('name', record['id']),
                'file': record['file'],
                'strength': record.get('strength', 1.0),
                'triggers': [t for t in (record.get('triggers') or {}).values() if t],
            }
        )
    return found


def merge_loras(settings_loras, automatic):
    """Generation LoRA list with the automatic ones added (a file already chosen wins)."""
    result = list(settings_loras or [])
    chosen = {lora.get('name') for lora in result}
    for lora in automatic:
        if lora['file'] not in chosen:
            result.append(
                {
                    'name': lora['file'],
                    'strength_model': lora['strength'],
                    'strength_clip': lora['strength'],
                    'auto': lora['id'],
                }
            )
    return result


def key_of(record):
    """What one automatic entry is for; two entries with the same key cannot both be on."""
    if record.get('scope') == 'global':
        return None
    origin = record.get('origin') or {}
    target = record.get('apply_to', 'character')
    outfit = origin.get('outfit_set_id') if target == 'outfit' else None
    # Anima and SDXL generations each get their own automatic LoRA.
    return (origin.get('work_id'), origin.get('character_id'), target, outfit, model_family(record))
