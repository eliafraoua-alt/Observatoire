FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir streamlit==1.35.0 plotly==5.22.0 requests==2.32.3 pandas==2.2.2
COPY app.py .
EXPOSE 8512
CMD ["streamlit", "run", "app.py", "--server.port=8512", "--server.address=0.0.0.0", "--server.headless=true"]
