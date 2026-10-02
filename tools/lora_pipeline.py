"""Train character LoRAs through a running Asset Studio server.

Targets are always ``WORK/CHARACTER/OUTFIT_SET`` (a character code is only unique inside
its work). The server builds the dataset from the adopted images, waits for the GPU,
runs the trainer and copies every saved epoch into the ComfyUI LoRA folder.

    python tools/lora_pipeline.py W001/C041/001
    python tools/lora_pipeline.py W001/C041/001 --dry-run       # dataset + captions only
    python tools/lora_pipeline.py W001/C041/001 --epochs 40 --learning-rate 1e-4
    python tools/lora_pipeline.py W001/C041/001 --all-images    # every image, not only adopted

Trainer paths come from ``data/settings/lora_pipeline.json``
(see ``config/lora_pipeline.example.json``).
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

POLL_SECONDS = 15
FINISHED = ('done', 'failed', 'cancelled', 'interrupted')


def call(server, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        server + path, data=data, headers={'Content-Type': 'application/json'}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        reason = json.loads(error.read() or b'{}').get('error', str(error))
        raise SystemExit(f'{path}: {reason}') from None
    except urllib.error.URLError as error:
        raise SystemExit(f'Asset Studio에 연결할 수 없습니다 ({server}): {error.reason}') from None


def follow(server, work, character, run):
    """Print progress until the run ends; returns the final record."""
    query = urllib.parse.urlencode({'work': work, 'character': character, 'id': run['id']})
    last = None
    while run['status'] not in FINISHED:
        time.sleep(POLL_SECONDS)
        run = call(server, f'/api/lora/run?{query}')
        progress = run.get('progress') or {}
        line = f'  {run["status"]}'
        if progress.get('step'):
            line += f' · step {progress["step"]}/{progress.get("total_steps")}'
            line += f' · epoch {progress.get("epoch")}'
        if line != last:
            print(line)
            last = line
    return run


def process(server, target, options):
    work, character, outfit = target.split('/')
    who = {'work_id': work, 'character_id': character}
    query = urllib.parse.urlencode({'work': work, 'character': character, 'outfit': outfit})
    pool = call(server, f'/api/lora/candidates?{query}')['items']
    paths = [item['path'] for item in pool if options.all_images or item['selected']]
    kind = 'images' if options.all_images else 'adopted images'
    print(f'\n== {target}: {len(paths)} {kind}')
    if len(paths) < options.min_images:
        raise SystemExit(f'  need at least {options.min_images} images (see --min-images).')
    body = {**who, 'outfit_set_id': outfit, 'paths': paths}
    if options.dataset_name:
        body['name'] = options.dataset_name
    triggers = {
        key: value
        for key, value in (
            ('character', options.trigger_character),
            ('outfit', options.trigger_outfit),
        )
        if value
    }
    if triggers:
        body['triggers'] = triggers
    dataset = call(server, '/api/lora/datasets/save', body)['entity']
    print(f'  dataset {dataset["id"]}, triggers {dataset["triggers"]}')
    print(f'  example caption: {dataset["items"][0]["caption"]}')
    if options.dry_run:
        print('  dry run: dataset saved, no training started.')
        return
    params = {
        'epochs': options.epochs,
        'save_every': options.save_every,
        'learning_rate': options.learning_rate,
    }
    start = {**who, 'dataset_id': dataset['id'], 'params': params}
    run = call(server, '/api/lora/runs/start', start)['run']
    print(f'  run {run["id"]} -> {run["output_name"]} (log: {run["log_path"]})')
    run = follow(server, work, character, run)
    if run['status'] != 'done':
        raise SystemExit(f'  training {run["status"]}: {run.get("error", "")}')
    print('  done: ' + ', '.join(output['file'] for output in run['outputs']))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('targets', nargs='+', metavar='WORK/CHARACTER/OUTFIT_SET')
    parser.add_argument('--server', default='http://127.0.0.1:8195')
    parser.add_argument('--epochs', type=int, default=40)
    parser.add_argument('--save-every', type=int, default=10)
    parser.add_argument('--learning-rate', default='1e-4')
    parser.add_argument('--min-images', type=int, default=15)
    parser.add_argument('--dataset-name', help='name of the saved dataset')
    parser.add_argument('--trigger-character', help='only with a single target')
    parser.add_argument('--trigger-outfit', help='only with a single target')
    parser.add_argument(
        '--all-images',
        action='store_true',
        help='use every image of the outfit set instead of the adopted ones',
    )
    parser.add_argument('--dry-run', action='store_true', help='save the dataset only')
    options = parser.parse_args()
    for target in options.targets:
        if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', target):
            parser.error(f'target must look like W001/C041/001: {target}')
    if len(options.targets) > 1 and (options.trigger_character or options.trigger_outfit):
        parser.error('custom triggers need exactly one target')
    for target in options.targets:
        process(options.server.rstrip('/'), target, options)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
