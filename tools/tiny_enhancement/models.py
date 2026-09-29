"""Pure-PyTorch tiny RGB enhancement adapters.

The implementations preserve the central ideas of the upstream references:

* Image-Adaptive 3D LUT: a small image encoder mixes learned basis LUTs.
* SVDLUT: low-rank separable LUT factors plus a low-resolution spatial mixer.
* Zero-DCE++: the official depthwise/pointwise curve estimator, changed only
  to identity initialization and direct paired supervision for this study.
* SRVGGNetCompact: the compact VGG body with its upsampler removed and a
  bounded native-resolution residual output.

The study intentionally uses a torch ``grid_sample`` trilinear path instead
of compiling the upstream custom interpolation extensions.  This keeps the
comparison reproducible on the local RTX 5070 Ti and makes the measured path
explicit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F


def _identity_lut(dim: int, device: torch.device | None = None) -> torch.Tensor:
    values = torch.linspace(0.0, 1.0, dim, device=device)
    red, green, blue = torch.meshgrid(values, values, values, indexing="ij")
    return torch.stack((red, green, blue), dim=0)


def _sample_lut(lut: torch.Tensor, image: torch.Tensor) -> torch.Tensor:
    """Apply a [B,3,D,D,D] LUT to [B,3,H,W] RGB values.

    ``grid_sample`` orders the 5-D LUT coordinates as width/height/depth.
    The LUT is stored as red/green/blue depth axes, so the RGB query is
    reversed to [blue, green, red] for the grid.
    """

    grid = image.permute(0, 2, 3, 1)[..., (2, 1, 0)]
    grid = grid.mul(2.0).sub(1.0).unsqueeze(1)
    sampled = F.grid_sample(
        lut,
        grid,
        mode="bilinear",
        padding_mode="border",
        align_corners=True,
    )
    return sampled.squeeze(2)


class _LowResEncoder(nn.Module):
    def __init__(self, out_channels: int = 48):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(3, 16, 3, stride=2, padding=1),
            nn.SiLU(inplace=True),
            nn.Conv2d(16, 32, 3, stride=2, padding=1),
            nn.SiLU(inplace=True),
            nn.Conv2d(32, out_channels, 3, stride=2, padding=1),
            nn.SiLU(inplace=True),
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return self.body(F.interpolate(image, size=(64, 64), mode="area"))


@dataclass(frozen=True)
class Adaptive3DLUTConfig:
    name: str = "adaptive_3dlut"
    basis: int = 5
    lut_dim: int = 17
    encoder_channels: int = 48
    residual_bound: float = 1.0


class Adaptive3DLUT(nn.Module):
    """Image-Adaptive-3DLUT-style paired RGB adapter."""

    def __init__(self, config: Adaptive3DLUTConfig | None = None):
        super().__init__()
        self.config = config or Adaptive3DLUTConfig()
        self.encoder = _LowResEncoder(self.config.encoder_channels)
        self.selector = nn.Linear(self.config.encoder_channels, self.config.basis)
        identity = _identity_lut(self.config.lut_dim)
        self.register_buffer("identity", identity)
        self.basis_delta = nn.Parameter(torch.empty(self.config.basis, 3, self.config.lut_dim, self.config.lut_dim, self.config.lut_dim))
        nn.init.normal_(self.basis_delta, mean=0.0, std=1e-4)
        nn.init.zeros_(self.selector.weight)
        nn.init.zeros_(self.selector.bias)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        features = self.encoder(image)
        pooled = F.adaptive_avg_pool2d(features, 1).flatten(1)
        weights = self.selector(pooled).softmax(dim=1)
        basis = self.identity.unsqueeze(0) + self.config.residual_bound * torch.tanh(self.basis_delta)
        lut = torch.einsum("bk,kcxyz->bcxyz", weights, basis)
        return _sample_lut(lut, image).clamp(0.0, 1.0)


@dataclass(frozen=True)
class SVDLUTConfig:
    name: str = "svdlut"
    basis: int = 4
    lut_dim: int = 17
    singular: int = 4
    encoder_channels: int = 32


class SVDLUT(nn.Module):
    """SVDLUT-style low-rank LUTs with a cache-friendly spatial mixer."""

    def __init__(self, config: SVDLUTConfig | None = None):
        super().__init__()
        self.config = config or SVDLUTConfig()
        self.encoder = _LowResEncoder(self.config.encoder_channels)
        self.spatial_selector = nn.Conv2d(self.config.encoder_channels, self.config.basis, 1)
        self.global_selector = nn.Linear(self.config.encoder_channels, self.config.basis)
        shape = (self.config.basis, 3, self.config.singular, self.config.lut_dim)
        self.factor_r = nn.Parameter(torch.zeros(shape))
        self.factor_g = nn.Parameter(torch.zeros(shape))
        self.factor_b = nn.Parameter(torch.zeros(shape))
        self._initialize_factors()
        nn.init.zeros_(self.spatial_selector.weight)
        nn.init.zeros_(self.spatial_selector.bias)
        nn.init.zeros_(self.global_selector.weight)
        nn.init.zeros_(self.global_selector.bias)

    def _initialize_factors(self) -> None:
        dim = self.config.lut_dim
        axis = torch.linspace(0.0, 1.0, dim)
        with torch.no_grad():
            for basis in range(self.config.basis):
                for channel in range(3):
                    rank = channel % self.config.singular
                    self.factor_r[basis, channel, rank].fill_(1.0)
                    self.factor_g[basis, channel, rank].fill_(1.0)
                    self.factor_b[basis, channel, rank].fill_(1.0)
                    if channel == 0:
                        self.factor_r[basis, channel, rank].copy_(axis)
                    elif channel == 1:
                        self.factor_g[basis, channel, rank].copy_(axis)
                    else:
                        self.factor_b[basis, channel, rank].copy_(axis)
            # Break otherwise exact basis symmetry without creating a visible
            # non-identity initialization at study precision.
            self.factor_r.add_(torch.randn_like(self.factor_r) * 1e-4)
            self.factor_g.add_(torch.randn_like(self.factor_g) * 1e-4)
            self.factor_b.add_(torch.randn_like(self.factor_b) * 1e-4)

    def _basis_luts(self) -> torch.Tensor:
        return torch.einsum(
            "bcrx,bcry,bcrz->bcxyz", self.factor_r, self.factor_g, self.factor_b
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        features = self.encoder(image)
        global_features = F.adaptive_avg_pool2d(features, 1).flatten(1)
        global_logits = self.global_selector(global_features).unsqueeze(-1).unsqueeze(-1)
        spatial_logits = self.spatial_selector(features) + global_logits
        weights = F.softmax(spatial_logits, dim=1)
        weights = F.interpolate(weights, size=image.shape[-2:], mode="bilinear", align_corners=False)

        basis_luts = self._basis_luts()
        batch, basis, _, dim, _, _ = (image.shape[0], self.config.basis, 3, self.config.lut_dim, 0, 0)
        del dim
        tiled_lut = basis_luts.unsqueeze(0).expand(batch, -1, -1, -1, -1, -1)
        tiled_lut = tiled_lut.reshape(batch * basis, 3, self.config.lut_dim, self.config.lut_dim, self.config.lut_dim)
        tiled_image = image.unsqueeze(1).expand(-1, basis, -1, -1, -1).reshape(batch * basis, 3, *image.shape[-2:])
        sampled = _sample_lut(tiled_lut, tiled_image).reshape(batch, basis, 3, *image.shape[-2:])
        return (sampled * weights.unsqueeze(2)).sum(dim=1).clamp(0.0, 1.0)


class _CSDNTem(nn.Module):
    """Zero-DCE++ depthwise + pointwise block."""

    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.depth_conv = nn.Conv2d(in_channels, in_channels, 3, padding=1, groups=in_channels)
        self.point_conv = nn.Conv2d(in_channels, out_channels, 1)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.point_conv(self.depth_conv(value))


@dataclass(frozen=True)
class ZeroDCEConfig:
    name: str = "zero_dce_supervised"
    feature_channels: int = 32
    scale_factor: int = 4
    curve_steps: int = 8


class ZeroDCEPlusPlus(nn.Module):
    """Supervised paired adaptation of the Zero-DCE++ curve network."""

    def __init__(self, config: ZeroDCEConfig | None = None):
        super().__init__()
        self.config = config or ZeroDCEConfig()
        f = self.config.feature_channels
        self.relu = nn.ReLU(inplace=True)
        self.e_conv1 = _CSDNTem(3, f)
        self.e_conv2 = _CSDNTem(f, f)
        self.e_conv3 = _CSDNTem(f, f)
        self.e_conv4 = _CSDNTem(f, f)
        self.e_conv5 = _CSDNTem(f * 2, f)
        self.e_conv6 = _CSDNTem(f * 2, f)
        self.e_conv7 = _CSDNTem(f * 2, 3)
        nn.init.zeros_(self.e_conv7.point_conv.weight)
        nn.init.zeros_(self.e_conv7.point_conv.bias)

    def _enhance(self, image: torch.Tensor, curves: torch.Tensor) -> torch.Tensor:
        current = image
        for step in range(self.config.curve_steps):
            current = current + curves * (current.square() - current)
        return current

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        scale = self.config.scale_factor
        reduced = image if scale == 1 else F.interpolate(image, scale_factor=1.0 / scale, mode="bilinear", align_corners=False)
        x1 = self.relu(self.e_conv1(reduced))
        x2 = self.relu(self.e_conv2(x1))
        x3 = self.relu(self.e_conv3(x2))
        x4 = self.relu(self.e_conv4(x3))
        x5 = self.relu(self.e_conv5(torch.cat((x3, x4), dim=1)))
        x6 = self.relu(self.e_conv6(torch.cat((x2, x5), dim=1)))
        curves = torch.tanh(self.e_conv7(torch.cat((x1, x6), dim=1)))
        if scale != 1:
            curves = F.interpolate(curves, size=image.shape[-2:], mode="bilinear", align_corners=False)
        return self._enhance(image, curves).clamp(0.0, 1.0)


@dataclass(frozen=True)
class SRVGGConfig:
    name: str = "srvgg_same_res"
    num_feat: int = 48
    num_conv: int = 8
    activation: str = "prelu"
    residual_bound: float = 1.0


class SRVGGSameRes(nn.Module):
    """Native-resolution residual version of Real-ESRGAN's SRVGG body."""

    def __init__(self, config: SRVGGConfig | None = None):
        super().__init__()
        self.config = config or SRVGGConfig()
        body: list[nn.Module] = [nn.Conv2d(3, self.config.num_feat, 3, padding=1)]
        body.append(self._activation(self.config.num_feat))
        for _ in range(self.config.num_conv):
            body.append(nn.Conv2d(self.config.num_feat, self.config.num_feat, 3, padding=1))
            body.append(self._activation(self.config.num_feat))
        self.body = nn.Sequential(*body)
        self.final = nn.Conv2d(self.config.num_feat, 3, 3, padding=1)
        nn.init.zeros_(self.final.weight)
        nn.init.zeros_(self.final.bias)

    def _activation(self, channels: int) -> nn.Module:
        if self.config.activation == "relu":
            return nn.ReLU(inplace=True)
        if self.config.activation == "leakyrelu":
            return nn.LeakyReLU(0.1, inplace=True)
        return nn.PReLU(num_parameters=channels)

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        residual = self.final(self.body(image))
        return (image + self.config.residual_bound * torch.tanh(residual)).clamp(0.0, 1.0)


MODEL_CONFIGS: dict[str, Any] = {
    "adaptive_3dlut": Adaptive3DLUTConfig,
    "svdlut": SVDLUTConfig,
    "zero_dce_supervised": ZeroDCEConfig,
    "srvgg_same_res": SRVGGConfig,
}

MODEL_CLASSES: dict[str, type[nn.Module]] = {
    "adaptive_3dlut": Adaptive3DLUT,
    "svdlut": SVDLUT,
    "zero_dce_supervised": ZeroDCEPlusPlus,
    "srvgg_same_res": SRVGGSameRes,
}


def build_model(name: str, config: dict[str, Any] | None = None) -> nn.Module:
    if name not in MODEL_CLASSES:
        raise ValueError(f"unknown tiny model: {name}")
    config_type = MODEL_CONFIGS[name]
    return MODEL_CLASSES[name](config_type(**(config or {})))


def model_config(model: nn.Module) -> dict[str, Any]:
    value = getattr(model, "config", None)
    if value is None:
        return {}
    return asdict(value)


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def identity_error(model: nn.Module, device: torch.device) -> float:
    model.eval()
    with torch.inference_mode():
        sample = torch.rand(2, 3, 64, 64, device=device)
        output = model(sample)
        return float((output - sample).abs().mean().item())

