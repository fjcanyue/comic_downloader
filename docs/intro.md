# Introduction

轻量级命令行动漫下载器，支持多种中文漫画网站。

## Features

- **多源搜索**: 同时搜索所有启用的漫画源，聚合结果展示
- **并行搜索**: 使用线程池并行执行多源搜索，提升速度
- **浏览器模式**: 支持三种 HTML 解析方式
  - **requests** — 纯 HTTP 请求，无需浏览器驱动
  - **SeleniumBase** — CDP 模式渲染，自动破解反爬
  - **CloakBrowser** — 高级反爬浏览器，支持指纹伪装
- **自动回退**: requests 模式收到 HTTP 403/429 时自动切换到 SeleniumBase
- **章节下载**: 支持全量下载和范围下载
- **下载续传**: 已存在的文件自动跳过，支持补零匹配
- **图片打包**: 下载完成后自动压缩为 ZIP 归档
- **驱动懒初始化**: 浏览器驱动仅在使用时创建，搜索/查看详情不强制依赖

## Basic Commands

| 命令 | 说明 |
|------|------|
| `source` | 选择漫画源（可选，默认自动匹配） |
| `s <keyword>` | 搜索动漫 |
| `i <index/url>` | 查看动漫详情 |
| `d <index/url>` | 全量下载动漫 |
| `v <options>` | 按范围下载章节 |
| `q` | 退出 |

## 支持的源

| 源 | 模块 | 浏览器模式 |
|----|------|------------|
| 摩锐漫画 | morui | CloakBrowser / SeleniumBase |
| 读漫屋 | dumanwu | requests |
| 漫蛙 | manhuagui | requests |
| 漫画站 | manhuazhan | requests |
| 漫画台 | thmh | requests |

已废弃的源（可通过完整 URL 访问）：伯牙漫画（boya）、动漫之家（dmzj）、猫 fly（maofly）。
