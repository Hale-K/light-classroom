import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

// Read-only inventory: exclude comments/types, retain locations for manual migration.
const root = path.resolve(import.meta.dirname, '../src')
const entries = new Map()
function scan(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name)
    if (entry.isDirectory()) { if (entry.name !== 'i18n') scan(file); continue }
    if (!/\.(ts|tsx)$/.test(file) || /\.test\./.test(file)) continue
    const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true)
    function visit(node) {
      if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isJsxText(node)) && /[\p{Script=Han}]/u.test(node.text)) {
        const text = node.text.trim()
        const locations = entries.get(text) || []
        locations.push(`${path.relative(root, file).replaceAll('\\', '/')}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}`)
        entries.set(text, locations)
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
}
scan(root)
console.log(JSON.stringify(Object.fromEntries([...entries].sort(([a], [b]) => a.localeCompare(b))), null, 2))
