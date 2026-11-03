# session-board

A side pane for Claude Code that keeps track of one busy session. When a session runs
several subagents, background commands and timers on different topics at once, the
transcript alone makes it hard to see what is still running, what is done, and what is
waiting on you. The board groups this session's work by state and topic:

- **WAITING ON YOU**: open `AskUserQuestion` calls, numbered asks the assistant wrote in a
  reply ("1. **Venue, Friday:** ..." under a message that says it needs you; shown as
  "inferred"), and asks the assistant recorded in the ledger
- **BLOCKED** and **HELD**: items the ledger (or an optional sprint log) marks that way
- **RUNNING**: background subagents, background Bash commands, scheduled crons (with
  their next fire time)
- **DONE**: what finished, folded behind a "show done" button

A one-line band above the prompt shows the counts ("board: 3 running · 2 waiting on you")
and toggles the pane.

Press a row to open its detail: start and end times, model, summary or result, the last
lines of a background command's output, the latest text of a running subagent, and any
report file. The press also scrolls the transcript to where the item came from (its tool
call, or for a numbered ask the latest message naming it). A running subagent offers "view
this subagent's transcript".

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install session-board --marketplace mikeakamine/claude-session-board
```

Answer `y` to add the marketplace, then pick a scope (user scope is first; press Enter).
The pane opens in each new interactive session.

Or add the marketplace first, then install from it:

```
/plugin marketplace add mikeakamine/claude-session-board
/plugin install session-board@claude-session-board
```

From a shell:

```
claude plugin install session-board --marketplace mikeakamine/claude-session-board
```

In the desktop app, where `/plugin` does not run: click + next to the prompt box, then
Plugins, Add marketplace with `mikeakamine/claude-session-board`, then Add plugin.

Requires `python3` on your `PATH` (3.7 or later, standard library only).

## Use

- `/board` opens and focuses the pane. `ctrl+x tab` focuses it; the arrow keys scroll it
  when focused. Unfocused, a short pane shows what needs you first and ends with
  "+N more".
- Press a row for its detail; press it again to close it.
- **Decisions you are asked.** When the assistant writes a line like
  `> **#12 — agree/disagree:** Publish the repo.` (blockquote and bold are optional;
  `#12 - agree/disagree:` and `#12 agree/disagree:` work too), it shows under WAITING ON
  YOU as `#12`, and a press scrolls the transcript to that message. A later definition of
  the same number replaces the earlier one. Answer in the prompt box with `12 agree`,
  `1 agree, 2 disagree`, `#12 ...`, `re #12 (...): ...`, or the words of the ask plus
  `agree` ("release notes agree"); the row moves to DONE with your verdict. Plain numbered
  option lists are no longer read as asks unless the reply also says agree/disagree.
- **YOU ASKED (N).** Your own prompts (not notifications), newest first, last 50, collapsed
  behind "show your questions (N)". Press one to jump back to it in the transcript and see
  the first line of the reply it got.
- **Show/hide from the prompt (optional).** The band's toggle claims the engine action
  `app:toggleDiffNoiseFilter`, which is unbound by default. Bind a chord to it in
  `~/.claude/keybindings.json` and that chord shows or hides the pane from the prompt.
  The toggle is `ctrl+q` (works in any terminal with no settings; the band's hint reads
"ctrl+q show/hide"). Add it to `~/.claude/keybindings.json`:

```json
{ "bindings": [ { "context": "Global", "bindings": { "ctrl+q": "app:toggleDiffNoiseFilter" } } ] }
```

  Inside the diff view the engine keeps that action for itself.

## Replying and the ledger

Some things cannot be read from the transcript: a to-do you owe, a decision with a
number, a topic name. The assistant (or you) records them in a per-session ledger with
the deriver that ships in this plugin, `scripts/session_board.py`. `/board` prints its
full path in your install.

```sh
B=<plugin folder>/scripts/session_board.py        # /board prints it
python3 "$B" note --kind ask  --id 4 --text "Rollout: agree to skip the beta?" --topic rollout
python3 "$B" note --kind todo --id renew-cert --text "Renew the TLS cert" --impact 3 --why "unblocks the deploy"
python3 "$B" note --kind blocked --id cert-upload --text "Waiting for the signed cert"
python3 "$B" note --kind topic --topic offsite --match "offsite|agenda"   # topic rule (regex on titles)
python3 "$B" tag a:1b2c3d4 --topic docs                                    # pin one item's topic
python3 "$B" resolve 4 --evidence "agreed in chat"                         # an ask or to-do -> done
python3 "$B" show                     # the board as text; --json for everything
python3 "$B" detail '#4'              # one item's detail
```

`--session` defaults to `$CLAUDE_CODE_SESSION_ID`, which Claude Code sets for commands
the assistant runs, so the assistant can call these without naming the session. A
numeric `--id` shows as `#N` and replaces an inferred ask with the same number; other ids
show as `l:<id>`. A later `note` on the same id reopens or updates it. `--impact` sorts
waiting items (higher first).

To have the assistant keep the ledger, add a line like this to your `CLAUDE.md`:

> When you ask me for something you cannot infer later (a decision, a to-do), record it
> with `python3 <path>/session_board.py note --kind ask|todo --id N --text "..."`, and
> `resolve` it when it is done.

**The reply flow.** On a waiting or blocked row, press "↳ reply": the prompt box fills
with `re <id> (<title>): ` and you type your answer. Once that prompt is sent, the item
moves to RUNNING with "you replied HH:MM; Claude's turn", and scrolling goes to your
reply. A new ask on the same id after your reply puts it back with you. Typing
`re <id> ...` yourself works the same. A ledger item also has "✓ mark done", which runs
`resolve` for it. An inferred numbered ask is marked answered when a later prompt of
yours names its number ("2 agree", "#2 ok").

## Configuration

All optional, read from the environment (set them in the `env` block of
`~/.claude/settings.json` to reach the pane):

| Variable | Default | What it is |
|---|---|---|
| `SESSION_BOARD_PROJECTS` | `~/.claude/projects` | where Claude Code keeps session transcripts |
| `SESSION_BOARD_DIR` | `~/.claude/session-board` | the ledger folder (one `<session id>.jsonl` each, owner-only permissions) |
| `SESSION_BOARD_NAMES_DIR` | unset | a folder of `<session id>.json` files holding `{"session_id": ..., "session_name": ...}`; with it, the board shows names and `--session` accepts a name. Without it, the short session id is shown |
| `SESSION_BOARD_SPRINTS_DIR` | unset | turns on the sprint feature (below) |
| `SESSION_BOARD_ASK_LABEL` | `Ask\|User` | regex for the label that starts an ask in a sprint log line |
| `SESSION_BOARD_PENDING` | unset (off) | a JSON file, or a shell command printing JSON, of items that wait for you outside any session (for example an inbox of handoffs from another tool): `[{"id", "kind", "producer", "flags": [], "conflict": false, "received_at": ISO-8601, "review": "command"}]`. They show in every session as WAITING (BLOCKED when flagged or in conflict), titled "<kind> from <producer> waiting for review"; keep content out of it, names and kinds only. A failing source shows nothing |
| `SESSION_BOARD_TASKS_GLOB` | `/private/tmp/claude-*/*/{sid}/tasks` on macOS, `/tmp/claude-*/*/{sid}/tasks` elsewhere | where background command output files live |

### Sprints (optional)

If you run batches of background work from folders like `<project>/sprints/<YYYY-MM-DD-name>/`,
point `SESSION_BOARD_SPRINTS_DIR` at the `sprints` folder. When the session mentions a
path under `<project>/sprints/<id>/`, the board reads that folder: `sprint_run.json`
(`status`, `started_at`, `window_label`), `manifest.json` (a list of `{"key": "app:item",
"agent": ..., "brief": ...}`), `launched.json` (a list of keys) and the `## Running log`
section of `SPRINT.md`, one line per event:

```
- 14:01 wave 1 launched: app:one, app:two
- 14:05 app:two — DONE on branch abc1234, tests OK. Ask: nothing.
- 14:06 app:three — BLOCKED: needs a signed PDF. Ask: save the PDF to the shared folder.
- 14:08 app:four — HELD: fix lives on another branch.
```

Each key becomes a row (BLOCKED, HELD and REVERTED set its state; anything else is done),
an `Ask:` clause becomes a waiting item, and a subagent whose prompt names
`briefs/<app>--<item>.md` is folded into its sprint row. The running sprint is shown, or
with none running, the newest one the session referenced.

## Privacy

The board reads local files only: the session's transcript, the ledger, background task
output files and, if configured, sprint folders. It makes no network calls and spends
zero model tokens; the pane refreshes every 20 seconds by running the Python script. The
ledger holds the text you or the assistant write to it and stays on your machine.

## Development

```sh
claude --plugin-dir .                # run this folder in one session
claude plugin test .                 # pane tests (tests/*.test.tsx)
python3 -m unittest                  # deriver tests (tests/test_session_board.py)
claude plugin validate .
```

## License

MIT, see [LICENSE](LICENSE).
