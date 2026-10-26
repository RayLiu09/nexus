(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('analysis-data').textContent);
  const $ = (id) => document.getElementById(id);
  const esc = (value = '') =>
    String(value).replace(
      /[&<>"']/g,
      (c) =>
        ({
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;',
        })[c],
    );
  const state = { mode: 'ksa', task: 'all', query: '', pending: false };
  const statusNames = {
    supported: '来源支持',
    inferred: '分析归纳',
    pending: '待专家确认',
  };
  const relations = {
    alias: '同义 / 近同职责',
    collaborator: '协作岗位',
    progression: '发展岗位',
  };
  const sourceKinds = {
    standard: '职业标准',
    official: '公共职业资料',
    industry: '行业资料',
    employer: '企业资料',
    user: '用户材料',
    other: '其他资料',
  };
  const sourceMap = new Map(
    data.sources.map((source, index) => [source.id, { ...source, number: index + 1 }]),
  );
  const allRequirements = data.tasks.flatMap((task) => task.requirements);
  const badge = (item) =>
    `<span class="evidence ${esc(item.evidenceStatus)}">${esc(statusNames[item.evidenceStatus])}</span>`;
  const refs = (ids) =>
    `<span class="refs">${ids.map((id) => `<button class="ref" data-source="${esc(id)}" aria-label="查看依据 ${sourceMap.get(id).number}">[${sourceMap.get(id).number}]</button>`).join('')}</span>`;
  const evidence = (item) =>
    badge(item) +
    refs(item.sourceRefs) +
    (item.reason ? `<div class="reason">${esc(item.reason)}</div>` : '');

  function requirement(item, task, application = false) {
    const contexts = task.workContents
      .filter((work) => item.workContentIds.includes(work.id))
      .map((work) => work.code + ' ' + work.title)
      .join('、');
    return `<div class="requirement" data-requirement-id="${esc(item.id)}"><strong>${esc(item.label)}</strong><p>${esc(state.mode === 'ksa' ? item.ksaContent : item.pgContent)}</p>${evidence(item)}${application ? `<div class="application">应用：${esc(contexts)}</div>` : ''}</div>`;
  }

  function matches(item, task) {
    if (state.pending && item.evidenceStatus !== 'pending' && task.evidenceStatus !== 'pending')
      return false;
    if (!state.query) return true;
    const contexts = task.workContents.filter((work) => item.workContentIds.includes(work.id));
    return [
      task.title,
      task.description,
      task.output,
      item.label,
      item.ksaContent,
      item.pgContent,
      ...contexts.flatMap((work) => [
        work.code,
        work.title,
        work.action,
        work.output,
        work.qualityCriteria,
      ]),
    ]
      .join(' ')
      .toLocaleLowerCase()
      .includes(state.query);
  }

  function workCell(work) {
    return `<div class="work-code">${esc(work.code)}</div><h3 class="work-title">${esc(work.title)}</h3><p class="work-action">${esc(work.action)}</p><p class="work-detail"><b>交付物：</b>${esc(work.output)}</p><p class="work-detail"><b>质量要求：</b>${esc(work.qualityCriteria)}</p>`;
  }

  const noItems = '<span class="no-items">当前范围无对应条目</span>';
  function renderTask(task, items) {
    const works = task.workContents.filter((work) =>
      items.some((item) => item.workContentIds.includes(work.id)),
    );
    const content = (group) =>
      group.length ? group.map((item) => requirement(item, task)).join('') : noItems;
    let table = '';
    let sharedItems;
    let groups;
    if (state.mode === 'ksa') {
      table = `<table><thead><tr><th>工作内容</th><th class="col-knowledge">知识</th><th class="col-skill">技能</th><th class="col-quality">素养</th></tr></thead><tbody>${works.map((work) => `<tr><td>${workCell(work)}</td>${['knowledge', 'skill', 'quality'].map((type) => `<td>${content(items.filter((item) => item.ksaType === type && item.workContentIds.includes(work.id)))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
      sharedItems = [];
      groups = [];
    } else {
      table = `<table class="pg-table"><thead><tr><th>工作内容</th><th class="col-knowledge">P · 职业能力</th></tr></thead><tbody>${works.map((work) => `<tr><td>${workCell(work)}</td><td>${content(items.filter((item) => item.pgType === 'P' && item.workContentIds.includes(work.id)))}</td></tr>`).join('')}</tbody></table>`;
      sharedItems = items.filter((item) => item.pgType !== 'P');
      groups = [
        ['G', 'G · 通用能力', ''],
        ['S', 'S · 社会能力', 'social'],
        ['D', 'D · 发展能力', 'development'],
      ];
    }
    const shared = sharedItems.length
      ? `<section class="shared"><h3>任务层面能力<small>应用于相关工作内容</small></h3><div class="shared-grid">${groups
          .filter(([type]) => sharedItems.some((item) => item.pgType === type))
          .map(([type, title, cls]) => {
            const group = sharedItems.filter((item) => item.pgType === type);
            return `<div class="shared-group"><h4 class="${cls}">${title}</h4>${group.map((item) => requirement(item, task, true)).join('')}</div>`;
          })
          .join('')}</div></section>`
      : '';
    return `<article class="task-section" data-task-id="${esc(task.id)}"><div class="task-title"><span class="task-code">${esc(task.code)}</span><h2>${esc(task.title)}</h2>${badge(task)}${refs(task.sourceRefs)}</div><p class="task-description">${esc(task.description)}</p><p class="task-output"><span>任务交付</span>${esc(task.output)}</p>${task.reason ? `<p class="reason">${esc(task.reason)}</p>` : ''}${works.length ? `<div class="table-wrap">${table}</div>` : ''}${shared}${task.notes.length ? `<div class="task-notes">${task.notes.map(esc).join('<br>')}</div>` : ''}</article>`;
  }

  function selection() {
    return data.tasks
      .filter((task) => state.task === 'all' || state.task === task.id)
      .map((task) => ({
        task,
        items: task.requirements.filter((item) => matches(item, task)),
      }))
      .filter(({ items }) => items.length);
  }

  function render() {
    document
      .querySelectorAll('.modes button')
      .forEach((button) =>
        button.setAttribute('aria-pressed', String(button.dataset.mode === state.mode)),
      );
    document.querySelectorAll('.nav-item').forEach((button) => {
      const selected = button.dataset.task === state.task;
      button.classList.toggle('active', selected);
      if (selected) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    });
    $('mode-description').textContent =
      state.mode === 'ksa'
        ? '围绕工作内容，查看需要掌握的知识、执行的技能与体现的素养。'
        : 'P 对应具体工作内容；G、S、D 在任务层面呈现，并注明应用位置。';
    const selected = selection();
    const count = selected.reduce((sum, { items }) => sum + items.length, 0);
    $('visible-count').textContent = `${selected.length} 项任务 · ${count} 条能力`;
    $('print-context').textContent =
      `分析初稿 · ${state.mode === 'ksa' ? '知识 / 技能 / 素养' : '职业 / 通用 / 社会 / 发展能力'} · 当前范围：${selected.length} 项任务、${count} 条能力${state.query ? ' · 关键词：' + state.query : ''}${state.pending ? ' · 仅看待确认' : ''}`;
    $('results').innerHTML = selected.length
      ? selected.map(({ task, items }) => renderTask(task, items)).join('')
      : '<div class="empty">未找到匹配内容。可调整关键词、任务范围或“仅看待确认”筛选。</div>';
  }

  function sourceLocator(source) {
    if (source.provider !== 'nexus') return '';
    return [source.resourceType, source.recordId, source.normalizedRefId, source.sectionId]
      .filter(Boolean).join(' · ');
  }

  function sourceStatus(source) {
    return source.verified ? '已读采用内容' : '尚未读取采用内容';
  }

  function sourceOrigin(source) {
    return source.provider === 'nexus' ? 'NEXUS 数据资产平台' : source.publisher || '联网资料';
  }

  function sourceHtml(source) {
    const link =
      source.url && /^https?:\/\//i.test(source.url)
        ? `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">打开来源原文 ↗</a><input class="source-url" aria-label="来源地址" readonly value="${esc(source.url)}">`
        : `<div class="source-meta">${source.provider === 'nexus' ? '平台资料，无需外部链接。' : '用户提供的材料，无公开链接。'}</div>`;
    return `<article class="source-item"><h3>[${source.number}] ${esc(source.title)}</h3><div class="source-meta">${esc(sourceKinds[source.kind])} · ${esc(sourceOrigin(source))} · ${sourceStatus(source)}${source.publishedAt ? ' · 发布 ' + esc(source.publishedAt) : ''}${source.verifiedAt ? ' · 读取 ' + esc(source.verifiedAt) : ''}</div>${sourceLocator(source) ? `<p class="source-meta">平台定位：${esc(sourceLocator(source))}</p>` : ''}<p><b>适用范围：</b>${esc(source.scope)}</p>${source.excerpt ? `<p><b>支持内容：</b>${esc(source.excerpt)}</p>` : ''}${source.limitations ? `<p><b>使用限制：</b>${esc(source.limitations)}</p>` : ''}${link}</article>`;
  }

  function showSources(id) {
    $('source-content').innerHTML = (id ? [sourceMap.get(id)] : [...sourceMap.values()])
      .map(sourceHtml)
      .join('');
    $('source-dialog-title').textContent = id ? '条目资料依据' : '全部资料依据';
    $('source-dialog').showModal();
  }

  let exportUrls = [];
  let copyText = '';
  const modeName = (mode) =>
    mode === 'ksa' ? '知识 / 技能 / 素养' : '职业 / 通用 / 社会 / 发展能力';
  function exportSnapshot() {
    const selected = selection();
    const count = selected.reduce((sum, row) => sum + row.items.length, 0);
    return {
      selected,
      mode: state.mode,
      count,
      range: `${modeName(state.mode)} · ${selected.length} 项任务 / ${count} 条能力${state.query ? ' · 关键词：' + state.query : ''}${state.pending ? ' · 仅看待确认' : ''}`,
    };
  }
  function clearExport() {
    const oldUrls = exportUrls;
    exportUrls = [];
    setTimeout(() => oldUrls.forEach((url) => URL.revokeObjectURL(url)), 60000);
    $('export-links').replaceChildren();
    $('copy-content').value = '';
    $('copy-content').hidden = true;
    $('copy-table').hidden = true;
    copyText = '';
  }
  function showExport(files, range, message, tableText = '') {
    clearExport();
    $('export-range').textContent = range;
    $('export-message').textContent = message;
    copyText = tableText;
    $('copy-table').hidden = !tableText;
    files.forEach((file) => {
      const blob = new Blob([file.content], { type: file.mime });
      const url = URL.createObjectURL(blob);
      exportUrls.push(url);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${data.occupation.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '-')}-职业能力分析${file.suffix}`;
      link.textContent = `${link.download} · ${(blob.size / 1024).toFixed(0)} KB · 点击下载`;
      $('export-links').append(link);
    });
    $('export-status').textContent = message;
    if (!$('export-dialog').open) $('export-dialog').showModal();
    $('export-links').querySelector('a')?.click();
  }
  function exportError(error) {
    clearExport();
    $('export-message').textContent = '未能生成文件：' + error.message;
    $('export-range').textContent = '请调整筛选或在系统浏览器中打开 HTML 后重试。';
    $('export-status').textContent = $('export-message').textContent;
    if (!$('export-dialog').open) $('export-dialog').showModal();
  }
  function exportHtml() {
    try {
      const clone = document.documentElement.cloneNode(true);
      ['source-dialog', 'export-dialog'].forEach((id) =>
        clone.querySelector('#' + id).removeAttribute('open'),
      );
      clone.querySelector('#search').setAttribute('value', '');
      clone.querySelector('#pending-only').removeAttribute('checked');
      ['export-status', 'export-message', 'export-range', 'export-links', 'copy-content'].forEach(
        (id) => (clone.querySelector('#' + id).textContent = ''),
      );
      ['copy-table', 'copy-content'].forEach((id) =>
        clone.querySelector('#' + id).setAttribute('hidden', ''),
      );
      clone.querySelector('#export-pdf').removeAttribute('disabled');
      showExport(
        [
          {
            content: '<!doctype html>\n' + clone.outerHTML,
            mime: 'text/html;charset=utf-8',
            suffix: '.html',
          },
        ],
        '完整岗位分析 · 包含两种模式及全部数据',
        'HTML 已生成并发起下载，重新打开可继续切换模式和导出。',
      );
    } catch (error) {
      exportError(error);
    }
  }

  function csvCell(value) {
    let text = String(value ?? '');
    if (/^[\s\uFEFF]*[=+@-]/u.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function detailRows(selected, mode) {
    const rows = [
      [
        '岗位',
        '分类模式',
        '任务编号',
        '典型工作任务',
        '任务描述',
        '任务交付物',
        '工作内容编号',
        '工作内容',
        '工作行动',
        '工作交付物',
        '质量要求',
        '能力ID',
        '能力类别',
        '简称',
        '完整能力表述',
        '证据状态',
        '判断说明',
        '来源',
      ],
    ];
    const classes = {
      knowledge: '知识',
      skill: '技能',
      quality: '素养',
      P: '职业能力',
      G: '通用能力',
      S: '社会能力',
      D: '发展能力',
    };
    for (const { task, items } of selected)
      for (const item of items) {
        const works = task.workContents.filter((work) => item.workContentIds.includes(work.id));
        rows.push([
          data.occupation,
          mode === 'ksa' ? '知识/技能/素养' : 'P/G/S/D',
          task.code,
          task.title,
          task.description,
          task.output,
          works.map((work) => work.code).join('；'),
          works.map((work) => work.title).join('；'),
          works.map((work) => work.action).join('；'),
          works.map((work) => work.output).join('；'),
          works.map((work) => work.qualityCriteria).join('；'),
          item.id,
          classes[mode === 'ksa' ? item.ksaType : item.pgType],
          item.label,
          mode === 'ksa' ? item.ksaContent : item.pgContent,
          statusNames[item.evidenceStatus],
          item.reason || '',
          item.sourceRefs
            .map((id) => {
              const source = sourceMap.get(id);
              return `[${source.number}] ${source.title}${source.provider === 'nexus' ? ' NEXUS ' + sourceLocator(source) : ''}${source.url ? ' ' + source.url : ''}`;
            })
            .join('；'),
        ]);
      }
    return rows;
  }

  function groups(mode) {
    return mode === 'ksa'
      ? [
          ['knowledge', '知识'],
          ['skill', '技能'],
          ['quality', '素养'],
        ]
      : [
          ['P', '职业能力'],
          ['G', '通用能力'],
          ['S', '社会能力'],
          ['D', '发展能力'],
        ];
  }
  function abilityText(items, mode, evidenceDetails = false) {
    return items
      .map(
        (item) =>
          `${item.label}：${mode === 'ksa' ? item.ksaContent : item.pgContent}${evidenceDetails ? '\n' + statusNames[item.evidenceStatus] + (item.sourceRefs.length ? ' ' + item.sourceRefs.map((id) => '[' + sourceMap.get(id).number + ']').join('') : '') + (item.reason ? ' · ' + item.reason : '') : ''}`,
      )
      .join('\n\n');
  }
  function workRows(snapshot, pdf = false) {
    const result = [];
    for (const { task, items } of snapshot.selected) {
      for (const work of task.workContents) {
        const related = items.filter((item) => item.workContentIds.includes(work.id));
        if (!related.length) continue;
        const abilities = groups(snapshot.mode).map(([type]) =>
          abilityText(
            related.filter(
              (item) => (snapshot.mode === 'ksa' ? item.ksaType : item.pgType) === type,
            ),
            snapshot.mode,
            pdf,
          ),
        );
        result.push(
          pdf
            ? [
                `${work.code} ${work.title}\n${work.action}\n交付物：${work.output}\n质量要求：${work.qualityCriteria}`,
                ...abilities,
              ]
            : [
                task.code,
                task.title,
                work.code,
                work.title,
                work.action,
                work.output,
                work.qualityCriteria,
                ...abilities,
              ],
        );
      }
    }
    return result;
  }
  function scopeParagraphs(snapshot) {
    return [
      '岗位：' + data.occupation + ' · ' + [data.industry, data.region, data.level].join(' / '),
      '整理日期：' + data.generatedAt + ' · 导出范围：' + snapshot.range,
      '分析摘要：' + data.summary,
      ...data.relatedRoles.map(
        (role) =>
          `相关岗位：${role.name}（${relations[role.relation]}） · ${role.boundary} · ${statusNames[role.evidenceStatus]}`,
      ),
      ...data.assumptions.map((text) => '范围假设：' + text),
      ...data.limitations.map((text) => '资料限制：' + text),
      ...data.researchChecks.map(
        (check) =>
          `${researchNames[check.category]}：${researchStatuses[check.status]} · ${check.summary}\n适用范围：${check.scope} · 检索日期：${check.checkedAt}\n检索词：${check.queries.join('；')}${check.sourceRefs.length ? '\n来源：' + check.sourceRefs.map((id) => '[' + sourceMap.get(id).number + ']').join(' ') : ''}`,
      ),
      ...[...sourceMap.values()].map(
        (source) =>
          `[${source.number}] ${source.title} · ${sourceOrigin(source)} · ${sourceStatus(source)}\n${source.provider === 'nexus' ? '平台定位：' + sourceLocator(source) : source.url || '用户材料，无公开链接'}\n适用范围：${source.scope}\n支持内容：${source.excerpt || '未提供摘录'}\n使用限制：${source.limitations || '未列出额外限制'}${source.publishedAt ? '\n发布日期：' + source.publishedAt : ''}${source.verifiedAt ? '\n读取日期：' + source.verifiedAt : ''}`,
      ),
    ];
  }
  function exportTable() {
    try {
      const snapshot = exportSnapshot();
      if (!snapshot.count) throw new Error('当前筛选范围没有可导出的能力，请清除或调整筛选');
      const details = detailRows(snapshot.selected, snapshot.mode);
      const main = [
        [
          '任务编号',
          '典型工作任务',
          '工作编号',
          '工作内容',
          '执行内容',
          '交付物',
          '质量要求',
          ...groups(snapshot.mode).map((group) => group[1]),
        ],
        ...workRows(snapshot),
      ];
      const bytes = window.CompetencyFiles.createSpreadsheet([
        {
          name: '工作内容与能力',
          rows: main,
          widths: [12, 26, 12, 26, 40, 30, 34, ...groups(snapshot.mode).map(() => 48)],
        },
        {
          name: '能力明细',
          rows: details,
          widths: [20, 22, 12, 28, 40, 30, 18, 32, 40, 32, 34, 18, 18, 22, 55, 18, 40, 50],
        },
        {
          name: '分析范围与依据',
          rows: [
            ['项目', '内容'],
            ...scopeParagraphs(snapshot).map((text, index) => [index + 1, text]),
          ],
          widths: [12, 110],
        },
      ]);
      const csv = '\uFEFF' + details.map((row) => row.map(csvCell).join(',')).join('\r\n');
      const tsv = main.map((row) => row.map((value) => csvCell(value)).join('\t')).join('\r\n');
      showExport(
        [
          {
            content: bytes,
            mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            suffix: '-' + snapshot.mode.toUpperCase() + '.xlsx',
          },
          {
            content: csv,
            mime: 'text/csv;charset=utf-8',
            suffix: '-' + snapshot.mode.toUpperCase() + '.csv',
          },
        ],
        snapshot.range,
        'Excel 已生成并发起下载，包含工作内容与能力、能力明细、分析范围与依据三个工作表。也可下载 CSV 或复制表格。',
        tsv,
      );
    } catch (error) {
      exportError(error);
    }
  }
  async function exportPdf() {
    const button = $('export-pdf');
    button.disabled = true;
    try {
      const snapshot = exportSnapshot();
      if (!snapshot.count) throw new Error('当前筛选范围没有可导出的能力，请清除或调整筛选');
      clearExport();
      $('export-message').textContent = '正在生成 PDF，请稍候…';
      $('export-range').textContent = snapshot.range;
      if (!$('export-dialog').open) $('export-dialog').showModal();
      await new Promise((resolve) => setTimeout(resolve, 0));
      const report = window.CompetencyFiles.createPdf({
        title: data.occupation + ' · 职业能力分析',
        subtitle: snapshot.range + ' · ' + data.generatedAt,
        sections: [
          ...snapshot.selected.map(({ task, items }) => ({
            title: task.code + ' ' + task.title,
            paragraphs: [
              task.description,
              '任务交付物：' + task.output,
              '任务证据：' +
                statusNames[task.evidenceStatus] +
                ' ' +
                task.sourceRefs.map((id) => '[' + sourceMap.get(id).number + ']').join(' ') +
                (task.reason ? ' · ' + task.reason : ''),
              ...task.notes,
            ],
            headers: ['工作内容', ...groups(snapshot.mode).map((group) => group[1])],
            widths: snapshot.mode === 'ksa' ? [28, 24, 24, 24] : [24, 22, 18, 18, 18],
            rows: workRows({ ...snapshot, selected: [{ task, items }] }, true),
          })),
          {
            title: '分析范围与资料依据',
            paragraphs: scopeParagraphs(snapshot),
          },
        ],
      });
      showExport(
        [
          {
            content: report.bytes,
            mime: 'application/pdf',
            suffix: '-' + snapshot.mode.toUpperCase() + '.pdf',
          },
        ],
        snapshot.range,
        `PDF 已生成（${report.pages} 页）并发起下载。文件采用高清图像页面，可阅读与打印，文字不支持搜索或复制。`,
      );
    } catch (error) {
      exportError(error);
    } finally {
      button.disabled = false;
    }
  }

  $('date').textContent = '整理于 ' + data.generatedAt;
  $('scope').textContent = [data.industry, data.region, data.level].join(' / ');
  $('summary').textContent = data.summary;
  const workCount = data.tasks.reduce((sum, task) => sum + task.workContents.length, 0);
  $('stats').innerHTML = [
    [data.tasks.length, '典型任务'],
    [workCount, '工作内容'],
    [allRequirements.length, '能力要求'],
  ]
    .map(([number, title]) => `<div><strong>${number}</strong><span>${title}</span></div>`)
    .join('');
  const researchNames = {
    dictionary: '职业分类大典',
    teaching_standard: '专业教学标准',
    certificate: '职业证书与评价要求',
  };
  const researchStatuses = {
    verified: '已读采用内容',
    not_found: '检索未找到匹配资料',
    unverified: '找到线索，尚未核验',
    unavailable: '检索受限，待补充',
  };
  const researchHtml = data.researchChecks
    .map(
      (check) =>
        `<article class="research-check"><h4>${esc(researchNames[check.category])}<span class="research-status">${esc(researchStatuses[check.status])}</span></h4><p>${esc(check.summary)}${refs(check.sourceRefs)}</p><p class="source-meta">适用范围：${esc(check.scope)} · 检索日期：${esc(check.checkedAt)}</p>${check.queries.length ? `<p class="source-meta">检索词：${check.queries.map(esc).join('；')}</p>` : ''}</article>`,
    )
    .join('');
  $('limits-count').textContent =
    `(${data.assumptions.length + data.limitations.length + data.researchChecks.length})`;
  $('scope-notes').innerHTML =
    `<p><b>范围假设</b></p>${data.assumptions.map((text) => `<p>${esc(text)}</p>`).join('')}<p><b>资料与结论限制</b></p>${data.limitations.map((text) => `<p>${esc(text)}</p>`).join('')}<p><b>三类资料检索记录</b></p>${researchHtml}`;
  $('roles').innerHTML = data.relatedRoles.length
    ? data.relatedRoles
        .map(
          (role) =>
            `<article class="role"><div class="role-top"><strong>${esc(role.name)}</strong><span class="relation">${esc(relations[role.relation])}</span></div><p>${esc(role.boundary)}</p>${evidence(role)}${
              role.includedTaskIds.length
                ? `<div class="application">关联任务：${esc(
                    data.tasks
                      .filter((task) => role.includedTaskIds.includes(task.id))
                      .map((task) => task.code)
                      .join('、'),
                  )}</div>`
                : ''
            }</article>`,
        )
        .join('')
    : '<p class="no-items">未确认相关岗位，详见分析范围。</p>';
  $('task-count').textContent = data.tasks.length;
  $('task-nav').innerHTML =
    `<button class="nav-item active" data-task="all"><span class="nav-index">全部</span>完整岗位分析</button>${data.tasks.map((task) => `<button class="nav-item" data-task="${esc(task.id)}"><span class="nav-index">${esc(task.code)}</span>${esc(task.title)}</button>`).join('')}`;
  $('print-sources').innerHTML =
    `<h2>资料依据与分析范围</h2><p>${data.assumptions.concat(data.limitations).map(esc).join('<br>')}</p>${researchHtml}${[...sourceMap.values()].map(sourceHtml).join('')}`;
  document.addEventListener('click', (event) => {
    const source = event.target.closest('[data-source]');
    if (source) showSources(source.dataset.source);
    const task = event.target.closest('[data-task]');
    if (task) {
      state.task = task.dataset.task;
      render();
    }
    const mode = event.target.closest('[data-mode]');
    if (mode) {
      state.mode = mode.dataset.mode;
      render();
    }
  });
  $('search').value = '';
  $('pending-only').checked = false;
  $('search').addEventListener('input', (event) => {
    state.query = event.target.value.trim().toLocaleLowerCase();
    render();
  });
  $('pending-only').addEventListener('change', (event) => {
    state.pending = event.target.checked;
    render();
  });
  $('all-sources').addEventListener('click', () => showSources());
  $('close-sources').addEventListener('click', () => $('source-dialog').close());
  $('source-dialog').addEventListener('click', (event) => {
    if (event.target === $('source-dialog')) {
      const box = event.target.getBoundingClientRect();
      if (
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom
      )
        event.target.close();
    }
  });
  $('export-html').addEventListener('click', exportHtml);
  $('export-table').addEventListener('click', exportTable);
  $('export-pdf').addEventListener('click', exportPdf);
  $('close-export').addEventListener('click', () => $('export-dialog').close());
  $('export-dialog').addEventListener('close', clearExport);
  $('copy-table').addEventListener('click', async () => {
    const text = copyText;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('无法自动复制');
      await navigator.clipboard.writeText(text);
      $('export-message').textContent = '表格已复制，请在 Excel 中粘贴。';
    } catch {
      $('copy-content').value = text;
      $('copy-content').hidden = false;
      $('copy-content').focus();
      $('copy-content').select();
      $('export-message').textContent = '已选中表格内容，请按 Ctrl+C 复制，再在 Excel 中粘贴。';
    }
  });
  render();
})();
