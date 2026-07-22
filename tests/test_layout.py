from PIL import Image

from textvideomaker.layout import contain_size, cover_size, fit_image, vf_fit


def test_cover_fills_both_dimensions():
    # wide source into tall frame: height drives the scale
    w, h = cover_size(1920, 1080, 1080, 1920)
    assert h == 1920
    assert w >= 1080


def test_cover_exact_fit():
    assert cover_size(1080, 1920, 1080, 1920) == (1080, 1920)


def test_contain_fits_inside():
    w, h = contain_size(1920, 1080, 1080, 1920)
    assert w == 1080
    assert h <= 1920


def test_fit_image_output_size_cover_and_contain():
    src = Image.new("RGB", (400, 300), (200, 10, 10))
    for mode in ("cover", "contain"):
        out = fit_image(src, 108, 192, mode)
        assert out.size == (108, 192)


def test_vf_fit_strings():
    assert "crop=1080:1920" in vf_fit("cover", 1080, 1920)
    assert "pad=1080:1920" in vf_fit("contain", 1080, 1920)
