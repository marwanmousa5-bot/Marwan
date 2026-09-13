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
  static const noTasksYet = 'No tasks assigned for now.';
  static const noTasksHint = 'New jobs appear here as your dispatcher assigns them.';
  static const todaysVehicle = "Today's vehicle";
  static const noVehicle = 'No vehicle assigned';
  static const safetyScore = 'Safety score';
  static const points = 'Points';

  // Standings
  static const myStanding = 'My standing';
  static const standingsTitle = 'Standings';
  static const standingsPrivate =
      'Your fleet keeps standings private, so you can see your own score and '
      'points but not anyone else\'s.';
  static const standingsRank = 'Rank';
  static const yourRow = 'You';
  static const badges = 'Badges';
  static const noBadgesYet = 'No badges yet this month.';
  static const badgeCatalogue = 'How to earn badges';
  static const provisionalScore =
      'Provisional - a score settles once you have driven enough distance '
      'this month.';
  static const standingsEmpty = 'No standings for this month yet.';

  // Inspection
  static const preTripInspection = 'Pre-trip inspection';
  static const inspectionDue = 'Pre-trip inspection due';
  static const inspectionDueHint = 'Check the vehicle before your first job today.';
  static const inspectionDone = 'Inspection complete for today';
  static const submitInspection = 'Submit inspection';
  static const odometerReading = 'Odometer (km)';
  static const inspectionNotes = 'Notes (optional)';
  static const inspectionFailWarning =
      'Reporting a fault raises an incident for your fleet team straight away.';

  // Task detail
  static const taskDetails = 'Task';
  static const accept = 'Accept';
  static const start = 'Start driving';
  static const complete = 'Complete';
  static const reportIssue = 'Report an issue';
  static const destination = 'Destination';
  static const instructions = 'Instructions';
  static const due = 'Due';
  static const eta = 'ETA';
  static const priorityUrgent = 'Urgent';
  static const routeUnavailable =
      'Route unavailable right now. You can still start the job.';
  static const completionNote = 'Completion note (optional)';
  static const attachPhoto = 'Attach proof photo';
  static const photoAttached = 'Photo attached';

  // Incident
  static const incidentTitle = 'What happened?';
  static const incidentDescription = 'Description';
  static const severity = 'Severity';
  static const submitReport = 'Send report';
  static const reportSent = 'Report sent to your fleet team.';

  // Generic
  static const loading = 'Loading…';
  static const retry = 'Try again';
  static const cancel = 'Cancel';
  static const somethingWentWrong = 'Something went wrong. Please try again.';
}
