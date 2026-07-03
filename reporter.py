import os
from datetime import datetime
from db_manager import fetch_report_data

HTML_REPORT_FILE = "report.html"


def generate_html_report(sources_list):
    print(f"\n[REPORT] Generating responsive HTML grid report to '{HTML_REPORT_FILE}'...")
    placeholders = ",".join("?" for _ in sources_list)

    try:
        rows = fetch_report_data(placeholders, sources_list)
    except Exception as e:
        print(f"[REPORT ERROR] Failed to fetch report data from DB manager: {e}")
        return

    total_online = len(rows)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Whitelist - Alphabetical Live Grid Report</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121214; color: #e2e8f0; margin: 0; padding: 20px; }}
        .container {{ max-width: 100%; margin: 0 auto; width: 100%; box-sizing: border-box; }}
        h1 {{ color: #4ade80; margin-top: 0; margin-bottom: 5px; font-size: 1.8rem; }}
        .meta {{ color: #94a3b8; margin-bottom: 20px; font-size: 0.85rem; }}
        .stats-card {{ background: #1e1e24; border: 1px solid #2d2d39; border-radius: 8px; padding: 12px 20px; margin-bottom: 20px; display: inline-block; }}
        .stats-card span {{ font-size: 1.8rem; font-weight: bold; color: #4ade80; display: block; line-height: 1.1; }}
        .alphabet-nav {{ display: flex; flex-wrap: wrap; gap: 6px; background-color: #1e1e24; border: 1px solid #2d2d39; padding: 12px; border-radius: 8px; margin-bottom: 25px; }}
        .letter-btn {{ background-color: #27272a; border: 1px solid #3f3f46; color: #e2e8f0; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; transition: all 0.15s ease; }}
        .letter-btn:hover {{ border-color: #4ade80; color: #4ade80; }}
        .letter-btn.active {{ background-color: #064e3b; border-color: #4ade80; color: #4ade80; font-weight: bold; }}
        .site-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 25px; width: 100%; }}
        .site-card {{ background-color: #1e1e24; border: 1px solid #2d2d39; border-radius: 10px; padding: 15px; box-sizing: border-box; display: flex; flex-direction: column; gap: 12px; width: 100%; }}
        .iframe-container {{ width: 100%; position: relative; border-radius: 6px; border: 1px solid #3f3f46; background-color: #1a1a1e; overflow: hidden; padding-top: 56.25%; }}
        .iframe-container iframe {{ width: 200%; height: 200%; border: none; position: absolute; top: 0; left: 0; transform: scale(0.5); transform-origin: 0 0; }}
        .card-info {{ display: flex; flex-direction: column; gap: 6px; font-size: 0.9rem; }}
        .card-row {{ display: flex; justify-content: space-between; align-items: center; }}
        .domain-link {{ color: #60a5fa; text-decoration: none; font-weight: bold; font-size: 1.1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .domain-link:hover {{ text-decoration: underline; }}
        .badge {{ background-color: #064e3b; color: #4ade80; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; }}
        .source-text {{ color: #a1a1aa; font-size: 0.8rem; }}
        @media (max-width: 768px) {{ .site-grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Available Sites Whitelist</h1>
        <div class="meta">Report generated on: {current_time}</div>
        <div class="stats-card">
            <span>{total_online}</span>
            Active Domains (ONLINE)
        </div>
        <div class="alphabet-nav" id="alphabetNav"></div>
        <div class="site-grid" id="siteGrid">"""
    for row in rows:
        domain, http_code, updated_at, source_file = row
        html_content += f"""
            <div class="site-card">
                <div class="iframe-container">
                    <iframe data-src="https://{domain}" loading="lazy" sandbox="allow-scripts allow-same-origin"></iframe>
                </div>
                <div class="card-info">
                    <div class="card-row">
                        <a href="https://{domain}" target="_blank" class="domain-link">{domain}</a>
                        <span class="badge">HTTP {http_code}</span>
                    </div>
                    <div class="card-row">
                        <span class="source_text" style="color: #71717a;">Source file mapping:</span>
                        <span class="source-text">{source_file}</span>
                    </div>
                </div>
            </div>"""
    html_content += """
        </div>
    </div>
    <script>
    const grid = document.getElementById('siteGrid');
    const cards = Array.from(grid.getElementsByClassName('site-card'));
    const groups = {};
    cards.forEach(card => {
        const domain = card.querySelector('.domain-link').innerText.trim().toLowerCase();
        let firstChar = domain.charAt(0);
        if (!/[a-z]/.test(firstChar)) firstChar = '0-9';
        if (!groups[firstChar]) groups[firstChar] = [];
        groups[firstChar].push(card);
    });
    const availableLetters = Object.keys(groups).sort((a, b) => {
        if (a === '0-9') return -1;
        if (b === '0-9') return 1;
        return a.localeCompare(b);
    });
    const filterByLetter = (targetLetter) => {
        document.querySelectorAll('.letter-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-letter') === targetLetter);
        });
        cards.forEach(card => {
            const domain = card.querySelector('.domain-link').innerText.trim().toLowerCase();
            let firstChar = domain.charAt(0);
            if (!/[a-z]/.test(firstChar)) firstChar = '0-9';
            const match = firstChar === targetLetter;
            card.style.display = match ? 'flex' : 'none';
            const frame = card.querySelector('iframe');
            if (frame) {
                if (match && !frame.src) frame.src = frame.getAttribute('data-src');
                if (!match && frame.src) frame.removeAttribute('src');
            }
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    const nav = document.getElementById('alphabetNav');
    availableLetters.forEach(letter => {
        const btn = document.createElement('button');
        btn.className = 'letter-btn';
        btn.innerText = letter.toUpperCase() + ' (' + groups[letter].length + ')';
        btn.setAttribute('data-letter', letter);
        btn.onclick = () => filterByLetter(letter);
        nav.appendChild(btn);
    });
    if (availableLetters.length > 0) {
        filterByLetter(availableLetters);
    }
    </script>
</body>
</html>"""
    with open(HTML_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[REPORT SUCCESS] HTML live iframe report compiled. Total listed entries: {total_online}")
