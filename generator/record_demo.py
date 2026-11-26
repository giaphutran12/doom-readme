"""Record a gameplay demo for the animated preview: the spawn-to-exit route with monsters on.

The player glides along the shortest route (as record_walk.py does). Whenever a live monster is
in view and close, it stops, turns onto it and fires until the kill counter goes up. God mode
keeps the run alive; the HUD stays on so health, ammo and the face react like real play.
"""

import argparse
import json
import math
from pathlib import Path

import vizdoom as vzd

from record_walk import heading_to, points_along, save_frame, shortest_route
from capture import shortest_turn, width_to_resolution

TURN_PER_FRAME = 8.0
LOOK_AHEAD = 72.0
ENGAGE_RANGE = 900.0
AIM_TOLERANCE = 4.0
MAX_FIGHT_FRAMES = 140
MAX_HIDDEN_FRAMES = 15
MAX_SWING = 50.0
VERBOSE = False
MONSTERS = {"ZombieMan", "ShotgunGuy", "DoomImp", "Demon", "Spectre", "ChaingunGuy",
            "LostSoul", "Cacodemon", "BaronOfHell", "HellKnight"}


def build_demo_game(iwad, pwad, map_name, width, height):
    game = vzd.DoomGame()
    game.set_doom_game_path(str(iwad))
    game.set_doom_scenario_path(str(pwad))
    game.set_doom_map(map_name)
    game.set_doom_skill(3)
    game.set_screen_resolution(width_to_resolution(width, height))
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    game.set_window_visible(False)
    game.set_sound_enabled(False)
    game.set_render_all_frames(True)
    game.set_render_hud(True)
    game.set_render_crosshair(False)
    game.set_render_weapon(True)
    game.set_render_messages(False)
    game.set_render_particles(True)
    game.set_render_screen_flashes(True)
    game.set_render_decals(True)
    game.set_labels_buffer_enabled(True)
    game.set_objects_info_enabled(True)
    game.add_available_button(vzd.Button.TURN_LEFT_RIGHT_DELTA)
    game.add_available_button(vzd.Button.ATTACK)
    for variable in ["ANGLE", "POSITION_X", "POSITION_Y", "KILLCOUNT"]:
        game.add_available_game_variable(getattr(vzd.GameVariable, variable))
    game.add_game_args("+sv_cheats 1 -nosound")
    game.init()
    return game


def turn_input(turn):
    """Doom angles grow counter-clockwise, but a positive TURN_LEFT_RIGHT_DELTA turns right."""
    return -max(-TURN_PER_FRAME, min(TURN_PER_FRAME, turn))


def player_position(game):
    return game.get_game_variable(vzd.GameVariable.POSITION_X), game.get_game_variable(vzd.GameVariable.POSITION_Y)


def visible_target(game, dead):
    state = game.get_state()
    if state is None:
        return None
    here = player_position(game)
    facing = game.get_game_variable(vzd.GameVariable.ANGLE)
    best = None
    for label in state.labels:
        if label.object_name not in MONSTERS or label.object_id in dead or label.width < 8:
            continue
        spot = (label.object_position_x, label.object_position_y)
        distance = math.hypot(spot[0] - here[0], spot[1] - here[1])
        in_front = abs(shortest_turn(heading_to(here, spot), facing)) <= MAX_SWING
        if distance <= ENGAGE_RANGE and in_front and (best is None or distance < best[0]):
            best = (distance, label.object_id, label.object_name)
    return best


def object_position(game, object_id):
    state = game.get_state()
    if state is None:
        return None
    for thing in state.objects:
        if thing.id == object_id:
            return thing.position_x, thing.position_y
    return None


def in_view(game, object_id):
    state = game.get_state()
    return state is not None and any(label.object_id == object_id for label in state.labels)


def camera_inside_a_sprite(game, screen_width):
    """Gliding by warp walks through things; a non-monster sprite wider than a quarter of the screen is a close-up blob."""
    state = game.get_state()
    return state is not None and any(
        label.width > screen_width / 4 and label.object_name not in MONSTERS and label.object_name != "DoomPlayer" for label in state.labels)


def fight(game, target_id, dead, out, saved):
    kills_before = game.get_game_variable(vzd.GameVariable.KILLCOUNT)
    shots = frames = 0
    hidden_frames = 0
    while frames < MAX_FIGHT_FRAMES and hidden_frames < MAX_HIDDEN_FRAMES:
        spot = object_position(game, target_id)
        if spot is None:
            break
        facing = game.get_game_variable(vzd.GameVariable.ANGLE)
        turn = shortest_turn(heading_to(player_position(game), spot), facing)
        visible = in_view(game, target_id)
        hidden_frames = 0 if visible else hidden_frames + 1
        aimed = visible and abs(turn) <= AIM_TOLERANCE
        game.make_action([turn_input(turn), 1 if aimed else 0])
        shots += aimed
        frames += 1
        if VERBOSE:
            print(f"  aim target={target_id} turn={turn:.1f} visible={visible} fired={aimed}", flush=True)
        saved += save_frame(game, out / f"demo_{saved:04d}.png")
        if game.get_game_variable(vzd.GameVariable.KILLCOUNT) > kills_before:
            for _ in range(18):
                game.make_action([0, 0])
                saved += save_frame(game, out / f"demo_{saved:04d}.png")
            break
    dead.add(target_id)
    print(f"fight target={target_id} frames={frames} trigger_frames={shots} "
          f"kills={game.get_game_variable(vzd.GameVariable.KILLCOUNT):.0f}", flush=True)
    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iwad", required=True)
    parser.add_argument("--pwad", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--step", type=float, default=12.0, help="units moved per frame")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text())
    route = shortest_route(data)
    waypoints = [tuple(data["nodes"][node]) for node in route]
    points = points_along(waypoints, args.step)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"route: {len(route)} nodes, {len(points)} glide points", flush=True)

    game = build_demo_game(args.iwad, args.pwad, data["map"], args.width, args.height)
    game.new_episode()
    for command in ["god", "give shotgun", "give ammo", "use Shotgun"]:
        game.send_game_command(command)
    dead = set()
    saved = skipped_close_ups = 0
    try:
        for _ in range(20):
            game.make_action([0, 0])
            saved += save_frame(game, out / f"demo_{saved:04d}.png")
        for index, here in enumerate(points):
            target = visible_target(game, dead)
            if target is not None:
                saved = fight(game, target[1], dead, out, saved)
            ahead = points[min(len(points) - 1, index + max(1, round(LOOK_AHEAD / args.step)))]
            game.send_game_command(f"warp {here[0]:.1f} {here[1]:.1f}")
            facing = game.get_game_variable(vzd.GameVariable.ANGLE)
            turn = shortest_turn(heading_to(here, ahead), facing) if ahead != here else 0
            game.make_action([turn_input(turn), 0])
            if camera_inside_a_sprite(game, args.width):
                skipped_close_ups += 1
                continue
            saved += save_frame(game, out / f"demo_{saved:04d}.png")
        print(f"skipped {skipped_close_ups} frames where the camera passed through a barrel or corpse", flush=True)
    finally:
        print(f"done: frames_saved={saved} kills={game.get_game_variable(vzd.GameVariable.KILLCOUNT):.0f}",
              flush=True)
        game.close()


if __name__ == "__main__":
    main()
