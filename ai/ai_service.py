
import os
from openai import OpenAI

def ask_ai(text):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # try:
    #     response = client.chat.completions.create(
    #         model="gpt-4o-mini",
    #         messages=[
    #             {"role":"user","content":text}
    #         ]
    #     )
    #     return response.choices[0].message.content
    # except Exception as e:
    #     return "AI 연결 실패 (API 키 확인 필요)"
    return "안녕!"
