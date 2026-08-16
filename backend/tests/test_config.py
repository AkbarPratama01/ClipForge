"""Configuration tests."""

from app.core.config import Settings


def test_defaults() -> None:
    s = Settings()
    assert s.app_name == "ClipForge"
    assert s.app_version == "0.1.0"


def test_phase11_music_defaults() -> None:
    s = Settings()
    assert s.background_music is False
    assert s.background_music_path == ""
    assert s.background_music_volume == 0.15


def test_cors_origin_list_parsing() -> None:
    s = Settings(cors_origins="http://a.example, http://b.example ,")
    assert s.cors_origin_list == ["http://a.example", "http://b.example"]


def test_cors_origin_list_empty() -> None:
    s = Settings(cors_origins=" , ")
    assert s.cors_origin_list == []
