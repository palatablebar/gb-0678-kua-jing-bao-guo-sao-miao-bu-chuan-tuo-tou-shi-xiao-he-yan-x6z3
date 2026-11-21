import sqlite3,json,hashlib
from datetime import datetime,timezone
from app.config import DATA_DIR
from app.errors import DomainError
def _now(): return datetime.now(timezone.utc).isoformat()
def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核',applied_version TEXT,switch_failed INTEGER NOT NULL DEFAULT 0,created_at TEXT)")
    # 旧库升级：缺列时补齐，不重建、不丢已存批次。
    columns={row[1] for row in db.execute("PRAGMA table_info(runs)")}
    for name,ddl in (("applied_version","TEXT"),("switch_failed","INTEGER NOT NULL DEFAULT 0"),("created_at","TEXT")):
        if name not in columns: db.execute(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")
    # 原始扫描单独落库且只增不删：批次重试、版本回退都不得动它。
    db.execute("CREATE TABLE IF NOT EXISTS raw_inputs (sha256 TEXT PRIMARY KEY,content BLOB NOT NULL,created_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS run_raws (run_id TEXT NOT NULL,sha256 TEXT NOT NULL,first_seen TEXT NOT NULL,PRIMARY KEY (run_id,sha256))")
    db.execute("CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL)")
    return db
def _stored(db,run_id):
    return db.execute("SELECT payload,version,decision,applied_version,switch_failed FROM runs WHERE id=?",(run_id,)).fetchone()
def _decode(row):
    payload=json.loads(row[0])
    return {**payload,"version":row[1],"decision":row[2],
            "applied_version":row[3] or (payload.get("versioning") or {}).get("applied"),
            "switch_failed":bool(row[4])}
def _event(db,run_id,kind,detail):
    db.execute("INSERT INTO events(run_id,kind,detail,created_at) VALUES (?,?,?,?)",(run_id,kind,json.dumps(detail,ensure_ascii=False),_now()))
def _attempt_from_events(db,run_id):
    rows=list(db.execute("SELECT kind,detail,created_at FROM events WHERE run_id=? ORDER BY event_id DESC LIMIT 1",(run_id,)))
    if not rows: return None
    kind,detail,at=rows[0];detail=json.loads(detail)
    restored=kind=="VERSION_SWITCH_FAILED" and bool(detail.get("restored"))
    return {"requested":detail.get("requested"),"applied":detail.get("applied"),
            "switch_failed":kind=="VERSION_SWITCH_FAILED","restored":restored,
            "batch_version":detail.get("batch_version",detail.get("applied")),
            "detail":detail.get("detail",""),"at":at,"kind":kind}
def save(run_id,payload,raw=None):
    versioning=payload.get("versioning") or {}
    applied=versioning.get("applied");failed=bool(versioning.get("switch_failed"))
    with connect() as db:
        if raw is not None:
            # 原始扫描只增不删：无论后续重试或版本回退，首次上传的内容都保留。
            sha=hashlib.sha256(raw).hexdigest()
            db.execute("INSERT OR IGNORE INTO raw_inputs(sha256,content,created_at) VALUES (?,?,?)",(sha,raw,_now()))
            db.execute("INSERT OR IGNORE INTO run_raws(run_id,sha256,first_seen) VALUES (?,?,?)",(run_id,sha,_now()))
        stored=_stored(db,run_id)
        if stored is None:
            db.execute("INSERT INTO runs(id,payload,applied_version,switch_failed,created_at) VALUES (?,?,?,?,?)",(run_id,json.dumps(payload,ensure_ascii=False),applied,int(failed),_now()))
            kind="VERSION_SWITCH_FAILED" if failed else "BATCH_SEALED"
            _event(db,run_id,kind,{"requested":versioning.get("requested"),"applied":applied,"header_schema":versioning.get("header_schema"),"detail":versioning.get("basis"),"restored":False,"batch_version":applied})
        else:
            current=_decode(stored);batch_version=current.get("applied_version")
            if failed and applied==batch_version:
                # 请求的新版未生效，整窗仍是旧版：保持已封存旧版批次，仅记录失败标记。
                db.execute("UPDATE runs SET switch_failed=1 WHERE id=?",(run_id,))
                _event(db,run_id,"VERSION_SWITCH_FAILED",{"requested":versioning.get("requested"),"applied":applied,"restored":True,"batch_version":batch_version,"detail":versioning.get("basis")})
            elif failed:
                # 窗口已按新版封存，但本次请求不再满足新版条件：不得静默降级已封存证据。
                raise DomainError("VERSION_CONFLICT","批次已按新版封存，本次请求不满足新版条件；请退回复核后显式采用旧版",409)
            elif applied==batch_version:
                # 同版本重试：复用已有正式批次，不新增行、不改复核版本。
                db.execute("UPDATE runs SET switch_failed=0 WHERE id=?",(run_id,))
                _event(db,run_id,"RETRY_REUSED",{"requested":versioning.get("requested"),"applied":applied,"batch_version":batch_version,"detail":"重试复用已有正式批次"})
            else:
                # 已复核批次已作为证据封存：版本口径变更必须先退回复核，避免在已确认证据下静默换解释。
                # 退回复核说明证据已解封，允许重新裁决版本。
                if current.get("decision","待复核")=="已复核":
                    raise DomainError("REVIEWED_BATCH","批次已复核，请先退回复核再切换版本",409)
                # 已按新版封存的窗口不得因自动回退而静默改判旧版：降级需显式请求旧版，或批次已退回复核。
                if batch_version=="v2" and applied=="v1" and versioning.get("requested")!="v1" and current.get("decision")!="退回复核":
                    raise DomainError("VERSION_CONFLICT","批次已按新版封存，降级需显式请求旧版",409)
                # 同一窗口版本成功切换（如补齐复核标记后升级）：仍为同一批次，仅替换口径与结果。
                db.execute("UPDATE runs SET payload=?,applied_version=?,switch_failed=0 WHERE id=?",(json.dumps(payload,ensure_ascii=False),applied,run_id))
                _event(db,run_id,"VERSION_APPLIED",{"requested":versioning.get("requested"),"applied":applied,"previous":batch_version,"batch_version":applied,"detail":versioning.get("basis")})
    result=get(run_id)
    if result.get("last_attempt") is None:
        result["last_attempt"]={"requested":versioning.get("requested"),"applied":applied,"switch_failed":failed,"restored":False,"batch_version":applied,"detail":versioning.get("basis")}
    return result
def get(run_id):
    with connect() as db:
        row=_stored(db,run_id)
        if not row: raise DomainError("NOT_FOUND","批次不存在",404)
        result=_decode(row);result["last_attempt"]=_attempt_from_events(db,run_id)
    return result
def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None
def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d,"applied_version":a,"switch_failed":bool(f)} for i,v,d,a,f in db.execute("SELECT id,version,decision,applied_version,switch_failed FROM runs ORDER BY rowid DESC")]
def events(run_id):
    with connect() as db:
        if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
        return [{"kind":k,"detail":json.loads(d),"at":t} for k,d,t in db.execute("SELECT kind,detail,created_at FROM events WHERE run_id=? ORDER BY event_id",(run_id,))]
def raw_input(sha256):
    with connect() as db: row=db.execute("SELECT content FROM raw_inputs WHERE sha256=?",(sha256,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","原始扫描不存在",404)
    return row[0]
def raws(run_id):
    """批次登记过的全部原始扫描（只增不删），按首次登记顺序。"""
    with connect() as db:
        if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
        return [{"sha256":s,"first_seen":t} for s,t in db.execute("SELECT sha256,first_seen FROM run_raws WHERE run_id=? ORDER BY first_seen,rowid",(run_id,))]
def raw_for_run(run_id):
    """批次当前封存口径对应的原始扫描；清单摘要与下载内容必须一致以便核验。"""
    with connect() as db:
        row=db.execute("SELECT payload FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise DomainError("NOT_FOUND","批次不存在",404)
        sealed=(json.loads(row[0]).get("manifest") or {}).get("input_sha256")
        sha=sealed
        if sha and db.execute("SELECT 1 FROM raw_inputs WHERE sha256=?",(sha,)).fetchone():
            content=db.execute("SELECT content FROM raw_inputs WHERE sha256=?",(sha,)).fetchone()
            return sha,content[0]
        first=db.execute("SELECT sha256 FROM run_raws WHERE run_id=? ORDER BY first_seen,rowid LIMIT 1",(run_id,)).fetchone()
        if not first: raise DomainError("NOT_FOUND","原始扫描不存在",404)
        content=db.execute("SELECT content FROM raw_inputs WHERE sha256=?",(first[0],)).fetchone()
    if not content: raise DomainError("NOT_FOUND","原始扫描不存在",404)
    return first[0],content[0]
def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1:
            if not db.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("NOT_FOUND","批次不存在",404)
            raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)
