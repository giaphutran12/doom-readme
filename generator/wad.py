"""Minimal WAD reader/writer and E1M1 level parser. No dependencies."""

import struct
from dataclasses import dataclass
from pathlib import Path

NO_SIDEDEF = 0xFFFF
LINE_IMPASSABLE = 0x0001
EXIT_SPECIALS = {11, 51, 52, 124}
SUBSECTOR_FLAG = 0x8000


def read_wad(path):
    data = Path(path).read_bytes()
    kind, count, directory_offset = struct.unpack_from("<4sii", data, 0)
    lumps = []
    for index in range(count):
        offset, size, raw_name = struct.unpack_from("<ii8s", data, directory_offset + 16 * index)
        name = raw_name.split(b"\0")[0].decode("ascii")
        lumps.append((name, data[offset:offset + size]))
    return kind.decode("ascii"), lumps


def write_pwad(path, lumps):
    body = b""
    directory = b""
    offset = 12
    for name, payload in lumps:
        directory += struct.pack("<ii8s", offset, len(payload), name.encode("ascii"))
        body += payload
        offset += len(payload)
    header = struct.pack("<4sii", b"PWAD", len(lumps), 12 + len(body))
    Path(path).write_bytes(header + body + directory)


def find_map_lumps(lumps, map_name):
    start = next(i for i, (name, _) in enumerate(lumps) if name == map_name)
    found = {}
    for name, payload in lumps[start + 1:start + 12]:
        found[name] = payload
    return found


def unpack_all(fmt, payload):
    return list(struct.iter_unpack(fmt, payload))


@dataclass
class Level:
    map_name: str
    things: list
    linedefs: list
    sidedefs: list
    vertexes: list
    segs: list
    subsectors: list
    nodes: list
    sectors: list
    raw_lumps: dict

    def sector_at(self, x, y):
        child = len(self.nodes) - 1
        while not child & SUBSECTOR_FLAG:
            node_x, node_y, delta_x, delta_y, *_boxes, right_child, left_child = self.nodes[child]
            on_back = (y - node_y) * delta_x >= (x - node_x) * delta_y
            child = left_child if on_back else right_child
        _count, first_seg = self.subsectors[child & ~SUBSECTOR_FLAG]
        _v1, _v2, _angle, linedef_index, direction, _offset = self.segs[first_seg]
        linedef = self.linedefs[linedef_index]
        sidedef_index = linedef[6] if direction else linedef[5]
        return self.sidedefs[sidedef_index][5]


def load_level(wad_path, map_name):
    _kind, lumps = read_wad(wad_path)
    raw = find_map_lumps(lumps, map_name)
    return Level(
        map_name=map_name,
        things=unpack_all("<hhHHH", raw["THINGS"]),
        linedefs=unpack_all("<HHHHHHH", raw["LINEDEFS"]),
        sidedefs=unpack_all("<hh8s8s8sH", raw["SIDEDEFS"]),
        vertexes=unpack_all("<hh", raw["VERTEXES"]),
        segs=unpack_all("<HHhHhh", raw["SEGS"]),
        subsectors=unpack_all("<HH", raw["SSECTORS"]),
        nodes=unpack_all("<hhhh8hHH", raw["NODES"]),
        sectors=[list(s) for s in unpack_all("<hh8s8shhh", raw["SECTORS"])],
        raw_lumps=raw,
    )
