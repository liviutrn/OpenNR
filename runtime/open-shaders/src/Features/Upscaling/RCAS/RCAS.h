#pragma once

#include "../../../Buffer.h"
#include "../../../State.h"

#include <algorithm>
#include <cmath>
#include <d3d11_4.h>
#include <winrt/base.h>

/**
 * @brief Robust Contrast Adaptive Sharpening (RCAS) implementation.
 *
 * Standalone sharpening pass based on AMD FidelityFX FSR1 RCAS algorithm.
 * Used to apply sharpening to DLSS output in HDR space before tonemapping.
 */
class RCAS
{
public:
	RCAS() = default;
	~RCAS();

	/**
	 * @brief Initializes RCAS resources including compute shader and constant buffer.
	 *
	 * Safe to call multiple times - will early-out if already initialized.
	 */
	void Initialize();

	/**
	 * @brief Applies RCAS sharpening to the input texture.
	 *
	 * @param inputTexture SRV of the texture to sharpen (typically kMAIN render target).
	 * @param outputUAV UAV to write sharpened result to.
	 * @param sharpness RCAS attenuation/extended strength after slider conversion.
	 * @return True when the sharpening dispatch was submitted.
	 */
	bool ApplySharpen(ID3D11ShaderResourceView* inputTexture, ID3D11UnorderedAccessView* outputUAV, float sharpness);

	/** @brief Convert the shared 0–3 slider to RCAS attenuation/extended strength. */
	static float MapSliderStrength(float strength)
	{
		strength = std::clamp(std::isfinite(strength) ? strength : 0.0f, 0.0f, 3.0f);
		return strength <= 1.0f ? std::exp2(2.0f * strength - 2.0f) : strength;
	}

private:
	void CreateComputeShader();

	winrt::com_ptr<ID3D11ComputeShader> rcasComputeShader;
	ConstantBuffer* rcasConfigCB = nullptr;
};
