"""Optional OpenAI adapter. Core pipeline depends only on Protocols."""
import base64
from io import BytesIO
import json
import time
import os
import httpx
from PIL import Image
from pydantic import ValidationError
from .models import SpikeError
from .api_usage import UsageLedger
from .imaging import to_srgb, prepare_edit_canvas, edit_region_box
from .look_models import MakeupStyle, LookComparison
from .look_prompts import enhancement_prompt, comparison_prompt
from .model_planning import LookDesign, planning_prompt, planning_response_format, validate_design


def png(image):
    output = BytesIO()
    image.save(output, format="PNG", compress_level=3)
    return output.getvalue()


class OpenAIProvider:
    def __init__(self, api_key: str, vision_model: str, edit_model: str):
        self.vision_model, self.edit_model = vision_model, edit_model
        self.review_model = os.environ.get("MAKEUP_REVIEW_MODEL", vision_model)
        self.usage_ledger = UsageLedger()
        self.trial_trace = None
        self.fast_ai = os.environ.get("MAKEUP_FAST_AI") == "1"
        self.edit_quality = os.environ.get("MAKEUP_EDIT_QUALITY", "low").lower()
        if self.edit_quality not in ("low", "medium", "high"):
            raise SpikeError("CONFIGURATION_ERROR", "Invalid image generation quality.")
        # Preserve PNG by default until a paired generation trial validates JPEG.
        self.edit_canvas_mode = os.environ.get("MAKEUP_EDIT_CANVAS_MODE", "full").lower()
        if self.edit_canvas_mode not in ("full", "region"):
            raise SpikeError("CONFIGURATION_ERROR", "Invalid image canvas mode.")
        self.edit_output_format = os.environ.get("MAKEUP_EDIT_OUTPUT_FORMAT", "png").lower()
        if self.edit_output_format not in ("png", "jpeg", "webp"):
            raise SpikeError("CONFIGURATION_ERROR", "Invalid image output format.")
        # No transport-level retry: the pipeline owns the single edit retry.
        self.client = httpx.Client(base_url="https://api.openai.com/v1/",
                                  headers={"Authorization": f"Bearer {api_key}"}, timeout=90)

    def _post(self, stage, endpoint, **kwargs):
        model = (kwargs.get('json') or kwargs.get('data'))['model']
        if endpoint == 'chat/completions' and model.startswith('gpt-5.6'):
            # The configured visual task has no need for a hidden reasoning pass.
            kwargs['json'].setdefault('reasoning_effort', 'none')
        record = self.usage_ledger.begin(stage, endpoint, model)
        if endpoint == 'images/edits':
            data = kwargs.get('data') or {}
            record['imageSettings'] = {key: data[key] for key in
                ('size', 'quality', 'output_format', 'output_compression') if key in data}
            record['inputImageBytes'] = sum(len(item[1]) for item in
                (kwargs.get('files') or {}).values() if isinstance(item[1], bytes))
        if self.trial_trace:
            self.trial_trace.begin(record, kwargs)
        started = time.perf_counter()
        try:
            response = self.client.post(endpoint, **kwargs)
        except httpx.HTTPError:
            self.usage_ledger.finish(record, duration_ms=(time.perf_counter() - started) * 1000)
            if self.trial_trace:
                self.trial_trace.finish(record)
            raise
        # Record before parsing/validation: a rejected result still consumed tokens.
        if endpoint == 'images/edits':
            record['responseBytes'] = len(response.content)
        self.usage_ledger.finish(record, response,
                                 duration_ms=(time.perf_counter() - started) * 1000)
        if self.trial_trace:
            self.trial_trace.finish(record, response)
        return response

    def close(self):
        self.client.close()

    def plan_techniques(self, original, style, points):
        """Model designs the look; local validation bounds the proposed actions."""
        self.last_technique_analysis = None
        style = MakeupStyle(style or MakeupStyle.AUTO)
        prompt = planning_prompt(style)
        response_format = planning_response_format()
        if self.fast_ai:
            from .fast_ai import planning_contract
            prompt, response_format = planning_contract(style)
        phase = 'request'
        response = None
        choice = {}
        try:
            response = self._post('planning', 'chat/completions', json={
                'model': self.vision_model, 'response_format': response_format,
                'messages': [{'role': 'system', 'content': prompt},
                             {'role': 'user', 'content': [{'type': 'text', 'text': 'Design a cohesive look from this original selfie and its existing makeup.'},
                                                      {'type': 'image_url', 'image_url': {
                                                          'url': 'data:image/png;base64,' + base64.b64encode(png(original)).decode(),
                                                          'detail': 'high'}}]}]})
            response.raise_for_status()
            phase = 'response_shape'
            choice = response.json()['choices'][0]
            content = choice['message']['content']
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Planning response has no JSON content.')
            phase = 'model_schema'
            if self.fast_ai:
                from .fast_ai import planning_decode
                design = planning_decode(content)
            else:
                design = LookDesign.model_validate_json(content)
            self.last_technique_analysis = {'analysis_schema': 'model_visual_reasoning_v1',
                                            **design.model_dump()}
            phase = 'local_validation'
            return validate_design(design)
        except httpx.HTTPStatusError as exc:
            raise SpikeError('ANALYSIS_FAILED', 'Could not verify a technique plan from the photo.',
                             {'planningFailure': {'phase': 'http_status',
                                                  'httpStatus': exc.response.status_code,
                                                  'requestId': exc.response.headers.get('x-request-id')}}) from exc
        except ValidationError as exc:
            # Report locations/types only; never echo the model's text or the photo.
            issues = [{'field': '.'.join(map(str, item['loc'])), 'type': item['type']}
                      for item in exc.errors(include_input=False, include_context=False,
                                             include_url=False)[:8]]
            raise SpikeError('ANALYSIS_FAILED', 'Could not verify a technique plan from the photo.',
                             {'planningFailure': {'phase': phase, 'issues': issues,
                                                  'finishReason': choice.get('finish_reason')}}) from exc
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            finish_reason = None
            if response is not None and response.is_success:
                try:
                    finish_reason = response.json()['choices'][0].get('finish_reason')
                except (ValueError, KeyError, IndexError, TypeError):
                    pass
            raise SpikeError('ANALYSIS_FAILED', 'Could not verify a technique plan from the photo.',
                             {'planningFailure': {'phase': phase, 'errorType': type(exc).__name__,
                                                  'finishReason': finish_reason}}) from exc

    def enhance(self, original, style=MakeupStyle.AUTO, mask=None, plan=None, correction=None):
        """One direct edit, locally limited to face-anchored cosmetic regions."""
        style = MakeupStyle(style or MakeupStyle.AUTO)
        if mask is None or mask.mode != 'L' or mask.size != original.size:
            raise SpikeError('QUALITY_CHECK_FAILED', 'A valid makeup mask is required.')
        region_box = (0, 0, original.width, original.height)
        if self.edit_model.startswith('gpt-image-2'):
            if self.edit_canvas_mode == 'region':
                region_box = edit_region_box(original, mask)
            source = original.crop(region_box) if region_box != (0, 0, original.width, original.height) else original
            source_mask = mask.crop(region_box) if source is not original else mask
            canvas, canvas_mask, crop = prepare_edit_canvas(source, source_mask)
        else:
            canvas, canvas_mask, crop = original, mask, (0, 0, original.width, original.height)
        output_size = canvas.size
        size = (f"{output_size[0]}x{output_size[1]}"
                if self.edit_model.startswith("gpt-image-2") else "auto")
        provider_mask = Image.new('RGBA', canvas.size, (0, 0, 0, 255))
        provider_mask.putalpha(canvas_mask.point(lambda value: 0 if value else 255))
        prompt = enhancement_prompt(style, plan)
        if correction:
            prompt += (' Previous attempt failed this check: ' + correction +
                       ' Start again from this ORIGINAL image and the same technique plan. '
                       'Keep the camera framing and face position fixed. Preserve exposure, flash highlights, '
                       'eye position and size, iris size, face proportions and mouth shape exactly. '
                       'A selected eyelid or eyeliner technique may keep each eye opening the same or make it slightly larger, '
                       'but never smaller; do not lower the upper lid, narrow the aperture, or anatomically enlarge or reshape the eyes. '
                       'Keep eyeliner on the upper-lid skin just outside the upper lash roots with a small visible skin gap; '
                       'keep eyeshadow above and outside the visible eye opening, blending upward and outward. '
                       'Preserve the original hairline and hair silhouette, volume, width, part and flyaways exactly; '
                       'do not widen or regenerate the hair. '
                       'Keep every under-eye wrinkle, crease, pore and age cue visible; only reduce uneven tone lightly, '
                       'never blur or erase skin texture. Preserve natural skin texture and all regions outside the selected '
                       'techniques and permitted facial base makeup. '
                       'Return finished makeup; no later fading is applied.')
        data = {"model": self.edit_model, "prompt": prompt,
                "n": "1", "size": size, "quality": self.edit_quality}
        if self.edit_model.startswith("gpt-image"):
            data["output_format"] = self.edit_output_format
            if self.edit_output_format in ("jpeg", "webp"):
                data["output_compression"] = "100"
        try:
            response = self._post("generation", "images/edits", data=data,
                files={"image": ("selfie.png", png(canvas), "image/png"),
                       "mask": ("mask.png", png(provider_mask), "image/png")})
            response.raise_for_status()
            raw = base64.b64decode(response.json()["data"][0]["b64_json"], validate=True)
            with Image.open(BytesIO(raw)) as enhanced:
                if enhanced.size != output_size:
                    raise SpikeError('QUALITY_CHECK_FAILED', 'The provider changed the requested canvas dimensions.')
                converted = to_srgb(enhanced).crop(crop)
                region_size = (region_box[2] - region_box[0], region_box[3] - region_box[1])
                if converted.size != region_size:
                    converted = converted.resize(region_size, Image.Resampling.LANCZOS)
                if region_box != (0, 0, original.width, original.height):
                    restored = original.copy()
                    restored.paste(converted, region_box[:2])
                    converted = restored
                return converted
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            raise SpikeError("IMAGE_EDIT_FAILED", "Could not generate the enhanced photograph.") from exc

    def explain_changes(self, original, enhanced, evidence=None):
        """Explain the actual image pair, without knowledge of the requested style."""
        content = []
        for label, image in (("ORIGINAL", original), ("ENHANCED", enhanced)):
            content.extend([{"type": "text", "text": label},
                            {"type": "image_url", "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(png(image)).decode(),
                                "detail": "high"}}])
        if evidence:
            content.append({'type': 'text', 'text':
                'LOCAL PIXEL EVIDENCE (diagnostic only, not proof of makeup): ' + json.dumps(evidence)})
            seen = set()
            if self.fast_ai:
                from .fast_ai import detail_boards
                for board in detail_boards(original, enhanced, evidence):
                    content.extend([{'type': 'text', 'text': 'Matched detail board: ORIGINAL left, ENHANCED right.'},
                                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' +
                                     base64.b64encode(png(board)).decode(), 'detail': 'high'}}])
            for region in ([] if self.fast_ai else evidence['regions']):
                for box in region['cropBoxes']:
                    key = tuple(box)
                    if key in seen:
                        continue
                    seen.add(key)
                    areas = sorted({r['area'] for r in evidence['regions'] if box in r['cropBoxes']})
                    for label, source in (('ORIGINAL', original), ('ENHANCED', enhanced)):
                        crop = source.crop(tuple(box))
                        # Identical crop coordinates and scale preserve spatial comparison.
                        scale = min(3., 512 / max(crop.size))
                        crop = crop.resize((max(1, round(crop.width * scale)),
                                            max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
                        content.extend([{'type': 'text', 'text': f"{', '.join(areas)} {box} {label} detail"},
                                        {'type': 'image_url', 'image_url': {
                                            'url': 'data:image/png;base64,' + base64.b64encode(png(crop)).decode(),
                                            'detail': 'high'}}])
        prompt, response_format = comparison_prompt(), {"type": "json_object"}
        if self.fast_ai:
            from .fast_ai import comparison_contract
            prompt, response_format = comparison_contract()
        try:
            response = self._post("comparison", "chat/completions", json={
                "model": self.review_model, "response_format": response_format,
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": content}]})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if self.fast_ai:
                from .fast_ai import comparison_decode
                return comparison_decode(content)
            return LookComparison.model_validate_json(content)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise SpikeError("EXPLANATION_FAILED", "The image is ready, but its makeup steps could not be verified.") from exc
