"""Provider abstraction layer.

Interfaces live in :mod:`app.providers.base`; concrete implementations
(Google Drive, DeepSeek, local Whisper, YouTube, ...) land in later phases.
Switching providers must never require changing application code — only the
``*_PROVIDER`` environment variable.
"""
