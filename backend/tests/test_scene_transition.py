from pipeline.scene_transition import _build_video_context_prompt, _format_duration
from utils.ffmpeg_paths import MediaProbeInfo


def _media_info(duration: float = 119.456) -> MediaProbeInfo:
    return MediaProbeInfo(
        duration=duration,
        has_audio=True,
        metadata={
            "duration": round(duration, 2),
            "fps": 29.97,
            "width": 1920,
            "height": 1080,
        },
        stderr="",
    )


def test_format_duration_uses_unambiguous_clock_notation():
    assert _format_duration(119.456) == "00:01:59.456"
    assert _format_duration(3_661.25) == "01:01:01.250"


def test_video_context_prompt_includes_authoritative_timestamp_bounds():
    prompt = _build_video_context_prompt(_media_info())

    assert "Exact playback duration: 119.456 seconds" in prompt
    assert "Duration in HH:MM:SS.mmm: 00:01:59.456" in prompt
    assert "0.000 through 119.456" in prompt
    assert "elapsed seconds from the very first frame" in prompt
    assert "not as MM:SS" in prompt
    assert "1920x1080" in prompt
    assert "29.97 fps" in prompt
    assert "Audio stream present: yes" in prompt
