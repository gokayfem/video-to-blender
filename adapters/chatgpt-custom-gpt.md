# ChatGPT Custom GPT

1. Create a GPT and paste `adapters/universal-system-prompt.md` (the part below the line) into **Instructions**.
2. Under **Knowledge**, upload:
   - `skills/procedural-blender-nodes/references/subject-routing.md`
   - `skills/procedural-blender-nodes/references/library-index.md`
   - `skills/procedural-blender-nodes/references/nodekit-guide.md`
   - every file in `skills/procedural-blender-nodes/nodekit/` and `skills/procedural-blender-nodes/library/`
     (rename `*.py` to `*.txt` if the uploader rejects them)
   - optionally the templates in `skills/procedural-blender-nodes/templates/`
3. Add this line to the instructions:

> The uploaded `nodekit` files are a graph builder (`Graph`: `input()` with descriptions, ranges and panels,
> `node()`, `group()`, `zone()`, `frame()`, `finish()`) and an inspector (`set_modifier_inputs`, `check_groups`).
> The `library` files are tested `NK` node groups; instance them by calling their builders instead of rewriting
> them. Use `library-index.md` to find groups and `subject-routing.md` to choose techniques. Build scripts put the
> skill folder on `sys.path` and import `nodekit` and `library`.

4. Code Interpreter has no Blender, so the GPT cannot run the scripts. Run them locally with
   `blender -b --factory-startup --python build.py` and paste back any error or node warning.
