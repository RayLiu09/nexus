"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Descriptions, Empty, Skeleton, Tag, Typography } from "antd";
import { BookOpen, BriefcaseBusiness, GraduationCap, ListChecks, ScrollText } from "lucide-react";
import { getApiData, type MajorProfile, type MajorProfileCourse, type MajorProfileItem } from "@/lib/api";

type Props = { normalizedRefId: string };

const COURSE_GROUP_LABEL: Record<string, string> = {
  foundation: "专业基础课程",
  core: "专业核心课程",
  practice_training: "实习实训",
};

export function MajorProfileKnowledgeView({ normalizedRefId }: Props) {
  const [state, setState] = useState<{
    loading: boolean;
    profile: MajorProfile | null;
    error: string | null;
  }>({ loading: true, profile: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, profile: null, error: null });
    getApiData<MajorProfile | null>(
      `/api/normalized-refs/${normalizedRefId}/major-profile`,
      null,
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setState({ loading: false, profile: null, error: res.error });
        return;
      }
      setState({ loading: false, profile: res.data, error: null });
    });
    return () => {
      active = false;
    };
  }, [normalizedRefId]);

  if (state.loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (state.error) {
    return <Alert type="error" showIcon title="加载专业简介失败" description={state.error} />;
  }
  if (!state.profile) {
    return <Empty description="该 ref 没有关联的专业简介结构化数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return <MajorProfileContent profile={state.profile} />;
}

function MajorProfileContent({ profile }: { profile: MajorProfile }) {
  const coursesByGroup = useMemo(() => {
    const groups: Record<string, MajorProfileCourse[]> = {
      foundation: [],
      core: [],
      practice_training: [],
    };
    for (const course of profile.courses ?? []) {
      const key = course.course_group || "foundation";
      if (!groups[key]) groups[key] = [];
      groups[key].push(course);
    }
    for (const key of Object.keys(groups)) {
      groups[key].sort((a, b) => a.item_index - b.item_index);
    }
    return groups;
  }, [profile.courses]);

  return (
    <div className="flex flex-col gap-4">
      <div className="card">
        <div className="card-header">
          <div>
            <Typography.Title level={5} className="!mb-0">
              {profile.major_name}
            </Typography.Title>
            <div className="text-muted mt-1 text-sm">
              {profile.major_code} · {profile.education_level ?? "层次未标注"} · {profile.basic_study_duration ?? "修业年限未标注"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Tag color="blue">major_profile.v1</Tag>
            {profile.confidence !== null && (
              <Tag color="green">置信度 {(profile.confidence * 100).toFixed(0)}%</Tag>
            )}
          </div>
        </div>
        <div className="card-body">
          <Descriptions
            size="small"
            colon={false}
            column={{ xs: 1, sm: 1, md: 2 }}
            items={[
              { key: "code", label: "专业代码", children: profile.major_code },
              { key: "name", label: "专业名称", children: profile.major_name },
              { key: "level", label: "层次", children: profile.education_level ?? "—" },
              { key: "duration", label: "基本修业年限", children: profile.basic_study_duration ?? "—" },
              { key: "extractor", label: "抽取器", children: profile.extractor_version },
              { key: "status", label: "结构化状态", children: profile.status },
            ]}
          />
        </div>
      </div>

      <Section title="培养目标定位" icon={<GraduationCap size={16} />}>
        <p className="m-0 whitespace-pre-wrap text-sm leading-6">{profile.training_goal ?? "—"}</p>
      </Section>

      <Section title="职业面向" icon={<BriefcaseBusiness size={16} />}>
        <ItemList items={profile.occupations ?? []} />
      </Section>

      <Section title="主要专业能力要求" icon={<ListChecks size={16} />}>
        <ItemList items={profile.abilities ?? []} ordered />
      </Section>

      <Section title="主要专业课程与实习实训" icon={<BookOpen size={16} />}>
        <div className="grid gap-3 md:grid-cols-3">
          {Object.entries(coursesByGroup).map(([group, items]) => (
            <div key={group} className="rounded-md border border-[var(--line)] p-3">
              <div className="mb-2 text-sm font-semibold">{COURSE_GROUP_LABEL[group] ?? group}</div>
              <ItemList items={items} compact />
            </div>
          ))}
        </div>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="职业类证书举例" icon={<ScrollText size={16} />}>
          <ItemList items={profile.certificates ?? []} compact />
        </Section>
        <Section title="接续专业举例" icon={<GraduationCap size={16} />}>
          <ItemList items={profile.continuations ?? []} compact />
        </Section>
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title inline-flex items-center gap-2">
          {icon}
          {title}
        </span>
      </div>
      <div className="card-body">{children}</div>
    </div>
  );
}

function ItemList({
  items,
  ordered = false,
  compact = false,
}: {
  items: MajorProfileItem[];
  ordered?: boolean;
  compact?: boolean;
}) {
  if (items.length === 0) {
    return <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const sorted = [...items].sort((a, b) => a.item_index - b.item_index);
  const ListTag = ordered ? "ol" : "ul";
  return (
    <ListTag className={`${ordered ? "list-decimal" : "list-disc"} m-0 pl-5 text-sm leading-6`}>
      {sorted.map((item) => (
        <li key={item.id} className={compact ? "mb-1" : "mb-2"}>
          <span>{item.text}</span>
        </li>
      ))}
    </ListTag>
  );
}
