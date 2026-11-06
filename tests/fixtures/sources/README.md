# 源详情解析样本

原有 `*-info.html`、详情 API JSON 和 `structure-changed.html` 是根据仓库现有 XPath、适配器和 API 字段契约手工编写的**合成回归样本**，
不是从线上站点抓取的快照，也不是已验证站点当前结构的脱敏副本。作品名、作者、编号和
内容均为测试数据，不含用户 Cookie、令牌或真实漫画图片。

每个默认启用源提供一个 `*-info.html`。`manhuafree-api.json` 对应详情 API，
`dumanwu-more.json` 对应追加章节 API。`structure-changed.html` 表示无法识别的详情结构。
测试在基础样本上确定性修改缺失字段、无效链接、重复链接、分组和 API 失败，
验证嵌套文本、链接解析、顺序、部分保留和诊断；所有 HTTP 请求由内存响应接管。

新增默认源时，应补充对应样本及期望值。将来引入真实脱敏快照时，另行记录采集日期、
来源地址、去标识步骤和适用范围，不应将这些合成样本重新标注为线上证据。

`manhuagui-search-live-page1.html` 与 `manhuagui-search-live-page2.html` 是公开搜索页的真实精简结构样本，
采集于 2026-11-06 23:49（北京时间），关键词为“海”。各页原有 10 条，仅保留前两条和下一页链接；
移除了图片、脚本、iframe、事件属性和作品简介正文，保留公开书目名称、作者与链接等解析字段。
`captured-pagination` 外层容器由采集脚本添加，其内部下一页链接来自原页面。
完整来源 URL、UTC 采集时间、HTTP 状态、条目数与处理说明记录在
`manhuagui-search-live-provenance.json`；这些样本不是完整页面副本，也不代表详情或图片下载可用。
