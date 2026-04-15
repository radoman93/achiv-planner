# Phase 5 — Frontend

Depends on: Phase 4 fully complete (all API endpoints working).
Complete all tasks before starting Phase 6.
After each task, verify acceptance criteria and update docs/progress.md.

---

## Design System

**Color palette (WoW-themed dark UI):**
- Background: `#0d0d0d` (near black)
- Surface: `#1a1a2e` (dark navy)
- Surface elevated: `#16213e`
- Border: `#2d2d4e`
- Primary accent: `#c9a227` (achievement gold)
- Primary hover: `#e8bc2d`
- Text primary: `#f0f0f0`
- Text secondary: `#9aa0b4`
- Alliance blue: `#1a6eb5`
- Horde red: `#b31c1c`
- Success: `#2ecc71`
- Warning: `#f39c12`
- Error: `#e74c3c`
- Confidence tiers: verified `#2ecc71`, high `#27ae60`, medium `#f39c12`, low `#e67e22`, research `#e74c3c`

**Typography:**
- Headings: system font stack, bold
- Body: system font stack, regular
- Achievement names: slightly larger than body, gold color
- Points badges: monospace, gold

**Component patterns:**
- Cards with `background: Surface`, `border: 1px solid Border`, `border-radius: 8px`
- Buttons: primary in gold, ghost variant in transparent with gold border
- Badges: small pill shapes for confidence tiers, faction, expansion
- Achievement icons: fetched from `https://wow.zamimg.com/images/wow/icons/medium/{icon_name}.jpg`

---

## TASK 5.1 — Next.js Project Setup

**Initialize project** (if not done in Task 0.1):
```bash
npx create-next-app@latest frontend --typescript --tailwind --app --no-src-dir
```

**Install additional dependencies:**
```
shadcn/ui (init with neutral base)
react-query (@tanstack/react-query v5)
recharts
axios (or use native fetch — pick one and be consistent)
date-fns
lucide-react
```

**Configure Tailwind** to include the design system colors above as custom CSS variables in `globals.css`.

**API client (`frontend/lib/api-client.ts`):**
- Base URL from `NEXT_PUBLIC_API_URL` env var
- Automatically includes credentials (for httpOnly cookie auth)
- Global error handler: on 401 response → clear local state, redirect to /login
- On 429 response → extract `retry_after_seconds`, throw typed `RateLimitError`
- TypeScript interfaces for all API response shapes

**React Query setup (`frontend/lib/query-client.ts`):**
- Default stale time: 5 minutes
- Default retry: 2 (don't retry on 401 or 404)
- Global error boundary integration

**Auth state (`frontend/lib/auth.ts`):**
- `useAuth()` hook: returns `{user, isLoading, isAuthenticated}`
- Fetches `/api/users/me` — if 401, user is not authenticated
- Caches result in React Query

**Middleware (`frontend/middleware.ts`):**
Protected routes: `/dashboard`, `/routes`, `/characters`, `/calendar`
If not authenticated (no valid cookie): redirect to `/login`
If authenticated and on `/login` or `/register`: redirect to `/dashboard`

**Acceptance:**
- `npm run dev` starts without errors
- `npm run build` completes without TypeScript errors
- API client correctly sends cookies with requests
- Middleware redirects unauthenticated users from `/dashboard` to `/login`
- Middleware redirects authenticated users from `/login` to `/dashboard`
- Design system colors applied as CSS custom properties

---

## TASK 5.2 — Auth Pages

**Files:**
- `frontend/app/(auth)/login/page.tsx`
- `frontend/app/(auth)/register/page.tsx`
- `frontend/app/(auth)/battlenet/callback/page.tsx`
- `frontend/app/(auth)/layout.tsx` — centered card layout, no navigation

**Login page:**
- Email and password inputs
- "Sign in" primary button
- Battle.net OAuth button (styled with Battle.net blue, Blizzard icon from lucide or custom SVG)
- "Don't have an account? Register" link
- Error display for invalid credentials
- Loading state on submit

**Register page:**
- Email, password, confirm password inputs
- Password strength indicator
- Battle.net OAuth button (preferred path — label it "Fastest: Connect Battle.net")
- "Already have an account? Sign in" link
- Validate passwords match client-side before submitting

**Battle.net callback page:**
- Shows loading spinner with "Connecting your Battle.net account..."
- On mount: the auth cookie is already set by the backend redirect — just call `/api/users/me`
- If successful: redirect to `/onboarding` (new user) or `/dashboard` (returning)
- If error (state mismatch etc.): show error message with "Try again" button

**Form handling:**
- Use React state (no form library needed — forms are simple)
- Client-side validation before API call
- Show API error messages inline (not alert dialogs)
- Disable submit button during loading

**Acceptance:**
- Full email/password register → login flow works end to end
- Battle.net OAuth button navigates to correct Battle.net URL
- Callback page correctly redirects new vs returning users
- Form validation shows inline errors (not browser native validation)
- Loading states prevent double-submission

---

## TASK 5.3 — Onboarding Flow

**File: `frontend/app/onboarding/page.tsx`**

Three-step flow with progress indicator at top (Step 1 of 3, Step 2 of 3, Step 3 of 3).
State persists between steps in React state (not URL params — user can't refresh to a specific step).

**Step 1 — Character Selection:**

If Battle.net connected:
- Show grid of character cards: avatar placeholder (faction icon), name, realm, class, level
- User clicks to select — selected card gets gold border
- "Continue" button enabled after selection

If not Battle.net connected (manual):
- Form with fields: name, realm, region (US/EU dropdown), faction (Horde/Alliance toggle), class (dropdown), race (dropdown filtered by class/faction), level (number input), flying unlocked (expansion checkboxes)
- Submit creates character via API

**Step 2 — Preferences:**

Priority mode selection — four large cards with icon and description:
- 🗺️ **Completionist** — "Get everything. Full coverage, optimized order."
- ⚡ **Points Per Hour** — "Maximum achievement points in minimum time."
- 🏆 **Goal-Driven** — "Pick a meta-achievement and work backwards to it."
- 📅 **Seasonal First** — "Never miss a time-limited achievement."

Session duration slider: 30 min to 8 hours, snaps to 30-minute increments, shows human label ("2 hours", "4.5 hours").

Solo/Group toggle: "Solo only" vs "Include group content" with brief explanation of what each means.

**Step 3 — Sync Progress:**

Shows if Battle.net character selected (skip this step for manual characters — go straight to dashboard).
Animated progress bar that fills as sync runs.
Below bar: "Syncing achievement data... X of ~847 achievements processed"
Polls `/api/characters/{id}/sync/status/{job_id}` every 3 seconds.
On completion: brief success animation, then "Your route is ready" CTA button → navigate to dashboard.

**Acceptance:**
- Can complete onboarding via Battle.net path end to end
- Can complete onboarding via manual character creation
- Priority mode selection visually clear which is selected
- Session duration slider produces valid values at all positions
- Sync polling correctly updates progress bar
- On sync complete, redirect to dashboard happens automatically

---

## TASK 5.4 — Dashboard Page

**File: `frontend/app/dashboard/page.tsx`**

Layout: sidebar navigation (desktop) / bottom tabs (mobile) + main content area.

**Navigation items:**
- Dashboard (home icon)
- My Route (map icon)
- Calendar (calendar icon)
- Browse (search icon)
- Settings (gear icon)

**Seasonal Alert Banner** (conditionally rendered):
- Appears at top if `seasonal_result.active_block` is non-empty
- Red/orange gradient background, warning icon
- Text: "⚠️ {N} seasonal achievements available — {X} days remaining on {event_name}"
- If multiple events: show most urgent one with "and {N} more" link
- Dismissible per browser session (localStorage flag — after dismissing, don't show until next day)
- Full-width, above all other content

**Active Route Card:**
- Shows current session: zone name, estimated time, number of stops remaining
- Mini list of next 3 stops: achievement name, zone, estimated time
- "Continue Route" button → navigates to `/routes/[id]`
- If no active route: "Generate Your First Route" CTA with priority mode description

**Character Stats Card:**
- Character name, faction icon, class
- Circular progress indicator: overall completion percentage
- Points earned / estimated total
- Horizontal bar chart (Recharts) showing completion by expansion — 5 most recent expansions

**Quick Actions:**
- "Regenerate Route" — opens mode selection modal, calls generate endpoint
- "Change Goal" — opens goal search modal (Pro feature, show upgrade prompt on free tier)
- "Switch Character" — character picker dropdown

**Recent Activity Feed:**
- Last 10 completed achievements
- Each entry: achievement name, points, zone, completion timestamp
- "None yet" empty state for new users

**Acceptance:**
- Dashboard renders without errors for a user with active route and achievements
- Seasonal banner appears when active seasonal data exists
- Banner dismisses and stays dismissed for the session
- Stats card shows accurate data
- Recent activity shows real completion data
- Empty states render correctly for new users with no data

---

## TASK 5.5 — Route View — List Mode

**File: `frontend/app/routes/[id]/page.tsx`**

Primary route display. Default view on `/routes/[id]`.

**Page header:**
- Route mode badge, creation date, overall confidence bar
- Toggle between List and Map view
- "Regenerate" button (calls reoptimize endpoint)

**Seasonal block** (if non-empty):
- Rendered above all sessions with distinct styling: amber/orange background, "⏰ Do These First" header
- Each seasonal stop shows days remaining badge (red if critical, orange if high, grey if normal)
- Same stop card as main route but with urgency styling

**Session sections** (collapsible, open by default):
- Session header: "Session 1 · Icecrown · ~2h 15m" with chevron
- Session progress bar (completed stops / total stops in session)
- Stop cards within session

**Stop card** (collapsed state):
- Achievement icon (from Zamimg CDN), name, points badge
- Zone badge, estimated time, confidence tier badge (color-coded)
- Two buttons: ✓ Complete, → Skip
- Expand chevron

**Stop card** (expanded state, clicking anywhere on card):
- All collapsed content plus:
- Numbered steps list — each step has type icon (🗺️ travel, ⚔️ kill, 💬 talk, etc.), description, location in grey
- Community Tips section: folded by default, "💡 X community tips" label → expands to show tip cards
- Each tip card: tip text, score indicator (star rating approximation)
- Confidence tier explanation: "This guide is based on [source] from [date]"
- "View on Wowhead ↗" link

**Complete/Skip interactions:**
- Optimistic UI: immediately visually mark the stop (don't wait for API)
- Fade out completed stops (keep visible but greyed out, or remove — user preference toggle)
- On skip: stop moves to bottom of session with strikethrough
- If newly unblocked achievements returned: show toast "🔓 [Achievement Name] is now available!"

**Blocked Pool** (collapsed section at bottom):
- "X achievements blocked" expandable section
- Each blocked achievement: name, reason badge, unlocker text in grey

**Acceptance:**
- Route renders correctly for a route with 3 sessions and 40 stops
- Expanding a stop shows guide steps and community tips
- Complete button triggers optimistic update and API call
- Skip button moves stop to bottom of session
- Newly unblocked toast appears when completing a prerequisite
- Confidence badges display correct colors
- Steps display correct type icons
- Wowhead links open in new tab

---

## TASK 5.6 — Route View — Map Mode

**File: `frontend/app/routes/[id]/map/page.tsx`** (or tab within route page)

Simple zone-level visualization. Not interactive navigation — orientation only.

**Implementation:**
Use a SVG-based approach with zone regions positioned approximately on a stylized WoW continent map.

Create a static SVG map file for each major continent grouping:
- Eastern Kingdoms + Kalimdor (Classic)
- Outland
- Northrend
- Cataclysm zones
- Pandaria
- Draenor
- Broken Isles
- Zandalar + Kul Tiras
- Shadowlands
- Dragon Isles
- Khaz Algar

Each zone is a clickable SVG region. Color code by route status:
- Gold fill: has stops in current route
- Dim grey: no stops
- Green: all stops completed

**Sequence numbers:**
- Each zone with stops shows a number badge (session-stop position, e.g. "2-3" means session 2, stop 3)
- If multiple stops in zone: show stop count badge

**Sidebar:**
- Continent selector tabs at top
- Clicking a zone region highlights it and shows its stops in sidebar
- Sidebar shows achievement list for selected zone (same collapsed stop card as list mode)

**Mobile:**
- Map view hidden on screens < 768px (show "Map view not available on mobile" message with link to list view)

**Acceptance:**
- Map renders without errors for a route covering 5+ zones
- Clicking a zone highlights it and shows stops in sidebar
- Zone color correctly reflects completion status
- Sequence numbers visible and accurate
- Continent tabs switch map display correctly
- Mobile correctly hides map and shows message

---

## TASK 5.7 — Seasonal Calendar Page

**File: `frontend/app/calendar/page.tsx`**

**Layout:** month grid calendar view + event detail sidebar.

**Calendar grid:**
- Standard month grid, current month default, prev/next month navigation
- WoW events shown as colored horizontal bands spanning their date range
- Each event has a distinct color (consistent across renders — hash event name to color)
- Events that wrap months show correctly

**Event band click → sidebar opens:**
- Event name, date range
- Progress bar: "X of Y achievements complete"
- Achievement list for this event:
  - Green checkmark if completed
  - Gold name if not completed
  - "Generate Seasonal Route" button at bottom

**"Generate Seasonal Route" button:**
- Calls route generation API with seasonal constraint for this event
- Navigates to generated route on success

**Upcoming events list** (below calendar):
- List of next 60 days of events
- Each: event name, opens in X days, achievement count, completion percentage
- Sort by opens_at ascending
- Highlight events opening within 7 days

**Notification preference toggle:**
- "Alert me when seasonal events open" toggle
- Stores preference in user settings (PUT /api/users/me)
- Frontend note: actual email notifications are a future feature — this toggle just stores the preference for later

**Acceptance:**
- Calendar renders current month with correct event bands
- Event bands spanning month boundaries render correctly
- Clicking event opens sidebar with accurate achievement list
- Completion percentage accurate for authenticated user
- Upcoming events list shows correct days-until-open
- Toggle stores preference via API

---

## TASK 5.8 — Achievement Browser Page

**File: `frontend/app/browse/page.tsx`**

Public page — no authentication required. Works for logged-in users too (shows completion status).

**Layout:** filter panel (left sidebar, collapsible on mobile) + achievement grid (main area).

**Filter panel:**
- Expansion multi-select (checkbox list)
- Category multi-select
- Points range slider (0 to 50)
- Toggles: Seasonal only, Solo only, Group content
- "Show completed" toggle (authenticated users only — hidden for guests)
- "Clear all filters" button
- Filters apply immediately (not a submit button) with 300ms debounce

**Search bar:**
- Prominent at top of main area
- 300ms debounce before API call
- Shows "Searching..." indicator
- Clears results when input cleared

**Achievement grid:**
- 3-column grid on desktop, 2 on tablet, 1 on mobile
- Achievement card: icon, name, points badge, category, zone name, confidence tier dot
- For authenticated users: completion checkmark overlay on completed achievements
- Infinite scroll OR pagination — implement pagination (simpler, less edge cases)
- "No results" empty state with suggestion to clear filters

**Achievement detail drawer** (slides in from right, not a new page):
- Full achievement detail: icon, name, description, points, category, expansion, zone
- Guide section: steps list (if guide exists), "No guide available — view on Wowhead" if not
- Community tips: top 3 tips by combined_score
- Confidence tier badge with explanation
- Criteria list (sub-tasks and their descriptions)
- Dependencies: "Requires" and "Required for" sections
- "Add to custom list" button (future feature — show as disabled with tooltip)
- "View on Wowhead ↗" external link
- Close button and ESC key to dismiss

**Acceptance:**
- Browser works without login — no auth errors on page load
- All filter combinations work and update results correctly
- Search returns relevant results with debouncing
- Detail drawer opens correctly and shows all sections
- Drawer closes on ESC and on backdrop click
- Completion overlays show for authenticated users only
- Pagination works correctly

---

## TASK 5.9 — Mobile Responsiveness Pass

**Scope:** audit all pages created in Tasks 5.2-5.8 for mobile usability.

**Breakpoints to test:** 375px (iPhone SE), 390px (iPhone 14), 768px (iPad), 1280px (desktop)

**Navigation:**
- Desktop (≥1024px): sidebar navigation, always visible
- Mobile (<1024px): bottom tab bar with 5 items (Dashboard, Route, Calendar, Browse, Settings icon)
- Tab bar fixed at bottom, above device safe area

**Route List View mobile requirements:**
- Stop cards full width, no horizontal scroll
- Expanded stop card scrollable within card
- Complete/Skip buttons 44px minimum height
- Session headers sticky while scrolling through session
- Map view tab hidden on mobile (<768px)

**Dashboard mobile requirements:**
- Stats card: stack vertically (no side-by-side)
- Expansion chart: horizontal scroll if needed, not truncated
- Recent activity: compact list view

**Achievement browser mobile requirements:**
- Filters: collapsed behind "Filters" button that opens a bottom sheet
- Grid: 1 column on mobile, 2 on tablet
- Detail drawer: full-screen modal on mobile instead of side drawer

**Form pages (login, register, onboarding):**
- Full width inputs, comfortable padding
- Keyboard-aware (no content hidden behind keyboard on iOS)

**Touch targets:**
- All interactive elements minimum 44x44px
- Sufficient spacing between adjacent touch targets (minimum 8px)

**Acceptance:**
- All pages render correctly at 375px with no horizontal overflow
- Navigation works on both desktop and mobile
- Route stop Complete/Skip buttons easily tappable on mobile
- Achievement filter sheet works on mobile
- Detail drawer becomes full-screen modal on mobile
- No content is inaccessible or cut off at any tested breakpoint
