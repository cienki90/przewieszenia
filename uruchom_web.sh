#!/bin/sh
# Generator nN w przeglądarce - uruchomienie bez Dockera (NAS z Pythonem 3.10+, Linux, macOS).
# Pierwszy raz:  python3 -m pip install -r requirements.txt
cd "$(dirname "$0")" && exec python3 generator_web.py "$@"
