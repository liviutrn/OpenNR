"""Wider context-v4 spatial student used for a controlled capacity ablation."""

from __future__ import annotations

from dataclasses import dataclass

from student_v2 import ReconstructionConfig
from student_v4 import StyleContextStudent


@dataclass
class WideConfig:
    width: int = 96
    blocks: int = 5
    scale: int = 4


class WideStyleContextStudent(StyleContextStudent):
    """Context-v4 with a wider/deeper inherited multiscale backbone."""

    architecture = "context_v8_wide"

    def __init__(self, config: WideConfig = WideConfig()):
        if config.width < 80:
            raise ValueError("Wide model width is too small")
        if config.blocks < 4:
            raise ValueError("Wide model block count is too small")
        super().__init__(
            ReconstructionConfig(width=config.width, blocks=config.blocks, scale=config.scale)
        )
        self.wide_config = config

