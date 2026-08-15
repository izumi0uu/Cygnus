# Cygnus Telemetry Runbook (CYG-142)

Companion to `config/observability/alert_rules.yml`. Every alert in that file
resolves to a section here. The `recovery` annotation on each rule states the
exact condition that clears the alert; verify it before closing a page.

## Ownership

| Group | Owner | Scope |
| --- | --- | --- |
| `cygnus_availability` | SecurityBaseline / ReadinessOps | API process, worker heartbeats |
| `cygnus_red` | SecurityBaseline / ToolRuntime | HTTP + MCP RED rates and latency |
| `cygnus_queues_workers` | DurableDispatch | queue age, terminal failures |
| `cygnus_governance` | ApprovalIntegrity / DeliveryReceipt | route exhaustion, propagation mismatch |
| `cygnus_dependencies` | ReadinessOps / TelemetryPlane / DataReliabilityAudit | readiness, pool saturation, telemetry loss, stale evidence |
| `cygnus_release` | ReleaseSupplyChain | release identity |
| `cygnus_capacity_gate` | CapacityCertification | staging capacity thresholds |

## Correlation and evidence

Every request carries one `correlation_id` (UUID) from HTTP through MCP tool
execution, ARQ job payloads, audit rows (`audit_log.correlation_id`), and
outbound delivery receipts. A W3C `traceparent` is derived from the same ID.

When investigating any operational failure:
1. Find the request: `X-Request-ID` echoed on the response.
2. Join across surfaces with `WHERE correlation_id = '<id>'` on
   `audit_log`, `mcp_query_log`, and the delivery receipts table.
3. Metrics carry the same bounded labels (route/tool/queue/role); spans carry
   `cygnus.correlation_id` so traces and metrics align.
4. Sanitization: labels are bounded to 64 chars, secret-shaped values are
   redacted (`<redacted>`), and payloads never appear in metrics or logs.

## Approved alert limits

`config/observability/alert_rules.yml` is a machine-readable template, not a
deployable rule file. Numeric comparison limits are deliberately absent from
source control. Production supplies an approved JSON document through
`CYGNUS_ALERT_THRESHOLDS_FILE`, plus the exact
`CYGNUS_ALERT_APPROVAL_REF`, `CYGNUS_ALERT_THRESHOLDS_REF`, and
`CYGNUS_ALERT_THRESHOLDS_SHA256` bindings. The production-input gate matches
those values to `production-inputs.json`; `scripts/render_alert_rules.py` then
verifies the file hash, the document's own approval refs, and the complete
required-key set before atomically writing `deploy/rendered/alert_rules.yml`.
The required, value-free document shape is published at
`config/observability/alert_thresholds.schema.json`; it contains no fallback
or example pass values.

Missing, placeholder, incomplete, unapproved, or hash-mismatched inputs are a
deployment blocker. There is no checked-in fallback threshold. Every rendered
rule carries the approval ref, threshold ref, and threshold-file hash as alert
labels so an alert can be traced to the exact external decision that created it.

## Alerts

### CygnusApiDown
- **Meaning:** the API process is not scrapable by Prometheus.
- **Run:** `docker compose ps api`; check `docker compose logs api`.
- **Recovery:** `up{job="cygnus-api"} == 1` for 1m.

### CygnusWorkerDead
- **Meaning:** no fresh `cygnus_worker_heartbeat` for a worker role
  (heartbeats are refreshed by the ARQ worker; timeout is
  `worker_heartbeat_timeout_seconds`).
- **Run:** check Redis keys `cygnus:runtime:worker-heartbeat:v1:*`; restart the
  worker service (`docker compose restart worker` / `worker-skills`).
- **Recovery:** `cygnus_worker_heartbeat{role=...} == 1` for 2m.

### ALERT-142-HTTP-ERROR_RATE / ALERT-142-HTTP-DENIAL_RATE / ALERT-142-HTTP-RETRY_RATE / ALERT-142-HTTP-LATENCY
- **Meaning:** an HTTP RED metric exceeded its externally approved, rendered
  limit.
- **Run:** check `cygnus_http_requests_total{status=~"5.."}` and
  `cygnus_http_request_duration_seconds` by route; inspect logs for the
  correlation IDs of failing requests; verify the alert's `approval_ref`,
  `thresholds_ref`, and `thresholds_sha256` labels against deployment evidence.
- **Recovery:** the same metric returns below the approved limit for the rule's
  declared recovery window.

### ALERT-142-MCP-ERROR_RATE / ALERT-142-MCP-DEADLINE
- **Meaning:** an MCP error or deadline metric exceeded its externally approved,
  rendered limit.
- **Run:** query `mcp_query_log` for `tool_name`, `status`, `correlation_id`;
  check provider health (`cygnus_provider_calls_total`) and the alert's approval
  labels.
- **Recovery:** the metric returns below the approved limit.

### ALERT-142-QUEUE-AGE / ALERT-142-QUEUE-TERMINAL
- **Meaning:** queue age or terminal failures exceeded the externally approved,
  rendered limit.
- **Run:** inspect ARQ queue length/age; check worker heartbeat; look at
  `cygnus_queue_jobs_total{state="failed|error"}` and the failing sources.
- **Recovery:** queue age and terminal-failure counts return below their
  approved limits.

### ALERT-142-GOVERNANCE-EXHAUSTED
- **Meaning:** governance route (feedback/review) reached terminal reason
  `exhausted` repeatedly.
- **Run:** inspect governance route state and terminal reasons in the ledger;
  check retry/attempt counters.
- **Recovery:** increase of exhausted terminal events drops to 0.

### ALERT-142-PROPAGATION-MISMATCH
- **Meaning:** publish/propagation mismatch or correlation-loss events.
- **Run:** inspect `cygnus_propagation_mismatch_total{kind=...}`; verify
  delivery receipts and propagation state; re-run the affected propagation.
- **Recovery:** increase drops to 0.

### ALERT-142-READINESS-DEPENDENCY
- **Meaning:** a readiness dependency (database/redis/minio) is not ready.
- **Run:** `curl /api/health` for per-service status; check the failing
  dependency's own health.
- **Recovery:** `cygnus_readiness_dependency{...} == 1` for 5m.

### ALERT-142-POOL-SATURATION
- **Meaning:** DB pool usage exceeded the externally approved, rendered limit.
- **Run:** compare `cygnus_db_pool_connections{state="checked_out"}` with
  `checked_in`; look for leaked sessions or a slow query; verify the alert's
  threshold-identity labels.
- **Recovery:** saturation returns below the approved limit.

### ALERT-142-TELEMETRY-LOSS
- **Meaning:** telemetry writes/exporters are degrading (OTel unavailable,
  exporter initialization failed, series overflow, or registry errors) beyond
  the externally approved limit.
- **Run:** check `cygnus_telemetry_failures_total{component=...}`; verify OTLP
  collector reachability and Prometheus scrape configuration.
- **Recovery:** the failure count returns below the approved limit.

### ALERT-142-STALE-EVIDENCE
- **Meaning:** stale evidence exceeded the externally approved, rendered limit.
- **Run:** identify the evidence kind and trigger the evidence refresh sweep.
- **Recovery:** the count returns below the approved limit.

### ALERT-142-RELEASE-IDENTITY
- **Meaning:** `cygnus_release_info{release="unknown"}` — build/env labels are
  not injected into the running image.
- **Run:** verify `APP_RELEASE` / `APP_COMMIT_SHA` / `APP_IMAGE_REF` env in the
  deployment manifest; rebuild/redeploy with labels.
- **Recovery:** `cygnus_release_info{release!="unknown"} == 1`.

### ALERT-142-CAPACITY-INPUTS-MISSING
- **Meaning:** no approval-bound capacity series exists, or one carries a
  placeholder approval/threshold/target ref or threshold fingerprint.
- **Run:** inspect the `LoadGateReport.config` refs and the exact
  `cygnus_capacity_gate_breach` labels; re-run the production-input and capacity
  gates with the approved CYG-144 inputs.
- **Recovery:** measured capacity series exist and every identity label is
  non-placeholder.

### ALERT-142-<ROUTE>-<METRIC> (capacity gate, 30 capacity + 15 RED keys)
- **Meaning:** a staging capacity-gate threshold was breached for the route
  (publish | ticket_import | ingestion | worker | query).
- **Run:** open the machine-readable `LoadGateReport` for the failing release
  (`cygnus.capacity.report`), read `routes[].checks[]` for
  `{metric, value, threshold, comparator, alert_rule}`, and follow the
  `failure_injection.targets[]` recovery evidence.
- **Recovery:** re-run the gate and observe PASS for the route, or the
  production RED rule (error_rate/denial_rate/retry_rate keys) clearing per
  `cygnus_red` above.
