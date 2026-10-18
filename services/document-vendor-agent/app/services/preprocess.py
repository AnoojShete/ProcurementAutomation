"""Image preprocessing before OCR (BR-2): grayscale, upscale small images,
remove noise, straighten a skewed scan. Only for images (scans, photos);
PDFs with a text layer never reach OCR. Switched by the business rule
document.image_preprocessing (kept on only because it measurably helps —
docs/results/extraction.md)."""
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

MIN_LONG_SIDE = 1600      # upscale anything smaller (OCR misses small text)
MAX_SKEW_DEGREES = 15     # bigger angles are left to PaddleOCR's angle classifier


def skew_angle(gray: np.ndarray) -> float:
    """Angle (degrees) of the text block: dark pixels' minimum-area rectangle."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < 50:
        return 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    # OpenCV 4.5+ returns (0, 90]; map to the small correction around 0.
    if angle > 45:
        angle -= 90
    return float(angle)


NOISE_SIGMA_THRESHOLD = 10.0  # denoise only images measured as noisy


def noise_sigma(gray: np.ndarray) -> float:
    """Estimated noise level (Immerkær's fast method): ~2-5 for a clean
    scan, 15+ for a grainy photo or fax."""
    h, w = gray.shape
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    conv = cv2.filter2D(gray.astype(np.float64), -1, kernel)
    return float(np.sum(np.abs(conv)) * np.sqrt(0.5 * np.pi) / (6 * (w - 2) * (h - 2)))


def preprocess_image(data: bytes, upscale: bool = True, denoise: str = "off",
                     max_scale: float = 1.5) -> tuple[bytes, dict]:
    """Returns (PNG bytes, what was done). Falls back to the input if the
    image can't be decoded. denoise: "auto" (only if measured noisy), "on", "off".
    Defaults are the measured best (docs/results/extraction.md): denoising
    blurred the characters PaddleOCR relies on, and upscaling more than
    1.5x turned half-resolution scans into nonsense."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return data, {"applied": False, "reason": "not decodable"}
    steps: dict = {"applied": True}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    sigma = noise_sigma(gray)  # measured before resizing changes it
    steps["noise_sigma"] = round(sigma, 1)
    if denoise == "on" or (denoise == "auto" and sigma > NOISE_SIGMA_THRESHOLD):
        gray = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
        steps["denoised"] = True

    h, w = gray.shape
    if upscale and max(h, w) < MIN_LONG_SIDE:
        scale = min(MIN_LONG_SIDE / max(h, w), max_scale)
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        steps["upscaled"] = round(scale, 2)

    angle = skew_angle(gray)
    if 0.3 <= abs(angle) <= MAX_SKEW_DEGREES:
        h, w = gray.shape
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        gray = cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        steps["deskewed_degrees"] = round(angle, 2)

    ok, png = cv2.imencode(".png", gray)
    return (png.tobytes(), steps) if ok else (data, {"applied": False, "reason": "encode failed"})
