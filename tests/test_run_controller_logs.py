"""Log level inference for dashboard subprocess streams."""

from applypilot.orchestration.run_controller import infer_log_level


def test_info_prefix_on_stderr_is_info_not_error():
    line = '23:40:46 - INFO - TD Bank: searching "software engineer"...'
    assert infer_log_level(line, "stderr") == "info"


def test_error_prefix_stays_error():
    line = "23:40:46 - ERROR - JobSpy crawl failed: No module named 'jobspy'"
    assert infer_log_level(line, "stderr") == "error"


def test_warning_prefix():
    line = "12:00:00 - WARNING - rate limited"
    assert infer_log_level(line, "stdout") == "warning"


def test_plain_stderr_without_level_is_warning():
    assert infer_log_level("something odd on stderr", "stderr") == "warning"
