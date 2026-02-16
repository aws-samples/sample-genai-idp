# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Load testing module for IDP CLI.

Provides functionality to simulate document processing load by copying files to S3.
"""

import csv
import logging
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Optional

import boto3
from botocore.config import Config
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from idp_sdk.core.stack_info import StackInfo

logger = logging.getLogger(__name__)
console = Console()


class CopyStats:
    """Thread-safe statistics tracker for file copies."""

    def __init__(self):
        self.total_copies = 0
        self.lock = Lock()
        self.start_time = time.time()
        self.copies_by_minute = defaultdict(int)

    def increment(self, minute: int = 0) -> int:
        with self.lock:
            if minute:
                self.copies_by_minute[minute] += 1
            self.total_copies += 1
            return self.total_copies

    def get_minute_copies(self, minute: int) -> int:
        with self.lock:
            return self.copies_by_minute[minute]

    def get_total(self) -> int:
        with self.lock:
            return self.total_copies

    def get_current_rate(self) -> float:
        with self.lock:
            elapsed = time.time() - self.start_time
            return (self.total_copies / (elapsed / 60)) if elapsed > 0 else 0

    def get_elapsed_time(self) -> tuple:
        elapsed_seconds = int(time.time() - self.start_time)
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
        return minutes, seconds


class LoadTester:
    """Run load tests by copying files to S3 input bucket."""

    def __init__(self, stack_name: str, region: Optional[str] = None):
        """Initialize load tester.

        Args:
            stack_name: CloudFormation stack name
            region: AWS region (optional)
        """
        self.stack_name = stack_name
        self.region = region

        # Get stack resources
        stack_info = StackInfo(stack_name, region)
        self.resources = stack_info.get_resources()

        # Initialize S3 client with connection pooling
        session = boto3.Session(region_name=region)
        self.s3 = session.client("s3", config=Config(max_pool_connections=100))

        # Get bucket names (using friendly names from StackInfo)
        self.input_bucket = self.resources.get("InputBucket")

    def _copy_file(
        self,
        source_bucket: str,
        source_key: str,
        dest_prefix: str,
        stats: CopyStats,
        current_minute: int = 0,
        target_copies: int = 0,
    ) -> bool:
        """Copy a single file to the input bucket."""
        try:
            # For scheduled mode, check if we've hit the target
            if current_minute and target_copies:
                current_copies = stats.get_minute_copies(current_minute)
                if current_copies >= target_copies:
                    return False

            sequence = stats.increment(current_minute)

            # Generate unique filename
            base_name = os.path.splitext(os.path.basename(source_key))[0]
            file_ext = os.path.splitext(source_key)[1]

            if current_minute:
                new_filename = (
                    f"{base_name}_{current_minute:03d}_{sequence:06d}{file_ext}"
                )
            else:
                new_filename = f"{base_name}_{sequence:06d}{file_ext}"

            new_key = f"{dest_prefix}/{new_filename}"

            self.s3.copy_object(
                Bucket=self.input_bucket,
                Key=new_key,
                CopySource={"Bucket": source_bucket, "Key": source_key},
            )
            return True
        except Exception as e:
            logger.error(f"Error copying file: {e}")
            return False

    def _upload_local_file(
        self, local_path: str, dest_prefix: str, stats: CopyStats
    ) -> bool:
        """Upload a local file to the input bucket."""
        try:
            sequence = stats.increment()
            base_name = os.path.splitext(os.path.basename(local_path))[0]
            file_ext = os.path.splitext(local_path)[1]
            new_filename = f"{base_name}_{sequence:06d}{file_ext}"
            new_key = f"{dest_prefix}/{new_filename}"

            self.s3.upload_file(local_path, self.input_bucket, new_key)
            return True
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return False

    def run_constant_load(
        self,
        source_file: str,
        rate: int = 2500,
        duration: int = 1,
        dest_prefix: str = "load-test",
    ) -> dict:
        """Run constant rate load test.

        Args:
            source_file: Local file path or S3 URI (s3://bucket/key)
            rate: Copies per minute
            duration: Duration in minutes
            dest_prefix: Destination prefix in input bucket

        Returns:
            Dict with test results
        """
        if not self.input_bucket:
            return {
                "success": False,
                "error": "Input bucket not found in stack outputs",
            }

        console.print("[bold blue]Starting load test[/bold blue]")
        console.print(f"  Rate: {rate} files/minute")
        console.print(f"  Duration: {duration} minutes")
        console.print(f"  Destination: s3://{self.input_bucket}/{dest_prefix}/")
        console.print()

        # Parse source file
        is_s3_source = source_file.startswith("s3://")
        if is_s3_source:
            parts = source_file[5:].split("/", 1)
            source_bucket = parts[0]
            source_key = parts[1] if len(parts) > 1 else ""
        else:
            source_bucket = None
            source_key = None
            if not os.path.exists(source_file):
                return {
                    "success": False,
                    "error": f"Source file not found: {source_file}",
                }

        stats = CopyStats()
        max_workers = min(rate, 500)
        batch_size = int(rate / 30)  # 30 batches per minute

        start_time = time.time()
        end_time = start_time + (duration * 60)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed} files"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Copying files...", total=rate * duration)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                while time.time() < end_time:
                    futures = []

                    # Adaptive batch sizing
                    current_rate = stats.get_current_rate()
                    if current_rate < rate * 0.9:
                        batch_size = int(batch_size * 1.2)
                    elif current_rate > rate * 1.1:
                        batch_size = int(batch_size * 0.8)
                    batch_size = max(1, min(batch_size, rate))

                    for _ in range(batch_size):
                        if is_s3_source:
                            futures.append(
                                executor.submit(
                                    self._copy_file,
                                    source_bucket,
                                    source_key,
                                    dest_prefix,
                                    stats,
                                )
                            )
                        else:
                            futures.append(
                                executor.submit(
                                    self._upload_local_file,
                                    source_file,
                                    dest_prefix,
                                    stats,
                                )
                            )

                    for future in as_completed(futures):
                        if future.result():
                            progress.update(task, completed=stats.get_total())

                    time.sleep(0.1)

        total = stats.get_total()
        total_time = time.time() - start_time
        minutes, seconds = divmod(int(total_time), 60)

        console.print()
        console.print("[green]✓ Load test complete[/green]")
        console.print(f"  Files copied: {total}")
        console.print(f"  Duration: {minutes:02d}:{seconds:02d}")
        console.print(f"  Average rate: {total / (total_time / 60):.1f} files/minute")

        return {
            "success": True,
            "total_files": total,
            "duration_seconds": total_time,
            "average_rate": total / (total_time / 60),
        }

    def run_scheduled_load(
        self, source_file: str, schedule_file: str, dest_prefix: str = "load-test"
    ) -> dict:
        """Run scheduled load test with variable rates.

        Args:
            source_file: Local file path or S3 URI
            schedule_file: CSV file with minute,count columns
            dest_prefix: Destination prefix in input bucket

        Returns:
            Dict with test results
        """
        if not self.input_bucket:
            return {
                "success": False,
                "error": "Input bucket not found in stack outputs",
            }

        # Load schedule
        schedule = {}
        with open(schedule_file, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) == 2 and row[0].strip().isdigit():
                    minute = int(row[0])
                    count = int(row[1])
                    schedule[minute] = count

        if not schedule:
            return {"success": False, "error": "No valid schedule entries found"}

        max_minutes = max(schedule.keys())
        total_planned = sum(schedule.values())

        console.print("[bold blue]Starting scheduled load test[/bold blue]")
        console.print(f"  Schedule: {len(schedule)} minutes")
        console.print(f"  Total planned: {total_planned} files")
        console.print(f"  Destination: s3://{self.input_bucket}/{dest_prefix}/")
        console.print()

        # Parse source file
        is_s3_source = source_file.startswith("s3://")
        if is_s3_source:
            parts = source_file[5:].split("/", 1)
            source_bucket = parts[0]
            source_key = parts[1] if len(parts) > 1 else ""
        else:
            source_bucket = None
            source_key = None
            if not os.path.exists(source_file):
                return {
                    "success": False,
                    "error": f"Source file not found: {source_file}",
                }

        stats = CopyStats()
        max_workers = 2000

        start_time = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Running schedule...", total=total_planned)

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
                        remaining = target_copies - current_copies
                        futures = []

                        for _ in range(remaining):
                            if is_s3_source:
                                futures.append(
                                    executor.submit(
                                        self._copy_file,
                                        source_bucket,
                                        source_key,
                                        dest_prefix,
                                        stats,
                                        current_minute,
                                        target_copies,
                                    )
                                )
                            else:
                                futures.append(
                                    executor.submit(
                                        self._upload_local_file,
                                        source_file,
                                        dest_prefix,
                                        stats,
                                    )
                                )

                        for future in as_completed(futures):
                            if future.result():
                                progress.update(task, completed=stats.get_total())

                    time.sleep(0.01)

        total = stats.get_total()
        total_time = time.time() - start_time
        minutes, seconds = divmod(int(total_time), 60)

        console.print()
        console.print("[green]✓ Scheduled load test complete[/green]")
        console.print(f"  Files copied: {total}")
        console.print(f"  Duration: {minutes:02d}:{seconds:02d}")

        return {
            "success": True,
            "total_files": total,
            "duration_seconds": total_time,
            "planned_files": total_planned,
        }
