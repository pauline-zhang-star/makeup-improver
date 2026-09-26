"""Offline diagnostics: no provider construction, credential access or HTTP calls."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from .imaging import load_image
from .models import SpikeError
from .preflight import check_image, validate_masks
from .report import write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a selfie and inspect masks locally, without an API key")
    parser.add_argument("image", type=Path, nargs="?")
    parser.add_argument("--output", type=Path, help="New private output directory")
    parser.add_argument("--landmark-model", type=Path, default=Path("models/face_landmarker.task"))
    parser.add_argument("--doctor", action="store_true", help="Load the model and test a synthetic blank image")
    args = parser.parse_args(argv)
    if not args.doctor and (args.image is None or args.output is None):
        parser.error("supply an image and --output, or use --doctor")
    if args.doctor and (args.image is not None or args.output is not None):
        parser.error("--doctor does not take an image or --output")
    detector = None
    created = False
    try:
        if not args.landmark_model.is_file():
            raise SpikeError("MODEL_NOT_FOUND", "Download face_landmarker.task or specify --landmark-model.")
        if not args.doctor and args.output.exists():
            raise SpikeError("OUTPUT_EXISTS", "Choose a new output directory to avoid mixing sessions.")
        # Decode the image before loading the native runtime; fail cheaply on bad input.
        original = None if args.doctor else load_image(args.image)
        from .landmarks import MediaPipeLandmarks
        detector = MediaPipeLandmarks(str(args.landmark_model))
        if args.doctor:
            faces = detector.detect(Image.new("RGB", (512, 512), "gray"))
            if faces:
                raise SpikeError("MODEL_CHECK_FAILED", "The detector reported a face in the blank test image.")
            import mediapipe
            print(json.dumps({"status": "ok", "python": sys.version.split()[0],
                              "mediapipe": mediapipe.__version__, "modelLoaded": True,
                              "blankImageFaces": 0, "networkUsed": False}))
            return 0
        args.output.mkdir(parents=True, mode=0o700)
        created = True
        preflight = check_image(original, detector)
        validate_masks(list(preflight.masks.values()))
        original.save(args.output / "original.png")
        for area, mask in preflight.masks.items():
            mask.save(args.output / f"mask-{area}.png")
        write_report(args.output / "review.html", original, masks=preflight.masks)
        report = {"status": "preflight_passed", "networkUsed": False, "phase1Validated": False,
                  "width": original.width, "height": original.height, "faceCount": 1,
                  "landmarkCount": len(preflight.points), "faceBounds": preflight.face_bounds,
                  "maskCoverage": {area: float(np.count_nonzero(mask) / (original.width * original.height))
                                   for area, mask in preflight.masks.items()},
                  "review": "review.html", "makeupAnalysis": "not_run",
                  "retention": "Local files remain until you delete this directory."}
        (args.output / "preflight.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"status": "preflight_passed", "review": str(args.output / "review.html")}))
        return 0
    except (SpikeError, OSError, ValueError, ImportError, RuntimeError) as exc:
        error = {"status": "failed", "errorCode": exc.code if isinstance(exc, SpikeError) else "CONFIGURATION_ERROR",
                 "message": exc.message if isinstance(exc, SpikeError) else
                 "Check file paths, dependencies and model asset. Run --doctor to check the native runtime."}
        if created:
            (args.output / "preflight.json").write_text(json.dumps(error, indent=2))
        print(json.dumps(error), file=sys.stderr)
        return 1
    finally:
        if detector:
            detector.close()


if __name__ == "__main__":
    sys.exit(main())
