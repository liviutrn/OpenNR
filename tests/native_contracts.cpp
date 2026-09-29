#include "BenchmarkContract.h"
#include <cassert>
#include <iostream>

int main()
{
    const auto guide = MakeBenchmarkGuide(128, 96, 256, 192, 64, 48, -2.0f, 3.0f);
    assert(guide.colorWidth == 128 && guide.outputWidth == 256);
    assert(guide.depthWidth == 64 && guide.motionHeight == 48);
    assert(guide.motionVectorsLowResolution && guide.motionVectorScaleX == -2.0f);
    assert(guide.colorBaseX == 0 && guide.motionBaseX == 0);
    try { MakeBenchmarkGuide(0, 96, 256, 192, 64, 48, 1, 1); return 1; }
    catch (const std::invalid_argument&) {}
    for (const auto* path : {L"D:/opennr-forbidden/new-output"}) {
        if (!std::filesystem::exists(std::filesystem::path(path).root_path())) continue;
        try { CheckedBenchmarkOutput(path); return 2; }
        catch (const std::invalid_argument&) {}
    }
    assert(CheckedBenchmarkOutput(L"C:/OpenNR/new-output").root_name() == L"C:");
    std::cout << "PASS: native guide dimensions, scaling, invalid inputs and physical storage destinations\n";
}
