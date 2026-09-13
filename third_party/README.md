# Dependency and ownership boundaries

The runtime's upstream submodule pins are preserved in the root `.gitmodules` and the imported runtime history. `_external/PixRestore` remains an optional upstream-owned submodule. Active local build dependencies are external and hash-inventoried in the consolidation manifest; compiled SDK tools and large environments are not vendored into the source tree.

Retain each dependency's licenses and attribution. NVIDIA's Feature 18 carrier, private weights, model checkpoints and generated evidence are local inputs, not source repository payloads. The consolidated monorepo does not grant additional redistribution rights for any imported component.
