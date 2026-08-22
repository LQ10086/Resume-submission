from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from qt_core import DATA_ROOT, DB_DIR, TEMP_DIR, read_json_file


JIANGUOYUN_WEBDAV_URL = "https://dav.jianguoyun.com/dav/"
JIANGUOYUN_APP_PASSWORD_HELP_URL = "https://help.jianguoyun.com/?p=2064"
DEFAULT_REMOTE_DIR = "/ResumeQuickPaste/databases"
CREDENTIALS_PATH = DATA_ROOT / "jianguoyun_sync.json"
BACKUP_ROOT = DATA_ROOT / "backups" / "databases"
SYNC_TEMP_ROOT = TEMP_DIR / "jianguoyun_sync"


class WebDavError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SyncCredentials:
    login: str
    password: str
    remote_dir: str = DEFAULT_REMOTE_DIR
    hostname: str = JIANGUOYUN_WEBDAV_URL

    @classmethod
    def from_dict(cls, raw: object) -> Optional["SyncCredentials"]:
        if not isinstance(raw, dict):
            return None
        login = str(raw.get("login") or "").strip()
        password = str(raw.get("password") or "")
        if not login or not password:
            return None
        return cls(
            login=login,
            password=password,
            remote_dir=normalize_remote_dir(raw.get("remote_dir")),
            hostname=str(raw.get("hostname") or JIANGUOYUN_WEBDAV_URL).strip() or JIANGUOYUN_WEBDAV_URL,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": "jianguoyun_webdav",
            "hostname": self.hostname,
            "login": self.login,
            "password": self.password,
            "remote_dir": normalize_remote_dir(self.remote_dir),
        }


def normalize_remote_dir(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return DEFAULT_REMOTE_DIR
    parts = [part for part in text.split("/") if part]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def remote_directory_path(value: object) -> str:
    directory = normalize_remote_dir(value)
    return "/" if directory == "/" else directory.rstrip("/") + "/"


def load_credentials() -> Optional[SyncCredentials]:
    try:
        with CREDENTIALS_PATH.open("r", encoding="utf-8-sig") as handle:
            return SyncCredentials.from_dict(json.load(handle))
    except (OSError, json.JSONDecodeError):
        return None


def save_credentials(credentials: SyncCredentials) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = credentials.to_dict()
    payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
    with CREDENTIALS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def credential_path() -> Path:
    return CREDENTIALS_PATH


def remote_child(directory: str, filename: str) -> str:
    directory = normalize_remote_dir(directory)
    return directory.rstrip("/") + "/" + Path(filename).name


class JianguoyunWebDavClient:
    def __init__(self, credentials: SyncCredentials, timeout: int = 30) -> None:
        self.credentials = credentials
        self.timeout = timeout
        self.hostname = credentials.hostname.rstrip("/") + "/"
        token = f"{credentials.login}:{credentials.password}".encode("utf-8")
        self.authorization = "Basic " + base64.b64encode(token).decode("ascii")

    def _url(self, remote_path: str) -> str:
        raw_path = str(remote_path or "/").strip().replace("\\", "/")
        path = normalize_remote_dir(raw_path)
        if raw_path.endswith("/") and path != "/":
            path += "/"
        return self.hostname + quote(path.lstrip("/"), safe="/")

    def _request(
        self,
        method: str,
        remote_path: str,
        data: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
        ok: tuple[int, ...] = (200,),
    ) -> bytes:
        request_headers = {
            "Authorization": self.authorization,
            "User-Agent": "ResumeQuickPaste/1.0",
        }
        request_headers.update(headers or {})
        request = Request(self._url(remote_path), data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.getcode()
                body = response.read()
        except HTTPError as exc:
            body = exc.read()
            if exc.code in ok:
                return body
            if exc.code == 401:
                raise WebDavError(
                    "坚果云 WebDAV 认证失败（HTTP 401）。请确认账号填写坚果云注册邮箱，"
                    "密码填写在坚果云“账户信息 → 安全选项 → 第三方应用管理”生成的第三方应用密码，"
                    "不是网页登录密码。",
                    exc.code,
                ) from exc
            detail = body.decode("utf-8", errors="replace").strip()
            suffix = f"：{detail[:200]}" if detail else ""
            raise WebDavError(f"坚果云 WebDAV 返回 HTTP {exc.code}{suffix}", exc.code) from exc
        except URLError as exc:
            raise WebDavError(f"无法连接坚果云 WebDAV：{exc.reason}") from exc
        if status not in ok:
            raise WebDavError(f"坚果云 WebDAV 返回 HTTP {status}", status)
        return body

    def _propfind(self, remote_path: str, depth: str) -> bytes:
        body = b'<?xml version="1.0" encoding="utf-8"?><propfind xmlns="DAV:"><allprop/></propfind>'
        return self._request(
            "PROPFIND",
            remote_path,
            data=body,
            headers={"Depth": depth, "Content-Type": "text/xml; charset=utf-8"},
            ok=(200, 207),
        )

    def exists(self, remote_path: str) -> bool:
        try:
            self._propfind(remote_path, "0")
            return True
        except WebDavError as exc:
            if exc.status == 404:
                return False
            raise

    def ensure_directory(self, remote_dir: str) -> None:
        current = ""
        parts = [part for part in normalize_remote_dir(remote_dir).strip("/").split("/") if part]
        if not parts:
            return
        for part in parts:
            current += "/" + part
            directory = remote_directory_path(current)
            if self.exists(directory):
                continue
            try:
                self._request("MKCOL", directory, ok=(200, 201, 405))
            except WebDavError as exc:
                if exc.status != 405:
                    raise

    def list_json_files(self, remote_dir: str) -> list[str]:
        body = self._propfind(remote_directory_path(remote_dir), "1")
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise WebDavError("无法解析坚果云目录列表。") from exc
        files: list[str] = []
        for response in root.findall(".//{DAV:}response"):
            if response.find(".//{DAV:}collection") is not None:
                continue
            href = response.findtext("{DAV:}href") or ""
            path = unquote(urlparse(href).path).rstrip("/")
            name = Path(path).name
            if name.lower().endswith(".json") and name not in files:
                files.append(name)
        return sorted(files)

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        data = local_path.read_bytes()
        self._request(
            "PUT",
            remote_path,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            ok=(200, 201, 204),
        )

    def download_file(self, remote_path: str, local_path: Path) -> None:
        data = self._request("GET", remote_path, ok=(200,))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)


def test_credentials(credentials: SyncCredentials) -> None:
    client = JianguoyunWebDavClient(credentials)
    client.ensure_directory(credentials.remote_dir)
    client.list_json_files(credentials.remote_dir)


def local_database_files() -> list[Path]:
    return sorted(path for path in DB_DIR.glob("*.json") if path.is_file())


def validate_database_file(path: Path) -> None:
    try:
        read_json_file(path)
    except ValueError as exc:
        raise ValueError(f"{path.name} 不是有效资料库：{exc}") from exc


def upload_local_databases(credentials: SyncCredentials) -> list[str]:
    files = local_database_files()
    if not files:
        raise ValueError("本地没有可上传的 JSON 资料库。")
    client = JianguoyunWebDavClient(credentials)
    client.ensure_directory(credentials.remote_dir)
    uploaded: list[str] = []
    for path in files:
        validate_database_file(path)
        client.upload_file(path, remote_child(credentials.remote_dir, path.name))
        uploaded.append(path.name)
    return uploaded


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _backup_local_databases() -> Optional[Path]:
    files = local_database_files()
    if not files:
        return None
    backup_dir = BACKUP_ROOT / _timestamp()
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in files:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def download_cloud_databases(credentials: SyncCredentials) -> tuple[list[str], Optional[Path]]:
    client = JianguoyunWebDavClient(credentials)
    client.ensure_directory(credentials.remote_dir)
    names = client.list_json_files(credentials.remote_dir)
    if not names:
        raise ValueError("云端目录里没有可下载的 JSON 资料库。")

    download_dir = SYNC_TEMP_ROOT / _timestamp()
    download_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for name in names:
        local_path = download_dir / Path(name).name
        client.download_file(remote_child(credentials.remote_dir, name), local_path)
        validate_database_file(local_path)
        downloaded.append(local_path)

    backup_dir = _backup_local_databases()
    DB_DIR.mkdir(parents=True, exist_ok=True)
    for path in downloaded:
        shutil.copy2(path, DB_DIR / path.name)
    return [path.name for path in downloaded], backup_dir
