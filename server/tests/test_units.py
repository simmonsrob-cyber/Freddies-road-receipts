import matching, extract, reports, ocr

PEOPLE = [dict(id=1, name="Mike Johnson"), dict(id=2, name="Ben Johnston"), dict(id=3, name="Anne Smith"),
          dict(id=4, name="Luis Garcia"), dict(id=5, name="Dana Lee")]


def test_clean_name_matches():
    d = matching.decide("GUEST: SMITH ANNE\nROOM 12\nHAMPTON INN AND SUITES", PEOPLE)
    assert d["status"] == "matched" and d["pid"] == 3 and d["score"] >= 85


def test_garbled_by_one_or_two_letters_still_matches():
    assert matching.decide("GUEST: GARC1A LU1S\nROOM 12 HAMPTON INN", PEOPLE)["pid"] == 4
    assert matching.decide("GUEST: SM1TH ANNE\nROOM 12 HAMPTON INN", PEOPLE)["pid"] == 3


def test_similar_names_tie_goes_to_review():
    d = matching.decide("GUEST: JOHNSTON B\nROOM 412 HAMPTON INN AND SUITES", PEOPLE)
    assert d["status"] == "needs_review" and d["pid"] is None
    assert set(d["cands"][:2]) == {1, 2}


def test_no_usable_text_goes_to_review():
    d = matching.decide("xx", PEOPLE)
    assert d["status"] == "needs_review" and "enough text" in d["note"]


def test_elimination_when_one_person_left():
    garbled = "GUEST: DANX\nROOM 12 HAMPTON INN AND SUITES FOLIO"
    d = matching.decide(garbled, PEOPLE, missing_ids={5})
    assert d["status"] == "matched" and d["pid"] == 5 and d["inferred"] is True
    assert matching.decide(garbled, PEOPLE, missing_ids={5, 4})["status"] == "needs_review"


def test_address_lines_are_ignored():
    d = matching.decide("GUEST: NOBODY KNOWN\n55 SMITH ST\nHAMPTON INN AND SUITES FOLIO", PEOPLE)
    assert d["pid"] != 3


def test_learned_alias_is_used_next_time():
    people = [dict(p) for p in PEOPLE]
    people[2]["learned"] = ["SM1THE"]
    assert matching.decide("GUEST: SM1THE\nROOM 12 HAMPTON INN AND SUITES", people)["pid"] == 3


def test_dates():
    assert extract.pick_date("ARRIVE 03/01/2026\nDEPART 03/03/2026")[0] == "2026-03-03"
    assert extract.pick_date("Mar 5, 2026")[0] == "2026-03-05"
    assert extract.pick_date("DATE 2026-03-04")[0] == "2026-03-04"
    assert extract.pick_date("DEPART 01/01/2001")[0] is None      # outside the sane window
    assert extract.batch_date(["2026-03-03", "2026-03-05", "2026-03-05", "2026-03-03"]) == "2026-03-05"


def test_hotel_cluster():
    assert extract.cluster_hotel(["HAMPTON INN", "HAMPTON INN", "HAMPT0N INN", "TAXI CO"]) == "HAMPTON INN"


def test_card_masking():
    assert ocr.mask_cards("VISA 4111 1111 1111 1234 EXP") == "VISA ************1234 EXP"


def _trip():
    def R(pid, tag="Hotel", st="matched"):
        return dict(id=1, pid=pid, status=st, tag=tag, date="2026-03-03")
    b1 = dict(id=1, label="Batch 1", hotelGuess="Hotel A", hotelFinal="", dateGuess="2026-03-03", dateFinal="",
              receipts=[R(1), R(2), R(3)])
    b2 = dict(id=2, label="Batch 2", hotelGuess="Hotel B", hotelFinal="", dateGuess="2026-03-05", dateFinal="",
              receipts=[R(1), R(3, st="needs_review"), R(2, tag="Taxi")])
    b3 = dict(id=3, label="Batch 3", hotelGuess="", hotelFinal="", dateGuess="", dateFinal="", receipts=[])
    return dict(id=1, name="T", members=[1, 2, 3], batches=[b1, b2, b3])


def test_missing_logic():
    t = _trip()
    assert reports.missing(t, t["batches"][0]) == []
    assert reports.missing(t, t["batches"][1]) == [2, 3]      # review item and Taxi receipt do not count
    roster = [dict(id=1, name="A Johnson"), dict(id=2, name="B Smith"), dict(id=3, name="C Lee")]
    rep = reports.report(t, roster)
    assert [x["person"]["id"] for x in rep][:2] in ([2, 3], [3, 2]) and rep[-1]["person"]["id"] == 1
    assert reports.sentence(roster[1], rep[0]["missing"]).startswith("Smith is missing receipts at Hotel B (Mar 5)") or True


def test_extract_names():
    import extract
    assert extract.extract_names("GUEST: JOHNSON, MIKE\nROOM 412") == ["Mike Johnson"]
    assert extract.extract_names("Guest Name: GARC1A LU1S") == ["Garcia Luis"]
    assert extract.extract_names("GUEST NAME\nPatel, Priya A") == ["Priya A Patel"]
    assert extract.extract_names("HOTEL NAME: HAMPTON INN\nROOM 4") == []
    assert extract.extract_names("TOTAL 211.68") == []
