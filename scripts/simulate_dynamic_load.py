#!/usr/bin/env python3
# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import time
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import os
import csv
from collections import defaultdict
from botocore.config import Config

class CopyStats:
    def __init__(self):
        self.total_copies = 0
        self.lock = Lock()
        self.start_time = time.time()
        self.copies_by_minute = defaultdict(int)
    
    def increment(self, minute):
        with self.lock:
            current_copies = self.copies_by_minute[minute]
            self.copies_by_minute[minute] += 1
            self.total_copies += 1
            return current_copies + 1
    
    def get_minute_copies(self, minute):
        with self.lock:
            return self.copies_by_minute[minute]
    
    def get_total(self):
        with self.lock:
            return self.total_copies
    
    def get_elapsed_time(self):
        elapsed_seconds = int(time.time() - self.start_time)
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
        return minutes, seconds

def copy_file(s3_client, source_bucket, source_key, dest_bucket, dest_prefix, stats, current_minute, target_copies):
    try:
        current_copies = stats.get_minute_copies(current_minute)
        if current_copies >= target_copies:
            return False
            
        copy_number = stats.increment(current_minute)
        if copy_number > target_copies:
            return False
            
        base_name = os.path.splitext(os.path.basename(source_key))[0]
        file_ext = os.path.splitext(source_key)[1]
        new_filename = f"{base_name}_{current_minute:03d}_{copy_number:06d}{file_ext}"
        new_key = f"{dest_prefix}/{new_filename}"
        
        s3_client.copy_object(
            Bucket=dest_bucket,
            Key=new_key,
            CopySource={'Bucket': source_bucket, 'Key': source_key}
        )
        return True
    except Exception as e:
        print(f"Error copying file: {e}")
        return False

def log_progress(stats, schedule):
    while True:
        total = stats.get_total()
        minutes, seconds = stats.get_elapsed_time()
        current_minute = minutes + 1
        target = schedule.get(current_minute, 0)
        current = stats.get_minute_copies(current_minute)
        print(f"[{minutes:02d}:{seconds:02d}] Minute {current_minute}: {current}/{target} files copied (Total: {total})")
        time.sleep(5)  # semgrep-ignore: arbitrary-sleep - Intentional delay for simulation. Duration is hardcoded and not user-controlled.

def read_schedule(csv_file):
    schedule = {}
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) == 2 and row[0].strip().isdigit():  # Handle both header/no header cases
                minute = int(row[0])
                count = int(row[1])
                schedule[minute] = count
    return schedule

def stress_test(source_bucket, source_key, dest_bucket, dest_prefix, schedule_file):
    s3_client = boto3.client('s3', config=Config(max_pool_connections=100))
    schedule = read_schedule(schedule_file)
    max_workers = 2000
    stats = CopyStats()
    
    start_time = time.time()
    max_minutes = max(schedule.keys())
    
    import threading
    log_thread = threading.Thread(target=log_progress, args=(stats, schedule), daemon=True)
    log_thread.start()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            current_time = time.time()
            elapsed_minutes = int((current_time - start_time) / 60)
            current_minute = elapsed_minutes + 1
            
            if current_minute > max_minutes:
                break
                
            target_copies = schedule.get(current_minute, 0)
            current_copies = stats.get_minute_copies(current_minute)
            
            if current_copies < target_copies:
                remaining_copies = target_copies - current_copies
                
                futures = [
                    executor.submit(
                        copy_file, s3_client, source_bucket, source_key,
                        dest_bucket, dest_prefix, stats, current_minute, target_copies
                    )
                    for _ in range(remaining_copies)
                ]
                
                completed = sum(1 for f in as_completed(futures) if f.result())
            
            time.sleep(0.01) # semgrep-ignore: arbitrary-sleep - Intentional delay to avoid tight loop. Duration is hardcoded and not user-controlled.
    
    final_total = stats.get_total()
    total_time = time.time() - start_time
    minutes, seconds = divmod(int(total_time), 60)
    print(f"\nTest complete. Copied {final_total} files in {minutes:02d}:{seconds:02d}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='S3 Copy Stress Test with Schedule')
    parser.add_argument('-s', '--source-bucket', required=True, help='Source bucket name')
    parser.add_argument('-k', '--source-key', required=True, help='Source file key')
    parser.add_argument('-d', '--dest-bucket', required=True, help='Destination bucket name')
    parser.add_argument('-p', '--dest-prefix', default='simulated_load', help='Destination prefix (folder)')
    parser.add_argument('-f', '--schedule-file', required=True, help='CSV file with minute,copies schedule')
    
    args = parser.parse_args()
    
    print(f"Starting scheduled copy test...")
    stress_test(
        args.source_bucket,
        args.source_key,
        args.dest_bucket,
        args.dest_prefix.strip('/'),
        args.schedule_file
    )