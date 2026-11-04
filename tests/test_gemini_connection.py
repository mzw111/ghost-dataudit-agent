from bs.agent.client import GeminiClient


def main():
    print("Connecting to Gemini...")

    gemini = GeminiClient()

    response = gemini.generate(
        "Explain what a personal data deletion audit is in two sentences."
    )

    print("\nGemini response:")
    print(response)


if __name__ == "__main__":
    main()