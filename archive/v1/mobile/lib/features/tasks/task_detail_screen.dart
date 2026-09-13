import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../models/task.dart';
import '../incidents/report_incident_screen.dart';

/// One task: details, the route to the destination, and the single action its
/// current state allows (Section 4f).
class TaskDetailScreen extends StatefulWidget {
  const TaskDetailScreen({super.key, required this.api, required this.task});

  final ApiClient api;
  final FleetTask task;

  @override
  State<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends State<TaskDetailScreen> {
  late FleetTask _task = widget.task;
  RoutePreview? _route;
  String? _routeError;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _loadRoute();
  }

  Future<void> _loadRoute() async {
    try {
      final json = await widget.api.get('/driver/tasks/${_task.id}/route');
      if (mounted) {
        setState(() => _route = RoutePreview.fromJson(json as Map<String, dynamic>));
      }
    } catch (_) {
      // Routing being unavailable must never block the driver from working.
      if (mounted) setState(() => _routeError = Strings.routeUnavailable);
    }
  }

  Future<void> _advance() async {
    final path = _task.nextActionPath;
    if (path == null) return;

    Map<String, dynamic>? body;
    if (path == 'complete') {
      body = await _askForCompletion();
      if (body == null) return;
    }

    setState(() => _busy = true);
    try {
      final json = await widget.api.post('/driver/tasks/${_task.id}/$path', body);
      final updated = FleetTask.fromJson(json as Map<String, dynamic>);
      if (!mounted) return;
      setState(() {
        _task = updated;
        _busy = false;
      });
      if (updated.status == TaskStatus.completed) {
        Navigator.of(context).pop(true);
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _busy = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  Future<Map<String, dynamic>?> _askForCompletion() async {
    final controller = TextEditingController();
    var photoAttached = false;

    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      backgroundColor: FleetBeatColors.inkSurface,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheetState) => Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(context).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                Strings.complete,
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: controller,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: Strings.completionNote,
                ),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                // Camera capture is wired up with the device plugins; the
                // upload endpoint and storage are a later phase, so this
                // records intent rather than pretending to upload.
                onPressed: () => setSheetState(() => photoAttached = true),
                icon: Icon(
                  photoAttached ? Icons.check_circle_outline : Icons.photo_camera_outlined,
                ),
                label: Text(
                  photoAttached ? Strings.photoAttached : Strings.attachPhoto,
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () => Navigator.of(context).pop({
                  'completion_note':
                      controller.text.trim().isEmpty ? null : controller.text.trim(),
                  'completion_photo_url': photoAttached ? 'pending-upload' : null,
                }),
                child: const Text(Strings.complete),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final action = _task.nextActionLabel;

    return Scaffold(
      appBar: AppBar(title: const Text(Strings.taskDetails)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  _task.title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (_task.isUrgent)
                const _Chip(label: Strings.priorityUrgent, color: FleetBeatColors.alertCoral),
            ],
          ),
          const SizedBox(height: 6),
          _Chip(label: _task.status.label, color: FleetBeatColors.electricBlue),
          const SizedBox(height: 20),

          _MapPlaceholder(task: _task, route: _route, error: _routeError),
          const SizedBox(height: 20),

          _DetailRow(
            label: Strings.destination,
            value: _task.destinationLabel ??
                '${_task.destinationLatitude.toStringAsFixed(4)}, '
                    '${_task.destinationLongitude.toStringAsFixed(4)}',
          ),
          if (_route != null)
            _DetailRow(
              label: Strings.eta,
              value: '${_formatTime(_route!.eta)} '
                  '(${_route!.distanceKm.toStringAsFixed(1)} km, '
                  '${_route!.durationMinutes.round()} min)',
            ),
          if (_task.dueAt != null)
            _DetailRow(label: Strings.due, value: _formatDateTime(_task.dueAt!)),

          if (_task.description != null && _task.description!.isNotEmpty) ...[
            const SizedBox(height: 18),
            const Text(
              Strings.instructions,
              style: TextStyle(
                color: Colors.white70,
                fontSize: 12,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.6,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              _task.description!,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.75),
                height: 1.5,
              ),
            ),
          ],

          const SizedBox(height: 28),
          if (action != null)
            FilledButton(
              onPressed: _busy ? null : _advance,
              child: Text(_busy ? Strings.loading : action),
            ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => ReportIncidentScreen(
                  api: widget.api,
                  taskId: _task.id,
                  vehicleId: _task.vehicleId,
                ),
              ),
            ),
            icon: const Icon(Icons.report_problem_outlined),
            label: const Text(Strings.reportIssue),
          ),
        ],
      ),
    );
  }
}

/// The route is shown as a schematic until the map plugin is added.
///
/// Drawing a real map needs flutter_map plus a tile source and a location
/// permission flow; the route itself is already real (OSRM), so the numbers
/// here are accurate even though the picture is not yet a map.
class _MapPlaceholder extends StatelessWidget {
  const _MapPlaceholder({required this.task, this.route, this.error});

  final FleetTask task;
  final RoutePreview? route;
  final String? error;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 150,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: FleetBeatColors.inkSurface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FleetBeatColors.inkBorder),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.route_outlined,
            size: 32,
            color: Colors.white.withValues(alpha: 0.35),
          ),
          const SizedBox(height: 10),
          if (error != null)
            Text(
              error!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: FleetBeatColors.warning, fontSize: 12),
            )
          else if (route != null)
            Text(
              '${route!.distanceKm.toStringAsFixed(1)} km  ·  '
              '${route!.durationMinutes.round()} min by road',
              style: const TextStyle(color: Colors.white, fontSize: 14),
            )
          else
            Text(
              Strings.loading,
              style: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
            ),
          const SizedBox(height: 4),
          Text(
            task.destinationLabel ?? Strings.destination,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.5),
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(
              label,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.5),
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(color: Colors.white, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(
          label,
          style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}

String _formatTime(DateTime value) =>
    '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';

String _formatDateTime(DateTime value) =>
    '${value.day}/${value.month} ${_formatTime(value)}';
