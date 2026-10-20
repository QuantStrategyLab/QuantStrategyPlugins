"""Explicit, opt-in audit of one frozen Crisis report; writes only private advisories.

A host supplies the approved Quant client/instance. This entry never provisions a
subscription or worker and never waits, retries, or falls back to another route.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from urllib.parse import quote, urlsplit, urlunsplit

from quant_strategy_plugins.ai_audit import prepare_crisis_shadow_audit, verify_crisis_shadow_audit


def _resource_identity(resource):
    """Canonical service identity for this caller's private receipt, never a route selector."""
    if not isinstance(resource, str) or any(char.isspace() or ord(char) < 32 for char in resource):
        raise ValueError("an explicit HTTPS resource is required")
    parsed = urlsplit(resource)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("resource must be HTTPS without credentials, query or fragment")
    authority = parsed.netloc.lower()
    if parsed.port == 443:
        authority = authority.removesuffix(":443")
    return urlunsplit(("https", authority, parsed.path.rstrip("/"), "", ""))


def _approved_client(client, service):
    if client is None:
        # Freeze only non-secret identity. The SDK alone obtains/uses credentials.
        if (not service["audience"] or os.environ.get("AI_SERVICE_AUDIENCE") != service["audience"]
                or _resource_identity(os.environ.get("AI_SERVICE_URL")) != service["resource"]):
            raise ValueError("workload identity does not match the approved service context")
        from ai_service.client import client_from_env
        client = client_from_env()
    if _resource_identity(client.resource) != service["resource"]:
        raise ValueError("client resource does not match the approved service context")
    return client


def _read_private(path):
    if path.is_symlink():
        raise ValueError("private evidence must be a regular file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("private evidence must have mode 0600")
        raw = stream.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("private evidence exceeds its bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("private evidence must be an object")
    return value, raw


def _binding(path, intent, intent_sha256, *, recovered=False):
    if not path.exists() and not path.is_symlink():
        return None
    value, _ = _read_private(path)
    task_id = value.get("task_id")
    if (value.get("status") != ("recovered" if recovered else "submitted")
            or value.get("operation_key") != intent["operation_key"]
            or value.get("request_sha256") != intent["request_sha256"]
            or value.get("service") != intent["service"]
            or not isinstance(task_id, str) or not 1 <= len(task_id) <= 200
            or "\r" in task_id or "\n" in task_id):
        raise ValueError("original task identity is unavailable")
    if recovered and (value.get("source") != "readonly_task_lookup"
                      or value.get("intent_sha256") != intent_sha256):
        raise ValueError("recovery provenance does not match the original intent")
    return value


def _unexpired(task):
    deadline = datetime.fromisoformat(task.spec["deadline"].replace("Z", "+00:00"))
    if deadline.tzinfo is None or datetime.now(timezone.utc) >= deadline:
        raise ValueError("original operation deadline passed")


def _uncancelled_history(client, task_id):
    history = client.request("GET", "/v1/tasks/" + quote(task_id, safe="") + "/events")
    if not isinstance(history, dict) or set(history) != {"events"}:
        raise ValueError("task history is unavailable")
    rows = history["events"]
    # The existing endpoint returns at most 100 rows. A full page cannot prove
    # that the history is complete; never poll or paginate as a fallback.
    if not isinstance(rows, list) or not 0 < len(rows) < 100:
        raise ValueError("complete bounded task history is required")
    previous = 0
    states = {"queued", "submitting", "running", "outcome_unknown", "cancel_requested",
              "completed", "failed", "invalid_output", "cancelled"}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"seq", "status", "created"}
                or type(row["seq"]) is not int or row["seq"] <= previous
                or not isinstance(row["status"], str) or row["status"] not in states
                or type(row["created"]) not in {int, float} or not math.isfinite(row["created"])):
            raise ValueError("task history is invalid")
        previous = row["seq"]
        if row["status"] in {"cancel_requested", "cancelled"}:
            raise ValueError("original operation has cancellation history")
    if rows[-1]["status"] != "completed":
        raise ValueError("task history does not confirm completion")


def main(argv=None, *, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["dry-run", "submit", "recover", "verify"], nargs="?", default="dry-run")
    parser.add_argument("--enabled", action="store_true", help="explicit native entry opt-in")
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--resource", help="explicit approved Quant service resource")
    parser.add_argument("--audience", help="explicit non-secret workload audience, when used")
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
            args.occurrence, args.submitted_at, args.resource,
        )):
            raise ValueError("explicit frozen context is required")
        service = {"resource": _resource_identity(args.resource), "audience": args.audience}
        if args.audience is not None and (not args.audience or any(char.isspace() for char in args.audience)):
            raise ValueError("audience must be an explicit non-secret identifier")
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
            if stat.S_IMODE(directory.stat().st_mode) != 0o700:
                raise ValueError("audit directory must have mode 0700")
            prefix = directory / ("crisis-" + task.spec["operation_key"].split(":", 1)[1])
            intent_path = Path(str(prefix) + ".intent.json")
            submitted_path = Path(str(prefix) + ".submitted.json")
            recovered_path = Path(str(prefix) + ".recovered.json")
            advisory_path = Path(str(prefix) + ".advisory.json")
            intent = {"status": "intent", "operation_key": task.spec["operation_key"],
                      "request_sha256": digest(task.request), "spec": task.spec, "request": task.request, "service": service}
            if args.command == "submit":
                if submitted_path.exists() or recovered_path.exists() or advisory_path.exists():
                    raise ValueError("operation already has a receipt")
                # SDK exclusive 0600/fsync write precedes client construction and POST.
                # Any exception leaves this intent intact, preventing another submission.
                write_private(intent_path, intent)
                client = _approved_client(client, service)
                record = submit(client, task)
                result = {"status": "submitted", "task_id": record["id"],
                          "operation_key": task.spec["operation_key"], "request_sha256": digest(task.request),
                          "service": service}
                write_private(submitted_path, result)
            else:
                original, intent_raw = _read_private(intent_path)
                if original != intent:
                    raise ValueError("frozen intent mismatch")
                _unexpired(task)
                if advisory_path.exists() or advisory_path.is_symlink():
                    raise ValueError("operation already has an advisory")
                intent_sha256 = hashlib.sha256(intent_raw).hexdigest()
                submitted = _binding(submitted_path, intent, intent_sha256)
                recovered = _binding(recovered_path, intent, intent_sha256, recovered=True)
                if submitted and recovered and submitted["task_id"] != recovered["task_id"]:
                    raise ValueError("conflicting task identities")
                if args.command == "recover" and submitted and not recovered:
                    result = submitted
                elif args.command == "recover" or recovered:
                    client = _approved_client(client, service)
                    # Every explicit recovery/provenance use gets one authoritative
                    # binding read; never trust a locally changed ID or retry a miss.
                    found = client.lookup(intent["operation_key"], intent["request_sha256"])
                    if (not isinstance(found, dict) or set(found) != {"id"}
                            or not isinstance(found["id"], str) or not 1 <= len(found["id"]) <= 200
                            or "\r" in found["id"] or "\n" in found["id"]):
                        raise ValueError("invalid recovery response")
                    if recovered and found["id"] != recovered["task_id"]:
                        raise ValueError("recovery binding changed")
                    _unexpired(task)
                    result = recovered or {"status": "recovered", "source": "readonly_task_lookup",
                        "task_id": found["id"], "operation_key": intent["operation_key"],
                        "request_sha256": intent["request_sha256"], "service": service,
                        "intent_sha256": intent_sha256}
                    if not recovered:
                        write_private(recovered_path, result)
                    recovered = result
                elif submitted is None:
                    raise ValueError("original task identity is unavailable")
                if args.command == "verify":
                    identity = submitted or recovered
                    client = _approved_client(client, service)
                    record = client.get(identity["task_id"])
                    result = verify_crisis_shadow_audit(task, record, task_id=identity["task_id"])
                    _uncancelled_history(client, identity["task_id"])
                    _unexpired(task)
                    write_private(advisory_path, result)
        print(json.dumps({"status": result["status"], "operation_key": task.spec["operation_key"]}))
        return 0
    except Exception:
        # No remote exception, input text, account, token or host path reaches stdout.
        print(json.dumps({"status": "unverified", "reason": "inspect the existing private intent; do not resubmit"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
