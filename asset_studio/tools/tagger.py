"""WD14 tagging as queue jobs: the image goes to ComfyUI, the tagger node reads it.

Tag jobs share the generation queue, so they wait for images being generated and
follow the same GPU rules. The node is ``WD14Tagger|pysssss`` (ComfyUI-WD14-Tagger);
it downloads its model from Hugging Face the first time a model is used.
"""

import io
import json
import uuid
import zipfile
from pathlib import PurePosixPath

from ..i18n import Msg, message_of
from ..util import now

NODE = 'WD14Tagger|pysssss'
DEFAULTS = {'model': 'wd-eva02-large-tagger-v3', 'threshold': 0.35, 'character_threshold': 0.85}
MAX_IDS = 500


def tag_settings(body, models):
    settings = {**DEFAULTS}
    for key in ('model', 'threshold', 'character_threshold'):
        if body.get(key) is not None:
            settings[key] = body[key]
    if models and settings['model'] not in models:
        raise ValueError(
            Msg(
                'server.tagger.choose_a_tagger_model_from_the',
                'Choose a tagger model from the list.',
            )
        )
    for key in ('threshold', 'character_threshold'):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(
                Msg(
                    'server.tagger.thresholds_must_be_between_0_and',
                    'Thresholds must be between 0 and 1.',
                )
            )
        settings[key] = float(value)
    return settings


def graph(image_name, settings):
    return {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': image_name}},
        '2': {
            'class_type': NODE,
            'inputs': {
                'image': ['1', 0],
                'model': settings['model'],
                'threshold': settings['threshold'],
                'character_threshold': settings['character_threshold'],
                'replace_underscore': True,
                'trailing_comma': False,
                'exclude_tags': '',
            },
        },
    }


def tags_of(entry):
    """Tag list from a finished history entry; the node returns one joined string."""
    texts = (entry.get('outputs', {}).get('2') or {}).get('tags') or []
    if not texts:
        raise RuntimeError(
            Msg('server.tagger.the_tagger_returned_no_result', 'The tagger returned no result.')
        )
    return [
        t.strip().replace('\\(', '(').replace('\\)', ')') for t in texts[0].split(',') if t.strip()
    ]


def norm(tag):
    """Compare tags the way the page does: case, underscores and a leading @ do not count."""
    return tag.lower().replace('_', ' ').removeprefix('@').strip()


class TaggerMixin:
    """Tag-job part of ``Studio``."""

    def tag_excludes(self):
        from ..settings_api import _read

        values, _ = _read(self.root, 'tags')
        return list(values.get('exclude') or [])

    def tagger_info(self):
        exclude = self.tag_excludes()
        try:
            info = self.comfy.request('/object_info/' + NODE.replace('|', '%7C'))
            spec = info[NODE]['input']['required']
            return {
                'available': True,
                'models': spec['model'][0],
                'defaults': DEFAULTS,
                'exclude': exclude,
            }
        except Exception as error:
            return {
                'available': False,
                'error': Msg(
                    'server.tagger.wd14_tagger_node_not_found',
                    'WD14 tagger node not found: {error}',
                    error=message_of(error),
                ),
                'exclude': exclude,
            }

    def export_tags(self, ids, kind):
        """Tags of the chosen images without the excluded ones: (bytes, file name, type).

        ``txt`` is a ZIP of one caption per image, named like the image ZIP so the two
        pair up when extracted together; ``json`` is one file with every image.
        """
        if kind not in ('txt', 'json'):
            raise ValueError(
                Msg(
                    'server.tagger.the_export_format_is_txt_or', 'The export format is txt or json.'
                )
            )
        skip = {norm(tag) for tag in self.tag_excludes()}
        rows = []
        for item, name in self.tools.zip_names(ids):
            if not item.get('tags'):
                continue
            tags = [tag for tag in item['tags']['tags'] if norm(tag) not in skip]
            rows.append((item, name, tags))
        if not rows:
            raise ValueError(
                Msg(
                    'server.tagger.none_of_the_chosen_images_has',
                    'None of the chosen images has been tagged.',
                )
            )
        if kind == 'json':
            data = [
                {
                    'name': item['name'],
                    'path': item['path'] if item['source'] == 'gallery' else None,
                    'file': name,
                    'tags': tags,
                    'model': item['tags'].get('model'),
                }
                for item, name, tags in rows
            ]
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
            return raw, f'tags-{len(rows)}.json', 'application/json'
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            for _, name, tags in rows:
                caption = PurePosixPath(name).with_suffix('.txt').as_posix()
                archive.writestr(caption, ', '.join(tags))
        return out.getvalue(), f'tags-{len(rows)}.zip', 'application/zip'

    def enqueue_tags(self, body):
        ids = body.get('ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS:
            raise ValueError(
                Msg(
                    'server.tagger.choose_1_to_images_to_tag',
                    'Choose 1 to {max_ids} images to tag.',
                    max_ids=MAX_IDS,
                )
            )
        info = self.tagger_info()
        if not info['available']:
            raise ValueError(info['error'])
        settings = tag_settings(body, info['models'])
        items = [self.tools.get(i) for i in ids]
        prepared = [
            dict(
                id=uuid.uuid4().hex,
                kind='tag',
                status='queued',
                created_at=now(),
                title=Msg('server.tagger.tagging', 'Tagging · {name}', name=item['name']),
                tool_item=item['id'],
                tag_settings=settings,
                seed=None,
                review_requested=False,
                snapshot={'kind': 'tag', 'tool_item': item['id'], 'tag_settings': settings},
            )
            for item in items
        ]
        with self.lock:
            if sum(j['status'] == 'queued' for j in self.jobs) + len(prepared) > 5000:
                raise ValueError(
                    Msg(
                        'server.tagger.too_many_queued_jobs_let_the',
                        'Too many queued jobs. Let the queue run first.',
                    )
                )
            self.jobs.extend(prepared)
            self.persist()
        return {
            'ok': True,
            'jobs': [{k: v for k, v in j.items() if k != 'snapshot'} for j in prepared],
        }

    def tag_graph(self, job):
        """Upload the job's image to ComfyUI's input folder and build the tagging graph."""
        item = self.tools.get(job['tool_item'])
        path = self.tools.file(item)
        name = f'asset_studio_tag_{item["id"]}{path.suffix.lower()}'
        uploaded = self.comfy.upload(name, path.read_bytes())
        reference = (
            f'{uploaded["subfolder"]}/{uploaded["name"]}'
            if uploaded.get('subfolder')
            else uploaded['name']
        )
        return graph(reference, job['tag_settings'])

    def finish_tags(self, job, entry):
        tags = tags_of(entry)
        self.tools.set_tags(
            job['tool_item'],
            {'tags': tags, **job['tag_settings'], 'job_id': job['id'], 'at': now()},
        )
        return tags
