# QuadView P0: read-only engine observation

This diagnostic build is based on v22 Build 29. It adds opt-in log records around the existing STALKER 2 DX12 viewport Draw and FSceneView constructor. It does not enable QuadView or create an additional view, draw, target, history, or XR submission.

## Run

1. Extract this injector into a separate test folder. Keep Build 3 and the user's working DuoView folder untouched.
2. Enable the Windows environment variable UEVR_QUAD_P0_PROBE with value 1, then restart Steam and the injector so the game inherits it.
3. In STALKER 2 DX12, capture one session with Native Stereo plus Native Stereo Fix enabled, and another with Synchronized Sequential selected.
4. Attach the UEVR log from each session. The probe is rate-limited and records only existing object identities, draw serials, frame counters, stereo pass values, and thread IDs.

The source can be analysed offline with:

    python audit_log.py path-to-UEVR-log.txt --output quad-p0-report.json

The audit reports candidates and warnings only. A four-distinct-pointer candidate does not establish persistent engine ownership, eye pose, a single gameplay tick, shading parity, GPU completion, or XR acceptance.

## Build status

This is a diagnostic prerequisite package, not a playable QuadView implementation. A successful Windows build only confirms that the pinned v22 DuoView plus passive probe compiled. The source probe is applied after the exact Stage234 transformation and byte-verified as reversible; other backend/frontend hashes must remain unchanged.
