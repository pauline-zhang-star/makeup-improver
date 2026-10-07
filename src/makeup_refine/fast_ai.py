"""Compact transport contracts; canonical validators still decide acceptance."""
import json
from PIL import Image, ImageDraw
from .model_planning import LookDesign, planning_response_format, planning_prompt
from .look_models import LookComparison
from .look_prompts import comparison_prompt


def planning_contract(style):
    response = planning_response_format()
    schema = response['json_schema']['schema']
    for name in ('PlacementTechnique', 'ColorTechnique'):
        node = schema['$defs'][name]
        for field in ('observation', 'style_reason', 'application_zh'):
            node['properties'].pop(field)
            node['required'].remove(field)
    prompt = planning_prompt(style, include_schema=False)
    prompt = prompt.replace(
        'Also give application_zh as a concise Simplified Chinese version of the SAME application; '
        'do not add an extra technique or change its strength in translation. ', '')
    prompt = prompt.replace(
        'For each proposal provide observation (what is actually visible in the original, including '
        'existing makeup), style_reason (why this change supports the whole chosen look), and application '
        '(where and how to apply this catalog technique on this photo, within its bounds). ',
        'For each proposal give the observation and whole-look style_reason in structured_evidence, '
        'and application describing where and how to execute the bounded technique. ')
    prompt += (' Transport rule: write observation and style_reason ONLY inside structured_evidence. '
               'Write application once in English; bilingual teaching comes after the user likes the image. '
               'Each evidence sentence at most 12 English words, application at most 20 words, '
               'look_direction at most 25 words. Keep all required numeric parameters and observations.')
    return prompt, response


def planning_decode(content):
    data = json.loads(content)
    for decision in data['region_decisions']:
        if decision.get('kind') == 'propose':
            # Unexpected fields must be rejected rather than overwritten.
            if any(key in decision for key in ('observation', 'style_reason', 'application_zh')):
                raise ValueError('Duplicate planning transport fields.')
            evidence = decision['structured_evidence']
            decision.update(observation=evidence['observation'], style_reason=evidence['style_reason'],
                            application_zh=None)
    return LookDesign.model_validate(data)


COMPARISON_KEYS = {'area': 'a', 'change': 'c', 'confidence': 'p', 'before': 'b',
                   'after': 't', 'instruction': 'i', 'instruction_zh': 'z'}


def comparison_contract():
    schema = LookComparison.model_json_schema()
    row = schema['$defs']['AreaComparison']
    row['properties'] = {COMPARISON_KEYS[k]: v for k, v in row['properties'].items()}
    base = row['properties']
    variants = []
    for change, fields in (('changed', ('a','c','p','b','t','i','z')),
                           ('unchanged', ('a','c','p','b')),
                           ('uncertain', ('a','c','p','b','t'))):
        properties = {key: base[key] for key in fields}
        properties['c'] = {'type': 'string', 'enum': [change]}
        variants.append({'type': 'object', 'properties': properties})
    schema['properties']['assessments']['items'] = {'anyOf': variants}
    schema['properties'] = {'p': schema['properties']['preservationIssues'],
                            'a': schema['properties']['assessments']}
    def close(node):
        if isinstance(node, dict):
            for key in ('default', 'title', 'minLength', 'maxLength'):
                node.pop(key, None)
            if node.get('type') == 'object':
                node['additionalProperties'] = False
                node['required'] = list(node['properties'])
            for child in node.values():
                close(child)
        elif isinstance(node, list):
            for child in node:
                close(child)
    close(schema)
    prompt = comparison_prompt(include_schema=False)
    prompt += (' Transport keys: top p=preservationIssues, a=assessments. For each assessment '
               'a=area,c=change,p=confidence,b=before,t=after,i=instruction,z=instruction_zh. '
               'Use at most 12 English words per before/after (lips may use 18 to record mouth/teeth), '
               '20 English words per instruction and 45 Chinese characters per instruction_zh. '
               'Keep exact location, direction and technique. For unchanged areas write the identical '
               'observed state once in b, omit t/i/z. For uncertain areas keep b/t and omit i/z. '
               'Do not omit any area or preservation check.')
    return prompt, {'type': 'json_schema', 'json_schema': {
        'name': 'observed_makeup_changes', 'strict': True, 'schema': schema}}


def comparison_decode(content):
    data = json.loads(content)
    if set(data) != {'p', 'a'}:
        raise ValueError('Invalid comparison transport fields.')
    reverse = {v: k for k, v in COMPARISON_KEYS.items()}
    rows = []
    for row in data['a']:
        expected = {'changed': set(reverse), 'unchanged': {'a','c','p','b'},
                    'uncertain': {'a','c','p','b','t'}}.get(row.get('c'))
        if expected is None or set(row) not in (expected, set(reverse)):
            raise ValueError('Incomplete comparison transport fields.')
        expanded = {reverse[k]: v for k, v in row.items()}
        if 't' not in row:
            expanded['after'] = row['b']
        expanded.setdefault('instruction', None)
        expanded.setdefault('instruction_zh', None)
        rows.append(expanded)
    return LookComparison.model_validate({'preservationIssues': data['p'], 'assessments': rows})


def detail_boards(original, enhanced, evidence):
    """Keep every unique matched crop, without artificial 3x enlargement.

    Lossless side-by-side boards retain labels and crop coordinates. Up to
    three rows share an image; full photos are sent separately for preservation.
    """
    pairs = []
    seen = set()
    for region in evidence['regions']:
        for box in region['cropBoxes']:
            key = tuple(box)
            if key in seen:
                continue
            seen.add(key)
            areas = sorted({r['area'] for r in evidence['regions'] if box in r['cropBoxes']})
            crops = [source.crop(key).convert('RGB') for source in (original, enhanced)]
            scale = min(1., 512 / max(crops[0].size))
            size = tuple(max(1, round(value * scale)) for value in crops[0].size)
            if scale < 1:
                crops = [crop.resize(size, Image.Resampling.LANCZOS) for crop in crops]
            pairs.append((crops, ','.join(areas) + ' ' + str(box)))
    for start in range(0, len(pairs), 3):
        rows = pairs[start:start + 3]
        width = max(2 * crops[0].width for crops, _ in rows)
        board = Image.new('RGB', (max(width, 480), sum(crops[0].height + 36 for crops, _ in rows)), 'white')
        draw = ImageDraw.Draw(board)
        y = 0
        for crops, label in rows:
            draw.text((2, y), label, fill='black')
            draw.text((2, y + 16), 'ORIGINAL', fill='black')
            draw.text((board.width // 2 + 2, y + 16), 'ENHANCED', fill='black')
            board.paste(crops[0], (0, y + 36))
            board.paste(crops[1], (board.width // 2, y + 36))
            y += crops[0].height + 36
        yield board
