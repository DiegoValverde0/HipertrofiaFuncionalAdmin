WeasyPrint installation notes (Windows / WSL)

This project can generate PDFs server-side using WeasyPrint. WeasyPrint relies on native libraries (cairo, pango, gdk-pixbuf, libffi, etc.). On Windows the easiest and most robust options are:

Option A — Use WSL (recommended)
1. Install WSL and Ubuntu (Windows Subsystem for Linux):
   Open an elevated PowerShell and run:

   wsl --install -d ubuntu

   Then launch Ubuntu from the Start menu and complete initial setup.

2. Inside the Ubuntu shell, install system deps and WeasyPrint:

   sudo apt update && sudo apt install -y build-essential python3-dev python3-pip python3-venv \
     libffi-dev libssl-dev libxml2 libxml2-dev libxslt1-dev zlib1g-dev libjpeg-dev libpng-dev \
     libcairo2 libcairo2-dev libpango1.0-0 libpango1.0-dev libgdk-pixbuf2.0-0 shared-mime-info

   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip setuptools wheel
   pip install WeasyPrint

3. Run your Flask app inside WSL or build a production container using the same packages.

Option B — MSYS2 (native Windows toolchain)
1. Install MSYS2 from https://www.msys2.org/ and follow the post-install steps to update the system.
2. Open the "MSYS2 MinGW 64-bit" shell and install dependencies:

   pacman -Syu
   pacman -S mingw-w64-x86_64-toolchain mingw-w64-x86_64-cairo mingw-w64-x86_64-pango mingw-w64-x86_64-gdk-pixbuf mingw-w64-x86_64-libffi mingw-w64-x86_64-libjpeg-turbo mingw-w64-x86_64-libpng mingw-w64-x86_64-libxml2 mingw-w64-x86_64-libxslt

3. In the MinGW shell create/activate a virtualenv and pip install WeasyPrint:

   python -m venv .venv
   source .venv/Scripts/activate
   pip install --upgrade pip setuptools wheel
   pip install WeasyPrint

Note: MSYS2 installation is more involved; many users prefer WSL or Docker.

Option C — Docker (recommended for production)
- Use an official Python image and apt install the system dependencies in the Dockerfile, then pip install WeasyPrint. Example (Debian/Ubuntu base):

FROM python:3.11-slim
RUN apt-get update && apt-get install -y build-essential libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info libjpeg-dev libpng-dev libxml2 libxslt1.1
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy project ... etc.

Verification
- After installation, you can verify in Python:

python -c "from weasyprint import HTML; print('weasy ok')"

If this prints 'weasy ok' without errors, the package is installed and you can use the /membresias/pdf/<token>?download=1 endpoint to get PDFs.

Notes
- WeasyPrint versions change; the project requirements specify `WeasyPrint>=59.0` to ensure compatibility.
- If you host behind a reverse proxy ensure `request.url_root` is set properly so WeasyPrint can resolve relative assets.
