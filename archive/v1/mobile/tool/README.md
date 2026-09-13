# Driver app checks

Two standalone checks that need no Flutter SDK. They exist because this app is
the one part of FleetBeat that cannot be compiled in every environment, and a
mistake a compiler would catch in a second otherwise stays invisible until a
driver taps the screen.

Neither replaces `flutter analyze` and `flutter test` — run those wherever the
SDK is available.

## `static_check.py`

```
python3 tool/static_check.py
```

Catches unbalanced delimiters, imports that resolve to nothing, `Strings.*`
uses with no matching constant, and a type used in a file that neither
declares nor imports it.

## `route_check.py`

```
python3 tool/route_check.py            # against a local API
FLEETBEAT_API_BASE_URL=… python3 tool/route_check.py
```

Pulls the OpenAPI schema the API actually serves and checks that every path
the app calls exists, with the right method. A path built by interpolation is
expanded to the concrete paths it can produce, so a task action that
interpolates `accept`/`start`/`complete` is checked as all three.

This found a real one: the standings screen called `/analytics/leaderboard`,
while the route the API serves is `/leaderboard`.
