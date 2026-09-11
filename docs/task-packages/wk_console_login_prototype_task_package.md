# NEXUS Console 生产级登录原型任务包

## 任务名称

NX-00 Console 生产级登录原型

## 来源上下文

- `SPEC.md`：P0 使用本地身份认证，不依赖企业 IAM。
- `ARCHITECT.md`：Console 与 Open API 调用身份保持独立边界。
- `docs/企业数据与知识资产平台Prototype设计文档_v2.2.md`：NX-00 登录与入口。
- `WORKFLOWS.md`：P0 页面变更需通过 Frontend UX Gate；身份边界需通过 Permission And Audit Gate。

## 目标

提供可直接演示并连接真实认证接口的 NEXUS Console 登录页，清晰呈现系统品牌、平台名称、SVG 场景背景、登录表单，以及数据管理员和业务专家两类 Console 登录角色。

## 范围

- `nexus-console/app/login/` 登录页面、样式和组件测试。
- `nexus-console/components/AppShell.tsx` 及测试中的登录路由壳层隔离。
- `nexus-console/public/images/` 登录背景 SVG。
- Prototype v2.2 的 NX-00 页面说明。
- 本任务包中的验证和 Review Gate 证据。

## 范围外

- 不新增注册、找回密码、记住登录或企业 IAM 流程。
- 不新增角色选择或客户端权限切换。
- 不修改认证 API、令牌、Cookie、账号或角色数据模型。
- 不向 `api_caller` 或运维角色开放 Console。

## 禁止变更

- 不引入企业 IAM 或第三方登录依赖。
- 不将 Open API 调用身份合并到 Console 登录角色。
- 不削弱服务端角色校验、重定向校验和 httpOnly Cookie 约束。
- 不引入 NEXUS AI Gateway 管理页面或任何 P1/P2 功能。

## 交付物

- 生产级响应式登录原型与 SVG 背景资产。
- 登录路由脱离主应用侧边栏和顶部栏。
- 登录页和 AppShell 的聚焦组件测试。
- 更新后的 NX-00 Prototype 说明。
- 静态检查、构建、桌面端和移动端演示证据。

## 验收标准

- `/login` 首屏左上方显示 NEXUS Logo 与系统全称，登录框在右侧相对视口垂直居中，并显示账号密码控件和两类支持角色。
- 角色仅作身份范围说明，真实角色继续由服务端认证结果决定。
- 登录页不显示 Console 侧边栏、顶部栏或快速上传入口。
- 会话检查、必填校验、提交中、认证失败和网络失败状态清晰。
- 桌面 `1440x1000` 与移动 `390x844` 无横向溢出、遮挡或不可用控件。
- `npm run typecheck`、聚焦 Vitest、变更文件 ESLint、`npm run build` 和 `git diff --check` 通过。

## Review Gate

### Frontend UX Gate

- [ ] 与 NX-00 页面目的和最新角色范围一致。
- [ ] 登录表单、错误态、加载态和响应式布局可演示。
- [ ] SVG 背景不影响信息层级、对比度和可操作性。

### Permission And Audit Gate

- [ ] 页面不提供角色切换能力。
- [ ] 仅 `platform_data_admin` 与 `business_expert` 可建立 Console 会话。
- [ ] `api_caller` 和其他非 Console 角色仍由服务端拒绝。
- [ ] 本次无认证 API 和审计契约变更。

## 验证证据

完成实现后补充命令结果与截图检查结论。
