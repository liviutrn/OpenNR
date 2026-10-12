#!/usr/bin/env python3
"""Port calibrated Joey Mono onto the pinned accessible public UEVR backend.

DX12/OpenXR compile-and-runtime experiment; Windows compilation and headset
validation remain separate prerequisites. IDs 3/4 remain reserved/unavailable.
"""
import argparse
from pathlib import Path
import subprocess

PUBLIC_UEVR_PIN = '4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d'
PUBLIC_SDK_PIN = '418729025bad57b094bf6b2e2b55734454c97de6'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    root = parser.parse_args().root.resolve()
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PUBLIC_UEVR_PIN:
        parser.error(f'expected public UEVR {PUBLIC_UEVR_PIN}, got {head}')
    patch = Path(__file__).with_name('public_mono.patch')
    subprocess.run(['git', '-C', str(root), 'apply', '--check', str(patch)], check=True)
    subprocess.run(['git', '-C', str(root), 'apply', str(patch)], check=True)
    print('Public calibrated Mono ID 5 port applied (DX12/OpenXR only; compile and headset validation required).')

if __name__ == '__main__':
    main()
