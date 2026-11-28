"""Scan pipeline: phone photo in, cleaned page out. Each step is its own function."""
import cv2
import numpy as np
from PIL import Image, ImageOps

import config

try:  # optional HEIC support
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass


def load_oriented(path):
    """Load with EXIF orientation applied, as a BGR OpenCV array."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def resize_long_edge(img, edge):
    h, w = img.shape[:2]
    s = edge / max(h, w)
    if s >= 1:
        return img, 1.0
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA), s


def order_corners(pts):
    pts = np.array(pts, dtype="float32").reshape(4, 2)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def find_page(small):
    """Return 4 corners (in `small` coordinates) or None."""
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area_img = small.shape[0] * small.shape[1]
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:10]:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4 and cv2.contourArea(approx) >= 0.20 * area_img:
            return order_corners(approx)
    return None


def flatten(img, quad):
    q = order_corners(quad)
    tl, tr, br, bl = q
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if w < 50 or h < 50:
        return img
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(q, dst), (w, h))


def enhance(img):
    """Grayscale with local contrast boost: crisp text, smaller JPEG."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def scan(original_path, out_path, quad_norm=None):
    """Make the stored scan. quad_norm = 4 corners as 0..1 fractions of the photo (manual crop).
    Returns (gray_for_ocr, auto_crop)."""
    img = load_oriented(original_path)
    H, W = img.shape[:2]
    auto = True
    if quad_norm is not None:
        quad = np.array([[x * W, y * H] for x, y in quad_norm], dtype="float32")
    else:
        small, s = resize_long_edge(img, config.DETECT_EDGE)
        q = find_page(small)
        quad = None if q is None else q / s
    if quad is None:
        auto, page = False, img
    else:
        page = flatten(img, quad)
    gray = enhance(resize_long_edge(page, config.OCR_EDGE)[0])
    store = resize_long_edge(gray, config.STORE_EDGE)[0]
    Image.fromarray(store).save(out_path, "JPEG", quality=config.JPEG_QUALITY, optimize=True)
    return gray, auto
