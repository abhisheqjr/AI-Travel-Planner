// Handles UI interactions, chatbot processing logs, rendering itinerary timeline boards, and triggering PDF download
document.addEventListener("DOMContentLoaded", () => {
    const chatForm = document.getElementById("chatForm");
    const userInput = document.getElementById("userInput");
    const chatFeed = document.getElementById("chatFeed");
    const displayWelcome = document.getElementById("displayWelcome");
    const itineraryWrapper = document.getElementById("itineraryWrapper");
    const itineraryTitle = document.getElementById("itineraryTitle");
    const itineraryDuration = document.getElementById("itineraryDuration");
    const itineraryBudget = document.getElementById("itineraryBudget");
    const itineraryCostEst = document.getElementById("itineraryCostEst");
    const transportGrid = document.getElementById("transportGrid");
    const hotelsGrid = document.getElementById("hotelsGrid");
    const foodGrid = document.getElementById("foodGrid");
    const attractionsGrid = document.getElementById("attractionsGrid");
    const timelineContainer = document.getElementById("timelineContainer");
    const downloadPdfBtn = document.getElementById("downloadPdfBtn");

    let activeItineraryData = null;
    let conversationHistory = [];
    let currentSessionId = localStorage.getItem("voyage_session_id") || null;

    // --- HISTORY SIDEBAR LOGIC ---
    const btnHistory = document.getElementById("btn-history");
    const btnNewChat = document.getElementById("btn-new-chat");
    const btnCloseHistory = document.getElementById("btn-close-history");
    const historyPanel = document.getElementById("history-panel");
    const historyList = document.getElementById("history-list");

    async function createNewSession() {
        try {
            const res = await fetch("/api/sessions", { method: "POST" });
            const data = await res.json();
            currentSessionId = data.id;
            localStorage.setItem("voyage_session_id", currentSessionId);
            historyPanel.classList.add("hidden");
            startFreshChat();
            loadHistoryList();
        } catch (e) { console.error("Session creation failed", e); }
    }

    async function loadHistoryList() {
        try {
            const res = await fetch("/api/sessions");
            const sessions = await res.json();
            historyList.innerHTML = "";
            if (sessions.length === 0) {
                historyList.innerHTML = "<p style='color:var(--text-secondary); text-align:center; padding: 20px;'>No past conversations</p>";
                return;
            }
            sessions.forEach(s => {
                const item = document.createElement("div");
                item.className = `session-item ${s.id === currentSessionId ? 'active' : ''}`;
                item.innerHTML = `
                    <div style="width: 80%">
                        <div class="session-title">${s.title}</div>
                        <div class="session-date">${new Date(s.created_at).toLocaleDateString()}</div>
                    </div>
                    <button class="btn-delete-session" data-id="${s.id}"><i class="fa-solid fa-trash"></i></button>
                `;
                item.addEventListener("click", (e) => {
                    if (e.target.closest('.btn-delete-session')) {
                        e.stopPropagation();
                        e.preventDefault();
                        showDeleteConfirmationModal(s.id, s.title);
                    } else {
                        loadSession(s.id);
                    }
                });
                historyList.appendChild(item);
            });
        } catch (e) { console.error(e); }
    }

    async function deleteSession(id) {
        try {
            console.log("Sending delete request to API for session:", id);
            const res = await fetch(`/api/sessions/${id}`, { method: "DELETE" });
            if (!res.ok) {
                const errData = await res.json();
                console.error("Delete call rejected by API:", errData.error);
                alert("Failed to delete session: " + (errData.error || res.statusText));
                return;
            }
            console.log("Delete call succeeded on server for session:", id);
            if (id === currentSessionId) {
                currentSessionId = null;
                localStorage.removeItem("voyage_session_id");
                startFreshChat();
            }
            loadHistoryList();
        } catch (e) {
            console.error("Delete network/fetch exception:", e);
            alert("Network error: Could not complete deletion.");
        }
    }

    function showDeleteConfirmationModal(sessionId, sessionTitle) {
        const overlay = document.createElement("div");
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: rgba(15, 23, 42, 0.4);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 99999;
            opacity: 0;
            transition: opacity 0.25s ease;
        `;

        const modal = document.createElement("div");
        modal.style.cssText = `
            background: rgba(255, 255, 255, 0.98);
            border: 1px solid rgba(226, 232, 240, 0.8);
            border-radius: 12px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
            width: 85%;
            max-width: 320px;
            padding: 18px;
            text-align: center;
            transform: scale(0.9);
            transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
            font-family: var(--font-body, 'Inter', sans-serif);
        `;

        modal.innerHTML = `
            <div style="background-color: #fee2e2; width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 12px;">
                <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444; font-size: 18px;"></i>
            </div>
            <h3 style="color: #0f172a; font-size: 15px; font-weight: 600; margin-bottom: 6px; margin-top: 0;">Delete Conversation</h3>
            <p style="color: #64748b; font-size: 12px; margin-bottom: 18px; line-height: 1.4; padding: 0 4px;">Are you sure you want to delete <strong>"${sessionTitle}"</strong>?.</p>
            <div style="display: flex; gap: 8px; justify-content: center;">
                <button id="btn-cancel-delete" style="flex: 1; padding: 8px 12px; border: 1px solid #e2e8f0; background: #ffffff; color: #334155; border-radius: 6px; font-weight: 500; font-size: 12px; cursor: pointer; transition: background-color 0.2s;">
                    Cancel
                </button>
                <button id="btn-confirm-delete" style="flex: 1; padding: 8px 12px; border: none; background: #ef4444; color: #ffffff; border-radius: 6px; font-weight: 500; font-size: 12px; cursor: pointer; transition: background-color 0.2s;">
                    Delete
                </button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        setTimeout(() => {
            overlay.style.opacity = "1";
            modal.style.transform = "scale(1)";
        }, 10);

        const closeModal = () => {
            overlay.style.opacity = "0";
            modal.style.transform = "scale(0.9)";
            setTimeout(() => {
                overlay.remove();
            }, 250);
        };

        const cancelBtn = modal.querySelector("#btn-cancel-delete");
        const confirmBtn = modal.querySelector("#btn-confirm-delete");

        cancelBtn.addEventListener("mouseover", () => cancelBtn.style.backgroundColor = "#f8fafc");
        cancelBtn.addEventListener("mouseout", () => cancelBtn.style.backgroundColor = "#ffffff");
        confirmBtn.addEventListener("mouseover", () => confirmBtn.style.backgroundColor = "#dc2626");
        confirmBtn.addEventListener("mouseout", () => confirmBtn.style.backgroundColor = "#ef4444");

        cancelBtn.addEventListener("click", closeModal);
        confirmBtn.addEventListener("click", async () => {
            closeModal();
            await deleteSession(sessionId);
        });

        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeModal();
        });
    }

    async function loadSession(id) {
        currentSessionId = id;
        localStorage.setItem("voyage_session_id", id);
        historyPanel.classList.add("hidden");

        chatFeed.innerHTML = "";
        conversationHistory = [];
        activeItineraryData = null;
        displayWelcome.style.display = "flex";
        itineraryWrapper.style.display = "none";

        try {
            const res = await fetch(`/api/sessions/${id}/messages`);
            const data = await res.json();

            // Rebuild chat
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(m => {
                    if (m.content && m.content.includes("Please confirm or edit your travel details")) {
                        return;
                    }
                    conversationHistory.push({ role: m.role, content: m.content });
                    appendRawMessage(m.role, m.content);
                });
            } else {
                startFreshChat();
            }

            // If there's a travel plan, inject the View Plan button to the last assistant bubble
            if (data.travel_plan) {
                appendViewPlanButton(data.travel_plan);
            }
            // Ensure user input is re-enabled to allow continuing the conversation in historic chats
            userInput.disabled = false;
            userInput.placeholder = "Tell me more about your preferences...";
            const sendBtn = document.getElementById("sendBtn");
            if (sendBtn) sendBtn.disabled = false;

            scrollToBottom();
            loadHistoryList();
        } catch (e) { console.error(e); }
    }

    function startFreshChat() {
        chatFeed.innerHTML = `
            <div class="chat-bubble bot">
                <p>Welcome! Tell me about your dream getaway (e.g., destination, budget, length, and interests) to build an amazing visual plan for you!</p>
            </div>
        `;
        conversationHistory = [];
        activeItineraryData = null;
        displayWelcome.style.display = "flex";
        itineraryWrapper.style.display = "none";
        userInput.disabled = false;
        userInput.placeholder = "E.g., 4 days in Paris on a mid-range budget...";
        document.getElementById("sendBtn").disabled = false;
    }

    function appendRawMessage(role, content) {
        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${role === 'user' ? 'user' : 'bot'}`;
        let htmlContent = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        bubble.innerHTML = `<p>${htmlContent}</p>`;
        chatFeed.appendChild(bubble);
    }

    btnHistory.addEventListener("click", () => {
        historyPanel.classList.toggle("hidden");
        if (!historyPanel.classList.contains("hidden")) loadHistoryList();
    });
    if (btnCloseHistory) btnCloseHistory.addEventListener("click", () => historyPanel.classList.add("hidden"));
    if (btnNewChat) {
        btnNewChat.addEventListener("click", () => {
            currentSessionId = null;
            localStorage.removeItem("voyage_session_id");
            historyPanel.classList.add("hidden");
            startFreshChat();
        });
    }

    // Always start a fresh chat session on page refresh/reload.
    // It will only be persisted in history/database when they send their first message.
    currentSessionId = null;
    localStorage.removeItem("voyage_session_id");
    startFreshChat();


    async function streamChatResponse(bodyData, finalStatus, logBox = null, card = null) {
        let botBubble = null;
        let textParagraph = null;
        let accumulatedResponse = "";

        let itinerary = null;
        let gatheredInfo = null;
        let assistantMessage = null;

        try {
            const response = await fetch("/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(bodyData)
            });

            if (!response.ok) {
                const errText = await response.text();
                let errMsg = "Failed to process chat response.";
                try {
                    const parsed = JSON.parse(errText);
                    errMsg = parsed.error || errMsg;
                } catch (e) { }
                throw new Error(errMsg);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;
                    const data = JSON.parse(line);
                    if (data.type === "text") {
                        if (!botBubble) {
                            if (finalStatus) finalStatus.remove();
                            botBubble = document.createElement("div");
                            botBubble.className = "chat-bubble bot";
                            textParagraph = document.createElement("p");
                            botBubble.appendChild(textParagraph);
                            chatFeed.appendChild(botBubble);
                        }
                        accumulatedResponse += data.content;
                        textParagraph.innerHTML = accumulatedResponse.replace(/\n/g, "<br>");
                        scrollToBottom();
                    } else if (data.type === "itinerary") {
                        itinerary = data.content;
                    } else if (data.type === "gathered_info") {
                        gatheredInfo = data.content;
                    } else if (data.type === "assistant_message") {
                        assistantMessage = data.content;
                    } else if (data.type === "error") {
                        throw new Error(data.content);
                    }
                }
            }

            if (finalStatus) finalStatus.remove();

            return {
                response: accumulatedResponse,
                itinerary: itinerary,
                gathered_info: gatheredInfo,
                assistant_message: assistantMessage
            };

        } catch (err) {
            console.error(err);
            if (finalStatus) finalStatus.remove();
            if (botBubble) {
                textParagraph.innerHTML += `<br><span style="color: #ef4444;"><i class="fa-solid fa-triangle-exclamation"></i> <strong>Error:</strong> ${err.message}</span>`;
            } else {
                appendBubble(`<i class="fa-solid fa-triangle-exclamation" style="color: #ef4444;"></i> <strong>Error:</strong> ${err.message}`, "bot");
            }
            throw err;
        }
    }

    // Submits new chat message
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = userInput.value.trim();
        if (!msg) return;

        // Render user bubble
        appendBubble(msg, "user");
        userInput.value = "";

        // Dynamically create a chat session in Supabase only when the first message is sent
        if (!currentSessionId) {
            try {
                console.log("Initializing session in Supabase dynamically on first message...");
                const sessionRes = await fetch("/api/sessions", { method: "POST" });
                if (!sessionRes.ok) throw new Error("Could not initialize session.");
                const sessionData = await sessionRes.json();
                currentSessionId = sessionData.id;
                localStorage.setItem("voyage_session_id", currentSessionId);
                console.log("Dynamic session initialized with ID:", currentSessionId);
            } catch (err) {
                console.error("Dynamic session initialization error:", err);
                appendBubble("System error: Could not initialize chat session. Please reload page.", "bot");
                return;
            }
        }

        // Check if message is a simple conversational greeting/thanks
        const msgLower = msg.toLowerCase();
        const greetings = ["hi", "hello", "hey", "hola", "sup", "greetings", "good morning", "good afternoon"];
        const thanks = ["thank you", "thanks", "tanks", "perfect", "awesome", "great", "cool", "ty"];
        const isConversational = greetings.some(g => msgLower.startsWith(g) || msgLower === g) ||
            thanks.some(t => msgLower.includes(t)) ||
            msgLower.length < 4;

        let logBox = null;
        let finalStatus = null;

        // Display brief typing loader for conversational flow
        finalStatus = document.createElement("div");
        finalStatus.className = "loading-status-text";
        finalStatus.style.padding = "10px 0";
        finalStatus.innerHTML = `<i class="fa-solid fa-ellipsis fa-bounce"></i> VoyageAgent is typing...`;
        chatFeed.appendChild(finalStatus);
        scrollToBottom();

        try {
            const data = await streamChatResponse({
                session_id: currentSessionId,
                message: msg,
                history: conversationHistory
            }, finalStatus);

            // Update history
            conversationHistory.push({ role: "user", content: msg });
            if (data.assistant_message) {
                conversationHistory.push(data.assistant_message);
            } else {
                conversationHistory.push({ role: "assistant", content: data.response });
            }

            if (data.gathered_info && Object.keys(data.gathered_info).length > 0) {
                renderConfirmationCard(data.gathered_info);
            }

            if (data.itinerary) {
                renderItinerary(data.itinerary);
                appendViewPlanButton(data.itinerary);
            }
        } catch (err) {
            console.error(err);
        }
    });

    // Renders the interactive parameter confirmation/edit card in chat
    function renderConfirmationCard(info) {
        const card = document.createElement("div");
        card.className = "param-confirm-card";

        function formatLocalYYYYMMDD(dateObj) {
            if (!dateObj || isNaN(dateObj.getTime())) return "";
            const yyyy = dateObj.getFullYear();
            const mm = String(dateObj.getMonth() + 1).padStart(2, '0');
            const dd = String(dateObj.getDate()).padStart(2, '0');
            return `${yyyy}-${mm}-${dd}`;
        }

        function parseCustomDate(dateStr) {
            if (!dateStr) return null;
            let s = dateStr.toLowerCase().trim();
            s = s.replace(/\b(\d+)(st|nd|rd|th)\b/g, "$1");
            s = s.replace(/\bof\b/gi, "");
            
            const months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
            const shortMonths = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
            
            let monthIdx = -1;
            for (let i = 0; i < 12; i++) {
                if (s.includes(months[i])) {
                    monthIdx = i;
                    s = s.replace(months[i], "");
                    break;
                }
            }
            if (monthIdx === -1) {
                for (let i = 0; i < 12; i++) {
                    if (s.includes(shortMonths[i])) {
                        monthIdx = i;
                        s = s.replace(shortMonths[i], "");
                        break;
                    }
                }
            }
            
            const dayMatch = s.match(/\b\d{1,2}\b/);
            if (monthIdx !== -1 && dayMatch) {
                const day = parseInt(dayMatch[0]);
                const yearMatch = s.match(/\b\d{4}\b/);
                const year = yearMatch ? parseInt(yearMatch[0]) : new Date().getFullYear();
                return new Date(year, monthIdx, day);
            }
            
            const parsed = Date.parse(dateStr);
            if (!isNaN(parsed)) {
                return new Date(parsed);
            }
            return null;
        }

        let defaultStart = "";
        let defaultEnd = "";

        if (info.travel_dates) {
            // Check for ISO date format YYYY-MM-DD
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
                    let parts = cleanedDates.split(/\bto\b|\band\b| - /i);
                    let startDt = parseCustomDate(parts[0]);
                    if (startDt && !isNaN(startDt.getTime())) {
                        // Prevent past dates relative to today
                        const today = new Date();
                        today.setHours(0, 0, 0, 0);
                        const finalStart = startDt < today ? today : startDt;
                        defaultStart = formatLocalYYYYMMDD(finalStart);

                        const days = parseInt(info.duration_days) || 3;
                        if (parts.length > 1) {
                            let endDt = parseCustomDate(parts[1]);
                            if (endDt && !isNaN(endDt.getTime())) {
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
                } catch (e) {
                    console.error("Custom date parsing failed", e);
                }
            }
        }

        // Calculate initial duration
        const startD = new Date(defaultStart);
        const endD = new Date(defaultEnd);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let initialDuration = "";
        if (!isNaN(startD) && !isNaN(endD) && startD >= today && endD >= today && startD <= endD) {
            initialDuration = Math.ceil((endD - startD) / (1000 * 60 * 60 * 24)) + 1;
        } else if (info.duration_days) {
            initialDuration = parseInt(info.duration_days);
        }

        card.innerHTML = `
            <h3><i class="fa-solid fa-square-poll-horizontal" style="color: var(--accent-blue);"></i> Confirm Trip Details</h3>
            <div class="param-form-grid">
                <div class="param-field">
                    <label>Origin</label>
                    <input type="text" id="param-origin" value="${info.origin || ''}">
                </div>
                <div class="param-field">
                    <label>Destination</label>
                    <input type="text" id="param-destination" value="${info.destination || ''}">
                </div>
                <div class="param-field">
                    <label>Travel Start Date</label>
                    <input type="date" id="param-start-date" value="${defaultStart}">
                </div>
                <div class="param-field">
                    <label>Travel End Date</label>
                    <input type="date" id="param-end-date" value="${defaultEnd}">
                </div>
                <div class="param-field">
                    <label>Duration (Calculated Days)</label>
                    <input type="number" id="param-duration" value="${initialDuration}" readonly style="background-color: #e2e8f0; cursor: not-allowed;">
                </div>
                <div class="param-field">
                    <label>Budget Level</label>
                    <select id="param-budget">
                        <option value="low budget" ${info.budget === 'low budget' || info.budget === 'budget' || info.budget === 'low' ? 'selected' : ''}>Low Budget</option>
                        <option value="mid budget" ${info.budget === 'mid budget' || info.budget === 'mid-range' || info.budget === 'medium' || info.budget === 'mid' ? 'selected' : ''}>Mid Budget</option>
                        <option value="luxury" ${info.budget === 'luxury' ? 'selected' : ''}>Luxury</option>
                    </select>
                </div>
                <div class="param-field">
                    <label>Interests</label>
                    <input type="text" id="param-interests" value="${info.interests || ''}">
                </div>
                <div class="param-field">
                    <label>Travelers</label>
                    <input type="number" id="param-travelers" value="${info.travelers || 1}">
                </div>
            </div>
            <div class="param-actions">
                <button class="param-btn edit" id="btn-reject-fresh" style="background-color: #ef4444; color: #ffffff;"><i class="fa-solid fa-trash-can"></i> Reject & Start Fresh</button>
                <button class="param-btn confirm" id="btn-confirm-plan"><i class="fa-solid fa-circle-check"></i> Confirm & Plan</button>
            </div>
        `;

        chatFeed.appendChild(card);
        scrollToBottom();

        const startDateInput = card.querySelector("#param-start-date");
        const endDateInput = card.querySelector("#param-end-date");
        const durationInput = card.querySelector("#param-duration");

        // Calculate and update duration days automatically when dates are changed
        function updateDuration() {
            const sDate = new Date(startDateInput.value);
            const eDate = new Date(endDateInput.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            if (!isNaN(sDate) && !isNaN(eDate)) {
                if (sDate < today || eDate < today || sDate > eDate) {
                    durationInput.value = "";
                } else {
                    const diffTime = eDate - sDate;
                    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
                    durationInput.value = diffDays > 0 ? diffDays : "";
                }
            } else {
                durationInput.value = "";
            }
        }

        startDateInput.addEventListener("change", updateDuration);
        endDateInput.addEventListener("change", updateDuration);

        // Disable user input to enforce interaction with confirmation card
        userInput.disabled = true;
        userInput.placeholder = "";
        document.getElementById("sendBtn").disabled = true;

        // Custom professional animated toast popup function
        function showToast(msg) {
            const toast = document.createElement("div");
            toast.style.cssText = `
                position: fixed;
                bottom: 24px;
                left: 50%;
                transform: translateX(-50%) translateY(20px);
                background: rgba(254, 242, 242, 0.95);
                color: #991b1b;
                padding: 12px 20px;
                border: 1px solid rgba(252, 165, 165, 0.6);
                border-radius: 8px;
                box-shadow: 0 10px 15px -3px rgba(220, 38, 38, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
                z-index: 99999;
                font-weight: 500;
                font-size: 13px;
                font-family: var(--font-body, 'Inter', sans-serif);
                display: flex;
                align-items: center;
                gap: 10px;
                opacity: 0;
                transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), opacity 0.3s ease;
            `;
            
            toast.innerHTML = `
                <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444; font-size: 14px;"></i>
                <span>${msg}</span>
            `;
            
            document.body.appendChild(toast);
            
            // Animate in
            setTimeout(() => {
                toast.style.opacity = "1";
                toast.style.transform = "translateX(-50%) translateY(0)";
            }, 10);
            
            // Animate out and remove
            setTimeout(() => {
                toast.style.opacity = "0";
                toast.style.transform = "translateX(-50%) translateY(20px)";
                setTimeout(() => { toast.remove(); }, 300);
            }, 4000);
        }

        // Confirm Action
        card.querySelector("#btn-confirm-plan").addEventListener("click", async () => {
            const travelersRaw = parseInt(card.querySelector("#param-travelers").value);
            const travelers = isNaN(travelersRaw) ? 0 : travelersRaw;

            const sDate = new Date(startDateInput.value);
            const today = new Date();
            today.setHours(0, 0, 0, 0);

            if (travelers <= 0) {
                showToast("Number of travelers must be 1 or more.");
                return;
            }
            if (isNaN(sDate) || sDate < today) {
                showToast("You cannot travel to the past! Please provide a valid current or future date.");
                return;
            }
            if (durationInput.value === "") {
                showToast("Invalid date range. End date must be on or after start date.");
                return;
            }

            const confirmedParams = {
                origin: card.querySelector("#param-origin").value.trim(),
                destination: card.querySelector("#param-destination").value.trim(),
                duration_days: parseInt(durationInput.value) || 3,
                budget: card.querySelector("#param-budget").value,
                interests: card.querySelector("#param-interests").value.trim(),
                travel_dates: `${startDateInput.value} to ${endDateInput.value}`,
                travelers: travelers
            };

            card.querySelector("#btn-confirm-plan").disabled = true;
            card.querySelector("#btn-confirm-plan").innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Planning...`;

            // Display tool running log sequence in feed
            const logBox = document.createElement("div");
            logBox.className = "tool-logs-container";
            chatFeed.appendChild(logBox);
            scrollToBottom();

            const logSteps = [
                { text: "Fetching Accommodations...", icon: "fa-hotel" },
                { text: "Finding Local Eats...", icon: "fa-utensils" },
                { text: "Identifying Hidden Gems...", icon: "fa-compass" }
            ];

            for (let step of logSteps) {
                const badge = document.createElement("div");
                badge.className = "tool-indicator-badge";
                badge.innerHTML = `
                    <span><i class="fa-solid ${step.icon}"></i> ${step.text}</span>
                    <i class="fa-solid fa-circle-notch fa-spin"></i>
                `;
                logBox.appendChild(badge);
                scrollToBottom();

                await new Promise(r => setTimeout(r, 800));

                badge.classList.add("completed");
                badge.innerHTML = `
                    <span><i class="fa-solid ${step.icon}"></i> ${step.text}</span>
                    <i class="fa-solid fa-check"></i>
                `;
            }

            const finalStatus = document.createElement("div");
            finalStatus.className = "loading-status-text";
            finalStatus.style.padding = "10px 0";
            finalStatus.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles fa-bounce"></i> Designing your itinerary...`;
            chatFeed.appendChild(finalStatus);
            scrollToBottom();

            try {
                const data = await streamChatResponse({
                    session_id: currentSessionId,
                    confirmed_params: confirmedParams
                }, finalStatus, logBox, card);

                if (data.itinerary) {
                    renderItinerary(data.itinerary);
                    appendViewPlanButton(data.itinerary);
                }
                // Disable parameters card inputs and buttons, update icon state
                card.querySelectorAll("input, select, button").forEach(el => {
                    el.disabled = true;
                });
                card.querySelector("#btn-confirm-plan").innerHTML = `<i class="fa-solid fa-circle-check"></i> Plan Generated`;
                
                // Re-enable chat inputs to let user send more messages
                userInput.disabled = false;
                userInput.placeholder = "Tell me more about your preferences...";
                const sendBtn = document.getElementById("sendBtn");
                if (sendBtn) sendBtn.disabled = false;
            } catch (err) {
                console.error(err);
                if (finalStatus) finalStatus.remove();
                logBox.remove();
                card.querySelector("#btn-confirm-plan").disabled = false;
                card.querySelector("#btn-confirm-plan").innerHTML = `<i class="fa-solid fa-circle-check"></i> Confirm & Plan`;
                
                // Re-enable chat inputs on error
                userInput.disabled = false;
                userInput.placeholder = "Tell me more about your preferences...";
                const sendBtn = document.getElementById("sendBtn");
                if (sendBtn) sendBtn.disabled = false;
            }
        });

        // Reject / Start fresh Action - preserves previous conversation history
        card.querySelector("#btn-reject-fresh").addEventListener("click", () => {
            // Re-enable inputs for user to continue typing
            userInput.disabled = false;
            userInput.placeholder = "E.g., 4 days in Paris on a mid-range budget...";
            const sendBtn = document.getElementById("sendBtn");
            if (sendBtn) sendBtn.disabled = false;

            // Deactivate parameters card buttons to prevent further actions on this card
            card.querySelectorAll("input, select, button").forEach(el => {
                el.disabled = true;
            });
            card.querySelector("#btn-reject-fresh").innerHTML = `<i class="fa-solid fa-ban"></i> Rejected`;
            card.querySelector("#btn-confirm-plan").disabled = true;

            // Ask questions again naturally without wiping history
            appendBubble("No problem! Let's adjust and refine your choices. What modifications would you like to make to the destination, budget, travel length, or interests?", "bot");
            userInput.focus();
        });
    }


    // Renders the main itinerary dashboard (5 sections scrollable)
    function renderItinerary(itinerary) {
        activeItineraryData = itinerary;

        // Swap welcome display with wrapper
        displayWelcome.classList.add("hidden");
        itineraryWrapper.classList.remove("hidden");
        displayWelcome.style.display = "none";
        itineraryWrapper.style.display = "block";

        // Title and meta
        itineraryTitle.textContent = `${itinerary.destination} (from ${itinerary.origin || 'your origin'})`;
        itineraryDuration.textContent = itinerary.duration || "5 Days";
        itineraryBudget.textContent = `Budget: ${itinerary.budget}`;

        if (itinerary.cost_estimation && itinerary.cost_estimation.total_estimated_cost) {
            itineraryCostEst.textContent = `Est. Cost: ${itinerary.cost_estimation.total_estimated_cost}`;
            itineraryCostEst.style.display = "inline-block";
        } else {
            itineraryCostEst.style.display = "none";
        }

        // 1. Render Transport Options (Outbound + Return)
        const returnTransportSection = document.getElementById("returnTransportSection");
        const returnTransportGrid = document.getElementById("returnTransportGrid");

        const trans = itinerary.transport_options || {};

        // Prefer structured outbound/return keys; fall back to flat keys for older responses
        const outbound = trans.outbound || { air: trans.air || [], rail: trans.rail || [], road: trans.road || [], water: trans.water || [] };
        const returnJ = trans.return || { air: [], rail: [], road: [], water: [] };

        const transportModes = [
            { key: "air", icon: "fa-plane", title: "Air Travel" },
            { key: "rail", icon: "fa-train", title: "Rail Travel" },
            { key: "road", icon: "fa-bus", title: "Road Travel" },
            { key: "water", icon: "fa-ship", title: "Water Travel" }
        ];

        function buildTransportCard(opt, mode) {
            const card = document.createElement("div");
            card.className = "transport-card";
            const title = opt.airline || opt.name || opt.type || mode.title;
            const duration = opt.duration || "Varies";
            const price = opt.price || "Check online";
            const details = opt.details || opt.departure || "Regular schedules apply";
            const arrival = opt.arrival ? `<p class="transport-detail"><i class="fa-solid fa-flag-checkered"></i> Arrives: ${opt.arrival}</p>` : "";

            const maxLen = 100;
            let displayDetails = details;
            let showViewMore = false;
            if (details.length > maxLen) {
                displayDetails = details.substring(0, maxLen) + "...";
                showViewMore = true;
            }

            card.innerHTML = `
                <div class="transport-mode-badge"><i class="fa-solid ${mode.icon}"></i></div>
                <h4 class="transport-name">${title}</h4>
                <p class="transport-detail"><i class="fa-solid fa-clock"></i> ${duration}</p>
                ${arrival}
                <p class="transport-detail transport-desc-p">
                    <span class="desc-text">${displayDetails}</span>
                    ${showViewMore ? ` <span class="view-more-link">View More</span>` : ""}
                </p>
                <div class="transport-price-row">
                    <span class="transport-price">${price}</span>
                    ${opt.link ? `<a href="${opt.link}" target="_blank" class="details-link">Book Now <i class="fa-solid fa-arrow-up-right-from-square"></i></a>` : ""}
                </div>
            `;

            if (showViewMore) {
                const descP = card.querySelector(".transport-desc-p");
                const descText = descP.querySelector(".desc-text");
                const viewMoreBtn = descP.querySelector(".view-more-link");

                viewMoreBtn.addEventListener("click", () => {
                    const isExpanded = descP.classList.contains("expanded");
                    if (isExpanded) {
                        descP.classList.remove("expanded");
                        descText.textContent = displayDetails;
                        viewMoreBtn.textContent = "View More";
                    } else {
                        descP.classList.add("expanded");
                        descText.textContent = details;
                        viewMoreBtn.textContent = "View Less";
                    }
                });
            }

            return card;
        }

        // Outbound grid
        transportGrid.innerHTML = "";
        let hasOutbound = false;
        transportModes.forEach(mode => {
            (outbound[mode.key] || []).forEach(opt => {
                hasOutbound = true;
                transportGrid.appendChild(buildTransportCard(opt, mode));
            });
        });
        if (!hasOutbound) {
            transportGrid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-secondary); text-align: center; padding: 20px;">No outbound transport options found.</p>`;
        }

        // Return grid
        const hasReturnData = transportModes.some(m => (returnJ[m.key] || []).length > 0);
        if (hasReturnData) {
            returnTransportGrid.innerHTML = "";
            let hasReturn = false;
            transportModes.forEach(mode => {
                (returnJ[mode.key] || []).forEach(opt => {
                    hasReturn = true;
                    returnTransportGrid.appendChild(buildTransportCard(opt, mode));
                });
            });
            returnTransportSection.style.display = hasReturn ? "block" : "none";
        } else {
            returnTransportSection.style.display = "none";
        }

        // 2. Render Stay Options (6 hotels)
        hotelsGrid.innerHTML = "";
        const hotels = itinerary.stay_options || [];
        hotels.forEach(hotel => {
            const card = document.createElement("div");
            card.className = "mini-hotel-card";

            let starsHtml = "";
            const starsCount = parseInt(hotel.stars) || 4;
            for (let i = 0; i < 5; i++) {
                starsHtml += `<i class="fa-solid fa-star" style="color: ${i < starsCount ? '#eab308' : '#e2e8f0'}"></i>`;
            }

            let amenitiesHtml = "";
            if (hotel.amenities && Array.isArray(hotel.amenities)) {
                hotel.amenities.forEach(am => {
                    amenitiesHtml += `<span class="amenity-chip">${am}</span>`;
                });
            }

            const desc = hotel.description || "";
            const maxLenHotel = 100;
            let displayDesc = desc;
            let showViewMoreHotel = false;
            if (desc.length > maxLenHotel) {
                displayDesc = desc.substring(0, maxLenHotel) + "...";
                showViewMoreHotel = true;
            }

            card.innerHTML = `
                <img src="${hotel.image || 'https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=600&q=80'}" alt="${hotel.name}" class="mini-hotel-img">
                <div class="mini-hotel-body">
                    <div class="mini-hotel-header">
                        <h4 class="mini-hotel-name">${hotel.name}</h4>
                        <div class="hotel-stars">${starsHtml}</div>
                    </div>
                    <p class="stay-loc"><i class="fa-solid fa-location-dot"></i> ${hotel.location}</p>
                    <p class="mini-hotel-price">${hotel.price} <span style="font-size: 11px; font-weight: normal; color: var(--text-secondary);">/ night</span></p>
                    <p class="mini-hotel-desc">
                        <span class="desc-text">${displayDesc}</span>
                        ${showViewMoreHotel ? ` <span class="view-more-link">View More</span>` : ""}
                    </p>
                    <div class="amenities-container">${amenitiesHtml}</div>
                    <div class="stay-footer" style="margin-top: auto; padding-top: 10px;">
                        <span class="rating-badge"><i class="fa-solid fa-star"></i> ${hotel.rating || 'N/A'}</span>
                        <span class="reviews-count">${hotel.reviews || ''}</span>
                        <a href="${hotel.google_maps_link || '#'}" target="_blank" class="details-link">View Details <i class="fa-solid fa-arrow-up-right-from-square"></i></a>
                    </div>
                </div>
            `;

            if (showViewMoreHotel) {
                const descP = card.querySelector(".mini-hotel-desc");
                const descText = descP.querySelector(".desc-text");
                const viewMoreBtn = descP.querySelector(".view-more-link");

                viewMoreBtn.addEventListener("click", () => {
                    const isExpanded = descP.classList.contains("expanded");
                    if (isExpanded) {
                        descP.classList.remove("expanded");
                        descText.textContent = displayDesc;
                        viewMoreBtn.textContent = "View More";
                    } else {
                        descP.classList.add("expanded");
                        descText.textContent = desc;
                        viewMoreBtn.textContent = "View Less";
                    }
                });
            }

            hotelsGrid.appendChild(card);
        });
        if (hotels.length === 0) {
            hotelsGrid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-secondary); text-align: center; padding: 20px;">No stay options found.</p>`;
        }

        // 3. Render Famous Food & Dining (6 restaurants)
        foodGrid.innerHTML = "";
        const dining = itinerary.food_options || [];
        dining.forEach(item => {
            const card = document.createElement("div");
            card.className = "mini-hotel-card";
            card.style.position = "relative";

            const desc = item.description || "";
            const maxLenFood = 100;
            let displayDesc = desc;
            let showViewMoreFood = false;
            if (desc.length > maxLenFood) {
                displayDesc = desc.substring(0, maxLenFood) + "...";
                showViewMoreFood = true;
            }

            card.innerHTML = `
                <span class="famous-dish-badge"><i class="fa-solid fa-fire"></i> ${item.famous_dish || 'Famous Platter'}</span>
                <img src="${item.image || 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=600&q=80'}" alt="${item.restaurant}" class="mini-hotel-img">
                <div class="mini-hotel-body">
                    <div class="mini-hotel-header" style="margin-top: 8px;">
                        <h4 class="mini-hotel-name">${item.restaurant}</h4>
                        <span class="rating-badge"><i class="fa-solid fa-star"></i> ${item.rating || 'N/A'}</span>
                    </div>
                    <p class="stay-loc"><i class="fa-solid fa-location-dot"></i> ${item.address}</p>
                    <p class="stay-loc" style="margin-top: 4px; color: var(--accent-cyan); font-weight: 500;"><i class="fa-solid fa-tags"></i> Price: ${item.price_range || '$$'}</p>
                    <p class="mini-hotel-desc">
                        <span class="desc-text">${displayDesc}</span>
                        ${showViewMoreFood ? ` <span class="view-more-link">View More</span>` : ""}
                    </p>
                    <div class="stay-footer" style="margin-top: auto; padding-top: 10px;">
                        <span class="reviews-count"><i class="fa-solid fa-map-pin"></i> ${item.distance_note || 'Central'}</span>
                        <a href="${item.google_maps_link || '#'}" target="_blank" class="details-link">View Details <i class="fa-solid fa-arrow-up-right-from-square"></i></a>
                    </div>
                </div>
            `;

            if (showViewMoreFood) {
                const descP = card.querySelector(".mini-hotel-desc");
                const descText = descP.querySelector(".desc-text");
                const viewMoreBtn = descP.querySelector(".view-more-link");

                viewMoreBtn.addEventListener("click", () => {
                    const isExpanded = descP.classList.contains("expanded");
                    if (isExpanded) {
                        descP.classList.remove("expanded");
                        descText.textContent = displayDesc;
                        viewMoreBtn.textContent = "View More";
                    } else {
                        descP.classList.add("expanded");
                        descText.textContent = desc;
                        viewMoreBtn.textContent = "View Less";
                    }
                });
            }

            foodGrid.appendChild(card);
        });
        if (dining.length === 0) {
            foodGrid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-secondary); text-align: center; padding: 20px;">No dining options found.</p>`;
        }

        // 4. Render Attractions (8 spots)
        attractionsGrid.innerHTML = "";
        const spots = itinerary.attractions || [];
        spots.forEach(spot => {
            const card = document.createElement("div");
            card.className = "attraction-card";

            let highlightsHtml = "";
            if (spot.highlights && Array.isArray(spot.highlights)) {
                spot.highlights.forEach(h => {
                    highlightsHtml += `<span class="highlight-chip">${h}</span>`;
                });
            }

            const desc = spot.description || "";
            const maxLenSpot = 100;
            let displayDesc = desc;
            let showViewMoreSpot = false;
            if (desc.length > maxLenSpot) {
                displayDesc = desc.substring(0, maxLenSpot) + "...";
                showViewMoreSpot = true;
            }

            card.innerHTML = `
                <img src="${spot.image || 'https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=600&q=80'}" alt="${spot.name}" class="attraction-img">
                <div class="attraction-body">
                    <div class="attraction-header">
                        <h4 class="attraction-name">${spot.name}</h4>
                        <span class="entry-fee-badge">${spot.entry_fee || 'Free'}</span>
                    </div>
                    <p class="stay-loc"><i class="fa-solid fa-location-dot"></i> ${spot.address}</p>
                    <p class="mini-hotel-desc" style="margin: 8px 0;">
                        <span class="desc-text">${displayDesc}</span>
                        ${showViewMoreSpot ? ` <span class="view-more-link">View More</span>` : ""}
                    </p>
                    <div class="highlights-container">${highlightsHtml}</div>
                    <div class="stay-footer" style="margin-top: auto; padding-top: 10px;">
                        <span class="rating-badge"><i class="fa-solid fa-star"></i> ${spot.rating || 'N/A'}</span>
                        <span class="reviews-count">${spot.reviews || ''} reviews</span>
                        <a href="${spot.google_maps_link || '#'}" target="_blank" class="details-link">View Details <i class="fa-solid fa-arrow-up-right-from-square"></i></a>
                    </div>
                </div>
            `;

            if (showViewMoreSpot) {
                const descP = card.querySelector(".mini-hotel-desc");
                const descText = descP.querySelector(".desc-text");
                const viewMoreBtn = descP.querySelector(".view-more-link");

                viewMoreBtn.addEventListener("click", () => {
                    const isExpanded = descP.classList.contains("expanded");
                    if (isExpanded) {
                        descP.classList.remove("expanded");
                        descText.textContent = displayDesc;
                        viewMoreBtn.textContent = "View More";
                    } else {
                        descP.classList.add("expanded");
                        descText.textContent = desc;
                        viewMoreBtn.textContent = "View Less";
                    }
                });
            }

            attractionsGrid.appendChild(card);
        });
        if (spots.length === 0) {
            attractionsGrid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-secondary); text-align: center; padding: 20px;">No attractions found.</p>`;
        }

        // 5. Build timeline (Proposed plan with rich period-based events)
        timelineContainer.innerHTML = "";
        itinerary.days.forEach((dayData) => {
            const item = document.createElement("div");
            item.className = "timeline-item";

            const periods = ["morning", "lunch", "afternoon", "dinner", "evening"];
            const periodIcons = {
                morning: "fa-sun",
                lunch: "fa-utensils",
                afternoon: "fa-compass",
                dinner: "fa-moon",
                evening: "fa-martini-glass-citrus"
            };

            let periodsHtml = "";
            periods.forEach(p => {
                if (dayData[p]) {
                    const data = dayData[p];
                    periodsHtml += `
                        <div class="day-period-row">
                            <div class="period-header">
                                <span class="period-title">
                                    <i class="fa-solid ${periodIcons[p]}"></i> ${p.toUpperCase()} (${data.time || ''})
                                </span>
                            </div>
                            <div class="period-body">
                                <p class="period-activity"><strong><i class="fa-solid fa-map-pin"></i> Activity:</strong> ${data.activity || 'Sightseeing'}</p>
                                ${data.food ? `<p class="period-food"><strong><i class="fa-solid fa-cookie-bite"></i> Food/Dining:</strong> ${data.food}</p>` : ''}
                                ${data.transport ? `<p class="period-transport"><strong><i class="fa-solid fa-route"></i> Transit:</strong> ${data.transport}</p>` : ''}
                            </div>
                        </div>
                    `;
                }
            });

            item.innerHTML = `
                <div class="timeline-node">${dayData.day}</div>
                <div class="timeline-content-card">
                    <h4 class="day-header-title">${dayData.title}</h4>
                    <div class="periods-container">
                        ${periodsHtml}
                    </div>
                </div>
            `;
            timelineContainer.appendChild(item);
        });
    }

    // PDF download trigger
    downloadPdfBtn.addEventListener("click", async () => {
        if (!activeItineraryData) return;

        try {
            downloadPdfBtn.disabled = true;
            downloadPdfBtn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Generating PDF...`;

            const response = await fetch("/download-pdf", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ itinerary: activeItineraryData })
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `Itinerary_${activeItineraryData.destination.replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
                document.body.appendChild(a);
                a.click();
                a.remove();
            } else {
                alert("Failed to build PDF. Please check server logs.");
            }
        } catch (err) {
            console.error(err);
            alert("Error trying to download PDF.");
        } finally {
            downloadPdfBtn.disabled = false;
            downloadPdfBtn.innerHTML = `<i class="fa-solid fa-cloud-arrow-down"></i> Download PDF`;
        }
    });

    // Helper functions
    function appendViewPlanButton(itineraryData) {
        if (!itineraryData) return;
        const bubbles = chatFeed.querySelectorAll(".chat-bubble.bot");
        if (bubbles.length > 0) {
            const lastBubble = bubbles[bubbles.length - 1];
            if (!lastBubble.querySelector(".view-plan-btn")) {
                const btn = document.createElement("button");
                btn.className = "view-plan-btn";
                btn.innerHTML = "<i class='fa-solid fa-map'></i> View Travel Plan";
                btn.addEventListener("click", () => renderItinerary(itineraryData));
                lastBubble.appendChild(btn);
            }
        }
    }

    function appendBubble(text, sender) {
        const bubble = document.createElement("div");
        bubble.className = `chat-bubble ${sender}`;
        bubble.innerHTML = `<p>${text}</p>`;
        chatFeed.appendChild(bubble);
        scrollToBottom();
    }

    function scrollToBottom() {
        chatFeed.scrollTop = chatFeed.scrollHeight;
    }
});
