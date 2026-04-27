#!/usr/bin/env python3
"""Re-clip greenspaces.geojson to NW London (8 boroughs, no Camden) + 200m buffer.

Background: the existing greenspaces.geojson was built when the dashboard
included Camden. Now Camden is purged from the borough scope, but greenspace
footprints that sit inside Camden still render on the map. This script
recreates the layer using the current borough geometry plus a 200m outer
buffer (so a park straddling the boundary stays visible at its NWL edge).

Inputs (already on disk):
    data/boundaries/boroughs.geojson   — 8 NWL borough polygons
    greenspaces.geojson                — current greenspace layer

Output:
    greenspaces.geojson                — overwritten in place

Dependencies:
    pip install shapely pyproj   (already required by fetch_all_data.py)

Run:
    python scripts/reclip_greenspaces.py
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO / 'data' / 'boundaries' / 'boroughs.geojson'
GREENSPACES = REPO / 'greenspaces.geojson'
BUFFER_M = 200  # metres — keeps greenspaces straddling the NWL edge visible


def main():
    try:
        from shapely.geometry import shape, mapping
        from shapely.ops import unary_union, transform
        import pyproj
    except ImportError as e:
        raise SystemExit(
            f"Missing dep ({e.name}). Run: pip install shapely pyproj"
        )

    if not BOUNDARIES.exists():
        raise SystemExit(
            f"Boundary file not found: {BOUNDARIES}\n"
            "Re-run fetch_all_data.py to download boundaries first."
        )
    if not GREENSPACES.exists():
        raise SystemExit(f"Greenspace file not found: {GREENSPACES}")

    print(f"loading boroughs: {BOUNDARIES}")
    with open(BOUNDARIES, encoding='utf-8') as f:
        bb = json.load(f)
    nwl_polys = [shape(f['geometry']) for f in bb['features']]
    print(f"  {len(nwl_polys)} borough polygons")

    nwl_union_wgs = unary_union(nwl_polys)

    # Buffer in metres requires projecting to BNG (EPSG:27700), buffering, and
    # projecting back to WGS84.
    project_to_bng   = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform
    project_to_wgs84 = pyproj.Transformer.from_crs(27700, 4326, always_xy=True).transform
    nwl_union_bng = transform(project_to_bng, nwl_union_wgs)
    nwl_buffered_bng = nwl_union_bng.buffer(BUFFER_M)
    nwl_clip = transform(project_to_wgs84, nwl_buffered_bng)
    print(f"  buffered NWL footprint: {nwl_clip.bounds}")

    print(f"\nloading greenspaces: {GREENSPACES}")
    with open(GREENSPACES, encoding='utf-8') as f:
        gs = json.load(f)
    in_count = len(gs['features'])
    print(f"  {in_count} input features")

    out = []
    for feat in gs['features']:
        try:
            g = shape(feat['geometry'])
        except Exception:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        if not g.intersects(nwl_clip):
            continue
        # Clip to the buffered NWL boundary so we don't render any portion
        # outside the buffer (Camden interiors etc.).
        clipped = g.intersection(nwl_clip)
        if clipped.is_empty:
            continue
        # Drop sliver-sized fragments left over after clipping. ~25 m² is
        # noise; real greenspaces are at least a few hundred m².
        try:
            clipped_bng = transform(project_to_bng, clipped)
            if clipped_bng.area < 25:
                continue
        except Exception:
            pass
        out.append({
            'type': 'Feature',
            'properties': feat.get('properties') or {},
            'geometry': mapping(clipped),
        })

    print(f"  {len(out)} features after clip (dropped {in_count - len(out)})")

    GREENSPACES.write_text(
        json.dumps({'type': 'FeatureCollection', 'features': out},
                   ensure_ascii=False, allow_nan=False),
        encoding='utf-8',
    )
    print(f"\nwrote {GREENSPACES} ({GREENSPACES.stat().st_size:,} bytes)")


if __name__ == '__main__':
    main()
