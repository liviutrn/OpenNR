// Standalone Linux sanity/edge tests for portable source in the recovery archive.
#include "QuadViewGeometry.hpp"
#include "QuadViewSettings.hpp"
#include "QuadViewViewDemand.hpp"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
using namespace uevr::quadview;
int main(){
 std::mt19937 rng{0x1861u};
 std::uniform_real_distribution<float> fraction{-0.2f,4.2f};
 // A 2-source-per-eye packed atlas is not representable at width=1.
 std::uniform_int_distribution<uint32_t> dims{256,8192};
 const Settings defaults{};
 uint64_t accepted=0,rejected=0;
 for(int i=0;i<200000;i++){
  auto w=dims(rng),h=dims(rng);
  Settings request=defaults;
  request.crop_width=fraction(rng);request.crop_height=fraction(rng);
  request.context_scale=fraction(rng);request.foveal_density=fraction(rng);
  auto fixed=reconcile_settings(request,defaults,w,h);
  auto layout=make_layout(w,h,fixed.settings.crop_width,fixed.settings.crop_height,fixed.settings.context_scale,fixed.settings.foveal_density);
  if (!layout) {std::cerr<<"FAIL i="<<i<<" w="<<w<<" h="<<h<<" options="<<fixed.settings.crop_width<<","<<fixed.settings.crop_height<<","<<fixed.settings.context_scale<<","<<fixed.settings.foveal_density<<" flags="<<fixed.rejected<<"\n"; return 1;} assert(layout->atlas_width==w*2 && layout->atlas_height==h);
  for(int eye=0;eye<2;++eye){
    auto c=layout->views[eye],f=layout->views[eye+2];
    assert(c.width>0 && f.width>0 && c.height>0 && f.height>0);
    assert(c.x==unsigned(eye)*w && f.x==c.x+c.width && f.x+f.width<=(eye+1)*w);
    assert(c.height<=h && f.height<=h);
    auto crop=layout->focus_crops[eye];
    assert(crop.u0>=0 && crop.v0>=0 && crop.u1<=1 && crop.v1<=1);
  }
  auto stable=reconcile_settings(fixed.settings,fixed.settings,w,h);
  assert(same_settings(stable.settings,fixed.settings));
  if(fixed.rejected)++rejected;else ++accepted;
 }
 // Second pass exercises valid physical atlas geometry, asymmetric per-eye
 // gaze positions and immutable per-draw latched crops at realistic VR sizes.
 std::uniform_real_distribution<float> crop{.05f,.60f};
 std::uniform_real_distribution<float> context{.05f,.25f};
 std::uniform_real_distribution<float> density{.25f,1.2f};
 std::uniform_real_distribution<float> position{0.f,1.f};
 uint64_t valid=0;
 for(int i=0;i<100000;i++){
  const uint32_t w=dims(rng),h=dims(rng);
  Settings s=defaults;
  s.crop_width=crop(rng);s.crop_height=crop(rng);
  s.context_scale=context(rng);s.foveal_density=density(rng);
  const std::array<FocusPoint,2> centers{{{position(rng),position(rng)},{position(rng),position(rng)}}};
  auto rects=make_layout(w,h,s.crop_width,s.crop_height,s.context_scale,s.foveal_density,centers);
  if(!rects)continue;
  ++valid;
  auto checked=reconcile_settings(s,defaults,w,h);
  assert(checked.rejected==0 && same_settings(s,checked.settings));
  for(unsigned eye=0;eye!=2;++eye){
   const auto& r=rects->views[eye+2];
   const auto& c=rects->focus_crops[eye];
   assert(rects->views[eye].width+r.width<=w);
   assert(r.height<=h);
   assert(c.u0>=0 && c.v0>=0 && c.u1<=1.f && c.v1<=1.f);
   assert(std::abs((c.u1-c.u0)-s.crop_width)<1e-5f);
   assert(std::abs((c.v1-c.v0)-s.crop_height)<1e-5f);
  }
  LayoutLatch latch;
  assert(latch.freeze(1,i+1,*rects));
  const auto different=make_layout(w,h,s.crop_width,s.crop_height,s.context_scale,s.foveal_density,
    std::array<FocusPoint,2>{{{.1f,.9f},{.9f,.1f}}});
  assert(different);
  assert(latch.freeze(1,i+1,*different)->focus_crops==rects->focus_crops);
  assert(latch.freeze(1,i+2,*different)->focus_crops==different->focus_crops);
 }
 assert(valid>90000);
 std::cout<<"200000 mixed validity + 100000 valid-range geometry/settings cases PASSED; "
          <<"mixed accepted="<<accepted<<", rejected="<<rejected<<", valid-range accepted="<<valid<<"\n";
}
