"""Explicit, opt-in audit of one frozen Crisis report; writes only private advisories.

A host supplies the approved Quant client/instance. This entry never provisions a
subscription or worker and never waits, retries, or falls back to another route.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from quant_strategy_plugins.ai_audit import prepare_crisis_shadow_audit, verify_crisis_shadow_audit


def main(argv=None, *, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["dry-run", "submit", "verify"], nargs="?", default="dry-run")
    parser.add_argument("--enabled", action="store_true", help="explicit native entry opt-in")
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-ref")
    parser.add_argument("--source-revision")
    parser.add_argument("--source-sha256")
    parser.add_argument("--occurrence")
    parser.add_argument("--submitted-at", help="frozen ISO timestamp; reuse it for verification")
    parser.add_argument("--audit-dir", type=Path, help="dedicated private directory outside the source report")
    args = parser.parse_args(argv)
    if not args.enabled:
        print(json.dumps({"status": "disabled", "dispatchable": False}))
        return 0
    try:
        if any(value is None for value in (
            args.instance, args.report, args.source_ref, args.source_revision, args.source_sha256,
            args.occurrence, args.submitted_at,
        )):
            raise ValueError("explicit frozen context is required")
        raw = args.report.read_bytes()
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != args.source_sha256:
            raise ValueError("report hash mismatch or size exceeded")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("report must be an object")
        task = prepare_crisis_shadow_audit(
            payload, instance=json.loads(args.instance.read_text()), source_ref=args.source_ref,
            source_revision=args.source_revision, source_sha256=args.source_sha256,
            occurrence=args.occurrence,
            submitted_at=datetime.fromisoformat(args.submitted_at.replace("Z", "+00:00")),
        )
        from ai_service.scenarios.pilot import digest, submit
        from ai_service.scenarios.pilot_cli import write_private

        if args.command == "dry-run":
            result = {"status": "prepared", "dispatchable": False,
                      "operation_key": task.spec["operation_key"], "request_sha256": digest(task.request)}
        else:
            if args.audit_dir is None or args.audit_dir.is_symlink():
                raise ValueError("a dedicated audit directory is required")
            directory = args.audit_dir.resolve()
            if args.report.resolve().is_relative_to(directory) or args.instance.resolve().is_relative_to(directory):
                raise ValueError("audit directory must be separate from the frozen inputs")
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            prefix = directory / ("crisis-" + task.spec["operation_key"].split(":", 1)[1])
            intent_path = Path(str(prefix) + ".intent.json")
            submitted_path = Path(str(prefix) + ".submitted.json")
            advisory_path = Path(str(prefix) + ".advisory.json")
            intent = {"status": "intent", "operation_key": task.spec["operation_key"],
                      "request_sha256": digest(task.request), "spec": task.spec, "request": task.request}
            if args.command == "submit":
                if submitted_path.exists() or advisory_path.exists():
                    raise ValueError("operation already has a receipt")
                # SDK exclusive 0600/fsync write precedes client construction and POST.
                # Any exception leaves this intent intact, preventing another submission.
                write_private(intent_path, intent)
                if client is None:
                    from ai_service.client import client_from_env
                    client = client_from_env()
                record = submit(client, task)
                result = {"status": "submitted", "task_id": record["id"],
                          "operation_key": task.spec["operation_key"], "request_sha256": digest(task.request)}
                write_private(submitted_path, result)
            else:
                if json.loads(intent_path.read_text()) != intent:
                    raise ValueError("frozen intent mismatch")
                submitted = json.loads(submitted_path.read_text())
                if (submitted.get("operation_key") != task.spec["operation_key"]
                        or submitted.get("request_sha256") != digest(task.request)
                        or not isinstance(submitted.get("task_id"), str) or not submitted["task_id"]):
                    raise ValueError("original task identity is unavailable")
                if client is None:
                    from ai_service.client import client_from_env
                    client = client_from_env()
                # One caller readback. Pending/unknown results remain pending/unknown.
                record = client.get(submitted["task_id"])
                result = verify_crisis_shadow_audit(task, record, task_id=submitted["task_id"])
                write_private(advisory_path, result)
        print(json.dumps({"status": result["status"], "operation_key": task.spec["operation_key"]}))
        return 0
    except Exception:
        # No remote exception, input text, account, token or host path reaches stdout.
        print(json.dumps({"status": "unverified", "reason": "inspect the existing private intent; do not resubmit"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
