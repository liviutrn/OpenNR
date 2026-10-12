#!/usr/bin/env python3
from pathlib import Path
import argparse, subprocess
p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args()
pin='60be4b0f9a646109fd9fdf448bacd41477234091'
assert subprocess.check_output(['git','-C',str(a.root),'rev-parse','HEAD'],text=True).strip()==pin
options=a.root/'UEVR/RenderingModeOptions.cs'; s=options.read_text(encoding='utf-8-sig')
anchor='            result.Add(Mono.ToString(), "Mono (Experimental)");'
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'\n            result.Add("6", "DuoView Mono (Experimental)");')
options.write_text(s,encoding='utf-8')
main=a.root/'UEVR/MainWindow.xaml.cs';s=main.read_text(encoding='utf-8-sig')
assert s.count('RenderingModeOptions.Create(supportsDibr: true)')==1
s=s.replace('RenderingModeOptions.Create(supportsDibr: true)','RenderingModeOptions.Create(supportsDibr: false)')
old='Mono (Experimental): One centered head-tracked scene sent to both eyes, without binocular scene depth. DX11/DX12 with OpenXR and parallel optical axes. Native Fix, Ghost Fix/bootstrap and depth submission are inactive without changing their saved preferences. Live switching waits for GPU copies to retire and a fresh main view; incompatible compatibility settings are reported in the in-game UI.'
new='Mono (Experimental): one centered scene with 6DoF head tracking sent to both eyes. DuoView Mono (Experimental): a sharp gaze-centered fovea and reduced-resolution full-FOV periphery, combined into the same Mono image. Both modes require DX12 and OpenXR in this build. Mode changes wait for current-frame resources. Configure DuoView from the in-game VR / Unreal menu.'
assert s.count(old)==1
s=s.replace(old,new)
main.write_text(s,encoding='utf-8')
test=a.root/'tests/RenderingModes/Program.cs';s=test.read_text()
s=s.replace('id <= 5','id <= 6').replace('id == 5 || dibr','id == 5 || id == 6 || dibr').replace('"5", "99"','"5", "6", "99"')
test.write_text(s)
