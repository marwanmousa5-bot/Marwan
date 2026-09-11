# FleetBeat Driver App

Flutter app for drivers (iOS + Android), consuming the same FastAPI backend as
the web dashboard.

## Phase 1 (this phase)

- Login screen with role check (driver accounts only).
- Session restore from stored tokens, with transparent refresh.
- "My Tasks" home shell.

There is no registration screen and there never will be: driver accounts are
created by an Org Admin or by FleetBeat staff (Section 9).

## Phase 3 (next)

Task list and detail, Accept → Start → Complete workflow, route-to-destination
map via OSRM, pre-trip inspection checklist, incident reporting and push
notifications.

## Running

```bash
flutter pub get
flutter run --dart-define=FLEETBEAT_API_BASE_URL=http://10.0.2.2:8000/api/v1
```

`10.0.2.2` is how the Android emulator reaches the host machine. On iOS
simulator or desktop use `http://localhost:8000/api/v1`.

Platform folders (`android/`, `ios/`) are not committed - generate them once
with `flutter create .` from this directory.
