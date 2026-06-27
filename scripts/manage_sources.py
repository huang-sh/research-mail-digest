#!/usr/bin/env python3
"""Manage saved research sources, interest keywords, and email recipients."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SKILL_DIR / "data"
FEEDS_FILE = DATA_DIR / "sources.txt"
INTERESTS_FILE = DATA_DIR / "interests.md"
RECIPIENTS_FILE = DATA_DIR / "recipients.md"
RECIPIENT_SECTIONS = {"to": "To", "cc": "Cc", "bcc": "Bcc"}


def ensure_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FEEDS_FILE.exists():
        FEEDS_FILE.write_text(
            "# One source URL per line. Currently supports RSS/Atom URLs.\n"
            "# Add sources only after the user provides or approves them.\n",
            encoding="utf-8",
        )
    if not INTERESTS_FILE.exists():
        INTERESTS_FILE.write_text("# User interests\n\n## Interests\n", encoding="utf-8")
    if not RECIPIENTS_FILE.exists():
        RECIPIENTS_FILE.write_text("# Email recipients\n\n## To\n\n## Cc\n\n## Bcc\n", encoding="utf-8")


def read_feeds() -> list[str]:
    ensure_files()
    return [
        line.strip()
        for line in FEEDS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def write_feeds(feeds: list[str]) -> None:
    ensure_files()
    unique_feeds = list(dict.fromkeys(feed.strip() for feed in feeds if feed.strip()))
    FEEDS_FILE.write_text(
        "# One source URL per line. Currently supports RSS/Atom URLs. Empty lines and comments are ignored.\n"
        "# Add sources only after the user provides or approves them.\n"
        + "\n".join(unique_feeds)
        + ("\n" if unique_feeds else ""),
        encoding="utf-8",
    )


def read_interests() -> list[str]:
    ensure_files()
    interests: list[str] = []
    for line in INTERESTS_FILE.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value.startswith("- "):
            interests.append(value[2:].strip())
        elif value.startswith("* "):
            interests.append(value[2:].strip())
    return interests


def write_interests(interests: list[str]) -> None:
    ensure_files()
    unique_interests = list(dict.fromkeys(interest.strip() for interest in interests if interest.strip()))
    body = "# User interests\n\n## Interests\n"
    if unique_interests:
        body += "\n".join(f"- {interest}" for interest in unique_interests) + "\n"
    INTERESTS_FILE.write_text(body, encoding="utf-8")


def read_recipients() -> dict[str, list[str]]:
    ensure_files()
    recipients = {key: [] for key in RECIPIENT_SECTIONS}
    current: str | None = None
    for line in RECIPIENTS_FILE.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value.startswith("## "):
            heading = value[3:].strip().lower()
            current = heading if heading in recipients else None
            continue
        if current and value.startswith(("- ", "* ")):
            recipients[current].append(value[2:].strip())
    return recipients


def write_recipients(recipients: dict[str, list[str]]) -> None:
    ensure_files()
    lines = ["# Email recipients", ""]
    for key, heading in RECIPIENT_SECTIONS.items():
        unique_values = list(dict.fromkeys(value.strip() for value in recipients.get(key, []) if value.strip()))
        lines.extend([f"## {heading}"])
        lines.extend(f"- {value}" for value in unique_values)
        lines.append("")
    RECIPIENTS_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def remove_or_set(values: list[str], selector: str, replacement: str | None = None) -> tuple[list[str], str]:
    target_index: int | None = None
    if selector.isdigit():
        index = int(selector)
        if index < 1 or index > len(values):
            raise SystemExit(f"index out of range: {selector}")
        target_index = index - 1
    else:
        for index, value in enumerate(values):
            if value == selector:
                target_index = index
                break
        if target_index is None:
            raise SystemExit(f"not found: {selector}")

    old_value = values[target_index]
    if replacement is None:
        del values[target_index]
    else:
        values[target_index] = replacement
    return values, old_value


def print_state() -> None:
    print(
        json.dumps(
            {
                "sources_file": str(FEEDS_FILE),
                "interests_file": str(INTERESTS_FILE),
                "recipients_file": str(RECIPIENTS_FILE),
                "sources": read_feeds(),
                "interests": read_interests(),
                "recipients": read_recipients(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list")

    add_feed = subparsers.add_parser("add-source", aliases=["add-feed"])
    add_feed.add_argument("url")

    remove_feed = subparsers.add_parser("remove-source", aliases=["remove-feed"])
    remove_feed.add_argument("selector")

    set_feed = subparsers.add_parser("set-source", aliases=["set-feed"])
    set_feed.add_argument("selector")
    set_feed.add_argument("url")

    add_interest = subparsers.add_parser("add-interest")
    add_interest.add_argument("text")

    remove_interest = subparsers.add_parser("remove-interest")
    remove_interest.add_argument("selector")

    set_interest = subparsers.add_parser("set-interest")
    set_interest.add_argument("selector")
    set_interest.add_argument("text")

    add_recipient = subparsers.add_parser("add-recipient")
    add_recipient.add_argument("kind", choices=sorted(RECIPIENT_SECTIONS))
    add_recipient.add_argument("email")

    remove_recipient = subparsers.add_parser("remove-recipient")
    remove_recipient.add_argument("kind", choices=sorted(RECIPIENT_SECTIONS))
    remove_recipient.add_argument("selector")

    set_recipient = subparsers.add_parser("set-recipient")
    set_recipient.add_argument("kind", choices=sorted(RECIPIENT_SECTIONS))
    set_recipient.add_argument("selector")
    set_recipient.add_argument("email")

    args = parser.parse_args()
    ensure_files()

    if args.command == "list":
        print_state()
        return 0

    if args.command in {"add-source", "add-feed"}:
        write_feeds([*read_feeds(), args.url])
    elif args.command in {"remove-source", "remove-feed"}:
        feeds, _ = remove_or_set(read_feeds(), args.selector)
        write_feeds(feeds)
    elif args.command in {"set-source", "set-feed"}:
        feeds, _ = remove_or_set(read_feeds(), args.selector, args.url)
        write_feeds(feeds)
    elif args.command == "add-interest":
        write_interests([*read_interests(), args.text])
    elif args.command == "remove-interest":
        interests, _ = remove_or_set(read_interests(), args.selector)
        write_interests(interests)
    elif args.command == "set-interest":
        interests, _ = remove_or_set(read_interests(), args.selector, args.text)
        write_interests(interests)
    elif args.command == "add-recipient":
        recipients = read_recipients()
        recipients[args.kind].append(args.email)
        write_recipients(recipients)
    elif args.command == "remove-recipient":
        recipients = read_recipients()
        recipients[args.kind], _ = remove_or_set(recipients[args.kind], args.selector)
        write_recipients(recipients)
    elif args.command == "set-recipient":
        recipients = read_recipients()
        recipients[args.kind], _ = remove_or_set(recipients[args.kind], args.selector, args.email)
        write_recipients(recipients)

    print_state()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
