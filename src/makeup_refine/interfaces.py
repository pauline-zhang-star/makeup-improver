from typing import Protocol
from PIL import Image
from .models import Plan
from .look_models import MakeupStyle, LookComparison
from .technique_catalog import TechniquePlan


class VisionProvider(Protocol):
    def analyze_and_plan(self, image: Image.Image) -> Plan: ...


class ImageEditProvider(Protocol):
    def edit(self, image: Image.Image, mask: Image.Image, plan: Plan, attempt: int) -> Image.Image: ...


class LandmarkProvider(Protocol):
    def detect(self, image: Image.Image) -> list[list[tuple[float, float]]]: ...


class LookEditor(Protocol):
    def plan_techniques(self, original: Image.Image, style: MakeupStyle,
                        points: list[tuple[float, float]]) -> TechniquePlan: ...

    def enhance(self, original: Image.Image, style: MakeupStyle,
                mask: Image.Image, plan: TechniquePlan, correction=None) -> Image.Image: ...


class LookExplainer(Protocol):
    def explain_changes(self, original: Image.Image, enhanced: Image.Image, evidence=None) -> LookComparison: ...
