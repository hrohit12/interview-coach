"""
interview_engine.py
Handles AI-powered question generation and answer evaluation.
Supports Google Gemini and Groq APIs.
"""

import json
import re
from typing import Optional


# ─── Gemini ──────────────────────────────────────────────────────────────────

def _gemini_chat(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
    )
    response = m.generate_content(user_message)
    return response.text


# ─── Groq ─────────────────────────────────────────────────────────────────────

def _groq_chat(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=1024,
    )
    return completion.choices[0].message.content


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def _call_ai(api_type: str, api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    if api_type.lower() == "gemini":
        return _gemini_chat(api_key, model, system_prompt, user_message)
    elif api_type.lower() == "groq":
        return _groq_chat(api_key, model, system_prompt, user_message)
    else:
        raise ValueError(f"Unsupported API type: {api_type}")


# ─── Question Generation ───────────────────────────────────────────────────────

def generate_question(
    api_type: str,
    api_key: str,
    model: str,
    topic: str,
    difficulty: str,
    candidate_name: str,
    qualification: str,
    resume_text: Optional[str] = None,
    notes_text: Optional[str] = None,
    question_number: int = 1,
    conversation_history: Optional[list] = None,
    language: str = "english",
) -> str:
    """
    Generate an interview question based on context.
    Returns plain text question string.
    """

    context_parts = []
    if resume_text:
        context_parts.append(f"Candidate Resume:\n{resume_text[:2000]}")
    if notes_text:
        context_parts.append(f"Study Notes:\n{notes_text[:1000]}")
    context = "\n\n".join(context_parts)

    system_prompt = f"""You are an expert technical interviewer conducting a {difficulty} level interview.
Interview Language: {language.capitalize()}
Candidate: {candidate_name} | Qualification: {qualification}
Interview Topic: {topic}
{f"Context about candidate: {context}" if context else ""}

Your role:
- The interview must be conducted STRICTLY in {language.capitalize()}. All your questions and text must be in {language.capitalize()}.
- Ask one clear, relevant interview question at a time
- Match difficulty: beginner (foundational), intermediate (applied), advanced (expert/design)
- Be professional, encouraging, and specific to the topic
- Vary question types: conceptual, scenario-based, behavioral, problem-solving
- Do NOT repeat questions already asked
- Return ONLY the question text, nothing else"""

    history_str = ""
    if conversation_history:
        for item in conversation_history[-6:]:  # Last 3 Q&A pairs
            history_str += f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}\n\n"

    history_prefix = ("Previous Q&A:\n" + history_str) if history_str else ""
    user_message = f"""This is question #{question_number} in the interview.
{history_prefix}
Generate the next appropriate interview question."""

    return _call_ai(api_type, api_key, model, system_prompt, user_message).strip()


# ─── Answer Evaluation ────────────────────────────────────────────────────────

def evaluate_answer(
    api_type: str,
    api_key: str,
    model: str,
    topic: str,
    difficulty: str,
    question: str,
    answer: str,
    candidate_name: str,
    language: str = "english",
) -> dict:
    """
    Evaluate a candidate's answer.
    Returns dict with: score, feedback, follow_up (optional)
    """

    system_prompt = f"""You are an expert technical interviewer evaluating a {difficulty} level answer.
Topic: {topic} | Candidate: {candidate_name}
Interview Language: {language.capitalize()}

Evaluate the answer and respond ONLY with valid JSON in this exact format.
IMPORTANT: All text and feedback values MUST be written strictly in {language.capitalize()}:
{{
  "score": <0-10 integer>,
  "technical_accuracy": <0-10 integer>,
  "communication_clarity": <0-10 integer>,
  "confidence_indicator": <0-10 integer>,
  "feedback": "<2-3 sentences of constructive feedback in {language.capitalize()}>",
  "strengths": ["<strength1>", "<strength2>"],
  "improvements": ["<improvement1>", "<improvement2>"],
  "follow_up": "<optional follow-up question or empty string>"
}}"""

    user_message = f"""Question: {question}
Candidate's Answer: {answer}

Evaluate this answer."""

    raw = _call_ai(api_type, api_key, model, system_prompt, user_message).strip()

    # Extract JSON from response
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback
    return {
        "score": 5,
        "technical_accuracy": 5,
        "communication_clarity": 5,
        "confidence_indicator": 5,
        "feedback": raw[:300] if raw else "Unable to evaluate answer.",
        "strengths": ["Attempted the question"],
        "improvements": ["Provide more detail in your answer"],
        "follow_up": ""
    }


# ─── Final Report Generation ──────────────────────────────────────────────────

def generate_final_report(
    api_type: str,
    api_key: str,
    model: str,
    candidate_name: str,
    qualification: str,
    topic: str,
    difficulty: str,
    conversation_history: list,
    evaluations: list,
    duration: str = "N/A",
    language: str = "english",
) -> dict:
    """
    Generate a comprehensive final interview report.
    Returns dict with all report fields.
    """

    # Aggregate scores
    if evaluations:
        avg_technical = round(sum(e.get("technical_accuracy", 5) for e in evaluations) / len(evaluations), 1)
        avg_communication = round(sum(e.get("communication_clarity", 5) for e in evaluations) / len(evaluations), 1)
        avg_confidence = round(sum(e.get("confidence_indicator", 5) for e in evaluations) / len(evaluations), 1)
        avg_overall = round(sum(e.get("score", 5) for e in evaluations) / len(evaluations), 1)
        all_strengths = [s for e in evaluations for s in e.get("strengths", [])]
        all_improvements = [i for e in evaluations for i in e.get("improvements", [])]
    else:
        avg_technical = avg_communication = avg_confidence = avg_overall = 5.0
        all_strengths = []
        all_improvements = []

    system_prompt = f"""You are an expert interview coach generating a final interview report.
Candidate: {candidate_name} | Qualification: {qualification}
Topic: {topic} | Difficulty: {difficulty.capitalize()}
Language: {language.capitalize()}

Based on the interview session, generate a concise final summary report.
Respond ONLY with valid JSON in this exact format. All text strings MUST be in {language.capitalize()}:
{{
  "overall_summary": "<2-3 sentence overall assessment>",
  "top_strengths": ["<strength1>", "<strength2>", "<strength3>"],
  "key_improvements": ["<improvement1>", "<improvement2>", "<improvement3>"],
  "recommendation": "<hire/consider/needs work>",
  "recommendation_note": "<1-2 sentences explaining recommendation>"
}}"""

    # Summarize conversation
    qa_summary = ""
    for i, item in enumerate(conversation_history[:10], 1):
        qa_summary += f"Q{i}: {item.get('question', '')[:100]}\nA{i}: {item.get('answer', '')[:150]}\n\n"

    user_message = f"""Interview Q&A Summary:
{qa_summary}

Aggregate Scores:
- Technical: {avg_technical}/10
- Communication: {avg_communication}/10
- Confidence: {avg_confidence}/10

Common Strengths: {', '.join(all_strengths[:5])}
Common Improvements: {', '.join(all_improvements[:5])}

Generate the final report summary."""

    raw = _call_ai(api_type, api_key, model, system_prompt, user_message).strip()

    json_match = re.search(r'\{[\s\S]*\}', raw)
    ai_summary = {}
    if json_match:
        try:
            ai_summary = json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return {
        "candidate_name": candidate_name,
        "qualification": qualification,
        "topic": topic,
        "difficulty": difficulty.capitalize(),
        "total_questions": len(conversation_history),
        "duration": duration,
        "technical_score": avg_technical,
        "communication_score": avg_communication,
        "confidence_score": avg_confidence,
        "overall_score": avg_overall,
        "overall_summary": ai_summary.get("overall_summary", "Interview completed successfully."),
        "strengths": ai_summary.get("top_strengths", list(set(all_strengths))[:3]),
        "improvements": ai_summary.get("key_improvements", list(set(all_improvements))[:3]),
        "recommendation": ai_summary.get("recommendation", "consider"),
        "recommendation_note": ai_summary.get("recommendation_note", ""),
        "conversation_history": conversation_history,
    }
