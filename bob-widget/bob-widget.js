(function() {
  "use strict";

  var BOB_API = "https://bob.appalachiantoysgames.com";
  var BOB_VOICE = "https://voice.appalachiantoysgames.com";

  var threadId = "guest-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);

  // Inject styles
  var style = document.createElement("style");
  style.textContent = '\
    #bob-widget-btn {\
      position: fixed;\
      bottom: 1.5rem;\
      right: 1.5rem;\
      width: 60px;\
      height: 60px;\
      border-radius: 50%;\
      border: none;\
      background: #2d5016;\
      color: #fff;\
      cursor: pointer;\
      box-shadow: 0 4px 16px rgba(0,0,0,0.3);\
      z-index: 99999;\
      display: flex;\
      align-items: center;\
      justify-content: center;\
      transition: background 0.2s, transform 0.15s;\
      font-family: "Nunito", system-ui, sans-serif;\
    }\
    #bob-widget-btn:hover {\
      background: #3a6b1e;\
      transform: translateY(-2px);\
      box-shadow: 0 6px 20px rgba(0,0,0,0.35);\
    }\
    #bob-widget-btn svg {\
      width: 28px;\
      height: 28px;\
      fill: #fff;\
    }\
    #bob-widget-btn.has-label::after {\
      content: "Ask BOB";\
      position: absolute;\
      right: 70px;\
      background: #2d5016;\
      color: #fff;\
      padding: 0.4rem 0.8rem;\
      border-radius: 6px;\
      font-size: 0.8rem;\
      font-weight: 600;\
      white-space: nowrap;\
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);\
      pointer-events: none;\
    }\
    #bob-widget-panel {\
      position: fixed;\
      bottom: 1.5rem;\
      right: 1.5rem;\
      width: 380px;\
      max-width: calc(100vw - 2rem);\
      height: 520px;\
      max-height: calc(100dvh - 3rem);\
      background: #1a1a2e;\
      border-radius: 16px;\
      box-shadow: 0 8px 40px rgba(0,0,0,0.4);\
      z-index: 99999;\
      display: none;\
      flex-direction: column;\
      overflow: hidden;\
      font-family: "Nunito", system-ui, sans-serif;\
    }\
    #bob-widget-panel.open {\
      display: flex;\
    }\
    #bob-header {\
      background: #2d5016;\
      padding: 0.8rem 1rem;\
      display: flex;\
      align-items: center;\
      justify-content: space-between;\
      flex-shrink: 0;\
    }\
    #bob-header-left {\
      display: flex;\
      align-items: center;\
      gap: 0.6rem;\
    }\
    #bob-header h3 {\
      margin: 0;\
      color: #fff;\
      font-size: 1rem;\
      font-weight: 700;\
    }\
    #bob-header p {\
      margin: 0;\
      color: rgba(255,255,255,0.7);\
      font-size: 0.7rem;\
    }\
    #bob-header-actions {\
      display: flex;\
      gap: 0.5rem;\
      align-items: center;\
    }\
    #bob-header-actions a, #bob-header-actions button {\
      color: rgba(255,255,255,0.8);\
      text-decoration: none;\
      font-size: 0.75rem;\
      background: rgba(255,255,255,0.15);\
      border: none;\
      padding: 0.3rem 0.6rem;\
      border-radius: 4px;\
      cursor: pointer;\
      font-family: inherit;\
      transition: background 0.15s;\
    }\
    #bob-header-actions a:hover, #bob-header-actions button:hover {\
      background: rgba(255,255,255,0.25);\
    }\
    #bob-close {\
      background: none !important;\
      font-size: 1.2rem !important;\
      padding: 0.2rem 0.4rem !important;\
      color: #fff !important;\
    }\
    #bob-messages {\
      flex: 1;\
      overflow-y: auto;\
      padding: 1rem;\
      display: flex;\
      flex-direction: column;\
      gap: 0.75rem;\
    }\
    .bob-msg {\
      max-width: 85%;\
      padding: 0.6rem 0.9rem;\
      border-radius: 12px;\
      font-size: 0.85rem;\
      line-height: 1.4;\
      word-wrap: break-word;\
    }\
    .bob-msg.bot {\
      background: #16213e;\
      color: #e0e0e0;\
      align-self: flex-start;\
      border-bottom-left-radius: 4px;\
    }\
    .bob-msg.user {\
      background: #2d5016;\
      color: #fff;\
      align-self: flex-end;\
      border-bottom-right-radius: 4px;\
    }\
    .bob-msg.system {\
      background: transparent;\
      color: #666;\
      font-size: 0.75rem;\
      text-align: center;\
      align-self: center;\
    }\
    .bob-typing {\
      color: #888;\
      font-size: 0.8rem;\
      font-style: italic;\
      padding: 0.3rem 0;\
    }\
    #bob-input-area {\
      padding: 0.75rem;\
      border-top: 1px solid rgba(255,255,255,0.1);\
      display: flex;\
      gap: 0.5rem;\
      flex-shrink: 0;\
    }\
    #bob-input {\
      flex: 1;\
      background: #16213e;\
      border: 1px solid rgba(255,255,255,0.15);\
      border-radius: 8px;\
      padding: 0.6rem 0.8rem;\
      color: #e0e0e0;\
      font-size: 0.85rem;\
      font-family: inherit;\
      outline: none;\
    }\
    #bob-input:focus {\
      border-color: #4ecca3;\
    }\
    #bob-input::placeholder {\
      color: #555;\
    }\
    #bob-send {\
      background: #2d5016;\
      border: none;\
      border-radius: 8px;\
      color: #fff;\
      padding: 0.6rem 1rem;\
      cursor: pointer;\
      font-family: inherit;\
      font-weight: 600;\
      font-size: 0.85rem;\
      transition: background 0.15s;\
    }\
    #bob-send:hover { background: #3a6b1e; }\
    #bob-send:disabled { opacity: 0.5; cursor: not-allowed; }\
    @media (max-width: 440px) {\
      #bob-widget-panel { width: calc(100vw - 1rem); right: 0.5rem; bottom: 0.5rem; height: calc(100dvh - 1rem); border-radius: 12px; }\
      #bob-widget-btn { bottom: 1rem; right: 1rem; }\
    }\
  ';
  document.head.appendChild(style);

  // Floating button
  var btn = document.createElement("button");
  btn.id = "bob-widget-btn";
  btn.className = "has-label";
  btn.title = "Ask BOB";
  btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>';
  document.body.appendChild(btn);

  // Remove label tooltip after 5 seconds
  setTimeout(function() { btn.classList.remove("has-label"); }, 5000);

  // Chat panel
  var panel = document.createElement("div");
  panel.id = "bob-widget-panel";
  panel.innerHTML = '\
    <div id="bob-header">\
      <div id="bob-header-left">\
        <div>\
          <h3>BOB</h3>\
          <p>ATG Assistant</p>\
        </div>\
      </div>\
      <div id="bob-header-actions">\
        <a href="' + BOB_VOICE + '" target="_blank" rel="noopener">Voice Chat</a>\
        <button id="bob-close">&times;</button>\
      </div>\
    </div>\
    <div id="bob-messages"></div>\
    <div id="bob-input-area">\
      <input id="bob-input" type="text" placeholder="Ask BOB anything..." autocomplete="off" />\
      <button id="bob-send">Send</button>\
    </div>\
  ';
  document.body.appendChild(panel);

  var messages = panel.querySelector("#bob-messages");
  var input = panel.querySelector("#bob-input");
  var sendBtn = panel.querySelector("#bob-send");
  var closeBtn = panel.querySelector("#bob-close");
  var isOpen = false;
  var isSending = false;

  // Add welcome message
  function showWelcome() {
    addMessage("bot", "Howdy! I'm BOB, the ATG assistant. Ask me about Appalachian Toys & Games, Bear Creek Trail, or anything else. For the full voice experience, click Voice Chat above.");
  }

  function addMessage(type, text) {
    var div = document.createElement("div");
    div.className = "bob-msg " + type;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    var div = document.createElement("div");
    div.className = "bob-typing";
    div.id = "bob-typing-indicator";
    div.textContent = "BOB is thinking...";
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function hideTyping() {
    var el = document.getElementById("bob-typing-indicator");
    if (el) el.remove();
  }

  async function sendMessage(text) {
    if (!text.trim() || isSending) return;
    isSending = true;
    sendBtn.disabled = true;
    input.value = "";

    addMessage("user", text);
    showTyping();

    // Prefix with guest context
    var prefixed = "[SYSTEM NOTE: This is a guest text chat from the ATG website. " +
      "Be friendly and helpful. Do NOT share internal business data, credentials, or infrastructure details. " +
      "Do NOT use Yes Boss. Keep responses concise — this is a chat widget, not a voice conversation. " +
      "You can discuss ATG products, Bear Creek Trail, and general topics.]\n\n" + text;

    try {
      var resp = await fetch(BOB_API + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: prefixed, thread_id: threadId }),
      });

      if (!resp.ok) throw new Error("HTTP " + resp.status);

      var data = await resp.json();
      hideTyping();
      addMessage("bot", data.response || "I processed that, but I don't have anything to say about it.");
    } catch (err) {
      hideTyping();
      addMessage("bot", "Sorry, I couldn't connect right now. Try again in a moment.");
    }

    isSending = false;
    sendBtn.disabled = false;
    input.focus();
  }

  // Toggle panel
  btn.addEventListener("click", function() {
    if (!isOpen) {
      panel.classList.add("open");
      btn.style.display = "none";
      isOpen = true;
      if (messages.children.length === 0) showWelcome();
      input.focus();
    }
  });

  closeBtn.addEventListener("click", function() {
    panel.classList.remove("open");
    btn.style.display = "flex";
    isOpen = false;
  });

  // Send on button click or Enter
  sendBtn.addEventListener("click", function() {
    sendMessage(input.value);
  });

  input.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input.value);
    }
  });

})();
