"""DeepSeekProvider — clip analysis via the DeepSeek chat API (§17, §18, §56).

DeepSeek's API is OpenAI-compatible. Only transcript text is sent — never
video frames (§55 cost optimization). Output is validated by the analysis
service (Pydantic) with a single retry on invalid JSON (§18).
"""

from __future__ import annotations

import json

import requests
import structlog

from app.core.config import settings
from app.modules.analysis.errors import AnalysisError
from app.providers.base import AIProvider

logger = structlog.get_logger(__name__)

API_URL = "https://api.deepseek.com/chat/completions"

SYSTEM_PROMPT = """You are an expert short-form video editor for YouTube Shorts.

Your task is to analyze the provided timestamped transcript and select the
3–5 strongest moments for standalone YouTube Shorts.

IMPORTANT:
- Think internally, but DO NOT output your reasoning.
- Return the final JSON immediately.
- Do not explain your analysis.
- Do not include markdown.
- Do not include code fences.
- The response MUST contain a non-empty "clips" array.
- Select 3–5 valid clips whenever the transcript contains enough material.

A clip should:
- work for a viewer who has NOT seen the long video
- be 15–60 seconds when possible
- have a strong hook
- contain a clear insight, story, emotion, or payoff
- make sense on its own

Evaluate:
- hook_score
- content_score
- context_score
- emotion_score
- standalone_score
- retention_score

Rules:
- NEVER cut mid-sentence.
- Use exact segment boundaries from the transcript.
- start_time and end_time must correspond to transcript segment boundaries.
- All scores must be integers from 0 to 100.
- start_time and end_time are seconds.

Return ONLY this JSON structure:

{
  "clips": [
    {
      "start_time": 0.0,
      "end_time": 30.0,
      "title": "Short title",
      "hook": "Short hook",
      "reason": "Why this moment works",
      "hook_score": 90,
      "content_score": 90,
      "context_score": 85,
      "emotion_score": 90,
      "standalone_score": 85,
      "retention_score": 90
    }
  ]
}
"""


def build_analysis_prompt(transcript: dict, max_clips: int = 5) -> str:
    """Serialize the transcript for the AI, bounded to keep cost low (§55)."""
    segments = transcript.get("segments", [])
    # Cap payload: ~20k chars of transcript text is plenty for analysis.
    total = 0
    trimmed = []
    for seg in segments:
        text = seg.get("text", "")
        if total + len(text) > 20_000:
            break
        total += len(text)
        trimmed.append(seg)
    payload = {
        "language": transcript.get("language"),
        "duration_seconds": transcript.get("duration"),
        "segments": trimmed,
    }
    return (
        f"Analyze this transcript and return up to {max_clips} clip candidates "
        f"as JSON. Transcript:\n{json.dumps(payload, ensure_ascii=False)}"
    )


class DeepSeekProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or settings.deepseek_api_key
        self._model = model or settings.deepseek_model

    def _chat_json(self, user_content: str, system_prompt: str = SYSTEM_PROMPT) -> dict:
        try:
            resp = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 8000,
                    "response_format": {"type": "json_object"},
                },
                timeout=120,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.RequestException as exc:
            raise AnalysisError("AI_ANALYSIS_FAILED", f"DeepSeek request failed: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise AnalysisError(
                "INVALID_AI_RESPONSE", f"Unexpected DeepSeek response: {exc}"
            ) from exc

    def analyze_transcript(self, transcript: dict) -> dict:
        prompt = build_analysis_prompt(transcript, settings.max_clips_per_video)
        return self._chat_json(prompt)

    def rank_clips(self, clips: list[dict]) -> list[dict]:
        return sorted(clips, key=lambda c: c.get("score", 0), reverse=True)

    def generate_metadata(self, clip: dict) -> dict:
        prompt = (
            "Write a YouTube Shorts title, description, hashtags and tags for this clip. "
            f"Return JSON: {{\"title\":\"\",\"description\":\"\",\"hashtags\":[],\"tags\":[]}}.\n"
            f"Clip: {json.dumps(clip, ensure_ascii=False)}"
        )
        return self._chat_json(
            prompt,
            system_prompt=(
                "You write accurate, non-clickbait YouTube Shorts metadata "
                "(§33). Return only valid JSON."
            ),
        )

    def generate_hook(self, clip: dict) -> str:
        prompt = (
            "Write a short hook text (max 60 chars, uppercase-friendly) for a "
            f"YouTube Short based on this clip. Clip: {json.dumps(clip, ensure_ascii=False)}"
        )
        result = self._chat_json(prompt, system_prompt="Return only plain text, no JSON.")
        return str(result).strip() if isinstance(result, str) else str(result)
