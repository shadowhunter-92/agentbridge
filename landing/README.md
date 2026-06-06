# AgentBridge landing page — deploy in 10 minutes

A single static file (`index.html`). No build step. This is a **demand instrument** — its only job
is to measure whether people want this (email signups).

## Step 1 — get a form endpoint (captures the emails)
Pick ONE (all free, no code):
- **Formspree** (easiest): sign up → create a form → copy its endpoint URL
  (looks like `https://formspree.io/f/abcd1234`).
- **Tally** or **Google Forms**: create a 1-field form; use its POST/endpoint, or just link to it.

In `index.html`, find the **two** places that say:
```
action="REPLACE_WITH_YOUR_FORM_ENDPOINT"
```
and paste your endpoint URL in both. (Until you do, the form still "works" as a demo — it shows the
thank-you state — but it does NOT save emails. Set the endpoint before you share it.)

## Step 2 — deploy (pick one)
- **Netlify Drop**: go to app.netlify.com/drop and drag the `landing` folder in. Done — you get a URL.
- **Vercel**: `vercel` in this folder, or import via the dashboard.
- **GitHub Pages**: push to a repo, enable Pages.
- **Cloudflare Pages**: connect the repo or upload.

## Step 3 — add analytics (know if anyone visits)
Add one line before `</head>` — e.g. **Plausible** (`<script defer data-domain="yourdomain" src="https://plausible.io/js/script.js"></script>`)
or Cloudflare Web Analytics. You want: visitors, and signups ÷ visitors (conversion).

## Step 4 — point traffic at it
Link the page from your launch posts, GitHub-issue replies, and outreach DMs.

## What "success" looks like
~10 signups (or 3+ "I'd pay/pilot" replies) in ~2 weeks → real signal → build the EU-AI-Act audit
pack for them. Crickets after genuine outreach → pivot the angle, don't build more.

## Editing copy
Everything is in `index.html` (inline CSS/JS). The headline, the EU-AI-Act table, and the two
waitlist forms are clearly labeled. Tweak the message per audience and re-deploy (drag again).
