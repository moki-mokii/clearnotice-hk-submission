# ClearNotice HK

We built ClearNotice HK for Hack4SDG 2026 to help people understand Hong Kong community notices. Paste a webpage link or notice text to get a concise action card in Traditional Chinese or English, with dates, eligibility, costs and original source evidence.

## Demo

[Watch our English narrated demonstration](https://moki-mokii.github.io/clearnotice-hk-submission/submission/) · [Download the MP4](https://moki-mokii.github.io/clearnotice-hk-submission/submission/demo/ClearNotice_HK_demo_2026-10-17.mp4)

The web recording makes a real DeepSeek request. The extension segment replays the same saved result. Screen playback runs at the labelled 1.3× speed. The historical notice demonstrates the product rather than current booking availability.

This repository contains the web application, deployment setup and demo page. The extension shown in the video uses a local backend and is not included in this package.

## Run locally

Use Python 3.12 and install the dependencies:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
& .\.venv\Scripts\python.exe deploy/start.py
```

Open http://127.0.0.1:8000 for the application and http://127.0.0.1:8000/submission/ for the demo page. Default example mode runs saved fictional notices without an API key.

For other notices, set `LLM_MODE=live` and `LLM_API_KEY` in your local `.env`. The supplied configuration uses DeepSeek. Restart after changing settings. Keep credentials out of source code and frontend files.

## Deploy

Connect the repository to a Render web service using `render.yaml`, or build and run the Docker image:

```text
docker build -t clearnotice-hk .
docker run --rm -p 8000:8000 clearnotice-hk
```

Set live-mode credentials in the hosting platform's environment settings, or pass a local environment file with Docker's `--env-file` option. Live mode incurs model API charges. We tested Python startup locally. The Docker setup has not yet been build-tested. Public live-model hosting needs access controls and usage limits.

## Current scope

We support webpage text and pasted notices, full explanations, source evidence, copying and printing. PDF and image input are not available yet. The model can still misinterpret a notice, so confirm important dates, costs and eligibility with the original source. Our next step is a small reading-task pilot. We have not completed a user study.
