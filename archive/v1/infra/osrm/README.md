# OSRM routing engine

FleetBeat uses a self-hosted [OSRM](https://project-osrm.org/) instance for
real point-to-point and multi-stop routing with ETAs (Section 3 of the product
spec). Routing is **real**; only the vehicle position feed is simulated.

OSRM needs an OpenStreetMap extract to be downloaded and pre-processed before
it can serve requests, so it sits behind a Compose profile rather than in the
default `docker compose up` — a first-run download of a continent-sized
extract would otherwise block the whole stack.

## One-time setup

Pick the smallest extract that covers your operating region from
[Geofabrik](https://download.geofabrik.de/). The steps below use the
Netherlands as an example; substitute your own region and keep the file name
consistent with `OSRM_REGION` in `.env`.

```bash
cd infra/osrm/data

# 1. Download the extract (~1 GB for a mid-sized country).
wget https://download.geofabrik.de/europe/netherlands-latest.osm.pbf -O region.osm.pbf

# 2. Extract, partition and customise using the car profile (MLD pipeline).
docker run --rm -v "$PWD:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v "$PWD:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-partition /data/region.osrm
docker run --rm -v "$PWD:/data" ghcr.io/project-osrm/osrm-backend \
  osrm-customize /data/region.osrm
```

Pre-processing is memory-hungry — budget roughly 2× the extract size in RAM.

## Running

```bash
docker compose --profile routing up osrm
```

The API reaches it at `http://osrm:5000` (`OSRM_BASE_URL`). Verify with:

```bash
curl "http://localhost:5000/route/v1/driving/4.9041,52.3676;4.4777,51.9244?overview=full"
```

## Notes

- The `car.lua` profile is the right default for vans and light trucks. Heavy
  goods vehicles need a custom profile with weight and height restrictions —
  out of scope for MVP.
- `infra/osrm/data/` is gitignored: the extract and its processed artefacts are
  large generated files.
- Full multi-stop route *optimization* (traveling-salesman stop sequencing) is
  explicitly out of scope for MVP. OSRM's `/trip` service would be the natural
  place to add it later.
