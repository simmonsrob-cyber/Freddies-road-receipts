"""PDFs, SUMMARY.pdf and the zip."""
import re
import secrets
import zipfile
from datetime import datetime
from pathlib import Path

import img2pdf
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas

import config
import db
import reports


def safe(s, fallback="x"):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(s)).strip("._-")
    return (s or fallback)[:60]


def person_folder(p):
    parts = p["name"].split()
    return safe(f"{parts[-1]}_{parts[0]}" if len(parts) > 1 else p["name"])


def last_name(p):
    return safe(p["name"].split()[-1])


def build_groups(trip, roster, scan_of):
    """Group receipts into PDFs: one per (person, batch, tag); extra pages when there is more than one."""
    by_id = {p["id"]: p for p in roster}
    groups, used = [], set()
    for b in trip["batches"]:
        buckets = {}
        for r in b["receipts"]:
            if r["status"] == "processing":
                continue
            key = (r["pid"] if r["status"] in ("matched", "confirmed") else None, r["tag"])
            buckets.setdefault(key, []).append(r)
        for (pid, tag), rs in buckets.items():
            who = last_name(by_id[pid]) if pid else "Unsorted"
            folder = person_folder(by_id[pid]) if pid else "UNSORTED"
            day = rs[0]["date"] or datetime.now().strftime("%Y-%m-%d")
            base = f"{who}_{day}_{safe(tag)}"
            name, n = base + ".pdf", 1
            while (folder, name) in used:
                n += 1
                name = f"{base}_{n}.pdf"
            used.add((folder, name))
            groups.append(dict(folder=folder, name=name, pid=pid, tag=tag, batch=b,
                               paths=[scan_of(r["id"]) for r in rs]))
    return groups


def summary_pdf(path, trip, roster):
    live = reports.live_batches(trip)
    by_id = {p["id"]: p for p in roster}
    rows = reports.report(trip, roster)
    c = canvas.Canvas(str(path), pagesize=landscape(letter))
    W, H = landscape(letter)
    dates = sorted(d for d in ((b["dateFinal"] or b["dateGuess"]) for b in live) if d)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(36, H - 44, trip["name"])
    c.setFont("Helvetica", 10)
    c.drawString(36, H - 60, ("Dates: %s to %s" % (dates[0], dates[-1])) if dates else "Dates: not read")
    other = {}
    for b in trip["batches"]:
        for r in b["receipts"]:
            if r["tag"] != config.HOTEL_TAG and r["status"] in ("matched", "confirmed"):
                other[r["tag"]] = other.get(r["tag"], 0) + 1
    if other:
        c.drawString(36, H - 74, "Other receipts filed: " + ", ".join(f"{k} {v}" for k, v in sorted(other.items())))
    left, top, namew = 36, H - 100, 150
    cols = max(1, len(live))
    colw = min(110, (W - 72 - namew) / cols)
    fs = 9 if len(rows) <= 14 else max(5, 9 - (len(rows) - 14) // 3)
    rowh = min(22, max(10, (top - 60) / (len(rows) + 2)))
    c.setFont("Helvetica-Bold", fs)
    c.drawString(left, top, "Person")
    for i, b in enumerate(live):
        label = reports.batch_label(b)
        c.drawString(left + namew + i * colw, top, label[:int(colw / (fs * 0.5))])
    c.setFont("Helvetica", fs)
    y = top - rowh
    for row in sorted(rows, key=lambda r: r["person"]["name"]):
        c.drawString(left, y, row["person"]["name"][:30])
        miss = {b["id"] for b in row["missing"]}
        for i, b in enumerate(live):
            if b["id"] in miss:
                c.setFillColorRGB(.75, 0, 0)
                c.drawString(left + namew + i * colw, y, "MISSING")
            else:
                c.setFillColorRGB(0, .45, 0)
                c.drawString(left + namew + i * colw, y, "OK")
            c.setFillColorRGB(0, 0, 0)
        y -= rowh
    c.setFont("Helvetica", 8)
    c.drawString(36, 28, "Generated " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    c.showPage()
    c.save()


def build_zip(trip, roster, scan_of):
    out_dir = config.DATA_DIR / "trips" / str(trip["id"]) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zpath = out_dir / f"{safe(trip['name'])}_Receipts_{stamp}.zip"
    tmp = out_dir / f"_tmp_{stamp}"
    tmp.mkdir(exist_ok=True)
    sumpath = tmp / "SUMMARY.pdf"
    summary_pdf(sumpath, trip, roster)
    groups = build_groups(trip, roster, scan_of)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(sumpath, "SUMMARY.pdf")
        for g in groups:
            data = img2pdf.convert([str(p) for p in g["paths"]])
            z.writestr(f"{g['folder']}/{g['name']}", data)
    sumpath.unlink()
    tmp.rmdir()
    tree = {}
    for g in groups:
        tree.setdefault(g["folder"], []).append(g["name"])
    return dict(path=zpath, size=zpath.stat().st_size, tree=tree, receipts=sum(len(g["paths"]) for g in groups))


def new_export(trip_id, path, size):
    token = secrets.token_urlsafe(24)[:32]
    c = db.conn()
    c.execute("INSERT INTO export(trip_id, token, path, size, created_at) VALUES (?,?,?,?,?)",
              (trip_id, token, str(path), size, db.now()))
    c.commit()
    c.close()
    return token
