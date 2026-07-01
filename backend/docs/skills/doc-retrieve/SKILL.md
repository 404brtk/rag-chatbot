---
name: doc-retrieve
description: Retrieves relevant documentation and context from the local RAG knowledge base.
---

# Local RAG Context Retrieval

Use this skill exclusively when the user explicitly requests context retrieval using the keyword `doc-retrieve` or `/doc-retrieve`.

## Agent Instructions:

1. Extract the raw search intent or text that follows the keyword from the user's prompt. Use recent conversation history to resolve pronouns, references ("it", "that"), or vague follow-ups into a standalone query.
2. Refine the query into two distinct strings (`refined_english_query` and `refined_polish_query`) adhering strictly to these guidelines:
   1. Language Detection: Detect if the input query is primarily in "polish" or "english".
   2. Typos & Grammar: Correct any typos, spelling errors, or grammatical issues in both outputs.
   3. Query Intent Detection & Tailored Refinement:
      - Practical / How-To Intent ("How do I use X?", "Implement Y"): Frame around clear action verbs and exact API/identifier co-occurrence (e.g., "how to configure [API]").
      - Conceptual Intent ("What is X?", "Architecture of Y"): Focus on core architectural concepts, fundamental mechanisms, and high-level definitions.
      - Debugging / Error Intent ("Fix error X", "Why does Y crash?"): Focus strictly on exact error messages, exception types, and root cause resolution phrases.
   4. Keyword Expansion & Synonyms:
      - Expand the query naturally using relevant synonyms or search keywords.
      - Keep the expanded query concise and highly focused on the user's search intent.
      - Avoid "query drift" (do not add unrelated tech terms or generic categories that shift the original meaning).
   5. Preserve Jargon and Brands: Keep proper nouns, brand names, product models, exact code identifiers, and domain-specific jargon intact in both languages.
   6. Translation:
      - Translate the core intent of the query accurately.
      - Ensure 'refined_english_query' sounds natural to native English searchers.
      - Ensure 'refined_polish_query' sounds natural to native Polish searchers (handling proper Polish search terms).
   7. Context Resolution: If the query references prior conversation, incorporate enough context into the refined queries so they are meaningful standalone (resolving pronouns like "it", "that", or vague references).
   8. Search Optimization Rules:
      - Natural Language Intent: Frame queries using natural, task-oriented action phrases rather than detached keyword lists. Natural intent matching aligns better with documentation headers.
      - Avoid Meta-Filler: Do not insert generic meta-words like "example", "sample", "tutorial", "snippet", or programming language names unless explicitly part of the search goal.
      - Preserve Code Syntax: Keep exact technical identifiers, function names, and directive syntax intact as naturally used in code.
   9. Technical Term Normalization: When a technical term appears with non-standard formatting or variable spacing/hyphenation, include common standard variants to maximize retrieval recall.


3. Replace `$ENG_QUERY` and `$POL_QUERY` in the commands below with your refined search strings.
4. Execute the appropriate command below for your OS shell to fetch the context.
5. Use the returned Markdown context to accurately answer the user's question.

### On Windows (PowerShell):

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/documents/retrieve/" -Method Post -ContentType "application/json" -Body '{"refined_english_query": "$ENG_QUERY", "refined_polish_query": "$POL_QUERY"}'
```

### On Linux / macOS (Bash):

```bash
curl -s -X POST http://localhost:8000/api/documents/retrieve/ -H "Content-Type: application/json" -d '{"refined_english_query": "$ENG_QUERY", "refined_polish_query": "$POL_QUERY"}'
```
