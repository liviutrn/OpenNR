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
    copy_rva = 0x1C4280
    copy_end = 0x1C4D34
    copy_prologue = bytes.fromhex("4c894c24204c89442418895424105553565741544155")
    if image[copy_rva:copy_rva+len(copy_prologue)] != copy_prologue:
        raise ValueError("Released Joey OpenXR::copy RVA/ABI prologue mismatch")
    if (copy_rva, copy_end) not in ranges:
        raise ValueError("Released Joey OpenXR::copy unwind boundary mismatch")
    marker = b"[VR] OpenXR: Frame not begun when trying to copy.\\x00".replace(b"\\x00",b"\\0")
    if copy_rva not in references.get(image.index(marker),set()):
        raise ValueError("OpenXR::copy diagnostic string not linked to candidate function")
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
    print("Verified dynamic SDK offsets, VR holder, active selection, and XR producer/consumer counter operands")

if __name__ == "__main__":
    verify(sys.argv[1])
