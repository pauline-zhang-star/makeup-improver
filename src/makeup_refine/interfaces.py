from typing import Protocol
from PIL import Image
from .models import Plan


class VisionProvider(Protocol):
    def analyze_and_plan(self, image: Image.Image) -> Plan: ...


class ImageEditProvider(Protocol):
    def edit(self, image: Image.Image, mask: Image.Image, plan: Plan, attempt: int) -> Image.Image: ...


class LandmarkProvider(Protocol):
    def detect(self, image: Image.Image) -> list[list[tuple[float, float]]]: ...
