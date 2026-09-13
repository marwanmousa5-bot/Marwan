"use client";

/**
 * Organisation settings and team management (Sections 4a, 4g, 9).
 *
 * This screen exists because of a Section 9 constraint: driver point weights
 * must not be hardcoded. They were always configurable through the API - this
 * is where an org admin can actually reach them, along with the alert
 * thresholds, the CO2 factors and the two behaviour switches (leaderboard
 * visibility and maintenance auto-booking) that other screens refer to.
 *
 * Everything here is org_admin only, and enforced server-side: a dispatcher
 * can read the settings but a PATCH from one is a 403.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import type {
  InviteUserResponse,
  Organization,
  OrganizationSettings,
  User,
  UserRole,
} from "@/lib/types";

/**
 * Labels for the tunables. Keys the API returns that are not listed here are
 * still rendered - a new weight added server-side must not silently vanish
 * from this screen.
 */
const POINT_LABELS: Record<string, string> = {
  harsh_braking: "Harsh braking",
  harsh_acceleration: "Harsh acceleration",
  speeding: "Speeding",
  geofence_breach: "Geofence breach",
  clean_streak: "Clean week",
  fuel_efficient: "Fuel-efficient driving",
};

const THRESHOLD_LABELS: Record<string, string> = {
  speeding_kph: "Speeding above (km/h)",
  harsh_braking_ms2: "Harsh braking below (m/s²)",
  harsh_acceleration_ms2: "Harsh acceleration above (m/s²)",
  idle_minutes: "Idling longer than (minutes)",
  document_expiry_warning_days: "Warn before document expiry (days)",
  maintenance_due_km: "Service due within (km)",
  maintenance_due_days: "Service due within (days)",
  fatigue_continuous_driving_hours: "Continuous driving limit (hours)",
  fatigue_min_rest_hours: "Minimum rest between shifts (hours)",
};

const FUEL_LABELS: Record<string, string> = {
  petrol: "Petrol",
  diesel: "Diesel",
  lpg: "LPG",
  electric: "Electric",
};

function humanise(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export default function SettingsPage() {
  const { session, refresh } = useSession();
  const isAdmin = session?.user.role === "org_admin";

  const [organization, setOrganization] = useState<Organization | null>(null);
  const [settings, setSettings] = useState<OrganizationSettings | null>(null);
  const [team, setTeam] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [org, config] = await Promise.all([
        api.get<Organization>("/organization"),
        api.get<OrganizationSettings>("/organization/settings"),
      ]);
      setOrganization(org);
      setSettings(config);
      if (isAdmin) {
        setTeam(await api.get<User[]>("/organization/users"));
      }
      setError(null);
    } catch {
      setError("We could not load your settings.");
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchSettings(patch: Partial<OrganizationSettings>) {
    setSaved(null);
    try {
      setSettings(
        await api.patch<OrganizationSettings>("/organization/settings", patch),
      );
      setSaved(strings.settings.saved);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : strings.settings.saveFailed);
    }
  }

  if (loading) {
    return <p className="fb-card text-sm text-ink-300">{strings.common.loading}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">{strings.settings.title}</h1>
        <p className="mt-1 text-sm text-ink-300">{strings.settings.subtitle}</p>
        {!isAdmin && (
          <p className="mt-2 rounded-lg border border-ink-600 px-3 py-2 text-xs text-ink-400">
            {strings.settings.adminOnly}
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}
      {saved && <p className="text-xs text-success">{saved}</p>}

      {organization && (
        <ProfileCard
          organization={organization}
          editable={isAdmin}
          onSaved={async (updated) => {
            setOrganization(updated);
            setSaved(strings.settings.saved);
            await refresh();
          }}
          onError={setError}
        />
      )}

      {settings && (
        <>
          <UnitsCard
            settings={settings}
            editable={isAdmin}
            onSave={patchSettings}
          />
          <PointsCard settings={settings} editable={isAdmin} onSave={patchSettings} />
          <NumberMapCard
            title={strings.settings.thresholdsTitle}
            hint={strings.settings.thresholdsHint}
            values={settings.alert_thresholds}
            labels={THRESHOLD_LABELS}
            step={0.1}
            editable={isAdmin}
            onSave={(next) => patchSettings({ alert_thresholds: next })}
          />
          <NumberMapCard
            title={strings.settings.emissionsTitle}
            hint={strings.settings.emissionsHint}
            values={settings.co2_emission_factors}
            labels={FUEL_LABELS}
            step={0.01}
            editable={isAdmin}
            onSave={(next) => patchSettings({ co2_emission_factors: next })}
          />
          <AutoBookCard
            settings={settings}
            editable={isAdmin}
            onSave={patchSettings}
          />
        </>
      )}

      {isAdmin && (
        <TeamCard team={team} onChanged={setTeam} onError={setError} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function ProfileCard({
  organization,
  editable,
  onSaved,
  onError,
}: {
  organization: Organization;
  editable: boolean;
  onSaved: (organization: Organization) => void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState({
    name: organization.name,
    industry: organization.industry ?? "",
    timezone: organization.timezone,
    contact_name: organization.contact_name ?? "",
    contact_email: organization.contact_email ?? "",
    contact_phone: organization.contact_phone ?? "",
  });
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      onSaved(
        await api.patch<Organization>("/organization", {
          ...form,
          industry: form.industry || null,
          contact_name: form.contact_name || null,
          contact_email: form.contact_email || null,
          contact_phone: form.contact_phone || null,
        }),
      );
    } catch (err) {
      onError(err instanceof ApiError ? err.message : strings.settings.saveFailed);
    } finally {
      setSaving(false);
    }
  }

  const fields: [keyof typeof form, string, string][] = [
    ["name", strings.settings.name, "text"],
    ["industry", strings.settings.industry, "text"],
    ["timezone", strings.settings.timezone, "text"],
    ["contact_name", strings.settings.contactName, "text"],
    ["contact_email", strings.settings.contactEmail, "email"],
    ["contact_phone", strings.settings.contactPhone, "tel"],
  ];

  return (
    <form onSubmit={submit} className="fb-card">
      <h2 className="text-sm font-semibold text-white">
        {strings.settings.profileTitle}
      </h2>
      <p className="mt-1 text-[11px] text-ink-400">{strings.settings.profileHint}</p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {fields.map(([key, label, type]) => (
          <label key={key} className="block">
            <span className="fb-label">{label}</span>
            <input
              type={type}
              value={form[key]}
              disabled={!editable}
              onChange={(event) =>
                setForm((current) => ({ ...current, [key]: event.target.value }))
              }
              className="fb-input mt-1 !py-1.5 text-xs disabled:opacity-60"
            />
          </label>
        ))}
      </div>

      {editable && (
        <button
          type="submit"
          disabled={saving}
          aria-label={`${strings.settings.save} - ${strings.settings.profileTitle}`}
          className="fb-button-primary mt-4 !py-1.5 text-xs disabled:opacity-50"
        >
          {saving ? strings.settings.saving : strings.settings.save}
        </button>
      )}
    </form>
  );
}

function UnitsCard({
  settings,
  editable,
  onSave,
}: {
  settings: OrganizationSettings;
  editable: boolean;
  onSave: (patch: Partial<OrganizationSettings>) => void;
}) {
  const [currency, setCurrency] = useState(settings.currency);

  return (
    <section className="fb-card">
      <h2 className="text-sm font-semibold text-white">
        {strings.settings.unitsTitle}
      </h2>

      <div className="mt-3 flex flex-wrap items-end gap-4">
        <div>
          <span className="fb-label">{strings.settings.distanceUnit}</span>
          <div className="mt-1 flex rounded-md border border-ink-600">
            {(["km", "mi"] as const).map((unit) => (
              <button
                key={unit}
                disabled={!editable}
                aria-pressed={settings.distance_unit === unit}
                onClick={() => onSave({ distance_unit: unit })}
                className={`px-3 py-1.5 text-xs transition disabled:opacity-60 ${
                  settings.distance_unit === unit
                    ? "bg-electric text-white"
                    : "text-ink-300 hover:bg-ink-700"
                }`}
              >
                {unit === "km" ? strings.settings.km : strings.settings.mi}
              </button>
            ))}
          </div>
        </div>

        <label className="block">
          <span className="fb-label">{strings.settings.currency}</span>
          <input
            value={currency}
            disabled={!editable}
            maxLength={8}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            onBlur={() => {
              if (currency && currency !== settings.currency) onSave({ currency });
            }}
            className="fb-input mt-1 w-24 !py-1.5 text-xs disabled:opacity-60"
          />
        </label>
      </div>
    </section>
  );
}

function PointsCard({
  settings,
  editable,
  onSave,
}: {
  settings: OrganizationSettings;
  editable: boolean;
  onSave: (patch: Partial<OrganizationSettings>) => void;
}) {
  const [weights, setWeights] = useState<Record<string, number>>(
    settings.point_weights,
  );
  const [baseline, setBaseline] = useState(settings.driver_points_baseline);

  const penalties = Object.entries(weights).filter(([, value]) => value < 0);
  const rewards = Object.entries(weights).filter(([, value]) => value >= 0);
  const dirty =
    baseline !== settings.driver_points_baseline ||
    Object.entries(weights).some(
      ([key, value]) => settings.point_weights[key] !== value,
    );

  function row([key, value]: [string, number]) {
    return (
      <label key={key} className="flex items-center justify-between gap-3 py-1.5">
        <span className="text-xs text-ink-200">
          {POINT_LABELS[key] ?? humanise(key)}
        </span>
        <input
          type="number"
          value={value}
          disabled={!editable}
          onChange={(event) =>
            setWeights((current) => ({
              ...current,
              [key]: Number(event.target.value),
            }))
          }
          className="fb-input fb-numeric w-20 !py-1 text-right text-xs disabled:opacity-60"
        />
      </label>
    );
  }

  return (
    <section className="fb-card">
      <h2 className="text-sm font-semibold text-white">
        {strings.settings.pointsTitle}
      </h2>
      <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
        {strings.settings.pointsHint}
      </p>

      <label className="mt-3 flex items-center justify-between gap-3">
        <span className="text-xs text-ink-200">{strings.settings.baseline}</span>
        <input
          type="number"
          min={0}
          value={baseline}
          disabled={!editable}
          onChange={(event) => setBaseline(Number(event.target.value))}
          className="fb-input fb-numeric w-20 !py-1 text-right text-xs disabled:opacity-60"
        />
      </label>

      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <p className="fb-label">{strings.settings.penalties}</p>
          <div className="mt-1 divide-y divide-ink-700/60">{penalties.map(row)}</div>
        </div>
        <div>
          <p className="fb-label">{strings.settings.rewards}</p>
          <div className="mt-1 divide-y divide-ink-700/60">{rewards.map(row)}</div>
        </div>
      </div>

      <label className="mt-4 flex cursor-pointer items-start gap-2">
        <input
          type="checkbox"
          checked={settings.show_leaderboard_to_drivers}
          disabled={!editable}
          onChange={(event) =>
            onSave({ show_leaderboard_to_drivers: event.target.checked })
          }
          className="mt-0.5 h-3.5 w-3.5 accent-electric"
        />
        <span>
          <span className="block text-xs text-ink-100">
            {strings.settings.leaderboardVisible}
          </span>
          <span className="block text-[11px] text-ink-400">
            {strings.settings.leaderboardHint}
          </span>
        </span>
      </label>

      {editable && dirty && (
        <button
          onClick={() =>
            onSave({ point_weights: weights, driver_points_baseline: baseline })
          }
          aria-label={`${strings.settings.save} - ${strings.settings.pointsTitle}`}
          className="fb-button-primary mt-4 !py-1.5 text-xs"
        >
          {strings.settings.save}
        </button>
      )}
    </section>
  );
}

function NumberMapCard({
  title,
  hint,
  values,
  labels,
  step,
  editable,
  onSave,
}: {
  title: string;
  hint: string;
  values: Record<string, number>;
  labels: Record<string, string>;
  step: number;
  editable: boolean;
  onSave: (values: Record<string, number>) => void;
}) {
  const [draft, setDraft] = useState(values);
  const dirty = Object.entries(draft).some(([key, value]) => values[key] !== value);

  return (
    <section className="fb-card">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      <p className="mt-1 text-[11px] text-ink-400">{hint}</p>

      <div className="mt-3 grid gap-x-6 sm:grid-cols-2">
        {Object.entries(draft).map(([key, value]) => (
          <label
            key={key}
            className="flex items-center justify-between gap-3 border-b border-ink-700/60 py-1.5"
          >
            <span className="text-xs text-ink-200">{labels[key] ?? humanise(key)}</span>
            <input
              type="number"
              step={step}
              value={value}
              disabled={!editable}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  [key]: Number(event.target.value),
                }))
              }
              className="fb-input fb-numeric w-24 !py-1 text-right text-xs disabled:opacity-60"
            />
          </label>
        ))}
      </div>

      {editable && dirty && (
        <button
          onClick={() => onSave(draft)}
          aria-label={`${strings.settings.save} - ${title}`}
          className="fb-button-primary mt-4 !py-1.5 text-xs"
        >
          {strings.settings.save}
        </button>
      )}
    </section>
  );
}

function AutoBookCard({
  settings,
  editable,
  onSave,
}: {
  settings: OrganizationSettings;
  editable: boolean;
  onSave: (patch: Partial<OrganizationSettings>) => void;
}) {
  const on = settings.maintenance_auto_book_enabled;
  return (
    <section
      className={`fb-card ${on ? "border-warning/40" : ""}`}
      aria-live="polite"
    >
      <h2 className="text-sm font-semibold text-white">
        {strings.settings.autoBookTitle}
      </h2>

      <label className="mt-3 flex cursor-pointer items-start gap-2">
        <input
          type="checkbox"
          checked={on}
          disabled={!editable}
          onChange={(event) =>
            onSave({ maintenance_auto_book_enabled: event.target.checked })
          }
          className="mt-0.5 h-3.5 w-3.5 accent-warning"
        />
        <span>
          <span className="block text-xs text-ink-100">
            {strings.settings.autoBookLabel}
          </span>
          <span className="block text-[11px] leading-relaxed text-ink-400">
            {strings.settings.autoBookHint}
          </span>
        </span>
      </label>

      <p
        className={`mt-3 text-[11px] font-medium ${on ? "text-warning" : "text-ink-400"}`}
      >
        {on ? strings.settings.autoBookOn : strings.settings.autoBookOff}
      </p>
    </section>
  );
}

function TeamCard({
  team,
  onChanged,
  onError,
}: {
  team: User[];
  onChanged: (team: User[]) => void;
  onError: (message: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("dispatcher");
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function invite(event: FormEvent) {
    event.preventDefault();
    setInviting(true);
    try {
      const result = await api.post<InviteUserResponse>("/organization/users", {
        email,
        full_name: fullName,
        role,
      });
      setLink(result.activation_url);
      setCopied(false);
      setEmail("");
      setFullName("");
      onChanged([...team, result.user]);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : strings.settings.saveFailed);
    } finally {
      setInviting(false);
    }
  }

  async function setStatus(user: User, action: "suspend" | "reactivate") {
    try {
      const updated = await api.post<User>(
        `/organization/users/${user.id}/${action}`,
      );
      onChanged(team.map((u) => (u.id === updated.id ? updated : u)));
    } catch (err) {
      onError(err instanceof ApiError ? err.message : strings.settings.saveFailed);
    }
  }

  return (
    <section className="fb-card">
      <h2 className="text-sm font-semibold text-white">{strings.settings.teamTitle}</h2>
      <p className="mt-1 text-[11px] text-ink-400">{strings.settings.teamHint}</p>

      <form onSubmit={invite} className="mt-4 flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="fb-label">{strings.settings.inviteEmail}</span>
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="fb-input mt-1 !py-1.5 text-xs"
          />
        </label>
        <label className="block">
          <span className="fb-label">{strings.settings.inviteName}</span>
          <input
            required
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            className="fb-input mt-1 !py-1.5 text-xs"
          />
        </label>
        <label className="block">
          <span className="fb-label">{strings.settings.inviteRole}</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as UserRole)}
            className="fb-input mt-1 !py-1.5 text-xs"
          >
            <option value="dispatcher">Dispatcher</option>
            <option value="driver">Driver</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={inviting}
          className="fb-button-primary !py-1.5 text-xs disabled:opacity-50"
        >
          {inviting ? strings.settings.inviting : strings.settings.invite}
        </button>
      </form>

      {link && (
        <div className="mt-3 rounded-lg border border-electric/40 bg-electric/5 p-3">
          <p className="text-[11px] text-ink-200">{strings.settings.inviteDone}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="fb-numeric min-w-0 flex-1 truncate rounded bg-ink-900 px-2 py-1 text-[11px] text-electric-200">
              {link}
            </code>
            <button
              onClick={async () => {
                await navigator.clipboard.writeText(link);
                setCopied(true);
              }}
              className="fb-button-ghost !py-1 text-[11px]"
            >
              {copied ? strings.settings.copied : strings.settings.copy}
            </button>
          </div>
        </div>
      )}

      <p className="mt-3 text-[11px] text-ink-500">{strings.settings.noDeviceRole}</p>

      {team.length === 0 ? (
        <p className="mt-3 text-xs text-ink-400">{strings.settings.teamEmpty}</p>
      ) : (
        <ul className="mt-3 divide-y divide-ink-700/60">
          {team.map((user) => (
            <li
              key={user.id}
              className="flex flex-wrap items-center justify-between gap-2 py-2"
            >
              <span className="min-w-0">
                <span className="block truncate text-xs text-ink-100">
                  {user.full_name}
                </span>
                <span className="block truncate text-[11px] text-ink-400">
                  {user.email} · {user.role.replace(/_/g, " ")}
                </span>
              </span>
              <span className="flex items-center gap-3">
                <span
                  className={`fb-badge ${
                    user.status === "active"
                      ? "bg-success/15 text-success"
                      : user.status === "pending_activation"
                        ? "bg-warning/15 text-warning"
                        : "bg-ink-700 text-ink-300"
                  }`}
                >
                  {user.status.replace(/_/g, " ")}
                </span>
                {user.role !== "org_admin" && (
                  <button
                    onClick={() =>
                      setStatus(
                        user,
                        user.status === "suspended" ? "reactivate" : "suspend",
                      )
                    }
                    className="text-[11px] text-ink-400 hover:text-ink-200"
                  >
                    {user.status === "suspended"
                      ? strings.settings.reactivate
                      : strings.settings.suspend}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
