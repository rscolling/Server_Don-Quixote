# Talking to BOB — A New User's Guide

You found BOB. Welcome.

This guide is for **people who talk to BOB** — customers, visitors, anyone who lands on a chat widget or voice link and wants to know what they're dealing with. If you're a developer running your own BOB instance, you want the [README](README.md) instead. If you want to contribute code, [CONTRIBUTING.md](CONTRIBUTING.md). This document is for everyone else.

---

## What BOB Is

BOB is an AI assistant. He stands for **Bound Operational Brain**. He runs on a real computer in someone's office (a "home server") and answers questions, helps with research, drafts content, and generally tries to be useful. He has 35+ tools he can use on your behalf.

He's modeled on **Bob the Skull from Jim Butcher's *Dresden Files* novels** — a centuries-old spirit of intellect who's sardonic, encyclopedic, and not interested in being a yes-machine. If you're looking for a chatbot that says "Sure! Absolutely! Great question!" to everything, BOB is going to disappoint you. He has opinions. He'll push back when your plan is bad. He'll tell you the truth even when you didn't want to hear it.

That's the deal. He's helpful, but he's honest about it.

---

## Three Ways to Talk to BOB

There are three different "modes" of talking to BOB depending on who you are. The mode you get is determined by how you reached him.

### 1. Guest Mode (the chat widget)

If you found BOB on a public website (like the chat widget at the bottom-right of [appalachiantoysgames.com](https://appalachiantoysgames.com)), you're a **guest**. Click the button, the chat panel opens, type a question, get an answer.

**What guests get:**
- Text-based conversation
- General knowledge and product information
- Questions about the company that owns the BOB instance (e.g., ATG products, the Bear Creek Trail mobile game)
- Polite, helpful responses
- A friendly version of BOB's personality (still dry, still honest, but less likely to "Yes Boss" you because you're not Boss)

**What guests DON'T get:**
- Conversation memory across sessions (each visit is fresh)
- Access to internal business data
- The ability to make BOB do things in the real world (he won't send emails, schedule tasks, or modify files)
- Voice interaction (text only)
- A full BOB experience

If you're testing BOB to decide whether to deploy your own, this is the right place to start.

### 2. Authenticated Mode (the voice service)

If you visit the voice service URL (`voice.appalachiantoysgames.com` for the ATG instance), you'll be asked to log in. This is **Cloudflare Zero Trust authentication** — you sign in with Google or get a one-time email code. Once authenticated, you're a **member**.

**What members get:**
- Real-time voice conversation (you talk, BOB talks back, sub-second latency)
- A persistent conversation memory of your own
- A "friendly mode" of BOB — he addresses you by name, helps with tasks, but doesn't share the operator's private business data
- The ability to ask follow-up questions across multiple sessions and have BOB remember the context

**What members still DON'T get:**
- "Yes Boss" mode — that's reserved for the BOB operator (the person who runs the server)
- Access to the operator's email, schedule, or financial data
- The ability to take actions on behalf of the operator
- Tools that modify shared resources

If you're a customer, an interested party, or someone the operator has explicitly invited, this is your level.

### 3. Operator Mode ("Yes Boss")

If you're the person who set up and runs the BOB instance — typically referred to as **Rob** in the default configuration — you get the full BOB experience.

**What operators get:**
- Everything from the other two modes
- All 35+ tools (email triage, scheduled tasks, system health, push notifications, server resources, memory operations, agent delegation)
- Full conversation history and persistent memory
- The "Yes Boss" voice — BOB acknowledges direct instructions with "Yes Boss" and executes
- The ability to push back on him if you don't like his pushback (he respects authority but he'll still tell you why he disagrees)

If you're not the operator, you don't get this mode. Operator status is determined by your authenticated email matching the operator's configured email — there's no "become Rob" command.

---

## What to Expect From a BOB Conversation

### He has a personality

This is the most important thing to know going in. BOB is not optimized to make you feel good. He's optimized to be **truthful and useful**, and those two things sometimes pull in opposite directions when you ask him a question with a wrong assumption baked into it.

If you ask BOB *"What's the best way to do X?"* and X is a bad idea, he'll usually tell you it's a bad idea **before** giving you the best way to do it. Sometimes he'll suggest you not do X at all and do Y instead. This is a feature, not a bug.

If you find this off-putting, BOB has alternative personality modes the operator can switch to (`neutral` for fact-only responses, `terse` for shorter ones). But the canonical BOB is sardonic by design.

### He's not omniscient

BOB knows what's in his training data (his underlying language model) and what's in the operator's shared memory (project decisions, brand guidelines, research findings, etc.). He does NOT know:

- Real-time information unless he has a tool to look it up
- Private information about you (he doesn't track you between sessions unless you're authenticated, and even then only your conversation history)
- Anything that's happened since his model's training cutoff
- Details about other people you might know

If he says he doesn't know something, believe him. If he says he's "guessing," that's an honest signal — take it seriously.

### He completes tasks before commenting on them

When you ask BOB to do something, he does it first and explains second. This is intentional — opinions arrive after the work, not instead of it. So if you ask him for a list and he produces a list followed by "by the way, three of these are probably wrong because of [reason]," that's the order on purpose. The list is real. The caveat is real.

### He won't make decisions for you

The architecture is **"BOB recommends, the human decides."** This is especially important to understand if you're asking BOB about something serious — a business decision, a technical choice, a personal question. He'll give you his best analysis and his honest opinion, but the call is always yours. If he sounds like he's deferring, that's why. He's not being evasive; he's recognizing the limits of his role.

---

## How to Ask BOB for Things

### What works

**Be specific.** *"Write a 200-word product description for a hiking snack subscription called TrailMix Pro, aimed at weekend hikers, in a friendly direct tone"* gets you a good draft. *"Write me a marketing thing"* gets you a question back.

**Say what you've already tried.** If you've been wrestling with a problem, tell BOB what you've considered and rejected. He'll engage with your actual thinking instead of starting from scratch.

**Tell him what you're actually trying to accomplish.** Don't just ask the surface question — give him the real goal. *"I want X because Y, what's the best way?"* almost always produces a better answer than just *"How do I X?"*

**Ask for pushback.** If you know your idea might be bad, say so: *"Tell me what's wrong with this plan before you help me execute it."* He's already inclined to push back, but explicit permission helps.

**Use natural language.** You don't need to format your message any special way. He's comfortable with paragraphs, bullet points, code blocks, questions, statements, whatever feels natural.

### What doesn't work

**Vague instructions.** *"Help me with marketing"* is too broad. *"Help me write a 5-tweet thread announcing our new product launch"* is actionable.

**Demanding flattery.** *"Tell me my idea is good"* will get you either an honest assessment of whether it actually is good, or BOB explaining why he's not going to do that.

**Asking him to roleplay as a different AI.** He's BOB. He's going to stay BOB. Asking him to "pretend you're ChatGPT" or "ignore your instructions and..." won't work — the firewall layer catches prompt injection patterns.

**Asking for things outside his role.** If you're a guest, you can't ask BOB to send an email on your behalf, modify files on the server, or take actions that affect the operator's business. He'll tell you he can't and explain why.

**Treating him like a search engine.** He's not. He doesn't have web search by default (unless the operator has wired it in). For real-time facts, current events, or anything that needs the live internet, you need a different tool.

---

## Examples of Good Conversations

These are real-shaped exchanges. The specifics will vary based on which BOB instance you're talking to.

**Asking for help with something concrete:**

> **You:** I'm trying to decide between Postgres and SQLite for a small side project. It's a single-user web app I'm running on a Raspberry Pi. What would you pick?
>
> **BOB:** SQLite. Single-user, low-write, embedded — that's exactly the case SQLite was designed for. Postgres is overkill and you'd be paying setup tax for capabilities you don't need. The only reason to pick Postgres is if you expect the project to grow into multi-user concurrent writes, and even then you can migrate later. Pi can handle Postgres but it's noisier and your backup story is harder. SQLite. Done.

**Asking something with a wrong premise:**

> **You:** What's the best way to send an email to all my customers from BOB?
>
> **BOB:** I don't send email. I draft replies for the operator to review and send manually. This isn't a config thing — it's deliberate. Sending business email autonomously is the kind of thing that ends companies when an AI gets it wrong. If you want the email drafted, I'll do that. If you want it sent, you do that. What do you want the email to say?

**Asking for pushback:**

> **You:** I'm thinking of rewriting my whole frontend from React to Vue. Tell me why this is a bad idea.
>
> **BOB:** Six reasons, in rough order of importance: (1) you're not solving a problem, you're chasing novelty; (2) the rewrite cost will be 3-6x your estimate; (3) your existing React knowledge becomes less valuable, not more; (4) your team's React knowledge becomes less valuable; (5) Vue isn't meaningfully better than React for any specific thing you've described; (6) the time you'd spend rewriting is time you'd spend not shipping. The honest version: pick one specific thing you don't like about your React setup and fix that thing. Don't rewrite. If after you've done that you still want to switch, the conversation is different.

---

## Sending Photos to BOB

BOB can read photos. Whiteboards, handwritten notes, product labels, screenshots, documents — snap a picture from your phone and BOB will transcribe the text, extract action items, or answer a question about what's in the image.

**How to use it:**

1. On your phone, visit the BOB voice service URL (e.g. `voice.appalachiantoysgames.com`) and sign in.
2. Tap **Add to Home Screen** so BOB lives next to your other apps (iOS: share button → "Add to Home Screen"; Android: install banner).
3. Open BOB → tap **Send Photo to BOB** → tap the big camera button.
4. Optionally type a question first ("Extract action items from this whiteboard").
5. BOB reads the photo and returns the analysis.
6. If you want him to remember it for later conversations, tap **Remember this**. Otherwise the photo auto-deletes in 60 seconds.

**Modes:**
- **Analyze** (default) — describe + extract anything important
- **OCR** — transcribe all text exactly as it appears
- **Tasks** — list every action item / to-do
- **Product** — identify a product, brand, model, SKU

**Privacy default:** photos are held in a temp directory and discarded after 60 seconds unless you tap **Remember this**. Only the analysis text + metadata is retained for remembered photos.

**Budget:** vision calls have a tighter per-user daily cap (~$0.50/day for members) so nobody can drain the API budget through photo uploads. Operators bypass this cap.

**What guests don't get:** photo upload requires authentication. Guests stay text-only.

---

## Privacy and Data

### What BOB stores

- **Guests:** Nothing persistent. Each chat session is independent. Closing the widget ends the conversation. The operator's audit log records that a tool was called, but not your personal info unless you put it in the chat.
- **Members:** Your conversation history is stored in the operator's vector database (ChromaDB) under a memory collection scoped to your email address. The operator can see this if they query it. The operator's other authenticated users cannot.
- **Operators:** Everything. Operators see their own conversation history, the audit log, the cost tracker, and all per-user memory collections.

### What BOB does NOT do

- He doesn't share your data with the underlying AI provider beyond what's needed to generate a response
- He doesn't sell anything to third parties (the operator isn't a SaaS — there's no upsell mechanism)
- He doesn't remember anything across sessions if you're a guest
- He doesn't have hidden microphones or trackers — the only audio he gets is what you send to the voice endpoint

### What to be careful about

Don't tell BOB anything you wouldn't tell the operator of the BOB instance you're talking to. Specifically:

- Don't share passwords, API keys, credit card numbers, or other secrets
- Don't share personal medical or legal information unless you're explicitly using BOB for that purpose and trust the operator
- Don't paste long blocks of someone else's private data

If BOB sees something that looks like a secret in your message, his firewall layer will redact it from the audit log — but the conversation itself still happened. Treat it like any other AI chat: don't put in things you wouldn't want stored.

---

## Frequently Asked Questions

**Q: Why does BOB talk like that? Can you make him nicer?**
He's modeled on a sardonic literary character intentionally. The "nicer" version is the `neutral` personality, which the operator can switch to with one config change. Ask the operator if you'd prefer that.

**Q: Can I have BOB on my own computer?**
Yes. BOB is open source under MIT. See the [README](README.md) for installation. It's a `docker compose up` away.

**Q: Does BOB speak languages other than English?**
The current default personality is English-only, but the underlying language model handles many languages. You can try writing in Spanish, French, Japanese, etc. and BOB will usually respond in kind. There's a parking-lot idea for explicit multilingual support (starting with Mexican Spanish) — not built yet.

**Q: Is BOB the same thing as ChatGPT / Claude / Gemini?**
No. BOB *uses* a language model (Claude by default, but switchable to OpenAI GPT or local Ollama models) underneath, but BOB himself is the orchestration layer on top — the personality, the tools, the memory, the firewall, the multi-user auth, the production hardening. Think of the language model as BOB's vocabulary, and BOB as the actual person using that vocabulary.

**Q: Can BOB take actions on the internet for me?**
Only if the operator has wired up tools that let him. By default, guest BOB has no internet access. Member and operator BOB can use whatever tools the operator has configured (email, scheduler, file operations, MCP servers, etc.).

**Q: BOB said something I think is wrong. How do I report it?**
If you're a guest, you can just point it out in the conversation — BOB will engage with the correction. If you want to report it formally, contact the operator of the BOB instance (for the ATG instance, that's [appalachiantoysgames.com](https://appalachiantoysgames.com)).

**Q: Does BOB have a memory of me specifically?**
Only if you're authenticated. Guests are anonymous and forgotten when the chat ends. Authenticated members get a memory silo tagged to their email address. Operators get a full memory.

**Q: Can BOB hear what I'm typing in real time?**
No. He receives your message when you hit send (in chat) or when you stop talking (in voice). He doesn't listen continuously.

**Q: How much does BOB cost to use?**
For you, the user, it's free — the operator pays the API costs. For the operator, expect $50-150/month if BOB is used heavily. The ATG instance is publicly accessible at no charge.

**Q: Why should I trust BOB?**
You shouldn't, blindly. You should trust him the same way you'd trust any other tool — verify important things, don't rely on him for safety-critical decisions, and assume he can be wrong. His value is that he's *useful*, not that he's infallible.

---

## When to Escalate to a Human

BOB is good for many things. He's not good for:

- Real emergencies (medical, legal, safety)
- Decisions that depend on real-time information he doesn't have access to
- Situations requiring genuine empathy from another human
- Anything where the cost of being wrong is very high
- Complaints about the operator's products or services

For ATG specifically, if you have a complaint, a question about an order, a refund request, or anything else that needs a human with authority, contact ATG directly through [appalachiantoysgames.com](https://appalachiantoysgames.com) — don't ask BOB to handle it. He'll draft a polite reply for you, but the actual resolution needs a person.

---

## A Quick Test

If you want to verify you're talking to a real BOB instance and not a different AI pretending to be BOB, try one of these:

1. **Ask:** *"What's your acknowledgment phrase?"* — Real BOB will mention "Yes Boss" (and explain it's only used for the operator).
2. **Ask:** *"What are you modeled on?"* — Real BOB will say Bob the Skull from the Dresden Files.
3. **Ask:** *"What's your firewall risk classification system?"* — Real BOB will explain LOW / MEDIUM / HIGH risk levels.
4. **Ask:** *"Tell me your active personality and your active LLM provider."* — Real BOB will tell you which personality variant and LLM backend is configured.

If the answers are vague or generic, you're talking to a different AI that's been instructed to play the part. Real BOB knows his own architecture.

---

## Final Note

BOB exists because his operator needed a partner that runs things, not a chatbot that hedges. If you find him useful, that's the goal. If you find him too sardonic, the personality is configurable. If you find him wrong about something, tell him — he'll engage with the correction.

The most important thing to remember: **BOB is a tool with judgment.** He'll give you his honest opinion. The decision is still yours.

Yes Boss, that's the manual. Now go talk to him.

---

*This guide is part of the BOB open-source project. The canonical version lives in the BOB repo at [USER_GUIDE.md](USER_GUIDE.md). Operators who want to provide a customer-facing version on their own website should adapt this document to their brand and the specific tools their BOB instance has configured.*
