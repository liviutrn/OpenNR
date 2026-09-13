#pragma once

#include "Runtime.h"

#include <array>
#include <cstdint>

struct ID3D11Device;
struct ID3D11DeviceContext;
struct ID3D11Resource;
struct ID3D11ShaderResourceView;
struct ID3D11UnorderedAccessView;

namespace NeuralRendering
{
	class Renderer
	{
	public:
			struct StereoEyeInput
		{
			ID3D11Resource* depth = nullptr;
			ID3D11ShaderResourceView* depthSRV = nullptr;
			ID3D11Resource* motionVectors = nullptr;
			std::uint32_t sourceX = 0;
			std::uint32_t sourceY = 0;
			float motionVectorScaleX = 1.0f;
			float motionVectorScaleY = 1.0f;
			};

			// Optional stable resource envelope for the adaptive regular-crop
			// experiment. The current guide/color extents remain explicit in the
			// ApplyStereo arguments; these dimensions describe only the backing
			// resources that may safely be reused while that valid region changes.
			struct StereoResourceEnvelope
			{
				bool enabled = false;
				std::uint32_t guideWidth = 0;
				std::uint32_t guideHeight = 0;
				std::uint32_t colorWidth = 0;
				std::uint32_t colorHeight = 0;

				[[nodiscard]] bool IsValid() const
				{
					return enabled && guideWidth != 0 && guideHeight != 0 &&
						colorWidth != 0 && colorHeight != 0;
				}
			};

		static Renderer& Instance();
		~Renderer();

		Renderer(const Renderer&) = delete;
		Renderer& operator=(const Renderer&) = delete;

		bool Apply(ID3D11Device* device, ID3D11DeviceContext* context, std::uint32_t eyeIndex,
			ID3D11Resource* color, ID3D11Resource* depth, ID3D11ShaderResourceView* depthSRV,
			ID3D11Resource* motionVectors,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight,
			float motionVectorScaleX, float motionVectorScaleY, const Tuning& tuning);
		bool ApplyStereo(ID3D11Device* device, ID3D11DeviceContext* context, ID3D11Resource* color,
			const std::array<StereoEyeInput, 2>& eyes,
			std::uint32_t guideWidth, std::uint32_t guideHeight,
			std::uint32_t colorWidth, std::uint32_t colorHeight, const Tuning& tuning,
			// Optional separate writeback target. The input remains `color`; this is
				// needed when a cropped NR result must be feathered over its background.
				ID3D11Resource* destination = nullptr,
				ID3D11UnorderedAccessView* destinationUAV = nullptr,
				bool blendSubrect = false,
				const StereoResourceEnvelope& resourceEnvelope = {});
		/** @brief Drops cached standalone neural-rendering shaders so they recompile on the next frame. */
		void ClearShaderCache();
		void Reset();
		void ResetHistory();

		[[nodiscard]] bool IsFailureLatched() const;
		[[nodiscard]] std::uint32_t NgxResult() const;
		[[nodiscard]] std::uint64_t SuccessfulFrames() const;
		[[nodiscard]] const char* StatusText() const;

	private:
		Renderer();
		class State;
		State* state_ = nullptr;
	};
}
