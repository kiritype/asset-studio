"""Configured local OpenAI-compatible vision adapter and explicit model ownership."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from PIL import Image

from ..i18n import message_of
from ..util import settings_file


class VLMError(RuntimeError):
    pass


class LocalVLM:
    def __init__(self, root):
        self.path = Path(
            os.environ.get('ASSET_STUDIO_VLM_CONFIG') or settings_file(root, 'vlm.json')
        )
        self.config = {}
        self.error = None
        self.owned = False
        self.reload()

    @staticmethod
    def _value(config, key):
        env = config.get(key + '_env')
        return os.environ.get(env, '') if env else config.get(key, '')

    def reload(self):
        self.error = None
        try:
            config = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            if not isinstance(config, dict):
                raise VLMError('VLM configuration must be an object')
            self.config = config
            if config.get('enabled'):
                url = self._value(config, 'url')
                model = self._value(config, 'model')
                parsed = urlparse(url)
                if (
                    parsed.scheme != 'http'
                    or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                    or not parsed.port
                    or parsed.username
                    or parsed.password
                ):
                    raise VLMError('VLM URL must be a local HTTP endpoint with a port')
                if not model or len(model) > 500:
                    raise VLMError('VLM model identifier is required')
                for key in ('load_command', 'unload_command', 'status_command'):
                    command = config.get(key)
                    if (
                        not isinstance(command, list)
                        or not command
                        or not all(isinstance(x, str) and x and len(x) < 1000 for x in command)
                    ):
                        raise VLMError(f'{key} must be an argv array')
                if not config.get('loaded_marker'):
                    raise VLMError('loaded_marker is required to verify actual model residency')
        except Exception as exc:
            self.error = message_of(exc)
            self.config = {'enabled': False}

    @property
    def enabled(self):
        return bool(self.config.get('enabled')) and not self.error

    def public_status(self):
        return {
            'configured': self.enabled,
            'config_path': str(self.path),
            'model': self._value(self.config, 'model') if self.enabled else '',
            'error': self.error,
            'provider': 'openai_compatible_local',
            'model_resource': self.config.get('model_resource', ''),
            'max_output_tokens': self.config.get('max_output_tokens', 180),
            'review_instruction_version': self.config.get('review_instruction_version', 'legacy'),
        }

    def _command(self, key):
        command = self.config[key]
        # Config contains argv, never a shell script or interpolated command line.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            shell=False,
            encoding='utf-8',
            errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            timeout=max(1, min(int(self.config.get('command_timeout_seconds', 120)), 600)),
        )
        if result.returncode:
            raise VLMError(f'{key} failed (exit {result.returncode})')
        return result.stdout

    def _loaded_instances(self):
        if not self.enabled:
            raise VLMError(self.error or 'VLM is not configured')
        output = self._command('status_command')
        try:
            parsed = json.loads(output)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                for key in ('models', 'loaded', 'instances'):
                    if isinstance(parsed.get(key), list):
                        return parsed[key]
        except ValueError:
            pass
        # A text status command can only establish target presence, not whether
        # other GPU models are loaded. Require JSON for safe scheduling.
        raise VLMError('status_command must return a JSON list of loaded instances')

    def is_loaded(self):
        marker = self.config['loaded_marker']
        return any(marker in json.dumps(item) for item in self._loaded_instances())

    def load(self):
        instances = self._loaded_instances()
        if instances:
            raise VLMError('Another VLM instance is already loaded; ownership is uncertain')
        self._command('load_command')
        loaded_after = self._loaded_instances()
        if not any(self.config['loaded_marker'] in json.dumps(item) for item in loaded_after):
            raise VLMError('VLM load was not confirmed by status_command')
        if len(loaded_after) != 1:
            raise VLMError('Additional VLM instance appeared during load')
        self.owned = True

    def unload(self):
        if not self.owned:
            raise VLMError('Cannot unload a VLM instance this process did not load')
        self._command('unload_command')
        if self.is_loaded():
            raise VLMError('VLM remains loaded after unload_command')
        self.owned = False

    def test(self):
        if not self.enabled:
            return {
                **self.public_status(),
                'ok': False,
                'loaded': False,
                'service_connected': False,
            }

        try:
            url = self._value(self.config, 'url').rstrip('/') + '/v1/models'
            headers = {}
            key = self._value(self.config, 'api_key')
            if key:
                headers['Authorization'] = 'Bearer ' + key
            with build_opener(ProxyHandler({})).open(
                Request(url, headers=headers), timeout=5
            ) as response:
                json.load(response)
            loaded = self.is_loaded()
            return {
                **self.public_status(),
                'ok': True,
                'loaded': loaded,
                'service_connected': True,
                'status': 'loaded' if loaded else 'connected_unloaded',
            }
        except Exception as exc:
            return {
                **self.public_status(),
                'ok': False,
                'loaded': False,
                'service_connected': False,
                'status': 'error',
                'error': 'VLM connection test failed: ' + type(exc).__name__,
            }

    def review(self, image_path, snapshot):
        if not self.is_loaded():
            raise VLMError('VLM is not loaded')
        with Image.open(image_path) as image:
            image.thumbnail((768, 768))
            output = io.BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=85)
        parts = snapshot.get('parts') or {}
        criterion = '\n'.join(
            f'{key}: {str(parts.get(key) or "")}'
            for key in ('work', 'appearance', 'outfit', 'expression', 'composition')
            if parts.get(key)
        )
        if not criterion:
            criterion = str(snapshot.get('positive') or '')
        if len(criterion) > 12000:
            raise VLMError(
                'Review criteria exceed configured context budget; human review required'
            )
        instruction = self.config.get('review_instruction') or (
            'Assess this generated character image against these visible requirements only. '
            'PASS requires clear evidence for every visible requirement; '
            'FAIL means a clear mismatch; '
            'UNCERTAIN means evidence is insufficient. Do not infer hidden details. '
            'Count each rendered human body. Return short JSON with verdict and evidence.'
        )
        if not isinstance(instruction, str) or not 1 <= len(instruction) <= 6000:
            raise VLMError('Invalid review_instruction')
        max_tokens = self.config.get('max_output_tokens', 180)
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 64 <= max_tokens <= 4096
        ):
            raise VLMError('max_output_tokens must be an integer from 64 to 4096')
        prompt = instruction + '\n' + criterion
        schema = {
            'type': 'object',
            'properties': {
                'verdict': {'type': 'string', 'enum': ['pass', 'fail', 'uncertain']},
                'evidence': {'type': 'string'},
            },
            'required': ['verdict', 'evidence'],
            'additionalProperties': False,
        }
        body = {
            'model': self._value(self.config, 'model'),
            'temperature': 0,
            'max_tokens': max_tokens,
            'messages': [
                {'role': 'system', 'content': 'Review one image independently. Return only JSON.'},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': 'data:image/jpeg;base64,'
                                + base64.b64encode(output.getvalue()).decode('ascii')
                            },
                        },
                    ],
                },
            ],
            'response_format': {
                'type': 'json_schema',
                'json_schema': {'name': 'review', 'strict': True, 'schema': schema},
            },
        }
        url = self._value(self.config, 'url').rstrip('/') + '/v1/chat/completions'
        key = self._value(self.config, 'api_key')
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(
                Request(url, data=json.dumps(body).encode(), headers=headers),
                timeout=max(1, min(int(self.config.get('request_timeout_seconds', 180)), 600)),
            ) as response:
                result = json.load(response)
            choice = result['choices'][0]
            if choice.get('finish_reason') not in ('stop', None):
                raise VLMError('VLM response was truncated')
            answer = json.loads(choice['message']['content'])
            verdict, evidence = answer['verdict'], answer['evidence']
            if (
                verdict not in ('pass', 'fail', 'uncertain')
                or not isinstance(evidence, str)
                or not evidence.strip()
                or len(evidence) > 1000
            ):
                raise ValueError('invalid verdict or evidence')
            # Model text is advisory. Contradictions are held for a person.
            low = evidence.lower()
            if verdict == 'pass' and any(
                word in low
                for word in (
                    'missing',
                    'absent',
                    'wrong',
                    'cannot tell',
                    'unclear',
                    'violat',
                    'mismatch',
                    'not visible',
                )
            ):
                return {
                    'verdict': 'uncertain',
                    'evidence': 'Contradictory VLM response: ' + evidence[:300],
                }
            return {'verdict': verdict, 'evidence': evidence.strip()}
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise VLMError('Invalid VLM response') from exc
        except Exception as exc:
            if isinstance(exc, VLMError):
                raise
            raise VLMError('VLM request failed: ' + type(exc).__name__) from exc
