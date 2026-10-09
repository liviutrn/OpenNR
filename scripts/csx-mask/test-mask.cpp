#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include "../../runtime/open-shaders/src/Features/Upscaling/ShaderDetailMask.h"
struct UV { float x,y,w,h; };
struct Offset { float x=0,y=0; };
struct Profile { bool available=false; float coverageScale=1,centerHorizontalScale=1; std::array<Offset,2> centerOffsets{}; };
int main() {
 unsigned cases=0,disabled=0;
 for (float w : {0.01f,0.1f,0.25f,0.5f,0.8f,0.9f,1.0f})
 for (float h : {0.01f,0.1f,0.25f,0.5f,0.8f,0.9f,1.0f})
 for (float lx : {0.0f,0.5f,1.0f}) for (float ly : {0.0f,0.5f,1.0f}) {
  UV left{lx*(1-w),ly*(1-h),w,h};
  UV right{(1-lx)*(1-w*0.85f),(1-ly)*(1-h*0.85f),w*0.85f,h*0.85f};
  Profile p; if (!ShaderDetailMask::ProtectRectangles(p,left,right)) {++disabled;continue;}
  for (unsigned eye=0;eye<2;++eye) {
   const auto& r=eye==0?left:right;
   for (float x : {r.x,r.x+r.w*0.5f,r.x+r.w})
   for (float y : {r.y,r.y+r.h*0.5f,r.y+r.h}) {
    const float nx=(x-0.5f-p.centerOffsets[eye].x)/(p.coverageScale*p.centerHorizontalScale*0.5f);
    const float ny=(y-0.5f-p.centerOffsets[eye].y)/(p.coverageScale*0.5f);
    if (nx*nx*nx*nx+ny*ny*ny*ny>1.000001f) throw std::runtime_error("Full-quality SR rectangle was reduced");
    ++cases;
   }
  }
 }
 Profile full; if (ShaderDetailMask::ProtectRectangles(full,UV{0,0,1,1},UV{0,0,1,1})) throw std::runtime_error("Full-eye mask should bypass");
 std::cout<<cases<<" protected stereo sample cases; "<<disabled<<" near-full masks bypassed\n";
}
