"""Rendering errors (Phase 6)."""

from __future__ import annotations


class RenderError(Exception):
    """Raised when a clip cannot be rendered; carries a stable error code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
