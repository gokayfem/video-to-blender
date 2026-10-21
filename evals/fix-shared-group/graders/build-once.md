---
type: llm
focus:
  source: file
  path: build.py
---

The original script called build_profile() from both build_rail() and build_posts(). build_profile() clears and rebuilds the shared "Round Profile" node group each time, which removes its interface sockets and so drops every link to the group node already placed in the Rail group. The rail then sweeps without a profile.

PASS if all hold:
- "Round Profile" is built once and the same tree is used by both the Rail and the Posts groups (for example cached, built when missing and reused, or built once and passed to both builders), or rebuilding no longer clears the interface of a group already in use.
- The Rail group's profile node is linked to its Radius input and to the Curve to Mesh profile after the script runs.
- The group names and their inputs (Rail: Curve, Height, Radius; Posts: Curve, Spacing, Height, Radius) are unchanged.

FAIL if the fix duplicates the profile into two separately named groups, re-adds links by hand after the second rebuild while still rebuilding in place, or removes the shared group.
