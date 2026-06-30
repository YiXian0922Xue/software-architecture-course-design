import sys
from pathlib import Path


class OCRService:
    def __init__(self, app_id: str, api_key: str, secret_key: str, sdk_path: Path):
        self.app_id = app_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.sdk_path = sdk_path

    def recognize(self, image_path: Path) -> str:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("百度 OCR 密钥未配置")
        if str(self.sdk_path) not in sys.path:
            sys.path.insert(0, str(self.sdk_path))
        try:
            from aip import AipOcr
        except ImportError as exc:
            raise RuntimeError(f"百度 OCR SDK 导入失败：{exc}") from exc
        client = AipOcr(self.app_id, self.api_key, self.secret_key)
        result = client.basicGeneral(image_path.read_bytes(), {"language_type": "CHN_ENG", "detect_direction": "true"})
        if "error_code" in result:
            raise RuntimeError(f"百度 OCR {result['error_code']}: {result.get('error_msg', '未知错误')}")
        return "\n".join(item.get("words", "") for item in result.get("words_result", []))
