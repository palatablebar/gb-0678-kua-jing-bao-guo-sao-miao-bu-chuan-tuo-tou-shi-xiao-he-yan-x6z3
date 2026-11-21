from pathlib import Path
import os
ROOT=Path(__file__).resolve().parent.parent
DATA_DIR=Path(os.environ.get("DATA_DIR", "/tmp/parcelsla"))
TITLE='跨境包裹扫描补传与妥投时效核验'
SHORT='parcelsla'
COLUMNS=['scan_id', 'parcel', 'node', 'event_time', 'received_time', 'destination', 'promised_hours', 'declared_value', 'reported', 'note']
# 承运商升级后新增复核标记列；旧版文件没有该列，因此两种表头都必须能读入。
REVIEW_COLUMN='review_mark'
SCHEMA_LEGACY='v1'
SCHEMA_CURRENT='v2'
HEADERS={SCHEMA_LEGACY: COLUMNS, SCHEMA_CURRENT: COLUMNS+[REVIEW_COLUMN]}
SCHEMA_LABELS={SCHEMA_LEGACY: '旧版', SCHEMA_CURRENT: '新版'}
VERSION_REQUEST_OPTIONS=('auto', SCHEMA_LEGACY, SCHEMA_CURRENT)
MODULES=[('scans', '扫描采信'), ('nodes', '节点映射'), ('timezones', '时区归整'), ('paths', '路径裁决'), ('timeliness', '时效计算'), ('compensation', '赔付对账'), ('archives', '批次归档')]
RULE_VERSION="2026.11.17-r1"
