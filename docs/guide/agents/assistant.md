# Assistant (chatbot)

Owned by Anooj.

## 1. Introduction

Answers questions in plain language ("What uptime does our SaaS contract
commit to?", "How many requests wait for approval?") from the platform's own
data, without showing anyone data they may not see.

## 2. Technical implementation

| Part | Detail |
|---|---|
| Model | Ollama on the host: `llama3.2:3b` for answers, `nomic-embed-text` for embeddings |
| Retrieval | `document_embeddings` (pgvector): contract clauses, document text, business rules and current records, re-indexed every minute; access checked per chunk |
| Intent first | Greetings, remarks and topic-only messages get a direct reply; licence anomalies come from live scores |
| API | `/api/chat/*` |

## 3. Functional implementation

Decide intent → retrieve the chunks this user may see → answer only from
them, citing the source (`CT-…`, `DOC-…`, `PR-…`, a rule key) → say so when
nothing relevant is found.

## 4. Results and evaluation

`tests/e2e/chatbot_eval.py`: 20/20 questions answered as expected, including
access limits (a requester asking for bank details is refused). 66 unit tests.
Without Ollama the rest of the platform works; the assistant can't answer.
