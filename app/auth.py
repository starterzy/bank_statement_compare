"""登录鉴权与用户管理。

用户保存在项目根 users.json（已 gitignore），密码用 PBKDF2 加盐哈希，不落明文。
会话 token 为随机串，服务端内存保存（与 RESULTS 一致，重启后需重新登录）。

可见公司模型：
- is_admin=True → 看全部公司；
- is_admin=False → 只看 org_roots（组织树子树根）覆盖到的公司；org_roots 为空则无可见公司。
"""
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import Depends, Header, HTTPException

USER_FILE = "users.json"
_ITERATIONS = 100_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               salt.encode("utf-8"), _ITERATIONS).hex()


@dataclass
class User:
    username: str
    display_name: str = ""
    is_admin: bool = False
    org_roots: List[str] = field(default_factory=list)  # 组织树子树根（pk_org）
    salt: str = ""
    password_hash: str = ""

    def to_dict(self, include_hash: bool = False) -> dict:
        d = {"username": self.username, "display_name": self.display_name,
             "is_admin": self.is_admin, "org_roots": self.org_roots}
        if include_hash:
            d["salt"] = self.salt
            d["password_hash"] = self.password_hash
        return d

    @staticmethod
    def from_dict(d: dict) -> "User":
        return User(username=d["username"], display_name=d.get("display_name", ""),
                    is_admin=bool(d.get("is_admin", False)),
                    org_roots=list(d.get("org_roots", [])),
                    salt=d.get("salt", ""), password_hash=d.get("password_hash", ""))


class UserStore:
    def __init__(self, path: str = USER_FILE):
        self.path = path

    def _load(self) -> Dict[str, User]:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        return {u["username"]: User.from_dict(u) for u in data.get("users", [])}

    def _save(self, users: Dict[str, User]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"users": [u.to_dict(include_hash=True) for u in users.values()]},
                      f, ensure_ascii=False, indent=2)

    def list(self) -> List[User]:
        return sorted(self._load().values(), key=lambda u: u.username)

    def get(self, username: str) -> Optional[User]:
        return self._load().get(username)

    def upsert(self, user: User) -> None:
        users = self._load()
        users[user.username] = user
        self._save(users)

    def delete(self, username: str) -> bool:
        users = self._load()
        if username not in users:
            return False
        del users[username]
        self._save(users)
        return True


def set_password(user: User, password: str) -> None:
    user.salt = secrets.token_hex(16)
    user.password_hash = _hash(password, user.salt)


def verify_password(user: User, password: str) -> bool:
    return bool(user.password_hash and
                secrets.compare_digest(user.password_hash, _hash(password, user.salt)))


def ensure_seed(store: UserStore) -> None:
    """首次运行（users.json 不存在）时创建默认管理员 admin / admin123（看全部）。"""
    if os.path.exists(store.path):
        return
    admin = User(username="admin", display_name="管理员", is_admin=True, org_roots=[])
    set_password(admin, "admin123")
    store.upsert(admin)


# 会话：token -> username
SESSIONS: Dict[str, str] = {}


def create_session(username: str) -> str:
    token = secrets.token_hex(32)
    SESSIONS[token] = username
    return token


def destroy_session(token: str) -> None:
    SESSIONS.pop(token, None)


def _bearer_token(authorization: Optional[str]) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def current_user(authorization: Optional[str] = Header(None)) -> User:
    username = SESSIONS.get(_bearer_token(authorization))
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    user = UserStore().get(username)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
