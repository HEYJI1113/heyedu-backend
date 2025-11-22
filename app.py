# backend/app.py

import os
import sqlite3
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI

# ---------- 기본 설정 ----------
app = FastAPI()

# CORS: 네틀리파이에서 오는 프론트 도메인도 나중에 여기에 추가 가능
origins = [
    "*",  # 개발 단계에서는 전체 허용, 배포 후에는 도메인만 허용하는 걸 추천
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI 클라이언트
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_PATH = "questions.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- 기존: 문제 리스트 API ----------
@app.get("/api/questions")
def get_questions():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM questions")
        rows = cur.fetchall()
        conn.close()

        questions = [dict(r) for r in rows]
        return {"questions": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


# ---------- 새로 추가: 답안 + LLM 피드백 ----------

class Answer(BaseModel):
    question_id: int          # 문제 id (DB의 id 컬럼)
    user_answer: int          # 학생이 고른 번호 (1~5)
    correct_answer: int       # 정답 번호 (1~5)


class SubmitRequest(BaseModel):
    grade: Optional[str] = None     # 중1/중2/중3 등
    term: Optional[str] = None      # 1학기/2학기
    textbook: Optional[str] = None  # 동아(윤) 등
    answers: List[Answer]


class FeedbackResponse(BaseModel):
    feedback_text: str              # LLM이 만들어준 정성적 피드백
    score_summary: Dict[str, Any]   # 영역/유형별 정량 요약 (간단히)


def build_feedback_prompt(payload: SubmitRequest, summary: Dict[str, Any]) -> str:
    """
    LLM에 넘길 프롬프트 문자열 생성
    """
    # 학생이 푼 정보 간단 요약
    meta_lines = []
    if payload.grade:
        meta_lines.append(f"- 학년: {payload.grade}")
    if payload.term:
        meta_lines.append(f"- 학기: {payload.term}")
    if payload.textbook:
        meta_lines.append(f"- 교과서: {payload.textbook}")

    meta_text = "\n".join(meta_lines) if meta_lines else "정보 없음"

    prompt = f"""
너는 중학생 영어 선생님이야.

학생이 풀었던 중등 영어 학습진단 평가 결과를 바탕으로
정성적인 피드백을 한국어로 작성해줘.

[학생 정보]
{meta_text}

[점수 요약]
- 전체 문항 수: {summary["total"]}문항
- 정답 개수: {summary["correct"]}문항
- 오답 개수: {summary["wrong"]}문항
- 정답률: {summary["accuracy_percent"]:.1f}%

[요청 사항]
1. 전체적인 학습 수준을 한두 문장으로 요약해줘.
2. 어휘, 문법, 독해 영역별로 어떤 강점/약점이 있는지 말해줘.
3. 학생이 다음 학기(또는 다음 단계) 학습을 위해 지금 당장 하면 좋은 공부법을
   3가지 정도 구체적으로 제안해줘.
4. 말투는 사려 깊고 응원하는 선생님처럼, 그러나 너무 유치하지 않게.

반드시 3~4개의 단락으로 나눠서 작성해줘.
"""
    return prompt.strip()


@app.post("/api/submit", response_model=FeedbackResponse)
async def submit_answers(payload: SubmitRequest):
    """
    학생 답안을 받아서:
    1) 정답/오답 집계 (간단 정량 요약)
    2) OpenAI LLM을 호출해서 정성적 피드백 생성
    """
    if not payload.answers:
        raise HTTPException(status_code=400, detail="answers 목록이 비어 있습니다.")

    # 1. 간단 정량 요약
    total = len(payload.answers)
    correct = sum(1 for a in payload.answers if a.user_answer == a.correct_answer)
    wrong = total - correct
    accuracy = (correct / total) * 100 if total > 0 else 0.0

    score_summary = {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy_percent": accuracy,
    }

    # 2. LLM 호출 (에러에 대비한 안전 처리)
    try:
        prompt = build_feedback_prompt(payload, score_summary)

        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # 필요하면 다른 모델명으로 변경 가능
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert Korean middle school English teacher.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
        )

        feedback_text = completion.choices[0].message.content.strip()
    except Exception as e:
        # API 에러 시, 최소한의 안내 문구라도 돌려주기
        raise HTTPException(status_code=500, detail=f"LLM 호출 중 오류 발생: {e}")

    return FeedbackResponse(
        feedback_text=feedback_text,
        score_summary=score_summary,
    )
