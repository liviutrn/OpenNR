# Released Joey adapter provenance

Official asset: https://github.com/joeyhodge/UEVR/releases/download/101226HELLRAISERp1/DIBRMONOUEVR.zip

ZIP SHA256: `d078f6e8c3c36f6877d0c6eafcb1d0344111d4f4992838c1a5ec4b91c553fade`.

Backend SHA256: `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.

The binary contains `5ac7edc207866569334175e4ed8a7517971547f6`, `3cffbc82429b6165ceec2714f0f0d9ae48f55596` and tag `092826MONO+5_8_3_UEVR`. The latter commit is not fetchable through public Git. The default public `ue57performance` branch does not contain the released Mono method; treating its HEAD as exact Mono source would be incorrect. Public `uevr-dibr-optin-safe` commit `e30b0ee5dd480ce607abb63ef74c317bd43bd871` supplies plugin headers and the algorithm reference, not a claim of exact released source provenance.

`verify_release.py` checks hash, PE unwind boundaries, RIP-relative logging-string xrefs, unchanged 16-byte prologues, and exact counter/accessor operand sequences. This reproduces the observed binary adapter rather than substituting a private SDK structure. The plugin also verifies the loaded prologues before patching. UEVR's own plugin inline-hook registration supplies trampolines and rollback. The injector/backend file is not modified.

| Function | Released RVA | ABI evidence |
| --- | --- | --- |
| AdjustViewRect | `0x2969b0` | RCX stereo, EDX index, R8/R9 x/y; w/h stack; unique marker |
| CalculateStereoProjectionMatrix | `0x2bf2f0` | RCX stereo, RDX output, R8D index; unique marker |
| Projection std::function closure | `0x2682c0` | RCX closure, RDX stereo, R8 output, R9D index; second marker reference |
| BeginRenderViewFamily | `0x2ad080` | RCX extension, RDX family; unwind/marker/source signature |
| PreRenderViewFamily_RenderThread | `0x3111f0` | RCX extension, RDX command list, R8 family; unwind/marker/source signature |
| D3D12Component::on_frame | `0x1f0f50` | RCX component, RDX VR; marker, argument stores, public signature |

The UE family frame offset is **not hardcoded**: both game and render functions load the dynamically discovered DWORD at image RVA `0x13d6d70` and read the family using that offset. The SDK resolved-layout descriptor pointer at `0xeba238` exposes its discovered views offset (`+0x14`) and validity bit (`+0x18`), proven by BeginRenderViewFamily's reads. The views array count is checked at offset +8 using the public TArray ABI.

`VR::get` at `0x136870` loads a holder pointer from image RVA `0xf10f10` and returns holder+8; the VR pointer is the first field of that shared_ptr reference. The exact release reads RenderingMethodSetting at VR+`0x56e60`, then its atomic active selection at `+0x90`. The plugin checks active **and requested** Native Stereo before touching a frame, avoiding a pending Mono transition.

The binary's game-family callback writes the family FrameNumber to active runtime+`0x328`. Its OpenXR consumer path loads VR+`0xa0` (OpenXR) and reads runtime+`0x32c` (the queued RHI render frame). The plugin uses the producer number from the family, not a guessed `engine frame + 1`; it matches the OpenXR number at composition time.

These observations establish exact-release hook/address operands. They do not prove game memory objects are live, that the source resource is the completed intended atlas, that lens mapping is correct in the headset, or that callbacks are sufficient under every engine pipeline. Runtime guards and staged game validation remain necessary.
