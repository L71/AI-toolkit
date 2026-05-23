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
    parsed = []
    for item in threads_arg:
        if '-' in item:
            parts = item.split('-', 1)
            start, end = int(parts[0]), int(parts[1])
            parsed.extend(range(start, end + 1))
        else:
            parsed.append(int(item))
    return parsed


def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama with different thread counts")
    parser.add_argument("--host", required=True, help="Ollama host (e.g. llm-t01)")
    parser.add_argument("--model", required=True, help="Model name (e.g. qwen3.6:35b)")
    parser.add_argument("--port", type=int, default=11434, help="Ollama port (default: 11434)")
    parser.add_argument("--threads", nargs="+", default=[2, 4, 5, 6, 7, 8],
                        help="Thread counts to test, supports ranges (e.g. 2 4 6 10-16)")
    parser.add_argument("--iterations", type=int, default=5,
                        help="Number of tests per thread count (default: 5)")
    parser.add_argument("--prompt", default="what is 2 ** 2 ?",
                        help="Prompt to use (default: 'what is 2 ** 2 ?')")
    args = parser.parse_args()

    test_threads = parse_threads(args.threads)

    endpoint = f"http://{args.host}:{args.port}/api/generate"
    model = args.model
    prompt = args.prompt
    no_of_tests = args.iterations
    options_default = {}
    post_header = {"Content-Type": "application/json"}

    print(f"Running tests on endpoint {endpoint}\nModel {model}\nPrompt: {prompt}\n")

    results = {}  # dict of result dicts

    for no_threads in test_threads:  # loop for list of threads to test
        thr_dictkey = str(no_threads)
        results[thr_dictkey] = {"pr_eval_rate": [], "eval_rate": []}  # empty dict entry for this type of threads

        print(f"threads: {no_threads:4d} x {no_of_tests:3d} tests... (please wait)")

        for test_no in range(0, no_of_tests):

            # prompt = f"{test_no} * {test_no} is equal to ?"
            post_data = {"model": model, "prompt": prompt, "stream": False,
                         "options": options_default | {'num_thread': no_threads}}
            reply = requests.post(endpoint, data=json.dumps(post_data), headers=post_header)
            if reply.status_code == 200:

                r_data = reply.json()
                r_time = reply.elapsed.total_seconds()
                r_prompt_eval_count = r_data['prompt_eval_count']
                r_prompt_eval_duration = int(r_data['prompt_eval_duration']) / 1e9
                r_eval_count = r_data['eval_count']
                r_eval_duration = int(r_data['eval_duration']) / 1e9

                results[thr_dictkey]['pr_eval_rate'].append(r_prompt_eval_count / r_prompt_eval_duration)
                results[thr_dictkey]['eval_rate'].append(r_eval_count / r_eval_duration)

        # Print progress after each thread count
        data = results[thr_dictkey]
        avg_pr_eval_rate = round(sum(data['pr_eval_rate']) / len(data['pr_eval_rate']), 2)
        avg_eval_rate = round(sum(data['eval_rate']) / len(data['eval_rate']), 2)
        print(f"  threads: {no_threads:4d}  tests: {no_of_tests:4d}  prompt eval rate: {avg_pr_eval_rate:6.2f} t/s  eval rate: {avg_eval_rate:6.2f} t/s\n")

    print("Final averages for tests:")
    for threads, data in results.items():
        no_threads = int(threads)
        avg_pr_eval_rate = round(sum(data['pr_eval_rate']) / len(data['pr_eval_rate']), 2)
        avg_eval_rate = round(sum(data['eval_rate']) / len(data['eval_rate']), 2)
        print(f"  threads: {no_threads:4d}  tests: {no_of_tests:4d}  prompt eval rate: {avg_pr_eval_rate:6.2f} t/s  eval rate: {avg_eval_rate:6.2f} t/s")


if __name__ == "__main__":
    main()
