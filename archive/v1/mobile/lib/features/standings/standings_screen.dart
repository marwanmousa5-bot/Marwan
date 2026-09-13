import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/strings.dart';
import '../../core/theme.dart';
import '../../models/task.dart';

/// The driver's own standing, and the leaderboard when their fleet allows it
/// (Section 4g).
///
/// The gate is the API's, not this screen's: when peer visibility is off the
/// server returns only this driver's row. The app renders whatever it is
/// given and explains why the list is short - filtering client-side would be
/// a privacy control that a proxy could step around.
class StandingsScreen extends StatefulWidget {
  const StandingsScreen({
    super.key,
    required this.api,
    required this.driverId,
  });

  final ApiClient api;
  final String driverId;

  @override
  State<StandingsScreen> createState() => _StandingsScreenState();
}

class _StandingsScreenState extends State<StandingsScreen> {
  Standings? _standings;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final json = await widget.api.get('/leaderboard');
      if (!mounted) return;
      setState(() {
        _standings = Standings.fromJson(json as Map<String, dynamic>);
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

  @override
  Widget build(BuildContext context) {
    final standings = _standings;

    return Scaffold(
      appBar: AppBar(title: const Text(Strings.standingsTitle)),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? _Message(text: _error!)
                : ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text(
                        standings!.period,
                        style: TextStyle(
                          fontSize: 12,
                          letterSpacing: 0.6,
                          color: Colors.white.withValues(alpha: 0.45),
                        ),
                      ),
                      const SizedBox(height: 12),
                      if (!standings.visibleToDrivers)
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(10),
                            border:
                                Border.all(color: FleetBeatColors.inkBorder),
                          ),
                          child: Text(
                            Strings.standingsPrivate,
                            style: TextStyle(
                              fontSize: 12,
                              height: 1.45,
                              color: Colors.white.withValues(alpha: 0.65),
                            ),
                          ),
                        ),
                      if (!standings.visibleToDrivers)
                        const SizedBox(height: 12),
                      if (standings.rows.isEmpty)
                        const _Message(text: Strings.standingsEmpty)
                      else
                        ...standings.rows.map(
                          (row) => _StandingTile(
                            row: row,
                            isMe: row.driverId == widget.driverId,
                            showRank: standings.visibleToDrivers,
                          ),
                        ),
                      const SizedBox(height: 24),
                      Text(
                        Strings.badgeCatalogue.toUpperCase(),
                        style: TextStyle(
                          fontSize: 10,
                          letterSpacing: 0.8,
                          color: Colors.white.withValues(alpha: 0.45),
                        ),
                      ),
                      const SizedBox(height: 8),
                      ...standings.badgeCatalogue.map(
                        (badge) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                badge.name,
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              Text(
                                badge.description,
                                style: TextStyle(
                                  fontSize: 12,
                                  height: 1.4,
                                  color: Colors.white.withValues(alpha: 0.55),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
      ),
    );
  }
}

class _StandingTile extends StatelessWidget {
  const _StandingTile({
    required this.row,
    required this.isMe,
    required this.showRank,
  });

  final StandingRow row;
  final bool isMe;
  final bool showRank;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        // The driver's own row is the one they came here for, so it is the
        // only one that carries the brand colour.
        color: isMe
            ? FleetBeatColors.electricBlue.withValues(alpha: 0.12)
            : FleetBeatColors.inkSurface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isMe
              ? FleetBeatColors.electricBlue.withValues(alpha: 0.5)
              : FleetBeatColors.inkBorder,
        ),
      ),
      child: Row(
        children: [
          if (showRank)
            SizedBox(
              width: 32,
              child: Text(
                '${row.rank}',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Colors.white.withValues(alpha: isMe ? 0.95 : 0.5),
                ),
              ),
            ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isMe ? '${row.driverName} (${Strings.yourRow})' : row.driverName,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${Strings.safetyScore}: ${row.safetyScore.round()}',
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.white.withValues(alpha: 0.55),
                  ),
                ),
                if (row.badges.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: row.badges
                          .map(
                            (badge) => Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 3,
                              ),
                              decoration: BoxDecoration(
                                color: FleetBeatColors.inkDark,
                                borderRadius: BorderRadius.circular(999),
                                border: Border.all(
                                  color: FleetBeatColors.inkBorder,
                                ),
                              ),
                              child: Text(
                                badge.replaceAll('_', ' '),
                                style: TextStyle(
                                  fontSize: 10,
                                  color: Colors.white.withValues(alpha: 0.7),
                                ),
                              ),
                            ),
                          )
                          .toList(),
                    ),
                  ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${row.pointsBalance}',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
              Text(
                Strings.points.toUpperCase(),
                style: TextStyle(
                  fontSize: 9,
                  letterSpacing: 0.8,
                  color: Colors.white.withValues(alpha: 0.45),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 32),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: TextStyle(
          fontSize: 13,
          color: Colors.white.withValues(alpha: 0.6),
        ),
      ),
    );
  }
}
