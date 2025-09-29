# Overview

This project uses `pytest` for testing.

## Test Directory

The tests are located in the `tests/` directory. The tests follow the standard `pytest` naming conventions.

## Running Tests

To run the tests, use the following command:

```bash
pytest
```

## Configuration

The `pytest` configuration is located in the `pyproject.toml` file under the `[tool.pytest.ini_options]` section.

```toml
[tool.pytest.ini_options]
minversion = "6.0"
testpaths = ["tests", "integration"]
```
