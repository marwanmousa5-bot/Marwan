/// All user-facing copy for the driver app.
///
/// English only for now (Section 9 forbids i18n infrastructure), but kept out
/// of widget code so a future extraction stays mechanical.
class Strings {
  const Strings._();

  static const appName = 'FleetBeat';
  static const tagline = 'The live pulse of your fleet.';

  // Login
  static const loginTitle = 'Driver sign in';
  static const emailLabel = 'Work email';
  static const passwordLabel = 'Password';
  static const signIn = 'Sign in';
  static const signingIn = 'Signing in…';
  static const signOut = 'Sign out';
  static const noSignup =
      'Driver accounts are created by your fleet administrator. '
      'If you cannot sign in, ask them to re-send your activation link.';
  static const loginFailed = 'We could not sign you in. Check your details.';
  static const notADriver =
      'This account is not a driver account. The web dashboard is for '
      'administrators and dispatchers.';

  // Home
  static const myTasks = 'My Tasks';
  static const noTasksYet = 'No tasks assigned yet.';
  static const tasksComingSoon =
      'Your task list, pre-trip checklist and trip tracking arrive in Phase 3.';
  static const preTripInspection = 'Pre-trip inspection';
  static const reportIssue = 'Report an issue';

  // Generic
  static const loading = 'Loading…';
  static const retry = 'Try again';
}
