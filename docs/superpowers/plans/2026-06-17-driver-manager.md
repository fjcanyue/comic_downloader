# Driver Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move browser driver lifecycle out of `downloader.shell.Context` into `downloader.browser.manager.DriverManager`.

**Architecture:** `DriverManager` owns driver cache, mode/headless resolution, initialization, and cleanup. `Context` remains the shell runtime state module and delegates its existing driver-related interface to `DriverManager` for compatibility.

**Tech Stack:** Python 3.10, Selenium, SeleniumBase, CloakBrowser adapter, pytest, Ruff.

---

## File Structure

- Create `downloader/browser/manager.py`: driver lifecycle module.
- Modify `downloader/shell.py`: remove driver initialization implementation and delegate to `DriverManager`.
- Add `tests/test_driver_manager.py`: focused tests for the new module.
- Modify `tests/test_shell_driver_lifecycle.py`: update tests that monkeypatch `Context` internals so they assert compatibility delegation instead.

## Task 1: DriverManager Module

**Files:**
- Create: `downloader/browser/manager.py`
- Test: `tests/test_driver_manager.py`

- [ ] **Step 1: Write failing tests**

Add tests that import `DriverManager`, construct it with a quiet presenter, and assert lazy initialization, cache reuse, profile cache key resolution, SeleniumBase routing, and cleanup.

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk uv run pytest tests/test_driver_manager.py -q`

Expected: FAIL because `downloader.browser.manager` does not exist.

- [ ] **Step 3: Implement `DriverManager`**

Move the driver lifecycle implementation from `Context` into `DriverManager`. Keep behaviour equivalent: same driver modes, cache keys, output messages, driver classes, and cleanup handling.

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run pytest tests/test_driver_manager.py -q`

Expected: PASS.

## Task 2: Context Delegation

**Files:**
- Modify: `downloader/shell.py`
- Test: `tests/test_shell_driver_lifecycle.py`

- [ ] **Step 1: Write failing compatibility test**

Add a test asserting `Context.ensure_driver()` delegates to `context.driver_manager.ensure_driver()` and `Context.driver` exposes `driver_manager.current_driver`.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run pytest tests/test_shell_driver_lifecycle.py::test_context_driver_methods_delegate_to_driver_manager -q`

Expected: FAIL because `Context` has no `driver_manager` delegation yet.

- [ ] **Step 3: Refactor `Context`**

Create `self.driver_manager = DriverManager(self.presenter)`. Replace `Context` driver lifecycle method bodies with delegation, and expose `driver`/`drivers` properties backed by manager state.

- [ ] **Step 4: Run focused shell lifecycle tests**

Run: `rtk uv run pytest tests/test_shell_driver_lifecycle.py tests/test_driver_manager.py -q`

Expected: PASS.

## Task 3: Verification

**Files:**
- Existing project files only.

- [ ] **Step 1: Run focused tests**

Run: `rtk uv run pytest tests/test_driver_manager.py tests/test_shell_driver_lifecycle.py tests/test_main_cli.py -q`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `rtk uv run pytest -q`

Expected: PASS.

- [ ] **Step 3: Run lint**

Run: `rtk uv run ruff check downloader tests main.py`

Expected: PASS.

## Self-Review

Spec coverage: The plan creates `DriverManager`, keeps `Context` compatibility, does not change command or download behaviour, and verifies the driver cache and cleanup semantics.

Placeholder scan: No placeholder implementation details remain; the tests and refactor steps name exact files and commands.

Type consistency: `DriverManager`, `driver_manager`, `current_driver`, `drivers`, `ensure_driver`, `get_driver`, `init_driver`, and `driver_cache_key` names are consistent across tasks.
