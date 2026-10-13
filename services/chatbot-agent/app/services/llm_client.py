import httpx
from app.config import settings
from app.services.context_service import fetch_procurement_summary

async def query_llm_with_tools(history: list, user_id: str) -> str:
    url = f"{settings.llm_api_base_url}/api/chat"
    
    # Define our tool
    tools = [{
        "type": "function",
        "function": {
            "name": "get_procurement_summary",
            "description": "Fetches live procurement data including pending approvals, overdue approvals, and open order value.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }]

    messages = [{"role": m.role, "content": m.content} for m in history]
    
    # Inject system prompt
    messages.insert(0, {
        "role": "system", 
        "content": "You are a helpful IT Procurement Assistant. If the user asks about order status or approvals, use the get_procurement_summary tool."
    })

    payload = {"model": settings.llm_model_name, "messages": messages, "stream": False, "tools": tools}

    async with httpx.AsyncClient(timeout=120.0) as client:
        # First call: See if LLM wants to use a tool
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})

        # Check if a tool call was requested
        if "tool_calls" in message and message["tool_calls"]:
            messages.append(message) # Append assistant's request to use tool
            
            for tool in message["tool_calls"]:
                if tool["function"]["name"] == "get_procurement_summary":
                    # Execute the actual Python function
                    result_json = await fetch_procurement_summary(user_id)
                    
                    # Append the tool's result to the messages
                    messages.append({
                        "role": "tool",
                        "content": result_json,
                    })
            
            # Second call: Send the tool result back to LLM to generate natural reply
            payload["messages"] = messages
            final_response = await client.post(url, json=payload)
            final_data = final_response.json()
            return final_data.get("message", {}).get("content", "Error generating response.")
        
        # If no tool was used, just return the standard text reply
        return message.get("content", "I could not generate a response.")