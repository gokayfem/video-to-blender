# Gemini Gem

1. Create a Gem and paste `adapters/universal-system-prompt.md` (the part below the line) into its instructions.
2. Add as knowledge files: `references/subject-routing.md`, `references/library-index.md`,
   `references/nodekit-guide.md`, and the `nodekit/*.py` and `library/*.py` files from
   `skills/procedural-blender-nodes/` (rename to `.txt` if needed).
3. Tell the Gem to build groups with nodekit's `Graph` and to instance `NK` library groups by calling their builders
   instead of rewriting them.

For Gemini CLI, install the extension or the skill directly (see the repository README); the CLI reads `SKILL.md`
folders and can run Blender and `scripts/nodes_tools.py` itself.
