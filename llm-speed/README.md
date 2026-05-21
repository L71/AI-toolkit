# llm-speed

A Python script to measure the token generation speed of Ollama, llama.cpp, or oMLX servers via their OpenAI-compatible APIs.

## Features

- Supports **Ollama**, **llama.cpp**, and **oMLX** via a unified OpenAI-compatible API
- **Streaming** mode with time-to-first-token (TTFT) measurement
- **Non-streaming** mode as a simpler fallback
- Configurable iterations, max tokens, and request timeout
- Automatic model discovery and validation
- **Automatic warmup round** before benchmarks (configurable, enabled by default)
- **Truncation detection** — warns when output hits `max_tokens` limit
- **JSON output** for scripting and CI pipelines
- **Prompt files** and stdin input for complex prompts
- Detailed performance metrics:
  - Generation tokens per second (excludes prompt processing in streaming mode)
  - Time per token
  - Time to first token (TTFT)
  - Input/output token counts (from API when available)

## Installation

No dependencies required beyond the standard library. Just ensure you have Python 3.7+ installed.

## Quick Start

Each backend connects to a default port unless you override it with `--port`:

| Backend | Default Port |
|---------|-------------|
| Ollama | 11434 |
| llama.cpp | 8080 |
| oMLX | 8000 |

**Step 1:** List available models on your server:

```bash
python llm-speed.py --backend ollama --host 192.168.1.100
```

**Step 2:** Run a benchmark (uses 5 built-in prompts, 3 iterations, 128 tokens):

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral
```

**Step 3:** Customize with your own prompt and more tokens:

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral \
  "Write a poem about the ocean." --max-tokens 256
```

**Step 4:** Get JSON output for scripting and CI pipelines:

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral --json
```

## Usage

### Customizing Prompts

Pass one or more prompts directly on the command line:

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral \
  "Explain machine learning." "What is AI?" --iterations 5
```

Read prompts from a file (one per line, empty lines skipped):

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral --prompt-file prompts.txt
```

Read from stdin:

```bash
cat prompts.txt | python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral --prompt-file -
```

If the file is missing or unreadable, the tool prints a clear error message instead of crashing.

### Listing Models in JSON

Combine `--json` without `--model` to get a machine-readable model list:

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --json
```

Outputs `{"server": {...}, "models": ["model1", "model2", ...]}`.

### Advanced Options

**Non-streaming mode** (no TTFT measurement, simpler fallback):

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral --no-stream
```

**Warmup round** (enabled by default to cold-start the model):

```bash
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral --no-warmup
python llm-speed.py --backend ollama --host 192.168.1.100 --model mistral --warmup-tokens 4
```

**Long-running benchmarks** (CPU-only servers with slow generation):

```bash
python llm-speed.py --backend llama-cpp --host 192.168.1.100 --model mistral \
  --timeout 600 --iterations 2 --max-tokens 512
```

**Full options:**

```bash
python llm-speed.py \
  --backend omlx \
  --host 192.168.1.100 \
  --model Qwen3-8B \
  --port 8000 \
  --iterations 5 \
  --max-tokens 256 \
  --stream \
  --timeout 300 \
  "Your prompt here"
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--backend` | `ollama` | LLM runtime backend: `ollama`, `llama-cpp`, or `omlx` |
| `--host` | `localhost` | Server hostname |
| `--port` | (auto) | Server port (auto-selected from backend type) |
| `--model` | (omit to list) | Model name (omit to list available models) |
| `--iterations` | `3` | Number of times to run each prompt |
| `--max-tokens` | `128` | Maximum tokens to generate per prompt |
| `--stream` | (default) | Use streaming API (enables TTFT measurement) |
| `--no-stream` | | Use non-streaming API (no TTFT) |
| `--timeout` | none | Request timeout in seconds per iteration |
| `--warmup` | (default) | Run a warmup round before benchmarks (enabled by default) |
| `--no-warmup` | | Skip the warmup round |
| `--warmup-tokens` | `1` | Maximum tokens for the warmup round |
| `--json` | | Output results as JSON (suppresses verbose output) |
| `--prompt-file` | | Read prompts from file (one per line). Use `-` for stdin. |
| `prompts` | (built-in set) | Prompt strings to test |

## Backend Configuration

### Ollama

```bash
ollama serve
```

Default: `http://localhost:11434`

### llama.cpp

```bash
./llama-server -m model.gguf -c 4096 --port 8080
```

Default: `http://localhost:8080`

### oMLX

```bash
omlx serve --model-dir ~/models
```

Default: `http://localhost:8000`

## Example Output

```
============================================================
Token Generation Speed Measurement
============================================================
Server: Ollama at http://192.168.1.100:11434
Model: mistral
Mode: streaming
Prompts: 5
Iterations: 3
Max tokens per generation: 128
============================================================

--- Prompt 1/5 ---
Input length: 32 chars
  Iteration 1/3... ✓ 42 tok | 161.5 t/s | TTFT: 50ms | Total: 310ms
  Iteration 2/3... ✓ 42 tok | 165.2 t/s | TTFT: 45ms | Total: 300ms
  Iteration 3/3... ✓ 42 tok | 158.8 t/s | TTFT: 55ms | Total: 320ms

...

============================================================
Summary
============================================================

Average generation t/s (excludes prompt processing): 161.83
Average time per token: 6.18 ms
Average time to first token (TTFT): 50ms
Total measurements: 5

  (Token counts are API-reported — exact for this model/server.)

  Prompt 1:
    Input: 32 chars (8 tokens)
    Output: 126 tokens
    Speed: 161.50 t/s
    Time/token: 6.20 ms/token
    TTFT: 50ms
```

## Error Handling

- **Server unreachable**: Clear error with server name, URL, and connection reason
- **Model not found**: Error with list of available models on the server
- **No models loaded**: Informative message about the empty model list
- **Truncated output**: Warning when generation hits `max_tokens` limit
- **Missing prompt file**: Clear error if `--prompt-file` points to a nonexistent or unreadable file

## Notes

- Token counts come from the API's `usage` field for accuracy
- oMLX may not always return usage in streaming mode; a heuristic fallback is used
- The tool automatically falls back if a server doesn't support `stream_options`
- Models with reasoning/thinking content are supported — `content`, `reasoning`, and `reasoning_content` delta fields are all captured for accurate TTFT and output measurement
- For CPU-only servers, use `--timeout` to avoid request timeouts during slow generation
- A warmup round runs automatically before benchmarks; disable with `--no-warmup`
- Results may vary based on system resources and model complexity

### Streaming vs Non-Streaming Throughput

In **streaming mode**, the reported tokens/second measures **pure generation throughput**
(excluding prompt processing time). The TTFT metric captures prompt processing separately.

In **non-streaming mode**, the reported tokens/second is **overall throughput** (includes
both prompt processing and generation), since the two cannot be separated without streaming.

When comparing configurations, use the same mode for fairness. Streaming mode provides
more granular insight into where time is spent.

### Token Count Heuristic

When the API does not return token usage (e.g. some llama.cpp server builds),
the script falls back to a rough character-count heuristic: it splits text
by whitespace and estimates ~1 token per 5 characters of each word. This
is **not accurate** for:

- Numbers, URLs, or long identifiers (overestimated)
- Code with symbols and punctuation (overestimated)
- Non-English text with dense scripts like CJK (underestimated)

Expect errors of 30-50% or more. Always prefer servers/APIs that report
token counts directly.

## Interpreting Results

Token counts and throughput numbers are **approximate** when the API does not
return usage information (the fallback heuristic is off by ~30-50% for
non-English text). Even when the API provides usage, different backends may
report token counts differently.

Use this tool to **compare configuration changes** (e.g. different `--max-tokens`,
`--iterations`, or server settings) rather than to report absolute performance
numbers. The relative ranking between configurations is what matters.

## License

MIT License
