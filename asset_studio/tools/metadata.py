"""Read what an image says about how it was made.

Sources, most specific first: Studio's own record (``asset_studio`` PNG chunk or the
JSON sidecar), A1111/Forge ``parameters`` text, and a ComfyUI ``prompt`` graph (PNG
chunk, or the EXIF Make/Model fields ComfyUI uses for WebP). Graphs are only read,
never run.
"""

import json
import re

from PIL import ExifTags, Image

TEXT_LIMIT = 200_000
# ComfyUI writes WebP metadata as EXIF Model = "prompt:{...}" and Make = "workflow:{...}".
EXIF_MAKE, EXIF_MODEL, EXIF_USER_COMMENT = 0x010F, 0x0110, 0x9286
SAMPLER_NODES = ('KSampler', 'KSamplerAdvanced', 'SamplerCustom', 'SamplerCustomAdvanced')
TEXT_NODES = ('CLIPTextEncode', 'CLIPTextEncodeSDXL')


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _user_comment(value):
    if isinstance(value, bytes):
        head, body = value[:8], value[8:]
        if head.startswith(b'UNICODE'):
            for codec in ('utf-16-be', 'utf-16-le'):
                try:
                    return body.decode(codec).strip('\x00')
                except UnicodeDecodeError:
                    continue
        return body.decode('utf-8', errors='replace').strip('\x00')
    return str(value)


def read_raw(image):
    """Text chunks and EXIF of an open image, as strings."""
    text = {}
    for key, value in (getattr(image, 'text', None) or image.info or {}).items():
        if isinstance(value, str):
            text[key] = value[:TEXT_LIMIT]
    exif = {}
    try:
        data = image.getexif()
        tags = dict(data)
        tags.update(data.get_ifd(ExifTags.IFD.Exif))
    except Exception:
        tags = {}
    for tag, value in tags.items():
        if tag == EXIF_USER_COMMENT:
            value = _user_comment(value)
        elif isinstance(value, bytes):
            continue
        name = ExifTags.TAGS.get(tag, hex(tag))
        exif[name] = str(value)[:TEXT_LIMIT]
    # ComfyUI WebP: the graphs live in EXIF, prefixed with their chunk name.
    for name in ('Make', 'Model'):
        value = exif.get(name, '')
        key, _, rest = value.partition(':')
        if key in ('prompt', 'workflow') and rest.startswith('{'):
            text.setdefault(key, rest)
    if exif.get('UserComment') and 'parameters' not in text:
        text['parameters'] = exif['UserComment']
    return text, exif


def parse_a1111(text):
    """``parameters`` text: prompt, ``Negative prompt:`` and a ``Key: value, ...`` line."""
    lines = text.strip().split('\n')
    settings_line = lines.pop() if lines and re.match(r'^\s*Steps:', lines[-1]) else ''
    body = '\n'.join(lines)
    positive, _, negative = body.partition('Negative prompt:')
    settings = {}
    for key, value in re.findall(r'\s*([\w \-/]+):\s*("[^"]*"|[^,]*)(?:,|$)', settings_line):
        settings[key.strip()] = value.strip().strip('"')
    return {'positive': positive.strip(), 'negative': negative.strip(), 'settings': settings}


def _text_of(graph, ref, depth=0):
    """Prompt text that feeds a conditioning input, following simple pass-through nodes."""
    if not isinstance(ref, list) or not ref or depth > 8:
        return None
    node = graph.get(str(ref[0])) or {}
    inputs = node.get('inputs') or {}
    if node.get('class_type') in TEXT_NODES:
        value = inputs.get('text', inputs.get('text_g'))
        if isinstance(value, str):
            return value
        return _text_of(graph, value, depth + 1)
    if isinstance(inputs.get('text'), str):
        return inputs['text']
    for key in ('conditioning', 'conditioning_1', 'positive', 'value', 'string'):
        found = _text_of(graph, inputs.get(key), depth + 1)
        if found is not None:
            return found
    return None


def parse_comfy(graph):
    """Prompt and main sampler settings from an API-format ComfyUI graph."""
    if not isinstance(graph, dict):
        return None
    result = {'positive': '', 'negative': '', 'settings': {}, 'models': []}
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get('inputs') or {}
        kind = node.get('class_type', '')
        for key in ('ckpt_name', 'unet_name', 'lora_name', 'vae_name', 'clip_name'):
            if isinstance(inputs.get(key), str):
                result['models'].append({'node': kind, key: inputs[key]})
        if kind in SAMPLER_NODES and not result['positive']:
            result['positive'] = _text_of(graph, inputs.get('positive')) or ''
            result['negative'] = _text_of(graph, inputs.get('negative')) or ''
            for key in ('seed', 'noise_seed', 'steps', 'cfg', 'sampler_name', 'scheduler'):
                if key in inputs and not isinstance(inputs[key], list):
                    result['settings'][key] = inputs[key]
    return result


def describe(path, sidecar=None):
    """Everything readable about one image file."""
    with Image.open(path) as image:
        info = {
            'format': image.format,
            'width': image.width,
            'height': image.height,
            'mode': image.mode,
            'has_alpha': 'A' in image.getbands() or 'transparency' in image.info,
            'animated': bool(getattr(image, 'is_animated', False)),
        }
        text, exif = read_raw(image)
    studio = _json(text.get('asset_studio')) or sidecar
    found = {'source': '', 'positive': '', 'negative': '', 'settings': {}}
    if isinstance(studio, dict) and studio.get('positive'):
        found = {
            'source': 'asset_studio',
            'positive': studio.get('positive', ''),
            'negative': studio.get('negative', ''),
            'settings': studio.get('settings') or {},
        }
    comfy = parse_comfy(_json(text.get('prompt')))
    a1111 = parse_a1111(text['parameters']) if text.get('parameters') else None
    if not found['source'] and a1111 and a1111['positive']:
        found = {'source': 'parameters', **a1111}
    if not found['source'] and comfy and comfy['positive']:
        found = {'source': 'comfyui', **{k: comfy[k] for k in ('positive', 'negative')}}
        found['settings'] = comfy['settings']
    shown = {k: (v if len(v) < 4000 else v[:4000] + '…') for k, v in text.items()}
    return {
        **info,
        'prompt': found,
        'comfy': comfy,
        'text_keys': sorted(text),
        'text': shown,
        'exif': {k: v for k, v in exif.items() if k not in ('Make', 'Model', 'UserComment')},
        'has_workflow': 'workflow' in text,
        'studio': studio if isinstance(studio, dict) else None,
    }
