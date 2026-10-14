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
    require(!baseline.observation().seen, "Gaze observation cannot exist before CAPI reads");
    psvr2::Status s{};s.size=sizeof(s);s.magic[0]='G';s.magic[1]='S';
    s.raw.frame_counter=123456u; s.raw.timestamp=9876543210123ll;
    psvr2::SampleSequence first_consumer,second_consumer;
    require(first_consumer.observe(s) && !first_consumer.observe(s),
            "Same CAPI payload must not renew sample freshness");
    require(second_consumer.observe(s),
            "Another CAPI consumer must not steal this reader's fresh sample");
    auto next=s;next.raw.frame_counter++;next.raw.timestamp+=8333;
    require(first_consumer.observe(next) && second_consumer.observe(next),
            "Both readers must accept a new payload even when CAPI notification was already consumed");
    next.raw.timestamp+=8333;
    require(first_consumer.observe(next),"Timestamp change must detect a new sensor packet independently");
    next.raw.frame_counter++;
    require(first_consumer.observe(next),"Counter change must detect a new sensor packet independently");
    auto malformed=next;malformed.size=0;
    require(!first_consumer.observe(malformed) && !first_consumer.observe(next),
            "Malformed packet cannot reset the last accepted packet identity");
    next.raw.timestamp=0;next.raw.frame_counter=0;
    require(first_consumer.observe(next) && !first_consumer.observe(next),
            "Sensor restart must be detected without accepting repeated packets as fresh");
    const auto observation=psvr2::describe_gaze_sample(s,5500123ull,true);
    require(observation.seen && observation.valid &&
            observation.device_frame_counter==123456u &&
            observation.device_timestamp_raw==9876543210123ll &&
            observation.host_arrival_ms==5500123ull,
            "Raw sensor metadata must be preserved, not converted to XR clock");
    const auto bad_sample=psvr2::describe_gaze_sample(s,5500124ull,false);
    require(bad_sample.seen && !bad_sample.valid,
            "Invalid new CAPI frames must still be visible to gated diagnostics");
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
    std::array<float,16> p{};p[0]=1;p[5]=1;p[11]=1;
    auto c=psvr2::projection_uv({0,0,1},p);
    require(c && std::abs(c->u-.5f)<1e-5f && std::abs(c->v-.5f)<1e-5f,"forward mapped to center");
    auto r=psvr2::projection_uv({.5f,.5f,1},p);
    require(r && std::abs(r->u-.75f)<1e-5f && std::abs(r->v-.25f)<1e-5f,"right/up projection");
    const float angle=.2f, cosine=std::cos(angle), sine=std::sin(angle);
    const auto optical=optical_ray({0,0,1},{cosine,0,-sine,0,1,0,sine,0,cosine});
    require(optical.has_value(),"left optical yaw produces a forward ray");
    const auto corrected=psvr2::projection_uv(*optical,p);
    require(corrected && std::abs(corrected->u-(.5f+.5f*std::tan(angle)))<1e-5f,
            "native calibrated gaze is projected after inverse optical yaw");
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
