import 'package:flutter_test/flutter_test.dart';

import 'package:fleetbeat_driver/models/task.dart';

void main() {
  group('FleetTask', () {
    Map<String, dynamic> payload({String status = 'assigned'}) => {
          'id': 'task-1',
          'title': 'Deliver pallet 42',
          'status': status,
          'task_type': 'delivery',
          'priority': 'urgent',
          'destination_latitude': 52.3105,
          'destination_longitude': 4.7683,
          'destination_label': 'Schiphol hub',
          'description': 'Ask for Jan at the gate',
          'due_at': '2026-09-12T09:30:00Z',
          'eta': '2026-09-12T09:05:00Z',
          'vehicle_id': 'vehicle-1',
        };

    test('parses the API payload', () {
      final task = FleetTask.fromJson(payload());

      expect(task.id, 'task-1');
      expect(task.status, TaskStatus.assigned);
      expect(task.isUrgent, isTrue);
      expect(task.destinationLabel, 'Schiphol hub');
      expect(task.eta, isNotNull);
    });

    test('maps the wire value en_route to its enum', () {
      expect(
        FleetTask.fromJson(payload(status: 'en_route')).status,
        TaskStatus.enRoute,
      );
    });

    test('offers exactly one action per state, mirroring the backend', () {
      // The backend refuses anything else, so the app must not offer it.
      expect(FleetTask.fromJson(payload()).nextActionPath, 'accept');
      expect(
        FleetTask.fromJson(payload(status: 'accepted')).nextActionPath,
        'start',
      );
      expect(
        FleetTask.fromJson(payload(status: 'en_route')).nextActionPath,
        'complete',
      );
      // Terminal states offer nothing.
      expect(
        FleetTask.fromJson(payload(status: 'completed')).nextActionPath,
        isNull,
      );
      expect(
        FleetTask.fromJson(payload(status: 'cancelled')).nextActionPath,
        isNull,
      );
    });
  });

  group('DriverHome', () {
    test('parses the home payload and defaults safely', () {
      final home = DriverHome.fromJson({
        'driver_id': 'driver-1',
        'driver_name': 'Dee Driver',
        'tasks': <dynamic>[],
        'inspection_due': true,
        'safety_score': 92.5,
        'points_balance': 118,
        'leaderboard_visible': false,
        'vehicle_id': 'vehicle-1',
        'vehicle_name': 'Van 01',
        'vehicle_plate': 'ACM-001',
      });

      expect(home.driverName, 'Dee Driver');
      expect(home.inspectionDue, isTrue);
      expect(home.safetyScore, 92.5);
      // Off unless the Org Admin opts in (Section 4g).
      expect(home.leaderboardVisible, isFalse);
    });
  });

  group('pre-trip checklist', () {
    test('defaults every item to OK so a clean vehicle is one tap', () {
      final items = defaultChecklist();
      expect(items, isNotEmpty);
      expect(items.every((item) => item.ok), isTrue);
      expect(items.first.toJson()['ok'], true);
    });

    test('serialises a reported fault with its note', () {
      final item = defaultChecklist().first
        ..ok = false
        ..note = 'Near-side worn';
      expect(item.toJson(), containsPair('ok', false));
      expect(item.toJson(), containsPair('note', 'Near-side worn'));
    });
  });

  group('Standings', () {
    test('parses the leaderboard payload', () {
      final standings = Standings.fromJson({
        'period': '2026-09',
        'visible_to_drivers': true,
        'rows': [
          {
            'rank': 1,
            'driver_id': 'driver-1',
            'driver_name': 'Dee Driver',
            'points_balance': 118,
            'safety_score': 93.4,
            'fatigue_risk_level': 'low',
            'badges': ['clean_streak'],
          },
        ],
        'badge_catalogue': [
          {
            'code': 'clean_streak',
            'name': 'Clean streak',
            'description': 'A full week with no violations.',
          },
        ],
      });

      expect(standings.period, '2026-09');
      expect(standings.visibleToDrivers, isTrue);
      expect(standings.rows.single.driverName, 'Dee Driver');
      expect(standings.rows.single.badges, ['clean_streak']);
      expect(standings.badgeCatalogue.single.name, 'Clean streak');
    });

    test('defaults to private when the flag is absent', () {
      // The screen shows peers only when the API says so, so a missing or
      // unreadable flag must fall closed rather than open.
      final standings = Standings.fromJson({'period': '2026-09', 'rows': []});

      expect(standings.visibleToDrivers, isFalse);
      expect(standings.rows, isEmpty);
      expect(standings.badgeCatalogue, isEmpty);
    });
  });
}
