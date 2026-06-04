import os
import json
import time
import requests
from flask import Flask, request, jsonify, render_template, send_file, Response, session, redirect, url_for
from dotenv import load_dotenv
from groq import Groq

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(32)
# ↑ Random key on every start = old sessions are always invalidated on restart,
#   forcing users to log in again. Set FLASK_SECRET_KEY in .env for persistent sessions.

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

GROQ_MODEL = "llama-3.3-70b-versatile"

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
        print(f"Failed to initialize Supabase client: {e}")# ─────────────────────────────────────────────
# TERMINAL LOGGER (coloured, timestamped, ASCII-safe for Windows)
# ─────────────────────────────────────────────
import sys, io
# Force UTF-8 output on Windows so special chars don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

class C:  # ANSI colour codes
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
    """Current timestamp string."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def log(level: str, msg: str, colour: str = C.WHITE) -> None:
    """Print a coloured, timestamped log line (ASCII-safe)."""
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
    print(f"{C.DIM}{ts()}{C.RESET} {icon} {label} {colour}{msg}{C.RESET}", flush=True)

def divider(char="=", colour=C.DIM, width=80):
    print(f"{colour}{char * width}{C.RESET}", flush=True)

# -- Startup banner -----------------------------------------------------------
divider("=", C.CYAN)
print(f"{C.CYAN}{C.BOLD}  [VoyageAgent]  Agentic AI Travel Planner  |  Real-Time SerpAPI + Groq{C.RESET}")
print(f"{C.DIM}  Model   : {GROQ_MODEL}{C.RESET}")
print(f"{C.DIM}  Groq    : {'OK - configured' if GROQ_API_KEY else 'MISSING - add to .env'}{C.RESET}")
print(f"{C.DIM}  SerpAPI : {'OK - configured' if SERPAPI_API_KEY else 'MISSING - add to .env'}{C.RESET}")
divider("=", C.CYAN)


# ─────────────────────────────────────────────
# REAL-TIME SERPAPI TOOL IMPLEMENTATIONS
# ─────────────────────────────────────────────

def serpapi_search(params: dict) -> dict:
    """Core SerpAPI caller with verbose logging."""
    if not SERPAPI_API_KEY or SERPAPI_API_KEY.startswith("your_serpapi"):
        raise ValueError("SERPAPI_API_KEY is not configured. Please add it to your .env file.")
    engine = params.get("engine", "?")
    query  = params.get("q", "?")
    log("API", f"SerpAPI [{engine}] -> \"{query}\"", C.BLUE)
    params["api_key"] = SERPAPI_API_KEY
    t0 = time.time()
    resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
    elapsed = (time.time() - t0) * 1000
    resp.raise_for_status()
    data = resp.json()
    log("OK", f"SerpAPI [{engine}] responded in {elapsed:.0f}ms - status {resp.status_code}", C.GREEN)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# AGENTIC IATA RESOLVER (replaces hardcoded map)
# ─────────────────────────────────────────────────────────────────────────────

_IATA_CACHE = {}

# Pre-defined mapping for extremely common cities to avoid network calls and timeouts
COMMON_CITY_IATA = {
    "dubai": "DXB",
    "new york": "JFK",
    "london": "LHR",
    "paris": "CDG",
    "tokyo": "HND",
    "singapore": "SIN",
    "sydney": "SYD",
    "rome": "FCO",
    "delhi": "DEL",
    "mumbai": "BOM",
    "bengaluru": "BLR",
    "bangalore": "BLR",
    "chennai": "MAA",
    "kolkata": "CCU",
    "hyderabad": "HYD",
    "san francisco": "SFO",
    "los angeles": "LAX",
    "chicago": "ORD",
    "miami": "MIA",
    "boston": "BOS",
    "seattle": "SEA",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "barcelona": "BCN",
    "madrid": "MAD",
    "amsterdam": "AMS",
    "berlin": "BER",
    "frankfurt": "FRA",
    "munich": "MUC",
    "zurich": "ZRH",
    "bangkok": "BKK",
    "hong kong": "HKG",
    "seoul": "ICN",
    "dublin": "DUB",
    "copenhagen": "CPH",
    "oslo": "OSL",
    "stockholm": "ARN",
    "vienna": "VIE",
    "brussels": "BRU",
    "geneva": "GVA",
    "istanbul": "IST",
    "cairo": "CAI",
    "cape town": "CPT",
    "johannesburg": "JNB",
    "nairobi": "NBO",
    "melbourne": "MEL",
    "auckland": "AKL",
}

# Translate metropolitan codes to primary airport codes (which SerpAPI Google Flights needs)
METRO_TO_AIRPORT = {
    "NYC": "JFK",  # New York City -> John F. Kennedy
    "LON": "LHR",  # London -> Heathrow
    "TYO": "HND",  # Tokyo -> Haneda
    "PAR": "CDG",  # Paris -> Charles de Gaulle
    "SEL": "ICN",  # Seoul -> Incheon
    "CHI": "ORD",  # Chicago -> O'Hare
    "WAS": "IAD",  # Washington DC -> Dulles
    "BJS": "PEK",  # Beijing -> Capital
    "SHA": "PVG",  # Shanghai -> Pudong
    "YTO": "YYZ",  # Toronto -> Pearson
    "ROM": "FCO",  # Rome -> Fiumicino
    "MIL": "MXP",  # Milan -> Malpensa
    "OSA": "KIX",  # Osaka -> Kansai
    "STO": "ARN",  # Stockholm -> Arlanda
    "REK": "KEF",  # Reykjavik -> Keflavik
    "MOW": "SVO",  # Moscow -> Sheremetyevo
}

def _resolve_iata(city: str) -> str | None:
    """Agentically resolve a city or country string to an IATA code using SerpAPI."""
    key = city.lower().strip()
    
    # Already a 3-letter IATA code
    if len(key) == 3 and key.isalpha():
        code = key.upper()
        return METRO_TO_AIRPORT.get(code, code)
        
    if key in COMMON_CITY_IATA:
        return COMMON_CITY_IATA[key]
        
    if key in _IATA_CACHE:
        return _IATA_CACHE[key]
        
    if not SERPAPI_API_KEY:
        log("WARN", "SerpAPI key missing. Cannot resolve IATA.", C.YELLOW)
        return None
        
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
            # 1. Check direct answer box
            ans = data.get("answer_box", {}).get("answer", "")
            if ans and len(ans) == 3 and ans.isalpha():
                code = ans.upper()
                code = METRO_TO_AIRPORT.get(code, code)
                _IATA_CACHE[key] = code
                return code
                
            # 2. Regex fallback on snippets
            snippets = " ".join([x.get("snippet", "") for x in data.get("organic_results", [])])
            m = re.search(r'(?i)\bIATA[^\w]*([A-Z]{3})\b', snippets)
            if m:
                code = m.group(1).upper()
                code = METRO_TO_AIRPORT.get(code, code)
                _IATA_CACHE[key] = code
                return code
                
        return None
    except Exception as e:
        log("WARN", f"IATA resolution failed for '{city}': {e}", C.YELLOW)
        return None

# ─────────────────────────────────────────────────────────────────────────────
# NEW AGENT TOOL — check_route_feasibility
# Uses SerpAPI Google search to determine whether flights / trains / buses
# actually exist between two cities.  100 % SerpAPI — no hardcoded logic.
# ─────────────────────────────────────────────────────────────────────────────

@tool
def tool_check_route_feasibility(origin: str, destination: str) -> dict:
    """Checks the overall feasibility and which transport modes are physically available between two locations."""
    log("TOOL", f"check_route_feasibility -> '{origin}' to '{destination}'", C.MAGENTA)

    flights_available = False
    trains_available = False
    buses_available = False
    ferry_available = False
    
    # Check flights via IATA resolution
    dep_iata = _resolve_iata(origin)
    arr_iata = _resolve_iata(destination)
    if dep_iata and arr_iata:
        flights_available = True

    # Check land/transit feasibility via Google Maps Directions
    try:
        # Check driving route (for buses/road)
        drive_params = {
            "engine": "google_maps_directions",
            "start_addr": origin,
            "end_addr": destination,
            "travel_mode": "0",  # Driving
            "api_key": SERPAPI_API_KEY
        }
        drive_resp = requests.get("https://serpapi.com/search", params=drive_params, timeout=5).json()
        if not drive_resp.get("error") and drive_resp.get("directions"):
            buses_available = True

        # Check transit route (for trains/buses/ferries)
        transit_params = {
            "engine": "google_maps_directions",
            "start_addr": origin,
            "end_addr": destination,
            "travel_mode": "3",  # Transit
            "api_key": SERPAPI_API_KEY
        }
        transit_resp = requests.get("https://serpapi.com/search", params=transit_params, timeout=5).json()
        if not transit_resp.get("error") and transit_resp.get("directions"):
            # If transit exists, assume trains are available as a generic fallback since Maps returned a route
            trains_available = True
            
            # Optionally check steps for ferry
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

    log("OK", f"Feasibility: flights={flights_available} trains={trains_available} "
               f"buses={buses_available} ferry={ferry_available}", C.GREEN)

    return {
        "flights_available": flights_available,
        "trains_available": trains_available,
        "buses_available": buses_available,
        "ferry_available": ferry_available,
        "summary": " ".join(summary)
    }


# ─────────────────────────────────────────────────────────────────────────────
# TRANSPORT OPTIONS TOOL  — SerpAPI only, zero fallback data
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_flights_serpapi(dep_code: str, arr_code: str, date: str) -> list:
    """
    Query SerpAPI Google Flights for dep_code -> arr_code on given date.
    First tries direct (type=2 one-way). Returns list of flight dicts.
    """
    results = []
    if not dep_code or not arr_code or dep_code == arr_code:
        return results

    base_params = {
        "engine": "google_flights",
        "departure_id": dep_code,
        "arrival_id":   arr_code,
        "outbound_date": date,
        "type": "2",          # 2 = one-way (fixes the 400 error caused by missing return_date)
        "currency": "USD",
        "hl": "en",
        "gl": "us",
    }

    try:
        flight_data = serpapi_search(base_params)
        candidates = flight_data.get("best_flights", []) or flight_data.get("other_flights", [])

        for f in candidates[:4]:
            legs = f.get("flights", [])
            if not legs:
                continue
            airline   = legs[0].get("airline", "Unknown Airline")
            total_min = f.get("total_duration", 0)
            duration  = f"{total_min // 60}h {total_min % 60}m" if total_min else "N/A"
            price     = f.get("price", "N/A")
            dep_time  = legs[0].get("departure_airport", {}).get("time", "")
            arr_time  = legs[-1].get("arrival_airport",  {}).get("time", "")

            if len(legs) == 1:
                flight_type = "Direct Flight"
            else:
                stopovers   = [leg.get("arrival_airport", {}).get("id", "?") for leg in legs[:-1]]
                flight_type = f"Connecting via {', '.join(stopovers)}"

            results.append({
                "airline":   f"{airline} ({flight_type})",
                "duration":  duration,
                "price":     f"${price}" if isinstance(price, (int, float)) else str(price),
                "departure": dep_time,
                "arrival":   arr_time,
                "link":      f"https://www.google.com/travel/flights?q=Flights+from+{dep_code}+to+{arr_code}+on+{date}",
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
    """
    Fetch real-time transport options (outbound + return) using SerpAPI only.
    - travel_date : departure date (YYYY-MM-DD)
    - return_date : return date   (YYYY-MM-DD)  — if provided, also fetches return journey
    - trains_available / buses_available : pass from check_route_feasibility
    """
    log("TOOL", f"fetch_transport_options -> '{origin}' to '{destination}' "
               f"out='{travel_date}' ret='{return_date}' "
               f"trains={trains_available} buses={buses_available}", C.MAGENTA)

    dep_code = _resolve_iata(origin)
    arr_code = _resolve_iata(destination)

    today        = datetime.now()
    default_out  = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    outbound_date = travel_date or default_out

    # ─── OUTBOUND FLIGHTS ──────────────────────────────────────────────────
    air_out: list = []
    if dep_code and arr_code:
        air_out = _fetch_flights_serpapi(dep_code, arr_code, outbound_date)
        if not air_out:
            log("WARN", f"No direct flights found {dep_code}->{arr_code}. Trying connecting search.", C.YELLOW)
            # SerpAPI sometimes returns connecting flights in a separate key — already handled.
            # If still empty, report clearly.
            air_out.append({
                "airline":  "No flights found for this date — check airline portals directly",
                "duration": "N/A",
                "price":    "N/A",
                "departure": outbound_date,
            })
    else:
        log("WARN", f"Could not resolve IATA: dep={dep_code} arr={arr_code}", C.YELLOW)
        air_out.append({
            "airline":  f"Airport code not found for '{origin if not dep_code else destination}' — check airline portals",
            "duration": "N/A",
            "price":    "N/A",
            "departure": outbound_date,
        })

    # ─── RETURN FLIGHTS ────────────────────────────────────────────────────
    air_ret: list = []
    if return_date and dep_code and arr_code:
        air_ret = _fetch_flights_serpapi(arr_code, dep_code, return_date)   # reversed direction
        if not air_ret:
            air_ret.append({
                "airline":  "No return flights found for this date — check airline portals directly",
                "duration": "N/A",
                "price":    "N/A",
                "departure": return_date,
            })


    # ── Ground / water transport variables ────────────────────────────────
    rail_results:  list = []
    road_results:  list = []
    water_results: list = []

    # ── 2. Trains (only if feasibility check confirmed availability) ──────

    if trains_available:
        try:
            train_data = serpapi_search({
                "engine": "google",
                "q": f"{origin} to {destination} train schedule fare IRCTC",
                "hl": "en",
                "gl": "in",
                "num": 6,
            })
            for r in train_data.get("organic_results", [])[:5]:
                title   = r.get("title", "").lower()
                snippet = r.get("snippet", "")
                link    = r.get("link", "")
                if any(kw in title for kw in ["train", "rail", "irctc", "express", "rajdhani", "shatabdi", "intercity"]):
                    rail_results.append({
                        "name":    r.get("title", "Train Service"),
                        "duration": "See schedule",
                        "price":   "Varies by class — check IRCTC",
                        "class":   "Sleeper / AC / General",
                        "details": snippet,
                        "link":    link,
                    })
            if not rail_results:
                # Still available but search returned no specific trains
                rail_results.append({
                    "name":    f"Train: {origin} to {destination}",
                    "duration": "Check IRCTC / local rail portal",
                    "price":   "Varies by class",
                    "class":   "Sleeper / AC",
                })
        except Exception as e:
            log("WARN", f"Train SerpAPI search error: {e}", C.YELLOW)
            rail_results.append({
                "name":    f"Train: {origin} to {destination}",
                "duration": "Check IRCTC",
                "price":   "Varies",
                "class":   "N/A",
            })
    else:
        rail_results.append({
            "name":    "No Train Service Available",
            "duration": "N/A",
            "price":   "N/A",
            "class":   "N/A",
            "details": f"Train travel between {origin} and {destination} is not possible "
                       f"(ocean/continent barrier or no rail connection confirmed by live search).",
        })

    # ── 3. Buses / Road (only if feasibility check confirmed availability) ─
    if buses_available:
        try:
            bus_data = serpapi_search({
                "engine": "google",
                "q": f"{origin} to {destination} bus KSRTC road cab taxi route",
                "hl": "en",
                "gl": "in",
                "num": 6,
            })
            for r in bus_data.get("organic_results", [])[:5]:
                title   = r.get("title", "").lower()
                snippet = r.get("snippet", "")
                link    = r.get("link", "")
                if any(kw in title for kw in ["bus", "ksrtc", "tnstc", "road", "drive", "cab", "taxi", "coach"]):
                    road_results.append({
                        "type":     "Bus / Cab" if "bus" in title or "ksrtc" in title else "Self-drive / Cab",
                        "duration": "Depends on route & traffic",
                        "price":    "Varies — check operator portals",
                        "operator": r.get("title", "Road Transport"),
                        "details":  snippet,
                        "link":     link,
                    })
            if not road_results:
                road_results.append({
                    "type":     "Bus / Self-drive",
                    "duration": "Check local bus operators",
                    "price":    "Varies",
                    "operator": "State / private bus operators",
                })
        except Exception as e:
            log("WARN", f"Bus/road SerpAPI search error: {e}", C.YELLOW)
            road_results.append({
                "type":     "Bus / Cab",
                "duration": "Check locally",
                "price":    "Varies",
                "operator": "N/A",
            })
    else:
        road_results.append({
            "type":     "No Bus/Road Route Available",
            "duration": "N/A",
            "price":    "N/A",
            "operator": "N/A",
            "details":  f"Road/bus travel between {origin} and {destination} is not possible "
                        f"(ocean/continent barrier or no road connection confirmed by live search).",
        })

    # ── 4. Ferry / boat (search regardless — only add if found) ──────────
    try:
        ferry_data = serpapi_search({
            "engine": "google",
            "q": f"{origin} to {destination} ferry boat cruise ship route",
            "hl": "en",
            "gl": "us",
            "num": 4,
        })
        for r in ferry_data.get("organic_results", [])[:4]:
            title   = r.get("title", "").lower()
            snippet = r.get("snippet", "")
            if any(kw in title for kw in ["ferry", "boat", "cruise", "ship", "sea route"]):
                water_results.append({
                    "type":     "Ferry / Boat / Cruise",
                    "duration": "Varies",
                    "price":    "Varies — check operator",
                    "operator": r.get("title", "Waterway Transport"),
                    "details":  snippet,
                    "link":     r.get("link", ""),
                })
    except Exception as e:
        log("WARN", f"Ferry SerpAPI search error: {e}", C.YELLOW)

    return {
        # Outbound journey (origin → destination)
        "outbound": {
            "air":   air_out,
            "rail":  rail_results,
            "road":  road_results,
            "water": water_results,
        },
        # Return journey (destination → origin) — empty if no return_date supplied
        "return": {
            "air":   air_ret,
            "rail":  rail_results if trains_available else [{
                "name": "No Train Service Available", "duration": "N/A", "price": "N/A", "class": "N/A",
                "details": f"Train travel between {destination} and {origin} is not possible.",
            }],
            "road":  road_results if buses_available else [{
                "type": "No Bus/Road Route Available", "duration": "N/A", "price": "N/A", "operator": "N/A",
                "details": f"Road/bus travel between {destination} and {origin} is not possible.",
            }],
            "water": water_results,
        },
        # Keep legacy flat keys so existing code doesn't break
        "air":   air_out,
        "rail":  rail_results,
        "road":  road_results,
        "water": water_results,
    }


@tool
def tool_fetch_accommodations(location: str, budget: str, check_in: str = "", check_out: str = "") -> dict:
    """Fetches real-time hotel and accommodation options from Google Hotels via SerpAPI."""
    """Fetch 6 real hotel options from SerpAPI Google Hotels with stars and amenities."""
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
        "hl": "en",
    }
    data = serpapi_search(params)
    properties = data.get("properties", [])
    if not properties:
        properties = data.get("hotels", [])
    results = []
    # Fetch 6 options
    for h in properties[:6]:
        name = h.get("name") or h.get("title", "")
        if not name:
            continue
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
    if not results:
        log("WARN", f"No hotels found for '{location}' — {len(properties)} raw properties returned", C.YELLOW)
        return {"error": f"No hotel results found for {location}.",
                "hotels": [], "location": location, "budget": budget}
    log("OK", f"Hotels found: {len(results)} - top: '{results[0]['name']}' @ {results[0]['price']}/night", C.GREEN)
    return {"hotels": results, "location": location, "budget": budget}


@tool
def tool_fetch_restaurants(location: str, cuisine_preferences: str = "") -> dict:
    """Fetches top-rated restaurants, cafes, and dining options via Google Maps SerpAPI."""
    """Fetch 6 real restaurant/food options via SerpAPI Google Maps."""
    log("TOOL", f"fetch_restaurants -> location='{location}' cuisine='{cuisine_preferences}'", C.MAGENTA)
    query = f"best restaurants {cuisine_preferences} in {location}".strip()
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "hl": "en",
        "gl": "us",
    }
    data = serpapi_search(params)
    places = data.get("local_results", [])
    results = []
    # Return 6 options
    for r in places[:6]:
        name = r.get("title") or r.get("name", "")
        if not name:
            continue
        maps_link = f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}+{requests.utils.quote(r.get('address', location))}"
        
        # Extract or construct a famous dish tag
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
            "google_maps_link": maps_link,
            "distance_note": "Central location"
        })
    if not results:
        log("WARN", f"No restaurants found for '{location}'", C.YELLOW)
        return {"error": f"No restaurant results found for {location}.",
                "restaurants": [], "location": location, "cuisine": cuisine_preferences}
    log("OK", f"Restaurants found: {len(results)} - top: '{results[0]['restaurant']}' rating:{results[0]['rating']}", C.GREEN)
    return {"restaurants": results, "location": location, "cuisine": cuisine_preferences}


@tool
def tool_fetch_attractions(location: str, interests: str = "", duration_days: int = 5) -> dict:
    """Fetches top tourist attractions, activities, and points of interest via Google Maps SerpAPI."""
    """Fetch 8 real attractions and things to do via SerpAPI Google Maps."""
    log("TOOL", f"fetch_attractions -> location='{location}' interests='{interests}' days={duration_days}", C.MAGENTA)
    query = f"top tourist attractions {interests} in {location}".strip()
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "hl": "en",
        "gl": "us",
    }
    data = serpapi_search(params)
    places = data.get("local_results", [])
    results = []
    for a in places[:8]:
        name = a.get("title") or a.get("name", "")
        if not name:
            continue
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
    if not results:
        log("WARN", f"No attractions found for '{location}'", C.YELLOW)
        return {"error": f"No attraction results found for {location}.",
                "attractions": [], "location": location, "interests": interests, "duration_days": duration_days}
    log("OK", f"Attractions found: {len(results)} - top: '{results[0]['name']}' rating:{results[0]['rating']}", C.GREEN)
    return {"attractions": results, "location": location, "interests": interests, "duration_days": duration_days}


@tool
def tool_search_travel_info(query: str) -> dict:
    """Searches Google for general travel information, local customs, visa details, or weather."""
    """General travel information search via SerpAPI."""
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
    answer_box = data.get("answer_box", {})
    log("OK", f"Travel info: {len(results)} organic results returned", C.GREEN)
    return {"query": query, "results": results, "answer": answer_box}


@tool
def tool_generate_detailed_plan(destination: str, duration_days: int, budget: str, interests: str, transport_summary: str, stay_summary: str, food_summary: str, attraction_summary: str) -> dict:
    """Generates the final comprehensive day-by-day travel itinerary JSON using the gathered tool data."""
    """Use Groq to synthesize an extremely elaborate, day-by-day itinerary incorporating morning food, where to go, how to go, what to see, lunch, dinner, etc."""
    log("TOOL", f"generate_detailed_plan -> destination='{destination}' days={duration_days}", C.MAGENTA)
    client = Groq(api_key=GROQ_API_KEY)
    
    length_constraint = ""
    if duration_days > 5:
        length_constraint = f"\n- CRITICAL: Since this is a long trip ({duration_days} days), you MUST keep the activity, food, and transport text fields concise (maximum 15-20 words each) to avoid output token limit truncation (4096 tokens)."

    prompt = f"""You are an elite travel concierge. Your task is to generate a highly detailed, elaborate day-by-day plan for a {duration_days}-day trip to {destination}.
Confirmed Details:
- Budget: {budget}
- Interests: {interests}
- Transport context: {transport_summary}
- Stays available: {stay_summary}
- Dining available: {food_summary}
- Attractions available: {attraction_summary}
{length_constraint}

For EACH day (from day 1 to day {duration_days}), you must generate an extremely detailed hour-by-hour schedule.
Specifically, you must make a strong effort to incorporate ALL of the user's interests ({interests}) across the daily plans. Additionally, you should enrich the plan by mixing in a few of your own professional local recommendations (agent suggestions) that complement their trip style.

For each day, define:
1. Morning (what to do, morning breakfast spot/food, how to get there)
2. Lunch (where to eat lunch from the dining options, what signature dish to try, travel details)
3. Afternoon (attractions to visit, what to see, how to travel)
4. Dinner (where to eat dinner, local delicacies, how to travel)
5. Evening (relaxed walk, night views, or cultural show)

You must output a JSON list of days. Use this exact schema for the returned days array:
[
  {{
    "day": 1,
    "title": "Day Title",
    "morning": {{
      "time": "08:00 - 12:00",
      "activity": "Detailed activity description of what to see and do",
      "food": "Breakfast options or local cafe with specific recommendations",
      "transport": "Travel mode (e.g. Tuk-tuk, walking, taxi) and route/distance details"
    }},
    "lunch": {{
      "time": "12:30 - 14:00",
      "activity": "Lunch break description",
      "food": "Name of restaurant from food options, recommended dishes, rating",
      "transport": "Travel mode/route from morning spot to lunch location"
    }},
    "afternoon": {{
      "time": "14:30 - 17:30",
      "activity": "Detailed sightseeing or activity description",
      "food": "Afternoon snack, tea, or local street food options",
      "transport": "Travel mode/route from lunch spot to afternoon location"
    }},
    "dinner": {{
      "time": "18:00 - 20:00",
      "activity": "Dinner experience details",
      "food": "Name of dinner restaurant, must-try specialties",
      "transport": "Travel mode/route to dinner location"
    }},
    "evening": {{
      "time": "20:30 - 22:00",
      "activity": "Evening walks, views, night market, or relaxing events",
      "food": "Dessert, local drinks, or mocktails details",
      "transport": "Travel mode back to stay option"
    }}
  }}
]

Return ONLY the JSON list inside a ```json ``` code block. Keep it highly detailed, elaborate, and actionable. Do not use generic placeholders. Use the real names of restaurants and attractions from the summaries.
"""
    
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096
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


def get_system_prompt_gather() -> str:
    now = datetime.now()
    today_str = now.strftime("%A, %B %d, %Y")
    tomorrow = (now + timedelta(days=1)).strftime("%B %d")
    after_2 = (now + timedelta(days=2)).strftime("%B %d")
    next_week = (now + timedelta(days=7)).strftime("%B %d")
    
    return f"""You are VoyageAgent, a professional and expert AI travel planning assistant.
The current local date is: {today_str}.

## STRICT PROFESSIONAL PERSONA RULE:
- You MUST maintain a strictly professional, polite, and helpful tone at all times.
- Under NO circumstances should you act unprofessionally or speak using terms of endearment (e.g. "sweetheart", "darling", "honey", "my friend", "bro"). 
- Treat every user with respect and formal courtesy.

## STRICT TOPIC GUARDRAIL:
- You are a TRAVEL PLANNER ONLY. You must STRICTLY refuse to answer ANY question or prompt that is not directly related to planning a trip.
- If the user asks about general knowledge, history, politics, people, programming, or anything else outside of travel planning, you must reply: "I am a travel assistant. I can only help you plan trips and vacations. How can I help you with your travel plans today?"
- DO NOT provide the answer to their out-of-context question before pivoting. Refuse the question entirely.

## YOUR GOAL:
Gather the following 7 required fields from the user naturally through conversation:
1. origin (City/Country they are leaving from)
2. destination (City/Country they want to go to)
3. duration_days (Number of days, an integer)
4. budget (low/budget, medium/mid-range, high/luxury, or specific numbers)
5. interests (e.g. adventure, food, relaxation, beaches, museums)
6. travel_dates (e.g. "next week", "June 2026", "flexible")
7. travelers (Number of people going)

## CRITICAL DATE RESOLUTION RULES:
- The current date is {today_str}.
- Never assume an exact date if the user provides a vague month or season (e.g., "June" -> just keep "June", do not invent a day).
- Resolve relative terms correctly based on {today_str}: "today" = {today_str} | "tomorrow" = {tomorrow} | "after 2 days" = {after_2} | "next week" = {next_week}.
- If the user says "next month", interpret it relative to {now.strftime("%B")}.
- Ensure the user's travel dates are mathematically possible given the duration.
- For example: "May 25 to May 27" cannot have duration 7 days.
- If duration doesn't match the dates provided, ask them to clarify either the dates or the duration!
- Reject any date in the past (prior to {today_str}). Say: "You cannot travel to the past! Please provide a current or future date."

## RESPONSE FORMAT RULES:
- If you are missing ANY of the 7 fields, ask a follow-up question. Do NOT assume fields.
- Keep your questions short, natural, and friendly. Do not just list bullet points asking for everything at once.
- NEVER invent information. If you don't know, ask the user.
- Once you have collected ALL 7 fields AND resolved any date/duration conflicts, you MUST call the `submit_trip_details` tool with the gathered information.
- Do NOT output any "READY_TO_PLAN" strings or JSON blocks manually. Just call the tool!
"""

def get_system_prompt_plan() -> str:
    now = datetime.now()
    today_str = now.strftime("%A, %B %d, %Y")
    
    return f"""You are VoyageAgent, an expert AI travel planning assistant. All required trip details have already been confirmed by the user. Your job now is to use the available tools to fetch real-time data and build a complete itinerary.
The current local date is: {today_str}.

## BUDGET DESIGN RULES:
- If the user says "low", "medium/mid", "luxury" budget, you must dynamically decide what the budget threshold is for the specific origin to destination combination:
  - Estimate the flight cost (e.g., Kochi to Paris flight is typically $500-$900 round trip).
  - Define local daily allowances (Low: $30-50/day, Mid: $100-180/day, Luxury: $300+/day).
  - Calculate a realistic target limit (e.g., for a 4-day low-budget trip to Paris from Kochi, the budget might be ~$800-$1000 total including flights, whereas a luxury trip would be $3000+).
- If the user specifies a particular total budget (e.g., "$1000 total"), select hotel, food, and activities such that the total estimated cost fits strictly within that range.
- Provide a clear cost estimation breakdown in the final JSON.

## INTERESTS & SUGGESTIONS MATCHING RULES:
- Carefully read every detail in the "interests" field — it contains the user's explicit activity wishes, restaurants, dishes, places, and plans.
- You MUST build the majority of the daily itinerary around these specific user suggestions (at least 70-80% of activities and meals should come from their stated interests).
- You may add only 1-2 of your own agent recommendations per day as supplementary options — clearly noted as "Agent Pick" — but they must not replace user-chosen items.
- Ensure the interests field is treated comprehensively: if the user mentioned kayaking, visiting a fort, eating at a specific place, or attending events, ALL of those must appear prominently in the plan.

## YOUR WORKFLOW FOR THIS PHASE:

**Step 1 - Call ALL relevant tools in this exact order:**
1. Call `check_route_feasibility` with origin and destination FIRST. Read the returned flags carefully:
   - `flights_available`, `trains_available`, `buses_available`, `ferry_available`
   - If trains_available=false or buses_available=false, those modes DO NOT EXIST for this route.
2. Call `fetch_transport_options` passing:
   - origin, destination
   - travel_date = first day of trip (YYYY-MM-DD)
   - return_date = last day of trip (YYYY-MM-DD)  ← ALWAYS pass this so return flights are fetched
   - trains_available and buses_available booleans from step 1
3. Call `fetch_accommodations` with the destination, budget, and dates.
4. Call `fetch_restaurants` with the destination and cuisine/food preferences.
5. Call `fetch_attractions` with the destination, interests, and duration.
6. Call `search_travel_info` for local tips, visa guidelines, currency, best time to visit etc.
7. Call `generate_detailed_plan` to synthesize an elaborate day-by-day plan. Pass text summaries of all the previous tool results so it has full context.

NEVER skip tool calls. NEVER invent transport options. NEVER fabricate flight times or prices.

**Step 2 - Generate the final response JSON:**
After ALL tools have returned results (including `generate_detailed_plan`), embed a complete itinerary inside ```json ... ``` markers.
IMPORTANT: To prevent token limit truncation and 429 rate limit issues, you MUST NOT include the raw arrays of transport_options, stay_options, food_options, or attractions in your final JSON output. The backend will automatically merge these from your SerpAPI tool results.
Only include the following fields in the final JSON:
```json
{
  "destination": "City, Country",
  "origin": "City, Country",
  "duration": "X Days",
  "budget": "Budget/Mid-Range/Luxury or specific range",
  "travel_dates": "Month Year",
  "travelers": 2,
  "cost_estimation": {
    "flight_cost_est": "$X total",
    "stay_cost_est": "$Y total ($Z/night)",
    "food_cost_est": "$W total",
    "attractions_cost_est": "$V total",
    "total_estimated_cost": "$Total"
  },
  "days": [
    // Output the detailed days structure returned by the generate_detailed_plan tool call.
  ],
  "travel_tips": ["tip1", "tip2", "tip3"]
}
```

## CRITICAL RULES:
- ONLY use real data returned by your tool calls. Never fabricate anything.
- Directly output the days structure returned by the `generate_detailed_plan` tool call in the "days" key. Do not simplify it.
- Be warm, enthusiastic, and make the itinerary feel premium and inspiring.
"""

# ─────────────────────────────────────────────
# LLM COMPRESSION HELPERS
# ─────────────────────────────────────────────

def compress_tool_result_for_llm(name: str, data: dict) -> str:
    """Creates a very concise version of tool results for the LLM to stay within Groq TPM limits."""
    try:
        if name == "fetch_transport_options":
            compressed = {}
            for mode in ["air", "rail", "road", "water"]:
                if mode in data:
                    compressed[mode] = []
                    for opt in data[mode][:2]:
                        compressed[mode].append({
                            "name": opt.get("airline") or opt.get("name") or opt.get("type"),
                            "price": opt.get("price"),
                            "duration": opt.get("duration")
                        })
            return json.dumps(compressed)
            
        elif name == "fetch_accommodations":
            hotels = data.get("hotels", [])
            compressed = []
            for h in hotels:
                compressed.append({
                    "name": h.get("name"),
                    "price": h.get("price"),
                    "rating": h.get("rating"),
                    "stars": h.get("stars")
                })
            return json.dumps({"hotels": compressed})
            
        elif name == "fetch_restaurants":
            restaurants = data.get("restaurants", [])
            compressed = []
            for r in restaurants:
                compressed.append({
                    "restaurant": r.get("restaurant"),
                    "famous_dish": r.get("famous_dish"),
                    "rating": r.get("rating")
                })
            return json.dumps({"restaurants": compressed})
            
        elif name == "fetch_attractions":
            attractions = data.get("attractions", [])
            compressed = []
            for a in attractions:
                compressed.append({
                    "name": a.get("name"),
                    "rating": a.get("rating"),
                    "highlights": a.get("highlights")
                })
            return json.dumps({"attractions": compressed})
    except Exception:
        pass
    raw = json.dumps(data)
    return raw[:600] + "..." if len(raw) > 600 else raw


# ─────────────────────────────────────────────
# AGENTIC CHAT LOOP — TWO-PHASE DESIGN
# ─────────────────────────────────────────────

def _classify_budget_tier(origin: str, destination: str, duration_days: int, travelers: int, raw_budget: str, api_key: str) -> str:
    """Classifies any non-standard budget string or numeric amount into 'low budget', 'mid budget', or 'luxury'."""
    clean = str(raw_budget).strip().lower()
    
    # Direct matching of standard keywords if no numbers are present
    if not any(char.isdigit() for char in clean):
        if any(kw in clean for kw in ["luxury", "high", "premium"]):
            return "luxury"
        if any(kw in clean for kw in ["mid", "medium", "standard", "moderate"]):
            return "mid budget"
        if any(kw in clean for kw in ["low", "budget"]):
            return "low budget"
            
    # If it contains digits or is unspecified/complex, classify it via LLM
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        prompt = f"""You are a travel budget analyst. A user is planning a trip with the following details:
- Origin: {origin}
- Destination: {destination}
- Duration: {duration_days} days
- Travelers: {travelers}
- Stated Budget/Amount: {raw_budget}

Determine which budget category this amount falls into for this specific trip: "low budget", "mid budget", or "luxury".
Consider typical flight costs between the origin and destination, hotel rates, and daily living expenses.
Respond with ONLY one of the following terms: "low budget", "mid budget", or "luxury". Do not include any punctuation or extra text."""

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
        
    # Standard fallbacks
    if any(kw in clean for kw in ["luxury", "high"]):
        return "luxury"
    if any(kw in clean for kw in ["mid", "medium", "standard", "moderate"]):
        return "mid budget"
    if any(kw in clean for kw in ["low", "budget"]):
        return "low budget"
    return "mid budget"


class TripDetails(BaseModel):
    """Call this tool when you have successfully gathered all 7 pieces of information from the user."""
    origin: str = Field(description="The city the user is departing from.")
    destination: str = Field(description="The city the user is traveling to.")
    duration_days: int = Field(description="Total duration of the trip in days.")
    budget: str = Field(description="Budget level: low, mid-range, or luxury.")
    interests: str = Field(description="Detailed comma-separated interests and activities.")
    travel_dates: str = Field(description="The exact or approximate dates of travel.")
    travelers: int = Field(description="Number of people traveling.")

def run_agent(messages: list, summary: str = None) -> tuple[str, list, dict | None, dict]:
    """
    Two-phase agentic loop:
      Phase 1: Info-gathering (no tools). Runs until the model emits READY_TO_PLAN.
      Phase 2: Tool-calling. Runs the full agentic SerpAPI loop with all tools enabled.
    Returns (final_text_response, list_of_tool_calls_made, gathered_info_or_None, tool_results_dict)
    """
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.startswith("gsk_your_dummy"):
        raise ValueError("GROQ_API_KEY is not configured. Please add your real Groq API key to the .env file.")

    client = Groq(api_key=api_key)
    tool_calls_made = []
    tool_results = {
        "transport_options": {},
        "stay_options": [],
        "food_options": [],
        "attractions": []
    }

    # ── PHASE 1: Info-Gathering (NO tools exposed to model) ──────────────────
    system_content = get_system_prompt_gather()
    if summary:
        system_content += f"\n\n## PREVIOUS CONVERSATION SUMMARY:\nNote: The user may be continuing a previous conversation. Here is a summary of what was discussed so far: {summary}"
    
    gather_messages = [{"role": "system", "content": system_content}]
    for m in messages[1:]:
        if m.get("role") in ("user", "assistant"):
            gather_messages.append({"role": m["role"], "content": m.get("content") or ""})

    divider("=", C.CYAN)
    log("PHASE", "PHASE 1 - Info gathering (no tools exposed to model)", C.YELLOW)
    log("INFO", f"History messages: {len(messages) - 2}", C.WHITE)

    log("AGENT", f"Calling Groq [{GROQ_MODEL}] for info-gathering turn...", C.MAGENTA)
    try:
        llm = ChatGroq(model=GROQ_MODEL, api_key=api_key, temperature=0.5, max_tokens=512)
        llm_with_tools = llm.bind_tools([TripDetails])
        
        # Convert raw dicts to LangChain BaseMessage objects to avoid `{}` formatting issues with raw JSON in prompt
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
        
        # Check if the model called the submit tool
        if getattr(gather_response, "tool_calls", None):
            for tc in gather_response.tool_calls:
                if tc["name"] == "TripDetails":
                    gathered_info = tc["args"]
                    
                    # Classify raw budget to a standardized tier (low, medium, luxury)
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
                            log("INFO", f"Phase 1 budget classification: '{raw_budget}' -> '{classified_budget}'", C.GREEN)
                        except Exception as e:
                            log("WARN", f"Phase 1 budget classification failed: {e}", C.YELLOW)
                    
                    # AI interpretation of interests for a more professional, inspiring presentation
                    raw_interests = gathered_info.get("interests", "")
                    if raw_interests:
                        try:
                            interpret_prompt = f"""You are an elite travel planner. Given the user's raw stated interests: "{raw_interests}"
Generate a brief, highly inspiring 1-sentence professional AI interpretation/description of their interests and the vibe they want for this trip.
Do not use preambles like "The user wants..." or "This trip is...". Start directly with the vibe and description, e.g., "A mix of outdoor water adventures like kayaking and deep-dives into local historical sites." or "A relaxing culinary getaway focused on fine dining, beach loungers, and vibrant local night markets."
Do not exceed 25 words."""
                            interpret_completion = client.chat.completions.create(
                                model="llama-3.1-8b-instant",
                                messages=[{"role": "user", "content": interpret_prompt}],
                                temperature=0.3,
                                max_tokens=60,
                            )
                            interpreted = interpret_completion.choices[0].message.content.strip().replace('"', '')
                            if len(interpreted) > 5:
                                gathered_info["interests"] = interpreted
                                log("INFO", f"Interpreted interests: '{raw_interests}' -> '{interpreted}'", C.GREEN)
                        except Exception as e:
                            log("WARN", f"Interests AI interpretation failed: {e}", C.YELLOW)

                    log("OK", f"All trip details collected via Structured Output: {json.dumps(gathered_info)}", C.GREEN)
                    log("INFO", "Trip details finalized! Halting for user confirmation card.", C.CYAN)
                    return "Please confirm or edit your travel details below.", [], gathered_info, tool_results
                    
    except Exception as e:
        log("WARN", f"Phase 1 LangChain ChatGroq call failed: {e}", C.YELLOW)
        raise ValueError("Groq servers are currently busy or unavailable. Please try again later.")

    log("INFO", f"Phase 1 response ({len(gather_text)} chars): {gather_text[:120].strip()}...", C.WHITE)
    log("INFO", "Still gathering info - returning conversational reply", C.CYAN)
    
    # Still gathering - return the conversational reply directly
    return gather_text, [], None, tool_results


from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Any

class AgentState(TypedDict):
    gathered_info: dict
    tool_results: dict
    final_text: str

def node_feasibility(state: AgentState):
    gi = state["gathered_info"]
    log("AGENT", "Node: check_route_feasibility", C.MAGENTA)
    res = tool_check_route_feasibility.invoke({"origin": gi.get("origin", ""), "destination": gi.get("destination", "")})
    state["tool_results"]["feasibility"] = res
    return state

def node_transport(state: AgentState):
    gi = state["gathered_info"]
    f = state["tool_results"].get("feasibility", {})
    log("AGENT", "Node: fetch_transport_options", C.MAGENTA)
    
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
        "origin": gi.get("origin", ""),
        "destination": gi.get("destination", ""),
        "travel_date": travel_date,
        "return_date": return_date,
        "flights_available": f.get("flights_available", True),
        "trains_available": f.get("trains_available", True),
        "buses_available": f.get("buses_available", True)
    })
    state["tool_results"]["transport_options"] = res
    return state

def node_stays(state: AgentState):
    gi = state["gathered_info"]
    log("AGENT", "Node: fetch_accommodations", C.MAGENTA)
    res = tool_fetch_accommodations.invoke({"location": gi.get("destination", ""), "budget": gi.get("budget", "")})
    state["tool_results"]["stay_options"] = res.get("hotels", [])
    return state

def node_food(state: AgentState):
    gi = state["gathered_info"]
    log("AGENT", "Node: fetch_restaurants", C.MAGENTA)
    res = tool_fetch_restaurants.invoke({"location": gi.get("destination", ""), "cuisine_preferences": gi.get("interests", "")})
    state["tool_results"]["food_options"] = res.get("restaurants", [])
    return state

def node_attractions(state: AgentState):
    gi = state["gathered_info"]
    log("AGENT", "Node: fetch_attractions", C.MAGENTA)
    res = tool_fetch_attractions.invoke({"location": gi.get("destination", ""), "interests": gi.get("interests", "")})
    state["tool_results"]["attractions"] = res.get("attractions", [])
    return state

def node_itinerary(state: AgentState):
    gi = state["gathered_info"]
    tr = state["tool_results"]
    log("AGENT", "Node: generate_detailed_plan", C.MAGENTA)
    
    # Compress the JSON to prevent Groq TPM (Tokens Per Minute) limit errors
    compact_stays = [{"name": s.get("name"), "price": s.get("price")} for s in tr.get("stay_options", [])[:3]]
    compact_food = [{"name": f.get("restaurant") or f.get("name"), "rating": f.get("rating"), "type": f.get("type")} for f in tr.get("food_options", [])[:5]]
    compact_attractions = [{"name": a.get("name"), "type": a.get("type"), "fee": a.get("entry_fee")} for a in tr.get("attractions", [])[:5]]
    
    # Pack everything and send to tool_generate_detailed_plan
    res = tool_generate_detailed_plan.invoke({
        "destination": gi.get("destination", ""),
        "duration_days": int(gi.get("duration_days", 1)),
        "budget": gi.get("budget", ""),
        "interests": gi.get("interests", ""),
        "transport_summary": json.dumps(tr.get("transport_options", {})),
        "stay_summary": json.dumps(compact_stays),
        "food_summary": json.dumps(compact_food),
        "attraction_summary": json.dumps(compact_attractions)
    })
    
    # Store the final text separately just for debugging or direct use, but tool_results gets the days
    state["final_text"] = "Your detailed trip plan is ready!"
    
    # Notice: we must merge into a final `days` object for the frontend
    state["tool_results"]["days"] = res.get("days", [])
    return state

def run_phase_2(gathered_info: dict) -> tuple[str, list, dict, dict]:
    """Runs Phase 2 (tool calling) using a deterministically executed LangGraph StateGraph."""
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.startswith("gsk_your_dummy"):
        raise ValueError("GROQ_API_KEY is not configured. Please add your real Groq API key to the .env file.")

    # Classify raw budget to a standardized tier (low, medium, luxury) if not already classified or edited manually
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
            log("INFO", f"Phase 2 budget classification: '{raw_budget}' -> '{classified_budget}'", C.GREEN)
        except Exception as e:
            log("WARN", f"Phase 2 budget classification failed: {e}", C.YELLOW)

    # Perform strict parameter validation
    travelers = int(gathered_info.get("travelers", 1))
    if travelers <= 0:
        raise ValueError("Number of travelers must be 1 or more.")

    travel_dates = str(gathered_info.get("travel_dates", "")).strip()
    try:
        import re
        date_match = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', travel_dates)
        if date_match:
            yr, mo, dy = map(int, date_match.groups())
            resolved_dt = datetime(yr, mo, dy)
            base_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if resolved_dt < base_dt:
                raise ValueError("You cannot travel to the past! Please provide a current or future date.")
    except ValueError as ve:
        raise ve
    except Exception:
        pass

    divider("=", C.CYAN)
    log("PHASE", "PHASE 2 - Deterministic StateGraph pipeline starting", C.YELLOW)
    log("INFO", f"Origin={gathered_info.get('origin')} | Destination={gathered_info.get('destination')} | Duration={gathered_info.get('duration_days')}d | Budget={gathered_info.get('budget')} | Travelers={gathered_info.get('travelers')}", C.WHITE)

    # Build StateGraph
    builder = StateGraph(AgentState)
    builder.add_node("feasibility", node_feasibility)
    builder.add_node("transport", node_transport)
    builder.add_node("stays", node_stays)
    builder.add_node("food", node_food)
    builder.add_node("attractions", node_attractions)
    builder.add_node("itinerary", node_itinerary)

    # Define edges - perfectly sequential execution
    builder.add_edge(START, "feasibility")
    builder.add_edge("feasibility", "transport")
    builder.add_edge("transport", "stays")
    builder.add_edge("stays", "food")
    builder.add_edge("food", "attractions")
    builder.add_edge("attractions", "itinerary")
    builder.add_edge("itinerary", END)

    graph = builder.compile()

    # Initial state
    initial_state = {
        "gathered_info": gathered_info,
        "tool_results": {
            "transport_options": {},
            "stay_options": [],
            "food_options": [],
            "attractions": []
        },
        "final_text": ""
    }

    log("AGENT", "Executing compiled LangGraph sequence...", C.MAGENTA)
    try:
        final_state = graph.invoke(initial_state)
        
        # We don't have LLM "tool_calls_made" logs to return, so we return a mock list
        mock_tool_calls_made = [
            {"name": "tool_check_route_feasibility", "args": {}},
            {"name": "tool_fetch_transport_options", "args": {}},
            {"name": "tool_fetch_accommodations", "args": {}},
            {"name": "tool_fetch_restaurants", "args": {}},
            {"name": "tool_fetch_attractions", "args": {}},
            {"name": "tool_generate_detailed_plan", "args": {}}
        ]

        return final_state["final_text"], mock_tool_calls_made, gathered_info, final_state["tool_results"]
    except Exception as e:
        log("WARN", f"Phase 2 StateGraph execution failed: {e}", C.YELLOW)
        raise ValueError("Groq servers are currently busy or unavailable. Please try again later.")


# ─────────────────────────────────────────────
# BACKGROUND SUMMARIZATION
# ─────────────────────────────────────────────

def update_chat_metadata(session_id: str):
    """
    Runs in a background thread. Takes the entire session history (up to last 10 messages)
    from the database, uses the Groq LLM to generate a 2-3 word title and a 50-word summary,
    then updates Supabase.
    """
    if not supabase or session_id == "local-dummy-id":
        return

    try:
        # Check if we've already done an update recently
        session_data = supabase.table("chat_sessions").select("title", "summary").eq("id", session_id).execute()
        if not session_data.data:
            return
            
        current_title = session_data.data[0].get("title", "New Travel Plan")
        
        # Query latest 10 messages directly from Supabase
        msg_res = supabase.table("messages").select("role, content").eq("session_id", session_id).order("created_at", desc=True).limit(10).execute()
        if not msg_res.data:
            return
            
        # Reverse to chronological order
        msgs = list(reversed(msg_res.data))
        chat_text = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in msgs])
        
        prompt = f"""You are a summarization assistant. Given the following chat log between a user and a travel planner, generate a JSON object with two fields:
1. "title": A 2 to 3 word highly descriptive title for this conversation (e.g., "Paris Summer Trip", "Tokyo Budget Getaway"). Never exceed 3 words.
2. "summary": A dense summary of the conversation up to 50 words. Focus on the destination, budget, dates, and what has been decided so far.

Chat Log:
{chat_text}

Output ONLY raw valid JSON like {{"title": "...", "summary": "..."}}. Do not use markdown blocks."""

        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key.startswith("gsk_your_dummy"):
            return

        from groq import Groq
        client = Groq(api_key=api_key)
        
        # Try primary model, fall back to llama-3.1-8b-instant if needed
        try:
            completion = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=150,
            )
        except Exception:
            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=150,
            )
        
        response = completion.choices[0].message.content.strip()
        try:
            import json
            if response.startswith("```json"):
                response = response[7:]
            if response.endswith("```"):
                response = response[:-3]
            data = json.loads(response.strip())
            
            update_payload = {"summary": data.get("summary", "")}
            if current_title == "New Travel Plan" and data.get("title"):
                update_payload["title"] = data["title"]
                
            supabase.table("chat_sessions").update(update_payload).eq("id", session_id).execute()
            log("INFO", f"Successfully updated session {session_id} metadata (Title: {data.get('title')})", C.GREEN)
        except Exception as e:
            log("WARN", f"Failed to parse or update metadata: {e}", C.YELLOW)

    except Exception as e:
        log("WARN", f"Background metadata thread failed: {e}", C.YELLOW)


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    # Clear the just_logged_in flag if present, but keep the session active
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

@app.route('/api/account/details', methods=['GET'])
def get_account_details():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    if not supabase:
        return jsonify({
            "username": session.get("username", "Siva"),
            "email": "siva@gmail.com"
        }), 200
        
    try:
        user_id = session.get("user_id")
        res = supabase.table("users").select("username, email").eq("id", user_id).execute()
        if not res.data:
            return jsonify({"error": "User not found."}), 404
        return jsonify(res.data[0]), 200
    except Exception as e:
        log("ERROR", f"Failed to fetch user details: {e}", C.RED)
        return jsonify({"error": "Database error."}), 500

@app.route('/api/account/send-otp', methods=['POST'])
def account_send_otp():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username:
        return jsonify({"error": "Username is required."}), 400

    user_email = ""
    if not supabase:
        user_email = "siva@gmail.com"
    else:
        try:
            user_id = session.get("user_id")
            res = supabase.table("users").select("email").eq("id", user_id).execute()
            if not res.data:
                return jsonify({"error": "User not found."}), 404
            user_email = res.data[0]["email"]
        except Exception as e:
            return jsonify({"error": "Database error."}), 500

    # Generate OTP
    otp = str(random.randint(100000, 999999))
    session["update_otp"] = otp
    session["update_username"] = username
    session["update_password"] = password
    session["update_email"] = user_email

    if not send_otp_email(user_email, otp, mode="update"):
        return jsonify({"error": "Failed to send verification email. Please verify your SMTP settings."}), 500
        
    return jsonify({"status": "success", "message": "Verification OTP sent."}), 200

@app.route('/api/account/verify-otp', methods=['POST'])
def account_verify_otp():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    otp = data.get("otp", "").strip()

    if not otp:
        return jsonify({"error": "OTP is required."}), 400

    saved_otp = session.get("update_otp")
    if not saved_otp or saved_otp != otp:
        return jsonify({"error": "Invalid or expired OTP."}), 400

    update_username = session.get("update_username")
    update_password = session.get("update_password")

    if not update_username:
        return jsonify({"error": "Session expired. Please try updating again."}), 400

    if not supabase:
        # Offline update
        session["username"] = update_username
        # Clean update sessions
        session.pop("update_otp", None)
        session.pop("update_username", None)
        session.pop("update_password", None)
        session.pop("update_email", None)
        return jsonify({"status": "success", "username": update_username, "message": "Account updated successfully!"}), 200

    try:
        user_id = session.get("user_id")
        update_payload = {"username": update_username}
        if update_password:
            update_payload["password_hash"] = update_password
            
        update_res = supabase.table("users").update(update_payload).eq("id", user_id).execute()
        if not update_res.data:
            return jsonify({"error": "Failed to update account. Please try again."}), 500

        # Success: update session username
        session["username"] = update_username
        
        # Clean update sessions
        session.pop("update_otp", None)
        session.pop("update_username", None)
        session.pop("update_password", None)
        session.pop("update_email", None)

        return jsonify({"status": "success", "username": update_username, "message": "Account updated successfully!"}), 200
    except Exception as e:
        log("ERROR", f"Failed to save account changes: {e}", C.RED)
        return jsonify({"error": "Database error. Please try again."}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────────
# SUPABASE DB API ROUTES
# ─────────────────────────────────────────────

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not supabase: return jsonify([]), 200
    try:
        user_id = session.get("user_id")
        res = supabase.table("chat_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return jsonify(res.data), 200
    except Exception as e:
        log("ERROR", f"Supabase fetch error: {e}", C.RED)
        return jsonify({"error": str(e)}), 500

@app.route('/api/sessions', methods=['POST'])
def create_session():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not supabase: return jsonify({"id": "local-dummy-id"}), 200
    try:
        user_id = session.get("user_id")
        res = supabase.table("chat_sessions").insert({"title": "New Travel Plan", "user_id": user_id}).execute()
        return jsonify(res.data[0]), 201
    except Exception as e:
        log("ERROR", f"Supabase insert error: {e}", C.RED)
        return jsonify({"error": str(e)}), 500

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not supabase: return jsonify({"status": "ok"}), 200
    try:
        user_id = session.get("user_id")
        # Verify ownership
        verify = supabase.table("chat_sessions").select("user_id").eq("id", session_id).execute()
        if not verify.data or verify.data[0].get("user_id") != user_id:
            return jsonify({"error": "Unauthorized"}), 403

        supabase.table("chat_sessions").delete().eq("id", session_id).execute()
        return jsonify({"status": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/sessions/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not supabase: return jsonify({"messages": [], "travel_plan": None}), 200
    try:
        user_id = session.get("user_id")
        # Verify ownership
        session_res = supabase.table("chat_sessions").select("user_id, travel_plan, gathered_info").eq("id", session_id).execute()
        if not session_res.data or session_res.data[0].get("user_id") != user_id:
            return jsonify({"error": "Unauthorized"}), 403

        travel_plan = session_res.data[0].get("travel_plan") if session_res.data else None
        gathered_info = session_res.data[0].get("gathered_info") if session_res.data else None
        
        msg_res = supabase.table("messages").select("*").eq("session_id", session_id).order("created_at").execute()
        return jsonify({
            "messages": msg_res.data,
            "travel_plan": travel_plan,
            "gathered_info": gathered_info
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/chat', methods=['POST'])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    history = data.get("history", [])
    confirmed_params = data.get("confirmed_params", None)

    if not user_message and not confirmed_params:
        return jsonify({"error": "Empty message"}), 400

    # Verify session ownership
    session_id = data.get("session_id")
    if supabase and session_id and session_id != "local-dummy-id":
        try:
            user_id = session.get("user_id")
            verify = supabase.table("chat_sessions").select("user_id").eq("id", session_id).execute()
            if verify.data and verify.data[0].get("user_id") != user_id:
                return jsonify({"error": "Unauthorized"}), 403
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    divider("-", C.CYAN)
    if confirmed_params:
        log("REQ", f"POST /chat | CONFIRM & PLAN | {json.dumps(confirmed_params)}", C.CYAN)
    else:
        log("REQ", f"POST /chat | msg='{user_message[:60]}{'...' if len(user_message)>60 else ''}' | history={len(history)} msgs", C.CYAN)

    def generate():
        try:
            session_id = data.get("session_id")
            fetched_summary = None
            if supabase and session_id and session_id != "local-dummy-id":
                try:
                    s_res = supabase.table("chat_sessions").select("summary").eq("id", session_id).execute()
                    if s_res.data:
                        fetched_summary = s_res.data[0].get("summary")
                except Exception:
                    pass

            if confirmed_params:
                response_text, tools_called, gathered_info, tool_results = run_phase_2(confirmed_params)
            else:
                messages = [{"role": "system", "content": "(phase managed internally)"}]
                # Manually implement the conversational buffer window (k=10 conversational turns = 20 messages)
                buffered_messages = history[-20:] if len(history) > 20 else history
                
                # Hydrate the messages array for the agent
                for msg in buffered_messages:
                    messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                
                messages.append({"role": "user", "content": user_message})
                response_text, tools_called, gathered_info, tool_results = run_agent(messages, summary=fetched_summary)

            if not gathered_info and "READY_TO_PLAN" in response_text:
                try:
                    g_start = response_text.index("```gathered") + 11
                    g_end = response_text.index("```", g_start)
                    gathered_info = json.loads(response_text[g_start:g_end].strip())
                except Exception:
                    pass

            itinerary = None
            display_text = response_text

            if tool_results and "days" in tool_results and tool_results["days"]:
                # Phase 2 now returns the parsed days directly in tool_results
                itinerary = {"days": tool_results["days"]}
                
                # Re-inject the metadata needed by the frontend banner
                if gathered_info:
                    itinerary["destination"] = gathered_info.get("destination", "Unknown")
                    itinerary["origin"] = gathered_info.get("origin", "Unknown")
                    itinerary["duration"] = f"{gathered_info.get('duration_days', 3)} Days"
                    itinerary["budget"] = gathered_info.get("budget", "Standard")

                for key in ["stay_options", "food_options", "attractions", "transport_options"]:
                    if key not in itinerary or not itinerary[key]:
                        itinerary[key] = tool_results.get(key, [] if key != "transport_options" else {})
            elif "```json" in response_text:
                idx = response_text.index("```json")
                display_text = response_text[:idx].strip()
                try:
                    json_start = idx + 7
                    if "```" in response_text[json_start:]:
                        json_end = response_text.index("```", json_start)
                        json_str = response_text[json_start:json_end].strip()
                    else:
                        json_str = response_text[json_start:].strip()
                    
                    itinerary = json.loads(json_str)
                    
                    for key in ["stay_options", "food_options", "attractions", "transport_options"]:
                        if key not in itinerary or not itinerary[key]:
                            itinerary[key] = tool_results.get(key, [] if key != "transport_options" else {})
                    
                    if not display_text:
                        display_text = (
                            f"Your complete {itinerary.get('duration', '')} itinerary for "
                            f"{itinerary.get('destination', '')} is ready! "
                            f"Check the right panel for your full plan."
                        )
                except Exception as e:
                    log("ERROR", f"Error parsing/merging itinerary JSON: {e}", C.RED)
                    if not display_text:
                        display_text = "I've generated your itinerary, but encountered an issue formatting it. Please try again."
                    yield json.dumps({"type": "text", "content": display_text}) + "\n"
                    yield json.dumps({"type": "itinerary", "content": None}) + "\n"
                    yield json.dumps({"type": "assistant_message", "content": {"role": "assistant", "content": display_text}}) + "\n"
                    return

            if "READY_TO_PLAN" in display_text:
                try:
                    rtp_idx = display_text.index("READY_TO_PLAN")
                    display_text = display_text[:rtp_idx].strip()
                except Exception:
                    pass
            if "```gathered" in display_text:
                try:
                    g_start = display_text.index("```gathered")
                    g_end = display_text.index("```", g_start + 11) + 3
                    display_text = (display_text[:g_start] + display_text[g_end:]).strip()
                except Exception:
                    pass

            log("DONE", f"Response ready | tools_called={[t['name'] for t in tools_called]} | itinerary={'YES' if itinerary else 'NO'}", C.GREEN)
            divider("-", C.CYAN)

            # Sync to Supabase in background logic
            session_id = data.get("session_id")
            if supabase and session_id and session_id != "local-dummy-id":
                try:
                    if user_message:
                        supabase.table("messages").insert({
                            "session_id": session_id,
                            "role": "user",
                            "content": user_message
                        }).execute()
                    
                    supabase.table("messages").insert({
                        "session_id": session_id,
                        "role": "assistant",
                        "content": display_text
                    }).execute()

                    # Update travel plan if we just generated it or gathered info
                    update_payload = {}
                    if itinerary:
                        update_payload["travel_plan"] = itinerary
                    if gathered_info:
                        update_payload["gathered_info"] = gathered_info
                    
                    if update_payload:
                        supabase.table("chat_sessions").update(update_payload).eq("id", session_id).execute()
                        
                    # Trigger background metadata generation (title/summary)
                    import threading
                    threading.Thread(target=update_chat_metadata, args=(session_id,)).start()

                except Exception as db_err:
                    log("ERROR", f"Failed to sync to Supabase: {db_err}", C.RED)

            chunk_size = 15
            for i in range(0, len(display_text), chunk_size):
                chunk = display_text[i:i+chunk_size]
                yield json.dumps({"type": "text", "content": chunk}) + "\n"
                time.sleep(0.015)

            yield json.dumps({"type": "itinerary", "content": itinerary}) + "\n"
            yield json.dumps({"type": "gathered_info", "content": gathered_info}) + "\n"
            
            # The assistant message to store in local history for UI context
            yield json.dumps({"type": "assistant_message", "content": {"role": "assistant", "content": display_text}}) + "\n"

        except ValueError as e:
            log("ERROR", f"ValueError in /chat: {e}", C.RED)
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"
        except Exception as e:
            import traceback
            log("ERROR", f"Unhandled exception in /chat: {e}", C.RED)
            traceback.print_exc()
            yield json.dumps({"type": "error", "content": f"Agent error: {str(e)}"}) + "\n"

    return Response(generate(), mimetype='application/x-ndjson')

def get_pdf_image(url, width=100, height=75):
    """Download image and return a ReportLab Image flowable, or None if download fails."""
    if not url or not url.startswith("http"):
        return None
    try:
        import hashlib
        h = hashlib.md5(url.encode()).hexdigest()
        temp_dir = os.path.join(os.path.dirname(__file__), "static", "temp_pdf_imgs")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"{h}.jpg")
        
        if not os.path.exists(temp_path):
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                with open(temp_path, "wb") as f:
                    f.write(r.content)
            else:
                return None
        from reportlab.platypus import Image as RLImage
        return RLImage(temp_path, width=width, height=height)
    except Exception as e:
        log("WARN", f"Failed to load image for PDF brochure: {e}", C.YELLOW)
        return None


@app.route('/download-pdf', methods=['POST'])
def download_pdf():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from reportlab.platypus import Table, TableStyle, KeepTogether
        data = request.get_json() or {}
        itinerary = data.get("itinerary", {})

        if not itinerary:
            return jsonify({"error": "No itinerary provided"}), 400

        dest = itinerary.get("destination", "Trip")
        duration = itinerary.get("duration", "")
        budget = itinerary.get("budget", "")
        tips = itinerary.get("travel_tips", [])

        filename = f"Itinerary_{dest.replace(' ', '_').replace(',', '')}.pdf"
        pdf_path = os.path.join(os.path.dirname(__file__), filename)

        # Standard margins for brochure style
        doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                                rightMargin=40, leftMargin=40,
                                topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('T', parent=styles['Heading1'],
                                     fontName='Helvetica-Bold', fontSize=24,
                                     textColor=colors.HexColor('#0f172a'), spaceAfter=4)
                                     
        meta_style = ParagraphStyle('M', parent=styles['Normal'],
                                    fontName='Helvetica-Bold', fontSize=10,
                                    textColor=colors.HexColor('#0284c7'), spaceAfter=14)
                                    
        h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
                                  fontName='Helvetica-Bold', fontSize=14,
                                  textColor=colors.HexColor('#0f172a'),
                                  spaceBefore=16, spaceAfter=8)
                                  
        body_style = ParagraphStyle('B', parent=styles['BodyText'],
                                    fontName='Helvetica', fontSize=10,
                                    textColor=colors.HexColor('#334155'),
                                    leading=14, spaceAfter=3)

        desc_style = ParagraphStyle('Desc', parent=styles['BodyText'],
                                    fontName='Helvetica-Oblique', fontSize=9,
                                    textColor=colors.HexColor('#475569'),
                                    leading=13)

        cost_style = ParagraphStyle('Cost', parent=styles['Normal'],
                                    fontName='Helvetica', fontSize=10,
                                    textColor=colors.HexColor('#1e293b'),
                                    leading=14)

        story = []
        
        # 1. Brochure Hero Header Banner
        banner_data = [
            [Paragraph(f"<b>VOYAGEAGENT ITINERARY</b>", ParagraphStyle('BText', parent=title_style, textColor=colors.white, fontSize=12, spaceAfter=0)), ""],
            [Paragraph(f"EXPLORE {dest.upper()}", ParagraphStyle('BTitle', parent=title_style, textColor=colors.white, fontSize=24, spaceAfter=0)), ""],
            [Paragraph(f"<b>Duration:</b> {duration}  |  <b>Budget target:</b> {budget}", ParagraphStyle('BMeta', parent=meta_style, textColor=colors.HexColor('#38bdf8'), spaceAfter=0)), ""]
        ]
        banner_table = Table(banner_data, colWidths=[400, 130])
        banner_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0f172a')),
            ('SPAN', (0,0), (1,0)),
            ('SPAN', (0,1), (1,1)),
            ('SPAN', (0,2), (1,2)),
            ('TOPPADDING', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
            ('LEFTPADDING', (0,0), (-1,-1), 20),
            ('RIGHTPADDING', (0,0), (-1,-1), 20),
        ]))
        story.append(banner_table)
        story.append(Spacer(1, 14))

        # 2. Cost Estimation Card
        cost_est = itinerary.get("cost_estimation", {})
        if cost_est:
            cost_html = (
                f"<b>💰 Estimated Budget Summary:</b><br/>"
                f"• Flight/Transport: {cost_est.get('flight_cost_est', 'N/A')} | "
                f"• Stays/Hotels: {cost_est.get('stay_cost_est', 'N/A')}<br/>"
                f"• Food & Dining: {cost_est.get('food_cost_est', 'N/A')} | "
                f"• Sightseeing & Entry: {cost_est.get('attractions_cost_est', 'N/A')}<br/>"
                f"<b>Total Estimated Trip Outlay: {cost_est.get('total_estimated_cost', 'N/A')}</b>"
            )
            cost_table = Table([[Paragraph(cost_html, cost_style)]], colWidths=[530])
            cost_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f0fdf4')),
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#bbf7d0')),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ('LEFTPADDING', (0,0), (-1,-1), 14),
                ('RIGHTPADDING', (0,0), (-1,-1), 14),
            ]))
            story.append(cost_table)
            story.append(Spacer(1, 10))

        # 3. Transport Details
        trans = itinerary.get("transport_options", {})
        if trans:
            story.append(Paragraph("RECOMMENDED TRANSPORT LINKS", h2_style))
            trans_rows = []
            for mode, options in trans.items():
                if options and isinstance(options, list):
                    # Filter placeholders
                    valid_opts = [o for o in options if o.get("price") != "Check online" and o.get("price") != "Varies" or "Flight" in str(o.values())]
                    opts_to_show = valid_opts if valid_opts else options
                    for opt in opts_to_show[:2]:
                        mode_icon = "✈️" if mode == "air" else "🚆" if mode == "rail" else "🚌"
                        opt_name = opt.get('airline') or opt.get('name') or opt.get('type') or "Standard Route"
                        price = opt.get('price', 'Varies')
                        duration = opt.get('duration', 'N/A')
                        trans_rows.append([
                            Paragraph(f"{mode_icon} <b>{opt_name}</b>", body_style),
                            Paragraph(f"⏱️ {duration}", body_style),
                            Paragraph(f"💵 <b>{price}</b>", body_style)
                        ])
            if trans_rows:
                t_table = Table(trans_rows, colWidths=[240, 150, 140])
                t_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
                ]))
                story.append(t_table)
            story.append(Spacer(1, 10))

        # 4. Stays Options (Styled Card Layout with Real Images)
        stays = itinerary.get("stay_options", [])
        if stays:
            story.append(Paragraph("ACCOMMODATION FEATURES", h2_style))
            for stay in stays[:3]:
                # Attempt to get real-time image
                img_flowable = get_pdf_image(stay.get("image"), width=90, height=65)
                
                # Format text
                try:
                    stars_val = int(float(stay.get("stars", 4)))
                except (ValueError, TypeError):
                    stars_val = 4
                stars = "★" * stars_val
                stars_txt = f"<font color='#eab308'>{stars}</font>"
                
                details_html = (
                    f"<b>{stay.get('name')}</b> {stars_txt}<br/>"
                    f"<font color='#0284c7' size='9'>📍 {stay.get('location', '')}</font> | "
                    f"<b>Rating:</b> {stay.get('rating', 'N/A')} ({stay.get('reviews', '')})<br/>"
                    f"<b>Tariff:</b> {stay.get('price', 'Varies')} / night<br/>"
                    f"<font color='#475569' size='8.5'><i>{stay.get('description', '')[:140]}...</i></font>"
                )
                
                # Layout side-by-side: Image left, details right
                card_data = []
                if img_flowable:
                    card_data = [[img_flowable, Paragraph(details_html, body_style)]]
                    col_widths = [100, 430]
                else:
                    card_data = [[Paragraph(details_html, body_style)]]
                    col_widths = [530]
                    
                card_table = Table(card_data, colWidths=col_widths)
                card_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
                    ('TOPPADDING', (0,0), (-1,-1), 8),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                    ('LEFTPADDING', (0,0), (-1,-1), 10),
                    ('RIGHTPADDING', (0,0), (-1,-1), 10),
                ]))
                story.append(KeepTogether([card_table, Spacer(1, 8)]))
            story.append(Spacer(1, 8))

        # 5. Day-by-Day proposed Schedule
        days = itinerary.get("days", [])
        if days:
            story.append(Paragraph("DETAILED TRAVEL PLANNER", h2_style))
            for d in days:
                day_num = d.get('day')
                day_title = d.get('title', f"Day {day_num}")
                
                # Day Banner
                day_banner = Table([[Paragraph(f"<b>DAY {day_num}: {day_title.upper()}</b>", ParagraphStyle('DBText', parent=title_style, textColor=colors.white, fontSize=11, spaceAfter=0))]], colWidths=[530])
                day_banner.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0284c7')),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('LEFTPADDING', (0,0), (-1,-1), 12),
                ]))
                
                # Daily Schedule Table Details
                schedule_rows = []
                periods = ["morning", "lunch", "afternoon", "dinner", "evening"]
                icons = {"morning": "☀️", "lunch": "🍴", "afternoon": "📸", "dinner": "🥂", "evening": "🌃"}
                
                for p in periods:
                    if d.get(p):
                        pdata = d[p]
                        act = pdata.get('activity', '')
                        food = pdata.get('food', '')
                        trans_details = pdata.get('transport', '')
                        
                        detail_txt = f"<b>Activity:</b> {act}"
                        if food:
                            detail_txt += f" | <b>Food:</b> {food}"
                        if trans_details:
                            detail_txt += f" | <b>Transit:</b> {trans_details}"
                            
                        schedule_rows.append([
                            Paragraph(f"{icons[p]} <b>{p.capitalize()}</b><br/><font color='#64748b' size='8'>{pdata.get('time', '')}</font>", body_style),
                            Paragraph(detail_txt, body_style)
                        ])
                        
                s_table = Table(schedule_rows, colWidths=[100, 430])
                s_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ffffff')),
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#f1f5f9')),
                    ('TOPPADDING', (0,0), (-1,-1), 8),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                    ('LEFTPADDING', (0,0), (-1,-1), 8),
                ]))
                
                story.append(day_banner)
                story.append(s_table)
                story.append(Spacer(1, 10))

        # 6. Travel Tips Page Break
        if tips:
            tip_story = []
            tip_story.append(Paragraph("VOYAGE CONCIERGE TIPS", h2_style))
            for tip in tips:
                tip_story.append(Paragraph(f"💡 {tip}", desc_style))
            story.append(KeepTogether(tip_story))

        doc.build(story)
        return send_file(pdf_path, as_attachment=True, download_name=filename)

    except Exception as e:
        import traceback
        log("ERROR", f"PDF Brochure generation failed: {e}", C.RED)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
