export type BoardItem = {
  id: string
  kind: string
  state: 'running' | 'waiting' | 'blocked' | 'held' | 'done' | 'asked'
  topic: string
  title: string
  started?: number | null
  ended?: number | null
  next_fire?: number | null
  inferred?: boolean
  /** A decision once answered: agree | disagree | answered. */
  verdict?: string | null
  agent_id?: string
  /** Agent rows: the model, as the call named it, else the agent definition, else "inherits"; absent when unknown. */
  model?: string | null
  /** Agent rows: the effort from the agent definition (or the call); absent when unknown. */
  effort?: string | null
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
      showAsked: Shaped<boolean>
    }
  }
}
