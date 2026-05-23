#!/usr/bin/env python3
"""
Token generation speed measurement script for Ollama, llama.cpp, or oMLX servers.
Uses the OpenAI-compatible API shared by all three backends.
"""

import sys
import time
import json
import argparse
import urllib.request
import urllib.error
from typing import Optional


SERVER_PORTS = {
    "ollama": 11434,
    "llama-cpp": 8080,
    "omlx": 8000,
}

SERVER_LABELS = {
    "ollama": "Ollama",
    "llama-cpp": "llama.cpp",
    "omlx": "oMLX",
}

DEFAULT_PROMPTS = [
    "Write a short poem about the ocean.",
    "Explain quantum computing in simple terms.",
    "What is the meaning of life?",
    "Write a Python function to sort a list.",
    "Describe the beauty of nature in three sentences.",
]


class OpenAIClient:
    """Client for any server exposing an OpenAI-compatible /v1/chat/completions API."""

    def __init__(self, server_type: str, host: str = "localhost", port: Optional[int] = None, model: Optional[str] = None):
        self.server_type = server_type
        self.host = host
        self.port = port or SERVER_PORTS.get(server_type, 8000)
        self.base_url = f"http://{host}:{self.port}"
        self.label = SERVER_LABELS.get(server_type, server_type)
        self.model = model
        self._supports_stream_options = None

    def _make_request(self, url: str, payload: dict) -> urllib.request.Request:
        data = json.dumps(payload).encode("utf-8")
        return urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )

    def generate(self, prompt: str, max_tokens: int = 128, timeout: Optional[float] = None) -> dict:
        """Non-streaming chat completion. Returns the full response dict."""
        url = f"{self.base_url}/v1/chat/completions"
        req = self._make_request(url, {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        })
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _parse_sse_stream(self, response, prompt: str, start_time: float) -> dict:
        """Parse an SSE stream response into structured results."""
        first_token_time = None
        output_parts = []
        completion_tokens = 0
        prompt_tokens = 0
        usage_received = False
        finish_reason = None
        done = False

        buffer = ""
        while not done:
            raw_chunk = response.readline()
            if not raw_chunk:
                break
            buffer += raw_chunk.decode("utf-8")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                for raw_line in block.split("\n"):
                    line = raw_line.rstrip("\r")
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].lstrip()
                    if data_str.strip() == "[DONE]":
                        done = True
                        break
                    try:
                        sse_chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    for choice in sse_chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        content = (delta.get("content") or "") + (delta.get("reasoning") or "") + (delta.get("reasoning_content") or "")
                        if content:
                            output_parts.append(content)
                            if first_token_time is None:
                                first_token_time = time.time()
                        fr = choice.get("finish_reason")
                        if fr and not finish_reason:
                            finish_reason = fr
                    usage = sse_chunk.get("usage")
                    if usage:
                        usage_received = True
                        completion_tokens = usage.get("completion_tokens", 0)
                        prompt_tokens = usage.get("prompt_tokens", 0)

        elapsed = time.time() - start_time
        ttft = (first_token_time - start_time) if first_token_time is not None else None
        output_text = "".join(output_parts)

        if not usage_received:
            if completion_tokens == 0:
                completion_tokens = count_generated_tokens(output_text)
            if prompt_tokens == 0:
                prompt_tokens = max(1, len(prompt) // 4)

        gen_elapsed = (elapsed - ttft) if ttft is not None else elapsed
        gen_elapsed = max(gen_elapsed, 0.001)

        return {
            "output": output_text,
            "completion_tokens": completion_tokens,
            "prompt_tokens": prompt_tokens,
            "elapsed": elapsed,
            "ttft": ttft,
            "generation_elapsed": gen_elapsed,
            "tokens_from_api": usage_received,
            "finish_reason": finish_reason,
        }

    def stream_generate(self, prompt: str, max_tokens: int = 128, timeout: Optional[float] = None) -> dict:
        """Streaming chat completion with TTFT and per-token timing.

        Returns dict with output, token counts, TTFT, generation_elapsed, and finish_reason.
        Automatically falls back if the server does not support stream_options.
        """
        use_stream_options = self._supports_stream_options if self._supports_stream_options is not None else True

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
        }
        if use_stream_options:
            payload["stream_options"] = {"include_usage": True}

        req = self._make_request(f"{self.base_url}/v1/chat/completions", payload)
        start_time = time.time()

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if use_stream_options:
                    self._supports_stream_options = True
                return self._parse_sse_stream(response, prompt, start_time)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if (e.code in (400, 422) and use_stream_options
                    and self._supports_stream_options is not False
                    and any(kw in body for kw in ("stream_options", "include_usage", "unknown"))):
                self._supports_stream_options = False
                return self.stream_generate(prompt, max_tokens, timeout)
            raise

    def list_models(self, timeout: Optional[float] = None) -> list:
        """Fetch available models from /v1/models endpoint. Returns list of model IDs."""
        url = f"{self.base_url}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            return [m["id"] for m in result.get("data", [])]


def print_http_error(e, context: str) -> None:
    """Print a detailed error message for an HTTP error response."""
    try:
        body = e.read().decode("utf-8")
    except Exception:
        body = None

    print(f"\u2717 HTTP {e.code}: {e.reason} ({context})")
    if body:
        try:
            data = json.loads(body)
            msg = data.get("message") or data.get("error", {}).get("message") or str(data)
        except json.JSONDecodeError:
            msg = body
        if len(msg) > 200:
            msg = msg[:200] + "..."
        print(f"  {msg}")


def count_generated_tokens(text: str) -> int:
    """Estimate token count for text when the API doesn't provide usage stats.

    Rough heuristic (off by ~30-50% for non-English text or complex punctuation).
    The API's own usage field is preferred whenever available.
    """
    tokens = 1
    for word in text.split():
        tokens += len(word) // 5 + 1
    return max(1, tokens)


def format_duration(seconds) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds is None:
        return "N/A"
    if seconds < 0.01:
        return "<10ms"
    elif seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = seconds / 60
        return f"{minutes:.2f}m ({seconds:.1f}s)"


def measure_generation_speed(
    client,
    prompts: list,
    iterations: int = 3,
    max_tokens: int = 128,
    use_streaming: bool = True,
    timeout: Optional[float] = None,
    verbose: bool = True,
) -> list:
    """Measure generation speed for multiple prompts."""
    results = []
    mode_label = "streaming" if use_streaming else "non-streaming"

    if verbose:
        print("\n" + "=" * 60)
        print("Token Generation Speed Measurement")
        print("=" * 60)
        print(f"Server: {client.label} at {client.base_url}")
        print(f"Model: {client.model}")
        print(f"Mode: {mode_label}")
        print(f"Prompts: {len(prompts)}")
        print(f"Iterations: {iterations}")
        print(f"Max tokens per generation: {max_tokens}")
        print("=" * 60 + "\n")

    for i, prompt in enumerate(prompts, 1):
        if verbose:
            print(f"\n--- Prompt {i}/{len(prompts)} ---")
            print(f"Input length: {len(prompt)} chars")

        total_input_tokens = 0
        total_output_tokens = 0
        total_elapsed = 0.0
        total_gen_elapsed = 0.0
        total_ttft = 0.0
        successful = 0
        tokens_from_api = False
        has_ttft = False
        poor_streaming = False
        truncated = False

        for iter_num in range(iterations):
            if verbose:
                print(f"  Iteration {iter_num + 1}/{iterations}...", end=" ", flush=True)
            start_time = time.time()

            try:
                if use_streaming:
                    result = client.stream_generate(prompt, max_tokens=max_tokens, timeout=timeout)
                    output_tokens = result["completion_tokens"]
                    input_tokens = result["prompt_tokens"]
                    elapsed = result["elapsed"]
                    ttft = result["ttft"]
                    gen_elapsed = result["generation_elapsed"]
                    tokens_from_api = tokens_from_api or result.get("tokens_from_api", False)
                    if ttft is not None:
                        has_ttft = True
                else:
                    result = client.generate(prompt, max_tokens=max_tokens, timeout=timeout)
                    elapsed = time.time() - start_time
                    tokens_from_api = tokens_from_api or bool(result.get("usage"))
                    usage = result.get("usage", {})
                    output_tokens = usage.get("completion_tokens", 0)
                    input_tokens = usage.get("prompt_tokens", 0)
                    ttft = None
                    gen_elapsed = elapsed
                    if output_tokens == 0:
                        output_tokens = count_generated_tokens(
                            result.get("choices", [{}])[0].get("message", {}).get("content", "")
                        )
                    if input_tokens == 0:
                        input_tokens = max(1, len(prompt) // 4)

                finish_reason = result.get("finish_reason")
                if not finish_reason and not use_streaming:
                    finish_reason = result.get("choices", [{}])[0].get("finish_reason")
                if finish_reason == "length":
                    truncated = True

                # Detect poor streaming: if gen_elapsed is <10% of total, the server
                # likely buffered all tokens and sent them in a single burst.
                iter_poor_streaming = (use_streaming and has_ttft and elapsed > 0
                                       and gen_elapsed / elapsed < 0.1)
                poor_streaming = poor_streaming or iter_poor_streaming
                tps_denom = gen_elapsed if (use_streaming and has_ttft and not iter_poor_streaming) else elapsed
                tps = output_tokens / tps_denom if tps_denom > 0 else 0

                if verbose:
                    ttft_str = format_duration(ttft) if ttft is not None else "N/A"
                    trunc_mark = " ⚠ truncated" if finish_reason == "length" else ""
                    stream_mark = " (buffered)" if iter_poor_streaming else ""
                    if use_streaming:
                        print(f"✓ {output_tokens} tok | {tps:.1f} t/s | TTFT: {ttft_str} | Total: {format_duration(elapsed)}{trunc_mark}{stream_mark}")
                    else:
                        print(f"✓ {output_tokens} tok | {tps:.1f} t/s | Total: {format_duration(elapsed)}{trunc_mark}")

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_elapsed += elapsed
                total_gen_elapsed += gen_elapsed
                if ttft is not None:
                    total_ttft += ttft
                successful += 1

            except urllib.error.HTTPError as e:
                if verbose:
                    print_http_error(e, f"{client.label} generation")
            except Exception as e:
                if verbose:
                    print(f"\u2717 Error: {e}")

        if successful > 0:
            tps_denom = total_gen_elapsed if (use_streaming and has_ttft and not poor_streaming) else total_elapsed
            avg_tps = total_output_tokens / tps_denom if tps_denom > 0 else 0
            avg_ttft = total_ttft / successful if has_ttft else None

            results.append({
                "prompt_id": i,
                "prompt": prompt,
                "input_length": len(prompt),
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_elapsed": round(total_elapsed, 4),
                "total_generation_elapsed": round(total_gen_elapsed, 4),
                "avg_tokens_per_second": round(avg_tps, 2),
                "avg_time_per_token": round(1 / avg_tps, 4) if avg_tps > 0 else None,
                "avg_ttft": round(avg_ttft, 4) if avg_ttft is not None else None,
                "successful_iterations": successful,
                "tokens_from_api": tokens_from_api,
                "truncated": truncated,
                "poor_streaming": poor_streaming,
            })

    return results


def print_summary(results: list, use_streaming: bool):
    """Print a human-readable summary of the measurement results."""
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    if not results:
        print("\nNo successful measurements.")
        print("=" * 60 + "\n")
        return

    all_api = all(r.get("tokens_from_api", False) for r in results)
    some_api = any(r.get("tokens_from_api", False) for r in results)

    avg_tps = sum(r["avg_tokens_per_second"] for r in results) / len(results)
    avg_tpt = 1 / avg_tps if avg_tps > 0 else None

    ttft_values = [r["avg_ttft"] for r in results if r["avg_ttft"] is not None]
    avg_ttft = sum(ttft_values) / len(ttft_values) if ttft_values else None

    any_poor_streaming = any(r.get("poor_streaming", False) for r in results)

    if use_streaming:
        if any_poor_streaming:
            tps_label = "overall t/s (server buffered output; includes prompt processing)"
        else:
            tps_label = "generation t/s (excludes prompt processing)"
    else:
        tps_label = "overall t/s (includes prompt processing)"

    print(f"\nAverage {tps_label}: {avg_tps:.2f}")
    if avg_tpt is not None:
        print(f"Average time per token: {avg_tpt * 1000:.2f} ms")
    if avg_ttft is not None:
        print(f"Average time to first token (TTFT): {format_duration(avg_ttft)}")
    print(f"Total measurements: {len(results)}")

    if all_api:
        print("\n  (Token counts are API-reported \u2014 exact for this model/server.)")
    elif some_api:
        print("\n  (Some token counts are API-reported, others are estimates.)")
    else:
        print("\n  (Token counts are heuristic estimates \u2014 not exact.)")

    for r in results:
        print(f"\n  Prompt {r['prompt_id']}:")
        print(f"    Input: {r['input_length']} chars ({r['input_tokens']} tokens)")
        print(f"    Output: {r['output_tokens']} tokens")
        print(f"    Speed: {r['avg_tokens_per_second']:.2f} t/s")
        if r["avg_time_per_token"] is not None:
            print(f"    Time/token: {r['avg_time_per_token'] * 1000:.2f} ms/token")
        if r["avg_ttft"] is not None:
            print(f"    TTFT: {format_duration(r['avg_ttft'])}")
        if r.get("poor_streaming"):
            print(f"    \u26a0 Server buffered output (TTFT includes generation time)")
        if r["truncated"]:
            print(f"    \u26a0 Output was truncated (hit max_tokens limit)")

    print("=" * 60 + "\n")


def print_json_results(client, results: list, use_streaming: bool, max_tokens: int, iterations: int):
    """Print results as a structured JSON object."""
    avg_tps = (sum(r["avg_tokens_per_second"] for r in results) / len(results)) if results else None
    avg_tpt = round(1 / avg_tps, 4) if avg_tps and avg_tps > 0 else None

    ttft_values = [r["avg_ttft"] for r in results if r["avg_ttft"] is not None]
    avg_ttft = round(sum(ttft_values) / len(ttft_values), 4) if ttft_values else None

    output = {
        "server": {
            "type": client.server_type,
            "label": client.label,
            "url": client.base_url,
        },
        "model": client.model,
        "mode": "streaming" if use_streaming else "non-streaming",
        "iterations": iterations,
        "max_tokens": max_tokens,
        "results": results,
        "summary": {
            "avg_tokens_per_second": round(avg_tps, 2) if avg_tps else None,
            "avg_time_per_token": avg_tpt,
            "avg_ttft": avg_ttft,
            "tokens_from_api": all(r.get("tokens_from_api", False) for r in results) if results else None,
            "total_measurements": len(results),
        },
    }
    print(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Measure token generation speed for Ollama, llama.cpp, or oMLX servers"
    )

    parser.add_argument(
        "--backend",
        choices=["ollama", "llama-cpp", "omlx"],
        default="ollama",
        help="LLM runtime backend (default: ollama)",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port (overrides server type default)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name to use (omit to list available models)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of iterations per prompt (default: 3)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=128,
        help="Maximum tokens to generate per prompt (default: 128)",
    )
    parser.add_argument(
        "--stream",
        dest="stream",
        action="store_true",
        default=True,
        help="Use streaming API (default, enables TTFT measurement)",
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Use non-streaming API (no TTFT measurement)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Request timeout in seconds per iteration (default: no timeout)",
    )
    parser.add_argument(
        "--warmup",
        dest="warmup",
        action="store_true",
        default=True,
        help="Run a quick warmup round before benchmarks (default: enabled)",
    )
    parser.add_argument(
        "--no-warmup",
        dest="warmup",
        action="store_false",
        help="Skip the warmup round",
    )
    parser.add_argument(
        "--warmup-tokens",
        type=int,
        default=1,
        help="Maximum tokens for the warmup round (default: 1)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (suppresses verbose output)",
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Read prompts from file (one per line, empty lines skipped). Use '-' for stdin.",
    )
    parser.add_argument(
        "prompts",
        nargs="*",
        help="Prompt strings to test (can be multiple)",
    )

    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        return

    client = OpenAIClient(
        server_type=args.backend,
        host=args.host,
        port=args.port,
        model=args.model,
    )

    try:
        available_models = client.list_models(timeout=10)
    except urllib.error.HTTPError as e:
        print_http_error(e, f"listing models on {client.label}")
        return
    except urllib.error.URLError as e:
        print(f"Error: Could not connect to {client.label} at {client.base_url}")
        print(f"  Make sure the server is running.")
        print(f"  Reason: {e.reason}")
        return
    except Exception as e:
        print(f"Error: Could not connect to {client.label} at {client.base_url}")
        print(f"  Reason: {e}")
        return

    if args.model is None:
        if args.json:
            print(json.dumps({"server": {"type": args.backend, "label": client.label, "url": client.base_url}, "models": available_models}))
        elif not available_models:
            print(f"\nNo models loaded on {client.label} at {client.base_url}")
        else:
            print(f"\nAvailable models on {client.label} at {client.base_url}:\n")
            for m in available_models:
                print(f"  {m}")
        return

    if args.model not in available_models:
        print(f"Error: Model '{args.model}' not found on {client.label} at {client.base_url}")
        if available_models:
            print(f"\nAvailable models:")
            for m in available_models:
                print(f"  {m}")
        else:
            print(f"\nNo models are currently loaded.")
        return

    client.model = args.model

    if args.warmup:
        try:
            if not args.json:
                print(f"\n[Warmup] Running quick warmup round ({args.warmup_tokens} token(s))...", end=" ", flush=True)
            if args.stream:
                client.stream_generate("Hi", max_tokens=args.warmup_tokens)
            else:
                client.generate("Hi", max_tokens=args.warmup_tokens)
            if not args.json:
                print("done")
        except Exception:
            if not args.json:
                print("skipped (server busy or unavailable)")

    if args.prompt_file:
        if args.prompt_file == "-":
            prompts = [line.strip() for line in sys.stdin if line.strip()]
        else:
            try:
                with open(args.prompt_file) as f:
                    prompts = [line.strip() for line in f if line.strip()]
            except FileNotFoundError:
                print(f"Error: prompt file '{args.prompt_file}' not found.")
                return
            except PermissionError:
                print(f"Error: permission denied reading '{args.prompt_file}'.")
                return
    elif args.prompts:
        prompts = args.prompts
    else:
        prompts = DEFAULT_PROMPTS

    if not prompts:
        print("Error: no prompts provided.")
        return

    results = measure_generation_speed(
        client,
        prompts,
        iterations=args.iterations,
        max_tokens=args.max_tokens,
        use_streaming=args.stream,
        timeout=args.timeout,
        verbose=not args.json,
    )

    if args.json:
        print_json_results(client, results, args.stream, args.max_tokens, args.iterations)
    else:
        print_summary(results, args.stream)

    return results


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
