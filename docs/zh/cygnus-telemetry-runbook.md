# Cygnus 遥测 Runbook（CYG-142）

配套文件：`config/observability/alert_rules.yml`。该文件中的每条告警都在本文件中对应一节。
每条规则上的 `recovery` 注解声明了清除该告警的确切条件；关闭工单前必须验证该条件。

## 归属

| 分组 | 负责人 | 范围 |
| --- | --- | --- |
| `cygnus_availability` | SecurityBaseline / ReadinessOps | API 进程、worker 心跳 |
| `cygnus_red` | SecurityBaseline / ToolRuntime | HTTP + MCP RED 速率与延迟 |
| `cygnus_queues_workers` | DurableDispatch | 队列年龄、终态失败 |
| `cygnus_governance` | ApprovalIntegrity / DeliveryReceipt | 路由耗尽、传播不一致 |
| `cygnus_dependencies` | ReadinessOps / TelemetryPlane / DataReliabilityAudit | 就绪性、连接池饱和、遥测丢失、过期证据 |
| `cygnus_release` | ReleaseSupplyChain | 发布身份 |
| `cygnus_capacity_gate` | CapacityCertification | staging 容量阈值 |

## 关联与证据

每个请求携带一个 `correlation_id`（UUID），从 HTTP 贯穿 MCP 工具执行、ARQ 任务负载、
审计行（`audit_log.correlation_id`）与出站投递回执。同一个 ID 派生出 W3C `traceparent`。

排查任何运维故障时：
1. 找到请求：响应中回显的 `X-Request-ID`。
2. 跨面联查：在 `audit_log`、`mcp_query_log` 与投递回执表上执行
   `WHERE correlation_id = '<id>'`。
3. 指标携带同一组有界标签（route/tool/queue/role）；span 携带
   `cygnus.correlation_id`，使 trace 与指标对齐。
4. 脱敏：标签长度上限 64 字符，疑似密钥的值统一改写为 `<redacted>`，
   指标与日志中绝不出现载荷内容。

## 经审批的告警阈值

`config/observability/alert_rules.yml` 是机器可读模板，不是可直接部署的规则文件。
数值比较阈值不会提交到源码。生产环境必须提供
`CYGNUS_ALERT_THRESHOLDS_FILE`，以及完全匹配的
`CYGNUS_ALERT_APPROVAL_REF`、`CYGNUS_ALERT_THRESHOLDS_REF` 与
`CYGNUS_ALERT_THRESHOLDS_SHA256`。生产输入门禁先把这些值与
`production-inputs.json` 对齐；`scripts/render_alert_rules.py` 再校验文件哈希、
文档内审批引用和完整必填键，最后原子写入
`deploy/rendered/alert_rules.yml`。
必填但不含任何数值默认值的文档结构见
`config/observability/alert_thresholds.schema.json`；其中不存在回退或示例通过值。

缺失、占位、键不完整、未审批或哈希不一致都会阻断部署；不存在源码内回退值。
渲染出的每条规则都带有审批引用、阈值引用和阈值文件哈希标签，可追溯到准确的
外部决策。

## 告警

### CygnusApiDown
- **含义：** Prometheus 无法抓取 API 进程。
- **操作：** `docker compose ps api`；检查 `docker compose logs api`。
- **恢复：** `up{job="cygnus-api"} == 1` 持续 1m。

### CygnusWorkerDead
- **含义：** 某个 worker 角色没有新心跳
  （心跳由 ARQ worker 刷新；超时见 `worker_heartbeat_timeout_seconds`）。
- **操作：** 检查 Redis key `cygnus:runtime:worker-heartbeat:v1:*`；重启对应 worker
  （`docker compose restart worker` / `worker-skills`）。
- **恢复：** `cygnus_worker_heartbeat{role=...} == 1` 持续 2m。

### ALERT-142-HTTP-ERROR_RATE / ALERT-142-HTTP-DENIAL_RATE / ALERT-142-HTTP-RETRY_RATE / ALERT-142-HTTP-LATENCY
- **含义：** HTTP RED 指标突破外部审批并渲染的阈值。
- **操作：** 按路由查看 `cygnus_http_requests_total{status=~"5.."}` 和
  `cygnus_http_request_duration_seconds`；用失败请求的 correlation ID 查日志；
  将告警的 `approval_ref`、`thresholds_ref`、`thresholds_sha256` 标签与部署证据核对。
- **恢复：** 同一指标回落到审批阈值以下并满足规则声明的恢复窗口。

### ALERT-142-MCP-ERROR_RATE / ALERT-142-MCP-DEADLINE
- **含义：** MCP 错误或超时指标突破外部审批并渲染的阈值。
- **操作：** 查询 `mcp_query_log` 的 `tool_name`、`status`、`correlation_id`；
  检查 provider 健康（`cygnus_provider_calls_total`）和告警审批标签。
- **恢复：** 指标回落到审批阈值以下。

### ALERT-142-QUEUE-AGE / ALERT-142-QUEUE-TERMINAL
- **含义：** 队列年龄或终态失败突破外部审批并渲染的阈值。
- **操作：** 检查 ARQ 队列长度/年龄、worker 心跳、
  `cygnus_queue_jobs_total{state="failed|error"}` 与失败源。
- **恢复：** 队列年龄与终态失败计数回落到审批阈值以下。

### ALERT-142-GOVERNANCE-EXHAUSTED
- **含义：** 治理路由（feedback/review）反复到达终态原因 `exhausted`。
- **操作：** 在账本中检查治理路由状态与终态原因；查看重试/尝试计数。
- **恢复：** exhausted 终态事件的增量降为 0。

### ALERT-142-PROPAGATION-MISMATCH
- **含义：** 发布/传播不一致或关联丢失事件。
- **操作：** 查看 `cygnus_propagation_mismatch_total{kind=...}`；核对投递回执与传播状态；
  重新执行受影响的传播。
- **恢复：** 增量降为 0。

### ALERT-142-READINESS-DEPENDENCY
- **含义：** 某个就绪性依赖（database/redis/minio）未就绪。
- **操作：** `curl /api/health` 查看各服务状态；检查故障依赖自身的健康状态。
- **恢复：** `cygnus_readiness_dependency{...} == 1` 持续 5m。

### ALERT-142-POOL-SATURATION
- **含义：** DB 连接池占用突破外部审批并渲染的阈值。
- **操作：** 对比 `cygnus_db_pool_connections{state="checked_out"}` 与
  `checked_in`；排查泄漏会话或慢查询；核对告警阈值身份标签。
- **恢复：** 饱和度回落到审批阈值以下。

### ALERT-142-TELEMETRY-LOSS
- **含义：** 遥测写入/导出器退化（OTel 不可用、导出器初始化失败、系列溢出、
  注册表错误）突破外部审批阈值。
- **操作：** 检查 `cygnus_telemetry_failures_total{component=...}`；确认 OTLP
  collector 可达性与 Prometheus 抓取配置。
- **恢复：** 失败计数回落到审批阈值以下。

### ALERT-142-STALE-EVIDENCE
- **含义：** 过期证据计数突破外部审批并渲染的阈值。
- **操作：** 定位证据 kind；触发证据刷新 sweep。
- **恢复：** 计数回落到审批阈值以下。

### ALERT-142-RELEASE-IDENTITY
- **含义：** `cygnus_release_info{release="unknown"}` —— 构建/环境标签未注入运行镜像。
- **操作：** 核对部署清单中的 `APP_RELEASE` / `APP_COMMIT_SHA` / `APP_IMAGE_REF`
  环境变量；携带标签重新构建/部署。
- **恢复：** `cygnus_release_info{release!="unknown"} == 1`。

### ALERT-142-CAPACITY-INPUTS-MISSING
- **含义：** 不存在绑定审批的容量指标序列，或序列带有占位的审批/阈值/目标引用或
  阈值指纹。
- **操作：** 检查 `LoadGateReport.config` 引用与
  `cygnus_capacity_gate_breach` 的完整标签；使用已审批 CYG-144 输入重新执行生产输入和
  容量门禁。
- **恢复：** 已测量的容量序列存在，且全部身份标签均非占位值。

### ALERT-142-<ROUTE>-<METRIC>（容量门禁，30 个容量键 + 15 个 RED 键）
- **含义：** 该路由（publish | ticket_import | ingestion | worker | query）的
  staging 容量阈值被突破。
- **操作：** 打开失败发布版本的机器可读 `LoadGateReport`
  （`cygnus.capacity.report`），读取 `routes[].checks[]` 中的
  `{metric, value, threshold, comparator, alert_rule}`，并跟进
  `failure_injection.targets[]` 的恢复证据。
- **恢复：** 重新运行门禁并观察到该路由 PASS；或对应的生产 RED 规则
  （error_rate/denial_rate/retry_rate 键）按上文 `cygnus_red` 清除。
