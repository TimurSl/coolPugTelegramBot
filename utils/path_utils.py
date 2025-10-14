"""Utilities for resolving the project home directory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union


home_dir = ""


def set_home_dir(path: Union[str, Path]) -> None:
    """Set the global home directory used by storage classes."""

    global home_dir
    home_dir = str(path)
    logging.getLogger(__name__).debug("Home directory set to %s", home_dir)


def get_home_dir() -> str:
    """Return the currently configured home directory."""

    if not home_dir:
        default = Path(__file__).resolve().parent.parent
        logging.getLogger(__name__).debug(
            "Home directory was not initialised; defaulting to %s", default
        )
        return str(default)
    logging.getLogger(__name__).debug("Fetching home directory: %s", home_dir)
    return home_dir

