# ChitChat

A ChatGPT-style web chat app built on the OpenAI Responses API, built in phases (see `docs/`).

## Run
```
cp .env.example .env   # add your OPENAI_API_KEY
uv run uvicorn app.main:app --reload
```

## Test
```
uv run pytest
```
