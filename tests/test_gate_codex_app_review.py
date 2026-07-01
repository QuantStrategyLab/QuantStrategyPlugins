import re

from scripts.gate_codex_app_review import scan_diff


def test_scan_diff_redacts_hardcoded_secret_values() -> None:
    secret_field = "API" + "_KEY"
    raw_secret = "super" + "secretvalue123456"
    diff = "\n".join(
        (
            "diff --git a/app.py b/app.py",
            "+++ b/app.py",
            f'+{secret_field} = "{raw_secret}"',
        )
    )

    violations = scan_diff(diff, path_patterns=[])

    assert len(violations) == 1
    assert "<redacted>" in violations[0]
    assert raw_secret not in violations[0]
    assert re.search(r"api[_\\s]?key", violations[0], re.IGNORECASE)
