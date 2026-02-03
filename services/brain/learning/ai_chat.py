import os
from dotenv import load_dotenv

load_dotenv()

def ask_ai_coach(question: str, context: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return (
            "LLM Coach is disabled.\n"
            "Based on your data, focus on trading only during strong market regimes "
            "and avoid overtrading."
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": context
                },
                {
                    "role": "user",
                    "content": question
                }
            ],
            temperature=0.3,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"AI Coach error: {str(e)}"
