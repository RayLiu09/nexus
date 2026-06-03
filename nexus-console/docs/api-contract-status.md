# NEXUS Console — API Contract Status

> 编制时间：2026-06-03
> 基于：v0.2 基线审计 + P1 认证/API 对齐
> 状态标记：`ready` / `partial` / `mock` / `planned`

---

## 状态定义

| 标记 | 含义 |
|------|------|
| `ready` | 后端已实现并通过验证，前端直接使用 |
| `partial` | 后端部分实现，前端已对接但可能存在字段差异或未完整测试 |
| `mock` | 前端使用 mock 数据，后端未实现或不可用 |
| `planned` | API 已设计但前后端均未实现，仅存在于规划中 |

---

## 一、认证 (Auth)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/auth/login` | POST | `planned` | `/login` (via `/api/auth/login` proxy) | Bearer JWT 签发，返回 access_token + refresh_token |
| `/v1/auth/refresh` | POST | `planned` | `lib/api.ts` (401 retry) | 使用 httpOnly refresh_token cookie 换新 access_token |
| `/v1/auth/logout` | POST | `planned` | `lib/auth/session.ts` (logout) | 失效 refresh_token |

---

## 二、数据源 (Data Sources)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/data-sources` | GET | `partial` | `/workbench`, `/data-sources`, `/ingest`, `/ingest/batch` | 列表查询，需确认分页/过滤参数 |
| `/v1/data-sources/{id}` | GET | `partial` | `/data-sources/[id]` | 单条详情 |
| `/v1/data-sources` | POST | `partial` | `/data-sources/new` | 创建数据源，需 Idempotency-Key |
| `/v1/data-sources/{id}` | DELETE | `planned` | `/data-sources/[id]` | P1.3 危险操作，需 ConfirmButton |

---

## 三、数据接入 (Ingest)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/ingest/batches` | GET | `partial` | `/workbench`, `/data-sources/[id]`, `/ingest` | 批次列表 |
| `/v1/ingest/batches/{id}` | GET | `partial` | `/ingest/batch` (via `/api/ingest/batches/[id]` proxy) | 批次详情+状态 |
| `/v1/ingest/files` | POST | `partial` | `/ingest` (Server Action) | 单文件上传接入 |
| `/v1/ingest/files/multi` | POST | `partial` | `/ingest/batch` (via `/api/ingest/files/multi` proxy) | 批量文件上传 |

---

## 四、原始数据与作业 (Raw Objects & Jobs)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/raw-objects` | GET | `partial` | `/workbench`, `/data-sources/[id]`, `/raw-ledger` | 原始对象列表，需服务端分页 |
| `/v1/jobs` | GET | `partial` | `/workbench`, `/jobs` | 作业列表 |
| `/v1/jobs/{id}/stages` | GET | `partial` | `/jobs` | 作业阶段详情 |
| `/v1/jobs/{id}/retry` | POST | `planned` | `/jobs` | P1.3 批量操作，需 ConfirmButton |
| `/v1/jobs/{id}/cancel` | POST | `planned` | `/jobs` | P1.3 批量操作，需 ConfirmButton |

---

## 五、资产 (Assets)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/assets` | GET | `partial` | `/workbench`, `/assets` | 资产目录列表 |
| `/v1/assets/{id}` | GET | `partial` | `/assets/[assetId]` | 资产详情 (AssetDetail: asset + versions + normalized_refs) |
| `/v1/normalized-refs` | GET | `partial` | `/workbench` | 标准化引用列表 |
| `/v1/normalized-refs/{refId}/governance-result` | GET | `partial` | `/governance` (DecisionTrailDrawer) | 治理结果详情，支持 `?view=` 参数 |
| `/v1/parse-artifacts` | GET | `partial` | `/assets/[assetId]` | 解析产物列表 |

---

## 六、AI 治理 (AI Governance)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/ai/governance-runs` | GET | `partial` | `/workbench`, `/governance`, `/my-workspace` | AI 治理运行列表 |
| `/v1/ai/governance-runs?normalized_ref_id={refId}` | GET | `partial` | `/assets/[assetId]` | 按标准化引用过滤 |
| `/v1/ai/governance-runs/{id}/adopt` | POST | `planned` | `/governance` | P5.1 裁定操作 |
| `/v1/ai/governance-runs/{id}/reject` | POST | `planned` | `/governance` | P5.1 裁定操作 |
| `/v1/ai/governance-runs/{id}/override` | POST | `planned` | `/governance` | P5.1 裁定操作 |

---

## 七、AI Prompt 配置 (AI Prompts)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/ai/prompt-profiles` | GET | `partial` | `/ai-prompts` | Prompt 模板列表 |
| `/v1/ai/prompt-profiles` | POST | `partial` | `/ai-prompts` (client fetch) | 创建 Prompt 模板 |
| `/v1/ai/prompt-profiles/{id}` | PUT | `partial` | `/ai-prompts` (client fetch) | 更新 Prompt 模板 |
| `/v1/ai/prompt-profiles/{id}/disable` | POST | `partial` | `/ai-prompts` (client fetch) | 禁用 Prompt 模板 |

---

## 八、治理规则 (Governance Rules)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/admin/governance-rules` | GET | `partial` | `/rules`, `/search` | 获取规则 JSON，需 ETag |
| `/v1/admin/governance-rules` | PUT | `partial` | `/rules` | 保存规则，需 `If-Match` ETag + `?recompute=true` |

---

## 九、标签审核 (Tag Review)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/tags/pending` | GET | `mock` | `/tag-review` | 当前使用 mock 数据 |
| `/v1/tags/committed` | GET | `mock` | `/tag-review` | 当前使用 mock 数据 |
| `/v1/tags/{id}/approve` | POST | `planned` | `/tag-review` | P5.2 批量审核 |
| `/v1/tags/{id}/reject` | POST | `planned` | `/tag-review` | P5.2 批量审核 |

---

## 十、检索与问答 (Search & QA)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/search` | GET | `partial` | `/search` (via `/api/search` proxy) | RAGFlow 检索，参数: q, kb, top_k, similarity_threshold |
| `/v1/qa` | GET | `partial` | `/search` (via `/api/qa` proxy) | RAGFlow QA，参数: q, kb, top_k |

---

## 十一、身份与组织 (Identity)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/org-units` | GET | `partial` | `/iam-audit` | 组织单元列表 |
| `/v1/users` | GET | `partial` | `/iam-audit` | 用户列表 |

---

## 十二、API Caller 管理

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/api-callers` | GET | `partial` | `/iam-audit`, `/api-callers` | API 调用方列表 |
| `/v1/api-callers` | POST | `planned` | `/api-callers` | 创建 API Caller，返回一次性 token |
| `/v1/api-callers/{id}` | DELETE | `planned` | `/api-callers` | 吊销 API Caller（P1.3 危险操作） |

---

## 十三、运行时与审计 (Runtime & Audit)

| Endpoint | Method | Status | 使用页面 | 备注 |
|----------|--------|--------|----------|------|
| `/v1/runtime/state` | GET | `partial` | `/workbench` | 运行时健康状态 |
| `/v1/audit-logs` | GET | `partial` | `/workbench`, `/iam-audit`, `/my-workspace` | 审计日志列表 |

---

## 汇总

| 分类 | ready | partial | mock | planned | 合计 |
|------|-------|---------|------|---------|------|
| Auth | 0 | 0 | 0 | 3 | 3 |
| Data Sources | 0 | 3 | 0 | 1 | 4 |
| Ingest | 0 | 4 | 0 | 0 | 4 |
| Raw Objects & Jobs | 0 | 3 | 0 | 2 | 5 |
| Assets | 0 | 5 | 0 | 0 | 5 |
| AI Governance | 0 | 2 | 0 | 3 | 5 |
| AI Prompts | 0 | 4 | 0 | 0 | 4 |
| Governance Rules | 0 | 2 | 0 | 0 | 2 |
| Tag Review | 0 | 0 | 2 | 2 | 4 |
| Search & QA | 0 | 2 | 0 | 0 | 2 |
| Identity | 0 | 2 | 0 | 0 | 2 |
| API Caller | 0 | 1 | 0 | 2 | 3 |
| Runtime & Audit | 0 | 2 | 0 | 0 | 2 |
| **总计** | **0** | **32** | **2** | **13** | **47** |

---

## 待办事项

- [ ] 与后端逐接口对齐，将 `partial` 升级为 `ready`
- [ ] 确认分页参数规范（page/pageSize vs offset/limit）
- [ ] 确认 `trace_id` 响应头/体统一格式
- [ ] `/v1/api-callers` POST 返回 token 格式确认（一次性展示）
- [ ] `/v1/tags/*` 系列接口定义（当前完全 mock）
- [ ] `/v1/jobs/{id}/retry` 和 `/v1/jobs/{id}/cancel` 接口设计
- [ ] Auth 三接口 (`/v1/auth/*`) 后端实现排期
