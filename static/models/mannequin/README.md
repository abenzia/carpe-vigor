# Carpe Vigor — smooth male and female mannequins

The active body preview uses `male.glb` and `female.glb`: two continuous skin
surfaces with matte monochrome materials. No anatomical muscle, skeleton or organ
asset is used in this view.

## Source and license

MakeHuman graphical assets, CC0 1.0 Universal:
https://github.com/makehumancommunity/makehuman

Pinned source commit: `a8bc2d54ff0ac92e78ff71431b1023eda42bf482`.
The original base mesh and six adult shape targets are retained in `source/`.
The bundled asset license is `LICENSE-CC0.md`. Source and generated-file SHA-256
values are in `manifest.json`.

MakeHuman asset credit: Data Collection AB, Joel Palmius, Jonas Hauquier and the
MakeHuman Community. License clarification:
https://www.makehumancommunity.org/about/license.html

Only graphical assets are used; no MakeHuman application code was copied or run.
No third-party application was installed.

## Adaptations

The reproducible builder is `/scripts/build_mannequins.py` (Python standard
library). It selects the skin and eye surfaces, omits all other helpers, blends
the three source adult shape families equally for each figure, relaxes the arms,
subdivides the quad surfaces once with Catmull–Clark and normalizes reference
height to 1.704 m. The GLBs and our mannequin adaptations are offered under CC0.
They have 54,078 vertices and 108,144 triangles each.

## Side-by-side reference figures

`male-fit.glb` and `female-fit.glb` add a restrained artistic muscle-target blend
(35% and 30% of the corresponding MakeHuman adult maximum-muscle target).
The original target files are included in `source/`, with their CC0 notices.
These graphical targets are by Manuel Bastioni / MakeHuman.

The app's `?body-reference=fit#body` view displays these figures side by side,
with example heights of 178 cm and 168 cm. Each receives uniform scaling only:
no BMI, waist or weight deformation and no eight-week comparison. Source shape
ratios are preserved. These are toned visual references, not a clinical definition
of fitness or a validated reconstruction of a person's anatomy.

The browser offers a male/female figure selector, synchronized rotation, zoom and
editable illustrative measures. A figure change retains the measures and camera
orientation. Both comparison panels use the same selected figure.

## What the comparison means

Height scales the figure. Weight relative to height adjusts generic body volume;
waist circumference adjusts the abdominal profile. These are artistic heuristics,
not a validated anthropometric reconstruction or a personal body scan. Neither
muscle mass nor fat distribution can be inferred from BMI alone.

The right-hand figure uses measurements chosen by the user, not an outcome
predicted from diet, exercise or adherence. Eight weeks is the display horizon.
The preview values stay in page memory and are not uploaded or stored in the
repository. Existing anatomical atlases in `/static/models/anatomy/` are historical
experiments and are no longer rendered by the body view.
