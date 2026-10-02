"""Build and validate the small ComfyUI graph used by Asset Studio."""

from __future__ import annotations

import math
from pathlib import PureWindowsPath
from typing import Any

from ..i18n import Msg

DEFAULTS: dict[str, Any] = {
    'model': 'anima_aestheticV11.safetensors',
    'text_encoder': 'qwen_3_06b_base.safetensors',
    'vae': 'qwen_image_vae.safetensors',
    'clip_type': 'stable_diffusion',
    'text_encoder_device': 'default',
    'steps': 32,
    'cfg': 5.0,
    'sampler': 'er_sde',
    'scheduler': 'simple',
    'width': 1536,
    'height': 1536,
    'seed': -1,
    'loras': [],
}

_CATALOG_KEYS = {
    'model': 'models',
    'text_encoder': 'text_encoders',
    'vae': 'vaes',
    'clip_type': 'clip_types',
    'sampler': 'samplers',
    'scheduler': 'schedulers',
}


def defaults(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return defaults, preferring known choices that are actually installed."""
    result = {**DEFAULTS, 'loras': []}
    if not isinstance(catalog, dict):
        return result
    supplied = catalog.get('defaults')
    if isinstance(supplied, dict):
        result.update(supplied)
    for key, catalog_key in _CATALOG_KEYS.items():
        choices = _choice_names(catalog.get(catalog_key))
        if choices and result[key] not in choices:
            result[key] = choices[0]
    return result


def _resolve(value: Any, choices: list[str]) -> Any:
    """``value`` as listed by ComfyUI. Files moved into a sub-folder (``anima\\x``) after a
    record was written are found by file name when exactly one entry matches."""
    if not isinstance(value, str) or value in choices:
        return value
    prefix, _, name = value.rpartition('::')

    def split(entry: str) -> tuple[str, str]:
        head, _, tail = entry.rpartition('::')
        return head, PureWindowsPath(tail).name

    wanted = (prefix, PureWindowsPath(name).name)
    found = [entry for entry in choices if split(entry) == wanted]
    return found[0] if len(found) == 1 else value


def _choice_names(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    names: list[str] = []
    for value in values:
        if isinstance(value, str):
            names.append(value)
        elif isinstance(value, dict):
            name = value.get('name', value.get('value', value.get('title')))
            if isinstance(name, str):
                names.append(name)
    return names


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label} must be a finite number') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label} must be a finite number')
    return number


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f'{label} must be an integer')
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label} must be an integer') from exc
    if isinstance(value, float) and number != value:
        raise ValueError(f'{label} must be an integer')
    if isinstance(value, str) and str(number) != value.strip():
        raise ValueError(f'{label} must be an integer')
    return number


FAMILIES = ('anima', 'sdxl')
# SDXL checkpoints carry their own text encoder and VAE.
SDXL_UNUSED = ('text_encoder', 'clip_type', 'text_encoder_device')


def validate_settings(settings: dict[str, Any] | None, catalog: dict[str, Any]) -> dict[str, Any]:
    """Validate user selections against ComfyUI catalog choices and normalize values.

    ``family`` picks the graph: ``anima`` (diffusion model + text encoder + VAE) or
    ``sdxl`` (one checkpoint; optional VAE override and CLIP skip).
    """
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    if not isinstance(catalog, dict):
        raise ValueError('catalog must be an object')
    family = settings.get('family') or 'anima'
    if family not in FAMILIES:
        raise ValueError('family must be anima or sdxl')
    result = defaults(catalog)
    if family == 'sdxl':
        for key in SDXL_UNUSED:
            result.pop(key, None)
        result['vae'] = ''  # Built-in VAE unless the request names one.
    result.update(settings)
    result['family'] = family

    for key, catalog_key in _CATALOG_KEYS.items():
        if family == 'sdxl' and key in SDXL_UNUSED:
            result.pop(key, None)
            continue
        if family == 'sdxl' and key == 'vae' and not result.get('vae'):
            continue
        choices = _choice_names(catalog.get(catalog_key))
        value = result[key] = _resolve(result.get(key), choices)
        if not choices:
            raise ValueError(f'catalog.{catalog_key} must contain available choices')
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f'{key} must be one of the available {catalog_key}')

    device = result.get('text_encoder_device', 'default')
    entry = catalog.get('model_entries', {}).get(result['model'])
    # Resolve from the server catalog, never trust client-supplied loader/path overrides.
    result['model_loader'] = entry['loader'] if entry else 'UNETLoader'
    result['model_filename'] = entry['filename'] if entry else result['model']
    if family == 'sdxl':
        if result['model_loader'] != 'CheckpointLoaderSimple':
            raise ValueError(
                Msg(
                    'server.workflow.sdxl_needs_a_checkpoint_model',
                    'SDXL needs a checkpoint model.',
                )
            )
        result['clip_skip'] = _integer(result.get('clip_skip', 2), 'clip_skip')
        if not 1 <= result['clip_skip'] <= 12:
            raise ValueError('clip_skip must be between 1 and 12')
    else:
        if device not in ('default', 'cpu'):
            raise ValueError("text_encoder_device must be 'default' or 'cpu'")
        result['text_encoder_device'] = device

    result['steps'] = _integer(result.get('steps'), 'steps')
    if not 1 <= result['steps'] <= 100:
        raise ValueError('steps must be between 1 and 100')
    result['cfg'] = _finite_number(result.get('cfg'), 'cfg')
    if not 0 <= result['cfg'] <= 30:
        raise ValueError('cfg must be between 0 and 30')
    for key in ('width', 'height'):
        result[key] = _integer(result.get(key), key)
        if not 256 <= result[key] <= 3072 or result[key] % 16:
            raise ValueError(f'{key} must be a multiple of 16 between 256 and 3072')
    result['seed'] = _integer(result.get('seed'), 'seed')
    if not -1 <= result['seed'] <= 2**53 - 1:
        raise ValueError('seed must be between -1 and 2**53 - 1')

    loras = result.get('loras', [])
    if not isinstance(loras, list):
        raise ValueError('loras must be a list')
    lora_choices = _choice_names(catalog.get('loras'))
    normalized_loras = []
    for index, item in enumerate(loras):
        if index >= 16:
            raise ValueError('loras cannot contain more than 16 entries')
        if isinstance(item, str):
            item = {'name': item}
        if not isinstance(item, dict):
            raise ValueError(f'loras[{index}] must be an object')
        name = _resolve(item.get('name'), lora_choices)
        if not isinstance(name, str) or name not in lora_choices:
            raise ValueError(f'loras[{index}].name must be an available LoRA')
        strength_model = _finite_number(
            item.get('strength_model', 1.0), f'loras[{index}].strength_model'
        )
        strength_clip = _finite_number(
            item.get('strength_clip', 1.0), f'loras[{index}].strength_clip'
        )
        if not -10 <= strength_model <= 10 or not -10 <= strength_clip <= 10:
            raise ValueError(f'loras[{index}] strengths must be between -10 and 10')
        normalized_loras.append(
            {'name': name, 'strength_model': strength_model, 'strength_clip': strength_clip}
        )
    result['loras'] = normalized_loras
    return result


def build_workflow(
    settings: dict[str, Any], positive: str, negative: str, seed: int
) -> dict[str, Any]:
    """Build a deterministic, plain ComfyUI API prompt graph."""
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    if not isinstance(positive, str) or not isinstance(negative, str):
        raise ValueError('positive and negative prompts must be strings')
    actual_seed = _integer(seed, 'seed')
    if actual_seed < 0 or actual_seed > 2**53 - 1:
        raise ValueError('seed must be between 0 and 2**53 - 1 when building a workflow')
    loras = settings.get('loras', [])
    if not isinstance(loras, list):
        raise ValueError('loras must be a list')

    model_ref: list[Any] = ['1', 0]
    clip_ref: list[Any] = ['2', 0]
    vae_ref: list[Any] = ['3', 0]
    if settings.get('family') == 'sdxl':
        # One checkpoint: its CLIP (cut at clip_skip) and, unless overridden, its VAE.
        graph = {
            '1': {
                'class_type': 'CheckpointLoaderSimple',
                'inputs': {'ckpt_name': settings['model_filename']},
            },
            '2': {
                'class_type': 'CLIPSetLastLayer',
                'inputs': {
                    'clip': ['1', 1],
                    'stop_at_clip_layer': -int(settings.get('clip_skip', 2)),
                },
            },
        }
        vae_ref = ['1', 2]
        if settings.get('vae'):
            graph['3'] = {'class_type': 'VAELoader', 'inputs': {'vae_name': settings['vae']}}
            vae_ref = ['3', 0]
    else:
        graph: dict[str, Any] = {
            '1': {
                'class_type': 'UNETLoader',
                'inputs': {'unet_name': settings['model'], 'weight_dtype': 'default'},
            },
            '2': {
                'class_type': 'CLIPLoader',
                'inputs': {
                    'clip_name': settings['text_encoder'],
                    'type': settings.get('clip_type', 'stable_diffusion'),
                    'device': settings.get('text_encoder_device', 'default'),
                },
            },
            '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': settings['vae']}},
        }
        if settings.get('model_loader') == 'CheckpointLoaderSimple':
            graph['1'] = {
                'class_type': 'CheckpointLoaderSimple',
                'inputs': {'ckpt_name': settings['model_filename']},
            }
    next_id = 4
    for lora in loras:
        if isinstance(lora, str):
            lora = {'name': lora}
        if not isinstance(lora, dict) or not isinstance(lora.get('name'), str):
            raise ValueError('each LoRA must include a name')
        node_id = str(next_id)
        graph[node_id] = {
            'class_type': 'LoraLoader',
            'inputs': {
                'model': model_ref,
                'clip': clip_ref,
                'lora_name': lora['name'],
                'strength_model': lora.get('strength_model', 1.0),
                'strength_clip': lora.get('strength_clip', 1.0),
            },
        }
        model_ref, clip_ref = [node_id, 0], [node_id, 1]
        next_id += 1
    positive_id, negative_id, latent_id, sampler_id, decode_id, preview_id = (
        str(next_id + n) for n in range(6)
    )
    graph[positive_id] = {
        'class_type': 'CLIPTextEncode',
        'inputs': {'text': positive, 'clip': clip_ref},
    }
    graph[negative_id] = {
        'class_type': 'CLIPTextEncode',
        'inputs': {'text': negative, 'clip': clip_ref},
    }
    graph[latent_id] = {
        'class_type': 'EmptyLatentImage',
        'inputs': {'width': settings['width'], 'height': settings['height'], 'batch_size': 1},
    }
    graph[sampler_id] = {
        'class_type': 'KSampler',
        'inputs': {
            'model': model_ref,
            'positive': [positive_id, 0],
            'negative': [negative_id, 0],
            'latent_image': [latent_id, 0],
            'seed': actual_seed,
            'steps': settings['steps'],
            'cfg': settings['cfg'],
            'sampler_name': settings['sampler'],
            'scheduler': settings['scheduler'],
            'denoise': 1.0,
        },
    }
    graph[decode_id] = {
        'class_type': 'VAEDecode',
        'inputs': {'samples': [sampler_id, 0], 'vae': vae_ref},
    }
    graph['output'] = {'class_type': 'PreviewImage', 'inputs': {'images': [decode_id, 0]}}
    return graph


def build_ui_workflow(
    settings: dict[str, Any], positive: str, negative: str, seed: int
) -> dict[str, Any]:
    """Build a standard ComfyUI workflow-editor export for the same generation graph."""
    prompt = build_workflow(settings, positive, negative, seed)
    numeric_ids = [int(key) for key in prompt if key.isdigit()]
    output_id = max(numeric_ids, default=0) + 1
    api_to_ui = {key: (output_id if key == 'output' else int(key)) for key in prompt}
    nodes: list[dict[str, Any]] = []
    links: list[list[Any]] = []
    link_id = 1

    # Socket definitions and widget order follow the built-in ComfyUI node schemas.
    specs: dict[str, tuple[list[tuple[str, str]], list[tuple[str, str]], list[Any]]] = {
        'CheckpointLoaderSimple': (
            [],
            [('MODEL', 'MODEL'), ('CLIP', 'CLIP'), ('VAE', 'VAE')],
            [settings.get('model_filename', settings['model'])],
        ),
        'UNETLoader': ([], [('MODEL', 'MODEL')], [settings['model'], 'default']),
        'CLIPLoader': (
            [],
            [('CLIP', 'CLIP')],
            [
                settings.get('text_encoder', ''),
                settings.get('clip_type', 'stable_diffusion'),
                settings.get('text_encoder_device', 'default'),
            ],
        ),
        'VAELoader': ([], [('VAE', 'VAE')], [settings.get('vae', '')]),
        'CLIPSetLastLayer': (
            [('clip', 'CLIP')],
            [('CLIP', 'CLIP')],
            [-int(settings.get('clip_skip', 2))],
        ),
        'LoraLoader': (
            [('model', 'MODEL'), ('clip', 'CLIP')],
            [('MODEL', 'MODEL'), ('CLIP', 'CLIP')],
            [],
        ),
        'CLIPTextEncode': ([('clip', 'CLIP')], [('CONDITIONING', 'CONDITIONING')], []),
        'EmptyLatentImage': (
            [],
            [('LATENT', 'LATENT')],
            [settings['width'], settings['height'], 1],
        ),
        'KSampler': (
            [
                ('model', 'MODEL'),
                ('positive', 'CONDITIONING'),
                ('negative', 'CONDITIONING'),
                ('latent_image', 'LATENT'),
            ],
            [('LATENT', 'LATENT')],
            [
                seed,
                'fixed',
                settings['steps'],
                settings['cfg'],
                settings['sampler'],
                settings['scheduler'],
                1.0,
            ],
        ),
        'VAEDecode': ([('samples', 'LATENT'), ('vae', 'VAE')], [('IMAGE', 'IMAGE')], []),
        'PreviewImage': ([('images', 'IMAGE')], [], []),
    }
    positions = {
        'CheckpointLoaderSimple': (40, 100),
        'UNETLoader': (40, 100),
        'CLIPLoader': (40, 300),
        'CLIPSetLastLayer': (40, 300),
        'VAELoader': (40, 500),
        'LoraLoader': (340, 200),
        'EmptyLatentImage': (650, 760),
        'KSampler': (1040, 370),
        'VAEDecode': (1390, 370),
        'PreviewImage': (1650, 370),
    }
    prompt_node_positions = [(650, 80), (650, 410)]
    prompt_node_index = 0

    for key, api_node in prompt.items():
        node_id = api_to_ui[key]
        node_type = api_node['class_type']
        input_defs, output_defs, widget_values = specs[node_type]
        if node_type == 'CLIPTextEncode':
            widget_values = [api_node['inputs']['text']]
        elif node_type == 'KSampler':
            widget_values[0] = seed
        elif node_type == 'LoraLoader':
            values = api_node['inputs']
            widget_values = [values['lora_name'], values['strength_model'], values['strength_clip']]
        if node_type == 'CLIPTextEncode':
            x, y = prompt_node_positions[prompt_node_index]
            prompt_node_index += 1
        else:
            x, y = positions[node_type]
        if node_type == 'LoraLoader':
            # Stack LoRAs vertically while keeping all other node IDs and positions fixed.
            lora_ordinal = sum(
                1
                for prior in prompt
                if prior != key
                and prior.isdigit()
                and int(prior) < int(key)
                and prompt[prior]['class_type'] == 'LoraLoader'
            )
            y += lora_ordinal * 180
        node = {
            'id': node_id,
            'type': node_type,
            'pos': [x, y],
            'size': {
                'CLIPTextEncode': [340, 280],
                'KSampler': [280, 280],
                'PreviewImage': [420, 420],
            }.get(node_type, [280, 100]),
            'flags': {},
            'order': len(nodes),
            'mode': 0,
            'inputs': [],
            'outputs': [],
            'properties': {'Node name for S&R': node_type},
            'widgets_values': widget_values,
        }
        for slot, (name, socket_type) in enumerate(input_defs):
            api_value = api_node['inputs'].get(name)
            input_link = None
            if (
                isinstance(api_value, list)
                and len(api_value) == 2
                and isinstance(api_value[0], str)
            ):
                origin_id = api_to_ui[api_value[0]]
                link = [link_id, origin_id, api_value[1], node_id, slot, socket_type]
                links.append(link)
                input_link = link_id
                # Output link bookkeeping is applied after all node objects exist.
                link_id += 1
            node['inputs'].append({'name': name, 'type': socket_type, 'link': input_link})
        for slot, (name, socket_type) in enumerate(output_defs):
            node['outputs'].append(
                {'name': name, 'type': socket_type, 'links': [], 'slot_index': slot}
            )
        nodes.append(node)

    nodes_by_id = {node['id']: node for node in nodes}
    for edge in links:
        _, origin_id, origin_slot, _, _, _ = edge
        nodes_by_id[origin_id]['outputs'][origin_slot]['links'].append(edge[0])
    return {
        'last_node_id': max(api_to_ui.values(), default=0),
        'last_link_id': link_id - 1,
        'nodes': nodes,
        'links': links,
        'groups': [],
        'config': {},
        'extra': {'ds': {'scale': 0.72, 'offset': [0, 0]}},
        'version': 0.4,
    }
