"""Demand Card rendering from IdeaForge's stored outside-post rows."""
from __future__ import annotations

from datetime import datetime


def _problem(idea):
    candidates = [idea.get("problem"), idea.get("description"), idea.get("summary"),
                  idea.get("eval_one_sentence"), idea.get("nlm_summary")]
    values = [str(value).strip() for value in candidates if value]
    if len(values) >= 2:
        return f"{values[0]} {values[1]}"
    if values:
        text = values[0]
        parts = [part.strip() for part in text.replace("!", ".").replace("?", ".").split(".") if part.strip()]
        if len(parts) >= 2:
            return ". ".join(parts[:2]) + "."
        return text.rstrip(".") + "."
    title = str(idea.get("video_title") or idea.get("title") or "This idea")
    return f"{title} addresses a problem worth checking. Demand evidence is required before building."


def _checked(value):
    text = str(value or "")
    return text[:10] if len(text) >= 10 else text


def build_card(idea, demand_rows, model_verdict):
    sources, urls, titles = [], set(), set()
    for row in demand_rows or []:
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        key = title.casefold()
        if not url.startswith("https://") or not title or url in urls or key in titles:
            continue
        urls.add(url); titles.add(key)
        sources.append({"platform": str(row.get("platform") or "unknown"), "url": url,
                        "title": title[:200], "engagement": row.get("engagement"),
                        "checked": _checked(row.get("fetched_at"))})
    count = len(sources)
    if str(model_verdict or "").upper() == "BUILD" and count >= 3:
        verdict, reason = "BUILD", "three or more independent outside posts"
    elif str(model_verdict or "").upper() != "BUILD":
        verdict, reason = "PARK", "model verdict PARK"
    else:
        verdict, reason = "PARK", f"only {count} independent outside posts"
    newest = max((source["checked"] for source in sources), default="unknown")
    return {"title": str(idea.get("video_title") or idea.get("title") or "Untitled idea"),
            "problem": _problem(idea), "sources": sources, "independent_sources": count,
            "verdict": verdict, "reason": reason, "checked": newest}


def to_markdown(card):
    lines = [f"# Demand Card: {card['title']}", "", "## Problem", card["problem"], "",
             f"## Verdict: {card['verdict']}", f"Reason: {card['reason']}", "",
             f"Independent outside posts: {card['independent_sources']}", "", "## Evidence"]
    for source in card["sources"]:
        lines.append(f"- **{source['platform']}**, checked {source['checked']}: "
                     f"\"{source['title']}\" — {source['url']} (engagement: {source['engagement']})")
    return "\n".join(lines) + "\n"


def to_agent_brief(card):
    lines = ["# Coding-agent brief", "", "Problem:", card["problem"], "", "Demand evidence:"]
    for source in card["sources"]:
        lines.append(f"- \"{source['title']}\" ({source['platform']}) — {source['url']}")
    lines.extend(["", f"Demand evidence: {card['independent_sources']} independent posts, checked {card['checked']}",
                  "", f"Demand verdict: {card['verdict']} — {card['reason']}"])
    return "\n".join(lines) + "\n"
