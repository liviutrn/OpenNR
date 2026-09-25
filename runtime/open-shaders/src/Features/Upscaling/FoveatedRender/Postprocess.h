#pragma once

struct Upscaling;

namespace FoveatedRenderImpl
{
	class Postprocess
	{
	public:
		/** Sharpens the current LDR stereo scene once per frame, before UI composition. */
		static bool ApplyDlssSharpening(Upscaling& upscaling);
		/** Releases the sharpening target and clears the frame guard. */
		static void Reset();
	};
}
