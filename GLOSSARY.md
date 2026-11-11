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
Meteosat at 0° and Himawari. A position, not a spacecraft: the satellite
serving it can change.
_Avoid_: Constellation, ring

**Disk**:
One satellite's full-disk scan that starts at a Slot.
_Avoid_: Scene, scan, granule, image

### Products

**Recipe**:
The rule that turns a Disk's bands into colour: true colour by day, infrared
clouds over city lights by night, blended across the terminator. One Recipe
serves every satellite.
_Avoid_: Composite (satpy's word for its band recipes: say "satpy composite"
when that is meant), GeoColor

**Rendering**:
A Disk turned into a colour image by the Recipe, in that satellite's own view
and at its native resolution.
_Avoid_: Composite, RGB, disk image

**Mosaic**:
The Renderings of one Slot joined on one global grid.
_Avoid_: Composite, blend, ring image

**Seam**:
The line in a Mosaic where two Renderings meet, placed where both satellites
view the ground at the same angle.
_Avoid_: Border, overlap, cut line

### Reference

**GeoColor**:
The products of that name from CIRA and EUMETSAT, which the Recipe is tuned
toward. Never the name of anything produced here.

**Comparison scene**:
A fixed place and time at which a Rendering is judged against GeoColor.
_Avoid_: Test image, sample
