"""Phase 7 Drive-output tests: remote path convention + payload field."""

from app.modules.rendering.models import ClipRender
from app.modules.rendering.service import render_payload
from app.modules.storage.constants import CLIPS_FOLDER, render_remote_path


def test_render_remote_path_convention() -> None:
    assert render_remote_path(12, 7) == f"{CLIPS_FOLDER}/12/clip-7.mp4"


def test_render_remote_path_unique_per_candidate() -> None:
    assert render_remote_path(12, 7) != render_remote_path(12, 8)


def test_render_remote_path_groups_by_video() -> None:
    assert render_remote_path(12, 7).startswith(f"{CLIPS_FOLDER}/12/")


def test_render_payload_includes_remote_path() -> None:
    render = ClipRender(
        candidate_id=7,
        video_id=12,
        status="rendered",
        local_path="/data/temp/renders/7/clip.mp4",
        remote_path=f"{CLIPS_FOLDER}/12/clip-7.mp4",
        filesize=1024,
        width=1080,
        height=1920,
        duration=10.5,
        quality_passed=True,
    )
    payload = render_payload(render)
    assert payload["remote_path"] == f"{CLIPS_FOLDER}/12/clip-7.mp4"
    assert payload["quality_passed"] is True


def test_render_payload_remote_path_none_for_local_only() -> None:
    render = ClipRender(candidate_id=7, video_id=12, status="rendered")
    assert render_payload(render)["remote_path"] is None
