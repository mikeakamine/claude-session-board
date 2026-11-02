"""Tests for session_board.py -- synthetic transcript + sprint folder, no real session data."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import session_board as sb  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"
T0 = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc).timestamp()


def iso(off):
    return datetime.fromtimestamp(T0 + off, timezone.utc).isoformat().replace("+00:00", "Z")


def asst(off, *blocks):
    return {"type": "assistant", "timestamp": iso(off), "message": {"content": list(blocks)}}


def use(uid, name, **inp):
    return {"type": "tool_use", "id": uid, "name": name, "input": inp}


def result(off, uid, tur, text="ok"):
    return {"type": "user", "timestamp": iso(off), "toolUseResult": tur,
            "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": text}]}}


def notif(task_id, status, summary, res=""):
    return (f"<task-notification>\n<task-id>{task_id}</task-id>\n<status>{status}</status>\n"
            f"<summary>{summary}</summary>\n<result>{res}</result>\n</task-notification>")


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


def prompt(off, text):
    return {"type": "user", "timestamp": iso(off), "message": {"content": text}}


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.projects = os.path.join(root, "projects", "-x")
        os.makedirs(self.projects)
        self.sprints = os.path.join(root, "proj", "sprints")
        self.sprint = os.path.join(self.sprints, "2026-10-31-test")
        os.makedirs(os.path.join(self.sprint, "briefs"))
        self._saved = (sb.PROJECTS, sb.BOARD_DIR, sb.NAMES_DIR, sb.SPRINTS_DIR)
        sb.PROJECTS = os.path.join(root, "projects")
        sb.BOARD_DIR = os.path.join(root, "board")
        sb.NAMES_DIR = os.path.join(root, "names")
        sb.SPRINTS_DIR = None   # each board() call names the sprints dir; the default stays off
        os.makedirs(sb.NAMES_DIR)
        put(os.path.join(sb.NAMES_DIR, SID + ".json"), json.dumps({"session_id": SID, "session_name": "claude-t1"}))
        self._write_sprint()
        self._write_transcript()

    def tearDown(self):
        sb.PROJECTS, sb.BOARD_DIR, sb.NAMES_DIR, sb.SPRINTS_DIR = self._saved
        self.tmp.cleanup()

    def _write_sprint(self):
        d = self.sprint
        put(os.path.join(d, "sprint_run.json"), json.dumps({"id": "2026-10-31-test", "status": "running", "started_at": "2026-10-31T14:00:00-07:00",
                   "window_label": "14:00 → 18:00"}))
        put(os.path.join(d, "manifest.json"), json.dumps([{"n": 1, "key": "app:one", "agent": "worker", "brief": d + "/briefs/app--one.md"},
                   {"n": 2, "key": "app:two", "agent": "worker"},
                   {"n": 3, "key": "app:three", "agent": "worker"},
                   {"n": 4, "key": "app:four", "agent": "worker"}]))
        put(os.path.join(d, "launched.json"), json.dumps(["app:one", "app:two", "app:three", "app:four"]))
        put(os.path.join(d, "app--two.md"),"# report two\nall good\n")
        put(os.path.join(d, "SPRINT.md"),
            "# Sprint\n\n## Queue\n- 14:00 app:not-a-log-line — DONE\n\n## Running log\n\n"
            "- 14:01 wave 1 launched: app:one, app:two, app:three (next: #4)\n"
            "- 14:02 PARENT other-repo landing — gate SHIP; merge HELD while sprint runs\n"
            "- 14:05 app:two — DONE on branch abc1234, 9 tests OK. Ask: nothing. [report: yes]\n"
            "- 14:06 app:three — BLOCKED: needs a PDF. Ask: save the PDF to ~/x/.\n"
            "- 14:07 launched app:four (worker)\n"
            "- 14:08 app:four — HELD: fix lives on another branch. Ask: agree/disagree on the diff\n"
            "- 14:09 app:four — DONE after all. [report: yes]\n")

    def _write_transcript(self):
        rows = [
            prompt(0, "start the sprint and plan the offsite"),
            asst(10, use("tu_a1", "Agent", description="Sprint: one", subagent_type="worker",
                         run_in_background=True,
                         prompt=f"Your brief is {self.sprints}/2026-10-31-test/briefs/app--one.md")),
            result(11, "tu_a1", {"agentId": "aone111111", "isAsync": True, "status": "async_launched",
                                 "outputFile": "/nonexistent/a.output"}),
            asst(20, use("tu_a2", "Agent", description="Draft rollout notes", run_in_background=True,
                         prompt="draw")),
            result(21, "tu_a2", {"agentId": "atwo222222", "isAsync": True}),
            asst(30, use("tu_b1", "Bash", command="sleep 100", description="Build release bundle",
                         run_in_background=True)),
            result(31, "tu_b1", {"backgroundTaskId": "bxyz1", "stdout": ""}),
            asst(40, use("tu_b2", "Bash", command="make", description="Gate watcher", run_in_background=True)),
            result(41, "tu_b2", {"backgroundTaskId": "bxyz2"}),
            asst(50, use("tu_c1", "CronCreate", cron="54 15 31 10 *", recurring=False, prompt="Offsite agenda prep")),
            result(51, "tu_c1", {"id": "cron1", "humanSchedule": "54 15 31 10 *", "recurring": False,
                                 "nextFireAt": int((T0 + 3600) * 1000)}),
            asst(55, use("tu_c2", "CronCreate", cron="0 9 * * *", recurring=False, prompt="Old reminder")),
            result(56, "tu_c2", {"id": "cron2", "recurring": False, "nextFireAt": int((T0 + 100) * 1000)}),
            asst(60, {"type": "text", "text": "Three decisions need you:\n"
                      "1. **Venue, Friday:** booking is a purchase.\n"
                      "2. **Rollout:** I will not send the announcement.\n"
                      "3. **Offsite agenda:** the final call is yours."}),
            prompt(70, "1 skip the venue, 3 ok set a reminder"),
            {"type": "attachment", "timestamp": iso(80),
             "attachment": {"type": "queued_command", "prompt": notif("bxyz1", "completed", "Bundle built")}},
            prompt(90, notif("atwo222222", "completed", 'Agent "Draft rollout notes" finished', "12 pages")),
            asst(95, use("tu_q", "AskUserQuestion", questions=[{"question": "Which region goes first?"}])),
            asst(100, use("tu_s", "SendMessage", to="atwo222222", message="more please")),
            {"type": "user", "isSidechain": True, "timestamp": iso(105), "message": {"content": "ignored"}},
        ]
        with open(os.path.join(self.projects, SID + ".jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def board(self):
        return sb.build_board("claude-t1", now=T0 + 600, sprints_dir=self.sprints)

    def by_id(self, b):
        return {i["id"]: i for i in b["items"]}

    def test_resolve_by_name_and_prefix(self):
        self.assertEqual(sb.resolve_session("claude-t1")[0], SID)
        self.assertEqual(sb.resolve_session(SID[:8])[0], SID)

    def test_agents_bash_and_notifications(self):
        items = self.by_id(self.board())
        self.assertEqual(items["b:bxyz1"]["state"], "done")          # queued attachment notification
        self.assertEqual(items["b:bxyz2"]["state"], "running")
        self.assertEqual(items["a:atwo222"]["state"], "running")     # resumed by SendMessage
        self.assertEqual(items["a:atwo222"]["result"], "12 pages")
        self.assertNotIn("a:aone111", items)                         # folded into its sprint item

    def test_crons(self):
        items = self.by_id(self.board())
        self.assertEqual(items["c:cron1"]["state"], "running")
        self.assertAlmostEqual(items["c:cron1"]["next_fire"], T0 + 3600)
        self.assertEqual(items["c:cron2"]["state"], "done")          # one-shot, fire time passed

    def test_inferred_asks_and_answers(self):
        items = self.by_id(self.board())
        self.assertEqual(items["#1"]["state"], "done")
        self.assertEqual(items["#3"]["state"], "done")
        self.assertEqual(items["#2"]["state"], "waiting")
        self.assertTrue(items["#2"]["inferred"])
        self.assertEqual(items["q:" + "tu_q"[-6:]]["state"], "waiting")

    def test_sprint_states(self):
        b = self.board()
        items = self.by_id(b)
        self.assertEqual(items["s:app:one"]["state"], "running")
        self.assertEqual(items["s:app:one"]["agent_id"], "aone111111")
        self.assertEqual(items["s:app:two"]["state"], "done")
        self.assertTrue(items["s:app:two"]["report"].endswith("app--two.md"))
        self.assertEqual(items["s:app:three"]["state"], "blocked")
        self.assertEqual(items["m:app:three"]["state"], "waiting")
        self.assertIn("save the PDF", items["m:app:three"]["ask"])
        self.assertEqual(items["s:app:four"]["state"], "done")
        self.assertEqual(items["m:app:four"]["state"], "done")       # superseded by a later line
        self.assertNotIn("s:app:not-a-log-line", items)
        held = [i for i in b["items"] if i["kind"] == "parent"]
        self.assertEqual(held[0]["state"], "held")
        self.assertEqual(b["sprints"][0]["launched"], 4)

    def test_ledger_topics_asks_resolve(self):
        sb.append_ledger(SID, {"kind": "topic", "topic": "offsite", "match": "offsite"})
        sb.append_ledger(SID, {"kind": "topic", "topic": "docs", "item": "a:atwo222"})
        sb.append_ledger(SID, {"kind": "ask", "id": "2", "text": "Rollout: agree to skip the beta?", "topic": "rollout"})
        sb.append_ledger(SID, {"kind": "todo", "id": "renew-cert", "text": "Renew the TLS cert"})
        b = self.board()
        items = self.by_id(b)
        self.assertEqual(items["c:cron1"]["topic"], "offsite")
        self.assertEqual(items["a:atwo222"]["topic"], "docs")
        self.assertEqual(items["s:app:one"]["topic"], "sprint")
        self.assertFalse(items["#2"].get("inferred"))                # ledger supersedes inferred
        self.assertEqual(items["#2"]["topic"], "rollout")
        self.assertEqual(items["l:renew-cert"]["state"], "waiting")
        sb.append_ledger(SID, {"kind": "resolve", "id": "2", "evidence": "agreed 15:00"})
        sb.append_ledger(SID, {"kind": "resolve", "id": "renew-cert"})
        items = self.by_id(self.board())
        self.assertEqual(items["#2"]["state"], "done")
        self.assertEqual(items["#2"]["evidence"], "agreed 15:00")
        self.assertEqual(items["l:renew-cert"]["state"], "done")
        # a later report reuses #2 for a new question: the new ask is open, the old resolve stays history
        sb.append_ledger(SID, {"kind": "ask", "id": "2", "text": "New question #2", "topic": "rollout"})
        items = self.by_id(self.board())
        self.assertEqual(items["#2"]["state"], "waiting")
        self.assertEqual(items["#2"]["title"], "New question #2")
        self.assertEqual(oct(os.stat(sb.ledger_path(SID)).st_mode & 0o777), "0o600")

    def test_anchors_for_scrolling_the_transcript(self):
        items = self.by_id(self.board())
        self.assertEqual(items["a:atwo222"]["anchor"], "tu_a2")           # an agent: its Agent call
        self.assertEqual(items["b:bxyz1"]["anchor"], "tu_b1")             # a background Bash: its call
        # a ledger note with no call of its own: the tool call at or before it
        sb.append_ledger(SID, {"kind": "todo", "id": "renew-cert", "text": "Renew the TLS cert"})
        items = self.by_id(self.board())
        self.assertTrue(items["l:renew-cert"]["anchor"])
        # a numbered ask: the latest assistant message naming its #N
        rows = [json.loads(l) for l in open(os.path.join(self.projects, SID + ".jsonl"))]
        rows.append({"type": "assistant", "uuid": "msg-late", "timestamp": iso(9000),
                     "message": {"content": [{"type": "text", "text": "Still open: #2 and #12."}]}})
        with open(os.path.join(self.projects, SID + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        sb.append_ledger(SID, {"kind": "ask", "id": "2", "text": "Rollout?"})
        items = self.by_id(self.board())
        self.assertEqual(items["#2"]["anchor"], "msg-late")
        self.assertIn("anchor_alt", items["#2"])
        self.assertEqual(items["s:app:one"]["anchor"], "tu_a1")
        self.assertEqual(sb.NUM_MENTION_RE.findall("see #4, not x#5 or ##6"), ["4"])

    def test_reply_moves_item_to_claude_and_anchors_latest(self):
        sb.append_ledger(SID, {"kind": "todo", "id": "launch-list", "text": "Docs, changelog, handoff"})
        sb.append_ledger(SID, {"kind": "todo", "id": "other", "text": "Untouched"})
        self.assertEqual(self.by_id(self.board())["l:launch-list"]["state"], "waiting")
        rows = [json.loads(l) for l in open(os.path.join(self.projects, SID + ".jsonl"))]
        later = time.time() + 0.5   # after the ledger note's own timestamp
        off = later - T0
        rows.append({"type": "user", "uuid": "u-reply", "timestamp": iso(off),
                     "message": {"content": "re l:launch-list (Docs, changelog, handoff): what is left?"}})
        rows.append({"type": "attachment", "uuid": "u-queued", "timestamp": iso(off + 5),
                     "attachment": {"type": "queued_command", "prompt": "re #2 (Rollout): agree"}})
        rows.append({"type": "assistant", "uuid": "msg-ans", "timestamp": iso(off + 10),
                     "message": {"content": [{"type": "text", "text": "On m:app:thing and #2: done."}]}})
        with open(os.path.join(self.projects, SID + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        sb.append_ledger(SID, {"kind": "ask", "id": "2", "text": "Rollout?"})
        items = self.by_id(sb.build_board("claude-t1", now=later + 60, sprints_dir=self.sprints))
        q = items["l:launch-list"]
        self.assertEqual(q["state"], "running")
        self.assertIn("Claude's turn", q["note"])
        self.assertEqual(q["anchor"], "u-reply")
        self.assertEqual(items["l:other"]["state"], "waiting")
        self.assertEqual(items["#2"]["anchor"], "msg-ans")     # numbered: latest message naming #2
        # a new ask on the same id after the reply is the user's turn again
        # ledger times are whole seconds; 2.1 s guarantees the re-ask's floored stamp is past the reply
        time.sleep(2.1)
        sb.append_ledger(SID, {"kind": "todo", "id": "launch-list", "text": "Pick A or B"})
        items = self.by_id(sb.build_board("claude-t1", now=later + 60, sprints_dir=self.sprints))
        self.assertEqual(items["l:launch-list"]["state"], "waiting")
        self.assertEqual(sb.REPLY_RE.match("re l:odd/id (x): y").group(1), "l:odd/id")
        # a sprint item blocked again after the reply is back with the user
        three = self.by_id(sb.build_board("claude-t1", now=later + 60, sprints_dir=self.sprints))["s:app:three"]
        self.assertEqual(three["state"], "blocked")
        rows = [json.loads(l) for l in open(os.path.join(self.projects, SID + ".jsonl"))]
        rows.append({"type": "user", "uuid": "u-r3", "timestamp": iso(three["ended"] - T0 - 30),
                     "message": {"content": "re s:app:three (x): saved it"}})
        with open(os.path.join(self.projects, SID + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        self.assertEqual(self.by_id(sb.build_board("claude-t1", now=later + 60, sprints_dir=self.sprints))
                         ["s:app:three"]["state"], "blocked")
        sb.append_ledger(SID, {"kind": "resolve", "id": "launch-list"})
        self.assertEqual(self.by_id(sb.build_board("claude-t1", now=later + 90, sprints_dir=self.sprints))
                         ["l:launch-list"]["state"], "done")
        self.assertEqual(sb.ITEM_REF_RE.findall("see l:x-1, m:app:id. not http://a:b"), ["l:x-1", "m:app:id"])

    def test_old_sprint_cited_later_does_not_replace_newest(self):
        old = os.path.join(self.sprints, "2026-10-13-old")
        os.makedirs(os.path.join(old, "briefs"))
        put(os.path.join(old, "sprint_run.json"), json.dumps({"id": "2026-10-13-old", "status": "closed"}))
        put(os.path.join(old, "SPRINT.md"), "# Sprint\n\n## Running log\n\n- 01:00 app:old — HELD: x. Ask: agree\n")
        # neither sprint is running, so the board must fall back to the newest by date
        put(os.path.join(self.sprint, "sprint_run.json"), json.dumps({"id": "2026-10-31-test", "status": "closed"}))
        rows = [json.loads(l) for l in open(os.path.join(self.projects, SID + ".jsonl"))]
        rows.append(asst(9500, use("tu_old", "Agent", description="apply an old diff", run_in_background=True,
                                   prompt=f"read {self.sprints}/2026-10-13-old/x.diff")))
        with open(os.path.join(self.projects, SID + ".jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")
        b = self.board()
        self.assertEqual([s["id"] for s in b["sprints"]], ["2026-10-31-test"])

    def test_overnight_sprint_lines_roll_to_the_next_day(self):
        put(os.path.join(self.sprint, "sprint_run.json"),
            json.dumps({"id": "2026-10-31-test", "status": "running", "started_at": "2026-10-31T23:30:00-07:00"}))
        put(os.path.join(self.sprint, "SPRINT.md"),
            "# Sprint\n\n## Running log\n\n- 23:40 wave 1 launched: app:one, app:two\n"
            "- 23:50 app:two — BLOCKED: needs a PDF. Ask: save it\n"
            "- 09:10 app:two — BLOCKED: still needs it. Ask: save it\n")
        two = self.by_id(self.board())["s:app:two"]
        first = datetime(2026, 10, 31, 23, 50).timestamp()
        self.assertGreater(two["ended"], first)                     # 09:10 is the next morning
        self.assertLess(two["ended"] - first, 12 * 3600)

    def test_counts_order_and_render(self):
        b = self.board()
        states = [i["state"] for i in b["items"]]
        self.assertEqual(states, sorted(states, key=sb.STATES.index))
        self.assertEqual(sum(b["counts"].values()), len(b["items"]))
        text = sb.render_text(b)
        self.assertIn("RUNNING", text)
        self.assertIn("WAITING ON YOU", text)
        self.assertIn("claude-t1", text)
        json.dumps(b, default=str)

    def test_detail_bounded(self):
        b = self.board()
        tasks = os.path.join(self.tmp.name, "tasks")
        os.makedirs(tasks)
        put(os.path.join(tasks, "bxyz2.output"),"\n".join(f"line {i}" for i in range(500)))
        saved = sb.TASK_GLOB
        sb.TASK_GLOB = tasks.replace(SID, "{sid}") if SID in tasks else tasks
        try:
            d = sb.detail(b, "bxyz2", lines=5)
        finally:
            sb.TASK_GLOB = saved
        self.assertEqual(d["lines"][-1].strip(), "line 499")
        self.assertEqual(sum(1 for x in d["lines"] if x.strip().startswith("line ")), 5)
        d2 = sb.detail(b, "app:two")
        self.assertIn("report", d2["paths"])
        self.assertIsNone(sb.detail(b, "nope"))

    def test_sprints_off_by_default(self):
        b = sb.build_board("claude-t1", now=T0 + 600)        # SPRINTS_DIR unset
        self.assertEqual(b["sprints"], [])
        self.assertFalse([i for i in b["items"] if i["id"].startswith(("s:", "m:"))])
        # the sprint's own agent is then an ordinary agent row
        self.assertIn("a:aone111", self.by_id(b))

    def test_sprints_dir_from_config(self):
        sb.SPRINTS_DIR = self.sprints
        b = sb.build_board("claude-t1", now=T0 + 600)
        self.assertEqual([s["id"] for s in b["sprints"]], ["2026-10-31-test"])

    def test_without_names_registry_the_short_id_is_shown(self):
        sb.NAMES_DIR = None
        self.assertEqual(sb.session_name(SID), SID[:8])
        self.assertEqual(sb.resolve_session(SID[:8])[0], SID)
        with self.assertRaises(SystemExit):
            sb.resolve_session("claude-t1")
        self.assertEqual(sb.build_board(SID, now=T0 + 600)["session"], SID[:8])

    def test_sprint_ref_matches_the_dirs_last_two_parts(self):
        r = sb.sprint_ref_re("/a/b/proj/sprints")
        self.assertEqual(r.findall("see ~/x/proj/sprints/2026-10-31-x/SPRINT.md"), ["2026-10-31-x"])
        self.assertEqual(r.findall("other/sprints/2026-10-31-x"), [])
        self.assertIsNone(sb.sprint_ref_re(None))

    def test_cli_note_requires_fields(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID
        try:
            with self.assertRaises(SystemExit):
                sb.main(["note", "--kind", "topic", "--topic", "x"])
            self.assertEqual(sb.main(["note", "--kind", "ask", "--id", "7", "--text", "Pick a region"]), 0)
        finally:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        self.assertEqual(sb.read_ledger(SID)[-1]["id"], "7")


if __name__ == "__main__":
    unittest.main()
