"""HTTP client for a running ComfyUI instance."""

import json
import uuid
from pathlib import PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


class Comfy:
    def __init__(self, url):
        self.url = url.rstrip('/')
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, body=None, raw=False, timeout=15):
        req = Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with self.opener.open(req, timeout=timeout) as response:
                data = response.read()
            return data if raw else (json.loads(data) if data.strip() else None)
        except HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')[:3000]
            raise RuntimeError(f'ComfyUI 요청 실패 ({e.code}): {detail}') from e
        except (URLError, TimeoutError) as e:
            raise RuntimeError(
                'ComfyUI에 연결할 수 없습니다. ComfyUI가 실행 중인지 확인하세요.'
            ) from e

    def upload(self, name, raw, subfolder='asset_studio'):
        """Put an image in ComfyUI's input folder (``/upload/image``); returns its reference."""
        boundary = 'asset-studio-' + uuid.uuid4().hex
        parts = []
        for key, value in (('overwrite', 'true'), ('type', 'input'), ('subfolder', subfolder)):
            head = f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
            parts.append(f'{head}\r\n\r\n{value}\r\n'.encode())
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n'.encode()
            + raw
            + b'\r\n'
        )
        parts.append(f'--{boundary}--\r\n'.encode())
        req = Request(
            self.url + '/upload/image',
            data=b''.join(parts),
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        )
        try:
            with self.opener.open(req, timeout=60) as response:
                return json.loads(response.read())
        except HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')[:1000]
            raise RuntimeError(f'ComfyUI 이미지 업로드 실패 ({e.code}): {detail}') from e
        except (URLError, TimeoutError) as e:
            raise RuntimeError('ComfyUI에 연결할 수 없습니다.') from e

    def catalog(self):
        try:
            info = self.request('/object_info')

            def values(node, field):
                item = info.get(node, {}).get('input', {}).get('required', {}).get(field, [[]])[0]
                return item if isinstance(item, list) else []

            result = {
                'connected': True,
                'models': values('UNETLoader', 'unet_name'),
                'text_encoders': values('CLIPLoader', 'clip_name'),
                'vaes': values('VAELoader', 'vae_name'),
                'loras': values('LoraLoader', 'lora_name'),
                'samplers': values('KSampler', 'sampler_name'),
                'schedulers': values('KSampler', 'scheduler'),
                'clip_types': values('CLIPLoader', 'type'),
            }
            # Checkpoint and diffusion-model directories are distinct ComfyUI catalogs.
            # Keep qualified checkpoint IDs so equal filenames cannot select the wrong file.
            result['model_entries'] = {
                name: {'filename': name, 'loader': 'UNETLoader', 'label': name}
                for name in result['models']
            }
            for name in values('CheckpointLoaderSimple', 'ckpt_name'):
                ident = 'checkpoint::' + name
                result['models'].append(ident)
                result['model_entries'][ident] = {
                    'filename': name,
                    'loader': 'CheckpointLoaderSimple',
                    'label': name + ' [체크포인트]',
                }

            def prefer(key, *names):
                # Files may sit in a family sub-folder (``anima/name``); match the file name.
                # Names are tried in order: the Hugging Face name, then the Civitai one.
                for name in names:
                    found = [e for e in result[key] if PureWindowsPath(e).name == name]
                    if found:
                        return found[0]
                return next(iter(result[key]), '')

            result['defaults'] = dict(
                model=prefer(
                    'models',
                    'anima-aesthetic-v1.1.safetensors',
                    'anima_aestheticV11.safetensors',
                    'anima-base-v1.0.safetensors',
                ),
                text_encoder=prefer('text_encoders', 'qwen_3_06b_base.safetensors'),
                vae=prefer('vaes', 'qwen_image_vae.safetensors'),
                clip_type='stable_diffusion',
                steps=32,
                cfg=5,
                sampler=prefer('samplers', 'er_sde'),
                scheduler=prefer('schedulers', 'simple'),
                width=1536,
                height=1536,
                seed=-1,
                loras=[],
                text_encoder_device='default',
            )
            return result
        except Exception as e:
            return dict(
                connected=False,
                error=str(e),
                models=[],
                text_encoders=[],
                vaes=[],
                loras=[],
                samplers=[],
                schedulers=[],
                clip_types=[],
                defaults={},
            )
