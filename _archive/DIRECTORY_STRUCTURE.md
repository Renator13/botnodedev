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
