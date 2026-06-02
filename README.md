# VoyageAgent: Agentic AI Travel Planner (Backend Core & Chat UI)

This repository contains the backend core and lightweight Chat UI of VoyageAgent, an AI-powered travel planning service. It features a conversational agent that gathers trip details from the user, uses a graph-based agent architecture to call live tools, and generates custom itineraries.

## Features
Interactive Chat UI: A clean, premium, minimal single-screen Chat UI where users can converse with VoyageAgent, edit their parameters interactively, and view daily summaries directly in the chat feed.

Parameter Gathering & Vibe Interpretation: AI chat agent collects travel details (origin, destination, budget, duration, interests, dates, and number of travelers) dynamically and interprets complex user interests into concise vibe descriptions.

Smart Budget Classifier: Integrates an LLM-based budget tier classification using `llama-3.1-8b-instant` to dynamically map custom text or numerical budget inputs into standard tiers.

Graph-Based Workflow: Built using LangGraph to execute travel queries in a deterministic, multi-node graph pipeline.

Live Search Tools: Connects to SerpAPI to fetch live transportation options (flights, train timetables, road transit), Google Hotels (with stars, pricing, reviews, images), and local Google Maps attractions/dining search.

Robust Itinerary Synthesis: Compiles a highly detailed hour-by-hour day-by-day plan using the Llama-3.3 model on Groq.

Output Truncation Prevention: Applies automatic prompt token limits for long trips (>5 days) and a brace-balancing parser fallback to guarantee a valid JSON response even if the LLM output is truncated.

Conversation memory: Supported via client-provided conversation history.

User Authentication & Session Database: Integrates Supabase as the data storage engine to handle authenticated user sessions and profiles.

Email Verification Service: Configured with standard SMTP servers to handle secure registration and password recovery verification codes.

## Technical Stack
* Language: Python 3
* Web Framework: Flask
* Database: Supabase DB (using python supabase client library)
* Email Client: SMTP Client (via `smtplib`)
* Agent Frameworks: LangGraph, LangChain Core
* LLM Provider: Groq Cloud (llama-3.3-70b-versatile, llama-3.1-8b-instant)
* Search APIs: SerpAPI (Google Flights, Google Hotels, Google Maps)

## Installation and Run Instructions

1. Clone the repository and navigate to the directory:
   ```bash
   cd voyageagent
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the root folder with the following variables:
   ```env
   GROQ_API_KEY=your_groq_api_key
   SERPAPI_API_KEY=your_serpapi_api_key
   
   # Database (Supabase)
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_key

   # Email OTP (SMTP Server configuration)
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your_gmail_username
   SMTP_PASSWORD=your_gmail_app_password
   SMTP_SENDER=your_sender_email
   ```

4. Run the Flask application:
   ```bash
   python app.py
   ```

5. Open your web browser and navigate to:
   ```
   http://localhost:5000/
   ```
