# CV Analyzer API - Frontend Integration Guide

Endpoint for analyzing PDF CVs against interview questions to identify what information is available and what clarification questions need to be asked.

## Overview

| Endpoint | Purpose |
|----------|---------|
| `POST /cv/analyze` | Analyze a PDF CV against interview questions |

The CV analyzer uses Gemini 2.5 Flash to process PDF documents natively and compare the content against your knockout and qualification questions.

---

## Analyze CV

Analyze a PDF CV against a set of interview questions.

```
POST /cv/analyze
Content-Type: application/json
```

### Request Body

```typescript
interface CVAnalyzeRequest {
  pdf_base64: string;  // Base64-encoded PDF file
  knockout_questions: CVQuestion[];
  qualification_questions: CVQuestion[];
}

interface CVQuestion {
  id: string;           // e.g., "ko_1" or "qual_1"
  question: string;     // The question text
  ideal_answer?: string; // For qualification questions (optional)
}
```

### Example Request

```json
{
  "pdf_base64": "JVBERi0xLjQKJeLjz9...",
  "knockout_questions": [
    {
      "id": "ko_1",
      "question": "Heb je een rijbewijs B?"
    },
    {
      "id": "ko_2",
      "question": "Ben je beschikbaar voor weekendwerk?"
    }
  ],
  "qualification_questions": [
    {
      "id": "qual_1",
      "question": "Hoeveel jaar ervaring heb je met CNC machines?",
      "ideal_answer": "Minstens 2 jaar hands-on ervaring met CNC machines."
    },
    {
      "id": "qual_2",
      "question": "Beschrijf je ervaring met kwaliteitscontrole.",
      "ideal_answer": "Ervaring met ISO-normen en meetinstrumenten."
    }
  ]
}
```

### Response

```typescript
interface CVAnalyzeResponse {
  knockout_analysis: QuestionAnalysis[];
  qualification_analysis: QuestionAnalysis[];
  cv_summary: string;              // Brief candidate profile summary
  clarification_questions: string[]; // Questions to ask the candidate
}

interface QuestionAnalysis {
  id: string;
  question_text: string;
  cv_evidence: string;           // What the CV says about this topic
  is_answered: boolean;          // Whether the CV provides sufficient info
  clarification_needed: string | null; // Suggested clarification question
}
```

### Example Response

```json
{
  "knockout_analysis": [
    {
      "id": "ko_1",
      "question_text": "Heb je een rijbewijs B?",
      "cv_evidence": "Geen vermelding van rijbewijs in CV",
      "is_answered": false,
      "clarification_needed": "Heb je een rijbewijs B?"
    },
    {
      "id": "ko_2",
      "question_text": "Ben je beschikbaar voor weekendwerk?",
      "cv_evidence": "Geen informatie over beschikbaarheid",
      "is_answered": false,
      "clarification_needed": "Ben je beschikbaar voor weekendwerk?"
    }
  ],
  "qualification_analysis": [
    {
      "id": "qual_1",
      "question_text": "Hoeveel jaar ervaring heb je met CNC machines?",
      "cv_evidence": "3 jaar als CNC-operator bij Bedrijf X (2020-2023), werkte met Mazak en Haas machines",
      "is_answered": true,
      "clarification_needed": null
    },
    {
      "id": "qual_2",
      "question_text": "Beschrijf je ervaring met kwaliteitscontrole.",
      "cv_evidence": "Vermeld: 'verantwoordelijk voor kwaliteitscontrole' maar geen details over methodes",
      "is_answered": false,
      "clarification_needed": "Welke meetinstrumenten en kwaliteitsnormen heb je ervaring mee?"
    }
  ],
  "cv_summary": "Technisch geschoolde CNC-operator met 3 jaar ervaring bij een productietedrijf. Ervaring met Mazak en Haas machines, basis kwaliteitscontrole ervaring.",
  "clarification_questions": [
    "Heb je een rijbewijs B?",
    "Ben je beschikbaar voor weekendwerk?",
    "Welke meetinstrumenten en kwaliteitsnormen heb je ervaring mee?"
  ]
}
```

### Error Responses

| Status | Detail |
|--------|--------|
| 400 | Invalid base64 encoding |
| 422 | Validation error (missing required fields) |
| 500 | Internal server error (PDF processing failed) |

---

## Frontend Implementation

### Converting File to Base64

```typescript
async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => {
      // Remove data URL prefix (e.g., "data:application/pdf;base64,")
      const base64 = (reader.result as string).split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
  });
}
```

### Calling the API

```typescript
interface Question {
  id: string;
  question: string;
  ideal_answer?: string;
}

async function analyzeCv(
  pdfFile: File,
  knockoutQuestions: Question[],
  qualificationQuestions: Question[]
): Promise<CVAnalyzeResponse> {
  const pdfBase64 = await fileToBase64(pdfFile);

  const response = await fetch('/cv/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pdf_base64: pdfBase64,
      knockout_questions: knockoutQuestions,
      qualification_questions: qualificationQuestions,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }

  return response.json();
}
```

### Example Usage

```typescript
// When user uploads a CV file
async function handleCvUpload(event: React.ChangeEvent<HTMLInputElement>) {
  const file = event.target.files?.[0];
  if (!file || file.type !== 'application/pdf') {
    showError('Please upload a PDF file');
    return;
  }

  setLoading(true);

  try {
    // Get questions from your pre-screening config
    const knockoutQuestions = preScreening.knockout_questions.map(q => ({
      id: q.id,
      question: q.question_text,
    }));

    const qualificationQuestions = preScreening.qualification_questions.map(q => ({
      id: q.id,
      question: q.question_text,
      ideal_answer: q.ideal_answer,
    }));

    const result = await analyzeCv(file, knockoutQuestions, qualificationQuestions);

    // Display results
    setCvSummary(result.cv_summary);
    setClarificationQuestions(result.clarification_questions);
    setAnalysis({
      knockout: result.knockout_analysis,
      qualification: result.qualification_analysis,
    });
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
}
```

---

## Integration with Pre-Screening

The CV analyzer is designed to work alongside the interview questions defined in your pre-screening configuration. A typical workflow:

```
┌─────────────────────┐
│  Candidate uploads  │
│       CV (PDF)      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Fetch pre-screening│
│    questions for    │
│      vacancy        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  POST /cv/analyze   │
│  with PDF + questions│
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Display results:   │
│  - CV summary       │
│  - What's answered  │
│  - What needs       │
│    clarification    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Start screening    │
│  with clarification │
│  questions          │
└─────────────────────┘
```

---

## TypeScript Types

```typescript
// Request types
interface CVQuestion {
  id: string;
  question: string;
  ideal_answer?: string;
}

interface CVAnalyzeRequest {
  pdf_base64: string;
  knockout_questions: CVQuestion[];
  qualification_questions: CVQuestion[];
}

// Response types
interface QuestionAnalysis {
  id: string;
  question_text: string;
  cv_evidence: string;
  is_answered: boolean;
  clarification_needed: string | null;
}

interface CVAnalyzeResponse {
  knockout_analysis: QuestionAnalysis[];
  qualification_analysis: QuestionAnalysis[];
  cv_summary: string;
  clarification_questions: string[];
}
```

---

## Notes

1. **PDF Size Limit**: While there's no hard limit, very large PDFs (>10MB) may take longer to process. Consider compressing large files before upload.

2. **Language**: The agent returns responses in Dutch (Vlaams nl-BE), matching the rest of the system.

3. **Processing Time**: Typical CV analysis takes 5-15 seconds depending on document complexity.

4. **What's Typically NOT in CVs**: The agent understands that certain information (like driver's license, weekend availability, salary expectations) is rarely included in CVs and will appropriately flag these for clarification.

5. **Evidence Quality**: The `cv_evidence` field provides specific quotes or paraphrases from the CV, making it easy to verify the agent's analysis.
