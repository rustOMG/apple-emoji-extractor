FROM python:3.11-slim

WORKDIR /app

RUN python -m pip install --no-cache-dir \
    bplist==1.1 \
    "fonttools>=4.48.1,<5" \
    Pillow==10.4.0

COPY extract.py /app/extract.py

ENTRYPOINT ["python", "/app/extract.py", "--input-tar", "-", "--output-dir", "/out"]
