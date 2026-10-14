#include "../DuoViewState.hpp"
#include <iostream>
#include <random>
#include <stdexcept>

using namespace uevr::duoview;
using V=std::array<double,3>;
using Q=std::array<double,4>;
static void check(bool value,const char* message) { if(!value) throw std::runtime_error(message); }
static Q product(Q a,Q b) {
    return {a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1],
        a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0],
        a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3],
        a[3]*b[3]-a[0]*b[0]-a[1]*b[1]-a[2]*b[2]};
}
static Q rotation(const CameraPose& camera) {
    constexpr double half_radians=3.14159265358979323846/360.;
    const auto p=camera.rotation[0]*half_radians,y=camera.rotation[1]*half_radians,
        r=camera.rotation[2]*half_radians;
    return product(product(Q{0,0,std::sin(y),std::cos(y)},
        Q{0,-std::sin(p),0,std::cos(p)}),Q{-std::sin(r),0,0,std::cos(r)});
}
static V rotate(Q q,V v) {
    const auto out=product(product(q,Q{v[0],v[1],v[2],0}),Q{-q[0],-q[1],-q[2],q[3]});
    return {out[0],out[1],out[2]};
}
static double distance(V a,V b) {
    return std::hypot(std::hypot(a[0]-b[0],a[1]-b[1]),a[2]-b[2]);
}
static void check_camera(CameraPose base,const Steering& steering) {
    const auto rendered=steering_camera(base,steering);
    check(rendered.position==base.position,"Gaze camera changed the optical origin");
    const auto before=rotation(base),after=rotation(rendered);
    for(unsigned row=0;row<3;++row) {
        const V mono{steering.basis[row*3],steering.basis[row*3+1],steering.basis[row*3+2]};
        const auto expected=rotate(before,{mono[2],mono[0],mono[1]});
        const V canonical=row==0 ? V{0,1,0} : row==1 ? V{0,0,1} : V{1,0,0};
        check(distance(expected,rotate(after,canonical))<1e-8,"Unreal Euler pose differs from independent quaternion oracle");
    }
}
int main() try {
    std::array<float,16> projection{};
    projection[0]=.78f;projection[5]=.82f;projection[11]=1;projection[14]=.1f;
    std::mt19937 generator{0x51EE43};
    std::uniform_real_distribution<float> uv(0.f,1.f),asym(-.25f,.25f);
    std::uniform_real_distribution<double> angle(-180.,180.),pitch(-90.,90.);
    unsigned count{};
    for(float extent:{.1f,.3f,.5f,.8f,1.f}) for(unsigned iteration=0;iteration<4000;++iteration) {
        projection[8]=asym(generator);projection[9]=asym(generator);
        const auto layout=make_layout(3000,3000,extent,extent,.2f,1.f,uv(generator),uv(generator));
        check(layout.has_value(),"Invalid oracle layout");
        const auto steering=make_steering(projection,*layout,true);
        check(steering.has_value(),"Steering rejected valid perspective");
        const UV center{(layout->u0+layout->u1)*.5f,(layout->v0+layout->v1)*.5f};
        const auto center_local=steering_local(*steering,center);
        check(center_local && std::abs(center_local->u-.5f)<2e-5f &&
            std::abs(center_local->v-.5f)<2e-5f,"Gaze is not at actual high-resolution center");
        const UV target{uv(generator),uv(generator)};
        const V full_ray{(2.*target.u-1.-projection[8])/projection[0],
            (1.-2.*target.v-projection[9])/projection[5],1.};
        std::array<double,3> camera_ray{};
        for(unsigned row=0;row<3;++row) for(unsigned axis=0;axis<3;++axis)
            camera_ray[row]+=steering->basis[row*3+axis]*full_ray[axis];
        const auto local=steering_local(*steering,target);
        if(camera_ray[2]>.1) {
            const double expected_u=.5+.5*projection[0]/extent*camera_ray[0]/camera_ray[2];
            const double expected_v=.5-.5*projection[5]/extent*camera_ray[1]/camera_ray[2];
            check(local && std::abs(local->u-expected_u)<2e-4 &&
                std::abs(local->v-expected_v)<2e-4,"Homography moved world detail relative to real camera projection");
        }
        check_camera({{pitch(generator),angle(generator),angle(generator)},{10,20,30}},*steering);
        check_camera({{90.,angle(generator),angle(generator)},{10,20,30}},*steering);
        check_camera({{-90.,angle(generator),angle(generator)},{10,20,30}},*steering);
        ++count;
    }
    const auto centered=*make_layout(3000,3000,.3f,.3f,.2f,1.f);
    projection[8]=projection[9]=0;
    const auto identity=*make_steering(projection,centered,true);
    check_camera({{90.,30.,20.},{1,2,3}},identity);
    check_camera({{-90.,-30.,-20.},{1,2,3}},identity);
    V world_target{1.,.1,.05};
    const double target_length=std::hypot(std::hypot(world_target[0],world_target[1]),world_target[2]);
    for(auto& component:world_target) component/=target_length;
    for(double head_yaw:{-10.,-2.,0.,2.,10.}) for(double head_pitch:{-10.,0.,10.}) {
        const CameraPose head{{head_pitch,head_yaw,7.},{10.,20.,30.}};
        const auto q=rotation(head);
        const auto local=rotate({-q[0],-q[1],-q[2],q[3]},world_target);
        const float gaze_u=float(.5+.5*projection[0]*local[1]/local[0]);
        const float gaze_v=float(.5-.5*projection[5]*local[2]/local[0]);
        const auto roi=*make_layout(3000,3000,.3f,.3f,.2f,1.f,gaze_u,gaze_v);
        const auto steering=*make_steering(projection,roi,true);
        const auto rendered=steering_camera(head,steering);
        check(distance(rotate(rotation(rendered),{1,0,0}),world_target)<2e-6,
            "Head turns during world fixation moved the real foveal camera away from target");
    }
    const CameraPose fixed{{12.,34.,56.},{1.,2.,3.}};
    check(steering_camera(fixed,*make_steering(projection,centered,false))==fixed,
        "Disabled eye tracking modified the fixed-center camera");
    for(unsigned fovea_view=0;fovea_view<2;++fovea_view) {
        State state;Settings settings;settings.fovea_view=fovea_view;
        check(state.configure(settings),"View selector settings failed");
        const auto frame=state.begin({43,1},3000,3000,projection,
            []()->std::optional<UV>{return UV{.65f,.35f};});
        check(frame.has_value(),"Steered source frame missing");
        const CameraPose base{{10,20,30},{100,200,300}};
        check(state.camera({43,1},0,base),"Base mono camera rejected");
        const auto first=state.camera({43,1},0),second=state.camera({43,1},1);
        check(first && second && first->position==second->position,"Source pair lost common optical origin");
        check(state.camera({43,1},1,*second),"Actual second source pose rejected");
        check((fovea_view==0 ? second->rotation : first->rotation)==base.rotation,
            "Peripheral camera was steered");
        check(first->rotation!=second->rotation,"Foveal camera did not move with gaze");
    }
    std::cout<<"Gaze camera/homography independent quaternion oracle PASS "<<count<<" cases\n";
} catch(const std::exception& error) {
    std::cerr<<error.what()<<'\n';return 1;
}
