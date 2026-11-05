# Chill: a casual programming language + compiler

## Setup
    pip install -r requirements.txt
    cd frontend && npm install && cd ..

## Run the app (two terminals, from the project root)
    uvicorn backend.app:app --reload        # API on :8000
    cd frontend && npm run dev              # UI on :5173

## Use the compiler from the command line
    python -m chill examples/recipe.chill --run
    python -m chill examples/recipe.chill -o out && ./out
    python -m chill prog.chill --tokens --ast --ir --opt-ir --llvm

## Tests
    pytest

## Documentation
1. [System design](docs/01-system-design.md): architecture, pipeline, data model, API, decisions
2. [Tech stack](docs/02-tech-stack.md): what each tool is, why it was chosen, alternatives
3. [Rebuild guide](docs/03-rebuild-guide.md): step-by-step instructions to recreate the project
4. [Interview Q&A](docs/04-interview-qa.md): pitch, demo script, and answers tied to this code
