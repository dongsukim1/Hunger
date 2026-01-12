# routes/recommender.py
from fastapi import APIRouter, HTTPException
import uuid
from ..recommendation_engine import load_candidate_restaurants, select_best_question, filter_candidates, select_best_question_ml
from ..utils import is_in_mission_sf
from ..models import RecommendationRequest, AnswerRequest 

router = APIRouter(prefix="/recommend", tags=["recommendations"])

SESSIONS = {} # In-memory sessions: {session_id: {"candidates": [...], "questions_asked": int, "max_questions": int}}

@router.post("/start")
def start_session(request: RecommendationRequest): 
    if not is_in_mission_sf(request.user_latitude, request.user_longitude):
        raise HTTPException(
            status_code=400,
            detail="Demo only available in Mission District, SF. Please adjust your location."
        )
    max_meters = request.max_distance_miles * 1609.34
    candidates = load_candidate_restaurants(request.user_latitude, request.user_longitude, max_meters)
    
    if not candidates:
        raise HTTPException(status_code=404, detail="No restaurants in range")
    
    session_id = str(uuid.uuid4())
    SESSIONS[session_id] = {
        "candidates": candidates,
        "questions_asked": [],
        "max_questions": request.max_questions,
        "list_id": request.list_id,
        "context": "Discovery Session" 
    }
    
    # Hardcoded to use ML-based question selection for now
    # question_id, question_text, options = select_best_question(candidates)
    SESSIONS[session_id]["context"] = "Discovery Session"  # store context in session
    question_id, question_text, options = select_best_question_ml(candidates, SESSIONS[session_id])
    
    return {
        "session_id": session_id,
        "question": {"id": question_id, "text": question_text, "options": options},
        "candidates_count": len(candidates)
    }

@router.post("/answer")
def answer_question(request: AnswerRequest):
    session_id = request.session_id
    answer = request.answer
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = SESSIONS[session_id]
    candidates = session["candidates"]
    questions_asked = session["questions_asked"]
    max_questions = session["max_questions"]
    
    # Get current question to interpret answer currently hardcoded to use ML-based question selection
    # question_id, _, _ = select_best_question(candidates)
    question_id, question_text, options = select_best_question_ml(candidates, session)
    
    # Filter candidates based on answer
    new_candidates = filter_candidates(candidates, question_id, answer)
    # Update session
    session["candidates"] = new_candidates
    session["questions_asked"].append(question_id)
    
    # Check termination conditions
    if len(new_candidates) == 1 or len(questions_asked) + 1 >= max_questions or len(new_candidates) <= 3:
        # Return top recommendations
        results = [
            {
                "id": c["id"], 
                "name": c["name"],
                "cuisine": c["cuisine"],
                "price_tier": c["price_tier"],
                "distance_miles": round(c["distance_m"] / 1609.34, 1)
            }
            for c in new_candidates[:3]
        ]
        # Clean up session
        del SESSIONS[session_id]
        return {"recommendations": results}
    
    # Ask next question defaulted to use ML-based question selection
    # next_q_id, next_q_text, next_options = select_best_question(new_candidates)
    next_q_id, next_q_text, next_options = select_best_question_ml(new_candidates, session)
    return {
        "session_id": session_id,
        "question": {"id": next_q_id, "text": next_q_text, "options": next_options},
        "candidates_count": len(new_candidates)
    }