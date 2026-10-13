"""Topic URLs, licensed local media and source references for research articles."""

from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata


def policy(config):
    settings = config["workflow"].get("presentation", {})
    if settings.get("public_process_notes", False) is not False:
        raise ValueError("Public articles must omit internal process notes")
    if settings.get("references", "source_based_appendix") not in {"source_based_appendix", "none"}:
        raise ValueError("Unsupported reference policy")
    if settings.get("emphasis", "restrained_bold_italic_underline") not in {"restrained_bold_italic_underline", "none"}:
        raise ValueError("Unsupported emphasis policy")
    for key, default in (("preferred_tables", 2), ("preferred_diagrams", 2), ("max_topic_words", 8)):
        value = settings.get(key, default)
        if type(value) is not int or not 0 <= value <= 12 or (key == "max_topic_words" and value == 0):
            raise ValueError("Invalid presentation count: " + key)
    return settings


def topic_slug(plan, day, settings=None):
    settings = settings or {}
    if settings.get("slug_style", "topic-date") != "topic-date":
        raise ValueError("Blog URLs use the topic-date style")
    title = re.sub(r"['’]s\b", "", plan["outline"]["title_en"], flags=re.I)
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    stop = {"a", "an", "the", "and", "of", "for", "to", "what", "how", "which", "is", "are", "do", "does", "must", "can"}
    words = [word for word in re.findall(r"[a-z0-9]+", title) if word not in stop][:settings.get("max_topic_words", 8)]
    prefix = "-".join(words)
    if not re.search("[a-z]", prefix):
        prefix = re.sub(r"^(?:candidate|topic)-", "", plan["selected_candidate_id"])
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix):
        raise ValueError("Selected topic needs an English URL slug")
    return prefix + "-" + day.isoformat()


def load_media(config, root):
    path = root / config["workflow"].get("presentation", {}).get("media_catalog", "config/media/approved-assets.json")
    if not path.is_file():
        return []
    catalog = json.loads(path.read_text())
    if catalog.get("version") != 1:
        raise ValueError("Unsupported media catalog")
    static = (Path(config["workflow"]["website_repo"]) / "web/static").resolve()
    assets = []
    for asset in catalog["assets"]:
        if not re.fullmatch(r"/static/images/[a-zA-Z0-9/_.-]+\.(?:jpg|jpeg|png|webp|svg)", asset["path"]):
            raise ValueError("Media needs a reviewed local image path")
        file = static / asset["path"].removeprefix("/static/")
        if file.is_symlink() or not file.resolve().is_relative_to(static):
            raise ValueError("Media escapes the website static directory")
        if not asset.get("creator") or asset.get("license") not in {"CC BY 4.0", "CC BY-SA 4.0", "CC0 1.0", "Public domain"}:
            raise ValueError("Media lacks approved attribution and license")
        if not all(asset.get(key, "").startswith("https://") for key in ("source_url", "license_url")):
            raise ValueError("Media needs source and license links")
        if any(type(asset.get(key)) is not int or not 1 <= asset[key] <= 20000 for key in ("width", "height")):
            raise ValueError("Media needs valid intrinsic dimensions")
        if file.stat().st_size > 10_000_000 or hashlib.sha256(file.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("Reviewed media hash mismatch")
        assets.append(deepcopy(asset))
    return assets


def selected_media(packet, plan):
    # Exclusion notes can name unrelated assets; they must not select a photo.
    outline = plan["outline"]
    text = " ".join(str(outline.get(key, "")) for key in
                    ("title_zh", "title_en", "central_question")).lower()
    return [asset for asset in packet.get("approved_media", [])
            if any(word.lower() in text for word in asset["match_keywords"])]


def media_urls(assets):
    return {asset[key] for asset in assets for key in ("source_url", "license_url")}


def image_figure(asset, language):
    en = language == "en"
    alt = asset["alt_en" if en else "alt_zh"]
    caption = asset["caption_en" if en else "caption_zh"]
    change = ("Original image, displayed at a smaller size." if en else "原图等比显示，未裁剪或修改。")
    if asset["modified"]:
        raise ValueError("Modified media needs a specific adaptation credit")
    source_label, license_label = ("Source", "License") if en else ("图片出处", "许可")
    return (f'<figure class="article-photo" markdown="1">\n'
            f'![{alt}]({asset["path"]}){{: width="{asset["width"]}" height="{asset["height"]}" loading="lazy" }}\n\n'
            f'<figcaption>{html.escape(caption)} '
            f'{html.escape(asset["creator"])} · '
            f'<a href="{html.escape(asset["source_url"], quote=True)}">{source_label}</a> · '
            f'<a href="{html.escape(asset["license_url"], quote=True)}">{license_label}: {html.escape(asset["license"])}</a>. '
            f'{change}</figcaption>\n</figure>')


def with_hero(body, assets, language):
    if not assets or re.search(r"!\[", body):
        return body
    paragraphs = body.split("\n\n")
    position = next((i + 1 for i, paragraph in enumerate(paragraphs)
                     if paragraph.strip() and not paragraph.startswith("#")), 0)
    paragraphs.insert(position, image_figure(assets[0], language))
    return "\n\n".join(paragraphs)


def with_references(body, sources, language):
    if re.search(r"(?mi)^##\s+(?:参考资料|参考文献|References|Sources and references)\s*$", body):
        return body
    heading = "参考资料" if language == "zh" else "References"
    lines = [body.rstrip(), "", "## " + heading, ""]
    for i, source in enumerate(sources, 1):
        title = source["title"].replace("[", "").replace("]", "")
        date = str(source.get("source_date") or source.get("snapshot_as_of") or "")[:10]
        publisher = source.get("publisher", "")
        lines.append(f'{i}. {publisher}. [{title}]({source["url"]}). {date}.')
    return "\n".join(lines) + "\n"


def validate_markup(body, assets, evidence_urls):
    prose = re.sub(r"```.*?```", "", body, flags=re.S)
    if re.search(r"(?mi)^#{1,6}\s+(?:编写与复核|写作与复核|Writing and review)\s*$", prose):
        raise ValueError("Internal writing and review notes do not belong in public articles")
    images = re.findall(r"(?<!\\)!\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", prose)
    if len(images) != len(re.findall(r"(?<!\\)!\[", prose)):
        raise ValueError("Images must use reviewed inline Markdown paths")
    allowed = {asset["path"] for asset in assets}
    if any(path not in allowed for path in images):
        raise ValueError("Article image is not in the licensed local media catalog")
    linked = set(re.findall(r"(?<!!)\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)", body))
    linked.update(html.unescape(url) for url in re.findall(r'href=["\'](https?://[^"\']+)["\']', body))
    if linked - evidence_urls - media_urls(assets):
        raise ValueError("Model invented a citation URL")
    if re.search(r"<\s*(?:script|iframe|img|style|svg)\b|\]\((?:javascript|data):|\bon[a-z]+\s*=", prose, re.I):
        raise ValueError("Unsafe article markup")
    for diagram in re.findall(r"```mermaid\s*\n(.*?)```", body, flags=re.S):
        if len(diagram) > 2500 or not re.match(r"\s*(?:flowchart|graph)\s+(?:TB|TD|LR|RL|BT)\b", diagram):
            raise ValueError("Mermaid needs a bounded flowchart")
        if re.search(r"%%\{|(?m:^\s*(?:click|style|classDef|linkStyle)\b)", diagram):
            raise ValueError("Mermaid configuration and interactive directives are not allowed")


def writing_guidance(config):
    settings = policy(config)
    emphasis = ("Use restrained **bold**, *italic* and <u>underline</u> for key claims and decision criteria. "
                if settings.get("emphasis", "restrained_bold_italic_underline") != "none" else "Keep prose emphasis minimal. ")
    references = ("The publisher supplies a source-based References section. "
                  if settings.get("references", "source_based_appendix") != "none" else "Preserve inline source citations. ")
    return ("Write reader-facing prose without model/tool/process credits or claims about exclusive human authorship. "
            f'Use about {settings.get("preferred_tables", 2)} meaningful Markdown tables and '
            f'{settings.get("preferred_diagrams", 2)} fenced mermaid flowcharts tied to the actual argument. '
            "Keep diagrams short, label assumptions and distinguish evidence relationships from event order. "
            + emphasis +
            "Use only approved local images with their supplied source, creator and license captions; no invented media. "
            "The publisher supplies a licensed hero when available. " + references)
