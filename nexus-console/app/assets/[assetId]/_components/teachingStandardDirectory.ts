import type { NormalizedBlock, NormalizedTocItem } from "@/lib/chunkTypes";

export type TeachingStandardTocItem = NormalizedTocItem;

export type TeachingStandardDirectoryNode = {
  key: string;
  title: string;
  children?: TeachingStandardDirectoryNode[];
};

type FlatDirectoryItem = {
  key: string;
  title: string;
  level: number;
};

const NUMBERED_HEADING = /^(\d+(?:\.\d+)*)(?:[.、．])?\s+(.+)$/;
const CHINESE_TOP_LEVEL_HEADING = /^([一二三四五六七八九十]+)[、．.]\s*(.+)$/;
const PARENTHETICAL_HEADING = /^[（(]([0-9一二三四五六七八九十]+)[）)]\s*(.+)$/;

export function resolveTeachingStandardDirectory(
  toc: TeachingStandardTocItem[] | null | undefined,
  blocks: NormalizedBlock[] | null | undefined,
): TeachingStandardDirectoryNode[] {
  const fromToc = flattenToc(toc ?? []);
  return toTree(fromToc.length > 0 ? fromToc : deriveFromHeadingBlocks(blocks ?? []));
}

function flattenToc(
  items: TeachingStandardTocItem[],
  parentLevel = 0,
  prefix = "toc",
): FlatDirectoryItem[] {
  return items.flatMap((item, index) => {
    const title = (item.title ?? item.text ?? "").trim();
    if (!title) return [];
    const level = positiveLevel(item.level) ?? parentLevel + 1;
    const number =
      typeof item.number === "string" && item.number.trim() ? item.number.trim() : null;
    const key = item.block_id ?? `${prefix}-${index}`;
    return [
      { key, level, title: number ? `${number} ${title}` : title },
      ...flattenToc(item.children ?? [], level, key),
    ];
  });
}

function deriveFromHeadingBlocks(blocks: NormalizedBlock[]): FlatDirectoryItem[] {
  const result: FlatDirectoryItem[] = [];
  let latestNumberedLevel = 0;

  for (const block of blocks) {
    if (block.block_type !== "heading") continue;
    const text = String(block.text ?? block.content ?? "").trim();
    if (!text) continue;

    const explicitLevel = positiveLevel(block.heading_level);
    const numbered = text.match(NUMBERED_HEADING);
    if (numbered) {
      const number = numbered[1];
      const level = explicitLevel ?? number.split(".").length;
      latestNumberedLevel = level;
      result.push({
        key: block.block_id,
        level,
        title: `${number} ${numbered[2].trim()}`,
      });
      continue;
    }

    const chineseTopLevel = text.match(CHINESE_TOP_LEVEL_HEADING);
    if (chineseTopLevel) {
      const level = explicitLevel ?? 1;
      latestNumberedLevel = level;
      result.push({
        key: block.block_id,
        level,
        title: `${chineseTopLevel[1]}、${chineseTopLevel[2].trim()}`,
      });
      continue;
    }

    const parenthetical = text.match(PARENTHETICAL_HEADING);
    if (parenthetical && (explicitLevel || latestNumberedLevel > 0)) {
      const level = explicitLevel ?? latestNumberedLevel + 1;
      result.push({
        key: block.block_id,
        level,
        title: `（${parenthetical[1]}）${parenthetical[2].trim()}`,
      });
      continue;
    }

    if (explicitLevel) {
      latestNumberedLevel = explicitLevel;
      result.push({
        key: block.block_id,
        level: explicitLevel,
        title: text,
      });
    }
  }
  return result;
}

function positiveLevel(value: number | undefined): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function toTree(items: FlatDirectoryItem[]): TeachingStandardDirectoryNode[] {
  const roots: TeachingStandardDirectoryNode[] = [];
  const stack: Array<{ level: number; children: TeachingStandardDirectoryNode[] }> = [
    { level: 0, children: roots },
  ];

  for (const item of items) {
    while (stack.length > 1 && stack[stack.length - 1].level >= item.level) {
      stack.pop();
    }
    const node: TeachingStandardDirectoryNode = { key: item.key, title: item.title };
    stack[stack.length - 1].children.push(node);
    node.children = [];
    stack.push({ level: item.level, children: node.children });
  }

  const removeEmptyChildren = (nodes: TeachingStandardDirectoryNode[]) => {
    for (const node of nodes) {
      if (node.children?.length) removeEmptyChildren(node.children);
      else delete node.children;
    }
  };
  removeEmptyChildren(roots);
  return roots;
}
