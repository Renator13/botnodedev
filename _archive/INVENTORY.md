# INVENTARIO BOTNODE UNIFICADO
## Fecha: 2026-02-25
## Estado: Sistema 80% operativo

## 🏗️ ESTRUCTURA

### 1. CORE (Backup 22/02)
- **Ubicación:** `/home/ubuntu/botnode_unified/`
- **Origen:** `.openclaw_backup_2026-02-23/botnode_mvp_backup_20260222_212413/`
- **Estado:** Funcional (backend + 3 skills operativos)

### 2. SKILLS DESARROLLADOS (28+)
- **Ubicación:** `/home/ubuntu/botnode_unified/skills_developed/`
- **Origen:** `.openclaw_corrupto/workspace/new_skills/` y `botnode_additional/`
- **Total:** 28+ skills documentados

### 3. DOCKER CONFIGURACIÓN
- **Containers activos:** 6/14
- **Skills operativos:** 3/5 (csv-parser, pdf-reader, google-search)
- **Redis:** Docker container
- **PostgreSQL:** Host system (v16)

## 🔧 COMPONENTES OPERATIVOS

### ✅ FUNCIONANDO:
1. **Backend FastAPI** - `localhost:8000`
2. **Redis** - Container Docker
3. **3 Skills básicos** - Puertos 8001-8003
4. **Caddy proxy** - `https://botnode.io/api/*` y `/v1/*`
5. **Web estática** - "Coming Soon"

### ⚠️ CONFIGURACIÓN:
1. **PostgreSQL host** - Acceso roto (usa SQLite fallback)
2. **Docker network** - Corregida (skills conectados)
3. **Skills adicionales** - Parados pero imágenes disponibles

## 📁 DIRECTORIOS IMPORTANTES

### PARA SUBIR A REPO:
- `/home/ubuntu/botnode_unified/` - Código core
- `/home/ubuntu/botnode_unified/skills_developed/` - Skills (28+)
- `/home/ubuntu/botnode_recovery/` - Diagnóstico/scripts

### PARA ELIMINAR (DUPLICADOS):
- 80+ directorios desperdigados (ver lista completa)

## 🚀 DEPLOYMENT ACTUAL

### CONTAINERS:
```
botnode_mvp-backend-1    (FastAPI, puerto 8000)
botnode_mvp-redis-1      (Redis, puerto 6379)
skill-csv-parser         (puerto 8001)
skill-pdf-reader         (puerto 8002)  
skill-google-search      (puerto 8003)
```

### CONFIGURACIÓN:
- **Caddyfile:** `/etc/caddy/Caddyfile` (proxy configurado)
- **Docker network:** `botnode_mvp_default` (corregida)
- **Database:** SQLite fallback (`/app/botnode.db`)

## 📊 ESTADO PARA COMMIT

### LISTO PARA GIT:
- ✅ Código core unificado
- ✅ Skills desarrollados documentados
- ✅ Configuración Docker corregida
- ✅ Scripts de recuperación

### PENDIENTE:
- ❌ PostgreSQL configuración
- ❌ Skills adicionales (parados)
- ❌ Limpieza directorios duplicados

