import argparse
import json
from pathlib import Path
import sys
from .imaging import load_image, to_srgb
from .models import Plan, SpikeError
from .pipeline import Pipeline
from .report import write_report
from .config import get_api_key


def main():
    parser = argparse.ArgumentParser(description="Local makeup-refinement technical spike")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New private output directory")
    parser.add_argument("--landmark-model", type=Path, required=True)
    parser.add_argument("--vision-model", required=True)
    parser.add_argument("--edit-model", required=True)
    parser.add_argument("--plan-file", type=Path,
                        help="Reuse a validated saved plan for a controlled experiment; skips paid analysis")
    parser.add_argument("--max-edit-attempts", type=int, choices=(1, 2), default=2)
    parser.add_argument("--blend-strength", type=float, default=0.5,
                        help="Experimental local blend coefficient, greater than 0 and at most 1")
    parser.add_argument("--provider-review", type=Path, required=True,
                        help="JSON record of the provider's face-editing policy and mask capability review")
    args = parser.parse_args()
    provider = detector = None
    try:
        if not 0 < args.blend_strength <= 1:
            raise SpikeError("CONFIGURATION_ERROR", "--blend-strength must be greater than 0 and at most 1.")
        review = json.loads(args.provider_review.read_text())
        if not (isinstance(review, dict) and review.get("provider") == "openai" and review.get("face_editing_permitted") is True
                and review.get("mask_editing_supported") is True and review.get("evidence")
                and review.get("reviewed_at") and review.get("edit_model") == args.edit_model):
            raise SpikeError("PROVIDER_REVIEW_REQUIRED", "Complete the provider review record before submitting photos.")
        key = get_api_key()
        if args.output.exists():
            raise SpikeError("OUTPUT_EXISTS", "Choose a new output directory to avoid mixing sessions.")
        original = load_image(args.image)
        saved_plan = Plan.model_validate_json(args.plan_file.read_text()) if args.plan_file else None
        class SavedPlanVision:
            def analyze_and_plan(self, image):
                return saved_plan
        from .landmarks import MediaPipeLandmarks
        from .providers import OpenAIProvider
        detector = MediaPipeLandmarks(str(args.landmark_model))
        provider = OpenAIProvider(key, args.vision_model, args.edit_model)
        args.output.mkdir(parents=True, mode=0o700)
        original.save(args.output / "original.png")

        def save_candidate(candidate, union, masks, plan, attempt):
            filename = f"candidate-{attempt + 1}.png"
            to_srgb(candidate).save(args.output / filename)
            union.save(args.output / "mask.png")
            regions = []
            for change, region in zip(plan.changes, masks):
                name = f"mask-{change.area}.png"
                region.save(args.output / name)
                regions.append({"area": change.area, "mask": name})
            manifest = {"status": "geometry_checked_candidate", "original": "original.png",
                        "candidate": filename, "mask": "mask.png", "regions": regions,
                        "plan": plan.model_dump(), "attempt": attempt + 1,
                        "blendSpace": "encoded_sRGB", "humanAccepted": False}
            (args.output / "candidate.json").write_text(json.dumps(manifest, indent=2))

        try:
            result, mask, report = Pipeline(SavedPlanVision() if saved_plan else provider, provider, detector,
                                            max_edit_attempts=args.max_edit_attempts,
                                            blend_strength=args.blend_strength,
                                            on_candidate=save_candidate).run(original)
        except SpikeError as exc:
            report = {"status": "failed", "errorCode": exc.code, "message": exc.message}
            (args.output / "result.json").write_text(json.dumps(report, indent=2))
            raise
        original.save(args.output / "original.png")
        if result is not None:
            result.save(args.output / "refined.png")
            mask.save(args.output / "mask.png")
            write_report(args.output / "review.html", original, masks={"combined": mask},
                         result=result, changes=report["changes"])
        else:
            write_report(args.output / "review.html", original, masks={}, outcome="completed_no_changes")
        report.update(originalImage="original.png", refinedImage="refined.png" if result else None,
                      analysisReused=bool(saved_plan),
                      provider="openai", visionModel=args.vision_model, editModel=args.edit_model,
                      retention="Local files remain until you delete this directory.")
        (args.output / "result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"status": report["status"], "output": str(args.output)}))
        return 0
    except SpikeError as exc:
        print(json.dumps({"status": "failed", "errorCode": exc.code, "message": exc.message}), file=sys.stderr)
        return 1
    except (OSError, ValueError, ImportError, RuntimeError):
        print(json.dumps({"status": "failed", "errorCode": "CONFIGURATION_ERROR",
                          "message": "Check dependencies, file paths, model asset, and review JSON."}), file=sys.stderr)
        return 1
    finally:
        if provider:
            provider.close()
        if detector:
            detector.close()


if __name__ == "__main__":
    sys.exit(main())
