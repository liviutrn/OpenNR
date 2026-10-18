#include "DuoViewPSVR2Gaze.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace uevr::duoview;
static void require(bool b,const char* msg){if(!b)throw std::runtime_error(msg);}
int main() try {
    const psvr2::Reader baseline{};
    auto stats=baseline.counters();
    require(!stats.fresh && !stats.reused && !stats.invalid &&
            !stats.expired && !stats.unavailable,
            "Gaze counters must remain zero until DuoView renders");
    psvr2::Status s{};s.size=sizeof(s);s.magic[0]='G';s.magic[1]='S';
    s.raw.combined_direction_valid=psvr2::Bool::yes;
    s.raw.combined_direction={0,0,1};
    auto straight=psvr2::calibrated_ray(s);
    require(straight && straight->right==0 && straight->up==0 && straight->forward==1,"straight CAPI ray");
    s.raw.combined_direction={-.25f,.25f,1};
    auto oblique=psvr2::calibrated_ray(s);
    require(oblique && oblique->right>0 && oblique->up>0,"native-to-Mono gaze coordinate mapping");
    s.raw.left.blink_valid=psvr2::Bool::yes;s.raw.left.blink=psvr2::Bool::yes;
    require(!psvr2::calibrated_ray(s),"blink invalidates ray");
    require(psvr2::is_blink(s),"blink packet reads as eyes-closed, not tracking lost");
    s.raw.left.blink=psvr2::Bool::no;
    require(!psvr2::is_blink(s),"open-eyes packet is not a blink");
    s.raw.combined_direction={0,0,-1};
    require(!psvr2::calibrated_ray(s),"backward ray invalidates");
    s.raw.combined_direction={0,0,1};s.size=0;
    require(!psvr2::calibrated_ray(s),"invalid CAPI packet size");
    std::array<float,16> p{};p[0]=1;p[5]=1;p[11]=1;
    auto c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.5f)<1e-5f && std::abs(c->v-.5f)<1e-5f,"forward mapped to center");
    auto r=psvr2::projection_uv({.5f,.5f,1},p);
    require(r && std::abs(r->u-.75f)<1e-5f && std::abs(r->v-.25f)<1e-5f,"right/up projection");
    // Regression (v23 Build29/32 headset trembling): the HMD-local calibrated ray
    // projects directly with no inverse head/eye rotation. Joey's Mono camera
    // is rotation-locked to the HMD, so the old inverse eye-in-stage rotation
    // made the foveal crop swim at twice the head rate during head motion.
    s.raw.left.blink=psvr2::Bool::no;s.size=sizeof(s);s.raw.combined_direction={-.25f,.25f,1};
    const auto oblique_ray=psvr2::calibrated_ray(s);
    require(oblique_ray.has_value(),"oblique CAPI ray for direct projection");
    const auto direct=psvr2::projection_uv(*oblique_ray,p);
    require(direct && std::abs(direct->u-.625f)<1e-5f && std::abs(direct->v-.375f)<1e-5f,
            "HMD-local gaze ray projects with no head/eye rotation applied");
    // Joey uses GLM column-major [column][row] storage and +Z-forward Mono.
    // x_clip=p[0]*right+p[8]*forward, w_clip=p[11]*forward:
    // +0.2 shifts the optical center to U=0.6; -0.2 shifts it to U=0.4.
    p[8]=.2f;c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.6f)<1e-5f,"positive asymmetric Mono projection");
    p[8]=-.2f;c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.4f)<1e-5f,"negative asymmetric Mono projection");
    p[8]=.2f;p[9]=.1f;c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.6f)<1e-5f &&
        std::abs(c->v-.45f)<1e-5f,"combined horizontal/vertical optical offset");
    r=psvr2::projection_uv({.5f,-.25f,1},p);
    require(r && std::abs(r->u-.85f)<1e-5f &&
        std::abs(r->v-.575f)<1e-5f,"off-axis ray with offset optical center");
    p[11]=-1;require(!psvr2::projection_uv({0,0,1},p),"unsupported negative-w projection fails closed");
    require(!psvr2::projection_uv({0,0,0},p),"invalid forward ray");
    std::cout<<"PSVR2 CAPI ABI, ray validity, blink, mapping and projection PASS\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
