# A3 危险动作清单与 UX 模式（Destructive Actions）

> 阶段 -1 A3 产出。`plan.md` 阶段 2 每个 PR 验收门槛 #10 引用本文件。
> 目标：把"toast 即完成"的高 blast-radius 操作分级，落实到具体 UX 模式。

---

## 模式定义

| 模式                       | 触发场景                          | UX 形式                                                                                         | 影响 |
| -------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------- | ---- |
| `confirm-dialog`           | 不可逆 / 影响他人 / 跨域          | Antd `Modal.confirm`，标题写后果，主按钮置灰直到用户阅读完毕（>= 1.5s）                         | 强制 |
| `two-step-input`           | 高破坏性，需"输入名字"二次确认    | Modal 内 input，输入指定字串方可点击主按钮（如输入 provider 名称）                              | 强制 |
| `undo-toast`               | 可恢复，影响范围局部              | Antd `notification` 含撤销按钮，10s 内可点；后端先 mark 后真删，超时后真生效                    | 默认 |
| `time-locked`              | 配置发布等批量影响                | `Validate → Preview Impact → Confirm`，每段独立按钮；Confirm 后倒计时 5s 才真正下发，期间可中止 | 强制 |
| `optimistic-with-rollback` | 单条记录可恢复（标签确认 / 撤销） | UI 立即更新，请求失败时 toast + 自动回退 + 重试按钮                                             | 隐性 |

---

## 危险动作清单

| 动作                      | 触发位置                    | 模式                       | 二次确认输入 | undo 时长 | 备注                                                                      |
| ------------------------- | --------------------------- | -------------------------- | ------------ | --------- | ------------------------------------------------------------------------- |
| 一键采纳高置信建议        | governance 顶部按钮         | `undo-toast`               | -            | 10s       | 后台才 commit；undo 期间 toast 显示"已采纳 N 条，10s 内可撤销"            |
| 批量裁定                  | governance bulk-bar         | `confirm-dialog`           | -            | -         | 显示选中条数 + 影响范围预览                                               |
| 批量改派                  | governance bulk-bar         | `confirm-dialog`           | -            | -         | 影响责任人 SLA，需确认                                                    |
| 批量重试（作业）          | jobs 顶部                   | `confirm-dialog`           | -            | -         | 仅对 retryable_failed 生效；显示将重试的 job 数                           |
| 重试单个作业              | jobs 详情                   | `optimistic-with-rollback` | -            | -         | UI 立即从 failed 切到 retrying                                            |
| 重处理资产                | asset-detail 顶部           | `confirm-dialog`           | -            | -         | 影响版本历史 + 索引；需确认                                               |
| 重建索引                  | asset-detail 顶部           | `confirm-dialog`           | -            | -         | 影响 RAGFlow，需确认                                                      |
| AI 重评分                 | asset-detail 顶部           | `confirm-dialog`           | -            | -         | 触发 LLM 调用 + 计费；说明"将消耗 LiteLLM quota"                          |
| 发布规则集                | rules                       | `time-locked`              | -            | 5s        | 三段：Validate → Preview Impact（45 ref / 31 stale）→ Confirm + 5s 倒计时 |
| 切换激活 Prompt 版本      | ai-prompts                  | `confirm-dialog`           | -            | -         | 影响治理 / 标签生成路径                                                   |
| 复制新 Prompt 版本        | ai-prompts                  | -                          | -            | -         | 非破坏，无需确认                                                          |
| 撤销自动提交标签          | tag-review 历史             | `undo-toast`               | -            | 10s       | 撤销立即生效，10s 内可二次撤销                                            |
| 标签批量驳回              | tag-review bulk-bar         | `confirm-dialog`           | -            | -         | 显示选中条数                                                              |
| 删除 Provider             | data-sources drawer         | `two-step-input`           | provider 名  | -         | 影响 batch 历史 + 资产关联，必须输入 provider 名                          |
| 撤销 API 调用方           | permissions API callers tab | `confirm-dialog`           | -            | -         | 立即生效；说明影响调用方                                                  |
| 导出审计                  | permissions                 | -                          | -            | -         | 非破坏，但需在 toast 注明"不含 query 明文与答案正文"                      |
| 触发立即同步              | ingest provider-card        | `optimistic-with-rollback` | -            | -         | 触发 1 次 sync，UI 立即变 processing                                      |
| 手动创建批次              | ingest 顶部                 | -                          | -            | -         | 创建型操作，wizard 引导                                                   |
| 切换激活规则集版本        | rules                       | `time-locked`              | -            | 5s        | 同发布流程                                                                |
| 重新治理（re-governance） | 规则发布触发                | `time-locked`              | -            | -         | 在规则发布的 Preview Impact 阶段一并展示                                  |

---

## 具体实现要点

### 1. `confirm-dialog` 模板

```tsx
import { App as AntdApp } from "antd";

const { modal } = AntdApp.useApp();

modal.confirm({
  title: "确认批量重试 12 个作业？",
  content: (
    <div style={{ display: "grid", gap: 8 }}>
      <div>仅对 retryable_failed 状态的作业创建新调度，已成功的作业不受影响。</div>
      <div style={{ color: "var(--text-secondary)" }}>
        预计耗时：5-10 分钟。每条作业生成独立 trace_id 与审计事件。
      </div>
    </div>
  ),
  okText: "确认重试",
  cancelText: "取消",
  okButtonProps: { danger: true },
  onOk: async () => {
    /* ... */
  },
});
```

### 2. `undo-toast` 模板

```tsx
import { App as AntdApp, Button } from "antd";

const { notification } = AntdApp.useApp();
const key = `adopt-${Date.now()}`;

notification.success({
  key,
  message: "已采纳 3 条高置信建议",
  description: "10 秒内可撤销。撤销后审计事件保留。",
  duration: 10,
  btn: (
    <Button type="link" onClick={() => undoAdoption(ids)}>
      撤销
    </Button>
  ),
});
```

### 3. `time-locked` 模板（规则发布）

阶段 P2.10 落地，详见 `app/rules/page.tsx` 重构方案：

- Step 1 `Validate`：受限表达式校验、命中样本回放，全部通过才解锁下一步。
- Step 2 `Preview Impact`：显示受影响的 normalized refs / stale index 数量，可展开列表。
- Step 3 `Confirm`：
  - 主按钮显示倒计时（5s），期间可中止；
  - 倒计时结束后真正调用发布 API；
  - 写入 RuleSetActivated 审计事件。

### 4. `two-step-input` 模板（删 Provider）

```tsx
modal.confirm({
  title: "确认删除 Provider 教研教材上传？",
  content: <DeleteProviderForm name="教研教材上传" />, // 内部 input + 校验
  okText: "永久删除",
  okButtonProps: { danger: true, disabled: true /* 由 form 控制 */ },
});
```

---

## 验收要求

PR 中触及任一危险动作时：

- [ ] 在 PR 描述列出动作清单与匹配的模式
- [ ] 含 toast / dialog 截图
- [ ] 后端写操作携带 Idempotency-Key（与 R3 联动）
- [ ] 失败路径：UI 自动回退 + 错误 toast 含 trace_id
- [ ] 审计事件类型在 PR 描述列出（如 RuleSetActivated / TagAdoptionReverted）
