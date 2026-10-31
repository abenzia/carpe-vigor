"""Build smooth, neutral mannequins from pinned MakeHuman CC0 graphical assets.

No MakeHuman application code is used. Run with Python's standard library.
"""
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1] / 'static/models/mannequin'
SOURCE = ROOT / 'source'
COMMIT = 'a8bc2d54ff0ac92e78ff71431b1023eda42bf482'


def read_base():
    vertices, faces, group = [], [], ''
    for line in (SOURCE / 'base.obj').read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'v':
            vertices.append(tuple(map(float, fields[1:4])))
        elif fields[0] == 'g':
            group = fields[1]
        elif fields[0] == 'f' and group in ('body', 'helper-l-eye', 'helper-r-eye'):
            faces.append([int(s.split('/')[0]) - 1 for s in fields[1:]])
    return vertices, faces


def average(points):
    return tuple(sum(p[k] for p in points) / len(points) for k in range(3))


def subdivide(vertices, faces):
    """One Catmull–Clark pass preserves the natural continuous skin surface."""
    centers = [average([vertices[v] for v in face]) for face in faces]
    edges, around, neighbors = {}, [[] for _ in vertices], [set() for _ in vertices]
    for fi, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            edges.setdefault(tuple(sorted((a, b))), []).append(fi)
            around[a].append(fi)
            neighbors[a].add(b)
            neighbors[b].add(a)
    result = []
    boundary = [[] for _ in vertices]
    for (a, b), fs in edges.items():
        if len(fs) == 1:
            boundary[a].append(b)
            boundary[b].append(a)
    for i, v in enumerate(vertices):
        if boundary[i]:
            b = average([vertices[j] for j in boundary[i]])
            result.append(tuple(.75 * v[k] + .25 * b[k] for k in range(3)))
        elif around[i]:
            n = len(around[i])
            f = average([centers[j] for j in around[i]])
            r = average([average([v, vertices[j]]) for j in neighbors[i]])
            result.append(tuple((f[k] + 2 * r[k] + (n - 3) * v[k]) / n for k in range(3)))
        else:
            result.append(v)
    edge_ids = {}
    for (a, b), fs in edges.items():
        edge_ids[(a, b)] = len(result)
        result.append(average([vertices[a], vertices[b]] + [centers[j] for j in fs]) if len(fs) > 1 else average([vertices[a], vertices[b]]))
    face_start = len(result)
    result.extend(centers)
    quads = []
    for fi, face in enumerate(faces):
        for i, a in enumerate(face):
            b, previous = face[(i + 1) % len(face)], face[i - 1]
            quads.append([a, edge_ids[tuple(sorted((a, b)))], face_start + fi, edge_ids[tuple(sorted((previous, a)))]])
    return result, quads


def smoothstep(a, b, x):
    t = max(0, min(1, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def write_glb(path, vertices, faces):
    triangles = []
    for f in faces:
        for i in range(1, len(f) - 1):
            triangles.extend((f[0], f[i], f[i + 1]))
    pos = struct.pack('<' + 'f' * (len(vertices) * 3), *(x for v in vertices for x in v))
    idx = struct.pack('<' + 'I' * len(triangles), *triangles)
    metadata = {
        'asset': {'version': '2.0', 'generator': 'Carpe Vigor mannequin builder', 'copyright': 'MakeHuman CC0 graphical assets; adapted for Carpe Vigor'},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': path.stem}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
        'materials': [{'name': 'Matte porcelain', 'pbrMetallicRoughness': {'baseColorFactor': [.72, .69, .62, 1], 'metallicFactor': .04, 'roughnessFactor': .68}}],
        'buffers': [{'byteLength': len(pos) + len(idx)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(pos), 'target': 34962}, {'buffer': 0, 'byteOffset': len(pos), 'byteLength': len(idx), 'target': 34963}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(vertices), 'type': 'VEC3', 'min': [min(v[k] for v in vertices) for k in range(3)], 'max': [max(v[k] for v in vertices) for k in range(3)]}, {'bufferView': 1, 'componentType': 5125, 'count': len(triangles), 'type': 'SCALAR'}],
    }
    j = json.dumps(metadata, separators=(',', ':')).encode()
    j += b' ' * (-len(j) % 4)
    binary = pos + idx
    binary += b'\0' * (-len(binary) % 4)
    path.write_bytes(struct.pack('<III', 0x46546C67, 2, 28 + len(j) + len(binary)) + struct.pack('<II', len(j), 0x4E4F534A) + j + struct.pack('<II', len(binary), 0x004E4942) + binary)
    return {'path': path.name, 'vertices': len(vertices), 'triangles': len(triangles) // 3, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    base, original_faces = read_base()
    used = sorted({i for f in original_faces for i in f})
    remap = {v: i for i, v in enumerate(used)}
    faces = [[remap[v] for v in f] for f in original_faces]
    assets = []
    for kind in ('male', 'female', 'male-fit', 'female-fit'):
        sex = kind.split('-')[0]
        full = [list(v) for v in base]
        # Equal blend of the three source shape families; no identity is inferred.
        for origin in ('african', 'asian', 'caucasian'):
            for line in (SOURCE / f'{origin}-{sex}-young.target').read_text().splitlines():
                if line.strip() and not line.startswith('#'):
                    fields = line.split()
                    if len(fields) == 4:
                        i = int(fields[0])
                        for k in range(3):
                            full[i][k] += float(fields[k + 1]) / 3
        if kind.endswith('-fit'):
            # A restrained artistic muscle blend, not a health/fitness assessment.
            blend = .35 if sex == 'male' else .30
            target = SOURCE / f'universal-{sex}-young-maxmuscle-averageweight.target'
            for line in target.read_text().splitlines():
                fields = line.split()
                if len(fields) == 4 and not line.startswith('#'):
                    i = int(fields[0])
                    for k in range(3):
                        full[i][k] += float(fields[k + 1]) * blend
        vertices = []
        for i in used:
            x, y, z = full[i]
            # Relax the source A-pose, blending the shoulder transition smoothly.
            # Weights follow the shared base topology, so morphing a hand cannot
            # change its pose weight partway through a finger.
            bx, by, _ = base[i]
            shoulder_blend = smoothstep(1.25, 2.1, abs(bx)) * smoothstep(2, 3, by)
            hand_blend = smoothstep(2.1, 2.6, abs(bx)) * smoothstep(0, .6, by)
            weight = max(shoulder_blend, hand_blend)
            side = 1 if x >= 0 else -1
            theta = -.43 * side * weight
            dx, dy = x - side * 1.65, y - 5.15
            x = side * 1.65 + math.cos(theta) * dx - math.sin(theta) * dy
            y = 5.15 + math.sin(theta) * dx + math.cos(theta) * dy
            vertices.append((x, y, z))
        vertices, refined_faces = subdivide(vertices, faces)
        ymin = min(v[1] for v in vertices)
        scale = 1.704 / (max(v[1] for v in vertices) - ymin)
        vertices = [(x * scale, (y - ymin) * scale, z * scale) for x, y, z in vertices]
        section = [v for v in vertices if abs(v[1] - 1.704 * .59) < .018 and abs(v[0]) < .18]
        zcenter = (min(v[2] for v in section) + max(v[2] for v in section)) / 2
        vertices = [(x, y, z - zcenter) for x, y, z in vertices]
        assets.append(write_glb(ROOT / f'{kind}.glb', vertices, refined_faces))
    sources = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(SOURCE.iterdir())]
    manifest = {'source': 'https://github.com/makehumancommunity/makehuman', 'commit': COMMIT, 'license': 'CC0-1.0', 'adaptations': 'Skin and eye surfaces only; equal blend of three adult shape families for each sex; relaxed arms; Catmull–Clark subdivision; normalized reference height; matte monochrome presentation. Illustrative, not a body scan or medical reconstruction.', 'assets': assets, 'sources': sources}
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(assets, indent=2))


if __name__ == '__main__':
    main()
