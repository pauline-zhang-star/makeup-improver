"""Local technique-planned image flow. Legacy experiments live in legacy_cli."""
import argparse
import json
import os
from pathlib import Path
import sys
import shutil
from PIL import Image
from .config import get_api_key
from .imaging import load_image, to_srgb
from .look_models import MakeupStyle
from .look_pipeline import LookPipeline, reconcile_guidance_with_plan, summarize_observed_changes
from .models import SpikeError
from .report import write_report
from .api_usage import attach_usage
from .trial_trace import TrialTrace, trace_for_report
from .photo_framing import frame_photo
from .landmark_cache import CachedLandmarks


def save_review(directory, original, enhanced, report, *, intermediate=False):
    # Fixed local names; never accept provider-supplied output paths.
    payload = {**report, 'apiTrace': trace_for_report(directory), 'originalImage': 'originalImage.png',
               'enhancedImage': 'enhancedImage.png' if enhanced is not None else None,
               'flow': 'image_first', 'humanReviewRequired': True,
               'retention': 'Local files remain until you delete this directory.'}
    # If the provider rejected dimensions before returning to the pipeline, retain
    # the real API image from the trace as a diagnostic candidate, too.
    generations = [c for c in payload['apiTrace'] if c['stage'] == 'generation']
    for number, call in enumerate(generations, 1):
        response = call.get('responsePayload') or {}
        data = response.get('data', []) if isinstance(response, dict) else []
        if data and isinstance(data[0], dict):
            ref = data[0].get('b64_json')
            if isinstance(ref, dict) and ref.get('file'):
                source = (directory / ref['file']).resolve()
                if directory.resolve() not in source.parents:
                    continue
                target = directory / f'candidate-{number}.png'
                if not target.exists():
                    try:
                        with Image.open(source) as image:
                            to_srgb(image).save(target)
                    except (OSError, ValueError):
                        continue
                if enhanced is None and number == len(generations):
                    payload['candidateImage'] = target.name
                    aligned = directory / f'aligned-candidate-{number}.png'
                    if aligned.exists():
                        payload['alignedCandidateImage'] = aligned.name
                    else:
                        payload.pop('alignedCandidateImage', None)
    temporary = directory / 'result.json.tmp'
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(directory / 'result.json')
    # The stateless Vercel response uses public_job and inline JPEGs, never the
    # private offline HTML. Avoid repeatedly encoding full-size PNGs for it.
    if (os.environ.get('MAKEUP_SKIP_REVIEW_HTML') == '1' or
            (intermediate and os.environ.get('MAKEUP_DEFER_REVIEW_HTML') == '1')):
        return
    comparison = enhanced
    if comparison is None:
        # A rejected API candidate is still useful in a test review. Prefer the
        # aligned/composited candidate that went through geometry checks, while
        # keeping enhancedImage unset so it cannot be mistaken for an accepted result.
        diagnostic_path = payload.get('alignedCandidateImage') or payload.get('candidateImage')
        if diagnostic_path:
            try:
                with Image.open(directory / diagnostic_path) as image:
                    comparison = to_srgb(image)
            except (OSError, ValueError):
                comparison = None
    write_report(directory / 'review.html', original, masks={}, result=comparison,
                 look_result=payload)


def save_working_png(image, path):
    # Public worker PNGs are temporary: use lossless fast encoding, retaining pixels.
    fast = any(os.environ.get(name) == '1' for name in
               ('MAKEUP_SKIP_REVIEW_HTML', 'MAKEUP_DEFER_REVIEW_HTML'))
    options = {'compress_level': 1} if fast else {}
    image.save(path, format='PNG', **options)


def cap_working_image(image, framing, source_size, max_edge):
    """Bound the public edit canvas while keeping the displayed pair aligned."""
    if max_edge is not None and not 512 <= max_edge <= 3840:
        raise ValueError('The maximum working edge must be between 512 and 3840 pixels.')
    if max_edge is None or max(image.size) <= max_edge:
        return image, framing
    scale = max_edge / max(image.size)
    size = tuple(max(1, round(edge * scale)) for edge in image.size)
    working = image.resize(size, Image.Resampling.LANCZOS)
    working.info.update(image.info)
    details = dict(framing) if framing else {
        'sourceSize': list(source_size),
        'cropBox': [0, 0, source_size[0], source_size[1]],
        'reasons': [],
    }
    details['method'] = 'framing_and_working_size_v1'
    details['workingSize'] = list(size)
    details['reasons'] = [*details['reasons'], 'public_generation_size_limit']
    details['sourcePreserved'] = False
    details['resized'] = True
    return working, details


def main():
    parser = argparse.ArgumentParser(description='Selfie → optional style → technique plan → enhanced image → observed makeup steps')
    parser.add_argument('image', type=Path, nargs='?')
    parser.add_argument('--output', type=Path, help='New private output directory')
    parser.add_argument('--style', choices=[s.value for s in MakeupStyle], default='Auto')
    parser.add_argument('--landmark-model', type=Path)
    parser.add_argument('--vision-model', required=True)
    parser.add_argument('--edit-model')
    parser.add_argument('--max-edit-attempts', type=int, choices=(1, 2), default=2,
                        help='At most one corrective retry from the original photo (default: 2 total calls)')
    parser.add_argument('--max-working-edge', type=int, default=None,
                        help='Optional public-service limit for the working image long edge')
    parser.add_argument('--retry-instructions', type=Path,
                        help='Compare the saved pair in this directory; never regenerate the image')
    parser.add_argument('--defer-guidance', action='store_true',
                        help='Return a locally checked preview; compare only after user likes it')
    args = parser.parse_args()
    if args.retry_instructions:
        if args.image or args.output or args.style != 'Auto':
            parser.error('--retry-instructions cannot be combined with an image, output or style.')
    elif not all((args.image, args.output, args.landmark_model, args.edit_model)):
        parser.error('Generation requires image, --output, --landmark-model and --edit-model.')
    provider = detector = None
    directory = None
    original = enhanced = None
    report = {}
    try:
        from .providers import OpenAIProvider
        if args.retry_instructions:
            directory = args.retry_instructions
            report = json.loads((directory / 'result.json').read_text())
            if (report.get('flow') != 'image_first' or report.get('enhancedImage') != 'enhancedImage.png'
                    or report.get('originalImage') != 'originalImage.png'):
                raise SpikeError('CONFIGURATION_ERROR', 'Use an image-first output containing both saved images.')
            with Image.open(directory / 'originalImage.png') as image:
                original = to_srgb(image)
            with Image.open(directory / 'enhancedImage.png') as image:
                enhanced = to_srgb(image)
            provider = OpenAIProvider(get_api_key(), args.vision_model, report.get('editModel', ''))
            attach_usage(provider, directory, report, historical=True)
            provider.trial_trace = TrialTrace(directory)
            # Saved evidence avoids detector initialization on subsequent comparisons.
            evidence = report.get('comparisonEvidence')
            if not evidence and args.landmark_model:
                from .landmarks import MediaPipeLandmarks, validate_face
                from .comparison_evidence import build_comparison_evidence
                detector = CachedLandmarks(MediaPipeLandmarks(str(args.landmark_model)))
                points = validate_face(detector.detect(original))
                evidence = build_comparison_evidence(original, enhanced, points,
                    report.get('requestedStyle', 'Auto'), report.get('techniquePlan', {}).get('selected', []))
                report['comparisonEvidence'] = evidence
            report.update(LookPipeline(provider, provider, None).explain(original, enhanced, evidence=evidence))
            if report.get('minimumDistinctRegionsTarget') or report.get('techniquePlan'):
                selected = report.get('techniquePlan', {}).get('selected', [])
                if report.get('generationMode') == 'direct_api_result':
                    planned_areas = {('eyebrows' if item['region'] == 'brows' else
                                     'complexion' if item['region'] == 'foundation' else item['region'])
                                     for item in selected}
                    allowed_areas = planned_areas | set(report.get('allowedSupplementaryAreas', []))
                    observed = {step['area'] for step in report.get('steps', [])}
                    report['filteredUnplannedObservedAreas'] = sorted(observed - allowed_areas)
                    report['steps'] = [step for step in report.get('steps', [])
                                       if step['area'] in allowed_areas]
                    report.update(summarize_observed_changes(
                        report.get('steps', []), selected,
                        report.get('allowedSupplementaryAreas', [])))
                    report['displayedStepCount'] = len(report.get('steps', []))
                else:
                    report.update(reconcile_guidance_with_plan(report, selected))
            if report['status'] != 'instructions_unavailable':
                report.pop('errorCode', None)
                if report['status'] != 'rejected':
                    report.pop('message', None)
            report.setdefault('visionModel', args.vision_model)
            report['reviewModel'] = getattr(provider, 'review_model', args.vision_model)
        else:
            if args.output.exists():
                raise SpikeError('OUTPUT_EXISTS', 'Choose a new output directory to avoid mixing sessions.')
            source = load_image(args.image)
            args.output.mkdir(parents=True, mode=0o700)
            directory = args.output
            from .landmarks import MediaPipeLandmarks
            detector = CachedLandmarks(MediaPipeLandmarks(str(args.landmark_model)))
            original, input_crop = frame_photo(source, detector)
            original, input_crop = cap_working_image(
                original, input_crop, source.size, args.max_working_edge)
            if input_crop and args.max_working_edge is None:
                save_working_png(source, directory / 'uploadedImage.png')
            save_working_png(original, directory / 'originalImage.png')
            report = {'status': 'generating', 'steps': [], 'requestedStyle': args.style,
                      'visionModel': args.vision_model, 'editModel': args.edit_model,
                      'provider': 'openai', 'guidanceDeferred': args.defer_guidance}
            if input_crop:
                report['inputCrop'] = input_crop
                if (directory / 'uploadedImage.png').is_file():
                    report['uploadedImage'] = 'uploadedImage.png'
            save_review(directory, original, None, report, intermediate=True)
            provider = OpenAIProvider(get_api_key(), args.vision_model, args.edit_model)
            report['reviewModel'] = getattr(provider, 'review_model', args.vision_model)
            attach_usage(provider, directory, report)
            provider.trial_trace = TrialTrace(directory)

            def save_enhanced(image):
                nonlocal enhanced
                enhanced = image
                save_working_png(enhanced, directory / 'enhancedImage.png')
                report.update(status='enhanced_ready')
                save_review(directory, original, enhanced, report, intermediate=True)

            def save_plan(plan):
                report['techniquePlan'] = plan.model_dump()
                report['selectedTechniques'] = [item['technique_id'] for item in plan.selected]
                if getattr(provider, 'last_technique_analysis', None) is not None:
                    report['techniqueAnalysis'] = provider.last_technique_analysis
                report['thresholdsEmpiricallyCalibrated'] = False
                report['status'] = 'plan_ready'
                save_review(directory, original, None, report, intermediate=True)

            def save_candidate(image):
                # Keep rejected provider output for human diagnosis, never as an accepted result.
                number = len(report.get('generationAttempts', [])) + 1
                save_working_png(image, directory / f'candidate-{number}.png')
                shutil.copyfile(directory / f'candidate-{number}.png', directory / 'candidateImage.png')
                report['candidateImage'] = 'candidateImage.png'
                report.pop('alignedCandidateImage', None)
                save_review(directory, original, None, report, intermediate=True)

            def save_attempt(record):
                report.setdefault('generationAttempts', []).append(record)
                report['imageEditCalls'] = len(report['generationAttempts'])
                save_review(directory, original, enhanced, report, intermediate=True)

            def save_aligned(image):
                number = len(report.get('generationAttempts', [])) + 1
                filename = f'aligned-candidate-{number}.png'
                save_working_png(image, directory / filename)
                report['alignedCandidateImage'] = filename

            enhanced, outcome = LookPipeline(provider, provider, detector, save_enhanced,
                                             save_candidate, save_plan, args.max_edit_attempts,
                                             save_attempt, save_aligned,
                                             defer_guidance=args.defer_guidance).run(original, args.style)
            report.update(outcome)
        save_review(directory, original, enhanced, report,
                    intermediate=os.environ.get('MAKEUP_DEFER_REVIEW_HTML') == '1')
        print(json.dumps({'status': report['status'], 'output': str(directory),
                          'apiCost': {k: report.get('apiUsage', {}).get(k) for k in
                                      ('totalEstimatedUSD', 'knownEstimatedUSD', 'complete')}}))
        return 1 if report['status'] == 'rejected' else 0
    except SpikeError as exc:
        failure = {'status': 'failed', 'errorCode': exc.code, 'message': exc.message, **exc.details}
        if directory is not None and original is not None and not args.retry_instructions:
            # Do not erase a usable image or successful prior session on retry failure.
            save_review(directory, original, enhanced, {**report, **failure, 'steps': []},
                        intermediate=os.environ.get('MAKEUP_DEFER_REVIEW_HTML') == '1')
        print(json.dumps(failure), file=sys.stderr)
        return 1
    except (OSError, ValueError, ImportError, RuntimeError) as exc:
        if os.environ.get('MAKEUP_DIAGNOSTICS') == '1' and (directory is None or original is None):
            # The public adapter only enables this before any provider call, so
            # startup failures can be diagnosed without logging image contents.
            print(json.dumps({'preflightErrorType': type(exc).__name__,
                              'preflightError': str(exc)[:600]}), file=sys.stderr)
        failure = {'status': 'failed', 'errorCode': 'CONFIGURATION_ERROR',
                   'message': 'Check dependencies, model names, local files and API key configuration.'}
        if directory is not None and original is not None and not args.retry_instructions:
            save_review(directory, original, enhanced, {**report, **failure, 'steps': []},
                        intermediate=os.environ.get('MAKEUP_DEFER_REVIEW_HTML') == '1')
        print(json.dumps(failure), file=sys.stderr)
        return 1
    finally:
        if provider:
            provider.close()
        if detector:
            detector.close()
        # Usage is saved by the provider even when parsing or comparison fails.
        # Refresh only its presentation; never replace a usable result with retry failure.
        if (directory is not None and original is not None and
                (directory / 'result.json').exists() and (directory / 'api-usage.json').exists()):
            saved = json.loads((directory / 'result.json').read_text())
            save_review(directory, original, enhanced, saved)


if __name__ == '__main__':
    sys.exit(main())
