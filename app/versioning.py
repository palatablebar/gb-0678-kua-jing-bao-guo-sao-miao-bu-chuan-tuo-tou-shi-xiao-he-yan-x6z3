"""整窗版本裁决：一个窗口只选一个版本，逐票只给依据，不逐票切换。"""
from app.config import SCHEMA_CURRENT,SCHEMA_LEGACY,SCHEMA_LABELS,VERSION_REQUEST_OPTIONS
from app.errors import DomainError
MARKED_TOKENS={"0","n","no","false","否","未复核","未审"}
def is_marked(value):
    text=str(value or "").strip()
    return bool(text) and text.casefold() not in MARKED_TOKENS
def resolve(schema,requested,total,marked):
    """返回整窗裁决。优先级：显式请求 > 自动判断；任何不满足新版条件的整窗一律回退旧版。"""
    if requested not in VERSION_REQUEST_OPTIONS: raise DomainError("BAD_VERSION","版本参数只能是 auto、v1 或 v2")
    unmarked=total-marked
    qualifies=schema==SCHEMA_CURRENT and total>0 and unmarked==0
    switch_failed=auto_fallback=False
    if requested==SCHEMA_CURRENT:
        if qualifies: applied=SCHEMA_CURRENT;basis="整窗全部扫描带复核标记，采用新版口径"
        else:
            applied=SCHEMA_LEGACY;switch_failed=True
            basis=("新版切换失败：整窗 %d/%d 条扫描缺少复核标记，恢复旧版口径，不把已发生扫描判成不完整" % (unmarked,total))
    elif requested==SCHEMA_LEGACY:
        applied=SCHEMA_LEGACY;basis="按请求采用旧版口径，整窗扫描不作新版完整性判定"
    elif qualifies:
        applied=SCHEMA_CURRENT;basis="整窗全部扫描带复核标记，自动采用新版口径"
    else:
        applied=SCHEMA_LEGACY;auto_fallback=True
        basis=("源文件无复核标记列，整窗采用旧版口径" if schema==SCHEMA_LEGACY
               else "整窗 %d/%d 条扫描缺少复核标记，自动回退旧版口径，不把已发生扫描判成不完整" % (unmarked,total))
    decision={"requested":requested,"header_schema":schema,"applied":applied,
              "label":SCHEMA_LABELS[applied],"basis":basis,"switch_failed":switch_failed,
              "auto_fallback":auto_fallback,"rows":total,"marked":marked,"unmarked":unmarked,
              "window":"整窗（单一版本）"}
    if switch_failed: decision["failure_detail"]=basis
    return decision
def row_basis(decision,raw_mark):
    """逐票适用依据：说明该票为何随整窗采用此版本，不构成独立版本选择。"""
    mark=str(raw_mark or "").strip();marked=is_marked(mark)
    if decision["applied"]==SCHEMA_CURRENT: return "新版：本票该扫描复核标记「%s」" % mark
    if decision["switch_failed"]: return "旧版：新版切换失败已恢复旧版，本票该扫描不按新版判不完整"
    if decision.get("auto_fallback"): return "旧版：整窗自动回退，本票该扫描%s复核标记（缺失不判不完整）" % ("有" if marked else "无")
    return "旧版：整窗旧版口径，本票该扫描%s复核标记" % ("有" if marked else "无")
def parcel_basis(decision,marked,total):
    """包裹级依据：把该票各扫描的复核情况汇总成一句话。"""
    if decision["applied"]==SCHEMA_CURRENT: return "新版：本票 %d 条扫描均带复核标记" % total
    if decision["switch_failed"]: return "旧版：新版切换失败已恢复旧版，本票 %d 条扫描不按新版判不完整" % total
    if decision.get("auto_fallback"): return "旧版：整窗自动回退，本票 %d 条扫描中 %d 条带复核标记（缺失不判不完整）" % (total,marked)
    return "旧版：整窗旧版口径，本票 %d 条扫描中 %d 条带复核标记（缺失不判不完整）" % (total,marked)
