# PDF Audiobook Generator

Local Docker tool that converts PDFs into audiobook MP3 files using Kokoro TTS.

## Current Status

- Extracts PDF text
- Saves structured book JSON
- Saves transcript TXT
- Creates output folders for chapters, chunks, WAV, and MP3
- GPU enabled (single) - for now.

For summaries requirements:

- Ollama Version0.30.11 (Should be installed in the machine not in the docker container - installation info bellow)
- Model:qwen3:8b.

## Run

Place a PDF inside:

```bash
input/

===============
To run the app 
spin the docker container from within the folder
===============

docker compose up --build
 
This generates the initial book read using Kokoro. 

======================= 
To generate the Summary
=======================

docker compose run --rm pdf-audiobook \
python /app/build_summary.py "/output/<Book>" 

example: docker compose run --rm pdf-audiobook python /app/build_summary.py "/output/AI Revolution_DVG_2025"

==========
IMPORTANT:
==========
If any changes to summary/ollama.py or refine_summary.py in case of changes to the seed or any updates to the prompt execute this sequence:


sudo rm -rf "output/AI Revolution_DVG_2025"/summary*

docker compose build

docker compose run --rm pdf-audiobook python /app/refine_summary.py "/output/<book name>" --force   (make sure the main book file is already created)

Once you get the desired output in summary/book_memories.txt dont use --force anymore. just run

docker compose run --rm pdf-audiobook python /app/refine_summary.py "/output/<book name>"




==============
# Ollama Setup
===============

The summary pipeline uses a locally running Ollama server to generate:

- Book Memories (`book_memories.txt`)
- Quick Companion (`quick.txt`)


===================================
Ollama installation and information
===================================

The application communicates with Ollama through its HTTP API.

Default endpoint:

```
http://host.docker.internal:11434
```

or

```
http://localhost:11434
```

depending on your Docker configuration.

---

## Verify Ollama is Running

Before generating summaries, make sure Ollama is running:

```bash
ollama serve
```

In another terminal:

```bash
ollama list
```

You should see the installed models, for example:

```text
NAME
qwen3:32b
llama3.1:8b
gemma3:27b
```

---

## Test the Connection

Verify the API is reachable:

```bash
curl http://localhost:11434/api/tags
```

A successful response returns a JSON list of installed models.

---

## Pull a Model

If the required model is not installed:

```bash
ollama pull qwen3:32b
```

or

```bash
ollama pull llama3.1:8b
```

---

## Running the Summary Pipeline

### Step 1 — Generate Book Memories

Creates:

```
summary/book_memories.txt
```

```bash
docker compose run --rm pdf-audiobook \
python /app/build_summary.py "/output/<BOOK_FOLDER>" --force
```

---

### Step 2 — Generate Quick Companion

Reads:

```
summary/book_memories.txt
```

Creates:

```
summary/quick.txt
```

```bash
docker compose run --rm pdf-audiobook \
python /app/refine_summary.py "/output/<BOOK_FOLDER>" --force
```

---

## Environment Variables

The provider can be configured using:

```text
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3:32b
```

These can be overridden from the command line:

```bash
python refine_summary.py \
"/output/<BOOK_FOLDER>" \
--model qwen3:32b \
--base-url http://host.docker.internal:11434
```

---

## Troubleshooting

### Verify the server

```bash
curl http://localhost:11434/api/version
```

---

### List installed models

```bash
ollama list
```

---

### View running models

```bash
ollama ps
```

---

### Stop Ollama

```bash
Ctrl + C
```

or

```bash
pkill ollama
```

---

### Restart Ollama

```bash
ollama serve
```

---

## Notes

- Ollama must be running before generating summaries.
- Summary generation is performed entirely offline.
- No external APIs or cloud services are required.
- Larger models produce more natural summaries but require more RAM and generate more slowly.
