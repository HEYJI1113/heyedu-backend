import sqlite3
import pandas as pd
from pathlib import Path

# 엑셀 파일 경로 (필요하면 수정)
EXCEL_PATH = Path("..") / "data" / "questions.xlsx"  # 실제 파일 경로에 맞게 수정

DB_PATH = Path("questions.db")

def create_table(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            passage TEXT,
            question TEXT,
            choice1 TEXT,
            choice2 TEXT,
            choice3 TEXT,
            choice4 TEXT,
            choice5 TEXT,
            area TEXT,
            qtype TEXT,
            difficulty TEXT,
            correct_answer INTEGER
        );
        """
    )
    conn.commit()


def load_from_excel(conn: sqlite3.Connection):
    # 엑셀 읽기
    df = pd.read_excel(EXCEL_PATH)

    # 엑셀 컬럼 이름을 DB 컬럼과 맞춰서 매핑
    # 엑셀에 실제로 있는 컬럼 이름에 맞게 왼쪽 부분을 수정해줘야 함!
    rename_map = {
        "문항ID": "question_id",
        "지문": "passage",
        "문항": "question",
        "선지1": "choice1",
        "선지2": "choice2",
        "선지3": "choice3",
        "선지4": "choice4",
        "선지5": "choice5",
        "영역": "area",
        "문항유형": "qtype",
        "난이도": "difficulty",
        "정답": "correct_answer",  # 엑셀에서 정답번호 컬럼 이름에 맞게 수정
    }

    df = df.rename(columns=rename_map)

    # 필요한 컬럼만 남기기 (없으면 에러가 나니까, 엑셀 컬럼명 꼭 확인!)
    required_cols = [
        "question_id",
        "passage",
        "question",
        "choice1", "choice2", "choice3", "choice4", "choice5",
        "area", "qtype", "difficulty", "correct_answer",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"엑셀에 없는 컬럼이 있습니다: {missing}")

    df = df[required_cols]

    # DB에 insert
    df.to_sql("questions", conn, if_exists="append", index=False)
    conn.commit()


def main():
    print(f"엑셀에서 DB 생성 시작: {EXCEL_PATH}")
    conn = sqlite3.connect(DB_PATH)
    create_table(conn)
    load_from_excel(conn)
    conn.close()
    print(f"완료! DB 파일 생성: {DB_PATH.absolute()}")


if __name__ == "__main__":
    main()
