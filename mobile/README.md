# FleetBeat Driver App

Flutter app for drivers (iOS + Android), consuming the same FastAPI backend as
the web dashboard.

## What the app does

- **Login** with a driver-only role check. There is no registration screen and
  there never will be: driver accounts are created by an Org Admin or by
  FleetBeat staff (Section 9).
- **My Tasks** — the home screen: today's jobs, the driver's vehicle, safety
  score and points balance, and a pre-trip inspection prompt when one is due.
- **Task detail** — instructions, destination, and the real OSRM route and ETA
  from the driver's own position. Exactly one action is offered per state,
  mirroring the backend's transition table: Accept → Start → Complete.
  Completing prompts for a note and an optional proof photo.
- **Pre-trip inspection** — a fixed checklist where every item defaults to OK,
  so a clean vehicle is one tap and flagging a fault is deliberate. A failed
  check raises an incident for the fleet team automatically.
- **Report an issue** — available from the task screen and the home screen.
  The report is always filed as the signed-in driver; the backend ignores any
  driver identity sent from the client.

## Known limitations in this phase

- **Push notifications**: `lib/core/push.dart` is the seam, and the backend
  logs what it would send, but no FCM/APNs provider is wired up. Filling in
  `PushNotifications.register` is the whole change — no screen is affected.
- **Maps**: the task screen shows the real route distance, duration and ETA
  from OSRM, but renders them as a summary rather than a drawn map. Adding
  `flutter_map` plus a tile source and the location-permission flow is the
  remaining work; the routing itself is already real.
- **Photo upload**: capture is offered and the intent is recorded, but there
  is no upload endpoint or object storage yet, so attachments are marked
  pending rather than transferred.

## Running

```bash
flutter pub get
flutter run --dart-define=FLEETBEAT_API_BASE_URL=http://10.0.2.2:8000/api/v1
```

`10.0.2.2` is how the Android emulator reaches the host machine. On iOS
simulator or desktop use `http://localhost:8000/api/v1`.

Platform folders (`android/`, `ios/`) are not committed - generate them once
with `flutter create .` from this directory.
