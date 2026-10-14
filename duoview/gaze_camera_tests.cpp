#include "DuoViewState.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    const std::array<float,16> projection{
        .55f,0,0,0, 0,.75f,0,0, .03f,-.02f,0,1, 0,0,.1f,0};
    const auto full_height=make_layout(3400,3172,.5f,.5f,.2f,2.f,.5f,.5f,true);
    assert(full_height && full_height->fovea.height==3176 && full_height->output_height==3172);
    assert(layout_valid(*full_height));
    for (float crop:{.1f,.3f,.5f,.8f}) for (float u:{0.f,.2f,.5f,.8f,1.f})
        for (float v:{0.f,.2f,.5f,.8f,1.f}) {
            const auto layout=make_layout(5000,5000,crop,crop,.2f,1.f,u,v,true);
            assert(layout && layout_valid(*layout));
            assert(layout->atlas_width==layout->fovea.width+layout->periphery.width);
            assert(layout->atlas_height==(std::max)(layout->fovea.height,layout->periphery.height));
            assert(layout->output_width==5000 && layout->output_height==5000);
            const auto camera=make_foveal_camera(projection,*layout);
            assert(camera);
            for (unsigned x=0;x<9;++x) for (unsigned y=0;y<9;++y) {
                const float full_u=layout->u0+(layout->u1-layout->u0)*x/8;
                const float full_v=layout->v0+(layout->v1-layout->v0)*y/8;
                const auto uv=foveal_uv(*camera,full_u,full_v);
                assert(uv[0]>=0 && uv[0]<=1 && uv[1]>=0 && uv[1]<=1);
                const float rx=(uv[0]*2-1)/camera->scale_x;
                const float ry=(1-uv[1]*2)/camera->scale_y;
                std::array<float,3> reconstructed{};
                for (unsigned i=0;i<3;++i)
                    reconstructed[i]=rx*camera->right[i]+ry*camera->up[i]+camera->forward[i];
                const auto ray=full_view_ray(camera->full_projection,full_u,full_v);
                assert(std::abs(reconstructed[0]/reconstructed[2]-ray[0])<5e-5f);
                assert(std::abs(reconstructed[1]/reconstructed[2]-ray[1])<5e-5f);
            }
            std::array<std::array<double,4>,4> matrix{};
            for (unsigned i=0;i<4;++i) matrix[i][i]=1;
            rotate_foveal_view(matrix,*camera);
            assert(matrix[3][0]==0 && matrix[3][1]==0 && matrix[3][2]==0 && matrix[3][3]==1);
            for (unsigned row=0;row<3;++row) {
                double axis=0;
                for (unsigned col=0;col<3;++col) axis+=matrix[col][row]*camera->forward[col];
                assert(std::abs(axis-(row==2 ? 1:0))<1e-5);
            }
        }
    State state;
    Settings s; s.gaze_camera=true; s.compact_atlas=true; s.hold_tracking_loss=true;
    assert(state.configure(s));
    const auto first=state.begin({1,1},5000,5000,projection,[]()->std::optional<UV>{return UV{.72f,.28f};},100);
    assert(first && first->config.foveal_camera.enabled);
    assert(first->config.layout.atlas_width==3504 && first->config.layout.atlas_height==2504);
    const auto second=state.begin({1,2},5000,5000,projection,[]()->std::optional<UV>{return {};},500);
    assert(second && second->config.gaze.u==first->config.gaze.u && second->config.gaze.v==first->config.gaze.v);
    const auto moved=state.begin({1,3},5000,5000,projection,[]()->std::optional<UV>{return UV{.28f,.72f};},501);
    assert(moved && moved->config.gaze.u==.28f && moved->config.gaze.v==.72f);
    CameraPose pose{};
    assert(state.camera({1,3},0,pose) && state.camera({1,3},1,pose));
    assert(state.rectangle({1,3},0) && state.rectangle({1,3},1));
    assert(state.projection({1,3},0) && state.projection({1,3},1));
    assert(state.family({1,3},true,2));
    assert(!state.consume({1,3}));
    assert(state.scene({1,3},0,100) && state.scene({1,3},1,200));
    assert(!state.consume({1,3}));
    assert(state.foveal_rotation({1,3}) && state.consume({1,3}));
    state.retire();
    const auto restart=state.begin({2,1},5000,5000,projection,[]()->std::optional<UV>{return {};},502);
    assert(restart && restart->config.gaze.u==.5f && restart->config.gaze.v==.5f);
    s.eye_tracked=false;
    assert(state.configure(s));
    const auto fixed=state.begin({2,2},5000,5000,projection,[]()->std::optional<UV>{assert(false);return {};},503);
    assert(fixed && !fixed->config.foveal_camera.enabled);
    std::cout << "8100 gaze ray round-trips, compact 5000 startup, loss hold, immediate reacquisition and restart passed\n";
}
