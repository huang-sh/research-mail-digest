#!/usr/bin/env python3
"""Build an email-friendly digest from saved research sources."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import textwrap
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
DC = "{http://purl.org/dc/elements/1.1/}"
RSS1 = "{http://purl.org/rss/1.0/}"
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FEEDS_FILE = SKILL_DIR / "data" / "sources.txt"
DEFAULT_INTERESTS_FILE = SKILL_DIR / "data" / "interests.md"


@dataclass
class FeedItem:
    title: str
    link: str
    feed_title: str
    published: str = ""
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    summary: str = ""
    score: int = 0


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def child_text(node: ET.Element, names: Iterable[str]) -> str:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def find_link(node: ET.Element) -> str:
    text_link = child_text(node, ["link", f"{RSS1}link"])
    if text_link:
        return text_link
    for link in node.findall(f"{ATOM}link"):
        rel = link.attrib.get("rel", "alternate")
        href = link.attrib.get("href", "")
        if href and rel == "alternate":
            return href
    link = node.find(f"{ATOM}link")
    return link.attrib.get("href", "") if link is not None else ""


def normalize_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.date().isoformat()
    except (TypeError, ValueError):
        pass
    iso_value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_value).date().isoformat()
    except ValueError:
        return value.strip()


def fetch_feed(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Codex Research Mail Digest/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def read_feeds_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    feeds: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            feeds.append(value)
    return feeds


def read_interests_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    interests: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("<!--"):
            continue
        if value.startswith("- "):
            interests.append(value[2:].strip())
        elif value.startswith("* "):
            interests.append(value[2:].strip())
    return interests


def parse_feed(xml_bytes: bytes, source_url: str) -> tuple[list[FeedItem], str]:
    root = ET.fromstring(xml_bytes)
    items: list[FeedItem] = []

    channel = root.find("channel") or root.find(f"{RSS1}channel")
    if channel is not None:
        feed_title = child_text(channel, ["title", f"{RSS1}title"]) or source_url
        rss_items = channel.findall("item") or root.findall(f"{RSS1}item")
        for item in rss_items:
            title = child_text(item, ["title", f"{RSS1}title"]) or "(untitled)"
            summary = child_text(item, ["description", f"{RSS1}description", f"{CONTENT}encoded"])
            authors = [
                v
                for v in [
                    child_text(item, ["author"]),
                    child_text(item, [f"{DC}creator"]),
                ]
                if v
            ]
            categories = [
                strip_html(c.text or "")
                for c in [*item.findall("category"), *item.findall(f"{RSS1}category")]
                if c.text
            ]
            items.append(
                FeedItem(
                    title=strip_html(title),
                    link=find_link(item),
                    feed_title=strip_html(feed_title),
                    published=normalize_date(
                        child_text(item, ["pubDate", "published", "updated", f"{DC}date"])
                    ),
                    authors=authors,
                    categories=categories,
                    summary=strip_html(summary),
                )
            )
        return items, feed_title

    if root.tag == f"{ATOM}feed" or root.find(f"{ATOM}entry") is not None:
        feed_title = child_text(root, [f"{ATOM}title"]) or source_url
        for entry in root.findall(f"{ATOM}entry"):
            title = child_text(entry, [f"{ATOM}title"]) or "(untitled)"
            authors = [
                child_text(author, [f"{ATOM}name"])
                for author in entry.findall(f"{ATOM}author")
                if child_text(author, [f"{ATOM}name"])
            ]
            categories = [
                cat.attrib.get("term", "")
                for cat in entry.findall(f"{ATOM}category")
                if cat.attrib.get("term")
            ]
            summary = child_text(entry, [f"{ATOM}summary", f"{ATOM}content"])
            items.append(
                FeedItem(
                    title=strip_html(title),
                    link=find_link(entry),
                    feed_title=strip_html(feed_title),
                    published=normalize_date(child_text(entry, [f"{ATOM}published", f"{ATOM}updated"])),
                    authors=authors,
                    categories=categories,
                    summary=strip_html(summary),
                )
            )
        return items, feed_title

    raise ValueError("Unsupported RSS/Atom format")


def tokenize_interests(interests: list[str]) -> list[str]:
    broad_terms = {"article", "articles", "journal", "journals", "paper", "papers", "research", "science", "study"}
    tokens: list[str] = []
    for interest in interests:
        phrase = interest.strip().lower()
        if phrase:
            tokens.append(phrase)
        tokens.extend(
            token
            for token in re.findall(r"[\w.+-]{2,}", phrase)
            if token not in {"and", "with", "the", "for", "from", "using"} and token not in broad_terms
        )
    return sorted(set(tokens), key=len, reverse=True)


def score_item(item: FeedItem, tokens: list[str]) -> int:
    haystack = " ".join(
        [item.title, item.summary, item.feed_title, " ".join(item.categories), " ".join(item.authors)]
    ).lower()
    score = 0
    for token in tokens:
        matched = token in haystack if " " in token else re.search(rf"(?<!\w){re.escape(token)}(?!\w)", haystack)
        if matched:
            score += 4 if " " in token else 1
            title = item.title.lower()
            title_matched = token in title if " " in token else re.search(rf"(?<!\w){re.escape(token)}(?!\w)", title)
            if title_matched:
                score += 2
    return score


def clip(value: str, length: int = 280) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def readable_join(values: list[str], fallback: str) -> str:
    values = [value for value in values if value]
    if not values:
        return fallback
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def build_intro(items: list[FeedItem], interests: list[str], intro_style: str) -> tuple[str, str]:
    interest_text = readable_join(interests, "recent feed updates")
    feed_titles = sorted({item.feed_title for item in items if item.feed_title})
    feed_text = readable_join(feed_titles, "the selected RSS feeds")
    top_titles = [item.title for item in items[:3]]
    top_text = "; ".join(top_titles) if top_titles else "No matching items were found"

    if intro_style == "short":
        html_intro = (
            f"<p>This digest was curated from {html.escape(feed_text)} for "
            f"{html.escape(interest_text)}.</p>"
        )
        text_intro = f"This digest was curated from {feed_text} for {interest_text}."
        return html_intro, text_intro

    html_intro = f"""
      <p style="font-size:15px;line-height:1.7;margin:0 0 10px 0;color:#33413e;">
        This issue was curated from {html.escape(feed_text)} around {html.escape(interest_text)}.
        The selection favors items that help connect feed-level updates to research judgment:
        what is worth reading now, what is mainly contextual, and what may affect future scientific work.
      </p>
      <p style="font-size:15px;line-height:1.7;margin:0 0 10px 0;color:#33413e;">
        The strongest signals in this batch are: {html.escape(top_text)}. Read these first if time is limited,
        then use the remaining items to track the broader policy, safety, and methods context around the topic.
      </p>
      <p style="font-size:15px;line-height:1.7;margin:0;color:#33413e;">
        The summaries below are rewritten from RSS metadata for quick triage. They are meant to help decide
        which links deserve full-text reading, not to replace the original articles.
      </p>
    """
    text_intro = (
        f"This issue was curated from {feed_text} around {interest_text}.\n\n"
        "The selection favors items that help connect feed-level updates to research judgment: "
        "what is worth reading now, what is mainly contextual, and what may affect future scientific work.\n\n"
        f"Read these first if time is limited: {top_text}.\n\n"
        "The summaries below are rewritten from RSS metadata for quick triage and do not replace the original articles."
    )
    return html_intro, text_intro


def item_to_dict(item: FeedItem) -> dict[str, object]:
    return {
        "title": item.title,
        "link": item.link,
        "feed_title": item.feed_title,
        "published": item.published,
        "authors": item.authors,
        "categories": item.categories,
        "summary": item.summary,
        "score": item.score,
    }


def build_html(items: list[FeedItem], interests: list[str], failures: list[str], title: str, intro_style: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    interest_text = ", ".join(interests) if interests else "recent feed updates"
    html_intro, _ = build_intro(items, interests, intro_style)
    priority_items = items[: min(3, len(items))]
    priority_cards = []
    for item in priority_items:
        safe_title = html.escape(item.title)
        linked_title = (
            f'<a href="{html.escape(item.link, quote=True)}" '
            'style="color:#195c6b;text-decoration:none;">'
            f"{safe_title}</a>"
            if item.link
            else safe_title
        )
        priority_cards.append(
            f"""
            <li style="margin:0 0 8px 0;padding:0;font-size:14px;line-height:1.55;color:#33413e;">
              <strong>{linked_title}</strong><br>
              <span style="color:#667571;">{html.escape(item.feed_title)}{(" · " + html.escape(item.published)) if item.published else ""}</span>
            </li>
            """
        )
    cards = []
    for index, item in enumerate(items, 1):
        safe_title = html.escape(item.title)
        linked_title = (
            f'<a href="{html.escape(item.link, quote=True)}" '
            'style="color:#195c6b;text-decoration:none;">'
            f"{safe_title}</a>"
            if item.link
            else safe_title
        )
        meta = " · ".join(part for part in [item.feed_title, item.published] if part)
        category_text = ", ".join(item.categories[:4])
        summary = clip(item.summary or "No summary was provided by the feed.")
        cards.append(
            f"""
            <section style="padding:18px 0;border-top:1px solid #dde7e5;">
              <div style="font-size:13px;color:#6a7976;margin-bottom:6px;">#{index} {html.escape(meta)}</div>
              <h2 style="font-size:19px;line-height:1.35;margin:0 0 8px 0;font-weight:700;">{linked_title}</h2>
              <p style="font-size:15px;line-height:1.65;margin:0 0 8px 0;color:#24312f;">{html.escape(summary)}</p>
              <p style="font-size:13px;line-height:1.5;margin:0;color:#667571;">Match score: {item.score}{(" · " + html.escape(category_text)) if category_text else ""}</p>
            </section>
            """
        )
    failure_note = ""
    if failures:
        failure_note = (
            '<p style="font-size:12px;color:#8a5a24;margin-top:20px;">'
            f"Feed fetch warnings: {html.escape('; '.join(failures))}</p>"
        )
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f8f7;">
    <main style="max-width:720px;margin:0 auto;padding:28px 18px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2b29;">
      <header style="padding:22px 0 18px 0;">
        <p style="font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#5d706c;margin:0 0 8px 0;">Research digest · {today}</p>
        <h1 style="font-size:28px;line-height:1.2;margin:0 0 10px 0;">{html.escape(title)}</h1>
        <p style="font-size:15px;line-height:1.6;margin:0;color:#52615e;">Curated for: {html.escape(interest_text)}</p>
      </header>
      <section style="padding:16px 0 18px 0;">
        <h2 style="font-size:18px;line-height:1.35;margin:0 0 10px 0;">Editor's note</h2>
        {html_intro}
      </section>
      <section style="padding:16px 0 18px 0;border-top:1px solid #dde7e5;">
        <h2 style="font-size:18px;line-height:1.35;margin:0 0 10px 0;">Read first</h2>
        <ol style="margin:0;padding-left:22px;">
          {''.join(priority_cards) if priority_cards else '<li>No priority items available.</li>'}
        </ol>
      </section>
      {''.join(cards) if cards else '<p>No matching feed items were found.</p>'}
      {failure_note}
    </main>
  </body>
</html>
"""


def build_text(items: list[FeedItem], interests: list[str], failures: list[str], title: str, intro_style: str) -> str:
    _, text_intro = build_intro(items, interests, intro_style)
    lines = [
        title,
        "",
        f"Curated for: {', '.join(interests) if interests else 'recent feed updates'}",
        "",
        "Editor's note",
        text_intro,
        "",
        "Read first",
    ]
    for index, item in enumerate(items[: min(3, len(items))], 1):
        lines.append(f"{index}. {item.title} ({item.feed_title}{', ' + item.published if item.published else ''})")
    lines.append("")
    for index, item in enumerate(items, 1):
        meta = " · ".join(part for part in [item.feed_title, item.published] if part)
        lines.extend(
            [
                f"{index}. {item.title}",
                meta,
                clip(item.summary or "No summary was provided by the feed.", 320),
                item.link,
                "",
            ]
        )
    if failures:
        lines.extend(["Feed fetch warnings:", *failures])
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", action="append", default=[], help="RSS/Atom source URL; repeatable")
    parser.add_argument(
        "--feeds-file",
        default=str(DEFAULT_FEEDS_FILE),
        help="File containing one source URL per line; currently RSS/Atom URLs",
    )
    parser.add_argument("--interest", action="append", default=[], help="User interest or keyword; repeatable")
    parser.add_argument(
        "--interests-file",
        default=str(DEFAULT_INTERESTS_FILE),
        help="Markdown file containing saved interest bullet lines",
    )
    parser.add_argument("--limit", type=int, default=8, help="Maximum articles in digest")
    parser.add_argument("--timeout", type=int, default=20, help="Network timeout per feed in seconds")
    parser.add_argument("--title", default="", help="Digest title")
    parser.add_argument(
        "--intro-style",
        choices=["short", "long"],
        default="long",
        help="Introduction length and structure for the generated digest",
    )
    parser.add_argument("--out-html", default="", help="Write HTML email body to this path")
    parser.add_argument("--out-text", default="", help="Write plaintext digest to this path")
    parser.add_argument("--out-json", default="", help="Write parsed selected items as JSON")
    args = parser.parse_args()

    feed_urls = [*read_feeds_file(Path(args.feeds_file)), *args.feed]
    interests = [*read_interests_file(Path(args.interests_file)), *args.interest]
    feed_urls = list(dict.fromkeys(feed_urls))
    interests = list(dict.fromkeys(interests))
    if not feed_urls:
        parser.error(
            "no sources configured; ask the user for at least one RSS/Atom source URL, "
            "then save it with scripts/manage_sources.py add-source or pass --feed"
        )
    if not interests:
        parser.error(
            "no interests configured; ask the user for at least one interest keyword or phrase, "
            "then save it with scripts/manage_sources.py add-interest or pass --interest"
        )

    tokens = tokenize_interests(interests)
    all_items: list[FeedItem] = []
    failures: list[str] = []

    for feed_url in feed_urls:
        try:
            xml_bytes = fetch_feed(feed_url, args.timeout)
            items, _ = parse_feed(xml_bytes, feed_url)
            all_items.extend(items)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError) as exc:
            failures.append(f"{feed_url}: {exc}")

    for item in all_items:
        item.score = score_item(item, tokens)

    all_items.sort(key=lambda item: (item.score, item.published), reverse=True)
    matched_items = [item for item in all_items if item.score > 0]
    selected_pool = matched_items or all_items
    selected = selected_pool[: max(args.limit, 1)]
    title = args.title or "Curated RSS Digest"

    html_body = build_html(selected, interests, failures, title, args.intro_style)
    text_body = build_text(selected, interests, failures, title, args.intro_style)

    if args.out_html:
        Path(args.out_html).write_text(html_body, encoding="utf-8")
    if args.out_text:
        Path(args.out_text).write_text(text_body, encoding="utf-8")
    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps([item_to_dict(item) for item in selected], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not args.out_html and not args.out_text and not args.out_json:
        print(textwrap.shorten(text_body, width=4000, placeholder="\n..."))

    if not selected:
        print("warning: no feed items selected", file=sys.stderr)
    for failure in failures:
        print(f"warning: {failure}", file=sys.stderr)
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
