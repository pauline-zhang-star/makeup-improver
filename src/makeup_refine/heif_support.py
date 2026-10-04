"""Register HEIC/HEIF decoding for the shared Pillow image pipeline."""

from pillow_heif import register_heif_opener

register_heif_opener()
