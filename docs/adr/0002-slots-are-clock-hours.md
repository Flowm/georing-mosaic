---
status: accepted
---

# Slots are clock hours

Every satellite in the set scans the full disk each 10 minutes, but a Slot is a
full clock hour and uses the scan that starts on that hour. The reason is
EUMETSAT's data policy (as amended 25 November 2025): the hourly Meteosat scans
are CC-BY and may be shown publicly in real time, while the other scans may not
be shown publicly until they are an hour old without a paid licence. Hourly is
the only cadence at which all four satellites are both free and current.

## Consequences

- A finer cadence means showing Meteosat an hour late, or paying the licence
  (the fee table reads EUR 4,000 to 8,000 per year).
- This rests on our reading of the policy, including that the hourly scan
  "referenced to" the clock hour is the one starting on it. Confirm both with
  EUMETSAT before the product is public.
