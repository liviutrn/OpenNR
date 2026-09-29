"""Fast guide-conditioned recurrent student for the OpenNR runtime path.

This model is intentionally separate from the existing joint semantic model and
from the existing temporal-student experiments.  It keeps the native Feature
18 guide contract (depth, motion-vector X/Y, and validity channels), carries
state only on the 1/8-resolution grid, and leaves the final native-resolution
operation to a three-channel residual head.  There is no DINO/ViT encoder and
there is no inferred optical-flow replacement for the native guides.

The zero-initialized residual heads make a fresh checkpoint an exact RGB
identity at step zero.  That is useful for safe training and for distinguishing
architecture/runtime failures from a learned image-quality regression.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F


@dataclass
class FastStudentConfig:
    """Fixed-shape-friendly width and conditioning settings.

    ``model_scale`` is the first learned grid (1/4 by default).  The second
    grid is the temporal core (1/8 by default), so the recurrent state is much
    smaller than a full-resolution history tensor.  ``base_width=32`` and
    ``mid_width=64`` are deliberately conservative for the first runtime
    candidate; width can be increased in an isolated training/export run.
    """

    base_width: int = 32
    mid_width: int = 64
    temporal_hidden: int = 64
    blocks: int = 2
    model_scale: int = 4
    temporal_downsample: int = 8
    guide_channels: int = 5
    context_channels: int = 8
    residual_scale: float = 0.12
    residual_mode: str = "rgb"
    use_native_refine: bool = True

    def validate(self) -> None:
        if self.base_width < 4 or self.mid_width < self.base_width:
            raise ValueError("mid_width must be at least base_width >= 4")
        if self.temporal_hidden < 4 or self.blocks < 1:
            raise ValueError("temporal_hidden and blocks must be positive")
        if self.model_scale < 1 or self.temporal_downsample < self.model_scale:
            raise ValueError("invalid learned-grid scale")
        if self.temporal_downsample != self.model_scale * 2:
            raise ValueError("FastStudentV1 expects temporal_downsample == model_scale * 2")
        if self.guide_channels != 5 or self.context_channels != 8:
            raise ValueError("the current OpenNR runtime contract is 5 guides and 8 context channels")
        if not 0.0 < self.residual_scale <= 1.0:
            raise ValueError("residual_scale must be in (0, 1]")
        if self.residual_mode not in {"rgb", "luma"}:
            raise ValueError("residual_mode must be 'rgb' or 'luma'")


class DepthwiseResidualBlock(nn.Module):
    """Small gated residual block with cheap spatial mixing."""

    def __init__(self, channels: int):
        super().__init__()
        self.norm = nn.GroupNorm(1, channels)
        self.expand = nn.Conv2d(channels, channels * 2, 1)
        self.spatial = nn.Conv2d(
            channels * 2,
            channels * 2,
            5,
            padding=2,
            groups=channels * 2,
        )
        self.project = nn.Conv2d(channels, channels, 1)
        self.gamma = nn.Parameter(torch.full((1, channels, 1, 1), 0.1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.spatial(self.expand(self.norm(x))).chunk(2, dim=1)
        return x + self.gamma * self.project(a * torch.sigmoid(b))


class FastStudentV1(nn.Module):
    """Guide-conditioned recurrent U-Net with a low-resolution temporal core."""

    def __init__(self, config: FastStudentConfig | None = None):
        super().__init__()
        self.config = config or FastStudentConfig()
        self.config.validate()
        c = self.config.base_width
        m = self.config.mid_width
        h = self.config.temporal_hidden
        n = self.config.blocks

        # The first grid sees the current RGB and all five native guide
        # channels.  Guides are resized, never reinterpreted as optical flow.
        self.stem = nn.Conv2d(3 + self.config.guide_channels, c, 3, padding=1)
        self.encoder = nn.Sequential(*(DepthwiseResidualBlock(c) for _ in range(n)))
        self.down = nn.Conv2d(c, m, 3, stride=2, padding=1)
        self.bottleneck = nn.Sequential(
            *(DepthwiseResidualBlock(m) for _ in range(n + 1))
        )

        # Context is a whole-eye conditioning signal.  Pooling it to a compact
        # affine vector keeps its cost independent of the render surface size.
        self.context_summary = nn.Sequential(
            nn.Conv2d(self.config.context_channels, 32, 3, stride=2, padding=1),
            nn.SiLU(),
            nn.Conv2d(32, 48, 3, stride=2, padding=1),
            nn.SiLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.context_affine = nn.Conv2d(48, 2 * m, 1)

        # Recurrent state lives at 1/8 of the native model input.  The input
        # contains current RGB, previous output, and the native guide bundle.
        # ``mid`` is projected into the same grid and fused into the GRU cell.
        self.temporal_encode = nn.Conv2d(3 + 3 + self.config.guide_channels, h, 3, padding=1)
        self.temporal_gates = nn.Conv2d(h * 2, h * 2, 3, padding=1)
        self.temporal_candidate = nn.Conv2d(h * 2, h, 3, padding=1)
        self.temporal_to_mid = nn.Conv2d(h, m, 1)

        self.decode = nn.Sequential(
            nn.Conv2d(m, c, 1),
            nn.SiLU(),
            *(DepthwiseResidualBlock(c) for _ in range(n)),
        )
        residual_channels = 1 if self.config.residual_mode == "luma" else 3
        self.low_residual = nn.Conv2d(c, residual_channels, 3, padding=1)

        # This is the only native-resolution learned operation: a three-channel
        # residual refine over RGB plus the upsampled low-grid residual.  It is
        # intentionally shallow so full-resolution work remains inexpensive.
        self.native_refine = nn.Conv2d(3 + residual_channels, residual_channels, 3, padding=1)

        # Exact identity initialization.  The direct low residual path keeps
        # gradients useful while native_refine starts as a no-op.
        nn.init.zeros_(self.low_residual.weight)
        nn.init.zeros_(self.low_residual.bias)
        nn.init.zeros_(self.native_refine.weight)
        nn.init.zeros_(self.native_refine.bias)

    @staticmethod
    def _ceil_div(value: int, divisor: int) -> int:
        return (value + divisor - 1) // divisor

    def _grid_sizes(self, height: int, width: int) -> tuple[tuple[int, int], tuple[int, int]]:
        first = (
            max(1, self._ceil_div(height, self.config.model_scale)),
            max(1, self._ceil_div(width, self.config.model_scale)),
        )
        temporal = (
            max(1, self._ceil_div(height, self.config.temporal_downsample)),
            max(1, self._ceil_div(width, self.config.temporal_downsample)),
        )
        return first, temporal

    def state_shapes(self, height: int, width: int) -> dict[str, tuple[int, ...]]:
        """Return the fixed runtime binding shapes for a one-item batch."""

        _, temporal = self._grid_sizes(height, width)
        return {
            "hidden": (1, self.config.temporal_hidden, temporal[0], temporal[1]),
            "previous": (1, 3, height, width),
        }

    def _temporal_step(
        self,
        mid: torch.Tensor,
        rgb: torch.Tensor,
        guides: torch.Tensor,
        previous: torch.Tensor,
        state: torch.Tensor | None,
    ) -> torch.Tensor:
        temporal_size = mid.shape[-2:]
        rgb_small = F.interpolate(rgb, size=temporal_size, mode="bilinear", align_corners=False)
        previous_small = F.interpolate(
            previous, size=temporal_size, mode="bilinear", align_corners=False
        )
        guides_small = F.interpolate(
            guides, size=temporal_size, mode="bilinear", align_corners=False
        )
        temporal_input = self.temporal_encode(
            torch.cat((rgb_small, previous_small, guides_small), dim=1)
        )
        if state is None:
            state = torch.zeros(
                temporal_input.shape[0],
                self.config.temporal_hidden,
                temporal_input.shape[-2],
                temporal_input.shape[-1],
                dtype=temporal_input.dtype,
                device=temporal_input.device,
            )
        elif state.shape != temporal_input.shape:
            raise ValueError(
                f"hidden state shape {tuple(state.shape)} does not match "
                f"{tuple(temporal_input.shape)}"
            )
        gates = self.temporal_gates(torch.cat((temporal_input, state), dim=1))
        update, reset = gates.chunk(2, dim=1)
        update = torch.sigmoid(update)
        reset = torch.sigmoid(reset)
        candidate = torch.tanh(
            self.temporal_candidate(torch.cat((temporal_input, reset * state), dim=1))
        )
        return (1.0 - update) * state + update * candidate

    def forward_temporal(
        self,
        rgb: torch.Tensor,
        guides: torch.Tensor,
        context: torch.Tensor,
        state: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        """Run one causal frame and return ``prediction, (hidden, previous)``."""

        if rgb.ndim != 4 or rgb.shape[1] != 3:
            raise ValueError("rgb must have shape [batch, 3, height, width]")
        if guides.ndim != 4 or guides.shape[1] != self.config.guide_channels:
            raise ValueError("guides must have shape [batch, 5, height, width]")
        if context.ndim != 4 or context.shape[1] != self.config.context_channels:
            raise ValueError("context must have shape [batch, 8, height, width]")

        height, width = rgb.shape[-2:]
        first_size, _ = self._grid_sizes(height, width)
        rgb_first = F.interpolate(rgb, size=first_size, mode="bilinear", align_corners=False)
        guides_first = F.interpolate(
            guides, size=first_size, mode="bilinear", align_corners=False
        )
        encoded = self.encoder(self.stem(torch.cat((rgb_first, guides_first), dim=1)))
        mid = self.down(encoded)

        context_vector = self.context_affine(self.context_summary(context))
        gain, bias = context_vector.chunk(2, dim=1)
        mid = mid * (1.0 + 0.1 * torch.tanh(gain)) + 0.1 * bias
        mid = self.bottleneck(mid)

        previous = rgb if state is None else state[1]
        hidden = None if state is None else state[0]
        next_hidden = self._temporal_step(mid, rgb, guides, previous, hidden)
        mid = mid + self.temporal_to_mid(next_hidden)

        decoded = self.decode(F.interpolate(mid, size=encoded.shape[-2:], mode="bilinear", align_corners=False))
        low_residual = self.low_residual(decoded)
        residual = F.interpolate(
            low_residual, size=(height, width), mode="bilinear", align_corners=False
        )
        if self.config.use_native_refine:
            refined = self.native_refine(torch.cat((rgb, residual), dim=1))
        else:
            # Profiling-only ablation: the production residual student should
            # use a fused native-frame compositor instead of this learned
            # full-resolution convolution.
            refined = torch.zeros_like(residual)
        signal = torch.tanh(residual + refined)
        if self.config.residual_mode == "luma":
            # The neural-upstream colour restore uses the network response as
            # a per-pixel luminance gain.  A learned one-channel signal keeps
            # the renderer's authored hue/saturation intact while still
            # allowing local tone/detail changes.
            gain = 1.0 + self.config.residual_scale * signal
            prediction = (rgb * gain).clamp(0.0, 1.0)
        else:
            prediction = (rgb + self.config.residual_scale * signal).clamp(0.0, 1.0)
        return prediction, (next_hidden, prediction)

    def forward(
        self,
        rgb: torch.Tensor,
        guides: torch.Tensor,
        context: torch.Tensor,
    ) -> torch.Tensor:
        prediction, _ = self.forward_temporal(rgb, guides, context, None)
        return prediction


class ScaleConditionedFastStudent(nn.Module):
    """Run FastStudentV1 at reduced work size and resolve at full size.

    The wrapped model owns recurrent state on the reduced grid. The wrapper
    returns a full-resolution prediction for supervision/evaluation while
    preserving that work-resolution state contract. This mirrors the
    matched-residual composition used by the public NeuralScreen path.
    """

    def __init__(self, model: FastStudentV1, work_scale: float):
        super().__init__()
        if not 0.0 < float(work_scale) <= 1.0:
            raise ValueError("work_scale must be in (0, 1]")
        self.model = model
        self.work_scale = float(work_scale)

    @staticmethod
    def _scaled(value: int, scale: float) -> int:
        return max(1, int(round(value * scale)))

    def work_size(self, height: int, width: int) -> tuple[int, int]:
        return self._scaled(height, self.work_scale), self._scaled(width, self.work_scale)

    def forward_temporal(
        self,
        rgb: torch.Tensor,
        guides: torch.Tensor,
        context: torch.Tensor,
        state: tuple[torch.Tensor, torch.Tensor] | None = None,
    ) -> tuple[torch.Tensor, tuple[torch.Tensor, torch.Tensor]]:
        height, width = rgb.shape[-2:]
        work_height, work_width = self.work_size(height, width)
        work_rgb = F.interpolate(
            rgb, size=(work_height, work_width), mode="bilinear", align_corners=False
        )
        work_guides = F.interpolate(
            guides,
            size=(
                self._scaled(guides.shape[-2], self.work_scale),
                self._scaled(guides.shape[-1], self.work_scale),
            ),
            mode="bilinear",
            align_corners=False,
        )
        work_prediction, next_state = self.model.forward_temporal(
            work_rgb, work_guides, context, state
        )
        work_residual = work_prediction - work_rgb
        residual = F.interpolate(
            work_residual, size=(height, width), mode="bilinear", align_corners=False
        )
        prediction = (rgb + residual).clamp(0.0, 1.0)
        return prediction, next_state


def config_dict(config: FastStudentConfig) -> dict:
    """Serialize a config without relying on dataclass internals downstream."""

    config.validate()
    return asdict(config)


def load_fast_student(path: str | Path, device: str | torch.device = "cpu") -> tuple[FastStudentV1, dict]:
    """Load an isolated FastStudent-v1 checkpoint for evaluation/export."""

    checkpoint = torch.load(path, map_location=device, weights_only=False)
    if checkpoint.get("architecture") != "fast_student_v1":
        raise ValueError("Checkpoint is not a fast_student_v1 checkpoint")
    model = FastStudentV1(FastStudentConfig(**checkpoint["config"])).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, checkpoint
