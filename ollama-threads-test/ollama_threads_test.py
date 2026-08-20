#!/usr/bin/env python3

import argparse
import requests
import json


def parse_threads(threads_arg):
    """Parse --threads argument, supporting individual values and ranges.

    Examples:
        [2, 4, 6, 8]
        [2, 4, 6, 10, 11, 12, 13, 14, 15, 16]
        [2, 4, 10, 11, 12, 13, 14, 15, 16]
    """
    if isinstance(threads_arg, int):
        threads_arg = [threads_arg]
    parsed = []
    for item in threads_arg:
        if '-' in str(item):
            parts = str(item).split('-', 1)
            start, end = int(parts[0]), int(parts[1])
            parsed.extend(range(start, end + 1))
        else:
            parsed.append(int(item))
    return parsed


def list_models(host, port):
    """List available models from Ollama using /v1/models endpoint."""
    models_url = f"http://{host}:{port}/v1/models"
    try:
        reply = requests.get(models_url)
        if reply.status_code == 200:
            data = reply.json()
            models = data.get('data', [])
            if not models:
                print("No models found.")
                return
            print(f"Available models on {host}:{port}, use --model to select one for testing:")
            for model in models:
                print(model['id'])
        else:
            print(f"Error: Server returned status {reply.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot connect to {models_url}")
        print("Make sure Ollama is running on the specified host and port.")
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama with different thread counts")
    parser.add_argument("--host", required=True, help="Ollama host (e.g. llm-t01)")
    parser.add_argument("--model", help="Model name (e.g. qwen3.6:35b)")
    parser.add_argument("--port", type=int, default=11434, help="Ollama port (default: 11434)")
    parser.add_argument("--threads", nargs="+", default=None,
                        help="Thread counts to test, supports ranges (e.g. 2 4 6 10-16). "
                             "If omitted, uses the server default.")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Number of tests per thread count (default: 3)")
    parser.add_argument("--prompt", default="what is 2 ** 2 ?",
                        help="Prompt to use (default: 'what is 2 ** 2 ?')")
    args = parser.parse_args()

    # If --model is not specified, list models and exit
    if not args.model:
        list_models(args.host, args.port)
        return

    if args.threads is None:
        server_default_used = True
        print("Warning: --threads not specified, using the server's default thread count.")
        print()
        test_threads = None
    else:
        test_threads = parse_threads(args.threads)

    endpoint = f"http://{args.host}:{args.port}/api/generate"
    model = args.model
    prompt = args.prompt
    no_of_tests = args.iterations
    options_default = {}
    post_header = {"Content-Type": "application/json"}

    print(f"Running tests on endpoint {endpoint}\nModel {model}\n")

    results = {}  # dict of result dicts

    # If --threads was not specified, wrap None in a special sentinel for single-pass treatment
    if test_threads is None:
        test_threads = [None]

    for no_threads in test_threads:  # loop for list of threads to test
        if no_threads is None:
            thr_dictkey = "server default"
        else:
            thr_dictkey = str(no_threads)

        results[thr_dictkey] = {"pr_eval_rate": [], "eval_rate": [], "prompt_chars": [], "output_chars": [], "prompt_tokens": [], "output_tokens": []}  # empty dict entry for this type of threads

        if no_threads is None:
            print(f"threads: server default x {no_of_tests:3d} tests... (please wait)")
        else:
            print(f"threads: {no_threads:4d} x {no_of_tests:3d} tests... (please wait)")

        for test_no in range(0, no_of_tests):

            # prompt = f"{test_no} * {test_no} is equal to ?"
            if no_threads is None:
                post_data = {"model": model, "prompt": prompt, "stream": False}
            else:
                post_data = {"model": model, "prompt": prompt, "stream": False,
                             "options": options_default | {'num_thread': no_threads}}
            try:
                reply = requests.post(endpoint, data=json.dumps(post_data), headers=post_header)
                if reply.status_code == 200:

                    r_data = reply.json()
                    r_prompt_eval_count = r_data['prompt_eval_count']
                    r_prompt_eval_duration = int(r_data['prompt_eval_duration']) / 1e9
                    r_eval_count = r_data['eval_count']
                    r_eval_duration = int(r_data['eval_duration']) / 1e9
                    output_text = r_data.get('response', '')

                    results[thr_dictkey]['pr_eval_rate'].append(r_prompt_eval_count / r_prompt_eval_duration)
                    results[thr_dictkey]['eval_rate'].append(r_eval_count / r_eval_duration)
                    results[thr_dictkey]['prompt_chars'].append(len(prompt))
                    results[thr_dictkey]['output_chars'].append(len(output_text))
                    results[thr_dictkey]['prompt_tokens'].append(r_prompt_eval_count)
                    results[thr_dictkey]['output_tokens'].append(r_eval_count)
                    print(f"  Test {test_no + 1}: prompt: {len(prompt)} chars ({r_prompt_eval_count} tokens)")
                    print(f"  -> output: {len(output_text)} chars ({r_eval_count} tokens)  prompt eval rate: {r_prompt_eval_count / r_prompt_eval_duration:6.2f} t/s  eval rate: {r_eval_count / r_eval_duration:6.2f} t/s")
                else:
                    print(f"  Warning: Server returned status {reply.status_code} (test {test_no + 1}/{no_of_tests})")
            except requests.exceptions.ConnectionError:
                print(f"  Error: Cannot connect to {endpoint}")
                print("  Make sure Ollama is running on the specified host and port.")
                return
            except requests.exceptions.Timeout:
                print(f"  Error: Request timed out (test {test_no + 1}/{no_of_tests})")
            except requests.exceptions.RequestException as e:
                print(f"  Error: {e}")

    print()
    print("Final averages for tests:")
    for threads, data in results.items():
        if data['pr_eval_rate']:
            if threads == "server default":
                no_threads_str = "server default"
            else:
                no_threads = int(threads)
                no_threads_str = f"{no_threads:4d}"
            avg_pr_eval_rate = round(sum(data['pr_eval_rate']) / len(data['pr_eval_rate']), 2)
            avg_eval_rate = round(sum(data['eval_rate']) / len(data['eval_rate']), 2)
            avg_prompt_chars = round(sum(data['prompt_chars']) / len(data['prompt_chars']))
            avg_output_chars = round(sum(data['output_chars']) / len(data['output_chars']))
            avg_prompt_tokens = round(sum(data['prompt_tokens']) / len(data['prompt_tokens']))
            avg_output_tokens = round(sum(data['output_tokens']) / len(data['output_tokens']))
            print(f"  threads: {no_threads_str}  tests: {no_of_tests:4d}  prompt: {avg_prompt_chars} chars ({avg_prompt_tokens} tokens)  output: {avg_output_chars} chars ({avg_output_tokens} tokens)  prompt eval rate: {avg_pr_eval_rate:6.2f} t/s  eval rate: {avg_eval_rate:6.2f} t/s")
        else:
            if threads == "server default":
                no_threads_str = "server default"
            else:
                no_threads = int(threads)
                no_threads_str = f"{no_threads:4d}"
            print(f"  threads: {no_threads_str}  No successful responses.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
