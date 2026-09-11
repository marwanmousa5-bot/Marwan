"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useRequireRole, useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import { AssistantPanel } from "@/components/ai/AssistantPanel";
import { Logo } from "@/components/Logo";
import { PulseLoader } from "@/components/PulseLoader";

/**
 * Customer-facing console shell (org_admin / dispatcher).
 *
 * Deliberately styled apart from the Platform Admin Console so the two can
 * never be mistaken for one another (Section 4a).
 */
const NAV = [
  { href: "/dashboard", label: strings.nav.liveTracking, phase: null },
  { href: "/dashboard/tasks", label: strings.nav.tasks, phase: null },
  { href: "/dashboard/history", label: strings.nav.history, phase: null },
  { href: "/dashboard/vehicles", label: strings.nav.vehicles, phase: null },
  { href: "/dashboard/drivers", label: strings.nav.drivers, phase: null },
  { href: "/dashboard/zones", label: strings.nav.zones, phase: null },
  {
    href: "/dashboard/maintenance",
    label: strings.nav.maintenance,
    phase: null,
  },
  { href: "/dashboard/fuel", label: strings.nav.fuel, phase: null },
  { href: "/dashboard/compliance", label: strings.nav.compliance, phase: null },
  { href: "/dashboard/analytics", label: strings.nav.analytics, phase: null },
  { href: "/dashboard/safety", label: strings.nav.safety, phase: null },
  { href: "/dashboard/reports", label: strings.nav.reports, phase: null },
] as const;

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { session, loading } = useRequireRole(["org_admin", "dispatcher"]);
  const { signOut } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  if (loading || !session) return <PulseLoader />;

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen flex-col bg-ink-900">
      {session.is_impersonating && (
        <div className="bg-coral px-4 py-2 text-center text-xs font-semibold text-ink-900">
          {strings.platform.impersonateWarning}
        </div>
      )}

      <header className="flex h-14 items-center justify-between border-b border-ink-700 bg-ink-800 px-4">
        <div className="flex items-center gap-6">
          <Link href="/dashboard">
            <Logo />
          </Link>
          <span className="hidden text-sm text-ink-300 sm:inline">
            {session.organization_name}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="hidden text-xs text-ink-400 md:inline">
            {strings.common.signedInAs} {session.user.email}
          </span>
          <button onClick={handleSignOut} className="fb-button-ghost !py-1.5">
            {strings.nav.signOut}
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        <nav className="hidden w-56 shrink-0 border-r border-ink-700 bg-ink-800/50 p-3 md:block">
          <ul className="space-y-1">
            {NAV.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/dashboard" && pathname.startsWith(item.href));
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm transition ${
                      active
                        ? "bg-electric/15 font-medium text-electric-300"
                        : "text-ink-200 hover:bg-ink-700"
                    }`}
                  >
                    <span>{item.label}</span>
                    {item.phase && (
                      <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-400">
                        {item.phase}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <main className="flex-1 overflow-x-hidden p-4 md:p-6">{children}</main>
      </div>

      {/* Reachable from every console screen, docked so it never covers the map. */}
      <AssistantPanel />
    </div>
  );
}
