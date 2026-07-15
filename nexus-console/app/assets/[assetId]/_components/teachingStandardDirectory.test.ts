import { describe, expect, it } from "vitest";
import { resolveTeachingStandardDirectory } from "./teachingStandardDirectory";
import type { NormalizedBlock } from "@/lib/chunkTypes";

describe("resolveTeachingStandardDirectory", () => {
  it("prefers normalized toc and preserves nested children", () => {
    const result = resolveTeachingStandardDirectory(
      [
        {
          level: 1,
          number: "1",
          title: "概述",
          block_id: "toc-1",
          children: [{ level: 2, title: "适用范围", block_id: "toc-1-1" }],
        },
      ],
      [block("b1", "一、专业名称（专业代码）", 1)],
    );

    expect(result).toEqual([
      {
        key: "toc-1",
        title: "1 概述",
        children: [{ key: "toc-1-1", title: "适用范围" }],
      },
    ]);
  });

  it("derives a directory from heading blocks when toc is empty", () => {
    const blocks = [
      block("b1", "一、专业名称（专业代码）", 1),
      block("b2", "（一）职业面向", 2),
      block("b3", "1.1 专业课程主要教学内容与要求", undefined),
      block("b4", "正文段落", undefined, "paragraph"),
    ];

    expect(resolveTeachingStandardDirectory([], blocks)).toEqual([
      {
        key: "b1",
        title: "一、专业名称（专业代码）",
        children: [
          { key: "b2", title: "（一）职业面向" },
          { key: "b3", title: "1.1 专业课程主要教学内容与要求" },
        ],
      },
    ]);
  });

  it("returns an empty tree when neither toc nor usable headings exist", () => {
    expect(
      resolveTeachingStandardDirectory(null, [block("b1", "正文", undefined, "paragraph")]),
    ).toEqual([]);
  });
});

function block(
  blockId: string,
  text: string,
  headingLevel?: number,
  blockType = "heading",
): NormalizedBlock {
  return {
    block_id: blockId,
    block_type: blockType,
    text,
    heading_level: headingLevel,
    md_char_range: null,
  };
}
