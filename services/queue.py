# fx/services/queue.py
import asyncio
import json
from typing import Any, Dict, Optional, Callable
from datetime import timedelta
import logging
from celery import Celery
from celery.result import AsyncResult

from config.settings import settings

logger = logging.getLogger(__name__)


class QueueService:
    """
    Celery-based task queue service
    """
    
    def __init__(self):
        redis_url = settings.REDIS_URL
        self.enabled = bool(redis_url)
        self.celery_app = Celery(
            'fx_signal_copier',
            # Celery treats a missing broker as its default AMQP broker. Keep
            # local/dry-run startup offline instead of silently selecting one.
            broker=redis_url or 'memory://',
            backend=redis_url or 'cache+memory://'
        )
        
        # Configure Celery
        self.celery_app.conf.update(
            task_serializer='json',
            accept_content=['json'],
            result_serializer='json',
            timezone='UTC',
            enable_utc=True,
            task_track_started=True,
            task_time_limit=30 * 60,  # 30 minutes
            task_soft_time_limit=25 * 60,  # 25 minutes
            worker_prefetch_multiplier=1,
            worker_concurrency=4,
            task_acks_late=True,
            task_reject_on_worker_lost=True,
            result_expires=3600,  # 1 hour
        )
        
        # Register tasks
        self._register_tasks()
        
        logger.info("Queue service initialized")
    
    def _register_tasks(self):
        """Register all background tasks"""
        
        @self.celery_app.task(bind=True, name='tasks.send_notification')
        def send_notification(self, user_id: int, message: str, notification_type: str):
            """Send notification to user"""
            # This will be called from the bot
            from services.notification import NotificationService
            # Implementation in bot layer
            pass
        
        @self.celery_app.task(bind=True, name='tasks.process_signal')
        def process_signal(self, user_id: int, signal_text: str):
            """Process a trading signal"""
            # This will be handled by trade executor
            pass
        
        @self.celery_app.task(bind=True, name='tasks.generate_report')
        def generate_report(self, user_id: int, report_type: str):
            """Generate and send a report"""
            pass
        
        @self.celery_app.task(bind=True, name='tasks.cleanup_old_data')
        def cleanup_old_data(self, days: int = 30):
            """Clean up old database records"""
            from database.cleanup import cleanup_old_records
            cleanup_old_records(days)
        
        @self.celery_app.task(bind=True, name='tasks.check_connections')
        def check_connections(self):
            """Check all user connections"""
            pass
        
        @self.celery_app.task(bind=True, name='tasks.update_prices')
        def update_prices(self, symbols: list):
            """Update price cache for symbols"""
            pass
    
    def send_task(self, task_name: str, args: list = None, 
                  kwargs: dict = None, delay: Optional[timedelta] = None) -> str:
        """
        Send a task to the queue
        Returns task ID
        """
        if not self.enabled:
            raise RuntimeError("Task queue is disabled: configure REDIS_URL to enable it")
        try:
            if delay:
                # Schedule for later
                result = self.celery_app.send_task(
                    task_name,
                    args=args or [],
                    kwargs=kwargs or {},
                    countdown=int(delay.total_seconds())
                )
            else:
                # Execute now
                result = self.celery_app.send_task(
                    task_name,
                    args=args or [],
                    kwargs=kwargs or {}
                )
            
            logger.info(f"Task {task_name} sent with ID {result.id}")
            return result.id
            
        except Exception as e:
            logger.error("Failed to send task %s (%s)", task_name, type(e).__name__)
            raise
    
    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task result by ID"""
        try:
            result = AsyncResult(task_id, app=self.celery_app)
            
            if result.ready():
                return {
                    'status': 'completed',
                    'result': result.result,
                    'success': result.successful()
                }
            elif result.failed():
                return {
                    'status': 'failed',
                    'error': 'Task failed'
                }
            else:
                return {
                    'status': result.state.lower()
                }
                
        except Exception as e:
            logger.error("Failed to get task result %s (%s)", task_id, type(e).__name__)
            return None
    
    def revoke_task(self, task_id: str, terminate: bool = False) -> bool:
        """Revoke/cancel a task"""
        try:
            self.celery_app.control.revoke(task_id, terminate=terminate)
            logger.info(f"Task {task_id} revoked")
            return True
        except Exception as e:
            logger.error("Failed to revoke task %s (%s)", task_id, type(e).__name__)
            return False
    
    def get_queue_length(self, queue_name: str = 'celery') -> int:
        """Get number of tasks in queue"""
        try:
            with self.celery_app.connection() as conn:
                client = conn.channel().client
                length = client.llen(queue_name)
                return length or 0
        except Exception as e:
            logger.error("Failed to get queue length (%s)", type(e).__name__)
            return 0
    
    def clear_queue(self, queue_name: str = 'celery') -> bool:
        """Clear all tasks from queue"""
        try:
            with self.celery_app.connection() as conn:
                client = conn.channel().client
                client.delete(queue_name)
            logger.info(f"Queue {queue_name} cleared")
            return True
        except Exception as e:
            logger.error("Failed to clear queue (%s)", type(e).__name__)
            return False


class AsyncTaskManager:
    """
    Manages async tasks within the bot
    """
    
    def __init__(self):
        self.tasks = {}
        # Construction is synchronous in Bot.__init__; Python 3.14 no longer
        # creates a policy loop on demand. Tasks bind to the active loop when
        # create_task is called.
        self.loop = None
    
    def create_task(self, coro, task_id: str = None):
        """Create an async task"""
        if not task_id:
            task_id = str(id(coro))
        
        self.loop = asyncio.get_running_loop()
        task = self.loop.create_task(coro)
        self.tasks[task_id] = task
        
        # Auto-remove when done
        task.add_done_callback(lambda t: self.tasks.pop(task_id, None))
        
        return task_id
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        if task_id in self.tasks:
            self.tasks[task_id].cancel()
            return True
        return False
    
    def get_task_status(self, task_id: str) -> Optional[str]:
        """Get task status"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if task.done():
                if task.cancelled():
                    return 'cancelled'
                if task.exception():
                    return 'failed'
                return 'completed'
            return 'running'
        return None
    
    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None):
        """Wait for a task to complete"""
        if task_id in self.tasks:
            try:
                return await asyncio.wait_for(self.tasks[task_id], timeout)
            except asyncio.TimeoutError:
                raise
        return None
    
    def get_all_tasks(self) -> Dict[str, str]:
        """Get all running tasks"""
        return {
            tid: self.get_task_status(tid)
            for tid in self.tasks
        }
