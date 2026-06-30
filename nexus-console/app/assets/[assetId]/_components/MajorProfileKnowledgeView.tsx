"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Descriptions, Empty, Segmented, Select, Skeleton, Tag, Typography } from "antd";
import { BookOpen, BriefcaseBusiness, GraduationCap, ListChecks, Network, ScrollText } from "lucide-react";
import type { ECharts, EChartsOption } from "echarts";
import { ChunkListSection } from "./ChunkListSection";
import {
  downloadEchartsGraphImage,
  GraphViewportActions,
  type GraphImageHandle,
} from "./GraphViewportActions";
import { getApiData, type MajorProfile, type MajorProfileCourse, type MajorProfileItem } from "@/lib/api";

type Props = { normalizedRefId: string };
type ViewKey = "chunks" | "directory" | "graph";

const COURSE_GROUP_LABEL: Record<string, string> = {
  foundation: "专业基础课程",
  core: "专业核心课程",
  practice_training: "实习实训",
};

const VIEW_OPTIONS: Array<{ label: string; value: ViewKey }> = [
  { label: "知识块", value: "chunks" },
  { label: "目录", value: "directory" },
  { label: "专业图谱", value: "graph" },
];

export function MajorProfileKnowledgeView({ normalizedRefId }: Props) {
  const [view, setView] = useState<ViewKey>("chunks");
  const [state, setState] = useState<{
    loading: boolean;
    profiles: MajorProfile[];
    error: string | null;
  }>({ loading: true, profiles: [], error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, profiles: [], error: null });
    getApiData<MajorProfile[]>(
      `/api/normalized-refs/${normalizedRefId}/major-profiles`,
      [],
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setState({ loading: false, profiles: [], error: res.error });
        return;
      }
      setState({ loading: false, profiles: res.data, error: null });
    });
    return () => {
      active = false;
    };
  }, [normalizedRefId]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <Segmented
          value={view}
          onChange={(value) => setView(value as ViewKey)}
          options={VIEW_OPTIONS}
          aria-label="切换专业简介知识视图"
        />
      </div>

      {view === "chunks" ? (
        <ChunkListSection
          refId={normalizedRefId}
          title="chunks 知识块"
          emptyDescription="该 ref 暂未生成 major_profile_knowledge 语义块。"
          mode="preview"
          actionLabel="定位原文"
          knowledgeTypeCode="major_profile_knowledge"
        />
      ) : null}

      {view !== "chunks" && state.loading ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
      {view !== "chunks" && state.error ? (
        <Alert type="error" showIcon title="加载专业简介失败" description={state.error} />
      ) : null}
      {view !== "chunks" && !state.loading && !state.error && state.profiles.length === 0 ? (
        <Empty description="该 ref 没有关联的专业简介结构化数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {view === "directory" && !state.loading && !state.error && state.profiles.length > 0 ? (
        <MajorProfileDirectory profiles={state.profiles} />
      ) : null}
      {view === "graph" && !state.loading && !state.error && state.profiles.length > 0 ? (
        <MajorProfileGraph profiles={state.profiles} />
      ) : null}
    </div>
  );
}

function MajorProfileDirectory({ profiles }: { profiles: MajorProfile[] }) {
  const [selectedProfileId, setSelectedProfileId] = useState<string>(profiles[0]?.id ?? "");
  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedProfileId) ?? profiles[0],
    [profiles, selectedProfileId],
  );

  useEffect(() => {
    if (!profiles.some((profile) => profile.id === selectedProfileId)) {
      setSelectedProfileId(profiles[0]?.id ?? "");
    }
  }, [profiles, selectedProfileId]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-start gap-3">
        <Select
          className="min-w-[280px]"
          value={selectedProfile?.id}
          onChange={setSelectedProfileId}
          options={profiles.map((profile) => ({
            value: profile.id,
            label: `${profile.major_code} ${profile.major_name}`,
          }))}
          placeholder="选择专业"
        />
      </div>
      {selectedProfile ? <MajorProfileContent profile={selectedProfile} /> : null}
    </div>
  );
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
            {profile.confidence !== null ? (
              <Tag color="green">置信度 {(profile.confidence * 100).toFixed(0)}%</Tag>
            ) : null}
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
              {group === "practice_training" ? (
                <PracticeTrainingText items={items} />
              ) : (
                <ItemList items={items} compact />
              )}
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

function PracticeTrainingText({ items }: { items: MajorProfileCourse[] }) {
  if (items.length === 0) {
    return <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const text = items
    .sort((a, b) => a.item_index - b.item_index)
    .map((item) => item.text)
    .join("\n");
  return <p className="m-0 whitespace-pre-wrap text-sm leading-6">{text}</p>;
}

type GraphNode = {
  id: string;
  name: string;
  fullText: string;
  category: number;
  symbolSize: number;
};

type GraphEdge = {
  source: string;
  target: string;
  name: string;
};

function MajorProfileGraph({ profiles }: { profiles: MajorProfile[] }) {
  const graph = useMemo(() => buildMajorProfileGraph(profiles), [profiles]);
  const graphRef = useRef<GraphImageHandle | null>(null);
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title inline-flex items-center gap-2">
          <Network size={16} />
          专业图谱
        </span>
        <div className="flex items-center gap-2">
          <Tag className="!mr-0">{graph.nodes.length} 节点 / {graph.edges.length} 边</Tag>
          <GraphViewportActions
            title="专业图谱"
            disabled={graph.nodes.length === 0}
            onDownload={() => graphRef.current?.downloadImage("专业图谱.png")}
          >
            <MajorProfileEcharts nodes={graph.nodes} edges={graph.edges} fullscreen />
          </GraphViewportActions>
        </div>
      </div>
      <div className="card-body">
        <MajorProfileEcharts ref={graphRef} nodes={graph.nodes} edges={graph.edges} />
      </div>
    </div>
  );
}

function buildMajorProfileGraph(profiles: MajorProfile[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const seenNodes = new Set<string>();
  const knownNodeIds = new Set<string>();
  const addNode = (node: GraphNode) => {
    if (!node.id || seenNodes.has(node.id)) return;
    seenNodes.add(node.id);
    knownNodeIds.add(node.id);
    nodes.push(node);
  };
  const addEdge = (edge: GraphEdge) => {
    if (!edge.source || !edge.target) return;
    edges.push(edge);
  };
  const addItems = (
    profile: MajorProfile,
    items: MajorProfileItem[],
    groupId: string,
    groupName: string,
    edgeName: string,
  ) => {
    if (items.length === 0) return;
    addNode({ id: groupId, name: groupName, fullText: groupName, category: 1, symbolSize: 44 });
    addEdge({ source: profile.id, target: groupId, name: edgeName });
    for (const [idx, item] of items.slice(0, 30).entries()) {
      const itemId = item.id || `${groupId}:item:${idx}`;
      addNode({
        id: itemId,
        name: compactGraphLabel(item.text),
        fullText: item.text,
        category: 2,
        symbolSize: 24,
      });
      addEdge({ source: groupId, target: itemId, name: "包含" });
    }
  };
  const addCourseGroups = (profile: MajorProfile) => {
    const courses = profile.courses ?? [];
    if (courses.length === 0) return;
    const courseRootId = `${profile.id}:courses`;
    addNode({ id: courseRootId, name: "课程实训", fullText: "主要专业课程与实习实训", category: 1, symbolSize: 44 });
    addEdge({ source: profile.id, target: courseRootId, name: "课程" });
    for (const group of ["foundation", "core", "practice_training"]) {
      const groupItems = courses
        .filter((course) => (course.course_group || "foundation") === group)
        .sort((a, b) => a.item_index - b.item_index);
      if (groupItems.length === 0) continue;
      const groupId = `${courseRootId}:${group}`;
      const groupName = COURSE_GROUP_LABEL[group] ?? group;
      addNode({ id: groupId, name: groupName, fullText: groupName, category: 1, symbolSize: 36 });
      addEdge({ source: courseRootId, target: groupId, name: "包含" });
      if (group === "practice_training") {
        const text = groupItems.map((item) => item.text).join("\n");
        const itemId = `${groupId}:whole`;
        addNode({
          id: itemId,
          name: compactGraphLabel(text),
          fullText: text,
          category: 2,
          symbolSize: 24,
        });
        addEdge({ source: groupId, target: itemId, name: "包含" });
        continue;
      }
      for (const [idx, item] of groupItems.slice(0, 30).entries()) {
        const itemId = item.id || `${groupId}:item:${idx}`;
        addNode({
          id: itemId,
          name: compactGraphLabel(item.text),
          fullText: item.text,
          category: 2,
          symbolSize: 22,
        });
        addEdge({ source: groupId, target: itemId, name: "包含" });
      }
    }
  };

  for (const profile of profiles) {
    addNode({
      id: profile.id,
      name: `${profile.major_name}\n${profile.major_code}`,
      fullText: `${profile.major_code} ${profile.major_name}`,
      category: 0,
      symbolSize: 66,
    });
    addItems(profile, profile.occupations ?? [], `${profile.id}:occupations`, "职业面向", "面向");
    addItems(profile, profile.abilities ?? [], `${profile.id}:abilities`, "能力要求", "要求");
    addCourseGroups(profile);
    addItems(profile, profile.certificates ?? [], `${profile.id}:certificates`, "证书", "证书");
    addItems(profile, profile.continuations ?? [], `${profile.id}:continuations`, "接续专业", "接续");
  }
  return {
    nodes,
    edges: edges.filter((edge) => knownNodeIds.has(edge.source) && knownNodeIds.has(edge.target)),
  };
}

function compactGraphLabel(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= 28) return normalized;
  return `${normalized.slice(0, 14)}\n${normalized.slice(14, 28)}...`;
}

const MajorProfileEcharts = forwardRef<GraphImageHandle, {
  nodes: GraphNode[];
  edges: GraphEdge[];
  fullscreen?: boolean;
}>(function MajorProfileEcharts({ nodes, edges, fullscreen = false }, forwardedRef) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instance = useRef<ECharts | null>(null);
  const option = useMemo<EChartsOption>(() => ({
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const item = Array.isArray(params) ? params[0] : params;
        const data = item?.data as Partial<GraphNode> | undefined;
        return data?.fullText ?? data?.name ?? "";
      },
    },
    legend: [{ top: 0, data: ["专业", "章节", "条目"] }],
    series: [{
      type: "graph",
      layout: "force",
      roam: true,
      top: 36,
      label: { show: true, formatter: "{b}", width: 150 },
      edgeLabel: { show: false },
      force: { repulsion: 220, edgeLength: 110 },
      categories: [
        { name: "专业", itemStyle: { color: "#2563eb" } },
        { name: "章节", itemStyle: { color: "#0d9488" } },
        { name: "条目", itemStyle: { color: "#d97706" } },
      ],
      data: nodes,
      links: edges,
      lineStyle: { color: "source", curveness: 0.18, opacity: 0.72 },
      emphasis: { focus: "adjacency" },
    }],
  }), [edges, nodes]);

  useImperativeHandle(forwardedRef, () => ({
    downloadImage: (filename: string) => downloadEchartsGraphImage({
      option,
      filename,
      nodeCount: nodes.length,
    }),
  }), [nodes.length, option]);

  useEffect(() => {
    if (nodes.length === 0 || !containerRef.current) return;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    const container = containerRef.current;
    import("echarts").then((echarts) => {
      if (disposed) return;
      const chart = echarts.init(container);
      instance.current = chart;
      chart.setOption(option);
      requestAnimationFrame(() => {
        if (!disposed && !chart.isDisposed()) chart.resize();
      });
      resizeObserver = new ResizeObserver(() => {
        if (disposed || chart.isDisposed()) return;
        requestAnimationFrame(() => {
          if (disposed || chart.isDisposed()) return;
          chart.resize();
        });
      });
      resizeObserver.observe(container);
    });
    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      instance.current?.dispose();
      instance.current = null;
    };
  }, [nodes.length, option]);

  useEffect(() => {
    instance.current?.setOption(option, true);
  }, [option]);

  if (nodes.length === 0) {
    return <Empty description="暂无可绘制的专业图谱数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return <div ref={containerRef} className={`w-full ${fullscreen ? "h-full min-h-[520px]" : "h-[620px] min-h-[420px]"}`} />;
});
