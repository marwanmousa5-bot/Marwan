import 'package:flutter/material.dart';

/// FleetBeat brand palette (Section 1).
///
/// [alertCoral] is reserved for live and critical signals only - it is never
/// used as a primary UI colour.
abstract final class FleetBeatColors {
  static const electricBlue = Color(0xFF1E90FF);
  static const alertCoral = Color(0xFFFF6B35);
  static const inkDark = Color(0xFF121417);
  static const inkSurface = Color(0xFF181B20);
  static const inkBorder = Color(0xFF2A2F38);
  static const paper = Color(0xFFF5F7FA);
  static const success = Color(0xFF2ECC71);
  static const warning = Color(0xFFF5A623);
  static const danger = Color(0xFFE74C3C);
}

ThemeData buildFleetBeatTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: FleetBeatColors.electricBlue,
    brightness: Brightness.dark,
  ).copyWith(
    primary: FleetBeatColors.electricBlue,
    error: FleetBeatColors.danger,
    surface: FleetBeatColors.inkSurface,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: FleetBeatColors.inkDark,
    appBarTheme: const AppBarTheme(
      backgroundColor: FleetBeatColors.inkSurface,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: FleetBeatColors.inkDark,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: FleetBeatColors.inkBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: FleetBeatColors.inkBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: FleetBeatColors.electricBlue),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: FleetBeatColors.electricBlue,
        minimumSize: const Size.fromHeight(48),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
        ),
      ),
    ),
  );
}
