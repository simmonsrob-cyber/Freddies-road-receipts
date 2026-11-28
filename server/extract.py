"""Hotel name and date guesses."""
import re
from collections import Counter
from datetime import date, datetime

from rapidfuzz import fuzz

from ocr import normalize

MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
KW_OUT = ("DEPART", "CHECK OUT", "CHECKOUT", "CHECK-OUT")
KW_ANY = KW_OUT + ("ARRIVE", "ARRIVAL", "DATE")
HOTEL_WORDS = ("INN", "SUITES", "HOTEL", "RESORT", "LODGE", "MARRIOTT", "HILTON", "HYATT", "HAMPTON",
               "HOLIDAY", "COURTYARD", "FAIRFIELD", "RESIDENCE")

RX = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), "mdy"),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2})\b"), "mdy2"),
    (re.compile(r"\b([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{4})\b"), "mon d y"),
    (re.compile(r"\b(\d{1,2}) ([A-Za-z]{3})[A-Za-z]*\.?,? (\d{4})\b"), "d mon y"),
]


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(line):
    out = []
    for rx, kind in RX:
        for g in rx.findall(line):
            if kind == "ymd":
                d = _mk(int(g[0]), int(g[1]), int(g[2]))
            elif kind == "mdy":
                d = _mk(int(g[2]), int(g[0]), int(g[1]))
            elif kind == "mdy2":
                d = _mk(2000 + int(g[2]), int(g[0]), int(g[1]))
            elif kind == "mon d y":
                d = _mk(int(g[2]), MONTHS.get(g[0].upper()[:3], 0), int(g[1])) if g[0].upper()[:3] in MONTHS else None
            else:
                d = _mk(int(g[2]), MONTHS.get(g[1].upper()[:3], 0), int(g[0])) if g[1].upper()[:3] in MONTHS else None
            if d:
                out.append(d)
    return out


def sane(d, today=None):
    today = today or date.today()
    return abs((d - today).days) <= 366


def pick_date(text, today=None):
    """Prefer departure/check-out, then other keyword lines, then any date. Returns (iso|None, all_iso)."""
    found, depart, kw = [], [], []
    for line in text.splitlines():
        up = line.upper()
        for d in find_dates(line):
            if not sane(d, today):
                continue
            found.append(d)
            if any(k in up for k in KW_OUT):
                depart.append(d)
            elif any(k in up for k in KW_ANY):
                kw.append(d)
    pick = depart[-1] if depart else (kw[0] if kw else (found[0] if found else None))
    return (pick.isoformat() if pick else None), sorted({d.isoformat() for d in found})


def hotel_candidate(lines, height):
    """Largest-text line in the top quarter of the page, else a line with a hotel word."""
    top = [l for l in lines if l["top"] < 0.25 * height and sum(c.isalpha() for c in l["text"]) >= 4]
    if top:
        return max(top, key=lambda l: l["h"])["text"].strip()
    for l in lines:
        if any(w in l["text"].upper() for w in HOTEL_WORDS):
            return l["text"].strip()
    return None


def hotel_from_lines(lines, height):
    return hotel_candidate(lines, height)


def cluster_hotel(names):
    """Cluster look-alike lines (score >= 80); most frequent original spelling of the biggest cluster."""
    names = [n for n in names if n]
    clusters = []
    for n in names:
        key = normalize(n)
        for c in clusters:
            if fuzz.ratio(key, c["key"]) >= 80:
                c["items"].append(n)
                break
        else:
            clusters.append(dict(key=key, items=[n]))
    if not clusters:
        return ""
    big = max(clusters, key=lambda c: len(c["items"]))
    return Counter(big["items"]).most_common(1)[0][0]


def batch_date(dates):
    """Most common date; ties go to the latest."""
    dates = [d for d in dates if d]
    if not dates:
        return ""
    c = Counter(dates)
    top = max(c.values())
    return max(d for d, n in c.items() if n == top)


# ---- guest names (so a mission needs no crew list)
_FIX = str.maketrans("01234568", "OIZEASGB")
_NAME_LABEL = re.compile(r"\b(?:GUEST\s*NAME|GUEST|NAME|BILL\s*TO|CARD\s*HOLDER|CARDHOLDER)\b\s*[:#\-]?\s*(.*)$", re.I)
_NOT_NAME = re.compile(r"\b(ROOM|DATE|ARRIVE|ARRIVAL|DEPART|DEPARTURE|FOLIO|INN|HOTEL|SUITES|TOTAL|BALANCE|AMOUNT|TAX|NIGHT|"
                       r"RATE|PAGE|NUMBER|VISA|MASTERCARD|AMEX|CARD|ACCOUNT|ADDRESS|PHONE|CONFIRMATION)\b")


def _tidy_name(raw):
    toks = []
    for t in (raw or "").upper().split():
        if any(ch.isalpha() for ch in t) and any(ch.isdigit() for ch in t):
            t = t.translate(_FIX)       # GARC1A -> GARCIA
        toks.append(t)
    s = re.sub(r"[^A-Z'\-, ]", " ", " ".join(toks))
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 4 or len(s) > 40 or _NOT_NAME.search(s):
        return ""
    if "," in s:                         # LAST, FIRST -> First Last
        q = [x.strip() for x in s.split(",") if x.strip()]
        parts = (" ".join(q[1:]) + " " + q[0]).split()
    else:
        parts = s.split()
    if len(parts) < 2 or len(parts) > 4:
        return ""
    return " ".join(p.capitalize() if len(p) > 1 else p for p in parts)


def extract_names(text):
    """Up to three guest names read from label lines like 'GUEST: JOHNSON, MIKE'. Each is a suggestion only."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    out = []
    for i, l in enumerate(lines):
        m = _NAME_LABEL.search(l)
        if not m:
            continue
        n = _tidy_name(m.group(1))
        if not n and not m.group(1).strip() and i + 1 < len(lines):
            n = _tidy_name(lines[i + 1])
        if n and n not in out:
            out.append(n)
    return out[:3]
