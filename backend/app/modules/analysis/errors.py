"""Analysis errors (§62): AI_ANALYSIS_FAILED, INVALID_AI_RESPONSE, …"""

from __future__ import annotations


class AnalysisError(Exception):
    """Machine-readable analysis failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
