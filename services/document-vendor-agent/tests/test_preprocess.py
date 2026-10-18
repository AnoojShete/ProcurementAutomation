"""BR-2: image preprocessing before OCR straightens skewed scans, upscales
small images, and never breaks an input it can't read."""
import cv2
import numpy as np

from app.services.preprocess import preprocess_image, skew_angle


def _page(angle=0.0, size=(1200, 900)):
    """A white page with lines of 'text' (black bars), rotated by `angle`."""
    h, w = size
    img = np.full((h, w), 255, np.uint8)
    for y in range(150, h - 150, 40):
        cv2.rectangle(img, (120, y), (w - 120, y + 14), 0, -1)
    if angle:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        img = cv2.warpAffine(img, m, (w, h), borderValue=255)
    return img


def _png(img):
    return cv2.imencode(".png", img)[1].tobytes()


def test_skew_is_detected():
    assert abs(skew_angle(_page(0))) < 0.5
    assert 4 <= abs(skew_angle(_page(5))) <= 6


def test_skewed_page_is_straightened():
    out, steps = preprocess_image(_png(_page(5)))
    assert "deskewed_degrees" in steps
    fixed = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert abs(skew_angle(fixed)) < 1.0


def test_straight_page_is_not_rotated():
    _, steps = preprocess_image(_png(_page(0)))
    assert "deskewed_degrees" not in steps


def test_small_image_is_upscaled():
    out, steps = preprocess_image(_png(_page(0, size=(600, 450))))
    img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert steps["upscaled"] == 1.5 and max(img.shape) == 900   # capped at 1.5x


def test_undecodable_input_is_passed_through():
    data = b"%PDF-1.4 not an image"
    out, steps = preprocess_image(data)
    assert out == data and steps["applied"] is False
