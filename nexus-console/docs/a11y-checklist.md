# A2 可访问性自查清单（a11y Checklist）

> 阶段 -1 A2 产出。`plan.md` 阶段 2 每个 PR 验收门槛 #9 引用本文件。
> 基线：WCAG 2.1 AA + 键盘可达 + 色盲友好 + 屏幕阅读器可解析。

---

## 全局基线（一次性落地）

### 1. Focus ring

`globals.css` 增加：

```css
:root {
  --focus-ring: 0 0 0 3px rgba(37, 99, 235, 0.4);
  --focus-ring-danger: 0 0 0 3px rgba(220, 38, 38, 0.4);
}

*:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: 4px;
  transition: box-shadow 120ms ease;
}

button:focus-visible,
a:focus-visible,
input:focus-visible,
[role="button"]:focus-visible {
  box-shadow: var(--focus-ring);
}
```

注意：Antd 自带的 hover/focus 样式不破坏，仅在自研组件与原生元素上叠加。

### 2. 颜色信号双通道

凡颜色传达语义，**必须**配 icon 或文本：

| 信号      | 颜色           | icon / 文字补充                                  |
| --------- | -------------- | ------------------------------------------------ |
| 状态-成功 | 绿圆点         | ✓ + "available"                                  |
| 状态-警告 | 橙圆点         | ⚑ + "review_required"                            |
| 状态-危险 | 红圆点         | ⚠ + "failed"                                     |
| 状态-信息 | 蓝圆点         | ◉ + "processing"                                 |
| heatmap   | 三色           | ✓ / ⚑ / —（参见 docs/ux-destructive-actions.md） |
| L1-L4     | 绿/蓝/橙/红    | "L1 公开" / "L2 内部" / "L3 受限" / "L4 例外"    |
| D1-D6     | 6 色           | "D1" / "D2" / ... 字母 + 域名 hover              |
| quality   | conic-gradient | 圆环中心数字 + 下方"pass / partial / poor"       |
| 优先级    | 左色条         | 行内 `<Tag>` 显式标注 "超时" / "今日" / "正常"   |

### 3. ARIA 属性

| 元素                                  | 要求                                                        |
| ------------------------------------- | ----------------------------------------------------------- |
| 纯图标按钮（`<Button icon={...} />`） | 必填 `aria-label`；Antd `Button` 接受该属性                 |
| 圆点状态徽标 `<StatusDot>`            | `role="status" aria-label="状态：xxx"`                      |
| 卡片可点击区域                        | `role="button" tabIndex={0}` + Enter/Space 触发             |
| Drawer 关闭                           | 焦点回到触发元素（Antd `Drawer` 默认行为，不要覆盖）        |
| Modal                                 | `aria-labelledby` 指向标题；`aria-describedby` 指向 content |
| Tab 切换                              | 用 Antd `Tabs`（已正确实现 a11y）                           |
| Skeleton                              | `role="status" aria-live="polite" aria-label="加载中"`      |
| Empty / Forbidden                     | `role="status"` 或 `role="alert"`                           |
| 表单字段                              | 必须有 `<Form.Item label="...">`，禁止仅靠 placeholder      |
| 动态消息（toast）                     | Antd `App.useApp().message` 默认 polite，无需手动           |

### 4. 键盘可达

每页验收：

- [ ] Tab 键能访问到所有可交互元素
- [ ] 顺序与视觉一致（无诡异跳跃）
- [ ] Enter / Space 触发主操作
- [ ] Esc 关闭 Modal / Drawer / Popover
- [ ] 自定义复合控件（如 BulkBar）支持上下箭头切换
- [ ] focus-visible 样式始终可见（可在 stylesheets 强制 outline）

### 5. 对比度

WCAG AA 要求：

| 文本               | 最小对比度 |
| ------------------ | ---------- |
| 普通文本（< 18pt） | 4.5 : 1    |
| 大文本（≥ 18pt）   | 3 : 1      |
| UI 组件描边        | 3 : 1      |

工具：Chrome DevTools `Accessibility > Color Contrast`、`@axe-core/playwright`。

**已知风险点**：

- sidebar `nav-section-title` 透明度 `0.40` → 提到 `0.60`（plan.md UI 优化 #23）
- `text-muted` `#9ca3af` 在 `#ffffff` 上对比 2.83:1 — 仅用于次要标签，不用于正文

---

## 每页 PR 自查清单

复制到 PR 描述：

```
### a11y 自查
- [ ] 所有交互元素 Tab 键可达，顺序合理
- [ ] focus-visible 样式可见
- [ ] Esc 关闭 Modal / Drawer / Popover
- [ ] 颜色信号已配 icon/text 双通道（参考 docs/a11y-checklist.md §2）
- [ ] 圆点徽标 / 纯图标按钮补 aria-label
- [ ] 表单字段有 label
- [ ] 文字对比度 ≥ AA（DevTools 自查或 axe）
- [ ] 加载 / 空 / 错误 状态有 role="status" 或 role="alert"
```

---

## 自动化（阶段 1 引入）

```
npm i -D @axe-core/playwright
```

E2E 关键页跑：

```ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("workbench has no a11y violations", async ({ page }) => {
  await page.goto("/workbench");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
```

阶段 3 把 axe 跑入 CI，AA 违规阻断合并。
