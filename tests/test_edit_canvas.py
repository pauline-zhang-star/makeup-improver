import numpy as np
import pytest
from PIL import Image
from makeup_refine.imaging import edit_canvas, scaled_edit_canvas
from makeup_refine.look_mask import makeup_mask, lip_mask, complexion_mask, FACE_OVAL
from makeup_refine.look_models import MakeupStyle
from test_pipeline import Detector


@pytest.mark.parametrize('size', [(730,1024),(768,1024),(512,512),(256,1024)])
def test_padding_is_valid_and_original_pixels_are_recoverable(size):
    image = Image.fromarray(np.random.default_rng(2).integers(0,255,(size[1],size[0],3),dtype=np.uint8))
    canvas, box = edit_canvas(image)
    w,h = canvas.size
    assert w%16 == h%16 == 0
    assert 655360 <= w*h <= 8294400
    assert max(w,h)/min(w,h) <= 3
    assert np.array_equal(canvas.crop(box), image)
    if size == (730,1024):
        assert canvas.size == (736,1024)
        assert box == (3,0,733,1024)


@pytest.mark.parametrize('size', [(788,524), (730,1024), (768,1024)])
def test_scaled_canvas_has_no_padded_border(size):
    image = Image.new('RGB', size, (80, 90, 100))
    canvas = scaled_edit_canvas(image)
    assert canvas.width % 16 == canvas.height % 16 == 0
    assert 655360 <= canvas.width * canvas.height <= 8294400
    assert canvas.getpixel((0, 0)) == (80, 90, 100)
    assert canvas.getpixel((canvas.width - 1, canvas.height - 1)) == (80, 90, 100)
    if size == (788, 524):
        assert canvas.size == (1008, 672)


def test_cosmetic_mask_is_local():
    image = Image.new('RGB', (788, 524))
    points = Detector().detect(image)[0]
    mask = makeup_mask(image.size, points)
    pixels = np.asarray(mask)
    assert 0 < np.count_nonzero(pixels) / pixels.size < .20
    assert pixels[0, 0] == 0


@pytest.mark.parametrize('style', [s for s in MakeupStyle if s != MakeupStyle.AUTO])
def test_explicit_style_has_wider_mask_than_auto(style):
    image = Image.new('RGB', (788, 524))
    points = Detector().detect(image)[0]
    auto = np.asarray(makeup_mask(image.size, points, MakeupStyle.AUTO))
    selected = np.asarray(makeup_mask(image.size, points, style))
    assert np.count_nonzero(selected) > np.count_nonzero(auto)
    assert np.count_nonzero(np.asarray(lip_mask(image.size, points, style))) > np.count_nonzero(
        np.asarray(lip_mask(image.size, points, MakeupStyle.AUTO)))
    assert selected[0, 0] == auto[0, 0] == 0


def test_complexion_mask_feathers_within_face_without_nose_skin_holes():
    size = (400, 400)
    points = [(0.5, 0.5)] * 478
    for index, angle in zip(FACE_OVAL, np.linspace(-np.pi / 2, 3 * np.pi / 2,
                                                    len(FACE_OVAL), endpoint=False)):
        points[index] = (.5 + .35 * np.cos(angle), .5 + .42 * np.sin(angle))
    points[33], points[263] = (.37, .43), (.63, .43)
    points[98], points[327] = (.45, .6), (.55, .6)
    mask = np.asarray(complexion_mask(size, points))
    assert mask[0, 0] == 0
    assert mask[300, 200] > 0
    assert mask[240, 180] > 0 and mask[240, 220] > 0
    assert 0 < mask[200, 65] < mask[300, 200]


def test_generation_region_retains_all_native_mask_pixels_without_rescaling():
    from makeup_refine.imaging import edit_region_box,prepare_edit_canvas
    from PIL import ImageDraw
    image=Image.fromarray(np.random.default_rng(11).integers(0,255,(1536,1152,3),dtype=np.uint8))
    mask=Image.new('L',image.size,0);ImageDraw.Draw(mask).rectangle((295,564,881,1106),fill=255)
    box=edit_region_box(image,mask)
    assert box==(180,427,996,1243)
    cropped=mask.crop(box)
    assert np.count_nonzero(cropped)==np.count_nonzero(mask)
    canvas,canvas_mask,undo=prepare_edit_canvas(image.crop(box),cropped)
    assert canvas.size==(816,816)
    assert np.array_equal(canvas.crop(undo),image.crop(box))
    assert np.array_equal(canvas_mask.crop(undo),cropped)


def test_broad_or_small_photo_keeps_full_generation_context():
    from makeup_refine.imaging import edit_region_box
    for size in ((1152,1536),(768,1024),(400,600)):
        mask=Image.new('L',size,255)
        assert edit_region_box(Image.new('RGB',size),mask)==(0,0,*size)


@pytest.mark.parametrize('box',[(0,0,100,100),(1000,1400,1152,1536),(0,650,1152,900)])
def test_generation_region_clamps_to_edges_and_keeps_every_editable_pixel(box):
    from makeup_refine.imaging import edit_region_box
    from PIL import ImageDraw
    image=Image.new('RGB',(1152,1536));mask=Image.new('L',image.size,0)
    ImageDraw.Draw(mask).rectangle(box,fill=255)
    crop=edit_region_box(image,mask)
    assert 0<=crop[0]<crop[2]<=image.width and 0<=crop[1]<crop[3]<=image.height
    assert np.count_nonzero(mask.crop(crop))==np.count_nonzero(mask)
