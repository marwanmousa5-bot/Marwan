/// Task, inspection and incident models mirrored from the FastAPI schemas.
library;

enum TaskStatus { assigned, accepted, enRoute, completed, cancelled }

TaskStatus taskStatusFrom(String raw) => switch (raw) {
      'assigned' => TaskStatus.assigned,
      'accepted' => TaskStatus.accepted,
      'en_route' => TaskStatus.enRoute,
      'completed' => TaskStatus.completed,
      _ => TaskStatus.cancelled,
    };

extension TaskStatusLabel on TaskStatus {
  String get label => switch (this) {
        TaskStatus.assigned => 'Assigned',
        TaskStatus.accepted => 'Accepted',
        TaskStatus.enRoute => 'En route',
        TaskStatus.completed => 'Completed',
        TaskStatus.cancelled => 'Cancelled',
      };
}

class FleetTask {
  const FleetTask({
    required this.id,
    required this.title,
    required this.status,
    required this.taskType,
    required this.priority,
    required this.destinationLatitude,
    required this.destinationLongitude,
    this.description,
    this.destinationLabel,
    this.dueAt,
    this.eta,
    this.vehicleId,
  });

  factory FleetTask.fromJson(Map<String, dynamic> json) => FleetTask(
        id: json['id'] as String,
        title: json['title'] as String,
        status: taskStatusFrom(json['status'] as String),
        taskType: json['task_type'] as String? ?? 'delivery',
        priority: json['priority'] as String? ?? 'normal',
        destinationLatitude: (json['destination_latitude'] as num).toDouble(),
        destinationLongitude: (json['destination_longitude'] as num).toDouble(),
        description: json['description'] as String?,
        destinationLabel: json['destination_label'] as String?,
        dueAt: _parseDate(json['due_at']),
        eta: _parseDate(json['eta']),
        vehicleId: json['vehicle_id'] as String?,
      );

  final String id;
  final String title;
  final TaskStatus status;
  final String taskType;
  final String priority;
  final double destinationLatitude;
  final double destinationLongitude;
  final String? description;
  final String? destinationLabel;
  final DateTime? dueAt;
  final DateTime? eta;
  final String? vehicleId;

  bool get isUrgent => priority == 'urgent';

  /// The single action available in this state, mirroring the backend's
  /// transition table. Anything else is refused server-side anyway.
  String? get nextActionLabel => switch (status) {
        TaskStatus.assigned => 'Accept',
        TaskStatus.accepted => 'Start driving',
        TaskStatus.enRoute => 'Complete',
        _ => null,
      };

  String? get nextActionPath => switch (status) {
        TaskStatus.assigned => 'accept',
        TaskStatus.accepted => 'start',
        TaskStatus.enRoute => 'complete',
        _ => null,
      };
}

class DriverHome {
  const DriverHome({
    required this.driverId,
    required this.driverName,
    required this.tasks,
    required this.inspectionDue,
    required this.safetyScore,
    required this.pointsBalance,
    required this.leaderboardVisible,
    this.vehicleId,
    this.vehicleName,
    this.vehiclePlate,
  });

  factory DriverHome.fromJson(Map<String, dynamic> json) => DriverHome(
        driverId: json['driver_id'] as String,
        driverName: json['driver_name'] as String,
        tasks: (json['tasks'] as List<dynamic>)
            .map((e) => FleetTask.fromJson(e as Map<String, dynamic>))
            .toList(),
        inspectionDue: json['inspection_due'] as bool? ?? false,
        safetyScore: (json['safety_score'] as num?)?.toDouble() ?? 100,
        pointsBalance: (json['points_balance'] as num?)?.toInt() ?? 0,
        leaderboardVisible: json['leaderboard_visible'] as bool? ?? false,
        vehicleId: json['vehicle_id'] as String?,
        vehicleName: json['vehicle_name'] as String?,
        vehiclePlate: json['vehicle_plate'] as String?,
      );

  final String driverId;
  final String driverName;
  final List<FleetTask> tasks;
  final bool inspectionDue;
  final double safetyScore;
  final int pointsBalance;
  final bool leaderboardVisible;
  final String? vehicleId;
  final String? vehicleName;
  final String? vehiclePlate;
}

class RoutePreview {
  const RoutePreview({
    required this.distanceKm,
    required this.durationMinutes,
    required this.eta,
  });

  factory RoutePreview.fromJson(Map<String, dynamic> json) => RoutePreview(
        distanceKm: (json['distance_km'] as num).toDouble(),
        durationMinutes: (json['duration_minutes'] as num).toDouble(),
        eta: DateTime.parse(json['eta'] as String).toLocal(),
      );

  final double distanceKm;
  final double durationMinutes;
  final DateTime eta;
}

/// The fixed pre-trip checklist. Backend-defined items would be a later
/// refinement; a stable list keeps the daily check fast to complete.
class InspectionItem {
  InspectionItem({required this.code, required this.label, this.ok = true, this.note});

  final String code;
  final String label;
  bool ok;
  String? note;

  Map<String, dynamic> toJson() => {
        'code': code,
        'label': label,
        'ok': ok,
        if (note != null && note!.isNotEmpty) 'note': note,
      };
}

List<InspectionItem> defaultChecklist() => [
      InspectionItem(code: 'tyres', label: 'Tyres and pressure'),
      InspectionItem(code: 'lights', label: 'Lights and indicators'),
      InspectionItem(code: 'brakes', label: 'Brakes'),
      InspectionItem(code: 'mirrors', label: 'Mirrors and glass'),
      InspectionItem(code: 'fluids', label: 'Oil and coolant'),
      InspectionItem(code: 'bodywork', label: 'Bodywork damage'),
      InspectionItem(code: 'load', label: 'Load secured'),
      InspectionItem(code: 'safety_kit', label: 'Safety kit on board'),
    ];

DateTime? _parseDate(Object? raw) =>
    raw is String ? DateTime.parse(raw).toLocal() : null;


/// One row of the monthly standings (Section 4g).
///
/// When the driver's Organization has peer visibility switched off the API
/// returns only their own row - the app does not filter this itself, because
/// a client-side filter is not a privacy control.
class StandingRow {
  const StandingRow({
    required this.rank,
    required this.driverId,
    required this.driverName,
    required this.pointsBalance,
    required this.safetyScore,
    required this.badges,
  });

  factory StandingRow.fromJson(Map<String, dynamic> json) => StandingRow(
        rank: (json['rank'] as num?)?.toInt() ?? 0,
        driverId: json['driver_id'] as String,
        driverName: json['driver_name'] as String,
        pointsBalance: (json['points_balance'] as num?)?.toInt() ?? 0,
        safetyScore: (json['safety_score'] as num?)?.toDouble() ?? 0,
        badges: ((json['badges'] as List<dynamic>?) ?? const [])
            .map((e) => e as String)
            .toList(),
      );

  final int rank;
  final String driverId;
  final String driverName;
  final int pointsBalance;
  final double safetyScore;
  final List<String> badges;
}

class BadgeDefinition {
  const BadgeDefinition({
    required this.code,
    required this.name,
    required this.description,
  });

  factory BadgeDefinition.fromJson(Map<String, dynamic> json) => BadgeDefinition(
        code: json['code'] as String,
        name: json['name'] as String,
        description: json['description'] as String,
      );

  final String code;
  final String name;
  final String description;
}

class Standings {
  const Standings({
    required this.period,
    required this.rows,
    required this.badgeCatalogue,
    required this.visibleToDrivers,
  });

  factory Standings.fromJson(Map<String, dynamic> json) => Standings(
        period: json['period'] as String? ?? '',
        rows: ((json['rows'] as List<dynamic>?) ?? const [])
            .map((e) => StandingRow.fromJson(e as Map<String, dynamic>))
            .toList(),
        badgeCatalogue: ((json['badge_catalogue'] as List<dynamic>?) ?? const [])
            .map((e) => BadgeDefinition.fromJson(e as Map<String, dynamic>))
            .toList(),
        visibleToDrivers: json['visible_to_drivers'] as bool? ?? false,
      );

  final String period;
  final List<StandingRow> rows;
  final List<BadgeDefinition> badgeCatalogue;
  final bool visibleToDrivers;
}
