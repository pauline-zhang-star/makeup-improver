"""Local technique-planned image flow. Legacy experiments live in legacy_cli."""
import argparse
import json
from pathlib import Path
import sys
from PIL import Image
from .config import get_api_key
from .imaging import load_image, to_srgb
from .look_models import MakeupStyle
from .look_pipeline import LookPipeline, reconcile_guidance_with_plan, summarize_observed_changes
from .models import SpikeError
from .report import write_report


def save_review(directory, original, enhanced, report):
    # Fixed local names; never accept provider-supplied output paths.
    payload = {**report, 'originalImage': 'originalImage.png',
               'enhancedImage': 'enhancedImage.png' if enhanced is not None else None,
               'flow': 'image_first', 'humanReviewRequired': True,
               'retention': 'Local files remain until you delete this directory.'}
    temporary = directory / 'result.json.tmp'
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(directory / 'result.json')
    write_report(directory / 'review.html', original, masks={}, result=enhanced,
                 look_result=payload)


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
    parser.add_argument('--retry-instructions', type=Path,
                        help='Compare the saved pair in this directory; never regenerate the image')
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
            # Explanation-only path has no detector and never uses the editor.
            report.update(LookPipeline(provider, provider, None).explain(original, enhanced))
            if report.get('minimumDistinctRegionsTarget') or report.get('techniquePlan'):
                selected = report.get('techniquePlan', {}).get('selected', [])
                if report.get('generationMode') == 'direct_api_result':
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
            report['visionModel'] = args.vision_model
        else:
            if args.output.exists():
                raise SpikeError('OUTPUT_EXISTS', 'Choose a new output directory to avoid mixing sessions.')
            original = load_image(args.image)
            from .landmarks import MediaPipeLandmarks
            detector = MediaPipeLandmarks(str(args.landmark_model))
            provider = OpenAIProvider(get_api_key(), args.vision_model, args.edit_model)
            args.output.mkdir(parents=True, mode=0o700)
            directory = args.output
            original.save(directory / 'originalImage.png')
            report = {'status': 'generating', 'steps': [], 'requestedStyle': args.style,
                      'visionModel': args.vision_model, 'editModel': args.edit_model,
                      'provider': 'openai'}

            def save_enhanced(image):
                nonlocal enhanced
                enhanced = image
                enhanced.save(directory / 'enhancedImage.png')
                report.update(status='enhanced_ready')
                save_review(directory, original, enhanced, report)

            def save_plan(plan):
                report['techniquePlan'] = plan.model_dump()
                report['selectedTechniques'] = [item['technique_id'] for item in plan.selected]
                if getattr(provider, 'last_technique_analysis', None) is not None:
                    report['techniqueAnalysis'] = provider.last_technique_analysis
                report['thresholdsEmpiricallyCalibrated'] = False
                report['status'] = 'plan_ready'
                save_review(directory, original, None, report)

            def save_candidate(image):
                # Keep rejected provider output for human diagnosis, never as an accepted result.
                number = len(report.get('generationAttempts', [])) + 1
                image.save(directory / f'candidate-{number}.png')
                image.save(directory / 'candidateImage.png')
                report['candidateImage'] = 'candidateImage.png'

            def save_attempt(record):
                report.setdefault('generationAttempts', []).append(record)
                report['imageEditCalls'] = len(report['generationAttempts'])
                save_review(directory, original, enhanced, report)

            def save_aligned(image):
                number = len(report.get('generationAttempts', [])) + 1
                filename = f'aligned-candidate-{number}.png'
                image.save(directory / filename)
                report['alignedCandidateImage'] = filename

            enhanced, outcome = LookPipeline(provider, provider, detector, save_enhanced,
                                             save_candidate, save_plan, args.max_edit_attempts,
                                             save_attempt, save_aligned).run(original, args.style)
            report.update(outcome)
        save_review(directory, original, enhanced, report)
        print(json.dumps({'status': report['status'], 'output': str(directory)}))
        return 1 if report['status'] == 'rejected' else 0
    except SpikeError as exc:
        failure = {'status': 'failed', 'errorCode': exc.code, 'message': exc.message, **exc.details}
        if directory is not None and original is not None and not args.retry_instructions:
            # Do not erase a usable image or successful prior session on retry failure.
            save_review(directory, original, enhanced, {**report, **failure, 'steps': []})
        print(json.dumps(failure), file=sys.stderr)
        return 1
    except (OSError, ValueError, ImportError, RuntimeError):
        print(json.dumps({'status': 'failed', 'errorCode': 'CONFIGURATION_ERROR',
                          'message': 'Check dependencies, model names, local files and API key configuration.'}), file=sys.stderr)
        return 1
    finally:
        if provider:
            provider.close()
        if detector:
            detector.close()


if __name__ == '__main__':
    sys.exit(main())
