"""Revision-checked editing of the library. Deleting moves records to a trash."""

import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime

from ..i18n import Msg
from ..lora import records as lora_records
from ..util import replace_file
from . import references
from .layout import Location, valid_id, visible_scopes
from .store import SCHEMA_VERSION

KINDS = ('work', 'character', 'piece', 'outfit_set', 'preset', 'dataset', 'lora')
FOLDER_KINDS = ('work', 'character')  # Stored as a folder; everything inside moves with it.
RENAMABLE = ('work', 'character', 'outfit_set')
MOVABLE = ('piece', 'outfit_set')
ADDRESS_FIELDS = ('kind', 'scope', 'work_id', 'character_id', 'category', 'preset_type')
LIBRARY_FOLDERS = ('works', 'pieces', 'outfit_sets', 'presets', 'loras')
CHANGED = Msg(
    'server.service.changed_elsewhere_your_draft_is_kept',
    'Changed elsewhere. Your draft is kept; compare it with the latest version.',
)


class ConflictError(ValueError):
    """The record changed since the caller read it, or the code is already taken."""


def _now():
    return datetime.now(UTC).isoformat()


def _remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


class _Undo:
    """Copies of everything an operation is about to change, so it can be rolled back."""

    def __init__(self, folder):
        self.folder = folder
        self.saved = []
        self.created = []

    def keep(self, path):
        self.folder.mkdir(parents=True, exist_ok=True)
        copy = self.folder / f'item-{len(self.saved)}'
        (shutil.copytree if path.is_dir() else shutil.copy2)(path, copy)
        self.saved.append((path, copy))

    def rollback(self):
        for path in self.created:
            _remove(path)
        for path, copy in self.saved:
            _remove(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if copy.is_dir() else shutil.copy2)(copy, path)


class Library:
    def __init__(self, store, lock):
        self.store, self.lock = store, lock
        self.root = store.root.resolve()
        self.trash = self.root / 'trash'

    # ---- addressing ------------------------------------------------------------

    def path(self, body, ident):
        kind = body.get('kind')
        if kind == 'work':
            return self.store.work_file(ident)
        if kind == 'character':
            return self.store.character_file(body.get('work_id'), ident)
        if kind == 'piece':
            return self.store.piece_file(Location.of(body), body.get('category'), ident)
        if kind == 'outfit_set':
            return self.store.set_file(Location.of(body), ident)
        if kind == 'preset':
            return self.store.preset_file(body.get('preset_type'), ident)
        if kind == 'dataset':
            return lora_records.dataset_file(
                self.store, body.get('work_id'), body.get('character_id'), ident
            )
        if kind == 'lora':
            return lora_records.lora_file(self.store, ident)
        raise ValueError(Msg('server.service.unsupported_item', 'Unsupported item.'))

    def _entity(self, body, path):
        if body['kind'] == 'piece':
            return self.store.piece_record(path, Location.of(body))
        if body['kind'] == 'outfit_set':
            return dict(self.store.read(path), **Location.of(body).fields())
        return self.store.read(path)

    @staticmethod
    def revision(path, kind):
        if not path.exists():
            return None
        digest = hashlib.sha256()
        files = sorted(path.parent.rglob('*.json')) if kind in FOLDER_KINDS else [path]
        for item in files:
            digest.update(item.relative_to(path.parent).as_posix().encode())
            digest.update(item.read_bytes())
        return digest.hexdigest()

    def get(self, body):
        with self.lock:
            path = self.path(body, body.get('id'))
            return {
                'entity': self._entity(body, path),
                'revision': self.revision(path, body['kind']),
            }

    def version(self):
        """Changes whenever any library file changes."""
        digest = hashlib.sha256()
        with self.lock:
            for folder in LIBRARY_FOLDERS:
                for path in sorted((self.root / folder).rglob('*.json')):
                    stat = path.stat()
                    digest.update(
                        f'{path.relative_to(self.root)}:{stat.st_mtime_ns}:{stat.st_size}'.encode()
                    )
        return {'revision': digest.hexdigest()}

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            replace_file(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    # ---- saving ----------------------------------------------------------------

    def save(self, body):
        kind, payload = body.get('kind'), body.get('payload')
        if kind not in KINDS:
            raise ValueError(Msg('server.service.unsupported_item', 'Unsupported item.'))
        if not isinstance(payload, dict):
            raise ValueError(Msg('server.service.item_data_is_required', 'Item data is required.'))
        ident = valid_id(payload.get('id'))
        with self.lock:
            original = body.get('original_id', ident)
            if original != ident:
                return self._rename(body, original)
            path = self.path(body, ident)
            revision = self.revision(path, kind)
            if 'expected_revision' not in body or revision != body['expected_revision']:
                raise ConflictError(CHANGED)
            if revision is None:
                self._require_free(path, kind)
            entity = self._store_save(body, payload)
            return {'ok': True, 'entity': entity, 'revision': self.revision(path, kind)}

    def _store_save(self, body, payload):
        kind = body['kind']
        if kind == 'work':
            return self.store.save_work(payload)
        if kind == 'character':
            return self.store.save_character(body.get('work_id'), payload)
        if kind == 'piece':
            return self.store.save_piece(Location.of(body), body.get('category'), payload)
        if kind == 'outfit_set':
            return self.store.save_outfit_set(Location.of(body), payload)
        if kind == 'dataset':
            return lora_records.save_dataset(
                self.store, body.get('work_id'), body.get('character_id'), payload
            )
        if kind == 'lora':
            return lora_records.save_lora(self.store, payload)
        return self.store.save_preset(body.get('preset_type'), payload)

    def _retired(self, path):
        return self.root / 'retired' / (path.relative_to(self.root).as_posix() + '.json')

    def _require_free(
        self,
        path,
        kind,
        message=Msg(
            'server.service.this_code_was_used_before_use',
            'This code was used before. Use another code.',
        ),
    ):
        """A code that was renamed away or sits in the trash must not get a new meaning."""
        if self._retired(path).exists():
            raise ConflictError(message)
        target = path.parent if kind in FOLDER_KINDS else path
        for item in self.list_trash()['items']:
            trashed = self.root / item['original_path']
            if target == trashed or target.is_relative_to(trashed):
                raise ConflictError(
                    Msg(
                        'server.service.this_code_belongs_to_an_item',
                        'This code belongs to an item in the trash. Restore it or use another '
                        'code.',
                    )
                )

    def _rename(self, body, original):
        """Change a code. Images and queue history keep the code they were made with."""
        kind, payload = body['kind'], body['payload']
        if kind not in RENAMABLE:
            raise ValueError(
                Msg(
                    'server.service.this_item_s_code_cannot_be',
                    "This item's code cannot be changed.",
                )
            )
        source, target = self.path(body, original), self.path(body, payload['id'])
        if not source.is_file():
            raise ValueError(
                Msg(
                    'server.service.the_item_to_change_was_not', 'The item to change was not found.'
                )
            )
        if (
            'expected_revision' not in body
            or self.revision(source, kind) != body['expected_revision']
        ):
            raise ConflictError(CHANGED)
        folder = kind in FOLDER_KINDS
        origin, destination = (source.parent, target.parent) if folder else (source, target)
        if destination.exists():
            raise ConflictError(
                Msg('server.service.this_code_is_already_in_use', 'This code is already in use.')
            )
        self._require_free(
            target,
            kind,
            Msg('server.service.this_code_was_used_before', 'This code was used before.'),
        )

        rewrites = []
        if kind == 'outfit_set':
            for path in references.default_outfit_users(self.store, Location.of(body), original):
                rewrites.append((path, dict(self.store.read(path), default_outfit=payload['id'])))
        data = {**self.store.read(source), **payload}
        marker = self._retired(source)
        undo = _Undo(self.root / 'backups' / ('rename-' + uuid.uuid4().hex))
        try:
            undo.keep(origin)
            for path, _ in rewrites:
                undo.keep(path)
            undo.created += [destination, marker]
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(origin, destination)
            self._store_save(body, data)
            for path, record in rewrites:
                self.store.write(path, record)
            self.write(marker, {'kind': kind, 'old_id': original, 'new_id': payload['id']})
            self.write(
                undo.folder / 'manifest.json',
                {
                    'kind': kind,
                    'old_id': original,
                    'new_id': payload['id'],
                    'source_path': origin.relative_to(self.root).as_posix(),
                    'updated_references': [
                        path.relative_to(self.root).as_posix() for path, _ in rewrites
                    ],
                    'renamed_at': _now(),
                },
            )
        except Exception:
            undo.rollback()
            raise
        return {
            'ok': True,
            'entity': self._entity(body, target),
            'revision': self.revision(target, kind),
            'previous_id': original,
        }

    # ---- moving between scopes -------------------------------------------------

    def move(self, body):
        """Move a piece or an outfit set to another scope (and, for a piece, folder)."""
        kind, ident, destination = body.get('kind'), body.get('id'), body.get('to')
        if kind not in MOVABLE:
            raise ValueError(
                Msg(
                    'server.service.only_pieces_and_outfit_sets_can',
                    'Only pieces and outfit sets can be moved.',
                )
            )
        if not isinstance(destination, dict):
            raise ValueError(Msg('server.service.a_target_is_required', 'A target is required.'))
        with self.lock:
            here, there = Location.of(body), Location.of(destination)
            source = self.path(body, ident)
            if not source.is_file():
                raise ValueError(
                    Msg(
                        'server.service.the_item_to_move_was_not', 'The item to move was not found.'
                    )
                )
            if self.revision(source, kind) != body.get('expected_revision'):
                raise ConflictError(CHANGED)
            self.store.require_owner(there)
            new_body = {key: body.get(key) for key in ADDRESS_FIELDS}
            new_body.update(
                scope=there.scope, work_id=there.work_id, character_id=there.character_id
            )
            if kind == 'piece':
                new_body['category'] = destination.get('category') or body.get('category')
                rewrites = self._plan_piece_move(
                    body, ident, here, there, new_body['category'], source
                )
            else:
                rewrites = self._plan_set_move(ident, here, there, source)
            target = self.path(new_body, ident)
            if target == source:
                raise ValueError(Msg('server.service.already_there', 'Already there.'))
            if target.exists():
                raise ConflictError(
                    Msg(
                        'server.service.an_item_with_the_same_code',
                        'An item with the same code is already there.',
                    )
                )
            self._require_free(target, kind)
            undo = _Undo(self.root / 'backups' / ('move-' + uuid.uuid4().hex))
            try:
                undo.keep(source)
                for path, _ in rewrites:
                    undo.keep(path)
                undo.created.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                for path, record in rewrites:
                    self.store.write(path, record)
            except Exception:
                undo.rollback()
                raise
            address = {key: value for key, value in new_body.items() if value is not None}
            return {
                'ok': True,
                'address': {**address, 'id': ident},
                'entity': self._entity(new_body, target),
                'revision': self.revision(target, kind),
            }

    def _plan_piece_move(self, body, ident, here, there, new_category, source):
        categories = self.store.categories()
        bucket = categories.parse(body.get('category'))['bucket']
        if categories.parse(new_category)['bucket'] != bucket:
            raise ValueError(
                Msg(
                    'server.service.cannot_move_to_a_category_of',
                    'Cannot move to a category of another role.',
                )
            )
        existing = self.store.find_piece(there, bucket, ident, categories)
        if existing and existing != source:
            raise ConflictError(
                Msg(
                    'server.service.a_piece_with_the_same_id',
                    'A piece with the same id is already there.',
                )
            )
        rewrites = []
        for place, set_path, slot in references.slot_references(self.store, here, bucket, ident):
            if not place.can_see(there):
                raise ValueError(
                    Msg(
                        'server.service.outfit_set_uses_this_piece_so',
                        'Outfit set {name}/{set_path} uses this piece, so it cannot move to that '
                        'scope.',
                        name=place.label(),
                        set_path=set_path.stem,
                    )
                )
            record = self.store.read(set_path)
            record['slots'][slot] = {**record['slots'][slot], 'scope': there.scope}
            rewrites.append((set_path, record))
        if bucket == 'composition':
            for place, path in references.composition_users(self.store, here, ident):
                if not place.can_see(there) and not self._wider_copy(here, bucket, ident):
                    raise ValueError(
                        Msg(
                            'server.service.expression_uses_this_composition_so_it',
                            'Expression {name}/{path} uses this composition, so it cannot move to '
                            'that scope.',
                            name=place.label(),
                            path=path.stem,
                        )
                    )
        return rewrites

    def _plan_set_move(self, ident, here, there, source):
        for slot, reference in self.store.read(source).get('slots', {}).items():
            if not there.can_see(here.widen(reference['scope'])):
                raise ValueError(
                    Msg(
                        'server.service.piece_would_not_be_visible_from',
                        'Piece {slot} would not be visible from the new place. Move the piece '
                        'first.',
                        slot=slot,
                    )
                )
        for path in references.default_outfit_users(self.store, here, ident):
            user = Location('character', path.parent.parent.parent.name, path.parent.name)
            if not user.can_see(there):
                raise ValueError(
                    Msg(
                        'server.service.this_is_the_default_outfit_of',
                        'This is the default outfit of {name}; it cannot move to that scope.',
                        name=user.label(),
                    )
                )
        return []

    def _wider_copy(self, location, bucket, ident):
        """True when the same identity also exists at a wider scope (this one overrides it)."""
        return any(
            self.store.find_piece(location.widen(scope), bucket, ident)
            for scope in visible_scopes(location.scope)[1:]
        )

    # ---- trash -----------------------------------------------------------------

    def list_trash(self):
        items = []
        with self.lock:
            for path in sorted(self.trash.glob('*/manifest.json'), reverse=True):
                try:
                    item = self.store.read(path)
                    if not item.get('restored_at') and (path.parent / 'content').exists():
                        items.append(item)
                except (OSError, ValueError):
                    continue
        return {'items': items}

    def _require_unreferenced(self, body, ident):
        kind = body['kind']
        if kind == 'piece':
            location = Location.of(body)
            bucket = self.store.categories().parse(body.get('category'))['bucket']
            slots = references.slot_references(self.store, location, bucket, ident)
            if slots:
                names = ', '.join(f'{place.label()}/{path.stem}' for place, path, _ in slots[:3])
                raise ValueError(
                    Msg(
                        'server.service.an_outfit_set_uses_this_piece',
                        'An outfit set uses this piece ({names}). Change the set first.',
                        names=names,
                    )
                )
            if self._wider_copy(location, bucket, ident):
                return  # The wider copy takes over for every id-based reference.
            if bucket == 'composition' and references.composition_users(
                self.store, location, ident
            ):
                raise ValueError(
                    Msg(
                        'server.service.an_expression_uses_this_composition_change',
                        'An expression uses this composition. Change that reference first.',
                    )
                )
            presets = references.preset_references(self.store, bucket, ident)
            if presets and not references.copies_elsewhere(self.store, location, bucket, ident):
                raise ValueError(
                    Msg(
                        'server.service.a_preset_uses_this_piece',
                        'A preset uses this piece: {presets}',
                        presets=', '.join(presets[:3]),
                    )
                )
        elif kind == 'outfit_set':
            location = Location.of(body)
            users = references.default_outfit_users(self.store, location, ident)
            wider = any(
                self.store.set_file(location.widen(scope), ident).is_file()
                for scope in visible_scopes(location.scope)[1:]
            )
            if users and not wider:
                raise ValueError(
                    Msg(
                        'server.service.this_is_a_default_outfit_change',
                        "This is a default outfit. Change the character's default outfit first.",
                    )
                )
        elif kind == 'preset' and body.get('preset_type') == 'generation':
            if any(
                preset.get('generation_preset_id') == ident
                for preset in self.store.list_presets('combination')
            ):
                raise ValueError(
                    Msg(
                        'server.service.a_combination_preset_uses_these_generation',
                        'A combination preset uses these generation settings.',
                    )
                )

    def delete(self, body):
        kind, ident = body.get('kind'), body.get('id')
        with self.lock:
            path = self.path(body, ident)
            if not path.exists():
                raise ValueError(Msg('server.service.already_deleted', 'Already deleted.'))
            if self.revision(path, kind) != body.get('expected_revision'):
                raise ConflictError(
                    Msg(
                        'server.service.the_item_changed_before_deletion_check',
                        'The item changed before deletion. Check the latest version.',
                    )
                )
            entity = self.store.read(path)
            self._require_unreferenced(body, ident)
            source = path.parent if kind in FOLDER_KINDS else path
            trash_id = datetime.now(UTC).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex
            address = {key: body[key] for key in ADDRESS_FIELDS if body.get(key) is not None}
            self.write(
                self.trash / trash_id / 'manifest.json',
                {
                    'id': trash_id,
                    'schema_version': SCHEMA_VERSION,
                    **address,
                    'entity_id': ident,
                    'name': entity.get('name', ident),
                    'original_path': source.relative_to(self.root).as_posix(),
                    'deleted_at': _now(),
                },
            )
            os.replace(source, self.trash / trash_id / 'content')
            return {'ok': True, 'trash_id': trash_id}

    def restore(self, trash_id):
        with self.lock:
            directory = self.trash / valid_id(trash_id)
            manifest = self.store.read(directory / 'manifest.json')
            target = (self.root / manifest['original_path']).resolve()
            if not any(target.is_relative_to(self.root / folder) for folder in LIBRARY_FOLDERS):
                raise ValueError(
                    Msg('server.service.restore_path_not_allowed', 'Restore path not allowed.')
                )
            if target.exists():
                raise ConflictError(
                    Msg(
                        'server.service.something_is_already_at_that_place',
                        'Something is already at that place. Existing files are not overwritten.',
                    )
                )
            kind = manifest.get('kind')
            if kind == 'character' and not self.store.work_file(manifest['work_id']).is_file():
                raise ValueError(
                    Msg(
                        'server.service.restore_the_parent_work_first',
                        'Restore the parent work first.',
                    )
                )
            if (
                kind == 'dataset'
                and not self.store.character_file(
                    manifest['work_id'], manifest['character_id']
                ).is_file()
            ):
                raise ValueError(
                    Msg(
                        'server.service.restore_the_parent_character_first',
                        'Restore the parent character first.',
                    )
                )
            if kind in MOVABLE:
                try:
                    self.store.require_owner(Location.of(manifest))
                except ValueError:
                    raise ValueError(
                        Msg(
                            'server.service.restore_the_parent_work_or_character',
                            'Restore the parent work or character first.',
                        )
                    ) from None
            if kind == 'piece':
                bucket = self.store.categories().parse(manifest['category'])['bucket']
                if self.store.find_piece(Location.of(manifest), bucket, manifest['entity_id']):
                    raise ConflictError(
                        Msg(
                            'server.service.a_piece_with_this_id_already',
                            'A piece with this id already exists.',
                        )
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(directory / 'content', target)
            manifest['restored_at'] = _now()
            self.write(directory / 'manifest.json', manifest)
            return {'ok': True}
