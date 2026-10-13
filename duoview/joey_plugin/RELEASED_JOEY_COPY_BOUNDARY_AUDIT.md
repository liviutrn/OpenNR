# Released Joey copy-boundary correction and evidence

Backend SHA-256: `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.

The Build49 handoff incorrectly identified `0x1c4280` as D3D12 OpenXR copy. It is the **D3D11** implementation: it calls the immediate context's CopyResource/CopySubresourceRegion methods at vtable offsets 0x178/0x170 and accepts a different callback signature. The error came from a shared diagnostic string referenced by both implementations. Do not hook that address with the D3D12 signature.

The actual released **D3D12** `OpenXR::copy` is RVA **`0x1e4770`**, unwind end `0x1e5ac2`. Both functions reference the same marker `[VR] OpenXR: Frame not begun when trying to copy.` at RVA `0xbae4f8`; DX12 references it at `0x1e490f`. The DX12 copy is called from the known `D3D12Component::on_frame` RVA `0x1f0f50`, including callsite `0x1f83f5`.

Exact entry bytes: `4c894c24204c894424188954241048894c240855535657415441554156415748`.

Binary argument/layout evidence correlates with the public embedded-commit source `5ac7edc207866569334175e4ed8a7517971547f6`:

- `this+0x170` is its mutex, distinct from DX11's `this+0x168`.
- Pre/additional/post optional std::function objects check their engaged byte at `+0x40`.
- With this prologue, stack argument offsets are: source `rbp+0x100`, extra callback `+0x110`, source state `+0x118`, source box `+0x120`, post callback `+0x128`, retained Mono resource `+0x130`, retained PairFrame shared_ptr `+0x138`. Pre callback arrives in R9.
- Pre callback receives the actual acquired destination and CommandContext at texture-context `+8`.
- Source state is passed as R9D to CommandContext::copy at `0x1e53a6`.
- CommandContext::execute is called at `0x1e54ef`, target `0x3b8090`.
- Binary field accesses match the exact header's command context layout: command-list offset 16, fence-value offset 32, mutex offset 48, waiting/has_commands/poisoned offsets 128/129/130. Since CommandContext begins at the containing texture context's +8, those appear at +0x88/+0x89/+0x8a in copy.

`verify_release.py` now guards the correct DX12 address, full unwind range, marker reference, DX12 on_frame caller and optional/state/execute operands. `JoeyCopyABI.hpp` uses the full exact C++ signature and exact embedded-commit CommandContext header. The Windows cross-DLL fixture exercises engaged and empty optional callbacks, a non-null aliasing shared_ptr and destruction/forwarding ownership.

Production composition runs in the actual acquired image's command list via a pre-copy callback, with original source set to null. The callback draws into a prewarmed owned Mono texture and duplicates it to the acquired XR destination. No engine texture is overwritten. Copy success requires recorded work, exact destination/device/extents, an advanced fence and non-poisoned command context, plus the original return. Source texture selection/state come from this exact boundary, not StereoHook's resource accessor.

Binary/source correlation and a fixture still do not prove STALKER 2 headset behavior. Activation therefore requires a real native snapshot copy and successful scene submission observed in-process before modifying a subsequent producer.
