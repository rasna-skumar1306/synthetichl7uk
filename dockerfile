FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

RUN mkdir -p data/hl7_inbound data/raw

CMD [ "python", "src/legacy_feed.py", "src/forge.py" ]