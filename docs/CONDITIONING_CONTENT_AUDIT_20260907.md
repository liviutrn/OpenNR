# Renderer-conditioning content and alignment audit

## Decision

The four eight-frame samples pass a pilot-level content and coordinate audit.
Proceed to a small varied 64-frame pilot after configuring it explicitly; this
audit did not change the current eight-frame capture settings or start training.
Exact subpixel correspondence and long-sequence temporal reliability remain
unproven. No further runtime repair is justified by these samples alone.

## Evidence

Source: `C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`.
Sequences: `seq-1788801555035-1`, `seq-1788801563400-2`,
`seq-1788801571220-3`, `seq-1788801582791-4`.

- 32 frames, both eyes, six conditioning stages: 384 conditioning payloads.
- All typed values finite. No spatially constant conditioning payloads.
- Each stage/eye has eight distinct raw SHA-256 hashes in every sequence.
  This excludes bit-identical frozen buffers, not all possible stale-content faults.
- R10G10B10A2 UNORM decoded for albedo and encoded normal/glossiness;
  unsigned R11G11B10 float decoded for masks/specular/reflectance;
  R16 UNORM decoded for masks2. Row pitch and exact payload size are checked.
- Normal decoding follows `package/Shaders/Common/GBuffer.hlsli` including the
  negative normalization convention. Preview roughness is 1 minus glossiness.
- Specular values reach 49.5; values above one are representable in this floating
  format and are not classified as corruption. No NaNs or infinities were found.
- Masks2 is sparse (approximately 76-81 percent zeros per sequence), but varies
  spatially and over time. Sparse masks must not be rejected solely for zeros.

## Coordinate mapping

The native per-eye source is 1664x1792 and its stored center crop starts at
(576,640). The teacher source is 2496x2688 and its stored crop starts at
(992,1088). Thus the teacher's 512-square field maps to approximately 341.33
native pixels per side, starting at (85.33,85.33) inside the stored native crop.
Every mapped field is fully contained. The native crop must be cropped and
resampled using this mapping; directly pairing the two 512-square arrays is wrong.
The previews use a bilinear affine transform based on recorded rectangles.
This does not establish a jitter-correct subpixel training transform.

## Eye and frame evidence

Mean input/albedo edge correlation (96-square luminance-gradient comparison):

| Sequence suffix | Same eye/frame | Previous frame | Next frame | Opposite eye, same frame |
|---|---:|---:|---:|---:|
| 1555035-1 | 0.578 | 0.492 | 0.500 | -0.002 |
| 1563400-2 | 0.630 | 0.561 | 0.553 | -0.029 |
| 1571220-3 | 0.528 | 0.460 | 0.466 | -0.034 |
| 1582791-4 | 0.667 | 0.556 | 0.557 | 0.002 |

These scores favor the matching eye/frame in every sequence on average. They
are a diagnostic comparison, not a calibrated pass threshold or proof that
every frame is temporally exact. Static content and illumination differences
limit sensitivity. The timeline of sequence 2 shows the approaching character
moving coherently across input, albedo, and normals.

Visual inspection finds corresponding stone walls, vegetation, character
silhouettes and clothing after mapping. Eyes appear closed or absent in the
deferred surface view while visible in final color, and hair/lighting coverage
differs. These are localized stage differences consistent with rendering after
the deferred pass; their exact cause was not established. Treat these channels
as partial auxiliary observations, not complete semantic labels or teacher inputs.

## Deliverables and next pilot

Reproducible CPU-only tool: `tools/audit_conditioning_content.py`.
Output: `out/conditioning_content_20260907/index.html`, `audit.json`, and twelve
PNG sheets (aligned first/last frames, eight-frame timelines, six-channel views).
JSON contains per-file hashes, component ranges/std, zero rates, affine mappings,
adjacent changes, and the complete eye/frame comparison scores.

Use three controlled 64-frame clips: NPC/face with modest head movement; outdoor
vegetation with slow pan and a moving actor; indoor lighting with visible material
variation. Validate complete six-channel coverage, resets, continuity, values,
and alignment before expanding collection. Large/high-effect or rapid-motion
coverage can follow once this bounded pilot passes. No MAE benefit is established.
