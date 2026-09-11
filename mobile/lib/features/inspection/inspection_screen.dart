import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../models/task.dart';

/// Pre-trip inspection checklist (Section 4 item 14).
///
/// Every item defaults to OK so a clean vehicle takes one tap to confirm;
/// flagging a fault is the deliberate action, and raises an incident for the
/// fleet team automatically.
class InspectionScreen extends StatefulWidget {
  const InspectionScreen({
    super.key,
    required this.api,
    required this.vehicleId,
    this.taskId,
  });

  final ApiClient api;
  final String vehicleId;
  final String? taskId;

  @override
  State<InspectionScreen> createState() => _InspectionScreenState();
}

class _InspectionScreenState extends State<InspectionScreen> {
  final List<InspectionItem> _items = defaultChecklist();
  final _odometerController = TextEditingController();
  final _notesController = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _odometerController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  bool get _hasFault => _items.any((item) => !item.ok);

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await widget.api.post('/driver/inspections', {
        'vehicle_id': widget.vehicleId,
        'task_id': widget.taskId,
        'items': _items.map((item) => item.toJson()).toList(),
        'odometer_km': double.tryParse(_odometerController.text.trim()),
        'notes': _notesController.text.trim().isEmpty
            ? null
            : _notesController.text.trim(),
      });
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text(Strings.preTripInspection)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ..._items.map(
            (item) => Card(
              margin: const EdgeInsets.only(bottom: 8),
              color: FleetBeatColors.inkSurface,
              child: SwitchListTile(
                value: item.ok,
                onChanged: (value) => setState(() => item.ok = value),
                title: Text(
                  item.label,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                ),
                subtitle: Text(
                  item.ok ? 'OK' : 'Fault reported',
                  style: TextStyle(
                    color: item.ok
                        ? FleetBeatColors.success
                        : FleetBeatColors.danger,
                    fontSize: 12,
                  ),
                ),
                activeColor: FleetBeatColors.success,
              ),
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _odometerController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: Strings.odometerReading),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _notesController,
            maxLines: 3,
            decoration: const InputDecoration(labelText: Strings.inspectionNotes),
          ),
          if (_hasFault) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: FleetBeatColors.warning.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Text(
                Strings.inspectionFailWarning,
                style: TextStyle(color: FleetBeatColors.warning, fontSize: 12),
              ),
            ),
          ],
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _submitting ? null : _submit,
            child: Text(_submitting ? Strings.loading : Strings.submitInspection),
          ),
        ],
      ),
    );
  }
}
