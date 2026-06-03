import type { Session, SessionRole } from "./session";

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
    username: "platform_admin",
    displayName: "张敏",
    role: "platform_admin",
    orgUnit: { id: "org-root", name: "产教融合中心" },
    description: "平台管理员 — 全部权限，可发布规则、管理 Prompt、查看全部审计",
  },
  {
    id: "user-steward-002",
    username: "data_steward",
    displayName: "李华",
    role: "data_steward",
    orgUnit: { id: "org-research", name: "教研中心" },
    description: "数据管家 — 数据源接入、批次治理、资产元数据补齐",
  },
  {
    id: "user-reviewer-003",
    username: "reviewer",
    displayName: "王涛",
    role: "reviewer",
    orgUnit: { id: "org-quality", name: "质量审核组" },
    description: "审核员 — AI 治理建议复核、敏感内容裁定",
  },
  {
    id: "user-reader-004",
    username: "reader",
    displayName: "陈雪",
    role: "reader",
    orgUnit: { id: "org-research", name: "教研中心" },
    description: "只读用户 — 仅检索与查看，无写权限",
  },
];

export const ROLE_LABELS: Record<SessionRole, string> = {
  platform_admin: "平台管理员",
  data_steward: "数据管家",
  reviewer: "审核员",
  reader: "只读用户",
};

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
