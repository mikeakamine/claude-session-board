import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'session-board',
  component: 'Pane',
  requestId: 'session-board',
  props: {
    title: 'Session board',
    isFocused: false,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const BOARD = {
  session: 'claude-t1',
  generated_at: 1793480000,
  counts: { running: 1, waiting: 1, blocked: 0, held: 0, done: 1 },
  sprints: [{ id: '2026-10-31-test', status: 'running', launched: 3, queued: 4 }],
  items: [
    { id: 'c:cron1', kind: 'cron', state: 'running', topic: 'offsite', title: 'Offsite agenda prep',
      started: 1793479000, next_fire: 1793487240 },
    { id: '#2', kind: 'ask', state: 'waiting', topic: 'rollout', title: 'Rollout: agree?', inferred: true },
    { id: 's:app:two', kind: 'sprint-item', state: 'done', topic: 'sprint', title: 'app:two', ended: 1793479500 },
  ],
}

test('the pane groups items by state and opens a detail on press', async ($, on) => {
  const calls: string[][] = []
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('process.run', (_, e) => {
    calls.push([...e.argv])
    const isDetail = e.argv.includes('detail')
    const stdout = isDetail
      ? JSON.stringify({ lines: ['c:cron1  [running]  Offsite agenda prep', 'fires 15:54'] })
      : JSON.stringify(BOARD)

    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /RUNNING \(1\)/ }))?.text).toBe('RUNNING (1)')
  expect(await ui.find({ type: 'Text', text: /WAITING ON YOU \(1\)/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Offsite agenda prep/ })).toBeTruthy()
  // done is collapsed behind a button
  expect(await ui.find({ type: 'Button', text: /show done \(1\)/ })).toBeTruthy()

  await $.ui.press({ plugin: 'session-board', key: 'c:cron1' })
  expect(await ui.find({ type: 'Text', text: /fires 15:54/ })).toBeTruthy()
  expect(calls.some(a => a.includes('detail') && a.includes('c:cron1'))).toBe(true)
  // the deriver runs from the plugin's own folder
  expect(calls.every(a => String(a[4]).endsWith('/scripts/session_board.py'))).toBe(true)
  await ui.unmount()
})

test('a failing deriver shows its error instead of a stale board', async ($, on) => {
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 3, stdout: '', stderr: 'session_board.py not found', isStdoutTruncated: false, isStderrTruncated: false } }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /not found/ })).toBeTruthy()
  await ui.unmount()
})

test('a short inline pane shows what waits on you first, then "+N more"', async ($, on) => {
  const many = {
    ...BOARD,
    counts: { running: 3, waiting: 2, blocked: 0, held: 0, done: 1 },
    items: [
      ...['a', 'b', 'c'].map(x => ({ id: `t:${x}`, kind: 'agent', state: 'running', topic: 'build',
        title: `Agent ${x}`, started: 1793479000 })),
      { id: '#5', kind: 'ask', state: 'waiting', topic: 'cert', title: 'Cert renewal needs your sign-off' },
      { id: '#6', kind: 'ask', state: 'waiting', topic: 'rollout', title: 'Beta rollout date' },
      BOARD.items[2],
    ],
  }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(many), stderr: '',
    isStdoutTruncated: false, isStderrTruncated: false } }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({
    ...PANE, surface: 'terminal',
    props: { ...PANE.props, placement: 'inline', scroll: { offset: 0, bodyRows: 6 } },
  })
  expect(await ui.find({ type: 'Text', text: /2 waiting on you/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /updated|stale/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /WAITING ON YOU \(2\)/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Cert renewal/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Beta rollout/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Agent c/ })).toBeFalsy()
  // 6 rows: header, label, 2 asks, 1 reserved; hidden = 3 running + 1 done items
  expect(await ui.find({ type: 'Text', text: /\+4 more/ })).toBeTruthy()
})

test('after /clear or a resume the pane follows the new session id', async ($, on) => {
  const calls: string[][] = []
  let sid = 'sid-old'
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: sid }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', (_, e) => {
    calls.push([...e.argv])
    return { value: { exitCode: 0, stdout: JSON.stringify(BOARD), stderr: '',
      isStdoutTruncated: false, isStderrTruncated: false } }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await new Promise(r => setTimeout(r, 20)) // let the start's own refresh finish
  expect(calls[0].includes('sid-old')).toBe(true)
  sid = 'sid-new'
  await $.command.run({ command: 'board', args: '' })
  expect(calls.some(a => a.includes('sid-new'))).toBe(true)
})

test('an opened row wraps its detail lines even when the pane is not focused', async ($, on) => {
  const long = 'detail '.repeat(30).trim()
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.scroll', () => ({ value: {} }))
  on('process.run', (_, e) => {
    const isDetail = e.argv.includes('detail')
    const stdout = isDetail ? JSON.stringify({ lines: [long] }) : JSON.stringify(BOARD)
    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal',
    props: { ...PANE.props, isFocused: false, bodyColumns: 60, scroll: { offset: 0, bodyRows: 30 } } })
  await $.ui.press({ plugin: 'session-board', key: '#2' })
  const t = await ui.find({ type: 'Text', text: /detail detail/ })
  expect(t).toBeTruthy()
  expect((t as any).props.wrap).toBe('wrap')
  await ui.unmount()
})

const ASKED = [
  { id: 'p:aaaa1111', kind: 'question', state: 'asked', topic: 'asked', title: 'what is blocked?',
    started: 1793479900 },
  { id: 'p:bbbb2222', kind: 'question', state: 'asked', topic: 'asked', title: 'is the reply button working?',
    started: 1793479800 },
]

test('YOU ASKED is collapsed behind a button, between the asks and the running section', async ($, on) => {
  const boardJson = { ...BOARD, counts: { ...BOARD.counts, asked: 2 },
    items: [...BOARD.items, ...ASKED, { id: '#9', kind: 'ask', state: 'done', topic: 'x',
      title: 'Use option 1', verdict: 'agree' }] }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.scroll', () => ({ value: {} }))
  on('process.run', (_, e) => ({ value: { exitCode: 0, stderr: '',
    stdout: e.argv.includes('detail') ? JSON.stringify({ lines: ['p:aaaa1111  [asked]  what is blocked?', 'you asked:', "Claude's reply began: two agents"] }) : JSON.stringify(boardJson),
    isStdoutTruncated: false, isStderrTruncated: false } }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /YOU ASKED \(2\)/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /show your questions \(2\)/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /what is blocked/ })).toBeFalsy()
  expect(await ui.find({ type: 'Button', text: /Use option 1/ })).toBeFalsy()   // done is collapsed too
  await $.ui.press({ plugin: 'session-board', key: 'show-asked' })
  expect(await ui.find({ type: 'Button', text: /what is blocked/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /hide your questions/ })).toBeTruthy()
  // a press opens the prompt's detail (the harness has no ui.scroll, so the rows here carry no anchor)
  await $.ui.press({ plugin: 'session-board', key: 'p:aaaa1111' })
  expect(await ui.find({ type: 'Text', text: /Claude's reply began/ })).toBeTruthy()
  await ui.unmount()
})

test('an answered decision shows its #N and verdict', async ($, on) => {
  const boardJson = { ...BOARD, items: [{ id: '#12', kind: 'ask', state: 'done', topic: 'x',
    title: 'Publish the repo', verdict: 'agree', ended: 1793479500 }] }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.scroll', () => ({ value: {} }))
  on('process.run', (_, e) => ({ value: { exitCode: 0, stderr: '',
    stdout: e.argv.includes('detail') ? JSON.stringify({ lines: ['x'] }) : JSON.stringify(boardJson),
    isStdoutTruncated: false, isStderrTruncated: false } }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await $.ui.press({ plugin: 'session-board', key: 'show-done' })
  expect(await ui.find({ type: 'Button', text: /#12 Publish the repo → agree/ })).toBeTruthy()
  await ui.unmount()
})

test('YOU ASKED never displaces a waiting item in a short pane', async ($, on) => {
  const boardJson = { ...BOARD, counts: { running: 1, waiting: 2, blocked: 0, held: 0, done: 1, asked: 2 },
    items: [
      { id: '#5', kind: 'ask', state: 'waiting', topic: 'cert', title: 'Cert renewal needs your sign-off' },
      { id: '#6', kind: 'ask', state: 'waiting', topic: 'rollout', title: 'Beta rollout date' },
      ...ASKED, BOARD.items[0], BOARD.items[2]] }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.scroll', () => ({ value: {} }))
  on('process.run', (_, e) => ({ value: { exitCode: 0, stderr: '',
    stdout: e.argv.includes('detail') ? JSON.stringify({ lines: ['x'] }) : JSON.stringify(boardJson),
    isStdoutTruncated: false, isStderrTruncated: false } }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({
    ...PANE, surface: 'terminal',
    props: { ...PANE.props, placement: 'inline', scroll: { offset: 0, bodyRows: 6 } },
  })
  expect(await ui.find({ type: 'Button', text: /Cert renewal/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Beta rollout/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /what is blocked/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /\+\d+ more/ })).toBeTruthy()
  await ui.unmount()
})

test('an expanded YOU ASKED shows its newest rows only in an unfocused pane', async ($, on) => {
  const boardJson = { ...BOARD, counts: { ...BOARD.counts, asked: 12 },
    items: [BOARD.items[0], ...Array.from({ length: 12 }, (_, n) => ({ id: `p:q${n}`, kind: 'question',
      state: 'asked', topic: 'asked', title: `question number ${n}`, started: 1793479000 - n }))] }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(boardJson), stderr: '',
    isStdoutTruncated: false, isStderrTruncated: false } }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await $.ui.press({ plugin: 'session-board', key: 'show-asked' })
  expect(await ui.find({ type: 'Button', text: /question number 7/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /question number 8/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /\+4 more/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Offsite agenda prep/ })).toBeTruthy()
  await ui.unmount()
})

test('agent rows show model/effort after the title; unknown parts are left out', async ($, on) => {
  const boardJson = { ...BOARD, counts: { running: 2, waiting: 0, blocked: 0, held: 0, done: 0 },
    items: [
      { id: 'a:aaa', kind: 'agent', state: 'running', topic: 'build', title: 'Agent a', model: 'sonnet', effort: 'medium', started: 1793479000 },
      { id: 'a:bbb', kind: 'agent', state: 'running', topic: 'build', title: 'Agent b', model: 'inherits', started: 1793479000 },
      { id: 'b:ccc', kind: 'bash', state: 'running', topic: 'build', title: 'Bash c', model: 'x', started: 1793479000 },
    ] }
  on('command.register', () => ({ value: { command: 'board' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('clock.every', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(boardJson), stderr: '',
    isStdoutTruncated: false, isStderrTruncated: false } }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Button', text: /Agent a · sonnet\/medium/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Agent b · inherits$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /Bash c · / })).toBeFalsy()
  await ui.unmount()
})
