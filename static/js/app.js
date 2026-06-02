document.addEventListener("DOMContentLoaded", () => {
    const chatForm = document.getElementById("chatForm");
    const userInput = document.getElementById("userInput");
    const chatFeed = document.getElementById("chatFeed");
    const btnNewChat = document.getElementById("btn-new-chat");

    let history = []; // Chat history array to maintain context

    // Reset Chat action
    btnNewChat.addEventListener("click", () => {
        chatFeed.innerHTML = `
            <div class="chat-bubble bot">
                <p>Chat reset! Tell me about your dream getaway (destination, budget level, travel dates, travelers, and interests) to plan your perfect trip.</p>
            </div>
        `;
        history = [];
        userInput.disabled = false;
        userInput.focus();
    });

    // Helper: Local Date Formatting to prevent timezone shifting
    function formatLocalYYYYMMDD(dateObj) {
        const yyyy = dateObj.getFullYear();
        const mm = String(dateObj.getMonth() + 1).padStart(2, '0');
        const dd = String(dateObj.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    // Helper: Print a message bubble to the screen
    function appendBubble(sender, text) {
        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${sender}`;
        bubble.innerHTML = `<p>${text.replace(/\n/g, "<br>")}</p>`;
        chatFeed.appendChild(bubble);
        chatFeed.scrollTop = chatFeed.scrollHeight;
    }

    // Helper: Append typing indicator
    function appendTypingIndicator() {
        const indicator = document.createElement("div");
        indicator.className = "chat-bubble bot typing-wrapper";
        indicator.style.padding = "10px 14px";
        indicator.innerHTML = `
            <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </div>
        `;
        chatFeed.appendChild(indicator);
        chatFeed.scrollTop = chatFeed.scrollHeight;
        return indicator;
    }

    // Handles user message submissions
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const message = userInput.value.trim();
        if (!message) return;

        appendBubble("user", message);
        userInput.value = "";

        const typingIndicator = appendTypingIndicator();

        try {
            const response = await fetch("/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message, history })
            });

            typingIndicator.remove();

            if (!response.ok) {
                appendBubble("bot", "Oops! I encountered an error communicating with the backend. Please try again.");
                return;
            }

            const data = await response.json();
            
            if (data.status === "confirming") {
                renderConfirmationCard(data.gathered_info);
            } else if (data.status === "gathering") {
                appendBubble("bot", data.message);
                history.push({ role: "user", content: message });
                history.push({ role: "assistant", content: data.message });
            }
        } catch (err) {
            typingIndicator.remove();
            appendBubble("bot", "Network error. Make sure the backend Flask app is running.");
        }
    });

    // Renders the interactive parameter confirmation card
    function renderConfirmationCard(info) {
        const card = document.createElement("div");
        card.className = "param-confirm-card";

        // Dynamically initialize dates based on current local date and duration
        const todayObj = new Date();
        let defaultStart = formatLocalYYYYMMDD(todayObj);

        const initialDays = parseInt(info.duration_days) || 3;
        const endDtObj = new Date(todayObj);
        endDtObj.setDate(endDtObj.getDate() + initialDays - 1);
        let defaultEnd = formatLocalYYYYMMDD(endDtObj);

        if (info.travel_dates) {
            const matches = info.travel_dates.match(/\b\d{4}-\d{2}-\d{2}\b/g);
            if (matches && matches.length > 0) {
                defaultStart = matches[0];
                if (matches.length > 1) {
                    defaultEnd = matches[1];
                } else {
                    const days = parseInt(info.duration_days) || 3;
                    const startDt = new Date(defaultStart);
                    startDt.setDate(startDt.getDate() + days - 1);
                    defaultEnd = formatLocalYYYYMMDD(startDt);
                }
            } else {
                try {
                    let cleanedDates = info.travel_dates;
                    cleanedDates = cleanedDates.replace(/\b(\d+)(st|nd|rd|th)\b/g, "$1");
                    cleanedDates = cleanedDates.replace(/\bof\b/gi, "");
                    
                    let parts = cleanedDates.split(/\bto\b|\band\b| - /i);
                    let parsedStart = Date.parse(parts[0].trim());
                    if (!isNaN(parsedStart)) {
                        const startDt = new Date(parsedStart);
                        const baseDt = new Date();
                        baseDt.setHours(0, 0, 0, 0);
                        const finalStart = startDt < baseDt ? baseDt : startDt;
                        defaultStart = formatLocalYYYYMMDD(finalStart);

                        const days = parseInt(info.duration_days) || 3;
                        if (parts.length > 1) {
                            let parsedEnd = Date.parse(parts[1].trim());
                            if (!isNaN(parsedEnd)) {
                                const endDt = new Date(parsedEnd);
                                const finalEnd = endDt < finalStart ? finalStart : endDt;
                                defaultEnd = formatLocalYYYYMMDD(finalEnd);
                            } else {
                                const numMatch = parts[1].trim().match(/^\d+$/);
                                if (numMatch) {
                                    const endDt = new Date(finalStart);
                                    endDt.setDate(parseInt(numMatch[0]));
                                    defaultEnd = formatLocalYYYYMMDD(endDt);
                                } else {
                                    const endDt = new Date(finalStart);
                                    endDt.setDate(endDt.getDate() + days - 1);
                                    defaultEnd = formatLocalYYYYMMDD(endDt);
                                }
                            }
                        } else {
                            const endDt = new Date(finalStart);
                            endDt.setDate(endDt.getDate() + days - 1);
                            defaultEnd = formatLocalYYYYMMDD(endDt);
                        }
                    }
                } catch (e) { }
            }
        }

        const dateRangeValue = `${defaultStart} to ${defaultEnd}`;

        card.innerHTML = `
            <h3><i class="fa-solid fa-clipboard-check"></i> Confirm Travel Details</h3>
            <div class="param-grid">
                <div class="param-field">
                    <label>Origin</label>
                    <input type="text" id="param-origin" value="${info.origin || ''}">
                </div>
                <div class="param-field">
                    <label>Destination</label>
                    <input type="text" id="param-destination" value="${info.destination || ''}">
                </div>
                <div class="param-field">
                    <label>Dates</label>
                    <input type="text" id="param-dates" value="${dateRangeValue}">
                </div>
                <div class="param-field">
                    <label>Budget</label>
                    <select id="param-budget">
                        <option value="low budget" ${info.budget === 'low budget' ? 'selected' : ''}>Low</option>
                        <option value="mid budget" ${info.budget === 'mid budget' ? 'selected' : ''}>Mid-Range</option>
                        <option value="luxury" ${info.budget === 'luxury' ? 'selected' : ''}>Luxury</option>
                    </select>
                </div>
                <div class="param-field" style="grid-column: span 2;">
                    <label>Interests / Vibe</label>
                    <input type="text" id="param-interests" value="${info.interests || ''}">
                </div>
                <div class="param-field">
                    <label>Travelers</label>
                    <input type="number" id="param-travelers" value="${info.travelers || 1}">
                </div>
            </div>
            <div class="param-actions">
                <button class="param-btn edit" id="btn-reject-fresh"><i class="fa-solid fa-trash-can"></i> Restart</button>
                <button class="param-btn confirm" id="btn-confirm-plan"><i class="fa-solid fa-circle-check"></i> Build Plan</button>
            </div>
        `;

        chatFeed.appendChild(card);
        chatFeed.scrollTop = chatFeed.scrollHeight;

        // Button action: Restart
        card.querySelector("#btn-reject-fresh").addEventListener("click", () => {
            card.remove();
            btnNewChat.click();
        });

        // Button action: Confirm and Submit Plan
        card.querySelector("#btn-confirm-plan").addEventListener("click", async () => {
            const confirmed_params = {
                origin: card.querySelector("#param-origin").value,
                destination: card.querySelector("#param-destination").value,
                travel_dates: card.querySelector("#param-dates").value,
                budget: card.querySelector("#param-budget").value,
                interests: card.querySelector("#param-interests").value,
                travelers: parseInt(card.querySelector("#param-travelers").value) || 1,
            };

            // Calculate duration_days dynamically
            let calculatedDuration = 3;
            try {
                const parts = confirmed_params.travel_dates.split(/\bto\b|\band\b| - /i);
                const d1 = new Date(parts[0].trim());
                const d2 = new Date(parts[1].trim());
                const diffTime = Math.abs(d2 - d1);
                calculatedDuration = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
            } catch (e) {}
            confirmed_params.duration_days = calculatedDuration;

            card.remove();
            appendBubble("bot", `Great! Generating your ${confirmed_params.duration_days}-day itinerary for ${confirmed_params.destination}. Please wait...`);

            const typingIndicator = appendTypingIndicator();

            try {
                const response = await fetch("/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ confirmed_params })
                });

                typingIndicator.remove();

                if (!response.ok) {
                    appendBubble("bot", "Failed to build travel plan. Check your server console.");
                    return;
                }

                const data = await response.json();
                renderItinerarySummary(data.itinerary);
            } catch (err) {
                typingIndicator.remove();
                appendBubble("bot", "Network error. Failed to plan.");
            }
        });
    }

    // Formats and appends itinerary days inside the Chat UI
    function renderItinerarySummary(itinerary) {
        if (!itinerary || !itinerary.days || itinerary.days.length === 0) {
            appendBubble("bot", "No days generated in your itinerary.");
            return;
        }

        let summaryHtml = `<strong>🎉 Trip Plan Ready!</strong><br><br>`;
        
        itinerary.days.forEach(day => {
            summaryHtml += `<strong>Day ${day.day}: ${day.title || 'Sightseeing'}</strong><br>`;
            if (day.morning) summaryHtml += `• 🌅 Morning: ${day.morning.activity} (Food: ${day.morning.food})<br>`;
            if (day.lunch) summaryHtml += `• 🍔 Lunch: ${day.lunch.activity} (Food: ${day.lunch.food})<br>`;
            if (day.afternoon) summaryHtml += `• 🏛️ Afternoon: ${day.afternoon.activity}<br>`;
            if (day.dinner) summaryHtml += `• 🍲 Dinner: ${day.dinner.activity} (Food: ${day.dinner.food})<br>`;
            if (day.evening) summaryHtml += `• 🌙 Evening: ${day.evening.activity}<br>`;
            summaryHtml += `<br>`;
        });

        appendBubble("bot", summaryHtml);
    }

    // Optional: Fetch logged-in user details to display in console (Phase 1)
    async function checkAccountSession() {
        try {
            const res = await fetch("/api/account/details");
            if (res.ok) {
                const user = await res.json();
                console.log("Welcome back to VoyageAgent, " + user.username + "!");
            }
        } catch (e) {
            console.warn("User session is local or inactive.");
        }
    }
    checkAccountSession();
});
