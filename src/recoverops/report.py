from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from recoverops.config import ProjectPaths
from recoverops.evidence import capture_fingerprint, utc_now, write_json


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def seconds_between(start: str, finish: str) -> float:
    return round((parse_timestamp(finish) - parse_timestamp(start)).total_seconds(), 3)


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def render_markdown(report: dict[str, Any]) -> str:
    comparison_rows = "\n".join(
        f"| {name} | {'PASS' if result['match'] else 'FAIL'} |"
        for name, result in report["comparisons"].items()
    )
    counts = report["recovery_fingerprint"]["row_counts"]
    primary_status = report["services"]["primary_api"]
    recovery_status = report["services"]["recovery_api"]
    primary_result = "PASS" if primary_status == 503 else "FAIL"
    recovery_result = "PASS" if recovery_status == 200 else "FAIL"
    return f"""# restore-verify recovery evidence

**Outcome:** {report["outcome"]}

**Generated:** {report["generated_at"]}

## Recovery metrics

| Metric | Seconds |
| --- | ---: |
| RTO (disaster start to recovery complete) | {report["metrics"]["rto_seconds"]} |
| Restore duration | {report["metrics"]["restore_duration_seconds"]} |
| Backup age at recovery | {report["metrics"]["backup_age_at_recovery_seconds"]} |

## Data verification

| Check | Result |
| --- | --- |
{comparison_rows}

Recovered rows: {counts["owners"]} owners, {counts["assets"]} assets, and
{counts["maintenance_events"]} maintenance events.

## Service verification

| Service | Expected | Actual | Result |
| --- | ---: | ---: | --- |
| Primary API after disaster | 503 | {primary_status} | {primary_result} |
| Recovery API | 200 | {recovery_status} | {recovery_result} |

## Evidence identifiers

- Source data SHA-256: `{report["source_fingerprint"]["data_sha256"]}`
- Recovery data SHA-256: `{report["recovery_fingerprint"]["data_sha256"]}`
- Source schema SHA-256: `{report["source_fingerprint"]["schema_sha256"]}`
- Recovery schema SHA-256: `{report["recovery_fingerprint"]["schema_sha256"]}`

This local rehearsal demonstrates recovery mechanics. It does not establish a
production recovery objective or replace a production disaster-recovery test.
"""


def build_recovery_report(paths: ProjectPaths) -> dict[str, Any]:
    source_path = paths.restore / "current/backup/source-fingerprint.json"
    state_path = paths.state / "workflow.json"
    if not source_path.is_file():
        raise FileNotFoundError("restored source fingerprint is missing; run restore first")
    if not state_path.is_file():
        raise FileNotFoundError("workflow timestamps are missing; run disaster and restore first")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    disaster = state["events"]["disaster"]
    restore = state["events"]["restore"]
    for record, fields in (
        (disaster, ("started_at", "completed_at")),
        (restore, ("started_at", "completed_at")),
    ):
        for field in fields:
            if field not in record:
                raise RuntimeError(f"workflow timestamp is missing: {field}")

    recovery = capture_fingerprint(paths, "recovery")
    write_json(paths.reports / "recovery-fingerprint.json", recovery)
    comparison_fields = ("schema_sha256", "data_sha256", "row_counts", "server_version")
    comparisons = {
        field: {
            "match": source[field] == recovery[field],
            "source": source[field],
            "recovery": recovery[field],
        }
        for field in comparison_fields
    }
    services = {
        "primary_api": http_status("http://127.0.0.1:18080/health"),
        "recovery_api": http_status("http://127.0.0.1:18081/health"),
    }
    passed = all(item["match"] for item in comparisons.values()) and services == {
        "primary_api": 503,
        "recovery_api": 200,
    }
    report = {
        "format_version": 1,
        "generated_at": utc_now(),
        "outcome": "PASS" if passed else "FAIL",
        "metrics": {
            "rto_seconds": seconds_between(disaster["started_at"], restore["completed_at"]),
            "restore_duration_seconds": seconds_between(
                restore["started_at"], restore["completed_at"]
            ),
            "backup_age_at_recovery_seconds": seconds_between(
                source["captured_at"], restore["completed_at"]
            ),
        },
        "services": services,
        "comparisons": comparisons,
        "source_fingerprint": source,
        "recovery_fingerprint": recovery,
        "workflow": state,
    }
    write_json(paths.reports / "recovery-report.json", report)
    (paths.reports / "recovery-report.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    return report
