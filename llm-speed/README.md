# llm-speed

A Python script to measure the token generation speed of Ollama, llama.cpp, or oMLX servers via their OpenAI-compatible APIs.

## Features

- Supports **Ollama**, **llama.cpp**, and **oMLX** via a unified OpenAI-compatible API
- **Streaming** mode with time-to-first-token (TTFT) measurement
- **Non-streaming** mode as a simpler fallback
- Configurable iterations, max tokens, and request timeout
- Automatic model discovery and validation
- Detailed performance metrics:
  - Tokens per second
  - Time per token
  - Time to first token (TTFT)
  - Input/output token counts (from API, not heuristics)

## Installation

No dependencies required beyond the standard library. Just ensure you have Python 3.x installed.

## Usage

### Show Help

Running with no arguments prints the help text:

```bash
python llm-speed.py
```

### List Available Models

Specify a server without `--model` to see loaded models:

```bash
python llm-speed.py --server ollama
python llm-speed.py --server omlx
python llm-speed.py --server llama-cpp
```

### Run a Benchmark

Specify `--model` to run the benchmark (model is verified before starting):

```bash
python llm-speed.py --server omlx --model Qwen3-8B
python llm-speed.py --server ollama --model llama2
python llm-speed.py --server llama-cpp --model mistral
```

### Custom Prompts

```bash
python llm-speed.py --server omlx --model Qwen3-8B "Write a poem about nature." --max-tokens 256
python llm-speed.py --server ollama --model llama2 "Explain machine learning." "What is AI?" --iterations 5
```

### Non-Streaming Mode

```bash
python llm-speed.py --server omlx --model Qwen3-8B --no-stream
```

### Long-Running Benchmarks (CPU Servers)

For CPU-only servers with slow generation, set a generous timeout:

```bash
python llm-speed.py --server llama-cpp --model llama2 --timeout 600 --iterations 2 --max-tokens 512
```

### Full Options

```bash
python llm-speed.py \
  --server omlx \
  --model Qwen3-8B \
  --host 127.0.0.1 \
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
| `--server` | `ollama` | Server type: `ollama`, `llama-cpp`, or `omlx` |
| `--host` | `localhost` | Server hostname |
| `--port` | (auto) | Server port (auto-selected from server type) |
| `--model` | (required) | Model name (omit to list available models) |
| `--iterations` | `3` | Number of times to run each prompt |
| `--max-tokens` | `128` | Maximum tokens to generate per prompt |
| `--stream` | (default) | Use streaming API (enables TTFT measurement) |
| `--no-stream` | | Use non-streaming API (no TTFT) |
| `--timeout` | none | Request timeout in seconds per iteration |
| `prompts` | (optional) | Prompt strings to test |

Default ports by server type:

| Server | Port |
|--------|------|
| Ollama | 11434 |
| llama.cpp | 8080 |
| oMLX | 8000 |

## Server Configuration

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
Server: Ollama at http://localhost:11434
Model: mistral
Mode: streaming
Prompts: 5
Iterations: 3
Max tokens per generation: 128
============================================================

--- Prompt 1/5 ---
Input length: 32 chars
  Iteration 1/3 ✓ 42 tokens in 0.31s (135.5 t/s) | TTFT: 0.05s
  Iteration 2/3 ✓ 42 tokens in 0.29s (144.8 t/s) | TTFT: 0.04s
  Iteration 3/3 ✓ 42 tokens in 0.32s (131.3 t/s) | TTFT: 0.06s

...

============================================================
Summary
============================================================

Average tokens per second: 137.20
Average time per token: 7.29 ms
Average time to first token (TTFT): 0.05s
Total measurements: 5

  (Token counts are API-reported — exact for this model/server.)

  Prompt 1:
    Input: 32 chars (8 tokens)
    Output: 126 tokens
    Speed: 136.80 t/s
    Time/token: 7.31 ms/token
    TTFT: 0.05s
```

## Error Handling

- **Server unreachable**: Clear error with server name, URL, and connection reason
- **Model not found**: Error with list of available models on the server
- **No models loaded**: Informative message about the empty model list

## Notes

- Token counts come from the API's `usage` field for accuracy
- oMLX may not always return usage in streaming mode; a heuristic fallback is used
- For CPU-only servers, use `--timeout` to avoid request timeouts during slow generation
- Results may vary based on system resources and model complexity

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