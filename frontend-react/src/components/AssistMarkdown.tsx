import type { ReactNode } from 'react'

/**
 * 助手气泡的轻量 markdown 渲染。
 * 只支持模型约定输出：# 标题、- 列表、1. 列表、- [x]/- [ ] 任务清单、**加粗**、`代码`、表格。
 * 不渲染链接、图片和 HTML——模型输出不可信，堵住钓鱼与注入面。
 */
const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`)/g

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

function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((cell) => /^:?-{2,}:?$/.test(cell))
}

export default function AssistMarkdown({ text }: { text: string }) {
  const lines = (text || '').replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let tasks: { done: boolean; text: string }[] | null = null
  let table: string[] | null = null

  const flush = () => {
    if (table) {
      const rows = table.map(splitRow)
      const header = rows[0]
      const body = rows.slice(1)
      if (header.length && body.length && isSeparatorRow(body[0])) {
        blocks.push(
          <table className="assist-md-table" key={`b${blocks.length}`}>
            <thead>
              <tr>{header.map((cell, i) => <th key={i}>{inline(cell, `h${blocks.length}-${i}`)}</th>)}</tr>
            </thead>
            <tbody>
              {body.slice(1).map((row, r) => (
                <tr key={r}>{row.map((cell, i) => <td key={i}>{inline(cell, `d${blocks.length}-${r}-${i}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>,
        )
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

  for (const raw of lines) {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/)
    const task = bullet?.[1].match(/^\[([xX ])\]\s+(.*)$/)
    const ordered = line.match(/^\s*\d+[.、]\s+(.*)$/)
    const heading = line.match(/^#{1,4}\s+(.*)$/)
    if (/^\s*\|.*\|\s*$/.test(line) && !bullet && !ordered && !heading) {
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
