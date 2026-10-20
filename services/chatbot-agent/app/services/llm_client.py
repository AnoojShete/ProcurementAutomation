import httpx
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from shared.auth.middleware import CurrentUser
from app.services import context_service
from app.services import rag_service

async def query_llm_with_tools(history: list, user: CurrentUser, db: AsyncSession) -> str:
    url = f"{settings.llm_api_base_url}/api/chat"
    
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
        },
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "Perform a semantic search over procurement documents (contracts, invoices, POs) to find specific clauses, item pricing, or historical text.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "query": {"type": "string", "description": "The semantic search query, e.g., 'termination clauses for SaaS' or 'laptop pricing'"}
                    }, 
                    "required": ["query"]
                }
            }
        }
    ]

    messages = [{"role": m.role, "content": m.content} for m in history]
    
    messages.insert(0, {
        "role": "system", 
        "content": (
            f"You are the Procurement Assistant AI. The current user is '{user.email}' with role '{user.role}'.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. You must use tools to answer questions.\n"
            "2. NEVER plan multiple steps at once. Call exactly ONE tool, wait for the result, and then call the next tool.\n"
            "3. NEVER invent or guess IDs. If you need a vendor_id, call 'search_vendors' first and wait for the response.\n"
            "4. NEVER write out JSON or numbered lists in your conversational response. Use the native tool calling API.\n"
        )
    })

    async with httpx.AsyncClient(timeout=180.0) as client:
        max_iterations = 5 
        
        for iteration in range(max_iterations):
            payload = {"model": settings.llm_model_name, "messages": messages, "stream": False, "tools": tools}
            
            response = await client.post(url, json=payload)
            response.raise_for_status()
            message = response.json().get("message", {})
            content = message.get("content", "")

            # --- LLM WRANGLER ---
            if ("tool_calls" not in message or not message["tool_calls"]) and '{"name":' in content:
                import re
                matches = re.findall(r'\{"name":\s*"[^"]+",\s*"parameters":\s*\{.*?\}\}', content, re.DOTALL)
                if matches:
                    message["tool_calls"] = []
                    try:
                        clean_json = matches[0].replace('\n', '').replace('\r', '')
                        func_data = json.loads(clean_json)
                        message["tool_calls"].append({"function": func_data})
                    except Exception:
                        pass
                    message["content"] = ""
            # --------------------

            if "tool_calls" not in message or not message["tool_calls"]:
                return content
            
            messages.append(message) 
            
            for tool in message["tool_calls"]:
                name = tool["function"]["name"]
                
                args = tool["function"].get("arguments", tool["function"].get("parameters", {}))
                
                try:
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
                    elif name == "search_documents":
                        # CRITICAL FIX: Pass the user object into the RAG service to enforce authorization
                        result = await rag_service.search_knowledge_base(args.get("query", ""), db, user)
                    else:
                        result = json.dumps({"error": f"Unknown tool: {name}"})
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                
                messages.append({"role": "tool", "content": str(result)})
        
        return "I reached my maximum thinking steps."
