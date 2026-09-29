"""Reprocess a saved image/candidate pair entirely locally, with quality gates."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from PIL import Image

from .cli import save_review
from .imaging import to_srgb
from .landmarks import MediaPipeLandmarks
from .look_pipeline import LookPipeline
from .models import SpikeError


def main():
    parser = argparse.ArgumentParser(description='Automatically repair saved makeup composites; no API calls')
    parser.add_argument('source', type=Path, help='Saved run with originalImage.png, candidateImage.png and result.json')
    parser.add_argument('--output', type=Path, required=True, help='New private output directory')
    parser.add_argument('--landmark-model', type=Path, required=True)
    args = parser.parse_args()
    detector = None
    original = None
    try:
        if args.output.exists():
            raise SpikeError('OUTPUT_EXISTS', 'Choose a new output directory.')
        previous = json.loads((args.source / 'result.json').read_text())
        with Image.open(args.source / 'originalImage.png') as image:
            original = to_srgb(image)
        with Image.open(args.source / 'candidateImage.png') as image:
            candidate = to_srgb(image)
        detector = MediaPipeLandmarks(str(args.landmark_model))
        args.output.mkdir(parents=True, mode=0o700)
        original.save(args.output / 'originalImage.png')
        shutil.copyfile(args.source / 'candidateImage.png', args.output / 'candidateImage.png')
        selected = (previous.get('techniquePlan') or {}).get('selected', [])
        enhanced, report = LookPipeline(None, None, detector).recompose(
            original, candidate, previous.get('requestedStyle', 'Auto'), selected)
        enhanced.save(args.output / 'enhancedImage.png')
        report.update(candidateImage='candidateImage.png', recomposedFrom=str(args.source.resolve()),
                      techniquePlan=previous.get('techniquePlan'),
                      selectedTechniques=previous.get('selectedTechniques', []),
                      thresholdsEmpiricallyCalibrated=previous.get('thresholdsEmpiricallyCalibrated', False),
                      visionModel=previous.get('visionModel'), editModel=previous.get('editModel'))
        save_review(args.output, original, enhanced, report)
        print(json.dumps({'status': report['status'], 'review': str((args.output / 'review.html').resolve()),
                          'lipBlendQuality': report['lipBlendQuality']}, ensure_ascii=False))
        return 0
    except (SpikeError, OSError, ValueError) as exc:
        error = {'status': 'failed', 'errorCode': getattr(exc, 'code', 'LOCAL_RECOMPOSE_FAILED'),
                 'message': str(exc)}
        if original is not None and args.output.is_dir() and not (args.output / 'result.json').exists():
            save_review(args.output, original, None, error)
        print(json.dumps(error), file=sys.stderr)
        return 1
    finally:
        if detector:
            detector.close()


if __name__ == '__main__':
    raise SystemExit(main())
