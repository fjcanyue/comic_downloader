# Management

This guide covers some common project management tasks.

## Dependency Management

This project uses `uv` for dependency management. The dependencies are listed in `pyproject.toml`.

### Installing dependencies

To install all dependencies, including development dependencies, run:

```bash
uv pip install -e .[dev,docs]
```

### Adding a dependency

To add a new dependency, add it to the `dependencies` list in `pyproject.toml` and then run the install command again.

## Running tests

This project uses `pytest` for testing. To run the tests, use the following command:

```bash
pytest
```

To run the tests with coverage, use:

```bash
pytest --cov
```

## Linting and Formatting

This project uses `ruff` for linting and formatting.

To check for linting errors, run:

```bash
ruff check .
```

To automatically fix linting errors, run:

```bash
ruff check . --fix
```

To format the code, run:

```bash
ruff format .
```
