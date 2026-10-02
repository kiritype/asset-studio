"""Sort model files into ``anima/`` and ``sdxl/`` sub-folders.

    python tools/organize_models.py            # show what would move
    python tools/organize_models.py --apply    # move, then fix Studio references
    python tools/organize_models.py --undo backups/models-<stamp>.json

Covers the checkpoint, diffusion model and LoRA folders of the shared model folder
(see ``models_dir`` in data/settings/models.json). Files whose family cannot be told
stay where they are. Sidecars (``.cm-info.json``, previews) move with their model.

ComfyUI lists a moved file as ``anima\\<name>``; Studio's generation presets, LoRA
registry, training-run outputs and the trainer's LoRA output folder are updated to match. Records of
images already made keep the old names, as history.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asset_studio.models import FAMILIES, KIND_FOLDERS, ModelProfiles, family_from_folder, sidecars
from asset_studio.util import atomic_json, settings_file

KINDS = ('checkpoints', 'diffusion_models', 'loras')
SUFFIXES = ('.safetensors', '.ckpt', '.pt', '.pth', '.gguf')


def plan(profiles):
    base = profiles.models_dir()
    if base is None:
        raise SystemExit('Set models_dir in data/settings/models.json.')
    moves = []
    for kind in KINDS:
        folder = base / KIND_FOLDERS[kind][0]
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            family, how = profiles.detect(kind, path.name)
            if family not in FAMILIES or family_from_folder(path.name):
                continue
            target = folder / family / path.name
            moves.append(
                {
                    'kind': kind,
                    'name': path.name,
                    'family': family,
                    'how': how,
                    'source': str(path),
                    'target': str(target),
                    'sidecars': [str(item) for item in sidecars(path)],
                }
            )
    return moves


def renamed(moves):
    """Old ComfyUI name -> new name, per kind."""
    names = {}
    for move in moves:
        names.setdefault(move['kind'], {})[move['name']] = f'{move["family"]}\\{move["name"]}'
    return names


def fix_references(root, names, settings_backup):
    """Point Studio's presets, registry and trainer output at the moved files."""
    data = root / 'data'
    changed = []
    checkpoints = names.get('checkpoints', {})
    models = {
        **names.get('diffusion_models', {}),
        **{f'checkpoint::{k}': f'checkpoint::{v}' for k, v in checkpoints.items()},
    }
    loras = names.get('loras', {})
    for path in sorted((data / 'presets' / 'generation').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        settings = record.get('settings') or {}
        before = json.dumps(settings, ensure_ascii=False)
        if settings.get('model') in models:
            settings['model'] = models[settings['model']]
        for lora in settings.get('loras') or []:
            if lora.get('name') in loras:
                lora['name'] = loras[lora['name']]
        if json.dumps(settings, ensure_ascii=False) != before:
            settings_backup[str(path)] = path.read_text(encoding='utf-8')
            atomic_json(path, record)
            changed.append(path)
    for path in sorted((data / 'loras').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('file') in loras:
            settings_backup[str(path)] = path.read_text(encoding='utf-8')
            record['file'] = loras[record['file']]
            atomic_json(path, record)
            changed.append(path)
    for path in sorted(data.glob('works/*/characters/*/lora_runs/*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        outputs = record.get('outputs') or []
        if any(output.get('file') in loras for output in outputs):
            settings_backup[str(path)] = path.read_text(encoding='utf-8')
            for output in outputs:
                output['file'] = loras.get(output['file'], output['file'])
            atomic_json(path, record)
            changed.append(path)
    trainer = settings_file(root, 'lora_pipeline.json')
    if trainer.is_file() and loras:
        record = json.loads(trainer.read_text(encoding='utf-8'))
        lora_dir = Path(record.get('lora_dir') or '')
        if lora_dir.name and lora_dir.name.lower() not in FAMILIES:
            settings_backup[str(trainer)] = trainer.read_text(encoding='utf-8')
            # Studio trains Anima LoRAs, so new ones land in the anima folder.
            record['lora_dir'] = str(lora_dir / 'anima').replace('\\', '/')
            atomic_json(trainer, record)
            changed.append(trainer)
    return changed


def apply(root, moves):
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    log = root / 'backups' / f'models-{stamp}.json'
    record = {'moves': [], 'files': {}}
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        for move in moves:
            target = Path(move['target'])
            target.parent.mkdir(exist_ok=True)
            for source in [move['source'], *move['sidecars']]:
                destination = target.parent / Path(source).name
                if destination.exists():
                    raise SystemExit(f'Already exists, nothing overwritten: {destination}')
                shutil.move(source, destination)
                record['moves'].append([source, str(destination)])
        changed = fix_references(root, renamed(moves), record['files'])
    finally:
        log.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
    return log, changed


def undo(log_path):
    record = json.loads(Path(log_path).read_text(encoding='utf-8'))
    for source, destination in reversed(record['moves']):
        if Path(destination).exists() and not Path(source).exists():
            shutil.move(destination, source)
    for path, text in record['files'].items():
        Path(path).write_text(text, encoding='utf-8')
    print(
        f'Undone: {len(record["moves"])} files moved back, {len(record["files"])} records restored.'
    )


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--undo', metavar='LOG')
    args = parser.parse_args()
    if args.undo:
        return undo(args.undo)
    moves = plan(ModelProfiles(ROOT))
    for move in moves:
        extra = f' (+{len(move["sidecars"])} sidecars)' if move['sidecars'] else ''
        print(f'{move["kind"]:17} {move["family"]:5} [{move["how"]}] {move["name"]}{extra}')
    print(f'{len(moves)} files to move.')
    if not args.apply:
        print('Nothing moved. Add --apply to move them.')
        return None
    log, changed = apply(ROOT, moves)
    print(f'Moved. Undo log: {log}')
    for path in changed:
        print(f'  updated {path}')
    return None


if __name__ == '__main__':
    main()
