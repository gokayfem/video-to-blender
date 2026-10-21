---
type: regex
target:
  source: file
  path: build.py
pattern: '(?:^|\n)(?:(?!#)[^\n])*?\[\s*f?["''](?:Socket|Input)_[\d{]'
match: not_contains
---
