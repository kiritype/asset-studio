"""Where library entities live on disk and how piece categories are read.

Layout (below ``data/``)::

    pieces/_categories.json                     category definition
    pieces/<category>/<id>.json                 global pieces
    outfit_sets/<id>.json                       global outfit sets
    works/<W>/work.json
    works/<W>/pieces/…  works/<W>/outfit_sets/… pieces and sets shared by one work
    works/<W>/characters/<C>/character.json
    works/<W>/characters/<C>/pieces/…           pieces bound to one character
    works/<W>/characters/<C>/outfit_sets/…
    presets/<type>/<id>.json                    generation, combination, expression_set
"""

import copy
import json
import re

from ..i18n import Msg

LAYOUT_VERSION = 2
LAYOUT_FILE = 'layout.json'
SCOPES = ('global', 'work', 'character')
PRESET_TYPES = ('generation', 'combination', 'expression_set')
CATEGORIES_FILE = '_categories.json'
MAX_CATEGORY_DEPTH = 8
_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# The top-level folder decides how a piece takes part in composition. A role with a
# ``level`` gives its first sub-folder a meaning (outfit slot, expression rating, ...);
# any deeper folder is only a way to keep files tidy.
DEFAULT_CATEGORIES = {
    'schema_version': 2,
    'roles': {
        'outfit': {
            'label': Msg('server.layout.outfit', 'Outfit'),
            'level': 'slot',
            'order': ['full', 'hands', 'top', 'bottom', 'shoes'],
            'labels': {
                'full': Msg('server.layout.all', 'All'),
                'hands': Msg('server.layout.hands', 'Hands'),
                'top': Msg('server.layout.top', 'Top'),
                'bottom': Msg('server.layout.bottom', 'Bottom'),
                'shoes': Msg('server.layout.shoes', 'Shoes'),
            },
        },
        'expression': {
            'label': Msg('server.layout.expression', 'Expression'),
            'level': 'rating',
            'order': ['sfw', 'nsfw'],
            'labels': {
                'sfw': Msg('server.layout.general', 'General'),
                'nsfw': Msg('server.layout.adult', 'Adult'),
            },
            'fixed_levels': True,
            'unique_across_levels': True,
        },
        'composition': {'label': Msg('server.layout.composition', 'Composition')},
        'artist': {'label': Msg('server.layout.style', 'Style')},
        'common': {
            'label': Msg('server.layout.common', 'Common'),
            'level': 'target',
            'order': ['positive', 'negative'],
            'labels': {
                'positive': Msg('server.layout.positive', 'Positive'),
                'negative': Msg('server.layout.negative', 'Negative'),
            },
            'fixed_levels': True,
        },
    },
    'compose_order': [
        'work',
        'common',
        'artist',
        'composition',
        'appearance',
        'expression',
        'outfit',
    ],
}
# Positions in ``compose_order`` that are not piece roles.
BUILT_IN_POSITIONS = ('work', 'appearance')


def valid_id(value, label='id'):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(
            Msg(
                'server.layout.use_only_letters_digits_and_1',
                "{value}: use only letters, digits, '_' and '-' (1–64 characters).",
                value=label,
            )
        )
    return value


def visible_scopes(scope):
    """Scopes a record stored at ``scope`` can refer to, closest first."""
    if scope not in SCOPES:
        raise ValueError(
            Msg(
                'server.layout.scope_must_be_global_work_or',
                'Scope must be global, work or character.',
            )
        )
    return SCOPES[SCOPES.index(scope) :: -1]


class Location:
    """One of the three places pieces and outfit sets can be stored."""

    def __init__(self, scope, work_id=None, character_id=None):
        if scope not in SCOPES:
            raise ValueError(
                Msg(
                    'server.layout.scope_must_be_global_work_or',
                    'Scope must be global, work or character.',
                )
            )
        self.scope = scope
        self.work_id = valid_id(work_id, 'work_id') if scope != 'global' else None
        self.character_id = valid_id(character_id, 'character_id') if scope == 'character' else None

    @classmethod
    def of(cls, body):
        return cls(body.get('scope'), body.get('work_id'), body.get('character_id'))

    def directory(self, data_root):
        if self.scope == 'global':
            return data_root
        work = data_root / 'works' / self.work_id
        return work if self.scope == 'work' else work / 'characters' / self.character_id

    def owner_file(self, data_root):
        """The record that must exist before anything is stored here."""
        if self.scope == 'global':
            return None
        name = 'work.json' if self.scope == 'work' else 'character.json'
        return self.directory(data_root) / name

    def widen(self, scope):
        """The enclosing location at a wider scope (character -> work -> global)."""
        if scope not in visible_scopes(self.scope):
            raise ValueError(
                Msg(
                    'server.layout.that_scope_is_not_visible_from',
                    'That scope is not visible from here.',
                )
            )
        return Location(scope, self.work_id, self.character_id)

    def can_see(self, other):
        if other.scope not in visible_scopes(self.scope):
            return False
        return self.widen(other.scope).fields() == other.fields()

    def fields(self):
        result = {'scope': self.scope}
        if self.work_id:
            result['work_id'] = self.work_id
        if self.character_id:
            result['character_id'] = self.character_id
        return result

    def label(self):
        """Short name for messages shown to the user."""
        if self.scope == 'global':
            return Msg('server.layout.global', 'Global')
        return (
            Msg('server.layout.shared_in', 'Shared in {work_id}', work_id=self.work_id)
            if self.scope == 'work'
            else f'{self.work_id}/{self.character_id}'
        )

    def __eq__(self, other):
        return isinstance(other, Location) and self.fields() == other.fields()

    def __hash__(self):
        return hash((self.scope, self.work_id, self.character_id))

    def __repr__(self):
        return '/'.join(filter(None, (self.scope, self.work_id, self.character_id)))


def _default_labels():
    labels = {}
    for role in DEFAULT_CATEGORIES['roles'].values():
        for label in [role['label'], *role.get('labels', {}).values()]:
            labels[label.key] = label
    return labels


DEFAULT_LABELS = _default_labels()
# Default labels as data/ stored them before labels were translated on the page.
LEGACY_LABELS = {
    '의상': 'server.layout.outfit',
    '전체': 'server.layout.all',
    '손': 'server.layout.hands',
    '상의': 'server.layout.top',
    '하의': 'server.layout.bottom',
    '신발': 'server.layout.shoes',
    '감정·동작': 'server.layout.expression',
    '일반': 'server.layout.general',
    '성인': 'server.layout.adult',
    '구도': 'server.layout.composition',
    '화풍': 'server.layout.style',
    '공통': 'server.layout.common',
    '긍정': 'server.layout.positive',
    '제외': 'server.layout.negative',
}


def _label(value):
    """A default label as a translatable ``Msg``; labels people typed stay as they are."""
    if isinstance(value, dict) and value.get('i18n') in DEFAULT_LABELS:
        return DEFAULT_LABELS[value['i18n']]
    if isinstance(value, str) and value in LEGACY_LABELS:
        return DEFAULT_LABELS[LEGACY_LABELS[value]]
    return value


class Categories:
    """The category definition: roles, the meaning of their first level, compose order."""

    def __init__(self, definition=None):
        self.definition = copy.deepcopy(definition or DEFAULT_CATEGORIES)
        for role in (self.definition.get('roles') or {}).values():
            if isinstance(role, dict):
                if 'label' in role:
                    role['label'] = _label(role['label'])
                if isinstance(role.get('labels'), dict):
                    role['labels'] = {k: _label(v) for k, v in role['labels'].items()}
        roles = self.definition.get('roles')
        if not isinstance(roles, dict) or not roles:
            raise ValueError(
                Msg(
                    'server.layout.the_category_definition_needs_roles',
                    'The category definition needs roles.',
                )
            )
        for name, role in roles.items():
            valid_id(name, Msg('server.layout.category_name', 'Category name'))
            if not isinstance(role, dict):
                raise ValueError(
                    Msg(
                        'server.layout.the_category_definition_is_invalid',
                        'The category definition is invalid: {name}',
                        name=name,
                    )
                )
        order = self.definition.get('compose_order')
        if not isinstance(order, list) or any(
            item not in roles and item not in BUILT_IN_POSITIONS for item in order
        ):
            raise ValueError(
                Msg(
                    'server.layout.compose_order_may_only_list_category',
                    'compose_order may only list category names, work and appearance.',
                )
            )
        missing = [name for name in (*roles, *BUILT_IN_POSITIONS) if name not in order]
        if missing:
            raise ValueError(
                Msg(
                    'server.layout.missing_from_compose_order',
                    'Missing from compose_order: {missing}',
                    missing=', '.join(missing),
                )
            )
        self.roles = roles
        self.compose_order = order

    @classmethod
    def load(cls, data_root):
        path = data_root / 'pieces' / CATEGORIES_FILE
        if not path.is_file():
            return cls()
        return cls(json.loads(path.read_text(encoding='utf-8')))

    def parse(self, category):
        """Split a category path into its role, level value and identity bucket.

        Ids are unique inside a bucket: ``outfit/top``, ``common/positive``, ``composition``,
        and all of ``expression`` (the image file name is the expression id).
        """
        if not isinstance(category, str):
            raise ValueError(
                Msg('server.layout.a_category_path_is_required', 'A category path is required.')
            )
        segments = category.split('/')
        if not 1 <= len(segments) <= MAX_CATEGORY_DEPTH:
            raise ValueError(
                Msg(
                    'server.layout.a_category_path_has_1_to',
                    'A category path has 1 to {max_category_depth} levels.',
                    max_category_depth=MAX_CATEGORY_DEPTH,
                )
            )
        for segment in segments:
            valid_id(segment, Msg('server.layout.category_folder_name', 'Category folder name'))
        role = self.roles.get(segments[0])
        if role is None:
            raise ValueError(
                Msg(
                    'server.layout.undefined_category',
                    'Undefined category: {segments}',
                    segments=segments[0],
                )
            )
        result = {
            'role': segments[0],
            'level': role.get('level'),
            'value': None,
            'bucket': segments[0],
        }
        if role.get('level'):
            if len(segments) < 2:
                raise ValueError(
                    Msg(
                        'server.layout.needs_a_subcategory',
                        '{segments} needs a subcategory.',
                        segments=role.get('label', segments[0]),
                    )
                )
            value = segments[1]
            if role.get('fixed_levels') and value not in role.get('order', []):
                raise ValueError(
                    Msg(
                        'server.layout.the_subcategory_of_must_be_one',
                        'The subcategory of {segments} must be one of {order}.',
                        segments=role.get('label', segments[0]),
                        order=', '.join(role.get('order', [])),
                    )
                )
            result['value'] = value
            if not role.get('unique_across_levels'):
                result['bucket'] = f'{segments[0]}/{value}'
        return result

    def ordered(self, role, values):
        """Sort level values (e.g. outfit slots) by the defined order; unknown ones last."""
        order = self.roles.get(role, {}).get('order', [])
        return sorted(values, key=lambda v: (order.index(v) if v in order else len(order), v))

    def piece_roles(self):
        """Roles in compose order."""
        return [name for name in self.compose_order if name in self.roles]
