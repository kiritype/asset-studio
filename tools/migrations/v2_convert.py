"""Read a v1 library and write it as v2 pieces, outfit sets and presets."""

import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asset_studio.compose import compose
from asset_studio.library.layout import Location
from asset_studio.library.store import LibraryStore
from asset_studio.util import join, text

SLOT_NAMES = {'full': '', 'hands': ' 손', 'top': ' 상의', 'bottom': ' 하의', 'shoes': ' 신발'}

THREE_LINE_SLOTS = ('hands', 'top', 'bottom')

# Names the v1 editor used for the same thing.
LEGACY_NAME_KEYS = {
    'quality': ('anima_quality_preset', 'quality_preset'),
    'artist': ('anima_artist_preset', 'artist_preset'),
}

UPPER_BODY_SLOTS = ['hands', 'top']

GLOBAL = Location('global')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def records(folder):
    return (
        [read(path) for path in sorted(Path(folder).glob('*.json'))]
        if Path(folder).is_dir()
        else []
    )


def negative_of(entity):
    """v1 kept an older ``negative`` field as a fallback for ``negative_prompt``."""
    return entity.get('negative_prompt', entity.get('negative', ''))


def carry(entity, drop):
    """Fields to keep as they are. ``design_notes`` becomes ``notes``."""
    result = {
        key: value for key, value in entity.items() if key not in drop and key != 'schema_version'
    }
    if 'design_notes' in result:
        result.setdefault('notes', result.pop('design_notes'))
    return result


def bare_tags(value):
    return [re.sub(r'^\((.*):[\d.]+\)$', r'\1', tag.strip()) for tag in text(value).split(',')]


class V1:
    """The v1 library as it is on disk."""

    def __init__(self, data):
        self.data = Path(data)
        self.works = []
        for work_file in sorted(self.data.glob('works/*/work.json')):
            folder = work_file.parent
            characters = []
            for path in sorted(folder.glob('characters/*/character.json')):
                character = read(path)
                character['outfits'] = records(path.parent / 'outfits')
                characters.append(character)
            self.works.append(
                {
                    'work': read(work_file),
                    'characters': characters,
                    'expressions': records(folder / 'expressions/sfw')
                    + records(folder / 'expressions/nsfw'),
                    'chains': records(folder / 'chains'),
                    **{
                        kind: records(folder / 'presets' / kind)
                        for kind in ('quality', 'artist', 'generation')
                    },
                }
            )
        self.presets = {
            kind: records(self.data / 'presets' / kind)
            for kind in ('quality', 'artist', 'generation')
        }

    def compose(self, entry, character, outfit, expression, quality, artist, parts=None):
        """The v1 composition rule, kept here to compare against the converted library."""
        if isinstance(outfit.get('parts'), dict):
            outfit_text = join(*(outfit['parts'][key] for key in (parts or list(outfit['parts']))))
        else:
            outfit_text = text(outfit.get('prompt'))
        work = entry['work']
        positive = join(
            work.get('prompt'),
            quality.get('prompt'),
            artist.get('prompt'),
            expression.get('composition'),
            character.get('prompt'),
            expression.get('prompt'),
            outfit_text,
        )
        negative = join(
            *(
                text(negative_of(entity))
                for entity in (work, quality, artist, character, outfit, expression)
            )
        )
        return positive, negative


class Converter:
    def __init__(self, v1, build_root, global_outfits=('099',)):
        self.v1 = v1
        self.store = LibraryStore(build_root)
        self.global_outfits = set(global_outfits)
        self.report = {
            'warnings': [],
            'outfits': [],
            'compositions': [],
            'common': [],
            'generation': [],
            'counts': Counter(),
            'moved': [],
        }
        # With one work, its expressions become global; several works keep their own.
        with_expressions = [entry for entry in v1.works if entry['expressions']]
        self.shared_expressions = len(with_expressions) <= 1
        self.composition_ids = {}
        self.negative_common = set()

    def warn(self, message):
        self.report['warnings'].append(message)

    def count(self, key, amount=1):
        self.report['counts'][key] += amount

    # ---- pieces ----------------------------------------------------------------

    def convert_prompt_presets(self, location, quality, artist):
        for item in artist:
            self.store.save_piece(location, 'artist', carry(item, ('scope',)))
            self.count('artist pieces')
        for item in quality:
            base = carry(item, ('scope', 'negative_prompt', 'negative'))
            self.store.save_piece(location, 'common/positive', base)
            self.count('common/positive pieces')
            negative = negative_of(item)
            if text(negative):
                self.store.save_piece(
                    location,
                    'common/negative',
                    {
                        'id': item['id'],
                        'name': item.get('name', item['id']),
                        'prompt': negative if isinstance(negative, list) else [negative],
                    },
                )
                self.negative_common.add((repr(location), item['id']))
                self.count('common/negative pieces')
            self.report['common'].append(
                {
                    'id': item['id'],
                    'name': item.get('name', ''),
                    'where': repr(location),
                    'negative': bool(text(negative)),
                }
            )

    def convert_expressions(self, entry):
        work_id = entry['work']['id']
        location = GLOBAL if self.shared_expressions else Location('work', work_id)
        by_frequency = Counter(text(e.get('composition')) for e in entry['expressions'])
        for value, uses in sorted(by_frequency.items(), key=lambda item: -item[1]):
            if not value or (repr(location), value) in self.composition_ids:
                continue
            ident = f'P{len(self.composition_ids) + 1:03d}'
            self.composition_ids[(repr(location), value)] = ident
            source = next(
                e['composition']
                for e in entry['expressions']
                if text(e.get('composition')) == value
            )
            piece = {
                'id': ident,
                'name': value,
                'prompt': source if isinstance(source, list) else [source],
            }
            if 'upper body' in bare_tags(value):
                piece['suggest_slots'] = UPPER_BODY_SLOTS
            self.store.save_piece(location, 'composition', piece)
            self.count('composition pieces')
            self.report['compositions'].append(
                {
                    'id': ident,
                    'prompt': value,
                    'uses': uses,
                    'suggest_slots': piece.get('suggest_slots'),
                }
            )
        for expression in entry['expressions']:
            for key in ('allowed_characters', 'allowed_outfits'):
                if expression.get(key):
                    self.warn(
                        f'{work_id} 감정 {expression["id"]}: {key} 제한은 v2에 없습니다 '
                        f'(값은 파일에 남깁니다): {expression[key]}'
                    )
            piece = carry(expression, ('category', 'composition', 'negative', 'negative_prompt'))
            piece['negative_prompt'] = negative_of(expression)
            composition = text(expression.get('composition'))
            if composition:
                piece['composition_id'] = self.composition_ids[(repr(location), composition)]
            self.store.save_piece(location, f'expression/{expression["category"]}', piece)
            self.count('expression pieces')

    def outfit_split(self, outfit):
        """(slot -> prompt lines, how it was decided) for one v1 outfit."""
        prompt = outfit.get('prompt')
        lines = prompt if isinstance(prompt, list) else ([prompt] if prompt else [])
        parts = outfit.get('parts')
        if isinstance(parts, dict) and parts:
            if text(lines) != join(*parts.values()):
                self.warn(
                    f'{outfit["character_id"]}/{outfit["id"]}: prompt와 parts 내용이 다릅니다. '
                    'parts를 기준으로 옮깁니다 (v1 조합도 parts를 썼습니다).'
                )
            return {
                slot: value if isinstance(value, list) else [value] for slot, value in parts.items()
            }, 'parts'
        if len(lines) == len(THREE_LINE_SLOTS):
            return {slot: [line] for slot, line in zip(THREE_LINE_SLOTS, lines)}, '3줄'
        return {'full': lines}, f'{len(lines)}줄 → 전체'

    def convert_outfit(self, work_id, character, outfit):
        character_id = character['id']
        slots, how = self.outfit_split(outfit)
        location = Location('character', work_id, character_id)
        if outfit['id'] in self.global_outfits:
            existing = self.store.set_file(GLOBAL, outfit['id'])
            if existing.is_file():
                same = all(
                    text(self.store.resolve_piece(GLOBAL, f'outfit/{slot}', outfit['id'])['prompt'])
                    == text(lines)
                    for slot, lines in slots.items()
                )
                if same:
                    self.report['outfits'].append(
                        {
                            'character': f'{work_id}/{character_id}',
                            'id': outfit['id'],
                            'name': outfit.get('name', ''),
                            'how': '전역 세트와 같음 (합침)',
                            'slots': list(slots),
                            'scope': 'global',
                        }
                    )
                    return
                target = f'{work_id}/{character_id}/{outfit["id"]}'
                self.warn(f'{target}: 전역 의상과 내용이 달라 캐릭터 귀속으로 둡니다.')
            else:
                location = GLOBAL
        name = outfit.get('name', outfit['id'])
        for slot, lines in slots.items():
            self.store.save_piece(
                location,
                f'outfit/{slot}',
                {
                    'id': outfit['id'],
                    'name': name + SLOT_NAMES.get(slot, ' ' + slot),
                    'prompt': lines,
                },
            )
            self.count('outfit pieces')
        outfit_set = carry(
            outfit,
            (
                'character_id',
                'prompt',
                'parts',
                'is_default',
                'negative',
                'negative_prompt',
                'props_for_action_scenes',
            ),
        )
        outfit_set['slots'] = {
            slot: {'scope': location.scope, 'id': outfit['id']} for slot in slots
        }
        if text(negative_of(outfit)):
            outfit_set['negative_prompt'] = negative_of(outfit)
        if outfit.get('props_for_action_scenes'):
            outfit_set['props'] = {'note': outfit['props_for_action_scenes'], 'pieces': []}
        self.store.save_outfit_set(location, outfit_set)
        self.count('outfit sets')
        self.report['outfits'].append(
            {
                'character': f'{work_id}/{character_id}',
                'id': outfit['id'],
                'name': name,
                'how': how,
                'slots': list(slots),
                'scope': location.scope,
            }
        )

    def convert_work(self, entry):
        work_id = entry['work']['id']
        self.store.save_work(carry(entry['work'], ()))
        self.count('works')
        self.convert_prompt_presets(Location('work', work_id), entry['quality'], entry['artist'])
        for character in entry['characters']:
            record = carry(character, ('outfits',))
            default = next((o['id'] for o in character['outfits'] if o.get('is_default')), None)
            if not record.get('default_outfit') and default:
                record['default_outfit'] = default
            self.store.save_character(work_id, record)
            self.count('characters')
            for outfit in character['outfits']:
                self.convert_outfit(work_id, character, outfit)
        self.convert_expressions(entry)

    # ---- presets ---------------------------------------------------------------

    def _piece_id(self, kind, settings, names):
        """The quality/artist a v1 generation preset selected, as a plain id."""
        reference = settings.get(f'{kind}_id')
        if isinstance(reference, str) and reference:
            return reference.removeprefix('global:')
        for key in LEGACY_NAME_KEYS[kind]:
            if settings.get(key) in names:
                return names[settings[key]]
        return None

    def convert_settings(self, settings, label):
        names = {
            kind: {item.get('name'): item['id'] for item in self.v1.presets[kind]}
            for kind in ('quality', 'artist')
        }
        result = {
            key: value
            for key, value in settings.items()
            if key
            not in (
                'quality_id',
                'artist_id',
                *LEGACY_NAME_KEYS['quality'],
                *LEGACY_NAME_KEYS['artist'],
            )
        }
        quality, artist = (
            self._piece_id(kind, settings, names[kind]) for kind in ('quality', 'artist')
        )
        if quality:
            result['common_positive_ids'] = [quality]
            result['common_negative_ids'] = (
                [quality] if (repr(GLOBAL), quality) in self.negative_common else []
            )
        if artist:
            result['artist_ids'] = [artist]
        self.report['generation'].append(
            {
                'preset': label,
                'quality': quality,
                'artist': artist,
                'common_negative': result.get('common_negative_ids', []),
            }
        )
        return result

    def convert_presets(self):
        self.convert_prompt_presets(GLOBAL, self.v1.presets['quality'], self.v1.presets['artist'])
        taken = set()
        sources = [('', self.v1.presets['generation'])]
        sources += [(entry['work']['id'], entry['generation']) for entry in self.v1.works]
        for work_id, presets in sources:
            for preset in presets:
                record = carry(preset, ('scope',))
                if record['id'] in taken:
                    record['id'] = f'{work_id}_{record["id"]}'
                    self.warn(
                        f'작품 {work_id}의 생성 설정 {preset["id"]}은(는) 전역과 id가 겹쳐 '
                        f'{record["id"]}(으)로 옮깁니다.'
                    )
                taken.add(record['id'])
                record['settings'] = self.convert_settings(
                    record.get('settings') or {}, record['id']
                )
                self.store.save_preset('generation', record)
                self.count('generation presets')
        for entry in self.v1.works:
            for chain in entry['chains']:
                record = carry(chain, ())
                record['expressions'] = [{'id': ref['id']} for ref in chain.get('expressions', [])]
                if isinstance(record.get('settings'), dict):
                    record['settings'] = self.convert_settings(
                        record['settings'], 'chain ' + record['id']
                    )
                if 'generation_id' in record:
                    record['generation_preset_id'] = str(record.pop('generation_id')).removeprefix(
                        'global:'
                    )
                self.store.save_preset('expression_set', record)
                self.count('expression sets')

    def run(self):
        self.store.save_categories(self.store.categories().definition)
        self.convert_presets()
        for entry in self.v1.works:
            self.convert_work(entry)
        retired = self.v1.data / 'retired'
        for marker in sorted(retired.rglob('*.json')) if retired.is_dir() else []:
            relative = marker.relative_to(retired).as_posix().replace('/outfits/', '/outfit_sets/')
            target = self.store.root / 'retired' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(marker, target)
            self.count('retired code markers')
        return self.report


def verify(v1, store, report):
    """Compose every combination both ways; the final prompts must match exactly."""
    checked, mismatches = 0, []
    selections = [(None, None)] + [(item['id'], None) for item in v1.presets['quality']]
    for item in report['generation']:
        if (item['quality'], item['artist']) not in selections:
            selections.append((item['quality'], item['artist']))
    for entry in v1.works:
        work_id = entry['work']['id']
        catalog = store.catalog(work_id)
        choices = {
            kind: {item['id']: item for item in v1.presets[kind] + entry[kind]}
            for kind in ('quality', 'artist')
        }
        for character in entry['characters']:
            for outfit in character['outfits']:
                variants = [None]
                if isinstance(outfit.get('parts'), dict) and len(outfit['parts']) > 1:
                    variants.append(list(outfit['parts'])[:2])
                for expression in entry['expressions']:
                    for quality_id, artist_id in selections:
                        for parts in variants:
                            quality = choices['quality'].get(quality_id, {})
                            artist = choices['artist'].get(artist_id, {})
                            before = v1.compose(
                                entry, character, outfit, expression, quality, artist, parts
                            )
                            request = {
                                'work_id': work_id,
                                'character_id': character['id'],
                                'outfit_id': outfit['id'],
                                'outfit_slots': parts,
                                'expressions': [{'id': expression['id']}],
                                'common_positive_ids': [quality_id] if quality_id else [],
                                'common_negative_ids': [quality_id]
                                if text(negative_of(quality))
                                else [],
                                'artist_ids': [artist_id] if artist_id else [],
                            }
                            after = compose(store, request, catalog=catalog)
                            checked += 1
                            if (
                                before != (after['positive'], after['negative'])
                                or after['category'] != expression['category']
                            ):
                                outfit_path = f'{work_id}/{character["id"]}/{outfit["id"]}'
                                mismatches.append(
                                    {
                                        'target': f'{outfit_path} · 감정 {expression["id"]}',
                                        'before': before,
                                        'after': (after['positive'], after['negative']),
                                    }
                                )
    return checked, mismatches
