"""Post-processing: background alpha, upscale, detailer and censor-area detection run as
queue jobs in ComfyUI; censoring itself is applied by Studio with an editable mask.

The nodes are Asset Studio's copies (``comfy_nodes/asset_studio_nodes``, ids
``AssetStudio…``). Until that folder is linked into ComfyUI, the AtelierX originals
with the same inputs are used. Results are new PNG files in ``outputs/_tools/<date>/``
with the graph and source recorded; the source image is never changed.
"""

import copy
import hashlib
import io
import json
import secrets
import time
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from PIL import Image, ImageChops, ImageOps, PngImagePlugin

from ..gallery.listing import is_asset_path
from ..generation.workflow import build_workflow, validate_settings
from ..i18n import Msg, message_of
from ..util import atomic_json, now, replace_file
from . import censor

PREFIXES = ('AssetStudio', 'AtelierX')
REMBG_MODEL = 'isnet-anime: anime illustrations'
PERSON_MODEL = 'person_yolov8n-seg.pt'
NSFW_MODEL = 'ntd11_anime_nsfw_segm_v5-variant1.pt'
# Labels the censor detector knows (same list as the node's REFERENCE_LABELS).
NSFW_LABELS = ('nipples', 'pussy', 'penis', 'anus', 'testicles', 'x-ray', 'cross-section')
OPS = {
    'alpha': Msg('server.postprocess.background_split_mask', 'Background split (mask)'),
    'detect': Msg('server.postprocess.censor_area_detection', 'Censor area detection'),
    'upscale': Msg('server.postprocess.upscale', 'Upscale'),
    'detail': Msg('server.postprocess.detailer_experimental', 'Detailer (experimental)'),
    'inpaint': Msg('server.postprocess.inpaint', 'Inpaint'),
}
DETAIL_STAGES = ('face', 'eye', 'mouth', 'hand')
DETECTORS = {
    'face': 'bbox/face_yolov8m.pt',
    'eye': 'segm/PitEyeDetailer-v2-seg.pt',
    'mouth': 'bbox/face_yolov8m.pt',
    'hand': 'bbox/hand_yolov8s.pt',
}
SAM_MODEL = 'sam_vit_b_01ec64.pth'


def _number(options, key, default, low, high, kind=float):
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(
            Msg(
                'server.postprocess.must_be_between_and',
                '{key} must be between {low} and {high}.',
                key=key,
                low=low,
                high=high,
            )
        )
    return kind(value)


def check_options(op, options, info):
    """Normalised options for ``op``; ``info`` is :meth:`PostprocessMixin.postprocess_info`."""
    options = options or {}
    if op == 'alpha':
        method = options.get('method', 'isnet')
        if method not in ('isnet', 'person'):
            raise ValueError(
                Msg(
                    'server.postprocess.choose_a_background_removal_method',
                    'Choose a background removal method.',
                )
            )
        return {'method': method, 'confidence': _number(options, 'confidence', 0.35, 0, 1)}
    if op == 'detect':
        labels = options.get('labels') or list(NSFW_LABELS)
        if isinstance(labels, str):
            labels = [label.strip() for label in labels.split(',') if label.strip()]
        if not labels or any(label not in NSFW_LABELS for label in labels):
            raise ValueError(
                Msg(
                    'server.postprocess.choose_areas_to_cover_from',
                    'Choose areas to cover from: {nsfw_labels}',
                    nsfw_labels=', '.join(NSFW_LABELS),
                )
            )
        return {
            'confidence': _number(options, 'confidence', 0.35, 0, 1),
            'labels': ','.join(labels),
        }
    if op == 'upscale':
        model = options.get('model') or next(iter(info['upscale_models']), '')
        if model not in info['upscale_models']:
            raise ValueError(
                Msg(
                    'server.postprocess.choose_an_upscale_model_from_the',
                    'Choose an upscale model from the list.',
                )
            )
        return {'model': model, 'scale': _number(options, 'scale', 2, 0.25, 8)}
    if op == 'detail':
        stages = {stage: bool(options.get(stage, stage != 'mouth')) for stage in DETAIL_STAGES}
        if not any(stages.values()):
            raise ValueError(
                Msg(
                    'server.postprocess.choose_at_least_one_area_to',
                    'Choose at least one area to redraw.',
                )
            )
        return {
            **stages,
            'denoise': _number(options, 'denoise', 0.4, 0.05, 1),
            'steps': _number(options, 'steps', 20, 1, 60, int),
        }
    if op == 'inpaint':
        # A prompt left out (None) is the image's own; an empty one stays empty.
        prompts = {}
        for key in ('positive', 'negative'):
            value = options.get(key)
            if value is None:
                prompts[key] = None
                continue
            if not isinstance(value, str) or len(value) > 8000:
                raise ValueError(
                    Msg(
                        'server.postprocess.the_prompt_must_be_text_of',
                        'The {key} prompt must be text of 8000 characters or fewer.',
                        key=key,
                    )
                )
            prompts[key] = value.strip()
        return {
            **prompts,
            'denoise': _number(options, 'denoise', 0.6, 0.05, 1),
            # 0 keeps the step count the image was made with.
            'steps': _number(options, 'steps', 0, 0, 60, int),
            'grow': _number(options, 'grow', 8, -64, 64, int),
            'feather': _number(options, 'feather', 8, 0, 64, int),
            # crop: redraw only the masked region, enlarged to the generation size.
            'area': _choice(options, 'area', ('crop', 'full')),
            'padding': _number(options, 'padding', 64, 0, 512, int),
        }
    raise ValueError(Msg('server.postprocess.unknown_post_process', 'Unknown post-process.'))


def _choice(options, key, allowed):
    value = options.get(key, allowed[0])
    if value not in allowed:
        raise ValueError(
            Msg(
                'server.postprocess.must_be_one_of',
                '{key} must be one of {allowed}.',
                key=key,
                allowed=', '.join(allowed),
            )
        )
    return value


def crop_region(box, image_size, padding, target_area):
    """The region around ``box`` to redraw and the size to redraw it at.

    The region is the mask's box plus ``padding`` (clamped to the image). It is enlarged
    so its area is about ``target_area`` (the size the model was used at), at most 4x
    and never shrunk, with both sides a multiple of 16.
    """
    width, height = image_size
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0 - padding), max(0, y0 - padding)
    x1, y1 = min(width, x1 + padding), min(height, y1 + padding)
    w, h = x1 - x0, y1 - y0
    scale = min(4.0, max(1.0, (target_area / (w * h)) ** 0.5))
    size = (max(64, round(w * scale / 16) * 16), max(64, round(h * scale / 16) * 16))
    return (x0, y0, x1, y1), size


def detail_graph(image_name, options, source, prefix):
    """The image's own loaders, LoRAs and prompts feeding the Impact detailer pipeline."""
    settings, seed = source['settings'], source['seed']
    built = build_workflow(settings, source['positive'], source['negative'], seed)
    sampler_id = next(k for k, n in built.items() if n['class_type'] == 'KSampler')
    sampler = built[sampler_id]['inputs']
    decode = next(n for n in built.values() if n['class_type'] == 'VAEDecode')
    clip = built[sampler['positive'][0]]['inputs']['clip']
    drop = {sampler_id, sampler['latent_image'][0]}
    drop |= {
        k for k, n in built.items() if n['class_type'] in ('VAEDecode', 'SaveImage', 'PreviewImage')
    }
    nodes = {k: v for k, v in built.items() if k not in drop}
    nodes['image'] = {'class_type': 'LoadImage', 'inputs': {'image': image_name}}
    nodes['detail'] = {
        'class_type': f'{prefix}ImpactDetailerPipeline',
        'inputs': {
            'image': ['image', 0],
            'model': sampler['model'],
            'clip': clip,
            'vae': decode['inputs']['vae'],
            'positive': sampler['positive'],
            'negative': sampler['negative'],
            **{f'{stage}_enabled': options[stage] for stage in DETAIL_STAGES},
            **{f'{stage}_detector_model': DETECTORS[stage] for stage in DETAIL_STAGES},
            'sam_model': SAM_MODEL,
            'seed': seed,
            'steps': options['steps'],
            'cfg': settings['cfg'],
            'sampler_name': settings['sampler'],
            'scheduler': settings['scheduler'],
            'denoise': options['denoise'],
        },
    }
    nodes['output'] = {'class_type': 'PreviewImage', 'inputs': {'images': ['detail', 0]}}
    return nodes


def inpaint_graph(image_name, mask_name, options, source):
    """Redraw the masked area with the image's own loaders, LoRAs and prompt.

    The image is encoded and only the masked latent is noised; afterwards the original
    pixels are put back outside the mask, so unpainted areas stay exactly as they were.
    """
    settings, seed = source['settings'], source['seed']
    built = build_workflow(settings, source['positive'], source['negative'], seed)
    sampler_id = next(k for k, n in built.items() if n['class_type'] == 'KSampler')
    sampler = built[sampler_id]['inputs']
    decode_id = next(k for k, n in built.items() if n['class_type'] == 'VAEDecode')
    vae = built[decode_id]['inputs']['vae']
    drop = {sampler['latent_image'][0]}
    drop |= {k for k, n in built.items() if n['class_type'] in ('SaveImage', 'PreviewImage')}
    nodes = {k: v for k, v in built.items() if k not in drop}
    nodes['image'] = {'class_type': 'LoadImage', 'inputs': {'image': image_name}}
    nodes['mask'] = {
        'class_type': 'LoadImageMask',
        'inputs': {'image': mask_name, 'channel': 'red'},
    }
    nodes['encode'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['image', 0], 'vae': vae}}
    nodes['noise_mask'] = {
        'class_type': 'SetLatentNoiseMask',
        'inputs': {'samples': ['encode', 0], 'mask': ['mask', 0]},
    }
    sampler.update(latent_image=['noise_mask', 0], denoise=options['denoise'])
    if options['steps']:
        sampler['steps'] = options['steps']
    nodes['composite'] = {
        'class_type': 'ImageCompositeMasked',
        'inputs': {
            'destination': ['image', 0],
            'source': [decode_id, 0],
            'x': 0,
            'y': 0,
            'resize_source': False,
            'mask': ['mask', 0],
        },
    }
    nodes['output'] = {'class_type': 'PreviewImage', 'inputs': {'images': ['composite', 0]}}
    return nodes


def graph(op, image_name, options, prefix):
    nodes = {'1': {'class_type': 'LoadImage', 'inputs': {'image': image_name}}}
    image = ['1', 0]
    if op == 'alpha':
        if options['method'] == 'isnet':
            nodes['2'] = {
                'class_type': 'RemBGSession+',
                'inputs': {'model': REMBG_MODEL, 'providers': 'CUDA'},
            }
            nodes['3'] = {
                'class_type': 'ImageRemoveBackground+',
                'inputs': {'rembg_session': ['2', 0], 'image': image},
            }
        else:
            nodes['3'] = {
                'class_type': f'{prefix}DetectCharacterMask',
                'inputs': {
                    'image': image,
                    'segmentation_model': PERSON_MODEL,
                    'confidence': options['confidence'],
                },
            }
        mask = ['3', 1] if options['method'] == 'isnet' else ['3', 0]
        # The kept area comes back as a mask to edit; Studio applies it afterwards.
        nodes['4'] = {'class_type': 'MaskToImage', 'inputs': {'mask': mask}}
        result = ['4', 0]
    elif op == 'detect':
        nodes['2'] = {
            'class_type': f'{prefix}DetectNsfwMask',
            'inputs': {
                'image': image,
                'segmentation_model': NSFW_MODEL,
                'labels': options['labels'],
                'confidence': options['confidence'],
            },
        }
        # The mask comes back as an image; it becomes the editable censor mask.
        nodes['3'] = {'class_type': 'MaskToImage', 'inputs': {'mask': ['2', 0]}}
        result = ['3', 0]
    else:
        nodes['2'] = {
            'class_type': f'{prefix}Upscale',
            'inputs': {
                'image': image,
                'upscale_model': options['model'],
                'scale': options['scale'],
            },
        }
        result = ['2', 0]
    # Same output node id as generation graphs, so the worker reads the result the same way.
    nodes['output'] = {
        'class_type': 'PreviewImage',
        'inputs': {'images': result},
    }
    return nodes


class PostprocessMixin:
    """Post-processing part of ``Studio``."""

    def postprocess_info(self):
        try:
            info = self.comfy.request('/object_info')
        except Exception as error:
            return {
                'available': False,
                'error': Msg(
                    'server.postprocess.cannot_connect_to_comfyui',
                    'Cannot connect to ComfyUI: {error}',
                    error=message_of(error),
                ),
            }
        prefix = next((p for p in PREFIXES if f'{p}Upscale' in info), None)
        if prefix is None:
            return {
                'available': False,
                'error': Msg(
                    'server.postprocess.asset_studio_post_processing_nodes_are',
                    'Asset Studio post-processing nodes are not in ComfyUI. Link '
                    'comfy_nodes/asset_studio_nodes into custom_nodes and restart ComfyUI.',
                ),
            }
        loader = info.get('UpscaleModelLoader', {}).get('input', {}).get('required', {})
        models = (loader.get('model_name') or [[]])[0]
        if isinstance(models, str):  # Newer ComfyUI: ("COMBO", {"options": [...]}).
            models = loader['model_name'][1].get('options', [])
        ops = dict(OPS)
        if f'{prefix}ImpactDetailerPipeline' not in info:
            del ops['detail']
        return {
            'available': True,
            'prefix': prefix,
            'ops': ops,
            'upscale_models': models,
            'rembg': 'RemBGSession+' in info,
        }

    def enqueue_postprocess(self, body):
        ids = body.get('ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 200:
            raise ValueError(
                Msg(
                    'server.postprocess.choose_1_to_200_images_to',
                    'Choose 1 to 200 images to process.',
                )
            )
        op = body.get('op')
        info = self.postprocess_info()
        if not info['available']:
            raise ValueError(info['error'])
        if op not in info['ops']:
            raise ValueError(
                Msg(
                    'server.postprocess.unknown_post_process_or_comfyui_lacks',
                    'Unknown post-process, or ComfyUI lacks the nodes it needs.',
                )
            )
        if op == 'alpha' and body.get('options', {}).get('method', 'isnet') == 'isnet':
            if not info['rembg']:
                raise ValueError(
                    Msg(
                        'server.postprocess.the_isnet_anime_background_removal_node',
                        'The isnet-anime background removal node (ComfyUI_essentials) is missing.',
                    )
                )
        options = check_options(op, body.get('options'), info)
        items = [self.tools.get(i) for i in ids]
        sources = {}
        if op in ('detail', 'inpaint'):
            # Redrawing needs the model, LoRAs and prompt the image was made with.
            catalog = self.comfy.catalog()
            missing = []
            for item in items:
                record = self.tools.analyze(item['id']).get('studio') or {}
                if not record.get('positive') or not isinstance(record.get('settings'), dict):
                    missing.append(item['name'])
                    continue
                settings = validate_settings(record['settings'], catalog)
                sources[item['id']] = {
                    'settings': settings,
                    'positive': options.get('positive') or record['positive'],
                    'negative': record.get('negative', '')
                    if options.get('negative') is None
                    else options['negative'],
                    'seed': secrets.randbits(32),
                }
            if missing:
                if op == 'detail':
                    raise ValueError(
                        Msg(
                            'server.postprocess.the_detailer_needs_images_made_with',
                            'The detailer needs images made with Asset Studio (with a record): '
                            '{missing}',
                            missing=', '.join(missing[:5]),
                        )
                    )
                raise ValueError(
                    Msg(
                        'server.postprocess.inpaint_needs_images_made_with_asset',
                        'Inpaint needs images made with Asset Studio (with a record): {missing}',
                        missing=', '.join(missing[:5]),
                    )
                )
        if op == 'inpaint':
            unmasked = [item['name'] for item in items if not item.get('inpaint_mask')]
            if unmasked:
                raise ValueError(
                    Msg(
                        'server.postprocess.save_a_mask_of_the_area',
                        'Save a mask of the area to redraw first: {unmasked}',
                        unmasked=', '.join(unmasked[:5]),
                    )
                )
        prepared = [
            dict(
                id=uuid.uuid4().hex,
                kind='post',
                status='queued',
                created_at=now(),
                title=f'{OPS[op]} · {item["name"]}',
                tool_item=item['id'],
                post_op=op,
                post_options=options,
                post_prefix=info['prefix'],
                post_source=sources.get(item['id']),
                seed=None,
                review_requested=False,
                snapshot={'kind': 'post', 'op': op, 'options': options},
            )
            for item in items
        ]
        with self.lock:
            if sum(j['status'] == 'queued' for j in self.jobs) + len(prepared) > 5000:
                raise ValueError(
                    Msg(
                        'server.postprocess.too_many_queued_jobs_let_the',
                        'Too many queued jobs. Let the queue run first.',
                    )
                )
            # Each inpaint job keeps the mask as it is now; generating and pasting back
            # both use this copy even if the mask is edited while the job waits or runs.
            previous, frozen = self.jobs[:], []
            try:
                for job in prepared:
                    if op == 'inpaint':
                        job['post_mask'] = self.tools.freeze_mask(job['tool_item'], 'inpaint')
                        frozen.append(job['post_mask'])
                self.jobs.extend(prepared)
                self.persist()
            except Exception:
                self.jobs = previous
                for token in frozen:
                    self.tools.job_mask_path(token).unlink(missing_ok=True)
                raise
        public = [{k: v for k, v in j.items() if k != 'snapshot'} for j in prepared]
        return {'ok': True, 'jobs': public}

    def post_graph(self, job):
        item = self.tools.get(job['tool_item'])
        path = self.tools.file(item)
        name = f'asset_studio_post_{item["id"]}{path.suffix.lower()}'
        uploaded = self.comfy.upload(name, path.read_bytes())
        reference = uploaded['name']
        if uploaded.get('subfolder'):
            reference = f'{uploaded["subfolder"]}/{reference}'
        if job['post_op'] == 'detail':
            return detail_graph(
                reference, job['post_options'], job['post_source'], job['post_prefix']
            )
        if job['post_op'] == 'inpaint':
            options = job['post_options']
            mask = self._inpaint_mask(item, job)
            job.pop('post_crop', None)
            if options.get('area') == 'crop':
                box = mask.getbbox()
                if box is None:
                    raise ValueError(
                        Msg(
                            'server.postprocess.the_mask_of_the_area_to',
                            'The mask of the area to redraw is empty.',
                        )
                    )
                settings = job['post_source']['settings']
                region, size = crop_region(
                    box, mask.size, options['padding'], settings['width'] * settings['height']
                )
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert('RGB')
                crop = image.crop(region).resize(size, Image.LANCZOS)
                mask = mask.crop(region).resize(size, Image.LANCZOS)
                reference = self._upload_png(f'asset_studio_inpaint_{item["id"]}_crop.png', crop)
                # save_post pastes the redrawn region back here.
                job['post_crop'] = {'region': list(region), 'size': list(size)}
            mask_ref = self._upload_png(f'asset_studio_inpaint_{item["id"]}.png', mask)
            return inpaint_graph(reference, mask_ref, options, job['post_source'])
        return graph(job['post_op'], reference, job['post_options'], job['post_prefix'])

    def _inpaint_mask(self, item, job):
        """The redraw mask of a job: the copy taken when it was queued (older saved jobs
        have none and use the image's current mask)."""
        options = job['post_options']
        if job.get('post_mask'):
            mask = self.tools.job_mask(job['post_mask'])
        else:
            mask = self.tools.mask(item['id'], 'inpaint')
        if mask is None:
            raise ValueError(
                Msg(
                    'server.postprocess.there_is_no_mask_for_the',
                    'There is no mask for the area to redraw.',
                )
            )
        return censor.shape_mask(
            mask.point(lambda v: 255 if v >= 128 else 0), options['grow'], options['feather']
        )

    def _upload_png(self, name, image):
        out = io.BytesIO()
        image.save(out, 'PNG')
        uploaded = self.comfy.upload(name, out.getvalue())
        if uploaded.get('subfolder'):
            return f'{uploaded["subfolder"]}/{uploaded["name"]}'
        return uploaded['name']

    def save_post(self, job, image_bytes, graph_used):
        """Store a post-processing result next to other tool outputs and list it as a tool image."""
        item = self.tools.get(job['tool_item'])
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        if job['post_op'] in ('detect', 'alpha'):
            kind = 'censor' if job['post_op'] == 'detect' else 'alpha'
            self.tools.set_mask(item['id'], image.convert('L'), 'detected', kind)
            return f'/api/tools/mask?id={item["id"]}&kind={kind}', None
        if job['post_op'] == 'inpaint' and job.get('post_crop'):
            # Shrink the redrawn region back and blend it in with the soft-edged mask.
            region = tuple(job['post_crop']['region'])
            mask = self._inpaint_mask(item, job).crop(region)
            with Image.open(self.tools.file(item)) as source:
                full = ImageOps.exif_transpose(source).convert('RGB')
            patch = image.convert('RGB').resize(mask.size, Image.LANCZOS)
            full.paste(patch, region[:2], mask)
            image = full
        if job['post_op'] == 'inpaint':
            # ComfyUI drops transparency; a transparent source keeps its own alpha.
            with Image.open(self.tools.file(item)) as source:
                if 'A' in source.getbands() and source.size == image.size:
                    image = image.convert('RGB')
                    image.putalpha(source.getchannel('A'))
        return self._store_result(
            item, image, job['post_op'], job['post_options'], graph_used, job['id']
        )

    def apply_censor(self, body):
        """Cover the masked area of one tool image (Studio, no GPU) and save the result."""
        item = self.tools.get(body.get('id'))
        options = {
            'treatment': body.get('treatment', 'mosaic'),
            'intensity': _number(body, 'intensity', 15, 0, 256, int),
            'color': str(body.get('color') or '#ffffff'),
            'opacity': _number(body, 'opacity', 100, 0, 100, int),
            'grow': _number(body, 'grow', 0, -64, 64, int),
            'feather': _number(body, 'feather', 0, 0, 64, int),
        }
        mask = self.tools.mask(item['id'])
        if mask is None:
            raise ValueError(
                Msg(
                    'server.postprocess.no_mask_detect_areas_or_paint',
                    'No mask. Detect areas or paint with the brush, then save.',
                )
            )
        with Image.open(self.tools.file(item)) as source:
            source.load()
            result = censor.apply(source, mask, **options)
        options['mask'] = item.get('mask')
        url, _ = self._store_result(item, result, 'censor', options, None, None)
        return {'ok': True, 'url': url}

    def apply_alpha(self, body):
        """Make everything outside the kept-area mask transparent (Studio, no GPU)."""
        item = self.tools.get(body.get('id'))
        options = {
            'grow': _number(body, 'grow', 0, -64, 64, int),
            'feather': _number(body, 'feather', 0, 0, 64, int),
        }
        mask = self.tools.mask(item['id'], 'alpha')
        if mask is None:
            raise ValueError(
                Msg(
                    'server.postprocess.there_is_no_keep_mask_split',
                    'There is no keep mask. Split the background or paint with the brush, then '
                    'save.',
                )
            )
        mask = censor.shape_mask(mask.point(lambda v: 255 if v >= 128 else 0), **options)
        with Image.open(self.tools.file(item)) as source:
            image = ImageOps.exif_transpose(source).convert('RGBA')
        # An image that is already transparent keeps its own alpha inside the new mask.
        alpha = ImageChops.multiply(image.getchannel('A'), mask)
        image.putalpha(alpha)
        options['mask'] = item.get('alpha_mask')
        url, _ = self._store_result(item, image, 'alpha', options, None, None)
        return {'ok': True, 'url': url}

    def _asset_source(self, item):
        """The gallery asset a tool image came from and its record, or (None, None)."""
        if item['source'] != 'gallery' or not is_asset_path(PurePosixPath(item['path']).parts):
            return None, None
        path = self.gallery._safe_path(item['path'])
        meta = self.gallery._read_metadata(path.with_suffix('.json'))
        if not meta or not meta.get('category'):
            return None, None
        return path, meta

    def _store_result(self, item, image, op, options, graph_used, job_id):
        source_path, meta = self._asset_source(item)
        if source_path:
            # Next to the source with its record, so a pass in review adopts it.
            folder, stem = source_path.parent, f'{source_path.stem}_{op}'
        else:
            folder = self.root / 'outputs' / '_tools' / time.strftime('%Y-%m-%d')
            stem = PurePosixPath(item['name']).stem or item['id']
            stem = ''.join(c if c not in '/\\:*?"<>|' else '_' for c in stem)[:120]
            stem = f'{stem}_{op}'
        folder.mkdir(parents=True, exist_ok=True)
        index = 1
        while True:
            path = folder / ((stem if index == 1 else f'{stem}_{index:03d}') + '.png')
            taken = (path, path.with_suffix('.webp'), path.with_suffix('.json'))
            if not any(p.exists() for p in taken):
                break
            index += 1
        if source_path:
            previous = meta.get('postprocessing') or {}
            record = copy.deepcopy(meta)
            record.update(created_at=now(), image_size=list(image.size))
            record['postprocessing'] = {
                'applied': True,
                'op': op,
                'options': copy.deepcopy(options),
                'source_image': item['path'],
                'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
                'job_id': job_id,
                'applied_at': now(),
                'workflow': graph_used,
                # An earlier pass on the source (upscale, then alpha, ...).
                'previous': previous if previous.get('applied') else None,
            }
            embedded = copy.deepcopy(record)
            embedded.pop('workflow', None)
            embedded['postprocessing'].pop('workflow', None)
        else:
            record = {
                'schema_version': 1,
                'kind': 'postprocess',
                'op': op,
                'options': copy.deepcopy(options),
                'source': {
                    'tool_item': item['id'],
                    'name': item['name'],
                    'source': item['source'],
                    'path': item['path'] if item['source'] == 'gallery' else None,
                    'sha256': item.get('sha256'),
                },
                'job_id': job_id,
                'created_at': now(),
                'image_size': list(image.size),
                'workflow': graph_used,
            }
            # The prompts and settings the source was made with carry over, so the result
            # can be redrawn (detailer, inpaint) again like its source.
            made = self.tools.analyze(item['id']).get('studio') or {}
            if made.get('positive') and isinstance(made.get('settings'), dict):
                record.update(
                    positive=made['positive'],
                    negative=made.get('negative', ''),
                    settings=copy.deepcopy(made['settings']),
                )
            embedded = {k: v for k, v in record.items() if k != 'workflow'}
        info = PngImagePlugin.PngInfo()
        if graph_used:
            info.add_text('prompt', json.dumps(graph_used, ensure_ascii=False))
        info.add_text('asset_studio', json.dumps(embedded, ensure_ascii=False))
        temp = path.with_suffix('.png.tmp')
        image.save(temp, format='PNG', pnginfo=info, compress_level=6)
        atomic_json(path.with_suffix('.json'), record)
        replace_file(temp, path)
        relative = path.relative_to(self.root / 'outputs').as_posix()
        # The result joins the tool list so it can be compared or processed further.
        self.gallery._last_scan = 0
        added = self.tools.add_gallery([relative])['added']
        if added:
            self.tools.set_parent(added[0]['id'], item['id'], op)
        return '/outputs/' + quote(relative, safe='/'), Path(path)
