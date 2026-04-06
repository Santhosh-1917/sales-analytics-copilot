# src/agent/copilot.py
# Phase 5: Agentic Claude reasoning loop — multi-step tool calling
# Run: python -m src.agent.copilot

import json
import os
import time
from anthropic import Anthropic, RateLimitError
from dotenv import load_dotenv
from src.tools.tool_layer import TOOL_DEFINITIONS, dispatch_tool

load_dotenv()

client = Anthropic()
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a sales analytics assistant for a Superstore dataset covering \
Furniture, Office Supplies, and Technology across four US regions (West, East, Central, South), \
spanning 2014–2017 with ~10,000 orders.

You have access to six tools:
- get_kpis: retrieve monthly, category, or regional KPI summaries
- detect_anomalies_tool: run 4-rule anomaly detection (margin compression, discount erosion, regional outlier, growth reversal)
- drill_down: granular breakdown of sales fact data by category, region, and/or period
- get_forecast_tool: Prophet time-series forecast with 80% confidence intervals
- run_scenario: what-if analysis — simulate discount rate changes or revenue growth
- generate_sql: convert a natural language question to SQL and execute it

Rules:
- Always call the appropriate tool before answering any data question. Never guess numbers.
- If a question needs multiple tools, call them in sequence.
- Be concise and business-focused. Lead with the key insight, then support with specific numbers.
- When quoting figures, round to 2 decimal places and include units ($, %, etc.).
- If a tool returns an error, explain what went wrong and suggest an alternative.
"""


class SalesCopilot:
    """Stateful multi-turn sales analytics agent powered by Claude."""

    def __init__(self) -> None:
        self.conversation_history: list[dict] = []

    def reset(self) -> None:
        """Clear conversation history to start a new session."""
        self.conversation_history = []

    def chat(self, user_message: str) -> tuple[str, list[tuple]]:
        """
        Process one user turn, run the tool loop, and return the final response.

        Parameters
        ----------
        user_message : str
            The user's question or instruction.

        Returns
        -------
        tuple[str, list[tuple]]
            (text_response, tool_calls_made)
            tool_calls_made is a list of (tool_name, tool_input, tool_result) tuples.
        """
        self.conversation_history.append({"role": "user", "content": user_message})

        # Truncate history if it grows too long (keep first + last 18 turns)
        if len(self.conversation_history) > 20:
            self.conversation_history = (
                self.conversation_history[:1] + self.conversation_history[-18:]
            )

        tool_calls_made: list[tuple] = []

        while True:
            for attempt in range(3):
                try:
                    response = client.messages.create(
                        model=MODEL,
                        max_tokens=4096,
                        system=SYSTEM_PROMPT,
                        tools=TOOL_DEFINITIONS,
                        messages=self.conversation_history,
                    )
                    break
                except RateLimitError:
                    if attempt < 2:
                        wait = 60 * (attempt + 1)  # 60s, then 120s
                        print(f"  [copilot] Rate limit hit — waiting {wait}s before retry...")
                        time.sleep(wait)
                    else:
                        raise

            # Append full assistant response (may contain text + tool_use blocks)
            self.conversation_history.append(
                {"role": "assistant", "content": response.content}
            )

            if response.stop_reason == "end_turn":
                # Extract text from the response
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text = block.text
                        break
                return text, tool_calls_made

            if response.stop_reason == "tool_use":
                # Collect all tool_use blocks and dispatch them
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    try:
                        result = dispatch_tool(block.name, block.input)
                    except Exception as e:
                        result = {"error": str(e)}

                    tool_calls_made.append((block.name, block.input, result))
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        }
                    )

                # Feed tool results back to Claude
                self.conversation_history.append(
                    {"role": "user", "content": tool_results}
                )

            else:
                # Unexpected stop reason — bail out gracefully
                return f"Unexpected stop reason: {response.stop_reason}", tool_calls_made


# ─── CLI RUNNER ───────────────────────────────────────────────────────────────

def run_cli() -> None:
    """Interactive command-line chat loop."""
    copilot = SalesCopilot()
    print("\nSales Copilot ready. Type 'exit' to quit, 'reset' to clear history.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Bye!")
            break
        if user_input.lower() == "reset":
            copilot.reset()
            print("Conversation history cleared.\n")
            continue

        response, tool_calls = copilot.chat(user_input)

        if tool_calls:
            print(f"\n[Tools used: {', '.join(tc[0] for tc in tool_calls)}]")

        print(f"\nCopilot: {response}\n")


if __name__ == "__main__":
    run_cli()
