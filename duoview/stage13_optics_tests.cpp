#include "joey_plugin/OpticalCalibration.hpp"
#include <cassert>
#include <cmath>
using namespace uevr::duoview;
int main() {
  const auto left_local=glm::angleAxis(glm::radians(-1.2f),glm::vec3(0,1,0));
  const auto right_local=glm::angleAxis(glm::radians(1.2f),glm::vec3(0,1,0));
  auto baseline=synchronized_left_eye_offset(left_local,right_local);
  assert(baseline);
  for(int yaw=-140;yaw<=140;yaw+=20) {
    const auto head=glm::angleAxis(glm::radians(float(yaw)),glm::normalize(glm::vec3(0,1.f,.2f)));
    const auto result=synchronized_left_eye_offset(head*left_local,head*right_local);
    assert(result);
    const auto ray0=glm::inverse(*baseline)*glm::vec3(0.f,0.f,-1.f);
    const auto ray1=glm::inverse(*result)*glm::vec3(0.f,0.f,-1.f);
    assert(glm::length(ray0-ray1)<1e-4f); // same gaze no head-motion drift
  }
  assert(!synchronized_left_eye_offset({0,0,0,0},right_local));
  const auto impossible=glm::angleAxis(glm::radians(35.f),glm::vec3(0,1,0));
  assert(!synchronized_left_eye_offset(left_local,impossible));
}
