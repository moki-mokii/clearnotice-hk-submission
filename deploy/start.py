"""Portable single-worker start for Docker and Python hosting platforms."""
import os
import sys
from pathlib import Path
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    uvicorn.run('app.main:app',host=os.environ.get('HOST','0.0.0.0'),port=int(os.environ.get('PORT','8000')),workers=1)
