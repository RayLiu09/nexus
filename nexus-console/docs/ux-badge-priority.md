# A6 徽标语义优先级矩阵（Badge Priority）

> 阶段 -1 A6 产出。`plan.md` 阶段 2 每个 PR 验收门槛 #11 引用本文件。
> 目标：解决 review-card 一行 5+ 徽标导致的视觉过载，让用户 ≤ 3 秒识别"这是什么、紧不紧急"。

---

## 核心规则

### 1. 一行徽标硬上限：3 个

超出 3 个时，按下方优先级保留前 3，其余折叠为 "+N" 并用 `Tooltip` / `Popover` 展开。

### 2. 优先级（高 → 低）

| 等级 | 类别         | 含义                                                               | 视觉                       | 例                              |
| ---- | ------------ | ------------------------------------------------------------------ | -------------------------- | ------------------------------- |
| 1    | **状态**     | 表示当前生命周期状态（version_status / job_status / index_status） | 圆点 + 文字（`StatusDot`） | available / processing / failed |
| 2    | **优先级**   | 表示需要"现在 vs 稍后"的时间紧迫度                                 | 左色条 + 角标              | overdue / today / normal        |
| 3    | **分级 L**   | 数据敏感分级，影响访问与脱敏                                       | `LevelChip` 含分级图标     | L1 / L2 / L3 / L4               |
| 4    | **域 D**     | 数据域归属                                                         | `DomainChip` 含域字母      | D1 / D2 / D4 / D6               |
| 5    | **置信度**   | AI 输出的置信度（仅 AI 相关场景显示）                              | 进度条 + 百分数            | 94% / 62%                       |
| 6    | **SLA**      | 倒计时 / 等待时长                                                  | 计时图标 + 时间            | 超时 26h / 剩余 5h              |
| 7    | **类型**     | source_type / content_type / pipeline_type                         | 中性 chip                  | document / record / file_upload |
| 8    | **审计角标** | trace_id / 是否已审计                                              | mono 短码                  | trace_4ae20                     |

### 3. 选取算法

伪代码：

```ts
function pickBadges(allBadges: Badge[]): Badge[] {
  return allBadges.sort((a, b) => priority[a.kind] - priority[b.kind]).slice(0, 3);
}
```

剩余的徽标在行尾显示 `<Popover content={overflowList}>+N 更多</Popover>`。

---

## 场景示例

### Case 1：governance review-card

**v3.2 原型**：D + L + 状态 + 置信度 + SLA + 优先级 = **6 个徽标**。

**应用矩阵后保留**：

```
[priority overdue 左色条]   政策法规汇编 2025
                            ref_doc_20260513_009
                            [● 高敏风险]  [L4]  [超时 26h]   +2 更多
```

折叠的 2 个：D6 域 / 置信度 45%。Hover Popover 展开看全。

### Case 2：assets 表行

**原型**：D + L + 状态 + 索引状态 + 组织范围 = **5 个徽标 + 左侧色条**。

**应用矩阵后**：

- 左侧色条仍由域决定（视觉锚点，不计入徽标 budget）
- 行内徽标按优先级保留 **状态 + L + 索引状态** 共 3 个
- D 域已通过左色条表达，不再重复
- 组织范围放到 hover 详情或单独列

### Case 3：jobs 列表

job pipeline 横管线条本身已表达进度，不再加阶段徽标。一行只保留：

- 状态（running / failed / completed）
- 优先级（仅 failed 时加 retryable / not-retryable）
- 类型（document / record）

---

## 视觉细节

| 要素      | 规则                                                                           |
| --------- | ------------------------------------------------------------------------------ |
| 间距      | 同行徽标之间 `gap: 6px`；与文本之间 `gap: 8px`                                 |
| 高度      | 统一 22px，避免高低不齐                                                        |
| 圆点直径  | 7px；与 chip 文字基线对齐                                                      |
| icon size | 12px（chip 内）/ 14px（独立时）                                                |
| `+N 更多` | 中性灰底；hover 时蓝边 brand-300；Popover 内每条徽标自带原色                   |
| 强制 aria | 每个圆点状态徽标必须 `aria-label="状态：available"` 等；颜色信号配 icon + 文字 |
| 拥挤检测  | `<BadgeRow>` 组件传入 budget=3，超出自动折叠；不在调用处手动判断               |

---

## 计划落地点

- 阶段 1 实现 `components/shared/BadgeRow.tsx`，签名：

```ts
type BadgeKind =
  | "status"
  | "priority"
  | "level"
  | "domain"
  | "confidence"
  | "sla"
  | "type"
  | "audit";

interface Badge {
  kind: BadgeKind;
  node: ReactNode;
  /** 折叠时显示在 Popover 列表中的文案 */
  label: string;
}

export function BadgeRow({ badges, budget = 3 }: { badges: Badge[]; budget?: number }): JSX.Element;
```

- 阶段 2 各页面表格 / 卡片 / 详情 渲染徽标统一通过 `BadgeRow`，禁止裸排 `<Tag>` × N。

---

## 反模式

- ❌ 在表格列里硬塞 `<Space>` 列出 5 个 tag
- ❌ 在 review-card 里每个状态都用同一种 Tag color，让用户靠文字反复扫描
- ❌ 把"trace_id"和"状态"放在同一视觉层级（trace_id 是审计辅助，应弱化）
- ❌ 优先级（overdue）用文字徽标 + 左色条 **重复**两次表达；左色条只是放大锚点，徽标仍要在
