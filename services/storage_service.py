import uuid

from config.settings import get_settings


def save_file(file_bytes: bytes, filename: str) -> str:
    unique_name = f"{uuid.uuid4()}_{filename}"
    upload_dir = get_settings().upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / unique_name

    with open(path, "wb") as f:
        f.write(file_bytes)

    return str(path)
