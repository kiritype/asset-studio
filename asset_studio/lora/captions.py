"""Training captions built from an image's generation record.

Order follows the trainer guide: rating, count, character trigger, outfit trigger,
artist, then general tags (framing, background, expression).
"""

import re

BACKGROUND_TAGS = ('white background', 'simple background')
SENTENCE = re.compile(r'^[A-Z].* .* ')


def tags_of(text, stop_at_sentence=True):
    """Comma tags without weights; stops at the first natural-language sentence."""
    out = []
    for token in (t.strip() for t in str(text or '').split(',')):
        token = re.sub(r'^\((.*):[\d.]+\)$', r'\1', token).strip().rstrip('.')
        if not token:
            continue
        if stop_at_sentence and SENTENCE.match(token):
            break
        out.append(token)
    return out


def caption(meta, triggers):
    """Caption for one image. ``meta`` is the image's JSON sidecar."""
    parts = meta.get('parts') or {}
    appearance = tags_of(parts.get('appearance'))
    count = next((t for t in appearance if re.fullmatch(r'\d(girl|boy)s?', t)), '1girl')
    common = parts.get('common', parts.get('quality'))  # v1 images named it "quality".
    general = (['solo'] if 'solo' in appearance else []) + tags_of(parts.get('composition'))
    general += [t for t in tags_of(common, stop_at_sentence=False) if t in BACKGROUND_TAGS]
    general += [t for t in tags_of(parts.get('expression')) if t != 'pov']
    rating = 'safe' if meta.get('category') == 'sfw' else 'nsfw'
    ordered, seen = [], set()
    for tag in [
        rating,
        count,
        triggers.get('character', ''),
        triggers.get('outfit', ''),
        *tags_of(parts.get('artist'), stop_at_sentence=False),
        *general,
    ]:
        if tag and tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    return ', '.join(ordered)


def default_triggers(work_id, character_id, outfit_set_id):
    base = f'{work_id}_{character_id}'.lower()
    return {'character': base, 'outfit': f'{base}_{outfit_set_id}'.lower()}
