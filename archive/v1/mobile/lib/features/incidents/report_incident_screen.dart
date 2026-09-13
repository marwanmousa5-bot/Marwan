import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';

/// Roadside incident reporting (Section 4 item 11).
///
/// The report is always filed as the signed-in driver: the backend ignores any
/// driver identity sent from the client.
class ReportIncidentScreen extends StatefulWidget {
  const ReportIncidentScreen({
    super.key,
    required this.api,
    this.taskId,
    this.vehicleId,
  });

  final ApiClient api;
  final String? taskId;
  final String? vehicleId;

  @override
  State<ReportIncidentScreen> createState() => _ReportIncidentScreenState();
}

class _ReportIncidentScreenState extends State<ReportIncidentScreen> {
  final _formKey = GlobalKey<FormState>();
  final _titleController = TextEditingController();
  final _descriptionController = TextEditingController();

  String _severity = 'minor';
  int _photoCount = 0;
  bool _submitting = false;

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _submitting = true);

    try {
      await widget.api.post('/driver/incidents', {
        'title': _titleController.text.trim(),
        'description': _descriptionController.text.trim().isEmpty
            ? null
            : _descriptionController.text.trim(),
        'severity': _severity,
        'task_id': widget.taskId,
        'vehicle_id': widget.vehicleId,
        'photo_urls': List<String>.generate(_photoCount, (i) => 'pending-upload-$i'),
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text(Strings.reportSent)));
      Navigator.of(context).pop();
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
      appBar: AppBar(title: const Text(Strings.reportIssue)),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            TextFormField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: Strings.incidentTitle),
              validator: (value) => (value == null || value.trim().isEmpty)
                  ? 'Describe what happened in a few words'
                  : null,
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _descriptionController,
              maxLines: 4,
              decoration:
                  const InputDecoration(labelText: Strings.incidentDescription),
            ),
            const SizedBox(height: 18),
            const Text(
              Strings.severity,
              style: TextStyle(color: Colors.white70, fontSize: 12),
            ),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'minor', label: Text('Minor')),
                ButtonSegment(value: 'moderate', label: Text('Moderate')),
                ButtonSegment(value: 'severe', label: Text('Severe')),
              ],
              selected: {_severity},
              onSelectionChanged: (selection) =>
                  setState(() => _severity = selection.first),
            ),
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: () => setState(() => _photoCount += 1),
              icon: const Icon(Icons.photo_camera_outlined),
              label: Text(
                _photoCount == 0 ? 'Add photos' : '$_photoCount photo(s) attached',
              ),
            ),
            const SizedBox(height: 28),
            FilledButton(
              onPressed: _submitting ? null : _submit,
              child: Text(_submitting ? Strings.loading : Strings.submitReport),
            ),
            const SizedBox(height: 12),
            Text(
              'Your fleet team sees this straight away.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.4),
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
