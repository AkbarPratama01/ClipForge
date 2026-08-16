"""AI provider factory (§56) — ``AI_PROVIDER`` selects the backend."""

from __future__ import annotations

from app.core.config import settings
from app.modules.analysis.errors import AnalysisError
from app.providers.base import AIProvider


def get_ai_provider() -> AIProvider:
    provider = settings.ai_provider
    if provider == "mock":
        from app.providers.ai.mock import MockAIProvider

        return MockAIProvider()

    if provider == "deepseek":
        if not settings.deepseek_api_key:
            raise AnalysisError(
                "AI_NOT_CONFIGURED",
                "Set DEEPSEEK_API_KEY in .env, or use AI_PROVIDER=mock for a demo without a key.",
            )
        from app.providers.ai.deepseek import DeepSeekProvider

        return DeepSeekProvider()

    raise AnalysisError(
        "AI_PROVIDER_UNSUPPORTED",
        f"Unknown AI_PROVIDER={provider!r} (supported: deepseek, mock)",
    )
