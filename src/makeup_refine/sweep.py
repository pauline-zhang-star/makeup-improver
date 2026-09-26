"""Offline Phase 1 calibration using one saved candidate; never calls a provider."""
import argparse
from dataclasses import asdict
from html import escape
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from .imaging import composite, to_srgb
from .models import SpikeError
from .quality import VisibilityThresholds, region_metrics, validate_candidate_geometry
from .landmarks import validate_face
from .report import data_url, write_report


def local_file(root, name):
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("Candidate manifest must use local filenames")
    return root / name


def sweep(trial: Path, output: Path, strengths=(0.3, 0.5, 0.7), detector=None):
    if not strengths or any(not np.isfinite(s) or not 0 < s <= 1 for s in strengths):
        raise ValueError("Strengths must be greater than 0 and at most 1")
    if len(set(strengths)) != len(strengths):
        raise ValueError("Use distinct strength values")
    manifest_path = trial / 'candidate.json'
    if not manifest_path.is_file():
        raise SpikeError('CANDIDATE_NOT_FOUND', 'This trial has no saved raw candidate. A previously blended result cannot substitute for it.')
    manifest = json.loads(manifest_path.read_text())
    if manifest['status'] != 'geometry_checked_candidate':
        raise ValueError('Candidate has not passed geometry checks')
    with Image.open(local_file(trial, manifest['original'])) as source:
        original = to_srgb(source)
    with Image.open(local_file(trial, manifest['candidate'])) as source:
        candidate = to_srgb(source)
    with Image.open(local_file(trial, manifest['mask'])) as source:
        if source.mode != 'L':
            raise ValueError('Invalid union mask')
        mask = source.copy()
    regions = []
    for region in manifest['regions']:
        with Image.open(local_file(trial, region['mask'])) as source:
            if source.mode != 'L' or source.size != original.size:
                raise ValueError('Invalid region mask')
            regions.append(source.copy())
    if not regions or not np.array_equal(np.maximum.reduce([np.asarray(m) for m in regions]), np.asarray(mask)):
        raise ValueError('Union mask must match the per-region masks')
    # Compute all variants before writing. No partial output on incompatible images.
    variants = [(s, composite(original, candidate, mask, s)) for s in strengths]
    points = validate_face(detector.detect(original)) if detector else None
    if detector:
        validate_candidate_geometry(candidate, original, points, detector)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []
    cards = [f'<figure><img src="{data_url(original)}" alt="Original"><figcaption>Original</figcaption></figure>']
    for index, (strength, result) in enumerate(variants):
        metrics = region_metrics(original, result, regions)
        geometry = {'status': 'not_checked'}
        if detector:
            try:
                deviation = validate_candidate_geometry(result, original, points, detector)
                geometry = {'status': 'passed', 'maxLandmarkDeviation': deviation}
            except SpikeError:
                geometry = {'status': 'failed'}
        filename = f'blend-{index + 1}.png'
        result.save(output / filename)
        write_report(output / f'review-{index + 1}.html', original, masks={'combined': mask}, result=result,
                     changes=manifest['plan']['changes'])
        outside_equal = bool(np.array_equal(np.asarray(original)[np.asarray(mask) == 0],
                                          np.asarray(result)[np.asarray(mask) == 0]))
        rows.append({'blendStrength': strength, 'image': filename, 'regions': metrics,
                     'outsideMaskIdentical': outside_equal,
                     'geometry': geometry,
                     'passesNumericBand': all(r['passesNumericBand'] for r in metrics),
                     'humanReview': {'visible': None, 'natural': None, 'samePerson': None,
                                     'reproducibleTechnique': None, 'accepted': None}})
        label = 'Within numerical band' if rows[-1]['passesNumericBand'] else 'Outside numerical band'
        label += ' · Geometry: ' + geometry['status']
        cards.append(f'<figure><img src="{data_url(result)}" alt="Blend strength {strength}">'
                     f'<figcaption>Strength {strength:g} · {escape(label)}<br>'
                     f'<a href="review-{index + 1}.html">Compare and inspect close-up</a></figcaption></figure>')
    report = {'status': 'calibration_only', 'networkUsed': False, 'newGenerations': 0,
              'candidate': manifest['candidate'], 'blendSpace': 'encoded_sRGB',
              'thresholds': asdict(VisibilityThresholds()), 'thresholdsEmpiricallyCalibrated': False,
              'geometry': 'checked_before_and_after_blending' if detector else 'not_checked_in_sweep',
              'variants': rows, 'selectedStrength': None}
    (output / 'calibration.json').write_text(json.dumps(report, indent=2))
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Blend strength calibration</title><style>body{margin:32px;background:#f8f5f2;color:#322a2d;font:16px/1.5 system-ui}main{max-width:1600px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}figure{margin:0}img{width:100%;display:block;border-radius:10px}figcaption{padding:12px 0}p{max-width:850px}a{color:#8c3c62}</style><main><h1>One candidate. Controlled strength.</h1>
<p>Offline calibration previews, all derived from the same generated image. No additional AI calls. The numerical band is an uncalibrated guard, not proof that an edit is visible, natural, or identity-preserving.</p>
<p>Inspect full face and close-ups. Record your judgments in calibration.json. No strength is automatically chosen.</p><div class="grid">'''
    (output / 'index.html').write_text(html + ''.join(cards) + '</div></main>')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare local blend strengths from one saved candidate; no API calls')
    parser.add_argument('trial', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--strengths', type=float, nargs='+', default=[0.3, 0.5, 0.7])
    parser.add_argument('--landmark-model', type=Path, help='Run local geometry checks on every blend')
    args = parser.parse_args(argv)
    detector = None
    try:
        if args.landmark_model:
            from .landmarks import MediaPipeLandmarks
            detector = MediaPipeLandmarks(str(args.landmark_model))
        sweep(args.trial, args.output, args.strengths, detector=detector)
        print(json.dumps({'status': 'calibration_only', 'review': str(args.output / 'index.html'), 'newGenerations': 0}))
        return 0
    except (SpikeError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'status': 'failed', 'message': 'Check the saved candidate manifest, image dimensions, strengths and new output directory.'}), file=sys.stderr)
        return 1
    finally:
        if detector:
            detector.close()


if __name__ == '__main__':
    sys.exit(main())
