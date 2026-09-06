# Strict temporal capture workflow — OpenNR 0.5.5+

The earlier 27 clips are structurally excellent but all start with
`history_reset: [false, false]`. The menu sequence was too indirect: it starts or
stops recording, but it does not itself guarantee that the next Feature 18 dispatch
is the first dispatch after a temporal reset.

The local capture implementation now requests the reset when a new capture sequence
starts. The request is consumed by the render-thread neural-rendering integration,
before the first eligible capture frame. The sequence manifest records
`history_reset_policy: "request_on_sequence_start"` so the control path is explicit.

Use this workflow after installing the rebuilt **local OpenNR** DLL. The active
capture profile is isolated at
`E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906`; the previous settings file is
backed up at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-strict-output-20260906_003846`.
The active profile remains a 64-frame crop burst with both eyes, native depth,
native motion vectors, and queue capacity 64.

1. Enable OpenNR Capture and load the crop-temporal profile. Leave the settings menu
   open only long enough to confirm the output directory and `burst_frames` value.
2. Close the menu and return to a stable rendered scene. Do not press the start/stop
   key first.
3. Press the configured burst key once while no capture sequence is active. This
   starts a new sequence, requests the reset, and arms the configured finite burst.
4. Do not press any capture key during the burst. Wait for the configured number of
   records and for the writer queue to drain before exiting or starting another clip.
5. Validate the new sequence immediately. The strict gate requires all of the
   following: first `history_reset` is `[true, true]`, every frame is complete,
   frame/sample/host increments are exactly one, and there are no drops,
   backpressure events, or mid-clip resets.

The same reset-on-start behavior also applies to the start/stop key and the
`start`/`single` feature actions when they create a new sequence. For strict
temporal data, the direct burst path is preferred because it combines sequence
creation and the finite burst in one user action. If the first record is still
`[false, false]`, keep the clip as valid steady-state continuity data but do not
promote it through the strict temporal gate; check the log to verify that the new
DLL was actually loaded.

The rebuilt capture-enabled Dev-Fast DLL is now installed in the active OpenNR
profile. The installed file is v0.5.5.0, 43,745,792 bytes, SHA-256
`751401C26DF6B9FCD7F6F3DD906EE6D57ED69D6F3C6EE6305D1C445C49E3FFD4`, and the
installed `OpenNRCapture.ini` matches the staged package. The pre-install DLL and
INI are preserved at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-capture-reset-0.5.5-20260906_002040`.
The exact source/staging/active hashes and scope are recorded in
`out\active_install_capture_reset_0.5.5_20260906\install_manifest.json`.
Existing captures and the trained student remain untouched.
