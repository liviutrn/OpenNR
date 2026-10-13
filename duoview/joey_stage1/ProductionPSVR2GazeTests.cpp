#include "DuoViewPSVR2Gaze.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace uevr::duoview;
static void require(bool b,const char* msg){if(!b)throw std::runtime_error(msg);}
int main() try {
    psvr2::Status s{};s.size=sizeof(s);s.magic[0]='G';s.magic[1]='S';
    s.raw.combined_direction_valid=psvr2::Bool::yes;
    s.raw.combined_direction={0,0,1};
    auto straight=psvr2::calibrated_ray(s);
    require(straight && straight->right==0 && straight->up==0 && straight->forward==1,"straight CAPI ray");
    s.raw.combined_direction={-.25f,.25f,1};
    auto oblique=psvr2::calibrated_ray(s);
    require(oblique && oblique->right>0 && oblique->up>0,"native-to-Mono gaze coordinate mapping");
    s.raw.left.blink_valid=psvr2::Bool::yes;s.raw.left.blink=psvr2::Bool::yes;
    require(!psvr2::calibrated_ray(s),"blink invalidates");
    s.raw.left.blink=psvr2::Bool::no;s.raw.combined_direction={0,0,-1};
    require(!psvr2::calibrated_ray(s),"backward ray invalidates");
    s.raw.combined_direction={0,0,1};s.size=0;
    require(!psvr2::calibrated_ray(s),"invalid CAPI packet size");
    std::array<float,16> p{};p[0]=1;p[5]=1;p[11]=-1;
    auto c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.5f)<1e-5f && std::abs(c->v-.5f)<1e-5f,"forward mapped to center");
    auto r=psvr2::projection_uv({.5f,.5f,1},p);
    require(r && std::abs(r->u-.75f)<1e-5f && std::abs(r->v-.25f)<1e-5f,"right/up projection");
    p[8]=.2f;c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.4f)<1e-5f,"asymmetric Mono optical projection");
    p[11]=1;require(!psvr2::projection_uv({0,0,1},p),"unsupported negative-w projection fails closed");
    require(!psvr2::projection_uv({0,0,0},p),"invalid forward ray");
    std::cout<<"PSVR2 CAPI ABI, ray validity, blink, mapping and projection PASS\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
