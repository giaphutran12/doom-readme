"""Record a smooth walk from the spawn to the exit switch, for the animated preview.

Glides the player along the shortest route through the node graph: every frame warps a few units
further along the path and turns a few degrees toward where the path is heading. Warping (not
walking) avoids snagging on wall corners. ffmpeg turns the saved PNGs into the preview GIF.
"""

import argparse
import json
import math
from collections import deque
from pathlib import Path

import cv2
import vizdoom as vzd

from capture import build_game, shortest_turn, teleport

TURN_PER_FRAME = 6.0
LOOK_AHEAD = 72.0


def shortest_route(data):
    start = data["spawn"]["node"]
    exits = set(data["exit_nodes"])
    previous = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in exits:
            route = []
            while node is not None:
                route.append(node)
                node = previous[node]
            return route[::-1]
        for target in data["links"][node]:
            if target >= 0 and target not in previous:
                previous[target] = node
                queue.append(target)
    raise SystemExit("no route from spawn to an exit node")


def points_along(waypoints, step):
    points = []
    for start, end in zip(waypoints, waypoints[1:]):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        pieces = max(1, round(length / step))
        for piece in range(pieces):
            share = piece / pieces
            points.append((start[0] + (end[0] - start[0]) * share, start[1] + (end[1] - start[1]) * share))
    points.append(waypoints[-1])
    return points


def heading_to(here, there):
    return math.degrees(math.atan2(there[1] - here[1], there[0] - here[0])) % 360


def save_frame(game, path):
    state = game.get_state()
    if state is None or state.screen_buffer is None:
        return False
    image = state.screen_buffer
    if image.ndim == 3 and image.shape[0] == 3:
        image = image.transpose(1, 2, 0)
    return bool(cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)))


def turn_toward(game, target_angle):
    facing = game.get_game_variable(vzd.GameVariable.ANGLE)
    turn = max(-TURN_PER_FRAME, min(TURN_PER_FRAME, shortest_turn(target_angle, facing)))
    game.make_action([turn])
    return abs(turn)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iwad", required=True)
    parser.add_argument("--pwad", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--step", type=float, default=16.0, help="units moved per frame")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text())
    route = shortest_route(data)
    waypoints = [tuple(data["nodes"][node]) for node in route]
    points = points_along(waypoints, args.step)
    exit_line = data["exit_lines"][0]
    switch = ((exit_line[0][0] + exit_line[1][0]) / 2, (exit_line[0][1] + exit_line[1][1]) / 2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"route: {len(route)} nodes, {len(points)} glide points", flush=True)

    game = build_game(args.iwad, args.pwad, data["map"], args.width, args.height)
    if not teleport(game, *waypoints[0]):
        raise SystemExit("could not place the player at the spawn")
    saved = 0
    try:
        for index, here in enumerate(points):
            ahead = points[min(len(points) - 1, index + max(1, round(LOOK_AHEAD / args.step)))]
            game.send_game_command(f"warp {here[0]:.1f} {here[1]:.1f}")
            if ahead != here:
                turn_toward(game, heading_to(here, ahead))
            else:
                game.make_action([0])
            saved += save_frame(game, out / f"walk_{saved:04d}.png")
        for _ in range(60):
            remaining = turn_toward(game, heading_to(points[-1], switch))
            saved += save_frame(game, out / f"walk_{saved:04d}.png")
            if remaining < 0.5:
                break
        for _ in range(10):
            game.make_action([0])
            saved += save_frame(game, out / f"walk_{saved:04d}.png")
    finally:
        game.close()
    print(f"done: frames_saved={saved}", flush=True)


if __name__ == "__main__":
    main()
