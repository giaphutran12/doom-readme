"""Build the walkable position graph for one level and write a patched copy of its sectors.

Steps, all straight from the WAD (no game engine needed):
  1. Open every door and lift permanently, so a static graph can reach the whole level.
  2. Flood-fill a fine 16-unit lattice outward from the player start (walls, steps and headroom
     respected). This is the walkable floor.
  3. Place nodes: first the best-aligned 64-unit grid, then fill-in nodes where corridors and
     doorways fall between grid points.
  4. Link each node to its nearest walkable neighbour in each of the 8 compass directions.
  5. Keep only nodes reachable from the start through those links.

Writes map_data.json and patched_<MAP>.wad.
"""

import argparse
import json
import math
import struct
from collections import deque

import wad

GRID_STEP = 64
LATTICE_STEP = 16
FILL_SPACING = 48
LINK_MIN = 24
LINK_MAX = 112
LINK_CONE_DEGREES = 25
MIN_HEADROOM = 56
MAX_STEP_HEIGHT = 24
WALL_CLEARANCE = 18
EXIT_REACH = 112
BUCKET = 128
ANGLES = [0, 90, 180, 270]
COMPASS = [0, 45, 90, 135, 180, 225, 270, 315]
LIFT_SPECIALS = {10, 21, 22, 62, 88, 120, 121, 122, 123}


def line_sectors(level, line):
    front = level.sidedefs[line[5]][5] if line[5] != wad.NO_SIDEDEF else None
    back = level.sidedefs[line[6]][5] if line[6] != wad.NO_SIDEDEF else None
    return front, back


def neighbours_by_sector(level):
    touching = {i: set() for i in range(len(level.sectors))}
    for line in level.linedefs:
        front, back = line_sectors(level, line)
        if front is not None and back is not None and front != back:
            touching[front].add(back)
            touching[back].add(front)
    return touching


def open_doors_and_lifts(level):
    touching = neighbours_by_sector(level)
    lift_tags = {line[4] for line in level.linedefs if line[3] in LIFT_SPECIALS and line[4]}
    opened = {"doors": [], "lifts": []}
    for index, sector in enumerate(level.sectors):
        floor, ceiling = sector[0], sector[1]
        around = [level.sectors[n] for n in touching[index]]
        if sector[6] in lift_tags:
            opened["lifts"].append(index)
        if ceiling - floor < MIN_HEADROOM and around:
            roomy_ceilings = [n[1] for n in around if n[1] - floor >= MIN_HEADROOM]
            if roomy_ceilings:
                sector[1] = max(roomy_ceilings)
                opened["doors"].append(index)
    return opened


def write_patched_wad(level, path):
    packed = b"".join(
        struct.pack("<hh8s8shhh", s[0], s[1], s[2], s[3], s[4], s[5], s[6]) for s in level.sectors
    )
    lumps = [(level.map_name, b"")]
    for name in ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS", "NODES",
                 "SECTORS", "REJECT", "BLOCKMAP"]:
        lumps.append((name, packed if name == "SECTORS" else level.raw_lumps[name]))
    wad.write_pwad(path, lumps)


def segment_crossing(p1, p2, q1, q2):
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    d2x, d2y = q2[0] - q1[0], q2[1] - q1[1]
    denominator = d1x * d2y - d1y * d2x
    if denominator == 0:
        return False
    t = ((q1[0] - p1[0]) * d2y - (q1[1] - p1[1]) * d2x) / denominator
    u = ((q1[0] - p1[0]) * d1y - (q1[1] - p1[1]) * d1x) / denominator
    return 0 <= t <= 1 and 0 <= u <= 1


def distance_to_segment(point, a, b):
    ax, ay = a
    bx, by = b
    length_squared = (bx - ax) ** 2 + (by - ay) ** 2
    if length_squared == 0:
        return math.hypot(point[0] - ax, point[1] - ay)
    t = max(0, min(1, ((point[0] - ax) * (bx - ax) + (point[1] - ay) * (by - ay)) / length_squared))
    return math.hypot(point[0] - (ax + t * (bx - ax)), point[1] - (ay + t * (by - ay)))


class Walkability:
    def __init__(self, level, lift_sectors=()):
        self.level = level
        self.lift_sectors = set(lift_sectors)
        self.wall_buckets = {}
        self.portal_buckets = {}
        for line in level.linedefs:
            a = level.vertexes[line[0]]
            b = level.vertexes[line[1]]
            front, back = line_sectors(level, line)
            if front is None or back is None or line[2] & wad.LINE_IMPASSABLE:
                self._add(self.wall_buckets, (a, b))
            else:
                self._add(self.portal_buckets, (a, b, front, back))

    @staticmethod
    def _cells(low_x, low_y, high_x, high_y):
        for cx in range(int(low_x // BUCKET), int(high_x // BUCKET) + 1):
            for cy in range(int(low_y // BUCKET), int(high_y // BUCKET) + 1):
                yield cx, cy

    def _add(self, buckets, item):
        a, b = item[0], item[1]
        margin = WALL_CLEARANCE + 2
        for cell in self._cells(min(a[0], b[0]) - margin, min(a[1], b[1]) - margin,
                                max(a[0], b[0]) + margin, max(a[1], b[1]) + margin):
            buckets.setdefault(cell, []).append(item)

    def _near(self, buckets, start, end):
        seen = {}
        for cell in self._cells(min(start[0], end[0]), min(start[1], end[1]),
                                max(start[0], end[0]), max(start[1], end[1])):
            for item in buckets.get(cell, ()):
                seen[id(item)] = item
        return seen.values()

    def standing_sector(self, x, y):
        sector_index = self.level.sector_at(x, y)
        floor, ceiling = self.level.sectors[sector_index][0], self.level.sectors[sector_index][1]
        if ceiling - floor < MIN_HEADROOM:
            return None
        for a, b in self.wall_buckets.get((x // BUCKET, y // BUCKET), ()):
            if distance_to_segment((x, y), a, b) < WALL_CLEARANCE:
                return None
        return sector_index

    def can_walk(self, start, end):
        for a, b in self._near(self.wall_buckets, start, end):
            if segment_crossing(start, end, a, b):
                return False
        for a, b, front, back in self._near(self.portal_buckets, start, end):
            if not segment_crossing(start, end, a, b):
                continue
            if front in self.lift_sectors or back in self.lift_sectors:
                continue
            front_sector = self.level.sectors[front]
            back_sector = self.level.sectors[back]
            if abs(front_sector[0] - back_sector[0]) > MAX_STEP_HEIGHT:
                return False
            if min(front_sector[1], back_sector[1]) - max(front_sector[0], back_sector[0]) < MIN_HEADROOM:
                return False
        return True


def lattice_flood_fill(walk, start_xy):
    snapped = (round(start_xy[0] / LATTICE_STEP) * LATTICE_STEP, round(start_xy[1] / LATTICE_STEP) * LATTICE_STEP)
    if walk.standing_sector(*snapped) is None:
        raise SystemExit(f"player start {start_xy} is not standable on the lattice")
    order = [snapped]
    seen = {snapped}
    queue = deque([snapped])
    offsets = [(dx * LATTICE_STEP, dy * LATTICE_STEP) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
    while queue:
        x, y = queue.popleft()
        for dx, dy in offsets:
            target = (x + dx, y + dy)
            if target in seen:
                continue
            seen.add(target)
            if walk.standing_sector(*target) is None or not walk.can_walk((x, y), target):
                continue
            order.append(target)
            queue.append(target)
    return order


def pick_nodes(region_in_bfs_order):
    region = set(region_in_bfs_order)
    best_origin, best_count = (0, 0), -1
    for ox in range(0, GRID_STEP, LATTICE_STEP):
        for oy in range(0, GRID_STEP, LATTICE_STEP):
            count = sum(1 for x, y in region if (x - ox) % GRID_STEP == 0 and (y - oy) % GRID_STEP == 0)
            if count > best_count:
                best_origin, best_count = (ox, oy), count
    ox, oy = best_origin
    nodes = [p for p in region_in_bfs_order if (p[0] - ox) % GRID_STEP == 0 and (p[1] - oy) % GRID_STEP == 0]
    hashed = {}

    def hash_cell(p):
        return (p[0] // FILL_SPACING, p[1] // FILL_SPACING)

    def crowded(p):
        cx, cy = hash_cell(p)
        for nx in (cx - 1, cx, cx + 1):
            for ny in (cy - 1, cy, cy + 1):
                for q in hashed.get((nx, ny), ()):
                    if math.hypot(p[0] - q[0], p[1] - q[1]) < FILL_SPACING:
                        return True
        return False

    for p in nodes:
        hashed.setdefault(hash_cell(p), []).append(p)
    grid_count = len(nodes)
    for p in region_in_bfs_order:
        if not crowded(p):
            nodes.append(p)
            hashed.setdefault(hash_cell(p), []).append(p)
    return nodes, best_origin, grid_count


def link_nodes(walk, nodes):
    by_cell = {}
    for index, (x, y) in enumerate(nodes):
        by_cell.setdefault((x // LINK_MAX, y // LINK_MAX), []).append(index)
    links = []
    for index, (x, y) in enumerate(nodes):
        best = {angle: (1e9, -1) for angle in COMPASS}
        cx, cy = x // LINK_MAX, y // LINK_MAX
        for nx in (cx - 1, cx, cx + 1):
            for ny in (cy - 1, cy, cy + 1):
                for other in by_cell.get((nx, ny), ()):
                    if other == index:
                        continue
                    ox, oy = nodes[other]
                    distance = math.hypot(ox - x, oy - y)
                    if not LINK_MIN <= distance <= LINK_MAX:
                        continue
                    bearing = math.degrees(math.atan2(oy - y, ox - x)) % 360
                    for angle in COMPASS:
                        off = abs((bearing - angle + 180) % 360 - 180)
                        if off > LINK_CONE_DEGREES:
                            continue
                        ideal = GRID_STEP if angle % 90 == 0 else GRID_STEP * math.sqrt(2)
                        lateral = distance * math.sin(math.radians(off))
                        score = abs(distance - ideal) + 1.5 * lateral
                        if score < best[angle][0] and walk.can_walk((x, y), (ox, oy)):
                            best[angle] = (score, other)
        links.append([best[angle][1] for angle in COMPASS])
    return links


def reachable_from(links, start_index):
    seen = {start_index}
    queue = deque([start_index])
    while queue:
        for target in links[queue.popleft()]:
            if target >= 0 and target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wad", required=True)
    parser.add_argument("--map", default="E1M1")
    parser.add_argument("--out", default=".")
    args = parser.parse_args()

    level = wad.load_level(args.wad, args.map)
    opened = open_doors_and_lifts(level)
    print(f"opened doors={len(opened['doors'])} lifts={len(opened['lifts'])}")
    write_patched_wad(level, f"{args.out}/patched_{args.map}.wad")

    start_thing = next(t for t in level.things if t[3] == 1)
    start_xy = (start_thing[0], start_thing[1])
    walk = Walkability(level, opened["lifts"])

    region = lattice_flood_fill(walk, start_xy)
    print(f"walkable lattice points={len(region)} (spacing {LATTICE_STEP})")
    nodes, origin, grid_count = pick_nodes(region)
    print(f"nodes={len(nodes)} (grid {grid_count} at origin {origin}, fill-in {len(nodes) - grid_count})")

    links = link_nodes(walk, nodes)
    spawn_index = min(range(len(nodes)), key=lambda i: math.hypot(nodes[i][0] - start_xy[0], nodes[i][1] - start_xy[1]))
    keep = reachable_from(links, spawn_index)
    print(f"reachable through links={len(keep)} of {len(nodes)}")

    remap = {old: new for new, old in enumerate(sorted(keep))}
    kept_nodes = [nodes[old] for old in sorted(keep)]
    kept_links = [[remap.get(t, -1) for t in links[old]] for old in sorted(keep)]
    exits = [(level.vertexes[l[0]], level.vertexes[l[1]]) for l in level.linedefs if l[3] in wad.EXIT_SPECIALS]
    exit_indexes = [
        i for i, p in enumerate(kept_nodes) if any(distance_to_segment(p, a, b) <= EXIT_REACH for a, b in exits)
    ]
    print(f"nodes next to the exit={len(exit_indexes)}")

    data = {
        "map": args.map,
        "angles": ANGLES,
        "compass": COMPASS,
        "spawn": {"node": remap[spawn_index], "angle": min(ANGLES, key=lambda a: abs(a - start_thing[2]))},
        "nodes": [list(p) for p in kept_nodes],
        "links": kept_links,
        "exit_nodes": exit_indexes,
        "exit_lines": [[list(a), list(b)] for a, b in exits],
    }
    with open(f"{args.out}/map_data.json", "w") as handle:
        json.dump(data, handle, separators=(",", ":"))
    print(f"wrote map_data.json: {len(kept_nodes)} nodes, {len(kept_nodes) * len(ANGLES)} frames")


if __name__ == "__main__":
    main()
