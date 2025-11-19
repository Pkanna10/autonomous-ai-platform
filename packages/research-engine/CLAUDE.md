# Research Engine Package - Claude Code Configuration

**Package:** `@autonomous-ai/research-engine` **Primary Language:** Python 3.11+
**Testing:** pytest **Key Libraries:** PyMuPDF, requests, SQLAlchemy,
sentence-transformers

---

## 🎯 Package Purpose

Research paper discovery, PDF parsing, algorithm extraction, and semantic
indexing for academic CS papers from arXiv, ACM, and other sources.

---

## 🐍 Python Best Practices

### Type Hints (MANDATORY)

```python
# ✅ GOOD: Explicit type hints
from typing import Optional, List
from dataclasses import dataclass

@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: List[str]
    abstract: str
    pdf_url: Optional[str] = None

def parse_paper(pdf_path: str) -> Paper:
    """Parse PDF and extract metadata."""
    # Implementation
    pass

# ❌ BAD: No type hints
def parse_paper(pdf_path):
    pass
```

### Error Handling

```python
# ✅ GOOD: Specific exceptions
class PaperParseError(Exception):
    """Raised when PDF parsing fails."""
    pass

def parse_pdf(path: str) -> Paper:
    if not path.endswith('.pdf'):
        raise PaperParseError(f"Not a PDF file: {path}")
    try:
        # Parse logic
        pass
    except Exception as e:
        raise PaperParseError(f"Failed to parse {path}: {e}") from e
```

---

## 📄 PDF Parsing Patterns

### PyMuPDF (fitz) Basic Pattern

```python
import fitz  # PyMuPDF

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from PDF."""
    doc = fitz.open(pdf_path)
    text = ""

    for page in doc:
        text += page.get_text()

    doc.close()
    return text
```

### Structured Extraction

```python
import re
from typing import Dict, Any

def extract_paper_metadata(pdf_path: str) -> Dict[str, Any]:
    """Extract title, authors, abstract from academic paper PDF."""
    doc = fitz.open(pdf_path)
    first_page = doc[0].get_text()

    # Extract title (usually first line, large font)
    title_match = re.search(r'^(.+?)\n', first_page, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Unknown"

    # Extract abstract
    abstract_match = re.search(
        r'Abstract[:\s]+(.*?)(?:\n\n|1\s+Introduction)',
        first_page,
        re.DOTALL | re.IGNORECASE
    )
    abstract = abstract_match.group(1).strip() if abstract_match else ""

    doc.close()

    return {
        'title': title,
        'abstract': abstract,
    }
```

### Algorithm Extraction

```python
def extract_algorithms(pdf_text: str) -> List[str]:
    """Extract algorithm pseudocode blocks from paper."""
    algorithms = []

    # Match algorithm blocks
    pattern = r'Algorithm\s+\d+:.*?(?=Algorithm\s+\d+:|$)'
    matches = re.findall(pattern, pdf_text, re.DOTALL | re.IGNORECASE)

    for match in matches:
        # Clean up whitespace
        algorithm = re.sub(r'\s+', ' ', match).strip()
        algorithms.append(algorithm)

    return algorithms
```

---

## 🔍 Research Paper Discovery

### arXiv API Pattern

```python
import requests
from datetime import datetime, timedelta
from typing import List

def fetch_recent_papers(
    category: str = 'cs.DS',  # Data Structures
    days: int = 7,
    max_results: int = 50
) -> List[Dict[str, Any]]:
    """Fetch recent papers from arXiv."""
    base_url = 'http://export.arxiv.org/api/query'

    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    query = f'cat:{category} AND submittedDate:[{start_date} TO *]'

    params = {
        'search_query': query,
        'start': 0,
        'max_results': max_results,
        'sortBy': 'submittedDate',
        'sortOrder': 'descending',
    }

    response = requests.get(base_url, params=params)
    response.raise_for_status()

    # Parse XML response (use xml.etree.ElementTree)
    papers = parse_arxiv_xml(response.text)
    return papers
```

### Retry Pattern with Exponential Backoff

```python
import time
from functools import wraps

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for retrying with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.RequestException as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(f"Retry {attempt + 1}/{max_retries} after {delay}s")
                    time.sleep(delay)
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3)
def download_pdf(url: str, save_path: str) -> None:
    """Download PDF with retry logic."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    with open(save_path, 'wb') as f:
        f.write(response.content)
```

---

## 🗄️ SQLAlchemy Patterns

### Model Definition

```python
from sqlalchemy import Column, String, Integer, Date, ARRAY, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
import uuid

Base = declarative_base()

class ResearchPaper(Base):
    __tablename__ = 'research_papers'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    arxiv_id = Column(String(50), unique=True, nullable=False)
    title = Column(String, nullable=False)
    authors = Column(ARRAY(String))
    abstract = Column(String)
    pdf_url = Column(String(500))
    published_date = Column(Date)
    categories = Column(ARRAY(String))
    citation_count = Column(Integer, default=0)
    extracted_algorithms = Column(JSONB)
    complexity_analysis = Column(JSONB)
    applicability_score = Column(Float)
```

### Repository Pattern

```python
from sqlalchemy.orm import Session
from typing import Optional, List

class PaperRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_arxiv_id(self, arxiv_id: str) -> Optional[ResearchPaper]:
        return self.session.query(ResearchPaper)\
            .filter(ResearchPaper.arxiv_id == arxiv_id)\
            .first()

    def save(self, paper: ResearchPaper) -> None:
        self.session.add(paper)
        self.session.commit()

    def find_recent(self, days: int = 7, limit: int = 50) -> List[ResearchPaper]:
        cutoff_date = datetime.now() - timedelta(days=days)
        return self.session.query(ResearchPaper)\
            .filter(ResearchPaper.published_date >= cutoff_date)\
            .order_by(ResearchPaper.published_date.desc())\
            .limit(limit)\
            .all()
```

### Vector Search with pgvector

```python
from sqlalchemy import text

def find_similar_papers(
    session: Session,
    query_embedding: List[float],
    limit: int = 5
) -> List[ResearchPaper]:
    """Find papers similar to query using cosine similarity."""
    sql = text("""
        SELECT id, title, abstract,
               1 - (embedding <=> :embedding::vector) AS similarity
        FROM research_papers
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> :embedding::vector
        LIMIT :limit
    """)

    result = session.execute(
        sql,
        {'embedding': str(query_embedding), 'limit': limit}
    )

    return [row._mapping for row in result]
```

---

## 🧪 Pytest Patterns

### Fixtures

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def db_session():
    """Provide test database session."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()

@pytest.fixture
def sample_paper():
    """Provide sample research paper for testing."""
    return ResearchPaper(
        arxiv_id='2301.12345',
        title='Test Paper',
        authors=['Author One', 'Author Two'],
        abstract='This is a test abstract',
        published_date=datetime(2023, 1, 15)
    )
```

### Given-When-Then Pattern

```python
def test_should_save_paper_to_database(db_session, sample_paper):
    """
    GIVEN a valid research paper
    WHEN saving to database
    THEN should persist and be retrievable
    """
    # GIVEN - fixtures provide the setup
    repo = PaperRepository(db_session)

    # WHEN
    repo.save(sample_paper)

    # THEN
    found = repo.find_by_arxiv_id('2301.12345')
    assert found is not None
    assert found.title == 'Test Paper'
    assert len(found.authors) == 2
```

### Mocking External APIs

```python
from unittest.mock import Mock, patch

def test_should_fetch_papers_from_arxiv_api():
    """GIVEN arXiv API, WHEN fetching papers, THEN should parse correctly."""
    # GIVEN
    mock_response = Mock()
    mock_response.text = SAMPLE_ARXIV_XML
    mock_response.raise_for_status = Mock()

    with patch('requests.get', return_value=mock_response) as mock_get:
        # WHEN
        papers = fetch_recent_papers(category='cs.DS', days=7)

        # THEN
        mock_get.assert_called_once()
        assert len(papers) > 0
        assert papers[0]['title'] is not None
```

---

## 🔄 Workflow Patterns

### Daily Paper Monitoring

```python
from apscheduler.schedulers.blocking import BlockingScheduler

def daily_arxiv_monitor():
    """Daily cron job to fetch new CS papers."""
    papers = fetch_recent_papers(category='cs.DS', days=1)

    for paper_data in papers:
        # Check if already exists
        existing = repo.find_by_arxiv_id(paper_data['arxiv_id'])
        if existing:
            continue

        # Download PDF
        pdf_path = download_pdf(paper_data['pdf_url'])

        # Extract algorithms
        text = extract_text_from_pdf(pdf_path)
        algorithms = extract_algorithms(text)

        # Save to database
        paper = ResearchPaper(
            arxiv_id=paper_data['arxiv_id'],
            title=paper_data['title'],
            extracted_algorithms={'algorithms': algorithms}
        )
        repo.save(paper)

# Schedule daily at 6 AM
scheduler = BlockingScheduler()
scheduler.add_job(daily_arxiv_monitor, 'cron', hour=6)
```

---

## 📁 Key Files

| File                                | Purpose                         |
| ----------------------------------- | ------------------------------- |
| `src/arxiv/fetcher.py`              | arXiv API client                |
| `src/parser/pdf_parser.py`          | PDF text extraction             |
| `src/parser/algorithm_extractor.py` | Algorithm pseudocode extraction |
| `src/models/paper.py`               | SQLAlchemy models               |
| `src/repositories/paper_repo.py`    | Database access layer           |
| `tests/test_pdf_parser.py`          | PDF parsing tests               |
| `tests/test_arxiv_fetcher.py`       | arXiv API tests (mocked)        |

---

**Last Updated:** 2025-11-19
