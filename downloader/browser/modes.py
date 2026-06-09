from __future__ import annotations

from typing import Any, Literal, cast

REQUESTS_MODE = 'requests'
SELENIUMBASE_MODE = 'seleniumbase'
CLOAKBROWSER_MODE = 'cloakbrowser'

BrowserModeName = Literal['requests', 'seleniumbase', 'cloakbrowser']

SUPPORTED_BROWSER_MODES = frozenset(
    {
        REQUESTS_MODE,
        SELENIUMBASE_MODE,
        CLOAKBROWSER_MODE,
    }
)


def normalize_browser_mode(value: Any) -> BrowserModeName:
    mode = str(value or REQUESTS_MODE).strip().lower()
    if mode not in SUPPORTED_BROWSER_MODES:
        supported = ', '.join(sorted(SUPPORTED_BROWSER_MODES))
        raise ValueError(f'Unsupported browser mode "{mode}". Supported modes: {supported}.')
    return cast(BrowserModeName, mode)


def is_driver_backed_browser_mode(value: Any) -> bool:
    return normalize_browser_mode(value) in {SELENIUMBASE_MODE, CLOAKBROWSER_MODE}
