# Configuring AMD 4650GE APU GPU Memory for LLM Inference

## Background

The AMD Ryzen 5 PRO 4650GE contains an integrated Vega 7 GPU (GCN5/gfx90c
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

This hardware is not particularly well suited to running LLMs and performance will be very slow unless limited to very small LLMs or using mixture-of-experts (MoE) models.

Applying the configuration in this document and running a recent Ollama version with Vulkan GPU acceleration achieves prefill speeds of ~110 tokens/s on long prompts and ~14 tokens/s on generation for Qwen3.6-35B-A3B (a 35B-parameter MoE model with 3B active parameters) with a context length of 256K. Gemma4-26B-A4B (26B total, 4B active parameters) also gives similar numbers.

The "unified memory" popularized by Apple and others is effectively present on this AMD hardware too — the iGPU can address almost the entire system RAM when GTT is raised accordingly. As mentioned above, the default settings limit this to 50% of RAM; this guide describes how to increase it significantly. Up to 60 GiB GTT memory (on a 64GB system) seems to work fine. Note that allocating too much GTT can starve the OS and CPU, potentially causing system instability.

If testing similar hardware with less memory, make sure both memory channels are populated with DIMMs since token generation is almost completely dependent on memory bandwidth.

**Addendum about newer hardware**

The same setup procedures have also been performed on a ThinkCentre M75q G5, 8700GE APU, 64GB, also running Ubuntu 26.04 with the same results. Vulkan acceleration works fine. ROCm acceleration _should_ also work on this hardware but appears complicated to setup and it has not been tested.

Some performance numbers from this machine, using qwen3.6-35b, MTP enabled, Ollama KV cache quantization q8_0, context 256k.

|Processor|Prompt|Prefill t/s|Generation t/s|
|---|---|---|---|
|CPU|"Hi there!"|~65|~27|
|CPU|27k chars/6926 tokens|~57|~16.5|
|GPU/Vulkan|"Hi there!"|~21|~27|
|GPU/Vulkan|2.6k chars/740 tokens|~232|~24|
|GPU/Vulkan|27k chars/6926 tokens|~266|~22|


---

## Recommended firmware settings

Set the VRAM carveout (may be labelled "UMA Frame Buffer Size", "IGPU Memory",
or similar) in the PC's UEFI setup or BIOS to the minimum your system allows. A large video RAM carveout reduces available GTT and provides no benefit for compute workloads.

---

## Step 1: Increase GTT Size and GPU compute timeout

GTT is the address space; TTM (Translation Table Manager) is the kernel's
actual page allocation budget.

The TTM limit is expressed in **4KB pages**. Examples:

```
48 GB:  48 × 1024 × 1024 / 4 = 12582912 pages
60 GB:  60 × 1024 × 1024 / 4 = 15728640 pages
```

With larger memory mappings, GPU compute jobs (particularly LLM prefill passes)
may take longer than the default 10-second timeout, causing spurious ring resets
and inference crashes. We fix this with another line in the same config file.

Create a modprobe configuration file `/etc/modprobe.d/amdgpu.conf` with this content:

```bash
# increase GPU memory allocation limits and pool size (number of 4K memory pages)
options ttm pages_limit=15728640 page_pool_size=15728640

# increase GPU compute ring timeout (milliseconds, default 10000)
options amdgpu lockup_timeout=50000
```

Both `pages_limit` (hard allocation ceiling) and `page_pool_size`
(pre-allocated pool) should be set to the same value so the pool can grow
to the full ceiling without an intermediate cap.

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

NOTE: consider this step optional if you run Ollama with 100% GPU acceleration.

With a very large memory pool, the processor must manage millions of 4KB page table
entries during inference. Transparent Hugepages (THP) consolidates these into
2MB pages, reducing the page table entry count by 512× and significantly lowering
TLB pressure, improving sustained memory throughput — particularly during prefill.

### Immediate (no reboot required)

```bash
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/shmem_enabled
echo defer+madvise | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
```

We use `defer+madvise` for defrag to avoid latency spikes from synchronous
page compaction while still forming hugepages opportunistically.

### Persistent (survives reboot)

Create the file `/etc/tmpfiles.d/thp.conf` with this content:
```bash
w /sys/kernel/mm/transparent_hugepage/enabled - - - - always
w /sys/kernel/mm/transparent_hugepage/shmem_enabled - - - - always
w /sys/kernel/mm/transparent_hugepage/defrag - - - - defer+madvise
```

---

## Step 3: Install Vulkan dependencies

On Ubuntu 26.04 server install the `vulkan-tools` package. This will pull in all necessary dependencies.


---

## Step 4: Install and configure Ollama

Install Ollama according to https://ollama.com/download

Make sure to use a recent version, 0.30 or later.

Also follow the Vulkan setup instructions here:
https://docs.ollama.com/gpu#vulkan-gpu-support

If you use the Ollama install script it may also download a package with ROCm libraries for the alternative GPU acceleration system on AMD. ROCm unfortunately does not support the 4650GE APU.

Create a systemd override to adjust relevant Ollama settings:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
Environment="OLLAMA_CONTEXT_LENGTH=262144"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_FLASH_ATTENTION=1"
# Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_IGPU_ENABLE=1"
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_MAX_LOADED_MODELS=3"
Environment="OLLAMA_NUM_PARALLEL=1"
EOF

sudo systemctl daemon-reload
sudo systemctl restart ollama
```

| Setting | Effect |
|---|---|
| `OLLAMA_HOST=0.0.0.0` | Binds the Ollama server to all network interfaces, enabling access from other machines on the local network. |
| `OLLAMA_CONTEXT_LENGTH=262144` | Sets the maximum context length to 256K tokens. Adjust based on model support, memory availability and your use case. |
| `OLLAMA_KEEP_ALIVE=-1` | Models remain loaded indefinitely in memory; eviction occurs only under memory pressure via LRU policy. |
| `OLLAMA_FLASH_ATTENTION=1` | Enables Flash Attention, reducing memory usage and accelerating long context processing. Required for KV cache quantization. |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | Quantizes the KV cache to 8-bit integers, saving ~50% KV cache memory with negligible quality loss. This may result in a significant performance drop depending on use case and context size.|
| `OLLAMA_IGPU_ENABLE=1` | Enables the use of integrated GPUs for inference, which is disabled by default in Ollama. |
| `OLLAMA_VULKAN=1` | Forces Vulkan as the compute backend, enabling GPU acceleration on AMD iGPUs. |
| `OLLAMA_MAX_LOADED_MODELS=3` | Allows up to 3 models to be loaded in memory simultaneously, enabling model switching without reloading. |
| `OLLAMA_NUM_PARALLEL=1` | Uses a single inference stream; avoids pre-allocating resources for concurrent requests on a dedicated machine. |

---

## Verification

After all steps and a final reboot, verify the full configuration:

```bash
# Check GTT and VRAM allocation
sudo dmesg | grep amdgpu | grep -iE "gtt|vram"

# Check TTM limit
cat /sys/module/ttm/parameters/pages_limit

# Check lockup timeout
cat /sys/module/amdgpu/parameters/lockup_timeout

# Check hugepages state
cat /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/defrag
```

The `ollama ps` command should report 100% GPU use when models are loaded — if they fit within available GTT memory.

The `radeontop` utility can be used to see GPU resource usage in real-time.

---

## Expected Performance (Vega 7, 64GB DDR4-3200)

| Metric | Value |
|---|---|
| Memory bandwidth | ~51 GB/s (dual channel DDR4-3200) |
| GPU compute | ~1.8 TFLOPS FP16 (Rapid Packed Math) |
| Token generation (7B Q4) | ~8–12 tokens/s |
| Token generation (13B Q4) | ~4–6 tokens/s |
| Prefill (short prompt) | ~20 tokens/s (fixed overhead dominates) |
| Prefill (long prompt) | ~80–110 tokens/s (GPU better utilized) |

Token generation speed is primarily limited by the 51 GB/s memory bandwidth
ceiling — this is a fundamental hardware constraint that no software
configuration can overcome. Prefill speed benefits most from the GTT and THP
optimizations in this guide.

---

**Some results from `ollama_threads_test.py`**

Model `qwen3.6-35B-A3B`, with different context sizes and KV quantization

For comparison a few CPU-only measurements are included; all others are Vulkan GPU accelerated.

| Context | Prompt size | Memory use | Prefill t/s | Generation t/s |
|---|---|---|---|---|
| 64K fp16 | 27k chars / 6926 tokens | 24G | 110 | 13.5 |
| 64K fp16 | 2.6k chars / 740 tokens | 24G | 99 | 14.2 |
| 256K fp16 | 27k chars / 6926 tokens | 29G | 113 | 13.5 |
| 256K fp16 | 2.6k chars / 740 tokens | 29G | 102 | 14.3 |
| 64K q8_0 | 27k chars / 6926 tokens | 24G | 101 | 13.1 |
| 64K q8_0 | 2.6k chars / 740 tokens | 24G | 99 | 14 |
| 256K q8_0 | 27k chars / 6926 tokens | 27G | 106 | 13.3 |
| 256K q8_0 | 2.6k chars / 740 tokens | 27G | 101 | 14.2 |
| 256K fp16 100% CPU | 27k chars / 6926 tokens | 30G | 45 | 7.4 |
| 256K fp16 100% CPU | 2.6k chars / 740 tokens | 30G | 52 | 13.3 |

---

**MTP (Multiple Token Prediction)**

Recent Ollama versions can utilize multiple-token prediction when generating tokens. The actual effect varies but generation speed using the example model below can increase by up to 20% when correctly configured at a slight cost to prefill speed. This requires the use of a model with MTP info embedded in it, like `qwen3.6:35b-a3b-mtp-q4_K_M` available from the Ollama registry.

The default setting of the enabling parameter, `draft_num_predict=4`, actually makes it slower on this hardware. A setting of 1 seems to give the best effect.

Create the following Ollama Modelfile:

    FROM qwen3.6:35b-a3b-mtp-q4_K_M

    # Enable MTP
    PARAMETER draft_num_predict 1

    # Tuning for coding (remove if not applicable)
    PARAMETER temperature 0.5
    PARAMETER top_p 0.95
    PARAMETER top_k 20
    PARAMETER repeat_penalty 1
    PARAMETER presence_penalty 0

Run the `ollama create qwen3.6:35b-mtp-code -f Modelfile` command to create a model with the updated parameters.


---

**System power usage**

The test computer power usage while idle is about 5-6W. Max power use observed while running LLMs GPU-accelerated seems to be about 45W. Max use when running CPU-only was 55W (also with noticeably more fan noise than when running GPU-accelerated). These measurements may not be precise.


---

## Troubleshooting

**See Ollama server logs**
- Run `journalctl -u ollama.service`, add `-f` to see live updates.

**Still seeing `ring comp_1.2.0 timeout`:**
- Verify `lockup_timeout=50000` is active
- Try reducing GPU layers: set `num_gpu` lower in Ollama modelfile
- Check `dmesg` for memory allocation failures alongside the timeout

**Model output garbled after ring reset:**
- The GPU recovered but the inference server may be in an inconsistent state
- Restart Ollama: `sudo systemctl restart ollama`

**Ollama not offloading to GPU:**
- Enable debug logging by adding `Environment="OLLAMA_DEBUG=1"` to the systemd override from Step 4, then `sudo systemctl restart ollama` and check `journalctl -u ollama -f` for `layers offloaded`
- Confirm Vulkan is working: `vulkaninfo --summary 2>/dev/null | grep -i "amd\|vega"`
- Ensure your user is in `render` and `video` groups: `sudo usermod -aG render,video $USER`
