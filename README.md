# VoyageAgent: Agentic AI Travel Planner (Backend Core)

This repository contains the backend core of VoyageAgent, an AI-powered travel planning service. It features a conversational agent that gathers trip details from the user, uses a graph-based agent architecture to call live tools, and generates custom itineraries.

## Features
* Parameter Gathering: Chat agent that collects travel details (origin, destination, budget, duration, interests, dates, and number of travelers) dynamically.
* Graph-Based Workflow: Built using LangGraph to execute travel queries in a deterministic pipeline.
* Search Tools: Live queries using SerpAPI to retrieve transport route feasibility, flights, hotels, restaurants, and top attractions.
* Itinerary Generation: Combines tool results to compile an hour-by-hour day-by-day plan using the Llama-3.3 model on Groq.
* Conversation memory: Supported via client-provided conversation history.

## Technical Stack
* Language: Python 3
* Web Framework: Flask
* Agent Frameworks: LangGraph, LangChain Core
* LLM Provider: Groq Cloud (llama-3.3-70b-versatile)
* Search APIs: SerpAPI (Google Flights, Google Hotels, Google Maps)

## Installation and Run Instructions

1. Clone the repository and navigate to the directory:
   cd voyageagent

2. Install the required dependencies:
   pip install -r requirements.txt

3. Create a .env file in the root folder with the following variables:
   FLASK_SECRET_KEY=your_flask_secret
   GROQ_API_KEY=your_groq_api_key
   SERPAPI_API_KEY=your_serpapi_api_key

4. Run the Flask application:
   python app.py
