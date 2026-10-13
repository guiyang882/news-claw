"""Bounded RSS/Atom and webpage collection with persistent source throttling."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import time
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from collectors.sec_submissions import parse_submissions

import scrapy
from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import IgnoreRequest
from scrapy.selector import Selector


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    temporary.replace(path)


def source_key(url: str):
    host = (urlparse(url).hostname or "").lower()
    return "google" if host == "google.com" or host.endswith(".google.com") else host


def policy_paths(root: Path, key: str):
    digest = hashlib.sha256(key.encode()).hexdigest()
    directory = root / "data/runs/request-policy"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.json", directory / f"{digest}.lock"


def load_state(path: Path):
    # A corrupt limiter state fails closed instead of silently resetting it.
    return json.loads(path.read_text()) if path.exists() else {}


def retry_after_deadline(value: str):
    try:
        return time.time() + max(0, int(value))
    except ValueError:
        try:
            return parsedate_to_datetime(value).timestamp()
        except (ValueError, TypeError, OverflowError):
            return 0


class SourceRobotsPolicy:
    """Apply an explicit feed override to its configured URL only."""

    def process_request(self, request, spider):
        source = request.meta.get("source")
        if source is None:
            # Scrapy's internal robots request has its own bypass flag.
            return
        override = (source.get("obey_robots_txt", True) is False
                    and source.get("type") in {"rss", "atom"}
                    and request.url == request.meta.get("robots_override_url"))
        # Redirect requests copy meta. Recompute the flag so a feed exception
        # cannot carry over to another URL, such as a publisher article.
        request.meta["dont_obey_robotstxt"] = override
        if override and request.url not in spider.robots_override_urls:
            spider.robots_override_urls.append(request.url)


class RequestPolicy:
    """Shared disk state enforces minimum intervals even between crawler runs."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    async def process_request(self, request, spider):
        # Installed after HttpCacheMiddleware: cache hits consume no network slot.
        key = source_key(request.url)
        policy = spider.task["collector"].get("request_policy", {})
        interval = float(policy.get("min_interval_seconds_per_host", 10))
        if key == "google":
            interval = max(interval, float(policy.get("google_search_min_interval_seconds", 45)))
        global_interval = float(policy.get("min_interval_seconds_global", 10))
        if spider.requests_made >= spider.request_budget:
            spider.fail("network request budget exhausted")
            raise IgnoreRequest("network request budget exhausted")
        state_path, lock_path = policy_paths(spider.root, key)
        global_path, global_lock_path = policy_paths(spider.root, "__all_sources__")
        with lock_path.open("a") as lock, global_lock_path.open("a") as global_lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    await asyncio.sleep(0.05)
                    continue
                state = load_state(state_path)
                if key == "google":
                    for path in policy.get("shared_circuit_paths", []):
                        legacy = load_state(Path(path))
                        if legacy.get("open"):
                            spider.fail(f"shared Google source circuit open: {path}")
                            raise IgnoreRequest("shared Google source circuit open")
                if state.get("blocked"):
                    spider.fail(f"source {key} is blocked: {state['blocked']}")
                    raise IgnoreRequest(f"persistent source circuit open: {key}")
                try:
                    fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    await asyncio.sleep(0.05)
                    continue
                global_state = load_state(global_path)
                permitted_at = float(state.get("last_request_at", 0)) + max(interval, float(state.get("interval", 0)))
                global_permitted_at = float(global_state.get("last_request_at", 0)) + max(
                    global_interval, float(global_state.get("interval", 0)))
                wait = max(permitted_at, global_permitted_at, float(state.get("not_before", 0))) - time.time()
                if wait > 0:
                    # Release while sleeping so a denial response can open the
                    # circuit immediately, including requests to another host
                    # that shares this service key.
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    fcntl.flock(global_lock, fcntl.LOCK_UN)
                    await asyncio.sleep(wait)
                    continue
                if spider.requests_made >= spider.request_budget:
                    spider.fail("network request budget exhausted")
                    raise IgnoreRequest("network request budget exhausted")
                spider.requests_made += 1
                atomic_json(state_path, {**state, "source": key, "last_request_at": time.time(), "interval": interval})
                atomic_json(global_path, {"source": "__all_sources__", "last_request_at": time.time(), "interval": global_interval})
                break

    async def process_response(self, request, response, spider):
        if response.status in {401, 403, 429}:
            request.meta["failure_detail"] = {
                "category": "http_rate_limited" if response.status == 429 else "http_access_denied",
                "url": request.url, "http_status": response.status,
            }
            key = source_key(request.url)
            state_path, lock_path = policy_paths(spider.root, key)
            with lock_path.open("a") as lock:
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(0.05)
                state = load_state(state_path)
                retry_after = response.headers.get("Retry-After", b"").decode()
                atomic_json(state_path, {**state, "source": key, "blocked": f"HTTP {response.status}",
                                        "blocked_at": utcnow(), "retry_after": retry_after,
                                        "not_before": max(float(state.get("not_before", 0)), retry_after_deadline(retry_after))})
            spider.fail(f"source {key} stopped after HTTP {response.status}: {request.url}",
                        **request.meta["failure_detail"])
            raise IgnoreRequest(f"source denied or rate limited: {key}")
        return response


def clean_text(value: str):
    return " ".join(Selector(text=value).xpath("//text()").getall()).strip()


def published_time(value: str | None):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


class NewsSpider(scrapy.Spider):
    name = "news_claw"

    def __init__(self, task, root, **kwargs):
        super().__init__(**kwargs)
        self.task, self.root = task, root
        self.sources = task["collector"].get("sources", [])
        self.request_budget = int(task["collector"].get("request_policy", {}).get("max_requests_per_run", 12))
        self.requests_made, self.items_seen, self.items_new, self.items_emitted = 0, 0, 0, 0
        self.errors = []
        self.failure_details = []
        self.robots_override_urls = []
        self.items_filtered = 0
        self.max_items = int(task.get("options", {}).get("max_items_per_run", 150))
        self.cutoff = datetime.now(timezone.utc) - timedelta(hours=float(task.get("options", {}).get("lookback_hours", 30)))

    def fail(self, message, *, category=None, url=None, http_status=None):
        if message not in self.errors:
            self.errors.append(message)
        if category:
            detail = {"category": category, "url": url, "http_status": http_status}
            if category == "robots_denied":
                detail["robots_url"] = urljoin(url, "/robots.txt")
                detail["blocked_before_download"] = True
            if detail not in self.failure_details:
                self.failure_details.append(detail)
        self.logger.error(message)

    async def start(self):
        for source in self.sources:
            request = scrapy.Request(source["url"], callback=self.parse_source, errback=self.failed_request,
                                     meta={"source": source})
            if source.get("obey_robots_txt", True) is False:
                request.meta["robots_override_url"] = request.url
            yield request

    def failed_request(self, failure):
        request = failure.request
        detail = request.meta.get("failure_detail", {"category": "request_error", "url": request.url})
        message = f"{request.url}: {failure.value}"
        if failure.check(IgnoreRequest) and str(failure.value) == "Forbidden by robots.txt":
            detail = {"category": "robots_denied", "url": request.url}
            message += " (local robots policy block; endpoint was not downloaded)"
        self.fail(message, **detail)

    def matches_source(self, source, title, text):
        keywords = source.get("include_keywords", [])
        matched = not keywords or any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)",
                                                title + " " + text, re.I) for word in keywords)
        if not matched:
            self.items_filtered += 1
        return matched

    def archive(self, response, source):
        digest = hashlib.sha256(response.body).hexdigest()
        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", source.get("name", source_key(response.url)))[:100]
        date = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        extension = "json" if source["type"] in {"federal_register", "sec_submissions"} else "xml" if source["type"] in {"rss", "atom"} else "html"
        raw = Path(f"data/raw/webpages/{slug}/{date}/{digest}.{extension}")
        meta = Path(f"data/raw/metadata/{slug}/{date}/{digest}.json")
        target = self.root / raw
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
            temporary.write_bytes(response.body)
            temporary.replace(target)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"raw archive content hash mismatch: {raw}")
        if not (self.root / meta).exists():
            atomic_json(self.root / meta, {"url": response.url, "fetched_at": utcnow(), "sha256": digest,
                                          "http_status": response.status, "cached": "cached" in response.flags,
                                          "content_type": response.headers.get("Content-Type", b"").decode()})
        return {"raw_path": str(raw), "metadata_path": str(meta), "http_status": response.status,
                "content_type": response.headers.get("Content-Type", b"").decode(), "source": source}

    def parse_source(self, response):
        source = response.meta["source"]
        archived = self.archive(response, source)
        if source["type"] == "sec_submissions":
            try:
                entries = parse_submissions(json.loads(response.text), source['cik'], source['forms'])
                for entry in entries:
                    self.items_seen += 1
                    if datetime.fromisoformat(entry['published_at']) < self.cutoff:
                        continue
                    if self.items_emitted >= self.max_items:
                        break
                    self.items_emitted += 1
                    yield {**archived, **entry}
            except (KeyError, TypeError, ValueError) as error:
                self.fail(f"invalid SEC submissions response {response.url}: {error}")
            return
        if source["type"] == "federal_register":
            try:
                result = json.loads(response.text)
                entries = result["results"]
                if not isinstance(entries, list):
                    raise ValueError("results must be a list")
                for entry in entries:
                    self.items_seen += 1
                    title, url = entry["title"], entry["html_url"]
                    if not isinstance(title, str) or urlparse(url).scheme not in {"https", "http"}:
                        raise ValueError("notice needs a title and public URL")
                    publication = published_time(entry["publication_date"])
                    if not publication:
                        raise ValueError("notice has no valid publication date")
                    if datetime.fromisoformat(publication) < self.cutoff:
                        continue
                    text = clean_text(entry.get("abstract") or "")
                    if not self.matches_source(source, title, text):
                        continue
                    if self.items_emitted >= self.max_items:
                        break
                    self.items_emitted += 1
                    yield {**archived, "canonical_url": url, "title": title, "published_at": publication,
                           "record_type": "regulatory_notice", "text": text}
            except (KeyError, TypeError, ValueError) as error:
                self.fail(f"invalid Federal Register response {response.url}: {error}")
            return
        if source["type"] == "page":
            self.items_seen += 1
            if self.items_emitted < self.max_items:
                self.items_emitted += 1
                yield {**archived, "canonical_url": response.url, "title": response.css("title::text").get(default="").strip(),
                       "published_at": None, "record_type": "webpage", "text": " ".join(response.xpath(
                           "//body//text()[not(ancestor::script or ancestor::style or ancestor::nav or ancestor::header or ancestor::footer)]").getall()).strip()}
            return
        try:
            tree = ET.fromstring(response.body)
        except (ET.ParseError, DefusedXmlException) as error:
            self.fail(f"invalid feed {response.url}: {error}")
            return
        if tree.tag.split("}")[-1].lower() not in {"rss", "feed", "rdf"}:
            self.fail(f"response is not an RSS/Atom feed: {response.url}")
            return
        selector = Selector(text=response.text, type="xml")
        selector.remove_namespaces()
        for entry in selector.xpath("//channel/item | //feed/entry | /RDF/item"):
            self.items_seen += 1
            if self.items_emitted >= self.max_items:
                break
            link = entry.xpath("link[not(@rel) or @rel='alternate']/@href").get() or entry.xpath("link/text()").get()
            if not link:
                continue
            publication = published_time(entry.xpath("pubDate/text() | published/text() | updated/text() | date/text()").get())
            if publication and datetime.fromisoformat(publication) < self.cutoff:
                continue
            title = clean_text(entry.xpath("title/text()").get(default=""))
            text = clean_text(" ".join(entry.xpath("encoded/text() | content/text() | description/text() | summary/text()").getall()))
            if not self.matches_source(source, title, text):
                continue
            self.items_emitted += 1
            yield {**archived, "canonical_url": urljoin(response.url, link.strip()),
                   "title": title,
                   "published_at": publication, "record_type": "feed_entry",
                   "text": text}


class DocumentPipeline:
    def open_spider(self, spider):
        self.connection = sqlite3.connect(os.environ["NEWS_CLAW_DB"], timeout=10)
        self.connection.execute("PRAGMA foreign_keys=ON")

    def close_spider(self, spider):
        self.connection.close()

    def process_item(self, item, spider):
        normalized = {key: item[key] for key in ("canonical_url", "title", "published_at", "record_type", "text")}
        digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        doc_id = hashlib.sha256((item["canonical_url"] + "\n" + digest).encode()).hexdigest()
        normalized_path = f"data/normalized/documents/{doc_id}.json"
        if not (spider.root / normalized_path).exists():
            atomic_json(spider.root / normalized_path, normalized)
        topics = [{"topic_id": topic, "assigned_by": "task", "confidence": None}
                  for topic in item["source"].get("topic_ids", spider.task.get("topic_ids", []))]
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute("""INSERT OR IGNORE INTO documents
                (id,source_json,canonical_url,title,published_at,fetched_at,content_hash,content_type,http_status,
                 raw_path,metadata_path,normalized_path,language,topic_links_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, json.dumps(item["source"], ensure_ascii=False), item["canonical_url"], item["title"], item["published_at"],
                 utcnow(), digest, item["content_type"], item["http_status"], item["raw_path"], item["metadata_path"],
                 normalized_path, item["source"].get("language"), json.dumps(topics), utcnow()))
            if cursor.rowcount:
                spider.items_new += 1
            else:
                old = json.loads(self.connection.execute("SELECT topic_links_json FROM documents WHERE id=?", (doc_id,)).fetchone()[0])
                existing = {link["topic_id"] for link in old}
                old.extend(link for link in topics if link["topic_id"] not in existing)
                self.connection.execute("UPDATE documents SET topic_links_json=? WHERE id=?", (json.dumps(old), doc_id))
        return item


def validate(task):
    sources = task.get("collector", {}).get("sources", [])
    if not sources:
        raise ValueError("collector.sources must contain an RSS, Atom, page or Federal Register entry")
    for source in sources:
        if source.get("type") not in {"rss", "atom", "page", "federal_register", "sec_submissions"} or urlparse(source.get("url", "")).scheme not in {"http", "https"}:
            raise ValueError(f"invalid source: {source}")
        if source['type'] == 'sec_submissions':
            cik = source.get('cik')
            if (type(cik) is not int or cik <= 0 or source['url'] != f'https://data.sec.gov/submissions/CIK{cik:010d}.json'
                    or source.get('obey_robots_txt', True) is not True):
                raise ValueError('SEC source requires its exact public API URL and robots compliance')
            if not isinstance(source.get('forms'), list) or not source['forms'] or any(not isinstance(f, str) or not f for f in source['forms']):
                raise ValueError('SEC source needs an explicit form allowlist')
        obey_robots = source.get("obey_robots_txt", True)
        if not isinstance(obey_robots, bool):
            raise ValueError("source.obey_robots_txt must be a boolean")
        if not obey_robots and source["type"] not in {"rss", "atom"}:
            raise ValueError("source.obey_robots_txt=false is supported only for RSS/Atom feeds")
        keywords = source.get("include_keywords", [])
        if not isinstance(keywords, list) or any(not isinstance(word, str) or not word.strip() for word in keywords):
            raise ValueError("source.include_keywords must be a list of nonempty strings")
        if "topic_ids" in source and (not isinstance(source["topic_ids"], list) or not source["topic_ids"]
                or any(topic not in task.get("topic_ids", []) for topic in source["topic_ids"])):
            raise ValueError("source.topic_ids must be a nonempty subset of task.topic_ids")
    policy = task["collector"].get("request_policy", {})
    if int(policy.get("max_requests_per_run", 12)) <= 0:
        raise ValueError("max_requests_per_run must be positive")
    for key in ("min_interval_seconds_per_host", "min_interval_seconds_global", "google_search_min_interval_seconds"):
        if float(policy.get(key, 10)) < 0:
            raise ValueError(f"{key} must be nonnegative")
    if int(task.get("options", {}).get("max_items_per_run", 150)) <= 0:
        raise ValueError("max_items_per_run must be positive")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate task and sources without fetching")
    parser.add_argument("--task", default=os.environ.get("NEWS_CLAW_TASK_ID"))
    parser.add_argument("--reset-source", help="clear a source circuit, e.g. google; retain request interval")
    args = parser.parse_args()
    root = Path(os.environ.get("NEWS_CLAW_ROOT", Path(__file__).resolve().parents[1])).resolve()
    if args.reset_source:
        state_path, lock_path = policy_paths(root, args.reset_source)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = load_state(state_path)
            for key in ("blocked", "blocked_at", "retry_after"):
                state.pop(key, None)
            atomic_json(state_path, state)
        print(f"source circuit cleared: {args.reset_source}")
        return 0
    db = Path(os.environ.get("NEWS_CLAW_DB", root / "data/db/news.sqlite3")).resolve()
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT config_json,enabled,scheduler_engine FROM tasks WHERE id=?", (args.task,)).fetchone()
        if row is None:
            parser.error("unknown or missing --task")
        snapshot = os.environ.get("NEWS_CLAW_TASK_CONFIG_PATH")
        task = json.loads(Path(snapshot).read_text() if snapshot and Path(snapshot).is_file() else row[0])
        validate(task)
        if args.check:
            print(json.dumps({"task_id": args.task, "sources": task["collector"]["sources"]}, ensure_ascii=False, indent=2))
            return 0
        if not row[1] or row[2] != "news-claw" or task.get("options", {}).get("do_not_start_from_news_claw"):
            parser.error("task is disabled or externally owned")
        run_id = os.environ.get("NEWS_CLAW_RUN_ID")
        if not connection.execute("SELECT 1 FROM task_runs WHERE id=? AND task_id=? AND status='running'", (run_id, args.task)).fetchone():
            parser.error("launch through the Go engine so the run has an owner and audit record")
    os.environ["NEWS_CLAW_DB"] = str(db)
    identity = "news-claw/0.1 (+https://github.com/guiyang882/news-claw)"
    if any(source['type'] == 'sec_submissions' for source in task['collector']['sources']):
        identity = os.environ.get('NEWS_CLAW_SEC_USER_AGENT', '').strip()
        if (not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', identity) or len(identity) > 200
                or '\r' in identity or '\n' in identity):
            parser.error('NEWS_CLAW_SEC_USER_AGENT must identify the application and contact email')
    process = CrawlerProcess(settings={
        "USER_AGENT": identity,
        "TELNETCONSOLE_ENABLED": False,
        "ROBOTSTXT_OBEY": True, "CONCURRENT_REQUESTS": 2, "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_TIMEOUT": 45, "DOWNLOAD_MAXSIZE": 5 * 1024 * 1024,
        "RETRY_ENABLED": False, "COOKIES_ENABLED": False,
        "HTTPCACHE_ENABLED": True, "HTTPCACHE_DIR": str(root / "data/runs/http-cache"),
        "HTTPCACHE_EXPIRATION_SECS": 1800, "HTTPCACHE_IGNORE_HTTP_CODES": [401, 403, 429, 500, 502, 503, 504],
        "DOWNLOADER_MIDDLEWARES": {"collectors.news.SourceRobotsPolicy": 95,
                                  "collectors.news.RequestPolicy": 950},
        "ITEM_PIPELINES": {"collectors.news.DocumentPipeline": 300},
        "LOG_LEVEL": "INFO",
    })
    crawler = process.create_crawler(NewsSpider)
    captured = {}
    failures = []

    def capture(spider):
        captured["spider"] = spider

    def error(failure, response, spider):
        spider.fail(str(failure.value))

    crawler.signals.connect(capture, signal=signals.spider_opened, weak=False)
    crawler.signals.connect(error, signal=signals.spider_error, weak=False)
    deferred = process.crawl(crawler, task=task, root=root)
    deferred.addErrback(lambda failure: failures.append(str(failure.value)))
    process.start()
    spider = captured.get("spider")
    stats = crawler.stats.get_stats()
    result = {"success": bool(spider) and not spider.errors and not failures and not stats.get("item_dropped_count", 0),
              "items_seen": spider.items_seen if spider else 0, "items_new": spider.items_new if spider else 0,
              "items_filtered": spider.items_filtered if spider else 0,
              "requests_made": spider.requests_made if spider else 0, "cache_hits": stats.get("httpcache/hit", 0),
              "failure_details": spider.failure_details if spider else [],
              "robots_override_urls": spider.robots_override_urls if spider else [],
              "errors": (spider.errors if spider else []) + failures, "finished_at": utcnow()}
    if stats.get("log_count/ERROR", 0):
        result["success"] = False
    result_path = os.environ.get("NEWS_CLAW_RESULT_PATH")
    if result_path:
        atomic_json(Path(result_path), result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
