import csv,io,pathlib
import pytest
from app import store
from app.config import SCHEMA_CURRENT,SCHEMA_LEGACY
from app.errors import DomainError
from app.modules.m1_scans.rules import evaluate as scan_evaluate
from app.modules.m6_compensation.rules import evaluate as reconcile
from app.pipeline import execute,load_sample
HEADER_LEGACY=b"scan_id,parcel,node,event_time,received_time,destination,promised_hours,declared_value,reported,note\n"
HEADER_CURRENT=b"scan_id,parcel,node,event_time,received_time,destination,promised_hours,declared_value,reported,note,review_mark\n"
BODY=[
    '0010,0001,收件,2026-11-02T00:00:00Z,2026-11-02T01:00:00Z,JP,24,200,0,x',
    '0011,0001,起运,2026-11-02T12:00:00Z,2026-11-02T13:00:00Z,JP,24,200,0,x',
    '0012,0001,清关,2026-11-03T00:00:00Z,2026-11-03T01:00:00Z,JP,24,200,0,x',
    '0013,0001,妥投,2026-11-04T00:00:00Z,2026-11-06T00:00:00Z,JP,24,200,0,x',
]
def build(marks,with_review_column=True):
    header=HEADER_CURRENT if with_review_column else HEADER_LEGACY
    lines=[header.decode().strip()]
    for body,mark in zip(BODY,marks):
        lines.append(body+((","+mark) if with_review_column else ""))
    return ("\n".join(lines)+"\n").encode()
def test_old_batch_without_marks_stays_legacy():
    "旧版记录没有复核标记：不得按新版完整性判定把已发生扫描判成不完整。"
    raw=build(["","","",""],with_review_column=False)
    result=scan_evaluate(raw,{})
    assert result["versioning"]["applied"]==SCHEMA_LEGACY
    assert result["versioning"]["switch_failed"] is False
    assert result["metrics"]["quarantine"]==0 and len(result["rows"])==4
    assert all(r["_version"]==SCHEMA_LEGACY and r["_version_basis"] for r in result["rows"])
def test_partial_marks_fall_back_as_whole_window():
    "同窗混有新老记录：整窗单一版本，不能逐票切换。"
    result=scan_evaluate(build(["已复核","","已复核",""]),{"parameters":{"version":"auto"}})
    decision=result["versioning"]
    assert decision["applied"]==SCHEMA_LEGACY and decision["auto_fallback"] is True
    assert decision["unmarked"]==2 and decision["rows"]==4
    assert {r["_version"] for r in result["rows"]}=={SCHEMA_LEGACY}
def test_fully_marked_window_uses_current():
    result=scan_evaluate(build(["已复核"]*4),{})
    assert result["versioning"]["applied"]==SCHEMA_CURRENT
    assert {r["_version"] for r in result["rows"]}=={SCHEMA_CURRENT}
def test_explicit_switch_failure_falls_back_and_is_reported():
    result=scan_evaluate(build(["已复核","","",""]),{"parameters":{"version":SCHEMA_CURRENT}})
    decision=result["versioning"]
    assert decision["switch_failed"] is True and decision["applied"]==SCHEMA_LEGACY
    assert "切换失败" in decision["failure_detail"]
def test_explicit_legacy_request_never_fabricates_incomplete():
    result=scan_evaluate(build(["已复核"]*4),{"parameters":{"version":SCHEMA_LEGACY}})
    assert result["versioning"]["applied"]==SCHEMA_LEGACY and result["metrics"]["quarantine"]==0
def test_unknown_version_rejected():
    with pytest.raises(DomainError) as error: scan_evaluate(build(["已复核"]*4),{"parameters":{"version":"v9"}})
    assert error.value.code=="BAD_VERSION"
def test_reconcile_rejects_mixed_versions():
    "结算必须整窗一个版本：逐票混口径直接拒绝。"
    context={"intake":None,"versioning":{"applied":SCHEMA_CURRENT},"quarantine":[]}
    with pytest.raises(DomainError) as error: reconcile([{"parcel":"1","_version":SCHEMA_LEGACY}],context)
    assert error.value.code in {"VERSION_MIXED","VERSION_MISMATCH"}
def test_reconcile_accepts_single_window_version(result):
    assert result["stages"][5]["metrics"]["balanced"] is True
    assert all(r["_version"]==result["versioning"]["applied"] for r in result["stages"][5]["rows"])
def test_pipeline_exposes_decision_and_parcel_basis(result):
    assert result["versioning"]["applied"]==SCHEMA_LEGACY
    assert result["manifest"]["applied_version"]==SCHEMA_LEGACY
    for row in result["stages"][3]["rows"]: assert row["_version_basis"] and row["_version"]==SCHEMA_LEGACY
def test_retry_does_not_create_new_batch(raw_sample=None):
    first=execute(load_sample("dirty.csv"));second=execute(load_sample("dirty.csv"))
    assert first["run_id"]==second["run_id"] and len(store.history())==1
    assert second["last_attempt"]["kind"]=="RETRY_REUSED"
def test_failed_switch_keeps_old_batch():
    "新版本切换失败：恢复旧版批次，批次号不变。"
    old=execute(load_sample("upgrade.csv"))
    assert old["applied_version"]==SCHEMA_LEGACY
    attempt=execute(load_sample("upgrade.csv"),{"version":SCHEMA_CURRENT})
    assert attempt["run_id"]==old["run_id"] and len(store.history())==1
    assert attempt["applied_version"]==SCHEMA_LEGACY
    assert attempt["last_attempt"]["switch_failed"] is True and attempt["last_attempt"]["restored"] is True
    assert attempt["last_attempt"]["batch_version"]==SCHEMA_LEGACY
def test_failed_switch_keeps_original_payload_and_raw():
    old=execute(load_sample("upgrade.csv"))
    original=store.get(old["run_id"])
    sha,raw=store.raw_for_run(old["run_id"])
    execute(load_sample("upgrade.csv"),{"version":SCHEMA_CURRENT})
    after=store.get(old["run_id"])
    assert after["stages"][5]["metrics"]==original["stages"][5]["metrics"]
    assert store.raw_for_run(old["run_id"])==(sha,raw)
def test_retry_after_failed_switch_adds_nothing():
    execute(load_sample("upgrade.csv"))
    execute(load_sample("upgrade.csv"),{"version":SCHEMA_CURRENT})
    execute(load_sample("upgrade.csv"),{"version":SCHEMA_CURRENT})
    assert len(store.history())==1
def test_missing_review_column_never_switches_to_current():
    raw=build(["已复核"]*4,with_review_column=False)
    result=scan_evaluate(raw,{"parameters":{"version":SCHEMA_CURRENT}})
    assert result["versioning"]["switch_failed"] is True and result["versioning"]["applied"]==SCHEMA_LEGACY

def test_page_states_applied_version_and_failure_notice(client):
    "首次即失败的切换：页面明确显示整窗按旧版建批，而不是伪造新版。"
    client.post("/api/runs",json={"sample":"upgrade.csv","parameters":{"version":"v2"}})
    html=client.get("/").data.decode()
    assert "整窗版本裁决" in html and "新版切换失败" in html and "整窗按旧版口径建立批次" in html
    assert "旧版" in html and "恢复旧版口径" in html

def test_page_shows_restored_batch_after_failed_switch(client):
    "已有旧版批次时切换失败：页面显示恢复旧版批次，批次号不变。"
    first=client.post("/api/runs",json={"sample":"upgrade.csv"}).get_json()
    client.post("/api/runs",json={"sample":"upgrade.csv","parameters":{"version":"v2"}})
    html=client.get("/").data.decode()
    assert "已恢复旧版批次 "+first["run_id"] in html
    assert "重试不会新增批次" in html

def test_page_selects_version_label_for_current(client):
    client.post("/api/runs",json={"sample":"reviewed.csv"})
    html=client.get("/").data.decode()
    assert "整窗全部扫描带复核标记" in html and "新版" in html

def test_archive_is_one_batch_with_version_basis(client):
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    r=client.get("/api/runs/"+p["run_id"]+"/archive")
    rows=list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    assert {row[0] for row in rows[1:] if row[0]}=={p["run_id"]}
    header=rows[0];assert "applied_version" in header and "version_basis" in header
    assert rows[-1][3]=="manifest"
    import json as _json
    manifest=_json.loads(rows[-1][6]);assert manifest["applied_version"]=="v1" and manifest["records"]==8

def test_raw_scan_survives_attempts_and_is_first_seen(client):
    data=open(pathlib.Path(__file__).resolve().parent.parent/"sample_data"/"upgrade.csv","rb").read()
    r=client.post("/api/upload",data={"file":(io.BytesIO(data),"u.csv"),"version":"v2"},content_type="multipart/form-data")
    run_id=r.get_json()["run_id"]
    first=client.get("/api/runs/"+run_id+"/raw")
    client.post("/api/runs",json={"sample":"upgrade.csv","parameters":{"version":"v2"}})
    again=client.get("/api/runs/"+run_id+"/raw")
    assert again.data==data==first.data
    assert again.headers["X-Raw-Sha256"]==first.headers["X-Raw-Sha256"]

def test_reviewed_batch_blocks_switch_without_new_batch(client):
    p=client.post("/api/runs",json={"sample":"upgrade.csv"}).get_json()
    assert client.post("/api/runs/"+p["run_id"]+"/review",json={"version":1,"decision":"已复核"}).status_code==200
    r=client.post("/api/runs",json={"sample":"reviewed.csv"})
    assert r.status_code==409 and r.get_json()["code"]=="REVIEWED_BATCH"
    assert len(store.history())==1

def test_legacy_database_is_migrated(tmp_path,monkeypatch):
    "旧库缺列时就地补齐，已存批次仍可读，不重建不丢行。"
    import sqlite3
    monkeypatch.setattr(store,"DATA_DIR",tmp_path)
    db=sqlite3.connect(tmp_path/"records.db")
    db.execute("CREATE TABLE runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("INSERT INTO runs(id,payload) VALUES (?,?)",("old",'{"stages":[],"manifest":{}}'))
    db.commit();db.close()
    migrated=store.get("old")
    assert migrated["version"]==1 and migrated["decision"]=="待复核"
    assert migrated["applied_version"] is None
    assert [r["run_id"] for r in store.history()]==["old"]

def test_successful_upgrade_keeps_every_original_scan(client):
    "同窗升级到新版：批次仍唯一，但两份原始扫描都保留、可分别取回。"
    import hashlib
    old=open(pathlib.Path(__file__).resolve().parent.parent/"sample_data"/"upgrade.csv","rb").read()
    r=client.post("/api/upload",data={"file":(io.BytesIO(old),"u.csv"),"version":"v2"},content_type="multipart/form-data")
    run_id=r.get_json()["run_id"]
    assert r.get_json()["applied_version"]==SCHEMA_LEGACY
    new=client.post("/api/runs",json={"sample":"reviewed.csv"}).get_json()
    assert new["run_id"]==run_id and new["applied_version"]==SCHEMA_CURRENT
    assert len(store.history())==1
    raws={item["sha256"] for item in store.raws(run_id)}
    assert hashlib.sha256(old).hexdigest() in raws and len(raws)==2
    for sha in raws: assert client.get(f"/api/runs/{run_id}/raws/{sha}").status_code==200
    assert client.get(f"/api/runs/{run_id}/raws/{'0'*64}").status_code==404

def test_manifest_hash_matches_downloaded_raw(client):
    import hashlib
    p=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    r=client.get("/api/runs/"+p["run_id"]+"/raw")
    assert hashlib.sha256(r.data).hexdigest()==p["manifest"]["input_sha256"]==r.headers["X-Raw-Sha256"]

def test_return_review_allows_version_redecision(client):
    "退回复核即解封证据，允许重新裁决整窗版本；仍是同一批次。"
    first=client.post("/api/runs",json={"sample":"upgrade.csv"}).get_json()
    client.post("/api/runs/"+first["run_id"]+"/review",json={"version":1,"decision":"已复核"})
    blocked=client.post("/api/runs",json={"sample":"reviewed.csv"})
    assert blocked.status_code==409
    client.post("/api/runs/"+first["run_id"]+"/review",json={"version":2,"decision":"退回复核"})
    upgraded=client.post("/api/runs",json={"sample":"reviewed.csv"}).get_json()
    assert upgraded["run_id"]==first["run_id"] and upgraded["applied_version"]==SCHEMA_CURRENT
    assert len(store.history())==1

def test_v2_sealed_batch_is_not_silently_downgraded(client):
    "已按新版封存的批次，遇缺标记请求不得静默降级；退回复核后可显式改为旧版。"
    first=client.post("/api/runs",json={"sample":"reviewed.csv"}).get_json()
    assert first["applied_version"]==SCHEMA_CURRENT
    blocked=client.post("/api/runs",json={"sample":"upgrade.csv"})
    assert blocked.status_code==409 and blocked.get_json()["code"]=="VERSION_CONFLICT"
    assert store.get(first["run_id"])["applied_version"]==SCHEMA_CURRENT
    client.post("/api/runs/"+first["run_id"]+"/review",json={"version":1,"decision":"退回复核"})
    downgraded=client.post("/api/runs",json={"sample":"upgrade.csv"}).get_json()
    assert downgraded["run_id"]==first["run_id"] and downgraded["applied_version"]==SCHEMA_LEGACY
    assert len(store.history())==1
