import 'dart:async';

import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/push.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../models/task.dart';
import '../incidents/report_incident_screen.dart';
import '../standings/standings_screen.dart';
import '../inspection/inspection_screen.dart';
import 'task_detail_screen.dart';

/// The driver's home screen is "My Tasks" (Section 4f).
class MyTasksScreen extends StatefulWidget {
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
  State<MyTasksScreen> createState() => _MyTasksScreenState();
}

class _MyTasksScreenState extends State<MyTasksScreen> {
  DriverHome? _home;
  String? _error;
  bool _loading = true;
  StreamSubscription<String>? _pushSubscription;

  @override
  void initState() {
    super.initState();
    _load();
    // A push about a new task should refresh the list the driver is looking at.
    _pushSubscription =
        PushNotifications.instance.taskNotifications.listen((_) => _load());
  }

  @override
  void dispose() {
    _pushSubscription?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final json = await widget.api.get('/driver/home');
      if (!mounted) return;
      setState(() {
        _home = DriverHome.fromJson(json as Map<String, dynamic>);
        _error = null;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = Strings.somethingWentWrong;
        _loading = false;
      });
    }
  }

  Future<void> _openTask(FleetTask task) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => TaskDetailScreen(api: widget.api, task: task),
      ),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final home = _home;

    return Scaffold(
      appBar: AppBar(
        title: const Text(Strings.myTasks),
        actions: [
          IconButton(
            tooltip: Strings.reportIssue,
            icon: const Icon(Icons.report_problem_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => ReportIncidentScreen(
                  api: widget.api,
                  vehicleId: home?.vehicleId,
                ),
              ),
            ),
          ),
          IconButton(
            tooltip: Strings.signOut,
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await widget.api.logout();
              widget.onSignedOut();
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? _ErrorState(message: _error!, onRetry: _load)
                : ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _DriverCard(
                        home: home!,
                        onOpenStandings: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => StandingsScreen(
                              api: widget.api,
                              driverId: home.driverId,
                            ),
                          ),
                        ),
                      ),
                      if (home.inspectionDue && home.vehicleId != null) ...[
                        const SizedBox(height: 12),
                        _InspectionPrompt(
                          onTap: () async {
                            final done = await Navigator.of(context).push<bool>(
                              MaterialPageRoute(
                                builder: (_) => InspectionScreen(
                                  api: widget.api,
                                  vehicleId: home.vehicleId!,
                                ),
                              ),
                            );
                            if (done ?? false) await _load();
                          },
                        ),
                      ],
                      const SizedBox(height: 20),
                      if (home.tasks.isEmpty)
                        const _EmptyTasks()
                      else
                        ...home.tasks.map(
                          (task) => _TaskCard(
                            task: task,
                            onTap: () => _openTask(task),
                          ),
                        ),
                    ],
                  ),
      ),
    );
  }
}

class _DriverCard extends StatelessWidget {
  const _DriverCard({required this.home, required this.onOpenStandings});

  final DriverHome home;
  final VoidCallback onOpenStandings;

  @override
  Widget build(BuildContext context) {
    return Container(
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
            home.driverName,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 17,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            home.vehicleName == null
                ? Strings.noVehicle
                : '${Strings.todaysVehicle}: ${home.vehicleName} (${home.vehiclePlate})',
            style: TextStyle(
              fontSize: 13,
              color: Colors.white.withValues(alpha: 0.55),
            ),
          ),
          const SizedBox(height: 16),
          // The whole block is the tap target: a driver looking at their
          // score is the driver who wants the detail behind it.
          InkWell(
            onTap: onOpenStandings,
            borderRadius: BorderRadius.circular(8),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                children: [
                  _Metric(
                    label: Strings.safetyScore,
                    value: home.safetyScore.round().toString(),
                  ),
                  const SizedBox(width: 24),
                  _Metric(
                    label: Strings.points,
                    value: home.pointsBalance.toString(),
                  ),
                  const Spacer(),
                  Row(
                    children: [
                      Text(
                        home.leaderboardVisible
                            ? Strings.standingsTitle
                            : Strings.myStanding,
                        style: TextStyle(
                          fontSize: 12,
                          color: FleetBeatColors.electricBlue
                              .withValues(alpha: 0.9),
                        ),
                      ),
                      const Icon(
                        Icons.chevron_right,
                        size: 18,
                        color: FleetBeatColors.electricBlue,
                      ),
                    ],
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

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label.toUpperCase(),
          style: TextStyle(
            fontSize: 10,
            letterSpacing: 0.8,
            color: Colors.white.withValues(alpha: 0.45),
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 20,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _InspectionPrompt extends StatelessWidget {
  const _InspectionPrompt({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: FleetBeatColors.warning.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: FleetBeatColors.warning.withValues(alpha: 0.4),
          ),
        ),
        child: Row(
          children: [
            const Icon(Icons.checklist_rtl, color: FleetBeatColors.warning),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    Strings.inspectionDue,
                    style: TextStyle(
                      color: FleetBeatColors.warning,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    Strings.inspectionDueHint,
                    style: TextStyle(
                      fontSize: 12,
                      color: FleetBeatColors.warning.withValues(alpha: 0.8),
                    ),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: FleetBeatColors.warning),
          ],
        ),
      ),
    );
  }
}

class _TaskCard extends StatelessWidget {
  const _TaskCard({required this.task, required this.onTap});

  final FleetTask task;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color: FleetBeatColors.inkSurface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: task.isUrgent
              ? FleetBeatColors.alertCoral.withValues(alpha: 0.5)
              : FleetBeatColors.inkBorder,
        ),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      task.title,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  if (task.isUrgent)
                    Container(
                      padding:
                          const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: FleetBeatColors.alertCoral.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: const Text(
                        Strings.priorityUrgent,
                        style: TextStyle(
                          color: FleetBeatColors.alertCoral,
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                ],
              ),
              if (task.destinationLabel != null) ...[
                const SizedBox(height: 4),
                Row(
                  children: [
                    Icon(
                      Icons.place_outlined,
                      size: 14,
                      color: Colors.white.withValues(alpha: 0.45),
                    ),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        task.destinationLabel!,
                        style: TextStyle(
                          fontSize: 13,
                          color: Colors.white.withValues(alpha: 0.6),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
              const SizedBox(height: 10),
              Row(
                children: [
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color:
                          FleetBeatColors.electricBlue.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      task.status.label,
                      style: const TextStyle(
                        color: FleetBeatColors.electricBlue,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  const Spacer(),
                  if (task.eta != null)
                    Text(
                      '${Strings.eta} ${task.eta!.hour.toString().padLeft(2, '0')}:'
                      '${task.eta!.minute.toString().padLeft(2, '0')}',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white.withValues(alpha: 0.5),
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyTasks extends StatelessWidget {
  const _EmptyTasks();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 48),
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
            style: TextStyle(color: Colors.white.withValues(alpha: 0.7)),
          ),
          const SizedBox(height: 6),
          Text(
            Strings.noTasksHint,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 12,
              color: Colors.white.withValues(alpha: 0.4),
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(32),
      children: [
        const SizedBox(height: 60),
        Icon(
          Icons.cloud_off_outlined,
          size: 40,
          color: Colors.white.withValues(alpha: 0.3),
        ),
        const SizedBox(height: 16),
        Text(
          message,
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white.withValues(alpha: 0.7)),
        ),
        const SizedBox(height: 20),
        Center(
          child: OutlinedButton(
            onPressed: onRetry,
            child: const Text(Strings.retry),
          ),
        ),
      ],
    );
  }
}
