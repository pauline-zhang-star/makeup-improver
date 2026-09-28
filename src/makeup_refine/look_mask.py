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


def direct_edit_mask(size, points, style, selected, include_complexion=True):
    """Selected techniques plus optional facial base makeup, without compositing.

    This landmark approximation is not semantic skin segmentation. Glasses and
    hair crossing the face still need the paired-image preservation assessment.
    Keep brow pigment protected unless a selected technique allows editing it.
    """
    base = complexion_mask(size, points) if include_complexion else Image.new('L', size, 0)
    xy = np.asarray(points, dtype=float) * size
    draw = ImageDraw.Draw(base)
    for brow in BROWS:
        draw.polygon([tuple(xy[i]) for i in brow], fill=0)
    selected_mask = technique_mask(size, points, style, selected)
    return Image.fromarray(np.maximum(np.asarray(base), np.asarray(selected_mask)))


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


def lip_center_highlight_mask(size, points):
    """A narrow lower-lip center, leaving the perimeter and corners unchanged."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    mouth_width = float(np.linalg.norm(xy[291] - xy[61]))
    center = (xy[14] + xy[17]) / 2
    lower_lip_depth = max(2., float(np.linalg.norm(xy[17] - xy[14])))
    local = Image.new('L', size, 0)
    draw = ImageDraw.Draw(local)
    rx = mouth_width * .19
    ry = lower_lip_depth * .42
    draw.ellipse((center[0]-rx, center[1]-ry,
                  center[0]+rx, center[1]+ry), fill=255)
    local = local.filter(ImageFilter.GaussianBlur(max(1., mouth_width * .015)))
    pigment = np.asarray(lip_pigment_mask(size, points))
    return Image.fromarray(np.minimum(np.asarray(local), pigment))


def outer_wing_mask(size, points):
    """Short feathered strokes beyond the outer eye corners only."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for index, direction in ((33, -1), (263, 1)):
        x, y = xy[index]
        draw.line((x, y, x + direction * eye_span * .12,
                   y - eye_span * .035), fill=255,
                  width=max(3, round(eye_span * .055)))
    return mask.filter(ImageFilter.GaussianBlur(max(1., eye_span * .008)))


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
        dx, dy = eye_span * .14 * expansion, eye_span * .055 * expansion
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
    cheek_radius_y = eye_span * .11 * expansion
    eye_y = (xy[33, 1] + xy[263, 1]) / 2
    mouth_y = xy[0, 1]
    cheek_y = eye_y + .42 * (mouth_y - eye_y)
    cheeks = Image.new('L', size, 0)
    cheek_draw = ImageDraw.Draw(cheeks)
    for eye_index in (33, 263):
        cheek_x = xy[eye_index, 0] + (-.04 * eye_span if eye_index == 33 else .04 * eye_span)
        cheek_draw.ellipse((cheek_x-cheek_radius_x, cheek_y-cheek_radius_y,
                            cheek_x+cheek_radius_x, cheek_y+cheek_radius_y), fill=255)

    # The provider may alter skin tone inside the eye region even when asked not
    # to. A broad inward feather prevents a visible oval seam in the final image.
    soft = mask.filter(ImageFilter.GaussianBlur(max(2, eye_span * .07)))
    eyes_and_lips = np.minimum(np.asarray(mask), np.asarray(soft))
    diffuse_cheeks = np.asarray(cheeks.filter(ImageFilter.GaussianBlur(max(3, eye_span * .06 * expansion))),
                                dtype=float)
    eye_strength = np.where(eyes_and_lips > 0, .9 * eyes_and_lips, 0)
    # Lip strength is handled separately by pigment-only compositing.
    eye_strength[np.asarray(lip) > 0] = np.asarray(lip)[np.asarray(lip) > 0]
    combined = np.maximum.reduce((eye_strength.astype(np.uint8),
                                  np.rint(diffuse_cheeks).astype(np.uint8),
                                  np.rint(diffuse_nose * .55).astype(np.uint8)))
    opening = Image.new('L', size, 0)
    ImageDraw.Draw(opening).polygon([tuple(xy[i]) for i in INNER_LIPS], fill=255)
    combined[np.asarray(opening) > 0] = 0
    return Image.fromarray(combined)


def technique_mask(size, points, style, selected):
    """Restrict the existing cosmetic mask to the preselected technique regions."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    ied = float(np.linalg.norm((xy[33] + xy[133]) / 2 - (xy[263] + xy[362]) / 2))
    allowed = np.zeros((h, w), dtype=np.uint8)
    for item in selected:
        region = item['region']
        technique_id = item['technique_id']
        shape = Image.new('L', size, 0)
        draw = ImageDraw.Draw(shape)
        if region == 'brows':
            margin = max(1, round(ied * .02))
            for brow in BROWS:
                coords = xy[list(brow)]
                draw.polygon([tuple(point) for point in coords], fill=255)
            shape = shape.filter(ImageFilter.MaxFilter(2 * margin + 1))
            if technique_id == 'brow_05':
                tail_draw = ImageDraw.Draw(shape)
                face_center_x = xy[1, 0]
                for brow in BROWS:
                    coords = xy[list(brow)]
                    outer = coords[np.argmin(coords[:, 0]) if coords[:, 0].mean() < face_center_x
                                   else np.argmax(coords[:, 0])]
                    direction = -1 if outer[0] < face_center_x else 1
                    # The only permitted excursion outside the brow is 0.06 IED.
                    tail_draw.line((outer[0], outer[1], outer[0] + direction * ied * .06, outer[1]),
                                   fill=255, width=max(1, round(ied * .01)))
        elif region in ('eyeliner', 'eyeshadow'):
            expansion = _style_expansion(style)
            for upper, lower in zip(UPPER_EYES, LOWER_EYES):
                coords = xy[list(set(upper) | set(lower))]
                x0, y0 = coords.min(axis=0)
                x1, y1 = coords.max(axis=0)
                dx = eye_span * (.14 if technique_id == 'eyeliner_05' else .08) * expansion
                dy = eye_span * (.025 if region == 'eyeliner' else .055) * expansion
                draw.ellipse((x0-dx, y0-dy, x1+dx, y1+dy), fill=255)
                draw.polygon([tuple(xy[i]) for i in upper] +
                             [tuple(xy[i]) for i in reversed(lower)], fill=0)
            if technique_id == 'eyeliner_05':
                for outer_index, direction in ((33, -1), (263, 1)):
                    x, y = xy[outer_index]
                    draw.line((x, y, x + direction * eye_span * .11,
                               y - eye_span * .035), fill=255,
                              width=max(2, round(eye_span * .028)))
        elif region == 'lips':
            shape = (lip_center_highlight_mask(size, points) if technique_id == 'lips_02'
                     else lip_mask(size, points, style))
        elif region == 'blush':
            eye_y = (xy[33, 1] + xy[263, 1]) / 2
            cheek_y = eye_y + .42 * (xy[0, 1] - eye_y)
            for index in (33, 263):
                x = xy[index, 0] + (-.04 * eye_span if index == 33 else .04 * eye_span)
                draw.ellipse((x-eye_span*.18, cheek_y-eye_span*.10,
                              x+eye_span*.18, cheek_y+eye_span*.10), fill=255)
        elif region == 'nose_contour':
            if technique_id == 'nose_02':
                draw.line([tuple(xy[i]) for i in (168, 6, 197, 195, 5)],
                          fill=255, width=max(3, round(eye_span * .10)))
            elif technique_id == 'nose_01':
                for index in (129, 358):
                    x, y = xy[index]
                    r = eye_span * .05
                    draw.ellipse((x-r, y-r, x+r, y+r), fill=255)
        elif region == 'foundation':
            if technique_id == 'foundation_01':
                for index in (33, 263):
                    x, y = xy[index]
                    draw.ellipse((x-eye_span*.18, y-eye_span*.02,
                                  x+eye_span*.18, y+eye_span*.32), fill=255)
            elif technique_id == 'foundation_02':
                for index in (33, 263):
                    x, y = xy[index]
                    direction = -1 if index == 33 else 1
                    x += direction * eye_span * .10
                    y += eye_span * .18
                    draw.ellipse((x-eye_span*.09, y-eye_span*.04,
                                  x+eye_span*.09, y+eye_span*.04), fill=255)
                draw.line([tuple(xy[i]) for i in (168, 6, 197, 195, 5)],
                          fill=255, width=max(3, round(eye_span * .04)))
        else:
            continue
        strength = item.get('intensity', 1.0)
        # The provider's cheek pigment is often faint after the final feather.
        # Restore local visibility without expanding the cheek boundary.
        if region == 'blush':
            strength = min(1., strength * 1.5)
        elif region == 'eyeshadow':
            strength = min(.8, strength * 1.7)
        allowed = np.maximum(allowed, np.rint(np.asarray(shape) * strength).astype(np.uint8))
    base = np.asarray(makeup_mask(size, points, style))
    return Image.fromarray(np.minimum(base, allowed))
