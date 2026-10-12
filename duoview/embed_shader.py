#!/usr/bin/env python3
from pathlib import Path
import argparse
p=argparse.ArgumentParser(); p.add_argument('output',type=Path); a=p.parse_args()
s=Path(__file__).parent
shader=(s/'DuoViewCompositeRaster.hlsl').read_text().replace('#include "DuoViewComposite.hlsl"',(s/'DuoViewComposite.hlsl').read_text())
a.output.write_text('#pragma once\nnamespace uevr::duoview::dx12 {\ninline constexpr char shader_source[] = R"DUOVIEW_SHADER('+shader+')DUOVIEW_SHADER";\n}\n')
