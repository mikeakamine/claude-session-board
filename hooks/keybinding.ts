// Pure merge logic for `/board setup`: add the toggle chord to a keybindings.json text without
// touching anything else. No I/O here; register.tsx reads and writes the file.

// The engine action the band's toggle claims. Unbound by default and handled by the engine only
// inside the diff view, so outside it the person's chord for it reaches the band's Button.
export const TOGGLE_ACTION = 'app:toggleDiffNoiseFilter'
export const DEFAULT_KEY = 'ctrl+q'
const SCHEMA = 'https://www.schemastore.org/claude-code-keybindings.json'
const DOCS = 'https://code.claude.com/docs/en/keybindings'

export type Plan =
  | { status: 'created' | 'updated'; key: string; before: string | null; after: string; notes: string[] }
  | { status: 'unchanged'; key: string; notes: string[] }
  | { status: 'conflict'; key: string; existing: unknown; notes: string[] }
  | { status: 'invalid'; key: string; reason: string; notes: string[] }

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const norm = (k: string) => k.trim().toLowerCase().replace(/\s+/g, ' ')

// one key or a chord of keys ("ctrl+q", "ctrl+x s"); lower-cased
export function parseKey(raw: string): string | null {
  const k = norm(raw)

  return /^[a-z0-9+]+( [a-z0-9+]+)*$/.test(k) ? k : null
}

export function planToggleBinding(text: string | null, rawKey: string = DEFAULT_KEY): Plan {
  const key = norm(rawKey)
  const notes: string[] = []
  const invalid = (reason: string): Plan => ({ status: 'invalid', key, reason, notes })
  const fresh = (): Obj => ({ context: 'Global', bindings: { [key]: TOGGLE_ACTION } })
  const render = (o: unknown) => JSON.stringify(o, null, 2) + '\n'

  if (text === null || text.trim() === '') {
    const root = { $schema: SCHEMA, $docs: DOCS, bindings: [fresh()] }

    return { status: 'created', key, before: text, after: render(root), notes }
  }
  let root: unknown
  try {
    root = JSON.parse(text)
  } catch (err) {
    return invalid(`keybindings.json is not valid JSON (${String((err as Error).message).slice(0, 120)}); nothing written`)
  }
  if (!isObj(root)) return invalid('keybindings.json is not a JSON object; nothing written')
  if (root.bindings !== undefined && !Array.isArray(root.bindings)) {
    return invalid('"bindings" is not an array; nothing written')
  }
  const blocks = (root.bindings ?? []) as unknown[]
  if (blocks.some(b => !isObj(b) || (b.bindings !== undefined && !isObj(b.bindings)))) {
    return invalid('a bindings entry has an unexpected shape; nothing written')
  }
  const entries = blocks as Obj[]

  let firstGlobal: Obj | undefined
  for (const b of entries) {
    const inGlobal = b.context === 'Global'
    if (inGlobal && !firstGlobal) firstGlobal = b
    for (const [k, v] of Object.entries((b.bindings ?? {}) as Obj)) {
      if (norm(k) !== key) continue
      if (inGlobal) {
        if (v === TOGGLE_ACTION) return { status: 'unchanged', key, notes }
        return { status: 'conflict', key, existing: v, notes }
      }
      notes.push(`the ${String(b.context)} context also binds ${key} (to ${JSON.stringify(v)}); it wins there over the Global binding`)
    }
  }

  if (firstGlobal) {
    firstGlobal.bindings = { ...((firstGlobal.bindings ?? {}) as Obj), [key]: TOGGLE_ACTION }
  } else {
    root.bindings = [...entries, fresh()]
  }

  return { status: 'updated', key, before: text, after: render(root), notes }
}

// Line diff (LCS) of two texts, as "- old" / "+ new" lines with up to 2 unchanged lines around each
// change and "  ..." where lines are skipped. Files are tiny, so the O(n*m) table is fine.
export function previewDiff(before: string | null, after: string): string {
  const a = before === null ? [] : before.replace(/\n$/, '').split('\n')
  const b = after.replace(/\n$/, '').split('\n')
  const t: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1])
    }
  }
  const ops: { s: ' ' | '+' | '-'; l: string }[] = []
  let i = 0
  let j = 0
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { ops.push({ s: ' ', l: a[i] }); i++; j++ }
    else if (i < a.length && (j === b.length || t[i + 1][j] >= t[i][j + 1])) { ops.push({ s: '-', l: a[i] }); i++ }
    else { ops.push({ s: '+', l: b[j] }); j++ }
  }
  const near = ops.map((_, n) => ops.slice(Math.max(0, n - 2), n + 3).some(o => o.s !== ' '))
  const out: string[] = []
  let skipping = false
  ops.forEach((o, n) => {
    if (near[n]) { out.push(`${o.s} ${o.l}`); skipping = false }
    else if (!skipping) { out.push('  ...'); skipping = true }
  })

  return out.join('\n')
}

export type SetupArgs = { kind: 'ok'; key: string; apply: boolean } | { kind: 'usage'; why: string }

// `setup [<key>] [--apply]`, in any order; args is the text after "setup"
export function parseSetupArgs(rest: string): SetupArgs {
  let apply = false
  const words: string[] = []
  for (const w of rest.trim().split(/\s+/).filter(Boolean)) {
    if (w === '--apply') apply = true
    else words.push(w)
  }
  const key = words.length ? parseKey(words.join(' ')) : DEFAULT_KEY
  if (!key) return { kind: 'usage', why: `"${words.join(' ')}" is not a key (examples: ctrl+q, alt+b, ctrl+x s)` }

  return { kind: 'ok', key, apply }
}
