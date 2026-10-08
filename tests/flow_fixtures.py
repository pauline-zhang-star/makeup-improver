"""Shared deterministic photo and landmarks for current-flow tests."""
import numpy as np
import pytest
from PIL import Image
from makeup_refine.landmarks import LIPS

@pytest.fixture
def image():
    return Image.fromarray(np.random.default_rng(10).integers(60, 190, (512, 512, 3), dtype=np.uint8))


class Detector:
    def detect(self, image):
        p = [(0.5, 0.5)] * 478
        p[1], p[2] = (.2, .2), (.8, .8)
        p[33], p[263] = (.35, .4), (.65, .4)
        for i, angle in zip(LIPS, np.linspace(0, 2 * np.pi, len(LIPS), endpoint=False)):
            p[i] = (.5 + .12 * np.cos(angle), .65 + .04 * np.sin(angle))
        return [p]


