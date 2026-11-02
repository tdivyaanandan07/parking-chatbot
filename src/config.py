import os
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

load_dotenv()

llm = AzureChatOpenAI(
    azure_endpoint=os.environ["DIAL_ENDPOINT"],
    api_key=os.environ["DIAL_API_KEY"],
    api_version=os.environ["DIAL_API_VERSION"],
    azure_deployment=os.environ["CHAT_MODEL"],
    temperature=0,
)

embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=os.environ["DIAL_ENDPOINT"],
    api_key=os.environ["DIAL_API_KEY"],
    api_version=os.environ["DIAL_API_VERSION"],
    azure_deployment=os.environ["EMBED_MODEL"],
)