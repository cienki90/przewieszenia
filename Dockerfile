# Generator projektów nN - wersja przeglądarkowa (serwer WWW) do uruchomienia na NAS.
#   docker compose up -d        ->  http://<adres NAS>:8765
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# sv-ttk to tylko wygląd okna - w wersji przeglądarkowej niepotrzebny
RUN grep -v "^sv-ttk" requirements.txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt
COPY . .
ENV GENERATOR_DANE=/dane PYTHONUNBUFFERED=1
VOLUME /dane
EXPOSE 8765
CMD ["python", "generator_web.py", "--port", "8765"]
