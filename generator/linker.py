"""Turn map_data.json into the click-through game: one markdown page per (x, y, facing angle).

Adapted from DoomMe's linker.py (MIT, Kuber Mehta). Differences: nodes and neighbours come from the
real level geometry (walls and drops are respected, not just missing graph edges), and the exit
trigger comes from the level's own exit switch instead of hard-coded coordinates.

Controls on every page:
        up-left   up   up-right        forward-left, forward, forward-right
        turn-left fire turn-right      turn 90 degrees in place, fire (muzzle-flash frame / finish at the exit)
        down-left down down-right      back-left, back, back-right
"""

import argparse
import json
from pathlib import Path

DIRECTION_NAMES = {0: "East", 90: "North", 180: "West", 270: "South"}
SPAWN_ANGLE_NAME = "spawn"


def page_name(x, y, angle, firing=False):
    return f"{x}_{y}_{angle}{'_fire' if firing else ''}.md"


def frame_name(x, y, angle, firing=False):
    return f"doom_{x}_{y}_{angle}{'_fire' if firing else ''}.webp"


def link_or_ghost(label, target):
    if target is None:
        return f'<span style="opacity:0.3">{label}</span>'
    return f'<a href="{page_name(*target)}">{label}</a>'


def build_neighbour_lookup(data):
    compass = data["compass"]

    def neighbour(node_index, world_angle):
        target = data["links"][node_index][compass.index(world_angle % 360)]
        return None if target < 0 else data["nodes"][target]

    return neighbour


def page_markdown(data, node_index, angle, neighbour, is_exit, firing=False):
    x, y = data["nodes"][node_index]

    def moved(offset):
        spot = neighbour(node_index, angle + offset)
        return None if spot is None else (spot[0], spot[1], angle)

    cells = {
        "nw": link_or_ghost("↖️", moved(45)),
        "n": link_or_ghost("⬆️", moved(0)),
        "ne": link_or_ghost("↗️", moved(-45)),
        "w": link_or_ghost("⬅️", (x, y, (angle + 90) % 360)),
        "e": link_or_ghost("➡️", (x, y, (angle - 90) % 360)),
        "sw": link_or_ghost("↙️", moved(135)),
        "s": link_or_ghost("⬇️", moved(180)),
        "se": link_or_ghost("↘️", moved(-135)),
    }
    if is_exit:
        fire = '<a href="end_game.md">💥</a>'
    else:
        fire = f'<a href="{page_name(x, y, angle, firing=not firing)}">💥</a>'
    facing = DIRECTION_NAMES[angle]
    action = ", firing" if firing else ""
    picture = (f'<img src="../assets/{frame_name(x, y, angle, firing)}" '
               f'alt="E1M1 facing {facing}{action}" width="640">')
    forward = moved(0)
    if forward is not None:
        picture = f'<a href="{page_name(*forward)}">{picture}</a>'

    return f"""<p align="center">
{picture}
</p>

<table align="center">
<tr>
<td align="center" width="80">{cells['nw']}</td>
<td align="center" width="80">{cells['n']}</td>
<td align="center" width="80">{cells['ne']}</td>
</tr>
<tr>
<td align="center" width="80">{cells['w']}</td>
<td align="center" width="80">{fire}</td>
<td align="center" width="80">{cells['e']}</td>
</tr>
<tr>
<td align="center" width="80">{cells['sw']}</td>
<td align="center" width="80">{cells['s']}</td>
<td align="center" width="80">{cells['se']}</td>
</tr>
</table>

<p align="center">
<sub>🧭 {facing} | <a href="../README.md">🏠 Menu</a></sub>
</p>
"""


def end_screen_markdown():
    return """<p align="center">
<img src="../static/end-screen.png" alt="THE END" width="640">
</p>

<h2 align="center">YOU SURVIVED E1M1</h2>

<p align="center">
<a href="START_PAGE"><strong>🔄 RESTART MISSION</strong></a>
</p>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--assets-dir", required=True)
    parser.add_argument("--readme-template")
    parser.add_argument("--readme-out")
    parser.add_argument("--strict-assets", action="store_true", help="fail if any frame is missing")
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text())
    game_dir = Path(args.game_dir)
    game_dir.mkdir(parents=True, exist_ok=True)
    neighbour = build_neighbour_lookup(data)
    exit_nodes = set(data["exit_nodes"])

    missing = []
    written = 0
    for node_index, (x, y) in enumerate(data["nodes"]):
        for angle in data["angles"]:
            for firing in (False, True):
                if not (Path(args.assets_dir) / frame_name(x, y, angle, firing)).exists():
                    missing.append((x, y, angle, "fire" if firing else "view"))
                text = page_markdown(data, node_index, angle, neighbour, node_index in exit_nodes, firing)
                (game_dir / page_name(x, y, angle, firing)).write_text(text, encoding="utf-8")
                written += 1

    spawn_x, spawn_y = data["nodes"][data["spawn"]["node"]]
    start_page = page_name(spawn_x, spawn_y, data["spawn"]["angle"])
    (game_dir / "end_game.md").write_text(end_screen_markdown().replace("START_PAGE", start_page), encoding="utf-8")
    print(f"wrote {written} pages + end_game.md; start page = game/{start_page}; "
          f"missing frames = {len(missing)}", flush=True)
    if args.readme_template:
        text = Path(args.readme_template).read_text(encoding="utf-8")
        for key, value in {"START_PAGE": f"game/{start_page}", "NODES": f"{len(data['nodes']):,}",
                           "FRAMES": f"{written // 2:,}", "ALL_FRAMES": f"{written:,}"}.items():
            text = text.replace("{{" + key + "}}", value)
        Path(args.readme_out).write_text(text, encoding="utf-8")
        print(f"wrote {args.readme_out} from {args.readme_template}", flush=True)
    if missing and args.strict_assets:
        raise SystemExit(f"{len(missing)} frames missing, first few: {missing[:5]}")


if __name__ == "__main__":
    main()
