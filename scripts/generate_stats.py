#!/usr/bin/env python3
"""Generate profile stat cards (languages + contribution streak) as SVGs.

Uses only the standard library. Needs a GitHub token in the GH_TOKEN env var.
With a personal access token that can read private repos, private repositories
and private contributions are included; only aggregate numbers are written out
(no repo names, no code).

Env vars:
  GH_TOKEN         token used for the GitHub GraphQL API (required)
  EXCLUDE_LANGS    comma-separated languages to ignore, e.g. "HTML,Dockerfile"
  OUT_DIR          output directory (default: assets)
"""
import datetime as dt
import html
import json
import os
import urllib.request

API = "https://api.github.com/graphql"
TOKEN = os.environ["GH_TOKEN"]
EXCLUDE = {s.strip().lower() for s in os.environ.get("EXCLUDE_LANGS", "").split(",") if s.strip()}
OUT_DIR = os.environ.get("OUT_DIR", "assets")
TOP_N = 8

STYLE = """
<style>
  .bg { fill: #ffffff; stroke: #d0d7de; }
  .title { font: 600 16px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #1f2328; }
  .label { font: 400 12px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #1f2328; }
  .muted { font: 400 12px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #59636e; }
  .big { font: 700 26px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #1f2328; }
  .accent { fill: #0969da; }
  .track { fill: #eff2f5; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #0d1117; stroke: #30363d; }
    .title, .label, .big { fill: #e6edf3; }
    .muted { fill: #9198a1; }
    .accent { fill: #4493f8; }
    .track { fill: #21262d; }
  }
</style>
"""


def gql(query, **variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


# ---------------------------------------------------------------- languages

def language_totals():
    q = """
    query($cursor: String) {
      viewer {
        repositories(first: 50, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
          pageInfo { hasNextPage endCursor }
          nodes {
            languages(first: 30, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name color } }
            }
          }
        }
      }
    }"""
    totals, colors, cursor = {}, {}, None
    while True:
        repos = gql(q, cursor=cursor)["viewer"]["repositories"]
        for repo in repos["nodes"]:
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                if name.lower() in EXCLUDE:
                    continue
                totals[name] = totals.get(name, 0) + edge["size"]
                colors[name] = edge["node"]["color"] or "#8b949e"
        if not repos["pageInfo"]["hasNextPage"]:
            return totals, colors
        cursor = repos["pageInfo"]["endCursor"]


def languages_svg(totals, colors):
    total = sum(totals.values()) or 1
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top, rest = ranked[:TOP_N], ranked[TOP_N:]
    items = [(n, s, colors[n]) for n, s in top]
    if rest:
        items.append(("Other", sum(s for _, s in rest), "#8b949e"))

    width, bar_x, bar_w = 420, 24, 372
    rows = (len(items) + 1) // 2
    height = 92 + rows * 24 + 8

    parts = [f'<rect class="track" x="{bar_x}" y="52" width="{bar_w}" height="10" rx="5"/>',
             f'<clipPath id="bar"><rect x="{bar_x}" y="52" width="{bar_w}" height="10" rx="5"/></clipPath>',
             '<g clip-path="url(#bar)">']
    x = bar_x
    for name, size, color in items:
        w = bar_w * size / total
        parts.append(f'<rect x="{x:.2f}" y="52" width="{w + 0.5:.2f}" height="10" fill="{color}"/>')
        x += w
    parts.append("</g>")

    for i, (name, size, color) in enumerate(items):
        col, row = i % 2, i // 2
        lx, ly = bar_x + col * 190, 92 + row * 24
        pct = 100 * size / total
        parts.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>')
        parts.append(f'<text class="label" x="{lx + 16}" y="{ly}">{html.escape(name)}</text>')
        parts.append(f'<text class="muted" x="{lx + 170}" y="{ly}" text-anchor="end">{pct:.1f}%</text>')

    return svg(width, height, "Most used languages", "\n  ".join(parts))


# ---------------------------------------------------------------- streak

def contribution_days():
    years = gql("{ viewer { contributionsCollection { contributionYears } } }")
    years = years["viewer"]["contributionsCollection"]["contributionYears"]
    q = """
    query($from: DateTime!, $to: DateTime!) {
      viewer { contributionsCollection(from: $from, to: $to) {
        contributionCalendar { weeks { contributionDays { date contributionCount } } }
      } }
    }"""
    days = {}
    for y in range(min(years), dt.date.today().year + 1):
        data = gql(q, **{"from": f"{y}-01-01T00:00:00Z", "to": f"{y}-12-31T23:59:59Z"})
        for week in data["viewer"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    today = dt.date.today().isoformat()
    return sorted((d, c) for d, c in days.items() if d <= today)


def streaks(days):
    longest = run = 0
    for _, count in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    current = 0
    rev = list(reversed(days))
    if rev and rev[0][1] == 0:  # today without contributions doesn't break the streak yet
        rev = rev[1:]
    for _, count in rev:
        if not count:
            break
        current += 1
    return current, longest


def streak_svg(days):
    total = sum(c for _, c in days)
    current, longest = streaks(days)

    # weekly totals for the last 52 weeks
    recent = days[-364:]
    weeks = [sum(c for _, c in recent[i:i + 7]) for i in range(0, len(recent), 7)]
    peak = max(weeks) or 1
    last_year = sum(weeks)

    width, height = 420, 196
    parts = []
    def days_label(n):
        return f"{n} day" if n == 1 else f"{n} days"

    stats = [(f"{total:,}", "Total contributions"),
             (days_label(current), "Current streak"),
             (days_label(longest), "Longest streak")]
    for i, (value, label) in enumerate(stats):
        cx = 24 + 62 + i * 124
        parts.append(f'<text class="big" x="{cx}" y="78" text-anchor="middle">{value}</text>')
        parts.append(f'<text class="muted" x="{cx}" y="98" text-anchor="middle">{label}</text>')

    chart_x, chart_y, chart_w, chart_h = 24, 120, 372, 44
    bar_w = chart_w / max(len(weeks), 1)
    for i, w in enumerate(weeks):
        h = max(2, chart_h * w / peak) if w else 2
        cls = "accent" if w else "track"
        parts.append(f'<rect class="{cls}" x="{chart_x + i * bar_w + 0.75:.2f}" y="{chart_y + chart_h - h:.2f}" '
                     f'width="{bar_w - 1.5:.2f}" height="{h:.2f}" rx="1"/>')
    parts.append(f'<text class="muted" x="{chart_x}" y="182">Last 52 weeks · {last_year:,} contributions</text>')

    return svg(width, height, "Contribution activity", "\n  ".join(parts))


# ---------------------------------------------------------------- output

def svg(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">
<title>{title}</title>
{STYLE}
  <rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8"/>
  <text class="title" x="24" y="34">{title}</text>
  {body}
</svg>
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    totals, colors = language_totals()
    with open(os.path.join(OUT_DIR, "languages.svg"), "w", encoding="utf-8") as f:
        f.write(languages_svg(totals, colors))
    with open(os.path.join(OUT_DIR, "activity.svg"), "w", encoding="utf-8") as f:
        f.write(streak_svg(contribution_days()))
    print("Wrote", OUT_DIR + "/languages.svg", OUT_DIR + "/activity.svg")


if __name__ == "__main__":
    main()
