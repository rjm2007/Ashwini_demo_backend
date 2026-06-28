from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AI service configuration from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = ""
    sqs_queue_url: str = ""
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "warranty_chunks"
    openai_api_key: str = ""
    small_model: str = "gpt-5.4-mini"
    large_model: str = "gpt-5.5"
    embedding_dims: int = 1536
    bm25_vocab_size: int = 262144

    LLM_PRICE_TABLE: dict = {
        "gpt-5.4-mini": {"prompt": 0.150, "completion": 0.600},
        "gpt-5.5": {"prompt": 2.50, "completion": 10.00},
    }
    enable_contextual_retrieval: bool = True
    enable_reranker: bool = True
    reranker_candidates: int = 20
    # openai | none
    reranker_provider: str = "openai"
    docling_url: str = "http://docling:5001"
    docling_serve_url: str = "http://docling:5001"
    parser_primary: str = "docling_structured"
    enable_section_classification: bool = True
    enable_schema_pipeline: bool = True
    enable_vehicle_llm_fallback: bool = True
    gate_heavy_on_certify: bool = True
    schema_max_text_chars: int = 40000
    ocr_method: str = "auto"
    textract_poll_interval: int = 3
    textract_timeout: int = 600

    # Phase upgrades (safe defaults: new behavior on, can disable per flag)
    enable_parent_child: bool = True
    enable_structured_reasoning: bool = True
    enable_retrieval_quality: bool = True
    enable_query_decomposition: bool = True
    retrieval_score_threshold: float = 0.01
    retrieval_min_chunks: int = 3
    retrieval_retry_top_k: int = 50
    strict_metadata_filters: bool = False


settings = Settings()
