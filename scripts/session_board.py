#!/usr/bin/env python3
"""session_board -- a side summary of ONE orchestrated Claude Code session.

One long Claude Code session that runs several subagents, background commands and timers on
several topics at once is hard to follow from the transcript alone. This groups that session's
work by STATE (running / waiting on you / blocked / held / done) and TOPIC, with a pointer to
the evidence for each item.

Zero model tokens. Derived from local files only, re-read on every call:
  * the session transcript  <transcripts dir>/*/<sid>.jsonl  (default ~/.claude/projects)
      - Agent tool calls (+ their result: agentId, async) and SendMessage resumes
      - background Bash (run_in_background, or a foreground call that timed out to the
        background: backgroundTaskId) and TaskStop
      - <task-notification> events (task-id, status, summary, result)
      - CronCreate / CronDelete (one-shot crons whose fire time passed count as done)
      - AskUserQuestion calls with no answer yet
      - numbered asks in the assistant's own replies ("1. **Venue, Friday:** ...") under a
        message that says it needs you -- labelled "inferred"; a later prompt of yours
        that names the number marks it answered
  * optional: sprint folders the transcript references (<sprints dir>/<id>/): manifest.json,
    launched.json and the SPRINT.md running log ("HH:MM key -- STATE: ... Ask: ..."); off
    unless $SESSION_BOARD_SPRINTS_DIR names the folder that holds them
  * the task output dir <tmp>/claude-*/*/<sid>/tasks/ (detail tails only)
  * an explicit per-session ledger the assistant appends to, for what cannot be inferred:
      <state dir>/<sid>.jsonl   (default ~/.claude/session-board, owner-only permissions)

PRIVACY: the board quotes transcript text (task descriptions, ask titles). It is printed, or
written to the ledger in the state dir only. Nothing here touches the network.

Configuration (environment variables, all optional):
    SESSION_BOARD_PROJECTS     transcripts dir                 (default ~/.claude/projects)
    SESSION_BOARD_DIR          ledger / state dir              (default ~/.claude/session-board)
    SESSION_BOARD_SPRINTS_DIR  folder of sprint folders        (default: unset, sprints off)
    SESSION_BOARD_NAMES_DIR    folder of <sid>.json files holding {"session_id", "session_name"}
                               for friendly names              (default: unset, short ids)
    SESSION_BOARD_TASKS_GLOB   background task output folders, "{sid}" for the session id
    SESSION_BOARD_ASK_LABEL    regex for the label that starts an ask in a sprint log line
                               (default "Ask|User")

CLI
    session_board.py show   [--session S] [--json]           # S = uuid, uuid prefix or name
    session_board.py detail ITEM [--session S] [--lines 30] [--json]
    session_board.py note   --kind ask|todo|done|held|blocked|running|topic --text "..."
                            [--id ID] [--topic T] [--match REGEX] [--evidence E] [--session S]
    session_board.py resolve ID [--evidence E] [--session S]  # an ask/todo -> done
    session_board.py tag ITEM --topic T [--session S]         # pin a derived item's topic
--session defaults to $CLAUDE_CODE_SESSION_ID.
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone


def _env_path(name, default=None):
    v = os.environ.get(name)
    return os.path.expanduser(v) if v else default


HOME = os.path.expanduser("~")
PROJECTS = _env_path("SESSION_BOARD_PROJECTS", os.path.join(HOME, ".claude", "projects"))
BOARD_DIR = _env_path("SESSION_BOARD_DIR", os.path.join(HOME, ".claude", "session-board"))
SPRINTS_DIR = _env_path("SESSION_BOARD_SPRINTS_DIR")      # None: the sprint feature is off
NAMES_DIR = _env_path("SESSION_BOARD_NAMES_DIR")          # None: sessions show their short id
TASK_GLOB = os.environ.get("SESSION_BOARD_TASKS_GLOB") or (
    "/private/tmp/claude-*/*/{sid}/tasks" if sys.platform == "darwin" else "/tmp/claude-*/*/{sid}/tasks")
ASK_LABEL = os.environ.get("SESSION_BOARD_ASK_LABEL") or "Ask|User"

STATES = ("running", "waiting", "blocked", "held", "done")
STATE_LABEL = {"running": "RUNNING", "waiting": "WAITING ON YOU", "blocked": "BLOCKED",
               "held": "HELD", "done": "DONE"}
LEDGER_KINDS = ("ask", "todo", "done", "held", "blocked", "running", "topic")
KIND_STATE = {"ask": "waiting", "todo": "waiting", "done": "done", "held": "held",
              "blocked": "blocked", "running": "running"}
TITLE_MAX = 110
SUMMARY_MAX = 400
NOTIF_RE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
TAG_RE = re.compile(r"<([a-z][a-z-]*)>(.*?)</\1>", re.S)
SPRINT_ID = r"([0-9]{4}-[0-9]{2}-[0-9]{2}[\w.-]*)"
NEEDS_YOU_RE = re.compile(r"need(s)? you|your call|decision|agree|waiting on you|"
                          r"blocking on you|only you|yours to", re.I)
ASK_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?#?(\d{1,2})[.)]?\s*(?:\*\*)?\s*"
                         r"\*\*([^*]{2,80}?)[:.]?\*\*[:.]?\s*(.*)$")
LOG_LINE_RE = re.compile(r"^-\s+(\d{1,2}:\d{2})\s+(.*)$")
KEY_RE = r"[a-z][\w-]*:[\w.-]+"


def sprint_ref_re(sprints_dir):
    """How the transcript names a sprint folder: the sprints dir's last two path parts
    ("<project>/sprints/<id>"), so an absolute, ~ or relative spelling all match."""
    if not sprints_dir:
        return None
    tail = "/".join(os.path.normpath(sprints_dir).split(os.sep)[-2:])
    return re.compile(re.escape(tail) + "/" + SPRINT_ID)


# ---------------------------------------------------------------- helpers
def _now():
    return time.time()


def _iso_to_epoch(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _clip(text, n=TITLE_MAX):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _local_hm(epoch):
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch).strftime("%H:%M")


def _age(epoch, now):
    if epoch is None:
        return ""
    s = max(0, int(now - epoch))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}"


def _read_json(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- session lookup
def resolve_session(arg):
    """uuid, uuid prefix, or session name (from NAMES_DIR/<sid>.json) -> (sid, transcript path)."""
    arg = (arg or os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if not arg:
        raise SystemExit("session_board: no --session and no $CLAUDE_CODE_SESSION_ID")
    paths = glob.glob(os.path.join(PROJECTS, "*", f"{arg}*.jsonl"))
    paths = [p for p in paths if os.path.basename(p).count("-") >= 4]
    if not paths and NAMES_DIR:
        for f in sorted(glob.glob(os.path.join(NAMES_DIR, "*.json")), key=os.path.getmtime,
                        reverse=True):
            try:
                d = _read_json(f)
            except (OSError, ValueError):
                continue
            if d.get("session_name") == arg and d.get("session_id"):
                paths = glob.glob(os.path.join(PROJECTS, "*", f"{d['session_id']}.jsonl"))
                if paths:
                    break
    if not paths:
        raise SystemExit(f"session_board: no transcript for session {arg!r}")
    path = max(paths, key=os.path.getmtime)
    return os.path.basename(path)[:-6], path


def session_name(sid):
    """A friendly name from the optional names registry, else the short session id."""
    if not NAMES_DIR:
        return sid[:8]
    try:
        return _read_json(os.path.join(NAMES_DIR, f"{sid}.json")).get("session_name") or sid[:8]
    except (OSError, ValueError):
        return sid[:8]


# ---------------------------------------------------------------- ledger
def ledger_path(sid):
    return os.path.join(BOARD_DIR, f"{sid}.jsonl")


def read_ledger(sid):
    rows = []
    try:
        with open(ledger_path(sid)) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def append_ledger(sid, row):
    os.makedirs(BOARD_DIR, mode=0o700, exist_ok=True)
    row = dict(row, ts=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with open(ledger_path(sid), "a") as f:
        f.write(json.dumps(row) + "\n")
    os.chmod(ledger_path(sid), 0o600)
    return row


# ---------------------------------------------------------------- transcript
def _texts(content):
    """(kind, text) pieces of a message content: kind text|tool_result."""
    if isinstance(content, str):
        return [("text", content)]
    out = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            out.append(("text", b.get("text") or ""))
        elif b.get("type") == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            out.append(("tool_result", c or ""))
    return out


def _is_user_prompt(rec):
    """A genuine prompt typed by the user (not a tool result, notification or meta row)."""
    if rec.get("type") != "user" or rec.get("isSidechain") or rec.get("isMeta"):
        return False
    c = (rec.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return False
        c = " ".join(t for k, t in _texts(c))
    c = c or ""
    if "<task-notification>" in c or c.lstrip().startswith("<"):
        return False
    return bool(c.strip())


def parse_transcript(path, now=None, sprint_re=None):
    """Walk the transcript once; return derived items, sprint ids, the user's prompts and the
    (epoch, tool_use_id) of every tool call, in order (anchors for items that carry none).
    `sprint_re` finds sprint folder references; None skips them."""
    now = now or _now()
    agents, bashes, crons, asks_q = {}, {}, {}, {}
    uses = {}               # tool_use_id -> (name, input, epoch)
    sprints = []
    prompts = []            # (epoch, text) of the user's prompts
    inferred = {}           # number -> item (latest list wins)
    marks = []              # (epoch, tool_use_id): where in the transcript each tool call sits
    mentions = {}           # "23" -> uuid of the latest assistant message that names #23
    refs = {}               # "l:x" / "m:app:id" / "#4" -> (uuid, alt) of the latest message naming it
    replies = {}            # item id -> epoch of the user's latest "re <id> ..." reply (the pane's reply button)
    last_ts = None
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("isSidechain"):
                continue
            ts = _iso_to_epoch(rec.get("timestamp"))
            if ts is not None:
                last_ts = ts
            ts = ts if ts is not None else last_ts
            typ = rec.get("type")
            # a notification can also arrive mid-turn as a queued command
            queued = ""
            if typ == "attachment" and isinstance(rec.get("attachment"), dict):
                queued = str(rec["attachment"].get("prompt") or "")
            elif typ == "queue-operation" and rec.get("operation") == "enqueue":
                queued = str(rec.get("content") or "")
            for m in NOTIF_RE.finditer(queued):
                _on_notification(m.group(1), ts, agents, bashes)
            if queued and "<task-notification>" not in queued:
                # the user typing while a turn runs arrives as a queued command, not a user record
                _on_reply(queued, ts, rec.get("uuid"), refs, replies)
            if typ not in ("user", "assistant"):
                continue
            msg = rec.get("message") or {}
            content = msg.get("content")
            if typ == "assistant" and isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        _on_tool_use(b, ts, uses, crons, asks_q, agents, bashes)
                        if b.get("id") and ts is not None:
                            marks.append((ts, b["id"]))
                        for m in (sprint_re.finditer(json.dumps(b.get("input") or {}))
                                  if sprint_re else ()):
                            if m.group(1) not in sprints:
                                sprints.append(m.group(1))
                    elif b.get("type") == "text":
                        _scan_asks(b.get("text") or "", ts, inferred, rec.get("uuid"))
                        if rec.get("uuid"):
                            for n in set(NUM_MENTION_RE.findall(b.get("text") or "")):
                                mentions[n] = (rec["uuid"], msg.get("id"))
                            for r in set(ITEM_REF_RE.findall(b.get("text") or "")):
                                refs[r] = (rec["uuid"], msg.get("id"))
            if typ == "user":
                tur = rec.get("toolUseResult")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            _on_tool_result(b, tur, ts, uses, agents, bashes, crons, asks_q)
                for kind, text in _texts(content):
                    for m in NOTIF_RE.finditer(text):
                        _on_notification(m.group(1), ts, agents, bashes)
                if _is_user_prompt(rec):
                    t = content if isinstance(content, str) else " ".join(x for _, x in _texts(content))
                    prompts.append((ts, t))
                    _on_reply(t, ts, rec.get("uuid"), refs, replies)
    # one-shot crons whose fire time passed: assume fired
    for c in crons.values():
        if c["state"] == "running" and not c.get("recurring") and c.get("next_fire") \
                and c["next_fire"] < now:
            c["state"] = "done"
            c["note"] = "fire time passed (assumed fired)"
            c["ended"] = c["next_fire"]
    # inferred asks answered by a later prompt naming the number
    for n, it in inferred.items():
        pat = re.compile(r"(?:^|[\s,;(])(?:#|\d+\.)?" + re.escape(n) + r"(?=[\s.:),]|$)")
        for pts, text in prompts:
            if pts and it["started"] and pts > it["started"] and pat.search(text[:400]):
                it["state"] = "done"
                it["note"] = "answered (inferred from your prompt " + _local_hm(pts) + ")"
                it["ended"] = pts
                break
    items = list(agents.values()) + list(bashes.values()) + list(crons.values()) + \
        [a for a in asks_q.values() if a["state"] == "waiting"] + list(inferred.values())
    return items, sprints, prompts, {"tools": marks, "mentions": mentions, "refs": refs, "replies": replies}


# The pane's reply button fills the prompt with "re <id> (<title>): "; ids look like l:x, m:app:id,
# s:app:id, a:agent, b:bash, c:cron, #N.
_SEG = r"[A-Za-z0-9][\w\-]*(?:\.[\w\-]+)*"          # a dot only inside an id, never trailing
_ITEM_ID = rf"[lmsabc]:{_SEG}(?::{_SEG})*"
ITEM_REF_RE = re.compile(rf"(?<![\w:/])({_ITEM_ID})")
# a reply takes the whole token after "re" (ledger ids are free text), minus trailing punctuation
REPLY_RE = re.compile(r"^\s*re\s+(#\d{1,3}|[lmsabc]:[^\s(]+)", re.I)


def _on_reply(text, ts, uuid, refs, replies):
    """A prompt starting "re <id>" answers that board item: remember when, and where it sits."""
    m = REPLY_RE.match(text or "")
    if not m:
        return
    rid = m.group(1).rstrip(":;,.)")
    if ts is not None:
        replies[rid] = ts
    if uuid and not rid.startswith("#"):   # a numbered ask scrolls to the latest reply naming #N
        refs[rid] = (uuid, None)


NUM_MENTION_RE = re.compile(r"(?<![\w#])#(\d{1,3})\b")


def anchor_for(marks, epoch):
    """The tool call nearest at or before `epoch` (ledger notes and sprint lines are written by one):
    what a press on the side pane scrolls the transcript to. None when nothing precedes it."""
    if epoch is None:
        return None
    best = None
    for ts, uid in marks:
        if ts <= epoch + 1:
            best = uid
        else:
            break
    return best


def _on_tool_use(b, ts, uses, crons, asks_q, agents, bashes):
    name, inp, uid = b.get("name"), b.get("input") or {}, b.get("id")
    uses[uid] = (name, inp, ts)
    if name == "AskUserQuestion":
        qs = inp.get("questions") or []
        q = qs[0].get("question") if qs and isinstance(qs[0], dict) else str(qs)[:80]
        asks_q[uid] = {"id": "q:" + uid[-6:], "kind": "question", "state": "waiting",
                       "title": _clip(q), "started": ts, "source": "AskUserQuestion", "anchor": uid}
    elif name == "SendMessage":
        to = inp.get("to") or inp.get("recipient")
        if to in agents:
            agents[to]["state"] = "running"
            agents[to]["resumed"] = ts
            agents[to].pop("ended", None)
    elif name == "TaskStop":
        tid = inp.get("task_id") or inp.get("id") or inp.get("shell_id")
        for pool in (agents, bashes):
            if tid in pool:
                pool[tid].update(state="done", note="stopped", ended=ts)
    elif name == "CronDelete":
        cid = inp.get("id")
        if cid in crons:
            crons[cid].update(state="done", note="deleted", ended=ts)


def _on_tool_result(b, tur, ts, uses, agents, bashes, crons, asks_q):
    uid = b.get("tool_use_id")
    if uid not in uses:
        return
    name, inp, started = uses[uid]
    tur = tur if isinstance(tur, dict) else {}
    if name == "Agent":
        aid = tur.get("agentId")
        if not aid:
            return
        is_async = bool(tur.get("isAsync") or inp.get("run_in_background"))
        prompt = inp.get("prompt") or ""
        brief = re.search(r"briefs/([\w.-]+?)--([\w.-]+)\.md", prompt)
        agents[aid] = {
            "id": "a:" + aid[:7], "kind": "agent", "agent_id": aid,
            "state": "running" if is_async else "done",
            "title": _clip(inp.get("description") or tur.get("description") or "agent"),
            "started": started, "ended": None if is_async else ts,
            "model": inp.get("model") or tur.get("resolvedModel"),
            "subagent_type": inp.get("subagent_type"),
            "output": tur.get("outputFile"),
            "sprint_key": f"{brief.group(1)}:{brief.group(2)}" if brief else None,
            "source": "Agent", "anchor": uid,
        }
    elif name == "Bash":
        tid = tur.get("backgroundTaskId")
        if not tid:
            return
        bashes[tid] = {"id": "b:" + tid, "kind": "bash", "task_id": tid, "state": "running",
                       "title": _clip(inp.get("description") or inp.get("command")),
                       "started": started, "source": "Bash", "anchor": uid}
        if tur.get("timedOutAfterMs"):
            bashes[tid]["note"] = "moved to background after timeout"
    elif name == "CronCreate":
        cid = str(tur.get("id") or uid[-6:])
        nf = tur.get("nextFireAt")
        crons[cid] = {"id": "c:" + cid, "kind": "cron", "state": "running",
                      "title": _clip(inp.get("prompt")), "started": started,
                      "summary": _clip(inp.get("prompt"), SUMMARY_MAX),
                      "schedule": tur.get("humanSchedule") or inp.get("cron"),
                      "recurring": bool(tur.get("recurring") if "recurring" in tur
                                        else inp.get("recurring")),
                      "next_fire": (nf / 1000.0) if isinstance(nf, (int, float)) else None,
                      "source": "CronCreate", "anchor": uid}
    elif name == "AskUserQuestion" and uid in asks_q:
        asks_q[uid]["state"] = "done"


def _on_notification(body, ts, agents, bashes):
    tags = dict((k, v.strip()) for k, v in TAG_RE.findall(body))
    tid = tags.get("task-id")
    status = (tags.get("status") or "").lower()
    target = agents.get(tid) or bashes.get(tid)
    if not target:
        return
    if status in ("completed", "failed", "killed", "stopped", "error"):
        target["state"] = "done"
        target["ended"] = ts
        if status != "completed":
            target["note"] = status
    if tags.get("summary"):
        target["summary"] = _clip(tags["summary"], SUMMARY_MAX)
    if tags.get("result"):
        target["result"] = _clip(tags["result"], SUMMARY_MAX)
    if tags.get("output-file"):
        target["output"] = tags["output-file"]


def _scan_asks(text, ts, inferred, msg_uuid=None):
    """Numbered "N. **Title:** body" lines in a reply that says it needs the user."""
    if not NEEDS_YOU_RE.search(text):
        return
    found = {}
    for line in text.splitlines():
        m = ASK_LINE_RE.match(line)
        if m:
            n, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
            found[n] = {"id": "#" + n, "kind": "ask", "state": "waiting", "inferred": True,
                        "title": _clip(f"{title}: {body}"), "started": ts,
                        "source": "parent reply (inferred)", "anchor": msg_uuid}
    if len(found) >= 1:
        inferred.update(found)


# ---------------------------------------------------------------- sprint
def parse_sprint(sprint_id, sprints_dir=None, now=None):
    sprints_dir = sprints_dir or SPRINTS_DIR
    if not sprints_dir:
        return [], None
    d = os.path.join(sprints_dir, sprint_id)
    if not os.path.isdir(d):
        return [], None
    try:
        run = _read_json(os.path.join(d, "sprint_run.json"))
    except (OSError, ValueError):
        run = {}
    try:
        manifest = {m["key"]: m for m in _read_json(os.path.join(d, "manifest.json"))}
    except (OSError, ValueError, KeyError, TypeError):
        manifest = {}
    items = {}
    log = ""
    try:
        with open(os.path.join(d, "SPRINT.md")) as f:
            log = f.read()
    except OSError:
        pass
    in_log = False
    day = (run.get("started_at") or "")[:10]
    prev_ts = None
    for raw in log.splitlines():
        if raw.startswith("## "):
            in_log = raw.strip().lower().startswith("## running log")
            continue
        if not in_log:
            continue
        m = LOG_LINE_RE.match(raw.strip())
        if not m:
            continue
        hm, rest = m.group(1), m.group(2)
        ts = _hm_epoch(day, hm)
        # the log is in time order and carries only HH:MM: a time earlier than the previous line
        # (by more than an hour of slack for hand-written lines) means the sprint ran past midnight
        if ts is not None and prev_ts is not None and ts < prev_ts - 3600:
            day = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            ts = _hm_epoch(day, hm)
        prev_ts = ts if ts is not None else prev_ts
        if rest.lower().startswith("wave") or rest.lower().startswith("launched"):
            for key in re.findall(KEY_RE, rest.split("(next")[0]):
                items.setdefault(key, _sprint_item(sprint_id, key, d, manifest, ts))
            continue
        if rest.startswith("PARENT"):
            body = rest[len("PARENT"):].strip()
            state = "held" if re.search(r"\bHELD\b", body) else "done"
            k = "parent:" + re.sub(r"\W+", "-", body.split("—")[0].strip().lower())[:40]
            items[k] = {"id": "s:" + k, "kind": "parent", "state": state, "topic": "sprint",
                        "title": _clip(body), "started": ts, "source": f"SPRINT.md {hm}"}
            continue
        km = re.match(r"(" + KEY_RE + r")\s+[—-]+\s+(.*)$", rest)
        if not km:
            continue
        key, verdict = km.group(1), km.group(2)
        it = items.setdefault(key, _sprint_item(sprint_id, key, d, manifest, ts))
        word = re.match(r"([A-Z][A-Z-]+)", verdict)
        word = word.group(1) if word else ""
        it["state"] = ("blocked" if word.startswith("BLOCKED") else
                       "held" if word.startswith(("HELD", "REVERTED")) else "done")
        it["verdict"] = word or "logged"
        it["evidence"] = _clip(verdict, 260)
        it["ended"] = ts
        asked = re.search(r"(?:" + ASK_LABEL + r"):\s*([^\[]+)", verdict)
        open_ask = items.get("ask:" + key)
        if open_ask and open_ask["state"] == "waiting":
            # a later log line for the same item supersedes its earlier ask
            open_ask.update(state="done", ended=ts, evidence=f"superseded by the {hm} log line")
        if asked and not asked.group(1).strip().lower().startswith(("nothing", "none", "-")):
            ask = asked.group(1).strip().rstrip(".")
            items["ask:" + key] = {"id": "m:" + key, "kind": "ask", "state": "waiting",
                                   "topic": "sprint", "title": _clip(f"{key}: {ask}"),
                                   "ask": ask, "started": ts, "report": it.get("report"),
                                   "source": f"SPRINT.md {hm}"}
    for it in items.values():
        it.setdefault("topic", "sprint")
    head = {"id": sprint_id, "status": run.get("status"), "window": run.get("window_label"),
            "queued": len(manifest), "dir": d,
            "launched": len(_load_list(os.path.join(d, "launched.json")))}
    return list(items.values()), head


def _load_list(path):
    try:
        v = _read_json(path)
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def _hm_epoch(day, hm):
    try:
        return datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        return None


def _sprint_item(sprint_id, key, d, manifest, ts):
    app, _, rid = key.partition(":")
    report = os.path.join(d, f"{app}--{rid}.md")
    m = manifest.get(key) or {}
    return {"id": "s:" + key, "kind": "sprint-item", "state": "running", "key": key,
            "title": key, "started": ts, "agent": m.get("agent"),
            "report": report if os.path.exists(report) else None,
            "brief": m.get("brief"), "source": f"sprint {sprint_id}"}


# ---------------------------------------------------------------- assemble
def apply_ledger(items, rows):
    """Ledger rows: topic rules, item-topic tags, explicit items, resolutions."""
    rules, tags, explicit, resolved = [], {}, {}, {}
    for r in rows:
        k = r.get("kind")
        if k == "topic" and r.get("topic"):
            if r.get("match"):
                rules.append((r["topic"], r["match"]))
            if r.get("item"):
                tags[r["item"]] = r["topic"]
        elif k == "resolve" and r.get("id"):
            resolved[str(r["id"]).lstrip("#")] = r
        elif k in KIND_STATE:
            rid = str(r.get("id") or f"l{len(explicit) + 1}")
            if KIND_STATE[k] != "done":
                resolved.pop(rid.lstrip("#"), None)   # a later ask reusing a number reopens it
            prev = explicit.get(rid.lstrip("#"), {})
            explicit[rid.lstrip("#")] = dict(prev, **{
                "id": ("#" + rid.lstrip("#")) if rid.lstrip("#").isdigit() else "l:" + rid,
                "kind": "ask" if k in ("ask", "todo") else k, "state": KIND_STATE[k],
                "title": _clip(r.get("text") or prev.get("title")),
                "topic": r.get("topic") or prev.get("topic"),
                "evidence": r.get("evidence") or prev.get("evidence"),
                "impact": float(r["impact"]) if r.get("impact") is not None else prev.get("impact"),
                "why": r.get("why") or prev.get("why"),
                "started": prev.get("started") or _iso_to_epoch(r.get("ts")),
                # the LATEST ask on this id: a reply only answers asks made before it
                "asked": _iso_to_epoch(r.get("ts")) or prev.get("asked"),
                "source": "ledger"})
    # explicit ledger rows supersede an inferred ask with the same number
    by_id = {it["id"]: it for it in items}
    for key, e in explicit.items():
        if e["id"] in by_id and by_id[e["id"]].get("inferred"):
            items.remove(by_id[e["id"]])
        items.append(e)
    for it in items:
        bare = it["id"].lstrip("#").split(":", 1)[-1]
        r = resolved.get(it["id"].lstrip("#")) or resolved.get(bare)
        if r and it["state"] != "done":
            it["state"] = "done"
            it["evidence"] = r.get("evidence") or it.get("evidence") or "resolved in ledger"
            it["ended"] = _iso_to_epoch(r.get("ts"))
        if it["id"] in tags:
            it["topic"] = tags[it["id"]]
        if not it.get("topic"):
            hay = " ".join(str(it.get(f) or "") for f in ("title", "summary", "key"))
            for topic, pat in rules:
                try:
                    if re.search(pat, hay, re.I):
                        it["topic"] = topic
                        break
                except re.error:
                    continue
        it.setdefault("topic", None)
        it["topic"] = it["topic"] or "other"
    return items


def build_board(session=None, now=None, sprints_dir=None):
    now = now or _now()
    sprints_dir = sprints_dir or SPRINTS_DIR
    sid, path = resolve_session(session)
    items, sprint_ids, _, anchors = parse_transcript(path, now, sprint_ref_re(sprints_dir))
    sprint_heads = []
    # a sprint agent is shown once, on its sprint item
    by_key = {}
    parsed = [(sp,) + parse_sprint(sp, sprints_dir, now) for sp in sprint_ids]
    parsed = [x for x in parsed if x[2]]
    # the running sprint(s); with none running, only the NEWEST one this session referenced (ids start
    # with their date). "Last referenced" would let a brief that merely cites an old sprint's file swap
    # the board to that sprint's stale asks.
    live = [x for x in parsed if x[2].get("status") == "running"] or sorted(
        parsed, key=lambda x: (x[0][:10], str(x[2].get("started_at") or ""), x[0]))[-1:]
    for sp, s_items, head in live:
        sprint_heads.append(head)
        for it in s_items:
            if it.get("key"):
                by_key[it["key"]] = it
        items.extend(s_items)
    for a in [i for i in items if sprints_dir and i.get("kind") == "agent" and i.get("sprint_key")]:
        s = by_key.get(a["sprint_key"])
        if not s:
            a["topic"] = "sprint"
            continue
        s["agent_id"] = a["agent_id"]
        s["anchor"] = a.get("anchor")      # the sprint item scrolls to its agent's own call
        s["output"] = a.get("output")
        s["result"] = a.get("result")
        if s["state"] == "running" and a["state"] == "done":
            s["state"] = "done"
            s["verdict"] = "finished, not yet logged"
            s["ended"] = a.get("ended")
        items.remove(a)
    items = apply_ledger(items, read_ledger(sid))
    for it in items:
        # where a press on the side pane scrolls the transcript: a numbered ask goes to the latest
        # reply that names its #N (where it was last discussed); else the item's own tool call or
        # message; else the tool call that wrote it (a ledger note, a sprint log line)
        num = it["id"][1:] if it["id"].startswith("#") else None
        replied = anchors["replies"].get(it["id"])
        # the item's latest ask: a ledger re-ask (`asked`), or a sprint log line that blocked it
        # again (`ended` moves with every log line); a reply only answers what came before it
        latest = max([x for x in (it.get("asked"), it.get("started"), it.get("ended")) if x] or [0])
        if replied and it.get("state") in ("waiting", "blocked") and replied >= latest:
            # the user answered it from the pane (or typed "re <id>"): it is Claude's turn now
            it["state"] = "running"
            it["replied"] = replied
            it["note"] = f"you replied {_local_hm(replied)}; Claude's turn"
        if it["id"] in anchors["refs"]:
            # the latest place it was discussed: the user's reply or a message naming the id
            # a queued (mid-turn) reply may not be drawn under its record uuid: fall back to the old spot
            prev = it.get("anchor") or anchor_for(anchors["tools"], it.get("started"))
            it["anchor"], alt = anchors["refs"][it["id"]]
            it["anchor_alt"] = alt or prev
        elif num and num in anchors["mentions"]:
            # a message row's render id is its record uuid or its API message id: the pane tries both
            it["anchor"], it["anchor_alt"] = anchors["mentions"][num]
        elif not it.get("anchor"):
            it["anchor"] = anchor_for(anchors["tools"], it.get("started"))
        if it.get("state") == "running" and it.get("output"):
            try:
                it["last_activity"] = os.path.getmtime(it["output"])
            except OSError:
                pass
    order = {s: i for i, s in enumerate(STATES)}
    # WAITING: biggest sprint blocker first (impact = how much it unblocks, set by --impact);
    # inferred asks have no impact and sink. Other states keep topic grouping.
    items.sort(key=lambda i: (order.get(i["state"], 9),
                              -(i.get("impact") or 0) if i["state"] == "waiting" else 0,
                              i["topic"], -(i.get("ended") or i.get("started") or 0)))
    counts = {s: sum(1 for i in items if i["state"] == s) for s in STATES}
    topics = {}
    for it in items:
        t = topics.setdefault(it["topic"], {s: 0 for s in STATES})
        t[it["state"]] += 1
    return {"session_id": sid, "session": session_name(sid), "transcript": path,
            "generated_at": now, "counts": counts, "topics": topics,
            "sprints": sprint_heads, "ledger": ledger_path(sid), "items": items}


# ---------------------------------------------------------------- detail
def _tail_lines(path, lines, max_bytes=8000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", "replace")
    except OSError as e:
        return [f"(cannot read {path}: {e.strerror})"]
    return data.splitlines()[-lines:]


def _agent_tail(path, n_texts=2, max_chars=1500):
    """Last assistant texts + tool count of a subagent transcript (bounded)."""
    texts, tools, last_tool = [], 0, None
    try:
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("type") != "assistant":
                    continue
                for b in (r.get("message") or {}).get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        texts.append(b["text"].strip())
                    elif b.get("type") == "tool_use":
                        tools += 1
                        inp = b.get("input") or {}
                        last_tool = f"{b.get('name')}: {_clip(inp.get('description') or inp.get('command') or inp.get('file_path') or '', 90)}"
    except OSError as e:
        return [f"(cannot read {path}: {e.strerror})"]
    out = [f"tool calls so far: {tools}"] + ([f"last tool: {last_tool}"] if last_tool else [])
    for t in texts[-n_texts:]:
        out.append("> " + _clip(t, max_chars // n_texts))
    return out


def detail(board, item_id, lines=30):
    it = next((i for i in board["items"] if i["id"] == item_id or
               i["id"].split(":", 1)[-1] == item_id or i["id"].lstrip("#") == item_id.lstrip("#")),
              None)
    if not it:
        return None
    now = board["generated_at"]
    out = {"item": it, "paths": {}, "lines": []}
    L = out["lines"]
    L.append(f"{it['id']}  [{it['state']}]  {it['title']}")
    meta = []
    if it.get("started"):
        meta.append(f"started {_local_hm(it['started'])} ({_age(it['started'], now)} ago)")
    if it.get("ended"):
        meta.append(f"ended {_local_hm(it['ended'])}")
    if it.get("last_activity"):
        meta.append(f"last activity {_age(it['last_activity'], now)} ago")
    for k in ("model", "subagent_type", "agent", "schedule", "verdict", "note", "source"):
        if it.get(k):
            meta.append(f"{k} {it[k]}")
    if it.get("next_fire"):
        meta.append(f"fires {_local_hm(it['next_fire'])}")
    L.append("  " + " · ".join(meta))
    for k in ("ask", "evidence", "summary", "result"):
        if it.get(k):
            L.append(f"{k}: {it[k]}")
    for k in ("report", "brief", "output"):
        if it.get(k):
            out["paths"][k] = it[k]
            L.append(f"{k}: {it[k]}")
    if it.get("kind") == "bash" or (it.get("task_id") and not it.get("output")):
        for g in glob.glob(TASK_GLOB.format(sid=board["session_id"])):
            p = os.path.join(g, f"{it['task_id']}.output")
            if os.path.exists(p):
                out["paths"]["output"] = p
                L.append(f"output: {p}")
                L.append(f"--- last {lines} lines ---")
                L.extend("  " + _clip(x, 200) for x in _tail_lines(p, lines))
    elif it.get("output") and os.path.exists(it["output"]):
        L.append("--- subagent, latest ---")
        L.extend("  " + x for x in _agent_tail(it["output"]))
    if it.get("report") and os.path.exists(it["report"]):
        L.append(f"--- report head ({os.path.basename(it['report'])}) ---")
        try:
            with open(it["report"]) as f:
                L.extend("  " + _clip(x, 200) for x in f.read().splitlines()[:12])
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- render
def render_text(board, width=100):
    now = board["generated_at"]
    c = board["counts"]
    out = [f"{board['session']} · {_local_hm(now)} · {c['running']} running · "
           f"{c['waiting']} waiting on you · {c['blocked'] + c['held']} blocked/held · "
           f"{c['done']} done"]
    for s in board["sprints"]:
        out.append(f"sprint {s['id']} ({s.get('status')}, {s.get('window') or ''}) "
                   f"launched {s['launched']}/{s['queued']}")
    for state in STATES:
        rows = [i for i in board["items"] if i["state"] == state]
        if not rows:
            continue
        out.append("")
        out.append(f"{STATE_LABEL[state]} ({len(rows)})")
        shown = rows if state != "done" else rows[:12]
        for it in shown:
            when = ""
            if state == "running":
                when = _age(it.get("started"), now)
                if it.get("next_fire"):
                    when = "fires " + _local_hm(it["next_fire"])
            elif it.get("ended"):
                when = _local_hm(it["ended"])
            extra = it.get("ask") and state == "waiting" and "" or ""
            tag = " (inferred)" if it.get("inferred") else ""
            line = f"  {it['id']:<14} {it['topic'][:10]:<10} {when:>8}  {it['title']}{tag}{extra}"
            out.append(_clip(line, width))
        if len(rows) > len(shown):
            out.append(f"  … {len(rows) - len(shown)} more done (--json for all)")
    out.append("")
    out.append("detail: session_board.py detail <id>   ledger: " + board["ledger"])
    return "\n".join(out)


def _json_default(o):
    return str(o)


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="session_board.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("show"); p.add_argument("--session"); p.add_argument("--json", action="store_true")
    p.add_argument("--width", type=int, default=110)
    p = sub.add_parser("detail"); p.add_argument("item"); p.add_argument("--session")
    p.add_argument("--lines", type=int, default=30); p.add_argument("--json", action="store_true")
    p = sub.add_parser("note"); p.add_argument("--session"); p.add_argument("--kind", required=True, choices=LEDGER_KINDS)
    p.add_argument("--text", default=""); p.add_argument("--id"); p.add_argument("--topic")
    p.add_argument("--match", help="topic rule: regex matched against item titles")
    p.add_argument("--evidence")
    p.add_argument("--impact", type=float, help="waiting items: how much this unblocks (sort key, higher first)")
    p.add_argument("--why", help="one line: what it unblocks")
    p = sub.add_parser("resolve"); p.add_argument("id"); p.add_argument("--session"); p.add_argument("--evidence")
    p = sub.add_parser("tag"); p.add_argument("item"); p.add_argument("--topic", required=True); p.add_argument("--session")
    a = ap.parse_args(argv)
    if a.cmd in (None, "show"):
        board = build_board(getattr(a, "session", None))
        if getattr(a, "json", False):
            print(json.dumps(board, default=_json_default))
        else:
            print(render_text(board, getattr(a, "width", 110)))
        return 0
    if a.cmd == "detail":
        board = build_board(a.session)
        d = detail(board, a.item, a.lines)
        if d is None:
            print(f"no item {a.item!r}", file=sys.stderr)
            return 1
        print(json.dumps(d, default=_json_default) if a.json else "\n".join(d["lines"]))
        return 0
    sid, _ = resolve_session(a.session)
    if a.cmd == "note":
        if a.kind == "topic" and not (a.topic and a.match):
            ap.error("note --kind topic needs --topic and --match")
        if a.kind != "topic" and not a.text:
            ap.error("note needs --text")
        row = {"kind": a.kind, "text": a.text, "id": a.id, "topic": a.topic,
               "match": a.match, "evidence": a.evidence,
               "impact": a.impact, "why": a.why}
        row = append_ledger(sid, {k: v for k, v in row.items() if v is not None and v != ""})
    elif a.cmd == "resolve":
        row = append_ledger(sid, {"kind": "resolve", "id": a.id, "evidence": a.evidence or ""})
    else:
        row = append_ledger(sid, {"kind": "topic", "item": a.item, "topic": a.topic})
    print(f"noted on {sid[:8]}: {json.dumps(row)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
