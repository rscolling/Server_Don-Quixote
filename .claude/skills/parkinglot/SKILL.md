---
name: parkinglot
description: Add a new idea to the IDEA_PARKING_LOT.md file. Usage: /parkinglot <idea title or description>
allowed-tools: Read, Edit, Bash
---

# Add Idea to Parking Lot

Add a new idea to `IDEA_PARKING_LOT.md` using the standard template.

## Instructions

1. Read `IDEA_PARKING_LOT.md` to get current state.

2. Parse the user's input from `$ARGUMENTS`. This can be anything from a one-liner to a full description. Extract:
   - **Title** — short name for the idea
   - **Description** — what the idea is (expand from the user's input if brief)

3. Build the new entry using this exact template:

```
### IDEA — [Short title]
**Added:** [today's date, YYYY-MM-DD]
**Source:** Rob
**Status:** Parked

**The idea:**
[One paragraph. What is it? Expand the user's input into a clear description.]

**Why it might be worth doing:**
[Infer from context. If not obvious, write a reasonable placeholder the user can refine.]

**What it would need:**
[Rough sense of effort — team, time, dependencies. Infer from the idea.]

**Open questions:**
[What do we not know yet that matters?]

**BOB notes:**
*(none yet)*
```

4. Insert the new entry into `IDEA_PARKING_LOT.md` at the END of the "Active Parking Lot" section — just BEFORE the `## Idea Template` heading. Include `---` separators to match existing formatting.

5. After inserting, confirm to the user by showing:
   - The idea title
   - The one-paragraph description you wrote
   - A note that it's been added to `IDEA_PARKING_LOT.md` under Active Parking Lot
   - Ask if the user wants to revise anything before considering it done
