#!/usr/bin/env python3
"""将 report.md 转换为自包含 HTML，渲染其中的 ECharts 图表与岗位图谱。

- ```chart 代码块 -> ECharts 图表（bar/pie/radar/wordCloud）
- ```json 代码块   -> 岗位图谱（treeLeftToRight / graph / radialTree / table 四视图）
- 其余 Markdown    -> 标准 HTML（含表格、脚注链接、参考文献）
"""
import json
import pathlib
import re

import markdown

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "report.md"
DST = HERE / "report.html"

TITLE = "跨境电子商务专业人才需求调研分析报告"


def extract_blocks(text: str):
    """抽取 fenced code block，用 div 占位符替换，返回 (正文, charts, graph)。"""
    lines = text.split("\n")
    out: list[str] = []
    charts: list[dict] = []
    graph: dict | None = None
    chart_idx = 0

    i = 0
    while i < len(lines):
        m = re.match(r"^```(chart|json)\s*$", lines[i].strip())
        if not m:
            out.append(lines[i])
            i += 1
            continue
        lang = m.group(1)
        buf: list[str] = []
        j = i + 1
        while j < len(lines) and lines[j].strip() != "```":
            buf.append(lines[j])
            j += 1
        code = "\n".join(buf)
        if lang == "chart":
            charts.append(json.loads(code))
            out.append(f'<div class="chart" id="chart-{chart_idx}"></div>')
            chart_idx += 1
        else:
            graph = json.loads(code)
            out.append('<div class="graph-wrap" id="graph-wrap"></div>')
        i = j + 1  # 跳过闭合 ```
    return "\n".join(out), charts, graph


def convert_markdown(text: str) -> str:
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
        extension_configs={
            "toc": {"toc_depth": "2-3", "title": "目录"},
        },
    )
    body = md.convert(text)
    toc = md.toc if hasattr(md, "toc") else ""
    return toc, body


CSS = """
:root {
  --ink: #2b2f36;
  --muted: #6b7280;
  --line: #e5e7eb;
  --accent: #1f5fbf;
  --bg: #f4f6f9;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  color: var(--ink);
  background: var(--bg);
  line-height: 1.75;
  font-size: 15px;
}
.report {
  max-width: 980px;
  margin: 0 auto;
  padding: 40px 48px 80px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}
h1 {
  font-size: 26px;
  text-align: center;
  padding-bottom: 18px;
  border-bottom: 2px solid var(--line);
  margin: 0 0 28px;
}
h2 {
  font-size: 21px;
  margin: 40px 0 16px;
  padding-left: 12px;
  border-left: 4px solid var(--accent);
}
h3 { font-size: 17px; margin: 28px 0 12px; }
h4 { font-size: 15px; margin: 18px 0 8px; }
p { margin: 10px 0; }
strong { color: #1a1d21; }
hr { border: none; border-top: 1px solid var(--line); margin: 32px 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* 目录 */
.toc {
  background: #f8fafc;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px 20px;
  margin: 0 0 32px;
  font-size: 14px;
}
.toc > .toc-title, .toc > p:first-child { font-weight: 700; margin: 0 0 8px; }
.toc ul { margin: 0; padding-left: 20px; }
.toc li { margin: 3px 0; }

/* 表格 */
table {
  border-collapse: collapse;
  width: 100%;
  margin: 14px 0;
  font-size: 13.5px;
  word-break: break-word;
}
th, td {
  border: 1px solid var(--line);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
th { background: #f1f5f9; font-weight: 600; }

/* 图表 */
.chart {
  width: 100%;
  height: 440px;
  margin: 16px 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}
.chart-error {
  color: #b91c1c;
  padding: 20px;
  font-size: 13px;
}

/* 来源注释 */
.source-note {
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
}

/* 图谱 */
.graph-wrap { margin: 16px 0; }
.graph-toolbar { margin-bottom: 8px; }
.graph-toolbar button {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  padding: 6px 14px;
  margin-right: 6px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.graph-toolbar button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
#graph-canvas {
  width: 100%;
  height: 760px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}
#graph-table {
  display: none;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 16px 20px;
  background: #fff;
  max-height: 760px;
  overflow: auto;
}
.legend { font-size: 12.5px; color: var(--muted); margin: 6px 0; }
.legend span { display: inline-block; margin-right: 14px; }
.legend i {
  display: inline-block; width: 10px; height: 10px;
  border-radius: 50%; margin-right: 4px; vertical-align: -1px;
}
"""

JS_TEMPLATE = r"""
<script>
(function () {
  var CHARTS = __CHARTS_JSON__;
  var GRAPH = __GRAPH_JSON__;

  var chartInstances = [];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderCharts() {
    if (!window.echarts) return;
    CHARTS.forEach(function (opt, i) {
      var el = document.getElementById('chart-' + i);
      if (!el) return;
      try {
        var c = echarts.init(el);
        c.setOption(opt);
        chartInstances.push(c);
      } catch (e) {
        el.innerHTML = '<div class="chart-error">图表渲染失败：' + esc(e.message) + '</div>';
      }
    });
  }

  // ===== 岗位图谱 =====
  var TYPE_COLORS = {
    "岗位群": "#5470c6",
    "岗位": "#91cc75",
    "典型工作任务": "#fac858",
    "知识要求": "#ee6666",
    "技能要求": "#73c0de",
    "素养要求": "#3ba272",
    "工具/平台": "#fc8452"
  };

  var nodeMap = {};
  GRAPH.nodes.forEach(function (n) { nodeMap[n.id] = n; });

  var adj = {};
  GRAPH.edges.forEach(function (e) { (adj[e.source] = adj[e.source] || []).push(e.target); });

  var hasIncoming = {};
  GRAPH.edges.forEach(function (e) { hasIncoming[e.target] = 1; });
  var roots = GRAPH.nodes.filter(function (n) { return !hasIncoming[n.id]; });

  function nodeName(id) { return nodeMap[id] ? nodeMap[id].name : id; }

  function buildTree() {
    function build(n) {
      var kids = (adj[n.id] || []).map(function (id) { return build(nodeMap[id]); });
      var o = {
        name: n.name,
        itemStyle: { color: TYPE_COLORS[n.type] || '#999' },
        symbolSize: n.type === '岗位群' ? 14 : (n.type === '岗位' ? 11 : 9)
      };
      if (kids.length) o.children = kids;
      return o;
    }
    return { name: GRAPH.graphName || '岗位图谱分析', children: roots.map(build) };
  }

  function tooltipTree(p) {
    return '<b>' + esc(p.name) + '</b>';
  }

  function treeOption(radial) {
    var base = {
      type: 'tree',
      data: [buildTree()],
      top: '2%', left: '5%', bottom: '2%', right: '18%',
      roam: true,
      expandAndCollapse: true,
      symbol: 'circle',
      edgeShape: 'curve',
      lineStyle: { color: '#b8c0cc', width: 1.4, curveness: 0.5 },
      emphasis: { focus: 'descendant' }
    };
    if (radial) {
      base.layout = 'radial';
      base.label = { position: 'radial', fontSize: 11 };
      base.leaves = { label: { position: 'radial', fontSize: 11 } };
    } else {
      base.layout = 'orthogonal';
      base.orient = 'LR';
      base.label = { position: 'left', verticalAlign: 'middle', align: 'right', fontSize: 11 };
      base.leaves = { label: { position: 'right', verticalAlign: 'middle', align: 'left', fontSize: 11 } };
    }
    return { tooltip: { trigger: 'item', formatter: tooltipTree }, series: [base] };
  }

  function graphOption() {
    return {
      tooltip: {
        formatter: function (p) {
          if (p.dataType === 'edge') {
            return esc(nodeName(p.data.source)) + ' —' + esc(p.data.relation) + '→ ' + esc(nodeName(p.data.target));
          }
          return esc(p.data.name);
        }
      },
      legend: [{ data: GRAPH.nodeTypes.slice(), bottom: 0 }],
      series: [{
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        categories: GRAPH.nodeTypes.map(function (t) {
          return { name: t, itemStyle: { color: TYPE_COLORS[t] || '#999' } };
        }),
        data: GRAPH.nodes.map(function (n) {
          return { id: n.id, name: n.name, category: GRAPH.nodeTypes.indexOf(n.type), symbolSize: 24 };
        }),
        links: GRAPH.edges.map(function (e) {
          return { source: e.source, target: e.target, relation: e.relation };
        }),
        label: { show: true, position: 'right', fontSize: 10, color: '#333' },
        edgeLabel: {
          show: true,
          formatter: function (p) { return p.data.relation || ''; },
          fontSize: 9, color: '#8a94a6'
        },
        force: { repulsion: 480, edgeLength: [70, 150], gravity: 0.08 },
        lineStyle: { color: '#c0c8d4', opacity: 0.6, curveness: 0.12 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 2 } }
      }]
    };
  }

  function legendHtml() {
    var html = '<div class="legend">';
    GRAPH.nodeTypes.forEach(function (t) {
      html += '<span><i style="background:' + (TYPE_COLORS[t] || '#999') + '"></i>' + esc(t) + '</span>';
    });
    return html + '</div>';
  }

  function buildTableHtml() {
    var html = legendHtml();
    html += '<h3>节点（按类型分组）</h3>';
    GRAPH.nodeTypes.forEach(function (t) {
      var ns = GRAPH.nodes.filter(function (n) { return n.type === t; });
      if (!ns.length) return;
      var isJob = t === '岗位';
      html += '<h4>' + esc(t) + '</h4><table><thead><tr><th>名称</th>' +
        (isJob ? '<th>层级</th>' : '') + '</tr></thead><tbody>';
      ns.forEach(function (n) {
        html += '<tr><td>' + esc(n.name) + '</td>' +
          (isJob ? '<td>' + esc(n.level || '') + '</td>' : '') + '</tr>';
      });
      html += '</tbody></table>';
    });
    html += '<h3>关系（边）</h3><table><thead><tr><th>源节点</th><th>关系</th><th>目标节点</th></tr></thead><tbody>';
    GRAPH.edges.forEach(function (e) {
      html += '<tr><td>' + esc(nodeName(e.source)) + '</td><td>' + esc(e.relation) +
        '</td><td>' + esc(nodeName(e.target)) + '</td></tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  var graphChart = null;
  var currentView = GRAPH.defaultView || 'treeLeftToRight';

  function renderGraph(view) {
    currentView = view;
    var canvas = document.getElementById('graph-canvas');
    var tableEl = document.getElementById('graph-table');
    var wrap = document.getElementById('graph-wrap');
    document.querySelectorAll('.graph-toolbar button').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-view') === view);
    });

    if (view === 'table') {
      canvas.style.display = 'none';
      tableEl.style.display = 'block';
      tableEl.innerHTML = buildTableHtml();
      return;
    }
    tableEl.style.display = 'none';
    canvas.style.display = 'block';
    if (!window.echarts) return;
    if (!graphChart) graphChart = echarts.init(canvas);
    var opt;
    if (view === 'radialTree') opt = treeOption(true);
    else if (view === 'graph') opt = graphOption();
    else opt = treeOption(false);
    graphChart.clear();
    graphChart.setOption(opt);
    if (graphChart.resize) graphChart.resize();
  }

  function buildToolbar() {
    var wrap = document.getElementById('graph-wrap');
    var views = [
      ['treeLeftToRight', '树状图（左→右）'],
      ['graph', '关系网络'],
      ['radialTree', '径向树'],
      ['table', '表格']
    ];
    var html = '<div class="graph-toolbar">';
    views.forEach(function (v) {
      html += '<button type="button" data-view="' + v[0] + '">' + v[1] + '</button>';
    });
    html += '</div><div id="graph-canvas"></div><div id="graph-table"></div>';
    wrap.innerHTML = html;
    wrap.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function () { renderGraph(b.getAttribute('data-view')); });
    });
    renderGraph(currentView);
  }

  // ===== 初始化 =====
  renderCharts();
  if (GRAPH && GRAPH.nodes) buildToolbar();

  window.addEventListener('resize', function () {
    chartInstances.forEach(function (c) { if (c.resize) c.resize(); });
    if (graphChart && graphChart.resize) graphChart.resize();
  });
})();
</script>
"""


def build_html(toc: str, body: str, charts: list[dict], graph: dict | None) -> str:
    charts_json = json.dumps(charts, ensure_ascii=False)
    graph_json = json.dumps(graph, ensure_ascii=False) if graph else "null"
    js = JS_TEMPLATE.replace("__CHARTS_JSON__", charts_json).replace("__GRAPH_JSON__", graph_json)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TITLE}</title>
<style>{CSS}</style>
</head>
<body>
<div class="report">
{toc}
{body}
</div>
<script src="libs/echarts.min.js"></script>
<script src="libs/echarts-wordcloud.min.js"></script>
{js}
</body>
</html>
"""


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    processed, charts, graph = extract_blocks(text)
    toc, body = convert_markdown(processed)
    # 给"数据来源"段落加样式
    body = body.replace("<p>数据来源", '<p class="source-note">数据来源')
    html = build_html(toc, body, charts, graph)
    DST.write_text(html, encoding="utf-8")
    print(f"charts: {len(charts)}")
    print(f"graph : {'有' if graph else '无'}（{len(graph['nodes']) if graph else 0} 节点 / {len(graph['edges']) if graph else 0} 边）")
    print(f"output: {DST} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
