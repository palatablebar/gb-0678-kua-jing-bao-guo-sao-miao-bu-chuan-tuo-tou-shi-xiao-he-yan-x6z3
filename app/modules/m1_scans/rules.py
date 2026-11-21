import csv,io
from app.config import HEADERS,REVIEW_COLUMN
from app.errors import DomainError
from app.reasons import reject
from app.versioning import is_marked,resolve,row_basis
def decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try: return raw.decode(encoding),encoding
        except UnicodeDecodeError: continue
    raise DomainError("ENCODING","无法识别文件编码")
def schema_of(header):
    for schema,candidate in HEADERS.items():
        if header==candidate: return schema
    return None
def _annotate(row,schema,decision):
    mark=str(row.get(REVIEW_COLUMN,"")).strip()
    row["_schema"]=schema;row["_review_mark"]=mark;row["_review_marked"]=is_marked(mark)
    row["_version"]=decision["applied"];row["_version_basis"]=row_basis(decision,mark)
def evaluate(raw,context=None):
    text,encoding=decode(raw)
    if not text: raise DomainError("EMPTY_FILE","文件为空")
    if not text.strip(): raise DomainError("BLANK_ONLY","全部为空行")
    stream=csv.reader(io.StringIO(text,newline=""));header=next(stream,None)
    schema=schema_of(header)
    if schema is None: raise DomainError("BAD_HEADER","表头不匹配")
    rows=[];bad=[];seen={};duplicate=blank=repeated=count=0
    try:
        for cells in stream:
            count+=1;line=stream.line_num
            if not cells or not any(c.strip() for c in cells): blank+=1;continue
            if cells==header: repeated+=1;continue
            row={"_line":line,"_sources":[line],"_raw":cells}
            if len(cells)!=len(header): bad.append(reject(row,"BAD_COLUMNS","列数不匹配"));continue
            row.update(dict(zip(header,[x.strip() for x in cells])))
            if not row[header[0]]: bad.append(reject(row,"EMPTY_VALUE","业务键为空"));continue
            key=row[header[0]]
            if key in seen:
                previous=seen[key]
                if cells==previous["_raw"]: duplicate+=1
                else: bad.append(reject(row,"DUPLICATE_CONFLICT","同键不同值"))
                continue
            seen[key]=row;rows.append(row)
    except csv.Error: raise DomainError("BAD_CSV","引号未闭合或文件损坏")
    if count==0: raise DomainError("HEADER_ONLY","仅有表头")
    if not rows and not bad: raise DomainError("BLANK_ONLY","全部为空行")
    # 版本只按整窗的采纳扫描裁决；隔离行记录其标记，但不得反向影响整窗版本。
    total=len(rows);marked=sum(1 for row in rows if is_marked(row.get(REVIEW_COLUMN,"")))
    requested=(context or {}).get("parameters",{}).get("version","auto")
    decision=resolve(schema,requested,total,marked)
    for row in rows: _annotate(row,schema,decision)
    for row in bad: _annotate(row,schema,decision)
    return {"rows":rows,"quarantine":bad,"versioning":decision,
            "metrics":{"input":count,"accepted":len(rows),"quarantine":len(bad),"duplicate":duplicate,"blank":blank,"repeated_headers":repeated,"encoding":encoding,"review_marked":marked,"review_unmarked":total-marked,"version":decision["applied"]}}
