import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const source = await readFile(new URL('./AssistMarkdown.tsx', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React },
})
globalThis.__assistMarkdownReact = React
const code = `const React=globalThis.__assistMarkdownReact;\n${outputText}`
const { default: AssistMarkdown } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
delete globalThis.__assistMarkdownReact
const render = text => renderToStaticMarkup(React.createElement(AssistMarkdown, { text }))

test('a four-column table has aligned headers and cells inside a keyboard-scrollable region', () => {
  const html = render('#### 三套方案\n\n| 科目 | 方案A | 方案B | 方案C |\n| :--- | ---: | ---: | ---: |\n| 语文 | 6 | 7 | 8 |')
  assert.equal((html.match(/<th\b/g) ?? []).length, 4)
  assert.equal((html.match(/<td\b/g) ?? []).length, 4)
  assert.match(html, /class="assist-md-table-scroll"[^>]*role="region"[^>]*tabindex="0"/)
  assert.match(html, /<th[^>]*text-align:right/)
  assert.match(html, /<td[^>]*text-align:right[^>]*>6<\/td>/)
  assert.doesNotMatch(html, /####|\| ---:/)
})

test('escaped pipes stay within a cell, including inline bold and code', () => {
  const html = render('| 科目 | A | B | C |\n| --- | ---: | ---: | ---: |\n| **物理\\|实验** | `1\\|2` | 3 | 4 |')
  assert.equal((html.match(/<td\b/g) ?? []).length, 4)
  assert.match(html, /<strong>物理\|实验<\/strong>/)
  assert.match(html, /<code>1\|2<\/code>/)
})

test('HTML, image and link-like model output stays escaped text', () => {
  const html = render('<script>alert(1)</script>\n[点击](javascript:alert(1))\n![图](https://bad.test/a.png)')
  assert.doesNotMatch(html, /<(script|img|a)\b/i)
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
  assert.match(html, /javascript:alert\(1\)/)
})

test('wrong column counts are visible errors and never silently drop a number', () => {
  const text = '| 科目 | A | B | C |\n| --- | --- | --- | --- |\n| 语文 | 6 | 7 | 8 | 999 |'
  const html = render(text)
  assert.match(html, /role="status"/)
  assert.match(html, /表格格式/)
  assert.match(html, /999/)
  assert.doesNotMatch(html, /<table\b/)
})

test('a saved flattened heading and four-column table recovers independent blocks without changing numbers', () => {
  const text = '#### 环境 #### 三方案 | 科目 | A | B | C | | --- | --- | --- | --- | | 体育 | 2 | 2 | 2 |'
  const html = render(text)
  assert.equal((html.match(/class="assist-md-title"/g) ?? []).length, 2)
  assert.equal((html.match(/<table\b/g) ?? []).length, 1)
  assert.equal((html.match(/<td\b/g) ?? []).length, 4)
  assert.equal((html.match(/>2<\/td>/g) ?? []).length, 3)
  assert.doesNotMatch(html, /回复格式|####|\| ---/)
})

test('valid GFM tables without outside pipes and empty cells render without inventing values', () => {
  const html = render('科目 | A | B | C\n--- | ---: | ---: | ---:\n语文 | 6 |  | 8')
  assert.equal((html.match(/<td\b/g) ?? []).length, 4)
  assert.match(html, /<td[^>]*><\/td>/)
  assert.doesNotMatch(html, /表格格式/)
})

test('a final escaped pipe belongs to its cell even without an outside closing pipe', () => {
  const html = render('| 科目 | A | B | C |\n| --- | --- | --- | --- |\n| 语文 | 6 | 7 | 8\\|')
  assert.equal((html.match(/<td\b/g) ?? []).length, 4)
  assert.match(html, /<td[^>]*>8\|<\/td>/)
  assert.doesNotMatch(html, /表格格式/)
})

test('an even number of backslashes does not escape a column delimiter', () => {
  const text = '| 科目 | A | B | C |\n| --- | --- | --- | --- |\n| 路径\\\\| 6 | 7 | 8 |'
  const html = render(text)
  assert.equal((html.match(/<td\b/g) ?? []).length, 4)
  assert.match(html, /6<\/td>/)
  assert.doesNotMatch(html, /表格格式/)
})

test('the user screenshot recovers all three tables while making its arithmetic contradictions readable', () => {
  const text = '按当前课位结构（已查询）：周一到周五每天9节，共 **45 节/周**；其中第1～7节共35节必满，第8～9节共10节可排可不排。体育2+音乐1+心理1共4节，剩余41节分给语数外物化生政史8门文化课。按高考分值权重（语数外各150、物/史100、化生政各100左右赋分），主科多、赋分科均衡，给3个方案： #### 方案一（45节排满，重主科） | 科目 | 建议课时（节/周） | 说明 | | --- | --: | --- | | 语文 | 7 | 150分主科 | | 数学 | 7 | 150分主科 | | 英语 | 7 | 150分主科 | | 物理 | 5 | 首选科 | | 化学 | 4 | 再选科 | | 生物 | 3 | 再选科 | | 政治 | 3 | 再选科 | | 历史 | 3 | 再选科 | | 体育 | 2 | 你指定 | | 音乐 | 1 | 你指定 | | 心理 | 1 | 你指定 | | 合计 | 45 | 每天排满9节 | #### 方案二（39节，第8～9节部分使用） | 科目 | 建议课时（节/周） | 说明 | | --- | --: | --- | | 语文 | 6 | 150分主科 | | 数学 | 6 | 150分主科 | | 英语 | 6 | 150分主科 | | 物理 | 5 | 首选科 | | 化学 | 4 | 再选科 | | 生物 | 4 | 再选科 | | 政治 | 4 | 再选科 | | 历史 | 4 | 再选科 | | 体育 | 2 | 你指定 | | 音乐 | 1 | 你指定 | | 心理 | 1 | 你指定 | | 合计 | 43 | 第8～9节待使用2节，其余留给自习/空堂 | #### 方案三（35节，只用第1～7节） | 科目 | 建议课时（节/周） | 说明 | | --- | --: | --- | | 语文 | 5 | 150分主科 | | 数学 | 5 | 150分主科 | | 英语 | 5 | 150分主科 | | 物理 | 4 | 首选科 | | 化学 | 4 | 再选科 | | 生物 | 3 | 再选科 | | 政治 | 3 | 再选科 | | 历史 | 3 | 再选科 | | 体育 | 2 | 你指定 | | 音乐 | 1 | 你指定 | | 心理 | 1 | 你指定 | | 合计 | 36 | 超出35节，需要排1节到第8节 |'
  const html = render(text)
  assert.equal((html.match(/<table\b/g) ?? []).length, 3)
  assert.equal((html.match(/<th\b/g) ?? []).length, 9)
  assert.equal((html.match(/<td\b/g) ?? []).length, 108)
  assert.match(html, /方案二（39节/)
  assert.match(html, /方案标题为39节，表格合计为43节/)
  assert.match(html, /方案标题为35节，表格合计为36节/)
  assert.match(html, /明细相加为43，表格合计为45/)
  assert.match(html, />45<\/td>/)
  assert.match(html, />43<\/td>/)
  assert.match(html, />36<\/td>/)
  assert.doesNotMatch(html, /####|\| --:/)
})

test('flattened tables with extra cells remain visibly invalid rather than being split to guessed widths', () => {
  const text = '#### 方案 | 科目 | A | B | C | | --- | --- | --- | --- | | 语文 | 6 | 7 | 8 | 999 |'
  const html = render(text)
  assert.match(html, /role="status"/)
  assert.match(html, /回复格式|表格格式/)
  assert.match(html, /999/)
  assert.doesNotMatch(html, /<table\b/)
})

test('layout recovery respects escaped pipes and leaves literal inline code unchanged', () => {
  const html = render('说明 `保留 #### 原样` #### 方案 | 科目 | 节数 | | --- | --: | | **物理\\|实验** | 6 |')
  assert.match(html, /<code>保留 #### 原样<\/code>/)
  assert.match(html, /<strong>物理\|实验<\/strong>/)
  assert.equal((html.match(/<td\b/g) ?? []).length, 2)
})
