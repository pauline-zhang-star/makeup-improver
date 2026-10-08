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

# Techniques in the same visual neighborhood can share a small transition
# margin. The margin is only enabled when at least two members are selected;
# it never turns an unselected feature into an editable region by itself.
ADJACENT_TECHNIQUE_GROUPS = (
    frozenset(('brows', 'eyeliner', 'eyeshadow', 'lashes')),
    frozenset(('nose_contour', 'foundation', 'blush')),
)


def _sparse_max_filter(mask, width):
    """Apply Pillow's exact rank filter only where the sparse mask can grow."""
    bounds = mask.getbbox()
    if bounds is None:
        return mask.copy()
    radius = width // 2
    box = (max(0, bounds[0] - radius), max(0, bounds[1] - radius),
           min(mask.width, bounds[2] + radius), min(mask.height, bounds[3] + radius))
    filtered = mask.crop(box).filter(ImageFilter.MaxFilter(width))
    result = Image.new('L', mask.size, 0)
    result.paste(filtered, box[:2])
    return result


def _style_expansion(style):
    """A selected look has more room for placement than conservative Auto."""
    return 1.0 if MakeupStyle(style or MakeupStyle.AUTO) == MakeupStyle.AUTO else 1.25


def _cheek_centers(xy, eye_span, style):
    """Landmark-anchored blush centers that reflect broad style conventions."""
    style = MakeupStyle(style or MakeupStyle.AUTO)
    eye_y = (xy[33, 1] + xy[263, 1]) / 2
    cheek_y = eye_y + .42 * (xy[0, 1] - eye_y)
    apple_styles = {MakeupStyle.NATURAL, MakeupStyle.KOREAN_SOFT, MakeupStyle.FRESH}
    face_center_x = (xy[33, 0] + xy[263, 0]) / 2
    for index in (33, 263):
        inward = (1 if face_center_x > xy[index, 0] else -1)
        shift = .12 if style in apple_styles else -.04
        yield xy[index, 0] + inward * eye_span * shift, cheek_y


def direct_edit_mask(size, points, style, selected, *, base_mask=None, eye_protected=None):
    """Exactly the selected techniques' masks, without full-face compositing.

    Full-face complexion editing is intentionally not added here. Foundation
    techniques already carry their own small, landmark-anchored masks inside
    ``technique_mask``.

    This landmark approximation is not semantic skin segmentation. Glasses and
    hair crossing the face still need the paired-image preservation assessment.
    """
    return technique_mask(size, points, style, selected,
                          base_mask=base_mask, eye_protected=eye_protected)


class DirectMaskCache:
    """Reuse the unchanged face support and technique masks within one photo run."""

    def __init__(self, size, points, style):
        self.size, self.points, self.style = size, points, style
        self.base_mask = None
        self.eye_protected = None
        self.masks = {}

    def mask_for(self, selected):
        key = tuple((item['region'], item['technique_id'], item.get('intensity', 1.0))
                    for item in selected)
        if key not in self.masks:
            if self.base_mask is None:
                self.base_mask = makeup_mask(self.size, self.points, self.style)
            if self.eye_protected is None:
                self.eye_protected = _eye_protected_mask(self.size, self.points)
            self.masks[key] = direct_edit_mask(
                self.size, self.points, self.style, selected,
                base_mask=self.base_mask, eye_protected=self.eye_protected)
        return self.masks[key]


def mouth_interior_mask(size, points):
    """Protect an open mouth without cutting a bare strip from a closed lip seam.

    A narrow landmark polygon on closed lips represents the contact crease,
    not visible oral interior. Mouth state is also checked by the image review.
    """
    xy = np.asarray(points, dtype=float) * size
    width = float(np.linalg.norm(xy[61] - xy[291]))
    gap = float(np.linalg.norm(xy[13] - xy[14]))
    opening = Image.new('L', size, 0)
    if width > 0 and gap / width > .04:
        ImageDraw.Draw(opening).polygon([tuple(xy[i]) for i in INNER_LIPS], fill=255)
    return opening


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
    lip = _sparse_max_filter(lip, width)
    draw = ImageDraw.Draw(lip)
    lip = Image.fromarray(np.where(np.asarray(mouth_interior_mask(size, points)) > 0,
                                  0, np.asarray(lip)).astype(np.uint8))
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
    lip = Image.fromarray(np.where(np.asarray(mouth_interior_mask(size, points)) > 0,
                                  0, np.asarray(lip)).astype(np.uint8))
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
    cheeks = Image.new('L', size, 0)
    cheek_draw = ImageDraw.Draw(cheeks)
    for cheek_x, cheek_y in _cheek_centers(xy, eye_span, style):
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
    combined[np.asarray(mouth_interior_mask(size, points)) > 0] = 0
    return Image.fromarray(combined)


def _eye_protected_mask(size, points):
    xy = np.asarray(points, dtype=float) * size
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    eye_protected = Image.new('L', size, 0)
    draw = ImageDraw.Draw(eye_protected)
    clearance = max(1, round(eye_span * .03))
    for upper, lower in zip(UPPER_EYES, LOWER_EYES):
        aperture = Image.new('L', size, 0)
        ImageDraw.Draw(aperture).polygon(
            [tuple(xy[i]) for i in upper] +
            [tuple(xy[i]) for i in reversed(lower)], fill=255)
        draw.bitmap((0, 0), _sparse_max_filter(aperture, 2 * clearance + 1), fill=255)
    return eye_protected


def technique_mask(size, points, style, selected, *, base_mask=None, eye_protected=None):
    """Restrict edits to selected techniques with bounded group transitions."""
    w, h = size
    xy = np.asarray(points, dtype=float) * (w, h)
    eye_span = float(np.linalg.norm(xy[263] - xy[33]))
    ied = float(np.linalg.norm((xy[33] + xy[133]) / 2 - (xy[263] + xy[362]) / 2))
    raw_by_region = {}
    selected_regions = {item['region'] for item in selected}
    if eye_protected is None:
        eye_protected = _eye_protected_mask(size, points)
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
            shape = _sparse_max_filter(shape, 2 * margin + 1)
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
            # Keep the visible aperture plus a small skin buffer opaque to the
            # provider. This gives eyeliner a little room above the lashes,
            # while preventing pigment or shadow from visually lowering the
            # upper lid and making the eye look smaller.
            for upper, lower in zip(UPPER_EYES, LOWER_EYES):
                coords = xy[list(set(upper) | set(lower))]
                x0, y0 = coords.min(axis=0)
                x1, y1 = coords.max(axis=0)
                dx = eye_span * (.14 if technique_id in ('eyeliner_02', 'eyeliner_05') else .08) * expansion
                dy = eye_span * (.025 if region == 'eyeliner' else .055) * expansion
                draw.ellipse((x0-dx, y0-dy, x1+dx, y1+dy), fill=255)
                draw.bitmap((0, 0), eye_protected, fill=0)
            if technique_id in ('eyeliner_02', 'eyeliner_05'):
                across = (xy[263] - xy[33]) / max(eye_span, 1e-6)
                upward = np.array([across[1], -across[0]])
                for outer_index, direction in ((33, -1), (263, 1)):
                    x, y = xy[outer_index]
                    start = np.array((x, y)) + upward * eye_span * .025
                    end = start + direction * across * eye_span * .11 + upward * eye_span * .035
                    draw.line((*start, *end), fill=255,
                              width=max(2, round(eye_span * .028)))
                # The wing mask is drawn after the protected eye aperture;
                # clear that protected support again so pigment stays on skin.
                draw.bitmap((0, 0), eye_protected, fill=0)
        elif region == 'lips':
            shape = (lip_center_highlight_mask(size, points) if technique_id == 'lips_02'
                     else lip_mask(size, points, style))
        elif region == 'blush':
            for x, cheek_y in _cheek_centers(xy, eye_span, style):
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
        region_mask = np.rint(np.asarray(shape) * strength).astype(np.uint8)
        raw_by_region[region] = np.maximum(raw_by_region.get(region, 0), region_mask)

    allowed = np.zeros((h, w), dtype=np.uint8)
    for region, region_mask in raw_by_region.items():
        allowed = np.maximum(allowed, region_mask)

    # Merge only selected regions that are visually adjacent. A short
    # dilation supplies a shared transition margin so the editor can blend
    # the group as one continuous area instead of painting isolated patches.
    for group in ADJACENT_TECHNIQUE_GROUPS:
        present = [region for region in group if region in selected_regions and region in raw_by_region]
        if len(present) < 2:
            continue
        group_mask = np.maximum.reduce([raw_by_region[region] for region in present])
        transition = max(1, round(eye_span * (.018 if 'eyeliner' in group else .022)))
        expanded = _sparse_max_filter(Image.fromarray(group_mask), 2 * transition + 1)
        allowed = np.maximum(allowed, np.asarray(expanded))

    # The transition margin must never open the eye aperture or its buffer.
    allowed[np.asarray(eye_protected) > 0] = 0
    base = np.asarray(base_mask if base_mask is not None else makeup_mask(size, points, style))
    return Image.fromarray(np.minimum(base, allowed))
