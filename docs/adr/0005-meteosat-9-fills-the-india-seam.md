---
status: accepted
---

# Meteosat-9 fills the India seam, in MTG-I1's colour, where it sees finer

Around 70°E, Meteosat at 0° and Himawari both view the ground at about 80°
from vertical. Meteosat-9, EUMETSAT's satellite over the Indian Ocean at
45.5°E, views it at 7 to 30°. It joins the Satellite set as the position
`meteosat-iodc`. Its imager, SEVIRI, has two limits the other four lack: its
bands are 3 km where theirs are 0.5 to 1 km, and it has no blue or green
band. So:

- **The Seam goes where two satellites see the ground equally finely**: a
  pixel's footprint grows as 1 / cos of the view angle, and 3 km at nadir is
  as large as 1 km seen at 70.5°. Meteosat-9 takes over only where the
  others look more slantwise than that: about 63 to 75°E at every latitude,
  4% of the Earth. Between the four imagers of equal pixels this is the view
  angle as before.
- **Its blue and green are looked up in a table of MTG-I1's colour**, made by
  `georing-fit-colour` from what Meteosat-9 and MTG-I1 see of the same ground
  at the same time over Africa, Arabia and the western Indian Ocean. Its day
  layer then takes FCI's tone curves, and it meets MTG-I1 at its Seam in one
  colour.
- **Its 1 km HRV band is not used.** It covers part of the disk only, and a
  step in sharpness would run across India where it ends.

## Considered Options

- **Plain view angle, as for the others.** Meteosat-9 would take 23 to 93°E,
  19% of the Earth, and replace MTG-I1's real colour at 0.5 to 1 km over
  East Africa and Arabia with made-up colour at 3 km.
- **A Seam halfway (as if SEVIRI were 2 km).** 53 to 81°E, 8% of the Earth;
  more of the slant view goes, and more of the neighbours' real colour.
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
- A Seam with Meteosat-9 is feathered over 2.5° of its angle, not 5°: its
  angle changes about a seventh as fast across the ground, and 5° would
  feather 900 to 1,300 km.
- The colour table is a file of the Recipe,
  `src/georing/satpy/seviri_colour.npz`. Remaking it needs the Disks of both
  satellites for its Slots; the tool and how it is called are in the notes.
- Meteosat-9 is old, flies an inclined orbit (7° on 2026-11-10) and serves the
  Indian Ocean as EUMETSAT's "best effort contribution". When another
  satellite takes the position, its bands decide whether the table still
  applies.
