from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils import path_utils


@pytest.fixture(autouse=True)
def override_home_dir(tmp_path):
    original = getattr(path_utils, "home_dir", "")
    path_utils.set_home_dir(tmp_path)
    yield
    if original:
        path_utils.set_home_dir(original)
    else:
        path_utils.home_dir = ""
