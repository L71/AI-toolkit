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


# Default ports per server type
SERVER_PORTS = {
    "ollama": 11434,
    "llama-cpp": 8080,
    "omlx": 8000,
}

# Human-readable server labels
SERVER_LABELS = {
    "ollama": "Ollama",
    "llama-cpp": "llama.cpp",
    "omlx": "oMLX",
}


class OpenAIClient:
    """Client for any server exposing an OpenAI-compatible /v1/chat/completions API."""

    def __init__(self, server_type: str, host: str = "localhost", port: Optional[int] = None, model: Optional[str] = None):
        self.server_type = server_type
        self.host = host
        self.port = port or SERVER_PORTS.get(server_type, 8000)
        self.base_url = f"http://{host}:{self.port}"
        self.label = SERVER_LABELS.get(server_type, server_type)
        self.model = model

    def _make_request(self, url: str, payload: dict, timeout: Optional[float] = None) -> urllib.request.Request:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return req

    def generate(self, prompt: str, max_tokens: int = 128, timeout: Optional[float] = None) -> dict:
        """Non-streaming chat completion. Returns the full response dict."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        }
        req = self._make_request(url, payload)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def stream_generate(self, prompt: str, max_tokens: int = 128, timeout: Optional[float] = None) -> dict:
        """Streaming chat completion. Returns dict with output, token counts, TTFT, and elapsed time.

        Parses SSE chunks to extract per-token arrival times and time-to-first-token.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        req = self._make_request(url, payload)

        start_time = time.time()
        first_token_time = None
        output_parts = []
        completion_tokens = 0
        prompt_tokens = 0
        usage_received = False

        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Read the response as a stream of SSE chunks using readline()
            # so we actually get chunks as they arrive (not blocked until full response).
            buffer = ""
            while True:
                raw_chunk = response.readline()
                if not raw_chunk:
                    break
                buffer += raw_chunk.decode("utf-8")
                # Process complete SSE messages from the buffer.
                # SSE messages are separated by blank lines (two consecutive newlines).
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    for raw_line in block.split("\n"):
                        line = raw_line.rstrip("\r")

                        if not line:
                            continue

                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]  # Strip "data: " prefix

                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            sse_chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Extract content from delta
                        choices = sse_chunk.get("choices", [])
                        for choice in choices:
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                output_parts.append(content)
                                if first_token_time is None:
                                    first_token_time = time.time()

                        # Extract usage from the final chunk (may be a separate chunk with only usage)
                        usage = sse_chunk.get("usage")
                        if usage:
                            usage_received = True
                            completion_tokens = usage.get("completion_tokens", 0)
                            prompt_tokens = usage.get("prompt_tokens", 0)

        elapsed = time.time() - start_time
        ttft = (first_token_time - start_time) if first_token_time is not None else 0.0
        output_text = "".join(output_parts)

        # Fallback: if the API didn't return usage, estimate from text
        tokens_from_api = usage_received
        if completion_tokens == 0:
            completion_tokens = count_generated_tokens(output_text)
        if prompt_tokens == 0:
            prompt_tokens = max(1, len(prompt) // 4)

        return {
            "output": output_text,
            "completion_tokens": completion_tokens,
            "prompt_tokens": prompt_tokens,
            "elapsed": elapsed,
            "ttft": ttft,
            "tokens_from_api": tokens_from_api,
        }

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

    print(f"✗ HTTP {e.code}: {e.reason} ({context})")

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

    This is a rough heuristic (off by ~30-50% for non-English text or complex
    punctuation). The API's own usage field is preferred whenever available.
    """
    tokens = 1
    for word in text.split():
        tokens += len(word) // 5 + 1
    return max(1, tokens)


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
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
) -> list:
    """Measure generation speed for multiple prompts."""
    results = []

    mode_label = "streaming" if use_streaming else "non-streaming"
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
        print(f"\n--- Prompt {i}/{len(prompts)} ---")
        print(f"Input length: {len(prompt)} chars")

        total_input_tokens = 0
        total_output_tokens = 0
        total_elapsed = 0.0
        total_ttft = 0.0
        successful_iterations = 0

        for iter_num in range(iterations):
            print(f"  Iteration {iter_num + 1}/{iterations}...", end=" ", flush=True)
            start_time = time.time()

            try:
                if use_streaming:
                    result = client.stream_generate(prompt, max_tokens=max_tokens, timeout=timeout)
                    output_text = result["output"]
                    output_tokens = result["completion_tokens"]
                    input_tokens = result["prompt_tokens"]
                    elapsed = result["elapsed"]
                    ttft = result["ttft"]
                    tokens_from_api = result.get("tokens_from_api", False)
                else:
                    result = client.generate(prompt, max_tokens=max_tokens, timeout=timeout)
                    elapsed = time.time() - start_time
                    tokens_from_api = bool(result.get("usage"))
                    usage = result.get("usage", {})
                    output_tokens = usage.get("completion_tokens", 0)
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    ttft = None  # No separate TTFT in non-streaming

                    # Fallback token estimation
                    if output_tokens == 0:
                        output_tokens = count_generated_tokens(output_text)
                    if input_tokens == 0:
                        input_tokens = max(1, len(prompt) // 4)

                tokens_per_second = output_tokens / elapsed if elapsed > 0 else 0
                ttft_str = format_duration(ttft) if ttft is not None else "N/A (non-streaming)"

                print(f"\u2713 {output_tokens} tokens in {format_duration(elapsed)} ({tokens_per_second:.1f} t/s) | TTFT: {ttft_str}")

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_elapsed += elapsed
                if ttft is not None:
                    total_ttft += ttft
                successful_iterations += 1

            except urllib.error.HTTPError as e:
                print_http_error(e, f"{client.label} generation")
            except Exception as e:
                print(f"\u2717 Error: {e}")

        if successful_iterations > 0:
            avg_tps = total_output_tokens / total_elapsed if total_elapsed > 0 else 0
            avg_ttft = total_ttft / successful_iterations if ttft is not None else None

            results.append({
                "prompt_id": i,
                "input_length": len(prompt),
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_elapsed": total_elapsed,
                "avg_tokens_per_second": avg_tps,
                "avg_time_per_token": 1 / avg_tps if avg_tps > 0 else float('inf'),
                "avg_ttft": avg_ttft,
                "successful_iterations": successful_iterations,
                "tokens_from_api": tokens_from_api,
            })

    return results


def print_summary(results: list):
    """Print a summary of the measurement results."""
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    if not results:
        print("\nNo successful measurements.")
        print("=" * 60 + "\n")
        return

    # Determine whether any results used API-reported token counts
    all_api = all(r.get("tokens_from_api", False) for r in results)
    some_api = any(r.get("tokens_from_api", False) for r in results)

    avg_tps = sum(r["avg_tokens_per_second"] for r in results) / len(results)
    avg_tpt = sum(r["avg_time_per_token"] for r in results) / len(results)

    ttft_values = [r["avg_ttft"] for r in results if r["avg_ttft"] is not None]
    avg_ttft = sum(ttft_values) / len(ttft_values) if ttft_values else None

    print(f"\nAverage tokens per second: {avg_tps:.2f}")
    print(f"Average time per token: {avg_tpt * 1000:.2f} ms")
    print(f"Average time to first token (TTFT): {format_duration(avg_ttft) if avg_ttft is not None else 'N/A (non-streaming mode)'}")
    print(f"Total measurements: {len(results)}")

    if all_api:
        print("\n  (Token counts are API-reported — exact for this model/server.)")
    elif some_api:
        print("\n  (Some token counts are API-reported, others are estimates.)")
    else:
        print("\n  (Token counts are heuristic estimates — not exact.)")

    for r in results:
        print(f"\n  Prompt {r['prompt_id']}:")
        print(f"    Input: {r['input_length']} chars ({r['input_tokens']} tokens)")
        print(f"    Output: {r['output_tokens']} tokens")
        print(f"    Speed: {r['avg_tokens_per_second']:.2f} t/s")
        print(f"    Time/token: {r['avg_time_per_token'] * 1000:.2f} ms/token")
        print(f"    TTFT: {format_duration(r['avg_ttft']) if r['avg_ttft'] is not None else 'N/A (non-streaming mode)'}")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Measure token generation speed for Ollama, llama.cpp, or oMLX servers"
    )

    parser.add_argument(
        "--server",
        choices=["ollama", "llama-cpp", "omlx"],
        default="ollama",
        help="Server type (default: ollama)",
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
        "prompts",
        nargs="*",
        help="Prompt strings to test (can be multiple)",
    )

    args = parser.parse_args()

    # No arguments: print help and exit
    if len(sys.argv) == 1:
        parser.print_help()
        return

    # Create client (model may be None at this point)
    client = OpenAIClient(
        server_type=args.server,
        host=args.host,
        port=args.port,
        model=args.model,
    )

    # Fetch available models (for listing and/or verification)
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

    # No --model specified: list available models and exit
    if args.model is None:
        if not available_models:
            print(f"\nNo models loaded on {client.label} at {client.base_url}")
        else:
            print(f"\nAvailable models on {client.label} at {client.base_url}:\n")
            for m in available_models:
                print(f"  {m}")
        return

    # --model specified: verify it exists
    if args.model not in available_models:
        print(f"Error: Model '{args.model}' not found on {client.label} at {client.base_url}")
        if available_models:
            print(f"\nAvailable models:")
            for m in available_models:
                print(f"  {m}")
        else:
            print(f"\nNo models are currently loaded.")
        return

    # Set the verified model on the client
    client.model = args.model

    # Warmup round (if enabled)
    if args.warmup:
        try:
            print(f"\n[Warmup] Running quick warmup round ({args.warmup_tokens} token(s))...", end=" ", flush=True)
            if args.stream:
                client.stream_generate("Hi", max_tokens=args.warmup_tokens)
            else:
                client.generate("Hi", max_tokens=args.warmup_tokens)
            print("done")
        except Exception:
            print("skipped (server busy or unavailable)")

    # Prompts
    if not args.prompts:
        prompts = [
            "Write a short poem about the ocean.",
            "Explain quantum computing in simple terms.",
            "What is the meaning of life?",
            "Write a Python function to sort a list.",
            "Describe the beauty of nature in three sentences.",
        ]
    else:
        prompts = args.prompts

    # Run measurements
    results = measure_generation_speed(
        client,
        prompts,
        iterations=args.iterations,
        max_tokens=args.max_tokens,
        use_streaming=args.stream,
        timeout=args.timeout,
    )

    # Print summary
    print_summary(results)

    return results


if __name__ == "__main__":
    main()
