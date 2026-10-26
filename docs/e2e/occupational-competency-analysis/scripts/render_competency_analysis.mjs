#!/usr/bin/env node
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

const args = {};
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  if (!['--input', '--output'].includes(key) || !process.argv[index + 1]) {
    throw new Error(
      '用法：node render_competency_analysis.mjs --input data.json --output analysis.html',
    );
  }
  args[key.slice(2)] = process.argv[index + 1];
}

function validate(data) {
  const warnings = [];
  const identifiers = new Set();
  const statuses = ['supported', 'inferred', 'pending'];
  const fail = (message) => {
    throw new Error('数据校验失败：' + message);
  };
  const string = (value, where) => {
    if (typeof value !== 'string' || !value.trim()) fail(where + '不能为空');
  };
  const list = (value, where, nonempty = false) => {
    if (!Array.isArray(value) || (nonempty && !value.length))
      fail(where + '必须是' + (nonempty ? '非空' : '') + '数组');
  };
  const unique = (object, where) => {
    if (!object || typeof object !== 'object' || Array.isArray(object)) fail(where + '必须是对象');
    string(object.id, where + '.id');
    if (identifiers.has(object.id)) fail('重复 id：' + object.id);
    identifiers.add(object.id);
  };
  const date = (value, where, required = false) => {
    if (!value && !required) return;
    if (
      typeof value !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !Number.isFinite(Date.parse(value)) ||
      new Date(value).toISOString().slice(0, 10) !== value
    ) {
      fail(where + '必须是有效 YYYY-MM-DD 日期');
    }
  };
  if (!data || data.schemaVersion !== 1) fail('schemaVersion 必须为 1');
  for (const key of ['occupation', 'industry', 'region', 'level', 'summary'])
    string(data[key], key);
  date(data.generatedAt, 'generatedAt', true);
  for (const key of ['assumptions', 'limitations']) {
    list(data[key], key);
    data[key].forEach((item) => string(item, key));
  }
  list(data.sources, 'sources');
  const sourceMap = new Map();
  for (const source of data.sources) {
    unique(source, '来源');
    for (const key of ['title', 'scope'])
      string(source[key], '来源 ' + source.id + '.' + key);
    if (source.provider !== undefined && !['nexus', 'web'].includes(source.provider))
      fail('来源 provider 不合法');
    if (source.provider === 'nexus') {
      for (const key of ['resourceType', 'recordId']) string(source[key], '平台来源.' + key);
      for (const key of ['recordId', 'normalizedRefId', 'sectionId']) {
        if (source[key] !== undefined && (typeof source[key] !== 'string' || !/^[\p{L}\p{N}_.:-]+$/u.test(source[key])))
          fail('平台引用定位不合法：' + key);
      }
    } else string(source.publisher, '来源 ' + source.id + '.publisher');
    if (!['standard', 'official', 'industry', 'employer', 'user', 'other'].includes(source.kind))
      fail('来源 kind 不合法');
    if (typeof source.verified !== 'boolean') fail('来源 verified 必须为布尔值');
    if (source.url) {
      try {
        const url = new URL(source.url);
        if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password)
          fail('来源 URL 只允许无凭据的 http(s)');
        if (['example.com', 'example.org', 'example.net'].includes(url.hostname))
          fail('不能把示例域名登记为证据');
      } catch {
        fail('来源 URL 不合法：' + source.id);
      }
    } else if (source.provider !== 'nexus' && (source.kind !== 'user' || source.provider === 'web'))
      fail('公开来源缺少 URL：' + source.id);
    date(source.publishedAt, '来源发布日期');
    date(source.verifiedAt, '来源核验日期', source.verified);
    if (source.verified) string(source.excerpt, '已核验来源摘要');
    sourceMap.set(source.id, source);
  }
  list(data.researchChecks, '三类资料检索记录 researchChecks', true);
  const researchCategories = new Set(['dictionary', 'teaching_standard', 'certificate']);
  for (const check of data.researchChecks) {
    if (!check || !researchCategories.delete(check.category)) fail('检索类别缺失、重复或不合法');
    if (!['verified', 'not_found', 'unverified', 'unavailable'].includes(check.status))
      fail('检索状态不合法');
    if (check.retrievalMethod !== undefined) {
      const expected = check.category === 'certificate' ? 'nexus_web_search' : 'nexus_api';
      if (check.retrievalMethod !== expected) fail('资料检索入口与类别不匹配');
    }
    for (const key of ['summary', 'scope']) string(check[key], '检索记录.' + key);
    date(check.checkedAt, '检索日期', true);
    list(check.queries, '检索词', check.status !== 'unavailable');
    check.queries.forEach((query) => string(query, '检索词'));
    list(check.sourceRefs, '检索来源引用');
    if (new Set(check.sourceRefs).size !== check.sourceRefs.length) fail('检索来源引用重复');
    for (const ref of check.sourceRefs)
      if (!sourceMap.has(ref)) fail('检索记录引用不存在的来源：' + ref);
    for (const ref of check.sourceRefs) {
      const provider = sourceMap.get(ref).provider;
      if (provider && provider !== (check.category === 'certificate' ? 'web' : 'nexus'))
        fail('资料来源不符合 NEXUS/证书联网检索边界');
    }
    if (
      check.status === 'verified' &&
      (!check.sourceRefs.length || check.sourceRefs.some((ref) => !sourceMap.get(ref).verified))
    )
      fail('已核验检索记录必须引用已核验正文');
    if (check.status !== 'verified')
      warnings.push('资料检索尚未核验：' + check.category + '（' + check.status + '）');
  }
  if (researchCategories.size) fail('必须逐项记录职业分类大典、专业教学标准、职业证书的检索结果');
  const evidence = (object, where) => {
    if (!statuses.includes(object.evidenceStatus)) fail(where + '缺少有效 evidenceStatus');
    list(object.sourceRefs, where + '.sourceRefs');
    if (new Set(object.sourceRefs).size !== object.sourceRefs.length)
      fail(where + '存在重复来源引用');
    for (const reference of object.sourceRefs)
      if (!sourceMap.has(reference)) fail(where + '引用不存在的来源：' + reference);
    if (object.evidenceStatus === 'supported') {
      if (
        !object.sourceRefs.length ||
        object.sourceRefs.some((ref) => !sourceMap.get(ref).verified)
      )
        fail(where + '“来源支持”必须引用已核验正文');
    } else string(object.reason, where + '归纳或待确认理由');
  };
  list(data.tasks, 'tasks', true);
  if (data.tasks.length > 3)
    warnings.push('单岗位典型工作任务原则上不超过 3 条，请归并并聚焦最核心任务，不追求全面罗列');
  const taskIds = new Set(data.tasks.map((task) => task?.id));
  const totals = {
    tasks: data.tasks.length,
    workContents: 0,
    requirements: 0,
    supported: 0,
    inferred: 0,
    pending: 0,
  };
  for (const task of data.tasks) {
    unique(task, '任务');
    for (const key of ['code', 'title', 'description', 'output'])
      string(task[key], '任务 ' + task.id + '.' + key);
    evidence(task, '任务 ' + task.id);
    list(task.notes, '任务 notes');
    task.notes.forEach((note) => string(note, '任务 notes'));
    list(task.workContents, '工作内容', true);
    list(task.requirements, '能力要求', true);
    const workIds = new Set();
    for (const work of task.workContents) {
      unique(work, '工作内容');
      for (const key of ['code', 'title', 'action', 'output', 'qualityCriteria'])
        string(work[key], '工作内容 ' + work.id + '.' + key);
      workIds.add(work.id);
      totals.workContents += 1;
    }
    const groups = new Set();
    for (const requirement of task.requirements) {
      unique(requirement, '能力要求');
      for (const key of ['label', 'ksaContent', 'pgContent'])
        string(requirement[key], '能力要求 ' + requirement.id + '.' + key);
      if (!['knowledge', 'skill', 'quality'].includes(requirement.ksaType))
        fail('ksaType 必须为 knowledge/skill/quality');
      if (!['P', 'G', 'S', 'D'].includes(requirement.pgType)) fail('pgType 必须为 P/G/S/D');
      list(requirement.workContentIds, '能力关联工作内容', true);
      if (new Set(requirement.workContentIds).size !== requirement.workContentIds.length)
        fail('能力关联工作内容重复');
      for (const ref of requirement.workContentIds)
        if (!workIds.has(ref)) fail('能力跨任务或引用不存在的工作内容：' + ref);
      if (requirement.pgType === 'P' && requirement.workContentIds.length !== 1)
        fail('P 能力必须且只能关联一个工作内容：' + requirement.id);
      evidence(requirement, '能力要求 ' + requirement.id);
      groups.add(requirement.pgType);
      totals.requirements += 1;
      totals[requirement.evidenceStatus] += 1;
      if (Array.from(requirement.label).length > 16) warnings.push('简称较长：' + requirement.id);
    }
    for (const work of task.workContents) {
      const related = task.requirements.filter((item) => item.workContentIds.includes(work.id));
      if (!related.some((item) => item.pgType === 'P')) fail('工作内容缺少职业能力 P：' + work.id);
      for (const type of ['knowledge', 'skill'])
        if (!related.some((item) => item.ksaType === type))
          warnings.push(
            work.code + ' 缺少' + (type === 'knowledge' ? '知识' : '技能') + '要求，请核验适用性',
          );
    }
    for (const type of ['G', 'S', 'D'])
      if (!groups.has(type))
        warnings.push(task.code + ' 缺少 ' + type + ' 维度，请在任务说明中注明不适用或待确认');
  }
  list(data.relatedRoles, 'relatedRoles');
  for (const role of data.relatedRoles) {
    unique(role, '相关岗位');
    string(role.name, '相关岗位名称');
    string(role.boundary, '相关岗位责任边界');
    if (!['alias', 'collaborator', 'progression'].includes(role.relation))
      fail('相关岗位关系不合法');
    list(role.includedTaskIds, '相关岗位 includedTaskIds');
    for (const taskId of role.includedTaskIds)
      if (!taskIds.has(taskId)) fail('相关岗位引用不存在的任务：' + taskId);
    evidence(role, '相关岗位 ' + role.name);
  }
  if (!data.sources.length) warnings.push('未提供可追溯来源，全部结论需明确证据限制');
  return { totals, warnings };
}

function escapeHtml(value) {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character],
  );
}

async function main() {
  if (!args.input || !args.output) throw new Error('必须指定 --input 和 --output');
  if (resolve(args.input) === resolve(args.output)) throw new Error('输出不能覆盖分析 JSON');
  const data = JSON.parse((await readFile(resolve(args.input), 'utf8')).replace(/^\uFEFF/, ''));
  const { totals, warnings } = validate(data);
  const assets = fileURLToPath(new URL('../assets/', import.meta.url));
  const [template, css, runtime, exports] = await Promise.all([
    readFile(resolve(assets, 'analysis.html'), 'utf8'),
    readFile(resolve(assets, 'analysis.css'), 'utf8'),
    readFile(resolve(assets, 'analysis-runtime.js'), 'utf8'),
    readFile(resolve(assets, 'file-export.js'), 'utf8'),
  ]);
  const replacements = {
    TITLE: escapeHtml(data.occupation),
    STYLE: css,
    DATA: JSON.stringify(data).replace(/</g, '\\u003c'),
    RUNTIME: runtime.replace(/<\/script/gi, '<\\/script'),
    EXPORTS: exports.replace(/<\/script/gi, '<\\/script'),
  };
  const html = template.replace(/\{\{([A-Z]+)\}\}/g, (_, key) => replacements[key]);
  const output = resolve(args.output);
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, html, 'utf8');
  console.log(
    JSON.stringify({
      output,
      occupation: data.occupation,
      ...totals,
      warnings,
    }),
  );
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
