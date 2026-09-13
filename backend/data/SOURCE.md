# Map data source

`helsinki.osm.pbf` is a real OpenStreetMap extract covering central Helsinki,
Finland (bbox 60.1642..60.1791 N, 24.9352..24.9534 E).

It is redistributed from the `pyrosm` Python package (`pyrosm/data/Helsinki.osm.pbf`),
which ships it as sample data.

* Data source: OpenStreetMap contributors
* Licence: Open Database Licence (ODbL) 1.0 — https://www.openstreetmap.org/copyright
* Attribution "© OpenStreetMap contributors" is rendered on every map surface in
  the product.

FleetBeat does not fabricate roads. Every street, building, junction and named
place in the demo comes from this extract. The routing graph, the vector tiles
and the geocoder are all derived from it by `scripts/build_basemap.py`.
