# Configuring AMD 4650GE APU GPU Memory for LLM Inference

## Background

The AMD Ryzen 5 PRO 4650GE contains an integrated Vega 7 GPU (GCN5/gfx900
architecture) that shares system RAM with the CPU. Unlike discrete GPUs with
dedicated VRAM, the iGPU accesses system memory through two mechanisms:

- **VRAM carveout** — a small region of RAM reserved exclusively for the GPU,
  configured in BIOS. Used for the framebuffer and legacy applications. This
  is what most tools report as "VRAM".
- **GTT (Graphics Translation Table)** — a much larger pool of system RAM that
  the GPU can access for compute workloads via the GART (Graphics Address
  Remapping Table). This is what LLM inference actually uses and what this guide
  targets for iGPU compute.

By default, the kernel limits GTT to approximately **50% of total system RAM**.
On a 64GB system this gives ~30GB of GPU-accessible memory — enough for smaller
models but insufficient for 27B+ parameter models at useful quantizations.

The GTT pool is dynamic: memory is only allocated when the GPU actually needs
it, and the OS can reclaim pages when the GPU is idle. This makes GTT-backed
allocations preferable to large VRAM carveouts, which permanently remove memory
from the OS regardless of whether the GPU is using it.

## Target hardware

A Lenovo ThinkCentre M75q Tiny G2 with AMD 4650GE APU, 64GB RAM, and Ubuntu 26.04.

This hardware is not particularly well suited to running LLMs. Applying the configuration in this document and running a recent Ollama version with Vulkan GPU acceleration achieves prefill speeds of ~100 t/s on long prompts and 14–14.5 t/s on generation for Qwen3.6-35B (a 35B-parameter MoE model with 3B active parameters). Gemma4-26B (a 26B A4B MoE model) also gives similar numbers, though slightly slower on generation.

The "unified memory" popularized by Apple and others is actually present on this AMD hardware too — the GPU can access pretty much all the RAM in the PC if configured to do so. As mentioned above, the default settings limit this to 50% of RAM; this guide describes how to increase it significantly. Up to 56GiB GPU memory (out of 64) seems to work fine and this configuration allows both Qwen3.6-35B and Gemma4-26B to be loaded at the same time. Note that some memory must always be available for the OS.

If testing similar hardware with less memory, make sure both memory channels are populated with DIMMs since token generation is almost completely dependent on memory bandwidth.

---

## Recommended firmware Settings

Set the VRAM carveout (may be labelled "UMA Frame Buffer Size", "IGPU Memory",
or similar) in the PC's UEFI setup or BIOS to the minimum your system allows. A large video RAM carveout reduces available GTT and provides no benefit for compute workloads.

---

## Step 1: Increase GTT Size and GPU compute timeout

GTT is the address space; TTM (Translation Table Manager) is the kernel's
actual page allocation budget.

The TTM limit is expressed in **4KB pages**. For 48GB:

```
48 × 1024 × 1024 / 4 = 12582912 pages
```

With larger memory mappings, GPU compute jobs (particularly LLM prefill passes)
may take longer than the default 10-second timeout, causing spurious ring resets
and inference crashes. We fix this with another line in the same config file.

Create a modprobe configuration file `/etc/modprobe.d/amdgpu.conf` with this content:

```bash
# increase GPU memory allocation limits and pool size (number of 4K memory pages)
options ttm pages_limit=12582912 page_pool_size=12582912

# increase CPU compute ring timeout (milliseconds, default 10000)
options amdgpu lockup_timeout=50000
```

Both `pages_limit` (hard allocation ceiling) and `page_pool_size`
(pre-allocated pool) should be set to the same value to avoid allocation
failures.

Rebuild initramfs to include the new configuration:

```bash
sudo update-initramfs -u
sudo reboot
```

After this, the following command should report the expected GTT memory:
```bash
sudo dmesg | grep -i "amdgpu" | grep -iE "gtt|vram"
```

---

## Step 2: Enable Transparent Hugepages

With a 48GB GTT pool, the GPU's IOMMU must manage millions of 4KB page table
entries during inference. Transparent Hugepages (THP) consolidates these into
2MB pages, reducing TLB pressure by 512× and improving sustained memory
throughput — particularly during prefill.

### Immediate (no reboot required)

```bash
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/shmem_enabled
echo defer+madvise | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
```

`defer+madvise` for defrag avoids latency spikes from aggressive page
compaction while still forming hugepages opportunistically.

### Persistent (survives reboot)

Create the file `/etc/tmpfiles.d/thp.conf` with this content:
```bash
w /sys/kernel/mm/transparent_hugepage/enabled - - - - always
w /sys/kernel/mm/transparent_hugepage/shmem_enabled - - - - always
w /sys/kernel/mm/transparent_hugepage/defrag - - - - defer+madvise
```

---

## Step 3: Configure Ollama

Install Ollama according to https://ollama.com/download

Make sure to use a recent version, 0.30.x or later.

Also follow the Vulkan setup instructions here:
https://docs.ollama.com/gpu#vulkan-gpu-support


Create a systemd override to adjust relevant Ollama settings:

Running `sudo systemctl edit ollama.service` will open an editor. After saving, the service is reloaded automatically.


```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"           # if serving via local LAN
Environment="OLLAMA_CONTEXT_LENGTH=131072"  # adjust to your use case
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_IGPU_ENABLE=1"          # enable integrated GPUs
Environment="OLLAMA_VULKAN=1"               # use Vulkan
Environment="OLLAMA_MAX_LOADED_MODELS=3"
Environment="OLLAMA_NUM_PARALLEL=1"
EOF

sudo systemctl daemon-reload
sudo systemctl restart ollama
```

| Setting | Effect |
|---|---|
| `OLLAMA_FLASH_ATTENTION=1` | Enables Flash Attention — reduces memory usage and speeds up long contexts. Required for KV cache quantization. |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | Quantizes KV cache to 8-bit integers, saving ~47% KV cache memory with negligible quality loss. |
| `OLLAMA_KEEP_ALIVE=-1` | Models stay loaded indefinitely; eviction only when memory pressure requires it (LRU policy). |
| `OLLAMA_NUM_PARALLEL=1` | Single inference stream; avoids pre-allocating resources for concurrent requests on a dedicated machine. |

---

## Verification

After all steps and a final reboot, verify the full configuration:

```bash
# Check GTT and VRAM allocation
dmesg | grep amdgpu | grep -iE "gtt|vram"

# Check TTM limit
cat /sys/module/ttm/parameters/pages_limit

# Check lockup timeout
cat /sys/module/amdgpu/parameters/lockup_timeout

# Check hugepages state
cat /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/defrag
```

The `ollama ps` command should report 100% GPU use when models are loaded — if they fit within GTT memory.

The `radeontop` utility can be used to see GPU resource usage in real-time.

---

## Expected Performance (Vega 7, 64GB DDR4-3200)

| Metric | Value |
|---|---|
| Memory bandwidth | ~51 GB/s (dual channel DDR4-3200) |
| GPU compute | ~1.8 TFLOPS FP16 (Rapid Packed Math) |
| Token generation (7B Q4) | ~8–12 tokens/s |
| Token generation (13B Q4) | ~4–6 tokens/s |
| Prefill (short prompt) | ~20 t/s (fixed overhead dominates) |
| Prefill (long prompt) | ~80–100 t/s (GPU better utilized) |

Token generation speed is primarily limited by the 51 GB/s memory bandwidth
ceiling — this is a fundamental hardware constraint that no software
configuration can overcome. Prefill speed benefits most from the GTT and THP
optimizations in this guide.

---

## Troubleshooting

**Still seeing `ring comp_1.2.0 timeout`:**
- Verify `lockup_timeout=50000` is active
- Try reducing GPU layers: set `num_gpu` lower in Ollama modelfile
- Check `dmesg` for memory allocation failures alongside the timeout

**Model output garbled after ring reset:**
- The GPU recovered but the inference server may be in an inconsistent state
- Restart Ollama: `sudo systemctl restart ollama`

**Ollama not offloading to GPU:**
- Run `OLLAMA_DEBUG=1 ollama serve` and check for `layers offloaded` in output
- Confirm Vulkan is working: `vulkaninfo --summary 2>/dev/null | grep -i "amd\|vega"`
- Ensure your user is in `render` and `video` groups: `sudo usermod -aG render,video $USER`
