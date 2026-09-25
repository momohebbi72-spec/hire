from radar import db as dbm
from radar.profile import load_profile
from radar.scoring import score_item
from radar.sources.base import Item


def test_duplicate_updates_existing_record():
    profile = load_profile()
    a = Item(title="SEO Manager", company="Example Co", location="Remote", url="https://a.example/1",
             source="Board A", source_type="remoteok", external_id="1")
    b = Item(title="SEO  Manager", company="Example Co.", location="Remote", url="https://b.example/9",
             source="Board B", source_type="remotive", external_id="9", description="longer text " * 20)
    with dbm.get_db() as con:
        kind1, id1 = dbm.upsert_opportunity(con, a, score_item(a, profile))
        kind2, id2 = dbm.upsert_opportunity(con, b, score_item(b, profile))
        con.commit()
        row = con.execute("SELECT * FROM opportunities WHERE id=?", (id1,)).fetchone()
    assert (kind1, kind2) == ("new", "updated")
    assert id1 == id2
    assert row["seen_count"] == 2
    assert "Board B" in row["also_on"]


def test_status_history():
    profile = load_profile()
    it = Item(title="Freelance SEO audit", source_type="freelancer", external_id="x1", source="Freelancer")
    with dbm.get_db() as con:
        _, oid = dbm.upsert_opportunity(con, it, score_item(it, profile))
        dbm.set_status(con, oid, "Saved")
        hist = con.execute("SELECT status FROM status_history WHERE opportunity_id=?", (oid,)).fetchall()
    assert [h[0] for h in hist] == ["Saved"]
