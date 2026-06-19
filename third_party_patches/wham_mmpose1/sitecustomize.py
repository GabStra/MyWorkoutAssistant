from __future__ import annotations

import os

import torch


if os.environ.get("WHAM_TRUSTED_LEGACY_TORCH_LOAD", "1") != "0":
    _original_torch_load = torch.load

    def _torch_load_with_legacy_checkpoint_support(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return _original_torch_load(*args, **kwargs)

    torch.load = _torch_load_with_legacy_checkpoint_support
