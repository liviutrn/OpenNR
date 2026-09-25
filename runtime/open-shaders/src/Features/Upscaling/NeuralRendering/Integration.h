#pragma once

namespace NeuralRendering
{
	/** Updates overlay state and consumes any render-thread history-reset request. */
	void UpdateFrameState();

	/** Requests a temporal-history reset from a non-render-thread event callback. */
	void RequestHistoryReset();
	/** Requests a full NR, DLSS and adaptive-failure reset on the render thread. */
	void RequestReset();

	/** Resets Feature 18 temporal history while keeping the runtime initialized. */
	void ResetHistory();

	/**
	 * Runs the opt-in first NR stage at Skyrim's native render resolution,
	 * immediately before the normal DLSS dispatch. A false result means the
	 * post-upscale hook should run the complete configured cascade as fallback.
	 */
	bool ApplyPreUpscale();

	/** Reports whether pre-upscale NR failed and is held off until toggled or reset. */
	bool IsPreUpscaleExecutionFailed();

	/** Runs DLSS Neural Rendering on the LDR foveated regions immediately before UI composite. */
	bool ApplyFoveatedLdr();

	/** Releases all runtime and shared-resource state. */
	void Reset();
}
