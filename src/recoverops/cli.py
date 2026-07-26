from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable

from recoverops import __version__
from recoverops.config import ProjectPaths
from recoverops.database import ensure_recoverops_database
from recoverops.evidence import capture_fingerprint, create_manifest, verify_manifest, write_json
from recoverops.report import build_recovery_report
from recoverops.restic import (
    backup_artifacts,
    check_repository,
    initialize_repository,
    restore_latest,
)
from recoverops.runner import (
    ansible_playbook,
    compose_base,
    compose_command,
    run,
    wait_for_container_health,
)
from recoverops.safety import assert_container_scope
from recoverops.state import record_event


def _check(label: str, command: list[str]) -> bool:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    state = "ok" if result.returncode == 0 else "fail"
    print(f"{state} {label}")
    return result.returncode == 0


def command_doctor(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    checks: list[bool] = []
    for command in ("python3", "docker", "git"):
        found = shutil.which(command) is not None
        print(f"{'ok' if found else 'fail'} command {command}")
        checks.append(found)
    checks.append(_check("docker daemon", ["docker", "info"]))
    try:
        compose = compose_command()
    except RuntimeError:
        print("fail docker compose")
        checks.append(False)
    else:
        print(f"ok docker compose ({' '.join(compose)})")
        checks.append(True)
        checks.append(
            _check(
                "compose configuration",
                [*compose_base(paths.root), "config", "--quiet"],
            )
        )
    for label, path in (
        ("environment file", paths.root / ".env"),
        ("restic password", paths.secrets / "restic-password"),
        ("compose file", paths.root / "compose.yml"),
    ):
        present = path.is_file()
        print(f"{'ok' if present else 'fail'} {label}")
        checks.append(present)
    return 0 if all(checks) else 1


def command_up(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    paths.ensure_generated_directories()
    run([*compose_base(paths.root), "up", "-d", "--build"], cwd=paths.root)
    for container in ("recoverops-primary-db", "recoverops-recovery-db"):
        wait_for_container_health(container)
    return 0


def command_status(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    return run([*compose_base(paths.root), "ps"], cwd=paths.root, check=False).returncode


def command_down(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    return run(
        [*compose_base(paths.root), "down", "--remove-orphans"],
        cwd=paths.root,
        check=False,
    ).returncode


def command_seed(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    ansible_playbook(paths.root, "seed.yml")
    return 0


def command_ensure_source(_: argparse.Namespace) -> int:
    result = ensure_recoverops_database("recoverops-primary-db", "primary-db")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def command_fingerprint(args: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    fingerprint = capture_fingerprint(paths, args.target)
    if args.output:
        output = paths.require_artifact_path(paths.root / args.output)
        write_json(output, fingerprint)
    print(json.dumps(fingerprint, indent=2, sort_keys=True))
    return 0


def command_manifest(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    manifest = create_manifest(paths)
    write_json(paths.backup / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def command_verify_manifest(args: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    directory = paths.require_artifact_path(paths.root / args.directory)
    manifest = paths.require_artifact_path(paths.root / args.manifest)
    errors = verify_manifest(directory, manifest)
    print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 2


def command_restic_init(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    print(json.dumps(initialize_repository(paths), indent=2, sort_keys=True))
    return 0


def command_restic_backup(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    print(json.dumps(backup_artifacts(paths), indent=2, sort_keys=True))
    return 0


def command_restic_check(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    print(json.dumps(check_repository(paths), indent=2, sort_keys=True))
    return 0


def command_backup(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    ansible_playbook(paths.root, "backup.yml")
    return 0


def command_assert_scope(args: argparse.Namespace) -> int:
    print(json.dumps(assert_container_scope(args.container, args.service), indent=2))
    return 0


def command_state_event(args: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    print(json.dumps(record_event(paths, args.name, args.status), indent=2, sort_keys=True))
    return 0


def command_restic_restore(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    print(json.dumps(restore_latest(paths), indent=2, sort_keys=True))
    return 0


def command_disaster(args: argparse.Namespace) -> int:
    if not args.apply:
        print("Refusing to remove the primary database without --apply.", file=sys.stderr)
        return 2
    paths = ProjectPaths.discover()
    ansible_playbook(paths.root, "disaster.yml")
    return 0


def command_restore(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    ansible_playbook(paths.root, "restore.yml")
    return 0


def command_build_report(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    report = build_recovery_report(paths)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["outcome"] == "PASS" else 2


def command_verify(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    ansible_playbook(paths.root, "verify.yml")
    return 0


def command_report(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    report = paths.reports / "recovery-report.md"
    if not report.is_file():
        raise RuntimeError("recovery report is missing; run verify first")
    print(report.read_text(encoding="utf-8"))
    return 0


def command_rehearse(args: argparse.Namespace) -> int:
    if not args.apply:
        print("Refusing to run the destructive rehearsal without --apply.", file=sys.stderr)
        return 2
    command_up(args)
    command_seed(args)
    command_backup(args)
    command_disaster(args)
    command_restore(args)
    command_verify(args)
    return 0


def command_test(_: argparse.Namespace) -> int:
    paths = ProjectPaths.discover()
    commands = [
        [str(paths.root / ".venv/bin/python"), "-m", "pytest", "-q"],
        [str(paths.root / ".venv/bin/ruff"), "format", "--check", "src", "app", "tests"],
        [str(paths.root / ".venv/bin/ruff"), "check", "src", "app", "tests"],
        ["bash", "-n", "scripts/bootstrap.sh", "scripts/lab.sh"],
        [*compose_base(paths.root), "config", "--quiet"],
    ]
    syntax_variables = json.dumps({"recoverops_root": str(paths.root)})
    for playbook in ("seed", "backup", "disaster", "restore", "verify"):
        commands.append(
            [
                str(paths.root / ".venv/bin/ansible-playbook"),
                str(paths.root / f"ansible/playbooks/{playbook}.yml"),
                "--syntax-check",
                "--extra-vars",
                syntax_variables,
            ]
        )
    commands.append(
        [
            str(paths.root / ".venv/bin/ansible-lint"),
            "ansible/playbooks",
            "ansible/roles",
        ]
    )
    for command in commands:
        result = run(command, cwd=paths.root, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recoverctl",
        description="Operate the restore-verify disaster-recovery rehearsal lab.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    handlers: dict[str, tuple[str, Callable[[argparse.Namespace], int]]] = {
        "doctor": ("Check local prerequisites and generated configuration.", command_doctor),
        "up": ("Build and start the lab services.", command_up),
        "status": ("Show lab service status.", command_status),
        "down": ("Stop and remove lab containers while preserving volumes.", command_down),
        "seed": ("Reset the primary database to the deterministic sample dataset.", command_seed),
        "backup": ("Create, encrypt, and verify a source database backup.", command_backup),
        "restore": (
            "Restore the latest verified snapshot into the recovery database.",
            command_restore,
        ),
        "verify": ("Compare recovered state and write recovery evidence.", command_verify),
        "report": ("Print the latest Markdown recovery report.", command_report),
        "test": ("Run the local validation suite.", command_test),
    }
    for name, (help_text, handler) in handlers.items():
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.set_defaults(handler=handler)

    disaster = subparsers.add_parser(
        "disaster",
        help="Remove the source database after explicit approval.",
    )
    disaster.add_argument("--apply", action="store_true")
    disaster.set_defaults(handler=command_disaster)

    rehearse = subparsers.add_parser(
        "rehearse",
        help="Run the complete backup, disaster, restore, and verification workflow.",
    )
    rehearse.add_argument("--apply", action="store_true")
    rehearse.set_defaults(handler=command_rehearse)

    fingerprint = subparsers.add_parser("fingerprint", help=argparse.SUPPRESS)
    fingerprint.add_argument("--target", choices=("primary", "recovery"), required=True)
    fingerprint.add_argument("--output")
    fingerprint.set_defaults(handler=command_fingerprint)

    manifest = subparsers.add_parser("manifest", help=argparse.SUPPRESS)
    manifest.set_defaults(handler=command_manifest)

    verify = subparsers.add_parser("verify-manifest", help=argparse.SUPPRESS)
    verify.add_argument("--directory", required=True)
    verify.add_argument("--manifest", required=True)
    verify.set_defaults(handler=command_verify_manifest)

    for name, handler in (
        ("restic-init", command_restic_init),
        ("restic-backup", command_restic_backup),
        ("restic-check", command_restic_check),
        ("restic-restore", command_restic_restore),
        ("ensure-source", command_ensure_source),
        ("build-report", command_build_report),
    ):
        internal = subparsers.add_parser(name, help=argparse.SUPPRESS)
        internal.set_defaults(handler=handler)

    scope = subparsers.add_parser("assert-scope", help=argparse.SUPPRESS)
    scope.add_argument("--container", required=True)
    scope.add_argument("--service", required=True)
    scope.set_defaults(handler=command_assert_scope)

    state_event = subparsers.add_parser("state-event", help=argparse.SUPPRESS)
    state_event.add_argument("--name", required=True)
    state_event.add_argument("--status", choices=("started", "completed", "failed"), required=True)
    state_event.set_defaults(handler=command_state_event)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        print(f"error: {detail}", file=sys.stderr)
        return exc.returncode or 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
