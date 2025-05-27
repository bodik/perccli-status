"""perccli_status tests"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perccli_status import main as perccli_status_main


@pytest.fixture(autouse=True)
def patch_shutil_which():
    """patch shutil which"""

    with patch("shutil.which", Mock(return_value="/usr/bin/dummy")):
        yield


def mock_perccli_commands(outputs):
    """mock factory"""

    tests_dir = Path(__file__).resolve().parent
    return patch(
        "subprocess.check_output",
        Mock(
            side_effect=[
                Path(f"{tests_dir}/{item}").read_text(encoding="utf-8") for item in outputs
            ]
        ),
    )


def test_run_v8():
    """test run"""

    mock_outputs = [
        "output_8.4.0.22_version.txt",
        "output_8.4.0.22_controllers_ok.json",
        "output_8.4.0.22_vdisks_ok.json",
        "output_8.4.0.22_pdisks_ok.json",
    ]

    with mock_perccli_commands(mock_outputs):
        ret = perccli_status_main([])
        assert ret == 0

    with mock_perccli_commands(mock_outputs):
        ret = perccli_status_main(["--nagios"])
        assert ret == 0

    mock_outputs = [
        "output_8.4.0.22_version.txt",
        "nojson.txt",
        "nojson.txt",
        "nojson.txt",
    ]

    with mock_perccli_commands(mock_outputs):
        ret = perccli_status_main([])
        assert ret == 2


def test_run_v7():
    """test run"""

    mock_outputs = [
        "output_7.2313_version.txt",
        "output_7.2313_controllers_ok.json",
        "output_7.2313_vdisks_ok.json",
        "output_7.2313_pdisks_ok.json",
    ]

    with mock_perccli_commands(mock_outputs):
        ret = perccli_status_main([])
        assert ret == 0

    with mock_perccli_commands(mock_outputs):
        ret = perccli_status_main(["--nagios"])
        assert ret == 0

    mock_outputs = [
        "output_7.2313_version.txt",
        "nojson.txt",
        "nojson.txt",
        "nojson.txt",
    ]

    with mock_perccli_commands(mock_outputs):
        ret = perccli_status_main([])
        assert ret == 2
