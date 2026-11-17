import os
from pathlib import Path


_MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "Qwen3.5-9B-Q6_K"
DEFAULT_LLAMA_CPP_BIN_DIR = "C:\\llama.cpp\\current"
DEFAULT_LLAMA_CPP_SERVER_COMMAND = os.environ.get(
    "EXERCISE_MOTION_LLAMA_CPP_SERVER_COMMAND",
    f"{DEFAULT_LLAMA_CPP_BIN_DIR}\\llama-server.exe",
)
DEFAULT_LLAMA_CPP_MODEL = str(_MODEL_DIR / "Qwen3.5-9B-Q6_K.gguf")
DEFAULT_LLAMA_CPP_MMPROJ = str(_MODEL_DIR / "mmproj-BF16.gguf")
DEFAULT_LLAMA_CPP_MTP_MODEL = None
DEFAULT_LLAMA_CPP_SPEC_DRAFT_N_MAX = 3
# N-gram speculative decoding is off: measured 2026-11-14 on b12380 + UD-Q4_K_XL,
# identical vision payload, only this flag differing -> 56.64 t/s decode without it vs
# 47.78 t/s with it (draft acceptance 19.9%, too low to pay for verification). Left
# env-overridable so the pure-JSON contract prompts can be re-measured on their own.
DEFAULT_LLAMA_CPP_SPEC_TYPE = os.environ.get("EXERCISE_MOTION_LLAMA_CPP_SPEC_TYPE") or None
# Send the vision encoder to the second GPU so encoding overlaps decode. Needs both GPUs
# visible: the exclusive GPU lane pins llama to GPU 0, which disables this.
DEFAULT_LLAMA_CPP_MMPROJ_DEVICE = os.environ.get("EXERCISE_MOTION_LLAMA_CPP_MMPROJ_DEVICE", "CUDA1")
DEFAULT_TEXT_LLAMA_CPP_MODEL = DEFAULT_LLAMA_CPP_MODEL
DEFAULT_TEXT_LLAMA_CPP_MMPROJ = None
DEFAULT_EXERCISE_CONTRACT_LLAMA_CPP_MODEL = DEFAULT_LLAMA_CPP_MODEL
DEFAULT_EXERCISE_CONTRACT_LLAMA_CPP_MMPROJ = DEFAULT_TEXT_LLAMA_CPP_MMPROJ
# Motion discovery and validation are structured classification tasks. Greedy
# decoding removes run-to-run candidate drift and avoids stochastic expansions
# that can multiply the number of reviewed chunks.
DEFAULT_LLAMA_CPP_TEMPERATURE = 0.0
DEFAULT_LLAMA_CPP_TOP_P = 1.0
DEFAULT_LLAMA_CPP_TOP_K = 0
DEFAULT_LLAMA_CPP_REASONING_BUDGET = 64
DEFAULT_LLAMA_CPP_REASONING_BUDGET_MESSAGE = "Now stop thinking and return the JSON object."
# Source reviews exceed 10K tokens; keep 16K per slot. Measured 2026-11-14 on b12380 +
# UD-Q4_K_XL with mmproj on the second GPU: aggregate decode scaled 48.5 -> 79.9 -> 102.4
# t/s at 1/2/4 concurrent requests. Beyond 4 does not fit: 4 slots at 64K peaked at
# 11569 of 12282 MiB. This also matches the 4 vision review workers.
DEFAULT_LLAMA_CPP_PARALLEL = 4
DEFAULT_LLAMA_CPP_CTX_SIZE = 16384 * DEFAULT_LLAMA_CPP_PARALLEL
DEFAULT_LLAMA_CPP_BATCH_SIZE = 1024
DEFAULT_LLAMA_CPP_UBATCH_SIZE = 512
DEFAULT_LLAMA_CPP_FLASH_ATTN = "on"
DEFAULT_LLAMA_CPP_CACHE_TYPE_K = "q8_0"
DEFAULT_LLAMA_CPP_CACHE_TYPE_V = "q8_0"
DEFAULT_LLAMA_CPP_FIT = "on"
DEFAULT_LLAMA_CPP_FIT_CTX = DEFAULT_LLAMA_CPP_CTX_SIZE
DEFAULT_LLAMA_CPP_FIT_TARGET = 2048
DEFAULT_LLAMA_CPP_MMAP = True
DEFAULT_LLAMA_CPP_MLOCK = False
DEFAULT_LLAMA_CPP_IMAGE_MIN_TOKENS = 1024
DEFAULT_LLAMA_CPP_IMAGE_MAX_TOKENS = 2048
# Must be >= IMAGE_MIN_TOKENS or each image is split across extra encoder passes;
# llama.cpp b12380 defaults this to 1024.
DEFAULT_LLAMA_CPP_MTMD_BATCH_MAX_TOKENS = 1024
