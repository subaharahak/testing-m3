# Card Checker Setup

This project requires a Python virtual environment with specific dependencies.

## Setup Instructions

### Option 1: Using Batch Script (Windows)
```bash
setup_venv.bat
```

### Option 2: Using PowerShell Script (Windows)
```powershell
.\setup_venv.ps1
```

### Option 3: Manual Setup
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows)
venv\Scripts\activate.bat

# Activate virtual environment (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running the Script

After setting up the virtual environment:

1. Activate the virtual environment:
   ```bash
   # Windows
   venv\Scripts\activate.bat
   
   # Linux/Mac
   source venv/bin/activate
   ```

2. Run the script:
   ```bash
   python p.py
   ```

## Required Files

Make sure you have the following files in your directory:
- `p.py` - Main script
- `cc.txt` - Card data file
- `site.txt` - Domain URL
- `proxy.txt` - Proxy list
- `cookies_*-1.txt` and `cookies_*-2.txt` - Cookie files

## Dependencies

The script requires these Python packages:
- requests
- beautifulsoup4
- user-agent
- urllib3
- lxml

All dependencies are listed in `requirements.txt`. 