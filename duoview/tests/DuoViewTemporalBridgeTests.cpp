// Deterministic proof for the v46 UE previous-clip bridge.
// This models the public FSceneView contract without requiring Unreal headers:
// ClipToPrevClipOverride must map current cropped clip coordinates to previous
// cropped clip coordinates, including both head motion and ROI motion.
#include "../DuoViewTemporalMath.hpp"
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace uevr::duoview;
using namespace uevr::duoview::temporal;

static void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

static RawMatrix4d raw_matrix(const Matrix4d& matrix) {
    return store_raw(matrix);
}

static Matrix4d projection() {
    Matrix4d result{};
    result.m[0][0]=1.27;
    result.m[1][1]=1.41;
    result.m[2][0]=.11;
    result.m[2][1]=-.08;
    result.m[2][2]=.23;
    result.m[2][3]=1.0;
    result.m[3][2]=.10;
    return result;
}

static Matrix4d rotation_z(double radians) {
    Matrix4d result=identity();
    const double c=std::cos(radians), s=std::sin(radians);
    result.m[0][0]=c; result.m[0][1]=-s;
    result.m[1][0]=s; result.m[1][1]=c;
    return result;
}

static ViewInput input(const Layout& layout, const std::array<double,3>& origin,
                       const Matrix4d& view_rotation, const Matrix4d& full_projection) {
    ViewInput result{};
    const auto projection_raw=raw_matrix(full_projection);
    for (size_t i=0; i<projection_raw.size(); ++i)
        result.projection[i]=static_cast<float>(projection_raw[i]);
    result.layout=layout;
    result.fovea_view=0;
    result.origin=origin;
    result.view_rotation=raw_matrix(view_rotation);
    result.valid=true;
    return result;
}

static std::array<double,3> normalized(const std::array<double,4>& value) {
    check(std::isfinite(value[3]) && std::abs(value[3])>1.0e-9,
          "homogeneous point has invalid W");
    return {value[0]/value[3],value[1]/value[3],value[2]/value[3]};
}

static double distance(const std::array<double,3>& a,
                       const std::array<double,3>& b) {
    return std::max({std::abs(a[0]-b[0]),std::abs(a[1]-b[1]),std::abs(a[2]-b[2])});
}

int main() {
    try {
        const auto previous_layout=*make_layout(3000,3000,.50f,.50f,.20f,1.0f,.50f,.50f);
        const auto current_layout=*make_layout(3000,3000,.50f,.50f,.20f,1.0f,.62f,.44f);
        const auto full_projection=projection();
        const auto previous=input(previous_layout,{0.0,0.0,0.0},rotation_z(.00),full_projection);
        const auto current=input(current_layout,{.035,-.018,.11},rotation_z(.035),full_projection);

        const auto override_raw=make_clip_to_prev_clip(previous,current,0);
        check(override_raw.has_value(),"valid cropped view pair rejected");
        const auto current_q=view_projection_for_view(current,0);
        const auto previous_q=view_projection_for_view(previous,0);
        const auto override_q=load_raw(*override_raw);

        // This is the defining UE row-vector contract:
        // world * current_Q * ClipToPrevClip == world * previous_Q.
        for (const std::array<double,4> world : {
                 std::array<double,4>{-.45,.20,2.1,1.0},
                 std::array<double,4>{.10,-.35,3.7,1.0},
                 std::array<double,4>{.63,.42,5.2,1.0}}) {
            const auto through_override=normalized(
                transform_row(transform_row(world,current_q),override_q));
            const auto direct_previous=normalized(transform_row(world,previous_q));
            check(distance(through_override,direct_previous)<2.0e-5,
                  "current cropped clip does not map to previous cropped clip");
        }

        // A guessed identity/"same current crop" history leaves the moving
        // ROI in the wrong place. This is the failure that v46 must prevent.
        const auto current_identity=identity();
        const auto wrong=normalized(transform_row(
            transform_row({.10,-.35,3.7,1.0},current_q),current_identity));
        const auto expected=normalized(transform_row({.10,-.35,3.7,1.0},previous_q));
        check(distance(wrong,expected)>.02,
              "negative control did not expose a missing previous crop");

        // A singular source projection is rejected instead of writing an
        // unvalidated matrix into UE's view object.
        auto singular=current;
        singular.projection.fill(0.0f);
        check(!make_clip_to_prev_clip(previous,singular,0).has_value(),
              "singular view projection was not rejected");

        // The override is view-specific and must not be synthesized for an
        // invalid source index.
        check(!make_clip_to_prev_clip(previous,current,2).has_value(),
              "invalid source view index was accepted");

        std::cout << "DuoView v46 temporal bridge matrix contract PASS\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "DuoView v46 temporal bridge matrix contract FAIL: "
                  << error.what() << '\n';
        return 1;
    }
}
