# ATG — Idea Parking Lot
### *Future projects, half-formed thoughts, and things worth revisiting*
### *BOB monitors this file. Rob owns it.*

---

> **How this works:** Drop ideas here in any state — rough, half-baked, or fully formed.
> Nothing in this file is a commitment. It's a holding pen.
> BOB reviews it during project planning and flags anything worth activating.
> Rob makes all final calls on what moves from here to `MISSION.md`.

---

## Active Parking Lot

---

### IDEA — Google Play Console integration
**Added:** 2026-03-18
**Source:** Rob
**Status:** Parked — needs build plan

**The idea:**
Connect BOB and the agent teams to the Google Play Console API for Bear Creek Trail. Agents should be able to query download counts, revenue, ratings, crash reports, and review sentiment without Rob manually checking the dashboard. BOB surfaces key metrics in the daily briefing.

**Why it might be worth doing:**
Revenue is the primary success metric. Agents can't optimize what they can't see. Marketing team needs real-time install and revenue data to adjust campaigns. Engineering team needs crash data and ANR rates to prioritize fixes.

**What it would need:**
Google Play Developer API credentials (service account + OAuth). Research team to identify which metrics endpoints to call. Engineering agent to write the integration. BOB webhook tool `get_play_metrics` added to orchestrator.

**Open questions:**
Which Google Play API endpoints expose revenue vs. installs vs. crashes? What are the rate limits? Does the service account need specific IAM permissions?

**BOB notes:**
Build plan needed before Android launch. Priority: HIGH — agents are blind to game performance without this.

---

### IDEA — iOS Apple App Store version (Bear Creek Trail)
**Added:** 2026-03-18
**Source:** Rob
**Status:** Parked — execute after Android launch

**The idea:**
After the Android version of Bear Creek Trail launches and is stable, execute the iOS port and App Store submission. Requires Apple Developer account, Xcode build pipeline, App Store Connect setup, and TestFlight beta before release.

**Why it might be worth doing:**
iOS users typically have higher LTV and spend more on in-app purchases. Expanding to iOS after a successful Android launch roughly doubles the addressable market at incremental cost.

**What it would need:**
Apple Developer account ($99/year). iOS build from the Unity project (likely a separate build target). App Store Connect setup and metadata. TestFlight beta period. App Store review process (typically 1-3 days). App Store Connect API for BOB metrics integration.

**Open questions:**
Is the current Unity project already configured for iOS build target? What changes are needed for iOS-specific UI (safe areas, notch, etc.)? What is Apple's current review timeline for games?

**BOB notes:**
Do not start until Android version is live and revenue-generating. Android launch validates the concept; iOS is the scale play. Build plan will be written when Android is live.

---

## Idea Template

Copy this block for each new idea:

```
### IDEA — [Short title]
**Added:** YYYY-MM-DD
**Source:** Rob / BOB suggestion / Research team / etc.
**Status:** Parked

**The idea:**
[One paragraph. What is it?]

**Why it might be worth doing:**
[Revenue potential, strategic fit, brand alignment, etc.]

**What it would need:**
[Rough sense of effort — team, time, dependencies]

**Open questions:**
[What do we not know yet that matters?]

**BOB notes:**
[BOB appends observations here when relevant research or signals emerge]
```

---

## Archive — Ideas That Were Activated

*When an idea moves to `MISSION.md` as an active project, move the entry here.*

| Idea | Activated | Became |
|---|---|---|
| Mobile phone video game (Bear Creek Trail) | 2026-03-18 | PROJECT-01 in MISSION.md |

---

*This file lives at `/opt/atg-agents/bob-context/IDEA_PARKING_LOT.md`*
*BOB reads this during project planning sessions.*
*Last updated: 2026-03-18*
