"""Phase 6 render geometry + quality gate tests (pure, no ffmpeg binary)."""

import pytest

from app.modules.rendering.geometry import (
    build_ffmpeg_command,
    crop_geometry,
    parse_probe,
    quality_check,
)


# ------------------------------------------------------------------ crop geometry


def test_landscape_16x9_crops_center_slice() -> None:
    geo = crop_geometry(1920, 1080)
    assert geo["crop"] == "crop=608:1080:656:0"
    assert geo["scale"] == "scale=1080:1920"


def test_portrait_9x16_needs_no_crop() -> None:
    geo = crop_geometry(1080, 1920)
    assert geo["crop"] is None
    assert geo["scale"] is None


def test_720p_portrait_scales_only() -> None:
    geo = crop_geometry(720, 1280)
    assert geo["crop"] is None
    assert geo["scale"] == "scale=1080:1920"


def test_square_crops_vertical_slice() -> None:
    geo = crop_geometry(1080, 1080)
    assert geo["crop"] == "crop=608:1080:236:0"
    assert geo["scale"] == "scale=1080:1920"


def test_ultrawide_crops_centered() -> None:
    geo = crop_geometry(3840, 2160)
    assert geo["crop"] == "crop=1216:2160:1312:0"
    assert geo["scale"] == "scale=1080:1920"


def test_tall_portrait_crops_horizontal_slice() -> None:
    geo = crop_geometry(1080, 2400)
    assert geo["crop"] == "crop=1080:1920:0:240"
    assert geo["scale"] is None  # crop already yields the target frame


def test_odd_dimensions_stay_even() -> None:
    geo = crop_geometry(1921, 1081)
    crop = geo["crop"]
    assert crop is not None
    assert "crop=" in crop
    # even width and x for h264
    parts = crop.replace("crop=", "").split(":")
    assert int(parts[0]) % 2 == 0
    assert int(parts[2]) % 2 == 0


def test_crop_geometry_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        crop_geometry(0, 1080)
    with pytest.raises(ValueError):
        crop_geometry(1920, -1)


# ------------------------------------------------------------- ffmpeg command


def test_build_ffmpeg_command_args_and_cwd() -> None:
    cmd, cwd = build_ffmpeg_command(
        "/data/temp/videos/1/video.mp4",
        "/data/temp/renders/3/clip.mp4",
        clip_start=5.0,
        clip_duration=10.0,
        src_width=1920,
        src_height=1080,
    )
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "5.000"
    assert "-i" in cmd
    assert cmd[cmd.index("-t") + 1] == "10.000"
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "setpts=PTS-STARTPTS,crop=608:1080:656:0,scale=1080:1920,ass=subs.ass"
    assert cmd[cmd.index("-af") + 1] == "asetpts=PTS-STARTPTS"
    assert cmd[-1] == "/data/temp/renders/3/clip.mp4"
    assert cwd == "/data/temp/renders/3"


def test_build_ffmpeg_command_no_music_has_no_complex_graph() -> None:
    cmd, _ = build_ffmpeg_command(
        "/data/temp/videos/1/video.mp4",
        "/data/temp/renders/3/clip.mp4",
        clip_start=5.0,
        clip_duration=10.0,
        src_width=1920,
        src_height=1080,
    )
    assert "-filter_complex" not in cmd
    assert "-stream_loop" not in cmd
    assert cmd.count("-i") == 1


def test_build_ffmpeg_command_with_music() -> None:
    cmd, _ = build_ffmpeg_command(
        "/data/temp/videos/1/video.mp4",
        "/data/temp/renders/3/clip.mp4",
        clip_start=5.0,
        clip_duration=10.0,
        src_width=1920,
        src_height=1080,
        music_path="/data/music/track.mp3",
        music_volume=0.15,
    )
    # second looped input
    assert cmd.count("-i") == 2
    loop = cmd.index("-stream_loop")
    assert cmd[loop + 1] == "-1"
    assert cmd[loop + 2] == "-i"
    assert cmd[loop + 3] == "/data/music/track.mp3"
    # complex graph replaces -vf/-af and maps labelled outputs
    assert "-vf" not in cmd and "-af" not in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:v]setpts=PTS-STARTPTS,crop=608:1080:656:0,scale=1080:1920,ass=subs.ass[vout]" in fc
    assert "[1:a]volume=0.150," in fc
    assert "[a0][mus]amix=inputs=2:duration=first:dropout_transition=3[aout]" in fc
    assert cmd[cmd.index("-map") + 1] == "[vout]"
    assert cmd[cmd.index("-map") + 3] == "[aout]"


def test_build_ffmpeg_command_music_volume_clamped() -> None:
    cmd, _ = build_ffmpeg_command(
        "/v.mp4", "/o.mp4", 0.0, 5.0, 1080, 1920, music_path="/m.mp3", music_volume=2.5
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "volume=1.000" in fc
    cmd2, _ = build_ffmpeg_command(
        "/v.mp4", "/o.mp4", 0.0, 5.0, 1080, 1920, music_path="/m.mp3", music_volume=-1.0
    )
    assert "volume=0.000" in cmd2[cmd2.index("-filter_complex") + 1]


# ------------------------------------------------------------------ ffprobe


def test_parse_probe_reads_streams_and_format() -> None:
    info = parse_probe(
        {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": "1080", "height": "1920", "duration": "10.0"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"size": "123456", "duration": "10.1"},
        }
    )
    assert info["width"] == 1080
    assert info["height"] == 1920
    assert info["duration"] == 10.0
    assert info["size"] == 123456
    assert info["has_audio"] is True
    assert info["codec"] == "h264"


def test_parse_probe_no_video_stream() -> None:
    info = parse_probe({"streams": [], "format": {}})
    assert info["width"] is None
    assert info["height"] is None
    assert info["duration"] == 0.0
    assert info["size"] == 0
    assert info["has_audio"] is False


# ------------------------------------------------------------- quality gate


def test_quality_check_passes_good_short() -> None:
    passed, problems = quality_check(
        {"width": 1080, "height": 1920, "size": 50_000, "duration": 10.2},
        expected_duration=10.0,
    )
    assert passed is True
    assert problems == []


def test_quality_check_rejects_wrong_resolution() -> None:
    passed, problems = quality_check(
        {"width": 720, "height": 1280, "size": 50_000, "duration": 10.2},
        expected_duration=10.0,
    )
    assert passed is False
    assert any("width 720" in p for p in problems)


def test_quality_check_rejects_empty_and_bad_duration() -> None:
    passed, problems = quality_check(
        {"width": 1080, "height": 1920, "size": 0, "duration": 3.0},
        expected_duration=10.0,
    )
    assert passed is False
    assert any("empty" in p for p in problems)
    assert any("too short" in p for p in problems)
