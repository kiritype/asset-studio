"""JSON files of the prompt library: works, characters, pieces, outfit sets and presets."""

import copy
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ..i18n import Msg
from ..util import read_text, replace_file
from .layout import (
    CATEGORIES_FILE,
    LAYOUT_FILE,
    LAYOUT_VERSION,
    PRESET_TYPES,
    Categories,
    Location,
    valid_id,
    visible_scopes,
)

SCHEMA_VERSION = 2
# Which model a prompt was written for. Records without the field were written for Anima.
MODEL_FAMILIES = ('anima', 'sdxl', 'shared')
# Filled in from the file location when a piece is read; never written back.
DERIVED_PIECE_FIELDS = ('category', 'role', 'bucket', 'scope', 'work_id', 'character_id')
DERIVED_SET_FIELDS = ('scope', 'work_id', 'character_id')
V1_MARKERS = ('queue.json', 'reviews.json', 'presets/quality', 'presets/artist')


class OutdatedLayoutError(RuntimeError):
    """The data folder still uses an older layout and must be converted first."""


def check_layout(data_root):
    """Refuse to work on a v1 data folder instead of reading it wrongly."""
    data_root = Path(data_root)
    marker = data_root / LAYOUT_FILE
    if marker.is_file():
        version = json.loads(marker.read_text(encoding='utf-8')).get('layout_version')
        if version != LAYOUT_VERSION:
            raise OutdatedLayoutError(
                Msg(
                    'server.store.data_format_version_is_not_supported',
                    'data/ format version {version} is not supported.',
                    version=version,
                )
            )
        return
    old = [name for name in V1_MARKERS if (data_root / name).exists()]
    works = data_root / 'works'
    if works.is_dir():
        old += [p.as_posix() for p in works.glob('*/expressions')]
        old += [p.as_posix() for p in works.glob('*/characters/*/outfits')]
    if old:
        raise OutdatedLayoutError(
            Msg(
                'server.store.the_data_folder_uses_the_old',
                'The data/ folder uses the old format (v1). Convert it with `python '
                'tools/migrations/v2.py --apply` before starting the server.',
            )
        )


def text_field(value, label):
    if isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(v, str) for v in value)
    ):
        return value
    raise ValueError(
        Msg(
            'server.store.must_be_text_or_a_list',
            '{value} must be text or a list of text.',
            value=label,
        )
    )


class LibraryStore:
    """Reads and writes library records. ``root`` is the application root."""

    def __init__(self, root):
        self.root = Path(root) / 'data'

    # ---- files -----------------------------------------------------------------

    @staticmethod
    def read(path):
        value = json.loads(read_text(path))
        if not isinstance(value, dict):
            raise ValueError(
                Msg('server.store.not_a_json_object', 'Not a JSON object: {path}', path=path)
            )
        return value

    def write(self, path, data):
        """Atomic write. The previous version is copied to ``data/backups`` first."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backups = self.root / 'backups'
            backups.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
            identity = '_'.join(path.relative_to(self.root).with_suffix('').parts)
            shutil.copy2(path, backups / f'{identity}.{stamp}.json')
        handle, temp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def mark_layout(self):
        marker = self.root / LAYOUT_FILE
        if not marker.exists():
            self.write(marker, {'layout_version': LAYOUT_VERSION})

    def categories(self):
        return Categories.load(self.root)

    # ---- paths -----------------------------------------------------------------

    def work_file(self, work_id):
        return self.root / 'works' / valid_id(work_id, 'work_id') / 'work.json'

    def character_file(self, work_id, character_id):
        return Location('character', work_id, character_id).directory(self.root) / 'character.json'

    def pieces_dir(self, location):
        return location.directory(self.root) / 'pieces'

    def sets_dir(self, location):
        return location.directory(self.root) / 'outfit_sets'

    def preset_file(self, preset_type, ident):
        if preset_type not in PRESET_TYPES:
            raise ValueError(
                Msg(
                    'server.store.the_preset_type_must_be_one',
                    'The preset type must be one of {preset_types}.',
                    preset_types=', '.join(PRESET_TYPES),
                )
            )
        return self.root / 'presets' / preset_type / (valid_id(ident) + '.json')

    def piece_file(self, location, category, ident):
        self.categories().parse(category)
        return self.pieces_dir(location).joinpath(*category.split('/')) / (
            valid_id(ident) + '.json'
        )

    def set_file(self, location, ident):
        return self.sets_dir(location) / (valid_id(ident) + '.json')

    def require_owner(self, location):
        owner = location.owner_file(self.root)
        if owner is not None and not owner.is_file():
            raise ValueError(
                Msg(
                    'server.store.work_or_character_not_found',
                    'Work or character not found: {name}',
                    name=location.label(),
                )
            )

    # ---- reading ---------------------------------------------------------------

    def list_works(self):
        folder = self.root / 'works'
        return (
            [self.read(path) for path in sorted(folder.glob('*/work.json'))]
            if folder.exists()
            else []
        )

    def all_locations(self):
        """Global, then every work, then every character."""
        locations = [Location('global')]
        works = self.root / 'works'
        for work_file in sorted(works.glob('*/work.json')) if works.exists() else []:
            work_id = work_file.parent.name
            locations.append(Location('work', work_id))
            for character_file in sorted(work_file.parent.glob('characters/*/character.json')):
                locations.append(Location('character', work_id, character_file.parent.name))
        return locations

    def piece_record(self, path, location, categories=None):
        """A piece file plus the fields its path implies (category, role, scope, ...)."""
        category = path.parent.relative_to(self.pieces_dir(location)).as_posix()
        parsed = (categories or self.categories()).parse(category)
        record = self.read(path)
        record.update(
            category=category, role=parsed['role'], bucket=parsed['bucket'], **location.fields()
        )
        if parsed['level']:
            record[parsed['level']] = parsed['value']
        return record

    def list_pieces(self, location, categories=None):
        """Every piece stored at one location, with the fields derived from its path."""
        categories = categories or self.categories()
        folder = self.pieces_dir(location)
        records = []
        for path in sorted(folder.rglob('*.json')) if folder.exists() else []:
            if path.name.startswith('_'):
                continue
            try:
                records.append(self.piece_record(path, location, categories))
            except ValueError:
                continue  # A folder outside the category definition is not part of the library.
        return records

    def find_piece(self, location, bucket, ident, categories=None):
        """The file of a piece by identity (bucket + id), wherever it sits below the bucket."""
        folder = self.pieces_dir(location).joinpath(*bucket.split('/'))
        categories = categories or self.categories()
        for path in sorted(folder.rglob(valid_id(ident) + '.json')) if folder.exists() else []:
            try:
                category = path.parent.relative_to(self.pieces_dir(location)).as_posix()
                if categories.parse(category)['bucket'] == bucket:
                    return path
            except ValueError:
                continue
        return None

    def resolve_piece(self, location, bucket, ident):
        """Closest piece visible from ``location``: character, then work, then global."""
        categories = self.categories()
        for scope in visible_scopes(location.scope):
            place = location.widen(scope)
            path = self.find_piece(place, bucket, ident, categories)
            if path:
                return self.piece_record(path, place, categories)
        return None

    def list_outfit_sets(self, location):
        folder = self.sets_dir(location)
        return [
            dict(self.read(path), **location.fields())
            for path in (sorted(folder.glob('*.json')) if folder.exists() else [])
        ]

    def list_presets(self, preset_type):
        folder = self.root / 'presets' / preset_type
        return [
            self.read(path) for path in (sorted(folder.glob('*.json')) if folder.exists() else [])
        ]

    def global_catalog(self):
        categories = self.categories()
        location = Location('global')
        return {
            'categories': categories.definition,
            'global_pieces': self.list_pieces(location, categories),
            'global_outfit_sets': self.list_outfit_sets(location),
            'presets': {kind: self.list_presets(kind) for kind in PRESET_TYPES},
        }

    def catalog(self, work_id):
        """Everything one work can use: global, work-shared and per-character records."""
        work_file = self.work_file(work_id)
        if not work_file.is_file():
            raise FileNotFoundError(
                Msg('server.store.work_not_found', 'Work not found: {work_id}', work_id=work_id)
            )
        catalog = self.global_catalog()
        categories = Categories(catalog['categories'])
        shared = Location('work', work_id)
        characters = []
        for path in sorted(work_file.parent.glob('characters/*/character.json')):
            character = self.read(path)
            place = Location('character', work_id, path.parent.name)
            character['pieces'] = self.list_pieces(place, categories)
            character['outfit_sets'] = self.list_outfit_sets(place)
            characters.append(character)
        catalog.update(
            work=self.read(work_file),
            work_pieces=self.list_pieces(shared, categories),
            work_outfit_sets=self.list_outfit_sets(shared),
            characters=characters,
        )
        return catalog

    # ---- writing ---------------------------------------------------------------

    def _merge(self, path, payload, drop=()):
        data = copy.deepcopy(payload)
        if path.exists():
            data = {**self.read(path), **data}  # Fields this version does not know are kept.
        for key in drop:
            data.pop(key, None)
        data['schema_version'] = SCHEMA_VERSION
        for key in ('prompt', 'negative_prompt'):
            if key in data:
                text_field(data[key], key)
        if data.get('model_family', 'anima') not in MODEL_FAMILIES:
            raise ValueError(
                Msg(
                    'server.store.model_family_must_be_anima_sdxl',
                    'model_family must be anima, sdxl or shared.',
                )
            )
        return data

    def save_work(self, payload):
        path = self.work_file(payload.get('id'))
        data = self._merge(path, payload)
        self.write(path, data)
        self.mark_layout()
        return data

    def save_character(self, work_id, payload):
        self.require_owner(Location('work', work_id))
        path = self.character_file(work_id, payload.get('id'))
        data = self._merge(path, payload, drop=('pieces', 'outfit_sets', 'work_id'))
        self.write(path, data)
        return data

    def save_piece(self, location, category, payload):
        categories = self.categories()
        parsed = categories.parse(category)
        self.require_owner(location)
        path = self.piece_file(location, category, payload.get('id'))
        existing = self.find_piece(location, parsed['bucket'], payload['id'], categories)
        if existing and existing != path:
            other = existing.parent.relative_to(self.pieces_dir(location)).as_posix()
            raise ValueError(
                Msg(
                    'server.store.a_piece_with_this_id_already',
                    'A piece with this id already exists: {other}/{id_value}',
                    other=other,
                    id_value=payload['id'],
                )
            )
        level = (parsed['level'],) if parsed['level'] else ()
        data = self._merge(path, payload, drop=(*DERIVED_PIECE_FIELDS, *level))
        if parsed['role'] == 'expression':
            # Image files are named <expression id>[_<n>].webp, so the id has a fixed shape.
            if not re.fullmatch(r'\d{3}', data['id']) or data['id'] == '000':
                raise ValueError(
                    Msg(
                        'server.store.an_expression_id_must_be_three',
                        'An expression id must be three digits from 001 to 999.',
                    )
                )
            self._check_composition(location, data)
        if parsed['role'] == 'composition' and 'suggest_slots' in data:
            if not isinstance(data['suggest_slots'], list):
                raise ValueError(
                    Msg(
                        'server.store.suggest_slots_must_be_a_list',
                        'suggest_slots must be a list of outfit slots.',
                    )
                )
            for slot in data['suggest_slots']:
                valid_id(slot, Msg('server.store.outfit_slots', 'Outfit slots'))
        self.write(path, data)
        return self.piece_record(path, location, categories)

    def _check_composition(self, location, data):
        reference = data.get('composition_id')
        if reference in (None, ''):
            data.pop('composition_id', None)
            return
        valid_id(reference, 'composition_id')
        if not self.resolve_piece(location, 'composition', reference):
            raise ValueError(
                Msg(
                    'server.store.composition_not_found',
                    'Composition not found: {reference}',
                    reference=reference,
                )
            )

    def save_outfit_set(self, location, payload):
        self.require_owner(location)
        path = self.set_file(location, payload.get('id'))
        data = self._merge(path, payload, drop=DERIVED_SET_FIELDS)
        slots = data.setdefault('slots', {})
        if not isinstance(slots, dict):
            raise ValueError(
                Msg(
                    'server.store.slots_must_map_slots_to_piece',
                    'slots must map slots to piece references.',
                )
            )
        categories = self.categories()
        for slot, reference in slots.items():
            self.slot_target(location, slot, reference, categories)
        if 'props' in data and not isinstance(data['props'], dict):
            raise ValueError(
                Msg('server.store.props_must_be_an_object', 'props must be an object.')
            )
        self.write(path, data)
        return dict(data, **location.fields())

    def slot_target(self, location, slot, reference, categories=None):
        """The piece file an outfit-set slot points at; raises when it does not exist."""
        valid_id(slot, Msg('server.store.outfit_slots', 'Outfit slots'))
        if not isinstance(reference, dict) or reference.get('scope') not in visible_scopes(
            location.scope
        ):
            raise ValueError(
                Msg(
                    'server.store.this_piece_scope_cannot_be_used',
                    '{slot}: this piece scope cannot be used here.',
                    slot=slot,
                )
            )
        place = location.widen(reference['scope'])
        path = self.find_piece(place, f'outfit/{slot}', valid_id(reference.get('id')), categories)
        if path is None:
            raise ValueError(
                Msg(
                    'server.store.outfit_piece_not_found',
                    '{slot}: outfit piece not found ({scope}/{id_value}).',
                    slot=slot,
                    scope=reference['scope'],
                    id_value=reference['id'],
                )
            )
        return path

    def save_preset(self, preset_type, payload):
        path = self.preset_file(preset_type, payload.get('id'))
        data = self._merge(path, payload)
        if preset_type == 'generation' and not isinstance(data.setdefault('settings', {}), dict):
            raise ValueError(
                Msg(
                    'server.store.generation_settings_must_be_an_object',
                    'Generation settings must be an object.',
                )
            )
        if preset_type == 'expression_set':
            expressions = data.setdefault('expressions', [])
            if not isinstance(expressions, list):
                raise ValueError(
                    Msg('server.store.expressions_must_be_a_list', 'expressions must be a list.')
                )
            for reference in expressions:
                if not isinstance(reference, dict):
                    raise ValueError(
                        Msg(
                            'server.store.an_expression_reference_looks_like',
                            'An expression reference looks like {"id": "001"}.',
                        )
                    )
                valid_id(reference.get('id'), Msg('server.store.expression_id', 'expression id'))
        self.write(path, data)
        return data

    def save_categories(self, definition):
        Categories(definition)
        self.write(self.root / 'pieces' / CATEGORIES_FILE, definition)
