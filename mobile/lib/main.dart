import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/push.dart';
import 'core/strings.dart';
import 'core/theme.dart';
import 'features/auth/login_screen.dart';
import 'features/tasks/my_tasks_screen.dart';
import 'shared/pulse_indicator.dart';

void main() {
  runApp(const FleetBeatDriverApp());
}

class FleetBeatDriverApp extends StatefulWidget {
  const FleetBeatDriverApp({super.key});

  @override
  State<FleetBeatDriverApp> createState() => _FleetBeatDriverAppState();
}

class _FleetBeatDriverAppState extends State<FleetBeatDriverApp> {
  final ApiClient _api = ApiClient();

  bool _restoring = true;
  Map<String, dynamic>? _session;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    await PushNotifications.instance.register();
    await _api.restoreSession();
    if (_api.hasSession) {
      try {
        final me = await _api.get('/auth/me') as Map<String, dynamic>;
        if (mounted) setState(() => _session = me);
      } catch (_) {
        await _api.clearSession();
      }
    }
    if (mounted) setState(() => _restoring = false);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: Strings.appName,
      debugShowCheckedModeBanner: false,
      theme: buildFleetBeatTheme(),
      home: _restoring
          ? const Scaffold(
              backgroundColor: FleetBeatColors.inkDark,
              body: Center(child: PulseIndicator(label: Strings.loading)),
            )
          : _session == null
              ? LoginScreen(
                  api: _api,
                  onSignedIn: (session) => setState(() => _session = session),
                )
              : MyTasksScreen(
                  api: _api,
                  session: _session!,
                  onSignedOut: () => setState(() => _session = null),
                ),
    );
  }
}
