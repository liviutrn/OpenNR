// ============================================================================
// Modes.cpp — Default / Faster DLSS execution strategies
// ============================================================================
//
// Each mode composes Ops primitives (snapshot, stretch, crop, blend…) in a
// different order.  Router resolves VRDlssParams and dispatches.
//
// ============================================================================

#include "Bridge.h"
#include "Core.h"
#include "Ops.h"
#include "Params.h"
#include "../CropMotion.h"

#include "../../../Globals.h"
#include "../../../Utils/Subrect.h"
#include "../../Upscaling.h"
#include "../FidelityFX.h"
#include "../Streamline.h"

#include <algorithm>
#include <cmath>

namespace FoveatedRenderImpl
{
	using namespace Ops;

	// ── Router: resolves params via Params module, dispatches to the selected mode ──

	bool Core::DispatchUpscaleRegion(Streamline& streamline, uint32_t eyeIndex,
		ID3D11Resource* colorIn, ID3D11Resource* colorOut, ID3D11Resource* depth, ID3D11Resource* mvec,
		ID3D11Resource* reactiveMask, ID3D11Resource* transparencyMask,
		uint32_t inW, uint32_t inH, uint32_t outW, uint32_t outH,
		uint32_t fullEyeWidthIn, uint32_t fullEyeHeightIn)
	{
		auto& upscaling = globals::features::upscaling;
		if (upscaling.GetUpscaleMethod() == Upscaling::UpscaleMethod::kFSR) {
			// FSR3's motionVectorScale is a pixel extent (not DLSS's ratio-based
			// correction from Bridge::ComputeMvecScale) that mvec values are multiplied
			// against. mvec is a straight crop copy staying normalized to the full eye,
			// so passing the smaller crop extent here would make FSR3 misjudge magnitude.
			return upscaling.fidelityFX.UpscaleRegion(eyeIndex, colorIn, depth, mvec, reactiveMask, transparencyMask,
				colorOut, inW, inH, outW, outH, (float)fullEyeWidthIn, (float)fullEyeHeightIn, upscaling.settings.sharpnessFSR, /*a_forceHostPath=*/true);
		}

		sl::ViewportHandle vp = (eyeIndex == 1) ? streamline.viewportRight : streamline.viewport;
		sl::Extent extentIn{ 0, 0, inW, inH };
		sl::Extent extentOut{ 0, 0, outW, outH };
		return streamline.EvaluateDLSS(vp, eyeIndex, colorIn, colorOut, depth, mvec, reactiveMask, transparencyMask,
			extentIn, extentOut, outW, outH);
	}

	bool Core::ExecuteFoveatedRoute(Streamline& streamline,
		ID3D11Resource* upscalingTexture, ID3D11Resource* depthTexture,
		ID3D11Resource* reactiveMask, ID3D11Resource* transparencyMask, ID3D11Resource* motionVectors)
	{
		// Resolve the adaptive decision before Params hashes the crop. The same
		// effective UVs are then consumed by DLSS, VRS, and the later NR hook.
		const auto frame = globals::state ? globals::state->frameCount : 0;
		globals::features::upscaling.foveatedRender.UpdateAdaptiveState(frame, true);
		auto p = VRDlssParams::Resolve(upscalingTexture, depthTexture, reactiveMask, transparencyMask, motionVectors);
		// Preserve the source guides for the optional display-space crop handoff.
		Core::vrAdaptiveCropDepthSource = p.depthTexture;
		Core::vrAdaptiveCropMotionSource = p.motionVectors;

		// Adaptive crop, including eye-tracked crop, uses a stable maximum-size
		// envelope. Gaze changes the valid-region origin and adaptive crop changes
		// its extent; neither change should recreate Streamline handles.
		const bool fixedEnvelopeCandidate = globals::features::upscaling.foveatedRender.IsAdaptiveCropRuntimeActive() &&
			std::abs(p.leftUV.w - p.rightUV.w) <= 0.0005f &&
			std::abs(p.leftUV.h - p.rightUV.h) <= 0.0005f && !Core::vrSubrectFixedEnvelopeRejected;
		const Util::Subrect::UVRegion envelopeUV{ 0.0f, 0.0f, 1.0f, 1.0f };
		uint64_t uvHash = fixedEnvelopeCandidate ?
			ComputeSubrectUVHash(envelopeUV, envelopeUV, (uint32_t)p.mode, false) :
			ComputeSubrectUVHash(p.leftUV, p.rightUV, (uint32_t)p.mode, !p.eyeTrackedGazeConfigured);
		if (uvHash != Core::activeSubrectUVHash) {
			logger::info("[FOVEATED] resource contract changed mode={} adaptiveEnvelope={} left={}x{} right={}x{}; recreating DLSS resources",
				static_cast<uint32_t>(p.mode), fixedEnvelopeCandidate, p.leftUV.w, p.leftUV.h, p.rightUV.w, p.rightUV.h);
			streamline.DestroyDLSSResources();
			Core::InvalidateTemporalState();
			logger::debug("[FOVEATED] Temporal state invalidated after subrect/mode change; waiting for fresh per-eye guides");
			Core::activeSubrectUVHash = uvHash;
		} else if (p.eyeTrackedGazeReset) {
			// A reacquisition, large gaze jump, or static handoff changes the
			// semantic crop/history contract without changing resource dimensions.
			Core::InvalidateTemporalState();
			logger::debug("[FOVEATED] Native OpenVR gaze history reset without resource resize");
		}

		Bridge::gazeHistoryReset = p.eyeTrackedGazeReset;
		Bridge::foveatedEvaluating = true;
		Core::neuralGuidesFrame = UINT32_MAX;
		bool result = (p.mode == FoveatedRender::DlssMode::kFaster) ?
		                  ExecuteFasterMode(streamline, p) :
		                  ExecuteDefaultMode(streamline, p);
		for (uint32_t eye = 0; eye < 2; ++eye)
			CropMotion::Commit(eye, result && Core::neuralGuidesFrame == frame && p.eyeTrackedGazeConfigured && !p.isFullEye);
		Bridge::foveatedEvaluating = false;
		Bridge::gazeHistoryReset = false;
		return result;
	}

	// ── Default mode: per-eye isolation, 2 resource sets, 2 evaluates ──

	bool Core::ExecuteDefaultMode(Streamline& streamline, const VRDlssParams& p)
	{
		// Subrect path needs colorDstUAV (StretchDRSBothEyes writes through it).
		// Full-eye path doesn't touch it. Return false on the subrect path so
		// the router falls back to standard DLSS rather than hitting the null
		// guard inside StretchDRSToFullEye every frame.
		if (!p.isFullEye && !p.colorDstUAV) {
			logger::error("[FOVEATED] ExecuteDefaultMode subrect path missing colorDstUAV — falling back");
			return false;
		}
		if (p.isFullEye) {
			// Full-eye path: same as standard VR DLSS
			if (!PreparePerEyeInputs(
					p.colorSrc, p.depthTexture, p.motionVectors, p.reactiveMask, p.transparencyMask,
					p.eyeWidthIn, p.eyeHeightIn, p.eyeWidthOut, p.eyeHeightOut))
				return false;

			for (uint32_t i = 0; i < 2; ++i) {
				if (!DispatchUpscaleRegion(streamline, i,
						Core::vrIntermediateColorIn[i]->resource.get(), Core::vrIntermediateColorOut[i]->resource.get(),
						Core::vrIntermediateDepth[i]->resource.get(), Core::vrIntermediateMotionVectors[i]->resource.get(),
						p.reactiveMask ? Core::vrIntermediateReactiveMask[i]->resource.get() : nullptr,
						p.transparencyMask ? Core::vrIntermediateTransparencyMask[i]->resource.get() : nullptr,
						p.eyeWidthIn, p.eyeHeightIn, p.eyeWidthOut, p.eyeHeightOut,
						p.eyeWidthIn, p.eyeHeightIn)) {
					SnapshotSBS(p.colorSrc, p.renderW, p.renderH);
					return StretchDRSBothEyes(p.colorDstUAV, p.eyeWidthOut, p.eyeHeightOut,
						p.eyeWidthIn, p.eyeHeightIn, p.renderW, p.renderH);
				}
			}

			const bool finalized = FinalizePerEyeOutputs(p.colorDst, p.eyeWidthOut, p.eyeHeightOut);
			if (finalized)
				Core::neuralGuidesFrame = globals::state ? globals::state->frameCount : UINT32_MAX;
			return finalized;
		}

		// ── Subrect path: crop per-eye, DLSS at subrect size, stretch back ──
		const auto& foveated = globals::features::upscaling.foveatedRender;
		const bool fixedEnvelopeCandidate = foveated.IsAdaptiveCropRuntimeActive() &&
			std::abs(p.leftUV.w - p.rightUV.w) <= 0.0005f &&
			std::abs(p.leftUV.h - p.rightUV.h) <= 0.0005f && !Core::vrSubrectFixedEnvelopeRejected;

		// The shared resource path requires symmetric eye extents. Fail closed rather
		// than write out of bounds if the two per-eye crop shapes diverge.
		if (p.leftUV.w != p.rightUV.w || p.leftUV.h != p.rightUV.h) {
			logger::error("[FOVEATED] ExecuteDefaultMode: asymmetric-size stereo subrect (left {}x{}, right {}x{}) not supported — falling back",
				p.leftUV.w, p.leftUV.h, p.rightUV.w, p.rightUV.h);
			return false;
		}

		const Util::Subrect::UVRegion* eyeUVs[2] = { &p.leftUV, &p.rightUV };

		// EnsureVRSubrectTextures allocates a shared per-eye envelope. The per-eye
		// loop below still uses each eye's UV for the valid copy/dispatch extent.
		uint32_t allocSubInW = std::max<uint32_t>(1, (uint32_t)(p.eyeWidthIn * p.leftUV.w));
		uint32_t allocSubInH = std::max<uint32_t>(1, (uint32_t)(p.eyeHeightIn * p.leftUV.h));
		uint32_t allocSubOutW = std::max<uint32_t>(1, (uint32_t)(p.eyeWidthOut * p.leftUV.w));
		uint32_t allocSubOutH = std::max<uint32_t>(1, (uint32_t)(p.eyeHeightOut * p.leftUV.h));
		// Size the backing set from the saved crop and the adaptive maximum, not
		// from this frame's smaller tier or moving gaze origin. The validated
		// envelope then remains resident through all adaptive crop changes.
		const auto baseLeftUV = foveated.subrectController.GetUV();
		const auto baseRightUV = foveated.subrectController.GetRightEyeUV();
		const float maximumScale = static_cast<float>(foveated.GetAdaptiveCropMaximumScalePercent()) / 100.0f;
		const auto envelopeDimension = [](std::uint32_t dimension, float cropExtent, float scale) {
			return std::max<std::uint32_t>(1, static_cast<std::uint32_t>(std::ceil(
				static_cast<float>(dimension) * cropExtent * scale)));
		};
		const float gazePaddingX = foveated.settings.neuralRenderingEyeTrackedFoveation && p.eyeWidthIn > 0 ?
			(2.0f * static_cast<float>(foveated.settings.neuralRenderingEyeTrackedCropPaddingPixels) /
				static_cast<float>(p.eyeWidthIn)) : 0.0f;
		const float gazePaddingY = foveated.settings.neuralRenderingEyeTrackedFoveation && p.eyeHeightIn > 0 ?
			(2.0f * static_cast<float>(foveated.settings.neuralRenderingEyeTrackedCropPaddingPixels) /
				static_cast<float>(p.eyeHeightIn)) : 0.0f;
		const float maximumCropWidth = std::min(1.0f, std::max(baseLeftUV.w, baseRightUV.w) + gazePaddingX);
		const float maximumCropHeight = std::min(1.0f, std::max(baseLeftUV.h, baseRightUV.h) + gazePaddingY);
		const uint32_t envelopeSubInW = fixedEnvelopeCandidate ? envelopeDimension(p.eyeWidthIn, maximumCropWidth, maximumScale) : allocSubInW;
		const uint32_t envelopeSubInH = fixedEnvelopeCandidate ? envelopeDimension(p.eyeHeightIn, maximumCropHeight, maximumScale) : allocSubInH;
		const uint32_t envelopeSubOutW = fixedEnvelopeCandidate ? envelopeDimension(p.eyeWidthOut, maximumCropWidth, maximumScale) : allocSubOutW;
		const uint32_t envelopeSubOutH = fixedEnvelopeCandidate ? envelopeDimension(p.eyeHeightOut, maximumCropHeight, maximumScale) : allocSubOutH;

		const auto frame = globals::state ? globals::state->frameCount : 0;
		if (!EnsureVRSubrectTextures(envelopeSubInW, envelopeSubInH, envelopeSubOutW, envelopeSubOutH,
			p.colorSrc, p.motionVectors, p.reactiveMask, p.transparencyMask,
			fixedEnvelopeCandidate, frame)) {
			logger::error("[FOVEATED] subrect resource contract could not be satisfied — falling back");
			return false;
		}
		if (Core::vrSubrectResourceContractChanged) {
			// A valid-extent-only handoff leaves the active envelope intact. Any
			// actual resource identity/source/extent change, however, must release
			// the old Streamline handles before they can observe the replacement.
			Core::vrSubrectResourceContractChanged = false;
			streamline.DestroyDLSSResources();
			Core::InvalidateTemporalState();
			logger::debug("[FOVEATED] Streamline handles invalidated after subrect resource contract change frame={}", frame);
		}

		// Snapshot + clear HMD hidden-area ring before cropping into subrect inputs.
		SnapshotSBS(p.colorSrc, p.renderW, p.renderH);
		ClearHMDMaskOnSnapshot(p);
		if (!StretchDRSBothEyes(p.colorDstUAV, p.eyeWidthOut, p.eyeHeightOut, p.eyeWidthIn, p.eyeHeightIn, p.renderW, p.renderH, MaybeTemporalSmooth(p))) {
			logger::error("[FOVEATED] ExecuteDefaultMode periphery stretch failed — falling back");
			return false;
		}

		// Crop subrect per-eye from mask-cleared snapshot (not kMAIN which was overwritten by stretch)
		auto context = globals::d3d::context;
		for (uint32_t i = 0; i < 2; ++i) {
			const auto& uv = *eyeUVs[i];
			// Per-eye sizing — right eye uses rightUV.w/h, not leftUV.
			uint32_t subInW = std::max<uint32_t>(1, (uint32_t)(p.eyeWidthIn * uv.w));
			uint32_t subInH = std::max<uint32_t>(1, (uint32_t)(p.eyeHeightIn * uv.h));
			uint32_t subOutW = std::max<uint32_t>(1, (uint32_t)(p.eyeWidthOut * uv.w));
			uint32_t subOutH = std::max<uint32_t>(1, (uint32_t)(p.eyeHeightOut * uv.h));

			uint32_t cropX = (uint32_t)(uv.x * p.eyeWidthIn);
			uint32_t cropY = (uint32_t)(uv.y * p.eyeHeightIn);
			uint32_t sbsX = (i == 1 ? p.eyeWidthIn : 0) + cropX;
			D3D11_BOX sbsCrop = { sbsX, cropY, 0, sbsX + subInW, cropY + subInH, 1 };

			context->CopySubresourceRegion(Core::vrSubrectColorIn[i]->resource.get(), 0, 0, 0, 0, Core::vrRenderSBS->resource.get(), 0, &sbsCrop);
			if (!CopyDepthRegionToTexture(p.depthTexture, nullptr, Core::vrSubrectDepth[i]->uav.get(),
				sbsX, cropY, subInW, subInH)) {
				logger::error("[FOVEATED] Failed to convert native depth for subrect eye {}", i);
				return false;
			}
			context->CopySubresourceRegion(Core::vrSubrectMotionVectors[i]->resource.get(), 0, 0, 0, 0, p.motionVectors, 0, &sbsCrop);
			if (p.reactiveMask)
				context->CopySubresourceRegion(Core::vrSubrectReactiveMask[i]->resource.get(), 0, 0, 0, 0, p.reactiveMask, 0, &sbsCrop);
			if (p.transparencyMask)
				context->CopySubresourceRegion(Core::vrSubrectTransparencyMask[i]->resource.get(), 0, 0, 0, 0, p.transparencyMask, 0, &sbsCrop);

			ID3D11Resource* srMotion = Core::vrSubrectMotionVectors[i]->resource.get();
			if (p.eyeTrackedGazeConfigured) {
				float scaleX = 1.0f, scaleY = 1.0f;
				Bridge::ComputeMvecScale(i, scaleX, scaleY);
				bool reset = p.eyeTrackedGazeReset;
				srMotion = CropMotion::Prepare(i, srMotion, { cropX, cropY, subInW, subInH },
					subInW, subInH, { scaleX, scaleY }, frame, reset);
				if (!srMotion) {
					Core::InvalidateTemporalState();
					return true;
				}
				Bridge::gazeHistoryReset = reset;
			}

			if (!DispatchUpscaleRegion(streamline, i,
					Core::vrSubrectColorIn[i]->resource.get(), Core::vrSubrectColorOut[i]->resource.get(),
					Core::vrSubrectDepth[i]->resource.get(), srMotion,
					p.reactiveMask ? Core::vrSubrectReactiveMask[i]->resource.get() : nullptr,
					p.transparencyMask ? Core::vrSubrectTransparencyMask[i]->resource.get() : nullptr,
					subInW, subInH, subOutW, subOutH,
					p.eyeWidthIn, p.eyeHeightIn)) {
				if (fixedEnvelopeCandidate && !Core::vrSubrectFixedEnvelopeRejected) {
					Core::vrSubrectFixedEnvelopeRejected = true;
					++Core::vrSubrectFallbackEntries;
					logger::warn("[FOVEATED] Envelope failed frame={}; exact extents on next frame, crop held until Reset", frame);
				}
				// The current-frame periphery already covers both eyes. A second
				// dispatch would resubmit constants and crop the overwritten input.
				Core::InvalidateTemporalState();
				return true;
			}
		}
		// Publish copied guide extents, never the larger backing allocation.
		Core::vrSubrectValidInW = allocSubInW;
		Core::vrSubrectValidInH = allocSubInH;
		Core::vrSubrectValidOutW = allocSubOutW;
		Core::vrSubrectValidOutH = allocSubOutH;
		Core::neuralGuidesFrame = globals::state ? globals::state->frameCount : UINT32_MAX;

		// Write DLSS output back at subrect position (with optional blend)
		for (uint32_t i = 0; i < 2; ++i) {
			const auto& uv = *eyeUVs[i];
			// Per-eye sizing.
			uint32_t subOutW = std::max<uint32_t>(1, (uint32_t)(p.eyeWidthOut * uv.w));
			uint32_t subOutH = std::max<uint32_t>(1, (uint32_t)(p.eyeHeightOut * uv.h));

			uint32_t dstCropX = (uint32_t)(uv.x * p.eyeWidthOut);
			uint32_t dstCropY = (uint32_t)(uv.y * p.eyeHeightOut);
			uint32_t dstX = (i == 1 ? p.eyeWidthOut : 0) + dstCropX;
			if (!BlendSubrectToOutput(Core::vrSubrectColorOut[i]->resource.get(), p.colorDst, p.colorDstUAV,
					dstX, dstCropY, subOutW, subOutH)) {
				logger::error("[FOVEATED] ExecuteDefaultMode subrect blend failed for eye {} — falling back", i);
				return false;
			}
		}

		return true;
	}

	// ── Faster mode: DLSS reads directly from SBS via extents, per-eye output, 2 evaluates ──
	// Input:  kMAIN/depth/mvec SBS textures using extent offsets (zero input copies).
	// Output: per-eye independent textures with extent {0,0}.
	// Flow:   DLSS read → snapshot+stretch background → copy outputs back to kMAIN.

	bool Core::ExecuteFasterMode(Streamline& streamline, const VRDlssParams& p)
	{
		// Subrect path needs colorDstUAV (StretchDRSBothEyes writes through it
		// in Step 3). Full-eye Faster skips Step 3 — don't reject it here just
		// because the UAV isn't bound.
		if (!p.isFullEye && !p.colorDstUAV) {
			logger::error("[FOVEATED] ExecuteFasterMode subrect path missing colorDstUAV — falling back");
			return false;
		}
		const Util::Subrect::UVRegion* eyeUVs[2] = { &p.leftUV, &p.rightUV };

		// NOTE: EnsureFasterOutputTextures allocates one per-eye texture set
		// sized to LEFT-eye subrect dimensions. Correct only while Util::Subrect
		// auto-mirror keeps leftUV.w/h == rightUV.w/h. Per-eye DLSS extents
		// below use the eye's own uv.
		uint32_t allocSubOutW = p.isFullEye ? p.eyeWidthOut : std::max<uint32_t>(1, (uint32_t)(p.eyeWidthOut * p.leftUV.w));
		uint32_t allocSubOutH = p.isFullEye ? p.eyeHeightOut : std::max<uint32_t>(1, (uint32_t)(p.eyeHeightOut * p.leftUV.h));

		// Step 1: Ensure per-eye output textures
		EnsureFasterOutputTextures(allocSubOutW, allocSubOutH, p.colorSrc);

		// Step 2a: Snapshot kMAIN into vrRenderSBS so we can clear the HMD
		// hidden-area ring without writing to kMAIN itself. Without this clear
		// DLSS's temporal accumulation drags Skyrim's default sky clear from
		// the masked-out edge into the visible region on fast head motion —
		// the standard Streamline path (Streamline.cpp) and Default mode both
		// pre-clear via per-eye intermediates.
		SnapshotSBS(p.colorSrc, p.renderW, p.renderH);
		ClearHMDMaskOnSnapshot(p);
		ID3D11Resource* dlssColorSrc = (Core::vrRenderSBS ? Core::vrRenderSBS->resource.get() : p.colorSrc);

		// Step 2b: DLSS reads from the mask-cleared SBS snapshot via extent offsets
		// → per-eye output. sl::Extent field order is {top, left, width, height}.
		for (uint32_t i = 0; i < 2; ++i) {
			const auto& uv = *eyeUVs[i];
			// Per-eye sizing.
			uint32_t subInW = p.isFullEye ? p.eyeWidthIn : std::max<uint32_t>(1, (uint32_t)(p.eyeWidthIn * uv.w));
			uint32_t subInH = p.isFullEye ? p.eyeHeightIn : std::max<uint32_t>(1, (uint32_t)(p.eyeHeightIn * uv.h));
			uint32_t subOutW = p.isFullEye ? p.eyeWidthOut : std::max<uint32_t>(1, (uint32_t)(p.eyeWidthOut * uv.w));
			uint32_t subOutH = p.isFullEye ? p.eyeHeightOut : std::max<uint32_t>(1, (uint32_t)(p.eyeHeightOut * uv.h));

			uint32_t cropX = p.isFullEye ? 0 : (uint32_t)(uv.x * p.eyeWidthIn);
			uint32_t cropY = p.isFullEye ? 0 : (uint32_t)(uv.y * p.eyeHeightIn);
			uint32_t inOffsetX = (i == 1 ? p.eyeWidthIn : 0) + cropX;
			uint32_t inOffsetY = cropY;

			sl::ViewportHandle vp = (i == 1) ? streamline.viewportRight : streamline.viewport;
			sl::Extent extentIn{ inOffsetY, inOffsetX, subInW, subInH };
			sl::Extent extentOut{ 0, 0, subOutW, subOutH };

			if (!streamline.EvaluateDLSS(vp, i,
					dlssColorSrc, Core::vrFasterColorOut[i]->resource.get(),
					p.depthTexture, p.motionVectors,
					p.reactiveMask, p.transparencyMask,
					extentIn, extentOut, subOutW, subOutH)) {
				logger::error("[FOVEATED] ExecuteFasterMode dispatch failed for eye {} — falling back", i);
				return false;
			}
		}

		// Step 3: Stretch DRS → kMAIN (subrect only) — snapshot reused from Step 2a.
		if (!p.isFullEye) {
			if (!StretchDRSBothEyes(p.colorDstUAV, p.eyeWidthOut, p.eyeHeightOut, p.eyeWidthIn, p.eyeHeightIn, p.renderW, p.renderH, MaybeTemporalSmooth(p))) {
				logger::error("[FOVEATED] ExecuteFasterMode periphery stretch failed — falling back");
				return false;
			}
		}

		// Step 4: Copy DLSS output back (with optional blend)
		for (uint32_t i = 0; i < 2; ++i) {
			const auto& uv = *eyeUVs[i];
			// Per-eye sizing.
			uint32_t subOutW = p.isFullEye ? p.eyeWidthOut : std::max<uint32_t>(1, (uint32_t)(p.eyeWidthOut * uv.w));
			uint32_t subOutH = p.isFullEye ? p.eyeHeightOut : std::max<uint32_t>(1, (uint32_t)(p.eyeHeightOut * uv.h));

			uint32_t dstCropX = p.isFullEye ? 0 : (uint32_t)(uv.x * p.eyeWidthOut);
			uint32_t dstCropY = p.isFullEye ? 0 : (uint32_t)(uv.y * p.eyeHeightOut);
			uint32_t dstX = (i == 1 ? p.eyeWidthOut : 0) + dstCropX;
			if (!BlendSubrectToOutput(Core::vrFasterColorOut[i]->resource.get(), p.colorDst, p.colorDstUAV,
					dstX, dstCropY, subOutW, subOutH)) {
				logger::error("[FOVEATED] ExecuteFasterMode subrect blend failed for eye {} — falling back", i);
				return false;
			}
		}

		return true;
	}

}
