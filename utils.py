import os
import re
import subprocess
import requests
from db_manager import load_processed_domains

CONFIG_FILE = "config.txt"

class NetworkStatus:
    OFFLINE = 0
    FULL_INTERNET = 1
    WHITELIST_MODE_ACTIVE = 2

class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"

def parse_config_section(section_name):
    if not os.path.exists(CONFIG_FILE):
        print(f"{Colors.RED}[CRITICAL ERROR] Unified configuration file '{CONFIG_FILE}' not found!{Colors.RESET}")
        return []
    items = []
    inside_section = False
    target_header = f"[{section_name.upper()}]"
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                inside_section = (line.upper() == target_header)
                continue
            if inside_section:
                line = line.split("#")[0].strip()
                if line:
                    items.append(line)
    return items

def load_settings():
    raw_settings = parse_config_section("SETTINGS")
    settings = {
        "max_workers": 50,
        "batch_size": 1000,
        "timeout": 3,
        "simulate_whitelist": False
    }
    for line in raw_settings:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().lower(), value.strip()
        if key in ["max_workers", "batch_size", "timeout"]:
            if value.isdigit():
                settings[key] = int(value)
        elif key == "simulate_whitelist":
            settings[key] = value.lower() in ["true", "1", "yes"]
    return settings

def load_urls_with_filters():
    raw_lines = parse_config_section("SITES")
    structured_sources = []
    for line in raw_lines:
        if "|" in line:
            url, raw_rules = line.split("|", 1)
            url = url.strip()
            raw_regex_list = [r.strip() for r in raw_rules.split(",") if r.strip()]
        else:
            url = line.strip()
            raw_regex_list = []
            
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
            
        include_filters = []
        exclude_filters = []
        
        for reg in raw_regex_list:
            # Detect prefixes: '-' for exclude, '+' or none for include
            if reg.startswith("-"):
                target_list = exclude_filters
                pattern = reg[1:].strip()
            elif reg.startswith("+"):
                target_list = include_filters
                pattern = reg[1:].strip()
            else:
                target_list = include_filters
                pattern = reg
                
            try:
                target_list.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                print(f"{Colors.YELLOW}[WARNING] Invalid regex skipped for '{url}': {reg}. Error: {e}{Colors.RESET}")
                
        structured_sources.append({
            "url": url,
            "file_name": url.split("/")[-1],
            "include_filters": include_filters,
            "exclude_filters": exclude_filters
        })
    return structured_sources

def download_file_with_curl(url, target_file):
    if os.path.exists(target_file):
        print(f"{Colors.CYAN}[CACHE] Found local file '{target_file}'. Skipping download.{Colors.RESET}")
        return True
    tmp_file = f"{target_file}.tmp"
    print(f"{Colors.BLUE}[FETCHING] Downloading via cURL (Resume enabled): {url}{Colors.RESET}")
    curl_cmd = ["curl", "-L", "-C", "-", "-sS", url, "-o", tmp_file]
    try:
        result = subprocess.run(curl_cmd, check=True)
        if result.returncode == 0:
            os.replace(tmp_file, target_file)
            print(f"{Colors.GREEN}[DOWNLOAD SUCCESS] Saved to '{target_file}'{Colors.RESET}")
            return True
    except subprocess.CalledProcessError as e:
        print(f"{Colors.RED}[DOWNLOAD ERROR] cURL failed for {url}. Broken fragment saved to '{tmp_file}'. Error: {e}{Colors.RESET}")
        return False
    return False

def parse_local_file(file_name, source_rules):
    if not os.path.exists(file_name):
        print(f"{Colors.RED}[PARSING ERROR] File '{file_name}' not found on disk. Skipping.{Colors.RESET}")
        return [], 0
    print(f"{Colors.CYAN}[PARSING] Reading domains from '{file_name}'...{Colors.RESET}")
    try:
        processed = load_processed_domains()
    except Exception:
        processed = set()
    with open(file_name, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if lines:
        first_line = lines[0]
        if not first_line.replace(",", "").replace(".", "").replace("-", "").replace("_", "").isdigit():
            lines = lines[1:]
    clean_domains = [line.split(",")[-1].strip() if "," in line else line.strip() for line in lines]
    filtered_domains = []
    skip_count = 0
    
    include_rules = source_rules.get("include_filters", [])
    exclude_rules = source_rules.get("exclude_filters", [])
    
    for d in clean_domains:
        if "<" in d or ">" in d:
            continue
        if d in processed:
            skip_count += 1
            continue
            
        # 1. Evaluate blacklists first: if any exclude rule matches, drop domain immediately
        if exclude_rules and any(regex.search(d) for regex in exclude_rules):
            continue
            
        # 2. Evaluate whitelists next: if whitelist exists, it must match. If empty, all pass.
        if include_rules:
            if any(regex.search(d) for regex in include_rules):
                filtered_domains.append((d, file_name))
        else:
            filtered_domains.append((d, file_name))
            
    print(f"{Colors.GREEN}[SUCCESS] Parsed {len(filtered_domains)} new domains | Bypassed via cache: {skip_count}{Colors.RESET}")
    return filtered_domains, skip_count

def check_single_domain(domain):
    url = f"https://{domain}" if not domain.startswith("http") else domain
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.head(url, headers=headers, timeout=3, allow_redirects=True)
        return response.status_code
    except requests.RequestException:
        return -1

def quick_network_check():
    russian_ok = (check_single_domain("https://vk.com") != -1)
    if not russian_ok:
        return NetworkStatus.OFFLINE
    global_ok = (check_single_domain("https://apple.com") != -1)
    if global_ok:
        return NetworkStatus.FULL_INTERNET
    return NetworkStatus.WHITELIST_MODE_ACTIVE

