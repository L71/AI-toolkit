# Ollama Threads Test

Benchmark Ollama's performance across different `num_thread` settings.

## How measurements work

This tool uses Ollama's native `/api/generate` endpoint, which returns Ollama-specific fields not available over the OpenAI-compatible API. The key values are `prompt_eval_count` (number of prompt tokens), `prompt_eval_duration` (server-side nanoseconds the model spent on the prompt), `eval_count` (number of generated tokens), and `eval_duration` (server-side nanoseconds spent generating). Prompt and evaluation rates are computed by dividing the token counts by their respective durations. Because these durations are recorded by Ollama's internal timers, they are pure server-side measurements and do not include network latency or client-side overhead.

## Comparison with `llm-speed`

The `llm-speed` script in the sibling `llm-speed` directory uses the OpenAI-compatible `/v1/chat/completions` endpoint instead of the native Ollama API. As a result, it cannot access Ollama's `prompt_eval_duration` and `eval_duration` fields directly. When benchmarking Ollama, `llm-speed` instead reports prompt processing speed using either the `prompt_time_ms` field from the usage object or (when unavailable) a TTFT-based estimation. Because the two tools use different endpoints and measure timing in different ways, their reported numbers will not match exactly. Use `ollama-threads-test` when you need fine-grained tuning of Ollama's thread count, and `llm-speed` when you want to compare performance across backends (Ollama, llama.cpp, oMLX).

## Usage

List available models (no `--model` required):

```bash
python ollama_threads_test.py --host llm-t01
```

Run benchmarks:

```bash
python ollama_threads_test.py --host llm-t01 --model qwen3.6:35b
```

## Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--host` | Yes | — | Ollama host (e.g. `llm-t01`) |
| `--model` | No | — | Model name; omit to list models |
| `--port` | No | `11434` | Ollama port |
| `--threads` | No | server default | Thread counts (supports ranges, e.g. `2 4 10-16`). Omit to use the server default (a warning is printed). |
| `--iterations` | No | `3` | Number of tests per thread count |
| `--prompt` | No | `"what is 2 ** 2 ?"` | Prompt to use |

## Examples

Test specific thread counts:

```bash
python ollama_threads_test.py --host llm-t01 --model qwen3:4b --threads 2 4 6 8
```

Test a range of thread counts:

```bash
python ollama_threads_test.py --host llm-t01 --model qwen3:4b --threads 2 4 10-16 --iterations 3
```

Use the server's default thread count:

```bash
python ollama_threads_test.py --host llm-t01 --model qwen3:4b --iterations 5
```

List models on a custom port:

```bash
python ollama_threads_test.py --host llm-t01 --port 8080
```
