"""Rebuild a placement demo's guide using saved images only; no API calls."""
import argparse
import json
from pathlib import Path
from PIL import Image
from makeup_refine.guidance import guided_change
from makeup_refine.models import Change
from makeup_refine.report import write_report


def render(directory):
    metadata = json.loads((directory / 'positions.json').read_text())
    types = {'eyeliner': 'lift_outer_wing', 'eyeshadow': 'blend_upward', 'lips': 'refine_edge'}
    masks, changes = {}, []
    for index, region in enumerate(metadata['regions']):
        area = region['area']
        masks[area] = Image.open(directory / f'mask-{area}.png').convert('L')
        change = Change(area=area, type=types[area], severity='subtle',
                        instruction=region['intendedChange'],
                        rationale='User-requested placement demo; not an automatic recommendation.')
        changes.append(guided_change(change, masks[area], index))
    write_report(directory / 'guided-review.html', Image.open(directory / 'original.png'),
                 result=Image.open(directory / 'refined.png'), masks=masks, changes=changes,
                 outcome='technique_demo_requires_review')
    (directory / 'guidance.json').write_text(json.dumps(changes, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    render(parser.parse_args().directory)
