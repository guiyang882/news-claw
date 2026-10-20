"""Bounded, text-only OpenCode pilot; normal CLI, no alternate endpoint or fallback."""
from datetime import datetime
import json
import os
from zoneinfo import ZoneInfo

FREE_MODEL = "opencode/deepseek-v4.1-flash-free"


def invocation(settings, prompt, schema):
    if settings["model"] != FREE_MODEL:
        raise ValueError("OpenCode pilot only permits the explicitly evaluated free model")
    prompt += "\nOUTPUT_CONTRACT_JSON_SCHEMA\n" + json.dumps(schema, ensure_ascii=False)
    prompt += "\nReturn exactly one complete JSON object matching this schema. No Markdown fences or commentary."
    if len(prompt.encode()) > 120_000:
        raise ValueError("OpenCode writer input exceeds the pilot budget")
    env = os.environ.copy()
    # Use the standard agent and existing runtime, not --pure or a custom system prompt.
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({
        "model": FREE_MODEL, "small_model": FREE_MODEL,
        "enabled_providers": ["opencode"], "autoupdate": False, "share": "disabled",
        "permission": {"*": "deny"},
        "agent": {"title": {"disable": True}, "summary": {"disable": True},
                  "compaction": {"disable": True}},
    })
    env["OPENCODE_PERMISSION"] = '{"*":"deny"}'
    return ([settings["executable"], "run", "--model", FREE_MODEL, "--agent", "build",
             "--format", "json", "--title", "Reviewed AI products summary"],
            env, prompt.encode())


def reserve(settings, policy, models):
    """Called under the provider lock; reserve even failed/aborted attempts."""
    cap = settings.get("max_calls_per_day")
    if type(cap) is not int or not 1 <= cap <= 3:
        raise ValueError("OpenCode pilot requires a daily cap between one and three")
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    path = policy / "opencode-usage.json"
    state = models.read_json(path) if path.exists() else {}
    count = state.get("calls", 0) if state.get("day") == stamp else 0
    if count >= cap:
        raise ValueError("OpenCode daily invocation budget exhausted")
    # A persistent timestamp also spaces calls from separate runs.
    last = datetime.fromisoformat(state["reserved_at"]).timestamp() if state.get("reserved_at") else 0
    models.time.sleep(max(0, 10 - (models.time.time() - last)))
    models.atomic_json(path, {"day": stamp, "calls": count + 1, "reserved_at": models.now()})


def parse_events(raw, call):
    """Only a complete single text turn can pass; CLI exit 0 alone is insufficient."""
    chunks, finishes, sessions = [], [], set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise ValueError("Malformed OpenCode event stream") from None
        if not isinstance(event, dict):
            raise ValueError("Malformed OpenCode event")
        kind = event.get("type")
        if event.get("sessionID"):
            sessions.add(event["sessionID"])
        if kind == "error":
            error = event.get("error", {})
            data = error.get("data", {}) if isinstance(error, dict) else {}
            status = data.get("statusCode")
            if status in (401, 403, 429) or "FreeTierError" in json.dumps(error):
                call["failure_kind"] = "provider_denied"
                raise PermissionError("OpenCode access or quota denied")
            call["failure_kind"] = "provider_error"
            raise RuntimeError("OpenCode reported an error; see private stage logs")
        part = event.get("part", {})
        if not isinstance(part, dict):
            raise ValueError("Malformed OpenCode event part")
        if kind == "tool_use" or part.get("type") == "tool":
            raise ValueError("Text-only OpenCode stage attempted a tool action")
        if kind == "text":
            if not isinstance(part.get("text"), str):
                raise ValueError("Invalid OpenCode text")
            chunks.append(part["text"])
        elif kind == "step_finish":
            finishes.append(part)
            call["usage"] = part.get("tokens", {})
            call["reported_cost"] = part.get("cost")
        elif kind not in {"step_start", "reasoning"}:
            raise ValueError("Unexpected OpenCode event type")
    if len(sessions) != 1 or len(finishes) != 1 or finishes[0].get("reason") != "stop":
        raise ValueError("OpenCode response incomplete or multiple model turns detected")
    call["session_id"] = next(iter(sessions))
    if call.get("reported_cost") != 0:
        raise PermissionError("OpenCode free pilot reported a nonzero or missing cost")
    text = "".join(chunks).strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    try:
        result = json.loads(text)
    except ValueError:
        raise ValueError("OpenCode did not return complete JSON") from None
    if not isinstance(result, dict):
        raise ValueError("OpenCode response is not a JSON object")
    return result
