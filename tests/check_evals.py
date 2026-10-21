#!/usr/bin/env python3
"""Validate evals/ against the `claude plugin eval` case format without running it (running costs money).

  python3 tests/check_evals.py

Checks every case's prompt.md and graders/*.md against the fields the plugin-evals docs list, enforces this suite's
conventions (positive / negative tags, identical shared graders, a skill-not-fired grader on negatives), and runs the
grader regexes on real inputs: the fixture scripts embedded in the repair prompts, the skill's templates, sample
outputs and tool commands, and the output formats of the skill's scripts (read from their source, so a changed
format fails here). It needs neither Blender nor a model call. Frontmatter is parsed with a small YAML subset
(scalars, quoted strings, flow lists, one level of nested maps), so keep it within that subset.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
SKILL = ROOT / "skills" / "procedural-blender-nodes"
TOOLS = SKILL / "scripts" / "nodes_tools.py"
VALIDATE = SKILL / "scripts" / "validate.py"

# https://code.claude.com/docs/en/plugin-evals#prompt-md-fields and #grader-frontmatter
PROMPT_FIELDS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
                 "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}
GRADER_COMMON = {"type", "weight", "arm"}
GRADER_OPTIONS = {
    "regex": {"pattern", "flags", "match", "target"},
    "tool_used": {"tool", "input_match", "min", "max"},
    "tool_order": {"before", "after"},
    "file_exists": {"path", "exists"},
    "llm": {"criteria", "focus"},
    "baseline": {"baseline_file", "criteria"},
}
TARGETS = {"last_message", "trace", "files", "mock_calls"}
TOOLS_KNOWN = {"Read", "Glob", "Grep", "NotebookRead", "Skill", "AskUserQuestion", "Agent", "TodoWrite", "TaskCreate",
               "TaskGet", "TaskList", "TaskUpdate", "TaskStop", "Bash", "Write", "Edit", "WebFetch", "WebSearch"}
# graders every positive case carries, byte-identical
SHARED_POSITIVE = ["node-tree", "nodes-modifier", "input-descriptions", "no-idprop-inputs", "saves-blend",
                   "ran-blender", "ran-nodes-tools", "validate-clean", "skill-fired"]

errors: list[str] = []


def fail(where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


# ------------------------------------------------------------------------------------------- frontmatter

def scalar(v: str, where: str):
    if v.startswith("'"):
        if len(v) < 2 or not v.endswith("'") or "'" in v[1:-1].replace("''", ""):
            fail(where, f"bad single-quoted string: {v}")
        return v[1:-1].replace("''", "'")
    if v.startswith('"'):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            fail(where, f"bad double-quoted string: {v}")
            return v
    if v.startswith("["):
        if not v.endswith("]"):
            fail(where, f"unterminated flow list: {v}")
        return [scalar(x.strip(), where) for x in v[1:-1].split(",") if x.strip()]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    if v in ("true", "false"):
        return v == "true"
    if ": " in v or " #" in v or v[0] in "{&*!|>%@`":
        fail(where, f"quote this value: {v}")
    return v


def frontmatter(path: Path) -> tuple[dict, str]:
    where = str(path.relative_to(ROOT))
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---(?:\n|$)(.*)", text, re.S)
    if not m:
        fail(where, "missing --- frontmatter ---")
        return {}, text
    data: dict = {}
    nested = None
    for line in m.group(1).split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kv = re.match(r"( *)([A-Za-z_][\w-]*):(?: +(.*))?$", line)
        if not kv:
            fail(where, f"cannot parse line: {line!r}")
            continue
        indent, key, val = kv.groups()
        target = data
        if indent:
            if nested is None:
                fail(where, f"unexpected indent: {line!r}")
                continue
            target = data[nested]
        if key in target:
            fail(where, f"duplicate key {key}")
        if val is None and not indent:
            target[key] = {}
            nested = key
        else:
            target[key] = scalar((val or "").strip(), where)
            if not indent:
                nested = None
    return data, m.group(2)


# ------------------------------------------------------------------------------------------- regexes

def js_regex(pattern: str, flags: str, where: str) -> re.Pattern | None:
    """Compile a grader's JavaScript regex with Python's re, rejecting syntax only one of the two accepts."""
    if re.search(r"\(\?[aiLmsux]+\)|\(\?P|\(\?>|\\[AZz]|[*+?}]\+", pattern):
        fail(where, f"pattern uses syntax JavaScript does not accept: {pattern}")
    if set(flags) - set("dgimsuyv"):
        fail(where, f"unknown JavaScript regex flags: {flags}")
    py_flags = (re.I if "i" in flags else 0) | (re.M if "m" in flags else 0) | (re.S if "s" in flags else 0)
    try:
        return re.compile(pattern, py_flags)
    except re.error as e:
        fail(where, f"pattern does not compile: {e}")
        return None


def grader_regex(case: str, grader: str) -> re.Pattern:
    data, _ = frontmatter(EVALS / case / "graders" / f"{grader}.md")
    key = "input_match" if data["type"] == "tool_used" else "pattern"
    rx = js_regex(data[key], data.get("flags", ""), f"{case}/{grader}")
    assert rx is not None
    return rx


# ------------------------------------------------------------------------------------------- format

def check_target(value, where: str, key: str) -> str | None:
    """Validate a target/focus value; return the workspace path it reads, if any."""
    if isinstance(value, dict):
        if set(value) != {"source", "path"} or value["source"] != "file" or not value["path"]:
            fail(where, f"{key} must be one of {sorted(TARGETS)} or {{source: file, path: <path>}}")
            return None
        return value["path"]
    if value not in TARGETS:
        fail(where, f"{key} {value!r} is not one of {sorted(TARGETS)}")
    return None


def check_grader(path: Path, prompt_body: str) -> None:
    where = str(path.relative_to(ROOT))
    data, body = frontmatter(path)
    gtype = data.get("type")
    if gtype not in GRADER_OPTIONS:
        fail(where, f"type {gtype!r} is not one of {sorted(GRADER_OPTIONS)}")
        return
    for key in set(data) - GRADER_COMMON - GRADER_OPTIONS[gtype]:
        fail(where, f"unknown key {key!r} for a {gtype} grader")
    if "arm" in data and data["arm"] not in ("with-only", "both"):
        fail(where, "arm must be with-only or both")
    if "weight" in data and not (isinstance(data["weight"], (int, float)) and data["weight"] > 0):
        fail(where, "weight must be a positive number")
    if gtype != "llm" and body.strip():
        fail(where, "only llm graders carry a body in this suite; put options in frontmatter")
    file_read = None
    if gtype == "regex":
        if not data.get("pattern"):
            fail(where, "regex grader needs a pattern")
        else:
            js_regex(data["pattern"], data.get("flags", ""), where)
        if "match" in data and not re.fullmatch(r"not_contains|count:\d+", str(data["match"])):
            fail(where, "match must be not_contains or count:N")
        file_read = check_target(data.get("target", "last_message"), where, "target")
    elif gtype == "tool_used":
        if not data.get("tool"):
            fail(where, "tool_used grader needs a tool")
        if "input_match" in data:
            js_regex(data["input_match"], "", where)
        for key in ("min", "max"):
            if key in data and not (isinstance(data[key], int) and data[key] >= 0):
                fail(where, f"{key} must be a non-negative integer")
    elif gtype == "llm":
        if not body.strip() and not data.get("criteria"):
            fail(where, "llm grader needs criteria (the file body)")
        file_read = check_target(data.get("focus", "last_message"), where, "focus")
    elif gtype == "file_exists" and not data.get("path"):
        fail(where, "file_exists grader needs a path")
    if file_read and f"`{file_read}`" not in prompt_body:
        fail(where, f"grades {file_read}, but the prompt never asks for `{file_read}`")


def check_case(case_dir: Path) -> str | None:
    """Validate one case; return its polarity tag."""
    where = str(case_dir.relative_to(ROOT))
    data, body = frontmatter(case_dir / "prompt.md")
    for key in set(data) - PROMPT_FIELDS:
        fail(where, f"unknown prompt.md field {key!r} (unknown keys are an error)")
    if not body.strip():
        fail(where, "prompt body is empty")
    if not 1 <= data.get("max_turns", 10) <= 200:
        fail(where, "max_turns must be 1..200")
    if not 1 <= data.get("timeout_seconds", 300) <= 3600:
        fail(where, "timeout_seconds must be 1..3600")
    if not 1 <= data.get("runs", 3) <= 50:
        fail(where, "runs must be 1..50")
    for tool in data.get("allowed_tools", []):
        if re.sub(r"\(.*\)$", "", tool) not in TOOLS_KNOWN:
            fail(where, f"unknown tool {tool!r} in allowed_tools")
    for key in data.get("env", {}) or {}:
        if not re.fullmatch(r"EVAL_[A-Z0-9_]*", key):
            fail(where, f"env key {key} must match EVAL_[A-Z0-9_]*")
    graders = sorted((case_dir / "graders").glob("*.md"))
    if not graders:
        fail(where, "a case needs at least one grader")
    for g in graders:
        check_grader(g, body)
    polarity = {"positive", "negative"} & set(data.get("tags", []))
    if len(polarity) != 1:
        fail(where, "tag the case with exactly one of positive / negative")
        return None
    return polarity.pop()


def check_suite_policy(positives: list[Path], negatives: list[Path]) -> None:
    for name in SHARED_POSITIVE:
        texts = {}
        for case in positives:
            p = case / "graders" / f"{name}.md"
            if not p.exists():
                fail(str(case.relative_to(ROOT)), f"positive case is missing the shared grader {name}.md")
            else:
                texts[case.name] = p.read_text(encoding="utf-8")
        if len(set(texts.values())) > 1:
            fail("evals", f"shared grader {name}.md differs between positive cases: {sorted(texts)}")
    for case in negatives:
        p = case / "graders" / "skill-not-fired.md"
        if not p.exists():
            fail(str(case.relative_to(ROOT)), "negative case needs graders/skill-not-fired.md")
            continue
        data, _ = frontmatter(p)
        if (data.get("tool"), data.get("min"), data.get("max"), data.get("arm")) != ("Skill", 0, 0, "both"):
            fail(str(p.relative_to(ROOT)), "skill-not-fired needs tool: Skill, min: 0, max: 0, arm: both")


# ------------------------------------------------------------------------------------------- grader self-tests

def fixture(case: str) -> str:
    _, body = frontmatter(EVALS / case / "prompt.md")
    m = re.search(r"```python\n(.*?)```", body, re.S)
    assert m, f"{case}: no ```python fixture in the prompt"
    return m.group(1)


def expect(name: str, rx: re.Pattern, text: str, found: bool) -> None:
    if bool(rx.search(text)) != found:
        fail("self-test", f"{name}: expected {'a match' if found else 'no match'}")


# A build script in the style the skill teaches (nodekit Graph, holder, set_modifier_inputs).
NODEKIT_BUILD = '''import sys, pathlib
sys.path.insert(0, "/plugins/video-to-blender/skills/procedural-blender-nodes")
import bpy
from nodekit.graph import Graph
from nodekit import scene, inspect
OUT = pathlib.Path(__file__).resolve().parent

def build_fence():
    g = Graph("Fence", description="Posts and rails along the curve", modifier=True)
    spacing = g.input("Post Spacing", "FLOAT", 1.5, min=0.2, max=10, panel="Primary", desc="Distance between posts")
    return g.finish()

sc = scene.reset()
path = scene.path_curve("s_bend")
ob, mod = scene.holder("Fence", path, build_fence())
inspect.set_modifier_inputs(mod, {"Post Spacing": 2.0})
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "scene.blend"))
'''

# The port fixture's modifier block, written against the Blender 5.2 API.
PORTED_BLOCK = '''inputs = mod.properties.inputs
inputs.Socket_1.value = 35.0
inputs.Socket_2.type = "ATTRIBUTE"
inputs.Socket_2.attribute_name = "pebble_size"
'''


def self_tests() -> None:
    g = lambda name, case="fence-along-curve": grader_regex(case, name)  # noqa: E731
    tree, modifier, desc, idprop, saves = (g(n) for n in
                                           ("node-tree", "nodes-modifier", "input-descriptions", "no-idprop-inputs",
                                            "saves-blend"))
    shared, port = fixture("fix-shared-group"), fixture("port-modifier-inputs")

    # Both fixtures are complete, runnable build scripts: every output grader but the one each case is about passes.
    for label, text in (("shared-group fixture", shared), ("port fixture", port), ("nodekit build", NODEKIT_BUILD)):
        expect(f"node-tree on the {label}", tree, text, True)
        expect(f"nodes-modifier on the {label}", modifier, text, True)
        expect(f"input-descriptions on the {label}", desc, text, True)
        expect(f"saves-blend on the {label}", saves, text, True)
    expect("no-idprop-inputs on the shared-group fixture", idprop, shared, False)
    expect("no-idprop-inputs on the port fixture", idprop, port, True)
    expect("no-idprop-inputs on the nodekit build", idprop, NODEKIT_BUILD, False)
    for line, found in (('mod["Socket_2"] = 1.0', True), ("mod['Input_3_use_attribute'] = True", True),
                        ('mod[f"Socket_{i}"] = v', True), ('x = 1  # was mod["Socket_2"] = 1.0', False),
                        ("mod.properties.inputs.Socket_2.value = 1.0", False)):
        expect(f"no-idprop-inputs on {line!r}", idprop, "import bpy\n" + line + "\n", found)
    expect("saves-blend without scene.blend", saves, 'bpy.ops.wm.save_as_mainfile(filepath="out.blend")', False)
    expect("saves-blend without saving", saves, 'print("scene.blend")', False)
    expect("node-tree on a script that builds no tree", tree, "import bpy\nbpy.ops.mesh.primitive_cube_add()\n",
           False)

    props, attr = g("uses-properties-inputs", "port-modifier-inputs"), g("attribute-mode", "port-modifier-inputs")
    expect("uses-properties-inputs on the port fixture", props, port, False)
    expect("attribute-mode on the port fixture", attr, port, False)
    expect("uses-properties-inputs on the ported block", props, PORTED_BLOCK, True)
    expect("attribute-mode on the ported block", attr, PORTED_BLOCK, True)
    expect("uses-properties-inputs on a nodekit build", props, NODEKIT_BUILD, True)

    for path in sorted((SKILL / "templates").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        expect(f"node-tree on templates/{path.name}", tree, text, True)
        expect(f"no-idprop-inputs on templates/{path.name}", idprop, text, False)

    sim = g("simulation-zone", "ivy-growth")
    expect("simulation-zone on Graph.zone", sim, 'zin, zout = g.zone("SIMULATION", [("FLOAT", "Age")])', True)
    expect("simulation-zone on raw bpy", sim, 'ng.nodes.new("GeometryNodeSimulationInput")', True)
    expect("simulation-zone on a repeat zone", sim, 'g.zone("REPEAT", [("FLOAT", "Age")])', False)

    # Tool inputs and traces are compact JSON (no spaces after `:` or `,`), as in a real eval trace.
    compact = lambda o: json.dumps(o, separators=(",", ":"))  # noqa: E731
    bash = lambda cmd: compact({"command": cmd, "description": "Run it"})  # noqa: E731
    ran_blender = g("ran-blender")
    for cmd, found in (("blender -b --factory-startup --python build.py", True),
                       ('"/Applications/Blender.app/Contents/MacOS/Blender" -b --python build.py -- --x=-1', True),
                       ('"$BLENDER" --background --python build.py', True),
                       ("blender -b scene.blend --python scripts/validate.py -- --no-cameras", True),
                       ("python3 scripts/nodes_tools.py check", False),
                       ("ls /tmp/video-to-blender -la", False),
                       ("cd /tmp/video-to-blender && grep -b x build.py", False)):
        expect(f"ran-blender on {cmd!r}", ran_blender, bash(cmd), found)

    ran_tools = g("ran-nodes-tools")
    for cmd, found in (("python3 scripts/nodes_tools.py check", True),
                       ('cd /p/skills/procedural-blender-nodes && python3 "scripts/nodes_tools.py" test -k curve', True),
                       ("python3 scripts/nodes_tools.py try -- --module build --root . --png out/try.png", True),
                       ("blender -b scene.blend --python /p/scripts/validate.py", True),
                       ("python3 scripts/nodes_tools.py search fence curve", False),
                       ("python3 scripts/nodes_tools.py index", False)):
        expect(f"ran-nodes-tools on {cmd!r}", ran_tools, bash(cmd), found)
    doc = TOOLS.read_text(encoding="utf-8")
    for sub in ("check", "test", "try"):
        if not re.search(rf"nodes_tools\.py {sub}\b", doc):
            fail("self-test", f"ran-nodes-tools expects `nodes_tools.py {sub}`, which nodes_tools.py no longer documents")

    # validate-clean reads validate.py's summary line; keep the grader in step with the script's print.
    if 'print("FAILURES", len(failures))' not in VALIDATE.read_text(encoding="utf-8"):
        fail("self-test", "validate.py no longer prints `FAILURES <n>`; update validate-clean.md")
    clean_rx = g("validate-clean")
    as_trace = lambda *outs: "\n".join(compact({"type": "tool_result", "content": o}) for o in outs)  # noqa: E731
    ok, bad = "SCENE Scene: Fence 4120 verts 0 warnings\nFAILURES 0\n", "FAILURES 2\n   Fence: node warning\n"
    expect("validate-clean on [clean]", clean_rx, as_trace(ok), True)
    expect("validate-clean on [failing, clean]", clean_rx, as_trace(bad, ok), True)
    expect("validate-clean on [clean, failing]", clean_rx, as_trace(ok, bad), False)
    expect("validate-clean on [failing]", clean_rx, as_trace(bad), False)
    expect("validate-clean on 'FAILURES 10'", clean_rx, as_trace("FAILURES 10"), False)

    skill_rx = g("skill-fired")
    skill = lambda name: compact({"skill": name, "args": "Build the fence"})  # noqa: E731
    expect("skill-fired, namespaced", skill_rx, skill("video-to-blender:procedural-blender-nodes"), True)
    expect("skill-fired, bare", skill_rx, skill("procedural-blender-nodes"), True)
    expect("skill-fired, other skill", skill_rx, skill("video-to-blender:other"), False)

    # Negatives: a plain correct answer passes every task grader.
    mpl = ("import numpy as np\nimport matplotlib.pyplot as plt\nax = plt.figure().add_subplot(projection='3d')\n"
           "ax.plot_surface(X, Y, Z, cmap='terrain')\nplt.savefig('terrain.png', dpi=150)\n")
    for name in ("uses-matplotlib", "surface-plot", "saves-figure"):
        expect(f"{name} on a sample plot script", g(name, "neg-matplotlib-terrain"), mpl, True)
    html = ('<script type="module">\nimport * as THREE from "https://cdn.jsdelivr.net/npm/three@0.170.0/build/'
            'three.module.js";\nrenderer.setAnimationLoop(tick);\n</script>')
    for name in ("imports-three", "animation-loop"):
        expect(f"{name} on a sample page", g(name, "neg-threejs-terrain"), html, True)
    answer = ("Add a Simple Noise node, compare it with Dissolve Amount using a Step node, and feed the result to "
              "Alpha with Alpha Clipping on.\n```csharp\nmaterial.SetFloat(\"_DissolveAmount\", t);\n```")
    for name in ("noise-node", "alpha-clip", "sets-property"):
        expect(f"{name} on a sample answer", g(name, "neg-unity-shadergraph"), answer, True)


def main() -> int:
    cases = sorted(p.parent for p in EVALS.glob("*/prompt.md"))
    polarity = {c: check_case(c) for c in cases}
    positives = [c for c, p in polarity.items() if p == "positive"]
    negatives = [c for c, p in polarity.items() if p == "negative"]
    check_suite_policy(positives, negatives)
    if not errors:
        self_tests()
    for e in errors:
        print(f"ERROR   {e}")
    print(f"{len(cases)} case(s): {len(positives)} positive, {len(negatives)} negative; {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
