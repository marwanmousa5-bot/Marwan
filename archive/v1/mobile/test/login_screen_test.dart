import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:fleetbeat_driver/core/api_client.dart';
import 'package:fleetbeat_driver/core/strings.dart';
import 'package:fleetbeat_driver/core/theme.dart';
import 'package:fleetbeat_driver/features/auth/login_screen.dart';

void main() {
  testWidgets('login screen offers no way to create an account', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildFleetBeatTheme(),
        home: LoginScreen(api: ApiClient(), onSignedIn: (_) {}),
      ),
    );

    expect(find.text(Strings.signIn), findsOneWidget);
    // Section 9: no public registration anywhere, including the mobile app.
    expect(find.textContaining('Sign up'), findsNothing);
    expect(find.textContaining('Create account'), findsNothing);
    expect(find.text(Strings.noSignup), findsOneWidget);
  });

  testWidgets('login form validates before calling the API', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildFleetBeatTheme(),
        home: LoginScreen(api: ApiClient(), onSignedIn: (_) {}),
      ),
    );

    await tester.tap(find.text(Strings.signIn));
    await tester.pump();

    expect(find.text('Enter your work email'), findsOneWidget);
    expect(find.text('Enter your password'), findsOneWidget);
  });
}
