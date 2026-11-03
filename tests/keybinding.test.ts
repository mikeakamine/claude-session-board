import { expect, test } from 'claude-code/testing'

import { parseSetupArgs, planToggleBinding, previewDiff } from '../hooks/keybinding'

const ACTION = 'app:toggleDiffNoiseFilter'
const parse = (p: { status: string; after?: string }) => JSON.parse(p.after as string)

test('no file: creates schema, docs and a Global block with ctrl+q', () => {
  const p = planToggleBinding(null)
  expect(p.status).toBe('created')
  const j = parse(p)
  expect(j.$schema).toContain('claude-code-keybindings')
  expect(j.$docs).toContain('keybindings')
  expect(j.bindings).toEqual([{ context: 'Global', bindings: { 'ctrl+q': ACTION } }])
})

test('file without a Global context: appends one, keeps the rest and the extra fields', () => {
  const src = JSON.stringify({ $schema: 'S', $docs: 'D', extra: 1,
    bindings: [{ context: 'Chat', bindings: { 'shift+enter': null } }] })
  const p = planToggleBinding(src)
  expect(p.status).toBe('updated')
  const j = parse(p)
  expect(j.$schema).toBe('S')
  expect(j.$docs).toBe('D')
  expect(j.extra).toBe(1)
  expect(j.bindings[0]).toEqual({ context: 'Chat', bindings: { 'shift+enter': null } })
  expect(j.bindings[1]).toEqual({ context: 'Global', bindings: { 'ctrl+q': ACTION } })
})

test('Global with other keys: adds ctrl+q beside them, other contexts untouched', () => {
  const src = JSON.stringify({ bindings: [
    { context: 'Global', bindings: { 'ctrl+x s': ACTION, 'ctrl+t': 'app:toggleTodos' } },
    { context: 'Chat', bindings: { 'ctrl+enter': null } } ] })
  const p = planToggleBinding(src)
  expect(p.status).toBe('updated')
  const j = parse(p)
  expect(j.bindings[0].bindings).toEqual({ 'ctrl+x s': ACTION, 'ctrl+t': 'app:toggleTodos', 'ctrl+q': ACTION })
  expect(j.bindings[1]).toEqual({ context: 'Chat', bindings: { 'ctrl+enter': null } })
  expect(j.bindings).toHaveLength(2)
})

test('ctrl+q already ours: unchanged, no text to write', () => {
  const src = JSON.stringify({ bindings: [{ context: 'Global', bindings: { 'Ctrl+Q': ACTION } }] })
  expect(planToggleBinding(src).status).toBe('unchanged')
})

test('ctrl+q bound to another action: conflict, reports it, offers nothing to write', () => {
  const src = JSON.stringify({ bindings: [{ context: 'Global', bindings: { 'ctrl+q': 'app:quit' } }] })
  const p = planToggleBinding(src)
  expect(p.status).toBe('conflict')
  if (p.status === 'conflict') expect(p.existing).toBe('app:quit')
  expect('after' in p).toBe(false)
  // an explicit unbind (null) is also the person's choice
  expect(planToggleBinding(JSON.stringify({ bindings: [{ context: 'Global', bindings: { 'ctrl+q': null } }] })).status)
    .toBe('conflict')
})

test('an alternative key merges where ctrl+q conflicts', () => {
  const src = JSON.stringify({ bindings: [{ context: 'Global', bindings: { 'ctrl+q': 'app:quit' } }] })
  const p = planToggleBinding(src, 'alt+b')
  expect(p.status).toBe('updated')
  expect(parse(p).bindings[0].bindings).toEqual({ 'ctrl+q': 'app:quit', 'alt+b': ACTION })
})

test('another context binding the key is noted, not changed', () => {
  const src = JSON.stringify({ bindings: [{ context: 'Chat', bindings: { 'ctrl+q': 'chat:x' } }] })
  const p = planToggleBinding(src)
  expect(p.status).toBe('updated')
  expect(p.notes.join(' ')).toContain('Chat')
})

test('malformed or oddly shaped input is refused with no text to write', () => {
  for (const src of ['{ "bindings": [', '[]', '{"bindings": {}}', '{"bindings": [1]}', '{"bindings": [{"context":"Global","bindings":[]}]}']) {
    const p = planToggleBinding(src)
    expect(p.status).toBe('invalid')
    expect('after' in p).toBe(false)
  }
})

test('the preview shows the added lines (plus the comma the previous line gains)', () => {
  const src = JSON.stringify({ bindings: [{ context: 'Global', bindings: { a: 'x' } }] }, null, 2) + '\n'
  const p = planToggleBinding(src)
  if (p.status !== 'updated') throw new Error('expected updated')
  const d = previewDiff(p.before, p.after)
  expect(d.split('\n').filter(l => l.startsWith('+ '))).toHaveLength(2)
  expect(d.split('\n').filter(l => l.startsWith('- '))).toEqual(['-         "a": "x"'])
  expect(d).toMatch(/\+ +"ctrl\+q": "app:toggleDiffNoiseFilter"/)
})

test('setup args: key and --apply in any order; junk is a usage error', () => {
  expect(parseSetupArgs('')).toEqual({ kind: 'ok', key: 'ctrl+q', apply: false })
  expect(parseSetupArgs('--apply')).toEqual({ kind: 'ok', key: 'ctrl+q', apply: true })
  expect(parseSetupArgs('Alt+B --apply')).toEqual({ kind: 'ok', key: 'alt+b', apply: true })
  expect(parseSetupArgs('--apply ctrl+x s')).toEqual({ kind: 'ok', key: 'ctrl+x s', apply: true })
  expect(parseSetupArgs('rm -rf /').kind).toBe('usage')
})

// the command end to end, with the file system and process mocked
function mocks(on: any, file: string | null, writes: Record<string, string>, ran: string[][],
  links: Record<string, string> = {}, extra: Record<string, string> = {}) {
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('env.get', () => ({ value: '/home/t' }))
  const store: Record<string, string> = { ...extra, ...(file === null ? {} : { '/home/t/.claude/keybindings.json': file }) }
  on('fs.exists', (_: any, e: any) => ({ value: e.path in store }))
  on('fs.read', (_: any, e: any) => ({ value: store[e.path] }))
  on('fs.stat', (_: any, e: any) => ({ value: { kind: 'file', size: 0, mtimeMs: 0, isLink: false,
    realPath: links[e.path] ?? e.path } }))
  on('fs.write', (_: any, e: any) => { store[e.path] = e.text; writes[e.path] = e.text; return { value: undefined } })
  on('process.run', (_: any, e: any) => {
    ran.push([...e.argv])
    if (e.argv[0] === 'mv') {
      store[e.argv[3]] = store[e.argv[2]]; delete store[e.argv[2]]
      for (const [lp, rp] of Object.entries(links)) if (rp === e.argv[3]) store[lp] = store[rp]
    }

    return { value: { exitCode: 0, stdout: '{}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return store
}

test('/board setup previews and writes nothing; --apply writes via temp+mv with a backup', async ($, on) => {
  const orig = JSON.stringify({ bindings: [{ context: 'Chat', bindings: { 'shift+enter': null } }] }, null, 2) + '\n'
  const writes: Record<string, string> = {}
  const ran: string[][] = []
  const store = mocks(on, orig, writes, ran)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const prev = await $.command.run({ command: 'board', args: 'setup' })
  expect(prev.text).toContain('+')
  expect(prev.text).toContain('--apply')
  expect(Object.keys(writes)).toHaveLength(0)

  const done = await $.command.run({ command: 'board', args: 'setup --apply' })
  expect(done.text).toContain('Written')
  const path = '/home/t/.claude/keybindings.json'
  expect(writes[`${path}.bak-board`]).toBe(orig)
  expect(Object.keys(writes).sort()).toEqual([`${path}.bak-board`, `${path}.board-tmp`])
  expect(ran.some(a => a[0] === 'mv' && a[2] === `${path}.board-tmp` && a[3] === path)).toBe(true)
  expect(JSON.parse(store[path]).bindings[1].bindings['ctrl+q']).toBe(ACTION)
})

async function refuses($: any, on: any, file: string, pattern: RegExp) {
  const writes: Record<string, string> = {}
  const ran: string[][] = []
  mocks(on, file, writes, ran)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'board', args: 'setup --apply' })
  expect(Object.keys(writes)).toHaveLength(0)
  expect(ran.some(a => a[0] === 'mv')).toBe(false)
  expect(r.text).toMatch(pattern)
}

test('/board setup --apply on a conflict writes nothing and suggests another key', async ($, on) => {
  await refuses($, on, JSON.stringify({ bindings: [{ context: 'Global', bindings: { 'ctrl+q': 'app:quit' } }] }),
    /already bound[\s\S]*\/board setup <key>/)
})

test('/board setup --apply on malformed JSON writes nothing', async ($, on) => {
  await refuses($, on, '{ nope', /not valid JSON/)
})

test('/board setup with no file creates it; already ours says so', async ($, on) => {
  const writes: Record<string, string> = {}
  mocks(on, null, writes, [])
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'board', args: 'setup --apply' })
  expect(r.text).toContain('Written')
  expect(Object.keys(writes)).toEqual(['/home/t/.claude/keybindings.json.board-tmp'])
  const again = await $.command.run({ command: 'board', args: 'setup --apply' })
  expect(again.text).toContain('nothing to do')
})

test('an existing .bak-board is kept, and a symlinked file is written through', async ($, on) => {
  const orig = JSON.stringify({ bindings: [] }, null, 2) + '\n'
  const path = '/home/t/.claude/keybindings.json'
  const writes: Record<string, string> = {}
  const ran: string[][] = []
  mocks(on, orig, writes, ran, { [path]: '/dots/kb.json' }, { [`${path}.bak-board`]: 'FIRST' })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'board', args: 'setup --apply' })
  expect(r.text).toContain('already existed and was kept')
  expect(writes[`${path}.bak-board`]).toBeUndefined()
  expect(ran.some(a => a[0] === 'mv' && a[2] === '/dots/kb.json.board-tmp' && a[3] === '/dots/kb.json')).toBe(true)
})
