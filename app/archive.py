import csv,hashlib,io,json
from app.errors import DomainError
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence","applied_version","schema","parcel","version_basis"])
    meta=run["manifest"];versioning=run.get("versioning") or {}
    applied=meta.get("applied_version") or versioning.get("applied") or ""
    rows=run["stages"][-1]["rows"]
    # 结算要求整窗只出一份正式批次：导出前再确认口径唯一，且与清单记录一致。
    versions={row.get("_version") for row in rows if row.get("_version")}
    if len(versions)>1 or (versions and versions!={applied}): raise DomainError("VERSION_MIXED","整窗版本不一致，不能导出正式批次",409)
    digest=hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    for row in rows:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False),applied,row.get("_schema",""),row.get("parcel",""),row.get("_version_basis","")])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False),applied,row.get("_schema",""),row.get("parcel",""),row.get("_version_basis","")])
    # 页脚清单行：同一批次唯一、口径唯一，便于人工核对。
    writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"manifest","[]","",json.dumps({"applied_version":applied,"version_basis":versioning.get("basis"),"switch_failed":bool(versioning.get("switch_failed")),"records":len(rows),"sha256":digest},ensure_ascii=False),applied,"","",""])
    return "﻿"+stream.getvalue()
