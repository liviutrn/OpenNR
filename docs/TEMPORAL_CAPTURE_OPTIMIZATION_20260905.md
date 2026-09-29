# Temporal capture optimization — 2026-09-05

The first live full-resolution temporal stress run used the prepared 0.5.3
OpenNR build with both eyes, two 512 crops, all guides, and a complete
full-frame master for every sample. It finished cleanly with 120 complete
records, but it is not a temporal-training clip.

## Observed bottleneck

The sequence is:

```text
C:\OpenNR_Captures_Temporal_20260905\seq-1788638984693-1
```

The byte validator found 120/120 complete records, 2,880/2,880 required
artifacts, no missing files, no dropped frames, and no failed records. The
sequence grew to approximately 24.8 GiB. Each frame contained 24 artifacts;
the full-frame portion was about 195 MiB per frame and the crop portion about
20 MiB per frame. Queue backpressure reached 87 events, and host-frame gaps
after the first 32 adjacent pairs ranged from 37 to 96 render frames. The
temporal master gate therefore rejects it. The first record also did not carry
the required `[true, true]` history reset.

This is a capture-throughput failure, not a missing-data or key-mapping
failure. Full-resolution GPU readback, raw writes, and color preview PNG
encoding dominate the queue. Increasing the queue would only postpone the
gaps and increase memory use.

## Capture roles going forward

Use two separate recordings:

1. **Temporal crop clips** use complete 512x512 input, teacher, depth, and
   exact Feature 18 motion resources for both eyes on every committed frame.
   They omit per-frame full-resolution artifacts, use one crop per frame, and
   are checked with:

   ```powershell
   python tools\validate_temporal_capture.py `
     C:\OpenNR_Captures_Temporal_Crops_20260905 `
     --mode crop `
     --output out\temporal_audit_crop_20260905.json
   ```

   This mode is intended for contiguous temporal training. It does not prove
   full-frame coverage; the spatial full-resolution masters remain a separate
   validation source.

2. **Full-resolution masters** remain short, low-rate or single-frame
   validation captures. They use `capture_full_frame_sequence=true` and the
   normal master validator. They must not be used as temporal clips when
   queue pressure creates host-frame gaps.

The prepared crop-mode template is
`config/opennr_capture_temporal_crop.example.json`. It requests 90 FPS,
one 512 crop, both eyes, all native guides, a 64-frame first burst, and a new
output directory outside MO2 overwrite/Root. The live profile will use this
configuration after the stress-run settings are backed up.

## Crop-mode evidence from the first live pass

The crop directory now contains 37 sequence directories and 1,936 complete
records. The required raw files and color PNG previews are present for every
complete record, and raw byte sizes match their recorded row pitch and height.
This is useful spatial/teacher evidence, but it is not a clean temporal set:
the 64-frame runs typically have only 25--55 adjacent host-frame transitions,
then gaps of 3--6 frames as the writer falls behind. The newest partial run
was still growing during inspection and must be treated as an incomplete tail.

Do not delete the directory. A later packager can retain contiguous prefixes as
spatial or short temporal candidates, while excluding one-sample probes and
any frames after the first host-frame gap for strict temporal training.

The next capture build adds `write_color_previews`. When false, sampled crop
frames keep the exact typed raw input, teacher, depth, and motion-vector
tensors but skip the four per-frame color PNG conversions/writes. Full-frame
validation artifacts continue to write their normal previews. This is a
throughput optimization only; it does not replace native Feature 18 guides or
repair host-frame gaps already present in the old captures.

## Interpretation boundary

The existing full-resolution stress sequence is preserved as diagnostic and
spatial-master evidence. Its complete artifacts are not repaired or inferred
into a temporal clip. A crop-mode sequence is temporal-ready only if the crop
gate reports consecutive frame/sample/host counters, the initial reset is
present, no mid-clip reset or drop occurs, and all required crop artifacts are
complete for both eyes.
