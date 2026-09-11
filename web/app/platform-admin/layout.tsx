"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useRequireRole, useSession } from "@/lib/session";
import { strings } from "@/lib/strings";
import { Logo } from "@/components/Logo";
import { PulseLoader } from "@/components/PulseLoader";

/**
 * Platform Admin Console shell - `super_admin` only (Section 4a).
 *
 * Given a deliberately different visual identity from the customer console:
 * a light "internal tool" chrome with a standing FLEETBEAT INTERNAL banner,
 * so a staff member can never confuse the two at a glance. The hard gate is
 * the API's role dependency; this guard is the UI half of it.
 */
const NAV = [
  { href: "/platform-admin", label: strings.platform.organizations, phase: null },
  { href: "/platform-admin/devices", label: strings.platform.devices, phase: null },
  { href: "/platform-admin/audit", label: strings.platform.auditLog, phase: null },
] as const;

export default function PlatformAdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { session, loading } = useRequireRole(["super_admin"]);
  const { signOut } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  if (loading || !session) return <PulseLoader />;

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
  }

  return (
    <div className="min-h-screen bg-ink-50 text-ink-900">
      <div className="bg-ink-900 px-4 py-1.5 text-center text-[11px] font-semibold uppercase tracking-[0.2em] text-electric-300">
        FleetBeat Internal
      </div>

      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
          <div className="flex items-center gap-6">
            <Link href="/platform-admin" className="flex items-center gap-2.5">
              <Logo compact />
              <span className="text-sm font-semibold text-ink-900">
                {strings.platform.title}
              </span>
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <span className="hidden text-xs text-ink-400 md:inline">
              {session.user.email}
            </span>
            <button
              onClick={handleSignOut}
              className="fb-button rounded-lg border border-ink-200 !py-1.5 text-ink-700 hover:bg-ink-50"
            >
              {strings.nav.signOut}
            </button>
          </div>
        </div>

        <nav className="mx-auto max-w-7xl px-4">
          <ul className="flex gap-1">
            {NAV.map((item) => {
              const active =
                item.href === "/platform-admin"
                  ? pathname === item.href ||
                    pathname.startsWith("/platform-admin/organizations")
                  : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`inline-flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm transition ${
                      active
                        ? "border-electric font-medium text-electric-600"
                        : "border-transparent text-ink-400 hover:text-ink-700"
                    }`}
                  >
                    {item.label}
                    {item.phase && (
                      <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-400">
                        {item.phase}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
