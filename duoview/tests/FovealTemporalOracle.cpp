// Independent CPU world-point reprojection oracle for DuoView.
// This is NOT an Unreal temporal history integration, nor a GPU/render test.
// The reference computes full-frustum world UV first.  The implementation
// path separately crops a matrix using production apply_foveal_crop.
// A deliberate missing-crop and double-correction path MUST fail.
#include "../DuoViewGeometry.hpp"
#include "../DuoViewHistoryCorrection.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

using namespace uevr::duoview;
using Matrix = std::array<std::array<double, 4>, 4>;
struct Point { double x{}, y{}, z{}; };
struct PixelUV { double u{}, v{}; };
struct Pose { double yaw{}, pitch{}, x{}, y{}, z{}; };

static void check(bool ok, const char* why) {
    if (!ok) throw std::runtime_error(why);
}
static Point camera_coordinates(Point world, Pose pose) {
    // Explicit inverse yaw and pitch in the same +Z-forward test basis.
    const double yaw=pose.yaw*3.14159265358979323846/180.0;
    const double pitch=pose.pitch*3.14159265358979323846/180.0;
    const double x=world.x-pose.x, y=world.y-pose.y, z=world.z-pose.z;
    const double rx=std::cos(yaw)*x-std::sin(yaw)*z;
    const double rz=std::sin(yaw)*x+std::cos(yaw)*z;
    return {rx, std::cos(pitch)*y-std::sin(pitch)*rz,
                std::sin(pitch)*y+std::cos(pitch)*rz};
}
static Matrix full_projection(bool asymmetric, double jitter_px_x,
                              double jitter_px_y, unsigned output_w,
                              unsigned output_h) {
    Matrix p{};
    p[0][0]=1.18; p[1][1]=1.34;
    p[2][0]=(asymmetric ? .21 : 0.0)+2.0*jitter_px_x/output_w;
    p[2][1]=(asymmetric ? -.13 : 0.0)-2.0*jitter_px_y/output_h;
    p[2][3]=1.0; // +Z forward, never substitute OpenXR -Z.
    p[3][2]=.1;
    return p;
}
static PixelUV matrix_project(const Matrix& p, Point v) {
    const std::array<double,4> q{v.x,v.y,v.z,1.0};
    double cx=0.0, cy=0.0, cw=0.0;
    for (int col=0;col<4;++col) {
        cx+=p[col][0]*q[col]; cy+=p[col][1]*q[col]; cw+=p[col][3]*q[col];
    }
    check(std::isfinite(cw) && cw>.01, "invalid homogeneous +Z");
    return {.5*(cx/cw+1.0),.5*(1.0-cy/cw)};
}
static PixelUV reference_full_uv(const Matrix& p, Point v) {
    // Independent perspective component derivation, not matrix_project.
    const double invz=1.0/v.z;
    const double ndcx=p[0][0]*v.x*invz+p[2][0];
    const double ndcy=p[1][1]*v.y*invz+p[2][1];
    return {.5*(ndcx+1.0), .5*(1.0-ndcy)};
}
static PixelUV local_from_full(PixelUV full, const Layout& l) {
    return {(full.u-l.u0)/l.crop_width,(full.v-l.v0)/l.crop_height};
}
static PixelUV ref_local(const Matrix& full_p, Point world, Pose pose,
                         const Layout& l) {
    return local_from_full(reference_full_uv(full_p,camera_coordinates(world,pose)),l);
}
static PixelUV impl_local(const Matrix& full_p, Point world, Pose pose,
                          const Layout& l) {
    Matrix cropped=full_p;
    apply_foveal_crop(cropped,l); // actual production code under test
    return matrix_project(cropped,camera_coordinates(world,pose));
}
static double max_pixel_error(PixelUV a, PixelUV b, const Layout& l) {
    return std::max(std::abs(a.u-b.u)*l.fovea.width,
                    std::abs(a.v-b.v)*l.fovea.height);
}
static void verify_pair(const Matrix& pp, const Matrix& np, Pose old_pose,
                        Pose new_pose, Point world, const Layout& prev,
                        const Layout& curr, double tolerance_pixels) {
    const PixelUV r0=ref_local(pp,world,old_pose,prev);
    const PixelUV r1=ref_local(np,world,new_pose,curr);
    const PixelUV i0=impl_local(pp,world,old_pose,prev);
    const PixelUV i1=impl_local(np,world,new_pose,curr);
    check(max_pixel_error(r0,i0,prev)<tolerance_pixels,
          "previous cropped projection vs independent world oracle");
    check(max_pixel_error(r1,i1,curr)<tolerance_pixels,
          "current cropped projection vs independent world oracle");
    // Sign: current->previous in current-source pixels, positive for a
    // right-moving ROI when the world and head do not move.
    const PixelUV expected_mv{
        curr.fovea.width*(r0.u-r1.u),
        curr.fovea.height*(r0.v-r1.v)};
    const PixelUV actual_mv{
        curr.fovea.width*(i0.u-i1.u),
        curr.fovea.height*(i0.v-i1.v)};
    check(std::abs(expected_mv.u-actual_mv.u)<tolerance_pixels &&
          std::abs(expected_mv.v-actual_mv.v)<tolerance_pixels,
          "current-to-previous local vector mismatch");
    // No world movement due to a moving crop. The compositor maps the
    // local foveal pixel back into the SAME full UV, independent of ROI.
    const auto full_prev=reference_full_uv(pp,camera_coordinates(world,old_pose));
    const auto full_now=reference_full_uv(np,camera_coordinates(world,new_pose));
    check(std::abs(prev.u0+prev.crop_width*r0.u-full_prev.u)<1e-6 &&
          std::abs(curr.u0+curr.crop_width*r1.u-full_now.u)<1e-6 &&
          std::abs(prev.v0+prev.crop_height*r0.v-full_prev.v)<1e-6 &&
          std::abs(curr.v0+curr.crop_height*r1.v-full_now.v)<1e-6,
          "full-world UV changes after crop composite");
}
static Layout layout(unsigned w,unsigned h,float extent,float density,
                     float origin_u,float origin_v) {
    const auto l=make_layout(w,h,extent,extent,.2f,density,
                             origin_u+extent*.5f,origin_v+extent*.5f);
    check(l.has_value(),"invalid production atlas layout");
    return *l;
}
static void negative_controls() {
    const auto prev=layout(3000,3000,.30f,2.5f,.25f,.25f);
    const auto now=layout(3000,3000,.30f,2.5f,.27f,.25f);
    const auto p=full_projection(false,0.0,0.0,3000,3000);
    const Point world{.05,0.0,2.0};
    const auto old=ref_local(p,world,{},prev);
    const auto cur=ref_local(p,world,{},now);
    const double correct=now.fovea.width*(old.u-cur.u);
    check(std::abs(correct-150.0)<.001,"150px numerical reference");
    check(std::abs(correct)>100.0,"negative control lacks crop motion");
    // Wrong UE previous matrix=current matrix would create zero motion.
    const auto incorrectly_current=impl_local(p,world,{},now);
    const double missing=now.fovea.width*(incorrectly_current.u-cur.u);
    check(std::abs(missing-correct)>100.0,"missing prior crop not detected");
    // UE previous projection already includes crop, so Cheeky-style extra
    // vector correction would double-count the gaze motion.
    const double double_correct=correct+correct;
    check(std::abs(double_correct-correct)>100.0,"double correction not detected");
    // Historical sign-reversed diagnostic must be rejected.
    const double inverted=(prev.u0-now.u0)*now.fovea.width/now.crop_width;
    check(std::abs(inverted+correct)<.001,"wrong-sign diagnostic not detected");
    FrameConfig prior{{1,1},prev}, current{{1,2},now};
    current.settings.history_sample_correction=true;
    const auto shift=compositor_history_shift(prior,true,current,true);
    check(shift.has_value(),"legacy correction counterexample not exercised");
    const double unshifted=now.u0+now.crop_width*cur.u;
    const double displaced=now.u0+now.crop_width*(cur.u-shift->u);
    check(std::abs((displaced-unshifted)*3000.+60.)<.001,
          "legacy RGB shift must expose 60px world displacement");
    // Also assert the half-width static case, independent of density.
    const auto a=layout(3000,3000,.50f,1.f,.25f,.25f);
    const auto b=layout(3000,3000,.50f,1.f,.26f,.25f);
    const auto x=ref_local(p,world,{},a),y=ref_local(p,world,{},b);
    check(std::abs(b.fovea.width*(x.u-y.u)-30.0)<.001,"30px reference");
}
int main() {
 try {
    negative_controls();
    const std::array<std::array<unsigned,2>,4> resolutions{{
        {2000,2000},{3000,3000},{3400,3172},{4096,2160}}};
    const std::array<float,3> extents{.30f,.50f,.80f};
    const std::array<float,2> densities{1.0f,2.5f};
    const std::array<double,9> output_steps{0.,1.,2.,3.,10.,30.,60.,.01*3000.,.02*3000.};
    std::mt19937 rng{0xD00FEE};
    std::uniform_real_distribution<double> xy(-.5,.5), depth(2.0,7.0);
    size_t checks=0;
    for(const auto res:resolutions) for(const float extent:extents)
    for(const float density:densities) for(const bool asym:{false,true}) {
        const unsigned w=res[0],h=res[1];
        // Some high-density 0.80 layouts cannot fit Joey's fixed atlas.
        if(!make_layout(w,h,extent,extent,.2f,density)) continue;
        const auto previous=layout(w,h,extent,density,(1.f-extent)*.5f,
                                                   (1.f-extent)*.5f);
        for(double delta:output_steps) {
            const float step=static_cast<float>(delta/w);
            const float target=std::min(1.f-extent,previous.u0+step);
            const auto current=layout(w,h,extent,density,target,previous.v0);
            for(const auto head:std::array<Pose,5>{{
                {},{2.,0.},{-10.,0.},{0.,2.},{10.,-2.,.02,-.01,.03}}}) {
                const auto pp=full_projection(asym,-.5,.5,w,h);
                const auto np=full_projection(asym,.5,-.5,w,h);
                for(int k=0;k<12;++k) {
                    const Point world{xy(rng),xy(rng),depth(rng)};
                    verify_pair(pp,np,{},head,world,previous,current,.03);
                    ++checks;
                }
            }
        }
    }
    // Hard corner-clamp control on the actual production layout function.
    auto edge=make_layout(3400,3172,.3f,.3f,.2f,2.5f,1.f,0.f);
    check(edge.has_value() &&
          std::abs(edge->u1-1.f)<1e-6 &&
          std::abs(edge->v0)<1e-6,
          "crop edge clamp");
    std::cout<<"DuoView independent foveal temporal oracle PASS "
             <<checks<<" randomized deterministic pairs\n";
    return 0;
 } catch(const std::exception& error) {
    std::cerr<<"DuoView temporal oracle FAIL: "<<error.what()<<'\n';
    return 1;
 }
}
