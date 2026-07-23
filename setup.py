from setuptools import setup, find_packages

setup(
    name="advanced-ai-automation-pipeline",
    version="0.4.4",
    description="Python Agentic AI QA Pipeline with GUI and reuse-aware Playwright generation",
    packages=find_packages(include=["qa_pipeline", "qa_pipeline.*"]),
    python_requires=">=3.11,<3.14",
    install_requires=[
        "pydantic>=2.7,<3",
        "python-dotenv>=1.0,<2",
        "requests>=2.32,<3",
        "fastapi>=0.115,<1",
        "uvicorn[standard]>=0.30,<1",
        "python-multipart>=0.0.9,<1",
        "pypdf>=4.2,<6",
        "python-docx>=1.1,<2",
        "openpyxl>=3.1,<4",
    ],
    entry_points={"console_scripts": ["qa-pipeline=qa_pipeline.cli:main"]},
)
