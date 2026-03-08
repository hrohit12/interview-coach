"""
main.py
FastAPI backend for Interview Coach
Run with: uvicorn main:app --reload
"""

import os
import uuid
import json
import base64
import asyncio
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from resume_parser import parse_uploaded_file
from interview_engine import generate_question, evaluate_answer, generate_final_report
from pdf_report import generate_pdf_report

# ─── App Setup ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
REPORTS_DIR = BASE_DIR / "uploads" / "reports"
TEMP_DIR = BASE_DIR / "uploads" / "temp_audio"
UPLOAD_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# ─── Whisper model (lazy-loaded on first STT request) ─────────────────────────
_whisper_model = None

def _get_whisper():
    """Load faster-whisper model once and reuse."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        # 'base' balances speed vs accuracy well on CPU
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Interview Coach API",
    description="AI-powered interview practice platform by hrohit12",
    version="1.0.0",
)

# Allow Cross-Origin Requests from the separate Netlify frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for easy Netlify deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ─── In-Memory Session Store ──────────────────────────────────────────────────
# Maps session_id -> session data dict
sessions: dict = {}


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class GenerateQuestionRequest(BaseModel):
    session_id: str
    api_type: str
    api_key: str
    model: str
    candidate_name: str
    qualification: str
    topic: str
    difficulty: str
    question_number: int = 1


class EvaluateAnswerRequest(BaseModel):
    session_id: str
    api_type: str
    api_key: str
    model: str
    candidate_name: str
    topic: str
    difficulty: str
    question: str
    answer: str


class FinalReportRequest(BaseModel):
    session_id: str
    api_type: str
    api_key: str
    model: str
    candidate_name: str
    qualification: str
    topic: str
    difficulty: str


class ValidateAPIRequest(BaseModel):
    api_type: str
    api_key: str
    model: str


# ─── HTML Page Routes ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    return templates.TemplateResponse("setup.html", {"request": request})


@app.get("/interview", response_class=HTMLResponse)
async def interview(request: Request):
    return templates.TemplateResponse("interview.html", {"request": request})


@app.get("/report", response_class=HTMLResponse)
async def report(request: Request):
    return templates.TemplateResponse("report.html", {"request": request})


# ─── API Endpoints ────────────────────────────────────────────────────────────

@app.post("/speech-to-text")
async def speech_to_text(
    audio: UploadFile = File(...),
    language: str = Form("en"),
):
    """
    Receive an audio blob from the browser (MediaRecorder),
    transcribe it with faster-whisper, and return the transcript.
    """
    import tempfile
    import subprocess

    # Save raw audio to a temp file
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    tmp_path = str(TEMP_DIR / f"stt_{uuid.uuid4().hex}{suffix}")

    try:
        content = await audio.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty audio file received.")

        with open(tmp_path, "wb") as f:
            f.write(content)

        # Convert to WAV if needed (ffmpeg handles webm/ogg/mp4/etc.)
        wav_path = tmp_path.replace(suffix, ".wav")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path,
                 "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                capture_output=True, timeout=30
            )
            audio_path = wav_path if os.path.exists(wav_path) else tmp_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # ffmpeg not available — feed raw file directly to Whisper
            audio_path = tmp_path

        # Transcribe
        model = _get_whisper()
        segments, info = model.transcribe(
            audio_path,
            language=language if language != "auto" else None,
            beam_size=5,
            vad_filter=True,          # skip silent segments
            vad_parameters={"min_silence_duration_ms": 500},
        )
        transcript = " ".join(seg.text.strip() for seg in segments).strip()

        return {"status": "success", "transcript": transcript, "language": info.language}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
    finally:
        # Clean up temp files
        for p in [tmp_path, wav_path if 'wav_path' in dir() else ""]:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


@app.post("/validate-api")
async def validate_api(req: ValidateAPIRequest):
    """Quick validation that the API key works by generating a short test response."""
    try:
        from interview_engine import _call_ai
        response = _call_ai(
            req.api_type, req.api_key, req.model,
            "You are a test assistant.",
            "Reply with exactly: OK"
        )
        return {"status": "success", "message": "API connection successful", "response": response[:50]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"API validation failed: {str(e)}")


@app.post("/upload-file")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form("resume"),  # "resume" or "notes"
    session_id: str = Form(None),
):
    """Upload a resume or notes file and extract its text content."""
    if not session_id:
        session_id = str(uuid.uuid4())

    # Validate file type
    allowed_extensions = {".pdf", ".txt", ".md"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"File type {ext} not supported. Use PDF, TXT, or MD.")

    # Save file
    safe_name = f"{session_id}_{file_type}{ext}"
    file_path = UPLOAD_DIR / safe_name

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Parse text
    extracted_text = parse_uploaded_file(str(file_path))

    # Store in session
    if session_id not in sessions:
        sessions[session_id] = {}

    sessions[session_id][f"{file_type}_text"] = extracted_text
    sessions[session_id][f"{file_type}_filename"] = file.filename

    return {
        "status": "success",
        "session_id": session_id,
        "filename": file.filename,
        "file_type": file_type,
        "text_length": len(extracted_text),
        "preview": extracted_text[:300] + "..." if len(extracted_text) > 300 else extracted_text,
    }


@app.post("/generate-question")
async def api_generate_question(req: GenerateQuestionRequest):
    """Generate the next interview question based on session context."""
    try:
        # Get session data
        session = sessions.get(req.session_id, {})
        resume_text = session.get("resume_text")
        notes_text = session.get("notes_text")
        conversation_history = session.get("conversation_history", [])

        question = generate_question(
            api_type=req.api_type,
            api_key=req.api_key,
            model=req.model,
            topic=req.topic,
            difficulty=req.difficulty,
            candidate_name=req.candidate_name,
            qualification=req.qualification,
            resume_text=resume_text,
            notes_text=notes_text,
            question_number=req.question_number,
            conversation_history=conversation_history,
        )

        # Store current question in session
        if req.session_id not in sessions:
            sessions[req.session_id] = {}
        sessions[req.session_id]["current_question"] = question

        return {"status": "success", "question": question, "question_number": req.question_number}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate question: {str(e)}")


@app.post("/evaluate-answer")
async def api_evaluate_answer(req: EvaluateAnswerRequest):
    """Evaluate a candidate's answer and store in session history."""
    try:
        evaluation = evaluate_answer(
            api_type=req.api_type,
            api_key=req.api_key,
            model=req.model,
            topic=req.topic,
            difficulty=req.difficulty,
            question=req.question,
            answer=req.answer,
            candidate_name=req.candidate_name,
        )

        # Store in session history
        if req.session_id not in sessions:
            sessions[req.session_id] = {}

        if "conversation_history" not in sessions[req.session_id]:
            sessions[req.session_id]["conversation_history"] = []
        if "evaluations" not in sessions[req.session_id]:
            sessions[req.session_id]["evaluations"] = []

        sessions[req.session_id]["conversation_history"].append({
            "question": req.question,
            "answer": req.answer,
            "feedback": evaluation.get("feedback", ""),
        })
        sessions[req.session_id]["evaluations"].append(evaluation)

        return {"status": "success", "evaluation": evaluation}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to evaluate answer: {str(e)}")


@app.post("/finish-interview")
async def api_finish_interview(req: FinalReportRequest):
    """Generate the final report after the interview session ends."""
    try:
        session = sessions.get(req.session_id, {})
        conversation_history = session.get("conversation_history", [])
        evaluations = session.get("evaluations", [])

        if not conversation_history:
            raise HTTPException(status_code=400, detail="No interview data found for this session.")

        report_data = generate_final_report(
            api_type=req.api_type,
            api_key=req.api_key,
            model=req.model,
            candidate_name=req.candidate_name,
            qualification=req.qualification,
            topic=req.topic,
            difficulty=req.difficulty,
            conversation_history=conversation_history,
            evaluations=evaluations,
        )

        # Store report in session
        sessions[req.session_id]["report"] = report_data

        return {"status": "success", "report": report_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


@app.get("/get-report/{session_id}")
async def get_report(session_id: str):
    """Retrieve the final report for a session."""
    session = sessions.get(session_id, {})
    report_data = session.get("report")

    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found for this session.")

    return {"status": "success", "report": report_data}


@app.post("/download-report/{session_id}")
async def download_report(session_id: str):
    """Generate and download the PDF report for a session."""
    session = sessions.get(session_id, {})
    report_data = session.get("report")

    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found. Please finish the interview first.")

    # Generate PDF
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_filename = f"interview_report_{session_id[:8]}_{timestamp}.pdf"
    pdf_path = str(REPORTS_DIR / pdf_filename)

    try:
        generate_pdf_report(report_data, pdf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    return FileResponse(
        path=pdf_path,
        filename=f"InterviewCoach_Report_{report_data.get('candidate_name', 'Candidate').replace(' ', '_')}.pdf",
        media_type="application/pdf",
    )


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session data (for debugging)."""
    session = sessions.get(session_id, {})
    return {
        "session_id": session_id,
        "has_resume": "resume_text" in session,
        "has_notes": "notes_text" in session,
        "question_count": len(session.get("conversation_history", [])),
        "has_report": "report" in session,
    }


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a session."""
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "success", "message": "Session cleared"}



# ─── Edge TTS helper ──────────────────────────────────────────────────────────

async def _tts_generate(text: str, voice: str = "en-US-JennyNeural") -> bytes:
    """Generate MP3 audio bytes using edge-tts. Returns empty bytes on failure."""
    if not text.strip():
        return b""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text.strip(), voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)
    except Exception as e:
        print(f"[TTS] edge-tts error: {e}")
        return b""


def _transcribe_file(path: str, lang: str = "en") -> str:
    """Synchronous faster-whisper transcription (run in executor)."""
    wav_path = path + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, timeout=30
        )
        audio_path = wav_path if os.path.exists(wav_path) else path
    except Exception:
        audio_path = path
    try:
        model = _get_whisper()
        segments, _ = model.transcribe(
            audio_path, language=lang, beam_size=5,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300}
        )
        return " ".join(s.text.strip() for s in segments).strip()
    finally:
        try:
            if os.path.exists(wav_path): os.remove(wav_path)
        except Exception:
            pass


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "app": "Interview Coach", "made_by": "hrohit12"}


# ─── WebSocket Real-Time Interview ────────────────────────────────────────────

@app.websocket("/ws-interview")
async def websocket_interview(websocket: WebSocket):
    await websocket.accept()
    config: dict = {}
    audio_buffer = bytearray()
    question_number = 0
    MAX_QUESTIONS = 10
    loop = asyncio.get_event_loop()

    def _get_voice(cfg: dict) -> str:
        voice = cfg.get("voice", "en-US-JennyNeural")
        if cfg.get("language", "english").lower() == "hindi":
            return "hi-IN-MadhurNeural" if "Guy" in voice else "hi-IN-SwaraNeural"
        return voice

    async def _send(data: dict):
        await websocket.send_json(data)

    async def _ask_question(qnum: int):
        nonlocal question_number
        question_number = qnum
        await _send({"type": "status", "state": "thinking"})

        session = sessions.get(config.get("session_id", ""), {})
        history = session.get("conversation_history", [])

        question = await loop.run_in_executor(
            None, lambda: generate_question(
                api_type=config["api_type"], api_key=config["api_key"],
                model=config["model"], topic=config["topic"],
                difficulty=config["difficulty"], candidate_name=config["name"],
                qualification=config.get("qualification", ""),
                question_number=qnum, conversation_history=history,
                resume_text=session.get("resume_text"),
                notes_text=session.get("notes_text"),
                language=config.get("language", "english"),
            )
        )
        sid = config["session_id"]
        sessions.setdefault(sid, {})["current_question"] = question

        audio_bytes = await _tts_generate(question, _get_voice(config))
        await _send({
            "type": "question",
            "text": question,
            "audio_b64": base64.b64encode(audio_bytes).decode() if audio_bytes else "",
            "question_number": qnum,
            "max_questions": MAX_QUESTIONS,
        })
        await _send({"type": "status", "state": "listening"})

    try:
        while True:
            msg = await websocket.receive()

            if "bytes" in msg and msg["bytes"]:
                audio_buffer.extend(msg["bytes"])

            elif "text" in msg:
                data = json.loads(msg["text"])
                msg_type = data.get("type")

                if msg_type == "init":
                    config = data
                    sid = config.get("session_id") or str(uuid.uuid4())
                    config["session_id"] = sid
                    sessions.setdefault(sid, {})
                    audio_buffer.clear()
                    await _ask_question(1)

                elif msg_type == "end_speech":
                    if not audio_buffer:
                        await _send({"type": "status", "state": "listening"})
                        continue
                    buf_copy = bytes(audio_buffer)
                    audio_buffer.clear()
                    await _send({"type": "status", "state": "thinking"})

                    tmp = str(TEMP_DIR / f"ws_{uuid.uuid4().hex}.webm")
                    with open(tmp, "wb") as f:
                        f.write(buf_copy)
                    try:
                        lang_code = "hi" if config.get("language", "english").lower() == "hindi" else "en"
                        transcript = await loop.run_in_executor(None, _transcribe_file, tmp, lang_code)
                    finally:
                        try: os.remove(tmp)
                        except Exception: pass

                    if not transcript.strip():
                        await _send({"type": "status", "state": "listening"})
                        continue

                    await _send({"type": "transcript", "text": transcript})

                    sid = config["session_id"]
                    current_q = sessions.get(sid, {}).get("current_question", "")
                    evaluation = await loop.run_in_executor(
                        None, lambda: evaluate_answer(
                            api_type=config["api_type"], api_key=config["api_key"],
                            model=config["model"], topic=config["topic"],
                            difficulty=config["difficulty"], question=current_q,
                            answer=transcript, candidate_name=config["name"],
                            language=config.get("language", "english"),
                        )
                    )

                    sess = sessions.setdefault(sid, {})
                    sess.setdefault("conversation_history", []).append({
                        "question": current_q, "answer": transcript,
                        "feedback": evaluation.get("feedback", ""),
                    })
                    sess.setdefault("evaluations", []).append(evaluation)

                    fb_text = evaluation.get("feedback", "")
                    fb_audio = await _tts_generate(fb_text, _get_voice(config))
                    await _send({
                        "type": "feedback",
                        "text": fb_text,
                        "audio_b64": base64.b64encode(fb_audio).decode() if fb_audio else "",
                        "score": evaluation.get("score", 5),
                        "strengths": evaluation.get("strengths", []),
                        "improvements": evaluation.get("improvements", []),
                        "follow_up": evaluation.get("follow_up", ""),
                    })

                    next_q = question_number + 1
                    if next_q > MAX_QUESTIONS:
                        history = sess.get("conversation_history", [])
                        evals = sess.get("evaluations", [])
                         # Format elapsed time as MM:SS
                        elapsed_sec = int(time.time() - sess.get("start_time", time.time()))
                        duration_str = f"{elapsed_sec // 60:02d}:{elapsed_sec % 60:02d}"

                        if history:
                            report = await loop.run_in_executor(
                                None, lambda: generate_final_report(
                                    api_type=config["api_type"], api_key=config["api_key"],
                                    model=config["model"], candidate_name=config["name"],
                                    qualification=config.get("qualification", ""),
                                    topic=config["topic"], difficulty=config["difficulty"],
                                    conversation_history=history, evaluations=evals,
                                    duration=duration_str,
                                    language=config.get("language", "english"),
                                )
                            )
                            sess["report"] = report
                        await _send({"type": "report_ready"})
                    else:
                        await asyncio.sleep(0.4)
                        await _ask_question(next_q)

                elif msg_type == "finish":
                    sid = config.get("session_id", "")
                    sess = sessions.get(sid, {})
                    history = sess.get("conversation_history", [])
                    evals = sess.get("evaluations", [])
                    if history and "report" not in sess:
                        report = await loop.run_in_executor(
                            None, lambda: generate_final_report(
                                api_type=config["api_type"], api_key=config["api_key"],
                                model=config["model"], candidate_name=config["name"],
                                qualification=config.get("qualification", ""),
                                topic=config["topic"], difficulty=config["difficulty"],
                                conversation_history=history, evaluations=evals,
                                language=config.get("language", "english"),
                            )
                        )
                        sess["report"] = report
                    await _send({"type": "report_ready"})
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await _send({"type": "error", "message": str(e)})
        except Exception:
            pass
