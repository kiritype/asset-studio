"""Prepare the external trainer (anima_lora) for Asset Studio runs.

The trainer is installed separately (see README). Before each run Studio checks that
it carries Studio's small preprocessing patch, copies Studio's method files into it
and writes the base-model presets from ``data/settings/lora_pipeline.json`` into a
marked block of ``configs/presets.toml``, so no hand edits of the trainer are needed.
"""

import filecmp
import shutil
from pathlib import Path

from ..i18n import Msg

# Shipped with the program (next to the asset_studio package), not with the data.
SHIPPED = Path(__file__).resolve().parents[2] / 'trainer' / 'anima_lora'
PATCH = SHIPPED / 'preprocess-model-paths.patch'
METHODS_DIR = SHIPPED / 'methods'
PATCH_MARKER = '# asset-studio patch'
BLOCK_START = '# >>> asset-studio: written by Asset Studio from data/settings/lora_pipeline.json'
BLOCK_END = '# <<< asset-studio'

# Training bases: the official Anima base, or the Anima fine-tune used for generation.
BASES = {
    'official': {
        'label': Msg('server.trainer_setup.official_anima_base', 'Official Anima base'),
        'preset': 'asset_studio_base',
        'cache_dir': 'post_image_dataset/lora_base',
    },
    'generation': {
        'label': Msg('server.trainer_setup.generation_model', 'Generation model'),
        'preset': 'asset_studio',
        'cache_dir': 'post_image_dataset/lora',
    },
}
BASE_ALIASES = {'miaomiao': 'generation'}
MODEL_KEYS = {'dit': 'pretrained_model_name_or_path', 'text_encoder': 'qwen3', 'vae': 'vae'}


def configured_bases(settings):
    """``{id: {...BASES[id], paths, base_model}}`` for bases whose files are all set."""
    result = {}
    for ident, base in BASES.items():
        paths = (settings.get('bases') or {}).get(ident) or {}
        if all(paths.get(key) for key in MODEL_KEYS):
            stem = Path(paths['dit']).stem
            label = base['label'] if ident == 'official' else f'{base["label"]} ({stem})'
            result[ident] = {**base, 'label': label, 'paths': paths, 'base_model': stem}
    return result


def _preset_block(bases):
    lines = [BLOCK_START]
    for base in bases.values():
        lines.append(f'[{base["preset"]}]')
        for key, field in MODEL_KEYS.items():
            path = str(base['paths'][key]).replace('\\', '/')
            lines.append(f'{field} = "{path}"')
        lines += [
            'vocab_pack = ""',
            'torch_compile = false',
            'use_repa = false',
            f'lora_cache_dir = "{base["cache_dir"]}"',
            '',
        ]
    lines.append(BLOCK_END)
    return '\n'.join(lines) + '\n'


def write_presets(path, bases):
    """Replace Studio's marked block in presets.toml, leaving the trainer's own presets alone."""
    text = path.read_text(encoding='utf-8') if path.is_file() else ''
    if BLOCK_START in text and BLOCK_END in text:
        head, rest = text.split(BLOCK_START, 1)
        tail = rest.split(BLOCK_END, 1)[1].lstrip('\n')
        text = head.rstrip('\n') + '\n\n' + tail
    presets = {base['preset'] for base in bases.values()}
    for line in text.splitlines():
        name = line.strip().strip('[]')
        if line.startswith('[') and name in presets:
            raise ValueError(
                Msg(
                    'server.trainer_setup.already_has_a_preset_asset_studio',
                    '{path} already has a [{name}] preset. Asset Studio manages that name; remove '
                    'that section and try again.',
                    path=path,
                    name=name,
                )
            )
    path.write_text(text.rstrip('\n') + '\n\n' + _preset_block(bases), encoding='utf-8')


def prepare(root, settings):
    """Check and configure the trainer; returns the configured bases. Raises with a fix."""
    trainer = Path(settings['trainer_dir'])
    if not (trainer / 'train.py').is_file():
        raise ValueError(
            Msg(
                'server.trainer_setup.trainer_anima_lora_not_found_install',
                'Trainer (anima_lora) not found: {trainer}. Install it following "LoRA training" '
                'in the README.',
                trainer=trainer,
            )
        )
    preprocess = trainer / 'scripts' / 'tasks' / 'preprocess.py'
    if not preprocess.is_file() or PATCH_MARKER not in preprocess.read_text(encoding='utf-8'):
        raise ValueError(
            Msg(
                'server.trainer_setup.the_asset_studio_patch_is_not',
                'The Asset Studio patch is not applied to anima_lora. Run git apply "{patch}" in '
                'the trainer folder.',
                patch=PATCH,
            )
        )
    bases = configured_bases(settings)
    if not bases:
        raise ValueError(
            Msg(
                'server.trainer_setup.set_the_training_model_files_in',
                'Set the training model files in Settings › LoRA training.',
            )
        )
    for base in bases.values():
        for key in MODEL_KEYS:
            if not Path(base['paths'][key]).is_file():
                raise ValueError(
                    Msg(
                        'server.trainer_setup.training_model_file_not_found',
                        'Training model file not found: {paths}',
                        paths=base['paths'][key],
                    )
                )
    methods = trainer / 'configs' / 'methods'
    methods.mkdir(parents=True, exist_ok=True)
    for source in sorted(METHODS_DIR.glob('*.toml')):
        target = methods / source.name
        if not target.is_file() or not filecmp.cmp(source, target, shallow=False):
            shutil.copyfile(source, target)
    write_presets(trainer / 'configs' / 'presets.toml', bases)
    return bases
