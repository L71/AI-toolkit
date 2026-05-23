# Ollama Threads Test

Benchmark Ollama's performance across different `num_thread` settings.

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
| `--threads` | No | `2 4 5 6 7 8` | Thread counts (supports ranges, e.g. `2 4 10-16`) |
| `--iterations` | No | `5` | Number of tests per thread count |
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

List models on a custom port:

```bash
python ollama_threads_test.py --host llm-t01 --port 8080
```
