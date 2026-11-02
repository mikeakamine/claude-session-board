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
