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
        self._saved = (sb.PROJECTS, sb.BOARD_DIR, sb.NAMES_DIR, sb.SPRINTS_DIR, sb.USER_AGENTS_DIR)
        self.user_agents = os.path.join(root, "home-agents")
        os.makedirs(self.user_agents)
        sb.USER_AGENTS_DIR = self.user_agents
        sb.PROJECTS = os.path.join(root, "projects")
        sb.BOARD_DIR = os.path.join(root, "board")
        sb.NAMES_DIR = os.path.join(root, "names")
        sb.SPRINTS_DIR = None   # each board() call names the sprints dir; the default stays off
        os.makedirs(sb.NAMES_DIR)
        put(os.path.join(sb.NAMES_DIR, SID + ".json"), json.dumps({"session_id": SID, "session_name": "claude-t1"}))
        self._write_sprint()
        self._write_transcript()

    def tearDown(self):
        sb.PROJECTS, sb.BOARD_DIR, sb.NAMES_DIR, sb.SPRINTS_DIR, sb.USER_AGENTS_DIR = self._saved
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
            asst(60, {"type": "text", "text": "Three decisions need you (agree or disagree each):\n"
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

    def _append(self, *rows):
        with open(os.path.join(self.projects, SID + ".jsonl"), "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_option_lists_are_not_asks(self):
        self._append(asst(200, {"type": "text", "text": "Which way? Your call:\n"
                                "1. **Skip the password:** one-time unlock.\n"
                                "2. **Reset it:** I redeploy."}))
        items = self.by_id(self.board())
        # the new list has no agree/disagree marker: #1/#2 stay the old reply's asks
        self.assertNotIn("Skip the password", items["#1"]["title"])
        self.assertNotIn("Reset it", items["#2"]["title"])

    def test_explicit_decision_forms_and_answers(self):
        self._append(
            dict(asst(200, {"type": "text", "text": "Two asks.\n\n"
                       "> **#7 — agree/disagree:** Push the repo. If you disagree, we keep it local.\n"
                       "**#8 - agree/disagree**: Send the **PDF** to Sam.\n"
                       "#9 agree/disagree: Use `option 1` first.\n"
                       "#10 — Agree or disagree: Rename the board.\n"
                       "#11 agree/disagree: Name guard on the release notes page.\n"
                       "1. **Pick one:** a plain list in the same reply is not inferred.\n"}), uuid="x"),
            dict(asst(210, {"type": "text", "text": "Reminder:\n> **#7 — agree/disagree:** Push the repo to GitHub. Default is to wait."}), uuid="y"),
            prompt(300, "7 agree, 8 disagree\nrandom words"),
            prompt(310, "re #9 (Use option 1 first): agree\nthanks"),
            prompt(320, "#10 sure, rename it"),
            prompt(330, "release notes agree"),
        )
        items = self.by_id(self.board())
        self.assertEqual(items["#7"]["title"], "Push the repo to GitHub.")   # later definition replaces
        self.assertEqual(items["#7"]["state"], "done")
        self.assertEqual(items["#7"]["verdict"], "agree")
        self.assertRegex(items["#7"]["note"], r"^answered \d\d:\d\d: agree$")
        self.assertEqual(items["#8"]["verdict"], "disagree")
        self.assertEqual(items["#8"]["title"], "Send the PDF to Sam.")
        self.assertEqual(items["#9"]["title"], "Use option 1 first.")
        self.assertEqual(items["#9"]["verdict"], "agree")
        self.assertEqual(items["#10"]["state"], "done")
        self.assertEqual(items["#10"]["verdict"], "answered")
        self.assertEqual(items["#11"]["state"], "done")                    # matched by words
        self.assertNotIn("inferred", items["#7"])
        self.assertEqual(items["#7"]["anchor"], "y")      # the replacing message
        self.assertEqual(items["#8"]["anchor"], "x")
        self.assertNotIn("a plain list", " ".join(i["title"] for i in items.values()))

    def _agent(self, n, off, cwd=None, result_extra=None, **inp):
        """An async Agent call + its result, returned as rows (cwd stamped on the call's record)."""
        call = asst(off, use(f"tu_m{n}", "Agent", description=f"model probe {n}", run_in_background=True,
                             prompt="x", **inp))
        if cwd:
            call["cwd"] = cwd
        return [call, result(off + 1, f"tu_m{n}", {"agentId": f"a{n:02d}xxxxxxxxx", "isAsync": True,
                                                    **(result_extra or {})})]

    def _def(self, root, name, body):
        os.makedirs(root, exist_ok=True)
        put(os.path.join(root, name + ".md"), body)

    def test_agent_model_and_effort_sources(self):
        proj = os.path.join(self.tmp.name, "proj")
        self._def(self.user_agents, "builder", '---\nname: builder\nmodel: "sonnet"\neffort: medium  # cheap\n---\nbody\n')
        self._def(self.user_agents, "plain", "---\nname: plain\neffort: high\n---\n")
        self._def(self.user_agents, "inheriting", "---\nname: inheriting\nmodel: inherit\n---\n")
        self._def(self.user_agents, "shadowed", "---\nmodel: opus\n---\n")
        self._def(self.user_agents, "longdesc", "---\ndescription: " + "x" * 9000 + "\nmodel: haiku\neffort: low\n---\n")
        self._def(self.user_agents, "huge", "---\ndescription: " + "x" * 70000 + "\nmodel: haiku\n---\n")
        self._def(os.path.join(proj, ".claude", "agents"), "shadowed", "---\nmodel: haiku\neffort: low\n---\n")
        self._append(
            *self._agent(1, 300, model="opus", subagent_type="builder"),                 # the call wins
            *self._agent(2, 310, subagent_type="builder"),                              # definition
            *self._agent(3, 320, subagent_type="plain"),                                # effort only: inherits
            *self._agent(4, 330, subagent_type="inheriting"),
            *self._agent(6, 340, subagent_type="shadowed"),                             # no project: user def
            *self._agent(5, 350, cwd=os.path.join(proj, "sub"), subagent_type="shadowed"),  # project wins
            *self._agent(11, 395, subagent_type="longdesc"),                            # model past 4 KB
            *self._agent(12, 396, subagent_type="huge"),                               # unreadable: unknown
            *self._agent(7, 360),                                                       # no type: inherits
            *self._agent(8, 370, subagent_type="Explore"),                              # unknown: omitted
            *self._agent(9, 380, subagent_type="../etc/passwd"),                        # never a path
            *self._agent(10, 390, subagent_type="builder", result_extra={"resolvedModel": "claude-sonnet-5-5"}),
        )
        os.makedirs(os.path.join(proj, "sub"))
        items = self.by_id(self.board())
        got = lambda n: {k: items[f"a:a{n:02d}xxxx"].get(k) for k in ("model", "effort", "model_source")}
        self.assertEqual(got(1), {"model": "opus", "effort": "medium", "model_source": "call"})
        self.assertEqual(got(2), {"model": "sonnet", "effort": "medium", "model_source": "definition"})
        self.assertEqual(got(3), {"model": "inherits", "effort": "high", "model_source": "inherits"})
        self.assertEqual(got(4), {"model": "inherits", "effort": None, "model_source": "inherits"})
        self.assertEqual(got(5), {"model": "haiku", "effort": "low", "model_source": "definition"})
        self.assertEqual(got(6), {"model": "opus", "effort": None, "model_source": "definition"})
        self.assertEqual(got(7), {"model": "inherits", "effort": None, "model_source": "inherits"})
        self.assertEqual(got(11), {"model": "haiku", "effort": "low", "model_source": "definition"})
        self.assertEqual(got(12), {"model": None, "effort": None, "model_source": None})
        self.assertEqual(got(8), {"model": None, "effort": None, "model_source": None})
        self.assertEqual(got(9), {"model": None, "effort": None, "model_source": None})
        self.assertEqual(items["a:a10xxxx"]["resolved_model"], "claude-sonnet-5-5")
        text = sb.render_text(self.board())
        self.assertIn("· sonnet/medium", text)
        d = sb.detail(self.board(), "a:a02xxxx")
        self.assertIn("model sonnet", d["lines"][1])
        self.assertIn("effort medium", d["lines"][1])

    def _decisions(self, extra=()):
        self._append(
            asst(200, {"type": "text", "text": "Decisions:\n#14 agree/disagree: Fourteen.\n"
                       "#15 agree/disagree: Fifteen.\n#16 agree/disagree: Sixteen.\n"
                       "#17 agree/disagree: Seventeen.\n#18 agree/disagree: Eighteen.\n"
                       "#19 agree/disagree: Nineteen.\n#20 agree/disagree: Twenty.\n"
                       "#21 agree/disagree: Twenty-one.\n"}),
            *extra)
        return self.by_id(self.board())

    def _states(self, items, nums):
        return {n: (items[f"#{n}"]["state"], items[f"#{n}"].get("verdict")) for n in nums}

    def test_answer_ranges_and_lists_in_either_order(self):
        for text, want in [
            ("agree 17-20", {17: "agree", 18: "agree", 19: "agree", 20: "agree", 21: None}),
            ("17-20 agree", {17: "agree", 20: "agree", 21: None}),
            ("17\u201320 agree", {17: "agree", 20: "agree", 21: None}),     # en dash
            ("agree 17, 18 and 20", {17: "agree", 18: "agree", 19: None, 20: "agree"}),
            ("17, 18 and 20 agree", {17: "agree", 18: "agree", 19: None, 20: "agree"}),
            ("17-20 yes", {17: "agree", 20: "agree", 21: None}),
            ("yes 14", {14: "agree", 15: None}),
            ("14 yes", {14: "agree", 15: None}),
            ("disagree 15-16", {14: None, 15: "disagree", 16: "disagree", 17: None}),
            ("no 16", {16: "disagree", 17: None}),
        ]:
            with self.subTest(text=text):
                self.setUp()
                try:
                    items = self._decisions([prompt(300, text)])
                    for n, verdict in want.items():
                        st = items[f"#{n}"]
                        if verdict is None:
                            self.assertEqual(st["state"], "waiting", (text, n))
                        else:
                            self.assertEqual((st["state"], st["verdict"]), ("done", verdict), (text, n))
                finally:
                    self.tearDown()

    def test_range_does_not_answer_numbers_that_are_not_open_asks(self):
        items = self._decisions([prompt(300, "agree 1-30"), prompt(310, "yes 14 minutes later")])
        self.assertEqual(items["#14"]["verdict"], "agree")        # open, inside 1-30
        self.assertNotIn("#25", items)                             # nothing invented for the rest

    def test_agree_on_all_resolves_the_listed_asks_only_right_after_the_reply(self):
        for text in ("agree on all", "all agree", "agree all", "yes to all", "Agree on all."):
            with self.subTest(text=text):
                self.setUp()
                try:
                    items = self._decisions([prompt(300, text)])
                    self.assertEqual({items[f"#{n}"]["state"] for n in range(14, 22)},
                                     {"done"})
                    self.assertEqual(items["#17"]["verdict"], "agree")
                finally:
                    self.tearDown()
        # not "immediately after": an assistant reply sits between the listing and the prompt
        self.setUp()
        items = self._decisions([asst(250, {"type": "text", "text": "Anything else? Standing by."}),
                                 prompt(300, "agree on all")])
        self.assertEqual(items["#17"]["state"], "waiting")
        self.tearDown()
        # and not the asks of an older listing: only the latest listing reply's asks are resolved
        self.setUp()
        try:
            items = self._decisions([asst(400, {"type": "text", "text": "More:\n#30 agree/disagree: Thirty.\n"}),
                                     prompt(410, "all agree")])
            self.assertEqual(items["#30"]["verdict"], "agree")
            self.assertEqual(items["#17"]["state"], "waiting")
        finally:
            self.tearDown()
        # with no listed asks open, "all agree" answers nothing
        self.setUp()
        try:
            self._append(prompt(300, "all agree"))
            self.assertEqual([i for i in self.board()["items"] if i.get("decision")], [])
        finally:
            self.tearDown()

    def test_decision_edge_cases(self):
        self._append(
            asst(200, {"type": "text", "text": "**#7** — agree/disagree: Bold number form.\n"
                       "#8 agree/disagree: Rename the Release Notes page.\n"
                       "#9 agree/disagree: Other thing that mentions also.\n"
                       "#10 agree/disagree: Third.\n"}),
            prompt(300, "re #7 (Bold number form): go with the second one"),
            prompt(310, "I also agree"),
            prompt(320, '<pasted_content id="1">\nlog\n</pasted_content>\nwhat does this mean?'),
            prompt(330, "1 agree, 2 agree, release notes agree"),
            asst(400, {"type": "text", "text": "> **#10 — agree:** done, pushed."}))
        b = self.board()
        items = self.by_id(b)
        self.assertEqual(items["#7"]["state"], "done")                      # a typed reply answers it
        self.assertEqual(items["#7"]["verdict"], "answered")
        self.assertEqual(items["#8"]["state"], "done")                      # "release notes agree"
        self.assertEqual(items["#9"]["state"], "waiting")                   # "I also agree" names nothing
        self.assertEqual(items["#10"]["title"], "Third.")                   # a bare "agree:" is not a decision
        self.assertIn("what does this mean?", [i["title"] for i in b["items"] if i["state"] == "asked"])

    def test_pending_items_optional_source(self):
        src = os.path.join(self.tmp.name, "pending.json")
        put(src, json.dumps([
            {"id": "abcdef1234567", "kind": "handoff", "producer": "codex", "received_at": "2026-11-02T20:00:00Z",
             "review": "tool show abcdef12"},
            {"id": "99887766aaaa", "kind": "note", "producer": "othertool", "flags": ["shell-cmd"]},
            {"kind": "no-id"}]))
        self.assertNotIn("b:abcdef12", self.by_id(self.board()))           # off by default
        os.environ["SESSION_BOARD_PENDING"] = src
        try:
            b = self.board()
            items = self.by_id(b)
            self.assertEqual(items["b:abcdef12"]["state"], "waiting")
            self.assertEqual(items["b:abcdef12"]["title"], "handoff from codex waiting for review")
            self.assertEqual(items["b:99887766"]["state"], "blocked")      # flagged
            d = sb.detail(b, "b:99887766")
            self.assertIn("shell-cmd", " ".join(d["lines"]))
            self.assertIn("review: tool show abcdef12", " ".join(sb.detail(b, "b:abcdef12")["lines"]))
            os.environ["SESSION_BOARD_PENDING"] = "echo '[{\"id\": \"cccccccc1\", \"kind\": \"x\"}]'"
            self.assertIn("b:cccccccc", self.by_id(self.board()))          # a command works too
            os.environ["SESSION_BOARD_PENDING"] = "exit 3"
            self.assertNotIn("b:cccccccc", self.by_id(self.board()))       # a failing source shows nothing
        finally:
            os.environ.pop("SESSION_BOARD_PENDING", None)

    def test_reused_decision_number_reopens_and_unanswered_waits(self):
        self._append(asst(200, {"type": "text", "text": "> **#7 — agree/disagree:** First."}),
                     prompt(300, "7 agree"),
                     asst(400, {"type": "text", "text": "> **#7 — agree/disagree:** Second, a new question."}),
                     asst(410, {"type": "text", "text": "> **#8 — agree/disagree:** Never answered."}),
                     prompt(420, "no idea what 8 is, so no answer"))
        items = self.by_id(self.board())
        self.assertEqual(items["#7"]["state"], "waiting")
        self.assertEqual(items["#7"]["title"], "Second, a new question.")
        self.assertEqual(items["#8"]["state"], "waiting")

    def test_ledger_ask_supersedes_a_derived_decision(self):
        self._append(asst(200, {"type": "text", "text": "> **#7 — agree/disagree:** Derived."}))
        sb.append_ledger(SID, {"kind": "ask", "id": "7", "text": "Ledger version", "topic": "x"})
        items = [i for i in self.board()["items"] if i["id"] == "#7"]
        self.assertEqual([i["title"] for i in items], ["Ledger version"])

    def test_you_asked_list(self):
        self._append(
            prompt(500, "what is blocked?\nsecond line"),
            asst(501, {"type": "text", "text": "\nTwo agents are running.\nDetails below."}),
            prompt(510, 'look at this\n\n<pasted_content id="1">\nbig paste\n</pasted_content>'),
            {"type": "attachment", "timestamp": iso(520), "uuid": "q-1",
             "attachment": {"type": "queued_command", "prompt": "queued while busy", "origin": {"kind": "human"},
                            "source_uuid": "src-1"}},
            {"type": "queue-operation", "operation": "enqueue", "timestamp": iso(519), "content": "queued while busy"},
            {"type": "attachment", "timestamp": iso(530),
             "attachment": {"type": "queued_command", "prompt": notif("bxyz2", "completed", "x")}},
            {"type": "attachment", "timestamp": iso(531),
             "attachment": {"type": "queued_command", "prompt": "<system-reminder>x</system-reminder>"}},
            {"type": "user", "timestamp": iso(540), "isMeta": True, "message": {"content": "meta text"}})
        b = self.board()
        asked = [i for i in b["items"] if i["state"] == "asked"]
        titles = [i["title"] for i in asked]
        self.assertEqual(titles[:3], ["queued while busy", "look at this", "what is blocked?"])  # newest first
        self.assertEqual(titles.count("queued while busy"), 1)
        self.assertNotIn("big paste", " ".join(titles))
        self.assertEqual(b["counts"]["asked"], len(asked))
        top = asked[2]
        self.assertEqual(top["kind"], "question")
        self.assertEqual(top["reply"], "Two agents are running.")
        self.assertTrue(top["anchor"] is None or top["anchor"])
        self.assertEqual(asked[0]["anchor"], "q-1")
        self.assertEqual(asked[0]["anchor_alt"], "src-1")
        # no notification text, no meta rows
        self.assertFalse(any("task-notification" in i["title"] or i["title"] == "meta text" for i in asked))
        d = sb.detail(b, top["id"])
        self.assertIn("second line", " ".join(d["lines"]))
        self.assertIn("Two agents are running.", " ".join(d["lines"]))
        self.assertIn("YOU ASKED", sb.render_text(b))

    def test_you_asked_is_capped(self):
        self._append(*[prompt(600 + n, f"question {n}") for n in range(sb.ASKED_MAX + 8)])
        asked = [i for i in self.board()["items"] if i["state"] == "asked"]
        self.assertEqual(len(asked), sb.ASKED_MAX)
        self.assertEqual(asked[0]["title"], f"question {sb.ASKED_MAX + 7}")

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
