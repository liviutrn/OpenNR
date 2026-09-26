#pragma once

#include <cstdint>

namespace NeuralRendering
{
	struct SecondPassCropConfig
	{
		std::uint32_t outputWidth = 0;
		std::uint32_t outputHeight = 0;
		std::uint32_t guideWidth = 0;
		std::uint32_t guideHeight = 0;
		std::uint32_t reductionX = 0;
		std::uint32_t reductionY = 0;

		bool operator==(const SecondPassCropConfig&) const = default;
	};

	class SecondPassCropFallbackLatch
	{
	public:
		[[nodiscard]] bool IsRejected(const SecondPassCropConfig& config)
		{
			if (!configured_ || config_ != config) {
				config_ = config;
				configured_ = true;
				rejected_ = false;
			}
			return rejected_;
		}

		bool MarkRejected()
		{
			if (rejected_)
				return false;
			rejected_ = true;
			return true;
		}

		void Reset()
		{
			configured_ = false;
			rejected_ = false;
		}

	private:
		SecondPassCropConfig config_{};
		bool configured_ = false;
		bool rejected_ = false;
	};
}
