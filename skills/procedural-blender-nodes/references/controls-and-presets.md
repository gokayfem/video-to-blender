# Controls and Presets

The modifier panel is the product. An artist who never opens the node editor should be able to get every
intended variation from it, and an artist who opens it should find each control wired to something visible.

## Contents

- [What to expose](#what-to-expose)
- [Declaring a good input](#declaring-a-good-input)
- [Panels](#panels)
- [The Primary panel: macro controls](#the-primary-panel-macro-controls)
- [Forwarding part inputs to the top group](#forwarding-part-inputs-to-the-top-group)
- [Naming and collisions](#naming-and-collisions)
- [Structure vs parameters](#structure-vs-parameters)
- [Presets as JSON](#presets-as-json)
- [Proving each control matters: sweeps](#proving-each-control-matters-sweeps)

## What to expose

Expose a control when an artist would plausibly want to change it **and** it changes the result visibly. Keep the
rest as constants in the builder.

| Expose | Keep internal |
|---|---|
| sizes and proportions (width, storeys, sag) | epsilon offsets, z-fighting nudges |
| densities and chances (prop chance, flowers per m²) | derived values (spacing from count and length) |
| style choices (roof style as a Menu, timber pattern) | node-count parameters with one correct value |
| palette colours | normalisation constants |
| motion amounts (wind, walk speed, swing) | integration constants, stance fraction (unless a gait control) |
| seed, input object, time scale/offset, visibility toggles | anything that breaks the graph outside a narrow range |

## Declaring a good input

```python
g.input("Sag", "FLOAT", 0.25, min=0.0, max=2.0, subtype="DISTANCE", panel="Strings",
        desc="How far each string hangs below the straight line between its anchors")
```

- **Description**: what it does in the image, in the artist's words, with the reference value if there is one
  ("1 = the reference's light breeze; 4–6 = a windy day"). Lint fails without one.
- **Range**: `min`/`max` that keep the graph valid. A range the graph cannot survive is a bug: either clamp
  internally or narrow the range. Test both ends.
- **Subtype**: `DISTANCE`, `ANGLE`, `FACTOR` (0..1 slider), `PERCENTAGE`, `TIME`, `TIME_ABSOLUTE`; vectors `XYZ`,
  `TRANSLATION`, `EULER`, `DIRECTION`. Units then show correctly.
- **Type**: INT for counts and storeys, BOOL for toggles, MENU (fed into a Menu Switch) for named styles, COLOR for
  palette, OBJECT/COLLECTION for inputs, never a FLOAT that is rounded internally.
- **Seed**: one `Seed` INT per top group; internal decisions use `Seed + k` with a distinct `k` per decision.

## Panels

Group inputs into panels named for what an artist thinks about: `Street`, `Houses`, `Windows`, `Palette`, `Wind`,
`Visibility`. Declaration order is display order. Collapse detail panels by default
(`g._panels[name].default_closed = True`).

## The Primary panel: macro controls

A large generator has hundreds of detailed controls (storybook street: about 180). Put a **Primary** panel first
with 6–10 macro controls, each of which scales several detailed ones. The detailed controls stay available and
are combined with the macro:

```python
PRIMARY = [
    # name, type, default, min, max, description, [(part, detailed input, op)]
    ("Prop Amount", "FLOAT", 1.0, 0.0, 2.0, "Scales every prop chance",
     [("Props", "Window Box Chance", "MULTIPLY"), ("Props", "Awning Chance", "MULTIPLY")]),
    ("Extra Storeys", "INT", 0, -2, 4, "Taller or lower houses",
     [("Houses", "Storeys Min", "ADD"), ("Houses", "Storeys Max", "ADD")]),
    ("Festivity", "FLOAT", 1.0, 0.2, 3.0, "More bunting strings",
     [("Bunting", "String Spacing", "DIVIDE")]),
]
# when forwarding a detailed input that is a macro target:
src = g.math(op, detailed_input_socket, macro_socket, label=f"{name} {op.lower()} {macro}")
```

- Neutral macro values (1 for MULTIPLY/DIVIDE, 0 for ADD) reproduce the defaults exactly, so the reference look is
  the macro defaults.
- A macro must change the image visibly at both ends of its range (prove with a sweep).
- Put the input object (`Path`), `Seed` and the one or two most important direct controls (`Walk Speed`) in Primary
  too.

## Forwarding part inputs to the top group

Each part is a group usable alone; the top group instances every part and forwards its inputs to the modifier.
Pattern (from `prompts/storybook-street/street/groups/assembly.py`):

```python
for it in part_tree.interface.items_tree:
    if it.item_type != "SOCKET" or it.in_out != "INPUT":
        continue
    sock = next(s for s in node.b.inputs if s.identifier == it.identifier)
    if it.name == "Curve":   g.connect(path_geometry, sock)       # shared wiring
    elif it.name == "Time":  g.connect(time, sock)
    elif it.name in shared:  g.connect(shared[it.name], sock)     # Seed, Street Width, ...
    else:                                                          # forward with the same spec
        panel = f"{label} > {it.parent.name}" if it.parent and it.parent.name else label
        src = g.input(name, stype, it.default_value, min=it.min_value, max=it.max_value,
                      subtype=it.subtype, desc=it.description, panel=panel)
        g.connect(src, sock)
```

- Forwarded panels are `"<Part> > <Panel>"`, so the modifier reads like the part structure.
- Shared inputs (one `Seed`, one `Street Width`) are declared once on the top group and wired to every part that
  has an input with that exact name. Agree the shared names before building parts.
- Forward the description, range and subtype; drop subtype `NONE`.
- Geometry inputs between parts (`Anchors`) are wired, not exposed.

## Naming and collisions

- Names must be unique on one group interface. When two parts both have `Color`, forward as `"<Part> Color"`, or
  better, make the part names unambiguous at the source (`Awning Color`, `Shutter Color`): presets and sweeps
  address controls by name.
- Names are API: renaming a control breaks presets, sweeps, drivers and docs. Rename deliberately and update them.
- Groups: library `NK <Name>`, project groups with a project prefix (`SS <Name>`), sub-groups `<Prefix> <Name>
  <Part>`. Materials the same.

## Structure vs parameters

| Kind | What | Where it changes | Reviewed as |
|---|---|---|---|
| **Structure** | which parts exist, how they connect, which inputs exist | Python builders only | code + regenerated `GRAPH.md` |
| **Parameters** | default values, ranges, presets, light, camera | builder defaults, `presets/*.json`, `light.json`, build script | value diffs |

Fitting to a reference (exposure, sun, densities, sizes) touches **parameters only**, so it can never break reuse
on other inputs. If matching a reference seems to need a structural special case ("house 7 is taller"), it is a
parameter distribution instead (a storeys range and a chance), or it is not reproduced.

## Presets as JSON

A preset is a flat `{control name: value}` over the top group's inputs. Colours are linear RGBA lists.

```json
{ "Festivity": 2.4, "Wind": 4.0, "Flower Amount": 2.2, "Seed": 3 }
```

```python
inspect.set_modifier_inputs(mod, json.loads(pathlib.Path("presets/festival.json").read_text()))
```

- `{}` is the reference preset: the defaults are the reference.
- Presets touch mostly Primary controls; a preset that needs 30 detailed values means a macro is missing.
- Render presets with `scripts/render.py --preset <path or name> --set "Seed=7"`. Validate every preset
  (`validate.py` after applying, or a build per preset) for warnings and camera clearance.
- Store presets next to the build script (`presets/`), one file each, numbered for the gallery order.

## Proving each control matters: sweeps

A control that does nothing visible, or only breaks things, should not be exposed.

```bash
blender -b my_effect.blend --python scripts/sweep.py -- --control "Timber Amount" \
    --values 0,1.7 --frames 48 --at 169 --out out/sweep/timber_
```

- Sweep every Primary control over its full range at a frame where its effect is visible; look at the first and
  last frames side by side, and play the sweep for discontinuities (sudden jumps mean a hard threshold that should
  be a smooth chance or a hashed per-piece threshold).
- Smooth sweeps: per-piece decisions compare a hashed `nk_rand` against the control (`rand < chance`), so raising
  the chance adds pieces one at a time instead of reshuffling all of them. Keep layout seeds independent of chance
  controls, so changing a chance never moves unrelated pieces.
- Spot-check detailed controls by group: each panel's controls at min and max on a small test render.
- Record sweeps in the deliverable (a start/end contact sheet per control).
