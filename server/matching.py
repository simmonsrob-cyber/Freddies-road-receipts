"""Person matching: honest about being unsure."""
import re

from rapidfuzz import fuzz

import config
from ocr import normalize

STREET = {"ST", "STREET", "AVE", "AVENUE", "BLVD", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "HWY", "WAY", "CT"}


CONFUSED = str.maketrans("01234568", "OIZEASGB")   # digits OCR often reads for letters


def _fix_token(tok):
    """Inside a word that mixes letters and digits (GARC1A), turn look-alike digits back into letters."""
    if any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok):
        return tok.translate(CONFUSED)
    return tok


def _clean_lines(text):
    """Normalized text with address-looking lines removed."""
    keep = []
    for line in text.splitlines():
        n = " ".join(_fix_token(t) for t in normalize(line).split())
        if n and not (set(n.split()) & STREET):
            keep.append(n)
    return keep


def windows(text):
    """Sliding windows of 1 to 3 consecutive tokens, by token count."""
    w = {1: set(), 2: set(), 3: set()}
    for line in _clean_lines(text):
        toks = line.split()
        for n in (1, 2, 3):
            for i in range(len(toks) - n + 1):
                w[n].add(" ".join(toks[i:i + n]))
    return w


def name_forms(full_name, aliases="", learned=()):
    n = normalize(full_name).split()
    forms = set()
    if n:
        forms.add(" ".join(n))
        forms.add(n[-1])
        forms.add(n[0])
        forms.add(f"{n[-1]} {n[0]}")
        forms.add(f"{n[0]} {n[-1]}")
    for a in list(filter(None, (x.strip() for x in aliases.split(",")))) + list(learned):
        na = normalize(a)
        if na:
            forms.add(na)
    return {f for f in forms if len(f.replace(" ", "")) >= 3}


def _best(form, wins):
    k = min(len(form.split()), 3)
    best, bw = 0.0, ""
    for w in wins.get(k, ()):
        sc = fuzz.ratio(form, w)
        if sc > best:
            best, bw = sc, w
    return best, bw


def score_person(wins, forms, full_name):
    parts = normalize(full_name).split()
    best, window = 0.0, ""
    for f in forms:
        s, w = _best(f, wins)
        if " " not in f:               # a lone surname or first name is weaker evidence than a full name
            s -= config.SINGLE_NAME_PENALTY
        if s > best:
            best, window = s, w
    if len(parts) >= 2:
        a, _ = _best(parts[0], wins)
        b, _ = _best(parts[-1], wins)
        if a > 85 and b > 85:
            best = min(100.0, best + 5)
    return best, window


def score_all(text, people):
    """people: [{id, name, aliases, learned}] -> sorted [(pid, score, window)] best first."""
    wins = windows(text)
    out = []
    for p in people:
        forms = name_forms(p["name"], p.get("aliases", ""), p.get("learned", ()))
        s, w = score_person(wins, forms, p["name"])
        out.append((p["id"], s, w))
    out.sort(key=lambda x: -x[1])
    return out


def decide(text, people, missing_ids=None):
    """Return dict(status, pid, score, cands, inferred, note)."""
    cleaned = " ".join(_clean_lines(text))
    scores = score_all(text, people)
    cands = [pid for pid, _, _ in scores[:3]]
    if len(re.sub(r"\s", "", cleaned)) < config.MIN_TEXT_CHARS:
        return dict(status="needs_review", pid=None, score=0.0, cands=cands, inferred=False,
                    note="Could not read enough text on this one.")
    best = scores[0] if scores else (None, 0.0, "")
    second = scores[1][1] if len(scores) > 1 else 0.0
    if best[1] >= config.ACCEPT_SCORE and best[1] - second >= config.TIE_MARGIN:
        return dict(status="matched", pid=best[0], score=best[1], cands=cands, inferred=False, note="")
    if config.ELIMINATION_ENABLED and missing_ids is not None and len(missing_ids) == 1:
        m = next(iter(missing_ids))
        ms = next((s for pid, s, _ in scores if pid == m), 0.0)
        others = [s for pid, s, _ in scores if pid != m]
        if ms >= config.ELIMINATION_MIN_SCORE and all(o <= config.ELIMINATION_MIN_SCORE for o in others):
            return dict(status="matched", pid=m, score=ms, cands=cands, inferred=True,
                        note="Guessed: everyone else already has a receipt.")
    return dict(status="needs_review", pid=None, score=best[1], cands=cands, inferred=False,
                note="Not sure whose this is.")


def learn_window(text, person):
    """Best-matching token window for this person, to remember a garbled spelling."""
    forms = name_forms(person["name"], person.get("aliases", ""), person.get("learned", ()))
    _, w = score_person(windows(text), forms, person["name"])
    return w
