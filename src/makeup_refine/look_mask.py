"""Conservative, face-anchored regions for the direct makeup edit."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .landmarks import INNER_LIPS, LIPS, LOWER_EYES, UPPER_EYES
from .look_models import MakeupStyle


BROWS = (
    (70, 63, 105, 66, 107, 55, 65, 52, 53, 46),
    (336, 296, 334, 293, 300, 276, 283, 282, 295, 285),
)

FACE_OVAL = (10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361,
             288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
             150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103,
             67, 109)


def complexion_mask(size, points):
    """Inward-feathered facial skin, excluding openings and lip pigment."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([tuple(xy[i]) for i in FACE_OVAL], fill=255)
    for upper, lower in zip(UPPER_EYES, LOWER_EYES):
        draw.polygon([tuple(xy[i]) for i in upper] +
                     [tuple(xy[i]) for i in reversed(lower)], fill=0)
    draw.polygon([tuple(xy[i]) for i in INNER_LIPS], fill=0)
    pixels = np.asarray(mask).copy()
    pixels[np.asarray(lip_mask(size, points)) > 0] = 0
    mask = Image.fromarray(pixels)
    feather = mask.filter(ImageFilter.GaussianBlur(max(2, eye_span * .07)))
    return Image.fromarray(np.minimum(pixels, np.asarray(feather)))


def _style_expansion(style):
    """A selected look has more room for placement than conservative Auto."""
    return 1.0 if MakeupStyle(style or MakeupStyle.AUTO) == MakeupStyle.AUTO else 1.25


def lip_mask(size, points, style=MakeupStyle.AUTO):
    """Original lip pigment and a small outline allowance; never the mouth interior."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    expansion = _style_expansion(style)
    lip = Image.new('L', size, 0)
    draw = ImageDraw.Draw(lip)
    mouth_left, mouth_right = xy[61, 0], xy[291, 0]
    center = (mouth_left + mouth_right) / 2
    half_width = max(1, (mouth_right - mouth_left) / 2)
    outline = []
    for order, index in enumerate(LIPS):
        x, y = xy[index]
        fullness = max(0., 1 - abs(x - center) / half_width) ** 2
        if 0 < order < 10:
            y -= eye_span * .018 * expansion * fullness
        elif 10 < order < len(LIPS):
            y += eye_span * .015 * expansion * fullness
        outline.append((x, y))
    draw.polygon(outline, fill=255)
    base_width = max(3, int(eye_span * .025) // 2 * 2 + 1)
    width = base_width + (4 if expansion > 1 else 0)
    lip = lip.filter(ImageFilter.MaxFilter(width))
    draw = ImageDraw.Draw(lip)
    draw.polygon([tuple(xy[i]) for i in INNER_LIPS], fill=0)
    soft = lip.filter(ImageFilter.GaussianBlur(max(1, eye_span * .008)))
    return Image.fromarray(np.minimum(np.asarray(lip), np.asarray(soft)))


def lip_pigment_mask(size, points):
    """Original lip surface only, feathered inward to avoid a painted edge."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    lip = Image.new('L', size, 0)
    draw = ImageDraw.Draw(lip)
    draw.polygon([tuple(xy[i]) for i in LIPS], fill=255)
    draw.polygon([tuple(xy[i]) for i in INNER_LIPS], fill=0)
    soft = lip.filter(ImageFilter.GaussianBlur(max(1, eye_span * .012)))
    return Image.fromarray(np.minimum(np.asarray(lip), np.asarray(soft)))


def makeup_mask(size, points, style=MakeupStyle.AUTO):
    """Cover pigment-bearing areas, while protecting eye and mouth interiors."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    expansion = _style_expansion(style)
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for brow, upper, lower in zip(BROWS, UPPER_EYES, LOWER_EYES):
        ids = set(brow) | set(upper) | set(lower)
        region = xy[list(ids)]
        x0, y0 = region.min(axis=0)
        x1, y1 = region.max(axis=0)
        # Brow, shadow, lashes and a short wing. No wide skin or hair edits.
        dx, dy = eye_span * .08 * expansion, eye_span * .055 * expansion
        draw.ellipse((x0-dx, y0-dy, x1+dx, y1+dy), fill=255)
        aperture = [tuple(xy[i]) for i in upper] + [tuple(xy[i]) for i in reversed(lower)]
        draw.polygon(aperture, fill=0)

    lip = lip_mask(size, points, style)
    draw.bitmap((0, 0), lip, fill=255)

    # Narrow highlight on the bridge and diffuse shadow beside the alae.
    # Diffuse nose contour without fixed circular cutouts on the skin.
    nose = Image.new('L', size, 0)
    nose_draw = ImageDraw.Draw(nose)
    bridge = [tuple(xy[i]) for i in (168, 6, 197, 195, 5)]
    nose_draw.line(bridge, fill=255, width=max(3, round(eye_span * .035 * expansion)), joint='curve')
    tip = xy[4]
    tip_radius = eye_span * .032 * expansion
    nose_draw.ellipse((tip[0]-tip_radius, tip[1]-tip_radius*.7,
                       tip[0]+tip_radius, tip[1]+tip_radius*.7), fill=255)
    for index in (129, 358):
        x, y = xy[index]
        rx, ry = eye_span * .035 * expansion, eye_span * .05 * expansion
        nose_draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=255)
    diffuse_nose = np.asarray(nose.filter(ImageFilter.GaussianBlur(max(2, eye_span * .02))),
                              dtype=float)

    # Cheek color is localized instead of allowing a global complexion rewrite.
    cheek_radius_x = eye_span * .14 * expansion
    cheek_radius_y = eye_span * .10 * expansion
    eye_y = (xy[33, 1] + xy[263, 1]) / 2
    mouth_y = xy[0, 1]
    cheek_y = eye_y + .48 * (mouth_y - eye_y)
    cheeks = Image.new('L', size, 0)
    cheek_draw = ImageDraw.Draw(cheeks)
    for eye_index in (33, 263):
        cheek_x = xy[eye_index, 0] + (.13 * eye_span if eye_index == 33 else -.13 * eye_span)
        cheek_draw.ellipse((cheek_x-cheek_radius_x, cheek_y-cheek_radius_y,
                            cheek_x+cheek_radius_x, cheek_y+cheek_radius_y), fill=255)

    # The provider may alter skin tone inside the eye region even when asked not
    # to. A broad inward feather prevents a visible oval seam in the final image.
    soft = mask.filter(ImageFilter.GaussianBlur(max(2, eye_span * .07)))
    eyes_and_lips = np.minimum(np.asarray(mask), np.asarray(soft))
    diffuse_cheeks = np.asarray(cheeks.filter(ImageFilter.GaussianBlur(max(3, eye_span * .06 * expansion))),
                                dtype=float)
    eye_strength = np.where(eyes_and_lips > 0, .68 * eyes_and_lips, 0)
    # Lip strength is handled separately by pigment-only compositing.
    eye_strength[np.asarray(lip) > 0] = np.asarray(lip)[np.asarray(lip) > 0]
    combined = np.maximum.reduce((eye_strength.astype(np.uint8),
                                  np.rint(diffuse_cheeks * .55).astype(np.uint8),
                                  np.rint(diffuse_nose * .55).astype(np.uint8)))
    opening = Image.new('L', size, 0)
    ImageDraw.Draw(opening).polygon([tuple(xy[i]) for i in INNER_LIPS], fill=255)
    combined[np.asarray(opening) > 0] = 0
    return Image.fromarray(combined)
