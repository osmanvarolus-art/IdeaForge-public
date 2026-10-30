"""Read public search results as unverified demand leads."""
import json
import re
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlsplit


def https_url(value):
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
    except (TypeError, ValueError):
        return False


def probe(query, runner=None, limit=5):
    runner = runner or subprocess.run
    commands = {
        "github": ["gh", "search", "issues", "--limit", str(limit), "--json", "url,title,commentsCount", "--", query],
        "reddit": ["rdt", "search", "--limit", str(limit), "--", query],
        "twitter": ["twitter", "search", "-n", str(limit), "--json", "--", query],
    }
    rows = []
    for platform, command in commands.items():
        try:
            result = runner(command, capture_output=True, text=True, timeout=30, check=True)
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = data.get("results", data.get("data"))
            if not isinstance(data, list):
                raise ValueError("unrecognised response format")
            for item in data[:limit]:
                if not isinstance(item, dict):
                    raise ValueError("unrecognised result")
                url = item.get("url") or item.get("link")
                if platform == "twitter" and not url:
                    author = item.get("author") or {}
                    name = author.get("screenName", "") if isinstance(author, dict) else ""
                    tweet_id = str(item.get("id") or "")
                    if re.fullmatch(r"[A-Za-z0-9_]{1,15}", name) and tweet_id.isdigit():
                        url = f"https://x.com/{name}/status/{tweet_id}"
                if not https_url(url):
                    continue
                rows.append({"platform": platform, "url": url,
                             "title": str(item.get("title") or item.get("text") or "Untitled"),
                             "engagement": item.get("commentsCount", item.get("score", item.get("likes", (item.get("metrics") or {}).get("likes", item.get("replies", 0))))),
                             "fetched_at": datetime.now(timezone.utc).isoformat()})
        except Exception as exc:
            rows.append({"platform": platform, "error": str(exc)})
    rows.append({"platform": "v2ex", "error": "No documented public search API available"})
    return rows


def init_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS demand (
        idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
        platform TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
        engagement TEXT, fetched_at TEXT NOT NULL, UNIQUE(idea_id, url))""")


def store(conn, idea_id, rows):
    found = list({row['url']: row for row in rows if https_url(row.get('url'))}.values())
    conn.executemany("INSERT OR IGNORE INTO demand (idea_id, platform, url, title, engagement, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                     [(idea_id, r["platform"], r["url"], r["title"], str(r["engagement"]), r["fetched_at"]) for r in found])
    return len(found), len({r["platform"] for r in found})
