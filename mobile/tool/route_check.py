"""Check every API path the Flutter app calls exists in the live OpenAPI schema.

Without a Flutter SDK nothing compiles the driver app, and a wrong path is
invisible until a driver taps the screen. This is the cheap substitute: pull
the schema the API actually serves and match each call against it.
"""
import json, pathlib, re, sys, urllib.request

import os

BASE = os.environ.get("FLEETBEAT_API_BASE_URL", "http://127.0.0.1:8000/api/v1")
LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"
schema = json.loads(urllib.request.urlopen(f"{BASE}/openapi.json").read())
served = set(schema["paths"])

# "/driver/tasks/{id}/accept" style: turn a served template into a matcher.
matchers = [
    (path, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$"))
    for path in served
]

calls = []
for file in sorted(LIB.rglob("*.dart")):
    for match in re.finditer(r"api\.(get|post)\(\s*'([^']+)'", file.read_text()):
        calls.append((file, match.group(1).upper(), match.group(2)))

def candidates(raw: str) -> list[str]:
    """Expand a Dart-interpolated path into the concrete paths it can produce.

    A trailing interpolation is usually a verb chosen from a fixed set
    (nextActionPath -> accept/start/complete), not a path parameter, so
    substituting one wildcard would wrongly report it missing. Every literal
    a single-word interpolation can hold is collected from the Dart source.
    """
    verbs = set()
    for file in LIB.rglob("*.dart"):
        for match in re.finditer(r"=>\s*'([a-z_]+)'", file.read_text()):
            verbs.add(match.group(1))

    body = re.sub(r"\$\{[^}]+\}", "\x00", raw)
    if re.search(r"\$\w+$", body):
        stem = re.sub(r"\$\w+$", "", body)
        return [
            "/api/v1" + (stem + verb).replace("\x00", "x") for verb in sorted(verbs)
        ]
    return ["/api/v1" + re.sub(r"\$\w+", "x", body).replace("\x00", "x")]


bad = []
for file, method, raw in calls:
    options = candidates(raw)
    missing = [
        option
        for option in options
        if next((p for p, m in matchers if m.match(option)), None) is None
    ]
    if missing == options:
        bad.append(f"{file.name}: {method} {raw} -> no such route")
    elif missing:
        bad.append(
            f"{file.name}: {method} {raw} -> missing for "
            + ", ".join(m.rsplit("/", 1)[-1] for m in missing)
        )
    else:
        for option in options:
            hit = next(p for p, m in matchers if m.match(option))
            if method.lower() not in schema["paths"][hit]:
                bad.append(f"{file.name}: {method} {option} -> wrong method")
        if not bad or not bad[-1].startswith(file.name):
            shown = raw if len(options) == 1 else f"{raw}  [{len(options)} variants]"
            print(f"  ok  {method:4} {shown}")

print(f"\nchecked {len(calls)} API calls from the driver app")
for problem in bad:
    print("  ✗", problem)
sys.exit(1 if bad else 0)
