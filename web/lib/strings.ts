/**
 * All user-facing copy lives here.
 *
 * English only for now (Section 9 forbids building i18n infrastructure), but
 * keeping strings out of JSX means a future extraction is a mechanical
 * change rather than an archaeology exercise.
 */
export const strings = {
  brand: {
    name: "FleetBeat",
    tagline: "The live pulse of your fleet.",
  },
  login: {
    title: "Sign in to FleetBeat",
    subtitle: "Fleet operations console",
    emailLabel: "Work email",
    passwordLabel: "Password",
    submit: "Sign in",
    submitting: "Signing in…",
    noSignup:
      "FleetBeat accounts are created by our team during onboarding. If you need access, contact your fleet administrator.",
    genericError: "We could not sign you in. Please check your details.",
  },
  activate: {
    title: "Set your password",
    subtitle:
      "Choose a password for your FleetBeat account. This link can only be used once.",
    passwordLabel: "New password",
    confirmLabel: "Confirm password",
    submit: "Set password and continue",
    submitting: "Setting your password…",
    mismatch: "Those passwords do not match.",
    requirements:
      "At least 12 characters, with upper and lower case letters and a number.",
    missingToken:
      "This activation link is incomplete. Ask your FleetBeat contact to re-issue it.",
    success: "Your password is set. You can sign in now.",
  },
  nav: {
    liveTracking: "Live Tracking",
    tasks: "Tasks",
    vehicles: "Vehicles",
    drivers: "Drivers",
    maintenance: "Maintenance",
    fuel: "Fuel & Energy",
    compliance: "Compliance",
    analytics: "Analytics",
    settings: "Settings",
    signOut: "Sign out",
  },
  dashboard: {
    liveTitle: "Live Tracking",
    liveSubtitle: "Every vehicle, in real time.",
    comingInPhase2:
      "The live map, vehicle sidebar, KPI strip and alerts feed arrive in Phase 2, once the device inventory and GPS simulation engine are in place.",
    vehiclesTitle: "Vehicles",
    driversTitle: "Drivers",
    notTracked: "Not tracked",
    notTrackedHint:
      "This vehicle has no active GPS device yet. FleetBeat provisions and links devices for you.",
  },
  platform: {
    title: "Platform Admin Console",
    subtitle: "FleetBeat internal — all organizations",
    organizations: "Organizations",
    newOrganization: "New organization",
    devices: "Devices",
    auditLog: "Audit log",
    provisionTitle: "Provision a new organization",
    provisionIntro:
      "This creates the customer's organization and its first administrator. The activation link is shown once here — copy it and send it to them.",
    activationReady: "Organization created",
    activationHint:
      "Copy this one-time link and send it to the new administrator. It is not emailed automatically.",
    copyLink: "Copy link",
    copied: "Copied",
    impersonate: "Open as customer",
    impersonateWarning:
      "You are viewing this account as its administrator. Every impersonation is recorded in the audit log.",
    suspend: "Suspend",
    reactivate: "Reactivate",
  },
  common: {
    loading: "Loading…",
    retry: "Try again",
    cancel: "Cancel",
    save: "Save",
    search: "Search",
    empty: "Nothing here yet.",
    signedInAs: "Signed in as",
  },
} as const;
