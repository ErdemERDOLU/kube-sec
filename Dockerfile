# DEPRECATED: Bu Docker imaji artik bakim altinda degildir. Kube-Sec yalnizca
# masaustu (PyInstaller ile paketlenmis) uygulama olarak desteklenmektedir.
# UYARI: Bu imaj 0.0.0.0'a bind eder ve varsayilan olarak kimlik dogrulama icermez.
# Yalnizca guvenilir/izole ag ortamlarinda kullanin.
# Ag erisim kontrolu icin KUBESEC_ALLOW_NETWORK_BIND ve KUBESEC_ACCESS_PASSWORD
# env var'larini kullanin (bkz. CLAUDE.md).
# Ornek: docker run -e KUBESEC_ALLOW_NETWORK_BIND=1 -e KUBESEC_ACCESS_PASSWORD=gizli-parola kube-sec

FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY src/ ./src/

# Set the entry point for the application
CMD ["python", "src/main.py"]
