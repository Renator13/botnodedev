# Python Documentation Standards
## State of the Art Docstrings for BotNode

## 📋 Overview

This document defines the documentation standards for all Python code in the BotNode project. Following these standards ensures consistency, enables automatic documentation generation, and helps maintain code quality.

## 🎯 Principles

1. **Clarity Over Brevity**: Clear explanations are more important than short docstrings
2. **Complete Coverage**: Every public function, class, and module must be documented
3. **Type Hints Required**: All function signatures must include type hints
4. **Examples Included**: Where helpful, include usage examples
5. **Google Style**: Follow Google Python Style Guide for docstring format

## 📝 Docstring Formats

### Module-Level Docstrings
```python
"""
BotNode Core Engine - Main FastAPI Application

This module implements the sovereign A2A marketplace backend with:
- Node registration and verification
- Skill marketplace operations
- Task execution with escrow
- Reputation system management

Author: BotNode Team
Version: 1.0.0
Status: Production (80% operational)
License: MIT
Repository: https://github.com/botnode-io/core

Example:
    >>> from botnode.core import BotNodeEngine
    >>> engine = BotNodeEngine()
    >>> result = engine.process_request(request_data)

Note:
    This module requires Redis and PostgreSQL connections to be established
    before use. See the setup() function for initialization.

See Also:
    - `botnode.database`: Database models and operations
    - `botnode.queue`: Redis queue management
    - `botnode.skills`: Skill execution framework
"""
```

### Class Docstrings
```python
class SkillProcessor:
    """Processor for executing BotNode skills with validation and caching.
    
    This class handles the complete lifecycle of skill execution including:
    1. Input validation and sanitization
    2. Skill selection and parameter binding
    3. Execution with timeout protection
    4. Result caching and return
    
    Attributes:
        redis_client (Redis): Redis connection for caching and queueing
        skill_registry (Dict[str, Skill]): Registry of available skills
        cache_ttl (int): Time-to-live for cached results in seconds
        max_timeout (int): Maximum execution time in seconds
        
    Example:
        >>> processor = SkillProcessor(redis_url="redis://localhost:6379")
        >>> result = processor.execute(
        ...     skill_id="csv_parser",
        ...     input_data={"csv": "a,b,c\n1,2,3"},
        ...     options={"delimiter": ","}
        ... )
        >>> print(result["processed_rows"])
        1
        
    Note:
        All skill executions are logged for audit purposes. Sensitive data
        should be encrypted before passing to the processor.
        
    Raises:
        SkillNotFoundError: When requested skill ID is not registered
        ValidationError: When input data fails validation
        TimeoutError: When skill execution exceeds max_timeout
    """
    
    def __init__(self, redis_url: str, cache_ttl: int = 300, max_timeout: int = 30):
        """Initialize the SkillProcessor with Redis connection and configuration.
        
        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379/0")
            cache_ttl: Time-to-live for cached results in seconds. Defaults to 300.
            max_timeout: Maximum execution time per skill in seconds. Defaults to 30.
            
        Raises:
            RedisConnectionError: If Redis connection cannot be established
            ConfigurationError: If invalid configuration values are provided
        """
        # Implementation
```

### Function/Method Docstrings
```python
def execute_skill(
    skill_id: str,
    input_data: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
    priority: str = "normal"
) -> Dict[str, Any]:
    """Execute a registered skill with given input and options.
    
    This function handles the complete execution flow:
    1. Validates skill_id exists in registry
    2. Sanitizes and validates input_data
    3. Checks cache for identical previous executions
    4. Executes skill with timeout protection
    5. Caches result for future identical requests
    
    Args:
        skill_id: Unique identifier of the skill to execute
        input_data: Dictionary containing skill-specific input data
        options: Optional dictionary of execution options. Defaults to None.
            Supported options:
            - timeout: Override default execution timeout
            - cache: Enable/disable result caching
            - validate: Enable/disable input validation
        priority: Execution priority ("low", "normal", "high"). Defaults to "normal".
    
    Returns:
        Dictionary containing:
            - result: Skill execution output
            - processing_time_ms: Execution time in milliseconds
            - cached: Boolean indicating if result was from cache
            - skill_metadata: Metadata about the executed skill
        
    Raises:
        SkillNotFoundError: If skill_id is not registered
        ValidationError: If input_data fails validation
        ExecutionError: If skill execution fails
        TimeoutError: If execution exceeds timeout
        
    Example:
        >>> result = execute_skill(
        ...     skill_id="sentiment_analyzer",
        ...     input_data={"text": "I love this product!"},
        ...     options={"language": "en", "detailed": True},
        ...     priority="high"
        ... )
        >>> print(result["result"]["sentiment"])
        'positive'
        
    Note:
        High priority requests may bypass cache even if identical request
        exists. Use sparingly for time-sensitive operations.
        
    See Also:
        - `register_skill`: Register new skills in the system
        - `list_skills`: Get available skills with metadata
        - `get_skill_health`: Check health status of specific skill
    """
    # Implementation
```

### Type Aliases and Constants
```python
from typing import Dict, List, Optional, Union
from datetime import datetime
from pydantic import BaseModel

# Type aliases with documentation
NodeID = str
"""Unique identifier for a BotNode node (32-character hex string)."""

SkillID = str
"""Unique identifier for a skill (lowercase with underscores)."""

TCKAmount = float
"""Amount of Tick tokens with up to 8 decimal places precision."""

Timestamp = datetime
"""ISO 8601 formatted timestamp with timezone information."""

# Constants with documentation
DEFAULT_TIMEOUT_SECONDS: int = 30
"""Default timeout for skill execution in seconds."""

MAX_CACHE_SIZE: int = 10000
"""Maximum number of cached results to store in memory."""

SUPPORTED_LANGUAGES: List[str] = ["en", "es", "fr", "de", "ja"]
"""List of language codes supported by multilingual skills."""

# Pydantic models with field documentation
class SkillRequest(BaseModel):
    """Request model for skill execution.
    
    Attributes:
        skill_id: Unique identifier of the skill to execute
        input_data: Skill-specific input parameters
        options: Optional execution configuration
        callback_url: URL to POST results when execution completes
    """
    
    skill_id: SkillID = Field(
        ...,
        description="Unique identifier of the skill to execute",
        example="csv_parser",
        min_length=3,
        max_length=50,
        regex=r"^[a-z][a-z0-9_]*$"
    )
    
    input_data: Dict[str, Any] = Field(
        ...,
        description="Skill-specific input parameters as key-value pairs",
        example={"csv_data": "a,b,c\n1,2,3", "has_header": True}
    )
    
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional execution configuration options",
        example={"timeout": 60, "cache": True, "priority": "high"}
    )
    
    callback_url: Optional[str] = Field(
        default=None,
        description="URL to POST results when execution completes (webhook)",
        example="https://api.your-service.com/webhooks/skill-result"
    )
```

## 🔧 Tools and Automation

### Auto-generating Documentation
```bash
# Generate HTML documentation with pdoc
pdoc --html --output-dir docs/ botnode/

# Generate API reference with pydoc-markdown
pydoc-markdown -I . --render-toc > API_REFERENCE.md

# Type checking with mypy
mypy --strict --ignore-missing-imports botnode/

# Linting with flake8 and docstring checking
flake8 --docstring-convention google botnode/
```

### Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        
  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort
        
  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        additional_dependencies: [flake8-docstrings]
        
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.3.0
    hooks:
      - id: mypy
        additional_dependencies: [types-redis, types-requests]
```

### Sphinx Configuration
```python
# conf.py for Sphinx documentation
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',  # For Google-style docstrings
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx_autodoc_typehints',
]

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = True
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_type_aliases = None
```

## 📚 Best Practices

### Do's
- **Do** write docstrings for all public modules, classes, and functions
- **Do** include type hints for all parameters and return values
- **Do** provide examples for complex functions
- **Do** document exceptions that can be raised
- **Do** keep docstrings up-to-date with code changes
- **Do** use descriptive variable names that reduce need for comments
- **Do** document side effects and performance characteristics

### Don'ts
- **Don't** write obvious docstrings (`"""Add two numbers."""` for `def add(a, b)`)
- **Don't** document private methods unless they're complex
- **Don't** use docstrings for implementation details that change frequently
- **Don't** write docstrings that just repeat the function name
- **Don't** forget to update docstrings when changing function signatures
- **Don't** use ambiguous terms without explanation
- **Don't** document default values that are obvious from the signature

### Examples vs Notes vs Warnings
```python
def process_data(data: List[float], method: str = "mean") -> float:
    """Process numerical data using specified statistical method.
    
    Args:
        data: List of numerical values to process
        method: Statistical method to apply. One of: "mean", "median", "mode"
    
    Returns:
        Processed result as float
        
    Example:
        >>> process_data([1, 2, 3, 4, 5], method="mean")
        3.0
        >>> process_data([1, 2, 3, 4, 100], method="median")
        3.0
        
    Note:
        For large datasets (>10,000 elements), consider using approximate
        methods for better performance.
        
    Warning:
        The "mode" method may return unexpected results for datasets with
        multiple modes or continuous data.
        
    Raises:
        ValueError: If data list is empty or method is not supported
        TypeError: If data contains non-numeric values
    """
```

## 🎨 Formatting Guidelines

### Line Length
- Keep docstrings to 88 characters per line (matching Black formatter)
- Break long descriptions at natural points
- Use hanging indents for multi-line arguments

### Section Order
1. One-line summary
2. Extended description (if needed)
3. Args section
4. Returns section  
5. Yields section (for generators)
6. Raises section
7. Examples section
8. Notes section
9. Warnings section
10. See Also section

### Markdown in Docstrings
```python
def generate_report(data: Dict[str, Any], format: str = "markdown") -> str:
    """Generate a formatted report from data.
    
    This function supports multiple output formats:
    
    - **Markdown**: For documentation and README files
    - **HTML**: For web display
    - **Plain Text**: For terminal output
    - **JSON**: For API responses
    
    Example markdown output:
    ```markdown
    # Data Report
    ## Summary
    - Total records: 150
    - Processing time: 2.3s
    - Success rate: 98.7%
    ```
    """
```

## 🔍 Quality Checklist

### Before Commit
- [ ] All public functions have complete docstrings
- [ ] Type hints are present and accurate
- [ ] Examples are provided for complex functions
- [ ] Exceptions are documented
- [ ] Docstrings follow Google style
- [ ] No spelling or grammar errors
- [ ] Cross-references are correct
- [ ] Default values are documented
- [ ] Performance characteristics are noted
- [ ] Side effects are documented

### Review Process
1. **Self-review**: Run `pydocstyle` on changed files
2. **Peer review**: Ask teammate to review documentation
3. **Automated check**: CI pipeline runs documentation checks
4. **Update references**: Ensure cross-references are still valid
5. **Test examples**: Verify examples in docstrings still work

## 📈 Metrics and Monitoring

### Documentation Coverage
```bash
# Check documentation coverage
interrogate --ignore-init-method --ignore-module --ignore-private botnode/

# Output:
# botnode/core.py: 95% (19/20)
# botnode/database.py: 100% (12/12)
# botnode/queue.py: 87% (13/15)
# Overall: 94% (44/47)
```

### Quality Metrics
- **Documentation Coverage**: Target >90%
- **Type Hint Coverage**: Target 100%
- **Example Coverage**: Target >50% for public APIs
- **Readability Score**: Flesch-Kincaid grade level < 12

## 🚀 Quick Start for New Developers

### Setting Up Documentation Environment
```bash
# Install documentation tools
pip install pdoc pydoc-markdown interrogate pydocstyle

# Generate initial documentation
pdoc --html --output-dir docs/ botnode/

# Check documentation quality
interrogate botnode/
pydocstyle botnode/

# Set up pre-commit hooks
pre-commit install
```

### Writing Your First Docstring
```python
def your_function(param1: str, param2: int = 10) -> Dict[str, Any]:
    """Brief one-line description of what the function does.
    
    Extended description explaining the function's purpose, algorithm,
    or any important details that aren't obvious from the name.
    
    Args:
        param1: Description of the first parameter
        param2: Description of the second parameter with default value
    
    Returns:
        Description of the return value structure
        
    Example:
        >>> result = your_function("test", 20)
        >>> print(result["status"])
        'success'
        
    Raises:
        ValueError: When param1 is empty string
        TypeError: When param2 is not an integer
    """
    # Your implementation here
```

## 📞 Support and Resources

### Tools
- **pdoc**: Modern Python documentation generator
- **Sphinx**: Comprehensive documentation system
- **MkDocs**: Simple markdown-based documentation
- **Read the Docs**: Hosting for documentation

### References
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [PEP 257 - Docstring Conventions](https://www.python.org/dev/peps/pep-0257/)
- [PEP 484 - Type Hints](https://www.python.org/dev/peps/pep-0484/)
- [Real Python - Documenting Python Code](https://realpython.com/documenting-python-code/)

### Training
- Internal documentation workshops
- Pair programming with documentation focus
- Code review with documentation emphasis
- Automated documentation quality checks in CI

---

**Remember: Good documentation is not a luxury, it's a necessity for maintainable code.**  
**Document today to save tomorrow's developer hours.**