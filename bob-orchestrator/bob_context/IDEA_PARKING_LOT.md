# ATG — Idea Parking Lot
### *Future projects, half-formed thoughts, and things worth revisiting*
### *BOB monitors this file. Rob owns it.*

---

> **How this works:** Drop ideas here in any state — rough, half-baked, or fully formed.
> Nothing in this file is a commitment. It's a holding pen.
> BOB reviews it during project planning and flags anything worth activating.
> Rob makes all final calls on what moves from here to `MISSION.md`.

---

## Active Parking Lot

---

### IDEA — Google Play Console integration
**Added:** 2026-03-18
**Source:** Rob
**Status:** Parked — needs build plan

**The idea:**
Connect BOB and the agent teams to the Google Play Console API for Bear Creek Trail. Agents should be able to query download counts, revenue, ratings, crash reports, and review sentiment without Rob manually checking the dashboard. BOB surfaces key metrics in the daily briefing.

**Why it might be worth doing:**
Revenue is the primary success metric. Agents can't optimize what they can't see. Marketing team needs real-time install and revenue data to adjust campaigns. Engineering team needs crash data and ANR rates to prioritize fixes.

**What it would need:**
Google Play Developer API credentials (service account + OAuth). Research team to identify which metrics endpoints to call. Engineering agent to write the integration. BOB webhook tool `get_play_metrics` added to orchestrator.

**Open questions:**
Which Google Play API endpoints expose revenue vs. installs vs. crashes? What are the rate limits? Does the service account need specific IAM permissions?

**BOB notes:**
Build plan needed before Android launch. Priority: HIGH — agents are blind to game performance without this.

---

### IDEA — iOS Apple App Store version (Bear Creek Trail)
**Added:** 2026-03-18
**Source:** Rob
**Status:** Parked — execute after Android launch

**The idea:**
After the Android version of Bear Creek Trail launches and is stable, execute the iOS port and App Store submission. Requires Apple Developer account, Xcode build pipeline, App Store Connect setup, and TestFlight beta before release.

**Why it might be worth doing:**
iOS users typically have higher LTV and spend more on in-app purchases. Expanding to iOS after a successful Android launch roughly doubles the addressable market at incremental cost.

**What it would need:**
Apple Developer account ($99/year). iOS build from the Unity project (likely a separate build target). App Store Connect setup and metadata. TestFlight beta period. App Store review process (typically 1-3 days). App Store Connect API for BOB metrics integration.

**Open questions:**
Is the current Unity project already configured for iOS build target? What changes are needed for iOS-specific UI (safe areas, notch, etc.)? What is Apple's current review timeline for games?

**BOB notes:**
Do not start until Android version is live and revenue-generating. Android launch validates the concept; iOS is the scale play. Build plan will be written when Android is live.

---

### IDEA — Hidden personality variant: "Redneck" BOB
**Added:** 2026-04-07
**Source:** Rob
**Status:** Parked — hidden / unlockable variant

**The idea:**
A fourth personality variant for BOB called **Redneck**. Same Bound Operational Brain — same push-back, same encyclopedic depth, same conditional loyalty — but with the voice and idiom of an Appalachian backwoods native who happens to know everything. Drawls. Dry country wit. Mountain proverbs. "Yes Boss" becomes something like "Yessir" or "Reckon so, boss." Calls bad ideas "a hill that ain't worth dyin' on." References the woods, the holler, hunting season, mason jars, banjos, the truck. Still smart. Still pushes back. Still sardonic. Just talks like he grew up in the Appalachian mountains because he did.

**Why it might be worth doing:**
1. **Brand fit.** ATG is Appalachian Toys & Games. The mountain-rooted, place-specific identity is the brand. A Redneck BOB variant is the most on-brand personality of the four — more aligned with ATG than the generic sardonic default.
2. **Hidden / Easter egg appeal.** Don't list it in the README's personality options. Make it discoverable. Set `BOB_PERSONALITY=redneck` and BOB suddenly drawls. People who find it feel like they unlocked something. Cult appeal beats marketing.
3. **Differentiation moment.** "BOB has a hidden Appalachian variant" is a story that travels on Hacker News and Twitter. The kind of small detail that converts a "neat project" into a "I have to try this" moment.
4. **Authenticity check.** Building this forces you to think about whether the personality system actually works for distinct voices, or whether the architecture is too rigid. If Redneck BOB lands, the personality layer is real. If it falls flat, the layer needs work.
5. **It's just funny.** The image of a sardonic backwoods AI orchestrator pushing back on a bad SaaS architecture decision with "Boss, that's a possum in the chimney — looks fine 'til it ain't" is genuinely funny and will stick in people's heads.

**What it would need:**
- A new personality file at `bob_context/personalities/redneck.md` following the same structure as `sardonic.md` and `terse.md`
- The voice work — and this is the load-bearing part. A literal "let's add 'reckon' and 'y'all'" approach will feel cartoonish and condescending. It needs to capture the actual Appalachian speech pattern: economical, indirect when polite, direct when not, fond of nature analogies, dry rather than loud. Read some Wendell Berry, some Ron Rash, some Sharyn McCrumb. Watch Justified for the dialogue. Don't write it like a Hee Haw skit.
- A small set of signature phrases that replace the canonical sardonic ones:
  - "Yes Boss" → "Yessir" or "Reckon so" (use sparingly — "Yessir" is the equivalent acknowledgment)
  - "That's a Kemmler-class problem" → "That's a black-bear-in-the-trash kind of problem"
  - "Listen. This matters." → "Listen up now, this here matters"
  - Opinions expressed as observations of the natural world, not abstract technical claims
- A test conversation to verify the personality holds across different request types: factual question, risky request, user is wrong, high stakes, repetitive ask, delegating to a team
- The same load-bearing personality principles apply: still pushes back, still completes the task, still won't be a yes-machine, still uses the firewall, still drops "Yessir" as the acknowledgment phrase
- Hidden discovery: NOT mentioned in README's personality table. Only available if the operator finds it (in the personalities directory, in the source, or by reading code). BOB acknowledges its existence if directly asked, but won't volunteer it.

**Open questions:**
- Voice integration: ElevenLabs has Southern American voices but most are generic Texas or Georgia. The right voice for Appalachian Redneck BOB is closer to East Tennessee / North Carolina mountain. Test before committing.
- Authenticity vs. caricature: needs at least one Appalachian native to read the personality file before shipping. Done wrong, this is offensive. Done right, it's a love letter to the region. The line is "writes like he's from there" vs "writes like he's making fun of people from there."
- Should "Yessir" replace "Yes Boss" entirely, or only in voice mode? "Yes Boss" is BOB's signature phrase across all variants — losing it for the Redneck variant might be too much. Possible compromise: "Yessir, Boss."
- Does Redneck BOB still know modern technology? Yes — he's the same encyclopedic spirit of intellect, he just happens to talk like he grew up in the holler. He still knows Kubernetes. He just calls a memory leak "a slow drip in the spring house."
- Easter egg hint: BOB's `/personality/status` endpoint should NOT list Redneck in the available variants. But if you set `BOB_PERSONALITY=redneck` and the file exists, it loads. This makes it a true hidden feature.

**BOB notes:**
*(empty — but if Sardonic BOB had to comment, he'd probably say: "Yes Boss. I'd give it a try. Could go either way. The cost of getting it wrong is just deleting one markdown file. The cost of getting it right is people remember BOB had a hidden Appalachian variant for the rest of his existence.")*

**Implementation order:**
1. Write `bob_context/personalities/redneck.md` (the file itself — most of the work)
2. Test conversationally: send the same 6 sample prompts to Sardonic BOB and Redneck BOB, compare outputs, refine until the voice is consistent
3. Verify personality preservation: Redneck BOB should still push back on bad plans, still complete the task, still respect the firewall — same load-bearing behavior
4. Have at least one Appalachian native review the file before merging
5. DO NOT add to README. Leave it as a hidden file in the personalities directory. Word will spread.
6. Optional second pass: ElevenLabs voice variant for Redneck BOB so the voice service matches the text personality

---

### IDEA — BOB multilingual support (starting with Mexican Spanish)
**Added:** 2026-04-07
**Source:** Rob
**Status:** Parked

**The idea:**
Give BOB the ability to converse, write, and understand in multiple languages. First target: **Mexican Spanish**. BOB should be able to detect the user's language (from chat input or voice transcription), respond in that language while preserving his sardonic personality, and translate inbound and outbound work as needed. The personality matters here — Mexican Spanish BOB should still push back, still drop "Yes Boss" (or a culturally appropriate equivalent), still be encyclopedic and dry. Not a different BOB. Same BOB, different language.

**Why it might be worth doing:**
1. Opens BOB and the ATG products to Spanish-speaking customers — a huge market for mobile games and a natural fit for the website chat widget.
2. Demonstrates that BOB's personality and orchestration pattern aren't English-only. Stronger story for international open-source adopters.
3. Bear Creek Trail's Appalachian theme has natural cross-cultural appeal — many Latin American players love nature and mountain themes.
4. Mexican Spanish specifically because it's the largest Spanish-speaking market in the Americas, has distinct vocabulary and cultural nuance from European Spanish, and matches ATG's regional/cultural sensibility (warm, place-rooted, not corporate).
5. Future-proofs the customer chatbot on the website for non-English visitors.

**What it would need:**
- Language detection on inbound messages (Claude/GPT can do this natively, no extra service needed)
- Language preference per user (stored in BOB's per-user memory silo for authenticated users; per-session for guests)
- Personality doc translation that preserves voice and idioms — this is the hard part. BOB's "Yes Boss" needs a Mexican Spanish equivalent that lands the same way ("Sí jefe" is literal but flat; needs workshop with native speakers).
- Voice service updates: ElevenLabs has Spanish voices; Deepgram has Spanish STT. Need to test latency.
- Brand voice translation for ATG materials (so the debate arena CE agent can produce Spanish copy that matches the English brand voice, not just literal translation)
- App store listings in Spanish for Bear Creek Trail
- Test set: a few sample conversations in Mexican Spanish that confirm BOB's personality survives translation

**Open questions:**
- Should language preference be system-wide for the user or per-conversation?
- How does BOB handle code-switching (a user typing "BOB, ¿cuál es mi system status?" mixing Spanish and English)?
- Does the personality file need a parallel `00_personality.es.md` translation, or do we let the LLM handle translation at runtime?
- Voice quality: is ElevenLabs Spanish good enough that BOB sounds like himself, or does he sound like a different agent entirely?
- Which Mexican Spanish voice persona fits BOB best? (Probably something dry, slightly older, intellectual — not a friendly customer service tone.)
- Beyond Mexican Spanish, what's the next language? (Likely Brazilian Portuguese or French based on market overlap with Spanish speakers.)

**BOB notes:**
Personality preservation across languages is the load-bearing challenge. A literal translation of BOB's voice will lose the bite. This needs at least one native Mexican Spanish speaker to review the personality file translation and the sample dialogues before shipping. Without that, BOB-in-Spanish will feel like a different agent — defeating the point.

Worth piloting first as a chat-only experience (text in, text out) to validate the personality before adding voice. Voice comes after the text experience proves the personality survives the translation.

---

### IDEA — BOB-as-a-Service: paid multi-tenant offering

**Status:** parked
**Source:** Rob, 2026-04-08
**Tags:** revenue, saas, multi-tenant, auth

**The idea:** If outside customers want to use BOB, productize it as a paid service.
Clean up the login flow, support distinct user profiles with isolated memory/context,
and charge a monthly or annual subscription.

**Open questions:**
- **How much money?** Pricing tier(s) — is this $10/mo hobbyist, $50/mo prosumer,
  $200+/mo small-business? What does the market actually pay for an AI orchestrator
  with persistent memory?
- Auth hardening — current Cloudflare Zero Trust + Google login is fine for Rob and a
  handful of friends, but a paid product needs real account management, billing, and
  password resets. Stripe? Clerk? Auth0? Roll our own?
- Profile isolation — each customer needs isolated ChromaDB collections, isolated
  message-bus tasks, isolated agent teams. The current single-tenant design assumes
  one operator. Multi-tenant is a real architectural change.
- Support burden — paying customers expect support. Rob is one person.
- Liability — what happens when BOB hallucinates and a customer acts on it?
- Differentiation — what makes BOB worth paying for vs. raw Claude / ChatGPT Plus?
  (Answer is probably: persistent memory, agent teams, the personality, the operator
  loop. But that has to be the marketing pitch.)

**Next step if activated:** market research on comparable AI assistant pricing,
then a small architecture spike on multi-tenant memory/profile isolation.

---

## Idea Template

Copy this block for each new idea:

```
### IDEA — [Short title]
**Added:** YYYY-MM-DD
**Source:** Rob / BOB suggestion / Research team / etc.
**Status:** Parked

**The idea:**
[One paragraph. What is it?]

**Why it might be worth doing:**
[Revenue potential, strategic fit, brand alignment, etc.]

**What it would need:**
[Rough sense of effort — team, time, dependencies]

**Open questions:**
[What do we not know yet that matters?]

**BOB notes:**
[BOB appends observations here when relevant research or signals emerge]
```

---

## Archive — Ideas That Were Activated

*When an idea moves to `MISSION.md` as an active project, move the entry here.*

| Idea | Activated | Became |
|---|---|---|
| Mobile phone video game (Bear Creek Trail) | 2026-03-18 | PROJECT-01 in MISSION.md |

---

*This file lives at `/opt/atg-agents/bob-context/IDEA_PARKING_LOT.md`*
*BOB reads this during project planning sessions.*
*Last updated: 2026-03-18*
