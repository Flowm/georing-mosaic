---
status: accepted
---

# Meteosat-9 fills the India seam, in MTG-I1's colour, where it sees most steeply

Around 70°E, Meteosat at 0° and Himawari both view the ground at about 80°
from vertical. Meteosat-9, EUMETSAT's satellite over the Indian Ocean at
45.5°E, views it at 7 to 30°. It joins the Satellite set as the position
`meteosat-iodc`. Its imager, SEVIRI, has two limits the other four lack: its
bands are 3 km where theirs are 0.5 to 1 km, and it has no blue or green
band. So:

- **Each pixel comes from the satellite that sees it most steeply**, as for
  the others: by the view angle alone, worked out from where the satellite
  actually was and from its grid (the larger of the two), feathered over 5°
  at every Seam. Meteosat-9 takes 23 to 93°E, 19% of the Earth. Its Seams lie
  halfway to MTG-I1 and to Himawari, where both see the ground at the same
  angle, under 45° near the equator: neither shows its limb there, and a sun
  glint, which lies halfway between the sun and each satellite, is matched
  on both sides.
- **Its blue and green are looked up in a table of its neighbours' colour**,
  made by `georing-fit-colour` from what Meteosat-9 and MTG-I1 see of the
  same ground at the same time over Africa, Arabia and the western Indian
  Ocean, and, since 2026-11-19, from Himawari's land over South Asia. Its
  day layer then takes FCI's tone curves, and it meets MTG-I1 at its Seam in
  one colour.
- **Its 1 km HRV band is not used.** It covers part of the disk only, and a
  step in sharpness would run across India where it ends.

## Considered Options

- **The Seam where two satellites see the ground equally finely.** A pixel's
  footprint grows as 1 / cos of the view angle, and 3 km straight down is as
  large as 1 km seen at 70.5°: Meteosat-9 would take only 63 to 75°E, 4% of
  the Earth, and keep MTG-I1's real colour at 0.5 to 1 km over East Africa
  and Arabia. It ran from 2026-11-14 to 2026-11-18. It kept MTG-I1 and
  Himawari out to about 70° from vertical: at dawn the low sun burnt MTG-I1's
  limb white down the Indian Ocean (02:00 and 03:00 on 2026-11-17: a stripe,
  a band of glint along 56–65°E, a white Madagascar), at dusk it hazed it over
  East Africa (14:00), and Himawari's hazy limb met Meteosat-9's clear view
  in a hard edge near 75°E. Measured along every Seam as the colour
  difference between the two neighbours' own Renderings at the same ground,
  it was 22.3, 24.0 and 22.6 levels at 02:00, 03:00 and 14:00 on 2026-11-17;
  by the view angle alone 19.5, 21.4 and 18.1, the Himawari and Meteosat-9
  Seam 52–58 against 29–31.
- **The same, with a glare penalty**: a satellite's angle counted up to 40°
  larger where it looked slantwise into a low sun's reflection (a glint
  angle under 60–30°, sun zenith and view angle together over 130–136°, the
  sun not yet set). It took the dawn limb away, but the penalty rose from
  nothing to 40° over a short distance and drew hard lines (the GOES-East and
  MTG-I1 Seam over the Atlantic at 18:00 on 2026-11-17), it left the dusk
  haze and Himawari's edge alone, and it was three more numbers to tune.
- **A Seam halfway (as if SEVIRI were 2 km).** 53 to 81°E, 8% of the Earth;
  still a view of 55–60° at each of Meteosat-9's Seams.
- **A fixed number of degrees added to Meteosat-9's view angle.** Its view
  angle and the others' change at different rates across the ground, so no
  one offset puts the Seam in the same place at every latitude; near its
  sub-satellite point it took the wrong region.
- **Colour fitted to CIRA's Meteosat-9 GeoColor.** SLIDER keeps it at 3 km.
  It matches CIRA more closely but nothing ties it to MTG-I1's colour at the
  Seam, and CIRA's Meteosat-9 sea is grey where its MTG-I1 sea is blue.
- **A cubic polynomial instead of the table.** Within 0.5% reflectance of the
  table overall, but it turned dense forest teal and lush crops red, where
  few pixels taught it: a polynomial bends between its data, the table holds
  each bin's median.
- **Natural colour (red, 0.8 and 1.6 µm).** No made-up bands, but land green
  and ice cyan: a different look at both of its Seams.
- **Leave the gap.** Quality around 70°E stays that of an 80° view.

## Consequences

- One Disk more per Slot: 260 MB from the Data Store with the same EUMETSAT
  key, and a render of 5 s and 1.5 GB.
- East Africa, Arabia and India are in Meteosat-9's colour looked up from
  MTG-I1's, at 3 km, where MTG-I1 saw them in real colour at 0.5 to 1 km.
  Sharpness steps down at its Seams.
- The join has no satellite-specific numbers: the view angle, one Seam width
  and the limb.
- The colour table is a file of the Recipe,
  `src/georing/satpy/seviri_colour.npz`. Remaking it needs the Disks of both
  satellites for its Slots; the tool and how it is called are in the notes.
- Meteosat-9 is old, flies an inclined orbit (7° on 2026-11-10) and serves the
  Indian Ocean as EUMETSAT's "best effort contribution". When another
  satellite takes the position, its bands decide whether the table still
  applies.
