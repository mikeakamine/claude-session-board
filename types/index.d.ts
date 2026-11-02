export type BoardItem = {
  id: string
  kind: string
  state: 'running' | 'waiting' | 'blocked' | 'held' | 'done'
  topic: string
  title: string
  started?: number | null
  ended?: number | null
  next_fire?: number | null
  inferred?: boolean
  agent_id?: string
  /** Where a press scrolls the transcript: a tool_use_id or a message uuid. */
  anchor?: string | null
  /** The same message's other id (API message id), tried when `anchor` is refused. */
  anchor_alt?: string | null
}

export type Board = {
  session: string
  generated_at: number
  counts: Record<string, number>
  sprints: { id: string; status?: string; launched: number; queued: number }[]
  items: BoardItem[]
  error?: string
}

export type Detail = { id: string; lines: string[] }

declare module 'claude-code' {
  interface PluginState {
    'session-board': {
      board: Shaped<Board | null>
      open: Shaped<string | null>
      detail: Shaped<Detail | null>
      showDone: Shaped<boolean>
    }
  }
}
