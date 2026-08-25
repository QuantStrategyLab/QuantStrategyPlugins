from __future__ import annotations

import tomllib
from pathlib import Path


def test_ruff_rule_selection_is_explicit_and_stable() -> None:
    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["ruff"]["lint"]["select"] == ["E4", "E7", "E9", "F"]
