#!/bin/bash
echo "=== SCRIPT DE LIMPIEZA DUPLICADOS BOTNODE ==="
echo "NO EJECUTAR SIN REVISIÓN - SOLO PARA REFERENCIA"
echo ""

echo "DIRECTORIOS A ELIMINAR (DUPLICADOS):"
echo ""

# 1. Backups viejos
echo "1. BACKUPS ANTIGUOS:"
echo "   rm -rf /home/ubuntu/.openclaw_backup_1771884585/botnode*"
echo "   rm -rf /home/ubuntu/.openclaw_backup_2026-02-23/botnode_mvp"
echo "   rm -rf /home/ubuntu/.openclaw_corrupto/workspace/botnode*"
echo ""

# 2. Legacy data
echo "2. LEGACY DATA:"
echo "   rm -rf /home/ubuntu/GusAI_FINAL_BACKUP/legacy_data/botnode*"
echo "   rm -rf /home/ubuntu/temp_memoria/legacy_data/botnode*"
echo "   rm -rf /home/ubuntu/rescate_gus/.openclaw/botnode*"
echo ""

# 3. Directorios temporales
echo "3. TEMPORALES:"
echo "   rm -rf /home/ubuntu/clawd/botnode_mvp"
echo "   rm -rf /home/ubuntu/proyectos/botnode/botnode-web-final"
echo ""

echo "=== ESTRUCTURA FINAL RECOMENDADA ==="
echo ""
echo "/home/ubuntu/botnode_unified/          # Código core"
echo "├── skills_developed/                  # 28+ skills"
echo "├── INVENTORY.md                       # Inventario"
echo "└── cleanup_duplicates.sh              # Este script"
echo ""
echo "/home/ubuntu/botnode_recovery/         # Diagnóstico"
echo "├── scripts/                           # Scripts recuperación"
echo "├── skills_inventory.md                # Lista skills"
echo "└── estado_actual.md                   # Estado sistema"
echo ""
echo "/var/www/botnode_v2/                   # Web estática"
echo ""
echo "=== FIN DEL SCRIPT ==="
echo ""
echo "NOTA: Revisar cada directorio antes de eliminar."
echo "      Algunos pueden contener configuraciones únicas."
