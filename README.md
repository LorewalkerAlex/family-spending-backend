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
├── transactions
├── enrichments
├── review indexes
├── spending projection
├── financial projection
└── operational status
```

查询直接读取 Read Model。命令先持久化相关事实或决策，再增量更新受影响的内存状态，然后返回成功。

## 6. Mutation 设计

旧系统的主要性能问题是任何写操作都会重新读取和解析全部 Evidence，再完整重建 Runtime Snapshot。新项目不得延续这一行为。

每个 command 必须声明其影响范围，例如：

```text
NO_CHANGE
FEEDBACK_ONLY
PROJECTIONS
ENRICHMENTS_AND_PROJECTIONS
TRANSACTIONS_AND_DOWNSTREAM
FULL_REBUILD
```

典型映射：

| Command | Impact |
| --- | --- |
| 创建或处理 Feedback | `FEEDBACK_ONLY` |
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

