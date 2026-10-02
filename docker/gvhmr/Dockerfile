# GVHMR inference image. Build context: third_party/GVHMR
#   docker build -t myworkoutassistant/gvhmr:torch2.3-cu121 -f docker/gvhmr/Dockerfile third_party/GVHMR
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-devel

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_MODULE_LOADING=LAZY \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        unzip \
        wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/gvhmr

COPY requirements.txt /tmp/gvhmr-requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip "setuptools<81" wheel packaging

# Pinned torch 2.3.0+cu121 comes from the base image; installing the rest of the
# pinned stack (hydra/lightning/pytorch3d wheel etc.).
# chumpy first from git: its PyPI sdist breaks under modern pip build isolation.
RUN python -m pip install --no-cache-dir --no-build-isolation \
        "chumpy @ git+https://github.com/mattloper/chumpy"
RUN python -m pip install --no-cache-dir -r /tmp/gvhmr-requirements.txt

COPY . /opt/gvhmr
RUN python -m pip install --no-cache-dir --no-build-isolation -e .

# Pretrained weights are downloaded on the host into third_party/GVHMR/inputs
# (gitignored) and copied in. GVHMR license is research/non-profit only.
COPY inputs/checkpoints /opt/gvhmr/inputs/checkpoints

# Startup-cost levers, measured 2026-10-02:
# - COPY does not byte-compile the application tree (pip does this for
#   site-packages), so every cold import recompiled /opt/gvhmr from source.
# - The model checkpoint loads pay a full eager read; mmap=True streams them
#   from the page cache instead. Tensor parity was verified against the
#   plain-load image on a real extraction job before this became default.
RUN sed -i \
        -e 's/torch\.load(ckpt_path, "cpu")/torch.load(ckpt_path, "cpu", mmap=True)/' \
        -e 's/check = torch\.load(checkpoint)/check = torch.load(checkpoint, mmap=True)/' \
            /opt/gvhmr/hmr4d/model/gvhmr/gvhmr_pl_demo.py \
            /opt/gvhmr/hmr4d/model/gvhmr/gvhmr_pl.py \
            /opt/gvhmr/hmr4d/utils/net_utils.py \
            /opt/gvhmr/hmr4d/utils/preproc/vitpose_pytorch/src/vitpose_infer/model_builder.py \
            /opt/gvhmr/hmr4d/utils/preproc/vitpose_pytorch/src/vitpose_infer/builder/model_builder.py \
    && python -m compileall -q /opt/gvhmr

WORKDIR /opt/gvhmr
CMD ["bash"]
