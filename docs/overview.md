# Overview

## 测试

项目使用 `pytest` 进行测试。

### 测试目录

测试文件位于 `tests/` 目录，遵循标准 pytest 命名规范。

### 运行测试

```bash
uv run pytest
```

### 测试标记

- `slow`: 慢速测试，可用 `-m 'not slow'` 排除
- `integration`: 集成测试
- `unit`: 单元测试

### 覆盖率

```bash
uv run pytest --cov
```

HTML 覆盖率报告输出到 `htmlcov/`。

## 配置

pytest 配置在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 中：

```toml
[tool.pytest.ini_options]
addopts = "-ra -q -s --strict-markers --cov=downloader --cov-report=term-missing --cov-report html:htmlcov"
pythonpath = ["."]
markers = [
  "slow: marks tests as slow (deselect with '-m \"not slow\"')",
  "integration: marks tests as integration tests",
  "unit: marks tests as unit tests",
]
```
