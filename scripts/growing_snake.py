#!/usr/bin/env python3
"""
Growing contribution snake.

Reads a GitHub user's contribution calendar and writes animated SVGs in which
a snake slithers through the grid, eats every day that has contributions and
grows one segment per day it eats (up to MAX_LENGTH).

Usage:
    python scripts/growing_snake.py <github-login> <output-dir>

If GITHUB_TOKEN is set, data comes from the GraphQL API. Otherwise the public
contributions page is read, so the script also runs locally with no token.
Standard library only, nothing to install.
"""
import json
import os
import re
import sys
import urllib.request

# ---------- tuning ----------
STEP = 14            # distance between cell centres (px)
CELL = 11            # cell size (px)
MARGIN = 16          # space around the grid (px)
START_LENGTH = 3     # segments the snake starts with
GROW_PER_MEAL = 1    # segments gained per contribution day eaten
MAX_LENGTH = 70      # cap so the snake never fills the whole grid
SECONDS_PER_STEP = 0.07
PAUSE_AT_END = 1.5   # seconds of empty grid before the loop restarts

THEMES = {
    "dark": {
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
        "body": "#39FF14",
        "head": "#EAFFE0",
    },
    "light": {
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "body": "#1a7f37",
        "head": "#0b3d1a",
    },
}

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

QUERY = """query($login: String!) { user(login: $login) { contributionsCollection {
  contributionCalendar { weeks { contributionDays { weekday contributionLevel } } } } } }"""


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "growing-snake", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def fetch_graphql(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    data = json.loads(http("https://api.github.com/graphql", body,
                           {"Authorization": f"bearer {token}", "Content-Type": "application/json"}))
    if data.get("errors"):
        sys.exit(f"GitHub API error: {data['errors']}")
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {(x, d["weekday"]): LEVELS[d["contributionLevel"]]
            for x, w in enumerate(weeks) for d in w["contributionDays"]}


def fetch_html(login):
    html = http(f"https://github.com/users/{login}/contributions")
    cells = {}
    for tag in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        pos = re.search(r'contribution-day-component-(\d+)-(\d+)', tag)
        lvl = re.search(r'data-level="(\d)"', tag)
        if pos and lvl:
            weekday, week = int(pos.group(1)), int(pos.group(2))
            cells[(week, weekday)] = int(lvl.group(1))
    if not cells:
        sys.exit("Could not read the contribution calendar.")
    return cells


def route(cols):
    """Serpentine path: down column 0, up column 1, ... then off the right edge."""
    pts = []
    for x in range(cols):
        ys = range(7) if x % 2 == 0 else range(6, -1, -1)
        pts += [(x, y) for y in ys]
    last_x, last_y = pts[-1]
    pts += [(last_x + i, last_y) for i in range(1, MAX_LENGTH + 2)]  # exit lane
    return pts


def centre(x, y):
    return MARGIN + x * STEP + CELL / 2, MARGIN + y * STEP + CELL / 2


def build(cells, theme):
    cols = max(x for x, _ in cells) + 1
    pts = route(cols)
    grid_steps = cols * 7
    total_steps = len(pts) - 1
    move_time = total_steps * SECONDS_PER_STEP
    duration = move_time + PAUSE_AT_END
    pct = lambda step: step * SECONDS_PER_STEP / duration * 100

    # snake timeline: (step, length) whenever the length changes
    length = START_LENGTH
    events = [(0, length)]
    meal_step = {}
    for s, p in enumerate(pts[:grid_steps]):
        if cells.get(p, 0) > 0:
            meal_step[p] = s
            new_len = min(length + GROW_PER_MEAL, MAX_LENGTH)
            if new_len != length:
                events.append((s, new_len))
                length = new_len

    # body: a dash of `length` steps whose front edge sits at the head
    def frame(step, ln):
        head = step * STEP
        return f"stroke-dasharray:{ln * STEP} 100000;stroke-dashoffset:{-(head - ln * STEP):.1f}"

    body_kf = []
    for i, (s, ln) in enumerate(events):
        prev_len = events[i - 1][1] if i else ln
        if i:
            body_kf.append(f"{pct(s):.4f}%{{{frame(s, prev_len)}}}")
        body_kf.append(f"{pct(s) + (0.0001 if i else 0):.4f}%{{{frame(s, ln)}}}")
    body_kf.append(f"{pct(total_steps):.4f}%,100%{{{frame(total_steps, length)}}}")

    head_kf = (f"0%{{stroke-dashoffset:0}}"
               f"{pct(total_steps):.4f}%,100%{{stroke-dashoffset:{-total_steps * STEP}}}")

    lv = theme["levels"]
    css = [f"@keyframes body{{{''.join(body_kf)}}}",
           f"@keyframes head{{{head_kf}}}",
           f".b{{animation:body {duration:.2f}s linear infinite}}",
           f".h{{animation:head {duration:.2f}s linear infinite}}"]
    rects = []
    for (x, y), level in sorted(cells.items()):
        px, py = MARGIN + x * STEP, MARGIN + y * STEP
        attrs = f'x="{px}" y="{py}" width="{CELL}" height="{CELL}" rx="2" fill="{lv[level]}"'
        if (x, y) in meal_step:
            name = f"e{x}_{y}"
            p = pct(meal_step[(x, y)])
            css.append(f"@keyframes {name}{{0%,{p:.4f}%{{fill:{lv[level]}}}"
                       f"{p + 0.0001:.4f}%,100%{{fill:{lv[0]}}}}}"
                       f".{name}{{animation:{name} {duration:.2f}s step-end infinite}}")
            attrs += f' class="{name}"'
        rects.append(f"<rect {attrs}/>")

    d = "M" + " L".join(f"{cx:.1f},{cy:.1f}" for cx, cy in (centre(*p) for p in pts))
    w = MARGIN * 2 + cols * STEP - (STEP - CELL)
    h = MARGIN * 2 + 7 * STEP - (STEP - CELL)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f"<style>{''.join(css)}</style>"
            f"{''.join(rects)}"
            f'<path class="b" d="{d}" fill="none" stroke="{theme["body"]}" stroke-width="{CELL - 1}" '
            f'stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="0 100000"/>'
            f'<path class="h" d="{d}" fill="none" stroke="{theme["head"]}" stroke-width="{CELL + 1}" '
            f'stroke-linecap="round" stroke-dasharray="0.01 100000"/>'
            f"</svg>")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    login, out = sys.argv[1], sys.argv[2]
    token = os.environ.get("GITHUB_TOKEN")
    cells = fetch_graphql(login, token) if token else fetch_html(login)
    os.makedirs(out, exist_ok=True)
    for name, theme in THEMES.items():
        path = os.path.join(out, f"growing-snake-{name}.svg")
        with open(path, "w") as f:
            f.write(build(cells, theme))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
