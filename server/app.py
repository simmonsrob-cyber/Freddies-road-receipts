"""Receipt OCR App: Flask app, background worker, routes."""
import json
import queue
import secrets
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, abort
from PIL import Image

import config
import db
import export
import extract
import imaging
import mailer
import matching
import ocr
import reports

JOBS = queue.Queue()
_worker_started = False
_lock = threading.Lock()


# ---------------------------------------------------------------- worker
def _people(c, trip_id):
    rows = c.execute("SELECT p.* FROM person p JOIN trip_member m ON m.person_id=p.id WHERE m.trip_id=?", (trip_id,)).fetchall()
    if not rows:   # an old mission with nobody listed: use the whole active crew list
        rows = c.execute("SELECT * FROM person WHERE active=1").fetchall()
    out = []
    for p in rows:
        learned = [r["alias"] for r in c.execute("SELECT alias FROM learned_alias WHERE person_id=?", (p["id"],))]
        out.append(dict(id=p["id"], name=p["full_name"], aliases=p["aliases"], learned=learned))
    return out


def _refresh_batch_guess(c, batch_id):
    hotels = [r["hotel_line"] for r in c.execute(
        "SELECT hotel_line FROM receipt WHERE batch_id=? AND tag=? AND hotel_line IS NOT NULL", (batch_id, config.HOTEL_TAG))]
    dates = [r["date_found"] for r in c.execute(
        "SELECT date_found FROM receipt WHERE batch_id=? AND tag=? AND date_found IS NOT NULL", (batch_id, config.HOTEL_TAG))]
    c.execute("UPDATE batch SET hotel_guess=?, date_guess=? WHERE id=?",
              (extract.cluster_hotel(hotels), extract.batch_date(dates), batch_id))


def process(receipt_id, quad=None):
    c = db.conn()
    try:
        r = c.execute("SELECT r.*, b.trip_id FROM receipt r JOIN batch b ON b.id=r.batch_id WHERE r.id=?", (receipt_id,)).fetchone()
        if not r:
            return
        tdir = config.DATA_DIR / "trips" / str(r["trip_id"]) / "scans"
        tdir.mkdir(parents=True, exist_ok=True)
        out = tdir / (secrets.token_hex(8) + ".jpg")
        try:
            gray, auto = imaging.scan(r["original_path"], str(out), quad)
            res = ocr.read(gray)
        except Exception:
            traceback.print_exc()
            c.execute("UPDATE receipt SET status='needs_review', note=? WHERE id=?",
                      ("Could not read this photo. Try a clearer one, or fix the crop.", receipt_id))
            c.commit()
            return
        people = _people(c, r["trip_id"])
        missing_ids = None
        if r["tag"] == config.HOTEL_TAG:
            have = {x["person_id"] for x in c.execute(
                "SELECT person_id FROM receipt WHERE batch_id=? AND tag=? AND id<>? AND person_id IS NOT NULL "
                "AND status IN ('matched','confirmed')", (r["batch_id"], config.HOTEL_TAG, receipt_id))}
            missing_ids = {p["id"] for p in people} - have
        if r["status"] == "confirmed" and r["person_id"]:   # re-scan of an already confirmed receipt keeps its owner
            d = dict(status="confirmed", pid=r["person_id"], score=r["match_score"], cands=json.loads(r["cands"] or "[]"),
                     inferred=False, note="")
        else:
            d = matching.decide(res["text"], people, missing_ids)
        sugg = extract.extract_names(res["text"])
        hotel = extract.hotel_from_lines(res["lines"], res["height"]) if r["tag"] == config.HOTEL_TAG else None
        found, _ = extract.pick_date(res["text"])
        old = r["scan_path"]
        c.execute("""UPDATE receipt SET person_id=?, match_score=?, status=?, inferred=?, cands=?, sugg=?, note=?, scan_path=?,
                     ocr_text=?, hotel_line=?, date_found=?, auto_crop=? WHERE id=?""",
                  (d["pid"], d["score"], d["status"], int(d["inferred"]), json.dumps(d["cands"]), json.dumps(sugg), d["note"],
                   str(out), res["text"], hotel, found, int(auto), receipt_id))
        _refresh_batch_guess(c, r["batch_id"])
        c.commit()
        if old and old != str(out):
            Path(old).unlink(missing_ok=True)
    finally:
        c.close()


def _worker():
    while True:
        rid, quad = JOBS.get()
        try:
            process(rid, quad)
        except Exception:
            traceback.print_exc()
        JOBS.task_done()


def start_worker():
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    c = db.conn()
    for r in c.execute("SELECT id FROM receipt WHERE status='processing'"):
        JOBS.put((r["id"], None))
    c.close()
    threading.Thread(target=_worker, daemon=True, name="ocr-worker").start()


# ---------------------------------------------------------------- app
def create_app(start=True):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024 * 25
    db.init()
    if start:
        start_worker()

    def J(**kw):
        return jsonify(kw)

    def bad(msg, code=400):
        return jsonify(ok=False, error=msg), code

    @app.after_request
    def hdr(r):
        r.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/"):
            r.headers["Cache-Control"] = "no-store"
        return r

    @app.get("/")
    def index():
        return render_template("index.html", version=config.VERSION)

    @app.get("/health")
    def health():
        return J(ok=True, version=config.VERSION, queue=JOBS.qsize())

    @app.get("/api/state")
    def api_state():
        return jsonify(db.state())

    # ---- roster
    @app.post("/api/person")
    def person_add():
        d = request.get_json(force=True)
        name = (d.get("name") or "").strip()
        if not name:
            return bad("Type a name first.")
        c = db.conn()
        cur = c.execute("INSERT INTO person(full_name, aliases) VALUES (?,?)", (name, (d.get("aliases") or "").strip()))
        c.commit()
        c.close()
        return J(ok=True, id=cur.lastrowid)

    @app.post("/api/person/<int:pid>/delete")
    def person_delete(pid):
        c = db.conn()
        if not c.execute("SELECT 1 FROM person WHERE id=?", (pid,)).fetchone():
            c.close()
            return bad("That person is already gone.", 404)
        n = c.execute("SELECT COUNT(*) FROM receipt WHERE person_id=?", (pid,)).fetchone()[0]
        # their receipts are kept and go back to the review list
        c.execute("UPDATE receipt SET person_id=NULL, status='needs_review', inferred=0, "
                  "note='This person was removed. Pick who this is.' WHERE person_id=?", (pid,))
        c.execute("DELETE FROM trip_member WHERE person_id=?", (pid,))
        c.execute("DELETE FROM learned_alias WHERE person_id=?", (pid,))
        c.execute("DELETE FROM person WHERE id=?", (pid,))
        c.commit()
        c.close()
        return J(ok=True, receipts=n)

    @app.post("/api/person/<int:pid>")
    def person_edit(pid):
        d = request.get_json(force=True)
        c = db.conn()
        p = c.execute("SELECT * FROM person WHERE id=?", (pid,)).fetchone()
        if not p:
            return bad("No such person.", 404)
        c.execute("UPDATE person SET full_name=?, aliases=?, active=? WHERE id=?",
                  ((d.get("name") or p["full_name"]).strip(), d.get("aliases", p["aliases"]).strip(),
                   int(d.get("active", p["active"])), pid))
        c.commit()
        c.close()
        return J(ok=True)

    # ---- tags
    @app.post("/api/tag")
    def tag_add():
        n = "".join(ch for ch in (request.get_json(force=True).get("name") or "") if ch.isalnum() or ch in "-_")[:20]
        if not n:
            return bad("Type a tag name.")
        c = db.conn()
        c.execute("INSERT OR IGNORE INTO tag(name, sort) VALUES (?, (SELECT COALESCE(MAX(sort),0)+1 FROM tag))", (n,))
        c.commit()
        c.close()
        return J(ok=True, name=n)

    # ---- trips and batches
    @app.post("/api/trip")
    def trip_add():
        d = request.get_json(force=True)
        name, mem = (d.get("name") or "").strip(), d.get("members") or []
        if not name:
            return bad("Give the mission a name.")
        c = db.conn()
        cur = c.execute("INSERT INTO trip(name, created_at) VALUES (?,?)", (name, db.now()))
        if not mem:   # nobody ticked: the whole crew list is on the mission
            mem = [r["id"] for r in c.execute("SELECT id FROM person WHERE active=1")]
        for m in mem:
            c.execute("INSERT OR IGNORE INTO trip_member(trip_id, person_id) VALUES (?,?)", (cur.lastrowid, int(m)))
        c.commit()
        c.close()
        return J(ok=True, id=cur.lastrowid)

    @app.post("/api/trip/<int:tid>/delete")
    def trip_delete(tid):
        c = db.conn()
        if not c.execute("SELECT 1 FROM trip WHERE id=?", (tid,)).fetchone():
            c.close()
            return bad("That mission is already gone.", 404)
        c.execute("DELETE FROM receipt WHERE batch_id IN (SELECT id FROM batch WHERE trip_id=?)", (tid,))
        c.execute("DELETE FROM batch WHERE trip_id=?", (tid,))
        c.execute("DELETE FROM trip_member WHERE trip_id=?", (tid,))
        c.execute("DELETE FROM export WHERE trip_id=?", (tid,))
        c.execute("DELETE FROM trip WHERE id=?", (tid,))
        c.commit()
        c.close()
        # every photo, scan and zip of a mission lives in its own folder
        shutil.rmtree(config.DATA_DIR / "trips" / str(int(tid)), ignore_errors=True)
        return J(ok=True)

    @app.post("/api/trip/<int:tid>/status")
    def trip_status(tid):
        st = request.get_json(force=True).get("status")
        if st not in ("open", "sent"):
            return bad("Bad status.")
        c = db.conn()
        c.execute("UPDATE trip SET status=? WHERE id=?", (st, tid))
        c.commit()
        c.close()
        return J(ok=True)

    @app.post("/api/trip/<int:tid>/batch")
    def batch_add(tid):
        c = db.conn()
        seq = (c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM batch WHERE trip_id=?", (tid,)).fetchone()[0])
        cur = c.execute("INSERT INTO batch(trip_id, seq, label, created_at) VALUES (?,?,?,?)", (tid, seq, f"Batch {seq}", db.now()))
        c.commit()
        c.close()
        return J(ok=True, id=cur.lastrowid)

    @app.post("/api/batch/<int:bid>/meta")
    def batch_meta(bid):
        d = request.get_json(force=True)
        c = db.conn()
        c.execute("UPDATE batch SET hotel_final=?, date_final=? WHERE id=?",
                  ((d.get("hotel") or "").strip(), (d.get("date") or "").strip(), bid))
        c.commit()
        c.close()
        return J(ok=True)

    # ---- upload
    @app.post("/api/batch/<int:bid>/upload")
    def upload(bid):
        c = db.conn()
        b = c.execute("SELECT * FROM batch WHERE id=?", (bid,)).fetchone()
        tag = (request.form.get("tag") or "").strip()
        if not b:
            return bad("No such batch.", 404)
        if not c.execute("SELECT 1 FROM tag WHERE name=?", (tag,)).fetchone():
            return bad("Pick a tag first.")
        odir = config.DATA_DIR / "trips" / str(b["trip_id"]) / "originals"
        odir.mkdir(parents=True, exist_ok=True)
        ids, errors = [], []
        today = datetime.now().strftime("%Y-%m-%d")
        for f in request.files.getlist("files"):
            f.stream.seek(0, 2)
            size = f.stream.tell()
            f.stream.seek(0)
            if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                errors.append(f"{f.filename}: bigger than {config.MAX_UPLOAD_MB} MB. Turn on 'Shrink big photos'.")
                continue
            try:
                im = Image.open(f.stream)
                fmt = im.format
                im.verify()
            except Exception:
                errors.append(f"{f.filename}: not a photo this app can read. On iPhone set the camera to 'Most Compatible'.")
                continue
            if fmt not in config.ALLOWED_FORMATS:
                errors.append(f"{f.filename}: only JPEG, PNG or HEIC photos are accepted.")
                continue
            ext = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png"}.get(fmt, "heic")
            path = odir / f"{secrets.token_hex(12)}.{ext}"
            f.stream.seek(0)
            f.save(path)
            cur = c.execute("""INSERT INTO receipt(batch_id, status, tag, upload_date, original_path, created_at)
                               VALUES (?,?,?,?,?,?)""", (bid, "processing", tag, today, str(path), db.now()))
            ids.append(cur.lastrowid)
        c.commit()
        c.close()
        for i in ids:
            JOBS.put((i, None))
        return J(ok=True, ids=ids, errors=errors)

    # ---- receipts
    @app.post("/api/receipt/<int:rid>/confirm")
    def confirm(rid):
        d = request.get_json(force=True)
        pid, name = int(d.get("person_id") or 0), (d.get("name") or "").strip()
        c = db.conn()
        r = c.execute("SELECT r.*, b.trip_id FROM receipt r JOIN batch b ON b.id=r.batch_id WHERE r.id=?", (rid,)).fetchone()
        if not r or not (pid or name):
            c.close()
            return bad("Pick a person or type a name.")
        if not pid:                                   # typed or suggested name: find that person, or add them
            pid = db.person_id_for_name(c, name, create=not config.ONLY_CREW)
            if not pid:
                c.close()
                return bad("That name is not on the crew list. Pick someone from the list.")
        elif not c.execute("SELECT 1 FROM person WHERE id=?", (pid,)).fetchone():
            c.close()
            return bad("That person was not found.")
        c.execute("INSERT OR IGNORE INTO trip_member(trip_id, person_id) VALUES (?,?)", (r["trip_id"], pid))
        c.execute("UPDATE receipt SET person_id=?, status='confirmed', inferred=0, note='' WHERE id=?", (pid, rid))
        people = {p["id"]: p for p in _people(c, r["trip_id"])}
        if pid in people and r["ocr_text"]:
            w = matching.learn_window(r["ocr_text"], people[pid])
            known = matching.name_forms(people[pid]["name"], people[pid]["aliases"], people[pid]["learned"])
            if w and w not in known:
                c.execute("INSERT OR IGNORE INTO learned_alias(person_id, alias) VALUES (?,?)", (pid, w))
        c.commit()
        c.close()
        return J(ok=True)

    @app.post("/api/receipt/<int:rid>/delete")
    def receipt_delete(rid):
        c = db.conn()
        r = c.execute("SELECT * FROM receipt WHERE id=?", (rid,)).fetchone()
        if not r:
            c.close()
            return bad("That receipt is already gone.", 404)
        c.execute("DELETE FROM receipt WHERE id=?", (rid,))
        _refresh_batch_guess(c, r["batch_id"])
        c.commit()
        c.close()
        for path in (r["original_path"], r["scan_path"]):
            if path:
                Path(path).unlink(missing_ok=True)
        return J(ok=True)

    @app.post("/api/receipt/<int:rid>/crop")
    def crop(rid):
        pts = request.get_json(force=True).get("points") or []
        if len(pts) != 4:
            return bad("Need four corners.")
        quad = [(min(1, max(0, float(x))), min(1, max(0, float(y)))) for x, y in pts]
        c = db.conn()
        c.execute("UPDATE receipt SET status=CASE WHEN status='confirmed' THEN 'confirmed' ELSE 'processing' END WHERE id=?", (rid,))
        c.commit()
        c.close()
        JOBS.put((rid, quad))
        return J(ok=True)

    @app.get("/img/<int:rid>")
    def img(rid):
        c = db.conn()
        r = c.execute("SELECT original_path, scan_path FROM receipt WHERE id=?", (rid,)).fetchone()
        c.close()
        if not r:
            abort(404)
        if request.args.get("orig") or not r["scan_path"]:
            p = Path(r["original_path"])
            if p.suffix.lower() not in (".jpg", ".png"):
                prev = p.with_suffix(".preview.jpg")
                if not prev.exists():
                    Image.open(p).convert("RGB").save(prev, "JPEG", quality=80)
                p = prev
            return send_file(p, max_age=3600)
        return send_file(r["scan_path"], mimetype="image/jpeg", max_age=3600)

    # ---- Aircraft Commander Review
    def _scan_of(rid):
        c = db.conn()
        r = c.execute("SELECT original_path, scan_path FROM receipt WHERE id=?", (rid,)).fetchone()
        c.close()
        if r["scan_path"]:
            return r["scan_path"]
        p = Path(r["original_path"])
        if p.suffix.lower() in (".jpg", ".png"):
            return str(p)
        out = p.with_suffix(".conv.jpg")
        Image.open(p).convert("L").save(out, "JPEG", quality=config.JPEG_QUALITY)
        return str(out)

    @app.post("/api/trip/<int:tid>/ac-send")
    def ac_send(tid):
        st = db.state()
        trip = next((t for t in st["trips"] if t["id"] == tid), None)
        if not trip:
            return bad("No such mission.", 404)
        if any(r["status"] == "processing" for b in trip["batches"] for r in b["receipts"]):
            return bad("Some receipts are still being read. Wait a minute and try again.")
        try:
            info = export.build_zip(trip, st["roster"], _scan_of)
        except Exception as e:
            traceback.print_exc()
            return bad("Could not build the zip (%s)." % type(e).__name__, 500)
        token = export.new_export(tid, info["path"], info["size"])
        base = config.PUBLIC_BASE_URL or request.host_url.rstrip("/")
        link = f"{base}/download/{token}.zip"
        mb = info["size"] / 1048576
        attach = mb <= config.MAX_ATTACH_MB - config.ATTACH_MARGIN_MB
        rep = reports.report(trip, st["roster"])
        lines = [reports.sentence(x["person"], x["missing"]) for x in rep if x["missing"]] or ["Nobody is missing receipts."]
        body = (f"Receipts for {trip['name']}\n\n" + "\n".join(lines) +
                f"\n\n{info['receipts']} receipts in the zip ({mb:.1f} MB).\n" +
                ("The zip is attached. " if attach else "The zip is too big to attach, so use the link. ") +
                f"\nDownload link (works on Tailscale): {link}\n")
        err = mailer.send(f"Receipts: {trip['name']}", body, info["path"] if attach else None)
        if err is None:
            c = db.conn()
            c.execute("UPDATE trip SET status='sent', sent_at=? WHERE id=?", (db.now(), tid))
            c.commit()
            c.close()
        return J(ok=err is None, error=err, mb=round(mb, 1), attached=attach and err is None, link=link,
                 tree=info["tree"], receipts=info["receipts"])

    @app.get("/download/<token>.zip")
    def download(token):
        c = db.conn()
        r = c.execute("SELECT * FROM export WHERE token=?", (token,)).fetchone()
        c.close()
        if not r or not Path(r["path"]).exists():
            abort(404)
        return send_file(r["path"], as_attachment=True, download_name=Path(r["path"]).name)

    return app
