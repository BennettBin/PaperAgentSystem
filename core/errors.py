"""
统一错误模型

所有系统错误都使用 ProjectError 和 ErrorCode。
"""

from enum import Enum
from http import HTTPStatus
from typing import Any, Optional


class ErrorCode(str, Enum):
    """全局错误代码"""

    # 4xx 客户端错误
    INVALID_ARGUMENT = "invalid_argument"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    PERMISSION_DENIED = "permission_denied"
    UNAUTHENTICATED = "unauthenticated"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    FAILED_PRECONDITION = "failed_precondition"
    OUT_OF_RANGE = "out_of_range"
    INVALID_STATE = "invalid_state"

    # 5xx 服务器错误
    INTERNAL_ERROR = "internal_error"
    UNAVAILABLE = "unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    UNIMPLEMENTED = "unimplemented"

    # 业务逻辑错误
    WORKSPACE_QUOTA_EXCEEDED = "workspace_quota_exceeded"
    TASK_QUOTA_EXCEEDED = "task_quota_exceeded"
    INVALID_WORKSPACE_ENTRY = "invalid_workspace_entry"
    PATH_TRAVERSAL_DETECTED = "path_traversal_detected"
    UNSAFE_FILE_TYPE = "unsafe_file_type"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    SKILL_NOT_FOUND = "skill_not_found"
    TOOL_NOT_FOUND = "tool_not_found"
    MODEL_NOT_AVAILABLE = "model_not_available"
    PARSING_FAILED = "parsing_failed"
    EXTRACTION_FAILED = "extraction_failed"
    GENERATION_FAILED = "generation_failed"
    VERIFICATION_FAILED = "verification_failed"
    CLAIM_UNSUPPORTED = "claim_unsupported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SANDBOX_EXECUTION_NOT_SUPPORTED = "sandbox_execution_not_supported"


class ErrorSeverity(str, Enum):
    """错误严重级别"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    """错误分类"""

    CLIENT = "client"  # 客户端导致
    RETRYABLE = "retryable"  # 可重试
    PERMISSION = "permission"  # 权限相关
    SECURITY = "security"  # 安全问题
    SYSTEM = "system"  # 系统问题
    TIMEOUT = "timeout"  # 超时
    RESOURCE = "resource"  # 资源问题
    BUSINESS_LOGIC = "business_logic"  # 业务逻辑


class ProjectError(Exception):
    """
    项目统一异常类

    所有业务异常都应该继承此类。
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: ErrorCategory = ErrorCategory.CLIENT,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.cause = cause
        self.severity = severity
        self.category = category
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的字典"""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "severity": self.severity.value,
                "category": self.category.value,
                "details": self.details,
            }
        }

    @property
    def http_status_code(self) -> int:
        """获取对应的 HTTP 状态码"""
        # 按分类和代码映射
        status_map = {
            ErrorCode.INVALID_ARGUMENT: 400,
            ErrorCode.MISSING_REQUIRED_FIELD: 400,
            ErrorCode.NOT_FOUND: 404,
            ErrorCode.ALREADY_EXISTS: 409,
            ErrorCode.PERMISSION_DENIED: 403,
            ErrorCode.UNAUTHENTICATED: 401,
            ErrorCode.RESOURCE_EXHAUSTED: 429,
            ErrorCode.FAILED_PRECONDITION: 412,
            ErrorCode.OUT_OF_RANGE: 400,
            ErrorCode.INVALID_STATE: 400,
            ErrorCode.INTERNAL_ERROR: 500,
            ErrorCode.UNAVAILABLE: 503,
            ErrorCode.DEADLINE_EXCEEDED: 504,
            ErrorCode.UNIMPLEMENTED: 501,
            ErrorCode.WORKSPACE_QUOTA_EXCEEDED: 429,
            ErrorCode.TASK_QUOTA_EXCEEDED: 429,
            ErrorCode.INVALID_WORKSPACE_ENTRY: 400,
            ErrorCode.PATH_TRAVERSAL_DETECTED: 400,
            ErrorCode.UNSAFE_FILE_TYPE: 400,
            ErrorCode.UNSUPPORTED_OPERATION: 501,
            ErrorCode.SKILL_NOT_FOUND: 404,
            ErrorCode.TOOL_NOT_FOUND: 404,
            ErrorCode.MODEL_NOT_AVAILABLE: 503,
            ErrorCode.PARSING_FAILED: 422,
            ErrorCode.EXTRACTION_FAILED: 422,
            ErrorCode.GENERATION_FAILED: 500,
            ErrorCode.VERIFICATION_FAILED: 422,
            ErrorCode.CLAIM_UNSUPPORTED: 400,
            ErrorCode.INSUFFICIENT_EVIDENCE: 422,
            ErrorCode.SANDBOX_EXECUTION_NOT_SUPPORTED: 501,
        }
        return status_map.get(self.code, 500)

    @property
    def is_retryable(self) -> bool:
        """是否可以重试"""
        return self.category == ErrorCategory.RETRYABLE or self.code in (
            ErrorCode.UNAVAILABLE,
            ErrorCode.DEADLINE_EXCEEDED,
            ErrorCode.RESOURCE_EXHAUSTED,
        )


class ValidationError(ProjectError):
    """数据验证错误"""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            code=ErrorCode.INVALID_ARGUMENT,
            message=message,
            details=details,
            category=ErrorCategory.CLIENT,
        )


class NotFoundError(ProjectError):
    """资源不存在"""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=f"{resource_type} not found: {resource_id}",
            details={"resource_type": resource_type, "resource_id": resource_id},
            category=ErrorCategory.CLIENT,
        )


class PermissionError(ProjectError):
    """权限不足"""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            code=ErrorCode.PERMISSION_DENIED,
            message=message,
            details=details,
            category=ErrorCategory.PERMISSION,
        )


class SecurityError(ProjectError):
    """安全问题"""

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(
            code=ErrorCode.INVALID_ARGUMENT,
            message=message,
            details=details,
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
        )


class PathTraversalError(SecurityError):
    """路径穿越攻击检测"""

    def __init__(self, attempted_path: str):
        super().__init__(
            message=f"Path traversal detected: {attempted_path}",
            details={"attempted_path": attempted_path},
        )


class UnsafeFileTypeError(SecurityError):
    """不安全的文件类型"""

    def __init__(self, file_type: str, allowed_types: list[str]):
        super().__init__(
            message=f"Unsafe file type: {file_type}",
            details={"file_type": file_type, "allowed_types": allowed_types},
        )


class RetryableError(ProjectError):
    """可重试的错误"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            details=details,
            cause=cause,
            category=ErrorCategory.RETRYABLE,
        )
