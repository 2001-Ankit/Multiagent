---
title: What Broke When I Built a Multi-Agent AI Assistant on Free-Tier Model Quotas
slug: what-broke-when-i-built-a-multi-agent-ai-assistant-on-free-t
date: 2026-08-05
description: As I reflect on my experience building a personal multi-agent AI assistant, I realized that several key issues arose when relying on free-tier model quotas. In this post, I'll shar
tags: ai,engineering
status: draft
---

As I reflect on my experience building a personal multi-agent AI assistant, I realized that several key issues arose when relying on free-tier model quotas. In this post, I'll share my first-hand evidence and the lessons I learned from building and running my project.

## Introduction to My Project
My project consists of a 2,329-line orchestrator that coordinates 13 specialist agents, including search, finance, news, academic, job finder, market opportunity, and others. I also wrote 155 automated tests to ensure the system's reliability. However, despite my best efforts, I encountered several challenges that I'll outline below.

## Measured Latency
One of the primary issues I faced was latency. According to my logs, the median response time was 6.7 seconds, with a p90 of 24.0 seconds, and the slowest run taking 119.7 seconds. Only 5 out of 22 runs finished in under a second, which is far from the 800 milliseconds required for a real-time voice interface. This meant that I was about 8x over budget at the median and 30x at p90.

## The Swarm Ate the Quota
Running specialists in parallel pushed a single query to roughly 70,000 tokens, triggering rate limits almost immediately. To mitigate this, I implemented three fixes: capping each tool result at 1,500 characters, keeping only the 2 newest tool outputs at full length and compacting older ones, and capping concurrent agents at 3. The history compaction mattered most, as conversation history grows quadratically when every agent's full tool output stays in context.

## Not All Rate Limits Are the Same
I initially treated every HTTP 429 identically, which was incorrect and expensive. A per-minute limit (TPM) should back off and retry the same model, while a per-day limit (TPD) must not retry at all, as the quota is gone until tomorrow. Classifying the two separately was the single highest-value reliability fix I made.

## Model Fallback Across Providers
My model fallback chain consists of llama-3.3-70b-versatile (Groq), then llama-3.1-8b-instant (Groq), then openai/gpt-oss-120b (Groq), and finally nvidia/llama-3.3-nemotron-super-49b-v1.5 (NVIDIA). I deliberately crossed providers, as when Groq's daily quota is exhausted, every Groq model is exhausted at once. My logs show that the chain itself changed mid-project, with 3 runs using moonshotai/kimi-k2.6 before it started returning 404, and 13 later runs using the NVIDIA nemotron model that replaced it.

## The Model That Could Not Call Tools
My original default model, gpt-oss-20b, kept producing output_parse_failed and tool_use_failed errors. The problem was not my prompt, but the model's inability to handle structured tool calling. Switching the default to llama-3.3-70b-versatile fixed a class of bugs I had spent hours trying to prompt my way out of.

## A Colon Almost Broke the Blog
My agent wrote posts with unquoted colons in the frontmatter, which is invalid YAML. The fix was to quote every generated string, rather than trusting the model's formatting. Generated content needs escaping exactly like user input does.

## Two Repos, One Mistake
The agent wrote posts into one repo using one frontmatter schema, while the website read a different directory in a different repo using a different schema. Nothing connected them, so posts were generated correctly but never appeared. Both publish commands ended by printing git commands for me to run by hand, which meant the automation stopped one step short of being useful.

## Key Takeaways
To avoid the pitfalls I encountered, keep the following in mind:
* Measure and monitor latency to ensure it meets your requirements.
* Implement rate limiting and model fallback strategies to avoid quota exhaustion.
* Classify rate limits correctly to avoid unnecessary retries.
* Use a model fallback chain that crosses providers to ensure reliability.
* Test your model's ability to handle structured tool calling.
* Escape generated content to avoid formatting issues.
* Ensure that your automation is complete and connected to avoid manual intervention.
