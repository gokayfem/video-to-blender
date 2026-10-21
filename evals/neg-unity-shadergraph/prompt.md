---
description: "Near miss: a node-graph dissolve effect, but in Unity Shader Graph."
tags: [negative]
expected_outcome: "The answer explains a URP Shader Graph dissolve (noise, step or alpha clip threshold, an emissive edge) in Unity terms; the Blender skill does not fire."
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I'm in Unity 6 with URP. How do I build a dissolve effect in Shader Graph where the mesh burns away along a noise pattern with a glowing orange edge, driven by a single Dissolve Amount property I can animate from a script? Walk me through the nodes and how to wire them, and show the C# line that sets the property.
