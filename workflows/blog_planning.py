"""Evidence-based editorial plans and approximate long-form reading estimates."""

import math
import re


def reading_options(policy):
    """Only explicitly configured formats may be selected by the planner."""
    options = policy.get('formats') or [{
        'target_minutes': policy['target_minutes'], 'tolerance_minutes': policy['tolerance_minutes']}]
    seen = set()
    for option in options:
        target, tolerance = option['target_minutes'], option['tolerance_minutes']
        if (type(target) is not int or type(tolerance) is not int
                or not 1 <= target <= 60 or not 0 <= tolerance < target
                or target in seen):
            raise ValueError('Invalid or duplicate reading format')
        seen.add(target)
    if policy['target_minutes'] not in seen:
        raise ValueError('Default reading target is not an allowed format')
    return [{**policy, 'target_minutes': option['target_minutes'],
             'tolerance_minutes': option['tolerance_minutes']} for option in options]


def reading_for_plan(settings, plan):
    target = plan['outline']['target_reading_minutes']
    for option in reading_options(settings['reading']):
        if type(target) is int and target == option['target_minutes']:
            return option
    raise ValueError('Outline does not target an allowed reading format')


def reading_metrics(body, language, policy):
    """Exclude URLs and code; count Han characters/words or English words."""
    text = re.sub(r"```.*?```", "", body, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^\n]*?\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    pattern = r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*"
    if language == "zh":
        pattern = r"[\u3400-\u9fff]|" + pattern
    units = len(re.findall(pattern, text))
    rate = policy["zh_units_per_minute" if language == "zh" else "en_words_per_minute"]
    return {"units": units, "minutes": math.ceil(units / rate), "rate": rate}


def length_requirements(policy):
    # Match reading_metrics: minutes are rounded up, including the lower bound.
    target = policy["target_minutes"]
    tolerance = policy["tolerance_minutes"]
    return {language: {"target": target * rate, "minimum": (target - tolerance - 1) * rate + 1,
                       "maximum": (target + tolerance) * rate}
            for language, rate in (("zh", policy["zh_units_per_minute"]),
                                   ("en", policy["en_words_per_minute"]))}


def selected_candidate(plan):
    return next(item for item in plan["candidates"] if item["id"] == plan["selected_candidate_id"])


def canonicalize_locators(plan, packet):
    """Normalize an exact document locator plus a model's paragraph annotation.

    Only an existing source/locator pair is accepted; unknown paths still fail.
    The unmodified model response remains in the stage's response.json audit.
    """
    from copy import deepcopy
    plan = deepcopy(plan)
    pairs = {(sid, item["locator"]) for item in packet["evidence"] for sid in item["source_ids"]}
    for section in plan.get("outline", {}).get("sections", []):
        for reference in section["evidence_refs"]:
            locator = reference["locator"]
            for sid, base in pairs:
                if sid != reference["source_id"] or not locator.startswith(base):
                    continue
                suffix = locator[len(base):]
                if re.match(r"^[；;]\s*text\s*(?:[:：]|→|->)", suffix):
                    reference["locator"] = base
                    break
    return plan


def validate_plan(plan, packet, settings, *, packet_sha256):
    if plan["packet_sha256"] != packet_sha256:
        raise ValueError("Editorial plan is not bound to the source packet")
    if plan["status"] != "ready":
        return
    policy = settings["planning"]
    candidates = plan["candidates"]
    if not 1 <= len(candidates) <= policy["max_candidates"]:
        raise ValueError("Invalid number of candidate topics")
    ids = [item["id"] for item in candidates]
    questions = [item["question"].strip().casefold() for item in candidates]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z0-9-]{1,60}", cid) for cid in ids):
        raise ValueError("Candidate topic IDs must be unique")
    if len(set(questions)) != len(questions) or any(len(question) < 15 for question in questions):
        raise ValueError("Candidate questions must be specific and distinct")
    sources = {source["id"]: source for source in packet["sources"]}
    for candidate in candidates:
        if any(sid not in sources for sid in candidate["source_ids"]):
            raise ValueError("Candidate topic refers to an unknown source")
        if not candidate["title"].strip() or not candidate["reader_value"].strip():
            raise ValueError("Candidate topic lacks a title or reader value")
    if plan["selected_candidate_id"] not in ids or not plan["selection_reason"].strip():
        raise ValueError("Editorial plan lacks a valid topic selection")
    chosen = selected_candidate(plan)
    chosen_ids = set(chosen["source_ids"])
    if len({sources[sid]["url"] for sid in chosen_ids}) < 2:
        raise ValueError("Selected topic needs at least two distinct source URLs")
    if not any(sources[sid]["evidence_level"] in {"cached_webpage", "existing_research_snapshot"} for sid in chosen_ids):
        raise ValueError("Headline-only evidence cannot support a long-form article")
    from .blog_schedule import validate_edition_plan
    validate_edition_plan(plan, packet)
    outline = plan["outline"]
    reading = reading_for_plan(settings, plan)
    for field in ("title_zh", "title_en", "central_question", "working_thesis", "scope", "reader_takeaway"):
        if not outline[field].strip():
            raise ValueError("Editorial outline is incomplete")
    sections = outline["sections"]
    if not policy["min_sections"] <= len(sections) <= policy["max_sections"]:
        raise ValueError("Outline needs enough substantive sections")
    section_ids = [section["id"] for section in sections]
    if len(set(section_ids)) != len(section_ids):
        raise ValueError("Outline section IDs must be unique")
    required = {"opening", "evidence", "mechanism", "counterargument", "implications", "conclusion"}
    if required - {section["kind"] for section in sections}:
        raise ValueError("Outline lacks an argument, counterargument or conclusion")
    for section in sections:
        if any(not section[field].strip() for field in ("id", "heading_zh", "heading_en", "purpose", "argument")):
            raise ValueError("Outline section lacks a concrete argument")
        if not section["boundaries"] or any(not value.strip() for value in section["boundaries"]):
            raise ValueError("Outline section lacks evidence boundaries")
        if not section["evidence_refs"]:
            raise ValueError("Outline section needs traceable evidence")
        for reference in section["evidence_refs"]:
            if reference["source_id"] not in chosen_ids or not any(
                    reference["source_id"] in item["source_ids"] and reference["locator"] == item["locator"]
                    for item in packet["evidence"]):
                raise ValueError("Outline evidence locator does not exist in the source packet")
    lengths = length_requirements(reading)
    for language, field in (("zh", "zh_units_budget"), ("en", "en_words_budget")):
        if any(section[field] <= 0 for section in sections):
            raise ValueError("Outline section lacks a length budget")
        budget = sum(section[field] for section in sections)
        if not lengths[language]["minimum"] <= budget <= lengths[language]["maximum"]:
            raise ValueError("Outline length budget does not support the target reading time")


def render_outline(plan, packet):
    chosen = selected_candidate(plan)
    outline = plan["outline"]
    sources = {source["id"]: source for source in packet["sources"]}
    lines = [f"# {outline['title_zh']}", "", f"目标阅读：约 {outline['target_reading_minutes']} 分钟（每种语言）",
             "", "## 候选题", ""]
    for candidate in plan["candidates"]:
        marker = "（选中）" if candidate["id"] == chosen["id"] else ""
        lines.extend([f"### {candidate['title']}{marker}", "", f"问题：{candidate['question']}",
                      f"读者价值：{candidate['reader_value']}", f"时效与角度：{candidate['why_now']}",
                      "证据缺口：" + ("；".join(candidate["evidence_gaps"]) or "仍须在事实复核中确认"), ""])
    lines.extend(["## 选题与论证", "", f"选择理由：{plan['selection_reason']}",
                  f"核心问题：{outline['central_question']}", f"暂定论点：{outline['working_thesis']}",
                  f"范围：{outline['scope']}", f"读者带走的判断：{outline['reader_takeaway']}", "", "## 章节大纲", ""])
    for index, section in enumerate(outline["sections"], 1):
        lines.extend([f"### {index}. {section['heading_zh']}", "", section["heading_en"], "",
                      f"用途：{section['purpose']}", f"论点：{section['argument']}",
                      f"篇幅：中文约 {section['zh_units_budget']} 单位；英文约 {section['en_words_budget']} 词",
                      "", "证据："])
        for ref in section["evidence_refs"]:
            source = sources[ref["source_id"]]
            lines.append(f"- [{source['title']}]({source['url']})；定位 `{ref['locator']}`")
        lines.extend(["", "边界："] + ["- " + value for value in section["boundaries"]] + [""])
    lines.extend([f"资料包 SHA256：`{plan['packet_sha256']}`", "",
                  "这是写作计划，候选判断仍须经过后续事实复核。", ""])
    return "\n".join(lines)


def summary(plan):
    return {"candidate_count": len(plan["candidates"]), "selected_candidate_id": plan["selected_candidate_id"],
            "title": plan["outline"]["title_zh"], "central_question": plan["outline"]["central_question"],
            "target_reading_minutes": plan["outline"]["target_reading_minutes"],
            "section_count": len(plan["outline"]["sections"])}
