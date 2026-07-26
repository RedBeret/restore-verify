# restore-verify v1 plan

## Product contract

restore-verify is a local disaster-recovery rehearsal environment. It proves that a
PostgreSQL backup is usable by restoring it into an isolated recovery database and
comparing the recovered application state with evidence captured before backup.

The project runs natively inside WSL and uses Docker, Ansible, Python, PostgreSQL,
and restic. It does not require a paid product or external infrastructure.

## Operator workflow

```text
bootstrap -> doctor -> up -> seed -> backup -> disaster --apply -> restore -> verify -> report -> down
```

`rehearse --apply` runs the complete workflow after prerequisites pass.

## Version 1 scope

- A primary PostgreSQL database with deterministic sample operational data.
- A small HTTP service that exposes health and summary endpoints.
- A separate recovery PostgreSQL database and recovery HTTP service.
- Source fingerprints containing schema, row-count, and canonical data hashes.
- A PostgreSQL custom-format dump protected by a SHA-256 manifest.
- An encrypted restic repository with an integrity check after every backup.
- An explicit approval gate before the primary database is removed.
- Restore into the recovery database only; restore never overwrites the primary.
- RPO and RTO measurements with JSON and Markdown evidence reports.
- Negative tests for missing approval, missing backup, and modified dump content.
- Native WSL bootstrap, diagnostics, CI, tests, linting, and operator documentation.

## Safety boundaries

- Destructive actions require the literal `--apply` flag.
- Disaster injection only drops the `recoverops` database inside the Compose project.
- Restore only targets the distinct `recovery-db` container.
- Docker resources use the fixed Compose project name `recoverops`.
- Host ports bind to `127.0.0.1` only.
- Generated passwords, dumps, repository data, and reports are ignored by Git.
- Cleanup commands resolve only paths beneath the repository's `artifacts/` directory.

## Out of scope for v1

- Production credentials or infrastructure.
- PostgreSQL physical backups, WAL archiving, or point-in-time recovery.
- Object-storage or cloud-provider integration.
- High-availability failover or multi-region orchestration.
- Claims that a local rehearsal establishes production recovery readiness.

## Done criteria

1. A fresh WSL clone completes `./scripts/bootstrap.sh` and `./scripts/lab.sh doctor`.
2. `up` produces healthy primary and recovery database containers.
3. `seed` is idempotent and produces the same source fingerprint twice.
4. `backup` creates a PostgreSQL dump, manifest, restic snapshot, and valid evidence.
5. `disaster` without `--apply` exits nonzero without changing the primary.
6. `disaster --apply` removes only the primary `recoverops` database and makes its API unhealthy.
7. `restore` rebuilds the database only in the isolated recovery target.
8. `verify` proves schema, row counts, and canonical data hashes match the source evidence.
9. A modified restored dump is rejected before `pg_restore` runs.
10. JSON reports parse, Markdown reports render, and RPO/RTO fields are present.
11. Unit, contract, shell, Ansible syntax, and lint checks pass.
12. The full live rehearsal passes and `down` leaves no lab containers running.

## Delivery stages

1. Product contract and environment verification.
2. Repository, CLI, Docker lab, bootstrap, and baseline tests.
3. Deterministic seeding and encrypted backup workflow.
4. Gated disaster injection and isolated restore workflow.
5. Verification, evidence, and negative paths.
6. CI, documentation, and governance.
7. Live acceptance and skeptical review.
