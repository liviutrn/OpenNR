#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/SinglePassLadder.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/AdaptiveCropController.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
using namespace NeuralRendering;
namespace Ladder = SinglePassLadder;
using Crop = AdaptiveCropController;
Crop::Config CropConfig(unsigned step) {
    Crop::Config c; c.enabled=true; c.minimumCoverage=100-2*step; c.stepCoverage=step;
    c.downshiftFrames=c.upshiftFrames=c.minimumDwellFrames=1; c.transitionFrames=8; return c;
}
void Tick(Crop& c, unsigned& frame, const Crop::Config& config, unsigned target) {
    const auto current=c.ActiveCoverage();
    c.Update(++frame,config,true,100,true,false,current>target,false,true,current>target,current<target);
}
void Settle(Crop& c, unsigned& frame, const Crop::Config& config, unsigned target) {
    for(unsigned i=0;i<100;++i) {
        Tick(c,frame,config,target);
        assert(c.RenderCoverage()>=60 && c.RenderCoverage()<=100);
        assert(std::isfinite(c.VisibleCoverage()));
        assert(c.VisibleCoverage()<=static_cast<float>(c.RenderCoverage()));
        if(!c.IsTransitioning() && c.RenderCoverage()==target) return;
    }
    assert(false && "Crop did not reach requested stage");
}
int main() {
    Ladder::Config config;
    for(unsigned stage=0;stage<4;++stage) assert(Ladder::Select(stage,1000,config,false,false)==1);
    assert(Ladder::Select(4,23,config,false,false)==0);
    assert(Ladder::Select(4,25,config,false,false)==1);
    assert(Ladder::Select(5,15,config,false,false)==0);
    assert(Ladder::Select(5,13,config,false,false)==2);
    assert(Ladder::Select(5,13,config,false,true)==0);
    for(unsigned stage=0;stage<6;++stage) {
        for(float ms:{1.f,13.f,19.f,20.f,24.f,60.f,1000.f}) {
            assert(Ladder::Select(stage,ms,config,true,false)==0);
            for(unsigned forced=1;forced<=6;++forced) {
                auto forcedConfig=config; forcedConfig.forcedStage=forced;
                assert(Ladder::Select(stage,ms,forcedConfig,false,false)==0);
            }
        }
        for(float invalid:{0.f,-1.f,std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()})
            assert(Ladder::Select(stage,invalid,config,false,false)==0);
    }
    config.enableBelow=config.disableAbove;
    assert(Ladder::Select(4,1000,config,false,false)==0);
    assert(Ladder::Select(5,1,config,false,false)==0);
    assert(Ladder::Select(2,1000,config,false,false)==1);
    assert(Ladder::Level(UINT32_MAX).nrEnabled==false);
    assert(Ladder::NormalizeCropStep(UINT32_MAX)==20);
    unsigned paths=0;
    for(unsigned step:{10u,15u,20u}) {
        assert(Ladder::Level(0,step).crop==100);
        assert(Ladder::Level(1,step).crop==100-step);
        for(unsigned stage=2;stage<=4;++stage) assert(Ladder::Level(stage,step).crop==100-2*step);
        assert(Ladder::Level(3,step).model==85 && Ladder::Level(4,step).model==70);
        assert(!Ladder::Level(5,step).nrEnabled && Ladder::Level(5,step).crop==100);
        for(unsigned from=0;from<6;++from) for(unsigned to=0;to<6;++to) {
            Crop crop; unsigned frame=0; auto cc=CropConfig(step);
            Settle(crop,frame,cc,Ladder::Level(from,step).crop);
            Settle(crop,frame,cc,Ladder::Level(to,step).crop);
            assert(crop.RenderCoverage()==Ladder::Level(to,step).crop);
            ++paths;
        }
        for(unsigned nextStep:{10u,15u,20u}) for(unsigned during=0;during<10;++during) {
            Crop crop; unsigned frame=0; auto cc=CropConfig(step);
            Settle(crop,frame,cc,100);
            for(unsigned i=0;i<=during;++i) Tick(crop,frame,cc,100-2*step);
            const auto oldRender=crop.RenderCoverage();
            const auto oldActive=crop.ActiveCoverage();
            cc=CropConfig(nextStep); Tick(crop,frame,cc,100-2*nextStep);
            // A live floor edit cannot commit new geometry in its first frame.
            if(oldActive<cc.minimumCoverage && crop.IsTransitioning()) assert(crop.RenderCoverage()==oldRender);
            Settle(crop,frame,cc,100-2*nextStep);
            const auto generation=crop.Generation(); const auto render=crop.RenderCoverage();
            crop.Update(frame,cc,true,100,true,false,true,false,true,true,false);
            assert(crop.Generation()==generation && crop.RenderCoverage()==render);
            ++paths;
        }
        Crop crop; unsigned frame=0;auto cc=CropConfig(step);
        Settle(crop,frame,cc,100); Tick(crop,frame,cc,100-step);
        const auto before=crop.RenderCoverage(); const auto alpha=crop.HandoffAlpha();
        cc.hold=true; for(unsigned i=0;i<20;++i) Tick(crop,frame,cc,100-step);
        assert(crop.RenderCoverage()==before && crop.HandoffAlpha()==alpha);
        cc.hold=false;Settle(crop,frame,cc,100-step);
        crop.Update(++frame,cc,true,100,false,false,true,false,true,true,false);
        assert(!crop.IsRuntimeActive() && crop.RenderCoverage()==100);
    }
    std::cout << "Actual ladder policy + crop actuator passed: " << paths
              << " forced-stage pairs/live step edits; endpoint gates, stale frame, hold, geometry loss.\n";
}
