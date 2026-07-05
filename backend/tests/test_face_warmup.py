from unittest.mock import MagicMock, patch

from pipeline import face_tracker


def test_warmup_face_analyzer_loads_model_and_runs_dummy_inference():
    mock_analyzer = MagicMock()

    with patch.object(
        face_tracker,
        "get_face_analyzer",
        return_value=mock_analyzer,
    ):
        face_tracker.warmup_face_analyzer()

    mock_analyzer.get.assert_called_once()
    dummy_frame = mock_analyzer.get.call_args.args[0]
    assert dummy_frame.shape == (320, 320, 3)
