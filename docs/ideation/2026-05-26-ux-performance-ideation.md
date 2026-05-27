---
date: 2026-05-26
topic: ux-performance
focus: 用户体验与性能优化
---

# Ideation: UX and Performance

## Codebase Context

这是一个 Python/Rich CLI 漫画下载器，核心路径是 `main.py` 的命令分发、
`downloader/shell.py` 的交互命令、`downloader/comic.py` 的通用下载流程，以及多个站点源实现。
默认启用源主要通过 HTTP 完成搜索和详情解析，但图片列表解析通常依赖 Selenium。

扫描中发现的主要杠杆点：

- 启动阶段原本总是初始化 WebDriver，即使用户只搜索、查看帮助或进入 HTTP-only 信息路径。
- 默认下载路径从 `__file__` 推导，源码运行时会落到项目父目录，和用户当前终端位置不一致。
- 下载图片失败后重跑时，即使本地已有完整图片，也会重新请求，浪费带宽和时间。
- 文档中存在 0-based 序号示例，但实际命令解析使用 1-based 序号。
- 全仓库 lint/type 检查存在较多历史问题，影响持续改进效率。

## Ranked Ideas

### 1. Lazy WebDriver Initialization
**Description:** 启动时只创建 HTTP session；只有驱动型搜索或下载解析图片前才初始化 Selenium，并将驱动注入当前源实例。  
**Rationale:** 明显减少启动等待，避免没有浏览器驱动的用户在非下载命令上被失败提示打断。  
**Downsides:** 需要各源声明下载是否依赖驱动，并确保下载前统一检查。  
**Confidence:** 95%  
**Complexity:** Medium  
**Status:** Explored / Implemented

### 2. Resumable Image Reuse
**Description:** `overwrite=False` 时复用已存在且非空的图片文件，避免重复请求。  
**Rationale:** 重跑失败章节时更快，也减少对目标站点的请求压力。  
**Downsides:** 只按文件存在和大小判断，不校验图片内容是否损坏。  
**Confidence:** 85%  
**Complexity:** Low  
**Status:** Explored / Implemented

### 3. CLI Defaults and Help
**Description:** 默认下载到当前工作目录，并增加 `--help` / `--debug` 等明确入口。  
**Rationale:** 命令行工具应服从用户当前目录直觉；帮助输出避免误把 `--help` 当作下载路径。  
**Downsides:** 默认路径变化可能影响依赖旧行为的少数用户。  
**Confidence:** 90%  
**Complexity:** Low  
**Status:** Explored / Implemented

### 4. Search Result Feedback
**Description:** 搜索结果表展示结果数和耗时；无结果时直接给出明确提示。  
**Rationale:** 用户可以判断搜索是否完成、是否无结果，而不是只看到空表。  
**Downsides:** 无明显缺点。  
**Confidence:** 90%  
**Complexity:** Low  
**Status:** Explored / Implemented

### 5. Source Health and Capability Metadata
**Description:** 为每个源声明启用状态、是否 deprecated、是否需要驱动、搜索/下载能力和最近验证状态。  
**Rationale:** 后续可以在 `source` 和搜索结果里提示站点状态，减少用户尝试失效源的成本。  
**Downsides:** 需要维护站点健康信息，可能过期。  
**Confidence:** 75%  
**Complexity:** Medium  
**Status:** Unexplored

### 6. Typed Context and Parser Cleanup
**Description:** 给 `Context`、`Comic` 模型和源接口补强类型，拆分大型 `info`/`download` 方法。  
**Rationale:** 当前 pyright 全量检查被大量历史类型问题阻塞，影响后续安全重构。  
**Downsides:** 工作量较大，需要分源逐步迁移，避免一次性重构过宽。  
**Confidence:** 80%  
**Complexity:** High  
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | 全面改成异步下载 | 当前站点解析和 Selenium 调用仍是同步模型，改动范围大，收益不如先做断点续跑和懒加载。 |
| 2 | 重写为图形界面 | 与现有 CLI 定位不一致，成本高且不直接解决当前性能热点。 |
| 3 | 自动校验所有站点可用性 | 需要外部网络和站点稳定性假设，适合后续做独立健康检查命令。 |
| 4 | 下载后删除图片目录只保留 zip | 可能破坏用户检查/恢复场景，需要先确认产品语义。 |
| 5 | 为所有源统一修 lint | 有价值，但会触及大量旧代码，适合单独批次处理。 |

## Session Log

- 2026-05-26: Initial ideation and implementation - 10 candidates considered, 6 survived, 4 implemented.
