#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import urllib.request
import urllib.error
from base64 import b64encode
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path


OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "RyanVerWey")
OUTPUT = Path(os.environ.get("LANGUAGE_METRICS_OUTPUT", "assets/language-metrics.svg"))
EXCLUDED_REPOS = {
    OWNER,
    f"{OWNER}.github.io",
}

LANGUAGES = {
    ".ts": ("TypeScript", "#3178C6"),
    ".tsx": ("TypeScript", "#3178C6"),
    ".js": ("JavaScript", "#F7DF1E"),
    ".jsx": ("JavaScript", "#F7DF1E"),
    ".mjs": ("JavaScript", "#F7DF1E"),
    ".cjs": ("JavaScript", "#F7DF1E"),
    ".py": ("Python", "#3776AB"),
    ".css": ("CSS", "#1572B6"),
    ".scss": ("CSS", "#CF649A"),
    ".sass": ("CSS", "#CF649A"),
    ".html": ("HTML", "#E34F26"),
    ".astro": ("Astro", "#BC52EE"),
    ".svelte": ("Svelte", "#FF3E00"),
    ".vue": ("Vue", "#41B883"),
    ".mdx": ("MDX", "#F9AC00"),
    ".java": ("Java", "#B07219"),
    ".kt": ("Kotlin", "#A97BFF"),
    ".go": ("Go", "#00ADD8"),
    ".rs": ("Rust", "#DEA584"),
    ".php": ("PHP", "#777BB4"),
    ".rb": ("Ruby", "#CC342D"),
    ".cs": ("C#", "#239120"),
    ".cpp": ("C++", "#00599C"),
    ".cxx": ("C++", "#00599C"),
    ".cc": ("C++", "#00599C"),
    ".c": ("C", "#A8B9CC"),
}

IGNORED_DIRS = {
    ".git",
    ".github",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".astro",
    "coverage",
    "dist",
    "build",
    "out",
    "node_modules",
    "vendor",
    "__pycache__",
}

IGNORED_FILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "composer.lock",
}


def github_api(path):
    token = github_token()
    req = urllib.request.Request(f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "RyanVerWey-profile-readme")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def github_token():
    return (
        os.environ.get("PROFILE_METRICS_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )


def authenticated_repo_listing_available():
    token = github_token()
    if not token:
        return False
    try:
        github_api("/user")
        return True
    except urllib.error.HTTPError:
        return False


def list_repositories():
    repos = []
    page = 1
    use_authenticated_listing = authenticated_repo_listing_available()
    while True:
        if use_authenticated_listing:
            path = (
                f"/user/repos?visibility=all&affiliation=owner"
                f"&per_page=100&page={page}&sort=updated"
            )
        else:
            path = f"/users/{OWNER}/repos?per_page=100&page={page}&type=owner&sort=updated"
        batch = github_api(path)
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return [
        repo
        for repo in repos
        if not repo.get("fork")
        and not repo.get("archived")
        and repo["name"] not in EXCLUDED_REPOS
    ]


def is_binary(path):
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(2048)
        return b"\0" in chunk
    except OSError:
        return True


def count_source_lines(path):
    if is_binary(path):
        return 0
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    count += 1
    except OSError:
        return 0
    return count


def collect_lines(repo, workspace):
    repo_path = workspace / repo["name"]
    command = ["git"]
    token = github_token()
    if token:
        basic_token = b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        command.extend(["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic_token}"])
    command.extend(["clone", "--depth", "1", "--quiet", repo["clone_url"], str(repo_path)])
    clone_env = os.environ.copy()
    clone_env["GIT_LFS_SKIP_SMUDGE"] = "1"
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clone_env)

    totals = Counter()
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(repo_path).parts)
        if parts & IGNORED_DIRS:
            continue
        if path.name in IGNORED_FILES:
            continue
        language = LANGUAGES.get(path.suffix.lower())
        if not language:
            continue
        totals[language[0]] += count_source_lines(path)
    return totals


def format_number(value):
    return f"{value:,}"


def render_svg(totals, public_repo_count, private_repo_count):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    total_lines = sum(totals.values())
    top = totals.most_common(9)
    colors = {name: color for _, (name, color) in LANGUAGES.items()}

    width = 980
    row_height = 44
    height = 170 + len(top) * row_height
    chart_x = 44
    chart_y = 118
    chart_w = width - 88
    chart_h = 26

    segments = []
    cursor = chart_x
    for index, (language, lines) in enumerate(top):
        ratio = lines / total_lines if total_lines else 0
        seg_w = max(2, chart_w * ratio)
        if index == len(top) - 1:
            seg_w = chart_x + chart_w - cursor
        segments.append(
            f'<rect x="{cursor:.2f}" y="{chart_y}" width="{seg_w:.2f}" height="{chart_h}" '
            f'rx="6" fill="{colors.get(language, "#94A3B8")}"/>'
        )
        cursor += seg_w

    rows = []
    start_y = 184
    for index, (language, lines) in enumerate(top):
        y = start_y + index * row_height
        bar_w = 410 * (lines / top[0][1]) if top and top[0][1] else 0
        color = colors.get(language, "#94A3B8")
        rows.append(
            f'<circle cx="58" cy="{y - 6}" r="7" fill="{color}"/>'
            f'<text x="78" y="{y}" class="label">{escape(language)}</text>'
            f'<text x="332" y="{y}" class="value">{format_number(lines)} lines</text>'
            f'<rect x="510" y="{y - 18}" width="410" height="16" rx="8" fill="#1E293B"/>'
            f'<rect x="510" y="{y - 18}" width="{bar_w:.2f}" height="16" rx="8" fill="{color}"/>'
        )

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    repo_summary = (
        f"{public_repo_count} public + {private_repo_count} private active repos"
        if private_repo_count
        else f"{public_repo_count} public active repos"
    )
    svg = f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Ryan VerWey language distribution</title>
  <desc id="desc">Estimated non-empty source lines by programming language across public and private active repositories. Private repositories are included only as aggregate counts.</desc>
  <defs>
    <linearGradient id="panel" x1="0" y1="0" x2="{width}" y2="{height}" gradientUnits="userSpaceOnUse">
      <stop stop-color="#07130D"/>
      <stop offset="0.55" stop-color="#0F172A"/>
      <stop offset="1" stop-color="#06120A"/>
    </linearGradient>
    <style>
      .eyebrow {{ fill: #94A3B8; font: 600 14px 'Segoe UI', Arial, sans-serif; letter-spacing: 1.6px; }}
      .title {{ fill: #F8FAFC; font: 800 34px 'Segoe UI', Arial, sans-serif; }}
      .meta {{ fill: #CBD5E1; font: 500 15px 'Segoe UI', Arial, sans-serif; }}
      .label {{ fill: #F8FAFC; font: 700 18px 'Segoe UI', Arial, sans-serif; }}
      .value {{ fill: #CBD5E1; font: 600 16px 'Segoe UI', Arial, sans-serif; }}
    </style>
  </defs>
  <rect width="{width}" height="{height}" rx="24" fill="url(#panel)"/>
  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="23" stroke="#334155"/>
  <text x="44" y="48" class="eyebrow">LANGUAGE MIX</text>
  <text x="44" y="88" class="title">{format_number(total_lines)}</text>
  <text x="{width - 44}" y="72" class="meta" text-anchor="end">{repo_summary}</text>
  <text x="{width - 44}" y="94" class="meta" text-anchor="end">private repos shown as aggregate only - updated {updated}</text>
  <rect x="{chart_x}" y="{chart_y}" width="{chart_w}" height="{chart_h}" rx="8" fill="#1E293B"/>
  {''.join(segments)}
  {''.join(rows)}
</svg>
"""
    OUTPUT.write_text(svg, encoding="utf-8")


def main():
    repos = list_repositories()
    public_repo_count = sum(1 for repo in repos if not repo.get("private"))
    private_repo_count = sum(1 for repo in repos if repo.get("private"))
    totals = Counter()
    with tempfile.TemporaryDirectory(prefix="language-metrics-") as temp:
        workspace = Path(temp)
        for repo in repos:
            try:
                totals.update(collect_lines(repo, workspace))
            except subprocess.CalledProcessError:
                visibility = "private" if repo.get("private") else "public"
                print(f"Skipping one {visibility} repository: clone failed")
    render_svg(totals, public_repo_count, private_repo_count)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
