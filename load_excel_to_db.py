import pandas as pd
import sqlite3

EXCEL_PATH = "../data/questions.xlsx"
DB_PATH = "questions.db"

# 1) 엑셀 읽기
df = pd.read_excel(EXCEL_PATH)

# 2) DB 연결
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 3) 테이블 생성
cur.execute("""
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area TEXT,
    qtype TEXT,
    difficulty TEXT,
    passage TEXT,
    question TEXT,
    choice1 TEXT,
    choice2 TEXT,
    choice3 TEXT,
    choice4 TEXT,
    choice5 TEXT,
    answer INTEGER
);
""")

# 4) 엑셀 데이터 → DB 삽입
for _, row in df.iterrows():
    cur.execute("""
        INSERT INTO questions (
            area, qtype, difficulty, passage, question,
            choice1, choice2, choice3, choice4, choice5, answer
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["문제영역"],
        row["문제유형"],
        row["난이도"],
        row.get("지문", None),
        row["문제내용"],
        row["선지1"],
        row["선지2"],
        row["선지3"],
        row["선지4"],
        row["선지5"],
        int(row["정답번호"])
    ))

conn.commit()
conn.close()

print("questions.db 생성 완료!")
