"""Request-scoped landmark reuse. Cache keys track pixels, never object identity."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256


class CachedLandmarks:
    def __init__(self, detector, capacity=8):
        if capacity < 1:
            raise ValueError('Landmark cache capacity must be positive.')
        self.detector = detector
        self.capacity = capacity
        self.cache = OrderedDict()
        self.hits = self.misses = 0

    def detect(self, image):
        key = (image.mode, image.size, sha256(image.tobytes()).digest())
        if key in self.cache:
            self.hits += 1
            self.cache.move_to_end(key)
            return deepcopy(self.cache[key])
        self.misses += 1
        points = self.detector.detect(image)
        self.cache[key] = deepcopy(points)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
        return points

    def close(self):
        self.cache.clear()
        self.detector.close()
