from src.db.sql_db import init_db
from src.rag.vector_store import build_index

init_db()
print("SQL database created")
build_index()