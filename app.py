# backend/app.py

import os
import json
import sqlite3
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI

# ---------- DB 설정 ----------
DB_PATH = "questions.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- FastAPI 앱 ----------
app = FastAPI()

# CORS (Netlify / 로컬파일 둘 다 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 필요하면 나중에 Netlify 도메인만 허용하도록 변경
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Pydantic 모델 ----------

class QuestionOut(BaseModel):
    id: int
    question: str
    passage: Optional[str] = None
    choice1: str
    choice2: str
    choice3: str
    choice4: str
    choice5: str
    correct_answer: int
    area: Optional[str] = None
    qtype: Optional[str] = None
    difficulty: Optional[str] = None


class AnswerItem(BaseModel):
    # 프론트에서 /submit 으로 보내는 각 문항 정보
    question_id: int
    selected: Optional[int] = None          # 0~4, 선택 안 하면 None
    correct_answer: Optional[int] = None    # 1~5 (엑셀 정답번호 기준)
    area: Optional[str] = None
    qtype: Optional[str] = None
    difficulty: Optional[str] = None
    user_answer: Optional[str] = None       # 선택한 보기 텍스트, 없을 수도 있음


class SubmitRequest(BaseModel):
    answers: List[AnswerItem]


class Feedback(BaseModel):
    summary: str
    strengths: str
    weaknesses: str
    recommendations: str


class SubmitResponse(BaseModel):
    score: int
    total: int
    feedback: Feedback


# ---------- OpenAI 클라이언트 ----------
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


# ---------- 엔드포인트 ----------

@app.get("/api/questions", response_model=List[QuestionOut])
def get_questions():
    """
    DB에서 모든 문항을 읽어서 프론트로 전달
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            question,
            passage,
            choice1,
            choice2,
            choice3,
            choice4,
            choice5,
            correct_answer,
            area,
            qtype,
            difficulty
        FROM questions
        """
    )
    rows = cur.fetchall()
    conn.close()

    return [QuestionOut(**dict(row)) for row in rows]


@app.post("/api/submit", response_model=SubmitResponse)
async def submit_answers(payload: SubmitRequest):
    """
    학생 답안을 받아서:
    1) 점수 계산
    2) OpenAI로 정성적 피드백 생성
    """
    answers = payload.answers
    total = len(answers)

    if total == 0:
        raise HTTPException(status_code=400, detail="answers 가 비어 있습니다.")

    # --- 1) 점수 계산 ---
    score = 0
    result_for_prompt = []  # LLM 프롬프트에 넣을 요약 정보

    for a in answers:
        # 선택/정답이 None 이면 채점에서 제외
        if a.selected is None or a.correct_answer is None:
            is_correct = False
        else:
            # selected 는 0~4, correct_answer 는 1~5 => +1 해서 비교
            is_correct = (a.selected + 1) == a.correct_answer

        if is_correct:
            score += 1

        result_for_prompt.append(
            {
                "question_id": a.question_id,
                "area": a.area,
                "qtype": a.qtype,
                "difficulty": a.difficulty,
                "selected_index": a.selected,
                "correct_answer": a.correct_answer,
                "user_answer": a.user_answer,
                "is_correct": is_correct,
            }
        )

    # --- 2) OpenAI 프롬프트 생성 ---
    # 필요시 한국어/영어 프롬프트 조정 가능
    system_msg = (
        "너는 한국 중학생을 지도하는 영어 교사야. "
        "학생이 응시한 진단평가 결과를 바탕으로 학습 피드백을 작성해줘. "
        "반드시 JSON 형식으로만 답해야 한다. "
        "키는 summary, strengths, weaknesses, recommendations 네 가지여야 한다."
    )

    user_msg = (
        "다음은 한 학생의 중등 영어 진단평가 결과야.\n\n"
        f"총 문항 수: {total}문항, 맞힌 문항 수: {score}문항.\n\n"
        "각 문항의 결과는 다음 JSON 배열이야.\n"
        "각 항목은 question_id, area(어휘/문법/독해 등), qtype(세부 유형), difficulty(난이도), "
        "selected_index(학생이 선택한 보기 번호 0~4, 선택 안 한 경우 null), "
        "correct_answer(정답 번호 1~5), is_correct(정답 여부) 를 포함한다.\n\n"
        "결과:\n"
        + json.dumps(result_for_prompt, ensure_ascii=False)
        + "\n\n"
        "이 정보를 바탕으로 아래 항목을 모두 한국어로 작성해서 JSON으로 반환해줘.\n"
        "1) summary: 학생의 전체적인 영어 실력과 이번 진단평가 결과 요약 (3~4문장)\n"
        "2) strengths: 학생의 강점(잘하는 영역/유형/학습 습관 등)\n"
        "3) weaknesses: 학생이 어려워한 영역/유형 및 자주 틀린 패턴\n"
        "4) recommendations: 앞으로 2~3주 동안의 구체적인 학습 전략과 활동 제안\n"
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        content = completion.choices[0].message.content or ""
    except Exception as e:
        # OpenAI 호출 실패 시, 기본 피드백 반환
        fallback_feedback = Feedback(
            summary="AI 피드백 생성 중 오류가 발생했습니다. 나중에 다시 시도해 주세요.",
            strengths="점수와 문항별 정오표를 기반으로 강점을 교사가 직접 분석해 주세요.",
            weaknesses="점수와 문항별 정오표를 기반으로 약점을 교사가 직접 분석해 주세요.",
            recommendations="교과서 및 기본 문법/어휘 복습, 틀린 문제 유형 위주로 재학습을 권장합니다.",
        )
        return SubmitResponse(score=score, total=total, feedback=fallback_feedback)

    # --- 3) JSON 파싱 + 안전한 fallback ---
    try:
        data = json.loads(content)
        feedback = Feedback(
            summary=data.get("summary", ""),
            strengths=data.get("strengths", ""),
            weaknesses=data.get("weaknesses", ""),
            recommendations=data.get("recommendations", ""),
        )
    except Exception:
        # 모델이 JSON 형식으로 안 줬을 때 대비
        feedback = Feedback(
            summary=content,
            strengths="",
            weaknesses="",
            recommendations="",
        )

    return SubmitResponse(score=score, total=total, feedback=feedback)


@app.get("/")
def root():
    return {"status": "ok", "message": "HeyEdu backend running"}
