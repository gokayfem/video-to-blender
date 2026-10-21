# Claude (claude.ai Projects)

Prefer the skill: zip the `skills/procedural-blender-nodes/` folder and upload it under **Settings > Capabilities >
Skills**. Claude then loads `SKILL.md`, the references, nodekit and the library on demand. Its code environment has
no Blender, so Claude writes the build script there and you run it locally with
`blender -b --factory-startup --python build.py`.

Without skills, use a Project:

1. Paste `adapters/universal-system-prompt.md` (the part below the line) into the project instructions.
2. Add to project knowledge: `references/subject-routing.md`, `references/library-index.md`,
   `references/nodekit-guide.md`, the `nodekit/*.py` files and the `library/*.py` files.
3. Add: "Build groups with nodekit's `Graph` and instance the `NK` library groups by calling their builders instead
   of rewriting them. Put the skill folder on `sys.path` at the top of the build script."

For Claude Code, install the plugin or copy the skill folder (see the repository README). Claude Code can run
Blender and the skill's checker itself.
