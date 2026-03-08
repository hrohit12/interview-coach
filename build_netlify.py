import os
import sys
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
DIST_DIR = BASE_DIR / "dist"

def build(backend_url):
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir()

    # Clean up trailing slashes
    backend_url = backend_url.rstrip('/')

    # Copy static files
    shutil.copytree(BASE_DIR / "static", DIST_DIR / "static")

    # Process HTML templates
    templates_dir = BASE_DIR / "templates"
    for file in templates_dir.glob("*.html"):
        content = file.read_text("utf-8")
        
        # 1. Update internal links for static hosting
        content = content.replace('href="/"', 'href="/index.html"')
        content = content.replace('href="/setup"', 'href="/setup.html"')
        content = content.replace('href="/interview"', 'href="/interview.html"')
        content = content.replace('href="/report"', 'href="/report.html"')
        content = content.replace("window.location.href = '/'", "window.location.href = '/index.html'")
        content = content.replace("window.location.href = '/setup'", "window.location.href = '/setup.html'")
        content = content.replace("window.location.href = '/interview'", "window.location.href = '/interview.html'")
        content = content.replace("window.location.href = '/report'", "window.location.href = '/report.html'")

        # 2. Inject BACKEND_URL prefix for API calls
        config_script = f'''
  <script>
    // Injected by build script
    const BACKEND_URL = "{backend_url}"; 
  </script>
</head>'''
        content = content.replace('</head>', config_script)

        # Update fetch calls to use the BACKEND_URL
        content = content.replace("fetch('/", "fetch(BACKEND_URL + '/")
        content = content.replace("fetch(`/", "fetch(BACKEND_URL + `/")

        # Save to dist
        (DIST_DIR / file.name).write_text(content, "utf-8")

    # Update JS WebSocket configuration
    main_js_path = DIST_DIR / "static" / "js" / "main.js"
    if main_js_path.exists():
        js_content = main_js_path.read_text("utf-8")
        js_content = js_content.replace("window.location.href = '/'", "window.location.href = '/index.html'")
        main_js_path.write_text(js_content, "utf-8")

    interview_js_path = DIST_DIR / "static" / "js" / "interview.js"
    if interview_js_path.exists():
        js_content = interview_js_path.read_text("utf-8")
        # Replace the wss://location.host/ws-interview logic with WS prefix
        js_content = js_content.replace(
            "const ws = new WebSocket(`${proto}://${location.host}/ws-interview`);",
            f"const ws_url = BACKEND_URL.replace('http', 'ws');\n    const ws = new WebSocket(`${{ws_url}}/ws-interview`);"
        )
        js_content = js_content.replace("window.location.href = '/report'", "window.location.href = '/report.html'")
        js_content = js_content.replace("window.location.href = '/'", "window.location.href = '/index.html'")
        interview_js_path.write_text(js_content, "utf-8")

    print(f"Build complete! Netlify Ready folder is: {DIST_DIR}")
    print(f"Configured to connect to backend at: {backend_url}")

if __name__ == "__main__":
    url = "http://127.0.0.1:8000"
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        print("Warning: No backend URL provided. Defaulting to http://127.0.0.1:8000")
        print("Usage: python build_netlify.py https://your-backend-url.onrender.com")
        print()
    
    build(url)
