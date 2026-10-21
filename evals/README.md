# Evals

Does the `procedural-blender-nodes` skill make Claude's Blender node systems better? This suite measures it with
[`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals). Each case runs with this plugin loaded and
again with no plugin, and the report shows both scores and their difference, `Δ`.

> **Running it costs money.** Every agent run and every judge call is a real model call on your account: billed to
> your API key, or counted against your plan. Validating the files is free; see [Validate](#validate-free).

## Cases

Six positive cases should trigger the skill. Three near-miss negatives sound node- or terrain-adjacent but should
not.

| Case | Kind | The prompt asks for | Case-specific graders |
|---|---|---|---|
| `fence-along-curve` | positive | a wooden fence on any curve: posts, rails, random lean, artist controls | `follows-curve`, `controls-for-artists` (judge) |
| `scatter-terrain` | positive | rocks on steep ground and flowers on flat ground, with density and slope controls | `distributes-on-faces`, `slope-and-density` (judge) |
| `ivy-growth` | positive | ivy creeping over any mesh frame by frame, branching, leaves | `simulation-zone`, `grows-over-surface` (judge) |
| `building-footprint` | positive | a building generator from any closed footprint: floors, ledge, windows, parapet | `footprint-extrude`, `building-controls` (judge) |
| `fix-shared-group` | positive, repair | a fix for a fence whose rail has no thickness. The prompt includes the script, which rebuilds the shared `Round Profile` group from two builders, so the second rebuild unlinks the first user | `build-once` (judge) |
| `port-modifier-inputs` | positive, repair | a port of a Blender 4.2 script that sets modifier inputs as ID properties (`mod["Socket_1"]`, `_use_attribute`, `_attribute_name`), which raises `TypeError` in 5.2 | `uses-properties-inputs`, `attribute-mode` |
| `neg-unity-shadergraph` | negative | a dissolve effect in Unity URP Shader Graph, explained in chat | `noise-node`, `alpha-clip`, `sets-property` |
| `neg-threejs-terrain` | negative | a single-file three.js page with a noise-displaced terrain | `imports-three`, `animation-loop` |
| `neg-matplotlib-terrain` | negative | a 3D surface plot of a noise heightfield with matplotlib | `uses-matplotlib`, `surface-plot`, `saves-figure` |

Both repair fixtures were run in Blender 5.2.2: the shared-group script saves a file whose Rail group has lost every
link to its profile node, and the 4.2 script stops with `TypeError: bpy_struct[key] = val: id properties not
supported for this type` on its first `mod["Socket_1"]` line. Its socket identifiers (`Socket_1` to `Socket_4`) are
the ones 5.2 assigns.

Each positive prompt asks for the build script in `build.py`, which saves `scene.blend` when run with
`blender -b --python build.py`. Every positive case carries these nine graders:

| Grader | Check | Counts toward the score |
|---|---|---|
| `node-tree` | `build.py` builds node trees: `node_groups.new(` or a nodekit `Graph(` | yes, both arms |
| `nodes-modifier` | `build.py` adds a Geometry Nodes modifier: `modifiers.new(…, "NODES")`, `modifier_add(type="NODES")`, `NodesModifier` or nodekit's `holder(` | yes, both arms |
| `input-descriptions` | `build.py` sets descriptions: `.description =` or a `desc=` / `description=` string argument | yes, both arms |
| `no-idprop-inputs` | `build.py` has no `["Socket_N…"]` or `["Input_N…"]` subscript outside `#` comments (the 4.x ID-property access that 5.2 rejects) | yes, both arms |
| `saves-blend` | `build.py` calls `save_as_mainfile(` and names `scene.blend` | yes, both arms |
| `ran-blender` | the agent ran Blender in background mode (`blender … -b` or `--background`) | no: with-plugin indicator (`arm: with-only`) |
| `ran-nodes-tools` | the agent ran `nodes_tools.py check`, `test` or `try`, or `scripts/validate.py` | no: with-plugin indicator (`arm: with-only`) |
| `validate-clean` | the last `validate.py` summary in the transcript was `FAILURES 0` | no: with-plugin indicator (`arm: with-only`) |
| `skill-fired` | Claude invoked the `procedural-blender-nodes` skill | no: excluded automatically, like every `tool_used: Skill` grader |

Each negative case has `skill-not-fired` (`tool_used: Skill`, `min: 0`, `max: 0`, `arm: both`), which counts in both
arms. Its other graders check that the agent did the non-Blender task it was given.

### Why four positive graders do not count toward the score

`ran-nodes-tools`, `validate-clean` and `skill-fired` can never pass without the plugin, because without it the
scripts and the skill don't exist. `ran-blender` could, but whether an agent runs Blender depends as much on the
machine (is Blender installed and visible to the sandbox?) as on the skill, so it is reported, not scored. Counting
these would push the no-plugin score toward zero and inflate `Δ`. So `Δ` on positives comes only from the output
graders (five shared regexes plus the case's own), and the indicators show in the with-plugin runs as the
skill-trigger rate, the run-it rate and the clean-validation rate. Under `--ablation none` all graders count.

### What the regexes cannot see

`claude plugin eval` has no custom-code graders, so no grader runs `build.py`. The regexes catch the API misuse that
breaks 5.2 scripts and the missing pieces of the deliverable in both arms; the `llm` judges read `build.py` for what
a regex cannot (controls named for artists, slope from normals, state carried in a simulation zone, a shared group
built once). Whether the script actually builds and evaluates shows up only in the with-plugin arm, through
`validate-clean`. To get a build rate for both arms, run with `--keep-temp`, then on each kept run:

```bash
blender -b --factory-startup --python <run dir>/build.py
blender -b <run dir>/scene.blend --python skills/procedural-blender-nodes/scripts/validate.py -- --no-cameras
```

## Requirements

- Claude Code v2.1.269 or later (`claude --version`) and git 2.31 or later.
- Credentials: export `ANTHROPIC_API_KEY`, or use the account or cloud-provider variables your normal sessions use.
- Blender 5.2 or later, reachable as `blender` on `PATH` (or the macOS app bundle). Without it, both arms can still
  write `build.py` and every scored grader still applies, but the with-plugin indicators fail.
- Linux: `bubblewrap` and `socat` for the Bash sandbox. On Ubuntu 24.04 and later, bubblewrap also needs the
  AppArmor profile from the [sandboxing docs](https://code.claude.com/docs/en/sandboxing). The CI workflow installs it.

## Validate (free)

```bash
python3 tests/check_evals.py
```

This checks every `prompt.md` and grader against the documented fields and this suite's conventions. It also runs
the grader regexes on real inputs: the two repair fixtures, the skill's templates, a nodekit-style build script,
sample tool commands and traces, and sample answers for the negatives. It reads `validate.py` and `nodes_tools.py`
to confirm the output line and subcommands the indicators look for still exist. It needs neither Blender nor a model
call. CI runs it in `checks.yml`.

## Run

Run from the repository root, which is the plugin root. Put the target `.` first and `--allow-tools` last, since it
takes a list. The cases need `Write` and `Edit` to save their output and `Bash` to run Blender and the skill's
scripts. Without the grant those tools are removed from the session and the positives fail. Granted Bash runs under
the OS sandbox.

Smoke test: one case, one run, no baseline.

```bash
claude plugin eval . --case port-modifier-inputs --runs 1 --ablation none --max-cost-usd 3 --allow-tools Write Edit Bash
```

Positive cases allow up to 50 turns and 25 minutes, because building, running Blender and validating takes several
rounds; expect them to cost several times a shader case. Run one case first and read its cost line before a full
comparison.

Full comparison: 9 cases × 3 runs × 2 arms = 54 agent sessions, plus one judge call per `llm` grader per run (5
positive cases carry one, so 30 judge calls). Set a ceiling you're comfortable with:

```bash
claude plugin eval . --model claude-sonnet-5-5 --judge-model claude-haiku-5-5 --threshold 0.8 --max-cost-usd 60 --allow-tools Write Edit Bash
```

Filters: `--tag positive`, `--tag negative`, `--tag repair`, or `--case 'neg-*'`. The first run in a terminal asks
`Trust this plugin directory?`. Answer `y`, or pass `--trust-plugin`.

Results go to `evals/results/<timestamp>/`: `report.html` plus `aggregate-result.json`. Keep that directory out of
git. When you're signed in with a claude.ai subscription that has artifacts, the report is also published privately
and the command prints a `Published:` link. Pass `--no-publish` to keep it local.

## Reading the result

- **Positives:** `WITH` is the share of output graders passed with the skill, and `W/OUT` is the same without it. A
  positive `Δ` means the skill improved adherence to the 5.2 API and to the deliverable. Open the report to see the
  with-plugin `skill-fired`, `ran-blender`, `ran-nodes-tools` and `validate-clean` indicators per run.
- **Negatives:** `Δ` below 0 means the skill fired, or derailed the task, where it shouldn't have.
- **Exit code:** the default `--threshold` is `1.0`, so the command exits 1 when any case scores below perfect.
  `Δ` never changes the exit code.

## CI

[`.github/workflows/evals.yml`](../.github/workflows/evals.yml) runs the suite on manual dispatch only. Add an
`ANTHROPIC_API_KEY` repository secret, then go to Actions → evals → Run workflow. The inputs set the case glob, runs,
models, threshold and cost ceiling. The job installs Blender 5.2.2 on `PATH`, uploads `eval-results` (report and
JSON) and writes a per-case table to the run summary.

## Adding a case

1. Create `evals/<name>/prompt.md`. Use only the documented frontmatter fields (`description`, `tags`, `runs`,
   `expected_outcome`, `model`, `max_turns`, `timeout_seconds`, `allowed_tools`, `append_system_prompt`, `env`, …).
   Double-quote any value that contains `: ` or ` #`. Write the body the way a user would type it, without naming
   the skill, and name the output file in backticks.
2. Tag the case `positive` or `negative`. Copy the nine shared graders into a positive case unchanged; a negative
   case needs `skill-not-fired.md`. Add graders for the case's own outcome. Prefer regex graders over long files and
   keep `llm` graders for what a regex cannot judge. A repair fixture goes in a ```` ```python ```` block; run it in
   Blender 5.2 to confirm it shows the bug the prompt describes.
3. Run `python3 tests/check_evals.py`, then a smoke run of the new case.

## Troubleshooting

- **`not granted` in the progress output:** add `--allow-tools Write Edit Bash`, after the target.
- **No `W/OUT` column, or "ablation requested but no plugin resolved":** add `plugins: ["../.."]` to the case's
  `prompt.md`.
- **`ran-nodes-tools` passes, but the transcript shows a permission error on `nodes_tools.py`, or Blender cannot
  read its own files:** eval runs make your home directory unreadable to shell commands, so the sandbox may block
  the plugin's scripts, or a Blender installed under your home directory. Copy the repository outside it (for
  example to `/tmp/video-to-blender`), install Blender outside it, and run from there. The CI workflow does both.
- **`ran-blender` fails in every with-plugin run:** Blender is not visible inside the sandbox. Check that
  `blender --version` works in a plain shell, or that the macOS app is in `/Applications`.
- **`validate-clean` fails although validation passed:** the regex reads the whole transcript. If Claude's own text
  after the last clean run quotes an earlier failing summary like `FAILURES 2`, the grader fails.
