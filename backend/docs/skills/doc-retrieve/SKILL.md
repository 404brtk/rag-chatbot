---
name: doc-retrieve
description: Retrieves relevant documentation and context from the local RAG knowledge base.
---

# Local RAG Context Retrieval

Use this skill exclusively when the user explicitly requests context retrieval using the keyword `doc-retrieve` or `/doc-retrieve`.

## Agent Instructions:

1. Extract the raw search intent or text that follows the keyword from the user's prompt.
2. Refine the query: Transform the raw input into an optimized search query. Strip away the trigger keywords, conversational filler, or unrelated code context. Rewrite it to focus strictly on core technical concepts, function names, or specific error messages that will yield the best embedding and semantic match results.
3. Replace `$QUERY` in the command below with your newly refined search query.
4. Execute the appropriate command below for your OS shell to fetch the context.
5. Use the returned Markdown context to accurately answer the user's question.

### On Windows (PowerShell):

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/documents/retrieve/" -Method Post -ContentType "application/json" -Body '{"query": "$QUERY"}'
```

### On Linux / macOS (Bash):

```bash
curl -s -X POST http://localhost:8000/api/documents/retrieve/ -H "Content-Type: application/json" -d '{"query": "$QUERY"}'
```
