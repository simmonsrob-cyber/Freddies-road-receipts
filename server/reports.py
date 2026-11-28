"""Missing-receipt logic. Works on the same dict shape the API returns."""
import config


def counts(r):
    return r["status"] in ("matched", "confirmed") and r["pid"] and r["tag"] == config.HOTEL_TAG


def present(batch):
    return {r["pid"] for r in batch["receipts"] if counts(r)}


def missing(trip, batch):
    p = present(batch)
    return [m for m in trip["members"] if m not in p]


def hotel_name(b):
    return b["hotelFinal"] or b["hotelGuess"] or b["label"]


def date_text(b):
    d = b["dateFinal"] or b["dateGuess"]
    if not d:
        return ""
    from datetime import date
    y, m, dd = map(int, d.split("-"))
    return date(y, m, dd).strftime("%b ") + str(dd)


def batch_label(b):
    dt = date_text(b)
    return hotel_name(b) + (f" ({dt})" if dt else "")


def live_batches(trip):
    return [b for b in trip["batches"] if b["receipts"]]


def report(trip, roster):
    """[{person, missing:[batch,...]}] most missing first. Skips batches with no receipts yet."""
    by_id = {p["id"]: p for p in roster}
    out = []
    for m in trip["members"]:
        out.append(dict(person=by_id[m], missing=[b for b in live_batches(trip) if m in missing(trip, b)]))
    out.sort(key=lambda x: -len(x["missing"]))
    return out


def sentence(person, miss):
    last = person["name"].split()[-1]
    return f"{last} is missing receipts at " + " and ".join(batch_label(b) for b in miss) + "."


def review_queue(trip):
    return [(b, r) for b in trip["batches"] for r in b["receipts"] if r["status"] == "needs_review"]
