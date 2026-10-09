#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/SinglePassLadder.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
using Crop = NeuralRendering::AdaptiveCropController;
namespace Ladder = NeuralRendering::SinglePassLadder;
Crop::Config Config(const std::array<unsigned,4>& crops) {
    Crop::Config c; c.enabled=true; c.minimumCoverage=crops.back(); c.stepCoverage=5;
    c.downshiftFrames=c.upshiftFrames=c.minimumDwellFrames=1; c.transitionFrames=8; return c;
}
void Tick(Crop& crop,unsigned& frame,Crop::Config config,unsigned target) {
    config.targetCoverage=target;
    const auto current=crop.ActiveCoverage();
    crop.Update(++frame,config,true,100,true,false,current>target,false,true,current>target,current<target);
}
void Settle(Crop& crop,unsigned& frame,const Crop::Config& config,unsigned target) {
    for(unsigned i=0;i<100;++i) {
        Tick(crop,frame,config,target);
        assert(crop.RenderCoverage()>=60 && crop.RenderCoverage()<=100);
        assert(std::isfinite(crop.VisibleCoverage()));
        assert(crop.VisibleCoverage()<=crop.RenderCoverage());
        if(!crop.IsTransitioning() && crop.RenderCoverage()==target) return;
    }
    assert(false && "stage target did not settle");
}
int main() {
    Ladder::Config config;
    for(unsigned s=0;s<5;++s) {
        assert(Ladder::Level(s).model==100 && Ladder::Level(s).nrEnabled);
        assert(Ladder::Level(s).crop==100-s*10);
    }
    assert(!Ladder::Level(5).nrEnabled && Ladder::Level(5).crop==100);
    assert(!Ladder::Level(UINT32_MAX).nrEnabled);
    for(unsigned s=0;s<4;++s) assert(Ladder::Select(s,1000,config,false,false)==1);
    assert(Ladder::Select(4,23,config,false,false)==0);
    assert(Ladder::Select(4,25,config,false,false)==1);
    assert(Ladder::Select(5,15,config,false,false)==0);
    assert(Ladder::Select(5,13,config,false,true)==2);
    assert(Ladder::Select(4,13,config,false,true)==0);
    for(unsigned s=0;s<6;++s) {
        for(float ms:{1.f,13.f,19.f,20.f,24.f,1000.f}) {
            assert(Ladder::Select(s,ms,config,true,false)==0);
            for(unsigned force=1;force<=6;++force) {
                auto fc=config;fc.forcedStage=force;
                assert(Ladder::Select(s,ms,fc,false,false)==0);
            }
        }
        for(float invalid:{0.f,-1.f,std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()})
            assert(Ladder::Select(s,invalid,config,false,false)==0);
    }
    config.enableBelow=config.disableAbove;
    assert(Ladder::Select(4,1000,config,false,false)==0);
    assert(Ladder::Select(5,1,config,false,false)==0);
    assert(Ladder::Select(2,1000,config,false,false)==1);
    assert((Ladder::NormalizeCrops({UINT32_MAX,0,75,61})==std::array<unsigned,4>{100,60,60,60}));
    unsigned paths=0;
    for(unsigned a=60;a<=100;a+=5) for(unsigned b=60;b<=a;b+=5)
    for(unsigned c=60;c<=b;c+=5) for(unsigned d=60;d<=c;d+=5) {
        const std::array<unsigned,4> crops{a,b,c,d};
        for(unsigned from=0;from<6;++from) for(unsigned to=0;to<6;++to) {
            Crop crop; unsigned frame=0;const auto cc=Config(crops);
            const auto source=Ladder::Level(from,crops).crop,target=Ladder::Level(to,crops).crop;
            assert(Ladder::Level(to,crops).model==100);
            Settle(crop,frame,cc,source);
            unsigned changes=0,previous=crop.RenderCoverage();
            for(unsigned i=0;i<30;++i) {
                Tick(crop,frame,cc,target);
                if(crop.RenderCoverage()!=previous) { ++changes; previous=crop.RenderCoverage(); }
                assert(crop.RenderCoverage()==source || crop.RenderCoverage()==target);
                if(!crop.IsTransitioning() && crop.RenderCoverage()==target) break;
            }
            assert(crop.RenderCoverage()==target && changes<=1);
            ++paths;
        }
    }
    for(unsigned floor=60;floor<=100;floor+=5) for(unsigned during=0;during<10;++during) {
        Crop crop;unsigned frame=0;auto cc=Config({90,80,70,60});
        Settle(crop,frame,cc,100);
        for(unsigned i=0;i<=during;++i) Tick(crop,frame,cc,60);
        const auto oldRender=crop.RenderCoverage();
        cc.minimumCoverage=floor;Tick(crop,frame,cc,floor);
        if(crop.IsTransitioning()) assert(crop.RenderCoverage()==oldRender);
        Settle(crop,frame,cc,floor);
        const auto generation=crop.Generation();const auto render=crop.RenderCoverage();
        cc.targetCoverage=100;
        crop.Update(frame,cc,true,100,true,false,false,false,true,false,true);
        assert(crop.Generation()==generation && crop.RenderCoverage()==render);
        ++paths;
    }
    Crop crop;unsigned frame=0;auto cc=Config({90,80,70,60});
    Settle(crop,frame,cc,100);Tick(crop,frame,cc,75);
    const auto before=crop.RenderCoverage();const auto alpha=crop.HandoffAlpha();
    cc.hold=true;for(unsigned i=0;i<20;++i) Tick(crop,frame,cc,75);
    assert(crop.RenderCoverage()==before && crop.HandoffAlpha()==alpha);
    cc.hold=false;Settle(crop,frame,cc,75);
    crop.Update(++frame,cc,true,100,false,false,true,false,true,true,false);
    assert(!crop.IsRuntimeActive() && crop.RenderCoverage()==100);
    std::cout<<"Full-resolution six-stage controller: "<<paths<<" transitions/live edits passed; direct geometry commits, endpoint gates, stale timing and hold checked.\n";
}
