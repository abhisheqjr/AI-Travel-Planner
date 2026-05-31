import os
import json
import time
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from groq import Groq

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(32)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ---------------------------------------------
# TERMINAL LOGGER
# ---------------------------------------------
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def log(level: str, msg: str, colour: str = C.WHITE) -> None:
    icons = {
        "INFO":  f"{C.CYAN}[i]{C.RESET}",
        "OK":    f"{C.GREEN}[+]{C.RESET}",
        "TOOL":  f"{C.MAGENTA}[T]{C.RESET}",
        "API":   f"{C.BLUE}[W]{C.RESET}",
        "WARN":  f"{C.YELLOW}[!]{C.RESET}",
        "ERROR": f"{C.RED}[X]{C.RESET}",
        "PHASE": f"{C.YELLOW}[>]{C.RESET}",
        "AGENT": f"{C.MAGENTA}[A]{C.RESET}",
        "REQ":   f"{C.CYAN}[R]{C.RESET}",
        "DONE":  f"{C.GREEN}[*]{C.RESET}",
    }
    icon = icons.get(level, "[-]")
    label = f"{colour}{C.BOLD}[{level:5s}]{C.RESET}"
    print(f"{ts()} {icon} {label} {colour}{msg}{C.RESET}", flush=True)

# ---------------------------------------------
# REAL-TIME SERPAPI TOOL IMPLEMENTATIONS
# ---------------------------------------------
def serpapi_search(params: dict) -> dict:
    if not SERPAPI_API_KEY or SERPAPI_API_KEY.startswith("your_serpapi"):
        raise ValueError("SERPAPI_API_KEY is not configured.")
    engine = params.get("engine", "?")
    query  = params.get("q", "?")
    log("API", f"SerpAPI [{engine}] -> \"{query}\"", C.BLUE)
    params["api_key"] = SERPAPI_API_KEY
    resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()

_IATA_CACHE = {}

def _resolve_iata(city: str) -> str | None:
    key = city.lower().strip()
    if len(key) == 3 and key.isalpha():
        return key.upper()
    if key in _IATA_CACHE:
        return _IATA_CACHE[key]
    try:
        import re
        params = {
            "engine": "google",
            "q": f"major airport IATA code for {city}",
            "api_key": SERPAPI_API_KEY
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            ans = data.get("answer_box", {}).get("answer", "")
            if ans and len(ans) == 3 and ans.isalpha():
                code = ans.upper()
                _IATA_CACHE[key] = code
                return code
            snippets = " ".join([x.get("snippet", "") for x in data.get("organic_results", [])])
            m = re.search(r'(?i)\bIATA[^\w]*([A-Z]{3})\b', snippets)
            if m:
                code = m.group(1).upper()
                _IATA_CACHE[key] = code
                return code
        return None
    except Exception as e:
        log("WARN", f"IATA resolution failed for '{city}': {e}", C.YELLOW)
        return None

@tool
def tool_check_route_feasibility(origin: str, destination: str) -> dict:
    """Checks the overall feasibility and which transport modes are physically available between two locations."""
    log("TOOL", f"check_route_feasibility -> '{origin}' to '{destination}'", C.MAGENTA)
    flights_available = False
    trains_available = False
    buses_available = False
    ferry_available = False
    
    dep_iata = _resolve_iata(origin)
    arr_iata = _resolve_iata(destination)
    if dep_iata and arr_iata:
        flights_available = True

    try:
        drive_params = {
            "engine": "google_maps_directions",
            "start_addr": origin,
            "end_addr": destination,
            "travel_mode": "0",
            "api_key": SERPAPI_API_KEY
        }
        drive_resp = requests.get("https://serpapi.com/search", params=drive_params, timeout=5).json()
        if not drive_resp.get("error") and drive_resp.get("directions"):
            buses_available = True

        transit_params = {
            "engine": "google_maps_directions",
            "start_addr": origin,
            "end_addr": destination,
            "travel_mode": "3",
            "api_key": SERPAPI_API_KEY
        }
        transit_resp = requests.get("https://serpapi.com/search", params=transit_params, timeout=5).json()
        if not transit_resp.get("error") and transit_resp.get("directions"):
            trains_available = True
            directions = transit_resp.get("directions", [])
            for trip in directions:
                for step in trip.get("trips", [{}])[0].get("details", []):
                    vehicle = step.get("transit_details", {}).get("vehicle", {}).get("type", "").lower()
                    if "ferry" in vehicle or "boat" in vehicle or "ship" in vehicle:
                        ferry_available = True
    except Exception as e:
        log("WARN", f"Maps routing failed: {e}", C.YELLOW)

    summary = []
    if flights_available: summary.append("Flights are possible.")
    if trains_available: summary.append("Trains/Rail transit are possible.")
    if buses_available: summary.append("Road/Bus travel is possible.")
    if ferry_available: summary.append("Ferry/Water travel is possible.")
    if not summary: summary.append("No standard routes found.")

    return {
        "flights_available": flights_available,
        "trains_available": trains_available,
        "buses_available": buses_available,
        "ferry_available": ferry_available,
        "summary": " ".join(summary)
    }

def _fetch_flights_serpapi(dep_code: str, arr_code: str, date: str) -> list:
    results = []
    if not dep_code or not arr_code or dep_code == arr_code:
        return results
    base_params = {
        "engine": "google_flights",
        "departure_id": dep_code,
        "arrival_id":   arr_code,
        "outbound_date": date,
        "type": "2",
        "currency": "USD",
        "hl": "en",
        "gl": "us",
    }
    try:
        flight_data = serpapi_search(base_params)
        candidates = flight_data.get("best_flights", []) or flight_data.get("other_flights", [])
        for f in candidates[:3]:
            legs = f.get("flights", [])
            if not legs: continue
            airline = legs[0].get("airline", "Unknown")
            price = f.get("price", "N/A")
            results.append({
                "airline": airline,
                "price": f"${price}" if isinstance(price, (int, float)) else str(price),
                "departure": legs[0].get("departure_airport", {}).get("time", ""),
                "arrival": legs[-1].get("arrival_airport", {}).get("time", "")
            })
    except Exception as e:
        log("WARN", f"Flights call failed: {e}", C.YELLOW)
    return results

@tool
def tool_fetch_transport_options(
    origin: str,
    destination: str,
    travel_date: str = "",
    return_date: str = "",
    trains_available: bool = True,
    buses_available: bool = True,
) -> dict:
    """Fetch real-time transport options using SerpAPI."""
    dep_code = _resolve_iata(origin)
    arr_code = _resolve_iata(destination)
    today = datetime.now()
    outbound_date = travel_date or (today + timedelta(days=30)).strftime("%Y-%m-%d")

    air_out = []
    if dep_code and arr_code:
        air_out = _fetch_flights_serpapi(dep_code, arr_code, outbound_date)

    rail_results = []
    if trains_available:
        rail_results.append({
            "name": f"Train: {origin} to {destination}",
            "duration": "Check local rail portal",
            "price": "Varies by class"
        })

    road_results = []
    if buses_available:
        road_results.append({
            "type": "Bus / Cab",
            "duration": "Check local operators",
            "price": "Varies"
        })

    return {
        "air": air_out,
        "rail": rail_results,
        "road": road_results
    }

@tool
def tool_fetch_accommodations(location: str, budget: str, check_in: str = "", check_out: str = "") -> dict:
    """Fetches real-time hotel and accommodation options from Google Hotels via SerpAPI."""
    today = datetime.now()
    params = {
        "engine": "google_hotels",
        "q": f"hotels in {location}",
        "check_in_date": check_in or (today + timedelta(days=30)).strftime("%Y-%m-%d"),
        "check_out_date": check_out or (today + timedelta(days=35)).strftime("%Y-%m-%d"),
        "currency": "USD",
    }
    data = serpapi_search(params)
    properties = data.get("properties", []) or data.get("hotels", [])
    results = []
    for h in properties[:4]:
        name = h.get("name") or h.get("title", "")
        if not name: continue
        price_info = h.get("rate_per_night") or h.get("prices", [{}])[0] if h.get("prices") else {}
        price = price_info.get("lowest") or price_info.get("rate") or "N/A"
        results.append({
            "name": name,
            "location": h.get("neighborhood") or location,
            "price": str(price),
            "rating": str(h.get("overall_rating") or "N/A"),
            "amenities": (h.get("amenities", [])[:3])
        })
    return {"hotels": results, "location": location, "budget": budget}

@tool
def tool_fetch_restaurants(location: str, cuisine_preferences: str = "") -> dict:
    """Fetches top-rated restaurants, cafes, and dining options via Google Maps SerpAPI."""
    query = f"best restaurants {cuisine_preferences} in {location}".strip()
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
    }
    data = serpapi_search(params)
    places = data.get("local_results", [])
    results = []
    for r in places[:4]:
        name = r.get("title") or r.get("name", "")
        if not name: continue
        results.append({
            "restaurant": name,
            "rating": str(r.get("rating", "N/A")),
            "type": r.get("type", "Restaurant"),
            "address": r.get("address", location),
            "description": r.get("description") or r.get("snippet", "")
        })
    return {"restaurants": results, "location": location}

@tool
def tool_fetch_attractions(location: str, interests: str = "", duration_days: int = 5) -> dict:
    """Fetches top tourist attractions, activities, and points of interest via Google Maps SerpAPI."""
    query = f"top tourist attractions {interests} in {location}".strip()
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
    }
    data = serpapi_search(params)
    places = data.get("local_results", [])
    results = []
    for a in places[:5]:
        name = a.get("title") or a.get("name", "")
        if not name: continue
        results.append({
            "name": name,
            "rating": str(a.get("rating", "N/A")),
            "type": a.get("type", "Attraction"),
            "description": a.get("description") or a.get("snippet", "")
        })
    return {"attractions": results, "location": location}

@tool
def tool_search_travel_info(query: str) -> dict:
    """Searches Google for general travel information, local customs, visa details, or weather."""
    params = {
        "engine": "google",
        "q": query,
    }
    data = serpapi_search(params)
    organic = data.get("organic_results", [])
    results = [{"title": r.get("title"), "snippet": r.get("snippet")} for r in organic[:3]]
    return {"query": query, "results": results}

@tool
def tool_generate_detailed_plan(destination: str, duration_days: int, budget: str, interests: str, transport_summary: str, stay_summary: str, food_summary: str, attraction_summary: str) -> dict:
    """Generates the final comprehensive day-by-day travel itinerary JSON using the gathered tool data."""
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"""You are an elite travel concierge. Generate a detailed day-by-day plan for a {duration_days}-day trip to {destination}.
Budget: {budget}
Interests: {interests}

Output a JSON list matching this schema:
[
  {{
    "day": 1,
    "title": "Day Title",
    "morning": {{ "time": "08:00 - 12:00", "activity": "description", "food": "breakfast option", "transport": "travel mode" }},
    "lunch": {{ "time": "12:30 - 14:00", "activity": "lunch description", "food": "restaurant name", "transport": "travel mode" }},
    "afternoon": {{ "time": "14:30 - 17:30", "activity": "description", "food": "afternoon snack", "transport": "travel mode" }},
    "dinner": {{ "time": "18:00 - 20:00", "activity": "dinner description", "food": "restaurant name", "transport": "travel mode" }},
    "evening": {{ "time": "20:30 - 22:00", "activity": "evening description", "food": "dessert", "transport": "travel mode" }}
  }}
]
Return ONLY the JSON list inside a ```json ``` block."""
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    content = response.choices[0].message.content or ""
    try:
        if "```json" in content:
            json_start = content.index("```json") + 7
            json_end = content.index("```", json_start)
            json_str = content[json_start:json_end].strip()
        else:
            json_start = content.find("[")
            json_end = content.rfind("]") + 1
            json_str = content[json_start:json_end].strip()
        return {"days": json.loads(json_str)}
    except Exception:
        return {"days": [], "raw_text": content}

# ---------------------------------------------
# AGENT LOGIC & SYSTEM PROMPTS
# ---------------------------------------------
def get_system_prompt_gather() -> str:
    return f"""You are VoyageAgent, an AI travel assistant.
Your goal is to gather the following 7 parameters from the user to build their trip:
1. origin
2. destination
3. duration_days
4. budget
5. interests
6. travel_dates
7. travelers

Keep your questions helpful, short, and friendly.
Once you have collected all 7 parameters, call the TripDetails tool to finalize parameters."""

class TripDetails(BaseModel):
    """Call this tool when you have successfully gathered all 7 pieces of information from the user."""
    origin: str = Field(description="The city the user is departing from.")
    destination: str = Field(description="The city the user is traveling to.")
    duration_days: int = Field(description="Total duration of the trip in days.")
    budget: str = Field(description="Budget level: low, mid-range, or luxury.")
    interests: str = Field(description="Detailed comma-separated interests and activities.")
    travel_dates: str = Field(description="The exact or approximate dates of travel.")
    travelers: int = Field(description="Number of people traveling.")

def run_agent(messages: list) -> tuple[str, dict | None]:
    api_key = os.getenv("GROQ_API_KEY")
    system_content = get_system_prompt_gather()
    gather_messages = [{"role": "system", "content": system_content}]
    for m in messages:
        gather_messages.append({"role": m["role"], "content": m.get("content") or ""})

    llm = ChatGroq(model=GROQ_MODEL, api_key=api_key, temperature=0.5)
    llm_with_tools = llm.bind_tools([TripDetails])

    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    lc_messages = []
    for m in gather_messages:
        if m["role"] == "system":
            lc_messages.append(SystemMessage(content=m["content"]))
        elif m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_messages.append(AIMessage(content=m["content"]))

    gather_response = llm_with_tools.invoke(lc_messages)
    gather_text = gather_response.content or ""

    if getattr(gather_response, "tool_calls", None):
        for tc in gather_response.tool_calls:
            if tc["name"] == "TripDetails":
                return "READY_TO_PLAN", tc["args"]

    return gather_text, None

# ---------------------------------------------
# LANGGRAPH EXECUTION PIPELINE (PHASE 2)
# ---------------------------------------------
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class AgentState(TypedDict):
    gathered_info: dict
    tool_results: dict
    final_text: str

def node_feasibility(state: AgentState):
    gi = state["gathered_info"]
    res = tool_check_route_feasibility.invoke({"origin": gi.get("origin"), "destination": gi.get("destination")})
    state["tool_results"]["feasibility"] = res
    return state

def node_transport(state: AgentState):
    gi = state["gathered_info"]
    f = state["tool_results"].get("feasibility", {})
    res = tool_fetch_transport_options.invoke({
        "origin": gi.get("origin"),
        "destination": gi.get("destination"),
        "trains_available": f.get("trains_available", True),
        "buses_available": f.get("buses_available", True)
    })
    state["tool_results"]["transport_options"] = res
    return state

def node_stays(state: AgentState):
    gi = state["gathered_info"]
    res = tool_fetch_accommodations.invoke({"location": gi.get("destination"), "budget": gi.get("budget")})
    state["tool_results"]["stay_options"] = res.get("hotels", [])
    return state

def node_food(state: AgentState):
    gi = state["gathered_info"]
    res = tool_fetch_restaurants.invoke({"location": gi.get("destination"), "cuisine_preferences": gi.get("interests")})
    state["tool_results"]["food_options"] = res.get("restaurants", [])
    return state

def node_attractions(state: AgentState):
    gi = state["gathered_info"]
    res = tool_fetch_attractions.invoke({"location": gi.get("destination"), "interests": gi.get("interests")})
    state["tool_results"]["attractions"] = res.get("attractions", [])
    return state

def node_itinerary(state: AgentState):
    gi = state["gathered_info"]
    tr = state["tool_results"]
    res = tool_generate_detailed_plan.invoke({
        "destination": gi.get("destination"),
        "duration_days": int(gi.get("duration_days", 1)),
        "budget": gi.get("budget"),
        "interests": gi.get("interests"),
        "transport_summary": json.dumps(tr.get("transport_options")),
        "stay_summary": json.dumps(tr.get("stay_options")[:3]),
        "food_summary": json.dumps(tr.get("food_options")[:3]),
        "attraction_summary": json.dumps(tr.get("attractions")[:3])
    })
    state["tool_results"]["days"] = res.get("days", [])
    state["final_text"] = "Plan generation finished."
    return state

def run_phase_2(gathered_info: dict) -> dict:
    builder = StateGraph(AgentState)
    builder.add_node("feasibility", node_feasibility)
    builder.add_node("transport", node_transport)
    builder.add_node("stays", node_stays)
    builder.add_node("food", node_food)
    builder.add_node("attractions", node_attractions)
    builder.add_node("itinerary", node_itinerary)

    builder.add_edge(START, "feasibility")
    builder.add_edge("feasibility", "transport")
    builder.add_edge("transport", "stays")
    builder.add_edge("stays", "food")
    builder.add_edge("food", "attractions")
    builder.add_edge("attractions", "itinerary")
    builder.add_edge("itinerary", END)

    graph = builder.compile()
    initial_state = {
        "gathered_info": gathered_info,
        "tool_results": {"transport_options": {}, "stay_options": [], "food_options": [], "attractions": []},
        "final_text": ""
    }
    return graph.invoke(initial_state)

# ---------------------------------------------
# FLASK ROUTE
# ---------------------------------------------
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    history = data.get("history", []) # Client acts as conversation memory
    confirmed_params = data.get("confirmed_params", None)

    if confirmed_params:
        try:
            results = run_phase_2(confirmed_params)
            return jsonify({
                "status": "planned",
                "gathered_info": confirmed_params,
                "itinerary": results["tool_results"]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Build messages array for info gathering phase
    messages = []
    for msg in history:
        messages.append({"role": msg.get("role"), "content": msg.get("content")})
    messages.append({"role": "user", "content": user_message})

    try:
        reply_text, gathered_info = run_agent(messages)
        if reply_text == "READY_TO_PLAN":
            return jsonify({
                "status": "confirming",
                "gathered_info": gathered_info,
                "message": "Please confirm your trip details before planning."
            })
        return jsonify({
            "status": "gathering",
            "message": reply_text
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return jsonify({"status": "running", "service": "VoyageAgent AI Core Backend"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
