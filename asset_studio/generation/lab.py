"""Lab generation: one prompt, tried with several seeds or one changing setting.

Lab jobs run through the same queue and worker as asset jobs but are not assets: they
carry no work/character/outfit, skip VLM review and are saved under
``outputs/_lab/<date>/``.
"""

import copy
import secrets
import uuid

from ..i18n import Msg
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
    'sampler': Msg('server.lab.sampler', 'Sampler'),
    'scheduler': Msg('server.lab.scheduler', 'Scheduler'),
    'clip_skip': 'CLIP skip',
    'lora_strength': Msg('server.lab.lora_strength', 'LoRA strength'),
}


def _text(value, name):
    if not isinstance(value, str) or len(value) > MAX_PROMPT_LENGTH:
        raise ValueError(
            Msg(
                'server.lab.prompt_too_long',
                '{name} must be text of at most {limit} characters.',
                name=name,
                limit=f'{MAX_PROMPT_LENGTH:,}',
            )
        )
    return value.strip()


def _variants(settings, sweep):
    """``[(label, changes)]``: one entry per tried value, or the settings as they are."""
    if not sweep:
        return [('', {})]
    key = sweep.get('key')
    if key not in SWEEP_KEYS:
        raise ValueError(
            Msg(
                'server.lab.the_value_to_vary_is_one',
                'The value to vary is one of {values}.',
                values=', '.join(SWEEP_LABELS.values()),
            )
        )
    values = sweep.get('values')
    if not isinstance(values, list) or not 2 <= len(values) <= MAX_VARIANTS:
        raise ValueError(
            Msg(
                'server.lab.enter_2_to_values_to_compare',
                'Enter 2 to {max_variants} values to compare.',
                max_variants=MAX_VARIANTS,
            )
        )
    try:
        values = [SWEEP_KEYS[key](value) for value in values]
    except (TypeError, ValueError) as error:
        raise ValueError(
            Msg('server.lab.check_the_values', 'Check the {key} values.', key=SWEEP_LABELS[key])
        ) from error
    if key != 'lora_strength':
        return [(f'{SWEEP_LABELS[key]} {value}', {key: value}) for value in values]
    index = sweep.get('lora_index', 0)
    loras = settings.get('loras') or []
    if not isinstance(index, int) or not 0 <= index < len(loras):
        raise ValueError(
            Msg(
                'server.lab.choose_the_lora_whose_strength_changes',
                'Choose the LoRA whose strength changes.',
            )
        )
    result = []
    for value in values:
        changed = copy.deepcopy(loras)
        changed[index].update(strength_model=value, strength_clip=value)
        result.append(
            (
                Msg('server.lab.lora_strength_2', 'LoRA strength {value}', value=value),
                {'loras': changed},
            )
        )
    return result


class LabMixin:
    """Lab part of ``Studio``'s queue."""

    def enqueue_lab(self, body):
        positive = _text(
            body.get('positive', ''), Msg('server.lab.positive_prompt', 'Positive prompt')
        )
        negative = _text(
            body.get('negative', ''), Msg('server.lab.negative_prompt', 'Negative prompt')
        )
        if not positive:
            raise ValueError(Msg('server.lab.enter_a_positive_prompt', 'Enter a positive prompt.'))
        count = body.get('count', 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
            raise ValueError(
                Msg(
                    'server.lab.seeds_must_be_a_whole_number',
                    'Seeds must be a whole number from 1 to {max_count}.',
                    max_count=MAX_COUNT,
                )
            )
        source = body.get('source')
        if source is not None and not isinstance(source, dict):
            raise ValueError(
                Msg('server.lab.source_must_be_an_object', 'source must be an object.')
            )
        catalog = self.comfy.catalog()
        if not catalog['connected']:
            raise ValueError(catalog['error'])
        base = validate_settings(body.get('settings', {}), catalog)
        variants = [
            (label, validate_settings({**base, **changes}, catalog))
            for label, changes in _variants(base, body.get('sweep'))
        ]
        if count * len(variants) > MAX_JOBS:
            raise ValueError(
                Msg(
                    'server.lab.up_to_images_per_lab_run',
                    'Up to {max_jobs} images per lab run.',
                    max_jobs=MAX_JOBS,
                )
            )
        fixed = base.get('seed', -1)
        # Every variant of one row shares its seed, so only the swept value differs.
        seeds = [secrets.randbits(32) if fixed == -1 else (fixed + i) % 2**32 for i in range(count)]
        group = uuid.uuid4().hex[:12]
        created = now()
        prepared = []
        for row, seed in enumerate(seeds):
            for column, (label, settings) in enumerate(variants):
                title = ' · '.join(
                    filter(None, [label, Msg('server.lab.seed', 'Seed {seed}', seed=seed)])
                )
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
                raise ValueError(
                    Msg(
                        'server.lab.too_many_queued_jobs_let_the',
                        'Too many queued jobs. Let the queue run first.',
                    )
                )
            self.jobs.extend(prepared)
            self.persist()
        return {
            'ok': True,
            'lab_group': group,
            'variants': [label for label, _ in variants],
            'seeds': seeds,
            'jobs': [{k: v for k, v in j.items() if k != 'snapshot'} for j in prepared],
        }
