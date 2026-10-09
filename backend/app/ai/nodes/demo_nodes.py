from ..schemas import AIState, ContentPlanOutput
from ..providers.factory import get_configured_provider as get_provider

async def analyze_input(state: AIState) -> AIState:
    provider = get_provider()
    prompt = f"Analyze the following input and extract the primary intent and keywords: {state['input_text']}"
    
    # In a real app we might use structured output for this too, but we use text for demo
    response = await provider.generate_text(prompt)
    
    return {
        **state,
        "intent": "Content Planning",
        "keywords": ["AI", "Coding", "Future"]
    }

async def generate_result(state: AIState) -> AIState:
    provider = get_provider()
    prompt = f"Based on the intent '{state.get('intent')}' and keywords {state.get('keywords')}, create a content plan for: {state['input_text']}"
    
    try:
        result: ContentPlanOutput = await provider.generate_structured(prompt, ContentPlanOutput)
        return {
            **state,
            "structured_output": result.model_dump(),
            "error": None
        }
    except Exception as e:
        return {
            **state,
            "error": str(e),
            "retries": state.get("retries", 0) + 1
        }

async def validate_result(state: AIState) -> AIState:
    if state.get("error"):
        return state
        
    output = state.get("structured_output")
    if not output:
        return {**state, "error": "No output generated"}
        
    try:
        # Validate again using Pydantic just to be safe
        ContentPlanOutput(**output)
        return state
    except Exception as e:
        return {**state, "error": f"Validation failed: {str(e)}"}
