import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';

/// The driver's home screen is "My Tasks" (Section 4f).
///
/// Phase 1 ships the authenticated shell and the empty state. The task list,
/// Accept -> Start -> Complete workflow, route map and pre-trip checklist
/// land in Phase 3, once the Task Manager API exists.
class MyTasksScreen extends StatelessWidget {
  const MyTasksScreen({
    super.key,
    required this.api,
    required this.session,
    required this.onSignedOut,
  });

  final ApiClient api;
  final Map<String, dynamic> session;
  final VoidCallback onSignedOut;

  @override
  Widget build(BuildContext context) {
    final user = session['user'] as Map<String, dynamic>;
    final organization = session['organization_name'] as String?;

    return Scaffold(
      appBar: AppBar(
        title: const Text(Strings.myTasks),
        actions: [
          IconButton(
            tooltip: Strings.signOut,
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await api.logout();
              onSignedOut();
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: FleetBeatColors.inkSurface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: FleetBeatColors.inkBorder),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  user['full_name'] as String? ?? '',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (organization != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    organization,
                    style: TextStyle(
                      fontSize: 13,
                      color: Colors.white.withValues(alpha: 0.55),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 20),
          Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 40),
              child: Column(
                children: [
                  Icon(
                    Icons.assignment_outlined,
                    size: 42,
                    color: Colors.white.withValues(alpha: 0.25),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    Strings.noTasksYet,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.7),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: Text(
                      Strings.tasksComingSoon,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 12,
                        height: 1.5,
                        color: Colors.white.withValues(alpha: 0.4),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
