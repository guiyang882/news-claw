"""Review and atomically replace a published article at the user's request."""

import argparse
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
from zoneinfo import ZoneInfo

from . import daily_blog as blog
from . import blog_presentation as presentation


def replace_publication(draft, packet, verdict, previous, prior_proof, site, run_id, skill_hash):
    from web.blog_runtime import load_runtime_articles, validate_article
    from web.blog import _ARTICLES
    blog.require_verdict(verdict, draft, packet, final=True)
    if not re.fullmatch(r"[a-f0-9]{64}", skill_hash):
        raise ValueError("Humanizer skill snapshot digest is missing")
    with blog.locked(site / "publish.lock"):
        current = list(load_runtime_articles(site))
        old = next((item for item in current if item["slug"] == previous["slug"]), None)
        if old is None or blog.digest(old) != blog.digest(previous):
            raise ValueError("Published article changed while awaiting review")
        slug = draft["article"]["slug"]
        if any(item["slug"] == slug and item["slug"] != old["slug"] for item in (*current, *_ARTICLES)):
            raise ValueError("Revised topic slug is already in use")
        owner = (site.stat().st_uid, site.stat().st_gid)
        metadata = deepcopy(draft["article"])
        metadata["aliases"] = list(dict.fromkeys([*old.get("aliases", []), old["slug"]])) if slug != old["slug"] else old.get("aliases", [])
        for localized in (metadata, metadata["en"]):
            raw = localized.pop("body_markdown").encode()
            name = hashlib.sha256(raw).hexdigest() + ".md"
            destination = site / "articles" / name
            if destination.exists() and destination.read_bytes() != raw:
                raise ValueError("Content-addressed article mismatch")
            blog.atomic_bytes(destination, raw, site_owner=owner)
            localized["source"] = "runtime:" + name
        metadata["sources"] = draft["sources"]
        metadata["media"] = draft.get("media", [])
        metadata["automation"] = {**draft["automation"], "run_id": run_id, "approval_kind": "model_review",
            "publication_kind": "revision", "draft_sha256": blog.digest(draft), "packet_sha256": blog.digest(packet),
            "humanizer_skill_sha256": skill_hash, "final_verdict_sha256": blog.digest(verdict)}
        validate_article(metadata, site)
        aliases = set(metadata["aliases"])
        if any(aliases.intersection({item["slug"], *item.get("aliases", [])}) for item in (*current, *_ARTICLES) if item["slug"] != old["slug"]):
            raise ValueError("Revised aliases collide with another article")
        proof = {"draft": draft, "packet": packet, "final_review": verdict, "skill_sha256": skill_hash,
                 "prior_publication": prior_proof, "run_id": run_id, "published_at": blog.now(),
                 "revision_kind": "user_requested_presentation_update"}
        # Retain prior metadata and proof even when an existing topic URL is revised again.
        history = site / "revisions"
        history.mkdir(exist_ok=True)
        if os.geteuid() == 0:
            os.chown(history, *owner)
        os.chmod(history, 0o750)
        blog.atomic_json(history / (old["slug"] + "-" + blog.digest(prior_proof)[:16] + ".json"),
                         {"article": old, "proof": prior_proof}, site_owner=owner)
        blog.atomic_json(site / "automation-reviews" / (slug + ".json"), proof, site_owner=owner)
        manifest = {"version": 1, "articles": [metadata if item["slug"] == old["slug"] else item for item in current]}
        blog.atomic_json(site / "manifest.json", manifest, site_owner=owner)
    return {"success": True, "business_status": "published", "publication_kind": "revision", "slug": slug,
            "previous_slug": old["slug"], "day": metadata["published_at"], "article_sha256": blog.digest(draft),
            "packet_sha256": blog.digest(packet), "humanizer_skill_sha256": skill_hash,
            "reading_estimates": draft["automation"]["reading_estimates"]}


def run(config, root, db, directory, slug, staged_path):
    settings = config["workflow"]
    sys.path.insert(0, settings["website_repo"])
    from web.blog_runtime import load_runtime_articles
    site = Path(settings["website_state"])
    current = next((item for item in load_runtime_articles(site) if item["slug"] == slug), None)
    if current is None:
        raise ValueError("Published article is missing")
    previous = blog.read_json(site / "automation-reviews" / (slug + ".json"))
    if current.get("automation", {}).get("draft_sha256") != blog.digest(previous["draft"]):
        raise ValueError("Publication proof does not match the active article")
    packet = deepcopy(previous["packet"])
    packet["approved_media"] = presentation.load_media(config, root)
    staged = blog.read_json(staged_path)
    day = date.fromisoformat(current["published_at"])
    draft = blog.build_draft(staged["model_draft"], packet, config, day,
                             plan=previous["draft"]["editorial_plan"], humanized=True)
    topic = staged["topic_slug"]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", topic) or len(topic) > 80:
        raise ValueError("Revision needs a short ASCII topic slug")
    draft["article"]["slug"] = topic + "-" + day.isoformat()
    draft["article"]["updated_at"] = datetime.now(ZoneInfo(config["timezone"])).date().isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    blog.atomic_json(directory / "source-packet.json", packet)
    blog.atomic_json(directory / "final-draft.json", draft)
    skill = Path(settings["humanizer_skill"]).read_text()
    skill_hash = hashlib.sha256(skill.encode()).hexdigest()
    blog.atomic_bytes(directory / "humanizer-SKILL.md", skill.encode())
    # This explicit post-publication edit has one review, separate from daily writing attempts.
    review_config = deepcopy(config)
    review_config["workflow"]["network_policy"]["max_cli_invocations_per_day"] = 1
    runner = blog.ModelRunner(review_config, root)
    prompt = ("This is a user-requested revision of an already published article. "
              "The requested changes remove internal process/model credits, add licensed historical imagery, "
              "evidence-preserving tables and conceptual diagrams, restrained emphasis, references, and a topic URL. "
              "Removing process notes is expected, not a lost company fact. Diagrams must label analytical relationships "
              "and uncertainty; do not turn arrows into established payment or engineering schedules. "
              + blog.review_prompt(draft, packet, original=previous["draft"], skill=skill))
    verdict = runner("revision_review", prompt, blog.SCHEMAS / "daily-blog-verdict.schema.json", directory / "codex-revision-review")
    blog.require_verdict(verdict, draft, packet, final=True)
    result = replace_publication(draft, packet, verdict, current, previous, site,
                                 os.environ["NEWS_CLAW_RUN_ID"], skill_hash)
    result["url"] = settings["public_base_url"].rstrip("/") + "/blog/" + result["slug"]
    result["model_calls"] = runner.calls
    blog.atomic_json(directory / "publication.json", result)
    try:
        blog.record_publication(root, db, result, draft, packet)
    except (OSError, sqlite3.Error) as error:
        result["knowledge_index_error"] = str(error)
        blog.atomic_json(directory / "publication.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--draft", type=Path, required=True)
    args = parser.parse_args()
    root = Path(os.environ["NEWS_CLAW_ROOT"]).resolve()
    db = Path(os.environ["NEWS_CLAW_DB"]).resolve()
    config = blog.read_json(Path(os.environ["NEWS_CLAW_TASK_CONFIG_PATH"]))
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        active = connection.execute("SELECT metadata_json FROM task_runs WHERE id=? AND task_id=? AND status='running'",
                                    (os.environ["NEWS_CLAW_RUN_ID"], os.environ["NEWS_CLAW_TASK_ID"])).fetchone()
    if not active or json.loads(active[0]).get("trigger") != "manual":
        parser.error("Revision requires an explicitly queued manual engine run")
    directory = Path(os.environ["NEWS_CLAW_RESULT_PATH"]).parent
    signal.signal(signal.SIGTERM, blog.terminate_model)
    signal.signal(signal.SIGINT, blog.terminate_model)
    try:
        result = run(config, root, db, directory, args.slug, args.draft.resolve())
    except Exception as error:
        result = {"success": False, "business_status": "failed", "error": str(error), "finished_at": blog.now()}
    blog.atomic_json(Path(os.environ["NEWS_CLAW_RESULT_PATH"]), result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
