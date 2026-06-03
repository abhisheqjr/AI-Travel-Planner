import os
import json
import time
import re
import requests
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
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

print("========================================================================", flush=True)
print("  [VoyageAgent] Starting Flask Server in Sync Target directory.", flush=True)
print("  Supabase Client connection state: checking keys...", flush=True)
print("========================================================================", flush=True)

# ─────────────────────────────────────────────
# SUPABASE INITIALIZATION
# ─────────────────────────────────────────────
from supabase import create_client, Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")

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

def divider(char: str = "=", colour: str = C.WHITE) -> None:
    print(f"{colour}{char * 80}{C.RESET}", flush=True)

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
    if not summary: summary.append("No standard direct routes found, might require multi-modal transit.")

    log("OK", f"Feasibility: flights={flights_available} trains={trains_available} buses={buses_available} ferry={ferry_available}", C.GREEN)

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
        for f in candidates[:4]:
            legs = f.get("flights", [])
            if not legs: continue
            airline = legs[0].get("airline", "Unknown Airline")
            total_min = f.get("total_duration", 0)
            duration  = f"{total_min // 60}h {total_min % 60}m" if total_min else "N/A"
            price = f.get("price", "N/A")
            dep_time = legs[0].get("departure_airport", {}).get("time", "")
            arr_time = legs[-1].get("arrival_airport", {}).get("time", "")

            if len(legs) == 1:
                flight_type = "Direct Flight"
            else:
                stopovers = [leg.get("arrival_airport", {}).get("id", "?") for leg in legs[:-1]]
                flight_type = f"Connecting via {', '.join(stopovers)}"

            results.append({
                "airline": f"{airline} ({flight_type})",
                "duration": duration,
                "price": f"${price}" if isinstance(price, (int, float)) else str(price),
                "departure": dep_time,
                "arrival": arr_time,
                "link": f"https://www.google.com/travel/flights?q=Flights+from+{dep_code}+to+{arr_code}+on+{date}"
            })
    except Exception as e:
        log("WARN", f"Google Flights error [{dep_code}->{arr_code}]: {e}", C.YELLOW)
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
    """Fetch real-time transport options (outbound + return) using SerpAPI."""
    log("TOOL", f"fetch_transport_options -> '{origin}' to '{destination}' trains={trains_available} buses={buses_available}", C.MAGENTA)
    dep_code = _resolve_iata(origin)
    arr_code = _resolve_iata(destination)
    today = datetime.now()
    default_out = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    outbound_date = travel_date or default_out

    air_out = []
    if dep_code and arr_code:
        air_out = _fetch_flights_serpapi(dep_code, arr_code, outbound_date)

    air_ret = []
    if return_date and dep_code and arr_code:
        air_ret = _fetch_flights_serpapi(arr_code, dep_code, return_date)

    rail_results = []
    if trains_available:
        try:
            train_data = serpapi_search({
                "engine": "google",
                "q": f"{origin} to {destination} train schedule fare",
                "hl": "en",
                "gl": "us",
                "num": 5
            })
            for r in train_data.get("organic_results", [])[:3]:
                rail_results.append({
                    "name": r.get("title", "Train Service"),
                    "duration": "Check local timetables",
                    "price": "Varies by class",
                    "details": r.get("snippet", ""),
                    "link": r.get("link", "")
                })
            if not rail_results:
                rail_results.append({
                    "name": f"Train: {origin} to {destination}",
                    "duration": "Check local rail portal",
                    "price": "Varies"
                })
        except Exception as e:
            log("WARN", f"Train search failed: {e}", C.YELLOW)

    road_results = []
    if buses_available:
        try:
            bus_data = serpapi_search({
                "engine": "google",
                "q": f"{origin} to {destination} bus route schedule taxi cab fare",
                "hl": "en",
                "gl": "us",
                "num": 5
            })
            for r in bus_data.get("organic_results", [])[:3]:
                road_results.append({
                    "type": "Bus / Cab",
                    "duration": "Route & traffic dependent",
                    "price": "Varies by operator",
                    "operator": r.get("title", "Road operator"),
                    "details": r.get("snippet", ""),
                    "link": r.get("link", "")
                })
            if not road_results:
                road_results.append({
                    "type": "Bus / Private Taxi",
                    "duration": "Check local schedules",
                    "price": "Varies"
                })
        except Exception as e:
            log("WARN", f"Road transport search failed: {e}", C.YELLOW)

    return {
        "outbound": {
            "air": air_out,
            "rail": rail_results,
            "road": road_results
        },
        "return": {
            "air": air_ret,
            "rail": rail_results if trains_available else [],
            "road": road_results if buses_available else []
        },
        "air": air_out,
        "rail": rail_results,
        "road": road_results
    }

@tool
def tool_fetch_accommodations(location: str, budget: str, check_in: str = "", check_out: str = "") -> dict:
    """Fetches real-time hotel and accommodation options from Google Hotels via SerpAPI."""
    log("TOOL", f"fetch_accommodations -> location='{location}' budget='{budget}'", C.MAGENTA)
    today = datetime.now()
    default_in = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    default_out = (today + timedelta(days=35)).strftime("%Y-%m-%d")

    params = {
        "engine": "google_hotels",
        "q": f"hotels in {location}",
        "check_in_date": check_in or default_in,
        "check_out_date": check_out or default_out,
        "currency": "USD",
        "gl": "us",
        "hl": "en"
    }
    data = serpapi_search(params)
    properties = data.get("properties", []) or data.get("hotels", [])
    results = []
    for h in properties[:6]:
        name = h.get("name") or h.get("title", "")
        if not name: continue
        price_info = h.get("rate_per_night") or h.get("prices", [{}])[0] if h.get("prices") else {}
        price = price_info.get("lowest") or price_info.get("rate") or "N/A"
        image_url = ""
        images = h.get("images") or h.get("photos", [])
        if images and isinstance(images, list):
            image_url = images[0].get("thumbnail") or images[0].get("url", "")
            
        maps_link = f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}+{requests.utils.quote(location)}"
        stars = str(h.get("class_rating") or "3-4")
        amenities = h.get("amenities", [])
        if not amenities:
            amenities = ["Free Wi-Fi", "Air Conditioning", "Comfortable beds"]

        results.append({
            "name": name,
            "location": h.get("neighborhood") or h.get("address", location),
            "price": str(price),
            "rating": str(h.get("overall_rating") or h.get("rating", "N/A")),
            "reviews": f"{h.get('reviews', 0)} reviews",
            "description": h.get("description") or f"A lovely hotel in {location}.",
            "image": image_url,
            "stars": stars,
            "amenities": amenities[:4],
            "google_maps_link": maps_link
        })
    log("OK", f"Hotels found: {len(results)}", C.GREEN)
    return {"hotels": results, "location": location, "budget": budget}

@tool
def tool_fetch_restaurants(location: str, cuisine_preferences: str = "") -> dict:
    """Fetches top-rated restaurants, cafes, and dining options via Google Maps SerpAPI."""
    log("TOOL", f"fetch_restaurants -> location='{location}' cuisine='{cuisine_preferences}'", C.MAGENTA)
    query = f"best restaurants {cuisine_preferences} in {location}".strip()
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "hl": "en",
        "gl": "us"
    }
    data = serpapi_search(params)
    places = data.get("local_results", [])
    results = []
    for r in places[:6]:
        name = r.get("title") or r.get("name", "")
        if not name: continue
        maps_link = f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}+{requests.utils.quote(r.get('address', location))}"
        
        desc = r.get("description") or r.get("snippet", "")
        famous_dish = "Signature Platter"
        keywords = ["biryani", "seafood", "fish", "curry", "dosa", "pasta", "pizza", "burger", "steak", "sushi", "croissant"]
        for kw in keywords:
            if kw in desc.lower():
                famous_dish = kw.capitalize()
                break

        results.append({
            "restaurant": name,
            "rating": str(r.get("rating", "N/A")),
            "reviews": str(r.get("reviews", "")),
            "type": r.get("type", "Restaurant"),
            "address": r.get("address", location),
            "price_range": r.get("price", "$$"),
            "famous_dish": famous_dish,
            "description": desc or f"A popular dining spot in {location}.",
            "image": r.get("thumbnail", ""),
            "google_maps_link": maps_link
        })
    log("OK", f"Restaurants found: {len(results)}", C.GREEN)
    return {"restaurants": results, "location": location}

@tool
def tool_fetch_attractions(location: str, interests: str = "", duration_days: int = 5) -> dict:
    """Fetches top tourist attractions, activities, and points of interest via Google Maps SerpAPI."""
    log("TOOL", f"fetch_attractions -> location='{location}' interests='{interests}'", C.MAGENTA)
    query = f"top tourist attractions {interests} in {location}".strip()
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "hl": "en",
        "gl": "us"
    }
    data = serpapi_search(params)
    places = data.get("local_results", [])
    results = []
    for a in places[:8]:
        name = a.get("title") or a.get("name", "")
        if not name: continue
        maps_link = f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}+{requests.utils.quote(a.get('address', location))}"
        
        desc = a.get("description") or a.get("snippet", "")
        highlights = ["Sightseeing", "Photography"]
        if "museum" in desc.lower() or "art" in desc.lower():
            highlights = ["Art Exhibits", "Guided Tours"]
        elif "beach" in desc.lower() or "nature" in desc.lower():
            highlights = ["Scenic Views", "Sunset Watching"]
            
        entry_fee = "Free Entry"
        if "ticket" in desc.lower() or "admission" in desc.lower():
            entry_fee = "Paid Admission"

        results.append({
            "name": name,
            "rating": str(a.get("rating", "N/A")),
            "reviews": str(a.get("reviews", "")),
            "type": a.get("type", "Attraction"),
            "address": a.get("address", location),
            "highlights": highlights,
            "entry_fee": entry_fee,
            "description": desc or f"A must-visit spot in {location}.",
            "image": a.get("thumbnail", ""),
            "google_maps_link": maps_link
        })
    log("OK", f"Attractions found: {len(results)}", C.GREEN)
    return {"attractions": results, "location": location}

@tool
def tool_search_travel_info(query: str) -> dict:
    """Searches Google for general travel information, local customs, visa details, or weather."""
    log("TOOL", f"search_travel_info -> query='{query}'", C.MAGENTA)
    params = {
        "engine": "google",
        "q": query,
        "hl": "en",
        "gl": "us",
        "num": 5
    }
    data = serpapi_search(params)
    organic = data.get("organic_results", [])
    results = [{"title": r.get("title"), "snippet": r.get("snippet"), "link": r.get("link")} for r in organic[:4]]
    return {"query": query, "results": results, "answer": data.get("answer_box", {})}

@tool
def tool_generate_detailed_plan(destination: str, duration_days: int, budget: str, interests: str, transport_summary: str, stay_summary: str, food_summary: str, attraction_summary: str) -> dict:
    """Generates the final comprehensive day-by-day travel itinerary JSON using the gathered tool data."""
    log("TOOL", f"generate_detailed_plan -> destination='{destination}' days={duration_days}", C.MAGENTA)
    client = Groq(api_key=GROQ_API_KEY)
    
    length_constraint = ""
    if duration_days > 5:
        length_constraint = f"\n- CRITICAL: Since this is a long trip ({duration_days} days), you MUST keep the activity, food, and transport text fields concise (maximum 15-20 words each) to avoid output token limit truncation (4096 tokens)."

    prompt = f"""You are an elite travel concierge. Generate a detailed day-by-day plan for a {duration_days}-day trip to {destination}.
Budget: {budget}
Interests: {interests}
Transport context: {transport_summary}
Stays available: {stay_summary}
Dining available: {food_summary}
Attractions available: {attraction_summary}
{length_constraint}

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
        json_str = ""
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            if json_end != -1:
                json_str = content[json_start:json_end].strip()
            else:
                json_str = content[json_start:].strip()
        elif "```" in content:
            json_start = content.find("```") + 3
            json_end = content.find("```", json_start)
            if json_end != -1:
                json_str = content[json_start:json_end].strip()
            else:
                json_str = content[json_start:].strip()
        else:
            json_start = content.find("[")
            json_end = content.rfind("]") + 1
            if json_start != -1 and json_end != 0:
                json_str = content[json_start:json_end].strip()
            else:
                json_str = content.strip()
                
        try:
            days = json.loads(json_str)
        except Exception as je:
            # Fallback: Extract completed day objects by balancing braces
            day_objects = []
            brace_count = 0
            start_pos = -1
            for pos, char in enumerate(content):
                if char == '{':
                    if brace_count == 0:
                        start_pos = pos
                    brace_count += 1
                elif char == '}':
                    if brace_count > 0:
                        brace_count -= 1
                        if brace_count == 0 and start_pos != -1:
                            candidate = content[start_pos:pos+1]
                            if '"day"' in candidate or "'day'" in candidate:
                                try:
                                    day_obj = json.loads(candidate)
                                    day_objects.append(day_obj)
                                except Exception:
                                    pass
            if day_objects:
                return {"days": day_objects}
            raise je

        return {"days": days}
    except Exception as e:
        log("ERROR", f"Failed to parse generated detailed plan: {e}", C.RED)
        return {"days": [], "raw_text": content}

# ---------------------------------------------
# BUDGET CLASSIFIER HELPER
# ---------------------------------------------
def _classify_budget_tier(origin: str, destination: str, duration_days: int, travelers: int, raw_budget: str, api_key: str) -> str:
    clean = str(raw_budget).strip().lower()
    if not any(char.isdigit() for char in clean):
        if any(kw in clean for kw in ["luxury", "high", "premium"]):
            return "luxury"
        if any(kw in clean for kw in ["mid", "medium", "standard", "moderate"]):
            return "mid budget"
        if any(kw in clean for kw in ["low", "budget"]):
            return "low budget"
            
    try:
        client = Groq(api_key=api_key)
        prompt = f"""You are a travel budget analyst. A user is planning a trip:
- Origin: {origin}
- Destination: {destination}
- Duration: {duration_days} days
- Travelers: {travelers}
- Stated Budget: {raw_budget}

Determine which category it fits: "low budget", "mid budget", or "luxury".
Respond with ONLY one of these terms. Do not add extra punctuation or text."""

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=15,
        )
        classified = completion.choices[0].message.content.strip().lower()
        if "low" in classified:
            return "low budget"
        elif "luxury" in classified or "high" in classified:
            return "luxury"
        elif "medium" in classified or "mid" in classified:
            return "mid budget"
    except Exception as e:
        log("WARN", f"Budget classification failed: {e}", C.YELLOW)
        
    if any(kw in clean for kw in ["luxury", "high"]):
        return "luxury"
    if any(kw in clean for kw in ["mid", "medium", "standard", "moderate"]):
        return "mid budget"
    if any(kw in clean for kw in ["low", "budget"]):
        return "low budget"
    return "mid budget"

# ---------------------------------------------
# AGENT LOGIC & SYSTEM PROMPTS
# ---------------------------------------------
def get_system_prompt_gather() -> str:
    now = datetime.now()
    today_str = now.strftime("%A, %B %d, %Y")
    tomorrow = (now + timedelta(days=1)).strftime("%B %d")
    after_2 = (now + timedelta(days=2)).strftime("%B %d")
    next_week = (now + timedelta(days=7)).strftime("%B %d")

    return f"""You are VoyageAgent, a professional AI travel assistant.
The current local date is: {today_str}.

Your goal is to gather the following 7 parameters from the user to build their trip:
1. origin
2. destination
3. duration_days
4. budget
5. interests
6. travel_dates
7. travelers

Rules:
- Treat the user with formal courtesy. Do not use terms of endearment.
- If the user asks general questions outside travel planning, refuse politely.
- Resolve relative terms correctly based on {today_str}: "today" = {today_str} | "tomorrow" = {tomorrow} | "after 2 days" = {after_2} | "next week" = {next_week}.
- Reject past dates.
- Once you have collected all 7 parameters, call the TripDetails tool to finalize parameters."""

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
                gathered_info = tc["args"]
                
                # Dynamic budget classification
                raw_budget = gathered_info.get("budget", "")
                if raw_budget:
                    try:
                        classified_budget = _classify_budget_tier(
                            origin=gathered_info.get("origin", ""),
                            destination=gathered_info.get("destination", ""),
                            duration_days=int(gathered_info.get("duration_days", 1)),
                            travelers=int(gathered_info.get("travelers", 1)),
                            raw_budget=raw_budget,
                            api_key=api_key
                        )
                        gathered_info["budget"] = classified_budget
                    except Exception as e:
                        log("WARN", f"Budget classification failed: {e}", C.YELLOW)

                # AI interpretation of interests
                raw_interests = gathered_info.get("interests", "")
                if raw_interests:
                    try:
                        client = Groq(api_key=api_key)
                        interpret_prompt = f"""You are an elite travel planner. Given the user's raw stated interests: "{raw_interests}"
Generate a brief, highly inspiring 1-sentence professional AI interpretation of their interests. Under 25 words."""
                        interpret_comp = client.chat.completions.create(
                            model="llama-3.1-8b-instant",
                            messages=[{"role": "user", "content": interpret_prompt}],
                            temperature=0.3,
                            max_tokens=50
                        )
                        interpreted = interpret_comp.choices[0].message.content.strip().replace('"', '')
                        if len(interpreted) > 5:
                            gathered_info["interests"] = interpreted
                    except Exception as e:
                        log("WARN", f"Interests AI interpretation failed: {e}", C.YELLOW)

                return "READY_TO_PLAN", gathered_info

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
    
    travel_dates = gi.get("travel_dates", "")
    travel_date = ""
    return_date = ""
    if travel_dates:
        import re
        date_matches = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', travel_dates)
        if len(date_matches) >= 1:
            travel_date = date_matches[0]
        if len(date_matches) >= 2:
            return_date = date_matches[1]

    res = tool_fetch_transport_options.invoke({
        "origin": gi.get("origin"),
        "destination": gi.get("destination"),
        "travel_date": travel_date,
        "return_date": return_date,
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

# ─────────────────────────────────────────────
# EMAIL OTP & PASSWORD RESET WORKFLOW (SMTP)
# ─────────────────────────────────────────────
import smtplib
import random
from email.mime.text import MIMEText

def send_otp_email(to_email, otp, mode="register"):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_sender = os.getenv("SMTP_SENDER", "")

    if not smtp_username or not smtp_password:
        log("ERROR", f"SMTP credentials missing. Cannot send OTP to {to_email}", C.RED)
        return False

    if mode == "register":
        title = "Verify Your Registration"
        greeting = "Welcome to VoyageAgent"
        message_text = "Thank you for joining VoyageAgent! To finish setting up your account, please verify your email address by using the 6-digit OTP code below."
        subject = "VoyageAgent - Verify Your Account OTP"
    elif mode == "update":
        title = "Verify Your Account Changes"
        greeting = "Hello"
        message_text = "We received a request to update your account username and/or password. To complete these changes, please verify using the 6-digit OTP code below."
        subject = "VoyageAgent - Verify Your Account Changes"
    else:
        title = "Reset Your Password"
        greeting = "Hello"
        message_text = "We received a request to reset your account password. Use the 6-digit OTP code below to set up your new credentials."
        subject = "VoyageAgent - Reset Your Password OTP"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>VoyageAgent Verification</title>
    <style>
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #f1f5f9;
            margin: 0;
            padding: 0;
            -webkit-font-smoothing: antialiased;
        }}
        .container {{
            max-width: 600px;
            margin: 40px auto;
            background-color: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 25px -5px rgba(0,0,0,0.05), 0 8px 10px -6px rgba(0,0,0,0.05);
            border: 1px solid #e2e8f0;
        }}
        .header {{
            background-color: #0f172a;
            padding: 32px;
            text-align: center;
            border-bottom: 3px solid #3b82f6;
        }}
        .logo-text {{
            font-size: 28px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.5px;
            text-decoration: none;
        }}
        .logo-icon {{
            color: #3b82f6;
            margin-right: 8px;
        }}
        .content {{
            padding: 40px 32px;
            color: #334155;
            line-height: 1.6;
        }}
        h2 {{
            color: #0f172a;
            font-size: 20px;
            font-weight: 700;
            margin-top: 0;
            margin-bottom: 16px;
        }}
        p {{
            font-size: 15px;
            margin-top: 0;
            margin-bottom: 24px;
        }}
        .otp-container {{
            background-color: #f8fafc;
            border: 2px dashed #cbd5e1;
            border-radius: 12px;
            padding: 24px;
            text-align: center;
            margin: 28px 0;
        }}
        .otp-code {{
            font-size: 36px;
            font-weight: 800;
            color: #2563eb;
            letter-spacing: 6px;
            margin: 0;
            font-family: 'Courier New', Courier, monospace;
        }}
        .otp-label {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #64748b;
            font-weight: 700;
            margin-bottom: 8px;
        }}
        .footer {{
            background-color: #f8fafc;
            padding: 24px 32px;
            text-align: center;
            font-size: 13px;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
        }}
        .security-notice {{
            font-size: 12px;
            color: #94a3b8;
            margin-top: 16px;
            border-top: 1px solid #f1f5f9;
            padding-top: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span class="logo-text">VoyageAgent</span>
        </div>
        <div class="content">
            <h2>{title}</h2>
            <p>{greeting},</p>
            <p>{message_text}</p>
            
            <div class="otp-container">
                <div class="otp-label">Verification OTP Code</div>
                <div class="otp-code">{otp}</div>
            </div>
            
            <p>This code is valid for <strong>10 minutes</strong>. For security reasons, please do not share this code with anyone.</p>
            
            <p>Safe travels,<br><strong>The VoyageAgent Team</strong></p>
        </div>
        <div class="footer">
            © 2026 VoyageAgent. All rights reserved.<br>
            Your AI-Powered Premium Itinerary Assistant.
            <div class="security-notice">
                If you did not request this verification code, please disregard this email. Your account remains completely secure.
            </div>
        </div>
    </div>
</body>
</html>"""

    msg = MIMEText(html_content, 'html')
    msg['Subject'] = subject
    msg['From'] = smtp_sender
    msg['To'] = to_email

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(smtp_sender, [to_email], msg.as_string())
        server.quit()
        log("INFO", f"HTML OTP successfully sent to {to_email}", C.GREEN)
        return True
    except Exception as e:
        log("ERROR", f"SMTP send failed: {e}.", C.RED)
        return False

# ---------------------------------------------
# FLASK ROUTE
# ---------------------------------------------
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    history = data.get("history", [])
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
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    session.pop("just_logged_in", None)
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json() or {}
        email = data.get("email", "").strip()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"error": "Email and password are required."}), 400

        if not supabase:
            # Safe local fallback offline
            if email == "siva@gmail.com" and password == "123456":
                session["user_id"] = "dummy-siva-uuid"
                session["username"] = "Siva"
                session["just_logged_in"] = True
                return jsonify({"status": "success"}), 200
            return jsonify({"error": "Invalid email or password."}), 400

        try:
            res = supabase.table("users").select("*").eq("email", email).execute()
            if not res.data:
                return jsonify({"error": "Invalid email or password."}), 400
            
            user = res.data[0]
            if user.get("password_hash") == password:
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["just_logged_in"] = True
                return jsonify({"status": "success"}), 200
            else:
                return jsonify({"error": "Invalid email or password."}), 400
        except Exception as e:
            log("ERROR", f"Login database error: {e}", C.RED)
            return jsonify({"error": "Database error. Please try again."}), 500

    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template('login.html')

@app.route('/register/send-otp', methods=['POST'])
def register_send_otp():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    if not username or not email or not password or not confirm_password:
        return jsonify({"error": "All fields are required."}), 400

    if password != confirm_password:
        return jsonify({"error": "Passwords do not match."}), 400

    # Verify if email already registered
    if supabase:
        try:
            res = supabase.table("users").select("id").eq("email", email).execute()
            if res.data:
                return jsonify({"error": "Email address already registered."}), 400
        except Exception as e:
            log("ERROR", f"Database error checking email: {e}", C.RED)
            return jsonify({"error": "Database error. Please try again."}), 500
    else:
        if email == "siva@gmail.com":
            return jsonify({"error": "Email address already registered."}), 400

    # Generate OTP
    otp = str(random.randint(100000, 999999))
    session["reg_otp"] = otp
    session["reg_email"] = email
    session["reg_username"] = username
    session["reg_password"] = password

    if not send_otp_email(email, otp, mode="register"):
        return jsonify({"error": "Failed to send verification email. Please verify your SMTP settings."}), 500
    return jsonify({"status": "success", "message": "Verification OTP sent to your email."}), 200

@app.route('/register/verify-otp', methods=['POST'])
def register_verify_otp():
    data = request.get_json() or {}
    otp = data.get("otp", "").strip()

    if not otp:
        return jsonify({"error": "OTP is required."}), 400

    saved_otp = session.get("reg_otp")
    if not saved_otp or saved_otp != otp:
        return jsonify({"error": "Invalid or expired OTP."}), 400

    username = session.get("reg_username")
    email = session.get("reg_email")
    password = session.get("reg_password")

    if not username or not email or not password:
        return jsonify({"error": "Session expired. Please try registering again."}), 400

    if not supabase:
        # Offline mode registration
        session.clear()
        session["user_id"] = "dummy-siva-uuid"
        session["username"] = username
        session["just_logged_in"] = True
        return jsonify({"status": "success", "message": "Account created successfully."}), 201

    try:
        new_user = {
            "username": username,
            "email": email,
            "password_hash": password
        }
        insert_res = supabase.table("users").insert(new_user).execute()
        if not insert_res.data:
            return jsonify({"error": "Failed to create account. Please try again."}), 500

        # Success: Clear register sessions, log user in
        session.clear()
        user = insert_res.data[0]
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["just_logged_in"] = True

        return jsonify({"status": "success", "message": "Account created successfully."}), 201
    except Exception as e:
        log("ERROR", f"Failed to save user: {e}", C.RED)
        return jsonify({"error": "Database error. Please try again."}), 500

@app.route('/forgot-password/send-otp', methods=['POST'])
def forgot_password_send_otp():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email address is required."}), 400

    # Verify if email exists in database
    user_found = False
    if supabase:
        try:
            res = supabase.table("users").select("id").eq("email", email).execute()
            if res.data:
                user_found = True
        except Exception as e:
            log("ERROR", f"Forgot password db check error: {e}", C.RED)
            return jsonify({"error": "Database error."}), 500
    else:
        if email == "siva@gmail.com":
            user_found = True

    if not user_found:
        return jsonify({"error": "Email address not found."}), 400

    # Generate OTP
    otp = str(random.randint(100000, 999999))
    session["forgot_otp"] = otp
    session["forgot_email"] = email
    session["forgot_otp_verified"] = False

    if not send_otp_email(email, otp, mode="forgot"):
        return jsonify({"error": "Failed to send verification email. Please verify your SMTP settings."}), 500
    return jsonify({"status": "success", "message": "Verification OTP sent to your email."}), 200

@app.route('/forgot-password/verify-otp', methods=['POST'])
def forgot_password_verify_otp():
    data = request.get_json() or {}
    otp = data.get("otp", "").strip()

    if not otp:
        return jsonify({"error": "OTP is required."}), 400

    saved_otp = session.get("forgot_otp")
    if not saved_otp or saved_otp != otp:
        return jsonify({"error": "Invalid or expired OTP."}), 400

    session["forgot_otp_verified"] = True
    return jsonify({"status": "success", "message": "OTP verified successfully."}), 200

@app.route('/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    data = request.get_json() or {}
    password = data.get("password", "")
    confirm_password = data.get("confirm_password", "")

    if not password or not confirm_password:
        return jsonify({"error": "Password and Confirm Password are required."}), 400

    if password != confirm_password:
        return jsonify({"error": "Passwords do not match."}), 400

    if not session.get("forgot_otp_verified"):
        return jsonify({"error": "Unauthorized. Please verify OTP first."}), 403

    email = session.get("forgot_email")
    if not email:
        return jsonify({"error": "Session expired. Please start forgot password flow again."}), 400

    if not supabase:
        # Offline mode simulated password reset
        session.clear()
        return jsonify({"status": "success", "message": "Password reset successfully. Please log in with your new password."}), 200

    try:
        # Update user password in the db
        update_res = supabase.table("users").update({"password_hash": password}).eq("email", email).execute()
        if not update_res.data:
            return jsonify({"error": "Failed to update password. Please try again."}), 500

        # Success: Clear sessions
        session.clear()
        return jsonify({"status": "success", "message": "Password reset successfully. Please log in with your new password."}), 200
    except Exception as e:
        log("ERROR", f"Failed to reset password: {e}", C.RED)
        return jsonify({"error": "Database error. Please try again."}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
