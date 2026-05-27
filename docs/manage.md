# Management

## Dependency Management

项目使用 `uv` 管理依赖，依赖列表在 `pyproject.toml` 的 `[project.dependencies]` 中。

### 安装依赖

```bash
uv sync
```

包含开发依赖（dev 组）：

```bash
uv sync --group dev
```

包含文档构建依赖：

```bash
uv sync --group docs
```

### 添加依赖

将依赖名添加到 `pyproject.toml` 的 `[project.dependencies]` 列表，然后运行 `uv sync`。

## Running Tests

```bash
uv run pytest
```

带覆盖率报告：

```bash
uv run pytest --cov
```

## Linting and Formatting

使用 `ruff` 进行 lint 和格式化。

检查 lint 错误：

```bash
uv run ruff check .
```

自动修复：

```bash
uv run ruff check . --fix
```

格式化代码：

```bash
uv run ruff format .
```

## 类型检查

```bash
uv run pyright
```

## 打包

```bash
uv run pyinstaller downloader.spec
```

## 文档构建

```bash
uv run mkdocs serve
```

生产构建：

```bash
uv run mkdocs build
```

版本化发布：

```bash
uv run mike deploy --push --update-aliases <version> latest
```
