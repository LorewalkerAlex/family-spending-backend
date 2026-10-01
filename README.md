# Family Spending Backend

Family Spending Backend 是 Family Spending Insights 的下一代独立后端项目。本仓库只负责财务数据、业务规则、后台任务和版本化 HTTP API，不包含 Web、微信小程序或 Android UI。

本文是新项目的启动说明，也是后续 Session 的架构基线。开始编码前，应先阅读项目根目录未来补充的 `AGENTS.md`；若它与本文冲突，以用户最新决定和 `AGENTS.md` 为准。

## 1. 项目来源

现有系统位于：

```text
F:\OtherProjects\family-spending-insights
```

当前稳定基线包括：

```text
84b0322 feat: enable periodic CMB email acquisition
959d29b chore: remove legacy implementation and tooling
```

旧项目仍是当前可运行系统和迁移行为基线。新项目不得直接修改、移动或删除旧项目的 `data/`；迁移必须使用副本，并通过明确的 parity verification 后才能切换生产服务。

## 2. 已确认的产品边界

- Backend、Web 和 Android 是三个独立项目、独立构建产物和独立发布单元。
- 微信小程序停止开发，不迁移 Mini UI 代码。
- Desktop Web 继续存在，但不放在本项目中。
- Android App 将作为新的移动客户端，但不放在本项目中。
- Backend 是全部 household data 和财务规则的唯一所有者。
- Web 与 Android 只能通过版本化 HTTP API 使用 Backend。
- 认证必须预留扩展口，但当前阶段不实现登录、Token、用户或角色系统。
- 当前阶段继续使用本地文件持久化和内存 Read Model。
- 数据库属于后续阶段，当前不引入 PostgreSQL、SQLite ORM 或数据库迁移框架。
- 当前不引入 Redis、Kafka、Celery、微服务或 Event Sourcing。

## 3. 目标部署形态

```text
                            Caddy Gateway
                           /             \
                          /               \
                 Web Static App       Backend API
                                           ▲
                                           │ HTTPS/JSON
                                      Android App
                                           │
                           ┌───────────────┴───────────────┐
                           │                               │
                    Local Files                    Memory Read Model
                raw evidence + state              indexes + projections
```

Caddy 属于独立的 `eurexis-gateway` 项目。Web 域名或 Web 路由指向 Web 容器；API 域名或 `/api` 路由直接指向 Backend，不再要求经过 Web Nginx 才能访问 Backend。

## 4. 当前阶段的 Backend 运行形态

使用本地文件期间，Backend 必须保持单进程、单实例：

```text
Backend Process
├── HTTP API
├── Application Services
├── Financial Mutation Coordinator
├── Memory Read Model
├── Parsed Evidence Cache
├── IMAP Source Supervisor
└── Scheduled Input Supervisor
```

约束：

- 只允许一个 Backend 实例挂载并修改生产 `data/`。
- 不做多副本或横向扩容。
- API、IMAP polling 和 Scheduler 暂时在同一进程内运行。
- Backend 运行时，不允许另一个 CLI 或临时容器直接修改同一份生产数据。
- 所有生产写操作必须经过 Application use case 和统一 mutation boundary。
- 完整 rebuild 只能用于启动、恢复、诊断、schema/parser 升级和一致性验证。

## 5. 数据原则

### 5.1 持久化真相

本地文件是当前阶段的 durable source of truth：

```text
data/
├── evidence/
│   ├── cmb-email/*.eml
│   └── manual/
├── state/
│   ├── identity/
│   ├── enrichment/
│   ├── mappings/
│   ├── schedules/
│   └── feedback/
└── derived/
```

- Raw EML 必须保持不可变并使用内容身份。
- SourceLink、Mapping 和人工 Enrichment Decision 是 durable decisions。
- Derived cache、index 和 projection 必须可以从持久化真相重建。
- 金额使用 Decimal 语义，不经过二进制浮点数。
- ID 不得依赖文件路径、数组位置或某版 parser 的遍历顺序。
- 每种持久化格式都应具备明确的 schema/parser version。

### 5.2 内存状态

内存只保存可恢复的查询状态：

```text
HouseholdReadModel
├── finance
│   ├── transactions / enrichments
│   ├── query indexes
│   └── spending / financial projections
├── automation
│   ├── scheduled rules
│   └── execution state
└── feedback
```

查询直接读取 Read Model。命令先持久化相关事实或决策，再增量更新受影响的内存状态，然后返回成功。

## 6. Mutation 设计

旧系统的主要性能问题是任何写操作都会重新读取和解析全部 Evidence，再完整重建 Runtime Snapshot。新项目不得延续这一行为。

每个 command 必须声明其影响范围，例如：

```text
NO_CHANGE
FEEDBACK_ONLY
AUTOMATION_ONLY
PROJECTIONS
ENRICHMENTS_AND_PROJECTIONS
TRANSACTIONS_AND_DOWNSTREAM
FULL_REBUILD
```

典型映射：

| Command | Impact |
| --- | --- |
| 创建或处理 Feedback | `FEEDBACK_ONLY` |
| 修改 Scheduled Rule 且没有到期记录 | `AUTOMATION_ONLY` |
| 无到期记录的 Scheduler tick | `NO_CHANGE` |
| 修改 Mapping | `ENRICHMENTS_AND_PROJECTIONS` |
| 修改单笔 Enrichment | `ENRICHMENTS_AND_PROJECTIONS` |
| 新增 Manual Evidence | `TRANSACTIONS_AND_DOWNSTREAM` |
| 获取到新 EML | 只解析新 Evidence，再更新下游 |
| 启动或恢复 | `FULL_REBUILD` |

不要使用模糊的 `rebuild=False` 布尔参数；影响范围应是显式类型，并由测试约束。

## 7. CMB Evidence 解析

EML 是不可变、内容寻址的证据，解析结果必须缓存。建议缓存键：

```text
evidence_sha256 + parser_version
```

一次解析应同时产生：

- statement date；
- normalized SourceRecords；
- skipped/diagnostic information；
- parser version。

SourceRecord 和 statement metadata 不得分别重新解析同一封 EML。第一阶段可以使用进程内缓存；持久化 derived cache 可在行为稳定后加入。

## 8. Backend 模块边界

建议保持模块化单体：

```text
src/family_spending_backend/
├── domain/
├── application/
│   └── ports/
├── sources/
│   ├── cmb_email/
│   └── manual/
├── persistence/
│   └── filesystem/
├── read_model/
├── runtime/
├── bootstrap/
├── interfaces/
│   ├── http/
│   └── cli/
└── config.py
```

依赖方向：

```text
interfaces ──► application ──► domain
runtime ─────► application
sources ─────► application ports
persistence ─► application ports
read_model consumes domain/application results
```

Domain 不得依赖 Path、JSON、YAML、HTTP、IMAP 或具体数据库。Application 不得直接读写 household files。

## 9. API V1

Backend 应从一开始提供版本化 API：

```text
/api/v1/health
/api/v1/runtime/status
/api/v1/transactions
/api/v1/analytics/*
/api/v1/mapping-reviews
/api/v1/mapping-reviews/recommend
/api/v1/manual-inputs
/api/v1/scheduled-inputs
/api/v1/feedback
```

API 要求：

- Request/Response DTO 与 Domain model 分离。
- 统一错误结构和稳定错误码。
- 列表接口预留分页、过滤和排序。
- 提供机器可读 OpenAPI contract。
- Web 与 Android 从同一 contract 生成或校验 API Client。
- API 不暴露本地文件路径和存储格式。
- 不为了旧前端永久保留无版本 compatibility endpoint。

### 9.1 Mapping Recommendation

`GET /api/v1/mapping-reviews` 会为每个待处理 description 附带 `recommendation`，客户端可直接把建议的 Merchant 和 Category 预填到人工审核表单。`POST /api/v1/mapping-reviews/recommend` 接受单个当前未分类 expense description，返回相同的只读建议。

Recommendation 是从当前已审核 Mapping 派生的可丢弃状态，不是 Mapping 或 Enrichment Decision。读取推荐不会写文件、不会发布新 generation，也不会自动应用结果；客户端仍须调用 preview/apply 完成人工确认。`rank_score` 是排序分而不是概率，`score_margin` 表示第一名与第二名的差距，`confidence` 同时受两者约束。算法版本通过 `model_version` 返回。

## 10. 认证扩展口

当前不实现认证，但 HTTP 入口必须预留统一边界：

```text
HTTP Request
    ↓
Authenticator
    ↓
RequestContext / Principal
    ↓
Application
```

当前模式：

```text
AUTH_MODE=disabled
Principal(user_id="owner", roles=("owner",))
```

未来可以增加 token、password 或 OIDC adapter。业务 use case 不得自行读取 Authorization header；Web 和 Android Client 也应预留 credential provider/interceptor，但当前可以返回空凭据。

## 11. 可观测性

所有 command 至少记录：

```text
request_id
command
lock_wait_ms
mutation_ms
persistence_ms
read_model_update_ms
total_ms
result
```

Runtime status 应能报告：

- 当前 generation；
- 最近成功/失败 mutation；
- 排队 mutation 数量；
- 最近 IMAP poll；
- 最近 Scheduler tick；
- Evidence parser cache 命中情况；
- 当前数据数量和 schema/parser version。

日志不得输出邮箱授权码或其他 credentials。

## 12. 数据库迁移预留

未来迁移数据库时，目标是替换 persistence adapter，而不是重写 Domain、Application、API 或客户端。

迁移流程应为：

```text
现有文件副本
    ↓
一次性 importer
    ↓
数据库候选状态
    ↓
identity / count / projection parity verification
    ↓
备份并切换 persistence implementation
```

当前不要为未来数据库提前引入通用 ORM Repository。继续使用按业务能力划分的 ports，例如 EvidenceStore、IdentityStore、MappingStore、DecisionStore、ScheduleStore 和 FeedbackStore。

## 13. 非目标

当前阶段明确不做：

- Android UI；
- Web UI；
- 微信小程序；
- 用户注册和登录；
- 多家庭或多租户；
- 数据库；
- 独立 Worker 进程；
- 多实例部署；
- 离线双向同步；
- 消息队列；
- 微服务拆分。

## 14. 建议实施顺序

1. 补充 `AGENTS.md`，确认工程规则和验收命令。
2. 建立最小 Python package、测试和格式化基础设施。
3. 定义 API V1 DTO、错误结构和 OpenAPI contract。
4. 从旧项目迁移 Domain，并使用 parity tests 锁定行为。
5. 迁移 filesystem stores，但保持旧生产数据只读。
6. 实现版本化 CMB parser cache。
7. 实现 Memory Read Model 和显式 Mutation Impact。
8. 迁移 Application use cases。
9. 建立只读 importer，对旧 `data/` 副本执行 parity verification。
10. 完成 Backend Docker image、健康检查、备份和恢复流程。
11. API 稳定后再启动独立 Web 项目和 Android 项目。

## 15. 第一阶段完成标准

新 Backend 在接入真实客户端前至少满足：

- 可以从旧数据副本恢复相同的 SourceRecord、Transaction 和 Mapping identity。
- Spending 与 Financial Projection 通过 parity verification。
- Feedback command 不触发财务 rebuild。
- 无变化的 Scheduler tick 不发布新 generation。
- 已解析 EML 不会在普通 command 中重复解析。
- API V1 contract tests 完整通过。
- 所有写入具备明确 mutation scope 和失败回滚语义。
- `data/` 可以备份、恢复并通过完整性检查。
- Docker 中只运行一个有权写入生产数据的 Backend 实例。

## 16. 当前实现状态

第一阶段 Backend 已按本文边界落地：

- 稳定的 SourceRecord、Transaction、SourceLink、Mapping、Enrichment、Feedback 和 Scheduled Input 领域模型；
- fail-closed `manifest.json`、严格 JSON/YAML/JSONL store、原子单文件替换和跨文件失败回滚；
- 不可变、内容寻址的 CMB EML Evidence，以及以 `evidence_sha256 + parser_version` 为键的进程内解析缓存；
- 可完整重建的不可变 `HouseholdReadModel`，按 finance、automation 和 feedback 子树组织；
- single-writer Mutation Coordinator、类型化 `ReadModelChange`、集中 `ReadModelProjector`、原子 publication 和结构化 mutation timing 日志；
- 类型化 `ApplicationContainer` 和集中 lifecycle；FastAPI 路由通过 dependency 获取容器，不直接定位动态 `app.state` 服务；
- Manual Input、单笔 Enrichment、Mapping Review、Feedback、Scheduled Input 和 Source Sync 应用用例；
- Mapping Review 的非权威 Merchant/Category 预填推荐、结构化备选、解释信号、分数/分差置信度和只读推荐接口；
- `/api/v1` 统一成功/错误结构、request ID、分页/过滤/排序、OpenAPI contract 和 `AUTH_MODE=disabled` 认证边界；
- 同进程 Scheduler 与可选 163 IMAP Source Supervisor；IMAP 使用只读 mailbox 和 `BODY.PEEK`；
- 只读源 importer、完整 identity/state/projection parity verifier、integrity checker、校验和 ZIP backup 和 staged restore；
- 单 worker Docker image、只读容器根文件系统、持久数据卷、健康检查和 data-root OS advisory lock。

查询只消费当前 Read Model；普通 command 不重新解析全部 EML。Feedback 和纯 Schedule 配置修改只替换各自子树，无变化的 Scheduler tick 不发布 generation。财务命令只携带 finance state，不再搬运无关 Feedback/Schedule 状态。所有生产写用例均通过统一 coordinator 和 `FileUnitOfWork`，后台 CMB 获取也把新 Evidence、identity 和 enrichment 放在同一回滚边界中。

推荐算法的评估口径、限制和当前基线见 [`docs/recommendation-evaluation.md`](./docs/recommendation-evaluation.md)，关键架构决策见 [`docs/adr/`](./docs/adr/)；推荐质量数字是回归证据，不是对未知商户准确率的承诺。

领域术语由根目录 [`CONTEXT.md`](./CONTEXT.md) 维护。第一阶段非目标仍以第 13 节为准；当前没有 UI、登录系统、数据库、多实例或独立 Worker。

## 17. 本地开发与验收

要求 CPython 3.14 或更高版本。Python 版本由 `.python-version` 声明，完整依赖图由 `uv.lock` 固定。首次准备环境或锁文件更新后执行：

```powershell
uv sync --frozen
```

正式验收命令：

```powershell
uv lock --check
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest
uv pip check
uv build
```

修改 `pyproject.toml` 中的依赖时使用 `uv lock` 更新锁文件，再执行 `uv sync --frozen`；不要用 `pip install` 绕过项目锁文件。

pytest 会把 `DeprecationWarning` 和 `PendingDeprecationWarning` 当作错误；HTTP 测试直接使用 ASGI transport，不依赖已弃用的 Starlette TestClient 行为。

本地启动：

```powershell
uv run --frozen family-spending-api
```

默认监听 `127.0.0.1:8000`。首次启动只会初始化空目录；非空但缺少 `manifest.json` 的目录会被拒绝。一个 data root 同时只能由一个 Backend 进程持有。

主要配置项：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FAMILY_SPENDING_ENVIRONMENT` | `development` | 运行环境：`development`、`test` 或 `production` |
| `FAMILY_SPENDING_DATA_ROOT` | `data` | 本进程拥有的文件数据根目录 |
| `AUTH_MODE` / `FAMILY_SPENDING_AUTH_MODE` | `disabled` | 当前只接受 `disabled` |
| `FAMILY_SPENDING_SCHEMA_VERSION` | `1` | 当前文件 schema 版本 |
| `FAMILY_SPENDING_PARSER_VERSION` | `cmb-v1` | CMB Evidence parser cache 版本 |
| `FAMILY_SPENDING_SCHEDULER_ENABLED` | `true` | 是否启用启动 tick 和周期 Scheduler |
| `FAMILY_SPENDING_SCHEDULER_INTERVAL_SECONDS` | `300` | Scheduler 周期秒数 |
| `FAMILY_SPENDING_CMB_EMAIL_POLL_ENABLED` | `false` | 是否启用 163 IMAP 获取 |
| `FAMILY_SPENDING_EMAIL_POLL_INTERVAL_SECONDS` | `300` | IMAP poll 周期秒数 |
| `FAMILY_SPENDING_IMAP_ADDRESS` | 无 | 启用 polling 时必填的邮箱地址 |
| `FAMILY_SPENDING_IMAP_AUTH_CODE` | 无 | 启用 polling 时必填的授权码；不得写入仓库或日志 |
| `FAMILY_SPENDING_IMAP_HOST` | `imap.163.com` | IMAP host |
| `FAMILY_SPENDING_IMAP_PORT` | `993` | IMAP TLS port |
| `FAMILY_SPENDING_IMAP_MAILBOX` | `INBOX` | 只读搜索的 mailbox |
| `FAMILY_SPENDING_IMAP_SUBJECT_KEYWORD` | `招商银行信用卡电子账单` | 账单主题过滤词 |
| `FAMILY_SPENDING_IMAP_SINCE` | `01-Jan-2020` | IMAP `SENTSINCE` 起点，格式 `DD-Mon-YYYY` |
| `FAMILY_SPENDING_IMAP_TIMEOUT_SECONDS` | `30` | IMAP 连接超时秒数 |
| `FAMILY_SPENDING_BIND_HOST` | `127.0.0.1` | HTTP bind host |
| `FAMILY_SPENDING_BIND_PORT` | `8000` | HTTP bind port |

## 18. 导入、校验、备份与恢复

这些命令是离线运维入口。操作当前 Backend 数据前应先停止 Backend；不要把旧生产 `data/` 本身作为 importer source，先复制它：

```powershell
Copy-Item -LiteralPath F:\OtherProjects\family-spending-insights\data `
  -Destination .\legacy-data-copy -Recurse

uv run --frozen family-spending-admin import `
  --source .\legacy-data-copy `
  --target .\data `
  --parser-version cmb-v1

uv run --frozen family-spending-admin parity `
  --left .\legacy-data-copy `
  --right .\data `
  --parser-version cmb-v1

uv run --frozen family-spending-admin integrity-check `
  --data-root .\data `
  --parser-version cmb-v1
```

Importer 永不写 source，且拒绝把 target 放在 source 内。Target 必须不存在或为空；数据先在 sibling staging 目录完成严格读取、完整 rebuild 和 parity，再原子发布。

备份与恢复：

```powershell
uv run --frozen family-spending-admin backup `
  --data-root .\data `
  --output .\backups\family-spending.zip `
  --parser-version cmb-v1

uv run --frozen family-spending-admin restore `
  --archive .\backups\family-spending.zip `
  --target .\restored-data `
  --parser-version cmb-v1
```

Backup 包含 durable truth 和逐文件 SHA-256，不包含 `derived/` 或 `.backend.lock`。Restore 会拒绝重复路径、路径穿越、文件清单或 checksum 不一致，并在 staging 完整 rebuild 通过后才发布到空 target。

## 19. Docker 运行

Compose 延续旧项目已经验证的部署方式，使用宿主机 `./data` bind mount 保存权威数据。首次部署先复制配置模板，并确保 `PUID`/`PGID` 与服务器上 `./data` 的所有者一致；邮箱授权码只写入未提交的 `.env`。

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Compose 只定义一个固定名称的 Backend service；容器以非 root 用户、单 Uvicorn worker、只读 root filesystem 运行，只有映射到 `/app/data` 的宿主机 `./data` 和 `/tmp` tmpfs 可写。API 端口默认只绑定 `127.0.0.1`，由独立 Caddy gateway 提供 HTTPS。不要对该 service 做 scale，也不要让临时容器同时挂载并修改 `./data`。更新使用 `docker compose up -d --build`，停止服务使用 `docker compose down`；Compose 不拥有或删除宿主机数据目录。

服务器准备、数据传输、Caddy 边界、更新和一致性备份步骤见 [`deploy/README.md`](./deploy/README.md)。

## 20. 第一阶段验收记录

2026-10-01 使用旧项目真实 `data/` 的只读副本完成了以下链路；验收临时数据和构建产物均在验收后删除，正式迁移前备份保存在仓库外：

- 旧生产目录 20 个文件在验收前后逐文件 SHA-256 一致；
- 12 封 CMB EML 重建为 1,152 个 SourceRecord 和 1,152 个 Transaction；
- 396 个 description mapping identity 一致；
- importer、integrity、backup、restore 和 restore 后 parity 全部通过；
- Spending `total_spending_minor = 12032726`；
- Financial `net_cash_flow_minor = 2687949`；
- 旧实现与新实现的完整 canonical state、Spending payload 和 Financial payload 逐字段相等，规范化结果 SHA-256 为 `9ffe93079637de4b4bbf59835f0f505065d754667a92fab60a60987195e41415`。
- 最终代码再次完成 import、integrity、backup、restore 和 restore 后 parity，结果仍为上述 1,152/396/金额基线。
- 无缓存 Ruff、format check、完整 pytest、弃用警告门禁和依赖检查全部通过；sdist 与 wheel 构建成功。
- 真实 Uvicorn 进程的 Health、Runtime status 和 OpenAPI smoke test 通过；第二个进程被同一 data-root advisory lock 拒绝。

Dockerfile/Compose 契约由自动化测试覆盖。执行实际 image build 仍需要本机或 CI 提供 Docker Engine。
