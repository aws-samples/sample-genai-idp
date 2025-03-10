#!/usr/bin/env python3
# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import time
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import os

class CopyStats:
    def __init__(self):
        self.total_copies = 0
        self.lock = Lock()
        self.start_time = time.time()
    
    def increment(self):
        with self.lock:
            self.total_copies += 1
            return self.total_copies
    
    def get_total(self):
        with self.lock:
            return self.total_copies
            
    def get_current_rate(self):
        with self.lock:
            current_time = time.time()
            elapsed = current_time - self.start_time
            return (self.total_copies / (elapsed / 60)) if elapsed > 0 else 0
    
    def get_elapsed_time(self):
        elapsed_seconds = int(time.time() - self.start_time)
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
        return minutes, seconds

def copy_file(s3_client, source_bucket, source_key, dest_bucket, dest_prefix, stats):
    try:
        base_name = os.path.splitext(os.path.basename(source_key))[0]
        file_ext = os.path.splitext(source_key)[1]
        sequence = stats.increment()
        new_filename = f"{base_name}_{sequence:06d}{file_ext}"
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

def log_progress(stats, target_rate):
    while True:
        total = stats.get_total()
        rate = stats.get_current_rate()
        minutes, seconds = stats.get_elapsed_time()
        print(f"[{minutes:02d}:{seconds:02d}] Files copied: {total}, Current rate: {rate:.1f} files/minute (target: {target_rate})")
        time.sleep(10) # semgrep-ignore: arbitrary-sleep - Intentional delay for periodic logging. Duration is hardcoded and not user-controlled.

def stress_test(source_bucket, source_key, dest_bucket, dest_prefix='', copies_per_minute=2500, duration_minutes=1):
    s3_client = boto3.client('s3')
    max_workers = min(copies_per_minute, 500)
    stats = CopyStats()
    batch_size = int(copies_per_minute / 30)
    
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    
    import threading
    log_thread = threading.Thread(target=log_progress, args=(stats, copies_per_minute), daemon=True)
    log_thread.start()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while time.time() < end_time:
            batch_start = time.time()
            futures = []
            
            current_rate = stats.get_current_rate()
            if current_rate < copies_per_minute * 0.9:
                batch_size = int(batch_size * 1.2)
            elif current_rate > copies_per_minute * 1.1:
                batch_size = int(batch_size * 0.8)
            
            batch_size = max(1, min(batch_size, copies_per_minute))
            
            for _ in range(batch_size):
                futures.append(executor.submit(
                    copy_file, s3_client, source_bucket, source_key, dest_bucket, dest_prefix, stats
                ))
            
            completed = sum(1 for f in futures if f.result())
            time.sleep(0.1) # semgrep-ignore: arbitrary-sleep - Intentional delay to avoid tight loop. Duration is hardcoded and not user-controlled.
    
    final_total = stats.get_total()
    total_time = time.time() - start_time
    minutes, seconds = divmod(int(total_time), 60)
    print(f"\nTest complete. Copied {final_total} files in {minutes:02d}:{seconds:02d}")
    print(f"Average rate: {final_total / (total_time / 60):.1f} files/minute")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='S3 Copy Stress Test')
    parser.add_argument('-s', '--source-bucket', required=True, help='Source bucket name')
    parser.add_argument('-k', '--source-key', required=True, help='Source file key')
    parser.add_argument('-d', '--dest-bucket', required=True, help='Destination bucket name')
    parser.add_argument('-p', '--dest-prefix', default='simulated_load', help='Destination prefix (folder)')
    parser.add_argument('-r', '--rate', type=int, default=2500, help='Copies per minute (default: 2500)')
    parser.add_argument('-t', '--duration', type=int, default=1, help='Duration in minutes')
    
    args = parser.parse_args()
    
    print(f"Starting stress test at {args.rate} copies per minute...")
    stress_test(
        args.source_bucket,
        args.source_key,
        args.dest_bucket,
        args.dest_prefix.strip('/'),
        args.rate,
        args.duration
    )