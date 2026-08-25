"""Typed configuration for the bounded hybrid document parser."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentProcessingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_file_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=500, gt=0)
    max_page_width_points: float = Field(default=20_000, gt=0)
    max_page_height_points: float = Field(default=20_000, gt=0)
    render_scale: float = Field(default=2.0, gt=0)
    max_render_pixels_per_page: int = Field(default=40_000_000, gt=0)
    max_render_pixels_per_document: int = Field(default=500_000_000, gt=0)
    native_min_characters_per_page: int = Field(default=80, ge=0)
    native_max_garble_ratio: float = Field(default=0.05, ge=0, le=1)
    image_coverage_vlm_threshold: float = Field(default=0.60, ge=0, le=1)
    text_overlap_layout_threshold: float = Field(default=0.15, ge=0, le=1)
    bbox_out_of_bounds_layout_threshold: float = Field(default=0.01, ge=0, le=1)
    drawing_count_layout_threshold: int = Field(default=6, ge=0)
    vlm_max_pages_per_document: int = Field(default=50, ge=0)
    vlm_max_long_edge_pixels: int = Field(default=2048, gt=0)
    vlm_max_render_pixels_per_page: int = Field(default=4_194_304, gt=0)
    vlm_batch_size: int = Field(default=1, gt=0, le=16)
    vlm_max_concurrency: int = Field(default=1, gt=0, le=16)
    vlm_timeout_seconds: float = Field(default=60, gt=0)
    vlm_max_retries: int = Field(default=1, ge=0, le=2)
    vlm_min_confidence: float = Field(default=0.55, ge=0, le=1)
    vlm_max_response_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    parse_timeout_seconds: float = Field(default=180, gt=0)
    docling_artifacts_path: str | None = None
    fusion_bbox_iou_threshold: float = Field(default=0.45, ge=0, le=1)
    fusion_text_similarity_threshold: float = Field(default=0.70, ge=0, le=1)
    fusion_candidate_summary_characters: int = Field(default=240, gt=0, le=2000)
    quality_pass_threshold: float = Field(default=0.80, ge=0, le=1)
    quality_warning_threshold: float = Field(default=0.65, ge=0, le=1)
    quality_retry_floor: float = Field(default=0.25, ge=0, le=1)

    @model_validator(mode="after")
    def validate_pixel_budget(self) -> "DocumentProcessingConfig":
        if self.max_render_pixels_per_document < self.max_render_pixels_per_page:
            raise ValueError("document render pixel budget must cover at least one page")
        if not (
            self.quality_retry_floor
            <= self.quality_warning_threshold
            <= self.quality_pass_threshold
        ):
            raise ValueError("quality thresholds must be ordered retry <= warning <= pass")
        return self
