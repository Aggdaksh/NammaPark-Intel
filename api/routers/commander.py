from __future__ import annotations

import re

from fastapi import APIRouter, Depends

from api.dependencies import get_prediction_store
from api.serving import TieredPredictionStore
from api.schemas.prediction import CommanderRequest, CommanderResponse


router = APIRouter(tags=["commander"])


import os
import re
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import get_prediction_store
from api.serving import TieredPredictionStore
from api.schemas.prediction import CommanderRequest, CommanderResponse

# Try importing google.genai, fallback gracefully if not installed
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

router = APIRouter(tags=["commander"])

def _top_cluster_ids(context: dict) -> list[int]:
    return [int(cluster["cluster_id"]) for cluster in context.get("top_clusters", [])[:10]]

@router.post("/commander", response_model=CommanderResponse)
async def ask_commander(request: CommanderRequest, fallback: TieredPredictionStore = Depends(get_prediction_store)) -> dict:
    context = fallback.read("commander_context.json") or {"top_clusters": []}
    top_clusters = context.get("top_clusters", [])
    if not top_clusters:
        return {"response": "No cluster prediction data is available.", "grounded_cluster_ids": [], "source": fallback.last_source}

    ids = _top_cluster_ids(context)
    message = request.user_message.strip()

    if not HAS_GEMINI:
        return {
            "response": "Google GenAI SDK is not installed. Please install it to use the AI Commander. Here is a mocked response based on your query: " + message,
            "grounded_cluster_ids": ids,
            "source": fallback.last_source
        }

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "response": "GEMINI_API_KEY is not configured in the environment.",
            "grounded_cluster_ids": ids,
            "source": fallback.last_source
        }

    # Construct the system prompt
    system_prompt = (
        "You are the NammaPark AI Commander, an expert assistant for Bengaluru Traffic Police. "
        "You help dispatchers analyze parking violations, prioritize enforcement, and understand "
        "the machine learning predictions (Risk, Delay, Anomalies).\n\n"
        "Here is the top-10 cluster context generated from the BPR and LightGBM models:\n"
    )
    for c in top_clusters[:5]: # Include top 5 to save tokens
        drivers = "; ".join(f"{d.get('feature')} ({d.get('shap_contribution_min')} min)" for d in c.get("shap_context", []))
        system_prompt += f"- Cluster {c.get('cluster_id')} near {c.get('police_station')}: {c.get('predicted_delay_min')} min delay, Risk: {c.get('final_risk_0_100')}. Drivers: {drivers}.\n"

    system_prompt += "\nAnswer the user's query clearly, concisely, and cite the data context provided. Do not hallucinate."

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1000,
            ),
        )
        response_text = response.text
    except Exception as e:
        response_text = f"Error calling Gemini API: {str(e)}"

    return {
        "response": response_text,
        "grounded_cluster_ids": ids,
        "source": fallback.last_source
    }

