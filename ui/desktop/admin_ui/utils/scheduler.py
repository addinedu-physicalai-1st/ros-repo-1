import time
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal

class TaskStatus:
    PENDING = "대기"
    MOVING = "이동 중"
    ARRIVED = "도착"
    WORKING = "작업 중"
    COMPLETED = "완료"
    FAILED = "실패"
    CHARGING = "충전 중"
    RETURNING_TO_CHARGER = "충전 복귀 중"

class TaskType:
    SERVING = "서빙"
    FOLLOW = "동행 이동"
    GUIDE = "고객 안내"
    COLLECT = "식기 수거"
    CHARGE = "충전 복귀"

class Task:
    def __init__(self, task_type, priority=1, table_id=None, robot_id=None, est_duration=60):
        self.id = f"T-{int(time.time() * 1000) % 10000:04d}"
        self.type = task_type
        self.status = TaskStatus.PENDING
        self.priority = priority
        self.table_id = table_id
        self.robot_id = robot_id
        self.req_time = datetime.now()
        self.start_time = None
        self.end_time = None
        self.est_duration = est_duration  # seconds
        self.progress = 0  # 0 to 100
        
    def to_list(self):
        duration = ""
        if self.start_time and self.end_time:
            duration = f"{(self.end_time - self.start_time).seconds}s"
        elif self.start_time:
            duration = f"{(datetime.now() - self.start_time).seconds}s"
            
        return [
            self.id,
            self.type,
            str(self.req_time.strftime("%H:%M:%S")),
            self.robot_id or "-",
            self.status,
            f"{duration} (예상:{self.est_duration}s)",
            "높음" if self.priority >= 2 else "보통"
        ]

class TaskScheduler(QObject):
    task_updated = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.pending_queue = []
        self.active_tasks = []
        self.history = []
        self.collector_robot_id = None
        self.collection_count = 0
        self.max_collection_batch = 5
        
        # New: Per-robot state tracking
        self.robots = ["R1", "R2", "R3"]
        self.robot_stats = {
            r: {"battery": 100, "status": "Idle", "is_emergency": False} for r in self.robots
        }
        # Randomize initial battery for demo
        import random
        self.robot_stats["R2"]["battery"] = 18 # Low battery case
        self.robot_stats["R3"]["battery"] = 45
        
    def add_task(self, task_type, table_id=None):
        priority = 1
        est_duration = 60
        if task_type == TaskType.COLLECT:
            priority = 2
            est_duration = 100
        elif task_type == TaskType.GUIDE:
            est_duration = 80
        elif task_type == TaskType.FOLLOW:
            est_duration = 120
            
        new_task = Task(task_type, priority, table_id, est_duration=est_duration)
        
        # Scheduling logic: Collect tasks go to the front of their priority level
        if priority >= 2:
            insert_idx = 0
            for i, t in enumerate(self.pending_queue):
                if t.priority < priority:
                    break
                insert_idx = i + 1
            self.pending_queue.insert(insert_idx, new_task)
        else:
            self.pending_queue.append(new_task)
            
        self.task_updated.emit()
        return new_task

    def manual_assign(self, task_id, robot_id):
        # Battery check
        if self.robot_stats[robot_id]["battery"] < 20:
            print(f"Assign failed: {robot_id} battery too low")
            return None

        # Check if robot is already busy
        for t in self.active_tasks:
            if t.robot_id == robot_id:
                self.complete_task(t) 
                break
                
        # Find task in queue
        target_task = None
        for t in self.pending_queue:
            if t.id == task_id:
                target_task = t
                break
        
        if target_task:
            self.pending_queue.remove(target_task)
            target_task.robot_id = robot_id
            target_task.status = TaskStatus.MOVING
            target_task.start_time = datetime.now()
            self.active_tasks.append(target_task)
            self.robot_stats[robot_id]["status"] = target_task.type
            self.task_updated.emit()
            return target_task
        return None

    def cancel_task_by_robot(self, robot_id):
        for t in self.active_tasks:
            if t.robot_id == robot_id:
                self.active_tasks.remove(t)
                t.status = TaskStatus.FAILED
                t.end_time = datetime.now()
                self.history.insert(0, t)
                self.robot_stats[robot_id]["status"] = "Idle"
                self.task_updated.emit()
                return True
        return False

    def assign_task(self, robot_id):
        if not self.pending_queue:
            return None
            
        # Battery check
        if self.robot_stats[robot_id]["battery"] < 20:
            return None
            
        # Specific Logic for Collector Exclusivity
        target_idx = -1
        
        # 1. If this robot is already the collector
        if self.collector_robot_id == robot_id:
            for idx, t in enumerate(self.pending_queue):
                if t.type == TaskType.COLLECT:
                    target_idx = idx
                    break
            if target_idx == -1:
                self.collector_robot_id = None
                self.collection_count = 0
                target_idx = 0 
        
        # 2. If this robot is NOT the collector but one exists
        elif self.collector_robot_id is not None:
            for idx, t in enumerate(self.pending_queue):
                if t.type != TaskType.COLLECT:
                    target_idx = idx
                    break
            if target_idx == -1: return None
            
        # 3. If no collector exists yet
        else:
            if self.pending_queue[0].type == TaskType.COLLECT:
                self.collector_robot_id = robot_id
                self.collection_count = 0
            target_idx = 0

        if target_idx == -1 or target_idx >= len(self.pending_queue):
            return None
            
        # Battery prediction (Simple: Every task needs at least 5% battery)
        if self.robot_stats[robot_id]["battery"] < 25: 
             # Skip if it's guide/serving which might take more
             if self.pending_queue[target_idx].type in [TaskType.SERVING, TaskType.GUIDE]:
                 return None

        task = self.pending_queue.pop(target_idx)
        task.robot_id = robot_id
        task.status = TaskStatus.MOVING
        task.start_time = datetime.now()
        self.active_tasks.append(task)
        self.robot_stats[robot_id]["status"] = task.type
        
        if task.type == TaskType.COLLECT:
            self.collection_count += 1
            
        self.task_updated.emit()
        return task

    def complete_task(self, task):
        if task in self.active_tasks:
            self.active_tasks.remove(task)
            was_collector = (task.robot_id == self.collector_robot_id and task.type == TaskType.COLLECT)
            
            task.status = TaskStatus.COMPLETED
            task.end_time = datetime.now()
            task.progress = 100
            self.history.insert(0, task)
            self.robot_stats[task.robot_id]["status"] = "Idle"
            
            if was_collector:
                collection_exists = any(t.type == TaskType.COLLECT for t in self.pending_queue)
                if not collection_exists or self.collection_count >= self.max_collection_batch:
                    self.collector_robot_id = None
                    self.collection_count = 0
            
            self.task_updated.emit()

    def update_progress(self):
        # 1. Update Active Tasks
        for task in self.active_tasks:
            rid = task.robot_id
            if task.type == TaskType.CHARGE:
                # Charging logic: Refill battery
                if self.robot_stats[rid]["battery"] < 100:
                    self.robot_stats[rid]["battery"] = min(100.0, self.robot_stats[rid]["battery"] + 2.0)
                    task.progress = self.robot_stats[rid]["battery"]
                    task.status = TaskStatus.CHARGING
                else:
                    self.complete_task(task)
            else:
                # Standard task logic: Normal progress and battery drain
                if task.progress < 100:
                    task.progress += (100 / task.est_duration)
                    if self.robot_stats[rid]["battery"] > 0:
                        self.robot_stats[rid]["battery"] -= 0.1
                    
                    if task.progress >= 40 and task.status == TaskStatus.MOVING:
                        task.status = TaskStatus.ARRIVED
                    if task.progress >= 60 and task.status == TaskStatus.ARRIVED:
                        task.status = TaskStatus.WORKING
                    if task.progress >= 100:
                        self.complete_task(task)
        
        # 2. Update Idle Robots & Auto-Charge/Wait Check
        active_ids = [t.robot_id for t in self.active_tasks]
        for rid in self.robots:
            if rid not in active_ids:
                # Passive drain
                if self.robot_stats[rid]["battery"] > 0:
                    self.robot_stats[rid]["battery"] -= 0.01
                
                # Auto-charge trigger:
                # 1. Battery below 20%
                # 2. OR No pending tasks in queue
                if self.robot_stats[rid]["battery"] < 20 or not self.pending_queue:
                    # Don't re-initiate if battery is already 100% and we are just waiting
                    if self.robot_stats[rid]["battery"] < 99.9:
                        self.initiate_charging(rid)

        self.task_updated.emit()

    def initiate_charging(self, robot_id):
        # Check if already charging
        for t in self.active_tasks:
            if t.robot_id == robot_id and t.type == TaskType.CHARGE:
                return
                
        charge_task = Task(TaskType.CHARGE, priority=3, robot_id=robot_id, est_duration=50)
        charge_task.status = TaskStatus.RETURNING_TO_CHARGER
        charge_task.start_time = datetime.now()
        self.active_tasks.append(charge_task)
        self.robot_stats[robot_id]["status"] = "Charging"
        self.task_updated.emit()
