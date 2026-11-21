from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app import store
def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=stage["rows"]
        # 旧库批次可能没有版本裁决信息：回退展示记录版本，不让页面报错。
        versioning=run.get("versioning") or {"applied":run.get("applied_version") or "v1","label":"旧版","basis":"该批次早于版本裁决，按记录时的规则版本展示","requested":"auto","switch_failed":bool(run.get("switch_failed"))}
        last_attempt=run.get("last_attempt")
        columns=[['scan_id', 'parcel', 'node', 'event_time', 'received_time', '_review_mark', '_version', '_version_basis'], ['scan_id', 'parcel', 'node', 'destination', 'zone'], ['scan_id', 'parcel', 'event_utc', 'received_utc', 'upload_lag_hours'], ['parcel', 'accepted_at', 'delivered_at', 'delivery_uploaded_at', 'scan_count', 'path'], ['parcel', 'accepted_at', 'delivered_at', 'working_hours', 'promised_hours', 'late_hours', 'expected', 'sla'], ['parcel', 'expected', 'reported', 'difference', 'status', '_version_basis'], ['parcel', 'delivered_at', 'sla', 'expected', 'status']][index]
        labels={'scan_id': '扫描号', 'parcel': '包裹号', 'node': '节点', 'event_time': '发生时间', 'received_time': '上传时间', 'destination': '目的地', 'zone': '时区', 'event_utc': '发生 UTC', 'received_utc': '上传 UTC', 'upload_lag_hours': '补传时差 / h', 'accepted_at': '收件 UTC', 'delivered_at': '妥投 UTC', 'delivery_uploaded_at': '妥投上传 UTC', 'scan_count': '扫描数', 'path': '节点路径', 'working_hours': '计时 / h', 'promised_hours': '承诺 / h', 'late_hours': '超时 / h', 'expected': '赔付 / 元', 'sla': '时效结论', 'reported': '申报 / 元', 'difference': '差额 / 元', 'status': '对账结论', 'accepted': '采纳扫描', 'late_uploads': '迟到上传', 'parcels': '包裹数', 'late_parcels': '超时包裹', 'compensation': '赔付合计', 'delivered': '妥投数', 'path_errors': '路径异常', 'records': '归档数', 'source_lines': '源行数', 'sha256': '摘要', 'ready': '可归档', 'differences': '差异数', '_review_mark': '复核标记', '_version': '适用版本', '_version_basis': '逐票适用依据', 'review_marked': '有复核标记', 'review_unmarked': '无复核标记', 'version': '整窗版本'}
        for key,label in {'accepted_inputs': '采纳来源行', 'quarantine_inputs': '隔离来源行', 'output_records': '结果记录', 'input': '输入行', 'excluded': '排除行', 'balanced': '行数平衡', 'expected_total': '预期合计', 'reported_total': '申报合计', 'differences': '差异项', 'blank': '空行', 'repeated_headers': '分段表头', 'encoding': '编码', 'duplicate': '重复行', 'quarantine': '隔离行', 'accepted': '采纳行', 'sha256': '校验摘要', 'ready': '可归档'}.items(): labels.setdefault(key,label)
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,columns=columns[:12],history=store.history(),labels=labels,versioning=versioning,last_attempt=last_attempt,events=store.events(run["run_id"]))
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
