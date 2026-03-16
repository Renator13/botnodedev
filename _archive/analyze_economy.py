#!/usr/bin/env python3
"""
Análisis rápido para identificar código económico propietario
"""
import os
import re

def analyze_file(filepath):
    """Analiza archivo para contenido económico"""
    with open(filepath, 'r') as f:
        content = f.read()
    
    economic_patterns = [
        r'balance\s*[+-]=',  # Modificaciones balance
        r'reputation_score',  # Scoring
        r'strikes\s*\+',      # Strike system
        r'price_tck',         # Pricing en TICKs
        r'escrow',            # Sistema escrow
        r'transaction',       # Transacciones
        r'fee.*%',            # Comisiones
        r'tax',               # Impuestos
        r'Decimal\(".*"\)',   # Operaciones monetarias
    ]
    
    economic_lines = []
    for i, line in enumerate(content.split('\n'), 1):
        for pattern in economic_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                economic_lines.append((i, line.strip()))
                break
    
    return economic_lines

def main():
    print("=== ANÁLISIS CÓDIGO ECONÓMICO PROPRIETARIO ===\n")
    
    files_to_analyze = [
        'main.py',
        'models.py', 
        'stripe_future.py',
        'skill_orchestrator.py',
        'worker.py'
    ]
    
    total_economic_lines = 0
    proprietary_files = []
    
    for filename in files_to_analyze:
        if os.path.exists(filename):
            print(f"\n📊 {filename}:")
            economic_lines = analyze_file(filename)
            
            if economic_lines:
                proprietary_files.append(filename)
                total_economic_lines += len(economic_lines)
                print(f"  ❌ {len(economic_lines)} líneas económicas identificadas")
                for line_num, line in economic_lines[:3]:  # Mostrar primeras 3
                    print(f"    L{line_num}: {line}")
                if len(economic_lines) > 3:
                    print(f"    ... y {len(economic_lines)-3} más")
            else:
                print(f"  ✅ Sin código económico identificado")
    
    print(f"\n=== RESUMEN ===")
    print(f"Archivos con economía: {len(proprietary_files)}")
    print(f"Líneas económicas totales: {total_economic_lines}")
    print(f"\nArchivos propietarios identificados:")
    for f in proprietary_files:
        print(f"  - {f}")
    
    # Skills avanzados (asumir todos excepto básicos)
    basic_skills = ['csv-parser', 'pdf-reader', 'google-search']
    all_skills = [d for d in os.listdir('skills_developed') if os.path.isdir(os.path.join('skills_developed', d))]
    advanced_skills = [s for s in all_skills if not any(basic in s for basic in basic_skills)]
    
    print(f"\nSkills avanzados propietarios: {len(advanced_skills)}")
    for skill in advanced_skills[:5]:
        print(f"  - {skill}")
    if len(advanced_skills) > 5:
        print(f"  ... y {len(advanced_skills)-5} más")

if __name__ == "__main__":
    main()
