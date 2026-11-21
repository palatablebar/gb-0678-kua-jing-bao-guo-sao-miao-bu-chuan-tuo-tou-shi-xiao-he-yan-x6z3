from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    versioning=context.get("versioning") or {}
    if versioning:
        # 整窗只允许一个版本：任一逐票口径偏离整窗裁决，直接拒绝，避免混用两套解释。
        applied=versioning.get("applied")
        versions={row.get("_version") for row in rows if row.get("_version")} | {row.get("_version") for row in bad if row.get("_version")}
        if len(versions)>1: raise DomainError("VERSION_MIXED","整窗版本不一致，不能结算")
        if versions and versions!={applied}: raise DomainError("VERSION_MISMATCH","逐票口径与整窗裁决不一致，不能结算")
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    return {"rows":output,"quarantine":[],"metrics":m}
