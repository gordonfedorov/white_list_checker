#!/usr/bin/python3
import concurrent.futures
import threading
import time
from reporter import generate_html_report
from utils import (
    load_urls_with_filters,
    load_settings,
    download_file_with_curl,
    parse_local_file,
    check_single_domain,
    quick_network_check,
    NetworkStatus
)
from db_manager import (
    init_database,
    sync_sources_mapping,
    save_batch_to_db
)
DB_NAME = "checker_results.db"
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
counter_lock = threading.Lock()
processed_count = 0
batch_processed_count = 0
session_online = 0
session_offline = 0
MAX_WORKERS = 50
BATCH_SIZE = 1000
TIMEOUT = 3
DEBUG_SIMULATE_WHITELIST = False
def load_runtime_config():
    global MAX_WORKERS, BATCH_SIZE, TIMEOUT, DEBUG_SIMULATE_WHITELIST
    cfg = load_settings()
    MAX_WORKERS = cfg["max_workers"]
    BATCH_SIZE = cfg["batch_size"]
    TIMEOUT = cfg["timeout"]
    DEBUG_SIMULATE_WHITELIST = cfg["simulate_whitelist"]
def handle_full_internet_stage(sources_data):
    print(f"\n{Colors.BLUE}=== STAGE 1: FULL INTERNET DETECTED. DOWNLOADING FILES VIA CURL ==={Colors.RESET}")
    download_failed = False
    for src in sources_data:
        success = download_file_with_curl(src["url"], src["file_name"])
        if not success:
            download_failed = True
    if download_failed:
        print(f"\n{Colors.RED}[CRITICAL NOTICE] Some downloads failed. Rerun the script later to resume.{Colors.RESET}")
    else:
        print(f"\n{Colors.GREEN}[FINISHED] Lists successfully updated on disk. Domain checks skipped under full network access.{Colors.RESET}")
def build_domains_pool(sources_data):
    print(f"\n{Colors.BLUE}=== STAGE 2: PARSING LOCAL CACHE FILES TO MEMORY ==={Colors.RESET}")
    pool = []
    total_skipped = 0
    for src in sources_data:
        # FIXED: Pass the entire 'src' configuration block mapping inside parse_local_file execution context
        file_domains, skipped = parse_local_file(src["file_name"], src)
        if file_domains:
            pool.extend(file_domains)
        total_skipped += skipped
    return pool, total_skipped
def _print_progress_log(status_code, is_available, domain, total_to_check, b_count, b_start):
    elapsed = time.time() - b_start
    speed = b_count / elapsed if elapsed > 0 else 0
    percentage = (processed_count / total_to_check) * 100
    progress_prefix = f"[{processed_count}/{total_to_check}] ({percentage:.2f}%) | {speed:.1f}/s"
    if not is_available:
        print(f"{Colors.CYAN}{progress_prefix}{Colors.RESET} {Colors.RED}[ Failed ]{Colors.RESET} {domain}")
    elif status_code == 200:
        print(f"{Colors.CYAN}{progress_prefix}{Colors.RESET} {Colors.GREEN}[ HTTP {status_code} ]{Colors.RESET} {domain}")
    else:
        print(f"{Colors.CYAN}{progress_prefix}{Colors.RESET} {Colors.YELLOW}[ HTTP {status_code} ]{Colors.RESET} {domain}")
def _process_batch_threads(current_batch, executor, domain_to_source_map, total_to_check, b_start):
    global processed_count, batch_processed_count, session_online, session_offline
    batch_results = []
    future_to_domain = {executor.submit(check_single_domain, domain): domain for domain in current_batch}
    for future in concurrent.futures.as_completed(future_to_domain):
        domain = future_to_domain[future]
        status_code = future.result()
        is_available = (status_code != -1)
        updated_at = int(time.time())
        source_file = domain_to_source_map.get(domain)
        with counter_lock:
            processed_count += 1
            batch_processed_count += 1
            if is_available:
                session_online += 1
            else:
                session_offline += 1
        _print_progress_log(status_code, is_available, domain, total_to_check, batch_processed_count, b_start)
        batch_results.append((domain, is_available, status_code, updated_at, source_file))
    return batch_results
def _verify_network_and_commit(batch_results, sources_map, batch_index):
    global DEBUG_SIMULATE_WHITELIST
    print(f"{Colors.YELLOW}[SECURITY] Checking network environment before committing batch {batch_index}...{Colors.RESET}")
    current_network = NetworkStatus.WHITELIST_MODE_ACTIVE if DEBUG_SIMULATE_WHITELIST else quick_network_check()
    if current_network == NetworkStatus.WHITELIST_MODE_ACTIVE:
        save_batch_to_db(batch_results, sources_map)
        print(f"{Colors.GREEN}[SECURITY SUCCESS] Network verified. Committed {len(batch_results)} entries to SQLite.{Colors.RESET}")
        return True
    lbl = "OFFLINE" if current_network == NetworkStatus.OFFLINE else "FULL_INTERNET"
    print(f"\n{Colors.RED}[CRITICAL ALARM] Network state shifted to code '{current_network}' ({lbl}) during verification!{Colors.RESET}")
    print(f"{Colors.RED}[SECURITY ROLLBACK] Dropping current memory batch to prevent data pollution.{Colors.RESET}")
    print(f"{Colors.RED}[FINISHED] Execution securely terminated. Re-run the script once Whitelist Mode is restored.{Colors.RESET}")
    return False
def execute_multithreaded_ping(all_domains_pool, sources_map):
    global batch_processed_count
    domain_to_source_map = {domain: source_file for domain, source_file in all_domains_pool}
    clean_domains_list = list(domain_to_source_map.keys())
    total_to_check = len(clean_domains_list)
    print(f"\n{Colors.BLUE}=== STAGE 3: BATCHED FILTERING AND MULTITHREADED CHECKING ==={Colors.RESET}")
    print(f"{Colors.MAGENTA}[START] Total to verify: {total_to_check} domains. Processing in batches of {BATCH_SIZE}...{Colors.RESET}")
    for i in range(0, total_to_check, BATCH_SIZE):
        current_batch = clean_domains_list[i:i + BATCH_SIZE]
        batch_index = (i // BATCH_SIZE) + 1
        print(f"\n{Colors.MAGENTA}[BATCH] Executing thread pool for items {i+1} to {min(i + BATCH_SIZE, total_to_check)}...{Colors.RESET}")
        batch_start_time = time.time()
        batch_processed_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            batch_results = _process_batch_threads(current_batch, executor, domain_to_source_map, total_to_check, batch_start_time)
        if not _verify_network_and_commit(batch_results, sources_map, batch_index):
            return False
    return True
def print_session_summary(total_checked, total_skipped, session_duration):
    avg_speed = total_checked / session_duration if session_duration > 0 else 0
    print(f"\n{Colors.CYAN}=================================================={Colors.RESET}")
    print(f"{Colors.GREEN}               SESSION VERIFICATION SUMMARY       {Colors.RESET}")
    print(f"{Colors.CYAN}=================================================={Colors.RESET}")
    print(f" Total verified this session : {Colors.BLUE}{total_checked}{Colors.RESET}")
    print(f" Active domains found        : {Colors.GREEN}{session_online}{Colors.RESET}")
    print(f" Unreachable/Offline domains : {Colors.RED}{session_offline}{Colors.RESET}")
    print(f" Bypassed via DB cache       : {Colors.YELLOW}{total_skipped}{Colors.RESET}")
    print(f" Total time elapsed          : {Colors.YELLOW}{session_duration:.2f} seconds{Colors.RESET}")
    print(f" Average session speed       : {Colors.CYAN}{avg_speed:.1f} sites/sec{Colors.RESET}")
    print(f"{Colors.CYAN}=================================================={Colors.RESET}")
def main():
    load_runtime_config()
    sources_data = load_urls_with_filters()
    if not sources_data:
        return
    init_database(sources_data)
    sources_map = sync_sources_mapping()
    active_sources = [src["file_name"] for src in sources_data]
    network_status = NetworkStatus.WHITELIST_MODE_ACTIVE if DEBUG_SIMULATE_WHITELIST else quick_network_check()
    if network_status == NetworkStatus.FULL_INTERNET:
        handle_full_internet_stage(sources_data)
        return
    elif network_status != NetworkStatus.WHITELIST_MODE_ACTIVE:
        print(f"\n{Colors.RED}=== STAGE 1: SYSTEM IS OFFLINE OR NETWORK INVALID ==={Colors.RESET}")
        print(f"{Colors.RED}[CRITICAL] Domain verification skipped. Checking sites requires an active Whitelist Mode environment.{Colors.RESET}")
        return
    print(f"\n{Colors.BLUE}=== STAGE 1: WHITELIST MODE ACTIVE. SKIPPING CURL DOWNLOAD ==={Colors.RESET}")
    print(f"{Colors.CYAN}[INFO] The script will now parse and verify local cache files under restricted network rules.{Colors.RESET}")
    all_domains_pool, total_skipped = build_domains_pool(sources_data)
    if not all_domains_pool:
        print(f"\n{Colors.GREEN}[FINISHED] All domains from the global pool have already been checked! Skipping Stage 3.{Colors.RESET}")
        print_session_summary(0, total_skipped, 0)
        generate_html_report(active_sources)
        return
    print(f"\n{Colors.CYAN}[INFO] Global pool contains {len(all_domains_pool)} domains across all sources.{Colors.RESET}")
    session_start_time = time.time()
    success = execute_multithreaded_ping(all_domains_pool, sources_map)
    if success:
        session_duration = time.time() - session_start_time
        print_session_summary(len(all_domains_pool), total_skipped, session_duration)
        generate_html_report(active_sources)
if __name__ == "__main__":
    main()
