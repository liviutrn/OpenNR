#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/FeatherGeometry.h"
#include <iostream>
#include <stdexcept>
using namespace NeuralRendering::FeatherGeometry;
void Require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Region { float x,y,w,h; };
int main()
{
    unsigned cases=0;
    for (float extent : {32.f,480.f,1000.f,1500.f,2000.f})
    for (float origin : {0.f,1.f,13.f,1999.f,2000.f})
    for (float resolution : {100.f,85.f,70.f})
    for (float compression : {1.f,3.f,5.f,10.f,20.f})
    for (float power : {1.f,2.f,3.5f,4.f})
    for (float border : {0.f,.05f,.167f,.3f}) {
        const float pitch=100.f/resolution;
        const auto a=MakeAxis(extent*border,extent*(1-border),extent,origin,pitch,compression,power);
        Require(a.packedExtent<=std::ceil(extent/pitch)+2,"Allocation envelope exceeded");
        float previous=-1e30f;
        for(unsigned i=0;i<=256;++i) {
            const float p=extent*float(i)/256;
            const float m=ToModel(p,a);
            Require(m>=previous,"Non-monotonic curve");previous=m;
            Require(std::abs(ToPhysical(m,a)-p)<.006f,"Curve roundtrip failed");
        }
        const float mid=(a.begin+a.end)*.5f;
        Require(std::abs(ToPhysical(ToModel(mid,a)+1,a)-mid-pitch)<.001f,"Centre pitch changed");
        const float lattice=(origin+a.begin)/pitch;
        if(a.begin>0) Require(std::abs(lattice-std::round(lattice))<.001f,"Centre phase not eye anchored");
        // Independent derivative of the forward curve at both ends.
        const float length=a.extent-a.end;
        if(length>32.f) {
            const float start=a.packedBegin+(a.end-a.begin)/pitch;
            const float divisor=1+(compression-1)/(power+1);
            const float end=start+length/(divisor*pitch);
            const float step=.001f*length/(divisor*pitch);
            Require(std::abs((ToPhysical(start+step,a)-ToPhysical(start,a))/step-pitch)<.035f+5e-7f*extent/step,"Inner curve slope discontinuity");
            Require(std::abs((ToPhysical(end,a)-ToPhysical(end-step,a))/step-pitch*compression)<.02f*pitch*compression+1e-6f*extent/step,"Edge compression wrong");
        }
        ++cases;
    }
    // Motion must refer to the previous curve even when the gaze and tier both change.
    for(float resolution:{100.f,85.f,70.f}) for(float previousResolution:{100.f,85.f,70.f}) {
        const auto current=MakeAxis(250,1250,1500,117,100/resolution,10,2);
        const auto previous=MakeAxis(200,1000,1200,134,100/previousResolution,10,2);
        for(float world:{400.f,650.f,900.f,1150.f}) {
            const float cur=ToModel(world-117,current);
            const float prev=ToModel(world-134-2.5f,previous);
            const float mapped=ToModel(ToPhysical(cur,current)+117-134-2.5f,previous);
            Require(std::abs(prev-mapped)<.002f,"Previous geometry motion mapping failed");
            Require(std::abs(ToPhysical(cur+(mapped-cur),previous)+134-(world-2.5f))<.005f,"Temporal destination not world aligned");
        }
        ++cases;
    }
    // Inverse LUT error, independently reconstructing linear interpolation.
    float worst=0;
    for(float compression:{1.f,3.f,10.f,20.f}) for(float power:{1.f,2.f,3.5f,4.f}) {
        Axis a;a.compression=compression;a.power=power;
        std::array<float,4097> lut{};
        for(unsigned i=0;i<lut.size();++i) lut[i]=ExteriorToModel(float(i)/4096,1,a);
        for(unsigned i=0;i<=16384;++i) {
            const float t=float(i)/16384, index=t*4096;
            const unsigned low=std::min(unsigned(index),4095u);
            const float value=lut[low]+(lut[low+1]-lut[low])*(index-float(low));
            worst=std::max(worst,std::abs(value-ExteriorToModel(t,1,a))*2000);
        }
    }
    Require(worst<.005f,"Inverse LUT not precise enough for gaze stability");
    for(float size:{.01f,.3f,.5f,.8f,1.f}) for(float x:{0.f,.1f,.5f,.99f}) for(float exp:{0.f,25.f,50.f,100.f}) {
        Region core{std::min(x,1-size),std::min(x,1-size),size,size};
        const auto expanded=Expand(core,exp);
        Require(expanded.x>=0&&expanded.y>=0&&expanded.x+expanded.w<=1.000001f,"Expansion not bounded");
        Require(expanded.x<=core.x&&expanded.x+expanded.w>=core.x+core.w-.000001f,"Expansion excludes centre");
        if(exp==0) Require(expanded.x==core.x&&expanded.w==core.w,"Zero expansion changed crop");
        ++cases;
    }
    std::cout<<cases<<" geometry, phase, motion and clipped crop cases; LUT max error "<<worst<<" pixels at 2K\n";
}
