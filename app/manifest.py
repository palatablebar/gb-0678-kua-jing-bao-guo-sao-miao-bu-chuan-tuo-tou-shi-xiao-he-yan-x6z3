import csv,hashlib,io,json,time
from datetime import datetime,timezone
from app.config import RULE_VERSION,REVIEW_COLUMN,HEADERS
# 请求版本不参与批次身份：同一窗口数据无论请求 auto 还是 v2，都应落到同一份正式批次；
# 真正采用的版本记入清单，切换失败则保持旧版批次不变。
IDENTITY_IGNORED=("version",)
def identity_params(params=None):
    return {k:v for k,v in (params or {}).items() if k not in IDENTITY_IGNORED}
def _decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try: return raw.decode(encoding)
        except UnicodeDecodeError: continue
    return None
def window_content(raw):
    """整窗身份只看业务内容：表头去复核标记列、去BOM、统一编码与行序列化。
    因此旧版文件与升级后带复核标记的同一窗口文件命中同一批次。"""
    text=_decode(raw)
    if text is None: return None
    reader=csv.reader(io.StringIO(text,newline=""));header=None
    try: header=next(reader,None)
    except csv.Error: return None
    if header is None or list(header) not in HEADERS.values(): return None
    drop=header.index(REVIEW_COLUMN) if REVIEW_COLUMN in header else None
    canonical=[cell for i,cell in enumerate(header) if i!=drop]
    lines=[json.dumps(canonical,ensure_ascii=False)]
    try:
        for cells in reader:
            if drop is not None and len(cells)>drop: cells=cells[:drop]+cells[drop+1:]
            lines.append(json.dumps([cell.strip() for cell in cells],ensure_ascii=False))
    except csv.Error: return None
    return "\n".join(lines).encode()
def window_key(raw):
    canonical=window_content(raw)
    return (raw,False) if canonical is None else (canonical,canonical!=raw)
def digest(raw,params=None):
    encoded=json.dumps(identity_params(params),sort_keys=True,ensure_ascii=False)
    key,_=window_key(raw)
    return hashlib.sha256(key+encoded.encode()+RULE_VERSION.encode()).hexdigest()
def manifest(raw,params,started,versioning=None):
    versioning=versioning or {}
    key,normalized=window_key(raw)
    return {"input_sha256":hashlib.sha256(raw).hexdigest(),"rule_version":RULE_VERSION,"parameters":params,
            "window_sha256":hashlib.sha256(key).hexdigest(),"window_normalized":normalized,
            "applied_version":versioning.get("applied"),"header_schema":versioning.get("header_schema"),
            "requested_version":versioning.get("requested"),"version_basis":versioning.get("basis"),
            "switch_failed":bool(versioning.get("switch_failed")),
            "generated_at":datetime.now(timezone.utc).isoformat(),"elapsed_ms":round((time.monotonic()-started)*1000,2)}
