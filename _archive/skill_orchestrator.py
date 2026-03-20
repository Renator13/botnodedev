#!/usr/bin/env python3
"""
🎯 DISPARO FRANCOTIRADOR - SKILL ORCHESTRATOR PARA BOTNODE

Sistema de orquestación para ejecutar skills distribuidos:
1. Recibir request HTTP → Identificar skill necesario
2. Publicar a Redis queue → Worker ejecuta skill
3. Devolver resultado con tracking

Integración seamless con backend BotNode existente.
"""

import os
import json
import uuid
import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, APIRouter
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
import redis.asyncio as redis
import httpx

# Importar componentes existentes del backend
import models
import schemas
from database import get_db

# Configuración de logging estructurado
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "module": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

class SkillCategory(str, Enum):
    """Categorías de skills para routing"""
    FAST = "fast"          # < 5 segundos
    SLOW = "slow"          # 5-30 segundos
    EXPENSIVE = "expensive" # > 30 segundos o alto coste computacional

class JobStatus(str, Enum):
    """Estados de un job de skill"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

# Configuración desde entorno
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
WORKER_POOL_SIZE = int(os.getenv("WORKER_POOL_SIZE", "5"))
DEFAULT_TIMEOUT = int(os.getenv("SKILL_TIMEOUT_SECONDS", "300"))
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_RESET_SECONDS = int(os.getenv("CIRCUIT_BREAKER_RESET_SECONDS", "60"))

# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class SkillExecuteRequest(BaseModel):
    """Request para ejecutar un skill"""
    skill_id: str = Field(..., description="ID del skill a ejecutar")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parámetros del skill")
    priority: int = Field(default=5, ge=1, le=10, description="Prioridad (1=alta, 10=baja)")
    timeout_seconds: Optional[int] = Field(default=None, description="Timeout personalizado")
    user_id: Optional[str] = Field(default=None, description="ID del usuario/organización")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos adicionales")

class SkillExecuteResponse(BaseModel):
    """Response inicial de ejecución de skill"""
    job_id: str = Field(..., description="ID único del job para tracking")
    status: JobStatus = Field(default=JobStatus.PENDING, description="Estado inicial")
    estimated_cost_tck: float = Field(..., description="Coste estimado en TCK")
    queue_position: Optional[int] = Field(default=None, description="Posición en la cola")
    estimated_wait_time: Optional[int] = Field(default=None, description="Tiempo de espera estimado (segundos)")

class JobStatusResponse(BaseModel):
    """Response con estado de un job"""
    job_id: str
    status: JobStatus
    skill_id: str
    created_at: datetime
    updated_at: datetime
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None
    actual_cost_tck: Optional[float] = None
    worker_id: Optional[str] = None

class WorkerStatus(BaseModel):
    """Estado de un worker"""
    worker_id: str
    status: str  # idle, processing, dead
    current_job_id: Optional[str] = None
    skills_processed: int = 0
    last_heartbeat: datetime
    failures: int = 0

class QueueStats(BaseModel):
    """Estadísticas de las colas"""
    queue_name: str
    pending_jobs: int
    processing_jobs: int
    avg_wait_time_seconds: float
    dead_letter_count: int

# ============================================================================
# GESTIÓN DE REDIS
# ============================================================================

class RedisManager:
    """Gestor de conexiones Redis y operaciones de cola"""
    
    def __init__(self):
        self.redis_client = None
        self.queues = {
            SkillCategory.FAST: "skills:fast",
            SkillCategory.SLOW: "skills:slow", 
            SkillCategory.EXPENSIVE: "skills:expensive"
        }
        self.dlq = "skills:dlq"
        self.job_prefix = "job:"
        self.worker_prefix = "worker:"
        self.circuit_prefix = "circuit:"
        
    async def connect(self):
        """Conectar a Redis"""
        try:
            connection_kwargs = {"url": REDIS_URL}
            if REDIS_PASSWORD:
                connection_kwargs["password"] = REDIS_PASSWORD
                
            self.redis_client = redis.Redis.from_url(**connection_kwargs)
            await self.redis_client.ping()
            logger.info("✅ Conectado a Redis")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a Redis: {e}")
            return False
    
    async def enqueue_job(self, job_id: str, skill_id: str, category: SkillCategory, 
                         priority: int, data: Dict) -> bool:
        """Publicar job a la cola apropiada"""
        try:
            queue_key = self.queues[category]
            
            # Crear job data con timestamp y prioridad
            job_data = {
                "job_id": job_id,
                "skill_id": skill_id,
                "category": category.value,
                "priority": priority,
                "data": json.dumps(data),
                "enqueued_at": datetime.utcnow().isoformat(),
                "attempts": 0
            }
            
            # Usar sorted set para prioridad (score = timestamp + prioridad inversa)
            # Prioridad 1 (alta) = score más bajo, Prioridad 10 (baja) = score más alto
            score = datetime.utcnow().timestamp() + (11 - priority) * 0.001
            
            await self.redis_client.zadd(queue_key, {json.dumps(job_data): score})
            logger.info(f"📤 Job {job_id} encolado en {queue_key} con prioridad {priority}")
            return True
        except Exception as e:
            logger.error(f"❌ Error encolando job {job_id}: {e}")
            return False
    
    async def dequeue_job(self, category: SkillCategory) -> Optional[Dict]:
        """Obtener siguiente job de la cola (con prioridad)"""
        try:
            queue_key = self.queues[category]
            
            # Obtener job con menor score (más alta prioridad)
            result = await self.redis_client.zpopmin(queue_key, count=1)
            
            if not result:
                return None
                
            job_json, score = result[0]
            job_data = json.loads(job_json)
            
            # Convertir string data de vuelta a dict
            if isinstance(job_data.get("data"), str):
                job_data["data"] = json.loads(job_data["data"])
                
            logger.info(f"📥 Job {job_data['job_id']} desencolado de {queue_key}")
            return job_data
        except Exception as e:
            logger.error(f"❌ Error desencolando job de {category}: {e}")
            return None
    
    async def store_job_result(self, job_id: str, result: Dict, status: JobStatus,
                             error: Optional[str] = None, execution_time_ms: Optional[int] = None):
        """Almacenar resultado de job en Redis (cache)"""
        try:
            job_key = f"{self.job_prefix}{job_id}"
            job_data = {
                "status": status.value,
                "result": json.dumps(result) if result else None,
                "error": error,
                "execution_time_ms": execution_time_ms,
                "completed_at": datetime.utcnow().isoformat(),
                "ttl": 3600  # 1 hora en segundos
            }
            
            await self.redis_client.hset(job_key, mapping=job_data)
            await self.redis_client.expire(job_key, 3600)
            logger.info(f"💾 Resultado almacenado para job {job_id}")
        except Exception as e:
            logger.error(f"❌ Error almacenando resultado para job {job_id}: {e}")
    
    async def get_job_result(self, job_id: str) -> Optional[Dict]:
        """Obtener resultado de job desde Redis"""
        try:
            job_key = f"{self.job_prefix}{job_id}"
            result = await self.redis_client.hgetall(job_key)
            
            if not result:
                return None
                
            # Decodificar bytes a strings
            decoded = {k.decode(): v.decode() if v else None for k, v in result.items()}
            
            # Parsear JSON del resultado
            if decoded.get("result"):
                decoded["result"] = json.loads(decoded["result"])
                
            return decoded
        except Exception as e:
            logger.error(f"❌ Error obteniendo resultado para job {job_id}: {e}")
            return None
    
    async def move_to_dlq(self, job_data: Dict, error: str):
        """Mover job fallido a Dead Letter Queue"""
        try:
            dlq_data = {
                **job_data,
                "error": error,
                "failed_at": datetime.utcnow().isoformat(),
                "original_queue": job_data.get("category")
            }
            
            await self.redis_client.lpush(self.dlq, json.dumps(dlq_data))
            logger.warning(f"⚠️ Job {job_data['job_id']} movido a DLQ: {error}")
        except Exception as e:
            logger.error(f"❌ Error moviendo job a DLQ: {e}")

# ============================================================================
# MOTOR DE PRECIOS
# ============================================================================

class PricingEngine:
    """Motor para calcular costes de skills"""
    
    # Costes base por categoría (en TCK)
    BASE_COSTS = {
        SkillCategory.FAST: 0.1,
        SkillCategory.SLOW: 0.3,
        SkillCategory.EXPENSIVE: 1.0
    }
    
    # Multiplicadores de complejidad
    COMPLEXITY_MULTIPLIERS = {
        "low": 1.0,
        "medium": 1.5,
        "high": 2.5,
        "very_high": 4.0
    }
    
    # Multiplicadores de recursos
    RESOURCE_MULTIPLIERS = {
        "cpu_low": 1.0,
        "cpu_medium": 1.3,
        "cpu_high": 1.8,
        "memory_low": 1.0,
        "memory_medium": 1.2,
        "memory_high": 1.5,
        "gpu": 3.0
    }
    
    @classmethod
    def calculate_cost(cls, skill_id: str, category: SkillCategory, 
                      parameters: Dict, skill_metadata: Dict) -> float:
        """Calcular coste total de ejecución de skill"""
        
        # Coste base por categoría
        base_cost = cls.BASE_COSTS.get(category, 0.5)
        
        # Multiplicador por complejidad
        complexity = skill_metadata.get("complexity", "medium")
        complexity_mult = cls.COMPLEXITY_MULTIPLIERS.get(complexity, 1.5)
        
        # Multiplicador por recursos requeridos
        resources = skill_metadata.get("resources", [])
        resource_mult = 1.0
        for resource in resources:
            resource_mult *= cls.RESOURCE_MULTIPLIERS.get(resource, 1.0)
        
        # Multiplicador por duración estimada
        estimated_duration = skill_metadata.get("estimated_duration_seconds", 10)
        duration_mult = max(1.0, estimated_duration / 10.0)
        
        # Multiplicador por tamaño de input
        input_size = len(json.dumps(parameters))
        size_mult = max(1.0, input_size / 1024.0)  # Normalizar por KB
        
        # Cálculo final
        total_cost = base_cost * complexity_mult * resource_mult * duration_mult * size_mult
        
        # Redondear a 2 decimales
        return round(total_cost, 2)
    
    @classmethod
    def track_usage(cls, user_id: str, skill_id: str, cost: float, db: Session):
        """Trackear uso y coste por usuario/organización"""
        # TODO: Implementar tracking en base de datos
        # Por ahora solo log
        logger.info(f"💰 Uso trackeado: user={user_id}, skill={skill_id}, cost={cost}TCK")
        
        # En una implementación real, actualizaríamos:
        # 1. Tabla de usage por usuario
        # 2. Balance del usuario
        # 3. Métricas agregadas

# ============================================================================
# CIRCUIT BREAKERS
# ============================================================================

class CircuitBreaker:
    """Circuit breaker por tipo de skill"""
    
    def __init__(self, skill_type: str, redis_manager: RedisManager):
        self.skill_type = skill_type
        self.redis = redis_manager
        self.key = f"{self.redis.circuit_prefix}{skill_type}"
    
    async def record_failure(self):
        """Registrar fallo y verificar si se activa el circuit breaker"""
        try:
            # Incrementar contador de fallos
            failures = await self.redis.redis_client.incr(self.key)
            
            # Establecer TTL si es el primer fallo
            if failures == 1:
                await self.redis.redis_client.expire(self.key, CIRCUIT_BREAKER_RESET_SECONDS)
            
            # Verificar si supera el umbral
            if failures >= CIRCUIT_BREAKER_THRESHOLD:
                logger.warning(f"🔴 Circuit breaker activado para {self.skill_type}")
                return True
                
            return False
        except Exception as e:
            logger.error(f"❌ Error en circuit breaker para {self.skill_type}: {e}")
            return False
    
    async def record_success(self):
        """Registrar éxito y resetear circuit breaker"""
        try:
            await self.redis.redis_client.delete(self.key)
            logger.info(f"🟢 Circuit breaker reseteado para {self.skill_type}")
        except Exception as e:
            logger.error(f"❌ Error reseteando circuit breaker para {self.skill_type}: {e}")
    
    async def is_open(self) -> bool:
        """Verificar si el circuit breaker está abierto"""
        try:
            failures = await self.redis.redis_client.get(self.key)
            return failures and int(failures) >= CIRCUIT_BREAKER_THRESHOLD
        except Exception as e:
            logger.error(f"❌ Error verificando circuit breaker para {self.skill_type}: {e}")
            return False

# ============================================================================
# WORKER POOL
# ============================================================================

class Worker:
    """Worker genérico que puede ejecutar cualquier skill"""
    
    def __init__(self, worker_id: str, redis_manager: RedisManager, db_session_factory):
        self.worker_id = worker_id
        self.redis = redis_manager
        self.db_session_factory = db_session_factory
        self.current_job = None
        self.is_running = False
        self.failures = 0
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        
    async def start(self):
        """Iniciar worker"""
        self.is_running = True
        logger.info(f"👷 Worker {self.worker_id} iniciado")
        
        while self.is_running:
            try:
                # Intentar obtener job de cualquier cola (prioridad: fast -> slow -> expensive)
                job_data = None
                for category in [SkillCategory.FAST, SkillCategory.SLOW, SkillCategory.EXPENSIVE]:
                    job_data = await self.redis.dequeue_job(category)
                    if job_data:
                        break
                
                if not job_data:
                    # No hay jobs, esperar antes de reintentar
                    await asyncio.sleep(1)
                    continue
                
                # Procesar job
                await self.process_job(job_data)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error en worker {self.worker_id}: {e}")
                await asyncio.sleep(5)  # Backoff en caso de error
    
    async def process_job(self, job_data: Dict):
        """Procesar un job específico"""
        job_id = job_data["job_id"]
        skill_id = job_data["skill_id"]
        category = SkillCategory(job_data["category"])
        
        logger.info(f"🔧 Worker {self.worker_id} procesando job {job_id} (skill: {skill_id})")
        
        # Actualizar estado del worker
        self.current_job = job_id
        
        try:
            # Verificar circuit breaker para este tipo de skill
            if skill_id not in self.circuit_breakers:
                self.circuit_breakers[skill_id] = CircuitBreaker(skill_id, self.redis)
            
            circuit_breaker = self.circuit_breakers[skill_id]
            
            if await circuit_breaker.is_open():
                error_msg = f"Circuit breaker abierto para skill {skill_id}"
                logger.warning(f"⚠️ {error_msg}")
                
                # Mover a DLQ
                await self.redis.move_to_dlq(job_data, error_msg)
                
                # Actualizar estado del job
                await self.redis.store_job_result(
                    job_id=job_id,
                    result=None,
                    status=JobStatus.FAILED,
                    error=error_msg
                )
                return
            
            # Obtener información del skill desde el registro
            skill_info = await self.get_skill_info(skill_id)
            if not skill_info:
                error_msg = f"Skill {skill_id} no encontrado"
                await self.redis.move_to_dlq(job_data, error_msg)
                await self.redis.store_job_result(
                    job_id=job_id,
                    result=None,
                    status=JobStatus.FAILED,
                    error=error_msg
                )
                return
            
            # Ejecutar skill
            start_time = datetime.utcnow()
            result = await self.execute_skill(skill_info, job_data["data"])
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if result.get("success"):
                # Éxito - registrar en circuit breaker
                await circuit_breaker.record_success()
                
                # Almacenar resultado
                await self.redis.store_job_result(
                    job_id=job_id,
                    result=result,
                    status=JobStatus.COMPLETED,
                    execution_time_ms=int(execution_time)
                )
                
                logger.info(f"✅ Job {job_id} completado en {execution_time:.0f}ms")
            else:
                # Fallo - registrar en circuit breaker
                await circuit_breaker.record_failure()
                
                error_msg = result.get("error", "Error desconocido")
                await self.redis.move_to_dlq(job_data, error_msg)
                
                await self.redis.store_job_result(
                    job_id=job_id,
                    result=None,
                    status=JobStatus.FAILED,
                    error=error_msg,
                    execution_time_ms=int(execution_time)
                )
                
                logger.error(f"❌ Job {job_id} falló: {error_msg}")
                
        except asyncio.TimeoutError:
            error_msg = f"Timeout ejecutando skill {skill_id}"
            await self.redis.move_to_dlq(job_data, error_msg)
            await self.redis.store_job_result(
                job_id=job_id,
                result=None,
                status=JobStatus.TIMEOUT,
                error=error_msg
            )
            logger.error(f"⏰ Job {job_id} timeout")
            
        except Exception as e:
            error_msg = f"Error inesperado: {str(e)}"
            await self.redis.move_to_dlq(job_data, error_msg)
            await self.redis.store_job_result(
                job_id=job_id,
                result=None,
                status=JobStatus.FAILED,
                error=error_msg
            )
            logger.error(f"💥 Error crítico en job {job_id}: {e}")
            
        finally:
            # Limpiar estado del worker
            self.current_job = None
    
    async def get_skill_info(self, skill_id: str) -> Optional[Dict]:
        """Obtener información del skill desde el backend existente"""
        try:
            # En una implementación real, esto consultaría la base de datos
            # o el registro de skills existente
            
            # Por ahora, simular obtención de skill info
            # TODO: Integrar con backend_skill_extensions.py
            
            # Skill info de ejemplo
            skill_info = {
                "id": skill_id,
                "name": skill_id.replace("_", " ").title(),
                "endpoint": f"http://skill-{skill_id}:8080",
                "category": "data_processing",
                "requires_internal_key": True,
                "metadata": {
                    "complexity": "medium",
                    "estimated_duration_seconds": 10,
                    "resources": ["cpu_medium"]
                }
            }
            
            return skill_info
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo info de skill {skill_id}: {e}")
            return None
    
    async def execute_skill(self, skill_info: Dict, parameters: Dict) -> Dict:
        """Ejecutar skill a través de HTTP"""
        try:
            # Headers para la request
            headers = {
                "Content-Type": "application/json",
                "User-Agent": f"BotNode-Worker/{self.worker_id}"
            }
            
            # Agregar API key interna si es necesario
            if skill_info.get("requires_internal_key"):
                headers["X-INTERNAL-API-KEY"] = os.getenv("INTERNAL_API_KEY", "botnode-internal-key")
            
            # Timeout basado en la categoría del skill
            timeout_map = {
                SkillCategory.FAST: 30,
                SkillCategory.SLOW: 120,
                SkillCategory.EXPENSIVE: 300
            }
            
            category = SkillCategory(skill_info.get("category", "slow"))
            timeout = timeout_map.get(category, 60)
            
            # Ejecutar request
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{skill_info['endpoint']}/run",
                    json=parameters,
                    headers=headers
                )
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "data": response.json(),
                        "status_code": response.status_code
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Skill returned status {response.status_code}",
                        "details": response.text,
                        "status_code": response.status_code
                    }
                    
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Skill timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error executing skill: {str(e)}"
            }
    
    async def stop(self):
        """Detener worker"""
        self.is_running = False
        logger.info(f"🛑 Worker {self.worker_id} detenido")

class WorkerPool:
    """Pool de workers gestionados"""
    
    def __init__(self, pool_size: int, redis_manager: RedisManager, db_session_factory):
        self.pool_size = pool_size
        self.redis = redis_manager
        self.db_session_factory = db_session_factory
        self.workers: List[Worker] = []
        self.tasks: List[asyncio.Task] = []
        
    async def start(self):
        """Iniciar pool de workers"""
        logger.info(f"🚀 Iniciando pool de {self.pool_size} workers")
        
        for i in range(self.pool_size):
            worker_id = f"worker-{i+1:03d}"
            worker = Worker(worker_id, self.redis, self.db_session_factory)
            self.workers.append(worker)
            
            # Crear task asíncrona para el worker
            task = asyncio.create_task(worker.start())
            self.tasks.append(task)
            
        logger.info(f"✅ Pool de workers iniciado con {len(self.workers)} workers")
    
    async def stop(self):
        """Detener todos los workers"""
        logger.info("🛑 Deteniendo pool de workers...")
        
        # Detener cada worker
        for worker in self.workers:
            await worker.stop()
        
        # Cancelar todas las tasks
        for task in self.tasks:
            task.cancel()
        
        # Esperar a que todas las tasks terminen
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        logger.info("✅ Pool de workers detenido")

# ============================================================================
# SKILL DISPATCHER (HTTP ENDPOINT)
# ============================================================================

class SkillDispatcher:
    """Dispatcher HTTP para recibir requests y encolar jobs"""
    
    def __init__(self, redis_manager: RedisManager, pricing_engine: PricingEngine):
        self.redis = redis_manager
        self.pricing = pricing_engine
        self.router = APIRouter(prefix="/api/v1/skills", tags=["skills-orchestrator"])
        
        # Registrar endpoints
        self.register_endpoints()
    
    def register_endpoints(self):
        """Registrar todos los endpoints HTTP"""
        
        @self.router.post("/execute", response_model=SkillExecuteResponse)
        async def execute_skill(
            request: SkillExecuteRequest,
            background_tasks: BackgroundTasks,
            db: Session = Depends(get_db)
        ):
            """Endpoint principal para ejecutar skills"""
            
            # Validar skill
            skill_info = await self.validate_skill(request.skill_id, db)
            if not skill_info:
                raise HTTPException(status_code=404, detail=f"Skill {request.skill_id} not found")
            
            # Determinar categoría
            category = self.determine_category(skill_info)
            
            # Calcular coste
            estimated_cost = self.pricing.calculate_cost(
                skill_id=request.skill_id,
                category=category,
                parameters=request.parameters,
                skill_metadata=skill_info.get("metadata", {})
            )
            
            # Crear job ID
            job_id = str(uuid.uuid4())
            
            # Preparar job data
            job_data = {
                "skill_id": request.skill_id,
                "parameters": request.parameters,
                "user_id": request.user_id,
                "metadata": request.metadata,
                "estimated_cost_tck": estimated_cost,
                "timeout_seconds": request.timeout_seconds or DEFAULT_TIMEOUT
            }
            
            # Encolar job (en background para no bloquear response)
            background_tasks.add_task(
                self.enqueue_job_async,
                job_id=job_id,
                skill_id=request.skill_id,
                category=category,
                priority=request.priority,
                job_data=job_data
            )
            
            # Trackear uso (solo estimación por ahora)
            if request.user_id:
                self.pricing.track_usage(request.user_id, request.skill_id, estimated_cost, db)
            
            # Calcular posición en cola (estimación)
            queue_position = await self.estimate_queue_position(category)
            estimated_wait = await self.estimate_wait_time(category, queue_position)
            
            return SkillExecuteResponse(
                job_id=job_id,
                status=JobStatus.PENDING,
                estimated_cost_tck=estimated_cost,
                queue_position=queue_position,
                estimated_wait_time=estimated_wait
            )
        
        @self.router.get("/jobs/{job_id}", response_model=JobStatusResponse)
        async def get_job_status(job_id: str):
            """Obtener estado de un job"""
            
            # Primero intentar desde Redis (cache)
            redis_result = await self.redis.get_job_result(job_id)
            
            if redis_result:
                # Job completado o fallado, retornar desde Redis
                return JobStatusResponse(
                    job_id=job_id,
                    status=JobStatus(redis_result["status"]),
                    skill_id="unknown",  # TODO: almacenar en Redis
                    created_at=datetime.fromisoformat(redis_result.get("enqueued_at", datetime.utcnow().isoformat())),
                    updated_at=datetime.fromisoformat(redis_result.get("completed_at", datetime.utcnow().isoformat())),
                    result=redis_result.get("result"),
                    error=redis_result.get("error"),
                    execution_time_ms=redis_result.get("execution_time_ms"),
                    actual_cost_tck=redis_result.get("actual_cost_tck")
                )
            
            # Si no está en Redis, podría estar aún en procesamiento
            # TODO: Consultar base de datos para jobs en progreso
            
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        @self.router.get("/queues/stats")
        async def get_queue_stats():
            """Obtener estadísticas de todas las colas"""
            stats = []
            
            for category, queue_name in self.redis.queues.items():
                try:
                    # Obtener tamaño de la cola
                    queue_size = await self.redis.redis_client.zcard(queue_name)
                    
                    # Obtener jobs en procesamiento (estimado)
                    # TODO: Implementar tracking real de jobs en procesamiento
                    
                    # Obtener tamaño de DLQ
                    dlq_size = await self.redis.redis_client.llen(self.redis.dlq)
                    
                    stats.append({
                        "queue_name": queue_name,
                        "category": category.value,
                        "pending_jobs": queue_size,
                        "processing_jobs": 0,  # TODO
                        "dead_letter_count": dlq_size,
                        "avg_wait_time_seconds": queue_size * 2  # Estimación simple
                    })
                except Exception as e:
                    logger.error(f"❌ Error obteniendo stats para {queue_name}: {e}")
            
            return stats
        
        @self.router.get("/workers/status")
        async def get_workers_status():
            """Obtener estado de todos los workers"""
            # TODO: Implementar tracking real de workers
            return {"message": "Worker status endpoint - TODO"}
        
        @self.router.post("/jobs/{job_id}/cancel")
        async def cancel_job(job_id: str):
            """Cancelar un job pendiente"""
            # TODO: Implementar cancelación de jobs
            return {"message": f"Cancel job {job_id} - TODO"}
    
    async def validate_skill(self, skill_id: str, db: Session) -> Optional[Dict]:
        """Validar que el skill existe y está disponible"""
        try:
            # TODO: Integrar con backend existente para validación real
            # Por ahora, simular validación
            
            # Consultar base de datos de skills
            skill = db.query(models.Skill).filter(models.Skill.id == skill_id).first()
            if not skill:
                return None
            
            # Convertir a dict
            skill_info = {
                "id": skill.id,
                "label": skill.label,
                "price_tck": float(skill.price_tck),
                "metadata": skill.metadata_json or {},
                "provider_id": skill.provider_id
            }
            
            return skill_info
            
        except Exception as e:
            logger.error(f"❌ Error validando skill {skill_id}: {e}")
            return None
    
    def determine_category(self, skill_info: Dict) -> SkillCategory:
        """Determinar categoría del skill basado en metadatos"""
        metadata = skill_info.get("metadata", {})
        
        # Basado en duración estimada
        estimated_duration = metadata.get("estimated_duration_seconds", 10)
        
        if estimated_duration < 5:
            return SkillCategory.FAST
        elif estimated_duration < 30:
            return SkillCategory.SLOW
        else:
            return SkillCategory.EXPENSIVE
    
    async def enqueue_job_async(self, job_id: str, skill_id: str, category: SkillCategory,
                              priority: int, job_data: Dict):
        """Encolar job de forma asíncrona"""
        success = await self.redis.enqueue_job(job_id, skill_id, category, priority, job_data)
        
        if not success:
            logger.error(f"❌ Error crítico: No se pudo encolar job {job_id}")
            # TODO: Notificar al usuario o reintentar
    
    async def estimate_queue_position(self, category: SkillCategory) -> Optional[int]:
        """Estimar posición en la cola"""
        try:
            queue_name = self.redis.queues[category]
            queue_size = await self.redis.redis_client.zcard(queue_name)
            return queue_size
        except Exception as e:
            logger.error(f"❌ Error estimando posición en cola: {e}")
            return None
    
    async def estimate_wait_time(self, category: SkillCategory, position: Optional[int]) -> Optional[int]:
        """Estimar tiempo de espera"""
        if position is None:
            return None
        
        # Estimación simple basada en categoría y posición
        avg_time_per_job = {
            SkillCategory.FAST: 2,
            SkillCategory.SLOW: 10,
            SkillCategory.EXPENSIVE: 30
        }
        
        avg_time = avg_time_per_job.get(category, 10)
        estimated_wait = position * avg_time
        
        # Considerar workers disponibles
        estimated_wait = max(1, estimated_wait // WORKER_POOL_SIZE)
        
        return estimated_wait

# ============================================================================
# INTEGRACIÓN CON BACKEND EXISTENTE
# ============================================================================

def create_skill_orchestrator_app() -> FastAPI:
    """Crear aplicación FastAPI para el skill orchestrator"""
    app = FastAPI(
        title="BotNode Skill Orchestrator",
        description="Sistema de orquestación para skills distribuidos",
        version="1.0.0"
    )
    
    # Inicializar componentes
    redis_manager