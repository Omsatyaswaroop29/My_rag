import streamlit as st
import openai
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
import pdfplumber
import shelve
import textract

# Load environment variables
load_dotenv()

# Constants for user and bot avatars
USER_AVATAR = "👤"
BOT_AVATAR = "🤖"

# Initialize session state for messages if not already present
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Pinecone initialization
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index_name = os.getenv('PINECONE_INDEX')
vector_store = pc.Index(name=index_name)

client = openai.Client(api_key=os.getenv('OPENAI_API_KEY'))

def extract_text_from_pdf(file):
    text = ''
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + '\n'
    return text

def extract_text_from_docx(file):
    text = textract.process(file)
    return text.decode("utf-8")

def extract_text_from_other(file):
    with open(file, "rb") as f:
        text = f.read().decode("utf-8")
    return text

def fetch_webpage_content(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        text = soup.get_text()
        
        return {'content': text}
    except requests.RequestException as e:
        return f"Failed to fetch {url}: {str(e)}"

# Streamlit UI
st.title("Intelligent Chatbot")
with st.sidebar:
    st.write("## File Upload")
    uploaded_files = st.file_uploader("Upload files", accept_multiple_files=True)
    if uploaded_files and st.button("Load and Index Documents"):
        for uploaded_file in uploaded_files:
            if uploaded_file.type == "application/pdf":
                text = extract_text_from_pdf(uploaded_file)
            elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                text = extract_text_from_docx(uploaded_file)
            else:
                text = extract_text_from_other(uploaded_file)
                
            document_chunks = [text[i:i+512] for i in range(0, len(text), 512)]
            for i, chunk in enumerate(document_chunks):
                response = client.embeddings.create(model="text-embedding-ada-002", input=chunk)
                vector_store.upsert([{"id": str(i), "values": response.data[0].embedding, "metadata": {"text": chunk}}])

    st.write("## Fetch Web Content")
    urls_input = st.text_area("Enter URLs, one per line:")
    if st.button("Fetch Web Content"):
        if urls_input:
            urls = urls_input.split('\n')
            for url in urls:
                if url:
                    webpage_content = fetch_webpage_content(url.strip())
                    st.text_area(f"Content from {url}:", value=webpage_content['content'], height=150)

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar=USER_AVATAR if message["role"] == "user" else BOT_AVATAR):
        st.markdown(f"**{datetime.fromtimestamp(message['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}** - {message['content']}")

# User query and processing
if user_query := st.chat_input("Ask a question:"):
    embedding_response = client.embeddings.create(model="text-embedding-ada-002", input=user_query)
    top_docs = vector_store.query(vector=embedding_response.data[0].embedding, top_k=5, include_metadata=True)
    
    context = " ".join([doc.metadata.get('text', '') for doc in top_docs.matches])
    full_query = f"Answer the user's question based on the below context:\n\n{context}. The question is: {user_query}"
    chat_response = openai.chat.completions.create(model="gpt-3.5-turbo-0125", messages=[{"role": "user", "content": full_query}], temperature=0.6)
    
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query, "timestamp": datetime.now().timestamp()})
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        st.write(chat_response.choices[0].message.content)
        st.session_state.messages.append({"role": "assistant", "content": chat_response.choices[0].message.content, "timestamp": datetime.now().timestamp()})

# Save chat history after each interaction
def save_chat_history(messages):
    with shelve.open("chat_history", writeback=True) as db:
        db["messages"] = messages

save_chat_history(st.session_state.messages)
