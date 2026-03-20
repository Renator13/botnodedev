#!/bin/bash
# BotNode State of the Art Documentation Application Script
# This script applies documentation standards to the entire project

set -e  # Exit on error

echo "========================================="
echo "BOTNODE STATE OF THE ART DOCUMENTATION"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="/home/ubuntu/botnode_unified"
BACKUP_DIR="${PROJECT_ROOT}/backup_$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${PROJECT_ROOT}/documentation_application.log"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Step 1: Backup existing README files
log "Step 1: Backing up existing documentation..."
find "$PROJECT_ROOT" -name "README*" -type f | while read file; do
    rel_path="${file#$PROJECT_ROOT/}"
    backup_path="$BACKUP_DIR/${rel_path//\//_}"
    cp "$file" "$backup_path"
    log "  Backed up: $rel_path"
done

# Step 2: Apply new README
log "Step 2: Applying new README..."
cp "${PROJECT_ROOT}/README_STATE_OF_THE_ART.md" "${PROJECT_ROOT}/README.md"
log "  Applied: README_STATE_OF_THE_ART.md → README.md"

# Step 3: Create directory structure documentation
log "Step 3: Creating directory structure documentation..."
cat > "${PROJECT_ROOT}/DIRECTORY_STRUCTURE.md" << 'EOF'
# BotNode Directory Structure

## 🏗️ Project Organization

```
botnode_unified/
├── 📁 .git/                    # Git repository
├── 📁 skills_developed/       # 28+ developed skills
│   ├── 📁 csv-parser-v1/      # CSV processing skill
│   ├── 📁 pdf-reader-v1/      # PDF extraction skill
│   ├── 📁 google-search-v1/   # Web search skill
│   └── ... (25+ more skills)
├── 📁 static/                 # Static assets
│   ├── 📁 assets/             # Images, fonts, etc.
│   ├── 📁 docs/               # Documentation files
│   └── 📁 mcp/                # Model Context Protocol
├── 📁 venv/                   # Python virtual environment
├── 📄 main.py                 # FastAPI main application
├── 📄 database.py             # Database models and operations
├── 📄 schemas.py              # Pydantic schemas
├── 📄 worker.py               # Redis queue worker
├── 📄 docker-compose.yml      # Docker orchestration
├── 📄 Dockerfile              # Backend Docker configuration
├── 📄 requirements.txt        # Python dependencies
├── 📄 README.md               # Main documentation (State of the Art)
├── 📄 README_STATE_OF_THE_ART.md # Template
├── 📄 SKILL_README_TEMPLATE.md   # Skill documentation template
├── 📄 PYTHON_DOCSTRING_TEMPLATE.md # Python doc standards
├── 📄 DIRECTORY_STRUCTURE.md  # This file
├── 📄 INVENTORY.md            # System inventory
└── 📄 apply_state_of_the_art_docs.sh # This script
```

## 📁 Core Components

### `/` (Root)
- **`main.py`**: FastAPI application with all route handlers
- **`database.py`**: SQLAlchemy models, migrations, and database operations
- **`schemas.py`**: Pydantic models for request/response validation
- **`worker.py`**: Redis RQ worker for asynchronous task processing
- **`docker-compose.yml`**: Multi-container Docker orchestration
- **`Dockerfile`**: Backend service container definition

### `/skills_developed/`
Contains 28+ independently developed skills, each with:
- `main.py` - FastAPI skill application
- `Dockerfile` - Skill container definition  
- `requirements.txt` - Python dependencies
- `README.md` - Skill-specific documentation (to be created)
- `/tests/` - Unit and integration tests
- `/docs/` - Skill documentation

### `/static/`
Static assets served by the web application:
- `/assets/` - Images, fonts, CSS, JavaScript
- `/docs/` - User documentation in multiple formats
- `/mcp/` - Model Context Protocol definitions
- `/library/` - Code library and examples
- `/join/` - Onboarding and registration pages

## 🔧 Development Structure

### Virtual Environment
```
venv/
├── bin/                      # Python executables
├── lib/                      # Python libraries
│   └── python3.14/
│       └── site-packages/    # Installed packages
└── pyvenv.cfg               # Virtual environment config
```

### Docker Configuration
```
# Service definitions in docker-compose.yml:
services:
  backend:     # FastAPI application (port 8000)
  redis:       # Redis queue (port 6379)
  postgres:    # PostgreSQL database (port 5432)
  caddy:       # Reverse proxy (ports 80/443)
  skill-*:     # Skill containers (ports 8001+)
```

## 📊 File Counts

```bash
# Count files by type
find . -name "*.py" | wc -l      # Python files
find . -name "*.md" | wc -l      # Markdown files
find . -name "*.yml" -o -name "*.yaml" | wc -l  # YAML files
find . -name "Dockerfile" | wc -l # Dockerfiles
find . -name "requirements.txt" | wc -l # Requirements files
```

## 🚀 Getting Started

### For Developers
1. Start with `README.md` for project overview
2. Check `DIRECTORY_STRUCTURE.md` for navigation
3. Review `PYTHON_DOCSTRING_TEMPLATE.md` for coding standards
4. Use `SKILL_README_TEMPLATE.md` for new skills

### For Contributors
1. Fork the repository
2. Create feature branch
3. Follow documentation standards
4. Submit pull request

### For Users
1. Read `README.md` for installation
2. Check `static/docs/` for user guides
3. Explore API via `http://localhost:8000/docs`

## 🔄 Maintenance

### Adding New Skills
1. Copy skill template to `skills_developed/new-skill-v1/`
2. Implement skill logic
3. Add to `INVENTORY.md`
4. Update `DIRECTORY_STRUCTURE.md`

### Updating Documentation
1. Update relevant `.md` files
2. Run documentation checks
3. Update this file if structure changes

### Code Organization Principles
- **Separation of Concerns**: Each file has single responsibility
- **Modularity**: Skills are independent and reusable
- **Documentation**: Every component is fully documented
- **Testing**: All code includes comprehensive tests
- **Configuration**: Environment-specific configs in `.env`

## 📈 Evolution

This structure has evolved from:
1. **MVP Phase**: Basic 3-skill system
2. **Expansion Phase**: 28+ skills developed
3. **Unification Phase**: Consolidated from 80+ directories
4. **Documentation Phase**: Current state (State of the Art)

Future improvements planned:
- [ ] Automated documentation generation
- [ ] API client libraries
- [ ] More skill categories
- [ ] Enhanced monitoring

---

*Last updated: $(date +%Y-%m-%d)*  
*Maintained by: BotNode CTO (Gus)*
EOF

log "  Created: DIRECTORY_STRUCTURE.md"

# Step 4: Create skill READMEs from template
log "Step 4: Creating skill READMEs..."
find "${PROJECT_ROOT}/skills_developed" -maxdepth 1 -type d -name "*-v1" | while read skill_dir; do
    skill_name=$(basename "$skill_dir" | sed 's/-v1$//')
    
    # Check if README already exists
    if [ ! -f "${skill_dir}/README.md" ]; then
        cp "${PROJECT_ROOT}/SKILL_README_TEMPLATE.md" "${skill_dir}/README.md"
        
        # Replace template variables
        sed -i "s/{Skill Name}/${skill_name}/g" "${skill_dir}/README.md"
        sed -i "s/{skill-name}/${skill_name}/g" "${skill_dir}/README.md"
        
        # Try to extract category from skill files
        category="data_processing"
        if grep -q "category" "${skill_dir}/main.py" 2>/dev/null; then
            category=$(grep -i "category" "${skill_dir}/main.py" | head -1 | sed "s/.*['\"]\([^'\"]*\)['\"].*/\1/" || echo "data_processing")
        fi
        
        sed -i "s/{Category}/${category}/g" "${skill_dir}/README.md"
        
        # Set default port based on skill name hash
        port_base=8000
        port_offset=$(echo "$skill_name" | md5sum | tr -dc '0-9' | head -c 3)
        port=$((port_base + (port_offset % 100)))
        sed -i "s/{XXXX}/${port}/g" "${skill_dir}/README.md"
        
        # Set default price
        price="0.5"
        sed -i "s/{X} TCK/${price} TCK/g" "${skill_dir}/README.md"
        
        log "  Created README for: ${skill_name} (category: ${category}, port: ${port})"
    else
        log "  Skipped (exists): ${skill_name}/README.md"
    fi
done

# Step 5: Create CONTRIBUTING.md
log "Step 5: Creating CONTRIBUTING.md..."
cat > "${PROJECT_ROOT}/CONTRIBUTING.md" << 'EOF'
# Contributing to BotNode

Thank you for your interest in contributing to BotNode! This document provides guidelines and instructions for contributing to the project.

## 🎯 Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

## 🚀 Getting Started

### Prerequisites
- Python 3.14+
- Docker and Docker Compose
- Git
- Basic understanding of FastAPI and Redis

### Development Environment Setup

1. **Fork and Clone**
   ```bash
   # Fork the repository on GitHub
   # Clone your fork
   git clone https://github.com/YOUR-USERNAME/botnode_unified.git
   cd botnode_unified
   
   # Add upstream remote
   git remote add upstream https://github.com/botnode-io/core.git
   ```

2. **Set Up Environment**
   ```bash
   # Create virtual environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Install dependencies
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # Development dependencies
   
   # Set up pre-commit hooks
   pre-commit install
   ```

3. **Run Services**
   ```bash
   # Start Redis and PostgreSQL
   docker-compose up -d redis postgres
   
   # Run the application
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   
   # Run worker
   python -m worker
   ```

## 📋 Contribution Workflow

### 1. Find an Issue
- Check [GitHub Issues](https://github.com/botnode-io/core/issues)
- Look for issues tagged `good-first-issue` or `help-wanted`
- Discuss your approach in the issue comments before starting

### 2. Create a Branch
```bash
# Sync with upstream
git fetch upstream
git checkout main
git merge upstream/main

# Create feature branch
git checkout -b feature/description-of-change
# or
git checkout -b fix/description-of-bug
# or
git checkout -b docs/description-of-docs
```

### 3. Make Changes
- Follow our [Python Documentation Standards](PYTHON_DOCSTRING_TEMPLATE.md)
- Write tests for new functionality
- Update documentation as needed
- Keep commits focused and atomic

### 4. Test Your Changes
```bash
# Run tests
pytest

# Run type checking
mypy --strict --ignore-missing-imports .

# Run linters
flake8 .
black --check .
isort --check-only .

# Run documentation checks
interrogate --ignore-init-method --ignore-module --ignore-private .
```

### 5. Commit Your Changes
```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add new skill for data visualization

- Implement data visualization processor
- Add tests for visualization functions
- Update API documentation
- Fixes #123"

# Push to your fork
git push origin feature/description-of-change
```

### 6. Create Pull Request
1. Go to your fork on GitHub
2. Click "Compare & pull request"
3. Fill out the PR template
4. Request review from maintainers
5. Address review comments

## 🧪 Testing Guidelines

### Unit Tests
- Place tests in `tests/` directory
- Use `pytest` framework
- Follow Arrange-Act-Assert pattern
- Aim for >80% code coverage

```python
def test_skill_execution():
    # Arrange
    processor = SkillProcessor()
    input_data = {"test": "data"}
    
    # Act
    result = processor.execute("test_skill", input_data)
    
    # Assert
    assert result["status"] == "success"
    assert "processed" in result
```

### Integration Tests
- Test interactions between components
- Use test databases (SQLite in-memory)
- Mock external APIs
- Test error conditions

### Performance Tests
- Include benchmarks for critical paths
- Test with realistic data sizes
- Monitor memory usage and response times

## 📝 Documentation Standards

### Code Documentation
- All public functions must have Google-style docstrings
- Include type hints for all parameters and return values
- Provide examples for complex functions
- Document exceptions that can be raised

### Skill Documentation
- Each skill must have a complete README.md
- Follow [SKILL_README_TEMPLATE.md](SKILL_README_TEMPLATE.md)
- Include API reference with examples
- Document configuration options

### Project Documentation
- Keep README.md up to date
- Update DIRECTORY_STRUCTURE.md when adding files
- Add to INVENTORY.md for new components

## 🎨 Code Style

### Python
- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Use [Black](https://github.com/psf/black) for formatting
- Use [isort](https://github.com/PyCQA/isort) for imports
- Maximum line length: 88 characters

### Imports Order
```python
# Standard library
import os
import sys
from typing import Dict, List

# Third-party
from fastapi import FastAPI
from pydantic import BaseModel

# Local
from .database import Session
from .models import User
```

### Naming Conventions
- **Variables**: `snake_case`
- **Functions**: `snake_case()`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private**: `_private_method()`

## 🔧 Skill Development

### Creating a New Skill
1. Copy template from `skill_template/`
2. Implement skill logic in `main.py`
3. Add tests in `tests/`
4. Create `Dockerfile`
5. Write `README.md`
6. Add to skills registry

### Skill Requirements
- Must have health check endpoint (`/healthz`)
- Must handle errors gracefully
- Must include comprehensive logging
- Must be stateless (use Redis for state)
- Must have timeout protection

### Skill API Contract
```python
# Request
{
    "input_data": {
        # Skill-specific input
    },
    "options": {
        # Optional configuration
    }
}

# Response
{
    "result": {
        # Processed output
    },
    "processing_time_ms": 150,
    "status": "success"
}
```

## 🚨 Pull Request Guidelines

### PR Title Format
```
type(scope): description

Types:
- feat: New feature
- fix: Bug fix
- docs: Documentation
- style: Formatting
- refactor: Code restructuring
- test: Adding tests
- chore: Maintenance
```

### PR Description Template
```markdown
## Description
Brief description of changes

## Changes
- Change 1
- Change 2
- Change 3

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Documentation updated

## Related Issues
Fixes #123
Related to #456

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] Tests added/updated
```

### Review Process
1. **Automated Checks**: CI must pass
2. **Code Review**: At least one maintainer approval
3. **Documentation Review**: Docs must be updated
4. **Testing Review**: Tests must be comprehensive
5. **Merge**: Squash and merge with descriptive message

## 🐛 Bug Reports

### Reporting Bugs
1. Check if bug already reported
2. Use bug report template
3. Include steps to reproduce
4. Add error messages and logs
5. Specify environment details