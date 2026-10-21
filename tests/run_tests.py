"""Run every tests/test_*.py test inside Blender. Started by `nodes_tools.py test [-k substring]`.

Each test function gets a fresh empty Blender file; library builders are re-imported per test so build-once caches
never point at freed trees. A test passes if it returns without raising; node warnings on objects it evaluated
are reported as failures unless the test sets `allow_warnings = True` on itself.
"""
import importlib, pathlib, sys, time, traceback
REPO = pathlib.Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "procedural-blender-nodes"
sys.path[:0] = [str(SKILL), str(REPO / "tests")]
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
pattern = argv[argv.index("-k") + 1] if "-k" in argv else ""


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name in [m for m in sys.modules if m == "library" or m.startswith("library.") or m == "nodekit.library"]:
        del sys.modules[name]
    import nodekit.graph
    nodekit.graph._ONCE.clear()


results = []
for path in sorted((REPO / "tests").glob("test_*.py")):
    mod_name = path.stem
    for tname in [n for n in dir(importlib.import_module(mod_name)) if n.startswith("test_")]:
        full = f"{mod_name}.{tname}"
        if pattern and pattern not in full:
            continue
        fresh()
        mod = importlib.reload(importlib.import_module(mod_name))
        fn = getattr(mod, tname)
        t0 = time.time()
        try:
            fn()
            warns = [] if getattr(fn, "allow_warnings", False) else [
                f"{o.name}: {w.message}" for o in bpy.data.objects for m in o.modifiers
                if m.type == "NODES" for w in m.node_warnings]
            ok, msg = (not warns), ("; ".join(warns) if warns else "")
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
        results.append((full, ok, time.time() - t0, msg))
        print(f"{'PASS' if ok else 'FAIL'} {full} ({(time.time() - t0) * 1000:.0f} ms){'  ' + msg if msg else ''}")

failed = [r for r in results if not r[1]]
print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
