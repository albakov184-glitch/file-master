FROM python:3.12-slim-trixie

ARG WITH_CALIBRE=1
ARG PANDOC_VERSION=3.6.4

# Инструменты конвертации:
#  - contrib/non-free нужны ради 7zip-rar (распаковка RAR);
#  - Calibre (эл. книги MOBI/AZW3) можно отключить: --build-arg WITH_CALIBRE=0;
#  - свежий Pandoc 3.x ставим из официального релиза (amd64 и arm64);
#  - ImageMagick по умолчанию запрещает PS/EPS/PDF — снимаем запрет (Ghostscript свежий).
RUN sed -i 's/^Components: main$/Components: main contrib non-free/' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw \
      ffmpeg imagemagick librsvg2-bin ghostscript \
      tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
      7zip 7zip-rar djvulibre-bin curl ca-certificates \
      fonts-dejavu fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-core \
 && if [ "$WITH_CALIBRE" = "1" ]; then apt-get install -y --no-install-recommends calibre; fi \
 && curl -fsSL -o /tmp/pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-$(dpkg --print-architecture).deb" \
 && dpkg -i /tmp/pandoc.deb && rm /tmp/pandoc.deb \
 && for f in /etc/ImageMagick-*/policy.xml; do sed -i '/pattern="\(PS\|PS2\|PS3\|EPS\|PDF\|XPS\)"/d' "$f"; done \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 1000 bot && mkdir -p /data && chown bot /data
USER bot
ENV DATA_DIR=/data PYTHONUNBUFFERED=1 HOME=/home/bot

CMD ["python", "-m", "app.bot.main"]
