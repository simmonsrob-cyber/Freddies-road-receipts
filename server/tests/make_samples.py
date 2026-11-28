"""Make synthetic receipt photos (tilted paper on a dark table) for testing."""
import glob
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = (glob.glob("/usr/share/fonts/**/DejaVuSansMono-Bold.ttf", recursive=True) or glob.glob("/usr/share/fonts/**/DejaVuSansMono.ttf", recursive=True) or [None])[0]


def f(size):
    return ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()


def receipt_page(name_line, hotel="HAMPTON INN AND SUITES", depart="03/05/2026", w=700, h=1000, card="4111 1111 1111 1234"):
    im = Image.new("RGB", (w, h), (250, 250, 247))
    d = ImageDraw.Draw(im)
    d.text((w // 2, 70), hotel, font=f(44), fill=(10, 10, 10), anchor="mm")
    d.text((w // 2, 125), "GUEST FOLIO", font=f(24), fill=(60, 60, 60), anchor="mm")
    y = 200
    for t in [f"GUEST: {name_line}", "ROOM 412", "ARRIVE 03/03/2026", f"DEPART {depart}", "123 MAIN ST", "", "ROOM CHARGE      189.00", "TAX               22.68", "TOTAL            211.68", f"VISA {card}"]:
        d.text((50, y), t, font=f(28), fill=(15, 15, 15))
        y += 52
    return im


def photo(page, out, tilt=True, table=(70, 60, 55), size=(1800, 2400)):
    """Paste the page onto a dark table with a perspective tilt."""
    W, H = size
    bg = np.full((H, W, 3), table, dtype=np.uint8)
    pg = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
    ph, pw = pg.shape[:2]
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    dst = np.float32([[300, 350], [1500, 250], [1550, 2050], [260, 2150]]) if tilt else np.float32([[300, 300], [1500, 300], [1500, 2100], [300, 2100]])
    M = cv2.getPerspectiveTransform(src, dst)
    warp = cv2.warpPerspective(pg, M, (W, H))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), M, (W, H))
    bg[mask > 0] = warp[mask > 0]
    cv2.imwrite(str(out), bg, [cv2.IMWRITE_JPEG_QUALITY, 88])


if __name__ == "__main__":
    import sys
    photo(receipt_page(sys.argv[1] if len(sys.argv) > 1 else "MIKE JOHNSON"), "sample.jpg")
