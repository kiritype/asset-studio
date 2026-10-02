"""Lab generation: one prompt, tried with several seeds or one changing setting.

Lab jobs run through the same queue and worker as asset jobs but are not assets: they
carry no work/character/outfit, skip VLM review and are saved under
``outputs/_lab/<date>/``.
"""

import copy
import secrets
import uuid

from ..util import now
from .workflow import validate_settings

MAX_PROMPT_LENGTH = 30000
MAX_COUNT = 16
MAX_VARIANTS = 12
MAX_JOBS = 48
# Settings a sweep may change. The seed stays the same so only that value differs.
SWEEP_KEYS = {
    'cfg': float,
    'steps': int,
    'sampler': str,
    'scheduler': str,
    'clip_skip': int,
    'lora_strength': float,
}
SWEEP_LABELS = {
    'cfg': 'CFG',
    'steps': 'Steps',
    'sampler': '샘플러',
    'scheduler': '스케줄러',
    'clip_skip': 'CLIP skip',
    'lora_strength': 'LoRA 강도',
}


def _text(value, name):
    if not isinstance(value, str) or len(value) > MAX_PROMPT_LENGTH:
        raise ValueError(f'{name}는 {MAX_PROMPT_LENGTH:,}자 이하의 문자열이어야 합니다.')
    return value.strip()


def _variants(settings, sweep):
    """``[(label, changes)]``: one entry per tried value, or the settings as they are."""
    if not sweep:
        return [('', {})]
    key = sweep.get('key')
    if key not in SWEEP_KEYS:
        raise ValueError('바꿔 볼 값은 ' + ', '.join(SWEEP_LABELS.values()) + ' 중 하나입니다.')
    values = sweep.get('values')
    if not isinstance(values, list) or not 2 <= len(values) <= MAX_VARIANTS:
        raise ValueError(f'비교할 값을 2~{MAX_VARIANTS}개 입력하세요.')
    try:
        values = [SWEEP_KEYS[key](value) for value in values]
    except (TypeError, ValueError) as error:
        raise ValueError(f'{SWEEP_LABELS[key]} 값을 확인하세요.') from error
    if key != 'lora_strength':
        return [(f'{SWEEP_LABELS[key]} {value}', {key: value}) for value in values]
    index = sweep.get('lora_index', 0)
    loras = settings.get('loras') or []
    if not isinstance(index, int) or not 0 <= index < len(loras):
        raise ValueError('강도를 바꿀 LoRA를 고르세요.')
    result = []
    for value in values:
        changed = copy.deepcopy(loras)
        changed[index].update(strength_model=value, strength_clip=value)
        result.append((f'LoRA 강도 {value}', {'loras': changed}))
    return result


class LabMixin:
    """Lab part of ``Studio``'s queue."""

    def enqueue_lab(self, body):
        positive = _text(body.get('positive', ''), '긍정 프롬프트')
        negative = _text(body.get('negative', ''), '부정 프롬프트')
        if not positive:
            raise ValueError('긍정 프롬프트를 입력하세요.')
        count = body.get('count', 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
            raise ValueError(f'시드 수는 1~{MAX_COUNT} 사이의 정수여야 합니다.')
        source = body.get('source')
        if source is not None and not isinstance(source, dict):
            raise ValueError('source는 객체여야 합니다.')
        catalog = self.comfy.catalog()
        if not catalog['connected']:
            raise ValueError(catalog['error'])
        base = validate_settings(body.get('settings', {}), catalog)
        variants = [
            (label, validate_settings({**base, **changes}, catalog))
            for label, changes in _variants(base, body.get('sweep'))
        ]
        if count * len(variants) > MAX_JOBS:
            raise ValueError(f'한 번에 {MAX_JOBS}장까지 실험할 수 있습니다.')
        fixed = base.get('seed', -1)
        # Every variant of one row shares its seed, so only the swept value differs.
        seeds = [secrets.randbits(32) if fixed == -1 else (fixed + i) % 2**32 for i in range(count)]
        group = uuid.uuid4().hex[:12]
        created = now()
        prepared = []
        for row, seed in enumerate(seeds):
            for column, (label, settings) in enumerate(variants):
                title = ' · '.join(filter(None, [label, f'시드 {seed}']))
                snapshot = {
                    'kind': 'lab',
                    'positive': positive,
                    'negative': negative,
                    'settings': {**settings, 'seed': seed},
                    'lab_group': group,
                    'lab_variant': label,
                    'source': copy.deepcopy(source),
                }
                prepared.append(
                    dict(
                        id=uuid.uuid4().hex,
                        kind='lab',
                        status='queued',
                        created_at=created,
                        lab_group=group,
                        lab_index=len(prepared) + 1,
                        lab_row=row,
                        lab_column=column,
                        lab_variant=label,
                        title=title,
                        seed=seed,
                        review_requested=False,
                        snapshot=snapshot,
                    )
                )
        with self.lock:
            if sum(j['status'] == 'queued' for j in self.jobs) + len(prepared) > 5000:
                raise ValueError('대기 작업이 너무 많습니다. 기존 작업을 먼저 처리하세요.')
            self.jobs.extend(prepared)
            self.persist()
        return {
            'ok': True,
            'lab_group': group,
            'variants': [label for label, _ in variants],
            'seeds': seeds,
            'jobs': [{k: v for k, v in j.items() if k != 'snapshot'} for j in prepared],
        }
