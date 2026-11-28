"""End to end: photos in, OCR, matching, review, missing report, zip, download."""
import io, json, time, zipfile
from pathlib import Path

import pytest

import app as appmod
import config
import make_samples as ms

NAMES = ["Mike Johnson", "Ben Johnston", "Anne Smith", "Luis Garcia", "Dana Lee",
         "Priya Patel", "Tom Nguyen", "Kim Brown", "Sam Davis", "Ray Miller"]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    a = appmod.create_app(start=False)
    return a.test_client()


def drain():
    n = 0
    while not appmod.JOBS.empty():
        rid, quad = appmod.JOBS.get_nowait()
        appmod.process(rid, quad)
        n += 1
    return n


def jpg(tmp, name_line, tilt=True, table=(70, 60, 55), hotel="HAMPTON INN AND SUITES", depart="03/05/2026"):
    p = Path(tmp) / (name_line.replace(" ", "_").replace(",", "") + ".jpg")
    ms.photo(ms.receipt_page(name_line, hotel=hotel, depart=depart), p, tilt=tilt, table=table)
    return p


def post_files(client, bid, paths, tag="Hotel"):
    data = {"tag": tag, "files": [(open(p, "rb"), Path(p).name) for p in paths]}
    r = client.post(f"/api/batch/{bid}/upload", data=data, content_type="multipart/form-data")
    return r.get_json()


def st(client):
    return client.get("/api/state").get_json()


def test_full_flow(client, tmp_path):
    # roster, mission, batch
    ids = {}
    for n in NAMES:
        ids[n] = client.post("/api/person", json={"name": n}).get_json()["id"]
    client.post(f"/api/person/{ids['Ray Miller']}", json={"active": 0})
    mem = [ids[n] for n in NAMES]
    tid = client.post("/api/trip", json={"name": "Test Mission, Mar 2026", "members": mem}).get_json()["id"]
    bid = client.post(f"/api/trip/{tid}/batch", json={}).get_json()["id"]

    # 8 clean tilted hotel receipts (Brown left out, Miller left out); one garbled name; Johnston is ambiguous
    lines = {"Mike Johnson": "JOHNSON, MIKE", "Ben Johnston": "JOHNSTON B", "Anne Smith": "SMITH, ANNE",
             "Luis Garcia": "GARC1A, LU1S", "Dana Lee": "LEE, DANA", "Priya Patel": "PATEL, PRIYA",
             "Tom Nguyen": "NGUYEN, TOM", "Sam Davis": "DAVIS, SAM"}
    paths = [jpg(tmp_path, v) for v in lines.values()]
    t0 = time.time()
    r = post_files(client, bid, paths)
    assert r["ok"] and len(r["ids"]) == 8 and not r["errors"]
    drain()
    print("\nread 8 receipts in %.1fs" % (time.time() - t0))

    s = st(client)
    trip = next(t for t in s["trips"] if t["id"] == tid)
    b = trip["batches"][0]
    by = {x["id"]: x for x in b["receipts"]}
    status = {P: by[i]["status"] for P, i in zip(lines, r["ids"])}
    print(status)
    assert status["Mike Johnson"] == "matched" and by[r["ids"][0]]["pid"] == ids["Mike Johnson"]
    assert status["Anne Smith"] == "matched" and status["Luis Garcia"] == "matched"
    assert status["Ben Johnston"] == "needs_review"                    # tie with Johnson: never filed silently
    assert b["hotelGuess"].upper().startswith("HAMPTON"), b["hotelGuess"]
    assert b["dateGuess"] == "2026-03-05", b["dateGuess"]
    print("hotel guess:", b["hotelGuess"], "date guess:", b["dateGuess"])

    # card number must be masked in stored text
    assert "4111" not in by[r["ids"][0]]["text"] and "1234" in by[r["ids"][0]]["text"]

    # confirm the tie; alias gets learned
    rid = r["ids"][1]
    assert client.post(f"/api/receipt/{rid}/confirm", json={"person_id": ids["Ben Johnston"]}).get_json()["ok"]

    # Taxi receipt does not count as a hotel receipt
    r2 = post_files(client, bid, [jpg(tmp_path, "BROWN, KIM", hotel="CITY TAXI")], tag="Taxi")
    drain()
    trip = next(t for t in st(client)["trips"] if t["id"] == tid)
    import reports
    miss = reports.missing(trip, trip["batches"][0])
    assert set(miss) == {ids["Kim Brown"], ids["Ray Miller"]}, miss
    print("missing:", [n for n in NAMES if ids[n] in miss])

    # second batch with one hotel receipt, so the report lists each person's missing batches
    bid2 = client.post(f"/api/trip/{tid}/batch", json={}).get_json()["id"]
    post_files(client, bid2, [jpg(tmp_path, "BROWN, KIM", hotel="MARRIOTT COURTYARD", depart="03/07/2026")])
    drain()
    s = st(client)
    trip = next(t for t in s["trips"] if t["id"] == tid)
    rep = reports.report(trip, s["roster"])
    print([ (x["person"]["name"], len(x["missing"])) for x in rep][:4])
    assert rep[0]["missing"] and len(rep[0]["missing"]) == 2           # Miller: missing in both batches

    # build the zip (email not configured: zip still built, readable message)
    t0 = time.time()
    r = client.post(f"/api/trip/{tid}/ac-send", json={}).get_json()
    print("zip build %.1fs" % (time.time() - t0), r["mb"], "MB", r["error"])
    assert r["ok"] is False and "not set up" in r["error"]
    z = client.get(r["link"].replace("http://localhost", ""))
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.data))
    names = zf.namelist()
    print("\n".join(names))
    assert "SUMMARY.pdf" in names and any(n.startswith("Johnson_Mike/") for n in names)
    assert any("_Taxi" in n for n in names)
    assert all(n.endswith(".pdf") for n in names)
    assert client.get("/download/notarealtoken.zip").status_code == 404

    # upload validation
    bad = client.post(f"/api/batch/{bid}/upload", data={"tag": "Hotel", "files": [(io.BytesIO(b"not an image"), "x.jpg")]},
                      content_type="multipart/form-data").get_json()
    assert bad["ok"] and bad["errors"] and not bad["ids"]


def test_failed_autocrop_then_manual_crop(client, tmp_path):
    pid = client.post("/api/person", json={"name": "Zed Quinn"}).get_json()["id"]
    tid = client.post("/api/trip", json={"name": "Crop test", "members": [pid]}).get_json()["id"]
    bid = client.post(f"/api/trip/{tid}/batch", json={}).get_json()["id"]
    # white paper on a white table: no visible edges, so auto-crop is expected to fail
    p = jpg(tmp_path, "QUINN, ZED", tilt=False, table=(250, 250, 247))
    r = post_files(client, bid, [p])
    drain()
    rec = next(x for t in st(client)["trips"] if t["id"] == tid for b in t["batches"] for x in b["receipts"])
    print("autoCrop:", rec["autoCrop"], rec["status"])
    assert rec["autoCrop"] is False
    # manual crop around the page (fractions of the photo)
    res = client.post(f"/api/receipt/{rec['id']}/crop", json={"points": [[.167, .125], [.833, .125], [.833, .875], [.167, .875]]}).get_json()
    assert res["ok"]
    drain()
    rec = next(x for t in st(client)["trips"] if t["id"] == tid for b in t["batches"] for x in b["receipts"])
    assert rec["autoCrop"] is True and rec["status"] in ("matched", "needs_review")
    print("after manual crop:", rec["status"])


def test_crew_only_and_partial_names(client, tmp_path):
    """Only the preloaded Crew 4 names exist; a first or last name alone is enough; strangers are never added."""
    s0 = st(client)
    names = {p["name"] for p in s0["roster"]}
    assert "Alicia Grajeda" in names and "Cale Simmons" in names 
    base = len(names)
    tid = client.post("/api/trip", json={"name": "Crew only", "members": []}).get_json()["id"]
    assert len(next(t for t in st(client)["trips"] if t["id"] == tid)["members"]) == len([p for p in st(client)["roster"] if p["active"]])   # nobody ticked: whole crew
    bid = client.post(f"/api/trip/{tid}/batch", json={}).get_json()["id"]
    post_files(client, bid, [jpg(tmp_path, "ALICIA"), jpg(tmp_path, "SIMMONS"), jpg(tmp_path, "OKAFOR, CHIDI")])
    drain()
    s = st(client)
    recs = next(t for t in s["trips"] if t["id"] == tid)["batches"][0]["receipts"]
    pn = {p["id"]: p["name"] for p in s["roster"]}
    got = sorted((pn.get(r["pid"]) or "-", r["status"]) for r in recs)
    print(got)
    assert ("Alicia Grajeda", "matched") in got and ("Cale Simmons", "matched") in got
    stranger = next(r for r in recs if r["pid"] is None)
    assert stranger["status"] == "needs_review"
    # a name that is not on the crew list is refused and nobody is created
    res = client.post(f"/api/receipt/{stranger['id']}/confirm", json={"name": "Chidi Okafor"})
    assert not res.get_json()["ok"]
    assert len(st(client)["roster"]) == base
    # a crew name works, in any case or punctuation
    assert client.post(f"/api/receipt/{stranger['id']}/confirm", json={"name": "katie  ha."}).get_json()["ok"]


def test_old_database_is_upgraded_not_lost(tmp_path, monkeypatch):
    """A database made by V5 (no sugg column) keeps every row when V6 starts."""
    import sqlite3, importlib
    old = tmp_path / "old"
    old.mkdir()
    con = sqlite3.connect(old / "app.db")
    con.executescript(open(Path(config.BASE_DIR) / "db.py").read().split('SCHEMA = """')[1].split('"""')[0]
                      .replace("sugg TEXT NOT NULL DEFAULT '[]', ", ""))
    con.execute("INSERT INTO person(full_name) VALUES ('Old Person')")
    con.commit(); con.close()
    monkeypatch.setattr(config, "DATA_DIR", old)
    monkeypatch.setattr(config, "DB_PATH", old / "app.db")
    import db
    db.init()
    s = db.state()
    assert [p["name"] for p in s["roster"]] == ["Old Person"]
    db.init()      # safe to run twice


def test_delete_receipt(client, tmp_path):
    tid = client.post("/api/trip", json={"name": "Delete test", "members": []}).get_json()["id"]
    bid = client.post(f"/api/trip/{tid}/batch", json={}).get_json()["id"]
    post_files(client, bid, [jpg(tmp_path, "DELGADO, ANA", hotel="HAMPTON INN AND SUITES")])
    drain()
    rec = next(x for t in st(client)["trips"] if t["id"] == tid for b in t["batches"] for x in b["receipts"])
    orig = Path(__import__("db").conn().execute("SELECT original_path, scan_path FROM receipt WHERE id=?", (rec["id"],)).fetchone()["original_path"])
    scan = Path(__import__("db").conn().execute("SELECT scan_path FROM receipt WHERE id=?", (rec["id"],)).fetchone()["scan_path"])
    assert orig.exists() and scan.exists()
    assert client.post(f"/api/receipt/{rec['id']}/delete", json={}).get_json()["ok"]
    left = [x for t in st(client)["trips"] if t["id"] == tid for b in t["batches"] for x in b["receipts"]]
    assert left == [] and not orig.exists() and not scan.exists()          # record and both files are gone
    assert client.post(f"/api/receipt/{rec['id']}/delete", json={}).status_code == 404   # second delete is harmless


def test_delete_mission_and_person(client, tmp_path):
    import shutil
    pa = client.post("/api/person", json={"name": "Vera Quill"}).get_json()["id"]
    pb = client.post("/api/person", json={"name": "Otto Marsh"}).get_json()["id"]
    tid = client.post("/api/trip", json={"name": "Doomed", "members": [pa, pb]}).get_json()["id"]
    bid = client.post(f"/api/trip/{tid}/batch", json={}).get_json()["id"]
    post_files(client, bid, [jpg(tmp_path, "QUILL, VERA"), jpg(tmp_path, "MARSH, OTTO")])
    drain()
    folder = Path(config.DATA_DIR) / "trips" / str(tid)
    assert folder.exists() and any(folder.rglob("*.jpg"))
    # a second, untouched mission must survive
    keep = client.post("/api/trip", json={"name": "Keeper", "members": [pa]}).get_json()["id"]
    # remove a person: their receipt is kept and goes back to review
    res = client.post(f"/api/person/{pa}/delete", json={}).get_json()
    assert res["ok"] and res["receipts"] == 1
    s = st(client)
    assert pa not in [p["id"] for p in s["roster"]]
    t = next(x for x in s["trips"] if x["id"] == tid)
    assert pa not in t["members"] and len(t["batches"][0]["receipts"]) == 2
    assert sum(r["status"] == "needs_review" for r in t["batches"][0]["receipts"]) == 1
    assert client.post(f"/api/person/{pa}/delete", json={}).status_code == 404
    # delete the mission: rows and the whole folder are gone, the other mission stays
    assert client.post(f"/api/trip/{tid}/delete", json={}).get_json()["ok"]
    s = st(client)
    assert tid not in [x["id"] for x in s["trips"]] and keep in [x["id"] for x in s["trips"]]
    assert not folder.exists()
    assert client.post(f"/api/trip/{tid}/delete", json={}).status_code == 404
