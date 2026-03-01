#!/usr/bin/env python3
"""Entry point for the autonomous agent."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("Copy .env.example to .env and add your API key.")
        sys.exit(1)

    # Accept task from CLI args or prompt interactively
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        print("Autonomous Agent  (powered by Claude)")
        print("=" * 42)
        task = input("Enter your task: ").strip()
        if not task:
            print("No task provided. Exiting.")
            sys.exit(1)

    print(f"\nTask: {task}")
    print("=" * 42)

    # Import here so missing env var is caught first
    from agent import Agent

    agent = Agent()
    result = agent.run(task, verbose=True)

    print("\n" + "=" * 42)
    print("Result:")
    print(result)


if __name__ == "__main__":
    main()
