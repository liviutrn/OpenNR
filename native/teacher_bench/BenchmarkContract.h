#pragma once
#include "Runtime.h"
#include "Utils/ExternalOutput.h"
#include <filesystem>
#include <stdexcept>

inline NeuralRendering::Feature18GuideContract MakeBenchmarkGuide(
    unsigned inputWidth, unsigned inputHeight, unsigned outputWidth, unsigned outputHeight,
    unsigned guideWidth, unsigned guideHeight, float motionX, float motionY)
{
    NeuralRendering::Feature18GuideContract guide{};
    guide.colorWidth = inputWidth;
    guide.colorHeight = inputHeight;
    guide.depthWidth = guide.motionWidth = guideWidth;
    guide.depthHeight = guide.motionHeight = guideHeight;
    guide.outputWidth = outputWidth;
    guide.outputHeight = outputHeight;
    guide.motionVectorScaleX = motionX;
    guide.motionVectorScaleY = motionY;
    guide.motionVectorsLowResolution = guideWidth <= inputWidth && guideHeight <= inputHeight;
    if (!guide.IsValid())
        throw std::invalid_argument("Feature 18 guide dimensions must be nonzero");
    return guide;
}

inline std::filesystem::path CheckedBenchmarkOutput(const std::filesystem::path& path)
{
    return OpenNRStorage::ResolveExternalOutput(path);
}
