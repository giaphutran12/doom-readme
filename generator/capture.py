"""Render the frames: teleport a VizDoom player to every node, one WebP per facing angle.

Adapted from DoomMe's gridmapper.py (MIT, Kuber Mehta). Runs headless; safe to shard across jobs.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import cv2
import vizdoom as vzd

POSITION_TOLERANCE = 16.0
ANGLE_TOLERANCE = 1.0
WEAPON_RAISE_TICS = 24


def build_game(iwad, pwad, map_name, width, height):
    game = vzd.DoomGame()
    game.set_doom_game_path(str(iwad))
    game.set_doom_scenario_path(str(pwad))
    game.set_doom_map(map_name)
    game.set_screen_resolution(width_to_resolution(width, height))
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    game.set_window_visible(False)
    game.set_sound_enabled(False)
    game.set_render_all_frames(True)
    game.set_render_hud(True)
    game.set_render_crosshair(False)
    game.set_render_weapon(True)
    game.set_render_messages(False)
    game.set_render_particles(False)
    game.set_render_screen_flashes(False)
    game.add_available_button(vzd.Button.TURN_LEFT_RIGHT_DELTA)
    game.add_available_game_variable(vzd.GameVariable.ANGLE)
    game.add_available_game_variable(vzd.GameVariable.POSITION_X)
    game.add_available_game_variable(vzd.GameVariable.POSITION_Y)
    game.add_game_args("+sv_cheats 1 -nomp -nosound -nomonsters +iddqd +notarget")
    game.init()
    return game


def width_to_resolution(width, height):
    name = f"RES_{width}X{height}"
    if not hasattr(vzd.ScreenResolution, name):
        raise SystemExit(f"VizDoom has no screen resolution {name}")
    return getattr(vzd.ScreenResolution, name)


def shortest_turn(target, current):
    diff = target - current
    while diff <= -180:
        diff += 360
    while diff > 180:
        diff -= 360
    return diff


def face(game, target_angle):
    for _ in range(10):
        current = game.get_game_variable(vzd.GameVariable.ANGLE)
        diff = shortest_turn(target_angle, current)
        if abs(diff) < ANGLE_TOLERANCE:
            break
        game.make_action([diff])
    game.make_action([0])


def teleport(game, x, y):
    game.new_episode()
    game.send_game_command(f"warp {x} {y}")
    for _ in range(WEAPON_RAISE_TICS):
        game.make_action([0])
    here = (game.get_game_variable(vzd.GameVariable.POSITION_X), game.get_game_variable(vzd.GameVariable.POSITION_Y))
    return math.hypot(here[0] - x, here[1] - y) <= POSITION_TOLERANCE


def snapshot(game, path, quality):
    state = game.get_state()
    if state is None or state.screen_buffer is None:
        return False
    image = state.screen_buffer
    if image.ndim == 3 and image.shape[0] == 3:
        image = image.transpose(1, 2, 0)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    return bool(cv2.imwrite(str(path), image, [cv2.IMWRITE_WEBP_QUALITY, quality]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iwad", required=True)
    parser.add_argument("--pwad", required=True)
    parser.add_argument("--map", default="E1M1")
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--quality", type=int, default=75)
    parser.add_argument("--shard", default="0/1", help="index/count")
    parser.add_argument("--limit", type=int, default=0, help="render only the first N nodes of this shard")
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text())
    shard_index, shard_count = (int(part) for part in args.shard.split("/"))
    mine = [i for i in range(len(data["nodes"])) if i % shard_count == shard_index]
    if args.limit:
        mine = mine[:args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"shard {shard_index}/{shard_count}: {len(mine)} nodes, {len(mine) * len(data['angles'])} frames, "
          f"{args.width}x{args.height} webp q{args.quality}", flush=True)

    game = build_game(args.iwad, args.pwad, args.map, args.width, args.height)
    started = time.time()
    rendered = skipped = failed = 0
    failed_nodes = []
    try:
        for count, index in enumerate(mine, 1):
            x, y = data["nodes"][index]
            paths = {angle: out / f"doom_{x}_{y}_{angle}.webp" for angle in data["angles"]}
            if all(path.exists() for path in paths.values()):
                skipped += 1
                continue
            if not teleport(game, x, y):
                failed += 1
                failed_nodes.append(index)
                print(f"teleport rejected node={index} x={x} y={y}", flush=True)
                continue
            for angle, path in paths.items():
                face(game, angle)
                game.make_action([0])
                if snapshot(game, path, args.quality):
                    rendered += 1
                else:
                    failed += 1
                    failed_nodes.append(index)
                    print(f"no frame node={index} angle={angle}", flush=True)
            if count % 100 == 0:
                rate = rendered / max(time.time() - started, 1e-6)
                print(f"progress {count}/{len(mine)} nodes, rendered={rendered}, {rate:.1f} frames/s", flush=True)
    finally:
        game.close()
    print(f"done: rendered={rendered} skipped_existing={skipped} failed={failed} "
          f"seconds={time.time() - started:.0f}", flush=True)
    (out / f"failed_shard_{shard_index}.json").write_text(json.dumps(sorted(set(failed_nodes))))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
