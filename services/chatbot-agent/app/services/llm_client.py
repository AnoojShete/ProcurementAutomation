import httpx
import json
from app.config import settings
from shared.auth.middleware import CurrentUser
from app.services import context_service

async def query_llm_with_tools(history: list, user: CurrentUser) -> str:
    url = f"{settings.llm_api_base_url}/api/chat"
    
    # Simplified schemas: Removed empty parameters and required arrays
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_procurement_summary",
                "description": "Fetches high-level executive procurement metrics including pending approvals, count of orders, and open order value."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_my_requests",
                "description": "Lists the latest purchase requests. Requesters see their own; staff see company-wide requests."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_purchase_requests",
                "description": "Searches purchase requests by status (e.g. 'pending', 'approved', 'rejected') or minimum dollar amount.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Filter by status: pending, approved, or rejected"},
                        "amount_min": {"type": "number", "description": "Minimum request amount"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_license_anomaly_summary",
                "description": "Returns counts of SaaS licenses by anomaly status and potential annual savings."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_vendors",
                "description": "Searches for vendors by company name to find their vendor ID and status.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Vendor name or part of name"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_vendor_risk",
                "description": "Fetches the risk score, risk band (low, medium, high), and top risk factors for a specific vendor ID.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "vendor_id": {"type": "string", "description": "The exact UUID of the vendor"}
                    }, 
                    "required": ["vendor_id"]
                }
            }
        }
    ]

    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.insert(0, {
        "role": "system", 
        "content": (
            f"You are the Procurement Assistant AI. The current user is '{user.email}' with role '{user.role}'.\n"
            "Guidelines:\n"
            "- If a vendor name is mentioned without an ID, call search_vendors first to get the vendor_id.\n"
            "- If an API returns HTTP 403 Forbidden, politely explain that the user's role does not permit viewing that data.\n"
            "- Always format results clearly with markdown bullet points and dollar values where appropriate."
        )
    })

    payload = {"model": settings.llm_model_name, "messages": messages, "stream": False, "tools": tools}

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})

        if "tool_calls" in message and message["tool_calls"]:
            messages.append(message)
            
            for tool in message["tool_calls"]:
                name = tool["function"]["name"]
                args = tool["function"].get("arguments", {})
                
                if name == "get_procurement_summary":
                    result = await context_service.fetch_procurement_summary(user)
                elif name == "list_my_requests":
                    result = await context_service.fetch_my_requests(user)
                elif name == "search_purchase_requests":
                    result = await context_service.search_purchase_requests(user, status=args.get("status"), amount_min=args.get("amount_min"))
                elif name == "get_license_anomaly_summary":
                    result = await context_service.fetch_license_anomaly_summary(user)
                elif name == "search_vendors":
                    result = await context_service.search_vendors(user, query=args.get("query", ""))
                elif name == "get_vendor_risk":
                    result = await context_service.fetch_vendor_risk(user, args.get("vendor_id", ""))
                else:
                    result = json.dumps({"error": f"Unknown tool: {name}"})
                
                messages.append({"role": "tool", "content": result})
            
            payload["messages"] = messages
            final_response = await client.post(url, json=payload)
            final_data = final_response.json()
            return final_data.get("message", {}).get("content", "Error generating response.")
        
        return message.get("content", "I could not generate a response.")
