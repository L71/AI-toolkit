
## AI toolkit

Tools & utilities for running local LLMs & other AI related stuff


## Content

### llm-service-mac

A script for running Homebrew-installed `Ollama` and `llama-server` LLM services on a Mac with sane and persistent configuration and service management. See the readme for details.

Not extensively tested but seems to work fine. Built using Claude / Sonnet 4.6 after an Ollama troubleshooting session.

This may not see much use since I discovered oMLX.


### llm-speed

A script for doing simple benchmarking of LLM configurations, designed for testing Ollama, llama.cpp / llama-server and oMLX via their OpenAI API.

Built using Qwen3.6-27B running on oMLX.


### ollama-threads-test

A script initially written to test Ollama behaviour with different numbers of CPU threads when running without GPU and in a VM.
Later updated with proper argument parsing and other fixes using Qwen3.6.

It reports the approximate prompt evaluation performance in addition to reporting token generation speed.


### howtos-docs-notes

What the headings says :-)
