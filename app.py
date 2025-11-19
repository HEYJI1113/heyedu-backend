from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

DB_PATH = "questions.db"

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/questions")
def get_questions(limit: int = 300):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM questions LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return {"questions": [dict(r) for r in rows]}
