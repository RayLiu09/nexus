import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const renderer = fileURLToPath(new URL('./render_competency_analysis.mjs', import.meta.url));
const reference = readFileSync(new URL('../reference.md', import.meta.url), 'utf8');

function fixture() {
  const data = JSON.parse(reference.match(/```json\n([\s\S]*?)\n```/)[1]);
  Object.assign(data.sources[0], {
    recordId: 'fixture-standard', normalizedRefId: 'fixture-ref', sectionId: 'block-1',
    title: '测试标准 <img src=x onerror=alert(1)>',
  });
  delete data.sources[0].publisher;
  delete data.sources[0].publishedAt;
  delete data.sources[0].url;
  data.researchChecks[1] = { ...data.researchChecks[1], status: 'verified',
    retrievalMethod: 'nexus_api', sourceRefs: ['source-1'] };
  return data;
}

function render(data) {
  const dir = mkdtempSync(join(tmpdir(), 'nexus-competency-test-'));
  const input = join(dir, 'data.json'), output = join(dir, 'analysis.html');
  writeFileSync(input, JSON.stringify(data));
  const result = spawnSync(process.execPath, [renderer, '--input', input, '--output', output], { encoding: 'utf8' });
  const html = existsSync(output) ? readFileSync(output, 'utf8') : null;
  rmSync(dir, { recursive: true, force: true });
  return { ...result, html };
}

test('platform records need locators and read content but no external metadata', () => {
  const result = render(fixture());
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.html, /fixture-standard/);
  assert.match(result.html, /\\u003cimg/);
  assert.doesNotMatch(result.html, /<img src=x onerror/);
  assert.match(result.html, /data-mode="pgsd"/);
  assert.match(result.html, /data-mode="ksa"/);
});

for (const [label, mutate, expected] of [
  ['missing platform record', d => delete d.sources[0].recordId, /recordId/],
  ['absolute path as locator', d => d.sources[0].recordId = '/home/private', /定位不合法/],
  ['unknown provider', d => d.sources[0].provider = 'other', /provider/],
  ['unread adopted source', d => d.sources[0].verified = false, /已核验正文/],
  ['missing adopted excerpt', d => delete d.sources[0].excerpt, /摘要/],
  ['wrong retrieval tool', d => d.researchChecks[1].retrievalMethod = 'web_search', /入口与类别不匹配/],
  ['certificate using platform record', d => d.researchChecks[2].sourceRefs = ['source-1'], /检索边界/],
  ['cross task ability link', d => d.tasks[0].requirements[0].workContentIds = ['other-work'], /跨任务/],
]) {
  test('rejects ' + label + ' before writing HTML', () => {
    const data = fixture(); mutate(data);
    const result = render(data);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, expected);
    assert.equal(result.html, null);
  });
}

test('certificate web sources retain URL and content requirements', () => {
  const data = fixture();
  data.sources.push({ ...data.sources[0], id: 'certificate', provider: 'web',
    publisher: '证书资料', url: 'https://www.mohrss.gov.cn/certificate', kind: 'official' });
  data.researchChecks[2] = { ...data.researchChecks[2], status: 'verified',
    retrievalMethod: 'nexus_web_search', sourceRefs: ['certificate'] };
  assert.equal(render(data).status, 0);
  delete data.sources[1].url;
  assert.match(render(data).stderr, /缺少 URL/);
});

test('legacy source records remain readable', () => {
  const data = fixture();
  delete data.sources[0].provider;
  data.sources[0].publisher = '原有用户资料';
  data.sources[0].kind = 'user';
  assert.equal(render(data).status, 0);
});
