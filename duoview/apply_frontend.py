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
main.write_text(s,encoding='utf-8')
test=a.root/'tests/RenderingModes/Program.cs';s=test.read_text()
s=s.replace('id <= 5','id <= 6').replace('id == 5 || dibr','id == 5 || id == 6 || dibr').replace('"5", "99"','"5", "6", "99"')
test.write_text(s)
