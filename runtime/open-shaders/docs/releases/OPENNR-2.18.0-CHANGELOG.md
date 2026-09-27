# OpenNR 2.18.0

- Promotes the 2.17.0 VR performance defaults after a local Skyrim VR session
  in which the user reported better performance and no visible problems.
- Keeps the 2.16.0 Open Shaders upstream refresh and the per-eye Streamline
  camera reprojection fix from Open Shaders PR #756.
- Prevents startup failure on Skyrim VR Address Library ID 100979. The legacy
  shadow viewport adapter is skipped on VR because that ID is absent from the
  installed VR address tables. Other verified compatibility adapters remain.
- Retains fresh VR defaults for lower-cost AO, incremental Skylighting updates,
  and hardware-gated variable-rate shading. Existing saved settings remain
  user-controlled.
- Retains native Feature 18 depth and motion vectors, per-eye state, and
  temporal history guards. NR and DLSS quality defaults are unchanged.

The local test is evidence of startup and playable HMD behavior, not a
controlled frame-time gain. The skipped shadow viewport and FullScreenBlur
adapters remain compatibility follow-ups. The earlier 2.17.0 changelog is in
`docs/OPENNR-2.17.0-CHANGELOG.md` in the source repository.
