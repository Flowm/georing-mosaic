# Georing Mosaic

Hourly colour imagery of the whole Earth, built from the raw scans of the
geostationary weather satellites. It exists because the published ring products
either look worse than GeoColor or leave out the newest satellites.

## Language

### Time and inputs

**Slot**:
The nominal time a Mosaic is for. Always a full clock hour in UTC.
_Avoid_: Timestep, frame, cycle

**Satellite set**:
The geostationary positions that contribute Disks: GOES-East, GOES-West,
Meteosat at 0°, Meteosat over the Indian Ocean and Himawari. A position, not
a spacecraft: the satellite serving it can change.
_Avoid_: Constellation, ring

**Disk**:
One satellite's full-disk scan that starts at a Slot.
_Avoid_: Scene, scan, granule, image

### Products

**Recipe**:
The rule that turns a Disk's bands into colour: true colour by day, infrared
clouds over city lights by night, blended across the terminator. One Recipe
serves every satellite; for Meteosat-9, which has no blue or green band, it
looks the day colour up in a table of MTG-I1's.
_Avoid_: Composite (satpy's word for its band recipes: say "satpy composite"
when that is meant), GeoColor

**Rendering**:
A Disk turned into a colour image by the Recipe, in that satellite's own view
and at its native resolution. It is a working file: only the Mosaic is
published.
_Avoid_: Composite, RGB, disk image

**Mosaic**:
The Renderings of one Slot joined on one global grid.
_Avoid_: Composite, blend, ring image

**Seam**:
The line in a Mosaic where two Renderings meet, placed where both satellites
see the ground equally finely: where they view it at the same angle, for
satellites whose pixels are the same size.
_Avoid_: Border, overlap, cut line

### Reference

**GeoColor**:
CIRA's product of that name, which the Recipe is tuned toward. EUMETSAT's
product of the same name for Meteosat is satpy's `geo_color` composite and is
not a reference. Never the name of anything produced here.

**Comparison scene**:
A fixed place and time at which a Rendering is judged against GeoColor. There
are twenty-eight in two sets. The twenty-one of the **tuning set**
(2026-11-10, and four from 15 to 19 November for a low sun and the limbs) are
what the Recipe is fitted to and looked at. The seven of the **holdout set**
(2026-09-14 and 2026-11-14, and 2026-10-01 for Meteosat-9; other places) are
only measured, never tuned against: they tell whether a change holds where it
was not made.
_Avoid_: Test image, sample
