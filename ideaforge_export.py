#!/usr/bin/env python3
"""Export eligible IdeaForge ideas through the Harvest Hub command."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:7888"
DEFAULT_HUB = Path.home() / ".local/bin/harvest-hub"
DECISIONS_PATH = Path.home() / ".local/state/harvest-hub/decisions.jsonl"
TIMEOUT_SECONDS = 15


def _http_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _youtube_id(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "youtu.be":
        parts = [part for part in parsed.path.split("/") if part]
        return parts[0] if parts else None
    if host == "youtube.com" or host.endswith(".youtube.com"):
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live", "v"}:
            return parts[1]
    return None


def _seen_at(idea):
    for value in (idea.get("updated_at"), idea.get("created_at")):
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            stamp = dt.datetime.fromisoformat(
                value[:-1] + "+00:00" if value.endswith("Z") else value
            )
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return stamp.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _summary(idea):
    sentence = idea.get("eval_one_sentence")
    if isinstance(sentence, str) and sentence.strip():
        return sentence
    preview = idea.get("transcript_preview")
    return preview[:220] if isinstance(preview, str) else ""


def candidate_from_idea(idea):
    if not isinstance(idea, dict):
        return None
    verdict = idea.get("eval_verdict")
    if isinstance(verdict, str) and verdict.strip().upper() == "REJECT":
        return None
    title = idea.get("video_title")
    if not isinstance(title, str) or not title.strip():
        return None
    youtube_url = idea.get("youtube_url")
    source_url = youtube_url if _http_url(youtube_url) else idea.get("source_path")
    if not _http_url(source_url):
        return None
    video_id = _youtube_id(source_url)
    idea_id = idea.get("id")
    if video_id:
        identifier, kind = f"youtube:{video_id}", "video"
    else:
        if idea_id is None or str(idea_id) == "":
            return None
        identifier, kind = f"ideaforge:{idea_id}", "idea"

    signals = {}
    score = idea.get("eval_fit_score")
    if (isinstance(score, (int, float)) and not isinstance(score, bool) and
            0 <= score <= 100 and math.isfinite(score)):
        signals["fit"] = score / 100
    if isinstance(verdict, str) and verdict.strip().upper() in {"BUILD", "ACCEPT"}:
        signals["verdict"] = 1
    if idea.get("outcome") == "shipped":
        signals["shipped"] = 1
    return {
        "id": identifier,
        "source": "ideaforge",
        "kind": kind,
        "url": source_url,
        "title": title,
        "summary": _summary(idea),
        "techniques": [],
        "signals": signals,
        "seen_at": _seen_at(idea),
    }


def _ideas(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        values = payload.get("ideas")
        if isinstance(values, list):
            return values
        if "id" in payload:
            return [payload]
    raise ValueError("IdeaForge response must be an idea list or object")


def feed_hub_decisions(base, ideas):
    """Apply the hub's send decisions as IdeaForge outcomes: send only, last line wins, idempotent."""
    decisions_path = Path(os.environ.get("IDEAFORGE_DECISIONS") or DECISIONS_PATH).expanduser()
    try:
        lines = decisions_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    last = {}
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("candidate"), str):
            last[row["candidate"]] = row
    index = {}
    for idea in ideas:
        if not isinstance(idea, dict) or idea.get("id") is None:
            continue
        url = idea.get("youtube_url")
        source = url if _http_url(url) else idea.get("source_path")
        video = _youtube_id(source) if isinstance(source, str) else None
        if video:
            index.setdefault(f"youtube:{video}", idea)
        index.setdefault(f"ideaforge:{idea['id']}", idea)
    posted = 0
    done = set()
    for row in last.values():
        goal = row.get("goal")
        if row.get("action") != "send" or not isinstance(goal, str) or not goal:
            continue
        idea = index.get(row["candidate"])
        if idea is None or idea.get("outcome") or idea.get("id") in done:
            continue
        body = json.dumps({"outcome": "in_progress", "notes": f"hub send {goal}"},
                          ensure_ascii=False).encode("utf-8")
        request = Request(f"{base}/api/outcome/{idea['id']}", data=body, method="POST",
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json"})
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read()
        done.add(idea.get("id"))
        posted += 1
    return posted


def export(base_url=None, hub_bin=None):
    base = (base_url or os.environ.get("IDEAFORGE_URL") or DEFAULT_URL).rstrip("/")
    request = Request(base + "/api/ideas", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        ideas = _ideas(payload)
        rejected = sum(1 for idea in ideas if isinstance(idea, dict) and
                       isinstance(idea.get("eval_verdict"), str) and
                       idea["eval_verdict"].strip().upper() == "REJECT")
        records = [row for idea in ideas
                   if (row := candidate_from_idea(idea)) is not None]
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError,
            json.JSONDecodeError, ValueError) as exc:
        print(f"ideaforge-export: IdeaForge request failed: {exc}", file=sys.stderr)
        return 1

    if not records:
        print(f"ideaforge-export: sent 0, refused 0, skipped {rejected} rejected")
        return 0
    command = Path(hub_bin or os.environ.get("IDEAFORGE_HUB_BIN", str(DEFAULT_HUB))).expanduser()
    body = "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                    for row in records)
    try:
        result = subprocess.run([str(command), "append"], input=body, text=True,
                                capture_output=True, check=False)
    except OSError as exc:
        print(f"ideaforge-export: hub command failed: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        print(f"ideaforge-export: hub command failed: {detail}", file=sys.stderr)
        return 1
    try:
        summary = json.loads(result.stdout)
        sent = int(summary.get("written", 0)) + int(summary.get("merged", 0))
        refused = len(summary.get("refused", []))
    except (TypeError, ValueError, json.JSONDecodeError, AttributeError) as exc:
        print(f"ideaforge-export: invalid hub response: {exc}", file=sys.stderr)
        return 1
    print(f"ideaforge-export: sent {sent}, refused {refused}, skipped {rejected} rejected")
    try:
        feed_hub_decisions(base, ideas)
    except Exception as exc:
        print(f"ideaforge-export: decision feedback failed: {exc}", file=sys.stderr)
    return 0


def main():
    return export()


if __name__ == "__main__":
    raise SystemExit(main())
