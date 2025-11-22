import os
import json
import sqlite3
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# =========================
# 기본 설정
# =========================

DB_PATH = "questions.db"

# Render 환경변수에 OPENAI_API_KEY 등록해 둔 상태 기준
# (Render 대시보드 Environment 탭에서 설정)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

# CORS (로컬 파일, Netlify 등 어디서든 호출 가능하도록 *)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 나중에 필요하면 Netlify 도메인만 허용하도록 변경
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Pydantic 모델 정의
# =========================

class QuestionOut(BaseModel):
    id: int
    question_id: int

    # 지문은 없는 문제도 있을 수 있으므로 Optional
    passage: Optional[str] = None

    question: str

    # 선지, 영역, 유형, 난이도 중 일부가 비어 있는 문항을 위해 Optional 처리
    choice1: Optional[str] = None
    choice2: Optional[str] = None
    choice3: Optional[str] = None
    choice4: Optional[str] = None
    choice5: Optional[str] = None

    area: Optional[str] = None
    qtype: Optional[str] = None
    difficulty: Optional[str] = None

    correct_answer: int

    class Config:
        orm_mode = True


class AnswerItem(BaseModel):
    # 프론트에서 보내는 1문항에 대한 정보
    question_id: int
    selected: Optional[int]  # 학생이 고른 보기(1~5), 미답이면 null
    correct_answer: int
    area: Optional[str] = None
    qtype: Optional[str] = None
    difficulty: Optional[str] = None


class SubmitPayload(BaseModel):
    answers: List[AnswerItem]


class Feedback(BaseModel):
    summary: str
    strengths: str
    weaknesses: str
    suggestions: str


class SubmitResponse(BaseModel):
    score: int
    total: int
    feedback: Feedback


# =========================
# DB 유틸
# =========================

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =========================
# 라우터
# =========================

@app.get("/api/questions", response_model=List[QuestionOut])
def get_questions():
    """
    DB에서 모든 문항을 읽어 프론트로 전달
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM questions").fetchall()
        conn.close()

        questions = [dict(row) for row in rows]
        return questions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 오류: {e}")


@app.post("/api/submit", response_model=SubmitResponse)
def submit_answers(payload: SubmitPayload):
    """
    학생 응답을 받아 점수 계산 + LLM으로 학습 피드백 생성
    """
    if not payload.answers:
        raise HTTPException(status_code=400, detail="answers가 비어 있습니다.")

    total = len(payload.answers)
    correct_count = 0

    # LLM 프롬프트를 위해 간단한 텍스트 요약용 리스트 생성
    rows_for_llm = []

    for idx, ans in enumerate(payload.answers, start=1):
        is_correct = ans.selected is not None and ans.selected == ans.correct_answer
        if is_correct:
            correct_count += 1

        rows_for_llm.append(
            {
                "no": idx,
                "question_id": ans.question_id,
                "selected": ans.selected,
                "correct": ans.correct_answer,
                "is_correct": is_correct,
                "area": ans.area,
                "qtype": ans.qtype,
                "difficulty": ans.difficulty,
            }
        )

    # -------------------------
    # LLM 호출 (정성적 피드백)
    # -------------------------
    # LLM에게 건네줄 요약 텍스트
    answers_text_lines = []
    for r in rows_for_llm:
        s = (
            f"{r['no']}번 | 영역: {r['area']} | 유형: {r['qtype']} | 난이도: {r['difficulty']} | "
            f"선택: {r['selected']} | 정답: {r['correct']} | {'정답' if r['is_correct'] else '오답'}"
        )
        answers_text_lines.append(s)

    answers_text = "\n".join(answers_text_lines)

    system_prompt = (
        "너는 중학생 영어 학습 진단을 돕는 교사야. "
        "아래에 주어지는 학생의 문제 풀이 결과(각 문항의 영역/유형/난이도와 정답 여부)를 보고 "
        "학생의 현재 영어 학습 수준을 분석하고, 구체적인 피드백을 JSON 형식으로 작성해줘.\n\n"
        "JSON 키는 반드시 다음 네 개만 사용해:\n"
        "1) summary: 전체적인 한 줄 요약 (한국어)\n"
        "2) strengths: 잘하고 있는 점 (한국어, 2~3문장)\n"
        "3) weaknesses: 부족한 점과 오답 경향 (한국어, 2~3문장)\n"
        "4) suggestions: 앞으로의 학습 방향과 구체적인 추천 활동 (한국어, 3~4문장)\n\n"
        "JSON 형식 예시는 다음과 같아.\n"
        '{\n'
        '  "summary": "...",\n'
        '  "strengths": "...",\n'
        '  "weaknesses": "...",\n'
        '  "suggestions": "..."\n'
        '}\n'
        "반드시 위와 같은 JSON만 출력하고, 다른 설명 문장은 출력하지 마."
    )

    user_prompt = (
        f"총 문항 수: {total}개, 맞힌 개수: {correct_count}개입니다.\n"
        f"문항별 상세 결과는 아래와 같습니다.\n\n"
        f"{answers_text}\n\n"
        "이 정보를 바탕으로 위에서 제시한 JSON 형식의 피드백을 작성해줘."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content
        feedback_json = json.loads(content)
    except Exception as e:
        # LLM 호출 실패 시, 기본값으로 대체
        feedback_json = {
            "summary": "AI 피드백 생성 중 오류가 발생했습니다. 기본 피드백을 제공합니다.",
            "strengths": "정답률과 응답 패턴을 기반으로 대략적인 실력을 추정할 수 있습니다.",
            "weaknesses": "어떤 문항에서 오답이 발생했는지 다시 확인해 보세요.",
            "suggestions": "세부적인 피드백을 위해 나중에 다시 시도해 보거나, 교사와 함께 풀이를 점검해 보세요.",
        }

    feedback = Feedback(
        summary=feedback_json.get("summary", ""),
        strengths=feedback_json.get("strengths", ""),
        weaknesses=feedback_json.get("weaknesses", ""),
        suggestions=feedback_json.get("suggestions", ""),
    )

    return SubmitResponse(
        score=correct_count,
        total=total,
        feedback=feedback,
    )


@app.get("/")
def root():
    return {"message": "HeyEdu backend is running"}
