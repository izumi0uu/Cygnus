# Cygnus 备份 / 恢复 / 演练 Runbook

**CYG-132 · Production V1 运维恢复。** 本文档给出可自动化、且失败即关闭（fail
closed）的确切命令：创建应用级一致性备份包、校验备份、恢复到一次性目标环境、以及执行
带测量证据的恢复演练。任何缺失、损坏或密钥不匹配的备份状态都会以机器可读错误阻断操作。

实现：`cygnus/runtime/backup_restore.py`（CLI 入口
`python -m cygnus.runtime.backup_restore`）。

English counterpart: [Backup / Restore / Drill Runbook](../en/backup-restore-runbook.md). 两个语言版本描述相同的 release identity、加密备份、隔离恢复和实测演练契约。

---

## 1. 保证

- 备份包**原子化**：先在 staging 目录组装，manifest 与完成标记写完后才原子改名发布；
  失败不留下半成品，且必定执行运维提供的 resume 命令。
- 备份是**应用级一致快照**，在运维**静默屏障（quiesce）**下完成：先执行
  quiesce 命令停写，再取 `pg_dump` 快照、拷贝 MinIO 对象清单、记录加密配置密钥指纹、
  完整 Git commit、不可变前后端镜像摘要、精确 Alembic head 与校验和，最后才执行
  resume 命令。
- **设计上排除 Redis/ARQ 载荷**：Redis 是临时传输层，已提交的 PostgreSQL outbox
  行才是恢复真相源。恢复会清空目标 Redis 库并重放记录的 durable reconciler
  （确定性 ARQ job ID 保证重放幂等）。
- **永不归档明文密钥**：只记录 `runtime.secret_key` 与
  `runtime.mcp_token_pepper` 的 SHA-256 指纹；恢复时密钥材料必须与指纹一致，否则拒绝。
- **破坏性恢复只接受显式空的一次性目标**：目标库无表、目标桶无对象、`target_id`
  与源身份不同、`--confirm-target` 精确一致。生产恢复还需 `--allow-production-restore`
  且 manifest 必须加密并签名。
- **演练报告为机器可读，RPO/RTO 只报实测值**：未测量时输出
  `"measured": false` 且秒数为 `null`——绝不臆造，也绝不默认填 0。

## 2. 包格式（`cygnus-coordinated-backup/v1`）

```
<backup-dir>/
  COMPLETE                    # 完成标记；锁定 manifest envelope 的 sha256
  manifest.envelope.json      # 指向 manifest 文件及其 sha256/字节数
  manifest.json               # （加密备份为 manifest.json.enc）
  manifest.sig                # （可选）manifest 文件的签名
  database.dump               # （或 .enc）pg_dump --format=custom
  objects/00000001.blob       # （或 .enc）每个 MinIO 对象一个文件
```

manifest 记录：

- `source` — 环境与源身份。
- `release_identity` — 完整 Git commit、后端/前端不可变 `@sha256` 镜像引用、以及精确
  Alembic head；生产包必须具备这些绑定。
- `consistency_boundary` — quiesce/dump 时间戳与**实测 RPO 上界**
  （`measured_rpo_upper_bound_seconds`）。
- `database` — 工件校验和（`sha256`、`bytes`、明文 `payload_sha256`/
  `payload_bytes`）、`database_revisions`、`repository_heads`。
- `objects` — 每个对象的 `object_key`、content type、元数据、源 ETag、工件校验和。
- `configuration_inventory` — 运行时配置项名与静态加密的敏感 `app_config` 键。
- `key_material` — 解密持久化加密配置所需密钥材料的 SHA-256 指纹。
- `queue_reconciliation` — Redis 策略与记录的 durable reconciler。
- `verification` — 同一静默屏障下采样的表行数基线与 FK 约束数，供演练比对恢复计数。

## 3. 前置条件

- `PATH` 上有 `psql`、`pg_dump`、`pg_restore`（PostgreSQL 15+）。
- 用 `uv run`（或激活的项目 venv）运行。
- MinIO 凭据与桶；目标 Redis URL。
- 生产备份需要加密与签名命令模板以及完整不可变 release identity（见 §4.2）。命令以
  argv 模板执行、**不经 shell**，模板内不要依赖 shell 操作符。
- 源数据库必须处于当前检出 Alembic head，且 production 传入的 head 必须与数据库和
  仓库 head 精确一致；否则备份拒绝（`database_not_at_repository_head` /
  `release_alembic_head_mismatch`）。

## 4. 备份

### 4.1 开发 / 预发（未加密包）

```bash
uv run python -m cygnus.runtime.backup_restore backup \
  --output-dir "/var/backups/cygnus/$(date -u +%Y%m%dT%H%M%SZ)" \
  --environment staging \
  --source-id "staging-01" \
  --quiesce-command "docker compose stop api worker worker-skills delivery-consumer" \
  --resume-command  "docker compose start api worker worker-skills delivery-consumer" \
  --retention-label daily \
  --report-file /var/backups/cygnus/backup-report.json
```

- 数据库 URL：`--database-url` 或 `CYGNUS_BACKUP_DATABASE_URL`；缺省取运行时配置。
- MinIO：`--minio-{endpoint,access-key,secret-key,bucket}` 或
  `CYGNUS_BACKUP_MINIO_*`；缺省取运行时配置。
- quiesce 命令必须停掉所有写路径（API、worker、定时任务）。工具执行 quiesce →
  快照 → 无论成败都在 `finally` 中执行 resume。
- 开发栈可传 `--quiesce-command "true"` / `--resume-command "true"`，但生产不可。
- 退出码 `0` 且 `"status": "completed"`；任何失败输出 `"status": "failed"`
  报告并返回非零退出码。

### 4.2 生产（必须加密 + 签名）

生产备份**缺少**工件加密、manifest 加密、manifest 签名或完整不可变 release identity
时直接拒绝：

```bash
export CYGNUS_REPO=/srv/cygnus
export CYGNUS_RELEASE=2026.08.15.1  # 必须对应 deploy/releases/<version>.env
export CYGNUS_RELEASE_GIT_COMMIT="$(git rev-parse HEAD)" # 仅接受完整 commit
export CYGNUS_RELEASE_BACKEND_IMAGE_REF="registry.example/cygnus-api@sha256:REPLACE_WITH_DEPLOYED_DIGEST"
export CYGNUS_RELEASE_FRONTEND_IMAGE_REF="registry.example/cygnus-web@sha256:REPLACE_WITH_DEPLOYED_DIGEST"
export CYGNUS_RELEASE_ALEMBIC_HEAD="REPLACE_WITH_DEPLOYED_ALEMBIC_HEAD"
cd "$CYGNUS_REPO"

uv run python -m cygnus.runtime.backup_restore backup \
  --output-dir "/var/backups/cygnus/$(date -u +%Y%m%dT%H%M%SZ)" \
  --environment production \
  --source-id "prod-01" \
  --git-commit "$CYGNUS_RELEASE_GIT_COMMIT" \
  --backend-image-ref "$CYGNUS_RELEASE_BACKEND_IMAGE_REF" \
  --frontend-image-ref "$CYGNUS_RELEASE_FRONTEND_IMAGE_REF" \
  --alembic-head "$CYGNUS_RELEASE_ALEMBIC_HEAD" \
  --quiesce-command "${CYGNUS_REPO}/scripts/prod/compose-control.sh --release ${CYGNUS_RELEASE} -- quiesce-backend" \
  --resume-command  "${CYGNUS_REPO}/scripts/prod/compose-control.sh --release ${CYGNUS_RELEASE} -- resume-backend" \
  --retention-label daily \
  --artifact-encrypt-command  "age --encrypt -r age1xxxxxxxx -o {output} {input}" \
  --artifact-decrypt-command  "age --decrypt -i /run/secrets/cygnus-backup-age.txt -o {output} {input}" \
  --manifest-encrypt-command  "age --encrypt -r age1xxxxxxxx -o {output} {input}" \
  --manifest-decrypt-command  "age --decrypt -i /run/secrets/cygnus-backup-age.txt -o {output} {input}" \
  --manifest-sign-command     "openssl dgst -sha256 -sign /run/secrets/cygnus-backup-sign.key -out {signature} {input}" \
  --manifest-verify-command   "openssl dgst -sha256 -verify /run/secrets/cygnus-backup-sign.pub -signature {signature} {input}" \
  --report-file /var/backups/cygnus/backup-report.json
```

外层 shell 会在 CLI 接收 argv 模板前展开 `CYGNUS_REPO`、`CYGNUS_RELEASE` 与
release identity 变量。`backup_restore` 刻意不经 shell 执行模板。绝对路径的
`compose-control.sh` 会加载并校验受保护生产环境与不可变 release，锁定生产 Compose
project；恢复时先启动 API + delivery consumer 并证明精确 TLS receipt 路由，再启动两个
worker。裸 `docker compose` 既可能误指向调用者本地栈，也可能让 worker 在路由可用前
发起 delivery。

两个 worker 启动后，wrapper 还要求公开 `/readyz` 返回
`{"status":"ready"}`。生产 Nginx 会持续用 consumer 的 `/health`（签名 secret +
durable receipt table）门控该响应；consumer 丢失时返回有界 `503`，同时 frontend
container 变为 unhealthy。`/livez` 仍只表示 API 进程存活。

占位符：加解密用 `{input}`/`{output}`，签名/验签用 `{input}`/`{signature}`。
命令不经 shell；选用 `age` 与 `openssl dgst` 是因为它们无需重定向。

## 5. 清点 / 校验

在任何破坏性步骤**之前**校验完成标记、工件校验和、明文载荷校验和，以及（传
`--key-material-file` 时）密钥指纹：

```bash
uv run python -m cygnus.runtime.backup_restore inventory \
  --backup-dir /var/backups/cygnus/20260812T000000Z \
  --key-material-file /run/secrets/cygnus-key-material.json \
  --report-file /var/backups/cygnus/inventory-report.json
```

`/run/secrets/cygnus-key-material.json`：

```json
{
  "runtime.secret_key": "<与源运行时一致的 secret>",
  "runtime.mcp_token_pepper": "<与源运行时一致的 pepper>"
}
```

被篡改的工件即使连 manifest 一起重新签名，也会在明文校验层失败
（`artifact_plaintext_checksum_mismatch`）；密钥错误则
`key_material_precondition_failed`。

## 6. 恢复（破坏性）

> 恢复是破坏性操作，**只接受空的一次性目标**：目标库零表、目标桶零对象、
> `--target-id` 与备份源身份不同、`--confirm-target` 与 `--target-id` 精确一致。
> 违反即在任何写入前中止。先跑 `--dry-run`——它执行全部只读预检（包校验、密钥指纹、
> 修订兼容、空目标检查）并输出计划。

```bash
uv run python -m cygnus.runtime.backup_restore restore \
  --backup-dir /var/backups/cygnus/20260812T000000Z \
  --target-database-url "postgresql+asyncpg://cygnus:CHANGE_ME@restore-host:5432/cygnus_restore" \
  --target-redis-url "redis://:CHANGE_ME@restore-host:6379/14" \
  --target-minio-endpoint "restore-minio:9000" \
  --target-minio-access-key "CHANGE_ME" \
  --target-minio-secret-key "CHANGE_ME" \
  --target-minio-bucket "cygnus-restore" \
  --target-environment isolated \
  --target-id "restore-20260812" \
  --confirm-target "restore-20260812" \
  --key-material-file /run/secrets/cygnus-key-material.json \
  --report-file /var/backups/cygnus/restore-report.json
```

加密备份需补 `--artifact-decrypt-command`、`--manifest-decrypt-command`、
`--manifest-verify-command`。生产恢复还需 `--allow-production-restore` 且 manifest
必须加密并签名；该路径视为最后手段。

恢复顺序：

1. 预检：envelope/校验和、密钥指纹、Alembic 修订兼容、明文校验和、`pg_restore --list`。
2. 空目标守卫（数据库 + 桶）——只读，`--dry-run` 同样执行。
3. `pg_restore --exit-on-error`；校验恢复后的 Alembic 修订。
4. 恢复每个 MinIO 对象；**读回并哈希**与 manifest 比对。
5. 执行前向 Alembic 迁移。
6. 对账对象引用（sources/source_images/skills/skill_versions/
   skill_contributions → 桶内 key）。
7. 清空目标 Redis 库，并在**指向目标的独立解释器**中重放记录的 durable outbox
   reconciler——恢复绝不会去扫源运行时的队列。

## 7. 恢复演练（实测 PASS/FAIL）

演练 = 对一次性 isolated 目标执行完整破坏性恢复，再测量恢复证据。这是 CYG-132
的验收证明。

作为 release evidence 时，备份 manifest 和 drill 报告必须绑定精确 source 环境/ID、
完整 Git commit、后端/前端不可变 `@sha256` 镜像引用和 Alembic head。以下目标引用必须
来自已批准的外部恢复目标；占位符故意不可直接使用：

```bash
export CYGNUS_APPROVED_RPO_OBJECTIVE_REF="<approved-RPO-objective-reference>"
export CYGNUS_APPROVED_RTO_OBJECTIVE_REF="<approved-RTO-objective-reference>"
```

```bash
uv run python -m cygnus.runtime.backup_restore drill \
  --backup-dir /var/backups/cygnus/20260812T000000Z \
  --target-database-url "postgresql+asyncpg://cygnus:CHANGE_ME@drill-host:5432/cygnus_drill" \
  --target-redis-url "redis://:CHANGE_ME@drill-host:6379/14" \
  --target-minio-endpoint "drill-minio:9000" \
  --target-minio-access-key "CHANGE_ME" \
  --target-minio-secret-key "CHANGE_ME" \
  --target-minio-bucket "cygnus-drill" \
  --target-environment isolated \
  --target-id "drill-20260812" \
  --confirm-target "drill-20260812" \
  --key-material-file /run/secrets/cygnus-key-material.json \
  --require-recovery-objectives \
  --rpo-max-seconds 60 \
  --rto-max-seconds 1800 \
  --rpo-objective-ref "$CYGNUS_APPROVED_RPO_OBJECTIVE_REF" \
  --rto-objective-ref "$CYGNUS_APPROVED_RTO_OBJECTIVE_REF" \
  --expected-git-commit "$CYGNUS_RELEASE_GIT_COMMIT" \
  --expected-backend-image-ref "$CYGNUS_RELEASE_BACKEND_IMAGE_REF" \
  --expected-frontend-image-ref "$CYGNUS_RELEASE_FRONTEND_IMAGE_REF" \
  --expected-alembic-head "$CYGNUS_RELEASE_ALEMBIC_HEAD" \
  --report-file /var/backups/cygnus/drill-report.json
```

- 退出码 `0` = `"status": "passed"`，`1` = `"status": "failed"`——可直接接入 CI/告警。
- 生产来源备份会在**任何恢复写入前**自动要求数值目标与非空
  `--rpo-objective-ref` / `--rto-objective-ref`。release gate 还必须传
  `--require-recovery-objectives` 与四个 `--expected-*` identity 字段。缺少任一值、
  manifest 缺少 identity 或 identity 不匹配都会在恢复前失败，绝不构成 release evidence。
  工具只绑定运维提供的目标引用，不能伪造或独立批准这些外部记录。
- 未传该 flag 的非生产完整性演练可省略目标值，但即便通过也不是生产/release 认证。
- 提供目标值后，任一实测值超标（或 RPO 无法测量）时演练**失败即关闭**。
- 演练只允许 `--target-environment isolated`；生产目标被拒
  （`drill_target_must_be_isolated`）。

### 演练报告结构（`cygnus-drill-report/v1`）

```jsonc
{
  "report_format": "cygnus-drill-report/v1",
  "operation": "drill",
  "status": "passed",                      // 或 "failed"
  "backup_dir": "/var/backups/cygnus/20260812T000000Z",
  "backup_created_at": "2026-08-12T00:00:00+00:00",
  "source": {"environment": "production", "identity": "prod-01"},
  "release_identity": {
    "git_commit": "<full-40-or-64-character-commit>",
    "backend_image_ref": "<backend>@sha256:<64-hex-digest>",
    "frontend_image_ref": "<frontend>@sha256:<64-hex-digest>",
    "alembic_head": "<exact-backed-up-head>"
  },
  "release_identity_requirement": {
    "manifest_required": true,
    "expected_match_required": true,
    "expected_match_verified": true
  },
  "target": {"environment": "isolated", "identity": "drill-20260812"},
  "rpo": {
    "measured": true,                      // false 且秒数为 null = 未声称
    "seconds": 0.45,
    "basis": "quiesce_completed_to_dump_started",
    "measured_at": "backup"
  },
  "rto": {
    "measured": true,
    "seconds": 42.7,
    "basis": "restore_start_to_verification_complete",
    "measured_at": "drill"
  },
  "objective_refs": {
    "rpo_objective_ref": "<approved-RPO-objective-reference>",
    "rto_objective_ref": "<approved-RTO-objective-reference>"
  },
  "objectives": {"rpo_max_seconds": 60, "rto_max_seconds": 1800},
  "objective_requirement": {
    "required": true,
    "source": "explicit_release_mode",
    "both_declared": true
  },
  "verification": {
    "table_row_counts": {"baseline_tables": 23, "checked": 23, "matched": 23, "mismatches": []},
    "object_hashes":    {"checked": 12, "matched": 12, "mismatches": []},
    "foreign_keys":     {"constraints_checked": 31, "orphan_rows": 0, "orphans": []},
    "idempotency_receipts": {
      "ledger_event_duplicate_idempotency_keys": [],
      "ledger_event_count": {"expected": 5, "actual": 5, "matched": true, "measured": true},
      "outbox_job_id_duplicates": [],
      "outbox_row_count": {"expected": 2, "actual": 2, "matched": true, "measured": true}
    },
    "pending_jobs": {"nonterminal_outbox_rows_after_replay": 0, "checked_statuses": ["pending", "dispatching"]},
    "redis": {"dbsize": 3, "arq_key_count": 2, "expected_arq_job_ids": 1, "enqueued_outbox_without_arq_job": []},
    "encrypted_config": {"checked": true, "sensitive_keys_checked": 2, "decrypt_ok": 2, "decrypt_failures": []}
  },
  "restore": {"completed_stages": ["database_restored", "objects_restored", "forward_migrations_applied", "object_references_reconciled", "durable_outboxes_replayed"], "object_count": 12},
  "checks": [
    {"name": "table_row_counts", "passed": true, "detail": "23/23 tables matched"},
    {"name": "object_hashes", "passed": true, "detail": "12/12 objects matched"},
    {"name": "foreign_key_integrity", "passed": true, "detail": "31 constraints checked, 0 orphan rows"},
    {"name": "idempotency_receipts", "passed": true, "detail": "0 duplicate ledger idempotency keys, 0 duplicate outbox job ids, ledger rows matched, outbox rows matched"},
    {"name": "pending_jobs_replayed", "passed": true, "detail": "0 non-terminal outbox rows remain after replay"},
    {"name": "redis_replay", "passed": true, "detail": "dbsize=3, arq keys=2, expected=1, missing=[]"},
    {"name": "encrypted_config_continuity", "passed": true, "detail": "2/2 sensitive values decrypt"},
    {"name": "rpo_objective", "passed": true, "detail": "measured rpo 0.45s (max 60s)"},
    {"name": "rto_objective", "passed": true, "detail": "measured rto 42.7s (max 1800s)"}
  ],
  "generated_at": "2026-08-12T01:00:00+00:00"
}
```

### 各项检查证明什么

- `table_row_counts` — 恢复后每个 public 表的行数与 manifest 中静默期采样的基线一致。
- `object_hashes` — 从目标桶读回每个对象，哈希与 manifest 明文校验和一致。
- `foreign_key_integrity` — 对 `public` 中每个已校验 FK 约束做通用 MATCH SIMPLE
  孤儿扫描，孤儿行数为 0。
- `idempotency_receipts` — `governance_ledger_events.idempotency_key` 与
  `wiki_draft_ai_pre_review_dispatches.job_id` 零重复，行数与备份一致——重放没有
  产生重复副作用。
- `pending_jobs_replayed` — durable reconciler 跑完后，outbox 不再残留
  `pending`/`dispatching` 行。
- `redis_replay` — 目标 Redis 库已清空，且每个 `enqueued` outbox 行都有对应
  `arq:job:<id>` 键。
- `encrypted_config_continuity` — 提供的 `runtime.secret_key`（其指纹已记录于备份）
  能解密所有恢复后的敏感 `app_config` 值。

### RPO / RTO 语义（只报实测，绝不臆造）

- **RPO** 在**备份时**测量：`dump_started_at − quiesce_completed_at`，即
  `pg_dump` 快照之前的运维静默窗口，是备份内数据年龄的上界。存入 manifest
  （`consistency_boundary.measured_rpo_upper_bound_seconds`），演练以
  `"basis": "quiesce_completed_to_dump_started"` 上报。
- **RTO** 在**演练时**测量：从恢复开始到校验完成（含验证阶段）的墙钟时间
  （`restore_start_to_verification_complete`）。
- 无法测量时（旧包无边界时间戳、未提供密钥、无基线），字段输出
  `"measured": false`、`"seconds": null` 并附 `reason`，**绝不**用默认值或估算值代替。
  设定了目标值而无法测量时演练失败。

## 8. 密钥连续性

`runtime.secret_key` 加密敏感 `app_config` 值（Fernet）并签 JWT；
`runtime.mcp_token_pepper` 哈希 MCP bearer token。两者在源与恢复目标间必须一致：

- 备份只记录 SHA-256 指纹。
- 恢复/演练/带 key 文件的清点需要真实值；缺失、错误或部分提供都会以
  `key_material_precondition_failed` 中止（details 逐键说明 `missing` /
  `fingerprint_mismatch`）。
- 备份后轮换 `secret_key` 会使该备份的加密配置连续性失效；先轮换密钥，再重新备份。

## 9. 失败即关闭的错误码

| 错误码 | 含义 / 运维动作 |
| --- | --- |
| `required_backup_file_missing` / `backup_json_invalid` | 包结构损坏；不要恢复。 |
| `completion_marker_checksum_mismatch` / `manifest_checksum_mismatch` | 包被篡改或截断；不要恢复。 |
| `backup_artifact_validation_failed` / `artifact_plaintext_checksum_mismatch` | 工件缺失/损坏（即使重新签名）；不要恢复。 |
| `key_material_precondition_failed` | 提供的密钥与备份指纹不符；提供源密钥。 |
| `database_not_at_repository_head` / `backup_revision_unknown` | 备份拒绝非 head 库，或包修订不在当前检出中；先迁移/换版本。 |
| `release_identity_required` / `release_identity_mismatch` / `release_alembic_head_mismatch` / `release_git_commit_mismatch` | 生产/发布证据缺少或不匹配 Git、镜像或 Alembic identity；修正已部署 release 记录后重新备份或演练。 |
| `drill_recovery_objectives_required` | 演练缺少数值 RPO/RTO、目标引用或 release 所需参数；在任何恢复写入前补齐。 |
| `restore_target_confirmation_mismatch` / `restore_target_matches_source` | 目标身份未确认或等于源；修正 `--target-id`/`--confirm-target`。 |
| `restore_target_database_not_empty` / `restore_target_bucket_not_empty` | 破坏性恢复守卫；准备空的一次性目标。 |
| `production_restore_guard_required` / `production_manifest_protection_required` | 生产路径需要显式标志与加密签名 manifest。 |
| `drill_target_must_be_isolated` | 演练只进一次性 isolated 目标。 |
| `restore_target_storage_missing` / `restore_target_configuration_missing` | 目标 MinIO/DB/Redis 未提供；恢复要求显式目标配置。 |
| `queue_reconciler_unavailable` | 记录的 durable reconciler 在当前运行时不可用；用 `--queue-reconciler` 覆盖或修复打包。 |
| `restore_execution_failed` | 恢复中途中止；**丢弃目标**（details 含 `target_requires_discard: true` 与 `completed_stages`）。 |
| `external_command_failed` / `required_tool_missing` | quiesce/resume/加密/psql 命令失败；看 `details.returncode`，备份场景源已恢复（backup），恢复场景需丢弃目标。 |

## 10. 本地演练栈（一次性）

例行演练可起一个可抛弃的栈再恢复：

```bash
docker compose -p cygnus-drill up -d postgres redis minio
# 已有源备份；按 §7 演练命令指向演练容器
# （主机端口 5432/6379/9000，专用 DB、Redis db 14、专用空桶）。
docker compose -p cygnus-drill down -v   # 全部丢弃
```

演练的空目标守卫使其可安全复用同一套容器：目标库或桶非空时，演练在任何写入前中止。
