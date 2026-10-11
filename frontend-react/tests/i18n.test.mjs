import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { resolveLocale, readLocale, persistLocale } from '../src/i18n/locale.ts'

test('resolves regional languages and falls back to simplified Chinese', () => {
  for (const value of ['zh-TW', 'zh-HK', 'zh-Hant', 'zh-Hant-HK']) assert.equal(resolveLocale(value), 'zh-TW')
  for (const value of ['zh', 'zh-CN', 'zh-SG', 'zh-Hans']) assert.equal(resolveLocale(value), 'zh-CN')
  for (const value of ['en', 'en-US', 'en-GB']) assert.equal(resolveLocale(value), 'en-US')
  assert.equal(resolveLocale('ja-JP'), undefined)
  assert.equal(readLocale(null, ['ja-JP']), 'zh-CN')
})

test('saved choice wins; unavailable or corrupt storage uses browser preferences', () => {
  assert.equal(readLocale({ getItem: () => 'en-US' }, ['zh-CN']), 'en-US')
  assert.equal(readLocale({ getItem: () => 'invalid' }, ['ja', 'zh-HK']), 'zh-TW')
  assert.equal(readLocale({ getItem: () => { throw new Error('blocked') } }, ['en-GB']), 'en-US')
  assert.doesNotThrow(() => persistLocale({ setItem: () => { throw new Error('blocked') } }, 'en-US'))
})

test('all bundled catalogs cover the same keys and preserve interpolation variables', () => {
  const catalog = locale => JSON.parse(fs.readFileSync(new URL(`../src/i18n/locales/${locale}.json`, import.meta.url), 'utf8'))
  const zh = catalog('zh-CN')
  const en = catalog('en-US')
  const tw = catalog('zh-TW')
  const placeholders = text => [...text.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)].map(match => match[1]).sort()
  assert(Object.keys(zh).length > 100)
  for (const other of [en, tw]) {
    assert.deepEqual(Object.keys(other).sort(), Object.keys(zh).sort())
    for (const key of Object.keys(zh)) {
      assert(other[key].trim(), key)
      assert.deepEqual(placeholders(other[key]), placeholders(zh[key]), key)
    }
  }
  assert.equal(en['进入工作台'], 'Open workspace')
  assert.equal(tw['学生选科'], '學生選科')
})
