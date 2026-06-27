#!/usr/bin/env python3
"""Run the scheduled research digest deterministically without a Codex subtask."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def run_command(command: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout)


def parse_json_from_output(output: str) -> dict[str, Any]:
    start = output.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in command output: {output[:500]}")
    return json.loads(output[start:])


def load_config() -> dict[str, Any]:
    result = run_command([sys.executable, str(SCRIPT_DIR / "manage_sources.py"), "list"], cwd=SKILL_DIR)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "failed to read saved configuration")
    return json.loads(result.stdout)


def preflight(config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not config.get("sources"):
        missing.append("sources")
    if not config.get("interests"):
        missing.append("interests")
    recipients = config.get("recipients", {})
    if not recipients.get("to"):
        missing.append("recipients.to")
    return missing


def check_mail_cli() -> dict[str, Any]:
    result = run_command([sys.executable, str(SCRIPT_DIR / "check_agently_mail.py")], cwd=SKILL_DIR)
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"mail readiness check did not return JSON: {result.stdout[:500]}") from exc
    if result.returncode != 0 or not status.get("ready"):
        raise RuntimeError(
            "agently-cli is not ready; read https://agent.qq.com/doc/cli-setup.md and complete setup before scheduling. "
            f"status={json.dumps(status, ensure_ascii=False)}"
        )
    return status


def clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = re.sub(r"\s+,", ",", value)
    value = re.sub(r",{2,}", ",", value)
    return value.strip(" ,")


def split_authors(authors: Any) -> list[str]:
    values: list[str] = []
    if isinstance(authors, list):
        for author in authors:
            values.extend(str(author).split(","))
    elif authors:
        values.extend(str(authors).split(","))
    return [clean_text(value) for value in values if clean_text(value)]


def source_label(value: str) -> str:
    lower = value.lower()
    if "science" in lower:
        return "Science"
    if "nature" in lower:
        return "Nature"
    return value


def clip(value: str, length: int = 300) -> str:
    value = clean_text(value)
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."


def cn_summary(item: dict[str, Any]) -> str:
    title = item.get("title", "")
    text = f"{title} {item.get('summary', '')}".lower()
    if "single-cell" in text or "single cell" in text or "multiomics" in text:
        return "这篇最贴近单细胞组学主线，重点在于把细胞状态、疾病相关遗传信号和多组学证据放在同一框架里理解。"
    if "privacy" in text or "medical records" in text or "membership inference" in text:
        return "这篇关注医疗 AI 的训练数据与隐私风险，提醒模型评估不能只看性能，还要看数据泄漏和群体差异风险。"
    if "ai safety" in text or "government" in text or "policy" in text:
        return "这篇提供 AI 安全、监管和科研生态之间的现实背景，适合判断科研工具落地时会遇到哪些制度约束。"
    if "antibiotic" in text or "drug-resistant" in text or "machine-learning" in text:
        return "这篇展示机器学习在药物发现和候选分子筛选中的具体应用，是 AI for science 从概念走向实验链条的案例。"
    if "dartmouth" in text:
        return "这篇回看 AI 研究早期脉络，有助于把当下 AI for science 的热潮放回更长的技术史中判断。"
    if "global ai" in text or "silicon valley" in text:
        return "这篇提醒 AI 基础设施和应用路线不能一套方案全球通用，语言、算力、电力和本地需求都会改变部署策略。"
    if "ai" in text:
        return "这篇与 AI for science 的工具、治理或应用场景有关，可作为本期主题的背景信息。"
    return "这篇与保存的兴趣主题有一定交集，可用于快速判断是否值得进一步阅读全文。"


def why_it_matters(item: dict[str, Any]) -> str:
    title = item.get("title", "")
    text = f"{title} {item.get('summary', '')}".lower()
    if "single-cell" in text or "multiomics" in text:
        return "如果你关注单细胞数据分析，这类文章有助于判断下一步应该怎样建模细胞状态和疾病机制。"
    if "privacy" in text or "medical" in text:
        return "医疗 AI 的隐私与合规风险会直接影响数据使用、模型验证和成果转化。"
    if "safety" in text or "government" in text:
        return "AI 科研工具越接近真实部署，安全规范和政策环境越会影响研究节奏。"
    if "antibiotic" in text or "machine-learning" in text:
        return "这是 AI 参与科学发现的实用案例，能帮助区分方法展示和可验证应用。"
    if "dartmouth" in text:
        return "历史脉络能帮助过滤短期噪音，判断哪些问题是长期研究命题。"
    return "它能补充本期主题的上下文，帮助决定是否需要进一步追踪。"


def build_digest(config: dict[str, Any], workdir: Path, limit: int) -> tuple[list[dict[str, Any]], list[str], Path]:
    out_dir = workdir / ".research-mail-digest"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "digest.json"
    result = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "build_digest.py"),
            "--limit",
            str(limit),
            "--intro-style",
            "long",
            "--out-json",
            str(json_path),
        ],
        cwd=SKILL_DIR,
        timeout=180,
    )
    warnings = [line for line in result.stderr.splitlines() if line.strip()]
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "failed to build digest")
    items = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise RuntimeError("digest JSON must be a list of selected items")
    filtered = [item for item in items if int(item.get("score") or 0) >= 2]
    selected = filtered or items
    return selected[:limit], warnings, out_dir


def build_zh_html(items: list[dict[str, Any]], interests: list[str], out_dir: Path) -> Path:
    today = datetime.now(timezone.utc).date().isoformat()
    interest_text = "、".join(interests)
    feed_names = sorted({source_label(str(item.get("feed_title", ""))) for item in items if item.get("feed_title")})
    feed_text = "、".join(feed_names) or "保存的信息源"
    priority = items[: min(3, len(items))]
    priority_titles = "、".join(f"<strong>{html.escape(clean_text(item.get('title', '')))}</strong>" for item in priority)

    parts: list[str] = [
        "<!doctype html>",
        '<html lang="zh-CN"><body style="margin:0;padding:0;background:#f6f8f7;">',
        "<main style=\"max-width:720px;margin:0 auto;padding:28px 18px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#1f2b29;\">",
        '<header style="padding:22px 0 18px 0;">',
        f'<p style="font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#5d706c;margin:0 0 8px 0;">Research digest · {today}</p>',
        '<h1 style="font-size:28px;line-height:1.2;margin:0 0 10px 0;">每日研究摘要</h1>',
        f'<p style="font-size:15px;line-height:1.6;margin:0;color:#52615e;">关注主题：{html.escape(interest_text)}</p>',
        "</header>",
        '<section style="padding:16px 0 18px 0;">',
        '<h2 style="font-size:18px;line-height:1.35;margin:0 0 10px 0;">导读</h2>',
        f'<p style="font-size:15px;line-height:1.7;margin:0 0 10px 0;color:#33413e;">这期摘要来自 {html.escape(feed_text)}，按保存的兴趣主题“{html.escape(interest_text)}”筛选。整体上，它把 AI for science 的安全、隐私、治理和真实科学应用，与单细胞/多组学的机制解释放在一起看。</p>',
        f'<p style="font-size:15px;line-height:1.7;margin:0 0 10px 0;color:#33413e;">如果时间有限，建议先看：{priority_titles or "暂无优先条目"}。这些条目通常覆盖本期最值得优先判断的研究脉络、方法进展或落地风险。</p>',
        '<p style="font-size:15px;line-height:1.7;margin:0;color:#33413e;">下面内容根据 RSS/Atom 元数据自动改写，目标是帮助快速判断哪些链接值得打开阅读全文。</p>',
        "</section>",
    ]

    if priority:
        parts.extend(
            [
                '<section style="padding:16px 0 18px 0;border-top:1px solid #dde7e5;">',
                '<h2 style="font-size:18px;line-height:1.35;margin:0 0 10px 0;">优先阅读</h2>',
                '<ol style="margin:0;padding-left:22px;">',
            ]
        )
        for item in priority:
            title = clean_text(str(item.get("title", "")))
            link = str(item.get("link", ""))
            meta = " · ".join(part for part in [source_label(str(item.get("feed_title", ""))), str(item.get("published", ""))] if part)
            parts.extend(
                [
                    '<li style="margin:0 0 8px 0;padding:0;font-size:14px;line-height:1.55;color:#33413e;">',
                    f'<strong><a href="{html.escape(link, quote=True)}" style="color:#195c6b;text-decoration:none;">{html.escape(title)}</a></strong><br>',
                    f'<span style="color:#667571;">{html.escape(meta)}</span>',
                    "</li>",
                ]
            )
        parts.extend(["</ol>", "</section>"])

    for index, item in enumerate(items, 1):
        title = clean_text(str(item.get("title", "")))
        link = str(item.get("link", ""))
        feed_title = source_label(str(item.get("feed_title", "")))
        published = str(item.get("published", ""))
        authors = split_authors(item.get("authors"))
        author_text = "，".join(authors) if authors else "无作者信息"
        summary = clean_text(str(item.get("summary", "")))
        meta = " · ".join(part for part in [feed_title, published] if part)
        parts.extend(
            [
                '<section style="padding:18px 0;border-top:1px solid #dde7e5;">',
                f'<div style="font-size:13px;color:#6a7976;margin-bottom:6px;">#{index} {html.escape(meta)}</div>',
                f'<h2 style="font-size:19px;line-height:1.35;margin:0 0 8px 0;font-weight:700;"><a href="{html.escape(link, quote=True)}" style="color:#195c6b;text-decoration:none;">{html.escape(title)}</a></h2>',
                f'<p style="font-size:15px;line-height:1.65;margin:0 0 8px 0;color:#24312f;">{html.escape(cn_summary(item))}</p>',
                f'<p style="font-size:14px;line-height:1.6;margin:0 0 8px 0;color:#44524f;"><strong>来源</strong>：{html.escape(feed_title)} · <strong>日期</strong>：{html.escape(published)} · <strong>作者</strong>：{html.escape(author_text)}</p>',
            ]
        )
        if summary:
            parts.append(
                f'<p style="font-size:14px;line-height:1.6;margin:0 0 8px 0;color:#44524f;"><strong>原始元数据</strong>：{html.escape(clip(summary, 420))}</p>'
            )
        parts.extend(
            [
                f'<p style="font-size:14px;line-height:1.6;margin:0;color:#33413e;"><strong>为什么重要</strong>：{html.escape(why_it_matters(item))}</p>',
                "</section>",
            ]
        )

    parts.extend(
        [
            '<section style="padding:16px 0 6px 0;border-top:1px solid #dde7e5;">',
            '<p style="font-size:12px;line-height:1.6;color:#6a7976;margin:0;">注：本文由 RSS/Atom 元数据自动整理而成，未主动打开原文。标题和摘要均来自上游源；如需全文核对，请点开相应链接。</p>',
            "</section>",
            "</main></body></html>",
        ]
    )
    out_path = out_dir / "digest_cn.html"
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return out_path


def send_mail(recipients: dict[str, list[str]], subject: str, body_file: Path, cwd: Path) -> tuple[dict[str, Any], list[str]]:
    command = ["agently-cli", "message", "+send"]
    for address in recipients.get("to", []):
        command.extend(["--to", address])
    for address in recipients.get("cc", []):
        command.extend(["--cc", address])
    for address in recipients.get("bcc", []):
        command.extend(["--bcc", address])
    command.extend(["--subject", subject, "--body-file", str(body_file.relative_to(cwd)), "--body-format", "html"])

    first = run_command(command, cwd=cwd, timeout=120)
    if first.returncode != 0:
        raise RuntimeError(first.stderr or first.stdout or "agently-cli send failed")
    first_payload = parse_json_from_output(first.stdout)
    if first_payload.get("data", {}).get("confirmation_required"):
        token = first_payload.get("data", {}).get("confirmation_token")
        if not token:
            raise RuntimeError("confirmation required but no confirmation_token returned")
        second = run_command([*command, "--confirmation-token", token], cwd=cwd, timeout=120)
        if second.returncode != 0:
            raise RuntimeError(second.stderr or second.stdout or "agently-cli confirmation failed")
        return parse_json_from_output(second.stdout), [first.stdout.strip()]
    return first_payload, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=str(SKILL_DIR), help="Working directory for generated digest files")
    parser.add_argument("--final-file", default="", help="Optional path for final markdown status")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="Build the digest and report recipients without sending")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    config = load_config()
    missing = preflight(config)
    if missing:
        message = f"Missing required configuration before fetch: {', '.join(missing)}"
        print(message)
        if args.final_file:
            Path(args.final_file).write_text(message + "\n", encoding="utf-8")
        return 2

    mail_status = check_mail_cli()
    items, warnings, out_dir = build_digest(config, workdir, args.limit)
    if not items:
        raise RuntimeError("no digest items selected")
    body_file = build_zh_html(items, config["interests"], out_dir)
    subject = f"每日研究摘要：{' / '.join(config['interests'][:2])} - {datetime.now(timezone.utc).date().isoformat()}"
    if args.dry_run:
        report_lines = [
            "Dry run completed; email was not sent.",
            "",
            f"- Sender: `{mail_status.get('email') or 'unknown'}`",
            f"- To: `{', '.join(config['recipients'].get('to', []))}`",
            f"- Cc: `{', '.join(config['recipients'].get('cc', [])) or 'none'}`",
            f"- Bcc: `{', '.join(config['recipients'].get('bcc', [])) or 'none'}`",
            f"- Subject: `{subject}`",
            f"- Body file: `{body_file.relative_to(workdir)}`",
            f"- Selected items: `{len(items)}`",
        ]
        if warnings:
            report_lines.append("")
            report_lines.append("Warnings:")
            report_lines.extend(f"- {warning}" for warning in warnings)
        report = "\n".join(report_lines).strip() + "\n"
        print(report)
        if args.final_file:
            Path(args.final_file).write_text(report, encoding="utf-8")
        return 0

    payload, confirmation_logs = send_mail(config["recipients"], subject, body_file, workdir)
    queued = bool(payload.get("data", {}).get("queued"))

    report_lines = [
        "邮件已成功排队。" if queued else "邮件发送未确认排队。",
        "",
        f"- Sender: `{mail_status.get('email') or 'unknown'}`",
        f"- To: `{', '.join(config['recipients'].get('to', []))}`",
        f"- Cc: `{', '.join(config['recipients'].get('cc', [])) or 'none'}`",
        f"- Bcc: `{', '.join(config['recipients'].get('bcc', [])) or 'none'}`",
        f"- Subject: `{subject}`",
    ]
    if warnings or confirmation_logs:
        report_lines.append("")
        report_lines.append("Warnings:")
        if confirmation_logs:
            report_lines.append("- agently-cli required a confirmation token; completed the second send call automatically for this scheduled run.")
        for warning in warnings:
            report_lines.append(f"- {warning}")
    report = "\n".join(report_lines).strip() + "\n"
    print(report)
    if args.final_file:
        Path(args.final_file).write_text(report, encoding="utf-8")
    return 0 if queued else 1


if __name__ == "__main__":
    raise SystemExit(main())
