from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


class HtmlExtractionMixin:
    logger: Any

    def parse_xpath_list(
        self,
        root: Any,
        xpath: str,
        extract_map: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        """Extract a list of mapped values from matching XPath nodes."""
        results: list[dict[str, Any]] = []
        try:
            nodes = root.xpath(xpath)
            results.extend(self._extract_xpath_item(node, extract_map) for node in nodes)
        except Exception as exc:
            self.logger.error('XPath解析失败: {xpath}, 错误: {error}', xpath=xpath, error=exc)
        return results

    def _extract_xpath_item(
        self,
        node: Any,
        extract_map: Mapping[str, str],
    ) -> dict[str, Any]:
        return {
            key: self._extract_xpath_value(node, key, expression)
            for key, expression in extract_map.items()
        }

    def _extract_xpath_value(self, node: Any, key: str, expression: str) -> Any:
        try:
            if expression.startswith('./@'):
                values = node.xpath(expression)
                value = values[0] if values else None
                result = value.strip() if isinstance(value, str) else value
            elif expression == './text()':
                result = node.text.strip() if node.text else None
            else:
                values = node.xpath(expression)
                text_node = values[0] if values else None
                if isinstance(text_node, str):
                    result = text_node.strip()
                elif text := getattr(text_node, 'text', None):
                    result = text.strip()
                else:
                    result = text_node
            return result
        except Exception as exc:
            self.logger.debug('提取 {key} 时出错: {error}', key=key, error=exc)
            return None

    _JS_DANGEROUS_PATTERNS = re.compile(
        r'(?:'
        r'(?<!\w)eval\s*\('
        r'|(?<!\w)Function\s*\('
        r'|(?<!\w)import\s*\('
        r'|document\.cookie'
        r'|localStorage'
        r'|sessionStorage'
        r'|XMLHttpRequest'
        r'|fetch\s*\('
        r'|navigator\.sendBeacon'
        r')',
    )

    def execute_js_safely(self, driver: Any, js_code: str | None, fallback: Any = None) -> Any:
        """Execute trusted extraction JavaScript after rejecting active-network patterns."""
        try:
            if not js_code:
                self.logger.warning('空的JS代码')
                return fallback
            if self._JS_DANGEROUS_PATTERNS.search(js_code):
                self.logger.warning('潜在不安全JS代码被阻止: {js_code}', js_code=js_code[:200])
                return fallback
            return driver.execute_script(js_code)
        except Exception as exc:
            self.logger.error('JS执行失败: {js_code}, 错误: {error}', js_code=js_code, error=exc)
            return fallback
