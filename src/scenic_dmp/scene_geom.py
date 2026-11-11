"""Scenes and maps as plain JSON geometry, for drawing top-down in the browser.

Coordinates are Scenic's: x right, y up, metres. A heading of 0 faces +y and
grows counterclockwise.
"""

import math

import shapely
import shapely.geometry

# Map layers drawn under the objects, bottom to top.
MAP_LAYERS = ["roadRegion", "intersectionRegion", "shoulderRegion", "sidewalkRegion", "crossingRegion"]


def scene_json(scene):
    """Each object's class, pose, size and footprint polygon, plus the ego flag."""
    objects = []
    for obj in scene.objects:
        x, y = float(obj.position.x), float(obj.position.y)
        heading = float(obj.heading)
        width, length = float(obj.width), float(obj.length)
        objects.append({
            "cls": type(obj).__name__,
            "x": round(x, 3),
            "y": round(y, 3),
            "heading": heading,
            "width": width,
            "length": length,
            "footprint": _footprint(obj, x, y, heading, width, length),
            "ego": obj is scene.egoObject,
        })
    return {"objects": objects}


def _footprint(obj, x, y, heading, width, length):
    try:
        poly = obj._boundingPolygon
        if poly.geom_type != "Polygon":
            poly = poly.convex_hull
        coords = list(poly.exterior.coords)[:-1]
        if len(coords) >= 3:
            return [[round(px, 3), round(py, 3)] for px, py, *_ in coords]
    except Exception:
        pass
    # A rectangle from the pose, if Scenic can't give a footprint.
    c, s = math.cos(heading), math.sin(heading)
    out = []
    for dx, dy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
        lx, ly = dx * width / 2, dy * length / 2
        out.append([round(x + lx * c - ly * s, 3), round(y + lx * s + ly * c, 3)])
    return out


def map_json(workspace, tolerance=0.25):
    """Road-network polygons of a driving workspace, or None for other workspaces.

    Returns {"layers": {name: [polygon, ...]}, "bounds": [minx, miny, maxx, maxy]},
    where a polygon is a list of rings and a ring a flat [x0, y0, x1, y1, ...] list.
    """
    network = getattr(workspace, "network", None)
    if network is None:
        return None
    layers = {}
    bounds = None
    for name in MAP_LAYERS:
        region = getattr(network, name, None)
        geom = getattr(region, "polygons", None)
        if geom is None or geom.is_empty:
            continue
        geom = shapely.simplify(geom, tolerance, preserve_topology=True)
        layers[name] = _polygons(geom)
        b = geom.bounds
        bounds = b if bounds is None else (
            min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3])
        )
    if not layers:
        return None
    return {"layers": layers, "bounds": [round(v, 2) for v in bounds]}


def _polygons(geom):
    if geom.geom_type == "Polygon":
        polys = [geom]
    elif hasattr(geom, "geoms"):
        polys = [g for g in geom.geoms if g.geom_type == "Polygon"]
    else:
        polys = []
    return [[_ring(p.exterior), *(_ring(r) for r in p.interiors)] for p in polys if not p.is_empty]


def _ring(ring):
    out = []
    for x, y, *_ in ring.coords:
        out.append(round(x, 2))
        out.append(round(y, 2))
    return out
