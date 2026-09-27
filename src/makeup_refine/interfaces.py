from typing import Protocol
from PIL import Image
from .models import Plan
from .look_models import MakeupStyle, LookComparison


class VisionProvider(Protocol):
    def analyze_and_plan(self, image: Image.Image) -> Plan: ...


class ImageEditProvider(Protocol):
    def edit(self, image: Image.Image, mask: Image.Image, plan: Plan, attempt: int) -> Image.Image: ...


class LandmarkProvider(Protocol):
    def detect(self, image: Image.Image) -> list[list[tuple[float, float]]]: ...


class LookEditor(Protocol):
    def enhance(self, original: Image.Image, style: MakeupStyle,
                mask: Image.Image) -> Image.Image: ...


class LookExplainer(Protocol):
    def explain_changes(self, original: Image.Image, enhanced: Image.Image) -> LookComparison: ...
