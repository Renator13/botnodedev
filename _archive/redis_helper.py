#!/usr/bin/env python3
"""
Redis helper for skill dispatcher.
Handles connection to Redis and queue operations.
"""

import os
import json
import redis
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Queue names
SKILLS_QUEUE = "skills:queue"
HIGH_PRIORITY_QUEUE = "skills:queue:high"
NORMAL_PRIORITY_QUEUE = "skills:queue:normal"
LOW_PRIORITY_QUEUE = "skills:queue:low"

class RedisQueue:
    """Redis queue manager for skill jobs."""
    
    def __init__(self):
        """Initialize Redis connection."""
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True
        )
        self._test_connection()
    
    def _test_connection(self):
        """Test Redis connection."""
        try:
            self.redis_client.ping()
            print(f"✅ Redis connected: {REDIS_HOST}:{REDIS_PORT}")
        except redis.ConnectionError as e:
            print(f"❌ Redis connection failed: {e}")
            raise
    
    def get_queue_name(self, priority: str) -> str:
        """Get queue name based on priority."""
        priority = priority.lower()
        if priority == "high":
            return HIGH_PRIORITY_QUEUE
        elif priority == "low":
            return LOW_PRIORITY_QUEUE
        else:
            return NORMAL_PRIORITY_QUEUE
    
    def publish_job(self, job_data: Dict[str, Any]) -> str:
        """
        Publish a job to the appropriate Redis queue.
        
        Args:
            job_data: Dictionary containing job information
            
        Returns:
            job_id: The unique ID of the published job
        """
        # Generate job ID if not provided
        if "job_id" not in job_data:
            job_data["job_id"] = str(uuid.uuid4())
        
        # Add timestamp
        job_data["queued_at"] = datetime.utcnow().isoformat()
        
        # Determine queue based on priority
        priority = job_data.get("priority", "normal")
        queue_name = self.get_queue_name(priority)
        
        # Convert to JSON string
        job_json = json.dumps(job_data)
        
        # Push to Redis list (left push for queue behavior)
        self.redis_client.lpush(queue_name, job_json)
        
        # Also push to main skills queue for backward compatibility
        self.redis_client.lpush(SKILLS_QUEUE, job_json)
        
        # Get queue position
        queue_position = self.redis_client.llen(queue_name)
        
        print(f"✅ Job {job_data['job_id']} published to {queue_name} (position: {queue_position})")
        
        return job_data["job_id"], queue_position
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get statistics for all queues."""
        stats = {
            "high_priority": self.redis_client.llen(HIGH_PRIORITY_QUEUE),
            "normal_priority": self.redis_client.llen(NORMAL_PRIORITY_QUEUE),
            "low_priority": self.redis_client.llen(LOW_PRIORITY_QUEUE),
            "total": self.redis_client.llen(SKILLS_QUEUE),
            "timestamp": datetime.utcnow().isoformat()
        }
        return stats
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a job by checking if it's still in queue.
        
        Note: This is a simple implementation. In production, you might want
        to use Redis hashes or a separate tracking system.
        """
        # Check all queues for the job
        for queue_name in [HIGH_PRIORITY_QUEUE, NORMAL_PRIORITY_QUEUE, LOW_PRIORITY_QUEUE, SKILLS_QUEUE]:
            queue_length = self.redis_client.llen(queue_name)
            
            # Get all jobs in the queue
            jobs = self.redis_client.lrange(queue_name, 0, -1)
            
            for job_json in jobs:
                try:
                    job_data = json.loads(job_json)
                    if job_data.get("job_id") == job_id:
                        # Find position in queue
                        position = jobs.index(job_json) + 1  # 1-indexed
                        return {
                            "job_id": job_id,
                            "status": "queued",
                            "queue": queue_name,
                            "queue_position": position,
                            "queued_at": job_data.get("queued_at"),
                            "priority": job_data.get("priority", "normal")
                        }
                except json.JSONDecodeError:
                    continue
        
        # Job not found in any queue (might be processing or completed)
        return None
    
    def pop_job(self, queue_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Pop a job from a queue (right pop for FIFO).
        
        Args:
            queue_name: Specific queue to pop from, or None to check priority order
            
        Returns:
            Job data dictionary or None if no jobs available
        """
        if queue_name:
            # Pop from specific queue
            job_json = self.redis_client.rpop(queue_name)
            if job_json:
                try:
                    return json.loads(job_json)
                except json.JSONDecodeError:
                    return None
            return None
        
        # Check queues in priority order: high -> normal -> low
        for qname in [HIGH_PRIORITY_QUEUE, NORMAL_PRIORITY_QUEUE, LOW_PRIORITY_QUEUE]:
            job_json = self.redis_client.rpop(qname)
            if job_json:
                try:
                    job_data = json.loads(job_json)
                    # Also remove from main queue if present
                    self._remove_from_main_queue(job_data.get("job_id"))
                    return job_data
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def _remove_from_main_queue(self, job_id: str):
        """Remove a job from the main skills queue."""
        jobs = self.redis_client.lrange(SKILLS_QUEUE, 0, -1)
        for i, job_json in enumerate(jobs):
            try:
                job_data = json.loads(job_json)
                if job_data.get("job_id") == job_id:
                    # Remove by index
                    self.redis_client.lset(SKILLS_QUEUE, i, "__DELETED__")
                    self.redis_client.lrem(SKILLS_QUEUE, 1, "__DELETED__")
                    break
            except json.JSONDecodeError:
                continue


# Global Redis queue instance
redis_queue = RedisQueue()