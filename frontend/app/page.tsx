import Link from "next/link";
import {
  Link2,
  Wand2,
  Flag,
  TrendingUp,
  Map as MapIcon,
  ChevronRight,
  Compass,
  Trophy,
  Users,
  Plus,
} from "lucide-react";

export const metadata = {
  title: "Achiv-Planner — Stop planning achievements. Start finishing them.",
};

export default function LandingPage() {
  return (
    <div className="relative text-fg-1 bg-bg-0 min-h-screen">
      <div
        aria-hidden
        className="absolute top-0 right-0 w-[55%] h-[700px] pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at top right, rgba(212, 160, 74, 0.12), transparent 60%)",
        }}
      />

      <LandingNav />

      {/* Hero */}
      <section className="relative grid items-center gap-16 px-6 md:px-20 py-16 md:py-24 lg:grid-cols-[1fr_1.1fr] max-w-[1440px] mx-auto">
        <div>
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded mb-7 font-mono text-[10px] uppercase tracking-[0.12em]"
            style={{
              background: "rgba(143, 191, 122, 0.08)",
              border: "1px solid rgba(143, 191, 122, 0.25)",
              color: "var(--good)",
            }}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-good" />
            Beta · Free while we iterate
          </div>

          <h1 className="font-display text-5xl md:text-6xl font-semibold leading-[1.05] tracking-tight mb-6">
            Stop planning achievements.
            <br />
            Start <span className="text-gold-1">finishing</span> them.
          </h1>

          <p className="text-[17px] md:text-[18px] leading-[1.55] text-fg-2 mb-9 max-w-[520px]">
            Achiv-Planner turns your character&apos;s achievement log into an optimized, session-sized
            route. Ranked by points-per-hour. Filtered by what your character can actually do.
            Exportable so it works even when your wifi doesn&apos;t.
          </p>

          <div className="flex gap-3 mb-7 flex-wrap">
            <Link
              href="/login"
              className="btn btn-primary"
              style={{ padding: "13px 20px", fontSize: 14 }}
            >
              <Link2 size={14} /> Connect with Battle.net
            </Link>
            <Link
              href="#showcase"
              className="btn"
              style={{ padding: "13px 18px", fontSize: 14 }}
            >
              See a sample route <ChevronRight size={12} />
            </Link>
          </div>

          <div className="flex gap-5 pt-6 border-t border-border-1 flex-wrap">
            {[
              { n: "2,184", l: "Achievements tracked" },
              { n: "184", l: "Zones mapped" },
              { n: "42", l: "Seasonal windows" },
            ].map((s) => (
              <div key={s.l}>
                <div className="font-display text-[22px] font-semibold text-gold-1">{s.n}</div>
                <div className="font-mono text-[10px] text-fg-3 uppercase tracking-[0.08em] mt-0.5">
                  {s.l}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative">
          <DashboardMockup />
        </div>
      </section>

      {/* How it works */}
      <section className="px-6 md:px-20 py-20 md:py-24 border-t border-border-1 bg-bg-1">
        <div className="max-w-[1200px] mx-auto">
          <div className="flex items-end justify-between gap-6 mb-14 flex-wrap">
            <div>
              <div className="font-mono text-[11px] text-gold-2 uppercase tracking-[0.14em] mb-2.5">
                How it works
              </div>
              <h2 className="font-display text-3xl md:text-[40px] font-semibold tracking-tight m-0">
                From login to loot, in three steps.
              </h2>
            </div>
            <div className="font-mono text-[11px] text-fg-3 uppercase tracking-[0.1em] text-right">
              Avg setup time
              <br />
              <span className="text-gold-1 text-[22px] font-display tracking-normal">~12s</span>
            </div>
          </div>

          <div className="grid gap-6 relative md:grid-cols-3">
            <div
              aria-hidden
              className="hidden md:block absolute top-[44px] left-[16%] right-[16%] h-px"
              style={{ borderTop: "1px dashed var(--border-3)" }}
            />

            {[
              {
                step: "01",
                title: "Connect",
                body:
                  "Sign in with Battle.net. Read-only. We pull your roster, achievements, reputations, and professions — no manual entry, ever.",
                Icon: Link2,
              },
              {
                step: "02",
                title: "Pick a goal",
                body:
                  "Completionist, points-per-hour, a specific meta, or whatever's time-gated this month. Tell the engine what \"done\" means.",
                Icon: Wand2,
              },
              {
                step: "03",
                title: "Follow the road",
                body:
                  "Get a zone-by-zone timeline sized to your session length. Check stops off. Export the whole plan offline.",
                Icon: Flag,
              },
            ].map((s) => (
              <div key={s.step} className="relative z-10">
                <div
                  className="w-[88px] h-[88px] mx-auto mb-5 rounded-full grid place-items-center relative"
                  style={{ background: "var(--bg-2)", border: "2px solid var(--border-2)" }}
                >
                  <s.Icon size={30} className="text-gold-1" />
                  <div
                    className="absolute -top-1.5 -right-1.5 w-7 h-7 rounded-full grid place-items-center font-display font-bold text-[12px]"
                    style={{
                      background: "linear-gradient(180deg, var(--gold-2), var(--gold-3))",
                      color: "#1A1408",
                    }}
                  >
                    {s.step}
                  </div>
                </div>
                <div className="text-center">
                  <h3 className="font-display text-[22px] font-semibold mb-2.5">{s.title}</h3>
                  <p className="text-sm leading-[1.55] text-fg-2 max-w-[340px] mx-auto m-0">{s.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Showcase */}
      <section id="showcase" className="px-6 md:px-20 py-24">
        <div className="max-w-[1200px] mx-auto">
          <div className="text-center mb-10">
            <div className="font-mono text-[11px] text-gold-2 uppercase tracking-[0.14em] mb-2.5">
              The product
            </div>
            <h2 className="font-display text-3xl md:text-[40px] font-semibold tracking-tight m-0">
              Three views. One source of truth.
            </h2>
          </div>

          <div
            className="p-6 min-h-[540px]"
            style={{
              background: "var(--bg-1)",
              border: "1px solid var(--border-1)",
              borderRadius: "var(--r-xl)",
            }}
          >
            <DashboardMockup />
          </div>

          <div className="text-center mt-10 text-sm text-fg-3">
            Every view updates live when Blizzard&apos;s servers do.
          </div>
        </div>
      </section>

      {/* Differentiators */}
      <section className="px-6 md:px-20 py-20 border-y border-border-1 bg-bg-1">
        <div className="max-w-[1200px] mx-auto grid gap-8 md:grid-cols-3">
          {[
            {
              Icon: TrendingUp,
              title: "Points-per-hour first",
              body:
                "Every stop is scored by expected gain ÷ estimated time. Clustered by zone. Ordered by geography. No backtracking, ever.",
            },
            {
              Icon: Link2,
              title: "Battle.net sync",
              body:
                "One-click OAuth. Read-only. No addons, no logs, no spreadsheets. Your roster is live the moment you connect.",
            },
            {
              Icon: MapIcon,
              title: "Offline export",
              body:
                "Export any route to Markdown, JSON, or a printable travel guide. Your plan goes with you — wifi optional.",
            },
          ].map((f) => (
            <div key={f.title}>
              <div className="text-gold-1 mb-4">
                <f.Icon size={24} />
              </div>
              <h4 className="font-display text-[22px] font-semibold mb-2.5">{f.title}</h4>
              <p className="text-sm leading-[1.6] text-fg-2 m-0">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-6 md:px-20 py-24 text-center">
        <h2 className="font-display text-4xl md:text-5xl font-semibold tracking-tight mb-4">
          Twelve seconds to a better route.
        </h2>
        <p className="text-base md:text-[17px] text-fg-2 mb-8">
          Free during beta. No credit card. Disconnect anytime.
        </p>
        <Link
          href="/login"
          className="btn btn-primary inline-flex"
          style={{ padding: "15px 26px", fontSize: 14 }}
        >
          <Link2 size={14} /> Connect with Battle.net
        </Link>
      </section>

      <LandingFooter />
    </div>
  );
}

function LandingNav() {
  return (
    <nav
      className="relative flex items-center justify-between px-6 md:px-10 py-5 border-b border-border-1 z-10"
      style={{ background: "rgba(10, 11, 15, 0.7)", backdropFilter: "blur(8px)" }}
    >
      <Link href="/" className="flex items-center gap-2.5">
        <div
          className="w-7 h-7 rounded grid place-items-center font-display font-bold text-base"
          style={{
            background: "linear-gradient(180deg, var(--gold-1), var(--gold-3))",
            color: "#1A1408",
          }}
        >
          A
        </div>
        <div className="leading-none">
          <div className="font-display text-lg font-semibold">Achiv</div>
          <div className="font-mono text-[9px] text-fg-3 uppercase tracking-[0.14em] mt-0.5">
            Route Optimizer
          </div>
        </div>
      </Link>

      <div className="hidden md:flex gap-8 items-center text-sm text-fg-2">
        <a href="#showcase" className="hover:text-fg-1">How it works</a>
        <a href="#showcase" className="hover:text-fg-1">Features</a>
        <Link href="/login" className="hover:text-fg-1">Sign in</Link>
      </div>

      <div className="flex gap-2.5 items-center">
        <Link href="/login" className="btn" style={{ padding: "8px 14px", fontSize: 13 }}>
          Sign in
        </Link>
        <Link
          href="/login"
          className="btn btn-primary hidden sm:inline-flex"
          style={{ padding: "8px 14px", fontSize: 13 }}
        >
          <Link2 size={13} /> Connect Battle.net
        </Link>
      </div>
    </nav>
  );
}

function LandingFooter() {
  return (
    <footer className="px-6 md:px-20 pt-12 pb-10 border-t border-border-1 grid gap-10 md:gap-16 md:grid-cols-[1.5fr_1fr_1fr_1fr] text-sm">
      <div>
        <div className="flex items-center gap-2.5 mb-3.5">
          <div
            className="w-6 h-6 rounded grid place-items-center font-display font-bold text-[14px]"
            style={{
              background: "linear-gradient(180deg, var(--gold-1), var(--gold-3))",
              color: "#1A1408",
            }}
          >
            A
          </div>
          <span className="font-display text-base font-semibold">Achiv-Planner</span>
        </div>
        <p className="text-fg-3 leading-[1.55] mb-3.5 max-w-[320px] m-0">
          A fan-made route optimizer for World of Warcraft achievement hunters. Not affiliated with
          Blizzard Entertainment.
        </p>
        <div className="font-mono text-[10px] text-fg-4 tracking-[0.08em] uppercase">
          © 2026 Achiv Labs · v0.9.2-beta
        </div>
      </div>
      {[
        { title: "Product", links: ["Features", "How it works", "Changelog", "Roadmap"] },
        { title: "Resources", links: ["Documentation", "Data sources", "API reference", "Status"] },
        { title: "Community", links: ["Discord", "GitHub", "Privacy", "Terms"] },
      ].map((col) => (
        <div key={col.title}>
          <div className="font-mono text-[11px] text-fg-2 uppercase tracking-[0.12em] mb-4 font-semibold">
            {col.title}
          </div>
          <div className="flex flex-col gap-2.5">
            {col.links.map((l) => (
              <a key={l} href="#" className="text-fg-3 text-sm hover:text-fg-1">
                {l}
              </a>
            ))}
          </div>
        </div>
      ))}
    </footer>
  );
}

function DashboardMockup() {
  return (
    <div
      className="overflow-hidden"
      style={{
        background: "var(--bg-1)",
        border: "1px solid var(--border-2)",
        borderRadius: "var(--r-xl)",
        boxShadow: "0 40px 80px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(212, 160, 74, 0.1)",
      }}
    >
      <div
        className="flex items-center gap-2 px-3.5 py-2.5 border-b border-border-1"
        style={{ background: "var(--bg-0)" }}
      >
        <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#3A4058" }} />
        <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#3A4058" }} />
        <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#3A4058" }} />
        <div className="flex-1 text-center font-mono text-[10px] text-fg-3">
          achiv-planner.app / dashboard
        </div>
      </div>

      <div className="grid min-h-[460px]" style={{ gridTemplateColumns: "160px 1fr" }}>
        <div className="border-r border-border-1 p-3 pt-4" style={{ background: "var(--bg-0)" }}>
          <div className="flex items-center gap-2 px-1 mb-4">
            <div
              className="w-[22px] h-[22px] rounded grid place-items-center font-display font-bold text-[12px]"
              style={{
                background: "linear-gradient(180deg, var(--gold-1), var(--gold-3))",
                color: "#1A1408",
              }}
            >
              A
            </div>
            <div className="font-display text-sm font-semibold">Achiv</div>
          </div>
          {[
            { n: "Home", Icon: Compass, active: true },
            { n: "My Route", Icon: Flag },
            { n: "Browse", Icon: Trophy },
            { n: "Characters", Icon: Users },
          ].map((r) => (
            <div
              key={r.n}
              className="flex items-center gap-2.5 px-2.5 py-1.5 rounded mb-0.5 text-[12px]"
              style={{
                background: r.active ? "var(--bg-3)" : "transparent",
                color: r.active ? "var(--gold-1)" : "var(--fg-2)",
                fontWeight: r.active ? 600 : 400,
              }}
            >
              <r.Icon size={14} /> {r.n}
            </div>
          ))}
          <button className="btn btn-primary w-full mt-3" style={{ padding: "8px 10px", fontSize: 11 }}>
            <Plus size={11} /> New Route
          </button>
        </div>

        <div className="p-5">
          <div className="font-mono text-[9px] text-gold-2 uppercase tracking-[0.14em] mb-1.5 flex items-center gap-1.5">
            <span
              className="inline-block w-1 h-1"
              style={{ background: "var(--gold-2)", transform: "rotate(45deg)" }}
            />
            Welcome back, Sylaria
          </div>
          <h3 className="font-display text-[22px] font-semibold mb-4 m-0">The road ahead</h3>

          <div
            className="relative overflow-hidden mb-3.5"
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "var(--r-lg)",
              padding: 18,
            }}
          >
            <div
              aria-hidden
              className="absolute pointer-events-none"
              style={{
                top: -40,
                right: -40,
                width: 200,
                height: 200,
                background: "radial-gradient(circle, var(--gold-glow), transparent 70%)",
              }}
            />

            <div className="flex justify-between items-start relative">
              <div>
                <div className="font-mono text-[9px] text-gold-2 uppercase tracking-[0.14em] mb-1">
                  Active Route
                </div>
                <div className="font-display text-[18px] font-semibold">The Long Road Home</div>
                <div className="text-[11px] text-fg-3 italic mt-0.5">
                  working toward{" "}
                  <span className="text-gold-1 not-italic">What a Long, Strange Trip It&apos;s Been</span>
                </div>
              </div>
              <div
                className="px-2 py-0.5 rounded-full text-[9px] font-mono uppercase tracking-[0.1em]"
                style={{
                  background: "var(--gold-4)",
                  color: "var(--gold-1)",
                  border: "1px solid var(--gold-3)",
                }}
              >
                Session 2 / 6
              </div>
            </div>

            <div
              className="mt-3.5 h-[5px] rounded overflow-hidden"
              style={{ background: "var(--bg-0)", border: "1px solid var(--border-1)" }}
            >
              <div
                className="h-full"
                style={{
                  width: "26%",
                  background: "linear-gradient(90deg, var(--gold-3), var(--gold-1))",
                  boxShadow: "0 0 12px var(--gold-glow)",
                }}
              />
            </div>
            <div className="mt-1.5 flex justify-between font-mono text-[9px] text-fg-3 uppercase tracking-[0.08em]">
              <span>11 / 42 stops</span>
              <span>26%</span>
            </div>

            <div className="mt-3.5 grid grid-cols-2 gap-2.5">
              <div>
                <div className="font-mono text-[9px] text-fg-3 uppercase tracking-[0.1em]">
                  Points earned
                </div>
                <div className="font-display text-[20px] font-semibold text-gold-1">
                  850{" "}
                  <span className="text-[11px] text-fg-3 font-mono font-normal">/ 3,280</span>
                </div>
              </div>
              <div>
                <div className="font-mono text-[9px] text-fg-3 uppercase tracking-[0.1em]">
                  Est. time left
                </div>
                <div className="font-display text-[20px] font-semibold">35h</div>
              </div>
            </div>
          </div>

          <div className="flex gap-2 overflow-hidden">
            {[
              { n: 1, done: true },
              { n: 2, current: true },
              { n: 3 },
              { n: 4 },
              { n: 5 },
              { n: 6 },
            ].map((s) => (
              <div
                key={s.n}
                className="flex-1 min-w-0"
                style={{
                  padding: "8px 10px",
                  borderRadius: 6,
                  background: s.current ? "rgba(233, 190, 106, 0.08)" : "var(--bg-2)",
                  border: "1px solid " + (s.current ? "var(--gold-3)" : "var(--border-1)"),
                  opacity: s.done ? 0.5 : 1,
                }}
              >
                <div
                  className="font-mono text-[8px] uppercase tracking-[0.1em]"
                  style={{ color: s.current ? "var(--gold-2)" : "var(--fg-3)" }}
                >
                  Session {s.n}
                </div>
                <div
                  className="text-[11px] font-medium mt-0.5"
                  style={{
                    color: s.done ? "var(--fg-3)" : "var(--fg-1)",
                    textDecoration: s.done ? "line-through" : "none",
                  }}
                >
                  {["Orgrimmar", "Stonetalon", "Desolace", "Feralas", "Tanaris", "Uldum"][s.n - 1]}
                </div>
                <div className="font-mono text-[9px] text-fg-3 mt-0.5">
                  ~{[6, 8, 7, 9, 8, 9][s.n - 1]}h
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
