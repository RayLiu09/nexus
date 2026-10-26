(() => {
  'use strict';
  const encoder = new TextEncoder();
  const xml = (value) =>
    String(value ?? '')
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
      .replace(
        /[&<>"']/g,
        (c) =>
          ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&apos;',
          })[c],
      );
  const join = (parts) => {
    const bytes = new Uint8Array(parts.reduce((n, part) => n + part.length, 0));
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.length;
    }
    return bytes;
  };
  const crcTable = Uint32Array.from({ length: 256 }, (_, index) => {
    let value = index;
    for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    return value >>> 0;
  });
  function zip(files) {
    const local = [];
    const central = [];
    let offset = 0;
    for (const [path, text] of files) {
      const name = encoder.encode(path);
      const body = encoder.encode(text);
      let crc = 0xffffffff;
      for (const byte of body) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);
      crc = (crc ^ 0xffffffff) >>> 0;
      const header = new Uint8Array(30);
      const view = new DataView(header.buffer);
      view.setUint32(0, 0x04034b50, true);
      view.setUint16(4, 20, true);
      view.setUint16(6, 0x800, true);
      view.setUint16(12, 33, true);
      view.setUint32(14, crc, true);
      view.setUint32(18, body.length, true);
      view.setUint32(22, body.length, true);
      view.setUint16(26, name.length, true);
      const directory = new Uint8Array(46);
      const dir = new DataView(directory.buffer);
      dir.setUint32(0, 0x02014b50, true);
      dir.setUint16(4, 20, true);
      dir.setUint16(6, 20, true);
      dir.setUint16(8, 0x800, true);
      dir.setUint16(14, 33, true);
      dir.setUint32(16, crc, true);
      dir.setUint32(20, body.length, true);
      dir.setUint32(24, body.length, true);
      dir.setUint16(28, name.length, true);
      dir.setUint32(42, offset, true);
      local.push(header, name, body);
      central.push(directory, name);
      offset += header.length + name.length + body.length;
    }
    const end = new Uint8Array(22);
    const view = new DataView(end.buffer);
    view.setUint32(0, 0x06054b50, true);
    view.setUint16(8, files.length, true);
    view.setUint16(10, files.length, true);
    view.setUint32(
      12,
      central.reduce((n, part) => n + part.length, 0),
      true,
    );
    view.setUint32(16, offset, true);
    return join([...local, ...central, end]);
  }
  function column(index) {
    let name = '';
    for (let number = index + 1; number; number = Math.floor((number - 1) / 26))
      name = String.fromCharCode(65 + ((number - 1) % 26)) + name;
    return name;
  }
  function createSpreadsheet(sheets) {
    const names = new Set();
    const ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
    const relNs = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
    const files = [];
    for (const [index, sheet] of sheets.entries()) {
      if (
        !sheet.name ||
        sheet.name.length > 31 ||
        /[\[\]:*?/\\]/.test(sheet.name) ||
        names.has(sheet.name)
      )
        throw new Error('工作表名称不合法');
      names.add(sheet.name);
      const columns = Math.max(...sheet.rows.map((row) => row.length));
      const range = `A1:${column(columns - 1)}${sheet.rows.length}`;
      const rows = sheet.rows
        .map((row, ri) => {
          const lines = Math.max(
            1,
            ...row.map((value, ci) =>
              String(value ?? '')
                .split('\n')
                .reduce(
                  (sum, line) =>
                    sum +
                    Math.max(
                      1,
                      Math.ceil(
                        Array.from(line).reduce(
                          (length, c) => length + (c.charCodeAt(0) < 128 ? 1 : 2),
                          0,
                        ) / (sheet.widths?.[ci] || 30),
                      ),
                    ),
                  0,
                ),
            ),
          );
          const cells = row
            .map((value, ci) => {
              const ref = column(ci) + (ri + 1);
              if (typeof value === 'number' && Number.isFinite(value))
                return `<c r="${ref}" s="${ri === 0 ? 1 : 0}"><v>${value}</v></c>`;
              if (String(value ?? '').length > 32767)
                throw new Error('单元格内容超过 Excel 限制，请缩小筛选范围或导出 CSV');
              return `<c r="${ref}" s="${ri === 0 ? 1 : 0}" t="inlineStr"><is><t xml:space="preserve">${xml(value)}</t></is></c>`;
            })
            .join('');
          return `<row r="${ri + 1}" ht="${ri === 0 ? 30 : Math.min(409, 16 * lines + 10)}" customHeight="1">${cells}</row>`;
        })
        .join('');
      files.push([
        `xl/worksheets/sheet${index + 1}.xml`,
        `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="${ns}"><dimension ref="${range}"/><sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="26"/><cols>${Array.from({ length: columns }, (_, ci) => `<col min="${ci + 1}" max="${ci + 1}" width="${sheet.widths?.[ci] || 30}" customWidth="1"/>`).join('')}</cols><sheetData>${rows}</sheetData><autoFilter ref="${range}"/><pageSetup orientation="landscape" paperSize="9"/></worksheet>`,
      ]);
    }
    files.push([
      '[Content_Types].xml',
      `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')}</Types>`,
    ]);
    files.push([
      '_rels/.rels',
      `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${relNs}/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    ]);
    files.push([
      'xl/workbook.xml',
      `<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="${ns}" xmlns:r="${relNs}"><sheets>${sheets.map((sheet, i) => `<sheet name="${xml(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`,
    ]);
    files.push([
      'xl/_rels/workbook.xml.rels',
      `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${relNs}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')}<Relationship Id="rId${sheets.length + 1}" Type="${relNs}/styles" Target="styles.xml"/></Relationships>`,
    ]);
    files.push([
      'xl/styles.xml',
      `<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="${ns}"><fonts count="2"><font><sz val="11"/><color rgb="FF334155"/><name val="Microsoft YaHei"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF025EFF"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom style="thin"><color rgb="FFE2E8F0"/></bottom><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`,
    ]);
    return zip(files);
  }

  function createPdf(report) {
    const width = 1684;
    const height = 1190;
    const margin = 64;
    const bottom = height - 66;
    const pages = [];
    let canvas;
    let ctx;
    let y;
    const font = (size, bold = false) => {
      ctx.font = `${bold ? '600 ' : ''}${size}px "Microsoft YaHei", "PingFang SC", sans-serif`;
    };
    function newPage() {
      canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('当前环境无法生成 PDF 页面');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, width, height);
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#0f172a';
      font(30, true);
      ctx.fillText(report.title, margin, 40, width - margin * 2);
      ctx.fillStyle = '#64748b';
      font(18);
      ctx.fillText(report.subtitle, margin, 84, width - margin * 2);
      ctx.strokeStyle = '#e2e8f0';
      ctx.beginPath();
      ctx.moveTo(margin, 116);
      ctx.lineTo(width - margin, 116);
      ctx.stroke();
      font(16);
      ctx.fillText(`职业能力分析初稿 · 第 ${pages.length + 1} 页`, margin, height - 40);
      pages.push(canvas);
      y = 140;
    }
    function wrap(value, maxWidth, size = 20) {
      font(size);
      const result = [];
      for (const paragraph of String(value ?? '')
        .replace(/\r/g, '')
        .split('\n')) {
        let line = '';
        for (const c of paragraph) {
          if (line && ctx.measureText(line + c).width > maxWidth) {
            result.push(line);
            line = c;
          } else line += c;
        }
        result.push(line);
      }
      return result;
    }
    function paragraph(text, size = 20, bold = false, color = '#475569') {
      const lines = wrap(text, width - margin * 2, size);
      for (const line of lines) {
        if (y + size + 10 > bottom) newPage();
        font(size, bold);
        ctx.fillStyle = color;
        ctx.fillText(line, margin, y);
        y += size + 10;
      }
      y += 10;
    }
    newPage();
    for (const section of report.sections) {
      let openingHeight = 140;
      if (section.rows?.length) {
        const totalWeight = section.widths.reduce((a, b) => a + b, 0);
        const firstRowLines = Math.max(
          ...section.rows[0].map(
            (value, ci) =>
              wrap(value, (section.widths[ci] / totalWeight) * (width - margin * 2) - 28).length,
          ),
        );
        const introHeight =
          wrap(section.title, width - margin * 2, 24).length * 34 +
          10 +
          (section.paragraphs || []).reduce(
            (sum, text) => sum + wrap(text, width - margin * 2).length * 30 + 10,
            0,
          ) +
          44;
        openingHeight = Math.min(bottom - 140, introHeight + firstRowLines * 30 + 20);
      }
      if (y + openingHeight > bottom) newPage();
      paragraph(section.title, 24, true, '#025eff');
      for (const text of section.paragraphs || []) paragraph(text);
      if (section.rows?.length) {
        const widths = section.widths.map(
          (weight) => (weight / section.widths.reduce((a, b) => a + b, 0)) * (width - margin * 2),
        );
        function header(continued = false) {
          if (continued) paragraph(section.title + '（续）', 24, true, '#025eff');
          ctx.fillStyle = '#eff6ff';
          ctx.fillRect(margin, y, width - margin * 2, 44);
          let x = margin;
          font(20, true);
          ctx.fillStyle = '#025eff';
          section.headers.forEach((text, ci) => {
            ctx.fillText(text, x + 12, y + 11);
            x += widths[ci];
          });
          y += 44;
        }
        if (y + 100 > bottom) newPage();
        header();
        for (const row of section.rows) {
          const lines = row.map((value, ci) => wrap(value, widths[ci] - 28));
          const count = Math.max(...lines.map((cell) => cell.length));
          const fullRowHeight = count * 30 + 20;
          if (fullRowHeight <= bottom - 238 && y + fullRowHeight > bottom) {
            newPage();
            header(true);
          }
          let start = 0;
          while (start < count) {
            if (y + 56 > bottom) {
              newPage();
              header(true);
            }
            const take = Math.min(count - start, Math.floor((bottom - y - 20) / 30));
            const rowHeight = take * 30 + 20;
            let x = margin;
            lines.forEach((cell, ci) => {
              ctx.strokeStyle = '#e2e8f0';
              ctx.strokeRect(x, y, widths[ci], rowHeight);
              ctx.fillStyle = '#334155';
              font(20);
              cell
                .slice(start, start + take)
                .forEach((line, index) => ctx.fillText(line, x + 12, y + 10 + index * 30));
              x += widths[ci];
            });
            y += rowHeight;
            start += take;
          }
        }
        y += 24;
      }
    }
    const objects = [];
    const text = (value) => encoder.encode(value);
    const pageIds = pages.map((_, i) => 3 + i * 3);
    objects.push(text('<< /Type /Catalog /Pages 2 0 R >>'));
    objects.push(
      text(
        `<< /Type /Pages /Count ${pages.length} /Kids [${pageIds.map((id) => id + ' 0 R').join(' ')}] >>`,
      ),
    );
    pages.forEach((page, index) => {
      const id = pageIds[index];
      const jpeg = Uint8Array.from(atob(page.toDataURL('image/jpeg', 0.94).split(',')[1]), (c) =>
        c.charCodeAt(0),
      );
      const stream = text('q 842 0 0 595 0 0 cm /PageImage Do Q');
      objects.push(
        text(
          `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /XObject << /PageImage ${id + 1} 0 R >> >> /Contents ${id + 2} 0 R >>`,
        ),
      );
      objects.push(
        join([
          text(
            `<< /Type /XObject /Subtype /Image /Width ${width} /Height ${height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`,
          ),
          jpeg,
          text('\nendstream'),
        ]),
      );
      objects.push(
        join([text(`<< /Length ${stream.length} >>\nstream\n`), stream, text('\nendstream')]),
      );
    });
    const parts = [text('%PDF-1.4\n%PGSD\n')];
    const offsets = [0];
    let offset = parts[0].length;
    objects.forEach((object, index) => {
      offsets.push(offset);
      const part = join([text(`${index + 1} 0 obj\n`), object, text('\nendobj\n')]);
      parts.push(part);
      offset += part.length;
    });
    parts.push(
      text(
        `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets
          .slice(1)
          .map((value) => String(value).padStart(10, '0') + ' 00000 n \n')
          .join(
            '',
          )}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${offset}\n%%EOF\n`,
      ),
    );
    return { bytes: join(parts), pages: pages.length };
  }
  window.CompetencyFiles = { createSpreadsheet, createPdf };
})();
