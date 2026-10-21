---
type: regex
target:
  source: file
  path: build.py
pattern: '\bmodifiers\.new\s*\([^)]*["'']NODES["'']|\bmodifier_add\s*\(\s*type\s*=\s*["'']NODES["'']|\bNodesModifier\b|\bholder\s*\('
---
