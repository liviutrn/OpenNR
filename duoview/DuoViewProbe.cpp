#include "DuoViewGeometry.hpp"
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>
using uevr::duoview::make_layout;
using uevr::duoview::rendered_pixels;

static void print_mode(float crop) {
    const auto l = make_layout(3000,3000,crop,crop);
    if (!l) { std::cerr << "DuoView invalid crop\n"; std::exit(1); }
    const auto rendered = rendered_pixels(*l);
    const auto baseline = 3000ull * 3000ull;
    std::cout << std::fixed << std::setprecision(1)
              << "Crop " << crop * 100.f << "%: "
              << "fovea " << l->fovea.width << "x" << l->fovea.height
              << " + periphery " << l->periphery.width << "x" << l->periphery.height
              << " = " << rendered << " game-render pixels ("
              << (100.0 * (1.0 - static_cast<double>(rendered)/baseline))
              << "% fewer than baseline)\n";
}

int main() {
    std::cout << "DuoView layout proof. No UEVR injection or GPU measurement.\n";
    print_mode(.50f);
    print_mode(.30f);
}
