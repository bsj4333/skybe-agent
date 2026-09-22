from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini")

response = llm.invoke("한국어로 짧게 자기소개 해줘")

print(response.content)
