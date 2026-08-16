"""Error raised when a required setting is missing — maps to a 4xx API error."""

from __future__ import annotations


class UnsetSettingError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
