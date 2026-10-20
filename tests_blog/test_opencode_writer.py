import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from workflows import daily_blog as models
from workflows import opencode_writer as writer


def events(text='{"ok":true}', reason="stop", cost=0):
    return "\n".join(json.dumps(e) for e in [
        {"type": "step_start", "sessionID": "test", "part": {}},
        {"type": "text", "sessionID": "test", "part": {"text": text}},
        {"type": "step_finish", "sessionID": "test",
         "part": {"reason": reason, "cost": cost, "tokens": {"input": 12, "output": 4}}},
    ])


class OpenCodeWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schema = self.root / "schema.json"
        self.schema.write_text('{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":false}')
        self.config = {"workflow": {
            "writer_provider": "opencode",
            "writer": {"executable": "opencode", "model": writer.FREE_MODEL,
                       "timeout_seconds": 10, "max_calls_per_day": 3, "permissions": "full"},
            "reviewer": {"executable": "codex", "model": "review-model", "service_tier": "default",
                         "timeout_seconds": 10},
            "min_model_interval_seconds": 0,
            "transient_retry": {"max_retries": 1},
            "network_policy": {"max_cli_invocations_per_run": 4},
        }}

    def run_fake(self, raw, code=0, stage="draft"):
        runner = models.ModelRunner(self.config, self.root)
        def start(command, **kw):
            kw["stdout"].write(raw.encode())
            kw["stdout"].flush()
            return Mock(returncode=code, poll=lambda: code)
        with patch.object(models.subprocess, "Popen", side_effect=start) as process:
            result = runner(stage, "Cached public evidence", self.schema, self.root / "stage")
        return runner, result, process

    def test_complete_free_response_and_usage(self):
        runner, result, process = self.run_fake(events())
        self.assertEqual(result, {"ok": True})
        self.assertEqual(runner.calls[0]["reported_cost"], 0)
        self.assertEqual(runner.calls[0]["usage"]["output"], 4)
        command = process.call_args.args[0]
        self.assertNotIn("--pure", command)
        self.assertEqual(command[command.index("--model") + 1], writer.FREE_MODEL)
        self.assertEqual(process.call_args.kwargs["env"]["OPENCODE_PERMISSION"], '{"*":"allow"}')
        self.assertIn("--auto", command)
        self.assertEqual(command[command.index("--dir") + 1], str(self.root / "stage"))
        self.assertEqual(process.call_args.kwargs["env"]["PWD"], str(self.root / "stage"))
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_incomplete_truncated_non_json_or_multiple_turns_rejected(self):
        for raw in (events(reason="length"), events(text='{"ok":'), events() + "\n" + events(),
                    '{"type":"text","sessionID":"t","part":{"text":"{}"}}', "not json"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    writer.parse_events(raw, {})

    def test_tool_rounds_parse_final_json_and_sum_usage(self):
        tool = json.dumps({"type": "tool_use", "sessionID": "test", "part": {
            "type": "tool", "tool": "bash", "state": {"status": "completed"}}})
        first = events(text="I will inspect the file.", reason="tool-calls").splitlines()
        first.insert(2, tool)
        raw = "\n".join(first) + "\n" + events()
        call = {}
        self.assertEqual(writer.parse_events(raw, call), {"ok": True})
        self.assertEqual(call["usage"], {"input": 24, "output": 8})
        self.assertEqual(call["model_steps"], 2)
        self.assertEqual(call["tool_calls"], [{"tool": "bash", "status": "completed"}])
        self.assertEqual(writer.parse_events(raw.replace('"completed"', '"error"'), {}), {"ok": True})
        for status in ("running", "pending"):
            with self.assertRaisesRegex(ValueError, "tool action incomplete"):
                writer.parse_events(raw.replace('"completed"', json.dumps(status)), {})
        with self.assertRaises(PermissionError):
            writer.parse_events(raw.replace('"cost": 0', '"cost": 0.1', 1), {})
        with self.assertRaises(ValueError):
            writer.parse_events("\n".join(first), {})

    def test_permissions_are_explicit_and_native(self):
        settings = self.config["workflow"]["writer"]
        command, env, _ = writer.invocation(settings, "test", {}, directory=self.root)
        config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(config["permission"], {"*": "allow"})
        self.assertEqual(config["agent"]["build"]["permission"], {"*": "allow"})
        for permission in (None, "ask", "deny", "ful"):
            with self.assertRaisesRegex(ValueError, "explicit full"):
                writer.invocation({**settings, "permissions": permission}, "test", {}, directory=self.root)

    def test_denial_even_with_exit_zero_opens_circuit(self):
        for code in (401, 403, 429):
            raw = json.dumps({"type": "error", "error": {"data": {"statusCode": code}}})
            with self.assertRaises(PermissionError):
                self.run_fake(raw)
            blocked = self.root / "data/runs/blog-provider-policy/opencode.blocked.json"
            self.assertTrue(blocked.is_file())
            runner = models.ModelRunner(self.config, self.root)
            with patch.object(models.subprocess, "Popen") as process:
                with self.assertRaises(PermissionError):
                    runner("draft", "x", self.schema, self.root / "again")
                process.assert_not_called()
            blocked.unlink()

    def test_cost_or_model_cannot_silently_switch_to_paid(self):
        with self.assertRaises(PermissionError):
            writer.parse_events(events(cost=0.1), {})
        settings = {**self.config["workflow"]["writer"], "model": "opencode/deepseek-v4.1-flash"}
        with self.assertRaises(ValueError):
            writer.invocation(settings, "test", {}, directory=self.root)

    def test_schema_failure_is_not_accepted_or_retried(self):
        with self.assertRaises(ValueError):
            self.run_fake(events(text='{"ok":"wrong type"}'))
        self.assertFalse((self.root / "stage/response.json").exists())
        self.assertEqual(models.read_json(self.root / "stage/call.json")["status"], "failed")
        self.assertFalse((self.root / "stage/retry-1").exists())

    def test_persisted_daily_cap_applies_across_runner_instances(self):
        settings = {**self.config["workflow"]["writer"], "max_calls_per_day": 1}
        policy = self.root / "policy"
        writer.reserve(settings, policy, models)
        with self.assertRaisesRegex(ValueError, "daily invocation"):
            writer.reserve(settings, policy, models)
        state = models.read_json(policy / "opencode-usage.json")
        state["day"] = "2000-01-01"
        state["reserved_at"] = "2000-01-01T00:00:00+00:00"
        models.atomic_json(policy / "opencode-usage.json", state)
        writer.reserve(settings, policy, models)

    def test_nonzero_exit_never_accepts_valid_text(self):
        with self.assertRaises(RuntimeError):
            self.run_fake(events(), code=1)
        self.assertFalse((self.root / "stage/response.json").exists())

    def test_timeout_is_counted_without_retry(self):
        process = Mock(returncode=None, poll=lambda: 0)
        process.communicate.side_effect = models.subprocess.TimeoutExpired("opencode", 10)
        runner = models.ModelRunner(self.config, self.root)
        with patch.object(models.subprocess, "Popen", return_value=process) as start:
            with self.assertRaises(RuntimeError):
                runner("draft", "test", self.schema, self.root / "stage")
            self.assertEqual(start.call_count, 1)
        self.assertEqual(runner.calls[0]["failure_kind"], "local_process_timeout")

    def test_reviewer_still_uses_codex(self):
        runner = models.ModelRunner(self.config, self.root)
        def start(command, **kw):
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok":true}')
            return Mock(returncode=0, poll=lambda: 0)
        with patch.object(models.subprocess, "Popen", side_effect=start) as process:
            runner("review", "test", self.schema, self.root / "review")
        self.assertEqual(process.call_args.args[0][0], "codex")


if __name__ == "__main__":
    unittest.main()
