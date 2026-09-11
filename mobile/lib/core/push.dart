import 'dart:async';

import 'package:flutter/foundation.dart';

/// Push notification seam (Section 4f).
///
/// No push provider is integrated in this phase - the backend logs what it
/// would have sent through its own NotificationService abstraction. This class
/// is the matching seam on the app side: wiring FCM/APNs later means filling
/// in [register] and forwarding the payload to [onTaskNotification], without
/// touching any screen.
class PushNotifications {
  PushNotifications._();

  static final PushNotifications instance = PushNotifications._();

  final StreamController<String> _taskIds = StreamController<String>.broadcast();

  /// Emits the task id of any task push the device receives.
  Stream<String> get taskNotifications => _taskIds.stream;

  Future<void> register() async {
    debugPrint(
      '[fleetbeat] push registration is not wired to a provider in this phase',
    );
  }

  /// Called by the platform handler once a provider is wired up.
  void onTaskNotification(Map<String, dynamic> payload) {
    final taskId = payload['task_id'];
    if (taskId is String) _taskIds.add(taskId);
  }

  void dispose() => _taskIds.close();
}
