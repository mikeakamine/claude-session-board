import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Board, BoardItem, Detail } from '../types'

// The pane beside the chat: what this session has RUNNING, WAITING ON YOU, BLOCKED,
// HELD and DONE, grouped by topic, plus YOU ASKED (your own prompts, newest first, collapsed).
// Every refresh runs scripts/session_board.py from this plugin's own folder (local files only,
// zero model tokens); pressing a row fetches that item's detail (report path,
// bounded output tail, latest subagent text) and, for a live subagent, offers its
// transcript in the main view.

const PANE = 'session-board'
const REFRESH_MS = 20000
// $1 is the deriver's path inside this plugin; the rest are its arguments
const RUNNER =
  'p="$1"; shift; ' +
    '[ -f "$p" ] && exec python3 "$p" "$@"; echo "session_board.py not found at $p" >&2; exit 3'
const deriver = ($: EngineInterface) => `${$.plugin.root}/scripts/session_board.py`
// drawn in this order: what needs you first, so a short pane still shows it.
// 'asked' (your own prompts) sits after what needs you and before the running/done sections, but is
// collapsed like done, so it costs two rows and never pushes an ask out
const VIEW_ORDER = ['waiting', 'blocked', 'held', 'asked', 'running', 'done'] as const
const LABEL: Record<string, string> = {
  running: 'RUNNING',
  waiting: 'WAITING ON YOU',
  blocked: 'BLOCKED',
  held: 'HELD',
  done: 'DONE',
  asked: 'YOU ASKED',
}
const FG = '#E8E8E8'
const FG_DIM = '#B8B8B8'
const COLOR: Record<string, string> = {
  running: 'success',
  waiting: 'warning',
  blocked: 'error',
  held: 'suggestion',
  asked: FG_DIM,
}

const board = atom({ plugin: 'session-board', key: 'board' } as const, null, { shape: 'board-1' })
const open = atom({ plugin: 'session-board', key: 'open' } as const, null, { shape: 'open-1' })
const detail = atom({ plugin: 'session-board', key: 'detail' } as const, null, { shape: 'detail-1' })
const showDone = atom({ plugin: 'session-board', key: 'showDone' } as const, false, {
  shape: 'done-1',
})
const showAsked = atom({ plugin: 'session-board', key: 'showAsked' } as const, false, {
  shape: 'asked-1',
})

const hm = (epoch?: number | null): string => {
  if (!epoch) return ''
  const d = new Date(epoch * 1000)
  const p = (n: number) => String(n).padStart(2, '0')

  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

const age = (epoch: number | null | undefined, now: number): string => {
  if (!epoch) return ''
  const s = Math.max(0, Math.round(now - epoch))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`

  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`
}

const when = (it: BoardItem, now: number): string => {
  if (it.next_fire && it.state === 'running') return `@${hm(it.next_fire)}`
  if (it.state === 'running') return age(it.started, now)

  return hm(it.ended ?? it.started)
}

let sessionId = ''
let busy = false
let ticking = false

// session.start does not fire again after a mod hot-reload, so the timer is (re)armed from any hook.
async function ensureLive($: EngineInterface) {
  if (!sessionId) sessionId = await $.session.id()
  if (ticking) return
  ticking = true
  $.clock.every(REFRESH_MS, () => refresh($))
  void refresh($)
}

function run($: EngineInterface, args: string[]) {
  return $.process.run(['sh', '-c', RUNNER, 'session_board', deriver($), ...args], { timeoutMs: 20000 })
}

async function refresh($: EngineInterface) {
  if (busy || !sessionId) return
  busy = true
  try {
    // After /clear or a resume the process goes on under a NEW session id and no session.start
    // fires, so the id is re-read on every refresh; otherwise the pane would keep showing the
    // ended session's board.
    const cur = await $.session.id()
    if (cur && cur !== sessionId) {
      sessionId = cur
      await update($, open, () => null)
      await update($, detail, () => null)
    }
    const { exitCode, stdout, stderr } = await run($, ['show', '--json', '--session', sessionId])
    if (exitCode !== 0) {
      await update($, board, () => ({
        session: sessionId.slice(0, 8),
        generated_at: Date.now() / 1000,
        counts: {},
        sprints: [],
        items: [],
        error: (stderr || `exit ${exitCode}`).slice(0, 300),
      }))
      return
    }
    const b = JSON.parse(stdout) as Board
    const slim: Board = {
      session: b.session,
      generated_at: b.generated_at,
      counts: b.counts,
      sprints: (b.sprints || []).map(s => ({
        id: s.id,
        status: s.status,
        launched: s.launched,
        queued: s.queued,
      })),
      items: b.items.map(i => ({
        id: i.id,
        kind: i.kind,
        state: i.state,
        topic: i.topic,
        title: i.title,
        started: i.started ?? null,
        ended: i.ended ?? null,
        next_fire: i.next_fire ?? null,
        inferred: !!i.inferred,
        verdict: i.verdict,
        agent_id: i.agent_id,
        anchor: i.anchor ?? null,
        anchor_alt: i.anchor_alt ?? null,
      })),
    }
    await update($, board, () => slim)
    const c = slim.counts
    $.ui.status(`board: ${c.running ?? 0} running · ${c.waiting ?? 0} waiting on you`)
  } catch (err) {
    $.ui.log(`session-board refresh failed: ${String(err)}`, { to: 'debug' })
  } finally {
    busy = false
  }
}

// A press opens the row's detail AND scrolls the main transcript to where the item came from
// (its own tool call or message; for a numbered ask, the latest reply naming its #N). The scroll
// runs first, inside the press: the engine moves a transcript row only for the person's own input.
// A row from before the last compaction is no longer in the view; the reason is shown in the detail.
// The engine action the band's toggle claims. Unbound by default and handled by the engine only
// inside the diff view, so outside it the person's chord for it reaches this Button.
const TOGGLE_ACTION = 'app:toggleDiffNoiseFilter'

async function toggleBoard($: EngineInterface) {
  const isUp = (await $.ui.panes()).some(p => p.id === PANE)
  if (isUp) await $.ui.close({ id: PANE })
  else {
    await ensureLive($)
    await $.ui.open({ id: PANE, title: 'Session board' })
  }
}

async function pressRow($: EngineInterface, it: BoardItem) {
  const opening = (await read($, open)) !== it.id
  let note: string | null = null
  if (opening && it.anchor) {
    let r = await $.ui.scroll({ to: { requestId: it.anchor }, block: 'start' })
    // a message row may be drawn under its API message id rather than its record uuid
    if (r.deny && it.anchor_alt) r = await $.ui.scroll({ to: { requestId: it.anchor_alt }, block: 'start' })
    if (r.deny) note = `(can't scroll the session there: ${r.deny}; it may be from before the last compaction)`
  }
  await toggle($, it.id)
  if (note) await update($, detail, d => (d && d.id === it.id ? { id: d.id, lines: [note as string, ...d.lines] } : d))
}

async function toggle($: EngineInterface, id: string) {
  const cur = await read($, open)
  if (cur === id) {
    await update($, open, () => null)
    return
  }
  await update($, open, () => id)
  await update($, detail, () => ({ id, lines: ['loading…'] }))
  try {
    const { exitCode, stdout, stderr } = await run($, [
      'detail',
      id,
      '--json',
      '--lines',
      '20',
      '--session',
      sessionId,
    ])
    const lines =
      exitCode === 0
        ? ((JSON.parse(stdout).lines as string[]) || []).slice(0, 45)
        : [(stderr || `exit ${exitCode}`).slice(0, 300)]
    await update($, detail, () => ({ id, lines }))
  } catch (err) {
    await update($, detail, () => ({ id, lines: [String(err)] }))
  }
}


export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    sessionId = await $.session.id()
    await ensureLive($)
    await $.command.register({
      name: 'board',
      description: 'Open the session board: running / waiting on you / held / done, by topic',
    })
    if (e.isInteractive) void $.ui.open({ id: PANE, title: 'Session board' })

    return started
  })

  on('command.run', { command: 'board' }, async $ => {
    await ensureLive($)
    await refresh($)
    await $.ui.open({ id: PANE, title: 'Session board', focus: true })

    return {
      text:
        'Session board opened (ctrl+x tab focuses it; press a row for detail). ' +
        `Ledger notes: python3 ${deriver($)} note --kind ask --id 1 --text "..."`,
    }
  })

  // A one-line band above the prompt: the board's counts, and the show/hide toggle. Its Button
  // claims the engine action TOGGLE_ACTION, so the person's chord for it (ctrl+x s or opt+s in
  // ~/.claude/keybindings.json) presses it from the prompt while the band is mounted.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    void ensureLive($)
    const c = (await read($, board))?.counts ?? {}
    const row = (
      <Button key="toggle-board" plain action={TOGGLE_ACTION} onPress={() => toggleBoard($)}>
        <Text color={FG_DIM}>
          board: {c.running ?? 0} running · {c.waiting ?? 0} waiting on you
          {e.surface === 'terminal' ? ' · opt+s show/hide' : ' · show/hide'}
        </Text>
      </Button>
    )
    // whatever else draws above the prompt (other plugins, the engine) stays, under this line
    const below = await next(e)
    return (
      <Box flexDirection="column">
        {row}
        {below}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    void ensureLive($)
    const b = await read($, board)
    const openId = await read($, open)
    const d = await read($, detail)
    const done = await read($, showDone)
    const asked = await read($, showAsked)

    if (!b) return <Text dimColor>Reading this session…</Text>
    if (b.error) return <Text color="error">session board: {b.error}</Text>

    const now = b.generated_at
    const c = b.counts
    const stale = Date.now() / 1000 - now > 90
    // The pane gets a fixed number of rows (`scroll.bodyRows`); inline above the prompt that is a
    // handful, and the terminal keeps the END of a taller tree in view, so a tall tree would show
    // only its "updated" footer. Unfocused, the tree is cut to fit, most important first:
    // counts + freshness, then waiting on you, blocked, held, running, done; one row per item.
    // Focused (ctrl+x tab), everything is drawn and the arrows scroll it.
    const focused = e.props.isFocused
    const budget = focused ? Number.MAX_SAFE_INTEGER : Math.max(2, e.props.scroll?.bodyRows ?? 40)
    const rowsOut: unknown[] = []
    let used = 0
    let hidden = 0
    // `item` is true for a board item's own row: "+N more" counts items, not labels or detail lines
    // `cost` is the rows a wrapped line takes, so an opened row's full text still fits the budget
    const cols = Math.max(20, e.props.bodyColumns ?? 80)
    const rowsFor = (text: string): number => Math.max(1, Math.ceil(text.length / cols))
    const add = (el: unknown, item = false, cost = 1): boolean => {
      if (used + cost > budget - 1) {
        if (item) hidden += 1
        return false
      }
      rowsOut.push(el)
      used += cost
      return true
    }

    add(
      <Box key="head" flexDirection="row" gap={1}>
        <Text bold color={FG} wrap="truncate-end">
          {c.waiting ?? 0} waiting on you · {(c.blocked ?? 0) + (c.held ?? 0)} held/blocked ·{' '}
          {c.running ?? 0} running · {c.done ?? 0} done
        </Text>
        <Button key="refresh" plain onPress={() => refresh($)}>
          <Text color={stale ? 'warning' : FG_DIM}>
            · {stale ? `stale ${hm(now)}, refresh` : `updated ${hm(now)}`}
          </Text>
        </Button>
      </Box>,
    )
    for (const state of VIEW_ORDER) {
      // sprint lines sit below what needs you, so a short pane never trades an ask for one
      if (state === 'running') {
      for (const s of b.sprints) {
        add(
          <Text key={`sprint-${s.id}`} color={FG_DIM} wrap="truncate-end">
            sprint {s.id} {s.status ?? ''} · launched {s.launched}/{s.queued}
          </Text>,
        )
      }
      }
      const rows = b.items.filter(i => i.state === state)
      if (rows.length === 0) continue
      if (!add(
        <Text key={`label-${state}`} bold color={COLOR[state]}>
          {LABEL[state]} ({rows.length})
        </Text>,
      )) {
        hidden += rows.length
        continue
      }
      if ((state === 'done' && !done) || (state === 'asked' && !asked)) {
        const isAsked = state === 'asked'
        if (!add(
          <Button
            key={`show-${state}`}
            plain
            onPress={() => (isAsked ? update($, showAsked, () => true) : update($, showDone, () => true))}
          >
            <Text color={FG_DIM}>
              {isAsked ? `show your questions (${rows.length})` : `show done (${rows.length})`}
            </Text>
          </Button>,
        )) hidden += rows.length
        continue
      }
      // an expanded YOU ASKED shows its newest few in an unfocused pane, so it never crowds out running/done
      const shown = state === 'asked' && !focused ? rows.slice(0, 8) : rows
      hidden += rows.length - shown.length
      for (const it of shown) {
        const isOpen = openId === it.id && d && d.id === it.id
        // an opened row shows its whole title, wrapped; closed rows stay one line each
        // a decision shows its #N and, once answered, the verdict
        const label = `${it.id.startsWith('#') && !it.title.startsWith(it.id) ? it.id + ' ' : ''}${it.title}${
          it.id.startsWith('#') && it.verdict ? ` → ${it.verdict}` : ''
        }`
        const head = `▾ ${it.topic.padEnd(10).slice(0, 10)} ${when(it, now).padStart(6)} ${label}`
        add(
          <Button key={it.id} plain onPress={() => pressRow($, it)}>
            <Text
              color={state === 'done' || state === 'asked' ? FG_DIM : FG}
              wrap={isOpen ? 'wrap' : 'truncate-end'}
            >
              {openId === it.id ? '▾' : '▸'} {it.topic.padEnd(10).slice(0, 10)}{' '}
              {when(it, now).padStart(6)} {label}
              {it.inferred ? ' (inferred)' : ''}
            </Text>
          </Button>,
          true,
          isOpen ? rowsFor(head) : 1,
        )
        if (!isOpen || !d) continue
        for (const [n, l] of d.lines.entries()) {
          add(
            <Text key={`d-${it.id}-${n}`} color={FG_DIM} wrap="wrap">
              {'   '}
              {l}
            </Text>,
            false,
            rowsFor('   ' + l),
          )
        }
        if (state === 'waiting' || state === 'blocked') {
          add(
            <Box key={`act-${it.id}`} flexDirection="row" gap={2}>
              <Button
                key={`reply-${it.id}`}
                plain
                onPress={async () => {
                  await $.prompt.fill({ text: `re ${it.id} (${it.title.slice(0, 60)}): ` })
                  $.ui.toast('reply started in the prompt box — type your answer, press Enter')
                }}
              >
                <Text color={FG}>{'   '}↳ reply</Text>
              </Button>
              {it.id.startsWith('l:') && (
                <Button
                  key={`done-${it.id}`}
                  plain
                  onPress={async () => {
                    await run($, ['resolve', it.id.slice(2), '--session', sessionId,
                      '--evidence', 'marked done on the board'])
                    await update($, open, () => null)
                    await refresh($)
                  }}
                >
                  <Text color={FG}>✓ mark done</Text>
                </Button>
              )}
            </Box>,
          )
        }
        if (it.agent_id && state === 'running') {
          add(
            <Button
              key={`view-${it.id}`}
              plain
              onPress={async () => {
                const r = await $.ui.view({ agentId: it.agent_id as string })
                if (r.deny) $.ui.toast(`cannot open that transcript: ${r.deny}`)
              }}
            >
              <Text color={FG}>{'   '}view this subagent's transcript</Text>
            </Button>,
          )
        }
      }
      if ((state === 'done' && done) || (state === 'asked' && asked)) {
        const isAsked = state === 'asked'
        add(
          <Button
            key={`hide-${state}`}
            plain
            onPress={() => (isAsked ? update($, showAsked, () => false) : update($, showDone, () => false))}
          >
            <Text color={FG_DIM}>{isAsked ? 'hide your questions' : 'hide done'}</Text>
          </Button>,
        )
      }
    }
    if (hidden > 0) {
      rowsOut.push(
        <Text key="more" color={FG_DIM} wrap="truncate-end">
          +{hidden} more · ctrl+x tab to focus, arrows to scroll
        </Text>,
      )
    }

    return <Box flexDirection="column">{rowsOut}</Box>
  })
}
