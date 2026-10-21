---
type: regex
target:
  source: file
  path: build.py
pattern: '\bGeometryNode(?:CurveToPoints|ResampleCurve|SampleCurve|CurveToMesh)\b|["'']NK Curve[^"'']*["'']|\bcurve_frame\s*\('
---
