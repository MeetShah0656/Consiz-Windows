# HeyClicky — Their Playbook, Their Real Gaps, Our Answer

> **REALITY CHECK (31 Aug 2026):** §6 said 'Lead with Windows / ship before writing another document' — we built Mac first anyway (dev machine), and wrote 4 more documents. Own both. The 5-second CSV demo is scripted (reel/) but NOT filmed. The rest of this file stands; see 12 for the current head-to-head.

---

## 1. The tweet

X blocks automated fetching, so here are the direct links to read yourself:

- **Original demo tweet (the one that blew up):** https://x.com/FarzaTV/status/2041314633978659092
- **Second viral demo, May 30 2026:** ~3M views, voice-controlling his whole Mac. OpenAI's Greg Brockman replied calling it "real magic."
- **YC launch post:** https://www.ycombinator.com/launches/QNN-this-is-heyclicky-an-ai-buddy-that-lives-next-to-your-computer-cursor
- **Open-source repo:** https://github.com/farzaa/clicky — 7,300 stars, 1,400 forks

**Numbers on the first tweet:** ~3M views, ~15K likes.

**The framing he used — this is the part that matters.** From his own launch copy:

> He wrote about missing the era when computers felt light and new — forums, flash games, random viral videos. That now he opens his computer and doesn't feel curious, just tired. So he wanted to build something that made him smile.

Then: "he's a lil buddy that lives next to your cursor."

No "AI-powered." No "productivity." No market size. A feeling, then a cute thing.

---

## 2. His actual sequence

1. **Had the audience first.** Buildspace — 100,000+ builders. He wound it down in 2024 and people waited for what he'd do next. When he posted, millions watched by default.
2. **Weekend side project.** Not a company. No pitch deck. Just a demo.
3. **Demo video where the value is visible in 5 seconds.** A blue arrow flies across the screen and points at the exact button. You don't need the caption to understand it.
4. **Emotional framing, not feature framing.** Nostalgia and a cute buddy, not "contextual AI assistant."
5. **Open-sourced it.** 7.3k stars, 1.4k forks. Free credibility, free distribution, free contributors.
6. **Free download, zero signup.** No email wall.
7. **Product Hunt + X + Instagram.** Instagram is where he says the "insane pull" came from.
8. **YC within weeks** — 4 weeks old at the YC launch post.
9. **Monetized after.** Free / $20 Pro / $100 Max.
10. **Closed-sourced the new work** in April 2026, kept the old repo public.

---

## 3. Can you run this same script?

Partly. Be honest about which parts.

| Step | Can you copy it? |
|---|---|
| Pre-existing audience | **No, not at his scale.** This was the whole engine. He had 100k builders waiting. You have a real audience but not that. Assume you get 5% of his reach, not 100%. |
| Weekend build, ship fast | **Yes.** With the hardware gone, your MVP is weeks. Do this. |
| Demo where value is visible in 5 seconds | **Yes, and this is your strongest move.** Select a messy CSV → press the button → correct total appears. That reads instantly. |
| Emotional framing over feature framing | **Yes.** Your current framing is all architecture and market. Nobody shares that. |
| Open source | **Yes, and consider it seriously.** It cost him nothing and bought enormous reach. |
| Free download, no signup | **Yes.** Especially for India. |
| Instagram/X demo videos | **Yes.** You already make video content. This is an unused asset. |

**The honest read:** his distribution was inherited, not built. Copying the tactics without the audience gets you a fraction of the result. Plan for that instead of expecting a viral hit.

---

## 4. Gap analysis — I checked my earlier claims, and I was partly wrong

I said earlier they can't do folders, files, or numbers. I went and read their repo, their changelog, and their product descriptions. Here is the corrected version.

### Gaps that are REAL

| Gap | Evidence |
|---|---|
| **Windows doesn't exist** | Mac only. macOS 14.2+ required. Windows on a waitlist with no announced date. **India's PC market is overwhelmingly Windows. They are absent from your home market.** This is the single biggest real gap. |
| **Voice-first is a hard constraint** | Push-to-talk is the primary input. Doesn't work in an office, a shared room, a library, a café, or a home with family around. Accent and ambient noise add failure. A silent button press has none of these problems. |
| **Instant path is vision-only** | Their fast loop is: screenshot → Claude vision → spoken answer. Numbers are read off pixels, not computed. Rows below the fold don't exist to it. |
| **Price** | $20/month Pro, $100/month Max. For India, that's a non-starter for most users. |
| **Segment** | They target creators and learners — people stuck in DaVinci, Figma, After Effects. Kids making games. Not analysts working with data. Different job. |

### Gaps I overstated — correcting myself

| What I said | The truth |
|---|---|
| "They can't touch files or folders" | **Wrong.** Their agents clean up desktop files, organize Notes and Calendar, and build Mac apps locally. They have filesystem access. |
| "They can't compute" | **Overstated.** Their instant path can't. But an agent that writes and runs code could. They just haven't aimed at it. |
| "Purely screenshot-based" | **Outdated.** Their changelog shows dictation writing into text boxes with clipboard fallback in Electron apps. Same technique we planned. |

**What this means:** our advantage is not that they *cannot* do these things. It's that they are **not built around them and not pointed at them.** Their fast path is vision and voice. Ours is structured data and silence. That's a design difference, not a capability wall — and a well-funded team could close it if they chose to.

Say this accurately. If you claim "they can't do files" to an investor who has used the product, you lose the room.

---

## 5. What to say when someone asks "how is yours better?"

**Don't say "better." Say different job.**

### The short answer (use this)

> "Clicky is a tutor. You get stuck in Figma, you ask out loud, it points at the button. We're not that. We're for the moment you're looking at data and need the right answer — select a column, press the button, get a number that's actually computed, not read off a screenshot. And we work on Windows, silently, which is most of the people we're building for."

### The three points behind it

**1. Different job.**
They answer "how do I do this?" We answer "what does this say?" One is teaching, one is comprehension. A person can use both.

**2. Different input.**
Voice vs a silent button. Theirs fails in every shared space. Ours works in an office, a classroom, a library, at 2am next to someone sleeping.

**3. Different accuracy model.**
They read numbers off an image. We compute them. When a model looks at a screenshot of a spreadsheet and reports a total, it's estimating. When we sum a column, it's arithmetic. Microsoft has publicly admitted Excel Copilot gets calculations wrong — that's the whole category's weak point, and it's the one thing we designed around from day one.

### If they push: "but they could add all of this"

> "Yes. And Microsoft could too. Nobody in this category has a technology moat — that's true of them and of us. What we have is a specific job we're built around instead of retrofitted into, and a market they haven't entered."

That answer is honest and it's stronger than pretending we have a moat we don't.

### What NOT to say

- ❌ "We're the first to do this" — false, and easily checked
- ❌ "They can't do files/folders" — no longer true
- ❌ "We have better AI" — same models, same APIs
- ❌ Anything comparing on general capability — they have $10M and we have documents

---

## 6. What this should change in our plan

- **Lead with Windows.** They're not there. It's most of India. Build Windows first, not second.
- **Lead with data, not text.** Text summarization is the crowded lane. Numbers and files is the empty one.
- **Silent is a feature, market it as one.** Nobody else is saying this.
- **Ship something before you write another document.** He was 4 weeks old at his YC launch. We are months in with zero code.
- **Use the video channel.** He won with demo videos. That's a channel we can actually access.
