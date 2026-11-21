# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

`/api/runs`与`/api/upload`接受`version`（auto/v1/v2，默认auto），返回体带`versioning`（applied、basis、switch_failed、marked/unmarked）与`manifest.applied_version`。`/api/runs/<id>/events`给出批次事件，`/api/runs/<id>/raws`列出保留的原始扫描摘要，`/api/runs/<id>/raws/<sha256>`取回指定原文，`/api/runs/<id>/raw`取回与清单摘要一致的原文。
