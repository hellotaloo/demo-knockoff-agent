# Backend Brief: Interview Analysis Agent

## Overview

We need a small AI agent that evaluates a set of pre-screening interview questions before they go live. The agent simulates how candidates would experience the interview and returns per-question analytics (clarity, drop-off risk, improvement tips) plus an overall verdict. The frontend already has the UI built with dummy data — this agent provides the real data.

---

## Purpose

Recruiters create pre-screening interviews with 3-8 questions (knockout + qualifying). Before publishing, they want to know:

1. Are any questions unclear or ambiguous?
2. Which questions are likely to cause candidate drop-off?
3. How long will the interview feel to a candidate?
4. What's the overall quality of the interview?

The agent acts as a "dry run" — it evaluates the questions from a candidate's perspective without actually running interviews.

---

## Input

```json
POST /api/pre-screenings/{id}/analyze

{
  "questions": [
    {
      "id": "q1",
      "text": "Mag je wettelijk werken in België?",
      "type": "knockout"
    },
    {
      "id": "q2",
      "text": "Hoe goed ben je met cijfers?",
      "type": "qualifying"
    }
  ],
  "vacancy": {
    "id": "v1",
    "title": "Bakkerijmedewerker",
    "description": "..."
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `questions` | array | The interview questions in order |
| `questions[].id` | string | Question ID |
| `questions[].text` | string | The question text |
| `questions[].type` | `"knockout"` \| `"qualifying"` | Question type |
| `vacancy` | object | Vacancy context for the agent to understand the role |

---

## Output

```json
{
  "summary": {
    "completionRate": 64,
    "avgTimeSeconds": 107,
    "verdict": "good",
    "verdictHeadline": "Dit interview is goed opgebouwd",
    "verdictDescription": "De knockout-vragen zijn helder en snel te beantwoorden. Let op bij vraag 5 en 6 — open vragen aan het einde veroorzaken de meeste drop-off. Overweeg deze te herformuleren of te vereenvoudigen."
  },
  "questions": [
    {
      "questionId": "q1",
      "completionRate": 98,
      "avgTimeSeconds": 8,
      "dropOffRisk": "low",
      "clarityScore": 95,
      "tip": null
    },
    {
      "questionId": "q2",
      "completionRate": 71,
      "avgTimeSeconds": 24,
      "dropOffRisk": "high",
      "clarityScore": 62,
      "tip": "Deze vraag is te vaag. Herformuleer naar een concreet scenario, bijv. 'Kan je nauwkeurig hoeveelheden afwegen?'"
    }
  ],
  "funnel": [
    { "step": "Start", "candidates": 200 },
    { "step": "q1", "candidates": 196 },
    { "step": "q2", "candidates": 142 },
    { "step": "Completed", "candidates": 128 }
  ]
}
```

### Field Reference

**`summary`**

| Field | Type | Description |
|-------|------|-------------|
| `completionRate` | number (0-100) | Estimated % of candidates that would complete the full interview |
| `avgTimeSeconds` | number | Estimated average duration in seconds for a full completion |
| `verdict` | `"excellent"` \| `"good"` \| `"needs_work"` \| `"poor"` | Overall quality rating |
| `verdictHeadline` | string | Short Dutch headline for the UI banner |
| `verdictDescription` | string | 1-2 sentence Dutch explanation with actionable advice |

**`questions[]`**

| Field | Type | Description |
|-------|------|-------------|
| `questionId` | string | Maps back to input question ID |
| `completionRate` | number (0-100) | Estimated % of candidates that would answer this question (cumulative — accounts for prior drop-off) |
| `avgTimeSeconds` | number | Estimated seconds a candidate spends on this question |
| `dropOffRisk` | `"low"` \| `"medium"` \| `"high"` | Risk that candidates abandon at this question |
| `clarityScore` | number (0-100) | How clear and unambiguous the question is |
| `tip` | string \| null | Improvement suggestion in Dutch. `null` if the question is fine. |

**`funnel[]`**

| Field | Type | Description |
|-------|------|-------------|
| `step` | string | `"Start"`, question ID, or `"Completed"` |
| `candidates` | number | Simulated number of remaining candidates at this step (starts at 200) |

---

## Agent Behavior

The agent should evaluate each question considering:

1. **Clarity** — Is the question unambiguous? Would a candidate understand what's being asked without re-reading?
2. **Cognitive load** — How much effort does it take to answer? Open-ended questions score lower.
3. **Position effect** — Questions later in the sequence have higher drop-off naturally. Open questions at the end amplify this.
4. **Relevance to vacancy** — Does the question make sense for this specific role?
5. **Question type impact** — Knockout questions should be simple yes/no. Qualifying questions can be more complex but shouldn't be vague.

### Tip Generation Rules

- Only generate a tip when `clarityScore < 85` or `dropOffRisk` is `"medium"` or `"high"`
- Tips must be in Dutch
- Tips should be specific and actionable (not generic advice)
- Reference the actual question text when suggesting rephrasing
- Keep tips to 1-2 sentences max

### Verdict Logic

| Verdict | Condition |
|---------|-----------|
| `excellent` | All questions have `clarityScore >= 85` and `completionRate >= 80%` |
| `good` | Overall `completionRate >= 50%` and max 2 questions with `dropOffRisk: "high"` |
| `needs_work` | Overall `completionRate >= 30%` or 3+ questions with medium/high risk |
| `poor` | Overall `completionRate < 30%` or majority of questions unclear |

---

## Integration Notes

- The analysis runs on-demand when the user clicks the analytics tab in the Test Suite view
- Cache the result per pre-screening version (invalidate when questions change)
- Target response time: < 5 seconds
- The funnel always starts at 200 simulated candidates (this is a display convention)
- Language: all generated text (tips, verdict) must be in Dutch

---

## Frontend Component

The UI is already built at `components/blocks/interview-analytics/interview-analytics-panel.tsx`. Currently uses hardcoded dummy data. When the API is ready, replace the constants with a fetch call and loading state.
