ARG BASE_IMAGE=pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    TORCH_CUDA_ARCH_LIST="8.9" \
    FORCE_CUDA=1 \
    CUDA_HOME=/usr/local/cuda \
    CUDA_MODULE_LOADING=LAZY \
    TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1 \
    NVIDIA_TF32_OVERRIDE=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    PYTHONPATH="/code/third-party/DPVO:/code/third-party/DPVO/dpvo:/opt/wham-src/third-party/DPVO:/opt/wham-src/third-party/DPVO/dpvo"

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        git \
        libglib2.0-0 \
        libgl1 \
        ninja-build \
        unzip \
        wget \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /tmp/ultralytics && chmod 777 /tmp/ultralytics

WORKDIR /opt/wham-src

COPY requirements.txt /tmp/wham-requirements.txt

RUN python -m pip install --no-cache-dir --upgrade \
        pip \
        "setuptools<81" \
        wheel \
        packaging \
        "numpy==1.26.4" \
        cython \
        ninja

RUN python -m pip install --no-cache-dir "mmengine==0.10.7"

RUN MMCV_WITH_OPS=1 python -m pip install --no-cache-dir --no-build-isolation "mmcv==2.1.0"

RUN python -m pip install --no-cache-dir --no-build-isolation \
        "chumpy @ git+https://github.com/mattloper/chumpy"

RUN python -m pip install --no-cache-dir \
        "mmpose==1.3.2" \
        "mmdet==3.2.0" \
        "mmpretrain==1.2.0" \
        "timm==1.0.27" \
        "ultralytics==8.4.69" \
        "gdown>=5.0.0" \
        "numba" \
        "kornia" \
        "pypose" \
        "evo" \
        "opencv-python-headless" \
        "imageio[ffmpeg]" \
        "matplotlib" \
        "tensorboard" \
        "smplx" \
        "progress" \
        "einops" \
        "munkres" \
        "xtcocotools>=1.8" \
        "loguru" \
        "yacs" \
        "joblib" \
        "scikit-image" \
        "tqdm" \
        "json_tricks"

RUN python -m pip install --no-cache-dir --no-build-isolation "torch-scatter==2.1.2"

RUN python -m pip install --no-cache-dir --force-reinstall "numpy==1.26.4"

COPY third-party/DPVO /opt/wham-src/third-party/DPVO
WORKDIR /opt/wham-src/third-party/DPVO
RUN if [ ! -d thirdparty/eigen-3.4.0 ]; then \
        wget -q https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.zip && \
        unzip -q eigen-3.4.0.zip -d thirdparty && \
        rm eigen-3.4.0.zip; \
    fi && \
    python -m pip install --no-cache-dir --no-build-isolation .

COPY . /opt/wham-src

WORKDIR /code
CMD ["bash"]
