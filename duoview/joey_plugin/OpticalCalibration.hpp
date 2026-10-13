#pragma once
// PSVR2 Toolkit gaze is HMD-relative, NOT world/stage space.
// Compute an optical offset from two synchronized xrLocateViews eye
// orientations. Never read the possibly stale UEVR HMD pipeline pose.
#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>
#include <optional>
#include <cmath>
namespace uevr::duoview {
inline std::optional<glm::quat> synchronized_left_eye_offset(glm::quat left, glm::quat right) {
    const auto valid=[](const glm::quat& q) {
        return std::isfinite(q.w) && std::isfinite(q.x) &&
               std::isfinite(q.y) && std::isfinite(q.z) &&
               std::abs(glm::length(q)-1.f)<.01f;
    };
    if(!valid(left)||!valid(right)) return {};
    left=glm::normalize(left);right=glm::normalize(right);
    if (glm::dot(left,right)<0.f) right=-right;
    const glm::quat relative=glm::normalize(glm::inverse(left)*right);
    // Grossly different eye rotations cannot form a reliable cyclopean HMD
    // basis and should not control foveated cropping.
    if(glm::angle(relative)>glm::radians(20.f)) return {};
    const glm::quat center=glm::normalize(glm::slerp(left,right,.5f));
    return glm::normalize(glm::inverse(center)*left);
}
} // namespace uevr::duoview
