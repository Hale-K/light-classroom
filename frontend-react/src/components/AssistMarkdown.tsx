import type { ReactNode } from 'react'

/**
 * 助手气泡的轻量 markdown 渲染。
 * 只支持模型约定输出：# 标题、- 列表、1. 列表、- [x]/- [ ] 任务清单、**加粗**、`代码`、表格。
 * 不渲染链接、图片和 HTML——模型输出不可信，堵住钓鱼与注入面。
 */
const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`)/g

function pipePositions(text: string): number[] {
  const positions: number[] = []
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== '|') continue
    let slashes = 0
    for (let j = i - 1; j >= 0 && text[j] === '\\'; j--) slashes++
    if (slashes % 2 === 0) positions.push(i)
  }
  return positions
}

function insideInlineCode(text: string, index: number): boolean {
  const prefix = text.slice(text.lastIndexOf('\n', index - 1) + 1, index)
  return (prefix.match(/(?<!\\)`/g) ?? []).length % 2 === 1
}

function recoverLayout(text: string): string {
  let result = (text || '').replace(/\r\n?/g, '\n')
  if (result.includes('```')) return result
  result = result.replace(/([^\n])[ \t]+(?=#{1,4}[ \t]+)/g, (match, before: string, index: number) => (
    insideInlineCode(result, index + match.length) ? match : `${before}\n\n`
  ))
  const separatorPattern = /\|[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|/
  let cursor = 0
  for (let attempt = 0; attempt < 12; attempt++) {
    const separator = separatorPattern.exec(result.slice(cursor))
    if (!separator) break
    const separatorStart = cursor + separator.index
    const separatorEnd = separatorStart + separator[0].length
    const width = pipePositions(separator[0]).length - 1
    const preceding = pipePositions(result.slice(0, separatorStart))
    cursor = separatorEnd
    if (width < 2 || preceding.length < width + 1 || insideInlineCode(result, separatorStart)) continue
    const start = preceding[preceding.length - width - 1]
    const header = result.slice(start, separatorStart).trim()
    if (header.includes('\n') || pipePositions(header).length !== width + 1) continue
    const rows = [header, separator[0]]
    let end = separatorEnd
    let invalid = false
    while (end < result.length) {
      let nextStart = end
      while (/\s/.test(result[nextStart] ?? '') && nextStart < result.length) nextStart++
      if (result[nextStart] !== '|') break
      const positions = pipePositions(result.slice(nextStart))
      if (positions.length < width + 1) {
        invalid = true
        break
      }
      const nextEnd = nextStart + positions[width] + 1
      const row = result.slice(nextStart, nextEnd)
      const tail = result.slice(nextEnd).split('\n', 1)[0].trimStart()
      // A row ending halfway through another cell is ambiguous. Recover none
      // of this table, rather than masking an extra number or missing column.
      if (row.includes('\n') || row.includes('####') || (tail && !tail.startsWith('|') && pipePositions(tail).length)) {
        invalid = true
        break
      }
      rows.push(row)
      end = nextEnd
    }
    if (invalid || rows.length < 3) continue
    const prefix = result.slice(0, start).trimEnd()
    const suffix = result.slice(end).trimStart()
    const block = rows.join('\n')
    result = `${prefix ? `${prefix}\n\n` : ''}${block}${suffix ? `\n\n${suffix}` : ''}`
    cursor = (prefix ? prefix.length + 2 : 0) + block.length
  }
  return result
}

function plainCell(cell: string): string {
  return cell.trim().replace(/^(\*\*|`)(.*)\1$/, '$2')
}

function cellNumber(cell: string): number | null {
  const match = plainCell(cell).match(/^(\d+(?:\.\d+)?)(?:\s*节(?:\/周)?)?$/)
  return match ? Number(match[1]) : null
}

function tableNumberIssues(header: string[], rows: string[][], heading: string): string[] {
  const totals = rows.filter((row) => /^(?:合计|总计|总课时|总节数)(?:[（(].*[)）])?$/.test(plainCell(row[0])))
  if (totals.length !== 1) return []
  const totalRow = totals[0]
  const details = rows.filter((row) => row !== totalRow)
  const numericColumns = header.map((_, index) => index).filter((index) => index > 0 && cellNumber(totalRow[index]) !== null)
  const issues: string[] = []
  for (const index of numericColumns) {
    const values = details.map((row) => cellNumber(row[index]))
    if (!values.length || values.some((value) => value === null) || details.some((row) => /小计|合计|总计/.test(plainCell(row[0])))) continue
    const sum = Number(values.reduce<number>((total, value) => total + (value ?? 0), 0).toFixed(8))
    const total = cellNumber(totalRow[index])!
    if (Math.abs(sum - total) > 1e-8) issues.push(`“${plainCell(header[index])}”明细相加为${sum}，表格合计为${total}。`)
  }
  const titleTotal = /方案/.test(heading) ? heading.match(/[（(:：\s](\d+(?:\.\d+)?)\s*节/) : null
  if (titleTotal && numericColumns.length === 1 && /课时|节数/.test(header[numericColumns[0]])) {
    const total = cellNumber(totalRow[numericColumns[0]])!
    if (Number(titleTotal[1]) !== total) issues.push(`方案标题为${titleTotal[1]}节，表格合计为${total}节。`)
  }
  return issues
}

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE_RE).map((part, i) => {
    const key = `${keyBase}-${i}`
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>
    }
    return part
  })
}

function parseRow(line: string): { cells: string[]; delimiters: number } {
  const source = line.trim()
  const cells: string[] = []
  let cell = ''
  let delimiters = 0
  let lastDelimiter = -1
  for (let i = 0; i < source.length; i++) {
    if (source[i] !== '|') {
      cell += source[i]
      continue
    }
    let slashes = 0
    for (let j = i - 1; j >= 0 && source[j] === '\\'; j--) slashes++
    if (slashes % 2) {
      // Remove only the pipe's escaping slash; keep literal backslashes.
      cell = `${cell.slice(0, -1)}|`
    } else {
      cells.push(cell.trim())
      cell = ''
      delimiters++
      lastDelimiter = i
    }
  }
  cells.push(cell.trim())
  if (source.startsWith('|')) cells.shift()
  if (lastDelimiter === source.length - 1) cells.pop()
  return { cells, delimiters }
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((cell) => /^:?-{2,}:?$/.test(cell))
}

function isFlattenedTable(cells: string[]): boolean {
  // Two outside row pipes around a separator row on the same line prove
  // the row boundaries were flattened. Preserve the original instead of guessing.
  return cells.some((cell, i) => {
    if (cell !== '') return false
    let end = i + 1
    while (end < cells.length && /^:?-{2,}:?$/.test(cells[end])) end++
    return end - i > 2 && cells[end] === '' && end + 1 < cells.length
  })
}

function alignment(separator: string): 'left' | 'center' | 'right' | undefined {
  if (separator.endsWith(':')) return separator.startsWith(':') ? 'center' : 'right'
  return separator.startsWith(':') ? 'left' : undefined
}

export default function AssistMarkdown({ text }: { text: string }) {
  const lines = recoverLayout(text).split('\n')
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let tasks: { done: boolean; text: string }[] | null = null
  let table: string[] | null = null
  let currentHeading = ''

  const formatProblem = (message: string, raw: string) => {
    blocks.push(
      <div className="assist-md-format-problem" role="status" key={`b${blocks.length}`}>
        <p>{message}</p>
        <pre>{raw}</pre>
      </div>,
    )
  }

  const flush = () => {
    if (table) {
      const rows = table.map((line) => parseRow(line).cells)
      const header = rows[0]
      const body = rows.slice(1)
      if (header.length && body.length && isSeparatorRow(body[0])) {
        if (body.some((row) => row.length !== header.length)) {
          formatProblem('表格格式有误：各行列数不一致，以下保留原始内容供核对。', table.join('\n'))
        } else {
          const aligns = body[0].map(alignment)
          const numberIssues = tableNumberIssues(header, body.slice(1), currentHeading)
          if (numberIssues.length) {
            blocks.push(<p className="assist-md-number-warning" role="status" key={`b${blocks.length}`}>数字需要核对：{numberIssues.join(' ')}保留原数字，未自动修正。</p>)
          }
          blocks.push(
            <div className="assist-md-table-scroll" role="region" tabIndex={0} aria-label="助手数据表格" key={`b${blocks.length}`}>
              <table className="assist-md-table" style={{ minWidth: `${Math.max(288, header.length * 96)}px` }}>
                <thead>
                  <tr>{header.map((cell, i) => <th scope="col" style={{ textAlign: aligns[i] }} key={i}>{inline(cell, `h${blocks.length}-${i}`)}</th>)}</tr>
                </thead>
                <tbody>
                  {body.slice(1).map((row, r) => (
                    <tr key={r}>{row.map((cell, i) => <td style={{ textAlign: aligns[i] }} key={i}>{inline(cell, `d${blocks.length}-${r}-${i}`)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>,
          )
        }
      } else {
        // 不是规范的表头+分隔线结构，按原始行渲染，避免吞内容。
        for (const raw of table) {
          blocks.push(<p key={`b${blocks.length}`}>{inline(raw, `p${blocks.length}`)}</p>)
        }
      }
      table = null
    }
    if (list) {
      const { ordered, items } = list
      blocks.push(
        ordered ? (
          <ol key={`b${blocks.length}`}>
            {items.map((item, i) => (
              <li key={i}>{inline(item, `o${blocks.length}-${i}`)}</li>
            ))}
          </ol>
        ) : (
          <ul key={`b${blocks.length}`}>
            {items.map((item, i) => (
              <li key={i}>{inline(item, `u${blocks.length}-${i}`)}</li>
            ))}
          </ul>
        ),
      )
      list = null
    }
    if (tasks) {
      blocks.push(
        <ul className="assist-md-tasks" key={`b${blocks.length}`}>
          {tasks.map((item, i) => (
            <li key={i} className={item.done ? 'is-done' : ''}>
              {inline(item.text, `t${blocks.length}-${i}`)}
            </li>
          ))}
        </ul>,
      )
      tasks = null
    }
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
    const raw = lines[lineIndex]
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/)
    const task = bullet?.[1].match(/^\[([xX ])\]\s+(.*)$/)
    const ordered = line.match(/^\s*\d+[.、]\s+(.*)$/)
    const heading = line.match(/^#{1,4}\s+(.*)$/)
    const row = parseRow(line)
    const nextRow = parseRow(lines[lineIndex + 1] ?? '')
    const tableLine = row.delimiters > 0 && (table || /^\s*\|/.test(line) || isSeparatorRow(nextRow.cells))
    if (row.delimiters >= 6 && isFlattenedTable(row.cells)) {
      flush()
      formatProblem('回复格式有误：表格行被压平，以下保留原始内容供核对。', line)
    } else if (tableLine && !bullet && !ordered && !heading) {
      if (table) table.push(line)
      else {
        flush()
        table = [line]
      }
    } else if (bullet && task) {
      if (tasks) tasks.push({ done: task[1] !== ' ', text: task[2] })
      else {
        flush()
        tasks = [{ done: task[1] !== ' ', text: task[2] }]
      }
    } else if (bullet) {
      if (list && !list.ordered) list.items.push(bullet[1])
      else {
        flush()
        list = { ordered: false, items: [bullet[1]] }
      }
    } else if (ordered) {
      if (list && list.ordered) list.items.push(ordered[1])
      else {
        flush()
        list = { ordered: true, items: [ordered[1]] }
      }
    } else if (heading) {
      flush()
      currentHeading = heading[1]
      blocks.push(
        <p className="assist-md-title" key={`b${blocks.length}`}>
          {inline(heading[1], `h${blocks.length}`)}
        </p>,
      )
    } else if (!line.trim()) {
      flush()
    } else {
      flush()
      blocks.push(<p key={`b${blocks.length}`}>{inline(line, `p${blocks.length}`)}</p>)
    }
  }
  flush()
  return <div className="assist-md">{blocks}</div>
}
