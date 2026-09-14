import type { Session, SessionRole } from "./session";
import { CONSOLE_ROLE_LABELS } from "./roles";

/**
 * dev 模式预置账号 —— 只用于 /login 选角色，不参与后端 IAM。
 *
 * 这些 id/orgUnit 与 `nexus_app/config/initial_data.py` 中 seed 用户对齐，
 * 便于后端 audit log 关联（即使当前后端不校验）。
 */
interface MockUser {
  id: string;
  username: string;
  displayName: string;
  role: SessionRole;
  orgUnit: Session["orgUnit"];
  description: string;
}

export const MOCK_USERS: ReadonlyArray<MockUser> = [
  {
    id: "user-admin-001",
    username: "admin@nexus.local",
    displayName: "张敏",
    role: "platform_data_admin",
    orgUnit: { id: "org-root", name: "产教融合中心" },
    description:
      "平台数据管理员 — 负责数据源接入、原始台账、作业中心、访问与审计以及用户管理等平台侧功能。",
  },
  {
    id: "user-steward-002",
    username: "expert@nexus.local",
    displayName: "李华",
    role: "business_expert",
    orgUnit: { id: "org-research", name: "教研中心" },
    description: "业务专家 — 负责资产中心浏览、智能检索问答以及治理审核与规则/Prompt 的业务复核。",
  },
];

export const ROLE_LABELS: Record<SessionRole, string> = CONSOLE_ROLE_LABELS;

export function findMockUserById(id: string): MockUser | null {
  return MOCK_USERS.find((u) => u.id === id) ?? null;
}

export function buildSessionFromMock(user: MockUser, env: Session["env"] = "demo"): Session {
  return {
    id: user.id,
    username: user.username,
    displayName: user.displayName,
    role: user.role,
    orgUnit: user.orgUnit,
    env,
    loggedInAt: Date.now(),
  };
}
