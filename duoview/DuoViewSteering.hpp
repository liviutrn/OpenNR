#pragma once
#include "DuoViewGaze.hpp"
#include <array>
#include <cmath>
#include <optional>

namespace uevr::duoview {
struct Steering {
    bool active{};
    std::array<double,9> basis{1,0,0,0,1,0,0,0,1};
    std::array<float,12> full_to_local{};
};

/** Build a rigid gaze camera and its depth-independent image homography. */
inline std::optional<Steering> make_steering(
    const std::array<float,16>& projection,const Layout& layout,bool enabled) {
    Steering result{};
    if (!enabled) return result;
    for(float value:projection) if(!std::isfinite(value)) return {};
    if(projection[0]<=0.f || projection[5]<=0.f ||
       projection[11]!=1.f || projection[15]!=0.f ||
       projection[1]!=0.f || projection[4]!=0.f ||
       projection[3]!=0.f || projection[7]!=0.f ||
       projection[12]!=0.f || projection[13]!=0.f ||
       layout.crop_width<=0.f || layout.crop_height<=0.f) return {};
    const double u=(double(layout.u0)+layout.u1)*.5;
    const double v=(double(layout.v0)+layout.v1)*.5;
    const double x=(2.*u-1.-projection[8])/projection[0];
    const double y=(1.-2.*v-projection[9])/projection[5];
    const double length=std::sqrt(x*x+y*y+1.);
    const double right_length=std::sqrt(x*x+1.);
    const std::array<double,3> forward{x/length,y/length,1./length};
    const std::array<double,3> right{1./right_length,0.,-x/right_length};
    const std::array<double,3> up{
        forward[1]*right[2],
        forward[2]*right[0]-forward[0]*right[2],
        -forward[1]*right[0]};
    for(unsigned axis=0;axis<3;++axis) {
        result.basis[axis]=right[axis];
        result.basis[3+axis]=up[axis];
        result.basis[6+axis]=forward[axis];
    }
    const auto ray_coefficients=[&](const std::array<double,3>& row) {
        return std::array<double,3>{2.*row[0]/projection[0],
            -2.*row[1]/projection[5],
            row[2]-row[0]*(1.+projection[8])/projection[0]+
                row[1]*(1.-projection[9])/projection[5]};
    };
    const auto r=ray_coefficients(right),t=ray_coefficients(up),f=ray_coefficients(forward);
    for(unsigned axis=0;axis<3;++axis) {
        result.full_to_local[axis]=float(.5*f[axis]+.5*projection[0]/layout.crop_width*r[axis]);
        result.full_to_local[4+axis]=float(.5*f[axis]-.5*projection[5]/layout.crop_height*t[axis]);
        result.full_to_local[8+axis]=float(f[axis]);
    }
    for(float value:result.full_to_local) if(!std::isfinite(value)) return {};
    result.active=true;
    return result;
}

/** Project a full Mono image coordinate into the actual foveal source. */
inline std::optional<UV> steering_local(const Steering& steering,UV full) {
    std::array<double,3> homogeneous{};
    for(unsigned row=0;row<3;++row) {
        const auto i=row*4;
        homogeneous[row]=steering.full_to_local[i]*double(full.u)+
            steering.full_to_local[i+1]*double(full.v)+steering.full_to_local[i+2];
    }
    if(!std::isfinite(homogeneous[2]) || homogeneous[2]<=0.) return {};
    return UV{float(homogeneous[0]/homogeneous[2]),float(homogeneous[1]/homogeneous[2])};
}

/** Rotate about the same optical origin using Unreal pitch/yaw/roll conventions. */
template<typename Pose>
Pose steering_camera(const Pose& base,const Steering& steering) {
    if(!steering.active) return base;
    constexpr double radians=3.14159265358979323846/180.;
    const double pitch=base.rotation[0]*radians,yaw=base.rotation[1]*radians,
        roll=base.rotation[2]*radians;
    const double sp=std::sin(pitch),cp=std::cos(pitch),sy=std::sin(yaw),cy=std::cos(yaw),
        sr=std::sin(roll),cr=std::cos(roll);
    const std::array<double,3> forward{cp*cy,cp*sy,sp};
    const std::array<double,3> right{sr*sp*cy-cr*sy,sr*sp*sy+cr*cy,-sr*cp};
    const std::array<double,3> up{-cr*sp*cy-sr*sy,sr*cy-cr*sp*sy,cr*cp};
    const auto world_axis=[&](unsigned row) {
        std::array<double,3> out{};
        for(unsigned axis=0;axis<3;++axis)
            out[axis]=steering.basis[row*3]*right[axis]+
                steering.basis[row*3+1]*up[axis]+steering.basis[row*3+2]*forward[axis];
        return out;
    };
    const auto f=world_axis(2),r=world_axis(0),u=world_axis(1);
    Pose result=base;
    const double horizontal=std::hypot(f[0],f[1]);
    result.rotation[0]=std::atan2(f[2],horizontal)/radians;
    result.rotation[1]=(horizontal>1e-10 ? std::atan2(f[1],f[0]) : std::atan2(-r[0],r[1]))/radians;
    result.rotation[2]=horizontal>1e-10 ? std::atan2(-r[2],u[2])/radians : 0.;
    return result;
}

/** Keep the foveal principal point fixed; gaze is represented by camera rotation. */
template<typename Matrix>
void apply_steering_projection(Matrix& matrix,const Layout& layout) {
    matrix[0][0]/=layout.crop_width;
    matrix[1][1]/=layout.crop_height;
    matrix[2][0]=0.;
    matrix[2][1]=0.;
}
}
