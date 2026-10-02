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
            'label': '의상',
            'level': 'slot',
            'order': ['full', 'hands', 'top', 'bottom', 'shoes'],
            'labels': {
                'full': '전체',
                'hands': '손',
                'top': '상의',
                'bottom': '하의',
                'shoes': '신발',
            },
        },
        'expression': {
            'label': '감정·동작',
            'level': 'rating',
            'order': ['sfw', 'nsfw'],
            'labels': {'sfw': '일반', 'nsfw': '성인'},
            'fixed_levels': True,
            'unique_across_levels': True,
        },
        'composition': {'label': '구도'},
        'artist': {'label': '화풍'},
        'common': {
            'label': '공통',
            'level': 'target',
            'order': ['positive', 'negative'],
            'labels': {'positive': '긍정', 'negative': '제외'},
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
        raise ValueError(f"{label}: 영문·숫자·'_'·'-'만 쓸 수 있습니다 (1~64자).")
    return value


def visible_scopes(scope):
    """Scopes a record stored at ``scope`` can refer to, closest first."""
    if scope not in SCOPES:
        raise ValueError('범위는 global, work, character 중 하나여야 합니다.')
    return SCOPES[SCOPES.index(scope) :: -1]


class Location:
    """One of the three places pieces and outfit sets can be stored."""

    def __init__(self, scope, work_id=None, character_id=None):
        if scope not in SCOPES:
            raise ValueError('범위는 global, work, character 중 하나여야 합니다.')
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
            raise ValueError('이 위치에서 볼 수 없는 범위입니다.')
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
            return '전역'
        return (
            f'{self.work_id} 공용'
            if self.scope == 'work'
            else f'{self.work_id}/{self.character_id}'
        )

    def __eq__(self, other):
        return isinstance(other, Location) and self.fields() == other.fields()

    def __hash__(self):
        return hash((self.scope, self.work_id, self.character_id))

    def __repr__(self):
        return '/'.join(filter(None, (self.scope, self.work_id, self.character_id)))


class Categories:
    """The category definition: roles, the meaning of their first level, compose order."""

    def __init__(self, definition=None):
        self.definition = copy.deepcopy(definition or DEFAULT_CATEGORIES)
        roles = self.definition.get('roles')
        if not isinstance(roles, dict) or not roles:
            raise ValueError('분류 정의에 roles가 필요합니다.')
        for name, role in roles.items():
            valid_id(name, '분류 이름')
            if not isinstance(role, dict):
                raise ValueError(f'분류 정의가 올바르지 않습니다: {name}')
        order = self.definition.get('compose_order')
        if not isinstance(order, list) or any(
            item not in roles and item not in BUILT_IN_POSITIONS for item in order
        ):
            raise ValueError('compose_order에는 분류 이름과 work, appearance만 쓸 수 있습니다.')
        missing = [name for name in (*roles, *BUILT_IN_POSITIONS) if name not in order]
        if missing:
            raise ValueError('compose_order에 빠진 항목: ' + ', '.join(missing))
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
            raise ValueError('분류 경로가 필요합니다.')
        segments = category.split('/')
        if not 1 <= len(segments) <= MAX_CATEGORY_DEPTH:
            raise ValueError(f'분류 경로는 1~{MAX_CATEGORY_DEPTH}단계여야 합니다.')
        for segment in segments:
            valid_id(segment, '분류 폴더 이름')
        role = self.roles.get(segments[0])
        if role is None:
            raise ValueError(f'정의되지 않은 분류입니다: {segments[0]}')
        result = {
            'role': segments[0],
            'level': role.get('level'),
            'value': None,
            'bucket': segments[0],
        }
        if role.get('level'):
            if len(segments) < 2:
                raise ValueError(f'{role.get("label", segments[0])}은(는) 하위 분류가 필요합니다.')
            value = segments[1]
            if role.get('fixed_levels') and value not in role.get('order', []):
                raise ValueError(
                    f'{role.get("label", segments[0])}의 하위 분류는 '
                    f'{", ".join(role.get("order", []))} 중 하나여야 합니다.'
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
