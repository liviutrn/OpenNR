# Adaptive NR memory-pressure ceiling

The session ending at 12:03 on September 17 had 151 Feature 18 creations
(32.47 seconds cumulatively inside creation), 97 NR changes, and 15 logged VRAM
warning episodes. From 12:00:00 to 12:01:25 crop stayed at 60%, but 23 native
features were created and NR changed 15 times. The previous direction-only
prewarming change did not stop restoration after the 120-frame pressure signal.

The controller now learns a session NR ceiling under memory pressure. It lowers
the ceiling as pressure causes downshifts; good frame timing or a target-FPS edit
cannot erase it. Temporary eligibility loss retains it, while explicit Neural
Rendering Reset (also available through the existing devbench command) or restart
clears it. A legal configured minimum remains respected. Normal workload-driven
reductions may still recover up to this ceiling.

The ceiling gates native feature prewarming and resource retention. Inactive
tiers above it are retired using the existing GPU-idle synchronization path;
the active tier is never freed by this filter. These retirements may themselves
cost time once, but prevent those rejected tiers being repeatedly allocated.
The UI shows the ceiling and exposes the existing Reset button while limited.
Changes emit `[DLSSNR][MEMORY]` records at normal info level.

This is conservative session policy, not a measurement of free VRAM. It does not
automatically probe higher tiers again after a timer expires. With a ceiling below
100%, crop restoration remains gated by the existing true-maximum-NR rule, so crop
may stay reduced as well. Initial creation, ordinary timing-driven tier changes,
and baseline GPU load can still hitch. The fixed-envelope geometry and corrected
valid-rectangle shader are unchanged.

Regression coverage checks persistence through long headroom, target-FPS edits,
eligibility loss, explicit reset, and recovery from workload-only reductions.
The C++ suite passes 2,489 assertions in 180 test cases. Live SkyrimVR/HMD
performance acceptance remains pending; the installed game has no devbench host.
