"""Tesseract wrapper."""
import re

import pytesseract
from pytesseract import Output

CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def mask_cards(text):
    """Mask all but the last four digits of anything that looks like a card number."""
    def m(x):
        digits = re.sub(r"\D", "", x.group(0))
        return "*" * (len(digits) - 4) + digits[-4:]
    return CARD.sub(m, text)


def normalize(text):
    t = re.sub(r"[^A-Z0-9 \n]", " ", text.upper())
    return re.sub(r"[ \t]+", " ", t).strip()


def read(gray):
    """Return dict(text, lines=[{text, top, h}], height)."""
    text = pytesseract.image_to_string(gray, lang="eng", config="--oem 1 --psm 6")
    if len(text.strip()) < 40:
        alt = pytesseract.image_to_string(gray, lang="eng", config="--oem 1 --psm 4")
        if len(alt.strip()) > len(text.strip()):
            text = alt
    d = pytesseract.image_to_data(gray, lang="eng", config="--oem 1 --psm 6", output_type=Output.DICT)
    lines = {}
    for i, w in enumerate(d["text"]):
        if not w.strip() or float(d["conf"][i]) < 0:
            continue
        k = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        L = lines.setdefault(k, dict(words=[], top=d["top"][i], hs=[]))
        L["words"].append(w)
        L["top"] = min(L["top"], d["top"][i])
        L["hs"].append(d["height"][i])
    out = [dict(text=" ".join(v["words"]), top=v["top"], h=sorted(v["hs"])[len(v["hs"]) // 2]) for v in lines.values()]
    out.sort(key=lambda x: x["top"])
    return dict(text=mask_cards(text), lines=out, height=gray.shape[0])
