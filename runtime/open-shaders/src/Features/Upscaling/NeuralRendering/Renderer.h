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
			// Optional crop-sized composite target used when the game's stereo
			// destination has no UAV. The caller seeds it from the current crop;
			// ApplyStereo blends locally and leaves copying the crop back to caller.
			ID3D11Resource* writebackTarget = nullptr;
			ID3D11UnorderedAccessView* writebackUAV = nullptr;
			std::uint32_t sourceX = 0;
			std::uint32_t sourceY = 0;
			// Optional origin inside the input depth/motion guide textures. Used
			// when the post-SR stage takes a smaller center crop from gaze guides.
			std::uint32_t guideSourceX = 0;
			std::uint32_t guideSourceY = 0;
			std::uint32_t guideSourceWidth = 0;
			std::uint32_t guideSourceHeight = 0;
			bool forceFeatherComposite = false;
			float motionVectorScaleX = 1.0f;
			float motionVectorScaleY = 1.0f;
			bool compensateCropMotion = false;
		};

		// Optional stable resource envelope for adaptive crop extents. The current
		// guide/color extents remain explicit in the
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
		/** @brief Separate persistent resources and Feature 18 slots for the pre-SR stage. */
		static Renderer& PreUpscaleInstance();
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
		/** @brief Resets the native renderer; false means the GPU fence could not be drained safely. */
		bool Reset();
		void ResetHistory();

		[[nodiscard]] bool IsFailureLatched() const;
		[[nodiscard]] bool IsFailureRecoverable() const;
		/** @brief Holds adaptive upshifts after the session's bounded recovery attempt. */
		[[nodiscard]] bool IsRecoveryLimited() const;
		/**
		 * @brief Returns whether an adaptive model tier and requested cascade capacity are resident for both eyes.
		 *
		 * Adaptive tier changes are only safe to expose at frame time when the
		 * shared textures and native Feature 18 handles already exist.  The
		 * renderer may prewarm those objects while the current tier is running;
		 * callers use this query to keep the controller on the current tier until
		 * the handoff can be made without an on-demand create stall.
		 */
		[[nodiscard]] bool IsAdaptiveTierReady(std::uint32_t modelResolution, std::uint32_t passCount) const;
		/** @brief True when ready, or when prewarm failed and a one-time live create is the only fallback. */
		[[nodiscard]] bool CanUseAdaptiveTier(std::uint32_t modelResolution, std::uint32_t passCount) const;
		[[nodiscard]] std::uint32_t NgxResult() const;
		[[nodiscard]] std::uint64_t SuccessfulFrames() const;
		[[nodiscard]] const char* StatusText() const;

	private:
		explicit Renderer(std::uint32_t runtimeFeatureSlotBlock = 0, std::uint32_t cropMotionSlotBase = 2);
		class State;
		State* state_ = nullptr;
		std::uint32_t cropMotionSlotBase_ = 2;
	};
}
