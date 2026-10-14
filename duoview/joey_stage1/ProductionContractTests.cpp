#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "DuoViewState.hpp"

using namespace uevr::duoview;
static void require(bool test, const char* what) {
    if (!test) throw std::runtime_error(what);
}
int main() try {
    for (auto wh: {std::array{2000u,2000u},std::array{3000u,3000u},
                   std::array{3400u,3172u},std::array{4096u,2160u}}) {
        const auto l=make_layout(wh[0],wh[1],.30f,.30f,.25f,2.5f,.5f,.5f);
        require(l.has_value(), "Pinned fixed-center geometry not admitted");
        require(layout_valid(*l), "Pinned geometry not valid");
        require(l->periphery.x == 0 && l->periphery.y == 0,
                "Primary FULL-FOV peripheral view MUST occupy the beginning of atlas");
        require(l->fovea.x == l->periphery.width && l->fovea.y == 0,
                "Second focused view must not overwrite primary view");
        require(l->fovea.x + l->fovea.width <= l->atlas_width &&
                l->periphery.width <= wh[0] && l->atlas_width == wh[0]*2,
                "Atlas bounds or original double-wide XR allocation changed");
        require(std::abs(l->u0 - .35f) < 1e-5f && std::abs(l->u1 - .65f) < 1e-5f,
                "Off-axis fovea projection no longer center cropped");
        const double ratio=static_cast<double>(rendered_pixels(*l))/(wh[0]*static_cast<double>(wh[1]));
        require(ratio>.622 && ratio<.628,
                "Unexpected rendered-pixel budget; two UE views may overdraw baseline");
        const Tans full{-1.8f, .92f, 1.3f, -1.3f};
        const auto crop=foveal_frustum(full,*l);
        require(crop && crop->left > full.left && crop->right < full.right &&
                crop->top < full.top && crop->bottom > full.bottom,
                "Fovea must have distinct off-axis smaller frustum in shared Mono basis");
    }
    State state;
    Settings settings{};
    settings.crop_width=.30f;
    settings.crop_height=.30f;
    settings.peripheral_scale=.25f;
    settings.foveal_density=2.5f;
    settings.feather_fraction=.08f;
    settings.eye_tracked=false;
    settings.fovea_view=1;
    require(state.configure(settings),"Fixed-center configuration rejected");
    settings.diagnostic_view=3;
    require(!state.configure(settings),"Invalid diagnostic accepted");
    settings.diagnostic_view=1;
    require(state.configure(settings),"Peripheral-only diagnostic unavailable");
    settings.diagnostic_view=2;
    require(state.configure(settings),"Fovea-only diagnostic unavailable");
    settings.diagnostic_view=0;
    require(state.configure(settings),"Composite diagnostic restore failed");
    settings.crop_width=.95f; settings.foveal_density=4.f;
    require(!state.configure(settings),"Oversized atlas accepted");
    settings.crop_width=.30f; settings.foveal_density=2.5f;
    require(state.configure(settings),"Valid atlas was not restored");
    FrameKey key{4,100};
    std::array<float,16> m{};m[0]=m[5]=m[10]=m[15]=1.0f;
    auto snap=state.begin(key,3000,3000,m,[]()->std::optional<UV>{return UV{.5f,.5f};});
    require(snap && !snap->gaze_valid, "Unexpected gaze sampling in fixed-center Stage 2-4");
    const CameraPose camera{{1.,2.,3.},{10.,20.,30.}};
    require(state.rectangle(key,0) && state.projection(key,0) && state.camera(key,0,camera),
            "Peripheral producer observations rejected");
    require(!state.consume(key),"Single view must not masquerade as paired compositor source");
    require(state.family(key,true,2),"Main 2-view family not recognized");
    require(!state.consume(key),"Missing foveal view must prohibit composition");
    require(state.rectangle(key,1) && state.projection(key,1) && state.camera(key,1,camera),
            "Second same-pose view observations rejected");
    require(!state.consume({4,101}),"Wrong engine frame must not compose");
    require(!state.consume({3,100}),"Wrong renderer generation must not compose");
    require(state.consume(key).has_value(),"Current coherent pair rejected");
    require(!state.consume(key),"Double submission of a frame must be rejected");
    state.retire();
    require(!state.consume(key),"Invalidated pair must not survive reset");
    require(state.begin({5,1},3000,3000,m,[]()->std::optional<UV>{return UV{.5f,.5f};}).has_value(),
            "New generation after reset must be supported");
    std::cout<<"Pinned Joey DuoView geometry, view pairing, generation, primary fallback contract PASS\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"DuoView contract test failure: "<<e.what()<<"\n";
    return 1;
}
