import 'package:flutter/material.dart';

import '../core/theme.dart';

/// The heartbeat motif (Section 1), used for loading and live states.
class PulseIndicator extends StatefulWidget {
  const PulseIndicator({super.key, this.label});

  final String? label;

  @override
  State<PulseIndicator> createState() => _PulseIndicatorState();
}

class _PulseIndicatorState extends State<PulseIndicator>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        ScaleTransition(
          scale: Tween<double>(begin: 0.85, end: 1.35).animate(
            CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
          ),
          child: Container(
            width: 12,
            height: 12,
            decoration: const BoxDecoration(
              color: FleetBeatColors.alertCoral,
              shape: BoxShape.circle,
            ),
          ),
        ),
        if (widget.label != null) ...[
          const SizedBox(height: 16),
          Text(
            widget.label!,
            style: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
          ),
        ],
      ],
    );
  }
}
