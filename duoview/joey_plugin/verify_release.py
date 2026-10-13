"""Verify the exact released binary and source-correlated x64 hook contracts."""
import bisect
import hashlib
import re
import struct
import sys
from pathlib import Path
import pefile
import capstone

HASH = "19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966"
CONTRACTS = {
    0x2969B0: ("adjust view rect called! {}", "4c894c24208954241055535741544155"),
    0x2BF2F0: ("calculate stereo projection matrix called! {} from {:x}", "488bc444894018488950104889480855"),
    0x2682C0: ("calculate stereo projection matrix called! {} from {:x}", "488bc448895808448948204c89401848"),
    0x2AD080: ("Called BeginRenderViewFamily for the first time", "48895c24085556574154415541564157"),
    0x3111F0: ("Called PreRenderViewFamily_RenderThread for the first time", "48895c2408488974241048897c241855"),
    0x1F0F50: ("[D3D12 VR] Could not set up, trying again next frame", "48895424105553565741544155415641"),
}

def verify(path):
    binary = Path(path).read_bytes()
    if hashlib.sha256(binary).hexdigest() != HASH:
        raise ValueError("Unrecognized released backend SHA256")
    pe = pefile.PE(data=binary)
    image = pe.get_memory_mapped_image()
    ranges = [(e.struct.BeginAddress, e.struct.EndAddress) for e in pe.DIRECTORY_ENTRY_EXCEPTION]
    begins = [a for a, _ in ranges]
    references = {}
    for match in re.finditer(b"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]", image):
        address = match.start()
        target = address + 7 + struct.unpack_from("<i", image, address + 3)[0]
        index = bisect.bisect_right(begins, address) - 1
        if index >= 0 and address < ranges[index][1]:
            references.setdefault(target, set()).add(ranges[index][0])
    # Independently correlate Joey's published C++ OpenXR::copy implementation
    # with this exact Mono DLL: full unwind region, prologue, and diagnostic.
    copy_rva = 0x1E4770
    copy_end = 0x1E5AC2
    copy_prologue = bytes.fromhex("4c894c24204c894424188954241048894c240855535657415441554156415748")
    if image[copy_rva:copy_rva+len(copy_prologue)] != copy_prologue:
        raise ValueError("Released Joey OpenXR::copy RVA/ABI prologue mismatch")
    if (copy_rva, copy_end) not in ranges:
        raise ValueError("Released Joey OpenXR::copy unwind boundary mismatch")
    marker = b"[VR] OpenXR: Frame not begun when trying to copy." + bytes([0])
    if copy_rva not in references.get(image.index(marker),set()):
        raise ValueError("OpenXR::copy diagnostic string not linked to candidate function")
    # Independent 2026-10-13 in-game diagnosis:
    # The original backend has NO openxr_loader.dll PE import; Khronos's loader
    # is statically linked into UEVRBackend.dll. Dynamic GetModuleHandleW
    # therefore leaves Build 61's native hooks inactive, even with a working UI.
    imports = {entry.dll.lower() for entry in pe.DIRECTORY_ENTRY_IMPORT}
    if b"openxr_loader.dll" in imports:
        raise ValueError("Backend import assumptions changed; re-audit embedded XR targets")

    # Exact wrapper RVAs and upstream callsites, confirmed against the published
    # Joey source and a real release disassembly. The plugin hooks the original
    # statically linked xrEndFrame/xrLocateViews, not another loader instance.
    embedded_openxr = {
        0x562790: ("xrEndFrame", "48895c2418574881ecb0000000488b05", 0x3DE20D),
        0x562E60: ("xrLocateViews", "405356574154415641574881ecc80000", 0x3F0746),
        0x562910: ("xrEnumerateSwapchainImages", "4053565741564881ecb8000000488b05", 0x3B2CFD),
    }
    for entry_rva, (name, prologue, caller) in embedded_openxr.items():
        if image[entry_rva:entry_rva + 16] != bytes.fromhex(prologue):
            raise ValueError(f"Embedded {name} entry contract mismatch: 0x{entry_rva:x}")
        if not any(a == entry_rva for a, _ in ranges):
            raise ValueError(f"Embedded {name} is not a PE unwind function entry")
        if image[caller] != 0xE8 or caller + 5 + struct.unpack_from("<i", image, caller + 1)[0] != entry_rva:
            raise ValueError(f"Embedded {name} original backend callsite mismatch")
        name_bytes = name.encode() + b"\\0"
        name_rva = image.find(name_bytes)
        if name_rva < 0 or entry_rva not in references.get(name_rva, set()):
            raise ValueError(f"Embedded {name} dispatch-string reference mismatch")
        print(f"Verified static OpenXR wrapper {name} RVA 0x{entry_rva:x}; direct original callsite 0x{caller:x}")

    print("Verified released Joey OpenXR::copy RVA, x64 prologue, unwind boundary and copy diagnostic")
    for address, (marker, prologue) in CONTRACTS.items():
        if image[address:address+16] != bytes.fromhex(prologue):
            raise ValueError(f"Function prologue mismatch: {address:x}")
        target = image.index(marker.encode() + b"\0")
        if address not in references.get(target, set()):
            raise ValueError(f"Marker is not referenced from the expected unwind function: {address:x}")
        print(f"Verified released function 0x{address:x}: {marker}")
    disassembler = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    proofs = {
        0x1E47A4: ("lea", "rbx, [rcx + 0x170]"),
        0x1E4890: ("cmp", "byte ptr [rbx + 0x40], 0"),
        0x1E5338: ("cmp", "byte ptr [r13 + 0x40], 0"),
        0x1E53A6: ("mov", "r9d, dword ptr [rbp + 0x118]"),
        0x1E5473: ("cmp", "byte ptr [rax + 0x40], 0"),
        0x1E549A: ("cmp", "byte ptr [r9 + 0x40], 0"),
        0x1E54EF: ("call", "0x3b8090"),
        0x2AD39D: ("mov", "ecx, dword ptr [rip + 0x11299cd]"),
        0x2AD3A3: ("mov", "edi, dword ptr [rcx + r15]"),
        0x2AD3B0: ("mov", "rax, qword ptr [rip + 0xc0ce81]"),
        0x2AD3B8: ("cmp", "byte ptr [rax + 0x18], 0"),
        0x2AD3C3: ("mov", "esi, dword ptr [rax + 0x14]"),
        0x3118F9: ("mov", "eax, dword ptr [rip + 0x10c5471]"),
        0x3118FF: ("mov", "ecx, dword ptr [rax + r14]"),
        0x136870: ("mov", "rax, qword ptr [rip + 0xdda699]"),
        0x136877: ("add", "rax, 8"),
        0x1F1040: ("mov", "rax, qword ptr [rbx + 0x56e60]"),
        0x1F1047: ("mov", "rax, qword ptr [rax + 0x90]"),
        0x2AD3CC: ("mov", "rbx, qword ptr [rax + 0x80]"),
        0x2AD3D3: ("mov", "dword ptr [rbx + 0x328], edi"),
        0x1F342F: ("mov", "rbx, qword ptr [rax + 0xa0]"),
        0x1F347E: ("mov", "eax, dword ptr [rbx + 0x32c]"),
    }
    for address, expected in proofs.items():
        instruction = next(disassembler.disasm(image[address:address+16], address))
        if (instruction.mnemonic, instruction.op_str) != expected:
            raise ValueError(f"Operand proof mismatch at 0x{address:x}")
    assert 0x2AD39D + 6 + 0x11299CD == 0x13D6D70
    assert 0x3118F9 + 6 + 0x10C5471 == 0x13D6D70
    assert 0x2AD3B0 + 7 + 0xC0CE81 == 0xEBA238
    assert 0x136870 + 7 + 0xDDA699 == 0xF10F10
    # The shared logging marker also occurs in DX11 copy at 0x1c4280.
    # Marker identity alone was the Build49 handoff mistake. Prove this
    # function is actually called from the exact D3D12 on_frame region.
    call=0x1F83F5
    assert image[call]==0xE8 and call+5+struct.unpack_from("<i",image,call+1)[0]==copy_rva
    print("Verified DX12 caller, optional callback flags, source-state operand and CommandContext execute target")
    print("Verified dynamic SDK offsets, VR holder, active selection, and XR producer/consumer counter operands")

if __name__ == "__main__":
    verify(sys.argv[1])
